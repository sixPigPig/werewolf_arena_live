from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.common import PaginationResponse


class AdminOverviewProfiles(BaseModel):
    total: int = Field(ge=0)
    draft: int = Field(ge=0)
    published: int = Field(ge=0)
    archived: int = Field(ge=0)
    featured: int = Field(ge=0)


class AdminOverviewGames(BaseModel):
    total: int = Field(ge=0)
    complete: int = Field(ge=0)
    incomplete: int = Field(ge=0)
    resumable: int = Field(ge=0)


class AdminOverviewRuns(BaseModel):
    total: int = Field(ge=0)
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    completed: int = Field(ge=0)
    canceled: int = Field(ge=0)
    failed: int = Field(ge=0)
    stale: int = Field(ge=0)
    recovery_exhausted: int = Field(ge=0)


class AdminOverviewJobs(BaseModel):
    total: int = Field(ge=0)
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)


class AdminOverviewQuality(BaseModel):
    cohort_days: int = Field(ge=1, le=30)
    sample_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    warn_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    legacy_count: int = Field(ge=0)
    p0_game_count: int = Field(ge=0)
    latest_p0_at: str | None
    pending_count: int = Field(ge=0)
    processing_count: int = Field(ge=0)
    worker_failed_count: int = Field(ge=0)
    expired_lease_count: int = Field(ge=0)
    oldest_pending_seconds: int | None = Field(default=None, ge=0)
    worker_up: bool
    critical_fact_expected: int = Field(ge=0)
    critical_fact_recorded: int = Field(ge=0)
    prompt_fact_expected: int = Field(ge=0)
    prompt_fact_included: int = Field(ge=0)
    voice_expected: int = Field(ge=0)
    voice_covered: int = Field(ge=0)
    action_sample_count: int = Field(ge=0)
    action_p95_ms: int | None = Field(default=None, ge=0)
    speech_check_count: int = Field(ge=0)
    repeated_speech_count: int = Field(ge=0)
    speech_retry_exhausted_count: int = Field(ge=0)
    lineup_warning_count: int = Field(ge=0)


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
    games: AdminOverviewGames
    runs: AdminOverviewRuns
    jobs: AdminOverviewJobs
    quality: AdminOverviewQuality
    reaper_up: bool
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
    reaper_poll_seconds: float = Field(gt=0)
    reaper_stale_grace_seconds: float = Field(ge=0)
    reaper_max_attempts: int = Field(ge=1)
    reaper_probe_max_age_seconds: float = Field(gt=0)


class AdminSettingsLiveRuns(BaseModel):
    lease_seconds: float = Field(gt=0)
    heartbeat_seconds: float = Field(gt=0)
    event_poll_seconds: float = Field(gt=0)


class AdminSettingsResponse(BaseModel):
    environment: Literal["development", "test", "staging", "production"]
    api_prefix: str = Field(max_length=80)
    tts_enabled: bool
    authentication: AdminSettingsAuthentication
    compatibility: AdminSettingsCompatibility
    workers: AdminSettingsWorkers
    live_runs: AdminSettingsLiveRuns


class AdminSearchResult(BaseModel):
    type: Literal["run", "game", "player", "job"]
    id: str = Field(max_length=80)
    label: str = Field(max_length=160)
    description: str = Field(max_length=240)
    status: str = Field(max_length=40)
    href: str = Field(max_length=240)


class AdminSearchResponse(BaseModel):
    query: str = Field(min_length=1, max_length=80)
    items: list[AdminSearchResult]
