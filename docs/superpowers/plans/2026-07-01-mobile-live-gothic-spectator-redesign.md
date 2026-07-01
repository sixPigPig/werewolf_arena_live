# Mobile Live Gothic Spectator Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the mobile live spectator page into a dark gothic, reference-image-inspired vertical theater while preserving the existing realtime data flow and controls.

**Architecture:** Keep `apps/mobile-web/src/pages/LivePage.tsx` as the only React surface for this change. Add speaker avatar rendering to the existing center stage and perform the larger transformation in the existing `.mobile-live-*` CSS block so routing, data derivation, controls, and accessibility labels stay stable.

**Tech Stack:** React 19, Vite, Vitest, Testing Library, CSS in `apps/mobile-web/src/styles/index.css`, workspace package `@werewolf-arena/game-client`.

---

## File Structure

- Modify `apps/mobile-web/src/pages/LivePage.tsx`
  - Add avatar image rendering to `LiveCenterStage`.
  - Reuse the existing `resolveAvatarImageUrl` helper.
  - Preserve existing aria labels, control behavior, and data flow.
- Modify `apps/mobile-web/src/styles/index.css`
  - Replace the current `.mobile-live-*` theater styling with the gothic theater treatment.
  - Keep the mobile tab hiding rule outside this block unchanged.
  - Keep compact typography expectations intact.
- Modify `apps/mobile-web/src/pages/LivePage.test.tsx`
  - Add a failing test for the center-stage speaker avatar.
  - Add a failing test for durable gothic style markers.
  - Keep existing route, aria label, API avatar URL, and short-screen tests.
- No changes expected in `apps/mobile-web/src/app/App.test.tsx`
  - The existing compact typography test should continue to pass by keeping `.mobile-live-center-stage strong { font-size: 18px; }`.

---

### Task 1: Add Center Speaker Avatar Test

**Files:**
- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`

- [ ] **Step 1: Import `within` from Testing Library**

Change the import at the top of `apps/mobile-web/src/pages/LivePage.test.tsx` from:

```tsx
import { render, screen } from "@testing-library/react";
```

to:

```tsx
import { render, screen, within } from "@testing-library/react";
```

- [ ] **Step 2: Add a public speaking event fixture**

Add this constant immediately after `gameStartedEvent`:

```tsx
const speakingDeltaEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "model_response_delta",
  actor: "阿青",
  action: "debate",
  payload: {
    request_id: "req-1",
    visible_text: "我先听后置位发言。",
  },
};
```

- [ ] **Step 3: Add the failing center-stage avatar test**

Add this test after `renders live seat avatars through API asset URLs`:

```tsx
  it("renders the current stage presenter with the speaker avatar asset", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, speakingDeltaEvent],
      latestEvent: speakingDeltaEvent,
    });

    renderLiveRoute();

    const stage = await screen.findByRole("region", { name: "当前舞台" });
    expect(within(stage).getByText("阿青")).toBeVisible();

    const presenterImage = stage.querySelector(".mobile-live-presenter img");
    expect(presenterImage).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });
```

- [ ] **Step 4: Run the focused test and verify it fails**

Run:

```bash
pnpm --filter mobile-web test -- --run src/pages/LivePage.test.tsx -t "speaker avatar asset"
```

Expected: FAIL because `.mobile-live-presenter` currently renders only text, so `presenterImage` is `null`.

---

### Task 2: Render the Center Speaker Avatar

**Files:**
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
- Test: `apps/mobile-web/src/pages/LivePage.test.tsx`

- [ ] **Step 1: Update `LiveCenterStage` to resolve and render the speaker avatar**

Replace the whole `LiveCenterStage` function body in `apps/mobile-web/src/pages/LivePage.tsx` with:

```tsx
function LiveCenterStage({
  currentEvent,
  currentPlayer,
  godViewState,
}: LiveCenterStageProps) {
  const presenterAvatarImageUrl = currentPlayer
    ? resolveAvatarImageUrl({
        avatar_image_url: currentPlayer.avatarImageUrl,
      })
    : null;

  return (
    <section className="mobile-live-center-stage" aria-label="当前舞台">
      <div className="mobile-live-presenter" aria-hidden="true">
        {presenterAvatarImageUrl ? (
          <img alt="" src={presenterAvatarImageUrl} />
        ) : (
          <span>
            {currentPlayer
              ? avatarInitial(currentPlayer.name, currentPlayer.seatNumber)
              : "?"}
          </span>
        )}
      </div>
      <span>{currentPlayer ? `${currentPlayer.seatNumber}号` : "等待"}</span>
      <strong>{currentPlayer?.name ?? "等待玩家行动"}</strong>
      <em>{currentPlayer?.stageStatus.label ?? godViewState.currentSeatLabel}</em>
      <p>{currentEvent?.type ?? "等待事件"}</p>
      {currentEvent?.action ? <small>{currentEvent.action}</small> : null}
    </section>
  );
}
```

- [ ] **Step 2: Run the focused avatar test and verify it passes**

Run:

```bash
pnpm --filter mobile-web test -- --run src/pages/LivePage.test.tsx -t "speaker avatar asset"
```

Expected: PASS.

- [ ] **Step 3: Run the full mobile live page test**

Run:

```bash
pnpm --filter mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Commit the avatar rendering slice**

Run:

```bash
git add apps/mobile-web/src/pages/LivePage.tsx apps/mobile-web/src/pages/LivePage.test.tsx
git commit -m "feat(mobile): show live speaker avatar on stage"
```

---

### Task 3: Add Gothic Visual Contract Tests

**Files:**
- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`

- [ ] **Step 1: Add CSS contract coverage for the gothic theater**

Add this test before `compresses theater seats on short phone screens`:

```tsx
  it("uses gothic spectator surfaces for the mobile live theater", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const pageRule =
      styles.match(/(?:^|\n)\.mobile-live-page\s*{[^}]+}/)?.[0] ?? "";
    const theaterBeforeRule =
      styles.match(/\.mobile-live-theater::before\s*{[^}]+}/)?.[0] ?? "";
    const skyOrbRule =
      styles.match(/(?:^|\n)\.mobile-live-sky-orb\s*{[^}]+}/)?.[0] ?? "";
    const presenterRule =
      styles.match(/(?:^|\n)\.mobile-live-presenter\s*{[^}]+}/)?.[0] ?? "";
    const focusRule =
      styles.match(/(?:^|\n)\.mobile-live-focus-strip\s*{[^}]+}/)?.[0] ?? "";

    expect(pageRule).toContain("mobile-gothic-castle-background.png");
    expect(theaterBeforeRule).toContain("linear-gradient(180deg");
    expect(skyOrbRule).toContain("border: 4px double");
    expect(presenterRule).toContain("aspect-ratio: 0.66");
    expect(focusRule).toContain("grid-template-columns: 42px minmax(0, 1fr) auto");
  });
```

- [ ] **Step 2: Update the short-screen CSS expectation to the new compact avatar size**

In `compresses theater seats on short phone screens`, replace:

```tsx
      /@media \(max-height: 700px\) {[\s\S]*?\.mobile-live-seat-avatar\s*{[^}]+width: clamp\(32px, 10\.8vw, 40px\)/,
```

with:

```tsx
      /@media \(max-height: 700px\) {[\s\S]*?\.mobile-live-seat-avatar\s*{[^}]+width: clamp\(34px, 10\.8vw, 42px\)/,
```

- [ ] **Step 3: Run the focused CSS test and verify it fails**

Run:

```bash
pnpm --filter mobile-web test -- --run src/pages/LivePage.test.tsx -t "gothic spectator surfaces"
```

Expected: FAIL because the current CSS does not reference `mobile-gothic-castle-background.png`, does not use a double-border moon ring, and the presenter still uses the old aspect ratio.

---

### Task 4: Apply Gothic Mobile Theater Styling

**Files:**
- Modify: `apps/mobile-web/src/styles/index.css`
- Test: `apps/mobile-web/src/pages/LivePage.test.tsx`
- Test: `apps/mobile-web/src/app/App.test.tsx`

- [ ] **Step 1: Replace the current mobile live CSS block**

In `apps/mobile-web/src/styles/index.css`, replace the block from `.mobile-live-page {` through the closing `}` of `@media (max-height: 700px)` with this CSS:

```css
.mobile-live-page {
  position: relative;
  min-height: 100svh;
  overflow: hidden;
  padding: 0;
  background:
    linear-gradient(180deg, rgb(2 3 6 / 38%), rgb(2 4 8 / 80)),
    url("../assets/mobile-gothic-castle-background.png") center / cover no-repeat,
    #05070a;
}

.mobile-live-page::before {
  position: absolute;
  inset: 0;
  z-index: 0;
  background:
    radial-gradient(circle at 50% 21%, rgb(176 194 219 / 38%) 0 8%, transparent 28%),
    linear-gradient(90deg, rgb(65 8 14 / 72%), transparent 24% 76%, rgb(65 8 14 / 72%)),
    linear-gradient(180deg, rgb(0 0 0 / 18%), rgb(0 0 0 / 58%));
  pointer-events: none;
  content: "";
}

.mobile-live-page:has(.mobile-live-theater) > .mobile-status-banner {
  position: absolute;
  top: calc(62px + env(safe-area-inset-top));
  right: 10px;
  left: 10px;
  z-index: 5;
  max-height: min(28svh, 120px);
  box-sizing: border-box;
  overflow-y: auto;
  margin: 0;
  border-color: rgb(190 74 74 / 54%);
  padding: 8px 10px;
  background: rgb(39 10 13 / 90%);
  box-shadow: 0 8px 22px rgb(0 0 0 / 44%);
}

.mobile-live-theater {
  position: relative;
  z-index: 1;
  isolation: isolate;
  display: grid;
  grid-template-rows: auto minmax(172px, 27svh) minmax(0, 1fr) auto;
  min-height: 100svh;
  box-sizing: border-box;
  overflow: hidden;
  padding: calc(10px + env(safe-area-inset-top)) 10px calc(10px + env(safe-area-inset-bottom));
  color: #f5e7c9;
}

.mobile-live-theater::before,
.mobile-live-theater::after {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: -1;
  width: 31%;
  pointer-events: none;
  content: "";
}

.mobile-live-theater::before {
  left: 0;
  background:
    linear-gradient(180deg, rgb(42 7 10 / 88%) 0 12%, transparent 28%),
    linear-gradient(90deg, rgb(24 3 6 / 88%), rgb(57 7 13 / 54%) 54%, transparent);
}

.mobile-live-theater::after {
  right: 0;
  background:
    linear-gradient(180deg, rgb(42 7 10 / 88%) 0 12%, transparent 28%),
    linear-gradient(270deg, rgb(24 3 6 / 88%), rgb(57 7 13 / 54%) 54%, transparent);
}

.mobile-live-theater-top {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 50px;
}

.mobile-live-back-button {
  width: 42px;
  height: 42px;
  border: 1px solid rgb(234 203 149 / 52%);
  border-radius: 999px;
  background:
    radial-gradient(circle at 38% 28%, rgb(245 222 174 / 24%), transparent 24%),
    linear-gradient(180deg, #322821, #0d0d10 72%);
  color: #f5e7c9;
  font-size: 31px;
  font-weight: 800;
  line-height: 1;
  box-shadow:
    inset 0 0 0 2px rgb(0 0 0 / 45%),
    0 6px 18px rgb(0 0 0 / 56%);
}

.mobile-live-theater-top div {
  position: relative;
  display: grid;
  min-width: 0;
  gap: 3px;
  min-height: 38px;
  align-content: center;
  border: 1px solid rgb(190 154 96 / 52%);
  border-radius: 4px;
  padding: 0 12px;
  background:
    linear-gradient(90deg, transparent, rgb(8 7 8 / 88%) 10% 90%, transparent),
    linear-gradient(180deg, rgb(56 43 31 / 82%), rgb(10 10 12 / 88%));
  box-shadow:
    inset 0 1px 0 rgb(255 235 186 / 12%),
    0 8px 20px rgb(0 0 0 / 36%);
}

.mobile-live-theater-top div::before,
.mobile-live-theater-top div::after {
  position: absolute;
  top: 50%;
  width: 7px;
  height: 7px;
  border: 1px solid rgb(190 154 96 / 72%);
  background: #1a1010;
  content: "";
  transform: translateY(-50%) rotate(45deg);
}

.mobile-live-theater-top div::before {
  left: -5px;
}

.mobile-live-theater-top div::after {
  right: -5px;
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
  color: #ead2a2;
  font-size: 14px;
  line-height: 1.1;
  text-shadow: 0 1px 8px rgb(0 0 0 / 80%);
}

.mobile-live-theater-top span {
  color: #bba681;
  font-size: 11px;
  font-weight: 800;
  line-height: 1.1;
}

.mobile-live-connection {
  max-width: 84px;
  border: 1px solid rgb(190 154 96 / 42%);
  border-radius: 999px;
  padding: 6px 8px;
  background: rgb(10 10 12 / 82%);
  color: #d9c59a;
  font-size: 11px;
  font-weight: 900;
  box-shadow: inset 0 0 12px rgb(0 0 0 / 42%);
}

.mobile-live-sky {
  position: relative;
  display: grid;
  place-items: start center;
  overflow: visible;
  min-height: 172px;
}

.mobile-live-sky::before {
  position: absolute;
  top: 4px;
  left: 50%;
  width: min(64vw, 252px);
  aspect-ratio: 1;
  border-radius: 999px;
  background:
    radial-gradient(circle at 50% 45%, rgb(176 194 219 / 42%) 0 22%, rgb(30 42 56 / 48%) 37%, transparent 64%),
    radial-gradient(circle at 50% 50%, rgb(0 0 0 / 20%), transparent 68%);
  box-shadow: 0 0 34px rgb(132 166 202 / 22%);
  content: "";
  transform: translateX(-50%);
}

.mobile-live-sky-orb {
  position: relative;
  z-index: 1;
  width: min(56vw, 228px);
  aspect-ratio: 1;
  border: 4px double rgb(194 160 103 / 78%);
  border-radius: 999px;
  background:
    radial-gradient(circle at 48% 36%, rgb(202 216 232 / 70%) 0 17%, rgb(82 103 127 / 54%) 31%, rgb(8 15 23 / 58%) 56%, rgb(0 0 0 / 64%) 100%);
  box-shadow:
    inset 0 0 0 9px rgb(0 0 0 / 34%),
    inset 0 0 28px rgb(0 0 0 / 72%),
    0 0 30px rgb(180 197 223 / 22%),
    0 16px 34px rgb(0 0 0 / 44%);
}

.mobile-live-day-banner {
  position: absolute;
  z-index: 2;
  top: 59px;
  right: 31px;
  left: 31px;
  display: grid;
  min-height: 61px;
  place-items: center;
  border-top: 1px solid rgb(224 194 138 / 44%);
  border-bottom: 1px solid rgb(224 194 138 / 44%);
  background: linear-gradient(90deg, transparent, rgb(7 7 9 / 82%) 14% 86%, transparent);
  text-align: center;
  text-shadow: 0 2px 12px rgb(0 0 0 / 82%);
}

.mobile-live-day-banner span {
  color: #bba681;
  font-size: 11px;
  font-weight: 900;
  line-height: 1.1;
}

.mobile-live-day-banner strong {
  color: #ead2a2;
  font-size: 30px;
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

.mobile-live-seat-stage::before {
  position: absolute;
  inset: 9% 17% 0;
  border: 1px solid rgb(155 124 79 / 24%);
  border-bottom: 0;
  border-radius: 100px 100px 0 0;
  background: linear-gradient(180deg, rgb(6 10 15 / 20%), rgb(5 5 7 / 52%));
  pointer-events: none;
  content: "";
}

.mobile-live-seat-column {
  position: relative;
  z-index: 2;
  display: grid;
  align-content: center;
  gap: clamp(5px, 1.15svh, 9px);
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
  color: #f5e7c9;
}

.mobile-live-seat-number {
  position: absolute;
  top: -3px;
  left: -2px;
  z-index: 2;
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border: 1px solid rgb(213 182 121 / 70%);
  border-radius: 999px;
  background:
    radial-gradient(circle at 35% 30%, rgb(235 208 158 / 30%), transparent 32%),
    #171317;
  color: #ead2a2;
  font-size: 10px;
  font-weight: 900;
  box-shadow: 0 3px 10px rgb(0 0 0 / 62%);
}

.mobile-live-seat-avatar {
  display: grid;
  width: clamp(43px, 12.4vw, 58px);
  aspect-ratio: 1;
  place-items: center;
  overflow: hidden;
  border: 2px solid rgb(194 160 103 / 86%);
  border-radius: 999px;
  background:
    radial-gradient(circle at 40% 28%, rgb(92 112 133), rgb(7 9 12) 68%),
    #090a0d;
  box-shadow:
    inset 0 0 0 2px rgb(0 0 0 / 54%),
    0 4px 14px rgb(0 0 0 / 54%);
}

.mobile-live-seat-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.mobile-live-seat-avatar > span {
  color: #ead2a2;
  font-size: 18px;
  font-weight: 900;
}

.mobile-live-seat-role {
  position: absolute;
  top: -5px;
  right: 2px;
  z-index: 2;
  display: grid;
  width: 23px;
  height: 23px;
  place-items: center;
  border: 1px solid rgb(241 222 174 / 34%);
  border-radius: 999px;
  background: #8d2026;
  color: #fff2d2;
  font-size: 11px;
  font-weight: 900;
  box-shadow: 0 4px 12px rgb(0 0 0 / 56%);
}

.mobile-live-seat strong,
.mobile-live-seat small {
  max-width: 64px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-live-seat strong {
  color: #ead2a2;
  font-size: 11px;
  line-height: 1.15;
  text-shadow: 0 1px 8px rgb(0 0 0 / 84%);
}

.mobile-live-seat small {
  color: #bba681;
  font-size: 10px;
  font-weight: 800;
  line-height: 1.1;
}

.mobile-live-seat-speaking .mobile-live-seat-avatar {
  border-color: #d5b679;
  box-shadow:
    inset 0 0 0 2px rgb(0 0 0 / 50%),
    0 0 0 3px rgb(148 28 34 / 44%),
    0 0 18px rgb(213 182 121 / 62%);
}

.mobile-live-seat-speaking .mobile-live-seat-role {
  background: #a7272d;
}

.mobile-live-seat-out {
  opacity: 0.52;
  filter: grayscale(1);
}

.mobile-live-center-stage {
  position: relative;
  z-index: 1;
  align-self: end;
  display: grid;
  min-width: 0;
  justify-items: center;
  gap: 5px;
  padding: 8px 6px 14px;
  text-align: center;
}

.mobile-live-center-stage::before {
  position: absolute;
  right: 6%;
  bottom: 0;
  left: 6%;
  z-index: -1;
  height: 40%;
  border: 1px solid rgb(155 124 79 / 32%);
  border-radius: 50px 50px 12px 12px;
  background: linear-gradient(180deg, rgb(8 8 10 / 24%), rgb(7 7 8 / 74%));
  box-shadow: inset 0 -16px 30px rgb(0 0 0 / 54%);
  content: "";
}

.mobile-live-presenter {
  display: grid;
  width: clamp(92px, 31vw, 138px);
  aspect-ratio: 0.66;
  place-items: center;
  overflow: hidden;
  border: 2px solid rgb(194 160 103 / 72%);
  border-radius: 62px 62px 18px 18px;
  background:
    radial-gradient(circle at 50% 18%, rgb(215 191 150 / 24%), transparent 28%),
    linear-gradient(180deg, #24252c, #07080b 48%, #1b0d10);
  color: #ead2a2;
  font-size: 34px;
  font-weight: 900;
  box-shadow:
    inset 0 0 0 3px rgb(0 0 0 / 46%),
    0 0 36px rgb(213 182 121 / 22%),
    0 18px 40px rgb(0 0 0 / 48%);
}

.mobile-live-presenter img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.mobile-live-presenter > span {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
}

.mobile-live-center-stage > span {
  color: #c7aa70;
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
  text-shadow: 0 1px 8px rgb(0 0 0 / 82%);
}

.mobile-live-center-stage strong {
  color: #f5e7c9;
  font-size: 18px;
  line-height: 1.15;
}

.mobile-live-center-stage em {
  color: #bba681;
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.mobile-live-center-stage p {
  color: #ead2a2;
  font-size: 13px;
  font-weight: 900;
}

.mobile-live-center-stage small {
  color: #a99573;
  font-size: 11px;
  font-weight: 800;
}

.mobile-live-control-deck {
  position: relative;
  z-index: 3;
  display: grid;
  gap: 8px;
}

.mobile-live-focus-strip {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 52px;
  border: 1px solid rgb(190 154 96 / 58%);
  border-radius: 8px;
  padding: 0 12px;
  background:
    linear-gradient(90deg, rgb(7 7 9 / 86%), rgb(32 25 21 / 88%) 50%, rgb(7 7 9 / 86%)),
    linear-gradient(180deg, rgb(80 63 42 / 82%), rgb(9 9 11 / 92%));
  color: #f5e7c9;
  box-shadow:
    inset 0 1px 0 rgb(255 236 190 / 13%),
    0 -8px 24px rgb(0 0 0 / 38%);
}

.mobile-live-focus-strip span {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid rgb(213 182 121 / 52%);
  border-radius: 999px;
  background: rgb(6 6 8 / 78%);
  color: #ead2a2;
  font-size: 18px;
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
  color: #ead2a2;
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
  overflow: hidden;
  border-color: rgb(190 154 96 / 44%);
  padding-right: 8px;
  padding-left: 8px;
  background:
    radial-gradient(circle at 50% 0, rgb(234 203 149 / 13%), transparent 42%),
    rgb(13 12 13 / 88%);
  color: #f5e7c9;
  text-align: center;
  text-decoration: none;
  text-overflow: ellipsis;
  white-space: nowrap;
  box-shadow: inset 0 0 14px rgb(0 0 0 / 46%);
}

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

@media (max-height: 700px) {
  .mobile-live-theater {
    grid-template-rows: auto minmax(138px, 22svh) minmax(0, 1fr) auto;
    padding: calc(8px + env(safe-area-inset-top)) 8px calc(8px + env(safe-area-inset-bottom));
  }

  .mobile-live-sky {
    min-height: 138px;
  }

  .mobile-live-sky-orb {
    width: min(50vw, 184px);
  }

  .mobile-live-day-banner {
    top: 44px;
    min-height: 48px;
  }

  .mobile-live-day-banner strong {
    font-size: 24px;
  }

  .mobile-live-seat-column {
    gap: 3px;
  }

  .mobile-live-seat-avatar {
    width: clamp(34px, 10.8vw, 42px);
  }

  .mobile-live-seat strong {
    font-size: 10px;
  }

  .mobile-live-seat small {
    display: none;
  }

  .mobile-live-center-stage {
    gap: 3px;
    padding: 6px 5px 10px;
  }

  .mobile-live-presenter {
    width: clamp(74px, 24vw, 98px);
  }

  .mobile-live-focus-strip {
    min-height: 44px;
  }

  .mobile-live-action-bar .mobile-button,
  .mobile-live-link {
    min-height: 36px;
  }
}
```

- [ ] **Step 2: Run the focused CSS contract test**

Run:

```bash
pnpm --filter mobile-web test -- --run src/pages/LivePage.test.tsx -t "gothic spectator surfaces"
```

Expected: PASS.

- [ ] **Step 3: Run the full mobile live page test**

Run:

```bash
pnpm --filter mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run the mobile app typography and route smoke tests**

Run:

```bash
pnpm --filter mobile-web test -- --run src/app/App.test.tsx
```

Expected: PASS, including the existing assertion that `.mobile-live-center-stage strong` contains `font-size: 18px`.

- [ ] **Step 5: Commit the gothic styling slice**

Run:

```bash
git add apps/mobile-web/src/styles/index.css apps/mobile-web/src/pages/LivePage.test.tsx
git commit -m "feat(mobile): restyle live spectator theater"
```

---

### Task 5: Final Verification and Local Preview

**Files:**
- No code changes expected.
- Verify: `apps/mobile-web`

- [ ] **Step 1: Run the complete mobile-web test suite**

Run:

```bash
pnpm --filter mobile-web test -- --run
```

Expected: PASS.

- [ ] **Step 2: Run the mobile-web build**

Run:

```bash
pnpm --filter mobile-web build
```

Expected: PASS with Vite build output and no TypeScript errors.

- [ ] **Step 3: Start the mobile-web dev server for visual QA**

Run:

```bash
pnpm --filter mobile-web dev
```

Expected: Vite starts on `http://127.0.0.1:5174`. Keep the session running until visual QA is complete.

- [ ] **Step 4: Inspect the live page at mobile dimensions**

Open a live route in the browser, such as:

```text
http://127.0.0.1:5174/games/run-1/live
```

Check these viewport sizes:

- `390x844`: background, rule plaque, moon ring, player rails, presenter, and bottom bar are visible.
- `360x640`: player names truncate, short-screen avatar rule applies, bottom controls remain tappable.
- `430x932`: composition keeps a one-screen gothic theater and does not leave the center stage visually empty.

- [ ] **Step 5: Stop the dev server**

Stop the running Vite process with `Ctrl-C`.

- [ ] **Step 6: Confirm git status is clean**

Run:

```bash
git status --short
```

Expected: no output.
