import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Python React Web API"
    api_v1_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/app"
    werewolf_logs_dir: str = "logs"
    ark_tts_enabled: bool = False
    ark_tts_api_key: str = ""
    ark_tts_resource_id: str = "seed-tts-2.0"
    ark_tts_ws_url: str = "wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection"
    ark_tts_player_speaker: str = "zh_female_gaolengyujie_uranus_bigtts"
    ark_tts_judge_speaker: str = "zh_female_vv_uranus_bigtts"
    ark_tts_audio_format: str = "pcm"
    ark_tts_sample_rate: int = 24000
    ark_tts_judge_asset_audio_format: str = "mp3"
    ark_tts_judge_asset_sample_rate: int = 24000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value.startswith("["):
                return json.loads(stripped_value)

            return [origin.strip() for origin in value.split(",") if origin.strip()]

        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
