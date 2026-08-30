"""drop V1 live, voice, replay, and quality tables

Revision ID: 20260820_58
Revises: 20260811_57
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260820_58"
down_revision = "20260811_57"
branch_labels = None
depends_on = None

# Children first. CASCADE is used on PostgreSQL so leftover FKs cannot block the drop.
_V1_LIVE_TABLES = (
    "voice_audio_chunks",
    "voice_utterances",
    "voice_materialization_jobs",
    "public_live_events",
    "god_view_live_events",
    "live_events",
    "live_runs",
    "speech_turn_segments",
    "speech_turn_receipts",
    "voice_playback_observations",
    "actor_mind_snapshots",
    "game_replay_payloads",
    "game_sessions",
    "game_quality_evaluations",
    "admin_run_control_requests",
)


def upgrade() -> None:
    cascade = " CASCADE" if op.get_bind().dialect.name == "postgresql" else ""
    for table_name in _V1_LIVE_TABLES:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {table_name}{cascade}"))


def downgrade() -> None:
    raise NotImplementedError("V1 live tables cannot be restored")
