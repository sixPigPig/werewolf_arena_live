"""create judge configurations

Revision ID: 20260723_41
Revises: 20260722_40
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_41"
down_revision = "20260722_40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_configurations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("model_provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("tts_speaker", sa.String(length=160), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("judge_configurations")
