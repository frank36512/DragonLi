from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QInputDialog, QMessageBox,
                             QGroupBox, QFormLayout, QLineEdit, QDialog, QSpinBox,
                             QTextEdit, QTabWidget, QListWidgetItem, QComboBox, QCheckBox,
                             QProgressDialog, QProgressBar, QApplication, QFileDialog,
                             QPlainTextEdit, QFrame, QButtonGroup, QScrollArea)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, QTimer, QSize
from PyQt6.QtGui import QPainter, QLinearGradient, QColor, QBrush, QPalette
import os
import json
import re
from core.project.project_manager import ProjectManager
from core.config.config_manager import ConfigManager
from core.project.series_manager import SeriesManager
from core.script import script_service
from ai_engine.llm.llm_client import LLMClient
from ui.script_window import ScriptGeneratorThread
from ui.utils import show_message
from ui import theme as _theme


def _is_cancelled():
    """全局协作取消状态（用户点过「停止」）。线程里用它静默退出，不弹错误框。"""
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
    """清除全局协作取消标记（开始新任务时调用，避免上一轮「停止」影响新任务）。"""
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


VISUAL_STYLES = [
    "Cinematic (电影质感)",
    "Anime (日系动漫)",
    "3D Animation (3D动画)",
    "Oil Painting (油画风格)",
    "Watercolor (水彩风格)",
    "Cyberpunk (赛博朋克)",
    "Sketch (素描手绘)",
    "Flat Illustration (扁平插画)",
    "Realistic (写实摄影)",
    "Fantasy (奇幻史诗)",
    "Chinese Ink (中国水墨)",
    "Ghibli (吉卜力风格)",
    "Pixel Art (像素风格)",
    "Vintage (复古风格)",
    "Noir (黑色电影)",
    "Impressionism (印象派)",
    "Surrealism (超现实主义)",
    "Ukiyo-e (浮世绘)",
    "Steampunk (蒸汽朋克)",
    "Gothic (哥特风格)"
]

# 超过该字数视为长篇原作，改编时走分块/摘要/RAG 流程
LONG_SOURCE_THRESHOLD = 20000


def is_long_source_text(text):
    """判断文本是否为需要分块处理的长篇原作。"""
    return bool(text) and len(text) >= LONG_SOURCE_THRESHOLD


def _short_source_title(text):
    """从长篇原文提取短标题（首行/前 20 字）。"""
    first_line = (text or "").strip().splitlines()[0] if text else ""
    title = re.sub(r'[\\/:*?"<>|\n\r]', '_', first_line or "长篇改编").strip()
    return (title[:20] or "长篇改编")


def _stylesheet():
    """项目页历史内联样式（每次调用按当前主题求值；当前已统一交由全局主题管理）。"""
    return """
    QWidget {
        font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
        font-size: 14px;
        color: """ + _theme.color("text") + """;
    }
    QListWidget {
        background-color: """ + _theme.color("panel") + """;
        border: 1px solid """ + _theme.color("accent") + """;
        border-radius: 10px;
        padding: 6px;
        color: """ + _theme.color("text") + """;
        outline: none;
    }
    QListWidget::item {
        padding: 10px 12px;
        border-bottom: 1px solid """ + _theme.color("border") + """;
        border-radius: 6px;
        margin: 2px;
    }
    QListWidget::item:selected {
        background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("accent_text") + """;
    }
    QListWidget::item:hover:!selected {
        background-color: """ + _theme.color("accent2") + """;
    }
    QPushButton {
        background-color: """ + _theme.color("accent2") + """; color: """ + _theme.color("accent_text") + """;
        border: none;
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: 600;
    }
    QPushButton:hover { background-color: """ + _theme.color("accent") + """; }
    QPushButton:pressed { background-color: """ + _theme.color("accent_strong") + """; }
    QPushButton:disabled {
        background-color: """ + _theme.color("border_strong") + """;
        color: """ + _theme.color("text_sub") + """;
    }
    QLabel { color: """ + _theme.color("text") + """; background: transparent; }
    QTabWidget::pane {
        border: 1px solid """ + _theme.color("border") + """;
        background: """ + _theme.color("panel") + """;
        border-radius: 10px;
    }
    QTabBar::tab {
        background: """ + _theme.color("panel2") + """;
        color: """ + _theme.color("text_sub") + """;
        padding: 8px 20px;
        border: 1px solid """ + _theme.color("border") + """;
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background: """ + _theme.color("accent") + """; color: """ + _theme.color("accent_text") + """;
        font-weight: bold;
    }
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
        border: 1px solid """ + _theme.color("border_strong") + """;
        border-radius: 8px;
        padding: 6px 8px;
        background: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
    }
    QComboBox QAbstractItemView {
        background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
        selection-background-color: """ + _theme.color("accent") + """;
        border: 1px solid """ + _theme.color("border") + """;
    }
    QComboBox QAbstractItemView::item:hover {
        background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("accent_text") + """;
    }
    QGroupBox {
        border: 1px solid """ + _theme.color("border_strong") + """;
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 16px;
        font-weight: bold;
        color: """ + _theme.color("text") + """;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
        left: 10px;
    }
    QScrollArea { background: transparent; border: none; }
    QScrollBar:vertical {
        background: transparent; width: 8px;
    }
    QScrollBar::handle:vertical {
        background: """ + _theme.color("border_strong") + """; border-radius: 4px; min-height: 30px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def _home_hero_card():
    """首页 Hero 卡样式（每次调用按当前主题求值）。"""
    return """
    QFrame#HeroCard {
        background: """ + _theme.color("panel") + """;
        border: 1px solid """ + _theme.color("accent") + """;
        border-radius: 16px;
    }
"""

class EditProjectDialog(QDialog):
    def __init__(self, current_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑项目信息")
        self.setMinimumWidth(500)
        self.current_data = current_data
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)
        
        self.title_edit = QLineEdit(self.current_data.get("title", ""))
        layout.addRow("项目名称:", self.title_edit)
        
        # Project Type Selection
        self.type_combo = QComboBox()
        self.type_combo.addItems(["原创短剧 (Original)", "改编短剧 (Adaptation)"])
        
        # Set current selection
        current_type = self.current_data.get("type", "original")
        if current_type == "adaptation":
            self.type_combo.setCurrentIndex(1)
        else:
            self.type_combo.setCurrentIndex(0)
            
        layout.addRow("创作类型:", self.type_combo)
        
        self.genre_edit = QLineEdit(self.current_data.get("genre", ""))
        layout.addRow("故事类型:", self.genre_edit)

        # Visual Style Selection
        self.style_combo = QComboBox()
        self.style_combo.addItems(VISUAL_STYLES)
        self.style_combo.setEditable(True) # Allow custom styles
        
        current_style = self.current_data.get("visual_style", "")
        if current_style:
            index = self.style_combo.findText(current_style)
            if index >= 0:
                self.style_combo.setCurrentIndex(index)
            else:
                self.style_combo.setEditText(current_style)
        
        layout.addRow("画面风格:", self.style_combo)
        
        self.episodes_spin = QSpinBox()
        self.episodes_spin.setRange(1, 1000)
        self.episodes_spin.setValue(int(self.current_data.get("total_episodes", 100)))
        layout.addRow("总集数:", self.episodes_spin)
        
        self.characters_edit = QTextEdit(self.current_data.get("main_characters", ""))
        self.characters_edit.setMaximumHeight(80)
        layout.addRow("主要角色:", self.characters_edit)
        
        self.premise_edit = QTextEdit(self.current_data.get("premise", ""))
        self.premise_edit.setPlaceholderText("一句话故事梗概 (Logline)")
        self.premise_edit.setMaximumHeight(100)
        layout.addRow("核心梗概:", self.premise_edit)
        
        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存修改")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + ";")
        
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def get_data(self):
        project_type = "original" if self.type_combo.currentIndex() == 0 else "adaptation"
        return {
            "title": self.title_edit.text(),
            "type": project_type,
            "genre": self.genre_edit.text(),
            "visual_style": self.style_combo.currentText(),
            "total_episodes": self.episodes_spin.value(),
            "main_characters": self.characters_edit.toPlainText(),
            "premise": self.premise_edit.toPlainText()
        }

class OutlineGeneratorThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, api_config, prompt, system_prompt=None):
        super().__init__()
        self.api_config = api_config
        self.prompt = prompt
        self.system_prompt = system_prompt

    def run(self):
        try:
            api_key = self.api_config.get("api_key")
            base_url = self.api_config.get("base_url")
            model = self.api_config.get("model")
            client = LLMClient(api_key=api_key, base_url=base_url, model=model)
            
            result = client.generate_script(self.prompt, system_prompt=self.system_prompt)
            if result:
                result = result.strip()
                # 大纲是 Markdown，不做 JSON 截断/花括号校验。
                # 仅当结果看起来像 JSON 时才做简单完整性检查。
                if result.startswith('{'):
                    open_braces = result.count('{') - result.count('}')
                    open_brackets = result.count('[') - result.count(']')
                    if open_braces != 0 or open_brackets != 0:
                        self.error.emit("响应包含未闭合的 JSON 结构，请重试或增加 max_tokens。")
                        return
                # 最小内容校验：防止 LLM 只回显项目名
                import re as _re
                stripped = _re.sub(r'[#*\-\s\d.、，。:：]', '', result)
                if len(stripped) < 30:
                    self.error.emit("LLM 返回内容过短（可能只输出了标题），请重试或更换模型。")
                    return
                self.finished.emit(result)
            elif _is_cancelled():
                return   # 用户点了停止：静默退出，别再报 Empty response
            else:
                self.error.emit("Empty response from LLM")
        except Exception as e:
            if _is_cancelled():
                return   # 断开流导致的连接异常也静默处理
            self.error.emit(str(e))

class GenerateOutlineDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("生成大纲配置")
        self.setMinimumWidth(400)
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)

        # API Config
        self.api_combo = QComboBox()
        self.refresh_api_list()
        layout.addRow("LLM 模型:", self.api_combo)

        # Style
        self.style_edit = QLineEdit()
        self.style_edit.setPlaceholderText("例如：悬疑、幽默、快节奏")
        layout.addRow("风格基调:", self.style_edit)

        # Extra Instructions
        self.instructions_edit = QTextEdit()
        self.instructions_edit.setPlaceholderText("额外的生成要求...")
        self.instructions_edit.setMaximumHeight(100)
        layout.addRow("额外要求:", self.instructions_edit)

        # Buttons
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("开始生成")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def refresh_api_list(self):
        from ui.utils import populate_api_combo
        populate_api_combo(self.api_combo, self.config_manager, "LLM", "未配置 (使用默认)")

    def get_data(self):
        return {
            "api_config": self.api_combo.currentData(),
            "style": self.style_edit.text(),
            "instructions": self.instructions_edit.toPlainText()
        }

class GenerateScriptDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("生成剧本配置")
        self.setMinimumWidth(500)
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)

        # API Config
        self.api_combo = QComboBox()
        self.refresh_api_list()
        layout.addRow("LLM 模型:", self.api_combo)

        # Embedding Config
        self.embedding_combo = QComboBox()
        self.refresh_embedding_list()
        layout.addRow("Embedding 模型:", self.embedding_combo)

        # Idea
        self.idea_edit = QTextEdit()
        self.idea_edit.setPlaceholderText("本集的核心情节、冲突或关键事件...")
        self.idea_edit.setMinimumHeight(80)
        layout.addRow("本集创意:", self.idea_edit)

        # Duration
        self.duration_combo = QComboBox()
        self.duration_combo.addItems(["智能时长", "300字", "500字", "800字", "1000字+"])
        layout.addRow("预估篇幅:", self.duration_combo)

        # Style
        self.style_edit = QLineEdit()
        self.style_edit.setPlaceholderText("延续系列风格")
        layout.addRow("风格调整:", self.style_edit)

        # Context Options
        self.context_group = QGroupBox("上下文引用")
        vbox = QVBoxLayout()
        self.use_global = QCheckBox("全局故事梗概 (Global Summary)")
        self.use_global.setChecked(True)
        self.use_state = QCheckBox("角色当前状态 (Character State)")
        self.use_state.setChecked(True)
        self.use_rag = QCheckBox("向量记忆检索 (RAG)")
        self.use_rag.setChecked(True)
        
        vbox.addWidget(self.use_global)
        vbox.addWidget(self.use_state)
        vbox.addWidget(self.use_rag)
        self.context_group.setLayout(vbox)
        layout.addRow(self.context_group)

        # Continuous Generation
        self.continuous_cb = QCheckBox("连续生成直到完结 (Continuous Generation)")
        self.continuous_cb.setToolTip("勾选后，将自动根据大纲生成剩余所有集数，无需每次确认。")
        layout.addRow(self.continuous_cb)

        # Buttons
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("开始生成")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def refresh_api_list(self):
        from ui.utils import populate_api_combo
        populate_api_combo(self.api_combo, self.config_manager, "LLM", "未配置 (使用默认)")

    def refresh_embedding_list(self):
        self.embedding_combo.clear()
        configs = self.config_manager.get("api_configs", [])
        emb_configs = [c for c in configs if c.get("type") == "Embedding"]
        
        self.embedding_combo.addItem("跟随 LLM 配置", {})
        for config in emb_configs:
            self.embedding_combo.addItem(config.get("name", "Unnamed"), config)

    def get_data(self):
        return {
            "api_config": self.api_combo.currentData(),
            "embedding_config": self.embedding_combo.currentData(),
            "idea": self.idea_edit.toPlainText(),
            "duration": self.duration_combo.currentText(),
            "style": self.style_edit.text(),
            "use_global": self.use_global.isChecked(),
            "use_state": self.use_state.isChecked(),
            "use_rag": self.use_rag.isChecked(),
            "continuous": self.continuous_cb.isChecked()
        }

class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建项目")
        self.setMinimumWidth(400)
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        layout.addRow("项目名称:", self.name_edit)

        # Project Type Selection
        self.type_combo = QComboBox()
        self.type_combo.setMinimumWidth(200)
        self.type_combo.addItems(["原创短剧 (Original)", "改编短剧 (Adaptation)"])
        layout.addRow("创作类型:", self.type_combo)

        # Language Selection - 新增语言配置项
        self.language_combo = QComboBox()
        self.language_combo.addItems(["中文 (Chinese)", "英文 (English)"])
        self.language_combo.setToolTip("项目语言一旦选定，创建后不能修改")
        layout.addRow("项目语言:", self.language_combo)

        self.theme_edit = QLineEdit()
        self.theme_edit.setPlaceholderText("例如：关于爱情的传奇故事")
        layout.addRow("短剧主题:", self.theme_edit)

        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("例如：浪漫爱情故事")
        layout.addRow("故事类型:", self.genre_edit)

        # Visual Style Selection
        self.style_combo = QComboBox()
        self.style_combo.addItems(VISUAL_STYLES)
        self.style_combo.setEditable(True)
        layout.addRow("画面风格:", self.style_combo)

        self.ep_count_spin = QSpinBox()
        self.ep_count_spin.setRange(1, 1000)
        self.ep_count_spin.setValue(3)
        layout.addRow("分集数量:", self.ep_count_spin)

        self.words_spin = QSpinBox()
        self.words_spin.setRange(100, 5000)
        self.words_spin.setValue(300)
        layout.addRow("每集字数:", self.words_spin)

        self.chars_edit = QTextEdit()
        self.chars_edit.setPlaceholderText("例如：李丽丽、王大力等")
        self.chars_edit.setMaximumHeight(60)
        layout.addRow("主要角色:", self.chars_edit)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("创建")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def get_data(self):
        project_type = "original" if self.type_combo.currentIndex() == 0 else "adaptation"
        language = "zh" if self.language_combo.currentIndex() == 0 else "en"
        return {
            "name": self.name_edit.text(),
            "type": project_type,
            "language": language,
            "theme": self.theme_edit.text(),
            "genre": self.genre_edit.text(),
            "visual_style": self.style_combo.currentText(),
            "total_episodes": self.ep_count_spin.value(),
            "words_per_episode": self.words_spin.value(),
            "main_characters": self.chars_edit.toPlainText()
        }

class LongSourcePrepThread(QThread):
    """长篇原作预处理线程：分块 → 摘要 → 全书大纲 → 向量入库。"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()   # 用户点了「停止」，与失败区分开

    def __init__(self, text, series, api_config, embedding_config=None, parent=None):
        super().__init__(parent)
        self.text = text
        self.series = series
        self.api_config = api_config or {}
        self.embedding_config = embedding_config

    def run(self):
        cancelled_exc = None
        try:
            try:
                from core.script.source_chunker import (
                    prepare_long_source, ensure_source_chunks_clean, LongSourceCancelled,
                )
            except ImportError:
                from src.core.script.source_chunker import (
                    prepare_long_source, ensure_source_chunks_clean, LongSourceCancelled,
                )
            cancelled_exc = LongSourceCancelled
            ensure_source_chunks_clean(self.series.vector_store)
            result = prepare_long_source(
                self.text, self.series, self.api_config,
                embedding_config=self.embedding_config,
                on_progress=lambda step, msg: self.progress.emit(msg),
            )
            self.finished.emit(result or {})
        except Exception as e:
            if cancelled_exc is not None and isinstance(e, cancelled_exc):
                self.cancelled.emit()
                return
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class ScriptAdaptationThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(str) # Add progress signal

    def __init__(self, api_config, source_text, style, episode_count=1, words_per_episode=500, current_episode_index=None, previous_context=None, character_list=None, language="zh", source_context=None):
        super().__init__()
        self.api_config = api_config
        self.source_text = source_text
        self.style = style
        self.episode_count = episode_count
        self.words_per_episode = words_per_episode
        self.current_episode_index = current_episode_index # 1-based index
        self.previous_context = previous_context
        self.character_list = character_list
        self.language = language
        # 长篇模式：按集预构建的原文上下文（大纲分段 + 块摘要 + 检索原文），
        # 传入时替代整段原文，避免超出模型上下文窗口。
        self.source_context = source_context or ""

    def run(self):
        try:
            api_key = self.api_config.get("api_key")
            base_url = self.api_config.get("base_url")
            model = self.api_config.get("model")

            client = LLMClient(api_key=api_key, base_url=base_url, model=model)

            # 长篇模式用按集上下文，短篇模式用完整原文
            content = self.source_context or self.source_text
            # 兜底：既无按集上下文又无分块时，截断超长原文，避免直接爆上下文
            if len(content) > 12000:
                content = content[:12000] + "\n（原文过长，已截断）"

            count_instruction = ""
            if self.current_episode_index is not None:
                # Serial Mode
                count_instruction = f"Write Episode {self.current_episode_index} of {self.episode_count}. Focus ONLY on the part of the story corresponding to this episode."
                if self.current_episode_index > 1:
                    count_instruction += " MAINTAIN the SAME structured format for video_prompt as previous episodes."
            elif self.episode_count > 1:
                # Batch Mode
                count_instruction = f"Strictly split the content into exactly {self.episode_count} distinct episodes."
            else:
                count_instruction = "Adapt into a single episode."

            context_instruction = ""
            if self.previous_context:
                context_instruction += f"\n\n[Previous Episode Context (Use this for continuity)]:\n{self.previous_context}"
            
            if self.character_list:
                context_instruction += f"\n\n[Main Characters]:\n{self.character_list}"

            # 根据语言选择提示词
            if self.language == "en":
                prompt = f"""
Please adapt the following text into a standard short drama script format and generate detailed AI image and video prompts.

Original Content:
{content}
{context_instruction}

Adaptation Requirements:
1. Style: {self.style}
2. {count_instruction}
3. Approximately {self.words_per_episode} words per episode.
4. Maintain core plot but adapt to fast-paced short drama format.
5. CRITICAL: Each episode MUST contain EXACTLY 10 shots (分镜). No more, no less!
6. Each shot must include:
   - video_prompt: the CREATIVE CORE of the shot only (1-2 sentences, max 120 chars):
     * what the subject is doing, key action/expression/emotional shift, the decisive moment
     * do NOT write the six-section template — the system auto-generates it later
7. CRITICAL: Each shot's duration MUST be between 8 and 10 seconds (8 recommended). NEVER below 8s or above 10s. The total duration of all shots in an episode MUST be at least 75 seconds (10 shots x 8s = 80s).
8. Output format must be JSON with "episodes" list.
9. Ensure valid JSON format, do not truncate in the middle.
10. CRITICAL: All episodes must use the SAME concise video_prompt style.
11. EXTREMELY IMPORTANT: You MUST output COMPLETE and VALID JSON with EXACTLY 10 shots per episode.
12. CRITICAL: Each shot's `characters` field MUST list the actual character names appearing in that shot. NEVER leave it empty!
"""
                
                system_prompt = """You are an AI visual prompt generator for short drama adaptation.
Output JSON only. Do not include any explanations or markdown code blocks (like ```json).
Each scene/shots should include a video_prompt for AI video generation.

The video_prompt field only needs the CREATIVE CORE of the shot (1-2 sentences, max 120 chars):
- what the subject is doing, key action/expression/emotional shift, the decisive moment
- Example: "The doctor suddenly presses the wound, looks up glaring at the intruder, eyes full of tears but holding back"
- Do NOT write the six-section template (【参考图描述】【视频基础信息】【分镜时间轴】【运镜设计】【参考图一致性约束】【质量要求】) — the system auto-generates those sections later. Writing them wastes output tokens and risks truncated JSON.

CRITICAL RULE: Each episode MUST contain EXACTLY 10 shots. Each shot duration MUST be between 8 and 10 seconds (8 recommended), and the total duration of all shots MUST be at least 75 seconds. Do NOT deviate from these numbers!

CRITICAL: Each shot's `characters` field MUST list the actual character names (from the episode's character list) who appear in that shot. NEVER leave it empty! This is essential for character-image binding in the storyboard.

Structure:
{
    "episodes": [
        {
            "title": "Episode Title",
            "genre": "Genre",
            "shots": [
                {
                    "shot_id": "1-1",
                    "scene_location": "Location",
                    "time": "Day/Night",
                    "atmosphere": "Tense/Romantic/Action",
                    "shot_type": "Close-up/Medium/Wide",
                    "camera_movement": "Static/Dolly/Pan",
                    "duration_seconds": 8,
                    "characters": "Character names",
                    "props": "Important props in this shot",
                    "action": "What characters are doing",
                    "dialogue": "Character dialogue",
                    "video_prompt": "Creative core of this shot (1-2 sentences, max 120 chars): what the subject is doing, key action/expression/emotional shift, the decisive moment. Do NOT write the six-section template (auto-generated by the system)"
                }
            ],
            "characters": [
                {
                    "name": "Character Name",
                    "gender": "Male/Female/Unknown",
                    "age": "Youth/Teen/Adult/Middle-aged/Elderly/Child",
                    "appearance_features": "Brief appearance description"
                }
                }
            ],
            "props": [
                {
                    "name": "Prop Name",
                    "description": "Detailed description including: material/craftsmanship, color/appearance, size, features, function",
                    "category": "Weapon/Furniture/Accessory/Tool/Food/Other",
                    "importance": "Important/General",
                    "material": "Material",
                    "color": "Color",
                    "size": "Size"
                }
            ],
            "script_scenes": [
                {
                    "name": "Scene Name",
                    "description": "Detailed environment description including: layout, architecture, details, atmosphere, lighting",
                    "time_of_day": "Day/Night/Dawn/Dusk",
                    "weather": "Sunny/Rainy/Foggy/Snowy/Clear",
                    "style": "Scene style",
                    "location_type": "Location type",
                    "atmosphere": "Atmosphere description",
                    "key_elements": "Key elements"
                }
            ]
        }
    ]
}

CHARACTER EXTRACTION Guidelines:
Extract all characters appearing in the script and create detailed profiles:
- name: Character name (use names from script)
- gender: Determine gender based on character traits (Male/Female/Unknown)
- age: Determine age group based on description (Child/Teen/Youth/Adult/Middle-aged/Elderly)
- appearance_features: Detailed appearance description including:
  * Height/Build: e.g., "180cm tall, robust build", "slender and petite figure"
  * Hair/Face: e.g., "long black hair to waist, oval face, phoenix eyes"
  * Clothing: e.g., "wearing red silk robe with golden embroidery"
  * Accessories: e.g., "golden crown on head, holding sword"
  * Expression: e.g., "determined eyes, resolute face"
- style_description: Overall art style
- personality: Personality traits
- role_in_story: Role in story
- background: Character background story

PROP EXTRACTION Guidelines:
Extract all important props from the script:
- name: Prop name
- description: Detailed description including: material/craftsmanship, color/appearance, size, features, function
- category: Category (Weapon/Furniture/Accessory/Tool/Food/Other)
- importance: Importance to plot
- material: Material
- color: Color
- size: Size

SCENE EXTRACTION Guidelines:
Extract all scenes from the script:
- name: Scene name
- description: Detailed environment description including: layout, architecture, details, atmosphere, lighting
- time_of_day: Time (Day/Night/Dawn/Dusk)
- weather: Weather (Sunny/Rainy/Foggy/Snowy/Clear)
- style: Scene style
- location_type: Location type
- atmosphere: Atmosphere description
- key_elements: Key elements

IMPORTANT:
1. Extract ALL unique characters from the story and create detailed character profiles
2. Extract ALL important props/objects mentioned in the story
3. Extract ALL scene locations used in the story
4. Provide detailed appearance_features for each character for AI image generation
5. Use the same character, prop, and scene names consistently throughout the episode
6. Include ALL required fields in character, prop, and scene objects
"""
            else:
                prompt = f"""
            请将以下文本改编为标准的短剧剧本格式，并生成详细的AI绘图和AI视频提示词。
            
            原文内容：
            {content}
            {context_instruction}
            
            改编要求：
            1. 风格：{self.style}
            2. {count_instruction}
            3. 每集大约 {self.words_per_episode} 字。
            4. 保持核心情节，但适应短剧的快节奏。
5. 关键规则：每集必须严格包含**9个分镜**，不能多也不能少！
6. 每个分镜(shot)必须包含：
   - video_prompt: 只写本镜头的**创意核心**（1-2句话，不超过120字）：
     * 主体在做什么、关键动作/表情/情绪变化、镜头要捕捉的决定性瞬间
     * **禁止**写六段式模板（【参考图描述】【视频基础信息】【分镜时间轴】【运镜设计】【参考图一致性约束】【质量要求】），系统会在后续步骤自动生成
7. 关键规则：每个分镜的时长根据情节灵活选择 **5-10 秒**（推荐 8 秒），对白多/动作复杂的镜头最多 10 秒（严禁超过 10 秒，生成会显存溢出失败），环境铺垫/空镜可以短到 5 秒！每集分镜总时长必须 **≥75 秒**（9 个分镜 × 8 秒 = 72 秒，系统会自动补足）！
8. 输出格式必须是JSON，包含 "episodes" 列表。
9. 确保 JSON 格式合法，不要在中间截断。
10. 关键：所有集数必须使用相同的简洁 video_prompt 写法。
11. 极其重要：必须输出完整的JSON，包含每集**恰好9个分镜**。
12. 关键：每个分镜的 `characters` 字段必须填入该分镜中实际出现的角色名称，**禁止留空**！
            """
            
                system_prompt = """You are an AI visual prompt generator for short drama adaptation.
            Output JSON only. Do not include any explanations or markdown code blocks (like ```json).
            Each scene/shots should include a video_prompt for AI video generation.
            
            关键要求：video_prompt 只写本镜头的**创意核心**（1-2句话，不超过120字）：
            - 写清主体在做什么、关键动作/表情/情绪变化、镜头要捕捉的决定性瞬间
            - 示例："女医猛地按住伤口，抬头怒视闯入者，眼中含泪却强忍不发"
            - **禁止**写六段式模板（【参考图描述】【视频基础信息】【分镜时间轴】【运镜设计】【参考图一致性约束】【质量要求】），系统会在后续步骤自动生成；写了纯属浪费输出 token，且极易导致 JSON 被截断

关键规则：每集必须严格包含**9个分镜**！每个分镜时长根据情节灵活选择 **5-10 秒**（推荐 8 秒），对白多/动作复杂的镜头最多 10 秒（严禁超过 10 秒，生成会显存溢出失败），环境铺垫/空镜可以短到 5 秒！每集分镜总时长**≥75秒**（9×8=72秒，系统自动补足）！不能多不能少！

关键：每个分镜的 `characters` 字段必须填入该分镜中实际出现的角色名称（从本集角色列表中选取），**禁止留空**！这是后续分镜角色图像绑定的关键依据。

            Structure:
            {
                "episodes": [
                    {
                        "title": "Episode Title",
                        "genre": "Genre",
                        "shots": [
                            {
                                "shot_id": "1-1",
                                "scene_location": "Location",
                                "time": "Day/Night",
                                "atmosphere": "紧张/浪漫/动作",
                                "shot_type": "特写/中景/全景",
                                "camera_movement": "固定/推轨/摇镜",
                                "duration_seconds": 8,
                                "characters": "角色名称",
                                "props": "本镜中的重要道具",
                                "action": "角色动作",
                                "dialogue": "角色对话",
                                "video_prompt": "本镜头创意核心（1-2句话，不超过120字）：主体在做什么、关键动作/表情/情绪变化、决定性瞬间。禁止写六段式模板（系统自动生成）"
                            }
                        ],
                        "characters": [
                            {
                                "name": "角色名称",
                                "gender": "男性/女性/未知",
                                "age": "青年/少年/中年/老年/儿童",
                                "appearance_features": "外貌描述"
                            }
                        ]
                    }
                ]
            }
            
            CHARACTER EXTRACTION Guidelines:
            从剧本中提取所有出现的角色，为每个角色创建详细档案：
            - name: 角色名称（使用剧本中的名字）
            - gender: 根据角色特征判断性别（男性/女性/未知）
            - age: 根据描述判断年龄段（儿童/少年/青年/中年/老年）
            - appearance_features: 详细外貌描述，必须包含以下要素：
              * 身高体型：如"身高180cm，体型魁梧健壮"、"身材纤细娇小"等
              * 发型面容：如"黑色长发及腰，瓜子脸，丹凤眼"、"短发干练，国字脸"等
              * 服装穿着：如"身穿红色丝绸长袍，金色刺绣花纹"、"现代黑色西装，白色衬衫"等
              * 配饰装备：如"头戴金冠，手持宝剑"、"佩戴珍珠耳环，手提名牌包"等
              * 表情神态：如"眼神坚定，面容刚毅"、"面带微笑，神态温和"等
            - style_description: 整体艺术风格
            - personality: 性格特点
            - role_in_story: 在故事中的角色定位
            - background: 角色背景故事

            PROP EXTRACTION Guidelines:
            从剧本中提取所有重要道具：
            - name: 道具名称
            - description: 详细描述，必须包含：材质工艺、颜色外观、尺寸大小、特征细节、功能用途
            - category: 分类（武器/家具/饰品/工具/食物/其他）
            - importance: 对剧情的重要性
            - material: 材质
            - color: 颜色
            - size: 尺寸

            SCENE EXTRACTION Guidelines:
            从剧本中提取所有场景：
            - name: 场景名称
            - description: 详细环境描述，必须包含：整体布局、建筑风格、环境细节、氛围营造、光影效果
            - time_of_day: 时间（Day/Night/Dawn/Dusk）
            - weather: 天气（Sunny/Rainy/Foggy/Snowy/Clear等）
            - style: 场景风格
            - location_type: 场景类型
            - atmosphere: 氛围描述
            - key_elements: 关键元素
            
            IMPORTANT:
            1. Extract ALL unique characters from the story and create detailed character profiles
            2. Extract ALL important props/objects mentioned in the story
            3. Extract ALL scene locations used in the story
            4. Provide detailed appearance_features for each character for AI image generation
            5. Use the same character, prop, and scene names consistently throughout the episode
            6. Include ALL required fields in character, prop, and scene objects
            """
            
            result = client.generate_script(prompt, system_prompt=system_prompt)
            
            if result:
                # Clean up markdown code blocks more robustly
                result = result.strip()
                
                # Remove markdown code block markers
                if result.startswith("```json"):
                    result = result[7:]
                elif result.startswith("```"):
                    result = result[3:]
                    
                if result.endswith("```"):
                    result = result[:-3]
                
                result = result.strip()
                
                # Try to find JSON content if there's explanatory text
                # If the result contains explanatory text before/after JSON, try to extract just the JSON
                json_pattern = r'(\{[\s\S]*"episodes"[\s\S]*\}|\[[\s\S]*\])'
                match = re.search(json_pattern, result)
                if match:
                    potential_json = match.group(1)
                    # Verify it's valid JSON
                    try:
                        json.loads(potential_json)
                        result = potential_json
                    except json.JSONDecodeError:
                        pass  # Keep original result if extraction fails
                
                self.finished.emit(result)
            elif _is_cancelled():
                return   # 用户点了停止：静默退出，不报 Empty response、不弹框
            else:
                self.error.emit("Empty response from LLM")
        except Exception as e:
            if _is_cancelled():
                return
            self.error.emit(str(e))

class AdaptScriptDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("改编剧本")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # API Config
        form_layout = QFormLayout()
        self.api_combo = QComboBox()
        self.refresh_api_list()
        form_layout.addRow("LLM 模型:", self.api_combo)
        layout.addLayout(form_layout)

        # Source Text
        layout.addWidget(QLabel("原文内容 (请输入或导入小说/文本):"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("在此粘贴小说章节或文本内容...")
        layout.addWidget(self.text_edit)

        # Import Button
        btn_layout = QHBoxLayout()
        import_btn = QPushButton("导入文本文件")
        import_btn.clicked.connect(self.import_file)
        btn_layout.addWidget(import_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Style/Instructions
        form_layout2 = QFormLayout()
        self.style_combo = QComboBox()
        self.style_combo.setEditable(True)
        self.style_combo.addItems([
            "保持原著风格",
            "增加冲突和张力",
            "快节奏紧凑",
            "慢节奏细腻",
            "增加幽默元素",
            "增加悬疑感",
            "浪漫温馨风格",
            "黑暗沉重风格",
            "现代白话改编",
            "古风韵味改编"
        ])
        self.style_combo.setCurrentText("保持原著风格")
        form_layout2.addRow("改编风格:", self.style_combo)
        
        self.ep_count_spin = QSpinBox()
        self.ep_count_spin.setRange(1, 1000)  # 与项目「总集数」一致，支持大文本长篇改编
        self.ep_count_spin.setValue(1)
        self.ep_count_spin.setSuffix(" 集")
        form_layout2.addRow("预计生成:", self.ep_count_spin)

        self.words_spin = QSpinBox()
        self.words_spin.setRange(100, 5000)
        self.words_spin.setValue(500)
        self.words_spin.setSuffix(" 字/集")
        form_layout2.addRow("每集字数:", self.words_spin)
        
        # Continuous Generation Checkbox
        self.continuous_cb = QCheckBox("逐集生成 (适用于多集)")
        self.continuous_cb.setToolTip("勾选后，将一集一集地生成，避免超时。适用于生成超过3集的情况。")
        form_layout2.addRow("", self.continuous_cb)
        
        layout.addLayout(form_layout2)

        # Buttons
        action_layout = QHBoxLayout()
        ok_btn = QPushButton("开始改编")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        action_layout.addWidget(ok_btn)
        action_layout.addWidget(cancel_btn)
        layout.addLayout(action_layout)

    def refresh_api_list(self):
        from ui.utils import populate_api_combo
        populate_api_combo(self.api_combo, self.config_manager, "LLM", "未配置 (使用默认)", select_default=False)

    def import_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文本文件", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.text_edit.setText(f.read())
            except Exception as e:
                QMessageBox.warning(self, "错误", f"无法读取文件: {e}")

    def get_data(self):
        return {
            "api_config": self.api_combo.currentData(),
            "source_text": self.text_edit.toPlainText(),
            "style": self.style_combo.currentText(),
            "episode_count": self.ep_count_spin.value(),
            "words_per_episode": self.words_spin.value(),
            "continuous": self.continuous_cb.isChecked()
        }

class EpisodeItemWidget(QWidget):
    delete_clicked = pyqtSignal(int) # Emits episode_id

    def __init__(self, text, episode_id, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.label = QLabel(text)
        self.label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.label)
        
        layout.addStretch()
        
        self.delete_btn = QPushButton("删除")
        self.delete_btn.setFixedWidth(60)
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("danger") + """; color: """ + _theme.color("accent_text") + """;
                border: none;
                border-radius: 3px;
                padding: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("danger") + """;
            }
        """)
        self.delete_btn.clicked.connect(self.on_delete)
        layout.addWidget(self.delete_btn)
        
        self.episode_id = episode_id

        # Ensure minimum height for visibility
        self.setMinimumHeight(50)
        # 背景交由全局主题管理，避免在浅色主题下显示深色条
        self.setStyleSheet("QWidget { border-bottom: 1px solid rgba(128,128,128,0.2); }")

    def on_delete(self):
        self.delete_clicked.emit(self.episode_id)

class ProjectWindow(QWidget):
    project_loaded = pyqtSignal(str) # Emits project path
    open_episode = pyqtSignal(str, str) # Emits (project_path, episode_id)
    request_auto_run = pyqtSignal(str) # Emits project path, requests switch to one-click page

    def __init__(self, projects_dir):
        super().__init__()
        self.manager = ProjectManager(projects_dir)
        self.config_manager = ConfigManager()
        self.current_series_manager = None
        self.current_project_path = None
        self.current_project_type = "original" # Default to original
        self.current_project_language = "zh" # Default to Chinese
        self.continuous_mode = False # Initialize continuous_mode
        # 大纲的原始 Markdown 源码：QTextEdit.toMarkdown() 会丢弃加粗等格式，
        # 用户未编辑时直接回存源码，避免保存后大纲格式丢失。
        self._outline_source_md = ""
        self.init_ui()
        self.refresh_list()

    def get_project_language(self):
        """获取当前项目的语言设置，默认为中文"""
        if self.current_project_path:
            try:
                project_json_path = os.path.join(self.current_project_path, "project.json")
                if os.path.exists(project_json_path):
                    with open(project_json_path, 'r', encoding='utf-8') as f:
                        project_meta = json.load(f)
                        return project_meta.get("language", "zh")
            except Exception as e:
                print(f"Error reading project language: {e}")
        return self.current_project_language

    def init_ui(self):
        self.setObjectName("ProjectHome")
        # 不再设置硬编码 STYLESHEET，交由全局 theme 系统统一管理，
        # 使深色/浅色、皮肤切换在项目页同样生效。
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ============ 左栏：项目列表 ============
        left_panel = QFrame()
        left_panel.setObjectName("SideBar")
        left_panel.setFixedWidth(290)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 18, 14, 14)
        left_layout.setSpacing(10)

        title_label = QLabel("📂  我的项目")
        title_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        left_layout.addWidget(title_label)

        self.project_list = QListWidget()
        self.project_list.itemClicked.connect(self.on_project_clicked)
        self.project_list.itemDoubleClicked.connect(self.load_selected_project)
        left_layout.addWidget(self.project_list, 1)

        load_btn = QPushButton("加载选中项目")
        load_btn.clicked.connect(self.load_selected_project)
        left_layout.addWidget(load_btn)

        # 断点续跑：项目生成被终止/失败后，可直接从项目页继续生成
        # （复用项目目录下的 autorun_state.json，已完成阶段自动跳过）
        self.resume_btn = QPushButton("▶ 继续生成")
        self.resume_btn.clicked.connect(self.resume_project_generation)
        self.resume_btn.setStyleSheet("""
            QPushButton { background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("accent_text") + """; border: none;
                padding: 8px 16px; border-radius: 8px; font-weight: 600; }
            QPushButton:hover { background-color: """ + _theme.color("accent2") + """; }
            QPushButton:disabled { background-color: """ + _theme.color("border_strong") + """; color: """ + _theme.color("text_sub") + """; }
        """)
        self.resume_btn.setEnabled(False)
        left_layout.addWidget(self.resume_btn)

        self.delete_btn = QPushButton("删除项目")
        self.delete_btn.clicked.connect(self.delete_project)
        self.delete_btn.setStyleSheet("""
            QPushButton { background-color: """ + _theme.color("danger") + """; color: """ + _theme.color("accent_text") + """; border: none;
                padding: 8px 16px; border-radius: 8px; font-weight: 600; }
            QPushButton:hover { background-color: """ + _theme.color("danger") + """; }
            QPushButton:disabled { background-color: """ + _theme.color("border_strong") + """; color: """ + _theme.color("text_sub") + """; }
        """)
        self.delete_btn.setEnabled(False)
        left_layout.addWidget(self.delete_btn)

        # ============ 右栏：项目详情 ============
        right_panel = QWidget()
        self.right_layout = QVBoxLayout(right_panel)
        self.right_layout.setContentsMargins(24, 16, 24, 16)
        self.right_layout.setSpacing(14)

        detail_title = QLabel("项目详情")
        detail_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.right_layout.addWidget(detail_title)

        # 生成大纲/生成剧本/改编剧本/从模板创建等入口已移除：
        # 项目创建与后续创作统一走首页（一键成片）。
        # 相关功能方法仍保留，供内部/自动化流程调用。

        # --- 进度区 ---
        self.progress_container = QWidget()
        progress_layout = QVBoxLayout(self.progress_container)
        progress_layout.setContentsMargins(0, 4, 0, 4)
        status_layout = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: " + _theme.color("text_sub") + ";")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        self.cancel_btn = QPushButton("停止")
        self.cancel_btn.setStyleSheet(
            "QPushButton { background-color: " + _theme.color("danger") + "; color: " + _theme.color("accent_text") + "; padding: 4px 12px; "
            "border-radius: 6px; font-size: 12px; }"
            "QPushButton:hover { background-color: " + _theme.color("danger") + "; }")
        self.cancel_btn.clicked.connect(self.cancel_generation)
        self.cancel_btn.hide()
        status_layout.addWidget(self.cancel_btn)
        progress_layout.addLayout(status_layout)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        progress_layout.addWidget(self.progress_bar)
        self.right_layout.addWidget(self.progress_container)

        # --- 详情 Tabs ---
        self.details_tabs = QTabWidget()
        self.info_tab = QWidget()
        info_main_layout = QVBoxLayout(self.info_tab)
        self.info_form_layout = QFormLayout()
        self.info_form_layout.setSpacing(12)
        self.info_form_layout.setContentsMargins(16, 16, 16, 16)
        info_main_layout.addLayout(self.info_form_layout)
        self.edit_info_btn = QPushButton("编辑信息")
        self.edit_info_btn.clicked.connect(self.edit_project_info)
        self.edit_info_btn.setEnabled(False)
        self.edit_info_btn.setFixedWidth(120)
        btn_container = QHBoxLayout()
        btn_container.addStretch()
        btn_container.addWidget(self.edit_info_btn)
        btn_container.addStretch()
        info_main_layout.addLayout(btn_container)
        info_main_layout.addStretch()
        self.details_tabs.addTab(self.info_tab, "基本信息")

        self.outline_tab = QWidget()
        outline_layout = QVBoxLayout(self.outline_tab)
        self.outline_edit = QTextEdit()
        self.outline_edit.setPlaceholderText("大纲内容...")
        save_outline_btn = QPushButton("保存大纲")
        save_outline_btn.clicked.connect(self.save_outline)
        outline_layout.addWidget(self.outline_edit)
        outline_layout.addWidget(save_outline_btn)
        self.details_tabs.addTab(self.outline_tab, "大纲")

        self.episodes_tab = QWidget()
        ep_layout = QVBoxLayout(self.episodes_tab)
        self.episode_list = QListWidget()
        self.episode_list.itemDoubleClicked.connect(self.on_episode_clicked)
        ep_layout.addWidget(self.episode_list)
        self.details_tabs.addTab(self.episodes_tab, "分集列表")

        self.right_layout.addWidget(self.details_tabs, 1)

        layout.addWidget(left_panel)
        layout.addWidget(right_panel, 1)

    # ------------------------------------------------------------------ 渐变背景
    # ------------------------------------------------------------------ 一键成片
    def _on_style_chip(self, style: str):
        self._selected_style = style

    def _import_topic(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入文字", "", "文本文件 (*.txt *.md);;所有文件 (*.*)")
        if not path:
            return
        try:
            from pathlib import Path
            content = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.topic_input.setPlainText(content[:5000])

    def _on_one_click_generate(self):
        topic = self.topic_input.toPlainText().strip()
        if not topic:
            self.topic_input.setFocus()
            QMessageBox.information(self, "提示", "请先输入短剧主题")
            return
        style = getattr(self, "_selected_style", "都市")
        name = re.sub(r'[\\/:*?"<>|\n\r]', '_', topic[:18]).strip() or "未命名短剧"
        try:
            path = self.manager.create_project(name, extra_data={
                "theme": topic,
                "genre": style,
                "total_episodes": 1,
                "words_per_episode": 300,
            })
        except ValueError as e:
            QMessageBox.warning(self, "创建失败", str(e))
            return
        self.refresh_list()
        self.current_project_path = path
        self.current_project_type = "original"
        # 让项目列表选中新项目
        for i in range(self.project_list.count()):
            it = self.project_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                self.project_list.setCurrentItem(it)
                self.on_project_clicked(it)
                break
        self.project_loaded.emit(path)
        # 请求主窗口跳转到一键成片页面继续
        self.request_auto_run.emit(path)


    def on_project_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        p_type = item.data(Qt.ItemDataRole.UserRole + 1)
        self.current_project_type = p_type
        self.delete_btn.setEnabled(True)
        self.resume_btn.setEnabled(self._project_can_resume(path))
        self.load_project_details(path)

    # ---------------- 断点续跑（项目页入口） ----------------
    @staticmethod
    def _resume_state_info(project_path):
        """读取项目的流水线状态，返回 (state, 是否有未完成阶段)。"""
        try:
            try:
                from core.autorun.state import PipelineState
            except ImportError:
                from src.core.autorun.state import PipelineState
            state = PipelineState(project_path)
        except Exception:
            return None, False
        try:
            return state, bool(state.has_unfinished())
        except Exception:
            return state, False

    def _project_can_resume(self, project_path):
        """该项目是否存在可续跑的未完成任务。"""
        if not project_path:
            return False
        state, unfinished = self._resume_state_info(project_path)
        if not state or not unfinished:
            return False
        # 必须有可用的运行参数（状态里保存了上次运行的 params）
        return bool(state.data.get("params"))

    def resume_project_generation(self):
        """从项目页继续生成：复用原项目与原参数，已完成阶段自动跳过。"""
        item = self.project_list.currentItem()
        path = item.data(Qt.ItemDataRole.UserRole) if item else self.current_project_path
        if not path:
            QMessageBox.information(self, "提示", "请先在左侧选中一个项目。")
            return
        state, unfinished = self._resume_state_info(path)
        if not state:
            QMessageBox.information(self, "提示", "该项目没有流水线状态，无法继续生成。")
            return
        if not unfinished:
            QMessageBox.information(self, "提示", "该项目的生成任务已全部完成，无需继续。")
            return
        raw_params = state.data.get("params") or {}
        if not raw_params:
            QMessageBox.warning(self, "提示",
                                "找不到上次的运行参数，无法直接续跑。\n"
                                "请到首页重新发起生成，或手动指定已有剧本。")
            return
        try:
            try:
                from core.autorun.params import AutoRunParams
            except ImportError:
                from src.core.autorun.params import AutoRunParams
            params = AutoRunParams.from_dict(raw_params)
        except Exception as e:
            QMessageBox.warning(self, "提示", f"读取运行参数失败：{e}")
            return

        # 找到首页的 AutoRun 窗口并启动续跑（reset_state=False → 保留已完成阶段）
        arw = self._get_auto_run_window()
        if arw is None:
            QMessageBox.warning(self, "提示", "找不到一键成片窗口，无法启动续跑。")
            return
        # 已有流水线在跑时不允许再启动一条，避免两个线程抢同一份状态
        try:
            rt = getattr(arw, "run_thread", None)
            if rt is not None and hasattr(rt, "isRunning") and rt.isRunning():
                QMessageBox.information(self, "提示",
                                        "当前还有生成任务在运行，请先等待它结束或停止后再续跑。")
                return
        except Exception:
            pass
        try:
            arw._last_run = {"project_path": path, "params": params, "is_batch": False}
        except Exception:
            pass
        show_message(self, "继续生成", f"正在从上次中断处继续：{os.path.basename(path)}")
        arw._start_pipeline(path, params, is_batch=False, reset_state=False)

    def _get_auto_run_window(self):
        """取首页的一键成片窗口（AutoRunWindow）。"""
        try:
            mw = self.window()
            arw = getattr(mw, "auto_run_window", None)
            if arw is not None:
                return arw
        except Exception:
            pass
        p = self.parent()
        while p is not None:
            try:
                arw = getattr(p, "auto_run_window", None)
                if arw is not None:
                    return arw
            except Exception:
                pass
            p = p.parent()
        return None

    def delete_project(self):
        if not self.current_project_path:
            return
        
        project_name = os.path.basename(self.current_project_path)
        
        # Count associated content
        episode_count = 0
        script_count = 0
        storyboard_count = 0
        image_count = 0
        video_count = 0
        
        try:
            series_manager = SeriesManager(self.current_project_path)
            episode_count = len(series_manager.get_episodes())
        except Exception:
            pass
        
        # Count files in various directories
        for root, dirs, files in os.walk(self.current_project_path):
            if 'scripts' in root:
                script_count += len([f for f in files if f.endswith('.json')])
            elif 'storyboards' in root:
                storyboard_count += len([f for f in files if f.endswith('.json')])
            elif 'images' in root:
                image_count += len(files)
            elif 'videos' in root or 'clips' in root:
                video_count += len(files)
        
        # Build confirmation message
        msg = f"确定要删除项目 \"{project_name}\" 吗？\n\n"
        msg += "此操作将彻底删除以下所有内容：\n"
        msg += f"  - 项目文件夹本身\n"
        msg += f"  - 剧本集数: {episode_count} 集\n"
        msg += f"  - 剧本文件: {script_count} 个\n"
        msg += f"  - 分镜配置: {storyboard_count} 个\n"
        msg += f"  - 图片文件: {image_count} 张\n"
        msg += f"  - 视频文件: {video_count} 个\n\n"
        msg += "⚠️ 注意：此操作不可恢复！"
        
        reply = QMessageBox.warning(
            self,
            "确认删除项目",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                import shutil
                # Delete the entire project directory
                shutil.rmtree(self.current_project_path)
                
                # Clear current project state
                self.current_project_path = None
                self.current_series_manager = None
                self.delete_btn.setEnabled(False)
                
                # Refresh the project list
                self.refresh_list()
                
                # Clear the details panel
                while self.info_form_layout.rowCount() > 0:
                    self.info_form_layout.removeRow(0)
                self.outline_edit.clear()
                self._outline_source_md = ""
                self.episode_list.clear()
                
                QMessageBox.information(self, "成功", f"项目 \"{project_name}\" 已删除。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除项目失败：{str(e)}")

    def load_project_details(self, path):
        self.current_project_path = path
        self.current_series_manager = SeriesManager(path)
        
        # Update button states based on project type
        self.update_button_states()
        
        # 1. Populate Info
        # Clear existing rows
        while self.info_form_layout.rowCount() > 0:
            self.info_form_layout.removeRow(0)
            
        data = self.current_series_manager.data
        
        def add_info_row(label_text, value_text):
            lbl = QLabel(str(value_text))
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-size: 14px; padding: 5px;")
            self.info_form_layout.addRow(QLabel(label_text), lbl)

        add_info_row("项目名称:", data.get("title", ""))

        # Project Type
        p_type = data.get("type", "original")
        type_map = {"original": "原创短剧", "adaptation": "改编短剧"}
        add_info_row("创作类型:", type_map.get(p_type, "原创短剧"))

        # Language
        language = self.get_project_language()
        language_map = {"zh": "中文", "en": "英文"}
        add_info_row("项目语言:", language_map.get(language, "中文"))

        # Read project.json for fields not stored in series.json
        project_meta = {}
        try:
            project_json_path = os.path.join(self.current_project_path, "project.json")
            if os.path.exists(project_json_path):
                with open(project_json_path, 'r', encoding='utf-8') as f:
                    project_meta = json.load(f)
        except Exception as e:
            print(f"Error reading project.json: {e}")

        add_info_row("短剧主题:", project_meta.get("theme", ""))
        add_info_row("故事类型:", data.get("genre", ""))
        add_info_row("画面风格:", project_meta.get("visual_style", ""))
        add_info_row("总集数:", data.get("total_episodes", ""))
        add_info_row("每集字数:", data.get("words_per_episode", ""))
        
        # Core Premise with Markdown formatting
        premise = data.get("premise", "")
        
        # Filter out "Brief description of each episode" for the Basic Info view
        display_premise = premise
        split_markers = ["简要描述每集剧情走向", "每集剧情走向", "分集剧情", "**简要描述每集剧情走向"]
        for marker in split_markers:
            if marker in display_premise:
                display_premise = display_premise.split(marker)[0]
                # Clean up trailing asterisks or newlines if split left them
                display_premise = display_premise.strip().rstrip('*').strip()
                break
        
        formatted_premise = self.format_markdown(display_premise)
        
        premise_view = QTextEdit()
        premise_view.setReadOnly(True)
        premise_view.setMarkdown(formatted_premise)
        premise_view.setMinimumHeight(300) # Increased height
        premise_view.setMaximumHeight(600)
        premise_view.setStyleSheet("QTextEdit { padding: 10px; font-size: 14px; }")
        self.info_form_layout.addRow(QLabel("核心梗概:"), premise_view)
        
        add_info_row("主要角色:", data.get("main_characters", ""))
        
        # 2. Populate Outline
        # Use the full premise/outline here
        self._outline_source_md = data.get("premise", "") or ""
        formatted_premise = self.format_markdown(self._outline_source_md)
        self.outline_edit.setMarkdown(formatted_premise)
        # 记录为“未编辑”，保存时可直接回存源码
        self.outline_edit.document().setModified(False)
        
        # 3. Populate Episodes
        self.refresh_episode_list()

    def edit_project_info(self):
        if not self.current_series_manager:
            return
            
        # We need to pass the current type to the dialog.
        # The type is stored in self.current_project_type (from project.json)
        # But SeriesManager.data (series.json) might not have it or it might be out of sync.
        # Let's inject it into the data passed to dialog.
        dialog_data = self.current_series_manager.data.copy()
        dialog_data["type"] = self.current_project_type
        
        # Also inject visual_style from project.json if possible
        try:
            project_json_path = os.path.join(self.current_project_path, "project.json")
            if os.path.exists(project_json_path):
                with open(project_json_path, 'r', encoding='utf-8') as f:
                    pm = json.load(f)
                    dialog_data["visual_style"] = pm.get("visual_style", "")
        except Exception: pass
        
        dialog = EditProjectDialog(dialog_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_data()
            
            # 1. Update SeriesManager (series.json)
            # Note: 'type' is not strictly part of series.json schema usually, but storing it there doesn't hurt.
            # However, the source of truth for the list is project.json.
            self.current_series_manager.data.update(new_data)
            self.current_series_manager.save()
            
            # 2. Update project.json
            # We need to read project.json, update it, and save it.
            try:
                project_json_path = os.path.join(self.current_project_path, "project.json")
                if os.path.exists(project_json_path):
                    with open(project_json_path, 'r', encoding='utf-8') as f:
                        project_meta = json.load(f)
                    
                    project_meta["type"] = new_data["type"]
                    project_meta["visual_style"] = new_data.get("visual_style", "")
                    # Also update name if title changed? Usually project name is folder name, but display name can be title.
                    # Let's keep it simple and just update type for now as requested.
                    
                    try:
                        from core.utils.json_store import atomic_write_json
                    except ImportError:
                        from src.core.utils.json_store import atomic_write_json
                    atomic_write_json(project_json_path, project_meta)
                        
                # Update local state
                self.current_project_type = new_data["type"]
                
            except Exception as e:
                print(f"Error updating project.json: {e}")
            
            # Refresh view
            self.load_project_details(self.current_project_path)
            self.refresh_list() # Refresh list to show new tags
            self.update_button_states() # Update buttons based on new type
            
            QMessageBox.information(self, "成功", "项目信息已更新")

    def refresh_episode_list(self):
        self.episode_list.clear()
        if self.current_series_manager:
            episodes = self.current_series_manager.get_episodes()
            for ep in episodes:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, ep['id'])
                
                # Create custom widget
                widget = EpisodeItemWidget(f"第 {ep['id']} 集: {ep['title']}", ep['id'])
                widget.delete_clicked.connect(self.delete_episode)
                
                # Set a fixed size hint to prevent overlapping
                item.setSizeHint(QSize(0, 60))
                
                self.episode_list.addItem(item)
                self.episode_list.setItemWidget(item, widget)

    def delete_episode(self, episode_id):
        if not self.current_series_manager:
            return
            
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除第 {episode_id} 集吗？\n此操作将删除对应的剧本文件，且后续集数会重新编号。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success = self.current_series_manager.delete_episode(episode_id)
            if success:
                self.refresh_episode_list()
                QMessageBox.information(self, "成功", "集数已删除并重新编号。")
            else:
                QMessageBox.warning(self, "错误", "删除失败，未找到该集。")

    def generate_outline(self):
        if not self.current_series_manager:
            return
            
        # Check if outline exists
        if self.current_series_manager.data.get("premise"):
            reply = QMessageBox.question(
                self, 
                "确认重新生成", 
                "当前项目已包含大纲内容。重新生成将覆盖现有大纲。\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            
        # Show Dialog
        dialog = GenerateOutlineDialog(self.config_manager, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        data = dialog.get_data()
        api_config = data["api_config"]
        style = data["style"]
        instructions = data["instructions"]
        
        project_data = self.current_series_manager.data
        
        # 根据项目语言选择提示词语言
        language = self.get_project_language()

        # 集数范围提示必须按项目实际集数生成，否则只有 1 集的项目也会产出多集大纲
        try:
            total_eps = int(project_data.get('total_episodes') or 1)
        except (TypeError, ValueError):
            total_eps = 1
        total_eps = max(total_eps, 1)
        if total_eps == 1:
            episode_scope_zh = ("本剧只有 1 集，因此严禁出现任何集数范围（如“1-5集”）或分集大纲，"
                                "只描述这一集的剧情走向，标题格式为“**第1集：标题**”。")
            episode_scope_en = ("This series has only 1 episode, so NEVER produce episode ranges (e.g. \"Episodes 1-5\") "
                                "or per-range outlines. Describe only this single episode, titled \"**Episode 1: Title**\".")
        else:
            episode_scope_zh = (f"本剧共 {total_eps} 集，请按每 5 集为一段划分（最后一段可不足 5 集），"
                                f"格式如“**1-5集：标题**”，且集数范围不得超过 {total_eps}。")
            episode_scope_en = (f"This series has {total_eps} episodes. Group them in ranges of 5 (the last range may be shorter), "
                                f"formatted as \"**Episodes 1-5: Title**\", and never exceed {total_eps}.")

        if language == "en":
            prompt = f"""
Please generate a detailed story outline for the following short drama project:
Project Name: {project_data.get('title')}
Genre: {project_data.get('genre')}
Theme/Logline: {project_data.get('premise')}
Main Characters: {project_data.get('main_characters')}
Number of Episodes: {total_eps}

Style Tone: {style}
Additional Requirements: {instructions}

Requirements (MANDATORY):
1. You MUST output a FULL outline, NOT just the project name or a single title line.
2. Include the overall story arc (beginning, rising action, climax, ending).
3. Describe the plot direction per episode (or per episode range). {episode_scope_en}
4. Highlight key conflicts, turning points and climaxes.
5. Minimum 500 words. If your response is shorter, it will be rejected.
6. Use Markdown format with double line breaks between sections for clear paragraphs.
7. The outline MUST match the episode count above exactly. Never invent more episodes than stated.
"""
            system_prompt = ("You are a professional short-drama screenwriter. "
                             "You MUST write a complete, detailed outline of at least 500 words. "
                             "Never respond with only the project name or a single title. "
                             f"The outline MUST match the project's episode count ({total_eps}). "
                             "Use Markdown with clear paragraph breaks.")
        else:
            prompt = f"""
请为以下短剧项目生成一个详细的故事大纲（Markdown格式）：
项目名称：{project_data.get('title')}
类型：{project_data.get('genre')}
核心梗概：{project_data.get('premise')}
主要角色：{project_data.get('main_characters')}
集数：{total_eps}

风格基调：{style}
额外要求：{instructions}

必须遵守的要求（违反将被拒绝）：
1. 必须输出完整大纲，禁止只回显项目名称或只输出一行标题。
2. 必须包含：整体故事弧线（开端→发展→高潮→结局）。
3. 按集（或集数范围）描述剧情走向。{episode_scope_zh}
4. 突出关键冲突、转折点和高潮。
5. 全文不少于500字，少于500字将被拒绝。
6. 使用Markdown格式，章节之间用双换行分隔，确保段落分明。
7. 大纲必须与上述集数完全一致，严禁超出项目实际集数。
"""
            system_prompt = ("你是一位专业的短剧编剧。你必须输出一份完整、详细、不少于500字的故事大纲。"
                             "禁止只回显项目名称或只输出一行标题。"
                             f"大纲必须与项目实际集数（{total_eps}集）完全一致。"
                             "使用Markdown格式，段落分明。")
        
        # Start Generation UI
        self.progress_bar.show()
        self.cancel_btn.show()
        self.status_label.setText("正在生成大纲，请稍候...")
        self.edit_info_btn.setEnabled(False) # Disable edit button during outline generation
        
        self.outline_thread = OutlineGeneratorThread(api_config, prompt, system_prompt)
        self.outline_thread.finished.connect(self.on_outline_generated)
        self.outline_thread.error.connect(self.handle_outline_error)
        
        self._begin_background_op()
        self.outline_thread.start()

    def handle_outline_error(self, e):
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.status_label.setText("生成失败")
        self.update_button_states()
        QMessageBox.critical(self, "Error", e)

    def format_markdown(self, text):
        """Ensure proper spacing for markdown headers and lists."""
        if not text:
            return ""
        
        # 1. Replace non-standard bullets
        text = text.replace('●', '-')
        
        # 2. Fix "*第X集" or "*第X阶段" pattern (often output by LLM without space, causing italics)
        # Turn "*第1集" or "*第一阶段" into "\n- 第1集"
        # 注意：只处理单个 *，避免把 **加粗标题** 误转成列表项
        text = re.sub(r'(?<!\*)\*(?!\*)\s*(第[0-9一二三四五六七八九十]+[集阶段])', r'\n- \1', text)
        
        # 3. Ensure headers (#, ##, ###) start on a new line with a blank line before them
        text = re.sub(r'([^\n])\s*(#+\s)', r'\1\n\n\2', text)
        
        # 4. Ensure lists start on new line (-, *, 1.)
        # 注意：不能把 **加粗** 的结尾 * 误判成列表符（否则会破坏标题并让正文变成列表项）
        text = re.sub(r'([^\n*\-])\s*([*-])(?![*-])\s+(?=[^\s*\-])', r'\1\n\2 ', text)
        text = re.sub(r'([^\n])\s*(\d+\.)\s+', r'\1\n\2 ', text)
        
        # 5. Fix "Wall of Text" by adding newlines before bold headers
        # Only add newline if ** is preceded by sentence punctuation (. ! ? 。 ！ ？)
        text = re.sub(r'([.!?。！？])\s*\*\*', r'\1\n\n**', text)
        
        # 6. Clean up double bullets like "- -" or "- *" created by replacements
        text = re.sub(r'^\s*[-*]\s*[-*]\s+', '- ', text, flags=re.MULTILINE)
        
        # 7. Fix episode range format: "集1-5" -> "1-5集"
        text = re.sub(r'集(\d+)-(\d+)', r'\1-\2集', text)
        
        return text

    def on_outline_generated(self, outline):
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.status_label.setText("大纲生成完毕")
        self.update_button_states()

        if outline:
            formatted_outline = self.format_markdown(outline)
            self._outline_source_md = formatted_outline
            self.outline_edit.setMarkdown(formatted_outline)
            self.outline_edit.document().setModified(False)
            self.save_outline()
            QMessageBox.information(self, "Success", "大纲生成完毕")

    def save_outline(self):
        if not self.current_series_manager:
            return
        try:
            # 用户未编辑时回存原始 Markdown 源码（toMarkdown() 会丢弃加粗等格式）
            if self.outline_edit.document().isModified():
                text = self.outline_edit.toMarkdown()
                self._outline_source_md = text
                self.outline_edit.document().setModified(False)
            else:
                text = self._outline_source_md or self.outline_edit.toMarkdown()
            self.current_series_manager.update_premise(text)
            QMessageBox.information(self, "保存", "大纲已保存")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"大纲保存失败：{e}")

    def generate_next_episode_with_ai(self):
        if not self.current_series_manager:
            return

        # Check if episodes exist
        ep_count = len(self.current_series_manager.data.get("episodes", []))
        if ep_count > 0:
             reply = QMessageBox.question(
                self, 
                "确认生成", 
                f"当前项目已有 {ep_count} 集剧本。\n是否继续生成第 {ep_count + 1} 集？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.Yes
            )
             if reply == QMessageBox.StandardButton.No:
                return

        # Show Dialog
        dialog = GenerateScriptDialog(self.config_manager, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        
        # Store config for continuous generation
        self.current_gen_config = data
        self.continuous_mode = data.get("continuous", False)
        
        # Start first generation
        self.start_script_generation(data["idea"])

    def start_script_generation(self, idea):
        data = self.current_gen_config
        api_config = data["api_config"]
        embedding_config = data.get("embedding_config", {})
        duration = data["duration"]
        style = data["style"]
        
        # 「跟随 LLM 配置」时保持 embedding_config 为空，
        # 交给 EmbeddingClient 自行回退（全局 embedding 配置 > LLM 配置），
        # 避免把 LLM 凭据复制成显式配置、覆盖设置页的独立 embedding 配置。

        # Update UI - Preparing
        self.progress_bar.show()
        self.cancel_btn.show()
        self.status_label.setText("正在准备上下文数据...")
        self.edit_info_btn.setEnabled(False) # Disable edit button during generation
        QApplication.processEvents() # Force UI update

        # Get context（含同步 embedding 网络请求，失败时必须给用户明确反馈，
        # 不能让异常从按钮槽函数里裸奔导致界面停在"准备中"状态）
        try:
            context_data = self.current_series_manager.get_full_context_data(idea, embedding_config=embedding_config)
        except Exception as e:
            print(f"Error preparing context data: {e}")
            import traceback
            traceback.print_exc()
            self.handle_gen_error(f"准备上下文数据失败，请检查 Embedding 配置与网络: {e}")
            return
        
        # Filter context
        if not data["use_global"]:
            context_data["global_summary"] = ""
        if not data["use_state"]:
            context_data["character_state"] = {}
        if not data["use_rag"]:
            context_data["rag_context"] = ""

        # Update UI - Generating
        next_ep_id = len(self.current_series_manager.data["episodes"]) + 1
        self.status_label.setText(f"正在生成第 {next_ep_id} 集... (AI思考中)")

        # Start Thread
        language = self.get_project_language()
        self.gen_thread = ScriptGeneratorThread(
            prompt=idea,
            api_config=api_config,
            duration=duration,
            style=style,
            context_data=context_data,
            project_dir=self.current_series_manager.project_dir,
            language=language
        )
        self.gen_thread.finished.connect(self.on_script_generated)
        self.gen_thread.error.connect(lambda e: self.handle_gen_error(e))
        self._begin_background_op()
        self.gen_thread.start()

    def handle_gen_error(self, e):
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.status_label.setText("生成出错")
        self.update_button_states()
        
        QMessageBox.critical(self, "Error", e)
        self.continuous_mode = False

    def on_script_generated(self, data):
        """Handle generation result with characters, props, and scenes"""
        if not self.current_series_manager:
            return
            
        try:
            # Handle dict data directly (new format)
            if isinstance(data, dict):
                script_data = data
            else:
                # Try to parse JSON string
                try:
                    script_data = json.loads(data)
                except (json.JSONDecodeError, ValueError) as e:
                    # 原来静默替换成空剧本，用户会以为 AI 真生成了一集空内容
                    preview = (data[:200] + "...") if isinstance(data, str) and len(data) > 200 else data
                    self.handle_gen_error(
                        f"AI 返回的内容不是有效 JSON，本集未保存。\n错误: {e}\n返回片段: {preview}"
                    )
                    return
            
            # Check for multi-episode package
            if "episodes" in script_data and isinstance(script_data["episodes"], list):
                # Multi-episode handling
                count = 0
                project_dir = self.current_series_manager.project_dir
                all_created_items = {
                    "characters": [],
                    "props": [],
                    "scenes": []
                }
                
                for ep_data in script_data["episodes"]:
                    next_id = len(self.current_series_manager.data["episodes"]) + 1
                    title = ep_data.get("title") or f"第{next_id}集"
                    
                    # Auto-create characters, props, and scenes for each episode
                    created_items = self._auto_create_resources(ep_data, project_dir)
                    all_created_items["characters"].extend(created_items["characters"])
                    all_created_items["props"].extend(created_items["props"])
                    all_created_items["scenes"].extend(created_items["scenes"])
                    
                    # Enhance video prompts
                    ep_data = self._enhance_video_prompts(ep_data)
                    
                    # Convert back to string for storage
                    self.current_series_manager.add_episode(title, json.dumps(ep_data, ensure_ascii=False))
                    count += 1
                
                self.refresh_episode_list()
                self.progress_bar.hide()
                self.cancel_btn.hide()
                
                # Calculate total episodes in project
                total_episodes = len(self.current_series_manager.data.get("episodes", []))
                self.status_label.setText(f"改编完成，共生成 {total_episodes} 集")
                self.update_button_states()
                
                # Show success message with created items
                msg = f"成功改编并生成了 {total_episodes} 集剧本。\n\n已自动创建:\n"
                msg += f"- 角色: {len(all_created_items['characters'])} 个\n"
                msg += f"- 道具: {len(all_created_items['props'])} 个\n"
                msg += f"- 场景: {len(all_created_items['scenes'])} 个"
                QMessageBox.information(self, "成功", msg)
                
                self.continuous_mode = False
                return # Exit early
            
            # Single episode logic with new format
            next_id = len(self.current_series_manager.data["episodes"]) + 1
            title = script_data.get("title") or f"第{next_id}集"
            
            # Auto-create characters, props, and scenes
            project_dir = self.current_series_manager.project_dir
            created_items = self._auto_create_resources(script_data, project_dir)
            
            # Enhance video prompts
            script_data = self._enhance_video_prompts(script_data)
            
            # Convert to JSON string for storage
            json_str = json.dumps(script_data, ensure_ascii=False)
            
            self.current_series_manager.add_episode(title, json_str)
            self.refresh_episode_list()
            
            # Calculate total episodes in project
            total_episodes = len(self.current_series_manager.data.get("episodes", []))
            
            # Show success message with created items
            msg = f"第 {next_id} 集 '{title}' 生成成功！\n\n"
            msg += f"项目当前共 {total_episodes} 集剧本。\n\n已自动创建:\n"
            msg += f"- 角色: {len(created_items['characters'])} 个\n"
            msg += f"- 道具: {len(created_items['props'])} 个\n"
            msg += f"- 场景: {len(created_items['scenes'])} 个"
            QMessageBox.information(self, "生成成功", msg)
            
            # Check Continuous
            total = int(self.current_series_manager.data.get("total_episodes", 100))
            current_count = len(self.current_series_manager.data["episodes"])
            
            if self.continuous_mode and current_count < total:
                # Continue
                next_idea = "Continue the story based on the outline and previous events."
                self.status_label.setText(f"第 {next_id} 集生成完毕，休息 5 秒后继续...")
                
                # Delay 5 seconds to avoid rate limits
                QTimer.singleShot(5000, lambda: self.start_script_generation(next_idea) if self.continuous_mode else None)
            else:
                # Done
                self.progress_bar.hide()
                self.cancel_btn.hide()
                self.status_label.setText("生成完毕")
                self.update_button_states()
                
                # Show total episodes generated
                total_episodes = len(self.current_series_manager.data.get("episodes", []))
                QMessageBox.information(self, "成功", f"生成完毕！\n\n共生成 {total_episodes} 集剧本。")
                self.continuous_mode = False
            
        except Exception as e:
            self.progress_bar.hide()
            self.cancel_btn.hide()
            self.status_label.setText("处理结果失败")
            self.update_button_states()
            
            QMessageBox.warning(self, "错误", f"保存生成结果失败: {e}")
            import traceback
            traceback.print_exc()
            self.continuous_mode = False
    
    def _auto_create_resources(self, data, project_dir):
        """Automatically create characters, props, and scenes from generated data"""
        return script_service.create_resources_from_data(data, project_dir)

    def _normalize_script_data(self, script_data):
        """保证剧本数据包含至少 5 个 shots 且字段齐全（委托 core.script.script_service）"""
        return script_service.normalize_script_data(script_data)

    def _enhance_video_prompts(self, script_data):
        """增强剧本中的视频提示词（委托 core.script.script_service）"""
        return script_service.enhance_video_prompts(script_data)

    def _discard_detached_thread(self, thread):
        """已取消的后台线程自然结束后，释放引用。"""
        detached = getattr(self, '_detached_threads', None)
        if detached is not None:
            detached.discard(thread)
            if not detached:
                # 被停止的任务都已退出 → 清掉全局取消标记，
                # 免得影响其它页面（剧本/角色/视频）后续正常发起的 LLM 请求
                _reset_cancel()
        thread.deleteLater()

    def _begin_background_op(self):
        """开始后台生成前，清除上一轮「停止」留下的全局取消标记。"""
        _reset_cancel()

    def cancel_generation(self):
        # 让正在流式生成的 LLM 请求立刻断开（服务端随之中断推理），
        # 而不是等整段生成自然跑完
        try:
            from ai_engine.utils.cancel import request_cancel as _cancel_request
        except ImportError:
            from src.ai_engine.utils.cancel import request_cancel as _cancel_request
        _cancel_request()
        self.continuous_mode = False
        if hasattr(self, 'adaptation_state'):
            self.adaptation_state["active"] = False
            
        self.status_label.setText("正在停止...")
        self.cancel_btn.setEnabled(False)
        
        # Try to stop threads if running
        # 安全说明：不再使用 QThread.terminate()。
        # 线程可能在 requests 调用中持有 GIL，terminate() 在 Windows 上可能
        # 造成进程死锁/崩溃。改为：断开结果信号 + requestInterruption()，
        # 让网络请求在后台自然结束，其结果被丢弃（不再写回 UI/磁盘）。
        if not hasattr(self, '_detached_threads'):
            self._detached_threads = set()

        def _detach_thread(thread, slot):
            try:
                thread.finished.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            thread.requestInterruption()
            # 持有引用直到真正结束，防止 "QThread: Destroyed while still running" 崩溃
            self._detached_threads.add(thread)
            thread.finished.connect(lambda t=thread: self._discard_detached_thread(t))

        if hasattr(self, 'gen_thread') and self.gen_thread.isRunning():
            _detach_thread(self.gen_thread, self.on_script_generated)

        if hasattr(self, 'outline_thread') and self.outline_thread.isRunning():
            _detach_thread(self.outline_thread, self.on_outline_generated)

        if hasattr(self, 'adapt_thread') and self.adapt_thread.isRunning():
            _detach_thread(self.adapt_thread, self.on_adaptation_finished)

        # 长篇预处理线程同样要停（finished 已断开，避免取消后又继续去改编）
        if hasattr(self, 'prep_thread') and self.prep_thread.isRunning():
            _detach_thread(self.prep_thread, self._on_long_source_prepared)
            
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.cancel_btn.setEnabled(True)
        self.status_label.setText("已停止")
        self.update_button_states()

    def adapt_script(self):
        if not self.current_series_manager:
            return
            
        # Check if episodes exist
        ep_count = len(self.current_series_manager.data.get("episodes", []))
        if ep_count > 0:
             reply = QMessageBox.question(
                self, 
                "确认改编", 
                f"当前项目已有 {ep_count} 集剧本。\n是否继续改编生成新的集数？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.Yes
            )
             if reply == QMessageBox.StandardButton.No:
                return
            
        dialog = AdaptScriptDialog(self.config_manager, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        data = dialog.get_data()
        api_config = data["api_config"]
        source_text = data["source_text"]
        style = data["style"]
        episode_count = data["episode_count"]
        words_per_episode = data.get("words_per_episode", 500)
        is_continuous = data.get("continuous", False)
        
        if not source_text.strip():
            QMessageBox.warning(self, "提示", "请输入或导入原文内容")
            return
            
        # Update UI
        self.progress_bar.show()
        self.cancel_btn.show()
        self.edit_info_btn.setEnabled(False) # Disable edit button during adaptation
        
        # Initialize Adaptation State
        self.adaptation_state = {
            "active": True,
            "api_config": api_config,
            "source_text": source_text,
            "style": style,
            "total_episodes": episode_count,
            "words_per_episode": words_per_episode,
            "current_episode": 1,
            "is_continuous": is_continuous
        }

        # 长篇原作：先做分块/摘要/大纲/向量化，再开始逐集改编。
        # 若已处理过但原文长度变化（重新导入了不同文本），则重新预处理。
        _need_prep = False
        if is_long_source_text(source_text):
            try:
                _old_len = int(self.current_series_manager.data.get("source_total_chars") or 0)
            except (TypeError, ValueError):
                _old_len = 0
            _need_prep = (not self.current_series_manager.is_long_source()
                          or _old_len != len(source_text))
        if _need_prep:
            self.status_label.setText("正在处理长篇原作（分块/摘要/建立索引）...")
            self.prep_thread = LongSourcePrepThread(
                source_text, self.current_series_manager, api_config,
                self.config_manager.get_embedding_config(), self)
            for sig, slot in (("finished", self._on_long_source_prepared),
                              ("error", self._on_long_source_prep_error),
                              ("cancelled", self._on_long_source_prep_cancelled)):
                try:
                    getattr(self.prep_thread, sig).disconnect()
                except Exception:
                    pass
                getattr(self.prep_thread, sig).connect(slot)
            self.prep_thread.progress.connect(
                lambda msg: self.status_label.setText(msg))
            self._begin_background_op()
            self.prep_thread.start()
            return

        self.start_adaptation_step()

    def _on_long_source_prepared(self, result):
        n = len(result.get("chunks") or [])
        self.status_label.setText(f"长篇原作处理完成（{n} 块），开始改编...")
        self.start_adaptation_step()

    def _on_long_source_prep_error(self, msg):
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.status_label.setText("长篇处理失败")
        self.update_button_states()
        self.adaptation_state["active"] = False
        QMessageBox.warning(self, "错误", f"长篇原作处理失败：{msg}")

    def _on_long_source_prep_cancelled(self):
        """长篇预处理线程因用户「停止」而结束（不是失败，不弹错误框）。"""
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.cancel_btn.setEnabled(True)
        self.status_label.setText("已停止")
        self.update_button_states()
        self.adaptation_state["active"] = False

    def start_adaptation_step(self):
        state = self.adaptation_state
        if not state["active"]:
            return

        current = state["current_episode"]
        total = state["total_episodes"]
        
        # Prepare Context
        previous_context = ""
        character_list = self.current_series_manager.data.get("main_characters", "")
        
        if current > 1:
            # Try to get the last episode's content
            episodes = self.current_series_manager.data.get("episodes", [])
            if episodes:
                last_ep = episodes[-1]
                # If we have a summary, use it. Otherwise extract key info from content.
                if last_ep.get("summary"):
                    previous_context = f"Summary of Episode {len(episodes)}: {last_ep.get('summary')}"
                else:
                    # Extract only plot-related fields, not the full prompts
                    try:
                        content = last_ep.get("content", "")
                        # Try to parse JSON and extract only story elements
                        ep_data = json.loads(content) if isinstance(content, str) else content
                        if isinstance(ep_data, dict):
                            # Extract shots with only story-relevant fields
                            shots_summary = []
                            shots = ep_data.get("shots", ep_data.get("scenes", []))
                            for shot in shots[:5]:  # Only last 5 shots for context
                                shot_info = {
                                    "shot_id": shot.get("shot_id", shot.get("scene_id", "")),
                                    "location": shot.get("scene_location", shot.get("location", "")),
                                    "characters": shot.get("characters", ""),
                                    "action": shot.get("action", ""),
                                    "dialogue": shot.get("dialogue", "")
                                }
                                shots_summary.append(shot_info)
                            
                            previous_context = f"Previous Episode {len(episodes)} - Last {len(shots_summary)} shots:\n"
                            previous_context += json.dumps(shots_summary, ensure_ascii=False, indent=2)
                        else:
                            # Fallback to simple text excerpt
                            excerpt = content[-1000:] if len(content) > 1000 else content
                            previous_context = f"Previous episode excerpt:\n{excerpt}"
                    except Exception:
                        # If parsing fails, use minimal excerpt
                        content = last_ep.get("content", "")
                        excerpt = content[-500:] if len(content) > 500 else content
                        previous_context = f"Previous episode story continuation..."
                
                # Add format reminder for subsequent episodes
                previous_context += "\n\nIMPORTANT: Continue using the SAME structured format for video_prompt as specified in the system instructions."

        # 获取项目语言
        language = self.get_project_language()

        # 长篇模式：取本集对应的原文上下文（大纲分段 + 块摘要 + 检索原文），
        # 避免把整部小说塞进单次 prompt
        source_context = ""
        if self.current_series_manager.is_long_source():
            try:
                from core.script.source_chunker import build_episode_source_context
            except ImportError:
                from src.core.script.source_chunker import build_episode_source_context
            source_context = build_episode_source_context(
                self.current_series_manager, current, total,
                embedding_config=self.config_manager.get_embedding_config(),
            ) or ""

        if state["is_continuous"]:
            # Serial Mode: Generate one by one
            self.status_label.setText(f"正在改编第 {current}/{total} 集...")
            self.adapt_thread = ScriptAdaptationThread(
                state["api_config"],
                state["source_text"],
                state["style"],
                total,
                state["words_per_episode"],
                current_episode_index=current,
                previous_context=previous_context,
                character_list=character_list,
                language=language,
                source_context=source_context
            )
        else:
            # Batch Mode: Generate all at once (Legacy behavior)
            self.status_label.setText(f"正在批量改编 {total} 集...")
            self.adapt_thread = ScriptAdaptationThread(
                state["api_config"],
                state["source_text"],
                state["style"],
                total,
                state["words_per_episode"],
                previous_context=previous_context,
                character_list=character_list,
                language=language,
                source_context=source_context
            )
            
        # Disconnect any previous connections to be safe
        try:
            self.adapt_thread.finished.disconnect()
        except Exception:
            pass
        self.adapt_thread.finished.connect(self.on_adaptation_finished)
        self.adapt_thread.error.connect(self.handle_gen_error)
        self._begin_background_op()
        self.adapt_thread.start()

    def _fix_json_string(self, text):
        """Try to fix common JSON string issues"""
        # Escape unescaped quotes in string values
        # This is a simple heuristic - look for patterns like "text": "value with "quotes" inside"
        # and escape the inner quotes
        
        # Method 1: Try to fix newlines inside string values
        # JSON strings should not have literal newlines, they should be \n
        # But AI often generates them with actual newlines
        
        # Method 2: Try to parse and fix incrementally
        lines = text.split('\n')
        fixed_lines = []
        in_string = False
        for line in lines:
            # Count quotes in line to determine if we're inside a string
            quote_count = line.count('"')
            # If odd number of quotes and line contains certain patterns, might need escaping
            if quote_count % 2 == 1 and ':' not in line:
                # This line might have an unescaped quote or newline issue
                # Try to escape internal quotes
                pass
            fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)

    def _fix_json_newlines(self, text):
        """Fix literal newlines inside JSON string values"""
        # This is a heuristic to fix JSON where AI put actual newlines inside string values
        # instead of \n escape sequences
        result = []
        i = 0
        in_string = False
        while i < len(text):
            char = text[i]
            if char == '"' and (i == 0 or text[i-1] != '\\'):
                in_string = not in_string
                result.append(char)
            elif char == '\n' and in_string:
                # Replace literal newline with \n escape sequence
                result.append('\\n')
            elif char == '\r' and in_string:
                # Skip carriage return inside strings
                pass
            elif char == '\t' and in_string:
                # Replace literal tab with \t escape sequence
                result.append('\\t')
            else:
                result.append(char)
            i += 1
        return ''.join(result)

    def _escape_json_quotes(self, text):
        """Try to escape unescaped quotes inside JSON string values"""
        # This is a heuristic to fix JSON where AI put unescaped quotes inside string values
        # We look for patterns like "text": "value with "quotes" inside"
        # and escape the inner quotes
        
        # Simple approach: find string values and escape any unescaped quotes inside them
        result = []
        i = 0
        while i < len(text):
            if text[i] == '"':
                # Found a quote, check if it's escaped
                if i > 0 and text[i-1] == '\\':
                    result.append('"')
                else:
                    result.append('"')
            else:
                result.append(text[i])
            i += 1
        return ''.join(result)

    def _fix_truncated_json(self, text):
        """Try to fix truncated JSON by adding missing closing brackets/braces"""
        # Count opening and closing brackets/braces
        open_braces = text.count('{')
        close_braces = text.count('}')
        open_brackets = text.count('[')
        close_brackets = text.count(']')
        
        # Add missing closing brackets/braces
        fixed = text
        
        # First, try to find where the JSON structure ends
        # Look for the last complete string value
        last_quote = text.rfind('"')
        if last_quote > 0:
            # Check if we're inside a string (odd number of quotes before this point)
            quotes_before = text[:last_quote].count('"')
            if quotes_before % 2 == 1:
                # We're inside a string, close it
                fixed = text[:last_quote] + '"' + text[last_quote+1:]
        
        # Add missing closing braces
        while open_braces > close_braces:
            fixed += '}'
            close_braces += 1
        
        # Add missing closing brackets
        while open_brackets > close_brackets:
            fixed += ']'
            close_brackets += 1
        
        # Remove trailing commas before closing brackets/braces
        fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)
        
        return fixed

    def _extract_json_from_text(self, text):
        """Try to extract JSON from text that may contain markdown or other content"""
        if isinstance(text, dict):
            return text
        
        if not isinstance(text, str):
            raise json.JSONDecodeError(f"Expected string or dict, got {type(text)}", str(text), 0)
        
        # Clean up the text first
        text = text.strip()
        
        # Remove BOM if present
        if text.startswith('\ufeff'):
            text = text[1:]
        
        # Remove control characters (except newline, tab, carriage return)
        import re as re_clean
        text = re_clean.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        
        # Debug: print first few characters
        print(f"DEBUG _extract_json_from_text: text length = {len(text)}")
        print(f"DEBUG _extract_json_from_text: first 50 chars = {repr(text[:50])}")
        
        # Try direct JSON parse first
        try:
            result = json.loads(text)
            print("DEBUG: Direct JSON parse successful")
            return result
        except json.JSONDecodeError as e:
            print(f"DEBUG: Direct JSON parse failed: {e}")
            
            # Try to fix the JSON and parse again
            # Common issue: newlines inside string values should be escaped
            try:
                # Replace literal newlines inside string values with \n
                # This is a heuristic that works for most cases
                fixed_text = self._fix_json_newlines(text)
                if fixed_text != text:
                    result = json.loads(fixed_text)
                    print("DEBUG: JSON parse successful after fixing newlines")
                    return result
            except json.JSONDecodeError:
                pass
            
            # Try another fix: escape unescaped quotes in values
            try:
                fixed_text = self._escape_json_quotes(text)
                if fixed_text != text:
                    result = json.loads(fixed_text)
                    print("DEBUG: JSON parse successful after escaping quotes")
                    return result
            except json.JSONDecodeError:
                pass
            
            # Try to fix truncated JSON by adding missing closing brackets/braces
            try:
                fixed_text = self._fix_truncated_json(text)
                if fixed_text != text:
                    result = json.loads(fixed_text)
                    print("DEBUG: JSON parse successful after fixing truncated JSON")
                    return result
            except json.JSONDecodeError:
                pass
            pass
        
        # Try to find JSON between markdown code blocks
        # Pattern 1: ```json ... ```
        pattern1 = r'```json\s*(.*?)\s*```'
        matches = re.findall(pattern1, text, re.DOTALL)
        for match in matches:
            try:
                result = json.loads(match.strip())
                print("DEBUG: JSON extracted from ```json block")
                return result
            except json.JSONDecodeError:
                continue
        
        # Pattern 2: ``` ... ``` (any code block)
        pattern2 = r'```\s*(.*?)\s*```'
        matches = re.findall(pattern2, text, re.DOTALL)
        for match in matches:
            try:
                result = json.loads(match.strip())
                print("DEBUG: JSON extracted from ``` block")
                return result
            except json.JSONDecodeError:
                continue
        
        # Pattern 3: Find JSON object/array starting with { or [
        # Look for the outermost JSON structure
        pattern3 = r'(\{[\s\S]*\}|\[[\s\S]*\])'
        matches = re.findall(pattern3, text)
        for match in matches:
            try:
                # Try to parse to verify it's valid JSON
                parsed = json.loads(match)
                # Check if it has expected structure
                if isinstance(parsed, dict) and ("episodes" in parsed or "shots" in parsed or "scenes" in parsed):
                    print("DEBUG: JSON extracted via pattern3 (dict with episodes/shots/scenes)")
                    return parsed
                elif isinstance(parsed, list) and len(parsed) > 0:
                    # Might be a list of episodes
                    print("DEBUG: JSON extracted via pattern3 (list)")
                    return {"episodes": parsed}
            except json.JSONDecodeError:
                continue
        
        # If all attempts fail, raise the original error with more details
        print(f"DEBUG: Failed to extract JSON. Text length: {len(text)}")
        print(f"DEBUG: First 200 chars: {repr(text[:200])}")
        print(f"DEBUG: Last 200 chars: {repr(text[-200:])}")
        raise json.JSONDecodeError("Could not extract valid JSON from text", text, 0)

    def on_adaptation_finished(self, result):
        """Handle adaptation result with characters, props, and scenes"""
        if not self.adaptation_state["active"]:
            return

        try:
            # Handle dict data directly (new format) or parse JSON string
            if isinstance(result, dict):
                data = result
            else:
                # Try to extract JSON from the result
                data = self._extract_json_from_text(result)
            
            episodes_to_save = []
            all_created_items = {
                "characters": [],
                "props": [],
                "scenes": []
            }
            
            # Case A: {"episodes": [...]}
            if "episodes" in data and isinstance(data["episodes"], list):
                episodes_to_save = data["episodes"]
            # Case B: Single episode object {"title": ..., "shots": ...} (new format)
            elif "shots" in data:
                episodes_to_save = [data]
            # Case C: Single episode object {"title": ..., "scenes": ...} (legacy format)
            elif "scenes" in data:
                episodes_to_save = [data]
            else:
                episodes_to_save = [{"title": "Adapted Script", "content": data}]

            count = 0
            project_dir = self.current_series_manager.project_dir
            existing_count = len(self.current_series_manager.data["episodes"])
            
            for i, ep_data in enumerate(episodes_to_save):
                ep_id = i + 1
                title = ep_data.get("title") or f"第{existing_count + ep_id}集"
                
                # Auto-create characters, props, and scenes for each episode
                created_items = self._auto_create_resources(ep_data, project_dir)
                all_created_items["characters"].extend(created_items["characters"])
                all_created_items["props"].extend(created_items["props"])
                all_created_items["scenes"].extend(created_items["scenes"])
                
                # Enhance video prompts
                ep_data = self._enhance_video_prompts(ep_data)
                
                content_str = json.dumps(ep_data, ensure_ascii=False)
                if i < existing_count:
                    # Replace existing episode (re-adaptation)
                    self.current_series_manager.update_episode(ep_id, title, content_str)
                    # Clear stale storyboard character data for replaced episode
                    sb_path = os.path.join(project_dir, "storyboards", f"episode_{ep_id}.json")
                    if os.path.exists(sb_path):
                        try:
                            from core.storyboard.storyboard_model import Storyboard
                            with open(sb_path, 'r', encoding='utf-8') as f:
                                sb = Storyboard.from_json(f.read())
                            for panel in sb.panels:
                                panel.characters = []
                                panel.props = []
                            sb.save(sb_path)
                            print(f"DEBUG: Cleared stale storyboard data for episode {ep_id}")
                        except Exception as e:
                            print(f"DEBUG: Error clearing storyboard data: {e}")
                else:
                    # Add new episode
                    self.current_series_manager.add_episode(title, content_str)
                count += 1
            
            self.refresh_episode_list()
            
            # Check if we need to continue
            state = self.adaptation_state
            if state["is_continuous"]:
                state["current_episode"] += 1
                if state["current_episode"] <= state["total_episodes"]:
                    # Continue to next episode
                    self.status_label.setText(f"第 {state['current_episode']-1} 集完成，休息 3 秒后继续...")
                    QTimer.singleShot(3000, self.start_adaptation_step)
                    return # Exit, don't reset UI yet

            # If we are here, we are done (either Batch mode finished, or Serial mode finished all eps)
            self.progress_bar.hide()
            self.cancel_btn.hide()
            self.status_label.setText("改编完成")
            self.update_button_states()
            self.adaptation_state["active"] = False
            
            # Calculate total episodes generated in this adaptation session
            # Use the actual episode count from the series manager
            total_episodes_in_project = len(self.current_series_manager.data.get("episodes", []))
            
            # Show success message with created items
            msg = f"改编任务全部完成！\n\n共生成 {total_episodes_in_project} 集\n\n已自动创建:\n"
            msg += f"- 角色: {len(all_created_items['characters'])} 个\n"
            msg += f"- 道具: {len(all_created_items['props'])} 个\n"
            msg += f"- 场景: {len(all_created_items['scenes'])} 个"
            QMessageBox.information(self, "成功", msg)
            
        except json.JSONDecodeError as e:
            # Case D: Not JSON (Raw text)
            next_id = len(self.current_series_manager.data["episodes"]) + 1
            self.current_series_manager.add_episode(f"第{next_id}集", result if isinstance(result, str) else json.dumps(result))
            self.refresh_episode_list()
            
            # If serial mode fails to parse JSON, we probably should stop or continue?
            # Let's stop to be safe.
            self.progress_bar.hide()
            self.cancel_btn.hide()
            self.status_label.setText("改编中断 (格式错误)")
            self.update_button_states()
            self.adaptation_state["active"] = False
            
            # Show detailed error with preview of the response
            import reprlib
            preview = reprlib.repr(result) if isinstance(result, str) else str(result)
            error_msg = f"返回的内容不是标准的JSON格式，已作为纯文本保存，任务停止。\n\n"
            error_msg += f"错误信息: {str(e)}\n\n"
            error_msg += f"返回内容类型: {type(result)}\n"
            error_msg += f"返回内容长度: {len(result) if isinstance(result, str) else 'N/A'}\n"
            error_msg += f"返回内容预览:\n{preview[:1000]}"
            QMessageBox.warning(self, "注意", error_msg)
            
        except Exception as e:
            self.progress_bar.hide()
            self.cancel_btn.hide()
            self.status_label.setText("改编出错")
            self.update_button_states()
            self.adaptation_state["active"] = False
            QMessageBox.warning(self, "错误", f"保存结果时出错: {e}")
            import traceback
            traceback.print_exc()

    def generate_next_episode_placeholder(self):
        # Legacy placeholder method - kept if needed or replaced
        pass

    def on_episode_clicked(self, item):
        try:
            ep_id = item.data(Qt.ItemDataRole.UserRole)
            if ep_id is None:
                return
            if not self.current_project_path:
                QMessageBox.warning(self, "错误", "当前没有选中项目")
                return
            # Emit signal to open this episode in Script Window
            self.open_episode.emit(self.current_project_path, str(ep_id))
        except Exception as e:
            print(f"点击集数时出错: {e}")
            QMessageBox.warning(self, "错误", f"点击集数时出现错误: {str(e)}")

    def load_project_by_path(self, path):
        """按路径恢复项目的选中态与详情。

        主题/皮肤切换会重建页面，重建后需要据此恢复当前项目，
        否则项目页会回到“未选中任何项目”的状态。
        """
        if not path or not os.path.isdir(path):
            return
        try:
            # 在列表中定位并选中该项，同时同步项目类型
            for i in range(self.project_list.count()):
                item = self.project_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == path:
                    self.project_list.setCurrentItem(item)
                    p_type = item.data(Qt.ItemDataRole.UserRole + 1)
                    if p_type:
                        self.current_project_type = p_type
                    break
            self.delete_btn.setEnabled(True)
            self.load_project_details(path)
        except Exception as e:
            print(f"[WARN] load_project_by_path: {e}")

    def create_project(self):
        dialog = NewProjectDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            name = data.pop("name")
            if name:
                try:
                    path = self.manager.create_project(name, extra_data=data)
                    self.refresh_list()
                    QMessageBox.information(self, "成功", f"项目 '{name}' 已创建。")
                except ValueError as e:
                    QMessageBox.warning(self, "错误", str(e))

    def refresh_list(self):
        self.project_list.clear()
        projects = self.manager.list_projects()
        for p in projects:
            p_type = p.get("type", "original")
            type_tag = "[改编]" if p_type == "adaptation" else "[原创]"
            # 有未完成任务的项目标注「可续跑」，方便一眼找到
            resumable = self._project_can_resume(p['path'])
            tag = f"{type_tag} {p['name']}" + ("  ⟨可续跑⟩" if resumable else "")
            self.project_list.addItem(tag)
            # Store path in item
            item = self.project_list.item(self.project_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, p['path'])
            item.setData(Qt.ItemDataRole.UserRole + 1, p_type)
            item.setData(Qt.ItemDataRole.UserRole + 2, bool(resumable))
        if hasattr(self, "resume_btn"):
            self.resume_btn.setEnabled(False)

    def load_selected_project(self):
        item = self.project_list.currentItem()
        if item:
            path = item.data(Qt.ItemDataRole.UserRole)
            p_type = item.data(Qt.ItemDataRole.UserRole + 1)
            
            self.current_project_type = p_type
            self.project_loaded.emit(path)
            
            # Update UI based on project type
            self.update_button_states()
                
            show_message(self, "已加载", f"项目已加载: {item.text()}")

    def update_button_states(self):
        self.edit_info_btn.setEnabled(True)
        if hasattr(self, "resume_btn"):
            self.resume_btn.setEnabled(self._project_can_resume(self.current_project_path))

    def _create_from_template(self):
        """从模板创建：跳转到剧本页并打开模板选择器。"""
        if not self.current_project_path:
            QMessageBox.information(self, "提示", "请先加载一个项目。")
            return
        # 通知主窗口切换到剧本页（索引2），并传递项目路径
        self.open_episode.emit(self.current_project_path, "0")
        # 稍后触发剧本页的模板选择
        QTimer.singleShot(500, self._trigger_script_template)

    def _trigger_script_template(self):
        try:
            mw = self.window()
            sw = getattr(mw, 'script_window', None)
            if sw is None:
                return
            # 确保剧本页已加载当前项目
            if getattr(sw, 'project_dir', None) != self.current_project_path:
                if hasattr(sw, 'set_project_dir'):
                    sw.set_project_dir(self.current_project_path)
                else:
                    sw.project_dir = self.current_project_path
                if hasattr(sw, 'check_project_status'):
                    sw.check_project_status()
            sw._create_from_template()
        except Exception as e:
            print(f"[WARN] _trigger_script_template: {e}")
