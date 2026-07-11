from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuntimeWorkerRecord(Base):
    __tablename__ = "runtime_workers"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    worker_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scans_total: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    recoveries_resumed_total: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    recoveries_canceled_total: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    recoveries_failed_total: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    errors_total: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


Index(
    "ix_runtime_workers_type_heartbeat_desc",
    RuntimeWorkerRecord.worker_type,
    RuntimeWorkerRecord.heartbeat_at.desc(),
)
