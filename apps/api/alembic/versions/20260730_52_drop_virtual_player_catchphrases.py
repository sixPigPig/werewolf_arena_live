"""drop virtual player catchphrases

Revision ID: 20260730_52
Revises: 20260729_51
Create Date: 2026-07-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260730_52"
down_revision = "20260729_51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("virtual_player_profiles", "catchphrases")


def downgrade() -> None:
    op.add_column(
        "virtual_player_profiles",
        sa.Column(
            "catchphrases",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
