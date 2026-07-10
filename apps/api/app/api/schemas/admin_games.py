from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.common import PaginationResponse


AdminGameStatus = Literal["complete", "partial"]
AdminGameRunStatus = Literal["queued", "running", "completed", "failed"]
AdminGameSort = Literal[
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
]


class AdminGameRuleSetSummary(BaseModel):
    id: str
    name: str
    player_count: int | None


class AdminGameRunSummary(BaseModel):
    run_id: str
    status: AdminGameRunStatus
    villager_model: str | None
    werewolf_model: str | None
    max_rounds: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    event_count: int
    has_error: bool


class AdminGameListItem(BaseModel):
    session_id: str
    status: AdminGameStatus
    winner: str | None
    round_count: int
    resumable: bool
    rule_set: AdminGameRuleSetSummary | None
    created_at: datetime
    updated_at: datetime
    latest_run: AdminGameRunSummary | None


class AdminGameListResponse(BaseModel):
    items: list[AdminGameListItem]
    pagination: PaginationResponse


class AdminGamePlayerSummary(BaseModel):
    seat: int
    name: str
    profile_id: str | None
    model: str | None
    role: str | None
    personality_id: str
    appearance_id: str
    avatar_image_url: str
    tags: list[str]


class AdminGameDeathSummary(BaseModel):
    player: str
    cause: str | None
    source: str | None


class AdminGameRoundSummary(BaseModel):
    number: int
    success: bool
    players: list[str]
    public_summary: str
    night_deaths: list[AdminGameDeathSummary]
    day_deaths: list[AdminGameDeathSummary]
    exiled: str | None
    hunter_shot: str | None
    idiot_revealed: str | None
    sheriff: str | None
    votes: dict[str, str]
    sheriff_elected: str | None
    werewolf_self_exploded: str | None


class AdminGameEventSummary(BaseModel):
    run_id: str
    event_id: int
    type: str
    round: int | None
    phase: str | None
    actor: str | None
    action: str | None
    created_at: datetime


class AdminGameDiagnostics(BaseModel):
    run_count: int
    event_count: int
    failed_voice_count: int
    last_event: AdminGameEventSummary | None


class AdminGameDetailResponse(AdminGameListItem):
    players: list[AdminGamePlayerSummary]
    rounds: list[AdminGameRoundSummary]
    runs: list[AdminGameRunSummary]
    recent_events: list[AdminGameEventSummary] = Field(max_length=50)
    diagnostics: AdminGameDiagnostics


class AdminGameRunErrorSummary(BaseModel):
    run_id: str
    error: str


class AdminGameDebugResponse(BaseModel):
    session_id: str
    game_error: str | None
    run_errors: list[AdminGameRunErrorSummary] = Field(max_length=20)
