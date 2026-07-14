from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any


DEFAULT_PLAYBACK_CREATED_AT = "1970-01-01T00:00:00Z"
PRIVATE_ROUND_MEMORY_ACTION = "summarize"
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
    "interruption",
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


def private_round_memory_event_ids(events: list[dict[str, Any]]) -> set[int]:
    """Return historical event ids that belong to the private round-memory action."""
    event_ids: set[int] = set()
    for event in events:
        if event.get("action") != PRIVATE_ROUND_MEMORY_ACTION:
            continue
        event_id = event.get("id")
        if isinstance(event_id, int):
            event_ids.add(event_id)
    return event_ids


def filter_public_playback_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop legacy private round-memory events before public playback serialization."""
    return [
        event
        for event in events
        if event.get("action") != PRIVATE_ROUND_MEMORY_ACTION
    ]


def filter_public_playback_voices(
    voices: list[dict[str, Any]],
    *,
    private_event_ids: set[int],
) -> list[dict[str, Any]]:
    """Drop legacy audio sourced from a private round-memory event range."""
    if not private_event_ids:
        return voices

    public_voices: list[dict[str, Any]] = []
    for voice in voices:
        first_event_id = voice.get("source_event_id")
        last_event_id = voice.get("last_source_event_id", first_event_id)
        if not isinstance(first_event_id, int) or not isinstance(last_event_id, int):
            public_voices.append(voice)
            continue
        if any(first_event_id <= event_id <= last_event_id for event_id in private_event_ids):
            continue
        public_voices.append(voice)
    return public_voices


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
        _publish_werewolf_decision_events(
            publish,
            round_state,
            round_log,
            round_number=round_number,
        )
        _publish_night_role_action_events(
            publish,
            round_state,
            round_log,
            round_number=round_number,
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
        sheriff_run_logs = _action_logs(round_log, ("sheriff_run",))
        if sheriff_run_logs:
            publish(
                "judge_cue",
                round_number=round_number,
                phase="day",
                actor=None,
                action="sheriff_raise_hands",
                payload={
                    "cue": "sheriff_raise_hands",
                    "visible_text": "想要竞选警长的玩家请举手。",
                },
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


def build_public_game_session(session: dict[str, Any]) -> dict[str, Any]:
    """Return the stored game payload without private round-memory fields."""
    public_session = copy.deepcopy(session)
    state = public_session.get("state")
    if isinstance(state, dict):
        rounds = state.get("rounds")
        if isinstance(rounds, list):
            for round_state in rounds:
                if not isinstance(round_state, dict):
                    continue
                round_state.pop("summaries", None)
                round_state.pop("private_summaries", None)

    logs = public_session.get("logs")
    if isinstance(logs, list):
        for round_log in logs:
            if isinstance(round_log, dict):
                round_log.pop("summaries", None)
    return public_session


def _publish_action_events(
    publish: Any,
    action_log: dict[str, Any],
    *,
    round_number: int,
    phase: str,
) -> None:
    if _is_secret_werewolf_action(action_log):
        return
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


def _publish_werewolf_decision_events(
    publish: Any,
    round_state: dict[str, Any],
    round_log: dict[str, Any],
    *,
    round_number: int,
) -> None:
    vote_rounds = _list_or_empty(round_state.get("werewolf_vote_rounds"))
    eliminate = _dict_or_empty(round_log.get("eliminate"))
    if not vote_rounds and not _looks_like_action_log(eliminate):
        return

    _publish_night_judge_cue(
        publish,
        cue="werewolves_wake",
        visible_text="狼人请睁眼，请互相确认队友。",
        round_number=round_number,
    )
    if eliminate.get("action") != "werewolf_kill_vote" and not vote_rounds:
        _publish_action_events(
            publish,
            eliminate,
            round_number=round_number,
            phase="night",
        )
        _publish_night_judge_cue(
            publish,
            cue="werewolves_sleep",
            visible_text="狼人请闭眼。",
            round_number=round_number,
        )
        return

    publish(
        "action_requested",
        round_number=round_number,
        phase="night",
        actor=None,
        action="remove",
        payload={},
    )
    if vote_rounds:
        for index, raw_vote_round in enumerate(vote_rounds):
            if not isinstance(raw_vote_round, dict):
                continue
            vote_round = raw_vote_round.get("round")
            if not isinstance(vote_round, int):
                vote_round = index + 1
            for actor, target in _dict_or_empty(raw_vote_round.get("votes")).items():
                if not isinstance(actor, str) or not isinstance(target, str):
                    continue
                _publish_werewolf_vote(
                    publish,
                    actor=actor,
                    target=target,
                    vote_round=vote_round,
                    round_number=round_number,
                )
            final_target = _optional_str(raw_vote_round.get("result"))
            if final_target:
                _publish_final_werewolf_target(
                    publish,
                    target=final_target,
                    vote_round=vote_round,
                    round_number=round_number,
                )
        _publish_night_judge_cue(
            publish,
            cue="werewolves_sleep",
            visible_text="狼人请闭眼。",
            round_number=round_number,
        )
        return

    # Older games only persisted the unanimous wolf action as `eliminate`.
    actor = _optional_str(eliminate.get("actor"))
    target = _optional_str(eliminate.get("choice"))
    if not target:
        _publish_night_judge_cue(
            publish,
            cue="werewolves_sleep",
            visible_text="狼人请闭眼。",
            round_number=round_number,
        )
        return
    if actor:
        _publish_werewolf_vote(
            publish,
            actor=actor,
            target=target,
            vote_round=1,
            round_number=round_number,
        )
    _publish_final_werewolf_target(
        publish,
        target=target,
        vote_round=1,
        round_number=round_number,
    )
    _publish_night_judge_cue(
        publish,
        cue="werewolves_sleep",
        visible_text="狼人请闭眼。",
        round_number=round_number,
    )


def _publish_night_role_action_events(
    publish: Any,
    round_state: dict[str, Any],
    round_log: dict[str, Any],
    *,
    round_number: int,
) -> None:
    role_groups = (
        ("guard_wake", "守卫请睁眼。", ("protect",), "guard_sleep", "守卫请闭眼。"),
        (
            "seer_wake",
            "预言家请睁眼。",
            ("investigate",),
            "seer_sleep",
            "预言家请闭眼。",
        ),
    )
    for wake_cue, wake_text, keys, sleep_cue, sleep_text in role_groups:
        action_logs = _action_logs(round_log, keys)
        if not action_logs:
            continue
        _publish_night_judge_cue(
            publish,
            cue=wake_cue,
            visible_text=wake_text,
            round_number=round_number,
        )
        for action_log in action_logs:
            _publish_action_events(
                publish,
                action_log,
                round_number=round_number,
                phase="night",
            )
        _publish_night_judge_cue(
            publish,
            cue=sleep_cue,
            visible_text=sleep_text,
            round_number=round_number,
        )

    witch_logs = _action_logs(round_log, ("witch_save", "witch_poison"))
    if not witch_logs:
        return
    _publish_night_judge_cue(
        publish,
        cue="witch_wake",
        visible_text="女巫请睁眼。",
        round_number=round_number,
    )
    attacked = _optional_str(round_state.get("attacked"))
    if attacked:
        _publish_night_judge_cue(
            publish,
            cue="witch_death",
            visible_text=f"今晚被狼人袭击的玩家是{attacked}。",
            round_number=round_number,
            target=attacked,
        )
    for action_log in witch_logs:
        _publish_action_events(
            publish,
            action_log,
            round_number=round_number,
            phase="night",
        )
    _publish_night_judge_cue(
        publish,
        cue="witch_sleep",
        visible_text="女巫请闭眼。",
        round_number=round_number,
    )


def _publish_night_judge_cue(
    publish: Any,
    *,
    cue: str,
    visible_text: str,
    round_number: int,
    target: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "cue": cue,
        "visible_text": visible_text,
    }
    if target:
        payload["target"] = target
    publish(
        "judge_cue",
        round_number=round_number,
        phase="night",
        actor=None,
        action=cue,
        payload=payload,
    )


def _publish_werewolf_vote(
    publish: Any,
    *,
    actor: str,
    target: str,
    vote_round: int,
    round_number: int,
) -> None:
    result = {"target": target}
    publish(
        "action_parsed",
        round_number=round_number,
        phase="night",
        actor=actor,
        action="werewolf_kill_vote",
        payload={
            "choice": target,
            "result": result,
            "visible_result": result,
            "vote_round": vote_round,
        },
    )


def _publish_final_werewolf_target(
    publish: Any,
    *,
    target: str,
    vote_round: int,
    round_number: int,
) -> None:
    result = {"target": target}
    publish(
        "action_parsed",
        round_number=round_number,
        phase="night",
        actor=None,
        action="remove",
        payload={
            "choice": target,
            "result": result,
            "visible_result": result,
            "vote_round": vote_round,
            "final_target": True,
        },
    )


def _is_secret_werewolf_action(action_log: dict[str, Any]) -> bool:
    return action_log.get("action") in {
        "werewolf_discuss",
        "werewolf_kill_vote",
        "werewolf_self_explosion",
    }


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
        "public_summary": str(round_state.get("public_summary") or ""),
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
