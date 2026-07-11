from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260711_05"
down_revision = "20260710_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    live_runs = sa.table(
        "live_runs",
        sa.column("status", sa.String(length=20)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("run_id", sa.String(length=32)),
    )
    op.create_index(
        "ix_live_runs_updated_at_run_id_desc",
        "live_runs",
        [live_runs.c.updated_at.desc(), live_runs.c.run_id.desc()],
    )
    op.create_index(
        "ix_live_runs_created_at_run_id_desc",
        "live_runs",
        [live_runs.c.created_at.desc(), live_runs.c.run_id.desc()],
    )
    op.create_index(
        "ix_live_runs_status_updated_at_run_id_desc",
        "live_runs",
        [
            live_runs.c.status,
            live_runs.c.updated_at.desc(),
            live_runs.c.run_id.desc(),
        ],
    )
    op.create_index(
        "ix_voice_utterances_run_status",
        "voice_utterances",
        ["run_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_utterances_run_status",
        table_name="voice_utterances",
    )
    op.drop_index(
        "ix_live_runs_status_updated_at_run_id_desc",
        table_name="live_runs",
    )
    op.drop_index(
        "ix_live_runs_created_at_run_id_desc",
        table_name="live_runs",
    )
    op.drop_index(
        "ix_live_runs_updated_at_run_id_desc",
        table_name="live_runs",
    )
