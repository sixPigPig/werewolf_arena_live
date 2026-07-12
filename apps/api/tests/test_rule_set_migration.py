from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic" / "versions" / "20260712_15_create_rule_set_catalog.py"
)

EXPECTED_SEEDS = {
    "classic_8": {
        "revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
        "content_hash": "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131",
        "display_order": 1,
        "is_default": True,
        "player_count": 8,
        "role_summary": "2 狼人 / 1 预言家 / 1 守卫 / 4 村民",
        "config": {
            "name": "经典 8 人局",
            "description": "包含狼人、预言家、守卫与村民的官方标准局。",
            "complexity": "标准",
            "estimated_duration": "中",
            "rule_tags": ["无警长", "顺序发言", "标准"],
            "role_counts": {
                "werewolf": 2,
                "villager": 4,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    "starter_6": {
        "revision_id": "b607e17e-b86f-5eb0-9dc2-b8df09aa71ab",
        "content_hash": "f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c",
        "display_order": 2,
        "is_default": False,
        "player_count": 6,
        "role_summary": "1 狼人 / 1 预言家 / 1 守卫 / 3 村民",
        "config": {
            "name": "新手 6 人快局",
            "description": "更短的官方入门局,适合快速观察模型策略。",
            "complexity": "入门",
            "estimated_duration": "短",
            "rule_tags": ["无警长", "顺序发言", "新手"],
            "role_counts": {
                "werewolf": 1,
                "villager": 3,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    "social_8": {
        "revision_id": "2b4a993f-e4e6-5312-b11d-92874851a70a",
        "content_hash": "21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc",
        "display_order": 3,
        "is_default": False,
        "player_count": 8,
        "role_summary": "2 狼人 / 6 村民",
        "config": {
            "name": "社交 8 人局",
            "description": "仅保留狼人夜晚行动的官方心理博弈局。",
            "complexity": "心理",
            "estimated_duration": "中",
            "rule_tags": ["无警长", "顺序发言", "心理"],
            "role_counts": {
                "werewolf": 2,
                "villager": 6,
                "seer": 0,
                "guard": 0,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    "classic_12_seer_witch_hunter_idiot": {
        "revision_id": "0489f6ac-16fd-5323-96ce-ee256c98cf32",
        "content_hash": "bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2",
        "display_order": 4,
        "is_default": False,
        "player_count": 12,
        "role_summary": "4 狼人 / 1 预言家 / 1 女巫 / 1 猎人 / 1 白痴 / 4 村民",
        "config": {
            "name": "12 人预女猎白局",
            "description": "4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
            "complexity": "进阶",
            "estimated_duration": "长",
            "rule_tags": ["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
            "role_counts": {
                "werewolf": 4,
                "villager": 4,
                "seer": 1,
                "guard": 0,
                "witch": 1,
                "hunter": 1,
                "idiot": 1,
            },
            "win_condition": "slaughter_side",
            "sheriff_enabled": True,
            "sheriff_vote_weight": 1.5,
            "speech_policy": "sheriff_directed",
            "werewolf_self_explosion_enabled": True,
            "sheriff_badge_bomb_policy": "double",
        },
    },
}


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rule_set_catalog_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_upgrade(connection, migration: ModuleType) -> None:
    context = MigrationContext.configure(connection)
    migration.op = Operations(context)
    migration.upgrade()


def test_rule_set_migration_has_expected_revision_chain_and_frozen_dependencies() -> None:
    migration = _load_migration()
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert migration.revision == "20260712_15"
    assert migration.down_revision == "20260711_14"
    assert "from app" not in source
    assert "import app" not in source
    assert "更短的官方入门局，适合快速观察模型策略。" not in source


def test_rule_set_migration_creates_exact_official_revision_one_seeds() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        _apply_upgrade(connection, migration)

        assert {"rule_sets", "rule_set_revisions"} <= set(inspect(connection).get_table_names())
        parents = (
            connection.execute(text("SELECT * FROM rule_sets ORDER BY display_order"))
            .mappings()
            .all()
        )
        revisions = (
            connection.execute(text("SELECT * FROM rule_set_revisions ORDER BY rule_set_id"))
            .mappings()
            .all()
        )

    assert len(parents) == 4
    assert len(revisions) == 4
    assert sum(bool(row["is_default"]) for row in parents) == 1

    parents_by_id = {row["id"]: row for row in parents}
    revisions_by_rule_set_id = {row["rule_set_id"]: row for row in revisions}
    assert set(parents_by_id) == set(EXPECTED_SEEDS)
    assert set(revisions_by_rule_set_id) == set(EXPECTED_SEEDS)

    for rule_set_id, expected in EXPECTED_SEEDS.items():
        parent = parents_by_id[rule_set_id]
        revision = revisions_by_rule_set_id[rule_set_id]
        config = revision["config"]
        if isinstance(config, str):
            config = json.loads(config)

        assert parent["status"] == "published"
        assert parent["current_published_revision_id"] == expected["revision_id"]
        assert parent["draft_revision_id"] is None
        assert bool(parent["is_default"]) is expected["is_default"]
        assert parent["display_order"] == expected["display_order"]
        assert parent["lock_version"] == 1

        assert revision["id"] == expected["revision_id"]
        assert revision["revision_no"] == 1
        assert revision["state"] == "published"
        assert revision["schema_version"] == 1
        assert revision["content_hash"] == expected["content_hash"]
        assert revision["lock_version"] == 1
        assert revision["name"] == expected["config"]["name"]
        assert revision["description"] == expected["config"]["description"]
        assert revision["player_count"] == expected["player_count"]
        assert revision["role_summary"] == expected["role_summary"]
        assert revision["complexity"] == expected["config"]["complexity"]
        assert revision["estimated_duration"] == expected["config"]["estimated_duration"]
        assert config == expected["config"]
        assert revision["published_at"] is not None


def test_rule_set_migration_downgrade_removes_catalog_tables() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        _apply_upgrade(connection, migration)
        migration.downgrade()

        table_names = set(inspect(connection).get_table_names())

    assert "rule_set_revisions" not in table_names
    assert "rule_sets" not in table_names
