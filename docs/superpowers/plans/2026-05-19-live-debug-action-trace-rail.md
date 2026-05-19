# 观战页 Action Trace Rail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把观战页右侧“调试事件”从 raw event list 升级为按行动聚合的 Action Trace Rail，能直观看清 request、model、parsed、state、stage 的因果链。

**Architecture:** 新增纯前端派生层 `liveDebugTrace.ts`，把 `LiveGameEvent[]` 转成 `LiveDebugTrace[]`。新增 `LiveDebugTraceRail` 组件负责右侧轨道、异常过滤和展开详情；`LiveStageExperience` 管理选中 trace，并把高亮玩家传给 `LiveDirectorStage`。第一版不改后端协议，不新增依赖。

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, Tailwind utilities, existing gothic/glass UI primitives.

---

## File Structure

- Create: `apps/web/src/features/games/liveDebugTrace.ts`
  - Owns `LiveDebugTrace` types and `buildLiveDebugTraces(events)` pure derivation.
  - Contains small helpers for payload reading, node status, impact summaries, warnings, and related players.

- Create: `apps/web/src/features/games/liveDebugTrace.test.ts`
  - Unit tests for event grouping, hidden stream events, warning/error status, system traces, and impact summaries.

- Create: `apps/web/src/features/games/components/LiveDebugTraceRail.tsx`
  - Renders trace list, issue filter, selected-card expansion, details sections, and player highlight callback.
  - Keeps UI local state for `showIssuesOnly`.

- Create: `apps/web/src/features/games/components/LiveDebugTraceRail.test.tsx`
  - Component tests for rendered trace cards, filter, expansion, and `onSelectTrace`.

- Modify: `apps/web/src/features/games/components/LiveStageExperience.tsx`
  - Builds traces with `useMemo`.
  - Owns `selectedTraceId`.
  - Replaces `LiveEventTimeline` debug content with `LiveDebugTraceRail`.
  - Passes selected trace to the stage.

- Modify: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
  - Rename prop from `debugTimeline` to `debugRail`, preserving the visible `调试事件` summary text.

- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
  - Accepts `debugTrace` and highlights related stage player cards.
  - Shows the selected trace event range as a compact badge near the current cue badges.

- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`
  - Updates expectations from raw timeline to Action Trace Rail and validates live events produce a trace.

- Modify: `apps/web/src/pages/GamePlaybackPage.test.tsx`
  - Adds playback coverage that trace output follows visible playback events.

## Task 1: Derive Action Traces From Live Events

**Files:**
- Create: `apps/web/src/features/games/liveDebugTrace.ts`
- Create: `apps/web/src/features/games/liveDebugTrace.test.ts`

- [ ] **Step 1: Write the failing derivation tests**

Create `apps/web/src/features/games/liveDebugTrace.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { buildLiveDebugTraces } from "./liveDebugTrace";
import type { LiveGameEvent } from "./types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "action_requested",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: partial.created_at ?? "2026-04-24T12:00:00Z",
    round: partial.round ?? 1,
    phase: partial.phase ?? "day",
    actor: partial.actor ?? "Sam",
    action: partial.action ?? "debate",
    payload: partial.payload ?? {},
  };
}

describe("buildLiveDebugTraces", () => {
  it("groups request model parsed and state events into one action trace", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 10,
        type: "action_requested",
        payload: { options: ["Isaac"] },
      }),
      event({
        id: 11,
        type: "model_request_started",
        payload: { request_id: "req_1", prompt: "请公开发言。" },
      }),
      event({
        id: 12,
        type: "model_response_received",
        payload: { raw_response: "{\"say\":\"我怀疑 Isaac\"}" },
      }),
      event({
        id: 13,
        type: "action_parsed",
        payload: {
          choice: "Isaac",
          visible_result: { say: "我怀疑 Isaac" },
        },
      }),
      event({
        id: 14,
        type: "state_updated",
        payload: {
          active_player: "Sam",
          debate_entry: { speaker: "Sam", message: "我怀疑 Isaac" },
        },
      }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0]).toMatchObject({
      id: "trace-10-14",
      eventIds: [10, 11, 12, 13, 14],
      actor: "Sam",
      action: "debate",
      choice: "Isaac",
      status: "ok",
      title: "Sam · 公开发言",
      relatedPlayers: ["Sam", "Isaac"],
    });
    expect(traces[0].nodes.map((node) => node.kind)).toEqual([
      "request",
      "model",
      "parsed",
      "state",
      "stage",
    ]);
    expect(traces[0].impactSummary).toContain("Sam 新增公开发言");
    expect(traces[0].stateDiff).toContainEqual({
      label: "当前发言",
      before: "未记录",
      after: "Sam",
    });
  });

  it("keeps streaming deltas out of the trace list but records model streaming status", () => {
    const traces = buildLiveDebugTraces([
      event({ id: 1, type: "action_requested" }),
      event({
        id: 2,
        type: "model_response_delta",
        payload: { request_id: "req_1", visible_text: "我" },
      }),
      event({ id: 3, type: "model_response_received" }),
      event({ id: 4, type: "action_parsed", payload: { choice: "skip" } }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0].eventIds).toEqual([1, 3, 4]);
    expect(traces[0].nodes.some((node) => node.eventId === 2)).toBe(false);
    expect(traces[0].nodes.find((node) => node.kind === "model")?.label).toBe(
      "模型返回",
    );
  });

  it("creates system traces for non actor flow events", () => {
    const traces = buildLiveDebugTraces([
      event({ id: 1, type: "round_started", actor: null, action: null, round: 2 }),
      event({
        id: 2,
        type: "phase_started",
        actor: null,
        action: null,
        phase: "night",
      }),
    ]);

    expect(traces).toHaveLength(2);
    expect(traces[0]).toMatchObject({
      id: "system-1",
      status: "system",
      title: "第 2 轮开始",
    });
    expect(traces[1]).toMatchObject({
      id: "system-2",
      status: "system",
      title: "夜晚阶段开始",
    });
  });

  it("marks missing parsed results as warnings", () => {
    const traces = buildLiveDebugTraces([
      event({ id: 1, type: "action_requested" }),
      event({ id: 2, type: "model_response_received" }),
    ]);

    expect(traces[0].status).toBe("warning");
    expect(traces[0].warnings).toContain("解析结果缺失");
  });

  it("marks parsed choice and state target conflicts as errors", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        action: "vote",
        payload: { options: ["Isaac", "Bert"] },
      }),
      event({
        id: 2,
        type: "action_parsed",
        action: "vote",
        payload: { choice: "Isaac" },
      }),
      event({
        id: 3,
        type: "state_updated",
        action: "vote",
        payload: { votes: { Sam: "Bert" } },
      }),
    ]);

    expect(traces[0].status).toBe("error");
    expect(traces[0].warnings).toContain("解析与状态不一致");
  });
});
```

- [ ] **Step 2: Run the derivation test and confirm it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveDebugTrace.test.ts
```

Expected: FAIL with an import error because `./liveDebugTrace` does not exist.

- [ ] **Step 3: Create the derivation module**

Create `apps/web/src/features/games/liveDebugTrace.ts` with this implementation:

```ts
import { actionLabel, eventTypeLabel, phaseLabel } from "./liveLabels";
import type { LiveGameEvent } from "./types";

export type LiveDebugTraceStatus = "ok" | "warning" | "error" | "system";
export type LiveDebugTraceNodeKind =
  | "request"
  | "model"
  | "parsed"
  | "state"
  | "stage"
  | "system";

export type LiveDebugTraceNode = {
  kind: LiveDebugTraceNodeKind;
  eventId: number;
  label: string;
  status: "ok" | "warning" | "error" | "muted";
};

export type LiveDebugStateDiff = {
  label: string;
  before: string;
  after: string;
};

export type LiveDebugTrace = {
  id: string;
  eventIds: number[];
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  choice: string | null;
  title: string;
  status: LiveDebugTraceStatus;
  nodes: LiveDebugTraceNode[];
  impactSummary: string[];
  warnings: string[];
  prompt?: string;
  rawResponse?: string;
  parsed?: unknown;
  payloads: Array<{ eventId: number; type: string; payload: unknown }>;
  stateDiff: LiveDebugStateDiff[];
  relatedPlayers: string[];
};

const STREAM_ONLY_EVENT_TYPES = new Set([
  "model_response_delta",
  "model_thinking_tick",
]);

const SYSTEM_EVENT_TYPES = new Set([
  "run_created",
  "run_started",
  "game_started",
  "round_started",
  "phase_started",
  "game_completed",
  "game_failed",
]);

export function buildLiveDebugTraces(
  events: LiveGameEvent[],
): LiveDebugTrace[] {
  const traces: LiveDebugTrace[] = [];

  for (const event of events) {
    if (STREAM_ONLY_EVENT_TYPES.has(event.type)) {
      markStreamingModelNode(traces, event);
      continue;
    }

    if (SYSTEM_EVENT_TYPES.has(event.type) && !event.actor) {
      traces.push(systemTrace(event));
      continue;
    }

    if (event.type === "action_requested") {
      traces.push(actionTrace(event));
      continue;
    }

    const trace = findActionTrace(traces, event) ?? actionTrace(event);
    if (!traces.includes(trace)) {
      traces.push(trace);
    }
    appendEvent(trace, event);
  }

  return traces.map(finalizeTrace).reverse();
}

function actionTrace(event: LiveGameEvent): LiveDebugTrace {
  return {
    id: `trace-${event.id}-${event.id}`,
    eventIds: [event.id],
    round: event.round,
    phase: event.phase,
    actor: event.actor,
    action: event.action,
    choice: null,
    title: actionTitle(event.actor, event.action),
    status: "ok",
    nodes:
      event.type === "action_requested"
        ? [
            {
              kind: "request",
              eventId: event.id,
              label: "行动请求",
              status: "ok",
            },
          ]
        : [],
    impactSummary: [],
    warnings: [],
    payloads: [{ eventId: event.id, type: event.type, payload: event.payload }],
    stateDiff: [],
    relatedPlayers: uniqueStrings([event.actor]),
  };
}

function systemTrace(event: LiveGameEvent): LiveDebugTrace {
  return {
    id: `system-${event.id}`,
    eventIds: [event.id],
    round: event.round,
    phase: event.phase,
    actor: null,
    action: null,
    choice: null,
    title: systemTitle(event),
    status: "system",
    nodes: [
      {
        kind: "system",
        eventId: event.id,
        label: eventTypeLabel(event.type),
        status: "muted",
      },
    ],
    impactSummary: [],
    warnings: [],
    payloads: [{ eventId: event.id, type: event.type, payload: event.payload }],
    stateDiff: [],
    relatedPlayers: [],
  };
}

function appendEvent(trace: LiveDebugTrace, event: LiveGameEvent) {
  trace.eventIds = uniqueNumbers([...trace.eventIds, event.id]);
  trace.id = `trace-${trace.eventIds[0]}-${trace.eventIds.at(-1)}`;
  trace.payloads.push({ eventId: event.id, type: event.type, payload: event.payload });
  trace.relatedPlayers = uniqueStrings([
    ...trace.relatedPlayers,
    event.actor,
    choiceFromPayload(event.payload),
    ...playersFromStatePayload(event.payload),
  ]);

  if (event.type === "model_request_started") {
    upsertNode(trace, {
      kind: "model",
      eventId: event.id,
      label: "模型请求",
      status: "ok",
    });
    trace.prompt = stringField(event.payload, "prompt") || trace.prompt;
  }

  if (event.type === "model_response_received") {
    upsertNode(trace, {
      kind: "model",
      eventId: event.id,
      label: "模型返回",
      status: "ok",
    });
    trace.rawResponse =
      stringField(event.payload, "raw_response") ||
      stringField(event.payload, "visible_text") ||
      stringField(event.payload, "message") ||
      trace.rawResponse;
  }

  if (event.type === "action_parsed") {
    const choice = choiceFromPayload(event.payload);
    trace.choice = choice || trace.choice;
    trace.parsed =
      event.payload.parsed ?? event.payload.result ?? event.payload.visible_result;
    upsertNode(trace, {
      kind: "parsed",
      eventId: event.id,
      label: "解析完成",
      status: "ok",
    });
  }

  if (event.type === "state_updated") {
    upsertNode(trace, {
      kind: "state",
      eventId: event.id,
      label: "状态更新",
      status: "ok",
    });
    upsertNode(trace, {
      kind: "stage",
      eventId: event.id,
      label: "舞台同步",
      status: "ok",
    });
    trace.impactSummary = uniqueStrings([
      ...trace.impactSummary,
      ...impactSummary(event.payload),
    ]);
    trace.stateDiff = [...trace.stateDiff, ...stateDiff(event.payload)];
  }
}

function finalizeTrace(trace: LiveDebugTrace): LiveDebugTrace {
  if (trace.status === "system") {
    return trace;
  }

  const warnings = new Set(trace.warnings);
  if (!trace.nodes.some((node) => node.kind === "model")) {
    warnings.add("模型返回缺失");
  }
  if (!trace.nodes.some((node) => node.kind === "parsed")) {
    warnings.add("解析结果缺失");
  }
  if (trace.choice && !trace.nodes.some((node) => node.kind === "state")) {
    warnings.add("选择未影响状态");
  }
  if (trace.choice && hasStateTargetConflict(trace.choice, trace.payloads)) {
    warnings.add("解析与状态不一致");
  }

  const warningList = Array.from(warnings);
  return {
    ...trace,
    warnings: warningList,
    status: warningList.includes("解析与状态不一致")
      ? "error"
      : warningList.length > 0
        ? "warning"
        : "ok",
  };
}

function findActionTrace(traces: LiveDebugTrace[], event: LiveGameEvent) {
  return [...traces].reverse().find((trace) => {
    if (trace.status === "system") {
      return false;
    }
    return (
      trace.actor === event.actor &&
      trace.action === event.action &&
      trace.round === event.round &&
      trace.phase === event.phase
    );
  });
}

function markStreamingModelNode(traces: LiveDebugTrace[], event: LiveGameEvent) {
  const trace = findActionTrace(traces, event);
  if (!trace) {
    return;
  }
  upsertNode(trace, {
    kind: "model",
    eventId: trace.nodes.find((node) => node.kind === "model")?.eventId ?? event.id,
    label: "模型流式返回",
    status: "ok",
  });
}

function upsertNode(trace: LiveDebugTrace, node: LiveDebugTraceNode) {
  const index = trace.nodes.findIndex((item) => item.kind === node.kind);
  if (index >= 0) {
    trace.nodes[index] = node;
  } else {
    trace.nodes.push(node);
  }
}

function actionTitle(actor: string | null, action: string | null) {
  return `${actor ?? "系统"} · ${actionLabel(action)}`;
}

function systemTitle(event: LiveGameEvent) {
  if (event.type === "round_started") {
    return event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`;
  }
  if (event.type === "phase_started") {
    return `${phaseLabel(event.phase)}阶段开始`;
  }
  return eventTypeLabel(event.type);
}

function impactSummary(payload: Record<string, unknown>) {
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    return [`${debateEntry.speaker} 新增公开发言`];
  }
  const votes = recordField(payload, "votes");
  if (votes) {
    return ["票型更新"];
  }
  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return [`${exiled} 被放逐`];
  }
  const eliminated = stringField(payload, "eliminated");
  if (eliminated) {
    return [`${eliminated} 夜晚出局`];
  }
  return [];
}

function stateDiff(payload: Record<string, unknown>): LiveDebugStateDiff[] {
  const diffs: LiveDebugStateDiff[] = [];
  const activePlayer = stringField(payload, "active_player");
  if (activePlayer) {
    diffs.push({ label: "当前发言", before: "未记录", after: activePlayer });
  }
  const votes = recordField(payload, "votes");
  if (votes) {
    diffs.push({
      label: "票型",
      before: "未记录",
      after: JSON.stringify(votes),
    });
  }
  for (const key of ["exiled", "eliminated", "attacked", "protected", "investigated"]) {
    const value = stringField(payload, key);
    if (value) {
      diffs.push({ label: key, before: "未记录", after: value });
    }
  }
  return diffs;
}

function choiceFromPayload(payload: Record<string, unknown>) {
  return (
    stringField(payload, "choice") ||
    stringField(payload, "target") ||
    stringField(payload, "vote")
  );
}

function playersFromStatePayload(payload: Record<string, unknown>) {
  const players = [
    stringField(payload, "active_player"),
    stringField(payload, "exiled"),
    stringField(payload, "eliminated"),
    stringField(payload, "attacked"),
    stringField(payload, "protected"),
    stringField(payload, "investigated"),
  ];
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    players.push(debateEntry.speaker);
  }
  return uniqueStrings(players);
}

function hasStateTargetConflict(
  choice: string,
  payloads: LiveDebugTrace["payloads"],
) {
  return payloads.some((item) => {
    if (item.type !== "state_updated" || !isRecord(item.payload)) {
      return false;
    }
    const votes = recordField(item.payload, "votes");
    if (votes) {
      return Object.values(votes).some((target) => String(target) !== choice);
    }
    return false;
  });
}

function stringField(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function recordField(
  payload: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = payload[key];
  return isRecord(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value))));
}

function uniqueNumbers(values: number[]) {
  return Array.from(new Set(values));
}
```

- [ ] **Step 4: Run the derivation tests**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveDebugTrace.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add apps/web/src/features/games/liveDebugTrace.ts apps/web/src/features/games/liveDebugTrace.test.ts
git commit -m "feat(web): derive live debug action traces"
```

Expected: commit succeeds with only the derivation module and its tests.

## Task 2: Build the Trace Rail Component

**Files:**
- Create: `apps/web/src/features/games/components/LiveDebugTraceRail.tsx`
- Create: `apps/web/src/features/games/components/LiveDebugTraceRail.test.tsx`

- [ ] **Step 1: Write the failing component tests**

Create `apps/web/src/features/games/components/LiveDebugTraceRail.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppTheme } from "../../../app/AppTheme";
import type { LiveDebugTrace } from "../liveDebugTrace";
import { LiveDebugTraceRail } from "./LiveDebugTraceRail";

const traces: LiveDebugTrace[] = [
  {
    id: "trace-10-14",
    eventIds: [10, 11, 12, 13, 14],
    round: 1,
    phase: "day",
    actor: "Sam",
    action: "debate",
    choice: "Isaac",
    title: "Sam · 公开发言",
    status: "ok",
    nodes: [
      { kind: "request", eventId: 10, label: "行动请求", status: "ok" },
      { kind: "model", eventId: 12, label: "模型返回", status: "ok" },
      { kind: "parsed", eventId: 13, label: "解析完成", status: "ok" },
      { kind: "state", eventId: 14, label: "状态更新", status: "ok" },
      { kind: "stage", eventId: 14, label: "舞台同步", status: "ok" },
    ],
    impactSummary: ["Sam 新增公开发言"],
    warnings: [],
    prompt: "请公开发言。",
    rawResponse: "{\"say\":\"我怀疑 Isaac\"}",
    parsed: { say: "我怀疑 Isaac" },
    payloads: [{ eventId: 14, type: "state_updated", payload: { active_player: "Sam" } }],
    stateDiff: [{ label: "当前发言", before: "未记录", after: "Sam" }],
    relatedPlayers: ["Sam", "Isaac"],
  },
  {
    id: "trace-20-22",
    eventIds: [20, 21, 22],
    round: 1,
    phase: "vote",
    actor: "Will",
    action: "vote",
    choice: "Bert",
    title: "Will · 放逐投票",
    status: "warning",
    nodes: [
      { kind: "request", eventId: 20, label: "行动请求", status: "ok" },
      { kind: "parsed", eventId: 22, label: "解析完成", status: "ok" },
    ],
    impactSummary: [],
    warnings: ["模型返回缺失", "选择未影响状态"],
    payloads: [],
    stateDiff: [],
    relatedPlayers: ["Will", "Bert"],
  },
];

describe("LiveDebugTraceRail", () => {
  it("renders trace cards with status nodes and impact summary", () => {
    render(
      <AppTheme>
        <LiveDebugTraceRail traces={traces} />
      </AppTheme>,
    );

    expect(screen.getByText("Action Trace")).toBeInTheDocument();
    expect(screen.getByText("#10-14")).toBeInTheDocument();
    expect(screen.getByText("Sam · 公开发言")).toBeInTheDocument();
    expect(screen.getByText("Sam 新增公开发言")).toBeInTheDocument();
    expect(screen.getByText("request")).toBeInTheDocument();
    expect(screen.getByText("model")).toBeInTheDocument();
    expect(screen.getByText("parsed")).toBeInTheDocument();
    expect(screen.getByText("state")).toBeInTheDocument();
    expect(screen.getByText("stage")).toBeInTheDocument();
  });

  it("expands details and notifies selection", async () => {
    const user = userEvent.setup();
    const onSelectTrace = vi.fn();

    render(
      <AppTheme>
        <LiveDebugTraceRail
          onSelectTrace={onSelectTrace}
          selectedTraceId={null}
          traces={traces}
        />
      </AppTheme>,
    );

    await user.click(screen.getByRole("button", { name: /Sam · 公开发言/ }));

    expect(onSelectTrace).toHaveBeenCalledWith(traces[0]);
    expect(screen.getByText("状态变化")).toBeInTheDocument();
    expect(screen.getByText("Prompt")).toBeInTheDocument();
    expect(screen.getByText(/请公开发言/)).toBeInTheDocument();
    expect(screen.getByText(/当前发言/)).toBeInTheDocument();
  });

  it("filters to issue traces", async () => {
    const user = userEvent.setup();

    render(
      <AppTheme>
        <LiveDebugTraceRail traces={traces} />
      </AppTheme>,
    );

    await user.click(screen.getByRole("button", { name: "只看异常" }));

    expect(screen.queryByText("Sam · 公开发言")).not.toBeInTheDocument();
    expect(screen.getByText("Will · 放逐投票")).toBeInTheDocument();
    const warningCard = screen.getByTestId("live-debug-trace-card-trace-20-22");
    expect(within(warningCard).getByText("需关注")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the component test and confirm it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveDebugTraceRail.test.tsx
```

Expected: FAIL with an import error because `LiveDebugTraceRail` does not exist.

- [ ] **Step 3: Implement the rail component**

Create `apps/web/src/features/games/components/LiveDebugTraceRail.tsx`:

```tsx
import { useState } from "react";

import type { LiveDebugTrace, LiveDebugTraceNode } from "../liveDebugTrace";

type LiveDebugTraceRailProps = {
  traces: LiveDebugTrace[];
  selectedTraceId?: string | null;
  onSelectTrace?: (trace: LiveDebugTrace) => void;
};

export function LiveDebugTraceRail({
  traces,
  selectedTraceId = null,
  onSelectTrace,
}: LiveDebugTraceRailProps) {
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(
    selectedTraceId,
  );
  const [showIssuesOnly, setShowIssuesOnly] = useState(false);
  const visibleTraces = showIssuesOnly
    ? traces.filter((trace) => trace.status === "warning" || trace.status === "error")
    : traces;

  if (traces.length === 0) {
    return <p className="p-4 text-sm text-slate-400">等待可追踪行动...</p>;
  }

  return (
    <section className="p-3" data-testid="live-debug-trace-rail">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-amber-50">Action Trace</h3>
          <p className="mt-0.5 text-[11px] text-slate-400">
            按行动聚合 · 当前 {traces.length} 条
          </p>
        </div>
        <button
          className={`rounded-md border px-2 py-1 text-[11px] font-semibold transition ${
            showIssuesOnly
              ? "border-red-300/45 bg-red-400/15 text-red-100"
              : "border-slate-600/45 bg-slate-950/45 text-slate-300"
          }`}
          onClick={() => setShowIssuesOnly((value) => !value)}
          type="button"
        >
          只看异常
        </button>
      </div>

      <div className="mt-3 space-y-2">
        {visibleTraces.length === 0 ? (
          <p className="rounded-md border border-slate-600/35 bg-slate-950/35 px-3 py-2 text-xs text-slate-400">
            当前没有异常行动包
          </p>
        ) : (
          visibleTraces.map((trace) => {
            const isExpanded =
              expandedTraceId === trace.id || selectedTraceId === trace.id;
            return (
              <TraceCard
                isExpanded={isExpanded}
                key={trace.id}
                onSelect={() => {
                  setExpandedTraceId(isExpanded ? null : trace.id);
                  onSelectTrace?.(trace);
                }}
                trace={trace}
              />
            );
          })
        )}
      </div>
    </section>
  );
}

function TraceCard({
  isExpanded,
  onSelect,
  trace,
}: {
  isExpanded: boolean;
  onSelect: () => void;
  trace: LiveDebugTrace;
}) {
  return (
    <article
      className={`rounded-md border bg-black/30 text-xs ${traceTone(trace.status)}`}
      data-testid={`live-debug-trace-card-${trace.id}`}
    >
      <button
        aria-expanded={isExpanded}
        className="w-full px-3 py-2 text-left"
        onClick={onSelect}
        type="button"
      >
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-amber-100">
            {eventRange(trace)}
          </span>
          <span className="min-w-0 flex-1 truncate font-semibold text-slate-100">
            {trace.title}
          </span>
          <span className={`shrink-0 rounded px-1.5 py-0.5 ${statusTone(trace.status)}`}>
            {statusLabel(trace.status)}
          </span>
        </div>
        <NodeStrip nodes={trace.nodes} />
        {trace.impactSummary.length > 0 ? (
          <p className="mt-2 line-clamp-2 text-[11px] text-slate-300">
            {trace.impactSummary.join("；")}
          </p>
        ) : trace.warnings.length > 0 ? (
          <p className="mt-2 line-clamp-2 text-[11px] text-red-100">
            {trace.warnings.join("；")}
          </p>
        ) : null}
      </button>

      {isExpanded ? <TraceDetails trace={trace} /> : null}
    </article>
  );
}

function NodeStrip({ nodes }: { nodes: LiveDebugTraceNode[] }) {
  return (
    <div className="mt-2 grid grid-cols-5 gap-1 text-center text-[10px]">
      {["request", "model", "parsed", "state", "stage"].map((kind) => {
        const node = nodes.find((item) => item.kind === kind);
        return (
          <span
            className={`rounded px-1 py-1 ${node ? nodeTone(node.status) : "bg-slate-900/60 text-slate-600"}`}
            key={kind}
            title={node?.label ?? `${kind} 缺失`}
          >
            {kind}
          </span>
        );
      })}
    </div>
  );
}

function TraceDetails({ trace }: { trace: LiveDebugTrace }) {
  return (
    <div className="space-y-3 border-t border-amber-500/15 px-3 py-3">
      {trace.warnings.length > 0 ? (
        <DetailBlock title="异常提示" tone="warning">
          {trace.warnings.join("\n")}
        </DetailBlock>
      ) : null}
      {trace.stateDiff.length > 0 ? (
        <section>
          <h4 className="text-[11px] font-semibold text-amber-100">状态变化</h4>
          <div className="mt-1 space-y-1">
            {trace.stateDiff.map((diff) => (
              <div
                className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-2 rounded border border-slate-700/45 bg-slate-950/40 px-2 py-1 text-[11px]"
                key={`${diff.label}-${diff.after}`}
              >
                <span className="text-slate-400">{diff.label}</span>
                <span className="min-w-0 break-words text-slate-200">
                  {diff.before} → {diff.after}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <DetailBlock title="Prompt">{trace.prompt || "无内容"}</DetailBlock>
      <DetailBlock title="Raw response">{trace.rawResponse || "无内容"}</DetailBlock>
      <DetailBlock title="Parsed result">{formatDebugValue(trace.parsed)}</DetailBlock>
      <DetailBlock title="Payload JSON">
        {JSON.stringify(trace.payloads, null, 2)}
      </DetailBlock>
    </div>
  );
}

function DetailBlock({
  children,
  title,
  tone = "default",
}: {
  children: string;
  title: string;
  tone?: "default" | "warning";
}) {
  return (
    <section>
      <h4
        className={`text-[11px] font-semibold ${
          tone === "warning" ? "text-red-100" : "text-amber-100"
        }`}
      >
        {title}
      </h4>
      <pre className="mt-1 max-h-44 overflow-auto whitespace-pre-wrap break-words rounded border border-slate-700/55 bg-slate-950/60 p-2 text-[11px] leading-5 text-slate-200">
        {children}
      </pre>
    </section>
  );
}

function eventRange(trace: LiveDebugTrace) {
  const first = trace.eventIds[0];
  const last = trace.eventIds.at(-1);
  return first === last ? `#${first}` : `#${first}-${last}`;
}

function statusLabel(status: LiveDebugTrace["status"]) {
  if (status === "error") {
    return "异常";
  }
  if (status === "warning") {
    return "需关注";
  }
  if (status === "system") {
    return "系统";
  }
  return "OK";
}

function traceTone(status: LiveDebugTrace["status"]) {
  if (status === "error") {
    return "border-red-400/35";
  }
  if (status === "warning") {
    return "border-amber-300/30";
  }
  if (status === "system") {
    return "border-slate-600/40";
  }
  return "border-emerald-300/25";
}

function statusTone(status: LiveDebugTrace["status"]) {
  if (status === "error") {
    return "bg-red-400/15 text-red-100";
  }
  if (status === "warning") {
    return "bg-amber-400/15 text-amber-100";
  }
  if (status === "system") {
    return "bg-slate-500/15 text-slate-300";
  }
  return "bg-emerald-400/15 text-emerald-100";
}

function nodeTone(status: LiveDebugTraceNode["status"]) {
  if (status === "error") {
    return "bg-red-500/20 text-red-100";
  }
  if (status === "warning") {
    return "bg-amber-500/20 text-amber-100";
  }
  if (status === "muted") {
    return "bg-slate-800/70 text-slate-400";
  }
  return "bg-emerald-500/15 text-emerald-100";
}

function formatDebugValue(value: unknown) {
  if (value === null || value === undefined) {
    return "无内容";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}
```

- [ ] **Step 4: Run the component tests**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveDebugTraceRail.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add apps/web/src/features/games/components/LiveDebugTraceRail.tsx apps/web/src/features/games/components/LiveDebugTraceRail.test.tsx
git commit -m "feat(web): add live debug trace rail"
```

Expected: commit succeeds with the new rail component and tests.

## Task 3: Replace Raw Debug Timeline In The Right Panel

**Files:**
- Modify: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
- Modify: `apps/web/src/features/games/components/LiveStageExperience.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Update the page test first**

In `apps/web/src/pages/LiveGamePage.test.tsx`, in the existing live-events test that emits `action_requested`, `model_request_started`, `model_response_delta`, `model_response_received`, `action_parsed`, and `state_updated`, add these expectations after the emitted events have rendered:

```tsx
expect(screen.getByText("Action Trace")).toBeInTheDocument();
expect(screen.getByText(/按行动聚合/)).toBeInTheDocument();
expect(screen.getByText(/张三 · 公开发言/)).toBeInTheDocument();
expect(screen.getByText(/#2-/)).toBeInTheDocument();
expect(screen.queryByText("等待实时事件...")).not.toBeInTheDocument();
```

Keep the existing expectation that the summary text `调试事件` exists, because the panel section label remains Chinese.

- [ ] **Step 2: Run the page test and confirm it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "renders live events and completed replay link"
```

Expected: FAIL because `Action Trace` is not rendered yet.

- [ ] **Step 3: Rename the right-panel prop**

In `apps/web/src/features/games/components/GodViewIntelPanel.tsx`, change the prop name and render site:

```tsx
type GodViewIntelPanelProps = {
  state: GodViewState;
  debugRail?: ReactNode;
};

export function GodViewIntelPanel({
  state,
  debugRail,
}: GodViewIntelPanelProps) {
  return (
    <aside
      className={withGlassPanel(
        "god-view-intel-panel god-view-frame min-w-0 overflow-hidden rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.32)] xl:max-h-[calc(100vh-8rem)] xl:overflow-auto",
      )}
      data-testid="god-view-intel-panel"
    >
      {/* existing IntelSection blocks stay unchanged */}

      {debugRail ? (
        <details className="border-t border-amber-500/15">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-300">
            调试事件
          </summary>
          {debugRail}
        </details>
      ) : null}
    </aside>
  );
}
```

When applying this change, keep the existing `IntelSection`, `EventLines`, `SkillTriggerLine`, and tone helper functions unchanged.

- [ ] **Step 4: Build traces in `LiveStageExperience`**

In `apps/web/src/features/games/components/LiveStageExperience.tsx`, replace the `LiveEventTimeline` import with:

```tsx
import { useMemo, useState } from "react";

import { buildLiveDebugTraces, type LiveDebugTrace } from "../liveDebugTrace";
import { LiveDebugTraceRail } from "./LiveDebugTraceRail";
```

Inside `LiveStageExperience`, add trace state after `focusedPlayerName`:

```tsx
const traces = useMemo(() => buildLiveDebugTraces(events), [events]);
const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
```

Replace the right-panel prop:

```tsx
right={
  <GodViewIntelPanel
    debugRail={
      <LiveDebugTraceRail
        onSelectTrace={(trace: LiveDebugTrace) => {
          setSelectedTraceId(trace.id);
          const focusName = trace.actor ?? trace.relatedPlayers[0] ?? null;
          if (focusName) {
            setAutoFollow(false);
            setManualFocusName(focusName);
          }
        }}
        selectedTraceId={selectedTraceId}
        traces={traces}
      />
    }
    state={godViewState}
  />
}
```

Keep the existing `LiveDirectorStage` props unchanged in this task:

```tsx
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
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "renders live events and completed replay link"
pnpm --dir apps/web exec vitest run src/features/games/components/LiveDebugTraceRail.test.tsx
```

Expected: both commands PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add apps/web/src/features/games/components/GodViewIntelPanel.tsx apps/web/src/features/games/components/LiveStageExperience.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat(web): replace raw live debug timeline"
```

Expected: commit succeeds with the right-panel integration.

## Task 4: Highlight Related Players On The Stage

**Files:**
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Add a page-level highlight expectation**

In `apps/web/src/pages/LiveGamePage.test.tsx`, after selecting a trace card in the live-events test, assert that the actor card has a debug highlight state:

```tsx
const user = userEvent.setup();
await user.click(await screen.findByRole("button", { name: /张三 · 公开发言/ }));

expect(screen.getByTestId("god-view-stage-player-card-张三")).toHaveAttribute(
  "data-debug-highlighted",
  "true",
);
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "renders live events and completed replay link"
```

Expected: FAIL because `data-debug-highlighted` is not set yet.

- [ ] **Step 3: Add the `debugTrace` prop**

In `apps/web/src/features/games/components/LiveDirectorStage.tsx`, add:

```tsx
import type { LiveDebugTrace } from "../liveDebugTrace";
```

Update `LiveDirectorStageProps`:

```tsx
type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
  players: LivePlayer[];
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  godViewState?: GodViewState;
  debugTrace?: LiveDebugTrace | null;
  autoFollow: boolean;
  onSelectPlayer: (name: string) => void;
  onAutoFollowChange: (value: boolean) => void;
};
```

In the component args, include `debugTrace`.

In `LiveStageExperience.tsx`, derive the selected trace after `selectedTraceId`:

```tsx
const selectedTrace =
  traces.find((trace) => trace.id === selectedTraceId) ?? null;
```

Pass `selectedTrace` to `LiveDirectorStage`:

```tsx
debugTrace={selectedTrace}
```

Create a set near `livePlayersByName`:

```tsx
const debugHighlightedPlayers = new Set(debugTrace?.relatedPlayers ?? []);
```

Pass it to both `PlayerRail` calls:

```tsx
debugHighlightedPlayers={debugHighlightedPlayers}
```

Add a selected trace badge inside the existing badge row:

```tsx
{debugTrace ? (
  <Badge color="amber" variant="surface">
    {traceEventRange(debugTrace)}
  </Badge>
) : null}
```

- [ ] **Step 4: Thread highlight state through player rail cards**

Update `PlayerRail` props:

```tsx
function PlayerRail({
  activePlayerName,
  debugHighlightedPlayers,
  focusedPlayerName,
  isTerminalCue,
  livePlayersByName,
  onSelectPlayer,
  players,
  side,
}: {
  activePlayerName: string | null;
  debugHighlightedPlayers: Set<string>;
  focusedPlayerName: string | null;
  isTerminalCue: boolean;
  livePlayersByName: Map<string, LivePlayer>;
  onSelectPlayer: (name: string) => void;
  players: GodViewPlayer[];
  side: "left" | "right";
}) {
```

Pass to `StagePlayerCard`:

```tsx
debugHighlighted={debugHighlightedPlayers.has(player.name)}
```

Update `StagePlayerCard` props:

```tsx
function StagePlayerCard({
  activePlayerName,
  debugHighlighted,
  focusedPlayerName,
  isTerminalCue,
  livePlayer,
  onSelectPlayer,
  player,
  side,
}: {
  activePlayerName: string | null;
  debugHighlighted: boolean;
  focusedPlayerName: string | null;
  isTerminalCue: boolean;
  livePlayer: LivePlayer | null;
  onSelectPlayer: (name: string) => void;
  player: GodViewPlayer;
  side: "left" | "right";
}) {
```

Add the highlight class and attribute to the `<button>`:

```tsx
className={`god-view-player-card pointer-events-auto grid w-full max-w-[13rem] grid-cols-[2.2rem_minmax(0,1fr)] items-center gap-2 rounded-md border bg-black/45 px-2 py-2 text-left shadow-[0_12px_32px_rgba(0,0,0,0.26)] transition duration-200 hover:-translate-y-0.5 hover:border-amber-200/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-200 ${
  side === "right" ? "text-right" : ""
} ${stagePlayerTone(player, cardState)} ${
  isFocused ? "is-focused ring-1 ring-amber-100/70" : ""
} ${
  debugHighlighted
    ? "ring-2 ring-amber-200/80 shadow-[0_0_26px_rgba(251,191,36,0.28)]"
    : ""
} ${!player.isAlive ? "opacity-65 grayscale" : ""}`}
data-debug-highlighted={debugHighlighted ? "true" : "false"}
```

Add helper near `importanceLabel`:

```tsx
function traceEventRange(trace: LiveDebugTrace) {
  const first = trace.eventIds[0];
  const last = trace.eventIds.at(-1);
  return first === last ? `Trace #${first}` : `Trace #${first}-${last}`;
}
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "renders live events and completed replay link"
pnpm --dir apps/web exec vitest run src/features/games/components/LiveDebugTraceRail.test.tsx
pnpm --dir apps/web exec vitest run src/features/games/liveDebugTrace.test.ts
```

Expected: all commands PASS.

- [ ] **Step 6: Commit Task 4 with Task 3 integration if Task 3 was waiting on types**
- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add apps/web/src/features/games/components/LiveDirectorStage.tsx apps/web/src/features/games/components/LiveStageExperience.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat(web): link debug traces to live stage"
```

Expected: commit succeeds with stage highlighting and the page-test highlight assertion.

## Task 5: Playback Coverage And Final Verification

**Files:**
- Modify: `apps/web/src/pages/GamePlaybackPage.test.tsx`

- [ ] **Step 1: Add playback trace coverage**

In `apps/web/src/pages/GamePlaybackPage.test.tsx`, add a test or extend the existing playback test with a playback response containing these events:

```tsx
events: [
  {
    id: 1,
    type: "game_started",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: "2026-04-24T12:00:01Z",
    round: null,
    phase: null,
    actor: null,
    action: null,
    payload: {
      players: [
        { name: "Sam", role: "村民", model: "deepseek-chat" },
        { name: "Isaac", role: "守卫", model: "deepseek-chat" },
      ],
    },
  },
  {
    id: 2,
    type: "action_requested",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: "2026-04-24T12:00:02Z",
    round: 1,
    phase: "day",
    actor: "Sam",
    action: "debate",
    payload: { options: [] },
  },
  {
    id: 3,
    type: "model_response_received",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: "2026-04-24T12:00:03Z",
    round: 1,
    phase: "day",
    actor: "Sam",
    action: "debate",
    payload: { raw_response: "{\"say\":\"我怀疑 Isaac\"}" },
  },
  {
    id: 4,
    type: "action_parsed",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: "2026-04-24T12:00:04Z",
    round: 1,
    phase: "day",
    actor: "Sam",
    action: "debate",
    payload: { choice: "Isaac", visible_result: { say: "我怀疑 Isaac" } },
  },
  {
    id: 5,
    type: "state_updated",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: "2026-04-24T12:00:05Z",
    round: 1,
    phase: "day",
    actor: "Sam",
    action: "debate",
    payload: {
      active_player: "Sam",
      debate_entry: { speaker: "Sam", message: "我怀疑 Isaac" },
    },
  },
]
```

Assert:

```tsx
expect(await screen.findByText("Action Trace")).toBeInTheDocument();
expect(screen.getByText("Sam · 公开发言")).toBeInTheDocument();
expect(screen.getByText("Sam 新增公开发言")).toBeInTheDocument();
```

- [ ] **Step 2: Run playback test and confirm it fails if integration misses playback visible events**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/GamePlaybackPage.test.tsx
```

Expected: PASS if `LiveStageExperience` receives `visibleEvents`; FAIL if the test expectation does not match existing playback setup. Fix only the test fixture or integration path needed for visible playback events.

- [ ] **Step 3: Run all focused web tests**

Run:

```bash
pnpm --dir apps/web exec vitest run \
  src/features/games/liveDebugTrace.test.ts \
  src/features/games/components/LiveDebugTraceRail.test.tsx \
  src/pages/LiveGamePage.test.tsx \
  src/pages/GamePlaybackPage.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run lint/typecheck equivalent for the web app**

Run:

```bash
pnpm --dir apps/web exec tsc --noEmit
```

Expected: PASS with no TypeScript errors.

- [ ] **Step 5: Run the local dev server and visually inspect**

Run:

```bash
pnpm --dir apps/web dev --host 127.0.0.1
```

Open the printed local URL in the in-app browser and inspect a live or playback route with events. Verify:

- Right panel still shows `事件记录`, `死亡信息`, and `身份线索 / 技能触发`.
- `调试事件` expands to `Action Trace`.
- A complete player action shows `request / model / parsed / state / stage`.
- Clicking a trace expands details and highlights the related player card.
- The panel remains readable on a narrow viewport.

- [ ] **Step 6: Commit final verification test changes**

Run:

```bash
git add apps/web/src/pages/GamePlaybackPage.test.tsx
git commit -m "test(web): cover playback debug traces"
```

Expected: commit succeeds if Task 5 changed playback tests. If Task 5 only verified existing behavior and changed no files, skip this commit.

## Final Verification

After all tasks are committed, run:

```bash
pnpm --dir apps/web exec vitest run \
  src/features/games/liveDebugTrace.test.ts \
  src/features/games/components/LiveDebugTraceRail.test.tsx \
  src/pages/LiveGamePage.test.tsx \
  src/pages/GamePlaybackPage.test.tsx
pnpm --dir apps/web exec tsc --noEmit
```

Expected: all commands PASS.

## Handoff Notes

- The existing worktree may contain unrelated uncommitted changes. Do not revert them.
- The first implementation should stay frontend-only.
- Keep the raw payload detail available in the expanded trace, but make the default card readable without opening JSON.
- If a real event sequence does not fit the initial grouping rules, add a focused unit test in `liveDebugTrace.test.ts` before changing the grouping logic.
