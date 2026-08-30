# Mobile Live Record Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mobile historical live replay so saved game records can be opened from history or replay summary and played inside the mobile live theater.

**Architecture:** Extract the current mobile live theater presentation from `LivePage` into a reusable component. Keep `LivePage` as the active SSE-run container, add `LiveReplayPage` as the saved playback-event container, and route both containers into the shared theater.

**Tech Stack:** React 19, React Router 7, TanStack Query, Vitest, Testing Library, `@werewolf-arena/game-client`.

---

## File Structure

- Create `apps/mobile-web/src/components/MobileLiveTheater.tsx`: reusable full-screen mobile theater UI. It owns no API calls and renders from derived props and callbacks.
- Modify `apps/mobile-web/src/pages/LivePage.tsx`: keep live data loading, live event derivation, resume mutation, and navigation; remove theater presentation functions now owned by `MobileLiveTheater`.
- Create `apps/mobile-web/src/pages/LiveReplayPage.tsx`: fetch `getGamePlayback`, drive `useLiveDirector` from saved events, derive visible playback state, and render `MobileLiveTheater`.
- Modify `apps/mobile-web/src/routes/definitions.tsx`: register `/games/:gameId/live-replay`.
- Modify `apps/mobile-web/src/pages/HistoryPage.tsx`: add the history-card "直播回放" link.
- Modify `apps/mobile-web/src/pages/PlaybackPage.tsx`: add the "导入直播页播放" link while preserving the summary view.
- Modify `apps/mobile-web/src/pages/HistoryPage.test.tsx`: cover the new history entry point.
- Modify `apps/mobile-web/src/pages/PlaybackPage.test.tsx`: cover the replay-summary entry point.
- Create `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`: cover saved playback fetching, default start, pause behavior, phase selection, and resumable records.

---

### Task 1: Add History Entry Point

**Files:**
- Modify: `apps/mobile-web/src/pages/HistoryPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/HistoryPage.tsx`

- [ ] **Step 1: Write the failing history route test**

Update `renderHistoryRoute` in `apps/mobile-web/src/pages/HistoryPage.test.tsx` so the memory router knows the new target:

```tsx
function renderHistoryRoute() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      { path: "/history", element: <HistoryPage /> },
      { path: "/games/:gameId/live", element: <h1>实时观战</h1> },
      { path: "/games/:gameId/live-replay", element: <h1>历史直播回放</h1> },
      { path: "/games/:gameId/replay", element: <h1>移动复盘</h1> },
    ],
    { initialEntries: ["/history"] },
  );

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { router };
}
```

In `renders resumable sessions with resume and replay actions`, add this assertion after the existing "查看复盘" assertion:

```tsx
expect(
  screen.getByRole("link", { name: "直播回放 session-1" }),
).toHaveAttribute("href", "/games/session-1/live-replay");
```

In `does not show resume for partial sessions without a checkpoint`, add this assertion after the resume-button absence assertion:

```tsx
expect(
  screen.getByRole("link", { name: "直播回放 session-1" }),
).toHaveAttribute("href", "/games/session-1/live-replay");
```

In `shows replay for complete non-resumable sessions`, add this assertion after the resume-button absence assertion:

```tsx
expect(
  screen.getByRole("link", { name: "直播回放 session-1" }),
).toHaveAttribute("href", "/games/session-1/live-replay");
```

- [ ] **Step 2: Run the history test and verify it fails**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/HistoryPage.test.tsx
```

Expected: FAIL with Testing Library unable to find a link named `直播回放 session-1`.

- [ ] **Step 3: Implement the history-card link**

In `apps/mobile-web/src/pages/HistoryPage.tsx`, update the `mobile-session-actions` block inside `HistorySessionCard` so it renders the live-replay link before the existing replay-summary link:

```tsx
      <div className="mobile-session-actions">
        {canResume ? (
          <button
            aria-label={`继续对局 ${session.session_id}`}
            className="mobile-button mobile-button-primary"
            disabled={isResuming}
            onClick={onResume}
            type="button"
          >
            {isResuming ? "继续中" : "继续对局"}
          </button>
        ) : null}
        <Link
          aria-label={`直播回放 ${session.session_id}`}
          className="mobile-button mobile-session-link"
          to={`/games/${session.session_id}/live-replay`}
        >
          直播回放
        </Link>
        <Link
          aria-label={`查看复盘 ${session.session_id}`}
          className="mobile-button mobile-session-link"
          to={`/games/${session.session_id}/replay`}
        >
          查看复盘
        </Link>
      </div>
```

- [ ] **Step 4: Run the history test and verify it passes**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/HistoryPage.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit the history entry point**

Run:

```bash
git add apps/mobile-web/src/pages/HistoryPage.tsx apps/mobile-web/src/pages/HistoryPage.test.tsx
git commit -m "feat(mobile): add live replay history action"
```

---

### Task 2: Add Replay Summary Entry Point

**Files:**
- Modify: `apps/mobile-web/src/pages/PlaybackPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/PlaybackPage.tsx`

- [ ] **Step 1: Write the failing replay-summary link test**

Update `renderPlaybackRoute` in `apps/mobile-web/src/pages/PlaybackPage.test.tsx` so it includes the live-replay target route:

```tsx
function renderPlaybackRoute() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      { path: "/games/:gameId/replay", element: <PlaybackPage /> },
      { path: "/games/:gameId/live-replay", element: <h1>历史直播回放</h1> },
    ],
    { initialEntries: ["/games/session-1/replay"] },
  );

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
```

In `renders mobile playback details for the replay route game id`, add this assertion before the `getGamePlayback` assertion:

```tsx
expect(
  screen.getByRole("link", { name: "导入直播页播放" }),
).toHaveAttribute("href", "/games/session-1/live-replay");
```

- [ ] **Step 2: Run the replay-summary test and verify it fails**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/PlaybackPage.test.tsx
```

Expected: FAIL with Testing Library unable to find a link named `导入直播页播放`.

- [ ] **Step 3: Implement the replay-summary link**

In `apps/mobile-web/src/pages/PlaybackPage.tsx`, change the import from React Router to include `Link`:

```tsx
import { Link, useParams } from "react-router-dom";
```

Replace the header with this version:

```tsx
      <header className="mobile-page-section">
        <h1>移动复盘</h1>
        {gameId ? (
          <Link
            className="mobile-button mobile-session-link"
            to={`/games/${gameId}/live-replay`}
          >
            导入直播页播放
          </Link>
        ) : null}
      </header>
```

- [ ] **Step 4: Run the replay-summary test and verify it passes**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/PlaybackPage.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit the replay-summary entry point**

Run:

```bash
git add apps/mobile-web/src/pages/PlaybackPage.tsx apps/mobile-web/src/pages/PlaybackPage.test.tsx
git commit -m "feat(mobile): link replay summary to live playback"
```

---

### Task 3: Extract Shared Mobile Live Theater

**Files:**
- Create: `apps/mobile-web/src/components/MobileLiveTheater.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
- Test: `apps/mobile-web/src/pages/LivePage.test.tsx`

- [ ] **Step 1: Run the existing live-page tests as the refactor safety net**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: PASS before refactoring. If this fails, stop and inspect the pre-existing failure before moving code.

- [ ] **Step 2: Create the shared theater component**

Create `apps/mobile-web/src/components/MobileLiveTheater.tsx` with these imports and public types:

```tsx
import { Link } from "react-router-dom";

import {
  deriveGodViewState,
  resolveAvatarImageUrl,
  useLiveDirector,
  type GameRunStatus,
  type GodViewPlayer,
  type LiveGameEvent,
  type LivePhaseSegment,
  type RuleSetSummary,
} from "@werewolf-arena/game-client";

type LiveDirectorControlsState = ReturnType<typeof useLiveDirector>;
type GodViewState = ReturnType<typeof deriveGodViewState>;

export type MobileLiveTheaterRun = {
  session_id: string;
  status: GameRunStatus | (string & {});
  rule_set?: RuleSetSummary | null;
};

export type MobileLiveTheaterProps = {
  canResumeRun: boolean;
  currentEvent: LiveGameEvent | null;
  director: LiveDirectorControlsState;
  godViewState: GodViewState;
  liveStatusLabel: string;
  onBack: () => void;
  onSelectPhase: (segment: LivePhaseSegment) => void;
  onResumeRun: () => void;
  phaseSegments: LivePhaseSegment[];
  replayLinkVisible: boolean;
  resumeIsPending: boolean;
  run: MobileLiveTheaterRun;
  terminalEvent: LiveGameEvent | undefined;
};
```

Then move these existing declarations from `LivePage.tsx` into `MobileLiveTheater.tsx` without changing their rendered markup or class names:

```tsx
export function MobileLiveTheater(props: MobileLiveTheaterProps) {
  const {
    canResumeRun,
    currentEvent,
    director,
    godViewState,
    liveStatusLabel,
    onBack,
    onSelectPhase,
    onResumeRun,
    phaseSegments,
    replayLinkVisible,
    resumeIsPending,
    run,
    terminalEvent,
  } = props;
  const currentPlayer = getCurrentTheaterPlayer(godViewState);
  const { left, right } = splitPlayersForColumns(godViewState.players);

  return (
    <section className="mobile-live-theater" aria-label="实时观战剧场">
      <MobileLiveTheaterTopBar
        liveStatusLabel={liveStatusLabel}
        onBack={onBack}
        onSelectPhase={onSelectPhase}
        phaseSegments={phaseSegments}
        ruleName={run.rule_set?.name ?? "实时对局"}
      />
      <LiveSkyBanner
        dayNightLabel={godViewState.dayNightLabel}
        phaseLabel={godViewState.phaseLabel}
      />
      <section className="mobile-live-seat-stage" aria-label="玩家席位">
        <LiveSeatColumn players={left} side="left" />
        <LiveCenterStage
          currentEvent={currentEvent}
          currentPlayer={currentPlayer}
          godViewState={godViewState}
        />
        <LiveSeatColumn players={right} side="right" />
      </section>
      <LiveTheaterControls
        canResumeRun={canResumeRun}
        currentPlayer={currentPlayer}
        director={director}
        godViewState={godViewState}
        onResumeRun={onResumeRun}
        replayLinkVisible={replayLinkVisible}
        resumeIsPending={resumeIsPending}
        run={run}
        terminalEvent={terminalEvent}
      />
    </section>
  );
}
```

Move the existing helper/component bodies unchanged for:

- `MobileLiveTheaterTopBar`, renamed from `LiveTheaterTopBar` and exported
- `LiveSkyBanner`
- `LiveSeatColumn`
- `LiveSeatAvatar`
- `LiveCenterStage`
- `LiveTheaterControls`
- `getCurrentTheaterPlayer`
- `splitPlayersForColumns`
- `avatarInitial`
- `roleShortLabel`
- `isTerminalRunStatus`

Inside the moved `LiveTheaterControls`, replace the old replay link condition:

```tsx
        {isTerminalRunStatus(run.status) || terminalEvent ? (
```

with the explicit prop:

```tsx
        {replayLinkVisible ? (
```

Keep the link target:

```tsx
          <Link
            className="mobile-button mobile-live-link"
            to={`/games/${run.session_id}/replay`}
          >
            复盘
          </Link>
```

- [ ] **Step 3: Update `LivePage` to use the shared component**

In `apps/mobile-web/src/pages/LivePage.tsx`, add this import:

```tsx
import {
  MobileLiveTheater,
  MobileLiveTheaterTopBar,
} from "../components/MobileLiveTheater";
```

Remove the import of `Link`, `resolveAvatarImageUrl`, `GodViewPlayer`, and `LivePhaseSegment` from `LivePage.tsx` if they are only used by the moved theater code.

Replace the local `LiveTheater` usage with:

```tsx
        <MobileLiveTheater
          canResumeRun={canResumeRun}
          currentEvent={currentEvent}
          director={director}
          godViewState={godViewState}
          liveStatusLabel={liveStatus.label}
          onBack={() => navigateBackToGames(navigate)}
          onSelectPhase={(segment) =>
            director.seekToEventId(segment.startEventId)
          }
          onResumeRun={() => resumeMutation.mutate(run.session_id)}
          phaseSegments={phaseSegments}
          replayLinkVisible={isTerminalRunStatus(run.status) || Boolean(terminalEvent)}
          resumeIsPending={resumeMutation.isPending}
          run={run}
          terminalEvent={terminalEvent}
        />
```

Update the loading shell at the top of `LivePage` to use the exported top bar:

```tsx
      {!run && runQuery.isPending ? (
        <section className="mobile-live-theater" aria-label="实时观战剧场">
          <MobileLiveTheaterTopBar
            liveStatusLabel={liveStatus.label}
            onBack={() => navigateBackToGames(navigate)}
            ruleName="实时对局"
          />
        </section>
      ) : null}
```

After this change, remove the local `LiveTheater`, `LiveTheaterTopBar`, and other moved presentational declarations from `LivePage.tsx`.

- [ ] **Step 4: Run the live-page tests and verify they pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: PASS. The existing style assertions should still pass because class names and CSS remain stable.

- [ ] **Step 5: Commit the extraction**

Run:

```bash
git add apps/mobile-web/src/components/MobileLiveTheater.tsx apps/mobile-web/src/pages/LivePage.tsx
git commit -m "refactor(mobile): share live theater presentation"
```

---

### Task 4: Add Historical Live Replay Page

**Files:**
- Create: `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`
- Create: `apps/mobile-web/src/pages/LiveReplayPage.tsx`
- Modify: `apps/mobile-web/src/routes/definitions.tsx`

- [ ] **Step 1: Write the failing historical playback page tests**

Create `apps/mobile-web/src/pages/LiveReplayPage.test.tsx` with this test suite:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveReplayPage } from "./LiveReplayPage";
import type { GamePlayback, GameRun, LiveGameEvent } from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  getGamePlayback: vi.fn(),
  resumeGameRun: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    getGamePlayback: gameClientMocks.getGamePlayback,
    resumeGameRun: gameClientMocks.resumeGameRun,
  };
});

const gameStartedEvent: LiveGameEvent = {
  id: 1,
  type: "game_started",
  run_id: "playback_session-1",
  session_id: "session-1",
  created_at: "2026-06-19T00:00:00Z",
  round: 1,
  phase: "day",
  actor: null,
  action: null,
  payload: {
    players: [
      { name: "阿青", role: "villager", model: "test-model" },
      { name: "白石", role: "werewolf", model: "test-model" },
      { name: "南风", role: "seer", model: "test-model" },
      { name: "木子", role: "witch", model: "test-model" },
    ],
  },
};

const phaseStartedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "phase_started",
  round: 1,
  phase: "day",
  payload: { active_players: ["阿青", "白石", "南风", "木子"] },
};

const requestStartedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 3,
  type: "model_request_started",
  actor: "阿青",
  action: "debate",
  payload: { request_id: "req-1" },
};

const speakingDeltaEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 4,
  type: "model_response_delta",
  actor: "阿青",
  action: "debate",
  payload: {
    request_id: "req-1",
    visible_text: "我先听后置位发言。",
  },
};

const completedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 5,
  type: "game_completed",
  round: null,
  phase: null,
  payload: { winner: "villagers" },
};

const failedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 5,
  type: "game_failed",
  round: null,
  phase: null,
  payload: { error: "模型中断" },
};

const resumedRun: GameRun = {
  run_id: "run-resumed",
  session_id: "session-1",
  villager_model: "test-model",
  werewolf_model: "test-model",
  seed: null,
  max_rounds: 8,
  winner: null,
  status: "queued",
  created_at: "2026-06-19T00:00:00Z",
  started_at: null,
  completed_at: null,
  error: null,
  event_count: 0,
};

function buildPlayback(overrides: Partial<GamePlayback> = {}): GamePlayback {
  return {
    session_id: "session-1",
    status: "complete",
    rule_set: {
      id: "classic_8",
      version: "test",
      name: "经典 8 人",
      player_count: 8,
      roles: [],
    },
    resumable: false,
    events: [
      gameStartedEvent,
      phaseStartedEvent,
      requestStartedEvent,
      speakingDeltaEvent,
      completedEvent,
    ],
    ...overrides,
  };
}

function renderLiveReplayRoute(initialEntry = "/games/session-1/live-replay") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      { path: "/games/:gameId/live-replay", element: <LiveReplayPage /> },
      { path: "/games/:gameId/live", element: <h1>实时观战</h1> },
      { path: "/games/:gameId/replay", element: <h1>移动复盘</h1> },
      { path: "/history", element: <h1>对局历史</h1> },
    ],
    { initialEntries: [initialEntry] },
  );

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { router };
}

describe("LiveReplayPage", () => {
  beforeEach(() => {
    gameClientMocks.getGamePlayback.mockResolvedValue(buildPlayback());
    gameClientMocks.resumeGameRun.mockResolvedValue(resumedRun);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads saved playback events and starts from the first event", async () => {
    renderLiveReplayRoute();

    expect(
      await screen.findByRole("heading", { name: "历史直播回放" }),
    ).toHaveClass("mobile-sr-only");
    expect(await screen.findAllByText("经典 8 人")).toHaveLength(1);
    const stage = await screen.findByRole("region", { name: "当前舞台" });
    expect(within(stage).getByText("game_started")).toBeVisible();
    expect(within(stage).queryByText("model_response_delta")).not.toBeInTheDocument();
    expect(gameClientMocks.getGamePlayback).toHaveBeenCalledWith("session-1");
  });

  it("does not reveal a future speaker delta while playback is paused", async () => {
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "暂停" }));
    expect(screen.getByRole("button", { name: "继续" })).toBeVisible();

    const stage = await screen.findByRole("region", { name: "当前舞台" });
    expect(within(stage).queryByText("阿青")).not.toBeInTheDocument();
    expect(within(stage).queryByText("model_response_delta")).not.toBeInTheDocument();
  });

  it("renders the mobile phase selector for saved playback", async () => {
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(
      await screen.findByRole("button", { name: "选择阶段，当前第1天" }),
    );
    expect(screen.getByRole("button", { name: "跳转到第1天" })).toBeVisible();
  });

  it("does not show resume for completed records", async () => {
    renderLiveReplayRoute();

    await screen.findByText("经典 8 人");
    expect(
      screen.queryByRole("button", { name: "继续对局" }),
    ).not.toBeInTheDocument();
  });

  it("resumes failed resumable records and navigates to the new live run", async () => {
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        status: "partial",
        resumable: true,
        events: [gameStartedEvent, failedEvent],
      }),
    );
    const user = userEvent.setup();
    const { router } = renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "继续对局" }));

    await waitFor(() => {
      expect(gameClientMocks.resumeGameRun).toHaveBeenCalledWith("session-1");
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/games/run-resumed/live");
    });
  });
});
```

- [ ] **Step 2: Run the new page test and verify it fails**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LiveReplayPage.test.tsx
```

Expected: FAIL with `Cannot find module './LiveReplayPage'`.

- [ ] **Step 3: Implement `LiveReplayPage`**

Create `apps/mobile-web/src/pages/LiveReplayPage.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  buildLivePhaseSegments,
  deriveGodViewState,
  deriveLiveSpectatorState,
  getGamePlayback,
  resumeGameRun,
  useLiveDirector,
  type GamePlayback,
  type GameRunStatus,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";

import {
  MobileLiveTheater,
  type MobileLiveTheaterRun,
} from "../components/MobileLiveTheater";

const EMPTY_EVENTS: LiveGameEvent[] = [];

export function LiveReplayPage() {
  const { gameId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const playbackQuery = useQuery({
    queryKey: ["game-playback", gameId],
    queryFn: () => getGamePlayback(gameId ?? ""),
    enabled: Boolean(gameId),
  });
  const playback = playbackQuery.data;
  const allEvents = playback?.events ?? EMPTY_EVENTS;
  const director = useLiveDirector(allEvents, {
    resetKey: gameId,
    startAtLatestTerminal: false,
  });
  const currentEventId = director.currentEventId;
  const stageEvents = useMemo(() => {
    if (currentEventId === null) {
      return EMPTY_EVENTS;
    }

    return allEvents.filter((event) => event.id <= currentEventId);
  }, [allEvents, currentEventId]);
  const currentEvent = stageEvents.at(-1) ?? null;
  const phaseSegments = useMemo(
    () => buildLivePhaseSegments(allEvents, currentEventId),
    [allEvents, currentEventId],
  );
  const spectatorState = useMemo(
    () => deriveLiveSpectatorState(stageEvents),
    [stageEvents],
  );
  const godViewState = useMemo(
    () =>
      deriveGodViewState(
        stageEvents,
        spectatorState,
        playback?.rule_set?.name ?? "历史回放",
        { sheriffEnabled: playback?.rule_set?.sheriff_enabled },
      ),
    [
      playback?.rule_set?.name,
      playback?.rule_set?.sheriff_enabled,
      spectatorState,
      stageEvents,
    ],
  );
  const visibleTerminalEvent = terminalEventFor(stageEvents);
  const terminalEvent = terminalEventFor(allEvents);
  const run = playback
    ? playbackRun(playback, statusForVisiblePlayback(visibleTerminalEvent))
    : null;
  const resumeMutation = useMutation({
    mutationFn: (sessionId: string) => resumeGameRun(sessionId),
    onSuccess: (newRun) => {
      void queryClient.invalidateQueries({ queryKey: ["games"] });
      void queryClient.invalidateQueries({ queryKey: ["game-playback", gameId] });
      navigate(`/games/${newRun.run_id}/live`);
    },
  });
  const canResumeRun = playback?.resumable === true;

  return (
    <main className="mobile-page mobile-live-page">
      <h1 className="mobile-sr-only">历史直播回放</h1>

      {playbackQuery.isPending ? (
        <p className="mobile-status-banner" role="status">
          正在准备历史播放台...
        </p>
      ) : null}
      {playbackQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取历史回放
        </p>
      ) : null}
      {resumeMutation.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法继续对局
        </p>
      ) : null}

      {run ? (
        <MobileLiveTheater
          canResumeRun={canResumeRun}
          currentEvent={currentEvent}
          director={director}
          godViewState={godViewState}
          liveStatusLabel={playbackStatusLabel({
            isPaused: director.isPaused,
            terminalEvent: visibleTerminalEvent,
          })}
          onBack={() => navigateBackToHistory(navigate)}
          onSelectPhase={(segment) =>
            director.seekToEventId(segment.startEventId)
          }
          onResumeRun={() => resumeMutation.mutate(run.session_id)}
          phaseSegments={phaseSegments}
          replayLinkVisible={true}
          resumeIsPending={resumeMutation.isPending}
          run={run}
          terminalEvent={terminalEvent}
        />
      ) : null}
    </main>
  );
}

function terminalEventFor(events: LiveGameEvent[]) {
  return events.find(
    (event) => event.type === "game_completed" || event.type === "game_failed",
  );
}

function statusForVisiblePlayback(
  terminalEvent: LiveGameEvent | undefined,
): GameRunStatus {
  if (terminalEvent?.type === "game_completed") {
    return "completed";
  }

  if (terminalEvent?.type === "game_failed") {
    return "failed";
  }

  return "running";
}

function playbackRun(
  playback: GamePlayback,
  status: GameRunStatus,
): MobileLiveTheaterRun {
  return {
    rule_set: playback.rule_set,
    session_id: playback.session_id,
    status,
  };
}

function playbackStatusLabel(input: {
  isPaused: boolean;
  terminalEvent: LiveGameEvent | undefined;
}) {
  if (input.terminalEvent?.type === "game_completed") {
    return "已完成";
  }

  if (input.terminalEvent?.type === "game_failed") {
    return "对局失败";
  }

  return input.isPaused ? "已暂停" : "历史回放";
}

function navigateBackToHistory(navigate: ReturnType<typeof useNavigate>) {
  const historyState = window.history.state as { idx?: number } | null;
  if (typeof historyState?.idx === "number" && historyState.idx > 0) {
    navigate(-1);
    return;
  }

  navigate("/history");
}
```

- [ ] **Step 4: Register the mobile route**

In `apps/mobile-web/src/routes/definitions.tsx`, import the page:

```tsx
import { LiveReplayPage } from "../pages/LiveReplayPage";
```

Add the route next to the live and replay routes:

```tsx
      { path: "games/:gameId/live", element: <LivePage /> },
      { path: "games/:gameId/live-replay", element: <LiveReplayPage /> },
      { path: "games/:gameId/replay", element: <PlaybackPage /> },
```

- [ ] **Step 5: Run the historical playback tests and verify they pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LiveReplayPage.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit the historical live replay page**

Run:

```bash
git add apps/mobile-web/src/pages/LiveReplayPage.tsx apps/mobile-web/src/pages/LiveReplayPage.test.tsx apps/mobile-web/src/routes/definitions.tsx
git commit -m "feat(mobile): play records in live theater"
```

---

### Task 5: Final Verification

**Files:**
- Verify: `apps/mobile-web/src/pages/HistoryPage.test.tsx`
- Verify: `apps/mobile-web/src/pages/PlaybackPage.test.tsx`
- Verify: `apps/mobile-web/src/pages/LivePage.test.tsx`
- Verify: `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`
- Verify: `apps/mobile-web/src/routes/definitions.tsx`

- [ ] **Step 1: Run the focused mobile page tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/HistoryPage.test.tsx src/pages/PlaybackPage.test.tsx src/pages/LivePage.test.tsx src/pages/LiveReplayPage.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run the full mobile test suite**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run
```

Expected: PASS.

- [ ] **Step 3: Run the mobile build**

Run:

```bash
pnpm --dir apps/mobile-web build
```

Expected: PASS with TypeScript and Vite build completing successfully.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected: only intentionally uncommitted user changes, if any. All files touched by this plan should either be committed by the task commits or intentionally left unstaged for review.
