from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260719_29_store_player_avatars_as_base64.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "player_avatar_base64_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_player_avatar_base64_migration_upgrade_and_downgrade() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    original = b"\x89PNG\r\n\x1a\nplayer-avatar"

    assert migration.revision == "20260719_29"
    assert migration.down_revision == "20260718_28"

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE player_avatar_assets ("
                "id VARCHAR(80) NOT NULL PRIMARY KEY, "
                "data BLOB NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO player_avatar_assets (id, data) "
                "VALUES ('system-test-avatar', :data)"
            ),
            {"data": original},
        )
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)

        migration.upgrade()

        assert {
            column["name"]
            for column in inspect(connection).get_columns("player_avatar_assets")
        } == {"id", "data_base64"}
        encoded = connection.scalar(
            text(
                "SELECT data_base64 FROM player_avatar_assets "
                "WHERE id = 'system-test-avatar'"
            )
        )
        assert encoded == base64.b64encode(original).decode("ascii")

        migration.downgrade()

        assert {
            column["name"]
            for column in inspect(connection).get_columns("player_avatar_assets")
        } == {"id", "data"}
        restored = connection.scalar(
            text(
                "SELECT data FROM player_avatar_assets "
                "WHERE id = 'system-test-avatar'"
            )
        )
        assert bytes(restored) == original
