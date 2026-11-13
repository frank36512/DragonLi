import os
import time
import subprocess
import requests
import imageio_ffmpeg
from PIL import Image
from core.config.config_manager import ConfigManager

try:
    from ai_engine.utils.cancel import interruptible_sleep
except ImportError:
    try:
        from src.ai_engine.utils.cancel import interruptible_sleep
    except ImportError:
        def interruptible_sleep(seconds, step=0.2):
            time.sleep(seconds)
            return False

# 网络超时：(连接超时, 读取超时)，避免服务端挂起时线程永久阻塞
HTTP_TIMEOUT = (15, 60)
DOWNLOAD_TIMEOUT = (15, 300)


def ensure_parent_dir(path):
    """确保文件的父目录存在；路径不含目录段时跳过。"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

class VideoGenClient:
    def __init__(self, api_key=None, base_url=None, model=None, provider=None, api_config=None):
        self.api_key = api_key or "sk-placeholder"
        self.base_url = base_url
        self.model = model or "luma-dream-machine"
        self.provider = provider or "mock"
        # Pass-through of full API config (from resources/config/config.json)
        # This may contain provider-specific options like 'duration', 'hd', 'watermark', 'private', 'notify_hook'
        self.api_config = api_config or {}
        # 最近一次生成失败的可读错误详情，供上层日志/UI展示
        self.last_error = ""

    def generate_video(self, image_path, prompt, output_path, text=None, voice_id=None, aspect_ratio="16:9", language="Chinese", end_image_path=None, input_video_path=None, duration=10, ref_images=None, ref_labels=None, seed=None, negative_prompt="", megapixels=None, resolution_preset=None):
        """
        Generates a video from an image and saves it to output_path.
        Returns: (video_path, task_id) tuple for retry capability, or just video_path for legacy support
        duration: video duration in seconds
        ref_images: Optional list of reference image paths for multi-ref workflows
        ref_labels: 与 ref_images 一一对应的参考图标签（角色/场景/道具），用于提示词 <Picture i> 索引
        seed: 可选随机种子（ComfyUI 用），不传则由工作流自带值决定
        negative_prompt: 额外负面词（ComfyUI 写入负向条件节点；Veo 走 extra_config）
        """
        print(f"Generating video from {image_path} with prompt '{prompt}' using {self.model} (Ratio: {aspect_ratio}, Duration: {duration}s)")
        
        # ComfyUI (Local) - Check BEFORE mock, because ComfyUI has no API key
        is_comfy = (self.provider and "comfy" in self.provider.lower())
        if is_comfy:
            # ratio/seed 必须透传：此前 aspect_ratio 被丢弃，工作流永远按内置 9:16 出片，
            # 项目选 16:9 时片段比例与成片不符
            result = self._generate_comfyui_video(image_path, prompt, output_path,
                                                  duration=duration, ref_images=ref_images,
                                                  ref_labels=ref_labels,
                                                  ratio=aspect_ratio, seed=seed,
                                                  negative_prompt=negative_prompt,
                                                  megapixels=megapixels,
                                                  resolution_preset=resolution_preset)
            if not result:
                # ComfyUI 失败原因透传（节点报错/上传失败/超时等）
                comfy_err = getattr(self, "_comfy_service", None) and getattr(self._comfy_service, "last_error", "")
                if comfy_err:
                    self.last_error = comfy_err
            return result
        
        # Mock generation (Local FFmpeg) - only if provider is mock or key is placeholder AND not ComfyUI
        if self.provider == "mock" or self.api_key == "sk-placeholder":
            return self._generate_ken_burns_video(image_path, output_path)

        # Luma Dream Machine API (Placeholder)
        if self.provider.lower() == "luma":
            return self._generate_luma_video(image_path, prompt, output_path)

        # Runway (via 302.ai or direct)
        if "runway" in self.provider.lower() or "runway" in self.model.lower() or "302" in self.provider.lower():
            return self._generate_runway_video(image_path, prompt, output_path)

        # Veo 3.1 / Sora / GeekAI / crun.ai (including Google official and Comfly)
        # Check provider, model, or base_url for veo/sora/google/comfly/geekai/crun
        base_url_lower = (self.base_url or "").lower()
        provider_lower = self.provider.lower() if self.provider else ""
        model_lower = self.model.lower() if self.model else ""
        if ("veo" in provider_lower or "veo" in model_lower or 
            "google" in provider_lower or "comfly" in provider_lower or
            "sora" in model_lower or "comfly" in base_url_lower or
            "geekai" in provider_lower or "geekai.co" in base_url_lower or
            "crun" in provider_lower or "crun.ai" in base_url_lower or
            "grok" in model_lower):  # Support GrokImagine models on crun.ai
            return self._generate_veo_video(image_path, prompt, output_path, text, voice_id, aspect_ratio, language, end_image_path, input_video_path, negative_prompt=negative_prompt)

        # ComfyUI (Local)
        if "comfy" in self.provider.lower():
            return self._generate_comfyui_video(image_path, prompt, output_path)

        # Default fallback
        return self._generate_ken_burns_video(image_path, output_path)

    def retry_fetch_video(self, task_id, output_path):
        """
        Retry fetching a video using a previously saved task_id.
        Useful when initial generation timed out during download.
        """
        from ai_engine.veo_service import VeoService
        
        print(f"Retrying video fetch for task_id: {task_id}")
        base_url = self.base_url if self.base_url else "https://api.veo.ai/v1"
        veo = VeoService(self.api_key, base_url, extra_config=self.api_config)
        return veo.retry_fetch_video(task_id, output_path)

    def _generate_comfyui_video(self, image_path, prompt, output_path, duration=10, ref_images=None, ref_labels=None, ratio=None, seed=None, negative_prompt="", megapixels=None, resolution_preset=None):
        """
        Generates video using ComfyUI.
        Uses workflow_file from api_config or defaults to model name.
        duration: video duration in seconds
        ref_images: Optional list of reference image paths for multi-ref workflows
        ref_labels: 与 ref_images 同序的标签，用于提示词 <Picture i> 索引映射
        ratio: 目标宽高比（如 16:9 / 9:16），映射到工作流的分辨率选择节点
        seed: 随机种子，None 表示沿用工作流自带值
        negative_prompt: 额外负面词（与内置防字幕禁令合并写入负向节点）
        """
        from ai_engine.video_gen.comfyui_service import ComfyUIService
        import json
        
        print(f"Calling ComfyUI API with duration={duration}s...")
        
        # Use configured base_url or default
        base_url = self.base_url if self.base_url else "http://127.0.0.1:8188"
        
        comfy = ComfyUIService(base_url)
        
        # 工作流只认设置（API 配置 → Video → 工作流文件），不再硬编码默认文件
        workflow_file = self.api_config.get("workflow_file", "") if self.api_config else ""
        if not workflow_file:
            self.last_error = "未配置视频工作流文件（设置 → API配置 → Video → 工作流文件）"
            print(f"Error: {self.last_error}")
            return None
        
        # Resolve workflow path - 工作流在 resources/workflows/ 目录
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        workflow_path = os.path.join(base_dir, "resources", "workflows", workflow_file)
        
        if not os.path.exists(workflow_path):
            print(f"Error: Workflow file not found at {workflow_path}")
            return None
        
        print(f"DEBUG: Using workflow: {workflow_path}")

        comfy = ComfyUIService(base_url)
        self._comfy_service = comfy
        # 透传完整 Video 配置（timeout_minutes / max_ref_images 等），
        # 仅覆盖 workflow_file 为已解析的绝对路径；此前只传
        # {"workflow_file": ...} 会把 timeout_minutes 等用户配置丢掉
        call_config = dict(self.api_config or {})
        call_config["workflow_file"] = workflow_path
        # 显存不足时的降级重试：上层传入的 megapixels 覆盖配置文件里的值
        if megapixels:
            call_config["megapixels"] = megapixels
        # 项目设置里的分辨率档（720p / 1080p）：覆盖接口配置里的档位，
        # 让「项目参数选 720P」真正决定生成分辨率。
        # 但显式 megapixels（OOM 降级学到的安全值）优先级更高，避免降级被档位覆盖回去。
        if resolution_preset and not megapixels:
            call_config["resolution_preset"] = resolution_preset
        return comfy.generate_video(image_path, prompt, output_path, call_config,
                                    duration=duration, ref_images=ref_images,
                                    ref_labels=ref_labels,
                                    ratio=ratio, seed=seed,
                                    negative_prompt=negative_prompt)

    def _generate_veo_video(self, image_path, prompt, output_path, text=None, voice_id=None, aspect_ratio="16:9", language="Chinese", end_image_path=None, input_video_path=None, negative_prompt=""):
        """
        Generates video using Veo 3.1 API.
        """
        from ai_engine.veo_service import VeoService
        
        print("Calling Veo 3.1 API...")
        
        # Use configured base_url or default
        base_url = self.base_url if self.base_url else "https://api.veo.ai/v1"
        
        # negative_prompt / watermark 由 extra_config 合并进请求体
        # （veo_service 的 optional_fields 白名单）；用户未显式配置时默认不出水印
        extra = dict(self.api_config or {})
        extra.setdefault("watermark", False)
        # 防字幕：与 ComfyUI 路径同款——正向末尾追加双语禁令，负向合并禁令词
        try:
            from ai_engine.video_gen.comfyui_service import VIDEO_ANTI_TEXT, _with_anti_text
        except ImportError:
            from src.ai_engine.video_gen.comfyui_service import VIDEO_ANTI_TEXT, _with_anti_text
        prompt = _with_anti_text(prompt)
        negative_prompt = (VIDEO_ANTI_TEXT
                           + (("，" + negative_prompt) if negative_prompt else ""))
        if negative_prompt:
            prev = (extra.get("negative_prompt") or "").strip()
            extra["negative_prompt"] = (prev + ", " if prev else "") + negative_prompt
        print(f"[防字幕] Veo：正向 {len(prompt)} 字（含双语禁令尾缀），"
              f"负向 {len(extra.get('negative_prompt') or '')} 字，"
              f"watermark={extra.get('watermark')}")
        veo = VeoService(self.api_key, base_url, extra_config=extra)
        
        # If text is provided, use generate_scene for full video+audio
        if text:
            print(f"Using Veo Scene Generation (Video+Audio) for: {text[:30]}...")
            return veo.generate_scene(
                image_path=image_path,
                text=text,
                voice_id=voice_id,
                prompt=prompt,
                output_path=output_path,
                model=self.model,
                aspect_ratio=aspect_ratio,
                language=language,
                end_image_path=end_image_path,
                input_video_path=input_video_path
            )
        
        # Otherwise just video
        return veo.generate_video(
            prompt=prompt, 
            image_path=image_path, 
            output_path=output_path,
            model=self.model,
            aspect_ratio=aspect_ratio,
            end_image_path=end_image_path,
            input_video_path=input_video_path
        )

    def _ensure_runway_resolution(self, image_path):
        """
        Resizes/Crops image to meet Runway Gen-4 requirements: 1280x768 or 768x1280.
        Returns path to the processed image (or original if no change needed).
        """
        try:
            with Image.open(image_path) as img:
                w, h = img.size
                
                # Determine target resolution
                if w >= h:
                    target_w, target_h = 1280, 768
                else:
                    target_w, target_h = 768, 1280
                
                if (w, h) == (target_w, target_h):
                    return image_path
                
                print(f"Resizing image from {w}x{h} to {target_w}x{target_h} for Runway...")
                
                # Resize and Crop (Aspect Fill)
                img_ratio = w / h
                target_ratio = target_w / target_h
                
                if img_ratio > target_ratio:
                    # Image is wider than target: resize by height, then crop width
                    new_h = target_h
                    new_w = int(w * (target_h / h))
                else:
                    # Image is taller than target: resize by width, then crop height
                    new_w = target_w
                    new_h = int(h * (target_w / w))
                    
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
                # Center Crop
                left = (new_w - target_w) / 2
                top = (new_h - target_h) / 2
                right = (new_w + target_w) / 2
                bottom = (new_h + target_h) / 2
                
                img = img.crop((left, top, right, bottom))
                
                # Save to temp file
                dir_name = os.path.dirname(image_path)
                base_name = os.path.splitext(os.path.basename(image_path))[0]
                temp_path = os.path.join(dir_name, f"{base_name}_runway_temp.png")
                img.save(temp_path)
                return temp_path
                
        except Exception as e:
            print(f"Error resizing image: {e}")
            return image_path

    def _generate_runway_video(self, image_path, prompt, output_path):
        """
        Generates video using Runway Gen-3/Gen-4 API (specifically 302.ai interface).
        """
        print("Calling Runway API...")

        # Ensure resolution
        original_image_path = image_path
        image_path = self._ensure_runway_resolution(image_path)
        resized_temp = image_path if image_path != original_image_path else None

        # Determine endpoints based on base_url or default to 302.ai
        base_url = self.base_url if self.base_url else "https://api.302.ai"
        if base_url.endswith("/"):
            base_url = base_url[:-1]

        # Construct Submit URL
        # Default to gen4-turbo if not specified, or use model name to decide
        submit_url = f"{base_url}/runway_gen4_turbo/submit"

        # If model implies Gen3, adjust URL (optional, but good for flexibility)
        if "gen3" in self.model.lower():
             submit_url = f"{base_url}/runway_gen3/submit" # Example, adjust if needed

        api_key = self.api_key
        if api_key.startswith("Bearer "):
            api_key = api_key.replace("Bearer ", "")

        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        try:
            # 1. Submit Task
            print(f"Submitting task to {submit_url}")
            with open(image_path, 'rb') as img_file:
                # Explicitly provide filename to ensure correct multipart handling
                files = {
                    'init_image': (os.path.basename(image_path), img_file)
                }
                data = {
                    'text_prompt': prompt if prompt else "",
                    'seconds': "10", # Default to 10s
                    'seed': "",
                    'callback': ""
                }
                
                response = requests.post(submit_url, headers=headers, files=files, data=data, timeout=HTTP_TIMEOUT)

                if response.status_code != 200:
                    print(f"Submit failed: {response.status_code}")
                    print(f"Response body: {response.text}")
                    response.raise_for_status()
                    
                result = response.json()
                
                task_id = result.get("task", {}).get("id")
                if not task_id:
                    print(f"Error: No task ID returned. Response: {result}")
                    return None
                
                print(f"Task submitted. ID: {task_id}")
                
            # 2. Poll for Result
            fetch_url = f"{base_url}/runway/task/{task_id}/fetch"
            
            max_retries = 60 # 5 minutes (5s * 60)
            for i in range(max_retries):
                if interruptible_sleep(5):
                    print("Polling cancelled by user")
                    return None
                print(f"Polling status... ({i+1}/{max_retries})")
                
                resp = requests.get(fetch_url, headers=headers, timeout=HTTP_TIMEOUT)
                if resp.status_code != 200:
                    print(f"Poll failed: {resp.status_code} - {resp.text}")
                    continue

                task_data = resp.json().get("task", {})
                status = task_data.get("status")

                if status == "SUCCEEDED":
                    artifacts = task_data.get("artifacts", [])
                    if artifacts and len(artifacts) > 0:
                        video_url = artifacts[0].get("url")
                        if video_url:
                            print(f"Video generated successfully: {video_url}")
                            # 3. Download Video；校验失败不能向上层返回成功路径
                            if self._download_file(video_url, output_path):
                                return output_path
                            print("Download failed.")
                            return None
                    print("Task succeeded but no video URL found.")
                    return None
                    
                elif status in ["FAILED", "CANCELLED", "THROTTLED"]: # Throttled might need retry logic, but treating as fail for now
                    print(f"Task failed with status: {status}")
                    return None
                    
            print("Timeout waiting for video generation.")
            return None

        except Exception as e:
            print(f"Runway API error: {e}")
            return None
        finally:
            # 清理为 Runway 生成的临时缩放图，避免批量生成时持续堆积
            if resized_temp:
                try:
                    os.remove(resized_temp)
                except OSError:
                    pass

    def _download_file(self, url, output_path):
        """
        下载视频到 output_path。
        返回 True/False；先下载到 .part 临时文件，校验大小后再原子替换，
        避免失败时留下半截文件而调用方却拿到“成功路径”。
        """
        temp_path = output_path + ".part"
        try:
            ensure_parent_dir(output_path)
            with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
                r.raise_for_status()
                file_size = 0
                with open(temp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        file_size += len(chunk)
            if file_size < 1000:
                print(f"Downloaded file too small ({file_size} bytes), treating as failure: {url}")
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                return False
            os.replace(temp_path, output_path)
            print(f"Downloaded video to {output_path} ({file_size} bytes)")
            return True
        except Exception as e:
            print(f"Failed to download video: {e}")
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            return False

    def _generate_luma_video(self, image_path, prompt, output_path):
        """
        Generates video using Luma Dream Machine API (via 302.ai or compatible).
        """
        print("Calling Luma Dream Machine API...")
        
        base_url = self.base_url if self.base_url else "https://api.302.ai"
        if base_url.endswith("/"):
            base_url = base_url[:-1]
            
        # Endpoint for Luma on 302.ai
        submit_url = f"{base_url}/luma/submit"
        
        api_key = self.api_key
        if api_key.startswith("Bearer "):
            api_key = api_key.replace("Bearer ", "")
            
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        try:
            # Submit Task
            # We use multipart/form-data to upload the image directly
            print(f"Submitting task to {submit_url}")
            
            with open(image_path, 'rb') as img_file:
                files = {
                    'image_url': (os.path.basename(image_path), img_file) # 302.ai often maps file fields flexibly, trying 'image_url' as file or 'file'
                }
                # Note: Some proxies might require 'file' or 'image'. 
                # If 'image_url' as a file field doesn't work, we might need to try 'file'.
                # However, based on Runway implementation, we'll try to be consistent.
                # Let's try a safer approach: check if we can use a standard field name.
                # But for now, we'll assume the proxy handles file uploads if we send them.
                
                # Actually, for Luma specifically, if the API expects a URL string in JSON, 
                # and we send a file, the proxy needs to handle it.
                # Let's assume the user has a proxy that supports this, or we fallback.
                
                # Alternative: If we can't upload, we might need to fail or use mock.
                # But let's try the upload.
                
                data = {
                    'prompt': prompt if prompt else "animate this image",
                }
                
                # Note: If the provider is strictly official Luma, this won't work without a URL.
                # But since we are optimizing for the "Local Software" context, we assume the 
                # configured provider (likely 302.ai) supports file upload.
                
                response = requests.post(submit_url, headers=headers, files=files, data=data, timeout=HTTP_TIMEOUT)

                if response.status_code != 200:
                    print(f"Luma Submit failed: {response.status_code}")
                    print(f"Response: {response.text}")
                    # Fallback to Ken Burns if API fails
                    print("Falling back to local effect...")
                    return self._generate_ken_burns_video(image_path, output_path)
                    
                result = response.json()
                task_id = result.get("id") or result.get("task_id")
                
                if not task_id:
                    print(f"Error: No task ID returned. Response: {result}")
                    return self._generate_ken_burns_video(image_path, output_path)
                
                print(f"Luma Task submitted. ID: {task_id}")
                
            # Poll for Result
            fetch_url = f"{base_url}/luma/task/{task_id}/fetch"
            
            max_retries = 60 # 5 minutes
            for i in range(max_retries):
                if interruptible_sleep(5):
                    print("Polling Luma cancelled by user")
                    return self._generate_ken_burns_video(image_path, output_path)
                print(f"Polling Luma status... ({i+1}/{max_retries})")
                
                resp = requests.get(fetch_url, headers=headers, timeout=HTTP_TIMEOUT)
                if resp.status_code != 200:
                    continue

                task_data = resp.json()
                status = task_data.get("status")
                
                if status == "succeeded" or status == "SUCCEEDED":
                    video_data = task_data.get("video")
                    video_url = None
                    if isinstance(video_data, dict):
                        video_url = video_data.get("url")
                    elif isinstance(video_data, str):
                        video_url = video_data
                        
                    if video_url:
                        print(f"Video generated successfully: {video_url}")
                        if self._download_file(video_url, output_path):
                            return output_path
                        print("Luma video download failed.")
                        return None
                        
                elif status in ["failed", "FAILED"]:
                    print(f"Luma task failed: {task_data}")
                    break
                    
            print("Luma generation timed out or failed.")
            return self._generate_ken_burns_video(image_path, output_path)

        except Exception as e:
            print(f"Luma API error: {e}")
            return self._generate_ken_burns_video(image_path, output_path)

    def _generate_ken_burns_video(self, image_path, output_path):
        """
        Uses FFmpeg to create a video with a 'Ken Burns' (slow zoom) effect.
        """
        time.sleep(1) # Simulate processing

        ensure_parent_dir(output_path)

        # 分镜图片已下线：无图片输入时无法做 Ken Burns 兜底，直接返回空
        if not image_path or not os.path.exists(image_path):
            print(f"Input image not found: {image_path}")
            return ""
            
        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            # Zoom in effect: zoom 1.0 -> 1.1 over 3 seconds (75 frames @ 25fps)
            # scale=trunc(iw/2)*2:trunc(ih/2)*2 ensures dimensions are even (required by some codecs)
            # format=yuv420p ensures compatibility
            
            filter_complex = "zoompan=z='min(zoom+0.0015,1.2)':d=125:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1024x1024,scale=trunc(iw/2)*2:trunc(ih/2)*2"
            
            cmd = [
                ffmpeg_exe,
                "-y",
                "-i", image_path,
                "-c:v", "libx264",
                "-t", "4", # 4 seconds
                "-pix_fmt", "yuv420p",
                "-vf", filter_complex,
                output_path
            ]
            
            # Suppress output unless error
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            return output_path
        except subprocess.CalledProcessError as e:
            print(f"Video generation failed: {e}")
            if e.stderr:
                try:
                    print(f"FFmpeg stderr: {e.stderr.decode('utf-8', errors='ignore')}")
                except Exception:
                    print(f"FFmpeg stderr: {e.stderr}")

            # Do NOT create a dummy file, so the UI knows it failed
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            return None
        except Exception as e:
            print(f"Video generation failed (General): {e}")
            return None
