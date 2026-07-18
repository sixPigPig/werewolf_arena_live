"""store player avatar assets as base64 text

Revision ID: 20260719_29
Revises: 20260718_28
Create Date: 2026-07-19
"""

from __future__ import annotations

import base64

from alembic import op
import sqlalchemy as sa


revision = "20260719_29"
down_revision = "20260718_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("player_avatar_assets") as batch_op:
        batch_op.add_column(sa.Column("data_base64", sa.Text(), nullable=True))

    connection = op.get_bind()
    assets = sa.table(
        "player_avatar_assets",
        sa.column("id", sa.String()),
        sa.column("data", sa.LargeBinary()),
        sa.column("data_base64", sa.Text()),
    )
    rows = connection.execute(sa.select(assets.c.id, assets.c.data)).mappings()
    for row in rows:
        encoded = base64.b64encode(bytes(row["data"])).decode("ascii")
        connection.execute(
            assets.update()
            .where(assets.c.id == row["id"])
            .values(data_base64=encoded)
        )

    with op.batch_alter_table("player_avatar_assets") as batch_op:
        batch_op.alter_column(
            "data_base64",
            existing_type=sa.Text(),
            nullable=False,
        )
        batch_op.drop_column("data")


def downgrade() -> None:
    with op.batch_alter_table("player_avatar_assets") as batch_op:
        batch_op.add_column(sa.Column("data", sa.LargeBinary(), nullable=True))

    connection = op.get_bind()
    assets = sa.table(
        "player_avatar_assets",
        sa.column("id", sa.String()),
        sa.column("data", sa.LargeBinary()),
        sa.column("data_base64", sa.Text()),
    )
    rows = connection.execute(
        sa.select(assets.c.id, assets.c.data_base64)
    ).mappings()
    for row in rows:
        decoded = base64.b64decode(row["data_base64"], validate=True)
        connection.execute(
            assets.update().where(assets.c.id == row["id"]).values(data=decoded)
        )

    with op.batch_alter_table("player_avatar_assets") as batch_op:
        batch_op.alter_column(
            "data",
            existing_type=sa.LargeBinary(),
            nullable=False,
        )
        batch_op.drop_column("data_base64")
