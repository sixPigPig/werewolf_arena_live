from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdminJudgeSpeakerOption(BaseModel):
    voice_type: str
    name: str


class AdminJudgeConfigurationResponse(BaseModel):
    voice_mode: Literal["fixed", "random"]
    tts_speaker: str
    random_tts_speakers: list[str]
    version: int
    source: Literal["database", "environment"]
    updated_at: datetime | None
    speakers: list[AdminJudgeSpeakerOption]
    speaker_catalog_available: bool
    tts_resource_id: str


class AdminJudgeConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_mode: Literal["fixed", "random"]
    tts_speaker: str | None = Field(default=None, min_length=1, max_length=160)
    random_tts_speakers: list[str] = Field(default_factory=list, max_length=100)
    expected_version: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_voice_selection(self) -> "AdminJudgeConfigurationRequest":
        if self.voice_mode == "fixed" and not self.tts_speaker:
            raise ValueError("tts_speaker is required in fixed mode")
        if self.voice_mode == "random" and len(set(self.random_tts_speakers)) < 2:
            raise ValueError("random mode requires at least two speakers")
        return self
