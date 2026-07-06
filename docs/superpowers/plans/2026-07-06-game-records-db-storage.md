# Game Records Database Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist newly created Werewolf game records, replay payloads, and resume checkpoints in PostgreSQL, remove file-backed game record usage, and provide a safe cleanup command for old `game_*` directories.

**Architecture:** Add database tables for game session metadata and replay JSON payloads, then replace the file-backed replay store with a SQLAlchemy store. `run_game`, `resume_game`, API routes, and CLI commands will receive an explicit database-backed record store; active live SSE state remains in `LiveRunRegistry`.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, PostgreSQL JSON columns, SQLite-backed pytest suites, existing `uv` and `pytest` workflows.

---

## File Structure

- Create `apps/api/app/models/game_session.py`: SQLAlchemy models for `game_sessions` and `game_replay_payloads`.
- Modify `apps/api/app/models/__init__.py`: import and export the new models so Alembic sees them.
- Create `apps/api/alembic/versions/20260706_01_create_game_record_tables.py`: database migration for the two tables and indexes.
- Replace `apps/api/app/werewolf/replay.py`: keep `SESSION_ID_RE` and `ReplayNotFoundError`, add `GameRecordStore` protocol and `DatabaseReplayStore`.
- Modify `apps/api/app/werewolf/checkpoint.py`: make `ResumeCheckpointManager` write checkpoints through `GameRecordStore` instead of `resume_checkpoint.json`.
- Modify `apps/api/app/werewolf/runner.py`: require a `record_store`, remove `logs_dir` writes, and return a DB-only `RunGameResult`.
- Modify `apps/api/app/api/routes/games.py`: inject a database-backed replay store and open a fresh DB session inside background threads.
- Create `apps/api/app/legacy_game_record_cleanup.py`: safe purge helper for legacy `game_*` directories.
- Modify `apps/api/app/cli.py`: make `run-game` use PostgreSQL and add `purge-legacy-game-records`.
- Modify `apps/api/tests/test_models.py`: model metadata tests for the new tables.
- Create `apps/api/tests/test_game_record_store.py`: focused unit tests for `DatabaseReplayStore`.
- Modify `apps/api/tests/test_werewolf_runner.py`, `apps/api/tests/test_werewolf_resume.py`, `apps/api/tests/test_games_api.py`, and `apps/api/tests/test_werewolf_cli.py`: update file-backed assertions to database-backed assertions.
- Modify `README.md` and `docs/architecture.md`: describe DB-backed game records and cleanup.

---

### Task 1: Add Game Record Database Schema

**Files:**
- Create: `apps/api/app/models/game_session.py`
- Modify: `apps/api/app/models/__init__.py`
- Create: `apps/api/alembic/versions/20260706_01_create_game_record_tables.py`
- Test: `apps/api/tests/test_models.py`

- [ ] **Step 1: Write failing model metadata tests**

Append these tests to `apps/api/tests/test_models.py` and update the imports at the top to include `GameReplayPayload` and `GameSessionRecord`.

```python
from app.models.game_session import GameReplayPayload, GameSessionRecord
```

```python
def test_game_session_table_is_registered_in_metadata() -> None:
    assert GameSessionRecord.__table__.name == "game_sessions"
    assert "game_sessions" in Base.metadata.tables


def test_game_session_table_matches_expected_schema() -> None:
    table = GameSessionRecord.__table__
    column_names = set(table.columns.keys())

    assert column_names == {
        "session_id",
        "status",
        "winner",
        "round_count",
        "rule_set",
        "resumable",
        "created_at",
        "updated_at",
    }
    assert table.c.session_id.primary_key is True
    assert table.c.status.nullable is False
    assert table.c.round_count.nullable is False
    assert table.c.resumable.nullable is False
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None
    assert any(index.name == "ix_game_sessions_status" for index in table.indexes)
    assert any(index.name == "ix_game_sessions_updated_at" for index in table.indexes)


def test_game_replay_payload_table_matches_expected_schema() -> None:
    table = GameReplayPayload.__table__
    column_names = set(table.columns.keys())

    assert column_names == {"session_id", "state", "logs", "checkpoint"}
    assert table.c.session_id.primary_key is True
    assert table.c.session_id.foreign_keys
    foreign_key = next(iter(table.c.session_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"
    assert table.c.state.nullable is False
    assert table.c.logs.nullable is False
    assert table.c.checkpoint.nullable is True
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_models.py::test_game_session_table_is_registered_in_metadata tests/test_models.py::test_game_session_table_matches_expected_schema tests/test_models.py::test_game_replay_payload_table_matches_expected_schema -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.game_session'`.

- [ ] **Step 3: Create the SQLAlchemy models**

Create `apps/api/app/models/game_session.py` with this content:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GameSessionRecord(Base):
    __tablename__ = "game_sessions"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    winner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    round_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    rule_set: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resumable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )


class GameReplayPayload(Base):
    __tablename__ = "game_replay_payloads"

    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("game_sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    logs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
```

Modify `apps/api/app/models/__init__.py` so it imports and exports the new classes:

```python
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile

__all__ = [
    "GameReplayPayload",
    "GameSessionRecord",
    "PlayerAvatarAsset",
    "User",
    "VirtualPlayerProfile",
]
```

- [ ] **Step 4: Add the Alembic migration**

Create `apps/api/alembic/versions/20260706_01_create_game_record_tables.py` with this content:

```python
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260706_01"
down_revision = "20260704_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_sessions",
        sa.Column("session_id", sa.String(length=32), primary_key=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("winner", sa.String(length=80), nullable=True),
        sa.Column("round_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rule_set", sa.JSON(), nullable=True),
        sa.Column("resumable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_game_sessions_status", "game_sessions", ["status"])
    op.create_index("ix_game_sessions_updated_at", "game_sessions", ["updated_at"])
    op.create_table(
        "game_replay_payloads",
        sa.Column(
            "session_id",
            sa.String(length=32),
            sa.ForeignKey("game_sessions.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("logs", sa.JSON(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("game_replay_payloads")
    op.drop_index("ix_game_sessions_updated_at", table_name="game_sessions")
    op.drop_index("ix_game_sessions_status", table_name="game_sessions")
    op.drop_table("game_sessions")
```

- [ ] **Step 5: Run model tests and migration check**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_models.py -v
.venv/bin/python -m alembic upgrade head
```

Expected: tests PASS; Alembic reaches revision `20260706_01`.

- [ ] **Step 6: Commit schema changes**

Run:

```bash
git add apps/api/app/models/game_session.py apps/api/app/models/__init__.py apps/api/alembic/versions/20260706_01_create_game_record_tables.py apps/api/tests/test_models.py
git commit -m "feat(api): add game record database tables"
```

---

### Task 2: Implement DatabaseReplayStore

**Files:**
- Replace: `apps/api/app/werewolf/replay.py`
- Create: `apps/api/tests/test_game_record_store.py`

- [ ] **Step 1: Write focused store tests**

Create `apps/api/tests/test_game_record_store.py` with this content:

```python
from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.werewolf.checkpoint import CHECKPOINT_SCHEMA_VERSION, ResumeCheckpointError
from app.werewolf.replay import DatabaseReplayStore, ReplayNotFoundError


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as session:
        yield session


def sample_state(session_id: str, *, winner: str = "狼人阵营", error: str = "") -> dict:
    return {
        "session_id": session_id,
        "players": [{"name": "张三", "role": "狼人", "model": "deepseek-chat", "observations": []}],
        "rounds": [{"number": 1, "players": ["张三"], "debate": []}],
        "winner": winner,
        "error_message": error,
        "rule_set": {"id": "starter_6", "name": "新手 6 人快局"},
    }


def sample_logs() -> list[dict]:
    return [{"number": 1, "debate": [], "summaries": []}]


def test_save_complete_game_lists_and_loads_session(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)
    state = sample_state("game_1200abcd")

    store.save_game_payload(state=state, logs=sample_logs())

    sessions = store.list_sessions()
    loaded = store.load_session("game_1200abcd")

    assert sessions == [
        {
            "session_id": "game_1200abcd",
            "status": "complete",
            "winner": "狼人阵营",
            "round_count": 1,
            "created_at": sessions[0]["created_at"],
            "rule_set": {"id": "starter_6", "name": "新手 6 人快局"},
            "resumable": False,
        }
    ]
    assert sessions[0]["created_at"].endswith("Z")
    assert loaded["session_id"] == "game_1200abcd"
    assert loaded["status"] == "complete"
    assert loaded["state"]["winner"] == "狼人阵营"
    assert loaded["logs"] == sample_logs()
    assert loaded["resumable"] is False


def test_checkpoint_makes_partial_session_resumable(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)
    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "session_id": "game_1200abcd",
        "state_at_round_start": sample_state("game_1200abcd", winner="", error=""),
        "logs_before_round": sample_logs(),
        "run_params": {
            "villager_model": "deepseek-chat",
            "werewolf_model": "deepseek-chat",
            "seed": 7,
            "max_rounds": 8,
            "rule_set_id": "starter_6",
            "player_configs": [],
        },
        "round_number": 1,
        "active_players": ["张三"],
        "cached_model_responses": [],
        "failed_request": None,
        "last_error": None,
    }

    store.save_resume_checkpoint("game_1200abcd", checkpoint)
    loaded_checkpoint = store.load_resume_checkpoint("game_1200abcd")
    loaded_session = store.load_session("game_1200abcd")

    assert loaded_checkpoint["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert loaded_checkpoint["session_id"] == "game_1200abcd"
    assert loaded_session["status"] == "partial"
    assert loaded_session["resumable"] is True
    assert loaded_session["state"]["session_id"] == "game_1200abcd"
    assert loaded_session["logs"] == sample_logs()


def test_complete_game_clears_checkpoint(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)
    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "session_id": "game_1200abcd",
        "state_at_round_start": sample_state("game_1200abcd", winner="", error=""),
        "logs_before_round": [],
        "run_params": {},
        "cached_model_responses": [],
    }

    store.save_resume_checkpoint("game_1200abcd", checkpoint)
    store.save_game_payload(state=sample_state("game_1200abcd"), logs=sample_logs())

    loaded_session = store.load_session("game_1200abcd")
    assert loaded_session["status"] == "complete"
    assert loaded_session["resumable"] is False
    with pytest.raises(ResumeCheckpointError):
        store.load_resume_checkpoint("game_1200abcd")


def test_missing_and_invalid_sessions_raise_not_found(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)

    with pytest.raises(ReplayNotFoundError):
        store.load_session("game_1200abcd")
    with pytest.raises(ReplayNotFoundError):
        store.load_session("../bad")
    with pytest.raises(ResumeCheckpointError):
        store.load_resume_checkpoint("game_1200abcd")
```

- [ ] **Step 2: Run the store tests and verify they fail**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_game_record_store.py -v
```

Expected: FAIL with `ImportError` for `DatabaseReplayStore`.

- [ ] **Step 3: Replace `apps/api/app/werewolf/replay.py`**

Replace the file with this implementation:

```python
from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.werewolf.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    ResumeCheckpointError,
)
from app.werewolf.models import GameState, RoundLog

SESSION_ID_RE = r"^game_[0-9a-f]{8}$"
_SESSION_PATTERN = re.compile(SESSION_ID_RE)


class ReplayNotFoundError(Exception):
    """Raised when a replay session cannot be loaded."""


class GameRecordStore(Protocol):
    def list_sessions(self) -> list[dict[str, Any]]:
        ...

    def load_session(self, session_id: str) -> dict[str, Any]:
        ...

    def load_resume_checkpoint(self, session_id: str) -> dict[str, Any]:
        ...

    def save_game(self, state: GameState, logs: list[RoundLog]) -> None:
        ...

    def save_game_payload(self, *, state: dict[str, Any], logs: list[Any]) -> None:
        ...

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, Any]) -> None:
        ...

    def clear_resume_checkpoint(self, session_id: str) -> None:
        ...


class DatabaseReplayStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_sessions(self) -> list[dict[str, Any]]:
        records = (
            self.db.query(GameSessionRecord)
            .order_by(GameSessionRecord.created_at.desc(), GameSessionRecord.session_id.desc())
            .all()
        )
        return [
            {
                "session_id": record.session_id,
                "status": record.status,
                "winner": record.winner,
                "round_count": record.round_count,
                "created_at": _format_datetime(record.created_at),
                "rule_set": copy.deepcopy(record.rule_set),
                "resumable": bool(record.resumable),
            }
            for record in records
        ]

    def load_session(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        record = self.db.get(GameSessionRecord, session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if record is None or payload is None:
            raise ReplayNotFoundError
        state = _dict_payload(payload.state)
        logs = _list_payload(payload.logs)
        return {
            "session_id": session_id,
            "status": record.status,
            "state": copy.deepcopy(state),
            "logs": copy.deepcopy(logs),
            "resumable": bool(record.resumable),
        }

    def load_resume_checkpoint(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if payload is None or not isinstance(payload.checkpoint, dict):
            raise ResumeCheckpointError
        checkpoint = copy.deepcopy(payload.checkpoint)
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ResumeCheckpointError
        return checkpoint

    def save_game(self, state: GameState, logs: list[RoundLog]) -> None:
        self.save_game_payload(
            state=state.to_dict(),
            logs=[log.to_dict() for log in logs],
        )

    def save_game_payload(self, *, state: dict[str, Any], logs: list[Any]) -> None:
        session_id = str(state.get("session_id") or "")
        self._validate_session_id(session_id)
        status = "partial" if state.get("error_message") else "complete"
        existing_payload = self.db.get(GameReplayPayload, session_id)
        checkpoint = existing_payload.checkpoint if existing_payload is not None else None
        resumable = status == "partial" and isinstance(checkpoint, dict)
        record = self._get_or_create_record(session_id)
        record.status = status
        record.winner = str(state.get("winner") or "") or None
        record.round_count = len(_list_payload(state.get("rounds", [])))
        record.rule_set = copy.deepcopy(state.get("rule_set"))
        record.resumable = resumable

        payload = self._get_or_create_payload(session_id)
        payload.state = copy.deepcopy(state)
        payload.logs = copy.deepcopy(logs)
        if status == "complete":
            payload.checkpoint = None
            record.resumable = False
        self.db.commit()

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, Any]) -> None:
        self._validate_session_id(session_id)
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ResumeCheckpointError
        state = _dict_payload(checkpoint.get("state_at_round_start"))
        logs = _list_payload(checkpoint.get("logs_before_round", []))
        record = self._get_or_create_record(session_id)
        record.status = "partial"
        record.winner = str(state.get("winner") or "") or None
        record.round_count = len(_list_payload(state.get("rounds", [])))
        record.rule_set = copy.deepcopy(state.get("rule_set"))
        record.resumable = True

        payload = self._get_or_create_payload(session_id)
        payload.state = copy.deepcopy(state)
        payload.logs = copy.deepcopy(logs)
        payload.checkpoint = copy.deepcopy(checkpoint)
        self.db.commit()

    def clear_resume_checkpoint(self, session_id: str) -> None:
        self._validate_session_id(session_id)
        record = self.db.get(GameSessionRecord, session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if record is None or payload is None:
            return
        payload.checkpoint = None
        record.resumable = False
        self.db.commit()

    def _get_or_create_record(self, session_id: str) -> GameSessionRecord:
        record = self.db.get(GameSessionRecord, session_id)
        if record is None:
            record = GameSessionRecord(session_id=session_id, status="partial")
            self.db.add(record)
            self.db.flush()
        return record

    def _get_or_create_payload(self, session_id: str) -> GameReplayPayload:
        payload = self.db.get(GameReplayPayload, session_id)
        if payload is None:
            payload = GameReplayPayload(session_id=session_id, state={}, logs=[])
            self.db.add(payload)
            self.db.flush()
        return payload

    def _validate_session_id(self, session_id: str) -> None:
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise ReplayNotFoundError


def _dict_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayNotFoundError
    return value


def _list_payload(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ReplayNotFoundError
    return value


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4: Run store tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_game_record_store.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the database store**

Run:

```bash
git add apps/api/app/werewolf/replay.py apps/api/tests/test_game_record_store.py
git commit -m "feat(api): add database game record store"
```

---

### Task 3: Persist Checkpoints Through the Store

**Files:**
- Modify: `apps/api/app/werewolf/checkpoint.py`
- Test: `apps/api/tests/test_werewolf_resume.py`

- [ ] **Step 1: Write failing checkpoint-manager test**

Add this helper and test to `apps/api/tests/test_werewolf_resume.py`.

```python
class RecordingRecordStore:
    def __init__(self) -> None:
        self.checkpoints: list[dict[str, object]] = []

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, object]) -> None:
        self.checkpoints.append({"session_id": session_id, "checkpoint": checkpoint.copy()})
```

```python
def test_resume_checkpoint_manager_persists_checkpoint_to_record_store() -> None:
    store = RecordingRecordStore()
    manager = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        run_params={"rule_set_id": "starter_6"},
    )
    state = initialize_game_state(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )

    manager.start_round(
        state=state,
        logs=[],
        round_number=1,
        active_players=["1号玩家"],
        rng_state=None,
    )
    manager.record_failure(
        actor="1号玩家",
        action="speech",
        phase="day",
        model="deepseek-chat",
        error="model provider offline",
    )

    assert len(store.checkpoints) == 2
    latest = store.checkpoints[-1]
    assert latest["session_id"] == "game_1200abcd"
    checkpoint = latest["checkpoint"]
    assert checkpoint["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert checkpoint["session_id"] == "game_1200abcd"
    assert checkpoint["last_error"] == "model provider offline"
```

Also update imports in `apps/api/tests/test_werewolf_resume.py`:

```python
from app.werewolf.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    ReplayThenLiveProvider,
    ResumeCheckpointManager,
    ResumeCheckpointError,
)
from app.werewolf.engine import initialize_game_state
from app.werewolf.rules import get_rule_set
```

- [ ] **Step 2: Run the new checkpoint-manager test and verify it fails**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_resume.py::test_resume_checkpoint_manager_persists_checkpoint_to_record_store -v
```

Expected: FAIL with `TypeError: ResumeCheckpointManager.__init__() got an unexpected keyword argument 'record_store'`.

- [ ] **Step 3: Modify `ResumeCheckpointManager`**

In `apps/api/app/werewolf/checkpoint.py`, remove `Path` usage from `ResumeCheckpointManager.__init__` and replace the class constructor and `_save` method with:

```python
    def __init__(
        self,
        *,
        record_store: object,
        session_id: str,
        run_params: dict[str, Any],
    ) -> None:
        self.record_store = record_store
        self.session_id = session_id
        self.run_params = copy.deepcopy(run_params)
        self._checkpoint: dict[str, Any] | None = None
```

```python
    def _save(self) -> None:
        if self._checkpoint is None:
            return
        self.record_store.save_resume_checkpoint(self.session_id, self._checkpoint)
```

Keep `RESUME_CHECKPOINT_FILE`, `load_resume_checkpoint`, `has_resume_checkpoint`, and `clear_resume_checkpoint` for now so intermediate tests that still import them continue to load. They will stop being used by runner and API in later tasks.

- [ ] **Step 4: Run checkpoint tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_resume.py::test_resume_checkpoint_manager_persists_checkpoint_to_record_store tests/test_game_record_store.py::test_checkpoint_makes_partial_session_resumable -v
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint persistence**

Run:

```bash
git add apps/api/app/werewolf/checkpoint.py apps/api/tests/test_werewolf_resume.py
git commit -m "feat(api): persist resume checkpoints through record store"
```

---

### Task 4: Convert Runner To DB-Only Persistence

**Files:**
- Modify: `apps/api/app/werewolf/runner.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`
- Modify: `apps/api/tests/test_werewolf_resume.py`

- [ ] **Step 1: Add test database store fixtures**

In both `apps/api/tests/test_werewolf_runner.py` and `apps/api/tests/test_werewolf_resume.py`, add these imports:

```python
from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.werewolf.replay import DatabaseReplayStore
```

Add this fixture near the top of each file:

```python
@pytest.fixture
def record_store() -> Generator[DatabaseReplayStore, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as session:
        yield DatabaseReplayStore(session)
```

- [ ] **Step 2: Update representative runner tests before implementation**

Change `test_run_game_with_deepseek_models_writes_complete_chinese_logs` in `apps/api/tests/test_werewolf_runner.py` to accept `record_store` and assert through the database:

```python
def test_run_game_with_deepseek_models_writes_complete_chinese_logs(
    record_store: DatabaseReplayStore,
) -> None:
    result = run_game(
        record_store=record_store,
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    replay = record_store.load_session(result.session_id)
    state = replay["state"]
    logs = replay["logs"]

    assert result.winner in {"好人阵营", "狼人阵营"}
    assert result.session_id.startswith("game_")
    assert replay["status"] == "complete"
    assert replay["resumable"] is False
    assert state["winner"] == result.winner
    assert len(state["players"]) == 8
    assert state["error_message"] == ""
    assert {player["role"] for player in state["players"]} == {"狼人", "预言家", "守卫", "村民"}
    assert any("第" in observation for player in state["players"] for observation in player["observations"])
    assert logs[0]["debate"]
    assert logs[0]["summaries"]
    assert "狼人杀" in logs[0]["debate"][0]["lm_log"]["prompt"]
    assert "我认为" in state["rounds"][0]["debate"][0]["message"]
```

Change `test_run_game_records_partial_log_when_max_rounds_is_exceeded`:

```python
def test_run_game_records_partial_state_when_max_rounds_is_exceeded(
    record_store: DatabaseReplayStore,
) -> None:
    with pytest.raises(GameRunError) as error:
        run_game(record_store=record_store, seed=3, max_rounds=0, provider=ScriptedChineseProvider())

    assert error.value.session_id is not None
    replay = record_store.load_session(error.value.session_id)
    assert replay["status"] == "partial"
    assert "Maximum rounds exceeded" in replay["state"]["error_message"]
```

Change `test_run_game_accepts_custom_session_id`:

```python
def test_run_game_accepts_custom_session_id(record_store: DatabaseReplayStore) -> None:
    result = run_game(
        record_store=record_store,
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
        event_sink=NullEventSink(),
    )

    assert result.session_id == "game_1200abcd"
    assert record_store.load_session("game_1200abcd")["status"] == "complete"
```

- [ ] **Step 3: Run the updated representative runner tests and verify they fail**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_run_game_with_deepseek_models_writes_complete_chinese_logs tests/test_werewolf_runner.py::test_run_game_records_partial_state_when_max_rounds_is_exceeded tests/test_werewolf_runner.py::test_run_game_accepts_custom_session_id -v
```

Expected: FAIL with `TypeError: run_game() got an unexpected keyword argument 'record_store'`.

- [ ] **Step 4: Modify `apps/api/app/werewolf/runner.py`**

Update imports:

```python
from app.werewolf.replay import GameRecordStore
```

Replace `RunGameResult`, `GameRunError`, `run_game`, and `resume_game` signatures and persistence calls with this shape:

```python
@dataclass(frozen=True)
class RunGameResult:
    winner: str
    session_id: str


class GameRunError(RuntimeError):
    def __init__(self, message: str, session_id: str | None = None) -> None:
        super().__init__(message)
        self.session_id = session_id
```

```python
def run_game(
    *,
    record_store: GameRecordStore,
    villager_model: str | None = None,
    werewolf_model: str | None = None,
    seed: int | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    provider: ModelProvider | None = None,
    session_id: str | None = None,
    event_sink: object | None = None,
    rule_set_id: str = DEFAULT_RULE_SET_ID,
    player_configs: list[PlayerConfig] | None = None,
) -> RunGameResult:
    session_id = session_id or new_session_id()
    rule_set = get_rule_set(rule_set_id)
    default_model = default_model_name()
    selected_villager_model = villager_model or default_model
    selected_werewolf_model = werewolf_model or default_model
    run_params = {
        "villager_model": selected_villager_model,
        "werewolf_model": selected_werewolf_model,
        "seed": seed,
        "max_rounds": max_rounds,
        "rule_set_id": rule_set.id,
        "player_configs": [config.to_dict() for config in player_configs or []],
    }
    state = initialize_game_state(
        session_id=session_id,
        villager_model=selected_villager_model,
        werewolf_model=selected_werewolf_model,
        seed=seed,
        rule_set=rule_set,
        player_configs=player_configs,
    )
    logs = []
    checkpoint_manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=session_id,
        run_params=run_params,
    )
    engine_rng = random.Random(f"{seed}:engine") if seed is not None else random.Random()

    engine = None
    try:
        engine = GameEngine(
            state=state,
            provider=provider or create_model_provider(),
            max_rounds=max_rounds,
            rule_set=rule_set,
            event_sink=event_sink or NullEventSink(),
            rng=engine_rng,
            checkpoint_manager=checkpoint_manager,
        )
        logs = engine.run()
    except Exception as exc:
        if engine is not None:
            logs = engine.logs
        state.error_message = str(exc)
        record_store.save_game(state, logs)
        raise GameRunError(str(exc), session_id) from exc

    record_store.save_game(state, logs)
    record_store.clear_resume_checkpoint(session_id)
    return RunGameResult(winner=state.winner, session_id=session_id)
```

```python
def resume_game(
    *,
    session_id: str,
    record_store: GameRecordStore,
    provider: ModelProvider | None = None,
    event_sink: object | None = None,
) -> RunGameResult:
    try:
        checkpoint = record_store.load_resume_checkpoint(session_id)
    except ResumeCheckpointError as exc:
        raise GameRunError("Resume checkpoint not found", session_id) from exc

    run_params = checkpoint.get("run_params", {})
    if not isinstance(run_params, dict):
        raise GameRunError("Resume checkpoint is invalid", session_id)

    rule_set_id = str(run_params.get("rule_set_id") or DEFAULT_RULE_SET_ID)
    rule_set = get_rule_set(rule_set_id)
    max_rounds = int(run_params.get("max_rounds") or DEFAULT_MAX_ROUNDS)
    state = game_state_from_dict(checkpoint["state_at_round_start"])
    state.error_message = ""
    logs_before_round = round_logs_from_dict(checkpoint.get("logs_before_round", []))
    active_players = [str(player) for player in checkpoint.get("active_players", [])]
    if not active_players:
        active_players = [player.name for player in state.players]
    replay_provider = ReplayThenLiveProvider(
        cached_model_responses=checkpoint.get("cached_model_responses", []),
        delegate=provider or create_model_provider(),
    )
    checkpoint_manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=session_id,
        run_params=run_params,
    )
    rng = rng_from_json_state(checkpoint.get("rng_state"))
    logs_after_resume = []

    engine = None
    try:
        engine = GameEngine(
            state=state,
            provider=replay_provider,
            max_rounds=max_rounds,
            rule_set=rule_set,
            event_sink=event_sink or NullEventSink(),
            rng=rng,
            starting_active_players=active_players,
            checkpoint_manager=checkpoint_manager,
        )
        logs_after_resume = engine.run()
    except Exception as exc:
        if engine is not None:
            logs_after_resume = engine.logs
        state.error_message = str(exc)
        record_store.save_game(state, logs_before_round + logs_after_resume)
        raise GameRunError(str(exc), session_id) from exc

    logs = logs_before_round + logs_after_resume
    record_store.save_game(state, logs)
    record_store.clear_resume_checkpoint(session_id)
    return RunGameResult(winner=state.winner, session_id=session_id)
```

Remove imports for `Path`, `clear_resume_checkpoint`, `load_resume_checkpoint`, and `save_game`.

- [ ] **Step 5: Finish updating runner and resume tests**

Use these replacement rules across `apps/api/tests/test_werewolf_runner.py` and `apps/api/tests/test_werewolf_resume.py`:

```text
Remove the keyword argument logs_dir=tmp_path from run_game calls and add record_store=record_store.
Remove the keyword argument logs_dir=tmp_path / "logs" from run_game calls and add record_store=record_store.
Remove the keyword argument logs_dir=tmp_path from resume_game calls and add record_store=record_store.
Replace error.value.log_directory.name with error.value.session_id.
Replace error.value.log_directory is not None with error.value.session_id is not None.
Replace reads from result.log_directory / "game_complete.json" with record_store.load_session(result.session_id)["state"].
Replace checkpoint_path JSON reads with record_store.load_resume_checkpoint(error.value.session_id).
```

For reproducibility tests, compare loaded database state:

```python
first_state = record_store.load_session(first.session_id)["state"]
second_state = second_record_store.load_session(second.session_id)["state"]
```

Use a second fixture instance named `second_record_store` by adding this fixture to `apps/api/tests/test_werewolf_runner.py`:

```python
@pytest.fixture
def second_record_store() -> Generator[DatabaseReplayStore, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as session:
        yield DatabaseReplayStore(session)
```

- [ ] **Step 6: Run runner and resume suites**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py tests/test_werewolf_resume.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit runner conversion**

Run:

```bash
git add apps/api/app/werewolf/runner.py apps/api/app/werewolf/checkpoint.py apps/api/tests/test_werewolf_runner.py apps/api/tests/test_werewolf_resume.py
git commit -m "feat(api): write game runs to database records"
```

---

### Task 5: Switch Game API Routes To DatabaseReplayStore

**Files:**
- Modify: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Add API test helpers for database records**

Modify imports in `apps/api/tests/test_games_api.py`:

```python
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.werewolf.replay import DatabaseReplayStore
```

Update the `isolated_db` fixture deletion order:

```python
        session.query(GameReplayPayload).delete()
        session.query(GameSessionRecord).delete()
        session.query(VirtualPlayerProfile).delete()
        session.query(PlayerAvatarAsset).delete()
        session.query(User).delete()
```

Use the same deletion order after `yield`.

Replace `override_logs_root` with:

```python
def override_replay_store() -> None:
    def _override() -> Generator[DatabaseReplayStore, None, None]:
        db = TestingSessionLocal()
        try:
            yield DatabaseReplayStore(db)
        finally:
            db.close()

    app.dependency_overrides[get_replay_store] = _override
```

Add this helper:

```python
def store_game_session(
    session_id: str,
    *,
    state: dict | None = None,
    logs: list[dict] | None = None,
    checkpoint: dict | None = None,
) -> None:
    with TestingSessionLocal() as session:
        store = DatabaseReplayStore(session)
        if checkpoint is not None:
            store.save_resume_checkpoint(session_id, checkpoint)
        store.save_game_payload(
            state=state or sample_state(session_id),
            logs=logs if logs is not None else sample_logs(),
        )
        if checkpoint is not None:
            store.save_resume_checkpoint(session_id, checkpoint)
```

- [ ] **Step 2: Update representative API history tests before implementation**

Replace `test_list_games_returns_complete_and_partial_sessions` with:

```python
def test_list_games_returns_complete_and_partial_sessions() -> None:
    complete_id = "game_05095066"
    partial_id = "game_0600abcd"
    store_game_session(complete_id, state=sample_state(complete_id), logs=sample_logs())
    store_game_session(
        partial_id,
        state=sample_state(partial_id, winner="", error="Maximum rounds exceeded"),
        logs=sample_logs(),
    )
    override_replay_store()

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert {item["session_id"] for item in payload["sessions"]} == {complete_id, partial_id}
    partial = next(item for item in payload["sessions"] if item["session_id"] == partial_id)
    complete = next(item for item in payload["sessions"] if item["session_id"] == complete_id)
    assert partial["status"] == "partial"
    assert complete["winner"] == "狼人阵营"
    assert complete["round_count"] == 1
    assert complete["created_at"].endswith("Z")
```

Replace `test_get_game_detail_returns_state_and_logs`:

```python
def test_get_game_detail_returns_state_and_logs() -> None:
    session_id = "game_05095066"
    store_game_session(session_id, state=sample_state(session_id), logs=sample_logs())
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "complete"
    assert payload["state"]["players"][0]["name"] == "张三"
    assert payload["logs"][0]["eliminate"]["lm_log"]["prompt"] == "请选择今晚击杀对象。"
```

Replace `test_get_game_playback_returns_404_for_missing_session`:

```python
def test_get_game_playback_returns_404_for_missing_session() -> None:
    override_replay_store()

    try:
        response = client.get("/api/v1/games/game_1200abcd/playback")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json() == {"detail": "Game session not found"}
```

- [ ] **Step 3: Run representative API tests and verify route dependency mismatch**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_games_api.py::test_list_games_returns_complete_and_partial_sessions tests/test_games_api.py::test_get_game_detail_returns_state_and_logs tests/test_games_api.py::test_get_game_playback_returns_404_for_missing_session -v
```

Expected: FAIL until `get_replay_store` uses `DatabaseReplayStore`.

- [ ] **Step 4: Modify `apps/api/app/api/routes/games.py`**

Update imports:

```python
from app.db.session import SessionLocal, get_db
from app.werewolf.replay import DatabaseReplayStore, GameRecordStore, ReplayNotFoundError, SESSION_ID_RE
```

Replace `get_replay_store`:

```python
def get_replay_store(db: Annotated[Session, Depends(get_db)]) -> DatabaseReplayStore:
    return DatabaseReplayStore(db)
```

In `resume_game_run`, replace direct file checkpoint loading:

```python
    try:
        checkpoint = store.load_resume_checkpoint(session_id)
    except ResumeCheckpointError as exc:
        raise HTTPException(status_code=404, detail="Resume checkpoint not found") from exc
```

Remove:

```python
    checkpoint_directory = store.logs_root / session_id
```

Update thread kwargs for resume:

```python
        kwargs={
            "run_id": run.run_id,
            "registry": registry,
            "session_id": session_id,
        },
```

Replace `_run_game_in_background` body with DB session creation:

```python
    registry.mark_running(run_id)
    db = SessionLocal()
    try:
        result = run_game(
            record_store=DatabaseReplayStore(db),
            villager_model=villager_model,
            werewolf_model=werewolf_model,
            seed=seed,
            rule_set_id=rule_set_id,
            max_rounds=max_rounds,
            session_id=session_id,
            event_sink=EventSink(registry, run_id),
            player_configs=player_configs,
        )
    except GameRunError as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    finally:
        db.close()

    registry.mark_completed(run_id, winner=result.winner)
```

Replace `_resume_game_in_background` signature and body:

```python
def _resume_game_in_background(
    *,
    run_id: str,
    registry: LiveRunRegistry,
    session_id: str,
) -> None:
    registry.mark_running(run_id)
    db = SessionLocal()
    try:
        result = resume_game(
            session_id=session_id,
            record_store=DatabaseReplayStore(db),
            event_sink=EventSink(registry, run_id),
        )
    except GameRunError as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    finally:
        db.close()

    registry.mark_completed(run_id, winner=result.winner)
```

- [ ] **Step 5: Finish updating API tests**

In `apps/api/tests/test_games_api.py`, replace every direct write to `tmp_path / session_id / "game_complete.json"` with `store_game_session(session_id, state=state, logs=logs)`, every direct write to `tmp_path / session_id / "game_partial.json"` with `store_game_session(session_id, state=state, logs=logs)`, and every call to `override_logs_root(tmp_path)` with `override_replay_store()`.

For tests that validate corrupt JSON, replace them with corrupt database payload tests:

```python
def test_get_game_playback_returns_404_for_corrupt_replay_payload() -> None:
    session_id = "game_1200abcd"
    with TestingSessionLocal() as session:
        session.add(
            GameSessionRecord(
                session_id=session_id,
                status="complete",
                round_count=0,
                resumable=False,
            )
        )
        session.add(
            GameReplayPayload(
                session_id=session_id,
                state=[],
                logs=[],
            )
        )
        session.commit()
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json() == {"detail": "Game session not found"}
```

For symlink security tests, replace the file-specific assertions with this DB-only legacy file ignore test:

```python
def test_list_games_ignores_legacy_file_directories(tmp_path: Path) -> None:
    legacy_id = "game_1200abcd"
    write_json(tmp_path / legacy_id / "game_complete.json", sample_state(legacy_id))
    override_replay_store()

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"sessions": []}
```

In `test_run_game_in_background_publishes_registry_and_engine_events_directly`, monkeypatch `SessionLocal` and assert the fake receives `record_store`:

```python
    monkeypatch.setattr("app.api.routes.games.SessionLocal", TestingSessionLocal)

    def fake_run_game(*, event_sink, record_store, **kwargs: object) -> SimpleNamespace:
        assert isinstance(record_store, DatabaseReplayStore)
        event_sink.publish("phase_started", phase="night")
        return SimpleNamespace(winner="狼人阵营")
```

- [ ] **Step 6: Run API tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_games_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit API route conversion**

Run:

```bash
git add apps/api/app/api/routes/games.py apps/api/tests/test_games_api.py
git commit -m "feat(api): serve game records from database"
```

---

### Task 6: Update CLI And Add Legacy Cleanup Command

**Files:**
- Create: `apps/api/app/legacy_game_record_cleanup.py`
- Modify: `apps/api/app/cli.py`
- Modify: `apps/api/tests/test_werewolf_cli.py`

- [ ] **Step 1: Write cleanup and CLI tests**

Append these tests to `apps/api/tests/test_werewolf_cli.py`:

```python
def test_purge_legacy_game_records_dry_run_lists_matches(tmp_path, capsys) -> None:
    (tmp_path / "game_1200abcd").mkdir()
    (tmp_path / "not-a-game").mkdir()
    (tmp_path / "player_profiles.json").write_text("{}", encoding="utf-8")

    exit_code = main(["purge-legacy-game-records", "--logs-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "匹配=1 删除=0" in output
    assert (tmp_path / "game_1200abcd").exists()
    assert (tmp_path / "not-a-game").exists()
    assert (tmp_path / "player_profiles.json").exists()


def test_purge_legacy_game_records_deletes_only_matching_directories(tmp_path, capsys) -> None:
    (tmp_path / "game_1200abcd").mkdir()
    (tmp_path / "game_bad").mkdir()
    (tmp_path / "player_profile_assets").mkdir()
    (tmp_path / "player_profiles.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "outside"
    target.mkdir()
    (tmp_path / "game_ffffffff").symlink_to(target, target_is_directory=True)

    exit_code = main(["purge-legacy-game-records", "--logs-dir", str(tmp_path), "--yes"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "匹配=1 删除=1 跳过=1" in output
    assert not (tmp_path / "game_1200abcd").exists()
    assert (tmp_path / "game_bad").exists()
    assert (tmp_path / "player_profile_assets").exists()
    assert (tmp_path / "player_profiles.json").exists()
    assert (tmp_path / "game_ffffffff").is_symlink()
    assert target.exists()
```

Update `test_run_game_command_defaults_to_deepseek_and_prints_chinese_result` so it no longer passes `--logs-dir` and asserts `record_store`:

```python
    def fake_run_game(**kwargs) -> RunGameResult:
        calls.update(kwargs)
        return RunGameResult(winner="狼人阵营", session_id="game_1200abcd")

    monkeypatch.setattr("app.cli.run_game", fake_run_game)
    monkeypatch.setattr(cli, "SessionLocal", lambda: type("FakeSession", (), {"close": lambda self: None})())

    exit_code = main(["run-game", "--seed", "13", "--max-rounds", "8"])
```

Then assert:

```python
    assert "session_id=game_1200abcd" in output
    assert "日志目录=" not in output
    assert "record_store" in calls
```

- [ ] **Step 2: Run CLI tests and verify failures**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_cli.py::test_purge_legacy_game_records_dry_run_lists_matches tests/test_werewolf_cli.py::test_purge_legacy_game_records_deletes_only_matching_directories tests/test_werewolf_cli.py::test_run_game_command_defaults_to_deepseek_and_prints_chinese_result -v
```

Expected: FAIL because `purge-legacy-game-records` does not exist and `run-game` still expects `--logs-dir`.

- [ ] **Step 3: Create cleanup helper**

Create `apps/api/app/legacy_game_record_cleanup.py` with this content:

```python
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

LEGACY_GAME_DIR_RE = re.compile(r"^game_[0-9a-f]{8}$")


@dataclass(frozen=True)
class LegacyGameRecordPurgeResult:
    matched_count: int
    deleted_count: int
    skipped_count: int


def purge_legacy_game_records(logs_dir: Path, *, confirm: bool) -> LegacyGameRecordPurgeResult:
    if not logs_dir.exists() or not logs_dir.is_dir():
        return LegacyGameRecordPurgeResult(matched_count=0, deleted_count=0, skipped_count=0)

    matched: list[Path] = []
    skipped_count = 0
    for child in logs_dir.iterdir():
        if not LEGACY_GAME_DIR_RE.fullmatch(child.name):
            continue
        if child.is_symlink() or not child.is_dir():
            skipped_count += 1
            continue
        matched.append(child)

    deleted_count = 0
    if confirm:
        for directory in matched:
            shutil.rmtree(directory)
            deleted_count += 1

    return LegacyGameRecordPurgeResult(
        matched_count=len(matched),
        deleted_count=deleted_count,
        skipped_count=skipped_count,
    )
```

- [ ] **Step 4: Modify CLI**

In `apps/api/app/cli.py`, update imports:

```python
from app.legacy_game_record_cleanup import purge_legacy_game_records
from app.werewolf.replay import DatabaseReplayStore
```

Remove `--logs-dir` from the `run-game` parser. Add:

```python
    purge_records_parser = subparsers.add_parser(
        "purge-legacy-game-records",
        help="Delete legacy file-backed game_* records from a logs directory.",
    )
    purge_records_parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path(settings.werewolf_logs_dir),
    )
    purge_records_parser.add_argument("--yes", action="store_true")
    purge_records_parser.set_defaults(func=_purge_legacy_game_records_command)
```

Replace `_run_game_command`:

```python
def _run_game_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = run_game(
            record_store=DatabaseReplayStore(db),
            villager_model=args.villager_model,
            werewolf_model=args.werewolf_model,
            seed=args.seed,
            max_rounds=args.max_rounds,
        )
    except GameRunError as exc:
        print(str(exc), file=sys.stderr)
        if exc.session_id:
            print(f"session_id={exc.session_id}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"胜利阵营={result.winner}")
    print(f"session_id={result.session_id}")
    return 0
```

Add:

```python
def _purge_legacy_game_records_command(args: argparse.Namespace) -> int:
    result = purge_legacy_game_records(args.logs_dir, confirm=args.yes)
    print(
        f"匹配={result.matched_count} "
        f"删除={result.deleted_count} "
        f"跳过={result.skipped_count}"
    )
    if not args.yes and result.matched_count:
        print("未传入 --yes，未删除旧对局目录。")
    return 0
```

- [ ] **Step 5: Finish CLI test updates**

Update all remaining `run-game` CLI tests in `apps/api/tests/test_werewolf_cli.py`:

```text
Remove `"--logs-dir", str(tmp_path)` from each run-game CLI test argument list passed to `main`.
Return RunGameResult(winner="狼人阵营", session_id="game_1200abcd") in fake_run_game.
For failure tests, raise GameRunError("Maximum rounds exceeded", "game_failed").
Assert "session_id=game_failed" instead of "日志目录=".
Patch cli.SessionLocal to a fake closeable object for fake run_game tests.
```

Use this fake session helper in tests that do not need a real database:

```python
class FakeSession:
    def close(self) -> None:
        pass
```

- [ ] **Step 6: Run CLI tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_cli.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit CLI and cleanup changes**

Run:

```bash
git add apps/api/app/legacy_game_record_cleanup.py apps/api/app/cli.py apps/api/tests/test_werewolf_cli.py
git commit -m "feat(api): add legacy game record cleanup command"
```

---

### Task 7: Remove File-Backed Game Record Assumptions

**Files:**
- Modify: `apps/api/app/werewolf/runner.py`
- Modify: `apps/api/app/werewolf/replay.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`
- Modify: `apps/api/tests/test_games_api.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: Add regression tests for no game JSON writes**

Add this test to `apps/api/tests/test_werewolf_runner.py`:

```python
def test_run_game_does_not_write_legacy_game_json_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_store: DatabaseReplayStore,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = run_game(
        record_store=record_store,
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    assert record_store.load_session(result.session_id)["status"] == "complete"
    assert list(tmp_path.rglob("game_complete.json")) == []
    assert list(tmp_path.rglob("game_partial.json")) == []
    assert list(tmp_path.rglob("game_logs.json")) == []
    assert list(tmp_path.rglob("resume_checkpoint.json")) == []
```

Add this test to `apps/api/tests/test_games_api.py`:

```python
def test_game_api_reads_database_only_when_legacy_files_exist(tmp_path: Path) -> None:
    legacy_id = "game_1200abcd"
    database_id = "game_05095066"
    write_json(tmp_path / legacy_id / "game_complete.json", sample_state(legacy_id))
    store_game_session(database_id, state=sample_state(database_id), logs=sample_logs())
    override_replay_store()

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert [item["session_id"] for item in response.json()["sessions"]] == [database_id]
```

- [ ] **Step 2: Run regression tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_run_game_does_not_write_legacy_game_json_files tests/test_games_api.py::test_game_api_reads_database_only_when_legacy_files_exist -v
```

Expected: PASS after Tasks 4 and 5. If the first test finds JSON files, remove the remaining call path that imports and calls `app.werewolf.logging.save_game`.

- [ ] **Step 3: Remove unused file-backed replay helpers**

In `apps/api/app/werewolf/replay.py`, verify the old file-scanning `ReplayStore` class is gone. Run:

```bash
rg -n "ReplayStore\\(|logs_root|game_complete\\.json|game_partial\\.json|game_logs\\.json|resume_checkpoint\\.json" apps/api/app/werewolf apps/api/app/api
```

Expected remaining matches:

```text
apps/api/app/werewolf/checkpoint.py:22:RESUME_CHECKPOINT_FILE = "resume_checkpoint.json"
```

`RESUME_CHECKPOINT_FILE` may remain for constants used by cleanup tests and old explicit file evaluation tests. There should be no production call to `save_game`, `load_resume_checkpoint(directory)`, `has_resume_checkpoint(directory)`, or file-scanning replay code.

- [ ] **Step 4: Update docs**

In `README.md`, replace the runtime data paragraph:

```markdown
实时 run 和 SSE 事件保存在 API 进程内存中，当前部署应使用单个 API worker。同一进程内重复恢复同一对局会复用已有活动 run，不会重复启动模型任务；跨进程排他需要后续引入共享任务存储。
```

with:

```markdown
新对局的历史记录、完整复盘和恢复检查点保存在 PostgreSQL。旧版 `apps/api/logs/game_*` 文件记录不会再被读取；完成迁移后可执行：

```bash
cd apps/api
.venv/bin/python -m app.cli purge-legacy-game-records --logs-dir logs --yes
```

实时 run 和 SSE 事件仍保存在 API 进程内存中，当前部署应使用单个 API worker。同一进程内重复恢复同一对局会复用已有活动 run，不会重复启动模型任务；跨进程排他需要后续引入共享任务存储。
```

In `docs/architecture.md`, replace:

```markdown
- Game checkpoints, completed replays, and avatar image assets remain under `WEREWOLF_LOGS_DIR`.
- Active live runs and SSE event history are held by the in-process `LiveRunRegistry`; production currently assumes one API worker.
```

with:

```markdown
- Game checkpoints and completed replays are stored in PostgreSQL in `game_sessions` and `game_replay_payloads`.
- Avatar image assets and legacy avatar migration inputs may still use `WEREWOLF_LOGS_DIR`.
- Active live runs and SSE event history are held by the in-process `LiveRunRegistry`; production currently assumes one API worker.
```

- [ ] **Step 5: Run docs-adjacent tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_run_game_does_not_write_legacy_game_json_files tests/test_games_api.py::test_game_api_reads_database_only_when_legacy_files_exist -v
```

Expected: PASS.

- [ ] **Step 6: Commit file-assumption cleanup**

Run:

```bash
git add README.md docs/architecture.md apps/api/tests/test_werewolf_runner.py apps/api/tests/test_games_api.py
git commit -m "docs(api): document database-backed game records"
```

---

### Task 8: Full Backend Verification

**Files:**
- Verify: `apps/api`

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_models.py tests/test_game_record_store.py tests/test_werewolf_runner.py tests/test_werewolf_resume.py tests/test_games_api.py tests/test_werewolf_cli.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full API suite**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```bash
cd apps/api
.venv/bin/ruff check .
```

Expected: PASS.

- [ ] **Step 4: Run migration on local database**

Run:

```bash
docker compose up -d db
cd apps/api
.venv/bin/python -m alembic upgrade head
```

Expected: Alembic completes at `20260706_01`.

- [ ] **Step 5: Smoke-test API startup**

Run:

```bash
cd apps/api
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Expected: server starts without import errors. Stop it with `Ctrl+C` after startup.

- [ ] **Step 6: Commit verification fixes if needed**

If verification required code or test adjustments, commit only those adjustments:

```bash
git add apps/api README.md docs/architecture.md
git commit -m "fix(api): complete database game record migration"
```

If verification passed without adjustments, do not create an empty commit.

---

### Task 9: Purge Existing Legacy Game Directories

**Files:**
- Runtime cleanup: `apps/api/logs/game_*`

- [ ] **Step 1: Preview deletion count**

Run:

```bash
cd apps/api
.venv/bin/python -m app.cli purge-legacy-game-records --logs-dir logs
```

Expected: output like `匹配=38 删除=0 跳过=0` and a second line saying `未传入 --yes，未删除旧对局目录。`

- [ ] **Step 2: Delete legacy game directories**

Run:

```bash
cd apps/api
.venv/bin/python -m app.cli purge-legacy-game-records --logs-dir logs --yes
```

Expected: output like `匹配=38 删除=38 跳过=0`.

- [ ] **Step 3: Confirm only game directories were removed**

Run:

```bash
find apps/api/logs -maxdepth 1 -type d -name 'game_*' | wc -l
find apps/api/logs -maxdepth 1 -print | sort
```

Expected: first command prints `0`. The second command may still show `apps/api/logs`, `apps/api/logs/player_profile_assets`, and `apps/api/logs/player_profiles.json` if those paths existed before cleanup.

- [ ] **Step 4: Commit cleanup only if legacy records are tracked**

Run:

```bash
git status --short apps/api/logs
```

If deleted legacy game files are tracked by git, commit their deletion:

```bash
git add apps/api/logs
git commit -m "chore(api): remove legacy file-backed game records"
```

If `apps/api/logs/game_*` files are untracked or ignored, no commit is needed.

---

## Self-Review

Spec coverage:

- New DB persistence for completed games: Tasks 1, 2, 4, 5.
- New DB persistence for failed games and resume checkpoints: Tasks 2, 3, 4, 5.
- API reads from PostgreSQL only: Task 5.
- No old file fallback: Tasks 5 and 7.
- Safe deletion of old `game_*` records: Tasks 6 and 9.
- No historical import: no task imports legacy `game_*` JSON into DB.
- Non-game `WEREWOLF_LOGS_DIR` uses remain: Tasks 6, 7, and 9 preserve non-matching files and avatar directories.

Placeholder scan:

- This plan contains concrete file paths, code snippets, commands, and expected outcomes.
- The plan intentionally avoids deferred implementation markers and vague edge-case instructions.

Type consistency:

- The store name is consistently `DatabaseReplayStore`.
- The protocol name is consistently `GameRecordStore`.
- The runner keyword is consistently `record_store`.
- `RunGameResult` consistently contains `winner` and `session_id`.
- `GameRunError` consistently exposes `session_id`.
