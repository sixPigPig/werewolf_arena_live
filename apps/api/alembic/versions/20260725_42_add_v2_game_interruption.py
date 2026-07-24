"""add live v2 game interruption

Revision ID: 20260725_42
Revises: 20260723_41
Create Date: 2026-07-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260725_42"
down_revision = "20260723_41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_game_runs",
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "v2_game_control_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["v2_game_records.game_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["v2_game_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_v2_game_control_requests_game_id",
        "v2_game_control_requests",
        ["game_id"],
    )
    op.create_index(
        "ix_v2_game_control_requests_run_id",
        "v2_game_control_requests",
        ["run_id"],
    )
    op.create_index(
        "uq_v2_game_control_actor_key",
        "v2_game_control_requests",
        ["actor_user_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_v2_game_control_actor_key",
        table_name="v2_game_control_requests",
    )
    op.drop_index(
        "ix_v2_game_control_requests_run_id",
        table_name="v2_game_control_requests",
    )
    op.drop_index(
        "ix_v2_game_control_requests_game_id",
        table_name="v2_game_control_requests",
    )
    op.drop_table("v2_game_control_requests")
    op.drop_column("v2_game_runs", "stop_requested_at")
