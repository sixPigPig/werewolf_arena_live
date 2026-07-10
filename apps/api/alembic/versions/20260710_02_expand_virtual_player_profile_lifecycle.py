from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260710_02"
down_revision = "20260710_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="published",
            )
        )
        batch_op.add_column(
            sa.Column(
                "featured",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column(
                "published_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.func.now(),
            )
        )
        batch_op.add_column(sa.Column("published_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("updated_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )

    profile_table = sa.table(
        "virtual_player_profiles",
        sa.column("favorite", sa.Boolean()),
        sa.column("featured", sa.Boolean()),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        profile_table.update().values(
            featured=profile_table.c.favorite,
            published_at=sa.func.coalesce(
                profile_table.c.created_at,
                profile_table.c.updated_at,
                sa.func.now(),
            ),
        )
    )

    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.create_foreign_key(
            "fk_virtual_player_profiles_published_by_user_id",
            "users",
            ["published_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_virtual_player_profiles_updated_by_user_id",
            "users",
            ["updated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_status",
            "status IN ('draft', 'published', 'archived')",
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_version_positive",
            "version >= 1",
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_lifecycle_timestamps",
            "(status = 'draft' AND published_at IS NULL AND deleted_at IS NULL) OR "
            "(status = 'published' AND published_at IS NOT NULL AND deleted_at IS NULL) OR "
            "(status = 'archived' AND published_at IS NOT NULL AND deleted_at IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_featured_published",
            "featured = false OR status = 'published'",
        )
        batch_op.create_index(
            "ix_virtual_player_profiles_status_display_order",
            ["status", "display_order", "id"],
        )
        batch_op.create_index(
            "ix_virtual_player_profiles_status_model",
            ["status", "model"],
        )
        batch_op.create_index(
            "ix_virtual_player_profiles_status_personality",
            ["status", "personality_id"],
        )
        batch_op.create_index(
            "ix_virtual_player_profiles_status_updated_at",
            ["status", "updated_at", "id"],
        )
        batch_op.create_index(
            "ix_virtual_player_profiles_published_by_user_id",
            ["published_by_user_id"],
        )
        batch_op.create_index(
            "ix_virtual_player_profiles_updated_by_user_id",
            ["updated_by_user_id"],
        )
        batch_op.create_index(
            "ix_virtual_player_profiles_deleted_at",
            ["deleted_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.drop_index("ix_virtual_player_profiles_deleted_at")
        batch_op.drop_index("ix_virtual_player_profiles_updated_by_user_id")
        batch_op.drop_index("ix_virtual_player_profiles_published_by_user_id")
        batch_op.drop_index("ix_virtual_player_profiles_status_updated_at")
        batch_op.drop_index("ix_virtual_player_profiles_status_personality")
        batch_op.drop_index("ix_virtual_player_profiles_status_model")
        batch_op.drop_index("ix_virtual_player_profiles_status_display_order")
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_featured_published",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_lifecycle_timestamps",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_version_positive",
            type_="check",
        )
        batch_op.drop_constraint("ck_virtual_player_profiles_status", type_="check")
        batch_op.drop_constraint(
            "fk_virtual_player_profiles_updated_by_user_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_virtual_player_profiles_published_by_user_id",
            type_="foreignkey",
        )
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("updated_by_user_id")
        batch_op.drop_column("published_by_user_id")
        batch_op.drop_column("published_at")
        batch_op.drop_column("version")
        batch_op.drop_column("featured")
        batch_op.drop_column("status")
