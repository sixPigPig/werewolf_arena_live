from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session

from app.models.game_session import GameSessionRecord
from app.models.live import LiveRunRecord


MIGRATIONS_DIR = Path(__file__).parents[1] / "alembic" / "versions"
CATALOG_MIGRATION_PATH = MIGRATIONS_DIR / "20260712_15_create_rule_set_catalog.py"
BACKFILL_MIGRATION_PATH = MIGRATIONS_DIR / "20260712_16_add_rule_revision_references.py"

FROZEN_MATCHES = {
    "classic_8": {
        "legacy_hash": "e63a962b73bb85d4d75f35c3c9fc7834b991ce39d41e4f892f66c3b68e4c4804",
        "revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
        "content_hash": "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131",
    },
    "starter_6": {
        "legacy_hash": "02f31f4aa42e54f83836bf2d9b68c25291181c91a722136ed6a0a9a0e40ea4fc",
        "revision_id": "b607e17e-b86f-5eb0-9dc2-b8df09aa71ab",
        "content_hash": "f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c",
    },
    "social_8": {
        "legacy_hash": "17ceee957477643a7d97fd31dd181c6ad126676ba1af0bc1fc144d4b4a411e6d",
        "revision_id": "2b4a993f-e4e6-5312-b11d-92874851a70a",
        "content_hash": "21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc",
    },
    "classic_12_seer_witch_hunter_idiot": {
        "legacy_hash": "688244c09a67521c10610875af305bafcadbcf16e164e5203cf7add4bd48aa00",
        "revision_id": "0489f6ac-16fd-5323-96ce-ee256c98cf32",
        "content_hash": "bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2",
    },
}


def _role(
    role: str,
    count: int,
    team: str,
    model_group: str,
    category: str,
) -> dict[str, object]:
    return {
        "role": role,
        "count": count,
        "team": team,
        "model_group": model_group,
        "category": category,
    }


def _legacy_snapshot(
    *,
    rule_set_id: str,
    name: str,
    description: str,
    roles: list[dict[str, object]],
    night_actions: list[str],
    day_actions: list[str],
    win_condition: str,
    complexity: str,
    estimated_duration: str,
    sheriff_enabled: bool,
    sheriff_vote_weight: float,
    self_explosion_enabled: bool,
    badge_bomb_policy: str,
    speech_policy: str,
    rule_tags: list[str],
) -> dict[str, object]:
    return {
        "id": rule_set_id,
        "version": "2026.04",
        "name": name,
        "description": description,
        "player_count": sum(int(role["count"]) for role in roles),
        "roles": roles,
        "night_actions": night_actions,
        "day_actions": day_actions,
        "win_condition": win_condition,
        "reveal_policy": "hidden",
        "complexity": complexity,
        "estimated_duration": estimated_duration,
        "sheriff_enabled": sheriff_enabled,
        "sheriff_vote_weight": sheriff_vote_weight,
        "werewolf_self_explosion_enabled": self_explosion_enabled,
        "sheriff_badge_bomb_policy": badge_bomb_policy,
        "speech_policy": speech_policy,
        "speech_rounds": 1,
        "rule_tags": rule_tags,
    }


EXACT_SNAPSHOTS = {
    "classic_8": _legacy_snapshot(
        rule_set_id="classic_8",
        name="经典 8 人局",
        description="包含狼人、预言家、守卫与村民的官方标准局。",
        roles=[
            _role("狼人", 2, "werewolves", "werewolf", "werewolf"),
            _role("预言家", 1, "villagers", "villager", "god"),
            _role("守卫", 1, "villagers", "villager", "god"),
            _role("村民", 4, "villagers", "villager", "civilian"),
        ],
        night_actions=["remove", "protect", "investigate"],
        day_actions=["debate", "vote", "summarize"],
        win_condition="wolves_gte_others",
        complexity="标准",
        estimated_duration="中",
        sheriff_enabled=False,
        sheriff_vote_weight=1.0,
        self_explosion_enabled=False,
        badge_bomb_policy="none",
        speech_policy="sequential",
        rule_tags=["无警长", "顺序发言", "标准"],
    ),
    "starter_6": _legacy_snapshot(
        rule_set_id="starter_6",
        name="新手 6 人快局",
        description="更短的官方入门局,适合快速观察模型策略。",
        roles=[
            _role("狼人", 1, "werewolves", "werewolf", "werewolf"),
            _role("预言家", 1, "villagers", "villager", "god"),
            _role("守卫", 1, "villagers", "villager", "god"),
            _role("村民", 3, "villagers", "villager", "civilian"),
        ],
        night_actions=["remove", "protect", "investigate"],
        day_actions=["debate", "vote", "summarize"],
        win_condition="wolves_gte_others",
        complexity="入门",
        estimated_duration="短",
        sheriff_enabled=False,
        sheriff_vote_weight=1.0,
        self_explosion_enabled=False,
        badge_bomb_policy="none",
        speech_policy="sequential",
        rule_tags=["无警长", "顺序发言", "新手"],
    ),
    "social_8": _legacy_snapshot(
        rule_set_id="social_8",
        name="社交 8 人局",
        description="仅保留狼人夜晚行动的官方心理博弈局。",
        roles=[
            _role("狼人", 2, "werewolves", "werewolf", "werewolf"),
            _role("村民", 6, "villagers", "villager", "civilian"),
        ],
        night_actions=["remove"],
        day_actions=["debate", "vote", "summarize"],
        win_condition="wolves_gte_others",
        complexity="心理",
        estimated_duration="中",
        sheriff_enabled=False,
        sheriff_vote_weight=1.0,
        self_explosion_enabled=False,
        badge_bomb_policy="none",
        speech_policy="sequential",
        rule_tags=["无警长", "顺序发言", "心理"],
    ),
    "classic_12_seer_witch_hunter_idiot": _legacy_snapshot(
        rule_set_id="classic_12_seer_witch_hunter_idiot",
        name="12 人预女猎白局",
        description="4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
        roles=[
            _role("狼人", 4, "werewolves", "werewolf", "werewolf"),
            _role("预言家", 1, "villagers", "villager", "god"),
            _role("女巫", 1, "villagers", "villager", "god"),
            _role("猎人", 1, "villagers", "villager", "god"),
            _role("白痴", 1, "villagers", "villager", "god"),
            _role("村民", 4, "villagers", "villager", "civilian"),
        ],
        night_actions=["remove", "investigate", "witch_save", "witch_poison"],
        day_actions=[
            "sheriff_run",
            "sheriff_speech",
            "sheriff_withdraw",
            "sheriff_vote",
            "sheriff_pk_speech",
            "sheriff_runoff_vote",
            "werewolf_self_explosion",
            "speech_order",
            "debate",
            "vote",
            "hunter_shoot",
            "summarize",
        ],
        win_condition="slaughter_side",
        complexity="进阶",
        estimated_duration="长",
        sheriff_enabled=True,
        sheriff_vote_weight=1.5,
        self_explosion_enabled=True,
        badge_bomb_policy="double",
        speech_policy="sheriff_directed",
        rule_tags=["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
    ),
}

CHANGED_SNAPSHOT = copy.deepcopy(EXACT_SNAPSHOTS["classic_8"])
CHANGED_SNAPSHOT["description"] = "相同 ID，但规则已修改。"

UNKNOWN_SNAPSHOT = copy.deepcopy(EXACT_SNAPSHOTS["classic_8"])
UNKNOWN_SNAPSHOT["id"] = "unknown_8"

INCOMPLETE_SNAPSHOT = {"id": "classic_8", "version": "2026.04"}

FULLWIDTH_STARTER_SNAPSHOT = copy.deepcopy(EXACT_SNAPSHOTS["starter_6"])
FULLWIDTH_STARTER_SNAPSHOT["description"] = "更短的官方入门局，适合快速观察模型策略。"

GAME_CASES: tuple[tuple[str, Mapping[str, object] | None], ...] = (
    ("game_exact001", EXACT_SNAPSHOTS["classic_8"]),
    ("game_exact002", EXACT_SNAPSHOTS["starter_6"]),
    ("game_exact003", EXACT_SNAPSHOTS["social_8"]),
    ("game_exact004", EXACT_SNAPSHOTS["classic_12_seer_witch_hunter_idiot"]),
    ("game_changed1", CHANGED_SNAPSHOT),
    ("game_unknown1", UNKNOWN_SNAPSHOT),
    ("game_incomplete1", INCOMPLETE_SNAPSHOT),
    ("game_fullwidth", FULLWIDTH_STARTER_SNAPSHOT),
    ("game_empty_id", {"id": "", "version": "2026.04"}),
    ("game_null_snap", None),
)

LIVE_CASES: tuple[tuple[str, str, Mapping[str, object] | None], ...] = (
    ("run_exact001", "classic_8", EXACT_SNAPSHOTS["classic_8"]),
    ("run_exact002", "starter_6", EXACT_SNAPSHOTS["starter_6"]),
    ("run_exact003", "social_8", EXACT_SNAPSHOTS["social_8"]),
    (
        "run_exact004",
        "classic_12_seer_witch_hunter_idiot",
        EXACT_SNAPSHOTS["classic_12_seer_witch_hunter_idiot"],
    ),
    ("run_changed1", "preserved_changed", CHANGED_SNAPSHOT),
    ("run_unknown1", "preserved_unknown", UNKNOWN_SNAPSHOT),
    ("run_incomplete1", "preserved_incomplete", INCOMPLETE_SNAPSHOT),
    ("run_fullwidth", "preserved_starter", FULLWIDTH_STARTER_SNAPSHOT),
    ("run_null_snap", "preserved_null", None),
)


def _canonical_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raw_json(value: Mapping[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=False,
        separators=(", ", ": "),
        allow_nan=False,
    )


def _load_migration(path: Path, module_name: str) -> ModuleType:
    assert path.exists(), f"missing migration: {path.name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind_migration(connection: Any, migration: ModuleType) -> None:
    context = MigrationContext.configure(connection)
    migration.op = Operations(context)


def _apply_upgrade(connection: Any, migration: ModuleType) -> None:
    _bind_migration(connection, migration)
    migration.upgrade()


def _create_pre_revision_schema(connection: Any) -> None:
    connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    connection.exec_driver_sql(
        """
        CREATE TABLE game_sessions (
            session_id VARCHAR(32) NOT NULL PRIMARY KEY,
            status VARCHAR(20) NOT NULL,
            winner VARCHAR(80),
            round_count INTEGER DEFAULT 0 NOT NULL,
            rule_set JSON,
            resumable BOOLEAN DEFAULT 0 NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE live_runs (
            run_id VARCHAR(32) NOT NULL PRIMARY KEY,
            session_id VARCHAR(32) NOT NULL,
            status VARCHAR(20) DEFAULT 'queued' NOT NULL,
            villager_model VARCHAR(120) NOT NULL,
            werewolf_model VARCHAR(120) NOT NULL,
            seed INTEGER,
            max_rounds INTEGER NOT NULL,
            rule_set_id VARCHAR(80) NOT NULL,
            rule_set JSON,
            player_configs JSON NOT NULL,
            lineup_quality_warnings JSON NOT NULL,
            winner VARCHAR(80),
            error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            started_at DATETIME,
            completed_at DATETIME,
            stop_requested_at DATETIME,
            worker_id VARCHAR(64),
            worker_heartbeat_at DATETIME,
            lease_expires_at DATETIME,
            control_version INTEGER DEFAULT 0 NOT NULL,
            fence_token INTEGER DEFAULT 0 NOT NULL,
            recovery_attempts INTEGER DEFAULT 0 NOT NULL,
            recovery_last_attempt_at DATETIME,
            recovery_not_before DATETIME,
            recovery_last_error TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
        """
    )


def _insert_legacy_rows(connection: Any) -> None:
    connection.execute(
        text(
            """
            INSERT INTO game_sessions (session_id, status, rule_set)
            VALUES (:session_id, 'completed', :rule_set)
            """
        ),
        [
            {
                "session_id": session_id,
                "rule_set": _raw_json(snapshot) if snapshot is not None else None,
            }
            for session_id, snapshot in GAME_CASES
        ],
    )
    connection.execute(
        text(
            """
            INSERT INTO live_runs (
                run_id,
                session_id,
                status,
                villager_model,
                werewolf_model,
                max_rounds,
                rule_set_id,
                rule_set,
                player_configs,
                lineup_quality_warnings
            ) VALUES (
                :run_id,
                :session_id,
                'completed',
                'villager-model',
                'werewolf-model',
                10,
                :rule_set_id,
                :rule_set,
                '[]',
                '[]'
            )
            """
        ),
        [
            {
                "run_id": run_id,
                "session_id": f"session_{index:02d}",
                "rule_set_id": rule_set_id,
                "rule_set": _raw_json(snapshot) if snapshot is not None else None,
            }
            for index, (run_id, rule_set_id, snapshot) in enumerate(LIVE_CASES, start=1)
        ],
    )


@pytest.fixture
def migrated_database(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'backfill.sqlite3'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    catalog_migration = _load_migration(CATALOG_MIGRATION_PATH, "catalog_migration")
    backfill_migration = _load_migration(BACKFILL_MIGRATION_PATH, "backfill_migration")
    with engine.begin() as connection:
        _create_pre_revision_schema(connection)
        _apply_upgrade(connection, catalog_migration)
        _insert_legacy_rows(connection)
        _apply_upgrade(connection, backfill_migration)

    try:
        yield engine
    finally:
        engine.dispose()


def _stored_json_hex(connection: Any, table_name: str, id_column: str) -> dict[str, str]:
    rows = connection.execute(
        text(
            f"SELECT {id_column}, hex(CAST(rule_set AS BLOB)) AS rule_set_hex "
            f"FROM {table_name} ORDER BY {id_column}"
        )
    ).all()
    return {str(row[0]): str(row[1]) for row in rows}


def _expected_json_hex(
    cases: tuple[tuple[str, Mapping[str, object] | None], ...],
) -> dict[str, str]:
    return {
        record_id: (
            _raw_json(snapshot).encode("utf-8").hex().upper() if snapshot is not None else ""
        )
        for record_id, snapshot in cases
    }


def test_rule_revision_migration_has_frozen_chain_and_no_app_imports() -> None:
    migration = _load_migration(BACKFILL_MIGRATION_PATH, "backfill_contract")
    source = BACKFILL_MIGRATION_PATH.read_text(encoding="utf-8")

    assert migration.revision == "20260712_16"
    assert migration.down_revision == "20260712_15"
    assert "from app" not in source
    assert "import app" not in source
    assert "更短的官方入门局，适合快速观察模型策略。" not in source
    assert migration._LEGACY_SNAPSHOT_MATCHES == {
        match["legacy_hash"]: (
            rule_set_id,
            match["revision_id"],
            match["content_hash"],
        )
        for rule_set_id, match in FROZEN_MATCHES.items()
    }
    assert {
        rule_set_id: _canonical_hash(snapshot) for rule_set_id, snapshot in EXACT_SNAPSHOTS.items()
    } == {rule_set_id: match["legacy_hash"] for rule_set_id, match in FROZEN_MATCHES.items()}


def test_backfill_links_only_exact_official_legacy_snapshots(
    migrated_database: Engine,
) -> None:
    exact_game_ids = {
        "game_exact001": "classic_8",
        "game_exact002": "starter_6",
        "game_exact003": "social_8",
        "game_exact004": "classic_12_seer_witch_hunter_idiot",
    }
    exact_run_ids = {
        "run_exact001": "classic_8",
        "run_exact002": "starter_6",
        "run_exact003": "social_8",
        "run_exact004": "classic_12_seer_witch_hunter_idiot",
    }

    with Session(migrated_database) as db:
        for session_id, rule_set_id in exact_game_ids.items():
            record = db.get(GameSessionRecord, session_id)
            assert record is not None
            match = FROZEN_MATCHES[rule_set_id]
            assert record.rule_set_id == rule_set_id
            assert record.rule_set_revision_id == match["revision_id"]
            assert record.rule_set_revision_no == 1
            assert record.rule_set_content_hash == match["content_hash"]

        for run_id, rule_set_id in exact_run_ids.items():
            record = db.get(LiveRunRecord, run_id)
            assert record is not None
            match = FROZEN_MATCHES[rule_set_id]
            assert record.rule_set_id == rule_set_id
            assert record.rule_set_revision_id == match["revision_id"]
            assert record.rule_set_revision_no == 1
            assert record.rule_set_content_hash == match["content_hash"]

        unmatched_games = {
            "game_changed1": "classic_8",
            "game_unknown1": "unknown_8",
            "game_incomplete1": "classic_8",
            "game_fullwidth": "starter_6",
        }
        for session_id, expected_rule_set_id in unmatched_games.items():
            record = db.get(GameSessionRecord, session_id)
            assert record is not None
            assert record.rule_set_id == expected_rule_set_id
            assert record.rule_set_revision_id is None
            assert record.rule_set_revision_no is None
            assert record.rule_set_content_hash is None

        for session_id in ("game_empty_id", "game_null_snap"):
            record = db.get(GameSessionRecord, session_id)
            assert record is not None
            assert record.rule_set_id is None
            assert record.rule_set_revision_id is None

        unmatched_runs = {
            "run_changed1": "preserved_changed",
            "run_unknown1": "preserved_unknown",
            "run_incomplete1": "preserved_incomplete",
            "run_fullwidth": "preserved_starter",
            "run_null_snap": "preserved_null",
        }
        for run_id, expected_rule_set_id in unmatched_runs.items():
            record = db.get(LiveRunRecord, run_id)
            assert record is not None
            assert record.rule_set_id == expected_rule_set_id
            assert record.rule_set_revision_id is None
            assert record.rule_set_revision_no is None
            assert record.rule_set_content_hash is None


def test_migration_adds_nullable_foreign_keys_and_frozen_indexes(
    migrated_database: Engine,
) -> None:
    inspector = inspect(migrated_database)

    for table_name in ("live_runs", "game_sessions"):
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert columns["rule_set_revision_id"]["nullable"] is True
        assert columns["rule_set_revision_no"]["nullable"] is True
        assert columns["rule_set_content_hash"]["nullable"] is True
        foreign_keys = inspector.get_foreign_keys(table_name)
        assert len(foreign_keys) == 1
        revision_fk = next(
            foreign_key
            for foreign_key in foreign_keys
            if foreign_key["constrained_columns"] == ["rule_set_revision_id"]
        )
        assert revision_fk["referred_table"] == "rule_set_revisions"
        assert revision_fk["referred_columns"] == ["id"]
        assert revision_fk["options"]["ondelete"] == "RESTRICT"

    game_columns = {column["name"]: column for column in inspector.get_columns("game_sessions")}
    assert game_columns["rule_set_id"]["nullable"] is True

    live_indexes = {index["name"] for index in inspector.get_indexes("live_runs")}
    game_indexes = {index["name"] for index in inspector.get_indexes("game_sessions")}
    assert {
        "ix_live_runs_rule_set_revision_id",
        "ix_live_runs_rule_set_id_updated_at_run_id_desc",
    } <= live_indexes
    assert {
        "ix_game_sessions_rule_set_revision_id",
        "ix_game_sessions_rule_set_id_created_at_session_id_desc",
    } <= game_indexes


def test_upgrade_and_downgrade_preserve_snapshot_bytes(
    migrated_database: Engine,
) -> None:
    expected_games = _expected_json_hex(GAME_CASES)
    expected_runs = _expected_json_hex(
        tuple((run_id, snapshot) for run_id, _rule_set_id, snapshot in LIVE_CASES)
    )
    migration = _load_migration(BACKFILL_MIGRATION_PATH, "backfill_downgrade")

    with migrated_database.begin() as connection:
        assert _stored_json_hex(connection, "game_sessions", "session_id") == expected_games
        assert _stored_json_hex(connection, "live_runs", "run_id") == expected_runs

        _bind_migration(connection, migration)
        migration.downgrade()

        game_columns = {
            column["name"] for column in inspect(connection).get_columns("game_sessions")
        }
        live_columns = {column["name"] for column in inspect(connection).get_columns("live_runs")}
        assert {
            "rule_set_id",
            "rule_set_revision_id",
            "rule_set_revision_no",
            "rule_set_content_hash",
        }.isdisjoint(game_columns)
        assert {
            "rule_set_revision_id",
            "rule_set_revision_no",
            "rule_set_content_hash",
        }.isdisjoint(live_columns)
        assert _stored_json_hex(connection, "game_sessions", "session_id") == expected_games
        assert _stored_json_hex(connection, "live_runs", "run_id") == expected_runs
