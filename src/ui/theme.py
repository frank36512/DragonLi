# -*- coding: utf-8 -*-
"""主题引擎：light / dark 双主题，teal 青绿主色。借鉴 ClipMaker 的 design。"""
from __future__ import annotations
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QPalette

LIGHT = {
    "bg": "#F4F6FA",
    "panel": "#FFFFFF",
    "panel2": "#EEF1F6",
    "border": "#E2E6EF",
    "border_strong": "#CBD3E1",
    "text": "#1F2329",
    "text_sub": "#6B7280",
    "accent": "#14B8A6",
    "accent2": "#0D9488",
    "accent_strong": "#0F766E",
    "accent_text": "#FFFFFF",
    "success": "#22AB67",
    "warning": "#E8A23B",
    "danger": "#E5484D",
    "info": "#14B8A6",
    "hover": "#EEF1F8",
    "selected": "#CCFBF1",
    "nav_hover": "#E9EEF8",
    "nav_active": "#CCFBF1",
    "success_soft": "#E6F6EE",
    "warning_soft": "#FBF0DC",
    "danger_soft": "#FBE7E8",
    "info_soft": "#E0F7F5",
}

DARK = {
    "bg": "#0F172A",
    "panel": "#1E293B",
    "panel2": "#334155",
    "border": "#334155",
    "border_strong": "#475569",
    "text": "#E2E8F0",
    "text_sub": "#94A3B8",
    "accent": "#14B8A6",
    "accent2": "#0D9488",
    "accent_strong": "#5EEAD4",
    "accent_text": "#FFFFFF",
    "success": "#34D399",
    "warning": "#FBBF24",
    "danger": "#F87171",
    "info": "#14B8A6",
    "hover": "#334155",
    "selected": "#134E4A",
    "nav_hover": "#1E293B",
    "nav_active": "#134E4A",
    "success_soft": "rgba(52,211,153,0.16)",
    "warning_soft": "rgba(251,191,36,0.16)",
    "danger_soft": "rgba(248,113,113,0.16)",
    "info_soft": "rgba(20,184,166,0.18)",
}

PALETTES = {"light": LIGHT, "dark": DARK}

# ---------------------------------------------------------------------------
# 皮肤：在 light/dark 基础上叠加不同主题色
# ---------------------------------------------------------------------------
_SKINS: dict[str, dict] = {
    "default": {"accent": "#14B8A6", "accent2": "#0D9488", "accent_strong": "#0F766E"},
    "ocean":   {"accent": "#0EA5E9", "accent2": "#0284C7", "accent_strong": "#0369A1"},
    "sunset":  {"accent": "#F97316", "accent2": "#EA580C", "accent_strong": "#C2410C"},
    "forest":  {"accent": "#22C55E", "accent2": "#16A34A", "accent_strong": "#15803D"},
    "lavender":{"accent": "#A78BFA", "accent2": "#7C3AED", "accent_strong": "#6D28D9"},
    "rose":    {"accent": "#F43F5E", "accent2": "#E11D48", "accent_strong": "#BE123C"},
    "amber":   {"accent": "#F59E0B", "accent2": "#D97706", "accent_strong": "#B45309"},
    "indigo":  {"accent": "#6366F1", "accent2": "#4F46E5", "accent_strong": "#4338CA"},
}

SKIN_NAMES = {
    "default": "默认青绿",
    "ocean": "海洋蓝",
    "sunset": "日落橙",
    "forest": "森林绿",
    "lavender": "薰衣草紫",
    "rose": "玫瑰红",
    "amber": "琥珀金",
    "indigo": "靛蓝",
}


def _apply_skin(base: dict, skin: str) -> dict:
    c = dict(base)
    if skin in _SKINS:
        c.update(_SKINS[skin])
    return c


def _qss(c: dict, radius: int = 10) -> str:
    ac = c["accent"]
    return f"""
    * {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif; }}
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QWidget {{ color: {c['text']}; font-size: 13px; }}

    QFrame#Card, QWidget#Card {{
        background: {c['panel']}; border: 1px solid {c['border']};
        border-radius: {radius}px;
    }}

    /* ---- left sidebar ---- */
    QFrame#SideBar {{
        background: {c['panel']}; border-right: 1px solid {c['border']};
    }}
    QFrame#SideBar2 {{
        background: {c['panel']}; border-right: 1px solid {c['border']};
    }}
    QPushButton#NavBtn {{
        background: transparent; border: none; text-align: left;
        padding: 11px 18px; border-radius: 8px; margin: 2px 8px; font-size: 14px;
    }}
    QPushButton#NavBtn:hover {{ background: {c['nav_hover']}; }}
    QPushButton#NavBtn:checked {{
        background: {ac}; color: {c['accent_text']}; font-weight: 600;
    }}

    /* ---- top bar ---- */
    QFrame#TopBar {{
        background: {c['panel']}; border-bottom: 1px solid {c['border']};
    }}

    /* ---- structural containers (跟随主题切换) ---- */
    QFrame#CenterArea, QWidget#CenterArea {{
        background: {c['bg']};
    }}
    QFrame#PanelBG, QWidget#PanelBG {{
        background: {c['panel']};
    }}
    QFrame#PanelBG2, QWidget#PanelBG2 {{
        background: {c['panel2']};
    }}
    QFrame#BottomBar, QWidget#BottomBar {{
        background: {c['panel']}; border-top: 1px solid {c['border']};
    }}
    QFrame#ToolbarBG, QWidget#ToolbarBG {{
        background: {c['panel']}; border-bottom: 1px solid {c['border']};
    }}
    QDialog#ThemedDialog {{
        background: {c['bg']};
    }}
    QFrame#DialogPanel, QWidget#DialogPanel {{
        background: {c['panel']};
    }}

    /* ---- home hero card (主题色渐变，随皮肤切换) ---- */
    QFrame#HeroCard {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {c['accent2']}, stop:1 {ac});
        border-radius: 16px;
    }}
    QLabel#HeroTitle {{ color: white; font-size: 20px; font-weight: 800; background: transparent; }}
    QLabel#HeroSub {{ color: rgba(255,255,255,0.88); font-size: 13px; background: transparent; }}
    QLineEdit#HeroInput {{
        background: rgba(255,255,255,0.95); color: #0F172A;
        border: none; border-radius: 10px; padding: 9px 12px; font-size: 13px;
        min-height: 22px;
    }}
    QPushButton#HeroImport {{
        background: rgba(255,255,255,0.2); color: white; border: 1px solid rgba(255,255,255,0.4);
        border-radius: 8px; padding: 7px 14px; font-weight: 600;
    }}
    QPushButton#HeroImport:hover {{ background: rgba(255,255,255,0.3); }}
    QPushButton#HeroGo {{
        background: white; color: {c['accent2']}; border: none;
        border-radius: 10px; padding: 9px 22px; font-weight: 800; font-size: 13px;
    }}
    QPushButton#HeroGo:hover {{ background: #E8F5E9; border: 2px solid {c['accent2']}; padding: 7px 20px; }}
    QPushButton#HeroGo:pressed {{ background: {c['accent']}; color: white; border: none; padding: 9px 22px; }}
    QPushButton#StyleChip {{
        background: rgba(255,255,255,0.18); color: white; border: 1px solid rgba(255,255,255,0.3);
        border-radius: 14px; padding: 4px 12px; font-size: 12px;
    }}
    QPushButton#StyleChip:hover {{ background: rgba(255,255,255,0.3); border-color: rgba(255,255,255,0.75); }}
    QPushButton#StyleChip:pressed {{ background: rgba(255,255,255,0.5); }}
    QPushButton#StyleChip:checked {{
        background: white; color: {c['accent2']}; font-weight: 700; border-color: white;
    }}
    /* 创作类型选项卡（原创短剧 / 改编短剧） */
    QPushButton#HeroTab {{
        background: rgba(255,255,255,0.16); color: white;
        border: 2px solid rgba(255,255,255,0.32); border-radius: 10px;
        padding: 7px 21px; font-weight: 700; font-size: 14px;
    }}
    /* 悬停：加深底色并提亮描边；按下再亮一档，确保有明确点击反馈 */
    QPushButton#HeroTab:hover {{
        background: rgba(255,255,255,0.32); border-color: rgba(255,255,255,0.8);
    }}
    QPushButton#HeroTab:pressed {{ background: rgba(255,255,255,0.52); }}
    QPushButton#HeroTab:checked {{
        background: white; color: {c['accent2']}; border-color: white;
    }}
    QPushButton#HeroTab:checked:hover {{ background: #F2FBF9; border-color: white; }}
    QLabel#HeroFieldLabel {{ color: white; font-size: 13px; font-weight: 600; background: transparent; }}
    QSpinBox[heroParam="true"], QComboBox[heroParam="true"] {{
        background: white; color: #0F172A;
        border: 1px solid rgba(0,0,0,0.15); border-radius: 8px; padding: 5px 8px;
    }}
    QSpinBox[heroParam="true"]:hover, QComboBox[heroParam="true"]:hover {{
        border-color: #10B981;
    }}
    QSpinBox[heroParam="true"]:focus, QComboBox[heroParam="true"]:focus {{
        border-color: #10B981;
    }}
    QSpinBox[heroParam="true"]::drop-down, QComboBox[heroParam="true"]::drop-down {{
        border: none; width: 20px;
    }}
    QSpinBox[heroParam="true"]::down-arrow, QComboBox[heroParam="true"]::down-arrow {{
        image: none;
    }}
    QPlainTextEdit#HeroSource {{
        background: rgba(255,255,255,0.95); color: #0F172A; border: none;
        border-radius: 10px; padding: 8px 12px; font-size: 13px;
    }}
    QLineEdit#HeroScriptPath {{
        background: rgba(255,255,255,0.95); color: #0F172A; border: none;
        border-radius: 10px; padding: 9px 12px; font-size: 13px; min-height: 22px;
    }}

    /* ---- buttons ---- */
    QPushButton {{
        background: {c['panel2']}; border: 1px solid {c['border_strong']};
        border-radius: 8px; padding: 7px 16px; color: {c['text']};
    }}
    QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}
    QPushButton:pressed {{ background: {c['selected']}; }}
    QPushButton:checked {{ background: {c['selected']}; color: {c['accent_strong']}; font-weight: 600; }}
    QPushButton:disabled {{ color: {c['text_sub']}; background: {c['panel2']}; border-color: {c['border']}; }}
    QPushButton#PrimaryBtn {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c['accent2']}, stop:1 {c['accent']});
        color: {c['accent_text']}; border: none; font-weight: 600;
    }}
    QPushButton#PrimaryBtn:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c['accent']}, stop:1 {c['accent2']});
    }}
    QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; }}
    QToolButton:hover {{ background: {c['hover']}; }}

    /* ---- inputs ---- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        background: {c['panel']}; border: 1px solid {c['border_strong']};
        border-radius: 8px; padding: 6px 10px; min-height: 24px;
        selection-background-color: {ac};
        selection-color: {c['accent_text']};
    }}
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {ac};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px;
        selection-background-color: {c['selected']}; selection-color: {c['text']};
        outline: 0; padding: 4px; text-shadow: none;
    }}
    QComboBox QAbstractItemView::item {{ text-shadow: none; }}
    /* 数字输入框：Qt 默认上下箭头在自定义样式下会被压成小点，
       页面里需要滚轮/键盘调节的 SpinBox 自行关闭按钮（NoButtons）。 */

    /* ---- lists / tables / trees ---- */
    QListWidget, QTableWidget, QTableView, QTreeWidget {{
        background: {c['panel']}; border: 1px solid {c['border']};
        border-radius: {radius}px; outline: 0;
    }}
    QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
    QListWidget::item:hover {{ background: {c['hover']}; }}
    QListWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
    QTableWidget::item:selected, QTableView::item:selected, QTreeWidget::item:selected {{
        background: {c['selected']}; color: {c['text']};
    }}
    QHeaderView::section {{
        background: {c['panel2']}; border: none; padding: 7px 10px;
        border-bottom: 1px solid {c['border']}; color: {c['text_sub']}; font-weight: 600;
    }}

    /* ---- scroll areas transparent ---- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollArea > QWidget {{ background: transparent; }}

    /* ---- tabs ---- */
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: {radius}px; top: -1px; }}
    QTabBar::tab {{
        background: transparent; padding: 8px 16px; border-radius: 8px 8px 0 0;
        color: {c['text_sub']}; margin-right: 4px;
    }}
    QTabBar::tab:selected {{ color: {ac}; font-weight: 600; }}
    QTabBar::tab:hover {{ background: {c['hover']}; }}

    /* ---- group boxes ---- */
    QGroupBox {{
        border: 1px solid {c['border']}; border-radius: {radius}px;
        margin-top: 14px; padding-top: 8px; font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {c['text']};
    }}

    /* ---- labels ---- */
    QLabel[dim="true"] {{ color: {c['text_sub']}; }}

    /* ---- progress ---- */
    QProgressBar {{
        background: {c['panel2']}; border: none; border-radius: 6px;
        text-align: center; color: {c['text_sub']}; height: 12px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c['accent2']}, stop:1 {ac});
        border-radius: 6px;
    }}

    /* ---- scrollbars ---- */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {c['border_strong']}; border-radius: 5px; min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{
        background: {c['border_strong']}; border-radius: 5px; min-width: 32px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {c['accent']}; }}

    /* ---- status bar ---- */
    QStatusBar {{ background: {c['panel']}; border-top: 1px solid {c['border']}; color: {c['text_sub']}; }}

    /* ---- menus / tooltips ---- */
    QToolTip {{
        background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: 6px; padding: 6px 10px;
    }}
    QMenu {{
        background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 6px;
    }}
    QMenu::item {{ padding: 7px 22px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c['selected']}; }}

    /* ---- checkbox / radio ---- */
    QCheckBox, QRadioButton {{ spacing: 7px; }}
    QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 4px; border: 1px solid {c['border_strong']}; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {ac}; border-color: {ac};
    }}
    QRadioButton::indicator {{
        width: 16px; height: 16px; border-radius: 8px; border: 1px solid {c['border_strong']};
    }}

    /* ---- splitter ---- */
    QSplitter::handle {{ background: transparent; width: 2px; height: 2px; }}
    """


def apply_theme(app: QApplication, theme: str = "light", skin: str = "default") -> None:
    base = PALETTES.get(theme, LIGHT)
    c = _apply_skin(base, skin)
    app.setStyleSheet(_qss(c))
    app.setProperty("palette", theme)
    app.setProperty("skin", skin)

    # 让原生提示气泡（QToolTip）也跟随主题，否则 Windows 下会渲染成黑底白字
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["panel"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    app.setPalette(pal)

    # 递归 unpolish/polish 所有 widget，确保 objectName 级 QSS 生效
    def _refresh(w):
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()
        for child in w.findChildren(type(w)):
            pass
        for child in w.children():
            if isinstance(child, type(w).__mro__[0].__bases__[0]) or hasattr(child, 'style'):
                try:
                    child.style().unpolish(child)
                    child.style().polish(child)
                    child.update()
                except Exception:
                    pass

    app.style().unpolish(app)
    app.style().polish(app)
    from PyQt6.QtWidgets import QWidget
    for w in app.topLevelWidgets():
        # 先刷新顶层
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()
        # 再递归刷新所有子孙 widget
        for child in w.findChildren(QWidget):
            try:
                child.style().unpolish(child)
                child.style().polish(child)
                child.update()
            except Exception:
                pass


def current() -> str:
    app = QApplication.instance()
    return str(app.property("palette")) if app else "light"


def current_skin() -> str:
    app = QApplication.instance()
    return str(app.property("skin")) if app else "default"


def color(key: str) -> str:
    base = PALETTES.get(current(), LIGHT)
    c = _apply_skin(base, current_skin())
    return c.get(key, LIGHT.get(key, "#14B8A6"))


def as_rule_block(qss: str, selector: str = "QPushButton") -> str:
    """把「仅声明」形式的样式包进选择器块。

    Qt 允许控件样式只写声明（如 `background: #fff; color: #333`），会自动作用于该控件；
    但这种声明与后续的规则块（`QPushButton:hover { ... }`）混排时会让整张样式表解析失败，
    控件会失去全部自定义外观。追加规则前必须先包成规则块。
    """
    s = (qss or "").strip()
    if not s or "{" in s:
        return s
    return f"{selector} {{ {s} }}"


def refresh(widget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
