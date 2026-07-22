"""add live v2 realtime action voice assets

Revision ID: 20260722_36
Revises: 20260721_35
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_36"
down_revision = "20260721_35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_voice_assets",
        sa.Column("voice_asset_id", sa.String(length=48), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("action_id", sa.String(length=48), nullable=False),
        sa.Column("presentation_id", sa.String(length=48), nullable=False),
        sa.Column("speech_id", sa.String(length=48), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("storage_key", sa.String(length=240), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("pcm_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["v2_game_records.game_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["v2_game_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("voice_asset_id"),
        sa.UniqueConstraint(
            "presentation_id",
            "speech_id",
            "segment_index",
            name="uq_v2_voice_assets_segment",
        ),
    )
    op.create_index("ix_v2_voice_assets_game_id", "v2_voice_assets", ["game_id"])
    op.create_index("ix_v2_voice_assets_run_id", "v2_voice_assets", ["run_id"])
    op.create_index("ix_v2_voice_assets_action_id", "v2_voice_assets", ["action_id"])
    op.create_index("ix_v2_voice_assets_state", "v2_voice_assets", ["state"])

    op.add_column(
        "v2_live_presentations",
        sa.Column("action_id", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "v2_live_presentations",
        sa.Column("voice_asset_id", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "v2_live_presentations",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "v2_live_presentations",
        "audio_asset_id",
        existing_type=sa.String(length=80),
        nullable=True,
    )
    op.alter_column(
        "v2_live_presentations",
        "audio_mime_type",
        existing_type=sa.String(length=80),
        nullable=True,
    )
    op.create_index(
        "ix_v2_presentations_action_id",
        "v2_live_presentations",
        ["action_id"],
    )
    op.create_index(
        "ix_v2_presentations_voice_asset_id",
        "v2_live_presentations",
        ["voice_asset_id"],
    )
    op.create_foreign_key(
        "fk_v2_presentations_voice_asset",
        "v2_live_presentations",
        "v2_voice_assets",
        ["voice_asset_id"],
        ["voice_asset_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_v2_presentations_voice_asset",
        "v2_live_presentations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_v2_presentations_voice_asset_id",
        table_name="v2_live_presentations",
    )
    op.drop_index("ix_v2_presentations_action_id", table_name="v2_live_presentations")
    op.alter_column(
        "v2_live_presentations",
        "audio_mime_type",
        existing_type=sa.String(length=80),
        nullable=False,
    )
    op.alter_column(
        "v2_live_presentations",
        "audio_asset_id",
        existing_type=sa.String(length=80),
        nullable=False,
    )
    op.drop_column("v2_live_presentations", "closed_at")
    op.drop_column("v2_live_presentations", "voice_asset_id")
    op.drop_column("v2_live_presentations", "action_id")
    op.drop_table("v2_voice_assets")
