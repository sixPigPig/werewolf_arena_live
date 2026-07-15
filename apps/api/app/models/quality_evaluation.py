from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GameQualityEvaluationRecord(Base):
    __tablename__ = "game_quality_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "evaluator_version",
            "source_revision",
            name="uq_game_quality_evaluation_revision",
        ),
        Index(
            "ix_game_quality_evaluations_claim",
            "status",
            "not_before",
            "lease_expires_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("game_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("live_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    evaluator_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    data_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="collecting", server_default="collecting"
    )
    verdict: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unavailable", server_default="unavailable"
    )
    safe_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    max_event_id: Mapped[int | None] = mapped_column(nullable=True)
    max_voice_source_event_id: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    not_before: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


Index(
    "ix_game_quality_evaluations_session_created",
    GameQualityEvaluationRecord.session_id,
    GameQualityEvaluationRecord.created_at.desc(),
    GameQualityEvaluationRecord.id.desc(),
)
Index(
    "ix_game_quality_evaluations_status_completed",
    GameQualityEvaluationRecord.status,
    GameQualityEvaluationRecord.completed_at.desc(),
)
Index(
    "ix_game_quality_evaluations_verdict_completed",
    GameQualityEvaluationRecord.verdict,
    GameQualityEvaluationRecord.completed_at.desc(),
)
