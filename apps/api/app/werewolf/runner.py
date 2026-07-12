from __future__ import annotations

import copy
import random
import uuid
from dataclasses import dataclass

from app.rule_sets.types import CompiledRuleSet
from app.werewolf.checkpoint import (
    ReplayThenLiveProvider,
    ResumeCheckpointError,
    ResumeCheckpointManager,
    game_state_from_dict,
    rng_from_json_state,
    round_logs_from_dict,
)
from app.werewolf.config import DEFAULT_MAX_ROUNDS
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.live import GameRunCanceled, NullEventSink
from app.werewolf.lm import ModelProvider
from app.werewolf.player_configs import PlayerConfig
from app.werewolf.providers import create_model_provider, default_model_name
from app.werewolf.replay import GameRecordStore, ReplayWriteFencedError
from app.werewolf.rules import DEFAULT_RULE_SET_ID


@dataclass(frozen=True)
class RunGameResult:
    winner: str
    session_id: str


class GameRunError(RuntimeError):
    def __init__(self, message: str, session_id: str | None = None) -> None:
        super().__init__(message)
        self.session_id = session_id


def run_game(
    *,
    record_store: GameRecordStore,
    compiled_rule_set: CompiledRuleSet,
    villager_model: str | None = None,
    werewolf_model: str | None = None,
    seed: int | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    provider: ModelProvider | None = None,
    session_id: str | None = None,
    event_sink: object | None = None,
    player_configs: list[PlayerConfig] | None = None,
) -> RunGameResult:
    session_id = session_id or new_session_id()
    rule_set = compiled_rule_set.rule_set
    default_model = default_model_name()
    selected_villager_model = villager_model or default_model
    selected_werewolf_model = werewolf_model or default_model
    run_params = {
        "villager_model": selected_villager_model,
        "werewolf_model": selected_werewolf_model,
        "seed": seed,
        "max_rounds": max_rounds,
        "rule_set_id": rule_set.id,
        "revision_id": compiled_rule_set.revision_id,
        "revision_no": compiled_rule_set.revision_no,
        "content_hash": compiled_rule_set.content_hash,
        "rule_set_snapshot": copy.deepcopy(compiled_rule_set.snapshot),
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
    state.rule_set = copy.deepcopy(compiled_rule_set.snapshot)
    logs = []
    checkpoint_manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=session_id,
        run_params=run_params,
    )
    engine_rng = random.Random(f"{seed}:engine") if seed is not None else random.Random()

    engine = None
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
    except ReplayWriteFencedError:
        raise
    except GameRunCanceled:
        if engine is not None:
            logs = engine.logs
        state.error_message = "Run canceled by administrator"
        record_store.save_game(state, logs)
        raise
    except Exception as exc:
        if engine is not None:
            logs = engine.logs
        state.error_message = str(exc)
        record_store.save_game(state, logs)
        raise GameRunError(str(exc), session_id) from exc

    record_store.save_game(state, logs)
    record_store.clear_resume_checkpoint(session_id)
    return RunGameResult(
        winner=state.winner,
        session_id=session_id,
    )


def resume_game(
    *,
    session_id: str,
    record_store: GameRecordStore,
    provider: ModelProvider | None = None,
    event_sink: object | None = None,
) -> RunGameResult:
    try:
        checkpoint = record_store.load_resume_checkpoint(session_id)
    except ResumeCheckpointError as exc:
        raise GameRunError("Resume checkpoint not found", session_id) from exc

    run_params = checkpoint.get("run_params", {})
    if not isinstance(run_params, dict):
        raise GameRunError("Resume checkpoint is invalid", session_id)

    from app.werewolf.rules import get_rule_set

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
        record_store=record_store,
        session_id=session_id,
        run_params=run_params,
    )
    rng = rng_from_json_state(checkpoint.get("rng_state"))
    logs_after_resume = []

    engine = None
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
    except ReplayWriteFencedError:
        raise
    except GameRunCanceled:
        if engine is not None:
            logs_after_resume = engine.logs
        state.error_message = "Run canceled by administrator"
        record_store.save_game(state, logs_before_round + logs_after_resume)
        raise
    except Exception as exc:
        if engine is not None:
            logs_after_resume = engine.logs
        state.error_message = str(exc)
        record_store.save_game(state, logs_before_round + logs_after_resume)
        raise GameRunError(str(exc), session_id) from exc

    logs = logs_before_round + logs_after_resume
    record_store.save_game(state, logs)
    record_store.clear_resume_checkpoint(session_id)
    return RunGameResult(
        winner=state.winner,
        session_id=session_id,
    )


def _new_session_id() -> str:
    return new_session_id()


def new_session_id() -> str:
    return f"game_{uuid.uuid4().hex[:8]}"
