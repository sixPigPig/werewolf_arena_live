from __future__ import annotations

from app.core.config import settings
from app.shared.volcengine_tts import VolcengineTtsConfig


def get_tts_config() -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=settings.ark_tts_enabled,
        api_key=settings.ark_tts_api_key,
        resource_id=settings.ark_tts_resource_id,
        ws_url=settings.ark_tts_ws_url,
        player_speaker=settings.ark_tts_player_speaker,
        judge_speaker=settings.ark_tts_judge_speaker,
        audio_format=settings.ark_tts_audio_format,
        sample_rate=settings.ark_tts_sample_rate,
    )
