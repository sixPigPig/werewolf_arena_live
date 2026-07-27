from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JudgeConfigurationRecord(Base):
    __tablename__ = "judge_configurations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    voice_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="fixed",
        server_default="fixed",
    )
    tts_speaker: Mapped[str] = mapped_column(String(160), nullable=False)
    random_tts_speakers: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
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
