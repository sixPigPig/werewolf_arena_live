from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.werewolf.live import LiveEvent, ProjectedLiveEvent


ProjectionAudience = Literal["player_public", "spectator_god_view"]

PROJECTION_VERSION = 1

_KNOWN_EVENT_TYPES = frozenset(
    {
        "action_parsed",
        "action_quality_warning",
        "action_requested",
        "game_canceled",
        "game_completed",
        "game_failed",
        "game_resumed",
        "game_started",
        "idiot_revealed",
        "judge_cue",
        "model_request_failed",
        "model_request_started",
        "model_response_delta",
        "model_response_received",
        "model_retry_scheduled",
        "model_thinking_tick",
        "phase_started",
        "public_action_cancelled",
        "role_revealed",
        "round_started",
        "run_created",
        "run_recovered",
        "run_started",
        "run_stop_requested",
        "state_updated",
        "werewolf_self_exploded",
    }
)

_KNOWN_PLAYER_ACTIONS = frozenset(
    {
        "bid",
        "debate",
        "eliminate",
        "exile_pk_speech",
        "exile_last_words",
        "exile_runoff_vote",
        "hunter_shoot",
        "investigate",
        "protect",
        "remove",
        "sheriff_badge",
        "sheriff_pk_speech",
        "sheriff_run",
        "sheriff_runoff_vote",
        "sheriff_speech",
        "sheriff_vote",
        "sheriff_withdraw",
        "speech_order",
        "summarize",
        "vote",
        "werewolf_discuss",
        "werewolf_kill_vote",
        "werewolf_self_explosion",
        "witch_poison",
        "witch_save",
    }
)

_KNOWN_STATE_ACTIONS = frozenset(
    {
        "day_resolution_completed",
        "debate",
        "exile_resolved",
        "exile_last_words",
        "exile_no_result",
        "exile_pk_started",
        "exile_runoff_tied",
        "exile_runoff_vote",
        "hunter_shot_resolved",
        "idiot_revealed",
        "night_resolved",
        "public_round_brief",
        "sheriff_badge_resolved",
        "sheriff_election_resolved",
        "sheriff_pk_started",
        "vote",
        "werewolf_self_explosion",
    }
)

_KNOWN_JUDGE_CUES = frozenset(
    {
        "badge_destroyed",
        "badge_owner_out",
        "badge_transfer",
        "dawn_deaths",
        "dawn_peaceful",
        "exile_result",
        "exile_last_words",
        "exile_last_words_skipped",
        "exile_no_runoff_voters",
        "exile_no_votes",
        "exile_no_result",
        "exile_pk_start",
        "exile_runoff_tied",
        "exile_runoff_vote",
        "exile_tie",
        "guard_sleep",
        "guard_wake",
        "hunter_shot_choose",
        "hunter_shot_result",
        "hunter_shot_skipped",
        "hunter_shot_start",
        "idiot_reveal",
        "idiot_stays",
        "self_explosion_skip",
        "seer_sleep",
        "seer_wake",
        "sheriff_election_postponed",
        "sheriff_no_badge",
        "sheriff_no_voters",
        "sheriff_pk_start",
        "sheriff_raise_hands",
        "sheriff_result",
        "sheriff_runoff_tied",
        "sheriff_runoff_vote",
        "sheriff_tie",
        "werewolf_self_explosion",
        "werewolf_tiebreak_result",
        "werewolf_tiebreak_start",
        "werewolves_sleep",
        "werewolves_wake",
        "witch_death",
        "witch_sleep",
        "witch_wake",
    }
)

PRIVATE_ACTIONS = frozenset(
    {
        "eliminate",
        "remove",
        "protect",
        "investigate",
        "witch_save",
        "witch_poison",
        "werewolf_discuss",
        "werewolf_kill_vote",
        "summarize",
    }
)

_PUBLIC_ONLY_HIDDEN_ACTIONS = frozenset(
    {
        "werewolf_tiebreak_result",
        "werewolf_tiebreak_start",
        "witch_death",
    }
)

_NEVER_EXTERNAL_EVENT_TYPES = frozenset(
    {
        "model_response_received",
        "model_retry_scheduled",
    }
)

_SENSITIVE_KEYS = frozenset(
    {
        "attacked",
        "cause",
        "caused_by",
        "death_cause",
        "gamestate",
        "investigated",
        "known_roles",
        "observations",
        "poisoned",
        "private_summaries",
        "prompt",
        "protected",
        "raw_response",
        "raw_responses",
        "reasoning",
        "resources",
        "role",
        "saved_by_witch",
        "source",
        "system_prompt",
        "team",
        "true_role",
        "wolf_teammates",
        "world_state",
    }
)

_SENSITIVE_KEY_TOKENS = frozenset(
    re.sub(r"[^a-z0-9]", "", key.lower()) for key in _SENSITIVE_KEYS
)
_SENSITIVE_KEY_FRAGMENTS = frozenset(
    {
        "deathcause",
        "knownroles",
        "observation",
        "privatesummar",
        "prompt",
        "rawresponse",
        "reasoning",
        "source",
        "wolfteammate",
        "worldstate",
    }
)

_PLAYER_PUBLIC_PLAYER_FIELDS = frozenset(
    {
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
)

_GOD_VIEW_PLAYER_FIELDS = _PLAYER_PUBLIC_PLAYER_FIELDS | {"role"}

_COMMON_RUN_PAYLOAD_KEYS = frozenset(
    {
        "completed_at",
        "created_at",
        "event_count",
        "lineup_quality_report",
        "lineup_quality_warnings",
        "max_rounds",
        "playback",
        "player_configs",
        "resumable",
        "rule_set",
        "rule_set_content_hash",
        "rule_set_id",
        "rule_set_revision_id",
        "rule_set_revision_no",
        "run_id",
        "seed",
        "session_id",
        "started_at",
        "status",
        "stop_requested_at",
        "villager_model",
        "werewolf_model",
        "winner",
    }
)

_ACTION_PAYLOAD_KEYS = frozenset(
    {
        "action_id",
        "allowed_values",
        "attempt",
        "attempt_count",
        "choice",
        "delta",
        "decision_stage",
        "elapsed_ms",
        "fallback_choice",
        "fallback_reason",
        "field",
        "final_target",
        "invalid_value",
        "is_public",
        "message",
        "model",
        "options",
        "presentation_id",
        "request_id",
        "result",
        "result_key",
        "stream_field",
        "visible_result",
        "visible_text",
        "vote_round",
        "warnings",
    }
)

_STATE_PAYLOAD_KEYS = frozenset(
    {
        "active_players",
        "bids",
        "day_deaths",
        "day_ended_by_self_explosion",
        "deaths",
        "debate",
        "eliminated",
        "exiled",
        "exile_last_words",
        "exile_pk_candidates",
        "exile_pk_speeches",
        "exile_resolution_reason",
        "exile_runoff_votes",
        "hunter_shot",
        "hunter_shot_status",
        "idiot_revealed",
        "interruption",
        "narration_mode",
        "night_deaths",
        "peaceful_night",
        "public_outcome_events",
        "public_outcome_next_sequence",
        "public_summary",
        "presentation_id",
        "sheriff",
        "sheriff_badge_lost",
        "sheriff_badge_lost_reason",
        "sheriff_badge_resolution",
        "sheriff_badge_target",
        "sheriff_candidates",
        "sheriff_elected",
        "sheriff_election_open",
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
        "vote_weights",
        "votes",
        "werewolf_self_exploded",
    }
)

_JUDGE_CUE_PAYLOAD_KEYS = frozenset(
    {
        "completed_actors",
        "cue",
        "cue_id",
        "from_player",
        "hunter",
        "outcome",
        "params",
        "pending_actors",
        "pk_candidates",
        "player",
        "players",
        "reason_code",
        "schema_version",
        "sheriff",
        "stage",
        "static_asset_id",
        "target",
        "to_player",
        "visible_text",
    }
)

_PAYLOAD_KEYS_BY_EVENT_TYPE: dict[str, frozenset[str]] = {
    "run_created": _COMMON_RUN_PAYLOAD_KEYS,
    "run_started": frozenset({"playback"}),
    "run_recovered": frozenset(),
    "run_stop_requested": frozenset({"requested_at"}),
    "game_started": frozenset({"active_players", "playback", "players", "rule_set"}),
    "game_resumed": frozenset(
        {
            "active_players",
            "attempt_no",
            "parent_run_id",
            "players",
            "resume_from_round",
            "terminal_recovery",
        }
    ),
    "round_started": frozenset({"active_players", "playback", "round"}),
    "phase_started": frozenset({"active_players", "narration_mode", "playback"}),
    "public_action_cancelled": frozenset({"canceled_action", "reason_code"}),
    "judge_cue": _JUDGE_CUE_PAYLOAD_KEYS,
    "action_requested": _ACTION_PAYLOAD_KEYS,
    "action_parsed": _ACTION_PAYLOAD_KEYS,
    "action_quality_warning": _ACTION_PAYLOAD_KEYS,
    "model_request_started": _ACTION_PAYLOAD_KEYS,
    "model_thinking_tick": _ACTION_PAYLOAD_KEYS,
    "model_response_delta": _ACTION_PAYLOAD_KEYS,
    "model_request_failed": _ACTION_PAYLOAD_KEYS,
    "model_response_received": _ACTION_PAYLOAD_KEYS,
    "model_retry_scheduled": _ACTION_PAYLOAD_KEYS,
    "state_updated": _STATE_PAYLOAD_KEYS,
    "role_revealed": frozenset({"player", "role"}),
    "idiot_revealed": frozenset({"player", "role"}),
    "werewolf_self_exploded": frozenset({"player", "role"}),
    "game_completed": frozenset({"playback", "roles", "terminal_keep_from_event_id", "winner"}),
    "game_failed": frozenset({"error", "message", "playback_partial"}),
    "game_canceled": frozenset({"message", "reason"}),
}


def project_live_event(
    event: LiveEvent,
    audience: ProjectionAudience,
) -> ProjectedLiveEvent | None:
    """Project one canonical event into a stable external audience contract."""

    if audience not in {"player_public", "spectator_god_view"}:
        raise ValueError(f"Unsupported projection audience: {audience}")
    if not _event_is_visible(event, audience):
        return None

    payload = _project_payload(event, audience)
    return ProjectedLiveEvent(
        id=event.id,
        source_event_id=event.id,
        type=event.type,
        run_id=event.run_id,
        session_id=event.session_id,
        created_at=event.created_at,
        audience=audience,
        projection_version=PROJECTION_VERSION,
        round=event.round,
        phase=event.phase,
        actor=event.actor,
        action=event.action,
        payload=payload,
    )


def _event_is_visible(event: LiveEvent, audience: ProjectionAudience) -> bool:
    if event.type not in _KNOWN_EVENT_TYPES or not _action_is_known(event):
        return False
    if event.type in _NEVER_EXTERNAL_EVENT_TYPES:
        return False
    if event.action not in PRIVATE_ACTIONS:
        return not (
            audience == "player_public" and event.action in _PUBLIC_ONLY_HIDDEN_ACTIONS
        )
    if audience == "player_public":
        return False
    return event.type == "action_parsed" and event.action != "summarize"


def _action_is_known(event: LiveEvent) -> bool:
    if event.action is None:
        return event.type not in {
            "action_parsed",
            "action_quality_warning",
            "action_requested",
            "judge_cue",
            "model_request_failed",
            "model_request_started",
            "model_response_delta",
            "model_response_received",
            "model_retry_scheduled",
            "model_thinking_tick",
            "state_updated",
        }
    if event.type == "judge_cue":
        return event.action in _KNOWN_JUDGE_CUES
    if event.type == "state_updated":
        return event.action in _KNOWN_STATE_ACTIONS
    if event.type in {
        "action_parsed",
        "action_quality_warning",
        "action_requested",
        "model_request_failed",
        "model_request_started",
        "model_response_delta",
        "model_response_received",
        "model_retry_scheduled",
        "model_thinking_tick",
    }:
        return event.action in _KNOWN_PLAYER_ACTIONS
    return False


def _project_payload(event: LiveEvent, audience: ProjectionAudience) -> dict[str, Any]:
    allowed_keys = _PAYLOAD_KEYS_BY_EVENT_TYPE[event.type]
    payload = {
        key: value
        for key, value in event.payload.items()
        if key in allowed_keys
    }
    if event.type == "game_failed":
        return {
            "message": "对局异常中断。",
            **(
                {"playback_partial": True}
                if payload.get("playback_partial") is True
                else {}
            ),
        }
    if event.type == "game_canceled":
        return {"message": "对局已终止。"}
    if event.type == "game_completed" and audience == "player_public":
        payload.pop("roles", None)
    if event.type == "game_started":
        players = payload.get("players")
        projected = _sanitize_mapping(
            payload,
            audience=audience,
            allow_roles=audience == "spectator_god_view",
        )
        if isinstance(players, Sequence) and not isinstance(players, (str, bytes, bytearray)):
            allowed_fields = (
                _PLAYER_PUBLIC_PLAYER_FIELDS
                if audience == "player_public"
                else _GOD_VIEW_PLAYER_FIELDS
            )
            projected["players"] = [
                _sanitize_player(player, allowed_fields=allowed_fields, audience=audience)
                for player in players
                if isinstance(player, Mapping)
            ]
        return projected
    projected = _sanitize_mapping(
        payload,
        audience=audience,
        allow_roles=(
            audience == "spectator_god_view"
            or event.type
            in {"role_revealed", "idiot_revealed", "werewolf_self_exploded"}
        ),
    )
    if (
        event.type == "state_updated"
        and event.action == "night_resolved"
        and isinstance(projected.get("night_deaths"), list)
    ):
        projected["peaceful_night"] = not projected["night_deaths"]
    return projected


def _sanitize_player(
    player: Mapping[str, Any],
    *,
    allowed_fields: frozenset[str],
    audience: ProjectionAudience,
) -> dict[str, Any]:
    return {
        key: _sanitize_value(value, audience=audience, key=key)
        for key, value in player.items()
        if key in allowed_fields
    }


def _sanitize_mapping(
    value: Mapping[str, Any],
    *,
    audience: ProjectionAudience,
    allow_roles: bool = False,
    allow_team: bool = False,
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key).lower()
        normalized_token = re.sub(r"[^a-z0-9]", "", normalized_key)
        if normalized_key == "rule_set" and isinstance(item, Mapping):
            projected[str(key)] = _sanitize_mapping(
                item,
                audience=audience,
                allow_roles=True,
                allow_team=True,
            )
            continue
        if normalized_key == "roles" and isinstance(item, Mapping) and not allow_roles:
            continue
        key_is_sensitive = normalized_token in _SENSITIVE_KEY_TOKENS or any(
            fragment in normalized_token for fragment in _SENSITIVE_KEY_FRAGMENTS
        )
        if key_is_sensitive and not (
            (allow_roles and normalized_token in {"role", "truerole"})
            or (allow_team and normalized_token == "team")
        ):
            continue
        projected[str(key)] = _sanitize_value(
            item,
            audience=audience,
            key=normalized_key,
            allow_roles=allow_roles,
            allow_team=allow_team,
        )
    return projected


def _sanitize_value(
    value: Any,
    *,
    audience: ProjectionAudience,
    key: str,
    allow_roles: bool = False,
    allow_team: bool = False,
) -> Any:
    if key in {"night_deaths", "day_deaths"} and isinstance(value, list):
        return [
            {"player": item.get("player")}
            for item in value
            if isinstance(item, Mapping) and isinstance(item.get("player"), str)
        ]
    if isinstance(value, Mapping):
        return _sanitize_mapping(
            value,
            audience=audience,
            allow_roles=allow_roles,
            allow_team=allow_team,
        )
    if isinstance(value, list):
        return [
            _sanitize_value(
                item,
                audience=audience,
                key=key,
                allow_roles=allow_roles,
                allow_team=allow_team,
            )
            for item in value
        ]
    return value
