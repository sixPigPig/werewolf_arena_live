from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AdminJudgeVoiceAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"


class AdminJudgeVoiceSort(StrEnum):
    CATEGORY = "category"
    CATEGORY_DESC = "-category"
    ID = "id"
    ID_DESC = "-id"
    BYTE_SIZE = "byte_size"
    BYTE_SIZE_DESC = "-byte_size"


class AdminJudgeVoiceCategorySummary(BaseModel):
    name: str = Field(max_length=80)
    total: int = Field(ge=0)
    available: int = Field(ge=0)
    missing: int = Field(ge=0)


class AdminJudgeVoiceLineItem(BaseModel):
    id: str = Field(max_length=80)
    text: str = Field(max_length=500)
    category: str = Field(max_length=80)
    used: bool
    available: bool
    byte_size: int | None = Field(default=None, ge=0)
    template_id: str | None = Field(default=None, max_length=80)
    seat_number: int | None = Field(default=None, ge=1, le=12)
    subtitle_cue_count: int = Field(ge=0)
    audio_url: str | None = Field(default=None, max_length=240)


class AdminJudgeVoiceCoverage(BaseModel):
    total: int = Field(ge=0)
    available: int = Field(ge=0)
    missing: int = Field(ge=0)
    byte_total: int = Field(ge=0)


class AdminJudgeVoicePagination(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class AdminJudgeVoiceLineListResponse(BaseModel):
    audio_format: str = Field(max_length=20)
    sample_rate: int = Field(gt=0)
    storage_mode: Literal["database", "legacy_static_directory"]
    coverage: AdminJudgeVoiceCoverage
    categories: list[AdminJudgeVoiceCategorySummary]
    items: list[AdminJudgeVoiceLineItem]
    pagination: AdminJudgeVoicePagination


class AdminJudgeVoiceGenerationRequest(BaseModel):
    mode: Literal["missing", "all"] = "missing"
    line_ids: list[str] | None = Field(default=None, min_length=1, max_length=160)


class AdminJudgeVoiceJobResponse(BaseModel):
    id: str = Field(max_length=36)
    mode: Literal["missing", "all"]
    status: Literal["queued", "running", "completed", "failed"]
    requested_line_ids: list[str] | None
    total_count: int = Field(ge=0)
    processed_count: int = Field(ge=0)
    generated_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=80)
    created_at: str
    started_at: str | None
    completed_at: str | None
