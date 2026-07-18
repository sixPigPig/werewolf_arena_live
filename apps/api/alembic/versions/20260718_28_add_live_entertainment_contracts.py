"""add live entertainment voice and quality contracts

Revision ID: 20260718_28
Revises: 20260717_27
Create Date: 2026-07-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260718_28"
down_revision = "20260717_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.add_column(
            sa.Column(
                "tts_speaker",
                sa.String(length=160),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "base_delivery_mood",
                sa.String(length=24),
                nullable=False,
                server_default="neutral",
            )
        )
        batch_op.add_column(
            sa.Column(
                "base_delivery_intensity",
                sa.String(length=16),
                nullable=False,
                server_default="medium",
            )
        )
        batch_op.add_column(
            sa.Column(
                "base_delivery_pace",
                sa.String(length=16),
                nullable=False,
                server_default="natural",
            )
        )
        batch_op.add_column(
            sa.Column(
                "base_delivery_instruction",
                sa.String(length=240),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "voice_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "voice_config_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_delivery_mood",
            "base_delivery_mood IN ('neutral', 'restrained', 'calm', 'confident', "
            "'skeptical', 'tense', 'frustrated', 'urgent', 'sad', 'excited', 'playful')",
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_delivery_intensity",
            "base_delivery_intensity IN ('low', 'medium', 'high')",
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_delivery_pace",
            "base_delivery_pace IN ('slow', 'natural', 'fast')",
        )
        batch_op.create_check_constraint(
            "ck_virtual_player_profiles_voice_version_positive",
            "voice_config_version >= 1",
        )

    with op.batch_alter_table("voice_materialization_jobs") as batch_op:
        batch_op.add_column(sa.Column("speaker", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("effective_delivery", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("effective_context_texts", sa.JSON(), nullable=True)
        )
        batch_op.add_column(sa.Column("voice_config_version", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("delivery_mapping_version", sa.String(length=40), nullable=True)
        )
        batch_op.add_column(
            sa.Column("tts_request_source", sa.String(length=40), nullable=True)
        )

    with op.batch_alter_table("voice_utterances") as batch_op:
        batch_op.add_column(sa.Column("effective_delivery", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("effective_context_texts", sa.JSON(), nullable=True)
        )
        batch_op.add_column(sa.Column("voice_config_version", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("delivery_mapping_version", sa.String(length=40), nullable=True)
        )
        batch_op.add_column(
            sa.Column("tts_request_source", sa.String(length=40), nullable=True)
        )

    with op.batch_alter_table("game_quality_evaluations") as batch_op:
        batch_op.add_column(
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("game_quality_evaluations") as batch_op:
        batch_op.drop_column("started_at")

    with op.batch_alter_table("voice_utterances") as batch_op:
        batch_op.drop_column("tts_request_source")
        batch_op.drop_column("delivery_mapping_version")
        batch_op.drop_column("voice_config_version")
        batch_op.drop_column("effective_context_texts")
        batch_op.drop_column("effective_delivery")

    with op.batch_alter_table("voice_materialization_jobs") as batch_op:
        batch_op.drop_column("tts_request_source")
        batch_op.drop_column("delivery_mapping_version")
        batch_op.drop_column("voice_config_version")
        batch_op.drop_column("effective_context_texts")
        batch_op.drop_column("effective_delivery")
        batch_op.drop_column("speaker")

    with op.batch_alter_table("virtual_player_profiles") as batch_op:
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_voice_version_positive",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_delivery_pace",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_delivery_intensity",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_virtual_player_profiles_delivery_mood",
            type_="check",
        )
        batch_op.drop_column("voice_config_version")
        batch_op.drop_column("voice_enabled")
        batch_op.drop_column("base_delivery_instruction")
        batch_op.drop_column("base_delivery_pace")
        batch_op.drop_column("base_delivery_intensity")
        batch_op.drop_column("base_delivery_mood")
        batch_op.drop_column("tts_speaker")
