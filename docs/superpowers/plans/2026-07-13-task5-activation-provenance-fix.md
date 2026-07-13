# Task 5 Activation Provenance Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make activation reject every rule identity, snapshot, or SQL-NULL provenance change that occurs after lease acquisition and before the locked activation transition.

**Architecture:** Capture one detached `RunRuleSetExpectedState` from the post-lease activation source and carry it through the registry, LiveStore protocol, session wrapper, and database store. After locking the run and complete ordered event stream, reuse the exact locked rule matcher before any activation mutation; canonicalize only when that captured expectation records true SQL NULL provenance.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, SQLite, PostgreSQL 17, Ruff.

## Global Constraints

- Keep all otherwise-reviewed Task 5 behavior frozen.
- Preserve run-to-events lock order, exact event validation, ACK recovery, positive fences, JSON-null rejection, and ordinary Task 3 semantics.
- Do not edit `.superpowers/sdd/progress.md`.
- Append `.superpowers/sdd/p2-task-5-report.md` and create a separate commit without amending reviewed history.

---

### Task 1: Activation Race Regressions

**Files:**
- Test: `apps/api/tests/test_live_store.py`

**Interfaces:**
- Consumes: `SessionLiveStore.activate_run()` and `LiveRunRegistry.mark_running()`.
- Produces: deterministic RED coverage for post-lease rule races.

- [x] **Step 1: Add the provenance and full-rule race matrix**

  Add a `SessionLiveStore` seam that mutates the persisted row immediately before forwarding `activate_run()`. Cover JSON `{}` to SQL NULL, historical SQL NULL to JSON `{}`, and a managed rule identity/hash/snapshot mutation. Assert `RunRuleSetMismatch`, unchanged local queued state, no activation cache entry, no subscriber notification, no `run_started`, and the raced database value remains uncanonicalized.

- [x] **Step 2: Verify RED**

  Run:

  ```bash
  cd apps/api
  .venv/bin/pytest -q tests/test_live_store.py -k 'activation_rejects_rule_race_after_lease'
  ```

  Expected: all race cases fail because current activation either canonicalizes SQL NULL or accepts non-null rule changes without exact comparison.

---

### Task 2: Exact Locked Activation Expectation

**Files:**
- Modify: `apps/api/app/werewolf/live.py`
- Modify: `apps/api/app/werewolf/live_store.py`
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_live_store.py`

**Interfaces:**
- Consumes: `RunRuleSetExpectedState`, `clone_rule_set_expected_state()`, and `DatabaseLiveStore._locked_rule_set_matches()`.
- Produces: `activate_run(..., expected_rule_set: RunRuleSetExpectedState, ...)` across every in-repo boundary.

- [x] **Step 1: Carry one detached post-lease expectation**

  In `mark_running()`, derive the expectation with `_rule_set_expected_state_from_source(source)` after lease application. Pass it through `_persist_activation_locked()`, `LiveStore.activate_run()`, and `SessionLiveStore.activate_run()`. Clone and strictly validate it at the database boundary before any lock wait.

- [x] **Step 2: Enforce the expectation inside the activation transaction**

  After the run row and complete event stream are locked, call `_locked_rule_set_matches(record, expected_rule_set)` and raise `RunRuleSetMismatch` before status, timestamp, rule, or event mutation on mismatch. Let provenance-query errors propagate.

- [x] **Step 3: Restrict legacy canonicalization**

  Remove empty-dictionary-derived authorization. Canonicalize `record.rule_set` from SQL NULL to JSON `{}` only when `expected_rule_set.rule_set_was_sql_null is True` and the exact locked expectation already matched.

- [x] **Step 4: Verify GREEN and historical behavior**

  Run:

  ```bash
  cd apps/api
  .venv/bin/pytest -q tests/test_live_store.py -k 'activation_rejects_rule_race_after_lease or legacy_null_rule_snapshot_activation_ack_canonicalizes_atomically or json_null_rule_snapshot_is_not_canonicalized'
  ```

  Expected: race cases reject; historical normal and ACK-loss SQL-NULL activation canonicalize to durable/local JSON `{}` with false local provenance; JSON null remains rejected.

---

### Task 3: Boundary Hardening and Review

**Files:**
- Test: `apps/api/tests/test_live_store.py`

**Interfaces:**
- Consumes: direct `DatabaseLiveStore.activate_run()` API.
- Produces: detached/type-strict store expectation and propagation-error coverage.

- [x] **Step 1: Add direct-store tests**

  Verify the database store snapshots the supplied rule expectation before waiting for locks, rejects malformed provenance types before locking, and propagates SQL-NULL provenance-query exceptions without compatibility fallback.

- [x] **Step 2: Run focused Task 3 and Task 5 suites**

  ```bash
  cd apps/api
  .venv/bin/pytest -q tests/test_werewolf_resume.py tests/test_game_record_store.py tests/test_orphan_reaper.py tests/test_games_api.py tests/test_live.py tests/test_live_store.py
  ```

- [x] **Step 3: Perform read-only self-review**

  Confirm every `activate_run` implementation/double forwards the exact expectation, the matcher runs after run-to-events locks and before mutations, and no broad exception handler masks provenance-query failures.

---

### Task 4: Final Verification, Report, and Commit

**Files:**
- Append: `.superpowers/sdd/p2-task-5-report.md`

**Interfaces:**
- Consumes: the reviewed implementation and regressions.
- Produces: final verification evidence and one separate commit.

- [x] **Step 1: Run full local and fresh PostgreSQL suites**

  Run the full API suite without PostgreSQL, then with explicit `DATABASE_URL` and `TEST_POSTGRESQL_URL` against a fresh PostgreSQL 17 container. All local tests must pass with only PostgreSQL-gated skips; all PostgreSQL tests must execute without skips.

- [x] **Step 2: Run static verification**

  Run Ruff lint and format checks on every changed Python file, followed by:

  ```bash
  git diff --check d387ac79d5d0757f134a9a5f351533a4d9b7ce50
  ```

- [x] **Step 3: Append the Task 5 report**

  Record RED/GREEN evidence for all three activation races, historical canonicalization, focused/full/PostgreSQL counts, and the final self-review. Confirm the progress ledger is untouched.

- [x] **Step 4: Commit separately**

  Stage only the authorized implementation, tests, and this plan, then create a new commit without amending `d387ac79`.
