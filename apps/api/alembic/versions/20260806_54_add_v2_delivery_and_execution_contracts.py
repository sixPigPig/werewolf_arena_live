"""add V2 delivery and execution contracts

Revision ID: 20260806_54
Revises: 20260805_53
Create Date: 2026-08-06
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260806_54"
down_revision = "20260805_53"
branch_labels = None
depends_on = None


_ACTIVE_STATES = (
    "status IN ('ready', 'generating', 'broadcasting', 'finalizing', "
    "'paused_model_error', 'awaiting_observation')"
)
_LEGACY_DELIVERY_SNAPSHOT = json.dumps(
    {
        "schema_version": 1,
        "mode": "legacy_unknown",
        "source": "pre_contract_record",
    },
    separators=(",", ":"),
    sort_keys=True,
)


def upgrade() -> None:
    with op.batch_alter_table("v2_game_records") as batch_op:
        batch_op.add_column(sa.Column("delivery_snapshot", sa.JSON(), nullable=True))
    bind = op.get_bind()
    snapshot_value = sa.bindparam(
        "legacy_delivery_snapshot",
        value=_LEGACY_DELIVERY_SNAPSHOT,
        type_=sa.String(),
    )
    if bind.dialect.name == "postgresql":
        backfill = sa.text(
            "UPDATE v2_game_records "
            "SET delivery_snapshot = CAST(:legacy_delivery_snapshot AS JSON) "
            "WHERE delivery_snapshot IS NULL"
        )
    else:
        backfill = sa.text(
            "UPDATE v2_game_records "
            "SET delivery_snapshot = :legacy_delivery_snapshot "
            "WHERE delivery_snapshot IS NULL"
        )
    op.execute(backfill.bindparams(snapshot_value))

    with op.batch_alter_table("v2_game_runs") as batch_op:
        batch_op.add_column(sa.Column("worker_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("worker_heartbeat_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("fence_token", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "ck_v2_game_runs_fence_nonnegative",
            "fence_token >= 0",
        )
        batch_op.create_index("ix_v2_game_runs_worker_id", ["worker_id"])
        batch_op.create_index("ix_v2_game_runs_lease_expires_at", ["lease_expires_at"])
    op.create_index(
        "ix_v2_game_runs_active_lease",
        "v2_game_runs",
        ["status", "lease_expires_at"],
        postgresql_where=sa.text(_ACTIVE_STATES),
        sqlite_where=sa.text(_ACTIVE_STATES),
    )


def downgrade() -> None:
    op.drop_index("ix_v2_game_runs_active_lease", table_name="v2_game_runs")
    with op.batch_alter_table("v2_game_runs") as batch_op:
        batch_op.drop_index("ix_v2_game_runs_lease_expires_at")
        batch_op.drop_index("ix_v2_game_runs_worker_id")
        batch_op.drop_constraint("ck_v2_game_runs_fence_nonnegative", type_="check")
        batch_op.drop_column("fence_token")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("worker_heartbeat_at")
        batch_op.drop_column("worker_id")
    with op.batch_alter_table("v2_game_records") as batch_op:
        batch_op.drop_column("delivery_snapshot")
