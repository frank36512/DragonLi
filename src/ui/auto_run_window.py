# -*- coding: utf-8 -*-
"""一键成片（全自动流水线）：首页 Hero 卡 + 模态弹窗式进度/检查点/日志。"""
import os
import json
import re

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QComboBox, QSpinBox, QCheckBox, QPushButton,
                             QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QFileDialog,
                             QGroupBox, QMessageBox, QSplitter, QFrame, QDialog,
                             QButtonGroup, QScrollArea, QListWidget, QListWidgetItem,
                             QListView, QStackedWidget, QAbstractSpinBox)
from core.project.project_manager import ProjectManager
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, QEvent
from PyQt6.QtGui import QColor, QPixmap, QStandardItem, QStandardItemModel
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from ui import theme as _theme

try:
    from core.autorun import AutoRunController, AutoRunParams, PipelineState, STAGES, STAGE_LABELS
    from core.autorun.params import GENERATE_MODE_LABELS
    from core.config.config_manager import ConfigManager
except ImportError:
    from src.core.autorun import AutoRunController, AutoRunParams, PipelineState, STAGES, STAGE_LABELS
    from src.core.autorun.params import GENERATE_MODE_LABELS
    from src.core.config.config_manager import ConfigManager

DURATION_OPTIONS = ["智能时长", "300字", "500字", "800字", "1000字+"]


class GenerateModeDialog(QDialog):
    """一键成片启动前的配置弹窗：选择生成调度模式 + 检查点阶段。

    采用主题样式卡片式选择，底部「取消 / 下一步」按钮。
    检查点语义随生成模式变化：
    - 逐集：每集完成到该阶段时暂停检查
    - 逐类：所有集完成该阶段后统一暂停检查
    """

    # 两种模式的描述信息
    MODES = [
        {
            "key": "episode",
            "title": "逐集生成",
            "icon": "🎬",
            "desc": "一集的剧本、角色、场景、视频全部完成后，再开始下一集。",
            "tip": "适合：希望逐集出片、可中途检查单集成片效果。",
        },
        {
            "key": "category",
            "title": "逐类生成",
            "icon": "📦",
            "desc": "先完成所有集的剧本+角色/场景/道具，再统一生成所有集的视频片段，最后逐集合成成片。",
            "tip": "适合：多集项目，便于统一审核剧本后再批量出视频。",
        },
    ]

    # 检查点阶段在不同模式下的说明文字
    CHECKPOINT_HINTS = {
        "episode": {
            "script": "每集剧本+分镜完成后暂停，可检查剧本与分镜",
            "clips": "每集视频片段生成完成后暂停",
            "subtitles": "每集字幕生成后暂停",
            "compose": "每集成片完成后暂停",
        },
        "category": {
            "script": "所有集剧本+分镜完成后统一暂停检查",
            "clips": "所有集视频片段完成后统一暂停检查",
            "subtitles": "所有集字幕完成后统一暂停检查",
            "compose": "所有集成片完成后统一暂停检查",
        },
    }

    def __init__(self, parent=None, default_mode="episode", default_checkpoints=None):
        super().__init__(parent)
        self.setWindowTitle("生成配置")
        self.setObjectName("ThemedDialog")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMaximumWidth(640)

        self._selected_mode = default_mode if default_mode in ("episode", "category") else "episode"
        self._default_checkpoints = default_checkpoints or []
        self._checkboxes = {}  # stage -> QCheckBox
        self._hint_labels = {}  # stage -> QLabel

        self._build_ui()
        self._apply_mode(self._selected_mode)

    def _card_qss(self, selected: bool) -> str:
        accent = _theme.color("accent")
        panel = _theme.color("panel")
        border = _theme.color("border_strong")
        selected_bg = _theme.color("selected")
        if selected:
            return (f"QFrame#ModeCard {{ background: {selected_bg}; "
                    f"border: 2px solid {accent}; border-radius: 12px; }}")
        return (f"QFrame#ModeCard {{ background: {panel}; "
                f"border: 1px solid {border}; border-radius: 12px; }}")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # 标题
        title = QLabel("⚙️ 生成配置")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        root.addWidget(title)

        subtitle = QLabel("请选择生成调度模式与检查点")
        subtitle.setProperty("dim", True)
        root.addWidget(subtitle)

        # ---- 模式选择卡片 ----
        mode_label = QLabel("调度模式")
        mode_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        root.addWidget(mode_label)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)
        self._cards = {}
        self._check_mark = {}
        for m in self.MODES:
            card = QFrame()
            card.setObjectName("ModeCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet(self._card_qss(m["key"] == self._selected_mode))

            lay = QVBoxLayout(card)
            lay.setContentsMargins(16, 14, 16, 14)
            lay.setSpacing(6)

            header = QHBoxLayout()
            icon_lbl = QLabel(m["icon"])
            icon_lbl.setStyleSheet("font-size: 22px;")
            t = QLabel(m["title"])
            t.setStyleSheet("font-size: 15px; font-weight: 700;")
            header.addWidget(icon_lbl)
            header.addWidget(t)
            header.addStretch()
            check = QLabel("✓")
            check.setStyleSheet(
                f"color: {_theme.color('accent')}; font-size: 16px; font-weight: 800;")
            check.setVisible(m["key"] == self._selected_mode)
            header.addWidget(check)
            self._check_mark[m["key"]] = check
            lay.addLayout(header)

            desc = QLabel(m["desc"])
            desc.setWordWrap(True)
            desc.setProperty("dim", True)
            lay.addWidget(desc)

            tip = QLabel(m["tip"])
            tip.setWordWrap(True)
            tip.setStyleSheet(f"color: {_theme.color('accent2')}; font-size: 12px;")
            lay.addWidget(tip)

            card.mousePressEvent = lambda e, k=m["key"]: self._on_card_clicked(k)
            cards_layout.addWidget(card)
            self._cards[m["key"]] = card

        root.addLayout(cards_layout)

        # ---- 检查点选择 ----
        cp_label = QLabel("检查点")
        cp_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        root.addWidget(cp_label)

        cp_hint = QLabel("勾选的阶段完成后会暂停并弹出预览，等待确认后继续。默认不勾选，全自动跑完。")
        cp_hint.setWordWrap(True)
        cp_hint.setProperty("dim", True)
        root.addWidget(cp_hint)

        self._cp_container = QVBoxLayout()
        self._cp_container.setSpacing(6)
        default_cp = set(self._default_checkpoints)
        for stage in STAGES:
            row = QHBoxLayout()
            row.setSpacing(10)
            cb = QCheckBox(STAGE_LABELS.get(stage, stage))
            cb.setChecked(stage in default_cp)
            cb.toggled.connect(lambda _checked, s=stage: self._update_hint(s))
            hint = QLabel("")
            hint.setProperty("dim", True)
            hint.setStyleSheet("font-size: 12px;")
            row.addWidget(cb)
            row.addWidget(hint, 1)
            self._cp_container.addLayout(row)
            self._checkboxes[stage] = cb
            self._hint_labels[stage] = hint
        root.addLayout(self._cp_container)

        root.addStretch(1)

        # ---- 底部按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        next_btn = QPushButton("下一步 →")
        next_btn.setObjectName("PrimaryBtn")
        next_btn.setMinimumWidth(120)
        next_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(next_btn)
        root.addLayout(btn_row)

    def _on_card_clicked(self, key):
        self._selected_mode = key
        for k, card in self._cards.items():
            card.setStyleSheet(self._card_qss(k == key))
            self._check_mark[k].setVisible(k == key)
        self._apply_mode(key)

    def _apply_mode(self, mode):
        """切换模式时更新检查点说明文字。"""
        hints = self.CHECKPOINT_HINTS.get(mode, {})
        for stage, lbl in self._hint_labels.items():
            lbl.setText(hints.get(stage, ""))

    def _update_hint(self, stage):
        # 预留：勾选状态变化时可联动，当前仅更新说明
        pass

    def get_result(self):
        """返回 (generate_mode, checkpoints_list)。"""
        checkpoints = [s for s, cb in self._checkboxes.items() if cb.isChecked()]
        return self._selected_mode, checkpoints


class ScriptParamsDialog(QDialog):
    """第二步：配置短剧参数（集数/比例/分辨率/篇幅/语言/画面风格/导出/转场等）。"""

    def __init__(self, parent=None, project_type="original", defaults=None, submit_text="开始生成 →"):
        super().__init__(parent)
        self.setWindowTitle("配置短剧参数")
        self.setObjectName("GenerateModeDialog")
        self.setMinimumWidth(560)
        self.setModal(True)
        self._project_type = project_type
        self._defaults = defaults or {}
        self._submit_text = submit_text
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title = QLabel("短剧参数配置")
        title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {_theme.color('accent')};")
        root.addWidget(title)
        subtitle = QLabel("设定集数、比例、分辨率、篇幅、语言、画面风格、转场等参数")
        subtitle.setStyleSheet(f"color: {_theme.color('text_secondary')}; font-size: 12px;")
        root.addWidget(subtitle)

        body = QWidget()
        body.setStyleSheet(f"background: {_theme.color('bg_elevated')}; border-radius: 10px;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 16, 16, 16)
        bl.setSpacing(10)

        # 集数
        self.episodes_spin = QSpinBox()
        self.episodes_spin.setRange(1, 1000)
        self.episodes_spin.setValue(self._defaults.get("episode_count", 1))
        self.episodes_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.episodes_spin.setToolTip("集数（1-1000）")
        bl.addWidget(self._field("集数", self.episodes_spin))

        # 比例 + 分辨率
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.ratio_combo = QComboBox()
        self.ratio_combo.addItem("横屏 16:9", "16:9")
        self.ratio_combo.addItem("竖屏 9:16", "9:16")
        r = self._defaults.get("ratio", "16:9")
        idx = self.ratio_combo.findData(r)
        if idx >= 0:
            self.ratio_combo.setCurrentIndex(idx)
        row1.addWidget(self._field("比例", self.ratio_combo), 1)

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("1080P", "1080p")
        self.resolution_combo.addItem("720P", "720p")
        res = self._defaults.get("resolution", "1080p")
        idx = self.resolution_combo.findData(res)
        if idx >= 0:
            self.resolution_combo.setCurrentIndex(idx)
        row1.addWidget(self._field("分辨率", self.resolution_combo), 1)
        bl.addLayout(row1)

        # 篇幅 + 语言
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.duration_combo = QComboBox()
        self.duration_combo.addItems(DURATION_OPTIONS)
        d = self._defaults.get("duration", DURATION_OPTIONS[0])
        idx = self.duration_combo.findText(d)
        if idx >= 0:
            self.duration_combo.setCurrentIndex(idx)
        row2.addWidget(self._field("篇幅", self.duration_combo), 1)

        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("English", "en")
        lg = self._defaults.get("language", "zh")
        idx = self.language_combo.findData(lg)
        if idx >= 0:
            self.language_combo.setCurrentIndex(idx)
        row2.addWidget(self._field("语言", self.language_combo), 1)
        bl.addLayout(row2)

        # 画面风格
        self.visual_style_combo = QComboBox()
        try:
            from ui.project_window import VISUAL_STYLES
            self.visual_style_combo.addItems(VISUAL_STYLES)
        except Exception:
            self.visual_style_combo.addItems(["Cinematic (电影质感)", "Anime (日系动漫)", "Realistic (写实摄影)"])
        vs = self._defaults.get("visual_style", "")
        idx = self.visual_style_combo.findText(vs)
        if idx >= 0:
            self.visual_style_combo.setCurrentIndex(idx)
        bl.addWidget(self._field("画面风格", self.visual_style_combo))

        # 导出预设 / 目标平台
        try:
            from core.synthesis.export_preset import list_presets as _list_presets
        except ImportError:
            from src.core.synthesis.export_preset import list_presets as _list_presets
        export_label = "目标平台" if self._project_type == "adaptation" else "导出预设"
        self.preset_combo = QComboBox()
        for _p in _list_presets():
            self.preset_combo.addItem(_p.name, _p.key)
        ep = self._defaults.get("export_preset")
        if ep:
            idx = self.preset_combo.findData(ep)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        bl.addWidget(self._field(export_label, self.preset_combo))

        # 改编幅度（仅改编）
        if self._project_type == "adaptation":
            self.fidelity_combo = QComboBox()
            self.fidelity_combo.addItem("忠于原著", "faithful")
            self.fidelity_combo.addItem("轻度改编", "light")
            self.fidelity_combo.addItem("大幅改编", "heavy")
            fd = self._defaults.get("fidelity", "faithful")
            idx = self.fidelity_combo.findData(fd)
            if idx >= 0:
                self.fidelity_combo.setCurrentIndex(idx)
            bl.addWidget(self._field("改编幅度", self.fidelity_combo))

        # 转场方式 + 时长
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        self.blend_combo = QComboBox()
        self.blend_combo.addItem("硬切", "hardcut")
        self.blend_combo.addItem("淡入淡出", "fade")
        self.blend_combo.addItem("叠化", "crossfade")
        bm = self._defaults.get("blend_mode", "crossfade")
        idx = self.blend_combo.findData(bm)
        if idx >= 0:
            self.blend_combo.setCurrentIndex(idx)
        row3.addWidget(self._field("转场方式", self.blend_combo), 1)

        self.trans_spin = QSpinBox()
        self.trans_spin.setRange(0, 20)
        self.trans_spin.setValue(self._defaults.get("transition_duration", 0))
        self.trans_spin.setSuffix(" x0.1s")
        self.trans_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.trans_spin.setToolTip("转场时长（0.1 秒为单位，0=默认值）")
        row3.addWidget(self._field("转场时长", self.trans_spin), 1)
        bl.addLayout(row3)

        root.addWidget(body)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("GhostBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        next_btn = QPushButton(self._submit_text)
        next_btn.setObjectName("PrimaryBtn")
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.clicked.connect(self.accept)
        btn_row.addWidget(next_btn)
        root.addLayout(btn_row)

    @staticmethod
    def _field(label_text, widget):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"font-size: 12px; color: {_theme.color('text_secondary')};")
        lay.addWidget(lbl)
        widget.setMinimumHeight(32)
        lay.addWidget(widget)
        return box

    def get_params(self):
        params = {
            "episode_count": self.episodes_spin.value(),
            "ratio": self.ratio_combo.currentData(),
            "resolution": self.resolution_combo.currentData(),
            "duration": self.duration_combo.currentText(),
            "language": self.language_combo.currentData(),
            "visual_style": self.visual_style_combo.currentText(),
            "export_preset": self.preset_combo.currentData(),
            "blend_mode": self.blend_combo.currentData(),
            "transition_duration": self.trans_spin.value(),
        }
        if self._project_type == "adaptation":
            params["fidelity"] = self.fidelity_combo.currentData()
        return params


# 检查点阶段 -> 编辑器跳转（主窗口 tab 索引）
# 索引顺序：0首页 1项目 2剧本 3角色 4视频 5素材 6设置 7帮助
EDITOR_JUMP = {
    "script": 2,        # 剧本页（分镜已并入本阶段）
    "clips": 4,         # 视频页
}

_STATUS_TEXT = {
    "pending": "待执行",
    "running": "执行中",
    "cached": "已跳过",
    "success": "完成",
    "failed": "失败",
    "checkpoint": "检查点",
    "episode_start": "开始",
    "episode_done": "完成",
}

def _status_color():
    """阶段状态 -> 颜色（每次调用按当前主题求值）。"""
    return {
        "success": _theme.color("success"),
        "failed": _theme.color("danger"),
        "running": _theme.color("warning"),
        "cached": _theme.color("text_sub"),
        "checkpoint": _theme.color("accent"),
    }


# ======================================================================
#  工作线程
# ======================================================================
class AutoRunThread(QThread):
    progress_changed = pyqtSignal(object, str, str, str)
    checkpoint_reached = pyqtSignal(int, str, list)
    error_reached = pyqtSignal(int, str, str)
    pipeline_finished = pyqtSignal(dict)
    log_line = pyqtSignal(str)

    def __init__(self, project_dir, params, config_manager=None, parent=None):
        super().__init__(parent)
        self.project_dir = project_dir
        self.params = params
        self.config_manager = config_manager
        self.controller = None

    def run(self):
        try:
            self.controller = AutoRunController(
                self.project_dir,
                self.config_manager,
                self.params,
                on_progress=lambda ep, st, status, msg: self.progress_changed.emit(
                    ep, st or "", status, msg or ""),
                on_checkpoint=lambda ep, st, arts: self.checkpoint_reached.emit(
                    int(ep), st, arts or []),
                on_error=lambda ep, st, msg: self.error_reached.emit(int(ep), st, msg or ""),
                on_log=lambda m: self.log_line.emit(str(m)),
            )
            result = self.controller.run()
            self.pipeline_finished.emit(result or {})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.pipeline_finished.emit({"success": False, "errors": [str(e)],
                                         "cancelled": False, "final_outputs": []})


# ======================================================================
#  进度弹窗（模态）
# ======================================================================
class AutoRunProgressDialog(QDialog):
    """一键成片进度弹窗：模态锁定主窗口，检查点时临时解锁供编辑。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("一键成片 - 进度")
        self.setModal(True)
        self.setMinimumSize(720, 560)
        self.resize(820, 640)

        self._tree_items = {}
        self._checkpoint_stage = None
        self._pause_toggled = False
        self._finished = False
        self._thread_ref = None
        self._main_window = None
        self._resume_pending = False   # 用户点了「继续生成」，关闭后由宿主窗口断点续跑

        self._build_ui()

        # 定时刷新日志，确保 QPlainTextEdit 实时更新
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start(200)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # 顶部状态行
        top = QHBoxLayout()
        self.title_label = QLabel("🚀 一键成片进行中...")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        top.addWidget(self.title_label)
        top.addStretch()
        self.status_label = QLabel("准备中...")
        self.status_label.setStyleSheet("font-weight: 600;")
        top.addWidget(self.status_label)
        root.addLayout(top)

        # 进度 + 检查点 + 日志
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 阶段进度树
        self.stage_tree = QTreeWidget()
        self.stage_tree.setHeaderLabels(["集数", "阶段", "状态", "说明"])
        self.stage_tree.setRootIsDecorated(False)
        self.stage_tree.setColumnWidth(0, 60)
        self.stage_tree.setColumnWidth(1, 120)
        self.stage_tree.setColumnWidth(2, 80)
        splitter.addWidget(self.stage_tree)

        # 检查点面板
        self.checkpoint_box = QGroupBox("检查点 / 错误处理")
        cp_panel = QVBoxLayout(self.checkpoint_box)
        self.checkpoint_info = QLabel("")
        self.checkpoint_info.setWordWrap(True)
        cp_panel.addWidget(self.checkpoint_info)

        # 媒体预览区（视频帧缩略图 / 单分镜试播）
        self.media_preview_frame = QFrame()
        self.media_preview_frame.setStyleSheet("background-color: " + _theme.color("bg") + "; border-radius: 4px;")
        mp_layout = QVBoxLayout(self.media_preview_frame)
        mp_layout.setContentsMargins(6, 6, 6, 6)
        mp_layout.setSpacing(4)
        self.media_preview_label = QLabel("媒体预览")
        self.media_preview_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 10px; font-weight: bold;")
        mp_layout.addWidget(self.media_preview_label)

        # 缩略图滚动区
        self.thumb_scroll = QScrollArea()
        self.thumb_scroll.setFixedHeight(100)
        self.thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumb_scroll.setWidgetResizable(True)
        self.thumb_container = QWidget()
        self.thumb_layout = QHBoxLayout(self.thumb_container)
        self.thumb_layout.setContentsMargins(2, 2, 2, 2)
        self.thumb_layout.setSpacing(6)
        self.thumb_layout.addStretch()
        self.thumb_scroll.setWidget(self.thumb_container)
        mp_layout.addWidget(self.thumb_scroll)

        self.media_preview_frame.hide()
        cp_panel.addWidget(self.media_preview_frame)

        self.checkpoint_preview = QPlainTextEdit()
        self.checkpoint_preview.setReadOnly(True)
        self.checkpoint_preview.setMaximumHeight(100)
        cp_panel.addWidget(self.checkpoint_preview)
        cp_btns = QHBoxLayout()
        self.cp_continue_btn = QPushButton("✓ 确认并继续")
        self.cp_continue_btn.setObjectName("PrimaryBtn")
        self.cp_continue_btn.clicked.connect(self._confirm_checkpoint)
        cp_btns.addWidget(self.cp_continue_btn)
        self.cp_edit_btn = QPushButton("📝 打开编辑器编辑")
        self.cp_edit_btn.clicked.connect(self._open_editor)
        cp_btns.addWidget(self.cp_edit_btn)
        self.cp_retry_btn = QPushButton("重试本阶段")
        self.cp_retry_btn.clicked.connect(self._retry_stage)
        cp_btns.addWidget(self.cp_retry_btn)
        cp_btns.addStretch()
        cp_panel.addLayout(cp_btns)
        self.checkpoint_box.hide()
        splitter.addWidget(self.checkpoint_box)

        # 日志
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("运行日志...")
        splitter.addWidget(self.log_view)

        splitter.setSizes([200, 140, 140])
        root.addWidget(splitter, 1)

        # 底部控制
        ctrl = QHBoxLayout()
        self.pause_btn = QPushButton("⏸ 暂停")
        self.pause_btn.setFixedHeight(32)
        self.pause_btn.clicked.connect(self._toggle_pause)
        ctrl.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton("⏹ 终止")
        self.cancel_btn.setFixedHeight(32)
        self.cancel_btn.clicked.connect(self._cancel_task)
        ctrl.addWidget(self.cancel_btn)

        ctrl.addStretch()

        # 终止/失败后出现：从断点继续跑（不新建项目、不清已完成阶段）
        self.resume_btn = QPushButton("▶ 继续生成（断点续跑）")
        self.resume_btn.setFixedHeight(32)
        self.resume_btn.hide()
        self.resume_btn.clicked.connect(self._request_resume)
        ctrl.addWidget(self.resume_btn)

        self.close_btn = QPushButton("关闭")
        self.close_btn.setFixedHeight(32)
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        ctrl.addWidget(self.close_btn)
        root.addLayout(ctrl)

        self._pending_logs = []

    # ---- 信号处理 ----
    def on_progress(self, ep, stage, status, msg):
        # 阶段级别提示（逐类模式的 category_start/category_done）：
        # ep 为 None，不绑定具体集，直接作为阶段横幅写入日志与标题
        if ep is None:
            self._append_log(f"==== {msg} ====")
            if status in ("category_start", "category_done"):
                self.status_label.setText(msg)
            return
        if stage is None or stage == "":
            self._append_log(f"—— 第 {ep} 集 {msg} ——")
            return
        key = f"{ep}|{stage}"
        item = self._tree_items.get(key)
        if item is None:
            item = QTreeWidgetItem([str(ep), STAGE_LABELS.get(stage, stage), "", ""])
            self.stage_tree.addTopLevelItem(item)
            self._tree_items[key] = item
        text = _STATUS_TEXT.get(status, status)
        color = _status_color().get(status, "" + _theme.color("text") + "")
        item.setText(2, text)
        item.setText(3, msg)
        item.setForeground(2, QColor(color))
        if status in ("running", "checkpoint"):
            self.stage_tree.scrollToItem(item)
        # 每条 progress 也写入日志；占位行（待执行）只在表里展示，不刷日志
        if status != "pending":
            self._append_log(f"[{ep}] {STAGE_LABELS.get(stage, stage)} → {text}: {msg}")

    def on_checkpoint(self, ep, stage, artifacts):
        self.checkpoint_box.show()
        self.cp_edit_btn.show()
        label = STAGE_LABELS.get(stage, stage)
        self.checkpoint_info.setText(
            f"第 {ep} 集【{label}】已完成，进入检查点。\n"
            "操作说明：\n"
            "  • 直接点「✓ 确认并继续」流水线将执行下一阶段\n"
            "  • 点「📝 打开编辑器编辑」可切到对应页面查看/修改产出，编辑完回到此弹窗点「确认并继续」\n"
            "  • 点「重试本阶段」将重新调用 LLM 生成")
        self.checkpoint_preview.setPlainText(self._preview_text(stage, artifacts))
        self._preview_media(stage, artifacts)
        self._checkpoint_stage = stage
        self.status_label.setText(f"⏸ 检查点：{label}")
        self._append_log(f"[检查点] 第 {ep} 集 {label}，等待确认")

    def on_error(self, ep, stage, message):
        self.checkpoint_box.show()
        self.cp_edit_btn.show()
        label = STAGE_LABELS.get(stage, stage)
        self.checkpoint_info.setText(f"第 {ep} 集【{label}】执行失败：\n{message}\n\n可「重试本阶段」或「终止」。")
        self.checkpoint_preview.setPlainText("")
        self._clear_media_preview()
        self._checkpoint_stage = stage
        self.status_label.setText(f"❌ 失败：{label}")
        self._append_log(f"[失败] 第 {ep} 集 {label}: {message}")

    def on_finished(self, result, run_thread=None):
        self._finished = True
        self._log_timer.stop()
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.checkpoint_box.hide()
        self._clear_media_preview()
        self.close_btn.setEnabled(True)

        if result.get("cancelled"):
            self.status_label.setText("已终止")
            self.title_label.setText("🚀 一键成片已终止")
            self._append_log("任务已终止（已完成的阶段已保存，可点「继续生成」断点续跑）")
            self._show_resume_btn("▶ 继续生成（断点续跑）")
        elif result.get("success"):
            outs = result.get("final_outputs", [])
            self.status_label.setText("全部完成！")
            self.title_label.setText("✅ 一键成片完成！")
            self._append_log(f"任务完成，成片 {len(outs)} 个:")
            for p in outs:
                self._append_log(f"  {p}")
            # 刷新主窗口项目列表，确保新项目可见
            if self._main_window:
                self._refresh_main_window()
        else:
            errs = result.get("errors", [])
            self.status_label.setText("任务失败")
            self.title_label.setText("❌ 一键成片失败")
            self._append_log("任务失败: " + "; ".join(errs))
            self._append_log("已完成的阶段已保存，可点「继续生成」从失败处断点续跑")
            self._show_resume_btn("▶ 继续生成（从失败处重试）")

    def _show_resume_btn(self, text):
        self.resume_btn.setText(text)
        self.resume_btn.show()
        self.resume_btn.setEnabled(True)

    def _request_resume(self):
        """关闭弹窗并通知宿主窗口：用原项目/原参数断点续跑。"""
        self._resume_pending = True
        self.accept()

    # ---- 控制 ----
    def _toggle_pause(self):
        if not (self._thread_ref and self._thread_ref.controller):
            return
        if self._pause_toggled:
            self._thread_ref.controller.resume()
            self.pause_btn.setText("⏸ 暂停")
            self._pause_toggled = False
            self.status_label.setText("运行中...")
        else:
            self._thread_ref.controller.pause()
            self.pause_btn.setText("▶ 继续")
            self._pause_toggled = True
            self.status_label.setText("将在当前阶段结束后暂停")

    def _cancel_task(self):
        if self._thread_ref and self._thread_ref.controller:
            self._thread_ref.controller.cancel()
            try:
                self._append_log("已发送终止：正在中断当前 LLM/视频请求（秒级生效）...")
            except Exception:
                pass
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("正在终止...")

    def _confirm_checkpoint(self):
        """确认继续：恢复模态 + 恢复流水线。"""
        self.setModal(True)
        self.checkpoint_box.hide()
        self._clear_media_preview()
        if self._thread_ref and self._thread_ref.controller:
            self._thread_ref.controller.resume()

    def _retry_stage(self):
        self.setModal(True)
        self.checkpoint_box.hide()
        self._clear_media_preview()
        if self._thread_ref and self._thread_ref.controller:
            self._thread_ref.controller.resume(retry=True)

    def _open_editor(self):
        """打开编辑器：临时解除模态，允许用户操作主窗口编辑产出。"""
        stage = getattr(self, "_checkpoint_stage", None)
        idx = EDITOR_JUMP.get(stage)
        if idx is None or self._main_window is None:
            QMessageBox.information(self, "提示", "该阶段暂无对应编辑器，可直接确认继续。")
            return
        # 临时解除模态，让用户能操作主窗口
        self.setModal(False)
        self.status_label.setText("📝 编辑模式：编辑完后回到此弹窗点「确认并继续」")
        # 刷新项目数据再跳转
        self._refresh_main_window()
        if hasattr(self._main_window, "goto_tab"):
            self._main_window.goto_tab(idx)
        # 把弹窗移到非聚焦状态但不隐藏
        self.raise_()
        self.activateWindow()

    # ---- 辅助 ----
    def _append_log(self, text):
        self._pending_logs.append(text)

    def _flush_log(self):
        if not self._pending_logs:
            return
        for line in self._pending_logs:
            self.log_view.appendPlainText(line)
        self._pending_logs.clear()
        # 自动滚到底
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _preview_text(self, stage, artifacts):
        try:
            if stage == "script" and artifacts:
                with open(artifacts[0], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                shots = data.get("shots") or data.get("scenes") or []
                lines = [f"标题: {data.get('title', '?')}", f"镜头数: {len(shots)}", ""]
                for s in shots[:5]:
                    lines.append(f"[{s.get('shot_id', '')}] {s.get('scene_location', '')} | "
                                 f"{(s.get('dialogue') or '')[:60]}")
                lines.append("\n(完整内容请在剧本页查看/编辑)")
                # 分镜已并入本阶段：第二个产物是分镜文件
                if len(artifacts) > 1 and os.path.isfile(artifacts[1]):
                    try:
                        with open(artifacts[1], 'r', encoding='utf-8') as f:
                            sb = json.load(f)
                        panels = sb.get("panels", [])
                        lines.append(f"分镜数: {len(panels)}")
                    except Exception:
                        pass
                return "\n".join(lines)
            return "\n".join(str(a) for a in artifacts) if artifacts else "(无产物)"
        except Exception as e:
            return f"(预览失败: {e})"

    # ---- 媒体预览 ----
    def _preview_media(self, stage, artifacts):
        """根据检查点阶段显示对应媒体预览。"""
        self._clear_media_preview()
        if not artifacts:
            return

        try:
            if stage == "clips":
                self._show_video_thumbnails(artifacts)
            elif stage == "compose":
                self._show_video_thumbnails(artifacts)
        except Exception as e:
            print(f"_preview_media error: {e}")

    def _show_video_thumbnails(self, artifacts):
        """clips/compose 阶段：显示视频帧缩略图；clips 阶段可点击试播单分镜。"""
        video_files = [a for a in artifacts if isinstance(a, str) and a.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')) and os.path.exists(a)]
        if not video_files:
            return
        self.media_preview_frame.show()
        self.media_preview_label.setText(f"视频预览（{len(video_files)} 个，点击缩略图试播）")
        for vpath in video_files[:6]:
            lbl = _ClickableThumb(vpath)
            lbl.setFixedSize(80, 80)
            # 尝试用 ffmpeg 截取第一帧
            thumb = self._extract_video_frame(vpath)
            if thumb:
                lbl.setPixmap(thumb)
            else:
                lbl.setText("▶")
                lbl.setStyleSheet("color: " + _theme.color("warning") + "; font-size: 20px; background-color: " + _theme.color("panel") + "; border-radius: 4px;")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # 点击缩略图弹出单分镜试播（clips/compose 都支持）
            lbl.clicked.connect(lambda checked, p=vpath: self._play_single_clip(p))
            self.thumb_layout.insertWidget(self.thumb_layout.count() - 1, lbl)

    def _play_single_clip(self, video_path):
        """弹窗试播单个分镜 MP4，免等全片合成。"""
        if not video_path or not os.path.isfile(video_path):
            return
        dlg = ClipPreviewDialog(video_path, self)
        dlg.exec()

    def _extract_video_frame(self, video_path):
        """用 ffmpeg 提取视频第一帧为 QPixmap。"""
        try:
            import tempfile
            import subprocess
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, mode='w')
            tmp_path = tmp.name
            tmp.close()
            # 尝试找到 ffmpeg 路径
            ffmpeg_cmd = "ffmpeg"
            try:
                import imageio
                ffmpeg_cmd = imageio.plugins.ffmpeg.get_exe()
            except Exception:
                pass
            result = subprocess.run(
                [ffmpeg_cmd, "-y", "-i", video_path, "-frames:v", "1", "-vf", "scale=80:80", tmp_path],
                capture_output=True, timeout=10
            )
            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                pix = QPixmap(tmp_path)
                os.unlink(tmp_path)
                return pix
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception as e:
            print(f"_extract_video_frame error: {e}")
        return None

    def _clear_media_preview(self):
        """清理媒体预览区：清空缩略图。"""
        # 清空缩略图
        while self.thumb_layout.count() > 1:
            item = self.thumb_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.media_preview_frame.hide()
        self.thumb_scroll.show()

    def set_thread_ref(self, thread, main_window=None):
        self._thread_ref = thread
        self._main_window = main_window

    def _refresh_main_window(self):
        """刷新主窗口的项目列表和剧本列表，确保新产出可见。"""
        if not self._main_window:
            return
        try:
            # 刷新项目列表
            pw = getattr(self._main_window, "project_window", None)
            if pw and hasattr(pw, "refresh_list"):
                pw.refresh_list()
            # 刷新剧本列表
            sw = getattr(self._main_window, "script_window", None)
            if sw and hasattr(sw, "load_episodes"):
                sw.load_episodes()
            elif sw and hasattr(sw, "refresh_episodes"):
                sw.refresh_episodes()
        except Exception as e:
            print(f"refresh_main_window: {e}")

    def closeEvent(self, event):
        if not self._finished:
            # 最小化而不是隐藏——hide() 会让模态弹窗不可见但仍阻塞主窗口
            event.ignore()
            self.showMinimized()
            return
        # 完成后刷新一次主窗口
        self._refresh_main_window()
        super().closeEvent(event)


# ======================================================================
#  首页（精简版）
# ======================================================================
class AutoRunWindow(QWidget):
    def __init__(self, project_dir, projects_dir=None):
        super().__init__()
        self.project_dir = project_dir
        self.projects_dir = projects_dir
        self.main_window = None
        self.config_manager = ConfigManager()
        self.run_thread = None
        self.state = None
        self._dialog = None
        self._current_style = "都市"
        # 创作类型：original=原创短剧 / adaptation=改编短剧（决定显示哪套选项卡内容）
        self._current_type = "original"
        self.init_ui()
        self._load_recent_projects()

    # ---------- 布局 ----------
    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)
        root.addStretch(1)

        # ===== Hero 创作卡 =====
        hero = QFrame()
        hero.setObjectName("HeroCard")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(10)

        hero_title = QLabel("🎬  开始创作你的短剧")
        hero_title.setObjectName("HeroTitle")
        hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(hero_title)

        hero_sub = QLabel("输入主题，一键生成剧本、分镜与成片")
        hero_sub.setObjectName("HeroSub")
        hero_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(hero_sub)

        # ===== 创作类型选项卡：原创短剧 / 改编短剧 =====
        tab_row = QHBoxLayout()
        tab_row.setSpacing(10)
        self._type_group = QButtonGroup(self)
        self._type_group.setExclusive(True)
        self.tab_original_btn = QPushButton("🎬 原创短剧")
        self.tab_original_btn.setObjectName("HeroTab")
        self.tab_original_btn.setCheckable(True)
        self.tab_original_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab_original_btn.setMinimumHeight(40)
        self.tab_original_btn.clicked.connect(lambda: self._on_type_tab("original"))
        self.tab_adapt_btn = QPushButton("📖 改编短剧")
        self.tab_adapt_btn.setObjectName("HeroTab")
        self.tab_adapt_btn.setCheckable(True)
        self.tab_adapt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab_adapt_btn.setMinimumHeight(40)
        self.tab_adapt_btn.clicked.connect(lambda: self._on_type_tab("adaptation"))
        self._type_group.addButton(self.tab_original_btn)
        self._type_group.addButton(self.tab_adapt_btn)
        self.tab_original_btn.setChecked(True)
        tab_row.addStretch()
        tab_row.addWidget(self.tab_original_btn)
        tab_row.addWidget(self.tab_adapt_btn)
        tab_row.addStretch()
        hl.addLayout(tab_row)

        # 选项卡内容：切换后显示不同的创作选项
        self.hero_stack = QStackedWidget()

        # ---------- 选项卡 1：原创短剧 ----------
        orig_page = QWidget()
        ol = QVBoxLayout(orig_page)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(10)

        # 风格 chips
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        chip_row.addStretch()
        for s in ["都市", "古风", "科幻", "悬疑", "喜剧", "情感"]:
            chip = QPushButton(s)
            chip.setObjectName("StyleChip")
            chip.setCheckable(True)
            chip.clicked.connect(lambda checked, st=s: self._on_style_chip(st))
            self._chip_group.addButton(chip)
            chip_row.addWidget(chip)
        # 模板按钮：从预置模板快速填充主题
        tpl_btn = QPushButton("📋 模板")
        tpl_btn.setObjectName("StyleChip")
        tpl_btn.setToolTip("从预置剧本模板（逆袭重生/战神赘婿/大女主复仇等15个）快速填充创作主题")
        tpl_btn.clicked.connect(self._pick_template)
        chip_row.addWidget(tpl_btn)
        chip_row.addStretch()
        ol.insertLayout(0, chip_row)

        # 主题输入行
        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.hero_topic = QLineEdit()
        self.hero_topic.setObjectName("HeroInput")
        self.hero_topic.setPlaceholderText("输入短剧主题，例如：外卖骑手意外获得读心术")
        self.hero_topic.returnPressed.connect(self._on_hero_generate)
        input_row.addWidget(self.hero_topic, 1)
        ol.addLayout(input_row)

        # 操作按钮行（居中）
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addStretch()
        go_btn = QPushButton("🚀 一键成片")
        go_btn.setObjectName("HeroGo")
        go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        go_btn.clicked.connect(self._on_hero_generate)
        action_row.addWidget(go_btn)
        enqueue_btn = QPushButton("＋ 加入队列")
        enqueue_btn.setObjectName("HeroEnqueue")
        enqueue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        enqueue_btn.clicked.connect(self._enqueue_current)
        action_row.addWidget(enqueue_btn)
        action_row.addStretch()
        ol.addLayout(action_row)
        self.hero_stack.addWidget(orig_page)

        # ---------- 选项卡 2：改编短剧 ----------
        adapt_page = QWidget()
        al = QVBoxLayout(adapt_page)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(10)

        # 原作素材输入 + 导入按钮
        src_row = QHBoxLayout()
        src_row.setSpacing(8)
        src_label = QLabel("原作素材:")
        src_label.setObjectName("HeroFieldLabel")
        src_row.addWidget(src_label)
        self.adapt_source = QPlainTextEdit()
        self.adapt_source.setObjectName("HeroSource")
        self.adapt_source.setPlaceholderText("粘贴小说/原著内容，或输入原作梗概，例如：《XXX》第 1 章 ...")
        self.adapt_source.setMaximumHeight(80)
        src_row.addWidget(self.adapt_source, 1)
        import_btn = QPushButton("导入")
        import_btn.setObjectName("HeroImport")
        import_btn.clicked.connect(self._import_script_or_source)
        src_row.addWidget(import_btn)
        al.addLayout(src_row)

        # 改编幅度、目标平台等参数已移至「一键成片」启动弹窗的第二步（ScriptParamsDialog）

        # 操作行（居中）
        adapt_act_row = QHBoxLayout()
        adapt_act_row.setSpacing(10)
        adapt_act_row.addStretch()
        adapt_go_btn = QPushButton("🎭 改编成片")
        adapt_go_btn.setObjectName("HeroGo")
        adapt_go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        adapt_go_btn.clicked.connect(self._on_hero_generate)
        adapt_act_row.addWidget(adapt_go_btn)
        adapt_enqueue_btn = QPushButton("＋ 加入队列")
        adapt_enqueue_btn.setObjectName("HeroEnqueue")
        adapt_enqueue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        adapt_enqueue_btn.clicked.connect(self._enqueue_current)
        adapt_act_row.addWidget(adapt_enqueue_btn)
        adapt_act_row.addStretch()
        al.addLayout(adapt_act_row)
        self.hero_stack.addWidget(adapt_page)

        hl.addWidget(self.hero_stack)

        # 通用参数（集数/比例/分辨率/篇幅/语言/画面风格/导出/转场）已移至
        # 「一键成片」启动弹窗的第二步（ScriptParamsDialog），首页不再保留
        root.addWidget(hero)
        root.addStretch(2)

        # ===== 最近项目 =====
        recent_group = QGroupBox("最近项目")
        rl = QVBoxLayout(recent_group)
        rl.setContentsMargins(10, 16, 10, 10)
        self.recent_container = QHBoxLayout()
        self.recent_container.setSpacing(12)
        rl.addLayout(self.recent_container)
        self.recent_empty = QLabel("暂无项目，输入主题开始创作")
        self.recent_empty.setProperty("dim", True)
        rl.addWidget(self.recent_empty)
        recent_group.setMaximumHeight(120)
        root.addWidget(recent_group)

        # 兼容旧代码引用
        self.style_combo = None
        self.topic_edit = None
        self.checkpoint_checks = {}
        self.start_btn = None
        self.pause_btn = None
        self.cancel_btn = None
        self.status_label = QLabel("")
        self.stage_tree = None
        self.log_view = None
        self.checkpoint_box = None
        self._pause_toggled = False
        self._tree_items = {}
        self._checkpoint_stage = None

        # ===== 批量队列 =====
        queue_group = QGroupBox("批量队列（按顺序串行处理多个主题）")
        ql = QVBoxLayout(queue_group)
        ql.setContentsMargins(10, 16, 10, 10)
        self.queue_list = QListWidget()
        self.queue_list.setMaximumHeight(120)
        self.queue_list.setAlternatingRowColors(True)
        ql.addWidget(self.queue_list)
        qbtn_row = QHBoxLayout()
        self.btn_run_queue = QPushButton("▶ 全部开始")
        self.btn_run_queue.setObjectName("HeroGo")
        self.btn_run_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_queue.clicked.connect(self._on_batch_start)
        self.btn_remove_queue = QPushButton("移除选中")
        self.btn_remove_queue.clicked.connect(self._dequeue_selected)
        self.btn_clear_queue = QPushButton("清空")
        self.btn_clear_queue.clicked.connect(self._clear_queue)
        qbtn_row.addWidget(self.btn_run_queue)
        qbtn_row.addWidget(self.btn_remove_queue)
        qbtn_row.addWidget(self.btn_clear_queue)
        qbtn_row.addStretch()
        ql.addLayout(qbtn_row)
        queue_group.setMaximumHeight(180)
        root.addWidget(queue_group)
        # 队列数据 + 游标
        self._batch_queue = []
        self._batch_cursor = 0

        # 首页所有按钮统一手型光标，明确可点击
        for btn in self.findChildren(QPushButton):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # 用样式化 QListView 替换下拉框原生 view，避免 Windows 原生渲染的文字阴影
        list_view_style = """
            QListView {
                background: """ + _theme.color("panel") + """;
                border: 1px solid """ + _theme.color("border") + """;
                border-radius: 8px;
                outline: 0;
                padding: 4px;
            }
            QListView::item {
                color: """ + _theme.color("text") + """;
                padding: 6px 10px;
                border-radius: 4px;
            }
            QListView::item:hover {
                background: """ + _theme.color("hover") + """;
            }
            QListView::item:selected {
                background: """ + _theme.color("selected") + """;
                color: """ + _theme.color("text") + """;
            }
        """
        for combo in self.findChildren(QComboBox):
            view = QListView()
            view.setStyleSheet(list_view_style)
            combo.setView(view)

        # 统一参数控件样式（与检查点按钮一致：白底、深色文字、圆角边框）
        for ctrl in self.findChildren(QSpinBox) + self.findChildren(QComboBox):
            ctrl.setProperty("heroParam", True)

    # ---------- Hero 入口 ----------
    def _on_style_chip(self, style):
        self._current_style = style

    def _on_type_tab(self, type_key):
        """切换「原创短剧 / 改编短剧」选项卡，显示不同的创作选项。"""
        self._current_type = type_key
        self.hero_stack.setCurrentIndex(0 if type_key == "original" else 1)

    def _import_topic(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入主题文本", "", "Text Files (*.txt *.md);;All Files (*)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.hero_topic.setText(f.read().strip()[:500])
            except Exception as e:
                QMessageBox.warning(self, "提示", f"读取失败: {e}")

    def _import_source(self):
        """改编页：从文本文件导入原作素材。"""
        path, _ = QFileDialog.getOpenFileName(self, "导入原文", "", "Text Files (*.txt *.md);;All Files (*)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.adapt_source.setPlainText(f.read())
            except Exception as e:
                QMessageBox.warning(self, "提示", f"读取失败: {e}")

    def _pick_template(self):
        """从模板库选择模板，把模板 prompt 填入主题输入框。"""
        try:
            from core.template.template_library import TemplateLibrary
            from ui.script_window import TemplatePickerDialog
        except ImportError as e:
            QMessageBox.warning(self, "提示", f"模板模块不可用: {e}")
            return
        library = TemplateLibrary()
        templates = library.list_templates()
        if not templates:
            QMessageBox.information(self, "提示", "未找到可用模板。")
            return
        dlg = TemplatePickerDialog(templates, self)
        if dlg.exec() and dlg.selected_template:
            topic = dlg.topic_text or self.hero_topic.text().strip()
            prompt = library.build_prompt(dlg.selected_template, topic)
            self.hero_topic.setText(prompt[:500])

    def _browse_script(self):
        """改编页：选择已有剧本 JSON 文件（选择后直接成片）。"""
        path, _ = QFileDialog.getOpenFileName(self, "选择剧本 JSON 文件", "", "剧本 JSON (*.json)")
        if path:
            self.adapt_script_edit.setText(path)

    def _import_script_or_source(self):
        """导入按钮：读取文本文件内容并显示在原作素材输入框中。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入文件", "",
            "文本文件 (*.txt *.md);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.adapt_source.setPlainText(f.read())
        except Exception as e:
            QMessageBox.warning(self, "提示", f"读取失败: {e}")

    def _short_title(self, text):
        """从长篇原文提取一个短标题（首行/前 20 字），用于项目名与主题。"""
        first_line = (text or "").strip().splitlines()[0] if text else ""
        title = re.sub(r'[\\/:*?"<>|\n\r]', '_', first_line or "长篇改编").strip()
        return (title[:20] or "长篇改编")

    def _on_hero_generate(self):
        # PyQt6 中槽函数抛出未捕获异常会直接 abort 整个应用，这里兜底：
        # 打印堆栈并弹窗提示，保证界面不会退出。
        try:
            item = self._collect_hero_item()
            if not item:
                return
            # 单次运行：走创建项目 + 线程 + 模态弹窗
            self._run_queue_item(item, is_batch=False)
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"改编成片启动失败:\n{e}")

    def _collect_hero_item(self):
        """按当前选项卡收集一个队列项参数。失败返回 None。"""
        if not self.projects_dir:
            QMessageBox.warning(self, "提示", "未配置项目目录，无法创建项目。")
            return None

        if self._current_type == "adaptation":
            source = self.adapt_source.toPlainText().strip()
            script_path = None
            if not source and not script_path:
                QMessageBox.information(self, "提示", "请粘贴原作素材，或选择已有剧本文件。")
                return None
            # 长篇原作：topic 用短标题，全文单独走 source_text，避免污染项目主题
            try:
                from ui.project_window import is_long_source_text
                long_mode = is_long_source_text(source)
            except Exception:
                long_mode = len(source) >= 20000
            if long_mode:
                topic = self._short_title(source)
                source_text = source
            else:
                topic = source or os.path.splitext(os.path.basename(script_path))[0]
                source_text = ""
            return {
                "topic": topic,
                "source_text": source_text,
                "style": self._current_style or "都市",
                "use_video_gen": True,
                "language": "zh",
                "genre": self._current_style or "都市",
                "project_type": "adaptation",
                "script_path": script_path,
            }

        # 原创短剧
        topic = self.hero_topic.text().strip()
        if not topic:
            QMessageBox.information(self, "提示", "请先输入短剧主题。")
            return None
        return {
            "topic": topic,
            "style": self._current_style or "都市",
            "use_video_gen": True,
            "language": "zh",
            "genre": self._current_style or "都市",
            "project_type": "original",
        }

    # ---------- 批量队列 ----------
    def _enqueue_current(self):
        """把当前选项卡的输入作为一个队列项加入批量队列（含生成配置）。"""
        try:
            item = self._collect_hero_item()
            if not item:
                return
            # 入队前弹出两步配置弹窗，将配置存入队列项
            mode, checkpoints, script_params = self._ask_run_config(item, submit_text="加入队列")
            if mode is None:
                return  # 用户取消，不入队
            item["generate_mode"] = mode
            item["checkpoints"] = list(checkpoints)
            item["script_params"] = dict(script_params)
            self._batch_queue.append(item)
            self._refresh_queue_list()
            # 入队后清空当前选项卡输入，方便继续添加下一个
            if self._current_type == "adaptation":
                self.adapt_source.clear()
            else:
                self.hero_topic.clear()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"加入队列失败:\n{e}")

    def _refresh_queue_list(self):
        self.queue_list.clear()
        for i, it in enumerate(self._batch_queue, start=1):
            tag = "[改编]" if it.get("project_type") == "adaptation" else "[原创]"
            sp = it.get("script_params", {})
            ep = sp.get("episode_count", "?")
            mode_label = GENERATE_MODE_LABELS.get(it.get("generate_mode"), "")
            label = f"{i}. {tag} {it['topic']}  [{it['style']}/{ep}集/{mode_label}]"
            lw = QListWidgetItem(label)
            self.queue_list.addItem(lw)
        # 选中最后加入的项，便于立即移除
        if self.queue_list.count() > 0:
            self.queue_list.setCurrentRow(self.queue_list.count() - 1)

    def _dequeue_selected(self):
        row = self.queue_list.currentRow()
        if 0 <= row < len(self._batch_queue):
            del self._batch_queue[row]
            self._refresh_queue_list()
            if row < self.queue_list.count():
                self.queue_list.setCurrentRow(row)

    def _clear_queue(self):
        self._batch_queue.clear()
        self._refresh_queue_list()

    def _on_batch_start(self):
        """按顺序串行处理队列中的所有主题（各队列项已自带生成配置，直接运行）。"""
        try:
            if not self._batch_queue:
                QMessageBox.information(self, "提示", "队列为空，请先加入主题。")
                return
            if not self.projects_dir:
                QMessageBox.warning(self, "提示", "未配置项目目录。")
                return
            self._batch_cursor = 0
            # 清除上一次运行残留的线程引用：旧 controller 可能仍带 cancelled 标记，
            # 不清掉会让队列首项还没启动就被误判为"用户已取消"而直接停止。
            self.run_thread = None
            self._run_next_in_queue()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"批量启动失败:\n{e}")

    def _ask_run_config(self, item, submit_text="开始生成 →"):
        """两步弹窗：①生成模式+检查点 ②短剧参数。

        submit_text 控制第二步弹窗的确认按钮文字（加入队列 / 开始生成）。
        返回 (generate_mode, checkpoints, script_params)；用户任一步取消返回 (None, None, None)。
        """
        # 第一步：生成模式 + 检查点
        dlg1 = GenerateModeDialog(self)
        if dlg1.exec() != QDialog.DialogCode.Accepted:
            return None, None, None
        mode, checkpoints = dlg1.get_result()

        # 第二步：短剧参数
        project_type = item.get("project_type", "original")
        dlg2 = ScriptParamsDialog(self, project_type=project_type, submit_text=submit_text)
        if dlg2.exec() != QDialog.DialogCode.Accepted:
            return None, None, None
        script_params = dlg2.get_params()

        return mode, checkpoints, script_params

    def _run_next_in_queue(self, from_pipeline=False):
        """运行队列游标指向的下一项；到末尾则结束。

        from_pipeline=True 表示由「上一项流水线结束」触发，此时才检查用户是否
        在进度窗里点了终止；首次点「全部开始」不检查，避免被上一轮残留的
        controller 取消标记误判。
        """
        if from_pipeline:
            ctrl = getattr(getattr(self, "run_thread", None), "controller", None)
            if ctrl is not None and getattr(ctrl, "cancelled", False):
                # 用户终止后保留队列内容，方便直接再点「全部开始」重试
                QMessageBox.information(
                    self, "批量已取消",
                    f"队列已停止，已完成 {max(0, self._batch_cursor - 1)}/{len(self._batch_queue)} 项。\n"
                    f"队列内容已保留，可再次点击「全部开始」重试。")
                return
        if self._batch_cursor >= len(self._batch_queue):
            QMessageBox.information(self, "批量完成", f"队列全部完成，共 {len(self._batch_queue)} 个项目。")
            self._batch_queue.clear()
            self._refresh_queue_list()
            return
        item = self._batch_queue[self._batch_cursor]
        self._batch_cursor += 1
        self._run_queue_item(item, is_batch=True)

    def _run_queue_item(self, item, is_batch=False):
        """创建项目并启动 AutoRunThread；模态弹窗结束后若为批量模式则继续下一项。"""
        try:
            # 队列项自带配置（加入队列时已弹窗确认）；单次一键成片则在此弹窗
            generate_mode = item.get("generate_mode")
            checkpoints = item.get("checkpoints", [])
            script_params = item.get("script_params")
            if generate_mode is None or script_params is None:
                generate_mode, checkpoints, script_params = self._ask_run_config(item)
                if generate_mode is None:
                    # 用户取消弹窗：批量模式清空队列并停止，单次模式直接返回
                    if is_batch:
                        self._batch_queue.clear()
                        self._refresh_queue_list()
                    return

            style = item["style"]
            language = script_params.get("language", "zh")
            topic = item["topic"]
            source_text = item.get("source_text", "") or ""
            ratio = script_params.get("ratio", "16:9")
            resolution = script_params.get("resolution", "1080p")
            visual_style = script_params.get("visual_style") or style

            # 创建项目（同名冲突时自动追加序号，避免批量队列重复运行时报错）
            try:
                manager = ProjectManager(self.projects_dir)
                base_name = topic[:20].replace('/', '_').replace('\\', '_')
                name = base_name
                project_path = None
                for _attempt in range(100):
                    try:
                        project_path = manager.create_project(name, {
                            "title": topic,
                            "type": item.get("project_type", "original"),
                            "language": language,
                            "theme": topic,
                            "genre": item.get("genre") or style,
                            "style": style,
                            "visual_style": visual_style,
                            "ratio": ratio,
                            "resolution": resolution,
                            "total_episodes": script_params.get("episode_count", 1),
                            "words_per_episode": 300,
                            "main_characters": "",
                        })
                        break
                    except ValueError:
                        # 项目已存在，追加序号重试
                        name = f"{base_name}_{_attempt + 2}"
                if project_path is None:
                    raise RuntimeError(f"无法创建项目 '{base_name}'：已存在太多同名项目。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"创建项目失败: {e}")
                return

            params = AutoRunParams(
                topic=topic,
                style=style,
                episode_count=script_params.get("episode_count", 1),
                duration=script_params.get("duration", DURATION_OPTIONS[0]),
                use_video_gen=item["use_video_gen"],
                checkpoints=checkpoints,
                existing_script_path=item.get("script_path"),
                instructions=item.get("instructions", ""),
                language=language,
                export_preset=script_params.get("export_preset", "custom"),
                blend_mode=script_params.get("blend_mode", "crossfade"),
                transition_duration=script_params.get("transition_duration", 0) / 10.0,
                aspect_ratio=ratio,
                resolution=script_params.get("resolution", "1080p"),
                source_text=source_text,
                fidelity=script_params.get("fidelity", ""),
                generate_mode=generate_mode,
            )

            # 保存本次运行信息，供「继续生成」断点续跑复用（不新建项目、不清状态）
            self._last_run = {"project_path": project_path, "params": params, "is_batch": is_batch}
            self._start_pipeline(project_path, params, is_batch=is_batch, reset_state=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"启动失败:\n{e}")

    def _resume_last_run(self):
        """终止/失败后点「继续生成」：用原项目和原参数断点续跑。"""
        info = getattr(self, "_last_run", None)
        if not info:
            QMessageBox.information(self, "提示", "没有可续跑的任务信息")
            return
        self._append_log("断点续跑：复用原项目，已完成阶段将自动跳过")
        self._start_pipeline(info["project_path"], info["params"],
                             is_batch=False, reset_state=False)

    def _start_pipeline(self, project_path, params, is_batch=False, reset_state=True):
        """启动一条流水线并弹出模态进度窗。

        reset_state=True（新建项目）清空流水线状态从头跑；
        reset_state=False（继续生成）保留 PipelineState，已完成阶段自动跳过。
        """
        # 加载项目到主窗口
        if self.main_window and hasattr(self.main_window, "on_project_loaded"):
            self.main_window.on_project_loaded(project_path)
        else:
            self.set_project_dir(project_path)

        # 刷新项目列表
        if self.main_window:
            pw = getattr(self.main_window, "project_window", None)
            if pw and hasattr(pw, "refresh_list"):
                pw.refresh_list()
        self._load_recent_projects()

        # 状态：新建清零 / 续跑保留（否则无法跳过已完成阶段）
        try:
            self.state = PipelineState(project_path)
            if reset_state:
                self.state.reset_all()
        except Exception:
            pass

        # 重新加载配置（确保设置页修改生效）
        self.config_manager = ConfigManager()

        # 启动线程
        self.run_thread = AutoRunThread(project_path, params, self.config_manager)

        # 创建进度弹窗（模态）
        self._dialog = AutoRunProgressDialog(self)
        self._dialog.set_thread_ref(self.run_thread, self.main_window)

        # 连接信号
        self.run_thread.progress_changed.connect(self._dialog.on_progress)
        self.run_thread.checkpoint_reached.connect(self._dialog.on_checkpoint)
        self.run_thread.error_reached.connect(self._dialog.on_error)
        self.run_thread.pipeline_finished.connect(
            lambda result: self._dialog.on_finished(result, self.run_thread))
        self.run_thread.log_line.connect(self._dialog._append_log)

        # 启动
        self.run_thread.start()
        # 模态弹窗结束后：批量模式自动继续下一项。
        # 用 QTimer.singleShot(0) 延迟到当前弹窗完全关闭后再启动下一个模态，
        # 避免在 finished 回调里嵌套 exec() 导致事件循环/模态栈异常。
        if is_batch:
            self._dialog.finished.connect(
                lambda _code: QTimer.singleShot(
                    0,
                    lambda: None if getattr(self._dialog, "_resume_pending", False)
                    else self._run_next_in_queue(from_pipeline=True)))
        self._dialog.exec()
        # 终止/失败后点了「继续生成」→ 关闭弹窗后续跑
        if getattr(self._dialog, "_resume_pending", False):
            QTimer.singleShot(0, self._resume_last_run)

    # ---------- 最近项目 ----------
    def _load_recent_projects(self):
        while self.recent_container.count():
            item = self.recent_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self.projects_dir:
            self.recent_empty.show()
            return
        try:
            manager = ProjectManager(self.projects_dir)
            projects = manager.list_projects()
        except Exception:
            projects = []
        projects.sort(key=lambda p: p.get("last_modified", ""), reverse=True)
        projects = projects[:6]
        if not projects:
            self.recent_empty.show()
            return
        self.recent_empty.hide()
        for p in projects:
            name = p.get("name") or p.get("title") or os.path.basename(p.get("path", ""))
            card = QPushButton(name)
            card.setObjectName("RecentCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet("""
                QPushButton#RecentCard {
                    border-radius: 10px; padding: 12px 16px; text-align: left;
                    font-weight: 600; min-height: 48px;
                }
            """)
            path = p.get("path", "")
            card.clicked.connect(lambda checked, pp=path: self._open_recent(pp))
            self.recent_container.addWidget(card)
        self.recent_container.addStretch()

    def _open_recent(self, project_path):
        if not project_path:
            return
        if self.main_window and hasattr(self.main_window, "on_project_loaded"):
            self.main_window.on_project_loaded(project_path)
        else:
            self.set_project_dir(project_path)
        self.hero_topic.setFocus()

    # ---------- 兼容接口 ----------
    def set_project_dir(self, path):
        self.project_dir = path

    def set_main_window(self, main_window):
        self.main_window = main_window

    def refresh_state_hint(self):
        pass

    def start_new_task(self):
        self._on_hero_generate()

    def toggle_pause(self):
        if self._dialog:
            self._dialog._toggle_pause()

    def cancel_task(self):
        if self._dialog:
            self._dialog._cancel_task()

    def confirm_checkpoint(self):
        if self._dialog:
            self._dialog._confirm_checkpoint()

    def retry_stage(self):
        if self._dialog:
            self._dialog._retry_stage()

    def open_editor_from_checkpoint(self):
        if self._dialog:
            self._dialog._open_editor()

    def on_progress(self, *a):
        if self._dialog:
            self._dialog.on_progress(*a)

    def on_checkpoint(self, *a):
        if self._dialog:
            self._dialog.on_checkpoint(*a)

    def on_error(self, *a):
        if self._dialog:
            self._dialog.on_error(*a)

    def on_finished(self, *a):
        if self._dialog:
            self._dialog.on_finished(*a)

    def append_log(self, text):
        if self._dialog:
            self._dialog._append_log(text)

    def _preview_text(self, stage, artifacts):
        if self._dialog:
            return self._dialog._preview_text(stage, artifacts)
        return ""


class _ClickableThumb(QLabel):
    """可点击的视频缩略图；点击发出 clicked 信号。"""
    clicked = pyqtSignal()

    def __init__(self, video_path, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击试播该分镜")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ClipPreviewDialog(QDialog):
    """单分镜 MP4 试播弹窗：QVideoWidget 播放 + 播放/暂停 + 关闭。"""

    def __init__(self, video_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"分镜试播 - {os.path.basename(video_path)}")
        self.resize(480, 560)
        self.video_path = video_path
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(360, 420)
        layout.addWidget(self.video_widget, 1)

        ctrl_row = QHBoxLayout()
        self.play_btn = QPushButton("⏸ 暂停")
        self.play_btn.clicked.connect(self._toggle_play)
        ctrl_row.addWidget(self.play_btn)
        ctrl_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        ctrl_row.addWidget(close_btn)
        layout.addLayout(ctrl_row)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.audio_output.setVolume(0.9)

    def showEvent(self, event):
        super().showEvent(event)
        # 显示后开始播放
        self.player.setSource(QUrl.fromLocalFile(self.video_path))
        self.player.play()

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("⏸ 暂停")
        else:
            self.play_btn.setText("▶ 播放")

    def closeEvent(self, event):
        try:
            self.player.stop()
        except Exception:
            pass
        super().closeEvent(event)
