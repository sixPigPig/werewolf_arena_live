from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import PaginationResponse
from app.api.schemas.admin_p2 import AdminGameP2QualityV1


AdminGameStatus = Literal["complete", "partial"]
AdminGameRunStatus = Literal["queued", "running", "completed", "failed", "canceled"]
AdminQualityEvaluationStatus = Literal[
    "not_scheduled",
    "queued",
    "running",
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
AdminQualityCriticalActionOrigin = Literal[
    "canceled",
    "failed",
    "model_after_retry",
    "model_first_attempt",
    "rule_default",
    "state_machine",
    "system_fallback",
    "system_timeout",
]
AdminQualityCriticalInputCompleteness = Literal[
    "complete",
    "critical_public_fact_missing",
    "private_observation_missing",
    "rule_missing",
    "unknown",
]
AdminQualityCriticalActionLegality = Literal[
    "invalid_normalized",
    "invalid_not_executed",
    "invalid_system_fallback",
    "legal_but_canceled",
    "legal_executed",
    "legal_system_result",
    "not_executed",
    "unknown",
]
AdminQualityCriticalReasoningObservation = Literal[
    "hard_rule_conflict",
    "identity_information_conflict",
    "internal_logic_contradiction",
    "not_assessed",
    "not_available",
    "used_unspecified_rule",
]
AdminQualityCriticalDirectImpact = Literal[
    "canceled_no_effect",
    "failed_no_effect",
    "game_state_effect_applied",
    "model_result_applied",
    "no_state_change",
    "phase_ended",
    "system_result_applied",
    "vote_recorded",
]
AdminQualityCriticalAttribution = Literal[
    "canceled",
    "model_internal_logic_contradiction",
    "model_judgment_and_rule_input_gap",
    "model_reasoning_error",
    "not_determined",
    "runtime_fallback",
]
AdminQualityCriticalClauseId = Annotated[
    str,
    Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_.-]+$"),
]
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
    exile_last_words: AdminGameSpeechSummary | None
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
    logical_action_counts: dict[str, int] = Field(default_factory=dict)
    provider_attempt_counts: dict[str, int] = Field(default_factory=dict)
    retry_counts: dict[str, int] = Field(default_factory=dict)


class AdminQualityContent(BaseModel):
    speech_check_count: int = Field(ge=0)
    repeated_speech_count: int = Field(ge=0)
    repeated_speech_rate: float | None = Field(default=None, ge=0, le=1)
    speech_rewrite_count: int = Field(ge=0)
    speech_rewrite_recovered_count: int = Field(ge=0)
    speech_retry_exhausted_count: int = Field(ge=0)
    privacy_p0_issue_count: int = Field(ge=0)
    lineup_warning_count: int = Field(ge=0)


class AdminLivenessLatencySummary(BaseModel):
    count: int = Field(ge=0)
    p50: int | None = Field(default=None, ge=0)
    p95: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)


class AdminLivenessTimingCoverage(BaseModel):
    count: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0, le=1)


class AdminLivenessFeatureModes(BaseModel):
    style_gate: Literal["async_observe"] | None = None
    actor_mind: Literal["read"] | None = None
    sentence_stream: Literal["committed_segments_v2"] | None = None
    affect_delivery: Literal["on"] | None = None
    tts_prefetch_depth: Literal[1] | None = None
    voice_preempt: Literal["deterministic"] | None = None


class AdminLivenessActorMind(BaseModel):
    snapshot_count: int = Field(ge=0)
    update_count: int = Field(ge=0)
    source_complete_count: int = Field(ge=0)


class AdminQualityLiveness(BaseModel):
    experience_revision: str | None = Field(default=None, max_length=40)
    feature_modes: AdminLivenessFeatureModes
    public_speech_count: int = Field(ge=0)
    timing_coverage: dict[str, AdminLivenessTimingCoverage]
    stage_latency_ms: dict[str, AdminLivenessLatencySummary]
    prompt_chars: AdminLivenessLatencySummary
    hard_gate_duration_ms: AdminLivenessLatencySummary
    hard_retry_count: int = Field(ge=0)
    hard_retry_rate: float | None = Field(default=None, ge=0, le=1)
    hard_exhausted_count: int = Field(ge=0)
    hard_exhausted_rate: float | None = Field(default=None, ge=0, le=1)
    partial_speech_count: int = Field(ge=0)
    interrupted_speech_count: int = Field(ge=0)
    voice_timing_coverage: dict[str, int]
    tts_to_first_audio_ms: AdminLivenessLatencySummary
    turn_to_first_audio_ms: AdminLivenessLatencySummary
    voice_status_counts: dict[str, int]
    playback_timing_coverage: dict[str, int]
    playback_status_counts: dict[str, int]
    speaker_gap_ms: AdminLivenessLatencySummary
    actor_mind: AdminLivenessActorMind


class AdminQualityCriticalClauseCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["complete", "partial", "missing", "unknown"]
    required_count: int = Field(ge=0, le=16)
    included_count: int = Field(ge=0, le=16)
    missing_count: int = Field(ge=0, le=16)
    missing_clause_ids: list[AdminQualityCriticalClauseId] = Field(max_length=16)


class AdminQualityCriticalAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    action_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    round_number: int | None = Field(default=None, ge=0, le=1_000_000)
    action: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    action_origin: AdminQualityCriticalActionOrigin
    input_completeness: AdminQualityCriticalInputCompleteness
    action_legality: AdminQualityCriticalActionLegality
    reasoning_observation: AdminQualityCriticalReasoningObservation
    direct_impact: AdminQualityCriticalDirectImpact
    attribution: AdminQualityCriticalAttribution
    clause_ids: list[AdminQualityCriticalClauseId] = Field(max_length=16)
    coverage: AdminQualityCriticalClauseCoverage


class AdminQualityLatestSuccessfulResult(BaseModel):
    evaluator_version: str = Field(max_length=40)
    source_revision: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    completed_at: datetime


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
    liveness: AdminQualityLiveness
    critical_actions: list[AdminQualityCriticalAction] = Field(max_length=64)
    evaluated_at: datetime | None
    source_revision: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempt_count: int = Field(default=0, ge=0)
    failure_reason: str | None = Field(default=None, max_length=64)
    can_retry: bool = False
    latest_successful_result: AdminQualityLatestSuccessfulResult | None = None


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
