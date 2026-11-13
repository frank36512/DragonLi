# -*- coding: utf-8 -*-
"""面板参考图收集（原创/改编两条链路共用）。

统一规则：
- 优先级：角色（按分镜出场顺序，主角在前）→ 场景 → 道具；
- 角色：优先单张正面图（front_view / avatar_path / reference_images），
  四宫格拼图只在没有任何单图时兜底（拼图会让参考 token 翻好几倍，采样极慢）；
- 场景：close_view / reference_image，取 1 张；
- 道具：front_view / reference_image，取 1 张；
- 总数上限由调用方给出（Video 配置 max_ref_images）。
  MiniMaxH3 的参考槽是动态的（COMFY_AUTOGROW_V3，min=0/max=9），最多可传 9 张。

关键：必须按"角色ID 去 characters 目录找角色 JSON"，
不能在 panel 字典里找 "{char_id}_front_view" 这类拼接键——panel 里根本没有这些键，
旧实现因此一张角色图都取不到（等于纯文生视频）。
"""
import os

try:
    from core.character.character_model import Character
    from core.prop.prop_model import Prop
    from core.scene.scene_model import Scene
except ImportError:
    from src.core.character.character_model import Character
    from src.core.prop.prop_model import Prop
    from src.core.scene.scene_model import Scene

# MiniMaxH3 参考槽上限（服务端 COMFY_AUTOGROW_V3 max=9）
MAX_REF_SLOTS = 9
# 默认 1~2 张角色 + 1 张场景 + 1 张道具
DEFAULT_MAX_REFS = 4

_KIND_LABEL = {"character": "角色", "scene": "场景", "prop": "道具"}


def _make_label(kind, name):
    """生成参考图标签（用于提示词里的 <Picture i> 索引映射）。"""
    name = (name or "").strip()
    base = _KIND_LABEL.get(kind, kind)
    return f'{base}「{name}」参考图' if name else f"{base}参考图"


def _find_json(project_dir, subdir, obj_id):
    d = os.path.join(project_dir, subdir)
    if not os.path.isdir(d) or not obj_id:
        return None
    for f in os.listdir(d):
        if f.endswith(".json") and obj_id in f:
            return os.path.join(d, f)
    return None


def _load(path, cls):
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as cf:
            return cls.from_json(cf.read())
    except Exception:
        return None


def _first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return ""


def _panel_text(panel):
    """分镜里可用于兜底匹配场景/道具名称的文本。"""
    parts = []
    for key in ("description", "video_prompt"):
        val = panel.get(key) if isinstance(panel, dict) else getattr(panel, key, "")
        if isinstance(val, str) and val:
            parts.append(val)
    return "\n".join(parts)


def _match_from_library(project_dir, subdir, cls, text, limit=1):
    """面板未绑定场景/道具 ID 时，按资源库对象 name 在分镜文本中兜底匹配。"""
    d = os.path.join(project_dir, subdir)
    if not text or not os.path.isdir(d) or limit <= 0:
        return []
    found = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        obj = _load(os.path.join(d, f), cls)
        if not obj:
            continue
        name = (getattr(obj, "name", "") or "").strip()
        if len(name) < 2 or name not in text:
            continue
        found.append(obj)
        if len(found) >= limit:
            break
    return found


def collect_panel_ref_detail(project_dir, panel, max_refs=DEFAULT_MAX_REFS,
                             include_scene_prop=True):
    """收集面板参考图明细：返回 [{"path","kind","name","label"}]。

    顺序即上传/槽位顺序（角色 → 场景 → 道具），调用方据此把
    <Picture 1..N> 与参考图一一对应写入视频提示词。
    """
    try:
        max_refs = max(1, int(max_refs or DEFAULT_MAX_REFS))
    except (TypeError, ValueError):
        max_refs = DEFAULT_MAX_REFS

    def _get(name, default=None):
        if isinstance(panel, dict):
            return panel.get(name, default)
        return getattr(panel, name, default)

    detail = []

    def _add(path, kind, name):
        if path and os.path.isfile(path) and len(detail) < max_refs:
            if any(d["path"] == path for d in detail):
                return False
            detail.append({"path": path, "kind": kind, "name": name or "",
                           "label": _make_label(kind, name)})
            return True
        return False

    # 角色：单张正面图优先，拼图垫底。
    # 有场景/道具时要给它们预留槽位，否则多角色分镜会把场景图挤掉。
    max_char = max(1, max_refs - 2) if include_scene_prop else max_refs
    char_count = 0
    for char_id in (_get("characters", []) or []):
        if char_count >= max_char or len(detail) >= max_refs:
            break
        obj = _load(_find_json(project_dir, "characters", char_id), Character)
        if not obj:
            continue
        picked = _first_existing([
            getattr(obj, "front_view", "") or "",
            getattr(obj, "avatar_path", "") or "",
        ])
        if not picked:
            for r in (getattr(obj, "reference_images", None) or []):
                if r and os.path.isfile(r):
                    picked = r
                    break
        if not picked:
            picked = _first_existing([getattr(obj, "grid_1drag4_path", "") or ""])
        if _add(picked, "character", getattr(obj, "name", "")):
            char_count += 1

    # 场景：1 张（面板未绑定场景 ID 时，按场景名在分镜文本里兜底匹配）
    if include_scene_prop and len(detail) < max_refs:
        text = _panel_text(panel)
        scene_objs = []
        for scene_id in (_get("scenes", []) or []):
            scene = _load(_find_json(project_dir, "scenes", scene_id), Scene)
            if scene:
                scene_objs.append(scene)
            if len(scene_objs) >= 1:
                break
        if not scene_objs:
            scene_objs = _match_from_library(project_dir, "scenes", Scene, text, 1)
        for scene in scene_objs:
            ref = _first_existing([scene.close_view or "", scene.reference_image or ""])
            if ref and _add(ref, "scene", getattr(scene, "name", "")):
                break

    # 道具：1 张（同样支持按道具名兜底匹配）
    if include_scene_prop and len(detail) < max_refs:
        text = _panel_text(panel)
        prop_objs = []
        for prop_id in (_get("props", []) or []):
            prop = _load(_find_json(project_dir, "props", prop_id), Prop)
            if prop:
                prop_objs.append(prop)
            if len(prop_objs) >= 1:
                break
        if not prop_objs:
            prop_objs = _match_from_library(project_dir, "props", Prop, text, 1)
        for prop in prop_objs:
            ref = _first_existing([prop.front_view or "", prop.reference_image or ""])
            if ref and _add(ref, "prop", getattr(prop, "name", "")):
                break

    return detail


def collect_panel_refs(project_dir, panel, max_refs=DEFAULT_MAX_REFS,
                       include_scene_prop=True):
    """收集面板的参考图路径（角色 → 场景 → 道具）。

    panel 可以是 dict 或对象（取 characters/scenes/props 属性）。
    include_scene_prop=False 时只取角色图（保持"每镜 1 张角色图"的轻量模式）。
    返回：存在的图片路径列表（去重，长度 <= max_refs）。
    """
    return [d["path"] for d in collect_panel_ref_detail(
        project_dir, panel, max_refs=max_refs,
        include_scene_prop=include_scene_prop)]
