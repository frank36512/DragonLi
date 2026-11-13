import os
import ffmpeg
import imageio_ffmpeg
import wave
import contextlib
import subprocess
import threading

class VideoComposer:
    def __init__(self):
        # Get ffmpeg executable path from imageio_ffmpeg
        self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        print(f"VideoComposer initialized with ffmpeg: {self.ffmpeg_path}")
        # We don't have ffprobe in imageio_ffmpeg, so probing might fail if we don't have it in system path.
        # We will rely on try-except blocks or alternative duration checking.

    def _run_ffmpeg(self, out_stream, timeout=None, quiet=True):
        """统一的 ffmpeg 运行封装：超时保护 + stderr 透传 + -nostdin。

        Args:
            out_stream: ffmpeg-python 的输出流（已配置好 input/output/filter）
            timeout: 超时秒数；None 时不限制（仅用于已知短操作）
            quiet: True 时 stderr 捕获到异常对象（由 ffmpeg-python 处理）；
                   False 时透传到控制台
        """
        kwargs = dict(cmd=self.ffmpeg_path, overwrite_output=True, quiet=quiet)
        try:
            if timeout:
                # ffmpeg-python 的 run() 不支持 timeout 参数，
                # 改用 run_async + communicate(timeout=...) 实现超时保护。
                # 注意：必须用 communicate 而非 wait，否则 stderr 管道填满后
                # ffmpeg 进程阻塞，wait() 永远等不到（死锁）。
                proc = out_stream.run_async(**kwargs)
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    raise RuntimeError(f"ffmpeg 执行超时（{timeout}s）")
                if proc.returncode != 0:
                    raise ffmpeg.Error(
                        "ffmpeg error",
                        stdout=stdout or b"",
                        stderr=stderr or b"",
                    )
            else:
                out_stream.run(**kwargs)
        except ffmpeg.Error as e:
            # ffmpeg-python 的 str(e) 只有 "ffmpeg error (see stderr output for detail)"，
            # 真实错误在 e.stderr —— 必须透传，否则完全不可诊断
            stderr_text = ""
            if e.stderr:
                try:
                    stderr_text = e.stderr.decode('utf-8', errors='replace')[-3000:]
                except Exception:
                    stderr_text = str(e.stderr)[-3000:]
            print(f"[ffmpeg error] {stderr_text}")
            raise

    def _run_ffmpeg_cmd(self, args, timeout=30):
        """运行 ffmpeg 子进程命令（用于探测等短操作），带超时与 -nostdin。"""
        cmd = [self.ffmpeg_path, '-nostdin'] + args
        return subprocess.run(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', timeout=timeout
        )

    def get_audio_duration(self, audio_path):
        """获取视频或音频文件的时长"""
        # Method 1: Use cv2 for video files (most reliable)
        try:
            import cv2
            cap = cv2.VideoCapture(audio_path)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if fps > 0 and frame_count > 0:
                    duration = frame_count / fps
                    cap.release()
                    print(f"Duration (cv2) for {os.path.basename(audio_path)}: {duration}")
                    return duration
            cap.release()
        except Exception as e:
            print(f"cv2 duration check failed: {e}")
        
        # Method 2: Use wave module if it's a wav file
        if audio_path.lower().endswith('.wav'):
            try:
                with contextlib.closing(wave.open(audio_path, 'r')) as f:
                    frames = f.getnframes()
                    rate = f.getframerate()
                    return frames / float(rate)
            except Exception:
                pass
        
        # Method 3: Try to use ffprobe if available in system
        try:
            probe = ffmpeg.probe(audio_path)
            dur = float(probe['format']['duration'])
            print(f"Duration (ffprobe) for {os.path.basename(audio_path)}: {dur}")
            return dur
        except Exception as e:
            print(f"ffprobe failed: {e}")
            
        # Method 4: Use ffmpeg -i to get duration (fallback if ffprobe missing)
        try:
            import subprocess
            import re
            
            # Use the ffmpeg executable we know exists
            cmd = [self.ffmpeg_path, '-i', audio_path]
            # ffmpeg prints info to stderr
            # 显式指定 utf-8 解码，避免中文 Windows(cp936) 环境解码失败，
            # 进而错误回退到 3.0s 默认时长导致成片被截断
            result = subprocess.run(
                cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace"
            )
            output = result.stderr
            
            # Search for "Duration: 00:00:05.32,"
            match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", output)
            if match:
                hours = float(match.group(1))
                minutes = float(match.group(2))
                seconds = float(match.group(3))
                total_seconds = hours * 3600 + minutes * 60 + seconds
                print(f"Duration (ffmpeg -i) for {os.path.basename(audio_path)}: {total_seconds}")
                return total_seconds
        except Exception as e:
            print(f"ffmpeg duration check failed: {e}")

        print(f"[ERROR] Could not determine duration for {audio_path}, defaulting to 3.0s — 成片可能被截断")
        return 3.0

    def get_video_info(self, path):
        # Method 1: ffprobe
        try:
            probe = ffmpeg.probe(path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            if video_stream:
                return int(video_stream['width']), int(video_stream['height'])
        except Exception:
            pass
            
        # Method 2: ffmpeg -i
        try:
            import subprocess
            import re
            cmd = [self.ffmpeg_path, '-i', path]
            result = subprocess.run(
                cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace"
            )
            output = result.stderr
            # Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 1280x720, 2373 kb/s, ...
            match = re.search(r"Video: .+, (\d+)x(\d+)", output)
            if match:
                return int(match.group(1)), int(match.group(2))
        except Exception as e:
            print(f"ffmpeg video info check failed: {e}")
            
        return None, None

    def create_clip(self, image_path, audio_path, output_path, duration=None, width=1024, height=1024, quality="high"):
        """
        Combines image and audio into a video clip.
        Uses Crop-to-Fill to avoid distortion.
        """
        try:
            # Determine bitrate based on quality
            crf_val = 20
            if quality == "medium":
                crf_val = 24
            elif quality == "low":
                crf_val = 29

            input_image = ffmpeg.input(image_path, loop=1)
            
            if audio_path:
                input_audio = ffmpeg.input(audio_path)
                # Get audio duration if not provided
                if duration is None:
                    duration = self.get_audio_duration(audio_path)
                    print(f"Detected audio duration: {duration}s")
                    # Add a larger buffer to prevent cutting off the end
                    if duration > 0:
                        duration += 0.5 
                
                # Video stream: Scale to fill and crop
                # scale=w:h:force_original_aspect_ratio=increase
                # crop=w:h
                v = (
                    input_image
                    .filter('scale', width, height, force_original_aspect_ratio='increase', flags='lanczos')
                    .filter('crop', width, height)
                )
                
                # Combine
                out = ffmpeg.output(v, input_audio, output_path, t=duration, pix_fmt='yuv420p', vcodec='libx264', crf=crf_val, acodec='aac', ar=44100, ac=2)
            else:
                # Silent clip
                if duration is None: duration = 3.0
                v = (
                    input_image
                    .filter('scale', width, height, force_original_aspect_ratio='increase', flags='lanczos')
                    .filter('crop', width, height)
                )
                a = ffmpeg.input('anullsrc=r=44100:cl=stereo', format='lavfi', t=duration)
                out = ffmpeg.output(v, a, output_path, t=duration, pix_fmt='yuv420p', vcodec='libx264', crf=crf_val, acodec='aac', ar=44100, ac=2)

            # Explicitly pass the ffmpeg executable path
            self._run_ffmpeg(out, timeout=600)
            return output_path, duration
        except Exception as e:
            print(f"Error creating clip: {e}")
            return None, 0

    def extract_audio(self, video_path, output_audio_path):
        """
        Extracts audio from a video file.
        """
        try:
            out = (
                ffmpeg
                .input(video_path)
                .output(output_audio_path, acodec='pcm_s16le', ac=1, ar=16000) # 16kHz mono for Whisper
            )
            self._run_ffmpeg(out, timeout=120)
            return output_audio_path
        except Exception as e:
            print(f"Error extracting audio: {e}")
            return None

    def _has_audio_stream(self, path):
        """探测视频是否含音频流。ffprobe 不可用时回退 ffmpeg -i 输出判断。"""
        try:
            probe = ffmpeg.probe(path)
            return any(s.get('codec_type') == 'audio' for s in probe.get('streams', []))
        except Exception:
            pass
        try:
            import subprocess
            result = subprocess.run(
                [self.ffmpeg_path, '-i', path],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace"
            )
            return 'Audio:' in result.stderr
        except Exception:
            return False

    def create_video_clip(self, video_path, audio_path, output_path, duration=None, width=1024, height=1024, quality="high"):
        """
        Combines video and audio into a video clip.
        - audio_path 有效：用外部音频（TTS）覆盖片段原音
        - audio_path 为空：保留片段自带音轨（MiniMax H3 / LTX 2.5 等自带音频的模型）
        Loops video if shorter than audio.
        Uses Crop-to-Fill to avoid distortion.
        """
        try:
            # Determine bitrate based on quality
            crf_val = 20
            if quality == "medium":
                crf_val = 24
            elif quality == "low":
                crf_val = 29

            has_tts = audio_path and os.path.isfile(audio_path) and os.path.getsize(audio_path) > 0

            if has_tts:
                # Duration driven by TTS audio
                if duration is None:
                    duration = self.get_audio_duration(audio_path)
                    print(f"Detected TTS audio duration: {duration}s")
                    if duration > 0:
                        duration += 1.0

                input_video = ffmpeg.input(video_path, stream_loop=-1)
                input_audio = ffmpeg.input(audio_path)
                v = (
                    input_video
                    .filter('scale', width, height, force_original_aspect_ratio='increase', flags='lanczos')
                    .filter('crop', width, height)
                )
                out = ffmpeg.output(v, input_audio, output_path, t=duration, pix_fmt='yuv420p', vcodec='libx264', crf=crf_val, acodec='aac', ar=44100, ac=2)
            else:
                # 无 TTS：原视频自带音轨时（MiniMax H3 / LTX 2.5 等），不做任何处理——
                # 直接 stream copy 保留原始音视频。此前 scale/crop 后只输出视频流，
                # 音轨被丢弃导致全片无声，且重编码损失画质
                if self._has_audio_stream(video_path):
                    input_video = ffmpeg.input(video_path)
                    out = ffmpeg.output(
                        input_video['v'], input_video['a'], output_path,
                        vcodec='copy', acodec='copy'
                    )
                    self._run_ffmpeg(out, timeout=120)
                    return output_path, duration
                # 无音轨：补一条 anullsrc 静音轨，确保拼接时流布局一致
                input_video = ffmpeg.input(video_path)
                v = (
                    input_video
                    .filter('scale', width, height, force_original_aspect_ratio='increase', flags='lanczos')
                    .filter('crop', width, height)
                )
                clip_dur = duration if (duration and duration > 0) else 5.0
                a = ffmpeg.input(f'anullsrc=r=44100:cl=stereo', format='lavfi', t=clip_dur)
                out = ffmpeg.output(v, a, output_path, t=clip_dur, pix_fmt='yuv420p', vcodec='libx264', crf=crf_val, acodec='aac', ar=44100, ac=2)

            self._run_ffmpeg(out, timeout=600)
            return output_path, duration
        except Exception as e:
            print(f"Error creating video clip: {e}")
            return None, 0

    def burn_subtitles(self, video_path, srt_path, output_path, style_config=None):
        """
        Burns subtitles into the video.
        """
        try:
            # Escape path for Windows: replace \ with / and escape :
            # e.g. C:\file.srt -> C\:/file.srt
            # Actually, ffmpeg filter syntax is complex.
            # Safest is usually forward slashes and escaping the colon after drive letter.
            
            # Method 1: Relative path if possible (risky if CWD differs)
            # Method 2: Full escaping
            
            try:
                # Try to use relative path to avoid drive letter colon issues
                rel_path = os.path.relpath(srt_path)
                safe_srt_path = rel_path.replace('\\', '/')
            except ValueError:
                # If on different drive, fallback to absolute with escaping
                # Escape backslashes and colon
                # For ffmpeg-python, we might need to be careful.
                # Trying: E:/path -> E\:/path
                safe_srt_path = srt_path.replace('\\', '/').replace(':', '\\:')

            print(f"DEBUG: Burning subtitles with path: {safe_srt_path}")
            
            # Style config can be used to set font, size, etc. in ForceStyle
            # e.g. ForceStyle='FontName=Arial,FontSize=24'
            style_str = ""
            if style_config:
                styles = []
                if 'font_size' in style_config:
                    styles.append(f"FontSize={style_config['font_size']}")
                if 'font_color' in style_config:
                    # FFmpeg expects &HBBGGRR
                    # We'll assume white for now or implement conversion later
                    pass
                if styles:
                    style_str = ":force_style='" + ",".join(styles) + "'"

            video = ffmpeg.input(video_path)
            audio = video.audio
            
            # subtitles filter
            # subtitles='filename'[options]
            # On Windows, we need to specify a font that supports Chinese to avoid boxes/garbled text.
            # Microsoft YaHei is a good default.
            
            style_settings = 'FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0,MarginV=20,FontName=Microsoft YaHei'
            
            out = ffmpeg.output(
                video.filter('subtitles', safe_srt_path, force_style=style_settings),
                audio,
                output_path,
                vcodec='libx264',
                acodec='aac',
                ar=44100, # Force standard sample rate
                ac=2      # Force stereo
            )
            self._run_ffmpeg(out, timeout=600, quiet=False)
            return output_path
        except Exception as e:
            print(f"Error burning subtitles: {e}")
            return None

    def replace_audio(self, video_path, audio_path, output_path):
        """
        Replaces the audio track of a video with a new audio file.
        Adjusts video duration to match audio:
        - If Audio < Video: Cuts video.
        - If Audio > Video: Freezes last frame of video to fill time.
        """
        try:
            # Get durations
            audio_dur = self.get_audio_duration(audio_path)
            # We can't easily get video duration without ffprobe, but we can let ffmpeg handle it.
            
            input_video = ffmpeg.input(video_path)
            input_audio = ffmpeg.input(audio_path)
            
            # Logic:
            # We want the output to be exactly audio_dur length.
            # We take the video stream.
            # If we just map them, ffmpeg stops at the shortest input by default (or longest depending on map).
            # To handle "Audio > Video", we need to loop or freeze.
            # Freezing last frame is complex in pure ffmpeg-python without complex filter graphs.
            # Simpler approach: Loop video? No, that looks weird for talking.
            # Let's try a simple "shortest=False" (stops at longest) but pad video?
            # Actually, tpad filter can pad video.
            
            # For now, let's implement the simple "Cut to shortest" or "Stop at audio end".
            # If video is shorter, it will just stop (black screen?).
            # Let's try to force the video to loop if needed? No.
            
            # Robust approach:
            # 1. Generate video stream that is long enough (loop or tpad).
            # 2. Cut to audio duration.
            
            # Using tpad to extend video indefinitely (by repeating last frame)
            # tpad=stop_mode=clone:stop_duration=-1 (infinite)
            # But tpad might not be available in older ffmpeg.
            
            # Fallback: Just combine. If video ends, it ends.
            # But we want to ensure the audio plays fully.
            
            v = input_video['v']
            a = input_audio['a']
            
            # Apply tpad if possible (requires ffmpeg 4.2+)
            # We assume a relatively modern ffmpeg.
            # stop_mode=clone repeats the last frame.
            v = v.filter('tpad', stop_mode='clone', stop_duration=60) # Add 60s buffer
            
            out = ffmpeg.output(v, a, output_path, t=audio_dur, vcodec='libx264', acodec='aac', strict='experimental')
            self._run_ffmpeg(out, timeout=600)
            return output_path
            
        except Exception as e:
            print(f"Error replacing audio: {e}")
            # Fallback: Simple mux (might cut audio if video is short)
            try:
                input_video = ffmpeg.input(video_path)
                input_audio = ffmpeg.input(audio_path)
                out = ffmpeg.output(input_video, input_audio, output_path, c='copy', map_metadata=-1)
                self._run_ffmpeg(out, timeout=120)
                return output_path
            except Exception:
                return None

    def concat_clips(self, clip_paths, output_path, bgm_path=None, quality="high", transition_duration=0.5, transitions=None, preset=None):
        """
        Concatenates multiple video clips into one, optionally adding background music.
        quality: "high" (default), "medium", "low"
        transition_duration: Duration of cross-dissolve transition in seconds. 0 to disable.
        transitions: List of transition dicts [{'type': 'fade', 'duration': 0.5}, ...]
        preset: 可选 ExportPreset，若提供则在拼接后按其 resolution/fps/quality 做最终缩放。
        """
        try:
            # 若提供了 preset，以 preset 的 quality 为准（预设是单一数据源）
            if preset is not None:
                quality = getattr(preset, "quality", quality) or quality

            # Determine bitrate based on quality
            crf_val = 20
            if quality == "medium":
                crf_val = 24
            elif quality == "low":
                crf_val = 29

            print(f"Concatenating with quality={quality} (crf={crf_val}), transition={transition_duration}s, preset={getattr(preset,'key',None)}")

            # Use xfade if transition is requested and we have multiple clips
            if transition_duration > 0 and len(clip_paths) > 1:
                result = self._concat_with_xfade(clip_paths, output_path, bgm_path, crf_val, transition_duration, transitions)
            else:
                result = self._concat_standard(clip_paths, output_path, bgm_path, crf_val)

            if not result:
                return None

            # 若提供了 preset 且需要缩放，做最终重采样
            if preset is not None:
                result = self.apply_preset(result, output_path, preset)
            return result

        except Exception as e:
            print(f"Error concatenating clips: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _concat_standard(self, clip_paths, output_path, bgm_path, crf_val):
        """标准 concat demuxer 拼接（无转场）。成功返回 output_path，失败返回 None。
        自行管理 list_file / temp_video 的清理。"""
        list_path = output_path + ".txt"
        temp_video = output_path + ".temp.mp4"
        try:
            with open(list_path, 'w', encoding='utf-8') as f:
                for path in clip_paths:
                    abs_path = os.path.abspath(path).replace('\\', '/')
                    # concat demuxer 单引号转义：' -> '\''
                    escaped = abs_path.replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            # Generate concatenated video (with voice)
            print("Concatenating clips (re-encoding for sync)...")
            out = (
                ffmpeg
                .input(list_path, format='concat', safe=0)
                .output(temp_video, vcodec='libx264', acodec='aac', pix_fmt='yuv420p', r=25, crf=crf_val)
            )
            self._run_ffmpeg(out, timeout=1800, quiet=False)

            # Mix BGM if provided（成功时内部会把 temp_video 落为 output_path）
            self._mix_bgm(temp_video, output_path, bgm_path)

            if not os.path.exists(output_path):
                print("Concat finished but output file is missing.")
                return None
            return output_path
        finally:
            # 无论成功失败都清理中间文件，避免批量导出时残留堆积
            for tmp in (list_path, temp_video):
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError as cleanup_err:
                    print(f"Warning: failed to remove temp file {tmp}: {cleanup_err}")

    def apply_preset(self, video_path, output_path, preset):
        """按 ExportPreset 对成片做最终缩放/帧率重采样。

        预设 width/height 为 0 表示保持原始；fps 为 0 表示保持原始帧率。
        输出覆盖到 output_path；若与 video_path 相同则先写临时文件再原子替换，
        避免 ffmpeg 同时读写同一文件导致损坏。
        """
        import shutil
        try:
            res = preset.resolution() if preset else None
            fps = getattr(preset, "fps", 0) or 0
            crf_val = {"high": 20, "medium": 24, "low": 29}.get(
                getattr(preset, "quality", "high"), 20)

            # 无需任何缩放/重采样：直接返回原文件（若与目标路径不同则拷贝）
            if not res and fps <= 0:
                if video_path and output_path and os.path.abspath(video_path) != os.path.abspath(output_path):
                    shutil.copyfile(video_path, output_path)
                return output_path if output_path else video_path

            # 输入输出同路径时先写到临时文件，完成后替换
            same_path = (output_path and os.path.abspath(video_path) == os.path.abspath(output_path))
            target = output_path
            if same_path:
                target = output_path + ".preset_tmp.mp4"

            input_v = ffmpeg.input(video_path)
            v = input_v['v']
            a = input_v['a'] if hasattr(input_v, '__getitem__') else None

            # 缩放 + 居中裁剪（避免变形）
            if res:
                w, h = res
                v = (v
                     .filter('scale', w, h, force_original_aspect_ratio='increase', flags='lanczos')
                     .filter('crop', w, h))

            output_kwargs = dict(
                vcodec='libx264', crf=crf_val, pix_fmt='yuv420p',
            )
            if fps > 0:
                output_kwargs['r'] = fps
            if a is not None:
                output_kwargs.update(dict(acodec='aac', ar=44100, ac=2))
                out = ffmpeg.output(v, a, target, **output_kwargs)
            else:
                out = ffmpeg.output(v, target, **output_kwargs)

            self._run_ffmpeg(out, timeout=1800)
            if not (os.path.exists(target) and os.path.getsize(target) > 0):
                print("apply_preset: output missing or empty, falling back to source")
                return video_path

            if same_path:
                # 原子替换：临时文件 -> output_path
                try:
                    os.replace(target, output_path)
                except OSError as replace_err:
                    print(f"apply_preset: os.replace failed ({replace_err}), keeping temp")
                    return target
            return output_path
        except Exception as e:
            print(f"apply_preset failed (using source as-is): {e}")
            # 缩放失败时回退用原文件，避免整片丢失
            if video_path and output_path and os.path.abspath(video_path) != os.path.abspath(output_path):
                try:
                    import shutil as _sh
                    _sh.copyfile(video_path, output_path)
                except Exception:
                    pass
            return video_path

    def _mix_bgm(self, video_path, output_path, bgm_path):
        if bgm_path and os.path.exists(bgm_path):
            try:
                video = ffmpeg.input(video_path)
                bgm = ffmpeg.input(bgm_path)
                
                # Mix: [0:a] is voice, [1:a] is bgm.
                out = ffmpeg.output(
                    video['v'], 
                    ffmpeg.filter([video['a'], bgm.filter('volume', 0.2)], 'amix', inputs=2, duration='first'),
                    output_path,
                    vcodec='copy', # Video is already re-encoded above, so copy is safe here
                    acodec='aac'
                )
                self._run_ffmpeg(out, timeout=600)
                if os.path.exists(video_path) and video_path != output_path:
                    os.remove(video_path)
            except Exception as e:
                print(f"Error mixing BGM: {e}")
                # Fallback: just move video
                if os.path.exists(output_path): os.remove(output_path)
                os.rename(video_path, output_path)
        else:
            # Just rename temp to output
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(video_path, output_path)

    def _concat_with_xfade(self, clip_paths, output_path, bgm_path, crf_val, transition_duration, transitions=None):
        print("Starting Cross-Dissolve Concatenation...")
        import subprocess

        # 转场类型映射到 ffmpeg xfade 的 transition 名称
        transition_map = {
            'fade': 'fade',
            'slide_left': 'slideleft',
            'slide_right': 'slideright',
            'slide_up': 'slideup',
            'slide_down': 'slidedown',
            'wipe_left': 'wipeleft',
            'wipe_right': 'wiperight',
            'wipe_up': 'wipeup',
            'wipe_down': 'wipedown',
            'zoom_in': 'zoomin',
            'zoom_out': 'zoomout',
            'dissolve': 'dissolve',
            'pixelize': 'pixelize',
            'blur': 'fadeblur',  # 使用 fadeblur 代替 blur
            'flash': 'flash',
            'flip': 'hblur',  # 使用 hblur 代替 flip
        }

        # 1. Get durations and target resolution
        durations = []
        target_w, target_h = 0, 0

        for i, p in enumerate(clip_paths):
            d = self.get_audio_duration(p)
            durations.append(d)

            if i == 0:
                w, h = self.get_video_info(p)
                if w and h:
                    target_w, target_h = w, h
                    print(f"Target resolution set to {target_w}x{target_h} from first clip.")
                else:
                    target_w, target_h = 1920, 1080
                    print("Could not determine resolution of first clip, defaulting to 1920x1080")

        # 2. Build Filter Complex
        # Inputs
        inputs = []
        for p in clip_paths:
            inputs.extend(["-i", p])

        filter_complex = ""

        # Pre-process inputs to scale them to target resolution
        # This ensures xfade works even if clips have different resolutions
        scale_filters = ""
        scaled_labels = []

        for i in range(len(clip_paths)):
            lbl = f"s{i}"
            # Scale to fit, then pad to fill
            # Also force fps=25 and format=yuv420p to ensure timebase and pixel format match for xfade
            scale_filters += f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,format=yuv420p[{lbl}];"
            scaled_labels.append(lbl)

        filter_complex += scale_filters

        current_offset = 0

        # Video Chain
        # [s0][s1]xfade=...:offset=O1[v1]
        # [v1][s2]xfade=...:offset=O2[v2]

        # Audio Chain
        # [0:a][1:a]acrossfade=d=T[a1]
        # [a1][2:a]acrossfade=d=T[a2]

        accumulated_duration = 0

        # Video Filters
        last_v_label = scaled_labels[0]
        last_a_label = "0:a"

        for i in range(len(clip_paths) - 1):
            accumulated_duration += durations[i]

            # 获取当前转场设置
            trans_type = 'fade'  # 默认淡入淡出
            trans_dur = transition_duration

            if transitions and i < len(transitions):
                trans_info = transitions[i]
                if trans_info and trans_info.get('type'):
                    mapped_type = transition_map.get(trans_info['type'])
                    if mapped_type:
                        trans_type = mapped_type
                if trans_info and trans_info.get('duration'):
                    trans_dur = trans_info['duration']

            # WB-12: 钳制转场时长，避免 offset 为负导致 xfade 失败
            clip_a_dur = durations[i]
            clip_b_dur = durations[i + 1] if (i + 1) < len(durations) else clip_a_dur
            max_trans = min(clip_a_dur, clip_b_dur) / 2.0
            trans_dur = max(0.05, min(trans_dur, max_trans))

            offset = accumulated_duration - (i + 1) * trans_dur

            next_v_label = f"v_out_{i+1}"
            next_a_label = f"a_out_{i+1}"

            # Video xfade with specific transition type
            # Use last_v_label (previous result) and scaled_labels[i+1] (next clip)
            filter_complex += f"[{last_v_label}][{scaled_labels[i+1]}]xfade=transition={trans_type}:duration={trans_dur}:offset={offset}[{next_v_label}];"

            # Audio acrossfade
            filter_complex += f"[{last_a_label}][{i+1}:a]acrossfade=d={trans_dur}[{next_a_label}];"

            last_v_label = next_v_label
            last_a_label = next_a_label

        # Remove trailing semicolon
        filter_complex = filter_complex.rstrip(';')

        # Map final labels
        map_v = f"[{last_v_label}]"
        map_a = f"[{last_a_label}]"

        temp_video = output_path + ".temp.mp4"

        # Write filter complex to file to avoid length limit
        filter_script_path = output_path + ".filter"
        with open(filter_script_path, "w", encoding="utf-8") as f:
            f.write(filter_complex)

        cmd = [self.ffmpeg_path] + inputs + [
            "-filter_complex_script", filter_script_path,
            "-map", map_v,
            "-map", map_a,
            "-c:v", "libx264",
            "-crf", str(crf_val),
            "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            "-y", temp_video
        ]

        print(f"Running xfade command with {len(clip_paths)} clips...")
        print(f"Filter complex: {filter_complex[:200]}...")

        try:
            # 超时给 30 分钟上限，防止 ffmpeg 卡死时线程永久挂起；
            # stderr 用 utf-8/replace 解码，避免中文环境解码失败丢日志
            proc = subprocess.run(
                cmd, check=False, stderr=subprocess.PIPE,
                timeout=1800
            )
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, cmd,
                    output=proc.stdout, stderr=proc.stderr
                )

            # Mix BGM
            self._mix_bgm(temp_video, output_path, bgm_path)
            if os.path.exists(output_path):
                return output_path
            print("xfade finished but output file is missing.")
            return None

        except subprocess.CalledProcessError as e:
            print(f"FFmpeg xfade failed: returncode={e.returncode}")
            if e.stderr:
                try:
                    print(e.stderr.decode("utf-8", errors="replace")[-3000:])
                except Exception:
                    print(str(e.stderr)[-3000:])
            return None
        except subprocess.TimeoutExpired:
            print("FFmpeg xfade timed out after 1800s")
            return None
        finally:
            # 清理 filter 脚本与临时成片（成功时 _mix_bgm 已移走 temp，删除为幂等空操作）
            for tmp in (filter_script_path, temp_video):
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError as cleanup_err:
                    print(f"Warning: failed to remove temp file {tmp}: {cleanup_err}")
