from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AdminP2DataStatus = Literal["legacy", "collecting", "available", "unavailable"]
AdminP2GateStatus = Literal["pass", "warn", "fail", "unavailable"]


class AdminP2PerformanceV1(BaseModel):
    request_count: int
    discrete_action_sample_count: int
    discrete_action_p50_ms: int | None
    discrete_action_p95_ms: int | None
    discrete_action_max_ms: int | None
    speech_first_token_sample_count: int
    speech_first_token_p95_ms: int | None
    speech_first_token_max_ms: int | None
    timeout_count: int
    fallback_count: int
    active_request_count: int
    game_duration_ms: int | None = None


class AdminP2SpeechQualityV1(BaseModel):
    checked_count: int
    retry_count: int
    exhausted_count: int
    low_novelty_window_count: int


class AdminP2ChoiceNormalizationV1(BaseModel):
    exact_count: int
    seat_alias_count: int
    public_label_count: int
    invalid_count: int
    other_count: int


class AdminP2ProviderAttemptOutcomesV1(BaseModel):
    attempt_count: int = Field(default=0, ge=0)
    valid_response_count: int = Field(default=0, ge=0)
    invalid_response_count: int = Field(default=0, ge=0)
    timed_out_count: int = Field(default=0, ge=0)
    canceled_count: int = Field(default=0, ge=0)
    transport_failed_count: int = Field(default=0, ge=0)


class AdminP2LogicalActionOutcomesV1(BaseModel):
    action_count: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)
    fallback_count: int = Field(default=0, ge=0)
    canceled_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)


class AdminP2LineupViolationV1(BaseModel):
    code: str
    severity: Literal["warning", "error"]
    count: int
    limit: int
    seat_numbers: list[int]


class AdminP2LineupQualityV1(BaseModel):
    policy_mode: Literal["observe", "repair", "enforce"] | None
    was_repaired: bool | None
    is_blocked: bool | None
    style_bucket_count: int | None
    required_style_bucket_count: int | None
    violations: list[AdminP2LineupViolationV1]


class AdminP2QualityGateV1(BaseModel):
    gate: str
    status: AdminP2GateStatus
    code: str
    threshold: str | None
    actual: str | None


class AdminPublicOutcomeEventV1(BaseModel):
    schema_version: Literal[1]
    round_number: int
    event_id: str
    sequence: int
    kind: Literal[
        "night_death",
        "hunter_shot",
        "self_explosion",
        "exile",
        "idiot_reveal",
        "badge_transferred",
        "badge_lost",
    ]
    actor_player_id: str | None
    target_player_id: str | None
    outcome: str
    caused_by_event_id: str | None
    occurred_phase: str


class AdminRunP2DiagnosticsV1(BaseModel):
    schema_version: Literal[1] = 1
    data_status: AdminP2DataStatus
    performance: AdminP2PerformanceV1
    speech_quality: AdminP2SpeechQualityV1
    choice_normalization: AdminP2ChoiceNormalizationV1
    provider_attempt_outcomes: AdminP2ProviderAttemptOutcomesV1 = Field(
        default_factory=AdminP2ProviderAttemptOutcomesV1
    )
    logical_action_outcomes: AdminP2LogicalActionOutcomesV1 = Field(
        default_factory=AdminP2LogicalActionOutcomesV1
    )


class AdminGameP2QualityV1(BaseModel):
    schema_version: Literal[1] = 1
    data_status: AdminP2DataStatus
    lineup_quality: AdminP2LineupQualityV1
    speech_quality: AdminP2SpeechQualityV1
    performance: AdminP2PerformanceV1
    choice_normalization: AdminP2ChoiceNormalizationV1
    provider_attempt_outcomes: AdminP2ProviderAttemptOutcomesV1 = Field(
        default_factory=AdminP2ProviderAttemptOutcomesV1
    )
    logical_action_outcomes: AdminP2LogicalActionOutcomesV1 = Field(
        default_factory=AdminP2LogicalActionOutcomesV1
    )
    public_outcomes: list[AdminPublicOutcomeEventV1]
    public_outcome_summary_mismatch_count: int
    quality_gates: list[AdminP2QualityGateV1]
