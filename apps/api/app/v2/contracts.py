from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import TypedDict


V2LiveState = Literal[
    "waiting_to_start",
    "ready",
    "generating",
    "broadcasting",
    "finalizing",
    "awaiting_observation",
    "paused_model_error",
    "canceled",
    "failed",
]
V2RequestedAudioMode = Literal["tts", "text_only"]
V2AudioMode = Literal["tts", "text_only", "legacy_unknown"]
V2MatchStatus = Literal["waiting", "running", "completed", "failed", "canceled"]
V2ExecutionState = Literal["unowned", "owned", "stale", "stopped"]
V2GamePhaseId = str
V2GamePhaseState = str
V2DirectorSceneKind = Literal[
    "opening",
    "public_stage",
    "nightfall",
    "werewolves",
    "guard",
    "seer",
    "witch",
    "hunter",
    "dawn",
    "terminal",
]


class V2ApiMetaResponse(BaseModel):
    api_version: Literal["v2"] = "v2"
    status: Literal["realtime_complete_match"] = "realtime_complete_match"


class V2LobbyRoleSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=1, le=24)
    team: str | None = Field(default=None, max_length=40)
    model_group: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=40)


class V2LobbyWerewolfAttackPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    resolution: Literal[
        "plurality_rotating_tiebreak",
        "plurality_seeded_random",
        "unanimous_no_attack",
    ]
    allow_no_attack: bool
    allow_wolf_target: bool


class V2LobbyRuleSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    player_count: int = Field(ge=1, le=24)
    roles: list[V2LobbyRoleSnapshot] = Field(min_length=1, max_length=24)
    night_actions: list[str] | None = Field(default=None, max_length=40)
    day_actions: list[str] | None = Field(default=None, max_length=40)
    win_condition: str | None = Field(default=None, max_length=500)
    reveal_policy: str | None = Field(default=None, max_length=80)
    complexity: str | None = Field(default=None, max_length=80)
    estimated_duration: str | None = Field(default=None, max_length=80)
    role_summary: str | None = Field(default=None, max_length=500)
    sheriff_enabled: bool | None = None
    sheriff_vote_weight: float | None = Field(default=None, ge=1, le=3)
    speech_policy: str | None = Field(default=None, max_length=80)
    speech_rounds: int | None = Field(default=None, ge=1, le=20)
    rule_tags: list[str] | None = Field(default=None, max_length=20)
    werewolf_self_explosion_enabled: bool | None = None
    exile_last_words_enabled: bool | None = None
    first_night_last_words_enabled: bool | None = None
    sheriff_badge_bomb_policy: str | None = Field(default=None, max_length=80)
    werewolf_attack_policy: V2LobbyWerewolfAttackPolicy | None = None
    revision_id: str | None = Field(default=None, max_length=80)
    revision_no: int | None = Field(default=None, ge=1)
    schema_version: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    is_default: bool | None = None

    @model_validator(mode="after")
    def validate_role_composition(self) -> "V2LobbyRuleSnapshot":
        role_names = [item.role for item in self.roles]
        if len(role_names) != len(set(role_names)):
            raise ValueError("rule roles must be unique")
        if sum(item.count for item in self.roles) != self.player_count:
            raise ValueError("rule role count must match player count")
        return self


class V2LobbyPlayerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int = Field(ge=1, le=24)
    profile_id: str = Field(min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=80)
    model_provider: str | None = Field(default=None, min_length=1, max_length=32)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    personality_id: str | None = Field(default=None, max_length=80)
    personality: str | None = Field(default=None, max_length=4000)
    appearance_id: str | None = Field(default=None, max_length=80)
    avatar_image_url: str | None = Field(default=None, max_length=2000)
    avatar_asset_id: str | None = Field(default=None, max_length=120)
    strategy_profile: str | None = Field(default=None, max_length=80)
    tts_speaker: str | None = Field(default=None, max_length=160)
    tts_dialect: str | None = Field(default=None, max_length=80)
    base_delivery_mood: str | None = Field(default=None, max_length=80)
    base_delivery_intensity: str | None = Field(default=None, max_length=80)
    base_delivery_pace: str | None = Field(default=None, max_length=80)
    base_delivery_instruction: str | None = Field(default=None, max_length=1000)
    voice_enabled: bool | None = None
    voice_config_version: int | None = Field(default=None, ge=1)
    tags: list[str] | None = Field(default=None, max_length=20)


class V2LobbyQualityViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=120)
    severity: Literal["warning", "error"]
    key: str = Field(min_length=1, max_length=120)
    count: int = Field(ge=0)
    limit: int = Field(ge=0)
    seat_numbers: list[int] = Field(default_factory=list, max_length=24)


class V2LobbyQualitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    policy_mode: Literal["observe", "repair", "enforce"]
    player_count: int = Field(ge=1, le=24)
    configured_count: int = Field(ge=0, le=24)
    is_blocked: bool
    was_repaired: bool
    style_bucket_count: int = Field(ge=0)
    required_style_bucket_count: int = Field(ge=0)
    violations: list[V2LobbyQualityViolation] = Field(default_factory=list, max_length=50)


class V2LobbyCreateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    model_binding_mode: Literal["explicit_snapshot", "profile_library"] = "explicit_snapshot"
    rule_set: V2LobbyRuleSnapshot
    rule_set_revision_id: str | None = Field(default=None, max_length=80)
    seed: int | None = None
    max_rounds: int = Field(ge=1, le=20)
    player_configs: list[V2LobbyPlayerSnapshot] = Field(min_length=1, max_length=24)
    lineup_quality_report: V2LobbyQualitySnapshot
    allow_lineup_quality_warnings: bool = False

    @model_validator(mode="after")
    def validate_complete_lineup(self) -> "V2LobbyCreateSnapshot":
        if self.model_binding_mode == "profile_library" and (
            self.rule_set_revision_id is None or self.rule_set.revision_id is None
        ):
            raise ValueError("profile library snapshots require matching rule revision identifiers")
        if (
            self.rule_set.revision_id is not None
            and self.rule_set_revision_id != self.rule_set.revision_id
        ):
            raise ValueError("rule_set_revision_id must match rule_set.revision_id")
        expected_seats = set(range(1, self.rule_set.player_count + 1))
        seats = [item.seat for item in self.player_configs]
        profile_ids = [item.profile_id for item in self.player_configs]
        if set(seats) != expected_seats or len(seats) != len(set(seats)):
            raise ValueError("player_configs must cover every rule seat exactly once")
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("player_configs must use unique profiles")
        if self.model_binding_mode == "explicit_snapshot" and any(
            item.model_provider is None or item.model is None for item in self.player_configs
        ):
            raise ValueError("explicit snapshots require player model bindings")
        report = self.lineup_quality_report
        if report.player_count != self.rule_set.player_count or report.configured_count != len(
            self.player_configs
        ):
            raise ValueError("lineup quality report does not match player snapshot")
        if report.is_blocked and not self.allow_lineup_quality_warnings:
            raise ValueError("blocked lineup requires explicit warning override")
        return self


class V2GameCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="Live V2 实时对局", min_length=1, max_length=120)
    audio_mode: V2RequestedAudioMode | None = None
    lobby_snapshot: V2LobbyCreateSnapshot

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title cannot be blank")
        return normalized


class V2ActorResponse(BaseModel):
    kind: Literal["judge", "player"]
    id: str


class V2GamePhaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_seq: int = Field(ge=0)
    phase_id: V2GamePhaseId
    phase_state: V2GamePhaseState


class V2MatchStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_no: int = Field(ge=1, le=20)
    sheriff_player_id: str | None = Field(default=None, max_length=80)
    sheriff_badge_state: Literal["disabled", "pending", "held", "destroyed"]
    winner: Literal["villagers", "werewolves"] | None = None


class V2CurrentPresentationResponse(BaseModel):
    action_id: str
    presentation_seq: int = Field(ge=1)
    presentation_id: str
    phase_id: str
    actor: V2ActorResponse
    speech_id: str
    segment_index: int = Field(ge=0)
    subtitle_text: str
    join_sample_cursor: int = Field(ge=0)


class V2PublicPlayerSeatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int = Field(ge=1, le=24)
    player_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=2000)
    alive: bool = True


class V2PublicRoleCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=1, le=24)


class V2PublicRuleSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    player_count: int = Field(ge=1, le=24)
    roles: list[V2PublicRoleCountResponse] = Field(min_length=1, max_length=24)
    max_rounds: int = Field(ge=1, le=20)
    sheriff_enabled: bool | None
    werewolf_self_explosion_enabled: bool | None
    exile_last_words_enabled: bool | None
    first_night_last_words_enabled: bool | None


class V2PublicRoleAssignmentStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["sealed", "unavailable"]
    assigned_count: int = Field(ge=0, le=24)

    @model_validator(mode="after")
    def validate_state_count(self) -> "V2PublicRoleAssignmentStatusResponse":
        if self.state == "sealed" and self.assigned_count == 0:
            raise ValueError("sealed role assignments require players")
        if self.state == "unavailable" and self.assigned_count != 0:
            raise ValueError("unavailable role assignments cannot contain players")
        return self


class V2LiveSnapshotResponse(BaseModel):
    protocol_version: Literal[1] = 1
    type: Literal["live.snapshot"] = "live.snapshot"
    api_version: Literal["v2"] = "v2"
    audience: Literal["player_public"]
    game_id: str
    run_id: str
    live_state: V2LiveState
    audio_mode: V2AudioMode
    match_status: V2MatchStatus
    execution_state: V2ExecutionState
    winner: Literal["villagers", "werewolves"] | None
    completion_reason: str | None
    completed_at: datetime | None
    game_phase: V2GamePhaseResponse
    match_state: V2MatchStateResponse | None
    latest_presentation_seq: int = Field(ge=0)
    server_time: datetime
    public_rule: V2PublicRuleSnapshotResponse | None
    public_players: list[V2PublicPlayerSeatResponse] = Field(max_length=24)
    public_role_assignment: V2PublicRoleAssignmentStatusResponse
    current_presentation: V2CurrentPresentationResponse | None


class V2GodViewPlayerIdentityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int = Field(ge=1, le=24)
    player_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=2000)
    role: str = Field(min_length=1, max_length=80)
    team: str | None = Field(default=None, max_length=40)
    alive: bool = True
    death_cause: str | None = Field(default=None, max_length=40)


class V2DirectorSceneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_kind: V2DirectorSceneKind
    action_id: str | None = Field(default=None, max_length=40)
    action_type: str | None = Field(default=None, max_length=120)
    ability_id: str | None = Field(default=None, max_length=120)
    actor_player_id: str | None = Field(default=None, max_length=80)


class V2DirectorLiveSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1
    type: Literal["director.live_snapshot"] = "director.live_snapshot"
    api_version: Literal["v2"] = "v2"
    audience: Literal["spectator_directed"] = "spectator_directed"
    game_id: str
    run_id: str
    live_state: V2LiveState
    audio_mode: V2AudioMode
    match_status: V2MatchStatus
    execution_state: V2ExecutionState
    winner: Literal["villagers", "werewolves"] | None
    completion_reason: str | None
    completed_at: datetime | None
    game_phase: V2GamePhaseResponse
    match_state: V2MatchStateResponse | None
    latest_presentation_seq: int = Field(ge=0)
    server_time: datetime
    rule: V2PublicRuleSnapshotResponse | None
    players: list[V2GodViewPlayerIdentityResponse] = Field(min_length=1, max_length=24)
    current_scene: V2DirectorSceneResponse
    current_presentation: V2CurrentPresentationResponse | None


class V2GodViewIdentitySnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1
    type: Literal["god_view.identity_snapshot"] = "god_view.identity_snapshot"
    api_version: Literal["v2"] = "v2"
    audience: Literal["spectator_god_view"] = "spectator_god_view"
    game_id: str
    run_id: str
    live_state: V2LiveState
    audio_mode: V2AudioMode
    match_status: V2MatchStatus
    execution_state: V2ExecutionState
    winner: Literal["villagers", "werewolves"] | None
    completion_reason: str | None
    completed_at: datetime | None
    game_phase: V2GamePhaseResponse
    match_state: V2MatchStateResponse | None
    server_time: datetime
    rule: V2PublicRuleSnapshotResponse | None
    players: list[V2GodViewPlayerIdentityResponse] = Field(min_length=1, max_length=24)


class V2GodViewLiveSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1
    type: Literal["god_view.live_snapshot"] = "god_view.live_snapshot"
    api_version: Literal["v2"] = "v2"
    audience: Literal["spectator_god_view"] = "spectator_god_view"
    game_id: str
    run_id: str
    live_state: V2LiveState
    audio_mode: V2AudioMode
    match_status: V2MatchStatus
    execution_state: V2ExecutionState
    winner: Literal["villagers", "werewolves"] | None
    completion_reason: str | None
    completed_at: datetime | None
    game_phase: V2GamePhaseResponse
    match_state: V2MatchStateResponse | None
    latest_presentation_seq: int = Field(ge=0)
    server_time: datetime
    rule: V2PublicRuleSnapshotResponse | None
    players: list[V2GodViewPlayerIdentityResponse] = Field(min_length=1, max_length=24)
    current_presentation: V2CurrentPresentationResponse | None


class V2GameCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: str
    run_id: str
    status: Literal["waiting_to_start"]
    audio_mode: V2RequestedAudioMode
    snapshot_url: str
    websocket_url: str
    director_snapshot_url: str
    director_websocket_url: str
    god_view_snapshot_url: str
    god_view_websocket_url: str
    god_view_access_token: str = Field(min_length=32, max_length=128)


class AdminV2GameListItem(BaseModel):
    game_id: str
    title: str
    status: str
    current_run_id: str
    record_schema_version: int
    last_record_seq: int
    last_presentation_seq: int
    phase_seq: int
    phase_id: str
    phase_state: str
    audio_mode: V2AudioMode
    match_status: V2MatchStatus
    execution_state: V2ExecutionState
    winner: Literal["villagers", "werewolves"] | None
    completion_reason: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminV2Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class AdminV2GameListResponse(BaseModel):
    items: list[AdminV2GameListItem]
    pagination: AdminV2Pagination


class AdminV2RunResponse(BaseModel):
    run_id: str
    attempt_no: int
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    stop_requested_at: datetime | None
    worker_id: str | None
    worker_heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    fence_token: int = Field(ge=0)


class AdminV2GameControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason must contain at least 3 characters")
        return normalized


class AdminV2GameControlResponse(BaseModel):
    action: Literal["stop"]
    game_id: str
    run_id: str
    run_status: str
    stop_requested_at: datetime
    replayed: bool


class AdminV2ModelActionRetryResponse(BaseModel):
    action: Literal["retry_model_action"]
    game_id: str
    run_id: str
    run_status: str
    action_id: str
    replayed: bool


class AdminV2EventResponse(BaseModel):
    event_id: int
    record_seq: int
    run_id: str
    event_type: str
    payload_schema_version: int
    payload: dict[str, Any]
    created_at: datetime


class AdminV2EventPageResponse(BaseModel):
    items: list[AdminV2EventResponse]
    after_record_seq: int
    next_after_record_seq: int
    has_more: bool


class AdminV2PresentationResponse(BaseModel):
    presentation_seq: int
    presentation_id: str
    action_id: str | None
    activation_id: str | None
    phase_id: str
    actor_kind: str
    actor_id: str
    audience: str
    speech_id: str
    segment_index: int
    source_event_id: int
    state: str
    subtitle_text: str
    voice_asset_id: str | None
    audio_duration_ms: int | None
    created_at: datetime
    closed_at: datetime | None


class AdminV2VoiceAssetResponse(BaseModel):
    voice_asset_id: str
    action_id: str
    activation_id: str | None
    audience: str
    presentation_id: str
    speech_id: str
    segment_index: int
    state: str
    mime_type: str
    sample_rate: int
    channels: int
    sample_count: int | None
    duration_ms: int | None
    pcm_sha256: str | None
    size_bytes: int | None
    audio_url: str | None
    created_at: datetime
    completed_at: datetime | None


class AdminV2OutputEnforcementResponse(BaseModel):
    requested: str | None
    actual: str | None
    schema_name: str | None
    schema_version: int | None


class AdminV2ProviderUsageResponse(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    cached_input_tokens: int


class AdminV2FailureEpisodeEventRefResponse(BaseModel):
    event_type: str
    event_id: int | str | None
    record_seq: int


class AdminV2ModelRequestSummaryResponse(BaseModel):
    attempt_id: str
    decision_family_id: str | None
    retry_scope: Literal[
        "action",
        "same_action",
        "batch_initial",
        "batch_recovery",
        "operator_retry",
    ]
    vote_batch_stage: str | None
    automatic_machine_format_attempt_count: int | None
    automatic_machine_format_budget: int | None
    prior_output_budget_failures: int | None
    output_budget_failure_count: int | None
    automatic_output_budget_attempt_count: int | None
    automatic_output_budget_budget: int | None
    attempt_no: int
    cycle_attempt_no: int
    retry_cycle: int
    max_attempts: int
    retry_of_attempt_id: str | None
    record_seq: int
    last_record_seq: int
    action_id: str
    run_id: str
    phase_id: str
    action_type: str
    actor_kind: str
    actor_id: str
    audience: str
    stored_audience: str | None
    effective_audience: str
    audience_source: Literal[
        "event_contract",
        "event_contract_narrowed",
        "presentation",
        "legacy_event",
        "action_context",
        "legacy_unknown",
    ]
    request_kind: str
    model_id: str | None
    model_provider: str | None
    judge_configuration_version: int | None
    prompt_schema_version: int | None
    model_context_schema_version: int | None
    prompt_template_version: int | None
    model_view_selector_version: int | None
    prompt_projection: dict[str, Any] | None
    output_enforcement: AdminV2OutputEnforcementResponse | None
    status: Literal["running", "succeeded", "failed"]
    input_source: Literal["persisted", "reconstructed", "unavailable"]
    passive_observation_count: int
    output_source: Literal["persisted", "legacy_inferred", "unavailable"]
    provider_request_id: str | None
    model_generation_policy_contract_status: Literal["supported", "legacy_disabled"] | None
    model_generation_policy_schema_version: int | None
    model_generation_policy_classification_version: int | None
    model_generation_policy_enforcement: Literal["observe_only", "disabled"] | None
    model_generation_policy_reasoning_parameter_mode: (
        Literal["inherit_frozen_model_configuration"] | None
    )
    model_generation_policy_profile: (
        Literal[
            "strategic_full",
            "recoverable_public_speech",
            "isolated_auxiliary",
        ]
        | None
    )
    model_generation_policy_profile_source: (
        Literal[
            "explicit_action_profile",
            "default_profile",
            "legacy_missing_contract",
        ]
        | None
    )
    reasoning_only_timeout_ms: int | None
    timeout_max_attempts: int | None
    shadow_would_timeout: bool | None
    finish_reason: (
        Literal[
            "completed",
            "stop",
            "length",
            "max_output_tokens",
            "content_filter",
            "tool_calls",
            "unknown",
        ]
        | None
    )
    provider_usage: AdminV2ProviderUsageResponse | None
    usage_update_count: int | None
    usage_conflict_observed: bool | None
    usage_consistency: (
        Literal[
            "exact",
            "provider_total_mismatch",
            "unavailable",
        ]
        | None
    )
    queue_wait_ms: int | None
    provider_in_flight: int | None
    provider_concurrency_limit: int | None
    first_token_ms: int | None
    reasoning_only_elapsed_ms: int | None
    completed_ms: int | None
    reasoning_delta_count: int | None
    text_delta_count: int | None
    max_inter_delta_ms: int | None
    last_progress_ms: int | None
    failure_kind: str | None
    failure_code: str | None
    failure_category: str | None
    failure_impact: (
        Literal[
            "expected_control_flow",
            "user_visible_degradation",
            "operational_failure",
        ]
        | None
    )
    counts_as_failure: bool
    repair_kind: str | None
    application_validation_result: Literal["accepted", "rejected"] | None
    retryable: bool | None
    terminal: bool | None
    failure_stage: str | None
    exception_type: str | None
    errno: int | None
    http_status: int | None
    first_token_seen: bool | None
    response_headers_seen: bool | None
    response_headers: dict[str, str] | None
    first_token_kind: str | None
    first_visible_text_ms: int | None
    timeout_scope: str | None
    failure_elapsed_ms: int | None
    attempt_budget_ms: int | None
    action_budget_ms: int | None
    action_elapsed_ms: int | None
    action_remaining_ms: int | None
    effective_attempt_limit: int | None
    retry_delay_ms: int | None
    required_retry_window_ms: int | None
    automatic_retry_scheduled: bool | None
    automatic_retry_stop_reason: (
        Literal[
            "not_retryable",
            "decision_family_budget_exhausted",
            "attempt_limit_reached",
            "insufficient_action_budget",
        ]
        | None
    )
    failure_episode_id: str | None
    failure_resolution: (
        Literal[
            "automatic_retry_success",
            "technical_skip",
            "technical_false_fallback",
            "operator_pause",
            "isolated_action_failure",
            "run_failure",
            "run_canceled",
            "unresolved",
            "invariant_conflict",
            "legacy_unavailable",
        ]
        | None
    )
    failure_episode_source_attempt_ids: list[str] | None
    failure_episode_source_event_refs: list[AdminV2FailureEpisodeEventRefResponse] | None
    failure_episode_terminal_event_refs: list[AdminV2FailureEpisodeEventRefResponse] | None
    resolution_event_type: str | None
    resolution_event_id: int | None
    resolution_event_record_seq: int | None
    supporting_event_type: str | None
    supporting_event_id: int | None
    supporting_event_record_seq: int | None
    resolution_updated_at_record_seq: int | None
    failure_episode_invariant_errors: list[str] | None
    model_binding_failure_streak: int | None
    model_binding_health_status: Literal["healthy", "impaired", "degraded"] | None
    model_binding_recovered_after_failures: int | None
    started_at: datetime
    completed_at: datetime | None


class AdminV2ModelRequestResponse(AdminV2ModelRequestSummaryResponse):
    request_payload: dict[str, Any] | None
    expanded_known_events: dict[str, Any] | None
    known_events_expansion_status: Literal[
        "verified",
        "not_applicable",
        "unavailable",
        "invalid",
    ]
    raw_response: str | None
    parsed_output: dict[str, Any] | None
    passive_observations: list[dict[str, Any]]
    stream_reasoning: str | None
    stream_text: str | None
    stream_reasoning_character_count: int
    stream_text_character_count: int
    stream_estimated_reasoning_tokens: int | None
    stream_estimated_output_tokens: int | None
    stream_content_truncated: bool
    stream_progress_updated_at: datetime | None


class AdminV2ModelRequestPageResponse(BaseModel):
    items: list[AdminV2ModelRequestSummaryResponse]
    after_record_seq: int
    next_after_record_seq: int
    has_more: bool


class AdminV2GameDetailResponse(AdminV2GameListItem):
    rule_snapshot: dict[str, Any]
    players_snapshot: list[dict[str, Any]]
    judge_voice_snapshot: dict[str, Any]
    delivery_snapshot: dict[str, Any] | None
    ability_snapshot: dict[str, Any]
    match_state: dict[str, Any] | None
    player_identities: list[V2GodViewPlayerIdentityResponse]
    runs: list[AdminV2RunResponse]
    presentations: list[AdminV2PresentationResponse]
    voice_assets: list[AdminV2VoiceAssetResponse]
    player_states: list[dict[str, Any]]
    action_windows: list[dict[str, Any]]
    ability_instances: list[dict[str, Any]]
    ability_activations: list[dict[str, Any]]
    effect_intents: list[dict[str, Any]]
    knowledge_facts: list[dict[str, Any]]
