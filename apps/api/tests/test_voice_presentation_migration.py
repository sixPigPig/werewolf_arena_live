from __future__ import annotations

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
    / "20260717_27_add_voice_presentation_id.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("voice_presentation_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_voice_presentation_migration_upgrade_and_downgrade() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260717_27"
    assert migration.down_revision == "20260717_26"

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE voice_utterances ("
                "utterance_id VARCHAR(64) NOT NULL PRIMARY KEY)"
            )
        )
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)
        migration.upgrade()

        columns = {
            column["name"]: column for column in inspect(connection).get_columns(
                "voice_utterances"
            )
        }
        assert columns["presentation_id"]["type"].length == 64
        assert columns["presentation_id"]["nullable"] is True

        migration.downgrade()
        assert {
            column["name"]
            for column in inspect(connection).get_columns("voice_utterances")
        } == {"utterance_id"}
