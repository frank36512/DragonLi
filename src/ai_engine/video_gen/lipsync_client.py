import os
from core.config.config_manager import ConfigManager

class LipSyncClient:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.config = self.config_manager.config

    def _get_provider_config(self):
        # 配置中该键可能为 None，做容错避免遍历 None 崩溃
        apis = self.config.get("api_configs") or []
        for api in apis:
            if api.get("type") == "LipSync":
                return api
        # Fallback
        for api in apis:
            if api.get("type") == "Veo":
                return api
        return None

    def sync_lips(self, video_path, audio_path, output_path):
        """
        Syncs video lips to audio.
        """
        print(f"Syncing lips for {video_path} with {audio_path}")

        config = self._get_provider_config()
        if not config:
            print("No LipSync provider configured.")
            return None

        provider = config.get("provider", "veo").lower()

        if provider == "veo":
            return self._sync_veo(video_path, audio_path, output_path, config)

        print(f"Unknown LipSync provider: {provider}")
        return None

    def _sync_veo(self, video_path, audio_path, output_path, config):
        from ai_engine.veo_service import VeoService

        base_url = config.get("base_url", "https://api.veo.ai/v1")
        api_key = config.get("api_key", "")

        if not api_key:
            print("Error: Veo API Key not configured.")
            return None

        veo = VeoService(api_key, base_url)
        # 形参名为 video_url/audio_url；VeoService 内部会把本地路径上传转换为公网 URL
        return veo.sync_lips(video_url=video_path, audio_url=audio_path, output_path=output_path)
