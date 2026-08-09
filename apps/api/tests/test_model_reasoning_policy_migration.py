from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260810_55_link_model_reasoning_policy.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "model_reasoning_policy_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tables() -> tuple[
    sa.MetaData,
    sa.Table,
    sa.Table,
    sa.Table,
    sa.Table,
    sa.Table,
]:
    metadata = sa.MetaData()
    configurations = sa.Table(
        "model_configurations",
        metadata,
        sa.Column("provider", sa.String, primary_key=True),
        sa.Column("model_id", sa.String, primary_key=True),
        sa.Column("supports_thinking", sa.Boolean, nullable=False),
        sa.Column("parameter_values", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    games = sa.Table(
        "v2_game_records",
        metadata,
        sa.Column("game_id", sa.String, primary_key=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("current_run_id", sa.String, nullable=False),
        sa.Column("phase_state", sa.String, nullable=False),
        sa.Column("players_snapshot", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    runs = sa.Table(
        "v2_game_runs",
        metadata,
        sa.Column("run_id", sa.String, primary_key=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    matches = sa.Table(
        "v2_match_states",
        metadata,
        sa.Column("game_id", sa.String, primary_key=True),
        sa.Column("winner", sa.String, nullable=True),
        sa.Column("completion_reason", sa.String, nullable=True),
    )
    events = sa.Table(
        "v2_game_record_events",
        metadata,
        sa.Column("event_id", sa.Integer, primary_key=True),
        sa.Column("game_id", sa.String, nullable=False),
        sa.Column("run_id", sa.String, nullable=False),
        sa.Column("event_type", sa.String, nullable=False),
    )
    return metadata, configurations, games, runs, matches, events


def test_reasoning_policy_migration_updates_catalog_and_only_exact_active_snapshots(
) -> None:
    migration = _load_migration()
    assert migration.revision == "20260810_55"
    assert migration.down_revision == "20260806_54"

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata, configurations, games, runs, matches, events = _tables()
    metadata.create_all(engine)
    old_timestamp = datetime(2026, 8, 1, tzinfo=UTC)
    old_parameters = {"thinking": "default", "max_tokens": 16_384}
    old_snapshot = [
        {
            "profile_id": "p1",
            "model_provider": "agent_plan",
            "model": "glm-5-2-260617",
            "model_parameters": {
                **old_parameters,
                "top_p": 0.7,
                "unknown_legacy_parameter": "drop-me",
            },
        }
    ]

    with engine.begin() as connection:
        connection.execute(
            configurations.insert(),
            [
                {
                    "provider": "agent_plan",
                    "model_id": "doubao-seed-2-0-lite-260215",
                    "supports_thinking": True,
                    "parameter_values": {
                        **old_parameters,
                        "temperature": 0.3,
                        "unknown_legacy_parameter": "drop-me",
                    },
                    "updated_at": old_timestamp,
                },
                {
                    "provider": "agent_plan",
                    "model_id": "glm-5-2-260617",
                    "supports_thinking": True,
                    "parameter_values": old_parameters,
                    "updated_at": old_timestamp,
                },
                {
                    "provider": "deepseek",
                    "model_id": "deepseek-v4-flash",
                    "supports_thinking": True,
                    "parameter_values": {
                        **old_parameters,
                        "temperature": 0.4,
                    },
                    "updated_at": old_timestamp,
                },
                {
                    "provider": "agent_plan",
                    "model_id": "kimi-k3",
                    "supports_thinking": True,
                    "parameter_values": old_parameters,
                    "updated_at": old_timestamp,
                },
                {
                    "provider": "agent_plan",
                    "model_id": "minimax-m3",
                    "supports_thinking": True,
                    "parameter_values": old_parameters,
                    "updated_at": old_timestamp,
                },
                {
                    "provider": "agent_plan",
                    "model_id": "kimi-k2.6",
                    "supports_thinking": True,
                    "parameter_values": {
                        **old_parameters,
                        "top_p": 4.0,
                        "unknown_legacy_parameter": "drop-me",
                    },
                    "updated_at": old_timestamp,
                },
            ],
        )
        connection.execute(
            runs.insert(),
            [
                {
                    "run_id": "run-active",
                    "status": "paused_model_error",
                    "completed_at": None,
                },
                {
                    "run_id": "run-missing",
                    "status": "waiting_to_start",
                    "completed_at": None,
                },
                {
                    "run_id": "run-completed",
                    "status": "awaiting_observation",
                    "completed_at": old_timestamp,
                },
                {
                    "run_id": "run-half-completed",
                    "status": "awaiting_observation",
                    "completed_at": None,
                },
                {"run_id": "run-failed", "status": "failed", "completed_at": None},
                {
                    "run_id": "run-canceled",
                    "status": "canceled",
                    "completed_at": None,
                },
            ],
        )
        connection.execute(
            games.insert(),
            [
                {
                    "game_id": "game-active",
                    "status": "paused_model_error",
                    "current_run_id": "run-active",
                    "phase_state": "night_running",
                    "players_snapshot": old_snapshot,
                    "updated_at": old_timestamp,
                },
                {
                    "game_id": "game-missing",
                    "status": "waiting_to_start",
                    "current_run_id": "run-missing",
                    "phase_state": "opening_ready",
                    "players_snapshot": [
                        {
                            "profile_id": "p2",
                            "model": "glm-5-2-260617",
                            "model_parameters": old_parameters,
                        }
                    ],
                    "updated_at": old_timestamp,
                },
                {
                    "game_id": "game-completed",
                    "status": "awaiting_observation",
                    "current_run_id": "run-completed",
                    "phase_state": "game_completed",
                    "players_snapshot": old_snapshot,
                    "updated_at": old_timestamp,
                },
                {
                    "game_id": "game-failed",
                    "status": "failed",
                    "current_run_id": "run-failed",
                    "phase_state": "failed",
                    "players_snapshot": old_snapshot,
                    "updated_at": old_timestamp,
                },
                {
                    "game_id": "game-half-completed",
                    "status": "awaiting_observation",
                    "current_run_id": "run-half-completed",
                    "phase_state": "game_completed",
                    "players_snapshot": old_snapshot,
                    "updated_at": old_timestamp,
                },
                {
                    "game_id": "game-canceled",
                    "status": "canceled",
                    "current_run_id": "run-canceled",
                    "phase_state": "night_running",
                    "players_snapshot": old_snapshot,
                    "updated_at": old_timestamp,
                },
            ],
        )
        connection.execute(
            matches.insert(),
            {
                "game_id": "game-completed",
                "winner": "villagers",
                "completion_reason": "deterministic_win_condition",
            },
        )
        connection.execute(
            events.insert(),
            {
                "event_id": 1,
                "game_id": "game-completed",
                "run_id": "run-completed",
                "event_type": "game_completed",
            },
        )

        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        migrated_configurations = {
            row.model_id: (row.supports_thinking, row.parameter_values)
            for row in connection.execute(sa.select(configurations))
        }
        assert migrated_configurations["doubao-seed-2-0-lite-260215"][1] == {
            "temperature": 0.3,
            "thinking": "enabled",
            "reasoning_effort": "low",
            "max_tokens_mode": "auto",
            "max_tokens": 4_096,
        }
        assert migrated_configurations["glm-5-2-260617"][1] == {
            "thinking": "enabled",
            "reasoning_effort": "high",
            "max_tokens_mode": "auto",
            "max_tokens": 8_192,
        }
        assert migrated_configurations["deepseek-v4-flash"][1] == {
            "thinking": "enabled",
            "reasoning_effort": "high",
            "max_tokens_mode": "auto",
            "max_tokens": 8_192,
        }
        assert migrated_configurations["kimi-k3"][1]["reasoning_effort"] == "low"
        assert migrated_configurations["minimax-m3"][1]["reasoning_effort"] is None
        assert migrated_configurations["minimax-m3"][1]["max_tokens"] == 8_192
        assert migrated_configurations["kimi-k2.6"] == (
            False,
            {
                "thinking": "disabled",
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 512,
            },
        )

        snapshots = {
            row.game_id: row.players_snapshot
            for row in connection.execute(sa.select(games))
        }
        active_player = snapshots["game-active"][0]
        assert active_player["model_parameters"] == {
            "top_p": 0.7,
            "thinking": "enabled",
            "reasoning_effort": "high",
            "max_tokens_mode": "auto",
            "max_tokens": 8_192,
        }
        assert active_player["model_supports_thinking"] is True
        assert active_player["model_configuration_updated_at"]
        assert snapshots["game-missing"][0]["model_parameters"] == old_parameters
        assert snapshots["game-completed"] == old_snapshot
        assert snapshots["game-half-completed"][0]["model_parameters"] == {
            "top_p": 0.7,
            "thinking": "enabled",
            "reasoning_effort": "high",
            "max_tokens_mode": "auto",
            "max_tokens": 8_192,
        }
        assert snapshots["game-failed"] == old_snapshot
        assert snapshots["game-canceled"] == old_snapshot

    engine.dispose()


@pytest.mark.parametrize(
    ("provider", "model_id", "supports_thinking", "thinking", "effort", "max_tokens"),
    [
        ("agent_plan", "deepseek-v4-flash-260425", True, "enabled", "high", 8_192),
        (
            "agent_plan",
            "deepseek-v4-flash-ga-260731",
            True,
            "enabled",
            "high",
            8_192,
        ),
        ("agent_plan", "deepseek-v4-pro-260425", True, "enabled", "high", 8_192),
        (
            "agent_plan",
            "doubao-seed-2-0-code-preview-260215",
            False,
            "disabled",
            None,
            512,
        ),
        (
            "agent_plan",
            "doubao-seed-2-0-lite-260215",
            True,
            "enabled",
            "low",
            4_096,
        ),
        (
            "agent_plan",
            "doubao-seed-2-0-mini-260215",
            True,
            "enabled",
            "low",
            4_096,
        ),
        (
            "agent_plan",
            "doubao-seed-2-0-pro-260215",
            True,
            "enabled",
            "low",
            4_096,
        ),
        (
            "agent_plan",
            "doubao-seed-2-1-turbo-260628",
            True,
            "enabled",
            "low",
            4_096,
        ),
        ("agent_plan", "doubao-seed-evolving", True, "enabled", "low", 4_096),
        ("agent_plan", "glm-5-2-260617", True, "enabled", "high", 8_192),
        ("agent_plan", "kimi-k2.6", False, "disabled", None, 512),
        ("agent_plan", "kimi-k2.7-code", False, "disabled", None, 512),
        ("agent_plan", "kimi-k3", True, "enabled", "low", 4_096),
        ("agent_plan", "minimax-m2.7", False, "disabled", None, 512),
        ("agent_plan", "minimax-m3", True, "enabled", None, 8_192),
        ("deepseek", "deepseek-v4-flash", True, "enabled", "high", 8_192),
        ("deepseek", "deepseek-v4-pro", True, "enabled", "high", 8_192),
    ],
)
def test_all_seventeen_catalog_records_have_explicit_cutover_policy(
    provider: str,
    model_id: str,
    supports_thinking: bool,
    thinking: str,
    effort: str | None,
    max_tokens: int,
) -> None:
    migration = _load_migration()

    migrated_support, parameters = migration._migrated_configuration(
        provider=provider,
        model_id=model_id,
        previous_supports_thinking=True,
        previous_parameters={
            "thinking": "default",
            "reasoning_effort": "legacy",
            "max_tokens": 123,
            "unknown_legacy_parameter": "drop-me",
        },
    )

    assert migrated_support is supports_thinking
    assert parameters == {
        "thinking": thinking,
        "reasoning_effort": effort,
        "max_tokens_mode": "auto",
        "max_tokens": max_tokens,
    }


def test_reasoning_policy_migration_downgrade_requires_backup_restore() -> None:
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="irreversible full cutover; restore backup"):
        migration.downgrade()


def test_terminal_cutover_matches_runtime_for_empty_completion_reason() -> None:
    migration = _load_migration()

    assert migration._is_terminal_game(
        game_status="awaiting_observation",
        phase_state="game_completed",
        run_status="awaiting_observation",
        winner="villagers",
        completion_reason="",
        run_completed_at=datetime(2026, 8, 10, tzinfo=UTC),
        has_completion_event=True,
    )


def test_snapshot_cutover_skips_legacy_missing_binding_but_rejects_missing_catalog(
) -> None:
    migration = _load_migration()
    timestamp = datetime(2026, 8, 10, tzinfo=UTC)
    configuration = {
        ("agent_plan", "glm-5-2-260617"): (
            True,
            {
                "thinking": "enabled",
                "reasoning_effort": "high",
                "max_tokens_mode": "auto",
                "max_tokens": 8_192,
            },
        )
    }

    assert (
        migration._migrated_players_snapshot(
            [],
            configurations=configuration,
            configuration_updated_at=timestamp,
        )
        is None
    )
    assert (
        migration._migrated_players_snapshot(
            [{"model": "glm-5-2-260617"}],
            configurations=configuration,
            configuration_updated_at=timestamp,
        )
        is None
    )
    with pytest.raises(
        RuntimeError,
        match="V2 snapshot references missing model configuration",
    ):
        migration._migrated_players_snapshot(
            [
                {
                    "model_provider": "agent_plan",
                    "model": "missing-model",
                }
            ],
            configurations=configuration,
            configuration_updated_at=timestamp,
        )

    deepseek_configuration = {
        ("deepseek", "deepseek-v4-flash"): (
            True,
            {
                "thinking": "enabled",
                "reasoning_effort": "high",
                "max_tokens_mode": "auto",
                "max_tokens": 8_192,
            },
        )
    }
    deepseek_snapshot = migration._migrated_players_snapshot(
        [
            {
                "model_provider": "deepseek",
                "model": "deepseek-v4-flash",
                "model_parameters": {"temperature": 0.7},
            }
        ],
        configurations=deepseek_configuration,
        configuration_updated_at=timestamp,
    )
    assert deepseek_snapshot is not None
    assert deepseek_snapshot[0]["model_parameters"] == {
        "thinking": "enabled",
        "reasoning_effort": "high",
        "max_tokens_mode": "auto",
        "max_tokens": 8_192,
    }


def test_snapshot_cutover_rejects_nonterminal_orphan_current_run() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata, configurations, games, _runs, _matches, _events = _tables()
    metadata.create_all(engine)
    timestamp = datetime(2026, 8, 1, tzinfo=UTC)

    with engine.begin() as connection:
        connection.execute(
            configurations.insert(),
            {
                "provider": "agent_plan",
                "model_id": "glm-5-2-260617",
                "supports_thinking": True,
                "parameter_values": {"thinking": "default", "max_tokens": 16_384},
                "updated_at": timestamp,
            },
        )
        connection.execute(
            games.insert(),
            {
                "game_id": "game-orphan",
                "status": "paused_model_error",
                "current_run_id": "run-missing",
                "phase_state": "night_running",
                "players_snapshot": [
                    {
                        "model_provider": "agent_plan",
                        "model": "glm-5-2-260617",
                    }
                ],
                "updated_at": timestamp,
            },
        )
        migration.op = Operations(MigrationContext.configure(connection))

        with pytest.raises(
            RuntimeError,
            match="nonterminal V2 game game-orphan has no current run",
        ):
            migration.upgrade()

    engine.dispose()


def test_terminal_detection_rejects_invalid_winner() -> None:
    migration = _load_migration()

    assert not migration._is_terminal_game(
        game_status="awaiting_observation",
        phase_state="game_completed",
        run_status="awaiting_observation",
        winner="unknown",
        completion_reason="deterministic_win_condition",
        run_completed_at=datetime(2026, 8, 10, tzinfo=UTC),
        has_completion_event=True,
    )


def test_terminal_detection_matches_runtime_for_empty_completion_reason() -> None:
    migration = _load_migration()

    assert migration._is_terminal_game(
        game_status="awaiting_observation",
        phase_state="game_completed",
        run_status="awaiting_observation",
        winner="villagers",
        completion_reason="",
        run_completed_at=datetime(2026, 8, 10, tzinfo=UTC),
        has_completion_event=True,
    )
