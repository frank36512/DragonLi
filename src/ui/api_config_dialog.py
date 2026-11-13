from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QComboBox, QDialogButtonBox, QLabel, QCheckBox,
                             QWidget, QHBoxLayout, QPushButton, QMessageBox,
                             QFileDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from ui import theme as _theme


class ConnectionTestThread(QThread):
    # 注意：不能命名为 finished，那会覆盖 QThread 内置的 finished() 信号
    test_finished = pyqtSignal(bool, str)
    
    def __init__(self, config_data):
        super().__init__()
        self.config_data = config_data
    
    def run(self):
        try:
            config_type = self.config_data.get("type", "LLM")
            provider = self.config_data.get("provider", "")
            api_key = self.config_data.get("api_key", "")
            base_url = self.config_data.get("base_url", "")
            model = self.config_data.get("model", "")
            workflow_file = self.config_data.get("workflow_file", "")
            
            # 不再在此检查 API Key，交给各测试方法内部处理
            # ComfyUI 由测试方法根据 provider 和 base_url 自行判断
            
            if config_type == "LLM":
                success, msg = self._test_llm_connection(api_key, base_url, model, provider)
            elif config_type == "Embedding":
                success, msg = self._test_embedding_connection(api_key, base_url, model, provider)
            elif config_type == "Image":
                success, msg = self._test_image_connection(api_key, base_url, model, provider,
                                                           workflow_file=workflow_file)
            elif config_type in ["Video", "ImageToVideo"]:
                success, msg = self._test_video_connection(api_key, base_url, model, provider,
                                                           workflow_file=workflow_file)
            elif config_type == "VideoEnhance":
                success, msg = self._test_enhance_connection(api_key, base_url, provider, self.config_data)
            elif config_type == "TTS":
                success, msg = self._test_tts_connection(api_key, base_url, model, provider)
            else:
                success, msg = False, f"不支持的类型: {config_type}"
            
            self.test_finished.emit(success, msg)
        except Exception as e:
            self.test_finished.emit(False, f"测试失败: {str(e)}")
    
    def _test_llm_connection(self, api_key, base_url, model, provider):
        try:
            import requests
            import json
            
            base = (base_url or "").rstrip('/')
            if not base:
                return False, "请填写 Base URL"
            
            print(f"DEBUG LLM Test: base={base}, model={model}")
            
            # 第1步：获取可用模型列表（禁用代理，避免系统代理干扰）
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            
            # 禁用代理，直接连接目标地址
            proxies = {'http': None, 'https': None}
            
            available_models = []
            try:
                resp = requests.get(f"{base}/models", headers=headers, timeout=10, proxies=proxies)
                print(f"DEBUG: /models status={resp.status_code}")
                if resp.status_code == 200:
                    models_data = resp.json()
                    if isinstance(models_data, dict) and 'data' in models_data:
                        available_models = [m.get('id', '') for m in models_data['data'] if m.get('id')]
                        print(f"DEBUG: Available models: {available_models}")
            except Exception as e:
                print(f"DEBUG: /models failed: {e}")
            
            # 第2步：确定要测试的模型
            test_model = None
            if model and model in available_models:
                test_model = model
            elif available_models:
                test_model = available_models[0]
            else:
                test_model = model if model else "gemma-4-26b-a4b-it"
            
            print(f"DEBUG: Testing with model={test_model}")
            
            # 第3步：直接用 requests 测试聊天接口（绕过 OpenAI 客户端，禁用代理）
            chat_url = f"{base}/chat/completions"
            payload = {
                "model": test_model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5,
                "stream": False
            }
            
            print(f"DEBUG: POST {chat_url} with model={test_model}")
            resp = requests.post(chat_url, headers=headers, json=payload, timeout=30, proxies={'http': None, 'https': None})
            print(f"DEBUG: chat status={resp.status_code}, response={resp.text[:300]}")
            
            if resp.status_code == 200:
                return True, f"连接成功！模型: {test_model}"
            elif resp.status_code == 404:
                return False, f"聊天接口不存在(404)：请检查 Base URL 是否正确（应为 http://192.168.2.4:1234/v1）"
            elif resp.status_code == 401:
                return False, "认证失败：API Key 无效"
            else:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
                
        except requests.exceptions.ConnectionError as e:
            return False, f"连接失败：无法连接到 {base}，请检查地址和端口是否正确，以及服务是否启动"
        except requests.exceptions.Timeout as e:
            return False, f"连接超时：服务响应太慢，请检查服务状态"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f"连接失败：{str(e)}"
    
    def _test_embedding_connection(self, api_key, base_url, model, provider):
        """用 EmbeddingClient.test()：失败时带回服务端真实响应与可用模型列表，
        避免只看到 SDK 那句没有信息量的 "No embedding data received"。"""
        try:
            from ai_engine.llm.llm_client import EmbeddingClient
        except ImportError:
            from src.ai_engine.llm.llm_client import EmbeddingClient
        client = EmbeddingClient({"api_key": api_key, "base_url": base_url,
                                  "model": model})
        return client.test()
    
    def _test_image_connection(self, api_key, base_url, model, provider, workflow_file=""):
        try:
            import requests
            import json
            
            if not base_url:
                return False, "请填写 ComfyUI 地址（如 http://192.168.2.4:8188）"
            
            base = base_url.rstrip('/')
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            
            # 判断是否是 ComfyUI（默认端口 8188 或 URL 包含 comfy）
            is_comfy = (provider.lower() == "comfyui")
            
            if is_comfy:
                print(f"DEBUG: Testing ComfyUI connection to {base}")
                try:
                    # 先测试系统状态接口
                    resp = requests.get(f"{base}/system_stats", timeout=10, proxies={'http': None, 'https': None})
                    print(f"DEBUG: ComfyUI /system_stats status={resp.status_code}")
                    if resp.status_code == 200:
                        # 读取工作流文件：只用设置里选的，不猜文件名
                        workflow_filename = (workflow_file or "").strip()
                        workflow_path = (self._find_comfy_workflow(workflow_filename)
                                         if workflow_filename else None)
                        
                        if workflow_path:
                            print(f"DEBUG: Found workflow: {workflow_path}")
                            with open(workflow_path, 'r', encoding='utf-8') as f:
                                workflow = json.load(f)
                            
                            # 构造 ComfyUI API 请求
                            payload = {"prompt": workflow}
                            print(f"DEBUG: POST {base}/prompt")
                            resp2 = requests.post(f"{base}/prompt", headers=headers, json=payload, timeout=30, proxies={'http': None, 'https': None})
                            print(f"DEBUG: /prompt status={resp2.status_code}")
                            if resp2.status_code in [200, 201]:
                                return True, f"ComfyUI 连接成功！工作流已加载"
                            else:
                                return False, f"ComfyUI 工作流提交失败: HTTP {resp2.status_code}"
                        else:
                            if workflow_filename:
                                return True, f"ComfyUI 连接成功！（未找到工作流文件 {workflow_filename}，请在 resources/workflows/ 目录添加）"
                            return True, "ComfyUI 连接成功！（未选择工作流文件，保存前请在「工作流文件」中选择）"
                except Exception as e:
                    print(f"DEBUG: ComfyUI test failed: {e}")
                    return False, f"ComfyUI 连接失败：{str(e)}"
            else:
                # 原有的 OpenAI 兼容图像生成测试逻辑
                test_url = base
                # 策略1: 尝试 GET /models 端点
                try:
                    resp = requests.get(f"{test_url}/models", headers=headers, timeout=10)
                    if resp.status_code in [200, 401, 403]:
                        if resp.status_code == 401:
                            return False, "API Key 无效或已过期"
                        if resp.status_code == 403:
                            return False, "API Key 没有权限访问此资源"
                        return True, f"连接成功！"
                except requests.exceptions.RequestException:
                    pass
                
                # 策略2: 如果 base_url 包含 /images/generations，尝试直接 POST 测试
                if "/images/generations" in test_url:
                    try:
                        test_payload = {
                            "model": model if model else "dall-e-3",
                            "prompt": "test",
                            "n": 1
                        }
                        resp = requests.post(test_url, headers=headers, json=test_payload, timeout=10)
                        if resp.status_code in [200, 400, 401, 403]:
                            if resp.status_code == 401:
                                return False, "API Key 无效或已过期"
                            if resp.status_code == 403:
                                return False, "API Key 没有权限访问此资源"
                            return True, f"连接成功！"
                    except requests.exceptions.RequestException as e:
                        return False, f"连接失败: {str(e)}"
                
                # 策略3: 尝试 POST 到 /images/generations 端点
                try:
                    test_payload = {
                        "model": model if model else "dall-e-3",
                        "prompt": "test",
                        "n": 1
                    }
                    resp = requests.post(f"{test_url}/images/generations", headers=headers, json=test_payload, timeout=10)
                    if resp.status_code in [200, 400, 401, 403]:
                        if resp.status_code == 401:
                            return False, "API Key 无效或已过期"
                        if resp.status_code == 403:
                            return False, "API Key 没有权限访问此资源"
                        return True, f"连接成功！"
                except requests.exceptions.RequestException:
                    pass
                
                return False, f"无法连接到指定的 API 地址，请检查 Base URL 是否正确"
            
        except Exception as e:
            return False, f"Image 连接失败: {str(e)}"
    
    def _find_comfy_workflow(self, filename=None):
        """查找 ComfyUI 工作流文件"""
        import os
        
        # 未指定文件名时不猜默认文件——工作流必须来自设置
        if not filename:
            print("DEBUG: _find_comfy_workflow 未指定工作流文件名")
            return None
        
        # 标准搜索路径
        # 相对当前文件向上两级到 src，再向上到项目根目录，避免硬编码绝对路径
        project_root = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        )
        search_dirs = [
            os.path.join(project_root, "resources", "workflows"),
            os.path.join(".", "resources", "workflows"),
            os.path.join(os.getcwd(), "resources", "workflows"),
        ]
        
        for base in search_dirs:
            p = os.path.normpath(os.path.join(base, filename))
            print(f"DEBUG: Checking workflow path: {p}")
            if os.path.exists(p):
                print(f"DEBUG: Found workflow: {p}")
                return p
        
        print(f"DEBUG: Workflow not found: {filename}")
        return None
    
    def _test_video_connection(self, api_key, base_url, model, provider, workflow_file=""):
        try:
            import requests
            import json
            
            if not base_url:
                return False, "请填写 ComfyUI 地址（如 http://192.168.2.4:8188）"
            
            base = base_url.rstrip('/')
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            
            # 判断是否是 ComfyUI 视频
            is_comfy_video = (provider.lower() == "comfyui")
            
            if is_comfy_video:
                print(f"DEBUG: Testing ComfyUI Video connection to {base}")
                try:
                    # 先测试系统状态接口
                    resp = requests.get(f"{base}/system_stats", timeout=10, proxies={'http': None, 'https': None})
                    print(f"DEBUG: ComfyUI Video /system_stats status={resp.status_code}")
                    if resp.status_code == 200:
                        # 读取视频工作流文件：只用设置里选的，不猜文件名
                        workflow_filename = (workflow_file or "").strip()
                        workflow_path = (self._find_comfy_workflow(workflow_filename)
                                         if workflow_filename else None)
                        
                        if workflow_path:
                            print(f"DEBUG: Found video workflow: {workflow_path}")
                            with open(workflow_path, 'r', encoding='utf-8') as f:
                                workflow = json.load(f)
                            
                            # 构造 ComfyUI API 请求
                            payload = {"prompt": workflow}
                            print(f"DEBUG: POST {base}/prompt")
                            resp2 = requests.post(f"{base}/prompt", headers=headers, json=payload, timeout=30, proxies={'http': None, 'https': None})
                            print(f"DEBUG: /prompt status={resp2.status_code}")
                            if resp2.status_code in [200, 201]:
                                return True, f"ComfyUI 视频连接成功！工作流已加载"
                            else:
                                return False, f"ComfyUI 视频工作流提交失败: HTTP {resp2.status_code}"
                        else:
                            if workflow_filename:
                                return True, f"ComfyUI 视频连接成功！（未找到工作流文件 {workflow_filename}，请在 resources/workflows/ 目录添加）"
                            return True, "ComfyUI 视频连接成功！（未选择工作流文件，保存前请在「工作流文件」中选择）"
                except Exception as e:
                    print(f"DEBUG: ComfyUI Video test failed: {e}")
                    return False, f"ComfyUI 视频连接失败：{str(e)}"
            else:
                # 原有的 OpenAI 兼容视频生成测试逻辑
                test_url = base
                # 策略1: 尝试 GET /models 端点
                try:
                    resp = requests.get(f"{test_url}/models", headers=headers, timeout=10)
                    if resp.status_code in [200, 401, 403]:
                        if resp.status_code == 401:
                            return False, "API Key 无效或已过期"
                        if resp.status_code == 403:
                            return False, "API Key 没有权限访问此资源"
                        return True, f"连接成功！"
                except requests.exceptions.RequestException:
                    pass
                
                # 策略2: 尝试常见的视频生成端点
                video_endpoints = [
                    "/v1/video/generations",
                    "/v2/videos/generations",
                    "/videos/generations",
                    "/video/generate"
                ]
                
                for endpoint in video_endpoints:
                    try:
                        test_payload = {
                            "model": model if model else "veo-3.1",
                            "prompt": "test"
                        }
                        resp = requests.post(f"{test_url}{endpoint}", headers=headers, json=test_payload, timeout=30)
                        if resp.status_code in [200, 400, 401, 403]:
                            if resp.status_code == 401:
                                return False, "API Key 无效或已过期"
                            if resp.status_code == 403:
                                return False, "API Key 没有权限访问此资源"
                            return True, f"连接成功！"
                    except requests.exceptions.RequestException:
                        continue
                
                return False, f"无法连接到指定的 API 地址，请检查 Base URL 是否正确"
            
        except Exception as e:
            return False, f"Video 连接失败: {str(e)}"
    
    def _test_enhance_connection(self, api_key, base_url, provider, config_data):
        """测试视频增强（ComfyUI 工作流）配置：检查服务可达性与已配置的工作流文件。"""
        import os
        try:
            import requests

            if not base_url:
                return False, "请填写 ComfyUI 地址（如 http://192.168.2.4:8188）"

            base = base_url.rstrip('/')
            try:
                resp = requests.get(f"{base}/system_stats", timeout=10, proxies={'http': None, 'https': None})
            except Exception as e:
                return False, f"ComfyUI 连接失败：{str(e)}"

            if resp.status_code != 200:
                return False, f"ComfyUI 连接失败: HTTP {resp.status_code}"

            labels = {
                "workflow_file_upscale": "超分",
                "workflow_file_interp": "帧率提升",
                "workflow_file_dewatermark": "去水印",
                "workflow_file_quality": "画质增强",
                "workflow_file_deblur": "模糊修复",
            }
            configured = []
            missing = []
            for key, label in labels.items():
                path = str(config_data.get(key, "") or "").strip()
                if not path:
                    continue
                if os.path.exists(path):
                    configured.append(label)
                else:
                    missing.append(label)

            if missing:
                return False, f"ComfyUI 连接成功，但工作流文件不存在: {', '.join(missing)}"
            if configured:
                return True, f"ComfyUI 连接成功！已配置增强工作流: {', '.join(configured)}"
            return True, "ComfyUI 连接成功！（未配置增强工作流，将使用本地 ffmpeg 处理）"
        except Exception as e:
            return False, f"视频增强连接失败: {str(e)}"

    def _test_tts_connection(self, api_key, base_url, model, provider):
        try:
            import requests
            
            provider_lower = provider.lower() if provider else ""
            
            if "elevenlabs" in provider_lower:
                resp = requests.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": api_key},
                    timeout=10
                )
                if resp.status_code == 200:
                    return True, "连接成功！ElevenLabs API 有效"
                elif resp.status_code in [401, 403]:
                    return False, "API Key 无效"
                return False, f"连接失败: HTTP {resp.status_code}"
            
            if base_url:
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.get(f"{base_url}/models", headers=headers, timeout=10)
                # 404 说明端点根本不存在，不能判为连接成功
                if resp.status_code in [200, 401, 403]:
                    if resp.status_code == 401:
                        return False, "API Key 无效或已过期"
                    if resp.status_code == 403:
                        return False, "API Key 没有权限访问此资源"
                    return True, f"连接成功！"
                return False, f"连接失败: HTTP {resp.status_code}"
            
            return True, "TTS配置已保存（请手动验证）"
        except Exception as e:
            return False, f"TTS 连接失败: {str(e)}"


class ApiConfigDialog(QDialog):
    def __init__(self, parent=None, config_data=None):
        super().__init__(parent)
        self.setWindowTitle("API 配置")
        self.resize(480, 560)
        self.config_data = config_data or {}
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.name_edit = QLineEdit(self.config_data.get("name", ""))
        self.name_edit.setPlaceholderText("给这个配置起个名字，如 '我的GPT-4'")
        self.name_edit.setStyleSheet("padding: 8px; background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 4px;")
        
        combo_style = """
            QComboBox {
                padding: 8px; 
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """; 
                border: 1px solid """ + _theme.color("border_strong") + """; 
                border-radius: 4px;
            }
            QComboBox:hover {
                background-color: """ + _theme.color("hover") + """;
                border: 1px solid """ + _theme.color("text_sub") + """;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                selection-background-color: """ + _theme.color("accent") + """;
                selection-color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                background-color: transparent; color: """ + _theme.color("text") + """;
                padding: 5px;
                min-height: 20px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
        """
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["LLM", "Embedding", "Image", "Video", "TTS", "ImageToVideo", "VideoEnhance"])
        self.type_combo.setCurrentText(self.config_data.get("type", "LLM"))
        self.type_combo.setStyleSheet(combo_style)
        
        self.provider_edit = QComboBox()
        self.provider_edit.setEditable(False)
        self.provider_edit.addItems(["OpenAI", "Google", "Azure", "DeepSeek", "ElevenLabs", "Runway", "Luma", "Veo", "ComfyUI", "Local"])
        self.provider_edit.setCurrentText(self.config_data.get("provider", "OpenAI"))
        self.provider_edit.setToolTip("选择提供商")
        self.provider_edit.setStyleSheet(combo_style)
        
        self.api_key_edit = QLineEdit(self.config_data.get("api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setStyleSheet("padding: 8px; background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 4px;")
        
        self.base_url_edit = QLineEdit(self.config_data.get("base_url", ""))
        self.base_url_edit.setPlaceholderText("可选，如本地部署地址")
        self.base_url_edit.setStyleSheet("padding: 8px; background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 4px;")
        
        self.model_edit = QLineEdit(self.config_data.get("model", ""))
        self.model_edit.setPlaceholderText("必填，如 gpt-4, sd-xl")
        self.model_edit.setStyleSheet("padding: 8px; background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 4px;")
        
        # 工作流文件选择（仅 ComfyUI 类型显示）
        self.workflow_label = QLabel("工作流文件:")
        self.workflow_label.setVisible(False)
        
        workflow_container = QWidget()
        workflow_layout = QHBoxLayout(workflow_container)
        workflow_layout.setContentsMargins(0, 0, 0, 0)
        
        self.workflow_edit = QLineEdit(self.config_data.get("workflow_file", ""))
        self.workflow_edit.setVisible(False)
        self.workflow_edit.setPlaceholderText("resources/workflows/ 下的 JSON 文件（必填，可点「浏览」选择）")
        workflow_layout.addWidget(self.workflow_edit)
        
        self.workflow_btn = QPushButton("浏览...")
        self.workflow_btn.setVisible(False)
        self.workflow_btn.setFixedSize(60, 30)
        self.workflow_btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; border-radius: 4px;")
        self.workflow_btn.clicked.connect(self.browse_workflow)
        workflow_layout.addWidget(self.workflow_btn)

        # 视频增强（VideoEnhance）工作流文件：超分/帧率提升/去水印/画质增强，各自可选
        self.enhance_label = QLabel("增强工作流:")
        self.enhance_label.setVisible(False)
        self.enhance_label.setToolTip("为各增强功能指定 ComfyUI 工作流；留空的项将回退为本地 ffmpeg 处理")

        self.enhance_container = QWidget()
        enhance_form = QFormLayout(self.enhance_container)
        enhance_form.setContentsMargins(0, 0, 0, 0)

        self.wf_edits = {}
        enhance_fields = [
            ("workflow_file_upscale", "超分:", "视频超分工作流 (如 video_upscale.json)"),
            ("workflow_file_interp", "帧率提升:", "帧插值工作流 (如 video_interp.json)"),
            ("workflow_file_dewatermark", "去水印:", "去水印工作流 (如 video_dewatermark.json)"),
            ("workflow_file_quality", "画质增强:", "画质增强工作流 (如 video_quality.json)"),
            ("workflow_file_deblur", "模糊修复:", "去模糊工作流 (如 video_deblur.json)"),
        ]
        for key, label_text, placeholder in enhance_fields:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            edit = QLineEdit(self.config_data.get(key, ""))
            edit.setPlaceholderText(placeholder)
            edit.setStyleSheet("padding: 8px; background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 4px;")
            row_layout.addWidget(edit)

            btn = QPushButton("浏览...")
            btn.setFixedSize(60, 30)
            btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; border-radius: 4px;")
            btn.clicked.connect(lambda _, e=edit: self._browse_workflow_into(e))
            row_layout.addWidget(btn)

            enhance_form.addRow(label_text, row)
            self.wf_edits[key] = edit

        # 水印位置预设：用户只需点选角落（99% 视频 LOGO 在四角），无需手填坐标
        self.wm_pos_combo = QComboBox()
        self.wm_pos_combo.addItems([
            "右上角 (top-right)",
            "右下角 (bottom-right)",
            "左上角 (top-left)",
            "左下角 (bottom-left)",
            "画面中央 (center)",
            "自动检测 (auto)",
            "自定义 (custom)",
        ])
        pos_to_index = {
            "top-right": 0, "bottom-right": 1, "top-left": 2,
            "bottom-left": 3, "center": 4, "auto": 5, "custom": 6,
        }
        self.wm_pos_combo.setCurrentIndex(pos_to_index.get(
            self.config_data.get("watermark_position", "top-right"), 0))
        self.wm_pos_combo.setStyleSheet(combo_style)
        self.wm_pos_combo.setToolTip(
            "水印所在位置：选角落即可自动换算像素坐标；'自动检测' 会尝试分析多帧方差，"
            "检测失败回退 top-right；'自定义' 需在 custom_xywh 填 x,y,w,h 像素值")
        enhance_form.addRow("水印位置:", self.wm_pos_combo)

        self.wm_pos_hint = QLabel("绝大多数视频平台水印在角落，选对应角落即可；"
                                  "自动检测对有明确 LOGO 的视频最准，自定义适合已知精确坐标的场景。")
        self.wm_pos_hint.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        self.wm_pos_hint.setWordWrap(True)
        enhance_form.addRow("", self.wm_pos_hint)

        # custom 模式坐标输入行（默认隐藏，仅当选 custom 时显示）
        self.wm_custom_row = QWidget()
        wm_custom_layout = QHBoxLayout(self.wm_custom_row)
        wm_custom_layout.setContentsMargins(0, 0, 0, 0)
        wm_custom_layout.addWidget(QLabel("x:"))
        self.wm_x_edit = QLineEdit()
        self.wm_x_edit.setFixedWidth(60)
        self.wm_x_edit.setStyleSheet("padding: 6px; background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 4px;")
        self.wm_x_edit.setPlaceholderText("像素")
        wm_custom_layout.addWidget(self.wm_x_edit)
        wm_custom_layout.addWidget(QLabel("y:"))
        self.wm_y_edit = QLineEdit()
        self.wm_y_edit.setFixedWidth(60)
        self.wm_y_edit.setStyleSheet(self.wm_x_edit.styleSheet())
        wm_custom_layout.addWidget(self.wm_y_edit)
        wm_custom_layout.addWidget(QLabel("w:"))
        self.wm_w_edit = QLineEdit()
        self.wm_w_edit.setFixedWidth(60)
        self.wm_w_edit.setStyleSheet(self.wm_x_edit.styleSheet())
        wm_custom_layout.addWidget(self.wm_w_edit)
        wm_custom_layout.addWidget(QLabel("h:"))
        self.wm_h_edit = QLineEdit()
        self.wm_h_edit.setFixedWidth(60)
        self.wm_h_edit.setStyleSheet(self.wm_x_edit.styleSheet())
        wm_custom_layout.addWidget(self.wm_h_edit)
        wm_custom_layout.addStretch(1)
        enhance_form.addRow("自定义坐标:", self.wm_custom_row)
        self.wm_custom_row.setVisible(self.wm_pos_combo.currentText().startswith("自定义"))
        self.wm_pos_combo.currentIndexChanged.connect(self._on_wm_pos_changed)

        self.enhance_container.setVisible(False)
        self.enhance_hint = QLabel("提示：输入视频经 /upload/image 上传，工作流中首个 LoadVideo 节点会自动写入该视频；"
                                   "输出需为 mp4/webm/gif。未配置工作流的增强项将使用本地 ffmpeg 处理。")
        self.enhance_hint.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        self.enhance_hint.setWordWrap(True)
        self.enhance_hint.setVisible(False)
        
        # 根据类型动态更新显示
        self.type_combo.currentTextChanged.connect(self._update_fields_visibility)
        self.provider_edit.currentTextChanged.connect(self._update_fields_visibility)

        self.default_cb = QCheckBox("设为默认配置")
        self.default_cb.setChecked(self.config_data.get("is_default", False))
        self.default_cb.setToolTip("勾选后，此类型的API调用将优先使用该配置")

        # ---- 单页表单：工作流/增强配置直接并入基本信息页（不再分页签） ----
        form_container = QWidget()
        basic_form = QFormLayout(form_container)
        basic_form.setContentsMargins(16, 16, 16, 16)
        basic_form.setSpacing(12)
        basic_form.addRow("名称 (Name):", self.name_edit)
        basic_form.addRow("类型 (Type):", self.type_combo)
        basic_form.addRow("提供商 (Provider):", self.provider_edit)
        basic_form.addRow("API Key:", self.api_key_edit)
        basic_form.addRow("Base URL:", self.base_url_edit)
        basic_form.addRow("模型 (Model):", self.model_edit)
        basic_form.addRow(self.workflow_label, workflow_container)
        basic_form.addRow(self.enhance_label, self.enhance_container)
        basic_form.addRow("", self.enhance_hint)
        basic_form.addRow("", self.default_cb)
        self._basic_form = basic_form
        layout.addWidget(form_container)

        self.test_result_label = QLabel("")
        self.test_result_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        self.test_result_label.setWordWrap(True)
        layout.addWidget(self.test_result_label)

        btn_layout = QHBoxLayout()

        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self.test_connection)
        btn_layout.addWidget(self.test_btn)

        btn_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        btn_layout.addWidget(buttons)

        layout.addLayout(btn_layout)

        # 初始化字段显示
        self._update_fields_visibility()
    
    def test_connection(self):
        config_data = self.get_data()
        
        config_type = config_data.get("type", "")
        provider = config_data.get("provider", "")
        base_url = config_data.get("base_url", "")
        
        # ComfyUI 类型无需 API Key（仅当提供商明确为 ComfyUI 时，大小写不敏感）；
        # VideoEnhance 一律走 ComfyUI，无需 API Key
        is_comfy = ((config_type in ["Image", "Video"] and provider.lower() == "comfyui")
                    or config_type == "VideoEnhance")
        
        if not is_comfy and not config_data.get("api_key"):
            QMessageBox.warning(self, "提示", "请先输入 API Key")
            return
        
        # ComfyUI 类型需要 base_url
        if is_comfy and not base_url:
            QMessageBox.warning(self, "提示", "请填写 ComfyUI 地址（如 http://192.168.2.4:8188）")
            return
        
        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中...")
        self.test_result_label.setText("正在测试连接...")
        self.test_result_label.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 12px;")
        
        self.test_thread = ConnectionTestThread(config_data)
        self.test_thread.test_finished.connect(self.on_test_finished)
        self.test_thread.start()
    
    def on_test_finished(self, success, message):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试连接")
        
        if success:
            self.test_result_label.setText(f"✅ {message}")
            self.test_result_label.setStyleSheet("color: " + _theme.color("success") + "; font-size: 12px; font-weight: bold;")
        else:
            self.test_result_label.setText(f"❌ {message}")
            self.test_result_label.setStyleSheet("color: " + _theme.color("danger") + "; font-size: 12px;")

    def on_billing_type_changed(self, billing_type):
        self.update_price_stack(billing_type)

    def _update_fields_visibility(self, text=None):
        """根据类型和提供商更新字段显示"""
        type_text = self.type_combo.currentText()
        provider_text = self.provider_edit.currentText()
        
        # 只有类型为 Image/Video 且提供商明确为 ComfyUI 时才显示工作流（大小写不敏感）
        is_comfy = (type_text in ["Image", "Video"] and 
                     provider_text.lower() == "comfyui")
        # 视频增强：使用 ComfyUI 时显示各增强工作流配置
        is_enhance = (type_text == "VideoEnhance")
        
        # ComfyUI 类型：显示工作流，隐藏 model
        self.model_edit.setVisible(not is_comfy and not is_enhance)
        # 隐藏 model 输入框时同步隐藏行标签，避免残留孤立文字
        model_label = self._basic_form.labelForField(self.model_edit)
        if model_label is not None:
            model_label.setVisible(not is_comfy and not is_enhance)
        self.workflow_label.setVisible(is_comfy)
        self.workflow_edit.setVisible(is_comfy)
        self.workflow_btn.setVisible(is_comfy)
        
        self.enhance_label.setVisible(is_enhance)
        self.enhance_container.setVisible(is_enhance)
        self.enhance_hint.setVisible(is_enhance)
        self.wm_custom_row.setVisible(is_enhance and self.wm_pos_combo.currentText().startswith("自定义"))

        # 类型切换时自适应高度：视频增强字段最多，需要更高的窗口
        self.resize(480, 780 if is_enhance else 520)
        
        # 更新提示
        if is_enhance:
            self.base_url_edit.setPlaceholderText("必填，ComfyUI 地址（如 http://192.168.2.4:8188）")
        elif is_comfy:
            self.base_url_edit.setPlaceholderText("可选，如本地部署地址")
            if type_text == "Video":
                self.model_edit.setPlaceholderText("ComfyUI 视频：模型名选填（工作流在「工作流文件」中选择）")
            else:
                self.model_edit.setPlaceholderText("ComfyUI 图片：模型名选填（工作流在「工作流文件」中选择）")
        else:
            self.base_url_edit.setPlaceholderText("可选，如本地部署地址")
            self.model_edit.setPlaceholderText("必填，如 gpt-4, sd-xl")
    
    def browse_workflow(self):
        """浏览选择工作流文件（单工作流字段）"""
        self._browse_workflow_into(self.workflow_edit)
    
    def _on_wm_pos_changed(self, _index):
        """水印位置下拉框切换时，显隐自定义坐标输入行。"""
        self.wm_custom_row.setVisible(self.wm_pos_combo.currentText().startswith("自定义"))

    def _browse_workflow_into(self, line_edit):
        """浏览选择工作流文件并写入指定输入框"""
        import os
        # 默认定位到项目根目录下的 resources/workflows
        project_root = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        )
        default_dir = os.path.join(project_root, "resources", "workflows")
        if not os.path.isdir(default_dir):
            default_dir = "resources/workflows"
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ComfyUI 工作流文件",
            default_dir,
            "JSON Files (*.json)")
        if path:
            line_edit.setText(path)
    
    def _update_model_placeholder(self, text=None):
        """兼容旧方法"""
        self._update_fields_visibility()

    def get_data(self):
        # 工作流文件（仅当类型为 Image/Video 且提供商明确为 ComfyUI 时使用）
        type_text = self.type_combo.currentText()
        provider_text = self.provider_edit.currentText()
        is_comfy = (type_text in ["Image", "Video"] and 
                      provider_text.lower() == "comfyui")
        
        workflow_file = ""
        if is_comfy:
            # 只保存用户在设置里选的工作流；留空就存空——运行时会明确报错提示，
            # 不再偷偷填一个硬编码文件名进配置
            workflow_file = self.workflow_edit.text().strip()

        data = {
            "name": self.name_edit.text(),
            "type": type_text,
            "provider": provider_text,
            "api_key": self.api_key_edit.text(),
            "base_url": self.base_url_edit.text(),
            "model": self.model_edit.text(),
            "workflow_file": workflow_file,
            "is_default": self.default_cb.isChecked()
        }

        # 视频增强工作流文件（各增强功能独立，留空则回退 ffmpeg）
        if type_text == "VideoEnhance":
            for key, edit in self.wf_edits.items():
                data[key] = edit.text().strip()
            idx_to_pos = ["top-right", "bottom-right", "top-left", "bottom-left",
                          "center", "auto", "custom"]
            data["watermark_position"] = idx_to_pos[self.wm_pos_combo.currentIndex()]
            # custom 模式：保存 x/y/w/h 像素坐标
            if data["watermark_position"] == "custom":
                try:
                    custom = [
                        int(self.wm_x_edit.text().strip() or 0),
                        int(self.wm_y_edit.text().strip() or 0),
                        int(self.wm_w_edit.text().strip() or 0),
                        int(self.wm_h_edit.text().strip() or 0),
                    ]
                    data["watermark_custom_xywh"] = custom
                except ValueError:
                    data["watermark_custom_xywh"] = None
            else:
                data["watermark_custom_xywh"] = None

        return data

