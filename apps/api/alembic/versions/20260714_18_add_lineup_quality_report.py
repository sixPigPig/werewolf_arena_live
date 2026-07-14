from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260714_18"
down_revision = "20260714_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "live_runs",
        sa.Column(
            "lineup_quality_report",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("live_runs", "lineup_quality_report")
