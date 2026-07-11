from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260711_14"
down_revision = "20260711_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_workers",
        sa.Column("worker_id", sa.String(length=64), primary_key=True),
        sa.Column("worker_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column("scans_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "recoveries_resumed_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "recoveries_canceled_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "recoveries_failed_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("errors_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_runtime_workers_worker_type", "runtime_workers", ["worker_type"])
    op.create_index("ix_runtime_workers_status", "runtime_workers", ["status"])
    op.create_index("ix_runtime_workers_heartbeat_at", "runtime_workers", ["heartbeat_at"])
    op.create_index(
        "ix_runtime_workers_type_heartbeat_desc",
        "runtime_workers",
        ["worker_type", sa.text("heartbeat_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_workers_type_heartbeat_desc", table_name="runtime_workers")
    op.drop_index("ix_runtime_workers_heartbeat_at", table_name="runtime_workers")
    op.drop_index("ix_runtime_workers_status", table_name="runtime_workers")
    op.drop_index("ix_runtime_workers_worker_type", table_name="runtime_workers")
    op.drop_table("runtime_workers")
