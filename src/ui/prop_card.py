from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction
import os
from ui import theme as _theme

class PropCardWidget(QFrame):
    clicked = pyqtSignal(str)
    deleted = pyqtSignal(str)

    def __init__(self, prop, parent=None):
        super().__init__(parent)
        self.prop = prop
        self.init_ui()

    def init_ui(self):
        self.setFixedSize(180, 240)
        self.setStyleSheet("""
            PropCardWidget {
                background-color: """ + _theme.color("panel") + """;
                border-radius: 10px;
            }
            QLabel { """ + _theme.color("text") + """; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.image_area = QFrame()
        self.image_area.setStyleSheet("background-color: " + _theme.color("panel2") + "; border-radius: 8px;")
        self.image_area.setFixedSize(160, 140)
        
        image_layout = QVBoxLayout(self.image_area)
        image_layout.setContentsMargins(0, 0, 0, 0)
        
        # Prop 模型没有 image_path 字段，用 front_view / reference_image 兜底
        _prop_img = getattr(self.prop, 'front_view', '') or getattr(self.prop, 'reference_image', '') or ""
        if _prop_img and os.path.exists(_prop_img):
            img_lbl = QLabel()
            pix = QPixmap(_prop_img)
            img_lbl.setPixmap(pix.scaled(160, 140, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_layout.addWidget(img_lbl)
        else:
            icon_lbl = QLabel("🎁")
            icon_lbl.setStyleSheet("font-size: 40px; color: " + _theme.color("text_sub") + ";")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_layout.addWidget(icon_lbl)
            
            set_btn = QPushButton("设置图片")
            set_btn.setStyleSheet("background: transparent; color: " + _theme.color("text_sub") + "; border: 1px solid " + _theme.color("text_sub") + "; border-radius: 15px; padding: 5px 10px; font-size: 12px;")
            set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            set_btn.clicked.connect(self.emit_clicked)
            
            btn_container = QHBoxLayout()
            btn_container.addStretch()
            btn_container.addWidget(set_btn)
            btn_container.addStretch()
            image_layout.addLayout(btn_container)

        layout.addWidget(self.image_area)
        
        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 5, 0, 0)
        
        name_lbl = QLabel(self.prop.name)
        name_lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        info_row.addWidget(name_lbl)
        
        info_row.addStretch()
        
        del_btn = QPushButton("×")
        del_btn.setFixedSize(24, 24)
        del_btn.setToolTip("删除道具")
        del_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent; 
                color: """ + _theme.color("text_sub") + """; 
                border: none; 
                font-weight: bold;
                font-size: 18px;
            }
            QPushButton:hover {
                color: """ + _theme.color("danger") + """;
                background-color: rgba(231, 76, 60, 0.1);
                border-radius: 4px;
            }
        """)
        del_btn.clicked.connect(self.on_delete_clicked)
        info_row.addWidget(del_btn)
        
        layout.addLayout(info_row)
        
        category_lbl = QLabel(f"{self.prop.category or '未分类'}")
        category_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        layout.addWidget(category_lbl)
        
        desc_lbl = QLabel(self.prop.description[:30] + "..." if len(self.prop.description) > 30 else self.prop.description)
        desc_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        layout.addWidget(desc_lbl)
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def on_delete_clicked(self):
        self.deleted.emit(self.prop.id)

    def emit_clicked(self):
        self.clicked.emit(self.prop.id)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.prop.id)
        super().mousePressEvent(event)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        delete_action = QAction("删除道具", self)
        delete_action.triggered.connect(lambda: self.deleted.emit(self.prop.id))
        menu.addAction(delete_action)
        menu.exec(self.mapToGlobal(pos))
