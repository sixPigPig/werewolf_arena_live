"""scope replay voice by audience and backfill god-view wolf chat

Revision ID: 20260716_25
Revises: 20260715_24
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_25"
down_revision = "20260715_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "voice_utterances",
        sa.Column(
            "audience",
            sa.String(length=32),
            server_default="player_public",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_voice_utterances_session_audience",
        "voice_utterances",
        ["session_id", "audience"],
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    god_events = sa.Table("god_view_live_events", metadata, autoload_with=bind)
    jobs = sa.Table("voice_materialization_jobs", metadata, autoload_with=bind)
    message = god_events.c.payload["visible_result"]["message"].as_string()
    existing_job = sa.exists(
        sa.select(1).where(
            jobs.c.run_id == god_events.c.run_id,
            jobs.c.source_event_id == god_events.c.source_event_id,
            jobs.c.speaker_kind == "player",
        )
    )
    bind.execute(
        sa.insert(jobs).from_select(
            [
                "run_id",
                "source_event_id",
                "speaker_kind",
                "session_id",
                "audience",
                "status",
                "attempt_count",
                "not_before",
            ],
            sa.select(
                god_events.c.run_id,
                god_events.c.source_event_id,
                sa.literal("player"),
                god_events.c.session_id,
                sa.literal("spectator_god_view"),
                sa.literal("pending"),
                sa.literal(0),
                sa.func.now(),
            ).where(
                god_events.c.type == "action_parsed",
                god_events.c.action.in_(("werewolf_discuss", "werewolf_kill_vote")),
                message.is_not(None),
                sa.func.trim(message) != "",
                ~existing_job,
            ),
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM voice_materialization_jobs "
            "WHERE audience = 'spectator_god_view'"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM voice_utterances "
            "WHERE audience = 'spectator_god_view'"
        )
    )
    op.drop_index(
        "ix_voice_utterances_session_audience",
        table_name="voice_utterances",
    )
    op.drop_column("voice_utterances", "audience")
