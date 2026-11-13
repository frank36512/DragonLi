import os
from core.config.config_manager import ConfigManager

class SubtitleClient:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.config = self.config_manager.config

    def _get_provider_config(self):
        # 配置中该键可能为 None，做容错避免遍历 None 崩溃
        apis = self.config.get("api_configs") or []
        for api in apis:
            if api.get("type") == "Subtitle":
                return api
        for api in apis:
            if api.get("type") == "Veo":
                return api
        return None

    def generate_subtitles(self, audio_path, output_path):
        """
        Generates subtitles (SRT) from audio using API.
        """
        print(f"Generating subtitles for {audio_path}")

        config = self._get_provider_config()
        if not config:
            print("No Subtitle provider configured.")
            return None

        provider = config.get("provider", "veo").lower()

        if provider == "veo":
            return self._generate_veo(audio_path, output_path, config)

        print(f"Unknown Subtitle provider: {provider}")
        return None

    def _generate_veo(self, audio_path, output_path, config):
        from ai_engine.veo_service import VeoService

        base_url = config.get("base_url", "https://api.veo.ai/v1")
        api_key = config.get("api_key", "")

        if not api_key:
            print("Error: Veo API Key not configured.")
            return None

        veo = VeoService(api_key, base_url)
        # 形参名为 audio_url；VeoService 内部会把本地路径上传转换为公网 URL
        return veo.generate_subtitles(audio_url=audio_path, output_path=output_path)
