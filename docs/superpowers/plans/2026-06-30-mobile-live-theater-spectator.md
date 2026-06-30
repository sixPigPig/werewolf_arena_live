# Mobile Live Theater Spectator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the mobile `/games/:gameId/live` spectator page into a full-screen theater-style live room with top return navigation, side seat columns, a central stage, and preserved live controls.

**Architecture:** Keep the feature inside the existing mobile page and stylesheet: `LivePage.tsx` owns data fetching, director controls, and page-local presentational subcomponents; `index.css` owns the theater scene, hidden tab bar, responsive seat columns, and button styling. The shared `@werewolf-arena/game-client` state derivation stays unchanged, so the implementation is a UI recomposition with no backend or desktop-web changes.

**Tech Stack:** React 19, React Router 7, TanStack Query 5, Vitest, Testing Library, Vite, CSS with the existing mobile px-to-rem pipeline.

---

## File Structure

- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`
  - Add tests for the new theater shell, top return button, side player seats, current stage content, and hidden-tab-bar CSS rule.
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
  - Replace the card-stack render with page-local theater components: `LiveTheaterTopBar`, `LiveSkyBanner`, `LiveSeatColumn`, `LiveSeatAvatar`, `LiveCenterStage`, and `LiveTheaterControls`.
  - Add small helper functions for current-player selection, seat splitting, role labels, avatar initials, and fallback back navigation.
- Modify: `apps/mobile-web/src/styles/index.css`
  - Replace the old `.mobile-live-*` card grid styles with full-screen theater styles and add `.mobile-app-shell:has(.mobile-live-page)` rules to hide the bottom mobile tab bar only on live pages.
- No changes: `apps/api`, `packages/game-client`, `apps/web`, mobile routes, or global navigation components.

---

### Task 1: Add Failing Theater Page Tests

**Files:**
- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`

- [ ] **Step 1: Extend the game-started fixture**

Replace the `players` payload in `gameStartedEvent` with four players so both left and right columns have visible seats:

```tsx
players: [
  { name: "阿青", role: "villager", model: "test-model" },
  { name: "白石", role: "werewolf", model: "test-model" },
  { name: "南风", role: "seer", model: "test-model" },
  { name: "木子", role: "witch", model: "test-model" },
],
```

Also set `gameStartedEvent.round` to `1` and `gameStartedEvent.phase` to `"day"` so the derived day label is `第 1 天`.

- [ ] **Step 2: Import the stylesheet reader**

At the top of `LivePage.test.tsx`, add the Node fs import:

```tsx
import { readFileSync } from "node:fs";
```

- [ ] **Step 3: Replace the visible-heading assertion with theater-shell assertions**

Update the existing `renders mobile live details for the route game id` test body to assert the new theater surface:

```tsx
it("renders mobile live details for the route game id", async () => {
  renderLiveRoute();

  expect(
    await screen.findByRole("heading", { name: "实时观战" }),
  ).toHaveClass("mobile-sr-only");
  expect(
    screen.getByRole("button", { name: "返回对局大厅" }),
  ).toBeVisible();
  expect((await screen.findAllByText("经典 8 人"))[0]).toBeVisible();
  expect(screen.getByText("连接正常")).toBeVisible();
  expect(screen.getByText("game_started")).toBeVisible();
  expect(screen.getByText("第 1 天")).toBeVisible();
  expect(
    screen.getByRole("region", { name: "玩家席位" }),
  ).toBeVisible();
  expect(
    screen.getByRole("article", { name: "1号 阿青 平民 存活" }),
  ).toBeVisible();
  expect(
    screen.getByRole("article", { name: "4号 木子 女巫 存活" }),
  ).toBeVisible();
  expect(gameClientMocks.getGameRun).toHaveBeenCalledWith("run-1");
  expect(gameClientMocks.useGameRunEvents).toHaveBeenCalledWith("run-1");
});
```

- [ ] **Step 4: Add a CSS contract test for immersive mode**

Append this test inside `describe("LivePage", () => { ... })`:

```tsx
it("hides the bottom mobile tab bar on the immersive live page", () => {
  const styles = readFileSync("src/styles/index.css", "utf8");
  const tabBarRule =
    styles.match(
      /\.mobile-app-shell:has\(\.mobile-live-page\) \.mobile-tab-bar\s*{[^}]+}/,
    )?.[0] ?? "";
  const contentRegionRule =
    styles.match(
      /\.mobile-app-shell:has\(\.mobile-live-page\) \.mobile-content-region\s*{[^}]+}/,
    )?.[0] ?? "";

  expect(tabBarRule).toContain("display: none");
  expect(contentRegionRule).toContain("padding-bottom: 0");
});
```

- [ ] **Step 5: Run the focused test and verify it fails**

Run:

```bash
pnpm --dir apps/mobile-web test --run src/pages/LivePage.test.tsx
```

Expected: FAIL because the current page still renders a visible `实时观战` heading, has no `返回对局大厅` button, no `region` named `玩家席位`, no article names like `1号 阿青 平民 存活`, and no live-page tab-bar hiding CSS.

- [ ] **Step 6: Commit the failing tests**

Run:

```bash
git add apps/mobile-web/src/pages/LivePage.test.tsx
git commit -m "test: cover mobile live theater shell"
```

Expected: Commit succeeds with only `LivePage.test.tsx` staged.

---

### Task 2: Recompose `LivePage.tsx` Into Theater Components

**Files:**
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`

- [ ] **Step 1: Import the GodView player type**

Extend the game-client import with `type GodViewPlayer`:

```tsx
import {
  deriveGodViewState,
  deriveLiveNavStatus,
  deriveLiveSpectatorState,
  getGameRun,
  resumeGameRun,
  useGameRunEvents,
  useLiveDirector,
  type GameRun,
  type GodViewPlayer,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";
```

- [ ] **Step 2: Replace the old JSX inside `return`**

Replace the current `<main className="mobile-page mobile-live-page">...</main>` body with this structure:

```tsx
return (
  <main className="mobile-page mobile-live-page">
    <h1 className="mobile-sr-only">实时观战</h1>

    {runQuery.isPending ? (
      <p className="mobile-status-banner">正在读取实时对局...</p>
    ) : null}
    {runQuery.isError ? (
      <p className="mobile-status-banner" role="alert">
        无法读取实时对局
      </p>
    ) : null}
    {resumeMutation.isError ? (
      <p className="mobile-status-banner" role="alert">
        无法继续对局
      </p>
    ) : null}

    {run ? (
      <LiveTheater
        canResumeRun={canResumeRun}
        connectionState={connectionState}
        currentEvent={currentEvent}
        director={director}
        godViewState={godViewState}
        liveStatusLabel={liveStatus.label}
        onBack={() => navigateBackToGames(navigate)}
        onResumeRun={() => resumeMutation.mutate(run.session_id)}
        resumeIsPending={resumeMutation.isPending}
        run={run}
        terminalEvent={terminalEvent}
      />
    ) : null}
  </main>
);
```

- [ ] **Step 3: Add theater prop types after `LivePage`**

Add these types below `LivePage`:

```tsx
type LiveDirectorControlsState = ReturnType<typeof useLiveDirector>;
type GodViewState = ReturnType<typeof deriveGodViewState>;

type LiveTheaterProps = {
  canResumeRun: boolean;
  connectionState: string;
  currentEvent: LiveGameEvent | null;
  director: LiveDirectorControlsState;
  godViewState: GodViewState;
  liveStatusLabel: string;
  onBack: () => void;
  onResumeRun: () => void;
  resumeIsPending: boolean;
  run: GameRun;
  terminalEvent: LiveGameEvent | undefined;
};
```

- [ ] **Step 4: Add the `LiveTheater` component**

Add this component below the new types:

```tsx
function LiveTheater({
  canResumeRun,
  connectionState,
  currentEvent,
  director,
  godViewState,
  liveStatusLabel,
  onBack,
  onResumeRun,
  resumeIsPending,
  run,
  terminalEvent,
}: LiveTheaterProps) {
  const currentPlayer = getCurrentTheaterPlayer(godViewState);
  const { left, right } = splitPlayersForColumns(godViewState.players);

  return (
    <section className="mobile-live-theater" aria-label="实时观战剧场">
      <LiveTheaterTopBar
        connectionState={connectionState}
        liveStatusLabel={liveStatusLabel}
        onBack={onBack}
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
        resumeIsPending={resumeIsPending}
        run={run}
        terminalEvent={terminalEvent}
      />
    </section>
  );
}
```

- [ ] **Step 5: Add top bar and sky banner components**

Add these components after `LiveTheater`:

```tsx
type LiveTheaterTopBarProps = {
  connectionState: string;
  liveStatusLabel: string;
  onBack: () => void;
  ruleName: string;
};

function LiveTheaterTopBar({
  connectionState,
  liveStatusLabel,
  onBack,
  ruleName,
}: LiveTheaterTopBarProps) {
  return (
    <header className="mobile-live-theater-top">
      <button
        aria-label="返回对局大厅"
        className="mobile-live-back-button"
        onClick={onBack}
        type="button"
      >
        ‹
      </button>
      <div>
        <strong>{ruleName}</strong>
        <span>{liveStatusLabel}</span>
      </div>
      <span className="mobile-live-connection">
        {connectionLabel(connectionState)}
      </span>
    </header>
  );
}

type LiveSkyBannerProps = {
  dayNightLabel: string;
  phaseLabel: string;
};

function LiveSkyBanner({ dayNightLabel, phaseLabel }: LiveSkyBannerProps) {
  return (
    <section className="mobile-live-sky" aria-label="当前轮次">
      <div className="mobile-live-sky-orb" aria-hidden="true" />
      <div className="mobile-live-day-banner">
        <span>{phaseLabel}</span>
        <strong>{dayNightLabel}</strong>
      </div>
    </section>
  );
}
```

- [ ] **Step 6: Add seat column and avatar components**

Add these components after `LiveSkyBanner`:

```tsx
type LiveSeatColumnProps = {
  players: GodViewPlayer[];
  side: "left" | "right";
};

function LiveSeatColumn({ players, side }: LiveSeatColumnProps) {
  return (
    <div className={`mobile-live-seat-column mobile-live-seat-column-${side}`}>
      {players.map((player) => (
        <LiveSeatAvatar key={player.name} player={player} />
      ))}
    </div>
  );
}

type LiveSeatAvatarProps = {
  player: GodViewPlayer;
};

function LiveSeatAvatar({ player }: LiveSeatAvatarProps) {
  const roleLabel = roleShortLabel(player.role);
  const statusLabel = player.isSpeaking ? "发言中" : player.stageStatus.label;
  const seatLabel = `${player.seatNumber}号 ${player.name} ${player.role || "未知"} ${statusLabel}`;
  const className = [
    "mobile-live-seat",
    player.isSpeaking ? "mobile-live-seat-speaking" : "",
    player.isAlive ? "" : "mobile-live-seat-out",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <article aria-label={seatLabel} className={className}>
      <span className="mobile-live-seat-number">{player.seatNumber}</span>
      <span className="mobile-live-seat-avatar">
        {player.avatarImageUrl ? (
          <img alt="" src={player.avatarImageUrl} />
        ) : (
          <span>{avatarInitial(player.name, player.seatNumber)}</span>
        )}
      </span>
      <span className="mobile-live-seat-role">{roleLabel}</span>
      <strong>{player.name}</strong>
      <small>{statusLabel}</small>
    </article>
  );
}
```

- [ ] **Step 7: Add center stage and controls components**

Add these components after `LiveSeatAvatar`:

```tsx
type LiveCenterStageProps = {
  currentEvent: LiveGameEvent | null;
  currentPlayer: GodViewPlayer | null;
  godViewState: GodViewState;
};

function LiveCenterStage({
  currentEvent,
  currentPlayer,
  godViewState,
}: LiveCenterStageProps) {
  return (
    <section className="mobile-live-center-stage" aria-label="当前舞台">
      <div className="mobile-live-presenter" aria-hidden="true">
        {currentPlayer ? avatarInitial(currentPlayer.name, currentPlayer.seatNumber) : "?"}
      </div>
      <span>{currentPlayer ? `${currentPlayer.seatNumber}号` : "等待"}</span>
      <strong>{currentPlayer?.name ?? "等待玩家行动"}</strong>
      <em>{currentPlayer?.stageStatus.label ?? godViewState.currentSeatLabel}</em>
      <p>{currentEvent?.type ?? "等待事件"}</p>
      {currentEvent?.action ? <small>{currentEvent.action}</small> : null}
    </section>
  );
}

type LiveTheaterControlsProps = {
  canResumeRun: boolean;
  currentPlayer: GodViewPlayer | null;
  director: LiveDirectorControlsState;
  godViewState: GodViewState;
  onResumeRun: () => void;
  resumeIsPending: boolean;
  run: GameRun;
  terminalEvent: LiveGameEvent | undefined;
};

function LiveTheaterControls({
  canResumeRun,
  currentPlayer,
  director,
  godViewState,
  onResumeRun,
  resumeIsPending,
  run,
  terminalEvent,
}: LiveTheaterControlsProps) {
  return (
    <footer className="mobile-live-control-deck" aria-label="实时观战操作">
      <div className="mobile-live-focus-strip">
        <span>{currentPlayer ? `${currentPlayer.seatNumber}` : "-"}</span>
        <strong>{currentPlayer?.name ?? "等待行动"}</strong>
        <em>{godViewState.countdownLabel}</em>
      </div>
      <div className="mobile-live-action-bar">
        <button className="mobile-button" onClick={director.togglePaused} type="button">
          {director.isPaused ? "继续" : "暂停"}
        </button>
        <button
          className="mobile-button"
          onClick={() => director.setSpeed(director.speed === 1 ? 2 : 1)}
          type="button"
        >
          {director.speed === 1 ? "1x" : "2x"}
        </button>
        <button className="mobile-button" onClick={director.catchUpToLatest} type="button">
          最新
        </button>
        {canResumeRun ? (
          <button
            className="mobile-button mobile-button-primary"
            disabled={resumeIsPending}
            onClick={onResumeRun}
            type="button"
          >
            {resumeIsPending ? "继续中" : "继续对局"}
          </button>
        ) : null}
        {isTerminalRunStatus(run.status) || terminalEvent ? (
          <Link className="mobile-button mobile-live-link" to={`/games/${run.session_id}/replay`}>
            复盘
          </Link>
        ) : null}
      </div>
    </footer>
  );
}
```

- [ ] **Step 8: Remove obsolete card components**

Delete these old types and functions because the theater components replace them:

```tsx
type LiveSummaryProps = { ... };
function LiveSummary(...) { ... }
type CurrentEventPanelProps = { ... };
function CurrentEventPanel(...) { ... }
```

- [ ] **Step 9: Add helper functions before `connectionLabel`**

Add these helpers above `connectionLabel`:

```tsx
function getCurrentTheaterPlayer(state: GodViewState) {
  return (
    state.speakerFlow.current ??
    state.players.find((player) => player.isSpeaking) ??
    null
  );
}

function splitPlayersForColumns(players: GodViewPlayer[]) {
  const midpoint = Math.ceil(players.length / 2);

  return {
    left: players.slice(0, midpoint),
    right: players.slice(midpoint),
  };
}

function avatarInitial(name: string, seatNumber: number) {
  const trimmed = name.trim();

  return trimmed ? trimmed.slice(0, 1) : String(seatNumber);
}

function roleShortLabel(role: string) {
  const labels: Record<string, string> = {
    hunter: "猎",
    idiot: "白",
    seer: "预",
    villager: "民",
    werewolf: "狼",
    witch: "巫",
  };

  return labels[role] ?? "未知";
}

function navigateBackToGames(navigate: ReturnType<typeof useNavigate>) {
  if (window.history.length > 1) {
    navigate(-1);
    return;
  }

  navigate("/games");
}
```

- [ ] **Step 10: Run the focused test and verify JSX failures remain CSS-only or pass partially**

Run:

```bash
pnpm --dir apps/mobile-web test --run src/pages/LivePage.test.tsx
```

Expected: The render assertions pass or only the CSS contract test fails because the stylesheet is not implemented yet.

- [ ] **Step 11: Commit the JSX recomposition**

Run:

```bash
git add apps/mobile-web/src/pages/LivePage.tsx
git commit -m "feat: recompose mobile live theater"
```

Expected: Commit succeeds with only `LivePage.tsx` staged.

---

### Task 3: Add Full-Screen Theater CSS

**Files:**
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Hide bottom navigation for live pages**

Add these rules near the existing `.mobile-app-shell:has(...)` rules:

```css
.mobile-app-shell:has(.mobile-live-page) .mobile-content-region {
  padding-bottom: 0;
}

.mobile-app-shell:has(.mobile-live-page) .mobile-tab-bar {
  display: none;
}
```

- [ ] **Step 2: Replace the old mobile live card styles**

Replace the existing block from `.mobile-live-page { ... }` through `.mobile-live-link { ... }` with:

```css
.mobile-live-page {
  position: relative;
  min-height: 100svh;
  overflow: hidden;
  padding: 0;
  background:
    radial-gradient(circle at 50% 17%, rgb(61 200 218 / 34%) 0 16%, transparent 36%),
    linear-gradient(180deg, rgb(30 4 7 / 94%) 0 14%, rgb(8 10 16 / 92%) 42%, rgb(26 17 10 / 96%) 100%);
}

.mobile-live-theater {
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-rows: auto minmax(146px, 24svh) minmax(0, 1fr) auto;
  min-height: 100svh;
  box-sizing: border-box;
  overflow: hidden;
  padding: calc(10px + env(safe-area-inset-top)) 10px calc(10px + env(safe-area-inset-bottom));
  color: #fff3d7;
}

.mobile-live-theater::before,
.mobile-live-theater::after {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: -1;
  width: 28%;
  background: linear-gradient(90deg, rgb(80 13 15 / 86%), rgb(36 6 9 / 68%), transparent);
  pointer-events: none;
  content: "";
}

.mobile-live-theater::before {
  left: 0;
}

.mobile-live-theater::after {
  right: 0;
  transform: scaleX(-1);
}

.mobile-live-theater-top {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 48px;
}

.mobile-live-back-button {
  width: 42px;
  height: 42px;
  border: 1px solid rgb(252 226 172 / 46%);
  border-radius: 999px;
  background: radial-gradient(circle at 35% 28%, #9d7a3e, #4e3218 72%);
  color: #fff6df;
  font-size: 31px;
  font-weight: 800;
  line-height: 1;
}

.mobile-live-theater-top div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.mobile-live-theater-top strong,
.mobile-live-theater-top span,
.mobile-live-connection {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-live-theater-top strong {
  color: #fff4d2;
  font-size: 14px;
  line-height: 1.1;
}

.mobile-live-theater-top span {
  color: #d8c49a;
  font-size: 11px;
  font-weight: 800;
  line-height: 1.1;
}

.mobile-live-connection {
  max-width: 90px;
  border: 1px solid rgb(230 190 111 / 34%);
  border-radius: 999px;
  padding: 6px 8px;
  background: rgb(31 18 9 / 72%);
  color: #f7ddb0;
  font-size: 11px;
  font-weight: 900;
}

.mobile-live-sky {
  position: relative;
  display: grid;
  place-items: start center;
  overflow: hidden;
  min-height: 146px;
}

.mobile-live-sky::before {
  position: absolute;
  top: -42px;
  left: 0;
  right: 0;
  height: 72px;
  background:
    radial-gradient(circle at 50% 0, rgb(0 0 0 / 70%) 0 24px, transparent 25px),
    linear-gradient(135deg, #210406, #5d1416 45%, #180305);
  box-shadow: 0 14px 28px rgb(0 0 0 / 44%);
  content: "";
}

.mobile-live-sky-orb {
  width: min(72vw, 300px);
  aspect-ratio: 1;
  border-radius: 999px;
  background:
    radial-gradient(circle at 43% 25%, #8cf7ff 0 28%, #31bdd1 48%, #0d7089 70%),
    #1aa9c2;
  box-shadow:
    inset 0 0 0 11px rgb(174 121 40 / 62%),
    0 0 34px rgb(42 213 232 / 34%);
}

.mobile-live-day-banner {
  position: absolute;
  top: 52px;
  left: 34px;
  right: 34px;
  display: grid;
  min-height: 56px;
  place-items: center;
  border-top: 1px solid rgb(251 233 184 / 36%);
  border-bottom: 1px solid rgb(251 233 184 / 36%);
  background: linear-gradient(90deg, transparent, rgb(10 8 7 / 68%) 16% 84%, transparent);
  text-align: center;
}

.mobile-live-day-banner span {
  color: #d9c59a;
  font-size: 11px;
  font-weight: 900;
  line-height: 1.1;
}

.mobile-live-day-banner strong {
  color: #fff4d5;
  font-size: 28px;
  font-weight: 900;
  line-height: 1.1;
}

.mobile-live-seat-stage {
  position: relative;
  display: grid;
  grid-template-columns: minmax(64px, 23%) minmax(0, 1fr) minmax(64px, 23%);
  align-items: stretch;
  gap: 6px;
  min-height: 0;
  overflow: hidden;
}

.mobile-live-seat-column {
  display: grid;
  align-content: center;
  gap: clamp(5px, 1.3svh, 10px);
  min-width: 0;
}

.mobile-live-seat-column-right .mobile-live-seat {
  justify-items: end;
  text-align: right;
}

.mobile-live-seat {
  position: relative;
  display: grid;
  min-width: 0;
  justify-items: start;
  gap: 2px;
  color: #fff3d7;
}

.mobile-live-seat-number {
  position: absolute;
  top: -3px;
  left: -2px;
  z-index: 1;
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border-radius: 999px;
  background: #806030;
  color: #fff8df;
  font-size: 10px;
  font-weight: 900;
}

.mobile-live-seat-avatar {
  display: grid;
  width: clamp(43px, 12.4vw, 58px);
  aspect-ratio: 1;
  place-items: center;
  overflow: hidden;
  border: 2px solid #caa364;
  border-radius: 999px;
  background: radial-gradient(circle at 38% 28%, #f3e5c8, #6c4732);
  box-shadow: 0 4px 14px rgb(0 0 0 / 42%);
}

.mobile-live-seat-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.mobile-live-seat-avatar > span {
  color: #34200d;
  font-size: 18px;
  font-weight: 900;
}

.mobile-live-seat-role {
  position: absolute;
  top: -4px;
  right: 4px;
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border-radius: 999px;
  background: #c4473c;
  color: #fff8e5;
  font-size: 11px;
  font-weight: 900;
}

.mobile-live-seat strong,
.mobile-live-seat small {
  max-width: 62px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-live-seat strong {
  font-size: 11px;
  line-height: 1.15;
}

.mobile-live-seat small {
  color: #dcc596;
  font-size: 10px;
  font-weight: 800;
  line-height: 1.1;
}

.mobile-live-seat-speaking .mobile-live-seat-avatar {
  border-color: #76f3a0;
  box-shadow:
    0 0 0 3px rgb(118 243 160 / 34%),
    0 0 18px rgb(118 243 160 / 74%);
}

.mobile-live-seat-out {
  opacity: 0.58;
  filter: grayscale(1);
}

.mobile-live-center-stage {
  align-self: end;
  display: grid;
  min-width: 0;
  justify-items: center;
  gap: 5px;
  padding: 10px 8px 16px;
  border-radius: 90px 90px 18px 18px;
  background:
    radial-gradient(ellipse at 50% 62%, rgb(236 166 68 / 32%), transparent 62%),
    linear-gradient(180deg, rgb(37 29 24 / 36), rgb(89 57 28 / 68));
  box-shadow: inset 0 -18px 40px rgb(0 0 0 / 28%);
  text-align: center;
}

.mobile-live-presenter {
  display: grid;
  width: clamp(82px, 28vw, 126px);
  aspect-ratio: 0.74;
  place-items: center;
  border-radius: 42px 42px 16px 16px;
  background: linear-gradient(180deg, #f8d1b2 0 28%, #e8faf6 28% 100%);
  color: #784321;
  font-size: 34px;
  font-weight: 900;
  box-shadow: 0 0 36px rgb(255 216 148 / 34%);
}

.mobile-live-center-stage > span {
  color: #f8d785;
  font-size: 12px;
  font-weight: 900;
}

.mobile-live-center-stage strong,
.mobile-live-center-stage em,
.mobile-live-center-stage p,
.mobile-live-center-stage small {
  max-width: 100%;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-live-center-stage strong {
  color: #fff4d5;
  font-size: 18px;
  line-height: 1.15;
}

.mobile-live-center-stage em {
  color: #d6c39a;
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.mobile-live-center-stage p {
  color: #fff1c9;
  font-size: 13px;
  font-weight: 900;
}

.mobile-live-center-stage small {
  color: #cbb58b;
  font-size: 11px;
  font-weight: 800;
}

.mobile-live-control-deck {
  display: grid;
  gap: 8px;
}

.mobile-live-focus-strip {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 48px;
  border: 1px solid rgb(255 230 177 / 46%);
  border-radius: 10px;
  padding: 0 12px;
  background: linear-gradient(180deg, #cfa563, #795327);
  color: #fff8df;
  box-shadow: 0 -8px 24px rgb(255 212 116 / 16%);
}

.mobile-live-focus-strip span {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 999px;
  background: rgb(55 34 12 / 62%);
  font-weight: 900;
}

.mobile-live-focus-strip strong,
.mobile-live-focus-strip em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-live-focus-strip strong {
  font-size: 15px;
  line-height: 1.1;
}

.mobile-live-focus-strip em {
  font-size: 18px;
  font-style: normal;
  font-weight: 900;
}

.mobile-live-action-bar {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.mobile-live-action-bar .mobile-button,
.mobile-live-link {
  display: inline-flex;
  min-width: 0;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  border-color: rgb(255 230 177 / 34%);
  background: rgb(55 34 18 / 82%);
  color: #fff3d7;
  text-align: center;
  text-decoration: none;
}
```

- [ ] **Step 3: Add the narrow-screen adjustment**

Add this media query after the new live styles:

```css
@media (max-width: 360px) {
  .mobile-live-seat-stage {
    grid-template-columns: 58px minmax(0, 1fr) 58px;
    gap: 4px;
  }

  .mobile-live-seat strong,
  .mobile-live-seat small {
    max-width: 56px;
  }

  .mobile-live-action-bar {
    gap: 6px;
  }
}
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
pnpm --dir apps/mobile-web test --run src/pages/LivePage.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit the CSS**

Run:

```bash
git add apps/mobile-web/src/styles/index.css
git commit -m "style: add mobile live theater scene"
```

Expected: Commit succeeds with only `index.css` staged.

---

### Task 4: Final Verification and Visual QA

**Files:**
- No source edits expected unless verification finds a defect.

- [ ] **Step 1: Run the full mobile test suite**

Run:

```bash
pnpm test:mobile
```

Expected: PASS.

- [ ] **Step 2: Run the mobile production build**

Run:

```bash
pnpm build:mobile
```

Expected: PASS.

- [ ] **Step 3: Start the mobile dev server**

Run:

```bash
pnpm dev:mobile
```

Expected: Vite serves `apps/mobile-web` at `http://127.0.0.1:5174/`. If port 5174 is occupied, Vite reports the alternate port; use that reported URL.

- [ ] **Step 4: Visually inspect the live page**

Open a mobile viewport at 375 x 812 and visit a live route such as:

```text
http://127.0.0.1:5174/games/run-1/live
```

Expected visual checks:

- The bottom mobile tab bar is not visible.
- The top return button is visible.
- The sky/day banner stays in the upper half.
- Left and right player seat columns do not overlap the center stage.
- The bottom focus strip and action buttons do not overlap the seat columns.
- Long player names and event names ellipsize instead of overflowing.

- [ ] **Step 5: Commit verification fixes if needed**

If visual or test verification requires small fixes, stage only those files and commit:

```bash
git add apps/mobile-web/src/pages/LivePage.tsx apps/mobile-web/src/styles/index.css apps/mobile-web/src/pages/LivePage.test.tsx
git commit -m "fix: polish mobile live theater layout"
```

Expected: Commit happens only if source files changed after Tasks 1-3.

---

## Self-Review

- Spec coverage: The plan covers top return navigation, hidden bottom nav, full-screen theater layout, sky/day banner, side seat columns, current actor center stage, preserved controls, failed-run resume, replay link, responsive constraints, and mobile-only scope.
- Placeholder scan: No `TBD`, `TODO`, `implement later`, or vague “add appropriate handling” instructions remain.
- Type consistency: `GodViewPlayer` and `GodViewState` come from the existing game-client exports and local `ReturnType`; helper names used by JSX are defined in Task 2; CSS class names match the JSX snippets.
