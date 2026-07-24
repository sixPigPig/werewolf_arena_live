"""defer V2 run start until a viewer is ready

Revision ID: 20260723_42
Revises: 20260723_41
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_42"
down_revision = "20260723_41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("v2_game_runs") as batch_op:
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
            server_default=None,
        )


def downgrade() -> None:
    op.execute(
        "UPDATE v2_game_runs SET started_at = CURRENT_TIMESTAMP WHERE started_at IS NULL"
    )
    with op.batch_alter_table("v2_game_runs") as batch_op:
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
