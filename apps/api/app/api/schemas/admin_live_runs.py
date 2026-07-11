from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.api.schemas.common import PaginationResponse


AdminLiveRunStatus = Literal["queued", "running", "completed", "failed", "canceled"]
AdminLiveRunWorkerState = Literal["active", "stale", "unassigned", "released"]
AdminLiveRunSort = Literal[
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
]


class AdminLiveRunRuleSetSummary(BaseModel):
    id: str
    name: str
    player_count: int | None


class AdminLiveRunGameSummary(BaseModel):
    status: Literal["complete", "partial"]
    resumable: bool
    terminal: bool


class AdminLiveRunVoiceCounts(BaseModel):
    total: int
    pending: int
    synthesizing: int
    complete: int
    failed: int
    canceled: int
    other: int


class AdminLiveRunListItem(BaseModel):
    run_id: str
    session_id: str
    status: AdminLiveRunStatus
    winner: str | None
    villager_model: str | None
    werewolf_model: str | None
    max_rounds: int
    rule_set: AdminLiveRunRuleSetSummary | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    stop_requested_at: datetime | None
    worker_heartbeat_at: datetime | None
    worker_state: AdminLiveRunWorkerState
    recovery_attempts: int
    recovery_last_attempt_at: datetime | None
    recovery_not_before: datetime | None
    recovery_exhausted: bool
    updated_at: datetime
    event_count: int
    last_activity_at: datetime
    is_stale: bool
    voice_counts: AdminLiveRunVoiceCounts
    has_error: bool
    game: AdminLiveRunGameSummary | None


class AdminLiveRunListResponse(BaseModel):
    items: list[AdminLiveRunListItem]
    pagination: PaginationResponse


class AdminLiveRunEventSummary(BaseModel):
    event_id: int
    type: str
    round: int | None
    phase: str | None
    actor: str | None
    action: str | None
    created_at: datetime


class AdminLiveRunDetailResponse(AdminLiveRunListItem):
    recent_events: list[AdminLiveRunEventSummary] = Field(max_length=50)


class AdminLiveRunControlRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return normalized


class AdminLiveRunControlResponse(BaseModel):
    action: Literal["stop", "resume"]
    target_run_id: str
    run_id: str
    session_id: str
    run_status: AdminLiveRunStatus
    stop_requested_at: datetime | None
    replayed: bool


class AdminLiveRunVoiceErrorSummary(BaseModel):
    utterance_id: str
    error: str


class AdminLiveRunDebugResponse(BaseModel):
    run_id: str
    run_error: str | None
    voice_error_total: int
    voice_errors: list[AdminLiveRunVoiceErrorSummary] = Field(max_length=20)
    truncated: bool
