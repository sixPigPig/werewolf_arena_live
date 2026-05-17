from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

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
CHECKPOINT_SCHEMA_VERSION = 1


class ResumeCheckpointError(Exception):
    """Raised when a resume checkpoint cannot be read."""


class ReplayThenLiveProvider:
    def __init__(
        self,
        *,
        cached_model_responses: list[dict[str, Any]],
        delegate: ModelProvider,
    ) -> None:
        self._cached_model_responses = copy.deepcopy(cached_model_responses)
        self._delegate = delegate
        self._index = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if self._index < len(self._cached_model_responses):
            response = self._cached_model_responses[self._index]
            self._index += 1
            return str(response["raw_response"])
        return self._delegate.complete_json(model=model, prompt=prompt, temperature=temperature)


class ResumeCheckpointManager:
    def __init__(
        self,
        *,
        log_directory: Path,
        session_id: str,
        run_params: dict[str, Any],
    ) -> None:
        self.log_directory = log_directory
        self.session_id = session_id
        self.run_params = copy.deepcopy(run_params)
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
        self._checkpoint = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "session_id": self.session_id,
            "run_params": copy.deepcopy(self.run_params),
            "round_number": round_number,
            "active_players": active_players.copy(),
            "rng_state": _json_safe_rng_state(rng_state),
            "state_at_round_start": state.to_dict(),
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
    ) -> None:
        if self._checkpoint is None:
            return
        self._checkpoint["cached_model_responses"].append(
            {
                "actor": actor,
                "action": action,
                "phase": phase,
                "model": model,
                "raw_response": raw_response,
            }
        )
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
        self.log_directory.mkdir(parents=True, exist_ok=True)
        checkpoint_path = self.log_directory / RESUME_CHECKPOINT_FILE
        temporary_path = checkpoint_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(self._checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(checkpoint_path)


def load_resume_checkpoint(directory: Path) -> dict[str, Any]:
    checkpoint_path = directory / RESUME_CHECKPOINT_FILE
    if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
        raise ResumeCheckpointError
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResumeCheckpointError from exc
    if not isinstance(checkpoint, dict):
        raise ResumeCheckpointError
    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ResumeCheckpointError
    return checkpoint


def has_resume_checkpoint(directory: Path) -> bool:
    try:
        load_resume_checkpoint(directory)
    except ResumeCheckpointError:
        return False
    return True


def clear_resume_checkpoint(directory: Path) -> None:
    checkpoint_path = directory / RESUME_CHECKPOINT_FILE
    try:
        if checkpoint_path.exists() and not checkpoint_path.is_symlink():
            checkpoint_path.unlink()
    except OSError:
        return


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
        ),
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
