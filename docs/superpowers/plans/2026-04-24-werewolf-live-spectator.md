# Werewolf Live Spectator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build phase two live spectating: start a local single-user Werewolf game from the web UI and watch detailed engine/model events in real time.

**Architecture:** The backend adds an in-memory live run registry and an optional engine event sink. A new SSE endpoint streams replayable, ordered events to the frontend, while the existing final log files remain compatible with the replay workbench.

**Tech Stack:** FastAPI, Python dataclasses/threading/queue, existing Werewolf engine, React, React Router, TanStack Query, Vitest, Testing Library, browser `EventSource`.

---

## File Structure

Backend:

- Create `apps/api/app/werewolf/live.py`: live event dataclasses, run state, in-memory registry, SSE formatting helpers.
- Modify `apps/api/app/werewolf/engine.py`: optional `EventSink`, phase/action/state event publication.
- Modify `apps/api/app/werewolf/runner.py`: optional `session_id` and `event_sink`, so live runs can return the session id immediately.
- Modify `apps/api/app/api/routes/games.py`: add create run, get run status, and SSE event endpoints under `/games/runs`.
- Modify `apps/api/tests/test_games_api.py`: API-level tests for run creation, status, and SSE replay.
- Create `apps/api/tests/test_live.py`: focused tests for registry and SSE formatting.
- Modify `apps/api/tests/test_werewolf_runner.py`: ensure event sink defaults preserve existing behavior and custom session ids work.

Frontend:

- Modify `apps/web/src/features/games/types.ts`: add live run and live event types.
- Create `apps/web/src/features/games/api/createGameRun.ts`: POST run creation.
- Create `apps/web/src/features/games/api/getGameRun.ts`: GET run status.
- Create `apps/web/src/features/games/hooks/useGameRunEvents.ts`: EventSource subscription, dedupe, fallback state.
- Create `apps/web/src/features/games/components/CreateGameRunForm.tsx`: compact launch form.
- Create `apps/web/src/features/games/components/LiveStatusStrip.tsx`: current status and connection state.
- Create `apps/web/src/features/games/components/LiveEventTimeline.tsx`: ordered live event feed.
- Create `apps/web/src/pages/LiveGamePage.tsx`: realtime spectator page.
- Modify `apps/web/src/pages/GamesPage.tsx`: add launch form above existing session list.
- Modify `apps/web/src/routes/definitions.tsx`: add `/games/live/:runId`.
- Add/modify frontend tests in `apps/web/src/pages/GamesPage.test.tsx` and `apps/web/src/pages/LiveGamePage.test.tsx`.

---

### Task 1: Backend Live Registry

**Files:**
- Create: `apps/api/app/werewolf/live.py`
- Test: `apps/api/tests/test_live.py`

- [ ] **Step 1: Write failing registry tests**

Add `apps/api/tests/test_live.py`:

```python
from __future__ import annotations

from app.werewolf.live import LiveRunRegistry


def test_registry_creates_run_with_initial_event() -> None:
    registry = LiveRunRegistry()

    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )

    assert run.run_id.startswith("run_")
    assert run.session_id == "session_20260424_120000_ab12cd34"
    assert run.status == "queued"
    assert run.event_count == 1
    assert run.events[0].type == "run_created"


def test_registry_appends_ordered_events_and_replays_after_id() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )

    registry.publish(
        run.run_id,
        "game_started",
        payload={"players": ["张三", "李四"]},
    )
    registry.publish(
        run.run_id,
        "round_started",
        round_number=1,
        payload={"round": 1},
    )

    replayed = registry.events_after(run.run_id, after_id=1)

    assert [event.id for event in replayed] == [2, 3]
    assert [event.type for event in replayed] == ["game_started", "round_started"]
    assert replayed[1].round == 1


def test_registry_marks_completed_and_failed() -> None:
    registry = LiveRunRegistry()
    completed = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )
    failed = registry.create_run(
        session_id="session_20260424_120001_cd34ab12",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )

    registry.mark_running(completed.run_id)
    registry.mark_completed(completed.run_id, winner="狼人阵营")
    registry.mark_failed(failed.run_id, error="Maximum rounds exceeded")

    assert registry.get_run(completed.run_id).status == "completed"
    assert registry.get_run(completed.run_id).completed_at is not None
    assert registry.get_run(completed.run_id).events[-1].type == "game_completed"
    assert registry.get_run(failed.run_id).status == "failed"
    assert registry.get_run(failed.run_id).error == "Maximum rounds exceeded"
    assert registry.get_run(failed.run_id).events[-1].type == "game_failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_live.py -q
```

Expected: FAIL because `app.werewolf.live` does not exist.

- [ ] **Step 3: Implement live registry**

Create `apps/api/app/werewolf/live.py`:

```python
from __future__ import annotations

import json
import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


RunStatus = Literal["queued", "running", "completed", "failed"]


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LiveEvent:
    id: int
    type: str
    run_id: str
    session_id: str
    created_at: str
    round: int | None = None
    phase: str | None = None
    actor: str | None = None
    action: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "round": self.round,
            "phase": self.phase,
            "actor": self.actor,
            "action": self.action,
            "payload": self.payload,
        }


@dataclass
class LiveGameRun:
    run_id: str
    session_id: str
    villager_model: str
    werewolf_model: str
    seed: int | None
    max_rounds: int
    status: RunStatus = "queued"
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    events: list[LiveEvent] = field(default_factory=list)
    subscribers: list[queue.Queue[LiveEvent]] = field(default_factory=list)
    next_event_id: int = 1

    @property
    def event_count(self) -> int:
        return len(self.events)

    def to_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "event_count": self.event_count,
        }


class LiveRunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, LiveGameRun] = {}
        self._lock = threading.RLock()

    def create_run(
        self,
        *,
        session_id: str,
        villager_model: str,
        werewolf_model: str,
        seed: int | None,
        max_rounds: int,
    ) -> LiveGameRun:
        with self._lock:
            run = LiveGameRun(
                run_id=f"run_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                villager_model=villager_model,
                werewolf_model=werewolf_model,
                seed=seed,
                max_rounds=max_rounds,
            )
            self._runs[run.run_id] = run
            self.publish(run.run_id, "run_created")
            return run

    def get_run(self, run_id: str) -> LiveGameRun:
        with self._lock:
            return self._runs[run_id]

    def try_get_run(self, run_id: str) -> LiveGameRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def mark_running(self, run_id: str) -> None:
        with self._lock:
            run = self._runs[run_id]
            run.status = "running"
            run.started_at = utc_now()
        self.publish(run_id, "run_started")

    def mark_completed(self, run_id: str, *, winner: str) -> None:
        with self._lock:
            run = self._runs[run_id]
            run.status = "completed"
            run.completed_at = utc_now()
        self.publish(run_id, "game_completed", payload={"winner": winner})

    def mark_failed(self, run_id: str, *, error: str) -> None:
        with self._lock:
            run = self._runs[run_id]
            run.status = "failed"
            run.error = error
            run.completed_at = utc_now()
        self.publish(run_id, "game_failed", payload={"error": error})

    def publish(
        self,
        run_id: str,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            event = LiveEvent(
                id=run.next_event_id,
                type=event_type,
                run_id=run.run_id,
                session_id=run.session_id,
                created_at=utc_now(),
                round=round_number,
                phase=phase,
                actor=actor,
                action=action,
                payload=payload or {},
            )
            run.next_event_id += 1
            run.events.append(event)
            subscribers = list(run.subscribers)

        for subscriber in subscribers:
            subscriber.put(event)
        return event

    def events_after(self, run_id: str, *, after_id: int | None) -> list[LiveEvent]:
        with self._lock:
            events = list(self._runs[run_id].events)
        if after_id is None:
            return events
        return [event for event in events if event.id > after_id]

    def subscribe(self, run_id: str) -> queue.Queue[LiveEvent]:
        subscriber: queue.Queue[LiveEvent] = queue.Queue()
        with self._lock:
            self._runs[run_id].subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, run_id: str, subscriber: queue.Queue[LiveEvent]) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run and subscriber in run.subscribers:
                run.subscribers.remove(subscriber)


class EventSink:
    def __init__(self, registry: LiveRunRegistry, run_id: str) -> None:
        self.registry = registry
        self.run_id = run_id

    def publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.registry.publish(
            self.run_id,
            event_type,
            round_number=round_number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
        )


class NullEventSink:
    def publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        return None


def format_sse(event: LiveEvent) -> str:
    payload = json.dumps(event.to_dict(), ensure_ascii=False)
    return f"id: {event.id}\nevent: {event.type}\ndata: {payload}\n\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_live.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/werewolf/live.py apps/api/tests/test_live.py
git commit -m "feat: add live run registry"
```

---

### Task 2: Runner Session Injection and Engine Event Sink

**Files:**
- Modify: `apps/api/app/werewolf/runner.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing runner tests**

Add these tests to `apps/api/tests/test_werewolf_runner.py`:

```python
from app.werewolf.live import NullEventSink


def test_run_game_accepts_custom_session_id(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=21,
        max_rounds=1,
        provider=ScriptedChineseProvider(),
        session_id="session_20260424_120000_ab12cd34",
        event_sink=NullEventSink(),
    )

    assert result.session_id == "session_20260424_120000_ab12cd34"
    assert result.log_directory == tmp_path / "session_20260424_120000_ab12cd34"
```

Add a small capturing sink in the same file:

```python
class CapturingEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append({"type": event_type, **kwargs})


def test_run_game_publishes_live_events(tmp_path) -> None:
    sink = CapturingEventSink()

    run_game(
        logs_dir=tmp_path,
        seed=21,
        max_rounds=1,
        provider=ScriptedChineseProvider(),
        session_id="session_20260424_120000_ab12cd34",
        event_sink=sink,
    )

    event_types = [event["type"] for event in sink.events]
    assert "game_started" in event_types
    assert "round_started" in event_types
    assert "action_requested" in event_types
    assert "model_request_started" in event_types
    assert "model_response_received" in event_types
    assert "action_parsed" in event_types
    assert "state_updated" in event_types
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py -q
```

Expected: FAIL because `run_game()` does not accept `session_id` or `event_sink`.

- [ ] **Step 3: Add runner arguments**

Modify `run_game()` in `apps/api/app/werewolf/runner.py`:

```python
from app.werewolf.live import NullEventSink
from app.werewolf.runner import new_session_id
```

Update the signature:

```python
def run_game(
    *,
    villager_model: str = "deepseek-chat",
    werewolf_model: str = "deepseek-chat",
    seed: int | None = None,
    logs_dir: str | Path = "logs",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    provider: ModelProvider | None = None,
    session_id: str | None = None,
    event_sink: object | None = None,
) -> RunGameResult:
```

Replace session creation and engine construction:

```python
    session_id = session_id or new_session_id()
    log_directory = Path(logs_dir) / session_id
```

Expose a public session id helper while keeping the private helper compatible:

```python
def _new_session_id() -> str:
    return new_session_id()


def new_session_id() -> str:
    timestamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%d_%H%M%S")
    return f"session_{timestamp}_{uuid.uuid4().hex[:8]}"
```

```python
        engine = GameEngine(
            state=state,
            provider=provider or DeepSeekProvider(),
            max_rounds=max_rounds,
            event_sink=event_sink or NullEventSink(),
        )
```

- [ ] **Step 4: Publish engine events**

Modify `apps/api/app/werewolf/engine.py`.

Add import:

```python
from app.werewolf.live import NullEventSink
```

Update `GameEngine.__init__`:

```python
    def __init__(
        self,
        *,
        state: GameState,
        provider: ModelProvider,
        max_rounds: int,
        debate_turns: int = DEFAULT_DEBATE_TURNS,
        event_sink: object | None = None,
    ) -> None:
        self.state = state
        self.provider = provider
        self.max_rounds = max_rounds
        self.debate_turns = debate_turns
        self.event_sink = event_sink or NullEventSink()
```

At the start of `run()` after `active_players`:

```python
        self.event_sink.publish(
            "game_started",
            payload={
                "players": [player.to_dict() for player in self.state.players],
            },
        )
```

After `round_log = RoundLog(number=round_number)`:

```python
            self.event_sink.publish(
                "round_started",
                round_number=round_number,
                payload={"players": active_players.copy()},
            )
```

At the start of `_run_night_phase()`:

```python
        self.event_sink.publish(
            "phase_started",
            round_number=round_state.number,
            phase="night",
        )
```

At the start of `_run_day_phase()`:

```python
        self.event_sink.publish(
            "phase_started",
            round_number=round_state.number,
            phase="day",
        )
```

Before `_run_voting()` loop body:

```python
        self.event_sink.publish(
            "phase_started",
            round_number=round_state.number,
            phase="vote",
        )
```

Before `_run_summaries()` loop body:

```python
        self.event_sink.publish(
            "phase_started",
            round_number=round_state.number,
            phase="summary",
        )
```

In `_player_action()`, before `generate_action()`:

```python
        world_state = self._world_state(player, options, round_state)
        self.event_sink.publish(
            "action_requested",
            round_number=round_state.number,
            actor=player.name,
            action=action,
            payload={"options": options},
        )
        self.event_sink.publish(
            "model_request_started",
            round_number=round_state.number,
            actor=player.name,
            action=action,
            payload={"model": player.model, "world_state": world_state},
        )
        value, lm_log = generate_action(
            provider=self.provider,
            action=action,
            world_state=world_state,
            model=player.model,
            allowed_values=options if options else None,
            result_key=result_key,
        )
```

Then publish response and parsed events after `action_log` is built:

```python
        self.event_sink.publish(
            "model_response_received",
            round_number=round_state.number,
            actor=player.name,
            action=action,
            payload={
                "prompt": lm_log.prompt,
                "raw_response": lm_log.raw_response,
            },
        )
        self.event_sink.publish(
            "action_parsed",
            round_number=round_state.number,
            actor=player.name,
            action=action,
            payload={
                "choice": action_log.choice,
                "result": lm_log.result,
                "options": options,
            },
        )
```

After public state changes, publish `state_updated`:

```python
            self.event_sink.publish(
                "state_updated",
                round_number=round_state.number,
                phase="night",
                payload={"eliminated": round_state.eliminated, "active_players": active_players.copy()},
            )
```

```python
            self.event_sink.publish(
                "state_updated",
                round_number=round_state.number,
                phase="day",
                payload={"exiled": round_state.exiled, "active_players": active_players.copy()},
            )
```

After appending debate entry:

```python
            self.event_sink.publish(
                "state_updated",
                round_number=round_state.number,
                phase="day",
                actor=speaker,
                action="debate",
                payload={"debate": entry.to_dict()},
            )
```

After votes are appended:

```python
        self.event_sink.publish(
            "state_updated",
            round_number=round_state.number,
            phase="vote",
            payload={"votes": votes},
        )
```

After each summary:

```python
                self.event_sink.publish(
                    "state_updated",
                    round_number=round_state.number,
                    phase="summary",
                    actor=name,
                    action="summarize",
                    payload={"summary": summary},
                )
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py tests/test_live.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/runner.py apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: publish live engine events"
```

---

### Task 3: Backend Run API and SSE Endpoint

**Files:**
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Write failing API tests**

Add imports:

```python
import pytest

from app.api.routes.games import get_live_registry
from app.werewolf.live import LiveRunRegistry
```

Add helper:

```python
def override_live_registry(registry: LiveRunRegistry) -> None:
    app.dependency_overrides[get_live_registry] = lambda: registry
```

Add tests:

```python
def test_create_game_run_returns_run_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    started: list[str] = []

    def fake_background_run(**kwargs: object) -> None:
        started.append(str(kwargs["run_id"]))

    monkeypatch.setattr(
        "app.api.routes.games._run_game_in_background",
        fake_background_run,
    )

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["run_id"].startswith("run_")
    assert payload["session_id"].startswith("session_")
    assert payload["status"] in {"queued", "running", "completed", "failed"}
    assert payload["event_count"] >= 1
    assert started == [payload["run_id"]]


def test_get_game_run_returns_404_for_missing_run() -> None:
    registry = LiveRunRegistry()
    override_live_registry(registry)

    try:
        response = client.get("/api/v1/games/runs/run_missing")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game run not found"


def test_game_run_events_replays_existing_events() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )
    registry.publish(run.run_id, "game_started", payload={"players": []})
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/runs/{run.run_id}/events")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: run_created" in body
    assert "event: game_started" in body
    assert "event: game_completed" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py -q
```

Expected: FAIL because live route functions do not exist.

- [ ] **Step 3: Implement route models and dependencies**

Modify `apps/api/app/api/routes/games.py` imports:

```python
import queue
import threading
from collections.abc import Iterator
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from app.werewolf.live import EventSink, LiveRunRegistry, format_sse
from app.werewolf.runner import GameRunError, new_session_id, run_game
```

Add module registry:

```python
live_registry = LiveRunRegistry()
```

Add request model:

```python
class CreateGameRunRequest(BaseModel):
    villager_model: str = "deepseek-chat"
    werewolf_model: str = "deepseek-chat"
    seed: int | None = None
    max_rounds: int = Field(default=8, ge=1, le=20)
```

Add dependency:

```python
def get_live_registry() -> LiveRunRegistry:
    return live_registry
```

- [ ] **Step 4: Implement run creation and status endpoints**

Add below existing detail endpoint:

```python
@router.post("/runs", status_code=201)
def create_game_run(
    request: CreateGameRunRequest,
    store: Annotated[ReplayStore, Depends(get_replay_store)],
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
) -> dict:
    session_id = new_session_id()
    run = registry.create_run(
        session_id=session_id,
        villager_model=request.villager_model,
        werewolf_model=request.werewolf_model,
        seed=request.seed,
        max_rounds=request.max_rounds,
    )
    thread = threading.Thread(
        target=_run_game_in_background,
        kwargs={
            "run_id": run.run_id,
            "session_id": session_id,
            "request": request,
            "logs_dir": store.logs_root,
            "registry": registry,
        },
        daemon=True,
    )
    thread.start()
    return run.to_summary()
```

Add status endpoint:

```python
@router.get("/runs/{run_id}")
def get_game_run(
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
) -> dict:
    run = registry.try_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Game run not found")
    return run.to_summary()
```

Add background runner:

```python
def _run_game_in_background(
    *,
    run_id: str,
    session_id: str,
    request: CreateGameRunRequest,
    logs_dir: FilePath,
    registry: LiveRunRegistry,
) -> None:
    registry.mark_running(run_id)
    try:
        result = run_game(
            villager_model=request.villager_model,
            werewolf_model=request.werewolf_model,
            seed=request.seed,
            logs_dir=logs_dir,
            max_rounds=request.max_rounds,
            session_id=session_id,
            event_sink=EventSink(registry, run_id),
        )
    except GameRunError as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    registry.mark_completed(run_id, winner=result.winner)
```

- [ ] **Step 5: Implement SSE endpoint**

Add:

```python
@router.get("/runs/{run_id}/events")
def stream_game_run_events(
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
) -> StreamingResponse:
    run = registry.try_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Game run not found")

    return StreamingResponse(
        _event_stream(registry, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
```

Add generator:

```python
def _event_stream(registry: LiveRunRegistry, run_id: str) -> Iterator[str]:
    for event in registry.events_after(run_id, after_id=None):
        yield format_sse(event)
        if event.type in {"game_completed", "game_failed"}:
            return

    subscriber = registry.subscribe(run_id)
    try:
        while True:
            try:
                event = subscriber.get(timeout=15)
            except queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
                continue

            yield format_sse(event)
            if event.type in {"game_completed", "game_failed"}:
                return
    finally:
        registry.unsubscribe(run_id, subscriber)
```

- [ ] **Step 6: Run tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py tests/test_live.py tests/test_werewolf_runner.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/api/routes/games.py apps/api/tests/test_games_api.py
git commit -m "feat: add live game run api"
```

---

### Task 4: Frontend Live Types and API Clients

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Create: `apps/web/src/features/games/api/createGameRun.ts`
- Create: `apps/web/src/features/games/api/getGameRun.ts`
- Test: `apps/web/src/features/games/api/liveRunApi.test.ts`

- [ ] **Step 1: Write failing API client tests**

Create `apps/web/src/features/games/api/liveRunApi.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun } from "./createGameRun";
import { getGameRun } from "./getGameRun";

describe("live run api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a game run", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1234abcd",
          session_id: "session_20260424_120000_ab12cd34",
          status: "queued",
          created_at: "2026-04-24T12:00:00Z",
          started_at: null,
          completed_at: null,
          error: null,
          event_count: 1,
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );

    const run = await createGameRun({ seed: 21, max_rounds: 8 });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed: 21, max_rounds: 8 }),
      }),
    );
    expect(run.run_id).toBe("run_1234abcd");
  });

  it("gets a game run", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1234abcd",
          session_id: "session_20260424_120000_ab12cd34",
          status: "running",
          created_at: "2026-04-24T12:00:00Z",
          started_at: "2026-04-24T12:00:01Z",
          completed_at: null,
          error: null,
          event_count: 4,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const run = await getGameRun("run_1234abcd");

    expect(run.status).toBe("running");
    expect(run.event_count).toBe(4);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/api/liveRunApi.test.ts
```

Expected: FAIL because API files do not exist.

- [ ] **Step 3: Add live types**

Append to `apps/web/src/features/games/types.ts`:

```ts
export type GameRunStatus = "queued" | "running" | "completed" | "failed";

export type GameRun = {
  run_id: string;
  session_id: string;
  status: GameRunStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  event_count: number;
};

export type CreateGameRunRequest = {
  villager_model?: string;
  werewolf_model?: string;
  seed?: number | null;
  max_rounds?: number;
};

export type LiveGameEvent = {
  id: number;
  type: string;
  run_id: string;
  session_id: string;
  created_at: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  payload: Record<string, unknown>;
};
```

- [ ] **Step 4: Add API clients**

Create `apps/web/src/features/games/api/createGameRun.ts`:

```ts
import { apiFetch } from "../../../api/client";
import type { CreateGameRunRequest, GameRun } from "../types";

export function createGameRun(request: CreateGameRunRequest): Promise<GameRun> {
  return apiFetch<GameRun>("/api/v1/games/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
```

Create `apps/web/src/features/games/api/getGameRun.ts`:

```ts
import { apiFetch } from "../../../api/client";
import type { GameRun } from "../types";

export function getGameRun(runId: string): Promise<GameRun> {
  return apiFetch<GameRun>(`/api/v1/games/runs/${runId}`);
}
```

- [ ] **Step 5: Run test**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/api/liveRunApi.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/api/createGameRun.ts apps/web/src/features/games/api/getGameRun.ts apps/web/src/features/games/api/liveRunApi.test.ts
git commit -m "feat: add live run api clients"
```

---

### Task 5: Frontend EventSource Hook

**Files:**
- Create: `apps/web/src/features/games/hooks/useGameRunEvents.ts`
- Test: `apps/web/src/features/games/hooks/useGameRunEvents.test.tsx`

- [ ] **Step 1: Write failing hook test**

Create `apps/web/src/features/games/hooks/useGameRunEvents.test.tsx`:

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useGameRunEvents } from "./useGameRunEvents";

class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  listeners = new Map<string, (event: MessageEvent) => void>();
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(type, listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, payload: object) {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    this.listeners.get(type)?.(event);
    this.onmessage?.(event);
  }
}

describe("useGameRunEvents", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    MockEventSource.instances = [];
  });

  it("subscribes to run events and dedupes by id", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    source.onopen?.();
    source.emit("game_started", {
      id: 1,
      type: "game_started",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:00Z",
      round: null,
      phase: null,
      actor: null,
      action: null,
      payload: { players: [] },
    });
    source.emit("game_started", {
      id: 1,
      type: "game_started",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:00Z",
      round: null,
      phase: null,
      actor: null,
      action: null,
      payload: { players: [] },
    });

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(result.current.connectionState).toBe("open");
    expect(source.url).toBe("/api/v1/games/runs/run_1234abcd/events");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/hooks/useGameRunEvents.test.tsx
```

Expected: FAIL because hook does not exist.

- [ ] **Step 3: Implement hook**

Create `apps/web/src/features/games/hooks/useGameRunEvents.ts`:

```ts
import { useEffect, useMemo, useState } from "react";

import type { LiveGameEvent } from "../types";

type ConnectionState = "idle" | "connecting" | "open" | "error" | "closed";

const EVENT_TYPES = [
  "run_created",
  "run_started",
  "game_started",
  "round_started",
  "phase_started",
  "action_requested",
  "model_request_started",
  "model_response_received",
  "action_parsed",
  "state_updated",
  "game_completed",
  "game_failed",
];

export function useGameRunEvents(runId: string | undefined) {
  const [events, setEvents] = useState<LiveGameEvent[]>([]);
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("idle");

  useEffect(() => {
    if (!runId) {
      setEvents([]);
      setConnectionState("idle");
      return;
    }

    setConnectionState("connecting");
    const source = new EventSource(`/api/v1/games/runs/${runId}/events`);

    source.onopen = () => setConnectionState("open");
    source.onerror = () => setConnectionState("error");

    const handleEvent = (message: MessageEvent) => {
      const event = JSON.parse(message.data) as LiveGameEvent;
      setEvents((current) => {
        if (current.some((item) => item.id === event.id)) {
          return current;
        }
        return [...current, event].sort((a, b) => a.id - b.id);
      });
      if (event.type === "game_completed" || event.type === "game_failed") {
        setConnectionState("closed");
        source.close();
      }
    };

    for (const eventType of EVENT_TYPES) {
      source.addEventListener(eventType, handleEvent);
    }

    return () => {
      source.close();
      setConnectionState("closed");
    };
  }, [runId]);

  const latestEvent = useMemo(() => events.at(-1) ?? null, [events]);

  return { events, latestEvent, connectionState };
}
```

- [ ] **Step 4: Run test**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/hooks/useGameRunEvents.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/games/hooks/useGameRunEvents.ts apps/web/src/features/games/hooks/useGameRunEvents.test.tsx
git commit -m "feat: stream live game events"
```

---

### Task 6: Frontend Launch Form and Games Page Integration

**Files:**
- Create: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Modify: `apps/web/src/pages/GamesPage.tsx`
- Test: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Write failing GamesPage test**

Add to `apps/web/src/pages/GamesPage.test.tsx` imports:

```ts
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
```

Add test:

```tsx
it("creates a live game run and navigates to the live page", async () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/v1/games/runs")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            run_id: "run_1234abcd",
            session_id: "session_20260424_120000_ab12cd34",
            status: "queued",
            created_at: "2026-04-24T12:00:00Z",
            started_at: null,
            completed_at: null,
            error: null,
            event_count: 1,
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  renderWithClient(
    <Routes>
      <Route path="/games" element={<GamesPage />} />
      <Route path="/games/live/:runId" element={<p>实时观战 run_1234abcd</p>} />
    </Routes>,
    "/games",
  );

  await userEvent.click(await screen.findByRole("button", { name: "发起对局" }));

  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/v1/games/runs",
    expect.objectContaining({ method: "POST" }),
  );
  expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL because launch form does not exist.

- [ ] **Step 3: Implement CreateGameRunForm**

Create `apps/web/src/features/games/components/CreateGameRunForm.tsx`:

```tsx
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { createGameRun } from "../api/createGameRun";

export function CreateGameRunForm() {
  const navigate = useNavigate();
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState("8");

  const mutation = useMutation({
    mutationFn: createGameRun,
    onSuccess: (run) => navigate(`/games/live/${run.run_id}`),
  });

  return (
    <form
      className="rounded-md border border-slate-200 bg-white p-4"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate({
          seed: seed ? Number(seed) : null,
          max_rounds: Number(maxRounds),
        });
      }}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
          随机种子
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            inputMode="numeric"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            placeholder="可留空"
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
          最大轮数
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            min={1}
            max={20}
            type="number"
            value={maxRounds}
            onChange={(event) => setMaxRounds(event.target.value)}
          />
        </label>
        <button
          className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
          disabled={mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? "正在发起..." : "发起对局"}
        </button>
      </div>
      {mutation.isError ? (
        <p className="mt-3 text-sm text-red-700">无法发起对局</p>
      ) : null}
    </form>
  );
}
```

- [ ] **Step 4: Integrate form into GamesPage**

Modify `apps/web/src/pages/GamesPage.tsx` imports:

```tsx
import { CreateGameRunForm } from "../features/games/components/CreateGameRunForm";
```

Render below heading:

```tsx
      <div className="mt-6">
        <CreateGameRunForm />
      </div>
```

Keep session list in a later block:

```tsx
      <div className="mt-6">
        {isPending ? (
```

- [ ] **Step 5: Run test**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/pages/GamesPage.tsx apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat: launch live games from list"
```

---

### Task 7: Live Game Page

**Files:**
- Create: `apps/web/src/features/games/components/LiveStatusStrip.tsx`
- Create: `apps/web/src/features/games/components/LiveEventTimeline.tsx`
- Create: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/routes/definitions.tsx`
- Test: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Write failing live page test**

Create `apps/web/src/pages/LiveGamePage.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../tests/renderWithClient";
import { LiveGamePage } from "./LiveGamePage";

class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, (event: MessageEvent) => void>();

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(type, listener);
  }

  close() {}

  emit(type: string, payload: object) {
    this.listeners.get(type)?.(
      new MessageEvent(type, { data: JSON.stringify(payload) }),
    );
  }
}

describe("LiveGamePage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    MockEventSource.instances = [];
  });

  it("renders live events and completed replay link", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1234abcd",
          session_id: "session_20260424_120000_ab12cd34",
          status: "running",
          created_at: "2026-04-24T12:00:00Z",
          started_at: "2026-04-24T12:00:01Z",
          completed_at: null,
          error: null,
          event_count: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderWithClient(
      <Routes>
        <Route path="/games/live/:runId" element={<LiveGamePage />} />
      </Routes>,
      "/games/live/run_1234abcd",
    );

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    const source = MockEventSource.instances[0];
    source.onopen?.();
    source.emit("action_requested", {
      id: 1,
      type: "action_requested",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:03Z",
      round: 1,
      phase: "day",
      actor: "张三",
      action: "debate",
      payload: { options: [] },
    });
    source.emit("model_response_received", {
      id: 2,
      type: "model_response_received",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:04Z",
      round: 1,
      phase: "day",
      actor: "张三",
      action: "debate",
      payload: { raw_response: "{\"say\":\"我不是狼\"}" },
    });
    source.emit("game_completed", {
      id: 3,
      type: "game_completed",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:10Z",
      round: null,
      phase: null,
      actor: null,
      action: null,
      payload: { winner: "狼人阵营" },
    });

    expect(await screen.findByText("张三 正在 debate")).toBeInTheDocument();
    expect(screen.getByText('{"say":"我不是狼"}')).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看完整复盘" })).toHaveAttribute(
      "href",
      "/games/session_20260424_120000_ab12cd34",
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL because page/components do not exist.

- [ ] **Step 3: Implement status strip**

Create `apps/web/src/features/games/components/LiveStatusStrip.tsx`:

```tsx
import type { GameRun } from "../types";

export function LiveStatusStrip({
  run,
  connectionState,
}: {
  run: GameRun;
  connectionState: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-4 py-3 text-sm">
      <span className="font-medium text-slate-950">{run.status}</span>
      <span className="text-slate-600">{run.session_id}</span>
      <span className="text-slate-500">连接：{connectionState}</span>
      {run.error ? <span className="text-red-700">{run.error}</span> : null}
    </div>
  );
}
```

- [ ] **Step 4: Implement timeline**

Create `apps/web/src/features/games/components/LiveEventTimeline.tsx`:

```tsx
import type { LiveGameEvent } from "../types";

function titleForEvent(event: LiveGameEvent) {
  if (event.type === "action_requested" && event.actor && event.action) {
    return `${event.actor} 正在 ${event.action}`;
  }
  if (event.type === "model_response_received") {
    return "模型返回原文";
  }
  if (event.type === "action_parsed") {
    return "行动解析完成";
  }
  if (event.type === "game_completed") {
    return "对局完成";
  }
  if (event.type === "game_failed") {
    return "对局失败";
  }
  return event.type;
}

function detailForEvent(event: LiveGameEvent) {
  const raw = event.payload.raw_response;
  if (typeof raw === "string") {
    return raw;
  }
  const choice = event.payload.choice;
  if (typeof choice === "string") {
    return choice;
  }
  const winner = event.payload.winner;
  if (typeof winner === "string") {
    return winner;
  }
  return "";
}

export function LiveEventTimeline({ events }: { events: LiveGameEvent[] }) {
  if (events.length === 0) {
    return <p className="p-4 text-sm text-slate-600">等待实时事件...</p>;
  }

  return (
    <ol className="divide-y divide-slate-200">
      {events.map((event) => (
        <li className="px-4 py-3" key={event.id}>
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-slate-950">
              {titleForEvent(event)}
            </p>
            <p className="text-xs text-slate-500">
              {event.round ? `第 ${event.round} 轮` : event.type}
            </p>
          </div>
          {detailForEvent(event) ? (
            <pre className="mt-2 overflow-auto rounded-md bg-slate-100 p-2 text-xs text-slate-700">
              {detailForEvent(event)}
            </pre>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
```

- [ ] **Step 5: Implement live page and route**

Create `apps/web/src/pages/LiveGamePage.tsx`:

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getGameRun } from "../features/games/api/getGameRun";
import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";

export function LiveGamePage() {
  const { runId } = useParams();
  const queryClient = useQueryClient();
  const { events, connectionState } = useGameRunEvents(runId);
  const { data: run, isError, isPending } = useQuery({
    queryKey: ["game-run", runId],
    queryFn: () => getGameRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 15000;
    },
  });

  const terminalEvent = events.find(
    (event) => event.type === "game_completed" || event.type === "game_failed",
  );

  if (terminalEvent) {
    queryClient.invalidateQueries({ queryKey: ["games"] });
  }

  if (isPending) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <p className="text-sm text-slate-600">正在读取实时对局...</p>
      </main>
    );
  }

  if (isError || !run) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <p className="text-sm text-red-700">无法读取实时对局</p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <div className="mb-4 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-950">实时观战</h1>
        {terminalEvent ? (
          <Link
            className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white"
            to={`/games/${run.session_id}`}
          >
            查看完整复盘
          </Link>
        ) : null}
      </div>
      <section className="overflow-hidden rounded-md border border-slate-200 bg-white">
        <LiveStatusStrip run={run} connectionState={connectionState} />
        <LiveEventTimeline events={events} />
      </section>
    </main>
  );
}
```

Modify `apps/web/src/routes/definitions.tsx`:

```tsx
import { LiveGamePage } from "../pages/LiveGamePage";
```

Add before `"/games/:sessionId"`:

```tsx
  {
    path: "/games/live/:runId",
    element: <LiveGamePage />,
  },
```

- [ ] **Step 6: Run test**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/games/components/LiveStatusStrip.tsx apps/web/src/features/games/components/LiveEventTimeline.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/routes/definitions.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat: add live spectator page"
```

---

### Task 8: Full Verification and Polish

**Files:**
- Modify only files needed to resolve failures found by verification.

- [ ] **Step 1: Run backend tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest
```

Expected: PASS.

- [ ] **Step 2: Run frontend tests**

Run:

```bash
cd apps/web && pnpm test -- --run
```

Expected: PASS.

- [ ] **Step 3: Build frontend**

Run:

```bash
cd apps/web && pnpm build
```

Expected: PASS and Vite emits a production build.

- [ ] **Step 4: Smoke test local flow**

Start API:

```bash
cd apps/api && .venv/bin/python -m app.cli serve --host 127.0.0.1 --port 8000
```

Start web:

```bash
cd apps/web && pnpm dev --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173/games
```

Expected:

- The games page shows the launch form.
- Clicking `发起对局` navigates to `/games/live/<run_id>`.
- Live events appear as the game runs.
- When complete, `查看完整复盘` links to `/games/<session_id>`.

- [ ] **Step 5: Commit final fixes if needed**

If verification required fixes:

```bash
git add <changed-files>
git commit -m "fix: polish live spectator flow"
```

If no fixes were needed, do not create an empty commit.
