from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction
import os
from ui import theme as _theme

class CharacterCardWidget(QFrame):
    clicked = pyqtSignal(str) # Emits character ID
    deleted = pyqtSignal(str) # Emits character ID

    def __init__(self, character, parent=None):
        super().__init__(parent)
        self.character = character
        self.init_ui()

    def init_ui(self):
        self.setFixedSize(180, 260)
        self.setStyleSheet("""
            CharacterCardWidget {
                background-color: """ + _theme.color("panel") + """;
                border-radius: 10px;
            }
            QLabel { """ + _theme.color("text") + """; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Avatar Area
        self.avatar_area = QFrame()
        self.avatar_area.setStyleSheet("background-color: " + _theme.color("panel2") + "; border-radius: 8px;")
        self.avatar_area.setFixedSize(160, 160)
        
        avatar_layout = QVBoxLayout(self.avatar_area)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        
        if self.character.avatar_path and os.path.exists(self.character.avatar_path):
            img_lbl = QLabel()
            pix = QPixmap(self.character.avatar_path)
            img_lbl.setPixmap(pix.scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar_layout.addWidget(img_lbl)
        else:
            # Placeholder
            icon_lbl = QLabel("👤")
            icon_lbl.setStyleSheet("font-size: 40px; color: " + _theme.color("text_sub") + ";")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar_layout.addWidget(icon_lbl)
            
            set_btn = QPushButton("设置形象")
            set_btn.setStyleSheet("background: transparent; color: " + _theme.color("text_sub") + "; border: 1px solid " + _theme.color("text_sub") + "; border-radius: 15px; padding: 5px 10px; font-size: 12px;")
            set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            set_btn.clicked.connect(self.emit_clicked)
            
            btn_container = QHBoxLayout()
            btn_container.addStretch()
            btn_container.addWidget(set_btn)
            btn_container.addStretch()
            avatar_layout.addLayout(btn_container)

        layout.addWidget(self.avatar_area)
        
        # Info Area
        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 5, 0, 0)
        
        name_lbl = QLabel(self.character.name)
        name_lbl.setStyleSheet("font-weight: bold; font-size: 16px;")
        info_row.addWidget(name_lbl)
        
        info_row.addStretch()
        
        self.del_btn = QPushButton("✕")
        self.del_btn.setFixedSize(28, 28)
        self.del_btn.setToolTip("删除角色")
        self.del_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(231, 76, 60, 0.95); color: """ + _theme.color("accent_text") + """;
                border: 2px solid white;
                border-radius: 14px;
                font-weight: bold;
                font-size: 12px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 1);
                border-color: """ + _theme.color("warning") + """;
            }
            QPushButton:pressed {
                background-color: rgba(192, 57, 43, 1);
            }
        """)
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_btn.clicked.connect(self.on_delete_clicked)
        info_row.addWidget(self.del_btn)
        
        layout.addLayout(info_row)
        
        details_lbl = QLabel(f"{self.character.gender or '未知'}, {self.character.age or '未知'}")
        details_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        layout.addWidget(details_lbl)
        
        voice_lbl = QLabel(f"🔊 {self.character.voice_id or '未设置配音'}")
        voice_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        layout.addWidget(voice_lbl)
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def on_delete_clicked(self):
        self.deleted.emit(self.character.id)

    def emit_clicked(self):
        self.clicked.emit(self.character.id)

    def mousePressEvent(self, event):
        # Check if the click is on the delete button or its child
        widget = self.childAt(event.pos())
        if widget and (widget == self.del_btn or widget.parent() == self.del_btn):
            # Click is on delete button, don't emit card click
            super().mousePressEvent(event)
            return
            
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.character.id)
        super().mousePressEvent(event)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        delete_action = QAction("删除角色", self)
        delete_action.triggered.connect(lambda: self.deleted.emit(self.character.id))
        menu.addAction(delete_action)
        menu.exec(self.mapToGlobal(pos))
