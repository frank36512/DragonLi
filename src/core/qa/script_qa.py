# -*- coding: utf-8 -*-
"""剧本语义 QA：LLM 出剧本后的结构性/连续性自检（与成片 QA 分离）。

error 项（触发带报告的自动重生成）：
1. 占位对白："无明确对白"类描述性文字（会被 TTS 直接朗读）
2. 时间倒流：time 序列回退（如 Night → Dusk），除非注明次日/闪回
3. 空镜：action 与 dialogue 均为空/占位

warning 项（记录不重试）：
4. 场景跳变但 continuity_note 未说明
5. 分镜数偏离目标 panel_count 过大
6. 跳剪风险：同场景相邻镜 景别+运镜 完全相同（提示词规则要求景别递进或拉开）
7. 弱开场：第 1 镜无角色出场且无对白，疑似空镜开场（黄金 3 秒要求最强冲突画面）
"""
import re

PLACEHOLDER_RE = re.compile(r"无(明确)?对白|无台词|无对话|没有台词|没有对白|（无）|\(无\)")

# 明确的时间跳跃标记：允许时间"回退"（其实是次日/新的一天/闪回）
_DAY_JUMP_RE = re.compile(r"次日|第二天|新的一天|数日后|几日后|多年后|next day|later|flashback|闪回|时间跳跃")

# 常见 time 取值 → 相对时刻（数值越大越晚）；未收录的值不参与比较
_TIME_ORDER = {
    "dawn": 1, "清晨": 1,
    "morning": 2, "上午": 2,
    "day": 3, "白天": 3,
    "noon": 3.5, "正午": 3.5,
    "afternoon": 4, "下午": 4,
    "evening": 5, "傍晚": 5,
    "dusk": 6, "黄昏": 6, "日落": 6,
    "night": 7, "夜晚": 7, "夜里": 7,
    "midnight": 8, "深夜": 8,
}


def _time_rank(value):
    if value is None:
        return None
    return _TIME_ORDER.get(str(value).strip().lower())


def _dialogue_text(d):
    """dialogue 可能是字符串或 [{role, content}] 列表，统一收敛为文本。"""
    if isinstance(d, str):
        return d
    if isinstance(d, (list, tuple)):
        parts = []
        for item in d:
            if isinstance(item, dict):
                parts.append(str(item.get("content", "") or ""))
            elif item:
                parts.append(str(item))
        return " | ".join(parts)
    if isinstance(d, dict):
        return str(d.get("content", "") or "")
    return str(d or "")


def _shots_of(script_data):
    if not isinstance(script_data, dict):
        return []
    shots = script_data.get("shots") or script_data.get("scenes") or []
    return [s for s in shots if isinstance(s, dict)]


def check_script(script_data, panel_count=None):
    """剧本语义 QA。返回 issues: list[{severity, code, message}]。"""
    issues = []
    if not isinstance(script_data, dict):
        return [{"severity": "error", "code": "structure",
                 "message": "剧本顶层不是 JSON 对象"}]
    shots = _shots_of(script_data)
    if not shots:
        return [{"severity": "error", "code": "empty",
                 "message": "剧本没有任何分镜（shots 为空）"}]

    prev_rank = None
    prev_time = ""
    prev_loc = ""
    prev_shot_type = ""
    prev_cam = ""
    for i, sh in enumerate(shots, 1):
        sid = sh.get("shot_id") or i
        action = str(sh.get("action") or "").strip()
        dial_raw = _dialogue_text(sh.get("dialogue"))

        # 1) 占位对白（整句或混合中的占位片段都会被 TTS 朗读）
        if PLACEHOLDER_RE.search(dial_raw):
            issues.append({
                "severity": "error", "code": "placeholder_dialogue",
                "message": f"镜头 {sid} 对白含占位文字（如'无明确对白'），会被 TTS 直接朗读；"
                           "无台词时应写'旁白: …'",
            })

        # 3) 空镜（剔除占位后动作与对白皆空）
        dial_clean = PLACEHOLDER_RE.sub("", dial_raw)
        dial_clean = re.sub(r"[\s|,，、]+", "", dial_clean)
        if not action and not dial_clean:
            issues.append({
                "severity": "error", "code": "empty_shot",
                "message": f"镜头 {sid} 动作与对白均为空（空镜），无法推进情节",
            })

        # 7) 弱开场（warning）：第 1 镜无角色出场且无对白，疑似空镜开场
        if i == 1:
            chars_field = sh.get("characters")
            has_chars = False
            if isinstance(chars_field, str) and chars_field.strip():
                has_chars = True
            elif isinstance(chars_field, (list, tuple)):
                has_chars = any(
                    isinstance(c, dict) and str(c.get("name") or "").strip()
                    for c in chars_field)
            if not has_chars and not dial_clean:
                issues.append({
                    "severity": "warning", "code": "weak_opening",
                    "message": f"镜头 {sid} 为第 1 镜但无角色出场且无对白，疑似空镜开场"
                               "（黄金 3 秒要求全集最强悬念/冲突画面）",
                })

        note = str(sh.get("continuity_note") or "")
        # 2) 时间倒流（注明次日/闪回则放行）
        time_val = sh.get("time")
        rank = _time_rank(time_val)
        if rank is not None:
            day_jump = bool(_DAY_JUMP_RE.search(note))
            if (prev_rank is not None and rank < prev_rank) and not day_jump:
                issues.append({
                    "severity": "error", "code": "time_regression",
                    "message": f"镜头 {sid} 时间「{time_val}」回退到上一镜「{prev_time}」之后"
                               "（时间线只能前进；若为次日请在 continuity_note 注明）",
                })
            if day_jump:
                # 新的一天：重置比较基线
                prev_rank = rank
                prev_time = time_val
            elif rank >= (prev_rank if prev_rank is not None else rank):
                prev_rank = rank
                prev_time = time_val

        # 4) 场景跳变未说明（warning）
        loc = str(sh.get("scene_location") or sh.get("location") or "").strip()
        if prev_loc and loc and loc != prev_loc:
            if not note or not any(
                    k in note for k in ("场景", "切换", "转场", "到达", "进入",
                                        "离开", "新场景", "时间跳", "cut")):
                issues.append({
                    "severity": "warning", "code": "location_jump",
                    "message": f"镜头 {sid} 场景从「{prev_loc}」跳到「{loc}」，"
                               "但 continuity_note 未说明切换方式",
                })

        # 6) 跳剪风险（warning）：同场景相邻镜 景别+运镜 完全相同
        shot_type = str(sh.get("shot_type") or "").strip()
        cam = str(sh.get("camera_movement") or "").strip()
        if (prev_loc and loc and loc == prev_loc
                and prev_shot_type and shot_type == prev_shot_type
                and prev_cam and cam == prev_cam):
            issues.append({
                "severity": "warning", "code": "jump_cut",
                "message": f"镜头 {sid} 与上一镜同场景且景别/运镜完全相同"
                           "（{shot_type}+{cam}），产生跳剪感；"
                           "同场景相邻镜应景别递进或拉开、运镜错开",
            })
        if shot_type:
            prev_shot_type = shot_type
        if cam:
            prev_cam = cam
        if loc:
            prev_loc = loc

    # 5) 镜数偏离目标（warning）
    if panel_count:
        tolerance = max(2, int(panel_count) // 2)
        if abs(len(shots) - int(panel_count)) > tolerance:
            issues.append({
                "severity": "warning", "code": "shot_count",
                "message": f"分镜数 {len(shots)} 与目标 {panel_count} 偏离过大",
            })
    return issues


def auto_fix_script(script_data):
    """可自动修复项：剔除 dialogue 字符串中的占位片段。返回是否有修改。"""
    changed = False
    for sh in _shots_of(script_data):
        d = sh.get("dialogue")
        if isinstance(d, str) and PLACEHOLDER_RE.search(d):
            parts = [p.strip() for p in d.split("|")]
            kept = [p for p in parts if p and not PLACEHOLDER_RE.search(p)]
            sh["dialogue"] = " | ".join(kept)
            changed = True
    return changed


def format_errors(issues):
    """把 error 项拼成给 LLM 的修复反馈文本。"""
    errs = [i for i in (issues or []) if i.get("severity") == "error"]
    return "\n".join("- %s" % i["message"] for i in errs)


def error_count(issues):
    return len([i for i in (issues or []) if i.get("severity") == "error"])
