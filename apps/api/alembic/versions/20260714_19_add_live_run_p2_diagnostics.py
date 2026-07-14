"""add live run p2 diagnostics

Revision ID: 20260714_19
Revises: 20260714_18
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_19"
down_revision = "20260714_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "live_runs",
        sa.Column(
            "p2_diagnostics",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("live_runs", "p2_diagnostics")
