# Mobile Lobby Interaction Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mobile `/games` lobby safer and faster to use by clarifying launch readiness, preventing silent seat moves, enlarging tiny tap targets, and adding a continuous seat-assignment flow.

**Architecture:** Keep the first implementation inside `apps/mobile-web/src/pages/GamesPage.tsx`, `apps/mobile-web/src/pages/GamesPage.test.tsx`, and `apps/mobile-web/src/styles/index.css`, matching the current mobile app pattern of page-local JSX plus one stylesheet. Add small pure helper functions at the bottom of `GamesPage.tsx` for launch status, occupied-seat labels, next-empty-seat lookup, and unknown rule-card fallback. Do not change API contracts, backend routes, shared package behavior, or desktop web.

**Tech Stack:** React 19, React Router 7, TanStack Query 5, Vitest, Testing Library, Vite, CSS with the existing px-to-rem processing.

---

## Priority Order

1. **P0 launch clarity:** Show whether the lineup is complete, auto-fillable, or blocked by player shortage before the user taps the launch CTA.
2. **P0 move clarity:** When a player card is already assigned to another seat, label it and make the confirm action say it will move that player.
3. **P0 tap target safety:** Keep rule indicator dots visually small while increasing their actual button hit area.
4. **P1 continuous assignment:** Let users confirm a card and advance to the next empty seat without closing the drawer.
5. **P1 destructive-action safety:** Require a second tap before clearing all seats.
6. **P2 resilience polish:** Stop showing the classic 8-player artwork for unknown rule sets; render a text fallback card instead.

## File Structure

- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
  - Add behavior tests for launch readiness text, dynamic launch CTA labels, occupied-player move labels, continuous assignment, clear confirmation, larger rule-dot hit area, and unknown rule fallback.
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
  - Add derived launch status, occupied-seat lookup, move-aware drawer copy, continuous assignment handlers, clear confirmation state, and unknown rule-card fallback markup.
- Modify: `apps/mobile-web/src/styles/index.css`
  - Add styles for launch status text, occupied card badges, secondary drawer footer actions, clear confirmation state, larger rule-dot hit areas, and fallback rule cards.
- No backend, shared package, route, or asset changes.

## Current Code Notes

- `GamesPage` already has rule, profile, lineup, drawer, and launch state in `apps/mobile-web/src/pages/GamesPage.tsx`.
- Current `upsertSeatProfile` deliberately moves a profile from its old seat to the new seat by filtering out duplicate `profile_id` values before adding the new config.
- Current `handleSubmit` auto-fills empty seats before calling `createGameRun`; this behavior should stay, but the CTA should preview it.
- Current rule dots are actual 7px/18px buttons; the visual should remain small, but the button box should become finger-sized.
- Current tests already cover drawer open/confirm/close and visual CSS guardrails.

---

### Task 1: Add Launch Readiness and Dynamic CTA

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write failing tests for launch readiness**

Add these tests inside `describe("GamesPage", () => { ... })` after the existing creation and shortage tests:

```tsx
it("labels launch as auto-fill when empty seats can be completed from the library", async () => {
  renderGamesPage();

  expect(await screen.findByText("已选 0/2 · 可自动补齐")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "补齐并发起" }),
  ).toBeEnabled();
});

it("shows a ready launch state when every seat has a player", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(await screen.findByRole("button", { name: "随机补齐" }));

  expect(await screen.findByText("已选 2/2 · 阵容已就绪")).toBeVisible();
  expect(screen.getByRole("button", { name: "发起对局" })).toBeEnabled();
});

it("blocks launch before submit when the player library cannot fill the lineup", async () => {
  gameClientMocks.listPlayerProfiles.mockResolvedValue({
    profiles: [buildProfile({ id: "profile-1", display_name: "阿青" })],
  });
  renderGamesPage();

  expect(await screen.findByText("已选 0/2 · 还差 1 名玩家")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "还差 1 名玩家" }),
  ).toBeDisabled();
  expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: FAIL because the page still renders the static launch button text `发起对局` and has no `已选 N/M` readiness text.

- [ ] **Step 3: Add the launch status helper**

In `apps/mobile-web/src/pages/GamesPage.tsx`, add this type and helper near the other bottom-of-file helpers:

```tsx
type LineupLaunchStatus = {
  assignedCount: number;
  emptySeatCount: number;
  profileShortageCount: number;
  summaryText: string;
  ctaLabel: string;
  canLaunch: boolean;
};

function buildLineupLaunchStatus(
  configs: PlayerConfig[],
  profiles: VirtualPlayerProfile[],
  playerCount: number,
): LineupLaunchStatus {
  const assignedProfileIds = new Set(
    configs
      .map((config) => config.profile_id)
      .filter((profileId): profileId is string => Boolean(profileId)),
  );
  const assignedCount = assignedProfileIds.size;
  const emptySeatCount = Math.max(playerCount - assignedCount, 0);
  const availableProfileCount = Math.max(profiles.length - assignedCount, 0);
  const profileShortageCount = Math.max(
    emptySeatCount - availableProfileCount,
    0,
  );
  const countPrefix = `已选 ${assignedCount}/${playerCount}`;

  if (playerCount === 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount: 0,
      summaryText: "等待规则加载",
      ctaLabel: "发起对局",
      canLaunch: false,
    };
  }

  if (profileShortageCount > 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount,
      summaryText: `${countPrefix} · 还差 ${profileShortageCount} 名玩家`,
      ctaLabel: `还差 ${profileShortageCount} 名玩家`,
      canLaunch: false,
    };
  }

  if (emptySeatCount > 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount,
      summaryText: `${countPrefix} · 可自动补齐`,
      ctaLabel: "补齐并发起",
      canLaunch: true,
    };
  }

  return {
    assignedCount,
    emptySeatCount,
    profileShortageCount,
    summaryText: `${countPrefix} · 阵容已就绪`,
    ctaLabel: "发起对局",
    canLaunch: true,
  };
}
```

- [ ] **Step 4: Wire the helper into `GamesPage`**

After `const activeSeatProfile = selectedProfilesBySeat.get(safeActiveSeat) ?? null;`, add:

```tsx
const launchStatus = useMemo(
  () => buildLineupLaunchStatus(visiblePlayerConfigs, profiles, playerCount),
  [playerCount, profiles, visiblePlayerConfigs],
);
const isLaunchDisabled = isSubmitDisabled || !launchStatus.canLaunch;
```

Then in the action bar, insert the status before the launch button:

```tsx
<span className="mobile-lobby-launch-status">
  {launchStatus.summaryText}
</span>
```

Change the launch button from:

```tsx
disabled={isSubmitDisabled}
```

to:

```tsx
disabled={isLaunchDisabled}
```

Change the button text from:

```tsx
{createGameRunMutation.isPending ? "发起中" : "发起对局"}
```

to:

```tsx
{createGameRunMutation.isPending ? "发起中" : launchStatus.ctaLabel}
```

- [ ] **Step 5: Style the launch status without expanding the action bar**

Add this CSS near `.mobile-lobby-action-bar`:

```css
.mobile-lobby-launch-status {
  grid-column: 1 / -1;
  min-width: 0;
  overflow: hidden;
  color: #d4b977;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.2;
  text-align: center;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

If the action bar becomes too tall in the 375px screenshot, reduce `.mobile-lobby-action-bar .mobile-button` from `min-height: 40px` to `min-height: 38px`.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: PASS for the new launch readiness tests and the existing creation tests.

Commit:

```bash
git add apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat: clarify mobile lobby launch readiness"
```

---

### Task 2: Make Occupied Player Moves Explicit

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write the failing move-label test**

Add this test after the existing `"confirms a player card into the active seat"` test:

```tsx
it("labels player cards that are already assigned and confirms moves explicitly", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(
    await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  );
  await user.click(
    screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
  );
  await user.click(screen.getByRole("button", { name: "确认选择" }));

  await user.click(
    await screen.findByRole("button", {
      name: "选择 2 号座位，当前为 待选择",
    }),
  );

  expect(screen.getByText("已在 1 号座位")).toBeVisible();
  await user.click(
    screen.getByRole("button", { name: "为 2 号座位候选 阿青，已在 1 号座位" }),
  );
  expect(screen.getByRole("button", { name: "移动到 2 号座位" })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "移动到 2 号座位" }));

  await waitFor(() => {
    expect(
      screen.queryByRole("dialog", { name: "玩家卡牌库" }),
    ).not.toBeInTheDocument();
  });
  expect(
    screen.getByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", {
      name: "选择 2 号座位，当前为 阿青",
    }),
  ).toBeVisible();
});
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: FAIL because player cards do not display `已在 1 号座位` and the confirm button still says `确认选择`.

- [ ] **Step 3: Add occupied-seat derived state and label helpers**

In `GamesPage`, after `selectedProfilesBySeat`, add:

```tsx
const assignedSeatByProfileId = useMemo(
  () =>
    new Map(
      visiblePlayerConfigs
        .filter((config) => Boolean(config.profile_id))
        .map((config) => [config.profile_id as string, config.seat]),
    ),
  [visiblePlayerConfigs],
);
```

Add these helpers near the other bottom helpers:

```tsx
function getProfileSeatStatusLabel(
  assignedSeat: number | undefined,
  activeSeat: number,
) {
  if (!assignedSeat) {
    return null;
  }

  return assignedSeat === activeSeat
    ? "当前座位"
    : `已在 ${assignedSeat} 号座位`;
}

function getProfileChoiceAriaLabel(
  activeSeat: number,
  profile: VirtualPlayerProfile,
  seatStatusLabel: string | null,
) {
  return [
    `为 ${activeSeat} 号座位候选 ${profile.display_name}`,
    seatStatusLabel && seatStatusLabel !== "当前座位" ? seatStatusLabel : null,
  ]
    .filter(Boolean)
    .join("，");
}

function getConfirmProfileButtonLabel(
  pendingProfile: VirtualPlayerProfile | null,
  assignedSeat: number | undefined,
  activeSeat: number,
) {
  if (!pendingProfile) {
    return "确认选择";
  }

  if (assignedSeat && assignedSeat !== activeSeat) {
    return `移动到 ${activeSeat} 号座位`;
  }

  return "确认选择";
}
```

- [ ] **Step 4: Render seat status on player cards**

Inside `filteredProfiles.map((profile) => { ... })`, add:

```tsx
const assignedSeat = assignedSeatByProfileId.get(profile.id);
const seatStatusLabel = getProfileSeatStatusLabel(assignedSeat, safeActiveSeat);
```

Change the player card `aria-label` to:

```tsx
aria-label={getProfileChoiceAriaLabel(
  safeActiveSeat,
  profile,
  seatStatusLabel,
)}
```

After the strategy label span, render:

```tsx
{seatStatusLabel ? (
  <span className="mobile-profile-card-seat-status">
    {seatStatusLabel}
  </span>
) : null}
```

Before rendering the footer button, add:

```tsx
const pendingAssignedSeat = pendingProfileId
  ? assignedSeatByProfileId.get(pendingProfileId)
  : undefined;
```

Change the confirm button text to:

```tsx
{getConfirmProfileButtonLabel(
  pendingProfile,
  pendingAssignedSeat,
  safeActiveSeat,
)}
```

- [ ] **Step 5: Style occupied-seat labels**

Add this CSS near `.mobile-profile-card-choice > span:not(.mobile-profile-card-image)`:

```css
.mobile-profile-card-seat-status {
  justify-self: start;
  border: 1px solid rgb(218 179 96 / 28%);
  border-radius: 6px;
  padding: 3px 6px;
  background: rgb(4 8 14 / 62%);
  color: #efd08b;
  font-size: 11px;
  font-weight: 900;
  line-height: 1.1;
}
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: PASS for the occupied move test and previous drawer tests.

Commit:

```bash
git add apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat: clarify mobile lobby player moves"
```

---

### Task 3: Enlarge Rule Indicator Tap Targets

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Update the existing rule-dot CSS test**

In the test `"centers rule indicator dots and highlights the selected rule color"`, extend the CSS assertions:

```tsx
const dotRule = styles.match(/\.mobile-lobby-rule-dot\s*{[^}]+}/)?.[0] ?? "";
const dotBeforeRule =
  styles.match(/\.mobile-lobby-rule-dot::before\s*{[^}]+}/)?.[0] ?? "";
const activeDotBeforeRule =
  styles.match(/\.mobile-lobby-rule-dot-active::before\s*{[^}]+}/)?.[0] ?? "";

expect(dotRule).toContain("width: 36px");
expect(dotRule).toContain("height: 36px");
expect(dotRule).toContain("background: transparent");
expect(dotBeforeRule).toContain("width: 7px");
expect(dotBeforeRule).toContain("height: 7px");
expect(activeDotBeforeRule).toContain("width: 18px");
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: FAIL because `.mobile-lobby-rule-dot` is still the small visible dot itself.

- [ ] **Step 3: Change the CSS so the button is large and the dot is a pseudo-element**

Replace the existing `.mobile-lobby-rule-dot` and `.mobile-lobby-rule-dot-active` rules with:

```css
.mobile-lobby-rule-dot {
  display: inline-flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 999px;
  padding: 0;
  background: transparent;
  color: currentColor;
  cursor: pointer;
}

.mobile-lobby-rule-dot::before {
  display: block;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.45;
  transition:
    opacity 160ms ease,
    transform 160ms ease,
    width 160ms ease;
  content: "";
}

.mobile-lobby-rule-dot-active::before {
  width: 18px;
  opacity: 1;
}
```

Keep the existing tone classes:

```css
.mobile-lobby-rule-dot-classic {
  color: #d7a934;
}

.mobile-lobby-rule-dot-starter {
  color: #8eb8d6;
}

.mobile-lobby-rule-dot-social {
  color: #ba74d9;
}

.mobile-lobby-rule-dot-advanced {
  color: #e1972f;
}
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: PASS.

Commit:

```bash
git add apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/styles/index.css
git commit -m "fix: enlarge mobile lobby rule indicators"
```

---

### Task 4: Add Continuous Seat Assignment

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write the failing continuous-assignment test**

Add this test after the occupied move test:

```tsx
it("can confirm a player and advance to the next empty seat without closing the drawer", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(
    await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  );
  await user.click(
    screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
  );
  await user.click(screen.getByRole("button", { name: "确认并下一位" }));

  expect(screen.getByRole("dialog", { name: "玩家卡牌库" })).toBeVisible();
  expect(screen.getByText("当前选择：2号座位")).toBeVisible();
  expect(
    screen.getByRole("button", {
      name: "选择 1 号座位，当前为 阿青",
    }),
  ).toBeVisible();
  expect(screen.getByText("请选择一张玩家卡")).toBeVisible();
});
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: FAIL because the drawer footer only has `确认选择`.

- [ ] **Step 3: Add next-empty-seat helpers**

Add these helpers near `clampSeat`:

```tsx
function findNextEmptySeat(
  configs: PlayerConfig[],
  playerCount: number,
  currentSeat: number,
) {
  const assignedSeats = new Set(
    configs
      .filter((config) => Boolean(config.profile_id))
      .map((config) => config.seat),
  );
  const seats = Array.from({ length: playerCount }, (_, index) => index + 1);
  const afterCurrent = seats.filter((seat) => seat > currentSeat);
  const beforeOrCurrent = seats.filter((seat) => seat <= currentSeat);

  return [...afterCurrent, ...beforeOrCurrent].find(
    (seat) => !assignedSeats.has(seat),
  );
}

function hasNextEmptySeat(
  configs: PlayerConfig[],
  playerCount: number,
  currentSeat: number,
) {
  return findNextEmptySeat(configs, playerCount, currentSeat) !== undefined;
}
```

- [ ] **Step 4: Update confirm handler to optionally advance**

Replace `confirmPendingProfile()` with:

```tsx
function confirmPendingProfile(options: { advanceToNextEmpty?: boolean } = {}) {
  if (!pendingProfileId) {
    return;
  }

  const nextConfigs = upsertSeatProfile(
    visiblePlayerConfigs,
    safeActiveSeat,
    pendingProfileId,
  );
  const nextEmptySeat = findNextEmptySeat(
    nextConfigs,
    playerCount,
    safeActiveSeat,
  );

  setValidationError(null);
  setShortage(false);
  setPlayerConfigs(nextConfigs);

  if (options.advanceToNextEmpty && nextEmptySeat) {
    setActiveSeat(nextEmptySeat);
    setPendingProfileId(null);
    return;
  }

  setIsProfileDrawerOpen(false);
  setPendingProfileId(null);
}
```

Add this derived value before `return (`:

```tsx
const canAdvanceAfterConfirm =
  Boolean(pendingProfileId) &&
  hasNextEmptySeat(
    upsertSeatProfile(
      visiblePlayerConfigs,
      safeActiveSeat,
      pendingProfileId ?? "",
    ),
    playerCount,
    safeActiveSeat,
  );
```

If TypeScript objects to `pendingProfileId ?? ""`, replace the derived value with:

```tsx
const canAdvanceAfterConfirm = pendingProfileId
  ? hasNextEmptySeat(
      upsertSeatProfile(visiblePlayerConfigs, safeActiveSeat, pendingProfileId),
      playerCount,
      safeActiveSeat,
    )
  : false;
```

- [ ] **Step 5: Add the secondary footer button**

In `.mobile-profile-drawer-footer`, before the existing confirm button, add:

```tsx
<button
  className="mobile-button mobile-profile-drawer-secondary-action"
  disabled={!canAdvanceAfterConfirm}
  onClick={() => confirmPendingProfile({ advanceToNextEmpty: true })}
  type="button"
>
  确认并下一位
</button>
```

Keep the existing primary confirm button and change its click handler to:

```tsx
onClick={() => confirmPendingProfile()}
```

- [ ] **Step 6: Style the footer for two actions**

Replace `.mobile-profile-drawer-footer` grid columns with:

```css
grid-template-columns: minmax(0, 1fr) minmax(108px, auto) minmax(108px, auto);
```

Add:

```css
.mobile-profile-drawer-secondary-action {
  border-color: rgb(218 179 96 / 28%);
  background: #111924;
  color: #efd08b;
}
```

Inside `@media (max-width: 360px)`, add:

```css
.mobile-profile-drawer-footer {
  grid-template-columns: 1fr;
}
```

- [ ] **Step 7: Run tests and commit**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: PASS.

Commit:

```bash
git add apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat: support continuous mobile lobby seat assignment"
```

---

### Task 5: Add Two-Tap Clear Confirmation

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write the failing clear-confirmation test**

Add this test near the creation action tests:

```tsx
it("requires a second tap before clearing assigned seats", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(await screen.findByRole("button", { name: "随机补齐" }));
  expect(
    screen.getByRole("button", {
      name: "选择 1 号座位，当前为 阿青",
    }),
  ).toBeVisible();

  await user.click(screen.getByRole("button", { name: "清空席位" }));
  expect(screen.getByRole("button", { name: "确认清空" })).toBeVisible();
  expect(
    screen.getByRole("button", {
      name: "选择 1 号座位，当前为 阿青",
    }),
  ).toBeVisible();

  await user.click(screen.getByRole("button", { name: "确认清空" }));
  expect(
    screen.getByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  ).toBeVisible();
});
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: FAIL because `清空席位` clears immediately.

- [ ] **Step 3: Add clear confirmation state**

In `GamesPage`, add state near the other local UI state:

```tsx
const [isClearConfirming, setIsClearConfirming] = useState(false);
```

Add this effect after the drawer focus effects:

```tsx
useEffect(() => {
  if (!isClearConfirming) {
    return;
  }

  const timeoutId = window.setTimeout(() => {
    setIsClearConfirming(false);
  }, 3000);

  return () => window.clearTimeout(timeoutId);
}, [isClearConfirming]);
```

Add this handler near `fillEmptySeats`:

```tsx
function handleClearSeats() {
  const hasAssignedSeats = visiblePlayerConfigs.some((config) =>
    hasPlayerConfig(config),
  );

  if (!hasAssignedSeats) {
    setPlayerConfigs([]);
    setShortage(false);
    setValidationError(null);
    setIsClearConfirming(false);
    return;
  }

  if (!isClearConfirming) {
    setIsClearConfirming(true);
    return;
  }

  setPlayerConfigs([]);
  setShortage(false);
  setValidationError(null);
  setIsClearConfirming(false);
}
```

- [ ] **Step 4: Wire the clear button**

Replace the current clear button `onClick` block with:

```tsx
onClick={handleClearSeats}
```

Change its className to:

```tsx
className={[
  "mobile-button",
  isClearConfirming ? "mobile-lobby-clear-confirming" : "",
]
  .filter(Boolean)
  .join(" ")}
```

Change its text to:

```tsx
{isClearConfirming ? "确认清空" : "清空席位"}
```

In `fillEmptySeats`, `openProfileDrawer`, `handleRuleSetChange`, and `confirmPendingProfile`, add:

```tsx
setIsClearConfirming(false);
```

- [ ] **Step 5: Style the confirmation state**

Add near `.mobile-lobby-action-bar .mobile-button`:

```css
.mobile-lobby-action-bar .mobile-lobby-clear-confirming {
  border-color: rgb(248 113 113 / 58%);
  background: rgb(66 16 16 / 84%);
  color: #fecaca;
}
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: PASS.

Commit:

```bash
git add apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/styles/index.css
git commit -m "fix: confirm destructive mobile lobby clearing"
```

---

### Task 6: Add Unknown Rule Card Fallback

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write the failing unknown-rule test**

Add this test near the rule-card tests:

```tsx
it("renders a text fallback instead of classic artwork for unknown rule card assets", async () => {
  gameClientMocks.listRuleSets.mockResolvedValue({
    rule_sets: [
      {
        ...classicRuleSet,
        id: "custom_10",
        name: "自定义 10 人局",
        player_count: 10,
        role_summary: "3 狼人 / 7 好人",
        complexity: "自定义",
      },
    ],
  });
  renderGamesPage();

  const selectedRule = await screen.findByRole("radio", {
    name: "选择规则 自定义 10 人局",
  });
  const selectedCard = selectedRule.closest(".mobile-lobby-rule-card");

  expect(selectedCard).toHaveTextContent("自定义 10 人局");
  expect(selectedCard).toHaveTextContent("10 人局");
  expect(selectedCard).toHaveTextContent("3 狼人 / 7 好人");
  expect(
    selectedCard?.querySelector(".mobile-lobby-rule-card-image"),
  ).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: FAIL because unknown rules currently use the classic 8-player artwork fallback.

- [ ] **Step 3: Return `null` for unknown rule images**

Change `getRuleCardImage` to:

```tsx
function getRuleCardImage(ruleSetId: string, isSelected: boolean) {
  const images = ruleCardImagesById[ruleSetId];

  if (!images) {
    return null;
  }

  return isSelected ? images.selected : images.unselected;
}
```

- [ ] **Step 4: Render fallback markup**

Inside the rule card map, keep:

```tsx
const ruleCardImage = getRuleCardImage(ruleSet.id, isSelected);
```

Replace the unconditional image with:

```tsx
{ruleCardImage ? (
  <img
    alt=""
    aria-hidden="true"
    className="mobile-lobby-rule-card-image"
    src={ruleCardImage}
  />
) : (
  <span className="mobile-lobby-rule-card-fallback">
    <strong>{ruleSet.name}</strong>
    <span>{ruleSet.player_count} 人局</span>
    <small>{ruleSet.role_summary ?? ruleSet.complexity ?? "自定义规则"}</small>
  </span>
)}
```

- [ ] **Step 5: Style fallback cards**

Add near `.mobile-lobby-rule-card-image`:

```css
.mobile-lobby-rule-card-fallback {
  display: grid;
  min-height: 0;
  aspect-ratio: 3 / 4;
  box-sizing: border-box;
  align-content: end;
  gap: 6px;
  padding: 10px;
  border: 1px solid rgb(218 179 96 / 34%);
  border-radius: 6px;
  background:
    linear-gradient(180deg, rgb(13 22 32 / 72%), rgb(5 8 13 / 96%)),
    radial-gradient(circle at 50% 18%, rgb(239 208 139 / 18%), transparent 46%);
  color: #f4e8d2;
}

.mobile-lobby-rule-card-fallback strong,
.mobile-lobby-rule-card-fallback span,
.mobile-lobby-rule-card-fallback small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mobile-lobby-rule-card-fallback strong {
  color: #fff1cc;
  font-size: 13px;
  line-height: 1.2;
  white-space: nowrap;
}

.mobile-lobby-rule-card-fallback span {
  color: #efd08b;
  font-size: 12px;
  font-weight: 900;
  line-height: 1.15;
}

.mobile-lobby-rule-card-fallback small {
  display: -webkit-box;
  color: #c8d4de;
  font-size: 10px;
  line-height: 1.25;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
```

Expected: PASS.

Commit:

```bash
git add apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/styles/index.css
git commit -m "fix: render unknown mobile lobby rules honestly"
```

---

## Visual QA

After all tasks pass, start the local app and verify at 375px width:

```bash
pnpm --dir apps/mobile-web dev
```

Open:

```text
http://127.0.0.1:5174/games
```

Check these states:

- Main lobby, empty lineup: readiness text says `已选 0/8 · 可自动补齐` when enough profiles exist.
- Main lobby, insufficient profiles: launch button says `还差 N 名玩家` and is disabled.
- Drawer opened from seat 1: footer has `确认并下一位` and `确认选择`.
- Drawer after selecting an already assigned player from another seat: card says `已在 X 号座位` and primary button says `移动到 Y 号座位`.
- Rule dots can be tapped without requiring pixel-perfect precision.
- `清空席位` does not clear until the second tap.
- Unknown rule cards show text and do not reuse classic artwork.

Take screenshots:

```text
output/mobile-lobby-review/mobile-lobby-375x812.png
output/mobile-lobby-review/mobile-lobby-drawer-375x812.png
```

## Final Verification

Run:

```bash
pnpm --dir apps/mobile-web test -- --run GamesPage.test.tsx
pnpm --dir apps/mobile-web build
```

Expected:

- Test command exits 0.
- Build command exits 0.
- No TypeScript errors from the new helpers.
- No text overflow in the 375px screenshots.

## Self-Review

- Spec coverage: P0 launch clarity, P0 move clarity, P0 tap targets, P1 continuous assignment, P1 destructive confirmation, and P2 unknown rule fallback each have a task.
- Placeholder scan: no unresolved placeholder text, no open-ended test instructions, and each task includes exact file paths, code snippets, commands, and expected outcomes.
- Type consistency: helper signatures use existing `PlayerConfig` and `VirtualPlayerProfile` imports already available in `GamesPage.tsx`; no new package API is required.
