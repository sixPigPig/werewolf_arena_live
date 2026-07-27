from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260727_46_add_player_model_provider.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "player_model_provider_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_previous_schema(connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE model_configurations ("
            "provider VARCHAR(32) NOT NULL, "
            "model_id VARCHAR(160) NOT NULL, "
            "PRIMARY KEY (provider, model_id))"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE virtual_player_profiles ("
            "id VARCHAR(36) NOT NULL PRIMARY KEY, "
            "status VARCHAR(20) NOT NULL, "
            "model VARCHAR(120) NOT NULL)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX ix_virtual_player_profiles_status_model "
            "ON virtual_player_profiles (status, model)"
        )
    )


def test_player_model_provider_migration_backfills_unique_provider_and_downgrades() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260727_46"
    assert migration.down_revision == "20260727_45"

    with engine.begin() as connection:
        _create_previous_schema(connection)
        connection.execute(
            text(
                "INSERT INTO model_configurations (provider, model_id) VALUES "
                "('deepseek', 'deepseek-v4-flash'), "
                "('agent_plan', 'doubao-seed-2-0-lite-260215')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO virtual_player_profiles (id, status, model) VALUES "
                "('profile-1', 'published', 'deepseek-v4-flash')"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        columns = {
            item["name"]: item
            for item in inspect(connection).get_columns("virtual_player_profiles")
        }
        assert columns["model_provider"]["nullable"] is False
        assert connection.execute(
            text(
                "SELECT model_provider, model "
                "FROM virtual_player_profiles WHERE id = 'profile-1'"
            )
        ).one() == ("deepseek", "deepseek-v4-flash")
        assert any(
            item["name"] == "fk_virtual_player_profiles_model_configuration"
            and item["constrained_columns"] == ["model_provider", "model"]
            for item in inspect(connection).get_foreign_keys(
                "virtual_player_profiles"
            )
        )
        assert next(
            item
            for item in inspect(connection).get_indexes("virtual_player_profiles")
            if item["name"] == "ix_virtual_player_profiles_status_model"
        )["column_names"] == ["status", "model_provider", "model"]

        migration.downgrade()

        assert "model_provider" not in {
            item["name"]
            for item in inspect(connection).get_columns("virtual_player_profiles")
        }


def test_player_model_provider_migration_rejects_ambiguous_model_id() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        _create_previous_schema(connection)
        connection.execute(
            text(
                "INSERT INTO model_configurations (provider, model_id) VALUES "
                "('deepseek', 'shared-model'), "
                "('agent_plan', 'shared-model')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO virtual_player_profiles (id, status, model) VALUES "
                "('profile-1', 'published', 'shared-model')"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))

        with pytest.raises(
            RuntimeError,
            match="cannot be resolved uniquely",
        ):
            migration.upgrade()
