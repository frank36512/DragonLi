# -*- coding: utf-8 -*-
"""成片自检（QA）：对合成后的成片做基本质量校验。

校验项：
1. 文件存在性 + 大小 > 0
2. 分辨率（与预设对比，若提供）
3. 时长（> 阈值，避免空片）
4. 字幕时间戳无重叠
5. 无连续黑帧（采样若干帧判断）
6. 有音频流

输出 QAResult：issues 列表（每项含 severity / category / message / fix_suggestion）。
"""
import os
import re

try:
    import ffmpeg
    import imageio_ffmpeg
except ImportError:
    ffmpeg = None
    imageio_ffmpeg = None


class Issue:
    def __init__(self, severity, category, message, fix_suggestion=""):
        # severity: "error" / "warning" / "info"
        self.severity = severity
        self.category = category  # file / resolution / duration / subtitle / blackframe / audio
        self.message = message
        self.fix_suggestion = fix_suggestion

    def to_dict(self):
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "fix_suggestion": self.fix_suggestion,
        }


class QAResult:
    def __init__(self):
        self.issues = []
        self.passed = True

    def add(self, issue):
        self.issues.append(issue)
        if issue.severity == "error":
            self.passed = False

    def errors(self):
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self):
        return [i for i in self.issues if i.severity == "warning"]

    def summary(self):
        n_err = len(self.errors())
        n_warn = len(self.warnings())
        status = "通过" if self.passed else "失败"
        return f"QA{status}：{n_err} 错误，{n_warn} 警告"

    def to_dict(self):
        return {
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
        }


class QAChecker:
    """成片自检器。所有方法均不抛异常，错误转为 Issue。"""

    def __init__(self):
        self._ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe() if imageio_ffmpeg else "ffmpeg"

    # ---------- 入口 ----------
    def check(self, video_path, preset=None, srt_path=None, min_duration=2.0):
        """对成片做全套自检。返回 QAResult。

        video_path: 成片路径
        preset: 可选 ExportPreset，用于校验分辨率/帧率
        srt_path: 可选字幕路径，校验时间戳重叠
        min_duration: 最小时长阈值（秒）
        """
        result = QAResult()

        # 1. 文件存在性
        if not video_path or not os.path.isfile(video_path):
            result.add(Issue("error", "file", f"成片文件不存在: {video_path}",
                             "检查 _stage_compose 是否成功生成产物"))
            return result
        size_kb = os.path.getsize(video_path) / 1024
        if size_kb < 10:
            result.add(Issue("error", "file", f"成片文件过小（{size_kb:.1f}KB），疑似损坏",
                             "重新合成或检查 ffmpeg 输出"))
            return result

        # 2. 探测流信息
        info = self._probe_streams(video_path)
        vstream = info.get("video")
        astream = info.get("audio")
        duration = info.get("duration", 0.0)

        # 3. 分辨率
        if vstream:
            vw, vh = vstream.get("width"), vstream.get("height")
            if preset and preset.width and preset.height:
                if vw != preset.width or vh != preset.height:
                    result.add(Issue("warning", "resolution",
                                     f"分辨率 {vw}x{vh} 与预设 {preset.width}x{preset.height} 不符",
                                     "重新应用导出预设或检查 apply_preset"))
        else:
            result.add(Issue("error", "resolution", "未检测到视频流",
                             "检查 ffmpeg 合成命令"))

        # 4. 时长
        if duration <= 0:
            result.add(Issue("warning", "duration", "无法探测时长",
                             "检查 ffmpeg 探测；可能缺 ffprobe"))
        elif duration < min_duration:
            result.add(Issue("error", "duration",
                             f"成片时长过短（{duration:.1f}s < {min_duration}s）",
                             "检查素材时长/拼接逻辑"))

        # 5. 音频流
        if not astream:
            result.add(Issue("warning", "audio", "未检测到音频流（无声片）",
                             "检查 TTS/配音是否生成；concat 是否包含音频"))

        # 6. 字幕时间戳
        if srt_path and os.path.isfile(srt_path):
            self._check_srt(srt_path, result)

        # 7. 黑帧采样
        if vstream and duration > 0:
            self._check_black_frames(video_path, duration, result)

        return result

    # ---------- 阶段级 QA 闸门（WB-10）----------
    def check_script(self, script_data):
        """剧本 schema 检查。返回 QAResult。"""
        result = QAResult()
        if not isinstance(script_data, dict):
            result.add(Issue("error", "schema", "剧本数据应为 dict"))
            return result
        
        scenes = script_data.get("shots") or script_data.get("scenes") or []
        if not scenes:
            result.add(Issue("error", "schema", "shots/scenes 为空"))
            return result
        
        for i, shot in enumerate(scenes):
            if not isinstance(shot, dict):
                result.add(Issue("error", "schema", f"shot[{i}] 应为 dict"))
                continue
            if not (shot.get("video_prompt") or "").strip():
                result.add(Issue("warning", "schema", f"shot[{i}] 缺少 video_prompt",
                               "补充视频提示词或重新生成剧本"))
        
        return result

    def check_clips(self, storyboard, clips_dir=None, expected_wh=None):
        """视频片段检查：数量、时长、分辨率。返回 QAResult。"""
        result = QAResult()
        panels = getattr(storyboard, "panels", []) or []
        
        # 分镜图片已下线：每个分镜都应有对应的视频片段
        expected_count = len(panels)
        
        missing = 0
        duration_mismatch = 0
        wrong_res = 0
        
        for panel in panels:
            clip_path = getattr(panel, "video_path", "") or ""
            panel_id = getattr(panel, "panel_id", "?")
            
            # 从 clips_dir 推断 clip 路径
            if not clip_path and clips_dir:
                candidate = os.path.join(clips_dir, f"panel_{panel_id}.mp4")
                if os.path.isfile(candidate):
                    clip_path = candidate
            
            if not clip_path or not os.path.isfile(clip_path):
                missing += 1
                continue
            
            # 时长检查
            panel_duration = getattr(panel, "duration", 0) or 0
            if panel_duration > 0 and ffmpeg:
                try:
                    info = self._probe_streams(clip_path)
                    clip_dur = info.get("duration", 0)
                    if clip_dur > 0 and abs(clip_dur - panel_duration) > 0.5:
                        duration_mismatch += 1
                except Exception:
                    pass
            
            # 分辨率检查：按宽高比比较（±5%）。模型原生分辨率（如 1216x704）
            # 与目标（如 1920x1080）常有轻微比例差，逐像素比较会全部误报
            if expected_wh and ffmpeg:
                try:
                    info = self._probe_streams(clip_path)
                    v = info.get("video") or {}
                    vw, vh = v.get("width", 0), v.get("height", 0)
                    if vw and vh and not self._same_ratio(vw, vh, *expected_wh):
                        wrong_res += 1
                except Exception:
                    pass
        
        if missing > 0:
            result.add(Issue("error", "clips", f"{missing}/{expected_count} 个分镜缺视频片段",
                           "检查片段合成阶段或重跑"))
        if duration_mismatch > 0:
            result.add(Issue("warning", "clips", f"{duration_mismatch} 个片段时长与面板 duration 偏差 >0.5s",
                           "检查音频时长探测或片段生成"))
        if wrong_res > 0:
            result.add(Issue("warning", "clips", f"{wrong_res} 个片段宽高比与预期不符"))
        
        return result

    @staticmethod
    def _same_ratio(w1, h1, w2, h2, tol=0.05):
        """宽高比是否一致（默认容差 ±5%）。"""
        if not (w1 and h1 and w2 and h2):
            return True
        r1 = w1 / float(h1)
        r2 = w2 / float(h2)
        return abs(r1 - r2) / r2 <= tol

    # ---------- 探测 ----------
    def _probe_streams(self, video_path):
        """用 ffmpeg -i 探测视频/音频流 + 时长 + 分辨率。返回 dict。"""
        info = {"video": None, "audio": None, "duration": 0.0}
        if not ffmpeg:
            return info
        try:
            probe = ffmpeg.probe(video_path)
            info["duration"] = float(probe.get("format", {}).get("duration", 0) or 0)
            for s in probe.get("streams", []):
                if s.get("codec_type") == "video" and info["video"] is None:
                    info["video"] = {
                        "width": int(s.get("width", 0) or 0),
                        "height": int(s.get("height", 0) or 0),
                        "fps": s.get("avg_frame_rate", "0/0"),
                    }
                elif s.get("codec_type") == "audio" and info["audio"] is None:
                    info["audio"] = {"sample_rate": s.get("sample_rate"), "channels": s.get("channels")}
            return info
        except Exception:
            pass

        # 退化方案：ffmpeg -i 解析 stderr
        try:
            import subprocess
            cmd = [self._ffmpeg_path, "-i", video_path]
            r = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace")
            out = r.stderr
            m = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", out)
            if m:
                info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            vm = re.search(r"Video: .+, (\d+)x(\d+)", out)
            if vm:
                info["video"] = {"width": int(vm.group(1)), "height": int(vm.group(2)), "fps": ""}
            if "Audio:" in out:
                info["audio"] = {"sample_rate": "", "channels": ""}
        except Exception:
            pass
        return info

    # ---------- 字幕 ----------
    def _check_srt(self, srt_path, result):
        """解析 SRT，检查时间戳重叠与负时长。"""
        try:
            with open(srt_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except Exception as e:
            result.add(Issue("warning", "subtitle", f"字幕读取失败: {e}"))
            return

        # 匹配 00:00:01,500 --> 00:00:03,000
        pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
        times = []
        for m in pattern.finditer(content):
            sh, sm, ss, sms, eh, em, es, ems = m.groups()
            start = int(sh) * 3600 + int(sm) * 60 + int(ss) + int(sms) / 1000
            end = int(eh) * 3600 + int(em) * 60 + int(es) + int(ems) / 1000
            times.append((start, end))

        if not times:
            result.add(Issue("warning", "subtitle", "字幕未解析到任何时间戳",
                             "检查 SRT 格式"))
            return

        # 负时长
        neg = [i for i, (s, e) in enumerate(times) if e < s]
        if neg:
            result.add(Issue("error", "subtitle",
                             f"{len(neg)} 条字幕结束时间早于开始时间",
                             "重新生成字幕"))

        # 重叠
        overlaps = 0
        for i in range(1, len(times)):
            if times[i][0] < times[i - 1][1]:
                overlaps += 1
        if overlaps > 0:
            result.add(Issue("warning", "subtitle",
                             f"{overlaps} 处字幕时间戳重叠",
                             "调整字幕生成逻辑或手动修正 SRT"))

    # ---------- 黑帧 ----------
    def _check_black_frames(self, video_path, duration, result):
        """用 blackdetect 滤镜检测连续黑帧。"""
        try:
            import subprocess
            # blackdetect=d=0.5 检测 >=0.5s 的黑段
            cmd = [
                self._ffmpeg_path, "-i", video_path,
                "-vf", "blackdetect=d=0.5:pix_th=0.10",
                "-an", "-f", "null", "-"
            ]
            r = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace")
            out = r.stderr
            black_segments = re.findall(r"black_duration:([\d.]+)", out)
            if black_segments:
                total_black = sum(float(x) for x in black_segments)
                # 仅当黑段总长 > 成片 10% 才告警
                if duration > 0 and total_black / duration > 0.10:
                    result.add(Issue("warning", "blackframe",
                                     f"检测到 {len(black_segments)} 段黑帧，共 {total_black:.1f}s（占 {total_black/duration*100:.0f}%）",
                                     "检查分镜图是否缺失或合成时静默片段"))
        except Exception as e:
            # 黑帧检测失败不阻断 QA
            print(f"blackdetect check skipped: {e}")
