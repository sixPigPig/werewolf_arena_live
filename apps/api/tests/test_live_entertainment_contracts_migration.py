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
    / "20260718_28_add_live_entertainment_contracts.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "live_entertainment_contracts_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_entertainment_contracts_migration_upgrade_and_downgrade() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260718_28"
    assert migration.down_revision == "20260717_27"

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE virtual_player_profiles ("
                "id VARCHAR(64) NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE voice_materialization_jobs ("
                "run_id VARCHAR(32) NOT NULL, "
                "source_event_id INTEGER NOT NULL, "
                "speaker_kind VARCHAR(20) NOT NULL, "
                "PRIMARY KEY (run_id, source_event_id, speaker_kind))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE voice_utterances ("
                "utterance_id VARCHAR(40) NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE game_quality_evaluations ("
                "id VARCHAR(64) NOT NULL PRIMARY KEY)"
            )
        )
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)
        migration.upgrade()

        schema = inspect(connection)
        profile_columns = {
            column["name"]: column
            for column in schema.get_columns("virtual_player_profiles")
        }
        assert profile_columns["tts_speaker"]["type"].length == 160
        assert profile_columns["base_delivery_mood"]["type"].length == 24
        assert profile_columns["base_delivery_intensity"]["type"].length == 16
        assert profile_columns["base_delivery_pace"]["type"].length == 16
        assert profile_columns["base_delivery_instruction"]["type"].length == 240
        assert profile_columns["voice_enabled"]["nullable"] is False
        assert profile_columns["voice_config_version"]["nullable"] is False
        assert {
            constraint["name"]
            for constraint in schema.get_check_constraints("virtual_player_profiles")
        } == {
            "ck_virtual_player_profiles_delivery_intensity",
            "ck_virtual_player_profiles_delivery_mood",
            "ck_virtual_player_profiles_delivery_pace",
            "ck_virtual_player_profiles_voice_version_positive",
        }

        job_columns = {
            column["name"]
            for column in schema.get_columns("voice_materialization_jobs")
        }
        assert {
            "speaker",
            "effective_delivery",
            "effective_context_texts",
            "voice_config_version",
            "delivery_mapping_version",
            "tts_request_source",
        } <= job_columns

        utterance_columns = {
            column["name"] for column in schema.get_columns("voice_utterances")
        }
        assert {
            "effective_delivery",
            "effective_context_texts",
            "voice_config_version",
            "delivery_mapping_version",
            "tts_request_source",
        } <= utterance_columns
        assert "started_at" in {
            column["name"]
            for column in schema.get_columns("game_quality_evaluations")
        }

        migration.downgrade()

        schema = inspect(connection)
        assert {
            column["name"]
            for column in schema.get_columns("virtual_player_profiles")
        } == {"id"}
        assert {
            column["name"]
            for column in schema.get_columns("voice_materialization_jobs")
        } == {"run_id", "source_event_id", "speaker_kind"}
        assert {
            column["name"] for column in schema.get_columns("voice_utterances")
        } == {"utterance_id"}
        assert {
            column["name"]
            for column in schema.get_columns("game_quality_evaluations")
        } == {"id"}
