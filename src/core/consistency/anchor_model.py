"""
一致性锚点表（AnchorTable）

统一管理角色 / 场景 / 声音三类一致性锚点，每个图像/视频/音频生成都强制查表注入。

三层一致性模型：
    A 层（弱）：提示词层 —— appearance_features / description 等文本特征，拼进 prompt。
    B 层（中）：参考图层 —— avatar_path / reference_images / base_image，作为 ref_images 注入。
    C 层（强）：模型层 —— LoRA / IP-Adapter / ControlNet / 声纹克隆，直接在生成模型侧约束。

持久化：每个项目的根目录下 anchors.json，使用原子写盘。
"""
import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional

try:
    from core.utils.json_store import atomic_write_json, read_json_file
except ImportError:
    from src.core.utils.json_store import atomic_write_json, read_json_file


# --------------------------------------------------------------------------- #
# 单个锚点
# --------------------------------------------------------------------------- #
@dataclass
class CharacterAnchor:
    """角色一致性锚点"""
    character_id: str
    name: str
    avatar_path: str = ""              # 主参考图（A+B 层）
    reference_images: List[str] = field(default_factory=list)  # 多视角参考图（B 层）
    appearance_features: str = ""      # 外观特征提示词（A 层）
    lora_path: str = ""                # C 层：LoRA 模型路径
    ip_adapter_weight: float = 0.0     # C 层：IP-Adapter 权重（0=不启用）
    voice_id: str = ""                # TTS voice id（A 层）
    voice_sample_path: str = ""       # C 层：声纹克隆样本路径
    voice_description: str = ""       # 声音描述（A 层）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterAnchor":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid}
        filtered.setdefault("character_id", "")
        filtered.setdefault("name", "")
        return cls(**filtered)


@dataclass
class SceneAnchor:
    """场景一致性锚点"""
    scene_id: str
    name: str
    location: str = ""                 # 场景位置（A 层，用于与分镜 scene_location 匹配）
    base_image: str = ""               # 场景基准图（B 层，即 Scene.reference_image）
    description: str = ""              # 场景描述（A 层）
    controlnet: str = ""               # C 层：ControlNet 类型（depth/canny/openpose/lineart）
    controlnet_weight: float = 0.0      # C 层：ControlNet 权重（0=不启用）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SceneAnchor":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid}
        filtered.setdefault("scene_id", "")
        filtered.setdefault("name", "")
        return cls(**filtered)


# --------------------------------------------------------------------------- #
# 锚点表
# --------------------------------------------------------------------------- #
@dataclass
class AnchorTable:
    """一致性锚点表：一个项目一张表"""
    characters: List[CharacterAnchor] = field(default_factory=list)
    scenes: List[SceneAnchor] = field(default_factory=list)

    ANCHOR_FILE = "anchors.json"

    # ----- 序列化 -----
    def to_dict(self) -> dict:
        return {
            "characters": [c.to_dict() for c in self.characters],
            "scenes": [s.to_dict() for s in self.scenes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnchorTable":
        if not isinstance(data, dict):
            return cls()
        chars = [CharacterAnchor.from_dict(c) for c in data.get("characters", []) if isinstance(c, dict)]
        scenes = [SceneAnchor.from_dict(s) for s in data.get("scenes", []) if isinstance(s, dict)]
        return cls(characters=chars, scenes=scenes)

    # ----- 持久化 -----
    def save(self, project_dir: str) -> str:
        """原子写入 project_dir/anchors.json，返回文件路径"""
        path = os.path.join(project_dir, self.ANCHOR_FILE)
        atomic_write_json(path, self.to_dict(), indent=4, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, project_dir: str) -> "AnchorTable":
        """读取 project_dir/anchors.json，不存在或损坏时返回空表"""
        path = os.path.join(project_dir, cls.ANCHOR_FILE)
        data = read_json_file(path, default=None)
        if data is None:
            return cls()
        return cls.from_dict(data)

    # ----- 从角色库/场景库同步构建 -----
    @classmethod
    def from_project(cls, project_dir: str) -> "AnchorTable":
        """
        扫描 project_dir/characters/*.json 与 project_dir/scenes/*.json，
        从 Character/Scene 模型同步生成锚点表。
        已存在的 anchors.json 中 C 层字段（lora_path/controlnet 等）会被保留合并。
        """
        # 先读旧表，保留用户手工配置的 C 层参数
        old = cls.load(project_dir)
        old_char_map = {c.character_id: c for c in old.characters}
        old_scene_map = {s.scene_id: s for s in old.scenes}

        characters: List[CharacterAnchor] = []
        scenes: List[SceneAnchor] = []

        # 角色库
        try:
            from core.character.character_model import Character
        except ImportError:
            from src.core.character.character_model import Character

        chars_dir = os.path.join(project_dir, "characters")
        if os.path.isdir(chars_dir):
            for fname in os.listdir(chars_dir):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(chars_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        raw = f.read()
                    ch = Character.from_json(raw)
                except Exception as e:
                    print(f"[anchor] 跳过损坏的角色文件 {fname}: {e}")
                    continue
                old_c = old_char_map.get(ch.id)
                characters.append(CharacterAnchor(
                    character_id=ch.id,
                    name=ch.name,
                    avatar_path=ch.avatar_path,
                    reference_images=list(ch.reference_images),
                    appearance_features=ch.appearance_features,
                    # C 层参数：优先用旧表保留值，否则取模型新字段
                    lora_path=(old_c.lora_path if old_c else ch.lora_path),
                    ip_adapter_weight=(old_c.ip_adapter_weight if old_c else ch.ip_adapter_weight),
                    voice_id=ch.voice_id,
                    voice_sample_path=(old_c.voice_sample_path if old_c else ch.voice_sample_path),
                    voice_description=ch.voice_description,
                ))

        # 场景库
        try:
            from core.scene.scene_model import Scene
        except ImportError:
            from src.core.scene.scene_model import Scene

        scenes_dir = os.path.join(project_dir, "scenes")
        if os.path.isdir(scenes_dir):
            for fname in os.listdir(scenes_dir):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(scenes_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        raw = f.read()
                    sc = Scene.from_json(raw)
                except Exception as e:
                    print(f"[anchor] 跳过损坏的场景文件 {fname}: {e}")
                    continue
                old_s = old_scene_map.get(sc.id)
                scenes.append(SceneAnchor(
                    scene_id=sc.id,
                    name=sc.name,
                    location=sc.location,
                    base_image=sc.reference_image,
                    description=sc.description,
                    controlnet=(old_s.controlnet if old_s else sc.controlnet),
                    controlnet_weight=(old_s.controlnet_weight if old_s else sc.controlnet_weight),
                ))

        return cls(characters=characters, scenes=scenes)

    # ----- 查询 -----
    def find_character(self, name: str) -> Optional[CharacterAnchor]:
        """按名称查找角色锚点（分镜 characters 列表里存的是名称）"""
        if not name:
            return None
        for c in self.characters:
            if c.name == name:
                return c
        # 容错：忽略大小写
        low = name.lower()
        for c in self.characters:
            if c.name.lower() == low:
                return c
        return None

    def find_scene(self, name_or_location: str) -> Optional[SceneAnchor]:
        """按名称或 location 查找场景锚点（分镜 scene_location 是文本）"""
        if not name_or_location:
            return None
        # 先精确匹配 name
        for s in self.scenes:
            if s.name == name_or_location:
                return s
        # 再匹配 location
        for s in self.scenes:
            if s.location == name_or_location:
                return s
        # 模糊：location/name 包含分镜文本（应对"东京街道-夜晚"这类复合写法）
        for s in self.scenes:
            if name_or_location in s.name or name_or_location in s.location:
                return s
            if s.name in name_or_location or s.location in name_or_location:
                return s
        # 忽略大小写兜底
        low = name_or_location.lower()
        for s in self.scenes:
            if s.name.lower() == low or s.location.lower() == low:
                return s
        return None
