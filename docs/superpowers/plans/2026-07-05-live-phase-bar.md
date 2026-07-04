# Live Phase Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clickable `夜一 -> 昼一 -> 夜二 -> 昼二` phase bar to live spectating and playback pages.

**Architecture:** Build phase segments from the existing `LiveGameEvent[]` stream, expose a director seek API, and render a shared React phase bar above the current god-view stage layout. Playback and live pages both compute segments from their full event list while the stage continues to derive visible state from events truncated by `currentEventId`.

**Tech Stack:** TypeScript, React, Vitest, Testing Library, Vite, pnpm workspace packages.

---

### Task 1: Phase Segment Extraction

**Files:**
- Create: `packages/game-client/src/live/livePhaseBar.ts`
- Create: `packages/game-client/src/live/livePhaseBar.test.ts`
- Modify: `packages/game-client/src/live/index.ts`

- [ ] **Step 1: Write the failing test**

Create `packages/game-client/src/live/livePhaseBar.test.ts` with tests for generating `夜一/昼一/夜二/昼二`, ignoring `vote` and `summary`, deduplicating repeated phase starts, and computing current/visited states from `currentEventId`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir packages/game-client test -- --run src/live/livePhaseBar.test.ts`
Expected: FAIL because `./livePhaseBar` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `livePhaseBar.ts` with `LivePhaseKind`, `LivePhaseSegment`, and `buildLivePhaseSegments(events, currentEventId)`. Export it from `src/live/index.ts`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --dir packages/game-client test -- --run src/live/livePhaseBar.test.ts`
Expected: PASS.

### Task 2: Director Seek API

**Files:**
- Modify: `packages/game-client/src/live/liveDirector.ts`
- Modify: `packages/game-client/src/live/liveDirector.test.ts`
- Modify: `apps/web/src/features/games/hooks/useLiveDirector.ts`

- [ ] **Step 1: Write the failing tests**

Add tests that mount the hook or exercise a small test component to verify `seekToEventId` jumps to a target event, clamps before/after available cues, and preserves pause state.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --dir packages/game-client test -- --run src/live/liveDirector.test.ts`
Expected: FAIL because `seekToEventId` is not returned.

- [ ] **Step 3: Add the seek API**

Add `seekToEventId(eventId: number)` to the shared director hook and mirror the same change in the web wrapper hook. Implement it through the existing `moveToIndex` helper so timing refs reset consistently.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir packages/game-client test -- --run src/live/liveDirector.test.ts`
Expected: PASS.

### Task 3: Phase Bar Component

**Files:**
- Create: `apps/web/src/features/games/components/LivePhaseBar.tsx`
- Create: `apps/web/src/features/games/components/LivePhaseBar.test.tsx`
- Modify: `apps/web/src/styles/index.css`

- [ ] **Step 1: Write the failing component tests**

Test that the component renders phase buttons, marks the current phase with `aria-current="step"`, calls `onSelectPhase` with the selected segment, and renders nothing for an empty segment list.

- [ ] **Step 2: Run component test to verify it fails**

Run: `pnpm --dir apps/web test -- --run src/features/games/components/LivePhaseBar.test.tsx`
Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement component and styles**

Create an accessible horizontal button row with stable dimensions, dark stage styling, current/visited classes, and horizontal overflow support.

- [ ] **Step 4: Run component test to verify it passes**

Run: `pnpm --dir apps/web test -- --run src/features/games/components/LivePhaseBar.test.tsx`
Expected: PASS.

### Task 4: Page Integration

**Files:**
- Modify: `apps/web/src/pages/GamePlaybackPage.tsx`
- Modify: `apps/web/src/pages/GamePlaybackPage.test.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`
- Modify: `apps/web/src/features/games/components/LiveStageExperience.tsx`

- [ ] **Step 1: Write failing page tests**

For playback, test that full event lists render complete phase bars and clicking `昼一` updates the current step. For live, test that SSE phase events append `夜一` then `昼一`, and clicking a shown phase rewinds the director.

- [ ] **Step 2: Run page tests to verify they fail**

Run: `pnpm --dir apps/web test -- --run src/pages/GamePlaybackPage.test.tsx src/pages/LiveGamePage.test.tsx`
Expected: FAIL because pages do not render the phase bar.

- [ ] **Step 3: Wire pages and stage experience**

Compute `phaseSegments` from the full event list in each page, pass `phaseSegments` and `onSelectPhase` into `LiveStageExperience`, and render `LivePhaseBar` above `LiveStageModule`.

- [ ] **Step 4: Run page tests to verify they pass**

Run: `pnpm --dir apps/web test -- --run src/pages/GamePlaybackPage.test.tsx src/pages/LiveGamePage.test.tsx`
Expected: PASS.

### Task 5: Final Verification

**Files:**
- All changed files.

- [ ] **Step 1: Run shared package tests**

Run: `pnpm test:game-client`
Expected: PASS.

- [ ] **Step 2: Run web tests**

Run: `pnpm test:web`
Expected: PASS.

- [ ] **Step 3: Run web build**

Run: `pnpm build:web`
Expected: PASS.

- [ ] **Step 4: Inspect diff**

Run: `git diff --check && git status --short`
Expected: no whitespace errors; only expected feature/docs files changed.
