from __future__ import annotations

import copy
import json
import random
import re
import threading
from collections.abc import Mapping
from typing import Any

from app.rule_sets.telemetry import record_rule_checkpoint_failure
from app.rule_sets.types import CompiledRuleSet
from app.werewolf.lm import LmLog, ModelProvider
from app.werewolf.models import (
    ActionLog,
    DebateEntry,
    DeathEvent,
    GameState,
    GameView,
    Player,
    RoundLog,
    RoundState,
)

RESUME_CHECKPOINT_FILE = "resume_checkpoint.json"
CHECKPOINT_SCHEMA_VERSION = 2
SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS = frozenset({1, 2})
_CONTENT_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_EXECUTION_RUN_PARAM_NAMES = (
    "villager_model",
    "werewolf_model",
    "seed",
    "max_rounds",
    "player_configs",
)
_DUPLICATE_RULE_PARAM_NAMES = (
    "revision_id",
    "revision_no",
    "content_hash",
    "rule_set_snapshot",
)
_CHECKPOINT_ERROR_MESSAGES = {
    "missing": "Resume checkpoint is missing",
    "unsupported_schema": "Resume checkpoint schema is unsupported",
    "invalid_structure": "Resume checkpoint structure is invalid",
    "invalid_rule_snapshot": "Resume checkpoint rule snapshot is invalid",
    "rule_snapshot_mismatch": "Resume checkpoint rule snapshots disagree",
    "rule_metadata_mismatch": "Resume checkpoint rule metadata disagrees",
}


class ResumeCheckpointError(Exception):
    """Raised when a resume checkpoint cannot be read."""

    def __init__(self, reason: str = "invalid_structure") -> None:
        bounded_reason = reason if reason in _CHECKPOINT_ERROR_MESSAGES else "invalid_structure"
        super().__init__(_CHECKPOINT_ERROR_MESSAGES[bounded_reason])
        self.reason = bounded_reason
        record_rule_checkpoint_failure(bounded_reason)


def resolved_rule_set_from_checkpoint(
    checkpoint: Mapping[str, object],
) -> CompiledRuleSet:
    if not isinstance(checkpoint, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    if "schema_version" not in checkpoint:
        raise ResumeCheckpointError("invalid_structure")
    schema_version = checkpoint.get("schema_version")
    if type(schema_version) is not int:
        raise ResumeCheckpointError("invalid_structure")
    if schema_version not in SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS:
        raise ResumeCheckpointError("unsupported_schema")
    state = checkpoint.get("state_at_round_start")
    run_params = checkpoint.get("run_params")
    if not isinstance(state, Mapping) or not isinstance(run_params, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    state_snapshot = state.get("rule_set")
    if not isinstance(state_snapshot, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    state_compiled = _resolve_checkpoint_rule_snapshot(state_snapshot)

    rule_set_id = run_params.get("rule_set_id")
    if type(rule_set_id) is not str or not rule_set_id or rule_set_id.strip() != rule_set_id:
        raise ResumeCheckpointError("rule_metadata_mismatch")

    present_duplicate_fields = {name for name in _DUPLICATE_RULE_PARAM_NAMES if name in run_params}
    if schema_version == 1:
        if present_duplicate_fields and present_duplicate_fields != set(
            _DUPLICATE_RULE_PARAM_NAMES
        ):
            raise ResumeCheckpointError("rule_metadata_mismatch")
        compiled = state_compiled
        if present_duplicate_fields:
            run_compiled = _resolve_checkpoint_rule_snapshot(
                _mapping_value(run_params, "rule_set_snapshot")
            )
            if run_compiled.snapshot != state_compiled.snapshot:
                raise ResumeCheckpointError("rule_snapshot_mismatch")
            _require_checkpoint_rule_metadata(run_params, state_compiled)
    else:
        if present_duplicate_fields != set(_DUPLICATE_RULE_PARAM_NAMES):
            raise ResumeCheckpointError("rule_metadata_mismatch")
        compiled = _resolve_checkpoint_rule_snapshot(
            _mapping_value(run_params, "rule_set_snapshot")
        )
        if compiled.snapshot != state_compiled.snapshot:
            raise ResumeCheckpointError("rule_snapshot_mismatch")
        _require_checkpoint_rule_metadata(run_params, compiled)

    if rule_set_id != compiled.rule_set.id:
        raise ResumeCheckpointError("rule_metadata_mismatch")
    return compiled


def _mapping_value(mapping: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = mapping.get(name)
    if not isinstance(value, Mapping):
        raise ResumeCheckpointError("invalid_rule_snapshot")
    return value


def _resolve_checkpoint_rule_snapshot(
    snapshot: Mapping[str, object],
) -> CompiledRuleSet:
    from app.rule_sets.snapshots import resolve_rule_set_snapshot

    try:
        compiled = resolve_rule_set_snapshot(snapshot)
    except ResumeCheckpointError:
        raise
    except Exception:
        raise ResumeCheckpointError("invalid_rule_snapshot") from None
    if compiled.revision_id is not None and compiled.revision_id.strip() != compiled.revision_id:
        raise ResumeCheckpointError("rule_metadata_mismatch")
    return compiled


def _require_checkpoint_rule_metadata(
    run_params: Mapping[str, object],
    compiled: CompiledRuleSet,
) -> None:
    revision_id = run_params.get("revision_id")
    revision_no = run_params.get("revision_no")
    content_hash = run_params.get("content_hash")
    if (
        type(content_hash) is not str
        or _CONTENT_HASH_PATTERN.fullmatch(content_hash) is None
        or content_hash != compiled.content_hash
    ):
        raise ResumeCheckpointError("rule_metadata_mismatch")
    if compiled.revision_id is None and compiled.revision_no is None:
        if revision_id is not None or revision_no is not None:
            raise ResumeCheckpointError("rule_metadata_mismatch")
        return
    if (
        type(revision_id) is not str
        or not revision_id
        or revision_id.strip() != revision_id
        or revision_id != compiled.revision_id
        or type(revision_no) is not int
        or revision_no <= 0
        or revision_no != compiled.revision_no
    ):
        raise ResumeCheckpointError("rule_metadata_mismatch")


class ReplayThenLiveProvider:
    def __init__(
        self,
        *,
        cached_model_responses: list[dict[str, Any]],
        delegate: ModelProvider,
    ) -> None:
        self._cached_model_responses = copy.deepcopy(cached_model_responses)
        self._delegate = delegate
        self._lock = threading.Lock()

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        with self._lock:
            prompt_match_index = self._find_prompt_match(model=model, prompt=prompt)
            if prompt_match_index is not None:
                response = self._cached_model_responses.pop(prompt_match_index)
                return str(response["raw_response"])

            legacy_match_index = self._find_legacy_match()
            if legacy_match_index is not None:
                response = self._cached_model_responses.pop(legacy_match_index)
                return str(response["raw_response"])
        return self._delegate.complete_json(model=model, prompt=prompt, temperature=temperature)

    def _find_prompt_match(self, *, model: str, prompt: str) -> int | None:
        for index, response in enumerate(self._cached_model_responses):
            if response.get("model") == model and response.get("prompt") == prompt:
                return index
        return None

    def _find_legacy_match(self) -> int | None:
        for index, response in enumerate(self._cached_model_responses):
            if "prompt" not in response:
                return index
        return None


class ResumeCheckpointManager:
    def __init__(
        self,
        *,
        record_store: object,
        session_id: str,
        compiled_rule_set: CompiledRuleSet,
        run_params: dict[str, Any],
    ) -> None:
        self.record_store = record_store
        self.session_id = session_id
        self.rule_set_snapshot = copy.deepcopy(compiled_rule_set.snapshot)
        self.run_params = {
            name: copy.deepcopy(run_params.get(name)) for name in _EXECUTION_RUN_PARAM_NAMES
        }
        self.run_params.update(
            {
                "rule_set_id": compiled_rule_set.rule_set.id,
                "revision_id": compiled_rule_set.revision_id,
                "revision_no": compiled_rule_set.revision_no,
                "content_hash": compiled_rule_set.content_hash,
                "rule_set_snapshot": copy.deepcopy(self.rule_set_snapshot),
            }
        )
        self._checkpoint: dict[str, Any] | None = None

    def start_round(
        self,
        *,
        state: GameState,
        logs: list[RoundLog],
        round_number: int,
        active_players: list[str],
        rng_state: object,
    ) -> None:
        state_payload = state.to_dict()
        state_payload["rule_set"] = copy.deepcopy(self.rule_set_snapshot)
        self._checkpoint = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "session_id": self.session_id,
            "run_params": copy.deepcopy(self.run_params),
            "round_number": round_number,
            "active_players": active_players.copy(),
            "rng_state": _json_safe_rng_state(rng_state),
            "state_at_round_start": state_payload,
            "logs_before_round": [log.to_dict() for log in logs],
            "cached_model_responses": [],
            "failed_request": None,
            "last_error": None,
        }
        self._save()

    def record_success(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        raw_response: str,
        prompt: str | None = None,
    ) -> None:
        if self._checkpoint is None:
            return
        cached_response = {
            "actor": actor,
            "action": action,
            "phase": phase,
            "model": model,
            "raw_response": raw_response,
        }
        if prompt is not None:
            cached_response["prompt"] = prompt
        self._checkpoint["cached_model_responses"].append(cached_response)
        self._checkpoint["failed_request"] = None
        self._checkpoint["last_error"] = None
        self._save()

    def record_failure(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        error: str,
    ) -> None:
        if self._checkpoint is None:
            return
        failed_request = {
            "actor": actor,
            "action": action,
            "phase": phase,
            "model": model,
            "error": error,
        }
        self._checkpoint["failed_request"] = failed_request
        self._checkpoint["last_error"] = error
        self._save()

    def _save(self) -> None:
        if self._checkpoint is None:
            return
        self.record_store.save_resume_checkpoint(self.session_id, self._checkpoint)


def game_state_from_dict(data: dict[str, Any]) -> GameState:
    return GameState(
        session_id=str(data["session_id"]),
        players=[player_from_dict(player) for player in data.get("players", [])],
        rule_set=copy.deepcopy(data.get("rule_set") or {}),
        rounds=[round_state_from_dict(round_state) for round_state in data.get("rounds", [])],
        winner=str(data.get("winner") or ""),
        error_message=str(data.get("error_message") or ""),
        sheriff=data.get("sheriff"),
        sheriff_badge_lost=bool(data.get("sheriff_badge_lost", False)),
        sheriff_pre_election_bomb_count=int(data.get("sheriff_pre_election_bomb_count", 0)),
        sheriff_election_pending=bool(data.get("sheriff_election_pending", False)),
        public_facts=copy.deepcopy(data.get("public_facts", [])),
    )


def round_logs_from_dict(data: list[Any]) -> list[RoundLog]:
    return [round_log_from_dict(log) for log in data if isinstance(log, dict)]


def rng_from_json_state(data: object) -> random.Random:
    rng = random.Random()
    if data is not None:
        rng.setstate(_tupleize_rng_state(data))
    return rng


def player_from_dict(data: dict[str, Any]) -> Player:
    return Player(
        name=str(data["name"]),
        role=str(data["role"]),
        model=str(data["model"]),
        personality_id=str(data.get("personality_id") or "balanced"),
        personality=str(data.get("personality") or ""),
        appearance_id=str(data.get("appearance_id") or "default"),
        avatar_prompt=str(data.get("avatar_prompt") or ""),
        avatar_image_url=str(data.get("avatar_image_url") or ""),
        profile_id=str(data["profile_id"]) if data.get("profile_id") is not None else None,
        tags=[str(item) for item in data.get("tags", [])],
        observations=[str(item) for item in data.get("observations", [])],
        bidding_rationale=str(data.get("bidding_rationale") or ""),
        gamestate=game_view_from_dict(data["gamestate"]) if data.get("gamestate") else None,
        known_roles={str(key): str(value) for key, value in data.get("known_roles", {}).items()},
        can_vote=bool(data.get("can_vote", True)),
        revealed_role=bool(data.get("revealed_role", False)),
        witch_antidote_available=bool(data.get("witch_antidote_available", False)),
        witch_poison_available=bool(data.get("witch_poison_available", False)),
        hunter_can_shoot=bool(data.get("hunter_can_shoot", False)),
        is_sheriff=bool(data.get("is_sheriff", False)),
    )


def game_view_from_dict(data: dict[str, Any]) -> GameView:
    return GameView(
        round_number=int(data.get("round_number", 0)),
        current_players=[str(player) for player in data.get("current_players", [])],
        debate=[debate_entry_from_dict(entry) for entry in data.get("debate", [])],
        other_wolf=data.get("other_wolf"),
        wolf_teammates=[str(player) for player in data.get("wolf_teammates", [])],
    )


def round_state_from_dict(data: dict[str, Any]) -> RoundState:
    return RoundState(
        number=int(data["number"]),
        players=[str(player) for player in data.get("players", [])],
        attacked=data.get("attacked"),
        eliminated=data.get("eliminated"),
        protected=data.get("protected"),
        investigated=data.get("investigated"),
        exiled=data.get("exiled"),
        night_deaths=[death_event_from_dict(item) for item in data.get("night_deaths", [])],
        day_deaths=[death_event_from_dict(item) for item in data.get("day_deaths", [])],
        saved_by_witch=data.get("saved_by_witch"),
        poisoned=data.get("poisoned"),
        hunter_shot=data.get("hunter_shot"),
        idiot_revealed=data.get("idiot_revealed"),
        debate=[debate_entry_from_dict(entry) for entry in data.get("debate", [])],
        bids=copy.deepcopy(data.get("bids", [])),
        votes=copy.deepcopy(data.get("votes", [])),
        summaries=copy.deepcopy(data.get("summaries", {})),
        private_summaries=copy.deepcopy(data.get("private_summaries", {})),
        public_summary=str(data.get("public_summary") or ""),
        sheriff=data.get("sheriff"),
        sheriff_candidates=[str(item) for item in data.get("sheriff_candidates", [])],
        sheriff_speech_order=[str(item) for item in data.get("sheriff_speech_order", [])],
        sheriff_speech_direction=data.get("sheriff_speech_direction"),
        sheriff_speeches=copy.deepcopy(data.get("sheriff_speeches", [])),
        sheriff_withdrawn=[str(item) for item in data.get("sheriff_withdrawn", [])],
        sheriff_final_candidates=[str(item) for item in data.get("sheriff_final_candidates", [])],
        sheriff_voters=[str(item) for item in data.get("sheriff_voters", [])],
        sheriff_votes=copy.deepcopy(data.get("sheriff_votes", {})),
        sheriff_pk_candidates=[str(item) for item in data.get("sheriff_pk_candidates", [])],
        sheriff_pk_speeches=copy.deepcopy(data.get("sheriff_pk_speeches", [])),
        sheriff_runoff_votes=copy.deepcopy(data.get("sheriff_runoff_votes", {})),
        sheriff_elected=data.get("sheriff_elected"),
        speech_order=[str(item) for item in data.get("speech_order", [])],
        speech_order_choice=data.get("speech_order_choice"),
        vote_weights=copy.deepcopy(data.get("vote_weights", {})),
        werewolf_discussion=copy.deepcopy(data.get("werewolf_discussion", [])),
        werewolf_vote_rounds=copy.deepcopy(data.get("werewolf_vote_rounds", [])),
        sheriff_badge_target=data.get("sheriff_badge_target"),
        sheriff_badge_lost=bool(data.get("sheriff_badge_lost", False)),
        werewolf_self_exploded=data.get("werewolf_self_exploded"),
        day_ended_by_self_explosion=bool(data.get("day_ended_by_self_explosion", False)),
        sheriff_pre_election_bomb_count=int(data.get("sheriff_pre_election_bomb_count", 0)),
        sheriff_election_pending=bool(data.get("sheriff_election_pending", False)),
        sheriff_badge_lost_reason=data.get("sheriff_badge_lost_reason"),
        success=bool(data.get("success", False)),
    )


def round_log_from_dict(data: dict[str, Any]) -> RoundLog:
    return RoundLog(
        number=int(data["number"]),
        eliminate=optional_action_log_from_dict(data.get("eliminate")),
        protect=optional_action_log_from_dict(data.get("protect")),
        investigate=optional_action_log_from_dict(data.get("investigate")),
        witch_save=optional_action_log_from_dict(data.get("witch_save")),
        witch_poison=optional_action_log_from_dict(data.get("witch_poison")),
        hunter_shoot=optional_action_log_from_dict(data.get("hunter_shoot")),
        bid=action_log_groups_from_dict(data.get("bid", [])),
        debate=action_logs_from_dict(data.get("debate", [])),
        votes=action_log_groups_from_dict(data.get("votes", [])),
        summaries=action_logs_from_dict(data.get("summaries", [])),
        sheriff_run=action_logs_from_dict(data.get("sheriff_run", [])),
        sheriff_speech=action_logs_from_dict(data.get("sheriff_speech", [])),
        sheriff_withdraw=action_logs_from_dict(data.get("sheriff_withdraw", [])),
        sheriff_pk_speech=action_logs_from_dict(data.get("sheriff_pk_speech", [])),
        sheriff_runoff_votes=action_logs_from_dict(data.get("sheriff_runoff_votes", [])),
        sheriff_votes=action_logs_from_dict(data.get("sheriff_votes", [])),
        speech_order=optional_action_log_from_dict(data.get("speech_order")),
        sheriff_badge=optional_action_log_from_dict(data.get("sheriff_badge")),
        werewolf_self_explosion=optional_action_log_from_dict(data.get("werewolf_self_explosion")),
        werewolf_discussion=action_logs_from_dict(data.get("werewolf_discussion", [])),
        werewolf_votes=action_log_groups_from_dict(data.get("werewolf_votes", [])),
    )


def optional_action_log_from_dict(data: object) -> ActionLog | None:
    return action_log_from_dict(data) if isinstance(data, dict) else None


def action_logs_from_dict(data: object) -> list[ActionLog]:
    if not isinstance(data, list):
        return []
    return [action_log_from_dict(item) for item in data if isinstance(item, dict)]


def action_log_groups_from_dict(data: object) -> list[list[ActionLog]]:
    if not isinstance(data, list):
        return []
    return [action_logs_from_dict(group) for group in data if isinstance(group, list)]


def action_log_from_dict(data: dict[str, Any]) -> ActionLog:
    lm_log_data = data.get("lm_log", {})
    if not isinstance(lm_log_data, dict):
        lm_log_data = {}
    return ActionLog(
        actor=str(data.get("actor") or ""),
        action=str(data.get("action") or ""),
        options=[str(item) for item in data.get("options", [])],
        choice=data.get("choice"),
        lm_log=LmLog(
            prompt=str(lm_log_data.get("prompt") or ""),
            raw_response=str(lm_log_data.get("raw_response") or ""),
            result=lm_log_data.get("result", lm_log_data.get("parsed")),
            request_id=lm_log_data.get("request_id"),
            invalid_attempts=copy.deepcopy(lm_log_data.get("invalid_attempts", [])),
        ),
        invalid_value=data.get("invalid_value"),
        fallback_choice=data.get("fallback_choice"),
        fallback_reason=data.get("fallback_reason"),
        attempt_count=int(data.get("attempt_count") or 1),
    )


def death_event_from_dict(data: dict[str, Any]) -> DeathEvent:
    return DeathEvent(
        player=str(data.get("player") or ""),
        cause=str(data.get("cause") or ""),
        source=data.get("source"),
    )


def debate_entry_from_dict(data: dict[str, Any]) -> DebateEntry:
    return DebateEntry(
        speaker=str(data.get("speaker") or ""),
        message=str(data.get("message") or ""),
    )


def _json_safe_rng_state(state: object) -> object:
    return json.loads(json.dumps(state))


def _tupleize_rng_state(data: object) -> Any:
    if isinstance(data, list):
        return tuple(_tupleize_rng_state(item) for item in data)
    return data
