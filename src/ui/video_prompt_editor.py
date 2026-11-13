from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QSpinBox, QDoubleSpinBox, QScrollArea, QWidget,
    QFrame, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from core.storyboard.storyboard_model import VideoPromptSegment
from ui import theme as _theme


class VideoSegmentWidget(QWidget):
    """单个视频时间段编辑控件"""
    deleted = pyqtSignal(object)  # 发送自身引用
    
    def __init__(self, segment: VideoPromptSegment, index: int, parent=None):
        super().__init__(parent)
        self.segment = segment
        self.index = index
        self.init_ui()
    
    def init_ui(self):
        self.setStyleSheet("""
            VideoSegmentWidget {
                background-color: """ + _theme.color("panel2") + """;
                border-radius: 5px;
                border: 1px solid """ + _theme.color("border_strong") + """;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # 顶部：时间范围和删除按钮
        header_layout = QHBoxLayout()
        
        time_label = QLabel(f"<b>时间段 {self.index + 1}</b>")
        time_label.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 13px;")
        header_layout.addWidget(time_label)
        
        header_layout.addStretch()
        
        # 开始时间
        start_label = QLabel("开始:")
        start_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        header_layout.addWidget(start_label)
        
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0, 60)
        self.start_spin.setDecimals(1)
        self.start_spin.setValue(self.segment.start_time)
        self.start_spin.setSuffix("秒")
        self.start_spin.setStyleSheet("""
            QDoubleSpinBox {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                padding: 3px;
                min-width: 60px;
            }
        """)
        self.start_spin.valueChanged.connect(self.on_start_changed)
        header_layout.addWidget(self.start_spin)
        
        # 结束时间
        end_label = QLabel("结束:")
        end_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        header_layout.addWidget(end_label)
        
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.1, 60)
        self.end_spin.setDecimals(1)
        self.end_spin.setValue(self.segment.end_time)
        self.end_spin.setSuffix("秒")
        self.end_spin.setStyleSheet("""
            QDoubleSpinBox {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                padding: 3px;
                min-width: 60px;
            }
        """)
        self.end_spin.valueChanged.connect(self.on_end_changed)
        header_layout.addWidget(self.end_spin)
        
        # 删除按钮
        delete_btn = QPushButton("×")
        delete_btn.setFixedSize(24, 24)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("danger") + """; color: """ + _theme.color("text") + """;
                border: none;
                border-radius: 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("danger") + """;
            }
        """)
        delete_btn.clicked.connect(self.on_delete)
        header_layout.addWidget(delete_btn)
        
        layout.addLayout(header_layout)
        
        # 描述输入
        desc_label = QLabel("画面描述:")
        desc_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        layout.addWidget(desc_label)
        
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlainText(self.segment.description)
        self.desc_edit.setPlaceholderText("描述这个时间段内的镜头运动和画面变化...")
        self.desc_edit.setMaximumHeight(80)
        self.desc_edit.setStyleSheet("""
            QTextEdit {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                border-radius: 3px;
                padding: 5px;
                font-size: 12px;
            }
        """)
        self.desc_edit.textChanged.connect(self.on_desc_changed)
        layout.addWidget(self.desc_edit)
        
        # 时间范围预览
        self.time_preview = QLabel(self.segment.format_time_range())
        self.time_preview.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 10px;")
        layout.addWidget(self.time_preview)
    
    def on_start_changed(self, value):
        self.segment.start_time = value
        if value >= self.segment.end_time:
            self.segment.end_time = value + 0.5
            self.end_spin.setValue(self.segment.end_time)
        self.update_preview()
    
    def on_end_changed(self, value):
        self.segment.end_time = value
        if value <= self.segment.start_time:
            self.segment.start_time = value - 0.5
            if self.segment.start_time < 0:
                self.segment.start_time = 0
            self.start_spin.setValue(self.segment.start_time)
        self.update_preview()
    
    def on_desc_changed(self):
        self.segment.description = self.desc_edit.toPlainText()
    
    def on_delete(self):
        self.deleted.emit(self)
    
    def update_preview(self):
        self.time_preview.setText(self.segment.format_time_range())
    
    def update_index(self, new_index):
        """更新序号显示"""
        self.index = new_index
        # 更新标签
        for child in self.children():
            if isinstance(child, QHBoxLayout):
                for i in range(child.count()):
                    widget = child.itemAt(i).widget()
                    if isinstance(widget, QLabel) and "时间段" in widget.text():
                        widget.setText(f"<b>时间段 {self.index + 1}</b>")
                        break


class VideoPromptEditorDialog(QDialog):
    """视频提示词编辑器对话框"""
    
    def __init__(self, segments, duration=10.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑视频提示词")
        self.resize(700, 600)
        self.duration = duration
        self.segments = []
        
        # 复制传入的分段
        for seg in segments:
            self.segments.append(VideoPromptSegment(
                start_time=seg.start_time,
                end_time=seg.end_time,
                description=seg.description
            ))
        
        self.segment_widgets = []
        self.init_ui()
    
    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: """ + _theme.color("bg") + """;
            }
            QLabel {
color: """ + _theme.color("text") + """;
            }
            QPushButton {
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 标题
        title = QLabel("🎬 视频提示词编辑器")
        title.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 18px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 说明
        desc = QLabel("按秒分段描述视频内容，让AI更精准地生成每一帧画面")
        desc.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        
        # 视频时长设置
        duration_layout = QHBoxLayout()
        duration_label = QLabel("视频总时长:")
        duration_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 13px;")
        duration_layout.addWidget(duration_label)
        
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(1, 60)
        self.duration_spin.setDecimals(1)
        self.duration_spin.setValue(self.duration)
        self.duration_spin.setSuffix(" 秒")
        self.duration_spin.setStyleSheet("""
            QDoubleSpinBox {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("border_strong") + """;
                padding: 5px;
                min-width: 80px;
            }
        """)
        self.duration_spin.valueChanged.connect(self.on_duration_changed)
        duration_layout.addWidget(self.duration_spin)
        
        duration_layout.addStretch()
        
        # 自动分段按钮
        auto_split_btn = QPushButton("🔄 自动分段")
        auto_split_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("accent2") + """; color: """ + _theme.color("accent_text") + """;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("accent2") + """;
            }
        """)
        auto_split_btn.clicked.connect(self.auto_split_segments)
        duration_layout.addWidget(auto_split_btn)
        
        layout.addLayout(duration_layout)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: " + _theme.color("panel2") + ";")
        line.setFixedHeight(2)
        layout.addWidget(line)
        
        # 分段列表区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        self.segments_container = QWidget()
        self.segments_layout = QVBoxLayout(self.segments_container)
        self.segments_layout.setContentsMargins(0, 0, 0, 0)
        self.segments_layout.setSpacing(10)
        self.segments_layout.addStretch()
        
        scroll.setWidget(self.segments_container)
        layout.addWidget(scroll, 1)
        
        # 添加分段按钮
        add_btn_layout = QHBoxLayout()
        add_btn_layout.addStretch()
        
        add_segment_btn = QPushButton("➕ 添加时间段")
        add_segment_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("success") + """; color: """ + _theme.color("accent_text") + """;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("accent_strong") + """;
            }
        """)
        add_segment_btn.clicked.connect(self.add_segment)
        add_btn_layout.addWidget(add_segment_btn)
        
        add_btn_layout.addStretch()
        layout.addLayout(add_btn_layout)
        
        # 预览区域
        preview_frame = QFrame()
        preview_frame.setStyleSheet("""
            QFrame {
                background-color: """ + _theme.color("panel") + """;
                border-radius: 5px;
                border: 1px solid """ + _theme.color("border_strong") + """;
            }
        """)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        
        preview_label = QLabel("📋 预览")
        preview_label.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 12px; font-weight: bold;")
        preview_layout.addWidget(preview_label)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(100)
        self.preview_text.setStyleSheet("""
            QTextEdit {
                background-color: """ + _theme.color("bg") + """;
                color: """ + _theme.color("text_sub") + """;
                border: 1px solid """ + _theme.color("panel2") + """;
                border-radius: 3px;
                padding: 5px;
                font-size: 11px;
            }
        """)
        preview_layout.addWidget(self.preview_text)
        
        layout.addWidget(preview_frame)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("text_sub") + """; color: """ + _theme.color("text") + """;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("text_sub") + """;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("保存")
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("warning") + """;
                color: """ + _theme.color("panel") + """;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("warning") + """;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        layout.addLayout(btn_layout)
        
        # 初始化显示现有分段
        self.refresh_segments_display()
    
    def refresh_segments_display(self):
        """刷新分段显示"""
        # 清除现有控件（保留stretch）
        while self.segments_layout.count() > 1:
            item = self.segments_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.segment_widgets.clear()
        
        # 按开始时间排序
        self.segments.sort(key=lambda x: x.start_time)
        
        # 创建控件
        for i, segment in enumerate(self.segments):
            widget = VideoSegmentWidget(segment, i, self)
            widget.deleted.connect(self.on_segment_deleted)
            self.segment_widgets.append(widget)
            self.segments_layout.insertWidget(i, widget)
        
        self.update_preview()
    
    def on_segment_deleted(self, widget):
        """处理分段删除"""
        if len(self.segments) <= 1:
            QMessageBox.warning(self, "提示", "至少保留一个时间段")
            return
        
        # 找到并移除
        for i, w in enumerate(self.segment_widgets):
            if w == widget:
                self.segments.pop(i)
                self.segment_widgets.pop(i)
                widget.deleteLater()
                break
        
        # 更新序号
        for i, w in enumerate(self.segment_widgets):
            w.update_index(i)
        
        self.update_preview()
    
    def add_segment(self):
        """添加新分段"""
        # 计算新分段的开始时间
        if self.segments:
            last_end = max(seg.end_time for seg in self.segments)
            start_time = min(last_end, self.duration - 1)
            end_time = min(start_time + 1, self.duration)
        else:
            start_time = 0
            end_time = min(2, self.duration)
        
        new_segment = VideoPromptSegment(
            start_time=start_time,
            end_time=end_time,
            description=""
        )
        self.segments.append(new_segment)
        
        # 刷新显示
        self.refresh_segments_display()
    
    def auto_split_segments(self):
        """自动分段"""
        from core.storyboard.prompt_factory import generate_default_video_segments
        
        self.segments = generate_default_video_segments(self.duration)
        self.refresh_segments_display()
    
    def on_duration_changed(self, value):
        """视频时长改变"""
        self.duration = value
        # 调整超出范围的分段
        for seg in self.segments:
            if seg.end_time > value:
                seg.end_time = value
            if seg.start_time >= value:
                seg.start_time = max(0, value - 1)
                seg.end_time = value
        
        self.refresh_segments_display()
    
    def update_preview(self):
        """更新预览文本"""
        lines = []
        for seg in sorted(self.segments, key=lambda x: x.start_time):
            lines.append(str(seg))
        
        self.preview_text.setPlainText("\n".join(lines) if lines else "暂无内容")
    
    def get_segments(self):
        """获取编辑后的分段列表"""
        # 按开始时间排序
        self.segments.sort(key=lambda x: x.start_time)
        return self.segments
    
    def get_duration(self):
        """获取设置的视频时长"""
        return self.duration
