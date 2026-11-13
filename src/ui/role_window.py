from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QGridLayout, QMessageBox,
                             QFrame, QLineEdit, QComboBox, QFileDialog,
                             QDialog, QScrollBar, QGridLayout, QSizePolicy, QSpacerItem,
                             QTextEdit, QGroupBox, QProgressBar, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QPixmap, QIcon
import os
import json
import uuid
import shutil
from core.character.character_model import Character
from core.scene.scene_model import Scene
from core.prop.prop_model import Prop
from core.script.script_model import Script
from ui.flow_layout import FlowLayout
from ui import theme as _theme


# 窗口关闭后仍在运行的图片生成线程保存在这里，
# 防止 QThread 被 Python GC 回收时触发 "Destroyed while thread is still running" 崩溃
_DETACHED_WORKERS = set()


def _btn_style_primary():
    """主色按钮样式（每次调用按当前主题求值）。"""
    return """
    QPushButton {
        background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("accent_text") + """;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("accent2") + """;
    }
    QPushButton:pressed {
        background-color: """ + _theme.color("info") + """;
    }
"""


def _btn_style_success():
    """成功色按钮样式（每次调用按当前主题求值）。"""
    return """
    QPushButton {
        background-color: """ + _theme.color("success") + """; color: """ + _theme.color("accent_text") + """;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("success") + """;
    }
    QPushButton:pressed {
        background-color: """ + _theme.color("success") + """;
    }
"""


def _btn_style_danger():
    """危险色按钮样式（每次调用按当前主题求值）。"""
    return """
    QPushButton {
        background-color: """ + _theme.color("danger") + """; color: """ + _theme.color("accent_text") + """;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("danger") + """;
    }
    QPushButton:pressed {
        background-color: """ + _theme.color("danger") + """;
    }
"""


def _btn_style_warning():
    """警告色按钮样式（每次调用按当前主题求值）。"""
    return """
    QPushButton {
        background-color: """ + _theme.color("warning") + """; color: """ + _theme.color("accent_text") + """;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("warning") + """;
    }
    QPushButton:pressed {
        background-color: """ + _theme.color("warning") + """;
    }
"""


def _btn_style_secondary():
    """次级按钮样式（每次调用按当前主题求值）。"""
    return """
    QPushButton {
        background-color: """ + _theme.color("text_sub") + """; color: """ + _theme.color("text") + """;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("text_sub") + """;
    }
    QPushButton:pressed {
        background-color: """ + _theme.color("text_sub") + """;
    }
"""


def _btn_style_accent():
    """强调按钮样式（每次调用按当前主题求值）。"""
    return """
    QPushButton {
        background-color: """ + _theme.color("warning") + """;
        color: """ + _theme.color("accent_text") + """;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("warning") + """;
    }
    QPushButton:pressed {
        background-color: """ + _theme.color("warning") + """;
    }
"""


def _btn_style_icon_small():
    """小图标按钮样式（主色，每次调用按当前主题求值）。"""
    return """
    QPushButton {
        color: """ + _theme.color("accent_text") + """;
        background-color: """ + _theme.color("accent") + """;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 3px 10px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("accent2") + """;
    }
    QPushButton:pressed {
        background-color: """ + _theme.color("info") + """;
        border: 1px solid """ + _theme.color("accent_text") + """;
    }
"""


def _btn_style_icon_success():
    """小图标按钮样式（成功色，每次调用按当前主题求值）。"""
    return """
    QPushButton {
        color: """ + _theme.color("accent_text") + """;
        background-color: """ + _theme.color("success") + """;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 3px 10px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("accent2") + """;
    }
    QPushButton:pressed {
        background-color: """ + _theme.color("accent") + """;
        border: 1px solid """ + _theme.color("accent_text") + """;
    }
"""


def _btn_style_delete_small():
    """小删除按钮样式（每次调用按当前主题求值）。"""
    return """
    QPushButton {
        color: rgba(255, 255, 255, 0.9);
        background: rgba(192, 57, 43, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.5);
        border-radius: 12px;
        font-size: 14px;
        font-weight: bold;
        padding: 0px;
    }
    QPushButton:hover {
color: """ + _theme.color("accent_text") + """;
        background: rgba(231, 76, 60, 0.9);
        border: 1px solid white;
    }
    QPushButton:pressed {
        background: rgba(192, 57, 43, 1);
    }
"""


def _btn_style_purple():
    """紫色按钮样式（每次调用按当前主题求值）。"""
    return """
    QPushButton {
        background-color: """ + _theme.color("accent2") + """; color: """ + _theme.color("accent_text") + """;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: """ + _theme.color("accent2") + """;
    }
"""


class ImageGenerationWorker(QThread):
    """图片生成工作线程"""
    progress_signal = pyqtSignal(int, str)  # 进度值, 状态文本
    finished_signal = pyqtSignal(dict, int, list)  # 生成的图片, 成功数, 失败字段
    error_signal = pyqtSignal(str)

    def __init__(self, item_type, fields, count, prompt, ratio, ref_images, gen_settings, storage_path, client, custom_output_path=None):
        super().__init__()
        self.item_type = item_type
        self.fields = fields[:count]
        self.prompt = prompt
        self.ratio = ratio
        self.ref_images = ref_images
        self.gen_settings = gen_settings
        self.storage_path = storage_path
        self.client = client
        self.custom_output_path = custom_output_path  # 自定义输出路径（用于1拖4模式）

    # 视角强关键词：放在提示词最前面（扩散模型对前置 token 权重最高）
    _VIEW_PREFIX = {
        "front": "front view, facing camera directly, ",
        "back": "back view, seen from behind, rear view, back facing camera, character's back to viewer, ",
        "right": "right side view, profile view from right side, character facing left, side profile, ",
        "left": "left side view, profile view from left side, character facing right, side profile, ",
        "top": "top view, seen from above, high angle looking down at character, ",
        "bottom": "bottom view, seen from below, low angle looking up at character, ",
        "wide": "wide shot, full body establishing view, ",
        "medium": "medium shot, ",
        "close": "close-up view, detailed face, ",
        "side": "side view, profile view, ",
        "three_quarter": "three-quarter view, 45 degree angle between front and side, ",
    }
    # 视角生成时需要中和掉的正面锚定构图词（来自 generate_character_prompt 的 [镜头构图] 段）
    _FRONT_ANCHORS = ("centered composition, eye-level angle, ", "portrait framing, centered composition, eye-level angle, ")

    def _build_view_prompt(self, field):
        """根据视角构建差异化提示词：前置视角关键词 + 移除正面构图锚点 + 身份锁定后缀。"""
        if "grid_1drag4" in field:
            # 1拖4模式：使用原始提示词（已经包含所有角度描述）
            return self.prompt
        prefix = ""
        for key, val in self._VIEW_PREFIX.items():
            if key in field:
                prefix = val
                break
        if not prefix:
            return self.prompt
        prompt = self.prompt
        # 非正面视角：移除会锚定正面的构图短语，避免与视角词冲突
        if "front" not in field:
            for anchor in self._FRONT_ANCHORS:
                prompt = prompt.replace(anchor, "")
        # 五宫格/多视角一致性：追加身份锁定语句，压住跨视角的脸型/服装漂移
        consistency = getattr(self, 'consistency_suffix', None)
        if consistency:
            prompt = prompt.rstrip() + ", " + consistency
        return prefix + prompt

    def run(self):
        try:
            generated_images = {}
            success_count = 0
            failed_fields = []

            for i, field in enumerate(self.fields):
                if self.isInterruptionRequested():
                    failed_fields.extend(self.fields[i:])
                    break
                self.progress_signal.emit(i, f"正在生成 {field} ({i+1}/{len(self.fields)})...")

                # 使用自定义输出路径或自动生成
                if self.custom_output_path and len(self.fields) == 1:
                    output_path = self.custom_output_path
                else:
                    output_name = f"{self.item_type}_{uuid.uuid4()}.png"
                    output_path = os.path.join(self.storage_path, output_name)

                # 根据视角调整提示词（前置强关键词 + 中和正面锚点）
                view_prompt = self._build_view_prompt(field)

                # 每个视角注入随机 seed：避免工作流内置固定 seed 导致所有视角产出同一份噪声
                # 例外：五宫格拼接模式（chain_reference）下 5 个视角共享同一 seed，
                # 配合参考图链与身份锁定后缀，最大程度保持同一角色外观
                import random as _rnd
                per_view_settings = dict(self.gen_settings) if self.gen_settings else {}
                if not isinstance(per_view_settings.get("seed"), int):
                    if getattr(self, 'chain_reference', False):
                        if not getattr(self, '_grid_seed', None):
                            self._grid_seed = _rnd.randint(1, 2**31 - 1)
                        per_view_settings["seed"] = self._grid_seed
                    else:
                        per_view_settings["seed"] = _rnd.randint(1, 2**31 - 1)

                try:
                    result = self.client.generate_image(view_prompt, output_path, self.ref_images, per_view_settings)

                    if result and os.path.exists(output_path):
                        generated_images[field] = output_path
                        success_count += 1
                        # 拼接模式：front_view 生成后作为后续视角的参考图，保证同一角色外观
                        if getattr(self, 'chain_reference', False) and field == "front_view":
                            self.ref_images = list(self.ref_images or []) + [output_path]
                    else:
                        failed_fields.append(field)
                except Exception as e:
                    print(f"生成 {field} 失败: {e}")
                    failed_fields.append(field)

            # 拼接模式：将 5 个单视角图本地合成为五宫格，保证布局永远只有 5 格
            grid_output = getattr(self, 'grid_output_path', None)
            if grid_output and success_count > 0:
                from ai_engine.image_gen.character_grid_generator import CharacterGridGenerator
                grid_path = CharacterGridGenerator.compose_grid(generated_images, grid_output)
                if grid_path:
                    generated_images = {"grid_1drag4": grid_path}

            self.progress_signal.emit(len(self.fields), "生成完成！")
            self.finished_signal.emit(generated_images, success_count, failed_fields)

        except Exception as e:
            self.error_signal.emit(str(e))


class MultiImageEditDialog(QDialog):
    def __init__(self, item_type, item_data, storage_path, parent=None):
        super().__init__(parent)
        self.item_type = item_type
        self.item_data = item_data
        self.storage_path = storage_path
        self.new_image_paths = {}
        self.image_buttons = {}
        self.worker = None
        self.init_ui()

    def done(self, result):
        """拦截 X/Esc/确定/取消：生成线程仍在运行时不能直接关闭对话框。"""
        worker = getattr(self, 'worker', None)
        if worker is not None and worker.isRunning():
            reply = QMessageBox.question(
                self, "图片生成中",
                "图片仍在后台生成。\n关闭后本次生成结果将不会保存到编辑界面（线程安全结束后自动释放）。\n\n确定要关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            # 不使用 terminate()：线程可能在 requests 中持有 GIL，强杀有死锁风险。
            # 断开结果信号（对话框销毁时 Qt 也会自动断开），保活引用到自然结束。
            worker.requestInterruption()
            _DETACHED_WORKERS.add(worker)
            worker.finished.connect(
                lambda w=worker: (_DETACHED_WORKERS.discard(w), w.deleteLater())
            )
        super().done(result)
    
    def init_ui(self):
        if self.item_type == "character":
            self.setWindowTitle(f"编辑角色 - {self.item_data.name}")
            self.resize(1080, 600)
            views = [
                ("front_view", "正面图", "👤"), ("back_view", "后面图", "👤"),
                ("right_side_view", "右侧面", "👤"), ("left_side_view", "左侧面", "👤"), ("top_view", "俯视图", "👤")
            ]
        elif self.item_type == "scene":
            self.setWindowTitle(f"编辑场景 - {self.item_data.name}")
            self.resize(1080, 600)
            views = [
                ("wide_view", "远视图", "🏞️"), ("medium_view", "中视图", "🏞️"),
                ("close_view", "近视图", "🏞️"), ("top_view", "俯视图", "🏞️"), ("side_view", "侧视图", "🏞️")
            ]
        else:
            self.setWindowTitle(f"编辑道具 - {self.item_data.name}")
            self.resize(1080, 600)
            views = [
                ("front_view", "正视图", "🎁"), ("back_view", "后视图", "🎁"),
                ("top_view", "上视图", "🎁"), ("bottom_view", "下视图", "🎁"), ("side_view", "侧视图", "🎁")
            ]
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # 标题栏
        title_bar = QFrame()
        title_bar.setObjectName("PanelBG")
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(15, 10, 15, 10)
        
        icon_c = "🎭" if self.item_type == "character" else ("🏞️" if self.item_type == "scene" else "🎁")
        title_lbl = QLabel(f"{icon_c} 编辑{self.item_type}")
        title_lbl.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 18px; font-weight: bold;")
        title_bar_layout.addWidget(title_lbl)
        title_bar_layout.addStretch()
        
        close_btn = QPushButton("×")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("QPushButton { background:transparent; color:" + _theme.color("text_sub") + "; font-size:22px; border:none; } QPushButton:hover{color:" + _theme.color("danger") + ";}")
        close_btn.clicked.connect(self.reject)
        title_bar_layout.addWidget(close_btn)
        main_layout.addWidget(title_bar)
        
        # 中间内容区域 - 左右布局
        content_container = QFrame()
        content_container.setStyleSheet("background-color: transparent;")
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(15)
        
        # 左侧区域 - 图片和信息（占2/3）
        left_container = QFrame()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        
        # 图片和信息区域 - 左右布局
        img_info_container = QFrame()
        img_info_container.setObjectName("PanelBG")
        img_info_main_layout = QHBoxLayout(img_info_container)
        img_info_main_layout.setContentsMargins(4, 4, 4, 4)
        img_info_main_layout.setSpacing(4)
        
        # 分离主图（正面图/近视图）和其他视图
        main_view = None
        other_views = []
        for field, label, icon in views:
            # 角色用 front_view 作为主图，场景用 close_view 作为主图，道具用 front_view
            if field == "front_view" or field == "close_view":
                main_view = (field, label, icon)
            else:
                other_views.append((field, label, icon))
        
        # 左侧 - 主图（大）+ 信息
        if main_view:
            main_container = QFrame()
            main_container.setObjectName("PanelBG2")
            main_layout_inner = QVBoxLayout(main_container)
            main_layout_inner.setContentsMargins(3, 3, 3, 3)
            main_layout_inner.setSpacing(2)

            # 创建选项卡控件来切换正面图和五宫格
            from PyQt6.QtWidgets import QTabWidget
            self.main_image_tabs = QTabWidget()
            self.main_image_tabs.setStyleSheet("""
                QTabWidget::pane {
                    border: none;
                    background-color: transparent;
                }
                QTabBar::tab {
                    background-color: """ + _theme.color("panel") + """;
                    color: """ + _theme.color("text_sub") + """;
                    padding: 6px 12px;
                    margin-right: 2px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }
                QTabBar::tab:selected {
                    background-color: """ + _theme.color("warning") + """;
                    color: """ + _theme.color("panel") + """;
                    font-weight: bold;
                }
            """)

            # 正面图选项卡
            self.front_tab = QWidget()
            front_tab_layout = QVBoxLayout(self.front_tab)
            front_tab_layout.setContentsMargins(0, 0, 0, 0)
            front_tab_layout.setSpacing(0)

            # 图片容器（用于放置图片和删除按钮）
            main_img_container = QFrame()
            main_img_container.setFixedSize(260, 300)
            main_img_container.setStyleSheet("background:transparent;")

            main_btn = QPushButton(main_img_container)
            main_btn.setFixedSize(260, 300)
            main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            main_btn.setProperty("field", main_view[0])

            current = getattr(self.item_data, main_view[0], "")
            if current and os.path.exists(current):
                self.update_btn_large(main_btn, current)
            else:
                main_btn.setText(f"{main_view[2]}\n点击设置")
                main_btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:2px dashed " + _theme.color("border_strong") + ";border-radius:6px;font-size:12px;}QPushButton:hover{border-color:" + _theme.color("warning") + ";color:" + _theme.color("warning") + ";}")

            main_btn.clicked.connect(lambda checked, f=main_view[0]: self.select_image(f))
            self.image_buttons[main_view[0]] = main_btn

            # 移除按钮（放在右上角）- 必须在最后创建以确保在最上层
            if current:
                # 删除按钮 - 右上角（作为img_container的子控件，确保在最上层）
                self.del_btn_main = QPushButton("✕", main_img_container)
                self.del_btn_main.setFixedSize(22, 22)
                self.del_btn_main.move(233, 5)
                self.del_btn_main.setStyleSheet(_btn_style_delete_small())
                self.del_btn_main.setCursor(Qt.CursorShape.PointingHandCursor)
                self.del_btn_main.clicked.connect(lambda checked, f=main_view[0]: self.remove_image(f))
                # 必须调用show和raise_确保在最上层
                self.del_btn_main.show()
                self.del_btn_main.raise_()

                # 设为参考图按钮 - 左下角
                set_ref_btn = QPushButton("📎 参考", main_img_container)
                set_ref_btn.setFixedSize(65, 18)
                set_ref_btn.move(10, 277)
                set_ref_btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(155, 89, 182, 0.9); color: """ + _theme.color("accent_text") + """;
                        border: none;
                        border-radius: 9px;
                        font-size: 9px;
                        padding: 0px;
                    }
                    QPushButton:hover {
                        background: rgba(142, 68, 173, 1);
                    }
                """)
                set_ref_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                set_ref_btn.clicked.connect(lambda checked, f=main_view[0]: self.set_as_reference_image(f))
                set_ref_btn.show()
                set_ref_btn.raise_()

                # 查看大图按钮 - 右下角
                view_large_btn = QPushButton("🔍 查看", main_img_container)
                view_large_btn.setFixedSize(55, 18)
                view_large_btn.move(188, 277)
                view_large_btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(52, 152, 219, 0.9); color: """ + _theme.color("accent_text") + """;
                        border: none;
                        border-radius: 9px;
                        font-size: 9px;
                        padding: 0px;
                    }
                    QPushButton:hover {
                        background: rgba(41, 128, 185, 1);
                    }
                """)
                view_large_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                view_large_btn.clicked.connect(lambda checked, f=main_view[0]: self.view_large_image(f))
                view_large_btn.show()
                view_large_btn.raise_()

            front_tab_layout.addWidget(main_img_container, 0, Qt.AlignmentFlag.AlignCenter)

            # 五宫格选项卡（初始时隐藏，等生成后再显示）
            self.grid_tab = QWidget()
            grid_tab_layout = QVBoxLayout(self.grid_tab)
            grid_tab_layout.setContentsMargins(0, 0, 0, 0)
            grid_tab_layout.setSpacing(0)

            # 五宫格图片容器
            self.grid_img_container = QFrame()
            self.grid_img_container.setFixedSize(260, 300)
            self.grid_img_container.setStyleSheet("background:transparent;")

            self.grid_btn = QPushButton(self.grid_img_container)
            self.grid_btn.setFixedSize(260, 300)
            self.grid_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.grid_btn.setText("🎨\n五宫格图片\n点击上传")
            self.grid_btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:2px dashed " + _theme.color("border_strong") + ";border-radius:6px;font-size:12px;}QPushButton:hover{border-color:" + _theme.color("warning") + ";color:" + _theme.color("warning") + ";}")
            # 保存按钮引用，方便后续更新点击事件
            self.grid_image_btn = self.grid_btn
            self.grid_btn.clicked.connect(self.on_grid_image_clicked)

            grid_tab_layout.addWidget(self.grid_img_container, 0, Qt.AlignmentFlag.AlignCenter)

            # 添加选项卡
            self.main_image_tabs.addTab(self.front_tab, "正面图")
            self.main_image_tabs.addTab(self.grid_tab, "五宫格")

            # 默认选中正面图选项卡
            self.main_image_tabs.setCurrentIndex(0)

            main_layout_inner.addWidget(self.main_image_tabs)

            # 检查是否有已保存的五宫格图片，如果有则加载
            if self.item_type == "character":
                saved_grid_path = getattr(self.item_data, 'grid_1drag4_path', '')
                print(f"DEBUG init_ui: saved_grid_path = {saved_grid_path}")
                print(f"DEBUG init_ui: exists = {os.path.exists(saved_grid_path) if saved_grid_path else False}")
                if saved_grid_path and os.path.exists(saved_grid_path):
                    print(f"DEBUG init_ui: Scheduling load_saved_grid_image")
                    # 延迟加载，确保UI已完全创建
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(100, lambda: self.load_saved_grid_image(saved_grid_path))
            
            # 信息区域 - 放在主图下方
            info_widget = QWidget()
            info_layout = QHBoxLayout(info_widget)
            info_layout.setContentsMargins(0, 2, 0, 0)
            info_layout.setSpacing(4)
            
            info_layout.addWidget(QLabel("名称:"))
            self.name_edit = QLineEdit(self.item_data.name)
            self.name_edit.setStyleSheet("QLineEdit{padding:3px;background:" + _theme.color("panel") + "; color: " + _theme.color("text") + ";border:1px solid " + _theme.color("border_strong") + ";border-radius:3px;min-width:80px;font-size:11px;}")
            info_layout.addWidget(self.name_edit)
            
            if self.item_type == "character":
                info_layout.addWidget(QLabel("性别:"))
                self.gender_combo = QComboBox()
                self.gender_combo.addItems(["男性", "女性", "未知"])
                self.gender_combo.setCurrentText(self.item_data.gender or "未知")
                self.gender_combo.setStyleSheet("QComboBox{padding:3px;background:" + _theme.color("panel") + "; color: " + _theme.color("text") + ";border:1px solid " + _theme.color("border_strong") + ";border-radius:3px;min-width:45px;font-size:11px;}")
                info_layout.addWidget(self.gender_combo)
                
                info_layout.addWidget(QLabel("年龄:"))
                self.age_combo = QComboBox()
                self.age_combo.addItems(["青年", "少年", "中年", "老年", "儿童"])
                self.age_combo.setCurrentText(self.item_data.age or "青年")
                self.age_combo.setStyleSheet("QComboBox{padding:3px;background:" + _theme.color("panel") + "; color: " + _theme.color("text") + ";border:1px solid " + _theme.color("border_strong") + ";border-radius:3px;min-width:45px;font-size:11px;}")
                info_layout.addWidget(self.age_combo)
            
            main_layout_inner.addWidget(info_widget)
            img_info_main_layout.addWidget(main_container, stretch=1)
        
        # 右侧 - 其他4图（宫格）
        if other_views:
            grid_container = QFrame()
            grid_container.setStyleSheet("background-color: transparent;")
            grid_layout = QGridLayout(grid_container)
            grid_layout.setContentsMargins(0, 0, 0, 0)
            grid_layout.setSpacing(4)
            
            for idx, (field, label, icon) in enumerate(other_views[:4]):  # 最多4个
                row = idx // 2
                col = idx % 2
                
                view_container = QFrame()
                view_container.setObjectName("PanelBG2")
                view_layout = QVBoxLayout(view_container)
                view_layout.setSpacing(1)
                view_layout.setContentsMargins(2, 2, 2, 2)
                
                view_lbl = QLabel(label)
                view_lbl.setStyleSheet("color: " + _theme.color("warning") + "; font-weight: bold; font-size: 10px;")
                view_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                view_layout.addWidget(view_lbl)
                
                # 图片容器（用于放置图片和删除按钮）
                img_container = QFrame()
                img_container.setFixedSize(130, 150)
                img_container.setStyleSheet("background:transparent;")
                
                view_btn = QPushButton(img_container)
                view_btn.setFixedSize(130, 150)
                view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                view_btn.setProperty("field", field)
                
                current = getattr(self.item_data, field, "")
                if current and os.path.exists(current):
                    self.update_btn(view_btn, current)
                else:
                    view_btn.setText(f"{icon}")
                    view_btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:2px dashed " + _theme.color("border_strong") + ";border-radius:4px;font-size:16px;}QPushButton:hover{border-color:" + _theme.color("warning") + ";color:" + _theme.color("warning") + ";}")
                
                view_btn.clicked.connect(lambda checked, f=field: self.select_image(f))
                self.image_buttons[field] = view_btn
                
                # 移除按钮（放在右上角）- 必须在最后创建以确保在最上层
                if current:
                    del_btn = QPushButton("✕", img_container)
                    del_btn.setFixedSize(24, 24)
                    del_btn.move(104, 2)  # 右上角位置
                    del_btn.setStyleSheet("""
                        QPushButton {
                            background: rgba(231, 76, 60, 0.95); color: """ + _theme.color("accent_text") + """;
                            border: 2px solid white;
                            border-radius: 12px;
                            font-size: 10px;
                            font-weight: bold;
                            padding: 0px;
                        }
                        QPushButton:hover {
                            background: rgba(255, 0, 0, 1);
                            border-color: """ + _theme.color("warning") + """;
                        }
                        QPushButton:pressed {
                            background: rgba(192, 57, 43, 1);
                        }
                    """)
                    del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    del_btn.clicked.connect(lambda checked, f=field: self.remove_image(f))
                    del_btn.show()
                    del_btn.raise_()
                    
                    # 查看大图按钮（放在底部中央）
                    view_large_btn = QPushButton("🔍 查看", img_container)
                    view_large_btn.setFixedSize(50, 18)
                    view_large_btn.move(40, 128)
                    view_large_btn.setStyleSheet("""
                        QPushButton {
                            background: rgba(52, 152, 219, 0.85); color: """ + _theme.color("accent_text") + """;
                            border: 1px solid rgba(255,255,255,0.3);
                            border-radius: 9px;
                            font-size: 9px;
                            padding: 0px;
                        }
                        QPushButton:hover {
                            background: rgba(41, 128, 185, 1);
                            border: 1px solid white;
                        }
                    """)
                    view_large_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    view_large_btn.clicked.connect(lambda checked, f=field: self.view_large_image(f))
                    view_large_btn.show()
                    view_large_btn.raise_()
                
                view_layout.addWidget(img_container, 0, Qt.AlignmentFlag.AlignCenter)
                
                grid_layout.addWidget(view_container, row, col)
            
            img_info_main_layout.addWidget(grid_container, stretch=1)
        
        left_layout.addWidget(img_info_container)
        
        # 左侧占2/3
        content_layout.addWidget(left_container, stretch=2)
        
        # 右侧区域 - AI提示词（占1/3）
        right_container = QFrame()
        right_container.setObjectName("PanelBG")
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)
        
        # AI提示词标题栏（带清空按钮）
        ai_title_layout = QHBoxLayout()
        
        ai_title = QLabel("🤖 AI生成提示词")
        ai_title.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 14px; font-weight: bold;")
        ai_title_layout.addWidget(ai_title)
        
        ai_title_layout.addStretch()
        
        # 清空按钮
        clear_btn = QPushButton("清空")
        clear_btn.setStyleSheet(_btn_style_danger())
        clear_btn.clicked.connect(self.clear_ai_prompt)
        ai_title_layout.addWidget(clear_btn)
        
        right_layout.addLayout(ai_title_layout)
        
        # AI提示词编辑区 - 字体加大
        self.ai_prompt_edit = QTextEdit()
        self.ai_prompt_edit.setPlaceholderText("AI生成提示词将显示在这里...")
        # 显示已有的ai_prompt
        ai_prompt_text = getattr(self.item_data, 'ai_prompt', '') or ''
        self.ai_prompt_edit.setText(ai_prompt_text)
        self.ai_prompt_edit.setStyleSheet("""
            QTextEdit {
                padding: 10px;
                background: """ + _theme.color("panel2") + """;
                color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("panel2") + """;
                border-radius: 5px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        right_layout.addWidget(self.ai_prompt_edit, stretch=1)
        
        # 显示默认提示词按钮
        show_default_btn = QPushButton("🔄 显示默认提示词")
        show_default_btn.setStyleSheet(_btn_style_warning())
        show_default_btn.clicked.connect(self.show_default_ai_prompt)
        right_layout.addWidget(show_default_btn)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: " + _theme.color("panel2") + "; background-color: " + _theme.color("panel2") + ";")
        line.setFixedHeight(2)
        right_layout.addWidget(line)
        
        # 数量、比例和生图接口并列排列
        options_layout = QHBoxLayout()
        options_layout.setSpacing(10)
        
        # 生成数量选择
        count_widget = QWidget()
        count_layout = QHBoxLayout(count_widget)
        count_layout.setContentsMargins(0, 0, 0, 0)
        count_layout.setSpacing(5)
        count_layout.addWidget(QLabel("数量:"))
        self.ai_count_combo = QComboBox()
        self.ai_count_combo.addItems(["1", "2", "3", "4"])
        self.ai_count_combo.setCurrentText("1")
        self.ai_count_combo.setStyleSheet("QComboBox{padding:5px;background:" + _theme.color("panel2") + "; color: " + _theme.color("text") + ";border:1px solid " + _theme.color("border_strong") + ";border-radius:4px;}")
        count_layout.addWidget(self.ai_count_combo)
        options_layout.addWidget(count_widget)
        
        # 宽高比选择
        ratio_widget = QWidget()
        ratio_layout = QHBoxLayout(ratio_widget)
        ratio_layout.setContentsMargins(0, 0, 0, 0)
        ratio_layout.setSpacing(5)
        ratio_layout.addWidget(QLabel("比例:"))
        self.ai_ratio_combo = QComboBox()
        self.ai_ratio_combo.addItems(["9:16", "1:1", "16:9", "4:3", "3:4"])
        self.ai_ratio_combo.setCurrentText("9:16")
        self.ai_ratio_combo.setStyleSheet("QComboBox{padding:5px;background:" + _theme.color("panel2") + "; color: " + _theme.color("text") + ";border:1px solid " + _theme.color("border_strong") + ";border-radius:4px;}")
        ratio_layout.addWidget(self.ai_ratio_combo)
        options_layout.addWidget(ratio_widget)
        
        # 生图接口选择
        provider_widget = QWidget()
        provider_layout = QHBoxLayout(provider_widget)
        provider_layout.setContentsMargins(0, 0, 0, 0)
        provider_layout.setSpacing(5)
        provider_layout.addWidget(QLabel("接口:"))
        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.setMinimumWidth(120)
        self.ai_provider_combo.setStyleSheet("""
            QComboBox {
                padding: 5px;
                background: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                border-radius: 4px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                selection-background-color: """ + _theme.color("accent") + """;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
        """)
        self.load_image_providers()
        provider_layout.addWidget(self.ai_provider_combo)
        options_layout.addWidget(provider_widget)
        
        options_layout.addStretch()
        right_layout.addLayout(options_layout)
        
        # 生成视角选择区域
        view_container = QFrame()
        view_container.setObjectName("PanelBG2")
        view_layout = QVBoxLayout(view_container)
        view_layout.setContentsMargins(6, 6, 6, 6)
        view_layout.setSpacing(4)
        
        view_title = QLabel("🎯 生成视角")
        view_title.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 11px; font-weight: bold;")
        view_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view_layout.addWidget(view_title)
        
        # 根据类型创建视角选择复选框
        self.view_checkboxes = {}
        if self.item_type == "character":
            views = [
                ("front_view", "正面图"), ("back_view", "后面图"),
                ("right_side_view", "右侧面"), ("left_side_view", "左侧面"),
                ("top_view", "俯视图")
            ]
        elif self.item_type == "scene":
            views = [
                ("wide_view", "远视图"), ("medium_view", "中视图"),
                ("close_view", "近视图"), ("top_view", "俯视图"),
                ("side_view", "侧视图")
            ]
        else:  # prop
            views = [
                ("front_view", "正视图"), ("back_view", "后视图"),
                ("top_view", "上视图"), ("bottom_view", "下视图"),
                ("side_view", "侧视图")
            ]
        
        # 创建2列的网格布局
        view_grid = QGridLayout()
        view_grid.setSpacing(4)
        for idx, (field, label) in enumerate(views):
            row = idx // 2
            col = idx % 2
            checkbox = QCheckBox(label)
            checkbox.setStyleSheet("QCheckBox { color: " + _theme.color("text") + "; font-size: 11px; } QCheckBox::indicator { width: 14px; height: 14px; }")
            checkbox.setProperty("field", field)
            # 默认只选中第一个（正面图/近视图/正视图）
            checkbox.setChecked(idx == 0)
            self.view_checkboxes[field] = checkbox
            view_grid.addWidget(checkbox, row, col)
        
        view_layout.addLayout(view_grid)
        
        # ── 五宫格（整图含 5 个视角）──
        view_layout.addSpacing(4)
        self.one_drag_four_checkbox = QCheckBox("🏠 五宫格（一张图含 5 个角度）")
        self.one_drag_four_checkbox.setStyleSheet("""
            QCheckBox {
                color: """ + _theme.color("warning") + """;
                font-size: 12px;
                font-weight: bold;
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                border: 2px solid """ + _theme.color("border_strong") + """;
                border-radius: 3px;
                background-color: """ + _theme.color("panel2") + """;
            }
            QCheckBox::indicator:checked {
                background-color: """ + _theme.color("warning") + """;
                border: 2px solid """ + _theme.color("warning") + """;
            }
        """)
        self.one_drag_four_checkbox.setToolTip("生成1张包含5个角度的5宫格图片，生成结果将显示在左侧「五宫格」选项卡")
        view_layout.addWidget(self.one_drag_four_checkbox)

        # 全选/取消全选按钮
        select_all_layout = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        select_all_btn.setStyleSheet(_btn_style_primary())
        select_all_btn.clicked.connect(self.select_all_views)
        select_all_layout.addWidget(select_all_btn)
        
        clear_all_btn = QPushButton("取消全选")
        clear_all_btn.setStyleSheet(_btn_style_secondary())
        clear_all_btn.clicked.connect(self.clear_all_views)
        select_all_layout.addWidget(clear_all_btn)
        select_all_layout.addStretch()
        
        view_layout.addLayout(select_all_layout)
        
        # 参考图区域（与视角选择并列）
        ref_container = QFrame()
        ref_container.setStyleSheet("background-color: " + _theme.color("panel2") + "; border-radius: 4px;")
        ref_layout = QVBoxLayout(ref_container)
        ref_layout.setContentsMargins(6, 6, 6, 6)
        ref_layout.setSpacing(4)
        
        ref_title = QLabel("📎 参考图")
        ref_title.setStyleSheet("color: " + _theme.color("accent2") + "; font-size: 11px; font-weight: bold;")
        ref_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ref_layout.addWidget(ref_title)
        
        # 参考图显示按钮
        self.ref_image_btn = QPushButton()
        self.ref_image_btn.setFixedSize(90, 90)
        self.ref_image_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ref_image_path = ""
        
        # 检查是否有已设置的参考图
        if hasattr(self.item_data, 'reference_image') and self.item_data.reference_image and os.path.exists(self.item_data.reference_image):
            self.ref_image_path = self.item_data.reference_image
            self.update_ref_btn(self.ref_image_btn, self.ref_image_path)
        else:
            self.ref_image_btn.setText("📷\n点击选择")
            self.ref_image_btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:2px dashed " + _theme.color("border_strong") + ";border-radius:4px;font-size:10px;}QPushButton:hover{border-color:" + _theme.color("accent2") + ";color:" + _theme.color("accent2") + ";}")
        
        self.ref_image_btn.clicked.connect(self.select_ref_image)
        ref_layout.addWidget(self.ref_image_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 清除参考图按钮
        if self.ref_image_path:
            clear_ref_btn = QPushButton("✕ 清除")
            clear_ref_btn.setStyleSheet(_btn_style_danger())
            clear_ref_btn.clicked.connect(self.clear_ref_image)
            ref_layout.addWidget(clear_ref_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 将视角选择和参考图并列显示（各占1/2）
        view_ref_layout = QHBoxLayout()
        view_ref_layout.addWidget(view_container, stretch=1)
        view_ref_layout.addWidget(ref_container, stretch=1)
        right_layout.addLayout(view_ref_layout)
        
        # AI生成按钮和进度条容器
        self.ai_btn_container = QWidget()
        ai_btn_layout = QVBoxLayout(self.ai_btn_container)
        ai_btn_layout.setContentsMargins(0, 0, 0, 0)
        ai_btn_layout.setSpacing(5)
        
        # AI生成按钮
        self.ai_btn = QPushButton("🤖 开始生成图片")
        self.ai_btn.setStyleSheet(_btn_style_primary())
        self.ai_btn.clicked.connect(self.start_ai_generate)
        ai_btn_layout.addWidget(self.ai_btn)
        
        # 进度条（初始隐藏）
        self.ai_progress_bar = QProgressBar()
        self.ai_progress_bar.setRange(0, 100)
        self.ai_progress_bar.setValue(0)
        self.ai_progress_bar.setTextVisible(True)
        self.ai_progress_bar.setFormat("准备生成...")
        self.ai_progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: """ + _theme.color("panel") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                border-radius: 5px;
                padding: 2px;
                text-align: center; color: """ + _theme.color("text") + """;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background-color: """ + _theme.color("accent") + """;
                border-radius: 3px;
            }
        """)
        self.ai_progress_bar.hide()
        ai_btn_layout.addWidget(self.ai_progress_bar)
        
        right_layout.addWidget(self.ai_btn_container)
        
        # 右侧占1/3
        content_layout.addWidget(right_container, stretch=1)
        
        main_layout.addWidget(content_container, stretch=1)
        
        # 按钮区域（底部）
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 8, 0, 0)
        
        lib_txt = "📚 素材库"
        lib_btn = QPushButton(lib_txt)
        lib_btn.setStyleSheet(_btn_style_purple())
        lib_btn.clicked.connect(self.open_library)
        btn_layout.addWidget(lib_btn)
        
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(100, 38)
        cancel_btn.setStyleSheet(_btn_style_secondary())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("保存")
        save_btn.setFixedSize(100, 38)
        save_btn.setStyleSheet(_btn_style_accent())
        save_btn.clicked.connect(self.save_changes)
        btn_layout.addWidget(save_btn)
        
        main_layout.addWidget(btn_container)
        # 背景交由全局主题管理
    
    def create_image_column(self, field, label, icon):
        col = QVBoxLayout()
        col.setSpacing(6)
        
        lbl = QLabel(label)
        lbl.setStyleSheet("color: " + _theme.color("warning") + "; font-weight: bold; font-size: 12px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(lbl)
        
        img_btn = QPushButton()
        img_btn.setFixedSize(160, 180)
        img_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        img_btn.setProperty("field", field)
        
        current = getattr(self.item_data, field, "")
        if current and os.path.exists(current):
            self.update_btn(img_btn, current)
        else:
            img_btn.setText(f"{icon}\n点击设置")
            img_btn.setStyleSheet("QPushButton{background:" + _theme.color("panel2") + ";color:" + _theme.color("text_sub") + ";border:2px dashed " + _theme.color("border_strong") + ";border-radius:8px;font-size:12px;}QPushButton:hover{border-color:" + _theme.color("warning") + ";color:" + _theme.color("warning") + ";}")
        
        img_btn.clicked.connect(lambda checked, f=field: self.select_image(f))
        self.image_buttons[field] = img_btn
        col.addWidget(img_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        if current:
            del_btn = QPushButton("移除")
            del_btn.setStyleSheet("QPushButton{background:" + _theme.color("danger") + "; color: " + _theme.color("accent_text") + ";border:none;border-radius:4px;padding:5px 10px;font-size:11px;}QPushButton:hover{background:" + _theme.color("danger") + ";}")
            del_btn.clicked.connect(lambda checked, f=field: self.remove_image(f))
            col.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        col.addStretch()
        return col
    
    def update_btn(self, btn, path):
        """更新小图按钮（宫格图）"""
        pix = QPixmap(path)
        # 使用 KeepAspectRatio 保持完整图片
        scaled = pix.scaled(110, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        btn.setIcon(QIcon(scaled))
        btn.setIconSize(scaled.size())
        btn.setText("")
        btn.setStyleSheet("QPushButton{background:" + _theme.color("panel2") + ";border:2px solid " + _theme.color("success") + ";border-radius:4px;padding:6px;}QPushButton:hover{border-color:" + _theme.color("success") + ";}")
    
    def update_btn_large(self, btn, path):
        """更新大图按钮（正面图）"""
        pix = QPixmap(path)
        print(f"DEBUG: Original image size: {pix.width()}x{pix.height()}")
        # 按钮尺寸 260x300，减去边框和padding后，图片区域约 250x290
        # 使用 KeepAspectRatio 保持完整图片比例
        scaled = pix.scaled(250, 290, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        print(f"DEBUG: Scaled image size: {scaled.width()}x{scaled.height()}")
        # 使用 QIcon 并设置图标大小
        icon = QIcon(scaled)
        btn.setIcon(icon)
        btn.setIconSize(scaled.size())
        print(f"DEBUG: Icon size set to: {scaled.size().width()}x{scaled.size().height()}")
        btn.setText("")
        # 设置样式，确保图标显示正确
        btn.setStyleSheet("""
            QPushButton {
                background: """ + _theme.color("panel") + """;
                border: 2px solid """ + _theme.color("success") + """;
                border-radius: 6px;
                padding: 2px;
            }
            QPushButton:hover {
                border-color: """ + _theme.color("success") + """;
            }
            QPushButton::icon {
                padding: 0px;
            }
        """)
    
    def update_ref_btn(self, btn, path):
        """更新参考图按钮"""
        pix = QPixmap(path)
        btn_size = btn.size()
        scaled = pix.scaled(btn_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        btn.setIcon(QIcon(scaled))
        btn.setIconSize(scaled.size())
        btn.setText("")
        btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";border:2px solid " + _theme.color("accent2") + ";border-radius:4px;}QPushButton:hover{border-color:" + _theme.color("accent2") + ";}")
    
    def select_ref_image(self):
        """选择参考图"""
        path, _ = QFileDialog.getOpenFileName(self, "选择参考图", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.ref_image_path = path
            self.update_ref_btn(self.ref_image_btn, path)
            # 重新加载参考图区域以显示清除按钮
            self.refresh_ref_area()
    
    def clear_ref_image(self):
        """清除参考图"""
        self.ref_image_path = ""
        self.ref_image_btn.setText("📷\n点击选择")
        self.ref_image_btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:2px dashed " + _theme.color("border_strong") + ";border-radius:4px;font-size:11px;}QPushButton:hover{border-color:" + _theme.color("accent2") + ";color:" + _theme.color("accent2") + ";}")
        self.ref_image_btn.setIcon(QIcon())
        # 重新加载参考图区域以隐藏清除按钮
        self.refresh_ref_area()
    
    def refresh_ref_area(self):
        """刷新参考图区域（用于显示/隐藏清除按钮）"""
        # 这里可以通过信号槽机制或者重新创建UI来实现
        # 简化处理：直接更新按钮状态
        pass
    
    def select_all_views(self):
        """全选所有视角"""
        for checkbox in self.view_checkboxes.values():
            checkbox.setChecked(True)
    
    def clear_all_views(self):
        """取消全选所有视角"""
        for checkbox in self.view_checkboxes.values():
            checkbox.setChecked(False)
    
    def get_selected_views(self):
        """获取用户选择的视角列表"""
        selected = []
        for field, checkbox in self.view_checkboxes.items():
            if checkbox.isChecked():
                selected.append(field)
        return selected
    
    def clear_ai_prompt(self):
        """清空AI提示词文本框"""
        self.ai_prompt_edit.clear()
    
    def set_as_reference_image(self, field):
        """将指定字段的图片设为参考图"""
        image_path = getattr(self.item_data, field, "")
        if image_path and os.path.exists(image_path):
            self.ref_image_path = image_path
            self.update_ref_btn(self.ref_image_btn, image_path)
            QMessageBox.information(self, "成功", "已设为参考图！")
        else:
            QMessageBox.warning(self, "错误", "图片不存在！")
    
    def view_large_image(self, field):
        """查看大图"""
        image_path = getattr(self.item_data, field, "")
        if not image_path or not os.path.exists(image_path):
            QMessageBox.warning(self, "错误", "图片不存在！")
            return
        
        # 创建大图查看对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("查看大图")
        dialog.setObjectName("ThemedDialog")
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 加载图片
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "错误", "无法加载图片！")
            return
        
        # 创建标签显示图片
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 计算缩放后的尺寸（最大800x600）
        screen_width = 800
        screen_height = 600
        img_width = pixmap.width()
        img_height = pixmap.height()
        
        # 按比例缩放
        if img_width > screen_width or img_height > screen_height:
            pixmap = pixmap.scaled(screen_width, screen_height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        img_label.setPixmap(pixmap)
        layout.addWidget(img_label)
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet("""
            QPushButton {
                background: """ + _theme.color("text_sub") + """; color: """ + _theme.color("text") + """;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: """ + _theme.color("text_sub") + """;
            }
        """)
        close_btn.clicked.connect(dialog.close)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # 设置对话框大小
        dialog.resize(pixmap.width() + 40, pixmap.height() + 80)
        dialog.exec()
    
    def load_image_providers(self):
        """加载生图接口列表"""
        self.ai_provider_combo.clear()
        
        try:
            from core.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            configs = config_manager.get("api_configs", [])
            
            # 筛选图片生成类型的配置
            image_configs = [c for c in configs if c.get("type") == "Image"]
            
            default_index = 0
            for i, config in enumerate(image_configs):
                name = config.get("name", f"{config.get('provider')} - {config.get('model')}")
                self.ai_provider_combo.addItem(name, config)
                if config.get("is_default"):
                    default_index = i
            
            # 如果没有配置，添加默认选项
            if self.ai_provider_combo.count() == 0:
                self.ai_provider_combo.addItem("默认 (DALL-E)", {
                    "provider": "openai",
                    "model": "dall-e-3",
                    "api_key": "",
                    "base_url": ""
                })
            else:
                self.ai_provider_combo.setCurrentIndex(default_index)
                
        except Exception as e:
            print(f"加载生图接口失败: {e}")
            # 添加默认选项
            self.ai_provider_combo.addItem("默认 (DALL-E)", {
                "provider": "openai",
                "model": "dall-e-3"
            })
    
    def select_image(self, field):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            ext = os.path.splitext(path)[1]
            new_name = f"{self.item_type}_{uuid.uuid4()}{ext}"
            dest = os.path.join(self.storage_path, new_name)
            shutil.copy2(path, dest)
            self.new_image_paths[field] = dest
            if field in self.image_buttons:
                # 主图（front_view 或 close_view）使用大图更新方法
                if field == "front_view" or field == "close_view":
                    self.update_btn_large(self.image_buttons[field], dest)
                else:
                    self.update_btn(self.image_buttons[field], dest)

    def select_grid_image(self):
        """选择五宫格图片"""
        path, _ = QFileDialog.getOpenFileName(self, "选择五宫格图片", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            ext = os.path.splitext(path)[1]
            new_name = f"{self.item_type}_grid_{uuid.uuid4()}{ext}"
            dest = os.path.join(self.storage_path, new_name)
            shutil.copy2(path, dest)

            # 保存路径
            self.item_data.grid_1drag4_path = dest
            self.new_image_paths["grid_1drag4_path"] = dest

            # 更新五宫格选项卡显示
            self.add_grid_image_tab(dest)

            QMessageBox.information(self, "成功", "五宫格图片已上传！")

    def on_grid_image_clicked(self):
        """五宫格图片点击事件 - 始终上传替换图片"""
        self.select_grid_image()

    def remove_image(self, field):
        # 弹窗确认
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这张图片吗？\n\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.new_image_paths[field] = None
        if field in self.image_buttons:
            btn = self.image_buttons[field]
            icon = "👤" if self.item_type == "character" else ("🏞️" if self.item_type == "scene" else "🎁")
            btn.setIcon(QIcon())
            btn.setText(f"{icon}\n点击设置")
            btn.setStyleSheet("QPushButton{background:" + _theme.color("panel2") + ";color:" + _theme.color("text_sub") + ";border:2px dashed " + _theme.color("border_strong") + ";border-radius:8px;font-size:12px;}QPushButton:hover{border-color:" + _theme.color("warning") + ";color:" + _theme.color("warning") + ";}")
    
    def open_library(self):
        if self.item_type == "character":
            from ui.character_library_dialog import CharacterLibraryDialog
            temp = Character(id=self.item_data.id, name=self.item_data.name, age=self.item_data.age or "青年",
                gender=self.item_data.gender or "未知", appearance_features="", style_description="",
                avatar_path=self.item_data.front_view or self.item_data.avatar_path or "")
            dialog = CharacterLibraryDialog(temp, self)
            if dialog.exec() and temp.avatar_path:
                self.item_data.front_view = temp.avatar_path
                self.item_data.avatar_path = temp.avatar_path
                if "front_view" in self.image_buttons:
                    self.update_btn(self.image_buttons["front_view"], self.item_data.front_view)
                self.name_edit.setText(temp.name)
                self.gender_combo.setCurrentText(temp.gender)
                self.age_combo.setCurrentText(temp.age)
        elif self.item_type == "scene":
            from ui.scene_library_dialog import SceneLibraryDialog
            temp = Scene(id=self.item_data.id, name=self.item_data.name, description=self.item_data.description or "",
                reference_image=getattr(self.item_data, 'reference_image', '') or getattr(self.item_data, 'close_view', '') or "")
            dialog = SceneLibraryDialog(temp, self)
            if dialog.exec() and temp.reference_image:
                self.item_data.reference_image = temp.reference_image
                if "close_view" in self.image_buttons:
                    self.update_btn(self.image_buttons["close_view"], temp.reference_image)
                self.name_edit.setText(temp.name)
        else:
            from ui.prop_library_dialog import PropLibraryDialog
            temp = Prop(id=self.item_data.id, name=self.item_data.name, description=self.item_data.description or "",
                reference_image=getattr(self.item_data, 'reference_image', '') or getattr(self.item_data, 'front_view', '') or "")
            dialog = PropLibraryDialog(temp, self)
            if dialog.exec() and temp.reference_image:
                self.item_data.reference_image = temp.reference_image
                if "front_view" in self.image_buttons:
                    self.update_btn(self.image_buttons["front_view"], temp.reference_image)
                self.name_edit.setText(temp.name)
    
    def save_changes(self):
        try:
            print(f"DEBUG: save_changes called, item_type={self.item_type}")
            self.item_data.name = self.name_edit.text()
            if self.item_type == "character":
                self.item_data.gender = self.gender_combo.currentText()
                self.item_data.age = self.age_combo.currentText()
            
            # 保存AI提示词
            self.item_data.ai_prompt = self.ai_prompt_edit.toPlainText()
            
            print(f"DEBUG: new_image_paths = {self.new_image_paths}")
            print(f"DEBUG: item_data type = {type(self.item_data)}")
            print(f"DEBUG: item_data has grid_1drag4_path = {hasattr(self.item_data, 'grid_1drag4_path')}")
            if hasattr(self.item_data, 'grid_1drag4_path'):
                print(f"DEBUG: item_data.grid_1drag4_path before save = {self.item_data.grid_1drag4_path}")

            # 处理所有新图片路径
            for field, path in self.new_image_paths.items():
                print(f"DEBUG: Processing field={field}, path={path}")
                if path is None:
                    # 删除图片
                    old = getattr(self.item_data, field, "")
                    if old and os.path.exists(old):
                        try: 
                            os.remove(old)
                            print(f"DEBUG: Removed old file {old}")
                        except Exception as e: 
                            print(f"DEBUG: Error removing file {old}: {e}")
                    setattr(self.item_data, field, "")
                elif path:
                    # 设置新图片路径
                    setattr(self.item_data, field, path)
                    print(f"DEBUG: Set {field} = {path}")
            
            # 同步 avatar_path 和 reference_image
            if self.item_type == "character":
                if self.item_data.front_view:
                    self.item_data.avatar_path = self.item_data.front_view
                    print(f"DEBUG: Set avatar_path = {self.item_data.front_view}")
            elif self.item_type == "scene":
                if self.item_data.close_view:
                    self.item_data.reference_image = self.item_data.close_view
                    print(f"DEBUG: Set reference_image = {self.item_data.close_view}")
            elif self.item_type == "prop":
                if self.item_data.front_view:
                    self.item_data.reference_image = self.item_data.front_view
                    print(f"DEBUG: Set reference_image = {self.item_data.front_view}")
            
            # 确保 project_id 被设置
            if hasattr(self.item_data, 'project_id') and not self.item_data.project_id:
                # 从 storage_path 推断 project_id
                project_id = os.path.basename(os.path.dirname(self.storage_path))
                self.item_data.project_id = project_id
                print(f"DEBUG: Set project_id = {project_id}")
            
            print(f"DEBUG: Saving to {self.storage_path}")
            if hasattr(self.item_data, 'grid_1drag4_path'):
                print(f"DEBUG: item_data.grid_1drag4_path after processing = {self.item_data.grid_1drag4_path}")
            save_result = self.item_data.save(self.storage_path)
            print(f"DEBUG: save_result = {save_result}")
            
            if save_result:
                self.accept()
            else:
                QMessageBox.warning(self, "错误", "保存失败，请稍后重试")
        except Exception as e:
            print(f"保存修改失败: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "错误", f"保存修改时出现错误: {str(e)}")
    
    def show_default_ai_prompt(self):
        """显示默认AI提示词（恢复创建项目时AI自动生成的默认提示词）"""
        try:
            # 从item_data中获取创建时保存的default_ai_prompt
            default_prompt = getattr(self.item_data, 'default_ai_prompt', '')
            
            if default_prompt and default_prompt.strip():
                self.ai_prompt_edit.setText(default_prompt)
                QMessageBox.information(self, "成功", "已恢复创建项目时的默认提示词！")
            else:
                QMessageBox.warning(self, "提示", "没有找到创建项目时保存的默认提示词。\n\n请先使用AI生成功能创建默认提示词。")
                
        except Exception as e:
            print(f"显示默认提示词失败: {e}")
            QMessageBox.warning(self, "错误", f"显示默认提示词失败: {str(e)}")
    
    def start_ai_generate(self):
        """直接开始AI生成图片（不弹窗）"""
        # 获取参数
        ratio = self.ai_ratio_combo.currentText()
        ref_image = getattr(self, 'ref_image_path', '')
        provider_config = self.ai_provider_combo.currentData() or {}
        
        # 获取提示词
        prompt = self.ai_prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "提示", "请先生成或输入AI提示词！")
            return
        
        # 检查是否启用1拖4模式
        use_one_drag_four = hasattr(self, 'one_drag_four_checkbox') and self.one_drag_four_checkbox.isChecked()
        
        if use_one_drag_four:
            # 1拖4模式：生成一张包含5个角度的五宫格图片
            self.do_one_drag_four_generate(prompt, ratio, ref_image, provider_config)
        else:
            # 普通模式：生成用户选择的视角
            selected_views = self.get_selected_views()
            if not selected_views:
                QMessageBox.warning(self, "提示", "请至少选择一个要生成的视角！")
                return
            
            # 构建视角名称映射
            view_names = {
                "front_view": "正面图", "back_view": "后面图/后视图",
                "right_side_view": "右侧面", "left_side_view": "左侧面",
                "top_view": "俯视图/上视图", "bottom_view": "下视图",
                "wide_view": "远视图", "medium_view": "中视图",
                "close_view": "近视图", "side_view": "侧视图"
            }
            selected_view_names = [view_names.get(v, v) for v in selected_views]
            
            # 确认生成
            reply = QMessageBox.question(
                self,
                "确认生成",
                f"将使用以下参数生成图片：\n\n"
                f"生成视角: {', '.join(selected_view_names)}\n"
                f"数量: {len(selected_views)} 张\n"
                f"比例: {ratio}\n"
                f"接口: {self.ai_provider_combo.currentText()}\n\n"
                f"是否开始生成？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            # 执行生成
            self.do_ai_generate(prompt, selected_views, ratio, ref_image, provider_config)
    
    def do_one_drag_four_generate(self, prompt, ratio, ref_image, provider_config):
        """执行五宫格生成：分视角生成 5 张图后本地拼接（不再依赖模型排格，保证永远只有 5 格）"""
        try:
            from ai_engine.image_gen.image_client import ImageGenClient
            from ai_engine.image_gen.character_grid_generator import CharacterGridGenerator

            # 获取接口配置
            api_key = provider_config.get("api_key", "")
            base_url = provider_config.get("base_url", "")
            model = provider_config.get("model", "dall-e-3")
            provider = provider_config.get("provider", "openai")

            if not api_key or api_key == "sk-placeholder":
                # ComfyUI 不需要 API Key，跳过检查
                if "comfy" not in provider.lower():
                    QMessageBox.warning(self, "错误", "请先配置图片生成API密钥")
                    return

            # 确认生成
            reply = QMessageBox.question(
                self,
                "确认生成",
                f"将使用五宫格模式生成图片：\n\n"
                f"生成内容: 5个角度的角色参考图（正面/侧面/背面/3-4侧面/特写）\n"
                f"方式: 分视角生成 5 张后自动拼接，布局固定为 1+4\n"
                f"比例: {ratio}\n"
                f"接口: {self.ai_provider_combo.currentText()}\n\n"
                f"是否开始生成？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            # 显示进度条，禁用按钮
            self.ai_btn.setEnabled(False)
            self.ai_btn.setText("生成五宫格...")
            self.ai_progress_bar.show()
            self.ai_progress_bar.setRange(0, 100)
            self.ai_progress_bar.setValue(0)
            self.ai_progress_bar.setFormat("准备生成...")

            client = ImageGenClient(api_key, base_url, model, provider, api_config=provider_config)

            ref_images = [ref_image] if ref_image else None
            gen_settings = {
                "aspect_ratio": ratio,
                "size": ratio,
                "quality": "standard",
                # 负向提示词：排除跨视角漂移（不同人/不同服装/不同脸型）
                "negative_prompt": ("different person, different face, different outfit, "
                                    "inconsistent appearance, changed hairstyle, changed clothing, "
                                    "different footwear, different shoes, exaggerated expression, "
                                    "text, watermark, subtitle, caption, letters, numbers, "
                                    "chinese characters, logo, signature, blurry, low quality"),
            }

            # 五宫格拼接输出路径
            grid_output_path = os.path.join(self.storage_path, f"{self.item_data.id}_grid_1drag4.png")

            # 分视角生成：正面先生成，之后自动作为后续视角的参考图（保持同一角色外观）
            fields = [f for f, _, _ in CharacterGridGenerator.GRID_VIEWS]
            self.worker = ImageGenerationWorker(
                self.item_type, fields, len(fields), prompt, ratio,
                ref_images, gen_settings, self.storage_path, client
            )
            self.worker.grid_output_path = grid_output_path
            self.worker.chain_reference = True
            # 身份锁定：所有视角共享同一段一致性约束，压住脸型/发型/服装漂移
            self.worker.consistency_suffix = (
                "same exact character, identical face, identical hairstyle, identical hair color, "
                "identical outfit and accessories, identical footwear and shoes, "
                "identical body proportions, same neutral facial expression in every view, "
                "consistent appearance across all views, character reference sheet"
            )

            # 连接信号
            self.worker.progress_signal.connect(self.on_generation_progress)
            self.worker.finished_signal.connect(self.on_one_drag_four_finished)
            self.worker.error_signal.connect(self.on_generation_error)

            # 启动线程
            self.worker.start()

        except Exception as e:
            QMessageBox.warning(self, "错误", f"生成失败: {str(e)}")
            print(f"五宫格生成失败: {e}")
            self.reset_generation_ui()
    
    def on_one_drag_four_finished(self, generated_images, success_count, failed_fields):
        """1拖4生成完成回调"""
        self.ai_progress_bar.setValue(100)
        self.ai_progress_bar.setFormat("生成完成！")

        print(f"DEBUG: on_one_drag_four_finished called")
        print(f"DEBUG: generated_images = {generated_images}")
        print(f"DEBUG: success_count = {success_count}")

        if success_count > 0 and "grid_1drag4" in generated_images:
            grid_path = generated_images["grid_1drag4"]
            print(f"DEBUG: grid_path = {grid_path}")
            if grid_path and os.path.exists(grid_path):
                # 保存1拖4图片路径 - 使用正确的字段名 grid_1drag4_path
                self.item_data.grid_1drag4_path = grid_path
                self.new_image_paths["grid_1drag4_path"] = grid_path
                print(f"DEBUG: Set new_image_paths['grid_1drag4_path'] = {grid_path}")
                print(f"DEBUG: new_image_paths = {self.new_image_paths}")

                # 添加选项卡显示1拖4图片（不覆盖正面图）
                self.add_grid_image_tab(grid_path)

                QMessageBox.information(self, "成功", "五宫格图片生成成功！\n\n请点击'五宫格'选项卡查看完整布局。")
            else:
                QMessageBox.warning(self, "失败", "图片生成失败，请检查API配置")
        else:
            QMessageBox.warning(self, "失败", "五宫格图片生成失败，请检查API配置")

        self.reset_generation_ui()
    
    def load_saved_grid_image(self, grid_image_path):
        """加载已保存的五宫格图片"""
        try:
            from PyQt6.QtGui import QPixmap
            from PyQt6.QtCore import Qt

            print(f"DEBUG load_saved_grid_image: grid_image_path = {grid_image_path}")
            print(f"DEBUG load_saved_grid_image: hasattr grid_tab = {hasattr(self, 'grid_tab')}")
            if hasattr(self, 'grid_tab'):
                print(f"DEBUG load_saved_grid_image: grid_tab is not None = {self.grid_tab is not None}")

            # 检查是否存在五宫格选项卡
            if not hasattr(self, 'grid_tab') or self.grid_tab is None:
                print(f"DEBUG load_saved_grid_image: grid_tab not available, returning")
                return

            # 清空五宫格选项卡的现有内容
            grid_layout = self.grid_tab.layout()
            if grid_layout:
                while grid_layout.count():
                    item = grid_layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()

            # 创建新的图片容器
            grid_img_container = QFrame()
            grid_img_container.setFixedSize(260, 300)
            grid_img_container.setStyleSheet("background:transparent;")

            # 创建图片按钮
            grid_btn = QPushButton(grid_img_container)
            grid_btn.setFixedSize(260, 300)
            grid_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            # 加载并显示图片
            pixmap = QPixmap(grid_image_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(250, 290, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon = QIcon(scaled_pixmap)
                grid_btn.setIcon(icon)
                grid_btn.setIconSize(scaled_pixmap.size())
                grid_btn.setText("")
                grid_btn.setStyleSheet("""
                    QPushButton {
                        background: """ + _theme.color("panel") + """;
                        border: 2px solid """ + _theme.color("success") + """;
                        border-radius: 6px;
                        padding: 2px;
                    }
                    QPushButton:hover {
                        border-color: """ + _theme.color("success") + """;
                    }
                """)

                # 点击上传替换图片
                grid_btn.clicked.connect(self.select_grid_image)

                # 添加删除按钮
                del_btn = QPushButton("✕", grid_img_container)
                del_btn.setFixedSize(24, 24)
                del_btn.move(232, 4)
                del_btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(192, 57, 43, 0.9); color: """ + _theme.color("accent_text") + """;
                        border: 2px solid white;
                        border-radius: 12px;
                        font-size: 10px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background: rgba(231, 76, 60, 1);
                        border-color: """ + _theme.color("warning") + """;
                    }
                """)
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.clicked.connect(lambda checked, p=grid_image_path: self.remove_grid_image(p))
                del_btn.show()
                del_btn.raise_()

                # 添加查看大图按钮
                view_large_btn = QPushButton("🔍 查看", grid_img_container)
                view_large_btn.setFixedSize(70, 22)
                view_large_btn.move(180, 268)
                view_large_btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(52, 152, 219, 0.9); color: """ + _theme.color("accent_text") + """;
                        border: none;
                        border-radius: 4px;
                        padding: 2px 6px;
                        font-size: 9px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background: rgba(41, 128, 185, 1);
                    }
                """)
                view_large_btn.clicked.connect(lambda checked, p=grid_image_path: self.view_large_image_by_path(p))
                view_large_btn.raise_()

            grid_layout.addWidget(grid_img_container, 0, Qt.AlignmentFlag.AlignCenter)

            # 保存五宫格图片路径
            self.grid_image_path = grid_image_path
            # 同时添加到 new_image_paths，确保保存时能正确处理
            self.new_image_paths["grid_1drag4_path"] = grid_image_path

        except Exception as e:
            print(f"加载已保存的五宫格图片失败: {e}")
            import traceback
            traceback.print_exc()

    def add_grid_image_tab(self, grid_image_path):
        """在五宫格选项卡中显示生成的图片"""
        try:
            from PyQt6.QtGui import QPixmap
            from PyQt6.QtCore import Qt

            # 检查是否存在五宫格选项卡
            if not hasattr(self, 'grid_tab') or self.grid_tab is None:
                print("五宫格选项卡不存在")
                return

            # 清空五宫格选项卡的现有内容
            grid_layout = self.grid_tab.layout()
            if grid_layout:
                # 移除所有现有控件
                while grid_layout.count():
                    item = grid_layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()

            # 创建新的图片容器
            grid_img_container = QFrame()
            grid_img_container.setFixedSize(260, 300)
            grid_img_container.setStyleSheet("background:transparent;")

            # 创建图片按钮
            grid_btn = QPushButton(grid_img_container)
            grid_btn.setFixedSize(260, 300)
            grid_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            # 加载并显示图片
            pixmap = QPixmap(grid_image_path)
            if not pixmap.isNull():
                # 缩放图片以适应按钮大小
                scaled_pixmap = pixmap.scaled(250, 290, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon = QIcon(scaled_pixmap)
                grid_btn.setIcon(icon)
                grid_btn.setIconSize(scaled_pixmap.size())
                grid_btn.setText("")
                grid_btn.setStyleSheet("""
                    QPushButton {
                        background: """ + _theme.color("panel") + """;
                        border: 2px solid """ + _theme.color("success") + """;
                        border-radius: 6px;
                        padding: 2px;
                    }
                    QPushButton:hover {
                        border-color: """ + _theme.color("success") + """;
                    }
                """)

                # 点击上传替换图片
                grid_btn.clicked.connect(self.select_grid_image)

                # 添加删除按钮
                del_btn = QPushButton("✕", grid_img_container)
                del_btn.setFixedSize(24, 24)
                del_btn.move(232, 4)
                del_btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(192, 57, 43, 0.9); color: """ + _theme.color("accent_text") + """;
                        border: 2px solid white;
                        border-radius: 12px;
                        font-size: 10px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background: rgba(231, 76, 60, 1);
                        border-color: """ + _theme.color("warning") + """;
                    }
                """)
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.clicked.connect(lambda checked, p=grid_image_path: self.remove_grid_image(p))
                del_btn.show()
                del_btn.raise_()

                # 添加查看大图按钮
                view_large_btn = QPushButton("🔍 查看", grid_img_container)
                view_large_btn.setFixedSize(70, 22)
                view_large_btn.move(180, 268)
                view_large_btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(52, 152, 219, 0.9); color: """ + _theme.color("accent_text") + """;
                        border: none;
                        border-radius: 4px;
                        padding: 2px 6px;
                        font-size: 9px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background: rgba(41, 128, 185, 1);
                    }
                """)
                view_large_btn.clicked.connect(lambda checked, p=grid_image_path: self.view_large_image_by_path(p))
                view_large_btn.raise_()

            # 添加到布局
            grid_layout.addWidget(grid_img_container, 0, Qt.AlignmentFlag.AlignCenter)

            # 保存五宫格图片路径
            self.grid_image_path = grid_image_path
            # 同时添加到 new_image_paths，确保保存时能正确处理
            self.new_image_paths["grid_1drag4_path"] = grid_image_path

            # 切换到五宫格选项卡
            if hasattr(self, 'main_image_tabs') and self.main_image_tabs:
                self.main_image_tabs.setCurrentIndex(1)  # 切换到五宫格选项卡

        except Exception as e:
            print(f"添加五宫格图片失败: {e}")
            import traceback
            traceback.print_exc()
    
    def view_large_image_by_path(self, image_path):
        """通过路径查看大图"""
        if not image_path or not os.path.exists(image_path):
            QMessageBox.warning(self, "错误", "图片不存在！")
            return

        # 创建大图查看对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("查看大图")
        dialog.setObjectName("ThemedDialog")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)

        # 加载图片
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "错误", "无法加载图片！")
            return

        # 创建标签显示图片
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 计算缩放后的尺寸（最大800x600）
        screen_width = 800
        screen_height = 600
        img_width = pixmap.width()
        img_height = pixmap.height()

        # 按比例缩放
        if img_width > screen_width or img_height > screen_height:
            pixmap = pixmap.scaled(screen_width, screen_height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        img_label.setPixmap(pixmap)
        layout.addWidget(img_label)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet("""
            QPushButton {
                background: """ + _theme.color("text_sub") + """; color: """ + _theme.color("text") + """;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: """ + _theme.color("text_sub") + """;
            }
        """)
        close_btn.clicked.connect(dialog.close)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 设置对话框大小
        dialog.resize(pixmap.width() + 40, pixmap.height() + 80)
        dialog.exec()

    def remove_grid_image(self, image_path):
        """删除五宫格图片"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除五宫格图片吗？\n\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # 删除文件
            if os.path.exists(image_path):
                os.remove(image_path)

            # 清空五宫格选项卡
            if hasattr(self, 'grid_tab') and self.grid_tab:
                grid_layout = self.grid_tab.layout()
                if grid_layout:
                    while grid_layout.count():
                        item = grid_layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()

                # 重新创建初始状态
                self.grid_img_container = QFrame()
                self.grid_img_container.setFixedSize(260, 300)
                self.grid_img_container.setStyleSheet("background:transparent;")

                self.grid_btn = QPushButton(self.grid_img_container)
                self.grid_btn.setFixedSize(260, 300)
                self.grid_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                self.grid_btn.setText("🎨\n五宫格图片\n点击生成")
                self.grid_btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:2px dashed " + _theme.color("border_strong") + ";border-radius:6px;font-size:12px;}QPushButton:hover{border-color:" + _theme.color("warning") + ";color:" + _theme.color("warning") + ";}")
                self.grid_btn.clicked.connect(lambda: self.one_drag_four_checkbox.setChecked(True))

                grid_layout.addWidget(self.grid_img_container, 0, Qt.AlignmentFlag.AlignCenter)

            # 清除保存的路径
            if hasattr(self, 'grid_image_path'):
                self.grid_image_path = None

            # 标记为删除，以便保存时更新
            self.new_image_paths["grid_1drag4_path"] = None
            # 同时清空 item_data 中的路径
            if hasattr(self.item_data, 'grid_1drag4_path'):
                self.item_data.grid_1drag4_path = ""

            # 切换到正面图选项卡
            if hasattr(self, 'main_image_tabs') and self.main_image_tabs:
                self.main_image_tabs.setCurrentIndex(0)

            QMessageBox.information(self, "成功", "五宫格图片已删除")

        except Exception as e:
            print(f"删除五宫格图片失败: {e}")
            QMessageBox.warning(self, "错误", f"删除失败: {str(e)}")

    def do_ai_generate(self, prompt, selected_views, ratio, ref_image, provider_config):
        """执行AI图片生成（异步）"""
        try:
            from ai_engine.image_gen.image_client import ImageGenClient
            
            # 获取接口配置
            api_key = provider_config.get("api_key", "")
            base_url = provider_config.get("base_url", "")
            model = provider_config.get("model", "dall-e-3")
            provider = provider_config.get("provider", "openai")
            
            if not api_key or api_key == "sk-placeholder":
                # ComfyUI 不需要 API Key，跳过检查
                if "comfy" not in provider.lower():
                    QMessageBox.warning(self, "错误", "请先配置图片生成API密钥")
                    return
            
            count = len(selected_views)
            
            # 显示进度条，禁用按钮
            self.ai_btn.setEnabled(False)
            self.ai_btn.setText("生成中...")
            self.ai_progress_bar.show()
            self.ai_progress_bar.setRange(0, count)
            self.ai_progress_bar.setValue(0)
            
            client = ImageGenClient(api_key, base_url, model, provider, api_config=provider_config)
            
            ref_images = [ref_image] if ref_image else None
            gen_settings = {"aspect_ratio": ratio, "size": ratio, "quality": "standard"}
            
            # 使用用户选择的视角
            fields = selected_views
            
            # 创建工作线程
            self.worker = ImageGenerationWorker(
                self.item_type, fields, count, prompt, ratio, 
                ref_images, gen_settings, self.storage_path, client
            )
            
            # 连接信号
            self.worker.progress_signal.connect(self.on_generation_progress)
            self.worker.finished_signal.connect(self.on_generation_finished)
            self.worker.error_signal.connect(self.on_generation_error)
            
            # 启动线程
            self.worker.start()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"生成失败: {str(e)}")
            print(f"AI生成失败: {e}")
            self.reset_generation_ui()
    
    def on_generation_progress(self, value, status_text):
        """更新生成进度"""
        self.ai_progress_bar.setValue(value)
        self.ai_progress_bar.setFormat(status_text)
    
    def on_generation_finished(self, generated_images, success_count, failed_fields):
        """生成完成回调"""
        # 进度条完成
        self.ai_progress_bar.setValue(self.ai_progress_bar.maximum())
        self.ai_progress_bar.setFormat("生成完成！")
        
        # 应用生成的图片
        for field, path in generated_images.items():
            if path and os.path.exists(path):
                setattr(self.item_data, field, path)
                self.new_image_paths[field] = path
                if field in self.image_buttons:
                    if field == "front_view" or field == "close_view":
                        self.update_btn_large(self.image_buttons[field], path)
                    else:
                        self.update_btn(self.image_buttons[field], path)
        
        # 显示结果
        count = self.ai_progress_bar.maximum()
        if success_count == count:
            QMessageBox.information(self, "成功", f"已成功生成 {success_count} 张图片！")
        elif success_count > 0:
            QMessageBox.warning(self, "部分成功", f"成功生成 {success_count}/{count} 张图片\n失败：{', '.join(failed_fields)}")
        else:
            QMessageBox.warning(self, "失败", "所有图片生成失败，请检查API配置")
        
        # 恢复UI状态
        self.reset_generation_ui()
    
    def on_generation_error(self, error_msg):
        """生成错误回调"""
        QMessageBox.warning(self, "错误", f"生成失败: {error_msg}")
        self.reset_generation_ui()
    
    def reset_generation_ui(self):
        """重置生成UI状态"""
        self.ai_progress_bar.hide()
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("🤖 开始生成图片")
    
    def show_ai_generate_dialog(self):
        """保留旧方法以兼容（现在直接调用start_ai_generate）"""
        self.start_ai_generate()


class AIGenerateDialog(QDialog):
    def __init__(self, item_type, item_data, storage_path, count=1, ratio="1:1", ref_image="", provider_config=None, parent=None):
        super().__init__(parent)
        self.item_type = item_type
        self.item_data = item_data
        self.storage_path = storage_path
        self.default_count = count
        self.default_ratio = ratio
        self.ref_image_path = ref_image
        self.provider_config = provider_config or {}
        self.generated_images = {}
        self.name_edit = None
        self.worker = None
        self.gen_btn = None
        self.init_ui()

    def done(self, result):
        """拦截 X/Esc：生成线程仍在运行时不能直接关闭对话框。"""
        worker = getattr(self, 'worker', None)
        if worker is not None and worker.isRunning():
            reply = QMessageBox.question(
                self, "图片生成中",
                "图片仍在后台生成。\n关闭后本次生成结果将不会保存。\n\n确定要关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            worker.requestInterruption()
            _DETACHED_WORKERS.add(worker)
            worker.finished.connect(
                lambda w=worker: (_DETACHED_WORKERS.discard(w), w.deleteLater())
            )
        super().done(result)
    
    def init_ui(self):
        self.setWindowTitle(f"AI生成{self.item_type}")
        self.resize(700, 500)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 标题
        title = QLabel("🤖 AI生成图片")
        title.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 20px; font-weight: bold;")
        main_layout.addWidget(title)
        
        # 提示词输入
        prompt_label = QLabel("生成提示词:")
        prompt_label.setStyleSheet("color: " + _theme.color("text") + "; font-weight: bold;")
        main_layout.addWidget(prompt_label)
        
        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("描述你想要生成的图片内容...")
        # 根据类型预设提示词 - 优先使用ai_prompt
        if self.item_type == "character":
            default_prompt = getattr(self.item_data, 'ai_prompt', None) or f"a character, {self.item_data.name}, {self.item_data.gender or 'adult'}, {self.item_data.age or 'young'}, detailed, high quality"
        elif self.item_type == "scene":
            default_prompt = getattr(self.item_data, 'ai_prompt', None) or f"a scene, {self.item_data.name}, detailed environment, high quality"
        else:
            default_prompt = getattr(self.item_data, 'ai_prompt', None) or f"a prop, {self.item_data.name}, detailed, high quality"
        self.prompt_edit.setText(default_prompt)
        self.prompt_edit.setStyleSheet("QLineEdit{padding:10px;background:" + _theme.color("panel2") + "; color: " + _theme.color("text") + ";border:1px solid " + _theme.color("border_strong") + ";border-radius:5px;}")
        main_layout.addWidget(self.prompt_edit)
        
        # 设置区域
        settings_layout = QHBoxLayout()
        
        # 生成数量
        settings_layout.addWidget(QLabel("数量:"))
        self.count_combo = QComboBox()
        self.count_combo.addItems(["1", "2", "3", "4"])
        self.count_combo.setCurrentText(str(self.default_count))
        self.count_combo.setStyleSheet("QComboBox{padding:8px;background:" + _theme.color("panel2") + "; color: " + _theme.color("text") + ";border:1px solid " + _theme.color("border_strong") + ";border-radius:5px;}")
        settings_layout.addWidget(self.count_combo)
        
        # 宽高比
        settings_layout.addWidget(QLabel("比例:"))
        self.ratio_combo = QComboBox()
        self.ratio_combo.addItems(["1:1", "16:9", "9:16", "4:3", "3:4"])
        self.ratio_combo.setCurrentText(self.default_ratio)
        self.ratio_combo.setStyleSheet("QComboBox{padding:8px;background:" + _theme.color("panel2") + "; color: " + _theme.color("text") + ";border:1px solid " + _theme.color("border_strong") + ";border-radius:5px;}")
        settings_layout.addWidget(self.ratio_combo)
        
        # 参考图
        settings_layout.addWidget(QLabel("参考图:"))
        self.ref_btn = QPushButton("更改参考图" if self.ref_image_path else "选择参考图")
        self.ref_btn.setStyleSheet(_btn_style_secondary())
        self.ref_btn.clicked.connect(self.select_ref_image)
        settings_layout.addWidget(self.ref_btn)
        
        settings_layout.addStretch()
        main_layout.addLayout(settings_layout)
        
        # 参考图预览
        self.ref_preview = QLabel()
        self.ref_preview.setFixedHeight(100)
        self.ref_preview.setStyleSheet("background:" + _theme.color("panel2") + ";color:" + _theme.color("text_sub") + ";border-radius:5px;padding:5px;")
        self.ref_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 如果有传入的参考图，显示它
        if self.ref_image_path and os.path.exists(self.ref_image_path):
            pix = QPixmap(self.ref_image_path)
            scaled = pix.scaled(90, 90, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.ref_preview.setPixmap(scaled)
        else:
            self.ref_preview.setText("未选择参考图")
        
        main_layout.addWidget(self.ref_preview)
        
        # 状态显示
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: " + _theme.color("accent") + ";")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)
        
        # 生成按钮
        self.gen_btn = QPushButton("🚀 开始生成")
        self.gen_btn.setFixedHeight(45)
        self.gen_btn.setStyleSheet(_btn_style_success())
        self.gen_btn.clicked.connect(self.generate_images)
        main_layout.addWidget(self.gen_btn)
        
        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(_btn_style_secondary())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("应用图片")
        ok_btn.setStyleSheet(_btn_style_accent())
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        main_layout.addLayout(btn_layout)

        # 背景交由全局主题管理
    
    def select_ref_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择参考图", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.ref_image_path = path
            pix = QPixmap(path).scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            self.ref_preview.setPixmap(pix)
            self.ref_preview.setText("")
    
    def generate_images(self):
        prompt = self.prompt_edit.text().strip()
        if not prompt:
            QMessageBox.warning(self, "提示", "请输入生成提示词！")
            return

        worker = getattr(self, 'worker', None)
        if worker is not None and worker.isRunning():
            return

        count = int(self.count_combo.currentText())
        ratio = self.ratio_combo.currentText()

        self.status_label.setText("正在生成图片，请稍候...")
        self.generated_images = {}

        try:
            from ai_engine.image_gen.image_client import ImageGenClient

            api_key = self.provider_config.get("api_key", "")
            base_url = self.provider_config.get("base_url", "")
            model = self.provider_config.get("model", "dall-e-3")
            provider = self.provider_config.get("provider", "openai")

            if not api_key or api_key == "sk-placeholder":
                # ComfyUI 不需要 API Key，跳过检查
                if provider.lower() != "comfyui":
                    QMessageBox.warning(self, "错误", "请先配置图片生成API密钥")
                    self.status_label.setText("未配置API密钥")
                    return

            client = ImageGenClient(api_key, base_url, model, provider, api_config=self.provider_config)

            ref_images = [self.ref_image_path] if self.ref_image_path else None
            gen_settings = {"aspect_ratio": ratio, "size": ratio, "quality": "standard"}

            if self.item_type == "character":
                fields = ["front_view", "back_view", "right_side_view", "left_side_view", "top_view"]
            elif self.item_type == "scene":
                fields = ["wide_view", "medium_view", "close_view", "top_view", "side_view"]
            else:
                fields = ["front_view", "back_view", "top_view", "bottom_view", "side_view"]

            # 后台线程生成，避免阻塞 UI（原同步循环最长可冻结约 15 分钟）
            self.worker = ImageGenerationWorker(
                self.item_type, fields, count, prompt, ratio,
                ref_images, gen_settings, self.storage_path, client
            )
            self.worker.progress_signal.connect(self._on_gen_progress)
            self.worker.finished_signal.connect(self._on_gen_finished)
            self.worker.error_signal.connect(self._on_gen_error)
            if self.gen_btn is not None:
                self.gen_btn.setEnabled(False)
                self.gen_btn.setText("生成中...")
            self.worker.start()

        except Exception as e:
            self.status_label.setText(f"生成失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"生成失败: {str(e)}")
            if self.gen_btn is not None:
                self.gen_btn.setEnabled(True)
                self.gen_btn.setText("🚀 开始生成")

    def _on_gen_progress(self, value, status_text):
        self.status_label.setText(status_text)

    def _on_gen_finished(self, generated_images, success_count, failed_fields):
        self.generated_images = generated_images
        count = len(self.worker.fields) if self.worker is not None else success_count + len(failed_fields)
        if success_count == count and count > 0:
            self.status_label.setText(f"生成完成！共 {success_count} 张图片")
            QMessageBox.information(self, "成功", f"已成功生成 {success_count} 张图片")
        elif success_count > 0:
            self.status_label.setText(f"部分完成：{success_count}/{count} 张图片")
            QMessageBox.warning(self, "部分成功", f"成功生成 {success_count}/{count} 张图片\n失败：{', '.join(failed_fields)}")
        else:
            self.status_label.setText("生成失败")
            QMessageBox.warning(self, "失败", "所有图片生成失败，请检查API配置")
        if self.gen_btn is not None:
            self.gen_btn.setEnabled(True)
            self.gen_btn.setText("🚀 开始生成")

    def _on_gen_error(self, error_msg):
        self.status_label.setText(f"生成失败: {error_msg}")
        QMessageBox.warning(self, "错误", f"生成失败: {error_msg}")
        if self.gen_btn is not None:
            self.gen_btn.setEnabled(True)
            self.gen_btn.setText("🚀 开始生成")
    
    def get_generated_images(self):
        return self.generated_images


class RoleWindow(QWidget):
    def __init__(self, characters_dir, props_dir, scenes_dir):
        super().__init__()
        self.characters_dir = characters_dir
        self.props_dir = props_dir
        self.scenes_dir = scenes_dir
        self.project_dir = None
        self.characters = []
        self.props = []
        self.scenes = []
        self.init_ui()
        self.load_data()
    
    def set_project_dir(self, path):
        print(f"DEBUG: RoleWindow.set_project_dir called with path: {path}")
        self.project_dir = path
        # Update directories to project-specific paths
        if path:
            self.characters_dir = os.path.join(path, "characters")
            self.props_dir = os.path.join(path, "props")
            self.scenes_dir = os.path.join(path, "scenes")
            print(f"DEBUG: Updated directories:")
            print(f"  characters_dir: {self.characters_dir}")
            print(f"  props_dir: {self.props_dir}")
            print(f"  scenes_dir: {self.scenes_dir}")
        else:
            print(f"DEBUG: path is empty, using default directories")
        self.load_data()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QFrame()
        header.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 " + _theme.color("panel") + ",stop:1 " + _theme.color("panel2") + ");")
        header.setFixedHeight(70)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(25, 12, 25, 12)
        
        title = QLabel("角色 / 道具 / 场景")
        title.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 24px; font-weight: bold;")
        sub = QLabel("统一管理项目中的人物、道具和场景资源")
        sub.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        
        hl.addWidget(title)
        hl.addWidget(sub)
        main_layout.addWidget(header)
        
        # Content
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea{border:none;background-color:" + _theme.color("bg") + ";}QScrollBar:vertical{width:10px;background:" + _theme.color("panel") + ";}QScrollBar::handle:vertical{background:" + _theme.color("panel2") + ";border-radius:5px;}")
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(30, 20, 30, 20)
        self.content_layout.setSpacing(20)
        
        self.scroll.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll)
    
    @staticmethod
    def _dedup_files_by_id(directory, files):
        """按 ID 去重文件列表，保留修改时间最新的文件，删除同 ID 的孤儿文件。
        文件名格式为 {name}_{id}.json，id 为末段 UUID。
        返回去重后应保留的文件名列表。"""
        by_id = {}
        suffix = ".json"
        for f in files:
            stem = f[:-len(suffix)] if f.endswith(suffix) else f
            # 提取末段作为 ID（UUID 形如 xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx）
            item_id = stem.rsplit("_", 1)[-1] if "_" in stem else ""
            by_id.setdefault(item_id, []).append(f)

        kept = []
        for item_id, group in by_id.items():
            if len(group) == 1:
                kept.append(group[0])
                continue
            # 多个文件同 ID：保留修改时间最新的，删除其余孤儿
            def _mtime(fn):
                try:
                    return os.path.getmtime(os.path.join(directory, fn))
                except Exception:
                    return 0.0
            group.sort(key=_mtime, reverse=True)
            kept.append(group[0])
            for orphan in group[1:]:
                try:
                    os.remove(os.path.join(directory, orphan))
                    print(f"DEBUG: Removed orphan file {orphan} (dup of {group[0]})")
                except Exception as e:
                    print(f"DEBUG: Failed to remove orphan {orphan}: {e}")
        return kept

    def load_data(self):
        self.characters = []
        self.props = []
        self.scenes = []

        char_files = [f for f in os.listdir(self.characters_dir) if f.endswith(".json")] if os.path.exists(self.characters_dir) else []
        char_files = self._dedup_files_by_id(self.characters_dir, char_files)
        for f in char_files:
            try:
                with open(os.path.join(self.characters_dir, f), encoding='utf-8') as fh:
                    char = Character.from_json(fh.read())
                self.characters.append(char)
            except Exception as e:
                print(f"  Error loading character {f}: {e}")

        prop_files = [f for f in os.listdir(self.props_dir) if f.endswith(".json") and f != 'metadata.json'] if os.path.exists(self.props_dir) else []
        prop_files = self._dedup_files_by_id(self.props_dir, prop_files)
        for f in prop_files:
            try:
                with open(os.path.join(self.props_dir, f), encoding='utf-8') as fh:
                    prop = Prop.from_json(fh.read())
                self.props.append(prop)
            except Exception as e:
                print(f"  Error loading prop {f}: {e}")

        scene_files = [f for f in os.listdir(self.scenes_dir) if f.endswith(".json")] if os.path.exists(self.scenes_dir) else []
        scene_files = self._dedup_files_by_id(self.scenes_dir, scene_files)
        for f in scene_files:
            try:
                with open(os.path.join(self.scenes_dir, f), encoding='utf-8') as fh:
                    scene = Scene.from_json(fh.read())
                self.scenes.append(scene)
            except Exception as e:
                print(f"  Error loading scene {f}: {e}")

        self.refresh_content()
    
    def refresh_content(self):
        while self.content_layout.count():
            w = self.content_layout.takeAt(0)
            if w.widget(): w.widget().deleteLater()
        
        all_items = []
        for c in self.characters:
            all_items.append(("char", c.project_id or "未分类", c))
        for p in self.props:
            all_items.append(("prop", p.project_id or "未分类", p))
        for s in self.scenes:
            all_items.append(("scene", s.project_id or "未分类", s))
        
        grouped = {}
        for t, pid, item in all_items:
            if pid not in grouped:
                grouped[pid] = {"char": [], "prop": [], "scene": []}
            grouped[pid][t].append(item)
        
        for pid in sorted(grouped.keys()):
            card = self.create_project_card(pid, grouped[pid])
            self.content_layout.addWidget(card)
        
        self.content_layout.addStretch()
    
    def create_project_card(self, project_id, items):
        card = QFrame()
        card.setStyleSheet("QFrame{background-color:" + _theme.color("panel") + ";border-radius:12px;border:1px solid " + _theme.color("hover") + ";}")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)
        
        # 标题行
        title_bar = QHBoxLayout()
        name = self.get_project_name(project_id)
        title = QLabel(f"📁 {name}")
        title.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 16px; font-weight: bold;")
        title_bar.addWidget(title)
        
        count = QLabel(f"({len(items['char'])}角色 / {len(items['prop'])}道具 / {len(items['scene'])}场景)")
        count.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        title_bar.addWidget(count)
        
        title_bar.addStretch()
        
        # 删除整个项目资源按钮
        if items['char'] or items['prop'] or items['scene']:
            # 如果不是当前打开的项目，显示删除按钮
            current_pid = os.path.basename(self.project_dir) if self.project_dir else ""
            is_current = (project_id == current_pid)
            
            if not is_current:
                del_all_btn = QPushButton("🗑️ 删除")
                del_all_btn.setStyleSheet(_btn_style_danger())
                del_all_btn.clicked.connect(lambda: self.delete_project_items(project_id, items))
                title_bar.addWidget(del_all_btn)
        
        layout.addLayout(title_bar)
        
        # 三个类别并列显示（横向布局）
        categories_container = QFrame()
        categories_container.setStyleSheet("background-color: transparent;")
        categories_layout = QHBoxLayout(categories_container)
        categories_layout.setContentsMargins(0, 0, 0, 0)
        categories_layout.setSpacing(15)
        
        # 角色列
        char_widget = self.create_category_column("char", "🎭 角色", items["char"], self.characters_dir, self.add_character, self.extract_characters)
        categories_layout.addWidget(char_widget, stretch=1)
        
        # 分隔线（垂直）
        vline1 = QFrame()
        vline1.setFixedWidth(1)
        vline1.setStyleSheet("background:transparent; border:0; border-left:1px dashed " + _theme.color("hover") + ";")
        categories_layout.addWidget(vline1)
        
        # 道具列
        prop_widget = self.create_category_column("prop", "🎁 道具", items["prop"], self.props_dir, self.add_prop, None)
        categories_layout.addWidget(prop_widget, stretch=1)
        
        # 分隔线（垂直）
        vline2 = QFrame()
        vline2.setFixedWidth(1)
        vline2.setStyleSheet("background:transparent; border:0; border-left:1px dashed " + _theme.color("hover") + ";")
        categories_layout.addWidget(vline2)
        
        # 场景列
        scene_widget = self.create_category_column("scene", "🏞️ 场景", items["scene"], self.scenes_dir, self.add_scene, self.extract_scenes)
        categories_layout.addWidget(scene_widget, stretch=1)
        
        layout.addWidget(categories_container)
        
        return card
    
    def create_category_column(self, item_type, title, items, storage_dir, add_func, extract_func):
        """创建纵向的类别列（用于三列并列布局）"""
        column = QFrame()
        column.setStyleSheet("background-color: transparent;")
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(8)
        
        # 标题栏
        bar = QHBoxLayout()
        tl = QLabel(title)
        tl.setStyleSheet("color: " + _theme.color("text") + "; font-size: 14px; font-weight: bold;")
        bar.addWidget(tl)
        
        cnt = QLabel(f"({len(items)}个)")
        cnt.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        bar.addWidget(cnt)
        
        bar.addStretch()
        
        if extract_func:
            eb = QPushButton("⬇ 提取")
            eb.setToolTip("从剧本提取")
            eb.setMinimumSize(68, 24)
            eb.setStyleSheet(_btn_style_icon_small())
            eb.setCursor(Qt.CursorShape.PointingHandCursor)
            eb.clicked.connect(extract_func)
            bar.addWidget(eb)

        ab = QPushButton("＋ 添加")
        ab.setToolTip("添加")
        ab.setMinimumSize(68, 24)
        ab.setStyleSheet(_btn_style_icon_success())
        ab.setCursor(Qt.CursorShape.PointingHandCursor)
        ab.clicked.connect(add_func)
        bar.addWidget(ab)
        
        col_layout.addLayout(bar)
        
        # 卡片区（横向排列，一行2张，纵向滚动）
        if items:
            scroll = QScrollArea()
            scroll.setFixedHeight(280)
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}QScrollBar:vertical{width:8px;background:" + _theme.color("panel2") + ";}QScrollBar::handle:vertical{background:" + _theme.color("border_strong") + ";border-radius:4px;}")
            
            w = QWidget()
            # 使用网格布局，一行2列，图片更大
            grid = QGridLayout(w)
            grid.setSpacing(10)
            grid.setContentsMargins(0, 0, 0, 0)
            
            for idx, item in enumerate(items):
                row = idx // 2  # 每行2个
                col = idx % 2   # 列索引 0, 1
                grid.addWidget(self.create_item_card_small(item_type, item), row, col)
            
            scroll.setWidget(w)
            col_layout.addWidget(scroll)
        else:
            empty = QLabel("暂无，点击添加")
            empty.setStyleSheet("color:" + _theme.color("text_sub") + ";font-size:11px;padding:20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col_layout.addWidget(empty)
        
        return column
    
    def create_category_row(self, item_type, title, items, storage_dir, add_func, extract_func):
        row = QVBoxLayout()
        row.setSpacing(8)
        
        # 标题栏
        bar = QHBoxLayout()
        tl = QLabel(title)
        tl.setStyleSheet("color: " + _theme.color("text") + "; font-size: 14px; font-weight: bold;")
        bar.addWidget(tl)
        
        cnt = QLabel(f"({len(items)}个)")
        cnt.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        bar.addWidget(cnt)
        
        bar.addStretch()
        
        if extract_func:
            eb = QPushButton("📥 提取")
            eb.setStyleSheet(_btn_style_primary())
            eb.clicked.connect(extract_func)
            bar.addWidget(eb)
        
        ab = QPushButton("➕ 添加")
        ab.setStyleSheet(_btn_style_success())
        ab.clicked.connect(add_func)
        bar.addWidget(ab)
        
        row.addLayout(bar)
        
        # 卡片区
        if items:
            scroll = QScrollArea()
            scroll.setFixedHeight(110)
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}QScrollBar:horizontal{height:8px;background:" + _theme.color("panel2") + ";}QScrollBar::handle:horizontal{background:" + _theme.color("border_strong") + ";border-radius:4px;}")
            
            w = QWidget()
            l = QHBoxLayout(w)
            l.setSpacing(12)
            l.setContentsMargins(0, 0, 0, 0)
            
            for item in items:
                l.addWidget(self.create_item_card(item_type, item))
            
            l.addStretch()
            scroll.setWidget(w)
            row.addWidget(scroll)
        else:
            empty = QLabel("暂无，点击添加")
            empty.setStyleSheet("color:" + _theme.color("text_sub") + ";font-size:11px;padding:8px;")
            row.addWidget(empty)
        
        return row
    
    def create_item_card(self, item_type, item):
        card = QFrame()
        card.setFixedSize(95, 105)
        card.setStyleSheet("QFrame{background-color:" + _theme.color("panel2") + ";border-radius:8px;border:2px solid transparent;}QFrame:hover{background-color:" + _theme.color("hover") + ";border-color:" + _theme.color("warning") + ";}")
        l = QVBoxLayout(card)
        l.setContentsMargins(6, 6, 6, 6)
        
        btn = QPushButton()
        btn.setFixedSize(83, 60)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if item_type == "char":
            path = item.front_view or item.avatar_path
        elif item_type == "scene":
            path = item.close_view or item.reference_image
        else:  # prop
            path = item.reference_image
        
        if path and os.path.exists(path):
            pix = QPixmap(path)
            scaled = pix.scaled(83, 60, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            btn.setIcon(QIcon(scaled))
            btn.setIconSize(scaled.size())
        else:
            ic = "👤" if item_type == "char" else ("🏞️" if item_type == "scene" else "🎁")
            btn.setText(ic)
            btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:1px dashed " + _theme.color("border_strong") + ";border-radius:5px;font-size:20px;}")
        
        if item_type == "char":
            btn.clicked.connect(lambda checked, c=item: self.edit_character(c))
        elif item_type == "scene":
            btn.clicked.connect(lambda checked, s=item: self.edit_scene(s))
        else:
            btn.clicked.connect(lambda checked, p=item: self.edit_prop(p))
        
        l.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        nm = item.name[:7] + ".." if len(item.name) > 7 else item.name
        lbl = QLabel(nm)
        lbl.setStyleSheet("color: " + _theme.color("text") + ";font-size:10px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(lbl, 0, Qt.AlignmentFlag.AlignCenter)
        
        return card
    
    def create_item_card_horizontal(self, item_type, item):
        """创建横向的卡片（适合纵向列表显示）"""
        card = QFrame()
        card.setFixedHeight(50)
        card.setStyleSheet("QFrame{background-color:" + _theme.color("panel2") + ";border-radius:6px;border:1px solid transparent;}QFrame:hover{background-color:" + _theme.color("hover") + ";border-color:" + _theme.color("warning") + ";}")
        l = QHBoxLayout(card)
        l.setContentsMargins(8, 4, 8, 4)
        l.setSpacing(8)
        
        # 图片按钮
        btn = QPushButton()
        btn.setFixedSize(40, 40)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if item_type == "char":
            path = item.front_view or item.avatar_path
        elif item_type == "scene":
            path = item.close_view or item.reference_image
        else:  # prop
            path = item.reference_image
        
        if path and os.path.exists(path):
            pix = QPixmap(path)
            scaled = pix.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            btn.setIcon(QIcon(scaled))
            btn.setIconSize(scaled.size())
            btn.setStyleSheet("QPushButton{background:transparent;border:none;border-radius:4px;}")
        else:
            ic = "👤" if item_type == "char" else ("🏞️" if item_type == "scene" else "🎁")
            btn.setText(ic)
            btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:1px dashed " + _theme.color("border_strong") + ";border-radius:4px;font-size:14px;}")
        
        if item_type == "char":
            btn.clicked.connect(lambda checked, c=item: self.edit_character(c))
        elif item_type == "scene":
            btn.clicked.connect(lambda checked, s=item: self.edit_scene(s))
        else:
            btn.clicked.connect(lambda checked, p=item: self.edit_prop(p))
        
        l.addWidget(btn)
        
        # 名称
        nm = item.name[:10] + ".." if len(item.name) > 10 else item.name
        lbl = QLabel(nm)
        lbl.setStyleSheet("color: " + _theme.color("text") + ";font-size:11px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        l.addWidget(lbl, stretch=1)
        
        # 删除按钮
        del_btn = QPushButton("×")
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet(_btn_style_delete_small())
        
        if item_type == "char":
            del_btn.clicked.connect(lambda: self.delete_character(item))
        elif item_type == "scene":
            del_btn.clicked.connect(lambda: self.delete_scene(item))
        else:
            del_btn.clicked.connect(lambda: self.delete_prop(item))
        
        l.addWidget(del_btn)
        
        return card
    
    def create_item_card_small(self, item_type, item):
        """创建小卡片（适合网格布局，一行2张）"""
        card = QFrame()
        card.setFixedSize(140, 160)
        card.setStyleSheet("QFrame{background-color:" + _theme.color("panel2") + ";border-radius:8px;border:1px solid transparent;}QFrame:hover{background-color:" + _theme.color("hover") + ";}")
        l = QVBoxLayout(card)
        l.setContentsMargins(5, 5, 5, 3)
        l.setSpacing(1)
        
        # 图片区域容器（用于放置图片和删除按钮）
        img_container = QFrame()
        img_container.setFixedSize(130, 105)
        img_container.setStyleSheet("background:transparent;")
        img_layout = QVBoxLayout(img_container)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(0)
        
        # 图片按钮
        btn = QPushButton()
        btn.setFixedSize(130, 105)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if item_type == "char":
            path = item.front_view or item.avatar_path
        elif item_type == "scene":
            path = item.close_view or item.reference_image
        else:  # prop
            path = item.reference_image
        
        if path and os.path.exists(path):
            pix = QPixmap(path)
            # 使用 KeepAspectRatio 保持完整图片，不裁剪，最大化利用空间
            scaled = pix.scaled(126, 101, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            btn.setIcon(QIcon(scaled))
            btn.setIconSize(scaled.size())
            btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";border:none;border-radius:6px;padding:1px;}QPushButton:hover{background:" + _theme.color("hover") + ";}")
        else:
            ic = "👤" if item_type == "char" else ("🏞️" if item_type == "scene" else "🎁")
            btn.setText(ic)
            btn.setStyleSheet("QPushButton{background:" + _theme.color("panel") + ";color:" + _theme.color("text_sub") + ";border:1px dashed " + _theme.color("border_strong") + ";border-radius:6px;font-size:24px;}")
        
        if item_type == "char":
            btn.clicked.connect(lambda checked, c=item: self.edit_character(c))
        elif item_type == "scene":
            btn.clicked.connect(lambda checked, s=item: self.edit_scene(s))
        else:
            btn.clicked.connect(lambda checked, p=item: self.edit_prop(p))
        
        img_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 删除按钮 - 放在图片容器右上角，必须在图片按钮之后创建以确保在最上层
        del_btn = QPushButton("✕", img_container)
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet(_btn_style_delete_small())
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.move(104, 2)
        del_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        del_btn.show()
        del_btn.raise_()
        
        if item_type == "char":
            del_btn.clicked.connect(lambda: self.delete_character(item))
        elif item_type == "scene":
            del_btn.clicked.connect(lambda: self.delete_scene(item))
        else:
            del_btn.clicked.connect(lambda: self.delete_prop(item))
        
        l.addWidget(img_container, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 名称
        nm = item.name[:10] + ".." if len(item.name) > 10 else item.name
        lbl = QLabel(nm)
        lbl.setStyleSheet("color: " + _theme.color("text") + ";font-size:11px;padding:0px;margin:0px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFixedHeight(16)
        l.addWidget(lbl, 0, Qt.AlignmentFlag.AlignCenter)
        
        return card
    
    def check_project(self):
        if not self.project_dir:
            QMessageBox.warning(self, "提示", "请先在左侧选择并打开一个项目！")
            return False
        # 检查项目目录是否存在
        if not os.path.exists(self.project_dir):
            QMessageBox.warning(self, "提示", "当前项目不存在，请重新选择项目！")
            return False
        return True
    
    def add_character(self):
        if not self.check_project():
            return
        try:
            pid = os.path.basename(self.project_dir) if self.project_dir else "未分类"
            c = Character(id=str(uuid.uuid4()), name="新角色", age="青年", gender="未知", project_id=pid)
            save_result = c.save(self.characters_dir)
            if save_result:
                self.load_data()
                self.edit_character(c)
            else:
                QMessageBox.warning(self, "错误", "保存角色失败，请稍后重试")
        except Exception as e:
            print(f"添加角色失败: {e}")
            QMessageBox.warning(self, "错误", f"添加角色时出现错误: {str(e)}")
    
    def edit_character(self, char):
        print(f"DEBUG: edit_character called for {char.name}")
        try:
            dialog = MultiImageEditDialog("character", char, self.characters_dir, self)
            dialog.exec()
            self.load_data()
        except Exception as e:
            print(f"DEBUG: edit_character error: {e}")
            import traceback
            traceback.print_exc()
    
    def add_prop(self):
        if not self.check_project():
            return
        try:
            pid = os.path.basename(self.project_dir) if self.project_dir else "未分类"
            p = Prop(id=str(uuid.uuid4()), name="新道具", description="", project_id=pid)
            save_result = p.save(self.props_dir)
            if save_result:
                self.load_data()
                self.edit_prop(p)
            else:
                QMessageBox.warning(self, "错误", "保存道具失败，请稍后重试")
        except Exception as e:
            print(f"添加道具失败: {e}")
            QMessageBox.warning(self, "错误", f"添加道具时出现错误: {str(e)}")
    
    def edit_prop(self, prop):
        dialog = MultiImageEditDialog("prop", prop, self.props_dir, self)
        dialog.exec()
        self.load_data()
    
    def add_scene(self):
        if not self.check_project():
            return
        try:
            pid = os.path.basename(self.project_dir) if self.project_dir else "未分类"
            s = Scene(id=str(uuid.uuid4()), name="新场景", description="", project_id=pid)
            save_result = s.save(self.scenes_dir)
            if save_result:
                self.load_data()
                self.edit_scene(s)
            else:
                QMessageBox.warning(self, "错误", "保存场景失败，请稍后重试")
        except Exception as e:
            print(f"添加场景失败: {e}")
            QMessageBox.warning(self, "错误", f"添加场景时出现错误: {str(e)}")
    
    def edit_scene(self, scene):
        dialog = MultiImageEditDialog("scene", scene, self.scenes_dir, self)
        dialog.exec()
        self.load_data()
    
    def delete_character(self, char):
        """删除角色"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除角色「{char.name}」吗？\n\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 角色保存格式为: {name}_{id}.json
                safe_name = "".join(c for c in char.name if c not in '<>:"/\\|?*')[:50]
                char_path = os.path.join(self.characters_dir, f"{safe_name}_{char.id}.json")
                if os.path.exists(char_path):
                    os.remove(char_path)
                    self.load_data()
                    QMessageBox.information(self, "成功", f"角色「{char.name}」已删除")
                else:
                    # 尝试查找包含该ID的任何文件
                    import glob
                    pattern = os.path.join(self.characters_dir, f"*_{char.id}.json")
                    matching_files = glob.glob(pattern)
                    if matching_files:
                        os.remove(matching_files[0])
                        self.load_data()
                        QMessageBox.information(self, "成功", f"角色「{char.name}」已删除")
                    else:
                        QMessageBox.warning(self, "错误", f"找不到角色文件")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除失败: {str(e)}")
    
    def delete_prop(self, prop):
        """删除道具"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除道具「{prop.name}」吗？\n\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 道具保存格式为: {name}_{id}.json
                safe_name = "".join(c for c in prop.name if c not in '<>:"/\\|?*')[:50]
                prop_path = os.path.join(self.props_dir, f"{safe_name}_{prop.id}.json")
                if os.path.exists(prop_path):
                    os.remove(prop_path)
                    self.load_data()
                    QMessageBox.information(self, "成功", f"道具「{prop.name}」已删除")
                else:
                    # 尝试查找包含该ID的任何文件
                    import glob
                    pattern = os.path.join(self.props_dir, f"*_{prop.id}.json")
                    matching_files = glob.glob(pattern)
                    if matching_files:
                        os.remove(matching_files[0])
                        self.load_data()
                        QMessageBox.information(self, "成功", f"道具「{prop.name}」已删除")
                    else:
                        QMessageBox.warning(self, "错误", f"找不到道具文件")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除失败: {str(e)}")
    
    def delete_scene(self, scene):
        """删除场景"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除场景「{scene.name}」吗？\n\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 场景保存格式为: {name}_{id}.json
                safe_name = "".join(c for c in scene.name if c not in '<>:"/\\|?*')[:50]
                scene_path = os.path.join(self.scenes_dir, f"{safe_name}_{scene.id}.json")
                if os.path.exists(scene_path):
                    os.remove(scene_path)
                    self.load_data()
                    QMessageBox.information(self, "成功", f"场景「{scene.name}」已删除")
                else:
                    # 尝试查找包含该ID的任何文件
                    import glob
                    pattern = os.path.join(self.scenes_dir, f"*_{scene.id}.json")
                    matching_files = glob.glob(pattern)
                    if matching_files:
                        os.remove(matching_files[0])
                        self.load_data()
                        QMessageBox.information(self, "成功", f"场景「{scene.name}」已删除")
                    else:
                        QMessageBox.warning(self, "错误", f"找不到场景文件")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除失败: {str(e)}")
    
    def delete_project_items(self, project_id, items):
        name = self.get_project_name(project_id)
        total = len(items['char']) + len(items['prop']) + len(items['scene'])
        
        reply = QMessageBox.question(self, "确认删除", 
            f"确定要删除项目「{name}」的所有资源吗？\n\n将删除：\n- {len(items['char'])} 个角色\n- {len(items['prop'])} 个道具\n- {len(items['scene'])} 个场景\n\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            # 删除角色
            for c in items['char']:
                for f in os.listdir(self.characters_dir):
                    if c.id in f:
                        os.remove(os.path.join(self.characters_dir, f))
                        break
            
            # 删除道具
            for p in items['prop']:
                for f in os.listdir(self.props_dir):
                    if p.id in f:
                        os.remove(os.path.join(self.props_dir, f))
                        break
            
            # 删除场景
            for s in items['scene']:
                for f in os.listdir(self.scenes_dir):
                    if s.id in f:
                        os.remove(os.path.join(self.scenes_dir, f))
                        break
            
            self.load_data()
            QMessageBox.information(self, "完成", f"已删除项目「{name}」的全部 {total} 个资源。")
    
    def extract_characters(self):
        if not self.check_project():
            return
        
        pid = os.path.basename(self.project_dir) if self.project_dir else "未分类"
        roles = set()
        
        sp = os.path.join(self.project_dir, "series.json")
        if os.path.exists(sp):
            try:
                for ep in json.load(open(sp, encoding='utf-8')).get("episodes", []):
                    p = os.path.join(self.project_dir, "scripts", f"episode_{ep['id']}.json")
                    if os.path.exists(p):
                        try:
                            for sc in Script.from_json(open(p, encoding='utf-8').read()).scenes:
                                for d in sc.dialogues:
                                    if d.role: roles.add(d.role)
                        except Exception: pass
            except Exception: pass
        else:
            p = os.path.join(self.project_dir, "current_script.json")
            if os.path.exists(p):
                try:
                    for sc in Script.from_json(open(p, encoding='utf-8').read()).scenes:
                        for d in sc.dialogues:
                            if d.role: roles.add(d.role)
                except Exception: pass
        
        if not roles:
            QMessageBox.information(self, "提示", "剧本中未找到角色。")
            return
        
        existing = set(c.name for c in self.characters)
        new_r = [r for r in sorted(roles) if r not in existing]
        
        if new_r:
            for r in new_r:
                Character(id=str(uuid.uuid4()), name=r, age="青年", gender="未知", project_id=pid).save(self.characters_dir)
            self.load_data()
            QMessageBox.information(self, "成功", f"已导入 {len(new_r)} 个角色。")
        else:
            QMessageBox.information(self, "提示", "所有角色已存在。")
    
    def extract_scenes(self):
        if not self.check_project():
            return
        
        pid = os.path.basename(self.project_dir) if self.project_dir else "未分类"
        scenes_set = set()
        
        sp = os.path.join(self.project_dir, "series.json")
        if os.path.exists(sp):
            try:
                for ep in json.load(open(sp, encoding='utf-8')).get("episodes", []):
                    p = os.path.join(self.project_dir, "scripts", f"episode_{ep['id']}.json")
                    if os.path.exists(p):
                        try:
                            for sc in Script.from_json(open(p, encoding='utf-8').read()).scenes:
                                if sc.location: scenes_set.add((sc.location, sc.time))
                        except Exception: pass
            except Exception: pass
        else:
            p = os.path.join(self.project_dir, "current_script.json")
            if os.path.exists(p):
                try:
                    for sc in Script.from_json(open(p, encoding='utf-8').read()).scenes:
                        if sc.location: scenes_set.add((sc.location, sc.time))
                except Exception: pass
        
        if not scenes_set:
            QMessageBox.information(self, "提示", "剧本中未找到场景。")
            return
        
        existing = set(s.name for s in self.scenes)
        new_s = [(l, t) for l, t in sorted(scenes_set) if l not in existing]
        
        if new_s:
            for loc, t in new_s:
                Scene(id=str(uuid.uuid4()), name=loc, description=f"位置: {loc}", time_of_day=t, project_id=pid).save(self.scenes_dir)
            self.load_data()
            QMessageBox.information(self, "成功", f"已导入 {len(new_s)} 个场景。")
        else:
            QMessageBox.information(self, "提示", "所有场景已存在。")
    
    def get_project_name(self, project_id):
        if project_id == "未分类":
            return "未分类"
        try:
            rd = os.path.dirname(self.characters_dir)
            pj = os.path.join(rd, "projects", project_id, "project.json")
            if os.path.exists(pj):
                return json.load(open(pj, encoding='utf-8')).get("name", project_id)
        except Exception: pass
        return project_id
    
    def load_existing_data(self):
        self.load_data()

    def data_fingerprint(self):
        """主窗口 Tab 切换指纹：角色/道具/场景目录内容未变时跳过重载。"""
        from ui.utils import dir_signature
        return dir_signature(self.characters_dir, self.props_dir, self.scenes_dir)
