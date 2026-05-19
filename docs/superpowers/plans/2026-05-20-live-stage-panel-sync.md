# Live Stage Panel Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Keep the live spectator side panels, bottom board, stage player cards, and narrative data synchronized to the director stage playback cursor instead of the latest SSE event.

**Architecture:** `LiveGamePage` remains responsible for the full SSE event stream and live navigation status. It derives a `stageEvents` window from `director.currentEventId`, then uses that window to derive `spectatorState`, `godViewState`, and the `events` passed into `LiveStageExperience`. Navigation status and run invalidation continue to use the complete `events` array.

**Tech Stack:** React, TypeScript, TanStack Query, Vitest, React Testing Library.

---

## File Structure

- Modify `apps/web/src/pages/LiveGamePage.tsx`: create the director before panel state derivation, derive `stageEvents`, pass `stageEvents` to `LiveStageExperience`, and keep run/nav status based on full `events`.
- Modify `apps/web/src/pages/LiveGamePage.test.tsx`: add a regression test that emits future state updates while the director is still showing an earlier cue, proving side panels do not reveal future state until the stage catches up.

### Task 1: Panel Sync Regression Test

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [x] **Step 1: Write the failing test**

Add this test near the existing director playback tests:

```tsx
it("syncs side panels to the director stage event window", async () => {
  vi.stubGlobal("EventSource", MockEventSource);
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(runningRunResponse()),
  );

  renderWithClient(
    <Routes>
      <Route path="/games/live/:runId" element={<LiveGamePage />} />
    </Routes>,
    "/games/live/run_1234abcd",
  );

  expect(await screen.findByText("实时观战")).toBeInTheDocument();
  const source = MockEventSource.instances[0];
  vi.useFakeTimers();

  act(() => {
    emitEvent(source, {
      id: 1,
      type: "game_started",
      payload: {
        players: [
          { name: "张三", role: "狼人", model: "deepseek-chat" },
          { name: "李四", role: "村民", model: "deepseek-chat" },
        ],
      },
    });
    emitEvent(source, { id: 2, type: "round_started", round: 1 });
    emitEvent(source, {
      id: 3,
      type: "phase_started",
      round: 1,
      phase: "day",
    });
    emitEvent(source, {
      id: 4,
      type: "state_updated",
      round: 1,
      phase: "day",
      payload: {
        active_players: ["张三"],
        exiled: "李四",
        public_text: "李四被放逐出局",
      },
    });
  });

  expect(
    within(screen.getByTestId("live-narrative-center")).getByText("对局开始"),
  ).toBeInTheDocument();
  expect(screen.getByTestId("god-view-intel-panel")).not.toHaveTextContent(
    "李四被放逐",
  );
  expect(screen.getByTestId("god-view-stage-player-card-李四")).not.toHaveAttribute(
    "data-card-state",
    "out",
  );

  act(() => {
    vi.advanceTimersByTime(20_000);
  });

  expect(screen.getByText("李四 被放逐出局")).toBeInTheDocument();
  expect(screen.getByTestId("god-view-stage-player-card-李四")).toHaveAttribute(
    "data-card-state",
    "out",
  );
  vi.useRealTimers();
});
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
pnpm --dir apps/web test --run src/pages/LiveGamePage.test.tsx -t "syncs side panels to the director stage event window"
```

Expected: FAIL because the right panel or player card uses full `events` and exposes the future `state_updated` before the director reaches event `4`.

### Task 2: LiveGamePage Stage Event Window

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Test: `apps/web/src/pages/LiveGamePage.test.tsx`

- [x] **Step 1: Move director before panel state derivation**

Keep `terminalEvent` and `canResumeRun` based on full `events`, keep `shouldStartAtTerminal`, then create `director` before deriving `spectatorState`.

- [x] **Step 2: Add `stageEvents`**

Add:

```ts
const currentEventId = director.currentEventId;
const stageEvents = useMemo(() => {
  if (currentEventId === null) {
    return EMPTY_EVENTS;
  }

  return events.filter((event) => event.id <= currentEventId);
}, [events, currentEventId]);
```

- [x] **Step 3: Derive panel state from `stageEvents`**

Change:

```ts
const spectatorState = useMemo(
  () => deriveLiveSpectatorState(events),
  [events],
);
```

to:

```ts
const spectatorState = useMemo(
  () => deriveLiveSpectatorState(stageEvents),
  [stageEvents],
);
```

Change the `deriveGodViewState` call to use `stageEvents` and update its dependency array.

- [x] **Step 4: Pass `stageEvents` into `LiveStageExperience`**

Change:

```tsx
events={events}
```

to:

```tsx
events={stageEvents}
```

- [x] **Step 5: Run the targeted test**

Run:

```bash
pnpm --dir apps/web test --run src/pages/LiveGamePage.test.tsx -t "syncs side panels to the director stage event window"
```

Expected: PASS.

### Task 3: Regression Suite Verification

**Files:**
- Verify: `apps/web/src/pages/LiveGamePage.test.tsx`
- Verify: `apps/web/src/pages/GamePlaybackPage.test.tsx`

- [x] **Step 1: Run live and playback page tests**

Run:

```bash
pnpm --dir apps/web test --run src/pages/LiveGamePage.test.tsx src/pages/GamePlaybackPage.test.tsx
```

Expected: PASS.

- [x] **Step 2: Run frontend build**

Run:

```bash
pnpm --dir apps/web build
```

Expected: exit code 0.

- [x] **Step 3: Review diff**

Run:

```bash
git diff -- apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx docs/superpowers/specs/2026-05-20-live-stage-panel-sync-design.md docs/superpowers/plans/2026-05-20-live-stage-panel-sync.md
```

Expected: diff only contains the design doc, plan doc, targeted regression test, and `LiveGamePage` data-flow change.
