from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VirtualPlayerProfile(Base):
    __tablename__ = "virtual_player_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    personality_id: Mapped[str] = mapped_column(String(40), nullable=False, default="balanced")
    personality_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance_id: Mapped[str] = mapped_column(String(40), nullable=False, default="default")
    avatar_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar_image_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar_image_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar_image_mime: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    avatar_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("player_avatar_assets.id"),
        nullable=True,
        default=None,
    )
    short_description: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    background_story: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaking_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    catchphrases: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )
    strategy_profile: Mapped[str] = mapped_column(String(40), nullable=False, default="balanced")
    risk_tolerance: Mapped[int] = mapped_column(nullable=False, default=3)
    bluffing_tendency: Mapped[int] = mapped_column(nullable=False, default=3)
    trust_tendency: Mapped[int] = mapped_column(nullable=False, default=3)
    leadership_tendency: Mapped[int] = mapped_column(nullable=False, default=3)
    talkativeness: Mapped[int] = mapped_column(nullable=False, default=3)
    example_messages: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        nullable=False,
        default=list,
    )
    display_order: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    favorite: Mapped[bool] = mapped_column(nullable=False, default=False)
    tags: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
