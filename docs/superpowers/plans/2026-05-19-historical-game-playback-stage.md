# Historical Game Playback Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a historical-game playback stage that turns saved `state + logs` into playback events and reuses the existing live stage, while keeping partial/failed game resume behavior unchanged.

**Architecture:** The backend owns historical log interpretation by adding a `replay_playback.py` builder and a read-only `GET /api/v1/games/{session_id}/playback` endpoint. The frontend adds a playback API/page, extracts source-agnostic live-stage UI from `LiveGamePage`, and wires history/detail navigation into `/games/playback/:sessionId`.

**Tech Stack:** FastAPI, pytest, React, React Router, TanStack Query, Vitest, Testing Library, TypeScript.

---

## File Structure

Backend:

- Create `apps/api/app/werewolf/replay_playback.py`: Converts replay `state + logs` dictionaries into `LiveEvent`-shaped dictionaries without creating a live registry run.
- Modify `apps/api/app/api/routes/games.py`: Adds the playback endpoint and delegates event generation to `replay_playback.py`.
- Modify `apps/api/tests/test_games_api.py`: Adds endpoint coverage for complete, partial, missing, and corrupt sessions.

Frontend:

- Modify `apps/web/src/features/games/types.ts`: Adds `GamePlayback`, `LiveStageRun`, and the playback status surface needed by shared stage UI.
- Create `apps/web/src/features/games/api/getGamePlayback.ts`: Fetches `/api/v1/games/{sessionId}/playback`.
- Create `apps/web/src/features/games/components/LiveStageExperience.tsx`: Owns the source-agnostic stage layout currently embedded in `LiveGamePage`; callers keep the director controller so top-nav controls and stage playback stay synchronized.
- Modify `apps/web/src/pages/LiveGamePage.tsx`: Keeps live data fetching and passes live state into `LiveStageExperience`.
- Create `apps/web/src/pages/GamePlaybackPage.tsx`: Fetches playback events, exposes resume for resumable partial/failed sessions, and renders `LiveStageExperience`.
- Modify `apps/web/src/routes/definitions.tsx`: Adds `/games/playback/:sessionId` before `/games/:sessionId`.
- Modify `apps/web/src/features/games/components/SessionList.tsx`: Adds a playback link next to the existing replay and resume controls.
- Modify `apps/web/src/pages/GameDetailPage.tsx`: Adds a top-nav playback action for the current session.
- Modify tests in `apps/web/src/pages/*.test.tsx` and `apps/web/src/tests/app.test.tsx`: Covers the new route, playback page, playback links, and unchanged resume behavior.

---

### Task 1: Backend Playback Builder Tests

**Files:**
- Create: `apps/api/app/werewolf/replay_playback.py`
- Modify: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Add focused playback endpoint tests**

Append these tests near the existing game detail tests in `apps/api/tests/test_games_api.py`:

```python
def test_get_game_playback_returns_complete_playback_events(tmp_path: Path) -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="好人阵营")
    state["rule_set"] = {"id": "starter_6", "name": "新手 6 人快局", "player_count": 6, "roles": []}
    state["rounds"][0]["debate"] = [{"speaker": "张三", "message": "我认为李四身份偏低。"}]
    state["rounds"][0]["votes"] = [{"张三": "李四"}]
    write_json(tmp_path / session_id / "game_complete.json", state)
    write_json(tmp_path / session_id / "game_logs.json", sample_logs())
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "complete"
    assert payload["resumable"] is False
    assert payload["rule_set"]["id"] == "starter_6"
    event_types = [event["type"] for event in payload["events"]]
    assert event_types[:3] == ["run_created", "run_started", "game_started"]
    assert "round_started" in event_types
    assert "action_requested" in event_types
    assert "action_parsed" in event_types
    assert event_types[-1] == "game_completed"
    assert payload["events"][-1]["payload"] == {"winner": "好人阵营"}
    assert [event["id"] for event in payload["events"]] == list(range(1, len(payload["events"]) + 1))
    assert all(event["run_id"] == f"playback_{session_id}" for event in payload["events"])
```

Append this partial/resume test after it:

```python
def test_get_game_playback_returns_partial_end_without_resuming(tmp_path: Path) -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="", error="Maximum rounds exceeded")
    write_json(tmp_path / session_id / "game_partial.json", state)
    write_json(tmp_path / session_id / "game_logs.json", sample_logs())
    write_json(
        tmp_path / session_id / RESUME_CHECKPOINT_FILE,
        {
            "state_at_round_start": state,
            "logs_before_round": sample_logs(),
            "run_params": {
                "villager_model": "deepseek-chat",
                "werewolf_model": "deepseek-chat",
                "seed": 7,
                "max_rounds": 8,
                "rule_set_id": "classic_8",
                "player_configs": [],
            },
        },
    )
    override_logs_root(tmp_path)
    registry = LiveRunRegistry()
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["resumable"] is True
    assert payload["events"][-1]["type"] == "game_failed"
    assert payload["events"][-1]["payload"]["playback_partial"] is True
    assert payload["events"][-1]["payload"]["error"] == "Maximum rounds exceeded"
    assert registry._runs == {}
```

Append this missing-session test:

```python
def test_get_game_playback_returns_404_for_missing_session(tmp_path: Path) -> None:
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games/game_1200abcd/playback")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json() == {"detail": "Game session not found"}
```

- [ ] **Step 2: Run the backend tests and verify they fail**

Run:

```bash
pytest apps/api/tests/test_games_api.py -k "game_playback" -q
```

Expected: all three new tests fail with `404 Not Found` because the playback endpoint does not exist.

- [ ] **Step 3: Commit the failing tests**

```bash
git add apps/api/tests/test_games_api.py
git commit -m "test: cover historical game playback api"
```

---

### Task 2: Backend Playback Builder and API

**Files:**
- Create: `apps/api/app/werewolf/replay_playback.py`
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Implement the playback builder**

Create `apps/api/app/werewolf/replay_playback.py` with this structure:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


BASE_FALLBACK_CREATED_AT = "1970-01-01T00:00:00Z"


def build_replay_playback(session: dict[str, Any]) -> dict[str, Any]:
    session_id = str(session["session_id"])
    status = str(session["status"])
    state = _record(session.get("state"))
    logs = [item for item in session.get("logs", []) if isinstance(item, dict)]
    resumable = bool(session.get("resumable"))
    builder = PlaybackEventBuilder(
        session_id=session_id,
        base_created_at=_session_created_at(state),
    )

    builder.publish(
        "run_created",
        payload={
            "playback": True,
            "session_id": session_id,
            "status": status,
            "rule_set": state.get("rule_set"),
            "resumable": resumable,
        },
    )
    builder.publish("run_started", payload={"playback": True})
    builder.publish(
        "game_started",
        payload={
            "players": _list(state.get("players")),
            "rule_set": state.get("rule_set"),
            "playback": True,
        },
    )

    logs_by_round = {int(log["number"]): log for log in logs if isinstance(log.get("number"), int)}
    for round_state in _list(state.get("rounds")):
        if not isinstance(round_state, dict) or not isinstance(round_state.get("number"), int):
            continue
        round_number = int(round_state["number"])
        round_log = logs_by_round.get(round_number, {})
        _publish_round(builder, round_number, round_state, round_log)

    winner = state.get("winner")
    if status == "complete" and isinstance(winner, str) and winner:
        builder.publish("game_completed", payload={"winner": winner})
    else:
        error = state.get("error_message")
        builder.publish(
            "game_failed",
            payload={
                "error": error if isinstance(error, str) and error else "历史对局未完成",
                "playback_partial": True,
            },
        )

    return {
        "session_id": session_id,
        "status": status,
        "rule_set": state.get("rule_set"),
        "resumable": resumable,
        "events": builder.events,
    }
```

Add the builder class below it:

```python
class PlaybackEventBuilder:
    def __init__(self, *, session_id: str, base_created_at: str) -> None:
        self.session_id = session_id
        self.run_id = f"playback_{session_id}"
        self.base_created_at = _parse_created_at(base_created_at)
        self.events: list[dict[str, Any]] = []

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
        event_id = len(self.events) + 1
        self.events.append(
            {
                "id": event_id,
                "type": event_type,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "created_at": _format_created_at(self.base_created_at + timedelta(seconds=event_id - 1)),
                "round": round_number,
                "phase": phase,
                "actor": actor,
                "action": action,
                "payload": _jsonish(payload or {}),
            }
        )
```

Add round/action helpers:

```python
NIGHT_ACTION_FIELDS = [
    "eliminate",
    "protect",
    "investigate",
    "witch_save",
    "witch_poison",
    "hunter_shoot",
]

DAY_ACTION_FIELDS = [
    "sheriff_run",
    "sheriff_speech",
    "sheriff_withdraw",
    "sheriff_votes",
    "sheriff_pk_speech",
    "sheriff_runoff_votes",
    "werewolf_self_explosion",
    "speech_order",
    "sheriff_badge",
    "debate",
    "votes",
    "summaries",
]


def _publish_round(
    builder: PlaybackEventBuilder,
    round_number: int,
    round_state: dict[str, Any],
    round_log: dict[str, Any],
) -> None:
    builder.publish("round_started", round_number=round_number)
    builder.publish("phase_started", round_number=round_number, phase="night", payload={"active_players": round_state.get("players", [])})
    for field in NIGHT_ACTION_FIELDS:
        for action_log in _action_items(round_log.get(field)):
            _publish_action(builder, round_number, "night", action_log)
    builder.publish("state_updated", round_number=round_number, phase="night", payload=_night_payload(round_state))

    builder.publish("phase_started", round_number=round_number, phase="day", payload={"active_players": round_state.get("players", [])})
    for field in DAY_ACTION_FIELDS:
        for action_log in _action_items(round_log.get(field)):
            _publish_action(builder, round_number, "day", action_log)
    builder.publish("state_updated", round_number=round_number, phase="day", payload=_day_payload(round_state))


def _publish_action(
    builder: PlaybackEventBuilder,
    round_number: int,
    phase: str,
    action_log: dict[str, Any],
) -> None:
    actor = _string_or_none(action_log.get("actor"))
    action = _string_or_none(action_log.get("action"))
    options = _list(action_log.get("options"))
    choice = action_log.get("choice")
    result = _lm_result(action_log)
    visible_result = _visible_result(result, choice)
    builder.publish(
        "action_requested",
        round_number=round_number,
        phase=phase,
        actor=actor,
        action=action,
        payload={"options": options},
    )
    builder.publish(
        "model_response_received",
        round_number=round_number,
        phase=phase,
        actor=actor,
        action=action,
        payload={"visible_text": _visible_text(visible_result), "result": result},
    )
    builder.publish(
        "action_parsed",
        round_number=round_number,
        phase=phase,
        actor=actor,
        action=action,
        payload={"choice": choice, "result": result, "visible_result": visible_result},
    )
```

Add payload helpers:

```python
def _night_payload(round_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_players": round_state.get("players", []),
        "attacked": round_state.get("attacked"),
        "eliminated": round_state.get("eliminated"),
        "protected": round_state.get("protected"),
        "investigated": round_state.get("investigated"),
        "night_deaths": round_state.get("night_deaths", []),
        "saved_by_witch": round_state.get("saved_by_witch"),
        "poisoned": round_state.get("poisoned"),
        "hunter_shot": round_state.get("hunter_shot"),
    }


def _day_payload(round_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_players": round_state.get("players", []),
        "debate_entry": _last_item(round_state.get("debate")),
        "debate": _last_item(round_state.get("debate")),
        "votes": _merge_votes(round_state.get("votes")),
        "vote_weights": round_state.get("vote_weights", {}),
        "exiled": round_state.get("exiled"),
        "day_deaths": round_state.get("day_deaths", []),
        "summaries": round_state.get("summaries", {}),
        "sheriff": round_state.get("sheriff"),
        "sheriff_candidates": round_state.get("sheriff_candidates", []),
        "sheriff_votes": round_state.get("sheriff_votes", {}),
        "sheriff_elected": round_state.get("sheriff_elected"),
        "werewolf_self_exploded": round_state.get("werewolf_self_exploded"),
    }
```

Add normalization helpers at the bottom:

```python
def _action_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                items.append(item)
            elif isinstance(item, list):
                items.extend(entry for entry in item if isinstance(entry, dict))
        return items
    return []


def _lm_result(action_log: dict[str, Any]) -> Any:
    lm_log = action_log.get("lm_log")
    if not isinstance(lm_log, dict):
        return None
    if "result" in lm_log:
        return lm_log["result"]
    return lm_log.get("parsed")


def _visible_result(result: Any, choice: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        visible = {key: result[key] for key in ("say", "summary", "reason", "choice") if key in result}
        if visible:
            return visible
    return {"choice": choice} if choice is not None else {}


def _visible_text(visible_result: dict[str, Any]) -> str:
    for key in ("say", "summary", "reason", "choice"):
        value = visible_result.get(key)
        if isinstance(value, str):
            return value
    return ""


def _merge_votes(value: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in _list(value):
        if isinstance(item, dict):
            merged.update(item)
    return merged


def _last_item(value: Any) -> Any:
    items = _list(value)
    return items[-1] if items else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _session_created_at(state: dict[str, Any]) -> str:
    value = state.get("created_at")
    return value if isinstance(value, str) and value else BASE_FALLBACK_CREATED_AT


def _parse_created_at(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)


def _format_created_at(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonish(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonish(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
```

- [ ] **Step 2: Add the API route**

Modify `apps/api/app/api/routes/games.py` imports:

```python
from app.werewolf.replay_playback import build_replay_playback
```

Add this route above `get_game` so `/playback` is not captured by `/{session_id}`:

```python
@router.get("/{session_id}/playback")
def get_game_playback(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[ReplayStore, Depends(get_replay_store)],
) -> dict:
    try:
        return build_replay_playback(store.load_session(session_id))
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game session not found") from exc
```

- [ ] **Step 3: Run backend playback tests**

Run:

```bash
pytest apps/api/tests/test_games_api.py -k "game_playback" -q
```

Expected: the three playback tests pass.

- [ ] **Step 4: Run the broader backend game API tests**

Run:

```bash
pytest apps/api/tests/test_games_api.py -q
```

Expected: all tests in `test_games_api.py` pass.

- [ ] **Step 5: Commit backend implementation**

```bash
git add apps/api/app/werewolf/replay_playback.py apps/api/app/api/routes/games.py apps/api/tests/test_games_api.py
git commit -m "feat: expose historical playback events"
```

---

### Task 3: Frontend Playback API and Route Tests

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Create: `apps/web/src/features/games/api/getGamePlayback.ts`
- Modify: `apps/web/src/routes/definitions.tsx`
- Create: `apps/web/src/pages/GamePlaybackPage.tsx`
- Modify: `apps/web/src/tests/app.test.tsx`

- [ ] **Step 1: Add route coverage before implementation**

Modify `apps/web/src/tests/app.test.tsx` to include a route test. Add this case near the existing games route tests:

```tsx
it("routes a historical playback path to the playback page", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        session_id: "game_1200abcd",
        status: "complete",
        rule_set: null,
        resumable: false,
        events: [
          {
            id: 1,
            type: "game_started",
            run_id: "playback_game_1200abcd",
            session_id: "game_1200abcd",
            created_at: "2026-05-19T00:00:00Z",
            round: null,
            phase: null,
            actor: null,
            action: null,
            payload: { players: [] },
          },
          {
            id: 2,
            type: "game_completed",
            run_id: "playback_game_1200abcd",
            session_id: "game_1200abcd",
            created_at: "2026-05-19T00:00:01Z",
            round: null,
            phase: null,
            actor: null,
            action: null,
            payload: { winner: "狼人阵营" },
          },
        ],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );

  renderRoute(["/games/playback/game_1200abcd"]);

  expect(await screen.findByText("历史回放")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the app route test and verify it fails**

Run:

```bash
pnpm --dir apps/web test -- --run src/tests/app.test.tsx -t "historical playback"
```

Expected: FAIL because `GamePlaybackPage` and the route do not exist.

- [ ] **Step 3: Add frontend playback types**

Modify `apps/web/src/features/games/types.ts` after `LiveGameEvent`:

```ts
export type GamePlayback = {
  session_id: string;
  status: GameStatus;
  rule_set?: RuleSetSummary | null;
  resumable?: boolean;
  events: LiveGameEvent[];
};

export type LiveStageRun = Pick<
  GameRun,
  | "run_id"
  | "session_id"
  | "status"
  | "rule_set"
  | "winner"
  | "error"
  | "created_at"
  | "started_at"
  | "completed_at"
  | "event_count"
> & {
  villager_model?: string;
  werewolf_model?: string;
  seed?: number | null;
  max_rounds?: number;
};
```

- [ ] **Step 4: Add the playback API helper**

Create `apps/web/src/features/games/api/getGamePlayback.ts`:

```ts
import { apiFetch } from "../../../api/client";
import type { GamePlayback } from "../types";

export function getGamePlayback(sessionId: string): Promise<GamePlayback> {
  return apiFetch<GamePlayback>(`/api/v1/games/${sessionId}/playback`);
}
```

- [ ] **Step 5: Add a temporary playback page shell**

Create `apps/web/src/pages/GamePlaybackPage.tsx`:

```tsx
import { Text } from "../components/ui";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
import { getGamePlayback } from "../features/games/api/getGamePlayback";

export function GamePlaybackPage() {
  const { sessionId } = useParams();
  const { data, isError, isPending } = useQuery({
    queryKey: ["game-playback", sessionId],
    queryFn: () => getGamePlayback(sessionId!),
    enabled: Boolean(sessionId),
  });

  return (
    <>
      <ArenaGlobalNav
        primaryAction={<ArenaNavButton to={`/games/${sessionId}`}>查看复盘</ArenaNavButton>}
        secondaryAction={<ArenaNavButton to="/games/history">返回历史</ArenaNavButton>}
      />
      <main className="min-h-screen px-4 py-8 text-slate-100">
        <h1 className="sr-only">历史回放</h1>
        {isPending ? <Text className="text-slate-300">正在准备历史播放台...</Text> : null}
        {isError ? <Text className="text-red-300">无法读取历史回放</Text> : null}
        {data ? <Text className="text-slate-300">历史回放</Text> : null}
      </main>
    </>
  );
}
```

- [ ] **Step 6: Add the route**

Modify `apps/web/src/routes/definitions.tsx`:

```tsx
import { GamePlaybackPage } from "../pages/GamePlaybackPage";
```

Insert this route before `/games/:sessionId`:

```tsx
{
  path: "/games/playback/:sessionId",
  element: <GamePlaybackPage />,
},
```

- [ ] **Step 7: Run the route test**

Run:

```bash
pnpm --dir apps/web test -- --run src/tests/app.test.tsx -t "historical playback"
```

Expected: PASS.

- [ ] **Step 8: Commit route/API shell**

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/api/getGamePlayback.ts apps/web/src/pages/GamePlaybackPage.tsx apps/web/src/routes/definitions.tsx apps/web/src/tests/app.test.tsx
git commit -m "feat: add historical playback route"
```

---

### Task 4: Extract Shared Live Stage Experience

**Files:**
- Create: `apps/web/src/features/games/components/LiveStageExperience.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Test: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Add regression assertions for the live page before extraction**

In `apps/web/src/pages/LiveGamePage.test.tsx`, extend the existing `"renders live events and completed replay link"` test with:

```tsx
expect(screen.getByTestId("live-game-page")).toBeInTheDocument();
expect(screen.getByText("观赛舞台")).toBeInTheDocument();
expect(screen.getByText("剧情时间线")).toBeInTheDocument();
```

- [ ] **Step 2: Run the focused live page test**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx -t "renders live events"
```

Expected: PASS before extraction.

- [ ] **Step 3: Create the shared component**

Create `apps/web/src/features/games/components/LiveStageExperience.tsx` by moving the source-agnostic stage layout from `LiveGamePage`. Keep `useLiveDirector`, `deriveLiveSpectatorState`, `deriveGodViewState`, and `deriveLiveNavStatus` in the caller so top-nav controls and the visible stage use the same director instance.

Use this component signature:

```tsx
import { Callout } from "../../../components/ui";
import { useState } from "react";

import { LivePageShell } from "../../../pages/components/LivePageShell";
import { LiveStageModule } from "../../../pages/components/LiveStageModule";
import type { UseLiveDirectorResult } from "../hooks/useLiveDirector";
import type { GodViewState } from "../liveGodView";
import type { LiveSpectatorState } from "../liveSpectator";
import type { LiveGameEvent } from "../types";
import { GodViewBottomBoard } from "./GodViewBottomBoard";
import { GodViewIntelPanel } from "./GodViewIntelPanel";
import { GodViewSituationPanel } from "./GodViewSituationPanel";
import { GodViewTopBar } from "./GodViewTopBar";
import { LiveDirectorStage } from "./LiveDirectorStage";
import { LiveEventTimeline } from "./LiveEventTimeline";

type LiveStageExperienceProps = {
  director: UseLiveDirectorResult;
  events: LiveGameEvent[];
  godViewState: GodViewState;
  mode: "live" | "playback";
  spectatorState: LiveSpectatorState;
};
```

Inside the component, keep only focus state and layout:

```tsx
export function LiveStageExperience({
  director,
  events,
  godViewState,
  mode,
  spectatorState,
}: LiveStageExperienceProps) {
  const [autoFollow, setAutoFollow] = useState(true);
  const [manualFocusName, setManualFocusName] = useState<string | null>(null);
  const autoFocusName = director.currentCue?.actor ?? spectatorState.activePlayerName;
  const focusedPlayerName = autoFollow ? autoFocusName : manualFocusName ?? autoFocusName;

  return (
    <LivePageShell>
      {mode === "playback" && events.length === 0 ? (
        <Callout.Root className="mb-3" color="amber" size="1" variant="soft">
          <Callout.Text>该对局没有可播放事件</Callout.Text>
        </Callout.Root>
      ) : null}
      <LiveStageModule
        bottom={<GodViewBottomBoard state={godViewState} />}
        left={<GodViewSituationPanel state={godViewState} />}
        right={
          <GodViewIntelPanel
            debugTimeline={
              <LiveEventTimeline currentEventId={director.currentEventId} events={events} />
            }
            state={godViewState}
          />
        }
        stage={
          <LiveDirectorStage
            activePlayerName={autoFocusName}
            autoFollow={autoFollow}
            backlogCount={director.backlogCount}
            cue={director.currentCue}
            focusedPlayerName={focusedPlayerName}
            godViewState={godViewState}
            isCatchingUp={director.isCatchingUp}
            onAutoFollowChange={(value) => {
              setAutoFollow(value);
              if (value) {
                setManualFocusName(null);
              }
            }}
            onSelectPlayer={(name) => {
              setAutoFollow(false);
              setManualFocusName(name);
            }}
            players={spectatorState.players}
          />
        }
        top={<GodViewTopBar state={godViewState} />}
      />
    </LivePageShell>
  );
}
```

- [ ] **Step 4: Replace the live page body with the shared component**

In `apps/web/src/pages/LiveGamePage.tsx`, keep fetching, navigation, resume mutation, and top nav context in the page. Replace the inline `LivePageShell`/`LiveStageModule` block with:

```tsx
<LiveStageExperience
  director={director}
  events={events}
  godViewState={godViewState}
  mode="live"
  spectatorState={spectatorState}
/>
```

Remove imports that moved into `LiveStageExperience`: `useState`, `LiveDirectorStage`, `LiveEventTimeline`, `LiveStageModule`, `LivePageShell`, and related GodView components. Keep `useMemo`, `useLiveDirector`, `deriveGodViewState`, `deriveLiveNavStatus`, and `deriveLiveSpectatorState` in `LiveGamePage`.

- [ ] **Step 5: Run the live page tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: PASS. The live page behavior should not change.

- [ ] **Step 6: Commit extraction**

```bash
git add apps/web/src/features/games/components/LiveStageExperience.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "refactor: share live stage experience"
```

---

### Task 5: Full Playback Page Behavior

**Files:**
- Modify: `apps/web/src/pages/GamePlaybackPage.tsx`
- Create: `apps/web/src/pages/GamePlaybackPage.test.tsx`

- [ ] **Step 1: Add playback page tests**

Create `apps/web/src/pages/GamePlaybackPage.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../tests/renderWithClient";
import { GamePlaybackPage } from "./GamePlaybackPage";

function playbackResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return new Response(
    JSON.stringify({
      session_id: "game_1200abcd",
      status: "complete",
      rule_set: {
        id: "starter_6",
        version: "2026.04",
        name: "新手 6 人快局",
        player_count: 6,
        roles: [],
        sheriff_enabled: false,
      },
      resumable: false,
      events: [
        {
          id: 1,
          type: "game_started",
          run_id: "playback_game_1200abcd",
          session_id: "game_1200abcd",
          created_at: "2026-05-19T00:00:00Z",
          round: null,
          phase: null,
          actor: null,
          action: null,
          payload: {
            players: [
              { name: "张三", role: "狼人", model: "deepseek-chat" },
              { name: "李四", role: "村民", model: "deepseek-chat" },
            ],
          },
        },
        {
          id: 2,
          type: "game_completed",
          run_id: "playback_game_1200abcd",
          session_id: "game_1200abcd",
          created_at: "2026-05-19T00:00:01Z",
          round: null,
          phase: null,
          actor: null,
          action: null,
          payload: { winner: "狼人阵营" },
        },
      ],
      ...overrides,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

describe("GamePlaybackPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders historical playback on the live stage", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(playbackResponse());

    renderWithClient(
      <Routes>
        <Route path="/games/playback/:sessionId" element={<GamePlaybackPage />} />
      </Routes>,
      "/games/playback/game_1200abcd",
    );

    expect(await screen.findByText("历史回放")).toBeInTheDocument();
    expect(screen.getByTestId("live-game-page")).toBeInTheDocument();
    expect(screen.getByText("观赛舞台")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看复盘" })).toHaveAttribute(
      "href",
      "/games/game_1200abcd",
    );
    expect(fetch).toHaveBeenCalledWith("/api/v1/games/game_1200abcd/playback", undefined);
  });

  it("resumes a resumable partial playback through the existing resume endpoint", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/game_1200abcd/resume")) {
        expect(init).toEqual(expect.objectContaining({ method: "POST" }));
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_resumed",
              session_id: "game_1200abcd",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              seed: null,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-05-19T00:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        playbackResponse({
          status: "partial",
          resumable: true,
          events: [
            {
              id: 1,
              type: "game_failed",
              run_id: "playback_game_1200abcd",
              session_id: "game_1200abcd",
              created_at: "2026-05-19T00:00:00Z",
              round: null,
              phase: null,
              actor: null,
              action: null,
              payload: { error: "Maximum rounds exceeded", playback_partial: true },
            },
          ],
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games/playback/:sessionId" element={<GamePlaybackPage />} />
        <Route path="/games/live/run_resumed" element={<p>继续后的实时观战</p>} />
      </Routes>,
      "/games/playback/game_1200abcd",
    );

    await screen.findByText("历史回放");
    await userEvent.click(screen.getByLabelText("实时设置"));
    await userEvent.click(screen.getByRole("button", { name: "继续对局" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/api/v1/games/game_1200abcd/resume",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(await screen.findByText("继续后的实时观战")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run playback page tests and verify they fail**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamePlaybackPage.test.tsx
```

Expected: FAIL because the current shell does not render `LiveStageExperience` or resume controls.

- [ ] **Step 3: Implement the playback page**

Replace `apps/web/src/pages/GamePlaybackPage.tsx` with:

```tsx
import { Callout, Text } from "../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ArenaCommandNav, ArenaNavButton } from "../app/navigation";
import { getGamePlayback } from "../features/games/api/getGamePlayback";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { LiveNavSessionBadge } from "../features/games/components/LiveNavSessionBadge";
import { LiveNavSettingsMenu } from "../features/games/components/LiveNavSettingsMenu";
import { LiveNavStatusBadge } from "../features/games/components/LiveNavStatusBadge";
import { LiveStageExperience } from "../features/games/components/LiveStageExperience";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
import { deriveGodViewState } from "../features/games/liveGodView";
import { deriveLiveNavStatus } from "../features/games/liveNavStatus";
import { deriveLiveSpectatorState } from "../features/games/liveSpectator";
import type { GamePlayback, LiveStageRun } from "../features/games/types";

export function GamePlaybackPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isError, isPending } = useQuery({
    queryKey: ["game-playback", sessionId],
    queryFn: () => getGamePlayback(sessionId!),
    enabled: Boolean(sessionId),
  });
  const resumeMutation = useMutation({
    mutationFn: resumeGameRun,
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["games"] });
      navigate(`/games/live/${run.run_id}`);
    },
  });
  const run = useMemo(() => (data ? playbackRun(data) : null), [data]);
  const terminalEvent = data?.events.find(
    (event) => event.type === "game_completed" || event.type === "game_failed",
  );
  const events = data?.events ?? [];
  const spectatorState = useMemo(() => deriveLiveSpectatorState(events), [events]);
  const godViewState = useMemo(
    () =>
      deriveGodViewState(events, spectatorState, run?.rule_set?.name ?? "历史回放", {
        sheriffEnabled: run?.rule_set?.sheriff_enabled,
      }),
    [events, run?.rule_set?.name, run?.rule_set?.sheriff_enabled, spectatorState],
  );
  const director = useLiveDirector(events, {
    resetKey: sessionId,
    startAtLatestTerminal: false,
  });
  const navStatus = run
    ? deriveLiveNavStatus({
        backlogCount: director.backlogCount,
        connectionState: "closed",
        hasCompletedTerminalEvent: terminalEvent?.type === "game_completed",
        hasFailedTerminalEvent: terminalEvent?.type === "game_failed",
        isPaused: director.isPaused,
        runStatus: run.status,
        speed: director.speed,
      })
    : null;

  const topNavActions =
    data && run && navStatus ? (
      <>
        <ArenaNavButton to={`/games/${data.session_id}`}>查看复盘</ArenaNavButton>
        <LiveNavSettingsMenu
          backlogCount={director.backlogCount}
          canResumeRun={Boolean(data.resumable)}
          isPaused={director.isPaused}
          isResuming={resumeMutation.isPending}
          onCatchUpToLatest={director.catchUpToLatest}
          onResumeRun={() => resumeMutation.mutate(data.session_id)}
          onSpeedChange={director.setSpeed}
          onTogglePaused={director.togglePaused}
          run={run}
          speed={director.speed}
          status={navStatus}
          title="回放设置"
        />
      </>
    ) : (
      <ArenaNavButton to="/games/history">返回历史</ArenaNavButton>
    );
  const topNavContext =
    data && navStatus ? (
      <div className="live-nav-context flex min-w-0 flex-1 flex-nowrap items-center gap-x-3 overflow-hidden">
        <h1 className="sr-only">历史回放</h1>
        <LiveNavSessionBadge sessionId={data.session_id} />
        <LiveNavStatusBadge status={navStatus} />
      </div>
    ) : null;

  if (isPending) {
    return (
      <>
        <ArenaCommandNav actions={topNavActions} context={topNavContext} />
        <main className="min-h-screen px-4 py-8 text-slate-100">
          <Text className="text-slate-300" size="2">正在准备历史播放台...</Text>
        </main>
      </>
    );
  }

  if (isError || !data || !run) {
    return (
      <>
        <ArenaCommandNav actions={topNavActions} context={topNavContext} />
        <main className="min-h-screen px-4 py-8 text-slate-100">
          <Callout.Root color="red" size="1" variant="soft">
            <Callout.Text>无法读取历史回放</Callout.Text>
          </Callout.Root>
        </main>
      </>
    );
  }

  return (
    <>
      <ArenaCommandNav actions={topNavActions} context={topNavContext} />
      <main className="live-game-page min-h-screen px-4 py-6 text-slate-100" data-testid="live-game-page">
        <LiveStageExperience
          director={director}
          events={data.events}
          godViewState={godViewState}
          mode="playback"
          spectatorState={spectatorState}
        />
      </main>
    </>
  );
}

function playbackRun(playback: GamePlayback): LiveStageRun {
  const terminalEvent = playback.events.find(
    (event) => event.type === "game_completed" || event.type === "game_failed",
  );
  const winner =
    typeof terminalEvent?.payload.winner === "string"
      ? terminalEvent.payload.winner
      : null;
  const error =
    typeof terminalEvent?.payload.error === "string"
      ? terminalEvent.payload.error
      : null;
  return {
    run_id: `playback_${playback.session_id}`,
    session_id: playback.session_id,
    status: playback.status === "complete" ? "completed" : "failed",
    rule_set: playback.rule_set ?? null,
    winner,
    error,
    created_at: playback.events[0]?.created_at ?? "",
    started_at: playback.events[1]?.created_at ?? null,
    completed_at: terminalEvent?.created_at ?? null,
    event_count: playback.events.length,
  };
}
```

- [ ] **Step 4: Add playback-compatible settings props**

Modify `apps/web/src/features/games/components/LiveNavSettingsMenu.tsx` imports:

```ts
import type { GameRun, LiveStageRun, RuleSetSummary } from "../types";
```

Change the `run` prop so both real runs and playback runs are accepted:

```ts
  run: GameRun | LiveStageRun;
```

Update `normalizeRule` to accept the same widened shape:

```ts
function normalizeRule(run: GameRun | LiveStageRun): RuleSetSummary {
  const configuredPlayerCount =
    "player_configs" in run ? run.player_configs?.length ?? 0 : 0;

  return (
    run.rule_set ?? {
      id: "live",
      name: "实时对局",
      player_count: configuredPlayerCount,
      roles: [],
      version: "-",
    }
  );
}
```

Add an optional settings title:

```ts
  title?: string;
```

Default it in the parameter list:

```tsx
  title = "实时设置",
```

Replace hardcoded settings labels:

```tsx
aria-label={title}
...
<h2 className="text-sm font-semibold text-amber-50" id="live-settings-title">
  {title}
</h2>
...
aria-label={`关闭${title}`}
```

Keep existing live page calls unchanged.

- [ ] **Step 5: Run playback page tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamePlaybackPage.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Run live settings tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/LiveNavSettingsMenu.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit playback page**

```bash
git add apps/web/src/pages/GamePlaybackPage.tsx apps/web/src/pages/GamePlaybackPage.test.tsx apps/web/src/features/games/components/LiveNavSettingsMenu.tsx
git commit -m "feat: render historical playback stage"
```

---

### Task 6: Playback Links from History and Detail

**Files:**
- Modify: `apps/web/src/features/games/components/SessionList.tsx`
- Modify: `apps/web/src/pages/GameHistoryPage.test.tsx`
- Modify: `apps/web/src/pages/GameDetailPage.tsx`
- Modify: `apps/web/src/pages/GameDetailPage.test.tsx`

- [ ] **Step 1: Add history-list playback link assertions**

In `apps/web/src/pages/GameHistoryPage.test.tsx`, extend `"renders available game sessions"` with:

```tsx
expect(screen.getByRole("link", { name: "播放 game_00000001" })).toHaveAttribute(
  "href",
  "/games/playback/game_00000001",
);
```

Extend `"resumes a resumable session from the list"` with:

```tsx
expect(screen.getByRole("link", { name: "播放 game_1200abcd" })).toHaveAttribute(
  "href",
  "/games/playback/game_1200abcd",
);
```

- [ ] **Step 2: Add detail-page playback link assertion**

In `apps/web/src/pages/GameDetailPage.test.tsx`, extend the main render test with:

```tsx
expect(screen.getByRole("link", { name: "放到播放台" })).toHaveAttribute(
  "href",
  "/games/playback/game_1200abcd",
);
```

- [ ] **Step 3: Run affected tests and verify they fail**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GameHistoryPage.test.tsx src/pages/GameDetailPage.test.tsx
```

Expected: FAIL because playback links do not exist yet.

- [ ] **Step 4: Add playback links to `SessionList`**

Modify both ornate and default branches in `apps/web/src/features/games/components/SessionList.tsx`.

In the ornate branch, add this link inside `.history-session-actions`, before the resume button:

```tsx
<Link
  aria-label={`播放 ${session.session_id}`}
  className="history-resume-button"
  to={`/games/playback/${session.session_id}`}
>
  播放
</Link>
```

In the default branch, add this link before the resume button:

```tsx
<Button asChild className="shrink-0" variant="surface">
  <Link aria-label={`播放 ${session.session_id}`} to={`/games/playback/${session.session_id}`}>
    播放
  </Link>
</Button>
```

If `Button` does not support `asChild` in this UI wrapper, use a plain `Link` with:

```tsx
className="shrink-0 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-800 transition hover:bg-slate-100"
```

- [ ] **Step 5: Add playback action to `GameDetailPage`**

Modify `apps/web/src/pages/GameDetailPage.tsx` top nav:

```tsx
secondaryAction={
  <div className="flex items-center gap-2">
    <ArenaNavButton to={`/games/playback/${sessionId}`}>放到播放台</ArenaNavButton>
    <ArenaNavButton to="/games">返回大厅</ArenaNavButton>
  </div>
}
```

Keep the existing refresh button unchanged.

- [ ] **Step 6: Run affected tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GameHistoryPage.test.tsx src/pages/GameDetailPage.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit links**

```bash
git add apps/web/src/features/games/components/SessionList.tsx apps/web/src/pages/GameHistoryPage.test.tsx apps/web/src/pages/GameDetailPage.tsx apps/web/src/pages/GameDetailPage.test.tsx
git commit -m "feat: link history sessions to playback"
```

---

### Task 7: Playback Status Consistency

**Files:**
- Modify: `apps/web/src/features/games/liveNavStatus.ts`
- Modify: `apps/web/src/features/games/liveNavStatus.test.ts`
- Modify: `apps/web/src/pages/GamePlaybackPage.test.tsx`

- [ ] **Step 1: Add status tests for closed completed playback**

Add to `apps/web/src/features/games/liveNavStatus.test.ts`:

```ts
it("treats closed completed playback as ended instead of interrupted", () => {
  expect(
    deriveLiveNavStatus({
      backlogCount: 0,
      connectionState: "closed",
      hasCompletedTerminalEvent: true,
      isPaused: false,
      runStatus: "completed",
      speed: 1,
    }),
  ).toMatchObject({
    kind: "ended",
    label: "已结束",
    tone: "done",
  });
});
```

Add this failed playback test:

```ts
it("treats failed playback as interrupted", () => {
  expect(
    deriveLiveNavStatus({
      backlogCount: 0,
      connectionState: "closed",
      hasFailedTerminalEvent: true,
      isPaused: false,
      runStatus: "failed",
      speed: 1,
    }),
  ).toMatchObject({
    kind: "interrupted",
    label: "异常中断",
    tone: "danger",
  });
});
```

- [ ] **Step 2: Run status tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveNavStatus.test.ts
```

Expected: PASS. If the first test fails, update `deriveLiveNavStatus` so terminal completion takes precedence over a closed playback connection:

```ts
if (isEnded) {
  return {
    detailItems: [endedLabel],
    kind: "ended",
    label: "已结束",
    tone: "done",
  };
}

if (isInterrupted) {
  return {
    detailItems: [interruptedLabel],
    kind: "interrupted",
    label: "异常中断",
    tone: "danger",
  };
}
```

- [ ] **Step 3: Add playback interruption text assertion**

In `apps/web/src/pages/GamePlaybackPage.test.tsx`, add:

```tsx
it("shows interrupted status for partial playback", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    playbackResponse({
      status: "partial",
      resumable: false,
      events: [
        {
          id: 1,
          type: "game_failed",
          run_id: "playback_game_1200abcd",
          session_id: "game_1200abcd",
          created_at: "2026-05-19T00:00:00Z",
          round: null,
          phase: null,
          actor: null,
          action: null,
          payload: { error: "Maximum rounds exceeded", playback_partial: true },
        },
      ],
    }),
  );

  renderWithClient(
    <Routes>
      <Route path="/games/playback/:sessionId" element={<GamePlaybackPage />} />
    </Routes>,
    "/games/playback/game_1200abcd",
  );

  expect(await screen.findByText("异常中断")).toBeInTheDocument();
});
```

- [ ] **Step 4: Run playback and status tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveNavStatus.test.ts src/pages/GamePlaybackPage.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit status polish**

```bash
git add apps/web/src/features/games/liveNavStatus.ts apps/web/src/features/games/liveNavStatus.test.ts apps/web/src/pages/GamePlaybackPage.test.tsx
git commit -m "test: lock playback stage status behavior"
```

---

### Task 8: Final Verification and Cleanup

**Files:**
- Modify only files that fail verification.

- [ ] **Step 1: Run backend verification**

Run:

```bash
pytest apps/api/tests/test_games_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run targeted frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/tests/app.test.tsx src/pages/GameHistoryPage.test.tsx src/pages/GameDetailPage.test.tsx src/pages/LiveGamePage.test.tsx src/pages/GamePlaybackPage.test.tsx src/features/games/liveNavStatus.test.ts src/features/games/components/LiveNavSettingsMenu.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS and Vite emits a production build without TypeScript errors.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only intentional files from this plan are changed.

- [ ] **Step 5: Commit verification-only fixes if any were needed**

If verification required code fixes, commit them:

```bash
git add apps/api apps/web
git commit -m "fix: complete playback verification"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review

Spec coverage:

- Historical playback route and API are covered by Tasks 1, 2, 3, and 5.
- Playback links from history and detail pages are covered by Task 6.
- Reusing the live stage is covered by Task 4 and Task 5.
- Partial/failed sessions preserving resume behavior is covered by Task 1 and Task 5.
- No model calls, no live run creation, and no log mutation are covered by Task 1 assertions and the read-only builder design in Task 2.
- Complete and partial terminal states are covered by Task 7.
- Final verification is covered by Task 8.

Placeholder scan:

- This plan contains no empty implementation steps or undefined plan-only file paths.

Type consistency:

- Backend playback returns `session_id`, `status`, `rule_set`, `resumable`, and `events`, matching the frontend `GamePlayback` type.
- `LiveStageRun` is the shared subset consumed by `GamePlaybackPage` and accepted by `LiveNavSettingsMenu` after Task 5 widens the `run` prop to `GameRun | LiveStageRun`.
- Routes use `/games/playback/:sessionId`, and all links target `/games/playback/${session.session_id}`.
