# 狼人杀对局复盘工作台实施计划

> **给 agentic workers：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项实施本计划。步骤使用 checkbox（`- [ ]`）语法进行跟踪。

**目标：** 构建一个只读的中文狼人杀对局复盘工作台，用于列出已生成的游戏会话，并为完整日志和部分日志打开三栏复盘/调试视图。

**架构：** 新增一个小型后端复盘 API，读取现有会话日志目录，并在不暴露文件路径的前提下返回稳定的 JSON 契约。新增前端 API 适配器、TanStack Query 页面，以及职责聚焦的 React 组件，用于渲染玩家、轮次、行动、投票、总结和模型调试详情。第一阶段保持只读：不使用 WebSocket，不从浏览器执行模型，也不修改游戏运行器。

**技术栈：** FastAPI, pathlib, pytest, React, Vite, React Router, TanStack Query, Testing Library, Tailwind CSS

---

## 文件结构

- 创建 `apps/api/app/werewolf/replay.py`：会话日志读取器、路径校验、状态/日志 JSON 加载、列表/详情契约。
- 创建 `apps/api/app/api/routes/games.py`：`/api/v1/games` 和 `/api/v1/games/{session_id}` 只读路由。
- 修改 `apps/api/app/api/router.py`：引入 games 路由。
- 修改 `apps/api/app/core/config.py`：添加 `werewolf_logs_dir` 设置，默认值为 `logs`。
- 创建 `apps/api/tests/test_games_api.py`：覆盖会话列表、详情加载、部分日志、未找到和非法会话 ID 的 API 测试。
- 创建 `apps/web/src/features/games/types.ts`：前端复盘、玩家、轮次、行动和调试项类型。
- 创建 `apps/web/src/features/games/api/adapters.ts`：将后端 JSON 规范化为 UI 模型。
- 创建 `apps/web/src/features/games/api/listGames.ts`：`GET /api/v1/games` 客户端。
- 创建 `apps/web/src/features/games/api/getGameDetail.ts`：`GET /api/v1/games/:sessionId` 客户端及适配器。
- 创建 `apps/web/src/features/games/api/adapters.test.ts`：适配器行为测试。
- 创建 `apps/web/src/features/games/components/SessionList.tsx`：紧凑会话列表。
- 创建 `apps/web/src/features/games/components/GameLayout.tsx`：响应式三栏复盘外壳。
- 创建 `apps/web/src/features/games/components/PlayerPanel.tsx`：玩家、角色、模型名称和结果元数据。
- 创建 `apps/web/src/features/games/components/RoundTimeline.tsx`：轮次循环和阶段组合。
- 创建 `apps/web/src/features/games/components/NightPhase.tsx`：击杀、守护、查验。
- 创建 `apps/web/src/features/games/components/DayPhase.tsx`：竞价、辩论、投票、总结。
- 创建 `apps/web/src/features/games/components/ActionCard.tsx`：可点击的行动/调试项卡片。
- 创建 `apps/web/src/features/games/components/BidChart.tsx`：紧凑竞价分数条。
- 创建 `apps/web/src/features/games/components/VoteTable.tsx`：投票者到目标的行列表。
- 创建 `apps/web/src/features/games/components/SummaryStrip.tsx`：按玩家展示的总结片段。
- 创建 `apps/web/src/features/games/components/DebugPanel.tsx`：prompt、raw response、parsed result 查看器。
- 创建 `apps/web/src/pages/GamesPage.tsx`：会话列表路由。
- 创建 `apps/web/src/pages/GameDetailPage.tsx`：详情路由和选中调试状态。
- 创建 `apps/web/src/tests/renderWithClient.tsx`：QueryClient 和路由测试辅助工具。
- 修改 `apps/web/src/routes/index.tsx`：`/` 重定向到 `/games`；添加 `/games` 和 `/games/:sessionId`。
- 修改 `apps/web/src/tests/app.test.tsx`：复盘工作台的路由冒烟测试。

## 后端契约

`GET /api/v1/games` 返回：

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

`GET /api/v1/games/{session_id}` 返回：

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

只接受匹配 `session_YYYYMMDD_HHMMSS_suffix` 的 ID。缺失的有效会话返回 `404`；非法 ID 由路径参数模式返回 `422`。

## 任务 1：后端复盘 API

**文件：**
- 创建：`apps/api/tests/test_games_api.py`
- 创建：`apps/api/app/werewolf/replay.py`
- 创建：`apps/api/app/api/routes/games.py`
- 修改：`apps/api/app/api/router.py`
- 修改：`apps/api/app/core/config.py`

- [ ] **步骤 1：编写预期失败的后端 API 测试**

创建 `apps/api/tests/test_games_api.py`：

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

- [ ] **步骤 2：运行后端测试并确认 RED**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py -q
```

预期：FAIL，因为 `app.api.routes.games` 和 `app.werewolf.replay` 还不存在。

- [ ] **步骤 3：实现复盘存储**

创建 `apps/api/app/werewolf/replay.py`：

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

- [ ] **步骤 4：添加配置和路由**

修改 `apps/api/app/core/config.py`，在 `Settings` 中添加设置：

```python
    werewolf_logs_dir: str = "logs"
```

创建 `apps/api/app/api/routes/games.py`：

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

修改 `apps/api/app/api/router.py`：

```python
from fastapi import APIRouter

from app.api.routes.games import router as games_router
from app.api.routes.health import router as health_router


api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(games_router, prefix="/games", tags=["games"])
```

- [ ] **步骤 5：运行后端测试并确认 GREEN**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py -q
```

预期：PASS。

- [ ] **步骤 6：提交后端 API**

运行：

```bash
git add apps/api/app/core/config.py apps/api/app/api/router.py apps/api/app/api/routes/games.py apps/api/app/werewolf/replay.py apps/api/tests/test_games_api.py
git commit -m "feat: add werewolf replay api"
```

## 任务 2：前端复盘类型和适配器

**文件：**
- 创建：`apps/web/src/features/games/types.ts`
- 创建：`apps/web/src/features/games/api/adapters.ts`
- 创建：`apps/web/src/features/games/api/adapters.test.ts`
- 创建：`apps/web/src/features/games/api/listGames.ts`
- 创建：`apps/web/src/features/games/api/getGameDetail.ts`

- [ ] **步骤 1：编写预期失败的适配器测试**

创建 `apps/web/src/features/games/api/adapters.test.ts`：

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

- [ ] **步骤 2：运行适配器测试并确认 RED**

运行：

```bash
cd apps/web && pnpm test -- --run src/features/games/api/adapters.test.ts
```

预期：FAIL，因为 games 适配器模块还不存在。

- [ ] **步骤 3：添加前端类型**

创建 `apps/web/src/features/games/types.ts`：

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

- [ ] **步骤 4：添加 API 函数和适配器**

创建 `apps/web/src/features/games/api/listGames.ts`：

```typescript
import { apiFetch } from "../../../api/client";
import type { GameSessionsResponse } from "../types";

export function listGames() {
  return apiFetch<GameSessionsResponse>("/api/v1/games");
}
```

创建 `apps/web/src/features/games/api/getGameDetail.ts`：

```typescript
import { apiFetch } from "../../../api/client";
import type { GameReplay, RawGameReplayResponse } from "../types";

import { normalizeGameReplay } from "./adapters";

export async function getGameDetail(sessionId: string): Promise<GameReplay> {
  const response = await apiFetch<RawGameReplayResponse>(`/api/v1/games/${sessionId}`);
  return normalizeGameReplay(response);
}
```

创建 `apps/web/src/features/games/api/adapters.ts`：

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

- [ ] **步骤 5：运行适配器测试并确认 GREEN**

运行：

```bash
cd apps/web && pnpm test -- --run src/features/games/api/adapters.test.ts
```

预期：PASS。

- [ ] **步骤 6：提交前端数据层**

运行：

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/api
git commit -m "feat: add werewolf replay data adapters"
```

## 任务 3：游戏列表页面

**文件：**
- 创建：`apps/web/src/tests/renderWithClient.tsx`
- 创建：`apps/web/src/features/games/components/SessionList.tsx`
- 创建：`apps/web/src/pages/GamesPage.tsx`
- 创建：`apps/web/src/pages/GamesPage.test.tsx`

- [ ] **步骤 1：添加测试渲染辅助工具**

创建 `apps/web/src/tests/renderWithClient.tsx`：

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

- [ ] **步骤 2：编写预期失败的 GamesPage 测试**

创建 `apps/web/src/pages/GamesPage.test.tsx`：

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

- [ ] **步骤 3：运行 GamesPage 测试并确认 RED**

运行：

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

预期：FAIL，因为 `GamesPage` 和 `SessionList` 还不存在。

- [ ] **步骤 4：实现会话列表页面**

创建 `apps/web/src/features/games/components/SessionList.tsx`：

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

创建 `apps/web/src/pages/GamesPage.tsx`：

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

- [ ] **步骤 5：运行 GamesPage 测试并确认 GREEN**

运行：

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

预期：PASS。

- [ ] **步骤 6：提交游戏列表页面**

运行：

```bash
git add apps/web/src/tests/renderWithClient.tsx apps/web/src/features/games/components/SessionList.tsx apps/web/src/pages/GamesPage.tsx apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat: add werewolf games list page"
```

## 任务 4：复盘详情组件和调试面板

**文件：**
- 创建：`apps/web/src/features/games/components/ActionCard.tsx`
- 创建：`apps/web/src/features/games/components/BidChart.tsx`
- 创建：`apps/web/src/features/games/components/DebugPanel.tsx`
- 创建：`apps/web/src/features/games/components/DayPhase.tsx`
- 创建：`apps/web/src/features/games/components/GameLayout.tsx`
- 创建：`apps/web/src/features/games/components/NightPhase.tsx`
- 创建：`apps/web/src/features/games/components/PlayerPanel.tsx`
- 创建：`apps/web/src/features/games/components/RoundTimeline.tsx`
- 创建：`apps/web/src/features/games/components/SummaryStrip.tsx`
- 创建：`apps/web/src/features/games/components/VoteTable.tsx`
- 创建：`apps/web/src/pages/GameDetailPage.tsx`
- 创建：`apps/web/src/pages/GameDetailPage.test.tsx`

- [ ] **步骤 1：编写预期失败的复盘交互测试**

创建 `apps/web/src/pages/GameDetailPage.test.tsx`：

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

- [ ] **步骤 2：运行复盘测试并确认 RED**

运行：

```bash
cd apps/web && pnpm test -- --run src/pages/GameDetailPage.test.tsx
```

预期：FAIL，因为详情页和组件还不存在。

- [ ] **步骤 3：实现布局、玩家面板和调试面板**

创建 `apps/web/src/features/games/components/GameLayout.tsx`：

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

创建 `apps/web/src/features/games/components/PlayerPanel.tsx`：

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

创建 `apps/web/src/features/games/components/DebugPanel.tsx`：

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

- [ ] **步骤 4：实现行动、阶段和时间线组件**

创建 `apps/web/src/features/games/components/ActionCard.tsx`：

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

创建 `apps/web/src/features/games/components/BidChart.tsx`：

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

创建 `apps/web/src/features/games/components/VoteTable.tsx`：

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

创建 `apps/web/src/features/games/components/SummaryStrip.tsx`：

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

创建 `apps/web/src/features/games/components/NightPhase.tsx`：

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

创建 `apps/web/src/features/games/components/DayPhase.tsx`：

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

创建 `apps/web/src/features/games/components/RoundTimeline.tsx`：

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

- [ ] **步骤 5：实现详情页**

创建 `apps/web/src/pages/GameDetailPage.tsx`：

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

- [ ] **步骤 6：运行复盘测试并确认 GREEN**

运行：

```bash
cd apps/web && pnpm test -- --run src/pages/GameDetailPage.test.tsx
```

预期：PASS。

- [ ] **步骤 7：提交复盘详情页**

运行：

```bash
git add apps/web/src/features/games/components apps/web/src/pages/GameDetailPage.tsx apps/web/src/pages/GameDetailPage.test.tsx
git commit -m "feat: add werewolf replay detail view"
```

## 任务 5：应用路由和冒烟测试

**文件：**
- 修改：`apps/web/src/routes/index.tsx`
- 修改：`apps/web/src/tests/app.test.tsx`

- [ ] **步骤 1：编写预期失败的应用路由测试**

将 `apps/web/src/tests/app.test.tsx` 替换为：

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

- [ ] **步骤 2：运行应用测试并确认 RED**

运行：

```bash
cd apps/web && pnpm test -- --run src/tests/app.test.tsx
```

预期：FAIL，因为 `/` 仍然渲染骨架首页。

- [ ] **步骤 3：接入路由**

修改 `apps/web/src/routes/index.tsx`：

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

- [ ] **步骤 4：运行应用测试并确认 GREEN**

运行：

```bash
cd apps/web && pnpm test -- --run src/tests/app.test.tsx
```

预期：PASS。

- [ ] **步骤 5：提交路由接入**

运行：

```bash
git add apps/web/src/routes/index.tsx apps/web/src/tests/app.test.tsx
git commit -m "feat: route app to werewolf replay workbench"
```

## 任务 6：完整验证和手动浏览器检查

**文件：**
- 不新增文件。
- 使用 `apps/api/logs` 下已有的生成日志；如果没有日志，则运行一次 CLI。

- [ ] **步骤 1：运行后端测试**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest
```

预期：PASS。

- [ ] **步骤 2：运行后端 lint**

运行：

```bash
cd apps/api && .venv/bin/ruff check .
```

预期：PASS。

- [ ] **步骤 3：运行前端测试**

运行：

```bash
npm run test:web
```

预期：PASS。

- [ ] **步骤 4：运行前端构建**

运行：

```bash
npm run build:web
```

预期：PASS。

- [ ] **步骤 5：启动后端和前端进行手动验证**

终端 A：

```bash
cd apps/api && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

终端 B：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 pnpm --dir apps/web dev --host 127.0.0.1 --port 5173
```

打开 `http://127.0.0.1:5173/games`。

预期手动检查：

- 会话列表可以加载，且不暴露文件路径。
- 完整对局可以打开，并展示玩家、胜利阵营、轮次数、夜晚阶段、白天阶段、投票和总结。
- 部分对局会在玩家面板中显示已存储的错误消息。
- 点击一条行动后，调试面板会更新并显示 prompt、raw response 和 parsed result。
- 在窄视口下，布局会堆叠成可读的面板。

- [ ] **步骤 6：提交验证过程中发现的小修复**

仅在手动检查需要小修复时运行：

```bash
git add apps/api apps/web
git commit -m "fix: polish werewolf replay workbench"
```

## 自查

- 规格覆盖：任务 1 创建只读后端 games API。任务 2 到任务 5 创建会话列表、复盘路由、玩家面板、轮次时间线、夜晚/白天阶段、投票、总结和可点击调试面板。任务 6 验证后端测试、前端测试、构建和浏览器行为。
- 占位内容扫描：本计划包含明确的文件路径、具体测试、代码块、命令和预期结果。
- 类型一致性：后端使用 `session_id`、`status`、`state` 和 `logs`；适配器将这些映射为 `sessionId`、`status`、`players`、`rounds` 和 `debugItems`；组件消费规范化后的类型。
- 范围检查：本计划保持只读，不添加 WebSockets、登录、浏览器触发的模型运行，也不修改 DeepSeek 游戏执行逻辑。
