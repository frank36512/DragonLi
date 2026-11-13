# -*- coding: utf-8 -*-
"""全自动流水线运行参数。"""

try:
    from core.autorun.state import STAGES
except ImportError:
    from src.core.autorun.state import STAGES


# 改编幅度：控制剧本对原著的忠实程度（UI「改编幅度」下拉的取值）
FIDELITY_LEVELS = ("faithful", "light", "heavy")

FIDELITY_LABELS = {"faithful": "忠于原著", "light": "轻度改编", "heavy": "大幅改编"}

# 生成调度模式：
# - episode（逐集）：一集跑完所有阶段（剧本→片段→字幕→合成）再进下一集
# - category（逐类）：所有集先跑完同一阶段，再进入下一阶段
#   （先所有集剧本，再所有集角色/场景/道具+分镜，再所有集视频片段，最后逐集合成）
GENERATE_MODES = ("episode", "category")
GENERATE_MODE_LABELS = {"episode": "逐集生成", "category": "逐类生成"}

FIDELITY_INSTRUCTIONS = {
    "faithful": {
        "zh": ("改编幅度【忠于原著】：必须严格忠于原文改编。"
               "禁止增删原文情节，保留原有对白、角色关系、时间线与场景细节，"
               "禁止为了节奏而删改关键信息。"
               "若大纲、摘要或任何上下文内容与原文冲突，一律以原文为准"
               "（大纲只是结构参考，不是情节来源）；"
               "风格类型只影响视觉呈现（服装、场景质感、时代感），"
               "不得改动情节、对白与人物关系，禁止新增原文没有的场景、人物职业或行为。"),
        "en": ("Adaptation level [Faithful]: follow the source closely. "
               "Do not add or remove plot points; keep original dialogue, character "
               "relationships, timeline and scene details; do not drop key information. "
               "If the outline, summaries or any context conflicts with the source text, "
               "the source text ALWAYS wins (the outline is structure reference only, "
               "never a plot source); genre/style only affects visual presentation "
               "(wardrobe, set texture, era look) and must NOT change plot, dialogue or "
               "relationships — never invent scenes, character occupations or behaviors "
               "absent from the source."),
    },
    "light": {
        "zh": ("改编幅度【轻度改编】：以原文情节和人物关系为骨架，"
               "可为增强节奏与冲突做小幅调整，但核心情节走向与结局必须保持一致。"
               "若大纲/摘要与原文冲突，以原文为准；新增内容不得破坏原文因果链。"),
        "en": ("Adaptation level [Light]: keep the source's plot and relationships as the "
               "skeleton; minor pacing/conflict adjustments are allowed, but the main plot "
               "direction and ending must stay the same. If outline/summaries conflict "
               "with the source, the source wins; additions must not break its causality."),
    },
    "heavy": {
        "zh": ("改编幅度【大幅改编】：可自由重组情节、压缩或扩展段落、增补新冲突以适配短剧节奏，"
               "只需保留原作世界观、人物设定与主题内核。"
               "增删改的情节必须自洽，禁止与大纲/摘要互相矛盾。"),
        "en": ("Adaptation level [Heavy]: feel free to restructure the plot, compress or expand "
               "sections and add conflicts to fit short-drama pacing; only keep the source's "
               "world, character settings and thematic core. All changes must stay "
               "self-consistent and never contradict the outline/summaries."),
    },
}


class AutoRunParams:
    """一次全自动任务的全部参数，可 JSON 序列化（存入 autorun_state.json 便于追溯）。"""

    def __init__(self,
                 topic="",
                 style="都市",
                 episode_count=1,
                 duration="智能时长",
                 use_video_gen=True,
                 checkpoints=None,
                 voice_id=None,
                 bgm_path=None,
                 existing_script_path=None,
                 instructions="",
                 language="zh",
                 export_preset="custom",
                  blend_mode="crossfade",
                 transition_duration=0.0,
                 aspect_ratio="16:9",
                 resolution="1080p",
                 seed=None,
                 negative_prompt="",
                 shot_duration=0.0,
                 panel_count=9,
                 allow_mock=False,
                 fail_on_qa_error=False,
                 source_text="",
                 fidelity="",
                 generate_mode="episode"):
        self.topic = topic
        self.style = style
        self.episode_count = max(1, int(episode_count or 1))
        self.duration = duration or "智能时长"
        # 视频片段生成方式：分镜图片下线后固定使用图生视频（角色/场景/道具参考图 + 提示词）。
        # 字段保留以兼容历史 autorun_state.json，流水线不再依据它切换路径。
        self.use_video_gen = bool(use_video_gen)
        # 检查点集合：这些阶段完成后暂停等待用户确认（须配合 on_checkpoint 回调）
        self.checkpoints = set(checkpoints) if checkpoints else set()
        self.voice_id = voice_id
        self.bgm_path = bgm_path
        # 指定已有剧本文件时，跳过 LLM 直接使用该剧本
        self.existing_script_path = existing_script_path
        # 附加创意说明（拼接到主题后）
        self.instructions = instructions
        # 输出语言：zh=中文，en=英文
        self.language = language or "zh"
        # 导出预设 key（custom/douyin/tiktok/kuaishou/bilibili/youtube）
        self.export_preset = export_preset or "custom"
        # 融合偏好：crossfade=叠化（默认）/ fade=淡入淡出 / hardcut=硬切
        self.blend_mode = blend_mode or "crossfade"
        # 转场时长（秒）；0=按融合模式取默认（crossfade 0.5s / fade 0.3s；硬切恒为 0）
        self.transition_duration = float(transition_duration or 0.0)
        # 宽高比（端到端贯穿：出图→clip→导出）
        self.aspect_ratio = aspect_ratio or "16:9"
        # 输出分辨率档：1080p / 720p。决定生成端像素预算与成片目标尺寸
        self.resolution = resolution or "1080p"
        # 固定 seed（None=随机；设置后同参数可复现）
        self.seed = int(seed) if seed is not None else None
        # 负面提示词（追加到 style preset 的 negative 之后）
        self.negative_prompt = negative_prompt or ""
        # 每镜头时长（秒）：0=自动（由 LLM 在 5-10 秒内灵活选择），>0=统一固定该值
        self.shot_duration = float(shot_duration or 0.0)
        # 剧本目标镜头数
        self.panel_count = max(1, int(panel_count or 9))
        # 是否允许 mock 降级路径（生产环境应为 False）
        self.allow_mock = bool(allow_mock)
        # QA 错误是否阻断（False=仅记录 warning）
        self.fail_on_qa_error = bool(fail_on_qa_error)
        # 长篇原作全文（仅长篇分块模式使用；短篇时为空，避免污染 topic/theme）
        self.source_text = source_text or ""
        # 改编幅度：faithful=忠于原著 / light=轻度改编 / heavy=大幅改编
        # 空字符串 = 无原作约束（原创短剧不注入改编指令）
        self.fidelity = fidelity if fidelity in FIDELITY_LEVELS else ""
        # 生成调度模式：episode=逐集（默认）/ category=逐类
        self.generate_mode = generate_mode if generate_mode in GENERATE_MODES else "episode"

    @property
    def fidelity_label(self):
        """改编幅度的中文标签（用于日志/界面回显）；无约束时返回空串。"""
        return FIDELITY_LABELS.get(self.fidelity, "")

    @property
    def fidelity_instruction(self):
        """按当前语言生成的改编幅度 prompt 指令（原创项目返回空串）。"""
        level = FIDELITY_INSTRUCTIONS.get(self.fidelity)
        if not level:
            return ""
        if (self.language or "zh") == "en":
            return level["en"]
        return level["zh"]

    @property
    def full_topic(self):
        text = self.topic or "一个有趣的短剧故事"
        if self.instructions:
            text = f"{text}\n附加要求: {self.instructions}"
        return text

    @property
    def has_long_source(self):
        """是否携带长篇原作全文。"""
        return bool(self.source_text and self.source_text.strip())

    @property
    def aspect_wh(self):
        """解析 aspect_ratio + resolution 为 (width, height) 元组。

        1080P 档按标准尺寸；720P 档按短边 720 重算（此前 resolution 参数
        完全没被读取，选 720P 实际仍按 1080P 出片）。
        """
        ratio_map = {
            "16:9": (1920, 1080),
            "9:16": (1080, 1920),
            "1:1": (1024, 1024),
            "4:3": (1440, 1080),
            "3:4": (1080, 1440),
            "21:9": (2560, 1080),
        }
        w, h = ratio_map.get(self.aspect_ratio, (1920, 1080))
        if str(getattr(self, "resolution", "") or "").lower() == "720p":
            # 按短边 720 等比缩放，宽高对齐到 8 的倍数
            short = min(w, h)
            factor = 720.0 / short
            w = int(round(w * factor / 8)) * 8
            h = int(round(h * factor / 8)) * 8
        return w, h

    def to_dict(self):
        return {
            "topic": self.topic,
            "style": self.style,
            "episode_count": self.episode_count,
            "duration": self.duration,
            "use_video_gen": self.use_video_gen,
            "checkpoints": sorted(self.checkpoints),
            "voice_id": self.voice_id,
            "bgm_path": self.bgm_path,
            "existing_script_path": self.existing_script_path,
            "instructions": self.instructions,
            "language": self.language,
            "export_preset": self.export_preset,
            "blend_mode": self.blend_mode,
            "transition_duration": self.transition_duration,
            "aspect_ratio": self.aspect_ratio,
            "resolution": self.resolution,
            "seed": self.seed,
            "negative_prompt": self.negative_prompt,
            "shot_duration": self.shot_duration,
            "panel_count": self.panel_count,
            "allow_mock": self.allow_mock,
            "fail_on_qa_error": self.fail_on_qa_error,
            "source_text": self.source_text,
            "fidelity": self.fidelity,
            "generate_mode": self.generate_mode,
        }

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(
            topic=data.get("topic", ""),
            style=data.get("style", "都市"),
            episode_count=data.get("episode_count", 1),
            duration=data.get("duration", "智能时长"),
            use_video_gen=data.get("use_video_gen", True),
            checkpoints=data.get("checkpoints") or [],
            voice_id=data.get("voice_id"),
            bgm_path=data.get("bgm_path"),
            existing_script_path=data.get("existing_script_path"),
            instructions=data.get("instructions", ""),
            language=data.get("language", "zh"),
            export_preset=data.get("export_preset", "custom"),
            blend_mode=data.get("blend_mode", "crossfade"),
            transition_duration=data.get("transition_duration", 0.0),
            aspect_ratio=data.get("aspect_ratio", "16:9"),
            resolution=data.get("resolution", "1080p"),
            seed=data.get("seed"),
            negative_prompt=data.get("negative_prompt", ""),
            shot_duration=data.get("shot_duration", 0.0),
            panel_count=data.get("panel_count", 9),
            allow_mock=data.get("allow_mock", False),
            fail_on_qa_error=data.get("fail_on_qa_error", False),
            source_text=data.get("source_text", ""),
            fidelity=data.get("fidelity", ""),
            generate_mode=data.get("generate_mode", "episode"),
        )

    def validate_checkpoints(self):
        """过滤掉非法检查点阶段名。"""
        self.checkpoints = {c for c in self.checkpoints if c in STAGES}
        return self.checkpoints
