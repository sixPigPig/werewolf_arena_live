# Mobile Live Phase Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the clickable `夜一 -> 昼一 -> 夜二 -> 昼二` phase bar to the mobile live spectator page.

**Architecture:** Reuse `buildLivePhaseSegments` and `useLiveDirector.seekToEventId` from `@werewolf-arena/game-client`. The mobile live page computes phase segments from the full SSE event list while its theater continues deriving visible stage state from `stageEvents`.

**Tech Stack:** TypeScript, React, Vitest, Testing Library, Vite, pnpm workspace packages.

---

### Task 1: Mobile Phase Bar Component

**Files:**
- Create: `apps/mobile-web/src/components/MobileLivePhaseBar.tsx`
- Create: `apps/mobile-web/src/components/MobileLivePhaseBar.test.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write the failing component test**

Test that the component renders phase buttons, marks the current phase with `aria-current="step"`, calls `onSelectPhase` with the clicked segment, and renders nothing for an empty list.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --dir apps/mobile-web test -- --run src/components/MobileLivePhaseBar.test.tsx`
Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the component and mobile styling**

Create a compact horizontally scrollable phase rail using mobile-specific class names. Keep it semantic with `nav`, `role="list"`, and button `aria-label`s such as `从夜一开始播放`.

- [ ] **Step 4: Run the component test to verify it passes**

Run: `pnpm --dir apps/mobile-web test -- --run src/components/MobileLivePhaseBar.test.tsx`
Expected: PASS.

### Task 2: Mobile Live Page Integration

**Files:**
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`

- [ ] **Step 1: Write the failing page test**

Mock live events containing `phase_started` night/day events. Verify the mobile live page renders `夜一` and `昼一`, and clicking `昼一` marks it as the current step.

- [ ] **Step 2: Run the page test to verify it fails**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx`
Expected: FAIL because `LivePage` does not render the phase bar.

- [ ] **Step 3: Wire shared phase segments into the page**

Import `buildLivePhaseSegments`, compute segments from the full `events` list and `director.currentEventId`, pass them into `LiveTheater`, and call `director.seekToEventId(segment.startEventId)` on selection.

- [ ] **Step 4: Run the page test to verify it passes**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx`
Expected: PASS.

### Task 3: Verification

**Files:**
- All changed mobile files.

- [ ] **Step 1: Run mobile tests**

Run: `pnpm test:mobile`
Expected: PASS.

- [ ] **Step 2: Run mobile build**

Run: `pnpm build:mobile`
Expected: PASS.

- [ ] **Step 3: Run mobile lint**

Run: `pnpm lint:mobile`
Expected: PASS.

- [ ] **Step 4: Inspect diff**

Run: `git diff --check && git status --short`
Expected: no whitespace errors; only expected mobile phase bar files changed.
