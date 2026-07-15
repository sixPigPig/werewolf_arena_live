"""create model configurations

Revision ID: 20260715_24
Revises: 20260715_23
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_24"
down_revision = "20260715_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_configurations",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("source_model_id", sa.String(length=160), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("available", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("supports_thinking", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("parameter_values", sa.JSON(), nullable=False),
        sa.Column("source_details", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("provider", "model_id"),
    )
    op.create_index(
        "ix_model_configurations_provider_available",
        "model_configurations",
        ["provider", "available"],
    )
    op.create_index(
        "uq_model_configurations_default",
        "model_configurations",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_model_configurations_default", table_name="model_configurations")
    op.drop_index(
        "ix_model_configurations_provider_available",
        table_name="model_configurations",
    )
    op.drop_table("model_configurations")
