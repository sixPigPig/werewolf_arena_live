from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260711_11"
down_revision = "20260711_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.add_column(sa.Column("worker_id", sa.String(length=64)))
        batch_op.add_column(sa.Column("worker_heartbeat_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column(
                "control_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_index("ix_live_runs_worker_id", ["worker_id"])
        batch_op.create_index("ix_live_runs_lease_expires_at", ["lease_expires_at"])

    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT run_id,
                       row_number() OVER (
                           PARTITION BY session_id
                           ORDER BY created_at DESC, run_id DESC
                       ) AS active_rank
                FROM live_runs
                WHERE status IN ('queued', 'running')
            )
            UPDATE live_runs
            SET status = 'failed',
                error = COALESCE(error, 'Superseded duplicate active run'),
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
            WHERE run_id IN (
                SELECT run_id FROM ranked WHERE active_rank > 1
            )
            """
        )
    )
    op.create_index(
        "uq_live_runs_active_session",
        "live_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_live_runs_active_session", table_name="live_runs")
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.drop_index("ix_live_runs_lease_expires_at")
        batch_op.drop_index("ix_live_runs_worker_id")
        batch_op.drop_column("control_version")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("worker_heartbeat_at")
        batch_op.drop_column("worker_id")
