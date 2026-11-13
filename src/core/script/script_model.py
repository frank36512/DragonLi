import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

try:
    from core.utils.json_store import atomic_write_text
except ImportError:
    from src.core.utils.json_store import atomic_write_text

@dataclass
class Dialogue:
    role: str
    content: str
    action: str = ""
    expression: str = ""
    tone: str = ""       # 语调：低沉/明亮/沙哑/甜美/颤抖/激昂/冰冷/温柔
    pace: str = ""       # 语速：缓慢/适中/快速/急促/停顿
    emotion: str = ""    # 情绪：平静/激动/愧疚/愤怒/恐惧/悲伤/喜悦/冷漠

@dataclass
class Scene:
    shot_id: str = "1-1"  # format: scene-shot, e.g. "1-1", "1-2"
    scene_location: str = ""
    time: str = "Day"
    weather: str = "Clear"
    atmosphere: str = ""
    style: str = ""
    shot_type: str = "中景"
    camera_movement: str = "固定"
    duration_seconds: int = 8
    characters: str = ""  # 兼容旧版字符串格式
    props: str = ""
    action: str = ""
    # Video prompt source
    dialogue: str = ""
    # AI generated prompts
    video_prompt: str = ""
    # 一致性与连续性字段（新版 schema）
    characters_detail: list = field(default_factory=list)  # [{name,pose,expression,clothing_note,position,emotional_state}]
    continuity_note: str = ""  # 与上一分镜的衔接说明
    # Legacy fields (for compatibility)
    scene_id: str = ""
    location: str = ""
    description: str = ""
    dialogues: list = field(default_factory=list)
    environment_image: str = ""
    scene_library_id: str = ""

    def get_character_names(self) -> list:
        """从 characters_detail 或 characters 字段提取角色名列表。"""
        if self.characters_detail:
            return [c.get("name", "") for c in self.characters_detail if isinstance(c, dict) and c.get("name")]
        if isinstance(self.characters, str) and self.characters:
            # 旧格式：逗号/顿号分隔的角色名或描述
            return [part.strip() for part in self.characters.replace("，", ",").replace("、", ",").split(",") if part.strip()]
        return []

    def get_character_detail(self, name: str) -> dict:
        """按角色名获取详细状态（pose/expression/emotional_state 等）。"""
        for c in self.characters_detail:
            if isinstance(c, dict) and c.get("name") == name:
                return c
        return {}

@dataclass
class Script:
    title: str
    genre: str
    summary: str = ""
    scenes: List[Scene] = field(default_factory=list)
    
    def to_json(self):
        return json.dumps(asdict(self), indent=4, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        
        # 兼容列表格式：如果 data 是列表，说明是纯场景列表
        if isinstance(data, list):
            script = cls(title="Untitled", genre="", summary="")
            for s_data in data:
                if not isinstance(s_data, dict):
                    continue
                
                # 处理 dialogue 字段：如果是列表，转换为字符串
                if 'dialogue' in s_data and isinstance(s_data['dialogue'], list):
                    dialogue_parts = []
                    for d in s_data['dialogue']:
                        if isinstance(d, dict):
                            role = d.get('role', '')
                            content = d.get('content', '')
                            action = d.get('action', '')
                            if role and content:
                                if action:
                                    dialogue_parts.append(f"{role}: {content} ({action})")
                                else:
                                    dialogue_parts.append(f"{role}: {content}")
                    s_data['dialogue'] = " | ".join(dialogue_parts)
                
                # 过滤场景数据
                scene_valid_keys = set(Scene.__dataclass_fields__.keys())
                scene_filtered_data = {k: v for k, v in s_data.items() if k in scene_valid_keys}
                scene = Scene(**scene_filtered_data)
                script.scenes.append(scene)
            return script
        
        # 字典格式处理（原有逻辑）
        scenes_data = data.pop('scenes', [])
        shots_data = data.pop('shots', [])
        
        if shots_data and not scenes_data:
            scenes_data = shots_data
        
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        # 旧版/手写 JSON 可能缺少必填字段，补默认值避免 TypeError
        filtered_data.setdefault("title", "")
        filtered_data.setdefault("genre", "")
        script = cls(**filtered_data)
        
        for s_data in scenes_data:
            if not isinstance(s_data, dict):
                continue
            
            # Map old fields to new if needed
            if 'scene_id' in s_data and not s_data.get('shot_id'):
                s_data['shot_id'] = s_data['scene_id']
            if 'location' in s_data and not s_data.get('scene_location'):
                s_data['scene_location'] = s_data['location']

            # 新版 schema：characters 是列表 [{name,pose,expression,...}]，转换为 characters_detail + 字符串兼容
            if isinstance(s_data.get('characters'), list):
                chars_list = s_data.pop('characters')
                # 存入 characters_detail（结构化状态）
                s_data['characters_detail'] = [c for c in chars_list if isinstance(c, dict)]
                # characters 字段保留角色名逗号分隔字符串（向后兼容）
                names = [c.get('name', '') for c in chars_list if isinstance(c, dict) and c.get('name')]
                s_data['characters'] = ",".join(names)
            # 旧版 characters 是字符串时，也生成空 characters_detail
            s_data.setdefault('characters_detail', [])

            # Filter scene data
            scene_valid_keys = set(Scene.__dataclass_fields__.keys())
            scene_filtered_data = {k: v for k, v in s_data.items() if k in scene_valid_keys}
            scene = Scene(**scene_filtered_data)
            
            # Handle old dialogues format - convert to dialogue string AND create Dialogue objects
            dialogues_data = s_data.get('dialogues', [])
            if dialogues_data and not scene.dialogue:
                dialogue_parts = []
                for d in dialogues_data:
                    if isinstance(d, Dialogue):
                        role = d.role
                        content = d.content
                        action = d.action
                    elif isinstance(d, dict):
                        role = d.get('role', '')
                        content = d.get('content', '')
                        action = d.get('action', '')
                    else:
                        continue
                    if role and content:
                        if action:
                            dialogue_parts.append(f"{role}: {content} ({action})")
                        else:
                            dialogue_parts.append(f"{role}: {content}")
                scene.dialogue = " | ".join(dialogue_parts)
            
            # If dialogues is still empty but dialogue string exists, parse it
            # 确保 dialogue 是字符串再调用 split
            if not scene.dialogues and isinstance(scene.dialogue, str) and scene.dialogue:
                for part in scene.dialogue.split("|"):
                    part = part.strip()
                    if not part:
                        continue
                    match = re.match(r'([^:]+):\s*(.+?)(?:\s*\(([^)]+)\))?$', part)
                    if match:
                        role = match.group(1).strip()
                        content = match.group(2).strip()
                        action = match.group(3).strip() if match.group(3) else ""
                        scene.dialogues.append(Dialogue(role=role, content=content, action=action))
            
            script.scenes.append(scene)
        
        return script

    def save(self, filepath):
        # 原子写入，避免写一半损坏剧本文件
        atomic_write_text(filepath, self.to_json())
