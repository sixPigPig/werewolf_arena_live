"""create live v2 foundation records

Revision ID: 20260721_35
Revises: 20260720_34
Create Date: 2026-07-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260721_35"
down_revision = "20260720_34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_game_records",
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_run_id", sa.String(length=40), nullable=False),
        sa.Column("record_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_record_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_presentation_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("players_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("game_id"),
    )
    op.create_index("ix_v2_game_records_status", "v2_game_records", ["status"])
    op.create_index("ix_v2_game_records_current_run_id", "v2_game_records", ["current_run_id"])
    op.create_index("ix_v2_game_records_updated_at", "v2_game_records", ["updated_at"])

    op.create_table(
        "v2_game_runs",
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("attempt_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("game_id", "attempt_no", name="uq_v2_game_runs_game_attempt"),
    )
    op.create_index("ix_v2_game_runs_game_id", "v2_game_runs", ["game_id"])
    op.create_index("ix_v2_game_runs_status", "v2_game_runs", ["status"])

    op.create_table(
        "v2_game_record_events",
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("record_seq", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["v2_game_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("game_id", "event_id"),
        sa.UniqueConstraint("game_id", "record_seq", name="uq_v2_game_events_record_seq"),
    )
    op.create_index("ix_v2_game_events_run_id", "v2_game_record_events", ["run_id"])
    op.create_index("ix_v2_game_events_event_type", "v2_game_record_events", ["event_type"])
    op.create_index("ix_v2_game_events_game_created", "v2_game_record_events", ["game_id", "created_at"])

    op.create_table(
        "v2_live_presentations",
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("presentation_seq", sa.Integer(), nullable=False),
        sa.Column("presentation_id", sa.String(length=48), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("phase_id", sa.String(length=40), nullable=False),
        sa.Column("actor_kind", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=80), nullable=False),
        sa.Column("speech_id", sa.String(length=48), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("subtitle_text", sa.Text(), nullable=False),
        sa.Column("subtitle_timings", sa.JSON(), nullable=False),
        sa.Column("audio_asset_id", sa.String(length=80), nullable=False),
        sa.Column("audio_mime_type", sa.String(length=80), nullable=False),
        sa.Column("audio_duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["v2_game_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("game_id", "presentation_seq"),
        sa.UniqueConstraint("presentation_id", name="uq_v2_presentations_id"),
    )
    op.create_index("ix_v2_presentations_run_id", "v2_live_presentations", ["run_id"])
    op.create_index("ix_v2_presentations_speech_id", "v2_live_presentations", ["speech_id"])
    op.create_index("ix_v2_presentations_state", "v2_live_presentations", ["state"])
    op.create_index("ix_v2_presentations_game_state", "v2_live_presentations", ["game_id", "state"])


def downgrade() -> None:
    op.drop_table("v2_live_presentations")
    op.drop_table("v2_game_record_events")
    op.drop_table("v2_game_runs")
    op.drop_table("v2_game_records")
