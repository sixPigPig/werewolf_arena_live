from __future__ import annotations

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260712_15"
down_revision = "20260711_14"
branch_labels = None
depends_on = None


_PUBLISHED_AT = datetime(2026, 7, 12, tzinfo=UTC)

_OFFICIAL_RULE_SET_SEEDS = (
    {
        "id": "classic_8",
        "revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
        "content_hash": "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131",
        "display_order": 1,
        "is_default": True,
        "player_count": 8,
        "role_summary": "2 狼人 / 1 预言家 / 1 守卫 / 4 村民",
        "config": {
            "name": "经典 8 人局",
            "description": "包含狼人、预言家、守卫与村民的官方标准局。",
            "complexity": "标准",
            "estimated_duration": "中",
            "rule_tags": ["无警长", "顺序发言", "标准"],
            "role_counts": {
                "werewolf": 2,
                "villager": 4,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    {
        "id": "starter_6",
        "revision_id": "b607e17e-b86f-5eb0-9dc2-b8df09aa71ab",
        "content_hash": "f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c",
        "display_order": 2,
        "is_default": False,
        "player_count": 6,
        "role_summary": "1 狼人 / 1 预言家 / 1 守卫 / 3 村民",
        "config": {
            "name": "新手 6 人快局",
            "description": "更短的官方入门局,适合快速观察模型策略。",
            "complexity": "入门",
            "estimated_duration": "短",
            "rule_tags": ["无警长", "顺序发言", "新手"],
            "role_counts": {
                "werewolf": 1,
                "villager": 3,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    {
        "id": "social_8",
        "revision_id": "2b4a993f-e4e6-5312-b11d-92874851a70a",
        "content_hash": "21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc",
        "display_order": 3,
        "is_default": False,
        "player_count": 8,
        "role_summary": "2 狼人 / 6 村民",
        "config": {
            "name": "社交 8 人局",
            "description": "仅保留狼人夜晚行动的官方心理博弈局。",
            "complexity": "心理",
            "estimated_duration": "中",
            "rule_tags": ["无警长", "顺序发言", "心理"],
            "role_counts": {
                "werewolf": 2,
                "villager": 6,
                "seer": 0,
                "guard": 0,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    {
        "id": "classic_12_seer_witch_hunter_idiot",
        "revision_id": "0489f6ac-16fd-5323-96ce-ee256c98cf32",
        "content_hash": "bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2",
        "display_order": 4,
        "is_default": False,
        "player_count": 12,
        "role_summary": "4 狼人 / 1 预言家 / 1 女巫 / 1 猎人 / 1 白痴 / 4 村民",
        "config": {
            "name": "12 人预女猎白局",
            "description": "4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
            "complexity": "进阶",
            "estimated_duration": "长",
            "rule_tags": ["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
            "role_counts": {
                "werewolf": 4,
                "villager": 4,
                "seer": 1,
                "guard": 0,
                "witch": 1,
                "hunter": 1,
                "idiot": 1,
            },
            "win_condition": "slaughter_side",
            "sheriff_enabled": True,
            "sheriff_vote_weight": 1.5,
            "speech_policy": "sheriff_directed",
            "werewolf_self_explosion_enabled": True,
            "sheriff_badge_bomb_policy": "double",
        },
    },
)


def upgrade() -> None:
    rule_sets = op.create_table(
        "rule_sets",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("current_published_revision_id", sa.String(length=36), nullable=True),
        sa.Column("draft_revision_id", sa.String(length=36), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "lock_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "archived_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_rule_sets_status",
        ),
        sa.CheckConstraint(
            "lock_version >= 1",
            name="ck_rule_sets_lock_version_positive",
        ),
        sa.CheckConstraint(
            "display_order >= 0",
            name="ck_rule_sets_display_order_nonnegative",
        ),
        sa.CheckConstraint(
            "is_default = false OR status = 'published'",
            name="ck_rule_sets_default_published",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND draft_revision_id IS NOT NULL) OR "
            "(status = 'published' AND current_published_revision_id IS NOT NULL) OR "
            "(status = 'archived' AND "
            "(current_published_revision_id IS NOT NULL OR draft_revision_id IS NOT NULL))",
            name="ck_rule_sets_pointer_state",
        ),
        sa.CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) OR "
            "(status != 'archived' AND archived_at IS NULL)",
            name="ck_rule_sets_archive_timestamp",
        ),
    )
    op.create_index(
        "ix_rule_sets_current_published_revision_id",
        "rule_sets",
        ["current_published_revision_id"],
    )
    op.create_index(
        "ix_rule_sets_draft_revision_id",
        "rule_sets",
        ["draft_revision_id"],
    )
    op.create_index(
        "ix_rule_sets_created_by_user_id",
        "rule_sets",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_rule_sets_updated_by_user_id",
        "rule_sets",
        ["updated_by_user_id"],
    )
    op.create_index(
        "ix_rule_sets_archived_by_user_id",
        "rule_sets",
        ["archived_by_user_id"],
    )
    op.create_index(
        "uq_rule_sets_one_default",
        "rule_sets",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default = 1"),
    )

    rule_set_revisions = op.create_table(
        "rule_set_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "rule_set_id",
            sa.String(length=80),
            sa.ForeignKey("rule_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "lock_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("player_count", sa.Integer(), nullable=False),
        sa.Column("role_summary", sa.String(length=500), nullable=False),
        sa.Column("complexity", sa.String(length=40), nullable=False),
        sa.Column("estimated_duration", sa.String(length=40), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "published_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("publish_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('draft', 'published', 'superseded')",
            name="ck_rule_set_revisions_state",
        ),
        sa.CheckConstraint(
            "revision_no >= 1",
            name="ck_rule_set_revisions_revision_positive",
        ),
        sa.CheckConstraint(
            "schema_version = 1",
            name="ck_rule_set_revisions_schema_version",
        ),
        sa.CheckConstraint(
            "lock_version >= 1",
            name="ck_rule_set_revisions_lock_version_positive",
        ),
        sa.CheckConstraint(
            "state = 'draft' OR "
            "(state IN ('published', 'superseded') "
            "AND content_hash IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_rule_set_revisions_publish_fields",
        ),
        sa.UniqueConstraint(
            "rule_set_id",
            "revision_no",
            name="uq_rule_set_revisions_rule_revision",
        ),
    )
    op.create_index(
        "ix_rule_set_revisions_created_by_user_id",
        "rule_set_revisions",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_rule_set_revisions_updated_by_user_id",
        "rule_set_revisions",
        ["updated_by_user_id"],
    )
    op.create_index(
        "ix_rule_set_revisions_published_by_user_id",
        "rule_set_revisions",
        ["published_by_user_id"],
    )
    op.create_index(
        "uq_rule_set_revisions_one_draft",
        "rule_set_revisions",
        ["rule_set_id"],
        unique=True,
        postgresql_where=sa.text("state = 'draft'"),
        sqlite_where=sa.text("state = 'draft'"),
    )
    op.create_index(
        "uq_rule_set_revisions_one_published",
        "rule_set_revisions",
        ["rule_set_id"],
        unique=True,
        postgresql_where=sa.text("state = 'published'"),
        sqlite_where=sa.text("state = 'published'"),
    )

    op.bulk_insert(
        rule_sets,
        [
            {
                "id": seed["id"],
                "status": "published",
                "current_published_revision_id": seed["revision_id"],
                "draft_revision_id": None,
                "is_default": seed["is_default"],
                "display_order": seed["display_order"],
                "lock_version": 1,
                "created_by_user_id": None,
                "updated_by_user_id": None,
                "archived_by_user_id": None,
                "archived_at": None,
            }
            for seed in _OFFICIAL_RULE_SET_SEEDS
        ],
    )
    op.bulk_insert(
        rule_set_revisions,
        [
            {
                "id": seed["revision_id"],
                "rule_set_id": seed["id"],
                "revision_no": 1,
                "state": "published",
                "schema_version": 1,
                "content_hash": seed["content_hash"],
                "lock_version": 1,
                "name": seed["config"]["name"],
                "description": seed["config"]["description"],
                "player_count": seed["player_count"],
                "role_summary": seed["role_summary"],
                "complexity": seed["config"]["complexity"],
                "estimated_duration": seed["config"]["estimated_duration"],
                "config": seed["config"],
                "created_by_user_id": None,
                "updated_by_user_id": None,
                "published_by_user_id": None,
                "publish_reason": None,
                "published_at": _PUBLISHED_AT,
            }
            for seed in _OFFICIAL_RULE_SET_SEEDS
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "uq_rule_set_revisions_one_published",
        table_name="rule_set_revisions",
    )
    op.drop_index(
        "uq_rule_set_revisions_one_draft",
        table_name="rule_set_revisions",
    )
    op.drop_index(
        "ix_rule_set_revisions_published_by_user_id",
        table_name="rule_set_revisions",
    )
    op.drop_index(
        "ix_rule_set_revisions_updated_by_user_id",
        table_name="rule_set_revisions",
    )
    op.drop_index(
        "ix_rule_set_revisions_created_by_user_id",
        table_name="rule_set_revisions",
    )
    op.drop_table("rule_set_revisions")

    op.drop_index("uq_rule_sets_one_default", table_name="rule_sets")
    op.drop_index("ix_rule_sets_archived_by_user_id", table_name="rule_sets")
    op.drop_index("ix_rule_sets_updated_by_user_id", table_name="rule_sets")
    op.drop_index("ix_rule_sets_created_by_user_id", table_name="rule_sets")
    op.drop_index("ix_rule_sets_draft_revision_id", table_name="rule_sets")
    op.drop_index(
        "ix_rule_sets_current_published_revision_id",
        table_name="rule_sets",
    )
    op.drop_table("rule_sets")
