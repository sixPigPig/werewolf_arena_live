"""create durable V2 model action recoveries

Revision ID: 20260805_53
Revises: 20260730_52
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260805_53"
down_revision = "20260730_52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_model_action_recoveries",
        sa.Column("action_id", sa.String(length=48), primary_key=True),
        sa.Column("recovery_id", sa.String(length=48), nullable=False, unique=True),
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
        sa.Column("action_type", sa.String(length=120), nullable=False),
        sa.Column("actor_id", sa.String(length=80), nullable=False),
        sa.Column("model_provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("model_context", sa.JSON(), nullable=False),
        sa.Column("action_snapshot", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(length=120), nullable=False),
        sa.Column("failure_category", sa.String(length=40), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("retry_cycle", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column(
            "control_request_id",
            sa.String(length=36),
            sa.ForeignKey("v2_game_control_requests.id", ondelete="SET NULL"),
        ),
        sa.Column("lease_owner", sa.String(length=120)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_attempt_id", sa.String(length=48)),
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
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_v2_model_action_recoveries_game_state",
        "v2_model_action_recoveries",
        ["game_id", "state"],
    )
    op.create_index(
        "ix_v2_model_action_recoveries_state",
        "v2_model_action_recoveries",
        ["state"],
    )
    op.create_index(
        "ix_v2_model_action_recoveries_state_updated",
        "v2_model_action_recoveries",
        ["state", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("v2_model_action_recoveries")
