"""
国际化提示词模块 - 支持中文和英文两种语言
项目创建时选定语言后，所有提示词将使用该语言
"""

# 剧本生成提示词
SCRIPT_GENERATION_PROMPT = {
    "zh": """
请为系列剧集创作下一集的剧本。

剧集信息：
标题：{episode_title}（第 {episode_number} 集，共 {total_episodes} 集）
类型：{genre}
目标长度：约 {words_per_episode} 字
主要角色：{main_characters}

系列梗概：
{premise}

全局故事摘要（到目前为止的故事）：
{global_summary}

角色状态（角色当前状态）：
{character_state}

即时上下文（最近几集的摘要）：
{recent_episodes_summary}

上一场景（上一剧本的最后几行）：
{previous_script_excerpt}

相关记忆（RAG检索）：
{rag_context}

本集创意：
{user_idea}

要求：
1. 格式：标准剧本格式（场景标题、动作、角色名、对话）。
2. 连续性：确保角色的情绪状态和物理位置与"角色状态"和"上一场景"匹配。
3. 节奏：{duration}
4. 风格：{style}
5. 视觉效果：编写详细的电影化动作描述。包括灯光、氛围和特定的角色表情，以帮助视频生成。
6. 视觉过渡：关键。编写连接场景的动作描述。
   - 如果角色离开场景，描述他们退出画面。
   - 如果新角色接下来出现，让当前角色朝那个方向看或反应。
   - 使用匹配的物体或动作连接不同场景（例如，"镜头推近手表..." -> 下一个场景以时钟开始）。
   - 确保一个场景的结束在视觉上流畅地过渡到下一个场景的开始。
7. 摄影技术：使用特定的摄影语言来指导视频生成。
   - 镜头类型：在动作描述中指定"特写"、"中景"、"全景"、"极特写"。
   - 角度：使用"低角度"（力量）、"高角度"（脆弱）、"荷兰角"（不安）、"平视"（中性）。
   - 运动：包括"摇摄"、"俯仰"、"推进/拉出"、"变焦"、"跟踪镜头"。
   - 示例："约翰颤抖的手的特写。镜头向上俯仰到他出汗的脸。"
8. 走位和定位：关键。定义角色相对于彼此和环境的位置。
   - 使用空间术语："前景"、"背景"、"左侧"、"右侧"、"中央"、"旁边"、"对面"、"后面"。
   - 指定相对位置："爱丽丝站在鲍勃的左边"、"约翰在背景中看着前景中的玛丽"。
   - 确保角色不会占据相同的空间，除非是故意的。

请生成第 {episode_number} 集的剧本。
""",
    "en": """
Create a script for the next episode of the series.

SERIES INFO:
Title: {episode_title} (Episode {episode_number} of {total_episodes})
Genre: {genre}
Target Length: ~{words_per_episode} words
Main Characters: {main_characters}

SERIES PREMISE:
{premise}

GLOBAL STORY SUMMARY (The story so far):
{global_summary}

CHARACTER STATE (Current status of characters):
{character_state}

IMMEDIATE CONTEXT (Summary of recent episodes):
{recent_episodes_summary}

PREVIOUS SCENE (Last few lines of the previous script):
{previous_script_excerpt}

RELEVANT MEMORY (RAG Retrieval):
{rag_context}

CURRENT EPISODE IDEA:
{user_idea}

REQUIREMENTS:
1. Format: Standard script format (Scene Heading, Action, Character Name, Dialogue).
2. Continuity: Ensure characters' emotional states and physical locations match the "Character State" and "Previous Scene".
3. Pacing: {duration}
4. Style: {style}
5. Visuals: Write detailed, cinematic action lines. Include lighting, atmosphere, and specific character expressions to aid video generation.
6. Visual Transitions: CRITICAL. Write action lines that bridge scenes visually.
   - If a character leaves a scene, describe them exiting frame.
   - If a new character appears next, have the current character look or react in that direction.
   - Use matching objects or motions to link distinct scenes (e.g., "Camera zooms in on the watch..." -> Next scene starts with a clock).
   - Ensure the end of one scene visually flows into the start of the next.
7. Cinematography: Use specific camera language to direct the video generation.
   - Shot Types: Specify "Close-up", "Medium Shot", "Wide Shot", "Extreme Close-up" in action lines.
   - Angles: Use "Low Angle" (power), "High Angle" (vulnerability), "Dutch Angle" (unease), "Eye Level" (neutral).
   - Movements: Include "Pan", "Tilt", "Dolly In/Out", "Zoom", "Tracking Shot".
   - Example: "Close-up of John's hand shaking. Camera tilts up to his sweating face."
8. Blocking & Positioning: CRITICAL. Define where characters are relative to each other and the environment.
   - Use spatial terms: "foreground", "background", "left", "right", "center", "next to", "opposite", "behind".
   - Specify relative positions: "Alice stands to the left of Bob", "John is in the background watching Mary in the foreground".
   - Ensure characters are not occupying the same space unless intended.

Generate the script for Episode {episode_number}.
"""
}

# 更新角色状态提示词
UPDATE_CHARACTER_STATE_PROMPT = {
    "zh": """
根据新生成的剧本更新角色状态。

当前角色状态：
{current_state}

新剧本内容：
{script_content}

说明：
1. 更新现有角色的状态（身体健康、情绪状态、物品/道具、关系）。
2. 添加剧本中引入的任何新主要角色。
3. 移除不再相关或已死亡的角色（可选）。
4. 保持格式结构化（JSON或清晰的文本）。

请仅返回更新后的角色状态描述。
""",
    "en": """
Based on the newly generated script, update the character state.

CURRENT CHARACTER STATE:
{current_state}

NEW SCRIPT CONTENT:
{script_content}

INSTRUCTIONS:
1. Update the status of existing characters (Physical health, Emotional state, Inventory/Items, Relationships).
2. Add any new major characters introduced in this script.
3. Remove characters that are no longer relevant or deceased (optional).
4. Keep the format structured (JSON or clear text).

Return ONLY the updated character state description.
"""
}

# 更新全局摘要提示词
UPDATE_GLOBAL_SUMMARY_PROMPT = {
    "zh": """
根据新剧集更新全局故事摘要。

当前全局摘要：
{current_summary}

新剧集摘要：
{episode_summary}

说明：
1. 将新剧集的关键事件整合到全局摘要中。
2. 保持简洁但足够全面，以理解整体叙事弧线。
3. 关注主要情节点和角色发展。

请仅返回更新后的全局摘要。
""",
    "en": """
Update the global story summary based on the new episode.

CURRENT GLOBAL SUMMARY:
{current_summary}

NEW EPISODE SUMMARY:
{episode_summary}

INSTRUCTIONS:
1. Integrate the key events of the new episode into the global summary.
2. Keep it concise but comprehensive enough to understand the overall narrative arc.
3. Focus on major plot points and character developments.

Return ONLY the updated global summary.
"""
}

# 剧集摘要提示词
SUMMARIZE_EPISODE_PROMPT = {
    "zh": """
将以下剧本总结为简洁的段落（100-200字）。
重点关注：关键情节事件、角色决策和悬念。

剧本：
{script_content}
""",
    "en": """
Summarize the following script into a concise paragraph (100-200 words).
Focus on: Key plot events, Character decisions, and Cliffhangers.

SCRIPT:
{script_content}
"""
}

# 视觉提示词生成提示词
PROMPT_GENERATION_PROMPT = {
    "zh": """
为系列剧集的下一集创建视觉提示词生成。
这些提示词将直接用于AI图像生成模型和视频生成模型。

剧集信息：
标题：{episode_title}（第 {episode_number} 集，共 {total_episodes} 集）
类型：{genre}
主要角色：{main_characters}

角色参考（角色参考图片）：
{character_references}

系列梗概：
{premise}

全局故事摘要：
{global_summary}

角色状态：
{character_state}

即时上下文：
{recent_episodes_summary}

上一场景：
{previous_script_excerpt}

本集创意：
{user_idea}

叙事与故事性要求（必须严格遵守）：
1. 集内叙事弧：本集是一条完整的叙事线——起（钩子/事件切入）→ 承（推进与升级）→ 转（冲突/意外/反转）→ 合（收束并留下悬念钩子）。所有分镜必须服务这条线，禁止把画面并列罗列成流水账。
2. 节拍表（把叙事弧映射到分镜位置，按实际分镜数等比分配）：
   - 第 1 镜：黄金钩子——全集最强的悬念/冲突画面，3 秒内抓住观众
   - 前 1/3 分镜：建立主角目标 + 第一次升级（阻碍出现）
   - 中间 1/3 分镜：对抗持续升级，至少一次信息差揭示或关系反转
   - 后 1/3 分镜：高潮对决，情绪达到全集顶点
   - 最后 1-2 镜：收束本集并留下悬念钩子
3. 情节增量：每个分镜必须带来新信息、关系变化、决定或危险升级；禁止两个分镜重复描述同一状态或重复同一动作。
4. 因果链：每个分镜是上一个分镜的"结果"并引发下一个分镜（因为…于是…但是…），镜头之间必须因果相接。
5. 冲突三要素：本集必须有明确的"主角欲望（想要什么）—对立力量（谁/什么在阻碍）—失败代价（输了会怎样）"；每个分镜至少把其中之一显性化到画面或对白中。
6. 爽点密度：每 2-3 个分镜至少安排一个爽点或反转（身份揭示/打脸/信息差曝光/意外反转/压抑后的情绪释放），禁止连续 3 个分镜无冲突、无新信息的平缓推进。
7. 对白火药味：对白必须短、狠、带钩——每句台词要么推进冲突，要么揭示信息，禁止寒暄客套、自我介绍式对白；善用潜台词（嘴上说的≠心里想的）；对抗场景中双方台词必须互相攻击/防守/反击，一句压一句。
8. 情绪曲线：全集情绪强度整体递增——前段压抑蓄力，中段出现小高潮（第一次情绪爆发），后段达到顶点；禁止全片情绪一马平川。
9. 集尾钩子：最后 1-2 个分镜必须留悬念（未解问题/新威胁/关键决定未执行），为承接下一集留口。
10. 改编要求：忠实度约束不放松（见改编幅度指令），但必须把所选情节重组为一条连续的因果动作线——原著的场景/段落可以压缩合并，情节因果与关键信息不得删减。
11. 单镜一事：每个分镜只承载一个事件、一个节拍。单集装不下全部情节时，用时间跳跃/转场省略中间过程（在 continuity_note 里说明省略了什么），禁止把多个事件堆叠进同一个分镜的 action（例如把"三次下毒+死亡"塞进一镜）。
12. 开场钩子：第 1 镜必须是全集最强悬念/冲突画面（黄金 3 秒），禁止用空镜、风景、起床、走路等无冲突内容开场。
13. 钩子工程：钩子分三类——信息悬念（秘密/真相将揭）、情绪悬念（关系将变）、危机悬念（危险将至）；相邻分镜与相邻集的钩子类型必须轮换，禁止连续使用同一类型；本集埋下的悬念必须在本集内兑现、或在末镜明确标注留待下集，禁止只埋不收；前段出现的道具/细节必须在后段发挥作用（契诃夫之枪），无铺垫的反转、天降外援一律禁止。
14. 情绪温度曲线：按 1-5 档（1日常/2推进/3对峙/4爆发/5失控）规划全集温度，典型曲线 2→3→4→2/3+钩子；温度只能逐级升降，禁止从 1 档直跳 4/5 档；每个分镜的 atmosphere 必须与该镜所处温度档匹配。
15. 主角能动性与对白工艺：主角必须主动调查/追问/做决定来推动剧情，禁止整集被动接收信息、只会震惊；对白必须配动作节拍（把动作/表情/环境变化写进 action），禁止单镜内 4 句以上纯对话来回而画面静止；同一角色的情绪反应在全集不得重复同一生理模板（如连续"心一紧"），需变换具体反应（胃里发凉/指尖发麻/忘了呼吸）。

一致性与连续性规则（必须严格遵守）：
1. 角色外貌一致性：characters 数组中的 appearance_features 是角色的固定外貌描述，全集通用。分镜的 characters 字段只写姿势/表情/服装变化/位置/情绪，禁止重复完整外貌描述。
2. 场景连续性：同一场景的连续分镜，scene_location/time/weather 必须完全相同。只有明确描写时间流逝或场景切换时才允许变化，并在 continuity_note 中说明。全集时间线只能向前推进（例如 Night 之后不得再回到 Dusk），除非明确标注闪回。
3. 情绪连贯性：每个角色的 emotional_state 必须与前一分镜自然衔接，情绪突变需要有剧情依据（如收到消息、看到某物）。
4. 空间稳定性：同一场景中角色的 position（前景/背景/左侧/右侧）应保持稳定，除非剧情描写角色移动。
5. 服装连续性：clothing_note 为"同前"表示服装不变；如有变化必须具体说明（如"外套已脱"），且变化必须有剧情依据（如打斗后衣服破损）。
6. 动作接戏：每个分镜的结尾状态必须是下一个分镜的起始状态——身体姿势、空间位置、正在进行的动作保持连续；下一镜从上一镜动作的"下一拍"开始，禁止重新起势、重复描述到达过程。
7. 轴线与视线匹配：双人对话/对抗场景必须保持同一轴线（180度规则）——上一镜 A 看向画面右侧，下一镜 B 必须在画面左侧（或从左侧入画）；相邻镜头禁止无故越轴造成方向混乱。characters 的 position 字段必须写明朝向（面向镜头/侧对/背对），且相邻镜头的朝向必须互补对应。
8. 景别递进：同一场景内相邻分镜的景别必须递进或拉开（如 全景建立→中景→特写 逐层收紧，或高潮后特写→全景拉开喘息）；禁止相邻两镜使用相同景别且相同运镜（产生跳剪感）；景别大幅跳变（特写直跳远景）必须在 continuity_note 说明理由。
9. 出入画衔接：角色离开场景必须写出画动作（走出画面/被遮挡/镜头摇离）；新角色入场必须承接上一镜的视线方向或动静（如上一镜角色看向门口，本镜新角色从门口入画；或敲门声/脚步声先入画再见人）。
10. 换场过渡显式化：换场镜头的 continuity_note 必须写明过渡方式——硬切+新环境建立镜头 / 匹配剪辑（物体或动作匹配）/ 声音先入（J-cut），并说明换场省略了什么过程（如路途）。
11. 语言：全中文输出。
12. 状态延续：角色的服装/情绪/姿态变化（湿透、受伤、弄脏、衣着更换、情绪剧变）一旦发生，后续分镜必须延续该状态，直到剧情明确改变；禁止湿透后下一镜又干爽、受伤后凭空痊愈。上述状态变化写入 characters_detail 的 clothing_note/emotional_state/pose 字段。

输出格式（JSON对象）：
{{
    "title": "本集中文标题（10字以内，吸引人，禁止写成 Episode N 或纯集数）",
    "shots": [
        {{
            "shot_id": "1-1",
            "scene_location": "场景名称（与前一分镜相同场景时必须使用完全相同的名称）",
            "time": "Day/Night/Dawn/Dusk（同一场景的连续分镜必须保持相同，除非明确描写时间流逝）",
            "weather": "Sunny/Rainy/Foggy/Snowy/Clear（同一场景的连续分镜必须保持相同）",
            "atmosphere": "紧张/浪漫/动作/恐怖/喜剧/悬疑/悲伤/史诗",
            "style": "电影感/写实/动漫/水墨/油画/赛博朋克/奇幻/科幻/中国风",
            "shot_type": "特写/中景/全景/远景/POV/双人镜头",
            "camera_movement": "固定/推轨/摇镜/俯仰/变焦/环绕/手持/稳定器/航拍",
            "duration_seconds": "整数，根据情节灵活选择 5-10 秒（推荐 8 秒），对白多/动作复杂的镜头最多 10 秒（严禁超过 10 秒，生成会显存溢出失败），环境铺垫/空镜可以短到 5 秒",
            "characters": [
                {{
                    "name": "角色名（必须与角色库中的名称完全一致）",
                    "pose": "当前姿势：站/坐/跪/躺/走/跑/转身等",
                    "expression": "当前表情：微笑/愤怒/惊讶/平静/哭泣等",
                    "clothing_note": "服装变化说明（如无变化写'同前'；如有变化写具体变化，如'外套已脱，只穿白衬衫'）",
                    "position": "空间位置：前景/背景/左侧/右侧/中央，以及朝向（面向镜头/侧对/背对）",
                    "emotional_state": "当前情绪状态，如'压抑的愤怒'、'强装镇定'、'释然的微笑'"
                }}
            ],
            "continuity_note": "与上一分镜的衔接说明，必须同时包含两部分：①场景关系（同场景续/换场景的过渡方式/时间跳跃内容）；②动作承接（上一镜收尾动作如何进入本镜，如'承接Clifford放下手的动作，手落桌面时镜头切至…'）",
            "props": "镜头中的重要道具或物体",
            "action": "角色在做什么（动作描述）",
            "dialogue": "角色名: 角色真正说出口的台词原文（必须为'角色名: 台词'格式）。本镜无台词时必须写成'旁白: …'一句旁白；严禁'无明确对白''无对白'等描述性文字——它们会被直接朗读出来",
            "video_prompt": "本镜头画面创意核心（1-2句话，不超过120字）：写清楚主体在做什么、关键动作/表情/情绪变化、镜头要捕捉的决定性瞬间。禁止写六段式模板（【参考图描述】【质量要求】等由系统自动生成）"
        }}
    ],
    "characters": [
        {{
            "name": "角色名称",
            "gender": "男性/女性/未知",
            "nationality": "国别/族裔（如中国汉族、日本大和、欧美白人等），必须明确填写，用于角色图面部特征一致性",
            "age": "青年/少年/中年/老年/儿童",
            "appearance_features": "详细外貌描述，必须包含：身高体型、发型面容、服装穿着、配饰装备。面部特征须与国别/族裔一致。注意：这是角色的固定外貌，全集通用，不要在分镜中重复",
            "style_description": "角色风格，如古装、现代、科幻等",
            "personality": "性格特点",
            "role_in_story": "主角/配角/反派等",
            "background": "角色背景故事"
        }}
    ],
    "props": [
        {{
            "name": "道具名称",
            "description": "道具详细描述，必须包含：材质工艺、颜色外观、尺寸大小、特征细节、功能用途",
            "category": "武器/家具/饰品/工具/食物/其他",
            "importance": "重要/一般",
            "material": "材质",
            "color": "颜色",
            "size": "尺寸"
        }}
    ],
    "script_scenes": [
        {{
            "name": "场景名称",
            "description": "场景详细描述，必须包含：整体布局、建筑风格、环境细节、氛围营造、光影效果",
            "time_of_day": "Day/Night/Dawn/Dusk",
            "weather": "Sunny/Rainy/Foggy/Snowy/Clear",
            "style": "场景风格",
            "location_type": "场景类型",
            "atmosphere": "氛围描述",
            "key_elements": "关键元素"
        }}
    ]
}}

========================================
视频提示词说明：
========================================

video_prompt 字段只写本镜头的创意核心（1-2句话，不超过120字）：
- 写清楚主体在做什么、关键动作/表情/情绪变化、镜头要捕捉的决定性瞬间
- 示例："女医猛地按住伤口，抬头怒视闯入者，眼中含泪却强忍不发"
- 禁止写【参考图描述】【视频基础信息】【分镜时间轴】【运镜设计】【参考图一致性约束】【质量要求】六段式模板——这些段落由系统在后续步骤自动生成，你无需输出

IMPORTANT: 视频生成基于角色、场景、道具参考图。参考图定义了必须严格遵守的角色外观、场景布局与道具样式；视频应围绕参考图的核心画面创建流畅的动态叙事，任何镜头运动都不得改变参考图中已确定的外观特征。此约束由系统自动写入生成提示词，你无需在 video_prompt 中重复。

========================================
风格: {style}

角色提取指南：
从剧本中提取所有出现的角色，为每个角色创建详细档案，用于AI图片生成：
- name: 角色名称（使用剧本中的名字）
- gender: 根据角色特征判断性别（男性/女性/未知）
- age: 根据描述判断年龄段（儿童/少年/青年/中年/老年）
- appearance_features: 详细外貌描述，必须包含以下要素，用于AI图片生成：
  * 身高体型：如"身高180cm，体型魁梧健壮"、"身材纤细娇小"等
  * 发型面容：如"黑色长发及腰，瓜子脸，丹凤眼，高鼻梁"、"短发干练，国字脸，浓眉大眼"等
  * 服装穿着：如"身穿红色丝绸长袍，金色刺绣花纹，腰间系着玉带"、"现代黑色西装，白色衬衫，蓝色领带"等
  * 配饰装备：如"头戴金冠，手持宝剑，脚穿战靴"、"佩戴珍珠耳环，手提名牌包"等
  * 表情神态：如"眼神坚定，面容刚毅"、"面带微笑，神态温和"等
- style_description: 整体艺术风格，如"中国古代武侠风格，唐代服饰"、"现代都市时尚风格，商务精英"、"赛博朋克风格，未来科技感"等
- personality: 性格特点，如"勇敢坚毅、正直不阿"、"温柔善良、聪慧过人"、"狡猾多疑、心机深沉"等
- role_in_story: 在故事中的角色定位（主角/配角/反派/路人等）
- background: 角色背景故事

道具提取指南：
从剧本中提取所有重要道具，用于AI图片生成：
- name: 道具名称
- description: 详细描述，必须包含以下要素，用于AI图片生成：
  * 材质工艺：如"青铜铸造，表面有精美纹饰"、"纯银打造，镶嵌宝石"、"木质结构，漆器工艺"等
  * 颜色外观：如"通体金黄色，剑身有龙纹图案"、"乌黑发亮，表面光滑如镜"、"翠绿色，半透明质感"等
  * 尺寸大小：如"长约1.2米，宽约30厘米"、"手掌大小，便于携带"、"巨大无比，需要双手才能举起"等
  * 特征细节：如"剑柄镶嵌红宝石，剑穗为红色丝绸"、"表面有岁月痕迹，古朴沧桑"、"散发着淡淡光芒，神秘莫测"等
  * 功能用途：如"锋利无比，可斩断钢铁"、"冬暖夏凉，可保持温度"、"内含机关，可变形组合"等
- category: 分类（武器/家具/饰品/工具/食物/其他）
- importance: 对剧情的重要性（重要/一般）
- material: 材质
- color: 颜色
- size: 尺寸

场景提取指南：
从剧本中提取所有场景，用于AI图片生成：
- name: 场景名称（如"古代寺庙庭院"、"现代咖啡厅"）
- description: 详细环境描述，必须包含以下要素，用于AI图片生成：
  * 整体布局：如"宽敞的大殿，正中供奉着佛像，两侧是罗汉像"、"狭长的街道，两旁是古老的建筑"等
  * 建筑风格：如"典型的中国古代宫殿建筑，飞檐翘角，红墙黄瓦"、"现代简约风格，玻璃幕墙，钢结构"等
  * 环境细节：如"地面铺着青石板，缝隙中长满了青苔"、"墙上挂着古老的字画，角落摆放着盆栽"等
  * 氛围营造：如"烟雾缭绕，香火鼎盛，庄严肃穆"、"阳光明媚，花香四溢，温馨舒适"等
  * 光影效果：如"阳光透过窗户洒入，形成斑驳光影"、"烛光摇曳，阴影跳动，神秘莫测"等
- time_of_day: 时间（Day/Night/Dawn/Dusk）
- weather: 天气（Sunny/Rainy/Foggy/Snowy/Clear等）
- style: 场景风格（古代/现代/科幻/奇幻等）
- location_type: 场景类型
- atmosphere: 氛围描述
- key_elements: 关键元素

重要提示：
1. 仅输出有效的JSON对象，不要markdown，不要解释
2. 分镜数量规则 - 重要：
   - 每集必须严格生成分镜数量为9个！
   - 禁止增减分镜数量！每集只能是9个分镜！
3. 时长规则 - 重要：
   - 每个分镜的时长根据情节灵活选择 5-10 秒（推荐 8 秒），对白多/动作复杂的镜头最多 10 秒（严禁超过 10 秒，生成会显存溢出失败），环境铺垫/空镜可以短到 5 秒
   - 每集所有分镜总时长必须 ≥75 秒（9 个分镜 × 8 秒 = 72 秒，系统会自动补足）！
4. 改编完整性 - 最高优先级：
   - 【最高优先级】改编短剧时，必须严格尊重原文！
   - 禁止随意增加原文没有的情节！
   - 禁止随意删除原文的重要情节！
   - 保留原作的核心情感和氛围
   - 保留原作的重要对白和台词（在不违反平台政策的前提下）
   - 保留原作的角色特征和关系
   - 保留原作的场景细节和环境描述
   - 保留原作的时间线和因果关系
   - 如果原作信息量大，必须在9个分镜内完整呈现，禁止压缩或跳过重要内容！
   - 禁止为了简洁而牺牲重要内容！
5. VIDEO_PROMPT要求（重要）：
   - 只写本镜头的创意核心（1-2句话，不超过120字）：主体在做什么、关键动作/表情/情绪变化、决定性瞬间
   - 禁止写六段式模板（【参考图描述】【视频基础信息】【分镜时间轴】【运镜设计】【参考图一致性约束】【质量要求】），这些由系统自动生成
   - 示例：「女医猛地按住伤口，抬头怒视闯入者，眼中含泪却强忍不发」
6. 对摄影机运动和时间要具体（体现在 action / shot_type / camera_movement 字段）
7. 如果提到主要角色，包含角色参考
8. 从剧本中提取所有独特的角色、道具和场景
9. 为角色提供详细的外貌描述，用于AI图片生成
10. 在角色、道具和场景对象中包含所有必填字段
11. 在JSON输出中返回characters、props和script_scenes数组

请生成第 {episode_number} 集的视觉提示词。
""",
    "en": """
Create a visual prompt generation for the next episode of the series.
These prompts will be used directly by AI image generation models and video generation models.

SERIES INFO:
Title: {episode_title} (Episode {episode_number} of {total_episodes})
Genre: {genre}
Main Characters: {main_characters}

CHARACTER REFERENCES:
{character_references}

SERIES PREMISE:
{premise}

GLOBAL STORY SUMMARY:
{global_summary}

CHARACTER STATE:
{character_state}

IMMEDIATE CONTEXT:
{recent_episodes_summary}

PREVIOUS SCENE:
{previous_script_excerpt}

CURRENT EPISODE IDEA:
{user_idea}

NARRATIVE & STORY REQUIREMENTS (MUST follow strictly):
1. Episode story arc: This episode is ONE complete narrative line — Hook (inciting moment) → Build (escalation) → Turn (conflict/twist) → Payoff (resolution with a suspense hook). ALL shots must serve this line; never list disconnected pretty pictures.
2. Beat sheet (map the arc onto shot positions, scaled to the actual shot count):
   - Shot 1: Golden hook — the episode's strongest suspense/conflict image, grabbing viewers within 3 seconds
   - First third of shots: establish the protagonist's goal + first escalation (the obstacle appears)
   - Middle third: confrontation keeps escalating, with at least one information-gap reveal or relationship reversal
   - Final third: climactic confrontation, emotion hits the episode's peak
   - Last 1-2 shots: resolve this episode AND leave a suspense hook
3. Plot increment: Every shot MUST bring new information, a relationship shift, a decision, or raised stakes. NEVER have two shots describe the same state or repeat the same action.
4. Causality chain: Each shot is the RESULT of the previous shot and the CAUSE of the next one (because... so... but...). Shots must connect causally.
5. Conflict triad: The episode MUST define a clear protagonist desire (what they want), an opposing force (who/what blocks them), and stakes (what failure costs); every shot makes at least one of these visible in frame or dialogue.
6. Payoff density: every 2-3 shots MUST deliver a payoff or twist (identity reveal / face-slapping / info-gap exposure / unexpected reversal / pent-up emotional release); NEVER allow 3 consecutive shots with no conflict and no new information.
7. Dialogue with teeth: lines MUST be short, sharp and hooked — every line either advances the conflict or reveals information; no small talk or self-introduction; use subtext (what they say ≠ what they mean); in confrontations, lines must attack/defend/counter-attack, each topping the previous.
8. Emotional curve: overall emotional intensity rises through the episode — suppressed build-up early, a mid-episode mini-climax (first emotional burst), and the peak near the end; NEVER keep emotion flat throughout.
9. End-of-episode hook: The final 1-2 shots MUST leave suspense (unresolved question / new threat / key decision unexecuted) to bridge into the next episode.
10. Adaptation requirement: The fidelity constraint stays in force (see adaptation level instruction), but you MUST reorganize the chosen source material into ONE continuous causal action line — source scenes/paragraphs may be compressed or merged, but plot causality and key information must not be dropped.
11. One event per shot: each shot carries EXACTLY ONE event/beat. If the episode cannot fit all plot, skip intermediate events via time jumps/transitions (explain the skip in continuity_note); NEVER stack multiple events into one shot's action (e.g. three poison attempts + death in a single shot).
12. Opening hook: Shot 1 MUST be the episode's strongest suspense/conflict image (the golden 3 seconds) — never open with empty scenery, landscapes, waking up, or walking shots.
13. Hook engineering: hooks come in three types — information suspense (a secret/truth about to surface), emotional suspense (a relationship about to shift), crisis suspense (danger approaching); adjacent shots and adjacent episodes MUST rotate hook types, never the same type twice in a row; every hook planted in this episode MUST pay off within it (or be explicitly marked in the final shot as reserved for the next) — never plant without payoff; props/details introduced early MUST fire later (Chekhov's gun); twists without setup and deus-ex-machina rescues are forbidden.
14. Emotional temperature curve: plan the episode on a 1-5 temperature scale (1 calm-daily / 2 progress / 3 standoff / 4 explosion / 5 unhinged); the typical curve is 2→3→4→2/3+hook; temperature may only move one band at a time — NEVER jump from band 1 straight to 4/5; each shot's atmosphere MUST match the temperature band it sits in.
15. Protagonist agency & dialogue craft: the protagonist MUST actively investigate / press / decide to drive the plot — never a whole episode of passive reception and shocked reactions; dialogue MUST be interleaved with action beats (write gesture/expression/environment shifts into action) — NEVER 4+ pure back-and-forth lines in one shot with a frozen frame; a character's emotional reaction MUST NOT repeat the same bodily template across the episode (e.g. three "heart tightens" in a row) — vary the concrete reaction (cold stomach / numb fingertips / forgetting to breathe).

CONSISTENCY & CONTINUITY RULES (MUST follow strictly):
1. Character appearance consistency: The appearance_features in the characters array is the character's FIXED appearance used throughout the episode. The characters field in each shot should ONLY describe pose/expression/clothing changes/position/emotional state. NEVER repeat the full appearance description.
2. Scene continuity: For consecutive shots in the same scene, scene_location/time/weather MUST be identical. Only change them when the script explicitly describes time passage or scene transition, and explain in continuity_note. The episode timeline only moves FORWARD (e.g. Dusk must never follow Night) unless a flashback is explicitly marked.
3. Emotional coherence: Each character's emotional_state must flow naturally from the previous shot. Emotional jumps need story justification (e.g., receiving news, seeing something).
4. Spatial stability: Characters' position (foreground/background/left/right) should remain stable within the same scene unless the story describes movement.
5. Clothing continuity: clothing_note "same as before" means no change; if changed, describe specifically (e.g., "jacket removed") and the change must have story justification (e.g., torn during fight).
6. Action match-on-action: Each shot's ENDING state (body posture, spatial position, ongoing action) MUST be the next shot's STARTING state. The next shot begins on the NEXT BEAT of the previous shot's action — never re-start the motion or re-describe the arrival.
7. Axis & eyeline match: two-person dialogue/confrontation MUST keep one axis (180-degree rule) — if A looks toward frame-right in one shot, B MUST be frame-left (or enter from frame-left) in the next; never cross the line without justification. The characters' position field MUST state orientation (facing camera/sideways/back), and adjacent shots' orientations MUST complement each other.
8. Shot-size progression: within the same scene, adjacent shots MUST progress or pull back in size (e.g. wide → medium → close-up tightening, or close-up → wide release after climax); NEVER use identical shot_type AND camera_movement in adjacent shots (jump-cut feel); a large size jump (close-up straight to long shot) MUST be justified in continuity_note.
9. Entrances & exits: a character leaving MUST be written exiting frame (walks out / gets occluded / camera pans away); a new character's entrance MUST continue the previous shot's eyeline or off-screen cue (e.g. previous shot looks at the door, this shot the newcomer enters through it; or knocking/footsteps heard before they appear).
10. Explicit scene transitions: a scene-change shot's continuity_note MUST state the transition method — hard cut + new-location establishing shot / match cut (object or action) / sound-first (J-cut) — and what intermediate process is elided (e.g. the journey).
11. Language: Output all content in Chinese.
12. State carry-over: once a character's clothing/emotion/pose changes (soaked, injured, dirtied, outfit change, emotional shift), EVERY following shot must continue that state until the plot explicitly changes it; never reset soaked clothing dry in the next shot or heal injuries off-screen. Record such changes in characters_detail's clothing_note/emotional_state/pose fields.

OUTPUT FORMAT (JSON object):
{{
    "title": "Episode title in Chinese (max 10 chars, catchy, do NOT use 'Episode N' or plain numbers)",
    "shots": [
        {{
            "shot_id": "1-1",
            "scene_location": "Location name (MUST use identical name as previous shot if same scene)",
            "time": "Day/Night/Dawn/Dusk (consecutive shots in same scene MUST be identical unless time skip is described)",
            "weather": "Sunny/Rainy/Foggy/Snowy/Clear (consecutive shots in same scene MUST be identical)",
            "atmosphere": "Tense/Romantic/Action/Horror/Comedy/Suspense/Sad/Epic",
            "style": "Cinematic/Realistic/Anime/Ink/Oil/Cyberpunk/Fantasy/Sci-fi/Chinese",
            "shot_type": "Close-up/Medium/Wide/Long/POV/Two-shot",
            "camera_movement": "Static/Dolly/Pan/Tilt/Zoom/Orbit/Handheld/Stabilizer/Aerial",
            "duration_seconds": "Integer, MUST be between 8 and 10 seconds (e.g. 8), allocated by content amount, never exceed 10 seconds per shot",
            "characters": [
                {{
                    "name": "Character name (MUST match character library exactly)",
                    "pose": "Current pose: standing/sitting/kneeling/lying/walking/running/turning etc",
                    "expression": "Current expression: smile/angry/surprised/calm/crying etc",
                    "clothing_note": "Clothing change note (write 'same as before' if unchanged; if changed, describe specifically, e.g. 'jacket removed, only white shirt')",
                    "position": "Spatial position: foreground/background/left/right/center, plus orientation (facing camera/sideways/back to camera)",
                    "emotional_state": "Current emotional state, e.g. 'suppressed anger', 'forced calm', 'relieved smile'"
                }}
            ],
            "continuity_note": "Connection to previous shot, MUST contain BOTH parts: 1) scene relationship ('same scene continuation' / transition for scene change / what the time skip covers); 2) action match-on-action (how the previous shot's ending action enters this shot, e.g. 'continues from Clifford lowering his hand — the shot cuts to... as his hand lands on the table')",
            "props": "Important props or objects in the shot",
            "action": "What characters are doing",
            "dialogue": "Character Name: actual spoken lines (MUST be 'Name: dialogue' format, e.g. 'Alice: I've been waiting for you.'). If the shot has NO spoken line, write narration as 'Narrator: ...' instead; NEVER write descriptive placeholders like 'no dialogue' or '无明确对白' — they would be read aloud by TTS",
            "video_prompt": "Creative visual core of this shot (1-2 sentences, max 120 chars): what the subject is doing, key action/expression/emotional shift, the decisive moment the camera should capture. Do NOT write the six-section template (reference description / quality requirements etc. are auto-generated by the system)"
        }}
    ],
    "characters": [
        {{
            "name": "Character name",
            "gender": "Male/Female/Unknown",
            "nationality": "Nationality/ethnicity (e.g. Chinese Han, Japanese, Caucasian, etc.) - REQUIRED for consistent facial features in character images",
            "age": "Youth/Teen/Adult/Middle-aged/Elderly/Child",
            "appearance_features": "Detailed appearance description including: height/build, hair/face, clothing, accessories. Facial features MUST match nationality/ethnicity. NOTE: This is the character's FIXED appearance for the entire episode, do NOT repeat it in shot-level descriptions",
            "style_description": "Character style, e.g., ancient, modern, sci-fi",
            "personality": "Personality traits",
            "role_in_story": "Protagonist/Supporting/Antagonist/etc",
            "background": "Character background story"
        }}
    ],
    "props": [
        {{
            "name": "Prop name",
            "description": "Detailed description including: material/craftsmanship, color/appearance, size, features, function",
            "category": "Weapon/Furniture/Accessory/Tool/Food/Other",
            "importance": "Important/General",
            "material": "Material",
            "color": "Color",
            "size": "Size"
        }}
    ],
    "script_scenes": [
        {{
            "name": "Scene name",
            "description": "Detailed environment description including: layout, architecture, details, atmosphere, lighting",
            "time_of_day": "Day/Night/Dawn/Dusk",
            "weather": "Sunny/Rainy/Foggy/Snowy/Clear",
            "style": "Scene style",
            "location_type": "Location type",
            "atmosphere": "Atmosphere description",
            "key_elements": "Key elements"
        }}
    ]
}}

========================================
VIDEO PROMPT NOTE:
========================================

The video_prompt field only needs the creative core of this shot (1-2 sentences, max 120 chars):
- What the subject is doing, key action/expression/emotional shift, the decisive moment the camera should capture
- Example: "The doctor suddenly presses the wound, looks up glaring at the intruder, eyes full of tears but holding back"
- Do NOT write the six-section template ([Reference Image Description][Video Basic Info][Shot Timeline][Camera Movement Design][Reference Consistency Constraints][Quality Requirements]) — these sections are auto-generated by the system in a later step

IMPORTANT: The video is generated from character/scene/prop reference images. The reference images define the character appearance, scene layout and prop styles that MUST be strictly respected. The video should build a smooth dynamic narrative around the core frame of the reference images; no camera movement may alter the appearance already fixed in the reference images. This constraint is automatically written into the generation prompt by the system — you do not need to repeat it in video_prompt.

========================================
STYLE: {style}

CHARACTER EXTRACTION Guidelines:
Extract all characters appearing in the script and create detailed profiles for AI image generation:
- name: Character name (use names from script)
- gender: Determine gender based on character traits (Male/Female/Unknown)
- age: Determine age group based on description (Child/Teen/Youth/Adult/Middle-aged/Elderly)
- appearance_features: Detailed appearance description for AI image generation including:
  * Height/Build: e.g., "180cm tall, robust build", "slender and petite figure"
  * Hair/Face: e.g., "long black hair to waist, oval face, phoenix eyes", "short neat hair, square face"
  * Clothing: e.g., "wearing red silk robe with golden embroidery", "modern black suit, white shirt"
  * Accessories: e.g., "golden crown on head, holding sword", "wearing pearl earrings, carrying designer bag"
  * Expression: e.g., "determined eyes, resolute face", "gentle smile, mild demeanor"
- style_description: Overall art style, e.g., "Ancient Chinese martial arts style, Tang Dynasty costume", "Modern urban fashion style"
- personality: Personality traits, e.g., "brave and upright", "gentle and kind", "cunning and suspicious"
- role_in_story: Role in story (Protagonist/Supporting/Antagonist/Extra)
- background: Character background story

PROP EXTRACTION Guidelines:
Extract all important props from the script for AI image generation:
- name: Prop name
- description: Detailed description for AI image generation including:
  * Material/Craftsmanship: e.g., "bronze casting with exquisite patterns", "pure silver with gemstone inlay"
  * Color/Appearance: e.g., "golden yellow body with dragon patterns", "jet black and smooth like mirror"
  * Size: e.g., "about 1.2m long, 30cm wide", "palm-sized, easy to carry"
  * Features: e.g., "ruby inlaid in handle, red silk tassel", "ancient traces on surface"
  * Function: e.g., "sharp enough to cut steel", "keeps temperature, warm in winter cool in summer"
- category: Category (Weapon/Furniture/Accessory/Tool/Food/Other)
- importance: Importance to plot (Important/General)
- material: Material
- color: Color
- size: Size

SCENE EXTRACTION Guidelines:
Extract all scenes from the script for AI image generation:
- name: Scene name (e.g., "Ancient Temple Courtyard", "Modern Coffee Shop")
- description: Detailed environment description for AI image generation including:
  * Layout: e.g., "spacious hall with Buddha statue in center, Arhat statues on sides"
  * Architecture: e.g., "typical ancient Chinese palace architecture, upturned eaves, red walls"
  * Details: e.g., "stone slabs on ground with moss in gaps", "ancient paintings on walls"
  * Atmosphere: e.g., "smoke lingering, incense burning, solemn and dignified"
  * Lighting: e.g., "sunlight through windows creating dappled shadows", "candlelight flickering"
- time_of_day: Time (Day/Night/Dawn/Dusk)
- weather: Weather (Sunny/Rainy/Foggy/Snowy/Clear)
- style: Scene style (Ancient/Modern/Sci-fi/Fantasy)
- location_type: Location type
- atmosphere: Atmosphere description
- key_elements: Key elements

IMPORTANT:
1. Output ONLY valid JSON object, no markdown, no explanations
2. PANEL COUNT RULE - CRITICAL:
   - Each episode MUST contain EXACTLY 10 shots (panels)!
   - Do NOT add or remove shots! Always 10 shots per episode!
3. DURATION RULES - CRITICAL:
   - Every shot MUST be between 8 and 10 seconds (8 recommended)! NEVER exceed 10 seconds per shot!
   - The total duration of all shots in an episode MUST be at least 75 seconds (10 shots x 8 seconds = 80 seconds)!
   - Adjust within the range based on content amount: dialogue-rich / complete-action shots take the upper bound (10s), fast-paced shots the lower bound (8s)
   - NEVER shorter than 8 seconds! NEVER longer than 10 seconds!
   - Do NOT use the same duration for all shots! Adjust dynamically based on scene content!
4. SCENE DIVERSITY - CRITICAL:
   - Each episode must have different types of scenes (indoor/outdoor, day/night, different locations)
   - Avoid using the same scene in consecutive episodes
   - Scenes should evolve and change as the story progresses
   - Character costumes and props should change with the story
5. VIDEO PROMPT QUALITY - CRITICAL:
   - VIDEO_PROMPT: only write the creative core (1-2 sentences, max 120 chars): what the subject is doing, key action/expression/emotional shift, the decisive moment
   - Do NOT write the six-section template — it is auto-generated by the system
   - Example: "The doctor suddenly presses the wound, looks up glaring at the intruder, eyes full of tears but holding back"
6. CONTENT SAFETY - CRITICAL:
   - Avoid dangerous driving, brake failure and other sensitive content
   - Avoid extreme emotion words (terror, fear, heartbeat sounds, etc.)
   - Convert negative emotions to positive expressions (e.g., use "tense" instead of "terror")
   - Dialogue content must comply with platform policies
7. ADAPTATION INTEGRITY - CRITICAL:
   - [IMPORTANT] When adapting, MUST preserve ALL important information from the original work, do NOT omit key plot points
   - Preserve the core emotions and atmosphere of the original
   - Preserve important dialogues and lines from the original (while complying with platform policies)
   - Preserve character traits and relationships from the original
   - Preserve scene details and environment descriptions from the original
   - Preserve timeline and cause-effect relationships from the original
   - If the original has a lot of information, cover it within 10 shots rather than compressing content
   - Do NOT sacrifice important information for brevity!
8. Be specific about camera movements and timing (via action / shot_type / camera_movement fields)
9. Include character reference if main characters are mentioned
10. Extract ALL unique characters, props, and scenes from the script
11. For characters, provide detailed appearance_features for AI image generation
12. Include ALL required fields in character, prop, and scene objects
13. Return characters, props, and script_scenes arrays in the JSON output

Generate the visual prompts for Episode {episode_number}.
"""
}


def get_prompt(prompt_dict: dict, language: str = "zh") -> str:
    """
    根据语言获取对应的提示词
    
    Args:
        prompt_dict: 包含中英文提示词的字典
        language: 语言代码，"zh"表示中文，"en"表示英文
    
    Returns:
        对应语言的提示词字符串
    """
    if language not in ["zh", "en"]:
        language = "zh"
    return prompt_dict.get(language, prompt_dict.get("zh", ""))


def format_prompt(prompt_dict: dict, language: str = "zh", **kwargs) -> str:
    """
    获取并格式化提示词
    
    Args:
        prompt_dict: 包含中英文提示词的字典
        language: 语言代码，"zh"表示中文，"en"表示英文
        **kwargs: 用于格式化提示词的参数
    
    Returns:
        格式化后的提示词字符串
    """
    prompt_template = get_prompt(prompt_dict, language)
    try:
        return prompt_template.format(**kwargs)
    except KeyError as e:
        # 如果格式化失败，返回原始模板
        return prompt_template
