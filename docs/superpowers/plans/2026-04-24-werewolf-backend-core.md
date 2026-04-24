# Werewolf Backend Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backend-only Werewolf game core and CLI in `apps/api`, based on the reference project but runnable and testable without external LLM credentials.

**Architecture:** Add an `app.werewolf` package with dataclass-based domain models, a deterministic local model client, a game engine, JSON session logging, and a runner facade. Add `app.cli` as the command-line entry point for running one game from the backend.

**Tech Stack:** Python 3.12, FastAPI project layout, argparse, dataclasses, pathlib, pytest, ruff

---

## File Structure

- Create `apps/api/app/werewolf/__init__.py`: package exports.
- Create `apps/api/app/werewolf/config.py`: role names, default names, player count, round limits.
- Create `apps/api/app/werewolf/models.py`: serializable domain dataclasses.
- Create `apps/api/app/werewolf/local_ai.py`: deterministic local player decisions.
- Create `apps/api/app/werewolf/engine.py`: Werewolf round execution and winner checks.
- Create `apps/api/app/werewolf/logging.py`: session directory and JSON writing.
- Create `apps/api/app/werewolf/runner.py`: public `run_game(...)` entry point.
- Create `apps/api/app/cli.py`: argparse CLI.
- Create `apps/api/tests/test_werewolf_runner.py`: runner and logging behavior.
- Create `apps/api/tests/test_werewolf_cli.py`: CLI behavior.

## Task 1: Runner Contract And Logs

**Files:**
- Create: `apps/api/tests/test_werewolf_runner.py`
- Create: `apps/api/app/werewolf/__init__.py`
- Create: `apps/api/app/werewolf/config.py`
- Create: `apps/api/app/werewolf/models.py`
- Create: `apps/api/app/werewolf/local_ai.py`
- Create: `apps/api/app/werewolf/engine.py`
- Create: `apps/api/app/werewolf/logging.py`
- Create: `apps/api/app/werewolf/runner.py`

- [ ] **Step 1: Write failing runner tests**

Add tests that call `run_game(...)` with local models and a temp log directory:

```python
import json

import pytest

from app.werewolf.runner import GameRunError, run_game


def test_run_game_with_local_models_writes_complete_logs(tmp_path) -> None:
    result = run_game(logs_dir=tmp_path, seed=7, max_rounds=8)

    assert result.winner in {"Villagers", "Werewolves"}
    assert result.session_id.startswith("session_")
    assert result.log_directory.exists()
    assert (result.log_directory / "game_complete.json").exists()
    assert (result.log_directory / "game_logs.json").exists()

    state = json.loads((result.log_directory / "game_complete.json").read_text())
    assert state["winner"] == result.winner
    assert len(state["players"]) == 8
    assert state["error_message"] == ""


def test_run_game_is_reproducible_for_same_seed(tmp_path) -> None:
    first = run_game(logs_dir=tmp_path / "first", seed=11, max_rounds=8)
    second = run_game(logs_dir=tmp_path / "second", seed=11, max_rounds=8)

    first_state = json.loads((first.log_directory / "game_complete.json").read_text())
    second_state = json.loads((second.log_directory / "game_complete.json").read_text())

    assert first.winner == second.winner
    assert first_state["players"] == second_state["players"]


def test_run_game_records_partial_log_when_max_rounds_is_exceeded(tmp_path) -> None:
    with pytest.raises(GameRunError) as error:
        run_game(logs_dir=tmp_path, seed=3, max_rounds=0)

    assert error.value.log_directory is not None
    partial_file = error.value.log_directory / "game_partial.json"
    assert partial_file.exists()

    state = json.loads(partial_file.read_text())
    assert "Maximum rounds exceeded" in state["error_message"]
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_runner.py -q
```

Expected: FAIL because `app.werewolf` does not exist.

- [ ] **Step 3: Implement domain models, local AI, engine, logging, and runner**

Implement the smallest complete backend core that satisfies the tests:

- `models.py` uses dataclasses with `to_dict()` methods.
- `local_ai.py` picks deterministic actions from legal options.
- `engine.py` initializes 8 players, runs night/day phases, checks winners, and enforces `max_rounds`.
- `logging.py` writes `game_complete.json` or `game_partial.json` plus `game_logs.json`.
- `runner.py` exposes `run_game(...)`, `RunGameResult`, and `GameRunError`.

- [ ] **Step 4: Run runner tests and verify GREEN**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_runner.py -q
```

Expected: PASS.

## Task 2: Backend CLI

**Files:**
- Create: `apps/api/tests/test_werewolf_cli.py`
- Create: `apps/api/app/cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests that call `main(...)` directly:

```python
from app.cli import main


def test_run_game_command_prints_result(tmp_path, capsys) -> None:
    exit_code = main([
        "run-game",
        "--logs-dir",
        str(tmp_path),
        "--seed",
        "13",
        "--max-rounds",
        "8",
    ])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "winner=" in output
    assert "session_id=session_" in output
    assert "log_directory=" in output


def test_run_game_command_returns_nonzero_on_engine_failure(tmp_path, capsys) -> None:
    exit_code = main([
        "run-game",
        "--logs-dir",
        str(tmp_path),
        "--seed",
        "13",
        "--max-rounds",
        "0",
    ])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Maximum rounds exceeded" in captured.err
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_cli.py -q
```

Expected: FAIL because `app.cli` does not exist.

- [ ] **Step 3: Implement `app.cli`**

Use `argparse` with a `run-game` subcommand. Parse `--villager-model`, `--werewolf-model`, `--seed`, `--logs-dir`, and `--max-rounds`, call `run_game(...)`, print `winner`, `session_id`, and `log_directory`, and return `1` on `GameRunError`.

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_cli.py -q
```

Expected: PASS.

## Task 3: Full Backend Verification

**Files:**
- Modify only backend files under `apps/api/app` and `apps/api/tests`.
- Do not modify files under `apps/web`.

- [ ] **Step 1: Run all backend tests**

Run:

```bash
cd apps/api && uv run pytest
```

Expected: PASS.

- [ ] **Step 2: Run backend lint**

Run:

```bash
cd apps/api && uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Smoke test the CLI**

Run:

```bash
cd apps/api && uv run python -m app.cli run-game --villager-model local --werewolf-model local --seed 21 --max-rounds 8
```

Expected: exit code 0 and output containing `winner=`, `session_id=session_`, and `log_directory=`.

## Self-Review

- Spec coverage: The plan covers backend-only scope, Werewolf domain modules, CLI, local model behavior, session JSON logs, max-round failure handling, and backend verification. Frontend work is explicitly excluded.
- Placeholder scan: No `TBD`, `TODO`, or unspecified test steps remain.
- Type consistency: Tests and planned implementation use `run_game`, `RunGameResult`, `GameRunError`, `winner`, `session_id`, and `log_directory` consistently.
