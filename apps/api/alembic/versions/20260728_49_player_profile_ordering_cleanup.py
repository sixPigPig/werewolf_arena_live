"""make player profile ordering explicit and remove legacy profile fields

Revision ID: 20260728_49
Revises: 20260727_48
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_49"
down_revision = "20260727_48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE virtual_player_profiles
            SET status = 'archived'
            WHERE status = 'published' AND deleted_at IS NOT NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id, row_number() OVER (
                    ORDER BY display_order ASC, id ASC
                ) AS next_order
                FROM virtual_player_profiles
                WHERE status = 'published'
            )
            UPDATE virtual_player_profiles AS profiles
            SET display_order = ranked.next_order
            FROM ranked
            WHERE profiles.id = ranked.id
            """
        )
    )
    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.alter_column(
            "display_order",
            existing_type=sa.Integer(),
            nullable=True,
            server_default=None,
        )
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            nullable=False,
            server_default="draft",
        )
        batch_op.alter_column(
            "published_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
            server_default=None,
        )

    connection.execute(
        sa.text(
            """
            UPDATE virtual_player_profiles
            SET display_order = NULL
            WHERE status <> 'published'
            """
        )
    )

    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.drop_index("ix_virtual_player_profiles_owner_user_id")
        batch_op.drop_constraint(
            "virtual_player_profiles_owner_user_id_fkey",
            type_="foreignkey",
        )
        batch_op.drop_column("favorite")
        batch_op.drop_column("owner_user_id")
        batch_op.drop_column("avatar_prompt")
        batch_op.drop_column("avatar_image_path")
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_display_order_lifecycle",
            "(status = 'published' AND display_order IS NOT NULL AND display_order >= 1) OR "
            "(status IN ('draft', 'archived') AND display_order IS NULL)",
        )
        batch_op.create_index(
            "uq_virtual_player_profiles_published_display_order",
            ["display_order"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.alter_column(
            "published_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        )
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            nullable=False,
            server_default="published",
        )
        batch_op.drop_index("uq_virtual_player_profiles_published_display_order")
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_display_order_lifecycle",
            type_="check",
        )
        batch_op.add_column(
            sa.Column(
                "avatar_image_path",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "avatar_prompt",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "favorite",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_foreign_key(
            "virtual_player_profiles_owner_user_id_fkey",
            "users",
            ["owner_user_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_virtual_player_profiles_owner_user_id",
            ["owner_user_id"],
        )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id
            FROM virtual_player_profiles
            ORDER BY
                CASE WHEN display_order IS NULL THEN 1 ELSE 0 END,
                display_order ASC,
                created_at ASC,
                id ASC
            """
        )
    ).fetchall()
    for display_order, row in enumerate(rows, start=1):
        connection.execute(
            sa.text(
                """
                UPDATE virtual_player_profiles
                SET display_order = :display_order
                WHERE id = :profile_id
                """
            ),
            {"display_order": display_order, "profile_id": row.id},
        )

    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.alter_column(
            "display_order",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="0",
        )
