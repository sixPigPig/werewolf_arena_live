from __future__ import annotations

from datetime import datetime

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
        CheckConstraint(
            "base_delivery_mood IN ('neutral', 'restrained', 'calm', 'confident', 'skeptical', "
            "'tense', 'frustrated', 'urgent', 'sad', 'excited', 'playful')",
            name="ck_virtual_player_profiles_delivery_mood",
        ),
        CheckConstraint(
            "base_delivery_intensity IN ('low', 'medium', 'high')",
            name="ck_virtual_player_profiles_delivery_intensity",
        ),
        CheckConstraint(
            "base_delivery_pace IN ('slow', 'natural', 'fast')",
            name="ck_virtual_player_profiles_delivery_pace",
        ),
        CheckConstraint(
            "gender IN ('female', 'male')",
            name="ck_virtual_player_profiles_gender",
        ),
        CheckConstraint(
            "tts_dialect IN ('', 'sichuan', 'shaanxi', 'northeast')",
            name="ck_virtual_player_profiles_tts_dialect",
        ),
        CheckConstraint(
            "voice_config_version >= 1",
            name="ck_virtual_player_profiles_voice_version_positive",
        ),
        CheckConstraint(
            "(status = 'published' AND display_order IS NOT NULL AND display_order >= 1) OR "
            "(status IN ('draft', 'archived') AND display_order IS NULL)",
            name="ck_virtual_player_profiles_display_order_lifecycle",
        ),
        Index(
            "ix_virtual_player_profiles_status_display_order",
            "status",
            "display_order",
            "id",
        ),
        Index(
            "uq_virtual_player_profiles_published_display_order",
            "display_order",
            unique=True,
        ),
        Index(
            "ix_virtual_player_profiles_status_model",
            "status",
            "model_provider",
            "model",
        ),
        ForeignKeyConstraint(
            ["model_provider", "model"],
            ["model_configurations.provider", "model_configurations.model_id"],
            name="fk_virtual_player_profiles_model_configuration",
            ondelete="RESTRICT",
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
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    personality_id: Mapped[str] = mapped_column(String(40), nullable=False, default="balanced")
    personality_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance_id: Mapped[str] = mapped_column(String(40), nullable=False, default="default")
    avatar_image_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar_image_mime: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    avatar_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("player_avatar_assets.id"),
        nullable=True,
        default=None,
    )
    short_description: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    background_story: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaking_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    gender: Mapped[str] = mapped_column(
        String(12), nullable=False, default="female", server_default="female"
    )
    tts_speaker: Mapped[str] = mapped_column(
        String(160), nullable=False, default="", server_default=""
    )
    tts_dialect: Mapped[str] = mapped_column(
        String(16), nullable=False, default="", server_default=""
    )
    base_delivery_mood: Mapped[str] = mapped_column(
        String(24), nullable=False, default="neutral", server_default="neutral"
    )
    base_delivery_intensity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium", server_default="medium"
    )
    base_delivery_pace: Mapped[str] = mapped_column(
        String(16), nullable=False, default="natural", server_default="natural"
    )
    base_delivery_instruction: Mapped[str] = mapped_column(
        String(240), nullable=False, default="", server_default=""
    )
    voice_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    voice_config_version: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default="1"
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
    display_order: Mapped[int | None] = mapped_column(nullable=True, default=None)
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
        default="draft",
        server_default="draft",
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True).evaluates_none(),
        nullable=True,
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
