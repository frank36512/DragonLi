# -*- coding: utf-8 -*-
"""
分镜构建服务：剧本 Script -> 分镜 Storyboard 的纯规则转换。
供全自动编排器与视频编辑器共用，不依赖 Qt，不做任何 UI 交互；输入输出均为 core 模型对象。
"""
import os
import re

try:
    from core.script.script_model import Dialogue
    from core.character.character_model import Character
    from core.scene.scene_model import Scene
    from core.prop.prop_model import Prop
    from core.storyboard.storyboard_model import Storyboard, Panel
    from core.storyboard.prompt_factory import (
        construct_video_prompt, parse_video_prompt_to_segments, generate_default_video_segments,
        compact_video_prompt
    )
    from core.consistency.anchor_model import AnchorTable
except ImportError:
    from src.core.script.script_model import Dialogue
    from src.core.character.character_model import Character
    from src.core.scene.scene_model import Scene
    from src.core.prop.prop_model import Prop
    from src.core.storyboard.storyboard_model import Storyboard, Panel
    from core.storyboard.prompt_factory import (
        construct_video_prompt, parse_video_prompt_to_segments, generate_default_video_segments,
        compact_video_prompt
    )
    from src.core.consistency.anchor_model import AnchorTable


def load_character_map(project_dir):
    """读取项目级与全局库角色，返回 {name: Character}，项目级优先。"""
    char_map = {}
    try:
        if not project_dir:
            return char_map

        # Load project-specific characters first (take precedence)
        project_char_dir = os.path.join(project_dir, "characters")
        if os.path.exists(project_char_dir):
            for f in os.listdir(project_char_dir):
                if f.endswith(".json"):
                    with open(os.path.join(project_char_dir, f), 'r', encoding='utf-8') as file:
                        c = Character.from_json(file.read())
                        char_map[c.name] = c

        # Also load global library characters (lower priority)
        resources_dir = os.path.dirname(os.path.dirname(project_dir))
        global_char_dir = os.path.join(resources_dir, "characters")
        if global_char_dir != project_char_dir and os.path.exists(global_char_dir):
            for root, dirs, files in os.walk(global_char_dir):
                for file in files:
                    if file.endswith(".json"):
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            c = Character.from_json(f.read())
                            if c.name not in char_map:
                                char_map[c.name] = c
    except Exception as e:
        print(f"Error loading characters: {e}")
    return char_map


def load_scene_map(project_dir):
    """读取项目级与全局库场景，返回 {name: Scene}，项目级优先。"""
    scene_map = {}
    try:
        if not project_dir:
            return scene_map

        # 项目级场景优先
        project_scene_dir = os.path.join(project_dir, "scenes")
        if os.path.exists(project_scene_dir):
            for f in os.listdir(project_scene_dir):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(project_scene_dir, f), 'r', encoding='utf-8') as file:
                            s = Scene.from_json(file.read())
                            scene_map[s.name] = s
                    except Exception as e:
                        print(f"Error loading scene {f}: {e}")

        # 全局库场景（低优先级）
        resources_dir = os.path.dirname(os.path.dirname(project_dir))
        global_scene_dir = os.path.join(resources_dir, "scenes")
        if global_scene_dir != project_scene_dir and os.path.exists(global_scene_dir):
            for root, dirs, files in os.walk(global_scene_dir):
                for file in files:
                    if file.endswith(".json"):
                        try:
                            with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                                s = Scene.from_json(f.read())
                                if s.name not in scene_map:
                                    scene_map[s.name] = s
                        except Exception as e:
                            print(f"Error loading global scene {file}: {e}")
    except Exception as e:
        print(f"Error loading scenes: {e}")
    return scene_map


def load_prop_map(project_dir):
    """读取项目级与全局库道具，返回 {name: Prop}，项目级优先。"""
    prop_map = {}
    try:
        if not project_dir:
            return prop_map
        project_prop_dir = os.path.join(project_dir, "props")
        if os.path.exists(project_prop_dir):
            for f in os.listdir(project_prop_dir):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(project_prop_dir, f), 'r', encoding='utf-8') as file:
                            p = Prop.from_json(file.read())
                            prop_map[p.name] = p
                    except Exception as e:
                        print(f"Error loading prop {f}: {e}")
        resources_dir = os.path.dirname(os.path.dirname(project_dir))
        global_prop_dir = os.path.join(resources_dir, "props")
        if global_prop_dir != project_prop_dir and os.path.exists(global_prop_dir):
            for root, dirs, files in os.walk(global_prop_dir):
                for file in files:
                    if file.endswith(".json"):
                        try:
                            with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                                p = Prop.from_json(f.read())
                                if p.name not in prop_map:
                                    prop_map[p.name] = p
                        except Exception as e:
                            print(f"Error loading global prop {file}: {e}")
    except Exception as e:
        print(f"Error loading props: {e}")
    return prop_map


def _match_ids_by_text(text, name_map, max_ids=3):
    """把自由文本（场景名/道具描述）匹配到资源库里的对象 ID。

    用于给分镜回填 scene/prop 绑定——此前 panel.scenes / panel.props 恒为空，
    导致场景图、道具图永远取不到（角色图之外的参考图全部失效）。
    """
    if not text or not name_map:
        return []
    if isinstance(text, (list, tuple)):
        parts = [str(x) for x in text if str(x).strip()]
    else:
        parts = [p for p in re.split(r"[，,、;；\n]+", str(text)) if p.strip()]
    ids = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        hit = None
        for name, obj in name_map.items():
            if not name:
                continue
            if name == part or name in part:
                hit = obj.id
                break
        if not hit:
            # 兜底：名称较长时按包含匹配（避免"手提箱"被"棕色手提箱"漏掉）
            for name, obj in name_map.items():
                if name and len(name) >= 2 and name in part:
                    hit = obj.id
                    break
        if hit and hit not in ids:
            ids.append(hit)
        if len(ids) >= max_ids:
            break
    return ids


def _char_state_text(scene, max_chars=3):
    """从 characters_detail 提取衣着/情绪/姿态摘要，供"状态承接"行使用。

    湿透/受伤/弄脏/情绪剧变这类状态必须跨镜延续——只传动作时，
    下一镜的角色参考图（干净衣着）会把状态重置回去。
    """
    details = getattr(scene, "characters_detail", None) or []
    parts = []
    for c in details:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        bits = []
        for key, label in (("clothing_note", "衣着"), ("emotional_state", "情绪"), ("pose", "姿态")):
            v = c.get(key)
            if v and str(v).strip():
                bits.append(f"{label}{str(v).strip()}")
        if bits:
            parts.append(f"{c['name']}（{'、'.join(bits)}）")
        if len(parts) >= max_chars:
            break
    return "；".join(parts)


def load_anchor_table(project_dir):
    """加载项目锚点表；失败返回空表（降级纯提示词）。"""
    try:
        if not project_dir:
            return AnchorTable()
        return AnchorTable.load(project_dir)
    except Exception as e:
        print(f"Error loading anchor table: {e}")
        return AnchorTable()


def _parse_dialogues(script):
    """
    确保 script 各 scene 的 dialogues 列表可用：
    dict 转 Dialogue、dialogue 字符串解析、空对白兜底为场景描述。
    （与原 generate_panels 行为一致，直接在 Script 对象上原地修补。）
    """
    for scene in script.scenes:
        # Initialize dialogues list if None
        if scene.dialogues is None:
            scene.dialogues = []

        # First convert any existing dict items to Dialogue objects
        if scene.dialogues:
            converted = []
            for d in scene.dialogues:
                if isinstance(d, dict):
                    converted.append(Dialogue(
                        role=d.get('role', ''),
                        content=d.get('content', ''),
                        action=d.get('action', ''),
                        expression=d.get('expression', '')
                    ))
                else:
                    converted.append(d)
            scene.dialogues = converted

        # Parse dialogue string to create Dialogue objects if dialogues is still empty
        if not scene.dialogues and scene.dialogue:
            # 确保 dialogue 是字符串
            if isinstance(scene.dialogue, list):
                # 如果是列表，先转换为字符串
                dialogue_parts = []
                for d in scene.dialogue:
                    if isinstance(d, dict):
                        role = d.get('role', '')
                        content = d.get('content', '')
                        action = d.get('action', '')
                        if role and content:
                            if action:
                                dialogue_parts.append(f"{role}: {content} ({action})")
                            else:
                                dialogue_parts.append(f"{role}: {content}")
                scene.dialogue = " | ".join(dialogue_parts)

            if isinstance(scene.dialogue, str) and scene.dialogue:
                # Parse dialogue string to create Dialogue objects
                # 格式要求 "角色名: [语调=...] [语速=...] [情绪=...] 台词 (action)"
                # 标签前缀可选，action 后缀也可选
                _TAG_RE = re.compile(r'\[([^\]=]+)=([^\]]+)\]')
                for part in scene.dialogue.split("|"):
                    part = part.strip()
                    if not part:
                        continue
                    match = re.match(r'([^:]+):\s*(.+?)(?:\s*\(([^)]+)\))?$', part)
                    if match:
                        role = match.group(1).strip()
                        raw_content = match.group(2).strip()
                        action = match.group(3).strip() if match.group(3) else ""
                        # 提取并移除 [key=value] 标签
                        extracted_tags = {}
                        def _tag_sub(m):
                            extracted_tags[m.group(1).strip()] = m.group(2).strip()
                            return ""
                        clean_content = _TAG_RE.sub(_tag_sub, raw_content).strip()
                        # 进一步清洗：移除括号内的情绪/动作描述、字幕标记
                        clean_content = re.sub(r'[（(【\[][^)）】\]]*[)）】\]]', '', clean_content).strip()
                        clean_content = re.sub(r'（[^）]*[字标][幕题][：:][^）]*）', '', clean_content).strip()
                        clean_content = re.sub(r'\([^()]*[字标][幕题][：:][^()]*\)', '', clean_content).strip()
                        tone = extracted_tags.get("语调", "")
                        pace = extracted_tags.get("语速", "")
                        emotion = extracted_tags.get("情绪", "")
                        scene.dialogues.append(Dialogue(
                            role=role, content=clean_content or raw_content,
                            action=action, tone=tone, pace=pace, emotion=emotion))
                    else:
                        # "无明确对白"类占位描述：直接丢弃——此前会被当旁白喂给
                        # TTS，结果全片把"无明确对白"朗读出来；真正有信息量的
                        # 叙述性文字（无冒号格式）仍作旁白兜底，避免全片静默
                        if re.search(r"无(明确)?对白|无台词|无对话|没有台词|没有对白"
                                     r"|（无）|\(无\)", part):
                            continue
                        scene.dialogues.append(Dialogue(
                            role="旁白", content=part, action="", expression=""))

        # If still no dialogues, create a default one from scene description
        if not scene.dialogues:
            scene.dialogues.append(Dialogue(
                role="场景",
                content=scene.description or "",
                action=scene.description or "",
                expression=""
            ))


def _group_dialogues_into_shots(script):
    """按动作关键词/长度对对白分组合并成镜头组，返回 [(scene, [dialogue, ...]), ...]。"""
    grouped_shots = []

    for scene in script.scenes:
        if not scene.dialogues:
            continue

        current_group = []

        for dialogue in scene.dialogues:
            # Handle both dict and Dialogue object
            if isinstance(dialogue, dict):
                continue  # Skip dicts, they weren't parsed properly

            if not current_group:
                current_group.append(dialogue)
                continue

            # 简化逻辑：默认合并，只在有明显变化时才分镜
            # 更激进的合并策略
            dialogue_action = getattr(dialogue, 'action', '') or ''
            dialogue_content = getattr(dialogue, 'content', '') or ''

            # 关键动作词 - 只有这些才分镜
            key_action_keywords = ['走出', '走进', '冲出', '跑出', '飞出', '跳入', '倒入',
                                   '拿起', '放下', '打开', '关闭', '推开门', '拉开门',
                                   '转身', '回头', '倒地', '跪下', '站起来', '坐下来']

            has_key_action = any(kw in dialogue_action for kw in key_action_keywords)
            has_long_action = len(dialogue_action) > 30

            # 只有满足以下条件才分镜：
            # 1. 有关键动作词 + 动作较长
            # 2. 动作特别长（>40字）
            if has_key_action and has_long_action:
                grouped_shots.append((scene, current_group))
                current_group = [dialogue]
            elif len(dialogue_action) > 40:
                grouped_shots.append((scene, current_group))
                current_group = [dialogue]
            else:
                current_group.append(dialogue)

        if current_group:
            grouped_shots.append((scene, current_group))

    return grouped_shots


def build_storyboard_from_script(script, char_map, script_title, anchor_table=None,
                                 scene_map=None, prop_map=None):
    """
    将剧本规则化转换为分镜（纯规则，无 LLM、无 UI 依赖）。
    参数:
        script: core.script.script_model.Script
        char_map: {角色名: Character}，来自 load_character_map
        script_title: 分镜标题
        anchor_table: 可选，一致性锚点表 AnchorTable；传入则查表填 panel._anchors
    返回:
        Storyboard（未保存，由调用方决定保存路径）
    """
    _parse_dialogues(script)

    storyboard = Storyboard(script_title=script_title)
    grouped_shots = _group_dialogues_into_shots(script)

    count = 0
    for i, (scene, dialogue_list) in enumerate(grouped_shots):
        count += 1

        primary_dialogue = dialogue_list[0]

        # Detect all characters in this shot (from ALL dialogues in group + structured characters_detail)
        present_chars = []  # List of (name, description)
        panel_char_ids = []  # List of IDs for the panel object
        seen_char_names = set()

        # Helper to add char
        def add_char(name):
            if name in seen_char_names:
                return

            # Filter out Narrator/Voiceover roles from visual characters
            if name in ["旁白", "画外音", "Narrator", "Voiceover", "OS", "字幕"]:
                return

            seen_char_names.add(name)
            char_obj = char_map.get(name)
            if char_obj:
                present_chars.append((char_obj.name, char_obj.appearance_features))
                panel_char_ids.append(char_obj.id)
            else:
                present_chars.append((name, ""))

        # 0. 优先从结构化 characters_detail 提取（新版 schema，含 pose/expression/emotional_state）
        for cname in scene.get_character_names():
            add_char(cname)

        # 1. Add speakers
        for d in dialogue_list:
            add_char(d.role)

        # 2. Detect others in Action or Content
        for d in dialogue_list:
            for char_name, char_obj in char_map.items():
                if char_name in seen_char_names:
                    continue
                if char_name in d.action or char_name in d.content:
                    add_char(char_name)

        # Combine actions for the prompt
        combined_action = ". ".join([d.action for d in dialogue_list if d.action])

        # 单一真相源 - 从 scene.duration_seconds 取时长（区间 5-10 秒）
        # 旧数据/手工编辑可能超出区间，统一收敛——超长时长会线性放大视频采样时间
        try:
            from core.script.script_service import clamp_shot_duration as _clamp_dur
        except ImportError:
            from src.core.script.script_service import clamp_shot_duration as _clamp_dur
        duration = float(_clamp_dur(getattr(scene, 'duration_seconds', None) or 8.0))

        # Build video_params dict directly - enriched for full fidelity
        char_names = [c[0] for c in present_chars]  # Extract just names
        video_params = {
            'audio': f"背景音乐{scene.atmosphere}，{scene.weather}环境音" if scene.atmosphere else "背景音乐根据场景氛围匹配",
            'camera_movement': scene.camera_movement if scene.camera_movement else "推轨镜头 + 稳定器轻微运动",
            'shot_type': scene.shot_type if scene.shot_type else "中景",
            'style': scene.style if hasattr(scene, 'style') else "电影感",
            'action': combined_action or (scene.action or ""),
            'duration': duration,
            'scene_description': scene.scene_location or scene.location or scene.description or "",
            'characters': '，'.join(char_names) if char_names else "",
            'props': "",  # TODO: extract props from dialogues if needed
            'atmosphere': scene.atmosphere if scene.atmosphere else "",
            'scene_location': scene.scene_location or scene.location or ""
        }

        # Combine descriptions
        full_desc = "\n".join([f"{d.role}: {d.content}" + (f" ({d.action})" if d.action else "") for d in dialogue_list])

        # video_params already built earlier, just add dialogue info
        video_params['dialogue'] = primary_dialogue.content
        video_params['dialogue_role'] = primary_dialogue.role

        # 构建场景描述
        scene_desc = f"{primary_dialogue.role}"
        if primary_dialogue.action:
            scene_desc += f" {primary_dialogue.action}"
        if scene.scene_location:
            scene_desc += f"，场景位于{scene.scene_location}"
        if scene.atmosphere:
            scene_desc += f"，氛围{scene.atmosphere}"

        # 角色参考图收集（供视频提示词 ref_image_count 与后续生成使用）
        ref_paths = []
        for cid in panel_char_ids:
            for cname, cobj in char_map.items():
                if cobj.id == cid:
                    # 优先级：avatar_path > front_view > grid_1drag4_path > reference_images
                    # 与 image_window 的参考图收集保持一致
                    for attr in ("avatar_path", "front_view", "grid_1drag4_path"):
                        p = getattr(cobj, attr, None)
                        if p and os.path.exists(p) and p not in ref_paths:
                            ref_paths.append(p)
                            break  # 每个角色取第一张可用的即可
                    for ri in (cobj.reference_images or []):
                        if ri and os.path.exists(ri) and ri not in ref_paths:
                            ref_paths.append(ri)
                    break

        # 先创建临时panel对象用于生成视频提示词
        temp_panel = Panel(
            panel_id="temp",
            scene_id=scene.shot_id or scene.scene_id,
            description=full_desc,
            video_prompt="",
            duration=duration
        )
        temp_panel.characters = char_names  # Use names, not UUIDs

        # 镜位标记：本镜在全片中的位置 + 上一镜动作（喂给 construct_video_prompt 做接戏起落幅）
        _total_shots = len(grouped_shots)
        _is_first = (i == 0)
        _is_last = (i == _total_shots - 1)

        def _action_text(value):
            if value is None:
                return ""
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, (list, tuple)):
                return "；".join(_action_text(v) for v in value if v)
            return str(value).strip()

        _prev_action = ""
        _prev_state = ""
        _same_scene_prev = True
        if i > 0:
            _prev_scene = grouped_shots[i - 1][0]
            _prev_action = _action_text(getattr(_prev_scene, "action", ""))
            if not _prev_action:
                _prev_list = grouped_shots[i - 1][1]
                _prev_action = "；".join(
                    _action_text(getattr(d, "action", ""))
                    for d in (_prev_list or []) if getattr(d, "action", ""))
            _prev_state = _char_state_text(_prev_scene)
            # 换场判定：场景或时间变化即为换场（天气渐变属同场景正常连续）。
            # 跨场景强接戏会让图生视频把无关场景硬性渐变出怪异画面，
            # 换场镜必须重新建立空间（construct_video_prompt 换场分支）。
            _prev_loc = str(getattr(_prev_scene, "scene_location", "")
                            or getattr(_prev_scene, "location", "")).strip()
            _cur_loc = str(getattr(scene, "scene_location", "")
                           or getattr(scene, "location", "")).strip()
            _prev_time = str(getattr(_prev_scene, "time", "") or "").strip()
            _cur_time = str(getattr(scene, "time", "") or "").strip()
            _same_scene_prev = (_prev_loc == _cur_loc and _prev_time == _cur_time)

        # 生成专业视频提示词：
        # 提取对白五要素（Experience 2215960）：tone/pace/emotion 从 Dialogue tags，
        # body_action 从 dialogue.action 或 characters_detail 的 pose/动作描述
        _tone = getattr(primary_dialogue, 'tone', '') or ''
        _pace = getattr(primary_dialogue, 'pace', '') or ''
        _emotion = getattr(primary_dialogue, 'emotion', '') or ''
        # emotion 兜底：Dialogue 没标但 characters_detail 有 → 用角色的 emotional_state
        if not _emotion:
            _det = scene.get_character_detail(primary_dialogue.role)
            if _det and _det.get("emotional_state"):
                _emotion = str(_det["emotional_state"]).strip()
        _body_action = getattr(primary_dialogue, 'action', '') or ''
        if not _body_action:
            _det = scene.get_character_detail(primary_dialogue.role)
            if _det and _det.get("pose"):
                _body_action = str(_det["pose"]).strip()

        # LLM 输出的六段式完整格式（含段落标记）直接用；
        # 简短创意核心 / 空 → construct_video_prompt 程序化展开（创意文本融入画面描述）。
        # 旧项目的超长提示词（LLM 自己写的六段式 + 字典原文，长度是紧凑版的 3-4 倍）
        # 同样重建成紧凑版——它要喂给 32B 编码器，长度直接吃生成时间。
        _existing_vp = (scene.video_prompt or "").strip()
        _is_full_format = ("【分镜时间轴】" in _existing_vp
                           or "【参考图描述】" in _existing_vp
                           or "[Shot Timeline]" in _existing_vp
                           or "[Reference Image Description]" in _existing_vp)
        _is_legacy_bloated = (len(_existing_vp) > 2500
                              or "'name':" in _existing_vp
                              or '"name":' in _existing_vp)
        if _existing_vp and _is_legacy_bloated:
            # 压缩旧长提示词：保留 LLM 写的创意时间轴，只砍样板段落 + 字典原文
            _compacted = compact_video_prompt(_existing_vp)
            if _compacted and len(_compacted) < len(_existing_vp):
                video_prompt = _compacted
            else:
                video_prompt = construct_video_prompt(
                    panel=temp_panel,
                    video_params=video_params,
                    dialogue_text=primary_dialogue.content,
                    dialogue_role=primary_dialogue.role,
                    duration=duration,
                    ref_image_count=len(ref_paths),
                    is_first=_is_first,
                    is_last=_is_last,
                    prev_action=_prev_action,
                    prev_state=_prev_state,
                    tone=_tone, pace=_pace,
                    emotional_state=_emotion,
                    body_action=_body_action,
                    same_scene_as_prev=_same_scene_prev
                )
        elif _existing_vp and _is_full_format:
            video_prompt = _existing_vp
        else:
            if _existing_vp and not _is_legacy_bloated:
                # 简短创意核心 → 融入 scene_description 喂给时间轴，保留创意内容与地点信息
                video_params = dict(video_params or {})
                _base_desc = video_params.get('scene_description') or ''
                if _base_desc and _base_desc != _existing_vp:
                    video_params['scene_description'] = f"{_existing_vp}（场景：{_base_desc}）"
                else:
                    video_params['scene_description'] = _existing_vp
            video_prompt = construct_video_prompt(
                panel=temp_panel,
                video_params=video_params,
                dialogue_text=primary_dialogue.content,
                dialogue_role=primary_dialogue.role,
                duration=duration,
                ref_image_count=len(ref_paths),
                is_first=_is_first,
                is_last=_is_last,
                prev_action=_prev_action,
                prev_state=_prev_state,
                tone=_tone, pace=_pace,
                emotional_state=_emotion,
                body_action=_body_action,
                same_scene_as_prev=_same_scene_prev
            )

        # 分段从最终提示词解析，保证与提示词时间轴一致；解析失败时按默认规则兜底
        video_segments = parse_video_prompt_to_segments(video_prompt, duration) \
            or generate_default_video_segments(duration, temp_panel)

        panel = Panel(
            panel_id=f"p_{count}",
            scene_id=scene.shot_id or scene.scene_id,
            description=full_desc,
            video_prompt=video_prompt,
            video_prompt_segments=video_segments,
            video_params=video_params,
            duration=duration
        )

        panel.characters = panel_char_ids
        # 场景/道具绑定：此前 panel.scenes / panel.props 恒为空，
        # 导致场景图、道具图永远取不到（只有角色图能用）。
        # 这里按名字把剧本里的场景/道具描述匹配到资源库对象，回填 ID。
        if scene_map:
            _sids = _match_ids_by_text(scene.scene_location or scene.location or "",
                                        scene_map, max_ids=1)
            if _sids:
                panel.scenes = _sids
        if prop_map:
            _pids = _match_ids_by_text(scene.props or "", prop_map, max_ids=2)
            if _pids:
                panel.props = _pids

        # WB-7: 存储结构化对白到 prompt_params（供逐行 TTS 和字幕使用）
        panel.prompt_params["_dialogues"] = [
            {
                "role": d.role,
                "content": d.content,
                "action": getattr(d, 'action', ''),
                "tone": getattr(d, 'tone', '') or '',
                "pace": getattr(d, 'pace', '') or '',
                "emotion": getattr(d, 'emotion', '') or '',
            }
            for d in dialogue_list
        ]

        # 一致性与连续性：将角色状态详情和连续性说明注入 prompt_params
        if scene.characters_detail:
            panel.prompt_params["_char_states"] = scene.characters_detail
        if scene.continuity_note:
            panel.prompt_params["_continuity"] = scene.continuity_note
        # 本镜动作文本：生成时接戏注入（_with_continuity）优先读这里，
        # 其次 video_params.action / _dialogues；scene.action 是单一真相源
        _action_text_val = _action_text(scene.action) or combined_action
        if _action_text_val:
            panel.prompt_params["_action"] = _action_text_val
        # 场景锚点：scene_location/time/weather 供 image_client 做同场景 seed/参考图判断
        panel.prompt_params["_scene_key"] = {
            "location": scene.scene_location or scene.location or "",
            "time": scene.time or "",
            "weather": scene.weather or "",
        }

        if ref_paths:
            # 取第一张作为 panel.reference_image_path（向后兼容字段）
            panel.reference_image_path = ref_paths[0]
            # 将全部参考图存入 panel 的 prompt_params 供 image_client 使用
            panel.prompt_params.setdefault("_ref_images", ref_paths)

        # 一致性锚点：查表注入 _anchors，供 image_client / tts_client 使用
        if anchor_table is not None:
            anchor_payload = {"characters": [], "scene": None}
            # 角色锚点：按 panel 内出现的角色名查表
            for cid in panel_char_ids:
                cobj = None
                for cname, c in char_map.items():
                    if c.id == cid:
                        cobj = c
                        break
                if not cobj:
                    continue
                ca = anchor_table.find_character(cobj.name)
                if ca:
                    anchor_payload["characters"].append(ca.to_dict())
            # 场景锚点：用分镜 scene_location 文本匹配场景库
            scene_loc = getattr(scene, "scene_location", "") or getattr(scene, "location", "")
            if scene_loc:
                sa = anchor_table.find_scene(scene_loc)
                if sa:
                    anchor_payload["scene"] = sa.to_dict()
            # 只有查到至少一个锚点才写入，避免空 payload
            if anchor_payload["characters"] or anchor_payload["scene"]:
                panel.prompt_params["_anchors"] = anchor_payload

        storyboard.panels.append(panel)

    # 构建摘要日志：确认状态承接/防字幕/禁令在各镜提示词中的覆盖率
    _n_total = len(storyboard.panels)
    _n_state = sum(1 for p in storyboard.panels
                   if p.video_prompt and "状态承接" in p.video_prompt)
    _n_anti = sum(1 for p in storyboard.panels
                  if p.video_prompt and "no subtitles" in p.video_prompt)
    _n_full = sum(1 for p in storyboard.panels
                  if p.video_prompt and "【分镜时间轴】" in p.video_prompt)
    print(f"[分镜工厂] 构建完成：{_n_total} 镜 | 状态承接行 {_n_state} 镜"
          f"（首镜天然无上一镜状态） | 防字幕禁令 {_n_anti} 镜"
          f" | 六段式完整提示词 {_n_full} 镜 | 含场景道具绑定 "
          f"{sum(1 for p in storyboard.panels if p.scenes or p.props)} 镜")

    return storyboard
