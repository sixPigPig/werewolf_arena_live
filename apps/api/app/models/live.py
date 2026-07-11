from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LiveRunRecord(Base):
    __tablename__ = "live_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued", index=True
    )
    villager_model: Mapped[str] = mapped_column(String(120), nullable=False)
    werewolf_model: Mapped[str] = mapped_column(String(120), nullable=False)
    seed: Mapped[int | None] = mapped_column(nullable=True)
    max_rounds: Mapped[int] = mapped_column(nullable=False)
    rule_set_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_set: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    player_configs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    lineup_quality_warnings: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
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
    control_version: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
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


class VoiceUtteranceRecord(Base):
    __tablename__ = "voice_utterances"
    __table_args__ = (
        Index("ix_voice_utterances_run_source_event", "run_id", "source_event_id"),
        Index("ix_voice_utterances_run_status", "run_id", "status"),
    )

    utterance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_event_id: Mapped[int] = mapped_column(nullable=False)
    last_source_event_id: Mapped[int] = mapped_column(nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    speaker_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    speaker_name: Mapped[str] = mapped_column(String(120), nullable=False)
    speaker: Mapped[str] = mapped_column(String(160), nullable=False)
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
