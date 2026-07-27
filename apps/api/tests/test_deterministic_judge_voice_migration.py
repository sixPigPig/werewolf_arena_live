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
    / "20260727_45_deterministic_judge_voice.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "deterministic_judge_voice_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deterministic_judge_voice_migration_upgrade_and_downgrade() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260727_45"
    assert migration.down_revision == "20260725_44"

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE judge_configurations ("
                "id VARCHAR(32) NOT NULL PRIMARY KEY, "
                "model_provider VARCHAR(32) NOT NULL, "
                "model_id VARCHAR(160) NOT NULL, "
                "tts_speaker VARCHAR(160) NOT NULL, "
                "version INTEGER NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE v2_game_records ("
                "game_id VARCHAR(40) NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO judge_configurations "
                "(id, model_provider, model_id, tts_speaker, version) "
                "VALUES ('default', 'agent_plan', 'judge-model', 'speaker-a', 3)"
            )
        )
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)
        migration.upgrade()

        judge_columns = {
            column["name"]
            for column in inspect(connection).get_columns("judge_configurations")
        }
        assert "model_provider" not in judge_columns
        assert "model_id" not in judge_columns
        assert {"voice_mode", "random_tts_speakers"} <= judge_columns
        game_columns = {
            column["name"]
            for column in inspect(connection).get_columns("v2_game_records")
        }
        assert "judge_voice_snapshot" in game_columns
        row = connection.execute(
            text(
                "SELECT voice_mode, random_tts_speakers "
                "FROM judge_configurations WHERE id = 'default'"
            )
        ).one()
        assert row == ("fixed", "[]")

        migration.downgrade()
        restored_judge_columns = {
            column["name"]
            for column in inspect(connection).get_columns("judge_configurations")
        }
        assert {"model_provider", "model_id"} <= restored_judge_columns
        assert "voice_mode" not in restored_judge_columns
        assert "random_tts_speakers" not in restored_judge_columns
        assert "judge_voice_snapshot" not in {
            column["name"]
            for column in inspect(connection).get_columns("v2_game_records")
        }
