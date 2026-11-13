"""
素材库窗口

统一展示 AI 生成图 / 上传图 / stock 素材；按 角色 / 场景 / 道具 索引；
支持搜索、上传、删除、标签编辑。供 P2.3 画面来源选择复用。
"""
import os
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QScrollArea, QFrame, QMessageBox, QFileDialog, QMenu,
    QDialog, QFormLayout, QTextEdit, QSizePolicy, QApplication
)
from ui import theme as _theme

try:
    from core.asset.asset_manager import (
        AssetManager, AssetItem,
        ASSET_TYPE_IMAGE, ASSET_TYPE_VIDEO, ASSET_TYPE_AUDIO,
        ASSET_SOURCE_AI, ASSET_SOURCE_UPLOAD, ASSET_SOURCE_STOCK,
        TAG_CHARACTER, TAG_SCENE, TAG_PROP, TAG_OTHER,
    )
except ImportError:
    from src.core.asset.asset_manager import (
        AssetManager, AssetItem,
        ASSET_TYPE_IMAGE, ASSET_TYPE_VIDEO, ASSET_TYPE_AUDIO,
        ASSET_SOURCE_AI, ASSET_SOURCE_UPLOAD, ASSET_SOURCE_STOCK,
        TAG_CHARACTER, TAG_SCENE, TAG_PROP, TAG_OTHER,
    )

try:
    from ui.flow_layout import FlowLayout
except ImportError:
    from src.ui.flow_layout import FlowLayout


# 标签中文名
TAG_LABELS = {
    TAG_CHARACTER: "角色",
    TAG_SCENE: "场景",
    TAG_PROP: "道具",
    TAG_OTHER: "其他",
}
SOURCE_LABELS = {
    ASSET_SOURCE_AI: "AI 生成",
    ASSET_SOURCE_UPLOAD: "上传",
    ASSET_SOURCE_STOCK: "Stock",
}
TYPE_LABELS = {
    ASSET_TYPE_IMAGE: "图片",
    ASSET_TYPE_VIDEO: "视频",
    ASSET_TYPE_AUDIO: "音频",
}

def _card_style():
    """素材卡片样式（每次调用按当前主题求值）。"""
    return """
AssetCard {
    background-color: """ + _theme.color("panel") + """;
    border: 1px solid """ + _theme.color("accent") + """;
    border-radius: 10px;
}
AssetCard:hover {
    border: 1px solid """ + _theme.color("accent") + """;
    background-color: """ + _theme.color("panel") + """;
}
"""

THUMB_SIZE = QSize(160, 120)


class AssetCard(QFrame):
    """单个素材卡片"""
    request_delete = pyqtSignal(str)   # asset_id
    request_edit = pyqtSignal(str)     # asset_id
    request_use = pyqtSignal(str)      # asset_id

    def __init__(self, item: AssetItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("AssetCard")
        self.setFixedSize(190, 230)
        self.setStyleSheet(_card_style())
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 缩略图
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(170, 120)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: " + _theme.color("bg") + "; border-radius: 6px;")
        self._load_thumb(item)
        layout.addWidget(self.thumb_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # 名称
        name_label = QLabel(item.name or "未命名")
        name_label.setStyleSheet("color: " + _theme.color("text") + "; font-size: 12px; font-weight: 600;")
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(36)
        layout.addWidget(name_label)

        # 标签行
        tag_text = TAG_LABELS.get(item.tag, item.tag)
        src_text = SOURCE_LABELS.get(item.source, item.source)
        meta_label = QLabel(f"[{tag_text}] · {src_text}")
        meta_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        layout.addWidget(meta_label)

        # 操作按钮行（用文字按钮，避免 ✎/🗑 等符号在部分字体下渲染成乱码）
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(4)

        edit_btn = QPushButton("编辑")
        edit_btn.setFixedSize(46, 26)
        edit_btn.setToolTip("编辑素材信息")
        edit_btn.setStyleSheet(
            "QPushButton { background:" + _theme.color("accent2") + "; color: " + _theme.color("accent_text") + "; border:none; border-radius:4px; padding:0; font-size:12px; }"
            "QPushButton:hover { background:" + _theme.color("accent") + "; }"
        )
        edit_btn.clicked.connect(lambda: self.request_edit.emit(self.item.id))
        btn_row.addWidget(edit_btn)

        use_btn = QPushButton("使用")
        use_btn.setFixedHeight(26)
        use_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        use_btn.setToolTip("在分镜中使用此素材")
        use_btn.setStyleSheet(
            "QPushButton { background:" + _theme.color("info") + "; color: " + _theme.color("accent_text") + "; border:none; border-radius:4px; padding:0; font-size:12px; }"
            "QPushButton:hover { background:" + _theme.color("info") + "; }"
        )
        use_btn.clicked.connect(lambda: self.request_use.emit(self.item.id))
        btn_row.addWidget(use_btn, 1)

        del_btn = QPushButton("删除")
        del_btn.setFixedSize(46, 26)
        del_btn.setToolTip("删除素材")
        del_btn.setStyleSheet(
            "QPushButton { background:" + _theme.color("danger") + "; color: " + _theme.color("accent_text") + "; border:none; border-radius:4px; padding:0; font-size:12px; }"
            "QPushButton:hover { background:" + _theme.color("danger") + "; }"
        )
        del_btn.clicked.connect(lambda: self.request_delete.emit(self.item.id))
        btn_row.addWidget(del_btn)

        layout.addLayout(btn_row)

    def _load_thumb(self, item: AssetItem):
        if item.type == ASSET_TYPE_IMAGE and item.path and os.path.exists(item.path):
            pix = QPixmap(item.path)
            if not pix.isNull():
                self.thumb_label.setPixmap(pix.scaled(
                    THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                return
        # 视频/音频或图片加载失败：用占位文字
        text = TYPE_LABELS.get(item.type, item.type)
        self.thumb_label.setText(text)
        self.thumb_label.setStyleSheet(
            "background-color: " + _theme.color("bg") + "; color:" + _theme.color("text_sub") + "; border-radius:6px; font-size:14px;"
        )


class AssetEditDialog(QDialog):
    """编辑素材属性（名称、标签、来源、描述、提示词、自由标签）"""
    def __init__(self, item: AssetItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑素材")
        self.resize(420, 380)
        self.setStyleSheet("QDialog { background-color:" + _theme.color("panel2") + "; color:" + _theme.color("text") + "; }")

        layout = QFormLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.name_edit = QLineEdit(item.name)
        self.name_edit.setStyleSheet(_input_style())
        layout.addRow("名称", self.name_edit)

        self.tag_combo = QComboBox()
        for k, v in TAG_LABELS.items():
            self.tag_combo.addItem(v, k)
        idx = self.tag_combo.findData(item.tag)
        if idx >= 0:
            self.tag_combo.setCurrentIndex(idx)
        self.tag_combo.setStyleSheet(_input_style())
        layout.addRow("标签类别", self.tag_combo)

        self.source_combo = QComboBox()
        for k, v in SOURCE_LABELS.items():
            self.source_combo.addItem(v, k)
        idx = self.source_combo.findData(item.source)
        if idx >= 0:
            self.source_combo.setCurrentIndex(idx)
        self.source_combo.setStyleSheet(_input_style())
        layout.addRow("来源", self.source_combo)

        self.linked_name_edit = QLineEdit(item.linked_name)
        self.linked_name_edit.setStyleSheet(_input_style())
        layout.addRow("关联实体", self.linked_name_edit)

        self.tags_edit = QLineEdit(" ".join(item.tags or []))
        self.tags_edit.setStyleSheet(_input_style())
        layout.addRow("自由标签", self.tags_edit)

        self.desc_edit = QTextEdit(item.description)
        self.desc_edit.setStyleSheet(_input_style())
        layout.addRow("描述", self.desc_edit)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("保存")
        ok_btn.setStyleSheet(_btn_primary())
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(_btn_secondary())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addRow("", btn_row)

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or "未命名",
            "tag": self.tag_combo.currentData(),
            "source": self.source_combo.currentData(),
            "linked_name": self.linked_name_edit.text().strip(),
            "tags": [t for t in self.tags_edit.text().split() if t],
            "description": self.desc_edit.toPlainText().strip(),
        }


def _input_style():
    """输入框样式（每次调用按当前主题求值）。"""
    return """
QLineEdit, QComboBox, QTextEdit {
    background-color: """ + _theme.color("panel") + """;
    color: """ + _theme.color("text") + """;
    border: 1px solid """ + _theme.color("panel2") + """;
    border-radius: 4px;
    padding: 6px;
}
"""
def _btn_primary():
    """主色按钮样式（每次调用按当前主题求值）。"""
    return """
QPushButton { background:""" + _theme.color("accent2") + """; color: """ + _theme.color("accent_text") + """; border:none; border-radius:6px; padding:8px 16px; font-weight:600; }
QPushButton:hover { background:""" + _theme.color("accent") + """; }
"""
def _btn_secondary():
    """次级按钮样式（每次调用按当前主题求值）。"""
    return """
QPushButton { background:""" + _theme.color("text_sub") + """; color: """ + _theme.color("text") + """; border:none; border-radius:6px; padding:8px 16px; }
QPushButton:hover { background:""" + _theme.color("text_sub") + """; }
"""


class AssetLibraryWindow(QWidget):
    """素材库主窗口"""

    # 选中素材在分镜中使用，供 P2.3 复用
    asset_selected = pyqtSignal(str, str)  # (asset_id, file_path)

    def __init__(self, parent=None, resources_dir: Optional[str] = None):
        super().__init__(parent)
        self.resources_dir = resources_dir or ""
        self.manager: Optional[AssetManager] = None
        if resources_dir:
            self.manager = AssetManager(resources_dir)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ===== 工具栏 =====
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.scope_combo = QComboBox()
        self.scope_combo.addItem("全部", "all")
        self.scope_combo.addItem("项目素材", "project")
        self.scope_combo.addItem("全局素材", "global")
        self.scope_combo.setStyleSheet(_input_style())
        toolbar.addWidget(QLabel("范围:"))
        toolbar.addWidget(self.scope_combo)

        self.type_combo = QComboBox()
        self.type_combo.addItem("全部类型", "")
        for k, v in TYPE_LABELS.items():
            self.type_combo.addItem(v, k)
        self.type_combo.setStyleSheet(_input_style())
        toolbar.addWidget(QLabel("类型:"))
        toolbar.addWidget(self.type_combo)

        self.tag_combo = QComboBox()
        self.tag_combo.addItem("全部标签", "")
        for k, v in TAG_LABELS.items():
            self.tag_combo.addItem(v, k)
        self.tag_combo.setStyleSheet(_input_style())
        toolbar.addWidget(QLabel("标签:"))
        toolbar.addWidget(self.tag_combo)

        self.source_combo = QComboBox()
        self.source_combo.addItem("全部来源", "")
        for k, v in SOURCE_LABELS.items():
            self.source_combo.addItem(v, k)
        self.source_combo.setStyleSheet(_input_style())
        toolbar.addWidget(QLabel("来源:"))
        toolbar.addWidget(self.source_combo)

        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("关键词搜索（名称/描述/标签）")
        self.keyword_edit.setStyleSheet(_input_style())
        self.keyword_edit.returnPressed.connect(self.refresh)
        toolbar.addWidget(self.keyword_edit, 1)

        search_btn = QPushButton("搜索")
        search_btn.setStyleSheet(_btn_primary())
        search_btn.clicked.connect(self.refresh)
        toolbar.addWidget(search_btn)

        toolbar.addStretch()

        upload_btn = QPushButton("📤 上传素材")
        upload_btn.setStyleSheet(_btn_primary())
        upload_btn.clicked.connect(self._on_upload)
        toolbar.addWidget(upload_btn)

        scan_btn = QPushButton("🔍 扫描")
        scan_btn.setToolTip("扫描项目目录下已有的图片并纳入素材库")
        scan_btn.setStyleSheet(_btn_secondary())
        scan_btn.clicked.connect(self._on_scan)
        toolbar.addWidget(scan_btn)

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet(_btn_secondary())
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        layout.addLayout(toolbar)

        # ===== 素材网格 =====
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            "QScrollArea { border:none; background:transparent; }"
        )
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        self.flow = FlowLayout(container, margin=8, spacing=10)
        self.scroll_area.setWidget(container)
        layout.addWidget(self.scroll_area, 1)

        # ===== 状态栏 =====
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color:" + _theme.color("text_sub") + "; font-size:12px;")
        layout.addWidget(self.status_label)

        # 联动过滤器
        for combo in (self.scope_combo, self.type_combo, self.tag_combo, self.source_combo):
            combo.currentIndexChanged.connect(self.refresh)

        self.refresh()
        self._polish_buttons()

    def _btn_feedback_qss(self) -> str:
        """统一的按钮悬停/按下描边规则（追加在按钮基础样式之后）。"""
        return f"""
QPushButton:hover {{ border: 1px solid {_theme.color("accent")}; }}
QPushButton:pressed {{ border: 1px solid {_theme.color("accent2")}; }}
"""

    def _polish_buttons(self):
        """补齐按钮的手型光标与悬停/按下反馈（幂等，可重复调用）。"""
        for btn in self.findChildren(QPushButton):
            base = btn.property("_base_qss")
            if base is None:
                base = _theme.as_rule_block(btn.styleSheet() or "")
                btn.setProperty("_base_qss", base)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(base + self._btn_feedback_qss())

    # ---------- 项目联动 ----------
    def set_resources_dir(self, resources_dir: str):
        self.resources_dir = resources_dir
        if not self.manager or not self.manager.resources_dir == resources_dir:
            self.manager = AssetManager(resources_dir)
        self.refresh()

    def set_project_dir(self, project_dir: Optional[str]):
        if not self.manager:
            if not self.resources_dir:
                self.status_label.setText("未初始化 resources_dir")
                return
            self.manager = AssetManager(self.resources_dir)
        self.manager.set_project_dir(project_dir)
        # 切换项目后顺手扫描一次旧资产，避免索引缺失
        if project_dir:
            try:
                self.manager.scan_existing_assets()
            except Exception as e:
                print(f"[AssetLibrary] 扫描旧资产失败: {e}")
        self.refresh()

    def data_fingerprint(self):
        """主窗口 Tab 切换指纹：素材索引未变时跳过重载。"""
        from ui.utils import dir_signature
        paths = []
        mgr = getattr(self, "manager", None)
        if mgr is not None:
            idx = getattr(mgr, "index_path", None) or getattr(mgr, "global_index_path", None)
            if idx:
                paths.append(idx)
            proj_idx = getattr(mgr, "project_index_path", None)
            if proj_idx:
                paths.append(proj_idx)
        if not paths:
            return None
        return dir_signature(*paths)

    def load_existing_data(self):
        """主窗口 switch_tab 时调用"""
        self.refresh()

    # ---------- 列表 ----------
    def refresh(self):
        # 清空旧卡片
        while self.flow.count():
            item = self.flow.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.setParent(None)
                w.deleteLater()

        if not self.manager:
            self.status_label.setText("未配置 resources_dir")
            return

        # 兜底：页面重建（切主题/皮肤）后可能没挂载项目，导致素材显示为空。
        # 这里从主窗口取当前项目补挂，避免出现“项目已加载但素材 0 项”。
        if not self.manager.project_dir:
            try:
                cur = getattr(self.window(), "_current_project_path", None)
            except Exception:
                cur = None
            if cur:
                self.manager.set_project_dir(cur)

        scope = self.scope_combo.currentData() or "all"
        type_f = self.type_combo.currentData() or None
        tag_f = self.tag_combo.currentData() or None
        src_f = self.source_combo.currentData() or None
        kw = self.keyword_edit.text().strip() or None

        items = self.manager.query(
            type_filter=type_f, tag_filter=tag_f,
            source_filter=src_f, keyword=kw, scope=scope
        )

        if not items:
            empty = QLabel("暂无素材，点击「上传素材」或「扫描」开始")
            empty.setStyleSheet("color:" + _theme.color("text_sub") + "; font-size:14px; padding:40px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.flow.addWidget(empty)
            self.status_label.setText("共 0 项")
            self._polish_buttons()
            return

        for it in items:
            card = AssetCard(it)
            card.request_delete.connect(self._on_delete)
            card.request_edit.connect(self._on_edit)
            card.request_use.connect(self._on_use)
            self.flow.addWidget(card)

        self.status_label.setText(f"共 {len(items)} 项素材")
        self._polish_buttons()

    # ---------- 操作 ----------
    def _on_upload(self):
        if not self.manager:
            QMessageBox.warning(self, "提示", "未初始化素材管理器")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择素材文件", "", "图片/视频/音频 (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.mp4 *.mov *.mp3 *.wav *.m4a)"
        )
        if not files:
            return
        scope = self.scope_combo.currentData() or "project"
        if scope == "all":
            scope = "project" if self.manager.project_dir else "global"
        count = 0
        for f in files:
            it = self.manager.add_asset(
                src_path=f, source=ASSET_SOURCE_UPLOAD, scope=scope
            )
            if it:
                count += 1
        if count:
            self.refresh()
            QMessageBox.information(self, "完成", f"已上传 {count} 个素材")
        else:
            QMessageBox.warning(self, "失败", "素材上传失败，请查看日志")

    def _on_scan(self):
        if not self.manager or not self.manager.project_dir:
            QMessageBox.warning(self, "提示", "请先在「项目」页加载项目，再扫描项目内旧资产")
            return
        n = self.manager.scan_existing_assets(force=True)
        self.refresh()
        QMessageBox.information(self, "扫描完成", f"共新增 {n} 项素材到项目索引")

    def _on_delete(self, asset_id: str):
        if not self.manager:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            "确认删除此素材？实体文件也会一并删除，操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self.manager.remove_asset(asset_id, delete_file=True):
            self.refresh()
        else:
            QMessageBox.warning(self, "失败", "素材删除失败，未找到对应记录")

    def _on_edit(self, asset_id: str):
        if not self.manager:
            return
        items = self.manager.list_assets(scope="all")
        target = next((it for it in items if it.id == asset_id), None)
        if not target:
            QMessageBox.warning(self, "失败", "未找到素材")
            return
        dlg = AssetEditDialog(target, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.values()
            ok = self.manager.update_asset(asset_id, **vals)
            if ok:
                self.refresh()
            else:
                QMessageBox.warning(self, "失败", "更新失败")

    def _on_use(self, asset_id: str):
        if not self.manager:
            return
        items = self.manager.list_assets(scope="all")
        target = next((it for it in items if it.id == asset_id), None)
        if not target or not target.path or not os.path.exists(target.path):
            QMessageBox.warning(self, "提示", "素材文件不存在，无法使用")
            return
        self.asset_selected.emit(target.id, target.path)
        QMessageBox.information(
            self, "已选择",
            f"已选中素材：{target.name}\n"
            f"路径：{target.path}\n\n"
            "稍后将支持直接拖拽到分镜卡片使用（P2.3）。"
        )
