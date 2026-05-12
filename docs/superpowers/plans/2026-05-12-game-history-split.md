# Game History Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the lobby session list to a dedicated game history page and add a top-nav entry.

**Architecture:** Keep `/games` as the create-run lobby. Add `/games/history` as the list/resume surface, reusing `SessionList` and the existing games query/mutation flow. Extend `AppTopNav` so history navigation is available consistently.

**Tech Stack:** React 19, React Router 7, TanStack Query 5, Vitest, Testing Library.

---

### Task 1: Add Failing Coverage

**Files:**
- Modify: `apps/web/src/pages/GamesPage.test.tsx`
- Create: `apps/web/src/pages/GameHistoryPage.test.tsx`
- Modify: `apps/web/src/tests/app.test.tsx`

- [ ] **Step 1: Update lobby expectations**

Assert `/games` still renders the create form and top nav, exposes the `对局历史` nav link, and no longer renders `games-sessions-module`.

- [ ] **Step 2: Add history page tests**

Cover list rendering, empty state, error state, refresh action, and resume navigation on `/games/history`.

- [ ] **Step 3: Add route test**

Assert `/games/history` routes to the new history page.

- [ ] **Step 4: Run tests to verify RED**

Run: `pnpm --filter web test -- --run src/pages/GamesPage.test.tsx src/pages/GameHistoryPage.test.tsx src/tests/app.test.tsx`

Expected: fail because `GameHistoryPage` and `/games/history` do not exist and the lobby still renders history.

### Task 2: Split Pages

**Files:**
- Modify: `apps/web/src/pages/GamesPage.tsx`
- Modify: `apps/web/src/pages/components/GamesWorkspace.tsx`
- Create: `apps/web/src/pages/GameHistoryPage.tsx`
- Modify: `apps/web/src/routes/definitions.tsx`

- [ ] **Step 1: Make lobby create-only**

Remove the games query, resume mutation, list refresh action, and list props from `GamesPage` and `GamesWorkspace`.

- [ ] **Step 2: Add `GameHistoryPage`**

Move the existing query/mutation/list rendering flow into the new page. Keep refresh, resume error, and navigation to `/games/live/:runId`.

- [ ] **Step 3: Register route**

Add `/games/history` before `/games/:sessionId` so history is not captured as a session id.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `pnpm --filter web test -- --run src/pages/GamesPage.test.tsx src/pages/GameHistoryPage.test.tsx src/tests/app.test.tsx`

Expected: pass.

### Task 3: Navigation Polish

**Files:**
- Modify: `apps/web/src/app/AppTopNav.tsx`
- Update: tests from Task 1

- [ ] **Step 1: Add top-nav history link**

Add an optional `showHistoryLink` prop defaulting to true. Render a `对局历史` link to `/games/history`; hide it when already on the history page if the page passes `showHistoryLink={false}`.

- [ ] **Step 2: Verify full frontend checks**

Run: `pnpm --filter web test -- --run`

Expected: pass.

Run: `pnpm --filter web build`

Expected: pass.
