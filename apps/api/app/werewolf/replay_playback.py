from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any


DEFAULT_PLAYBACK_CREATED_AT = "1970-01-01T00:00:00Z"
NIGHT_ACTION_KEYS = (
    "eliminate",
    "protect",
    "investigate",
    "witch_save",
    "witch_poison",
)
DAY_ACTION_KEYS = (
    "sheriff_run",
    "sheriff_speech",
    "sheriff_withdraw",
    "sheriff_pk_speech",
    "sheriff_runoff_votes",
    "sheriff_votes",
    "speech_order",
    "sheriff_badge",
    "bid",
    "debate",
    "votes",
    "hunter_shoot",
    "werewolf_self_explosion",
    "summaries",
)
DAY_STAGE_STATE_KEYS = (
    "sheriff",
    "sheriff_candidates",
    "sheriff_speech_order",
    "sheriff_speech_direction",
    "sheriff_speeches",
    "sheriff_withdrawn",
    "sheriff_final_candidates",
    "sheriff_voters",
    "sheriff_votes",
    "sheriff_pk_candidates",
    "sheriff_pk_speeches",
    "sheriff_runoff_votes",
    "sheriff_elected",
    "speech_order",
    "speech_order_choice",
    "vote_weights",
    "sheriff_badge_target",
    "sheriff_badge_lost",
    "werewolf_self_exploded",
    "day_ended_by_self_explosion",
    "sheriff_pre_election_bomb_count",
    "sheriff_election_pending",
    "sheriff_badge_lost_reason",
)
PUBLIC_PLAYER_KEYS = (
    "name",
    "role",
    "model",
    "personality_id",
    "personality",
    "appearance_id",
    "avatar_prompt",
    "avatar_image_url",
    "profile_id",
    "tags",
)


def build_replay_playback(session: dict[str, Any]) -> dict[str, Any]:
    state = _dict_or_empty(session.get("state"))
    session_id = str(session.get("session_id") or state.get("session_id") or "")
    status = str(session.get("status") or "partial")
    run_id = f"playback_{session_id}"
    base_created_at = _parse_created_at(state.get("created_at"))
    events: list[dict[str, Any]] = []

    def publish(
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event_id = len(events) + 1
        events.append(
            {
                "id": event_id,
                "type": event_type,
                "run_id": run_id,
                "session_id": session_id,
                "created_at": _format_created_at(base_created_at, event_id),
                "round": round_number,
                "phase": phase,
                "actor": actor,
                "action": action,
                "payload": _copy_json_payload(payload or {}),
            }
        )

    rule_set = state.get("rule_set")
    publish(
        "run_created",
        payload={
            "playback": True,
            "session_id": session_id,
            "status": status,
            "rule_set": rule_set,
            "resumable": bool(session.get("resumable")),
        },
    )
    publish("run_started", payload={"playback": True})
    publish(
        "game_started",
        payload={
            "playback": True,
            "rule_set": rule_set,
            "players": _public_players(state.get("players")),
            "active_players": _active_players(state),
        },
    )

    logs_by_round = _logs_by_round(session.get("logs"))
    for round_state in _valid_rounds(state.get("rounds")):
        round_number = int(round_state["number"])
        round_log = logs_by_round.get(round_number, {})
        active_players = _list_or_empty(round_state.get("players"))
        publish(
            "round_started",
            round_number=round_number,
            payload={"active_players": active_players},
        )

        publish(
            "phase_started",
            round_number=round_number,
            phase="night",
            payload={"active_players": active_players},
        )
        for action_log in _action_logs(round_log, NIGHT_ACTION_KEYS):
            _publish_action_events(
                publish,
                action_log,
                round_number=round_number,
                phase="night",
            )
        publish(
            "state_updated",
            round_number=round_number,
            phase="night",
            payload=_night_state_payload(round_state, active_players),
        )

        publish(
            "phase_started",
            round_number=round_number,
            phase="day",
            payload={"active_players": active_players},
        )
        for action_log in _action_logs(round_log, DAY_ACTION_KEYS):
            _publish_action_events(
                publish,
                action_log,
                round_number=round_number,
                phase="day",
            )
        publish(
            "state_updated",
            round_number=round_number,
            phase="day",
            payload=_day_state_payload(round_state, active_players),
        )

    if status == "complete":
        publish("game_completed", payload={"winner": state.get("winner")})
    else:
        publish(
            "game_failed",
            payload={
                "error": str(
                    state.get("error_message") or session.get("error") or "Playback is partial"
                ),
                "playback_partial": True,
            },
        )

    return {
        "session_id": session_id,
        "status": status,
        "rule_set": rule_set,
        "resumable": bool(session.get("resumable")),
        "events": events,
    }


def _publish_action_events(
    publish: Any,
    action_log: dict[str, Any],
    *,
    round_number: int,
    phase: str,
) -> None:
    actor = _optional_str(action_log.get("actor"))
    action = _optional_str(action_log.get("action"))
    options = _list_or_empty(action_log.get("options"))
    choice = action_log.get("choice")
    lm_log = _dict_or_empty(action_log.get("lm_log"))
    parsed_result = lm_log.get("result") or lm_log.get("parsed")
    public_result = _public_result(choice, parsed_result)
    visible_text = _visible_text(choice, public_result)

    publish(
        "action_requested",
        round_number=round_number,
        phase=phase,
        actor=actor,
        action=action,
        payload={
            "options": options,
        },
    )
    publish(
        "model_response_received",
        round_number=round_number,
        phase=phase,
        actor=actor,
        action=action,
        payload={
            "request_id": lm_log.get("request_id"),
            "result": public_result,
            "visible_text": visible_text,
        },
    )
    publish(
        "action_parsed",
        round_number=round_number,
        phase=phase,
        actor=actor,
        action=action,
        payload={
            "choice": choice,
            "result": public_result,
            "visible_result": public_result,
            "visible_text": visible_text,
        },
    )


def _night_state_payload(round_state: dict[str, Any], active_players: list[Any]) -> dict[str, Any]:
    return {
        "attacked": round_state.get("attacked"),
        "eliminated": round_state.get("eliminated"),
        "protected": round_state.get("protected"),
        "investigated": round_state.get("investigated"),
        "saved_by_witch": round_state.get("saved_by_witch"),
        "poisoned": round_state.get("poisoned"),
        "night_deaths": _list_or_empty(round_state.get("night_deaths")),
        "active_players": active_players,
    }


def _day_state_payload(round_state: dict[str, Any], active_players: list[Any]) -> dict[str, Any]:
    payload = {
        "debate": _list_or_empty(round_state.get("debate")),
        "bids": _list_or_empty(round_state.get("bids")),
        "votes": _latest_mapping(round_state.get("votes")),
        "summaries": _dict_or_empty(round_state.get("summaries")),
        "exiled": round_state.get("exiled"),
        "day_deaths": _list_or_empty(round_state.get("day_deaths")),
        "hunter_shot": round_state.get("hunter_shot"),
        "idiot_revealed": round_state.get("idiot_revealed"),
        "active_players": active_players,
    }
    payload.update(
        {
            key: round_state.get(key)
            for key in DAY_STAGE_STATE_KEYS
            if key in round_state
        }
    )
    return payload


def _logs_by_round(logs: Any) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    if not isinstance(logs, list):
        return result
    for log in logs:
        if not isinstance(log, dict) or not isinstance(log.get("number"), int):
            continue
        result[log["number"]] = log
    return result


def _valid_rounds(rounds: Any) -> list[dict[str, Any]]:
    if not isinstance(rounds, list):
        return []
    return [
        round_state
        for round_state in rounds
        if isinstance(round_state, dict) and isinstance(round_state.get("number"), int)
    ]


def _action_logs(round_log: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    for key in keys:
        logs.extend(_flatten_action_logs(round_log.get(key)))
    return logs


def _flatten_action_logs(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value] if _looks_like_action_log(value) else []
    if isinstance(value, list):
        logs: list[dict[str, Any]] = []
        for item in value:
            logs.extend(_flatten_action_logs(item))
        return logs
    return []


def _looks_like_action_log(value: dict[str, Any]) -> bool:
    return isinstance(value.get("actor"), str) and isinstance(value.get("action"), str)


def _active_players(state: dict[str, Any]) -> list[Any]:
    rounds = state.get("rounds")
    if isinstance(rounds, list) and rounds:
        first_round = rounds[0]
        if isinstance(first_round, dict):
            players = first_round.get("players")
            if isinstance(players, list):
                return players
    players = state.get("players")
    if not isinstance(players, list):
        return []
    return [
        player.get("name")
        for player in players
        if isinstance(player, dict) and player.get("name")
    ]


def _public_players(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        _public_player(player)
        for player in value
        if isinstance(player, dict)
    ]


def _public_player(player: dict[str, Any]) -> dict[str, Any]:
    return _copy_json_payload(
        {
            key: player[key]
            for key in PUBLIC_PLAYER_KEYS
            if key in player
        }
    )


def _latest_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict):
                return item
    return {}


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.fromisoformat(DEFAULT_PLAYBACK_CREATED_AT.replace("Z", "+00:00"))


def _format_created_at(base_created_at: datetime, event_id: int) -> str:
    return (
        base_created_at + timedelta(seconds=event_id - 1)
    ).isoformat().replace("+00:00", "Z")


def _visible_text(choice: Any, visible_result: Any) -> str | None:
    if isinstance(visible_result, dict):
        parts = [
            _optional_str(visible_result.get(key))
            for key in ("say", "summary", "choice")
        ]
        visible_parts = [part for part in parts if part]
        if visible_parts:
            return " ".join(visible_parts)
    return _optional_str(choice) or _stringify_visible(visible_result)


def _public_result(choice: Any, result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        public_result = {
            key: result[key]
            for key in ("say", "summary", "choice")
            if key in result
        }
        if public_result:
            return public_result
    return {"choice": choice}


def _stringify_visible(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _copy_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))
