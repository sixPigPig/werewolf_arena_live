from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.common import PaginationResponse
from app.api.schemas.admin_p2 import AdminGameP2QualityV1


AdminGameStatus = Literal["complete", "partial"]
AdminGameRunStatus = Literal["queued", "running", "completed", "failed", "canceled"]
AdminQualityEvaluationStatus = Literal[
    "not_scheduled",
    "pending",
    "processing",
    "completed",
    "failed",
    "superseded",
]
AdminQualityDataStatus = Literal[
    "collecting",
    "available",
    "partial",
    "legacy",
    "unavailable",
]
AdminQualityVerdict = Literal["pass", "warn", "fail", "unavailable"]
AdminGameModelRequestStatus = Literal[
    "pending",
    "completed",
    "failed",
    "response_missing",
]
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
    revision_id: str | None
    revision_no: int | None
    content_hash: str | None


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


class AdminGameSpeechSummary(BaseModel):
    speaker: str
    message: str


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
    sheriff_candidates: list[str]
    sheriff_withdrawn: list[str]
    sheriff_final_candidates: list[str]
    sheriff_votes: dict[str, str]
    sheriff_pk_candidates: list[str]
    sheriff_runoff_votes: dict[str, str]
    exile_pk_candidates: list[str]
    exile_runoff_votes: dict[str, str]
    exile_resolution_reason: str | None
    sheriff_speech_order: list[str]
    sheriff_speech_direction: str | None
    speech_order: list[str]
    speech_order_choice: str | None
    sheriff_speeches: list[AdminGameSpeechSummary]
    sheriff_pk_speeches: list[AdminGameSpeechSummary]
    exile_pk_speeches: list[AdminGameSpeechSummary]
    debate: list[AdminGameSpeechSummary]
    sheriff_badge_target: str | None
    sheriff_badge_lost: bool
    sheriff_badge_lost_reason: str | None
    day_ended_by_self_explosion: bool


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


class AdminQualitySourceCoverage(BaseModel):
    state: str = Field(max_length=20)
    logs: str = Field(max_length=20)
    events: str = Field(max_length=20)
    voice: str = Field(max_length=20)
    subtitles: str = Field(max_length=20)
    pending_voice_count: int = Field(ge=0)
    failed_voice_count: int = Field(ge=0)


class AdminQualityIssueCounts(BaseModel):
    P0: int = Field(ge=0)
    P1: int = Field(ge=0)
    P2: int = Field(ge=0)


class AdminQualityFacts(BaseModel):
    critical_opportunity_count: int = Field(ge=0)
    critical_recorded_count: int = Field(ge=0)
    critical_fact_write_rate: float | None = Field(default=None, ge=0, le=1)
    prompt_expected_critical_count: int = Field(ge=0)
    prompt_included_critical_count: int = Field(ge=0)
    prompt_missing_critical_count: int = Field(ge=0)
    critical_fact_prompt_coverage_rate: float | None = Field(default=None, ge=0, le=1)
    deterministic_contradiction_count: int = Field(ge=0)


class AdminQualityStructure(BaseModel):
    max_consecutive_self_explosions: int = Field(ge=0)
    chain_three_count: int = Field(ge=0)
    normal_day_debate_round_count: int = Field(ge=0)
    sheriff_model_request_count: int = Field(ge=0)
    public_model_request_count: int = Field(ge=0)
    sheriff_model_request_rate: float | None = Field(default=None, ge=0, le=1)


class AdminQualityVoice(BaseModel):
    narratable_event_count: int = Field(ge=0)
    effective_voice_event_count: int = Field(ge=0)
    missing_narratable_event_count: int = Field(ge=0)
    voice_coverage_rate: float | None = Field(default=None, ge=0, le=1)
    voice_source_event_lag: int | None = Field(default=None, ge=0)
    terminal_judge_voice_coverage: bool | None
    pending_voice_count: int = Field(ge=0)
    failed_voice_count: int = Field(ge=0)
    interruption_count: int = Field(ge=0)
    replay_count: int = Field(ge=0)


class AdminQualityPerformance(BaseModel):
    action_count: int = Field(ge=0)
    action_duration_ms_max: int | None = Field(default=None, ge=0)
    action_duration_p95_ms: int | None = Field(default=None, ge=0)
    first_token_count: int = Field(ge=0)
    first_token_ms_max: int | None = Field(default=None, ge=0)
    first_token_p95_ms: int | None = Field(default=None, ge=0)
    game_duration_ms: int | None = Field(default=None, ge=0)
    timeout_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    fallback_count: int = Field(ge=0)


class AdminQualityContent(BaseModel):
    speech_check_count: int = Field(ge=0)
    repeated_speech_count: int = Field(ge=0)
    repeated_speech_rate: float | None = Field(default=None, ge=0, le=1)
    speech_rewrite_count: int = Field(ge=0)
    speech_rewrite_recovered_count: int = Field(ge=0)
    speech_retry_exhausted_count: int = Field(ge=0)
    privacy_p0_issue_count: int = Field(ge=0)
    lineup_warning_count: int = Field(ge=0)


class AdminGameQualityEvaluationSummary(BaseModel):
    schema_version: Literal[1] = 1
    evaluator_version: str = Field(max_length=40)
    evaluation_status: AdminQualityEvaluationStatus
    data_status: AdminQualityDataStatus
    verdict: AdminQualityVerdict
    source_coverage: AdminQualitySourceCoverage
    issue_counts: AdminQualityIssueCounts
    facts: AdminQualityFacts
    structure: AdminQualityStructure
    voice: AdminQualityVoice
    performance: AdminQualityPerformance
    content: AdminQualityContent
    evaluated_at: datetime | None


class AdminGameQualityEvaluationResponse(BaseModel):
    session_id: str = Field(max_length=32)
    quality_evaluation: AdminGameQualityEvaluationSummary


class AdminGameQualityIssue(BaseModel):
    issue_id: str = Field(max_length=40)
    code: str = Field(max_length=80)
    severity: Literal["P0", "P1", "P2"]
    channel: str = Field(max_length=40)
    round_number: int | None = Field(default=None, ge=0)
    event_id: int | None = Field(default=None, ge=0)
    utterance_id: str | None = Field(default=None, max_length=80)
    first_detected_at: datetime


class AdminGameQualityIssuesResponse(BaseModel):
    session_id: str = Field(max_length=32)
    evaluation_id: str | None = Field(default=None, max_length=40)
    items: list[AdminGameQualityIssue] = Field(max_length=200)


class AdminGameQualityRetryResponse(BaseModel):
    session_id: str = Field(max_length=32)
    evaluation_id: str = Field(max_length=40)
    status: Literal["pending"]


class AdminGameDetailResponse(AdminGameListItem):
    players: list[AdminGamePlayerSummary]
    rounds: list[AdminGameRoundSummary]
    runs: list[AdminGameRunSummary]
    recent_events: list[AdminGameEventSummary] = Field(max_length=50)
    diagnostics: AdminGameDiagnostics
    p2_quality: AdminGameP2QualityV1
    quality_evaluation: AdminGameQualityEvaluationSummary


class AdminGameModelRequestSummary(BaseModel):
    request_id: str = Field(max_length=80)
    round_number: int | None = Field(default=None, ge=0)
    phase: str | None = Field(default=None, max_length=40)
    actor: str | None = Field(default=None, max_length=120)
    action: str = Field(max_length=80)
    model: str | None = Field(default=None, max_length=120)
    status: AdminGameModelRequestStatus
    attempt_count: int = Field(ge=0)
    invalid_attempt_count: int = Field(ge=0)
    run_id: str | None = Field(default=None, max_length=32)
    event_id: int | None = Field(default=None, ge=0)
    created_at: datetime | None


class AdminGameModelRequestListResponse(BaseModel):
    session_id: str = Field(max_length=32)
    items: list[AdminGameModelRequestSummary] = Field(max_length=1000)


class AdminGameModelRequestDetail(AdminGameModelRequestSummary):
    prompt: str | None = Field(default=None, max_length=200_000)
    raw_response: str | None = Field(default=None, max_length=200_000)
    parsed_output: str | None = Field(default=None, max_length=200_000)
    raw_choice: str | None = Field(default=None, max_length=200_000)
    error: str | None = Field(default=None, max_length=4_000)


class AdminGameRunErrorSummary(BaseModel):
    run_id: str
    error: str


class AdminGameDebugResponse(BaseModel):
    session_id: str
    game_error: str | None
    run_errors: list[AdminGameRunErrorSummary] = Field(max_length=20)
