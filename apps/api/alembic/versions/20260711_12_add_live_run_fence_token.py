from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260711_12"
down_revision = "20260711_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "fence_token",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.drop_column("fence_token")
