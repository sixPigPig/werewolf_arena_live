"""persist the explicit TTS dialect used for voice materialization

Revision ID: 20260728_50
Revises: 20260728_49
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_50"
down_revision = "20260728_49"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("voice_materialization_jobs") as batch_op:
        batch_op.add_column(sa.Column("tts_dialect", sa.String(length=16), nullable=True))
    with op.batch_alter_table("voice_utterances") as batch_op:
        batch_op.add_column(sa.Column("tts_dialect", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("voice_utterances") as batch_op:
        batch_op.drop_column("tts_dialect")
    with op.batch_alter_table("voice_materialization_jobs") as batch_op:
        batch_op.drop_column("tts_dialect")
