from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                              QLabel,
                              QFrame, QMessageBox, QSplitter, QComboBox, QTextEdit,
                              QDialog, QScrollArea, QCheckBox, QLineEdit, QFormLayout,
                              QFileDialog, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
import os
import json
import time
from ui import theme as _theme

try:
    from core.utils.json_store import atomic_write_json
except ImportError:
    from src.core.utils.json_store import atomic_write_json





class VideoGenThread(QThread):
    # 注意：不能覆盖 QThread.finished 内建信号，否则标准线程生命周期管理失效
    video_ready = pyqtSignal(str, str, str)
    
    def __init__(self, panel_id, image_path, prompt, output_path, api_config, text=None, voice_id=None, ratio="16:9", language="English", end_image_path=None, input_video_path=None, duration=10, ref_images=None, ref_labels=None):
        super().__init__()
        self.panel_id = panel_id
        self.image_path = image_path
        self.prompt = prompt
        self.output_path = output_path
        self.api_config = api_config or {}
        self.text = text
        self.voice_id = voice_id
        self.ratio = ratio
        self.language = language
        self.end_image_path = end_image_path
        self.input_video_path = input_video_path
        self.duration = duration
        self.ref_images = ref_images
        self.ref_labels = ref_labels

    def run(self):
        try:
            api_key = self.api_config.get("api_key")
            base_url = self.api_config.get("base_url")
            model = self.api_config.get("model")
            provider = self.api_config.get("provider")

            print(f"DEBUG: Starting video generation for panel {self.panel_id} with provider {provider}, ratio {self.ratio}, language {self.language}")
            from ai_engine.video_gen.video_client import VideoGenClient
            
            client = VideoGenClient(api_key=api_key, base_url=base_url, model=model, provider=provider, api_config=self.api_config)
            
            result = client.generate_video(
                self.image_path,
                self.prompt,
                self.output_path,
                self.text,
                self.voice_id,
                aspect_ratio=self.ratio,
                language=self.language,
                end_image_path=self.end_image_path,
                input_video_path=self.input_video_path,
                duration=self.duration,
                ref_images=self.ref_images,
                ref_labels=self.ref_labels
            )
            
            video_path = None
            task_id = ""
            if isinstance(result, tuple) and len(result) == 2:
                video_path, task_id = result
            else:
                video_path = result
            
            print(f"DEBUG: Video generation finished. Path: {video_path}, TaskID: {task_id}")
            self.video_ready.emit(self.panel_id, video_path or "", task_id or "")
        except Exception as e:
            print(f"DEBUG: Exception in VideoGenThread: {e}")
            import traceback
            traceback.print_exc()
            task_id = ""
            try:
                if 'result' in locals() and isinstance(result, tuple) and len(result) >= 2:
                    task_id = result[1] or ""
            except Exception:
                pass
            self.video_ready.emit(self.panel_id, "", task_id)


class VideoEnhanceDialog(QDialog):
    def __init__(self, video_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("视频增强")
        self.resize(500, 450)
        self.video_path = video_path
        self.selected_enhancements = []
        # 读取 VideoEnhance 类型的 ComfyUI 工作流配置；读取不到时为空 dict（回退 ffmpeg 实现）
        self.api_config = self._load_enhance_config()
        self.init_ui()

    def _load_enhance_config(self):
        """从配置读取 VideoEnhance 类型（ComfyUI 工作流）配置。"""
        try:
            from core.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            config_manager.reload()  # 读取磁盘最新配置，避免使用缓存的旧值
            configs = config_manager.get("api_configs", []) or []
            config = next((c for c in configs if c.get("type") == "VideoEnhance"), None)
            if config:
                print(f"[VideoEnhance] 使用配置: {config.get('name')} (provider={config.get('provider')})")
                return config
            print("[VideoEnhance] 未找到 VideoEnhance 配置，将使用 ffmpeg 本地增强")
            return {}
        except Exception as e:
            print(f"[VideoEnhance] 读取增强配置失败: {e}")
            return {}
    
    def init_ui(self):
        # 背景交由全局主题管理
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        header = QLabel("选择视频增强功能")
        header.setStyleSheet("color: " + _theme.color("warning") + "; font-weight: bold; font-size: 16px;")
        layout.addWidget(header)
        
        desc = QLabel("请选择需要应用的增强功能（可多选）：")
        desc.setStyleSheet("color: " + _theme.color("text_sub") + "; margin-bottom: 10px;")
        layout.addWidget(desc)
        
        self.enhancement_tags = QFrame()
        self.enhancement_tags.setObjectName("PanelBG")
        tags_layout = QVBoxLayout(self.enhancement_tags)
        
        self.tag_buttons = {}
        enhancements = [
            ("remove_watermark", "视频去水印", "去除视频中的水印标识"),
            ("super_resolution", "视频超分 (8K)", "将视频分辨率提升至8K级别"),
            ("quality_enhance", "画质增强", "提升视频整体画质和清晰度"),
            ("frame_interpolation", "帧率提升", "提高视频帧率，使画面更流畅"),
            ("deblur", "模糊修复", "修复视频中的模糊区域"),
        ]
        
        for key, name, tooltip in enhancements:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                    padding: 12px 20px;
                    border-radius: 5px;
                    text-align: left;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: """ + _theme.color("accent") + """;
                }
                QPushButton:checked {
                    background-color: """ + _theme.color("success") + """;
                    border: 2px solid """ + _theme.color("success") + """;
                }
            """)
            btn.clicked.connect(lambda checked, k=key: self.toggle_enhancement(k, checked))
            tags_layout.addWidget(btn)
            self.tag_buttons[key] = btn
        
        layout.addWidget(self.enhancement_tags)
        
        video_info_frame = QFrame()
        video_info_frame.setObjectName("PanelBG")
        info_layout = QVBoxLayout(video_info_frame)
        
        video_info_label = QLabel("当前视频:")
        video_info_label.setStyleSheet("color: " + _theme.color("text_sub") + ";")
        info_layout.addWidget(video_info_label)
        
        self.video_path_label = QLabel(self.video_path or "未选择视频")
        self.video_path_label.setStyleSheet("color: " + _theme.color("accent") + "; word-wrap: break-word;")
        self.video_path_label.setWordWrap(True)
        info_layout.addWidget(self.video_path_label)
        
        layout.addWidget(video_info_frame)
        
        self.preview_label = QLabel("已选择: 无")
        self.preview_label.setStyleSheet("color: " + _theme.color("warning") + "; margin-top: 10px;")
        layout.addWidget(self.preview_label)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px 25px; border-radius: 5px;")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        self.enhance_btn = QPushButton("开始增强")
        self.enhance_btn.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; padding: 10px 25px; border-radius: 5px; font-weight: bold;")
        self.enhance_btn.clicked.connect(self.start_enhance)
        btn_layout.addWidget(self.enhance_btn)
        
        layout.addLayout(btn_layout)
    
    def toggle_enhancement(self, key, checked):
        if checked:
            if key not in self.selected_enhancements:
                self.selected_enhancements.append(key)
        else:
            if key in self.selected_enhancements:
                self.selected_enhancements.remove(key)
        self.update_preview()
    
    def update_preview(self):
        if self.selected_enhancements:
            names = []
            enhancement_names = {
                "remove_watermark": "去水印",
                "super_resolution": "超分(8K)",
                "quality_enhance": "画质增强",
                "frame_interpolation": "帧率提升",
                "deblur": "模糊修复"
            }
            for key in self.selected_enhancements:
                names.append(enhancement_names.get(key, key))
            self.preview_label.setText(f"已选择: {', '.join(names)}")
        else:
            self.preview_label.setText("已选择: 无")
    
    def start_enhance(self):
        if not self.selected_enhancements:
            QMessageBox.warning(self, "提示", "请至少选择一项增强功能")
            return
        
        if not self.video_path:
            QMessageBox.warning(self, "提示", "未选择视频文件")
            return
        
        # 获取输出路径
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存增强后的视频",
            os.path.splitext(self.video_path)[0] + "_enhanced.mp4",
            "视频文件 (*.mp4 *.mov *.avi);;所有文件 (*.*)"
        )
        
        if not output_path:
            return
        
        # 禁用按钮，显示进度
        self.enhance_btn.setEnabled(False)
        self.enhance_btn.setText("增强中...")
        self.progress_label = QLabel("准备开始...")
        self.progress_label.setStyleSheet("color: " + _theme.color("warning") + ";")
        self.layout().insertWidget(self.layout().count() - 1, self.progress_label)
        
        # 创建并启动增强线程
        self.enhance_thread = VideoEnhanceWorker(
            self.video_path,
            self.selected_enhancements,
            output_path,
            self.api_config
        )
        self.enhance_thread.progress.connect(self.update_progress)
        self.enhance_thread.enhance_done.connect(self.on_enhance_finished)
        self.enhance_thread.error.connect(self.on_enhance_error)
        self.enhance_thread.start()
    
    def update_progress(self, progress, message):
        """更新进度"""
        self.progress_label.setText(f"{progress}% - {message}")
        self.enhance_btn.setText(f"增强中... {progress}%")
    
    def on_enhance_finished(self, output_path):
        """增强完成"""
        QMessageBox.information(self, "完成", f"视频增强完成!\n已保存至: {output_path}")
        self.enhanced_video_path = output_path
        self.accept()
    
    def on_enhance_error(self, error_msg):
        """增强出错"""
        QMessageBox.critical(self, "错误", f"视频增强失败:\n{error_msg}")
        self.enhance_btn.setEnabled(True)
        self.enhance_btn.setText("开始增强")
        if hasattr(self, 'progress_label'):
            self.progress_label.setText("增强失败")
    
    def get_selected_enhancements(self):
        return self.selected_enhancements
    
    def get_enhanced_video_path(self):
        return getattr(self, 'enhanced_video_path', None)

    def closeEvent(self, event):
        # 增强线程运行中不允许关闭，避免悬空槽调用崩溃
        if hasattr(self, 'enhance_thread') and self.enhance_thread and self.enhance_thread.isRunning():
            QMessageBox.information(self, "提示", "增强仍在进行中，请等待完成或出错后再关闭。")
            event.ignore()
            return
        super().closeEvent(event)


class VideoEnhanceWorker(QThread):
    """视频增强工作线程"""
    progress = pyqtSignal(int, str)
    # 注意：不能覆盖 QThread.finished 内建信号
    enhance_done = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, video_path, enhancements, output_path, api_config=None):
        super().__init__()
        self.video_path = video_path
        self.enhancements = enhancements
        self.output_path = output_path
        self.api_config = api_config or {}
        
    def run(self):
        try:
            from ai_engine.video_enhance import VideoEnhanceClient
            
            # 创建客户端并设置进度回调（传入 api_config 以便对接 ComfyUI 工作流）
            client = VideoEnhanceClient(api_config=self.api_config)
            client.set_progress_callback(lambda p, m: self.progress.emit(p, m))
            
            # 执行增强
            result = client.enhance_video(
                self.video_path,
                self.enhancements,
                self.output_path
            )
            
            if result and os.path.exists(result):
                self.enhance_done.emit(result)
            else:
                self.error.emit("增强失败，未生成输出文件")
                
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.error.emit(error_msg)


class AdvancedVideoParamsDialog(QDialog):
    def __init__(self, current_params=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高级视频参数")
        self.resize(450, 400)
        self.current_params = current_params or {}
        self.result_params = {}
        self.init_ui()
    
    def init_ui(self):
        # 背景交由全局主题管理
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        video_type_opts = [
            ("无", ""),
            ("电影级中景", "Cinematic medium shot"),
            ("电影级特写", "Cinematic close-up shot"),
            ("电影级广角", "Cinematic wide shot"),
            ("牛仔镜头", "Cinematic cowboy shot"),
            ("过肩镜头", "Over-the-shoulder shot"),
            ("第一人称视角", "POV shot"),
            ("群像镜头", "Cinematic group shot"),
            ("航拍镜头", "Aerial shot"),
            ("鱼眼镜头", "Fisheye shot"),
            ("微距镜头", "Macro shot")
        ]
        
        video_viewpoint_opts = [
            ("无", ""),
            ("正视", "Eye-level"),
            ("俯视", "High angle"),
            ("仰视", "Low angle"),
            ("侧视", "Side profile"),
            ("顶视", "Top-down"),
            ("虫视", "Worm's eye view"),
            ("荷兰角", "Dutch angle"),
            ("自拍视角", "Selfie view")
        ]
        
        video_composition_opts = [
            ("无", ""),
            ("居中构图", "Centered composition"),
            ("三分法", "Rule of thirds"),
            ("对称构图", "Symmetrical composition"),
            ("黄金比例", "Golden ratio"),
            ("引导线", "Leading lines"),
            ("极简构图", "Minimalist"),
            ("景深虚化", "Depth of field"),
            ("框架构图", "Framing")
        ]
        
        video_lighting_opts = [
            ("无", ""),
            ("自然光", "Natural lighting"),
            ("电影布光", "Cinematic lighting"),
            ("柔光", "Soft lighting"),
            ("侧光", "Side lighting"),
            ("逆光", "Backlighting"),
            ("伦勃朗光", "Rembrandt lighting"),
            ("赛博朋克霓虹", "Cyberpunk neon"),
            ("黄金时刻", "Golden hour"),
            ("蓝色时刻", "Blue hour"),
            ("阴郁光线", "Moody lighting"),
            ("摄影棚光", "Studio lighting"),
            ("体积光", "Volumetric lighting")
        ]
        
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        self.shot_type_combo = QComboBox()
        self.shot_type_combo.setStyleSheet(self._get_combo_style())
        for label, value in video_type_opts:
            self.shot_type_combo.addItem(label, value)
        self._set_combo_current(self.shot_type_combo, self.current_params.get("shot_type", ""))
        form_layout.addRow("镜头类型:", self.shot_type_combo)
        
        self.viewpoint_combo = QComboBox()
        self.viewpoint_combo.setStyleSheet(self._get_combo_style())
        for label, value in video_viewpoint_opts:
            self.viewpoint_combo.addItem(label, value)
        self._set_combo_current(self.viewpoint_combo, self.current_params.get("viewpoint", ""))
        form_layout.addRow("视角:", self.viewpoint_combo)
        
        self.composition_combo = QComboBox()
        self.composition_combo.setStyleSheet(self._get_combo_style())
        for label, value in video_composition_opts:
            self.composition_combo.addItem(label, value)
        self._set_combo_current(self.composition_combo, self.current_params.get("composition", ""))
        form_layout.addRow("构图法:", self.composition_combo)
        
        self.lighting_combo = QComboBox()
        self.lighting_combo.setStyleSheet(self._get_combo_style())
        for label, value in video_lighting_opts:
            self.lighting_combo.addItem(label, value)
        self._set_combo_current(self.lighting_combo, self.current_params.get("lighting", ""))
        form_layout.addRow("光线:", self.lighting_combo)
        
        layout.addLayout(form_layout)
        
        preview_label = QLabel("预览效果:")
        preview_label.setStyleSheet("color: " + _theme.color("text_sub") + "; margin-top: 10px;")
        layout.addWidget(preview_label)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(100)
        self.preview_text.setStyleSheet("background-color: " + _theme.color("panel") + "; border: 1px solid " + _theme.color("panel2") + "; border-radius: 5px; padding: 5px;")
        layout.addWidget(self.preview_text)
        
        self.shot_type_combo.currentIndexChanged.connect(self.update_preview)
        self.viewpoint_combo.currentIndexChanged.connect(self.update_preview)
        self.composition_combo.currentIndexChanged.connect(self.update_preview)
        self.lighting_combo.currentIndexChanged.connect(self.update_preview)
        
        self.update_preview()
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 8px 20px; border-radius: 5px;")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; padding: 8px 20px; border-radius: 5px; font-weight: bold;")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        layout.addLayout(btn_layout)
    
    def _get_combo_style(self):
        return """
            QComboBox {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                border-radius: 5px;
                padding: 8px;
                min-width: 200px;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 8px solid """ + _theme.color("warning") + """;
                margin-right: 10px;
            }
            QComboBox QAbstractItemView {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                selection-background-color: """ + _theme.color("accent") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
        """
    
    def _set_combo_current(self, combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                break
    
    def update_preview(self):
        parts = []
        
        shot_type = self.shot_type_combo.currentData()
        if shot_type:
            parts.append(shot_type)
        
        viewpoint = self.viewpoint_combo.currentData()
        if viewpoint:
            parts.append(viewpoint)
        
        composition = self.composition_combo.currentData()
        if composition:
            parts.append(composition)
        
        lighting = self.lighting_combo.currentData()
        if lighting:
            parts.append(lighting)
        
        if parts:
            preview = ", ".join(parts)
            self.preview_text.setPlainText(preview)
        else:
            self.preview_text.setPlainText("未选择任何高级参数")
    
    def get_params(self):
        params = {}
        
        shot_type = self.shot_type_combo.currentData()
        if shot_type:
            params["shot_type"] = shot_type
        
        viewpoint = self.viewpoint_combo.currentData()
        if viewpoint:
            params["viewpoint"] = viewpoint
        
        composition = self.composition_combo.currentData()
        if composition:
            params["composition"] = composition
        
        lighting = self.lighting_combo.currentData()
        if lighting:
            params["lighting"] = lighting
        
        return params
    
    def accept(self):
        self.result_params = self.get_params()
        super().accept()


class BatchVideoDialog(QDialog):
    def __init__(self, storyboard_data, project_dir, current_panel_idx=-1, parent=None):
        super().__init__(parent)
        print("DEBUG: BatchVideoDialog.__init__ started")
        try:
            self.setWindowTitle("生成视频")
            self.resize(900, 600)
            self.storyboard_data = storyboard_data
            self.project_dir = project_dir
            self.current_panel_idx = current_panel_idx
            from core.config.config_manager import ConfigManager
            self.config_manager = ConfigManager()
            self.selected_panels = set()
            self.init_ui()
            print("DEBUG: BatchVideoDialog.__init__ finished")
        except Exception as e:
            print(f"ERROR in BatchVideoDialog.__init__: {e}")
            import traceback
            traceback.print_exc()
            raise e

    def load_video_models(self):
        configs = self.config_manager.get("api_configs", [])
        video_configs = [c for c in configs if c.get("type") in ["Video", "ImageToVideo"]]
        
        self.model_combo.clear()
        
        default_index = 0
        for i, config in enumerate(video_configs):
            name = config.get("name", f"{config.get('provider')} - {config.get('model')}")
            self.model_combo.addItem(name, config)
            if config.get("is_default"):
                default_index = i
            
        if video_configs:
            self.model_combo.setCurrentIndex(default_index)

    def get_selected_config(self):
        config = self.model_combo.currentData() or {}
        config = config.copy()
        if hasattr(self, 'prompt_input') and self.prompt_input.text().strip():
            config['prompt_suffix'] = self.prompt_input.text().strip()
        if hasattr(self, 'chk_extend_video'):
            config['extend_video'] = self.chk_extend_video.isChecked()
        return config

    def init_ui(self):
        # 背景交由全局主题管理
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        
        self.btn_batch = QPushButton("生成视频")
        self.btn_batch.setCheckable(True)
        self.btn_batch.setChecked(True)
        self.btn_batch.setStyleSheet("background-color: transparent; color: " + _theme.color("warning") + "; font-size: 16px; font-weight: bold; border-bottom: 2px solid " + _theme.color("warning") + ";")
        
        header_layout.addWidget(self.btn_batch)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        config_frame = QFrame()
        config_frame.setObjectName("PanelBG")
        config_layout = QVBoxLayout(config_frame)
        
        row1 = QHBoxLayout()
        lbl_model = QLabel("视频模型:")
        lbl_model.setStyleSheet("font-size: 14px; color: " + _theme.color("text_sub") + ";")
        row1.addWidget(lbl_model)
        
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)
        self.model_combo.setStyleSheet("""
            QComboBox {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("text_sub") + """;
                border-radius: 5px;
                padding: 5px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                selection-background-color: """ + _theme.color("accent") + """;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
        """)
        self.load_video_models()
        row1.addWidget(self.model_combo)
        
        self.chk_extend_video = QCheckBox("视频延展 (Video Extension)")
        self.chk_extend_video.setStyleSheet("color: " + _theme.color("text_sub") + "; margin-left: 10px;")
        self.chk_extend_video.setToolTip("如勾选，将尝试使用上一分镜视频作为输入，生成当前分镜视频，实现连续镜头。\n注意：上一分镜须已有视频。")
        row1.addWidget(self.chk_extend_video)
        
        row1.addStretch()
        config_layout.addLayout(row1)
        
        row2 = QHBoxLayout()
        lbl_prompt = QLabel("附加提示词:")
        lbl_prompt.setStyleSheet("font-size: 14px; color: " + _theme.color("text_sub") + ";")
        row2.addWidget(lbl_prompt)
        
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("输入附加提示词 (可选)...")
        self.prompt_input.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("text_sub") + "; border-radius: 5px; padding: 5px;")
        row2.addWidget(self.prompt_input)
        config_layout.addLayout(row2)
        
        layout.addWidget(config_frame)

        self.chk_all = QCheckBox("全选")
        self.chk_all.setStyleSheet("margin-left: 10px; font-size: 14px;")
        self.chk_all.stateChanged.connect(self.toggle_all)
        layout.addWidget(self.chk_all)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("PanelBG")
        
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setSpacing(10)
        
        self.checkboxes = []
        
        panels = self.storyboard_data.get("panels", [])
        for i, panel in enumerate(panels):
            # 分镜图片已下线：无图片时仍列出分镜（改由角色/场景/道具参考图 + 提示词生成视频）
            item_frame = QFrame()
            item_frame.setFixedHeight(80)
            item_frame.setObjectName("PanelBG2")
            item_layout = QHBoxLayout(item_frame)
            
            chk = QCheckBox()
            chk.setProperty("panel_id", panel.get("panel_id", f"p_{i+1}"))
            chk.stateChanged.connect(self.update_selection)
            
            if i == self.current_panel_idx:
                chk.setChecked(True)
                
            self.checkboxes.append(chk)
            item_layout.addWidget(chk)
            
            idx_lbl = QLabel(f"{i+1:02d}")
            idx_lbl.setStyleSheet("color: " + _theme.color("warning") + "; font-weight: bold; font-size: 16px;")
            item_layout.addWidget(idx_lbl)
            
            script_title = self.storyboard_data.get("script_title", "Unknown")
            info_text = f"项目: {script_title} | 场景: {panel.get('scene_id', '')} | 分镜: {panel.get('panel_id', '')}"
            lbl_info = QLabel(info_text)
            lbl_info.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
            item_layout.addWidget(lbl_info)
            
            item_layout.addStretch()
            
            self.list_layout.addWidget(item_frame)
            
        self.list_layout.addStretch()
        scroll.setWidget(self.list_widget)
        layout.addWidget(scroll)
        
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(100, 40)
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_next = QPushButton("下一步")
        btn_next.setFixedSize(100, 40)
        btn_next.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; border-radius: 5px;")
        btn_next.clicked.connect(self.accept)
        
        footer_layout.addWidget(btn_cancel)
        footer_layout.addWidget(btn_next)
        
        layout.addLayout(footer_layout)

    def toggle_all(self, state):
        for chk in self.checkboxes:
            chk.setChecked(state == Qt.CheckState.Checked.value)

    def update_selection(self, state=None):
        pass

    def accept(self):
        super().accept()
                
    def get_selected_panels(self):
        selected = []
        for chk in self.checkboxes:
            if chk.isChecked():
                pid = chk.property("panel_id")
                if pid:
                    selected.append(pid)
        print(f"DEBUG: get_selected_panels found {len(selected)} items: {selected}")
        return selected


class VideoGenWindow(QWidget):
    """分镜视频生成窗口"""
    add_to_timeline = pyqtSignal(str)
    add_to_library = pyqtSignal(str)  # 添加视频到素材库信号
    
    def __init__(self, project_dir=None, parent=None):
        super().__init__(parent)
        self.project_dir = project_dir
        self.current_storyboard = None
        self.current_episode_id = None
        self.current_panel_index = -1
        self.video_queue = []
        self.video_thread = None
        self.current_video_config = None
        self.project_style = None
        self.advanced_params = {}
        self.init_ui()
        if self.project_dir:
            self.load_episodes()
    
    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        center_area = QWidget()
        center_area.setObjectName("CenterArea")
        center_layout = QVBoxLayout(center_area)
        # 边距收窄：该面板在视频页被约束为窄栏，需要给内容更多可用宽度
        center_layout.setContentsMargins(8, 8, 8, 8)

        # 顶部工具条：集数/分镜选择 + 加载按钮（最右）
        toolbar = QFrame()
        toolbar.setObjectName("ToolbarBG")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 6, 4, 6)
        toolbar_layout.setSpacing(6)

        combo_style = """
            QComboBox {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                border-radius: 3px;
                padding: 3px 4px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
                width: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                selection-background-color: """ + _theme.color("accent") + """;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
        """

        self.episode_combo = QComboBox()
        # 分集名称（如「第1集: 女神降临」）较长，让它占满剩余宽度，避免被截断
        self.episode_combo.setMinimumWidth(140)
        self.episode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.episode_combo.setStyleSheet(combo_style)
        self.episode_combo.currentIndexChanged.connect(self.on_episode_changed)
        # 名称仍可能被省略号截断，悬停显示完整分集名
        self.episode_combo.currentTextChanged.connect(self.episode_combo.setToolTip)
        toolbar_layout.addWidget(self.episode_combo, 1)

        self.shot_combo = QComboBox()
        # 分镜框收窄到刚好容纳「分镜1 ✓」，把宽度让给分集下拉
        self.shot_combo.setFixedWidth(84)
        self.shot_combo.setStyleSheet(combo_style)
        self.shot_combo.currentIndexChanged.connect(self.on_shot_selected)
        toolbar_layout.addWidget(self.shot_combo)

        load_btn = QPushButton("加载")
        load_btn.setToolTip("加载所选分镜的提示词")
        load_btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; padding: 3px 4px; border-radius: 3px; font-size: 12px;")
        load_btn.clicked.connect(self.load_storyboard)
        toolbar_layout.addWidget(load_btn)

        center_layout.addWidget(toolbar)
        
        prompt_frame = QFrame()
        prompt_frame.setObjectName("PanelBG")
        prompt_layout = QVBoxLayout(prompt_frame)
        prompt_layout.setContentsMargins(10, 10, 10, 10)
        
        self.prompt_text = QTextEdit()
        self.prompt_text.setPlaceholderText("视频生成提示词将自动从剧本功能获取...")
        self.prompt_text.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("accent") + "; border: 1px solid " + _theme.color("panel2") + "; border-radius: 4px; padding: 10px; min-height: 100px;")
        prompt_layout.addWidget(self.prompt_text)

        # 只有「视频提示词」一个内容区，直接用面板承载，不再套一层标签页
        center_layout.addWidget(prompt_frame)
        
        bottom_frame = QFrame()
        bottom_frame.setObjectName("ThemedDialog")
        bottom_layout = QHBoxLayout(bottom_frame)
        
        self.gen_video_btn = QPushButton("🎥 生成视频")
        self.gen_video_btn.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("accent_text") + "; padding: 6px 9px; border-radius: 5px; font-size: 12px; font-weight: bold;")
        self.gen_video_btn.clicked.connect(self.open_batch_video_dialog)
        self.gen_video_btn.setEnabled(False)
        bottom_layout.addWidget(self.gen_video_btn)
        
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet("background-color: " + _theme.color("success") + "; color: " + _theme.color("text") + "; padding: 6px 9px; border-radius: 5px; font-size: 12px;")
        save_btn.clicked.connect(self.save_changes)
        bottom_layout.addWidget(save_btn)
        
        # 高级参数：紧邻「生成视频」，便于生成前调整参数
        self.advanced_params_btn = QPushButton("⚙️ 高级参数")
        self.advanced_params_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
                padding: 6px 9px;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("accent2") + """;
            }
        """)
        self.advanced_params_btn.clicked.connect(self.open_advanced_params_dialog)
        bottom_layout.addWidget(self.advanced_params_btn)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        bottom_layout.addWidget(self.status_label)
        
        bottom_layout.addStretch()
        
        center_layout.addWidget(bottom_frame)
        main_layout.addWidget(center_area)

        self._polish_buttons()

    def _polish_buttons(self):
        """补齐按钮的手型光标与悬停/按下反馈（幂等，可重复调用）。"""
        feedback = f"""
QPushButton:hover {{ border: 1px solid {_theme.color("accent")}; }}
QPushButton:pressed {{ border: 1px solid {_theme.color("accent2")}; }}
"""
        for btn in self.findChildren(QPushButton):
            base = btn.property("_base_qss")
            if base is None:
                base = _theme.as_rule_block(btn.styleSheet() or "")
                btn.setProperty("_base_qss", base)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(base + feedback)
    
    def set_project_dir(self, project_dir):
        self.project_dir = project_dir
        self.load_episodes()

    def load_episodes(self):
        self.episode_combo.clear()
        if not self.project_dir:
            return
        
        series_path = os.path.join(self.project_dir, "series.json")
        if os.path.exists(series_path):
            try:
                with open(series_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    episodes = data.get("episodes", [])
                    for ep in episodes:
                        self.episode_combo.addItem(f"第{ep.get('id', 1)}集: {ep.get('title', '')}", ep.get("id"))
                    if self.episode_combo.count() > 0:
                        self.current_episode_id = self.episode_combo.itemData(0)
                        self.load_storyboard()
            except Exception as e:
                print(f"Error loading episodes: {e}")
        else:
            self.episode_combo.addItem("第1集", 1)
            self.current_episode_id = 1
            self.load_storyboard()
    
    def on_episode_changed(self, index):
        if index >= 0:
            self.current_episode_id = self.episode_combo.currentData()
            self.load_storyboard()
    
    def load_storyboard(self):
        if not self.project_dir:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        
        # 如果没有当前剧集ID，尝试从下拉框获取
        if not self.current_episode_id:
            if self.episode_combo.count() > 0:
                self.current_episode_id = self.episode_combo.currentData()
            else:
                # 单集项目，使用默认ID 1
                self.current_episode_id = 1
        
        storyboard_path = os.path.join(self.project_dir, "storyboards", f"episode_{self.current_episode_id}.json")
        
        # 如果没有分镜文件，尝试加载剧本数据来自动生成
        if not os.path.exists(storyboard_path):
            # 尝试从剧本生成基础分镜数据
            script_path = os.path.join(self.project_dir, "scripts", f"episode_{self.current_episode_id}.json")
            if not os.path.exists(script_path):
                script_path = os.path.join(self.project_dir, "current_script.json")
            
            if os.path.exists(script_path):
                try:
                    from core.script.script_model import Script
                    from core.storyboard.storyboard_model import Storyboard, Panel
                    
                    with open(script_path, "r", encoding="utf-8") as f:
                        script = Script.from_json(f.read())
                    
                    # 创建基础分镜数据
                    self.current_storyboard = {
                        "script_title": script.title,
                        "panels": []
                    }
                    
                    # 从剧本场景生成分镜
                    for i, scene in enumerate(script.scenes):
                        panel = {
                            "panel_id": f"p_{i+1}",
                            "scene_id": getattr(scene, 'shot_id', None) or scene.scene_id,
                            "description": scene.description or "",
                            "video_prompt": getattr(scene, 'video_prompt', "") or "",
                            "video_path": "",
                            "characters": [],
                            "prompt_params": {},
                            "video_params": {}
                        }
                        self.current_storyboard["panels"].append(panel)
                    
                    self.refresh_shot_list()
                    self.gen_video_btn.setEnabled(True)
                    return
                except Exception as e:
                    print(f"从剧本生成分镜失败: {e}")
            
            # 分镜文件不存在，清空数据
            self.current_storyboard = None
            self.shot_combo.clear()
            self.gen_video_btn.setEnabled(False)
            return
        
        try:
            import json
            with open(storyboard_path, "r", encoding="utf-8") as f:
                self.current_storyboard = json.load(f)
            
            # 尝试从剧本同步最新的视频提示词
            self._sync_prompts_from_script()
            
            self.refresh_shot_list()
            self.gen_video_btn.setEnabled(True)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载失败: {str(e)}")
    
    def _sync_prompts_from_script(self):
        """从剧本同步最新的视频提示词"""
        if not self.current_storyboard:
            print("DEBUG: No storyboard loaded, skipping sync")
            return
        
        # 尝试加载剧本
        script_path = os.path.join(self.project_dir, "scripts", f"episode_{self.current_episode_id}.json")
        print(f"DEBUG: Looking for script at: {script_path}")
        if not os.path.exists(script_path):
            script_path = os.path.join(self.project_dir, "current_script.json")
            print(f"DEBUG: Looking for script at: {script_path}")
        
        if not os.path.exists(script_path):
            print(f"DEBUG: Script file not found")
            return
        
        print(f"DEBUG: Found script file: {script_path}")
        
        try:
            from core.script.script_model import Script
            
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()
                script = Script.from_json(script_content)
            
            print(f"DEBUG: Loaded script with {len(script.scenes)} scenes")
            
            panels = self.current_storyboard.get("panels", [])
            print(f"DEBUG: Storyboard has {len(panels)} panels")
            
            updated_count = 0
            
            # 为每个分镜同步提示词
            for panel in panels:
                scene_id = panel.get("scene_id", "")
                panel_id = panel.get("panel_id", "unknown")
                print(f"DEBUG: Processing panel {panel_id}, scene_id: {scene_id}")
                
                # 在剧本中查找对应的场景
                found = False
                for scene in script.scenes:
                    scene_scene_id = getattr(scene, 'scene_id', '')
                    scene_shot_id = getattr(scene, 'shot_id', '')
                    
                    if scene_scene_id == scene_id or scene_shot_id == scene_id:
                        found = True
                        print(f"DEBUG: Found matching scene for panel {panel_id}")
                        
                        # 同步视频提示词（如果剧本中有且更新）
                        script_video_prompt = getattr(scene, 'video_prompt', "")
                        print(f"DEBUG: Scene video_prompt length: {len(script_video_prompt) if script_video_prompt else 0}")
                        if script_video_prompt and script_video_prompt.strip():
                            # 只要有视频提示词就同步，不再严格检查格式
                            # 这样可以支持各种格式的视频提示词
                            panel["video_prompt"] = script_video_prompt
                            print(f"DEBUG: Updated video_prompt for panel {panel_id}")
                            updated_count += 1
                        else:
                            print(f"DEBUG: No video_prompt found for panel {panel_id}")
                        
                        break
                
                if not found:
                    print(f"DEBUG: No matching scene found for panel {panel_id} with scene_id {scene_id}")
            
            print(f"DEBUG: Synced {updated_count} prompts from script for {len(panels)} panels")
            
            # 保存更新后的分镜数据
            if updated_count > 0:
                self.save_storyboard()
                print(f"DEBUG: Saved updated storyboard")
            
        except Exception as e:
            print(f"DEBUG: Failed to sync prompts from script: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_video_prompt_from_script(self, panel):
        """直接从剧本文件获取最新的视频提示词"""
        if not self.project_dir or not panel:
            return panel.get("video_prompt", "")
        
        panel_id = panel.get("panel_id", "")
        
        # 尝试加载剧本文件
        script_path = os.path.join(self.project_dir, "scripts", f"episode_{self.current_episode_id}.json")
        if not os.path.exists(script_path):
            script_path = os.path.join(self.project_dir, "current_script.json")
        
        if not os.path.exists(script_path):
            print(f"DEBUG: Script file not found for panel {panel_id}")
            return panel.get("video_prompt", "")
        
        try:
            from core.script.script_model import Script
            
            with open(script_path, "r", encoding="utf-8") as f:
                script = Script.from_json(f.read())
            
            print(f"DEBUG: Loaded script with {len(script.scenes)} scenes for panel {panel_id}")
            
            # 通过 panel_id 的索引来匹配剧本中的场景
            # panel_id 格式为 "p_1", "p_2" 等
            try:
                panel_index = int(panel_id.split("_")[1]) - 1  # "p_1" -> 0
                if 0 <= panel_index < len(script.scenes):
                    scene = script.scenes[panel_index]
                    script_video_prompt = getattr(scene, 'video_prompt', "")
                    print(f"DEBUG: Found scene at index {panel_index}, video_prompt length: {len(script_video_prompt) if script_video_prompt else 0}")
                    if script_video_prompt and script_video_prompt.strip():
                        return script_video_prompt
            except (IndexError, ValueError) as e:
                print(f"DEBUG: Error parsing panel_id {panel_id}: {e}")
            
            # 如果通过索引找不到，尝试通过 scene_id 匹配
            scene_id = panel.get("scene_id", "")
            if scene_id:
                for scene in script.scenes:
                    scene_scene_id = getattr(scene, 'scene_id', '')
                    scene_shot_id = getattr(scene, 'shot_id', '')
                    
                    if scene_scene_id == scene_id or scene_shot_id == scene_id:
                        script_video_prompt = getattr(scene, 'video_prompt', "")
                        print(f"DEBUG: Found scene by scene_id {scene_id}, video_prompt length: {len(script_video_prompt) if script_video_prompt else 0}")
                        if script_video_prompt and script_video_prompt.strip():
                            return script_video_prompt
                        break
            
            # 如果在剧本中没找到，返回分镜数据中的提示词
            print(f"DEBUG: Using panel video_prompt for {panel_id}")
            return panel.get("video_prompt", "")
            
        except Exception as e:
            print(f"DEBUG: Error reading video_prompt from script: {e}")
            import traceback
            traceback.print_exc()
            return panel.get("video_prompt", "")
    
    def refresh_shot_list(self):
        # 填充顶部分镜下拉框（原左侧 QListWidget 简化而来）
        self.shot_combo.blockSignals(True)
        self.shot_combo.clear()
        if not self.current_storyboard:
            self.shot_combo.blockSignals(False)
            return

        panels = self.current_storyboard.get("panels", [])
        for i, panel in enumerate(panels):
            video_status = "✓" if panel.get("video_path") else "○"

            item_text = f"分镜{i+1} {video_status}"
            self.shot_combo.addItem(item_text, i)

        self.shot_combo.blockSignals(False)
        if self.shot_combo.count() > 0:
            self.shot_combo.setCurrentIndex(0)
            self.on_shot_selected(0)
    
    def open_advanced_params_dialog(self):
        dialog = AdvancedVideoParamsDialog(self.advanced_params, self)
        if dialog.exec():
            self.advanced_params = dialog.result_params
            self.apply_advanced_params_to_prompt()
    
    def apply_advanced_params_to_prompt(self):
        if not self.advanced_params:
            return
        
        current_prompt = self.prompt_text.toPlainText().strip()
        
        params_parts = []
        for key, value in self.advanced_params.items():
            if value:
                params_parts.append(value)
        
        if params_parts:
            params_str = ", ".join(params_parts)
            
            existing_prompt = current_prompt
            for key, value in self.advanced_params.items():
                if value and value in existing_prompt:
                    existing_prompt = existing_prompt.replace(value, "").strip()
                    existing_prompt = existing_prompt.replace(", ,", ",").strip()
                    existing_prompt = existing_prompt.strip(",").strip()
            
            if existing_prompt:
                new_prompt = f"{existing_prompt}, {params_str}"
            else:
                new_prompt = params_str
            
            new_prompt = new_prompt.replace(", ,", ",").strip()
            self.prompt_text.setPlainText(new_prompt)
    
    def on_shot_selected(self, row):
        if row < 0 or not self.current_storyboard:
            return

        # combo 的 itemData 存的是 panel 索引，优先使用
        panel_idx = self.shot_combo.itemData(row)
        if panel_idx is None:
            panel_idx = row

        panels = self.current_storyboard.get("panels", [])
        if panel_idx >= len(panels):
            return

        self.current_panel_index = panel_idx
        panel = panels[panel_idx]
        
        # 优先从剧本文件读取最新的视频提示词
        video_prompt = self._get_video_prompt_from_script(panel)
        
        print(f"DEBUG: Panel {panel.get('panel_id')} video_prompt length: {len(video_prompt) if video_prompt else 0}")
        print(f"DEBUG: First 100 chars: {video_prompt[:100] if video_prompt else 'EMPTY'}")
        
        # 如果没有视频提示词，显示提示信息
        if not video_prompt:
            video_prompt = "【提示】请先前往剧本功能生成视频提示词，或在此处手动输入。"
        
        self.prompt_text.setPlainText(video_prompt)

        self.advanced_params = panel.get("advanced_params", {}).copy()

    def open_video_enhance_dialog(self):
        if not self.current_storyboard:
            QMessageBox.warning(self, "提示", "请先加载分镜数据")
            return
        
        if self.current_panel_index < 0:
            QMessageBox.warning(self, "提示", "请先选择一个分镜")
            return
        
        panels = self.current_storyboard.get("panels", [])
        if self.current_panel_index >= len(panels):
            QMessageBox.warning(self, "提示", "分镜索引无效")
            return
        
        panel = panels[self.current_panel_index]
        video_path = panel.get("video_path", "")
        
        if not video_path:
            QMessageBox.warning(self, "提示", "当前分镜没有视频文件，请先生成视频")
            return
        
        if not os.path.exists(video_path):
            QMessageBox.warning(self, "提示", f"视频文件不存在: {video_path}")
            return
        
        dialog = VideoEnhanceDialog(video_path, self)
        dialog.exec()

    def open_batch_video_dialog(self):
        print("DEBUG: open_batch_video_dialog called")
        try:
            if not self.current_storyboard:
                QMessageBox.warning(self, "提示", "请先加载分镜数据。")
                return
                
            print("DEBUG: Creating BatchVideoDialog...")
            dialog = BatchVideoDialog(self.current_storyboard, self.project_dir, self.current_panel_index, self)
            print("DEBUG: BatchVideoDialog created. Executing...")
            if dialog.exec():
                selected_ids = dialog.get_selected_panels()
                selected_config = dialog.get_selected_config()
                print(f"DEBUG: Dialog accepted. Selected {len(selected_ids)} panels. Config: {selected_config.get('name')}")
                if selected_ids:
                    self.run_batch_video_generation(selected_ids, selected_config)
        except Exception as e:
            print(f"ERROR in open_batch_video_dialog: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"操作失败: {str(e)}")

    def run_batch_video_generation(self, panel_ids, video_config=None):
        print(f"DEBUG: run_batch_video_generation called with {len(panel_ids)} panels")
        if not video_config:
            from core.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            configs = config_manager.get("api_configs", [])
            video_config = next((c for c in configs if c.get("type") == "Video"), None)
            
            if not video_config:
                print("DEBUG: No video config found, using mock")
                video_config = {"provider": "mock", "api_key": "sk-placeholder"}
            
        self.current_video_config = video_config
        print(f"DEBUG: Using video config: {video_config}")
            
        video_dir = os.path.join(self.project_dir, "clips")
        os.makedirs(video_dir, exist_ok=True)
        
        self.video_queue = []
        self.video_generation_results = {"success": [], "failed": []}  # 跟踪生成结果
        panels = self.current_storyboard.get("panels", [])
        for pid in panel_ids:
            panel = next((p for p in panels if p.get("panel_id") == pid), None)
            if not panel:
                continue
            # 分镜图片已下线：所有选中分镜都按参考图/纯提示词生成，不再要求存在分镜图片
            timestamp = int(time.time())
            output_path = os.path.join(video_dir, f"{panel.get('panel_id', 'unknown')}_{timestamp}.mp4")
            self.video_queue.append((panel, output_path))
                
        if self.video_queue:
            print(f"DEBUG: Queue populated with {len(self.video_queue)} items. Starting process.")
            self.process_video_queue()
        else:
            print("DEBUG: Queue empty (no panels selected)")
            QMessageBox.warning(self, "提示", "未选中分镜，无法生成视频。")

    def process_video_queue(self):
        try:
            if not self.video_queue:
                self.gen_video_btn.setText("🎥 生成视频")
                self.gen_video_btn.setEnabled(True)
                
                # 根据结果显示不同的提示
                success_count = len(self.video_generation_results["success"])
                failed_count = len(self.video_generation_results["failed"])
                
                if failed_count == 0:
                    # 全部成功
                    QMessageBox.information(self, "完成", f"所有视频生成完毕！\n\n成功: {success_count} 个\n\n生成的视频已自动添加到右侧素材库面板。")
                elif success_count == 0:
                    # 全部失败
                    QMessageBox.warning(self, "生成失败", f"所有视频生成失败！\n\n失败: {failed_count} 个\n\n请检查网络连接或API配置后重试。")
                else:
                    # 部分成功
                    failed_details = "\n".join([f"- {panel_id}" for panel_id in self.video_generation_results["failed"]])
                    QMessageBox.warning(self, "部分完成", f"视频生成部分完成！\n\n成功: {success_count} 个\n失败: {failed_count} 个\n\n失败的分镜:\n{failed_details}\n\n成功的视频已自动添加到右侧素材库面板。")
                
                self.save_storyboard()
                return
                
            panel, output_path = self.video_queue.pop(0)
            panel_id = panel.get("panel_id", "unknown")
            print(f"DEBUG: Processing panel {panel_id}")
            
            self.gen_video_btn.setText(f"生成中... 剩余 {len(self.video_queue) + 1}")
            self.gen_video_btn.setEnabled(False)
            
            text = panel.get("description", "")
            role_name = None
            if text and ":" in text:
                parts = text.split(":", 1)
                role_name = parts[0].strip()
                text = parts[1].strip()
            elif not text:
                text = ""
                
            voice_id = None 
            language = "English"
            
            char_id = None
            if panel.get("characters"):
                char_id = panel["characters"][0]
            
            resources_dir = os.path.dirname(os.path.dirname(self.project_dir))
            characters_dir = os.path.join(resources_dir, "characters")
            
            found_char = None
            
            if os.path.exists(characters_dir):
                from core.utils.entity_index import character_by_id, character_index
                if char_id:
                    found_char = character_by_id(characters_dir, char_id)
                    if found_char is None:
                        # 文件名匹配兜底：旧数据 id 可能只出现在文件名中
                        for f in os.listdir(characters_dir):
                            if f.endswith(".json") and char_id in f:
                                try:
                                    with open(os.path.join(characters_dir, f), 'r', encoding='utf-8') as cf:
                                        from core.character.character_model import Character
                                        found_char = Character.from_json(cf.read())
                                        break
                                except Exception:
                                    pass
                
                if not found_char and role_name:
                    found_char = character_index(characters_dir).get(role_name)
            
            if found_char:
                voice_id = found_char.voice_id
                if hasattr(found_char, 'language'):
                    language = found_char.language
                print(f"DEBUG: Found character {found_char.name}, Language: {language}, VoiceID: {voice_id}")
            
            ratio = "16:9"
            try:
                project_json_path = os.path.join(self.project_dir, "project.json")
                if os.path.exists(project_json_path):
                    with open(project_json_path, 'r', encoding='utf-8') as f:
                        project_data = json.load(f)
                        ratio = project_data.get("ratio", "16:9")
            except Exception: pass
            
            # 优先从剧本文件读取最新的视频提示词
            prompt = self._get_video_prompt_from_script(panel).strip()
            
            if not prompt:
                # 如果没有视频提示词，跳过此分镜，处理下一个
                self.status_label.setText(f"分镜 {panel.get('panel_id')} 没有视频提示词，跳过")
                print(f"DEBUG: Skipping panel {panel.get('panel_id')} - no video prompt")
                # 递归处理下一个
                self.process_video_queue()
                return
            
            # 添加配置后缀
            if self.current_video_config and self.current_video_config.get("prompt_suffix"):
                prompt += f"\n\n【附加提示】{self.current_video_config.get('prompt_suffix')}"
            
            print(f"DEBUG: Using Video Prompt from Script:\n{prompt[:500]}...")

            input_video_path = None
            if self.current_video_config and self.current_video_config.get("extend_video"):
                try:
                    panels = self.current_storyboard.get("panels", [])
                    current_idx = panels.index(panel)
                    if current_idx > 0:
                        prev_panel = panels[current_idx - 1]
                        if prev_panel.get("video_path") and os.path.exists(prev_panel["video_path"]):
                            input_video_path = prev_panel["video_path"]
                            print(f"DEBUG: Extending video from panel {prev_panel.get('panel_id')}")
                except ValueError:
                    pass

            # 参考图收集：与 AutoRun(改编) 共用 ref_collector 的同一套实现。
            # 旧实现在 panel 字典里找 "{char_id}_front_view" 这种拼接键，而 panel 里
            # 根本没有这些键 → 实际一张角色图都取不到（等于纯文生视频，人物一致性失效）。
            image_path = None
            ref_images = []
            ref_labels = []
            max_refs = 4
            include_sp = True
            try:
                vcfg = self.current_video_config or {}
                max_refs = max(1, int(vcfg.get("max_ref_images") or 4))
                include_sp = str(vcfg.get("ref_include_scene_prop", "true")).lower() not in ("false", "0", "no")
            except Exception:
                max_refs = 4
            panels_data = self.current_storyboard.get("panels", [])
            panel_obj = next((p for p in panels_data if p.get("panel_id") == panel_id), None)
            if panel_obj:
                try:
                    try:
                        from core.storyboard.ref_collector import collect_panel_ref_detail
                    except ImportError:
                        from src.core.storyboard.ref_collector import collect_panel_ref_detail
                    ref_detail = collect_panel_ref_detail(self.project_dir, panel_obj,
                                                          max_refs=max_refs,
                                                          include_scene_prop=include_sp)
                    ref_images = [d["path"] for d in ref_detail]
                    ref_labels = [d["label"] for d in ref_detail]
                except Exception as e:
                    print(f"DEBUG: ref collection failed: {e}")

            print(f"DEBUG: Using {len(ref_images)} reference images for video generation: {ref_labels}")
            
            # 获取分镜的时长（优先从视频提示词解析，其次从 Scene 数据），并收敛到 5-10 秒
            duration = 8  # 默认8秒
            try:
                # 方法1：从视频提示词里解析 "视频时长: X秒"
                import re
                duration_match = re.search(r'视频时长[：:]\s*(\d+)\s*秒', prompt)
                if duration_match:
                    duration = int(duration_match.group(1))
                    print(f"DEBUG: Parsed duration from prompt: {duration}s")
                else:
                    # 方法2：从 Scene 数据获取
                    panels = self.current_storyboard.get("panels", [])
                    panel_obj = next((p for p in panels if p.get("panel_id") == panel_id), None)
                    if panel_obj:
                        scene = self.find_scene_for_panel(panel_obj)
                        if scene:
                            duration = getattr(scene, 'duration_seconds', 8)
                            print(f"DEBUG: Scene duration for {panel_id}: {duration}s")
            except Exception as e:
                print(f"DEBUG: Error getting duration: {e}")
            try:
                from core.script.script_service import clamp_shot_duration
                duration = clamp_shot_duration(duration)
            except Exception:
                pass
            print(f"DEBUG: Resolved duration for {panel_id}: {duration}s")
            
            print(f"DEBUG: Starting thread for panel {panel_id}. Text: {text[:20] if text else 'N/A'}... Ratio: {ratio}, Duration: {duration}s")
            
            # 等待旧线程完全退出后再覆盖引用，避免 "QThread destroyed while running"
            old_thread = getattr(self, 'video_thread', None)
            if old_thread is not None and old_thread.isRunning():
                old_thread.wait(5000)
            if old_thread is not None:
                old_thread.deleteLater()
            
            self.video_thread = VideoGenThread(
                panel_id, 
                image_path, 
                prompt, 
                output_path, 
                self.current_video_config,
                text=text,
                voice_id=voice_id,
                ratio=ratio,
                language=language,
                input_video_path=input_video_path,
                duration=duration,
                ref_images=ref_images or None,
                ref_labels=ref_labels or None
            )
            self.video_thread.video_ready.connect(self.on_video_ready)
            self.video_thread.start()
            print("DEBUG: Thread started.")
        except Exception as e:
            print(f"ERROR in process_video_queue: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"处理队列失败: {str(e)}")
            self.gen_video_btn.setEnabled(True)
            self.gen_video_btn.setText("🎥 生成视频")
        
    def on_video_ready(self, panel_id, path, task_id=""):
        print(f"DEBUG: on_video_ready called for {panel_id}, path={path}")
        
        is_success = False
        
        if path and os.path.exists(path):
            file_size = os.path.getsize(path)
            print(f"DEBUG: Video file size: {file_size} bytes")
            if file_size < 1000:
                print(f"WARNING: Video file is too small ({file_size} bytes), likely failed.")
                QMessageBox.warning(self, "生成失败", "生成的视频文件过小，可能已损坏。")
                path = None
            else:
                is_success = True
        else:
            print(f"WARNING: Video file not found at {path}")
            path = None

        # 记录生成结果
        if is_success:
            self.video_generation_results["success"].append(panel_id)
        else:
            self.video_generation_results["failed"].append(panel_id)

        panels = self.current_storyboard.get("panels", [])
        panel = next((p for p in panels if p.get("panel_id") == panel_id), None)
        if panel:
            if path:
                if panel.get("video_path") and os.path.exists(panel["video_path"]) and panel["video_path"] not in panel.get("history_videos", []):
                    print(f"Saving previous video to history: {panel['video_path']}")
                    if "history_videos" not in panel:
                        panel["history_videos"] = []
                    panel["history_videos"].append(panel["video_path"])
                
                panel["video_path"] = os.path.abspath(path)
                panel["is_animated"] = True
                
                # 发出信号将视频添加到素材库
                self.add_to_library.emit(os.path.abspath(path))
                
                try:
                    idx = panels.index(panel)
                    if idx == self.current_panel_index:
                        self.on_shot_selected(idx)
                        
                except Exception as e:
                    print(f"Error updating UI thumbnail: {e}")
        else:
            print(f"Video generation failed for panel {panel_id}")
            
        self.process_video_queue()

    def save_changes(self):
        if not self.current_storyboard or not self.project_dir:
            return
        
        panels = self.current_storyboard.get("panels", [])
        current_row = self.shot_combo.currentIndex()
        if current_row >= 0 and current_row < len(panels):
            panel = panels[current_row]
            panel["video_prompt"] = self.prompt_text.toPlainText()
            panel["advanced_params"] = self.advanced_params.copy()
            
            # 尝试解析分段信息
            from core.storyboard.prompt_factory import parse_video_prompt_to_segments
            segments = parse_video_prompt_to_segments(
                panel["video_prompt"], 
                panel.get("duration", 10.0)
            )
            if segments:
                panel["video_prompt_segments"] = [seg.to_dict() for seg in segments]
        
        self.save_storyboard()
        QMessageBox.information(self, "成功", "保存成功")
    
    def save_storyboard(self):
        if not self.current_storyboard or not self.project_dir or not self.current_episode_id:
            return
        
        storyboard_path = os.path.join(self.project_dir, "storyboards", f"episode_{self.current_episode_id}.json")
        os.makedirs(os.path.dirname(storyboard_path), exist_ok=True)

        # 原子写入，避免写一半损坏分镜文件
        atomic_write_json(storyboard_path, self.current_storyboard)


