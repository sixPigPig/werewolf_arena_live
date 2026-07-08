# Live Voice True Streaming And Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make live voice truly play audio as chunks arrive, while persisting live events and generated voice chunks in the database.

**Architecture:** Add SQLAlchemy models and stores for durable live events and voice chunks, then wire them into the existing in-memory live registry without removing SSE behavior. Change backend TTS from completed-utterance forwarding to PCM chunk forwarding, and change the frontend from Blob playback to an `AudioContext` PCM scheduler with Blob fallback for non-PCM audio.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest, Volcengine WebSocket TTS, Vite, React, Vitest, Web Audio API.

---

## Current Constraints

- The worktree already contains unrelated unstaged changes. Stage only the files listed in each task.
- Rate limiting and external access controls are out of scope because this project is single-user.
- Subtitle-only live viewing must continue to work if voice fails.
- The existing `LiveRunRegistry` API should remain usable by current tests and routes.

## File Structure

- `apps/api/app/models/live.py`: SQLAlchemy tables for live runs, live events, voice utterances, and voice audio chunks.
- `apps/api/alembic/versions/20260708_01_create_live_voice_tables.py`: database migration for those tables.
- `apps/api/app/werewolf/live_store.py`: durable store for `LiveGameRun` and `LiveEvent` records.
- `apps/api/app/werewolf/voice_store.py`: durable store for voice utterances and audio chunks.
- `apps/api/app/werewolf/live.py`: optional persistence adapter support in `LiveRunRegistry`.
- `apps/api/app/werewolf/voice.py`: voice protocol message metadata for PCM chunks.
- `apps/api/app/werewolf/volcengine_tts.py`: async text streaming, PCM config, and vendor timeouts.
- `apps/api/app/werewolf/voice_stream.py`: live event-to-TTS bridge with immediate audio forwarding.
- `apps/api/app/api/routes/games.py`: DB-backed registry/store dependencies and `current_event_id` query support.
- `packages/game-client/src/live/livePcmPlayer.ts`: PCM decoding and Web Audio scheduling helpers.
- `packages/game-client/src/live/liveVoiceStream.ts`: message types, unlock API, PCM path, and URL fix.
- `apps/mobile-web/src/pages/LivePage.tsx`: call audio unlock from the voice button before enabling voice.
- `README.md` and `apps/api/.env.example`: document TTS key semantics and PCM default.

---

### Task 1: Add Live And Voice Database Tables

**Files:**
- Create: `apps/api/app/models/live.py`
- Create: `apps/api/alembic/versions/20260708_01_create_live_voice_tables.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/tests/test_models.py`

- [ ] **Step 1: Write failing model metadata tests**

Add these imports near the top of `apps/api/tests/test_models.py`:

```python
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceUtteranceRecord,
)
```

Append these tests:

```python
def test_live_run_table_matches_expected_schema() -> None:
    table = LiveRunRecord.__table__

    assert table.name == "live_runs"
    assert set(table.columns.keys()) == {
        "run_id",
        "session_id",
        "status",
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "rule_set_id",
        "rule_set",
        "player_configs",
        "lineup_quality_warnings",
        "winner",
        "error",
        "created_at",
        "started_at",
        "completed_at",
        "updated_at",
    }
    assert table.c.run_id.primary_key is True
    assert table.c.session_id.index is True
    assert any(index.name == "ix_live_runs_status" for index in table.indexes)
    assert any(index.name == "ix_live_runs_updated_at" for index in table.indexes)


def test_live_event_table_matches_expected_schema() -> None:
    table = LiveEventRecord.__table__

    assert table.name == "live_events"
    assert set(table.columns.keys()) == {
        "run_id",
        "event_id",
        "session_id",
        "type",
        "round",
        "phase",
        "actor",
        "action",
        "payload",
        "created_at",
    }
    assert table.primary_key.columns.keys() == ["run_id", "event_id"]
    assert table.c.run_id.foreign_keys
    assert any(index.name == "ix_live_events_run_id_event_id" for index in table.indexes)
    assert any(index.name == "ix_live_events_session_id" for index in table.indexes)
    assert any(index.name == "ix_live_events_type" for index in table.indexes)


def test_voice_utterance_table_matches_expected_schema() -> None:
    table = VoiceUtteranceRecord.__table__

    assert table.name == "voice_utterances"
    assert set(table.columns.keys()) == {
        "utterance_id",
        "run_id",
        "session_id",
        "source_event_id",
        "last_source_event_id",
        "request_id",
        "speaker_kind",
        "speaker_name",
        "speaker",
        "action",
        "text",
        "text_hash",
        "audio_format",
        "sample_rate",
        "mime_type",
        "status",
        "duration_ms",
        "error_message",
        "created_at",
        "updated_at",
        "completed_at",
    }
    assert table.c.utterance_id.primary_key is True
    assert any(index.name == "ix_voice_utterances_run_source_event" for index in table.indexes)
    assert any(index.name == "ix_voice_utterances_request_id" for index in table.indexes)
    assert any(index.name == "ix_voice_utterances_text_hash" for index in table.indexes)
    assert any(index.name == "ix_voice_utterances_status" for index in table.indexes)


def test_voice_audio_chunk_table_matches_expected_schema() -> None:
    table = VoiceAudioChunkRecord.__table__

    assert table.name == "voice_audio_chunks"
    assert set(table.columns.keys()) == {
        "utterance_id",
        "chunk_index",
        "audio",
        "byte_length",
        "created_at",
    }
    assert table.primary_key.columns.keys() == ["utterance_id", "chunk_index"]
    assert table.c.utterance_id.foreign_keys
    foreign_key = next(iter(table.c.utterance_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"
```

- [ ] **Step 2: Run model tests and verify failure**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_models.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'app.models.live'`.

- [ ] **Step 3: Create SQLAlchemy models**

Create `apps/api/app/models/live.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Binary, DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LiveRunRecord(Base):
    __tablename__ = "live_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    villager_model: Mapped[str] = mapped_column(String(120), nullable=False)
    werewolf_model: Mapped[str] = mapped_column(String(120), nullable=False)
    seed: Mapped[int | None] = mapped_column(nullable=True)
    max_rounds: Mapped[int] = mapped_column(nullable=False)
    rule_set_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_set: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    player_configs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    lineup_quality_warnings: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    winner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_live_runs_status", "status"),
        Index("ix_live_runs_updated_at", "updated_at"),
    )


class LiveEventRecord(Base):
    __tablename__ = "live_events"

    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("live_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    round: Mapped[int | None] = mapped_column(nullable=True)
    phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_live_events_run_id_event_id", "run_id", "event_id"),
        Index("ix_live_events_session_id", "session_id"),
        Index("ix_live_events_type", "type"),
    )


class VoiceUtteranceRecord(Base):
    __tablename__ = "voice_utterances"

    utterance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_event_id: Mapped[int] = mapped_column(nullable=False)
    last_source_event_id: Mapped[int] = mapped_column(nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    speaker_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    speaker_name: Mapped[str] = mapped_column(String(120), nullable=False)
    speaker: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audio_format: Mapped[str] = mapped_column(String(20), nullable=False)
    sample_rate: Mapped[int] = mapped_column(nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_voice_utterances_run_source_event", "run_id", "source_event_id"),
        Index("ix_voice_utterances_request_id", "request_id"),
        Index("ix_voice_utterances_text_hash", "text_hash"),
        Index("ix_voice_utterances_status", "status"),
    )


class VoiceAudioChunkRecord(Base):
    __tablename__ = "voice_audio_chunks"

    utterance_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("voice_utterances.utterance_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_index: Mapped[int] = mapped_column(primary_key=True)
    audio: Mapped[bytes] = mapped_column(Binary, nullable=False)
    byte_length: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
```

Modify `apps/api/app/models/__init__.py` to import and export the four new classes.

- [ ] **Step 4: Create Alembic migration**

Create `apps/api/alembic/versions/20260708_01_create_live_voice_tables.py` with matching columns and indexes. Use `sa.LargeBinary()` for `voice_audio_chunks.audio` and `sa.JSON()` for JSON columns. Set `down_revision = "20260706_01"`.

- [ ] **Step 5: Run model tests and verify pass**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_models.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/models/live.py apps/api/app/models/__init__.py apps/api/alembic/versions/20260708_01_create_live_voice_tables.py apps/api/tests/test_models.py
git commit -m "feat(api): add live voice persistence tables"
```

---

### Task 2: Add DatabaseLiveStore

**Files:**
- Create: `apps/api/app/werewolf/live_store.py`
- Create: `apps/api/tests/test_live_store.py`

- [ ] **Step 1: Write failing store tests**

Create `apps/api/tests/test_live_store.py`:

```python
from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.live import LiveRunRecord
from app.werewolf.live import LiveEvent, LiveRunRegistry
from app.werewolf.live_store import DatabaseLiveStore


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


def test_live_store_saves_run_and_events(db_session: Session) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={"id": "classic_8", "name": "经典 8 人局"},
    )
    event = registry.publish(
        run.run_id,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-1", "visible_text": "我不是狼", "is_public": True},
    )
    store = DatabaseLiveStore(db_session)

    store.save_run(run)
    store.append_event(event)
    loaded_events = store.events_after(run.run_id)

    saved_run = db_session.get(LiveRunRecord, run.run_id)
    assert saved_run is not None
    assert saved_run.session_id == "game_1200abcd"
    assert [item.id for item in loaded_events] == [event.id]
    assert loaded_events[0].payload["visible_text"] == "我不是狼"


def test_live_store_events_after_filters_by_event_id(db_session: Session) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    first = registry.publish(run.run_id, "phase_started", phase="night")
    second = registry.publish(run.run_id, "phase_started", phase="day")
    store = DatabaseLiveStore(db_session)

    store.save_run(run)
    store.append_event(first)
    store.append_event(second)

    assert [event.id for event in store.events_after(run.run_id, after_id=first.id)] == [second.id]


def test_live_store_updates_run_status(db_session: Session) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    store = DatabaseLiveStore(db_session)

    store.save_run(run)
    run.status = "completed"
    run.winner = "好人阵营"
    run.completed_at = "2026-07-08T00:00:00Z"
    store.save_run(run)

    saved_run = db_session.get(LiveRunRecord, run.run_id)
    assert saved_run is not None
    assert saved_run.status == "completed"
    assert saved_run.winner == "好人阵营"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_live_store.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'app.werewolf.live_store'`.

- [ ] **Step 3: Implement `DatabaseLiveStore`**

Create `apps/api/app/werewolf/live_store.py`:

```python
from __future__ import annotations

import copy
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.live import LiveEventRecord, LiveRunRecord
from app.werewolf.live import LiveEvent, LiveGameRun


def parse_live_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_live_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class DatabaseLiveStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save_run(self, run: LiveGameRun) -> None:
        record = self.db.get(LiveRunRecord, run.run_id)
        if record is None:
            record = LiveRunRecord(
                run_id=run.run_id,
                session_id=run.session_id,
                status=run.status,
                villager_model=run.villager_model,
                werewolf_model=run.werewolf_model,
                seed=run.seed,
                max_rounds=run.max_rounds,
                rule_set_id=run.rule_set_id,
                created_at=parse_live_datetime(run.created_at) or datetime.now(tz=UTC),
            )
            self.db.add(record)
        record.status = run.status
        record.rule_set = copy.deepcopy(run.rule_set)
        record.player_configs = copy.deepcopy(run.player_configs)
        record.lineup_quality_warnings = copy.deepcopy(run.lineup_quality_warnings)
        record.winner = run.winner
        record.error = run.error
        record.started_at = parse_live_datetime(run.started_at)
        record.completed_at = parse_live_datetime(run.completed_at)
        self.db.commit()

    def append_event(self, event: LiveEvent) -> None:
        record = LiveEventRecord(
            run_id=event.run_id,
            event_id=event.id,
            session_id=event.session_id,
            type=event.type,
            round=event.round,
            phase=event.phase,
            actor=event.actor,
            action=event.action,
            payload=event.payload,
            created_at=parse_live_datetime(event.created_at) or datetime.now(tz=UTC),
        )
        self.db.merge(record)
        self.db.commit()

    def events_after(self, run_id: str, *, after_id: int | None = None) -> list[LiveEvent]:
        query = self.db.query(LiveEventRecord).filter(LiveEventRecord.run_id == run_id)
        if after_id is not None:
            query = query.filter(LiveEventRecord.event_id > after_id)
        rows = query.order_by(LiveEventRecord.event_id.asc()).all()
        return [
            LiveEvent(
                id=row.event_id,
                type=row.type,
                run_id=row.run_id,
                session_id=row.session_id,
                created_at=format_live_datetime(row.created_at),
                round=row.round,
                phase=row.phase,
                actor=row.actor,
                action=row.action,
                payload=copy.deepcopy(row.payload),
            )
            for row in rows
        ]
```

- [ ] **Step 4: Run test and verify pass**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_live_store.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/werewolf/live_store.py apps/api/tests/test_live_store.py
git commit -m "feat(api): add database live event store"
```

---

### Task 3: Wire LiveRunRegistry To Persistence

**Files:**
- Modify: `apps/api/app/werewolf/live.py`
- Modify: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/tests/test_live.py`
- Modify: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Add failing registry persistence tests**

Append to `apps/api/tests/test_live.py`:

```python
class RecordingLiveStore:
    def __init__(self) -> None:
        self.saved_runs = []
        self.events = []

    def save_run(self, run) -> None:
        self.saved_runs.append((run.run_id, run.status, run.winner, run.error))

    def append_event(self, event) -> None:
        self.events.append((event.run_id, event.id, event.type))


def test_live_registry_persists_created_run_and_events() -> None:
    store = RecordingLiveStore()
    registry = LiveRunRegistry(live_store=store)

    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    registry.mark_running(run.run_id)
    registry.mark_completed(run.run_id, winner="好人阵营")

    assert [item[1] for item in store.saved_runs] == ["queued", "running", "completed"]
    assert [item[2] for item in store.events] == ["run_created", "run_started", "game_completed"]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_live.py::test_live_registry_persists_created_run_and_events -q
```

Expected: fail because `LiveRunRegistry.__init__` does not accept `live_store`.

- [ ] **Step 3: Modify registry constructor and publish path**

In `apps/api/app/werewolf/live.py`, add a protocol and optional store:

```python
class LiveStore(Protocol):
    def save_run(self, run: LiveGameRun) -> None:
        ...

    def append_event(self, event: LiveEvent) -> None:
        ...
```

Change `LiveRunRegistry.__init__`:

```python
def __init__(self, live_store: LiveStore | None = None) -> None:
    self._runs: dict[str, LiveGameRun] = {}
    self._lock = threading.RLock()
    self._live_store = live_store
```

After run creation, call `self._persist_run_locked(run)`. Inside `_publish_locked`, append to memory, persist event, then notify subscribers:

```python
run.next_event_id += 1
run.events.append(event)
self._persist_event_locked(event)
for subscriber in run.subscribers:
    subscriber.put(event)
return event
```

Add helpers:

```python
def _persist_run_locked(self, run: LiveGameRun) -> None:
    if self._live_store is not None:
        self._live_store.save_run(run)


def _persist_event_locked(self, event: LiveEvent) -> None:
    if self._live_store is not None:
        self._live_store.append_event(event)
```

Call `_persist_run_locked` after status changes in `mark_running`, `mark_completed`, and `mark_failed` before publishing the status event.

- [ ] **Step 4: Wire route dependency without replacing test overrides**

In `apps/api/app/api/routes/games.py`, keep the global registry for tests, but provide a store-backed registry at module creation:

```python
live_registry = LiveRunRegistry()
```

Leave the global line unchanged in this task to avoid broad API-test churn. Add a follow-up dependency helper:

```python
def attach_live_store_for_request(registry: LiveRunRegistry, db: Session) -> LiveRunRegistry:
    registry.set_live_store(DatabaseLiveStore(db))
    return registry
```

If adding `set_live_store`, make it simple:

```python
def set_live_store(self, live_store: LiveStore | None) -> None:
    with self._lock:
        self._live_store = live_store
```

Use this only in request paths that create runs. Background threads can continue using the store that was attached during run creation.

- [ ] **Step 5: Run registry and API smoke tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_live.py tests/test_games_api.py::test_create_game_run_returns_live_run -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/live.py apps/api/app/api/routes/games.py apps/api/tests/test_live.py apps/api/tests/test_games_api.py
git commit -m "feat(api): persist live registry events"
```

---

### Task 4: Add VoiceUtteranceStore

**Files:**
- Create: `apps/api/app/werewolf/voice_store.py`
- Create: `apps/api/tests/test_voice_store.py`

- [ ] **Step 1: Write failing voice store tests**

Create `apps/api/tests/test_voice_store.py`:

```python
from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.werewolf.voice import VoiceUtterance
from app.werewolf.voice_store import DatabaseVoiceStore, text_hash_for_voice


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


def utterance(text: str = "我不是狼") -> VoiceUtterance:
    return VoiceUtterance(
        utterance_id="voice_1",
        run_id="run_1",
        source_event_id=4,
        request_id="req-1",
        speaker_kind="player",
        speaker_name="阿青",
        speaker="zh_female_vv_uranus_bigtts",
        text=text,
        action="debate",
    )


def test_voice_store_creates_updates_chunks_and_completes(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")

    store.upsert_utterance(
        utterance(),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="synthesizing",
    )
    store.append_chunk("voice_1", chunk_index=0, audio=b"abc")
    store.append_chunk("voice_1", chunk_index=1, audio=b"def")
    store.complete_utterance("voice_1", duration_ms=1200)

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "complete"
    assert loaded["text"] == "我不是狼"
    assert store.load_chunks("voice_1") == [b"abc", b"def"]


def test_voice_store_finds_recent_utterance_for_request(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    first = utterance("第一句")
    second = utterance("第二句")
    second = VoiceUtterance(
        utterance_id="voice_2",
        run_id=second.run_id,
        source_event_id=8,
        request_id=second.request_id,
        speaker_kind=second.speaker_kind,
        speaker_name=second.speaker_name,
        speaker=second.speaker,
        text=second.text,
        action=second.action,
    )

    store.upsert_utterance(first, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.upsert_utterance(second, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")

    found = store.find_recent_utterance(run_id="run_1", current_event_id=9)
    assert found is not None
    assert found["utterance_id"] == "voice_2"


def test_text_hash_includes_voice_settings() -> None:
    assert text_hash_for_voice(
        speaker="speaker-a",
        audio_format="pcm",
        sample_rate=24000,
        text="hello",
    ) != text_hash_for_voice(
        speaker="speaker-b",
        audio_format="pcm",
        sample_rate=24000,
        text="hello",
    )
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice_store.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'app.werewolf.voice_store'`.

- [ ] **Step 3: Implement voice store**

Create `apps/api/app/werewolf/voice_store.py` with:

```python
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.live import VoiceAudioChunkRecord, VoiceUtteranceRecord
from app.werewolf.voice import VoiceUtterance


def text_hash_for_voice(
    *,
    speaker: str,
    audio_format: str,
    sample_rate: int,
    text: str,
) -> str:
    source = "\n".join([speaker, audio_format, str(sample_rate), text])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


class DatabaseVoiceStore:
    def __init__(self, db: Session, *, session_id: str) -> None:
        self.db = db
        self.session_id = session_id

    def upsert_utterance(
        self,
        utterance: VoiceUtterance,
        *,
        audio_format: str,
        sample_rate: int,
        mime_type: str,
        status: str = "synthesizing",
    ) -> None:
        record = self.db.get(VoiceUtteranceRecord, utterance.utterance_id)
        if record is None:
            record = VoiceUtteranceRecord(
                utterance_id=utterance.utterance_id,
                run_id=utterance.run_id,
                session_id=self.session_id,
                source_event_id=utterance.source_event_id,
                last_source_event_id=utterance.source_event_id,
                request_id=utterance.request_id,
                speaker_kind=utterance.speaker_kind,
                speaker_name=utterance.speaker_name,
                speaker=utterance.speaker,
                action=utterance.action,
                text=utterance.text,
                text_hash=text_hash_for_voice(
                    speaker=utterance.speaker,
                    audio_format=audio_format,
                    sample_rate=sample_rate,
                    text=utterance.text,
                ),
                audio_format=audio_format,
                sample_rate=sample_rate,
                mime_type=mime_type,
                status=status,
            )
            self.db.add(record)
        record.last_source_event_id = max(record.last_source_event_id, utterance.source_event_id)
        record.text = utterance.text
        record.text_hash = text_hash_for_voice(
            speaker=utterance.speaker,
            audio_format=audio_format,
            sample_rate=sample_rate,
            text=utterance.text,
        )
        record.status = status
        self.db.commit()

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        self.db.merge(
            VoiceAudioChunkRecord(
                utterance_id=utterance_id,
                chunk_index=chunk_index,
                audio=audio,
                byte_length=len(audio),
            )
        )
        self.db.commit()

    def complete_utterance(self, utterance_id: str, *, duration_ms: int) -> None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None:
            return
        record.status = "complete"
        record.duration_ms = duration_ms
        record.completed_at = datetime.now(tz=UTC)
        self.db.commit()

    def fail_utterance(self, utterance_id: str, *, message: str) -> None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None:
            return
        record.status = "failed"
        record.error_message = message
        record.completed_at = datetime.now(tz=UTC)
        self.db.commit()

    def load_utterance(self, utterance_id: str) -> dict[str, Any] | None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None:
            return None
        return {
            "utterance_id": record.utterance_id,
            "status": record.status,
            "text": record.text,
            "source_event_id": record.source_event_id,
            "last_source_event_id": record.last_source_event_id,
            "mime_type": record.mime_type,
            "audio_format": record.audio_format,
            "sample_rate": record.sample_rate,
        }

    def load_chunks(self, utterance_id: str) -> list[bytes]:
        rows = (
            self.db.query(VoiceAudioChunkRecord)
            .filter(VoiceAudioChunkRecord.utterance_id == utterance_id)
            .order_by(VoiceAudioChunkRecord.chunk_index.asc())
            .all()
        )
        return [row.audio for row in rows]

    def find_recent_utterance(
        self,
        *,
        run_id: str,
        current_event_id: int,
    ) -> dict[str, Any] | None:
        record = (
            self.db.query(VoiceUtteranceRecord)
            .filter(VoiceUtteranceRecord.run_id == run_id)
            .filter(VoiceUtteranceRecord.source_event_id <= current_event_id)
            .order_by(VoiceUtteranceRecord.source_event_id.desc())
            .first()
        )
        if record is None:
            return None
        return self.load_utterance(record.utterance_id)
```

- [ ] **Step 4: Run voice store tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice_store.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/werewolf/voice_store.py apps/api/tests/test_voice_store.py
git commit -m "feat(api): add voice chunk store"
```

---

### Task 5: Extend Voice Protocol For PCM Chunks

**Files:**
- Modify: `apps/api/app/werewolf/voice.py`
- Modify: `apps/api/app/werewolf/volcengine_tts.py`
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/.env.example`
- Modify: `apps/api/tests/test_voice.py`
- Modify: `apps/api/tests/test_volcengine_tts.py`

- [ ] **Step 1: Write failing protocol tests**

Update `test_voice_messages_serialize_audio_chunks` in `apps/api/tests/test_voice.py` to call:

```python
start, chunk, end = build_voice_messages(
    utterance_id="voice_1",
    source_event_id=10,
    speaker_kind="player",
    speaker_name="阿青",
    audio=b"abc",
    mime_type="audio/L16",
    duration_ms=1200,
    audio_format="pcm",
    sample_rate=24000,
    chunk_index=3,
)
```

Assert:

```python
assert start["audio_format"] == "pcm"
assert start["sample_rate"] == 24000
assert chunk == {
    "type": "audio_chunk",
    "utterance_id": "voice_1",
    "chunk_index": 3,
    "mime_type": "audio/L16",
    "audio_format": "pcm",
    "sample_rate": 24000,
    "data": "YWJj",
}
```

Add to `apps/api/tests/test_volcengine_tts.py`:

```python
def test_mime_type_for_pcm_uses_l16() -> None:
    assert mime_type_for_format("pcm") == "audio/L16"
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice.py::test_voice_messages_serialize_audio_chunks tests/test_volcengine_tts.py::test_mime_type_for_pcm_uses_l16 -q
```

Expected: `build_voice_messages` fails due to missing keyword arguments.

- [ ] **Step 3: Extend `build_voice_messages`**

In `apps/api/app/werewolf/voice.py`, add keyword-only arguments:

```python
audio_format: str,
sample_rate: int,
chunk_index: int,
```

Add `audio_format` and `sample_rate` to `voice_start`, and add `chunk_index`, `audio_format`, and `sample_rate` to `audio_chunk`.

- [ ] **Step 4: Make PCM the default live TTS format**

In `apps/api/app/core/config.py`, change:

```python
ark_tts_audio_format: str = "pcm"
```

In `apps/api/.env.example`, change:

```env
ARK_TTS_AUDIO_FORMAT=pcm
```

Keep `ARK_TTS_SAMPLE_RATE=24000`.

- [ ] **Step 5: Run protocol tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice.py tests/test_volcengine_tts.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/voice.py apps/api/app/werewolf/volcengine_tts.py apps/api/app/core/config.py apps/api/.env.example apps/api/tests/test_voice.py apps/api/tests/test_volcengine_tts.py
git commit -m "feat(api): add pcm voice stream metadata"
```

---

### Task 6: Stream TTS Audio Before Utterance End

**Files:**
- Modify: `apps/api/app/werewolf/volcengine_tts.py`
- Modify: `apps/api/app/werewolf/voice_stream.py`
- Modify: `apps/api/tests/test_volcengine_tts.py`
- Modify: `apps/api/tests/test_voice_stream_api.py`

- [ ] **Step 1: Add failing backend stream timing test**

In `apps/api/tests/test_voice_stream_api.py`, add a fake client that yields multiple chunks:

```python
class MultiChunkTtsClient:
    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config

    async def synthesize(self, *, speaker: str, text_chunks: list[str]):
        yield b"first"
        yield b"second"
```

Add test:

```python
def test_voice_stream_sends_audio_chunks_before_voice_end() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=MultiChunkTtsClient,
    )

    async def stream_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={"request_id": "req-1", "visible_text": "我是好人。", "is_public": True},
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    message_types = [message["type"] for message in websocket.messages]
    assert message_types[:4] == ["voice_start", "audio_chunk", "audio_chunk", "voice_end"]
    assert websocket.messages[1]["chunk_index"] == 0
    assert websocket.messages[2]["chunk_index"] == 1
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice_stream_api.py::test_voice_stream_sends_audio_chunks_before_voice_end -q
```

Expected: fail until `audio_chunk` includes `chunk_index` and the service tracks chunk order.

- [ ] **Step 3: Add chunk indexes in `_stream_utterance`**

In `apps/api/app/werewolf/voice_stream.py`, set:

```python
chunk_index = 0
```

Increment after every yielded audio chunk. Call `build_voice_messages` with `audio_format=self.config.audio_format`, `sample_rate=self.config.sample_rate`, and `chunk_index=chunk_index`.

- [ ] **Step 4: Add adapter timeout tests**

In `apps/api/tests/test_volcengine_tts.py`, add a test that patches `protocol.receive_message` to await forever and asserts `asyncio.TimeoutError` becomes `RuntimeError("Volcengine TTS timed out")`.

- [ ] **Step 5: Add conservative timeouts**

In `apps/api/app/werewolf/volcengine_tts.py`, add module constants:

```python
CONNECT_TIMEOUT_SECONDS = 8
EVENT_TIMEOUT_SECONDS = 8
FIRST_AUDIO_TIMEOUT_SECONDS = 12
AUDIO_IDLE_TIMEOUT_SECONDS = 8
```

Wrap waits:

```python
await asyncio.wait_for(protocol.wait_for_event(...), timeout=EVENT_TIMEOUT_SECONDS)
message = await asyncio.wait_for(
    protocol.receive_message(websocket),
    timeout=FIRST_AUDIO_TIMEOUT_SECONDS if not yielded_audio else AUDIO_IDLE_TIMEOUT_SECONDS,
)
```

Raise:

```python
raise RuntimeError("Volcengine TTS timed out") from exc
```

- [ ] **Step 6: Run backend voice tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice.py tests/test_volcengine_tts.py tests/test_voice_stream_api.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/volcengine_tts.py apps/api/app/werewolf/voice_stream.py apps/api/tests/test_volcengine_tts.py apps/api/tests/test_voice_stream_api.py
git commit -m "feat(api): stream voice audio chunks immediately"
```

---

### Task 7: Persist Voice Utterances And Audio Chunks During Streaming

**Files:**
- Modify: `apps/api/app/werewolf/voice_stream.py`
- Modify: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/tests/test_voice_stream_api.py`

- [ ] **Step 1: Add fake voice store to stream tests**

In `apps/api/tests/test_voice_stream_api.py`, add:

```python
class RecordingVoiceStore:
    def __init__(self) -> None:
        self.utterances = []
        self.chunks = []
        self.completed = []
        self.failed = []

    def upsert_utterance(self, utterance, *, audio_format, sample_rate, mime_type, status="synthesizing") -> None:
        self.utterances.append((utterance.utterance_id, utterance.text, audio_format, sample_rate, mime_type, status))

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        self.chunks.append((utterance_id, chunk_index, audio))

    def complete_utterance(self, utterance_id: str, *, duration_ms: int) -> None:
        self.completed.append((utterance_id, duration_ms))

    def fail_utterance(self, utterance_id: str, *, message: str) -> None:
        self.failed.append((utterance_id, message))
```

Add test:

```python
def test_voice_stream_persists_utterance_chunks_and_completion() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={"request_id": "req-1", "visible_text": "我是好人。", "is_public": True},
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    assert voice_store.utterances[0][1] == "我是好人。"
    assert voice_store.chunks[0][1:] == (0, b"abc")
    assert voice_store.completed[0][0] == voice_store.utterances[0][0]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice_stream_api.py::test_voice_stream_persists_utterance_chunks_and_completion -q
```

Expected: fail because `LiveVoiceStreamService` does not accept `voice_store_factory`.

- [ ] **Step 3: Add optional voice store factory**

In `apps/api/app/werewolf/voice_stream.py`, define:

```python
class VoiceStore(Protocol):
    def upsert_utterance(self, utterance: VoiceUtterance, *, audio_format: str, sample_rate: int, mime_type: str, status: str = "synthesizing") -> None:
        ...

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        ...

    def complete_utterance(self, utterance_id: str, *, duration_ms: int) -> None:
        ...

    def fail_utterance(self, utterance_id: str, *, message: str) -> None:
        ...
```

Add `voice_store_factory: Callable[[str], VoiceStore | None] | None = None` to `LiveVoiceStreamService.__init__`. Inside `stream_run`, after loading `run`, create:

```python
voice_store = self.voice_store_factory(run.session_id) if self.voice_store_factory else None
```

Pass `voice_store` into `_stream_utterance`. Persist:

- before synthesis: `upsert_utterance(...)`
- each audio chunk: `append_chunk(...)`
- after `voice_end`: `complete_utterance(...)`
- in exception path: `fail_utterance(...)`

- [ ] **Step 4: Wire route dependency**

In `apps/api/app/api/routes/games.py`, create the voice store factory using `SessionLocal`:

```python
def build_voice_store_factory():
    def _factory(session_id: str):
        db = SessionLocal()
        return DatabaseVoiceStore(db, session_id=session_id)

    return _factory
```

Because that factory opens sessions, add a small wrapper class that closes the session after each method or create a `SessionVoiceStore` wrapper with `close()`. The implementation must not leak sessions after WebSocket disconnect.

- [ ] **Step 5: Run stream tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice_stream_api.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/voice_stream.py apps/api/app/api/routes/games.py apps/api/tests/test_voice_stream_api.py
git commit -m "feat(api): persist live voice chunks"
```

---

### Task 8: Add PCM Audio Scheduler

**Files:**
- Create: `packages/game-client/src/live/livePcmPlayer.ts`
- Create: `packages/game-client/src/live/livePcmPlayer.test.ts`
- Modify: `packages/game-client/src/live/index.ts`

- [ ] **Step 1: Write failing PCM tests**

Create `packages/game-client/src/live/livePcmPlayer.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import {
  base64ToPcm16,
  createPcmAudioScheduler,
  pcm16ToFloat32,
} from "./livePcmPlayer";

function int16Base64(values: number[]) {
  const bytes = new Uint8Array(values.length * 2);
  const view = new DataView(bytes.buffer);
  values.forEach((value, index) => view.setInt16(index * 2, value, true));
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

describe("live PCM player", () => {
  it("decodes base64 little-endian pcm16", () => {
    expect(Array.from(base64ToPcm16(int16Base64([0, 32767, -32768])))).toEqual([
      0,
      32767,
      -32768,
    ]);
  });

  it("converts int16 pcm to float audio samples", () => {
    expect(Array.from(pcm16ToFloat32(new Int16Array([0, 32767, -32768])))).toEqual([
      0,
      32767 / 32768,
      -1,
    ]);
  });

  it("schedules chunks continuously", async () => {
    const starts: number[] = [];
    const context = {
      currentTime: 10,
      state: "running",
      createBuffer: vi.fn((_channels: number, length: number, sampleRate: number) => ({
        duration: length / sampleRate,
        getChannelData: () => new Float32Array(length),
      })),
      createBufferSource: vi.fn(() => ({
        buffer: null,
        connect: vi.fn(),
        start: vi.fn((time: number) => starts.push(time)),
      })),
      destination: {},
      resume: vi.fn().mockResolvedValue(undefined),
      suspend: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
    } as unknown as AudioContext);
    const scheduler = createPcmAudioScheduler(context);

    await scheduler.schedule(int16Base64([1, 2]), 2);
    await scheduler.schedule(int16Base64([3, 4]), 2);

    expect(starts).toEqual([10, 11]);
  });
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
pnpm --filter @werewolf-arena/game-client test -- livePcmPlayer
```

Expected: fail because `livePcmPlayer.ts` does not exist.

- [ ] **Step 3: Implement PCM helpers**

Create `packages/game-client/src/live/livePcmPlayer.ts`:

```ts
export function base64ToPcm16(data: string) {
  const binary = globalThis.atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const view = new DataView(bytes.buffer);
  const samples = new Int16Array(Math.floor(bytes.byteLength / 2));
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = view.getInt16(index * 2, true);
  }
  return samples;
}

export function pcm16ToFloat32(samples: Int16Array) {
  const output = new Float32Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    output[index] = Math.max(-1, samples[index] / 32768);
  }
  return output;
}

export type PcmAudioScheduler = {
  close: () => Promise<void>;
  resume: () => Promise<void>;
  schedule: (base64Pcm: string, sampleRate: number) => Promise<void>;
  suspend: () => Promise<void>;
};

export function createPcmAudioScheduler(context: AudioContext): PcmAudioScheduler {
  let nextPlaybackTime = context.currentTime;

  return {
    async close() {
      await context.close();
    },
    async resume() {
      if (context.state !== "running") {
        await context.resume();
      }
      nextPlaybackTime = Math.max(nextPlaybackTime, context.currentTime);
    },
    async schedule(base64Pcm: string, sampleRate: number) {
      const pcm = base64ToPcm16(base64Pcm);
      const samples = pcm16ToFloat32(pcm);
      const buffer = context.createBuffer(1, samples.length, sampleRate);
      buffer.getChannelData(0).set(samples);
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      const startTime = Math.max(nextPlaybackTime, context.currentTime);
      source.start(startTime);
      nextPlaybackTime = startTime + buffer.duration;
    },
    async suspend() {
      if (context.state === "running") {
        await context.suspend();
      }
    },
  };
}
```

Export from `packages/game-client/src/live/index.ts`.

- [ ] **Step 4: Run PCM tests**

Run:

```bash
pnpm --filter @werewolf-arena/game-client test -- livePcmPlayer
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add packages/game-client/src/live/livePcmPlayer.ts packages/game-client/src/live/livePcmPlayer.test.ts packages/game-client/src/live/index.ts
git commit -m "feat(client): add pcm voice scheduler"
```

---

### Task 9: Use AudioContext In `useLiveVoiceStream`

**Files:**
- Modify: `packages/game-client/src/live/liveVoiceStream.ts`
- Modify: `packages/game-client/src/live/liveVoiceStream.test.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`

- [ ] **Step 1: Extend message types and tests**

In `packages/game-client/src/live/liveVoiceStream.test.tsx`, update `emitReadyUtterance` to include:

```ts
audio_format: "pcm",
sample_rate: 24000,
chunk_index: 0,
```

Add a hook test:

```ts
it("unlocks an audio context before enabling voice playback", async () => {
  const resume = vi.fn().mockResolvedValue(undefined);
  const close = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal(
    "AudioContext",
    vi.fn(() => ({
      currentTime: 0,
      state: "suspended",
      createBuffer: vi.fn(),
      createBufferSource: vi.fn(),
      destination: {},
      resume,
      suspend: vi.fn().mockResolvedValue(undefined),
      close,
    })),
  );
  vi.stubGlobal("WebSocket", MockWebSocket);

  const { result } = renderHook(() =>
    useLiveVoiceStream("run-1", {
      currentEventId: 1,
      enabled: false,
      isPaused: false,
    }),
  );

  await act(async () => {
    await result.current.unlockAudio();
  });

  expect(resume).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Run hook tests and verify failure**

Run:

```bash
pnpm --filter @werewolf-arena/game-client test -- liveVoiceStream
```

Expected: fail because `unlockAudio` is not returned and PCM metadata is not validated.

- [ ] **Step 3: Implement audio unlock and PCM scheduling**

In `packages/game-client/src/live/liveVoiceStream.ts`:

- Add `audio_format`, `sample_rate`, and `chunk_index` to message types and validation.
- Import `createPcmAudioScheduler`.
- Keep Blob fallback for messages where `audio_format !== "pcm"`.
- Add `unlockAudio` to the hook return value.
- Store the scheduler in a ref.
- On PCM `audio_chunk`, schedule the chunk when the item is active and the director has reached `sourceEventId`.
- On pause, call scheduler `suspend`.
- On resume, call scheduler `resume`.
- On disabled or run change, close scheduler and clear refs.

The hook return should include:

```ts
unlockAudio: () => Promise<boolean>;
```

The implementation should return `false` and record `"当前浏览器不支持语音播放。"` if `AudioContext` is unavailable.

- [ ] **Step 4: Update mobile voice button handler**

In `apps/mobile-web/src/pages/LivePage.tsx`, make `handleToggleVoice` async:

```ts
const handleToggleVoice = async () => {
  if (!voiceEnabled) {
    const unlocked = await voice.unlockAudio();
    if (!unlocked) {
      return;
    }
  }
  if (voiceEnabled && voice.connectionState === "error") {
    setVoiceEnabled(false);
    window.setTimeout(() => setVoiceEnabled(true), 0);
    return;
  }

  setVoiceEnabled((current) => !current);
};
```

- [ ] **Step 5: Run frontend tests**

Run:

```bash
pnpm --filter @werewolf-arena/game-client test -- liveVoiceStream livePcmPlayer
pnpm --filter mobile-web test -- LivePage
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add packages/game-client/src/live/liveVoiceStream.ts packages/game-client/src/live/liveVoiceStream.test.tsx apps/mobile-web/src/pages/LivePage.tsx apps/mobile-web/src/pages/LivePage.test.tsx
git commit -m "feat(mobile): play live voice pcm chunks"
```

---

### Task 10: Add Late Connect Recovery And URL Fix

**Files:**
- Modify: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/app/werewolf/voice_stream.py`
- Modify: `apps/api/tests/test_voice_stream_api.py`
- Modify: `packages/game-client/src/live/liveVoiceStream.ts`
- Modify: `packages/game-client/src/live/liveVoiceStream.test.tsx`

- [ ] **Step 1: Add URL tests**

In `packages/game-client/src/live/liveVoiceStream.test.tsx`, replace the `/api` doubled expectation with:

```ts
expect(resolveVoiceStreamUrl("run/slash id", "/api")).toBe(
  `${expectedOrigin}/api/v1/games/runs/run%2Fslash%20id/voice-stream`,
);
```

Add:

```ts
expect(resolveVoiceStreamUrl("run-1", "", 42)).toContain("current_event_id=42");
```

- [ ] **Step 2: Run URL test and verify failure**

Run:

```bash
pnpm --filter @werewolf-arena/game-client test -- liveVoiceStream
```

Expected: fail because `/api/api/v1` is still produced and `current_event_id` is not supported.

- [ ] **Step 3: Fix URL builder**

Change `resolveVoiceStreamUrl` signature:

```ts
export function resolveVoiceStreamUrl(
  runId: string,
  baseUrl = API_BASE_URL,
  currentEventId?: number | null,
) {
```

When `base.pathname` already ends with `/api`, append `/v1/games/...` instead of `/api/v1/games/...`. Set `current_event_id` in `base.searchParams` when present.

- [ ] **Step 4: Add backend late-connect test**

In `apps/api/tests/test_voice_stream_api.py`, add a fake voice store with `find_recent_utterance` and `load_chunks`:

```python
class ReplayVoiceStore(RecordingVoiceStore):
    def find_recent_utterance(self, *, run_id: str, current_event_id: int):
        return {
            "utterance_id": "voice_saved",
            "source_event_id": current_event_id,
            "speaker_kind": "player",
            "speaker_name": "阿青",
            "mime_type": "audio/L16",
            "audio_format": "pcm",
            "sample_rate": 24000,
        }

    def load_chunks(self, utterance_id: str):
        return [b"saved"]
```

Add test:

```python
def test_voice_stream_replays_saved_chunks_for_late_connect() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    voice_store = ReplayVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_saved() -> None:
        task = asyncio.create_task(
            service.stream_run(run.run_id, websocket, current_event_id=7)
        )
        await asyncio.sleep(0)
        websocket.disconnect()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_saved())

    assert [message["type"] for message in websocket.messages[:3]] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
```

- [ ] **Step 5: Implement late-connect replay**

In `LiveVoiceStreamService.stream_run`, accept `current_event_id: int | None = None`. If `voice_store` exists and `current_event_id` is not `None`, call `find_recent_utterance`. If it returns a complete utterance with chunks, send:

- `voice_start`
- each saved `audio_chunk` with chunk indexes
- `voice_end`

Then subscribe to future events after the latest current live event, as before.

In `games.py`, add:

```python
current_event_id: Annotated[int | None, Query(ge=0)] = None
```

to the WebSocket route and pass it to `streamer.stream_run`.

- [ ] **Step 6: Run late-connect tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice_stream_api.py -q
pnpm --filter @werewolf-arena/game-client test -- liveVoiceStream
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/api/routes/games.py apps/api/app/werewolf/voice_stream.py apps/api/tests/test_voice_stream_api.py packages/game-client/src/live/liveVoiceStream.ts packages/game-client/src/live/liveVoiceStream.test.tsx
git commit -m "feat(live): recover voice stream on late connect"
```

---

### Task 11: Document TTS Configuration And Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `apps/api/.env.example`

- [ ] **Step 1: Update documentation**

In `README.md`, add a short voice subsection after model configuration:

```markdown
### 实时语音配置

实时语音使用火山/豆包语音合成 TTS 配置，和普通对局文本模型 key 不是同一个权限语义。`ARK_TTS_API_KEY` 必须具备 `ARK_TTS_RESOURCE_ID` 对应的语音合成资源权限。默认直播路径使用 `pcm` + `24000` Hz，以便移动端可以边收边播。

本项目当前按单人本地使用设计，没有对 `/voice-stream` 做公开访问限流。若后续开放给多人或公网访问，需要再补鉴权、限流和共享音频缓存策略。
```

In `apps/api/.env.example`, add comments above TTS variables:

```env
# Live TTS uses a speech/TTS-capable key for the configured resource ID.
# This key is not assumed to be interchangeable with chat model provider keys.
```

- [ ] **Step 2: Run full relevant backend verification**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_models.py tests/test_live.py tests/test_live_store.py tests/test_voice.py tests/test_voice_store.py tests/test_volcengine_tts.py tests/test_voice_stream_api.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 3: Run frontend verification**

Run:

```bash
pnpm --filter @werewolf-arena/game-client test -- liveVoiceStream livePcmPlayer
pnpm --filter @werewolf-arena/game-client typecheck
pnpm --filter mobile-web test -- LivePage
pnpm --filter mobile-web build
```

Expected: all commands pass.

- [ ] **Step 4: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit docs and final fixes**

```bash
git add README.md apps/api/.env.example
git commit -m "docs: document live voice streaming config"
```

---

## Self-Review Checklist

- Spec coverage: database tables, stores, true PCM playback, late connect recovery, URL fix, TTS key docs, vendor timeout handling, and fallback subtitle behavior are covered.
- Completeness scan: this plan intentionally avoids unresolved markers, vague "add tests", and unbounded future work.
- Type consistency: backend message fields use `audio_format`, `sample_rate`, and `chunk_index`; frontend tests and hook should use the same field names.
- Scope: implementation is broad but decomposed into independently testable tasks. It does not include public access controls, voice replay UI, backfill, or per-player speaker configuration.
