from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260715_22_replace_slow_player_models.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("slow_player_model_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_slow_player_models_are_replaced() -> None:
    migration = load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert migration.revision == "20260715_22"
    assert migration.down_revision == "20260715_21"

    rows = [
        ("pro-player", "doubao-seed-2-0-pro-260215", 1),
        ("kimi-player", "kimi-k2.7-code", 2),
        ("46b6dfa5-d7d6-46b8-a37b-001aa0f3edca", "kimi-k2.7-code", 3),
        ("minimax-player", "minimax-m2.7", 4),
        ("older-kimi-player", "kimi-k2.6", 5),
        ("retained-player", "minimax-m3", 6),
    ]

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE virtual_player_profiles ("
                "id VARCHAR(36) PRIMARY KEY, "
                "model VARCHAR(120) NOT NULL, "
                "version INTEGER NOT NULL, "
                "updated_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO virtual_player_profiles (id, model, version) "
                "VALUES (:id, :model, :version)"
            ),
            [{"id": row[0], "model": row[1], "version": row[2]} for row in rows],
        )
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)

        migration.upgrade()

        migrated = dict(
            connection.execute(
                text("SELECT id, model FROM virtual_player_profiles ORDER BY id")
            ).all()
        )
        versions = dict(
            connection.execute(
                text("SELECT id, version FROM virtual_player_profiles ORDER BY id")
            ).all()
        )

    assert migrated == {
        "46b6dfa5-d7d6-46b8-a37b-001aa0f3edca": "doubao-seed-2-0-lite-260215",
        "kimi-player": "deepseek-v4-flash",
        "minimax-player": "minimax-m3",
        "older-kimi-player": "glm-5-2-260617",
        "pro-player": "deepseek-v4-flash",
        "retained-player": "minimax-m3",
    }
    assert versions == {
        "46b6dfa5-d7d6-46b8-a37b-001aa0f3edca": 4,
        "kimi-player": 3,
        "minimax-player": 5,
        "older-kimi-player": 6,
        "pro-player": 2,
        "retained-player": 6,
    }
