from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, JSON, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JudgeVoiceAssetRecord(Base):
    __tablename__ = "judge_voice_assets"
    __table_args__ = (Index("ix_judge_voice_assets_category_id", "category", "id"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    seat_number: Mapped[int | None] = mapped_column(nullable=True)
    audio_format: Mapped[str] = mapped_column(String(20), nullable=False)
    sample_rate: Mapped[int] = mapped_column(nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    subtitle_timings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="migrated")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
