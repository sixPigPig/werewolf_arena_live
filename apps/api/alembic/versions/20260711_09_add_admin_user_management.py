from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260711_09"
down_revision = "20260711_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "admin_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )

    op.create_table(
        "admin_user_provisioning_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_admin_user_provisioning_actor_key",
        "admin_user_provisioning_requests",
        ["actor_user_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_admin_user_provisioning_actor_key",
        table_name="admin_user_provisioning_requests",
    )
    op.drop_table("admin_user_provisioning_requests")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("admin_version")
