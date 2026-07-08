from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260708_01"
down_revision = "20260706_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_runs",
        sa.Column("run_id", sa.String(length=32), primary_key=True),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("villager_model", sa.String(length=120), nullable=False),
        sa.Column("werewolf_model", sa.String(length=120), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("rule_set_id", sa.String(length=40), nullable=False),
        sa.Column("rule_set", sa.JSON(), nullable=False),
        sa.Column("player_configs", sa.JSON(), nullable=False),
        sa.Column("lineup_quality_warnings", sa.JSON(), nullable=False),
        sa.Column("winner", sa.String(length=80), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_live_runs_session_id", "live_runs", ["session_id"])
    op.create_index("ix_live_runs_status", "live_runs", ["status"])
    op.create_index("ix_live_runs_updated_at", "live_runs", ["updated_at"])

    op.create_table(
        "live_events",
        sa.Column(
            "run_id",
            sa.String(length=32),
            sa.ForeignKey("live_runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("event_id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(length=40), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_live_events_run_id_event_id", "live_events", ["run_id", "event_id"])
    op.create_index("ix_live_events_session_id", "live_events", ["session_id"])
    op.create_index("ix_live_events_type", "live_events", ["type"])

    op.create_table(
        "voice_utterances",
        sa.Column("utterance_id", sa.String(length=32), primary_key=True),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=False),
        sa.Column("last_source_event_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("speaker_kind", sa.String(length=20), nullable=False),
        sa.Column("speaker_name", sa.String(length=80), nullable=False),
        sa.Column("speaker", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("audio_format", sa.String(length=20), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_voice_utterances_run_source_event",
        "voice_utterances",
        ["run_id", "source_event_id"],
    )
    op.create_index("ix_voice_utterances_request_id", "voice_utterances", ["request_id"])
    op.create_index("ix_voice_utterances_text_hash", "voice_utterances", ["text_hash"])
    op.create_index("ix_voice_utterances_status", "voice_utterances", ["status"])

    op.create_table(
        "voice_audio_chunks",
        sa.Column(
            "utterance_id",
            sa.String(length=32),
            sa.ForeignKey("voice_utterances.utterance_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chunk_index", sa.Integer(), primary_key=True),
        sa.Column("audio", sa.LargeBinary(), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("voice_audio_chunks")
    op.drop_index("ix_voice_utterances_status", table_name="voice_utterances")
    op.drop_index("ix_voice_utterances_text_hash", table_name="voice_utterances")
    op.drop_index("ix_voice_utterances_request_id", table_name="voice_utterances")
    op.drop_index("ix_voice_utterances_run_source_event", table_name="voice_utterances")
    op.drop_table("voice_utterances")
    op.drop_index("ix_live_events_type", table_name="live_events")
    op.drop_index("ix_live_events_session_id", table_name="live_events")
    op.drop_index("ix_live_events_run_id_event_id", table_name="live_events")
    op.drop_table("live_events")
    op.drop_index("ix_live_runs_updated_at", table_name="live_runs")
    op.drop_index("ix_live_runs_status", table_name="live_runs")
    op.drop_index("ix_live_runs_session_id", table_name="live_runs")
    op.drop_table("live_runs")
