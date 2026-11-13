from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTabWidget, QLabel,
                             QPushButton,
                             QTextEdit,
                             QDialog, QHBoxLayout,
                             QComboBox, QCheckBox, QFileDialog, QSplitter)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCharFormat
from datetime import datetime
from core.utils.log_manager import log_manager
from ui import theme as _theme


class LogViewerWidget(QWidget):
    """日志查看器组件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.connect_log_signals()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 工具栏
        toolbar_layout = QHBoxLayout()

        # 日志级别过滤
        self.level_filter = QComboBox()
        self.level_filter.addItems(["全部", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.level_filter.currentTextChanged.connect(self.on_filter_changed)
        self.level_filter.setStyleSheet("""
            QComboBox QAbstractItemView {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                selection-background-color: """ + _theme.color("accent") + """;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
        """)
        toolbar_layout.addWidget(QLabel("日志级别:"))
        toolbar_layout.addWidget(self.level_filter)

        # 自动滚动选项
        self.auto_scroll_cb = QCheckBox("自动滚动")
        self.auto_scroll_cb.setChecked(True)
        toolbar_layout.addWidget(self.auto_scroll_cb)

        toolbar_layout.addStretch()

        # 清空按钮
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.clear_logs)
        toolbar_layout.addWidget(clear_btn)

        # 导出按钮
        export_btn = QPushButton("导出日志")
        export_btn.clicked.connect(self.export_logs)
        toolbar_layout.addWidget(export_btn)

        layout.addLayout(toolbar_layout)

        # 日志显示区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: %s;
                color: %s;
                border: 1px solid %s;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                line-height: 1.5;
            }
        """ % (_theme.color("panel"), _theme.color("text"), _theme.color("border")))
        layout.addWidget(self.log_text)

        # 状态栏
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: " + _theme.color("text_sub") + ";")
        layout.addWidget(self.status_label)

        # 加载现有日志
        self.load_existing_logs()

    def connect_log_signals(self):
        """连接日志信号"""
        log_manager.log_emitter.log_signal.connect(self.on_log_received)

    def on_log_received(self, message: str, level: str):
        """接收到新日志时的处理"""
        # 根据过滤条件决定是否显示
        filter_level = self.level_filter.currentText()
        if filter_level != "全部" and filter_level != level:
            return

        # 格式化日志文本
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}"

        # 设置颜色格式
        color = self.get_level_color(level)
        self.append_colored_text(log_entry, color)

        # 更新状态栏
        self.status_label.setText(f"最后更新: {timestamp} | 总条目: {len(log_manager.log_entries)}")

        # 自动滚动
        if self.auto_scroll_cb.isChecked():
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )

    def get_level_color(self, level: str) -> QColor:
        """获取日志级别对应的颜色"""
        colors = {
            "DEBUG": QColor(_theme.color("text_sub")),   # 次级文字
            "INFO": QColor(_theme.color("info")),        # 信息色
            "WARNING": QColor(_theme.color("warning")),  # 警告色
            "ERROR": QColor(_theme.color("danger")),     # 危险色
            "CRITICAL": QColor(_theme.color("danger")),  # 危险色
        }
        return colors.get(level, QColor(_theme.color("text")))

    def append_colored_text(self, text: str, color: QColor):
        """添加带颜色的文本"""
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)

        format = QTextCharFormat()
        format.setForeground(color)

        cursor.insertText(text + "\n", format)
        self.log_text.setTextCursor(cursor)

    def load_existing_logs(self):
        """加载已有的日志条目"""
        self.log_text.clear()
        entries = log_manager.get_log_entries(limit=100)

        filter_level = self.level_filter.currentText()

        for entry in entries:
            if filter_level != "全部" and filter_level != entry['level']:
                continue

            log_entry = f"[{entry['timestamp']}] [{entry['level']}] {entry['message']}"
            color = self.get_level_color(entry['level'])
            self.append_colored_text(log_entry, color)

        # 滚动到底部
        if self.auto_scroll_cb.isChecked():
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )

    def on_filter_changed(self, level: str):
        """日志级别过滤改变"""
        self.load_existing_logs()

    def clear_logs(self):
        """清空日志"""
        log_manager.clear_logs()
        self.log_text.clear()
        self.status_label.setText("日志已清空")

    def export_logs(self):
        """导出日志"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出日志",
            f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            log_manager.export_logs(file_path)

class HelpWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid """ + _theme.color("panel2") + """; background: """ + _theme.color("panel2") + """; }
            QTabBar::tab { background: """ + _theme.color("panel2") + """; color: """ + _theme.color("text_sub") + """; padding: 10px 20px; }
            QTabBar::tab:selected { background: """ + _theme.color("panel2") + """; color: """ + _theme.color("warning") + """; border-bottom: 2px solid """ + _theme.color("warning") + """; }
            QWidget { background-color: """ + _theme.color("panel2") + """; }
        """)
        
        # Tab 1: About
        self.about_tab = QWidget()
        self.init_about_tab()
        self.tabs.addTab(self.about_tab, "关于")
        
        # Tab 2: Help
        self.help_tab = QWidget()
        self.init_help_tab()
        self.tabs.addTab(self.help_tab, "帮助")
        
        # Tab 3: Logs
        self.logs_tab = QWidget()
        self.init_logs_tab()
        self.tabs.addTab(self.logs_tab, "运行日志")

        layout.addWidget(self.tabs)

    def init_about_tab(self):
        layout = QVBoxLayout(self.about_tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("狸猫短剧 (Dragonli)")
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px; color: " + _theme.color("text") + ";")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        version = QLabel("版本: v1.0.0 (Preview)")
        version.setStyleSheet("font-size: 14px; color: " + _theme.color("text_sub") + ";")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        desc = QLabel("一款基于大语言模型的全流程AI短剧创作工具。\n\n"
                      "核心功能：\n"
                      "1. 剧本生成：一键生成分集剧情与对话\n"
                      "2. 角色定制：个性化角色形象与声音设定\n"
                      "3. 分镜制作：自动拆解剧本，生成AI绘画提示词\n"
                      "4. 视频合成：多模态融合，生成最终短剧视频\n\n"
                      "技术支持：\n"
                      "基于 PyQt6 + OpenAI/Claude + Veo/Sora 等先进技术构建。")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("margin: 20px; color: " + _theme.color("text") + "; font-size: 14px; line-height: 1.5;")
        
        copyright = QLabel("© 2025 AI Drama Studio. All rights reserved.\n联系我们: frank36512@gmail.com")
        copyright.setStyleSheet("color: " + _theme.color("text_sub") + "; margin-top: 20px;")
        copyright.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(version)
        layout.addWidget(desc)
        layout.addWidget(copyright)
        layout.addStretch()

    def init_help_tab(self):
        layout = QVBoxLayout(self.help_tab)
        
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setStyleSheet("""
            QTextEdit {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                border: none;
                padding: 15px;
                font-size: 14px;
                line-height: 1.6;
            }
        """)
        help_text.setMarkdown("""
# 狸猫短剧 (Dragonli) - 使用指南

## 1. 快速开始
- **新建项目**：在"项目管理"页点击"新建项目"，填写项目名称和简介。
- **生成大纲**：进入项目后，点击"生成大纲"获取初步故事结构。

## 2. 剧本创作流程
1. **分集剧情**：在左侧列表选择集数，输入本集摘要。
2. **智能生成**：点击"智能生成"按钮，AI将自动编写对话和动作。
3. **人工润色**：在右侧编辑器中直接修改内容，支持实时保存。

## 3. 角色设定
- **添加角色**：点击"添加角色"，填写姓名、性别、性格特征。
- **形象定制**：上传参考图或使用AI生成角色头像。
- **声音配置**：选择合适的音色（支持多种语言和情感）。

## 4. 分镜与视频
- **自动拆解**：系统自动将剧本拆解为分镜。
- **提示词优化**：支持手动修改每个分镜的视频提示词。
- **生成视频**：以角色/道具/场景参考图配合视频提示词，直接生成分镜视频。

## 5. 合成成片
- **编辑与配音**：在视频编辑器中完成配音、字幕与片段调整。
- **导出视频**：点击"开始合成"，生成最终的 MP4 视频文件。

## 常见问题
- **Q: 生成速度慢？** A: 取决于网络状态和所选模型的响应速度。
- **Q: 角色画面不一致？** A: 请先在「角色」页生成或上传角色参考图，生成视频时会作为参考图保持形象一致。
        """)
        layout.addWidget(help_text)

    def init_logs_tab(self):
        """初始化运行日志选项卡"""
        layout = QVBoxLayout(self.logs_tab)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建日志查看器
        self.log_viewer = LogViewerWidget()
        layout.addWidget(self.log_viewer)
