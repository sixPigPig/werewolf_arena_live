from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LivenessRolloutConfigRecord(Base):
    __tablename__ = "liveness_rollout_configs"
    __table_args__ = (
        CheckConstraint(
            "revision >= 1",
            name="ck_liveness_rollout_configs_revision_positive",
        ),
        CheckConstraint(
            "treatment_percent >= 0 AND treatment_percent <= 100",
            name="ck_liveness_rollout_configs_treatment_percent",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    experience_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    experiment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    treatment_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    )
