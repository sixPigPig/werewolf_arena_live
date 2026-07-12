from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuleSetRecord(Base):
    __tablename__ = "rule_sets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_rule_sets_status",
        ),
        CheckConstraint(
            "lock_version >= 1",
            name="ck_rule_sets_lock_version_positive",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="ck_rule_sets_display_order_nonnegative",
        ),
        CheckConstraint(
            "is_default = false OR status = 'published'",
            name="ck_rule_sets_default_published",
        ),
        CheckConstraint(
            "(status = 'draft' AND draft_revision_id IS NOT NULL) OR "
            "(status = 'published' AND current_published_revision_id IS NOT NULL) OR "
            "(status = 'archived' AND "
            "(current_published_revision_id IS NOT NULL OR draft_revision_id IS NOT NULL))",
            name="ck_rule_sets_pointer_state",
        ),
        CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) OR "
            "(status != 'archived' AND archived_at IS NULL)",
            name="ck_rule_sets_archive_timestamp",
        ),
        Index(
            "uq_rule_sets_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default = true"),
            sqlite_where=text("is_default = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    current_published_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    draft_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    lock_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    archived_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __mapper_args__ = {"version_id_col": lock_version}


class RuleSetRevisionRecord(Base):
    __tablename__ = "rule_set_revisions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('draft', 'published', 'superseded')",
            name="ck_rule_set_revisions_state",
        ),
        CheckConstraint(
            "revision_no >= 1",
            name="ck_rule_set_revisions_revision_positive",
        ),
        CheckConstraint(
            "schema_version = 1",
            name="ck_rule_set_revisions_schema_version",
        ),
        CheckConstraint(
            "lock_version >= 1",
            name="ck_rule_set_revisions_lock_version_positive",
        ),
        CheckConstraint(
            "state = 'draft' OR "
            "(state IN ('published', 'superseded') "
            "AND content_hash IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_rule_set_revisions_publish_fields",
        ),
        UniqueConstraint(
            "rule_set_id",
            "revision_no",
            name="uq_rule_set_revisions_rule_revision",
        ),
        Index(
            "uq_rule_set_revisions_one_draft",
            "rule_set_id",
            unique=True,
            postgresql_where=text("state = 'draft'"),
            sqlite_where=text("state = 'draft'"),
        ),
        Index(
            "uq_rule_set_revisions_one_published",
            "rule_set_id",
            unique=True,
            postgresql_where=text("state = 'published'"),
            sqlite_where=text("state = 'published'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rule_set_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("rule_sets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        active_history=True,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lock_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    role_summary: Mapped[str] = mapped_column(String(500), nullable=False)
    complexity: Mapped[str] = mapped_column(String(40), nullable=False)
    estimated_duration: Mapped[str] = mapped_column(String(40), nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    publish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        active_history=True,
    )

    __mapper_args__ = {"version_id_col": lock_version}


_PUBLISHED_IMMUTABLE_FIELDS = (
    "id",
    "rule_set_id",
    "revision_no",
    "schema_version",
    "content_hash",
    "name",
    "description",
    "player_count",
    "role_summary",
    "complexity",
    "estimated_duration",
    "config",
    "created_by_user_id",
    "published_by_user_id",
    "publish_reason",
    "created_at",
    "published_at",
)


def _original_attribute_value(
    target: RuleSetRevisionRecord,
    attribute_name: str,
) -> object:
    attribute = inspect(target).attrs[attribute_name]
    if attribute.history.deleted:
        return attribute.history.deleted[0]
    return getattr(target, attribute_name)


@event.listens_for(RuleSetRevisionRecord, "before_update")
def _protect_published_revision_content(
    _mapper: object,
    _connection: object,
    target: RuleSetRevisionRecord,
) -> None:
    original_state = _original_attribute_value(target, "state")

    if original_state == "superseded":
        raise ValueError("superseded rule revision is immutable")
    if original_state != "published":
        return

    changed_content = any(
        inspect(target).attrs[field].history.has_changes() for field in _PUBLISHED_IMMUTABLE_FIELDS
    )
    if changed_content:
        raise ValueError("published rule revision content is immutable")
    if target.state != "superseded":
        raise ValueError("published rule revision can only transition to superseded")


@event.listens_for(RuleSetRevisionRecord, "before_delete")
def _protect_published_revision_deletion(
    _mapper: object,
    _connection: object,
    target: RuleSetRevisionRecord,
) -> None:
    original_state = _original_attribute_value(target, "state")
    original_published_at = _original_attribute_value(target, "published_at")
    if original_state != "draft" or original_published_at is not None:
        raise ValueError("only draft rule revisions can be deleted")
