import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict

try:
    from core.utils.json_store import atomic_write_text
except ImportError:
    from src.core.utils.json_store import atomic_write_text

@dataclass
class Prop:
    id: str
    name: str
    description: str = ""
    category: str = ""  # e.g., "Weapon", "Tool", "Furniture", "饰品", "食物", "其他"
    importance: str = "一般"  # "重要" 或 "一般"
    reference_image: str = ""
    tags: List[str] = field(default_factory=list)
    ai_prompt: str = ""  # AI生成的提示词（当前使用的提示词）
    default_ai_prompt: str = ""  # 创建项目时AI自动生成的默认提示词（用于恢复）
    project_id: str = ""  # 所属项目ID
    # 5 view images for prop
    front_view: str = ""      # 正视图 (default)
    back_view: str = ""       # 后视图
    top_view: str = ""        # 上视图
    bottom_view: str = ""     # 下视图
    side_view: str = ""       # 侧视图
    grid_1drag4_path: str = ""  # 1拖4五宫格图片路径
    
    def to_json(self):
        return json.dumps(asdict(self), indent=4)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        # 必填字段缺失时补默认值，避免旧数据 TypeError
        filtered.setdefault("id", str(uuid.uuid4()))
        filtered.setdefault("name", "Unknown")
        return cls(**filtered)

    def save(self, directory):
        # 如果传入的目录已经是props目录，则直接使用
        if os.path.basename(directory) == "props":
            props_dir = directory
        else:
            # 否则，在目录下创建props子目录
            props_dir = os.path.join(directory, "props")
        
        # 确保props目录存在
        if not os.path.exists(props_dir):
            os.makedirs(props_dir, exist_ok=True)
        
        # 清理文件名中的特殊字符（结尾的点和空格在 Windows 下也非法）
        safe_name = "".join(c for c in self.name if c not in '<>:"/\\|?*').strip().rstrip('.')
        safe_name = safe_name[:50] or "prop"  # 限制文件名长度
        filename = f"{safe_name}_{self.id}.json"
        path = os.path.join(props_dir, filename)

        # 重命名后旧文件残留会导致同ID出现两个文件，加载时形成重复项
        # 在写入前清理同ID的旧文件（文件名后缀为 _{id}.json 但与目标文件名不同）
        id_suffix = f"_{self.id}.json"
        try:
            for existing in os.listdir(props_dir):
                if existing.endswith(id_suffix) and existing != filename:
                    try:
                        os.remove(os.path.join(props_dir, existing))
                        print(f"DEBUG: Removed orphan prop file {existing}")
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            atomic_write_text(path, self.to_json())
            print(f"DEBUG: Prop saved to {path}")
            return path
        except Exception as e:
            print(f"保存道具失败: {e}")
            import traceback
            traceback.print_exc()
            return None
