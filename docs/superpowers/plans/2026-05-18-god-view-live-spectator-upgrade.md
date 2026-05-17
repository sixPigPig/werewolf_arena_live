# God View Live Spectator Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `/games/live/:runId` into a dense "上帝视角直播台" that matches the provided gothic control-room reference while staying on the current SSE event contract.

**Architecture:** Add a focused front-end derivation layer that turns `LiveGameEvent[]` plus `LiveSpectatorState` into god-view dashboard data. Keep `LiveGamePage` as the orchestration point, split new visual surfaces into small React components, and avoid backend/API changes unless a later review explicitly asks for richer event fields.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, Tailwind CSS utilities, existing gothic/glass CSS surfaces.

---

## Scope And Constraints

This is a front-end upgrade only. The first implementation must not add backend fields, migrations, new dependencies, websocket changes, or real countdown timing. Any value unavailable from current live events should be shown as "暂无记录", "等待行动", or a clearly derived state.

The reference image should guide information density and hierarchy:

- Top command band: board name, day/night, current phase, current speaking seat, countdown-like status, alive count, win mode.
- Left identity board: every player seat, nickname, avatar, real role, camp/group, alive/dead/speaking/sheriff/vote state, received votes, derived suspicion/clue tags.
- Center stage: current speaker portrait, identity/camp badges, previous/current/next speaking order, speech mode tags.
- Right intelligence stack: event log, death info, identity clues, sheriff information, camp/win progress.
- Bottom board: speaking order, vote matrix/tally, exile candidate ranking, public info, replay marks.

## Existing Context

Current relevant files:

- `apps/web/src/pages/LiveGamePage.tsx` orchestrates run query, SSE events, director cues, roster items, stage, and timeline.
- `apps/web/src/pages/components/LiveStageModule.tsx` defines the three-column live layout.
- `apps/web/src/features/games/liveSpectator.ts` derives current players, actor, phase, round, alive/dead state, and last action details from live events.
- `apps/web/src/features/games/liveDirector.ts` builds stage cues from live events.
- `apps/web/src/features/games/components/LiveDirectorStage.tsx` renders the current round-table stage.
- `apps/web/src/features/games/components/PlayerRosterPanel.tsx` renders the left player list.
- `apps/web/src/features/games/components/LiveEventTimeline.tsx` renders event timelines.
- `apps/web/src/pages/LiveGamePage.test.tsx` covers the live page layout and interactions.
- `apps/web/src/features/games/liveSpectator.test.ts` covers derived live state.
- `apps/web/src/styles/index.css` contains landscape and gothic live-page responsive styles.

## Proposed File Structure

- Create `apps/web/src/features/games/liveGodView.ts`
  - Responsibility: derive all god-view dashboard data from existing live events and `LiveSpectatorState`.
  - Exports: `deriveGodViewState`, `GodViewState`, `GodViewPlayer`, small display types.

- Create `apps/web/src/features/games/liveGodView.test.ts`
  - Responsibility: prove vote, death, night-action, sheriff, camp progress, and fallback derivations.

- Create `apps/web/src/features/games/components/GodViewRosterPanel.tsx`
  - Responsibility: render the left identity board with all player rows and dense status columns.

- Create `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
  - Responsibility: render the right intelligence stack: event log, death info, night actions, sheriff, identity clues, camp progress.

- Create `apps/web/src/features/games/components/GodViewBottomBoard.tsx`
  - Responsibility: render the bottom board: speaking order, vote matrix/tally, exile candidates, public info, replay marks.

- Modify `apps/web/src/features/games/components/LiveDirectorStage.tsx`
  - Responsibility change: accept optional god-view state, show current speaker portrait/identity badges and top stage status.

- Modify `apps/web/src/pages/components/LiveStageModule.tsx`
  - Responsibility change: preserve the existing three main columns while allowing an optional full-width bottom board.

- Modify `apps/web/src/pages/LiveGamePage.tsx`
  - Responsibility change: call `deriveGodViewState`, pass god-view data into the new roster, stage, intel, and bottom components.

- Modify `apps/web/src/pages/LiveGamePage.test.tsx`
  - Responsibility change: assert the upgraded god-view surfaces render and remain interactive.

- Modify `apps/web/src/styles/index.css`
  - Responsibility change: add responsive compact rules for the denser board, especially short landscape viewports.

## Data Mapping

Use current live events as follows:

- `game_started.payload.players`: player order, seat number, nickname, role, model, avatar/profile fields, tags.
- `event.round` and `event.phase`: day/night label and phase label.
- `event.actor`, `event.action`, model streaming events: current speaking/acting player and stage state.
- `state_updated.payload.active_players`: alive count and dead/out status.
- `state_updated.payload.attacked`, `protected`, `saved_by_witch`, `poisoned`, `investigated`: night action panel.
- `state_updated.payload.eliminated`, `exiled`, `night_deaths`, `day_deaths`: death panel.
- `state_updated.payload.votes`, `vote_weights`: current vote targets, received vote counts, tally, sheriff 1.5 vote support.
- `state_updated.payload.sheriff`, `sheriff_elected`, `sheriff_candidates`, `sheriff_voters`, `sheriff_badge_target`, `sheriff_badge_lost`: sheriff panel.
- `game_completed.payload.winner`: winner label and terminal progress.

Derived values:

- Camp/group from role: 狼人阵营, 神职, 平民, 好人阵营.
- Win mode: default `屠边` for current rule sets unless `run.rule_set.win_condition` exposes a clearer label.
- Suspicion value: deterministic visual meter based on known god-view role, received votes, and active/speaking state. It is a broadcast-board cue, not game logic.
- Countdown: show `00:45` only as a stage-display placeholder when a current public speaker exists; otherwise show `夜间行动中`, `投票中`, or `待命`.

## Task 1: Add God-View Derivation Tests

**Files:**
- Create: `apps/web/src/features/games/liveGodView.test.ts`
- Create later in Task 2: `apps/web/src/features/games/liveGodView.ts`

- [ ] **Step 1: Write tests for core god-view derivation**

Create tests with a small `event(partial)` helper mirroring `liveSpectator.test.ts`. Cover:

```ts
it("derives player identities, camps, alive counts and current seat", () => {
  const spectator = deriveLiveSpectatorState([
    event({
      type: "game_started",
      payload: {
        players: [
          { name: "7号 暗夜领主", role: "狼人", model: "deepseek-chat" },
          { name: "2号 银月诗人", role: "女巫", model: "deepseek-chat" },
          { name: "4号 暗鸦学者", role: "平民", model: "deepseek-chat" },
        ],
      },
    }),
    event({ id: 2, type: "action_requested", round: 3, phase: "day", actor: "7号 暗夜领主", action: "debate" }),
  ]);

  const state = deriveGodViewState([], spectator, "暗夜古堡");

  expect(state.boardName).toBe("暗夜古堡");
  expect(state.dayNightLabel).toBe("第 3 天");
  expect(state.phaseLabel).toBe("白天发言");
  expect(state.currentSeatLabel).toBe("发言席：1 号");
  expect(state.aliveLabel).toBe("存活 3/3");
  expect(state.progress).toMatchObject({ wolvesAlive: 1, godsAlive: 1, villagersAlive: 1 });
  expect(state.players[0]).toMatchObject({ camp: "狼人阵营", identityGroup: "狼人", isSpeaking: true });
});
```

Also cover night actions, death info, votes, sheriff fields, and fallback empty states.

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveGodView.test.ts
```

Expected: FAIL because `liveGodView.ts` does not exist yet.

## Task 2: Implement `liveGodView.ts`

**Files:**
- Create: `apps/web/src/features/games/liveGodView.ts`
- Test: `apps/web/src/features/games/liveGodView.test.ts`

- [ ] **Step 1: Add exported types and pure derivation function**

Implement `GodViewState`, `GodViewPlayer`, `GodViewEventLine`, `GodViewActionLine`, `GodViewDeathInfo`, `GodViewVoteTally`, and:

```ts
export function deriveGodViewState(
  events: LiveGameEvent[],
  spectator: LiveSpectatorState,
  boardName: string,
): GodViewState
```

Use only pure functions and local helpers. Do not mutate `spectator.players`.

- [ ] **Step 2: Implement event collectors**

Collectors should handle:

- `action_parsed` for parsed night actions and direct vote choices.
- `state_updated` for active players, votes, vote weights, night results, deaths, sheriff state, public facts.
- `game_completed` for winner.
- `phase_started`, `state_updated`, `game_completed` for replay marks.

- [ ] **Step 3: Implement role/camp/status helpers**

Map backend role ids and Chinese role names:

```ts
werewolf -> 狼人
villager -> 平民
seer -> 预言家
guard -> 守卫
doctor -> 医生
witch -> 女巫
hunter -> 猎人
idiot -> 白痴
```

Camp/group rules:

- role contains `狼`: 狼人阵营 / 狼人.
- 预言家、女巫、守卫、医生、猎人、白痴: 好人阵营 / 神职.
- 平民、村民: 好人阵营 / 平民.
- unknown: 好人阵营 / 未知.

- [ ] **Step 4: Run derivation tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveGodView.test.ts
```

Expected: PASS.

## Task 3: Build Dense Roster, Intel, And Bottom Components

**Files:**
- Create: `apps/web/src/features/games/components/GodViewRosterPanel.tsx`
- Create: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
- Create: `apps/web/src/features/games/components/GodViewBottomBoard.tsx`
- Test later through `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Build `GodViewRosterPanel`**

Props:

```ts
type GodViewRosterPanelProps = {
  players: GodViewPlayer[];
  onSelectPlayer: (name: string) => void;
};
```

Render:

- Heading `身份牌（上帝视角）`.
- A compact table/list with seat, avatar, name, role, camp/group, status, sheriff/speaking icons, vote target, received votes, suspicion percentage.
- Use `button` rows so selecting a player still pins focus.
- Add `data-testid="god-view-roster-panel"` and `data-testid="god-view-player-row-${player.name}"`.

- [ ] **Step 2: Build `GodViewIntelPanel`**

Props:

```ts
type GodViewIntelPanelProps = {
  state: GodViewState;
};
```

Render stacked sections:

- `事件记录`
- `死亡信息`
- `夜晚行动回顾`
- `身份线索（上帝视角）`
- `警长信息`
- `阵营进度`

Use compact headings and lists. Avoid explanatory tutorial text.

- [ ] **Step 3: Build `GodViewBottomBoard`**

Props:

```ts
type GodViewBottomBoardProps = {
  state: GodViewState;
};
```

Render five compact columns:

- `发言顺序`
- `票型矩阵`
- `投票统计`
- `放逐候选排名`
- `公开信息`
- `本局标记（回放点）`

Keep fixed/min heights and allow horizontal overflow on small screens instead of squeezing text into unreadable columns.

## Task 4: Wire Components Into The Live Page

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/components/LiveStageModule.tsx`
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`

- [ ] **Step 1: Compute god-view state**

In `LiveGamePage.tsx`, import `deriveGodViewState` and compute:

```ts
const godViewState = useMemo(
  () =>
    deriveGodViewState(
      events,
      spectatorState,
      run?.rule_set?.name ?? "实时对局",
    ),
  [events, run?.rule_set?.name, spectatorState],
);
```

- [ ] **Step 2: Replace left roster**

Use `GodViewRosterPanel` in the `roster` slot. Preserve the existing pin-player behavior:

```tsx
<GodViewRosterPanel
  onSelectPlayer={(name) => {
    setAutoFollow(false);
    setManualFocusName(name);
  }}
  players={godViewState.players}
/>
```

- [ ] **Step 3: Replace right timeline slot with intel stack**

Keep `LiveEventTimeline` available in the right stack under `事件记录` or a collapsible debug section. The visible right column should prioritize god-view intelligence.

- [ ] **Step 4: Add bottom board support**

Extend `LiveStageModuleProps`:

```ts
type LiveStageModuleProps = {
  roster: ReactNode;
  stage: ReactNode;
  timeline: ReactNode;
  bottom?: ReactNode;
};
```

Render bottom as a full-width row after the three main columns:

```tsx
{bottom ? (
  <div className="live-god-bottom-board min-w-0 md:col-span-2 xl:col-span-3">
    {bottom}
  </div>
) : null}
```

- [ ] **Step 5: Upgrade center stage header**

Add an optional `godViewState` prop to `LiveDirectorStage`. Use it to show:

- Board/day/phase strip.
- Current seat and countdown-like label.
- Alive count, win mode, winner/progress label.
- Focused/current player role and camp badges near the speaker portrait.

Do not remove existing automatic follow switch or seat ring behavior.

## Task 5: Responsive And Visual Polish

**Files:**
- Modify: `apps/web/src/styles/index.css`
- Modify as needed: component class names from Task 3.

- [ ] **Step 1: Add dense-board CSS hooks**

Add classes for:

- `.god-view-roster-panel`
- `.god-view-intel-panel`
- `.god-view-bottom-board`
- `.god-view-stat-grid`
- `.god-view-compact-row`

Use existing glass/gothic colors: amber borders, slate-black panels, red for wolves/death, blue/teal for good-side actions, purple/fuchsia for witch/identity clues. Avoid a one-hue palette.

- [ ] **Step 2: Preserve short landscape behavior**

Update existing landscape media queries so dense rows shrink safely:

- roster rows reduce avatar size and hide secondary clue tags.
- right intel stack max-height becomes scrollable.
- bottom board becomes horizontally scrollable with stable column widths.

- [ ] **Step 3: Check mobile behavior**

On mobile, order should be:

1. Stage
2. Identity roster
3. Intel panel
4. Bottom board

If the existing grid cannot support this without churn, keep source order roster/stage/intel but use CSS grid ordering only for mobile.

## Task 6: Page Tests

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Update existing layout assertions**

Adjust the "stage-first live layout" test:

- Still expect `live-stage-layout`.
- Expect `god-view-roster-panel`, `live-director-stage`, `god-view-intel-panel`, and `god-view-bottom-board`.
- Continue verifying no legacy `app-top-nav`.
- Continue verifying command nav controls.

- [ ] **Step 2: Add god-view data test**

Extend the existing SSE event test or add a new one:

```ts
expect(screen.getByText("身份牌（上帝视角）")).toBeInTheDocument();
expect(screen.getByText("狼人阵营")).toBeInTheDocument();
expect(screen.getByText("夜晚行动回顾")).toBeInTheDocument();
expect(screen.getByText("死亡信息")).toBeInTheDocument();
expect(screen.getByText("投票统计")).toBeInTheDocument();
```

Emit a `state_updated` event with votes, eliminated/exiled, sheriff, and active players. Assert:

- killed/exiled player appears in death info.
- vote tally shows the top target.
- sheriff panel shows current sheriff or badge flow.
- player row shows received votes and status.

- [ ] **Step 3: Keep interaction test**

The existing pin-player test must still pass:

- Click a player row.
- Confirm the corresponding stage seat gets `is-focused`.
- Toggle `自动跟随`.
- Confirm focus returns to current actor.

## Task 7: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveGodView.test.ts src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run full web tests**

Run:

```bash
pnpm --dir apps/web test -- --run
```

Expected: PASS.

- [ ] **Step 3: Build**

Run:

```bash
pnpm --dir apps/web build
```

Expected: TypeScript and Vite build complete successfully.

- [ ] **Step 4: Browser visual QA**

Start dev server:

```bash
pnpm --dir apps/web dev -- --host 127.0.0.1
```

Open a live run route in the in-app Browser. Verify:

- Desktop: no overlapping text in top strip, roster, right panel, bottom board.
- Mobile narrow viewport: readable stacked layout, no clipped buttons.
- Short landscape: dense rows fit and right/bottom panels scroll instead of overlapping.
- Stage is nonblank and player selection still works.

## Acceptance Criteria

- The live page visibly reads as a gothic "上帝视角直播台" rather than a generic debug page.
- The page includes the user's requested categories where current event data supports them: basic game info, all-player identity/status, central speaking stage, night actions, death info, voting, sheriff, event timeline, camp/win progress, replay markers.
- Missing backend data is represented honestly as empty/waiting/fallback state.
- Existing live director controls, auto-follow, manual player pinning, replay link, and SSE behavior continue to work.
- Focused tests, full web tests, and web build pass.

## Self-Review

- Spec coverage: all requested information groups are mapped to either direct event fields, derived values, or honest fallback displays.
- Placeholder scan: no task uses unresolved placeholder wording; unavailable runtime facts are explicitly handled as display fallbacks.
- Type consistency: `GodViewState` is introduced before component props that depend on it; component names match the file structure.
