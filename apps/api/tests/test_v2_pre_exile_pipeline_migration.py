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
    / "20260811_57_create_v2_pre_exile_pipeline.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "v2_pre_exile_pipeline_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pre_exile_pipeline_migration_upgrades_and_downgrades() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    assert migration.revision == "20260811_57"
    assert migration.down_revision == "20260811_56"

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE v2_game_records (game_id VARCHAR(40) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE v2_game_runs (run_id VARCHAR(40) PRIMARY KEY)"))
        connection.execute(
            text("CREATE TABLE v2_knowledge_facts (knowledge_fact_id VARCHAR(48) PRIMARY KEY)")
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        inspector = inspect(connection)
        assert {
            "v2_pre_exile_pipelines",
            "v2_pre_exile_results",
        } <= set(inspector.get_table_names())
        pipeline_columns = {
            column["name"] for column in inspector.get_columns("v2_pre_exile_pipelines")
        }
        assert {
            "predecessor_source_event_id",
            "predecessor_source_record_seq",
            "predecessor_sealed_record_seq",
            "public_cutoff_record_seq",
            "selected_explosion_player_id",
        } <= pipeline_columns
        result_columns = {
            column["name"] for column in inspector.get_columns("v2_pre_exile_results")
        }
        assert {
            "action_id",
            "response_record_seq",
            "terminal_record_seq",
            "result_record_seq",
            "private_fact_id",
            "private_fact_record_seq",
            "recovery_action_id",
            "recovery_response_record_seq",
            "recovery_terminal_record_seq",
        } <= result_columns
        result_unique_names = {
            item["name"] for item in inspector.get_unique_constraints("v2_pre_exile_results")
        }
        assert {
            "uq_v2_pre_exile_results_member",
            "uq_v2_pre_exile_results_action",
            "uq_v2_pre_exile_results_recovery_action",
        } <= result_unique_names

        migration.downgrade()
        assert "v2_pre_exile_pipelines" not in inspect(connection).get_table_names()

    engine.dispose()
