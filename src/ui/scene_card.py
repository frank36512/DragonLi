from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction
import os
from ui import theme as _theme

class SceneCardWidget(QWidget):
    clicked = pyqtSignal(str) # scene_id
    deleted = pyqtSignal(str) # scene_id
    edited = pyqtSignal(str)  # scene_id

    def __init__(self, scene):
        super().__init__()
        self.scene = scene
        self.setFixedSize(200, 280)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Card Container
        self.container = QWidget()
        self.container.setStyleSheet("""
            QWidget {
                background-color: """ + _theme.color("panel2") + """;
                border-radius: 10px;
            }
            QWidget:hover {
                background-color: """ + _theme.color("hover") + """;
            }
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        
        # Image
        self.img_lbl = QLabel()
        self.img_lbl.setFixedSize(180, 180)
        self.img_lbl.setStyleSheet("background-color: " + _theme.color("panel") + "; border-radius: 5px;")
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Scene 模型没有 image_path 字段，用 close_view / reference_image / wide_view 兜底
        _scene_img = (getattr(self.scene, 'close_view', '') or getattr(self.scene, 'reference_image', '')
                      or getattr(self.scene, 'wide_view', '') or "")
        if _scene_img and os.path.exists(_scene_img):
            pixmap = QPixmap(_scene_img)
            self.img_lbl.setPixmap(pixmap.scaled(
                self.img_lbl.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
        else:
            self.img_lbl.setText("无图片")
            self.img_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; background-color: " + _theme.color("panel") + "; border-radius: 5px;")
            
        container_layout.addWidget(self.img_lbl)
        
        # Info
        info_layout = QVBoxLayout()
        name_lbl = QLabel(self.scene.name)
        name_lbl.setStyleSheet("font-weight: bold; color: " + _theme.color("text") + "; font-size: 14px; background: transparent;")
        name_lbl.setWordWrap(True)
        
        desc_lbl = QLabel(self.scene.description[:30] + "..." if len(self.scene.description) > 30 else self.scene.description)
        desc_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px; background: transparent;")
        desc_lbl.setWordWrap(True)
        
        info_layout.addWidget(name_lbl)
        info_layout.addWidget(desc_lbl)
        container_layout.addLayout(info_layout)
        
        layout.addWidget(self.container)
        
        # Context Menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.scene.id)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("panel2") + """;
            }
            QMenu::item:selected {
                background-color: """ + _theme.color("warning") + """;
                color: """ + _theme.color("panel") + """;
            }
        """)
        
        edit_action = QAction("编辑", self)
        edit_action.triggered.connect(lambda: self.edited.emit(self.scene.id))
        menu.addAction(edit_action)
        
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: self.deleted.emit(self.scene.id))
        menu.addAction(delete_action)
        
        menu.exec(self.mapToGlobal(pos))
