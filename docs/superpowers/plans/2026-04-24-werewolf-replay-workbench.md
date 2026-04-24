# Werewolf Replay Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only Chinese Werewolf replay workbench that lists generated game sessions and opens a three-panel replay/debug view for complete and partial logs.

**Architecture:** Add a small backend replay API that reads existing session log directories and returns stable JSON contracts without exposing file paths. Add frontend API adapters, TanStack Query pages, and focused React components that render players, rounds, actions, votes, summaries, and model debug details. Keep the first phase read-only: no WebSocket, no model execution from the browser, and no changes to the game runner.

**Tech Stack:** FastAPI, pathlib, pytest, React, Vite, React Router, TanStack Query, Testing Library, Tailwind CSS

---

## File Structure

- Create `apps/api/app/werewolf/replay.py`: session-log reader, path validation, state/log JSON loading, list/detail contracts.
- Create `apps/api/app/api/routes/games.py`: `/api/v1/games` and `/api/v1/games/{session_id}` read-only routes.
- Modify `apps/api/app/api/router.py`: include the games router.
- Modify `apps/api/app/core/config.py`: add `werewolf_logs_dir` setting with default `logs`.
- Create `apps/api/tests/test_games_api.py`: API tests for session listing, detail loading, partial logs, not found, and invalid session IDs.
- Create `apps/web/src/features/games/types.ts`: frontend replay, player, round, action, and debug item types.
- Create `apps/web/src/features/games/api/adapters.ts`: backend JSON to UI model normalization.
- Create `apps/web/src/features/games/api/listGames.ts`: `GET /api/v1/games` client.
- Create `apps/web/src/features/games/api/getGameDetail.ts`: `GET /api/v1/games/:sessionId` client plus adapter.
- Create `apps/web/src/features/games/api/adapters.test.ts`: adapter behavior tests.
- Create `apps/web/src/features/games/components/SessionList.tsx`: compact session list.
- Create `apps/web/src/features/games/components/GameLayout.tsx`: responsive three-panel replay shell.
- Create `apps/web/src/features/games/components/PlayerPanel.tsx`: players, roles, model names, result metadata.
- Create `apps/web/src/features/games/components/RoundTimeline.tsx`: round loop and phase composition.
- Create `apps/web/src/features/games/components/NightPhase.tsx`: elimination, protection, investigation.
- Create `apps/web/src/features/games/components/DayPhase.tsx`: bids, debate, votes, summaries.
- Create `apps/web/src/features/games/components/ActionCard.tsx`: clickable action/debug item card.
- Create `apps/web/src/features/games/components/BidChart.tsx`: compact bid score bars.
- Create `apps/web/src/features/games/components/VoteTable.tsx`: voter to target rows.
- Create `apps/web/src/features/games/components/SummaryStrip.tsx`: per-player summary snippets.
- Create `apps/web/src/features/games/components/DebugPanel.tsx`: prompt, raw response, parsed result viewer.
- Create `apps/web/src/pages/GamesPage.tsx`: session-list route.
- Create `apps/web/src/pages/GameDetailPage.tsx`: detail route and selected debug state.
- Create `apps/web/src/tests/renderWithClient.tsx`: QueryClient and router test helper.
- Modify `apps/web/src/routes/index.tsx`: `/` redirects to `/games`; add `/games` and `/games/:sessionId`.
- Modify `apps/web/src/tests/app.test.tsx`: route smoke test for replay workbench.

## Backend Contract

`GET /api/v1/games` returns:

```json
{
  "sessions": [
    {
      "session_id": "session_20260424_050950_66ea9f38",
      "status": "complete",
      "winner": "狼人阵营",
      "round_count": 3,
      "created_at": "2026-04-24T05:09:50Z"
    }
  ]
}
```

`GET /api/v1/games/{session_id}` returns:

```json
{
  "session_id": "session_20260424_050950_66ea9f38",
  "status": "complete",
  "state": {
    "session_id": "session_20260424_050950_66ea9f38",
    "players": [],
    "rounds": [],
    "winner": "狼人阵营",
    "error_message": ""
  },
  "logs": []
}
```

Only IDs matching `session_YYYYMMDD_HHMMSS_suffix` are accepted. Missing valid sessions return `404`; invalid IDs return `422` from the path parameter pattern.

## Task 1: Backend Replay API

**Files:**
- Create: `apps/api/tests/test_games_api.py`
- Create: `apps/api/app/werewolf/replay.py`
- Create: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/app/core/config.py`

- [ ] **Step 1: Write failing backend API tests**

Create `apps/api/tests/test_games_api.py`:

```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes.games import get_replay_store
from app.main import app
from app.werewolf.replay import ReplayStore


client = TestClient(app)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def override_logs_root(tmp_path: Path) -> None:
    app.dependency_overrides[get_replay_store] = lambda: ReplayStore(tmp_path)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def sample_state(session_id: str, *, winner: str = "狼人阵营", error: str = "") -> dict:
    return {
        "session_id": session_id,
        "players": [
            {"name": "张三", "role": "狼人", "model": "deepseek-chat", "observations": []},
            {"name": "李四", "role": "村民", "model": "deepseek-chat", "observations": []},
        ],
        "rounds": [
            {
                "number": 1,
                "players": ["张三", "李四"],
                "eliminated": "李四",
                "protected": None,
                "investigated": "张三",
                "exiled": None,
                "debate": [],
                "bids": [{"张三": 3}],
                "votes": [{"张三": "李四"}],
                "summaries": {"张三": "我会隐藏身份。"},
                "success": True,
            }
        ],
        "winner": winner,
        "error_message": error,
    }


def sample_logs() -> list[dict]:
    return [
        {
            "number": 1,
            "eliminate": {
                "actor": "张三",
                "action": "remove",
                "options": ["李四"],
                "choice": "李四",
                "lm_log": {
                    "prompt": "请选择今晚击杀对象。",
                    "raw_response": "{\"choice\":\"李四\"}",
                    "parsed": {"choice": "李四"},
                },
            },
            "protect": None,
            "investigate": None,
            "bid": [],
            "debate": [],
            "votes": [],
            "summaries": [],
        }
    ]


def test_list_games_returns_complete_and_partial_sessions(tmp_path) -> None:
    complete_id = "session_20260424_050950_66ea9f38"
    partial_id = "session_20260424_060000_abcd1234"
    write_json(tmp_path / complete_id / "game_complete.json", sample_state(complete_id))
    write_json(tmp_path / complete_id / "game_logs.json", sample_logs())
    write_json(
        tmp_path / partial_id / "game_partial.json",
        sample_state(partial_id, winner="", error="Maximum rounds exceeded"),
    )
    write_json(tmp_path / partial_id / "game_logs.json", sample_logs())
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert [item["session_id"] for item in payload["sessions"]] == [partial_id, complete_id]
    assert payload["sessions"][0]["status"] == "partial"
    assert payload["sessions"][1]["winner"] == "狼人阵营"
    assert payload["sessions"][1]["round_count"] == 1
    assert payload["sessions"][1]["created_at"] == "2026-04-24T05:09:50Z"


def test_get_game_detail_returns_state_and_logs(tmp_path) -> None:
    session_id = "session_20260424_050950_66ea9f38"
    write_json(tmp_path / session_id / "game_complete.json", sample_state(session_id))
    write_json(tmp_path / session_id / "game_logs.json", sample_logs())
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "complete"
    assert payload["state"]["players"][0]["name"] == "张三"
    assert payload["logs"][0]["eliminate"]["lm_log"]["prompt"] == "请选择今晚击杀对象。"


def test_get_game_detail_returns_404_for_missing_valid_session(tmp_path) -> None:
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games/session_20260424_050950_missing")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"


def test_get_game_detail_rejects_invalid_session_id(tmp_path) -> None:
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games/invalid-session-id")
    finally:
        clear_overrides()

    assert response.status_code == 422
```

- [ ] **Step 2: Run backend tests and verify RED**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py -q
```

Expected: FAIL because `app.api.routes.games` and `app.werewolf.replay` do not exist.

- [ ] **Step 3: Implement replay store**

Create `apps/api/app/werewolf/replay.py`:

```python
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SESSION_ID_RE = re.compile(r"^session_(\d{8})_(\d{6})_[A-Za-z0-9_-]+$")


class ReplayNotFoundError(FileNotFoundError):
    pass


class ReplayStore:
    def __init__(self, logs_root: Path) -> None:
        self.logs_root = logs_root

    def list_sessions(self) -> list[dict[str, Any]]:
        if not self.logs_root.exists():
            return []

        sessions = []
        for directory in self.logs_root.iterdir():
            if not directory.is_dir() or not SESSION_ID_RE.match(directory.name):
                continue

            try:
                detail = self.load_session(directory.name)
            except ReplayNotFoundError:
                continue

            state = detail["state"]
            sessions.append(
                {
                    "session_id": directory.name,
                    "status": detail["status"],
                    "winner": state.get("winner") or None,
                    "round_count": len(state.get("rounds", [])),
                    "created_at": created_at_from_session_id(directory.name),
                }
            )

        return sorted(sessions, key=lambda item: item["session_id"], reverse=True)

    def load_session(self, session_id: str) -> dict[str, Any]:
        if not SESSION_ID_RE.match(session_id):
            raise ReplayNotFoundError(session_id)

        session_dir = (self.logs_root / session_id).resolve()
        root = self.logs_root.resolve()
        if root not in session_dir.parents and session_dir != root:
            raise ReplayNotFoundError(session_id)

        complete_file = session_dir / "game_complete.json"
        partial_file = session_dir / "game_partial.json"
        logs_file = session_dir / "game_logs.json"

        if complete_file.exists():
            status = "complete"
            state_file = complete_file
        elif partial_file.exists():
            status = "partial"
            state_file = partial_file
        else:
            raise ReplayNotFoundError(session_id)

        return {
            "session_id": session_id,
            "status": status,
            "state": read_json(state_file),
            "logs": read_json(logs_file) if logs_file.exists() else [],
        }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def created_at_from_session_id(session_id: str) -> str | None:
    match = SESSION_ID_RE.match(session_id)
    if not match:
        return None

    raw_value = "".join(match.groups())
    created_at = datetime.strptime(raw_value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return created_at.isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4: Add config and routes**

Modify `apps/api/app/core/config.py` by adding the setting inside `Settings`:

```python
    werewolf_logs_dir: str = "logs"
```

Create `apps/api/app/api/routes/games.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam

from app.core.config import settings
from app.werewolf.replay import ReplayNotFoundError, ReplayStore


router = APIRouter()


def get_replay_store() -> ReplayStore:
    return ReplayStore(Path(settings.werewolf_logs_dir))


@router.get("")
def list_games(store: Annotated[ReplayStore, Depends(get_replay_store)]) -> dict:
    return {"sessions": store.list_sessions()}


@router.get("/{session_id}")
def get_game_detail(
    session_id: Annotated[
        str,
        PathParam(pattern=r"^session_\d{8}_\d{6}_[A-Za-z0-9_-]+$"),
    ],
    store: Annotated[ReplayStore, Depends(get_replay_store)],
) -> dict:
    try:
        return store.load_session(session_id)
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game session not found") from exc
```

Modify `apps/api/app/api/router.py`:

```python
from fastapi import APIRouter

from app.api.routes.games import router as games_router
from app.api.routes.health import router as health_router


api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(games_router, prefix="/games", tags=["games"])
```

- [ ] **Step 5: Run backend tests and verify GREEN**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit backend API**

Run:

```bash
git add apps/api/app/core/config.py apps/api/app/api/router.py apps/api/app/api/routes/games.py apps/api/app/werewolf/replay.py apps/api/tests/test_games_api.py
git commit -m "feat: add werewolf replay api"
```

## Task 2: Frontend Replay Types And Adapters

**Files:**
- Create: `apps/web/src/features/games/types.ts`
- Create: `apps/web/src/features/games/api/adapters.ts`
- Create: `apps/web/src/features/games/api/adapters.test.ts`
- Create: `apps/web/src/features/games/api/listGames.ts`
- Create: `apps/web/src/features/games/api/getGameDetail.ts`

- [ ] **Step 1: Write failing adapter tests**

Create `apps/web/src/features/games/api/adapters.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { normalizeGameReplay } from "./adapters";
import type { RawGameReplayResponse } from "../types";

const rawReplay: RawGameReplayResponse = {
  session_id: "session_20260424_050950_66ea9f38",
  status: "complete",
  state: {
    session_id: "session_20260424_050950_66ea9f38",
    players: [
      { name: "张三", role: "狼人", model: "deepseek-chat", observations: [] },
      { name: "李四", role: "村民", model: "deepseek-chat", observations: [] },
    ],
    rounds: [
      {
        number: 1,
        players: ["张三", "李四"],
        eliminated: "李四",
        protected: null,
        investigated: "张三",
        exiled: null,
        debate: [{ speaker: "李四", message: "我不是狼。" }],
        bids: [{ 张三: 3 }, { 李四: 1 }],
        votes: [{ 张三: "李四" }],
        summaries: { 张三: "我需要继续伪装。" },
        success: true,
      },
    ],
    winner: "狼人阵营",
    error_message: "",
  },
  logs: [
    {
      number: 1,
      eliminate: {
        actor: "张三",
        action: "remove",
        options: ["李四"],
        choice: "李四",
        lm_log: {
          prompt: "请选择今晚击杀对象。",
          raw_response: "{\"choice\":\"李四\"}",
          parsed: { choice: "李四" },
        },
      },
      protect: null,
      investigate: null,
      bid: [],
      debate: [],
      votes: [],
      summaries: [],
    },
  ],
};

describe("normalizeGameReplay", () => {
  it("maps backend replay payload into stable UI fields", () => {
    const replay = normalizeGameReplay(rawReplay);

    expect(replay.sessionId).toBe("session_20260424_050950_66ea9f38");
    expect(replay.status).toBe("complete");
    expect(replay.winner).toBe("狼人阵营");
    expect(replay.players[0]).toMatchObject({ name: "张三", role: "狼人" });
    expect(replay.rounds[0].bids).toEqual([
      { actor: "张三", score: 3 },
      { actor: "李四", score: 1 },
    ]);
  });

  it("creates debug items for model actions", () => {
    const replay = normalizeGameReplay(rawReplay);

    expect(replay.debugItems).toHaveLength(1);
    expect(replay.debugItems[0]).toMatchObject({
      id: "round-1-night-eliminate",
      roundNumber: 1,
      phase: "night",
      title: "狼人击杀",
      actor: "张三",
      choice: "李四",
      prompt: "请选择今晚击杀对象。",
    });
  });
});
```

- [ ] **Step 2: Run adapter tests and verify RED**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/api/adapters.test.ts
```

Expected: FAIL because the games adapter module does not exist.

- [ ] **Step 3: Add frontend types**

Create `apps/web/src/features/games/types.ts`:

```typescript
export type GameStatus = "complete" | "partial";

export type GameSessionSummary = {
  session_id: string;
  status: GameStatus;
  winner: string | null;
  round_count: number;
  created_at: string | null;
};

export type GameSessionsResponse = {
  sessions: GameSessionSummary[];
};

export type RawLmLog = {
  prompt?: string;
  raw_response?: string;
  parsed?: unknown;
};

export type RawActionLog = {
  actor: string;
  action: string;
  options: string[];
  choice: string | null;
  lm_log: RawLmLog;
};

export type RawRoundLog = {
  number: number;
  eliminate: RawActionLog | null;
  protect: RawActionLog | null;
  investigate: RawActionLog | null;
  bid: RawActionLog[][];
  debate: RawActionLog[];
  votes: RawActionLog[][];
  summaries: RawActionLog[];
};

export type RawPlayer = {
  name: string;
  role: string;
  model: string;
  observations?: string[];
};

export type RawRoundState = {
  number: number;
  players: string[];
  eliminated: string | null;
  protected: string | null;
  investigated: string | null;
  exiled: string | null;
  debate: Array<{ speaker: string; message: string }>;
  bids: Array<Record<string, number>>;
  votes: Array<Record<string, string>>;
  summaries: Record<string, string>;
  success: boolean;
};

export type RawGameState = {
  session_id: string;
  players: RawPlayer[];
  rounds: RawRoundState[];
  winner: string;
  error_message: string;
};

export type RawGameReplayResponse = {
  session_id: string;
  status: GameStatus;
  state: RawGameState;
  logs: RawRoundLog[];
};

export type BidEntry = {
  actor: string;
  score: number;
};

export type VoteEntry = {
  voter: string;
  target: string;
};

export type DebugItem = {
  id: string;
  roundNumber: number;
  phase: "night" | "day" | "summary";
  title: string;
  actor: string;
  action: string;
  choice: string | null;
  prompt: string;
  rawResponse: string;
  parsed: unknown;
};

export type GameRound = Omit<RawRoundState, "bids" | "votes"> & {
  bids: BidEntry[];
  votes: VoteEntry[];
};

export type GameReplay = {
  sessionId: string;
  status: GameStatus;
  winner: string;
  errorMessage: string;
  players: RawPlayer[];
  rounds: GameRound[];
  logs: RawRoundLog[];
  debugItems: DebugItem[];
};
```

- [ ] **Step 4: Add API functions and adapter**

Create `apps/web/src/features/games/api/listGames.ts`:

```typescript
import { apiFetch } from "../../../api/client";
import type { GameSessionsResponse } from "../types";

export function listGames() {
  return apiFetch<GameSessionsResponse>("/api/v1/games");
}
```

Create `apps/web/src/features/games/api/getGameDetail.ts`:

```typescript
import { apiFetch } from "../../../api/client";
import type { GameReplay, RawGameReplayResponse } from "../types";

import { normalizeGameReplay } from "./adapters";

export async function getGameDetail(sessionId: string): Promise<GameReplay> {
  const response = await apiFetch<RawGameReplayResponse>(`/api/v1/games/${sessionId}`);
  return normalizeGameReplay(response);
}
```

Create `apps/web/src/features/games/api/adapters.ts`:

```typescript
import type {
  DebugItem,
  GameReplay,
  GameRound,
  RawActionLog,
  RawGameReplayResponse,
  RawRoundLog,
} from "../types";

const ACTION_TITLES: Record<string, string> = {
  remove: "狼人击杀",
  protect: "医生守护",
  investigate: "预言家查验",
  bid: "发言竞价",
  debate: "白天发言",
  vote: "放逐投票",
  summarize: "轮次总结",
};

export function normalizeGameReplay(response: RawGameReplayResponse): GameReplay {
  return {
    sessionId: response.session_id,
    status: response.status,
    winner: response.state.winner,
    errorMessage: response.state.error_message,
    players: response.state.players,
    rounds: response.state.rounds.map(normalizeRound),
    logs: response.logs,
    debugItems: response.logs.flatMap(debugItemsFromRound),
  };
}

function normalizeRound(round: RawGameReplayResponse["state"]["rounds"][number]): GameRound {
  return {
    ...round,
    bids: round.bids.flatMap((entry) =>
      Object.entries(entry).map(([actor, score]) => ({ actor, score })),
    ),
    votes: round.votes.flatMap((entry) =>
      Object.entries(entry).map(([voter, target]) => ({ voter, target })),
    ),
  };
}

function debugItemsFromRound(round: RawRoundLog): DebugItem[] {
  const items: DebugItem[] = [];
  pushAction(items, round.number, "night", "night-eliminate", round.eliminate);
  pushAction(items, round.number, "night", "night-protect", round.protect);
  pushAction(items, round.number, "night", "night-investigate", round.investigate);

  round.bid.flat().forEach((action, index) => {
    pushAction(items, round.number, "day", `day-bid-${index}`, action);
  });
  round.debate.forEach((action, index) => {
    pushAction(items, round.number, "day", `day-debate-${index}`, action);
  });
  round.votes.flat().forEach((action, index) => {
    pushAction(items, round.number, "day", `day-vote-${index}`, action);
  });
  round.summaries.forEach((action, index) => {
    pushAction(items, round.number, "summary", `summary-${index}`, action);
  });

  return items;
}

function pushAction(
  items: DebugItem[],
  roundNumber: number,
  phase: DebugItem["phase"],
  suffix: string,
  action: RawActionLog | null,
) {
  if (!action) {
    return;
  }

  items.push({
    id: `round-${roundNumber}-${suffix}`,
    roundNumber,
    phase,
    title: ACTION_TITLES[action.action] ?? action.action,
    actor: action.actor,
    action: action.action,
    choice: action.choice,
    prompt: action.lm_log.prompt ?? "",
    rawResponse: action.lm_log.raw_response ?? "",
    parsed: action.lm_log.parsed,
  });
}
```

- [ ] **Step 5: Run adapter tests and verify GREEN**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/api/adapters.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit frontend data layer**

Run:

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/api
git commit -m "feat: add werewolf replay data adapters"
```

## Task 3: Games List Page

**Files:**
- Create: `apps/web/src/tests/renderWithClient.tsx`
- Create: `apps/web/src/features/games/components/SessionList.tsx`
- Create: `apps/web/src/pages/GamesPage.tsx`
- Create: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Add test render helper**

Create `apps/web/src/tests/renderWithClient.tsx`:

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
}

export function renderWithClient(ui: ReactElement, route = "/") {
  const queryClient = createTestQueryClient();

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

export function TestQueryProvider({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>
  );
}
```

- [ ] **Step 2: Write failing GamesPage tests**

Create `apps/web/src/pages/GamesPage.test.tsx`:

```typescript
import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../tests/renderWithClient";
import { GamesPage } from "./GamesPage";

describe("GamesPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders generated game sessions", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          sessions: [
            {
              session_id: "session_20260424_050950_66ea9f38",
              status: "complete",
              winner: "狼人阵营",
              round_count: 3,
              created_at: "2026-04-24T05:09:50Z",
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderWithClient(<GamesPage />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "狼人杀对局复盘" })).toBeInTheDocument(),
    );
    expect(screen.getByText("session_20260424_050950_66ea9f38")).toBeInTheDocument();
    expect(screen.getByText("狼人阵营")).toBeInTheDocument();
  });

  it("renders an empty state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithClient(<GamesPage />);

    expect(await screen.findByText("还没有可复盘的对局")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run GamesPage tests and verify RED**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL because `GamesPage` and `SessionList` do not exist.

- [ ] **Step 4: Implement session list page**

Create `apps/web/src/features/games/components/SessionList.tsx`:

```tsx
import { Link } from "react-router-dom";

import type { GameSessionSummary } from "../types";

export function SessionList({ sessions }: { sessions: GameSessionSummary[] }) {
  if (sessions.length === 0) {
    return (
      <div className="border border-dashed border-slate-700 bg-slate-900/70 p-8 text-center text-slate-300">
        还没有可复盘的对局
      </div>
    );
  }

  return (
    <div className="divide-y divide-slate-800 border border-slate-800 bg-slate-950">
      {sessions.map((session) => (
        <Link
          key={session.session_id}
          to={`/games/${session.session_id}`}
          className="grid gap-2 p-4 text-slate-100 transition hover:bg-slate-900 md:grid-cols-[1fr_120px_120px_170px]"
        >
          <span className="font-mono text-sm">{session.session_id}</span>
          <span>{session.status === "complete" ? "已完成" : "部分日志"}</span>
          <span>{session.winner ?? "未决出"}</span>
          <span className="text-slate-400">{session.round_count} 轮</span>
        </Link>
      ))}
    </div>
  );
}
```

Create `apps/web/src/pages/GamesPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";

import { listGames } from "../features/games/api/listGames";
import { SessionList } from "../features/games/components/SessionList";

export function GamesPage() {
  const gamesQuery = useQuery({
    queryKey: ["games"],
    queryFn: listGames,
  });

  return (
    <main className="min-h-screen bg-slate-950 text-slate-50">
      <section className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold">狼人杀对局复盘</h1>
          <p className="text-sm text-slate-400">
            查看后端生成的中文狼人杀日志、回合行动和模型调试信息。
          </p>
        </div>

        {gamesQuery.isPending ? (
          <p className="text-slate-300">正在读取对局列表...</p>
        ) : gamesQuery.isError ? (
          <p className="text-rose-300">无法读取对局列表</p>
        ) : (
          <SessionList sessions={gamesQuery.data.sessions} />
        )}
      </section>
    </main>
  );
}
```

- [ ] **Step 5: Run GamesPage tests and verify GREEN**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit games list page**

Run:

```bash
git add apps/web/src/tests/renderWithClient.tsx apps/web/src/features/games/components/SessionList.tsx apps/web/src/pages/GamesPage.tsx apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat: add werewolf games list page"
```

## Task 4: Replay Detail Components And Debug Panel

**Files:**
- Create: `apps/web/src/features/games/components/ActionCard.tsx`
- Create: `apps/web/src/features/games/components/BidChart.tsx`
- Create: `apps/web/src/features/games/components/DebugPanel.tsx`
- Create: `apps/web/src/features/games/components/DayPhase.tsx`
- Create: `apps/web/src/features/games/components/GameLayout.tsx`
- Create: `apps/web/src/features/games/components/NightPhase.tsx`
- Create: `apps/web/src/features/games/components/PlayerPanel.tsx`
- Create: `apps/web/src/features/games/components/RoundTimeline.tsx`
- Create: `apps/web/src/features/games/components/SummaryStrip.tsx`
- Create: `apps/web/src/features/games/components/VoteTable.tsx`
- Create: `apps/web/src/pages/GameDetailPage.tsx`
- Create: `apps/web/src/pages/GameDetailPage.test.tsx`

- [ ] **Step 1: Write failing replay interaction test**

Create `apps/web/src/pages/GameDetailPage.test.tsx`:

```typescript
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import { renderWithClient } from "../tests/renderWithClient";
import { GameDetailPage } from "./GameDetailPage";

const detailResponse = {
  session_id: "session_20260424_050950_66ea9f38",
  status: "complete",
  state: {
    session_id: "session_20260424_050950_66ea9f38",
    players: [
      { name: "张三", role: "狼人", model: "deepseek-chat", observations: [] },
      { name: "李四", role: "村民", model: "deepseek-chat", observations: [] },
    ],
    rounds: [
      {
        number: 1,
        players: ["张三", "李四"],
        eliminated: "李四",
        protected: null,
        investigated: "张三",
        exiled: "李四",
        debate: [{ speaker: "李四", message: "我不是狼。" }],
        bids: [{ 张三: 3 }, { 李四: 1 }],
        votes: [{ 张三: "李四" }],
        summaries: { 张三: "我需要继续伪装。" },
        success: true,
      },
    ],
    winner: "狼人阵营",
    error_message: "",
  },
  logs: [
    {
      number: 1,
      eliminate: {
        actor: "张三",
        action: "remove",
        options: ["李四"],
        choice: "李四",
        lm_log: {
          prompt: "请选择今晚击杀对象。",
          raw_response: "{\"choice\":\"李四\"}",
          parsed: { choice: "李四" },
        },
      },
      protect: null,
      investigate: null,
      bid: [],
      debate: [],
      votes: [],
      summaries: [],
    },
  ],
};

describe("GameDetailPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders replay details and opens model debug output", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(detailResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithClient(
      <Routes>
        <Route path="/games/:sessionId" element={<GameDetailPage />} />
      </Routes>,
      "/games/session_20260424_050950_66ea9f38",
    );

    await waitFor(() => expect(screen.getByText("狼人阵营")).toBeInTheDocument());
    expect(screen.getByText("张三")).toBeInTheDocument();
    expect(screen.getByText("第 1 轮")).toBeInTheDocument();
    expect(screen.getByText("李四 -> 我不是狼。")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /狼人击杀 张三 选择 李四/i }));

    expect(screen.getByText("请选择今晚击杀对象。")).toBeInTheDocument();
    expect(screen.getByText("{\"choice\":\"李四\"}")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run replay test and verify RED**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GameDetailPage.test.tsx
```

Expected: FAIL because the detail page and components do not exist.

- [ ] **Step 3: Implement layout, player panel, and debug panel**

Create `apps/web/src/features/games/components/GameLayout.tsx`:

```tsx
import type { ReactNode } from "react";

export function GameLayout({
  players,
  timeline,
  debug,
}: {
  players: ReactNode;
  timeline: ReactNode;
  debug: ReactNode;
}) {
  return (
    <div className="grid min-h-screen gap-4 bg-slate-950 p-4 text-slate-50 xl:grid-cols-[280px_minmax(0,1fr)_360px]">
      <aside className="border border-slate-800 bg-slate-950">{players}</aside>
      <section className="min-w-0 border border-slate-800 bg-slate-950">{timeline}</section>
      <aside className="border border-slate-800 bg-slate-950">{debug}</aside>
    </div>
  );
}
```

Create `apps/web/src/features/games/components/PlayerPanel.tsx`:

```tsx
import type { GameReplay } from "../types";

const ROLE_CLASS: Record<string, string> = {
  狼人: "border-rose-500/40 bg-rose-500/10 text-rose-100",
  预言家: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100",
  医生: "border-sky-500/40 bg-sky-500/10 text-sky-100",
  村民: "border-slate-600 bg-slate-900 text-slate-200",
};

export function PlayerPanel({ replay }: { replay: GameReplay }) {
  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <p className="text-xs uppercase text-slate-500">Session</p>
        <h2 className="break-all font-mono text-sm">{replay.sessionId}</h2>
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <p className="text-slate-500">胜利阵营</p>
          <p>{replay.winner || "未决出"}</p>
        </div>
        <div>
          <p className="text-slate-500">轮次</p>
          <p>{replay.rounds.length}</p>
        </div>
      </div>
      {replay.errorMessage ? <p className="text-sm text-amber-300">{replay.errorMessage}</p> : null}
      <div className="flex flex-col gap-2">
        {replay.players.map((player) => (
          <div
            key={player.name}
            className={`border p-3 text-sm ${ROLE_CLASS[player.role] ?? ROLE_CLASS["村民"]}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{player.name}</span>
              <span>{player.role}</span>
            </div>
            <p className="mt-1 break-all text-xs opacity-80">{player.model}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
```

Create `apps/web/src/features/games/components/DebugPanel.tsx`:

```tsx
import type { DebugItem } from "../types";

export function DebugPanel({ item }: { item: DebugItem | null }) {
  if (!item) {
    return <div className="p-4 text-sm text-slate-400">选择一条行动查看模型输入输出</div>;
  }

  return (
    <div className="flex h-full flex-col gap-4 p-4 text-sm">
      <div>
        <p className="text-xs uppercase text-slate-500">Debug</p>
        <h2 className="text-lg font-semibold">{item.title}</h2>
        <p className="text-slate-400">
          第 {item.roundNumber} 轮 · {item.actor} · {item.choice ?? "无选择"}
        </p>
      </div>
      <DebugBlock title="Prompt" value={item.prompt} />
      <DebugBlock title="Raw Response" value={item.rawResponse} />
      <DebugBlock title="Parsed Result" value={JSON.stringify(item.parsed, null, 2)} />
    </div>
  );
}

function DebugBlock({ title, value }: { title: string; value: string }) {
  return (
    <section className="min-h-0">
      <h3 className="mb-2 text-xs uppercase text-slate-500">{title}</h3>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap border border-slate-800 bg-slate-900 p-3 text-xs text-slate-100">
        {value || "无内容"}
      </pre>
    </section>
  );
}
```

- [ ] **Step 4: Implement action, phase, and timeline components**

Create `apps/web/src/features/games/components/ActionCard.tsx`:

```tsx
import type { DebugItem } from "../types";

export function ActionCard({
  item,
  selected,
  onSelect,
}: {
  item: DebugItem;
  selected: boolean;
  onSelect: (item: DebugItem) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(item)}
      className={`w-full border p-3 text-left text-sm transition ${
        selected ? "border-cyan-400 bg-cyan-400/10" : "border-slate-800 bg-slate-900 hover:bg-slate-800"
      }`}
      aria-label={`${item.title} ${item.actor} 选择 ${item.choice ?? "无"}`}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{item.title}</span>
        <span className="text-slate-400">{item.actor}</span>
      </div>
      <p className="mt-1 text-slate-300">选择：{item.choice ?? "无"}</p>
    </button>
  );
}
```

Create `apps/web/src/features/games/components/BidChart.tsx`:

```tsx
import type { BidEntry } from "../types";

export function BidChart({ bids }: { bids: BidEntry[] }) {
  if (bids.length === 0) {
    return <p className="text-sm text-slate-500">无竞价记录</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {bids.map((bid) => (
        <div key={`${bid.actor}-${bid.score}`} className="grid grid-cols-[72px_1fr_24px] items-center gap-2 text-sm">
          <span>{bid.actor}</span>
          <span className="h-2 bg-slate-800">
            <span className="block h-2 bg-amber-300" style={{ width: `${Math.max(8, bid.score * 20)}%` }} />
          </span>
          <span className="text-right text-slate-400">{bid.score}</span>
        </div>
      ))}
    </div>
  );
}
```

Create `apps/web/src/features/games/components/VoteTable.tsx`:

```tsx
import type { VoteEntry } from "../types";

export function VoteTable({ votes }: { votes: VoteEntry[] }) {
  if (votes.length === 0) {
    return <p className="text-sm text-slate-500">无投票记录</p>;
  }

  return (
    <div className="divide-y divide-slate-800 border border-slate-800">
      {votes.map((vote) => (
        <div key={`${vote.voter}-${vote.target}`} className="grid grid-cols-2 p-2 text-sm">
          <span>{vote.voter}</span>
          <span className="text-slate-300">{vote.target}</span>
        </div>
      ))}
    </div>
  );
}
```

Create `apps/web/src/features/games/components/SummaryStrip.tsx`:

```tsx
export function SummaryStrip({ summaries }: { summaries: Record<string, string> }) {
  const entries = Object.entries(summaries);

  if (entries.length === 0) {
    return <p className="text-sm text-slate-500">无总结记录</p>;
  }

  return (
    <div className="grid gap-2 md:grid-cols-2">
      {entries.map(([speaker, summary]) => (
        <p key={speaker} className="border border-slate-800 bg-slate-900 p-3 text-sm text-slate-300">
          <span className="font-medium text-slate-100">{speaker}</span>：{summary}
        </p>
      ))}
    </div>
  );
}
```

Create `apps/web/src/features/games/components/NightPhase.tsx`:

```tsx
import type { DebugItem, GameRound } from "../types";

import { ActionCard } from "./ActionCard";

export function NightPhase({
  round,
  items,
  selectedId,
  onSelect,
}: {
  round: GameRound;
  items: DebugItem[];
  selectedId: string | null;
  onSelect: (item: DebugItem) => void;
}) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-slate-300">夜晚</h3>
      <div className="grid gap-2 md:grid-cols-3">
        <p className="text-sm text-slate-400">死亡：{round.eliminated ?? "无人"}</p>
        <p className="text-sm text-slate-400">守护：{round.protected ?? "无人"}</p>
        <p className="text-sm text-slate-400">查验：{round.investigated ?? "无人"}</p>
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        {items.map((item) => (
          <ActionCard key={item.id} item={item} selected={selectedId === item.id} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}
```

Create `apps/web/src/features/games/components/DayPhase.tsx`:

```tsx
import type { DebugItem, GameRound } from "../types";

import { ActionCard } from "./ActionCard";
import { BidChart } from "./BidChart";
import { SummaryStrip } from "./SummaryStrip";
import { VoteTable } from "./VoteTable";

export function DayPhase({
  round,
  items,
  selectedId,
  onSelect,
}: {
  round: GameRound;
  items: DebugItem[];
  selectedId: string | null;
  onSelect: (item: DebugItem) => void;
}) {
  return (
    <section className="flex flex-col gap-4">
      <h3 className="text-sm font-semibold text-slate-300">白天</h3>
      <BidChart bids={round.bids} />
      <div className="flex flex-col gap-2">
        {round.debate.map((entry) => (
          <p key={`${entry.speaker}-${entry.message}`} className="text-sm text-slate-300">
            {entry.speaker} -&gt; {entry.message}
          </p>
        ))}
      </div>
      <VoteTable votes={round.votes} />
      <SummaryStrip summaries={round.summaries} />
      <div className="grid gap-2 md:grid-cols-2">
        {items.map((item) => (
          <ActionCard key={item.id} item={item} selected={selectedId === item.id} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}
```

Create `apps/web/src/features/games/components/RoundTimeline.tsx`:

```tsx
import type { DebugItem, GameReplay } from "../types";

import { DayPhase } from "./DayPhase";
import { NightPhase } from "./NightPhase";

export function RoundTimeline({
  replay,
  selectedId,
  onSelect,
}: {
  replay: GameReplay;
  selectedId: string | null;
  onSelect: (item: DebugItem) => void;
}) {
  return (
    <div className="flex flex-col gap-6 p-4">
      <div>
        <p className="text-xs uppercase text-slate-500">Replay</p>
        <h1 className="text-2xl font-semibold">对局时间线</h1>
      </div>
      {replay.rounds.map((round) => {
        const roundItems = replay.debugItems.filter((item) => item.roundNumber === round.number);
        const nightItems = roundItems.filter((item) => item.phase === "night");
        const dayItems = roundItems.filter((item) => item.phase !== "night");

        return (
          <article key={round.number} className="flex flex-col gap-5 border border-slate-800 bg-slate-950 p-4">
            <h2 className="text-lg font-semibold">第 {round.number} 轮</h2>
            <NightPhase round={round} items={nightItems} selectedId={selectedId} onSelect={onSelect} />
            <DayPhase round={round} items={dayItems} selectedId={selectedId} onSelect={onSelect} />
          </article>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 5: Implement detail page**

Create `apps/web/src/pages/GameDetailPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { getGameDetail } from "../features/games/api/getGameDetail";
import { DebugPanel } from "../features/games/components/DebugPanel";
import { GameLayout } from "../features/games/components/GameLayout";
import { PlayerPanel } from "../features/games/components/PlayerPanel";
import { RoundTimeline } from "../features/games/components/RoundTimeline";
import type { DebugItem } from "../features/games/types";

export function GameDetailPage() {
  const { sessionId = "" } = useParams();
  const [selected, setSelected] = useState<DebugItem | null>(null);

  const gameQuery = useQuery({
    queryKey: ["games", sessionId],
    queryFn: () => getGameDetail(sessionId),
    enabled: Boolean(sessionId),
  });

  const selectedItem = useMemo(() => {
    if (!gameQuery.data) {
      return null;
    }
    return selected ?? gameQuery.data.debugItems[0] ?? null;
  }, [gameQuery.data, selected]);

  if (gameQuery.isPending) {
    return <main className="min-h-screen bg-slate-950 p-6 text-slate-300">正在读取对局...</main>;
  }

  if (gameQuery.isError) {
    return <main className="min-h-screen bg-slate-950 p-6 text-rose-300">无法读取该对局</main>;
  }

  return (
    <GameLayout
      players={<PlayerPanel replay={gameQuery.data} />}
      timeline={
        <RoundTimeline
          replay={gameQuery.data}
          selectedId={selectedItem?.id ?? null}
          onSelect={setSelected}
        />
      }
      debug={<DebugPanel item={selectedItem} />}
    />
  );
}
```

- [ ] **Step 6: Run replay tests and verify GREEN**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GameDetailPage.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit replay detail page**

Run:

```bash
git add apps/web/src/features/games/components apps/web/src/pages/GameDetailPage.tsx apps/web/src/pages/GameDetailPage.test.tsx
git commit -m "feat: add werewolf replay detail view"
```

## Task 5: App Routes And Smoke Tests

**Files:**
- Modify: `apps/web/src/routes/index.tsx`
- Modify: `apps/web/src/tests/app.test.tsx`

- [ ] **Step 1: Write failing app route test**

Replace `apps/web/src/tests/app.test.tsx` with:

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../app/App";

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("redirects the root route to the games workbench", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <App />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "狼人杀对局复盘" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run app test and verify RED**

Run:

```bash
cd apps/web && pnpm test -- --run src/tests/app.test.tsx
```

Expected: FAIL because `/` still renders the skeleton home page.

- [ ] **Step 3: Wire routes**

Modify `apps/web/src/routes/index.tsx`:

```tsx
import { Navigate, createBrowserRouter } from "react-router-dom";

import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Navigate to="/games" replace />,
  },
  {
    path: "/games",
    element: <GamesPage />,
  },
  {
    path: "/games/:sessionId",
    element: <GameDetailPage />,
  },
]);
```

- [ ] **Step 4: Run app test and verify GREEN**

Run:

```bash
cd apps/web && pnpm test -- --run src/tests/app.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit route wiring**

Run:

```bash
git add apps/web/src/routes/index.tsx apps/web/src/tests/app.test.tsx
git commit -m "feat: route app to werewolf replay workbench"
```

## Task 6: Full Verification And Manual Browser Check

**Files:**
- No new files.
- Use existing generated logs under `apps/api/logs` or run the CLI once if no logs exist.

- [ ] **Step 1: Run backend tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest
```

Expected: PASS.

- [ ] **Step 2: Run backend lint**

Run:

```bash
cd apps/api && .venv/bin/ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
npm run test:web
```

Expected: PASS.

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm run build:web
```

Expected: PASS.

- [ ] **Step 5: Start backend and frontend for manual verification**

Terminal A:

```bash
cd apps/api && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal B:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 pnpm --dir apps/web dev --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/games`.

Expected manual checks:

- The session list loads without exposing file paths.
- A complete game opens and shows players, winner, round count, night phase, day phase, votes, and summaries.
- A partial game displays the stored error message in the player panel.
- Clicking an action updates the debug panel with prompt, raw response, and parsed result.
- The layout stacks into readable panels on a narrow viewport.

- [ ] **Step 6: Commit any verification-driven fixes**

Run this only if the manual check required a small fix:

```bash
git add apps/api apps/web
git commit -m "fix: polish werewolf replay workbench"
```

## Self-Review

- Spec coverage: Task 1 creates the read-only backend games API. Tasks 2 through 5 create the session list, replay route, player panel, round timeline, night/day phases, votes, summaries, and clickable debug panel. Task 6 verifies backend tests, frontend tests, build, and browser behavior.
- Placeholder scan: The plan contains exact file paths, concrete tests, code blocks, commands, and expected outcomes.
- Type consistency: Backend uses `session_id`, `status`, `state`, and `logs`; adapters map these to `sessionId`, `status`, `players`, `rounds`, and `debugItems`; components consume the normalized types.
- Scope check: The plan remains read-only and does not add WebSockets, login, browser-triggered model runs, or changes to DeepSeek game execution.
