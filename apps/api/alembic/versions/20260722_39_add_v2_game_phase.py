"""add live v2 game phase state

Revision ID: 20260722_39
Revises: 20260722_38
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_39"
down_revision = "20260722_38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_game_records",
        sa.Column("phase_seq", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "v2_game_records",
        sa.Column(
            "phase_id",
            sa.String(length=40),
            server_default="legacy",
            nullable=False,
        ),
    )
    op.add_column(
        "v2_game_records",
        sa.Column(
            "phase_state",
            sa.String(length=40),
            server_default="legacy_frozen",
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE v2_game_records "
            "SET status = 'awaiting_observation' "
            "WHERE status IN ('ready', 'generating', 'broadcasting', 'finalizing')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE v2_game_runs "
            "SET status = 'awaiting_observation' "
            "WHERE status IN ('ready', 'generating', 'broadcasting', 'finalizing')"
        )
    )


def downgrade() -> None:
    op.drop_column("v2_game_records", "phase_state")
    op.drop_column("v2_game_records", "phase_id")
    op.drop_column("v2_game_records", "phase_seq")
