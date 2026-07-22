"""create live v2 god view access grants

Revision ID: 20260722_38
Revises: 20260722_37
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_38"
down_revision = "20260722_37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_god_view_access_grants",
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["v2_game_records.game_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("game_id"),
        sa.UniqueConstraint("token_sha256"),
    )


def downgrade() -> None:
    op.drop_table("v2_god_view_access_grants")
