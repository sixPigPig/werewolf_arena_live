from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


V2LiveState = Literal[
    "waiting_to_start",
    "ready",
    "generating",
    "broadcasting",
    "finalizing",
    "awaiting_observation",
    "canceled",
    "failed",
]
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
    sheriff_badge_bomb_policy: str | None = Field(default=None, max_length=80)
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
    model: str | None = Field(default=None, max_length=120)
    personality_id: str | None = Field(default=None, max_length=80)
    personality: str | None = Field(default=None, max_length=4000)
    appearance_id: str | None = Field(default=None, max_length=80)
    avatar_prompt: str | None = Field(default=None, max_length=1000)
    avatar_image_url: str | None = Field(default=None, max_length=2000)
    avatar_asset_id: str | None = Field(default=None, max_length=120)
    catchphrases: list[str] | None = Field(default=None, max_length=20)
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
    rule_set: V2LobbyRuleSnapshot
    rule_set_revision_id: str | None = Field(default=None, max_length=80)
    seed: int | None = None
    max_rounds: int = Field(ge=1, le=20)
    player_configs: list[V2LobbyPlayerSnapshot] = Field(min_length=1, max_length=24)
    lineup_quality_report: V2LobbyQualitySnapshot
    allow_lineup_quality_warnings: bool = False

    @model_validator(mode="after")
    def validate_complete_lineup(self) -> "V2LobbyCreateSnapshot":
        expected_seats = set(range(1, self.rule_set.player_count + 1))
        seats = [item.seat for item in self.player_configs]
        profile_ids = [item.profile_id for item in self.player_configs]
        if set(seats) != expected_seats or len(seats) != len(set(seats)):
            raise ValueError("player_configs must cover every rule seat exactly once")
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("player_configs must use unique profiles")
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
    lobby_snapshot: V2LobbyCreateSnapshot | None = None

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


class AdminV2EventResponse(BaseModel):
    event_id: int
    record_seq: int
    run_id: str
    event_type: str
    payload_schema_version: int
    payload: dict[str, Any]
    created_at: datetime


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


class AdminV2ModelRequestResponse(BaseModel):
    attempt_id: str
    action_id: str
    run_id: str
    phase_id: str
    action_type: str
    actor_kind: str
    actor_id: str
    audience: str
    request_kind: str
    model_id: str | None
    model_provider: str | None
    judge_configuration_version: int | None
    status: Literal["running", "succeeded", "failed"]
    request_payload: dict[str, Any] | None
    input_source: Literal["persisted", "reconstructed", "unavailable"]
    raw_response: str | None
    parsed_output: dict[str, Any] | None
    output_source: Literal["persisted", "legacy_inferred", "unavailable"]
    provider_request_id: str | None
    first_token_ms: int | None
    completed_ms: int | None
    failure_kind: str | None
    failure_code: str | None
    started_at: datetime
    completed_at: datetime | None


class AdminV2GameDetailResponse(AdminV2GameListItem):
    rule_snapshot: dict[str, Any]
    players_snapshot: list[dict[str, Any]]
    judge_voice_snapshot: dict[str, Any]
    ability_snapshot: dict[str, Any]
    match_state: dict[str, Any] | None
    player_identities: list[V2GodViewPlayerIdentityResponse]
    runs: list[AdminV2RunResponse]
    events: list[AdminV2EventResponse]
    model_requests: list[AdminV2ModelRequestResponse]
    presentations: list[AdminV2PresentationResponse]
    voice_assets: list[AdminV2VoiceAssetResponse]
    player_states: list[dict[str, Any]]
    action_windows: list[dict[str, Any]]
    ability_instances: list[dict[str, Any]]
    ability_activations: list[dict[str, Any]]
    effect_intents: list[dict[str, Any]]
    knowledge_facts: list[dict[str, Any]]
