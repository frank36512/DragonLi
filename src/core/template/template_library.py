# -*- coding: utf-8 -*-
"""剧本模板库：预置套路结构 + 自定义模板管理。

模板 JSON 结构：
{
  "key": "rebirth",
  "name": "逆袭重生",
  "genre": "都市逆袭",
  "description": "一句话简介",
  "prompt": "完整的故事创意提示词（填入 AI 生成输入框）",
  "characters": ["主角（重生者）", "反派", ...],
  "beats": ["开局落魄", "重生/金手指", "初次反击", ...]
}
"""
import os
import json

try:
    from core.utils.json_store import atomic_write_json
except ImportError:
    try:
        from src.core.utils.json_store import atomic_write_json
    except ImportError:
        atomic_write_json = None


class TemplateLibrary:
    """模板目录扫描 + 读取。templates_dir 默认 resources/templates。"""

    def __init__(self, templates_dir=None):
        if templates_dir is None:
            # 优先用 get_executable_dir（PyInstaller 兼容）
            try:
                from main import get_executable_dir
                base = get_executable_dir()
                cand = os.path.join(base, "resources", "templates")
                if os.path.isdir(cand):
                    templates_dir = cand
            except Exception:
                pass
            if templates_dir is None:
                # 回退：<项目根>/resources/templates
                base = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)))))
                templates_dir = os.path.join(base, "resources", "templates")
        self.templates_dir = templates_dir

    def list_templates(self):
        """扫描目录，返回模板 dict 列表（按 name 排序）。损坏文件跳过。"""
        templates = []
        if not os.path.isdir(self.templates_dir):
            return templates
        for fn in sorted(os.listdir(self.templates_dir)):
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(self.templates_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("name"):
                    data.setdefault("key", os.path.splitext(fn)[0])
                    data.setdefault("prompt", "")
                    data.setdefault("description", "")
                    data.setdefault("genre", "")
                    data.setdefault("characters", [])
                    data.setdefault("beats", [])
                    templates.append(data)
            except Exception as e:
                print(f"[TemplateLibrary] 跳过损坏模板 {fn}: {e}")
        templates.sort(key=lambda t: t.get("name", ""))
        return templates

    def get(self, key):
        """按 key（文件名去后缀）取模板，找不到返回 None。"""
        for t in self.list_templates():
            if t.get("key") == key:
                return t
        return None

    def save_template(self, data):
        """保存/覆盖自定义模板（原子写盘）。返回文件路径。"""
        os.makedirs(self.templates_dir, exist_ok=True)
        key = data.get("key") or f"custom_{len(self.list_templates()) + 1}"
        # key 只留安全字符
        safe = "".join(c for c in key if c.isalnum() or c in "-_") or "template"
        data["key"] = safe
        path = os.path.join(self.templates_dir, f"{safe}.json")
        if atomic_write_json is not None:
            atomic_write_json(path, data)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def build_prompt(self, tpl, topic=""):
        """把模板结构拼成完整生成提示词；topic 优先于模板默认主题。"""
        lines = []
        theme = (topic or "").strip()
        if theme:
            lines.append(f"主题：{theme}")
        elif tpl.get("description"):
            lines.append(f"主题：{tpl['description']}")
        if tpl.get("genre"):
            lines.append(f"类型：{tpl['genre']}")
        beats = tpl.get("beats") or []
        if beats:
            lines.append("剧情节拍（按顺序展开）：")
            for i, b in enumerate(beats, 1):
                lines.append(f"{i}. {b}")
        chars = tpl.get("characters") or []
        if chars:
            lines.append(f"主要角色：{'、'.join(chars)}")
        if tpl.get("prompt"):
            lines.append("")
            lines.append(tpl["prompt"])
        return "\n".join(lines).strip()
