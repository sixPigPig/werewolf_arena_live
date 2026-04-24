from __future__ import annotations

import json
from pathlib import Path

from app.werewolf.models import GameState, RoundLog


def save_game(state: GameState, logs: list[RoundLog], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)

    state_file = directory / "game_complete.json"
    partial_file = directory / "game_partial.json"
    if state.error_message:
        state_file = partial_file
    elif partial_file.exists():
        partial_file.unlink()

    _write_json(state_file, state.to_dict())
    _write_json(directory / "game_logs.json", [log.to_dict() for log in logs])


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
