from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QTextEdit, QPushButton, QSplitter, 
                             QProgressBar, QMessageBox, QTabWidget, QComboBox,
                             QRadioButton, QButtonGroup, QListWidget, QListWidgetItem,
                             QStackedWidget, QFrame, QInputDialog, QGroupBox, QFormLayout,
                             QDialog, QDialogButtonBox, QTextBrowser)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QIcon
import json
import os
import uuid
from core.script.script_model import Script
from core.character.character_model import Character
from core.prop.prop_model import Prop
from core.scene.scene_model import Scene
from core.script import script_service
from core.config.config_manager import ConfigManager
from core.project.series_manager import SeriesManager
from ui.script_editor_widget import ScriptEditorWidget
from ui import theme as _theme

try:
    from core.template.template_library import TemplateLibrary
except ImportError:
    from src.core.template.template_library import TemplateLibrary


def _is_cancelled():
    """全局协作取消状态（项目页点过「停止」）：线程静默退出，不弹错误框。"""
    try:
        from ai_engine.utils.cancel import cancelled as _c
    except ImportError:
        try:
            from src.ai_engine.utils.cancel import cancelled as _c
        except ImportError:
            return False
    try:
        return bool(_c())
    except Exception:
        return False


def _reset_cancel():
    """开始新的生成任务前清除全局取消标记，避免上一轮「停止」让新任务秒退。"""
    try:
        from ai_engine.utils.cancel import reset as _r
    except ImportError:
        try:
            from src.ai_engine.utils.cancel import reset as _r
        except ImportError:
            return
    try:
        _r()
    except Exception:
        pass

class ScriptGeneratorThread(QThread):
    finished = pyqtSignal(dict)  # Changed to emit dict with all data
    error = pyqtSignal(str)

    def __init__(self, prompt, api_config, duration, style, context_data=None, project_dir=None, language="zh"):
        super().__init__()
        self.prompt = prompt
        self.api_config = api_config or {}
        self.duration = duration
        self.style = style
        self.context_data = context_data or {}
        self.project_dir = project_dir
        self.language = language

    def run(self):
        try:
            # 剧本生成逻辑已提取到 core.script.script_service，UI 线程仅做信号包装
            data = script_service.generate_script_data(
                prompt=self.prompt,
                api_config=self.api_config,
                duration=self.duration,
                style=self.style,
                context_data=self.context_data,
                language=self.language
            )
            self.finished.emit(data)
        except Exception as e:
            if _is_cancelled():
                return   # 终止导致的异常（连接被断开等）静默处理
            self.error.emit(str(e))

class ScriptWindow(QWidget):
    def __init__(self, project_dir):
        super().__init__()
        self.project_dir = project_dir
        self.current_script = None
        self.current_episode_id = None # Track which episode is being edited
        self.series_manager = None
        self.config_manager = ConfigManager()
        self.init_ui()
        self.check_project_status()

    def check_project_status(self):
        if self.project_dir and os.path.exists(os.path.join(self.project_dir, "project.json")):
            project_name = os.path.basename(self.project_dir)
            self.project_label.setText(f"当前项目: {project_name}")
            self.project_label.setStyleSheet("color: " + _theme.color("success") + "; font-weight: bold;")
            
            # Initialize Series Manager
            self.series_manager = SeriesManager(self.project_dir)
            self.refresh_episode_list()
            
        else:
            self.project_label.setText("未选择项目 (请先在项目管理中加载)")
            self.project_label.setStyleSheet("color: " + _theme.color("danger") + "; font-weight: bold;")

    def set_project_dir(self, path):
        if not path:
            return
        self.project_dir = path
        self.check_project_status()
        self.load_existing_script()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Left Sidebar ---
        left_sidebar = QFrame()
        left_sidebar.setObjectName("SideBar")
        left_sidebar.setFixedWidth(280) # Widened for episode list
        left_layout = QVBoxLayout(left_sidebar)
        left_layout.setContentsMargins(15, 20, 15, 20)
        left_layout.setSpacing(15)

        # Project Info
        self.project_label = QLabel("检测中...")
        self.project_label.setWordWrap(True)
        left_layout.addWidget(self.project_label)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: " + _theme.color("panel2") + ";")
        left_layout.addWidget(line)

        # Video Ratio
        left_layout.addWidget(QLabel("视频比例"))
        ratio_layout = QHBoxLayout()
        self.ratio_h = QRadioButton("横屏 16:9")
        self.ratio_v = QRadioButton("竖屏 9:16")
        self.ratio_h.setChecked(True)

        ratio_group = QButtonGroup(self)
        ratio_group.addButton(self.ratio_h)
        ratio_group.addButton(self.ratio_v)

        ratio_layout.addWidget(self.ratio_h)
        ratio_layout.addWidget(self.ratio_v)
        left_layout.addLayout(ratio_layout)

        self.ratio_h.toggled.connect(self.save_project_settings)
        self.ratio_v.toggled.connect(self.save_project_settings)

        # Video Resolution
        left_layout.addWidget(QLabel("视频分辨率"))
        res_layout = QHBoxLayout()
        self.res_1080 = QRadioButton("1080P")
        self.res_720 = QRadioButton("720P")
        self.res_1080.setChecked(True)

        res_group = QButtonGroup(self)
        res_group.addButton(self.res_1080)
        res_group.addButton(self.res_720)

        res_layout.addWidget(self.res_1080)
        res_layout.addWidget(self.res_720)
        left_layout.addLayout(res_layout)

        self.res_1080.toggled.connect(self.save_project_settings)
        self.res_720.toggled.connect(self.save_project_settings)

        # --- Series Management ---
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        left_layout.addWidget(line2)
        
        left_layout.addWidget(QLabel("剧集列表 (Series)"))
        
        # Episode List
        self.episode_list = QListWidget()
        self.episode_list.setStyleSheet("""
            QListWidget { background-color: """ + _theme.color("panel2") + """; border: none; color: """ + _theme.color("text") + """; }
            QListWidget::item { padding: 8px; border-bottom: 1px solid """ + _theme.color("panel") + """; }
            QListWidget::item:selected { background-color: """ + _theme.color("accent2") + """; }
        """)
        self.episode_list.itemClicked.connect(self.on_episode_selected)
        left_layout.addWidget(self.episode_list)
        
        # Removed "New Series" and "Set Outline" buttons as requested

        # Removed "LLM Model Config" as requested

        # Project Info Box
        info_box = QGroupBox("项目信息")
        info_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid """ + _theme.color("panel2") + """;
                border-radius: 5px;
                margin-top: 10px;
                color: """ + _theme.color("text_sub") + """;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
            }
            QLabel {
                color: """ + _theme.color("text") + """;
                font-size: 12px;
            }
        """)
        info_layout = QFormLayout(info_box)
        info_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        info_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        self.info_type = QLabel("AI短剧")
        self.info_genre = QLabel("未设置")
        self.info_visual_style = QLabel("未设置")
        self.info_visual_style.setWordWrap(True)
        self.info_count = QLabel("0 集")
        
        info_layout.addRow("创作类型:", self.info_type)
        info_layout.addRow("故事类型:", self.info_genre)
        info_layout.addRow("画面风格:", self.info_visual_style)
        info_layout.addRow("总集数:", self.info_count)
        
        left_layout.addWidget(info_box)
        
        left_layout.addStretch() # Push everything up

        main_layout.addWidget(left_sidebar)

        # --- Right Content Area ---
        right_content = QWidget()
        right_layout = QVBoxLayout(right_content)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Header (Title Bar)
        header = QFrame()
        header.setObjectName("TopBar")
        header.setFixedHeight(50)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)

        header_title = QLabel("剧本编辑")
        header_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(header_title)
        header_layout.addStretch()

        # 「从模板创建」入口已移除：模板功能统一在首页创作卡使用。
        # _create_from_template 方法保留，供内部调用。

        right_layout.addWidget(header)

        # Script Editor
        self.script_editor = ScriptEditorWidget()
        right_layout.addWidget(self.script_editor)
        
        # Bottom Bar with Save Button
        bottom_bar = QFrame()
        bottom_bar.setObjectName("BottomBar")
        bottom_bar.setFixedHeight(60)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(20, 10, 20, 10)
        
        bottom_layout.addStretch()
        
        save_btn = QPushButton("保存本集")
        save_btn.setFixedSize(120, 40)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("success") + """; color: """ + _theme.color("text") + """;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("success") + """;
            }
            QPushButton:pressed {
                background-color: """ + _theme.color("accent_strong") + """;
            }
        """)
        save_btn.clicked.connect(self.save_script)
        bottom_layout.addWidget(save_btn)
        
        right_layout.addWidget(bottom_bar)

        main_layout.addWidget(right_content)

    def refresh_api_list(self):
        from ui.utils import populate_api_combo
        populate_api_combo(self.api_combo, self.config_manager, "LLM", "未配置 (使用默认/Mock)", select_default=False)

    def refresh_episode_list(self):
        if not self.series_manager:
            return
        
        self.episode_list.clear()
        episodes = self.series_manager.get_episodes()
        
        for ep in episodes:
            item = QListWidgetItem(f"第{ep['id']}集: {ep['title']}")
            item.setData(Qt.ItemDataRole.UserRole, ep)
            self.episode_list.addItem(item)
            
        # Also check for legacy "current_script.json" and maybe import it?
        # For now, we just list what's in series.json

    def create_new_episode_ui(self):
        self.current_script = None
        self.current_episode_id = None
        self.script_editor.load_script(None)
        self.episode_list.clearSelection()

    def edit_premise(self):
        if not self.series_manager: return
        current_premise = self.series_manager.data.get("premise", "")
        text, ok = QInputDialog.getMultiLineText(self, "设定剧集大纲", "输入整个系列的故事背景、世界观和主线:", current_premise)
        if ok:
            self.series_manager.update_premise(text)

    # ---------- 模板创建 ----------
    def _create_from_template(self):
        """弹出模板选择器，用模板节拍生成剧本骨架并载入编辑器。"""
        if not self.project_dir:
            QMessageBox.information(self, "提示", "请先在项目管理中加载项目。")
            return
        try:
            library = TemplateLibrary()
            templates = library.list_templates()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"读取模板目录失败: {e}")
            return
        if not templates:
            QMessageBox.information(self, "提示", "暂无可用模板。")
            return

        dlg = TemplatePickerDialog(templates, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected_template:
            return
        tpl = dlg.selected_template
        topic = dlg.topic_text.strip()

        # 用模板节拍构建剧本骨架（每拍一个分镜，8s）
        from core.script.script_model import Scene as ScriptScene
        script = Script(
            title=topic or tpl.get("name", "模板剧本"),
            genre=tpl.get("genre", ""),
            summary=tpl.get("description", ""),
        )
        beats = tpl.get("beats") or []
        characters = "、".join(tpl.get("characters") or [])
        for i, beat in enumerate(beats, start=1):
            scene = ScriptScene(
                shot_id=f"1-{i}",
                scene_location="",
                atmosphere=tpl.get("genre", ""),
                style=tpl.get("name", ""),
                shot_type="中景",
                camera_movement="固定",
                duration_seconds=8,
                characters=characters,
                action=beat,
                description=beat,
            )
            script.scenes.append(scene)
        # 无节拍时至少给一个空分镜
        if not script.scenes:
            script.scenes.append(ScriptScene(shot_id="1-1", duration_seconds=8))

        # 载入编辑器；清空 current_episode_id 使保存时创建新剧集
        self.current_script = script
        self.current_episode_id = None
        self.script_editor.project_dir = self.project_dir
        self.script_editor.load_script(script, title_info=f"[模板] {tpl.get('name', '')}")
        QMessageBox.information(self, "模板已载入", f"已按模板「{tpl.get('name', '')}」生成 {len(script.scenes)} 个分镜骨架，可编辑后点击「保存本集」。")

    def on_episode_selected(self, item):
        if not item:
            print("DEBUG: on_episode_selected called with None item")
            return
        try:
            ep_data = item.data(Qt.ItemDataRole.UserRole)
            if not ep_data:
                print("DEBUG: ep_data is None")
                return
            script_rel_path = ep_data.get("script_path")
            if script_rel_path:
                full_path = os.path.join(self.project_dir, script_rel_path)
                if os.path.exists(full_path):
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        self.current_script = Script.from_json(content)
                        
                        # 规范化：补齐至少9个分镜，并把单镜时长收敛到 5-10 秒区间
                        from core.script.script_model import Scene
                        from core.script.script_service import clamp_shot_duration
                        while len(self.current_script.scenes) < 9:
                            idx = len(self.current_script.scenes) + 1
                            self.current_script.scenes.append(Scene(shot_id=f"1-{idx}", duration_seconds=8))
                        for scene in self.current_script.scenes:
                            scene.duration_seconds = clamp_shot_duration(getattr(scene, 'duration_seconds', None))
                        
                        # Construct Title
                        project_name = os.path.basename(self.project_dir)
                        ep_id = ep_data.get('id', '?')
                        self.current_episode_id = ep_data.get('id') # Store ID
                        ep_title = ep_data.get('title', 'Untitled')
                        full_title = f"{project_name} - 第 {ep_id} 集: {ep_title}"
                        
                        self.script_editor.project_dir = self.project_dir
                        self.script_editor.current_script_path = full_path
                        self.script_editor.load_script(self.current_script, full_title)
        except Exception as e:
            print(f"Error loading episode script: {e}")
            import traceback
            traceback.print_exc()

    def load_episode_by_id(self, ep_id):
        """Loads an episode by its ID (string or int)."""
        print(f"DEBUG: load_episode_by_id called with ep_id={ep_id}, series_manager={self.series_manager}")
        if not self.series_manager:
            print("DEBUG: series_manager is None, returning")
            return
        
        try:
            ep_id = int(ep_id)
        except (ValueError, TypeError):
            print(f"Invalid episode ID: {ep_id}")
            return
        
        print(f"DEBUG: Looking for episode {ep_id} in {self.episode_list.count()} items")
        # Find the item in the list widget
        for i in range(self.episode_list.count()):
            item = self.episode_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            print(f"DEBUG: Item {i}: data={data}")
            if data and data.get("id") == ep_id:
                print(f"DEBUG: Found episode at index {i}")
                self.episode_list.setCurrentItem(item)
                self.on_episode_selected(item)
                return
        
        print(f"Episode {ep_id} not found in list.")

    def data_fingerprint(self):
        """主窗口 Tab 切换指纹：项目设置/剧集/剧本未变时跳过重载。"""
        from ui.utils import dir_signature
        if not self.project_dir:
            return None
        return dir_signature(
            os.path.join(self.project_dir, "project.json"),
            os.path.join(self.project_dir, "series.json"),
            os.path.join(self.project_dir, "scripts"),
            os.path.join(self.project_dir, "current_script.json"),
        )

    def load_existing_script(self):
        """Loads script from the current project directory if it exists."""
        if not self.project_dir:
            return
            
        # Load Project Settings (Ratio & Style)
        try:
            project_json_path = os.path.join(self.project_dir, "project.json")
            if os.path.exists(project_json_path):
                with open(project_json_path, 'r', encoding='utf-8') as f:
                    project_data = json.load(f)
                    ratio = project_data.get("ratio", "16:9")
                    resolution = project_data.get("resolution", "1080p")
                    # 兼容旧项目：早期只写了 style，未写 visual_style
                    visual_style = project_data.get("visual_style") or project_data.get("style") or "未设置"
                    
                    if ratio == "9:16":
                        self.ratio_v.setChecked(True)
                    else:
                        self.ratio_h.setChecked(True)
                        
                    if resolution == "720p":
                        self.res_720.setChecked(True)
                    else:
                        self.res_1080.setChecked(True)
                        
                    # Update Info Box —— 严格显示创建项目时写入的配置
                    p_type = project_data.get("type", "original")
                    p_genre = project_data.get("genre", "未设置")
                    p_episodes = project_data.get("total_episodes", 0)
                    
                    type_map = {"original": "原创短剧", "adaptation": "改编短剧"}
                    self.info_type.setText(type_map.get(p_type, "原创短剧"))
                    self.info_genre.setText(p_genre or "未设置")
                    self.info_visual_style.setText(visual_style)
                    if p_episodes:
                        self.info_count.setText(f"{p_episodes} 集")
                        
        except Exception as e:
            print(f"Error loading project settings: {e}")

        # Try to load series data
        if self.series_manager:
            self.refresh_episode_list()
            
            # If episodes exist, select the appropriate one
            if self.episode_list.count() > 0:
                print(f"DEBUG: load_existing_script - current_episode_id={self.current_episode_id}, total_episodes={self.episode_list.count()}")
                # Priority 1: If we have a current_episode_id, select that episode
                if self.current_episode_id:
                    print(f"DEBUG: Selecting previously edited episode {self.current_episode_id}")
                    self.load_episode_by_id(self.current_episode_id)
                else:
                    # Priority 2: Select the last episode (default behavior)
                    print(f"DEBUG: No current_episode_id, selecting last episode")
                    self.episode_list.setCurrentRow(self.episode_list.count() - 1)
                    current_item = self.episode_list.currentItem()
                    if current_item:
                        self.on_episode_selected(current_item)
            else:
                # Fallback to legacy current_script.json if series is empty
                path = os.path.join(self.project_dir, "current_script.json")
                if os.path.exists(path):
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            self.current_script = Script.from_json(content)
                            
                            # 强制规范化
                            from core.script.script_model import Scene
                            from core.script.script_service import clamp_shot_duration as _clamp_dur
                            while len(self.current_script.scenes) < 9:
                                idx = len(self.current_script.scenes) + 1
                                self.current_script.scenes.append(Scene(shot_id=f"1-{idx}", duration_seconds=8))
                            for scene in self.current_script.scenes:
                                scene.duration_seconds = _clamp_dur(scene.duration_seconds)
                            
                            project_name = os.path.basename(self.project_dir)
                            full_title = f"{project_name} - 当前剧本"
                            
                            self.script_editor.project_dir = self.project_dir
                            self.script_editor.current_script_path = path
                            self.script_editor.load_script(self.current_script, full_title)
                    except Exception as e:
                        print(f"Failed to auto-load script: {e}")

    def start_generation(self):
        prompt = self.topic_input.toPlainText()
        if not prompt:
            QMessageBox.warning(self, "错误", "请输入故事创意。")
            return
            
        self.progress.show()
        self.progress.setRange(0, 0) # Indeterminate
        
        selected_config = self.api_combo.currentData()
        duration = self.duration_combo.currentText()
        style = self.style_list.currentItem().text() if self.style_list.currentItem() else "Default"
        
        # Get Context from SeriesManager (RAG)
        context_data = {}
        if self.series_manager:
            context_data = self.series_manager.get_full_context_data(prompt)
            print(f"DEBUG: Context gathered for generation.")
        
        _reset_cancel()
        self.thread = ScriptGeneratorThread(prompt, selected_config, duration, style, context_data, self.project_dir)
        self.thread.finished.connect(self.on_generation_finished)
        self.thread.error.connect(self.on_generation_error)
        self.thread.start()

    def on_generation_finished(self, data):
        """Handle generation result with characters, props, and scenes"""
        self.progress.hide()
        try:
            # Normalize: force exactly 10 shots, each 8-10s (总时长 ≥75s)
            scenes = data.get("shots", []) or data.get("scenes", [])
            from core.script.script_service import clamp_shot_duration as _clamp_dur
            shots = (scenes or [])[:10]
            while len(shots) < 10:
                idx = len(shots) + 1
                shots.append({
                    "shot_id": f"1-{idx}",
                    "scene_location": "",
                    "time": "Day",
                    "weather": "Clear",
                    "atmosphere": "",
                    "style": "",
                    "shot_type": "中景",
                    "camera_movement": "固定",
                    "characters": "",
                    "props": "",
                    "action": "",
                    "dialogue": "",
                    "video_prompt": "",
                    "duration_seconds": 8
                })
            for shot in shots:
                shot["duration_seconds"] = _clamp_dur(shot.get("duration_seconds"))
            data["shots"] = shots
            
            # Create Script object
            next_id = len(self.series_manager.data.get("episodes", [])) + 1 if self.series_manager else 1
            self.current_script = Script(
                title=data.get("title") or f"第{next_id}集",
                genre=self.style,
                scenes=shots
            )
            
            # Auto-create characters, props, and scenes
            created_items = self._auto_create_resources(data)
            
            # Construct Title
            project_name = os.path.basename(self.project_dir) if self.project_dir else "未保存项目"
            title = self.current_script.title or f"第{next_id}集"
            full_title = f"{project_name} - 第 {next_id} 集: {title}"
            
            self.script_editor.load_script(self.current_script, full_title)
            self.content_tabs.setCurrentIndex(1) # Switch to editor tab
            
            # Show success message with created items
            msg = f"剧本生成成功！\n\n已自动创建:\n"
            msg += f"- 角色: {len(created_items['characters'])} 个\n"
            msg += f"- 道具: {len(created_items['props'])} 个\n"
            msg += f"- 场景: {len(created_items['scenes'])} 个"
            QMessageBox.information(self, "生成成功", msg)
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"处理生成结果失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _auto_create_resources(self, data):
        """Automatically create characters, props, and scenes from generated data"""
        created = {
            "characters": [],
            "props": [],
            "scenes": []
        }
        
        if not self.project_dir:
            print("DEBUG: No project_dir, skipping resource creation")
            return created
        
        # Debug: Print what we received
        print(f"DEBUG: Received data keys: {data.keys()}")
        print(f"DEBUG: Characters data: {data.get('characters', [])}")
        print(f"DEBUG: Props data: {data.get('props', [])}")
        print(f"DEBUG: Scenes data (script_scenes): {data.get('script_scenes', [])}")
        print(f"DEBUG: Scenes data (scenes): {data.get('scenes', [])}")
        
        # Create characters
        characters_data = data.get("characters", [])
        print(f"DEBUG: Creating {len(characters_data)} characters")
        for char_data in characters_data:
            try:
                character = self._create_character(char_data)
                if character:
                    created["characters"].append(character.name)
                    print(f"DEBUG: Created character: {character.name}")
            except Exception as e:
                print(f"Error creating character {char_data.get('name')}: {e}")
        
        # Create props
        props_data = data.get("props", [])
        print(f"DEBUG: Creating {len(props_data)} props")
        for prop_data in props_data:
            try:
                prop = self._create_prop(prop_data)
                if prop:
                    created["props"].append(prop.name)
                    print(f"DEBUG: Created prop: {prop.name}")
            except Exception as e:
                print(f"Error creating prop {prop_data.get('name')}: {e}")
        
        # Create scenes (handle both "scenes" and "script_scenes" keys)
        scenes_data = data.get("script_scenes", []) or data.get("scenes", [])
        print(f"DEBUG: Creating {len(scenes_data)} scenes")
        for scene_data in scenes_data:
            try:
                scene = self._create_scene(scene_data)
                if scene:
                    created["scenes"].append(scene.name)
                    print(f"DEBUG: Created scene: {scene.name}")
            except Exception as e:
                print(f"Error creating scene {scene_data.get('name')}: {e}")
        
        print(f"DEBUG: Created items: {created}")
        return created
    
    def _create_character(self, char_data):
        """Create a character from generated data"""
        name = char_data.get("name", "")
        if not name:
            return None
        
        # Check if character already exists
        characters_dir = os.path.join(self.project_dir, "characters")
        if os.path.exists(characters_dir):
            for f in os.listdir(characters_dir):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(characters_dir, f), 'r', encoding='utf-8') as file:
                            existing = json.load(file)
                            if existing.get("name") == name:
                                print(f"Character '{name}' already exists, skipping")
                                return None
                    except Exception:
                        pass
        
        character = Character(
            id=str(uuid.uuid4()),
            name=name,
            gender=char_data.get("gender", "未知"),
            nationality=char_data.get("nationality", "") or char_data.get("ethnicity", ""),
            age=char_data.get("age", "未知"),
            appearance_features=char_data.get("appearance_features", ""),
            style_description=char_data.get("style_description", ""),
            personality=char_data.get("personality", ""),
            role_in_story=char_data.get("role_in_story", "配角"),
            ai_prompt=self._generate_character_prompt(char_data),
            default_ai_prompt=self._generate_character_prompt(char_data),
            project_id=os.path.basename(self.project_dir)
        )
        
        # Save character
        character.save(self.project_dir)
        return character
    
    def _create_prop(self, prop_data):
        """Create a prop from generated data"""
        name = prop_data.get("name", "")
        if not name:
            return None
        
        # Check if prop already exists
        props_dir = os.path.join(self.project_dir, "props")
        if os.path.exists(props_dir):
            for f in os.listdir(props_dir):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(props_dir, f), 'r', encoding='utf-8') as file:
                            existing = json.load(file)
                            if existing.get("name") == name:
                                print(f"Prop '{name}' already exists, skipping")
                                return None
                    except Exception:
                        pass
        
        prop = Prop(
            id=str(uuid.uuid4()),
            name=name,
            description=prop_data.get("description", ""),
            category=prop_data.get("category", "其他"),
            importance=prop_data.get("importance", "一般"),
            ai_prompt=self._generate_prop_prompt(prop_data),
            default_ai_prompt=self._generate_prop_prompt(prop_data),
            project_id=os.path.basename(self.project_dir)
        )
        
        # Save prop
        prop.save(self.project_dir)
        return prop
    
    def _create_scene(self, scene_data):
        """Create a scene from generated data"""
        name = scene_data.get("name", "")
        if not name:
            return None
        
        # Check if scene already exists
        scenes_dir = os.path.join(self.project_dir, "scenes")
        if os.path.exists(scenes_dir):
            for f in os.listdir(scenes_dir):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(scenes_dir, f), 'r', encoding='utf-8') as file:
                            existing = json.load(file)
                            if existing.get("name") == name:
                                print(f"Scene '{name}' already exists, skipping")
                                return None
                    except Exception:
                        pass
        
        scene = Scene(
            id=str(uuid.uuid4()),
            name=name,
            description=scene_data.get("description", ""),
            time_of_day=scene_data.get("time_of_day", "Day"),
            weather=scene_data.get("weather", "Clear"),
            style=scene_data.get("style", ""),
            ai_prompt=self._generate_scene_prompt(scene_data),
            default_ai_prompt=self._generate_scene_prompt(scene_data),
            project_id=os.path.basename(self.project_dir)
        )
        
        # Save scene
        scene.save(self.project_dir)
        return scene
    
    def _generate_character_prompt(self, char_data):
        """委托给 script_service 的统一实现，确保性别/国别强约束一致。"""
        return script_service.generate_character_prompt(char_data)
    
    def _generate_prop_prompt(self, prop_data):
        """Generate AI prompt for prop with detailed description"""
        name = prop_data.get("name", "")
        description = prop_data.get("description", "")
        category = prop_data.get("category", "其他")
        material = prop_data.get("material", "")
        color = prop_data.get("color", "")
        size = prop_data.get("size", "")
        style = prop_data.get("style", "")
        
        prompt = f"[道具/主体]\n"
        prompt += f"道具名称: {name}\n"
        prompt += f"分类: {category}\n\n"
        
        prompt += f"[详细描述]\n"
        prompt += f"{description}\n\n"
        
        if material or color or size:
            prompt += f"[材质规格]\n"
            if material:
                prompt += f"材质: {material}\n"
            if color:
                prompt += f"颜色: {color}\n"
            if size:
                prompt += f"尺寸: {size}\n"
            prompt += "\n"
        
        prompt += f"[场景环境]\n"
        prompt += f"clean studio background, neutral backdrop, product display setting, minimal environment\n\n"
        
        prompt += f"[时间天气]\n"
        prompt += f"controlled indoor lighting, studio environment\n\n"
        
        prompt += f"[光影氛围]\n"
        prompt += f"professional product lighting, soft shadows, highlights on surface, three-point lighting setup, clean illumination\n\n"
        
        prompt += f"[镜头构图]\n"
        prompt += f"centered composition, product focused, slight angle view, clear visibility of details, fill frame appropriately\n\n"
        
        prompt += f"[风格画质]\n"
        if style:
            prompt += f"{style}, "
        prompt += f"product photography, ultra detailed, 8k, masterpiece, best quality, studio lighting, clean background, sharp focus, high resolution, commercial photography style\n\n"
        
        prompt += f"[反向提示词]\n"
        prompt += f"lowres, bad anatomy, bad hands, text, error, blurry, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, bad proportions, deformed, disfigured, mutation, mutated, ugly, disgusting, blurry, poorly drawn, bad art, beginner, amateur, cluttered background, distracting elements, dirty, damaged"
        
        return prompt
    
    def _generate_scene_prompt(self, scene_data):
        """Generate AI prompt for scene with detailed description"""
        name = scene_data.get("name", "")
        description = scene_data.get("description", "")
        time_of_day = scene_data.get("time_of_day", "Day")
        weather = scene_data.get("weather", "Clear")
        style = scene_data.get("style", "")
        location_type = scene_data.get("location_type", "")
        atmosphere = scene_data.get("atmosphere", "")
        key_elements = scene_data.get("key_elements", "")
        
        prompt = f"[场景/环境]\n"
        prompt += f"场景名称: {name}\n\n"
        
        prompt += f"[场景描述]\n"
        prompt += f"{description}\n\n"
        
        if location_type:
            prompt += f"[场景类型]\n"
            prompt += f"{location_type}\n\n"
        
        if key_elements:
            prompt += f"[关键元素]\n"
            prompt += f"{key_elements}\n\n"
        
        prompt += f"[时间天气]\n"
        prompt += f"时间: {time_of_day}\n"
        prompt += f"天气: {weather}\n\n"
        
        prompt += f"[光影氛围]\n"
        if atmosphere:
            prompt += f"{atmosphere}\n"
        prompt += f"cinematic lighting, dramatic atmosphere, volumetric light, atmospheric perspective, depth of field\n\n"
        
        prompt += f"[镜头构图]\n"
        prompt += f"wide shot, establishing shot, landscape view, balanced composition, clear foreground and background, environmental storytelling\n\n"
        
        prompt += f"[风格画质]\n"
        if style:
            prompt += f"{style}, "
        prompt += f"environment concept art, ultra detailed, 8k, masterpiece, best quality, matte painting, cinematic composition, photorealistic environment, rich details\n\n"
        
        prompt += f"[反向提示词]\n"
        prompt += f"lowres, blurry, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, bad proportions, deformed, disfigured, mutation, mutated, ugly, disgusting, blurry, poorly drawn, bad art, beginner, amateur, flat lighting, empty scene, boring composition"
        
        return prompt

    def on_generation_error(self, error_msg):
        self.progress.hide()
        QMessageBox.critical(self, "错误", f"生成失败: {error_msg}")

    def save_script(self):
        if not self.current_script:
            return

        # If we are in series mode, save as episode
        if self.series_manager:
            # Determine title
            title = self.current_script.title or "未命名剧集"
            content = self.current_script.to_json()
            
            if self.current_episode_id:
                # Update existing episode
                success = self.series_manager.update_episode(
                    self.current_episode_id, 
                    title, 
                    content, 
                    summary=self.current_script.summary
                )
                if success:
                    self.refresh_episode_list()
                    # Reselect the current item
                    self.load_episode_by_id(self.current_episode_id)
                    QMessageBox.information(self, "已保存", f"剧集 '{title}' 已更新。")
                else:
                    QMessageBox.warning(self, "错误", "更新剧集失败，ID未找到。")
            else:
                # Add new episode
                self.series_manager.add_episode(title, content, summary=self.current_script.summary)
                self.refresh_episode_list()
                # Select the new (last) item
                if self.episode_list.count() > 0:
                    self.episode_list.setCurrentRow(self.episode_list.count() - 1)
                    item = self.episode_list.currentItem()
                    if item:
                        data = item.data(Qt.ItemDataRole.UserRole)
                        self.current_episode_id = data.get("id")
                
                QMessageBox.information(self, "已保存", f"剧集 '{title}' 已保存到系列。")
            
            # Also save as current_script.json for backward compatibility with other modules
            path = os.path.join(self.project_dir, "current_script.json")
            self.current_script.save(path)
            
        else:
            # Fallback
            path = os.path.join(self.project_dir, "current_script.json")
            self.current_script.save(path)
            QMessageBox.information(self, "已保存", f"剧本已保存至 {path}")
        
        # Also ensure settings are saved
        self.save_project_settings()

    def save_project_settings(self):
        """Saves ratio and resolution to project.json immediately."""
        if not self.project_dir:
            return
            
        try:
            project_json_path = os.path.join(self.project_dir, "project.json")
            if os.path.exists(project_json_path):
                with open(project_json_path, 'r', encoding='utf-8') as f:
                    project_data = json.load(f)
            else:
                project_data = {}
            
            # Update ratio & resolution
            ratio = "16:9" if self.ratio_h.isChecked() else "9:16"
            resolution = "1080p" if self.res_1080.isChecked() else "720p"
            
            # Only save if changed to avoid unnecessary writes/logs
            if project_data.get("ratio") == ratio and project_data.get("resolution") == resolution:
                return

            project_data["ratio"] = ratio
            project_data["resolution"] = resolution
            
            try:
                from core.utils.json_store import atomic_write_json
            except ImportError:
                from src.core.utils.json_store import atomic_write_json
            atomic_write_json(project_json_path, project_data)
                
            # print(f"DEBUG: Project settings saved to {os.path.abspath(project_json_path)}: Ratio={ratio}, Resolution={resolution}")
                
        except Exception as e:
            print(f"DEBUG: Error saving project settings: {e}")


class TemplatePickerDialog(QDialog):
    """模板选择器：左侧模板列表 + 右侧详情预览 + 主题输入。"""

    def __init__(self, templates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("从模板创建剧本")
        self.resize(640, 460)
        self.templates = templates
        self.selected_template = None
        self.topic_text = ""
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        tip = QLabel("选择一个剧本模板，按其节拍生成分镜骨架；可在下方填入自定义主题。")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        body = QHBoxLayout()
        # 左：模板列表
        self.list_widget = QListWidget()
        self.list_widget.setFixedWidth(200)
        for t in self.templates:
            item = QListWidgetItem(t.get("name", "未命名"))
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.list_widget.addItem(item)
        self.list_widget.currentRowChanged.connect(self._on_select)
        body.addWidget(self.list_widget)

        # 右：详情
        self.detail_view = QTextBrowser()
        self.detail_view.setOpenExternalLinks(False)
        body.addWidget(self.detail_view, 1)
        layout.addLayout(body, 1)

        # 主题输入
        topic_row = QHBoxLayout()
        topic_row.addWidget(QLabel("主题:"))
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("可选：你的故事主题（留空则用模板默认）")
        topic_row.addWidget(self.topic_edit, 1)
        layout.addLayout(topic_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # 默认选第一个
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _on_select(self, row):
        item = self.list_widget.item(row)
        if not item:
            self.detail_view.clear()
            return
        t = item.data(Qt.ItemDataRole.UserRole)
        html = [f"<h3>{t.get('name', '')}</h3>"]
        if t.get("genre"):
            html.append(f"<p><b>类型：</b>{t['genre']}</p>")
        if t.get("description"):
            html.append(f"<p><b>简介：</b>{t['description']}</p>")
        chars = t.get("characters") or []
        if chars:
            html.append(f"<p><b>角色：</b>{'、'.join(chars)}</p>")
        beats = t.get("beats") or []
        if beats:
            html.append("<p><b>剧情节拍：</b></p><ol>")
            for b in beats:
                html.append(f"<li>{b}</li>")
            html.append("</ol>")
        if t.get("prompt"):
            html.append(f"<p><b>生成要求：</b>{t['prompt']}</p>")
        self.detail_view.setHtml("".join(html))

    def _on_accept(self):
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个模板。")
            return
        self.selected_template = item.data(Qt.ItemDataRole.UserRole)
        self.topic_text = self.topic_edit.text().strip()
        self.accept()
