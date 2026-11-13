"""
素材库管理器

统一管理 AI 生成图、上传图、stock 素材；按 角色 / 场景 / 道具 / 其他 标签索引。

设计要点：
- 全局素材索引：resources/assets/index.json
- 项目素材索引：<project_dir>/assets/index.json
- 素材实体文件统一存放到对应 assets/files 目录，避免散落各处
- 自动扫描项目已有图片目录(images / characters / props / scenes)以纳入旧资产
- 所有 JSON 写盘均走原子写，遵循项目硬约束
"""
import os
import json
import re
import uuid
import shutil
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional

try:
    from core.utils.json_store import atomic_write_json, read_json_file
except ImportError:
    from src.core.utils.json_store import atomic_write_json, read_json_file

try:
    from core.utils.log_manager import info, debug, warning, error
except ImportError:
    try:
        from src.core.utils.log_manager import info, debug, warning, error
    except ImportError:
        def info(msg): print(msg)
        def debug(msg): print(msg)
        def warning(msg): print(msg)
        def error(msg): print(msg)

# 素材类型
ASSET_TYPE_IMAGE = "image"
ASSET_TYPE_VIDEO = "video"
ASSET_TYPE_AUDIO = "audio"

# 素材来源
ASSET_SOURCE_AI = "ai_generated"
ASSET_SOURCE_UPLOAD = "uploaded"
ASSET_SOURCE_STOCK = "stock"

# 标签类别（按 角色/场景/道具 索引 + 自由标签）
TAG_CHARACTER = "character"
TAG_SCENE = "scene"
TAG_PROP = "prop"
TAG_OTHER = "other"

# 图片扩展名
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


def _detect_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return ASSET_TYPE_IMAGE
    if ext in _VIDEO_EXTS:
        return ASSET_TYPE_VIDEO
    if ext in _AUDIO_EXTS:
        return ASSET_TYPE_AUDIO
    # 未知扩展名（如 .json 数据文件）返回空串，由调用方决定是否跳过，
    # 否则会被当成图片素材，出现“缩略图加载不出”的空卡片
    return ""


def _is_media_file(path: str) -> bool:
    """是否为受支持的媒体文件（图片/视频/音频）。"""
    return bool(_detect_type(path))


def _norm_path(path: str) -> str:
    """归一化路径用于去重（Windows 下大小写不敏感，避免 E:\\ 与 e:\\ 被判为两条）。"""
    return os.path.normcase(os.path.normpath(path or ""))


def _entity_uuid(stem: str) -> str:
    """从 char_<uuid> / prop_<uuid> / scene_<uuid> 或 <名字>_<uuid> 中取出 uuid。"""
    m = re.search(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                  r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', stem or "")
    return m.group(1).lower() if m else ""


def _build_entity_name_map(project_dir: str) -> Dict[str, str]:
    """扫描 characters/props/scenes 下的实体 JSON，返回 {uuid: 实体名}。

    用于把 char_<uuid>.png 这类内部文件名还原成「云汐」「仙鹤玉佩」等可读名称。
    """
    name_map: Dict[str, str] = {}
    if not project_dir:
        return name_map
    for sub in ("characters", "props", "scenes"):
        sub_dir = os.path.join(project_dir, sub)
        if not os.path.isdir(sub_dir):
            continue
        for fn in os.listdir(sub_dir):
            if not fn.lower().endswith(".json"):
                continue
            stem = os.path.splitext(fn)[0]
            try:
                data = read_json_file(os.path.join(sub_dir, fn), default={})
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            display = (data.get("name") or "").strip()
            if not display:
                continue
            # JSON 文件名形如 <名字>_<uuid>，同时登记 uuid 与文件名前缀两种键
            uid = _entity_uuid(stem)
            if uid:
                name_map[uid] = display
            prefix = stem.split("_")[0].strip()
            if prefix:
                name_map.setdefault(f"prefix:{prefix}", display)
    return name_map


def _friendly_asset_name(path: str, name_map: Optional[Dict[str, str]] = None) -> str:
    """把素材文件名转成可读显示名，取不到实体名时退化为去掉前缀/uuid 的文件名。"""
    base = os.path.basename(path or "")
    stem = os.path.splitext(base)[0]
    if not stem:
        return "未命名"

    name_map = name_map or {}
    uid = _entity_uuid(stem)
    if uid and uid in name_map:
        return name_map[uid]

    prefix = stem.split("_")[0].strip()
    if prefix and f"prefix:{prefix}" in name_map:
        return name_map[f"prefix:{prefix}"]

    # 回退：去掉 char_/prop_/scene_ 前缀与 uuid 尾巴
    cleaned = re.sub(r'^(?:char|prop|scene)_', '', stem, flags=re.IGNORECASE)
    if uid:
        cleaned = cleaned.replace(uid, "").strip("_ -")
    return cleaned or stem


@dataclass
class AssetItem:
    id: str
    path: str             # 素材文件绝对路径
    name: str             # 显示名
    type: str = ASSET_TYPE_IMAGE
    source: str = ASSET_SOURCE_UPLOAD  # ai_generated / uploaded / stock
    tag: str = TAG_OTHER  # character / scene / prop / other
    linked_id: str = ""   # 关联的角色/道具/场景 ID
    linked_name: str = "" # 关联实体名（用于展示）
    project_id: str = ""  # 所属项目 ID（文件夹名），空表示全局
    tags: List[str] = field(default_factory=list)  # 自由标签
    description: str = ""
    prompt: str = ""     # AI 生成时的提示词
    created_at: str = ""
    size: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AssetItem":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid}
        filtered.setdefault("id", str(uuid.uuid4()))
        filtered.setdefault("name", "Unknown")
        return cls(**filtered)


class AssetManager:
    """素材库管理器：负责扫描、登记、查询、增删素材。"""

    INDEX_FILENAME = "index.json"
    FILES_SUBDIR = "files"

    def __init__(self, resources_dir: str, project_dir: Optional[str] = None):
        self.resources_dir = resources_dir
        self.global_assets_dir = os.path.join(resources_dir, "assets")
        self.global_index_path = os.path.join(self.global_assets_dir, self.INDEX_FILENAME)
        os.makedirs(self.global_assets_dir, exist_ok=True)
        os.makedirs(os.path.join(self.global_assets_dir, self.FILES_SUBDIR), exist_ok=True)

        self.project_dir = project_dir
        self._name_map_cache: Optional[Dict[str, str]] = None
        if project_dir:
            self.project_assets_dir = os.path.join(project_dir, "assets")
            self.project_index_path = os.path.join(self.project_assets_dir, self.INDEX_FILENAME)
            os.makedirs(self.project_assets_dir, exist_ok=True)
            os.makedirs(os.path.join(self.project_assets_dir, self.FILES_SUBDIR), exist_ok=True)
        else:
            self.project_assets_dir = None
            self.project_index_path = None

    # ---------- index load / save ----------
    def _name_map(self) -> Dict[str, str]:
        """实体名映射（uuid -> 实体名），按项目缓存，切换项目时失效。"""
        if self._name_map_cache is None:
            self._name_map_cache = _build_entity_name_map(self.project_dir or "")
        return self._name_map_cache

    @staticmethod
    def _looks_internal(name: str, path: str) -> bool:
        """名称是否等于内部文件名（char_<uuid> / <文件名>），是则说明需要用友好名替换。"""
        nm = (name or "").strip()
        base = os.path.basename(path or "")
        stem = os.path.splitext(base)[0]
        if not nm:
            return True
        if nm in (base, stem):
            return True
        return bool(re.fullmatch(r'(?:char|prop|scene)_[0-9a-fA-F-]{36}', nm))

    def _load_index_raw(self, index_path: str) -> List[AssetItem]:
        """读取索引原始条目（不做去重/过滤/改名）。"""
        data = read_json_file(index_path, default={"items": []})
        raw = data.get("items", []) if isinstance(data, dict) else []
        return [AssetItem.from_dict(it) for it in raw]

    def _filter_items(self, raw: List[AssetItem]) -> List[AssetItem]:
        """过滤非媒体文件、按路径去重，并把内部文件名还原为可读名称。"""
        name_map = self._name_map()
        out: List[AssetItem] = []
        seen = set()
        for item in raw:
            # 过滤非媒体文件（历史脏数据：.json 被误登记为图片 -> 空缩略图卡片）
            if not _is_media_file(item.path or ""):
                continue
            key = _norm_path(item.path or "")
            if key in seen:
                continue
            seen.add(key)
            # 内部文件名（char_<uuid>.png）还原为「云汐」这类可读名称
            if self._looks_internal(item.name, item.path):
                item.name = _friendly_asset_name(item.path, name_map)
            out.append(item)
        return out

    def _load_index(self, index_path: str) -> List[AssetItem]:
        return self._filter_items(self._load_index_raw(index_path))

    def _save_index(self, index_path: str, items: List[AssetItem]) -> None:
        atomic_write_json(index_path, {"items": [it.to_dict() for it in items]})

    # ---------- public API ----------
    def list_assets(self, scope: str = "all") -> List[AssetItem]:
        """
        scope:
          - "all": 全局 + 当前项目
          - "global": 仅全局
          - "project": 仅当前项目
        """
        result: List[AssetItem] = []
        if scope in ("all", "global"):
            result.extend(self._load_index(self.global_index_path))
        if scope in ("all", "project") and self.project_index_path:
            result.extend(self._load_index(self.project_index_path))
        return result

    def query(self,
              type_filter: Optional[str] = None,
              tag_filter: Optional[str] = None,
              source_filter: Optional[str] = None,
              keyword: Optional[str] = None,
              scope: str = "all") -> List[AssetItem]:
        items = self.list_assets(scope=scope)
        out = []
        kw = (keyword or "").strip().lower()
        for it in items:
            if type_filter and it.type != type_filter:
                continue
            if tag_filter and it.tag != tag_filter:
                continue
            if source_filter and it.source != source_filter:
                continue
            if kw:
                hay = f"{it.name} {it.description} {it.linked_name} {' '.join(it.tags)}".lower()
                if kw not in hay:
                    continue
            out.append(it)
        return out

    def add_asset(self,
                  src_path: str,
                  name: Optional[str] = None,
                  type_: Optional[str] = None,
                  source: str = ASSET_SOURCE_UPLOAD,
                  tag: str = TAG_OTHER,
                  linked_id: str = "",
                  linked_name: str = "",
                  project_id: str = "",
                  description: str = "",
                  prompt: str = "",
                  tags: Optional[List[str]] = None,
                  copy_file: bool = True,
                  scope: str = "project") -> Optional[AssetItem]:
        """
        新增素材。copy_file=True 会把源文件拷贝到 assets/files 目录统一管理。
        scope: "project" 写入项目索引，"global" 写入全局索引。
        """
        if not src_path or not os.path.exists(src_path):
            warning(f"[AssetManager] 源文件不存在: {src_path}")
            return None

        asset_id = str(uuid.uuid4())
        display_name = name or os.path.splitext(os.path.basename(src_path))[0]
        asset_type = type_ or _detect_type(src_path)
        # 非媒体文件（.json 等）不应进入素材库，否则会出现空缩略图卡片
        if not asset_type:
            warning(f"[AssetManager] 不支持的素材类型，已忽略: {src_path}")
            return None
        # 决定目标目录
        if scope == "project" and self.project_assets_dir:
            target_dir = os.path.join(self.project_assets_dir, self.FILES_SUBDIR)
        else:
            target_dir = os.path.join(self.global_assets_dir, self.FILES_SUBDIR)
            scope = "global"
        os.makedirs(target_dir, exist_ok=True)

        ext = os.path.splitext(src_path)[1]
        dest_name = f"{asset_id}{ext}"
        dest_path = os.path.join(target_dir, dest_name)

        if copy_file:
            try:
                # 同源目录则跳过拷贝（避免在 assets/files 内自拷）
                if os.path.normpath(src_path) != os.path.normpath(dest_path):
                    shutil.copy2(src_path, dest_path)
            except Exception as e:
                error(f"[AssetManager] 拷贝素材失败: {e}")
                return None
            file_path = dest_path
        else:
            file_path = os.path.abspath(src_path)

        # 解析 project_id：留空表全局，否则取项目目录名
        pid = ""
        if scope == "project" and self.project_dir:
            pid = os.path.basename(self.project_dir.rstrip(os.sep))
        elif project_id:
            pid = project_id

        try:
            size = os.path.getsize(file_path)
        except OSError:
            size = 0

        item = AssetItem(
            id=asset_id,
            path=file_path,
            name=display_name,
            type=asset_type,
            source=source,
            tag=tag,
            linked_id=linked_id,
            linked_name=linked_name,
            project_id=pid,
            tags=list(tags or []),
            description=description,
            prompt=prompt,
            created_at=datetime.now().isoformat(),
            size=size,
        )

        index_path = self.project_index_path if scope == "project" and self.project_index_path else self.global_index_path
        items = self._load_index(index_path)
        items.append(item)
        self._save_index(index_path, items)
        info(f"[AssetManager] 新增素材 {display_name} -> {index_path}")
        return item

    def remove_asset(self, asset_id: str, delete_file: bool = True) -> bool:
        """从索引中删除指定素材，可选删除实体文件。会自动在两个索引中查找。"""
        for index_path in (self.project_index_path, self.global_index_path):
            if not index_path:
                continue
            items = self._load_index(index_path)
            target = next((it for it in items if it.id == asset_id), None)
            if target is None:
                continue
            items = [it for it in items if it.id != asset_id]
            self._save_index(index_path, items)
            if delete_file and target.path and os.path.exists(target.path):
                try:
                    os.remove(target.path)
                except OSError as e:
                    warning(f"[AssetManager] 删除实体文件失败: {e}")
            info(f"[AssetManager] 已删除素材 {target.name} ({index_path})")
            return True
        warning(f"[AssetManager] 未找到要删除的素材 id={asset_id}")
        return False

    def update_asset(self, asset_id: str, **fields) -> Optional[AssetItem]:
        """更新素材属性；只支持 dataclass 已有字段。"""
        for index_path in (self.project_index_path, self.global_index_path):
            if not index_path:
                continue
            items = self._load_index(index_path)
            for it in items:
                if it.id == asset_id:
                    valid = AssetItem.__dataclass_fields__
                    for k, v in fields.items():
                        if k in valid:
                            setattr(it, k, v)
                    self._save_index(index_path, items)
                    return it
        return None

    # ---------- 扫描旧资产 ----------
    def scan_existing_assets(self, force: bool = False) -> int:
        """
        扫描项目目录下的 images/characters/props/scenes 子目录里的图片，
        把尚未登记的文件加入素材索引。返回新增数量。
        """
        if not self.project_dir:
            return 0
        added = 0
        # 目录 -> tag 映射
        scan_map = {
            "images": (TAG_OTHER, ""),
            "characters": (TAG_CHARACTER, ""),
            "props": (TAG_PROP, ""),
            "scenes": (TAG_SCENE, ""),
        }
        raw_items = self._load_index_raw(self.project_index_path)
        # 清理历史脏数据：非媒体文件（如误登记成图片的 .json）与重复路径一并剔除
        items = self._filter_items(raw_items)
        purged = len(raw_items) - len(items)

        name_map = self._name_map()
        existing_paths = {_norm_path(it.path) for it in items}

        for sub, (tag, _) in scan_map.items():
            sub_dir = os.path.join(self.project_dir, sub)
            if not os.path.isdir(sub_dir):
                continue
            for root, _dirs, files in os.walk(sub_dir):
                for fn in files:
                    if not _is_media_file(fn):
                        continue
                    fpath = os.path.join(root, fn)
                    norm = _norm_path(fpath)
                    if norm in existing_paths:
                        continue
                    item = AssetItem(
                        id=str(uuid.uuid4()),
                        path=fpath,
                        name=_friendly_asset_name(fpath, name_map),
                        type=_detect_type(fpath),
                        source=ASSET_SOURCE_AI if sub == "images" else ASSET_SOURCE_UPLOAD,
                        tag=tag,
                        project_id=os.path.basename(self.project_dir.rstrip(os.sep)),
                        created_at=datetime.now().isoformat(),
                    )
                    try:
                        item.size = os.path.getsize(fpath)
                    except OSError:
                        pass
                    items.append(item)
                    existing_paths.add(norm)
                    added += 1
        if added > 0 or purged > 0 or force:
            self._save_index(self.project_index_path, items)
        if purged:
            info(f"[AssetManager] 清理 {purged} 个非媒体脏素材条目")
        if added:
            info(f"[AssetManager] 扫描旧资产完成，新增 {added} 个素材到 {self.project_index_path}")
        return added

    # ---------- 项目切换 ----------
    def set_project_dir(self, project_dir: Optional[str]) -> None:
        self._name_map_cache = None
        if not project_dir:
            self.project_dir = None
            self.project_assets_dir = None
            self.project_index_path = None
            return
        self.project_dir = project_dir
        self.project_assets_dir = os.path.join(project_dir, "assets")
        self.project_index_path = os.path.join(self.project_assets_dir, self.INDEX_FILENAME)
        os.makedirs(self.project_assets_dir, exist_ok=True)
        os.makedirs(os.path.join(self.project_assets_dir, self.FILES_SUBDIR), exist_ok=True)
