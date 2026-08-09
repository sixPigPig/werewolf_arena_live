from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.model_catalog.defaults import (
    max_output_tokens_limit,
    normalize_model_parameters,
)


class V2FrozenModelParametersError(ValueError):
    pass


@dataclass(frozen=True)
class V2FrozenPlayerModelConfiguration:
    provider: str
    model_id: str
    supports_thinking: bool
    parameters: dict[str, Any]


def validate_frozen_model_parameters(
    values: object,
    *,
    provider: str,
    model_id: str,
    supports_thinking: object,
) -> dict[str, Any]:
    """Validate that a V2 snapshot is the complete canonical policy result."""

    if not isinstance(supports_thinking, bool):
        raise V2FrozenModelParametersError("model_supports_thinking must be a boolean")
    if not isinstance(values, dict):
        raise V2FrozenModelParametersError("model_parameters must be an object")
    if "reasoning_effort" not in values:
        raise V2FrozenModelParametersError("frozen reasoning_effort key is required")
    try:
        normalized = normalize_model_parameters(
            provider,
            model_id,
            values,
            supports_thinking=supports_thinking,
            limit=max_output_tokens_limit(provider, model_id),
            enforce_auto_max_tokens=True,
        )
    except ValueError as exc:
        raise V2FrozenModelParametersError(
            "frozen model parameters violate the model reasoning policy"
        ) from exc
    if _canonical_json(normalized) != _canonical_json(values):
        raise V2FrozenModelParametersError("frozen model parameters are not canonical")
    return dict(values)


def validate_players_snapshot_model_configurations(snapshot: object) -> None:
    if not isinstance(snapshot, list) or not snapshot:
        raise V2FrozenModelParametersError(
            "players_snapshot must contain frozen player model configurations"
        )
    for index, player in enumerate(snapshot):
        if not isinstance(player, dict):
            raise V2FrozenModelParametersError(f"players_snapshot[{index}] must be an object")
        try:
            frozen_player_model_configuration(player)
        except V2FrozenModelParametersError as exc:
            raise V2FrozenModelParametersError(
                f"players_snapshot[{index}] has an invalid frozen model configuration"
            ) from exc


def frozen_player_model_configuration(
    player: object,
) -> V2FrozenPlayerModelConfiguration:
    if not isinstance(player, dict):
        raise V2FrozenModelParametersError("frozen player must be an object")
    provider = player.get("model_provider")
    model_id = player.get("model")
    if not isinstance(provider, str) or not provider.strip():
        raise V2FrozenModelParametersError("model_provider must be a non-empty string")
    if not isinstance(model_id, str) or not model_id.strip():
        raise V2FrozenModelParametersError("model must be a non-empty string")
    supports_thinking = player.get("model_supports_thinking")
    parameters = validate_frozen_model_parameters(
        player.get("model_parameters"),
        provider=provider,
        model_id=model_id,
        supports_thinking=supports_thinking,
    )
    assert isinstance(supports_thinking, bool)
    return V2FrozenPlayerModelConfiguration(
        provider=provider.strip(),
        model_id=model_id.strip(),
        supports_thinking=supports_thinking,
        parameters=parameters,
    )


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
