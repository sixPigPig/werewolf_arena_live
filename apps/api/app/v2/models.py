from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class V2GameRecord(Base):
    __tablename__ = "v2_game_records"

    game_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    current_run_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    record_schema_version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        server_default="1",
    )
    last_record_seq: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_presentation_seq: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    phase_seq: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    phase_id: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="legacy",
        server_default="legacy",
    )
    phase_state: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="legacy_frozen",
        server_default="legacy_frozen",
    )
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    players_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    judge_voice_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    ability_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ability_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )


class V2MatchState(Base):
    __tablename__ = "v2_match_states"

    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    round_no: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    sheriff_player_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sheriff_badge_state: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="disabled",
        server_default="disabled",
    )
    pre_sheriff_explosion_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    winner: Mapped[str | None] = mapped_column(String(24), nullable=True)
    completion_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class V2GameRun(Base):
    __tablename__ = "v2_game_runs"
    __table_args__ = (
        UniqueConstraint("game_id", "attempt_no", name="uq_v2_game_runs_game_attempt"),
    )

    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class V2GameControlRequest(Base):
    __tablename__ = "v2_game_control_requests"
    __table_args__ = (
        Index(
            "uq_v2_game_control_actor_key",
            "actor_user_id",
            "idempotency_key",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class V2GodViewAccessGrant(Base):
    __tablename__ = "v2_god_view_access_grants"

    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class V2RoleAssignmentBatch(Base):
    __tablename__ = "v2_role_assignment_batches"

    assignment_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    seed_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    assignment_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    player_count: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class V2RoleAssignment(Base):
    __tablename__ = "v2_role_assignments"
    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_v2_role_assignments_player"),
    )

    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    seat: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("v2_role_assignment_batches.assignment_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[str] = mapped_column(String(80), nullable=False)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    role_key: Mapped[str] = mapped_column(String(80), nullable=False)
    team: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class V2GameRecordEvent(Base):
    __tablename__ = "v2_game_record_events"
    __table_args__ = (
        UniqueConstraint("game_id", "record_seq", name="uq_v2_game_events_record_seq"),
        Index("ix_v2_game_events_run_id", "run_id"),
        Index("ix_v2_game_events_event_type", "event_type"),
        Index("ix_v2_game_events_game_created", "game_id", "created_at"),
    )

    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[int] = mapped_column(primary_key=True)
    record_seq: Mapped[int] = mapped_column(nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        server_default="1",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class V2LivePresentation(Base):
    __tablename__ = "v2_live_presentations"
    __table_args__ = (
        UniqueConstraint("presentation_id", name="uq_v2_presentations_id"),
        Index("ix_v2_presentations_action_id", "action_id"),
        Index("ix_v2_presentations_run_id", "run_id"),
        Index("ix_v2_presentations_speech_id", "speech_id"),
        Index("ix_v2_presentations_state", "state"),
        Index("ix_v2_presentations_voice_asset_id", "voice_asset_id"),
        Index("ix_v2_presentations_game_state", "game_id", "state"),
    )

    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    presentation_seq: Mapped[int] = mapped_column(primary_key=True)
    presentation_id: Mapped[str] = mapped_column(String(48), nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    activation_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    run_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_id: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    audience: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    speech_id: Mapped[str] = mapped_column(String(48), nullable=False)
    segment_index: Mapped[int] = mapped_column(nullable=False)
    source_event_id: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    subtitle_text: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle_timings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    voice_asset_id: Mapped[str | None] = mapped_column(
        String(48),
        ForeignKey("v2_voice_assets.voice_asset_id", ondelete="SET NULL"),
        nullable=True,
    )
    audio_asset_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    audio_mime_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    audio_duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class V2VoiceAsset(Base):
    __tablename__ = "v2_voice_assets"
    __table_args__ = (
        UniqueConstraint(
            "presentation_id",
            "speech_id",
            "segment_index",
            name="uq_v2_voice_assets_segment",
        ),
    )

    voice_asset_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    activation_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    audience: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    presentation_id: Mapped[str] = mapped_column(String(48), nullable=False)
    speech_id: Mapped[str] = mapped_column(String(48), nullable=False)
    segment_index: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(240), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    sample_rate: Mapped[int] = mapped_column(nullable=False)
    channels: Mapped[int] = mapped_column(nullable=False)
    sample_count: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    pcm_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class V2PlayerState(Base):
    __tablename__ = "v2_player_states"

    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    player_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    seat: Mapped[int] = mapped_column(nullable=False)
    alive: Mapped[bool] = mapped_column(nullable=False, default=True)
    death_cause: Mapped[str | None] = mapped_column(String(40), nullable=True)
    death_window_seq: Mapped[int | None] = mapped_column(nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class V2ActionWindow(Base):
    __tablename__ = "v2_action_windows"
    __table_args__ = (
        UniqueConstraint("game_id", "window_seq", name="uq_v2_action_windows_game_seq"),
    )

    window_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    window_seq: Mapped[int] = mapped_column(nullable=False)
    window_type: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    ability_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class V2AbilityInstance(Base):
    __tablename__ = "v2_ability_instances"
    __table_args__ = (
        UniqueConstraint("game_id", "ability_id", "owner_id", name="uq_v2_ability_instances_owner"),
    )

    ability_instance_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ability_id: Mapped[str] = mapped_column(String(80), nullable=False)
    ability_version: Mapped[int] = mapped_column(nullable=False)
    owner_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_role_key: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class V2AbilityActivation(Base):
    __tablename__ = "v2_ability_activations"
    __table_args__ = (
        UniqueConstraint(
            "game_id",
            "window_id",
            "ability_instance_id",
            "occurrence",
            name="uq_v2_ability_activations_occurrence",
        ),
    )

    activation_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    window_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("v2_action_windows.window_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ability_instance_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("v2_ability_instances.ability_instance_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    occurrence: Mapped[int] = mapped_column(nullable=False, default=1)
    action_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    decision_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    actor_player_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    skip_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    knowledge_fact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    decision: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class V2EffectIntent(Base):
    __tablename__ = "v2_effect_intents"

    effect_intent_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    window_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("v2_action_windows.window_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activation_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("v2_ability_activations.activation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    effect_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_player_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class V2KnowledgeFact(Base):
    __tablename__ = "v2_knowledge_facts"

    knowledge_fact_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_activation_id: Mapped[str | None] = mapped_column(
        String(48),
        ForeignKey("v2_ability_activations.activation_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    fact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
