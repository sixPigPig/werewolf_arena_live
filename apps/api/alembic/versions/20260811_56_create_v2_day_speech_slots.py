"""create durable V2 day speech pipeline slots

Revision ID: 20260811_56
Revises: 20260810_55
Create Date: 2026-08-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_56"
down_revision = "20260810_55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_day_speech_slots",
        sa.Column("slot_id", sa.String(length=48), primary_key=True),
        sa.Column(
            "game_id",
            sa.String(length=40),
            sa.ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=40),
            sa.ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fence_worker_id", sa.String(length=64), nullable=False),
        sa.Column("fence_token", sa.BigInteger(), nullable=False),
        sa.Column("phase_id", sa.String(length=40), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("speech_round", sa.Integer(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=120), nullable=False),
        sa.Column("actor_player_id", sa.String(length=80), nullable=False),
        sa.Column("predecessor_action_id", sa.String(length=48), nullable=False),
        sa.Column("predecessor_presentation_id", sa.String(length=48), nullable=False),
        sa.Column("predecessor_source_event_id", sa.BigInteger(), nullable=False),
        sa.Column("predecessor_source_record_seq", sa.BigInteger(), nullable=False),
        sa.Column("context_cutoff_record_seq", sa.BigInteger(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=24),
            nullable=False,
            server_default="reserved",
        ),
        sa.Column("generation_action_id", sa.String(length=48)),
        sa.Column("generation_attempt_id", sa.String(length=48)),
        sa.Column("generation_response_record_seq", sa.BigInteger()),
        sa.Column("decision", sa.JSON()),
        sa.Column("presentation_action_id", sa.String(length=48)),
        sa.Column("presentation_id", sa.String(length=48)),
        sa.Column("failure_record_seq", sa.BigInteger()),
        sa.Column("failure", sa.JSON()),
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
        sa.Column("generation_started_at", sa.DateTime(timezone=True)),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("presenting_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "game_id",
            "run_id",
            "phase_id",
            "speech_round",
            "turn_index",
            name="uq_v2_day_speech_slots_turn",
        ),
        sa.UniqueConstraint(
            "game_id",
            "run_id",
            "predecessor_presentation_id",
            name="uq_v2_day_speech_slots_predecessor",
        ),
        sa.UniqueConstraint(
            "generation_action_id",
            name="uq_v2_day_speech_slots_generation_action",
        ),
        sa.UniqueConstraint(
            "generation_attempt_id",
            name="uq_v2_day_speech_slots_generation_attempt",
        ),
        sa.UniqueConstraint(
            "presentation_action_id",
            name="uq_v2_day_speech_slots_presentation_action",
        ),
        sa.UniqueConstraint(
            "presentation_id",
            name="uq_v2_day_speech_slots_presentation",
        ),
        sa.UniqueConstraint(
            "game_id",
            "generation_response_record_seq",
            name="uq_v2_day_speech_slots_response_event",
        ),
        sa.CheckConstraint(
            "state IN ('reserved', 'generating', 'ready', 'presenting', 'consumed', "
            "'failed', 'canceled', 'invalidated')",
            name="ck_v2_day_speech_slots_state",
        ),
        sa.CheckConstraint(
            "action_type = 'day_debate_speech'",
            name="ck_v2_day_speech_slots_action_type",
        ),
        sa.CheckConstraint(
            "fence_token >= 0",
            name="ck_v2_day_speech_slots_fence_nonnegative",
        ),
        sa.CheckConstraint(
            "round_no >= 1 AND speech_round >= 1 AND turn_index >= 2",
            name="ck_v2_day_speech_slots_position_positive",
        ),
        sa.CheckConstraint(
            "predecessor_source_event_id >= 1 AND predecessor_source_record_seq >= 1 AND "
            "context_cutoff_record_seq >= predecessor_source_record_seq",
            name="ck_v2_day_speech_slots_cutoff_lineage",
        ),
    )
    op.create_index(
        "ix_v2_day_speech_slots_game_state",
        "v2_day_speech_slots",
        ["game_id", "state"],
    )
    op.create_index(
        "ix_v2_day_speech_slots_run_state",
        "v2_day_speech_slots",
        ["run_id", "state"],
    )


def downgrade() -> None:
    op.drop_table("v2_day_speech_slots")
