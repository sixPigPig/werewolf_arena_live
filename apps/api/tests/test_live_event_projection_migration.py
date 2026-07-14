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
    / "20260715_21_create_live_event_projections.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("live_event_projection_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_projection_migration_upgrade_downgrade_upgrade_cycle() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260715_21"
    assert migration.down_revision == "20260714_20"

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE live_events ("
                "run_id VARCHAR(32) NOT NULL, "
                "event_id INTEGER NOT NULL, "
                "PRIMARY KEY (run_id, event_id))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE voice_materialization_jobs ("
                "run_id VARCHAR(32) NOT NULL, "
                "source_event_id INTEGER NOT NULL, "
                "speaker_kind VARCHAR(20) NOT NULL, "
                "status VARCHAR(20) NOT NULL, "
                "PRIMARY KEY (run_id, source_event_id, speaker_kind))"
            )
        )
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)

        migration.upgrade()
        schema = inspect(connection)
        assert {"public_live_events", "god_view_live_events"}.issubset(
            schema.get_table_names()
        )
        assert "audience" in {
            column["name"]
            for column in schema.get_columns("voice_materialization_jobs")
        }
        for table_name in ("public_live_events", "god_view_live_events"):
            foreign_keys = schema.get_foreign_keys(table_name)
            assert foreign_keys[0]["referred_table"] == "live_events"
            assert foreign_keys[0]["constrained_columns"] == [
                "run_id",
                "source_event_id",
            ]

        migration.downgrade()
        schema = inspect(connection)
        assert "public_live_events" not in schema.get_table_names()
        assert "god_view_live_events" not in schema.get_table_names()
        assert "audience" not in {
            column["name"]
            for column in schema.get_columns("voice_materialization_jobs")
        }

        migration.upgrade()
        assert {"public_live_events", "god_view_live_events"}.issubset(
            inspect(connection).get_table_names()
        )
