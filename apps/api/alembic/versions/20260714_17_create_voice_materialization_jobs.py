from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260714_17"
down_revision = "20260712_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_materialization_jobs",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=False),
        sa.Column("speaker_kind", sa.String(length=20), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "not_before",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id", "source_event_id"],
            ["live_events.run_id", "live_events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "source_event_id", "speaker_kind"),
    )
    op.create_index(
        "ix_voice_materialization_jobs_claim",
        "voice_materialization_jobs",
        ["status", "not_before", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_voice_materialization_jobs_session",
        "voice_materialization_jobs",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_materialization_jobs_session",
        table_name="voice_materialization_jobs",
    )
    op.drop_index(
        "ix_voice_materialization_jobs_claim",
        table_name="voice_materialization_jobs",
    )
    op.drop_table("voice_materialization_jobs")
