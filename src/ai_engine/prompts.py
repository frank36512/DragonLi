# Prompts adapted from novel_maker for continuous script generation

SCRIPT_GENERATION_PROMPT = """
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

UPDATE_CHARACTER_STATE_PROMPT = """
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

UPDATE_GLOBAL_SUMMARY_PROMPT = """
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

SUMMARIZE_EPISODE_PROMPT = """
Summarize the following script into a concise paragraph (100-200 words).
Focus on: Key plot events, Character decisions, and Cliffhangers.

SCRIPT:
{script_content}
"""

PROMPT_GENERATION_PROMPT = """
Create a visual prompt generation for the next episode of the series.
These prompts will be used directly by AI image generation models and video generation models.

SERIES INFO:
Title: {episode_title} (Episode {episode_number} of {total_episodes})
Genre: {genre}
Main Characters: {main_characters}

CHARACTER REFERENCES (角色参考图片):
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

OUTPUT FORMAT (JSON object):
{
    "shots": [
        {
            "shot_id": "1-1",
            "scene_location": "Location name",
            "time": "Day/Night/Dawn/Dusk",
            "weather": "Sunny/Rainy/Foggy/Snowy/Clear",
            "atmosphere": "紧张/浪漫/动作/恐怖/喜剧/悬疑/悲伤/史诗",
            "style": "电影感/写实/动漫/水墨/油画/赛博朋克/奇幻/科幻/中国风",
            "shot_type": "特写/中景/全景/远景/POV/双人镜头",
            "camera_movement": "固定/推轨/摇镜/俯仰/变焦/环绕/手持/稳定器/航拍",
            "duration_seconds": "整数，根据情节灵活选择 5-10 秒（推荐 8 秒），对白多/动作复杂的镜头最多 10 秒（严禁超过 10 秒，生成会显存溢出失败），环境铺垫/空镜可以短到 5 秒",
            "characters": "Who appears in this shot, their appearance, clothing, pose - 必须详细描述外貌、服装、姿态、表情",
            "props": "Important props or objects in the shot - 必须描述道具的材质、颜色、细节",
            "action": "What characters are doing (动作描述) - 必须详细描述动作过程、肢体语言、表情变化",
            "dialogue": "Character dialogue/narration (if any) - 注意：避免危险驾驶、恐怖、极端情绪等敏感内容",
            "video_prompt": "Complete prompt for AI video generation with motion (use line breaks for timing) - 必须包含【参考图描述】【视频基础信息】【分镜时间轴（秒级分段，每段含画面/对白/运镜/音效/情绪）】【运镜设计】【参考图一致性约束】【质量要求】各段落，信息完整具体"
        }
    ],
    "characters": [
        {
            "name": "角色名称",
            "gender": "男性/女性/未知",
            "nationality": "国别/族裔（如中国汉族、日本大和、欧美白人等），必须明确填写，用于角色图面部特征一致性",
            "age": "青年/少年/中年/老年/儿童",
            "appearance_features": "详细外貌描述，必须包含：身高体型、发型面容、服装穿着、配饰装备、表情神态；面部特征须与国别/族裔一致",
            "style_description": "角色风格，如古装、现代、科幻等",
            "personality": "性格特点",
            "role_in_story": "主角/配角/反派等",
            "background": "角色背景故事"
        }
    ],
    "props": [
        {
            "name": "道具名称",
            "description": "道具详细描述，必须包含：材质工艺、颜色外观、尺寸大小、特征细节、功能用途",
            "category": "武器/家具/饰品/工具/食物/其他",
            "importance": "重要/一般",
            "material": "材质",
            "color": "颜色",
            "size": "尺寸"
        }
    ],
    "script_scenes": [
        {
            "name": "场景名称",
            "description": "场景详细描述，必须包含：整体布局、建筑风格、环境细节、氛围营造、光影效果",
            "time_of_day": "Day/Night/Dawn/Dusk",
            "weather": "Sunny/Rainy/Foggy/Snowy/Clear",
            "style": "场景风格",
            "location_type": "场景类型",
            "atmosphere": "氛围描述",
            "key_elements": "关键元素"
        }
    ]
}

========================================
VIDEO PROMPT Guidelines (秒级时间轴分段 - 强化版):
========================================

必须使用以下格式，基于角色/场景/道具参考图生成视频。输出必须完整包含以下六个段落，缺一不可：
【参考图描述】【视频基础信息】【分镜时间轴】【运镜设计】【参考图一致性约束】【质量要求】

IMPORTANT: 视频生成基于角色、场景、道具参考图。参考图定义了必须严格遵守的角色外观、场景布局与道具样式；视频应围绕参考图的核心画面创建流畅的动态叙事，任何镜头运动都不得改变参考图中已确定的外观特征。

【参考图描述】
- 说明参考图包含角色/场景/道具参考图若干张，逐张描述核心内容
- 描述角色的外观、服装、发型、姿态、表情
- 描述场景环境、光照、色调、整体氛围与视觉风格
- 描述关键道具的样式与位置
- 示例: "参考图包含悟空的角色参考图与菩提禅房场景参考图。悟空身穿金甲圣衣，跪拜在蒲团上，低头闭目，神情虔诚。菩提禅房古朴典雅，阳光透过窗棂洒入，整体氛围庄重肃穆，光线明亮温暖，电影感风格"

【视频基础信息】
- 画面主体: 主要角色和特征（必须与角色参考图一致）
- 场景环境: 地点和环境（必须与场景参考图一致）
- 光影氛围: 光线和氛围描述（与参考图一致）
- 运镜基调: 该分镜整体运镜风格（如"缓慢推近"、"手持跟随"、"固定机位"）
- 情绪基调: 该分镜整体情绪（如"庄重肃穆"、"紧张压迫"、"温情舒缓"）
- 参考图类型: 角色/场景/道具参考图
- 视频时长: X秒

【分镜时间轴】
把视频时长切成 3-4 个秒级（或百分比）段落，完整覆盖 0 秒到总时长。每段必须包含以下五行，缺一不可：
- 画面：该时间段画面内容（基于参考图如何随时间变化）
- 对白：角色名："对白内容"（无对白写"（无）"）
- 运镜：该段具体镜头运动（推/拉/摇/移/环绕/手持 + 景别变化）
- 音效：该段音效（背景音乐、环境音、拟音、音乐情绪变化）
- 情绪：该段情绪基调与起伏（如"庄重→虔诚递进"）

时间分配规则（以总时长 8 秒为例，切 3 段，每段约 2-3 秒；单镜时长可在 5-10 秒间按情节灵活选择，严禁超过 10 秒）：
- 第1段（0-3秒）：建立画面，交代环境与主体位置，缓慢推近或展现环境细节
- 第2段（3-6秒）：主体动作启动，展现角色姿态与表情，动作展开进入核心叙事
- 第3段（6-8秒）：情感高潮或动作重点，景别收窄到特写，收尾或过渡

【运镜设计】
依据 shot_type（景别）与 camera_movement 生成具体镜头语言，写清起幅、落幅与转场：
- 景别：特写 / 中景 / 全景 / 远景 / POV / 双人镜头，说明景别如何随时间变化
- 运镜词表：固定、推轨(Dolly In/Out)、摇镜(Pan)、俯仰(Tilt)、变焦(Zoom)、环绕(Orbit)、手持(Handheld)、稳定器(Steadicam)、航拍(Aerial)
- 起幅/落幅：从什么构图开始、到什么构图结束（如"中景起幅 → 特写落幅"）
- 转场衔接：与下一分镜的视觉衔接方式（如"镜头停留在双手细节后淡出"）

【参考图一致性约束】
- 角色一致性：角色脸部特征、发型、服装、配饰必须与角色参考图完全一致，禁止变形、换脸、服装突变
- 场景一致性：场景布局、建筑结构、光照色调必须与场景参考图一致，禁止场景漂移或凭空新增元素
- 道具一致性：道具的材质、颜色、形状、位置必须与道具参考图一致，禁止道具消失、变形或突变
- 全程画面禁止出现任何文字、字幕、标语、水印

【质量要求】
- 画面稳定，无抖动
- 运动流畅自然
- 保持与参考图一致的视觉风格
- 电影级画质
- 无变形、无鬼影、无闪烁

完整示例 (8秒视频，基于角色/场景参考图):
【参考图描述】
参考图包含悟空的角色参考图与菩提禅房场景参考图。悟空身穿金甲圣衣，跪拜在蒲团上，低头闭目，神情虔诚专注。菩提禅房古朴典雅，木质结构，阳光透过窗棂洒入，灰尘在光柱中飞舞。整体氛围庄重肃穆，光线明亮温暖，电影感风格

【视频基础信息】
画面主体: 悟空，身穿金甲圣衣，跪拜姿态，虔诚表情
场景环境: 菩提禅房，古朴典雅，木质结构
光影氛围: 自然光从窗户照入，明亮温暖，庄重
运镜基调: 缓慢推近，稳定过渡
情绪基调: 庄重肃穆，由虔诚渐入平静
参考图类型: 角色/场景参考图
视频时长: 8秒

【分镜时间轴】
第0-3秒：
- 画面：基于参考图，镜头缓缓推近，展现菩提禅房全貌和悟空跪拜位置，建立空间关系
- 对白：（无）
- 运镜：从固定镜头缓慢推近（中景），建立视觉焦点
- 音效：背景音乐庄重，风声，渐入
- 情绪：庄重肃穆

第3-6秒：
- 画面：聚焦悟空跪拜动作，展现双手合十的姿态和恭敬之意
- 对白：悟空："师父，弟子明白了！"
- 运镜：平滑推近到中景，保持稳定
- 音效：音乐持续，风声持续
- 情绪：虔诚加深

第6-8秒：
- 画面：镜头在悟空双手合十与虔诚表情的细节上停留，特写收窄，然后淡出
- 对白：（无）
- 运镜：推近到特写，在细节上停留，然后淡出
- 音效：音乐渐弱，自然过渡
- 情绪：余韵收束

【运镜设计】
- 景别：中景起幅 → 特写落幅
- 运镜：固定 → 平滑推近 → 停留 → 淡出
- 转场衔接：镜头停留在双手细节后淡出，衔接下一分镜

【参考图一致性约束】
- 角色一致性：悟空脸部特征、金甲圣衣、发型与角色参考图完全一致，禁止变形或服装突变
- 场景一致性：菩提禅房的木质结构、窗棂光影与场景参考图一致，禁止场景漂移
- 道具一致性：蒲团材质与位置与参考图一致，禁止道具消失或变形
- 全程画面禁止出现任何文字、字幕、标语、水印

【质量要求】
- 画面稳定，无抖动
- 运动流畅自然
- 保持参考图的视觉风格（电影感，庄重）
- 电影级画质
- 无变形、无鬼影、无闪烁

[音频提示]
background music, ambient sounds, emotional cues, natural transitions

[质量要求]
smooth motion, no jitter, high quality, consistent lighting, no morphing, no distortion, professional cinematography

========================================
STYLE: {style}

CHARACTER EXTRACTION Guidelines:
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

PROP EXTRACTION Guidelines:
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

SCENE EXTRACTION Guidelines:
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

IMPORTANT:
1. Output ONLY valid JSON object, no markdown, no explanations
2. PANEL COUNT RULE - CRITICAL (分镜数量):
   - 每集必须严格生成分镜数量为9个！
   - 禁止增减分镜数量！每集只能是9个分镜！
3. DURATION RULE - CRITICAL (时长):
   - 每个分镜的时长根据情节灵活选择 5-10 秒（推荐 8 秒），对白多/动作复杂的镜头最多 10 秒（严禁超过 10 秒，生成会显存溢出失败），环境铺垫/空镜可以短到 5 秒
   - 每集所有分镜总时长必须 ≥75 秒（9 个分镜 × 8 秒 = 72 秒，系统会自动补足）！
   - 在video_prompt中，时间轴必须从第0秒到该分镜总时长完整分段描述
4. SCENE DIVERSITY - CRITICAL (场景多样性):
   - 每一集必须合理分配9个分镜覆盖主要场景
   - 避免连续分镜使用相同场景
   - 根据剧情进展，场景应该有变化和发展
   - 角色服装、道具应该随剧情变化
5. VIDEO PROMPT QUALITY - CRITICAL (视频提示词质量，最高优先级):
   - VIDEO_PROMPT 必须完整包含【参考图描述】【视频基础信息】【分镜时间轴】【运镜设计】【参考图一致性约束】【质量要求】六个段落
   - 【分镜时间轴】必须按秒级分段（3-4 段，完整覆盖 0 秒到总时长），每段包含"画面/对白/运镜/音效/情绪"五行
   - 必须细化运镜（推/拉/摇/移/环绕/手持 + 景别变化 + 起幅落幅），并写明参考图一致性约束
   - 每个镜头的提示词必须详细、具体，禁止过于简洁
   - 必须描述角色的具体表情、动作细节、服装细节
6. CONTENT SAFETY - CRITICAL (内容安全):
   - 避免危险驾驶、刹车失灵等敏感内容
   - 避免极端情绪词汇（惊恐、恐惧、心跳声等）
   - 将负面情绪转化为正向表达（如"紧张"代替"惊恐"）
   - 对白内容必须符合平台政策
7. ADAPTATION INTEGRITY - CRITICAL (改编完整性，最高优先级):
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
8. VIDEO_PROMPT must use line breaks (\n) to separate sections and include second-level timing (第X-Y秒)
9. Always include 【质量要求】 section in video_prompt
10. Be specific about camera movements and timing
11. Include character reference if main characters are mentioned
12. Extract ALL unique characters, props, and scenes from the script
13. For characters, provide detailed appearance_features for AI image generation
14. Include ALL required fields in character, prop, and scene objects
15. Return characters, props, and script_scenes arrays in the JSON output

Generate the visual prompts for Episode {episode_number}.
"""
