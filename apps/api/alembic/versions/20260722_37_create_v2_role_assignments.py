"""create private live v2 role assignments

Revision ID: 20260722_37
Revises: 20260722_36
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_37"
down_revision = "20260722_36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_role_assignment_batches",
        sa.Column("assignment_id", sa.String(length=48), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("seed_hex", sa.String(length=64), nullable=False),
        sa.Column("assignment_digest", sa.String(length=64), nullable=False),
        sa.Column("player_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["v2_game_records.game_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("assignment_id"),
        sa.UniqueConstraint("game_id"),
    )
    op.create_table(
        "v2_role_assignments",
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.String(length=48), nullable=False),
        sa.Column("player_id", sa.String(length=80), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("team", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["v2_role_assignment_batches.assignment_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["v2_game_records.game_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("game_id", "seat"),
        sa.UniqueConstraint(
            "game_id",
            "player_id",
            name="uq_v2_role_assignments_player",
        ),
    )
    op.create_index(
        "ix_v2_role_assignments_assignment_id",
        "v2_role_assignments",
        ["assignment_id"],
    )


def downgrade() -> None:
    op.drop_table("v2_role_assignments")
    op.drop_table("v2_role_assignment_batches")
