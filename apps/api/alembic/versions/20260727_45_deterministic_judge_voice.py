"""make V2 judge speech deterministic and freeze game voice

Revision ID: 20260727_45
Revises: 20260725_44
Create Date: 2026-07-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260727_45"
down_revision = "20260725_44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "judge_configurations",
        sa.Column(
            "voice_mode",
            sa.String(length=16),
            server_default="fixed",
            nullable=False,
        ),
    )
    op.add_column(
        "judge_configurations",
        sa.Column(
            "random_tts_speakers",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.drop_column("judge_configurations", "model_id")
    op.drop_column("judge_configurations", "model_provider")
    op.add_column(
        "v2_game_records",
        sa.Column(
            "judge_voice_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("v2_game_records", "judge_voice_snapshot")
    op.add_column(
        "judge_configurations",
        sa.Column(
            "model_provider",
            sa.String(length=32),
            server_default="agent_plan",
            nullable=False,
        ),
    )
    op.add_column(
        "judge_configurations",
        sa.Column(
            "model_id",
            sa.String(length=160),
            server_default="",
            nullable=False,
        ),
    )
    op.drop_column("judge_configurations", "random_tts_speakers")
    op.drop_column("judge_configurations", "voice_mode")
