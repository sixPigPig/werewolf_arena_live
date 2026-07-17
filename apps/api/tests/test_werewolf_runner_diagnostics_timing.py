from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.werewolf import runner
from tests.rule_set_fixtures import (
    complete_resume_checkpoint,
    legacy_official_compiled_rule_set,
)


class _CompletingEngine:
    def __init__(self, **kwargs: object) -> None:
        self.state = kwargs["state"]
        self.logs: list[object] = []
        self.terminal_keep_from_event_id = None

    def run(self) -> list[object]:
        self.state.winner = "好人阵营"
        return self.logs


class _RunnerStore:
    def __init__(self, checkpoint: dict[str, object] | None = None) -> None:
        self.checkpoint = copy.deepcopy(checkpoint)
        self.saved: list[tuple[object, list[object]]] = []
        self.cleared: list[str] = []

    def load_resume_checkpoint(self, _session_id: str) -> dict[str, Any]:
        assert self.checkpoint is not None
        return copy.deepcopy(self.checkpoint)

    def save_game(self, state: object, logs: list[object]) -> None:
        self.saved.append((state, logs.copy()))

    def clear_resume_checkpoint(self, session_id: str) -> None:
        self.cleared.append(session_id)


def _install_clock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    started_at: datetime,
    completed_at: datetime,
) -> None:
    timestamps = iter((started_at, completed_at))
    monkeypatch.setattr(
        runner,
        "_utc_now",
        lambda: next(timestamps),
        raising=False,
    )


def test_run_game_passes_real_wall_clock_bounds_to_p2_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime(2026, 7, 17, 1, 2, 3, tzinfo=UTC)
    _install_clock(
        monkeypatch,
        started_at=started_at,
        completed_at=started_at + timedelta(milliseconds=2_345),
    )
    monkeypatch.setattr(runner, "GameEngine", _CompletingEngine)
    store = _RunnerStore()

    result = runner.run_game(
        record_store=store,  # type: ignore[arg-type]
        compiled_rule_set=legacy_official_compiled_rule_set("starter_6"),
        provider=object(),  # type: ignore[arg-type]
        session_id="game_timing",
    )

    assert result.p2_diagnostics["performance"]["game_duration_ms"] == 2_345
    assert store.cleared == ["game_timing"]


def test_resume_game_passes_real_wall_clock_bounds_to_p2_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_resume_timing"
    compiled = legacy_official_compiled_rule_set("starter_6")
    store = _RunnerStore(complete_resume_checkpoint(session_id, compiled))
    started_at = datetime(2026, 7, 17, 5, 6, 7, tzinfo=UTC)
    _install_clock(
        monkeypatch,
        started_at=started_at,
        completed_at=started_at + timedelta(milliseconds=4_567),
    )
    monkeypatch.setattr(runner, "GameEngine", _CompletingEngine)

    result = runner.resume_game(
        session_id=session_id,
        record_store=store,  # type: ignore[arg-type]
        provider=object(),  # type: ignore[arg-type]
    )

    assert result.p2_diagnostics["performance"]["game_duration_ms"] == 4_567
    assert store.cleared == [session_id]
