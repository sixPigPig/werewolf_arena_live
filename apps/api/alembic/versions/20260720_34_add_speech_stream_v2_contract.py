"""add speech stream v2 contract

Revision ID: 20260720_34
Revises: 20260721_33
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_34"
down_revision = "20260721_33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("speech_turn_receipts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "speech_stream_mode",
                sa.String(length=24),
                nullable=False,
                server_default="segments_v2",
            )
        )
        batch_op.add_column(sa.Column("final_segment_index", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("sealed_source_run_id", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("sealed_source_event_id", sa.Integer(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_speech_turn_receipts_stream_mode",
            "speech_stream_mode = 'segments_v2'",
        )


def downgrade() -> None:
    with op.batch_alter_table("speech_turn_receipts") as batch_op:
        batch_op.drop_constraint(
            "ck_speech_turn_receipts_stream_mode",
            type_="check",
        )
        batch_op.drop_column("sealed_source_event_id")
        batch_op.drop_column("sealed_source_run_id")
        batch_op.drop_column("final_segment_index")
        batch_op.drop_column("speech_stream_mode")
