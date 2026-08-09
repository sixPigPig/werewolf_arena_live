"""link model reasoning policy and active V2 snapshots

Revision ID: 20260810_55
Revises: 20260806_54
Create Date: 2026-08-10
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260810_55"
down_revision = "20260806_54"
branch_labels = None
depends_on = None


_SAMPLING_KEYS = {
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
}
_TERMINAL_STATES = {"failed", "canceled"}


model_configurations = sa.table(
    "model_configurations",
    sa.column("provider", sa.String),
    sa.column("model_id", sa.String),
    sa.column("supports_thinking", sa.Boolean),
    sa.column("parameter_values", sa.JSON),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

v2_game_records = sa.table(
    "v2_game_records",
    sa.column("game_id", sa.String),
    sa.column("status", sa.String),
    sa.column("current_run_id", sa.String),
    sa.column("phase_state", sa.String),
    sa.column("players_snapshot", sa.JSON),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

v2_game_runs = sa.table(
    "v2_game_runs",
    sa.column("run_id", sa.String),
    sa.column("status", sa.String),
    sa.column("completed_at", sa.DateTime(timezone=True)),
)

v2_match_states = sa.table(
    "v2_match_states",
    sa.column("game_id", sa.String),
    sa.column("winner", sa.String),
    sa.column("completion_reason", sa.String),
)

v2_game_record_events = sa.table(
    "v2_game_record_events",
    sa.column("game_id", sa.String),
    sa.column("run_id", sa.String),
    sa.column("event_type", sa.String),
)


def upgrade() -> None:
    connection = op.get_bind()
    migrated_at = datetime.now(tz=UTC)
    configurations: dict[tuple[str, str], tuple[bool, dict[str, Any]]] = {}

    rows = list(
        connection.execute(
            sa.select(
                model_configurations.c.provider,
                model_configurations.c.model_id,
                model_configurations.c.supports_thinking,
                model_configurations.c.parameter_values,
            )
        ).mappings()
    )
    for row in rows:
        provider = str(row["provider"])
        model_id = str(row["model_id"])
        supports_thinking, parameters = _migrated_configuration(
            provider=provider,
            model_id=model_id,
            previous_supports_thinking=bool(row["supports_thinking"]),
            previous_parameters=row["parameter_values"],
        )
        connection.execute(
            sa.update(model_configurations)
            .where(
                model_configurations.c.provider == provider,
                model_configurations.c.model_id == model_id,
            )
            .values(
                supports_thinking=supports_thinking,
                parameter_values=parameters,
                updated_at=migrated_at,
            )
        )
        configurations[(provider, model_id)] = (supports_thinking, parameters)

    completion_events = {
        (str(game_id), str(run_id))
        for game_id, run_id in connection.execute(
            sa.select(
                v2_game_record_events.c.game_id,
                v2_game_record_events.c.run_id,
            ).where(v2_game_record_events.c.event_type == "game_completed")
        )
    }
    game_rows = list(
        connection.execute(
            sa.select(
                v2_game_records.c.game_id,
                v2_game_records.c.status,
                v2_game_records.c.current_run_id,
                v2_game_records.c.phase_state,
                v2_game_records.c.players_snapshot,
                v2_game_runs.c.status.label("run_status"),
                v2_game_runs.c.completed_at.label("run_completed_at"),
                v2_match_states.c.winner,
                v2_match_states.c.completion_reason,
            ).outerjoin(
                v2_game_runs,
                v2_game_runs.c.run_id == v2_game_records.c.current_run_id,
            ).outerjoin(
                v2_match_states,
                v2_match_states.c.game_id == v2_game_records.c.game_id,
            )
        ).mappings()
    )
    for row in game_rows:
        run_status = row["run_status"]
        if _is_terminal_game(
            game_status=str(row["status"]),
            phase_state=str(row["phase_state"]),
            run_status=str(run_status or ""),
            winner=row["winner"],
            completion_reason=row["completion_reason"],
            run_completed_at=row["run_completed_at"],
            has_completion_event=(
                str(row["game_id"]),
                str(row["current_run_id"]),
            )
            in completion_events,
        ):
            continue
        if run_status is None:
            raise RuntimeError(
                f"nonterminal V2 game {row['game_id']} has no current run"
            )
        migrated_snapshot = _migrated_players_snapshot(
            row["players_snapshot"],
            configurations=configurations,
            configuration_updated_at=migrated_at,
        )
        if migrated_snapshot is None:
            continue
        connection.execute(
            sa.update(v2_game_records)
            .where(v2_game_records.c.game_id == row["game_id"])
            .values(
                players_snapshot=migrated_snapshot,
                updated_at=migrated_at,
            )
        )


def downgrade() -> None:
    # This is an intentional full cutover. The old ambiguous defaults and
    # executable snapshots cannot be reconstructed safely.
    raise RuntimeError("irreversible full cutover; restore backup")


def _migrated_configuration(
    *,
    provider: str,
    model_id: str,
    previous_supports_thinking: bool,
    previous_parameters: Any,
) -> tuple[bool, dict[str, Any]]:
    del previous_supports_thinking
    policy = _policy_name(model_id)
    supports_thinking = policy != "non_thinking"
    parameters = _valid_sampling_parameters(previous_parameters)
    if policy == "deepseek_v4" and supports_thinking:
        parameters = {
            key: value
            for key, value in parameters.items()
            if key not in _SAMPLING_KEYS
        }
    parameters.update(_default_linkage(policy))
    return supports_thinking, parameters


def _valid_sampling_parameters(values: Any) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    ranges = {
        "temperature": (0.0, 2.0),
        "top_p": (0.0, 1.0),
        "frequency_penalty": (-2.0, 2.0),
        "presence_penalty": (-2.0, 2.0),
    }
    normalized: dict[str, float] = {}
    for key, (minimum, maximum) in ranges.items():
        value = values.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if minimum <= value <= maximum:
            normalized[key] = float(value)
    return normalized


def _policy_name(model_id: str) -> str:
    normalized = model_id.strip().lower()
    if "doubao-seed-2-0-code-preview" in normalized:
        return "non_thinking"
    if "glm-5-2" in normalized:
        return "glm_5_2"
    if "deepseek-v4" in normalized:
        return "deepseek_v4"
    if normalized == "kimi-k3" or normalized.startswith("kimi-k3-"):
        return "kimi_k3"
    if normalized == "minimax-m3" or normalized.startswith("minimax-m3-"):
        return "minimax_m3"
    if "doubao-" in normalized:
        return "doubao"
    return "non_thinking"


def _default_linkage(policy: str) -> dict[str, Any]:
    if policy == "doubao":
        effort, max_tokens = "low", 4_096
    elif policy in {"glm_5_2", "deepseek_v4"}:
        effort, max_tokens = "high", 8_192
    elif policy == "kimi_k3":
        effort, max_tokens = "low", 4_096
    elif policy == "minimax_m3":
        effort, max_tokens = None, 8_192
    else:
        return {
            "thinking": "disabled",
            "reasoning_effort": None,
            "max_tokens_mode": "auto",
            "max_tokens": 512,
        }
    return {
        "thinking": "enabled",
        "reasoning_effort": effort,
        "max_tokens_mode": "auto",
        "max_tokens": max_tokens,
    }


def _is_terminal_game(
    *,
    game_status: str,
    phase_state: str,
    run_status: str,
    winner: Any = None,
    completion_reason: Any = None,
    run_completed_at: Any = None,
    has_completion_event: bool = False,
) -> bool:
    if (
        game_status in _TERMINAL_STATES
        or run_status in _TERMINAL_STATES
        or phase_state == "failed"
    ):
        return True
    return (
        phase_state == "game_completed"
        and winner in {"villagers", "werewolves"}
        and completion_reason is not None
        and run_completed_at is not None
        and has_completion_event
    )


def _migrated_players_snapshot(
    snapshot: Any,
    *,
    configurations: dict[tuple[str, str], tuple[bool, dict[str, Any]]],
    configuration_updated_at: datetime,
) -> list[dict[str, Any]] | None:
    if not isinstance(snapshot, list) or not snapshot:
        # Legacy empty/incomplete snapshots remain historical but intentionally
        # fail the strict runtime contract after this full cutover.
        return None
    bindings: list[tuple[dict[str, Any], tuple[bool, dict[str, Any]]]] = []
    for player in snapshot:
        if not isinstance(player, dict):
            return None
        provider = player.get("model_provider")
        model_id = player.get("model")
        if not isinstance(provider, str) or not provider.strip():
            return None
        if not isinstance(model_id, str) or not model_id.strip():
            return None
        configuration = configurations.get((provider, model_id))
        if configuration is None:
            raise RuntimeError(
                "V2 snapshot references missing model configuration: "
                f"{provider}/{model_id}"
            )
        bindings.append((player, configuration))

    migrated: list[dict[str, Any]] = []
    frozen_updated_at = configuration_updated_at.isoformat()
    for player, (supports_thinking, parameters) in bindings:
        sampling_parameters = _valid_sampling_parameters(
            player.get("model_parameters")
        )
        if (
            _policy_name(str(player["model"])) == "deepseek_v4"
            and parameters["thinking"] == "enabled"
        ):
            sampling_parameters = {}
        migrated.append(
            {
                **player,
                "model_parameters": {
                    **sampling_parameters,
                    **{
                        key: parameters[key]
                        for key in (
                            "thinking",
                            "reasoning_effort",
                            "max_tokens_mode",
                            "max_tokens",
                        )
                    },
                },
                "model_supports_thinking": supports_thinking,
                "model_configuration_updated_at": frozen_updated_at,
            }
        )
    return migrated
