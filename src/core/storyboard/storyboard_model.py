import json
from dataclasses import dataclass, field, asdict
from typing import List

try:
    from core.utils.json_store import atomic_write_text
except ImportError:
    from src.core.utils.json_store import atomic_write_text

@dataclass
class VideoPromptSegment:
    """视频提示词分段，按秒描述"""
    start_time: float  # 开始时间（秒）
    end_time: float    # 结束时间（秒）
    description: str   # 该时间段的描述
    dialogue: str = ""          # 该时间段的对白
    camera_movement: str = ""   # 运镜
    sound_effect: str = ""      # 音效
    emotion: str = ""           # 情绪

    def to_dict(self):
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "description": self.description,
            "dialogue": self.dialogue,
            "camera_movement": self.camera_movement,
            "sound_effect": self.sound_effect,
            "emotion": self.emotion
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls(start_time=0, end_time=0, description="")
        return cls(
            start_time=data.get("start_time", 0),
            end_time=data.get("end_time", 0),
            description=data.get("description", ""),
            dialogue=data.get("dialogue", ""),
            camera_movement=data.get("camera_movement", ""),
            sound_effect=data.get("sound_effect", ""),
            emotion=data.get("emotion", "")
        )

    def format_time_range(self):
        """格式化时间范围显示"""
        if self.start_time == self.end_time:
            return f"第{int(self.start_time)}秒"
        else:
            start = int(self.start_time)
            end = int(self.end_time)
            if start == 0 and end == 1:
                return "第1秒"
            return f"第{start}-{end}秒"

    def __str__(self):
        return f"{self.format_time_range()}：{self.description}"


@dataclass
class Panel:
    panel_id: str
    scene_id: str
    description: str
    video_prompt: str = ""
    video_prompt_segments: List[VideoPromptSegment] = field(default_factory=list)
    image_path: str = ""
    history_images: List[str] = field(default_factory=list)
    characters: List[str] = field(default_factory=list)
    props: List[str] = field(default_factory=list)
    scenes: List[str] = field(default_factory=list)  # List of Scene names
    audio_path: str = ""
    video_path: str = ""
    history_videos: List[str] = field(default_factory=list)  # Video version history
    duration: float = 8.0  # 默认8秒（区间 5-10 秒，>10s 生成会爆显存）
    is_animated: bool = False
    prompt_params: dict = field(default_factory=dict)
    video_params: dict = field(default_factory=dict)
    reference_image_path: str = ""
    last_image_task_id: str = ""
    last_video_task_id: str = ""

    # 画面来源相关字段（P2.3）：ai 生成 / asset 素材库选取 / upload 用户上传
    image_source: str = "ai"
    image_asset_id: str = ""

    # 线稿模式相关字段
    use_line_art: bool = False
    line_art_image_path: str = ""

@dataclass
class Storyboard:
    script_title: str
    panels: List[Panel] = field(default_factory=list)

    def to_json(self):
        """序列化为JSON，处理VideoPromptSegment的特殊转换"""
        data = asdict(self)
        # 转换video_prompt_segments为可序列化的字典列表
        for panel in data.get('panels', []):
            if 'video_prompt_segments' in panel:
                panel['video_prompt_segments'] = [
                    segment.to_dict() if isinstance(segment, VideoPromptSegment) else segment
                    for segment in panel['video_prompt_segments']
                ]
        return json.dumps(data, indent=4, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        if not isinstance(data, dict):
            data = {}

        # 只保留数据类已知字段，缺失的 script_title 用默认值，避免旧版/手写 JSON 崩溃
        storyboard_fields = set(cls.__dataclass_fields__.keys())
        sb_kwargs = {k: v for k, v in data.items() if k in storyboard_fields and k != 'panels'}
        sb_kwargs.setdefault("script_title", "")
        sb = cls(**sb_kwargs)

        panel_fields = set(Panel.__dataclass_fields__.keys())
        # Panel 必填字段默认值，缺字段时不再 TypeError
        panel_required_defaults = {
            "panel_id": "",
            "scene_id": "",
            "description": "",
        }

        # 处理Panel的创建，特别是video_prompt_segments
        panels = []
        panels_data = data.get('panels', [])
        if not isinstance(panels_data, list):
            panels_data = []
        for p_data in panels_data:
            if not isinstance(p_data, dict):
                continue
            # 处理video_prompt_segments
            segments_data = p_data.get('video_prompt_segments', [])
            filtered = {k: v for k, v in p_data.items() if k in panel_fields and k != 'video_prompt_segments'}
            for key, default in panel_required_defaults.items():
                filtered.setdefault(key, default)

            try:
                panel = Panel(**filtered)
            except TypeError as e:
                print(f"Skipping invalid panel data: {e}")
                continue

            # 转换字典列表为VideoPromptSegment对象列表
            if isinstance(segments_data, list) and segments_data:
                panel.video_prompt_segments = [
                    VideoPromptSegment.from_dict(seg) if isinstance(seg, dict) else seg
                    for seg in segments_data
                ]
            panels.append(panel)

        sb.panels = panels
        return sb

    def save(self, filepath):
        # 原子写入，避免写一半损坏分镜文件
        atomic_write_text(filepath, self.to_json())
