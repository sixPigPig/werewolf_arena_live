from __future__ import annotations

import datetime as dt
import random
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.werewolf.checkpoint import (
    ReplayThenLiveProvider,
    ResumeCheckpointError,
    ResumeCheckpointManager,
    clear_resume_checkpoint,
    game_state_from_dict,
    load_resume_checkpoint,
    rng_from_json_state,
    round_logs_from_dict,
)
from app.werewolf.config import DEFAULT_MAX_ROUNDS
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.live import NullEventSink
from app.werewolf.logging import save_game
from app.werewolf.lm import ModelProvider
from app.werewolf.player_configs import PlayerConfig
from app.werewolf.providers import create_model_provider, default_model_name
from app.werewolf.rules import DEFAULT_RULE_SET_ID, get_rule_set


@dataclass(frozen=True)
class RunGameResult:
    winner: str
    session_id: str
    log_directory: Path


class GameRunError(RuntimeError):
    def __init__(self, message: str, log_directory: Path | None = None) -> None:
        super().__init__(message)
        self.log_directory = log_directory


def run_game(
    *,
    villager_model: str | None = None,
    werewolf_model: str | None = None,
    seed: int | None = None,
    logs_dir: str | Path = "logs",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    provider: ModelProvider | None = None,
    session_id: str | None = None,
    event_sink: object | None = None,
    rule_set_id: str = DEFAULT_RULE_SET_ID,
    player_configs: list[PlayerConfig] | None = None,
) -> RunGameResult:
    session_id = session_id or new_session_id()
    log_directory = Path(logs_dir) / session_id
    rule_set = get_rule_set(rule_set_id)
    default_model = default_model_name()
    selected_villager_model = villager_model or default_model
    selected_werewolf_model = werewolf_model or default_model
    run_params = {
        "villager_model": selected_villager_model,
        "werewolf_model": selected_werewolf_model,
        "seed": seed,
        "max_rounds": max_rounds,
        "rule_set_id": rule_set.id,
        "player_configs": [config.to_dict() for config in player_configs or []],
    }
    state = initialize_game_state(
        session_id=session_id,
        villager_model=selected_villager_model,
        werewolf_model=selected_werewolf_model,
        seed=seed,
        rule_set=rule_set,
        player_configs=player_configs,
    )
    logs = []
    checkpoint_manager = ResumeCheckpointManager(
        log_directory=log_directory,
        session_id=session_id,
        run_params=run_params,
    )
    engine_rng = random.Random(f"{seed}:engine") if seed is not None else random.Random()

    try:
        engine = GameEngine(
            state=state,
            provider=provider or create_model_provider(),
            max_rounds=max_rounds,
            rule_set=rule_set,
            event_sink=event_sink or NullEventSink(),
            rng=engine_rng,
            checkpoint_manager=checkpoint_manager,
        )
        logs = engine.run()
    except Exception as exc:
        state.error_message = str(exc)
        save_game(state, logs, log_directory)
        raise GameRunError(str(exc), log_directory) from exc

    save_game(state, logs, log_directory)
    clear_resume_checkpoint(log_directory)
    return RunGameResult(
        winner=state.winner,
        session_id=session_id,
        log_directory=log_directory,
    )


def resume_game(
    *,
    session_id: str,
    logs_dir: str | Path = "logs",
    provider: ModelProvider | None = None,
    event_sink: object | None = None,
) -> RunGameResult:
    log_directory = Path(logs_dir) / session_id
    try:
        checkpoint = load_resume_checkpoint(log_directory)
    except ResumeCheckpointError as exc:
        raise GameRunError("Resume checkpoint not found", log_directory) from exc

    run_params = checkpoint.get("run_params", {})
    if not isinstance(run_params, dict):
        raise GameRunError("Resume checkpoint is invalid", log_directory)

    rule_set_id = str(run_params.get("rule_set_id") or DEFAULT_RULE_SET_ID)
    rule_set = get_rule_set(rule_set_id)
    max_rounds = int(run_params.get("max_rounds") or DEFAULT_MAX_ROUNDS)
    state = game_state_from_dict(checkpoint["state_at_round_start"])
    state.error_message = ""
    logs_before_round = round_logs_from_dict(checkpoint.get("logs_before_round", []))
    active_players = [str(player) for player in checkpoint.get("active_players", [])]
    if not active_players:
        active_players = [player.name for player in state.players]
    replay_provider = ReplayThenLiveProvider(
        cached_model_responses=checkpoint.get("cached_model_responses", []),
        delegate=provider or create_model_provider(),
    )
    checkpoint_manager = ResumeCheckpointManager(
        log_directory=log_directory,
        session_id=session_id,
        run_params=run_params,
    )
    rng = rng_from_json_state(checkpoint.get("rng_state"))
    logs_after_resume = []

    try:
        engine = GameEngine(
            state=state,
            provider=replay_provider,
            max_rounds=max_rounds,
            rule_set=rule_set,
            event_sink=event_sink or NullEventSink(),
            rng=rng,
            starting_active_players=active_players,
            checkpoint_manager=checkpoint_manager,
        )
        logs_after_resume = engine.run()
    except Exception as exc:
        state.error_message = str(exc)
        save_game(state, logs_before_round + logs_after_resume, log_directory)
        raise GameRunError(str(exc), log_directory) from exc

    logs = logs_before_round + logs_after_resume
    save_game(state, logs, log_directory)
    clear_resume_checkpoint(log_directory)
    return RunGameResult(
        winner=state.winner,
        session_id=session_id,
        log_directory=log_directory,
    )


def _new_session_id() -> str:
    return new_session_id()


def new_session_id() -> str:
    timestamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%d_%H%M%S")
    return f"session_{timestamp}_{uuid.uuid4().hex[:8]}"
