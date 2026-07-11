from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260711_10"
down_revision = "20260711_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.add_column(sa.Column("stop_requested_at", sa.DateTime(timezone=True)))
    op.create_table(
        "admin_run_control_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("target_run_id", sa.String(length=32), nullable=False),
        sa.Column("result_run_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_admin_run_control_actor_key",
        "admin_run_control_requests",
        ["actor_user_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_admin_run_control_actor_key",
        table_name="admin_run_control_requests",
    )
    op.drop_table("admin_run_control_requests")
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.drop_column("stop_requested_at")
