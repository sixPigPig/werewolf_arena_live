from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.werewolf.live import LiveEvent
from app.werewolf.privacy_projection import ProjectionAudience, project_live_event
from app.werewolf.checkpoint import (
    sheriff_badge_resolution_from_dict,
    sheriff_election_resolution_from_dict,
)
from app.werewolf.judge_narration import (
    JudgeCueSpec,
    cue_spec,
    dawn_result_cue,
    exile_no_result_cue,
    exile_result_cue,
    exile_runoff_tied_cue,
    exile_tie_cues,
    hunter_result_cue,
    idiot_reveal_cues,
    legacy_exile_no_result_cue,
    seat_asset_id,
    self_explosion_cues,
    sheriff_badge_cues,
    sheriff_election_cues,
)


DEFAULT_PLAYBACK_CREATED_AT = "1970-01-01T00:00:00Z"
PRIVATE_ROUND_MEMORY_ACTION = "summarize"
DAY_ACTION_KEYS = (
    "sheriff_run",
    "sheriff_speech",
    "sheriff_withdraw",
    "sheriff_pk_speech",
    "sheriff_runoff_votes",
    "exile_pk_speech",
    "exile_runoff_votes",
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
    "exile_pk_candidates",
    "exile_pk_speeches",
    "exile_runoff_votes",
    "exile_resolution_reason",
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
    "sheriff_election_resolution",
    "sheriff_badge_resolution",
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
    """Apply the live player-public contract to persisted and reconstructed replay events."""
    return project_playback_events(events, audience="player_public")


def project_playback_events(
    events: list[dict[str, Any]],
    *,
    audience: ProjectionAudience,
) -> list[dict[str, Any]]:
    projected_events: list[dict[str, Any]] = []
    for event in events:
        try:
            canonical = LiveEvent(
                id=int(event["id"]),
                type=str(event["type"]),
                run_id=str(event["run_id"]),
                session_id=str(event["session_id"]),
                created_at=str(event["created_at"]),
                round=event.get("round") if isinstance(event.get("round"), int) else None,
                phase=event.get("phase") if isinstance(event.get("phase"), str) else None,
                actor=event.get("actor") if isinstance(event.get("actor"), str) else None,
                action=event.get("action") if isinstance(event.get("action"), str) else None,
                payload=event.get("payload") if isinstance(event.get("payload"), dict) else {},
            )
        except (KeyError, TypeError, ValueError):
            continue
        projected = project_live_event(canonical, audience)
        if projected is not None:
            projected_events.append(projected.to_dict())
    return projected_events


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
            action="night_resolved",
            payload={
                **_night_state_payload(round_state, active_players),
                "narration_mode": "explicit_v1",
            },
        )
        night_deaths = _list_or_empty(round_state.get("night_deaths"))
        _publish_replay_cue(
            publish,
            dawn_result_cue(
                [
                    str(death.get("player"))
                    for death in night_deaths
                    if isinstance(death, dict) and death.get("player")
                ]
            ),
            round_number=round_number,
            phase="day",
        )

        publish(
            "phase_started",
            round_number=round_number,
            phase="day",
            payload={
                "active_players": active_players,
                "narration_mode": "explicit_v1",
            },
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
                    "schema_version": 1,
                    "cue_id": "sheriff_raise_hands",
                    "cue": "sheriff_raise_hands",
                    "visible_text": "想要竞选警长的玩家请举手。",
                    "static_asset_id": "sheriff_raise_hands",
                    "params": {},
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
            action="day_resolution_completed",
            payload={
                **_day_state_payload(round_state, active_players),
                "narration_mode": "explicit_v1",
            },
        )
        _publish_replay_day_cues(
            publish,
            round_state,
            round_number=round_number,
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
    """Return a player-public game DTO without canonical replay logs or private state."""
    raw_state = _dict_or_empty(session.get("state"))
    status = str(session.get("status") or "partial")
    terminal_reveal = (
        status == "complete"
        and not bool(session.get("resumable"))
        and bool(raw_state.get("winner"))
    )
    players = [
        _public_game_player(player, reveal_role=terminal_reveal)
        for player in _list_or_empty(raw_state.get("players"))
        if isinstance(player, dict)
    ]
    rounds = [
        _public_game_round(round_state)
        for round_state in _valid_rounds(raw_state.get("rounds"))
    ]
    state = {
        "session_id": str(raw_state.get("session_id") or session.get("session_id") or ""),
        "players": players,
        "rounds": rounds,
        "winner": str(raw_state.get("winner") or "") if terminal_reveal else "",
        "error_message": (
            "对局异常中断。" if raw_state.get("error_message") and not terminal_reveal else ""
        ),
        "public_facts": copy.deepcopy(raw_state.get("public_facts") or []),
        "rule_set": copy.deepcopy(raw_state.get("rule_set")),
        "sheriff": raw_state.get("sheriff"),
        "sheriff_badge_lost": bool(raw_state.get("sheriff_badge_lost")),
    }
    return {
        "session_id": str(session.get("session_id") or state["session_id"]),
        "status": status,
        "resumable": bool(session.get("resumable")),
        "state": state,
        "logs": [],
    }


def _public_game_player(player: dict[str, Any], *, reveal_role: bool) -> dict[str, Any]:
    allowed = {
        "appearance_id",
        "avatar_image_url",
        "avatar_prompt",
        "can_vote",
        "is_sheriff",
        "model",
        "name",
        "personality",
        "personality_id",
        "profile_id",
        "revealed_role",
        "tags",
    }
    if reveal_role:
        allowed.add("role")
    return {
        key: copy.deepcopy(value)
        for key, value in player.items()
        if key in allowed
    }


def _public_game_round(round_state: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "active_players",
        "bids",
        "day_deaths",
        "day_ended_by_self_explosion",
        "debate",
        "eliminated",
        "exiled",
        "exile_pk_candidates",
        "exile_pk_speeches",
        "exile_resolution_reason",
        "exile_runoff_votes",
        "hunter_shot",
        "idiot_revealed",
        "interruption",
        "night_deaths",
        "number",
        "players",
        "public_facts",
        "public_outcome_events",
        "public_outcome_next_sequence",
        "public_summary",
        "sheriff",
        "sheriff_badge_lost",
        "sheriff_badge_lost_reason",
        "sheriff_badge_resolution",
        "sheriff_badge_target",
        "sheriff_candidates",
        "sheriff_elected",
        "sheriff_election_pending",
        "sheriff_election_resolution",
        "sheriff_final_candidates",
        "sheriff_pk_candidates",
        "sheriff_pk_speeches",
        "sheriff_pre_election_bomb_count",
        "sheriff_runoff_votes",
        "sheriff_speech_direction",
        "sheriff_speech_order",
        "sheriff_speeches",
        "sheriff_voters",
        "sheriff_votes",
        "sheriff_withdrawn",
        "speech_order",
        "speech_order_choice",
        "success",
        "vote_weights",
        "votes",
        "werewolf_self_exploded",
    }
    projected = {
        key: copy.deepcopy(value)
        for key, value in round_state.items()
        if key in allowed
    }
    for field_name in ("night_deaths", "day_deaths"):
        deaths = projected.get(field_name)
        if isinstance(deaths, list):
            projected[field_name] = [
                {"player": death.get("player")}
                for death in deaths
                if isinstance(death, dict) and isinstance(death.get("player"), str)
            ]
    return projected


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
    for raw_entry in _list_or_empty(round_state.get("werewolf_discussion")):
        if not isinstance(raw_entry, dict):
            continue
        actor = _optional_str(raw_entry.get("speaker"))
        target = _optional_str(raw_entry.get("target"))
        if not actor or not target:
            continue
        _publish_werewolf_discussion(
            publish,
            actor=actor,
            target=target,
            message=_optional_str(raw_entry.get("message")) or "",
            round_number=round_number,
        )
    if vote_rounds:
        for index, raw_vote_round in enumerate(vote_rounds):
            if not isinstance(raw_vote_round, dict):
                continue
            vote_round = raw_vote_round.get("round")
            if not isinstance(vote_round, int):
                vote_round = index + 1
            if raw_vote_round.get("stage") != "discussion_consensus":
                for actor, target in _dict_or_empty(raw_vote_round.get("votes")).items():
                    if not isinstance(actor, str) or not isinstance(target, str):
                        continue
                    _publish_werewolf_vote(
                        publish,
                        actor=actor,
                        target=target,
                        vote_round=vote_round,
                        round_number=round_number,
                        decision_stage="final",
                    )
            tiebreak = _dict_or_empty(raw_vote_round.get("tiebreak"))
            tiebreak_actor = _optional_str(tiebreak.get("actor"))
            tiebreak_choice = _optional_str(tiebreak.get("choice"))
            tiebreak_candidates = [
                str(item) for item in _list_or_empty(tiebreak.get("candidates"))
            ]
            if tiebreak_actor and tiebreak_choice and tiebreak_candidates:
                _publish_werewolf_tiebreak_cue(
                    publish,
                    cue_id="werewolf_tiebreak_start",
                    visible_text=(
                        "狼队刀口出现平票。"
                        f"本夜由{tiebreak_actor}行使归票权，请从"
                        f"{'、'.join(tiebreak_candidates)}中确认最终刀口。"
                    ),
                    actor=tiebreak_actor,
                    candidates=tiebreak_candidates,
                    round_number=round_number,
                )
                _publish_werewolf_vote(
                    publish,
                    actor=tiebreak_actor,
                    target=tiebreak_choice,
                    vote_round=vote_round,
                    round_number=round_number,
                    decision_stage="tiebreak",
                )
                _publish_werewolf_tiebreak_cue(
                    publish,
                    cue_id="werewolf_tiebreak_result",
                    visible_text=(
                        f"{tiebreak_actor}最终归票{tiebreak_choice}，狼人请确认刀口。"
                    ),
                    actor=tiebreak_actor,
                    candidates=tiebreak_candidates,
                    round_number=round_number,
                    target=tiebreak_choice,
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
    params: dict[str, object] = {}
    if target:
        params["target"] = target
    static_asset_id = (
        seat_asset_id(cue, target) if cue == "witch_death" and target else cue
    )
    _publish_replay_cue(
        publish,
        cue_spec(
            cue,
            visible_text,
            static_asset_id=static_asset_id,
            params=params,
        ),
        round_number=round_number,
        phase="night",
    )


def _publish_replay_cue(
    publish: Any,
    cue: JudgeCueSpec,
    *,
    round_number: int,
    phase: str,
) -> None:
    publish(
        "judge_cue",
        round_number=round_number,
        phase=phase,
        actor=None,
        action=cue.cue_id,
        payload=cue.to_payload(),
    )


def _publish_replay_day_cues(
    publish: Any,
    round_state: dict[str, Any],
    *,
    round_number: int,
) -> None:
    election = sheriff_election_resolution_from_dict(
        round_state.get("sheriff_election_resolution")
    )
    if election is not None:
        for cue in sheriff_election_cues(election):
            _publish_replay_cue(publish, cue, round_number=round_number, phase="day")
    else:
        elected = _optional_str(round_state.get("sheriff_elected"))
        if elected:
            _publish_replay_cue(
                publish,
                cue_spec(
                    "sheriff_result",
                    f"{elected}当选警长，获得警徽。",
                    static_asset_id=seat_asset_id("sheriff_result", elected),
                    params={"sheriff": elected, "legacy_synthesized": True},
                ),
                round_number=round_number,
                phase="day",
            )
        elif round_state.get("sheriff_badge_lost") is True:
            _publish_replay_cue(
                publish,
                cue_spec(
                    "sheriff_no_badge",
                    static_asset_id="sheriff_no_badge",
                    params={"legacy_synthesized": True},
                ),
                round_number=round_number,
                phase="day",
            )

    self_exploded = _optional_str(round_state.get("werewolf_self_exploded"))
    if self_exploded:
        interruption = _dict_or_empty(round_state.get("interruption"))
        cues = self_explosion_cues(
            self_exploded,
            stage=str(interruption.get("stage") or "day"),
            completed_actors=[
                str(item)
                for item in _list_or_empty(interruption.get("completed_actors"))
            ],
            pending_actors=[
                str(item)
                for item in _list_or_empty(interruption.get("pending_actors"))
            ],
        )
        for cue in cues:
            _publish_replay_cue(publish, cue, round_number=round_number, phase="day")

    exile_pk_candidates = [
        str(item)
        for item in _list_or_empty(round_state.get("exile_pk_candidates"))
    ]
    exile_resolution_reason = _optional_str(round_state.get("exile_resolution_reason"))
    if exile_pk_candidates:
        tie_cues = exile_tie_cues(exile_pk_candidates)
        for cue in tie_cues[:2]:
            _publish_replay_cue(publish, cue, round_number=round_number, phase="vote")
        if _dict_or_empty(round_state.get("exile_runoff_votes")):
            _publish_replay_cue(
                publish,
                tie_cues[2],
                round_number=round_number,
                phase="vote",
            )
        if exile_resolution_reason == "runoff_tied":
            _publish_replay_cue(
                publish,
                exile_runoff_tied_cue(exile_pk_candidates),
                round_number=round_number,
                phase="vote",
            )
        elif exile_resolution_reason == "no_runoff_voters":
            _publish_replay_cue(
                publish,
                exile_no_result_cue(exile_resolution_reason),
                round_number=round_number,
                phase="vote",
            )
    elif exile_resolution_reason == "no_valid_votes":
        _publish_replay_cue(
            publish,
            exile_no_result_cue(exile_resolution_reason),
            round_number=round_number,
            phase="vote",
        )
    elif (
        exile_resolution_reason is None
        and not round_state.get("exiled")
        and not round_state.get("idiot_revealed")
        and not round_state.get("day_ended_by_self_explosion")
        and any(_dict_or_empty(entry) for entry in _list_or_empty(round_state.get("votes")))
    ):
        _publish_replay_cue(
            publish,
            legacy_exile_no_result_cue(),
            round_number=round_number,
            phase="vote",
        )

    idiot = _optional_str(round_state.get("idiot_revealed"))
    if idiot:
        for cue in idiot_reveal_cues(idiot):
            _publish_replay_cue(publish, cue, round_number=round_number, phase="vote")

    exiled = _optional_str(round_state.get("exiled"))
    if exiled:
        _publish_replay_cue(
            publish,
            exile_result_cue(exiled),
            round_number=round_number,
            phase="vote",
        )

    hunter_shot = _optional_str(round_state.get("hunter_shot"))
    if hunter_shot:
        _publish_replay_cue(
            publish,
            hunter_result_cue(hunter_shot),
            round_number=round_number,
            phase="vote",
        )

    badge = sheriff_badge_resolution_from_dict(round_state.get("sheriff_badge_resolution"))
    if badge is not None:
        for cue in sheriff_badge_cues(badge):
            _publish_replay_cue(publish, cue, round_number=round_number, phase="vote")
    else:
        badge_target = _optional_str(round_state.get("sheriff_badge_target"))
        badge_lost = round_state.get("sheriff_badge_lost") is True
        if badge_target or (badge_lost and election is not None):
            legacy_params: dict[str, object] = {"legacy_synthesized": True}
            _publish_replay_cue(
                publish,
                cue_spec(
                    "badge_owner_out",
                    static_asset_id="badge_owner_out",
                    params=legacy_params,
                ),
                round_number=round_number,
                phase="vote",
            )
            if badge_target:
                _publish_replay_cue(
                    publish,
                    cue_spec(
                        "badge_transfer",
                        f"警徽移交给 {badge_target}。",
                        static_asset_id=seat_asset_id("badge_transfer", badge_target),
                        params={**legacy_params, "to_player": badge_target},
                    ),
                    round_number=round_number,
                    phase="vote",
                )
            else:
                _publish_replay_cue(
                    publish,
                    cue_spec(
                        "badge_destroyed",
                        static_asset_id="badge_destroyed",
                        params=legacy_params,
                    ),
                    round_number=round_number,
                    phase="vote",
                )


def _publish_werewolf_vote(
    publish: Any,
    *,
    actor: str,
    target: str,
    vote_round: int,
    round_number: int,
    decision_stage: str | None = None,
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
            **({"decision_stage": decision_stage} if decision_stage else {}),
        },
    )


def _publish_werewolf_discussion(
    publish: Any,
    *,
    actor: str,
    target: str,
    message: str,
    round_number: int,
) -> None:
    result = {"target": target, "message": message}
    publish(
        "action_parsed",
        round_number=round_number,
        phase="night",
        actor=actor,
        action="werewolf_discuss",
        payload={
            "choice": target,
            "result": result,
            "visible_result": result,
            "message": message,
            "decision_stage": "proposal",
            "vote_round": 1,
        },
    )


def _publish_werewolf_tiebreak_cue(
    publish: Any,
    *,
    cue_id: str,
    visible_text: str,
    actor: str,
    candidates: list[str],
    round_number: int,
    target: str | None = None,
) -> None:
    params: dict[str, object] = {
        "player": actor,
        "players": candidates.copy(),
    }
    if target:
        params["target"] = target
    _publish_replay_cue(
        publish,
        cue_spec(cue_id, visible_text, params=params),
        round_number=round_number,
        phase="night",
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
