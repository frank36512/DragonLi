# -*- coding: utf-8 -*-
"""导出预设：统一管理各平台分辨率/帧率/质量参数。

UI（导出弹窗）与合成器（VideoComposer / 控制器 _stage_compose）共用同一份预设，
避免两边硬编码分辨率列表导致不一致。
"""
from dataclasses import dataclass, asdict


@dataclass
class ExportPreset:
    """单个导出预设。width/height 为 None 表示保持原始分辨率。"""
    key: str            # 唯一标识，如 "douyin"
    name: str           # 显示名，如 "抖音 9:16"
    width: int          # 目标宽（0 表示保持原始）
    height: int         # 目标高（0 表示保持原始）
    fps: int = 30       # 目标帧率
    quality: str = "high"  # high / medium / low
    format: str = "mp4"    # mp4 / mov / avi
    aspect: str = "9:16"  # 仅用于 UI 展示
    bitrate_k: int = 0    # 0=由 quality 决定；>0 显式码率（kbps）
    description: str = ""

    def resolution(self):
        """返回 (w, h) 或 None（保持原始）。"""
        if self.width and self.height:
            return (self.width, self.height)
        return None

    def to_dict(self):
        return asdict(self)


# ---- 预设表（单一数据源）----
PRESETS = [
    ExportPreset(
        key="douyin", name="抖音 9:16",
        width=1080, height=1920, fps=30, quality="high",
        aspect="9:16", bitrate_k=0,
        description="抖音/抖音火山版竖屏 1080×1920，30fps 高画质",
    ),
    ExportPreset(
        key="tiktok", name="TikTok 9:16",
        width=1080, height=1920, fps=30, quality="high",
        aspect="9:16", bitrate_k=0,
        description="TikTok 国际版竖屏 1080×1920，30fps 高画质",
    ),
    ExportPreset(
        key="kuaishou", name="快手 9:16",
        width=720, height=1280, fps=30, quality="high",
        aspect="9:16", bitrate_k=0,
        description="快手竖屏 720×1280，30fps 高画质",
    ),
    ExportPreset(
        key="bilibili", name="B站 16:9",
        width=1920, height=1080, fps=30, quality="high",
        aspect="16:9", bitrate_k=0,
        description="哔哩哔哩横屏 1920×1080，30fps 高画质",
    ),
    ExportPreset(
        key="youtube", name="YouTube 16:9",
        width=1920, height=1080, fps=30, quality="high",
        aspect="16:9", bitrate_k=0,
        description="YouTube 横屏 1920×1080，30fps 高画质",
    ),
    ExportPreset(
        key="custom", name="自定义",
        width=0, height=0, fps=0, quality="high",
        aspect="", bitrate_k=0,
        description="保持原始分辨率与帧率",
    ),
]

# key -> ExportPreset
_PRESET_MAP = {p.key: p for p in PRESETS}


def list_presets():
    """返回所有预设（顺序固定，UI 直接遍历）。"""
    return list(PRESETS)


def get_preset(key):
    """按 key 取预设；未知 key 返回 custom 预设。"""
    return _PRESET_MAP.get(key, _PRESET_MAP["custom"])


def preset_keys():
    """所有预设 key（供 UI 按钮组 id 映射）。"""
    return [p.key for p in PRESETS]
