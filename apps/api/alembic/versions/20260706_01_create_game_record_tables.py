from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260706_01"
down_revision = "20260704_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_sessions",
        sa.Column("session_id", sa.String(length=32), primary_key=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("winner", sa.String(length=80), nullable=True),
        sa.Column("round_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rule_set", sa.JSON(), nullable=True),
        sa.Column("resumable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_game_sessions_status", "game_sessions", ["status"])
    op.create_index("ix_game_sessions_updated_at", "game_sessions", ["updated_at"])
    op.create_table(
        "game_replay_payloads",
        sa.Column(
            "session_id",
            sa.String(length=32),
            sa.ForeignKey("game_sessions.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("logs", sa.JSON(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("game_replay_payloads")
    op.drop_index("ix_game_sessions_updated_at", table_name="game_sessions")
    op.drop_index("ix_game_sessions_status", table_name="game_sessions")
    op.drop_table("game_sessions")
