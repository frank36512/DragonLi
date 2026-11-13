import os
import json
import re
import time
import requests
import base64
from openai import OpenAI
from core.config.config_manager import ConfigManager

# 图片工作流也常带 RAMCleanup 激进清理节点（clean_dlls/clean_processes），
# 会在出图后 trim 进程工作集与 DLL 句柄，导致后续读模型报
# HostBuffer.read_file_slice failed。提交前统一关闭，外部工作流同样生效。
try:
    from ai_engine.video_gen.comfyui_service import sanitize_cleanup_nodes
except ImportError:
    try:
        from src.ai_engine.video_gen.comfyui_service import sanitize_cleanup_nodes
    except ImportError:
        sanitize_cleanup_nodes = None


class ImageGenClient:
    def __init__(self, api_key=None, base_url=None, model=None, provider=None, api_config=None):
        config = ConfigManager()
        key = api_key or os.environ.get("OPENAI_API_KEY") or config.get("OPENAI_API_KEY") or "sk-placeholder"
        self.api_key = key
        self.base_url = base_url
        
        # Fix base_url for OpenAI client if it contains the full path
        openai_base_url = base_url
        if base_url and "/images/generations" in base_url:
            openai_base_url = base_url.split("/images/generations")[0]
            
        self.client = OpenAI(
            api_key=key,
            base_url=openai_base_url,
            timeout=180.0,
            max_retries=1
        )
        self.model = model or "dall-e-3"
        self.provider = provider or "openai"
        self.api_config = api_config or {}
        self.global_workflow = config.get("default_image_workflow", "")

    def generate_image(self, prompt, output_path, ref_images=None, gen_settings=None, status_callback=None, use_line_art=None, anchors=None):
        """
        Generates an image and saves it to output_path.
        status_callback: Optional function to report status strings.
        use_line_art: Explicit flag for line art mode (None=auto-detect from prompt)
        anchors: 可选，一致性锚点 payload（来自 panel.prompt_params["_anchors"]），
                 含 characters/scene，供 ComfyUI 识别 IP-Adapter/ControlNet/LoRA 节点。
        """
        gen_settings = gen_settings or {}
        print(f"Generating image for: {prompt} using {self.model}")

        if status_callback: status_callback("正在初始化...")

        # ComfyUI (Local) - Check provider or base_url
        is_comfy = (self.provider and "comfy" in self.provider.lower()) or \
                   (self.base_url and "8188" in self.base_url)
        if is_comfy:
            return self._generate_comfyui_image(prompt, output_path, ref_images, gen_settings, status_callback, anchors)

        # Check if it's Google provider but NOT Comfly (Comfly uses OpenAI format)
        is_comfly = self.base_url and "comfly" in self.base_url
        if self.provider and self.provider.lower() == "google" and not is_comfly:
            return self._generate_google_image(prompt, output_path, gen_settings, ref_images, status_callback, use_line_art)

        if ref_images:
            print(f"Using reference images: {ref_images}")
        
        # Mock generation if key is placeholder
        if self.client.api_key == "sk-placeholder":
            return self._generate_mock_image(output_path, ref_images, gen_settings, prompt)

        try:
            full_prompt = prompt
            
            print(f"[DEBUG] ImageGenClient: Original prompt length: {len(full_prompt)}")
            print(f"[DEBUG] ImageGenClient: Prompt contains 'LINE ART': {'LINE ART' in full_prompt}")
            print(f"[DEBUG] ImageGenClient: Prompt contains '线稿': {'线稿' in full_prompt}")
            print(f"[DEBUG] ImageGenClient: use_line_art param: {use_line_art}")
            
            # Check if this is a line art request
            # Priority: explicit use_line_art parameter > auto-detect from prompt
            if use_line_art is not None:
                is_line_art = use_line_art
                print(f"[DEBUG] ImageGenClient: Using explicit use_line_art={is_line_art}")
            else:
                is_line_art = "LINE ART" in prompt.upper() or "线稿" in prompt
                print(f"[DEBUG] ImageGenClient: Auto-detected line art: {is_line_art}")
             
            # 1. Handle Reference Images (Character Consistency)
            ref_image_base64_list = []
            for ref_img in (ref_images or []):
                try:
                    base64_str = self._encode_image(ref_img)
                    ref_image_base64_list.append(base64_str)
                    print(f"Encoded reference image: {ref_img}")
                except Exception as e:
                    print(f"Failed to encode reference image {ref_img}: {e}")
            
            if ref_image_base64_list:
                    # 构建参考图片说明，强调场景描述优先
                    ref_instruction = """
 
【参考图片使用说明 - 重要】
1. 参考图片仅用于保持角色外观一致性（服装、发型、面部特征）
2. 必须严格按照上述【场景描述】生成画面，不得偏离
3. 场景环境、背景、动作必须完全按照场景描述，不能复制参考图片的场景
4. 角色应该出现在新的场景环境中，而不是参考图片的环境中
5. 禁止直接复制参考图片的构图或背景"""
                    
                    # 这里只需要添加参考图片说明，不需要再添加线稿/彩色前缀
                    full_prompt = f"{full_prompt}{ref_instruction}"
                    print(f"Total reference images encoded: {len(ref_image_base64_list)}")

            # 从全局工作流提取参数（如 negative_prompt）
            wf_params = self._load_global_workflow_params()
            wf_negative = wf_params.get("negative_prompt", "")

            print(f"[DEBUG] ImageGenClient: Final prompt length: {len(full_prompt)}")
            print(f"[DEBUG] ImageGenClient: Final prompt contains 'LINE ART': {'LINE ART' in full_prompt}")
            
            # 2. Append settings to prompt
            if gen_settings.get("style") and gen_settings.get("style") != "None":
                # Only add style if no reference image (to avoid conflict)
                if not ref_image_base64_list:
                    full_prompt += f", style: {gen_settings.get('style')}"
                else:
                    print(f"Skipping style setting due to reference images presence")

            # Apply negative prompt from global workflow
            if wf_negative and not is_line_art:
                full_prompt += f", avoid: {wf_negative}"
            
            # Determine size based on aspect ratio
            size = "1024x1024"
            ratio = gen_settings.get("aspect_ratio", "16:9")
            resolution = gen_settings.get("resolution", "1080P")
            
            if ratio in ["16:9", "4:3"]:
                size = "1792x1024" # Landscape (Default 1080P-ish for DALL-E 3)
                if resolution == "720P" and self.model != "dall-e-3":
                     # If not DALL-E 3, we might try smaller size if supported
                     # But for safety, we stick to standard sizes or maybe 1280x720 if model allows
                     # For now, let's just log it.
                     pass
            elif ratio in ["9:16", "3:4"]:
                size = "1024x1792" # Portrait
            
            # Determine quality
            quality = gen_settings.get("quality", "standard")

            if status_callback: status_callback("正在请求API生成...")
            
            print("\n" + "="*50)
            print(" [DEBUG] OpenAI/Comfly API Request Payload ")
            print("="*50)
            print(f"Model:      {self.model}")
            print(f"Size:       {size} (Ratio: {ratio})")
            print(f"Resolution: {resolution}")
            print(f"Quality:    {quality}")
            print(f"RefImages:  {len(ref_image_base64_list)} images" if ref_image_base64_list else "RefImages:  None")
            print(f"Prompt:     {full_prompt}")
            print("="*50 + "\n")

            # Comfly needs direct HTTP request for custom parameters
            if is_comfly or "comfly" in str(self.base_url).lower() or self.model == "nano-banana":
                # Use direct HTTP request for Comfly
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": self.model,
                    "prompt": full_prompt,
                    "aspect_ratio": ratio,
                    "n": 1,
                }
                
                if ref_image_base64_list:
                    payload["image"] = ref_image_base64_list
                
                url = f"{self.base_url}/images/generations" if not self.base_url.endswith("/images/generations") else self.base_url
                
                if status_callback: status_callback("正在请求Comfly API...")
                print(f"[DEBUG] Sending request to {url}")
                
                response = requests.post(url, headers=headers, json=payload, timeout=180)
                
                # Retry without reference images if model doesn't support image input
                if response.status_code != 200 and ref_image_base64_list and ("not support image input" in response.text.lower() or "does not support" in response.text.lower()):
                    print(f"Model does not support image input, retrying without reference images")
                    if status_callback: status_callback("模型不支持参考图，降级为纯文本生成...")
                    del payload["image"]
                    response = requests.post(url, headers=headers, json=payload, timeout=180)
                
                if response.status_code == 200:
                    data = response.json()
                    if "data" in data and len(data["data"]) > 0:
                        image_url = data["data"][0].get("url")
                        if image_url:
                            print(f"Got Image URL: {image_url}")
                            
                            if status_callback: status_callback("正在下载图片...")
                            try:
                                img_response = requests.get(image_url, timeout=300)
                                img_response.raise_for_status()
                                
                                with open(output_path, 'wb') as f:
                                    f.write(img_response.content)
                                # Return tuple (path, url) for retry capability
                                return (output_path, image_url)
                            except Exception as download_error:
                                print(f"[ERROR] Download failed: {download_error}")
                                # Return (None, url) so UI can save URL and show retry button
                                raise Exception(f"下载失败: {download_error}. URL: {image_url}")
                
                    raise Exception(f"Unexpected response format: {data}")
                else:
                    raise Exception(f"Comfly API Error: {response.status_code} - {response.text}")
            else:
                # Standard OpenAI format
                api_params = {
                    "model": self.model,
                    "prompt": full_prompt,
                    "size": size,
                    "quality": quality,
                    "n": 1,
                }
                
                if status_callback: status_callback("正在请求OpenAI API...")
                response = self.client.images.generate(**api_params)
                
                if status_callback: status_callback("正在解析响应...")
                
                image_url = response.data[0].url
                print(f"Got Image URL: {image_url}")
                
                if status_callback: status_callback("正在下载图片...")
                
                # Download with validation
                try:
                    img_response = requests.get(image_url, timeout=300)
                    img_response.raise_for_status() # Ensure we got a 200 OK
                    
                    with open(output_path, 'wb') as f:
                        f.write(img_response.content)
                    
                    # Return tuple (path, url) for retry capability    
                    return (output_path, image_url)
                except Exception as download_error:
                    print(f"[ERROR] Download failed: {download_error}")
                    # Raise with URL included so it can be extracted
                    raise Exception(f"下载失败: {download_error}. URL: {image_url}")
            
        except Exception as e:
            print(f"Image Gen Error: {e}")
            # Re-raise exception so UI thread can catch it
            raise e

    def retry_download_image(self, image_url, output_path):
        """
        Retry downloading an image from a saved URL.
        Useful when initial download timed out or failed.
        """
        print(f"[Retry] Downloading image from: {image_url}")
        try:
            img_response = requests.get(image_url, timeout=300)
            img_response.raise_for_status()
            
            with open(output_path, 'wb') as f:
                f.write(img_response.content)
            
            print(f"[Retry] ✓ Image downloaded successfully")
            return output_path
        except Exception as e:
            print(f"[Retry] Error: {e}")
            return None

    def _load_global_workflow_params(self):
        """从全局工作流 JSON 中提取通用参数（如 negative_prompt）。"""
        params = {}
        if not self.global_workflow:
            return params
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        workflow_path = os.path.join(base_dir, "resources", "workflows", self.global_workflow)
        if not os.path.isabs(self.global_workflow):
            workflow_path = os.path.join(base_dir, "resources", "workflows", self.global_workflow)
        else:
            workflow_path = self.global_workflow
        try:
            with open(workflow_path, 'r', encoding='utf-8') as f:
                workflow = json.load(f)
            for node in workflow.values():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") == "CLIPTextEncode":
                    title = (node.get("_meta", {}).get("title", "") or "").lower()
                    if "negative" in title:
                        inputs = node.get("inputs", {})
                        if isinstance(inputs.get("text"), str):
                            params["negative_prompt"] = inputs["text"]
        except Exception as e:
            print(f"[WARN] Failed to load global workflow params: {e}")
        return params

    def _generate_google_image(self, prompt, output_path, gen_settings, ref_images=None, status_callback=None, use_line_art=None):
        try:
            # Construct URL
            url = self.base_url
            if not url:
                raise Exception("Base URL is required for Google provider")
                
            if "{model}" in url:
                url = url.replace("{model}", self.model)
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            full_prompt = prompt
            parts = []

            if status_callback: status_callback("正在处理参考图...")

            # 从全局工作流提取参数（如 negative_prompt）
            wf_params = self._load_global_workflow_params()
            negative_prompt = wf_params.get("negative_prompt", "")
            
            # Check if this is a line art request
            if use_line_art is not None:
                is_line_art = use_line_art
            else:
                is_line_art = "LINE ART" in prompt.upper() or "线稿" in prompt
            
            
            print(f"[DEBUG] Google Provider: use_line_art={use_line_art}, is_line_art={is_line_art}")
            
            # 2. Handle Style (only if not line art mode)
            if gen_settings.get("style") and gen_settings.get("style") != "None" and not is_line_art:
                 full_prompt += f", style: {gen_settings.get('style')}"

            # Apply negative prompt from global workflow
            if negative_prompt and not is_line_art:
                full_prompt += f", avoid: {negative_prompt}"

            # Add text prompt to parts
            parts.insert(0, {"text": full_prompt})
            
            # 1. Handle Reference Images
            if ref_images and len(ref_images) > 0:
                for img_path in ref_images:
                    try:
                        b64_data = self._encode_image(img_path)
                        mime_type = "image/png"
                        if img_path.lower().endswith(".jpg") or img_path.lower().endswith(".jpeg"):
                            mime_type = "image/jpeg"
                        elif img_path.lower().endswith(".webp"):
                            mime_type = "image/webp"
                        
                        parts.append({
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_data
                            }
                        })
                    except Exception as e:
                        print(f"Failed to encode reference image {img_path}: {e}")

            # 3. Handle Aspect Ratio
            aspect_ratio = gen_settings.get("aspect_ratio", "1:1")
            resolution = gen_settings.get("resolution", "1080P")
            
            payload = {
                "contents": [
                    {
                        "parts": parts
                    }
                ],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                    "aspectRatio": aspect_ratio
                }
            }
            
            # 302.ai specific query param for URL output
            params = {"response_format": "url"}
            
            if status_callback: status_callback("正在请求Google API...")
            
            print("\n" + "="*50)
            print(" [DEBUG] Google API Request Payload ")
            print("="*50)
            print(f"URL:        {url}")
            print(f"Model:      {self.model}")
            print(f"Ratio:      {aspect_ratio}")
            print(f"Resolution: {resolution}")
            print(f"Prompt:     {full_prompt}")
            print(f"RefImgs:    {len(ref_images) if ref_images else 0}")
            print("="*50 + "\n")
            
            response = requests.post(url, headers=headers, json=payload, params=params, timeout=180)
            
            # Retry without reference images if model doesn't support image input
            if response.status_code != 200 and ref_images and ("not support image input" in response.text.lower() or "does not support" in response.text.lower()):
                print(f"Model does not support image input, retrying without reference images")
                if status_callback: status_callback("模型不支持参考图，降级为纯文本生成...")
                payload["contents"] = [{"parts": [{"text": full_prompt}]}]
                response = requests.post(url, headers=headers, json=payload, params=params, timeout=180)
            
            if response.status_code == 200:
                if status_callback: status_callback("正在解析Google响应...")
                data = response.json()
                # Extract URL: candidates[0].content.parts[0].url
                if "candidates" in data and len(data["candidates"]) > 0:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts and "url" in parts[0]:
                        image_url = parts[0]["url"]
                        print(f"Image URL: {image_url}")
                        
                        if status_callback: status_callback("正在下载图片...")
                        img_response = requests.get(image_url, timeout=300)
                        img_response.raise_for_status()
                        
                        with open(output_path, 'wb') as f:
                            f.write(img_response.content)
                        return output_path
                
                print(f"Unexpected response format: {data}")
                raise Exception(f"Unexpected response format: {data}")
            else:
                print(f"Google Image Gen Error: {response.text}")
                raise Exception(f"Google API Error: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"Google Image Gen Exception: {e}")
            raise e

    def _encode_image(self, image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _analyze_ref_image(self, image_path):
        """
        Uses a Vision model (GPT-4o) to describe the reference image.
        """
        try:
            base64_image = self._encode_image(image_path)
            
            # Ensure we are using a model that supports vision
            vision_model = "gpt-4o" 
            
            # If self.client is configured for Google (REST URL), we can't use it for OpenAI Chat Completion.
            # We need a client configured for an LLM provider (OpenAI compatible).
            analysis_client = self.client
            
            # Check if current client is likely incompatible (e.g. Google REST URL)
            if "api.302.ai/v1/v1beta" in str(self.base_url):
                # Create a temporary client using config
                config = ConfigManager()
                # Try to find a valid LLM config
                llm_config = None
                for c in (config.get("api_configs") or []):
                    if c.get("type") == "LLM" and c.get("provider") == "openai":
                        llm_config = c
                        break
                
                if llm_config:
                    analysis_client = OpenAI(
                        api_key=llm_config["api_key"],
                        base_url=llm_config["base_url"]
                    )
                else:
                    # Fallback to env vars or default config
                    key = os.environ.get("OPENAI_API_KEY") or config.get("OPENAI_API_KEY")
                    if key:
                        analysis_client = OpenAI(api_key=key)
                    else:
                        print("Warning: No OpenAI compatible client found for image analysis.")
                        return None

            response = analysis_client.chat.completions.create(
                model=vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe the character in this image in detail. Focus on physical features (hair color/style, eye color, skin tone, age), clothing (style, colors, specific items), and distinctive accessories. Keep the description precise and visual."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=300
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error analyzing reference image: {e}")
            # Fallback: return None so we just use the original prompt
            return None

    def _generate_mock_image(self, output_path, ref_images=None, gen_settings=None, prompt=None):
        """Create a single placeholder image using Pillow"""
        from PIL import Image, ImageDraw, ImageFont
        import random
        
        gen_settings = gen_settings or {}
        
        # Create a single image (16:9 aspect ratio)
        width, height = 1024, 576
        img = Image.new('RGB', (width, height), color=(40, 40, 40))
        
        # Try to load font
        try:
            font_large = ImageFont.truetype("arial.ttf", 32)
            font_medium = ImageFont.truetype("arial.ttf", 20)
            font_small = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font_large = ImageFont.load_default()
            font_medium = font_large
            font_small = font_large
        
        d = ImageDraw.Draw(img)
        
        # Draw a simple scene placeholder
        panel_colors = [(80, 80, 120), (120, 80, 80), (80, 120, 80), (120, 120, 80)]
        color = random.choice(panel_colors)
        
        # Draw main area
        d.rectangle([50, 50, width-50, height-50], fill=color, outline=(200, 200, 200), width=2)
        
        # Draw center text
        if prompt:
            prompt_display = prompt[:80] + "..." if len(prompt) > 80 else prompt
            # Draw semi-transparent background
            d.rectangle([0, height//2-30, width, height//2+30], fill=(0, 0, 0, 180))
            d.text((width//2-200, height//2-15), f"MOCK IMAGE", fill=(255, 255, 255), font=font_medium)
            d.text((20, height//2+5), prompt_display, fill=(200, 200, 200), font=font_small)
        else:
            d.text((width//2-100, height//2-15), "MOCK IMAGE", fill=(255, 255, 255), font=font_medium)
        
        # Draw bottom info
        info_y = height - 60
        d.rectangle([0, info_y, width, height], fill=(30, 30, 30))
        d.text((20, info_y+10), "MOCK IMAGE - API Not Configured", fill=(255, 100, 100), font=font_medium)
        
        if gen_settings:
            info_text = f"Style: {gen_settings.get('style', 'None')} | Steps: {gen_settings.get('steps', 30)} | CFG: {gen_settings.get('cfg_scale', 7.0)}"
            d.text((20, info_y+35), info_text, fill=(200, 200, 200), font=font_small)
        
        img.save(output_path)
        print(f"[MOCK] Generated single image: {output_path}")
        return output_path

    def _generate_comfyui_image(self, prompt, output_path, ref_images=None, gen_settings=None, status_callback=None, anchors=None):
        """
        Generates image using ComfyUI local server.
        Uses workflow file from api_config or default location.
        anchors: 可选，一致性锚点 payload；含 scene.base_image（场景基准图）与
                 characters[].lora_path / ip_adapter_weight 等，供 C 层一致性使用。
        """
        import uuid
        from PIL import Image

        if status_callback: status_callback("正在连接 ComfyUI...")

        # Get base_url from config or use default
        base_url = self.base_url if self.base_url else "http://127.0.0.1:8188"
        base_url = base_url.rstrip('/')

        # Upload reference images if provided
        uploaded_images = []
        if ref_images:
            for ref_img in ref_images:
                try:
                    upload_result = self._comfy_upload_image(ref_img, base_url)
                    if upload_result:
                        uploaded_images.append(upload_result.get("name"))
                        print(f"Uploaded reference image: {upload_result.get('name')}")
                except Exception as e:
                    print(f"Failed to upload reference image: {e}")

        # 一致性 C 层：上传场景基准图（作为 ControlNet 输入图）
        # 放到 uploaded_images 末尾，_modify_image_workflow 会按 LoadImage 顺序填充
        if anchors and isinstance(anchors, dict):
            scene_anchor = anchors.get("scene") or {}
            base_img = scene_anchor.get("base_image", "")
            if base_img and os.path.exists(base_img):
                try:
                    upload_result = self._comfy_upload_image(base_img, base_url)
                    if upload_result:
                        uploaded_images.append(upload_result.get("name"))
                        print(f"Uploaded scene base image: {upload_result.get('name')}")
                except Exception as e:
                    print(f"Failed to upload scene base image: {e}")

        # 工作流来源：只认设置（API 配置 workflow_file/_ref1/_ref3 > 全局图片工作流），
        # 不再硬编码任何默认文件名。带参考图时优先参考图专用工作流，
        # 未配置则回退本配置的 workflow_file（同一工作流做图生图）。
        n_imgs = len(uploaded_images)
        if n_imgs == 0:
            _candidates = [("API配置", self.api_config.get("workflow_file", "")),
                           ("全局图片工作流", self.global_workflow)]
        elif n_imgs == 1:
            _candidates = [("API配置(单参考图)", self.api_config.get("workflow_file_ref1", "")),
                           ("API配置", self.api_config.get("workflow_file", "")),
                           ("全局图片工作流", self.global_workflow)]
        else:
            _candidates = [("API配置(多参考图)", self.api_config.get("workflow_file_ref3", "")),
                           ("API配置(单参考图)", self.api_config.get("workflow_file_ref1", "")),
                           ("API配置", self.api_config.get("workflow_file", "")),
                           ("全局图片工作流", self.global_workflow)]
        workflow_file = ""
        workflow_source = ""
        for _src, _wf in _candidates:
            if _wf:
                workflow_file, workflow_source = _wf, _src
                break
        if not workflow_file:
            _msg = ("未配置图片工作流——请在 设置 → API配置 中为 Image 配置填写「工作流文件」"
                    "（或在 设置 → 全局图片工作流 填写）")
            print(f"Error: {_msg}")
            if status_callback: status_callback(_msg)
            return None

        # Resolve workflow path
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if not os.path.isabs(workflow_file):
            workflow_path = os.path.join(base_dir, "resources", "workflows", workflow_file)
        else:
            workflow_path = workflow_file

        if not os.path.exists(workflow_path):
            print(f"Error: Workflow file not found at {workflow_path}")
            if status_callback: status_callback("工作流文件未找到")
            return None

        if status_callback: status_callback("正在加载工作流...")

        # Load workflow
        try:
            with open(workflow_path, 'r', encoding='utf-8') as f:
                workflow = json.load(f)
        except Exception as e:
            print(f"Error loading workflow: {e}")
            return None

        print(f"[工作流] 图片生成：来源={workflow_source}，文件={workflow_file}，参考图 {n_imgs} 张")

        # Modify workflow with prompt and images (+ anchors for IP-Adapter/ControlNet/LoRA)
        workflow = self._modify_image_workflow(workflow, prompt, uploaded_images, gen_settings, anchors, base_url=base_url)

        # 关闭 RAMCleanup 激进参数（clean_dlls/clean_processes），
        # 避免出图后进程工作集被 trim 导致下一次读模型失败
        if sanitize_cleanup_nodes:
            _fixed = sanitize_cleanup_nodes(workflow)
            if _fixed:
                print(f"[图片] RAMCleanup 激进参数已关闭: {', '.join(_fixed)}")

        if status_callback: status_callback("正在生成图片...")
        
        # Queue prompt
        client_id = str(uuid.uuid4())
        try:
            response = requests.post(f"{base_url}/prompt", json={
                "prompt": workflow,
                "client_id": client_id
            }, proxies={'http': None, 'https': None}, timeout=300)
            response.raise_for_status()
            result = response.json()
            prompt_id = result.get("prompt_id")
            if not prompt_id:
                print("Failed to queue prompt: no prompt_id")
                return None
        except Exception as e:
            print(f"Error queuing prompt: {e}")
            # 解析 ComfyUI 400 校验错误，定位到具体缺哪个模型/参数，避免只报"失败"
            resp = getattr(e, 'response', None)
            detail = self._describe_comfy_error(resp) if resp is not None else ""
            if detail:
                print(f"ComfyUI 校验失败详情: {detail}")
                if status_callback: status_callback(f"提交失败: {detail}")
            return None
        
        if status_callback: status_callback("等待生成完成...")
        
        # Poll for completion
        max_wait = 300  # 5 minutes
        start_time = time.time()
        try:
            from ai_engine.utils.cancel import interruptible_sleep
        except ImportError:
            from src.ai_engine.utils.cancel import interruptible_sleep
        while time.time() - start_time < max_wait:
            if interruptible_sleep(0):
                print("ComfyUI image generation cancelled")
                self._comfy_interrupt(base_url)
                if status_callback: status_callback("已取消")
                return None
            try:
                history_resp = requests.get(f"{base_url}/history/{prompt_id}", proxies={'http': None, 'https': None}, timeout=60)
                history_resp.raise_for_status()
                history = history_resp.json()
                
                if prompt_id in history:
                    # 节点报错时快速失败（此前空等满 300s 超时，流水线像卡死）
                    status = history[prompt_id].get("status") or {}
                    status_str = str(status.get("status_str", "")).lower()
                    if status_str == "error":
                        err_detail = ""
                        for m in (status.get("messages") or []):
                            if isinstance(m, (list, tuple)) and len(m) >= 2 and m[0] == "execution_error":
                                info = m[1] if isinstance(m[1], dict) else {}
                                err_detail = (f"节点 {info.get('node_type', info.get('node_id', '?'))} "
                                              f"执行出错: {info.get('exception_message', '未知错误')}")
                                break
                        print(f"ComfyUI image task failed: {err_detail or status_str}")
                        if status_callback: status_callback(f"生成失败: {err_detail or '节点执行出错'}")
                        return None

                    outputs = history[prompt_id].get("outputs", {})
                    # Find image output
                    for node_id, output_data in outputs.items():
                        if "images" in output_data:
                            files = output_data["images"]
                            if files:
                                file_info = files[0]
                                filename = file_info.get("filename")
                                subfolder = file_info.get("subfolder", "")
                                folder_type = file_info.get("type", "output")
                                
                                # Download image
                                img_url = f"{base_url}/view"
                                img_params = {
                                    "filename": filename,
                                    "subfolder": subfolder,
                                    "type": folder_type
                                }
                                img_resp = requests.get(img_url, params=img_params, proxies={'http': None, 'https': None}, timeout=300)
                                img_resp.raise_for_status()
                                
                                # Save image
                                with open(output_path, 'wb') as f:
                                    f.write(img_resp.content)
                                
                                print(f"ComfyUI image generated: {output_path}")
                                if status_callback: status_callback("图片生成完成")
                                return output_path
                    break
            except Exception as e:
                print(f"Error polling history: {e}")
            
            if interruptible_sleep(2):
                print("ComfyUI image generation cancelled")
                self._comfy_interrupt(base_url)
                if status_callback: status_callback("已取消")
                return None
        
        print("ComfyUI generation timeout or failed")
        if status_callback: status_callback("生成超时或失败")
        return None
    
    def _comfy_upload_image(self, image_path, base_url):
        """Upload image to ComfyUI"""
        url = f"{base_url}/upload/image"
        try:
            with open(image_path, 'rb') as f:
                files = {'image': (os.path.basename(image_path), f)}
                response = requests.post(url, files=files, proxies={'http': None, 'https': None}, timeout=300)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Upload error: {e}")
            return None
    
    def _comfy_interrupt(self, base_url):
        """中断 ComfyUI 服务端当前任务。"""
        try:
            requests.post(f"{base_url}/interrupt", json={}, proxies={'http': None, 'https': None}, timeout=(5, 10))
            print("ComfyUI interrupt sent")
        except Exception as e:
            print(f"ComfyUI interrupt failed: {e}")

    @staticmethod
    def _describe_comfy_error(resp):
        """把 /prompt 校验失败（400）的响应转成可读提示。

        重点提取 node_errors 的 details（含 received_value 与合法枚举），
        例如「VAELoader(节点22) vae_name: 'flux2-vae.safetensors' not in [...]」，
        让缺模型/参数错误直接出现在日志与 UI 状态里，不再只报"失败"。
        """
        try:
            data = resp.json()
        except Exception:
            try:
                return (resp.text or "").strip()[:300]
            except Exception:
                return ""
        parts = []
        for nid, info in (data.get("node_errors") or {}).items():
            class_type = (info or {}).get("class_type", "")
            for err in (info or {}).get("errors") or []:
                msg = err.get("details") or err.get("message") or ""
                if msg:
                    # 合法枚举列表很长（几十个文件名），界面上只保留缺失值本身
                    msg = re.sub(r"\s*not in \[.*?\]", "（服务器上不存在该文件）", msg)
                    parts.append(f"{class_type}(节点{nid}) {msg}")
        if not parts:
            parts.append(str(data.get("error") or ""))
        return "；".join(p for p in parts if p)[:200]
    
    # gen_settings 比例 → ResolutionSelector 常见枚举静态兜底映射
    # （优先用 /object_info 拉取的真实枚举，此处仅查询失败时兜底）
    _RES_RATIO_LABELS = {
        "1:1": "1:1 (Square)",
        "2:3": "2:3 (Portrait)",
        "3:4": "3:4 (Portrait)",
        "9:16": "9:16 (Portrait Widescreen)",
        "3:2": "3:2 (Landscape)",
        "4:3": "4:3 (Landscape)",
        "16:9": "16:9 (Landscape Widescreen)",
        "21:9": "21:9 (Cinematic)",
    }

    # 比例 → 数值宽高比（用于推导参考图尺寸）
    _RATIO_VALUES = {
        "1:1": (1, 1),
        "2:3": (2, 3),
        "3:4": (3, 4),
        "9:16": (9, 16),
        "3:2": (3, 2),
        "4:3": (4, 3),
        "16:9": (16, 9),
        "21:9": (21, 9),
    }

    @classmethod
    def _sizes_for_ratio(cls, ratio, megapixels=0.6, multiple=8):
        """按比例 + 像素预算推导参考图宽高，对齐到 multiple 的倍数。

        返回 (width, height, megapixels_actual)；
        比例未知或为空时返回 (None, None, None)，此时保留工作流原值。
        """
        rv = cls._RATIO_VALUES.get(str(ratio or "").strip())
        if not rv:
            return None, None, None
        try:
            mp = float(megapixels)
        except (TypeError, ValueError):
            mp = 0.6
        if mp <= 0:
            return None, None, None

        rw, rh = rv
        ratio_h = (mp * 1_000_000 * rh / rw) ** 0.5
        ratio_w = ratio_h * rw / rh
        w = max(multiple, int(round(ratio_w / multiple)) * multiple)
        h = max(multiple, int(round(ratio_h / multiple)) * multiple)
        return w, h, round(w * h / 1_000_000, 2)

    def _match_resolution_label(self, base_url, ratio):
        """把 gen_settings 的比例（如 16:9）映射为 ResolutionSelector 的合法枚举值。

        优先从 ComfyUI /object_info 拉取真实枚举列表（保证提交校验通过），
        查询失败时回退静态映射；找不到合法值则返回空串（保留工作流原值）。
        """
        if not ratio:
            return ""
        fallback = self._RES_RATIO_LABELS.get(ratio, "")
        if not base_url:
            return fallback
        try:
            resp = requests.get(f"{base_url}/object_info/ResolutionSelector",
                                proxies={'http': None, 'https': None}, timeout=5)
            if resp.status_code == 200:
                info = resp.json().get("ResolutionSelector", {}) or {}
                opts = (info.get("input", {}).get("required", {})
                        .get("aspect_ratio", []))
                options = opts[0] if isinstance(opts, (list, tuple)) and opts else []
                if isinstance(options, list) and options:
                    options = [str(o) for o in options]
                    # 精确匹配优先，其次前缀匹配（"16:9 (Landscape Widescreen)"）
                    for opt in options:
                        if opt == ratio:
                            return opt
                    for opt in options:
                        if opt.startswith(ratio + " ") or opt.startswith(ratio + ":"):
                            return opt
                    # 比例不在枚举中时，仅当静态兜底值确实合法才使用
                    return fallback if fallback in options else ""
        except Exception as e:
            print(f"[ResolutionSelector] object_info query failed: {e}")
        return fallback

    def _modify_image_workflow(self, workflow, prompt, image_filenames=None, gen_settings=None, anchors=None, base_url=None):
        """Modify ComfyUI workflow with prompt and images.

        base_url: ComfyUI 服务地址（可选），用于 ResolutionSelector 等节点的
                  /object_info 枚举校验，保证注入值合法。
        anchors: 一致性锚点 payload（可选），识别并填充：
          - IP-Adapter 节点（class_type 含 "IPAdapter"）→ weight = 角色 ip_adapter_weight
          - ControlNet Apply 节点（class_type 含 "ControlNet" 且含 "Apply"）→ strength = scene.controlnet_weight
          - ControlNetLoader 节点 → control_net_name 按类型映射（仅常见默认值，不匹配则跳过）
          - LoraLoader 节点（class_type 含 "LoraLoader"）→ lora_name = basename(角色 lora_path)
        所有 C 层参数均为“查到才填”，查不到则保留 workflow 原值（降级）。
        """
        import copy
        workflow = copy.deepcopy(workflow)
        # 过滤非节点键（如 _comment 元数据），避免遍历时 .get 崩溃
        workflow = {k: v for k, v in workflow.items() if isinstance(v, dict)}

        # Find and update prompt nodes
        prompt_updated = False
        # FLUX.2: 提示词存在 PrimitiveStringMultiline 节点的 value 字段
        for node_id, node in workflow.items():
            if node.get("class_type") == "PrimitiveStringMultiline":
                inputs = node.get("inputs", {})
                if "value" in inputs and not prompt_updated:
                    inputs["value"] = prompt
                    prompt_updated = True
                    print(f"Updated prompt in PrimitiveStringMultiline node {node_id}")
        # 传统 workflow: 提示词存在 CLIPTextEncode 的 text 字段（区分 positive/negative）
        # 未配置负向提示词时使用默认值：重点禁文字/水印——绘图模型渲染中文必出乱码鬼符
        default_negative = ("text, watermark, subtitle, caption, letters, numbers, "
                            "chinese characters, logo, signature, blurry, low quality")
        negative_prompt_text = (gen_settings.get("negative_prompt", "") if gen_settings else "") or default_negative
        # 先从 KSampler 的 positive/negative 链接反查提示词节点（比标题匹配更可靠，
        # 兼容 _meta.title 为中文或缺失的工作流，如 image_moss.json）
        pos_ids, neg_ids = set(), set()
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") not in ("KSampler", "KSamplerAdvanced"):
                continue
            k_in = node.get("inputs", {})
            for key, bucket in (("positive", pos_ids), ("negative", neg_ids)):
                link = k_in.get(key)
                if isinstance(link, (list, tuple)) and len(link) >= 1:
                    bucket.add(str(link[0]))
        positive_updated = False
        for node_id, node in workflow.items():
            if node.get("class_type") != "CLIPTextEncode":
                continue
            inputs = node.get("inputs", {})
            title = (node.get("_meta", {}).get("title", "") or "").lower()
            is_neg = node_id in neg_ids or "negative" in title
            if is_neg:
                # Update negative prompt if provided
                if negative_prompt_text and "text" in inputs and isinstance(inputs["text"], str):
                    inputs["text"] = negative_prompt_text
                    print(f"Updated negative prompt in CLIPTextEncode node {node_id}")
                continue
            # 有链路信息时只写 positive 槽位节点；无链路信息回退"第一个带 text 的节点"
            matched_pos = (not pos_ids) or (node_id in pos_ids)
            if "text" in inputs and not positive_updated and matched_pos and isinstance(inputs["text"], str):
                inputs["text"] = prompt
                positive_updated = True
                print(f"Updated prompt in CLIPTextEncode node {node_id}")

        # Find and update LoadImage nodes
        # 关键：LoadImage 必须按条件链（ReferenceLatent 链）的顺序填充，
        # 而非节点 ID 字典序。FLUX2 3i2i 工作流中，条件链顺序为
        # 文本→参考图A→参考图B→参考图C→CFGGuider，语义槽位由链位置决定。
        # 按节点 ID 序填充会导致角色图进错槽位（串脸/丢场景）。
        if image_filenames:
            load_ids = self._load_image_ids_in_chain_order(workflow)
            if not load_ids:
                # 无 ReferenceLatent 链时回退到节点 ID 序
                load_ids = [nid for nid, n in workflow.items()
                            if isinstance(n, dict) and n.get("class_type") == "LoadImage"]
            for i, nid in enumerate(load_ids):
                node = workflow.get(nid)
                if not node:
                    continue
                if i < len(image_filenames):
                    node["inputs"]["image"] = image_filenames[i]
                    print(f"Updated LoadImage node {nid} with {image_filenames[i]} (slot {i})")
                else:
                    # 图不够时复用最后一张，保证 LoadImage 不空
                    node["inputs"]["image"] = image_filenames[-1]
                    print(f"Updated LoadImage node {nid} with last image (reused, slot {i})")

        # Apply gen_settings if provided（仅写入有效值，None/空值不覆盖 workflow 默认值）
        if gen_settings:
            seed_val = gen_settings.get("seed")
            if not isinstance(seed_val, int):
                seed_val = None
            steps_val = gen_settings.get("steps")
            if not isinstance(steps_val, int) or steps_val <= 0:
                steps_val = None
            cfg_val = gen_settings.get("cfg_scale")
            if not isinstance(cfg_val, (int, float)):
                cfg_val = None
            w_val = gen_settings.get("width")
            if not isinstance(w_val, int) or w_val <= 0:
                w_val = None
            h_val = gen_settings.get("height")
            if not isinstance(h_val, int) or h_val <= 0:
                h_val = None

            # 参考图目标像素预算：调用方可通过 megapixels 显式指定，
            # 否则按 0.6MP 推导（短边对齐到 8 的倍数）。
            # 依据：下游 i2v（MiniMaxH3 ref_image_size=match）只消耗生成 latent 的面积，
            # 1080P 目标下约 0.52MP；0.6MP 略高一点可保留面部细节，再大就是浪费。
            try:
                _mp_budget = float(gen_settings.get("megapixels") or 0.6)
            except (TypeError, ValueError):
                _mp_budget = 0.6
            derived_w, derived_h, derived_mp = self._sizes_for_ratio(
                str(gen_settings.get("aspect_ratio", "") or "").strip(), _mp_budget)

            # FLUX.2 / Turbo 架构检测：蒸馏模型的 steps/cfg 由工作流作者调好
            # （FLUX2 通常 steps=4/cfg=1，turbo 通常 steps=8/cfg=1），
            # 外部传入的 SD 默认参数（30/7.0）覆盖后会严重过饱和、色彩失真。
            # 检测条件：含 CFGGuider/Flux2Scheduler（FLUX2），或含
            # res_multistep sampler / ModelSamplingAuraFlow（turbo 系）。
            is_distilled = False
            for n in workflow.values():
                if not isinstance(n, dict):
                    continue
                ct = n.get("class_type", "")
                if ct in ("CFGGuider", "Flux2Scheduler", "ModelSamplingAuraFlow"):
                    is_distilled = True
                    break
                if ct == "KSampler":
                    smp = n.get("inputs", {}).get("sampler_name", "")
                    if smp in ("res_multistep", "res_multistep_ancestral", "res_multistep_cfg"):
                        is_distilled = True
                        break
                # DMD/LCM/Turbo 系加速 LoRA（如 MOSS-Image-SFT-8-steps-dmd）：
                # 步数/cfg 由工作流作者调好，外部覆盖会色彩失真
                if ct in ("LoraLoaderModelOnly", "LoraLoader"):
                    ln = str(n.get("inputs", {}).get("lora_name", "")).lower()
                    if any(k in ln for k in ("dmd", "lcm", "turbo", "hyper", "lightning")):
                        is_distilled = True
                        break
            if is_distilled and (steps_val is not None or cfg_val is not None):
                print(f"[distilled] 检测到蒸馏工作流，保留内置 steps/cfg（忽略外部 steps={steps_val}, cfg={cfg_val}，防止色彩失真）")
                steps_val = None
                cfg_val = None
            for node_id, node in workflow.items():
                class_type = node.get("class_type")
                inputs = node.get("inputs", {})
                if class_type == "KSampler":
                    if steps_val is not None:
                        inputs["steps"] = steps_val
                    if cfg_val is not None:
                        inputs["cfg"] = cfg_val
                    if seed_val is not None:
                        inputs["seed"] = seed_val
                elif class_type in ("EmptyLatentImage", "EmptySD3LatentImage", "EmptyFlux2LatentImage"):
                    # 仅当 width/height 是整数（非节点链接）时才覆盖。
                    # 调用方未给显式宽高时，按 aspect_ratio 推导——否则工作流内置的
                    # 1024x1024 方形会让 9:16 / 16:9 的角色参考图比例完全错位，
                    # 下游 i2v 再做 match 缩放时人脸/身体会被压扁。
                    _w = w_val if w_val is not None else derived_w
                    _h = h_val if h_val is not None else derived_h
                    if isinstance(inputs.get("width", 0), int) and _w:
                        inputs["width"] = _w
                    if isinstance(inputs.get("height", 0), int) and _h:
                        inputs["height"] = _h
                # FLUX.2 调度器（steps）
                elif class_type == "Flux2Scheduler":
                    if steps_val is not None:
                        inputs["steps"] = steps_val
                # FLUX.2 CFG引导器
                elif class_type == "CFGGuider":
                    if cfg_val is not None:
                        inputs["cfg"] = cfg_val
                # FLUX.2 随机噪波（seed 写这里，不是 KSampler）
                elif class_type == "RandomNoise":
                    if seed_val is not None:
                        inputs["noise_seed"] = seed_val
                # 分辨率选择器（image_moss.json 等）：宽高由比例枚举决定，
                # EmptyFlux2LatentImage 的 width/height 是链接，需按比例写入枚举值
                elif class_type == "ResolutionSelector":
                    ratio = str(gen_settings.get("aspect_ratio", "") or "").strip()
                    label = self._match_resolution_label(base_url, ratio)
                    if label and "aspect_ratio" in inputs:
                        inputs["aspect_ratio"] = label
                        print(f"[ResolutionSelector] node {node_id} aspect_ratio -> {label}")
                    # 参考图不必按工作流内置的 2MP 出图：下游 i2v 的 ref_image_size=match
                    # 会把参考图压到生成 latent 的面积（1080P 目标下约 0.52MP），
                    # 超出部分是白烧时间与显存。按推导面积写入更合适的像素预算。
                    if derived_mp and isinstance(inputs.get("megapixels"), (int, float)):
                        inputs["megapixels"] = derived_mp
                        print(f"[ResolutionSelector] node {node_id} megapixels -> {derived_mp}")

        # ---------- 一致性 C 层：识别 IP-Adapter / ControlNet / LoRA 节点 ----------
        if anchors and isinstance(anchors, dict):
            char_anchors = anchors.get("characters") or []
            scene_anchor = anchors.get("scene") or {}

            # 取第一个有 ip_adapter_weight>0 的角色
            ip_weight = 0.0
            ip_found = False
            for ca in char_anchors:
                w = float(ca.get("ip_adapter_weight", 0.0) or 0.0)
                if w > 0.0:
                    ip_weight = w
                    ip_found = True
                    break

            # 取第一个有 lora_path 的角色
            lora_name = ""
            for ca in char_anchors:
                lp = ca.get("lora_path", "") or ""
                if lp:
                    lora_name = os.path.basename(lp)
                    break

            # 场景 ControlNet 参数
            cn_weight = float(scene_anchor.get("controlnet_weight", 0.0) or 0.0)
            cn_type = (scene_anchor.get("controlnet", "") or "").lower()

            # ControlNet 类型 → 常见模型名映射（仅做默认提示，不匹配则不动）
            cn_model_map = {
                "depth": "control_v11f1p_sd15_depth.pth",
                "canny": "control_v11p_sd15_canny.pth",
                "openpose": "control_v11p_sd15_openpose.pth",
                "lineart": "control_v11p_sd15_lineart.pth",
                "hed": "control_v11p_sd15_hed.pth",
                "scribble": "control_v11p_sd15_scribble.pth",
            }
            cn_model_name = cn_model_map.get(cn_type, "")

            for node_id, node in workflow.items():
                class_type = (node.get("class_type") or "")
                inputs = node.get("inputs", {})

                # IP-Adapter（IPAdapterApply / IPAdapterAdvanced / IPAdapterPlus）
                if "ipadapter" in class_type.lower():
                    if ip_found and "weight" in inputs:
                        inputs["weight"] = ip_weight
                        print(f"[anchor] IP-Adapter node {node_id} weight={ip_weight}")
                    elif "weight" in inputs:
                        # 无有效权重则确保为 0（不启用），保留 workflow 原值更安全，这里不动
                        pass

                # ControlNet Apply（ControlNetApply / ControlNetApplyAdvanced）
                elif "controlnet" in class_type.lower() and "apply" in class_type.lower():
                    if cn_weight > 0.0 and "strength" in inputs:
                        inputs["strength"] = cn_weight
                        print(f"[anchor] ControlNet Apply node {node_id} strength={cn_weight}")

                # ControlNet Loader（ControlNetLoader）
                # 不覆盖 workflow 模板里已预设的模型名（Flux/SD 架构不同，用户需在 workflow 里预设 Flux 版）
                elif "controlnetloader" in class_type.lower():
                    existing_cn = inputs.get("control_net_name", "")
                    if cn_model_name and not existing_cn and "control_net_name" in inputs:
                        inputs["control_net_name"] = cn_model_name
                        print(f"[anchor] ControlNetLoader node {node_id} model={cn_model_name}")

                # LoRA Loader（LoraLoader / LoraLoaderModelOnly）
                elif "loraloader" in class_type.lower():
                    if lora_name and "lora_name" in inputs:
                        inputs["lora_name"] = lora_name
                        print(f"[anchor] LoraLoader node {node_id} lora={lora_name}")

        return workflow

    def _load_image_ids_in_chain_order(self, workflow):
        """按 ReferenceLatent 条件链顺序返回 LoadImage 节点 ID 列表。

        FLUX2 i2i 工作流中，参考图通过 ReferenceLatent 链注入条件：
          text → RefLatent(imgA) → RefLatent(imgB) → RefLatent(imgC) → CFGGuider
        链位置决定语义槽位（角色/产品/场景），必须按链序而非节点 ID 序填充。
        找不到链时返回空列表（调用方回退到节点 ID 序）。
        """
        # 找 CFGGuider 的 positive 输入作为链尾
        chain_tail = None
        for nid, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "CFGGuider":
                pos = node.get("inputs", {}).get("positive")
                if isinstance(pos, list) and len(pos) == 2:
                    chain_tail = pos[0]
                break
        if not chain_tail:
            return []

        # 从链尾反向遍历 ReferenceLatent，收集每层的 latent 来源
        # latent 输入格式: ["VAEEncode_node_id", 0]
        latent_sources = []
        current = chain_tail
        visited = set()
        while current and current not in visited:
            visited.add(current)
            node = workflow.get(current)
            if not node:
                break
            ct = node.get("class_type", "")
            if ct == "ReferenceLatent":
                lat = node.get("inputs", {}).get("latent")
                if isinstance(lat, list) and len(lat) == 2:
                    latent_sources.append(lat[0])  # VAEEncode node id
                current = node.get("inputs", {}).get("conditioning")
                if isinstance(current, list) and len(current) == 2:
                    current = current[0]
            elif ct == "CLIPTextEncode":
                break  # 到达文本编码，链结束
            else:
                current = None

        if not latent_sources:
            return []

        # latent_sources 是从链尾到链头的顺序，需要反转
        latent_sources.reverse()

        # 每个 VAEEncode → ImageScaleToTotalPixels → LoadImage
        load_ids = []
        for vaee_id in latent_sources:
            vaee = workflow.get(vaee_id)
            if not vaee:
                continue
            pixels = vaee.get("inputs", {}).get("pixels")
            if isinstance(pixels, list) and len(pixels) == 2:
                scale_id = pixels[0]
                scale = workflow.get(scale_id)
                if scale:
                    img = scale.get("inputs", {}).get("image")
                    if isinstance(img, list) and len(img) == 2:
                        load_ids.append(img[0])

        return load_ids
