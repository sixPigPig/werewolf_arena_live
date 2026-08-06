from __future__ import annotations

import importlib.util
from io import StringIO
import json
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260806_54_add_v2_delivery_and_execution_contracts.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "v2_delivery_execution_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_delivery_execution_migration_upgrades_and_downgrades() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260806_54"
    assert migration.down_revision == "20260805_53"

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE v2_game_records ("
                "game_id VARCHAR(40) PRIMARY KEY, current_run_id VARCHAR(40) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE v2_game_runs ("
                "run_id VARCHAR(40) PRIMARY KEY, game_id VARCHAR(40) NOT NULL, "
                "status VARCHAR(32) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO v2_game_records (game_id, current_run_id) "
                "VALUES ('v2_game_legacy000000', 'v2_run_legacy0000000')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO v2_game_runs (run_id, game_id, status) "
                "VALUES ('v2_run_legacy0000000', 'v2_game_legacy000000', "
                "'awaiting_observation')"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        inspector = inspect(connection)
        game_columns = {item["name"]: item for item in inspector.get_columns("v2_game_records")}
        run_columns = {item["name"]: item for item in inspector.get_columns("v2_game_runs")}
        assert "delivery_snapshot" in game_columns
        assert {
            "worker_id",
            "worker_heartbeat_at",
            "lease_expires_at",
            "fence_token",
        } <= set(run_columns)
        assert run_columns["fence_token"]["nullable"] is False
        assert str(run_columns["fence_token"]["default"]).strip("'\"") in {"0", "0.0"}

        raw_snapshot = connection.execute(
            text(
                "SELECT delivery_snapshot FROM v2_game_records "
                "WHERE game_id = 'v2_game_legacy000000'"
            )
        ).scalar_one()
        snapshot = json.loads(raw_snapshot) if isinstance(raw_snapshot, str) else raw_snapshot
        assert snapshot == {
            "schema_version": 1,
            "mode": "legacy_unknown",
            "source": "pre_contract_record",
        }

        run_indexes = inspector.get_indexes("v2_game_runs")
        index_names = {item["name"] for item in run_indexes}
        assert {
            "ix_v2_game_runs_worker_id",
            "ix_v2_game_runs_lease_expires_at",
            "ix_v2_game_runs_active_lease",
        } <= index_names
        active_lease_index = next(
            item for item in run_indexes if item["name"] == "ix_v2_game_runs_active_lease"
        )
        assert "awaiting_observation" in str(
            active_lease_index["dialect_options"]["sqlite_where"]
        )
        check_names = {
            item["name"] for item in inspector.get_check_constraints("v2_game_runs")
        }
        assert "ck_v2_game_runs_fence_nonnegative" in check_names

        migration.downgrade()

        inspector = inspect(connection)
        assert "delivery_snapshot" not in {
            item["name"] for item in inspector.get_columns("v2_game_records")
        }
        assert "worker_id" not in {
            item["name"] for item in inspector.get_columns("v2_game_runs")
        }


def test_v2_delivery_execution_migration_renders_postgresql_offline_sql() -> None:
    migration = _load_migration()
    output = StringIO()
    migration.op = Operations(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={
                "as_sql": True,
                "literal_binds": True,
                "output_buffer": output,
            },
        )
    )

    migration.upgrade()

    rendered = output.getvalue()
    assert "ALTER TABLE v2_game_records ADD COLUMN delivery_snapshot JSON" in rendered
    assert "UPDATE v2_game_records" in rendered
    assert "CAST(" in rendered
    assert "legacy_unknown" in rendered
    assert "pre_contract_record" in rendered
    assert "CREATE INDEX ix_v2_game_runs_active_lease" in rendered
