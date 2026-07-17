"""enqueue missing god-view-only judge voice jobs

Revision ID: 20260717_26
Revises: 20260716_25
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260717_26"
down_revision = "20260716_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    god_events = sa.Table("god_view_live_events", metadata, autoload_with=bind)
    public_events = sa.Table("public_live_events", metadata, autoload_with=bind)
    jobs = sa.Table("voice_materialization_jobs", metadata, autoload_with=bind)

    public_event = sa.exists(
        sa.select(1).where(
            public_events.c.run_id == god_events.c.run_id,
            public_events.c.event_id == god_events.c.event_id,
        )
    )
    existing_job = sa.exists(
        sa.select(1).where(
            jobs.c.run_id == god_events.c.run_id,
            jobs.c.source_event_id == god_events.c.source_event_id,
            jobs.c.speaker_kind == "judge",
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
                sa.literal("judge"),
                god_events.c.session_id,
                sa.literal("spectator_god_view"),
                sa.literal("pending"),
                sa.literal(0),
                sa.func.now(),
            ).where(
                god_events.c.type == "judge_cue",
                ~public_event,
                ~existing_job,
            ),
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    god_events = sa.Table("god_view_live_events", metadata, autoload_with=bind)
    public_events = sa.Table("public_live_events", metadata, autoload_with=bind)
    jobs = sa.Table("voice_materialization_jobs", metadata, autoload_with=bind)

    god_only_judge_cue = sa.exists(
        sa.select(1).where(
            god_events.c.run_id == jobs.c.run_id,
            god_events.c.source_event_id == jobs.c.source_event_id,
            god_events.c.type == "judge_cue",
            ~sa.exists(
                sa.select(1).where(
                    public_events.c.run_id == god_events.c.run_id,
                    public_events.c.event_id == god_events.c.event_id,
                )
            ),
        )
    )
    bind.execute(
        sa.delete(jobs).where(
            jobs.c.audience == "spectator_god_view",
            jobs.c.speaker_kind == "judge",
            god_only_judge_cue,
        )
    )
