# Reliability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore green CI, make game resume idempotent per active session, and use PostgreSQL as the only runtime source for virtual player profiles.

**Architecture:** Keep live-run ownership inside `LiveRunRegistry`, adding one atomic get-or-create operation keyed by session. Remove file-store dependencies from HTTP routes and translate recoverable SQLAlchemy failures to stable `503` responses. Retain the JSON parser only behind an explicit, idempotent CLI import command.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest, Ruff, argparse.

---

### Task 1: Restore API lint

**Files:**
- Modify: `apps/api/tests/test_werewolf_runner.py`

- [ ] Remove premature `del model, temperature` statements from provider methods whose fallback branches pass those values to `super().complete_json()`.
- [ ] Run `cd apps/api && .venv/bin/ruff check tests/test_werewolf_runner.py` and confirm zero errors.
- [ ] Run the affected concurrency tests and confirm they pass.

### Task 2: Make resume idempotent

**Files:**
- Modify: `apps/api/app/werewolf/live.py`
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_live.py`
- Test: `apps/api/tests/test_games_api.py`

- [ ] Add failing registry tests proving atomic get-or-create returns one active run for the same session and creates a new run after terminal status.
- [ ] Add a failing API test proving repeated resume requests return the same run and start one background task.
- [ ] Implement `LiveRunRegistry.get_or_create_active_run()` under its existing lock and use it in the resume route.
- [ ] Return `201` for a newly created resume and `200` for an existing active resume without starting another thread.
- [ ] Run focused registry and games API tests.

### Task 3: Enforce PostgreSQL runtime ownership

**Files:**
- Modify: `apps/api/app/api/routes/player_profiles.py`
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_player_profiles_api.py`
- Test: `apps/api/tests/test_games_api.py`

- [ ] Replace fallback tests with failing tests that expect stable `503` responses when profile database operations fail.
- [ ] Remove `PlayerProfileFileStore` dependencies and branches from HTTP routes.
- [ ] Translate `OperationalError` and `ProgrammingError` to `HTTPException(503, "Player profile database unavailable")` after rolling back writes.
- [ ] Preserve existing `404`, `422`, and successful CRUD behavior.
- [ ] Run focused profile and games API tests.

### Task 4: Add legacy JSON import CLI

**Files:**
- Create: `apps/api/app/player_profile_import.py`
- Modify: `apps/api/app/cli.py`
- Test: `apps/api/tests/test_werewolf_cli.py`
- Modify: `README.md`

- [ ] Add failing CLI tests for successful import, duplicate-ID skipping, malformed/empty input, and database rollback.
- [ ] Implement a focused import service that reads profiles through `PlayerProfileFileStore`, inserts missing IDs in one transaction, and returns read/imported/skipped counts.
- [ ] Add `import-player-profiles --source PATH` to argparse with stable stdout/stderr and nonzero failure status.
- [ ] Document PostgreSQL as required for player profiles, the `503` behavior, and the one-time import command.
- [ ] Run CLI tests and Ruff.

### Task 5: Full verification

- [ ] Run `make lint`.
- [ ] Run `make test`.
- [ ] Run `cd apps/web && pnpm build`.
- [ ] Run `git diff --check` and inspect the final diff against the approved design.
