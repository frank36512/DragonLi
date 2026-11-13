"""
角色1拖4图片生成器
生成包含5个角度的5宫格图片：
- 左侧：正面大图（占据整个高度）
- 右侧：4张小图，每行2张（侧面、背面、3/4侧面、特写）
"""
import os
from typing import List, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont


class CharacterGridGenerator:
    """角色5宫格图片生成器"""
    
    # 五宫格分视角定义：字段名 → (视角提示词前缀, 宫格位置)
    # 位置: left=左列整高, tl/tr/bl/br=右列 2×2
    GRID_VIEWS = [
        ("front_view", "front view, facing camera directly, full body from head to toe", "left"),
        ("right_side_view", "right side view, profile view from right side, full body", "tl"),
        ("back_view", "back view, seen from behind, rear view, full body", "tr"),
        ("three_quarter_view", "three-quarter view, 45 degree angle between front and side, full body", "bl"),
        ("close_view", "close-up portrait, head and shoulders only, detailed face", "br"),
    ]

    @classmethod
    def compose_grid(cls, view_images: Dict[str, str], output_path: str) -> Optional[str]:
        """将 5 个单视角图片拼接为 1+4 五宫格（本地 PIL 合成，保证永远只有 5 格）。

        画布为正方形（2 列 × 单元格 1:2 竖版）：
        - 左列 1 格（front_view），占满整高
        - 右列 2×2 共 4 格（侧面/背面/3-4侧面/特写）
        缺失的视角用浅灰占位格填充。
        """
        try:
            CELL_W, CELL_H = 512, 1024          # 单元格 1:2 竖版
            BORDER = 8                           # 白色分隔边
            canvas_w = CELL_W * 2 + BORDER * 3
            canvas_h = CELL_H + BORDER * 2
            canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))

            def _paste(path: Optional[str], x: int, y: int, w: int, h: int):
                if path and os.path.exists(path):
                    img = Image.open(path).convert("RGB")
                    # 居中裁剪到目标宽高比再缩放，避免拉伸变形
                    tw, th = w, h
                    sw, sh = img.size
                    target_ratio = tw / th
                    src_ratio = sw / sh
                    if src_ratio > target_ratio:   # 源图偏宽 → 裁两边
                        new_w = int(sh * target_ratio)
                        x0 = (sw - new_w) // 2
                        img = img.crop((x0, 0, x0 + new_w, sh))
                    else:                          # 源图偏高 → 裁上下
                        new_h = int(sw / target_ratio)
                        y0 = (sh - new_h) // 2
                        img = img.crop((0, y0, sw, y0 + new_h))
                    img = img.resize((tw, th), Image.LANCZOS)
                    canvas.paste(img, (x, y))
                else:
                    ImageDraw.Draw(canvas).rectangle(
                        [x, y, x + w, y + h], fill=(230, 230, 230))

            # 左列整高（占 1 格宽 × 1 格高，与右侧 2×2 等高）
            left = next((p for f, _, pos in cls.GRID_VIEWS if pos == "left"
                         for p in [view_images.get(f)] if p), None)
            _paste(left, BORDER, BORDER, CELL_W, CELL_H)

            # 右列 2×2
            pos_map = {"tl": (0, 0), "tr": (1, 0), "bl": (0, 1), "br": (1, 1)}
            half_w = (CELL_W - BORDER) // 2
            half_h = (CELL_H - BORDER) // 2
            for field, _, pos in cls.GRID_VIEWS:
                if pos == "left":
                    continue
                col, row = pos_map[pos]
                x = BORDER + CELL_W + BORDER + col * (half_w + BORDER)
                y = BORDER + row * (half_h + BORDER)
                _paste(view_images.get(field), x, y, half_w, half_h)

            canvas.save(output_path, "PNG")
            return output_path
        except Exception as e:
            print(f"五宫格拼接失败: {e}")
            return None

    @classmethod
    def generate_prompt(cls, base_prompt: str, character_name: str = "") -> str:
        """
        生成1拖4五宫格的提示词

        Args:
            base_prompt: 基础角色描述
            character_name: 角色名称

        Returns:
            str: 完整的五宫格生成提示词
        """

        name = character_name if character_name else "the character"

        prompt = f"""Character reference sheet for {name}: {base_prompt}

Create ONE SINGLE IMAGE containing EXACTLY 5 panels — no more, no less — arranged in a 1+4 grid layout inside a tall vertical 9:16 portrait canvas:

GRID STRUCTURE (strictly 5 panels only):
- The canvas is divided into 2 columns
- Left column: 1 tall panel spanning the full height
- Right column: exactly 2 rows × 2 columns = 4 small panels

Panel 1 — LEFT COLUMN (full height):
- Full body FRONT view of {name}
- Standing straight, facing directly toward viewer
- Complete body from head to toe
- Neutral expression, arms at sides

Panel 2 — RIGHT TOP-LEFT:
- Full body SIDE view, facing left
- Profile silhouette, same standing pose

Panel 3 — RIGHT TOP-RIGHT:
- Full body BACK view
- Facing away from viewer

Panel 4 — RIGHT BOTTOM-LEFT:
- 3/4 angle view (45° between front and side)
- Full body visible

Panel 5 — RIGHT BOTTOM-RIGHT:
- CLOSE-UP portrait (head and shoulders only)
- Same face as other views

STRICT REQUIREMENTS:
- EXACTLY 5 panels total, never 6, 7, or 8
- Right column MUST have exactly 2 rows and 2 columns
- Same {name} character in all 5 panels
- IDENTICAL appearance: same hair, same clothing, same colors, same style
- Consistent lighting across all panels
- Light gray or white neutral background
- Thin white borders between panels
- NO text, NO labels, NO watermarks, NO numbers, NO extra panels
- Professional character design reference sheet, high quality, detailed rendering"""

        return prompt
    
    @classmethod
    def generate_simple_prompt(cls, base_prompt: str, character_name: str = "") -> str:
        """
        生成简化的1拖4提示词

        Args:
            base_prompt: 基础角色描述
            character_name: 角色名称

        Returns:
            str: 简化版提示词
        """
        name = character_name if character_name else "character"
        return f"""Character reference sheet for {name}: {base_prompt}

Create ONE SINGLE IMAGE in 9:16 portrait orientation with EXACTLY 5 panels (no more, no less):
- LEFT COLUMN (full height): Front view, full body
- RIGHT TOP-LEFT: Side view (facing left), full body
- RIGHT TOP-RIGHT: Back view, full body
- RIGHT BOTTOM-LEFT: 3/4 angle view, full body
- RIGHT BOTTOM-RIGHT: Close-up portrait, head and shoulders

Right side MUST be exactly 2 rows × 2 columns. Total panels MUST be exactly 5. Same character in all views. Identical appearance and costume. Consistent lighting. Neutral background. No text, no extra panels. High quality."""


def create_1_drag_4_prompt(character_name: str, character_description: str) -> str:
    """
    便捷函数：创建1拖4五宫格提示词
    
    Args:
        character_name: 角色名称
        character_description: 角色描述
        
    Returns:
        str: 完整的提示词
    """
    return CharacterGridGenerator.generate_prompt(character_description, character_name)
