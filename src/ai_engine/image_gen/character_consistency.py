# -*- coding: utf-8 -*-
"""角色一致性校验：基于图片基本属性（尺寸/宽高比/平均色）的简单相似度告警。

不依赖外部模型，仅用 Pillow 做轻量级图像特征比对，用于生成图片后快速告警。
若需要更精确的 CLIP/InsightFace 比对，可扩展 extract_features 接入外部模型。
"""
import os
from dataclasses import dataclass


@dataclass
class ConsistencyResult:
    """一致性校验结果。"""
    score: float          # 0.0 ~ 1.0
    is_consistent: bool  # score >= threshold
    warning: str          # 告警信息，一致时为空


class CharacterConsistency:
    """角色一致性检查器：用图像基本属性做粗略相似度评估。"""

    def __init__(self, threshold: float = 0.55):
        self.threshold = threshold

    def extract_features(self, image_path):
        """
        从图片提取基本特征：宽、高、宽高比、平均 RGB。
        返回 dict 或 None（文件不存在/无法读取时）。
        """
        if not image_path or not os.path.exists(image_path):
            return None
        try:
            from PIL import Image
            img = Image.open(image_path).convert("RGB")
            w, h = img.size
            # 缩小到 32x32 计算平均色，降低开销
            small = img.resize((32, 32))
            pixels = list(small.getdata())
            avg_r = sum(p[0] for p in pixels) // len(pixels)
            avg_g = sum(p[1] for p in pixels) // len(pixels)
            avg_b = sum(p[2] for p in pixels) // len(pixels)
            return {
                "width": w,
                "height": h,
                "aspect_ratio": w / h if h > 0 else 0,
                "avg_r": avg_r,
                "avg_g": avg_g,
                "avg_b": avg_b,
            }
        except Exception as e:
            print(f"[CharacterConsistency] extract_features error: {e}")
            return None

    def validate_consistency(self, generated_image_path, reference_features):
        """
        检查生成的图片是否与参考特征匹配。
        参数:
            generated_image_path: 生成图片路径
            reference_features: extract_features 返回的 dict，或直接传参考图路径
        返回:
            ConsistencyResult
        """
        gen_feat = self.extract_features(generated_image_path)

        # 如果 reference_features 是字符串（路径），先提取
        if isinstance(reference_features, str):
            ref_feat = self.extract_features(reference_features)
        else:
            ref_feat = reference_features

        if not gen_feat or not ref_feat:
            return ConsistencyResult(score=0.0, is_consistent=False,
                                     warning="无法提取图片特征，可能文件不存在或格式不支持")

        # 1. 宽高比相似度（权重 40%）
        ar_diff = abs(gen_feat["aspect_ratio"] - ref_feat["aspect_ratio"])
        ar_score = max(0, 1 - ar_diff / 0.5)  # 差 0.5 以上记 0 分

        # 2. 平均色相似度（权重 60%）
        color_diff = (abs(gen_feat["avg_r"] - ref_feat["avg_r"]) +
                       abs(gen_feat["avg_g"] - ref_feat["avg_g"]) +
                       abs(gen_feat["avg_b"] - ref_feat["avg_b"])) / 3
        color_score = max(0, 1 - color_diff / 128)  # 差 128 以上记 0 分

        score = ar_score * 0.4 + color_score * 0.6
        is_consistent = score >= self.threshold

        if is_consistent:
            warning = ""
        else:
            warning = (f"角色一致性告警：相似度 {score:.0%}（阈值 {self.threshold:.0%}）。"
                       f"宽高比差异 {ar_diff:.2f}，色差 {color_diff:.0f}。"
                       "建议检查角色参考图或调整提示词。")

        return ConsistencyResult(score=score, is_consistent=is_consistent, warning=warning)

    def check_panel_consistency(self, panel):
        """
        校验单个 panel 的生成图片与参考图的一致性。
        返回 ConsistencyResult；如果 panel 无参考图或生成图，返回 None。
        """
        gen_path = getattr(panel, "image_path", "")
        ref_path = getattr(panel, "reference_image_path", "")

        if not gen_path or not os.path.exists(gen_path):
            return None
        if not ref_path or not os.path.exists(ref_path):
            return None

        return self.validate_consistency(gen_path, ref_path)

    def train_lora(self, character_id, image_paths):
        """
        训练 LoRA 模型（占位，当前未实现）。
        """
        print(f"[CharacterConsistency] LoRA training not implemented for {character_id}")
        return None
