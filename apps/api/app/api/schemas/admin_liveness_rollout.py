from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AdminLivenessExperienceOption(BaseModel):
    revision: str = Field(max_length=40)
    label: str = Field(max_length=80)
    description: str = Field(max_length=300)
    control_summary: str = Field(max_length=300)
    treatment_summary: str = Field(max_length=300)


class AdminLivenessRolloutResponse(BaseModel):
    revision: int = Field(ge=0)
    experience_revision: str = Field(max_length=40)
    experiment_id: str = Field(max_length=64)
    treatment_percent: int = Field(ge=0, le=100)
    control_percent: int = Field(ge=0, le=100)
    source: Literal["database", "environment_fallback"]
    effective_scope: Literal["new_sessions_only"]
    updated_at: datetime | None
    available_experiences: list[AdminLivenessExperienceOption]


class AdminLivenessRolloutUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=0, strict=True)
    experience_revision: str = Field(min_length=1, max_length=40)
    experiment_id: str = Field(min_length=1, max_length=64)
    treatment_percent: int = Field(ge=0, le=100, strict=True)
    change_reason: str = Field(min_length=3, max_length=500)

    @field_validator("experience_revision", "experiment_id", "change_reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned
