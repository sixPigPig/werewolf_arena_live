from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "admin_role IS NULL OR admin_role IN "
            "('viewer', 'content_editor', 'operator', 'super_admin')",
            name="ck_users_admin_role",
        ),
        CheckConstraint(
            "(auth_provider IS NULL AND auth_subject IS NULL) OR "
            "(auth_provider IS NOT NULL AND auth_subject IS NOT NULL)",
            name="ck_users_auth_identity_paired",
        ),
        UniqueConstraint(
            "auth_provider",
            "auth_subject",
            name="uq_users_auth_provider_subject",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    auth_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_role: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    admin_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
