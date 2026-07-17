"""add semantic presentation identity to persisted voice

Revision ID: 20260717_27
Revises: 20260717_26
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260717_27"
down_revision = "20260717_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "voice_utterances",
        sa.Column("presentation_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("voice_utterances", "presentation_id")
