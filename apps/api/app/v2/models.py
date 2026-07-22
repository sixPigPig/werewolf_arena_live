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
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    players_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
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
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class V2GameRecordEvent(Base):
    __tablename__ = "v2_game_record_events"
    __table_args__ = (
        UniqueConstraint("game_id", "record_seq", name="uq_v2_game_events_record_seq"),
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
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
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
        Index("ix_v2_presentations_game_state", "game_id", "state"),
    )

    game_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    presentation_seq: Mapped[int] = mapped_column(primary_key=True)
    presentation_id: Mapped[str] = mapped_column(String(48), nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    run_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phase_id: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    speech_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    segment_index: Mapped[int] = mapped_column(nullable=False)
    source_event_id: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
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
        index=True,
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
