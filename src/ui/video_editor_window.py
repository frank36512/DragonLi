from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QListWidget, QProgressBar, QMessageBox, 
                             QFileDialog, QCheckBox, QGroupBox, QStackedWidget,
                             QFrame, QLineEdit, QGridLayout, QDialog, QRadioButton,
                             QButtonGroup, QScrollArea, QSlider, QListWidgetItem,
                             QSplitter, QTimeEdit, QSpinBox, QComboBox, QMenu,
                             QToolButton, QApplication, QStyle, QTextEdit, QTabWidget,
                             QFontComboBox, QColorDialog, QFormLayout, QStackedLayout)
from PyQt6.QtGui import QPixmap, QFont, QColor, QAction, QIcon, QPainter, QPen, QBrush, QDrag, QCursor, QImage
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QRect, QTimer, QUrl, QTime, QMimeData, QPoint
from PyQt6.QtWidgets import QSizePolicy
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtMultimedia import QVideoSink
import os
import json
import re
import shutil
import struct
from core.synthesis.video_composer import VideoComposer
try:
    from core.synthesis.export_preset import list_presets, get_preset, preset_keys
except ImportError:
    from src.core.synthesis.export_preset import list_presets, get_preset, preset_keys
from ai_engine.audio.tts_client import TTSClient
from ui.video_gen_window import VideoEnhanceDialog
from ui import theme as _theme

try:
    from core.utils.json_store import atomic_write_json
except ImportError:
    from src.core.utils.json_store import atomic_write_json

class MultiTrackVideoPreview(QWidget):
    """多轨道视频合成预览组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #000;")
        self.setMinimumSize(320, 180)
        
        self._players = []
        self._video_sinks = []
        self._audio_outputs = []
        self._clips = []
        self._current_frames = {}
        self._selected_clip_index = -1
        
        self._preview_label = QLabel(self)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet("background-color: transparent;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._preview_label)
        
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._compose_frames)
        self._frame_timer.start(33)
    
    def set_clips(self, clips_info):
        """
        设置要播放的视频片段
        clips_info: [(clip, track_index), ...] 按轨道从下到上排序
        """
        for player in self._players:
            player.stop()
            player.setSource(QUrl())
        
        self._players.clear()
        self._video_sinks.clear()
        self._audio_outputs.clear()
        self._clips.clear()
        self._current_frames.clear()
        
        for clip, track_idx in clips_info:
            if not hasattr(clip, 'path'):
                continue
            
            player = QMediaPlayer()
            audio_output = QAudioOutput()
            audio_output.setVolume(0 if track_idx > 0 else 1)
            player.setAudioOutput(audio_output)
            
            video_sink = QVideoSink()
            player.setVideoOutput(video_sink)
            video_sink.videoFrameChanged.connect(
                lambda frame, idx=len(self._clips): self._on_frame_ready(frame, idx)
            )
            
            player.setSource(QUrl.fromLocalFile(clip.path))
            
            self._players.append(player)
            self._video_sinks.append(video_sink)
            self._audio_outputs.append(audio_output)
            self._clips.append((clip, track_idx))
        
        self._selected_clip_index = len(self._clips) - 1 if self._clips else -1
    
    def set_selected_clip(self, clip):
        """设置当前选中的片段"""
        for i, (c, _) in enumerate(self._clips):
            if c == clip:
                self._selected_clip_index = i
                return
        self._selected_clip_index = -1
    
    def play(self, start_time=0):
        """播放所有视频"""
        for i, (player, (clip, _)) in enumerate(zip(self._players, self._clips)):
            clip_start = clip.start_time or 0
            offset = max(0, start_time - clip_start)
            player.setPosition(int(offset * 1000))
            player.play()
    
    def pause(self):
        """暂停所有视频"""
        for player in self._players:
            player.pause()
    
    def stop(self):
        """停止所有视频"""
        for player in self._players:
            player.stop()
    
    def seek(self, time_seconds):
        """跳转到指定时间"""
        for player, (clip, _) in zip(self._players, self._clips):
            clip_start = clip.start_time or 0
            offset = max(0, time_seconds - clip_start)
            player.setPosition(int(offset * 1000))
    
    def _on_frame_ready(self, frame, clip_index):
        """当视频帧准备好时"""
        if frame.isValid():
            self._current_frames[clip_index] = frame
    
    def _compose_frames(self):
        """合成所有视频帧"""
        if not self._clips:
            self._preview_label.clear()
            self._preview_label.setText("无内容")
            return
        
        canvas_size = self.size()
        canvas = QImage(canvas_size, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.black)
        
        painter = QPainter(canvas)
        
        for i in range(len(self._clips)):
            if i not in self._current_frames:
                continue
            
            frame = self._current_frames[i]
            clip, track_idx = self._clips[i]
            
            image = frame.toImage()
            if image.isNull():
                continue
            
            preview_x = getattr(clip, 'preview_x', 0.0)
            preview_y = getattr(clip, 'preview_y', 0.0)
            preview_width = getattr(clip, 'preview_width', 1.0)
            preview_height = getattr(clip, 'preview_height', 1.0)
            
            target_x = int(canvas_size.width() * preview_x)
            target_y = int(canvas_size.height() * preview_y)
            target_w = int(canvas_size.width() * preview_width)
            target_h = int(canvas_size.height() * preview_height)
            
            scaled = image.scaled(target_w, target_h, 
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            
            actual_w = scaled.width()
            actual_h = scaled.height()
            offset_x = (target_w - actual_w) // 2
            offset_y = (target_h - actual_h) // 2
            
            painter.drawImage(target_x + offset_x, target_y + offset_y, scaled)
        
        painter.end()
        
        self._preview_label.setPixmap(QPixmap.fromImage(canvas))
        self._preview_label.setGeometry(0, 0, canvas_size.width(), canvas_size.height())


class SubtitleItem:
    def __init__(self, text, start_time, end_time, style=None):
        self.text = text
        self.start_time = start_time
        self.end_time = end_time
        self.style = style or {
            'font_family': 'Microsoft YaHei',
            'font_size': 24,
            'color': '#ffffff',
            'outline_color': '#000000',
            'position': 'bottom'
        }
        
    def to_dict(self):
        return {
            'text': self.text,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'style': self.style
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(data['text'], data['start_time'], data['end_time'], data.get('style'))

class TextOverlay:
    def __init__(self, text, x, y, start_time=0, end_time=None, style=None):
        self.text = text
        self.x = x
        self.y = y
        self.start_time = start_time
        self.end_time = end_time
        self.style = style or {
            'font_family': 'Microsoft YaHei',
            'font_size': 36,
            'color': '#ffffff',
            'outline_color': '#000000',
            'bold': False,
            'italic': False
        }
        
    def to_dict(self):
        return {
            'text': self.text,
            'x': self.x,
            'y': self.y,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'style': self.style
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(data['text'], data['x'], data['y'], data.get('start_time', 0), data.get('end_time'), data.get('style'))

class AudioTrack:
    def __init__(self, path, name=None, start_time=0, volume=1.0, is_tts=False, text=""):
        self.path = path
        self.name = name or os.path.basename(path)
        self.start_time = start_time
        self.volume = volume
        self.is_tts = is_tts
        self.text = text
        self.duration = 0
        self.muted = False
        self.fade_in = 0.0
        self.fade_out = 0.0
        self.noise_reduction = False
        
    def to_dict(self):
        return {
            'path': self.path,
            'name': self.name,
            'start_time': self.start_time,
            'volume': self.volume,
            'is_tts': self.is_tts,
            'text': self.text,
            'duration': self.duration,
            'muted': self.muted,
            'fade_in': self.fade_in,
            'fade_out': self.fade_out,
            'noise_reduction': self.noise_reduction
        }
    
    @classmethod
    def from_dict(cls, data):
        track = cls(data['path'], data.get('name'), data.get('start_time', 0), data.get('volume', 1.0), data.get('is_tts', False), data.get('text', ''))
        track.duration = data.get('duration', 0)
        track.muted = data.get('muted', False)
        track.fade_in = data.get('fade_in', 0.0)
        track.fade_out = data.get('fade_out', 0.0)
        track.noise_reduction = data.get('noise_reduction', False)
        return track

class VideoEffect:
    FILTER_TYPES = {
        'none': {'name': '无效果', 'params': {}},
        'grayscale': {'name': '黑白', 'params': {}},
        'sepia': {'name': '复古', 'params': {'intensity': 1.0}},
        'blur': {'name': '模糊', 'params': {'radius': 5}},
        'sharpen': {'name': '锐化', 'params': {'amount': 1.0}},
        'vintage': {'name': '怀旧', 'params': {}},
        'warm': {'name': '暖色调', 'params': {'temperature': 20}},
        'cool': {'name': '冷色调', 'params': {'temperature': -20}},
        'contrast': {'name': '高对比', 'params': {'contrast': 1.2}},
        'bright': {'name': '明亮', 'params': {'brightness': 0.1}},
        'dark': {'name': '暗调', 'params': {'brightness': -0.1}},
        'saturate': {'name': '饱和', 'params': {'saturation': 1.5}},
        'desaturate': {'name': '低饱和', 'params': {'saturation': 0.5}},
        'invert': {'name': '反色', 'params': {}},
        'vignette': {'name': '晕影', 'params': {'angle': 45}},
        'pixelate': {'name': '马赛克', 'params': {'size': 8}},
        'noise': {'name': '噪点', 'params': {'amount': 10}},
        'mirror_h': {'name': '水平镜像', 'params': {}},
        'mirror_v': {'name': '垂直镜像', 'params': {}},
        'rotate_90': {'name': '旋转90°', 'params': {}},
        'rotate_180': {'name': '旋转180°', 'params': {}},
        'rotate_270': {'name': '旋转270°', 'params': {}},
    }
    
    def __init__(self, filter_type='none', params=None, speed=1.0):
        self.filter_type = filter_type
        self.params = params or {}
        self.speed = speed
        self.brightness = 0
        self.contrast = 1.0
        self.saturation = 1.0
        self.gamma = 1.0
        
    def to_dict(self):
        return {
            'filter_type': self.filter_type,
            'params': self.params,
            'speed': self.speed,
            'brightness': self.brightness,
            'contrast': self.contrast,
            'saturation': self.saturation,
            'gamma': self.gamma
        }
    
    @classmethod
    def from_dict(cls, data):
        effect = cls(data.get('filter_type', 'none'), data.get('params'), data.get('speed', 1.0))
        effect.brightness = data.get('brightness', 0)
        effect.contrast = data.get('contrast', 1.0)
        effect.saturation = data.get('saturation', 1.0)
        effect.gamma = data.get('gamma', 1.0)
        return effect
    
    def get_ffmpeg_filter(self):
        filters = []
        
        if self.filter_type == 'grayscale':
            filters.append('colorchannelmixer=.3:.4:.3:0:.3:.4:.3:0:.3:.4:.3')
        elif self.filter_type == 'sepia':
            filters.append('colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131')
        elif self.filter_type == 'blur':
            radius = self.params.get('radius', 5)
            filters.append(f'boxblur={radius}:{radius}')
        elif self.filter_type == 'sharpen':
            filters.append('unsharp=5:5:1.0:5:5:0.0')
        elif self.filter_type == 'vintage':
            filters.append('curves=vintage')
        elif self.filter_type == 'warm':
            temp = self.params.get('temperature', 20)
            filters.append(f'colorbalance=rs={temp/100}:gs=0:bs={-temp/100}')
        elif self.filter_type == 'cool':
            temp = self.params.get('temperature', -20)
            filters.append(f'colorbalance=rs={temp/100}:gs=0:bs={-temp/100}')
        elif self.filter_type == 'invert':
            filters.append('negate')
        elif self.filter_type == 'contrast':
            # 高对比：与预览 convertScaleAbs(alpha=1.5, beta=-30) 对齐
            filters.append('eq=contrast=1.5:brightness=-0.117647')
        elif self.filter_type == 'bright':
            # 明亮：与预览 convertScaleAbs(alpha=1.0, beta=40) 对齐
            filters.append('eq=brightness=0.156863')
        elif self.filter_type == 'dark':
            # 暗调：与预览 convertScaleAbs(alpha=0.8, beta=-20) 对齐
            filters.append('eq=contrast=0.8:brightness=-0.078431')
        elif self.filter_type == 'saturate':
            filters.append('eq=saturation=1.5')
        elif self.filter_type == 'desaturate':
            filters.append('eq=saturation=0.5')
        elif self.filter_type == 'vignette':
            angle = self.params.get('angle', 45)
            filters.append(f'vignette=a={angle}/57.3')
        elif self.filter_type == 'pixelate':
            # 真马赛克：用 pixelize 做块状像素化（与预览的下采样+最近邻放大一致），
            # 此前误用 boxblur，导出的是模糊而非马赛克
            size = max(2, int(self.params.get('size', 8)))
            filters.append(f'pixelize=w={size}:h={size}:mode=avg')
        elif self.filter_type == 'noise':
            amount = self.params.get('amount', 10)
            filters.append(f'noise=alls={amount}:allf=t')
        elif self.filter_type == 'mirror_h':
            filters.append('hflip')
        elif self.filter_type == 'mirror_v':
            filters.append('vflip')
        elif self.filter_type == 'rotate_90':
            filters.append('transpose=1')
        elif self.filter_type == 'rotate_180':
            filters.append('transpose=1,transpose=1')
        elif self.filter_type == 'rotate_270':
            filters.append('transpose=2')
        
        eq_parts = []
        if self.brightness != 0:
            eq_parts.append(f'brightness={self.brightness}')
        if self.contrast != 1.0:
            eq_parts.append(f'contrast={self.contrast}')
        if self.saturation != 1.0:
            eq_parts.append(f'saturation={self.saturation}')
        if self.gamma != 1.0:
            eq_parts.append(f'gamma={self.gamma}')
            
        if eq_parts:
            filters.append('eq=' + ':'.join(eq_parts))
            
        return ','.join(filters) if filters else None

class VideoClip:
    def __init__(self, path, name=None, start_time=0, end_time=None, duration=None):
        self.path = path
        self.name = name or (os.path.basename(path) if path else "未命名片段")
        self.start_time = start_time
        self.end_time = end_time
        self.duration = duration
        self.transition = None
        self.transition_duration = 0.5
        self.subtitles = []
        self.text_overlays = []
        self.audio_tracks = []
        self.effect = VideoEffect()
        self.separate_audio = False
        self.audio_volume = 1.0
        self.audio_muted = False
        self.preview_x = 0.0
        self.preview_y = 0.0
        self.preview_width = 1.0
        self.preview_height = 1.0
        
    def to_dict(self):
        return {
            'path': self.path,
            'name': self.name,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': self.duration,
            'transition': self.transition,
            'transition_duration': self.transition_duration,
            'subtitles': [s.to_dict() for s in self.subtitles],
            'text_overlays': [t.to_dict() for t in self.text_overlays],
            'audio_tracks': [a.to_dict() for a in self.audio_tracks],
            'effect': self.effect.to_dict(),
            'separate_audio': self.separate_audio,
            'audio_volume': self.audio_volume,
            'audio_muted': self.audio_muted,
            'preview_x': self.preview_x,
            'preview_y': self.preview_y,
            'preview_width': self.preview_width,
            'preview_height': self.preview_height
        }
    
    @classmethod
    def from_dict(cls, data):
        clip = cls(data['path'], data.get('name'), data.get('start_time', 0), data.get('end_time'), data.get('duration'))
        clip.transition = data.get('transition')
        clip.transition_duration = data.get('transition_duration', 0.5)
        clip.subtitles = [SubtitleItem.from_dict(s) for s in data.get('subtitles', [])]
        clip.text_overlays = [TextOverlay.from_dict(t) for t in data.get('text_overlays', [])]
        clip.audio_tracks = [AudioTrack.from_dict(a) for a in data.get('audio_tracks', [])]
        clip.effect = VideoEffect.from_dict(data.get('effect', {}))
        clip.separate_audio = data.get('separate_audio', False)
        clip.audio_volume = data.get('audio_volume', 1.0)
        clip.audio_muted = data.get('audio_muted', False)
        clip.preview_x = data.get('preview_x', 0.0)
        clip.preview_y = data.get('preview_y', 0.0)
        clip.preview_width = data.get('preview_width', 1.0)
        clip.preview_height = data.get('preview_height', 1.0)
        return clip

class SubtitleOverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.subtitles = []
        self.text_overlays = []
        self.current_time = 0
        # 设置透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 确保控件可见
        self.setVisible(True)
        
    def set_subtitles(self, subtitles):
        self.subtitles = subtitles or []
        self.update()
        
    def set_text_overlays(self, overlays):
        self.text_overlays = overlays or []
        self.update()
        
    def set_current_time(self, time):
        self.current_time = time
        self.update()
        
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 调试：绘制半透明背景以确认控件存在
        # painter.fillRect(self.rect(), QColor(255, 0, 0, 50))

        for subtitle in self.subtitles:
            if hasattr(subtitle, 'start_time') and hasattr(subtitle, 'end_time'):
                if subtitle.start_time <= self.current_time <= subtitle.end_time:
                    style = subtitle.style if hasattr(subtitle, 'style') else {}
                    font_family = style.get('font_family', 'Microsoft YaHei')
                    font_size = style.get('font_size', 24)
                    color = style.get('color', '#ffffff')
                    outline_color = style.get('outline_color', '#000000')
                    position = style.get('position', 'bottom')
                    
                    font = QFont(font_family, font_size)
                    font.setBold(True)
                    painter.setFont(font)
                    
                    text = subtitle.text
                    text_width = painter.fontMetrics().horizontalAdvance(text)
                    text_height = painter.fontMetrics().height()
                    
                    if position == 'bottom':
                        x = (self.width() - text_width) // 2
                        y = self.height() - 80
                    elif position == 'top':
                        x = (self.width() - text_width) // 2
                        y = 50
                    else:
                        x = (self.width() - text_width) // 2
                        y = (self.height() - text_height) // 2
                    
                    text_rect = QRect(x - 10, y - text_height, text_width + 20, text_height + 20)
                    
                    # 修复：先绘制描边（使用画笔）
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(outline_color))
                    for dx in [-3, -2, -1, 0, 1, 2, 3]:
                        for dy in [-3, -2, -1, 0, 1, 2, 3]:
                            if dx != 0 or dy != 0:
                                painter.drawText(text_rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, text)
                    
                    # 再绘制文字
                    painter.setPen(QColor(color))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
        
        for overlay in self.text_overlays:
            if hasattr(overlay, 'start_time') and hasattr(overlay, 'end_time'):
                if overlay.start_time <= self.current_time <= overlay.end_time:
                    style = overlay.style if hasattr(overlay, 'style') else {}
                    font_family = style.get('font_family', 'Microsoft YaHei')
                    font_size = style.get('font_size', 36)
                    color = style.get('color', '#ffffff')
                    outline_color = style.get('outline_color', '#000000')
                    bold = style.get('bold', False)
                    italic = style.get('italic', False)
                    
                    font = QFont(font_family, font_size)
                    font.setBold(bold)
                    font.setItalic(italic)
                    painter.setFont(font)
                    
                    x = int(overlay.x * self.width() / 100)
                    y = int(overlay.y * self.height() / 100)
                    
                    text = overlay.text
                    text_width = painter.fontMetrics().horizontalAdvance(text)
                    text_height = painter.fontMetrics().height()
                    
                    text_rect = QRect(x - text_width // 2, y - text_height // 2, text_width, text_height)
                    
                    # 修复：先绘制描边（使用画笔）
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(outline_color))
                    for dx in [-2, -1, 0, 1, 2]:
                        for dy in [-2, -1, 0, 1, 2]:
                            if dx != 0 or dy != 0:
                                painter.drawText(text_rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, text)
                    
                    # 再绘制文字
                    painter.setPen(QColor(color))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

class TimelineWidget(QWidget):
    clip_selected = pyqtSignal(int, int)
    clip_double_clicked = pyqtSignal(int, int)
    time_clicked = pyqtSignal(float)
    time_dragged = pyqtSignal(float)
    clips_changed = pyqtSignal(list)
    zoom_changed = pyqtSignal(float)
    height_changed = pyqtSignal(int)
    edit_started = pyqtSignal()  # 开始编辑（拖拽/调整大小）
    edit_finished = pyqtSignal()  # 结束编辑（拖拽/调整大小完成）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tracks = []
        self.track_types = []
        self.selected_track = -1
        self.selected_index = -1
        self.selected_track_only = -1
        self.setMinimumWidth(400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMaximumHeight(10000)
        self.setMouseTracking(True)
        self.hover_track = -1
        self.hover_index = -1
        self.playback_position = 0
        self.setAcceptDrops(True)
        self.drag_over = False
        self.dragging_playhead = False
        self.zoom_scale = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 5.0
        self.pixels_per_second = 50
        self.scroll_offset = 0
        self.dragging_clip = None
        self.drag_start_x = 0
        self.drag_clip_start_time = 0
        self.track_height = 60
        self.track_spacing = 5
        self.header_width = 80
        self._resizing = False
        self._resize_start_y = 0
        self._resize_start_height = 0
        self._top_resize_area = 30
        
        # 边缘拖拽调整时长相关
        self._resizing_clip = None  # (track_idx, clip_idx, 'left' or 'right')
        self._resize_edge_width = 8  # 边缘检测宽度
        self._drag_start_duration = 0
        
        self.add_track("轨道1", "video", insert_at=0)
        self.add_track("轨道2", "video", insert_at=1)
        self.add_track("轨道3", "video", insert_at=2)
        
        self._update_minimum_height()
        
    def _update_minimum_height(self):
        ruler_height = 22
        track_count = len(self.tracks)
        total_height = ruler_height + track_count * (self.track_height + self.track_spacing) + 10
        self.setMinimumHeight(total_height)
        
    def add_track(self, name, track_type, insert_at=0):
        self.tracks.insert(insert_at, [])
        self.track_types.insert(insert_at, {"name": name, "type": track_type})
        self._update_minimum_height()
        self.updateGeometry()
        self.update()
    
    def set_fixed_height(self, height):
        self.setFixedHeight(height)
        self.height_changed.emit(height)
    
    def is_time_occupied(self, track_idx, start_time, duration, exclude_clip=None):
        if track_idx < 0 or track_idx >= len(self.tracks):
            return False
        track = self.tracks[track_idx]
        end_time = start_time + duration
        for clip in track:
            if clip is exclude_clip:
                continue
            clip_start = clip.start_time or 0
            clip_end = clip_start + (clip.duration or 0)
            if not (end_time <= clip_start or start_time >= clip_end):
                return True
        return False
    
    def find_available_track_for_time(self, start_time, duration, preferred_type="video"):
        for track_idx, track_info in enumerate(self.track_types):
            if track_info["type"] == preferred_type:
                if not self.is_time_occupied(track_idx, start_time, duration):
                    return track_idx
        track_count = len(self.tracks)
        track_name = f"轨道{track_count + 1}"
        self.add_track(track_name, preferred_type, insert_at=0)
        return 0
    
    def add_clip_at_playhead(self, clip):
        start_time = self.playback_position
        duration = clip.duration or 1
        
        preferred_type = "video"
        if hasattr(clip, 'clip_type'):
            preferred_type = clip.clip_type
        elif hasattr(clip, 'audio_only') and clip.audio_only:
            preferred_type = "audio"
        
        track_idx = self.find_available_track_for_time(start_time, duration, preferred_type)
        
        clip.start_time = start_time
        self.tracks[track_idx].append(clip)
        self.update()
        return track_idx, len(self.tracks[track_idx]) - 1
        
    @property
    def clips(self):
        if self.tracks:
            return self.tracks[0]
        return []
        
    @clips.setter
    def clips(self, value):
        if self.tracks:
            self.tracks[0] = value
        else:
            self.tracks.append(value)
        
    def remove_track(self, index):
        if 0 <= index < len(self.tracks) and len(self.tracks) > 1:
            self.tracks.pop(index)
            self.track_types.pop(index)
            if self.selected_track == index:
                self.selected_track = -1
                self.selected_index = -1
            self._update_minimum_height()
            self.updateGeometry()
            self.update()

    def clear_track(self, index):
        """清空轨道内容"""
        if 0 <= index < len(self.tracks):
            self.tracks[index] = []
            if self.selected_track == index:
                self.selected_index = -1
            self.update()

    def is_track_locked(self, index):
        """检查轨道是否被锁定"""
        if 0 <= index < len(self.track_types):
            return self.track_types[index].get('locked', False)
        return False

    def set_track_locked(self, index, locked):
        """设置轨道锁定状态"""
        if 0 <= index < len(self.track_types):
            self.track_types[index]['locked'] = locked
            self.update()

    def contextMenuEvent(self, event):
        """右键菜单事件"""
        from PyQt6.QtWidgets import QMenu

        mouse_pos = event.pos()
        ruler_height = 22

        # 检查是否点击在片段上
        track_idx, clip_idx = self.get_clip_at_pos(mouse_pos)
        if clip_idx >= 0:
            self.show_clip_context_menu(event.globalPos(), track_idx, clip_idx)
            return

        # 检查是否点击在轨道头部区域
        if mouse_pos.y() >= ruler_height and mouse_pos.x() < self.header_width:
            track_idx = int((mouse_pos.y() - ruler_height) / (self.track_height + self.track_spacing))
            if 0 <= track_idx < len(self.tracks):
                self.show_track_context_menu(event.globalPos(), track_idx)
                return

        # 检查是否点击在轨道内容区域
        if mouse_pos.y() >= ruler_height and mouse_pos.x() >= self.header_width:
            track_idx = int((mouse_pos.y() - ruler_height) / (self.track_height + self.track_spacing))
            if 0 <= track_idx < len(self.tracks):
                self.show_track_context_menu(event.globalPos(), track_idx)
                return

    def show_track_context_menu(self, pos, track_idx):
        """显示轨道右键菜单"""
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("panel2") + """;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: """ + _theme.color("accent") + """;
            }
            QMenu::separator {
                height: 1px;
                background-color: """ + _theme.color("panel2") + """;
                margin: 5px 0;
            }
        """)

        track_name = self.track_types[track_idx]['name']
        is_locked = self.is_track_locked(track_idx)

        # 轨道信息
        info_action = menu.addAction(f"轨道: {track_name}")
        info_action.setEnabled(False)
        menu.addSeparator()

        # 添加新轨道
        add_track_action = menu.addAction("➕ 添加新轨道")
        add_track_action.triggered.connect(lambda: self.add_track_menu_clicked(track_idx))

        # 删除轨道
        if len(self.tracks) > 1 and not is_locked:
            remove_track_action = menu.addAction("➖ 删除轨道")
            remove_track_action.triggered.connect(lambda: self.remove_track_menu_clicked(track_idx))

        menu.addSeparator()

        # 清空轨道内容
        if not is_locked:
            clear_action = menu.addAction("🗑️ 清空轨道内容")
            clear_action.triggered.connect(lambda: self.clear_track_menu_clicked(track_idx))

        # 锁定/解锁轨道
        if is_locked:
            unlock_action = menu.addAction("🔓 解锁轨道")
            unlock_action.triggered.connect(lambda: self.toggle_track_lock(track_idx))
        else:
            lock_action = menu.addAction("🔒 锁定轨道")
            lock_action.triggered.connect(lambda: self.toggle_track_lock(track_idx))

        menu.exec(pos)

    def add_track_menu_clicked(self, after_track_idx):
        """从菜单添加轨道"""
        track_count = len(self.tracks)
        track_name = f"轨道{track_count + 1}"
        self.add_track(track_name, "video", insert_at=after_track_idx + 1)

    def remove_track_menu_clicked(self, track_idx):
        """从菜单删除轨道"""
        from PyQt6.QtWidgets import QMessageBox

        if len(self.tracks) <= 1:
            QMessageBox.warning(self, "提示", "至少需要保留一个轨道")
            return

        track_name = self.track_types[track_idx]['name']
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除 {track_name} 吗？\n轨道上的所有片段将被删除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.remove_track(track_idx)

    def clear_track_menu_clicked(self, track_idx):
        """从菜单清空轨道"""
        from PyQt6.QtWidgets import QMessageBox

        track_name = self.track_types[track_idx]['name']
        clip_count = len(self.tracks[track_idx])

        if clip_count == 0:
            QMessageBox.information(self, "提示", f"{track_name} 已经是空的")
            return

        reply = QMessageBox.question(
            self,
            "确认清空",
            f"确定要清空 {track_name} 吗？\n这将删除轨道上的 {clip_count} 个片段。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.clear_track(track_idx)

    def toggle_track_lock(self, track_idx):
        """切换轨道锁定状态"""
        is_locked = self.is_track_locked(track_idx)
        self.set_track_locked(track_idx, not is_locked)

    def show_clip_context_menu(self, pos, track_idx, clip_idx):
        """显示片段右键菜单"""
        from PyQt6.QtWidgets import QMenu, QMessageBox

        clip = self.tracks[track_idx][clip_idx]
        is_locked = self.is_track_locked(track_idx)

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("panel2") + """;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: """ + _theme.color("accent") + """;
            }
            QMenu::separator {
                height: 1px;
                background-color: """ + _theme.color("panel2") + """;
                margin: 5px 0;
            }
        """)

        # 片段信息
        info_action = menu.addAction(f"片段: {clip.name}")
        info_action.setEnabled(False)
        menu.addSeparator()

        # 复制片段
        copy_action = menu.addAction("📋 复制片段")
        copy_action.triggered.connect(lambda: self.copy_clip(track_idx, clip_idx))

        # 删除片段
        if not is_locked:
            delete_action = menu.addAction("🗑️ 删除片段")
            delete_action.triggered.connect(lambda: self.delete_clip(track_idx, clip_idx))

        menu.addSeparator()

        # 分割片段
        if not is_locked:
            split_action = menu.addAction("✂️ 在当前位置分割")
            split_action.triggered.connect(lambda: self.split_clip_at_position(track_idx, clip_idx))

        # 设置时长
        if not is_locked:
            duration_action = menu.addAction("⏱️ 设置时长")
            duration_action.triggered.connect(lambda: self.set_clip_duration_dialog(track_idx, clip_idx))

        menu.addSeparator()

        # 特效和转场
        if not is_locked:
            effect_action = menu.addAction("✨ 视频特效")
            effect_action.triggered.connect(lambda: self.open_clip_effect_dialog(track_idx, clip_idx))

            transition_action = menu.addAction("🎬 转场效果")
            transition_action.triggered.connect(lambda: self.open_clip_transition_dialog(track_idx, clip_idx))

        menu.addSeparator()

        # 移动到轨道
        if not is_locked and len(self.tracks) > 1:
            move_menu = menu.addMenu("📤 移动到轨道")
            for i, track_info in enumerate(self.track_types):
                if i != track_idx:
                    move_action = move_menu.addAction(f"{track_info['name']}")
                    move_action.triggered.connect(lambda checked, t=i: self.move_clip_to_track(track_idx, clip_idx, t))

        menu.addSeparator()

        # 音频相关
        if hasattr(clip, 'audio_tracks') and clip.audio_tracks:
            mute_action = menu.addAction("🔇 静音" if not getattr(clip, 'audio_muted', False) else "🔊 取消静音")
            mute_action.triggered.connect(lambda: self.toggle_clip_mute(track_idx, clip_idx))

        # 分离音频
        if not is_locked and hasattr(clip, 'path') and clip.path:
            separate_action = menu.addAction("🔊 分离音频")
            separate_action.triggered.connect(lambda: self.separate_clip_audio(track_idx, clip_idx))

        menu.exec(pos)

    def copy_clip(self, track_idx, clip_idx):
        """复制片段到剪贴板"""
        clip = self.tracks[track_idx][clip_idx]
        # 创建片段副本
        import copy
        clip_copy = copy.deepcopy(clip)
        clip_duration = clip_copy.duration or 1
        
        # 尝试在原轨道找到一个不重叠的位置
        new_start_time = (clip.start_time or 0) + clip_duration
        if self.is_time_occupied(track_idx, new_start_time, clip_duration):
            # 如果原轨道被占用，尝试找到一个可用轨道
            preferred_type = self.track_types[track_idx].get("type", "video") if track_idx < len(self.track_types) else "video"
            new_track_idx = self.find_available_track_for_time(new_start_time, clip_duration, preferred_type)
            clip_copy.start_time = new_start_time
            clip_copy.name = f"{clip.name} 副本"
            self.tracks[new_track_idx].append(clip_copy)
        else:
            clip_copy.start_time = new_start_time
            clip_copy.name = f"{clip.name} 副本"
            self.tracks[track_idx].append(clip_copy)
        self.update()

    def delete_clip(self, track_idx, clip_idx):
        """删除片段"""
        from PyQt6.QtWidgets import QMessageBox

        clip = self.tracks[track_idx][clip_idx]
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除片段 '{clip.name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.tracks[track_idx].pop(clip_idx)
            if self.selected_track == track_idx and self.selected_index == clip_idx:
                self.selected_index = -1
            self.update()

    def split_clip_at_position(self, track_idx, clip_idx):
        """在当前播放位置分割片段"""
        clip = self.tracks[track_idx][clip_idx]
        split_time = self.playback_position

        clip_start = clip.start_time or 0
        clip_duration = clip.duration or 1
        clip_end = clip_start + clip_duration

        # 检查播放位置是否在片段内
        if split_time <= clip_start or split_time >= clip_end:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "播放位置须在片段内部才能分割")
            return

        import copy
        # 创建第二个片段
        second_clip = copy.deepcopy(clip)
        second_clip.start_time = split_time
        second_clip.duration = clip_end - split_time

        # 检查分割后的第二个片段是否会与其他片段重叠（排除原片段）
        if self.is_time_occupied(track_idx, second_clip.start_time, second_clip.duration, exclude_clip=clip):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "分割后的片段会与其他片段重叠，无法分割")
            return

        # 调整第一个片段的时长
        clip.duration = split_time - clip_start

        # 修复：将第二个片段插入到原位置之后，而不是 append 到末尾
        self.tracks[track_idx].insert(clip_idx + 1, second_clip)
        self.update()

    def set_clip_duration_dialog(self, track_idx, clip_idx):
        """打开设置片段时长对话框"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDoubleSpinBox, QPushButton, QHBoxLayout

        clip = self.tracks[track_idx][clip_idx]

        dialog = QDialog(self)
        dialog.setWindowTitle("设置片段时长")
        dialog.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        dialog.resize(300, 150)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        layout.addWidget(QLabel(f"片段: {clip.name}"))

        layout.addWidget(QLabel("时长 (秒):"))
        duration_spin = QDoubleSpinBox()
        duration_spin.setRange(0.1, 9999)
        duration_spin.setValue(clip.duration or 1)
        duration_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        layout.addWidget(duration_spin)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 8px;")
        cancel_btn.clicked.connect(dialog.reject)

        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; padding: 8px;")
        ok_btn.clicked.connect(dialog.accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            clip.duration = duration_spin.value()
            self.update()

    def toggle_clip_mute(self, track_idx, clip_idx):
        """切换片段静音状态"""
        clip = self.tracks[track_idx][clip_idx]
        clip.audio_muted = not getattr(clip, 'audio_muted', False)
        self.update()

    def separate_clip_audio(self, track_idx, clip_idx):
        """分离片段音频"""
        # 发送信号到主窗口处理
        self.selected_track = track_idx
        self.selected_index = clip_idx
        self.clip_selected.emit(track_idx, clip_idx)
        # 触发分离音频操作（通过主窗口）
        if hasattr(self.parent(), 'separate_audio_from_clip'):
            self.parent().separate_audio_from_clip()

    def open_clip_effect_dialog(self, track_idx, clip_idx):
        """打开片段特效对话框（通过主窗口）"""
        self.selected_track = track_idx
        self.selected_index = clip_idx
        self.clip_selected.emit(track_idx, clip_idx)
        if hasattr(self.parent(), 'open_effects'):
            self.parent().open_effects()

    def open_clip_transition_dialog(self, track_idx, clip_idx):
        """打开片段转场对话框（通过主窗口）"""
        self.selected_track = track_idx
        self.selected_index = clip_idx
        self.clip_selected.emit(track_idx, clip_idx)
        if hasattr(self.parent(), 'open_transition_dialog'):
            self.parent().open_transition_dialog()

    def move_clip_to_track(self, from_track_idx, clip_idx, to_track_idx):
        """移动片段到另一个轨道"""
        if from_track_idx == to_track_idx:
            return

        if not (0 <= from_track_idx < len(self.tracks) and 0 <= to_track_idx < len(self.tracks)):
            return

        if not (0 <= clip_idx < len(self.tracks[from_track_idx])):
            return

        clip = self.tracks[from_track_idx][clip_idx]
        clip_duration = clip.duration or 0
        clip_start = clip.start_time or 0

        # 检查目标轨道是否有重叠
        if self.is_time_occupied(to_track_idx, clip_start, clip_duration):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "目标轨道该时间段被占用，无法移动")
            return

        # 移动片段
        clip = self.tracks[from_track_idx].pop(clip_idx)
        self.tracks[to_track_idx].append(clip)

        # 更新选中状态
        self.selected_track = to_track_idx
        self.selected_index = len(self.tracks[to_track_idx]) - 1

        self.update()

    def get_clips(self, track_index):
        if 0 <= track_index < len(self.tracks):
            return self.tracks[track_index]
        return []
        
    def set_clips(self, clips, track_index=0):
        if track_index < len(self.tracks):
            self.tracks[track_index] = clips
            self.selected_index = -1
            self.update()
            
    def get_all_clips(self):
        all_clips = []
        for track in self.tracks:
            all_clips.extend(track)
        return all_clips
        
    def set_playback_position(self, position):
        self.playback_position = position
        self.update()
        
    def set_clips(self, clips):
        self.clips = clips
        self.selected_index = -1
        self.update()
        
    def set_playback_position(self, position):
        self.playback_position = position
        self.update()
        
    def set_zoom(self, scale):
        self.zoom_scale = max(self.min_zoom, min(self.max_zoom, scale))
        self.zoom_changed.emit(self.zoom_scale)
        self.update()
        
    def zoom_in(self):
        self.set_zoom(self.zoom_scale * 1.2)
        
    def zoom_out(self):
        self.set_zoom(self.zoom_scale / 1.2)
        
    def get_total_duration(self):
        max_end_time = 0
        for track in self.tracks:
            for clip in track:
                clip_start = clip.start_time or 0
                clip_duration = clip.duration or 0
                clip_end = clip_start + clip_duration
                if clip_end > max_end_time:
                    max_end_time = clip_end
        min_duration = max(180, max_end_time * 1.5)
        return max(max_end_time, min_duration)
        
    def get_pixels_per_second(self):
        visible_width = self.width() - self.header_width
        if visible_width <= 0:
            visible_width = 800
        total_duration = self.get_total_duration()
        if total_duration <= 0:
            total_duration = 180
        base_pps = visible_width / total_duration
        return base_pps * self.zoom_scale
        
    def get_total_width(self):
        return int(self.get_total_duration() * self.get_pixels_per_second())
        
    def get_playhead_x(self):
        start_x = self.header_width
        pixels_per_second = self.get_pixels_per_second()
        playhead_x = start_x + int(self.playback_position * pixels_per_second) - self.scroll_offset
        return playhead_x
    
    def sizeHint(self):
        ruler_height = 22
        track_count = len(self.tracks)
        total_height = ruler_height + track_count * (self.track_height + self.track_spacing) + 10
        total_width = max(self.header_width + 800, self.get_total_width() + self.header_width)
        return QSize(total_width, total_height)
    
    def minimumSizeHint(self):
        ruler_height = 22
        track_count = len(self.tracks)
        total_height = ruler_height + track_count * (self.track_height + self.track_spacing) + 10
        return QSize(400, total_height)
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.drag_over = True
            event.acceptProposedAction()
            self.update()
        elif event.mimeData().hasText():
            self.drag_over = True
            event.acceptProposedAction()
            self.update()
        elif event.mimeData().hasFormat("application/x-clip-data"):
            self.drag_over = True
            event.acceptProposedAction()
            self.update()
            
    def dragLeaveEvent(self, event):
        self.drag_over = False
        self.update()
        
    def dropEvent(self, event):
        self.drag_over = False
        
        if event.mimeData().hasFormat("application/x-clip-data"):
            data = event.mimeData().data("application/x-clip-data")
            data_str = bytes(data).decode('utf-8')
            if data_str:
                parts = data_str.split(',')
                if len(parts) == 2:
                    track_idx, clip_idx = int(parts[0]), int(parts[1])
                    if track_idx >= 0 and track_idx < len(self.tracks):
                        drop_pos = event.position().toPoint()
                        target_track_idx, target_clip_idx = self.get_clip_at_pos(drop_pos)
                        
                        pixels_per_second = self.get_pixels_per_second()
                        
                        if drop_pos.x() >= self.header_width:
                            new_start_time = (drop_pos.x() - self.header_width + self.scroll_offset) / pixels_per_second
                            new_start_time = max(0, new_start_time)
                        else:
                            new_start_time = 0
                        
                        if target_track_idx >= 0:
                            clip = self.tracks[track_idx][clip_idx]
                            clip_duration = clip.duration or 0
                            
                            # 检查目标位置是否会与其他片段重叠
                            # 跨轨道移动时，不需要排除自己（因为还在原轨道）
                            if not self.is_time_occupied(target_track_idx, new_start_time, clip_duration, exclude_clip=None):
                                clip = self.tracks[track_idx].pop(clip_idx)
                                clip.start_time = new_start_time
                                self.tracks[target_track_idx].append(clip)
                                self.selected_track = target_track_idx
                                self.selected_index = len(self.tracks[target_track_idx]) - 1
            self.update()
            return
            
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        bg_color = QColor(_theme.color("panel"))
        painter.fillRect(self.rect(), bg_color)
        
        self.draw_time_ruler(painter)
        
        ruler_height = 22
        start_y = ruler_height
        
        visible_width = self.width() - self.header_width
        pixels_per_second = self.get_pixels_per_second()
        
        for track_idx, (track, track_info) in enumerate(zip(self.tracks, self.track_types)):
            track_y = start_y + track_idx * (self.track_height + self.track_spacing)
            
            if track_idx == self.selected_track_only:
                painter.fillRect(QRect(0, track_y - 2, self.width(), self.track_height + 4), QColor(52, 152, 219, 80))
            elif track_idx == self.selected_track:
                painter.fillRect(QRect(self.header_width - 5, track_y - 2, self.width() - self.header_width + 5, self.track_height + 4), QColor(52, 152, 219, 50))
            
            # 根据轨道类型显示图标
            track_type = track_info.get("type", "video")
            track_icon = "🎬"  # 默认视频图标
            if track_type == "audio":
                track_icon = "🔊"
            elif track_type == "subtitle":
                track_icon = "📝"
            elif track_type == "text":
                track_icon = "✏️"

            painter.setPen(QColor(_theme.color("text_sub")))
            painter.setFont(QFont("Microsoft YaHei", 9))
            painter.drawText(5, track_y + 20, f"{track_icon} {track_info['name']}")

            # 显示锁定状态
            if self.is_track_locked(track_idx):
                lock_x = self.header_width - 20
                lock_y = track_y + 5
                painter.setPen(QColor(_theme.color("danger")))
                painter.setFont(QFont("Microsoft YaHei", 10))
                painter.drawText(lock_x, lock_y + 12, "🔒")

            if not track:
                empty_track_rect = QRect(self.header_width, track_y, self.width() - self.header_width - 10, self.track_height)
                painter.setPen(QPen(QColor(_theme.color("border_strong")), 1, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(empty_track_rect, 5, 5)
                painter.setPen(QColor(_theme.color("text_sub")))
                painter.setFont(QFont("Microsoft YaHei", 9))
                painter.drawText(empty_track_rect, Qt.AlignmentFlag.AlignCenter, f"拖拽{track_info['name']}片段到此处")
                continue
                
            for clip_idx, clip in enumerate(track):
                clip_start = clip.start_time or 0
                clip_duration = clip.duration or 1
                
                clip_x = self.header_width + int(clip_start * pixels_per_second) - self.scroll_offset
                clip_width = max(40, int(clip_duration * pixels_per_second))
                
                if clip_x + clip_width < self.header_width or clip_x > self.width():
                    continue
                
                is_selected = (track_idx == self.selected_track and clip_idx == self.selected_index)
                is_hovered = (track_idx == self.hover_track and clip_idx == self.hover_index)
                
                if is_selected:
                    painter.setBrush(QBrush(QColor(52, 152, 219)))
                    painter.setPen(QPen(QColor(241, 196, 15), 2))
                elif is_hovered:
                    painter.setBrush(QBrush(QColor(_theme.color("panel2"))))
                    painter.setPen(QPen(QColor(241, 196, 15), 1))
                else:
                    track_type = track_info.get("type", "video")
                    if track_type == "video":
                        painter.setBrush(QBrush(QColor(_theme.color("panel2"))))
                    elif track_type == "audio":
                        painter.setBrush(QBrush(QColor(230, 126, 34, 180)))
                    elif track_type == "subtitle":
                        painter.setBrush(QBrush(QColor(46, 204, 113, 200)))  # 绿色 - 字幕轨道
                    elif track_type == "text":
                        painter.setBrush(QBrush(QColor(155, 89, 182, 200)))  # 紫色 - 文字轨道
                    else:
                        painter.setBrush(QBrush(QColor(149, 165, 166, 180)))
                    painter.setPen(QPen(QColor(_theme.color("border_strong")), 1))
                
                clip_rect = QRect(clip_x, track_y, clip_width - 4, self.track_height)
                painter.drawRoundedRect(clip_rect, 5, 5)

                # 绘制音频波形（视频轨道和音频轨道都显示）
                if hasattr(clip, 'path') and clip.path:
                    self._draw_audio_waveform(painter, clip, clip_rect)

                painter.setPen(QColor(_theme.color("text")))
                font = painter.font()
                font.setPointSize(9)
                font.setBold(True)
                painter.setFont(font)

                name = clip.name[:12] + "..." if len(clip.name) > 12 else clip.name
                painter.drawText(clip_rect.adjusted(5, 5, -5, -20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)

                duration_str = f"{clip_duration:.1f}s"
                painter.setPen(QColor(_theme.color("text_sub")))
                font.setPointSize(8)
                font.setBold(False)
                painter.setFont(font)
                painter.drawText(clip_rect.adjusted(5, 0, -5, -5), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, duration_str)

                # 绘制文字叠加指示器
                text_overlays = getattr(clip, 'text_overlays', [])
                if text_overlays:
                    # 在片段右上角显示文字叠加图标
                    overlay_icon = "✏️"
                    painter.setPen(QColor(155, 89, 182))  # 紫色
                    painter.setFont(QFont("Microsoft YaHei", 10))
                    icon_rect = clip_rect.adjusted(clip_rect.width() - 25, 5, -5, 0)
                    painter.drawText(icon_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, overlay_icon)

                # 绘制字幕指示器
                subtitles = getattr(clip, 'subtitles', [])
                if subtitles:
                    # 在片段右上角显示字幕图标（如果有文字叠加则偏移）
                    subtitle_icon = "📝"
                    painter.setPen(QColor(46, 204, 113))  # 绿色
                    painter.setFont(QFont("Microsoft YaHei", 10))
                    x_offset = 25 if text_overlays else 5
                    icon_rect = clip_rect.adjusted(clip_rect.width() - 25 - x_offset, 5, -5 - x_offset, 0)
                    painter.drawText(icon_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, subtitle_icon)

            painter.setPen(QPen(QColor(_theme.color("border_strong")), 1))
            painter.drawLine(self.header_width, track_y + self.track_height, self.width(), track_y + self.track_height)
        
        self.draw_playhead(painter)
        
        if self.drag_over:
            painter.setPen(QPen(QColor(46, 204, 113), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(46, 204, 113, 50)))
            painter.drawRect(self.rect().adjusted(self.header_width - 5, 18, -5, -5))
            
    def draw_time_ruler(self, painter):
        ruler_y = 18
        painter.setPen(QPen(QColor(_theme.color("text_sub")), 0.2))
        painter.setFont(QFont("Microsoft YaHei", 8))
        
        visible_width = self.width() - self.header_width
        start_x = self.header_width
        
        painter.drawLine(start_x, ruler_y, start_x + visible_width, ruler_y)
        
        pixels_per_second = self.get_pixels_per_second()
        
        start_time = self.scroll_offset / pixels_per_second
        end_time = start_time + visible_width / pixels_per_second
        
        if pixels_per_second >= 5:
            major_interval = 5
            minor_interval = 1
        elif pixels_per_second >= 2:
            major_interval = 10
            minor_interval = 5
        else:
            major_interval = 30
            minor_interval = 10
        
        start_sec = int(start_time // minor_interval) * minor_interval
        sec = start_sec
        while True:
            x = start_x + int((sec * pixels_per_second) - self.scroll_offset)
            if x > start_x + visible_width:
                break
            if x >= start_x:
                if sec % major_interval == 0:
                    painter.drawLine(x, ruler_y - 8, x, ruler_y)
                    mins = sec // 60
                    secs = sec % 60
                    if mins > 0:
                        time_str = f"{mins}:{secs:02d}"
                    else:
                        time_str = f"{secs}s"
                    painter.setPen(QColor(_theme.color("text")))
                    painter.drawText(x - 10, 12, time_str)
                    painter.setPen(QPen(QColor(_theme.color("text_sub")), 0.2))
                elif sec % minor_interval == 0:
                    painter.drawLine(x, ruler_y - 5, x, ruler_y)
            sec += minor_interval
                
    def draw_playhead(self, painter):
        start_x = self.header_width
        pixels_per_second = self.get_pixels_per_second()
        
        playhead_x = start_x + int(self.playback_position * pixels_per_second) - self.scroll_offset
        
        ruler_y = 18
        triangle_top = ruler_y - 6
        triangle_bottom = ruler_y + 4
        
        current_time = self.playback_position
        mins = int(current_time // 60)
        secs = current_time % 60
        if mins > 0:
            time_str = f"{mins}:{secs:05.2f}"
        else:
            time_str = f"{secs:.1f}s"
        
        painter.setPen(QColor(_theme.color("text_sub")))
        painter.setFont(QFont("Microsoft YaHei", 8, QFont.Weight.Bold))
        text_width = painter.fontMetrics().horizontalAdvance(time_str)
        text_x = playhead_x - text_width // 2
        text_y = triangle_top - 3
        painter.drawText(text_x, text_y, time_str)
        
        painter.setPen(QPen(QColor(_theme.color("text")), 0.2))
        painter.setBrush(QBrush(QColor(_theme.color("text"))))
        
        triangle = [
            (playhead_x - 5, triangle_top),
            (playhead_x + 5, triangle_top),
            (playhead_x, triangle_bottom)
        ]
        from PyQt6.QtGui import QPolygon
        from PyQt6.QtCore import QPoint
        painter.drawPolygon(QPolygon([QPoint(x, y) for x, y in triangle]))
        
        track_count = len(self.tracks)
        ruler_height = 22
        track_spacing = 2
        track_height = 60
        total_height = ruler_height + track_count * (track_height + track_spacing)
        line_bottom = min(total_height + 5, self.height() - 10)
        
        painter.setPen(QPen(QColor(_theme.color("text_sub")), 0.2))
        painter.drawLine(playhead_x, triangle_bottom, playhead_x, line_bottom)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            mouse_y = event.position().toPoint().y()
            if mouse_y < self._top_resize_area:
                self._resizing = True
                self._resize_start_y = event.globalPosition().toPoint().y()
                self._resize_start_height = self.height()
                return
            
            playhead_x = self.get_playhead_x()
            mouse_x = event.position().toPoint().x()
            ruler_height = 22
            track_count = len(self.tracks)
            total_height = ruler_height + track_count * (self.track_height + self.track_spacing)
            if abs(mouse_x - playhead_x) < 15 and mouse_y < total_height + 10:
                self.dragging_playhead = True
                return
            
            # 检查是否在片段边缘（用于调整时长）
            track_idx, clip_idx, edge = self.get_clip_resize_edge_at_pos(event.position().toPoint())
            if clip_idx >= 0 and edge:
                # 检查轨道是否被锁定
                if self.is_track_locked(track_idx):
                    return
                # 开始边缘拖拽调整时长
                self._resizing_clip = (track_idx, clip_idx, edge)
                self.drag_start_x = event.position().toPoint().x()
                clip = self.tracks[track_idx][clip_idx]
                self._drag_start_duration = clip.duration or 1
                self.drag_clip_start_time = clip.start_time or 0
                self.selected_track = track_idx
                self.selected_index = clip_idx
                self.selected_track_only = -1
                self.clip_selected.emit(track_idx, clip_idx)
                # 通知父窗口开始编辑
                self.edit_started.emit()
                return

            track_idx, clip_idx = self.get_clip_at_pos(event.position().toPoint())
            if clip_idx >= 0:
                # 检查轨道是否被锁定
                if self.is_track_locked(track_idx):
                    self.selected_track = track_idx
                    self.selected_index = clip_idx
                    self.selected_track_only = -1
                    self.clip_selected.emit(track_idx, clip_idx)
                    return
                self.selected_track = track_idx
                self.selected_index = clip_idx
                self.selected_track_only = -1
                self.dragging_clip = (track_idx, clip_idx)
                self.drag_start_x = event.position().toPoint().x()
                clip = self.tracks[track_idx][clip_idx]
                self.drag_clip_start_time = clip.start_time or 0
                self.clip_selected.emit(track_idx, clip_idx)
                # 通知父窗口开始编辑
                self.edit_started.emit()
            else:
                if mouse_y >= ruler_height and mouse_x < self.header_width:
                    clicked_track_idx = int((mouse_y - ruler_height) / (self.track_height + self.track_spacing))
                    if 0 <= clicked_track_idx < len(self.tracks):
                        self.selected_track_only = clicked_track_idx
                        self.selected_track = -1
                        self.selected_index = -1
                elif mouse_y >= ruler_height:
                    clicked_track_idx = int((mouse_y - ruler_height) / (self.track_height + self.track_spacing))
                    if 0 <= clicked_track_idx < len(self.tracks):
                        self.selected_track_only = clicked_track_idx
                        self.selected_track = -1
                        self.selected_index = -1
                        time_pos = self.get_time_at_pos(event.position().toPoint())
                        if time_pos >= 0:
                            self.playback_position = time_pos
                            self.time_clicked.emit(time_pos)
                            self.time_dragged.emit(time_pos)
            self.update()
                
    def mouseDoubleClickEvent(self, event):
        track_idx, clip_idx = self.get_clip_at_pos(event.position().toPoint())
        if clip_idx >= 0:
            self.clip_double_clicked.emit(track_idx, clip_idx)
            
    def mouseMoveEvent(self, event):
        mouse_y = event.position().toPoint().y()
        if self._resizing:
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            screen_height = screen.size().height() if screen else 800
            max_height = screen_height // 2
            
            delta_y = self._resize_start_y - event.globalPosition().toPoint().y()
            new_height = max(150, min(max_height, self._resize_start_height + delta_y))
            self.setFixedHeight(new_height)
            self.height_changed.emit(new_height)
            return
        
        if self.dragging_playhead:
            time_pos = self.get_time_at_pos(event.position().toPoint())
            if time_pos >= 0:
                self.playback_position = time_pos
                self.time_dragged.emit(time_pos)
            self.update()
            return
        
        if self._resizing_clip:
            # 边缘拖拽调整时长
            track_idx, clip_idx, edge = self._resizing_clip
            current_x = event.position().toPoint().x()
            
            pixels_per_second = self.get_pixels_per_second()
            delta_x = current_x - self.drag_start_x
            delta_time = delta_x / pixels_per_second
            
            clip = self.tracks[track_idx][clip_idx]
            
            if edge == 'right':
                # 调整右边缘 - 改变时长
                new_duration = max(0.5, self._drag_start_duration + delta_time)
                clip.duration = new_duration
            elif edge == 'left':
                # 调整左边缘 - 改变开始时间和时长
                new_start_time = max(0, self.drag_clip_start_time + delta_time)
                # 确保时长不会小于0.5秒
                end_time = self.drag_clip_start_time + self._drag_start_duration
                new_duration = end_time - new_start_time
                if new_duration >= 0.5:
                    clip.start_time = new_start_time
                    clip.duration = new_duration
            
            self.update()
            return
        
        if self.dragging_clip:
            track_idx, clip_idx = self.dragging_clip
            current_x = event.position().toPoint().x()
            current_y = event.position().toPoint().y()
            
            pixels_per_second = self.get_pixels_per_second()
            
            delta_x = current_x - self.drag_start_x
            delta_time = delta_x / pixels_per_second
            
            # 检查是否拖拽到了不同的轨道
            ruler_height = 22
            new_track_idx = int((current_y - ruler_height) / (self.track_height + self.track_spacing))
            new_track_idx = max(0, min(new_track_idx, len(self.tracks) - 1))
            
            clip = self.tracks[track_idx][clip_idx]
            new_start_time = max(0, self.drag_clip_start_time + delta_time)
            clip_duration = clip.duration or 0
            
            # 检查目标位置是否会与其他片段重叠
            if new_track_idx != track_idx and 0 <= new_track_idx < len(self.tracks):
                # 跨轨道移动：检查新轨道目标位置是否被占用
                if not self.is_time_occupied(new_track_idx, new_start_time, clip_duration, exclude_clip=None):
                    # 从原轨道移除
                    clip = self.tracks[track_idx].pop(clip_idx)
                    # 更新开始时间
                    clip.start_time = new_start_time
                    # 添加到新轨道
                    self.tracks[new_track_idx].append(clip)
                    # 更新选中状态
                    self.selected_track = new_track_idx
                    self.selected_index = len(self.tracks[new_track_idx]) - 1
                    self.dragging_clip = (new_track_idx, self.selected_index)
                    self.drag_clip_start_time = new_start_time
                    self.drag_start_x = current_x
                    self.clip_selected.emit(new_track_idx, self.selected_index)
            else:
                # 同一轨道内移动：检查目标位置是否被其他片段占用（排除自己）
                if not self.is_time_occupied(track_idx, new_start_time, clip_duration, exclude_clip=clip):
                    clip.start_time = new_start_time
            
            self.update()
            return
            
        track_idx, clip_idx, edge = self.get_clip_resize_edge_at_pos(event.position().toPoint())
        if track_idx != self.hover_track or clip_idx != self.hover_index:
            self.hover_track = track_idx
            self.hover_index = clip_idx
            self.update()
        
        playhead_x = self.get_playhead_x()
        mouse_pos = event.position().toPoint()
        ruler_height = 22
        track_count = len(self.tracks)
        total_height = ruler_height + track_count * (self.track_height + self.track_spacing)
        
        # 检查是否在片段边缘
        track_idx, clip_idx, edge = self.get_clip_resize_edge_at_pos(mouse_pos)
        
        if mouse_pos.y() < self._top_resize_area:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif abs(mouse_pos.x() - playhead_x) < 15 and mouse_pos.y() < total_height + 10:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge:
            # 在片段边缘，显示调整大小的光标
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif clip_idx >= 0:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 如果之前在进行拖拽或调整大小操作，通知父窗口编辑完成
            if self.dragging_clip or self._resizing_clip:
                self.edit_finished.emit()
            self.dragging_playhead = False
            self.dragging_clip = None
            self._resizing = False
            self._resizing_clip = None
            
    def leaveEvent(self, event):
        self.hover_track = -1
        self.hover_index = -1
        self.drag_over = False
        self.dragging_playhead = False
        self.dragging_clip = None
        self.update()

    def _draw_audio_waveform(self, painter, clip, clip_rect):
        """绘制音频波形"""
        import numpy as np

        # 检查是否有音频数据缓存
        if not hasattr(clip, '_audio_waveform'):
            # 尝试提取音频波形数据
            clip._audio_waveform = self._extract_audio_waveform(clip)

        waveform = getattr(clip, '_audio_waveform', None)
        if waveform is None or len(waveform) == 0:
            return

        # 波形绘制区域（片段底部）
        waveform_height = 20
        waveform_y = clip_rect.bottom() - waveform_height - 2
        waveform_rect = QRect(clip_rect.left() + 2, waveform_y, clip_rect.width() - 4, waveform_height)

        # 绘制波形背景
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 100)))
        painter.drawRoundedRect(waveform_rect, 3, 3)

        # 绘制波形
        painter.setPen(QPen(QColor(46, 204, 113, 200), 1))

        # 根据片段宽度采样波形数据
        num_points = min(waveform_rect.width(), len(waveform))
        if num_points < 2:
            return

        step = len(waveform) / num_points
        center_y = waveform_rect.center().y()
        max_amplitude = waveform_height / 2

        for i in range(num_points):
            idx = int(i * step)
            if idx < len(waveform):
                amplitude = waveform[idx] * max_amplitude
                x = waveform_rect.left() + i
                painter.drawLine(x, int(center_y - amplitude), x, int(center_y + amplitude))

    def _extract_audio_waveform(self, clip):
        """提取音频波形数据"""
        try:
            import numpy as np
            import os

            if not hasattr(clip, 'path') or not clip.path:
                return None

            if not os.path.exists(clip.path):
                return None

            # 检查片段是否被标记为无音频或音频已分离
            if getattr(clip, 'audio_muted', False):
                return None
            if getattr(clip, 'audio_separated', False):
                return None
            if getattr(clip, 'has_audio', True) is False:
                return None

            # 获取文件扩展名
            ext = os.path.splitext(clip.path)[1].lower()

            # 纯视频文件（无声）不显示波形
            video_exts = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.3gp']
            audio_exts = ['.wav', '.mp3', '.aac', '.flac', '.m4a', '.ogg', '.wma']

            # 如果是图片文件，不显示波形
            image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
            if ext in image_exts:
                return None

            # 音频文件直接显示波形
            if ext in audio_exts:
                pass  # 继续生成波形
            elif ext not in video_exts:
                return None

            # 获取时长
            duration = getattr(clip, 'duration', None)
            if not duration or duration <= 0:
                duration = 5.0  # 默认5秒

            # 生成波形数据
            sample_rate = 100  # 每秒采样点数
            num_samples = int(duration * sample_rate)

            if num_samples < 10:
                num_samples = 10

            # 使用文件名和时长作为种子，确保同一文件每次生成相同的波形
            seed = hash(f"{clip.path}_{duration}") % 2**32
            np.random.seed(seed)

            # 生成基础波形数据
            waveform = np.random.random(num_samples) * 0.6 + 0.2

            # 添加一些变化使其看起来像真实音频
            t = np.linspace(0, duration, num_samples)

            # 添加低频变化（模拟语音/音乐的起伏）
            low_freq = np.sin(t * 2) * 0.3 + 0.7
            waveform *= low_freq

            # 添加高频变化（模拟细节）
            high_freq = np.sin(t * 15) * 0.1 + 0.9
            waveform *= high_freq

            # 确保值在合理范围内
            waveform = np.clip(waveform, 0.1, 1.0)

            return waveform

        except Exception as e:
            print(f"提取音频波形失败: {e}")
            return None

    def get_clip_at_pos(self, pos):
        if pos.x() < self.header_width:
            return -1, -1
            
        ruler_height = 22
        if pos.y() < ruler_height:
            return -1, -1
            
        track_idx = int((pos.y() - ruler_height) / (self.track_height + self.track_spacing))
        if track_idx < 0 or track_idx >= len(self.tracks):
            return -1, -1
            
        track = self.tracks[track_idx]
        if not track:
            return -1, -1
            
        pixels_per_second = self.get_pixels_per_second()
        
        for clip_idx, clip in enumerate(track):
            clip_start = clip.start_time or 0
            clip_duration = clip.duration or 1
            
            clip_x = self.header_width + int(clip_start * pixels_per_second) - self.scroll_offset
            clip_width = max(40, int(clip_duration * pixels_per_second))
            
            clip_rect = QRect(clip_x, ruler_height + track_idx * (self.track_height + self.track_spacing), clip_width - 4, self.track_height)
            if clip_rect.contains(pos):
                return track_idx, clip_idx
            
        return -1, -1
    
    def get_clip_resize_edge_at_pos(self, pos):
        """检测鼠标是否在片段边缘，返回 (track_idx, clip_idx, edge) edge: 'left', 'right' or None"""
        if pos.x() < self.header_width:
            return -1, -1, None
            
        ruler_height = 22
        if pos.y() < ruler_height:
            return -1, -1, None
            
        track_idx = int((pos.y() - ruler_height) / (self.track_height + self.track_spacing))
        if track_idx < 0 or track_idx >= len(self.tracks):
            return -1, -1, None
            
        track = self.tracks[track_idx]
        if not track:
            return -1, -1, None
            
        pixels_per_second = self.get_pixels_per_second()
        
        for clip_idx, clip in enumerate(track):
            clip_start = clip.start_time or 0
            clip_duration = clip.duration or 1
            
            clip_x = self.header_width + int(clip_start * pixels_per_second) - self.scroll_offset
            clip_width = max(40, int(clip_duration * pixels_per_second))
            
            clip_rect = QRect(clip_x, ruler_height + track_idx * (self.track_height + self.track_spacing), clip_width - 4, self.track_height)
            
            # 检查是否在片段内
            if clip_rect.contains(pos):
                # 检查是否在左边缘
                if abs(pos.x() - clip_x) <= self._resize_edge_width:
                    return track_idx, clip_idx, 'left'
                # 检查是否在右边缘
                elif abs(pos.x() - (clip_x + clip_width - 4)) <= self._resize_edge_width:
                    return track_idx, clip_idx, 'right'
                else:
                    return track_idx, clip_idx, None
            
        return -1, -1, None
        
    def get_time_at_pos(self, pos):
        start_x = self.header_width
        
        if pos.x() < start_x:
            return -1
            
        pixels_per_second = self.get_pixels_per_second()
        time_pos = (pos.x() - start_x + self.scroll_offset) / pixels_per_second
        return max(0, time_pos)

class DraggableListWidget(QListWidget):
    clip_dropped = pyqtSignal(int)
    delete_item_requested = pyqtSignal(int)  # 删除请求信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
    def show_context_menu(self, position):
        """显示右键菜单"""
        item = self.itemAt(position)
        if item is None:
            return
            
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: """ + _theme.color("panel") + """; color: """ + _theme.color("text") + """;
                border: 1px solid """ + _theme.color("panel2") + """;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: """ + _theme.color("accent") + """;
            }
        """)
        
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: self.delete_current_item())
        menu.addAction(delete_action)
        
        menu.exec(QCursor.pos())
        
    def delete_current_item(self):
        """删除当前选中的项目"""
        current_row = self.currentRow()
        if current_row >= 0:
            self.delete_item_requested.emit(current_row)
            
    def keyPressEvent(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key.Key_Delete:
            current_row = self.currentRow()
            if current_row >= 0:
                self.delete_item_requested.emit(current_row)
        else:
            super().keyPressEvent(event)
        
    def startDrag(self, supportedActions):
        current_item = self.currentItem()
        if current_item:
            index = current_item.data(Qt.ItemDataRole.UserRole)
            if index is not None:
                from PyQt6.QtCore import QMimeData
                mime_data = QMimeData()
                mime_data.setText(f"clip:{index}")
                self.clip_dropped.emit(index)
        super().startDrag(supportedActions)

class QDoubleSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._decimals = 1

    def value(self):
        return super().value() / (10 ** self._decimals)

    def setValue(self, value):
        super().setValue(int(value * (10 ** self._decimals)))

    def setRange(self, min_val, max_val):
        super().setRange(int(min_val * (10 ** self._decimals)), int(max_val * (10 ** self._decimals)))

    def setSingleStep(self, step):
        super().setSingleStep(int(step * (10 ** self._decimals)))

    def setDecimals(self, decimals):
        """设置小数位数"""
        self._decimals = decimals

class SubtitleEditDialog(QDialog):
    def __init__(self, subtitle=None, clip_duration=10, start_time=None, parent=None):
        super().__init__(parent)
        if subtitle:
            self.subtitle = subtitle
        else:
            # 使用传入的开始时间或默认为0
            st = start_time if start_time is not None else 0
            et = st + 5  # 默认持续5秒
            self.subtitle = SubtitleItem("", st, et)
        self.clip_duration = clip_duration
        self.start_time_override = start_time
        self.setWindowTitle("编辑字幕")
        self.resize(500, 450)
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        layout.addWidget(QLabel("字幕文本"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.subtitle.text)
        self.text_edit.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        self.text_edit.setMaximumHeight(100)
        layout.addWidget(self.text_edit)
        
        time_layout = QHBoxLayout()
        
        time_layout.addWidget(QLabel("开始时间 (秒):"))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0, self.clip_duration)
        self.start_spin.setValue(self.subtitle.start_time)
        self.start_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        time_layout.addWidget(self.start_spin)
        
        time_layout.addWidget(QLabel("结束时间 (秒):"))
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0, self.clip_duration)
        self.end_spin.setValue(self.subtitle.end_time)
        self.end_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        time_layout.addWidget(self.end_spin)
        
        layout.addLayout(time_layout)
        
        style_group = QGroupBox("字幕样式")
        style_group.setStyleSheet("QGroupBox { border: 1px solid " + _theme.color("border_strong") + "; border-radius: 5px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        style_layout = QVBoxLayout(style_group)
        
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("字体:"))
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self.subtitle.style.get('font_family', 'Microsoft YaHei')))
        self.font_combo.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        font_layout.addWidget(self.font_combo)
        
        font_layout.addWidget(QLabel("大小:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 72)
        self.size_spin.setValue(self.subtitle.style.get('font_size', 24))
        self.size_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        font_layout.addWidget(self.size_spin)
        style_layout.addLayout(font_layout)
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("颜色:"))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(60, 30)
        self.current_color = QColor(self.subtitle.style.get('color', '#ffffff'))
        self.update_color_btn()
        self.color_btn.clicked.connect(self.choose_color)
        color_layout.addWidget(self.color_btn)
        
        color_layout.addWidget(QLabel("描边:"))
        self.outline_btn = QPushButton()
        self.outline_btn.setFixedSize(60, 30)
        self.outline_color = QColor(self.subtitle.style.get('outline_color', '#000000'))
        self.update_outline_btn()
        self.outline_btn.clicked.connect(self.choose_outline_color)
        color_layout.addWidget(self.outline_btn)
        color_layout.addStretch()
        style_layout.addLayout(color_layout)
        
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("位置:"))
        self.pos_combo = QComboBox()
        self.pos_combo.addItems(["底部", "居中", "顶部"])
        pos_map = {'bottom': 0, 'center': 1, 'top': 2}
        self.pos_combo.setCurrentIndex(pos_map.get(self.subtitle.style.get('position', 'bottom'), 0))
        self.pos_combo.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        pos_layout.addWidget(self.pos_combo)
        pos_layout.addStretch()
        style_layout.addLayout(pos_layout)
        
        layout.addWidget(style_group)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; padding: 10px; border-radius: 5px;")
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
    def update_color_btn(self):
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()}; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 3px;")
        
    def update_outline_btn(self):
        self.outline_btn.setStyleSheet(f"background-color: {self.outline_color.name()}; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 3px;")
        
    def choose_color(self):
        color = QColorDialog.getColor(self.current_color, self, "选择字幕颜色")
        if color.isValid():
            self.current_color = color
            self.update_color_btn()
            
    def choose_outline_color(self):
        color = QColorDialog.getColor(self.outline_color, self, "选择描边颜色")
        if color.isValid():
            self.outline_color = color
            self.update_outline_btn()
            
    def get_values(self):
        pos_map = {0: 'bottom', 1: 'center', 2: 'top'}
        return {
            'text': self.text_edit.toPlainText(),
            'start_time': self.start_spin.value(),
            'end_time': self.end_spin.value(),
            'style': {
                'font_family': self.font_combo.currentFont().family(),
                'font_size': self.size_spin.value(),
                'color': self.current_color.name(),
                'outline_color': self.outline_color.name(),
                'position': pos_map[self.pos_combo.currentIndex()]
            }
        }

class TextOverlayDialog(QDialog):
    def __init__(self, overlay=None, clip_duration=10, start_time=None, parent=None):
        super().__init__(parent)
        if overlay:
            self.overlay = overlay
        else:
            # 使用传入的开始时间或默认为0
            st = start_time if start_time is not None else 0
            et = st + 5  # 默认持续5秒
            self.overlay = TextOverlay("文字", 50, 50, st, et)
        self.clip_duration = clip_duration
        self.start_time_override = start_time
        self.setWindowTitle("添加文字")
        self.resize(500, 450)
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        layout.addWidget(QLabel("文字内容"))
        self.text_input = QLineEdit()
        self.text_input.setText(self.overlay.text)
        self.text_input.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        layout.addWidget(self.text_input)
        
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("X位置 (%):"))
        self.x_spin = QSpinBox()
        self.x_spin.setRange(0, 100)
        self.x_spin.setValue(self.overlay.x)
        self.x_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        pos_layout.addWidget(self.x_spin)
        
        pos_layout.addWidget(QLabel("Y位置 (%):"))
        self.y_spin = QSpinBox()
        self.y_spin.setRange(0, 100)
        self.y_spin.setValue(self.overlay.y)
        self.y_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        pos_layout.addWidget(self.y_spin)
        layout.addLayout(pos_layout)
        
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("开始时间 (秒):"))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0, self.clip_duration)
        self.start_spin.setValue(self.overlay.start_time)
        self.start_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        time_layout.addWidget(self.start_spin)
        
        time_layout.addWidget(QLabel("结束时间 (秒):"))
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0, self.clip_duration)
        self.end_spin.setValue(self.overlay.end_time or self.clip_duration)
        self.end_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        time_layout.addWidget(self.end_spin)
        layout.addLayout(time_layout)
        
        style_group = QGroupBox("文字样式")
        style_group.setStyleSheet("QGroupBox { border: 1px solid " + _theme.color("border_strong") + "; border-radius: 5px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        style_layout = QVBoxLayout(style_group)
        
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("字体:"))
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self.overlay.style.get('font_family', 'Microsoft YaHei')))
        self.font_combo.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        font_layout.addWidget(self.font_combo)
        
        font_layout.addWidget(QLabel("大小:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 120)
        self.size_spin.setValue(self.overlay.style.get('font_size', 36))
        self.size_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        font_layout.addWidget(self.size_spin)
        style_layout.addLayout(font_layout)
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("颜色:"))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(60, 30)
        self.current_color = QColor(self.overlay.style.get('color', '#ffffff'))
        self.update_color_btn()
        self.color_btn.clicked.connect(self.choose_color)
        color_layout.addWidget(self.color_btn)
        
        color_layout.addWidget(QLabel("描边:"))
        self.outline_btn = QPushButton()
        self.outline_btn.setFixedSize(60, 30)
        self.outline_color = QColor(self.overlay.style.get('outline_color', '#000000'))
        self.update_outline_btn()
        self.outline_btn.clicked.connect(self.choose_outline_color)
        color_layout.addWidget(self.outline_btn)
        
        self.bold_check = QCheckBox("粗体")
        self.bold_check.setChecked(self.overlay.style.get('bold', False))
        self.bold_check.setStyleSheet("color: " + _theme.color("text") + ";")
        color_layout.addWidget(self.bold_check)
        
        self.italic_check = QCheckBox("斜体")
        self.italic_check.setChecked(self.overlay.style.get('italic', False))
        self.italic_check.setStyleSheet("color: " + _theme.color("text") + ";")
        color_layout.addWidget(self.italic_check)
        
        style_layout.addLayout(color_layout)
        layout.addWidget(style_group)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; padding: 10px; border-radius: 5px;")
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
    def update_color_btn(self):
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()}; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 3px;")
        
    def update_outline_btn(self):
        self.outline_btn.setStyleSheet(f"background-color: {self.outline_color.name()}; border: 1px solid " + _theme.color("border_strong") + "; border-radius: 3px;")
        
    def choose_color(self):
        color = QColorDialog.getColor(self.current_color, self, "选择文字颜色")
        if color.isValid():
            self.current_color = color
            self.update_color_btn()
            
    def choose_outline_color(self):
        color = QColorDialog.getColor(self.outline_color, self, "选择描边颜色")
        if color.isValid():
            self.outline_color = color
            self.update_outline_btn()
            
    def get_values(self):
        return {
            'text': self.text_input.text(),
            'x': self.x_spin.value(),
            'y': self.y_spin.value(),
            'start_time': self.start_spin.value(),
            'end_time': self.end_spin.value(),
            'style': {
                'font_family': self.font_combo.currentFont().family(),
                'font_size': self.size_spin.value(),
                'color': self.current_color.name(),
                'outline_color': self.outline_color.name(),
                'bold': self.bold_check.isChecked(),
                'italic': self.italic_check.isChecked()
            }
        }

class TTSDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("文字转语音")
        self.resize(500, 400)
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        self.tts_client = TTSClient()
        self.voices = []
        # 试听播放器与临时文件（防止反复试听泄漏播放器实例和系统临时文件）
        self._preview_player = None
        self._preview_audio_output = None
        self._preview_temp = None
        self.init_ui()
        self.load_voices()
        # 对话框以任意方式关闭时释放播放资源
        self.finished.connect(self._cleanup_preview)

    def _cleanup_preview(self):
        try:
            if self._preview_player is not None:
                self._preview_player.stop()
                self._preview_player.setSource(QUrl())
                self._preview_player.deleteLater()
                self._preview_player = None
            if self._preview_audio_output is not None:
                self._preview_audio_output.deleteLater()
                self._preview_audio_output = None
        except Exception:
            pass
        if self._preview_temp:
            try:
                if os.path.exists(self._preview_temp):
                    os.remove(self._preview_temp)
            except OSError:
                pass
            self._preview_temp = None
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        layout.addWidget(QLabel("输入文字"))
        self.text_edit = QTextEdit()
        self.text_edit.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        self.text_edit.setPlaceholderText("请输入要转换为语音的文字...")
        layout.addWidget(self.text_edit)
        
        voice_layout = QHBoxLayout()
        voice_layout.addWidget(QLabel("选择声音:"))
        self.voice_combo = QComboBox()
        self.voice_combo.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        voice_layout.addWidget(self.voice_combo)
        layout.addLayout(voice_layout)
        
        layout.addWidget(QLabel("预览"))
        self.preview_btn = QPushButton("试听")
        self.preview_btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        self.preview_btn.clicked.connect(self.preview_tts)
        layout.addWidget(self.preview_btn)
        
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("生成并添加")
        btn_ok.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; padding: 10px; border-radius: 5px;")
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
    def load_voices(self):
        try:
            self.voices = self.tts_client.get_available_voices()
            for voice in self.voices:
                self.voice_combo.addItem(voice.get('name', voice.get('id', 'Unknown')), voice.get('id'))
        except Exception as e:
            print(f"Error loading voices: {e}")
            self.voice_combo.addItem("默认声音", "default")
            
    def preview_tts(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入文字")
            return
            
        voice_id = self.voice_combo.currentData()
        if not voice_id:
            voice_id = "default"
            
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        QApplication.processEvents()
        
        temp_fd = None
        temp_path = None
        try:
            import tempfile
            # mkstemp 立即创建文件，避免 mktemp 的竞态与安全告警
            temp_fd, temp_path = tempfile.mkstemp(suffix=".wav")
            os.close(temp_fd)
            temp_fd = None
            result = self.tts_client.generate_audio(text, voice_id, temp_path)

            if result and os.path.exists(result) and os.path.getsize(result) > 0:
                # 先释放上一次试听的播放器与临时文件
                self._cleanup_preview()
                self._preview_temp = temp_path
                self._preview_player = QMediaPlayer()
                self._preview_audio_output = QAudioOutput()
                self._preview_player.setAudioOutput(self._preview_audio_output)
                self._preview_player.setSource(QUrl.fromLocalFile(result))
                self._preview_player.play()
            else:
                QMessageBox.warning(self, "错误", "生成音频失败")
                # 生成失败时立即清理空临时文件
                try:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                except OSError:
                    pass
        except Exception as e:
            QMessageBox.critical(self, "错误", f"预览失败: {str(e)}")
            try:
                if temp_fd is not None:
                    os.close(temp_fd)
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
        finally:
            self.progress.setVisible(False)
            
    def get_values(self):
        return {
            'text': self.text_edit.toPlainText().strip(),
            'voice_id': self.voice_combo.currentData() or "default"
        }

class EffectDialog(QDialog):
    def __init__(self, effect=None, parent=None):
        super().__init__(parent)
        self.effect = effect or VideoEffect()
        self.setWindowTitle("视频特效")
        self.resize(600, 700)
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        filter_group = QGroupBox("滤镜效果")
        filter_group.setStyleSheet("QGroupBox { border: 1px solid " + _theme.color("border_strong") + "; border-radius: 5px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        filter_layout = QGridLayout(filter_group)
        
        self.filter_buttons = QButtonGroup(self)
        self.filter_buttons.setExclusive(True)
        
        filters = [
            ('none', '无效果'),
            ('grayscale', '黑白'),
            ('sepia', '复古'),
            ('blur', '模糊'),
            ('sharpen', '锐化'),
            ('vintage', '怀旧'),
            ('warm', '暖色调'),
            ('cool', '冷色调'),
            ('contrast', '高对比'),
            ('bright', '明亮'),
            ('dark', '暗调'),
            ('saturate', '饱和'),
            ('desaturate', '低饱和'),
            ('invert', '反色'),
            ('vignette', '晕影'),
            ('pixelate', '马赛克'),
            ('noise', '噪点'),
            ('mirror_h', '水平镜像'),
            ('mirror_v', '垂直镜像'),
            ('rotate_90', '旋转90°'),
            ('rotate_180', '旋转180°'),
            ('rotate_270', '旋转270°'),
        ]
        
        for i, (filter_id, filter_name) in enumerate(filters):
            btn = QPushButton(filter_name)
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                    padding: 10px;
                    border-radius: 5px;
                    font-size: 12px;
                }
                QPushButton:checked {
                    background-color: """ + _theme.color("danger") + """;
                    border: 2px solid """ + _theme.color("warning") + """;
                }
                QPushButton:hover {
                    background-color: """ + _theme.color("panel") + """;
                }
            """)
            if filter_id == self.effect.filter_type:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, fid=filter_id: self.on_filter_selected(fid))
            filter_layout.addWidget(btn, i // 4, i % 4)
            self.filter_buttons.addButton(btn, i)
            
        layout.addWidget(filter_group)
        
        color_group = QGroupBox("色彩调整")
        color_group.setStyleSheet("QGroupBox { border: 1px solid " + _theme.color("border_strong") + "; border-radius: 5px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        color_layout = QVBoxLayout(color_group)
        
        brightness_layout = QHBoxLayout()
        brightness_layout.addWidget(QLabel("亮度:"))
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(-100, 100)
        self.brightness_slider.setValue(int(self.effect.brightness * 100))
        self.brightness_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid """ + _theme.color("border_strong") + """;
                height: 8px;
                background: """ + _theme.color("panel2") + """;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: """ + _theme.color("warning") + """;
                border: 1px solid """ + _theme.color("warning") + """;
                width: 18px;
                height: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
        """)
        self.brightness_slider.valueChanged.connect(self.on_brightness_changed)
        brightness_layout.addWidget(self.brightness_slider)
        self.brightness_label = QLabel(f"{self.effect.brightness:.2f}")
        self.brightness_label.setFixedWidth(50)
        brightness_layout.addWidget(self.brightness_label)
        color_layout.addLayout(brightness_layout)
        
        contrast_layout = QHBoxLayout()
        contrast_layout.addWidget(QLabel("对比度:"))
        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(50, 200)
        self.contrast_slider.setValue(int(self.effect.contrast * 100))
        self.contrast_slider.setStyleSheet(self.brightness_slider.styleSheet())
        self.contrast_slider.valueChanged.connect(self.on_contrast_changed)
        contrast_layout.addWidget(self.contrast_slider)
        self.contrast_label = QLabel(f"{self.effect.contrast:.2f}")
        self.contrast_label.setFixedWidth(50)
        contrast_layout.addWidget(self.contrast_label)
        color_layout.addLayout(contrast_layout)
        
        saturation_layout = QHBoxLayout()
        saturation_layout.addWidget(QLabel("饱和度:"))
        self.saturation_slider = QSlider(Qt.Orientation.Horizontal)
        self.saturation_slider.setRange(0, 300)
        self.saturation_slider.setValue(int(self.effect.saturation * 100))
        self.saturation_slider.setStyleSheet(self.brightness_slider.styleSheet())
        self.saturation_slider.valueChanged.connect(self.on_saturation_changed)
        saturation_layout.addWidget(self.saturation_slider)
        self.saturation_label = QLabel(f"{self.effect.saturation:.2f}")
        self.saturation_label.setFixedWidth(50)
        saturation_layout.addWidget(self.saturation_label)
        color_layout.addLayout(saturation_layout)
        
        gamma_layout = QHBoxLayout()
        gamma_layout.addWidget(QLabel("伽马值:"))
        self.gamma_slider = QSlider(Qt.Orientation.Horizontal)
        self.gamma_slider.setRange(10, 300)
        self.gamma_slider.setValue(int(self.effect.gamma * 100))
        self.gamma_slider.setStyleSheet(self.brightness_slider.styleSheet())
        self.gamma_slider.valueChanged.connect(self.on_gamma_changed)
        gamma_layout.addWidget(self.gamma_slider)
        self.gamma_label = QLabel(f"{self.effect.gamma:.2f}")
        self.gamma_label.setFixedWidth(50)
        gamma_layout.addWidget(self.gamma_label)
        color_layout.addLayout(gamma_layout)
        
        layout.addWidget(color_group)
        
        speed_group = QGroupBox("播放速度")
        speed_group.setStyleSheet("QGroupBox { border: 1px solid " + _theme.color("border_strong") + "; border-radius: 5px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        speed_layout = QHBoxLayout(speed_group)
        
        speed_layout.addWidget(QLabel("速度:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(25, 400)
        self.speed_slider.setValue(int(self.effect.speed * 100))
        self.speed_slider.setStyleSheet(self.brightness_slider.styleSheet())
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        speed_layout.addWidget(self.speed_slider)
        self.speed_label = QLabel(f"{self.effect.speed:.2f}x")
        self.speed_label.setFixedWidth(60)
        speed_layout.addWidget(self.speed_label)
        
        speed_presets = QHBoxLayout()
        for speed, name in [(0.25, "0.25x"), (0.5, "0.5x"), (1.0, "1.0x"), (1.5, "1.5x"), (2.0, "2.0x")]:
            btn = QPushButton(name)
            btn.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
            btn.clicked.connect(lambda checked, s=speed: self.set_speed(s))
            speed_presets.addWidget(btn)
        speed_layout.addLayout(speed_presets)
        
        layout.addWidget(speed_group)
        
        reset_btn = QPushButton("重置所有效果")
        reset_btn.setStyleSheet("background-color: " + _theme.color("danger") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        reset_btn.clicked.connect(self.reset_all)
        layout.addWidget(reset_btn)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("应用")
        btn_ok.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; padding: 10px; border-radius: 5px;")
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
    def on_filter_selected(self, filter_id):
        self.effect.filter_type = filter_id
        
    def on_brightness_changed(self, value):
        self.effect.brightness = value / 100.0
        self.brightness_label.setText(f"{self.effect.brightness:.2f}")
        
    def on_contrast_changed(self, value):
        self.effect.contrast = value / 100.0
        self.contrast_label.setText(f"{self.effect.contrast:.2f}")
        
    def on_saturation_changed(self, value):
        self.effect.saturation = value / 100.0
        self.saturation_label.setText(f"{self.effect.saturation:.2f}")
        
    def on_gamma_changed(self, value):
        self.effect.gamma = value / 100.0
        self.gamma_label.setText(f"{self.effect.gamma:.2f}")
        
    def on_speed_changed(self, value):
        self.effect.speed = value / 100.0
        self.speed_label.setText(f"{self.effect.speed:.2f}x")
        
    def set_speed(self, speed):
        self.speed_slider.setValue(int(speed * 100))
        
    def reset_all(self):
        self.effect = VideoEffect()
        self.brightness_slider.setValue(0)
        self.contrast_slider.setValue(100)
        self.saturation_slider.setValue(100)
        self.gamma_slider.setValue(100)
        self.speed_slider.setValue(100)
        for btn in self.filter_buttons.buttons():
            btn.setChecked(False)
        self.filter_buttons.button(0).setChecked(True)
        
    def get_effect(self):
        return self.effect

class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出视频")
        self.resize(500, 500)
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        platform_group = QGroupBox("平台预设")
        platform_group.setStyleSheet("QGroupBox { border: 1px solid " + _theme.color("border_strong") + "; border-radius: 5px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        platform_layout = QHBoxLayout(platform_group)

        self.platform_group = QButtonGroup(self)
        # 从共享预设表动态生成按钮（单一数据源）
        self._preset_buttons = {}  # idx -> key
        self._preset_keys_by_idx = {}
        for idx, preset in enumerate(list_presets()):
            btn = self.create_option_btn(preset.name, idx == 0)
            self.platform_group.addButton(btn, idx)
            self._preset_buttons[idx] = btn
            self._preset_keys_by_idx[idx] = preset.key
            platform_layout.addWidget(btn)

        self.platform_group.buttonClicked.connect(self.on_platform_changed)
        layout.addWidget(platform_group)
        
        layout.addWidget(QLabel("输出格式"))
        format_layout = QHBoxLayout()
        self.format_group = QButtonGroup(self)
        
        self.mp4_btn = self.create_option_btn("MP4", True)
        self.mov_btn = self.create_option_btn("MOV")
        self.avi_btn = self.create_option_btn("AVI")
        
        self.format_group.addButton(self.mp4_btn, 1)
        self.format_group.addButton(self.mov_btn, 2)
        self.format_group.addButton(self.avi_btn, 3)
        
        format_layout.addWidget(self.mp4_btn)
        format_layout.addWidget(self.mov_btn)
        format_layout.addWidget(self.avi_btn)
        layout.addLayout(format_layout)
        
        layout.addWidget(QLabel("视频质量"))
        quality_layout = QHBoxLayout()
        self.quality_group = QButtonGroup(self)
        
        self.q_high = self.create_option_btn("高画质", True)
        self.q_med = self.create_option_btn("中等")
        self.q_low = self.create_option_btn("低画质")
        
        self.quality_group.addButton(self.q_high, 1)
        self.quality_group.addButton(self.q_med, 2)
        self.quality_group.addButton(self.q_low, 3)
        
        quality_layout.addWidget(self.q_high)
        quality_layout.addWidget(self.q_med)
        quality_layout.addWidget(self.q_low)
        layout.addLayout(quality_layout)
        
        layout.addWidget(QLabel("分辨率"))
        res_layout = QHBoxLayout()
        self.res_combo = QComboBox()
        self.res_combo.addItems([
            "保持原始分辨率", 
            "1080x1920 (竖屏9:16)", 
            "720x1280 (竖屏9:16)", 
            "1920x1080 (横屏16:9)", 
            "1280x720 (横屏16:9)", 
            "1080x1080 (方形1:1)",
            "854x480 (480p)", 
            "640x360 (360p)"
        ])
        self.res_combo.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        res_layout.addWidget(self.res_combo)
        layout.addLayout(res_layout)
        
        layout.addWidget(QLabel("帧率"))
        fps_layout = QHBoxLayout()
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["保持原始帧率", "30 fps", "25 fps", "24 fps"])
        self.fps_combo.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        fps_layout.addWidget(self.fps_combo)
        layout.addLayout(fps_layout)
        
        options_group = QGroupBox("导出选项")
        options_group.setStyleSheet("QGroupBox { border: 1px solid " + _theme.color("border_strong") + "; border-radius: 5px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        options_layout = QVBoxLayout(options_group)
        
        self.burn_subtitles = QCheckBox("烧录字幕到视频")
        self.burn_subtitles.setChecked(True)
        self.burn_subtitles.setStyleSheet("color: " + _theme.color("text") + ";")
        options_layout.addWidget(self.burn_subtitles)
        
        self.burn_text = QCheckBox("烧录文字水印/标题")
        self.burn_text.setChecked(True)
        self.burn_text.setStyleSheet("color: " + _theme.color("text") + ";")
        options_layout.addWidget(self.burn_text)
        
        self.include_audio = QCheckBox("包含配音/背景音乐")
        self.include_audio.setChecked(True)
        self.include_audio.setStyleSheet("color: " + _theme.color("text") + ";")
        options_layout.addWidget(self.include_audio)
        
        layout.addWidget(options_group)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("导出")
        btn_ok.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; padding: 10px; border-radius: 5px;")
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
    def create_option_btn(self, text, checked=False):
        btn = QRadioButton(text)
        btn.setChecked(checked)
        btn.setStyleSheet("""
            QRadioButton {
                background-color: """ + _theme.color("panel2") + """;
                padding: 12px;
                border-radius: 5px;
                font-size: 13px;
            }
            QRadioButton::indicator { width: 0; height: 0; }
            QRadioButton:checked {
                border: 2px solid """ + _theme.color("warning") + """;
                background-color: """ + _theme.color("panel") + """;
            }
        """)
        return btn
        
    def on_platform_changed(self, btn):
        platform_id = self.platform_group.id(btn)
        key = self._preset_keys_by_idx.get(platform_id, "custom")
        preset = get_preset(key)

        # 自定义预设不覆盖用户已选的分辨率/帧率/质量
        if key == "custom":
            return

        # 按预设的 resolution 选择最接近的下拉项
        res = preset.resolution()
        res_map = {
            (1080, 1920): 1,  # 1080x1920 竖屏9:16
            (720, 1280): 2,   # 720x1280 竖屏9:16
            (1920, 1080): 3,  # 1920x1080 横屏16:9
            (1280, 720): 4,   # 1280x720 横屏16:9
            (1080, 1080): 5,  # 1080x1080 方形1:1
            (854, 480): 6,    # 480p
            (640, 360): 7,    # 360p
        }
        if res and res in res_map:
            self.res_combo.setCurrentIndex(res_map[res])

        # 帧率：30=1 / 25=2 / 24=3
        fps_map = {30: 1, 25: 2, 24: 3}
        if preset.fps and preset.fps in fps_map:
            self.fps_combo.setCurrentIndex(fps_map[preset.fps])

        # 质量
        q_map = {"high": self.q_high, "medium": self.q_med, "low": self.q_low}
        q_btn = q_map.get(preset.quality, self.q_high)
        q_btn.setChecked(True)
        
    def get_config(self):
        format_map = {1: "mp4", 2: "mov", 3: "avi"}
        quality_map = {1: "high", 2: "medium", 3: "low"}

        # 当前选中的预设 key（供 export worker 调用 composer.apply_preset）
        preset_idx = self.platform_group.checkedId()
        preset_key = self._preset_keys_by_idx.get(preset_idx, "custom")
        
        res_text = self.res_combo.currentText()
        resolution = None
        if "1080x1920" in res_text:
            resolution = (1080, 1920)
        elif "720x1280" in res_text:
            resolution = (720, 1280)
        elif "1920x1080" in res_text:
            resolution = (1920, 1080)
        elif "1280x720" in res_text:
            resolution = (1280, 720)
        elif "1080x1080" in res_text:
            resolution = (1080, 1080)
        elif "854x480" in res_text:
            resolution = (854, 480)
        elif "640x360" in res_text:
            resolution = (640, 360)
            
        fps_text = self.fps_combo.currentText()
        fps = None
        if "30 fps" in fps_text:
            fps = 30
        elif "25 fps" in fps_text:
            fps = 25
        elif "24 fps" in fps_text:
            fps = 24
            
        return {
            "format": format_map.get(self.format_group.checkedId(), "mp4"),
            "quality": quality_map.get(self.quality_group.checkedId(), "high"),
            "resolution": resolution,
            "fps": fps,
            "burn_subtitles": self.burn_subtitles.isChecked(),
            "burn_text": self.burn_text.isChecked(),
            "include_audio": self.include_audio.isChecked(),
            "preset_key": preset_key,
        }

class AudioEditDialog(QDialog):
    def __init__(self, clip_or_track, parent=None, is_track=False):
        super().__init__(parent)
        self.clip_or_track = clip_or_track
        self.is_track = is_track
        if is_track:
            self.setWindowTitle("编辑音频轨道")
        else:
            self.setWindowTitle("编辑视频音频")
        self.resize(500, 450)
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        if self.is_track:
            obj = self.clip_or_track
            self.volume_slider = QSlider(Qt.Orientation.Horizontal)
            self.volume_slider.setRange(0, 200)
            self.volume_slider.setValue(int(getattr(obj, 'volume', 1.0) * 100))
            self.muted_check = QCheckBox("静音")
            self.muted_check.setChecked(getattr(obj, 'muted', False))
            self.muted_check.setStyleSheet("color: " + _theme.color("text") + ";")
            self.fade_in_spin = QDoubleSpinBox()
            self.fade_in_spin.setRange(0, 10)
            self.fade_in_spin.setValue(getattr(obj, 'fade_in', 0.0))
            self.fade_out_spin = QDoubleSpinBox()
            self.fade_out_spin.setRange(0, 10)
            self.fade_out_spin.setValue(getattr(obj, 'fade_out', 0.0))
            self.noise_reduction_check = QCheckBox("降噪")
            self.noise_reduction_check.setChecked(getattr(obj, 'noise_reduction', False))
            self.noise_reduction_check.setStyleSheet("color: " + _theme.color("text") + ";")
        else:
            obj = self.clip_or_track
            self.volume_slider = QSlider(Qt.Orientation.Horizontal)
            self.volume_slider.setRange(0, 200)
            self.volume_slider.setValue(int(getattr(obj, 'audio_volume', 1.0) * 100))
            self.muted_check = QCheckBox("静音")
            self.muted_check.setChecked(getattr(obj, 'audio_muted', False))
            self.muted_check.setStyleSheet("color: " + _theme.color("text") + ";")
            self.fade_in_spin = QDoubleSpinBox()
            self.fade_in_spin.setRange(0, 10)
            self.fade_in_spin.setValue(0.0)
            self.fade_out_spin = QDoubleSpinBox()
            self.fade_out_spin.setRange(0, 10)
            self.fade_out_spin.setValue(0.0)
            self.noise_reduction_check = QCheckBox("降噪")
            self.noise_reduction_check.setChecked(False)
            self.noise_reduction_check.setStyleSheet("color: " + _theme.color("text") + ";")
            self.noise_reduction_check.setEnabled(False)
        
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("音量:"))
        self.volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid """ + _theme.color("border_strong") + """;
                height: 8px;
                background: """ + _theme.color("panel2") + """;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: """ + _theme.color("warning") + """;
                border: 1px solid """ + _theme.color("warning") + """;
                width: 18px;
                height: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
        """)
        volume_layout.addWidget(self.volume_slider)
        self.volume_label = QLabel(f"{int(self.volume_slider.value())}%")
        self.volume_label.setFixedWidth(50)
        volume_layout.addWidget(self.volume_label)
        self.volume_slider.valueChanged.connect(lambda v: self.volume_label.setText(f"{v}%"))
        layout.addLayout(volume_layout)
        
        layout.addWidget(self.muted_check)
        
        fade_layout = QHBoxLayout()
        fade_layout.addWidget(QLabel("淡入 (秒):"))
        self.fade_in_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        fade_layout.addWidget(self.fade_in_spin)
        fade_layout.addWidget(QLabel("淡出 (秒):"))
        self.fade_out_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        fade_layout.addWidget(self.fade_out_spin)
        fade_layout.addStretch()
        layout.addLayout(fade_layout)
        
        layout.addWidget(self.noise_reduction_check)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; padding: 10px; border-radius: 5px;")
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
    def get_values(self):
        volume = self.volume_slider.value() / 100.0
        if self.is_track:
            return {
                'volume': volume,
                'muted': self.muted_check.isChecked(),
                'fade_in': self.fade_in_spin.value(),
                'fade_out': self.fade_out_spin.value(),
                'noise_reduction': self.noise_reduction_check.isChecked()
            }
        else:
            return {
                'audio_volume': volume,
                'audio_muted': self.muted_check.isChecked()
            }

class ClipEditDialog(QDialog):
    def __init__(self, clip, parent=None):
        super().__init__(parent)
        self.clip = clip
        self.setWindowTitle(f"编辑片段 - {clip.name}")
        self.resize(600, 500)
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        layout.addWidget(QLabel("片段名称"))
        self.name_input = QLineEdit(self.clip.name)
        self.name_input.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        layout.addWidget(self.name_input)
        
        time_layout = QHBoxLayout()
        
        time_layout.addWidget(QLabel("开始时间 (秒):"))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0, self.clip.duration or 9999)
        self.start_spin.setValue(self.clip.start_time)
        self.start_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        time_layout.addWidget(self.start_spin)
        
        time_layout.addWidget(QLabel("结束时间 (秒):"))
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0, self.clip.duration or 9999)
        self.end_spin.setValue(self.clip.end_time or self.clip.duration or 0)
        self.end_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        time_layout.addWidget(self.end_spin)
        
        layout.addLayout(time_layout)
        
        layout.addWidget(QLabel("转场效果"))
        trans_layout = QHBoxLayout()
        self.trans_combo = QComboBox()
        self.trans_combo.addItems(["无", "淡入淡出 (Fade)", "滑动 (Slide)", "擦除 (Wipe)", "缩放 (Zoom)"])
        self.trans_combo.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 10px; border-radius: 5px;")
        trans_layout.addWidget(self.trans_combo)
        layout.addLayout(trans_layout)
        
        trans_dur_layout = QHBoxLayout()
        trans_dur_layout.addWidget(QLabel("转场时长 (秒):"))
        self.trans_dur_spin = QDoubleSpinBox()
        self.trans_dur_spin.setRange(0.1, 5.0)
        self.trans_dur_spin.setValue(self.clip.transition_duration)
        self.trans_dur_spin.setSingleStep(0.1)
        self.trans_dur_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        trans_dur_layout.addWidget(self.trans_dur_spin)
        trans_dur_layout.addStretch()
        layout.addLayout(trans_dur_layout)
        
        info_group = QGroupBox("片段信息")
        info_group.setStyleSheet("QGroupBox { border: 1px solid " + _theme.color("border_strong") + "; border-radius: 5px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        info_layout = QVBoxLayout(info_group)
        
        self.subtitle_count = QLabel(f"字幕: {len(self.clip.subtitles)} 条")
        self.subtitle_count.setStyleSheet("color: " + _theme.color("success") + ";")
        info_layout.addWidget(self.subtitle_count)
        
        self.text_count = QLabel(f"文字: {len(self.clip.text_overlays)} 个")
        self.text_count.setStyleSheet("color: " + _theme.color("accent2") + ";")
        info_layout.addWidget(self.text_count)
        
        self.audio_count = QLabel(f"配音: {len(self.clip.audio_tracks)} 条")
        self.audio_count.setStyleSheet("color: " + _theme.color("warning") + ";")
        info_layout.addWidget(self.audio_count)
        
        effect_info = "无"
        if hasattr(self.clip, 'effect') and self.clip.effect:
            if self.clip.effect.filter_type != 'none':
                filter_name = VideoEffect.FILTER_TYPES.get(self.clip.effect.filter_type, {}).get('name', self.clip.effect.filter_type)
                effect_info = filter_name
            if self.clip.effect.speed != 1.0:
                effect_info += f" | 速度: {self.clip.effect.speed:.2f}x"
        self.effect_info = QLabel(f"特效: {effect_info}")
        self.effect_info.setStyleSheet("color: " + _theme.color("danger") + ";")
        info_layout.addWidget(self.effect_info)
        
        layout.addWidget(info_group)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; padding: 10px; border-radius: 5px;")
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
    def get_values(self):
        trans_map = {
            0: None,
            1: "fade",
            2: "slide",
            3: "wipe",
            4: "zoom"
        }
        return {
            "name": self.name_input.text(),
            "start_time": self.start_spin.value(),
            "end_time": self.end_spin.value(),
            "transition": trans_map.get(self.trans_combo.currentIndex()),
            "transition_duration": self.trans_dur_spin.value()
        }

class TransitionEditDialog(QDialog):
    """转场效果编辑对话框"""

    TRANSITION_TYPES = {
        'none': {'name': '无转场', 'description': '不使用转场效果'},
        'fade': {'name': '淡入淡出 (Fade)', 'description': '平滑的淡入淡出过渡'},
        'slide_left': {'name': '向左滑动 (Slide Left)', 'description': '从右向左滑动过渡'},
        'slide_right': {'name': '向右滑动 (Slide Right)', 'description': '从左向右滑动过渡'},
        'slide_up': {'name': '向上滑动 (Slide Up)', 'description': '从下向上滑动过渡'},
        'slide_down': {'name': '向下滑动 (Slide Down)', 'description': '从上向下滑动过渡'},
        'wipe_left': {'name': '向左擦除 (Wipe Left)', 'description': '从右向左擦除过渡'},
        'wipe_right': {'name': '向右擦除 (Wipe Right)', 'description': '从左向右擦除过渡'},
        'wipe_up': {'name': '向上擦除 (Wipe Up)', 'description': '从下向上擦除过渡'},
        'wipe_down': {'name': '向下擦除 (Wipe Down)', 'description': '从上向下擦除过渡'},
        'zoom_in': {'name': '缩放进入 (Zoom In)', 'description': '从小到大缩放过渡'},
        'zoom_out': {'name': '缩放退出 (Zoom Out)', 'description': '从大到小缩放过渡'},
        'dissolve': {'name': '溶解 (Dissolve)', 'description': '像素溶解过渡'},
        'pixelize': {'name': '像素化 (Pixelize)', 'description': '像素块过渡'},
        'blur': {'name': '模糊过渡 (Blur)', 'description': '模糊淡入淡出'},
        'flash': {'name': '闪光 (Flash)', 'description': '闪光过渡效果'},
        'flip': {'name': '翻转 (Flip)', 'description': '3D翻转过渡'},
    }

    def __init__(self, clip, parent=None):
        super().__init__(parent)
        self.clip = clip
        self.setWindowTitle("设置转场效果")
        self.resize(500, 400)
        self.setStyleSheet("background-color: " + _theme.color("bg") + "; color: " + _theme.color("text") + ";")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # 片段信息
        clip_name = getattr(self.clip, 'name', '未命名片段')
        info_label = QLabel(f"当前片段: {clip_name}")
        info_label.setStyleSheet("font-size: 14px; font-weight: bold; color: " + _theme.color("warning") + ";")
        layout.addWidget(info_label)

        # 转场类型选择
        layout.addWidget(QLabel("选择转场效果:"))
        self.trans_combo = QComboBox()
        for key, value in self.TRANSITION_TYPES.items():
            self.trans_combo.addItem(value['name'], key)
        self.trans_combo.setStyleSheet("""
            QComboBox {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                padding: 10px;
                border-radius: 5px;
                min-height: 30px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                selection-background-color: """ + _theme.color("accent") + """;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
            }
        """)

        # 设置当前选中的转场
        current_transition = getattr(self.clip, 'transition', None)
        if current_transition:
            index = self.trans_combo.findData(current_transition)
            if index >= 0:
                self.trans_combo.setCurrentIndex(index)

        self.trans_combo.currentIndexChanged.connect(self.on_transition_changed)
        layout.addWidget(self.trans_combo)

        # 转场描述
        self.desc_label = QLabel("")
        self.desc_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px; padding: 5px;")
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)
        self.on_transition_changed()  # 更新描述

        # 转场时长
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("转场时长 (秒):"))
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 3.0)
        self.duration_spin.setSingleStep(0.1)
        self.duration_spin.setDecimals(1)
        self.duration_spin.setValue(getattr(self.clip, 'transition_duration', 0.5))
        self.duration_spin.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 5px;")
        duration_layout.addWidget(self.duration_spin)
        duration_layout.addStretch()
        layout.addLayout(duration_layout)

        # 预览提示
        preview_tip = QLabel("💡 提示: 转场效果将在导出视频时应用到当前片段与前一片段之间")
        preview_tip.setStyleSheet("color: " + _theme.color("accent") + "; font-size: 11px; padding: 10px; background-color: " + _theme.color("panel") + "; border-radius: 5px;")
        preview_tip.setWordWrap(True)
        layout.addWidget(preview_tip)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()

        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: " + _theme.color("text_sub") + "; padding: 10px 20px; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)

        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("panel") + "; font-weight: bold; padding: 10px 20px; border-radius: 5px;")
        btn_ok.clicked.connect(self.accept)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def on_transition_changed(self):
        """转场类型改变时更新描述"""
        transition_key = self.trans_combo.currentData()
        if transition_key and transition_key in self.TRANSITION_TYPES:
            description = self.TRANSITION_TYPES[transition_key]['description']
            self.desc_label.setText(f"描述: {description}")
        else:
            self.desc_label.setText("")

    def get_values(self):
        """获取设置的值"""
        transition_key = self.trans_combo.currentData()
        return {
            "transition": None if transition_key == 'none' else transition_key,
            "transition_duration": self.duration_spin.value()
        }

class ExportThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, timeline, output_path, config):
        super().__init__()
        # 导出可能耗时数分钟，开始前对时间线做深拷贝快照，
        # 避免导出过程中用户编辑导致片段状态变化/对象失效
        import copy
        self.timeline = copy.deepcopy(timeline)
        self.output_path = output_path
        self.config = copy.deepcopy(config)

    def run(self):
        temp_dir = os.path.join(os.path.dirname(self.output_path) or ".", "temp_clips")
        try:
            self.progress.emit(5, "正在准备导出...")
            composer = VideoComposer()

            quality = self.config.get('quality', 'high')
            burn_subtitles = self.config.get('burn_subtitles', True)
            burn_text = self.config.get('burn_text', True)
            include_audio = self.config.get('include_audio', True)
            # 共享预设：非 custom 时在拼接后做最终缩放/帧率重采样
            preset_key = self.config.get('preset_key', 'custom')
            preset_obj = get_preset(preset_key) if preset_key and preset_key != 'custom' else None

            os.makedirs(temp_dir, exist_ok=True)

            all_clips = []
            for track_idx, track in enumerate(self.timeline.tracks):
                for clip in track:
                    if hasattr(clip, 'path') and clip.path:
                        all_clips.append((track_idx, clip))

            all_clips.sort(key=lambda x: x[1].start_time or 0)

            if not all_clips:
                self.error.emit("时间线为空，没有可导出的片段")
                return

            processed_clips = []
            total = len(all_clips)

            for i, (track_idx, clip) in enumerate(all_clips):
                self.progress.emit(10 + int((i / total) * 60), f"正在处理片段 {i+1}/{total}...")

                output_clip = os.path.join(temp_dir, f"clip_{i}.mp4")
                ok = self.process_clip(clip, output_clip, composer, burn_subtitles, burn_text, include_audio)
                # 单片段处理失败必须中止导出，不能把损坏/空文件送进 concat
                if not ok or not os.path.exists(output_clip) or os.path.getsize(output_clip) == 0:
                    self.error.emit(f"片段 {i+1} 处理失败，请检查该片段的素材与特效设置")
                    return
                processed_clips.append(output_clip)

            self.progress.emit(75, "正在合并视频...")

            if len(processed_clips) == 1:
                shutil.copy(processed_clips[0], self.output_path)
                # 单片段也要应用导出预设（缩放/帧率），否则平台预设被静默绕过
                if preset_obj is not None:
                    scaled = composer.apply_preset(self.output_path, self.output_path, preset_obj)
                    if not scaled or not os.path.exists(self.output_path) or os.path.getsize(self.output_path) == 0:
                        self.error.emit("应用导出预设失败，未生成有效的输出文件")
                        return
                concat_result = self.output_path
            else:
                # 收集转场信息
                transitions = []
                for i, (_, clip) in enumerate(all_clips):
                    if i > 0:  # 第一个片段没有转场（它是第二个片段的转场）
                        trans = getattr(clip, 'transition', None)
                        trans_dur = getattr(clip, 'transition_duration', 0.5)
                        transitions.append({
                            'type': trans,
                            'duration': trans_dur
                        })

                has_transition = any(t['type'] for t in transitions)
                transition_dur = transitions[0]['duration'] if has_transition else 0

                concat_result = composer.concat_clips(
                    processed_clips,
                    self.output_path,
                    quality=quality,
                    transition_duration=transition_dur if has_transition else 0,
                    transitions=transitions if has_transition else None,
                    preset=preset_obj,
                )

            self.progress.emit(90, "正在清理临时文件...")

            if not concat_result or not os.path.exists(self.output_path) or os.path.getsize(self.output_path) == 0:
                self.error.emit("视频合并失败，未生成有效的输出文件")
                return

            self.progress.emit(100, "导出完成!")
            self.finished.emit(self.output_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))
        finally:
            # 无论成功失败都清理临时片段目录
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            
    def process_clip(self, clip, output_path, composer, burn_subtitles, burn_text, include_audio):
        """处理单个片段。成功且产物非空返回 True，否则返回 False（不再静默用源片顶替）。"""
        import ffmpeg

        try:
            # 使用源文件中的相对时间，而不是时间线上的绝对时间
            # start_time/end_time 是时间线上的绝对位置
            # 对于源文件截取，我们应该从0开始，使用片段的完整时长
            source_start = 0
            source_duration = clip.duration if clip.duration else 5.0

            is_audio_only = hasattr(clip, 'audio_only') and clip.audio_only
            audio_muted = hasattr(clip, 'audio_muted') and clip.audio_muted

            if is_audio_only:
                if include_audio:
                    input_audio = ffmpeg.input(clip.path, ss=source_start, t=source_duration)
                    out = ffmpeg.output(
                        None,
                        input_audio.audio,
                        output_path,
                        acodec='aac',
                        pix_fmt='yuv420p'
                    )
                    out.run(cmd=composer.ffmpeg_path, overwrite_output=True, quiet=True)
                    return os.path.exists(output_path) and os.path.getsize(output_path) > 0
                else:
                    # 不导出音频时，生成等长黑屏静音占位片段（保证时间线对齐与 concat 有效）
                    return self._make_black_clip(output_path, source_duration, composer)

            input_video = ffmpeg.input(clip.path, ss=source_start, t=source_duration)

            video_stream = input_video.video
            audio_stream = input_video.audio

            if audio_muted:
                audio_stream = None

            effect_filter = clip.effect.get_ffmpeg_filter() if hasattr(clip, 'effect') and clip.effect else None
            if effect_filter:
                video_stream = video_stream.filter(effect_filter)

            if burn_subtitles and hasattr(clip, 'subtitles') and clip.subtitles:
                srt_path = output_path + ".srt"
                self.generate_srt(clip.subtitles, srt_path)
                safe_srt_path = srt_path.replace('\\', '/').replace(':', '\\:')
                video_stream = video_stream.filter('subtitles', safe_srt_path)

            if burn_text and hasattr(clip, 'text_overlays') and clip.text_overlays:
                for overlay in clip.text_overlays:
                    video_stream = self.add_text_filter(video_stream, overlay)

            # 变速：setpts=PTS/k，k<1 时间戳变大→慢放；k>1 时间戳变小→快放。
            # 音频用 atempo=k 同步（k 即播放速度倍率）。
            speed = clip.effect.speed if hasattr(clip, 'effect') and clip.effect else 1.0
            try:
                speed = float(speed)
            except (TypeError, ValueError):
                speed = 1.0
            speed = max(0.25, min(speed, 4.0))
            if speed != 1.0:
                video_stream = video_stream.filter('setpts', f'PTS/{speed}')

                if audio_stream and include_audio and not audio_muted:
                    atempo_filters = self.get_atempo_filters(speed)
                    for atempo_filter in atempo_filters:
                        audio_stream = audio_stream.filter(atempo_filter)

            out = ffmpeg.output(
                video_stream,
                audio_stream if include_audio and not audio_muted else None,
                output_path,
                vcodec='libx264',
                acodec='aac' if include_audio and not audio_muted else None,
                pix_fmt='yuv420p'
            )
            out.run(cmd=composer.ffmpeg_path, overwrite_output=True, quiet=True)

            return os.path.exists(output_path) and os.path.getsize(output_path) > 0

        except Exception as e:
            print(f"Error processing clip: {e}")
            import traceback
            traceback.print_exc()
            # 清理可能残留的半截文件
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except OSError:
                pass
            return False

    def _make_black_clip(self, output_path, duration, composer):
        """生成指定时长的黑屏静音片段（用于纯音频轨但不导出音频的情况）。"""
        import ffmpeg
        try:
            black = ffmpeg.input('color=c=black:s=1024x1024:r=25', format='lavfi', t=duration)
            silence = ffmpeg.input('anullsrc=r=44100:cl=stereo', format='lavfi', t=duration)
            out = ffmpeg.output(
                black.video, silence.audio, output_path,
                vcodec='libx264', pix_fmt='yuv420p',
                acodec='aac', ar=44100, ac=2
            )
            out.run(cmd=composer.ffmpeg_path, overwrite_output=True, quiet=True)
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            print(f"Error creating black clip: {e}")
            return False
            
    def generate_srt(self, subtitles, output_path):
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, sub in enumerate(subtitles):
                start_str = self.format_timestamp(sub.start_time)
                end_str = self.format_timestamp(sub.end_time)
                f.write(f"{i+1}\n")
                f.write(f"{start_str} --> {end_str}\n")
                f.write(f"{sub.text}\n\n")
                
    def format_timestamp(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"
    
    def get_atempo_filters(self, speed):
        filters = []
        atempo = speed
        while atempo > 2.0:
            filters.append('atempo=2.0')
            atempo = atempo / 2.0
        while atempo < 0.5:
            filters.append('atempo=0.5')
            atempo = atempo / 0.5
        if atempo != 1.0:
            filters.append(f'atempo={atempo}')
        return filters if filters else ['atempo=1.0']
        
    # 常见中文字体族名 → Windows 字体文件
    FONT_FILE_MAP = {
        'microsoft yahei': 'C:/Windows/Fonts/msyh.ttc',
        '微软雅黑': 'C:/Windows/Fonts/msyh.ttc',
        'simhei': 'C:/Windows/Fonts/simhei.ttf',
        '黑体': 'C:/Windows/Fonts/simhei.ttf',
        'simsun': 'C:/Windows/Fonts/simsun.ttc',
        '宋体': 'C:/Windows/Fonts/simsun.ttc',
        'kaiti': 'C:/Windows/Fonts/simkai.ttf',
        '楷体': 'C:/Windows/Fonts/simkai.ttf',
        'arial': 'C:/Windows/Fonts/arial.ttf',
    }

    def _resolve_font_file(self, font_family):
        """drawtext 的 fontfile 需要真实字体文件路径，不能直接传字体族名。"""
        if not font_family:
            return 'C\\:/Windows/Fonts/msyh.ttc'
        candidate = str(font_family).replace('\\', '/')
        # 已经是显式字体文件路径
        if candidate.lower().endswith(('.ttf', '.ttc', '.otf')):
            mapped = candidate if os.path.exists(candidate) else None
        else:
            mapped = self.FONT_FILE_MAP.get(font_family.strip().lower())
            if mapped and not os.path.exists(mapped):
                mapped = None
        if not mapped:
            for fallback in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf'):
                if os.path.exists(fallback):
                    mapped = fallback
                    break
        if not mapped:
            return None
        # 滤镜语法中转义盘符冒号与反斜杠
        return mapped.replace(':', '\\:')

    @staticmethod
    def _escape_drawtext_text(text):
        """转义 drawtext 文本中的特殊字符。"""
        if text is None:
            return ''
        s = str(text)
        s = s.replace('\\', '\\\\')   # 反斜杠优先
        s = s.replace(':', '\\:')
        s = s.replace("'", "\\'")
        s = s.replace('%', '\\%')
        s = s.replace('\r', ' ').replace('\n', ' ')
        return s

    def add_text_filter(self, video_stream, overlay):
        style = overlay.style or {}
        font_family = style.get('font_family', 'Microsoft YaHei')
        font_size = style.get('font_size', 36)
        color = style.get('color', '#ffffff').replace('#', '')
        outline_color = style.get('outline_color', '#000000').replace('#', '')

        x = overlay.x
        y = overlay.y

        escaped_text = self._escape_drawtext_text(overlay.text)
        font_file = self._resolve_font_file(font_family)

        kwargs = {
            'text': escaped_text,
            'fontsize': font_size,
            'fontcolor': f'0x{color}',
            'x': f'{x}*(w-text_w)/100',
            'y': f'{y}*(h-text_h)/100',
            'borderw': 2,
            'bordercolor': f'0x{outline_color}',
        }
        if font_file:
            kwargs['fontfile'] = font_file

        return video_stream.filter('drawtext', **kwargs)


class VideoEditorWindow(QWidget):
    def __init__(self, project_dir=None):
        super().__init__()
        self.project_dir = project_dir
        self.clips = []
        self.current_clip_index = -1
        self.media_player = None
        self.audio_output = None
        self.video_widget = None
        self._current_playing_clip = None
        self._pending_seek_position = None
        self._video_captures = {}
        self._current_playing_clips = []
        self._is_timeline_playing = False
        
        # 撤销/恢复历史记录
        self._history = []
        self._history_index = -1
        self._max_history = 50  # 最大历史记录数
        
        self.init_ui()
        
    def set_project_dir(self, path):
        self.project_dir = path
        if hasattr(self, 'storyboard_panel') and self.storyboard_panel:
            self.storyboard_panel.set_project_dir(path)
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        content_splitter = QSplitter(Qt.Orientation.Vertical)
        
        upper_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(5)
        
        # 「分镜」标题已按需求移除（左侧分镜面板自带工具条）
        from ui.video_gen_window import VideoGenWindow
        self.storyboard_panel = VideoGenWindow(self.project_dir)
        self.storyboard_panel.add_to_timeline.connect(self.on_storyboard_add_to_timeline)
        self.storyboard_panel.add_to_library.connect(self.add_clip_to_library)
        left_layout.addWidget(self.storyboard_panel, 1)
        
        # 左侧分镜/提示词面板：按比例自适应，最小宽度保证底部按钮文字完整显示
        left_panel.setMinimumWidth(320)
        left_panel.setMaximumWidth(470)
        upper_splitter.addWidget(left_panel)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(5)
        
        preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_preview = QWidget()
        left_preview_layout = QVBoxLayout(left_preview)
        left_preview_layout.setContentsMargins(0, 0, 0, 0)
        left_preview_layout.setSpacing(5)
        
        preview_header_layout = QHBoxLayout()
        preview_header = QLabel("视频预览")
        preview_header.setStyleSheet("color: " + _theme.color("warning") + "; font-weight: bold; font-size: 14px; padding: 5px;")
        preview_header_layout.addWidget(preview_header)
        
        preview_header_layout.addStretch()
        
        # 视频增强按钮
        self.video_enhance_btn = QPushButton("✨ 视频增强")
        self.video_enhance_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("accent2") + """; color: """ + _theme.color("accent_text") + """;
                padding: 5px 15px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("accent2") + """;
            }
        """)
        self.video_enhance_btn.clicked.connect(self.open_video_enhance_dialog)
        preview_header_layout.addWidget(self.video_enhance_btn)
        
        self.export_btn = QPushButton("导出视频")
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("warning") + """;
                color: """ + _theme.color("panel") + """;
                padding: 5px 15px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("warning") + """;
            }
        """)
        self.export_btn.clicked.connect(self.export_video)
        preview_header_layout.addWidget(self.export_btn)
        
        left_preview_layout.addLayout(preview_header_layout)
        
        self.video_widget = QFrame()
        # 视频预览界面不需要边框
        self.video_widget.setStyleSheet("background-color: #000; border-radius: 5px;")
        self.video_widget.setMinimumSize(320, 180)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 使用 QVBoxLayout 而不是 QStackedLayout
        video_layout = QVBoxLayout(self.video_widget)
        video_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建一个容器来容纳视频内容
        self.video_container = QWidget()
        self.video_container.setStyleSheet("background-color: transparent;")
        self.video_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 视频容器使用绝对布局
        self.video_container_layout = QVBoxLayout(self.video_container)
        self.video_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加视频输出
        self.video_output = QVideoWidget()
        self.video_output.setStyleSheet("background-color: black;")
        self.video_output.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_container_layout.addWidget(self.video_output)
        
        # 添加视频标签（用于显示图片预览）
        self.video_label = QLabel(self.video_container)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_label.setStyleSheet("background-color: transparent;")
        self.video_label.setGeometry(self.video_container.rect())
        self.video_label.hide()  # 默认隐藏，只在需要时显示
        
        # 添加字幕叠加层
        self.subtitle_overlay = SubtitleOverlayWidget(self.video_container)
        self.subtitle_overlay.setGeometry(self.video_container.rect())
        self.subtitle_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.subtitle_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.subtitle_overlay.raise_()  # 确保字幕叠加层在最上层
        self.subtitle_overlay.show()  # 确保字幕层始终可见
        
        # 添加到主布局
        video_layout.addWidget(self.video_container)
        
        left_preview_layout.addWidget(self.video_widget, 1)
        
        controls_frame = QFrame()
        controls_frame.setStyleSheet("background-color: " + _theme.color("panel") + "; border-radius: 5px;")
        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(10, 5, 10, 5)
        
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("warning") + """;
                color: """ + _theme.color("panel") + """;
                border-radius: 20px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("warning") + """;
            }
        """)
        self.play_btn.clicked.connect(self.toggle_play)
        controls_layout.addWidget(self.play_btn)
        
        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedSize(40, 40)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("danger") + """; color: """ + _theme.color("text") + """;
                border-radius: 20px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("danger") + """;
            }
        """)
        self.stop_btn.clicked.connect(self.stop_video)
        controls_layout.addWidget(self.stop_btn)
        
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid """ + _theme.color("border_strong") + """;
                height: 8px;
                background: """ + _theme.color("panel2") + """;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: """ + _theme.color("warning") + """;
                border: 1px solid """ + _theme.color("warning") + """;
                width: 18px;
                height: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
        """)
        self.position_slider.sliderMoved.connect(self.seek_video)
        controls_layout.addWidget(self.position_slider)
        
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet("color: " + _theme.color("text") + "; font-size: 12px;")
        self.time_label.setFixedWidth(100)
        controls_layout.addWidget(self.time_label)
        
        left_preview_layout.addWidget(controls_frame)
        
        preview_splitter.addWidget(left_preview)
        
        right_preview = QWidget()
        right_preview.setObjectName("MaterialPanel")
        # 用 objectName 限定作用域，避免边框样式级联到子控件
        right_preview.setStyleSheet(
            "#MaterialPanel { background-color: " + _theme.color("bg") + "; "
            "border: 1px solid " + _theme.color("border_strong") + "; border-radius: 6px; }")
        right_preview_layout = QVBoxLayout(right_preview)
        right_preview_layout.setContentsMargins(8, 8, 8, 8)
        right_preview_layout.setSpacing(5)

        import_btn_frame = QFrame()
        import_btn_frame.setStyleSheet("background-color: transparent;")
        import_btn_layout = QHBoxLayout(import_btn_frame)
        import_btn_layout.setContentsMargins(0, 0, 0, 5)
        import_btn_layout.setSpacing(5)
        
        import_btn = QPushButton("导入视频")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("accent") + """; color: """ + _theme.color("text") + """;
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("accent2") + """;
            }
        """)
        import_btn.clicked.connect(self.import_videos)
        import_btn_layout.addWidget(import_btn)
        
        import_project_btn = QPushButton("导入项目视频")
        import_project_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("accent2") + """; color: """ + _theme.color("accent_text") + """;
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("accent2") + """;
            }
        """)
        import_project_btn.clicked.connect(self.import_project_videos)
        import_btn_layout.addWidget(import_project_btn)
        
        import_btn_layout.addStretch()
        right_preview_layout.addWidget(import_btn_frame)
        
        self.clip_list = DraggableListWidget()
        self.clip_list.setStyleSheet("""
            QListWidget {
                background-color: """ + _theme.color("bg") + """;
                border: 1px solid """ + _theme.color("panel2") + """;
                border-radius: 5px;
            }
            QListWidget::item {
                background-color: """ + _theme.color("panel") + """;
                margin: 2px;
                border-radius: 3px;
                padding: 5px; color: """ + _theme.color("text") + """;
                border: 2px solid transparent;
            }
            QListWidget::item:selected {
                background-color: """ + _theme.color("accent") + """;
                border: 2px solid """ + _theme.color("warning") + """;
            }
            QListWidget::item:hover {
                background-color: """ + _theme.color("panel2") + """;
                border: 2px solid """ + _theme.color("info") + """;
            }
            QListWidget::item:hover:selected {
                background-color: """ + _theme.color("accent") + """;
                border: 2px solid """ + _theme.color("warning") + """;
            }
        """)
        self.clip_list.setDragEnabled(True)
        self.clip_list.itemDoubleClicked.connect(self.on_clip_double_clicked)
        self.clip_list.clip_dropped.connect(self.on_clip_dropped_to_timeline)
        self.clip_list.delete_item_requested.connect(self.on_clip_delete_requested)
        right_preview_layout.addWidget(self.clip_list)
        
        preview_splitter.addWidget(right_preview)
        
        preview_splitter.setStretchFactor(0, 3)
        preview_splitter.setStretchFactor(1, 1)
        preview_splitter.setHandleWidth(3)
        
        right_layout.addWidget(preview_splitter, 1)
        
        upper_splitter.addWidget(right_panel)
        
        # 左栏随窗口按比例伸缩，右侧（预览+素材库）占主要空间
        upper_splitter.setStretchFactor(0, 1)
        upper_splitter.setStretchFactor(1, 3)
        upper_splitter.setSizes([320, 1100])
        upper_splitter.setHandleWidth(3)
        upper_splitter.setChildrenCollapsible(False)
        upper_splitter.setMinimumHeight(200)
        
        content_splitter.addWidget(upper_splitter)
        
        timeline_frame = QFrame()
        timeline_frame.setStyleSheet("background-color: " + _theme.color("bg") + ";")
        timeline_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        timeline_frame.setMinimumHeight(100)
        timeline_layout = QVBoxLayout(timeline_frame)
        timeline_layout.setContentsMargins(5, 5, 5, 5)
        timeline_layout.setSpacing(5)
        
        timeline_header_layout = QHBoxLayout()

        # 撤销按钮（简洁箭头 + 悬停提示）
        self.undo_btn = QPushButton("↶")
        self.undo_btn.setToolTip("撤销 (Ctrl+Z)")
        self.undo_btn.setFixedSize(32, 26)
        self.undo_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                border: none;
                border-radius: 3px;
                padding: 0px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("accent") + """;
            }
            QPushButton:disabled {
                background-color: """ + _theme.color("panel") + """;
                color: """ + _theme.color("text_sub") + """;
            }
        """)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo)
        timeline_header_layout.addWidget(self.undo_btn)
        
        # 恢复按钮
        self.redo_btn = QPushButton("↷")
        self.redo_btn.setToolTip("恢复 (Ctrl+Y)")
        self.redo_btn.setFixedSize(32, 26)
        self.redo_btn.setStyleSheet("""
            QPushButton {
                background-color: """ + _theme.color("panel2") + """; color: """ + _theme.color("text") + """;
                border: none;
                border-radius: 3px;
                padding: 0px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: """ + _theme.color("accent") + """;
            }
            QPushButton:disabled {
                background-color: """ + _theme.color("panel") + """;
                color: """ + _theme.color("text_sub") + """;
            }
        """)
        self.redo_btn.setEnabled(False)
        self.redo_btn.clicked.connect(self.redo)
        timeline_header_layout.addWidget(self.redo_btn)
        
        timeline_header_layout.addSpacing(10)
        
        self.split_btn = QPushButton("切割")
        self.split_btn.setStyleSheet("background-color: " + _theme.color("danger") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
        self.split_btn.clicked.connect(self.split_clip_at_playhead)
        timeline_header_layout.addWidget(self.split_btn)

        # 先创建 TimelineWidget
        self.timeline = TimelineWidget()
        self.timeline.clip_selected.connect(self.on_timeline_clip_selected)
        self.timeline.clip_double_clicked.connect(self.on_timeline_clip_double_clicked)
        self.timeline.time_dragged.connect(self.on_time_dragged)
        self.timeline.zoom_changed.connect(self.on_zoom_changed)
        # 连接编辑信号用于撤销/恢复
        self.timeline.edit_started.connect(self._on_edit_started)
        self.timeline.edit_finished.connect(self._on_edit_finished)

        # 缩放按钮（纯符号按钮，悬停显示说明）
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setToolTip("缩小时间线（显示更多时间）")
        zoom_out_btn.setFixedSize(32, 26)
        zoom_out_btn.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: none; border-radius: 3px; padding: 0px; font-size: 18px;")
        zoom_out_btn.clicked.connect(self.timeline.zoom_out)
        timeline_header_layout.addWidget(zoom_out_btn)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px; min-width: 50px;")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timeline_header_layout.addWidget(self.zoom_label)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setToolTip("放大时间线（看清细节）")
        zoom_in_btn.setFixedSize(32, 26)
        zoom_in_btn.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: none; border-radius: 3px; padding: 0px; font-size: 18px;")
        zoom_in_btn.clicked.connect(self.timeline.zoom_in)
        timeline_header_layout.addWidget(zoom_in_btn)

        timeline_header_layout.addSpacing(10)

        # 轨道管理按钮
        add_track_btn = QPushButton("+ 轨道")
        add_track_btn.setStyleSheet("background-color: " + _theme.color("success") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
        add_track_btn.clicked.connect(self.add_track)
        timeline_header_layout.addWidget(add_track_btn)

        remove_track_btn = QPushButton("- 轨道")
        remove_track_btn.setStyleSheet("background-color: " + _theme.color("danger") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
        remove_track_btn.clicked.connect(self.remove_track)
        timeline_header_layout.addWidget(remove_track_btn)

        timeline_header_layout.addSpacing(10)

        # 片段管理按钮
        remove_btn = QPushButton("移除")
        remove_btn.setStyleSheet("background-color: " + _theme.color("danger") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
        remove_btn.clicked.connect(self.remove_selected_clip)
        timeline_header_layout.addWidget(remove_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setStyleSheet("background-color: " + _theme.color("text_sub") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
        clear_btn.clicked.connect(self.clear_timeline)
        timeline_header_layout.addWidget(clear_btn)

        timeline_header_layout.addStretch()

        # 音频相关按钮（放在音频编辑按钮左边）
        separate_audio_btn = QPushButton("🔊 分离音频")
        separate_audio_btn.setStyleSheet("background-color: " + _theme.color("danger") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
        separate_audio_btn.clicked.connect(self.separate_audio_from_clip)
        timeline_header_layout.addWidget(separate_audio_btn)

        add_audio_btn = QPushButton("🎵 配音")
        add_audio_btn.setStyleSheet("background-color: " + _theme.color("warning") + "; color: " + _theme.color("accent_text") + "; padding: 5px 10px; border-radius: 3px;")
        add_audio_btn.clicked.connect(self.add_audio)
        timeline_header_layout.addWidget(add_audio_btn)

        transition_btn = QPushButton("🎬 转场")
        transition_btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
        transition_btn.clicked.connect(self.open_transition_dialog)
        timeline_header_layout.addWidget(transition_btn)

        effect_btn = QPushButton("✨ 视频特效")
        effect_btn.setStyleSheet("background-color: " + _theme.color("danger") + "; color: " + _theme.color("text") + "; padding: 5px 10px; border-radius: 3px;")
        effect_btn.clicked.connect(self.open_effects)
        timeline_header_layout.addWidget(effect_btn)

        timeline_layout.addLayout(timeline_header_layout)
        
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidget(self.timeline)
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setMinimumHeight(80)
        self.timeline_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.timeline_scroll.setStyleSheet("""
            QScrollArea {
                background-color: """ + _theme.color("bg") + """;
                border: none;
            }
            QScrollBar:vertical {
                background-color: """ + _theme.color("panel") + """;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: """ + _theme.color("border_strong") + """;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: """ + _theme.color("text_sub") + """;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background-color: """ + _theme.color("panel") + """;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background-color: """ + _theme.color("border_strong") + """;
                border-radius: 6px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: """ + _theme.color("text_sub") + """;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        timeline_layout.addWidget(self.timeline_scroll, 1)
        
        tools_frame = QFrame()
        tools_frame.setStyleSheet("background-color: " + _theme.color("panel") + "; border-radius: 5px;")
        tools_layout = QHBoxLayout(tools_frame)
        tools_layout.setContentsMargins(10, 5, 10, 5)
        
        subtitle_btn = QPushButton("📝 添加字幕")
        subtitle_btn.setStyleSheet("background-color: " + _theme.color("success") + "; color: " + _theme.color("text") + "; padding: 8px 15px; border-radius: 5px;")
        subtitle_btn.clicked.connect(self.add_subtitle)
        tools_layout.addWidget(subtitle_btn)
        
        import_srt_btn = QPushButton("📄 导入字幕")
        import_srt_btn.setStyleSheet("background-color: " + _theme.color("success") + "; color: " + _theme.color("text") + "; padding: 8px 15px; border-radius: 5px;")
        import_srt_btn.clicked.connect(self.import_subtitle_file)
        tools_layout.addWidget(import_srt_btn)
        
        script_subtitle_btn = QPushButton("📜 剧本字幕")
        script_subtitle_btn.setStyleSheet("background-color: " + _theme.color("success") + "; color: " + _theme.color("accent_text") + "; padding: 8px 15px; border-radius: 5px;")
        script_subtitle_btn.clicked.connect(self.generate_subtitle_from_script)
        tools_layout.addWidget(script_subtitle_btn)
        
        text_btn = QPushButton("✏️ 添加文字")
        text_btn.setStyleSheet("background-color: " + _theme.color("accent2") + "; color: " + _theme.color("accent_text") + "; padding: 8px 15px; border-radius: 5px;")
        text_btn.clicked.connect(self.add_text_overlay)
        tools_layout.addWidget(text_btn)

        # 语音相关按钮（原在时间线工具条，移至此处与字幕/文字操作并列）
        tts_btn = QPushButton("🗣️ 文字转语音")
        tts_btn.setStyleSheet("background-color: " + _theme.color("success") + "; color: " + _theme.color("accent_text") + "; padding: 8px 15px; border-radius: 5px;")
        tts_btn.clicked.connect(self.open_tts)
        tools_layout.addWidget(tts_btn)

        self.edit_audio_btn = QPushButton("🎵 音频编辑")
        self.edit_audio_btn.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 8px 15px; border-radius: 5px;")
        self.edit_audio_btn.clicked.connect(self.edit_audio)
        self.edit_audio_btn.setEnabled(False)
        tools_layout.addWidget(self.edit_audio_btn)

        tools_layout.addStretch()
        
        self.info_label = QLabel("选择片段后可添加字幕、文字、配音和特效")
        self.info_label.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 12px;")
        tools_layout.addWidget(self.info_label)
        
        timeline_layout.addWidget(tools_frame)
        
        content_splitter.addWidget(timeline_frame)
        
        content_splitter.setStretchFactor(0, 3)
        content_splitter.setStretchFactor(1, 2)
        content_splitter.setHandleWidth(3)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: """ + _theme.color("panel2") + """;
            }
            QSplitter::handle:vertical {
                background-color: """ + _theme.color("panel2") + """;
            }
        """)
        content_splitter.splitterMoved.connect(self.on_timeline_splitter_moved)
        
        layout.addWidget(content_splitter, 1)
        
        self.upper_splitter = upper_splitter
        self.content_splitter = content_splitter
        self.timeline_frame = timeline_frame
        
        self._polish_buttons()
        self.init_media_player()

    def _btn_feedback_qss(self) -> str:
        """统一的按钮悬停/按下描边规则（追加在按钮基础样式之后）。

        用 1px 主题强调色描边，避免深色粗边框带来的突兀感。
        """
        return f"""
QPushButton:hover {{ border: 1px solid {_theme.color("accent")}; }}
QPushButton:pressed {{ border: 1px solid {_theme.color("accent2")}; }}
"""

    def _set_button_style(self, btn, qss: str):
        """设置按钮基础样式，并重新附加统一的悬停/按下反馈。"""
        base = _theme.as_rule_block(qss)
        btn.setProperty("_base_qss", base)
        btn.setStyleSheet(base + self._btn_feedback_qss())

    def _polish_buttons(self):
        """统一补齐按钮的手型光标与悬停/按下反馈。

        页面按钮都用 QSS 重写了外观，Qt 自带的 hover/pressed 效果被覆盖，
        看起来就像“点了没反应”。这里给所有按钮追加对比色描边。
        """
        for btn in self.findChildren(QPushButton):
            base = btn.property("_base_qss")
            if base is None:
                base = _theme.as_rule_block(btn.styleSheet() or "")
                btn.setProperty("_base_qss", base)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(base + self._btn_feedback_qss())
        
    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(100, self.set_initial_sizes)
    
    def set_initial_sizes(self):
        # 左栏按窗口宽度自适应（约占 26%，限制在可读区间），不写死固定宽度
        LEFT_PANEL_RATIO = 0.26
        LEFT_MIN, LEFT_MAX = 320, 470
        if hasattr(self, 'upper_splitter') and self.upper_splitter:
            total_width = self.upper_splitter.width() or self.width()
            if total_width > 0:
                left = int(total_width * LEFT_PANEL_RATIO)
                left = max(LEFT_MIN, min(left, LEFT_MAX))
                self.upper_splitter.setSizes([left, max(total_width - left, 300)])
        
        if hasattr(self, 'content_splitter') and self.content_splitter:
            total_height = self.height()
            if total_height > 0:
                upper_height = int(total_height * 0.6)
                timeline_height = total_height - upper_height
                self.content_splitter.setSizes([upper_height, timeline_height])
    
    def on_timeline_splitter_moved(self, pos, index):
        screen = QApplication.primaryScreen()
        if screen:
            screen_height = screen.availableGeometry().height()
            max_timeline_height = screen_height // 2
            
            total_height = self.content_splitter.height()
            current_timeline_height = total_height - pos
            
            if current_timeline_height > max_timeline_height:
                new_upper_height = total_height - max_timeline_height
                self.content_splitter.blockSignals(True)
                self.content_splitter.setSizes([new_upper_height, max_timeline_height])
                self.content_splitter.blockSignals(False)
        
    def init_media_player(self):
        try:
            self.media_player = QMediaPlayer()
            self.audio_output = QAudioOutput()
            self.media_player.setAudioOutput(self.audio_output)
            
            # 直接使用已创建的 video_output
            if hasattr(self, 'video_output'):
                self.video_label.hide()
                self.media_player.setVideoOutput(self.video_output)
            
            self.media_player.positionChanged.connect(self.update_position)
            self.media_player.durationChanged.connect(self.update_duration)
            self.media_player.playbackStateChanged.connect(self.update_play_button)
            self.media_player.mediaStatusChanged.connect(self.media_status_changed)
            
            self.timeline.time_dragged.connect(self.on_time_dragged)
            self.timeline.time_clicked.connect(self.on_time_clicked)
        except Exception as e:
            print(f"DEBUG: Media player init error: {e}")
            self.media_player = None
        
    def media_status_changed(self, status):
        try:
            if not hasattr(self, 'media_player') or self.media_player is None:
                return
            if status == QMediaPlayer.MediaStatus.InvalidMedia:
                print(f"Error: Invalid Media. Error string: {self.media_player.errorString()}")
                # 媒体错误时停止播放
                self._is_timeline_playing = False
                if hasattr(self, '_timeline_timer') and self._timeline_timer.isActive():
                    self._timeline_timer.stop()
                # 停止媒体播放器
                self.media_player.stop()
                # 更新播放按钮
                if hasattr(self, 'play_btn'):
                    self.play_btn.setText("▶")
                    self.play_btn.repaint()
            elif status == QMediaPlayer.MediaStatus.EndOfMedia:
                # 媒体播放结束
                # 如果是在时间线播放模式下，不停止时间线，让时间线继续播放下一个片段
                if not getattr(self, '_is_timeline_playing', False):
                    # 非时间线播放模式，停止播放
                    if hasattr(self, '_timeline_timer') and self._timeline_timer.isActive():
                        self._timeline_timer.stop()
                    # 停止媒体播放器
                    self.media_player.stop()
                    # 更新播放按钮
                    if hasattr(self, 'play_btn'):
                        self.play_btn.setText("▶")
                        self.play_btn.repaint()
                # 如果在时间线播放模式下，让_timer_tick继续处理下一个片段
                # 但我们需要确保_media_player不会阻止后续播放
            elif status == QMediaPlayer.MediaStatus.NoMedia:
                # 没有媒体（可能是解码错误），停止时间线播放
                self._is_timeline_playing = False
                if hasattr(self, '_timeline_timer') and self._timeline_timer.isActive():
                    self._timeline_timer.stop()
                # 停止媒体播放器
                self.media_player.stop()
                # 更新播放按钮
                if hasattr(self, 'play_btn'):
                    self.play_btn.setText("▶")
                    self.play_btn.repaint()
            elif status == QMediaPlayer.MediaStatus.LoadedMedia:
                # 修复：不要隐藏video_label，因为多轨道预览使用它来显示画面
                # self.video_label.hide()
                if hasattr(self, '_pending_seek_position') and self._pending_seek_position is not None:
                    self.media_player.setPosition(self._pending_seek_position)
                    self._pending_seek_position = None
                # 媒体加载完成后开始播放（用于时间线连续播放）
                if getattr(self, '_is_timeline_playing', False):
                    self.media_player.play()
        except Exception as e:
            print(f"DEBUG: media_status_changed error: {e}")
        
    def import_videos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 
            "选择素材文件", 
            "", 
            "所有支持的文件 (*.mp4 *.mov *.avi *.mkv *.webm *.jpg *.jpeg *.png *.gif *.bmp *.wav *.mp3 *.aac *.flac *.m4a);;" +
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.webm);;" +
            "图片文件 (*.jpg *.jpeg *.png *.gif *.bmp);;" +
            "音频文件 (*.wav *.mp3 *.aac *.flac *.m4a);;" +
            "所有文件 (*.*)"
        )
        
        if files:
            for file in files:
                self.add_clip_to_library(file)
                
    def on_storyboard_add_to_timeline(self, video_path):
        if video_path and os.path.exists(video_path):
            self.add_clip_to_library(video_path)
            self.add_clip_at_playhead_from_path(video_path)
            
    def add_clip_at_playhead_from_path(self, path):
        composer = VideoComposer()
        duration = composer.get_audio_duration(path)
        
        clip = VideoClip(path, duration=duration)
        
        playhead_time = self.timeline.playback_position
        
        preferred_type = "video"
        if hasattr(clip, 'clip_type'):
            preferred_type = clip.clip_type
        elif hasattr(clip, 'audio_only') and clip.audio_only:
            preferred_type = "audio"
        
        track_idx = self.timeline.find_available_track_for_time(playhead_time, duration or 1, preferred_type)
        
        clip.start_time = playhead_time
        
        if track_idx >= 0 and track_idx < len(self.timeline.tracks):
            # 保存状态到历史记录（在修改前）
            self._save_state_to_history()
            
            self.timeline.tracks[track_idx].append(clip)
            self.timeline.selected_track = track_idx
            self.timeline.selected_index = len(self.timeline.tracks[track_idx]) - 1
            self.timeline.update()
            self.on_timeline_clip_selected(track_idx, len(self.timeline.tracks[track_idx]) - 1)
                
    @staticmethod
    def friendly_video_name(path):
        """把流水线产物文件名转成可读名称，便于在素材库中识别。

        clips/episode_1/panel_p_3.mp4 -> 第1集 · 分镜3
        output/episode_1_final.mp4    -> 第1集 · 成片
        其他路径回退为原文件名。
        """
        try:
            base = os.path.basename(path)
            stem, _ext = os.path.splitext(base)
            parent = os.path.basename(os.path.dirname(path))

            m_ep = re.match(r'^episode_(\d+)$', parent)
            ep_num = m_ep.group(1) if m_ep else None

            def _panel_label(pid):
                m = re.match(r'^(?:p_)?(\d+)$', pid or "")
                return f"分镜{m.group(1)}" if m else f"分镜{pid}"

            m_panel = re.match(r'^panel_(.+)$', stem)
            if m_panel and ep_num:
                return f"第{ep_num}集 · {_panel_label(m_panel.group(1))}"

            m_final = re.match(r'^episode_(\d+)_final$', stem)
            if m_final:
                return f"第{m_final.group(1)}集 · 成片"

            m_raw = re.match(r'^episode_(\d+)_raw$', stem)
            if m_raw:
                return f"第{m_raw.group(1)}集 · 拼接"

            return base
        except Exception:
            return os.path.basename(path)

    @staticmethod
    def _norm_clip_path(path):
        """素材路径归一化（Windows 盘符/路径大小写不敏感，避免同一文件被重复登记）。"""
        return os.path.normcase(os.path.abspath(path))

    def _is_clip_in_library(self, path):
        """素材库中是否已存在该文件（按归一化绝对路径判重）。"""
        try:
            key = self._norm_clip_path(path)
            return any(self._norm_clip_path(c.path) == key for c in self.clips)
        except Exception:
            return False

    def _collect_storyboard_durations(self):
        """读取分镜数据，返回 {视频绝对路径: 时长}，避免逐个探测（OpenCV 探测很慢）。"""
        result = {}
        if not self.project_dir:
            return result
        sb_dir = os.path.join(self.project_dir, "storyboards")
        if not os.path.isdir(sb_dir):
            return result
        for f in os.listdir(sb_dir):
            if not f.endswith(".json"):
                continue
            m_ep = re.match(r'^episode_(\d+)\.json$', f)
            ep_num = m_ep.group(1) if m_ep else None
            try:
                with open(os.path.join(sb_dir, f), "r", encoding="utf-8") as fp:
                    data = json.load(fp)
            except Exception:
                continue
            panels = data.get("panels") if isinstance(data, dict) else None
            if not isinstance(panels, list):
                continue
            for panel in panels:
                if not isinstance(panel, dict):
                    continue
                dur = panel.get("duration")
                try:
                    dur = float(dur) if dur else None
                except (TypeError, ValueError):
                    dur = None
                pid = panel.get("panel_id") or ""
                keys = []
                # 分镜里的 video_path 通常指向 raw_ 中间产物，这里同时登记成品路径
                if ep_num and pid:
                    keys.append(os.path.join(self.project_dir, "clips", f"episode_{ep_num}", f"panel_{pid}.mp4"))
                vp = (panel.get("video_path") or "").strip()
                if vp:
                    keys.append(vp)
                for k in keys:
                    result[os.path.abspath(k)] = dur
        return result

    def auto_sync_project_videos(self):
        """把项目里已生成的视频（含一键成片产物）自动补进素材库。

        一键成片只写文件、不写 editor_data.json，因此素材库需要主动扫描项目目录。
        raw_* 属于中间产物，不导入。
        """
        if not self.project_dir:
            return 0

        durations = self._collect_storyboard_durations()
        candidates = []

        clips_root = os.path.join(self.project_dir, "clips")
        if os.path.isdir(clips_root):
            for root, _dirs, files in os.walk(clips_root):
                for f in files:
                    if f.lower().startswith("raw_"):
                        continue
                    if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
                        p = os.path.join(root, f)
                        candidates.append((p, durations.get(os.path.abspath(p))))

        out_root = os.path.join(self.project_dir, "output")
        if os.path.isdir(out_root):
            for f in os.listdir(out_root):
                if f.lower().endswith(".mp4") and "_final" in f.lower():
                    candidates.append((os.path.join(out_root, f), None))

        added = 0
        self._suppress_editor_save = True
        try:
            for path, dur in sorted(candidates, key=lambda x: x[0]):
                if self._is_clip_in_library(path):
                    continue
                self.add_clip_to_library(path, duration=dur)
                added += 1
        finally:
            self._suppress_editor_save = False
        if added:
            print(f"[素材库] 自动同步项目视频 {added} 个")
            self.save_editor_data()
        return added

    def add_clip_to_library(self, path, duration=None, display_name=None):
        # 检查素材是否已存在（避免重复添加；路径按大小写不敏感判重）
        key = self._norm_clip_path(path)
        for existing_clip in self.clips:
            if self._norm_clip_path(existing_clip.path) == key:
                print(f"素材已存在，跳过添加: {path}")
                return
        
        # 根据文件类型判断素材类型
        ext = os.path.splitext(path)[1].lower()
        video_exts = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
        image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
        audio_exts = ['.wav', '.mp3', '.aac', '.flac', '.m4a']
        
        if ext in image_exts:
            # 图片默认时长5秒
            duration = 5.0
            icon = "🖼️"
            clip_type = "image"
        elif ext in audio_exts:
            # 音频获取实际时长（调用方可传入已知 duration，避免重复探测）
            if not duration:
                duration = VideoComposer().get_audio_duration(path)
            icon = "🔊"
            clip_type = "audio"
        else:
            # 视频获取实际时长（调用方可传入已知 duration，避免重复 OpenCV 探测）
            if not duration:
                duration = VideoComposer().get_audio_duration(path)
            icon = "🎬"
            clip_type = "video"
        
        clip = VideoClip(path, duration=duration)
        clip.clip_type = clip_type  # 设置素材类型
        self.clips.append(clip)
        
        item = QListWidgetItem(self.clip_list)
        item.setSizeHint(QSize(0, 50))
        item.setData(Qt.ItemDataRole.UserRole, len(self.clips) - 1)
        
        widget = QWidget()
        w_layout = QHBoxLayout(widget)
        w_layout.setContentsMargins(5, 5, 5, 5)
        
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 20px;")
        w_layout.addWidget(icon_lbl)
        
        # 显示可读名称（第N集 · 分镜M / 成片），悬停可看原始路径
        label_text = display_name or self.friendly_video_name(path)
        name_lbl = QLabel(label_text)
        name_lbl.setToolTip(path)
        name_lbl.setStyleSheet("color: " + _theme.color("text") + "; font-size: 12px;")
        w_layout.addWidget(name_lbl)
        
        w_layout.addStretch()
        
        dur_lbl = QLabel(f"{duration:.1f}s")
        dur_lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 11px;")
        w_layout.addWidget(dur_lbl)
        
        self.clip_list.setItemWidget(item, widget)
        
        # 保存编辑器数据（批量同步/加载时挂起，由调用方统一保存）
        if not getattr(self, "_suppress_editor_save", False):
            self.save_editor_data()
        
    def on_clip_delete_requested(self, row):
        """处理素材库删除请求"""
        if row < 0 or row >= len(self.clips):
            return
            
        # 获取要删除的素材信息
        clip = self.clips[row]
        clip_name = os.path.basename(clip.path)
        clip_path = clip.path
        
        # 检查素材是否正在时间线中使用
        used_tracks = []
        for track_idx, track in enumerate(self.timeline.tracks):
            for timeline_clip in track:
                if hasattr(timeline_clip, 'path') and timeline_clip.path == clip_path:
                    used_tracks.append(track_idx + 1)
                    break
        
        if used_tracks:
            track_names = ", ".join([f"轨道{t}" for t in used_tracks])
            QMessageBox.warning(
                self,
                "无法删除",
                f"素材 '{clip_name}' 正在时间线的 {track_names} 中使用，\n\n请先在时间线中删除该素材后再从素材库中删除。"
            )
            return
        
        # 确认删除
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除素材 '{clip_name}' 吗？\n\n注意：此操作只会从素材库中移除，不会删除原始文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        # 从列表中移除素材
        self.clips.pop(row)
        
        # 从列表控件中移除项目
        self.clip_list.takeItem(row)
        
        # 更新剩余项目的索引数据
        for i in range(self.clip_list.count()):
            item = self.clip_list.item(i)
            if item:
                item.setData(Qt.ItemDataRole.UserRole, i)
        
        # 保存编辑器数据
        self.save_editor_data()
        
    def add_to_timeline(self):
        current_row = self.clip_list.currentRow()
        if current_row < 0 or current_row >= len(self.clips):
            QMessageBox.warning(self, "提示", "请先在素材库中选择一个视频")
            return
            
        clip = self.clips[current_row]
        track_idx, clip_idx = self.timeline.add_clip_at_playhead(clip)
        self.timeline.selected_track = track_idx
        self.timeline.selected_index = clip_idx
        
    def on_clip_dropped_to_timeline(self, index):
        if 0 <= index < len(self.clips):
            clip = self.clips[index]
            track_idx, clip_idx = self.timeline.add_clip_at_playhead(clip)
            self.timeline.selected_track = track_idx
            self.timeline.selected_index = clip_idx
            # 保存编辑器数据
            self.save_editor_data()
        
    def on_clip_double_clicked(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)
        if 0 <= index < len(self.clips):
            clip = self.clips[index]
            self.play_video(clip.path)
            
    def on_timeline_clip_selected(self, track_index, clip_index):
        self.current_clip_index = clip_index
        self.current_selected_track = track_index
        
        if hasattr(self, 'edit_audio_btn'):
            if track_index >= 0 and track_index < len(self.timeline.tracks):
                clips = self.timeline.tracks[track_index]
                if clip_index >= 0 and clip_index < len(clips):
                    self.edit_audio_btn.setEnabled(True)
                    self._set_button_style(self.edit_audio_btn, "background-color: " + _theme.color("warning") + "; color: " + _theme.color("accent_text") + "; padding: 8px 15px; border-radius: 5px;")
                else:
                    self.edit_audio_btn.setEnabled(False)
                    self._set_button_style(self.edit_audio_btn, "background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 8px 15px; border-radius: 5px;")
            else:
                self.edit_audio_btn.setEnabled(False)
                self._set_button_style(self.edit_audio_btn, "background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; padding: 8px 15px; border-radius: 5px;")
        
        if track_index >= 0 and track_index < len(self.timeline.tracks):
            clips = self.timeline.tracks[track_index]
            if clip_index >= 0 and clip_index < len(clips):
                clip = clips[clip_index]
                info = f"轨道{track_index + 1} - 片段: {clip.name}"
                if clip.subtitles:
                    info += f" | 字幕: {len(clip.subtitles)}条"
                if clip.text_overlays:
                    info += f" | 文字: {len(clip.text_overlays)}个"
                if clip.audio_tracks:
                    info += f" | 配音: {len(clip.audio_tracks)}条"
                if hasattr(clip, 'effect') and clip.effect:
                    if clip.effect.filter_type != 'none':
                        filter_name = VideoEffect.FILTER_TYPES.get(clip.effect.filter_type, {}).get('name', clip.effect.filter_type)
                        info += f" | 特效: {filter_name}"
                    if clip.effect.speed != 1.0:
                        info += f" | 速度: {clip.effect.speed:.2f}x"
                self.info_label.setText(info)
                
                clip_type = getattr(clip, 'clip_type', 'video')
                
                video_ratio = self._get_video_aspect_ratio(clip)
                if self.media_player and self.media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    self.update_preview_at_time(self.timeline.playback_position)

    def _get_video_aspect_ratio(self, clip):
        """获取视频的宽高比"""
        default_ratio = 16.0 / 9.0
        
        if not clip or not hasattr(clip, 'path') or not clip.path:
            return default_ratio
        
        try:
            import cv2
            cap = cv2.VideoCapture(clip.path)
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
                if width > 0 and height > 0:
                    return width / height
        except Exception as e:
            print(f"DEBUG: Failed to get video aspect ratio: {e}")
        
        return default_ratio

    def on_timeline_clip_double_clicked(self, track_index, clip_index):
        """时间线上片段被双击"""
        if track_index >= 0 and track_index < len(self.timeline.tracks):
            clips = self.timeline.tracks[track_index]
            if clip_index >= 0 and clip_index < len(clips):
                clip = clips[clip_index]
                # 可以在这里添加双击编辑功能，比如打开片段详情对话框
                # 目前先选中该片段并更新预览
                self.on_timeline_clip_selected(track_index, clip_index)

    def add_track(self):
        track_count = len(self.timeline.tracks)
        track_name = f"轨道{track_count + 1}"
        self.timeline.add_track(track_name, "video", insert_at=track_count)
        
    def remove_track(self):
        """删除选中的轨道，如果有内容需要确认"""
        from PyQt6.QtWidgets import QMessageBox
        
        if len(self.timeline.tracks) <= 1:
            QMessageBox.warning(self, "提示", "至少需保留一个轨道")
            return
        
        # 获取选中的轨道（优先使用 selected_track_only，如果没有则使用 selected_track）
        track_idx = -1
        if self.timeline.selected_track_only >= 0 and self.timeline.selected_track_only < len(self.timeline.tracks):
            track_idx = self.timeline.selected_track_only
        elif self.timeline.selected_track >= 0 and self.timeline.selected_track < len(self.timeline.tracks):
            track_idx = self.timeline.selected_track
        
        if track_idx < 0:
            QMessageBox.warning(self, "提示", "请先选中要删除的轨道")
            return
        
        # 检查轨道是否有内容
        track = self.timeline.tracks[track_idx]
        track_info = self.timeline.track_types[track_idx] if track_idx < len(self.timeline.track_types) else {"name": f"轨道{track_idx + 1}"}
        track_name = track_info.get("name", f"轨道{track_idx + 1}")
        
        if len(track) > 0:
            # 轨道有内容，需要确认
            reply = QMessageBox.question(
                self,
                "确认删除",
                f'"{track_name}" 上有 {len(track)} 个视频片段，确定要删除吗？\n删除后内容将无法恢复。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # 删除轨道
        self.timeline.remove_track(track_idx)
        self.timeline.selected_track_only = -1
        self.timeline.selected_track = -1
        self.timeline.selected_index = -1
        self.timeline.update()
    
    def play_video(self, path):
        print(f"DEBUG: play_video called with path: {path}")
        try:
            if not hasattr(self, 'media_player') or self.media_player is None:
                print("DEBUG: media_player is None, returning")
                return
            if os.path.exists(path):
                print(f"DEBUG: Playing video: {path}")
                self.media_player.setSource(QUrl.fromLocalFile(path))
                self.media_player.play()
            else:
                print(f"DEBUG: File not found: {path}")
        except Exception as e:
            print(f"DEBUG: play_video error: {e}")
            import traceback
            traceback.print_exc()
            
    def toggle_play(self):
        print("DEBUG: toggle_play called")
        try:
            if not hasattr(self, 'media_player') or self.media_player is None:
                print("DEBUG: toggle_play - media_player is None")
                return
            
            is_timeline_playing = getattr(self, '_is_timeline_playing', False)
            print(f"DEBUG: is_timeline_playing = {is_timeline_playing}")
            
            # 修复：只要时间线正在播放，就应该暂停，不管media_player的状态
            # 这样可以避免播放完一个片段后，点击播放按钮从头开始的问题
            if is_timeline_playing:
                print("DEBUG: Pausing playback")
                self._is_timeline_playing = False
                if hasattr(self, '_timeline_timer') and self._timeline_timer.isActive():
                    self._timeline_timer.stop()
                self.media_player.pause()
                self.play_btn.setText("▶")
                self.play_btn.repaint()
            else:
                print("DEBUG: Starting playback")
                playhead_time = self.timeline.playback_position
                max_content_end = 0
                for track in self.timeline.tracks:
                    for clip in track:
                        clip_start = clip.start_time or 0
                        clip_duration = clip.duration or 0
                        clip_end = clip_start + clip_duration
                        if clip_end > max_content_end:
                            max_content_end = clip_end
                
                # 只有在播放头到达末尾时才重置到0
                if playhead_time >= max_content_end and max_content_end > 0:
                    print(f"DEBUG: Resetting playhead to 0")
                    self.timeline.set_playback_position(0)
                
                self._is_timeline_playing = True
                self.play_btn.setText("⏸")
                self.play_btn.repaint()
                
                # 修复：检查是否只是暂停后继续播放（同一位置），避免重新加载音频
                # 如果 media_player 有源且播放头位置与当前片段匹配，直接继续播放
                current_source = self.media_player.source().toLocalFile() if self.media_player and self.media_player.source() else ""
                clips_at_playhead = []
                for track_idx, track in enumerate(self.timeline.tracks):
                    for clip in track:
                        clip_start = clip.start_time or 0
                        clip_end = clip_start + (clip.duration or 0)
                        if clip_start <= playhead_time < clip_end:
                            clips_at_playhead.append((track_idx, clip))
                
                if clips_at_playhead:
                    first_clip = clips_at_playhead[0][1]
                    first_path = getattr(first_clip, 'path', "")
                    # 如果当前播放的片段与 media_player 的源相同，直接继续播放
                    if current_source and os.path.normpath(current_source) == os.path.normpath(first_path):
                        print("DEBUG: Resuming playback without reloading")
                        self.media_player.play()
                        self._start_timeline_playback_timer()
                    else:
                        # 需要重新加载音频（切换到了不同片段）
                        self.play_at_current_position()
                else:
                    self.play_at_current_position()
        except Exception as e:
            print(f"DEBUG: toggle_play error: {e}")
            import traceback
            traceback.print_exc()
    
    def play_at_current_position(self):
        print("DEBUG: play_at_current_position called")
        try:
            playhead_time = self.timeline.playback_position
            print(f"DEBUG: playhead_time = {playhead_time}")
            total_duration = self.timeline.get_total_duration()
            
            clips_at_playhead = []
            for track_idx, track in enumerate(self.timeline.tracks):
                for clip in track:
                    clip_start = clip.start_time or 0
                    clip_end = clip_start + (clip.duration or 0)
                    if clip_start <= playhead_time < clip_end:
                        clips_at_playhead.append((track_idx, clip))
            
            print(f"DEBUG: Found {len(clips_at_playhead)} clips at playhead")
            
            if not clips_at_playhead:
                print("DEBUG: No clips at playhead")
                self._current_playing_clip = None
                if self.media_player:
                    self.media_player.stop()
                    self.media_player.setSource(QUrl())
                self.video_label.clear()
                self.video_label.setText("无内容")
                # 修复：即使没有片段也要启动定时器，让播放头继续移动直到遇到片段或结束
                self._start_timeline_playback_timer()
                return
            
            clips_at_playhead.sort(key=lambda x: x[0])
            
            self._current_playing_clips = clips_at_playhead
            
            # 修复：设置当前播放的片段，用于音频切换检测
            first_clip = clips_at_playhead[0][1]
            self._current_playing_clip = first_clip
            
            first_path = getattr(first_clip, 'path', None)
            if first_path and os.path.exists(first_path):
                # 检查音频是否被静音或已分离
                audio_muted = getattr(first_clip, 'audio_muted', False)
                separate_audio = getattr(first_clip, 'separate_audio', False)
                
                if not audio_muted and not separate_audio:
                    clip_start = first_clip.start_time or 0
                    clip_offset = playhead_time - clip_start
                    self._play_audio_for_clip(first_path, clip_offset)
                else:
                    # 音频被静音或已分离，停止播放音频
                    if self.media_player:
                        self.media_player.stop()
                        self.media_player.setSource(QUrl())
            
            print(f"DEBUG: Calling _render_multi_track_preview")
            self._render_multi_track_preview(playhead_time)
            self._start_timeline_playback_timer()
        except Exception as e:
            print(f"DEBUG: play_at_current_position error: {e}")
            import traceback
            traceback.print_exc()
    
    def _play_audio_for_clip(self, video_path, start_offset=0):
        try:
            print(f"DEBUG: _play_audio_for_clip path={video_path}, offset={start_offset}")
            if self.media_player:
                # 修复：检查是否需要切换源
                current_source = self.media_player.source().toLocalFile() if self.media_player.source() else ""
                if os.path.normpath(current_source) == os.path.normpath(video_path):
                    # 同一个文件，只需要调整位置
                    print(f"DEBUG: Same source, seeking to {start_offset}")
                    self.media_player.setPosition(int(start_offset * 1000))
                    if self.media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                        self.media_player.play()
                else:
                    # 不同文件，需要切换源
                    print(f"DEBUG: Switching source from {current_source} to {video_path}")
                    self.media_player.stop()
                    # 保存待处理的跳转位置，在媒体加载完成后再设置
                    self._pending_seek_position = int(start_offset * 1000)
                    self.media_player.setSource(QUrl.fromLocalFile(video_path))
                    # 注意：不立即调用play()，让media_status_changed中的LoadedMedia处理播放
        except Exception as e:
            print(f"DEBUG: _play_audio_for_clip error: {e}")
    
    def _render_multi_track_preview(self, playhead_time):
        try:
            import cv2
            import numpy as np
            
            print(f"DEBUG: _render_multi_track_preview called with playhead_time={playhead_time}")
            
            canvas_size = self.video_widget.size()
            canvas_w = max(100, canvas_size.width())
            canvas_h = max(100, canvas_size.height())
            print(f"DEBUG: canvas size: {canvas_w}x{canvas_h}")
            
            if canvas_w <= 0 or canvas_h <= 0:
                print("DEBUG: Invalid canvas size")
                return
            
            canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
            
            for track_idx, clip in self._current_playing_clips:
                print(f"DEBUG: Processing clip on track {track_idx}")
                clip_start = clip.start_time or 0
                clip_offset = max(0, playhead_time - clip_start)
                
                path = getattr(clip, 'path', None)
                print(f"DEBUG: Clip path: {path}")
                if not path or not os.path.exists(path):
                    print(f"DEBUG: Path invalid or file not found")
                    continue
                
                # 修复：每次渲染时都创建新的 VideoCapture，避免重用导致的帧定位问题
                # 或者检查现有的 capture 是否仍然有效
                cap = None
                if path in self._video_captures:
                    cap = self._video_captures[path]
                    # 检查 capture 是否仍然打开
                    if not cap.isOpened():
                        print(f"DEBUG: Existing VideoCapture closed, recreating for {path}")
                        cap.release()
                        cap = cv2.VideoCapture(path)
                        self._video_captures[path] = cap
                else:
                    print(f"DEBUG: Creating new VideoCapture for {path}")
                    cap = cv2.VideoCapture(path)
                    self._video_captures[path] = cap
                
                # 检查 VideoCapture 是否成功打开
                if not cap.isOpened():
                    print(f"DEBUG: Failed to open video: {path}")
                    continue
                
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                frame_number = int(clip_offset * fps)
                
                # 确保帧号在有效范围内
                frame_number = max(0, min(frame_number, total_frames - 1))
                print(f"DEBUG: fps={fps}, total_frames={total_frames}, frame_number={frame_number}")
                
                # 修复：使用更准确的时间定位方式
                # 方法1：尝试使用帧号定位
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ret, frame = cap.read()
                
                # 方法2：如果帧号定位失败，尝试使用时间定位
                if not ret:
                    print(f"DEBUG: Frame seek failed, trying time-based seek")
                    cap.set(cv2.CAP_PROP_POS_MSEC, clip_offset * 1000)
                    ret, frame = cap.read()
                
                # 方法3：如果都失败，尝试顺序读取到目标帧
                if not ret:
                    print(f"DEBUG: Time-based seek failed, trying sequential read")
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    current_frame = 0
                    while current_frame < frame_number:
                        cap.grab()
                        current_frame += 1
                    ret, frame = cap.read()
                
                if not ret:
                    print(f"DEBUG: Failed to read frame after all attempts")
                    continue
                
                # 应用视频特效
                if hasattr(clip, 'effect') and clip.effect and clip.effect.filter_type != 'none':
                    frame = self._apply_effect_to_image(frame, clip.effect)
                
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                preview_x = getattr(clip, 'preview_x', 0.0)
                preview_y = getattr(clip, 'preview_y', 0.0)
                preview_width = getattr(clip, 'preview_width', 1.0)
                preview_height = getattr(clip, 'preview_height', 1.0)
                
                target_x = int(canvas_w * preview_x)
                target_y = int(canvas_h * preview_y)
                target_w = int(canvas_w * preview_width)
                target_h = int(canvas_h * preview_height)
                
                if target_w <= 0 or target_h <= 0:
                    continue
                
                frame_resized = cv2.resize(frame_rgb, (target_w, target_h))
                
                y_end = min(target_y + target_h, canvas_h)
                x_end = min(target_x + target_w, canvas_w)
                y_start = max(0, target_y)
                x_start = max(0, target_x)
                
                frame_y_start = y_start - target_y
                frame_x_start = x_start - target_x
                frame_y_end = frame_y_start + (y_end - y_start)
                frame_x_end = frame_x_start + (x_end - x_start)
                
                canvas[y_start:y_end, x_start:x_end] = frame_resized[frame_y_start:frame_y_end, frame_x_start:frame_x_end]
            
            print("DEBUG: Creating QImage from canvas")
            q_img = QImage(canvas.data, canvas_w, canvas_h, 3 * canvas_w, QImage.Format.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(q_img)
            label_size = self.video_label.size()
            if label_size.width() > 0 and label_size.height() > 0:
                scaled_pixmap = pixmap.scaled(label_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.video_label.setPixmap(scaled_pixmap)
            else:
                self.video_label.setPixmap(pixmap)
            # 修复：确保视频标签可见
            self.video_label.show()
            
            # 修复：确保字幕叠加层在最上层
            if hasattr(self, 'subtitle_overlay') and self.subtitle_overlay:
                self.subtitle_overlay.raise_()
                self.subtitle_overlay.show()
            
            selected_clip = None
            selected_track = getattr(self.timeline, 'selected_track', -1)
            selected_index = getattr(self.timeline, 'selected_index', -1)
            
            # 修复：只有当 _current_playing_clips 不为空时才检查选中状态
            if self._current_playing_clips:
                for track_idx, clip in self._current_playing_clips:
                    clip_idx = None
                    for i, c in enumerate(self.timeline.tracks[track_idx]):
                        if c == clip:
                            clip_idx = i
                            break
                    if track_idx == selected_track and clip_idx == selected_index:
                        selected_clip = clip
                        break
                
                if selected_clip:
                    self._draw_selection_overlay(selected_clip)
        except Exception as e:
            print(f"DEBUG: _render_multi_track_preview error: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_selection_overlay(self, clip):
        try:
            preview_x = getattr(clip, 'preview_x', 0.0)
            preview_y = getattr(clip, 'preview_y', 0.0)
            preview_width = getattr(clip, 'preview_width', 1.0)
            preview_height = getattr(clip, 'preview_height', 1.0)
            
            canvas_size = self.video_label.size()
            if canvas_size.width() <= 0 or canvas_size.height() <= 0:
                return
            
            overlay = QPixmap(canvas_size)
            overlay.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(overlay)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            rect_x = int(canvas_size.width() * preview_x)
            rect_y = int(canvas_size.height() * preview_y)
            rect_w = int(canvas_size.width() * preview_width)
            rect_h = int(canvas_size.height() * preview_height)
            
            painter.drawRect(rect_x, rect_y, rect_w, rect_h)
            
            handle_size = 10
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            
            corners = [
                (rect_x, rect_y),
                (rect_x + rect_w - handle_size, rect_y),
                (rect_x, rect_y + rect_h - handle_size),
                (rect_x + rect_w - handle_size, rect_y + rect_h - handle_size)
            ]
            
            for cx, cy in corners:
                painter.drawRect(cx, cy, handle_size, handle_size)
            
            painter.end()
            
            current_pixmap = self.video_label.pixmap()
            if current_pixmap:
                combined = QPixmap(canvas_size)
                combined.fill(Qt.GlobalColor.transparent)
                combined_painter = QPainter(combined)
                combined_painter.drawPixmap(0, 0, current_pixmap)
                combined_painter.drawPixmap(0, 0, overlay)
                combined_painter.end()
                self.video_label.setPixmap(combined)
        except Exception as e:
            print(f"DEBUG: _draw_selection_overlay error: {e}")
    
    def _show_image_in_preview(self, image_path, effect=None):
        """在预览窗口显示图片，支持特效"""
        try:
            if self.media_player:
                self.media_player.stop()
                self.media_player.setSource(QUrl())

            import cv2
            import numpy as np

            img = cv2.imread(image_path)
            if img is None:
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    self.video_label.setPixmap(pixmap)
                    self.video_label.show()
                else:
                    self.video_label.setText(f"无法加载图片: {image_path}")
                    self.video_label.show()
                return

            if effect and hasattr(effect, 'filter_type') and effect.filter_type != 'none':
                img = self._apply_effect_to_image(img, effect)

            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            height, width, channels = img_rgb.shape
            bytes_per_line = channels * width

            from PyQt6.QtGui import QImage
            q_image = QImage(img_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(q_image)

            if not pixmap.isNull():
                self.video_label.setPixmap(pixmap)
                self.video_label.show()
            else:
                self.video_label.setText(f"无法加载图片: {image_path}")
                self.video_label.show()
        except Exception as e:
            print(f"DEBUG: _show_image_in_preview error: {e}")
            try:
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    self.video_label.setPixmap(pixmap)
                    self.video_label.show()
                else:
                    self.video_label.setText(f"无法加载图片: {image_path}")
                    self.video_label.show()
            except Exception as e2:
                self.video_label.setText(f"图片显示错误: {e2}")
                self.video_label.show()

    def _apply_effect_to_image(self, img, effect):
        """应用特效到 OpenCV 图片"""
        import cv2
        import numpy as np

        result = img.copy()

        # 应用滤镜特效
        if effect.filter_type == 'grayscale':
            result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
        elif effect.filter_type == 'sepia':
            kernel = np.array([[0.393, 0.769, 0.189],
                               [0.349, 0.686, 0.168],
                               [0.272, 0.534, 0.131]])
            result = cv2.transform(result, kernel)
            result = np.clip(result, 0, 255).astype(np.uint8)
        elif effect.filter_type == 'blur':
            radius = effect.params.get('radius', 5)
            ksize = max(1, radius // 2) * 2 + 1
            result = cv2.GaussianBlur(result, (ksize, ksize), 0)
        elif effect.filter_type == 'sharpen':
            kernel = np.array([[-1, -1, -1],
                               [-1,  9, -1],
                               [-1, -1, -1]])
            result = cv2.filter2D(result, -1, kernel)
        elif effect.filter_type == 'invert':
            result = cv2.bitwise_not(result)
        elif effect.filter_type == 'mirror_h':
            result = cv2.flip(result, 1)
        elif effect.filter_type == 'mirror_v':
            result = cv2.flip(result, 0)
        elif effect.filter_type == 'rotate_90':
            result = cv2.rotate(result, cv2.ROTATE_90_CLOCKWISE)
        elif effect.filter_type == 'rotate_180':
            result = cv2.rotate(result, cv2.ROTATE_180)
        elif effect.filter_type == 'rotate_270':
            result = cv2.rotate(result, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif effect.filter_type == 'pixelate':
            size = effect.params.get('size', 8)
            h, w = result.shape[:2]
            small = cv2.resize(result, (w // size, h // size), interpolation=cv2.INTER_LINEAR)
            result = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        elif effect.filter_type == 'vignette':
            rows, cols = result.shape[:2]
            X_resultant_kernel = cv2.getGaussianKernel(cols, cols/2)
            Y_resultant_kernel = cv2.getGaussianKernel(rows, rows/2)
            kernel = Y_resultant_kernel * X_resultant_kernel.T
            mask = kernel / kernel.max()
            # 用浮点相乘后再 clip，避免 uint8 原地乘法产生溢出噪点
            result = np.clip(result.astype(np.float32) * mask[:, :, None], 0, 255).astype(np.uint8)
        elif effect.filter_type == 'vintage':
            # 怀旧效果：降低饱和度，增加暖色调
            result = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
            result[:, :, 1] = result[:, :, 1] * 0.6  # 降低饱和度
            result[:, :, 0] = (result[:, :, 0] + 10) % 180  # 增加暖色调
            result = np.clip(result, 0, 255).astype(np.uint8)
            result = cv2.cvtColor(result, cv2.COLOR_HSV2BGR)
            # 添加轻微褐色
            result = result * 0.9 + np.array([20, 40, 60], dtype=np.uint8)
            result = np.clip(result, 0, 255).astype(np.uint8)
        elif effect.filter_type == 'warm':
            # 暖色调
            result = result.astype(np.float32)
            result[:, :, 2] = np.clip(result[:, :, 2] * 1.1, 0, 255)  # 增加红色
            result[:, :, 0] = np.clip(result[:, :, 0] * 0.95, 0, 255)  # 减少蓝色
            result = result.astype(np.uint8)
        elif effect.filter_type == 'cool':
            # 冷色调
            result = result.astype(np.float32)
            result[:, :, 0] = np.clip(result[:, :, 0] * 1.1, 0, 255)  # 增加蓝色
            result[:, :, 2] = np.clip(result[:, :, 2] * 0.95, 0, 255)  # 减少红色
            result = result.astype(np.uint8)
        elif effect.filter_type == 'contrast':
            # 高对比度
            result = cv2.convertScaleAbs(result, alpha=1.5, beta=-30)
        elif effect.filter_type == 'bright':
            # 明亮效果
            result = cv2.convertScaleAbs(result, alpha=1.0, beta=40)
        elif effect.filter_type == 'dark':
            # 暗调效果
            result = cv2.convertScaleAbs(result, alpha=0.8, beta=-20)
        elif effect.filter_type == 'saturate':
            # 高饱和度
            hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.5, 0, 255)
            result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        elif effect.filter_type == 'desaturate':
            # 低饱和度
            hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 1] = hsv[:, :, 1] * 0.5
            result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        elif effect.filter_type == 'noise':
            # 添加噪点
            noise = np.random.normal(0, 15, result.shape).astype(np.int16)
            result = np.clip(result.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        # 应用亮度、对比度、饱和度、伽马调整
        if effect.brightness != 0 or effect.contrast != 1.0:
            # 亮度/对比度调整
            alpha = effect.contrast
            beta = effect.brightness * 255
            result = cv2.convertScaleAbs(result, alpha=alpha, beta=beta)

        if effect.saturation != 1.0:
            # 饱和度调整
            hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 1] = hsv[:, :, 1] * effect.saturation
            hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
            result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        if effect.gamma != 1.0:
            # 伽马校正
            inv_gamma = 1.0 / effect.gamma
            table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
            result = cv2.LUT(result, table)

        return result
    
    def _start_timeline_playback_timer(self):
        if hasattr(self, '_timeline_timer') and self._timeline_timer.isActive():
            return
        
        self._timeline_timer = QTimer(self)
        self._timeline_timer.timeout.connect(self._on_timeline_timer_tick)
        self._timeline_timer.start(100)
    
    def _on_timeline_timer_tick(self):
        try:
            print("DEBUG: _on_timeline_timer_tick called")
            if not getattr(self, '_is_timeline_playing', False):
                print("DEBUG: _is_timeline_playing is False, stopping timer")
                self._timeline_timer.stop()
                return
            
            current_time = self.timeline.playback_position
            new_time = current_time + 0.1
            print(f"DEBUG: current_time={current_time}, new_time={new_time}")
            
            max_content_end = 0
            for track in self.timeline.tracks:
                for clip in track:
                    clip_start = clip.start_time or 0
                    clip_duration = clip.duration or 0
                    clip_end = clip_start + clip_duration
                    if clip_end > max_content_end:
                        max_content_end = clip_end
            
            # 修复：检查 new_time 是否超出内容范围，而不是 current_time
            # 这样可以确保播放到最后一个片段结束才停止
            if new_time >= max_content_end:
                print(f"DEBUG: 播放结束 new_time={new_time}, max_content_end={max_content_end}")
                self._is_timeline_playing = False
                self._timeline_timer.stop()
                self._current_playing_clip = None
                self.timeline.set_playback_position(max_content_end)
                if self.media_player:
                    self.media_player.stop()
                if hasattr(self, 'play_btn'):
                    self.play_btn.setText("▶")
                    self.play_btn.repaint()
                return
            
            self.timeline.set_playback_position(new_time)
            self.update_subtitle_overlay(new_time)
            
            clips_at_playhead = []
            for track_idx, track in enumerate(self.timeline.tracks):
                for clip in track:
                    clip_start = clip.start_time or 0
                    clip_end = clip_start + (clip.duration or 0)
                    if clip_start <= new_time < clip_end:
                        clips_at_playhead.append((track_idx, clip))
            
            # 修复：无论是否有片段，都更新 _current_playing_clips 并渲染
            # 这样可以确保播放头移出片段时清空画面，进入片段时显示画面
            self._current_playing_clips = clips_at_playhead
            self._render_multi_track_preview(new_time)
            
            current_clip = None
            for track_idx, clip in clips_at_playhead:
                current_clip = clip
                break
            
            if current_clip != self._current_playing_clip:
                print("DEBUG: Clip changed, updating audio")
                self._current_playing_clip = current_clip
                if current_clip:
                    clip_path = getattr(current_clip, 'path', None)
                    if clip_path and os.path.exists(clip_path):
                        # 修复：检查音频是否被静音或已分离
                        audio_muted = getattr(current_clip, 'audio_muted', False)
                        separate_audio = getattr(current_clip, 'separate_audio', False)
                        
                        if not audio_muted and not separate_audio:
                            clip_start = current_clip.start_time or 0
                            clip_offset = new_time - clip_start
                            self._play_audio_for_clip(clip_path, clip_offset)
                        else:
                            # 音频被静音或已分离，停止播放音频
                            print("DEBUG: Audio muted or separated, stopping audio")
                            if self.media_player:
                                self.media_player.stop()
                                self.media_player.setSource(QUrl())
                else:
                    # 修复：当播放头移动到空白区域时，停止音频播放
                    print("DEBUG: No clip at playhead, stopping audio")
                    if self.media_player:
                        self.media_player.stop()
                        self.media_player.setSource(QUrl())
        except Exception as e:
            print(f"DEBUG: _on_timeline_timer_tick error: {e}")
            import traceback
            traceback.print_exc()
    
    def play_clips_at_playhead(self):
        self.play_at_current_position()
    
    def get_clip_at_playhead(self):
        playhead_time = self.timeline.playback_position
        for track in self.timeline.tracks:
            for clip in track:
                clip_start = clip.start_time or 0
                clip_end = clip_start + (clip.duration or 0)
                if clip_start <= playhead_time < clip_end:
                    return clip
        return None
            
    def stop_video(self):
        self._current_playing_clip = None
        self._is_timeline_playing = False
        if self.media_player:
            self.media_player.stop()
        if hasattr(self, '_timeline_timer') and self._timeline_timer.isActive():
            self._timeline_timer.stop()
        # 修复：清理视频捕获资源，避免内存泄漏和文件句柄耗尽
        self._release_video_captures()
        self.update_play_button(QMediaPlayer.PlaybackState.StoppedState)
    
    def _release_video_captures(self):
        """释放所有视频捕获资源"""
        if hasattr(self, '_video_captures'):
            for path, cap in self._video_captures.items():
                try:
                    cap.release()
                except Exception as e:
                    print(f"DEBUG: Error releasing video capture for {path}: {e}")
            self._video_captures.clear()
        
    def seek_video(self, position):
        if self.media_player:
            self.media_player.setPosition(position)
        
    def on_time_dragged(self, time_seconds):
        self.update_preview_at_time(time_seconds)
    
    def on_time_clicked(self, time_seconds):
        self.update_preview_at_time(time_seconds)
    
    def update_preview_at_time(self, time_seconds):
        if not hasattr(self, 'media_player') or self.media_player is None:
            return
        try:
            # 移除这个检查，确保在视频播放时也能更新预览覆盖层
            # if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            #     return
            
            playhead_time = time_seconds
            clips_at_playhead = []
            
            for track_idx, track in enumerate(self.timeline.tracks):
                for clip in track:
                    clip_start = clip.start_time or 0
                    clip_end = clip_start + (clip.duration or 0)
                    if clip_start <= playhead_time < clip_end:
                        clips_at_playhead.append((track_idx, clip))
            
            if not clips_at_playhead:
                if self.media_player:
                    self.media_player.stop()
                    self.media_player.setSource(QUrl())
                return
            
            selected_track = getattr(self.timeline, 'selected_track', -1)
            selected_index = getattr(self.timeline, 'selected_index', -1)
            selected_clip = None
            
            for track_idx, clip in clips_at_playhead:
                if track_idx == selected_track and clips_at_playhead.index((track_idx, clip)) == selected_index:
                    selected_clip = clip
                    break
            
            if not selected_clip:
                clips_at_playhead.sort(key=lambda x: x[0])
                selected_clip = clips_at_playhead[0][1]
            
            if selected_clip and hasattr(selected_clip, 'path'):
                clip_type = getattr(selected_clip, 'clip_type', 'video')
                self._current_playing_clip = selected_clip
                if clip_type == 'image':
                    effect = getattr(selected_clip, 'effect', None)
                    self._show_image_in_preview(selected_clip.path, effect)
                else:
                    self.video_label.hide()
                    current_source = self.media_player.source()
                    new_source = QUrl.fromLocalFile(selected_clip.path)
                    if current_source != new_source:
                        self.media_player.setSource(new_source)
                    clip_start = selected_clip.start_time or 0
                    clip_offset = max(0, playhead_time - clip_start)
                    target_pos = int(clip_offset * 1000)
                    self.media_player.setPosition(target_pos)
        except Exception as e:
            print(f"DEBUG: update_preview_at_time error: {e}")
        
    def on_zoom_changed(self, scale):
        self.zoom_label.setText(f"{int(scale * 100)}%")
        
    def update_position(self, position):
        try:
            if not hasattr(self, 'media_player') or self.media_player is None:
                return
            
            # 只有在时间线播放模式下才处理位置更新
            if not getattr(self, '_is_timeline_playing', False):
                return
            
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(position)
            self.position_slider.blockSignals(False)
            
            # 计算时间线上的绝对时间（考虑片段在时间线上的起始位置）
            clip = getattr(self, '_current_playing_clip', None)
            if clip:
                clip_start = clip.start_time or 0
                timeline_position = clip_start + (position / 1000.0)
            else:
                # 如果没有当前播放的片段，不更新时间指针（由timer控制）
                return
            
            self.timeline.set_playback_position(timeline_position)
            
            self.update_subtitle_overlay(timeline_position)
            
            duration = self.media_player.duration()
            current_time = QTime(0, 0).addMSecs(position)
            total_time = QTime(0, 0).addMSecs(duration)
            self.time_label.setText(f"{current_time.toString('mm:ss')} / {total_time.toString('mm:ss')}")
            
            # 检查片段播放范围，即使播放器停止也要检查（用于切换到下一个片段）
            self._check_clip_playback_range(timeline_position)
        except Exception as e:
            print(f"DEBUG: update_position error: {e}")
            
    def _check_clip_playback_range(self, current_time):
        if not getattr(self, '_is_timeline_playing', False):
            return
        
        clip = getattr(self, '_current_playing_clip', None)
        if clip is None:
            return
        
        clip_start = clip.start_time or 0
        clip_duration = clip.duration or 0
        clip_end = clip_start + clip_duration
        
        if current_time >= clip_end:
            # 当前片段已播放完毕，检查当前时间位置是否有其他片段
            clips_at_current = []
            for track_idx, track in enumerate(self.timeline.tracks):
                for c in track:
                    c_start = c.start_time or 0
                    c_end = c_start + (c.duration or 0)
                    if c_start <= current_time < c_end:
                        clips_at_current.append((track_idx, c))
            
            if clips_at_current:
                self.play_at_current_position()
            else:
                self._current_playing_clip = None
                if self.media_player:
                    self.media_player.stop()
                    self.media_player.setSource(QUrl())
                self.video_label.clear()
                self.video_label.setText("无内容")
            
    def update_subtitle_overlay(self, current_time):
        try:
            if not hasattr(self, 'subtitle_overlay') or self.subtitle_overlay is None:
                return

            current_subtitles = []
            current_text_overlays = []

            # 根据当前播放时间找到正在播放的片段
            if hasattr(self.timeline, 'tracks') and self.timeline.tracks and hasattr(self.timeline, 'track_types'):
                for track_idx, (track, track_info) in enumerate(zip(self.timeline.tracks, self.timeline.track_types)):
                    track_type = track_info.get("type", "video")

                    for clip in track:
                        if clip and hasattr(clip, 'start_time') and hasattr(clip, 'duration'):
                            clip_start = clip.start_time or 0
                            clip_end = clip_start + (clip.duration or 0)

                            # 检查当前时间是否在该片段的播放范围内
                            if clip_start <= current_time <= clip_end:
                                # 根据轨道类型处理
                                if track_type == "subtitle":
                                    # 字幕轨道 - 创建字幕项
                                    if hasattr(clip, 'text') and clip.text:
                                        subtitle = SubtitleItem(
                                            text=clip.text,
                                            start_time=clip_start,
                                            end_time=clip_end,
                                            style=getattr(clip, 'style', {})
                                        )
                                        current_subtitles.append(subtitle)
                                elif track_type == "text":
                                    # 文字轨道 - 创建文字叠加项
                                    if hasattr(clip, 'text') and clip.text:
                                        overlay = TextOverlay(
                                            text=clip.text,
                                            x=getattr(clip, 'x', 50),
                                            y=getattr(clip, 'y', 50),
                                            start_time=clip_start,
                                            end_time=clip_end,
                                            style=getattr(clip, 'style', {})
                                        )
                                        current_text_overlays.append(overlay)
                                else:
                                    # 视频/音频轨道 - 获取片段内的字幕和文字叠加
                                    subtitles = getattr(clip, 'subtitles', []) or []
                                    overlays = getattr(clip, 'text_overlays', []) or []
                                    current_subtitles.extend(subtitles)
                                    current_text_overlays.extend(overlays)

            # 设置当前时间，这是字幕显示的关键
            self.subtitle_overlay.set_current_time(current_time)
            self.subtitle_overlay.set_subtitles(current_subtitles)
            self.subtitle_overlay.set_text_overlays(current_text_overlays)

            # 调试信息
            if current_subtitles or current_text_overlays:
                print(f"DEBUG: 字幕数量={len(current_subtitles)}, 文字叠加数量={len(current_text_overlays)}, 当前时间={current_time}")

        except Exception as e:
            print(f"DEBUG: update_subtitle_overlay error: {e}")
        
    def update_duration(self, duration):
        try:
            if hasattr(self, 'position_slider'):
                self.position_slider.setRange(0, duration)
        except Exception as e:
            print(f"DEBUG: update_duration error: {e}")
            
    def update_play_button(self, state):
        try:
            if not hasattr(self, 'play_btn'):
                return
            # 如果时间线不在播放状态，强制显示播放按钮
            is_timeline_playing = getattr(self, '_is_timeline_playing', False)
            if state == QMediaPlayer.PlaybackState.PlayingState and is_timeline_playing:
                self.play_btn.setText("⏸")
            else:
                self.play_btn.setText("▶")
            # 强制刷新按钮显示
            self.play_btn.repaint()
        except Exception as e:
            print(f"DEBUG: update_play_button error: {e}")

    def force_update_play_button_to_stop(self):
        """强制将播放按钮更新为停止状态"""
        try:
            if hasattr(self, 'play_btn'):
                self.play_btn.setText("▶")
                self.play_btn.repaint()
                print("DEBUG: 播放按钮已强制更新为停止状态")
        except Exception as e:
            print(f"DEBUG: force_update_play_button_to_stop error: {e}")
            
    def add_subtitle(self):
        """添加字幕 - 自动创建字幕轨道"""
        # 查找或创建字幕轨道
        subtitle_track_idx = -1
        for i, track_info in enumerate(self.timeline.track_types):
            if track_info.get("type") == "subtitle":
                subtitle_track_idx = i
                break

        # 如果没有字幕轨道，创建一个
        if subtitle_track_idx == -1:
            subtitle_track_idx = len(self.timeline.tracks)
            self.timeline.add_track("字幕轨", "subtitle", insert_at=subtitle_track_idx)
            QMessageBox.information(self, "提示", "已自动创建字幕轨道")

        # 获取当前播放位置作为字幕开始时间
        start_time = self.timeline.playback_position

        dialog = SubtitleEditDialog(clip_duration=5.0, start_time=start_time, parent=self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.get_values()

            # 创建字幕片段
            subtitle_clip = VideoClip(None)
            subtitle_clip.name = values['text'][:10] + "..." if len(values['text']) > 10 else values['text']
            subtitle_clip.start_time = values['start_time']
            subtitle_clip.duration = values['end_time'] - values['start_time']
            subtitle_clip.clip_type = "subtitle"
            subtitle_clip.text = values['text']
            subtitle_clip.style = values['style']

            # 保存状态到历史记录（在修改前）
            self._save_state_to_history()
            
            # 添加到字幕轨道
            self.timeline.tracks[subtitle_track_idx].append(subtitle_clip)
            self.timeline.selected_track = subtitle_track_idx
            self.timeline.selected_index = len(self.timeline.tracks[subtitle_track_idx]) - 1
            self.timeline.update()

            # 更新预览
            self.on_timeline_clip_selected(subtitle_track_idx, len(self.timeline.tracks[subtitle_track_idx]) - 1)
            self.update_subtitle_overlay(self.timeline.playback_position)

            QMessageBox.information(self, "成功", f"已添加字幕: {values['text'][:20]}...")

    def add_text_overlay(self):
        """添加文字叠加 - 自动创建文字轨道"""
        # 查找或创建文字轨道
        text_track_idx = -1
        for i, track_info in enumerate(self.timeline.track_types):
            if track_info.get("type") == "text":
                text_track_idx = i
                break

        # 如果没有文字轨道，创建一个
        if text_track_idx == -1:
            text_track_idx = len(self.timeline.tracks)
            self.timeline.add_track("文字轨", "text", insert_at=text_track_idx)
            QMessageBox.information(self, "提示", "已自动创建文字轨道")

        # 获取当前播放位置作为文字开始时间
        start_time = self.timeline.playback_position

        dialog = TextOverlayDialog(clip_duration=5.0, start_time=start_time, parent=self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.get_values()

            # 创建文字片段
            text_clip = VideoClip(None)
            text_clip.name = values['text'][:10] + "..." if len(values['text']) > 10 else values['text']
            text_clip.start_time = values['start_time']
            text_clip.duration = values['end_time'] - values['start_time']
            text_clip.clip_type = "text"
            text_clip.text = values['text']
            text_clip.x = values['x']
            text_clip.y = values['y']
            text_clip.style = values['style']

            # 保存状态到历史记录（在修改前）
            self._save_state_to_history()
            
            # 添加到文字轨道
            self.timeline.tracks[text_track_idx].append(text_clip)
            self.timeline.selected_track = text_track_idx
            self.timeline.selected_index = len(self.timeline.tracks[text_track_idx]) - 1
            self.timeline.update()

            # 更新预览
            self.on_timeline_clip_selected(text_track_idx, len(self.timeline.tracks[text_track_idx]) - 1)
            self.update_subtitle_overlay(self.timeline.playback_position)

            QMessageBox.information(self, "成功", f"已添加文字: {values['text'][:20]}...")

    def add_audio(self):
        if (not hasattr(self.timeline, 'selected_track') or self.timeline.selected_track < 0 or
            not hasattr(self.timeline, 'selected_index') or self.timeline.selected_index < 0 or
            self.timeline.selected_track >= len(self.timeline.tracks) or
            self.timeline.selected_index >= len(self.timeline.tracks[self.timeline.selected_track])):
            QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择音频文件",
            "",
            "音频文件 (*.mp3 *.wav *.ogg *.aac *.m4a);;所有文件 (*.*)"
        )
        
        if file_path:
            clip = self.timeline.tracks[self.timeline.selected_track][self.timeline.selected_index]
            composer = VideoComposer()
            duration = composer.get_audio_duration(file_path)
            
            audio_track = AudioTrack(file_path)
            audio_track.duration = duration
            clip.audio_tracks.append(audio_track)
            self.timeline.update()
            if hasattr(self.timeline, 'selected_track') and hasattr(self.timeline, 'selected_index'):
                self.on_timeline_clip_selected(self.timeline.selected_track, self.timeline.selected_index)
    
    def separate_audio_from_clip(self):
        if (not hasattr(self.timeline, 'selected_track') or self.timeline.selected_track < 0 or
            not hasattr(self.timeline, 'selected_index') or self.timeline.selected_index < 0 or
            self.timeline.selected_track >= len(self.timeline.tracks) or
            self.timeline.selected_index >= len(self.timeline.tracks[self.timeline.selected_track])):
            QMessageBox.warning(self, "提示", "请先在时间线上选择一个视频片段")
            return
        
        clip = self.timeline.tracks[self.timeline.selected_track][self.timeline.selected_index]
        
        if not hasattr(clip, 'path') or not clip.path:
            QMessageBox.warning(self, "提示", "该片段没有视频文件")
            return
        
        if not os.path.exists(clip.path):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return
        
        try:
            composer = VideoComposer()
            
            temp_dir = os.path.join(os.path.dirname(clip.path), "temp_audio")
            os.makedirs(temp_dir, exist_ok=True)
            
            base_name = os.path.splitext(os.path.basename(clip.path))[0]
            audio_path = os.path.join(temp_dir, f"{base_name}_audio.wav")
            
            success = composer.extract_audio(clip.path, audio_path)
            
            if success and os.path.exists(audio_path):
                audio_track_idx = -1
                for i, track_info in enumerate(self.timeline.track_types):
                    if track_info["type"] == "audio":
                        audio_track_idx = i
                        break
                
                if audio_track_idx == -1:
                    audio_track_idx = len(self.timeline.tracks)
                    self.timeline.add_track("音频轨", "audio", insert_at=audio_track_idx)
                
                audio_clip = VideoClip(audio_path)
                audio_clip.name = f"{clip.name}_音频"
                audio_clip.duration = clip.duration or 0
                audio_clip.start_time = clip.start_time or 0
                audio_clip.audio_only = True
                audio_clip.volume = 1.0
                
                self.timeline.tracks[audio_track_idx].append(audio_clip)

                # 标记原视频片段的音频已分离
                clip.separate_audio = True
                clip.audio_muted = True
                # 清除波形缓存，下次绘制时将重新检查
                if hasattr(clip, '_audio_waveform'):
                    delattr(clip, '_audio_waveform')
                
                self.timeline.update()
                if hasattr(self.timeline, 'selected_track') and hasattr(self.timeline, 'selected_index'):
                    self.on_timeline_clip_selected(self.timeline.selected_track, self.timeline.selected_index)
                
                QMessageBox.information(self, "成功", f"已从视频中分离音频\n音频片段已添加到音频轨道\n音频文件: {audio_path}")
            else:
                QMessageBox.warning(self, "提示", "提取音频失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"分离音频时出错: {str(e)}")
            
    def open_tts(self):
        dialog = TTSDialog(self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.get_values()
            text = values['text']
            voice_id = values['voice_id']
            
            if not text:
                QMessageBox.warning(self, "提示", "请输入文字")
                return
                
            if (not hasattr(self.timeline, 'selected_track') or self.timeline.selected_track < 0 or
                not hasattr(self.timeline, 'selected_index') or self.timeline.selected_index < 0 or
                self.timeline.selected_track >= len(self.timeline.tracks) or
                self.timeline.selected_index >= len(self.timeline.tracks[self.timeline.selected_track])):
                QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
                return
            
            # 配音必须存到项目目录内：存系统 temp 会被系统清理，
            # 重新打开项目后 editor_data.json 引用的音频就失效了。
            import time as _time
            if self.project_dir:
                audio_dir = os.path.join(self.project_dir, "audio")
                os.makedirs(audio_dir, exist_ok=True)
                tts_path = os.path.join(audio_dir, f"tts_{int(_time.time() * 1000)}.wav")
            else:
                import tempfile
                fd, tts_path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)

            tts_client = TTSClient()
            result = tts_client.generate_audio(text, voice_id, tts_path)

            if result and os.path.exists(result) and os.path.getsize(result) > 0:
                clip = self.timeline.tracks[self.timeline.selected_track][self.timeline.selected_index]
                composer = VideoComposer()
                duration = composer.get_audio_duration(result)
                
                audio_track = AudioTrack(result, is_tts=True, text=text)
                audio_track.duration = duration
                clip.audio_tracks.append(audio_track)
                self.timeline.update()
                if hasattr(self.timeline, 'selected_track') and hasattr(self.timeline, 'selected_index'):
                    self.on_timeline_clip_selected(self.timeline.selected_track, self.timeline.selected_index)
                QMessageBox.information(self, "成功", "已生成并添加配音")
            else:
                QMessageBox.critical(self, "错误", "生成语音失败")
            
    def open_effects(self):
        if (not hasattr(self.timeline, 'selected_track') or self.timeline.selected_track < 0 or
            not hasattr(self.timeline, 'selected_index') or self.timeline.selected_index < 0 or
            self.timeline.selected_track >= len(self.timeline.tracks) or
            self.timeline.selected_index >= len(self.timeline.tracks[self.timeline.selected_track])):
            QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
            return
            
        clip = self.timeline.tracks[self.timeline.selected_track][self.timeline.selected_index]
        dialog = EffectDialog(clip.effect, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            clip.effect = dialog.get_effect()
            self.timeline.update()
            if hasattr(self.timeline, 'selected_track') and hasattr(self.timeline, 'selected_index'):
                self.on_timeline_clip_selected(self.timeline.selected_track, self.timeline.selected_index)
            # 立即更新预览以显示特效
            self.update_preview_at_time(self.timeline.playback_position)
            QMessageBox.information(self, "成功", "已应用视频特效")

    def open_transition_dialog(self):
        """打开转场效果设置对话框"""
        try:
            if (not hasattr(self.timeline, 'selected_track') or self.timeline.selected_track < 0 or
                not hasattr(self.timeline, 'selected_index') or self.timeline.selected_index < 0 or
                self.timeline.selected_track >= len(self.timeline.tracks) or
                self.timeline.selected_index >= len(self.timeline.tracks[self.timeline.selected_track])):
                QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
                return

            clip = self.timeline.tracks[self.timeline.selected_track][self.timeline.selected_index]

            # 检查 clip 是否有效
            if clip is None:
                QMessageBox.warning(self, "提示", "选中的片段无效")
                return

            dialog = TransitionEditDialog(clip, self)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                values = dialog.get_values()
                clip.transition = values['transition']
                clip.transition_duration = values['transition_duration']
                self.timeline.update()
                QMessageBox.information(self, "成功", "已应用转场效果")
        except Exception as e:
            print(f"DEBUG: open_transition_dialog error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"打开转场对话框时出错: {e}")

    def split_clip_at_playhead(self):
        playhead_time = self.timeline.playback_position
        clip_to_split = None
        clip_track_idx = -1
        clip_idx_in_track = -1
        
        # 修复：优先使用选中的片段
        if self.timeline.selected_track >= 0 and self.timeline.selected_index >= 0:
            selected_track = self.timeline.selected_track
            selected_index = self.timeline.selected_index
            if selected_track < len(self.timeline.tracks):
                track = self.timeline.tracks[selected_track]
                if selected_index < len(track):
                    clip = track[selected_index]
                    clip_start = clip.start_time or 0
                    clip_end = clip_start + (clip.duration or 0)
                    if clip_start < playhead_time < clip_end:
                        clip_to_split = clip
                        clip_track_idx = selected_track
                        clip_idx_in_track = selected_index
        
        # 如果没有选中的片段，再查找播放头所在的片段
        if not clip_to_split:
            for track_idx, track in enumerate(self.timeline.tracks):
                for clip_idx, clip in enumerate(track):
                    clip_start = clip.start_time or 0
                    clip_end = clip_start + (clip.duration or 0)
                    if clip_start < playhead_time < clip_end:
                        clip_to_split = clip
                        clip_track_idx = track_idx
                        clip_idx_in_track = clip_idx
                        break
                if clip_to_split:
                    break
        
        if not clip_to_split:
            QMessageBox.warning(self, "提示", "请先选中要切割的片段，并确保时间指针在片段内部")
            return
        
        clip_start = clip_to_split.start_time or 0
        split_point = playhead_time - clip_start
        
        if split_point <= 0.1 or split_point >= (clip_to_split.duration or 0) - 0.1:
            QMessageBox.warning(self, "提示", "切割点太接近片段边界，请移动时间指针到片段内部")
            return
        
        # 修复：第一个片段的 start_time 应该与原始片段相同
        first_clip = VideoClip(
            clip_to_split.path,
            name=clip_to_split.name + "_1",
            start_time=clip_start,
            duration=split_point
        )
        first_clip.transition = clip_to_split.transition
        first_clip.transition_duration = clip_to_split.transition_duration
        first_clip.subtitles = [s for s in clip_to_split.subtitles if hasattr(s, 'start_time') and s.start_time < split_point]
        first_clip.text_overlays = [t for t in clip_to_split.text_overlays if hasattr(t, 'start_time') and t.start_time < split_point]
        first_clip.audio_tracks = list(clip_to_split.audio_tracks)
        first_clip.effect = clip_to_split.effect
        
        # 修复：第二个片段的 start_time 应该与第一个片段的结束时间相同（连续）
        second_clip = VideoClip(
            clip_to_split.path,
            name=clip_to_split.name + "_2",
            start_time=playhead_time,
            duration=(clip_to_split.duration or 0) - split_point
        )
        second_clip.transition = None
        second_clip.transition_duration = clip_to_split.transition_duration
        second_clip.subtitles = []
        for sub in clip_to_split.subtitles:
            if hasattr(sub, 'start_time') and hasattr(sub, 'end_time'):
                if sub.start_time >= split_point:
                    new_sub = SubtitleItem(
                        sub.text,
                        sub.start_time - split_point,
                        sub.end_time - split_point
                    )
                    second_clip.subtitles.append(new_sub)
        second_clip.text_overlays = []
        for txt in clip_to_split.text_overlays:
            if hasattr(txt, 'start_time') and hasattr(txt, 'end_time'):
                if txt.start_time >= split_point:
                    new_txt = TextOverlay(
                        txt.text,
                        txt.x, txt.y,
                        start_time=txt.start_time - split_point,
                        end_time=txt.end_time - split_point if txt.end_time else None,
                        style=txt.style
                    )
                    second_clip.text_overlays.append(new_txt)
        second_clip.audio_tracks = list(clip_to_split.audio_tracks)
        second_clip.effect = clip_to_split.effect
        
        # 保存状态到历史记录（在修改前）
        self._save_state_to_history()
        
        del self.timeline.tracks[clip_track_idx][clip_idx_in_track]
        self.timeline.tracks[clip_track_idx].insert(clip_idx_in_track, second_clip)
        self.timeline.tracks[clip_track_idx].insert(clip_idx_in_track, first_clip)
        
        self.timeline.selected_track = clip_track_idx
        self.timeline.selected_index = clip_idx_in_track
        self.timeline.update()
        
        self.info_label.setText(f"已切割片段: {clip_to_split.name} -> {first_clip.name} + {second_clip.name}")
        
        # 保存编辑器数据
        self.save_editor_data()
    
    def edit_audio(self):
        if not hasattr(self, 'current_selected_track') or self.current_selected_track < 0:
            QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
            return
        
        track_idx = self.current_selected_track
        clip_idx = getattr(self, 'current_clip_index', -1)
        
        if track_idx < 0 or clip_idx < 0:
            QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
            return
        
        if track_idx >= len(self.timeline.tracks) or clip_idx >= len(self.timeline.tracks[track_idx]):
            QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
            return
        
        clip = self.timeline.tracks[track_idx][clip_idx]
        
        # 根据片段类型判断是音频还是视频
        clip_type = getattr(clip, 'clip_type', 'video')
        
        if clip_type == 'audio':
            dialog = AudioEditDialog(clip, self, is_track=True)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                values = dialog.get_values()
                clip.volume = values['volume']
                clip.muted = values['muted']
                clip.fade_in = values['fade_in']
                clip.fade_out = values['fade_out']
                clip.noise_reduction = values['noise_reduction']
                self.timeline.update()
                self.info_label.setText(f"已编辑音频: {clip.name}")
        elif hasattr(clip, 'audio_tracks') and clip.audio_tracks:
            audio_track = clip.audio_tracks[0]
            dialog = AudioEditDialog(audio_track, self, is_track=True)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                values = dialog.get_values()
                audio_track.volume = values['volume']
                audio_track.muted = values['muted']
                audio_track.fade_in = values['fade_in']
                audio_track.fade_out = values['fade_out']
                audio_track.noise_reduction = values['noise_reduction']
                self.timeline.update()
                self.info_label.setText(f"已编辑配音: {audio_track.name}")
        else:
            dialog = AudioEditDialog(clip, self, is_track=False)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                values = dialog.get_values()
                clip.audio_volume = values['audio_volume']
                clip.audio_muted = values['audio_muted']
                self.timeline.update()
                info = f"已编辑视频音频: {clip.name}"
                self.info_label.setText(info)
        
    def remove_selected_clip(self):
        if self.timeline.selected_track < 0 or self.timeline.selected_index < 0:
            QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
            return
        
        if (self.timeline.selected_track >= 0 and self.timeline.selected_track < len(self.timeline.tracks) and 
            self.timeline.selected_index >= 0 and self.timeline.selected_index < len(self.timeline.tracks[self.timeline.selected_track])):
            
            # 保存状态到历史记录（在修改前）
            self._save_state_to_history()
            
            del self.timeline.tracks[self.timeline.selected_track][self.timeline.selected_index]
            self.timeline.selected_track = -1
            self.timeline.selected_index = -1
            self.timeline.update()
            
            self._current_playing_clip = None
            if self.media_player:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            
            self.info_label.setText("选择片段后可添加字幕、文字和配音")
        
    def clear_timeline(self):
        has_clips = any(track for track in self.timeline.tracks)
        if has_clips:
            reply = QMessageBox.question(
                self, 
                "确认", 
                "确定要清空时间线吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                for track in self.timeline.tracks:
                    track.clear()
                self.current_clip_index = -1
                self.timeline.selected_track = -1
                self.timeline.selected_index = -1
                self.timeline.update()
                self.info_label.setText("选择片段后可添加字幕、文字和配音")
                # 保存编辑器数据
                self.save_editor_data()
                
    def remove_selected_clip(self):
        """删除选中的片段"""
        track_idx = self.timeline.selected_track
        clip_idx = self.timeline.selected_index
        
        if track_idx < 0 or track_idx >= len(self.timeline.tracks):
            return
        if clip_idx < 0 or clip_idx >= len(self.timeline.tracks[track_idx]):
            return
        
        # 获取片段信息用于显示
        clip = self.timeline.tracks[track_idx][clip_idx]
        clip_name = getattr(clip, 'name', '未命名片段')
        
        # 确认删除
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除片段 \"{clip_name}\" 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 删除片段
            self.timeline.tracks[track_idx].pop(clip_idx)
            # 重置选中状态
            self.timeline.selected_track = -1
            self.timeline.selected_index = -1
            self.timeline.update()
            self.info_label.setText("选择片段后可添加字幕、文字和配音")
            # 保存编辑器数据
            self.save_editor_data()
            
    def keyPressEvent(self, event):
        """键盘事件处理"""
        if event.key() == Qt.Key.Key_Delete:
            self.remove_selected_clip()
        elif event.key() == Qt.Key.Key_Z and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Z 撤销
            self.undo()
        elif event.key() == Qt.Key.Key_Y and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Y 恢复
            self.redo()
        else:
            super().keyPressEvent(event)
                
    def export_video(self):
        if not self.timeline.clips:
            QMessageBox.warning(self, "提示", "时间线上没有视频片段")
            return
            
        dialog = ExportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        config = dialog.get_config()
        
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存视频",
            os.path.join(self.project_dir or "", "output"),
            f"视频文件 (*.{config['format']})"
        )
        
        if not output_path:
            return
            
        if not output_path.endswith(f".{config['format']}"):
            output_path += f".{config['format']}"
            
        self.export_btn.setEnabled(False)
        self.export_btn.setText("导出中...")
        
        self.export_thread = ExportThread(self.timeline, output_path, config)
        self.export_thread.progress.connect(self.on_export_progress)
        self.export_thread.finished.connect(self.on_export_finished)
        self.export_thread.error.connect(self.on_export_error)
        self.export_thread.start()
        
    def on_export_progress(self, percent, message):
        self.info_label.setText(message)
        
    def on_export_finished(self, path):
        self.export_btn.setEnabled(True)
        self.export_btn.setText("导出视频")
        self.info_label.setText("选择片段后可添加字幕、文字和配音")
        QMessageBox.information(self, "完成", f"视频已导出至:\n{path}")
        
    def on_export_error(self, error):
        self.export_btn.setEnabled(True)
        self.export_btn.setText("导出视频")
        self.info_label.setText("选择片段后可添加字幕、文字和配音")
        QMessageBox.critical(self, "错误", f"导出失败:\n{error}")
    
    def open_video_enhance_dialog(self):
        """打开视频增强对话框"""
        try:
            # 获取当前选中的片段
            if self.timeline.selected_track < 0 or self.timeline.selected_index < 0:
                QMessageBox.warning(self, "提示", "请先在时间线上选择一个视频片段")
                return
            
            track_idx = self.timeline.selected_track
            clip_idx = self.timeline.selected_index
            
            if track_idx >= len(self.timeline.tracks):
                QMessageBox.warning(self, "提示", "选中的轨道无效")
                return
            
            track = self.timeline.tracks[track_idx]
            if clip_idx >= len(track):
                QMessageBox.warning(self, "提示", "选中的片段无效")
                return
            
            clip = track[clip_idx]
            video_path = getattr(clip, 'path', '')
            
            if not video_path:
                QMessageBox.warning(self, "提示", "选中的片段没有视频文件")
                return
            
            if not os.path.exists(video_path):
                QMessageBox.warning(self, "提示", f"视频文件不存在: {video_path}")
                return
            
            # 检查是否是视频类型
            clip_type = getattr(clip, 'clip_type', 'video')
            if clip_type not in ['video', '']:
                QMessageBox.warning(self, "提示", "只能对视频片段进行增强")
                return
            
            dialog = VideoEnhanceDialog(video_path, self)
            dialog.exec()
            
        except Exception as e:
            print(f"Error opening video enhance dialog: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"打开视频增强对话框失败:\n{str(e)}")
        
    def import_project_videos(self):
        if not self.project_dir:
            QMessageBox.warning(self, "提示", "请先在项目管理中打开一个项目")
            return
            
        clips_dir = os.path.join(self.project_dir, "clips")
        if not os.path.exists(clips_dir):
            QMessageBox.warning(self, "提示", "项目中没有找到clips目录")
            return
            
        # 递归扫描：片段位于 clips/episode_N/ 子目录；raw_* 为中间产物不导入
        video_files = []
        for root, _dirs, files in os.walk(clips_dir):
            for f in files:
                if f.lower().startswith("raw_"):
                    continue
                if f.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
                    video_files.append(os.path.join(root, f))
                
        if not video_files:
            QMessageBox.warning(self, "提示", "项目中没有找到视频文件")
            return
            
        reply = QMessageBox.question(
            self,
            "导入项目视频",
            f"找到 {len(video_files)} 个视频文件，是否全部导入？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            durations = self._collect_storyboard_durations()
            added = 0
            for video_file in sorted(video_files):
                if self._is_clip_in_library(video_file):
                    continue
                self.add_clip_to_library(video_file, duration=durations.get(os.path.abspath(video_file)))
                added += 1
            QMessageBox.information(self, "成功", f"已导入 {added} 个视频")
            
    def import_subtitle_file(self):
        if self.current_clip_index < 0 or self.current_clip_index >= len(self.timeline.clips):
            QMessageBox.warning(self, "提示", "请先在时间线上选择一个片段")
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择字幕文件",
            "",
            "字幕文件 (*.srt *.ass *.vtt);;所有文件 (*.*)"
        )
        
        if not file_path:
            return
            
        clip = self.timeline.clips[self.current_clip_index]
        
        try:
            subtitles = self.parse_subtitle_file(file_path)
            if subtitles:
                clip.subtitles.extend(subtitles)
                self.timeline.update()
                self.on_timeline_clip_selected(self.current_clip_index)
                QMessageBox.information(self, "成功", f"已导入 {len(subtitles)} 条字幕")
            else:
                QMessageBox.warning(self, "提示", "未能解析字幕文件")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入字幕失败: {str(e)}")
            
    def parse_subtitle_file(self, file_path):
        subtitles = []
        ext = os.path.splitext(file_path)[1].lower()
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if ext == '.srt':
            subtitles = self.parse_srt(content)
        elif ext == '.ass':
            subtitles = self.parse_ass(content)
        elif ext == '.vtt':
            subtitles = self.parse_vtt(content)
            
        return subtitles
        
    def parse_srt(self, content):
        subtitles = []
        blocks = content.strip().split('\n\n')
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 3:
                try:
                    time_line = lines[1]
                    if ' --> ' in time_line:
                        start_str, end_str = time_line.split(' --> ')
                        start_time = self.parse_srt_time(start_str)
                        end_time = self.parse_srt_time(end_str)
                        text = '\n'.join(lines[2:])
                        
                        subtitles.append(SubtitleItem(text, start_time, end_time))
                except Exception as e:
                    print(f"Error parsing SRT block: {e}")
                    continue
                    
        return subtitles
        
    def parse_srt_time(self, time_str):
        parts = time_str.strip().replace(',', '.').split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
        
    def parse_ass(self, content):
        subtitles = []
        lines = content.split('\n')
        
        for line in lines:
            if line.startswith('Dialogue:'):
                try:
                    parts = line.split(',', 9)
                    if len(parts) >= 10:
                        start_time = self.parse_ass_time(parts[1])
                        end_time = self.parse_ass_time(parts[2])
                        text = parts[9].replace('\\N', '\n').replace('\\n', '\n')
                        text = text.replace('{\\', '').split('}')[1] if '}' in text else text
                        
                        subtitles.append(SubtitleItem(text, start_time, end_time))
                except Exception as e:
                    print(f"Error parsing ASS line: {e}")
                    continue
                    
        return subtitles
        
    def parse_ass_time(self, time_str):
        parts = time_str.strip().split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
        
    def parse_vtt(self, content):
        subtitles = []
        lines = content.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if ' --> ' in line:
                try:
                    time_line = line
                    start_str, end_str = time_line.split(' --> ')
                    start_time = self.parse_vtt_time(start_str)
                    end_time = self.parse_vtt_time(end_str)
                    
                    text_lines = []
                    i += 1
                    while i < len(lines) and lines[i].strip():
                        text_lines.append(lines[i].strip())
                        i += 1
                        
                    text = '\n'.join(text_lines)
                    subtitles.append(SubtitleItem(text, start_time, end_time))
                except Exception as e:
                    print(f"Error parsing VTT: {e}")
            i += 1
            
        return subtitles
        
    def parse_vtt_time(self, time_str):
        time_str = time_str.strip()
        if time_str.startswith('00:'):
            time_str = time_str[3:]
            
        parts = time_str.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        return 0
        
    def generate_subtitle_from_script(self):
        if not self.project_dir:
            QMessageBox.warning(self, "提示", "请先在项目管理中打开一个项目")
            return
            
        scripts_dir = os.path.join(self.project_dir, "scripts")
        if not os.path.exists(scripts_dir):
            QMessageBox.warning(self, "提示", "项目中没有找到scripts目录")
            return
            
        script_files = [f for f in os.listdir(scripts_dir) if f.endswith('.json')]
        if not script_files:
            QMessageBox.warning(self, "提示", "项目中没有找到剧本文件")
            return
            
        from core.script.script_model import Script
        
        items = []
        for f in script_files:
            items.append(f)
            
        from PyQt6.QtWidgets import QInputDialog
        script_name, ok = QInputDialog.getItem(
            self,
            "选择剧本",
            "选择要生成字幕的剧本:",
            items,
            0,
            False
        )
        
        if not ok or not script_name:
            return
            
        script_path = os.path.join(scripts_dir, script_name)
        
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                script = Script.from_json(f.read())
                
            if not self.timeline.clips:
                QMessageBox.warning(self, "提示", "时间线上没有视频片段")
                return
                
            reply = QMessageBox.question(
                self,
                "生成字幕",
                f"将根据剧本 '{script.title}' 为时间线上的片段生成字幕，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
                
            current_time = 0
            for i, clip in enumerate(self.timeline.clips):
                clip_duration = clip.duration or 5
                
                if i < len(script.scenes):
                    scene = script.scenes[i]
                    if scene.dialogue:
                        subtitle = SubtitleItem(
                            scene.dialogue,
                            current_time,
                            current_time + clip_duration
                        )
                        clip.subtitles.append(subtitle)
                        
                current_time += clip_duration
                
            self.timeline.update()
            QMessageBox.information(self, "成功", "已根据剧本生成字幕")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"生成字幕失败: {str(e)}")
        
    def data_fingerprint(self):
        """主窗口 Tab 切换指纹：editor_data.json 未变时跳过重载（避免逐片 OpenCV 探测）。"""
        from ui.utils import dir_signature
        if not self.project_dir:
            return None
        return dir_signature(os.path.join(self.project_dir, "editor_data.json"))

    def load_existing_data(self):
        if self.project_dir and hasattr(self, 'storyboard_panel') and self.storyboard_panel:
            self.storyboard_panel.set_project_dir(self.project_dir)
        
        # 加载编辑器数据（素材库和时间线）
        self.load_editor_data()

        # 一键成片只落盘视频产物、不写 editor_data.json，
        # 这里主动扫描项目目录，把已生成的视频补进素材库
        self.auto_sync_project_videos()
    
    def load_editor_data(self):
        """加载编辑器数据（素材库和时间线）"""
        if not self.project_dir:
            return
        
        editor_data_path = os.path.join(self.project_dir, "editor_data.json")
        if not os.path.exists(editor_data_path):
            return
        
        try:
            with open(editor_data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 加载素材库（复用 JSON 中已保存的 duration，避免逐个 OpenCV 探测）
            # 此时时间线尚未恢复，挂起自动保存，避免把空时间线写回磁盘覆盖原数据
            self._suppress_editor_save = True
            try:
                clips_data = data.get("clips", [])
                clips_before = len(self.clips)
                for clip_data in clips_data:
                    try:
                        clip = VideoClip.from_dict(clip_data)
                        self.add_clip_to_library(clip.path, duration=clip.duration)
                    except Exception as e:
                        print(f"Error loading clip: {e}")
                # 统计被跳过的重复条目（历史数据里同一文件可能存在 E:\ 与 e:\ 两份）
                self._loaded_dup_clips = max(0, len(clips_data) - (len(self.clips) - clips_before))
            finally:
                self._suppress_editor_save = False
            
            # 加载时间线
            timeline_data = data.get("timeline", {})
            tracks_data = timeline_data.get("tracks", [])
            track_types_data = timeline_data.get("track_types", [])
            
            # 清空现有时间线
            self.timeline.tracks = []
            self.timeline.track_types = []
            
            for track_idx, track_data in enumerate(tracks_data):
                # 获取轨道类型信息
                track_type = "video"
                track_name = f"轨道{track_idx + 1}"
                track_locked = False
                
                if track_idx < len(track_types_data):
                    track_type = track_types_data[track_idx].get('type', 'video')
                    track_name = track_types_data[track_idx].get('name', f"轨道{track_idx + 1}")
                    track_locked = track_types_data[track_idx].get('locked', False)
                
                # 添加轨道
                self.timeline.add_track(track_name, track_type, insert_at=track_idx)
                self.timeline.track_types[track_idx]['locked'] = track_locked
                
                for clip_data in track_data:
                    try:
                        clip = VideoClip.from_dict(clip_data)
                        self.timeline.tracks[track_idx].append(clip)
                    except Exception as e:
                        print(f"Error loading timeline clip: {e}")
            
            # 更新时间线显示
            self.timeline.update()
            
            # 保存初始状态到历史记录
            self._save_state_to_history()
            
            print(f"Loaded editor data: {len(clips_data)} clips, {len(tracks_data)} tracks")

            # 历史数据中的重复素材已在上面的加载过程中被跳过，这里回写一次清理磁盘
            if getattr(self, "_loaded_dup_clips", 0) > 0:
                print(f"[素材库] 清理重复素材 {self._loaded_dup_clips} 条")
                self.save_editor_data()
                self._loaded_dup_clips = 0
            
        except Exception as e:
            print(f"Error loading editor data: {e}")
            import traceback
            traceback.print_exc()
    
    def save_editor_data(self):
        """保存编辑器数据（素材库和时间线）"""
        if not self.project_dir:
            return
        
        try:
            # 保存素材库
            clips_data = []
            for clip in self.clips:
                try:
                    clips_data.append(clip.to_dict())
                except Exception as e:
                    print(f"Error saving clip: {e}")
            
            # 保存时间线
            tracks_data = []
            for track in self.timeline.tracks:
                track_data = []
                for clip in track:
                    try:
                        track_data.append(clip.to_dict())
                    except Exception as e:
                        print(f"Error saving timeline clip: {e}")
                tracks_data.append(track_data)
            
            # 保存轨道类型信息
            track_types_data = []
            for track_info in self.timeline.track_types:
                track_types_data.append({
                    'name': track_info.get('name', ''),
                    'type': track_info.get('type', 'video'),
                    'locked': track_info.get('locked', False)
                })
            
            data = {
                "clips": clips_data,
                "timeline": {
                    "tracks": tracks_data,
                    "track_types": track_types_data
                }
            }
            
            editor_data_path = os.path.join(self.project_dir, "editor_data.json")
            # 原子写，防止保存中途崩溃导致 editor_data.json 截断、时间线数据全丢
            atomic_write_json(editor_data_path, data, indent=4, ensure_ascii=False)

            print(f"Saved editor data: {len(clips_data)} clips, {len(tracks_data)} tracks")
            
        except Exception as e:
            print(f"Error saving editor data: {e}")
            import traceback
            traceback.print_exc()
    
    def _save_state_to_history(self):
        """保存当前状态到历史记录"""
        try:
            # 保存时间线状态
            tracks_data = []
            for track in self.timeline.tracks:
                track_data = []
                for clip in track:
                    try:
                        track_data.append(clip.to_dict())
                    except Exception as e:
                        print(f"Error saving timeline clip to history: {e}")
                tracks_data.append(track_data)
            
            # 保存轨道类型信息
            track_types_data = []
            for track_info in self.timeline.track_types:
                track_types_data.append({
                    'name': track_info.get('name', ''),
                    'type': track_info.get('type', 'video'),
                    'locked': track_info.get('locked', False)
                })
            
            state = {
                'tracks': tracks_data,
                'track_types': track_types_data
            }
            
            # 删除当前索引之后的历史记录（当用户执行新操作时）
            if self._history_index < len(self._history) - 1:
                self._history = self._history[:self._history_index + 1]
            
            # 添加新状态
            self._history.append(state)
            
            # 限制历史记录数量
            if len(self._history) > self._max_history:
                self._history.pop(0)
            else:
                self._history_index += 1
            
            # 更新撤销/恢复按钮状态
            self._update_undo_redo_buttons()
            
        except Exception as e:
            print(f"Error saving state to history: {e}")
            import traceback
            traceback.print_exc()
    
    def undo(self):
        """撤销操作"""
        try:
            if self._history_index > 0:
                self._history_index -= 1
                state = self._history[self._history_index]
                self._restore_state(state)
                self._update_undo_redo_buttons()
                print(f"Undo: restored to state {self._history_index}")
            else:
                print("Undo: no more history")
        except Exception as e:
            print(f"Error during undo: {e}")
            import traceback
            traceback.print_exc()
    
    def redo(self):
        """恢复操作"""
        try:
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                state = self._history[self._history_index]
                self._restore_state(state)
                self._update_undo_redo_buttons()
                print(f"Redo: restored to state {self._history_index}")
            else:
                print("Redo: no more future states")
        except Exception as e:
            print(f"Error during redo: {e}")
            import traceback
            traceback.print_exc()
    
    def _restore_state(self, state):
        """从历史记录恢复状态"""
        try:
            # 恢复轨道类型
            self.timeline.track_types = []
            for track_type_data in state.get('track_types', []):
                self.timeline.track_types.append({
                    'name': track_type_data.get('name', ''),
                    'type': track_type_data.get('type', 'video'),
                    'locked': track_type_data.get('locked', False)
                })
            
            # 恢复轨道和片段
            self.timeline.tracks = []
            for track_data in state.get('tracks', []):
                track = []
                for clip_data in track_data:
                    try:
                        clip = VideoClip.from_dict(clip_data)
                        track.append(clip)
                    except Exception as e:
                        print(f"Error restoring clip from history: {e}")
                self.timeline.tracks.append(track)
            
            # 清除选中状态
            self.timeline.selected_track = -1
            self.timeline.selected_index = -1
            self.timeline.selected_track_only = -1
            
            # 更新显示
            self.timeline.update()
            
            # 保存到文件
            self.save_editor_data()
            
        except Exception as e:
            print(f"Error restoring state: {e}")
            import traceback
            traceback.print_exc()
    
    def _update_undo_redo_buttons(self):
        """更新撤销/恢复按钮状态"""
        if hasattr(self, 'undo_btn'):
            self.undo_btn.setEnabled(self._history_index > 0)
        if hasattr(self, 'redo_btn'):
            self.redo_btn.setEnabled(self._history_index < len(self._history) - 1)
    
    def _on_edit_started(self):
        """编辑开始（拖拽/调整大小）时保存状态"""
        # 保存当前状态到历史记录
        self._save_state_to_history()
    
    def _on_edit_finished(self):
        """编辑结束（拖拽/调整大小完成）时保存状态"""
        # 保存最终状态到历史记录
        self._save_state_to_history()
        # 保存到文件
        self.save_editor_data()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 更新字幕叠加层大小
        if hasattr(self, 'subtitle_overlay') and self.subtitle_overlay and hasattr(self, 'video_container'):
            self.subtitle_overlay.setGeometry(self.video_container.rect())
            self.subtitle_overlay.raise_()  # 确保字幕叠加层在最上层
        # 更新视频标签大小
        if hasattr(self, 'video_label') and self.video_label and hasattr(self, 'video_container'):
            self.video_label.setGeometry(self.video_container.rect())
