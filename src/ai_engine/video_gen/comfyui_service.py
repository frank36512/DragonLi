import json
import os
import re
import time
import hashlib
import tempfile
import requests
import uuid
from urllib.parse import urlencode

try:
    from ai_engine.utils.cancel import interruptible_sleep
except ImportError:
    try:
        from src.ai_engine.utils.cancel import interruptible_sleep
    except ImportError:
        def interruptible_sleep(seconds, step=0.2):
            time.sleep(seconds)
            return False

# ComfyUI 一般是本机服务；显式绕过系统代理，防止代理设置导致连接失败
NO_PROXY = {"http": None, "https": None}
# (连接超时, 读取超时)
# ComfyUI 的 HTTP 服务与模型执行跑在同一事件循环上：模型加载/初始化期间
# 所有 HTTP 端点完全无响应。日志实测首次加载 4 分 20 秒、二次初始化仅
# Model Initializing 就要 2 分 28 秒，之后还要采样 4~5 分钟。因此读取超时
# 必须给到能"等穿"整个加载窗口的量级（5~10 分钟），否则每次忙时探测都会
# 读超时 → 在 ComfyUI 侧留下 ConnectionResetError，并触发误判。
HTTP_TIMEOUT = (15, 300)
# 生成结果可能较大，下载读取超时放宽
DOWNLOAD_TIMEOUT = (15, 600)
# /system_stats 健康哨兵：同样要能等穿模型加载窗口（5 分钟）
HEALTH_TIMEOUT = (15, 300)
# /history 轮询：单次请求最多等 10 分钟，宁可一个请求长等，
# 也不要在服务端忙时反复超时重连
POLL_TIMEOUT = (15, 600)

# 防字幕/水印：MiniMax H3 这类音视频模型倾向把台词渲染成屏幕文字，
# 长提示词末尾的一句中文禁令服从度差——注入层统一在末尾追加双语禁令，
# 并写入工作流的负向条件节点（若有）。
VIDEO_ANTI_TEXT = (
    "no subtitles, no captions, no closed captions, no on-screen text, "
    "no text overlay, no typography, no signs, no letters, no words, "
    "no watermark, no logo, "
    "无字幕, 无屏幕文字, 无文字叠加, 无水印, 无标识"
)


def sanitize_cleanup_nodes(workflow):
    """关闭 RAMCleanup 节点的激进清理参数（提交前兜底）。

    clean_processes / clean_dlls 会 trim ComfyUI 进程工作集与 DLL 句柄，
    紧接着读取 20GB 模型分片时申请不到 I/O 缓冲，报
    HostBuffer.read_file_slice failed（Windows error 1450，系统资源不足），
    且每跑完一个片段清一次 → 越往后越容易级联失败。
    外部工作流常带着这组激进默认值，这里统一关掉。
    返回被修正的参数列表（无改动返回空）。
    """
    changed = []
    for node_id, node in (workflow or {}).items():
        if not isinstance(node, dict) or node.get("class_type") != "RAMCleanup":
            continue
        inputs = node.setdefault("inputs", {})
        for key in ("clean_processes", "clean_dlls", "clean_file_cache"):
            if inputs.get(key) is not False:
                inputs[key] = False
                changed.append(f"{node_id}.{key}")
    return changed


def _with_anti_text(prompt):
    """在提示词末尾追加防字幕禁令（已以禁令结尾则不重复）。

    正面提示词中部的中文禁令（如分镜工厂的【一致性约束】行）对视频模型
    服从度不足——末尾再追加一块双语关键词，首中尾三段同时起效。
    """
    p = (prompt or "").strip()
    if not p:
        return VIDEO_ANTI_TEXT
    if p.endswith(VIDEO_ANTI_TEXT):
        return p
    return p + "\n" + VIDEO_ANTI_TEXT


_REF_DESC_HEADS = ("【参考图描述】", "reference image description")


def inject_ref_index(prompt, labels):
    """把参考图槽位映射写入视频提示词。

    MiniMaxH3ReferenceToVideo 的节点说明要求用 <Picture i> / <Video k> 标签
    引用参考输入。此前提示词只写"角色参考图/场景参考图"这类泛称，模型无法
    判断哪张图对应哪个主体，且提示词里的参考图数量常与实际传入不一致
    （剧本写了场景/道具参考图，实际只传了角色图）——这里按真实上传顺序
    生成 <Picture 1..N> 映射块，并修正数量/类型描述。
    """
    p = (prompt or "").strip()
    if not labels:
        return p
    # 修正旧的"共N张参考图"表述（LLM 自写的数量常与实际不符）
    p = re.sub(r"共\s*\d+\s*张参考图", f"共{len(labels)}张参考图", p)

    types = []
    for lb in labels:
        for key in ("角色", "场景", "道具"):
            if key in (lb or "") and key not in types:
                types.append(key)
    if types:
        # LLM 自写的"参考图类型：无"或程序模板里的"角色/场景/道具"都按实际传入修正，
        # 避免提示词宣称有实际并不存在的参考图类型
        p = re.sub(r"参考图类型[：:][^\n]*",
                   "参考图类型：" + "/".join(types) + "参考图", p)

    block_lines = [
        f"本次实际传入 {len(labels)} 张参考图，输入槽位与参考对象对应如下"
        "（下文一律用 <Picture i> 指代对应参考图）：",
    ]
    for i, lb in enumerate(labels, start=1):
        block_lines.append(f"- <Picture {i}>：{lb}")
    block_lines.append(
        "文中如出现“参考图N/图片N/reference image N”等编号，一律按上面的 "
        "<Picture i> 序号理解；")
    block_lines.append(
        "未在上面列出的参考图本次不存在，禁止当作已提供的参考图使用，"
        "相关元素仅按文本描述生成。")
    block = "\n".join(block_lines)

    lines = p.split("\n")
    for idx, ln in enumerate(lines):
        low = ln.strip().lower()
        if any(low.startswith(h) or h in low for h in _REF_DESC_HEADS):
            lines.insert(idx + 1, block)
            return "\n".join(lines)
    # 压缩版提示词没有【参考图描述】段：放到最前面，保证模型先看到索引
    return block + "\n" + p


def find_negative_conditioning_nodes(workflow):
    """沿节点 inputs 中 negative* 引用遍历，找出全部负向条件文本节点 id。

    例如 LTX 工作流：Guider.negative -> LTXVConditioning(index1) -> CLIPTextEncode。
    标题可能不叫 "negative"（如 LTX 的负向节点标题就是"CLIP文本编码"），
    因此必须按图连线识别，不能按 title 猜。
    """
    neg_ids = set()
    if not isinstance(workflow, dict):
        return neg_ids
    changed = True
    while changed:
        changed = False
        for nid, node in list(workflow.items()):
            if not isinstance(node, dict):
                continue
            for k, v in (node.get("inputs") or {}).items():
                if "negative" not in str(k).lower():
                    continue
                if isinstance(v, (list, tuple)) and v and str(v[0]) != str(nid):
                    tid = str(v[0])
                    if tid not in neg_ids:
                        neg_ids.add(tid)
                        changed = True
    return neg_ids


def inject_prompt(workflow, prompt, negative_prompt=""):
    """把提示词写入正向节点、负面词写入负向节点。

    正向节点：ToVideo 主节点 prompt / JjkText / CLIPTextEncode(非负向) /
    PrimitiveString*(title 含 prompt/提示词)——统一追加防字幕后缀。
    负向节点：沿 negative 引用识别后写入 VIDEO_ANTI_TEXT(+调用方负面词)，
    并保证正向注入永不覆盖负向节点（此前 title 不含 "negative" 时会被覆盖，
    LTX 工作流的负向约束因此完全失效）。
    返回 (positive_injected: bool, negative_ids: set)
    """
    neg_ids = find_negative_conditioning_nodes(workflow)
    # 首部禁令：MiniMaxH3 这类工作流没有负向条件通道（BasicGuider 单引导），
    # 防字幕只能靠正向提示词——长提示词里模型对开头/结尾服从度最高，
    # 因此在最前面再放一条高优先级禁令，与中部【参考图一致性约束】行、
    # 末尾 VIDEO_ANTI_TEXT 形成首中尾三段。
    # 注意必须在 _with_anti_text 追加尾部之前判断原 prompt 开头，
    # 否则短提示词前 200 字符已含尾部禁令，首部会被误判为已存在而跳过。
    head = (prompt or "")[:200]
    if "no subtitles" not in head and "无字幕" not in head:
        prompt = ("全程画面禁止出现任何文字、字幕、标语、水印，"
                  "尤其画面底部不得出现字幕条/对白文字条，台词只走音轨"
                  "（no subtitles, no captions, no on-screen text, "
                  "no text overlay, no watermark, no logo），"
                  "本约束优先级最高，贯穿全部时间段。\n" + (prompt or ""))
    full_prompt = _with_anti_text(prompt)
    effective_negative = VIDEO_ANTI_TEXT
    extra = (negative_prompt or "").strip()
    if extra and extra not in effective_negative:
        effective_negative = effective_negative + ", " + extra

    positive_injected = False
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "") or ""
        inputs = node.setdefault("inputs", {})
        title = ((node.get("_meta") or {}).get("title", "") or "").lower()
        is_neg_node = str(node_id) in neg_ids

        # 负向条件节点：写入防字幕负面词
        if is_neg_node:
            for key in ("text", "value"):
                if isinstance(inputs.get(key), str):
                    inputs[key] = effective_negative
                    print(f"Set negative prompt on node {node_id} ({class_type})")
            continue

        # 正向注入
        if "tovideo" in class_type.lower() and isinstance(inputs.get("prompt"), str):
            inputs["prompt"] = full_prompt
            positive_injected = True
            print(f"Set video prompt on node {node_id} ({class_type})")
        elif class_type == "JjkText" and isinstance(inputs.get("text"), str):
            inputs["text"] = full_prompt
            positive_injected = True
            print(f"Set video prompt on JjkText node {node_id}")
        elif class_type == "CLIPTextEncode" and isinstance(inputs.get("text"), str):
            inputs["text"] = full_prompt
            positive_injected = True
            print(f"Set video prompt on CLIPTextEncode node {node_id}")
        elif class_type.startswith("PrimitiveString") and isinstance(inputs.get("value"), str) \
                and ("prompt" in title or "提示词" in title or "positive" in title):
            inputs["value"] = full_prompt
            positive_injected = True
            print(f"Set video prompt on {class_type} node {node_id} ({title})")

    if not positive_injected:
        print("WARNING: 未找到可注入提示词的视频节点，将使用工作流内置提示词")
    _appended = not (prompt or "").strip().endswith(VIDEO_ANTI_TEXT)
    if neg_ids:
        _neg_part = (f"负向节点 {', '.join(sorted(neg_ids))} 已写入禁令词"
                     + (f"（含额外负面词 {len(extra)} 字）" if extra else ""))
    else:
        _neg_part = "该工作流无负向条件节点（仅靠正面禁令约束）"
    print(f"[防字幕] 正向禁令后缀{'已追加' if _appended else '已存在（跳过追加）'}"
          f"（提示词 {len(prompt or '')} → {len(full_prompt)} 字）；{_neg_part}")
    return positive_injected, neg_ids


def _ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


class ComfyUIService:
    def __init__(self, base_url="http://127.0.0.1:8188"):
        self.base_url = base_url.rstrip('/')
        self.client_id = str(uuid.uuid4())
        self._current_prompt_id = None
        # 最近一次生成失败的可读错误详情，供上层 UI/日志展示
        self.last_error = ""

    def interrupt(self):
        """中断当前 ComfyUI 任务（服务端停止 GPU 计算）。"""
        try:
            requests.post(
                f"{self.base_url}/interrupt",
                json={},
                proxies=NO_PROXY,
                # 中断只是"顺手通知"，不应把取消流程本身卡住几分钟
                timeout=(10, 60),
            )
            print("ComfyUI interrupt sent")
        except Exception as e:
            print(f"ComfyUI interrupt failed: {e}")

    @staticmethod
    def poll_timeout_seconds(api_config=None):
        """轮询超时秒数。

        默认 30 分钟——LTX/MiniMax 等 i2v 在消费级显卡上 12 秒片段常需
        20 分钟以上，原 20 分钟硬编码会把正常生成判成超时。
        Video 配置里的 timeout_minutes 可覆盖（如 timeout_minutes=45）。
        """
        try:
            minutes = float((api_config or {}).get("timeout_minutes") or 30)
        except (TypeError, ValueError):
            minutes = 30.0
        return max(1.0, minutes) * 60.0

    @staticmethod
    def _prepare_ref_image(ref_path, max_side=1024):
        """参考图预处理：超过 max_side 像素的先缩到 max_side 再上传。

        说明：MiniMaxH3 的 ref_image_size=match 本身会把参考图缩到生成像素面积，
        所以这一步不是提速关键（真正的大头是帧数/提示词/放大倍数），
        保留它只是为了少传几 MB、并避免个别后端按原图尺寸解码。副本写临时目录，
        不污染项目素材。
        """
        try:
            from PIL import Image
            with Image.open(ref_path) as im:
                im.load()
                w, h = im.size
                if max(w, h) <= max_side:
                    return ref_path
                scale = max_side / float(max(w, h))
                new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                im2 = im.convert("RGB").resize(new_size, Image.LANCZOS)
                key = hashlib.md5(f"{ref_path}|{os.path.getmtime(ref_path)}".encode()).hexdigest()[:12]
                out = os.path.join(tempfile.gettempdir(), f"ref_{key}_{max_side}.png")
                im2.save(out)
                print(f"Ref image downscaled: {os.path.basename(ref_path)} "
                      f"{w}x{h} -> {new_size[0]}x{new_size[1]}")
                return out
        except Exception as e:
            print(f"Ref image preprocess skipped ({type(e).__name__}): {ref_path}")
            return ref_path

    def upload_image(self, image_path, subfolder=""):
        """
        Uploads an image to ComfyUI.
        """
        url = f"{self.base_url}/upload/image"

        try:
            with open(image_path, 'rb') as f:
                files = {'image': (os.path.basename(image_path), f)}
                data = {}
                if subfolder:
                    data['subfolder'] = subfolder

                response = requests.post(
                    url, files=files, data=data,
                    timeout=HTTP_TIMEOUT, proxies=NO_PROXY
                )
                response.raise_for_status()

                result = response.json()
                # Returns: {"name": "filename.png", "subfolder": "", "type": "input"}
                return result
        except Exception as e:
            print(f"ComfyUI Upload Error: {e}")
            return None

    def queue_prompt(self, workflow):
        """
        Queues a workflow (prompt) to ComfyUI.
        """
        url = f"{self.base_url}/prompt"
        payload = {
            "prompt": workflow,
            "client_id": self.client_id
        }

        try:
            # 排队请求单独放宽读取超时：ComfyUI 的 HTTP 线程在节点执行/加载模型时
            # 会被阻塞，30s 超时会在服务端其实已排队的情况下报失败 → 重试提交重复任务。
            response = requests.post(url, json=payload, timeout=(15, 600), proxies=NO_PROXY)
            response.raise_for_status()
            return response.json()  # {"prompt_id": "..."}
        except Exception as e:
            print(f"ComfyUI Queue Error: {e}")
            return None

    def get_history(self, prompt_id):
        url = f"{self.base_url}/history/{prompt_id}"
        try:
            response = requests.get(url, timeout=POLL_TIMEOUT, proxies=NO_PROXY)
            response.raise_for_status()
            self._last_history_ok = True
            return response.json()
        except Exception as e:
            # 失败时置标志位：调用方据此区分「服务端无响应」与「任务还没进历史」。
            # 此前一律返回 {}，轮询循环完全看不出服务端已经卡死，会一直空转到超时。
            self._last_history_ok = False
            self._last_history_error = f"{type(e).__name__}: {e}"
            # 只有连接级失败（端口未监听/连接被拒）才算"失联"；
            # 读超时说明端口通、只是服务端在忙（加载模型/推理中），不能判死。
            self._last_history_unreachable = isinstance(
                e, (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout))
            print(f"ComfyUI History Error: {e}")
            return {}

    # 宽高比 → ResolutionSelector 的合法取值
    _ASPECT_COMBOS = {
        "16:9": "16:9 (Widescreen)",
        "9:16": "9:16 (Portrait Widescreen)",
        "1:1": "1:1 (Square)",
        "4:3": "4:3 (Standard)",
        "3:4": "3:4 (Portrait Standard)",
        "2:3": "2:3 (Portrait Photo)",
        "3:2": "3:2 (Photo)",
        "21:9": "21:9 (Ultrawide)",
    }

    # 目标 1080P 的像素总数（短边 = 1080），用于自动反推初始 megapixels
    # key = ResolutionSelector.aspect_ratio 枚举值，value = 目标像素
    _TARGET_1080P_PIXELS = {
        "16:9 (Widescreen)": 1920 * 1080,        # 2073600
        "9:16 (Portrait Widescreen)": 1080 * 1920,
        "1:1 (Square)": 1080 * 1080,             # 1166400
        "4:3 (Standard)": 1440 * 1080,           # 1555200
        "3:4 (Portrait Standard)": 1080 * 1440,
        "2:3 (Portrait Photo)": 1080 * 1620,     # 1749600
        "3:2 (Photo)": 1620 * 1080,
        "21:9 (Ultrawide)": 2520 * 1080,         # 2721600
    }

    @staticmethod
    def _detect_upscale_scale(workflow, cfg):
        """检测工作流的 latent 放大倍数。

        前置条件：工作流里必须存在 upscale 节点，否则强制返回 1.0。
        有放大节点时：config 显式值 > 节点内置值。
        自动推断覆盖 MiniMaxH3 / LTX / 通用 upscale 节点。
        """
        workflow_has_upscale = False
        node_scale = None  # 节点内置的放大倍数（尚未考虑 config 覆盖）

        for node in (workflow or {}).values():
            if not isinstance(node, dict):
                continue
            ct = str(node.get("class_type", ""))
            low = ct.lower()
            inp = node.get("inputs") or {}

            # MiniMaxH3 latent upscaler
            if ct == "MinimaxH3LatentUpscaler3D":
                workflow_has_upscale = True
                if "mode.scale" in inp:
                    try:
                        node_scale = float(inp["mode.scale"])
                    except (TypeError, ValueError):
                        pass
                if node_scale is None:
                    node_scale = 2.0
                break

            # LTX latent upsampler：节点本身固定 ×2（同时兼容双t/单t拼写）
            if ("ltxvlatentupsampl" in low or "ltxlatentupsampl" in low
                    or ("ltx" in low and "upsampl" in low and "latent" in low)):
                workflow_has_upscale = True
                node_scale = 2.0
                break

            # 通用 upscale 节点（排除纯模型加载器）
            if (any(k in low for k in ("upscal", "upsample", "upscale"))
                    and "loader" not in low and "load" not in low):
                for key in ("multiplier", "scale", "upscale_factor"):
                    val = inp.get(key)
                    if val is None:
                        continue
                    try:
                        s = float(val)
                        if s > 1.0:
                            workflow_has_upscale = True
                            node_scale = s
                            break
                    except (TypeError, ValueError):
                        continue
                if workflow_has_upscale:
                    break

        if not workflow_has_upscale:
            return 1.0  # 无放大节点 → 不管 config 配多少都不生效

        # 有放大节点时：config 显式值优先
        scale = (cfg or {}).get("upscale_scale")
        if scale is not None:
            try:
                s = float(scale)
                if 1.0 <= s <= 4.0:
                    return s
            except (TypeError, ValueError):
                pass

        return node_scale if node_scale else 1.0

    # 输出分辨率档位：短边像素。供 config 里用 resolution_preset 直接选档
    # （720p 在 3090 24G 上是稳定档，1080P 的 latent 采样会 OOM）
    _RESOLUTION_TIERS = {"480p": 480, "540p": 540, "720p": 720, "900p": 900, "1080p": 1080}

    @classmethod
    def _calc_init_megapixels(cls, aspect_ratio_combo, upscale_scale=2.0, short_side=1080):
        """根据目标输出分辨率 + 放大倍数，反推初始 megapixels。

        公式：initial_mp = target_pixels / upscale_scale² / 1_000_000
        upscale_scale² 是因为 latent 放大对宽和高各乘 scale → 面积乘 scale²。
        short_side: 目标短边像素（720 → 720P，1080 → 1080P）；
        非 1080 档按面积比例 (short_side/1080)² 缩放目标像素。
        返回 None 表示无法推算（未知比例），或 float。
        """
        target = cls._TARGET_1080P_PIXELS.get(aspect_ratio_combo)
        if not target:
            return None
        try:
            factor = (float(short_side) / 1080.0) ** 2
        except (TypeError, ValueError):
            factor = 1.0
        target = target * factor
        scale2 = upscale_scale ** 2
        if scale2 < 1.0:
            scale2 = 1.0
        init_mp = target / scale2 / 1_000_000
        return round(init_mp, 2)

    def _apply_extra_params(self, workflow, api_config, ratio=None, seed=None):
        """把宽高比/种子/采样步数/分辨率/放大倍数写进工作流。

        自动注入逻辑：
        - aspect_ratio  → 用户选择（必需）
        - upscale_scale → config 显式值 > 工作流节点自动检测 > 默认 1.0
        - megapixels    → config 显式值 > 根据 upscale_scale + 1080P 目标自动计算
        - sampler_steps → config 显式值
        - seed          → 调用方传入

        自动计算 megapixels 的数学：
          目标最终像素 = 1080P 按比例（短边 = 1080）
          initial_mp  = target_pixels / upscale_scale² / 1_000_000
          latent 放大对宽和高各乘 scale → 面积乘 scale²
        """
        cfg = api_config or {}
        applied = {}

        # --- 1) 宽高比 ---
        combo = None
        if ratio:
            combo = self._ASPECT_COMBOS.get(str(ratio).strip())
            if combo:
                for node in workflow.values():
                    if not isinstance(node, dict):
                        continue
                    if node.get("class_type") == "ResolutionSelector":
                        inputs = node.setdefault("inputs", {})
                        if inputs.get("aspect_ratio") != combo:
                            inputs["aspect_ratio"] = combo
                            print(f"Set ResolutionSelector aspect_ratio to {combo}")
                        # 即使工作流内置值相同也记录，便于上层/日志确认实际生效比例
                        applied["aspect_ratio"] = combo
                        break
            else:
                print(f"WARN: 未知的宽高比 {ratio}，保持工作流原值")

        # --- 2) upscale_scale：config 显式值 > 工作流节点自动检测 ---
        upscale = self._detect_upscale_scale(workflow, cfg)
        upscale_explicit = bool(cfg.get("upscale_scale"))
        if upscale_explicit:
            print(f"upscale_scale={upscale} (config 显式配置)")
        else:
            print(f"upscale_scale={upscale} (工作流节点自动推断)")

        # --- 3) megapixels：config 显式值 > resolution_preset 档位 > 1080P 自动计算 ---
        # 显存不够时把档位调到 720p（分辨率降一半，采样时间与显存都大幅下降），
        # 成片阶段再按项目目标分辨率补一次 lanczos 放大。
        _preset = str(cfg.get("resolution_preset") or "").strip().lower()
        _short_side = self._RESOLUTION_TIERS.get(_preset)
        if _short_side:
            print(f"resolution_preset={_preset} → 目标短边 {_short_side}px")

        mp = cfg.get("megapixels")
        mp_explicit = bool(mp)
        if mp_explicit:
            try:
                mp = float(mp)
            except (TypeError, ValueError):
                mp = None
        elif combo:
            mp = self._calc_init_megapixels(combo, upscale, _short_side or 1080)
            # 无放大节点时自动值可能太大（如 2.07MP 直接出 1080P），
            # 打个告警但不强行覆盖——让用户知道需要自己配 megapixels 或给工作流加 upscaler
            if mp is not None and upscale <= 1.0 and mp > 1.5:
                print(f"WARN: 工作流无 latent 放大节点，自动 megapixels={mp}MP 可能显存压力很大，"
                      f"建议在 config.json 显式设一个较低值，或给工作流添加 latent upscaler")
        else:
            mp = None  # ratio 未提供时无法自动计算

        if mp:
            try:
                mp = float(mp)
            except (TypeError, ValueError):
                mp = None
            if mp:
                for node in workflow.values():
                    if not isinstance(node, dict):
                        continue
                    if node.get("class_type") == "ResolutionSelector":
                        node.setdefault("inputs", {})["megapixels"] = mp
                        applied["megapixels"] = mp
                        source = "config" if mp_explicit else f"auto 1080P (upscale×{upscale})"
                        print(f"Set ResolutionSelector megapixels to {mp}  [{source}]")
                        break

        # --- 4) upscale_scale 写入 MiniMaxH3 latent upscaler ---
        # （LTX / 通用 upscale 节点模型本身就是固定倍率，无需注入）
        if upscale > 1.0:
            for node in workflow.values():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") == "MinimaxH3LatentUpscaler3D":
                    node.setdefault("inputs", {})["mode.scale"] = upscale
                    applied["upscale_scale"] = upscale
                    print(f"Set LatentUpscaler3D mode.scale to {upscale}")
                    break

        # --- 5) 采样步数 ---
        steps = cfg.get("sampler_steps")
        if steps:
            try:
                steps = int(steps)
            except (TypeError, ValueError):
                steps = None
            if steps:
                for node in workflow.values():
                    if not isinstance(node, dict):
                        continue
                    if node.get("class_type") == "BasicScheduler":
                        node.setdefault("inputs", {})["steps"] = steps
                        applied["steps"] = steps
                        print(f"Set BasicScheduler steps to {steps}")
                        break

        # --- 6) 随机种子 ---
        if seed is not None:
            try:
                s = int(seed)
            except (TypeError, ValueError):
                s = None
            if s is not None:
                for node in workflow.values():
                    if not isinstance(node, dict):
                        continue
                    if node.get("class_type") == "RandomNoise":
                        node.setdefault("inputs", {})["noise_seed"] = s
                        applied["seed"] = s
                        print(f"Set RandomNoise noise_seed to {s}")
                        break

        # --- 7) 显存优化：分块 VAE 解码 + 高分辨率跳过精修采样 ---
        applied.update(self._optimize_for_memory(workflow, cfg, _short_side or 1080))

        self._applied_params = applied
        return applied

    def _optimize_for_memory(self, workflow, cfg, target_short_side=1080):
        """针对高分辨率的显存优化。

        1) VAEDecode → VAEDecodeTiled：视频 VAE 解码是 1080P 的第二大显存消耗，
           分块（含时间维分块）后峰值大幅下降。
        2) hires_refine=false（或 auto 且目标 ≥1080P）时跳过第二遍精修采样：
           该采样的 latent 分辨率等于成片分辨率（1080P 即 1088x1920），
           在 24G 显存上是 OOM 的根源。跳过后先把放大的 latent 直接解码，
           成片仍是 1080P，只是少了 4 步精修（画面略软）。
        """
        applied = {}
        # 1) 分块解码（默认开启）
        tiled = cfg.get("vae_tiled")
        tiled = True if tiled is None else str(tiled).lower() not in ("false", "0", "no")
        if tiled:
            for node in workflow.values():
                if isinstance(node, dict) and node.get("class_type") == "VAEDecode":
                    node["class_type"] = "VAEDecodeTiled"
                    inp = node.setdefault("inputs", {})
                    inp.setdefault("tile_size", 512)
                    inp.setdefault("overlap", 64)
                    inp.setdefault("temporal_size", 64)
                    inp.setdefault("temporal_overlap", 8)
                    applied["vae_tiled"] = True
                    print("VAEDecode → VAEDecodeTiled（分块解码，降低显存峰值）")
                    break

        # 2) 是否跳过第二遍精修采样
        refine = str(cfg.get("hires_refine", "auto") or "auto").lower()
        if refine in ("false", "0", "no"):
            skip_refine = True
        elif refine in ("true", "1", "yes"):
            skip_refine = False
        else:  # auto：只有 1080P 档才跳，720P 保留精修（显存够且画质更好）
            try:
                skip_refine = int(target_short_side) >= 1080
            except (TypeError, ValueError):
                skip_refine = True
        if skip_refine:
            applied.update(self._bypass_refine_pass(workflow))
        return applied

    def _bypass_refine_pass(self, workflow):
        """把解码节点接到 latent 放大输出，跳过第二遍采样器。

        结构：LatentUpscaler → LTXVConcatAVLatent(视频+音频) → SamplerCustomAdvanced(第二遍) → 解码
        改为：LatentUpscaler → 视频解码；原始音频 latent → 音频解码
        """
        for sid, node in list(workflow.items()):
            if not isinstance(node, dict) or node.get("class_type") != "SamplerCustomAdvanced":
                continue
            lat = (node.get("inputs") or {}).get("latent_image")
            if not (isinstance(lat, list) and lat and str(lat[0]) in workflow):
                continue
            concat = workflow[str(lat[0])]
            if concat.get("class_type") != "LTXVConcatAVLatent":
                continue
            cin = concat.get("inputs") or {}
            video_src, audio_src = cin.get("video_latent"), cin.get("audio_latent")
            if not (isinstance(video_src, list) and isinstance(audio_src, list)):
                continue

            rewired = 0
            for cid, c in workflow.items():
                if not isinstance(c, dict):
                    continue
                ct = c.get("class_type") or ""
                if ct not in ("VAEDecode", "VAEDecodeTiled", "VAEDecodeAudio"):
                    continue
                for k, v in list((c.get("inputs") or {}).items()):
                    if isinstance(v, list) and v and str(v[0]) == sid:
                        c["inputs"][k] = list(audio_src if "Audio" in ct else video_src)
                        rewired += 1
            if rewired:
                workflow.pop(sid, None)
                print(f"跳过第二遍精修采样（重接 {rewired} 个解码节点）")
                return {"hires_refine": False, "refine_rewired": rewired}
        return {}

    def _print_param_summary(self, workflow, duration_val, ref_count):
        """打印本次实际生效的关键参数，便于逐项对比不同工作流/项目的差异。"""
        def _find(ct):
            for node in workflow.values():
                if isinstance(node, dict) and node.get("class_type") == ct:
                    return node.get("inputs") or {}
            return {}

        res = _find("ResolutionSelector")
        sched = _find("BasicScheduler")
        up = _find("MinimaxH3LatentUpscaler3D")
        noise = _find("RandomNoise")
        prim = {}
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            title = (node.get("_meta", {}) or {}).get("title", "") or ""
            if "秒" in title or "duration" in title.lower():
                prim = node.get("inputs") or {}
                break
        secs = prim.get("value", duration_val)
        try:
            secs = float(secs)
        except (TypeError, ValueError):
            pass
        frames = int(max(5, round(secs * 24)))
        print("=" * 62)
        print(f"[生成参数] 时长 {secs:.0f}s → 约 {frames} 帧(24fps)"
              f" | 分辨率 {res.get('aspect_ratio', '?')} @ {res.get('megapixels', '?')}MP"
              f" | 采样 {sched.get('steps', '?')} 步"
              f" | 放大 ×{up.get('mode.scale', '?')}"
              f" | 参考图 {ref_count} 张"
              f" | 种子 {noise.get('noise_seed', '?')}")
        print("=" * 62)

    def check_health(self):
        """检查 ComfyUI 服务端是否健康。

        返回 (是否健康, 说明)。/system_stats 返回 500 通常意味着 GPU 状态异常
        （显存耗尽/OOM 后 CUDA 上下文出错），此时排队新任务只会卡死。
        """
        try:
            r = requests.get(f"{self.base_url}/system_stats", timeout=HEALTH_TIMEOUT,
                             proxies=NO_PROXY)
        except requests.exceptions.Timeout as e:
            # 端口通但服务端忙（模型加载/推理占满事件循环）——不是失联
            self._health_busy = True
            return False, f"ComfyUI 响应超时（服务端可能正在加载模型）: {e}"
        except Exception as e:
            self._health_busy = False
            return False, f"ComfyUI 服务不可达: {type(e).__name__}: {e}"
        self._health_busy = False
        if r.status_code != 200:
            return False, (f"ComfyUI 服务异常（HTTP {r.status_code}）"
                           f"——通常是显存不足或上一单卡死，请重启 ComfyUI / 关闭其它任务后重试")
        return True, "ok"

    def is_prompt_failed(self, history, prompt_id):
        """检查 ComfyUI 记录里该任务是否已报错（快速失败，避免空转 5 分钟）。"""
        entry = history.get(prompt_id) or {}
        status = entry.get("status") or {}
        status_str = str(status.get("status_str", "")).lower()
        if status_str == "error" or (isinstance(status.get("completed"), bool)
                                     and status.get("completed") is False
                                     and status.get("status_str")):
            messages = status.get("messages") or []
            print(f"ComfyUI task reported error status: {status_str}; messages: {messages[:2]}")
            return True
        return False

    def get_prompt_error(self, history, prompt_id):
        """提取 ComfyUI 任务的人类可读错误详情（节点类型 + 异常信息），无错误返回空串。"""
        entry = history.get(prompt_id) or {}
        status = entry.get("status") or {}
        status_str = str(status.get("status_str", "")).lower()
        failed = (status_str == "error" or (isinstance(status.get("completed"), bool)
                  and status.get("completed") is False and status.get("status_str")))
        if not failed:
            return ""
        for m in (status.get("messages") or []):
            if isinstance(m, (list, tuple)) and len(m) >= 2 and m[0] == "execution_error":
                info = m[1] if isinstance(m[1], dict) else {}
                node = info.get("node_type") or info.get("node_id") or "?"
                msg = info.get("exception_message") or "未知错误"
                return f"节点 {node} 执行出错: {msg}"
        # 被外部中断（execution_interrupted）：ComfyUI 队列标志被置位。
        # 常见原因：同机其它任务抢占、显存不足被中止、手动点停止。
        # 明确写出来，避免上层把它当成"未知错误"而反复重试。
        for m in (status.get("messages") or []):
            if isinstance(m, (list, tuple)) and len(m) >= 2 and m[0] == "execution_interrupted":
                info = m[1] if isinstance(m[1], dict) else {}
                node = info.get("node_type") or info.get("node_id") or "?"
                # 措辞避开"节点"二字：上层把"节点…"判为确定性错误、不会重试
                return (f"任务被中断（execution_interrupted，停在 {node}）"
                        f"——通常是 ComfyUI 上有其它任务抢占、显存不足或被手动停止")
        return f"ComfyUI 任务状态异常: {status_str or 'unknown'}"

    def get_image_url(self, filename, subfolder="", type="output"):
        """Get the URL to download a generated image/video（参数统一编码，避免特殊字符破坏 URL）"""
        query = urlencode({
            "filename": filename,
            "subfolder": subfolder or "",
            "type": type,
        })
        return f"{self.base_url}/view?{query}"

    def _download_result(self, download_url, output_path):
        """下载生成结果到 output_path，先写 .part 再原子替换，返回 True/False。"""
        part_path = output_path + ".part"
        try:
            _ensure_parent_dir(output_path)
            response = requests.get(download_url, timeout=DOWNLOAD_TIMEOUT, proxies=NO_PROXY)
            response.raise_for_status()
            content = response.content
            if not content or len(content) < 1000:
                print(f"Downloaded content too small ({len(content) if content else 0} bytes), not ready or invalid")
                return False
            with open(part_path, 'wb') as f:
                f.write(content)
            os.replace(part_path, output_path)
            return True
        except Exception as e:
            print(f"Failed to download result: {e}")
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
            except OSError:
                pass
            return False

    def generate_video(self, image_path, prompt, output_path, api_config, text=None, voice_id=None, ratio="16:9", language="English", end_image_path=None, input_video_path=None, duration=10, ref_images=None, ref_labels=None, seed=None, negative_prompt=""):
        """
        Generate video using ComfyUI workflow.

        Args:
            image_path: Path to first-frame image (used as video starting frame)
            prompt: Video generation prompt
            output_path: Where to save the generated video
            api_config: API configuration dict
            text: Optional dialogue text for TTS
            voice_id: Optional voice ID for TTS
            ratio: Aspect ratio (16:9, 9:16, 1:1)
            language: Language for TTS
            end_image_path: Optional end frame image
            input_video_path: Optional input video for extension
            duration: Duration in seconds
            ref_images: Optional list of reference image paths (character/prop/scene) for multi-ref workflows
            ref_labels: 与 ref_images 同序的标签（如"角色「云汐」参考图"），用于提示词 <Picture i> 索引
            negative_prompt: 额外负面词（与 VIDEO_ANTI_TEXT 合并写入负向节点）

        Returns:
            Path to generated video or None
        """
        self.last_error = ""
        # OOM 标记：显存不足属"降分辨率可恢复"，由上层据此逐步下调 megapixels 重试
        self.last_oom = False
        self.last_megapixels = None
        workflow_file = api_config.get("workflow_file", "")
        if not workflow_file or not os.path.exists(workflow_file):
            print(f"Workflow file not found: {workflow_file}")
            self.last_error = f"工作流文件不存在: {workflow_file}"
            return None

        # 0. 服务端健康检查：显存不足/OOM 会让 ComfyUI 的状态接口直接 500，
        # 此时继续排队只会让任务卡死几十分钟，先快速失败并给出可执行的原因。
        health, health_msg = self.check_health()
        if not health:
            print(f"ComfyUI health check failed: {health_msg}")
            self.last_error = health_msg
            return None

        # 1. Load Workflow
        try:
            with open(workflow_file, 'r', encoding='utf-8') as f:
                workflow_template = json.load(f)
        except Exception as e:
            print(f"Failed to load workflow: {e}")
            return None

        # 2. Upload Images
        uploaded_image_name = None
        if image_path:
            upload_result = self.upload_image(image_path)
            if not upload_result:
                print("Failed to upload first-frame image to ComfyUI")
                self.last_error = "首帧图片上传 ComfyUI 失败"
                return None
            uploaded_image_name = upload_result.get("name")
            print(f"Uploaded first-frame image: {uploaded_image_name}")

        uploaded_ref_names = []
        uploaded_ref_labels = []
        if ref_images:
            for i, ref_path in enumerate(ref_images):
                if not ref_path or not os.path.exists(ref_path):
                    print(f"Reference image {i} not found: {ref_path}, skipping")
                    continue
                # 超大参考图先缩放：参考 token 数直接影响采样耗时
                up_path = self._prepare_ref_image(ref_path)
                upload_result = self.upload_image(up_path)
                if upload_result:
                    uploaded_ref_names.append(upload_result.get("name"))
                    label = ""
                    if ref_labels and i < len(ref_labels):
                        label = str(ref_labels[i] or "")
                    uploaded_ref_labels.append(label or f"参考图{i + 1}")
                    print(f"Uploaded reference image {i}: {upload_result.get('name')}"
                          + (f" ({label})" if label else ""))
                else:
                    print(f"Failed to upload reference image {i}: {ref_path}")

        # 3. Modify Workflow
        workflow = workflow_template.copy()
        # 激进内存清理节点兜底关闭：否则每跑完一个片段 trim 一次进程工作集，
        # 下次读模型分片报 HostBuffer.read_file_slice failed（error 1450）
        _fixed = sanitize_cleanup_nodes(workflow)
        if _fixed:
            print(f"RAMCleanup 激进参数已关闭: {', '.join(_fixed)}")

        # Set first-frame image to the first LoadImage node (if image_path provided)
        if uploaded_image_name:
            for node_id, node in workflow.items():
                if node.get("class_type") == "LoadImage":
                    node["inputs"]["image"] = uploaded_image_name
                    print(f"Set first LoadImage node {node_id} to {uploaded_image_name} (first frame)")
                    break

        # Set reference images.
        # 槽位映射以 ToVideo 节点的 ref_image_N 连线为准（不是 LoadImage 节点的字典顺序）；
        # 参考图不足时把多余槽位整个删掉（节点允许 min=0），
        # 而不是拿最后一张重复填充——重复图也要被 32B 视觉编码器再编一遍，白白吃时间。
        if uploaded_ref_names:
            to_video_node = None
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                ct = str(node.get("class_type", ""))
                if "tovideo" in ct.lower() and "prompt" in (node.get("inputs") or {}):
                    to_video_node = node
                    break

            # 1) 按 ToVideo 的 ref_image_N -> [LoadImage节点, 0] 映射精确填槽
            slot_nodes = []
            if to_video_node is not None:
                tv_inputs = to_video_node.get("inputs") or {}
                for i in range(9):
                    key = f"ref_images.ref_image_{i}"
                    link = tv_inputs.get(key)
                    if not isinstance(link, (list, tuple)) or len(link) < 1:
                        continue
                    src_id = str(link[0])
                    src_node = workflow.get(src_id)
                    if not isinstance(src_node, dict) or src_node.get("class_type") != "LoadImage":
                        continue
                    slot_nodes.append((i, key, src_id, src_node))

            # 工作流默认只接了 3 个 LoadImage 节点，而 MiniMaxH3 的参考槽是动态的
            # （COMFY_AUTOGROW_V3，min=0/max=9）——需要更多参考图时克隆 LoadImage 补槽。
            if slot_nodes and len(slot_nodes) < len(uploaded_ref_names):
                template = slot_nodes[0][3]
                next_slot = len(slot_nodes)
                while (len(slot_nodes) < len(uploaded_ref_names)
                       and next_slot < 9
                       and len(slot_nodes) < 9):
                    new_id = f"{slot_nodes[0][2]}_ref{next_slot}"
                    new_node = json.loads(json.dumps(template))  # 深拷贝
                    new_node.setdefault("inputs", {})["image"] = ""
                    workflow[new_id] = new_node
                    key = f"ref_images.ref_image_{next_slot}"
                    to_video_node.setdefault("inputs", {})[key] = [new_id, 0]
                    slot_nodes.append((next_slot, key, new_id, new_node))
                    print(f"Cloned LoadImage node {new_id} for ref slot {next_slot}")
                    next_slot += 1

            used_slots = []
            if slot_nodes:
                for i, key, src_id, src_node in slot_nodes:
                    if i >= len(uploaded_ref_names):
                        # 该槽位无参考图 → 删除连线，让模型少编一张图
                        to_video_node["inputs"].pop(key, None)
                        continue
                    src_node.setdefault("inputs", {})["image"] = uploaded_ref_names[i]
                    used_slots.append(i)
                    print(f"Set ref slot {i} (node {src_id}) to {uploaded_ref_names[i]}")
            else:
                # 没有 ToVideo 映射（其它工作流）：退回按 LoadImage 节点顺序填
                print(f"WARN: 当前工作流没有 ref_image_N 参考槽位，{len(uploaded_ref_names)} 张参考图"
                      "只能按 LoadImage 节点顺序填充；若工作流是 ImageToVideo（只认 first_frame/"
                      "last_frame），参考图一致性不会生效，应改用 ReferenceToVideo 工作流")
                load_image_nodes = [
                    (nid, node) for nid, node in workflow.items()
                    if isinstance(node, dict) and node.get("class_type") == "LoadImage"
                ]
                ref_idx = 0
                for nid, node in load_image_nodes:
                    current_img = node.get("inputs", {}).get("image", "")
                    if current_img == uploaded_image_name:
                        continue
                    if ref_idx < len(uploaded_ref_names):
                        node.setdefault("inputs", {})["image"] = uploaded_ref_names[ref_idx]
                        print(f"Set LoadImage node {nid} to {uploaded_ref_names[ref_idx]} (ref {ref_idx})")
                        ref_idx += 1
                    else:
                        node.setdefault("inputs", {})["image"] = uploaded_ref_names[-1]
                        print(f"Set LoadImage node {nid} to {uploaded_ref_names[-1]} (ref reused)")

        # 注入视频提示词 + 防字幕负面词——此前缺失，导致 i2v 节点
        # （如 MiniMaxH3ImageToVideo）一直使用工作流内置的测试提示词；
        # 且旧逻辑按 title 判负向，LTX 等工作流负向节点 title 不含 "negative"
        # 时会被正向提示词覆盖，负向约束完全失效——现按图连线识别负向节点。
        if prompt and prompt.strip():
            # 参考图索引：按实际上传成功的参考图生成 <Picture 1..N> 映射，
            # 修正提示词里虚报的参考图数量/类型，让模型明确对应关系
            indexed_prompt = inject_ref_index(prompt, uploaded_ref_labels)
            inject_prompt(workflow, indexed_prompt, negative_prompt=negative_prompt)

        # Set video duration (frames)；duration 可能以字符串传入，做容错转换
        try:
            duration_val = float(duration)
        except (TypeError, ValueError):
            duration_val = 10.0
        frame_count = max(1, int(duration_val * 25))  # Assuming 25fps
        print(f"Setting video duration to {duration_val}s -> {frame_count} frames")

        for node_id, node in workflow.items():
            class_type = node.get("class_type", "")
            inputs = node.get("inputs", {})
            meta = node.get("_meta", {})
            title = (meta.get("title", "") or "").strip().lower()

            # Find Length node (PrimitiveInt with title="Length")
            if "PrimitiveInt" in class_type and title == "length":
                inputs["value"] = frame_count
                print(f"Set PrimitiveInt node {node_id} (Length) value to {frame_count}")
                continue

            # MiniMax H3 等工作流：时长是秒，存在 PrimitiveFloat(title 含 duration)，
            # 由 ComfyMathExpression 换算帧数——此前未识别，导致一直用内置 15 秒
            if "PrimitiveFloat" in class_type and ("duration" in title or "秒" in title or "second" in title):
                inputs["value"] = duration_val
                print(f"Set PrimitiveFloat node {node_id} (duration) value to {duration_val}s")
                continue

            # Also check EmptyLTXVideo / LTXVEmptyLatentVideo nodes
            if "EmptyLTXVideo" in class_type or "LTXVEmptyLatentVideo" in class_type:
                if "length" in inputs and isinstance(inputs["length"], int):
                    inputs["length"] = frame_count
                    print(f"Set node {node_id} ({class_type}) length to {frame_count} frames")

        # 5. 宽高比 / 分辨率 / 采样步数 / 放大倍数 / 随机种子 —— 逐项可配
        applied = self._apply_extra_params(workflow, api_config, ratio, seed)
        self.last_megapixels = applied.get("megapixels")

        # 6. 打印本次实际生效的关键参数（便于逐项对比不同工作流/不同项目的差异）
        self._print_param_summary(workflow, duration_val, len(uploaded_ref_names))

        # 4. Queue Prompt
        print("Queuing workflow...")
        queue_res = self.queue_prompt(workflow)
        if not queue_res or "prompt_id" not in queue_res:
            print("Failed to queue prompt.")
            return None

        prompt_id = queue_res["prompt_id"]
        self._current_prompt_id = prompt_id
        print(f"Workflow queued. Prompt ID: {prompt_id}")

        # 5. Poll for Completion
        print("Waiting for generation...")
        start_time = time.time()
        timeout_s = self.poll_timeout_seconds(api_config)
        timeout_min = timeout_s / 60.0
        last_beat = start_time
        download_failures = 0
        # 服务端无响应的连续计数：单次超时可能是模型加载/显存压力导致的偶发卡顿，
        # 连续多次才判定进程已卡死，避免误杀正在正常生成的长任务。
        health_failures = 0
        history_failures = 0
        while True:
            # 超时/取消检查放在循环顶部，确保下载失败分支也能命中
            if interruptible_sleep(0):
                print("Generation cancelled by user")
                self.interrupt()
                return None
            elapsed = time.time() - start_time
            if elapsed > timeout_s:
                print("Generation timed out.")
                # 超时也要停掉服务端任务：否则 GPU 继续算完这一单，
                # 下一次重试只会排在它后面，越等越久
                self.interrupt()
                self.last_error = f"图生视频超时（{timeout_min:.0f} 分钟，已等待 {elapsed/60:.1f} 分钟）"
                final_history = self.get_history(prompt_id)
                if prompt_id in final_history:
                    print(f"DEBUG: Final history outputs: {final_history[prompt_id].get('outputs', {})}")
                return None
            # 120s 一次即可：模型加载期间每次探测都可能读超时，间隔太短只会刷噪音
            if time.time() - last_beat >= 120:
                last_beat = time.time()
                print(f"图生视频生成中... 已等待 {elapsed/60:.1f} 分钟（超时上限 {timeout_min:.0f} 分钟）", flush=True)
                # 服务端健康哨兵：显存/OOM 异常时 /system_stats 会直接 500，
                # 此时任务已卡死，继续等只是白等 —— 中断并报明确原因。
                # 只有"不可达"才累计次数判死；读取超时（服务端忙）不算失联。
                healthy, why = self.check_health()
                if not healthy:
                    if getattr(self, "_health_busy", False):
                        # 只是读取超时：端口是通的，服务端在加载模型/推理，属于正常繁忙。
                        # 之前把这种超时也算作失联，3 分钟就误杀正在跑的长任务。
                        print(f"ComfyUI 暂未响应（服务端繁忙，继续等待）: {why}", flush=True)
                        health_failures = 0
                    else:
                        health_failures += 1
                        print(f"ComfyUI 服务探测失败（第 {health_failures}/5 次）: {why}", flush=True)
                        if health_failures >= 5:
                            print(f"ComfyUI 服务连续 5 次不可达，判定进程已退出: {why}", flush=True)
                            self.interrupt()
                            self.last_error = (
                                f"ComfyUI 服务不可达（{why}）。任务可能仍在后台生成——"
                                "请先查看 ComfyUI 的 output 目录是否已产出视频，再重启 ComfyUI 后重试")
                            return None
                else:
                    health_failures = 0

            history = self.get_history(prompt_id)

            # 服务端 HTTP 卡死时（TCP 可连但不应答）轮询会一直拿到空 history，
            # 此前只能干等到 poll_timeout 才失败，白等几十分钟。连续失败即提前退出。
            if not getattr(self, "_last_history_ok", True):
                if getattr(self, "_last_history_unreachable", False):
                    history_failures += 1
                else:
                    # 读超时：端口监听正常，服务端在忙（模型加载/推理），按总超时兜底即可
                    history_failures = 0
                    print(f"ComfyUI 轮询超时（服务端繁忙，继续等待）: "
                          f"{getattr(self, '_last_history_error', '')}", flush=True)
                # 6 次（轮询间隔 10s，约 1 分钟）才判死：服务端忙碌时偶发的连接重置
                # 不应直接毁掉整段视频
                if history_failures >= 6:
                    print(f"ComfyUI 连续 {history_failures} 次不可达，判定服务已退出", flush=True)
                    self.last_error = (
                        f"ComfyUI 连接中断（{getattr(self, '_last_history_error', '')}）。"
                        "任务可能仍在后台生成——请先查看 ComfyUI 的 output 目录是否已产出视频，"
                        "再重启 ComfyUI 后重试")
                    return None
            else:
                history_failures = 0

            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})

                # Debug: Print full outputs structure on first detection
                if outputs and not hasattr(self, '_printed_outputs'):
                    print(f"DEBUG: Full outputs: {outputs}")
                    self._printed_outputs = True

                # Find video output - recursively search for video files
                def find_video_files(obj, path=""):
                    """Recursively find video/gif files in outputs"""
                    if isinstance(obj, dict):
                        # Check if this dict looks like a file info
                        if "filename" in obj and ("gif" in obj.get("filename", "") or "mp4" in obj.get("filename", "") or "webm" in obj.get("filename", "")):
                            return [(obj.get("filename", ""), obj.get("subfolder", ""))]

                        # Search in all values
                        results = []
                        for k, v in obj.items():
                            results.extend(find_video_files(v, f"{path}.{k}"))
                        return results
                    elif isinstance(obj, list):
                        results = []
                        for i, item in enumerate(obj):
                            results.extend(find_video_files(item, f"{path}[{i}]"))
                        return results
                    return []

                video_files = find_video_files(outputs)

                # 任务报错：先抢救输出中已生成的视频（部分节点先完成的情况），
                # 确实无产物才判失败，并把节点错误详情存入 last_error 供上层显示。
                # 此前顺序相反——ComfyUI 界面里能看到已生成的视频，软件却报"失败"。
                if self.is_prompt_failed(history, prompt_id):
                    if video_files:
                        filename, subfolder = video_files[0]
                        print(f"Task errored but output video exists, salvaging: {filename}")
                        download_url = self.get_image_url(filename, subfolder)
                        if self._download_result(download_url, output_path):
                            print(f"Video salvaged to: {output_path}")
                            return output_path
                    self.last_error = self.get_prompt_error(history, prompt_id)
                    # 显存溢出：上层要据此下调分辨率重试，而不是用同一套参数再耗一轮
                    _el = (self.last_error or "").lower()
                    self.last_oom = ("out of memory" in _el
                                     or "allocation on device" in _el
                                     or "cuda out of memory" in _el)
                    if self.last_oom and self.last_megapixels:
                        self.last_error = (f"{self.last_error}"
                                           f"（本次 megapixels={self.last_megapixels}，"
                                           f"可按比例下调后重试）")
                    print(f"ComfyUI task failed: {self.last_error}")
                    return None

                if video_files:
                    filename, subfolder = video_files[0]
                    print(f"Found video file: {filename} (subfolder: {subfolder})")

                    # Download the video
                    download_url = self.get_image_url(filename, subfolder)
                    print(f"Downloading result: {filename}")

                    if self._download_result(download_url, output_path):
                        print(f"Video saved to: {output_path}")
                        return output_path
                    # Download failed — count consecutive failures to avoid infinite loop
                    download_failures += 1
                    if download_failures >= 5:
                        print(f"Download failed {download_failures} consecutive times, giving up")
                        return None
                    if interruptible_sleep(1):
                        print("Generation cancelled by user")
                        self.interrupt()
                        return None
                    continue

                # If outputs exist but no video found
                if outputs:
                    print("Outputs found but no video file yet, continuing to wait...")
                else:
                    print("History found but outputs not ready yet...")

            # Wait before next poll（可被取消打断）
            # 10s 一次：生成动辄 5~10 分钟，轮询再密也快不了，反而会在服务端
            # 忙时堆出一串注定读超时的请求
            if interruptible_sleep(10):
                print("Generation cancelled by user")
                self.interrupt()
                return None

            # Timeout check（与循环顶部同一套参数，下载失败分支 continue 后也会命中）
            if time.time() - start_time > timeout_s:
                print("Generation timed out.")
                self.interrupt()
                self.last_error = f"图生视频超时（{timeout_min:.0f} 分钟）"
                # Debug: Print final history state
                final_history = self.get_history(prompt_id)
                if prompt_id in final_history:
                    print(f"DEBUG: Final history outputs: {final_history[prompt_id].get('outputs', {})}")
                return None

    def generate_image(self, prompt, output_path, api_config, ratio="1:1", negative_prompt=""):
        """
        Generate image using ComfyUI workflow.

        Args:
            prompt: Image generation prompt
            output_path: Where to save the generated image
            api_config: API configuration dict
            ratio: Aspect ratio
            negative_prompt: Negative prompt

        Returns:
            Path to generated image or None
        """
        workflow_file = api_config.get("workflow_file", "")
        if not workflow_file or not os.path.exists(workflow_file):
            print(f"Workflow file not found: {workflow_file}")
            return None

        # Load workflow
        try:
            with open(workflow_file, 'r', encoding='utf-8') as f:
                workflow_template = json.load(f)
        except Exception as e:
            print(f"Failed to load workflow: {e}")
            return None

        # Modify workflow (set prompt, etc.)
        workflow = workflow_template.copy()

        # Find CLIP text encode nodes and set prompt
        for node_id, node in workflow.items():
            class_type = node.get("class_type", "")
            if "CLIPTextEncode" in class_type:
                # Check if this is the positive prompt (usually connected to sampler)
                # For simplicity, we'll just set the text input
                if "text" in node.get("inputs", {}):
                    node["inputs"]["text"] = prompt

        # Queue and wait
        print("Queuing image workflow...")
        queue_res = self.queue_prompt(workflow)
        if not queue_res or "prompt_id" not in queue_res:
            return None

        prompt_id = queue_res["prompt_id"]

        # Poll for completion
        start_time = time.time()
        while True:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                # 出错后快速失败
                if self.is_prompt_failed(history, prompt_id):
                    return None

                outputs = history[prompt_id].get("outputs", {})

                for node_id, output_data in outputs.items():
                    if "images" in output_data:
                        files = output_data["images"]
                        if files:
                            filename = files[0].get("filename", "")
                            subfolder = files[0].get("subfolder", "")

                            download_url = self.get_image_url(filename, subfolder)

                            if self._download_result(download_url, output_path):
                                print(f"Image saved to: {output_path}")
                                return output_path

            if interruptible_sleep(2):
                print("Image generation cancelled by user")
                return None

            if time.time() - start_time > 300:
                print("Image generation timed out.")
                return None
