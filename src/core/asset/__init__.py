"""素材库模块：统一管理 AI 生成图、上传图、stock 素材。"""
from .asset_manager import AssetManager, AssetItem, ASSET_TYPE_IMAGE, ASSET_TYPE_VIDEO, ASSET_TYPE_AUDIO

__all__ = ["AssetManager", "AssetItem", "ASSET_TYPE_IMAGE", "ASSET_TYPE_VIDEO", "ASSET_TYPE_AUDIO"]
