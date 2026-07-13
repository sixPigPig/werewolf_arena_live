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
    report_resume_checkpoint_error,
    resolved_rule_set_from_checkpoint,
    rng_from_json_state,
    round_logs_from_dict,
)
from app.werewolf.config import DEFAULT_MAX_ROUNDS
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.live import GameRunCanceled, NullEventSink, strict_json_equal
from app.werewolf.lm import ModelProvider
from app.werewolf.player_configs import PlayerConfig
from app.werewolf.providers import create_model_provider, default_model_name
from app.werewolf.replay import GameRecordStore, ReplayWriteFencedError


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
        compiled_rule_set=compiled_rule_set,
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
    expected_compiled_rule_set: CompiledRuleSet | None = None,
) -> RunGameResult:
    try:
        checkpoint = record_store.load_resume_checkpoint(session_id)
    except ResumeCheckpointError as exc:
        report_resume_checkpoint_error(exc)
        message = (
            "Resume checkpoint not found"
            if exc.reason == "missing"
            else "Resume checkpoint is invalid"
        )
        raise GameRunError(message, session_id) from exc

    try:
        compiled = resolved_rule_set_from_checkpoint(checkpoint)
    except ResumeCheckpointError as exc:
        report_resume_checkpoint_error(exc)
        raise GameRunError("Resume checkpoint is invalid", session_id) from exc
    if expected_compiled_rule_set is not None and not _compiled_rule_sets_match(
        compiled,
        expected_compiled_rule_set,
    ):
        raise GameRunError("Resume checkpoint rule snapshot changed", session_id)

    run_params = checkpoint.get("run_params", {})
    if not isinstance(run_params, dict):
        raise GameRunError("Resume checkpoint is invalid", session_id)
    max_rounds_value = run_params.get("max_rounds")
    if type(max_rounds_value) is not int or max_rounds_value <= 0:
        raise GameRunError("Resume checkpoint is invalid", session_id)
    max_rounds = max_rounds_value
    try:
        state = game_state_from_dict(checkpoint["state_at_round_start"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GameRunError("Resume checkpoint is invalid", session_id) from exc
    state.rule_set = copy.deepcopy(compiled.snapshot)
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
        compiled_rule_set=compiled,
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
            rule_set=compiled.rule_set,
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


def _compiled_rule_sets_match(
    first: CompiledRuleSet,
    second: CompiledRuleSet,
) -> bool:
    return (
        first.rule_set.id == second.rule_set.id
        and first.revision_id == second.revision_id
        and first.revision_no == second.revision_no
        and first.content_hash == second.content_hash
        and strict_json_equal(first.snapshot, second.snapshot)
    )


def _new_session_id() -> str:
    return new_session_id()


def new_session_id() -> str:
    return f"game_{uuid.uuid4().hex[:8]}"
