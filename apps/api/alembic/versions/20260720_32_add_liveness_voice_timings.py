"""add liveness voice timings

Revision ID: 20260720_32
Revises: 20260719_31
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_32"
down_revision = "20260719_31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("voice_utterances") as batch_op:
        batch_op.add_column(
            sa.Column("tts_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("first_audio_chunk_at", sa.DateTime(timezone=True), nullable=True)
        )
    with op.batch_alter_table("voice_playback_observations") as batch_op:
        batch_op.add_column(
            sa.Column("playback_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("playback_finished_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ack_received_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("voice_playback_observations") as batch_op:
        batch_op.drop_column("ack_received_at")
        batch_op.drop_column("playback_finished_at")
        batch_op.drop_column("playback_started_at")
    with op.batch_alter_table("voice_utterances") as batch_op:
        batch_op.drop_column("first_audio_chunk_at")
        batch_op.drop_column("tts_started_at")
