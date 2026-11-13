import re
from typing import List, Dict, Optional
from core.storyboard.storyboard_model import Panel, VideoPromptSegment


def _split_timeline(duration: float):
    """把时长切成 3-6 个秒级分段，返回 [(start, end), ...]。"""
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = 8.0
    if duration <= 0:
        duration = 8.0
    if duration < 7:
        n = 3
    elif duration < 11:
        n = 4
    elif duration < 13:
        n = 5
    else:
        n = 6
    step = duration / n
    bounds = [round(step * i, 1) for i in range(n + 1)]
    bounds[0] = 0.0
    bounds[-1] = round(duration, 1)
    return list(zip(bounds[:-1], bounds[1:]))


def _fmt(value):
    """数字显示：整数不带小数点，小数保留一位。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{int(v)}" if v.is_integer() else f"{v:.1f}"


def _format_subject_list(value, max_detail=2):
    """把角色/道具字段规范成简短可读文本。

    新版剧本 schema 里 characters 是结构化列表：
        [{"name": "康斯坦丝", "pose": "走", "expression": "兴奋明亮", ...}]
    直接 f-string 会把 Python 字典原文塞进提示词（又长又噪），
    而提示词要交给 32B 的 qwen3vl 编码器逐 token 处理，长度直接吃生成时间。
    这里统一成「名字（姿态，表情）」的紧凑写法。
    """
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return str(value)
    parts = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("character")
                       or item.get("id") or "").strip()
            if not name:
                continue
            detail = []
            for key in ("pose", "expression", "emotional_state",
                        "clothing_note", "position"):
                v = str(item.get(key) or "").strip()
                if not v or v == "同前":
                    continue
                detail.append(v)
                if len(detail) >= max_detail:
                    break
            parts.append(f"{name}（{'，'.join(detail)}）" if detail else name)
        elif item:
            parts.append(str(item).strip())
    return "、".join(p for p in parts if p)


def _drop_section(text, head):
    """删除以 head 开头的那一段（到下一个段落标记或文末）。"""
    i = text.find(head)
    if i == -1:
        return text
    j = text.find("【", i + len(head))
    if j == -1:
        return text[:i]
    return text[:i] + text[j:]


def compact_video_prompt(text):
    """压缩 LLM 自写的六段式长提示词。

    只砍"样板"内容，**保留【分镜时间轴】里的创意画面描述**（最有价值的部分）：
    - 【参考图描述】【参考图一致性约束】【质量要求】【运镜设计】每镜几乎一模一样，
      由系统重新生成更划算；
    - 角色/道具的 Python 字典原文换成紧凑文本。
    """
    if not text:
        return text
    s = text
    # 1) 角色/道具字典原文 → 紧凑文本
    try:
        import ast
        def _rep(m):
            raw = m.group(0)
            try:
                val = ast.literal_eval(raw)
            except Exception:
                return raw
            return _format_subject_list(val) or raw
        s = re.sub(r"\[\s*(\{[^{}]*\}\s*(?:,\s*\{[^{}]*\}\s*)*)\]", _rep, s)
    except Exception:
        pass
    # 2) 去掉样板段落（时间轴与基础信息保留）
    for head in ("【参考图描述】", "【参考图一致性约束】", "【质量要求】", "【运镜设计】"):
        s = _drop_section(s, head)
    # 3) 压缩多余空行
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def construct_video_prompt(
    panel: Optional[Panel] = None,
    video_params: Optional[Dict] = None,
    dialogue_text: str = "",
    dialogue_role: str = "",
    duration: float = 8.0,
    ref_image_count: int = 0,
    is_first: bool = True,
    is_last: bool = True,
    prev_action: str = "",
    prev_state: str = "",
    tone: str = "",
    pace: str = "",
    emotional_state: str = "",
    body_action: str = "",
    same_scene_as_prev: bool = True
) -> str:
    """构建视频提示词（基于角色/场景/道具参考图）。

    输出六个段落：【参考图描述】【视频基础信息】【分镜时间轴】【运镜设计】
    【参考图一致性约束】【质量要求】。分镜时间轴按秒级切成 3-6 段，
    每段含画面/对白/运镜/音效/情绪。

    镜位化（连续性）：is_first/is_last 标记本镜在全片中的位置。
    非首镜首段不再"建立画面"而是承接上一镜（prev_action 的下一拍）；
    非末镜末段保持动作进行中直接切出（不淡出不停格），仅末镜保留淡出收束。
    prev_state：上一镜角色状态摘要（衣着/情绪/姿态变化），写入"状态承接"行，
    防止湿透/受伤/弄脏等状态在下一镜凭空恢复。
    same_scene_as_prev：本镜与上一镜是否同场景。False（换场）时首段改为
    "换场建立画面"——跨场景强行接戏会让图生视频把无关场景硬性渐变出怪异画面，
    换场镜需重新建立空间，仅保持剧情时间线与角色状态连续。
    """
    if video_params is None:
        video_params = {}
    lines = []
    if panel and panel.video_prompt:
        return panel.video_prompt

    scene_desc = video_params.get('scene_description', '') or ''
    if not scene_desc and panel and panel.description:
        scene_desc = panel.description

    chars = _format_subject_list(video_params.get('characters', ''))
    action = _format_subject_list(video_params.get('action', ''), max_detail=1)
    props = _format_subject_list(video_params.get('props', ''))
    atmosphere = video_params.get('atmosphere', '')
    scene_location = video_params.get('scene_location', '')
    shot_type = video_params.get('shot_type', '') or '中景'
    camera_movement = video_params.get('camera_movement', '') or '缓慢推近'

    # 【参考图描述】
    lines.append("【参考图描述】")
    if ref_image_count > 0:
        lines.append(f"共{ref_image_count}张参考图。")
    ref_desc_parts = []
    if chars:
        ref_desc_parts.append(f"角色参考图：{chars}")
    if props:
        ref_desc_parts.append(f"道具参考图：{props}")
    if scene_location or scene_desc:
        ref_desc_parts.append(f"场景参考图：{scene_location or scene_desc}")
    if ref_desc_parts:
        lines.append("；".join(ref_desc_parts))
    elif ref_image_count == 0:
        lines.append("无参考图，按以下文本描述生成。")
    lines.append("")

    # 【视频基础信息】
    lines.append("【视频基础信息】")
    if prev_state and not is_first:
        lines.append(f"- 状态承接：{prev_state}"
                     "（服装/情绪/姿态与上一镜保持连续，禁止湿透后变干爽、受伤后凭空痊愈等状态重置）")
    if chars:
        lines.append(f"画面主体：{chars}")
    if scene_desc:
        lines.append(f"场景环境：{scene_desc}")
    if atmosphere:
        lines.append(f"光影氛围：{atmosphere}")
    lines.append(f"运镜基调：{camera_movement}")
    lines.append(f"情绪基调：{atmosphere or '自然'}")
    lines.append("参考图类型：角色/场景/道具参考图" if ref_image_count > 0 else "参考图类型：无")
    lines.append(f"视频时长：{_fmt(duration)}秒")
    lines.append("")

    # 【分镜时间轴】秒级细分为 3-6 段
    seg_parts = []
    if scene_desc:
        seg_parts.append(scene_desc)
    if chars and action:
        seg_parts.append(f"{chars}正在{action}")
    elif chars:
        seg_parts.append(chars)
    elif action:
        seg_parts.append(action)
    seg_summary = "，".join(seg_parts) if seg_parts else "核心画面"

    if dialogue_text:
        # H3 原生语音五要素结构化对白（Experience 2215960）：
        # 说什么(dialogue_text) / 语调(tone) / 语速(pace) / 情绪(emotional_state) / 动作绑定(body_action)
        _act_bits = []
        if tone:
            _act_bits.append(f"语调{tone}")
        if pace:
            _act_bits.append(f"语速{pace}")
        if emotional_state:
            _act_bits.append(f"情绪{emotional_state}")
        if body_action:
            _act_bits.append(f"动作绑定{body_action}")
        _act_str = "；".join(_act_bits)
        _h3_audio_core = "中文口播，吐字清楚，发音标准，声音干净无杂音无回声"
        if _act_str:
            _h3_audio = f"{_h3_audio_core}。{_act_str}。"
        else:
            _h3_audio = f"{_h3_audio_core}。"
        if dialogue_role:
            dialogue_line = (
                f"- 人声（该内容只作为音轨人声说出，画面中不得出现对应文字、"
                f"字幕条或任何字符形态）：{dialogue_role}以自然口型说话\n"
                f"- 音轨语音：{_h3_audio}\n"
                f"- 语音内容（仅音频，勿绘制为文字）：{dialogue_text}")
        else:
            dialogue_line = (
                f"- 人声（该内容只作为音轨人声说出，画面中不得出现对应文字、"
                f"字幕条或任何字符形态）：以自然口型说话\n"
                f"- 音轨语音：{_h3_audio}\n"
                f"- 语音内容（仅音频，勿绘制为文字）：{dialogue_text}")
    else:
        dialogue_line = "- 对白：（无）"

    segs = _split_timeline(duration)
    n = len(segs)
    dialogue_idx = 1 if n > 1 else 0

    lines.append("【分镜时间轴】")
    # prev_action 可能是 LLM 返回的 list/dict（JSON 无类型约束），统一收敛为文本
    if isinstance(prev_action, str):
        _prev = prev_action.strip()
    elif isinstance(prev_action, (list, tuple)):
        _prev = "；".join(str(x).strip() for x in prev_action if x)
    elif isinstance(prev_action, dict):
        _prev = str(prev_action.get("action") or "").strip()
    else:
        _prev = str(prev_action).strip() if prev_action else ""
    _prev = _prev or "上一镜的收尾动作"
    for idx, (start, end) in enumerate(segs):
        if idx == 0:
            if is_first:
                visual = f"建立画面，展现{seg_summary}，交代环境和空间关系，建立视觉焦点"
                cam = f"起幅：{camera_movement}（{shot_type}），建立空间关系"
                audio = "背景音乐渐入，环境音"
                emo = "氛围建立"
            elif not same_scene_as_prev:
                # 换场镜头：跨场景强接戏会让图生视频把无关场景硬性渐变出怪异画面，
                # 必须重新建立空间，仅保持剧情时间线与角色状态连续
                visual = (f"换场建立画面：展现新场景——{seg_summary}，交代新环境的空间关系"
                          "与光线氛围，快速建立视觉焦点（本镜为换场后的新场景开场，"
                          "无需延续上一镜的构图与机位）")
                cam = f"换场起幅：{camera_movement}（{shot_type}），建立新场景空间关系"
                audio = "新场景环境音建立，背景音乐延续剧情情绪"
                emo = "氛围重建，情绪延续剧情"
            else:
                visual = f"承接上一镜继续：从（{_prev}）的下一拍自然进入{seg_summary}，不重新建立空间、不重新起镜、不重复交代环境"
                cam = f"接戏起幅：延续上一镜的机位与景别（{shot_type}），画面直接进入动作"
                audio = "音乐与环境音延续，无渐入"
                emo = "承接上镜情绪"
        elif idx == n - 1:
            if is_last:
                visual = f"收尾，镜头停留在{chars or '主体'}的细节或表情上，然后淡出或过渡"
                cam = f"落幅：停留后淡出（{shot_type}）"
                audio = "音乐渐弱，自然过渡"
                emo = "余韵收束"
            else:
                visual = f"动作进行中收尾：{seg_summary}（保持动势，直接切入下一镜，禁止淡出、黑场或停格）"
                cam = f"落幅：动作未完即切（{shot_type}），保持动势"
                audio = "音乐与环境音持续（不淡出）"
                emo = "余韵保持"
        elif idx == 1:
            visual = f"聚焦{seg_summary}，展现动作细节和表情变化"
            cam = f"{camera_movement}，景别保持{shot_type}"
            audio = "音乐持续，环境音"
            emo = "情绪递进"
        else:
            visual = f"推进{seg_summary}，呈现情绪变化与动作重点"
            cam = f"{camera_movement}，景别保持{shot_type}"
            audio = "音乐持续，环境音"
            emo = "情绪加深"

        lines.append(f"第{_fmt(start)}-{_fmt(end)}秒：")
        lines.append(f"- 画面：{visual}")
        if dialogue_text and idx == dialogue_idx:
            lines.append(dialogue_line)
        else:
            lines.append("- 对白：（无）")
        lines.append(f"- 运镜：{cam}")
        lines.append(f"- 音效：{audio}")
        lines.append(f"- 情绪：{emo}")
        lines.append("")

    # 【运镜设计】
    lines.append("【运镜设计】")
    lines.append(f"- 景别：{shot_type}起幅 → {shot_type}落幅")
    if is_last:
        lines.append(f"- 运镜：{camera_movement} → 停留 → 淡出")
        lines.append("- 转场衔接：镜头停留在主体细节后淡出，结束全片")
    else:
        lines.append(f"- 运镜：{camera_movement} → 保持动势")
        if not is_first and not same_scene_as_prev:
            lines.append("- 转场衔接：硬切换场，本镜以新场景建立镜头开场"
                         "（剧情时间线与角色状态保持连续，构图机位重新建立）；"
                         "结尾保持动作进行中直接切入下一镜（不淡出、不停格）")
        else:
            lines.append(f"- 转场衔接：起幅承接上一镜（{_prev}），结尾保持动作进行中直接切入下一镜（不淡出、不停格）")
    lines.append("")

    # 【参考图一致性约束】
    lines.append("【参考图一致性约束】")
    lines.append("- 角色一致性：角色脸部特征、发型、服装、配饰必须与角色参考图完全一致，禁止变形、换脸、服装突变")
    lines.append("- 场景一致性：场景布局、建筑结构、光照色调必须与场景参考图一致，禁止场景漂移或凭空新增元素")
    lines.append("- 道具一致性：道具的材质、颜色、形状、位置必须与道具参考图一致，禁止道具消失、变形或突变")
    lines.append("- 全程画面禁止出现任何文字、字幕、标语、水印"
                 "（no subtitles, no captions, no on-screen text, no text overlay,"
                 " no typography, no signs, no watermark, no logo）")
    lines.append("- 画面底部禁止出现字幕条/对白文字条，台词只允许存在于音轨，"
                 "不得以任何字符形态出现在画面上")
    lines.append("")

    # 【质量要求】
    lines.append("【质量要求】")
    lines.append("- 画面稳定，无抖动")
    lines.append("- 运动流畅自然")
    lines.append("- 与参考图视觉风格一致")
    lines.append("- 电影级画质")
    lines.append("- 无变形、无鬼影、无闪烁")
    lines.append("- 语音清晰、吐字清楚、发音标准、语速自然、声音干净无杂音无回声")

    return "\n".join(lines)


def parse_video_prompt_to_segments(prompt: str, duration: Optional[float] = None) -> List[VideoPromptSegment]:
    segments = []
    current_segment = None
    lines = prompt.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        time_match = re.search(r'第([\d.]+)-([\d.]+)秒：', line)
        if time_match:
            if current_segment:
                segments.append(current_segment)
            start_time = float(time_match.group(1))
            end_time = float(time_match.group(2))
            current_segment = VideoPromptSegment(
                start_time=start_time,
                end_time=end_time,
                description="",
                dialogue="",
                camera_movement="",
                sound_effect=""
            )
        elif current_segment:
            if line.startswith('- 画面：'):
                current_segment.description = line.replace('- 画面：', '').strip()
            elif line.startswith('- 对白：'):
                current_segment.dialogue = line.replace('- 对白：', '').strip()
            elif line.startswith('- 运镜：'):
                current_segment.camera_movement = line.replace('- 运镜：', '').strip()
            elif line.startswith('- 音效：'):
                current_segment.sound_effect = line.replace('- 音效：', '').strip()
            elif line.startswith('- 情绪：'):
                # 兼容旧格式：无"情绪"行时不报错
                current_segment.emotion = line.replace('- 情绪：', '').strip()
    if current_segment:
        segments.append(current_segment)
    return segments


def format_segments_to_video_prompt(segments: List[VideoPromptSegment]) -> str:
    lines = ["【分镜时间轴】"]
    for seg in segments:
        lines.append(f"第{seg.start_time:.1f}-{seg.end_time:.1f}秒：")
        lines.append(f"- 画面：{seg.description}")
        if seg.dialogue:
            lines.append(f"- 对白：{seg.dialogue}")
        else:
            lines.append("- 对白：（无）")
        lines.append(f"- 运镜：{seg.camera_movement}")
        lines.append(f"- 音效：{seg.sound_effect}")
        if seg.emotion:
            lines.append(f"- 情绪：{seg.emotion}")
        lines.append("")
    return "\n".join(lines)


def generate_default_video_segments(duration: float = 8.0, panel: Optional[Panel] = None) -> List[VideoPromptSegment]:
    """生成默认的视频分段：秒级 3-6 段，每段含画面/运镜/音效/情绪。"""
    segs = _split_timeline(duration)
    n = len(segs)
    base_desc = panel.description if panel is not None else ""
    segments = []
    for idx, (start, end) in enumerate(segs):
        if idx == 0:
            desc = f"建立画面，展现{base_desc or '核心画面'}"
            cam = "起幅：固定镜头，缓慢推近"
            sfx = "背景音乐渐入，环境音"
            emo = "氛围建立"
        elif idx == n - 1:
            desc = "收尾，镜头停留后淡出或过渡"
            cam = "落幅：停留后淡出"
            sfx = "音乐渐弱，自然过渡"
            emo = "余韵收束"
        elif idx == 1:
            desc = f"聚焦{base_desc or '核心画面'}，展现动作细节和表情变化"
            cam = "平滑推近，景别保持中景"
            sfx = "音乐持续，环境音"
            emo = "情绪递进"
        else:
            desc = "推进动作重点，呈现情绪变化"
            cam = "平滑推近，景别保持中景"
            sfx = "音乐持续，环境音"
            emo = "情绪加深"
        segments.append(VideoPromptSegment(
            start_time=start,
            end_time=end,
            description=desc,
            dialogue="",
            camera_movement=cam,
            sound_effect=sfx,
            emotion=emo,
        ))
    return segments
