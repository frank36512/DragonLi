"""
角色/场景/道具资源索引：把"每个面板重新扫目录 + 解析全部 JSON"降为一次索引查询。

背景：storyboard/video_gen 等窗口在生成提示词时，曾对每个镜头的每个角色名
都 os.listdir + 逐个 Character.from_json，复杂度 O(面板 × 角色 × 文件)。
本模块按目录缓存 {name: Entity}，用目录内容签名（文件名+mtime）判断失效。
"""
import os
import threading

try:
    from core.character.character_model import Character
    from core.scene.scene_model import Scene
    from core.prop.prop_model import Prop
except ImportError:
    from src.core.character.character_model import Character
    from src.core.scene.scene_model import Scene
    from src.core.prop.prop_model import Prop

_lock = threading.Lock()
_cache = {}  # dir -> (signature, {name: Entity}, {id: Entity})


def _dir_signature(directory):
    try:
        entries = []
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.endswith(".json"):
                    try:
                        entries.append((entry.name, entry.stat().st_mtime))
                    except OSError:
                        continue
        return tuple(sorted(entries))
    except OSError:
        return ()


def _load_index(directory, loader):
    sig = _dir_signature(directory)
    with _lock:
        cached = _cache.get(directory)
        if cached is not None and cached[0] == sig:
            return cached[1], cached[2]

    by_name = {}
    by_id = {}
    if os.path.isdir(directory):
        for fn in os.listdir(directory):
            if not fn.endswith(".json") or fn == "metadata.json":
                continue
            try:
                with open(os.path.join(directory, fn), "r", encoding="utf-8") as f:
                    entity = loader(f.read())
                name = getattr(entity, "name", None)
                eid = getattr(entity, "id", None)
                if name:
                    by_name[name] = entity
                if eid:
                    by_id[eid] = entity
                    # 文件名通常为 {name}_{id}.json，id 也作为文件名匹配的后备键
                    by_id.setdefault(fn, entity)
            except Exception:
                continue

    with _lock:
        _cache[directory] = (sig, by_name, by_id)
    return by_name, by_id


def character_index(char_dir):
    """{name: Character}；目录内容变化时自动重建。"""
    by_name, _ = _load_index(char_dir, Character.from_json)
    return by_name


def character_by_id(char_dir, entity_id):
    """按 id（或含 id 的文件名）查找 Character；找不到返回 None。"""
    if not entity_id:
        return None
    _, by_id = _load_index(char_dir, Character.from_json)
    return by_id.get(entity_id)


def scene_index(scene_dir):
    """{name: Scene}"""
    by_name, _ = _load_index(scene_dir, Scene.from_json)
    return by_name


def scene_by_id(scene_dir, entity_id):
    if not entity_id:
        return None
    _, by_id = _load_index(scene_dir, Scene.from_json)
    return by_id.get(entity_id)


def prop_index(prop_dir):
    """{name: Prop}"""
    by_name, _ = _load_index(prop_dir, Prop.from_json)
    return by_name


def prop_by_id(prop_dir, entity_id):
    if not entity_id:
        return None
    _, by_id = _load_index(prop_dir, Prop.from_json)
    return by_id.get(entity_id)


def invalidate(directory=None):
    """手动失效缓存（新增/删除实体后可调用；通常 mtime 签名已能自动感知）。"""
    with _lock:
        if directory is None:
            _cache.clear()
        else:
            _cache.pop(directory, None)
