from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QStackedWidget, QLabel, QFrame, QMessageBox,
                             QApplication)
from PyQt6.QtCore import Qt
import os
from ui.role_window import RoleWindow
from ui.script_window import ScriptWindow
from ui.project_window import ProjectWindow
from ui.settings_window import SettingsWindow
from ui.help_window import HelpWindow
from ui.video_editor_window import VideoEditorWindow
from ui.auto_run_window import AutoRunWindow
from ui.asset_library_window import AssetLibraryWindow
from ui import theme as theme_mod
import i18n
try:
    from paths import get_executable_dir
except ImportError:
    try:
        from src.paths import get_executable_dir
    except ImportError:
        def get_executable_dir(): return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("狸猫短剧")
        self.resize(1280, 799)
        self.setMinimumSize(1024, 700)

        # ---- restore theme & language ----
        self._current_theme = "light"
        self._current_skin = "default"
        theme_mod.apply_theme(QApplication.instance(), self._current_theme, self._current_skin)
        i18n.set_language("zh-CN")

        # ---- main container: top bar + (sidebar + content) ----
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ===== Top Bar =====
        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        self.top_bar.setFixedHeight(52)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(16, 0, 16, 0)
        top_layout.setSpacing(12)

        self.lang_btn = QPushButton("中/EN")
        self.lang_btn.setFixedHeight(32)
        self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_btn.clicked.connect(self._toggle_lang)
        top_layout.addWidget(self.lang_btn)

        self.project_status_label = QLabel("")
        self.project_status_label.setStyleSheet("color: " + theme_mod.color("text_sub") + "; font-size: 13px;")
        top_layout.addWidget(self.project_status_label)

        top_layout.addStretch()

        self.theme_btn = QPushButton("浅色/深色")
        self.theme_btn.setFixedHeight(32)
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._toggle_theme)
        top_layout.addWidget(self.theme_btn)

        self.skin_btn = QPushButton("🎨 默认青绿")
        self.skin_btn.setFixedHeight(32)
        self.skin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skin_btn.clicked.connect(self._cycle_skin)
        top_layout.addWidget(self.skin_btn)

        # ===== body: sidebar + content =====
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("SideBar")
        self.sidebar.setFixedWidth(180)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 12)
        sidebar_layout.setSpacing(4)

        self.nav_buttons = []
        self.nav_labels = ["首页", "项目", "剧本", "角色", "视频", "素材", "设置", "帮助"]
        for idx, label in enumerate(self.nav_labels):
            self.create_nav_button(label, idx, sidebar_layout)

        sidebar_layout.addStretch()

        # ===== Content Area =====
        self.content_area = QStackedWidget()

        body.addWidget(self.sidebar)
        body.addWidget(self.content_area, 1)

        body_widget = QWidget()
        body_widget.setLayout(body)
        main_layout.addWidget(self.top_bar)
        main_layout.addWidget(body_widget, 1)

        # ---- paths ----
        base_dir = get_executable_dir()
        resources_dir = os.path.join(base_dir, "resources")
        characters_dir = os.path.join(resources_dir, "characters")
        props_dir = os.path.join(resources_dir, "props")
        scenes_dir = os.path.join(resources_dir, "scenes")
        projects_dir = os.path.join(resources_dir, "projects")

        # ---- windows ----
        self.auto_run_window = AutoRunWindow(None, projects_dir=projects_dir)
        self.auto_run_window.set_main_window(self)
        self.project_window = ProjectWindow(projects_dir)
        self.script_window = ScriptWindow(None)
        self.role_window = RoleWindow(characters_dir, props_dir, scenes_dir)
        self.video_editor_window = VideoEditorWindow(None)
        self.asset_library_window = AssetLibraryWindow(None, resources_dir=resources_dir)
        self.settings_window = SettingsWindow()
        self.help_window = HelpWindow()

        # ---- signals ----
        self.project_window.project_loaded.connect(self.on_project_loaded)
        self.project_window.open_episode.connect(self.open_episode_in_script_editor)

        # ---- add widgets (index order must match nav_labels) ----
        self.content_area.addWidget(self.auto_run_window)   # 0 首页
        self.content_area.addWidget(self.project_window)     # 1 项目
        self.content_area.addWidget(self.script_window)      # 2 剧本
        self.content_area.addWidget(self.role_window)        # 3 角色
        self.content_area.addWidget(self.video_editor_window)# 4 视频
        self.content_area.addWidget(self.asset_library_window)# 5 素材
        self.content_area.addWidget(self.settings_window)    # 6 设置
        self.content_area.addWidget(self.help_window)        # 7 帮助

        # default = 首页
        self.nav_buttons[0].setChecked(True)

        # Tab 切换指纹缓存：(tab_index -> fingerprint)，内容未变则跳过全量重载
        self._tab_fingerprints = {}
        # 待按当前主题重建的页面索引集合（主题切换后内联样式需重新求值）
        self._stale_pages = set()
        # 当前打开的项目路径：主题/皮肤切换会重建页面，重建后需要据此恢复项目
        self._current_project_path = None

    # ---------- theme / language ----------
    def _toggle_theme(self):
        self._current_theme = "light" if self._current_theme == "dark" else "dark"
        self._apply_theme_and_refresh()

    def _cycle_skin(self):
        keys = list(theme_mod.SKIN_NAMES.keys())
        idx = keys.index(self._current_skin) if self._current_skin in keys else 0
        self._current_skin = keys[(idx + 1) % len(keys)]
        name = theme_mod.SKIN_NAMES.get(self._current_skin, "默认")
        self.skin_btn.setText(f"🎨 {name}")
        self._apply_theme_and_refresh()

    def _apply_theme_and_refresh(self):
        """应用主题/皮肤，并刷新所有页面。

        页面的内联样式（_theme.color(...)）在构造时求值，切换主题后必须重建才会
        生效。此前只重建「当前可见页」，用户切到其他页时那些页仍是旧主题的配色，
        表现为：浅色主题下大量深色面板、深色主题下大量浅色面板。
        这里把全部页面标记为待重建，脚本切到哪页就重建哪页，避免一次性重建全部
        重载页面造成卡顿与状态丢失。
        """
        theme_mod.apply_theme(QApplication.instance(), self._current_theme, self._current_skin)
        # 更新 Windows 标题栏颜色
        from ui.utils import apply_windows_dark_title_bar
        apply_windows_dark_title_bar(self, dark=(self._current_theme == "dark"))

        self._stale_pages = set(range(self.content_area.count()))
        # 当前可见页立即重建（否则要等切页才刷新，用户会先看到旧配色）
        self._recreate_current_page()

    def _recreate_current_page(self):
        """重建当前可见页面。"""
        self._recreate_page(self.content_area.currentIndex())

    def _recreate_page(self, idx):
        """按当前主题重建指定索引的页面（内联样式在创建时求值，必须重建才能生效）。"""
        try:
            if idx < 0 or idx >= self.content_area.count():
                return
            self._stale_pages.discard(idx)
            old_widget = self.content_area.widget(idx)
            if old_widget is None:
                return
            # 记录项目路径以便重建后恢复
            proj_path = self._current_project_path or getattr(
                getattr(self, "project_window", None), "current_project_path", None)
            # 剧本页还需保留当前选中的集，否则重建后会跳回其他集
            prev_episode_id = getattr(old_widget, "current_episode_id", None) if idx == 2 else None

            # 按索引重建
            resources_dir = os.path.join(get_executable_dir(), "resources")
            characters_dir = os.path.join(resources_dir, "characters")
            props_dir = os.path.join(resources_dir, "props")
            scenes_dir = os.path.join(resources_dir, "scenes")
            projects_dir = os.path.join(resources_dir, "projects")

            ctors = {
                0: lambda: AutoRunWindow(None, projects_dir=projects_dir),
                1: lambda: ProjectWindow(projects_dir),
                2: lambda: ScriptWindow(None),
                3: lambda: RoleWindow(characters_dir, props_dir, scenes_dir),
                4: lambda: VideoEditorWindow(None),
                5: lambda: AssetLibraryWindow(None, resources_dir=resources_dir),
                6: lambda: SettingsWindow(),
                7: lambda: HelpWindow(),
            }
            if idx not in ctors:
                return
            new_widget = ctors[idx]()

            # 替换
            self.content_area.removeWidget(old_widget)
            old_widget.deleteLater()
            self.content_area.insertWidget(idx, new_widget)
            self.content_area.setCurrentIndex(idx)

            # 若当前为英文，新建页面需要即时翻译（否则保持中文）
            if i18n.lang() == "en-US":
                i18n.apply_language(new_widget, "en-US")

            # 更新属性引用
            attr_names = {
                0: "auto_run_window", 1: "project_window", 2: "script_window",
                3: "role_window", 4: "video_editor_window", 5: "asset_library_window",
                6: "settings_window", 7: "help_window",
            }
            attr = attr_names.get(idx)
            if attr:
                setattr(self, attr, new_widget)

            # 重连信号
            if idx == 0 and hasattr(new_widget, "set_main_window"):
                new_widget.set_main_window(self)
            if idx == 1:
                new_widget.project_loaded.connect(self.on_project_loaded)
                new_widget.open_episode.connect(self.open_episode_in_script_editor)
                if proj_path and hasattr(new_widget, "load_project_by_path"):
                    new_widget.load_project_by_path(proj_path)

            # 重建后必须让下次 switch_tab 重新加载：
            # 新页面是空白的，而磁盘指纹与旧页面相同会被误判为“无需重载”，
            # 表现为切换主题后页面空白、丢失当前项目信息。
            if proj_path and idx != 1 and hasattr(new_widget, "set_project_dir"):
                if idx == 2:
                    # 剧本页：只挂载目录 + 恢复选中集，加载交给下面的 load_existing_script
                    new_widget.project_dir = proj_path
                    if prev_episode_id is not None:
                        try:
                            new_widget.current_episode_id = int(prev_episode_id)
                        except (TypeError, ValueError):
                            pass
                    if hasattr(new_widget, "check_project_status"):
                        new_widget.check_project_status()
                else:
                    new_widget.set_project_dir(proj_path)

            # 立即加载页面数据：新页面是空白的，若不加载，切主题后当前页会变成空面板
            # （素材库/分镜/剧本全空），看起来就像丢了当前项目。
            if hasattr(new_widget, 'load_existing_data'):
                try:
                    new_widget.load_existing_data()
                except Exception as e:
                    print(f"[WARN] _recreate_page load_existing_data({idx}): {e}")
            elif hasattr(new_widget, 'load_existing_script'):
                try:
                    new_widget.load_existing_script()
                except Exception as e:
                    print(f"[WARN] _recreate_page load_existing_script({idx}): {e}")

            # 记录加载后的指纹，让随后的 switch_tab 判定“无需重载”，避免重复全量加载
            get_fp = getattr(new_widget, "data_fingerprint", None)
            if callable(get_fp):
                try:
                    self._tab_fingerprints[idx] = get_fp()
                except Exception:
                    self._tab_fingerprints.pop(idx, None)
            else:
                self._tab_fingerprints.pop(idx, None)
        except Exception as e:
            print(f"[WARN] _recreate_page: {e}")

    def _toggle_lang(self):
        new = "en-US" if i18n.lang() == "zh-CN" else "zh-CN"
        i18n.set_language(new)
        i18n.apply_language(self, new)
        # retranslate nav buttons + window title
        for idx, btn in enumerate(self.nav_buttons):
            btn.setText(i18n.t(self.nav_labels[idx]))
        self.setWindowTitle(i18n.t("狸猫短剧"))

    # ---------- nav ----------
    def create_nav_button(self, text, index, layout):
        btn = QPushButton(i18n.t(text))
        btn.setObjectName("NavBtn")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self.switch_tab(index, btn))
        layout.addWidget(btn)
        self.nav_buttons.append(btn)

    def goto_tab(self, index):
        if 0 <= index < len(self.nav_buttons):
            self.switch_tab(index, self.nav_buttons[index])

    def switch_tab(self, index, sender_btn):
        try:
            # 该页若是在切换主题前构建的，先按当前主题重建，避免残留旧主题配色
            if index in self._stale_pages:
                self._recreate_page(index)
            self.content_area.setCurrentIndex(index)
            for btn in self.nav_buttons:
                btn.setChecked(False)
            sender_btn.setChecked(True)

            current_widget = self.content_area.currentWidget()

            # 指纹未变则跳过重载（原每次切换都全量扫目录 + 解析 JSON + 重建卡片，造成明显卡顿）
            fingerprint = None
            get_fp = getattr(current_widget, "data_fingerprint", None)
            if callable(get_fp):
                try:
                    fingerprint = get_fp()
                except Exception:
                    fingerprint = None
            cached = self._tab_fingerprints.get(index)
            if fingerprint is not None and fingerprint == cached:
                return

            if hasattr(current_widget, 'load_existing_data'):
                try:
                    current_widget.load_existing_data()
                except Exception as e:
                    print(f"ERROR in switch_tab load_existing_data: {e}")
            elif hasattr(current_widget, 'load_existing_script'):
                try:
                    current_widget.load_existing_script()
                except Exception as e:
                    print(f"ERROR in switch_tab load_existing_script: {e}")

            if fingerprint is not None:
                self._tab_fingerprints[index] = fingerprint
        except Exception as e:
            print(f"ERROR in switch_tab: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"切换标签页时出错: {str(e)}")

    # ---------- project ----------
    def on_project_loaded(self, project_path):
        if not project_path:
            return
        try:
            self._current_project_path = project_path
            # 项目切换后所有 Tab 的指纹失效，必须全量重载
            self._tab_fingerprints = {}

            if hasattr(self.script_window, 'set_project_dir'):
                self.script_window.set_project_dir(project_path)
            else:
                self.script_window.project_dir = project_path

            self.role_window.set_project_dir(project_path)
            self.video_editor_window.set_project_dir(project_path)

            if hasattr(self.auto_run_window, 'set_project_dir'):
                self.auto_run_window.set_project_dir(project_path)

            if hasattr(self.asset_library_window, 'set_project_dir'):
                self.asset_library_window.set_project_dir(project_path)

            name = os.path.basename(project_path)
            self.project_status_label.setText(f"  •  当前项目：{name}")
        except Exception as e:
            print(f"ERROR in on_project_loaded: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"加载项目时出错: {str(e)}")

    def open_episode_in_script_editor(self, project_path, episode_id):
        try:
            # 只切换项目目录，不触发全量重载（on_project_loaded 会重载所有 Tab，导致卡死）
            self._current_project_path = project_path
            if self.script_window.project_dir != project_path:
                self.script_window.project_dir = project_path
                self.script_window.check_project_status()
            # 先设置目标集 ID，让 switch_tab 触发的 load_existing_script 自动加载它
            try:
                self.script_window.current_episode_id = int(episode_id)
            except (ValueError, TypeError):
                pass
            self.switch_tab(2, self.nav_buttons[2])
            if hasattr(self.script_window, 'load_episode_by_id'):
                self.script_window.load_episode_by_id(episode_id)
        except Exception as e:
            print(f"ERROR in open_episode_in_script_editor: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"打开剧集失败: {str(e)}")

    def closeEvent(self, event):
        busy = []
        checks = [
            (getattr(self, "project_window", None), ("gen_thread", "outline_thread", "adapt_thread"), "剧本生成"),
            (getattr(self, "script_window", None), ("thread",), "剧本生成"),
            (getattr(self, "video_editor_window", None), ("export_thread",), "视频导出"),
            (getattr(self, "auto_run_window", None), ("run_thread",), "全自动流水线"),
        ]
        for win, attrs, label in checks:
            if win is None:
                continue
            for attr in attrs:
                t = getattr(win, attr, None)
                if t is not None and getattr(t, "isRunning", lambda: False)():
                    busy.append(label)
                    break
        editor = getattr(self, "video_editor_window", None)
        panel = getattr(editor, "storyboard_panel", None)
        vt = getattr(panel, "video_thread", None)
        if vt is not None and getattr(vt, "isRunning", lambda: False)():
            busy.append("视频生成")
        if busy:
            reply = QMessageBox.question(
                self, "任务进行中",
                f"以下任务仍在执行：{'、'.join(dict.fromkeys(busy))}\n\n"
                "强制退出可能产生半成品文件。确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
