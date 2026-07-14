"""create audience-scoped live event projections

Revision ID: 20260715_21
Revises: 20260714_20
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_21"
down_revision = "20260714_20"
branch_labels = None
depends_on = None


def _create_projection_table(table_name: str, index_prefix: str) -> None:
    op.create_table(
        table_name,
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(length=40), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id", "source_event_id"],
            ["live_events.run_id", "live_events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "event_id"),
    )
    op.create_index(
        f"ix_{index_prefix}_run_id_event_id",
        table_name,
        ["run_id", "event_id"],
    )
    op.create_index(f"ix_{index_prefix}_session_id", table_name, ["session_id"])
    op.create_index(f"ix_{table_name}_type", table_name, ["type"])


def upgrade() -> None:
    _create_projection_table("public_live_events", "public_live_events")
    _create_projection_table("god_view_live_events", "god_view_live_events")
    op.add_column(
        "voice_materialization_jobs",
        sa.Column(
            "audience",
            sa.String(length=32),
            server_default="player_public",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_voice_materialization_jobs_audience_status",
        "voice_materialization_jobs",
        ["audience", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_materialization_jobs_audience_status",
        table_name="voice_materialization_jobs",
    )
    op.drop_column("voice_materialization_jobs", "audience")
    op.drop_table("god_view_live_events")
    op.drop_table("public_live_events")
