"""add virtual player model provider

Revision ID: 20260727_46
Revises: 20260727_45
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260727_46"
down_revision = "20260727_45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "virtual_player_profiles",
        sa.Column("model_provider", sa.String(length=32), nullable=True),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE virtual_player_profiles AS profile
            SET model_provider = matched.provider
            FROM (
                SELECT model_id, min(provider) AS provider
                FROM model_configurations
                GROUP BY model_id
                HAVING count(*) = 1
            ) AS matched
            WHERE profile.model = matched.model_id
            """
        )
    )
    unresolved = connection.scalar(
        sa.text(
            "SELECT count(*) FROM virtual_player_profiles "
            "WHERE model_provider IS NULL"
        )
    )
    if unresolved:
        raise RuntimeError(
            "virtual player model providers cannot be resolved uniquely; "
            "configure every player with an explicit provider before upgrading"
        )

    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.alter_column(
            "model_provider",
            existing_type=sa.String(length=32),
            nullable=False,
        )
        batch_op.drop_index("ix_virtual_player_profiles_status_model")
        batch_op.create_index(
            "ix_virtual_player_profiles_status_model",
            ["status", "model_provider", "model"],
        )
        batch_op.create_foreign_key(
            "fk_virtual_player_profiles_model_configuration",
            "model_configurations",
            ["model_provider", "model"],
            ["provider", "model_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.drop_constraint(
            "fk_virtual_player_profiles_model_configuration",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_virtual_player_profiles_status_model")
        batch_op.create_index(
            "ix_virtual_player_profiles_status_model",
            ["status", "model"],
        )
        batch_op.drop_column("model_provider")
