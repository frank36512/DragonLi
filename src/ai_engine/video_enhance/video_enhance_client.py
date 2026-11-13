import os
import time
import subprocess
from typing import List, Optional, Callable

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover - imageio_ffmpeg 缺失时回退 PATH 查找
    imageio_ffmpeg = None

from PIL import Image  # noqa: F401  (保留既有依赖)
import cv2
import numpy as np  # noqa: F401  (保留既有依赖)


def get_ffmpeg_exe():
    """统一获取 ffmpeg 可执行文件，避免裸写 "ffmpeg" 在 PATH 缺失时失败。"""
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return "ffmpeg"


def _startupinfo_hidden():
    """Windows 下隐藏子进程控制台窗口。"""
    if os.name == 'nt':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    return None


class VideoEnhanceClient:
    """视频增强客户端，支持多种AI增强功能"""

    def __init__(self, api_key=None, base_url=None, provider=None, api_config=None):
        self.api_config = api_config or {}
        self.api_key = api_key or self.api_config.get("api_key") or "sk-placeholder"
        self.base_url = base_url or self.api_config.get("base_url")
        self.provider = provider or self.api_config.get("provider") or "local"
        self.progress_callback = None
        self.ffmpeg_exe = get_ffmpeg_exe()
        # 协作取消标志
        self.cancelled = False
        # 单个增强阶段的最长执行时间（秒）
        self.stage_timeout = 1800
        # ComfyUI /object_info 缓存（用于界面格式工作流转 API 格式）
        self._object_info = None
        # 水印位置预设：top-left / top-right / bottom-left / bottom-right / center / custom
        self.watermark_position = (self.api_config or {}).get(
            "watermark_position", "top-right"
        )
        # custom 模式下的像素坐标 (x, y, width, height)
        self.watermark_custom_xywh = (self.api_config or {}).get(
            "watermark_custom_xywh", None
        )

    def request_cancel(self):
        """请求取消正在进行的增强（阶段间生效，ffmpeg 子进程会被 kill）。"""
        self.cancelled = True

    def set_progress_callback(self, callback: Callable[[int, str], None]):
        """设置进度回调函数"""
        self.progress_callback = callback

    def _report_progress(self, progress: int, message: str):
        """报告进度"""
        if self.progress_callback:
            self.progress_callback(progress, message)
        print(f"[VideoEnhance] {progress}%: {message}")

    def _run_ffmpeg(self, cmd: List[str]) -> tuple:
        """
        运行 ffmpeg 子进程：
        - 轮询以便响应取消与超时；
        - Windows 隐藏黑窗；
        - 返回 (success: bool, stderr_tail: str)。
        """
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                startupinfo=_startupinfo_hidden(),
            )
        except FileNotFoundError as e:
            return False, f"ffmpeg not found: {e}"
        except Exception as e:
            return False, f"failed to start ffmpeg: {e}"

        start = time.time()
        while True:
            ret = proc.poll()
            if ret is not None:
                break
            if self.cancelled:
                proc.kill()
                proc.wait(timeout=10)
                return False, "cancelled by user"
            if time.time() - start > self.stage_timeout:
                proc.kill()
                proc.wait(timeout=10)
                return False, f"stage timeout after {self.stage_timeout}s"
            time.sleep(0.5)

        stderr_tail = ""
        if proc.stderr is not None:
            try:
                raw = proc.stderr.read()
                stderr_tail = raw.decode("utf-8", errors="replace")[-2000:]
            except Exception:
                stderr_tail = ""
        return ret == 0, stderr_tail

    def enhance_video(self, video_path: str, enhancements: List[str], output_path: str) -> Optional[str]:
        """
        增强视频

        Args:
            video_path: 输入视频路径
            enhancements: 增强功能列表，可选值：
                - "super_resolution": 视频超分
                - "remove_watermark": 去水印
                - "quality_enhance": 画质增强
                - "frame_interpolation": 帧率提升
                - "deblur": 模糊修复
            output_path: 输出视频路径

        Returns:
            输出视频路径或None（失败）
        """
        if not os.path.exists(video_path):
            print(f"[VideoEnhance] Error: Video not found at {video_path}")
            return None

        self._report_progress(0, "开始视频增强处理...")

        try:
            # 根据provider选择处理方式
            if self.provider.lower() in ["runway", "api", "302"]:
                return self._enhance_via_api(video_path, enhancements, output_path)
            else:
                return self._enhance_local(video_path, enhancements, output_path)
        except Exception as e:
            print(f"[VideoEnhance] Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _enhance_via_api(self, video_path: str, enhancements: List[str], output_path: str) -> Optional[str]:
        """通过API进行视频增强"""
        # 这里可以实现调用Runway、Veo等API进行视频增强
        # 目前使用本地处理作为fallback
        self._report_progress(10, "API增强模式，切换到本地处理...")
        return self._enhance_local(video_path, enhancements, output_path)

    def _enhance_local(self, video_path: str, enhancements: List[str], output_path: str) -> Optional[str]:
        """本地视频增强处理"""
        import tempfile
        import shutil

        # 确保输出目录存在
        out_parent = os.path.dirname(output_path)
        if out_parent:
            os.makedirs(out_parent, exist_ok=True)

        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="video_enhance_")

        try:
            # 提取视频信息
            self._report_progress(5, "分析视频信息...")
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                print(f"[VideoEnhance] Error: cannot open video {video_path}")
                return None
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            if width <= 0 or height <= 0 or fps <= 0:
                print(f"[VideoEnhance] Error: invalid video info {width}x{height} @ {fps}fps")
                return None

            self._report_progress(10, f"视频信息: {width}x{height}, {fps}fps, {total_frames}帧")

            # 确定处理流程
            current_video = video_path

            # 1. 超分辨率处理（优先 ComfyUI 工作流；失败或未配置时回退 ffmpeg 高质量缩放）
            if "super_resolution" in enhancements and not self.cancelled:
                self._report_progress(15, "应用超分辨率...")
                sr_output = os.path.join(temp_dir, "sr_video.mp4")
                wf = self._stage_workflow("super_resolution")
                sr_result = None
                if wf:
                    sr_result = self._run_comfyui_stage(wf, current_video, sr_output, "视频超分")
                    if not sr_result and not self.cancelled:
                        self._report_progress(15, "ComfyUI 超分失败，回退本地 ffmpeg 处理...")
                if not sr_result and not self.cancelled:
                    sr_result = self._apply_super_resolution(current_video, sr_output, width, height)
                if sr_result:
                    current_video = sr_result
                    # 以实际产物分辨率刷新尺寸，兼容 2x/4x 等不同超分倍率
                    nw, nh = self._probe_size(current_video)
                    if nw > 0 and nh > 0:
                        width, height = nw, nh
                else:
                    print("[VideoEnhance] super resolution stage failed")
                    return None

            # 2. 画质增强
            if "quality_enhance" in enhancements and current_video and not self.cancelled:
                self._report_progress(35, "应用画质增强...")
                quality_output = os.path.join(temp_dir, "quality_video.mp4")
                wf = self._stage_workflow("quality_enhance")
                result = None
                if wf:
                    result = self._run_comfyui_stage(wf, current_video, quality_output, "画质增强")
                    if not result and not self.cancelled:
                        self._report_progress(35, "ComfyUI 画质增强失败，回退本地 ffmpeg 处理...")
                if not result and not self.cancelled:
                    result = self._apply_quality_enhance(current_video, quality_output)
                if not result:
                    return None
                current_video = result

            # 3. 去模糊
            if "deblur" in enhancements and current_video and not self.cancelled:
                self._report_progress(50, "应用去模糊...")
                deblur_output = os.path.join(temp_dir, "deblur_video.mp4")
                wf = self._stage_workflow("deblur")
                result = None
                if wf:
                    result = self._run_comfyui_stage(wf, current_video, deblur_output, "模糊修复")
                    if not result and not self.cancelled:
                        self._report_progress(50, "ComfyUI 模糊修复失败，回退本地 ffmpeg 处理...")
                if not result and not self.cancelled:
                    result = self._apply_deblur(current_video, deblur_output)
                if not result:
                    return None
                current_video = result

            # 4. 帧率提升
            if "frame_interpolation" in enhancements and current_video and not self.cancelled:
                self._report_progress(65, "应用帧率提升...")
                frame_output = os.path.join(temp_dir, "frame_video.mp4")
                wf = self._stage_workflow("frame_interpolation")
                result = None
                if wf:
                    result = self._run_comfyui_stage(wf, current_video, frame_output, "帧率提升")
                    if not result and not self.cancelled:
                        self._report_progress(65, "ComfyUI 帧率提升失败，回退本地 ffmpeg 补帧...")
                if not result and not self.cancelled:
                    result = self._apply_frame_interpolation(current_video, frame_output, fps)
                if not result:
                    return None
                current_video = result
                nfps = self._probe_fps(current_video)
                if nfps > 0:
                    fps = nfps

            # 5. 去水印
            if "remove_watermark" in enhancements and current_video and not self.cancelled:
                self._report_progress(80, "应用去水印...")
                watermark_output = os.path.join(temp_dir, "watermark_video.mp4")
                wf = self._stage_workflow("remove_watermark")
                result = None
                if wf:
                    result = self._run_comfyui_stage(wf, current_video, watermark_output, "去水印")
                    if not result and not self.cancelled:
                        self._report_progress(80, "ComfyUI 去水印失败，回退本地 ffmpeg 处理...")
                if not result and not self.cancelled:
                    result = self._apply_watermark_removal(current_video, watermark_output)
                if not result:
                    return None
                current_video = result

            if self.cancelled:
                print("[VideoEnhance] cancelled before saving output")
                return None

            # 复制最终结果（校验非空，避免把损坏/空文件交给上层当成功）
            if current_video and os.path.exists(current_video) and os.path.getsize(current_video) > 0:
                self._report_progress(95, "保存增强后的视频...")
                shutil.copy2(current_video, output_path)
                if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                    print("[VideoEnhance] output file missing or empty after copy")
                    return None
                self._report_progress(100, "视频增强完成!")
                return output_path
            else:
                return None

        finally:
            # 清理临时目录
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _valid_output(path: str) -> bool:
        return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0

    @staticmethod
    def _probe_size(video_path: str) -> tuple:
        """读取视频实际宽高，失败返回 (0, 0)。"""
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
                if w > 0 and h > 0:
                    return w, h
        except Exception as e:
            print(f"[VideoEnhance] probe size failed: {e}")
        return 0, 0

    @staticmethod
    def _probe_fps(video_path: str) -> float:
        """读取视频实际帧率，失败返回 0。"""
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                fps = float(cap.get(cv2.CAP_PROP_FPS))
                cap.release()
                if fps > 0:
                    return fps
        except Exception as e:
            print(f"[VideoEnhance] probe fps failed: {e}")
        return 0.0

    # 增强阶段 -> 配置项键名（工作流文件路径）。未配置的项回退 ffmpeg 实现。
    STAGE_WORKFLOW_KEYS = {
        "super_resolution": "workflow_file_upscale",
        "frame_interpolation": "workflow_file_interp",
        "remove_watermark": "workflow_file_dewatermark",
        "quality_enhance": "workflow_file_quality",
        "deblur": "workflow_file_deblur",
    }

    # 水印位置预设：按视频宽高的相对比例，自动换算像素坐标。
    # 99% 的视频平台 LOGO/水印都在四角，用这个就够用了。
    # (x_ratio, y_ratio, w_ratio, h_ratio) —— x/y 是左上角在画面中的相对位置。
    WATERMARK_PRESETS = {
        "top-left":      (0.00, 0.00, 0.22, 0.15),
        "top-right":     (0.78, 0.00, 0.22, 0.15),
        "bottom-left":   (0.00, 0.88, 0.22, 0.12),
        "bottom-right":  (0.78, 0.88, 0.22, 0.12),
        "center":        (0.35, 0.42, 0.30, 0.16),
    }

    def _resolve_watermark_region(self, video_path: str) -> Optional[tuple]:
        """根据预设 + 视频尺寸解析水印矩形 (x, y, width, height)。

        返回的是像素坐标，可直接写入 Mask Rect Area (Advanced) 节点的 x/y/width/height 输入。
        """
        w, h = self._probe_size(video_path)
        if w <= 0 or h <= 0:
            return None

        pos = (self.watermark_position or "top-right").lower().strip()
        if pos == "custom" and self.watermark_custom_xywh:
            try:
                x, y, cw, ch = [int(v) for v in self.watermark_custom_xywh]
                if x >= 0 and y >= 0 and cw > 0 and ch > 0 and x + cw <= w and y + ch <= h:
                    return (x, y, cw, ch)
            except (TypeError, ValueError):
                pass
            print("[VideoEnhance] 警告: watermark_custom_xywh 无效，回退 top-right 预设")
            pos = "top-right"

        if pos == "auto":
            # 自动检测（多帧方差 + 边缘密度），检测失败回退 top-right
            detected = self._detect_watermark_region_openCV(video_path)
            if detected:
                return detected
            print("[VideoEnhance] 自动检测未找到水印，回退 top-right 预设")
            pos = "top-right"

        preset = self.WATERMARK_PRESETS.get(pos) or self.WATERMARK_PRESETS["top-right"]
        xr, yr, wr, hr = preset
        x = max(0, int(w * xr))
        y = max(0, int(h * yr))
        cw = max(16, int(w * wr))
        ch = max(16, int(h * hr))
        # 边界保护
        cw = min(cw, w - x)
        ch = min(ch, h - y)
        return (x, y, cw, ch)

    @staticmethod
    def _detect_watermark_region_openCV(video_path: str, sample_frames: int = 15) -> Optional[tuple]:
        """OpenCV 自动检测水印（多帧方差 + 边缘密度）。"""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if w <= 0 or h <= 0 or total < 4:
            cap.release()
            return None

        sample_count = min(sample_frames, max(4, total))
        max_scan = min(total, int(fps * 60))
        indices = np.linspace(0, max_scan - 1, sample_count, dtype=np.int32)

        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ok, frame = cap.read()
            if ok:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
                frames.append(gray)
        cap.release()

        if len(frames) < 4:
            return None

        stack = np.stack(frames, axis=0)
        var_img = stack.var(axis=0)
        var_norm = cv2.normalize(var_img, None, 0, 1, cv2.NORM_MINMAX)
        sobel = cv2.Sobel(stack.mean(axis=0), cv2.CV_32F, 1, 1, ksize=3)
        sobel_norm = cv2.normalize(np.abs(sobel), None, 0, 1, cv2.NORM_MINMAX)

        heat_inv = 1.0 - var_norm
        candidate = heat_inv * sobel_norm
        cand_norm = cv2.normalize(candidate, None, 0, 1, cv2.NORM_MINMAX)

        _, thresh = cv2.threshold(cand_norm, 0.28, 1.0, cv2.THRESH_BINARY)
        mask = (thresh * 255).astype(np.uint8)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.dilate(mask, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        min_side = int(min(w, h) * 0.03)
        max_side = int(min(w, h) * 0.35)

        best, best_score = None, -1e9
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if cw < min_side or ch < min_side or cw > max_side or ch > max_side:
                continue
            area_score = cv2.contourArea(cnt) / (w * h)
            density = cv2.contourArea(cnt) / max(cw * ch, 1)
            score = area_score * density * 10000
            if score > best_score:
                best_score = score
                best = (x, y, cw, ch)

        return best

    def _stage_workflow(self, stage_key: str) -> Optional[str]:
        """返回该阶段应使用的 ComfyUI 工作流路径；未配置或非 ComfyUI 时返回 None。

        仅当 provider 为 ComfyUI 且 api_config 中配置了对应工作流文件时才启用，
        否则由调用方回退到 ffmpeg 实现。
        """
        if (self.provider or "").lower() != "comfyui":
            return None
        key = self.STAGE_WORKFLOW_KEYS.get(stage_key)
        if not key:
            return None
        path = str((self.api_config or {}).get(key, "") or "").strip()
        if path and os.path.exists(path):
            return path
        return None

    # ComfyUI 中作为「控件」(widget) 参与节点参数的输入类型；
    # 其余类型(IMAGE/MASK/MODEL...)为连线输入。
    # 注意：新版 ComfyUI 用字面量 "COMBO" 表示下拉框，旧版用列表表示。
    WIDGET_TYPES = ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")

    def _get_object_info(self, base_url: str) -> dict:
        """获取并缓存 ComfyUI 节点定义（用于界面格式 -> API 格式转换）。"""
        if self._object_info is None:
            import requests
            url = f"{base_url.rstrip('/')}/object_info"
            resp = requests.get(url, timeout=(10, 120), proxies={"http": None, "https": None})
            resp.raise_for_status()
            self._object_info = resp.json()
        return self._object_info

    @staticmethod
    def _node_specs(info_node: dict) -> tuple:
        """按 ComfyUI 前端的规则，把节点输入拆分为「控件」与「连线」两类（保持声明顺序）。"""
        inp = info_node.get("input", {}) or {}
        order = info_node.get("input_order") or {
            "required": list((inp.get("required") or {}).keys()),
            "optional": list((inp.get("optional") or {}).keys()),
        }
        widgets, link_inputs = [], []
        for sect in ("required", "optional"):
            for name in (order.get(sect) or []):
                spec = (inp.get(sect) or {}).get(name)
                if spec is None:
                    continue
                t = spec[0]
                if isinstance(t, list) or t in VideoEnhanceClient.WIDGET_TYPES:
                    widgets.append((name, spec))
                else:
                    link_inputs.append((name, t))
        return widgets, link_inputs

    def _ui_to_api(self, graph: dict, object_info: dict) -> dict:
        """把 ComfyUI 界面格式(含 nodes/links)转换为 /prompt 所需的 API 格式。"""
        # 仅保留可执行节点：Note/Reroute/Primitive 等纯界面节点在 /prompt 中不存在，
        # 直接跳过它们（指向它们连线也就不会被写入，改回落到控件值）。
        nodes = []
        valid_ids = set()
        for node in (graph.get("nodes") or []):
            if node.get("mode") in (2, 4):  # 2=静音, 4=绕过
                continue
            info_node = object_info.get(node.get("type"))
            if not info_node:
                continue
            nodes.append(node)
            valid_ids.add(str(node.get("id")))

        linkmap = {}
        for link in (graph.get("links") or []):
            # [link_id, origin_node, origin_slot, target_node, target_slot, type]
            if isinstance(link, list) and len(link) >= 3 and str(link[1]) in valid_ids:
                linkmap[link[0]] = [str(link[1]), link[2]]

        api = {}
        for node in nodes:
            class_type = node.get("type")
            info_node = object_info[class_type]
            widgets, _ = self._node_specs(info_node)

            # 输入槽：普通连线槽与「控件被转为输入」的槽都会出现在 inputs 中，
            # 后者带 widget 标记，由下面的控件循环按同名回填，二者只需取其一。
            inputs = {}
            linked = set()
            for slot in (node.get("inputs") or []):
                lid = slot.get("link")
                if lid is not None and lid in linkmap:
                    inputs[slot.get("name")] = list(linkmap[lid])
                    linked.add(slot.get("name"))

            wvals = node.get("widgets_values") or []
            for idx, (name, spec) in enumerate(widgets):
                if name in linked:
                    continue  # 该控件已由连线提供，忽略其占位值
                if idx < len(wvals) and wvals[idx] is not None:
                    inputs[name] = wvals[idx]
                    continue
                cfg = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                if cfg.get("options"):
                    inputs[name] = cfg["options"][0]  # COMBO 默认取首个选项
                elif "default" in cfg:
                    inputs[name] = cfg["default"]
                elif not isinstance(spec[0], list):
                    pass  # 无默认值的控件留空，交由 ComfyUI 处理
                else:
                    inputs[name] = ""

            api[str(node.get("id"))] = {"class_type": class_type, "inputs": inputs}
        return api

    def _load_workflow(self, workflow_file: str, base_url: str) -> dict:
        """读取工作流文件，返回 API 格式；若为界面格式则自动转换。"""
        import json
        with open(workflow_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("nodes"), list):
            print("[VideoEnhance] 检测到界面格式工作流，自动转换为 API 格式")
            return self._ui_to_api(data, self._get_object_info(base_url))
        return data

    def _run_comfyui_stage(self, workflow_file: str, input_video: str,
                           output_path: str, label: str) -> Optional[str]:
        """通过 ComfyUI 工作流处理单个增强阶段，成功返回输出路径，否则 None。

        注入约定（便于用户自备工作流对接）：
        - 输入视频通过 /upload/image 上传（ComfyUI 该接口同样接受视频文件）；
        - 自动写入工作流中首个 class_type 含 "LoadVideo" 的节点，
          依次尝试 inputs 中的 video / video_path / filename / file 键；
        - 输出取 history 中递归找到的 mp4/webm/gif 文件。
        """
        try:
            import json
            try:
                from ai_engine.video_gen.comfyui_service import ComfyUIService
            except ImportError:
                from src.ai_engine.video_gen.comfyui_service import ComfyUIService
        except Exception as e:
            print(f"[VideoEnhance] ComfyUI 依赖导入失败: {e}")
            return None

        base_url = self.base_url or "http://127.0.0.1:8188"
        service = ComfyUIService(base_url)

        # 1. 加载工作流（支持界面格式与 API 格式，界面格式会自动转换）
        try:
            workflow = self._load_workflow(workflow_file, base_url)
        except Exception as e:
            print(f"[VideoEnhance] 工作流加载失败 {workflow_file}: {e}")
            return None

        # 2. 上传输入视频
        self._report_progress(0, f"{label}: 上传视频到 ComfyUI...")
        upload = service.upload_image(input_video)
        if not upload or not upload.get("name"):
            print("[VideoEnhance] 上传视频到 ComfyUI 失败")
            return None
        uploaded_name = upload.get("name")
        print(f"[VideoEnhance] 已上传视频: {uploaded_name}")

        # 3. 注入输入视频节点
        injected = False
        for node_id, node in workflow.items():
            class_type = str(node.get("class_type", "") or "")
            inputs = node.get("inputs", {})
            if "LoadVideo" in class_type:
                for k in ("video", "video_path", "filename", "file"):
                    if k in inputs:
                        inputs[k] = uploaded_name
                        injected = True
                        break
                if not injected:
                    inputs["video"] = uploaded_name
                    injected = True
                print(f"[VideoEnhance] 已注入 LoadVideo 节点 {node_id} -> {uploaded_name}")
                break
        if not injected:
            print("[VideoEnhance] 警告: 工作流中未找到 LoadVideo 节点，将使用内置输入")

        # 3.5 注入输出帧率：VHS_VideoCombine 的 frame_rate 需等于「源帧率 × 插值倍数」，
        #     否则帧数变化后成片时长会错误（例如插帧后按固定帧率合成会变慢动作）。
        # 插值倍数：优先识别 RIFE/VFI/Interpolate 命名的节点；用户自备工作流可能用
        # LeeRIFEGPU 之类的类名，此时兜底取带数值 multiplier 输入的节点，避免漏判。
        multiplier = 1.0
        fallback_multiplier = None
        for node in workflow.values():
            class_type = str(node.get("class_type", "") or "")
            inputs = node.get("inputs") or {}
            if "multiplier" not in inputs:
                continue
            try:
                val = float(inputs.get("multiplier") or 1)
            except (TypeError, ValueError):
                continue
            if val <= 1:
                continue
            if any(k in class_type for k in ("Interpolate", "VFI", "RIFE")):
                multiplier = val
                fallback_multiplier = None
                break
            if fallback_multiplier is None:
                fallback_multiplier = val
        if fallback_multiplier is not None:
            multiplier = fallback_multiplier
        src_fps = self._probe_fps(input_video)
        if src_fps > 0:
            target_fps = src_fps * multiplier
            for node in workflow.values():
                if str(node.get("class_type", "") or "") == "VHS_VideoCombine":
                    node.setdefault("inputs", {})["frame_rate"] = target_fps
                    print(f"[VideoEnhance] 设置合成帧率 {target_fps} (源 {src_fps} x 倍数 {multiplier})")

        # 3.6 去水印阶段：注入 Mask Rect Area (Advanced) 的 x/y/width/height
        #     根据 watermark_position 预设（top-right 等）+ 视频尺寸自动换算像素坐标，
        #     用户无需手填坐标。
        if "dewatermark" in os.path.basename(workflow_file).lower() or any(
            "Mask Rect Area" in str(n.get("class_type", "") or "") for n in workflow.values()
        ):
            wm_xywh = self._resolve_watermark_region(input_video)
            if wm_xywh:
                x, y, cw, ch = wm_xywh
                for node in workflow.values():
                    if str(node.get("class_type", "") or "") == "Mask Rect Area (Advanced)":
                        inp = node.setdefault("inputs", {})
                        inp["x"] = x
                        inp["y"] = y
                        inp["width"] = cw
                        inp["height"] = ch
                        print(f"[VideoEnhance] 注入水印区域: x={x} y={y} w={cw} h={ch}"
                              f"  (preset={self.watermark_position})")
                        break

        # 4. 提交并轮询
        queue_res = service.queue_prompt(workflow)
        if not queue_res or "prompt_id" not in queue_res:
            print("[VideoEnhance] ComfyUI 任务提交失败")
            return None
        prompt_id = queue_res["prompt_id"]
        print(f"[VideoEnhance] 工作流已提交, prompt_id={prompt_id}")

        start_time = time.time()
        download_failures = 0
        while True:
            if self.cancelled:
                service.interrupt()
                print("[VideoEnhance] 用户取消，已中断 ComfyUI 任务")
                return None
            if time.time() - start_time > self.stage_timeout:
                print(f"[VideoEnhance] {label} 工作流超时 ({self.stage_timeout}s)")
                return None

            history = service.get_history(prompt_id)
            if prompt_id in history:
                if service.is_prompt_failed(history, prompt_id):
                    # 上报 ComfyUI 节点级错误详情（此前只报"工作流执行报错"，无法定位）
                    err = service.get_prompt_error(history, prompt_id)
                    hint = ""
                    low = err.lower()
                    if "frame interpolation" in low or "interp" in low:
                        hint = "（插帧模型格式不被 ComfyUI 内置节点支持，"
                        hint += "请使用 LeeRIFEGPU 等自定义节点的工作流，或更换 ComfyUI 兼容格式的 RIFE 模型）"
                    elif "could not be loaded with cv" in low:
                        hint = "（ComfyUI 无法读取输入视频，请确认视频已上传且格式为 mp4/avi/mov）"
                    print(f"[VideoEnhance] {label} 工作流执行报错: {err}{hint}")
                    self._report_progress(0, f"{label}失败: {err}{hint}")
                    return None

                outputs = history[prompt_id].get("outputs", {})
                video_files = self._find_output_videos(outputs)
                if video_files:
                    filename, subfolder = video_files[0]
                    download_url = service.get_image_url(filename, subfolder)
                    if service._download_result(download_url, output_path) and self._valid_output(output_path):
                        print(f"[VideoEnhance] {label} 完成: {output_path}")
                        return output_path
                    download_failures += 1
                    if download_failures >= 5:
                        print("[VideoEnhance] 结果下载连续失败，放弃")
                        return None
                    time.sleep(1)
                    continue

            time.sleep(3)

    @staticmethod
    def _find_output_videos(obj, path=""):
        """递归在 ComfyUI outputs 中查找视频文件，返回 [(filename, subfolder), ...]。"""
        if isinstance(obj, dict):
            filename = obj.get("filename", "")
            if isinstance(filename, str) and filename.lower().endswith((".mp4", ".webm", ".gif")):
                return [(filename, obj.get("subfolder", ""))]
            results = []
            for k, v in obj.items():
                results.extend(VideoEnhanceClient._find_output_videos(v, f"{path}.{k}"))
            return results
        if isinstance(obj, list):
            results = []
            for i, item in enumerate(obj):
                results.extend(VideoEnhanceClient._find_output_videos(item, f"{path}[{i}]"))
            return results
        return []

    def _apply_super_resolution(self, video_path: str, output_path: str, width: int, height: int) -> Optional[str]:
        """应用超分辨率（使用FFmpeg高质量缩放作为简化实现）"""
        try:
            # 使用FFmpeg进行高质量缩放（作为超分的简化实现）
            # 实际项目中可以使用Real-ESRGAN等AI模型
            cmd = [
                self.ffmpeg_exe, "-y",
                "-i", video_path,
                "-vf", f"scale={width*2}:{height*2}:flags=lanczos",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-c:a", "copy",
                output_path
            ]

            ok, stderr_tail = self._run_ffmpeg(cmd)
            if ok and self._valid_output(output_path):
                return output_path
            print(f"[VideoEnhance] Super resolution failed: {stderr_tail}")
            return None
        except Exception as e:
            print(f"[VideoEnhance] Super resolution error: {e}")
            return None

    def _apply_quality_enhance(self, video_path: str, output_path: str) -> Optional[str]:
        """应用画质增强（对比度、锐化、降噪）"""
        try:
            # unsharp: 锐化, hqdn3d: 降噪, eq: 对比度/亮度调整
            filters = "unsharp=5:5:1.0:5:5:0.0,hqdn3d=4:4:3:3,eq=contrast=1.1:brightness=0.05"

            cmd = [
                self.ffmpeg_exe, "-y",
                "-i", video_path,
                "-vf", filters,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-c:a", "copy",
                output_path
            ]

            ok, stderr_tail = self._run_ffmpeg(cmd)
            if ok and self._valid_output(output_path):
                return output_path
            print(f"[VideoEnhance] Quality enhance failed: {stderr_tail}")
            return None
        except Exception as e:
            print(f"[VideoEnhance] Quality enhance error: {e}")
            return None

    def _apply_deblur(self, video_path: str, output_path: str) -> Optional[str]:
        """应用去模糊"""
        try:
            # 使用FFmpeg的smartblur进行去模糊
            cmd = [
                self.ffmpeg_exe, "-y",
                "-i", video_path,
                "-vf", "smartblur=lr=5:ls=-1.0",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-c:a", "copy",
                output_path
            ]

            ok, stderr_tail = self._run_ffmpeg(cmd)
            if ok and self._valid_output(output_path):
                return output_path
            print(f"[VideoEnhance] Deblur failed: {stderr_tail}")
            return None
        except Exception as e:
            print(f"[VideoEnhance] Deblur error: {e}")
            return None

    def _apply_frame_interpolation(self, video_path: str, output_path: str, fps: float) -> Optional[str]:
        """应用帧率提升（帧插值）"""
        try:
            # 使用FFmpeg的minterpolate进行帧插值
            # 实际项目中可以使用RIFE等AI帧插值模型
            new_fps = fps * 2
            cmd = [
                self.ffmpeg_exe, "-y",
                "-i", video_path,
                "-vf", f"minterpolate='fps={new_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir'",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-c:a", "copy",
                output_path
            ]

            ok, stderr_tail = self._run_ffmpeg(cmd)
            if ok and self._valid_output(output_path):
                return output_path
            print(f"[VideoEnhance] Frame interpolation failed: {stderr_tail}")
            return None
        except Exception as e:
            print(f"[VideoEnhance] Frame interpolation error: {e}")
            return None

    def _apply_watermark_removal(self, video_path: str, output_path: str) -> Optional[str]:
        """应用去水印（自动检测并模糊水印区域）"""
        try:
            # 使用FFmpeg的delogo滤镜去除水印
            # 这里使用一个通用的水印区域（右上角）作为示例

            # 首先获取视频尺寸
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                print("[VideoEnhance] cannot open video for watermark removal")
                return None
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            if width <= 0 or height <= 0:
                print("[VideoEnhance] invalid video dimensions for watermark removal")
                return None

            # 定义常见水印区域（右上角）
            watermark_w = min(200, width // 5)
            watermark_h = min(80, height // 10)
            watermark_x = width - watermark_w - 20
            watermark_y = 20

            # 使用delogo滤镜
            delogo_filter = f"delogo=x={watermark_x}:y={watermark_y}:w={watermark_w}:h={watermark_h}"

            cmd = [
                self.ffmpeg_exe, "-y",
                "-i", video_path,
                "-vf", delogo_filter,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-c:a", "copy",
                output_path
            ]

            ok, stderr_tail = self._run_ffmpeg(cmd)
            if ok and self._valid_output(output_path):
                return output_path
            print(f"[VideoEnhance] Watermark removal failed: {stderr_tail}")
            return None
        except Exception as e:
            print(f"[VideoEnhance] Watermark removal error: {e}")
            return None


class VideoEnhanceThread:
    """视频增强工作线程（用于后台处理）"""

    def __init__(self, client: VideoEnhanceClient, video_path: str,
                 enhancements: List[str], output_path: str):
        self.client = client
        self.video_path = video_path
        self.enhancements = enhancements
        self.output_path = output_path
        self.is_running = False
        self.result = None
        self.error = None

    def start(self):
        """开始增强处理"""
        self.is_running = True
        try:
            self.result = self.client.enhance_video(
                self.video_path,
                self.enhancements,
                self.output_path
            )
        except Exception as e:
            self.error = str(e)
        finally:
            self.is_running = False

    def stop(self):
        """停止增强处理：通知客户端取消（ffmpeg 子进程会被 kill）。"""
        self.is_running = False
        try:
            self.client.request_cancel()
        except Exception:
            pass
