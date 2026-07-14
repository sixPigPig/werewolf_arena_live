"""create game quality evaluations

Revision ID: 20260714_20
Revises: 20260714_19
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_20"
down_revision = "20260714_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_quality_evaluations",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("evaluator_version", sa.String(length=40), nullable=False),
        sa.Column("source_revision", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "data_status", sa.String(length=20), server_default="collecting", nullable=False
        ),
        sa.Column(
            "verdict", sa.String(length=20), server_default="unavailable", nullable=False
        ),
        sa.Column("safe_summary", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("max_event_id", sa.Integer(), nullable=True),
        sa.Column("max_voice_source_event_id", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["live_runs.run_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "evaluator_version",
            "source_revision",
            name="uq_game_quality_evaluation_revision",
        ),
    )
    op.create_index(
        "ix_game_quality_evaluations_claim",
        "game_quality_evaluations",
        ["status", "not_before", "lease_expires_at", "id"],
    )
    op.create_index(
        "ix_game_quality_evaluations_session_created",
        "game_quality_evaluations",
        ["session_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_game_quality_evaluations_status_completed",
        "game_quality_evaluations",
        ["status", sa.text("completed_at DESC")],
    )
    op.create_index(
        "ix_game_quality_evaluations_verdict_completed",
        "game_quality_evaluations",
        ["verdict", sa.text("completed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_game_quality_evaluations_verdict_completed",
        table_name="game_quality_evaluations",
    )
    op.drop_index(
        "ix_game_quality_evaluations_status_completed",
        table_name="game_quality_evaluations",
    )
    op.drop_index(
        "ix_game_quality_evaluations_session_created",
        table_name="game_quality_evaluations",
    )
    op.drop_index(
        "ix_game_quality_evaluations_claim",
        table_name="game_quality_evaluations",
    )
    op.drop_table("game_quality_evaluations")
