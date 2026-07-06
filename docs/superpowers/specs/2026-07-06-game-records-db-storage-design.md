# Game Records Database Storage Design

## Goal

Move persisted game records from `apps/api/logs/game_*/*.json` files into PostgreSQL for newly created games only. Existing file-backed game records are not migrated and will be deleted as part of the rollout. Runtime API behavior should stay stable for the web and mobile clients.

## Scope

In scope:

- Persist new completed and failed game sessions in PostgreSQL.
- Persist resume checkpoints in PostgreSQL.
- Serve game history, game details, playback, and resume reads from PostgreSQL only.
- Stop writing `game_complete.json`, `game_partial.json`, `game_logs.json`, and `resume_checkpoint.json` for game records.
- Provide a safe cleanup path that deletes only legacy `game_*` directories under the configured logs directory.
- Update tests and docs to describe database-backed game records.

Out of scope:

- Importing existing `apps/api/logs/game_*` history into PostgreSQL.
- Keeping a file fallback for missing database rows.
- Normalizing replay rounds, votes, and action logs into many relational tables.
- Moving player profile storage, player avatar asset storage, or active live SSE event history.

## Current State

Game records are written by `app.werewolf.logging.save_game` into a per-session directory under `settings.werewolf_logs_dir`. `run_game` and `resume_game` pass that directory through to file save and checkpoint code. `ReplayStore` lists and loads sessions by scanning `game_*` directories and reading `game_complete.json`, `game_partial.json`, `game_logs.json`, and `resume_checkpoint.json`.

The FastAPI routes in `app.api.routes.games` depend on `ReplayStore` for `GET /api/v1/games`, `GET /api/v1/games/{session_id}`, `GET /api/v1/games/{session_id}/playback`, and resume checkpoint lookup. Active live runs and SSE event history already live in the process-local `LiveRunRegistry` and remain unchanged.

## Recommended Architecture

Use database-backed JSON snapshots with relational metadata:

- `game_sessions` stores list-page metadata and lifecycle status.
- `game_replay_payloads` stores the full state, logs, and current resume checkpoint JSON for each session.

This keeps the API contract close to the current file-backed payloads while making list queries cheap and explicit. It avoids over-normalizing replay internals before the product needs cross-game analytical queries.

## Database Model

Create SQLAlchemy models in `apps/api/app/models/game_session.py`.

`game_sessions`:

- `session_id`: `String(32)`, primary key. Current format remains `game_[0-9a-f]{8}`.
- `status`: `String(20)`, not null. Allowed values in application code: `complete`, `partial`.
- `winner`: `String(80)`, nullable.
- `round_count`: integer, not null, default `0`.
- `rule_set`: JSON, nullable.
- `resumable`: boolean, not null, default `False`.
- `created_at`: timezone datetime, not null, server default `now()`.
- `updated_at`: timezone datetime, not null, server default `now()`, updates on write.

Indexes:

- `ix_game_sessions_updated_at` on `updated_at`.
- `ix_game_sessions_status` on `status`.

`game_replay_payloads`:

- `session_id`: `String(32)`, primary key and foreign key to `game_sessions.session_id` with cascade delete.
- `state`: JSON, not null.
- `logs`: JSON, not null, default empty list.
- `checkpoint`: JSON, nullable.

PostgreSQL will store these JSON columns as JSON/JSONB through SQLAlchemy. Tests can continue using SQLite where needed because the existing model layer already uses SQLAlchemy JSON columns.

## Store Interface

Replace the file-only `ReplayStore` with a database-backed store that preserves the route-facing methods:

- `list_sessions() -> list[dict]`
- `load_session(session_id: str) -> dict`
- `load_resume_checkpoint(session_id: str) -> dict`
- `save_game(state: GameState, logs: list[RoundLog]) -> None`
- `save_resume_checkpoint(session_id: str, checkpoint: dict) -> None`
- `clear_resume_checkpoint(session_id: str) -> None`

The store will validate session IDs with the existing `SESSION_ID_RE`. `load_session` returns the same dictionary shape currently used by the routes:

```python
{
    "session_id": session_id,
    "status": "complete" | "partial",
    "state": state_dict,
    "logs": logs_list,
    "resumable": bool,
}
```

`list_sessions` returns the current list shape:

```python
{
    "session_id": session_id,
    "status": status,
    "winner": winner,
    "round_count": round_count,
    "created_at": created_at_iso,
    "rule_set": rule_set,
    "resumable": resumable,
}
```

## Write Flow

`run_game` and `resume_game` should accept a persistence dependency instead of a file logs directory for game records. The minimal implementation can introduce a `GameRecordStore` protocol and default to a database store in API code. Tests and CLI can pass an explicit store.

On round start, the checkpoint manager stores a checkpoint row update:

- Create or update `game_sessions` with `status="partial"` and `resumable=True`.
- Store `state_at_round_start`, `logs_before_round`, and checkpoint fields in `game_replay_payloads.checkpoint`.
- Store partial `state` and `logs` too, so history/detail endpoints work before resume.

On model success or failure, update only `checkpoint`.

On game completion:

- Upsert `game_sessions` with `status="complete"`, `winner`, `round_count`, `rule_set`, and `resumable=False`.
- Upsert `game_replay_payloads.state` and `logs`.
- Clear `checkpoint`.

On game failure:

- Upsert `game_sessions` with `status="partial"`, `winner=None`, `round_count`, `rule_set`, and `resumable=True` when a checkpoint exists.
- Upsert `game_replay_payloads.state`, `logs`, and the latest checkpoint.

## Read Flow

`GET /api/v1/games` uses `DatabaseReplayStore.list_sessions`.

`GET /api/v1/games/{session_id}` uses `DatabaseReplayStore.load_session`.

`GET /api/v1/games/{session_id}/playback` continues to call `build_replay_playback(store.load_session(session_id))`.

`POST /api/v1/games/{session_id}/resume` reads `checkpoint` from the database. It does not read `resume_checkpoint.json`.

## CLI And Cleanup

The `run-game` CLI should write to PostgreSQL by default, matching API behavior. The old `--logs-dir` argument becomes unnecessary for game records and should be removed or ignored with a clear help text update. Existing CLI replay evaluation can remain file-based because it evaluates an explicitly supplied JSON file.

Add a cleanup command:

```bash
cd apps/api
.venv/bin/python -m app.cli purge-legacy-game-records --logs-dir logs --yes
```

The command deletes only direct child directories matching `game_[0-9a-f]{8}` under the selected logs directory. It must skip symlinks and must not delete `player_profiles.json`, `player_profile_assets`, avatar files, or any non-matching directory. Without `--yes`, it prints the number of matching directories and exits without deleting.

## Tests

API tests should override `get_replay_store` with a database-backed test store using the existing in-memory SQLite setup or test transaction session.

Required coverage:

- Creating a completed game writes `game_sessions` and `game_replay_payloads`.
- Failed games write partial state, logs, and checkpoint in the database.
- Game list, detail, and playback endpoints read only database records.
- Resume endpoint reads checkpoint from the database and resumes idempotently for active runs.
- Missing database rows return the existing `404` responses.
- Legacy file directories are ignored by API reads.
- Cleanup command deletes matching `game_*` directories and leaves non-game files and symlinks untouched.
- `run_game` no longer creates `game_complete.json`, `game_partial.json`, `game_logs.json`, or `resume_checkpoint.json`.

## Rollout

1. Run Alembic migration to create the tables.
2. Deploy database-backed store and runner writes.
3. Verify new games appear in history and playback from database rows.
4. Run the cleanup command with `--yes` to delete old file-backed game records.
5. Keep `WEREWOLF_LOGS_DIR` for non-game assets that still use it.

## Risks And Decisions

- Existing historical games disappear because they are intentionally not migrated.
- If PostgreSQL is unavailable, game history and new game persistence should fail explicitly instead of silently writing files.
- Active live SSE event history remains in memory, so this change does not make live run event streams multi-worker safe.
- JSON snapshots are chosen over normalized replay tables to minimize API and frontend churn.
