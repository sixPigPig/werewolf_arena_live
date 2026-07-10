from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260709_01"
down_revision = "20260708_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "voice_utterances",
        sa.Column("subtitle_timings", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("voice_utterances", "subtitle_timings")
