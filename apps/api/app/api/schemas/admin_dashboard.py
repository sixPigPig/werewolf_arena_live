from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.common import PaginationResponse


class AdminOverviewProfiles(BaseModel):
    total: int = Field(ge=0)
    draft: int = Field(ge=0)
    published: int = Field(ge=0)
    archived: int = Field(ge=0)
    featured: int = Field(ge=0)


class AdminOverviewJobs(BaseModel):
    total: int = Field(ge=0)
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)


class AdminOverviewAlert(BaseModel):
    code: str = Field(max_length=80)
    severity: Literal["info", "warning", "critical"]
    title: str = Field(max_length=160)
    detail: str = Field(max_length=300)
    count: int = Field(ge=0)
    href: str = Field(max_length=240)


class AdminOverviewResponse(BaseModel):
    generated_at: str
    environment: Literal["development", "test", "staging", "production"]
    profiles: AdminOverviewProfiles
    jobs: AdminOverviewJobs
    alerts: list[AdminOverviewAlert]


class AdminJobItem(BaseModel):
    id: str = Field(max_length=36)
    type: Literal["judge_voice_generation"]
    mode: Literal["missing", "all"]
    status: Literal["queued", "running", "completed", "failed"]
    total_count: int = Field(ge=0)
    processed_count: int = Field(ge=0)
    generated_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=80)
    created_at: str
    started_at: str | None
    completed_at: str | None


class AdminJobListResponse(BaseModel):
    items: list[AdminJobItem]
    pagination: PaginationResponse


class AdminSettingsAuthentication(BaseModel):
    oidc_enabled: bool
    development_login_enabled: bool
    secure_admin_cookie: bool
    secure_public_cookie: bool
    admin_session_ttl_seconds: int = Field(ge=300)
    public_session_ttl_seconds: int = Field(ge=300)


class AdminSettingsCompatibility(BaseModel):
    legacy_content_writes_enabled: bool
    legacy_voice_generation_enabled: bool


class AdminSettingsWorkers(BaseModel):
    judge_voice_poll_seconds: float = Field(gt=0)
    judge_voice_heartbeat_seconds: float = Field(gt=0)
    judge_voice_probe_max_age_seconds: float = Field(gt=0)


class AdminSettingsResponse(BaseModel):
    environment: Literal["development", "test", "staging", "production"]
    api_prefix: str = Field(max_length=80)
    tts_enabled: bool
    authentication: AdminSettingsAuthentication
    compatibility: AdminSettingsCompatibility
    workers: AdminSettingsWorkers


class AdminSearchResult(BaseModel):
    type: Literal["player", "job"]
    id: str = Field(max_length=80)
    label: str = Field(max_length=160)
    description: str = Field(max_length=240)
    status: str = Field(max_length=40)
    href: str = Field(max_length=240)


class AdminSearchResponse(BaseModel):
    query: str = Field(min_length=1, max_length=80)
    items: list[AdminSearchResult]
