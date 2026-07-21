from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LiveRunRecord(Base):
    __tablename__ = "live_runs"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "attempt_no",
            name="uq_live_runs_session_attempt_no",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued", index=True
    )
    villager_model: Mapped[str] = mapped_column(String(120), nullable=False)
    werewolf_model: Mapped[str] = mapped_column(String(120), nullable=False)
    seed: Mapped[int | None] = mapped_column(nullable=True)
    max_rounds: Mapped[int] = mapped_column(nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("live_runs.run_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    resume_from_round: Mapped[int | None] = mapped_column(nullable=True)
    attempt_no: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    rule_set_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_set_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "rule_set_revisions.id",
            name="fk_live_runs_rule_set_revision_id_rule_set_revisions",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    rule_set_revision_no: Mapped[int | None] = mapped_column(nullable=True)
    rule_set_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_set: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    player_configs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    lineup_quality_warnings: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    lineup_quality_report: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    p2_diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    liveness_experience_revision: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )
    liveness_experience_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    winner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    worker_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    control_version: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    fence_token: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    recovery_attempts: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    recovery_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_not_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    recovery_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )


Index(
    "ix_live_runs_session_created_run_desc",
    LiveRunRecord.session_id,
    LiveRunRecord.created_at.desc(),
    LiveRunRecord.run_id.desc(),
)
Index(
    "uq_live_runs_active_session",
    LiveRunRecord.session_id,
    unique=True,
    postgresql_where=LiveRunRecord.status.in_(("queued", "running")),
    sqlite_where=LiveRunRecord.status.in_(("queued", "running")),
)
Index(
    "ix_live_runs_updated_at_run_id_desc",
    LiveRunRecord.updated_at.desc(),
    LiveRunRecord.run_id.desc(),
)
Index(
    "ix_live_runs_created_at_run_id_desc",
    LiveRunRecord.created_at.desc(),
    LiveRunRecord.run_id.desc(),
)
Index(
    "ix_live_runs_status_updated_at_run_id_desc",
    LiveRunRecord.status,
    LiveRunRecord.updated_at.desc(),
    LiveRunRecord.run_id.desc(),
)
Index(
    "ix_live_runs_rule_set_id_updated_at_run_id_desc",
    LiveRunRecord.rule_set_id,
    LiveRunRecord.updated_at.desc(),
    LiveRunRecord.run_id.desc(),
)


class LiveEventRecord(Base):
    __tablename__ = "live_events"
    __table_args__ = (Index("ix_live_events_run_id_event_id", "run_id", "event_id"),)

    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("live_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    round: Mapped[int | None] = mapped_column(nullable=True)
    phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublicLiveEventRecord(Base):
    __tablename__ = "public_live_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ("run_id", "source_event_id"),
            ("live_events.run_id", "live_events.event_id"),
            ondelete="CASCADE",
        ),
        Index("ix_public_live_events_run_id_event_id", "run_id", "event_id"),
        Index("ix_public_live_events_session_id", "session_id"),
    )

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[int] = mapped_column(primary_key=True)
    source_event_id: Mapped[int] = mapped_column(nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    round: Mapped[int | None] = mapped_column(nullable=True)
    phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    projection_version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GodViewLiveEventRecord(Base):
    __tablename__ = "god_view_live_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ("run_id", "source_event_id"),
            ("live_events.run_id", "live_events.event_id"),
            ondelete="CASCADE",
        ),
        Index("ix_god_view_live_events_run_id_event_id", "run_id", "event_id"),
        Index("ix_god_view_live_events_session_id", "session_id"),
    )

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[int] = mapped_column(primary_key=True)
    source_event_id: Mapped[int] = mapped_column(nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    round: Mapped[int | None] = mapped_column(nullable=True)
    phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    projection_version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VoiceMaterializationJobRecord(Base):
    __tablename__ = "voice_materialization_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ("run_id", "source_event_id"),
            ("live_events.run_id", "live_events.event_id"),
            ondelete="CASCADE",
        ),
        Index(
            "ix_voice_materialization_jobs_claim",
            "status",
            "not_before",
            "lease_expires_at",
        ),
        Index("ix_voice_materialization_jobs_session", "session_id"),
        Index(
            "ix_voice_materialization_jobs_audience_status",
            "audience",
            "status",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_event_id: Mapped[int] = mapped_column(primary_key=True)
    speaker_kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False)
    audience: Mapped[str] = mapped_column(
        String(32), nullable=False, default="player_public", server_default="player_public"
    )
    speaker: Mapped[str | None] = mapped_column(String(160), nullable=True)
    effective_delivery: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    effective_context_texts: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    voice_config_version: Mapped[int | None] = mapped_column(nullable=True)
    delivery_mapping_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tts_request_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    not_before: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class VoiceUtteranceRecord(Base):
    __tablename__ = "voice_utterances"
    __table_args__ = (
        Index("ix_voice_utterances_run_source_event", "run_id", "source_event_id"),
        Index("ix_voice_utterances_run_status", "run_id", "status"),
        Index("ix_voice_utterances_session_audience", "session_id", "audience"),
    )

    utterance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    audience: Mapped[str] = mapped_column(
        String(32), nullable=False, default="player_public", server_default="player_public"
    )
    source_event_id: Mapped[int] = mapped_column(nullable=False)
    last_source_event_id: Mapped[int] = mapped_column(nullable=False)
    presentation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    action_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    speech_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    segment_id: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    segment_index: Mapped[int | None] = mapped_column(nullable=True)
    segment_final: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    speaker_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    speaker_name: Mapped[str] = mapped_column(String(120), nullable=False)
    speaker: Mapped[str] = mapped_column(String(160), nullable=False)
    effective_delivery: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    effective_context_texts: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    voice_config_version: Mapped[int | None] = mapped_column(nullable=True)
    delivery_mapping_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tts_request_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    audio_format: Mapped[str] = mapped_column(String(20), nullable=False)
    sample_rate: Mapped[int] = mapped_column(nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending", index=True
    )
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    tts_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_audio_chunk_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    subtitle_timings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceAudioChunkRecord(Base):
    __tablename__ = "voice_audio_chunks"

    utterance_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("voice_utterances.utterance_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_index: Mapped[int] = mapped_column(primary_key=True)
    audio: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    byte_length: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
