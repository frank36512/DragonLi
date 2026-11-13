from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QComboBox, QScrollArea, 
                             QGridLayout, QFrame, QFileDialog, QMessageBox, QTextEdit)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
import os
import shutil
import uuid
from ui import theme as _theme

class PropLibraryDialog(QDialog):
    def __init__(self, prop, parent=None):
        super().__init__(parent)
        self.setWindowTitle("道具设定")
        self.resize(800, 600)
        self.prop = prop
        # Prop 模型没有 image_path 字段，用 reference_image / front_view 兜底
        self.selected_image = getattr(prop, 'reference_image', '') or getattr(prop, 'front_view', '') or ""
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        sidebar = QFrame()
        sidebar.setFixedWidth(300)
        sidebar.setStyleSheet("background-color: " + _theme.color("panel") + "; color: " + _theme.color("text") + "; border-right: 1px solid " + _theme.color("panel2") + ";")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 20, 20, 20)
        sidebar_layout.setSpacing(15)

        self.image_lbl = QLabel("点击选择图片")
        self.image_lbl.setFixedSize(260, 260)
        self.image_lbl.setStyleSheet("""
            QLabel {
                background-color: """ + _theme.color("panel2") + """;
                color: """ + _theme.color("text_sub") + """;
                border: 2px dashed """ + _theme.color("text_sub") + """;
                border-radius: 10px;
                font-size: 14px;
            }
            QLabel:hover {
                border-color: """ + _theme.color("warning") + """;
                color: """ + _theme.color("warning") + """;
            }
        """)
        self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_lbl.mousePressEvent = self.select_image
        self.update_image_preview()
        sidebar_layout.addWidget(self.image_lbl)

        sidebar_layout.addWidget(QLabel("道具名称"))
        self.name_edit = QLineEdit(self.prop.name)
        self.name_edit.setStyleSheet("padding: 8px; background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 4px;")
        sidebar_layout.addWidget(self.name_edit)

        sidebar_layout.addWidget(QLabel("分类"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(["武器", "服装", "道具", "交通工具", "电子产品", "食品", "装饰品", "其他"])
        if self.prop.category:
            self.category_combo.setCurrentText(self.prop.category)
        self.category_combo.setStyleSheet("""
            QComboBox {
                padding: 8px; 
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """; 
                border: 1px solid """ + _theme.color("border_strong") + """; 
                border-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                selection-background-color: """ + _theme.color("accent") + """;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
        """)
        sidebar_layout.addWidget(self.category_combo)

        sidebar_layout.addStretch()
        
        confirm_btn = QPushButton("确定")
        confirm_btn.setFixedSize(260, 40)
        confirm_btn.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; border-radius: 5px; font-size: 16px;")
        confirm_btn.clicked.connect(self.accept_changes)
        sidebar_layout.addWidget(confirm_btn)

        main_layout.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("ThemedDialog")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)

        header_layout = QHBoxLayout()
        title = QLabel("道具描述")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: " + _theme.color("text") + ";")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        close_btn = QPushButton("×")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("background: transparent; color: " + _theme.color("text") + "; font-size: 20px; border: none;")
        close_btn.clicked.connect(self.reject)
        header_layout.addWidget(close_btn)
        content_layout.addLayout(header_layout)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("详细描述道具的外观、材质、颜色等特点...")
        self.description_edit.setText(self.prop.description)
        self.description_edit.setStyleSheet("""
            QTextEdit {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
            }
        """)
        content_layout.addWidget(self.description_edit)

        main_layout.addWidget(content)

    def select_image(self, event):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.selected_image = path
            self.update_image_preview()

    def update_image_preview(self):
        if self.selected_image and os.path.exists(self.selected_image):
            pix = QPixmap(self.selected_image)
            self.image_lbl.setPixmap(pix.scaled(260, 260, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
        else:
            self.image_lbl.setText("点击选择图片")

    def accept_changes(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "提示", "请输入道具名称")
            return
        
        self.prop.name = self.name_edit.text().strip()
        self.prop.category = self.category_combo.currentText()
        self.prop.description = self.description_edit.toPlainText()
        self.prop.reference_image = self.selected_image
        self.accept()
