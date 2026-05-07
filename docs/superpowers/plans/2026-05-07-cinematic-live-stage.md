# Cinematic Live Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the live spectator page's separate director card and seat panel with a cinematic round-table stage whose player avatars highlight the current speaker.

**Architecture:** Keep all data derivation in `LiveGamePage` and `deriveLiveSpectatorState`; move player rendering into `LiveDirectorStage` through explicit props. Use React and Tailwind-only markup for the stage, with small local helpers for role tone, avatar color, and seat positioning.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS v4, Radix Themes, Vitest, Testing Library.

---

## File Structure

- Modify `apps/web/src/features/games/components/LiveDirectorStage.tsx`
  - Owns the cinematic table layout, player avatar seats, active/focused/dead visual states, auto-follow switch, and center cue body.
- Modify `apps/web/src/pages/LiveGamePage.tsx`
  - Removes the standalone `LivePlayerPanel` column and passes player/focus state into `LiveDirectorStage`.
- Modify `apps/web/src/pages/LiveGamePage.test.tsx`
  - Updates existing page tests for the merged stage and adds assertions for active speaker and dead player state.
- Do not modify `apps/web/src/features/games/liveSpectator.ts`
  - Existing derived player data is sufficient for this visual change.
- Do not delete `apps/web/src/features/games/components/LivePlayerPanel.tsx`
  - Leave it in place to avoid broad cleanup while the new stage ships.

---

### Task 1: Update Page Tests For Merged Stage Behavior

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Replace the old seat panel assertion**

In `renders live events and completed replay link`, change the initial layout assertions from:

```tsx
expect(screen.getByText("观赛舞台")).toBeInTheDocument();
expect(screen.getByText("座位盘")).toBeInTheDocument();
expect(screen.getByText("剧情时间线")).toBeInTheDocument();
```

to:

```tsx
expect(screen.getByText("观赛舞台")).toBeInTheDocument();
expect(screen.getByText("圆桌座位")).toBeInTheDocument();
expect(screen.queryByText("座位盘")).not.toBeInTheDocument();
expect(screen.getByText("剧情时间线")).toBeInTheDocument();
```

- [ ] **Step 2: Add active speaker and dead player assertions**

After the existing `model_response_delta` expectations in `renders live events and completed replay link`, add a state update that eliminates `李四` and assert the seat labels:

```tsx
act(() => {
  source.emit("state_updated", {
    id: 6,
    type: "state_updated",
    run_id: "run_1234abcd",
    session_id: "session_20260424_120000_ab12cd34",
    created_at: "2026-04-24T12:00:04Z",
    round: 1,
    phase: "day",
    actor: null,
    action: null,
    payload: {
      active_players: ["张三"],
      exiled: "李四",
    },
  });
});

expect(screen.getByRole("button", { name: /张三/ })).toHaveAccessibleName(
  /发言中/,
);
expect(screen.getByRole("button", { name: /李四/ })).toHaveAccessibleName(
  /出局/,
);
```

Then renumber later emitted event ids in that test so `model_response_received` uses `id: 7` and `game_completed` uses `id: 8`.

- [ ] **Step 3: Replace the grid shrink test with the new layout test**

Replace `allows live grid columns to shrink inside wrapped panels` with:

```tsx
it("uses a stage-first live layout with a separate timeline column", async () => {
  vi.stubGlobal("EventSource", MockEventSource);
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(runningRunResponse()),
  );

  const { container } = renderWithClient(
    <Routes>
      <Route path="/games/live/:runId" element={<LiveGamePage />} />
    </Routes>,
    "/games/live/run_1234abcd",
  );

  expect(await screen.findByText("实时观战")).toBeInTheDocument();
  const liveGrid = container.querySelector('[data-testid="live-stage-layout"]');
  expect(liveGrid).not.toBeNull();
  const [stageColumn, eventsColumn] = Array.from(liveGrid!.children);

  expect(stageColumn).toHaveClass("min-w-0");
  expect(eventsColumn).toHaveClass("min-w-0");
});
```

- [ ] **Step 4: Update pinning assertions to use the stage seat class**

In `lets users pin a player and re-enable auto follow`, replace each `.toHaveClass("ring-2")` expectation with:

```tsx
expect(await screen.findByRole("button", { name: /张三/ })).toHaveClass(
  "is-focused",
);
```

For `李四`, use:

```tsx
expect(screen.getByRole("button", { name: /李四/ })).toHaveClass(
  "is-focused",
);
```

For the final auto-follow assertion, use:

```tsx
expect(screen.getByRole("button", { name: /张三/ })).toHaveClass(
  "is-focused",
);
```

- [ ] **Step 5: Run the focused test and confirm failure**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL because `圆桌座位`, `data-testid="live-stage-layout"`, `is-focused`, and active/dead seat labels are not implemented yet.

---

### Task 2: Expand LiveDirectorStage Props And Helpers

**Files:**
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`

- [ ] **Step 1: Replace imports and props**

At the top of `LiveDirectorStage.tsx`, replace the imports and prop type with:

```tsx
import { Badge, Switch } from "@radix-ui/themes";
import type { CSSProperties } from "react";

import type { DirectorCue } from "../liveDirector";
import { actionLabel, phaseLabel } from "../liveLabels";
import type { LivePlayer } from "../liveSpectator";

type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
  players: LivePlayer[];
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  autoFollow: boolean;
  onSelectPlayer: (name: string) => void;
  onAutoFollowChange: (value: boolean) => void;
};
```

- [ ] **Step 2: Add role and status helpers under `LiveDirectorStage`**

Use these helper constants and functions in the same file:

```tsx
const STATUS_LABELS: Record<LivePlayer["status"], string> = {
  waiting: "等待中",
  thinking: "思考中",
  requesting: "请求模型",
  streaming: "发言中",
  responded: "已返回",
  acted: "已行动",
  out: "出局",
};

const AVATAR_GRADIENTS = [
  "from-slate-700 to-slate-950",
  "from-stone-600 to-slate-950",
  "from-zinc-700 to-stone-950",
  "from-neutral-600 to-slate-900",
  "from-amber-900 to-slate-950",
  "from-red-950 to-slate-950",
];

function roleTone(role: string) {
  if (role.includes("狼")) {
    return {
      ring: "border-red-400 shadow-red-500/45",
      badge: "bg-red-950/80 text-red-100 ring-red-500/40",
      dot: "bg-red-400",
    };
  }
  if (role.includes("预言家")) {
    return {
      ring: "border-amber-300 shadow-amber-300/45",
      badge: "bg-amber-900/80 text-amber-100 ring-amber-400/50",
      dot: "bg-amber-300",
    };
  }
  if (role.includes("女巫")) {
    return {
      ring: "border-violet-300 shadow-violet-300/45",
      badge: "bg-violet-950/80 text-violet-100 ring-violet-400/50",
      dot: "bg-violet-300",
    };
  }
  if (role.includes("守卫") || role.includes("医生")) {
    return {
      ring: "border-cyan-300 shadow-cyan-300/35",
      badge: "bg-cyan-950/80 text-cyan-100 ring-cyan-400/40",
      dot: "bg-cyan-300",
    };
  }
  if (role.includes("猎人")) {
    return {
      ring: "border-sky-300 shadow-sky-300/35",
      badge: "bg-sky-950/80 text-sky-100 ring-sky-400/40",
      dot: "bg-sky-300",
    };
  }
  return {
    ring: "border-stone-300 shadow-stone-300/25",
    badge: "bg-stone-900/80 text-stone-100 ring-stone-400/30",
    dot: "bg-stone-300",
  };
}

function avatarGradient(name: string) {
  const charTotal = Array.from(name).reduce(
    (total, char) => total + char.charCodeAt(0),
    0,
  );
  return AVATAR_GRADIENTS[charTotal % AVATAR_GRADIENTS.length];
}

function avatarText(name: string) {
  return Array.from(name).slice(0, 2).join("");
}

function seatStyle(index: number, total: number): CSSProperties {
  const angle = -90 + (360 / Math.max(total, 1)) * index;
  const radiusX = 43;
  const radiusY = 38;
  const x = 50 + radiusX * Math.cos((angle * Math.PI) / 180);
  const y = 50 + radiusY * Math.sin((angle * Math.PI) / 180);

  return {
    left: `${x}%`,
    top: `${y}%`,
    transform: "translate(-50%, -50%)",
  };
}
```

- [ ] **Step 3: Keep existing label helpers**

Leave `importanceLabel` and `stageTone` in the file, but update `stageTone` in Task 3 to return dark stage accent classes.

---

### Task 3: Implement The Cinematic Stage Markup

**Files:**
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`

- [ ] **Step 1: Replace the empty state with the shared stage shell**

Remove the early branch that returns a Radix `Card` when `cue` is missing. Start `LiveDirectorStage` with:

```tsx
export function LiveDirectorStage({
  cue,
  backlogCount,
  isCatchingUp,
  players,
  activePlayerName,
  focusedPlayerName,
  autoFollow,
  onSelectPlayer,
  onAutoFollowChange,
}: LiveDirectorStageProps) {
  const tone = stageTone(cue);
  const focusedPlayer =
    players.find((player) => player.name === focusedPlayerName) ?? null;
  const title = cue?.title ?? "等待导播事件";
  const body = cue?.body ?? "对局运行已创建，正在等待下一条实时事件。";

  return (
    <section className={`relative overflow-hidden rounded-lg border border-amber-900/40 bg-slate-950 text-slate-100 shadow-2xl ${tone.surface}`}>
      {/* stage content from the next steps */}
    </section>
  );
}
```

- [ ] **Step 2: Add background, table, top status, and center cue**

Inside the returned `<section>`, add:

```tsx
<div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_8%,rgba(30,64,175,0.28),transparent_28%),radial-gradient(circle_at_50%_48%,rgba(146,64,14,0.42),transparent_42%),linear-gradient(180deg,#07111f_0%,#111827_48%,#030712_100%)]" />
<div className="absolute inset-x-0 top-0 h-32 bg-[linear-gradient(180deg,rgba(15,23,42,0.15),rgba(15,23,42,0.82)),repeating-linear-gradient(90deg,rgba(148,163,184,0.12)_0_1px,transparent_1px_72px)]" />

<div className="relative min-h-[38rem] px-4 py-4 sm:min-h-[42rem] sm:px-6 lg:min-h-[46rem]">
  <div className="mx-auto flex w-fit items-center gap-3 rounded-full border border-amber-500/50 bg-slate-950/85 px-4 py-2 text-sm shadow-[0_0_24px_rgba(245,158,11,0.24)]">
    <span className="text-slate-400">观赛舞台</span>
    <span className="font-semibold text-amber-200">
      {cue?.round ? `第 ${cue.round} 轮` : "等待回合"}
    </span>
    <span className="text-slate-500">|</span>
    <span className="font-semibold text-amber-100">
      {cue?.phase ? phaseLabel(cue.phase) : "阶段未开始"}
    </span>
  </div>

  <div className="absolute left-1/2 top-[52%] h-[58%] w-[78%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-amber-700/45 bg-[radial-gradient(circle_at_50%_45%,rgba(120,78,40,0.96),rgba(54,34,19,0.96)_48%,rgba(20,13,9,0.98)_76%)] shadow-[inset_0_0_70px_rgba(0,0,0,0.72),0_30px_90px_rgba(0,0,0,0.55)] sm:w-[70%]" />
  <div className="absolute left-1/2 top-[52%] h-[44%] w-[58%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-amber-400/20 shadow-[inset_0_0_45px_rgba(251,191,36,0.12)]" />
  <div className="absolute left-1/2 top-[45%] -translate-x-1/2 -translate-y-1/2 select-none text-7xl font-black text-amber-100/10 sm:text-9xl">
    狼
  </div>

  <div className="absolute left-1/2 top-[54%] z-10 w-[min(30rem,72vw)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-amber-500/30 bg-slate-950/70 p-4 text-center shadow-[0_20px_60px_rgba(0,0,0,0.42)] backdrop-blur-sm">
    <div className="mb-3 flex flex-wrap justify-center gap-2 text-xs">
      {cue ? (
        <>
          <Badge color="amber" variant="surface">#{cue.eventId}</Badge>
          <Badge color="gray" variant="surface">{importanceLabel(cue.importance)}</Badge>
        </>
      ) : null}
      <Badge color="gray" variant="surface">队列剩余：{backlogCount}</Badge>
      {isCatchingUp ? <Badge color="amber" variant="surface">自动追进度中</Badge> : null}
    </div>
    <h2 className="text-xl font-semibold text-amber-50 sm:text-2xl">{title}</h2>
    <div className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md border border-amber-500/20 bg-black/20 p-3 text-left text-sm leading-6 text-slate-200 sm:max-h-48 sm:text-base">
      {body}
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add player seats**

Still inside the relative stage `<div>`, after the center cue, add:

```tsx
<div aria-label="圆桌座位" className="absolute inset-0 z-20">
  <p className="sr-only">圆桌座位</p>
  {players.length === 0 ? (
    <p className="absolute left-1/2 top-[72%] -translate-x-1/2 text-sm text-slate-400">
      等待玩家加入
    </p>
  ) : (
    players.map((player, index) => {
      const isActive = player.name === activePlayerName && player.isAlive;
      const isFocused = player.name === focusedPlayerName;
      const role = roleTone(player.role);
      const lastAction = player.lastAction ? actionLabel(player.lastAction) : "";
      const status = player.isAlive
        ? isActive
          ? "发言中"
          : STATUS_LABELS[player.status]
        : "出局";

      return (
        <button
          aria-label={`${index + 1}号 ${player.name} ${player.role} ${status} ${lastAction} ${player.lastDetail}`}
          className={`absolute w-24 -translate-x-1/2 -translate-y-1/2 text-center transition duration-200 hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-200 sm:w-28 ${
            isFocused ? "is-focused" : ""
          } ${!player.isAlive ? "opacity-60 grayscale" : ""}`}
          key={player.name}
          onClick={() => onSelectPlayer(player.name)}
          style={seatStyle(index, players.length)}
          type="button"
        >
          <span className="mx-auto mb-1 flex h-7 w-7 items-center justify-center rounded-full border border-amber-300/50 bg-slate-950 text-xs font-semibold text-amber-100 shadow-md">
            {index + 1}
          </span>
          <span className={`mx-auto flex h-16 w-16 items-center justify-center rounded-full border-2 bg-gradient-to-br ${avatarGradient(player.name)} text-lg font-bold text-slate-100 shadow-lg ${role.ring} ${
            isActive ? "border-amber-200 shadow-[0_0_26px_rgba(250,204,21,0.85),0_0_42px_rgba(34,197,94,0.42)]" : ""
          } ${isFocused ? "ring-2 ring-amber-100 ring-offset-2 ring-offset-slate-950" : ""}`}>
            {avatarText(player.name)}
          </span>
          <span className="mt-1 block truncate text-sm font-semibold text-slate-50 drop-shadow">
            {player.name}
          </span>
          <span className={`mx-auto mt-1 inline-flex max-w-full items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ${role.badge}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${player.isAlive ? role.dot : "bg-slate-400"}`} />
            <span className="truncate">{player.role}</span>
          </span>
          <span className={`mx-auto mt-1 block w-fit rounded-md px-2 py-0.5 text-[11px] font-semibold ${
            isActive ? "bg-green-500/20 text-green-200 ring-1 ring-green-300/40" : "bg-black/35 text-slate-300"
          }`}>
            {status}
          </span>
        </button>
      );
    })
  )}
</div>
```

- [ ] **Step 4: Add bottom focus summary and auto-follow switch**

Inside the stage `<div>`, before it closes, add:

```tsx
<div className="absolute inset-x-4 bottom-4 z-30 flex flex-col gap-3 rounded-lg border border-amber-500/25 bg-slate-950/78 p-3 text-sm text-slate-200 backdrop-blur sm:inset-x-6 sm:flex-row sm:items-center sm:justify-between">
  <div className="min-w-0">
    <p className="text-xs font-semibold text-amber-200">当前关注</p>
    <p className="mt-1 truncate">
      {focusedPlayer
        ? `${focusedPlayer.name} · ${focusedPlayer.role} · ${
            focusedPlayer.lastAction ? actionLabel(focusedPlayer.lastAction) : "等待行动"
          }`
        : "等待玩家行动"}
    </p>
  </div>
  <label className="flex shrink-0 items-center gap-2 text-xs text-slate-300">
    <Switch
      checked={autoFollow}
      color="amber"
      onCheckedChange={onAutoFollowChange}
    />
    自动跟随
  </label>
</div>
```

- [ ] **Step 5: Update `stageTone` for dark surfaces**

Replace `stageTone` with:

```tsx
function stageTone(cue: DirectorCue | null) {
  if (!cue) {
    return { surface: "" };
  }
  if (cue.importance === "terminal") {
    return { surface: "ring-1 ring-emerald-400/30" };
  }
  if (cue.phase === "night") {
    return { surface: "ring-1 ring-indigo-300/25" };
  }
  if (cue.phase === "vote") {
    return { surface: "ring-1 ring-amber-300/30" };
  }
  if (cue.importance === "key") {
    return { surface: "ring-1 ring-cyan-300/25" };
  }
  return { surface: "" };
}
```

- [ ] **Step 6: Run the focused test and confirm component failures are resolved**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL only because `LiveGamePage` has not passed the new props and still renders the old `LivePlayerPanel`.

---

### Task 4: Wire The Stage Into LiveGamePage

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.tsx`

- [ ] **Step 1: Remove the old player panel import**

Delete:

```tsx
import { LivePlayerPanel } from "../features/games/components/LivePlayerPanel";
```

- [ ] **Step 2: Replace the three-column layout**

Replace:

```tsx
<div className="mt-4 grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)_22rem]">
  <div className="order-2 min-w-0 lg:order-1">
    <LivePlayerPanel
      activePlayerName={spectatorState.activePlayerName}
      autoFollow={autoFollow}
      focusedPlayerName={focusedPlayerName}
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
  </div>
  <div className="order-1 min-w-0 space-y-3 lg:order-2">
    <LiveDirectorStage
      backlogCount={director.backlogCount}
      cue={director.currentCue}
      isCatchingUp={director.isCatchingUp}
    />
    <LiveDirectorControls
      backlogCount={director.backlogCount}
      isCatchingUp={director.isCatchingUp}
      isPaused={director.isPaused}
      onCatchUpToLatest={director.catchUpToLatest}
      onSpeedChange={director.setSpeed}
      onTogglePaused={director.togglePaused}
      speed={director.speed}
    />
  </div>
  <Card asChild size="1">
    <section className="order-3 min-w-0 overflow-hidden lg:order-3 lg:max-h-[calc(100vh-8rem)] lg:overflow-auto">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-950">
          剧情时间线
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          关键阶段、行动和结算
        </p>
      </div>
      <LiveEventTimeline
        currentEventId={director.currentEventId}
        events={events}
        variant="story"
      />
      <details className="border-t border-slate-200">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">
          调试事件
        </summary>
        <LiveEventTimeline
          currentEventId={director.currentEventId}
          events={events}
        />
      </details>
    </section>
  </Card>
</div>
```

with:

```tsx
<div
  className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]"
  data-testid="live-stage-layout"
>
  <div className="min-w-0 space-y-3">
    <LiveDirectorStage
      activePlayerName={autoFocusName}
      autoFollow={autoFollow}
      backlogCount={director.backlogCount}
      cue={director.currentCue}
      focusedPlayerName={focusedPlayerName}
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
    <LiveDirectorControls
      backlogCount={director.backlogCount}
      isCatchingUp={director.isCatchingUp}
      isPaused={director.isPaused}
      onCatchUpToLatest={director.catchUpToLatest}
      onSpeedChange={director.setSpeed}
      onTogglePaused={director.togglePaused}
      speed={director.speed}
    />
  </div>
  <Card asChild size="1">
    <section className="min-w-0 overflow-hidden xl:max-h-[calc(100vh-8rem)] xl:overflow-auto">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-950">
          剧情时间线
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          关键阶段、行动和结算
        </p>
      </div>
      <LiveEventTimeline
        currentEventId={director.currentEventId}
        events={events}
        variant="story"
      />
      <details className="border-t border-slate-200">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">
          调试事件
        </summary>
        <LiveEventTimeline
          currentEventId={director.currentEventId}
          events={events}
        />
      </details>
    </section>
  </Card>
</div>
```

Keep the timeline section content exactly as shown so the story timeline and debug drawer continue to work.

- [ ] **Step 3: Run the focused test**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: PASS for the live page test file.

---

### Task 5: Verify And Browser-Polish The Stage

**Files:**
- Modify if needed: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify if needed: `apps/web/src/pages/LiveGamePage.tsx`

- [ ] **Step 1: Run all frontend tests**

Run:

```bash
cd apps/web && pnpm test -- --run
```

Expected: PASS.

- [ ] **Step 2: Run production build**

Run:

```bash
cd apps/web && pnpm build
```

Expected: PASS with Vite build output and no TypeScript errors.

- [ ] **Step 3: Verify the existing local page in the browser**

Open or reload:

```text
http://127.0.0.1:5173/games/live/run_28148690ed8d
```

Expected:

- The first major live area is a dark round-table stage.
- Player avatars surround the table.
- The current speaking or acting player has a gold/green glow and `发言中`.
- Clicking another player moves the visible focus ring to that avatar and turns off auto-follow.
- The timeline remains visible in the right column on desktop.
- On a narrow viewport, the stage appears before the timeline and the avatar labels remain readable.

- [ ] **Step 4: Commit implementation**

Stage only the files changed for this feature:

```bash
git add apps/web/src/features/games/components/LiveDirectorStage.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx docs/superpowers/plans/2026-05-07-cinematic-live-stage.md
git commit -m "feat: add cinematic live spectator stage"
```
