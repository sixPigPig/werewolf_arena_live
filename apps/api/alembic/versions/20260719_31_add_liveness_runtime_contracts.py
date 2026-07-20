"""add liveness runtime contracts

Revision ID: 20260719_31
Revises: 20260719_30
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260719_31"
down_revision = "20260719_30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("game_sessions", "live_runs"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column("liveness_experience_revision", sa.String(length=40), nullable=True)
            )
            batch_op.add_column(
                sa.Column("liveness_experience_snapshot", sa.JSON(), nullable=True)
            )
            batch_op.add_column(
                sa.Column("liveness_experiment_id", sa.String(length=64), nullable=True)
            )
            batch_op.add_column(
                sa.Column("liveness_experiment_variant", sa.String(length=64), nullable=True)
            )
            batch_op.create_index(
                f"ix_{table_name}_liveness_experience_revision",
                ["liveness_experience_revision"],
                unique=False,
            )

    op.create_table(
        "actor_mind_snapshots",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_source_run_id", sa.String(length=32), nullable=True),
        sa.Column("last_source_event_id", sa.Integer(), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "actor"),
    )
    op.create_index(
        "ix_actor_mind_snapshots_session", "actor_mind_snapshots", ["session_id"]
    )

    op.create_table(
        "speech_turn_receipts",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("action_id", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(length=40), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=True),
        sa.Column("experience_revision", sa.String(length=40), nullable=False),
        sa.Column("plan_id", sa.String(length=40), nullable=True),
        sa.Column("fence", sa.JSON(), nullable=True),
        sa.Column("scene_packet_hash", sa.String(length=64), nullable=True),
        sa.Column("planner_request_id", sa.String(length=80), nullable=True),
        sa.Column("renderer_attempts", sa.JSON(), nullable=False),
        sa.Column("accepted_renderer_request_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("delivery_snapshot", sa.JSON(), nullable=True),
        sa.Column("actor_mind_revision_before", sa.Integer(), nullable=True),
        sa.Column("actor_mind_revision_after", sa.Integer(), nullable=True),
        sa.Column("actor_mind_delta", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "action_id"),
    )
    op.create_index(
        "ix_speech_turn_receipts_session_status",
        "speech_turn_receipts",
        ["session_id", "status"],
    )

    op.create_table(
        "speech_turn_segments",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("action_id", sa.String(length=40), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.String(length=40), nullable=False),
        sa.Column("speech_id", sa.String(length=40), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("source_run_id", sa.String(length=32), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("presentation_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "action_id"],
            ["speech_turn_receipts.session_id", "speech_turn_receipts.action_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", "action_id", "segment_index"),
        sa.UniqueConstraint("segment_id", name="uq_speech_turn_segments_segment_id"),
        sa.UniqueConstraint(
            "presentation_id", name="uq_speech_turn_segments_presentation_id"
        ),
    )
    op.create_index(
        "ix_speech_turn_segments_speech_id", "speech_turn_segments", ["speech_id"]
    )
    op.create_index(
        "ix_speech_turn_segments_source",
        "speech_turn_segments",
        ["source_run_id", "source_event_id"],
    )

    with op.batch_alter_table("voice_utterances") as batch_op:
        batch_op.add_column(sa.Column("action_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("speech_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("segment_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("segment_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("segment_final", sa.Boolean(), nullable=True))
        batch_op.create_index("ix_voice_utterances_action_id", ["action_id"], unique=False)
        batch_op.create_index("ix_voice_utterances_speech_id", ["speech_id"], unique=False)
        batch_op.create_unique_constraint(
            "uq_voice_utterances_segment_id", ["segment_id"]
        )

    op.create_table(
        "voice_playback_observations",
        sa.Column("playback_session_id", sa.String(length=64), nullable=False),
        sa.Column("utterance_id", sa.String(length=40), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("speech_id", sa.String(length=40), nullable=True),
        sa.Column("server_terminal_status", sa.String(length=24), nullable=False),
        sa.Column("client_status", sa.String(length=20), nullable=True),
        sa.Column("played_ms", sa.Integer(), nullable=True),
        sa.Column(
            "first_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["utterance_id"], ["voice_utterances.utterance_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("playback_session_id", "utterance_id"),
    )
    op.create_index(
        "ix_voice_playback_observations_session",
        "voice_playback_observations",
        ["session_id"],
    )
    op.create_index(
        "ix_voice_playback_observations_updated_at",
        "voice_playback_observations",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_playback_observations_updated_at",
        table_name="voice_playback_observations",
    )
    op.drop_index(
        "ix_voice_playback_observations_session",
        table_name="voice_playback_observations",
    )
    op.drop_table("voice_playback_observations")

    with op.batch_alter_table("voice_utterances") as batch_op:
        batch_op.drop_constraint("uq_voice_utterances_segment_id", type_="unique")
        batch_op.drop_index("ix_voice_utterances_speech_id")
        batch_op.drop_index("ix_voice_utterances_action_id")
        batch_op.drop_column("segment_final")
        batch_op.drop_column("segment_index")
        batch_op.drop_column("segment_id")
        batch_op.drop_column("speech_id")
        batch_op.drop_column("action_id")

    op.drop_index("ix_speech_turn_segments_source", table_name="speech_turn_segments")
    op.drop_index("ix_speech_turn_segments_speech_id", table_name="speech_turn_segments")
    op.drop_table("speech_turn_segments")
    op.drop_index(
        "ix_speech_turn_receipts_session_status", table_name="speech_turn_receipts"
    )
    op.drop_table("speech_turn_receipts")
    op.drop_index("ix_actor_mind_snapshots_session", table_name="actor_mind_snapshots")
    op.drop_table("actor_mind_snapshots")

    for table_name in ("live_runs", "game_sessions"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_liveness_experience_revision")
            batch_op.drop_column("liveness_experiment_variant")
            batch_op.drop_column("liveness_experiment_id")
            batch_op.drop_column("liveness_experience_snapshot")
            batch_op.drop_column("liveness_experience_revision")
