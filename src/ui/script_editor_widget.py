from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QTextEdit, QPushButton, QFrame, 
                             QScrollArea, QGroupBox, QMenu, QScrollBar, QApplication, QDialog, QTabWidget)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QClipboard, QFont
from core.script.script_model import Script, Scene
from core.storyboard.storyboard_model import VideoPromptSegment
from core.storyboard.prompt_factory import (
    parse_video_prompt_to_segments, format_segments_to_video_prompt,
    generate_default_video_segments, construct_video_prompt
)
from ui.video_prompt_editor import VideoPromptEditorDialog
from ui import theme as _theme


class PromptEditWidget(QFrame):
    """可编辑的提示词组件"""
    text_changed = pyqtSignal(str)
    
    def __init__(self, prompt: str = "", title: str = "提示词", color: str = "" + _theme.color("warning") + "", read_only=False, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.title = title
        self.color = color
        self.read_only = read_only
        self.init_ui()
    
    def init_ui(self):
        self.setStyleSheet(f"""
            PromptEditWidget {{
                background-color: {_theme.color("panel2")};
                border: 1px solid {self.color};
                border-radius: 6px;
                margin: 2px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        
        header = QHBoxLayout()
        title_lbl = QLabel(self.title)
        title_lbl.setStyleSheet(f"color: {self.color}; font-weight: bold; font-size: 12px; background: transparent;")
        header.addWidget(title_lbl)
        header.addStretch()
        
        if self.read_only:
            copy_btn = QPushButton("📋 复制")
            copy_btn.setFixedSize(60, 22)
            copy_btn.setStyleSheet("""
                QPushButton { background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text_sub") + """; border: none; border-radius: 3px; font-size: 10px; }
                QPushButton:hover { background-color: """ + _theme.color("panel2") + """; }
            """)
            copy_btn.clicked.connect(self._copy)
            header.addWidget(copy_btn)
        else:
            save_btn = QPushButton("💾 保存")
            save_btn.setFixedSize(60, 22)
            save_btn.setStyleSheet("""
                QPushButton { background-color: """ + _theme.color("success") + """; color: """ + _theme.color("text") + """; border: none; border-radius: 3px; font-size: 10px; }
                QPushButton:hover { background-color: """ + _theme.color("accent_strong") + """; }
            """)
            save_btn.clicked.connect(self._save)
            header.addWidget(save_btn)
        
        layout.addLayout(header)
        
        self.editor = QTextEdit()
        self.editor.setReadOnly(self.read_only)
        self.editor.setPlainText(self.prompt)
        self.editor.setStyleSheet(f"""
            QTextEdit {{
                background-color: {_theme.color("bg")};
                color: {self.color};
                border: none;
                border-radius: 4px;
                padding: 8px;
                font-size: 11px;
                line-height: 1.5;
            }}
        """)
        self.editor.setMinimumHeight(80)
        if not self.read_only:
            self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor)
    
    def set_prompt(self, prompt: str):
        self.prompt = prompt
        self.editor.setPlainText(prompt)
    
    def get_prompt(self) -> str:
        return self.editor.toPlainText()
    
    def _on_text_changed(self):
        self.prompt = self.editor.toPlainText()
        self.text_changed.emit(self.prompt)
    
    def _copy(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.prompt)
    
    def _save(self):
        self.prompt = self.editor.toPlainText()
        self.text_changed.emit(self.prompt)


class ShotPromptWidget(QFrame):
    """分镜提示词组件 - 支持编辑"""
    deleted = pyqtSignal(int)
    prompt_updated = pyqtSignal(int, str)  # index, video_prompt
    
    def __init__(self, index, scene: Scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.index = index
        # 注意：自动生成提示词的逻辑移到 ScriptEditorWidget.load_script 中
        # 以确保信号连接后再执行
        self.init_ui()
    
    def _ensure_video_prompt(self):
        """确保视频提示词正常，优先保留已有对白"""
        existing_prompt = getattr(self.scene, 'video_prompt', '')
        existing_dialogue = getattr(self.scene, 'dialogue', '')
        
        # 如有对白字段为空，但旧 prompt 中有对白，则提取
        if not existing_dialogue and existing_prompt:
            import re
            m = re.search(r'- 对白[：:]\s*(.+?)(?:\n|$)', existing_prompt)
            if m:
                dialogue_text = m.group(1).strip()
                if dialogue_text and dialogue_text != '（无）':
                    setattr(self.scene, 'dialogue', dialogue_text)
        
        # 只在无 prompt 或 prompt 有已知乱码时才重新生成
        needs_regen = False
        if not existing_prompt:
            needs_regen = True
        else:
            garbled = ['氛围氛围', '风格风格', '场景位于位于', '正在在']
            if any(g in existing_prompt for g in garbled):
                needs_regen = True
        
        if needs_regen:
            self._auto_generate_video_prompt()
            self.prompt_updated.emit(self.index, self.scene.video_prompt)
    
    def _auto_generate_video_prompt(self):
        """自动生成完整格式的视频提示词"""
        from core.storyboard.prompt_factory import construct_video_prompt
        
        # ==================== 提取所有关键信息 ====================
        
        # 1. 基础信息
        scene_location = getattr(self.scene, 'scene_location', '')
        time_of_day = getattr(self.scene, 'time', 'Day')
        weather = getattr(self.scene, 'weather', 'Clear')
        atmosphere = getattr(self.scene, 'atmosphere', '')
        style = getattr(self.scene, 'style', '电影感')
        
        # 2. 镜头信息
        shot_type = getattr(self.scene, 'shot_type', '中景')
        camera_movement = getattr(self.scene, 'camera_movement', '固定')
        duration = getattr(self.scene, 'duration_seconds', 8.0)
        
        # 3. 角色和动作信息
        characters = getattr(self.scene, 'characters', '')
        action = getattr(self.scene, 'action', '')
        props = getattr(self.scene, 'props', '')
        
        # 4. 对白信息
        dialogue_text = getattr(self.scene, 'dialogue', '')
        dialogue_role = ''
        
        # 尝试从dialogue_list获取更详细的对白信息
        if hasattr(self.scene, 'dialogue_list') and self.scene.dialogue_list:
            primary_dialogue = self.scene.dialogue_list[0]
            dialogue_text = primary_dialogue.content
            dialogue_role = primary_dialogue.role
            if primary_dialogue.action and not action:
                action = primary_dialogue.action
        elif dialogue_text and ':' in dialogue_text:
            parts = dialogue_text.split(':', 1)
            dialogue_role = parts[0].strip()
            dialogue_text = parts[1].strip() if len(parts) > 1 else ''
        
        # ==================== 构建详细描述 ====================
        
        # 构建画面主体描述（必须包含角色和动作）
        subject_parts = []
        if characters:
            subject_parts.append(characters)
        if action:
            subject_parts.append(action)
        subject_desc = "，".join(subject_parts) if subject_parts else "场景主体"
        
        # 构建完整场景描述（【画面描述】部分）
        scene_desc_parts = []
        
        # 角色和动作（核心信息）
        if characters:
            scene_desc_parts.append(f"{characters}")
        if action:
            scene_desc_parts.append(f"{action}")
        
        # 场景环境
        if scene_location:
            scene_desc_parts.append(scene_location)
        
        # 道具
        if props:
            scene_desc_parts.append(props)
        
        # 时间和天气
        if time_of_day:
            scene_desc_parts.append(f"{time_of_day}")
        if weather and weather != 'Clear':
            scene_desc_parts.append(f"{weather}")
        
        # 氛围
        if atmosphere:
            scene_desc_parts.append(atmosphere)
        
        # 视觉风格
        if style:
            scene_desc_parts.append(style)
        
        scene_description = "，".join(scene_desc_parts) if scene_desc_parts else "展现场景动作和氛围"
        
        # ==================== 构建分镜时间轴 ====================
        
        # 根据时长创建分段
        segments = []
        
        # 第一段：开场，建立视觉焦点
        seg1_end = min(2, duration)
        seg1_desc = f"镜头缓缓推近，展现{subject_desc}的整体姿态"
        if scene_location:
            seg1_desc += f"和{scene_location}环境"
        seg1_desc += "，建立视觉焦点"
        if atmosphere:
            seg1_desc += f"，营造{atmosphere}氛围"
        
        segments.append({
            'start_time': 0,
            'end_time': seg1_end,
            'description': seg1_desc
        })
        
        # 第二段：主体动作和表情（如果有对白，放在这里）
        if duration > 2:
            seg2_start = seg1_end
            seg2_end = min(4, duration)
            seg2_desc = f"镜头保持稳定，特写{subject_desc}"
            if action:
                seg2_desc += f"的{action}动作"
            seg2_desc += "细节"
            if atmosphere:
                seg2_desc += f"，呈现{atmosphere}情绪高潮"
            
            segments.append({
                'start_time': seg2_start,
                'end_time': seg2_end,
                'description': seg2_desc
            })
        
        # 第三段：收尾和过渡
        if duration > 4:
            seg3_start = 4
            seg3_desc = f"镜头轻微运动，"
            if action:
                seg3_desc += f"{action}动作收尾"
            else:
                seg3_desc += "保持画面生动性"
            seg3_desc += "，自然过渡到下一场景"
            
            segments.append({
                'start_time': seg3_start,
                'end_time': duration,
                'description': seg3_desc
            })
        
        # ==================== 准备参数 ====================
        
        # 视频参数
        video_params = {
            'duration': duration,
            'dialogue': dialogue_text,
            'dialogue_role': dialogue_role,
            'camera_movement': camera_movement,
            'shot_type': shot_type,
            'viewpoint': shot_type,
            'audio': f"背景音乐{atmosphere if atmosphere else '根据场景氛围匹配'}，{weather if weather else '环境音'}",
            'segments': segments,
            'scene_description': scene_description,
            'characters': characters
        }
        
        # ==================== 生成视频提示词 ====================
        
        new_video_prompt = construct_video_prompt(
            video_params=video_params,
            dialogue_text=dialogue_text,
            dialogue_role=dialogue_role,
            duration=duration
        )
        
        # ==================== 更新Scene ====================
        
        self.scene.video_prompt = new_video_prompt
        self.scene.duration_seconds = duration
        
        # 更新UI显示
        self.video_editor.setPlainText(new_video_prompt)
        self.duration_lbl.setText(f"时长: {duration}秒")
        
        # 更新分段数据（从生成的提示词解析，保证与提示词时间轴一致）
        self.scene.video_prompt_segments = parse_video_prompt_to_segments(new_video_prompt, duration) or []
    
    def init_ui(self):
        self.setStyleSheet("""
            ShotPromptWidget {
                background-color: """ + _theme.color("bg") + """;
                border-radius: 8px;
                margin: 5px;
                border: 1px solid """ + _theme.color("hover") + """;
            }
            QLabel { color: """ + _theme.color("text_sub") + """; }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # Header
        header = QHBoxLayout()
        
        shot_lbl = QLabel(f"分镜 {self.scene.shot_id}")
        shot_lbl.setStyleSheet("color: " + _theme.color("success") + "; font-weight: bold; font-size: 14px;")
        header.addWidget(shot_lbl)
        
        self.duration_lbl = QLabel(f"时长: {self.scene.duration_seconds}秒")
        self.duration_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        header.addWidget(self.duration_lbl)
        
        header.addStretch()
        
        del_btn = QPushButton("删除")
        # 宽度需容纳「删除」两个中文字，否则文字会被截断
        del_btn.setFixedSize(76, 28)
        del_btn.setStyleSheet("""
            QPushButton { background-color: """ + _theme.color("danger") + """; color: """ + _theme.color("accent_text") + """; border: none; border-radius: 4px; padding: 0px; font-size: 12px; }
            QPushButton:hover { background-color: """ + _theme.color("danger") + """; }
        """)
        del_btn.clicked.connect(lambda: self.deleted.emit(self.index))
        header.addWidget(del_btn)
        
        main_layout.addLayout(header)
        
        # 提示词以选项卡形式显示（视频提示词）
        self.prompt_tabs = QTabWidget()
        self.prompt_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid """ + _theme.color("hover") + """; border-radius: 4px; background-color: """ + _theme.color("bg") + """; top: -1px; }
            QTabBar::tab { background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text_sub") + """; padding: 6px 16px; border-radius: 4px; margin-right: 2px; font-size: 12px; }
            QTabBar::tab:selected { background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """; font-weight: bold; }
            QTabBar::tab:hover { background-color: """ + _theme.color("panel2") + """; }
        """)

        # ========== 选项卡：视频提示词 ==========
        video_tab = QWidget()
        video_container = QVBoxLayout(video_tab)
        video_container.setContentsMargins(10, 10, 10, 10)
        video_container.setSpacing(6)

        # 标签页标题已标明名称，这里不再重复「视频提示词」文案，只保留保存按钮
        video_header = QHBoxLayout()
        video_header.addStretch()

        # 保存按钮
        video_save_btn = QPushButton("💾 保存")
        video_save_btn.setFixedSize(60, 22)
        video_save_btn.setStyleSheet("""
            QPushButton { background-color: """ + _theme.color("success") + """; color: """ + _theme.color("text") + """; border: none; border-radius: 3px; font-size: 10px; }
            QPushButton:hover { background-color: """ + _theme.color("accent_strong") + """; }
        """)
        video_save_btn.clicked.connect(self._save_video_prompt)
        video_header.addWidget(video_save_btn)

        video_container.addLayout(video_header)

        # 视频提示词编辑器
        self.video_editor = QTextEdit()
        self.video_editor.setPlainText(self.scene.video_prompt)
        self.video_editor.setStyleSheet("""
            QTextEdit {
                background-color: """ + _theme.color("bg") + """;
                color: """ + _theme.color("accent") + """;
                border: 1px solid """ + _theme.color("accent") + """;
                border-radius: 4px;
                padding: 8px;
                font-size: 11px;
                line-height: 1.5;
            }
        """)
        self.video_editor.setMinimumHeight(220)
        video_container.addWidget(self.video_editor)

        # 分段预览标签
        self.segment_preview = QLabel("")
        self.segment_preview.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 10px;")
        video_container.addWidget(self.segment_preview)

        self.prompt_tabs.addTab(video_tab, "🎬 视频提示词")

        main_layout.addWidget(self.prompt_tabs)

        self._update_segment_preview()
    
    def _save_video_prompt(self):
        """保存视频提示词"""
        self.scene.video_prompt = self.video_editor.toPlainText()
        # 尝试解析分段信息
        segments = parse_video_prompt_to_segments(self.scene.video_prompt, self.scene.duration_seconds)
        if segments:
            self.scene.video_prompt_segments = segments
        self.prompt_updated.emit(self.index, self.scene.video_prompt)
        self._update_segment_preview()
    
    def _regenerate_video_prompt(self):
        """重新生成新格式的视频提示词，包含剧本所有关键信息"""
        from core.storyboard.prompt_factory import construct_video_prompt
        
        # ==================== 提取所有关键信息 ====================
        
        # 1. 基础信息
        shot_id = getattr(self.scene, 'shot_id', '1-1')
        scene_location = getattr(self.scene, 'scene_location', '')
        time_of_day = getattr(self.scene, 'time', 'Day')
        weather = getattr(self.scene, 'weather', 'Clear')
        atmosphere = getattr(self.scene, 'atmosphere', '')
        style = getattr(self.scene, 'style', '电影感')
        
        # 2. 镜头信息
        shot_type = getattr(self.scene, 'shot_type', '中景')
        camera_movement = getattr(self.scene, 'camera_movement', '固定')
        duration = getattr(self.scene, 'duration_seconds', 8.0)
        
        # 3. 角色和动作信息
        characters = getattr(self.scene, 'characters', '')
        action = getattr(self.scene, 'action', '')
        props = getattr(self.scene, 'props', '')
        
        # 4. 对白信息
        dialogue_text = getattr(self.scene, 'dialogue', '')
        dialogue_role = ''
        
        # 尝试从dialogue_list获取更详细的对白信息
        if hasattr(self.scene, 'dialogue_list') and self.scene.dialogue_list:
            primary_dialogue = self.scene.dialogue_list[0]
            dialogue_text = primary_dialogue.content
            dialogue_role = primary_dialogue.role
            # 如果对白中有动作描述，补充到action中
            if primary_dialogue.action and not action:
                action = primary_dialogue.action
        elif dialogue_text and ':' in dialogue_text:
            # 尝试从dialogue字段解析
            parts = dialogue_text.split(':', 1)
            dialogue_role = parts[0].strip()
            dialogue_text = parts[1].strip() if len(parts) > 1 else ''
        
        # ==================== 构建详细描述 ====================
        
        # 构建画面主体描述（必须包含角色和动作）
        subject_parts = []
        if characters:
            subject_parts.append(characters)
        if action:
            subject_parts.append(f"正在{action}")
        subject_desc = "，".join(subject_parts) if subject_parts else "场景主体"
        
        # 构建完整场景描述（【画面描述】部分）
        scene_desc_parts = []
        
        # 角色和动作（核心信息）
        if characters:
            scene_desc_parts.append(f"{characters}")
        if action:
            scene_desc_parts.append(f"{action}")
        
        # 场景环境
        if scene_location:
            scene_desc_parts.append(f"场景位于{scene_location}")
        
        # 道具
        if props:
            scene_desc_parts.append(f"使用道具：{props}")
        
        # 时间和天气
        if time_of_day:
            scene_desc_parts.append(f"{time_of_day}")
        if weather and weather != 'Clear':
            scene_desc_parts.append(f"{weather}天气")
        
        # 氛围
        if atmosphere:
            scene_desc_parts.append(f"氛围{atmosphere}")
        
        # 视觉风格
        if style:
            scene_desc_parts.append(f"{style}风格")
        
        scene_description = "，".join(scene_desc_parts) if scene_desc_parts else "展现场景动作和氛围"
        
        # ==================== 构建分镜时间轴 ====================
        
        # 根据时长创建分段
        segments = []
        
        # 第一段：开场，建立视觉焦点
        seg1_end = min(2, duration)
        seg1_desc = f"镜头缓缓推近，展现{subject_desc}的整体姿态"
        if scene_location:
            seg1_desc += f"和{scene_location}环境"
        seg1_desc += "，建立视觉焦点"
        if atmosphere:
            seg1_desc += f"，营造{atmosphere}氛围"
        
        segments.append({
            'start_time': 0,
            'end_time': seg1_end,
            'description': seg1_desc
        })
        
        # 第二段：主体动作和表情（如果有对白，放在这里）
        if duration > 2:
            seg2_start = seg1_end
            seg2_end = min(4, duration)
            seg2_desc = f"镜头保持稳定，特写{subject_desc}"
            if action:
                seg2_desc += f"的{action}动作"
            seg2_desc += "细节"
            if atmosphere:
                seg2_desc += f"，呈现{atmosphere}情绪高潮"
            
            segments.append({
                'start_time': seg2_start,
                'end_time': seg2_end,
                'description': seg2_desc
            })
        
        # 第三段：收尾和过渡
        if duration > 4:
            seg3_start = 4
            seg3_desc = f"镜头轻微运动，"
            if action:
                seg3_desc += f"{action}动作收尾"
            else:
                seg3_desc += "保持画面生动性"
            seg3_desc += "，自然过渡到下一场景"
            
            segments.append({
                'start_time': seg3_start,
                'end_time': duration,
                'description': seg3_desc
            })
        
        # ==================== 准备参数 ====================
        
        # 视频参数
        video_params = {
            'duration': duration,
            'dialogue': dialogue_text,
            'dialogue_role': dialogue_role,
            'camera_movement': camera_movement,
            'shot_type': shot_type,
            'viewpoint': shot_type,
            'audio': f"背景音乐{atmosphere if atmosphere else '根据场景氛围匹配'}，{weather if weather else '环境音'}",
            'segments': segments,
            'scene_description': scene_description,
            'characters': characters
        }
        
        # ==================== 生成视频提示词 ====================
        
        new_video_prompt = construct_video_prompt(
            video_params=video_params,
            dialogue_text=dialogue_text,
            dialogue_role=dialogue_role,
            duration=duration
        )
        
        # ==================== 更新Scene ====================
        
        self.scene.video_prompt = new_video_prompt
        self.scene.duration_seconds = duration
        
        # 更新分段数据（从生成的提示词解析，保证与提示词时间轴一致）
        self.scene.video_prompt_segments = parse_video_prompt_to_segments(new_video_prompt, duration) or []
        
        # 更新UI
        self.video_editor.setPlainText(new_video_prompt)
        self._update_segment_preview()
        self.prompt_updated.emit(self.index, self.scene.video_prompt)
    
    def _open_video_segment_editor(self):
        """打开视频分段编辑器"""
        # 获取或创建分段数据
        if not hasattr(self.scene, 'video_prompt_segments') or not self.scene.video_prompt_segments:
            if self.scene.video_prompt:
                self.scene.video_prompt_segments = parse_video_prompt_to_segments(
                    self.scene.video_prompt, 
                    self.scene.duration_seconds
                )
            else:
                self.scene.video_prompt_segments = generate_default_video_segments(self.scene.duration_seconds)
        
        dialog = VideoPromptEditorDialog(
            self.scene.video_prompt_segments,
            self.scene.duration_seconds,
            self
        )
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.scene.video_prompt_segments = dialog.get_segments()
            self.scene.duration_seconds = dialog.get_duration()
            # 更新文本格式
            self.scene.video_prompt = format_segments_to_video_prompt(self.scene.video_prompt_segments)
            self.video_editor.setPlainText(self.scene.video_prompt)
            self._update_segment_preview()
            self.prompt_updated.emit(self.index, self.scene.video_prompt)
    
    def _update_segment_preview(self):
        """更新分段预览"""
        if hasattr(self.scene, 'video_prompt_segments') and self.scene.video_prompt_segments:
            count = len(self.scene.video_prompt_segments)
            self.segment_preview.setText(f"📋 已设置 {count} 个时间段 | 总时长: {self.scene.duration_seconds}秒")
        else:
            self.segment_preview.setText("")
    
    def update_prompts(self):
        """更新显示的提示词"""
        self.video_editor.setPlainText(self.scene.video_prompt)
        self._update_segment_preview()


class ScriptEditorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_script = None
        self.current_script_path = None
        self.project_dir = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部信息条容器（标题 + 类型/分镜数）
        self.header_widget = QWidget()
        self.header_widget.setStyleSheet("background-color: " + _theme.color("panel") + ";")
        self.header_layout = QVBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(20, 12, 20, 8)
        self.header_layout.setSpacing(6)
        layout.addWidget(self.header_widget)

        # 选项卡：每个分镜一个选项卡
        self.shot_tabs = QTabWidget()
        self.shot_tabs.setMovable(True)
        self.shot_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: """ + _theme.color("panel") + """; }
            QTabBar::tab { background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text_sub") + """; padding: 8px 16px; border-radius: 4px; margin-right: 2px; font-size: 12px; }
            QTabBar::tab:selected { background-color: """ + _theme.color("accent2") + """; color: """ + _theme.color("text") + """; font-weight: bold; }
            QTabBar::tab:hover { background-color: """ + _theme.color("panel2") + """; }
        """)
        layout.addWidget(self.shot_tabs)

    def load_script(self, script: Script, title_info=""):
        self.current_script = script

        # 清空顶部信息条
        while self.header_layout.count():
            item = self.header_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 清空原有选项卡
        while self.shot_tabs.count():
            w = self.shot_tabs.widget(0)
            self.shot_tabs.removeTab(0)
            if w:
                w.deleteLater()

        if not script:
            return

        if title_info:
            title_lbl = QLabel(title_info)
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_lbl.setStyleSheet("color: " + _theme.color("text") + "; font-size: 22px; font-weight: bold;")
            self.header_layout.addWidget(title_lbl)

        info_bar = QHBoxLayout()
        type_lbl = QLabel(f"类型: {script.genre}")
        type_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        info_bar.addWidget(type_lbl)
        count_lbl = QLabel(f" | 分镜数: {len(script.scenes)}")
        count_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        info_bar.addWidget(count_lbl)
        info_bar.addStretch()
        self.header_layout.addLayout(info_bar)

        for i, scene in enumerate(script.scenes):
            shot_widget = ShotPromptWidget(i + 1, scene)
            shot_widget.deleted.connect(self.remove_shot)
            shot_widget.prompt_updated.connect(self._on_prompt_updated)
            # 选项卡标题使用分镜号（如 1-1）
            self.shot_tabs.addTab(shot_widget, scene.shot_id)

            # 在信号连接后，检查并自动生成提示词
            shot_widget._ensure_video_prompt()

        # 默认选中第一个分镜
        if self.shot_tabs.count() > 0:
            self.shot_tabs.setCurrentIndex(0)
    
    def _on_prompt_updated(self, index, video_prompt):
        """处理提示词更新"""
        if self.current_script and 0 <= index - 1 < len(self.current_script.scenes):
            scene = self.current_script.scenes[index - 1]
            scene.video_prompt = video_prompt
            print(f"DEBUG: Updated prompts for shot {scene.shot_id}")
            
            # 保存剧本到文件
            self._save_script_to_file()

    def _save_script_to_file(self):
        """保存剧本到文件"""
        if not self.current_script or not self.project_dir:
            print("DEBUG: Cannot save script - no script or project_dir")
            return
        
        try:
            import os
            
            # 使用当前剧本路径保存（如已加载自文件）
            if self.current_script_path:
                script_path = self.current_script_path
            else:
                # 确保 scripts 目录存在
                scripts_dir = os.path.join(self.project_dir, "scripts")
                os.makedirs(scripts_dir, exist_ok=True)
                # 默认第一集
                script_path = os.path.join(scripts_dir, "episode_1.json")
            
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(self.current_script.to_json())
            
            print(f"DEBUG: Saved script to {script_path}")
            
        except Exception as e:
            print(f"DEBUG: Failed to save script: {e}")
            import traceback
            traceback.print_exc()

    def remove_shot(self, index):
        if self.current_script and 0 <= index - 1 < len(self.current_script.scenes):
            self.current_script.scenes.pop(index - 1)
            self.load_script(self.current_script, "")
