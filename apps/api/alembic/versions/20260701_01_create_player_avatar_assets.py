from __future__ import annotations

import hashlib
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "20260701_01"
down_revision = "20260517_02"
branch_labels = None
depends_on = None

SYSTEM_AVATARS = {
    "gothic-male-1": "system-gothic-male-1",
    "gothic-male-2": "system-gothic-male-2",
    "gothic-female-1": "system-gothic-female-1",
    "gothic-female-2": "system-gothic-female-2",
}


def upgrade() -> None:
    op.create_table(
        "player_avatar_assets",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_player_avatar_assets_sha256",
        "player_avatar_assets",
        ["sha256"],
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("avatar_asset_id", sa.String(length=80), nullable=True),
    )
    op.create_foreign_key(
        "fk_virtual_player_profiles_avatar_asset_id",
        "virtual_player_profiles",
        "player_avatar_assets",
        ["avatar_asset_id"],
        ["id"],
    )
    _seed_system_avatar_assets()
    _backfill_system_avatar_profiles()


def downgrade() -> None:
    op.drop_constraint(
        "fk_virtual_player_profiles_avatar_asset_id",
        "virtual_player_profiles",
        type_="foreignkey",
    )
    op.drop_column("virtual_player_profiles", "avatar_asset_id")
    op.drop_index("ix_player_avatar_assets_sha256", table_name="player_avatar_assets")
    op.drop_table("player_avatar_assets")


def _seed_system_avatar_assets() -> None:
    connection = op.get_bind()
    assets_dir = Path(__file__).resolve().parents[2] / "app" / "assets" / "player_avatars"
    rows = []
    for appearance_id, asset_id in SYSTEM_AVATARS.items():
        data = (assets_dir / f"{appearance_id}.png").read_bytes()
        rows.append(
            {
                "id": asset_id,
                "source": "system",
                "content_type": "image/png",
                "data": data,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    table = sa.table(
        "player_avatar_assets",
        sa.column("id", sa.String),
        sa.column("source", sa.String),
        sa.column("content_type", sa.String),
        sa.column("data", sa.LargeBinary),
        sa.column("sha256", sa.String),
        sa.column("size_bytes", sa.Integer),
    )
    connection.execute(table.insert(), rows)


def _backfill_system_avatar_profiles() -> None:
    connection = op.get_bind()
    for appearance_id, asset_id in SYSTEM_AVATARS.items():
        legacy_url = f"/player-avatars/{appearance_id}.png"
        connection.execute(
            sa.text(
                """
                UPDATE virtual_player_profiles
                SET avatar_asset_id = :asset_id,
                    avatar_image_mime = 'image/png'
                WHERE avatar_asset_id IS NULL
                  AND (appearance_id = :appearance_id OR avatar_image_url = :legacy_url)
                """
            ),
            {
                "asset_id": asset_id,
                "appearance_id": appearance_id,
                "legacy_url": legacy_url,
            },
        )
