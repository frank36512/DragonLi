import os
import re
import time
import threading
import httpx
from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError
from core.config.config_manager import ConfigManager

try:
    from ai_engine.utils.cancel import (
        cancelled as _cancel_requested,
        register_abort as _register_abort,
        interruptible_sleep as _interruptible_sleep,
    )
except ImportError:                      # pragma: no cover - 兼容包外导入
    try:
        from src.ai_engine.utils.cancel import (
            cancelled as _cancel_requested,
            register_abort as _register_abort,
            interruptible_sleep as _interruptible_sleep,
        )
    except ImportError:
        def _cancel_requested():
            return False

        def _register_abort(fn):
            return fn

        def _interruptible_sleep(seconds, step=0.2):
            time.sleep(seconds)
            return False

# 模块级 httpx 连接池缓存：按 base_url 复用，避免按次构造 LLMClient 时 socket 泄漏
_http_clients = {}


def _get_http_client(base_url):
    """按 base_url 获取（或创建）共享 httpx.Client。"""
    cached = _http_clients.get(base_url)
    # 终止钩子可能刚关掉旧池：已关闭的不能复用（httpx 会拒发新请求）
    if cached is None or cached.is_closed:
        cached = httpx.Client(
            timeout=httpx.Timeout(1800.0, connect=60.0),
            trust_env=False,
        )
        _http_clients[base_url] = cached
    return cached


def _abort_inflight_requests():
    """取消钩子：立刻关闭在途 LLM/embedding 连接，唤醒阻塞在 socket 读上的线程。

    协作式检查只在「收到下一个 chunk 之间」运行；prefill 期间服务端不发数据，
    线程阻塞在 recv 上（read timeout 1800s），光置取消标记要等首 token 才生效
    （27B 预填可长达数分钟，用户感受就是「点了终止没反应」）。
    Windows 下从别的线程 sock.shutdown() 打不醒阻塞的 recv（实测），
    但关闭 httpx.Client 会立即让阻塞读抛错（实测 0.0s 唤醒）——故直接关池。
    关掉的池由 _get_http_client 按需重建，已持有的实例在下次请求前惰性换新。
    """
    clients = list(_http_clients.values())
    _http_clients.clear()
    for c in clients:
        try:
            c.close()
        except Exception:
            pass


_register_abort(_abort_inflight_requests)


def _revive_http_client(openai_client, base_url):
    """终止钩子关过连接池后，把实例换回（新建的）共享连接，保证取消后可复用。"""
    if openai_client is None or not base_url:
        return
    try:
        hc = getattr(openai_client, "_client", None)
        # 用 is True 而非真值判断：测试里的 MagicMock 属性也是 truthy
        if hc is not None and getattr(hc, "is_closed", None) is True:
            openai_client._client = _get_http_client(base_url)
    except Exception:
        pass


def normalize_openai_base_url(base_url, default_path="/v1"):
    """补全 OpenAI 兼容地址缺失的路径段。

    本地服务（LM Studio / Ollama / vLLM / llama.cpp）常被写成 http://host:1234，
    而实际接口是 http://host:1234/v1/embeddings。只在“完全没有路径”时补 /v1；
    已带 /v1、/api/v1 等路径的一律原样保留，避免误改云端地址。
    """
    b = (base_url or "").strip().rstrip("/")
    if not b:
        return b
    try:
        from urllib.parse import urlsplit
        path = urlsplit(b).path.rstrip("/")
    except Exception:
        return b
    if path:
        return b
    return b + default_path


def _service_origin(base_url):
    """取服务根地址（scheme://host[:port]），用于本地服务的管理接口。

    聊天/embeddings 挂在 /v1 下，而 LM Studio 的模型加载接口
    （/api/v1/models/load、/api/v0/models）挂在服务根路径，
    所以这里去掉 /v1 只保留主机部分，避免拼出 /api/api/v1 这类路径。
    """
    from urllib.parse import urlsplit, urlunsplit
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme:
        parts = urlsplit("http://" + raw)
    if not parts.netloc:
        return raw
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _is_model_not_loaded(err):
    """判断错误是否为「本地服务尚未加载该模型」（LM Studio 的典型报错）。"""
    s = str(err or "")
    return "No models loaded" in s or "model is not loaded" in s.lower()


def _is_invalid_model(err):
    """判断错误是否为「配置的模型名不存在/无效」（区别于“还没加载”）。"""
    s = str(err or "").lower()
    if not s or _is_model_not_loaded(err):
        return False
    return ("invalid model identifier" in s
            or "model_not_found" in s
            or "not found in downloaded models" in s
            or ("model" in s and "not found" in s))


def _is_context_overflow(err):
    """判断错误是否为「超出上下文窗口」（prompt + max_tokens 超过模型上下文）。

    本地模型常以较小的上下文加载（如 16k），而 prompt 本身已占 8-10k token，
    再要 16384 的输出就会被服务端拒绝；此时应自动调小 max_tokens 重试，
    而不是直接失败。
    """
    s = str(err or "").lower()
    if not s:
        return False
    return (("context" in s and ("length" in s or "window" in s or "exceed" in s
                                 or "too long" in s or "maximum" in s))
            or "maximum context length" in s
            or "reduce the length" in s
            or "context_length_exceeded" in s)


# (服务根地址, 配置里的模型名) -> 实际可用的模型名（避免每次调用都先吃一个 400）
_MODEL_CACHE = {}


def _available_embedding_models(origin):
    """列出服务端可用的 embedding 模型 id（去重，保持顺序）。"""
    try:
        import requests
        r = requests.get(f"{origin}/api/v0/models", timeout=8,
                         proxies={"http": None, "https": None})
        rows = r.json().get("data") or []
        emb = [m.get("id") for m in rows if isinstance(m, dict)
               and m.get("id") and m.get("type") == "embeddings"]
        if emb:
            return list(dict.fromkeys(emb))
    except Exception:
        pass
    try:
        import requests
        r = requests.get(f"{origin}/v1/models", timeout=8,
                         proxies={"http": None, "https": None})
        ids = [m.get("id") for m in (r.json().get("data") or [])
               if isinstance(m, dict) and m.get("id")]
        ids = list(dict.fromkeys(ids))
        emb = [i for i in ids if "embed" in i.lower()]
        return emb or ids
    except Exception:
        return []


def _pick_embedding_model(configured, ids):
    """在可用模型里挑一个最接近配置名的（如 embedding-bge → text-embedding-bge-large-zh-v1.5）。

    打分：命中的词元各计 1 分；只被唯一候选命中的词元（如 bge）计 3 分，
    这样比通用词（embedding）更具体的名字胜出。
    """
    if not ids:
        return None
    if configured in ids:
        return configured
    tokens = [t for t in re.split(r"[^a-z0-9]+", (configured or "").lower())
              if len(t) >= 3]
    if not tokens:
        return ids[0]
    best, best_score = None, 0
    for cid in ids:
        low = cid.lower()
        score = 0
        for t in tokens:
            if t in low:
                hits = sum(1 for x in ids if t in x.lower())
                score += 3 if hits == 1 else 1
        if score > best_score:
            best, best_score = cid, score
    return best or ids[0]


def resolve_embedding_model(base_url, configured):
    """配置的模型不可用时，返回服务端真正可用的模型名（进程内缓存）。"""
    origin = _service_origin(base_url)
    if not origin:
        return None
    key = (origin, configured)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    ids = _available_embedding_models(origin)
    picked = _pick_embedding_model(configured, ids) if ids else None
    if picked:
        _MODEL_CACHE[key] = picked
    return picked


def _model_state(origin, model):
    """查询本地服务里某模型的状态：loaded / not-loaded / None(查询失败)。"""
    try:
        import requests
        r = requests.get(f"{origin}/api/v0/models", timeout=8,
                         proxies={"http": None, "https": None})
        for m in (r.json().get("data") or []):
            if isinstance(m, dict) and m.get("id") == model:
                return m.get("state")
    except Exception:
        return None
    return None


def unload_model(base_url, model, timeout=60.0):
    """卸载本地推理服务上的模型，释放显存。

    本机 GPU 同时承担 LM Studio(LLM) 与 ComfyUI(视频)：
    27B 模型常驻显存会挤掉 MiniMaxH3 需要的空间，导致视频任务 OOM 卡死。
    接口：POST {origin}/api/v1/models/unload，body={"instance_id": "<model id>"}。
    （注意：load 用 {"model": id}，unload 用 {"instance_id": id}，两者不同）
    返回 (是否成功, 说明)。
    """
    origin = _service_origin(base_url)
    if not origin or not model:
        return False, "缺少地址或模型名，跳过卸载"
    try:
        import requests
        r = requests.post(f"{origin}/api/v1/models/unload", json={"instance_id": model},
                          timeout=max(10.0, float(timeout)),
                          proxies={"http": None, "https": None})
    except Exception as e:
        return False, f"卸载请求失败: {type(e).__name__}: {e}"
    body = (r.text or "").strip()
    if r.status_code == 404:
        # 模型本来就没加载（最常见），视为成功
        return True, f"模型 {model} 未加载（无需卸载）"
    if r.status_code != 200:
        return False, f"卸载接口不可用: HTTP {r.status_code} {body[:160]}"
    return True, f"已卸载模型 {model}"


def auto_load_model(base_url, model, timeout=90.0, should_abort=None):
    """本地推理服务（LM Studio 等）按需自动加载模型。

    接口：POST {origin}/api/v1/models/load，body={"model": "<id>"}。
    返回 (是否成功, 说明)。不支持该接口时返回 (False, 原因)，
    调用方据此放弃重试，不影响原有的错误路径。
    should_abort: 可选回调，返回 True 表示用户已终止，立即中断加载等待。
    """
    origin = _service_origin(base_url)
    if not origin or not model:
        return False, "缺少地址或模型名，跳过自动加载"
    if should_abort and should_abort():
        return False, "已终止"
    # 已加载就不重复调加载接口（幂等，避免来回卸载/重载）
    if _model_state(origin, model) == "loaded":
        return True, f"模型 {model} 已加载"
    # 加载 POST 可能阻塞很久（加载 27B 耗时数十秒）：放到子线程发，
    # 主线程轮询 should_abort，用户点终止时立刻返回，不再干等到超时
    box = {}

    def _do_load():
        try:
            import requests
            box["r"] = requests.post(f"{origin}/api/v1/models/load", json={"model": model},
                                     timeout=max(30.0, float(timeout)),
                                     proxies={"http": None, "https": None})
        except Exception as e:  # noqa: BLE001
            box["e"] = e

    th = threading.Thread(target=_do_load, daemon=True)
    th.start()
    while th.is_alive():
        if should_abort and should_abort():
            return False, "已终止"     # 弃用后台 POST（daemon），加载本身无害
        th.join(0.1)
    if "e" in box:
        e = box["e"]
        return False, f"自动加载请求失败: {type(e).__name__}: {e}"
    r = box.get("r")
    if r is None:
        return False, "自动加载请求未返回结果"

    body = (r.text or "").strip()
    if r.status_code != 200:
        return False, f"加载接口不可用: HTTP {r.status_code} {body[:200]}"
    if '"loaded"' not in body:
        return False, f"加载返回异常: {body[:200]}"

    # 轮询确认真正就绪（加载大模型可能耗时较久）
    deadline = time.time() + float(timeout)
    while True:
        if should_abort and should_abort():
            return False, "已终止"      # 用户点了终止：别再等到超时
        state = _model_state(origin, model)
        if state in (None, "loaded"):     # None = 查不到状态，信任响应体
            return True, f"已自动加载模型 {model}"
        if time.time() >= deadline:
            return False, f"加载超时({timeout:.0f}s)，当前状态: {state}"
        # 分片 sleep：终止时最多 0.1s 内返回
        for _ in range(10):
            if should_abort and should_abort():
                return False, "已终止"
            time.sleep(0.1)


class LLMClient:
    # 类级默认：测试里用 __new__ 构造的实例也可能读到
    max_tokens = 16384

    def __init__(self, api_key=None, base_url=None, model=None):
        self.config_manager = ConfigManager()
        # 重新从磁盘加载，确保拿到设置页的最新配置
        self.config_manager.reload()
        self.last_error = None

        # 优先从 api_configs 读取 LLM 配置
        api_configs = self.config_manager.get("api_configs") or []
        llm_config = None
        for config in api_configs:
            if config.get("type") == "LLM":
                llm_config = config
                break
        
        if llm_config:
            # 使用配置文件中的 LLM 配置
            key = api_key or llm_config.get("api_key") or "dummy-key"
            base_url = base_url or llm_config.get("base_url")
            self.model = model or llm_config.get("model") or "gpt-4o"
            print(f"DEBUG LLMClient: Using config '{llm_config.get('name')}', base_url={base_url}, model={self.model}")
        else:
            # 回退到环境变量或默认值
            key = api_key or os.environ.get("OPENAI_API_KEY") or "dummy-key"
            base_url = base_url or os.environ.get("OPENAI_BASE_URL")
            self.model = model or "gpt-4o"
            print(f"DEBUG LLMClient: Using fallback, base_url={base_url}, model={self.model}")

        # 剧本生成 max_tokens：长篇改编每镜 video_prompt 很长，
        # 固定 8192 会在输出 1.5-2 万字符处被服务端截断（Unterminated string）。
        # 可在 LLM 配置里用 max_tokens 覆盖。
        try:
            self.max_tokens = int((llm_config or {}).get("max_tokens") or 16384)
        except (TypeError, ValueError):
            self.max_tokens = 16384
        
        # 禁用代理仅作用于本客户端（trust_env=False）。
        # 不再在构造时写进程级 os.environ["no_proxy"]="*"，避免污染
        # requests/ComfyUI 等其它 HTTP 客户端的代理行为。
        # 使用模块级共享连接池，避免按次构造时 socket 泄漏
        http_client = _get_http_client(base_url)

        self.base_url = base_url
        self._auto_loaded = False     # 自动加载模型只触发一次，避免反复请求
        self.client = OpenAI(
            api_key=key,
            base_url=base_url,
            http_client=http_client,
            max_retries=0  # We handle retries manually
        )

    def close(self):
        """显式关闭底层 httpx 连接池（共享池通常无需关闭）。"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def generate_script(self, prompt, system_prompt=None):
        if not system_prompt:
            system_prompt = """You are an AI visual prompt generator for image and video creation.
            Generate detailed visual prompts for AI image/video generation models based on the user's request.
            The JSON structure must be:
            {
                "title": "Episode Title",
                "genre": "Genre",
                "scenes": [
                    {
                        "scene_id": "1",
                        "location": "Location Name",
                        "time": "Day/Night/Dawn/Dusk",
                        "weather": "Sunny/Rainy/Foggy/Snowy/Clear",
                        "description": "Brief scene description",
                        "video_prompt": "Creative visual core of this shot (1-2 sentences, max 120 chars): what the subject is doing, key action/expression/emotional shift, the decisive moment. Do NOT write the six-section template (auto-generated by the system)",
                        "shot_type": "Close-up/Medium Shot/Wide Shot/Extreme Wide Shot",
                        "camera_movement": "Static/Pan/Tilt/Dolly/Tracking/Zoom",
                        "duration_seconds": "5-10秒（整数，根据情节灵活选择，推荐8秒，对白多/动作复杂的镜头最多10秒、严禁超过10秒，环境铺垫/空镜可以短到5秒）",
                        "dialogues": [
                            {
                                "role": "Character Name",
                                "content": "Dialogue text",
                                "action": "Character action",
                                "expression": "Facial expression"
                            }
                        ]
                    }
                ]
            }
            Return ONLY valid JSON string, no markdown formatting.
            """

        self.last_error = None  # 记录最后一次失败原因，供调用方展示给用户
        if _cancel_requested():
            self.last_error = "已终止"
            print("LLM request skipped: cancelled by user")
            return None
        _revive_http_client(self.client, self.base_url)
        max_retries = 3
        # 本次请求实际使用的 max_tokens（上下文超限时可下调后重试）
        cur_max_tokens = self.max_tokens
        for attempt in range(max_retries):
            if _cancel_requested():
                # 上一轮可能卡在自动加载/退避等待里，进入下一轮前再确认一次
                self.last_error = "已终止"
                return None
            try:
                start_time = time.time()
                print(f"LLM Request started (Attempt {attempt+1})...")

                # 使用流式调用：27B 本地模型生成长剧本可能耗时很久，
                # 非流式时服务器在生成完成前不发数据，读超时一到连接就断了，
                # 但模型仍在后台跑完——改成 stream=True 后服务器边生成边发 token，
                # 连接保持活跃，不会误超时
                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=cur_max_tokens,
                    stream=True,
                )

                content_parts = []
                finish_reason = ""
                first_token_at = None
                for chunk in stream:
                    # 用户点「终止」→ 立刻关连接：服务端收到底 FIN 会中断生成，
                    # 不再继续烧 GPU 干等整段跑完
                    if _cancel_requested():
                        self.last_error = "已终止"
                        print("LLM stream cancelled by user, closing connection")
                        try:
                            stream.close()
                        except Exception:
                            pass
                        return None
                    if chunk.choices:
                        if chunk.choices[0].delta.content:
                            if first_token_at is None:
                                first_token_at = time.time()
                            content_parts.append(chunk.choices[0].delta.content)
                        if getattr(chunk.choices[0], "finish_reason", None):
                            finish_reason = chunk.choices[0].finish_reason

                duration = time.time() - start_time
                content = "".join(content_parts)
                ttft = (first_token_at - start_time) if first_token_at else duration
                gen_secs = max(duration - ttft, 0.001) if content else 0.0
                cph = (len(content) / gen_secs) if content else 0.0
                print(f"LLM Request finished in {duration:.2f}s"
                      f"（首token {ttft:.1f}s | 输出 {len(content)} 字 | 约 {cph:.0f} 字/s）")
                # 慢速启发：首 token 很慢 = 预填在 CPU 跑；生成速率低 = 逐 token 在 CPU 跑。
                # 27B 在 3090 满载 offload 下通常 TTFT < 10s、30+ 字/s，
                # 达不到即提示用户检查 LM Studio 的 GPU Offload。
                if (first_token_at and ttft > 20) or (content and cph < 12):
                    print("[LLM] 推理速度偏慢（疑似 GPU offload 不足）："
                          "请在 LM Studio 卸载模型 → GPU Offload 拉到 MAX 后重新加载；"
                          "视频阶段会自动卸载 LLM，脚本阶段拉满显存不会与 ComfyUI 冲突")

                if not content or not content.strip():
                    self.last_error = "LLM 返回了空内容（model 可能未加载或 max_tokens 不足）"
                    print(f"LLM 返回空内容 (Attempt {attempt+1})")
                    if attempt < max_retries - 1:
                        if _interruptible_sleep(3 * (attempt + 1)):
                            self.last_error = "已终止"
                            return None
                        continue
                    return None
                # 输出被 max_tokens 截断 → 记录明确原因，便于上层提示调大配置
                if finish_reason == "length":
                    print(f"LLM 输出被 max_tokens={cur_max_tokens} 截断"
                          f"（已生成 {len(content)} 字符），JSON 可能不完整")
                return content
            except (APIConnectionError, APITimeoutError, RateLimitError) as e:
                duration = time.time() - start_time
                # 用户终止会主动关连接（abort 钩子），报错是关连接的副产物，不当作故障
                if _cancel_requested():
                    self.last_error = "已终止"
                    print(f"LLM request aborted by user after {duration:.1f}s")
                    return None
                self.last_error = f"{type(e).__name__}: {e}（{duration:.1f}s）"
                print(f"LLM Network Error (Attempt {attempt+1}/{max_retries}) after {duration:.1f}s: {e}")
                if attempt < max_retries - 1:
                    # 退避期间也可被终止打断（原先 time.sleep 要干等 3-6s）
                    if _interruptible_sleep(3 * (attempt + 1)):
                        self.last_error = "已终止"
                        return None
                else:
                    print(f"LLM Failed after {max_retries} attempts.")
                    return None
            except Exception as e:
                # 用户已终止 → 不再重试、不再触发自动加载，直接返回
                # （abort 钩子关连接产生的 WinError/ReadError 也走这里）
                if _cancel_requested():
                    self.last_error = "已终止"
                    print(f"LLM request aborted by user ({type(e).__name__})")
                    return None
                self.last_error = f"{type(e).__name__}: {e}"
                print(f"LLM Error: {e}")
                # prompt + max_tokens 超出模型上下文窗口 → 调小 max_tokens 重试，
                # 而不是直接失败（本地模型常以 16k 上下文加载）
                if (_is_context_overflow(e) and cur_max_tokens > 4096
                        and attempt < max_retries - 1):
                    cur_max_tokens = max(4096, cur_max_tokens // 2)
                    print(f"[llm] 超出上下文窗口，自动把 max_tokens 降到 {cur_max_tokens} 后重试")
                    continue
                # 本地服务（LM Studio）尚未加载该模型 → 自动加载后重试一次，
                # 不用再让用户手动去 LM Studio 点加载
                if attempt < max_retries - 1 and _is_model_not_loaded(e) and not self._auto_loaded:
                    self._auto_loaded = True
                    ok, load_msg = auto_load_model(self.base_url, self.model, timeout=240.0,
                                                   should_abort=_cancel_requested)
                    print(f"[llm] {load_msg}")
                    if ok:
                        if _interruptible_sleep(1.0):
                            self.last_error = "已终止"
                            return None
                        continue
                return None

    def get_embedding(self, text, model=None):
        """Generates embedding for the given text using OpenAI API."""
        try:
            text = text.replace("\n", " ")
            
            # Get model from argument or config, default to text-embedding-3-small
            if not model:
                model = self.config_manager.get("embedding_model", "text-embedding-3-small")
            
            _revive_http_client(self.client, getattr(self, "base_url", None))
            response = self.client.embeddings.create(
                input=[text],
                model=model
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"Embedding Error: {e}")
            # Return a zero vector or None as fallback?
            # Better to return None and handle it.
            return None


class EmbeddingClient:
    """独立的 embedding 客户端，使用单独的 API 配置（可与 LLM 不同）。

    配置优先级：显式传入的 api_config > 全局 embedding_* 配置 > LLM 配置（向后兼容）。
    这样可以用「本地 LLM + 云端 embedding」的组合，适配本地模型服务不支持
    embeddings 接口的场景。

    用法：
        client = EmbeddingClient()                      # 读全局配置
        client = EmbeddingClient({"api_key": ..., "base_url": ..., "model": ...})
        vec = client.get_embedding("文本")               # 不可用时返回 None
    """

    def __init__(self, api_config=None, config_manager=None):
        self.config_manager = config_manager or ConfigManager()
        cfg = dict(api_config or {})
        self.configured_model = ""  # __new__ 构造的测试实例也可能读到

        api_key = cfg.get("api_key") or self.config_manager.get("embedding_api_key", "")
        base_url = cfg.get("base_url") or self.config_manager.get("embedding_base_url", "")
        self.model = (cfg.get("model")
                      or self.config_manager.get("embedding_model")
                      or "text-embedding-3-small")

        # 回退到 LLM 配置（用户未单独配置 embedding 时保持原行为）。
        # api_key 与 base_url 各自独立回退：只填了 Key 没填地址时也要能用。
        llm_cfgs = self.config_manager.get("api_configs") or []
        llm = next((c for c in llm_cfgs if c.get("type") == "LLM"), {}) or {}
        if not api_key:
            api_key = llm.get("api_key") or ""
        if not base_url:
            base_url = llm.get("base_url") or ""

        # 本地服务常漏写 /v1，导致 200 + {"error":...} 被 SDK 解析成空 data
        base_url = normalize_openai_base_url(base_url)

        self.api_key = api_key
        self.base_url = base_url
        self.client = None
        self.configured_model = self.model   # 配置里写的模型名（可能已失效）
        self.last_load_msg = ""     # 自动换模型/加载模型的说明（供 test() 回显）

        # 进程内缓存：该配置模型已被判定失效时直接用上次解析出的可用模型，
        # 避免每次调用都先吃一个 400 再换
        cached = _MODEL_CACHE.get((_service_origin(base_url), self.model))
        if cached and cached != self.model:
            self.model = cached
            self._note(f"模型「{self.configured_model}」在服务端不可用，已自动改用「{cached}」")

        if api_key:
            try:
                http_client = _get_http_client(base_url)
                self.client = OpenAI(
                    api_key=api_key,
                    base_url=base_url or None,
                    http_client=http_client,
                    max_retries=0,
                )
            except Exception as e:
                print(f"EmbeddingClient init error: {e}")

        # 延迟自动卸载：空闲 IDLE_AFTER 秒后主动调 LM Studio unload 接口释放显存。
        # 模块级 httpx 连接池会保持 TCP 长连接，LM Studio 把它当作"模型仍在使用"
        # 而不触发自身的空闲卸载计时器，这里补上显式卸载。
        # 定时器每次 get_embedding 成功都会重置，批量调用期间不会卸载。
        self._idle_timer = None
        self._idle_lock = threading.Lock()
        self._last_used = 0.0
        self.idle_unload_seconds = float(
            self.config_manager.get("embedding_idle_unload", 60.0) or 60.0)

    def _note(self, msg):
        """累积自动处理过程的说明，供测试/日志回显。"""
        if not msg:
            return
        self.last_load_msg = (f"{self.last_load_msg}；{msg}" if self.last_load_msg else msg)
        print(f"[embedding] {msg}")

    def _schedule_idle_unload(self):
        """重置空闲卸载定时器：每次成功调用后启动/重启。"""
        with self._idle_lock:
            self._last_used = time.time()
            if self._idle_timer is not None:
                self._idle_timer.cancel()
            self._idle_timer = threading.Timer(
                self.idle_unload_seconds, self._do_unload)
            self._idle_timer.daemon = True     # 程序退出时不阻塞
            self._idle_timer.start()

    def _do_unload(self):
        """定时器到期：主动卸载 embedding 模型释放显存。"""
        try:
            ok, msg = unload_model(self.base_url, self.model, timeout=30.0)
            if ok:
                print(f"[embedding] 空闲 {self.idle_unload_seconds:.0f}s 自动卸载模型 {self.model}")
            else:
                print(f"[embedding] 自动卸载失败: {msg}")
        except Exception as e:
            print(f"[embedding] 自动卸载异常: {e}")
        finally:
            with self._idle_lock:
                self._idle_timer = None

    def close(self):
        """立即取消定时器并卸载（供批量 embedding 完成后主动调用）。"""
        with self._idle_lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
        if self.client and self.base_url and self.model:
            try:
                unload_model(self.base_url, self.model, timeout=15.0)
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def get_embedding(self, text, model=None):
        """返回 embedding 向量；不可用时返回 None（调用方降级）。

        本地服务两类常见问题自动处理，无需用户手动干预：
        1. 模型未加载 → 调加载接口后重试；
        2. 配置的模型名已不存在 → 换成服务端可用的 embedding 模型并加载后重试。
        """
        if not self.client:
            return None
        if _cancel_requested():
            return None
        _revive_http_client(self.client, getattr(self, "base_url", None))
        model = model or self.model
        text = (text or "").replace("\n", " ")
        for attempt in range(4):
            if _cancel_requested():
                return None          # 加载等待期间被终止
            try:
                response = self.client.embeddings.create(input=[text], model=model)
                if model != self.model:
                    self.model = model
                self._schedule_idle_unload()   # 成功获取后启动/重置空闲卸载定时器
                return response.data[0].embedding
            except Exception as e:
                print(f"Embedding Error: {e}")
                if attempt >= 2:      # 已换过模型/加载过，不再反复折腾
                    return None
                if _is_model_not_loaded(e):
                    # 服务端没加载任何模型：先确认配置的模型名在服务端存在，
                    # 不存在就先换成可用模型再加载——此前拿无效名（如 embedding-bge）
                    # 去调加载接口必然失败，导致 RAG 直接降级
                    configured = getattr(self, "configured_model", None) or model
                    if model not in (_available_embedding_models(_service_origin(self.base_url)) or []):
                        alt = resolve_embedding_model(self.base_url, configured)
                        if alt and alt != model:
                            self._note(f"服务端未加载模型且「{model}」不可用，"
                                       f"自动改用「{alt}」")
                            model = alt
                    ok, msg = auto_load_model(self.base_url, model, timeout=60.0,
                                              should_abort=_cancel_requested)
                    self._note(msg if ok else "")
                    if ok:
                        continue
                    return None
                if _is_invalid_model(e):
                    alt = resolve_embedding_model(self.base_url,
                                                  getattr(self, "configured_model", None) or model)
                    if not alt or alt == model:
                        return None
                    self._note(f"模型「{model}」在服务端不可用，已自动改用「{alt}」")
                    model = alt
                    ok, msg = auto_load_model(self.base_url, model, timeout=60.0,
                                              should_abort=_cancel_requested)
                    self._note(msg if ok else "")
                    continue
                return None
        return None

    def test(self):
        """连接自检，返回 (是否成功, 说明文案)。

        SDK 在“服务端返回 200 但没有向量”时只会抛 No embedding data received，
        信息量为 0；这里改用原始 HTTP 请求拿到服务端真实响应，并列出可用模型，
        便于直接定位 Base URL 少写 /v1、模型名不存在、服务未加载模型等问题。
        """
        if not self.base_url:
            return False, "未配置 Base URL"
        if not self.client:
            return False, "未配置 API Key（本地服务可填任意值，如 sk-local）"
        try:
            vec = self.get_embedding("test")
            if vec:
                msg = (f"连接成功！模型: {self.model}，向量维度: {len(vec)}\n"
                       f"实际地址: {self.base_url}/embeddings")
                if self.last_load_msg:
                    msg += f"\n{self.last_load_msg}"
                if self.configured_model and self.model != self.configured_model:
                    msg += f"\n→ 建议把配置里的 Model 字段改为「{self.model}」"
                return True, msg
        except Exception:
            pass
        return False, (f"Embedding 连接失败（模型: {self.model}，地址: {self.base_url}）\n"
                       + self._raw_probe())

    def _raw_probe(self):
        """直接请求服务端，取回真实状态码/响应体与可用模型列表。"""
        import requests
        out = []
        try:
            r = requests.post(
                f"{self.base_url}/embeddings",
                headers={"Content-Type": "application/json"},
                json={"model": self.model, "input": "test"},
                timeout=15, proxies={"http": None, "https": None})
            body = (r.text or "").replace("\n", " ").strip()[:300]
            out.append(f"服务端响应: HTTP {r.status_code} {body}")
            if "No models loaded" in body:
                out.append("→ 服务还没有加载模型，请先在 LM Studio 开发者页加载（或 lms load）")
            elif r.status_code == 404:
                out.append("→ 路径不存在，请检查 Base URL（通常需以 /v1 结尾）")
        except Exception as e:
            out.append(f"服务端响应: 请求失败 {type(e).__name__}: {e}")
        try:
            r = requests.get(f"{self.base_url}/models", timeout=8,
                             proxies={"http": None, "https": None})
            ids = [m.get("id") for m in (r.json().get("data") or [])
                   if isinstance(m, dict) and m.get("id")]
            emb = [i for i in ids if "embed" in i.lower()]
            pick = emb or ids
            if pick:
                out.append("可用模型: " + ", ".join(pick[:8]))
                if emb and self.model not in emb:
                    out.append(f"→ 当前 Model「{self.model}」不在可用 embedding 模型中，请改用上面的某个")
        except Exception:
            pass
        return "\n".join(out)
