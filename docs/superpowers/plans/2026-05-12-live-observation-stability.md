# Live Observation Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live game observation page more resilient during reconnects, malformed stream messages, and route-state changes.

**Architecture:** Keep the existing in-memory `LiveRunRegistry` and browser `EventSource` shape. Add `after_id` and browser-native `Last-Event-ID` resume support to the SSE endpoint, keep frontend event parsing defensive, and move live-page run bookkeeping out of render into effects.

**Tech Stack:** FastAPI, Python 3.12, React 19, TanStack Query 5, Vitest, Testing Library.

---

### Task 1: Backend SSE Resume Cursor

**Files:**
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_games_api.py`

- [x] **Step 1: Write the failing API test**

Add tests that create a registry with four events, call `/api/v1/games/runs/{run_id}/events?after_id=2` and `/api/v1/games/runs/{run_id}/events` with `Last-Event-ID: 2`, and assert each stream starts at event id `3` rather than replaying ids `1` and `2`.

- [x] **Step 2: Run test to verify RED**

Run: `cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py::test_game_run_events_honors_after_id_query tests/test_games_api.py::test_game_run_events_honors_last_event_id_header -q`

Expected: fail because the route currently ignores both resume cursors.

- [x] **Step 3: Implement cursor support**

Add an optional FastAPI query parameter `after_id: int | None = None` and `Last-Event-ID` header to `stream_game_run_events`, pass the resolved cursor into `_event_stream`, and have `_event_stream` seed `last_event_id` from that cursor while replaying `registry.events_after(run_id, after_id=after_id)`.

- [x] **Step 4: Run test to verify GREEN**

Run: `cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py::test_game_run_events_honors_after_id_query tests/test_games_api.py::test_game_run_events_honors_last_event_id_header -q`

Expected: pass.

### Task 2: Frontend Stream Parse Safety

**Files:**
- Modify: `apps/web/src/features/games/hooks/useGameRunEvents.ts`
- Test: `apps/web/src/features/games/hooks/useGameRunEvents.test.tsx`

- [x] **Step 1: Write failing hook tests**

Add a test that emits invalid JSON and expects the hook to keep prior events while moving to `error`.

- [x] **Step 2: Run tests to verify RED**

Run: `cd apps/web && pnpm test -- --run src/features/games/hooks/useGameRunEvents.test.tsx`

Expected: fail because the hook parses without a guard.

- [x] **Step 3: Implement minimal hook changes**

Wrap `JSON.parse` in `try/catch`; on parse failure keep events unchanged and set `connectionState` to `error`.

- [x] **Step 4: Run tests to verify GREEN**

Run: `cd apps/web && pnpm test -- --run src/features/games/hooks/useGameRunEvents.test.tsx`

Expected: pass.

### Task 3: Live Page Regression Guard

**Files:**
- Test: `apps/web/src/pages/LiveGamePage.test.tsx`

- [x] **Step 1: Add live page coverage**

Extend the existing route-switching test that navigates between two terminal/running live runs and asserts React does not warn about component updates during render.

- [x] **Step 2: Check current coverage**

Run: `cd apps/web && pnpm test -- --run src/pages/LiveGamePage.test.tsx`

Expected: existing behavior remains covered; ESLint does not flag the guarded render-time state write, so this step is treated as a safe refactor under existing route-switching coverage.

- [x] **Step 3: Evaluate implementation options**

Tried moving the bookkeeping into an effect and then a ref-backed memo. The React hooks lint rules reject those alternatives (`set-state-in-effect` and `refs`), while the existing guarded render-time state adjustment is accepted. Keep the production logic unchanged and retain the route-switching regression guard.

- [ ] **Step 4: Run focused and broad checks**

Run: `cd apps/web && pnpm test -- --run src/pages/LiveGamePage.test.tsx src/features/games/hooks/useGameRunEvents.test.tsx`

Run: `cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py::test_stream_game_run_events_honors_after_id tests/test_live.py -q`

Expected: pass.

Run: `cd apps/web && pnpm build`

Expected: pass.
