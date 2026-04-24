from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.werewolf.config import DEFAULT_MAX_ROUNDS
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.logging import save_game
from app.werewolf.lm import ModelProvider
from app.werewolf.providers import DeepSeekProvider


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
    villager_model: str = "deepseek-chat",
    werewolf_model: str = "deepseek-chat",
    seed: int | None = None,
    logs_dir: str | Path = "logs",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    provider: ModelProvider | None = None,
) -> RunGameResult:
    session_id = _new_session_id()
    log_directory = Path(logs_dir) / session_id
    state = initialize_game_state(
        session_id=session_id,
        villager_model=villager_model,
        werewolf_model=werewolf_model,
        seed=seed,
    )
    logs = []

    try:
        engine = GameEngine(
            state=state,
            provider=provider or DeepSeekProvider(),
            max_rounds=max_rounds,
        )
        logs = engine.run()
    except Exception as exc:
        state.error_message = str(exc)
        save_game(state, logs, log_directory)
        raise GameRunError(str(exc), log_directory) from exc

    save_game(state, logs, log_directory)
    return RunGameResult(
        winner=state.winner,
        session_id=session_id,
        log_directory=log_directory,
    )


def _new_session_id() -> str:
    timestamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%d_%H%M%S")
    return f"session_{timestamp}_{uuid.uuid4().hex[:8]}"
