from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VirtualPlayerProfile(Base):
    __tablename__ = "virtual_player_profiles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_virtual_player_profiles_status",
        ),
        CheckConstraint("version >= 1", name="ck_virtual_player_profiles_version_positive"),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL AND deleted_at IS NULL) OR "
            "(status = 'published' AND published_at IS NOT NULL AND deleted_at IS NULL) OR "
            "(status = 'archived' AND published_at IS NOT NULL AND deleted_at IS NOT NULL)",
            name="ck_virtual_player_profiles_lifecycle_timestamps",
        ),
        CheckConstraint(
            "featured = false OR status = 'published'",
            name="ck_virtual_player_profiles_featured_published",
        ),
        Index(
            "ix_virtual_player_profiles_status_display_order",
            "status",
            "display_order",
            "id",
        ),
        Index(
            "ix_virtual_player_profiles_status_model",
            "status",
            "model",
        ),
        Index(
            "ix_virtual_player_profiles_status_personality",
            "status",
            "personality_id",
        ),
        Index(
            "ix_virtual_player_profiles_status_updated_at",
            "status",
            "updated_at",
            "id",
        ),
    )

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
    featured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    tags: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="published",
        server_default="published",
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True).evaluates_none(),
        nullable=True,
        server_default=func.now(),
    )
    published_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __mapper_args__ = {"version_id_col": version}
