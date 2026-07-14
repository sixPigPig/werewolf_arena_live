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
    / "20260714_17_create_voice_materialization_jobs.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("voice_materialization_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_voice_materialization_migration_schema_and_downgrade() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260714_17"
    assert migration.down_revision == "20260712_16"

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE live_events ("
                "run_id VARCHAR(32) NOT NULL, "
                "event_id INTEGER NOT NULL, "
                "PRIMARY KEY (run_id, event_id))"
            )
        )
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)
        migration.upgrade()

        schema = inspect(connection)
        assert "voice_materialization_jobs" in schema.get_table_names()
        assert schema.get_pk_constraint("voice_materialization_jobs")["constrained_columns"] == [
            "run_id",
            "source_event_id",
            "speaker_kind",
        ]
        assert {
            index["name"] for index in schema.get_indexes("voice_materialization_jobs")
        } == {
            "ix_voice_materialization_jobs_claim",
            "ix_voice_materialization_jobs_session",
        }
        foreign_keys = schema.get_foreign_keys("voice_materialization_jobs")
        assert foreign_keys[0]["referred_table"] == "live_events"
        assert foreign_keys[0]["constrained_columns"] == ["run_id", "source_event_id"]

        migration.downgrade()
        assert "voice_materialization_jobs" not in inspect(connection).get_table_names()
