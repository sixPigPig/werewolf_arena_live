from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GameSessionRecord(Base):
    __tablename__ = "game_sessions"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    winner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    round_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    rule_set_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rule_set_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "rule_set_revisions.id",
            name="fk_game_sessions_rule_set_revision_id_rule_set_revisions",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    rule_set_revision_no: Mapped[int | None] = mapped_column(nullable=True)
    rule_set_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_set: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resumable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    liveness_experience_revision: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )
    liveness_experience_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )


class GameReplayPayload(Base):
    __tablename__ = "game_replay_payloads"

    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("game_sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    logs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ActorMindSnapshotRecord(Base):
    __tablename__ = "actor_mind_snapshots"
    __table_args__ = (Index("ix_actor_mind_snapshots_session", "session_id"),)

    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("game_sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    actor: Mapped[str] = mapped_column(String(120), primary_key=True)
    schema_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    revision: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_source_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_source_event_id: Mapped[int | None] = mapped_column(nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SpeechTurnReceiptRecord(Base):
    __tablename__ = "speech_turn_receipts"
    __table_args__ = (
        CheckConstraint(
            "speech_stream_mode = 'segments_v2'",
            name="ck_speech_turn_receipts_stream_mode",
        ),
        Index("ix_speech_turn_receipts_session_status", "session_id", "status"),
    )

    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("game_sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    action_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    round: Mapped[int | None] = mapped_column(nullable=True)
    phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    speech_stream_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="segments_v2",
        server_default="segments_v2",
    )
    experience_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    scene_packet_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    planner_request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    renderer_attempts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    accepted_renderer_request_id: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    final_segment_index: Mapped[int | None] = mapped_column(nullable=True)
    sealed_source_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sealed_source_event_id: Mapped[int | None] = mapped_column(nullable=True)
    final_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    delivery_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    actor_mind_revision_before: Mapped[int | None] = mapped_column(nullable=True)
    actor_mind_revision_after: Mapped[int | None] = mapped_column(nullable=True)
    actor_mind_delta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SpeechTurnSegmentRecord(Base):
    __tablename__ = "speech_turn_segments"
    __table_args__ = (
        ForeignKeyConstraint(
            ("session_id", "action_id"),
            ("speech_turn_receipts.session_id", "speech_turn_receipts.action_id"),
            ondelete="CASCADE",
        ),
        UniqueConstraint("segment_id", name="uq_speech_turn_segments_segment_id"),
        UniqueConstraint("presentation_id", name="uq_speech_turn_segments_presentation_id"),
        Index("ix_speech_turn_segments_source", "source_run_id", "source_event_id"),
    )

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    action_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    segment_index: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[str] = mapped_column(String(40), nullable=False)
    speech_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_event_id: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    presentation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VoicePlaybackObservationRecord(Base):
    __tablename__ = "voice_playback_observations"
    __table_args__ = (
        Index("ix_voice_playback_observations_session", "session_id"),
        Index("ix_voice_playback_observations_updated_at", "updated_at"),
    )

    playback_session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    utterance_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("voice_utterances.utterance_id", ondelete="CASCADE"),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    speech_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    server_terminal_status: Mapped[str] = mapped_column(String(24), nullable=False)
    client_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    played_ms: Mapped[int | None] = mapped_column(nullable=True)
    playback_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    playback_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ack_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


Index(
    "ix_game_sessions_created_at_session_id_desc",
    GameSessionRecord.created_at.desc(),
    GameSessionRecord.session_id.desc(),
)
Index(
    "ix_game_sessions_status_created_at_session_id_desc",
    GameSessionRecord.status,
    GameSessionRecord.created_at.desc(),
    GameSessionRecord.session_id.desc(),
)
Index(
    "ix_game_sessions_rule_set_id_created_at_session_id_desc",
    GameSessionRecord.rule_set_id,
    GameSessionRecord.created_at.desc(),
    GameSessionRecord.session_id.desc(),
)
