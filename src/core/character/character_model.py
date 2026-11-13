import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict

try:
    from core.utils.json_store import atomic_write_text
except ImportError:
    from src.core.utils.json_store import atomic_write_text

@dataclass
class Character:
    id: str
    name: str
    age: str = ""
    gender: str = ""
    nationality: str = ""   # 国别/族裔，如"中国汉族""日本大和""欧美白人"，用于角色图一致性
    appearance_features: str = ""  # e.g., "Blue hair, twin tails, mechanical eye"
    style_description: str = ""    # e.g., "Cyberpunk, Anime style"
    personality: str = ""          # 性格特点
    role_in_story: str = ""        # 在故事中的角色（主角/配角/反派等）
    voice_id: str = ""        # e.g., "zh_male_xiaoshuai" (TTS ID)
    voice_description: str = "" # e.g., "Deep, raspy male voice" (For Video Gen)
    language: str = "English" # e.g., "English", "Chinese", "Japanese"
    avatar_path: str = ""     # Path to the main avatar image (正面图)
    project_id: str = ""      # ID (folder name) of the project this character belongs to
    reference_images: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    ai_prompt: str = ""       # AI生成的提示词（当前使用的提示词）
    default_ai_prompt: str = ""  # 创建项目时AI自动生成的默认提示词（用于恢复）
    # 5 view images for character
    front_view: str = ""      # 正面图 (default)
    back_view: str = ""       # 后面图
    right_side_view: str = ""  # 右侧面图
    left_side_view: str = ""   # 左侧面图
    top_view: str = ""        # 俯视图
    grid_1drag4_path: str = ""  # 1拖4五宫格图片路径
    # 一致性 C 层参数
    lora_path: str = ""            # LoRA 模型路径（角色一致性）
    ip_adapter_weight: float = 0.0  # IP-Adapter 权重（0=不启用）
    voice_sample_path: str = ""    # 声纹克隆样本路径（声音一致性）
    
    def to_json(self):
        return json.dumps(asdict(self), indent=4)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        
        # Handle nested format: {"xxx.png": {"name": ..., "gender": ...}}
        if len(data) == 1 and isinstance(list(data.values())[0], dict):
            inner = list(data.values())[0]
            if "id" not in inner and "name" not in inner:
                # Try to extract from outer key
                outer_key = list(data.keys())[0]
                inner["id"] = outer_key.replace(".png", "").replace("character_", "")
                if "name" not in inner:
                    inner["name"] = outer_key.replace(".png", "").replace("character_", "")
            data = inner
        
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        
        # Ensure required fields exist
        if "id" not in filtered:
            import uuid
            filtered["id"] = str(uuid.uuid4())
        if "name" not in filtered:
            filtered["name"] = "Unknown"
        
        return cls(**filtered)

    def save(self, directory):
        # 如果传入的目录已经是characters目录，则直接使用
        if os.path.basename(directory) == "characters":
            characters_dir = directory
        else:
            # 否则，在目录下创建characters子目录
            characters_dir = os.path.join(directory, "characters")
        
        # 确保characters目录存在
        if not os.path.exists(characters_dir):
            os.makedirs(characters_dir, exist_ok=True)
        
        # 清理文件名中的特殊字符（结尾的点和空格在 Windows 下也非法）
        safe_name = "".join(c for c in self.name if c not in '<>:"/\\|?*').strip().rstrip('.')
        safe_name = safe_name[:50] or "character"  # 限制文件名长度
        filename = f"{safe_name}_{self.id}.json"
        path = os.path.join(characters_dir, filename)

        # 重命名后旧文件残留会导致同ID出现两个文件，加载时形成重复项
        # 在写入前清理同ID的旧文件（文件名后缀为 _{id}.json 但与目标文件名不同）
        id_suffix = f"_{self.id}.json"
        try:
            for existing in os.listdir(characters_dir):
                if existing.endswith(id_suffix) and existing != filename:
                    try:
                        os.remove(os.path.join(characters_dir, existing))
                        print(f"DEBUG: Removed orphan character file {existing}")
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            atomic_write_text(path, self.to_json())
            print(f"DEBUG: Character saved to {path}")
            return path
        except Exception as e:
            print(f"保存角色失败: {e}")
            import traceback
            traceback.print_exc()
            return None
