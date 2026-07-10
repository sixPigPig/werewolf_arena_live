from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260710_04"
down_revision = "20260710_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    game_sessions = sa.table(
        "game_sessions",
        sa.column("status", sa.String(length=20)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("session_id", sa.String(length=32)),
    )
    op.create_index(
        "ix_game_sessions_created_at_session_id_desc",
        "game_sessions",
        [game_sessions.c.created_at.desc(), game_sessions.c.session_id.desc()],
    )
    op.create_index(
        "ix_game_sessions_status_created_at_session_id_desc",
        "game_sessions",
        [
            game_sessions.c.status,
            game_sessions.c.created_at.desc(),
            game_sessions.c.session_id.desc(),
        ],
    )
    live_runs = sa.table(
        "live_runs",
        sa.column("session_id", sa.String(length=32)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("run_id", sa.String(length=32)),
    )
    op.create_index(
        "ix_live_runs_session_created_run_desc",
        "live_runs",
        [
            live_runs.c.session_id,
            live_runs.c.created_at.desc(),
            live_runs.c.run_id.desc(),
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_runs_session_created_run_desc",
        table_name="live_runs",
    )
    op.drop_index(
        "ix_game_sessions_status_created_at_session_id_desc",
        table_name="game_sessions",
    )
    op.drop_index(
        "ix_game_sessions_created_at_session_id_desc",
        table_name="game_sessions",
    )
