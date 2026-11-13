import os
import requests
import json
import time
import base64
import re
import uuid

try:
    from ai_engine.utils.cancel import cancelled as _poll_cancelled, interruptible_sleep
except ImportError:
    try:
        from src.ai_engine.utils.cancel import cancelled as _poll_cancelled, interruptible_sleep
    except ImportError:
        def _poll_cancelled():
            return False

        def interruptible_sleep(seconds, step=0.2):
            time.sleep(seconds)
            return False

class VeoService:
    # Patterns that indicate dialogue already exists in the prompt
    DIALOGUE_PATTERNS = [
        r'对白\s*[:：]',           # 对白：xxx
        r'对话\s*[:：]',           # 对话：xxx
        r'\(V\.?O\.?\)',          # (V.O.) 画外音标记
        r'\(O\.?S\.?\)',          # (O.S.) 画外音标记
        r'\(V\.?O\)',             # (VO)
        r'["""][^"""]+["""]',      # 引号包裹的内容
        r'says\s*[:：]',           # says: xxx
        r'speaks\s*[:：]',         # speaks: xxx
        r'台词\s*[:：]',           # 台词：xxx
    ]
    
    @classmethod
    def _has_dialogue_in_prompt(cls, prompt):
        """Check if prompt already contains dialogue indicators."""
        if not prompt:
            return False
        prompt_lower = prompt.lower()
        for pattern in cls.DIALOGUE_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False

    def __init__(self, api_key, base_url, extra_config=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        # Extra provider-specific configuration passed from the caller (VideoGenClient)
        # e.g. {"duration": 10, "hd": true, "watermark": false, "notify_hook": "https://..."}
        self.extra_config = extra_config or {}
        
        # Check if using crun.ai API (uses x-api-key header instead of Bearer)
        self.is_crun = "crun.ai" in self.base_url.lower()
        
        if self.is_crun:
            self.headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json"
            }
        else:
            self.headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

    def _post(self, endpoint, payload):
        # Handle 302.ai style URLs where base_url is the full endpoint
        # Also handle Comfly style URLs ending in /generations
        # And Google Vertex AI URLs
        # And GeekAI style URLs
        # And crun.ai style URLs
        is_full_endpoint = (
            "submit" in self.base_url or 
            self.base_url.endswith("/generations") or 
            "googleapis.com" in self.base_url or
            "geekai.co" in self.base_url or
            "crun.ai" in self.base_url
        )
        
        if is_full_endpoint and (endpoint.startswith("video/") or endpoint.startswith("v2/videos/") or endpoint == "google_predict" or endpoint == "geekai_video" or endpoint.startswith("api/")):
             # If base_url is a full endpoint, use it directly
             # For crun.ai, if base_url already contains the full endpoint path, use it directly
             if "crun.ai" in self.base_url and endpoint.startswith("api/"):
                 # Check if base_url already ends with the endpoint
                 if self.base_url.endswith(endpoint.split("/")[-1]):
                     url = self.base_url
                 else:
                     url = f"{self.base_url}/{endpoint}"
             else:
                 url = self.base_url
        else:
             url = f"{self.base_url}/{endpoint}"
             
        # Handle Google API Key if using generativelanguage.googleapis.com
        if "generativelanguage.googleapis.com" in url:
            if "key=" not in url:
                url += f"?key={self.api_key}"
            # Remove Authorization header as we are using API Key in query param
            if "Authorization" in self.headers:
                del self.headers["Authorization"]

        print(f"Veo Request URL: {url}")
        
        # Determine timeout based on API type
        # timeout=(connect_timeout, read_timeout)
        if "geekai" in url.lower():
            timeout = (120, 600)  # 2分钟连接，10分钟读取
        else:
            timeout = (60, 300)  # 1分钟连接，5分钟读取
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=timeout)
            
            # Handle 422 validation error with detailed message
            if response.status_code == 422:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = json.dumps(error_json, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                print(f"Veo API Validation Error (422): {error_detail}")
                return None
                
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ReadTimeout as e:
            print(f"Veo API Read Timeout ({endpoint}): Request took longer than {timeout[1]}s")
            print(f"Hint: The video generation might still be processing. Try using async mode.")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Veo API Error ({endpoint}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None

    def _post_crun_with_files(self, endpoint, payload, image_paths):
        """
        Special POST method for crun.ai Grok models that require file upload.
        Uses multipart/form-data instead of JSON.
        """
        url = self.base_url
        if not self.base_url.endswith(endpoint.split("/")[-1]):
            url = f"{self.base_url}/{endpoint}"

        print(f"[crun.ai] Uploading files to: {url}")
        print(f"[crun.ai] Image paths: {image_paths}")

        # multipart 请求不能带固定的 Content-Type，requests 需要自行追加 boundary
        upload_headers = {k: v for k, v in self.headers.items() if k.lower() != "content-type"}
        opened_files = []
        try:
            # Prepare multipart form data
            files = []
            for i, img_path in enumerate(image_paths):
                if os.path.exists(img_path):
                    fh = open(img_path, "rb")
                    opened_files.append(fh)
                    files.append(("img_urls", (os.path.basename(img_path), fh)))
                else:
                    print(f"[crun.ai WARNING] Image not found: {img_path}")

            # Prepare other form fields from payload
            data = {
                "model": payload.get("model", ""),
            }
            if "callback_url" in payload:
                data["callback_url"] = payload["callback_url"]

            # Add input as JSON string (not nested form fields)
            input_data = payload.get("input", {})
            # Remove img_urls from input_data as it's handled as files
            input_data_copy = {k: v for k, v in input_data.items() if k != "img_urls"}
            data["input"] = json.dumps(input_data_copy)

            print(f"[crun.ai] Form data: {data}")

            timeout = (60, 300)  # 1分钟连接，5分钟读取
            response = requests.post(url, headers=upload_headers, data=data, files=files, timeout=timeout)

            # Handle 422 validation error with detailed message
            if response.status_code == 422:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = json.dumps(error_json, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                print(f"Veo API Validation Error (422): {error_detail}")
                return None

            response.raise_for_status()
            return response.json()
        except requests.exceptions.ReadTimeout:
            print(f"Veo API Read Timeout ({endpoint}): Request took longer than 300s")
            print(f"Hint: The video generation might still be processing. Try using async mode.")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Veo API Error ({endpoint}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None
        finally:
            # 无论成功或异常都关闭文件句柄，避免 Windows 下图片被锁
            for fh in opened_files:
                try:
                    fh.close()
                except Exception:
                    pass

    def _upload_image_to_catbox(self, image_path):
        """
        Upload image to catbox.moe (free image hosting service) and return public URL.
        This is needed for Grok models that require public image URLs.
        """
        try:
            print(f"[crun.ai] Uploading image to catbox.moe: {image_path}")
            
            with open(image_path, 'rb') as f:
                response = requests.post(
                    'https://litterbox.catbox.moe/resources/internals/api.php',
                    data={
                        'reqtype': 'fileupload',
                        'time': '1h'  # 1 hour expiry
                    },
                    files={'fileToUpload': f},
                    timeout=60
                )
            
            if response.status_code == 200:
                url = response.text.strip()
                if url.startswith('http'):
                    print(f"[crun.ai] Image uploaded successfully: {url}")
                    return url
                else:
                    print(f"[crun.ai] Upload failed: {url}")
                    return None
            else:
                print(f"[crun.ai] Upload failed: HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"[crun.ai] Error uploading image: {e}")
            return None

    def _download_file(self, url, output_path):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        print(f"[Download] Starting download from: {url}")
        print(f"[Download] Output path: {output_path}")
        # 先下载到 .part 临时文件，校验通过后再原子替换，避免半成品文件被当成成功产物
        temp_path = output_path + ".part"
        try:
            with requests.get(url, stream=True, headers=headers, timeout=(30, 300)) as r:
                r.raise_for_status()
                content_type = r.headers.get('content-type', '')
                print(f"[Download] Status: {r.status_code}, Content-Type: {content_type}")

                file_size = 0
                magic = b""
                with open(temp_path, 'wb') as f:
                    for i, chunk in enumerate(r.iter_content(chunk_size=8192)):
                        if i == 0:
                            magic = chunk[:12]
                        f.write(chunk)
                        file_size += len(chunk)

                print(f"[Download] ✓ Downloaded {file_size} bytes")

                # Validate file size
                if file_size < 1000:
                    print(f"[ERROR] Downloaded file is too small ({file_size} bytes), likely invalid")
                    self._safe_remove(temp_path)
                    return None

                # 用魔数判断真实视频：MP4/MOV 在偏移 4 处为 'ftyp'，WebM/Matroska 以 1A45DFA3 开头。
                # 部分 CDN 会返回 text/plain 或缺省 content-type，不能只凭响应头判定。
                is_video_blob = magic[4:8] == b'ftyp' or magic.startswith(b'\x1aE\xdf\xa3')
                ct_ok = ('video' in content_type or 'octet-stream' in content_type
                         or content_type == '' or 'binary' in content_type)
                if not is_video_blob and not ct_ok:
                    print(f"[ERROR] Downloaded content is not a video (content-type={content_type}, magic={magic[:8]!r})")
                    self._safe_remove(temp_path)
                    return None

            os.replace(temp_path, output_path)
            return output_path
        except Exception as e:
            print(f"[Download] Error: {e}")
            self._safe_remove(temp_path)
            return None

    @staticmethod
    def _safe_remove(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    @staticmethod
    def _find_video_uri(obj):
        """在 Google Vertex 响应中递归查找视频 URI（videos[0].uri / 任意 https、gs 链接）。"""
        if isinstance(obj, str):
            if obj.startswith(("gs://", "https://", "http://")):
                return obj
            return None
        if isinstance(obj, dict):
            # 优先匹配常见视频字段
            for key in ("uri", "url", "videoUrl", "video_url"):
                val = obj.get(key)
                if isinstance(val, str) and val.startswith(("gs://", "https://", "http://")):
                    return val
            for val in obj.values():
                found = VeoService._find_video_uri(val)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = VeoService._find_video_uri(item)
                if found:
                    return found
        return None

    def generate_scene(self, image_path, text, voice_id, prompt, sfx_prompt=None, output_path=None, model="veo-3.1", aspect_ratio="9:16", voice_description=None, language="English", end_image_path=None, input_video_path=None):
        """
        Generates a full scene (Video + Audio + LipSync + SFX) in one call using Veo 3.1.
        Constructs a rich prompt including dialogue and visual description.
        """
        # 302.ai / Veo 3.1 Endpoint
        # If base_url is the submit URL, we use it. Otherwise we default to a standard endpoint.
        # But for 302.ai, the user likely configured the full submit URL.
        endpoint = "video/generate" 
        
        # Construct Rich Prompt for Veo 3.1
        # Best Practice: [Visual Description]. [Character] says, "[Dialogue]". [SFX].
        
        full_prompt = prompt.strip()
        if not full_prompt.endswith('.'):
            full_prompt += "."
        
        if sfx_prompt:
            full_prompt += f". Audio atmosphere: {sfx_prompt}"

        # Disable embedded subtitles to avoid garbled text.
        # We will handle subtitles in the final synthesis stage locally.
        
        # Check if using Comfly API (v2 format) or Sora models
        is_comfly = ("comfly" in self.base_url.lower() or 
                     model in ["veo3-pro-frames", "veo2-fast-frames", "veo2-fast-components"] or
                     "sora" in model.lower())
        
        # Check if using GeekAI API
        is_geekai = "geekai.co" in self.base_url.lower()
        
        # Check if using crun.ai API
        is_crun = "crun.ai" in self.base_url.lower()
        
        if is_geekai:
            # Use GeekAI format
            return self._generate_scene_geekai(image_path, text, voice_id, prompt, output_path, model, aspect_ratio, language, end_image_path, input_video_path)
        
        if is_crun:
            # Use crun.ai format
            return self._generate_scene_crun(image_path, text, voice_id, prompt, output_path, model, aspect_ratio, language, end_image_path, input_video_path)
        
        if is_comfly:
            # Use Comfly v2/videos/generations format
            return self._generate_scene_comfly(image_path, text, voice_id, prompt, output_path, model, aspect_ratio, language, end_image_path, input_video_path)
        
        # Legacy 302.ai format
        payload = {
            "model": model,
            "prompt": full_prompt,
            "enhance_prompt": True,
            "subtitle_mode": "none", 
            "enable_subtitles": False,
            "aspect_ratio": aspect_ratio,
            "generation_config": {
                "subtitle_mode": "none",
                "audio_sample_rate": 44100, # Standardize audio output
                "audio_bitrate": 320000
            }
        }
        
        # Handle Images (Start and Optional End)
        images_list = []
        
        # 1. Start Image
        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    data_uri = f"data:{mime};base64,{b64_string}"
                    images_list.append(data_uri)
            except Exception as e:
                print(f"Error encoding start image: {e}")

        # 2. End Image (Optional)
        if end_image_path and os.path.exists(end_image_path):
            try:
                with open(end_image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(end_image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    data_uri = f"data:{mime};base64,{b64_string}"
                    images_list.append(data_uri)
                    print(f"Added end frame from {end_image_path}")
            except Exception as e:
                print(f"Error encoding end image: {e}")

        if images_list:
            # 302.ai / Veo usually accepts "images" list for start/end frames
            payload["images"] = images_list
            # Fallback for single image endpoints
            if len(images_list) > 0:
                payload["image_url"] = images_list[0]
            if len(images_list) > 1:
                payload["end_image_url"] = images_list[1] # Some endpoints might use this key

        # Input Video (for extension)
        if input_video_path and os.path.exists(input_video_path):
            try:
                with open(input_video_path, "rb") as vid_file:
                    b64_string = base64.b64encode(vid_file.read()).decode('utf-8')
                    ext = os.path.splitext(input_video_path)[1].lower()
                    mime = "video/mp4" # Assume mp4
                    payload["video_url"] = f"data:{mime};base64,{b64_string}"
            except Exception as e:
                print(f"Error encoding input video: {e}")

        print(f"Calling Veo Scene API with prompt: {full_prompt[:100]}... Ratio: {aspect_ratio}")
        result = self._post(endpoint, payload)
        print(f"Veo Submit Result: {result}") # Debug print
        
        if result:
            # 302.ai returns {"data": { "id": "..." }} or {"data": "id"} or {"id": "..."}
            task_id = None
            if "data" in result:
                if isinstance(result["data"], dict):
                    task_id = result["data"].get("id")
                else:
                    task_id = result["data"]
            
            if not task_id:
                task_id = result.get("id") or result.get("task_id")
            
            if task_id:
                # If base_url ends with /generations, we use _poll_task_v2 logic which handles .../generations/{id}
                if self.base_url.endswith("/generations"):
                     return self._poll_task_v2(task_id, output_path)
                return self._poll_task(task_id, output_path)
            elif "url" in result:
                if output_path:
                    return self._download_file(result["url"], output_path)
                return result["url"]
        
        return None

    def _generate_scene_geekai(self, image_path, text, voice_id, prompt, output_path, model, aspect_ratio, language, end_image_path, input_video_path):
        """
        Generate scene using GeekAI API (geekai.co).
        Supports video generation with optional audio.
        """
        # Construct image data
        image_data = None
        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    image_data = f"data:{mime};base64,{b64_string}"
            except Exception as e:
                print(f"[GeekAI Scene] Error encoding image: {e}")
        
        # Construct enhanced prompt
        full_prompt = prompt.strip()
        if not full_prompt.endswith('.'):
            full_prompt += "."
        
        # Build payload
        payload = {
            "model": model,
            "prompt": full_prompt,
            "aspect_ratio": aspect_ratio,
            "async": True,  # Use async mode to avoid timeout
        }
        
        # Add image
        if image_data:
            payload["image"] = image_data
        
        # Add end image
        if end_image_path and os.path.exists(end_image_path):
            try:
                with open(end_image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(end_image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    payload["image_tail"] = f"data:{mime};base64,{b64_string}"
            except Exception as e:
                print(f"[GeekAI Scene] Error encoding end image: {e}")
        
        # Enable audio generation if text is provided
        if text:
            payload["with_audio"] = True
        
        # Merge optional fields
        optional_fields = ["duration", "fps", "watermark", "quality", "resolution", "size", "negative_prompt"]
        for k in optional_fields:
            if k in self.extra_config and self.extra_config.get(k) is not None:
                payload[k] = self.extra_config.get(k)
        
        print(f"[GeekAI Scene] Calling geekai.co API")
        print(f"[GeekAI Scene] Model: {model}, Aspect: {aspect_ratio}")
        print(f"[GeekAI Scene] Prompt: {full_prompt[:100]}...")
        print(f"[GeekAI Scene] Image: {'Yes' if image_data else 'No'}, Audio: {'Yes' if text else 'No'}")
        
        result = self._post("geekai_video", payload)
        
        print(f"[GeekAI Scene] Response: {result}")
        
        if result:
            # Check for direct video URL
            if "url" in result:
                if output_path:
                    return (self._download_file(result["url"], output_path), None)
                return (result["url"], None)
            
            # Check for task_id (async mode)。data 字段可能是字符串，不能直接 .get
            data_field = result.get("data")
            data_task_id = data_field.get("task_id") if isinstance(data_field, dict) else None
            task_id = result.get("task_id") or result.get("id") or data_task_id
            if task_id:
                print(f"[GeekAI Scene] Got task_id: {task_id}")
                video_path = self._poll_task_geekai(task_id, output_path)
                return (video_path, task_id)
            
            # Check for video in data field
            if "data" in result:
                data = result["data"]
                if isinstance(data, dict):
                    video_url = data.get("url") or data.get("video_url") or data.get("output")
                    if video_url:
                        if output_path:
                            return (self._download_file(video_url, output_path), None)
                        return (video_url, None)
                elif isinstance(data, str):
                    if output_path:
                        return (self._download_file(data, output_path), None)
                    return (data, None)
        
        print(f"[GeekAI Scene] No video URL or task_id found in response")
        return (None, None)

    def _generate_scene_comfly(self, image_path, text, voice_id, prompt, output_path, model, aspect_ratio, language, end_image_path, input_video_path):
        """
        Generate scene using Comfly v2/videos/generations API with Veo 3.1.
        Veo 3.1 supports automatic audio generation with three types:
        1. Dialogue (对话): Use quotes, e.g., "This must be the key," he said in a low voice
        2. Sound Effects (音效/SFX): Describe sounds explicitly, e.g., The tires emit a harsh scream
        3. Ambient Noise (环境噪声): Describe soundscape, e.g., A faint and distant noise echoes in the background
        """
        # Comfly uses simpler format - just prompt, images, and basic settings
        images = []
        
        # Start Image
        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    images.append(f"data:{mime};base64,{b64_string}")
            except Exception as e:
                print(f"Error encoding start image: {e}")

        # End Image (for veo2-fast-frames which supports 2 frames)
        if end_image_path and os.path.exists(end_image_path) and model == "veo2-fast-frames":
            try:
                with open(end_image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(end_image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    images.append(f"data:{mime};base64,{b64_string}")
                    print(f"Added end frame for veo2-fast-frames")
            except Exception as e:
                print(f"Error encoding end image: {e}")
        
        # Construct enhanced prompt following Veo 3 audio guidelines
        full_prompt = prompt.strip()
        if not full_prompt.endswith('.'):
            full_prompt += "."
        
        # Note: SFX and ambient noise from video_params['audio'] are already in the prompt
        # They were added by construct_video_prompt() in the format:
        # - Audio: [description of sounds/ambient noise]
        # Veo 3 will automatically generate these sounds based on the descriptions
        
        # Construct endpoint
        if self.base_url.endswith("/generations"):
            endpoint = "v2/videos/generations"
        elif "comfly" in self.base_url and not self.base_url.endswith("/generations"):
            endpoint = "v2/videos/generations"
        else:
            endpoint = "v2/videos/generations"
        
        payload = {
            "prompt": full_prompt,
            "model": model,
            "enhance_prompt": True,  # Enable auto-translation, optimization, and audio generation
            "images": images,
            "aspect_ratio": aspect_ratio
        }

        # Include provider-specific options if provided via extra_config (Sora2/Comfly supports these)
        # Accept common keys: duration, hd, watermark, private, notify_hook, fps
        try:
            for k in ["duration", "hd", "watermark", "private", "notify_hook", "fps"]:
                if k in self.extra_config and self.extra_config.get(k) is not None:
                    payload[k] = self.extra_config.get(k)
        except Exception as e:
            print(f"[DEBUG] Ignoring extra_config merge error: {e}")
        
        print(f"[Comfly Veo 3.1] Calling v2/videos/generations")
        print(f"[Comfly Veo 3.1] Model: {model}, enhance_prompt: True (auto-audio enabled)")
        print(f"[Comfly Veo 3.1] Full Prompt: {full_prompt[:150]}...")
        print(f"[Comfly Veo 3.1] Images: {len(images)} frame(s), Aspect: {aspect_ratio}")
        
        result = self._post(endpoint, payload)
        
        print(f"[DEBUG] Comfly API Response: {result}")
        
        if result:
            # Check for task_id in different possible locations
            task_id = None
            if "task_id" in result:
                task_id = result["task_id"]
            elif "data" in result:
                if isinstance(result["data"], dict) and "task_id" in result["data"]:
                    task_id = result["data"]["task_id"]
                elif isinstance(result["data"], str):
                    task_id = result["data"]
            
            if task_id:
                print(f"[Comfly Veo 3.1] Got task_id: {task_id}")
                video_path = self._poll_task_v2(task_id, output_path)
                
                if video_path:
                    if text:
                        print(f"[Comfly Veo 3.1] ✓ Video generated with automatic dialogue audio")
                    else:
                        print(f"[Comfly Veo 3.1] ✓ Video generated (ambient/SFX audio only)")
                
                # Return both video_path and task_id for retry capability
                return (video_path, task_id)
            else:
                print(f"[ERROR] No task_id found in response: {result}")
        else:
            print(f"[ERROR] API request failed, no response")
            
        return (None, None)

    def _generate_scene_crun(self, image_path, text, voice_id, prompt, output_path, model, aspect_ratio, language, end_image_path, input_video_path):
        """
        Generate scene using crun.ai API.
        crun.ai uses a different format:
        - Endpoint: https://api.crun.ai/api/v1/client/job/CreateTask
        - Auth: x-api-key header
        - Payload: {"model": "...", "callback_url": "...", "input": {...}}
        """
        # Debug info
        model_lower = (model or "").lower()
        print(f"[crun.ai DEBUG] Model: {model}")
        print(f"[crun.ai DEBUG] Model lower: {model_lower}")
        print(f"[crun.ai DEBUG] Image path: {image_path}")
        print(f"[crun.ai DEBUG] Image exists: {os.path.exists(image_path) if image_path else False}")
        print(f"[crun.ai DEBUG] Is Grok model: {'grok' in model_lower}")
        
        # Construct enhanced prompt
        full_prompt = prompt.strip()
        if not full_prompt.endswith('.'):
            full_prompt += "."
        
        # Determine duration based on model
        # grok-imagine/i2v only supports 6, 10, or 15 seconds
        if "grok" in model_lower:
            # For grok models, use valid duration values (6, 10, or 15)
            requested_duration = self.extra_config.get("duration", 6)
            # Map to nearest valid duration
            valid_durations = [6, 10, 15]
            duration = min(valid_durations, key=lambda x: abs(x - requested_duration))
            print(f"[crun.ai] Grok model detected, using duration: {duration}s (requested: {requested_duration}s)")
        else:
            duration = self.extra_config.get("duration", 8)
        
        # Build input object
        if "grok" in model_lower:
            # Grok models use different parameters
            input_data = {
                "prompt": full_prompt,
                "duration": duration,
                "resolution": self.extra_config.get("resolution", "720p"),
                "mode": self.extra_config.get("mode", "normal")
            }
        else:
            input_data = {
                "prompt": full_prompt,
                "duration": duration,
                "translate_prompt": True,
                "aspect_ratio": aspect_ratio
            }
        
        # Handle Images (Start frame)
        # Grok models use "img_urls" (array of image URLs), other models use base64 "image"
        if image_path and os.path.exists(image_path):
            try:
                if "grok" in model_lower:
                    # Grok models require public image URLs
                    # Upload image to temporary hosting service
                    public_url = self._upload_image_to_catbox(image_path)
                    if public_url:
                        input_data["img_urls"] = [public_url]
                        print(f"[crun.ai] Added start frame image URL to img_urls (Grok model)")
                    else:
                        print(f"[crun.ai ERROR] Failed to upload image for Grok model")
                else:
                    # Other models use base64 encoded image
                    with open(image_path, "rb") as img_file:
                        b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                        ext = os.path.splitext(image_path)[1].lower()
                        mime = "image/png" if ext == ".png" else "image/jpeg"
                        image_data_uri = f"data:{mime};base64,{b64_string}"
                        input_data["image"] = image_data_uri
                        print(f"[crun.ai] Added start frame image")
            except Exception as e:
                print(f"[crun.ai] Error handling start image: {e}")
        
        # Build payload according to crun.ai format
        payload = {
            "model": model if model else "google/veo3-1-fast-r2v",
            "input": input_data
        }
        
        # Add callback_url if provided in extra_config
        if "callback_url" in self.extra_config:
            payload["callback_url"] = self.extra_config["callback_url"]
        
        print(f"[crun.ai] Calling CreateTask API")
        print(f"[crun.ai] Model: {payload['model']}")
        print(f"[crun.ai] Prompt: {full_prompt[:100]}...")
        print(f"[crun.ai] Aspect Ratio: {aspect_ratio}")
        print(f"[crun.ai DEBUG] Full input_data keys: {list(input_data.keys())}")
        print(f"[crun.ai DEBUG] Full payload: {json.dumps(payload, indent=2)}")
        
        # crun.ai uses /api/v1/client/job/CreateTask endpoint
        endpoint = "api/v1/client/job/CreateTask"
        
        # Use JSON POST for all crun.ai models (including Grok)
        # Grok models use base64 data URIs in img_urls field
        result = self._post(endpoint, payload)
        
        print(f"[crun.ai] Response: {result}")
        
        if result:
            # Check for task_id in different possible locations
            task_id = None
            if "task_id" in result:
                task_id = result["task_id"]
            elif "id" in result:
                task_id = result["id"]
            elif "data" in result:
                if isinstance(result["data"], dict):
                    task_id = result["data"].get("task_id") or result["data"].get("id")
                elif isinstance(result["data"], str):
                    task_id = result["data"]
            
            if task_id:
                print(f"[crun.ai] Got task_id: {task_id}")
                video_path = self._poll_task_crun(task_id, output_path)
                return (video_path, task_id)
            else:
                print(f"[crun.ai ERROR] No task_id found in response: {result}")
        else:
            print(f"[crun.ai ERROR] API request failed, no response")
            
        return (None, None)

    def _poll_task_crun(self, task_id, output_path=None, max_retries=60, interval=5):
        """
        Poll crun.ai task status.
        crun.ai uses: GET /api/v1/client/job/{task_id}
        """
        # Construct poll URL for crun.ai
        base = self.base_url.rstrip('/')
        
        # Remove /CreateTask from base_url if present to get the base endpoint
        if base.endswith("/CreateTask"):
            base = base[:-11]  # Remove "/CreateTask"
        
        # Construct the GetTask URL - try different formats
        # Format 1: /api/v1/client/job/{task_id}
        url = f"{base}/{task_id}"
        
        print(f"[crun.ai Poll] Starting to poll task: {task_id}")
        print(f"[crun.ai Poll] URL: {url}")
        print(f"[crun.ai Poll] Max retries: {max_retries}, Interval: {interval}s")
        
        for i in range(max_retries):
            try:
                response = requests.get(url, headers=self.headers, timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    
                    print(f"[crun.ai Poll] Attempt {i+1}/{max_retries}")
                    print(f"[crun.ai Poll] Response: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
                    
                    # Check status - crun.ai might use different status field names
                    status = data.get("status") or data.get("state") or data.get("task_status")
                    
                    # Check nested data
                    if not status and "data" in data and isinstance(data["data"], dict):
                        status = data["data"].get("status") or data["data"].get("state") or data["data"].get("task_status")
                    
                    print(f"[crun.ai Poll] Status: {status}")
                    
                    if status in ["SUCCEEDED", "COMPLETED", "succeeded", "completed", "SUCCESS", "success", "succeed", "finished", "FINISHED"]:
                        # Find video URL - crun.ai might return it in different fields
                        video_url = None
                        
                        # Check top level
                        if "url" in data:
                            video_url = data["url"]
                        elif "video_url" in data:
                            video_url = data["video_url"]
                        elif "output" in data:
                            if isinstance(data["output"], dict):
                                video_url = data["output"].get("url") or data["output"].get("video_url")
                            elif isinstance(data["output"], str):
                                video_url = data["output"]
                        
                        # Check nested data
                        if not video_url and "data" in data:
                            data_obj = data["data"]
                            if isinstance(data_obj, dict):
                                video_url = data_obj.get("url") or data_obj.get("video_url") or data_obj.get("output")
                                if not video_url and "output" in data_obj and isinstance(data_obj["output"], dict):
                                    video_url = data_obj["output"].get("url") or data_obj["output"].get("video_url")
                            elif isinstance(data_obj, str):
                                video_url = data_obj
                        
                        if video_url:
                            print(f"[crun.ai Poll] ✓ Task completed! Video URL: {video_url[:80]}...")
                            if output_path:
                                return self._download_file(video_url, output_path)
                            return video_url
                        else:
                            print(f"[crun.ai Poll ERROR] Task succeeded but no video URL found")
                            print(f"[crun.ai Poll ERROR] Full response: {json.dumps(data, indent=2)}")
                            return None
                            
                    elif status in ["FAILED", "failed", "FAILURE", "error", "ERROR"]:
                        error_msg = data.get("error") or data.get("message") or "Unknown error"
                        print(f"[crun.ai Poll ERROR] Task failed: {error_msg}")
                        return None
                        
                    elif status in ["PROCESSING", "processing", "PENDING", "pending", "IN_PROGRESS", "running", "RUNNING", "queued", "QUEUED"]:
                        print(f"[crun.ai Poll] Task still processing... waiting {interval}s")
                    else:
                        # If no status field found, task might still be processing
                        print(f"[crun.ai Poll] Unknown or empty status, assuming still processing... waiting {interval}s")
                else:
                    print(f"[crun.ai Poll ERROR] HTTP {response.status_code}: {response.text[:200]}")
            except Exception as e:
                print(f"[crun.ai Poll ERROR] Exception: {e}")
                import traceback
                traceback.print_exc()
            
            if interruptible_sleep(interval):
                print(f"[crun.ai Poll] Cancelled by user")
                return None
        
        print(f"[crun.ai Poll ERROR] Timeout after {max_retries} attempts")
        return None

    def retry_fetch_video(self, task_id, output_path):
        """
        Retry fetching a video using a previously saved task_id.
        This is useful when the initial fetch timed out but the video generation succeeded.
        """
        print(f"[Retry] Attempting to fetch video for task_id: {task_id}")
        return self._poll_task_v2(task_id, output_path)

    def _generate_video_google(self, prompt, image_url, image_path, output_path, model, aspect_ratio):
        # Map friendly model name to Google API model name
        google_model = model
        if model == "veo-3.1":
            google_model = "veo-3.1-generate-preview"
        
        # Construct Vertex AI / Gemini payload
        # This is a best-effort implementation for Google's official API formats
        
        # 1. Try Vertex AI "instances" format (Standard for Google Cloud Models)
        instance = {"prompt": prompt}
        
        if image_path and os.path.exists(image_path):
             try:
                 with open(image_path, "rb") as f:
                     b64_data = base64.b64encode(f.read()).decode("utf-8")
                     instance["image"] = {"bytesBase64Encoded": b64_data}
             except Exception as e:
                 print(f"Error encoding image for Google API: {e}")

        payload = {
            "instances": [instance],
            "parameters": {
                "aspectRatio": aspect_ratio,
                "sampleCount": 1
            }
        }
        
        # If using Gemini API (generativelanguage), format is different
        # However, veo-3.1:predict might use 'instances' even on generativelanguage
        # Let's try to stick to 'instances' if the endpoint is :predict
        if "generativelanguage" in self.base_url and ":predict" not in self.base_url:
             # If it's not explicitly :predict, maybe it's generateContent? 
             # But for Veo we know it's predict or predictLongRunning.
             pass

        print(f"Calling Google Veo API ({google_model}): {prompt[:50]}...")
        
        # Determine endpoint method
        method = "predict"
        if "veo" in google_model:
            method = "predictLongRunning"
            
        # Construct URL if base_url is just the root
        if "models/" not in self.base_url:
             endpoint = f"models/{google_model}:{method}"
        else:
             # If base_url already has model, just append method if missing
             if not self.base_url.endswith(f":{method}"):
                 # Replace existing method or append
                 if ":predict" in self.base_url:
                     endpoint = self.base_url.replace(":predict", f":{method}")
                 else:
                     endpoint = f"{self.base_url}:{method}"
                 # We need to handle the case where _post expects a relative endpoint or full URL
                 # _post logic: if base_url has googleapis.com, it uses it directly.
                 # So we should update self.base_url or pass the full URL to _post?
                 # _post takes 'endpoint'. If we pass "google_predict", it uses base_url.
                 # Let's update base_url temporarily or pass a special marker.
                 pass
             endpoint = "google_predict" # Marker for _post to use base_url (but we might need to update it)

        # Actually, let's just construct the full URL and pass it to _post if we can, 
        # but _post logic is a bit rigid. 
        # Let's rely on _post using self.base_url if it contains googleapis.com.
        # We need to ensure self.base_url is correct.
        
        # If the user provided a base_url like .../models/veo-3.1:predict, we need to change it to .../models/veo-3.1-generate-preview:predictLongRunning
        current_url = self.base_url
        if "veo-3.1:predict" in current_url:
            current_url = current_url.replace("veo-3.1:predict", f"{google_model}:{method}")
        elif "veo-3.1" in current_url and method not in current_url:
             # Append method
             current_url = f"{current_url}:{method}"
        
        # Temporarily swap base_url for this request
        original_base_url = self.base_url
        self.base_url = current_url
        
        try:
            result = self._post("google_predict", payload)
        finally:
            self.base_url = original_base_url
        
        if result:
            print(f"Google API Response: {json.dumps(result, indent=2)}")
            
            # Handle Long Running Operation
            if "name" in result and ("operations" in result["name"] or "models" in result["name"]):
                return self._poll_google_operation(result["name"], output_path)

            # Handle Vertex AI Response (Immediate)
            predictions = result.get("predictions")
            if predictions and len(predictions) > 0:
                pred = predictions[0]
                if isinstance(pred, dict):
                    if "bytesBase64Encoded" in pred:
                        video_data = base64.b64decode(pred["bytesBase64Encoded"])
                        if output_path:
                            with open(output_path, "wb") as f:
                                f.write(video_data)
                            return output_path
                    elif "gcsUri" in pred:
                        return pred["gcsUri"] # Return GCS URI if we can't download it easily
            
        return None

    def _poll_google_operation(self, operation_name, output_path):
        print(f"Polling Google Operation: {operation_name}")
        # Operation name is like "projects/.../operations/..." or "operations/..."
        # We need to construct the poll URL.
        # If using generativelanguage, it's https://generativelanguage.googleapis.com/v1beta/{operation_name}
        
        root_url = "https://generativelanguage.googleapis.com/v1beta"
        if "aiplatform" in self.base_url:
             # Extract root from base_url (e.g. https://us-central1-aiplatform.googleapis.com/v1)
             # Simple heuristic: split by /projects/
             root_url = self.base_url.split("/projects/")[0] + "/v1"
        
        poll_url = f"{root_url}/{operation_name}"
        if "key=" not in poll_url and "generativelanguage" in poll_url:
             poll_url += f"?key={self.api_key}"
             
        for i in range(60): # Poll for 5 minutes (5s interval)
            try:
                # Remove Auth header if using API Key
                headers = self.headers.copy()
                if "key=" in poll_url and "Authorization" in headers:
                    del headers["Authorization"]
                    
                response = requests.get(poll_url, headers=headers, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("done"):
                        if "error" in data:
                            print(f"Operation failed: {data['error']}")
                            return None
                        
                        # Success
                        print("Operation done. Extracting result...")
                        # Result is usually in response.result or response
                        # For Veo, it might be in 'response' -> 'result' -> 'videos' ?
                        # Let's dump it to see
                        # print(json.dumps(data, indent=2))
                        
                        # Try to find video bytes or URI
                        # Structure might be: { "response": { "@type": "...", "videos": [ ... ] } }
                        res = data.get("response", {})
                        # Check for video bytes
                        # This part depends on the specific response schema of Veo 3.1
                        # Assuming it returns a GCS URI or Base64
                        
                        # If we can't find it easily, return the whole response for now
                        # But let's try to find 'bytesBase64Encoded' or 'uri'
                        
                        # Common patterns:
                        # 1. response.videos[0].uri
                        # 2. response.result.videos[0]...
                        
                        # Let's look for any string starting with "gs://" or "https://"
                        video_uri = self._find_video_uri(res)
                        if video_uri:
                            print(f"Extracted video URI: {video_uri}")
                            if output_path and video_uri.startswith("http"):
                                return self._download_file(video_uri, output_path)
                            return video_uri
                        # 找不到可用 URI 时返回 None，不能把 dict 的字符串形式当文件路径返回
                        print(f"Operation succeeded but no video URI found in response: {str(res)[:500]}")
                        return None
                        
                    else:
                        print(f"Operation status: Running... ({i})")
                else:
                    print(f"Poll error: {response.status_code}")
            except Exception as e:
                print(f"Poll exception: {e}")
            
            if interruptible_sleep(5):
                print("Poll cancelled by user")
                return None
            
        return None

    def generate_video(self, prompt, image_url=None, image_path=None, output_path=None, model="veo-3.1", aspect_ratio="9:16", end_image_path=None, input_video_path=None):
        """
        Generates a video from text or image.
        """
        # Check for Google Official API
        if "googleapis.com" in self.base_url:
            return self._generate_video_google(prompt, image_url, image_path, output_path, model, aspect_ratio)

        # Check for GeekAI API (geekai.co)
        if "geekai.co" in self.base_url:
            return self._generate_video_geekai(prompt, image_url, image_path, output_path, model, aspect_ratio, end_image_path)

        # Check for crun.ai API
        if "crun.ai" in self.base_url:
            return self._generate_video_crun(prompt, image_url, image_path, output_path, model, aspect_ratio, end_image_path)

        # Check for Comfly API (force V2 logic if comfly is in URL or sora model)
        if "comfly" in self.base_url or model in ["veo3-pro-frames", "veo2-fast-frames", "veo2-fast-components"] or "sora" in model.lower():
            return self._generate_video_v2(prompt, image_url, image_path, output_path, model, aspect_ratio, end_image_path)

        endpoint = "video/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio
        }
        
        images_list = []
        
        # Start Image
        if image_url:
            images_list.append(image_url)
        elif image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    images_list.append(f"data:{mime};base64,{b64_string}")
            except Exception as e:
                print(f"Error encoding start image: {e}")

        # End Image
        if end_image_path and os.path.exists(end_image_path):
            try:
                with open(end_image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(end_image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    images_list.append(f"data:{mime};base64,{b64_string}")
            except Exception as e:
                print(f"Error encoding end image: {e}")

        if images_list:
            payload["images"] = images_list
            if len(images_list) > 0:
                payload["image_url"] = images_list[0]
            if len(images_list) > 1:
                payload["end_image_url"] = images_list[1]

        # Input Video (for extension)
        if input_video_path and os.path.exists(input_video_path):
            try:
                with open(input_video_path, "rb") as vid_file:
                    b64_string = base64.b64encode(vid_file.read()).decode('utf-8')
                    ext = os.path.splitext(input_video_path)[1].lower()
                    mime = "video/mp4" # Assume mp4
                    payload["video_url"] = f"data:{mime};base64,{b64_string}"
            except Exception as e:
                print(f"Error encoding input video: {e}")

        print(f"Calling Veo Video API: {prompt[:50]}...")
        result = self._post(endpoint, payload)
        
        if result and "url" in result:
            if output_path:
                return self._download_file(result["url"], output_path)
            return result["url"]
        elif result and "id" in result:
            task_id = result["id"]
            return self._poll_task(task_id, output_path)
            
        return None

    def _generate_video_geekai(self, prompt, image_url, image_path, output_path, model, aspect_ratio, end_image_path):
        """
        Generate video using GeekAI API (geekai.co).
        
        API Documentation:
        - Endpoint: https://geekai.co/api/v1/videos/generations
        - Auth: Bearer token in Authorization header
        - Image field: "image" (singular, base64 data URI or URL)
        - Supports: model, prompt, aspect_ratio, duration, fps, watermark, etc.
        """
        # Construct image data
        image_data = None
        if image_url:
            image_data = image_url
        elif image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    image_data = f"data:{mime};base64,{b64_string}"
            except Exception as e:
                print(f"[GeekAI] Error encoding image: {e}")
        
        # Build payload according to GeekAI API spec
        payload = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "async": True,  # Use async mode to avoid timeout
        }
        
        # Add image if provided
        if image_data:
            payload["image"] = image_data
        
        # Add end image (image_tail) if provided
        if end_image_path and os.path.exists(end_image_path):
            try:
                with open(end_image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(end_image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    payload["image_tail"] = f"data:{mime};base64,{b64_string}"
            except Exception as e:
                print(f"[GeekAI] Error encoding end image: {e}")
        
        # Merge optional fields from extra_config
        optional_fields = ["duration", "fps", "watermark", "quality", "resolution", "size", "with_audio", "negative_prompt"]
        for k in optional_fields:
            if k in self.extra_config and self.extra_config.get(k) is not None:
                payload[k] = self.extra_config.get(k)
        
        print(f"[GeekAI] Calling geekai.co API")
        print(f"[GeekAI] Model: {model}, Aspect: {aspect_ratio}")
        print(f"[GeekAI] Prompt: {prompt[:100]}...")
        print(f"[GeekAI] Image: {'Yes' if image_data else 'No'}")
        
        result = self._post("geekai_video", payload)
        
        print(f"[GeekAI] Response: {result}")
        
        if result:
            # Check for direct video URL
            if "url" in result:
                if output_path:
                    return self._download_file(result["url"], output_path)
                return result["url"]
            
            # Check for task_id (async mode)。data 字段可能是字符串，不能直接 .get
            data_field = result.get("data")
            data_task_id = data_field.get("task_id") if isinstance(data_field, dict) else None
            task_id = result.get("task_id") or result.get("id") or data_task_id
            if task_id:
                print(f"[GeekAI] Got task_id: {task_id}")
                return self._poll_task_geekai(task_id, output_path)
            
            # Check for video in data field
            if "data" in result:
                data = result["data"]
                if isinstance(data, dict):
                    video_url = data.get("url") or data.get("video_url") or data.get("output")
                    if video_url:
                        if output_path:
                            return self._download_file(video_url, output_path)
                        return video_url
                elif isinstance(data, str):
                    # data is the video URL directly
                    if output_path:
                        return self._download_file(data, output_path)
                    return data
        
        print(f"[GeekAI] No video URL or task_id found in response")
        return None

    def _poll_task_geekai(self, task_id, output_path=None, max_retries=120, interval=10):
        """
        Poll GeekAI task status.
        
        Args:
            task_id: Task ID to poll
            output_path: Output file path
            max_retries: Maximum number of polling attempts (default 120 = 20 minutes)
            interval: Polling interval in seconds (default 10s)
        """
        # Construct poll URL for GeekAI
        # Correct format: https://geekai.co/api/v1/videos/{task_id}
        base = self.base_url.rstrip('/')
        
        # If base_url ends with /generations, remove it and use /videos
        if base.endswith("/generations"):
            base = base[:-12]  # Remove "/generations"
        
        # Construct the correct URL
        url = f"{base}/{task_id}"
        
        print(f"[GeekAI Poll] Starting to poll task: {task_id}")
        print(f"[GeekAI Poll] URL: {url}")
        print(f"[GeekAI Poll] Max retries: {max_retries}, Interval: {interval}s")
        
        for i in range(max_retries):
            try:
                response = requests.get(url, headers=self.headers, timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    
                    print(f"[GeekAI Poll] Attempt {i+1}/{max_retries}")
                    print(f"[GeekAI Poll] Response: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
                    
                    # Check status
                    status = data.get("status") or data.get("state")
                    
                    # Check nested data
                    if not status and "data" in data and isinstance(data["data"], dict):
                        status = data["data"].get("status")
                    
                    print(f"[GeekAI Poll] Status: {status}")
                    
                    if status in ["SUCCEEDED", "COMPLETED", "succeeded", "completed", "SUCCESS", "success", "succeed"]:
                        # Find video URL
                        video_url = None
                        if "url" in data:
                            video_url = data["url"]
                        elif "video_url" in data:
                            video_url = data["video_url"]
                        elif "data" in data:
                            if isinstance(data["data"], dict):
                                video_url = data["data"].get("url") or data["data"].get("video_url") or data["data"].get("output")
                            elif isinstance(data["data"], str):
                                video_url = data["data"]
                        
                        if video_url:
                            print(f"[GeekAI Poll] ✓ Task completed! Video URL: {video_url[:80]}...")
                            if output_path:
                                return self._download_file(video_url, output_path)
                            return video_url
                        else:
                            print(f"[GeekAI Poll ERROR] Task succeeded but no video URL found")
                            return None
                            
                    elif status in ["FAILED", "failed", "FAILURE", "error"]:
                        error_msg = data.get("error") or data.get("message") or "Unknown error"
                        print(f"[GeekAI Poll ERROR] Task failed: {error_msg}")
                        return None
                        
                    elif status in ["PROCESSING", "processing", "PENDING", "pending", "IN_PROGRESS", "running"]:
                        print(f"[GeekAI Poll] Task still processing... waiting {interval}s")
                    else:
                        print(f"[GeekAI Poll WARNING] Unknown status: {status}")
                else:
                    print(f"[GeekAI Poll ERROR] HTTP {response.status_code}: {response.text[:200]}")
            except Exception as e:
                print(f"[GeekAI Poll ERROR] Exception: {e}")
                import traceback
                traceback.print_exc()
            
            if interruptible_sleep(interval):
                print(f"[GeekAI Poll] Cancelled by user")
                return None
        
        print(f"[GeekAI Poll ERROR] Timeout after {max_retries} attempts")
        return None

    def _generate_video_v2(self, prompt, image_url, image_path, output_path, model, aspect_ratio, end_image_path):
        # Handle Comfly endpoint logic
        if "comfly" in self.base_url and not self.base_url.endswith("/generations"):
             # If base_url is just the domain, append the correct path
             endpoint = "v2/videos/generations"
        elif self.base_url.endswith("/generations"):
             # If base_url is already the full endpoint, use it directly (handled by _post)
             endpoint = "v2/videos/generations" # _post will ignore this if base_url is full
        else:
             endpoint = "v2/videos/generations"
        
        images = []
        # Handle Start Image
        if image_url:
            images.append(image_url)
        elif image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    images.append(f"data:{mime};base64,{b64_string}")
            except Exception as e:
                print(f"Error encoding start image: {e}")

        # Handle End Image (only for supported models)
        if end_image_path and os.path.exists(end_image_path):
             try:
                with open(end_image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    ext = os.path.splitext(end_image_path)[1].lower()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    images.append(f"data:{mime};base64,{b64_string}")
             except Exception as e:
                print(f"Error encoding end image: {e}")

        payload = {
            "prompt": prompt,
            "model": model,
            "enhance_prompt": True,  # Enable auto-translation and optimization
            "images": images,
            "aspect_ratio": aspect_ratio
        }

        # Merge optional provider fields (duration, hd, watermark, private, notify_hook, fps)
        try:
            for k in ["duration", "hd", "watermark", "private", "notify_hook", "fps"]:
                if k in self.extra_config and self.extra_config.get(k) is not None:
                    payload[k] = self.extra_config.get(k)
        except Exception as e:
            print(f"[DEBUG] Ignoring extra_config merge error (v2): {e}")
        
        print(f"[Veo V2] Calling v2/videos/generations with model={model}")
        print(f"[Veo V2] enhance_prompt=True (auto-translate enabled)")
        print(f"[Veo V2] Prompt: {prompt[:100]}...")
        print(f"[Veo V2] Images: {len(images)} frame(s), Aspect: {aspect_ratio}")
        result = self._post(endpoint, payload)
        
        if result and "task_id" in result:
            return self._poll_task_v2(result["task_id"], output_path)
            
        return None

    def _poll_task_v2(self, task_id, output_path=None, max_retries=60, interval=5):
        # Handle URL construction
        if self.base_url.endswith("/generations"):
             url = f"{self.base_url}/{task_id}"
        else:
             endpoint = f"v2/videos/generations/{task_id}"
             url = f"{self.base_url}/{endpoint}"
        
        print(f"[Poll] Starting to poll task: {task_id}")
        print(f"[Poll] URL: {url}")
        
        for i in range(max_retries):
            try:
                response = requests.get(url, headers=self.headers, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    
                    print(f"[Poll] Attempt {i+1}/{max_retries}")
                    print(f"[Poll] Response: {json.dumps(data, indent=2)}")
                    
                    # Comfly Response Format: {"data": {"status": "SUCCESS", "output": "url"}}
                    status = None
                    video_url = None
                    
                    # Check top level status
                    status = data.get("status") or data.get("state")
                    
                    # Check nested data status (Comfly)
                    if not status and "data" in data and isinstance(data["data"], dict):
                        status = data["data"].get("status")
                        video_url = data["data"].get("output")
                    
                    print(f"[Poll] Status: {status}, Video URL: {video_url[:50] if video_url else 'None'}...")

                    if status in ["SUCCEEDED", "COMPLETED", "succeeded", "completed", "SUCCESS"]:
                        if not video_url:
                             video_url = data.get("video_url") or data.get("url")
                        if not video_url:
                            # videos 可能是 [{"url": ...}] 或 ["http..."]，逐项安全取值
                            videos = data.get("videos")
                            if isinstance(videos, list) and videos:
                                first = videos[0]
                                if isinstance(first, dict):
                                    video_url = first.get("url") or first.get("video_url")
                                elif isinstance(first, str):
                                    video_url = first
                        
                        # Check Comfly data.output if still not found
                        if not video_url and "data" in data and isinstance(data["data"], dict):
                            video_url = data["data"].get("output")

                        if video_url:
                            print(f"[Poll] ✓ Task completed! Video URL: {video_url}")
                            if output_path:
                                return self._download_file(video_url, output_path)
                            return video_url
                        else:
                            print(f"[Poll ERROR] Task succeeded but no video URL found")
                            print(f"[Poll ERROR] Full response: {json.dumps(data, indent=2)}")
                            return None
                    elif status in ["FAILED", "failed", "FAILURE"]:
                        print(f"[Poll ERROR] Task failed: {data}")
                        return None
                    elif status in ["PROCESSING", "processing", "PENDING", "pending", "IN_PROGRESS"]:
                        print(f"[Poll] Task still processing... waiting {interval}s")
                    else:
                        print(f"[Poll WARNING] Unknown status: {status}")
                else:
                    print(f"[Poll ERROR] HTTP {response.status_code}: {response.text[:200]}")
            except Exception as e:
                print(f"[Poll ERROR] Exception: {e}")
                import traceback
                traceback.print_exc()
                
            if interruptible_sleep(interval):
                print(f"[Poll] Cancelled by user")
                return None
        
        print(f"[Poll ERROR] Timeout after {max_retries} attempts")
        return None

    def _generate_video_crun(self, prompt, image_url, image_path, output_path, model, aspect_ratio, end_image_path):
        """
        Generate video using crun.ai API.
        
        API Documentation:
        - Endpoint: POST https://api.crun.ai/api/v1/client/job/CreateTask
        - Auth: x-api-key header
        - Payload: {"model": "...", "input": {"prompt": "...", "aspect_ratio": "...", ...}}
        """
        # Determine duration based on model
        # grok-imagine/i2v only supports 6, 10, or 15 seconds
        model_lower = (model or "").lower()
        if "grok" in model_lower:
            # For grok models, use valid duration values (6, 10, or 15)
            requested_duration = self.extra_config.get("duration", 6)
            # Map to nearest valid duration
            valid_durations = [6, 10, 15]
            duration = min(valid_durations, key=lambda x: abs(x - requested_duration))
            print(f"[crun.ai] Grok model detected, using duration: {duration}s (requested: {requested_duration}s)")
        else:
            duration = self.extra_config.get("duration", 8)
        
        # Build input object
        if "grok" in model_lower:
            # Grok models use different parameters
            input_data = {
                "prompt": prompt,
                "duration": duration,
                "resolution": self.extra_config.get("resolution", "720p"),
                "mode": self.extra_config.get("mode", "normal")
            }
        else:
            input_data = {
                "prompt": prompt,
                "duration": duration,
                "translate_prompt": True,
                "aspect_ratio": aspect_ratio
            }
        
        # Handle Start Image
        # Grok models use "img_urls" (array of public URLs), other models use base64 "image"
        if "grok" in model_lower:
            # Grok models require public image URLs
            if image_url:
                # Use provided URL directly
                input_data["img_urls"] = [image_url]
                print(f"[crun.ai] Added start frame image URL to img_urls (Grok model)")
            elif image_path and os.path.exists(image_path):
                # Upload image to temporary hosting service
                public_url = self._upload_image_to_catbox(image_path)
                if public_url:
                    input_data["img_urls"] = [public_url]
                    print(f"[crun.ai] Added start frame image URL to img_urls (Grok model)")
                else:
                    print(f"[crun.ai ERROR] Failed to upload image for Grok model")
        else:
            # Other models use base64 encoded image
            image_data_uri = None
            if image_url:
                image_data_uri = image_url
            elif image_path and os.path.exists(image_path):
                try:
                    with open(image_path, "rb") as img_file:
                        b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                        ext = os.path.splitext(image_path)[1].lower()
                        mime = "image/png" if ext == ".png" else "image/jpeg"
                        image_data_uri = f"data:{mime};base64,{b64_string}"
                except Exception as e:
                    print(f"[crun.ai] Error encoding start image: {e}")
            
            if image_data_uri:
                input_data["image"] = image_data_uri
                print(f"[crun.ai] Added start frame image")
        
        # Build payload according to crun.ai format
        payload = {
            "model": model if model else "google/veo3-1-fast-r2v",
            "input": input_data
        }
        
        # Add callback_url if provided in extra_config
        if "callback_url" in self.extra_config:
            payload["callback_url"] = self.extra_config["callback_url"]
        
        print(f"[crun.ai] Calling CreateTask API")
        print(f"[crun.ai] Model: {payload['model']}")
        print(f"[crun.ai] Prompt: {prompt[:100]}...")
        print(f"[crun.ai] Aspect Ratio: {aspect_ratio}")
        
        # crun.ai uses /api/v1/client/job/CreateTask endpoint
        endpoint = "api/v1/client/job/CreateTask"
        
        # Use JSON POST for all crun.ai models (including Grok)
        # Grok models use base64 data URIs in img_urls field
        result = self._post(endpoint, payload)
        
        print(f"[crun.ai] Response: {result}")
        
        if result:
            # Check for task_id in different possible locations
            task_id = None
            if "task_id" in result:
                task_id = result["task_id"]
            elif "id" in result:
                task_id = result["id"]
            elif "data" in result:
                if isinstance(result["data"], dict):
                    task_id = result["data"].get("task_id") or result["data"].get("id")
                elif isinstance(result["data"], str):
                    task_id = result["data"]
            
            if task_id:
                print(f"[crun.ai] Got task_id: {task_id}")
                return self._poll_task_crun(task_id, output_path)
            else:
                print(f"[crun.ai ERROR] No task_id found in response: {result}")
        else:
            print(f"[crun.ai ERROR] API request failed, no response")
            
        return None

    def generate_audio(self, text, voice_id, output_path=None, model="veo-audio-3.1", language=None, prompt=None):
        """
        Generates speech from text.
        """
        endpoint = "audio/generate"
        payload = {
            "model": model,
            "text": text,
            "voice_id": voice_id
        }
        
        if language:
            payload["language"] = language
            
        if prompt:
            payload["prompt"] = prompt
        
        print(f"Calling Veo Audio API: {text[:50]}... (Lang: {language})")
        result = self._post(endpoint, payload)
        
        if result and "url" in result:
            if output_path:
                return self._download_file(result["url"], output_path)
            return result["url"]
        
        return None

    def generate_sfx(self, prompt, output_path=None, duration=5.0):
        """
        Generates sound effects from text.
        """
        endpoint = "audio/sfx"
        payload = {
            "prompt": prompt,
            "duration": duration
        }
        
        print(f"Calling Veo SFX API: {prompt[:50]}...")
        result = self._post(endpoint, payload)
        
        if result and "url" in result:
            if output_path:
                return self._download_file(result["url"], output_path)
            return result["url"]
        
        return None

    @staticmethod
    def _is_remote_url(value):
        return isinstance(value, str) and value.startswith(("http://", "https://", "gs://"))

    def _ensure_remote_url(self, path_or_url):
        """API 需要公网 URL；若传入本地文件路径，则上传到临时图床换取 URL，失败返回 None。"""
        if not path_or_url:
            return None
        if self._is_remote_url(path_or_url):
            return path_or_url
        if os.path.exists(path_or_url):
            return self._upload_image_to_catbox(path_or_url)
        print(f"[veo] 路径既不是 URL 也不是存在的本地文件: {path_or_url}")
        return None

    def sync_lips(self, video_url, audio_url, output_path=None):
        """
        Syncs video lips to audio.
        """
        # 兼容调用方传入本地文件路径
        video_url = self._ensure_remote_url(video_url)
        audio_url = self._ensure_remote_url(audio_url)
        if not video_url or not audio_url:
            print("LipSync failed: could not resolve video/audio URL")
            return None

        endpoint = "video/lipsync"
        payload = {
            "video_url": video_url,
            "audio_url": audio_url
        }
        
        print(f"Calling Veo LipSync API...")
        result = self._post(endpoint, payload)
        
        if result and "url" in result:
            if output_path:
                return self._download_file(result["url"], output_path)
            return result["url"]
        elif result and "id" in result:
             return self._poll_task(result["id"], output_path)
        
        return None

    def generate_subtitles(self, audio_url, output_path=None):
        """
        Generates subtitles (SRT) from audio.
        """
        # 兼容调用方传入本地音频文件路径
        audio_url = self._ensure_remote_url(audio_url)
        if not audio_url:
            print("Subtitle generation failed: could not resolve audio URL")
            return None

        endpoint = "audio/transcribe"
        payload = {
            "audio_url": audio_url,
            "format": "srt"
        }

        print(f"Calling Veo Subtitle API...")
        result = self._post(endpoint, payload)

        if result and "text" in result:
            # If it returns text content directly
            if output_path:
                try:
                    from core.utils.json_store import atomic_write_text
                    atomic_write_text(output_path, result["text"])
                except ImportError:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(result["text"])
                return output_path
            return result["text"]
        elif result and "url" in result:
            if output_path:
                return self._download_file(result["url"], output_path)
            return result["url"]
            
        return None

    def _poll_task(self, task_id, output_path=None, max_retries=60, interval=2):
        """
        Polls for task completion.
        """
        from urllib.parse import urlparse
        
        urls_to_try = []
        
        # Handle 302.ai style fetch URL
        if "submit" in self.base_url:
            # 预先计算 base_root，兼容 /submit/xxx 与 /submit 两种写法，避免 NameError
            base_root = self.base_url.split("/submit")[0]

            # Strategy 0: Direct append (Documentation style: .../submit/veo3-v2/{task_id})
            urls_to_try.append(f"{self.base_url}/{task_id}")

            # Strategy 1: Replace /submit/xxx with /task/{id}/fetch
            if "/submit/" in self.base_url:
                urls_to_try.append(f"{base_root}/task/{task_id}/fetch")
            
            # Strategy 2: Use domain root + /task/{id}/fetch
            parsed = urlparse(self.base_url)
            domain_root = f"{parsed.scheme}://{parsed.netloc}"
            urls_to_try.append(f"{domain_root}/task/{task_id}/fetch")
            
            # Strategy 3: Use domain root + /302/task/{id}/fetch (Common 302 pattern)
            urls_to_try.append(f"{domain_root}/302/task/{task_id}/fetch")

            # Strategy 4: Try without /fetch (some endpoints use just /task/{id})
            urls_to_try.append(f"{base_root}/task/{task_id}")
            urls_to_try.append(f"{domain_root}/task/{task_id}")
        else:
            endpoint = f"tasks/{task_id}"
            urls_to_try.append(f"{self.base_url}/{endpoint}")
            
        # Deduplicate
        urls_to_try = list(dict.fromkeys(urls_to_try))
        
        active_url = urls_to_try[0]
        print(f"Polling Veo task {task_id}. Initial URL: {active_url}")
        
        for i in range(max_retries):
            try:
                response = requests.get(active_url, headers=self.headers, timeout=30)
                
                # If 404 or 500, try switching to next URL strategy
                if response.status_code in [404, 500]:
                    print(f"Poll {response.status_code} at {active_url}")
                    current_idx = urls_to_try.index(active_url)
                    if current_idx + 1 < len(urls_to_try):
                        active_url = urls_to_try[current_idx + 1]
                        print(f"Switching poll URL to: {active_url}")
                        continue # Retry immediately with new URL
                
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")
                    
                    # Comfly support: Check nested data status
                    if not status and "data" in data and isinstance(data["data"], dict):
                        status = data["data"].get("status")

                    print(f"Poll status: {status}") # Debug
                    
                    if status in ["succeeded", "completed", "SUCCEEDED", "SUCCESS"]:
                        print(f"DEBUG: Full Task Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
                        
                        # Check for subtitles
                        subtitle_url = data.get("subtitleUrl") or data.get("subtitle_url")
                        if not subtitle_url and "output" in data and isinstance(data["output"], dict):
                            subtitle_url = data["output"].get("subtitleUrl") or data["output"].get("subtitle_url")
                        
                        if subtitle_url and output_path:
                            srt_path = os.path.splitext(output_path)[0] + ".srt"
                            print(f"Downloading subtitles to {srt_path}")
                            self._download_file(subtitle_url, srt_path)

                        # ... (Success handling logic) ...
                        result_url = None
                        if "videoUrl" in data:
                             result_url = data["videoUrl"]
                        elif "url" in data:
                             result_url = data["url"]
                        elif isinstance(data.get("output"), dict) and data["output"].get("url"): # 302.ai sometimes uses output.url
                             result_url = data["output"]["url"]
                        elif isinstance(data.get("result"), dict) and data["result"].get("url"):
                             result_url = data["result"]["url"]
                        elif isinstance(data.get("videos"), list) and data["videos"]:
                             first_video = data["videos"][0]
                             result_url = first_video.get("url") if isinstance(first_video, dict) else (first_video if isinstance(first_video, str) else None)
                        elif isinstance(data.get("data"), dict) and data["data"].get("output"): # Comfly
                             result_url = data["data"]["output"]
                        # 只有确实是 URL 字符串才采用，避免把 dict/list 当路径下载
                        if not isinstance(result_url, str) or not result_url:
                             result_url = None
                             
                        if result_url:
                             if output_path:
                                 return self._download_file(result_url, output_path)
                             return result_url
                        else:
                            print(f"Task succeeded but no URL found in: {data}")
                            
                    elif status in ["failed", "FAILED"]:
                        print(f"Veo task failed: {data.get('error')}")
                        return None
                else:
                    print(f"Poll error: {response.status_code} at {active_url}")
            except Exception as e:
                print(f"Poll exception: {e}")
            
            if interruptible_sleep(interval):
                print("Poll cancelled by user")
                return None
            
        print("Veo task timed out.")
        return None
