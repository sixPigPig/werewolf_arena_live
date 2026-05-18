# 实时直播导播节奏优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **2026-05-18 修订**: 本计划中后端 `event_pacing`、`EventPacer`、标准演示/慢速讲解延迟和创建对局页“演示慢速”控件已被新的前端-only 播放速度方案取代。后续实现请以 `docs/superpowers/specs/2026-05-18-frontend-only-live-playback-pacing-design.md` 为准。

**Goal:** 让实时直播页用前端导播队列按观赛节奏播放所有事件，并在创建对局时支持后端演示慢速模式。

**Architecture:** 前端保留 `useGameRunEvents()` 作为真实 SSE 事件源，新增纯函数 `toDirectorCue()` 和 `useLiveDirector()` 生成可播放导播队列；直播页主画面消费当前 cue，右侧原始事件列表仍显示完整事件。后端新增 `event_pacing` 运行参数和可注入 pacer，默认 `off` 不等待，演示模式只在后台对局执行路径中延迟事件推进。

**Tech Stack:** FastAPI、Pydantic、Python dataclass、React、TypeScript、TanStack Query、Vitest、React Testing Library、Pytest。

---

## 文件结构

- `apps/web/src/features/games/liveDirector.ts`
  - 新建。负责把 `LiveGameEvent` 转成 `DirectorCue`，计算标题、正文、重要级别、停留时长和是否可压缩。
- `apps/web/src/features/games/liveDirector.test.ts`
  - 新建。覆盖所有现有事件类型、长文本停留、未知事件降级。
- `apps/web/src/features/games/hooks/useLiveDirector.ts`
  - 新建。负责导播播放状态、暂停/继续、倍速、追到最新、积压压缩。
- `apps/web/src/features/games/hooks/useLiveDirector.test.tsx`
  - 新建。用 fake timers 验证播放推进和控制行为。
- `apps/web/src/features/games/components/LiveDirectorStage.tsx`
  - 新建。中间主画面，展示当前 cue、正文、回合阶段、演员、进度状态。
- `apps/web/src/features/games/components/LiveDirectorControls.tsx`
  - 新建。暂停/继续、追到最新、倍速切换、积压提示。
- `apps/web/src/features/games/components/LiveEventTimeline.tsx`
  - 修改。增加 `currentEventId` 可选 prop，高亮当前导播播放的原始事件。
- `apps/web/src/pages/LiveGamePage.tsx`
  - 修改。接入 `useLiveDirector()`，用导播主画面替换当前 `LiveFocusStage` 的中间位置。
- `apps/web/src/features/games/types.ts`
  - 修改。增加 `EventPacingMode`、`event_pacing` 字段。
- `apps/web/src/features/games/components/CreateGameRunForm.tsx`
  - 修改。增加演示慢速选择，提交 `event_pacing`。
- `apps/web/src/features/games/components/LiveStatusStrip.tsx`
  - 修改。展示演示慢速模式和队列状态入口文案。
- `apps/web/src/features/games/api/liveRunApi.test.ts`
  - 修改。覆盖 `event_pacing` 解析。
- `apps/web/src/pages/GamesPage.test.tsx`
  - 修改。覆盖创建对局时提交演示慢速。
- `apps/web/src/pages/LiveGamePage.test.tsx`
  - 修改。覆盖导播主画面、暂停/继续、追到最新、当前事件高亮。
- `apps/api/app/werewolf/pacing.py`
  - 新建。定义 pacing 模式、延迟策略和可注入 sleeper。
- `apps/api/tests/test_werewolf_pacing.py`
  - 新建。验证默认不等待、演示模式等待、非法模式拒绝。
- `apps/api/app/werewolf/live.py`
  - 修改。`LiveGameRun` 和 summary 增加 `event_pacing`。
- `apps/api/app/api/routes/games.py`
  - 修改。`CreateGameRunRequest` 增加 `event_pacing`，后台运行时注入 pacer。
- `apps/api/tests/test_live.py`
  - 修改。创建 run 的测试传入或断言默认 pacing。
- `apps/api/tests/test_games_api.py`
  - 修改。覆盖创建 run 接收、返回和拒绝 pacing。

## Task 1: 前端导播 cue 纯函数

**Files:**
- Create: `apps/web/src/features/games/liveDirector.ts`
- Create: `apps/web/src/features/games/liveDirector.test.ts`
- Modify: `apps/web/src/features/games/types.ts`

- [ ] **Step 1: 写失败测试**

创建 `apps/web/src/features/games/liveDirector.test.ts`：

```ts
import { describe, expect, it } from "vitest";

import { toDirectorCue } from "./liveDirector";
import type { LiveGameEvent } from "./types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "phase_started",
    run_id: "run_1234abcd",
    session_id: "session_20260424_120000_ab12cd34",
    created_at: "2026-04-26T08:00:00Z",
    round: partial.round ?? null,
    phase: partial.phase ?? null,
    actor: partial.actor ?? null,
    action: partial.action ?? null,
    payload: partial.payload ?? {},
  };
}

describe("toDirectorCue", () => {
  it("renders action request as a playable action cue", () => {
    const cue = toDirectorCue(
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: { options: ["李四"] },
      }),
    );

    expect(cue).toMatchObject({
      eventId: 2,
      title: "张三 准备 debate",
      body: "可选目标：李四",
      importance: "action",
      compressible: true,
    });
    expect(cue.durationMs).toBeGreaterThanOrEqual(2000);
  });

  it("keeps model responses readable for longer", () => {
    const cue = toDirectorCue(
      event({
        id: 3,
        type: "model_response_received",
        actor: "张三",
        action: "debate",
        payload: { raw_response: "我不是狼人，我建议今天先听李四发言。" },
      }),
    );

    expect(cue.title).toBe("张三 的模型返回");
    expect(cue.body).toContain("我不是狼人");
    expect(cue.importance).toBe("key");
    expect(cue.compressible).toBe(false);
    expect(cue.durationMs).toBeGreaterThanOrEqual(6000);
  });

  it("renders state updates for debate, votes, exile and winner", () => {
    expect(
      toDirectorCue(
        event({
          type: "state_updated",
          actor: "李四",
          action: "debate",
          payload: {
            debate_entry: { speaker: "李四", message: "张三的发言很可疑。" },
          },
        }),
      ).body,
    ).toBe("李四：张三的发言很可疑。");

    expect(
      toDirectorCue(
        event({
          type: "state_updated",
          phase: "vote",
          action: "vote",
          payload: { votes: { 张三: "李四", 李四: "张三" } },
        }),
      ).body,
    ).toBe("张三 -> 李四\n李四 -> 张三");

    expect(
      toDirectorCue(
        event({
          type: "state_updated",
          payload: { exiled: "王五", active_players: ["张三", "李四"] },
        }),
      ).title,
    ).toBe("王五 被放逐");

    expect(
      toDirectorCue(
        event({
          type: "game_completed",
          payload: { winner: "好人阵营" },
        }),
      ),
    ).toMatchObject({
      title: "对局完成",
      body: "胜利阵营：好人阵营",
      importance: "terminal",
      compressible: false,
    });
  });

  it("falls back safely for unknown or malformed events", () => {
    const cue = toDirectorCue(
      event({
        type: "custom_diagnostic",
        payload: { note: "debug value", count: 2 },
      }),
    );

    expect(cue.title).toBe("custom_diagnostic");
    expect(cue.body).toContain("debug value");
    expect(cue.importance).toBe("normal");
    expect(cue.compressible).toBe(true);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- liveDirector.test.ts --run
```

Expected: FAIL，错误包含 `Failed to resolve import "./liveDirector"` 或 `toDirectorCue` 未定义。

- [ ] **Step 3: 增加类型和实现**

在 `apps/web/src/features/games/types.ts` 末尾新增：

```ts
export type EventPacingMode = "off" | "standard" | "slow";
```

创建 `apps/web/src/features/games/liveDirector.ts`：

```ts
import type { LiveGameEvent } from "./types";

export type DirectorCueImportance = "normal" | "action" | "key" | "terminal";

export type DirectorCue = {
  eventId: number;
  type: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  title: string;
  body: string;
  importance: DirectorCueImportance;
  durationMs: number;
  compressible: boolean;
};

const MIN_DURATION_MS = 500;
const MAX_LONG_TEXT_DURATION_MS = 10000;

export function toDirectorCue(event: LiveGameEvent): DirectorCue {
  const payload = payloadForEvent(event);
  const base = cueBase(event);

  if (event.type === "run_created") {
    return { ...base, title: "对局已创建", body: stringField(payload, "session_id"), durationMs: 2000 };
  }
  if (event.type === "run_started") {
    return { ...base, title: "对局开始运行", durationMs: 2000 };
  }
  if (event.type === "game_started") {
    return {
      ...base,
      title: "玩家入场",
      body: playersBody(payload),
      importance: "key",
      durationMs: 5000,
      compressible: false,
    };
  }
  if (event.type === "round_started") {
    return {
      ...base,
      title: event.round ? `第 ${event.round} 轮开始` : "新回合开始",
      body: activePlayersBody(payload),
      durationMs: 2000,
    };
  }
  if (event.type === "phase_started") {
    return {
      ...base,
      title: `进入${phaseLabel(event.phase)}阶段`,
      body: activePlayersBody(payload),
      durationMs: 2000,
    };
  }
  if (event.type === "action_requested") {
    return {
      ...base,
      title: `${event.actor ?? "玩家"} 准备 ${event.action ?? "行动"}`,
      body: optionsBody(payload),
      importance: "action",
      durationMs: 2500,
      compressible: true,
    };
  }
  if (event.type === "model_request_started") {
    return {
      ...base,
      title: `${event.actor ?? "玩家"} 正在请求模型`,
      body: stringField(payload, "model"),
      importance: "action",
      durationMs: 2500,
      compressible: true,
    };
  }
  if (event.type === "model_response_received") {
    const body = stringField(payload, "raw_response");
    return {
      ...base,
      title: `${event.actor ?? "玩家"} 的模型返回`,
      body,
      importance: "key",
      durationMs: longTextDuration(body),
      compressible: false,
    };
  }
  if (event.type === "action_parsed") {
    return {
      ...base,
      title: "行动解析完成",
      body: parsedActionBody(payload),
      importance: "action",
      durationMs: 3500,
      compressible: true,
    };
  }
  if (event.type === "state_updated") {
    return stateUpdatedCue(event, payload, base);
  }
  if (event.type === "game_completed") {
    return {
      ...base,
      title: "对局完成",
      body: winnerBody(payload),
      importance: "terminal",
      durationMs: 8000,
      compressible: false,
    };
  }
  if (event.type === "game_failed") {
    return {
      ...base,
      title: "对局失败",
      body: stringField(payload, "error"),
      importance: "terminal",
      durationMs: 8000,
      compressible: false,
    };
  }

  return {
    ...base,
    title: event.type,
    body: readablePayload(payload),
    durationMs: 2000,
  };
}

function cueBase(event: LiveGameEvent): DirectorCue {
  return {
    eventId: event.id,
    type: event.type,
    round: event.round,
    phase: event.phase,
    actor: event.actor,
    action: event.action,
    title: event.type,
    body: "",
    importance: "normal",
    durationMs: 2000,
    compressible: true,
  };
}

function stateUpdatedCue(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
  base: DirectorCue,
): DirectorCue {
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    const message = typeof debateEntry.message === "string" ? debateEntry.message : "";
    return {
      ...base,
      title: `${debateEntry.speaker} 发言`,
      body: `${debateEntry.speaker}：${message}`,
      importance: "key",
      durationMs: longTextDuration(message),
      compressible: false,
    };
  }

  const votes = payload.votes;
  if (isRecord(votes)) {
    return {
      ...base,
      title: "投票结果更新",
      body: Object.entries(votes).map(([voter, target]) => `${voter} -> ${String(target)}`).join("\n"),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return {
      ...base,
      title: `${exiled} 被放逐`,
      body: activePlayersBody(payload),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const eliminated = stringField(payload, "eliminated");
  if (eliminated) {
    return {
      ...base,
      title: `${eliminated} 夜晚出局`,
      body: activePlayersBody(payload),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  return {
    ...base,
    title: `${phaseLabel(event.phase)}状态更新`,
    body: readablePayload(payload),
    importance: "action",
    durationMs: 3500,
  };
}

function longTextDuration(text: string): number {
  if (!text) {
    return 6000;
  }
  const estimated = 6000 + Math.min(4000, Math.floor(text.length / 30) * 1000);
  return Math.min(MAX_LONG_TEXT_DURATION_MS, Math.max(6000, estimated));
}

function optionsBody(payload: Record<string, unknown>): string {
  const options = payload.options;
  if (!Array.isArray(options) || options.length === 0) {
    return "";
  }
  return `可选目标：${options.map(String).join("、")}`;
}

function parsedActionBody(payload: Record<string, unknown>): string {
  const choice = stringField(payload, "choice");
  const result = payload.result;
  if (choice) {
    return `选择：${choice}`;
  }
  if (isRecord(result)) {
    return readablePayload(result);
  }
  return "";
}

function playersBody(payload: Record<string, unknown>): string {
  const players = payload.players;
  if (!Array.isArray(players)) {
    return "";
  }
  return players
    .filter(isRecord)
    .map((player) => `${String(player.name ?? "未知")}（${String(player.role ?? "未知")}）`)
    .join("、");
}

function activePlayersBody(payload: Record<string, unknown>): string {
  const activePlayers = payload.active_players;
  if (!Array.isArray(activePlayers) || activePlayers.length === 0) {
    return "";
  }
  return `存活玩家：${activePlayers.map(String).join("、")}`;
}

function winnerBody(payload: Record<string, unknown>): string {
  const winner = stringField(payload, "winner");
  return winner ? `胜利阵营：${winner}` : "";
}

function phaseLabel(phase: string | null): string {
  if (phase === "night") return "夜晚";
  if (phase === "day") return "白天发言";
  if (phase === "vote") return "投票";
  if (phase === "summary") return "总结";
  return phase ?? "当前";
}

function stringField(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function readablePayload(payload: Record<string, unknown>): string {
  const values = Object.entries(payload)
    .filter(([, value]) => typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    .map(([key, value]) => `${key}: ${String(value)}`);
  return values.join("\n");
}

function payloadForEvent(event: LiveGameEvent): Record<string, unknown> {
  return isRecord(event.payload) ? event.payload : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
pnpm --dir apps/web test -- liveDirector.test.ts --run
```

Expected: PASS，`liveDirector.test.ts` 全部通过。

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/liveDirector.ts apps/web/src/features/games/liveDirector.test.ts
git commit -m "feat(web): add live director cue mapping"
```

## Task 2: 前端导播播放 hook

**Files:**
- Create: `apps/web/src/features/games/hooks/useLiveDirector.ts`
- Create: `apps/web/src/features/games/hooks/useLiveDirector.test.tsx`

- [ ] **Step 1: 写失败测试**

创建 `apps/web/src/features/games/hooks/useLiveDirector.test.tsx`：

```ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveDirector } from "./useLiveDirector";
import type { LiveGameEvent } from "../types";

function event(id: number, type = "phase_started"): LiveGameEvent {
  return {
    id,
    type,
    run_id: "run_1234abcd",
    session_id: "session_20260424_120000_ab12cd34",
    created_at: "2026-04-26T08:00:00Z",
    round: 1,
    phase: "day",
    actor: type === "phase_started" ? null : "张三",
    action: type === "phase_started" ? null : "debate",
    payload:
      type === "model_response_received"
        ? { raw_response: "这是一段较长的模型回答。" }
        : {},
  };
}

describe("useLiveDirector", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("plays events in order instead of jumping to the latest event", () => {
    const { result, rerender } = renderHook(
      ({ events }: { events: LiveGameEvent[] }) => useLiveDirector(events),
      { initialProps: { events: [event(1), event(2, "model_response_received")] } },
    );

    expect(result.current.currentCue?.eventId).toBe(1);
    rerender({ events: [event(1), event(2, "model_response_received"), event(3)] });
    expect(result.current.currentCue?.eventId).toBe(1);

    act(() => {
      vi.advanceTimersByTime(result.current.currentCue?.durationMs ?? 0);
    });

    expect(result.current.currentCue?.eventId).toBe(2);
    expect(result.current.backlogCount).toBe(1);
  });

  it("pauses and resumes playback without dropping received events", () => {
    const { result, rerender } = renderHook(
      ({ events }: { events: LiveGameEvent[] }) => useLiveDirector(events),
      { initialProps: { events: [event(1), event(2)] } },
    );

    act(() => result.current.pause());
    expect(result.current.isPaused).toBe(true);
    rerender({ events: [event(1), event(2), event(3)] });

    act(() => {
      vi.advanceTimersByTime(10000);
    });

    expect(result.current.currentCue?.eventId).toBe(1);
    expect(result.current.backlogCount).toBe(2);

    act(() => result.current.resume());
    act(() => {
      vi.advanceTimersByTime(result.current.currentCue?.durationMs ?? 0);
    });

    expect(result.current.currentCue?.eventId).toBe(2);
  });

  it("catches up by skipping compressible events and landing on the latest key event", () => {
    const { result } = renderHook(() =>
      useLiveDirector([
        event(1),
        event(2),
        event(3, "model_response_received"),
        event(4),
      ]),
    );

    act(() => result.current.catchUpToLatest());

    expect(result.current.currentCue?.eventId).toBe(3);
    expect(result.current.backlogCount).toBe(1);
  });

  it("compresses normal cue duration when backlog is high", () => {
    const events = Array.from({ length: 12 }, (_, index) => event(index + 1));
    const { result } = renderHook(() => useLiveDirector(events));

    expect(result.current.isCatchingUp).toBe(true);
    expect(result.current.effectiveDurationMs).toBeLessThan(result.current.currentCue!.durationMs);
    expect(result.current.effectiveDurationMs).toBeGreaterThanOrEqual(500);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- useLiveDirector.test.tsx --run
```

Expected: FAIL，错误包含 `Failed to resolve import "./useLiveDirector"`。

- [ ] **Step 3: 实现 hook**

创建 `apps/web/src/features/games/hooks/useLiveDirector.ts`：

```ts
import { useCallback, useEffect, useMemo, useState } from "react";

import { type DirectorCue, toDirectorCue } from "../liveDirector";
import type { LiveGameEvent } from "../types";

type PlaybackSpeed = 1 | 1.5;

const BACKLOG_THRESHOLD = 8;
const MIN_COMPRESSED_DURATION_MS = 500;

export function useLiveDirector(events: LiveGameEvent[]) {
  const cues = useMemo(() => events.map(toDirectorCue), [events]);
  const [currentEventId, setCurrentEventId] = useState<number | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);

  useEffect(() => {
    if (currentEventId !== null || cues.length === 0) {
      return;
    }
    setCurrentEventId(cues[0].eventId);
  }, [cues, currentEventId]);

  const currentIndex = cues.findIndex((cue) => cue.eventId === currentEventId);
  const currentCue = currentIndex >= 0 ? cues[currentIndex] : null;
  const backlogCount = currentIndex >= 0 ? Math.max(0, cues.length - currentIndex - 1) : cues.length;
  const isCatchingUp = backlogCount >= BACKLOG_THRESHOLD;
  const effectiveDurationMs = currentCue
    ? durationForCue(currentCue, { isCatchingUp, speed })
    : 0;

  const advance = useCallback(() => {
    setCurrentEventId((eventId) => {
      if (eventId === null) {
        return cues[0]?.eventId ?? null;
      }
      const index = cues.findIndex((cue) => cue.eventId === eventId);
      const next = cues[index + 1];
      return next ? next.eventId : eventId;
    });
  }, [cues]);

  useEffect(() => {
    if (!currentCue || isPaused) {
      return;
    }
    const timeout = window.setTimeout(advance, effectiveDurationMs);
    return () => window.clearTimeout(timeout);
  }, [advance, currentCue, effectiveDurationMs, isPaused]);

  const catchUpToLatest = useCallback(() => {
    setCurrentEventId((eventId) => {
      if (cues.length === 0) {
        return null;
      }
      const currentIndex = cues.findIndex((cue) => cue.eventId === eventId);
      const remaining = currentIndex >= 0 ? cues.slice(currentIndex + 1) : cues;
      const latestKey = [...remaining].reverse().find((cue) => !cue.compressible);
      return latestKey?.eventId ?? cues.at(-1)!.eventId;
    });
  }, [cues]);

  return {
    cues,
    currentCue,
    currentEventId,
    backlogCount,
    isCatchingUp,
    isPaused,
    speed,
    effectiveDurationMs,
    pause: () => setIsPaused(true),
    resume: () => setIsPaused(false),
    togglePaused: () => setIsPaused((value) => !value),
    setSpeed,
    advance,
    catchUpToLatest,
  };
}

function durationForCue(
  cue: DirectorCue,
  { isCatchingUp, speed }: { isCatchingUp: boolean; speed: PlaybackSpeed },
) {
  const compressed =
    isCatchingUp && cue.compressible
      ? Math.min(cue.durationMs, MIN_COMPRESSED_DURATION_MS)
      : cue.durationMs;
  return Math.max(MIN_COMPRESSED_DURATION_MS, Math.round(compressed / speed));
}
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
pnpm --dir apps/web test -- useLiveDirector.test.tsx --run
```

Expected: PASS，`useLiveDirector.test.tsx` 全部通过。

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/features/games/hooks/useLiveDirector.ts apps/web/src/features/games/hooks/useLiveDirector.test.tsx
git commit -m "feat(web): add live director playback hook"
```

## Task 3: 直播页接入导播主画面

**Files:**
- Create: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Create: `apps/web/src/features/games/components/LiveDirectorControls.tsx`
- Modify: `apps/web/src/features/games/components/LiveEventTimeline.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写失败测试**

在 `apps/web/src/pages/LiveGamePage.test.tsx` 新增测试：

```ts
it("plays the live director stage at readable pace and highlights the current event", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", MockEventSource);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        villager_model: "deepseek-chat",
        werewolf_model: "deepseek-chat",
        seed: null,
        max_rounds: 8,
        event_pacing: "off",
        status: "running",
        created_at: "2026-04-24T12:00:00Z",
        started_at: "2026-04-24T12:00:01Z",
        completed_at: null,
        winner: null,
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
  act(() => {
    source.emit("phase_started", {
      id: 1,
      type: "phase_started",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:02Z",
      round: 1,
      phase: "day",
      actor: null,
      action: null,
      payload: { active_players: ["张三", "李四"] },
    });
    source.emit("model_response_received", {
      id: 2,
      type: "model_response_received",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:03Z",
      round: 1,
      phase: "day",
      actor: "张三",
      action: "debate",
      payload: { raw_response: "我不是狼人，我建议先观察李四。" },
    });
  });

  expect(await screen.findByRole("heading", { name: "进入白天发言阶段" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "张三 的模型返回" })).not.toBeInTheDocument();
  expect(screen.getByText("当前播放")).toBeInTheDocument();

  act(() => {
    vi.advanceTimersByTime(2000);
  });

  expect(await screen.findByRole("heading", { name: "张三 的模型返回" })).toBeInTheDocument();
  expect(screen.getByText("我不是狼人，我建议先观察李四。")).toBeInTheDocument();
  vi.useRealTimers();
});
```

在同一文件新增控制测试：

```ts
it("lets users pause and catch up the director playback", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", MockEventSource);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        villager_model: "deepseek-chat",
        werewolf_model: "deepseek-chat",
        seed: null,
        max_rounds: 8,
        event_pacing: "off",
        status: "running",
        created_at: "2026-04-24T12:00:00Z",
        started_at: "2026-04-24T12:00:01Z",
        completed_at: null,
        winner: null,
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
  act(() => {
    source.emit("phase_started", {
      id: 1,
      type: "phase_started",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:02Z",
      round: 1,
      phase: "day",
      actor: null,
      action: null,
      payload: {},
    });
    source.emit("game_completed", {
      id: 2,
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
  });

  await userEvent.click(screen.getByRole("button", { name: "暂停" }));
  act(() => {
    vi.advanceTimersByTime(5000);
  });
  expect(screen.getByRole("heading", { name: "进入白天发言阶段" })).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "追到最新" }));
  expect(await screen.findByRole("heading", { name: "对局完成" })).toBeInTheDocument();
  vi.useRealTimers();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- LiveGamePage.test.tsx --run
```

Expected: FAIL，找不到“当前播放”“暂停”“追到最新”或导播标题。

- [ ] **Step 3: 新增导播组件**

创建 `apps/web/src/features/games/components/LiveDirectorStage.tsx`：

```tsx
import type { DirectorCue } from "../liveDirector";

type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
};

export function LiveDirectorStage({
  cue,
  backlogCount,
  isCatchingUp,
}: LiveDirectorStageProps) {
  if (!cue) {
    return (
      <section className="min-h-80 rounded-md border border-slate-200 bg-white p-6">
        <p className="text-sm text-slate-600">等待导播事件...</p>
      </section>
    );
  }

  return (
    <section className="min-h-80 rounded-md border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-slate-500">当前播放</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">
              {cue.title}
            </h2>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-slate-600">
            {cue.round ? <span>第 {cue.round} 轮</span> : null}
            {cue.phase ? <span>{cue.phase}</span> : null}
            {cue.actor ? <span>{cue.actor}</span> : null}
          </div>
        </div>
      </div>
      <div className="space-y-4 px-5 py-5">
        {cue.body ? (
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-100 p-4 text-sm leading-6 text-slate-800">
            {cue.body}
          </pre>
        ) : (
          <p className="rounded-md bg-slate-50 p-4 text-sm text-slate-600">
            这条事件没有额外正文。
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>事件 #{cue.eventId}</span>
          <span>{cue.type}</span>
          <span>队列剩余 {backlogCount} 条</span>
          {isCatchingUp ? <span className="text-amber-700">自动追进度中</span> : null}
        </div>
      </div>
    </section>
  );
}
```

创建 `apps/web/src/features/games/components/LiveDirectorControls.tsx`：

```tsx
type LiveDirectorControlsProps = {
  isPaused: boolean;
  speed: 1 | 1.5;
  backlogCount: number;
  isCatchingUp: boolean;
  onTogglePaused: () => void;
  onCatchUp: () => void;
  onSpeedChange: (speed: 1 | 1.5) => void;
};

export function LiveDirectorControls({
  isPaused,
  speed,
  backlogCount,
  isCatchingUp,
  onTogglePaused,
  onCatchUp,
  onSpeedChange,
}: LiveDirectorControlsProps) {
  return (
    <section className="rounded-md border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="rounded-md bg-slate-950 px-3 py-1.5 text-sm font-medium text-white"
          type="button"
          onClick={onTogglePaused}
        >
          {isPaused ? "继续" : "暂停"}
        </button>
        <button
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700"
          type="button"
          onClick={onCatchUp}
        >
          追到最新
        </button>
        <button
          className={`rounded-md border px-3 py-1.5 text-sm font-medium ${
            speed === 1 ? "border-slate-950 text-slate-950" : "border-slate-300 text-slate-700"
          }`}
          type="button"
          onClick={() => onSpeedChange(1)}
        >
          1x
        </button>
        <button
          className={`rounded-md border px-3 py-1.5 text-sm font-medium ${
            speed === 1.5 ? "border-slate-950 text-slate-950" : "border-slate-300 text-slate-700"
          }`}
          type="button"
          onClick={() => onSpeedChange(1.5)}
        >
          1.5x
        </button>
        <span className="text-xs text-slate-500">
          {isCatchingUp ? "自动追进度" : "观赛节奏"} · 队列 {backlogCount} 条
        </span>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: 时间线高亮当前事件**

修改 `apps/web/src/features/games/components/LiveEventTimeline.tsx` 的 props 和 `li` class：

```tsx
export function LiveEventTimeline({
  events,
  currentEventId,
}: {
  events: LiveGameEvent[];
  currentEventId?: number | null;
}) {
  if (events.length === 0) {
    return <p className="p-4 text-sm text-slate-600">等待实时事件...</p>;
  }

  return (
    <ol className="divide-y divide-slate-200">
      {events.map((event) => {
        const detail = detailForEvent(event);
        const isCurrent = event.id === currentEventId;

        return (
          <li
            className={`px-4 py-3 ${isCurrent ? "bg-slate-100 ring-1 ring-inset ring-slate-300" : ""}`}
            key={event.id}
          >
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-950">
                {titleForEvent(event)}
              </p>
              <p className="text-xs text-slate-500">
                {event.round ? `第 ${event.round} 轮` : event.type}
              </p>
            </div>
            {detail ? (
              <pre className="mt-2 overflow-auto rounded-md bg-slate-100 p-2 text-xs text-slate-700">
                {detail}
              </pre>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
```

- [ ] **Step 5: 接入 LiveGamePage**

修改 `apps/web/src/pages/LiveGamePage.tsx`：

```tsx
import { LiveDirectorControls } from "../features/games/components/LiveDirectorControls";
import { LiveDirectorStage } from "../features/games/components/LiveDirectorStage";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
```

在 `events` 后新增：

```tsx
const director = useLiveDirector(events);
```

用当前 cue actor 驱动自动跟随：

```tsx
const displayedActorName = director.currentCue?.actor ?? spectatorState.activePlayerName;
const focusedPlayerName = autoFollow
  ? displayedActorName
  : manualFocusName ?? displayedActorName;
```

替换中间 `LiveFocusStage`：

```tsx
<div className="space-y-3">
  <LiveDirectorStage
    cue={director.currentCue}
    backlogCount={director.backlogCount}
    isCatchingUp={director.isCatchingUp}
  />
  <LiveDirectorControls
    isPaused={director.isPaused}
    speed={director.speed}
    backlogCount={director.backlogCount}
    isCatchingUp={director.isCatchingUp}
    onTogglePaused={director.togglePaused}
    onCatchUp={director.catchUpToLatest}
    onSpeedChange={director.setSpeed}
  />
</div>
```

给原始事件列表传当前事件：

```tsx
<LiveEventTimeline events={events} currentEventId={director.currentEventId} />
```

- [ ] **Step 6: 运行页面测试确认通过**

Run:

```bash
pnpm --dir apps/web test -- LiveGamePage.test.tsx --run
```

Expected: PASS，`LiveGamePage.test.tsx` 全部通过。

- [ ] **Step 7: 提交**

```bash
git add apps/web/src/features/games/components/LiveDirectorStage.tsx apps/web/src/features/games/components/LiveDirectorControls.tsx apps/web/src/features/games/components/LiveEventTimeline.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat(web): add live director stage"
```

## Task 4: 后端 pacing 模型和运行摘要

**Files:**
- Create: `apps/api/app/werewolf/pacing.py`
- Create: `apps/api/tests/test_werewolf_pacing.py`
- Modify: `apps/api/app/werewolf/live.py`
- Modify: `apps/api/tests/test_live.py`

- [ ] **Step 1: 写失败测试**

创建 `apps/api/tests/test_werewolf_pacing.py`：

```python
from app.werewolf.pacing import EventPacer, validate_event_pacing


def test_validate_event_pacing_accepts_supported_modes() -> None:
    assert validate_event_pacing("off") == "off"
    assert validate_event_pacing("standard") == "standard"
    assert validate_event_pacing("slow") == "slow"


def test_validate_event_pacing_rejects_unknown_mode() -> None:
    try:
        validate_event_pacing("turbo")
    except ValueError as exc:
        assert str(exc) == "Unsupported event pacing mode: turbo"
    else:
        raise AssertionError("Expected invalid pacing mode to raise")


def test_off_pacer_does_not_sleep() -> None:
    calls: list[float] = []
    pacer = EventPacer("off", sleeper=calls.append)

    pacer.wait("model_response_received")

    assert calls == []


def test_standard_pacer_sleeps_for_key_events() -> None:
    calls: list[float] = []
    pacer = EventPacer("standard", sleeper=calls.append)

    pacer.wait("model_response_received")
    pacer.wait("phase_started")

    assert calls == [1.5, 1.0]


def test_slow_pacer_uses_longer_delays() -> None:
    calls: list[float] = []
    pacer = EventPacer("slow", sleeper=calls.append)

    pacer.wait("game_completed")

    assert calls == [4.0]
```

在 `apps/api/tests/test_live.py` 增加断言：

```python
def test_registry_includes_event_pacing_in_summary() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        event_pacing="standard",
        **classic_rule_kwargs(),
    )

    assert run.to_summary()["event_pacing"] == "standard"
    assert run.events[0].payload["event_pacing"] == "standard"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_pacing.py tests/test_live.py -q
```

Expected: FAIL，`app.werewolf.pacing` 不存在或 `create_run()` 不接受 `event_pacing`。

- [ ] **Step 3: 实现 pacing 模型**

创建 `apps/api/app/werewolf/pacing.py`：

```python
from __future__ import annotations

import time
from typing import Callable, Literal

EventPacingMode = Literal["off", "standard", "slow"]

SUPPORTED_EVENT_PACING: tuple[EventPacingMode, ...] = ("off", "standard", "slow")

STANDARD_DELAYS: dict[str, float] = {
    "phase_started": 1.0,
    "action_requested": 1.0,
    "model_response_received": 1.5,
    "action_parsed": 1.0,
    "state_updated": 1.5,
    "game_completed": 2.0,
    "game_failed": 2.0,
}

SLOW_DELAYS: dict[str, float] = {
    "phase_started": 3.0,
    "action_requested": 3.0,
    "model_response_received": 4.0,
    "action_parsed": 3.0,
    "state_updated": 4.0,
    "game_completed": 4.0,
    "game_failed": 4.0,
}


def validate_event_pacing(value: str) -> EventPacingMode:
    if value in SUPPORTED_EVENT_PACING:
        return value  # type: ignore[return-value]
    raise ValueError(f"Unsupported event pacing mode: {value}")


class EventPacer:
    def __init__(
        self,
        mode: EventPacingMode,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mode = mode
        self._sleeper = sleeper

    def wait(self, event_type: str) -> None:
        delay = self.delay_for(event_type)
        if delay > 0:
            self._sleeper(delay)

    def delay_for(self, event_type: str) -> float:
        if self.mode == "standard":
            return STANDARD_DELAYS.get(event_type, 0.0)
        if self.mode == "slow":
            return SLOW_DELAYS.get(event_type, 0.0)
        return 0.0
```

- [ ] **Step 4: 把 pacing 写入 LiveGameRun**

修改 `apps/api/app/werewolf/live.py`：

```python
from app.werewolf.pacing import EventPacingMode
```

在 `LiveGameRun` 中增加字段：

```python
event_pacing: EventPacingMode = "off"
```

在 `to_summary()` 返回中增加：

```python
"event_pacing": self.event_pacing,
```

在 `LiveRunRegistry.create_run()` 参数中增加：

```python
event_pacing: EventPacingMode = "off",
```

创建 `LiveGameRun` 时传入：

```python
event_pacing=event_pacing,
```

`run_created` payload 增加：

```python
"event_pacing": event_pacing,
```

- [ ] **Step 5: 运行后端相关测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_pacing.py tests/test_live.py -q
```

Expected: PASS，pacing 和 live registry 测试通过。

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/werewolf/pacing.py apps/api/app/werewolf/live.py apps/api/tests/test_werewolf_pacing.py apps/api/tests/test_live.py
git commit -m "feat(api): add live event pacing model"
```

## Task 5: 后端 API 和后台运行接入演示慢速

**Files:**
- Modify: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_games_api.py` 增加：

```python
def test_create_game_run_accepts_event_pacing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_live_registry(registry)
    started: list[dict[str, object]] = []

    class ImmediateThread:
        def __init__(self, *, target, kwargs, daemon):
            started.append({"target": target, "kwargs": kwargs, "daemon": daemon})

        def start(self) -> None:
            return None

    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    response = client.post(
        "/api/v1/games/runs",
        json={
            "rule_set_id": "classic_8",
            "max_rounds": 8,
            "event_pacing": "standard",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["event_pacing"] == "standard"
    assert started[0]["kwargs"]["event_pacing"] == "standard"


def test_create_game_run_rejects_unknown_event_pacing(client: TestClient) -> None:
    registry = LiveRunRegistry()
    override_live_registry(registry)

    response = client.post(
        "/api/v1/games/runs",
        json={"rule_set_id": "classic_8", "event_pacing": "turbo"},
    )

    assert response.status_code == 422
```

增加后台 pacer 注入测试：

```python
def test_background_run_uses_event_pacer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    rule = get_rule_set("classic_8")
    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id=rule.id,
        rule_set=rule_set_snapshot(rule),
        event_pacing="standard",
    )
    calls: list[str] = []

    class CapturingPacer:
        def __init__(self, mode):
            calls.append(f"mode:{mode}")

        def wait(self, event_type: str) -> None:
            calls.append(event_type)

    class Result:
        winner = "好人阵营"

    def fake_run_game(**kwargs):
        kwargs["event_sink"].publish("phase_started")
        return Result()

    monkeypatch.setattr("app.api.routes.games.EventPacer", CapturingPacer)
    monkeypatch.setattr("app.api.routes.games.run_game", fake_run_game)

    _run_game_in_background(
        run_id=run.run_id,
        registry=registry,
        session_id=run.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id=rule.id,
        event_pacing="standard",
    )

    assert "mode:standard" in calls
    assert "run_started" in calls
    assert "phase_started" in calls
    assert "game_completed" in calls
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py -q
```

Expected: FAIL，`event_pacing` 未被接受或 `_run_game_in_background()` 不接收该参数。

- [ ] **Step 3: 修改 API request 和后台参数**

在 `apps/api/app/api/routes/games.py` import 增加：

```python
from app.werewolf.pacing import EventPacer, EventPacingMode
```

修改 `CreateGameRunRequest`：

```python
class CreateGameRunRequest(BaseModel):
    villager_model: str = "deepseek-chat"
    werewolf_model: str = "deepseek-chat"
    seed: int | None = None
    max_rounds: int = Field(default=8, ge=1, le=20)
    rule_set_id: str = DEFAULT_RULE_SET_ID
    event_pacing: EventPacingMode = "off"
```

创建 run 时传入：

```python
event_pacing=request.event_pacing,
```

线程 kwargs 增加：

```python
"event_pacing": request.event_pacing,
```

修改 `_run_game_in_background()` 签名：

```python
event_pacing: EventPacingMode,
```

- [ ] **Step 4: 增加 paced sink**

在 `apps/api/app/api/routes/games.py` 中增加本地包装类：

```python
class PacedEventSink:
    def __init__(self, sink: EventSink, pacer: EventPacer) -> None:
        self._sink = sink
        self._pacer = pacer

    def publish(self, event_type: str, **kwargs: object) -> LiveEvent:
        self._pacer.wait(event_type)
        return self._sink.publish(event_type, **kwargs)
```

在 `_run_game_in_background()` 中创建 pacer：

```python
pacer = EventPacer(event_pacing)
pacer.wait("run_started")
registry.mark_running(run_id)
```

传给 `run_game()`：

```python
event_sink=PacedEventSink(EventSink(registry, run_id), pacer),
```

完成和失败前等待：

```python
pacer.wait("game_failed")
registry.mark_failed(run_id, error=str(exc))
```

```python
pacer.wait("game_completed")
registry.mark_completed(run_id, winner=result.winner)
```

- [ ] **Step 5: 运行后端 API 测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py tests/test_werewolf_pacing.py tests/test_live.py -q
```

Expected: PASS，API、pacing、live tests 全部通过。

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/api/routes/games.py apps/api/tests/test_games_api.py
git commit -m "feat(api): support event pacing in live runs"
```

## Task 6: 前端创建表单和状态条接入 event_pacing

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Modify: `apps/web/src/features/games/components/LiveStatusStrip.tsx`
- Modify: `apps/web/src/features/games/api/liveRunApi.test.ts`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: 写失败测试**

在 `apps/web/src/pages/GamesPage.test.tsx` 的创建对局测试中新增对慢速模式的交互和断言：

```ts
await userEvent.selectOptions(screen.getByLabelText("演示慢速"), "standard");
```

断言请求体：

```ts
expect(JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body))).toMatchObject({
  rule_set_id: "classic_8",
  max_rounds: 8,
  event_pacing: "standard",
});
```

在 `apps/web/src/features/games/api/liveRunApi.test.ts` 中给 run 响应增加并断言：

```ts
event_pacing: "slow",
```

```ts
expect(run.event_pacing).toBe("slow");
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- GamesPage.test.tsx liveRunApi.test.ts --run
```

Expected: FAIL，找不到“演示慢速”控件或 `event_pacing` 未提交。

- [ ] **Step 3: 更新前端类型**

修改 `apps/web/src/features/games/types.ts`：

```ts
export type EventPacingMode = "off" | "standard" | "slow";
```

在 `GameRun` 增加：

```ts
event_pacing: EventPacingMode;
```

在 `CreateGameRunRequest` 增加：

```ts
event_pacing?: EventPacingMode;
```

- [ ] **Step 4: 更新创建表单**

修改 `apps/web/src/features/games/components/CreateGameRunForm.tsx`：

```tsx
const [eventPacing, setEventPacing] = useState<EventPacingMode>("off");
```

提交时增加：

```tsx
event_pacing: eventPacing,
```

在参数区加入选择器：

```tsx
<label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
  演示慢速
  <select
    className="rounded-md border border-slate-300 px-3 py-2 text-sm"
    value={eventPacing}
    onChange={(event) => setEventPacing(event.target.value as EventPacingMode)}
  >
    <option value="off">关闭</option>
    <option value="standard">标准演示</option>
    <option value="slow">慢速讲解</option>
  </select>
</label>
```

- [ ] **Step 5: 更新状态条**

修改 `apps/web/src/features/games/components/LiveStatusStrip.tsx`：

```tsx
const PACING_LABELS: Record<string, string> = {
  off: "快速执行",
  standard: "标准演示",
  slow: "慢速讲解",
};
```

在状态条中展示：

```tsx
<span className="text-slate-500">
  节奏：{PACING_LABELS[run.event_pacing] ?? "快速执行"}
</span>
```

- [ ] **Step 6: 运行前端相关测试确认通过**

Run:

```bash
pnpm --dir apps/web test -- GamesPage.test.tsx liveRunApi.test.ts LiveGamePage.test.tsx --run
```

Expected: PASS，创建、API、直播页测试通过。

- [ ] **Step 7: 提交**

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/features/games/components/LiveStatusStrip.tsx apps/web/src/features/games/api/liveRunApi.test.ts apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat(web): expose event pacing controls"
```

## Task 7: 全量验证和体验校准

**Files:**
- Modify only if verification finds real failures in files touched by Tasks 1-6.

- [ ] **Step 1: 运行后端全量测试**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest -v
```

Expected: PASS，所有 pytest 测试通过。

- [ ] **Step 2: 运行前端全量测试**

Run:

```bash
pnpm --dir apps/web test -- --run
```

Expected: PASS，所有 Vitest 测试通过。

- [ ] **Step 3: 运行前端构建**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS，TypeScript 和 Vite build 成功。

- [ ] **Step 4: 人工体验检查**

启动本地服务：

```bash
make api
make web
```

在浏览器检查：

- `/games` 创建对局表单有“演示慢速”选择。
- 默认 `关闭` 创建对局后，直播主画面从第一条事件开始播放，不会立即跳到最后一条。
- 点击“暂停”后，主画面停住，右侧原始事件继续追加。
- 点击“继续”后，主画面继续播放下一条 cue。
- 点击“追到最新”后，主画面停在最近关键事件或最新事件。
- 右侧原始事件列表中当前播放事件有高亮。
- 创建 `标准演示` 对局后，状态条展示 `节奏：标准演示`。

- [ ] **Step 5: 修复验证发现的问题**

如果测试或人工检查失败，只修改与失败直接相关的文件。每个修复必须先补测试，再改实现。

- [ ] **Step 6: 最终提交**

如果 Step 5 有修复：

```bash
git add apps/api/app/api/routes/games.py apps/api/app/werewolf/live.py apps/api/app/werewolf/pacing.py apps/api/tests/test_games_api.py apps/api/tests/test_live.py apps/api/tests/test_werewolf_pacing.py apps/web/src/features/games apps/web/src/pages
git commit -m "fix: polish live director pacing"
```

如果 Step 5 没有修复，不创建空提交。

## 自审记录

- 规格覆盖：
  - 前端导播队列：Task 1、Task 2、Task 3。
  - 主画面播放所有事件：Task 1 保证每个事件生成 cue，Task 3 接入主画面。
  - 观赛节奏和积压追进度：Task 2。
  - 暂停、继续、追到最新、倍速：Task 2、Task 3。
  - 原始事件列表保留和当前事件高亮：Task 3。
  - 后端演示慢速：Task 4、Task 5、Task 6。
  - 默认兼容：Task 4 和 Task 5 的默认 `off`。
- 占位符扫描：
  - 本计划已扫描常见占位词和含糊执行语句。
- 类型一致性：
  - 前后端 pacing mode 使用 `off | standard | slow`。
  - 前端 `DirectorCue.eventId` 对应 `LiveGameEvent.id`。
  - API 字段统一为 `event_pacing`。
