from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, func
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
