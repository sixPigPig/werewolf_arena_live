"""add liveness rollout config

Revision ID: 20260720_33
Revises: 20260720_32
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_33"
down_revision = "20260720_32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "liveness_rollout_configs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("experience_revision", sa.String(length=40), nullable=False),
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("treatment_percent", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
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
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_liveness_rollout_configs_revision_positive",
        ),
        sa.CheckConstraint(
            "treatment_percent >= 0 AND treatment_percent <= 100",
            name="ck_liveness_rollout_configs_treatment_percent",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("liveness_rollout_configs")
