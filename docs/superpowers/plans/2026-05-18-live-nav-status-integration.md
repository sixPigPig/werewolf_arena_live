# Live Nav Status Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace separate live navigation connection/run labels with one spectator-facing status derived from connection, run, and director playback state.

**Architecture:** Add a pure `deriveLiveNavStatus` helper for status priority and copy, then render it through a focused navigation badge component. `LiveGamePage` wires existing `connectionState`, `run.status`, terminal events, and `useLiveDirector` playback fields into the helper while leaving SSE, backend run status, stage, timeline, and player state behavior unchanged.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, existing Tailwind utility classes.

---

## File Structure

- Create `apps/web/src/features/games/liveNavStatus.ts` for the derived navigation-only status model and priority rules.
- Create `apps/web/src/features/games/liveNavStatus.test.ts` for pure helper tests.
- Create `apps/web/src/features/games/components/LiveNavStatusBadge.tsx` for compact rendering in `ArenaCommandNav` context.
- Modify `apps/web/src/pages/LiveGamePage.tsx` to use the new derived status in the nav context.
- Modify `apps/web/src/pages/LiveGamePage.test.tsx` to assert combined nav status rendering and preserve playback controls.
- Leave `apps/web/src/features/games/hooks/useGameRunEvents.ts`, `apps/web/src/features/games/hooks/useLiveDirector.ts`, and player/stage state files unchanged.

### Task 1: Derived Live Nav Status Helper

**Files:**
- Create: `apps/web/src/features/games/liveNavStatus.ts`
- Create: `apps/web/src/features/games/liveNavStatus.test.ts`

- [ ] **Step 1: Write failing tests for status priority**

Create `apps/web/src/features/games/liveNavStatus.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { deriveLiveNavStatus } from "./liveNavStatus";

describe("deriveLiveNavStatus", () => {
  it("maps idle and connecting streams to connecting", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "idle",
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: [],
      kind: "connecting",
      label: "连接中",
    });

    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "connecting",
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }).kind,
    ).toBe("connecting");
  });

  it("maps an open running stream with no backlog to live", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "open",
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["1x"],
      kind: "live",
      label: "直播中",
    });
  });

  it("maps backlog to catching up with speed and backlog details", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 8,
        connectionState: "open",
        isPaused: false,
        runStatus: "running",
        speed: 2,
      }),
    ).toMatchObject({
      detailItems: ["落后 8 条", "2x"],
      kind: "catchingUp",
      label: "追播中",
    });
  });

  it("prioritizes paused over catch-up", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 2,
        connectionState: "open",
        isPaused: true,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["落后 2 条"],
      kind: "paused",
      label: "已暂停",
    });
  });

  it("prioritizes completed runs over closed connections", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "closed",
        isPaused: false,
        runStatus: "completed",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["已完成"],
      kind: "ended",
      label: "已结束",
    });

    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "closed",
        hasCompletedTerminalEvent: true,
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["已完成"],
      kind: "ended",
      label: "已结束",
    });
  });

  it("prioritizes failures and active closed streams as interrupted", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "open",
        isPaused: false,
        runStatus: "failed",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["失败"],
      kind: "interrupted",
      label: "异常中断",
    });

    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "closed",
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["已关闭"],
      kind: "interrupted",
      label: "异常中断",
    });

    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "open",
        hasFailedTerminalEvent: true,
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["失败"],
      kind: "interrupted",
      label: "异常中断",
    });
  });
});
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveNavStatus.test.ts
```

Expected: FAIL because `src/features/games/liveNavStatus.ts` does not exist.

- [ ] **Step 3: Implement the derived status helper**

Create `apps/web/src/features/games/liveNavStatus.ts`:

```ts
import type { ConnectionState } from "./hooks/useGameRunEvents";
import type { LiveDirectorSpeed } from "./hooks/useLiveDirector";
import type { GameRunStatus } from "./types";

export type LiveNavStatusKind =
  | "connecting"
  | "live"
  | "catchingUp"
  | "paused"
  | "ended"
  | "interrupted";

export type LiveNavStatusTone = "neutral" | "good" | "warning" | "danger" | "done";

export type LiveNavStatus = {
  kind: LiveNavStatusKind;
  label: string;
  detailItems: string[];
  tone: LiveNavStatusTone;
};

export type LiveNavStatusInput = {
  connectionState: ConnectionState | (string & {});
  runStatus: GameRunStatus | (string & {});
  isPaused: boolean;
  backlogCount: number;
  speed: LiveDirectorSpeed;
  hasCompletedTerminalEvent?: boolean;
  hasFailedTerminalEvent?: boolean;
};

const connectionLabels = {
  idle: "未连接",
  connecting: "连接中",
  open: "已连接",
  closed: "已关闭",
  error: "连接异常",
} satisfies Record<ConnectionState, string>;

const runStatusLabels = {
  queued: "排队中",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
} satisfies Record<GameRunStatus, string>;

export function deriveLiveNavStatus(input: LiveNavStatusInput): LiveNavStatus {
  const backlogCount = Math.max(0, input.backlogCount);
  const connectionLabel = labelForConnectionState(input.connectionState);
  const runStatusLabel = labelForRunStatus(input.runStatus);
  const endedLabel =
    input.runStatus === "completed" || input.hasCompletedTerminalEvent
      ? "已完成"
      : runStatusLabel;
  const interruptedLabel =
    input.runStatus === "failed" || input.hasFailedTerminalEvent
      ? "失败"
      : connectionLabel;
  const isEnded =
    input.runStatus === "completed" || input.hasCompletedTerminalEvent === true;
  const isInterrupted =
    input.runStatus === "failed" ||
    input.hasFailedTerminalEvent === true ||
    (!isEnded &&
      (input.connectionState === "error" || input.connectionState === "closed"));

  if (isInterrupted) {
    return {
      detailItems: [interruptedLabel],
      kind: "interrupted",
      label: "异常中断",
      tone: "danger",
    };
  }

  if (isEnded) {
    return {
      detailItems: [endedLabel],
      kind: "ended",
      label: "已结束",
      tone: "done",
    };
  }

  if (input.isPaused) {
    return {
      detailItems: backlogCount > 0 ? [`落后 ${backlogCount} 条`] : [],
      kind: "paused",
      label: "已暂停",
      tone: "warning",
    };
  }

  if (
    input.connectionState === "idle" ||
    input.connectionState === "connecting" ||
    input.runStatus === "queued"
  ) {
    return {
      detailItems: [],
      kind: "connecting",
      label: "连接中",
      tone: "neutral",
    };
  }

  if (backlogCount > 0) {
    return {
      detailItems: [`落后 ${backlogCount} 条`, `${input.speed}x`],
      kind: "catchingUp",
      label: "追播中",
      tone: "warning",
    };
  }

  return {
    detailItems: [`${input.speed}x`],
    kind: "live",
    label: "直播中",
    tone: "good",
  };
}

function labelForConnectionState(
  connectionState: ConnectionState | (string & {}),
) {
  return connectionLabels[connectionState as ConnectionState] ?? connectionState;
}

function labelForRunStatus(runStatus: GameRunStatus | (string & {})) {
  return runStatusLabels[runStatus as GameRunStatus] ?? runStatus;
}
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveNavStatus.test.ts
```

Expected: PASS.

### Task 2: Compact Nav Status Badge

**Files:**
- Create: `apps/web/src/features/games/components/LiveNavStatusBadge.tsx`
- Test through: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Create the nav badge component**

Create `apps/web/src/features/games/components/LiveNavStatusBadge.tsx`:

```tsx
import { Fragment } from "react";

import type { LiveNavStatus, LiveNavStatusTone } from "../liveNavStatus";

type LiveNavStatusBadgeProps = {
  status: LiveNavStatus;
};

const toneClasses = {
  danger: {
    dot: "bg-red-300 shadow-[0_0_10px_rgba(252,165,165,0.55)]",
    text: "text-red-100",
  },
  done: {
    dot: "bg-slate-300 shadow-[0_0_10px_rgba(203,213,225,0.35)]",
    text: "text-slate-200",
  },
  good: {
    dot: "bg-teal-300 shadow-[0_0_10px_rgba(94,234,212,0.55)]",
    text: "text-teal-100",
  },
  neutral: {
    dot: "bg-sky-300 shadow-[0_0_10px_rgba(125,211,252,0.45)]",
    text: "text-sky-100",
  },
  warning: {
    dot: "bg-amber-300 shadow-[0_0_10px_rgba(252,211,77,0.5)]",
    text: "text-amber-100",
  },
} satisfies Record<LiveNavStatusTone, { dot: string; text: string }>;

export function LiveNavStatusBadge({ status }: LiveNavStatusBadgeProps) {
  const tone = toneClasses[status.tone];

  return (
    <div
      className={`live-nav-status flex min-w-0 shrink-0 flex-nowrap items-center gap-x-2 text-xs font-semibold ${tone.text}`}
      data-status-kind={status.kind}
      data-testid="live-nav-status"
    >
      <span
        aria-hidden="true"
        className={`h-2 w-2 shrink-0 rounded-full ${tone.dot}`}
      />
      <span className="shrink-0">{status.label}</span>
      {status.detailItems.map((item) => (
        <Fragment key={item}>
          <span aria-hidden="true" className="text-slate-500">
            ·
          </span>
          <span className="shrink-0 text-slate-300">{item}</span>
        </Fragment>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Run the related page test before wiring and verify no nav badge exists**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: existing tests pass, but no test expects `live-nav-status` yet.

### Task 3: Wire Live Page Navigation

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Add failing page expectations for combined nav status**

In `apps/web/src/pages/LiveGamePage.test.tsx`, update the live page test that currently checks `live-status-strip` inside `live-nav-context`.

Replace:

```ts
expect(
  within(liveNavContext).getByTestId("live-status-strip"),
).toBeInTheDocument();
```

with:

```ts
const navStatus = within(liveNavContext).getByTestId("live-nav-status");
expect(navStatus).toHaveTextContent("连接中");
expect(navStatus).toHaveAttribute("data-status-kind", "connecting");
expect(
  within(liveNavContext).queryByTestId("live-status-strip"),
).not.toBeInTheDocument();
```

In the same test, keep these assertions so the old split labels do not return:

```ts
expect(liveNavContext).not.toHaveTextContent("连接：连接中");
expect(liveNavContext).not.toHaveTextContent("节奏：");
expect(liveNavContext).not.toHaveTextContent("进行中");
```

Update the earlier live rendering test that opens the event source. Replace:

```ts
expect(screen.getByText("已连接")).toBeInTheDocument();
```

with:

```ts
expect(screen.getByTestId("live-nav-status")).toHaveTextContent("直播中");
expect(screen.getByTestId("live-nav-status")).toHaveTextContent("1x");
```

- [ ] **Step 2: Run the page tests and verify they fail**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL because `LiveGamePage` still renders `LiveStatusStrip` in the nav context.

- [ ] **Step 3: Wire derived status into `LiveGamePage`**

Modify imports in `apps/web/src/pages/LiveGamePage.tsx`.

Remove:

```ts
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
```

Add:

```ts
import { LiveNavStatusBadge } from "../features/games/components/LiveNavStatusBadge";
import { deriveLiveNavStatus } from "../features/games/liveNavStatus";
```

After `const director = useLiveDirector(...)`, add:

```ts
  const liveNavStatus = deriveLiveNavStatus({
    backlogCount: director.backlogCount,
    connectionState,
    hasCompletedTerminalEvent: terminalEvent?.type === "game_completed",
    hasFailedTerminalEvent: terminalEvent?.type === "game_failed",
    isPaused: director.isPaused,
    runStatus: run?.status ?? "queued",
    speed: director.speed,
  });
```

Replace the status strip in `topNavContext`:

```tsx
<LiveStatusStrip run={run} connectionState={connectionState} variant="nav" />
```

with:

```tsx
<LiveNavStatusBadge status={liveNavStatus} />
```

- [ ] **Step 4: Run the page tests and verify they pass**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

### Task 4: Verification and Cleanup

**Files:**
- Modify only if verification reveals a focused issue in files from Tasks 1-3.

- [ ] **Step 1: Run focused component and helper tests**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveNavStatus.test.ts src/features/games/components/LiveDirectorControls.test.tsx src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run the web test suite**

Run:

```bash
pnpm --dir apps/web exec vitest run
```

Expected: PASS.

- [ ] **Step 3: Run the web production build**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS with Vite build output and no TypeScript errors.

- [ ] **Step 4: Check diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Review final diff**

Run:

```bash
git diff -- apps/web/src/features/games/liveNavStatus.ts apps/web/src/features/games/liveNavStatus.test.ts apps/web/src/features/games/components/LiveNavStatusBadge.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx
```

Expected: the diff only adds the derived nav status helper, the nav badge, and live-page wiring/tests.
