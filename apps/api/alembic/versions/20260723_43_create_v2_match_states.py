"""create live v2 match states

Revision ID: 20260723_43
Revises: 20260723_42
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_43"
down_revision = "20260723_42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_match_states",
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("round_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("sheriff_player_id", sa.String(length=80), nullable=True),
        sa.Column(
            "sheriff_badge_state",
            sa.String(length=24),
            server_default="disabled",
            nullable=False,
        ),
        sa.Column(
            "pre_sheriff_explosion_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("winner", sa.String(length=24), nullable=True),
        sa.Column("completion_reason", sa.String(length=80), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("game_id"),
    )


def downgrade() -> None:
    op.drop_table("v2_match_states")
