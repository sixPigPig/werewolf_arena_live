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
    / "20260805_53_create_v2_model_action_recoveries.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "v2_model_action_recovery_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_model_action_recovery_migration_upgrades_and_downgrades() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260805_53"
    assert migration.down_revision == "20260730_52"

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE v2_game_records (game_id VARCHAR(40) PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE v2_game_runs ("
                "run_id VARCHAR(40) PRIMARY KEY, game_id VARCHAR(40) NOT NULL)"
            )
        )
        connection.execute(
            text("CREATE TABLE v2_game_control_requests (id VARCHAR(36) PRIMARY KEY)")
        )
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        inspector = inspect(connection)
        columns = {
            item["name"]: item for item in inspector.get_columns("v2_model_action_recoveries")
        }
        assert {
            "action_id",
            "recovery_id",
            "game_id",
            "run_id",
            "request_payload",
            "request_hash",
            "model_context",
            "action_snapshot",
            "failure_category",
            "state",
            "control_request_id",
            "resolved_attempt_id",
        } <= set(columns)
        assert columns["action_id"]["primary_key"] == 1
        indexes = {item["name"] for item in inspector.get_indexes("v2_model_action_recoveries")}
        assert "ix_v2_model_action_recoveries_game_state" in indexes
        assert "ix_v2_model_action_recoveries_state_updated" in indexes

        migration.downgrade()

        assert "v2_model_action_recoveries" not in inspect(connection).get_table_names()
