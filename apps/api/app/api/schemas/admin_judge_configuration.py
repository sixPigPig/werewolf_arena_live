from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminJudgeModelOption(BaseModel):
    provider: Literal["agent_plan"]
    model_id: str
    label: str


class AdminJudgeSpeakerOption(BaseModel):
    voice_type: str
    name: str


class AdminJudgeConfigurationResponse(BaseModel):
    model_provider: Literal["agent_plan"]
    model_id: str
    tts_speaker: str
    version: int
    source: Literal["database", "environment"]
    updated_at: datetime | None
    models: list[AdminJudgeModelOption]
    speakers: list[AdminJudgeSpeakerOption]
    speaker_catalog_available: bool
    tts_resource_id: str


class AdminJudgeConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_provider: Literal["agent_plan"] = "agent_plan"
    model_id: str = Field(min_length=1, max_length=160)
    tts_speaker: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=0)
