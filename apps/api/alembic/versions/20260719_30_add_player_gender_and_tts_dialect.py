"""add player gender and TTS dialect

Revision ID: 20260719_30
Revises: 20260719_29
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260719_30"
down_revision = "20260719_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.add_column(
            sa.Column(
                "gender",
                sa.String(length=12),
                nullable=False,
                server_default="female",
            )
        )
        batch_op.add_column(
            sa.Column(
                "tts_dialect",
                sa.String(length=16),
                nullable=False,
                server_default="",
            )
        )

    profiles = sa.table(
        "virtual_player_profiles",
        sa.column("gender", sa.String()),
        sa.column("tts_speaker", sa.String()),
    )
    op.execute(
        profiles.update().values(
            gender=sa.case(
                (profiles.c.tts_speaker.contains("_male_", autoescape=True), "male"),
                else_="female",
            )
        )
    )

    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_gender",
            "gender IN ('female', 'male')",
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_tts_dialect",
            "tts_dialect IN ('', 'sichuan', 'shaanxi', 'northeast')",
        )


def downgrade() -> None:
    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_tts_dialect",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_gender",
            type_="check",
        )
        batch_op.drop_column("tts_dialect")
        batch_op.drop_column("gender")
