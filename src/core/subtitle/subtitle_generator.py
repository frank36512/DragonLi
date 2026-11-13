import re
from datetime import timedelta

# 与 video_composer.create_clip / create_video_clip 的音频缓冲保持一致
# 避免字幕时间轴与实际合成时长系统性漂移
CLIP_AUDIO_BUFFER = 1.0

class SubtitleGenerator:
    def __init__(self):
        pass

    @staticmethod
    def _strip_text_markers(text):
        """剥离（字幕：xxx）（标题：xxx）等叙事标记——这是给画面看的标注，
        不能作为字幕文本烧进视频。"""
        if not text:
            return text
        try:
            from core.storyboard.prompt_factory import _TEXT_MARKER_RE
            return _TEXT_MARKER_RE.sub("", text)
        except ImportError:
            import re
            return re.sub(r"[（(【\[]\s*(?:字幕|标题)\s*[:：][^）)】\]]*[）)】\]]", "", text)

    def format_timestamp(self, seconds):
        """Converts seconds to SRT timestamp format: HH:MM:SS,mmm"""
        td = timedelta(seconds=seconds)
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        millis = int(td.microseconds / 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

    def clean_subtitle_text(self, text):
        """
        Cleans subtitle text according to rules:
        1. No punctuation at the end, except ? and !
        2. Punctuation in the middle replaced by space.
        """
        if not text:
            return ""
            
        text = text.strip()
        
        # Define punctuation that should be handled
        punc_pattern = r"[.,;?:!，。；：？！、…—\"“”]"

        # 1. Separate trailing allowed punctuation (? ! ？！)
        # We want to keep the sequence of ?! at the end.
        allowed_end_pattern = r"([?!？！]+)$"
        match = re.search(allowed_end_pattern, text)
        
        trailing_allowed = ""
        content = text
        
        if match:
            trailing_allowed = match.group(1)
            content = text[:match.start()]
            
        # 2. Remove other trailing punctuation from content
        while content and re.search(punc_pattern + r"$", content):
             content = content[:-1].strip()
             
        # 3. Replace punctuation in middle of content with space
        content = re.sub(punc_pattern, ' ', content)
        
        # 4. Collapse spaces
        content = re.sub(r'\s+', ' ', content).strip()
        
        return content + trailing_allowed

    def strip_role_prefix(self, text):
        """剥离角色前缀（支持半角:和全角：）和尾部动作注释。"""
        if not text:
            return ""
        # 剥离角色前缀：角色名: 台词 或 角色名：台词
        text = re.sub(r'^[^:：]{1,10}[:：]\s*', '', text)
        # 剥离尾部动作注释：(动作) 或 （动作）
        text = re.sub(r'\s*\([^)]*\)\s*$', '', text)
        text = re.sub(r'\s*（[^）]*）\s*$', '', text)
        return text.strip()

    def split_long_cue(self, text, max_chars=16):
        """拆分超长 cue 为多条（按标点断行，每条 <= max_chars）。"""
        if not text or len(text) <= max_chars:
            return [text] if text else []
        
        # 按标点分句
        parts = re.split(r'([，。！？；、!?;])', text)
        sentences = []
        for i in range(0, len(parts) - 1, 2):
            s = parts[i] + parts[i+1]
            if s.strip():
                sentences.append(s.strip())
        if parts[-1].strip():
            sentences.append(parts[-1].strip())
        
        # 合并短句，拆分超长句
        cues = []
        current = ""
        for sent in sentences:
            if len(sent) > max_chars:
                # 超长句强制拆分
                if current:
                    cues.append(current)
                    current = ""
                for j in range(0, len(sent), max_chars):
                    cues.append(sent[j:j+max_chars])
            elif len(current) + len(sent) <= max_chars:
                current += sent
            else:
                if current:
                    cues.append(current)
                current = sent
        if current:
            cues.append(current)
        
        return cues  # 返回全部，不截断（截断会丢失台词内容）

    def generate_srt(self, storyboard, output_path):
        """
        Generates an SRT file from the storyboard panels.
        WB-8: 优先使用结构化对白 prompt_params._dialogues 生成逐行 cue；
        无对白时回退到 panel.description。
        """
        current_time = 0.0
        cue_index = 1
        
        with open(output_path, 'w', encoding='utf-8-sig') as f:
            for i, panel in enumerate(storyboard.panels):
                # 加缓冲对齐实际编码时长（create_clip/create_video_clip 会额外加音频缓冲）
                duration = getattr(panel, 'duration', 3.0) + CLIP_AUDIO_BUFFER
                panel_start = current_time
                
                # WB-8: 获取结构化对白
                dialogues = (getattr(panel, 'prompt_params', None) or {}).get("_dialogues") or []
                
                if dialogues:
                    # 逐行 cue：每条对白一条 cue，时长按字符数比例分配
                    total_chars = sum(len(d.get("content", "")) for d in dialogues) or 1
                    cue_start = current_time
                    for d in dialogues:
                        content = d.get("content", "")
                        if not content.strip():
                            continue
                        # 按字符比例分配时长
                        char_ratio = len(content) / total_chars
                        cue_duration = duration * char_ratio
                        cue_end = cue_start + cue_duration
                        
                        # 清理文本
                        clean = self.strip_role_prefix(content)
                        clean = self.clean_subtitle_text(clean)
                        clean = self._strip_text_markers(clean)
                        
                        # 拆分超长 cue
                        cues = self.split_long_cue(clean)
                        if not cues:
                            continue
                        sub_dur = cue_duration / len(cues)
                        sub_start = cue_start
                        for cue_text in cues:
                            if not cue_text.strip():
                                continue
                            sub_end = sub_start + sub_dur
                            f.write(f"{cue_index}\n")
                            f.write(f"{self.format_timestamp(sub_start)} --> {self.format_timestamp(sub_end)}\n")
                            f.write(f"{cue_text}\n\n")
                            cue_index += 1
                            sub_start = sub_end
                        cue_start = cue_end
                else:
                    # 回退：整面板一条 cue
                    text = panel.description or ""
                    # 剥离角色前缀和动作
                    text = self.strip_role_prefix(text)
                    text = self.clean_subtitle_text(text)
                    text = self._strip_text_markers(text)
                    
                    if text:
                        f.write(f"{cue_index}\n")
                        f.write(f"{self.format_timestamp(current_time)} --> {self.format_timestamp(current_time + duration)}\n")
                        f.write(f"{text}\n\n")
                        cue_index += 1
                
                current_time = panel_start + duration
        
        return output_path
