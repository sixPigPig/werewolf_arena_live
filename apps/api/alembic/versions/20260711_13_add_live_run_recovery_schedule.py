from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260711_13"
down_revision = "20260711_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "recovery_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("recovery_last_attempt_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("recovery_not_before", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("recovery_last_error", sa.Text()))
        batch_op.create_index(
            "ix_live_runs_recovery_not_before",
            ["recovery_not_before"],
        )


def downgrade() -> None:
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.drop_index("ix_live_runs_recovery_not_before")
        batch_op.drop_column("recovery_last_error")
        batch_op.drop_column("recovery_not_before")
        batch_op.drop_column("recovery_last_attempt_at")
        batch_op.drop_column("recovery_attempts")
