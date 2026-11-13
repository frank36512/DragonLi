from PyQt6.QtWidgets import QMessageBox
import ctypes
import os

def apply_windows_dark_title_bar(window, dark=True):
    try:
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 2004+ and Windows 11)
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        hwnd = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        set_window_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass

def dir_signature(*paths):
    """
    计算文件/目录的轻量指纹（路径 + mtime）。
    用于 Tab 切换时判断是否需要重新加载：目录内容未变则跳过昂贵的
    JSON 解析 + 控件重建。比全量 load 快几个数量级。
    """
    parts = []
    for p in paths:
        if not p:
            parts.append(None)
            continue
        if os.path.isfile(p):
            try:
                parts.append((p, os.path.getmtime(p)))
            except OSError:
                parts.append((p, 0.0))
        elif os.path.isdir(p):
            try:
                entries = []
                with os.scandir(p) as it:
                    for entry in it:
                        try:
                            entries.append((entry.name, entry.stat().st_mtime))
                        except OSError:
                            continue
                parts.append((p, tuple(sorted(entries))))
            except OSError:
                parts.append((p, ()))
        else:
            parts.append((p, None))
    return tuple(parts)

def show_message(parent, title, text, icon=QMessageBox.Icon.Information):
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(icon)
    
    # Apply dark theme stylesheet explicitly if needed, though it should inherit from app
    # But title bar needs the DWM hack
    apply_windows_dark_title_bar(msg)
    
    msg.exec()

def show_warning(parent, title, text):
    show_message(parent, title, text, QMessageBox.Icon.Warning)

def show_error(parent, title, text):
    show_message(parent, title, text, QMessageBox.Icon.Critical)


def populate_api_combo(combo, config_manager, api_type, empty_text="未配置 (使用默认)", select_default=True):
    """
    按类型填充 API 配置下拉框，并选中默认项。
    统一原先分散在 project/script/storyboard 等窗口里的 8 份重复逻辑。
    """
    combo.clear()
    configs = config_manager.get("api_configs", []) or []
    matched = [c for c in configs if c.get("type") == api_type]

    default_index = 0
    for i, config in enumerate(matched):
        name = config.get("name") or f"{config.get('provider', '')} - {config.get('model', '')}".strip() or "Unnamed"
        combo.addItem(name, config)
        if config.get("is_default"):
            default_index = i

    if combo.count() == 0:
        combo.addItem(empty_text, {})
    elif select_default:
        combo.setCurrentIndex(default_index)

