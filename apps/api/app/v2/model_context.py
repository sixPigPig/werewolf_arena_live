from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class V2ModelPlayerReference:
    player_id: str
    seat: int
    display_name: str

    @property
    def ref(self) -> str:
        return f"seat_{self.seat}"

    @property
    def label(self) -> str:
        return f"{self.seat}号"


def project_model_action_context(
    context: dict[str, Any],
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> dict[str, Any]:
    if not players:
        return dict(context)
    projected = _project_value(context, players=players)
    public_history = context.get("public_history")
    if isinstance(public_history, list) or isinstance(public_history, tuple):
        facts, statements = _project_public_history(public_history, players=players)
        projected.pop("public_history", None)
        projected["authoritative_public_facts"] = facts
        projected["public_statements"] = statements
    projected["player_reference_rule"] = {
        "reference_format": "seat_N",
        "spoken_format": "N号",
        "names_available": False,
        "instruction": "只使用座位号称呼玩家，不得猜测或生成玩家姓名。",
    }
    return projected


def sanitize_model_speech(
    speech: str,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str:
    return _project_text(speech, players=players)


def resolve_model_target(
    target: str | None,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str | None:
    if target is None:
        return None
    return {player.ref: player.player_id for player in players}.get(target)


def _project_public_history(
    history: Iterable[Any],
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    latest_round = 1
    for raw_item in history:
        if not isinstance(raw_item, dict):
            continue
        event_type = raw_item.get("event_type")
        payload = raw_item.get("payload")
        if not isinstance(event_type, str) or not isinstance(payload, dict):
            continue
        round_no = payload.get("round_no")
        if isinstance(round_no, int) and round_no > 0:
            latest_round = round_no
        projected_payload = _project_value(payload, players=players)

        if event_type == "day_speech_committed":
            statements.append(
                {
                    "kind": "player_statement",
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "stage": projected_payload.get("stage"),
                    "speaker_ref": projected_payload.get("player_id"),
                    "speech": projected_payload.get("speech"),
                }
            )
            continue
        if event_type == "day_vote_committed":
            facts.append(
                {
                    "kind": "day_vote",
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "action_type": projected_payload.get("action_type"),
                    "voter_ref": projected_payload.get("voter_player_id"),
                    "target_ref": projected_payload.get("target_player_id"),
                    "weight": projected_payload.get("weight"),
                }
            )
            speech = projected_payload.get("speech")
            if isinstance(speech, str) and speech:
                statements.append(
                    {
                        "kind": "player_statement",
                        "occurred_in": {"period": "day", "round_no": latest_round},
                        "stage": projected_payload.get("action_type"),
                        "speaker_ref": projected_payload.get("voter_player_id"),
                        "speech": speech,
                    }
                )
            continue
        if event_type == "dawn_public_result":
            eliminated = projected_payload.get("dead_player_ids")
            eliminated_refs = eliminated if isinstance(eliminated, list) else []
            facts.append(
                {
                    "kind": "night_result",
                    "occurred_in": {"period": "night", "round_no": latest_round},
                    "announced_in": {"period": "dawn", "round_no": latest_round},
                    "outcome": "deaths" if eliminated_refs else "peaceful",
                    "eliminated_player_refs": eliminated_refs,
                }
            )
            continue
        if event_type == "player_exiled":
            facts.append(
                {
                    "kind": "player_eliminated",
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "public_reason": "exile",
                    "player_ref": projected_payload.get("player_id"),
                }
            )
            continue
        if event_type == "werewolf_self_exploded":
            facts.append(
                {
                    "kind": "player_eliminated",
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "public_reason": "self_explosion",
                    "player_ref": projected_payload.get("player_id"),
                    "stage": projected_payload.get("stage"),
                }
            )
            continue
        if event_type == "hunter_response_resolved":
            facts.append(
                {
                    "kind": "hunter_response",
                    "occurred_in": {
                        "period": projected_payload.get("period") or "day",
                        "round_no": latest_round,
                    },
                    "hunter_ref": projected_payload.get("hunter_player_id"),
                    "target_ref": projected_payload.get("target_player_id"),
                }
            )
            continue
        facts.append(
            {
                "kind": event_type,
                "occurred_in": {
                    "period": _public_event_period(event_type),
                    "round_no": latest_round,
                },
                "payload": projected_payload,
            }
        )
    return facts, statements


def _public_event_period(event_type: str) -> str:
    return "dawn" if event_type == "dawn_public_result" else "day"


def _project_value(
    value: Any,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> Any:
    if isinstance(value, dict):
        return {
            (
                _project_text(key, players=players)
                if isinstance(key, str)
                else key
            ): _project_value(item, players=players)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_project_value(item, players=players) for item in value]
    if isinstance(value, tuple):
        return [_project_value(item, players=players) for item in value]
    if isinstance(value, str):
        return _project_text(value, players=players)
    return value


def _project_text(
    value: str,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str:
    projected = value
    for player in sorted(players, key=lambda item: len(item.player_id), reverse=True):
        projected = projected.replace(player.player_id, player.ref)
    for player in sorted(players, key=lambda item: len(item.display_name), reverse=True):
        if player.display_name:
            projected = projected.replace(player.display_name, player.label)
    return projected
