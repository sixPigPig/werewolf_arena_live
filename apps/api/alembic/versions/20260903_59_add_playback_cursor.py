"""add audience playback cursor to v2 games

Revision ID: 20260903_59
Revises: 20260820_58
Create Date: 2026-09-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_59"
down_revision = "20260820_58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("v2_game_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "playback_cursor",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("v2_game_records") as batch_op:
        batch_op.drop_column("playback_cursor")
