from __future__ import annotations

import copy
import os
import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event as sqlalchemy_event, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import StaticPool

from app.api.routes.games import SessionLiveStore
from app.db.base import Base
from app.models.live import LiveEventRecord, LiveRunRecord
from app.werewolf.live import (
    ACTIVATION_ACK_RUN_FIELD_NAMES,
    ACTIVATION_ACK_RUN_TIMESTAMP_NAMES,
    EventSink,
    GameRunCanceled,
    LiveEvent,
    LiveRunRegistry,
    RunLeaseUnavailable,
    RunRecoveryCandidate,
)
from app.werewolf.live_store import (
    DatabaseLiveStore,
    activation_ack_schema_inventory_complete,
)
from app.werewolf.orphan_reaper import run_next_orphan_recovery


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


def pinned_rule_snapshot() -> dict[str, object]:
    return {
        "id": "classic_8",
        "version": "2",
        "name": " 经典 8 人局 ",
        "revision_id": "revision-2",
        "revision_no": 2,
        "schema_version": 1,
        "content_hash": "a" * 64,
        "storage_marker": {"preserve": ["exact", 2]},
    }


def test_activation_ack_inventory_covers_every_semantic_run_column() -> None:
    table_columns = frozenset(column.name for column in LiveRunRecord.__table__.columns)

    assert activation_ack_schema_inventory_complete() is True
    assert (
        ACTIVATION_ACK_RUN_FIELD_NAMES | ACTIVATION_ACK_RUN_TIMESTAMP_NAMES | {"updated_at"}
        == table_columns
    )


def seed_incomplete_live_run(
    db_session: Session,
    *,
    run_id: str = "run_incomplete",
    session_id: str = "game_incomplete",
    fence_token: int = 4,
    control_version: int = 2,
    recovery_attempts: int = 0,
) -> LiveRunRecord:
    stale_at = datetime.now(tz=UTC) - timedelta(minutes=5)
    record = LiveRunRecord(
        run_id=run_id,
        session_id=session_id,
        status="queued",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={"id": "classic_8"},
        created_at=stale_at,
        worker_id="worker-incomplete-owner",
        worker_heartbeat_at=stale_at,
        lease_expires_at=stale_at,
        fence_token=fence_token,
        control_version=control_version,
        recovery_attempts=recovery_attempts,
        recovery_not_before=stale_at,
    )
    db_session.add(record)
    db_session.commit()
    return record


def live_run_claim_state(
    session_factory: sessionmaker[Session],
    run_id: str,
) -> tuple[object, ...]:
    with session_factory() as observer:
        saved = observer.get(LiveRunRecord, run_id)
        assert saved is not None
        return (
            saved.status,
            saved.worker_id,
            saved.worker_heartbeat_at,
            saved.lease_expires_at,
            saved.stop_requested_at,
            saved.control_version,
            saved.fence_token,
            saved.recovery_attempts,
            saved.recovery_last_attempt_at,
            saved.recovery_not_before,
            saved.recovery_last_error,
        )


class DeleteEventsBeforeClaimSessionLiveStore(SessionLiveStore):
    def _delete_events(self, run_id: str) -> None:
        with self.session_factory() as db:
            db.execute(delete(LiveEventRecord).where(LiveEventRecord.run_id == run_id))
            db.commit()

    def acquire_lease(self, run_id: str, **kwargs):
        self._delete_events(run_id)
        return super().acquire_lease(run_id, **kwargs)

    def acquire_recovery_lease(self, run_id: str, **kwargs):
        self._delete_events(run_id)
        return super().acquire_recovery_lease(run_id, **kwargs)


class MutateEventsBeforeClaimSessionLiveStore(SessionLiveStore):
    def __init__(self, session_factory, *, mutation: str) -> None:
        super().__init__(session_factory)
        self.mutation = mutation

    def _mutate_events(self, run_id: str) -> None:
        with self.session_factory() as db:
            run = db.get(LiveRunRecord, run_id)
            assert run is not None
            if self.mutation == "append":
                db.add(
                    LiveEventRecord(
                        run_id=run_id,
                        event_id=3,
                        session_id=run.session_id,
                        type="phase_started",
                        phase="day",
                        payload={"external": True},
                    )
                )
            else:
                event = db.get(LiveEventRecord, (run_id, 2))
                assert event is not None
                event.payload = {"flag": 1}
                flag_modified(event, "payload")
            db.commit()

    def acquire_lease(self, run_id: str, **kwargs):
        self._mutate_events(run_id)
        return super().acquire_lease(run_id, **kwargs)

    def acquire_recovery_lease(self, run_id: str, **kwargs):
        self._mutate_events(run_id)
        return super().acquire_recovery_lease(run_id, **kwargs)


def test_session_store_read_boundaries_reject_a_zero_event_active_run(
    db_session: Session,
) -> None:
    record = seed_incomplete_live_run(db_session)
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(live_store=SessionLiveStore(session_factory))

    assert registry.try_get_active_run_for_session(record.session_id) is None
    assert registry.try_get_run(record.run_id) is None
    assert registry._runs == {}


def test_stale_claim_rejects_a_zero_event_run_without_mutating_ownership(
    db_session: Session,
) -> None:
    record = seed_incomplete_live_run(db_session)
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-recovery",
    )

    claimed = registry.try_claim_stale_run(record.run_id)

    assert claimed is None
    assert registry._runs == {}
    with session_factory() as observer:
        saved = observer.get(LiveRunRecord, record.run_id)
    assert saved is not None
    assert saved.worker_id == "worker-incomplete-owner"
    assert saved.fence_token == 4
    assert saved.control_version == 2
    assert saved.recovery_attempts == 0


def test_orphan_claim_rejects_a_zero_event_run_without_mutating_recovery_state(
    db_session: Session,
) -> None:
    record = seed_incomplete_live_run(db_session, recovery_attempts=1)
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-reaper",
    )
    now = datetime.now(tz=UTC)

    claimed = registry.try_claim_orphan(
        RunRecoveryCandidate(
            run_id=record.run_id,
            session_id=record.session_id,
            recovery_attempts=1,
        ),
        stale_before=(now - timedelta(seconds=1)).isoformat(),
        recovery_not_before=(now + timedelta(seconds=30)).isoformat(),
        max_attempts=3,
    )

    assert claimed is None
    assert registry._runs == {}
    with session_factory() as observer:
        saved = observer.get(LiveRunRecord, record.run_id)
    assert saved is not None
    assert saved.worker_id == "worker-incomplete-owner"
    assert saved.fence_token == 4
    assert saved.control_version == 2
    assert saved.recovery_attempts == 1
    assert saved.recovery_last_attempt_at is None

    background_starts: list[str] = []
    result = run_next_orphan_recovery(
        session_factory,
        registry,
        stale_grace_seconds=0,
        backoff_seconds=30,
        max_attempts=3,
        execute_recovery=lambda run, _registry: background_starts.append(run.run_id),
    )
    assert result is None
    assert background_starts == []


def test_stale_claim_rechecks_events_atomically_after_prevalidation(
    db_session: Session,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-stale-owner",
    )
    run = owner.create_run(
        session_id="game_atomic_stale",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)
    with session_factory() as db:
        saved = db.get(LiveRunRecord, run.run_id)
        assert saved is not None
        saved.worker_heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=2)
        saved.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        db.commit()
    before = live_run_claim_state(session_factory, run.run_id)
    claimant = LiveRunRegistry(
        live_store=DeleteEventsBeforeClaimSessionLiveStore(session_factory),
        worker_id="worker-stale-claimant",
    )

    claimed = claimant.try_claim_stale_run(run.run_id)

    assert claimed is None
    assert claimant._runs == {}
    assert live_run_claim_state(session_factory, run.run_id) == before
    with session_factory() as observer:
        assert (
            observer.query(LiveEventRecord).filter(LiveEventRecord.run_id == run.run_id).count()
            == 0
        )


def test_orphan_claim_rechecks_events_atomically_after_prevalidation(
    db_session: Session,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-orphan-owner",
    )
    run = owner.create_run(
        session_id="game_atomic_orphan",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)
    with session_factory() as db:
        saved = db.get(LiveRunRecord, run.run_id)
        assert saved is not None
        saved.worker_heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=2)
        saved.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        db.commit()
    before = live_run_claim_state(session_factory, run.run_id)
    claimant = LiveRunRegistry(
        live_store=DeleteEventsBeforeClaimSessionLiveStore(session_factory),
        worker_id="worker-orphan-claimant",
    )
    now = datetime.now(tz=UTC)

    claimed = claimant.try_claim_orphan(
        RunRecoveryCandidate(
            run_id=run.run_id,
            session_id=run.session_id,
            recovery_attempts=0,
        ),
        stale_before=(now - timedelta(seconds=1)).isoformat(),
        recovery_not_before=(now + timedelta(seconds=30)).isoformat(),
        max_attempts=3,
    )

    assert claimed is None
    assert claimant._runs == {}
    assert live_run_claim_state(session_factory, run.run_id) == before
    with session_factory() as observer:
        assert (
            observer.query(LiveEventRecord).filter(LiveEventRecord.run_id == run.run_id).count()
            == 0
        )


@pytest.mark.parametrize("claim_kind", ["stale", "orphan"])
@pytest.mark.parametrize("mutation", ["append", "update"])
def test_claim_rejects_a_structurally_valid_stream_changed_after_prevalidation(
    db_session: Session,
    claim_kind: str,
    mutation: str,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-stream-owner",
    )
    run = owner.create_run(
        session_id="game_expected_stream",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)
    with session_factory() as db:
        saved = db.get(LiveRunRecord, run.run_id)
        assert saved is not None
        saved.worker_heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=2)
        saved.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        if mutation == "update":
            event = db.get(LiveEventRecord, (run.run_id, 2))
            assert event is not None
            event.payload = {"flag": True}
            flag_modified(event, "payload")
        db.commit()
    before = live_run_claim_state(session_factory, run.run_id)
    claimant = LiveRunRegistry(
        live_store=MutateEventsBeforeClaimSessionLiveStore(
            session_factory,
            mutation=mutation,
        ),
        worker_id="worker-stream-claimant",
    )

    if claim_kind == "stale":
        claimed = claimant.try_claim_stale_run(run.run_id)
    else:
        now = datetime.now(tz=UTC)
        claimed = claimant.try_claim_orphan(
            RunRecoveryCandidate(
                run_id=run.run_id,
                session_id=run.session_id,
                recovery_attempts=0,
            ),
            stale_before=(now - timedelta(seconds=1)).isoformat(),
            recovery_not_before=(now + timedelta(seconds=30)).isoformat(),
            max_attempts=3,
        )

    assert claimed is None
    assert claimant._runs == {}
    assert live_run_claim_state(session_factory, run.run_id) == before
    with session_factory() as observer:
        events = (
            observer.query(LiveEventRecord)
            .filter(LiveEventRecord.run_id == run.run_id)
            .order_by(LiveEventRecord.event_id)
            .all()
        )
    if mutation == "append":
        assert [event.event_id for event in events] == [1, 2, 3]
    else:
        assert [event.event_id for event in events] == [1, 2]
        assert events[1].payload == {"flag": 1}
        assert type(events[1].payload["flag"]) is int


def test_live_store_round_trips_pinned_rule_metadata_exactly(db_session: Session) -> None:
    snapshot = pinned_rule_snapshot()
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set_revision_id="revision-2",
        rule_set_revision_no=2,
        rule_set_content_hash="a" * 64,
        rule_set=snapshot,
    )
    store = DatabaseLiveStore(db_session)

    store.save_run(run)
    loaded = store.load_run(run.run_id)

    assert loaded is not None
    assert loaded.rule_set_revision_id == "revision-2"
    assert loaded.rule_set_revision_no == 2
    assert loaded.rule_set_content_hash == "a" * 64
    assert loaded.rule_set == snapshot
    assert loaded.rule_set is not run.rule_set


def test_stage_new_run_flushes_run_and_real_initial_event_without_committing(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    run = registry.prepare_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    store = DatabaseLiveStore(db_session)
    commit_calls: list[None] = []

    def reject_commit() -> None:
        commit_calls.append(None)
        raise AssertionError("stage_new_run must not commit")

    monkeypatch.setattr(db_session, "commit", reject_commit)

    store.stage_new_run(run)

    saved_run = db_session.get(LiveRunRecord, run.run_id)
    saved_events = (
        db_session.query(LiveEventRecord).filter(LiveEventRecord.run_id == run.run_id).all()
    )
    assert saved_run is not None
    assert saved_run.rule_set == run.rule_set
    assert saved_run.player_configs == run.player_configs
    assert len(saved_events) == 1
    assert saved_events[0].event_id == run.events[0].id
    assert saved_events[0].type == "run_created"
    assert saved_events[0].payload == run.events[0].payload
    assert commit_calls == []

    db_session.rollback()
    assert db_session.get(LiveRunRecord, run.run_id) is None
    assert (
        db_session.query(LiveEventRecord).filter(LiveEventRecord.run_id == run.run_id).count() == 0
    )


def test_stage_new_run_rejects_mutated_prepared_run_before_database_access(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = LiveRunRegistry().prepare_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    run.status = "completed"
    run.completed_at = datetime.now(tz=UTC).isoformat()

    def reject_database_access(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("invalid prepared runs must fail before database access")

    monkeypatch.setattr(db_session, "get", reject_database_access)

    with pytest.raises(ValueError, match="fresh prepared run"):
        DatabaseLiveStore(db_session).stage_new_run(run)


def test_save_new_run_stages_and_commits_the_run_and_initial_event_once(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = LiveRunRegistry().prepare_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    store = DatabaseLiveStore(db_session)
    original_commit = db_session.commit
    commit_calls = 0

    def tracking_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        original_commit()

    monkeypatch.setattr(db_session, "commit", tracking_commit)

    store.save_new_run(run)

    assert commit_calls == 1
    assert db_session.get(LiveRunRecord, run.run_id) is not None
    events = db_session.query(LiveEventRecord).filter_by(run_id=run.run_id).all()
    assert len(events) == 1
    assert events[0].event_id == 1
    assert events[0].type == "run_created"


def test_save_new_run_rolls_back_when_initial_event_staging_fails(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = LiveRunRegistry().prepare_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    store = DatabaseLiveStore(db_session)
    original_stage = store.stage_new_run

    def fail_after_staging(staged_run) -> None:
        original_stage(staged_run)
        raise RuntimeError("initial event write failed")

    monkeypatch.setattr(store, "stage_new_run", fail_after_staging)

    with pytest.raises(RuntimeError, match="initial event write failed"):
        store.save_new_run(run)

    assert db_session.get(LiveRunRecord, run.run_id) is None
    assert db_session.query(LiveEventRecord).filter_by(run_id=run.run_id).count() == 0


def test_save_new_run_rolls_back_when_commit_fails(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = LiveRunRegistry().prepare_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    store = DatabaseLiveStore(db_session)
    original_rollback = db_session.rollback
    rollback_calls = 0

    def fail_commit() -> None:
        raise RuntimeError("commit failed")

    def tracking_rollback() -> None:
        nonlocal rollback_calls
        rollback_calls += 1
        original_rollback()

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", tracking_rollback)

    with pytest.raises(RuntimeError, match="commit failed"):
        store.save_new_run(run)

    assert rollback_calls == 1
    assert db_session.get(LiveRunRecord, run.run_id) is None
    assert db_session.query(LiveEventRecord).filter_by(run_id=run.run_id).count() == 0


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL_URL"),
    reason="requires an explicitly disposable PostgreSQL URL",
)
def test_two_registries_converge_on_one_complete_database_winner() -> None:
    database_url = os.environ["TEST_POSTGRESQL_URL"]
    schema = f"task3_atomic_create_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_engine(
        database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    ScopedSession = sessionmaker(bind=scoped_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(scoped_engine)
    first_reads = threading.Barrier(2)

    class FirstReadBarrierStore(SessionLiveStore):
        def __init__(self) -> None:
            super().__init__(ScopedSession)
            self._read_lock = threading.Lock()
            self._first_read = True
            self.attempted_run_id: str | None = None

        def active_run_for_session(self, session_id: str):
            observed = super().active_run_for_session(session_id)
            with self._read_lock:
                wait_for_peer = self._first_read
                self._first_read = False
            if wait_for_peer:
                assert observed is None
                first_reads.wait(timeout=5)
            return observed

        def save_new_run(self, run) -> None:
            self.attempted_run_id = run.run_id
            super().save_new_run(run)

    stores = [FirstReadBarrierStore(), FirstReadBarrierStore()]
    registries = [
        LiveRunRegistry(live_store=stores[0], worker_id="worker-a"),
        LiveRunRegistry(live_store=stores[1], worker_id="worker-b"),
    ]

    def create_or_get(registry: LiveRunRegistry):
        return registry.get_or_create_active_run(
            session_id="game_atomic_create",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create_or_get, registries))

        assert len({run.run_id for run, _created in results}) == 1
        assert sorted(created for _run, created in results) == [False, True]
        assert all(run.event_count == 1 for run, _created in results)
        assert all(run.next_event_id == 2 for run, _created in results)
        winner_id = results[0][0].run_id
        for store, (_run, created) in zip(stores, results, strict=True):
            assert store.attempted_run_id is not None
            if created:
                assert store.attempted_run_id == winner_id
            else:
                assert store.attempted_run_id != winner_id
        with ScopedSession() as observer:
            saved_runs = observer.query(LiveRunRecord).all()
            saved_events = observer.query(LiveEventRecord).all()
        assert len(saved_runs) == 1
        assert len(saved_events) == 1
        assert saved_events[0].run_id == saved_runs[0].run_id
        assert saved_events[0].event_id == 1
        assert saved_events[0].type == "run_created"
    finally:
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL_URL"),
    reason="requires an explicitly disposable PostgreSQL URL",
)
def test_stale_claim_waits_for_event_lock_then_rejects_a_deleted_stream() -> None:
    database_url = os.environ["TEST_POSTGRESQL_URL"]
    schema = f"task3_atomic_claim_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_engine(
        database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    ScopedSession = sessionmaker(bind=scoped_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(scoped_engine)
    claim_entered = threading.Event()
    claim_pid: list[int] = []
    claim_results: list[object] = []
    errors: list[BaseException] = []

    class ObservableClaimStore(SessionLiveStore):
        def acquire_lease(self, run_id: str, **kwargs):
            db = self.session_factory()
            try:
                pid = db.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                claim_pid.append(pid)
                claim_entered.set()
                return DatabaseLiveStore(db).acquire_lease(run_id, **kwargs)
            finally:
                db.close()

    try:
        owner = LiveRunRegistry(
            live_store=SessionLiveStore(ScopedSession),
            worker_id="worker-pg-owner",
        )
        run = owner.create_run(
            session_id="game_atomic_claim",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
        )
        owner.mark_running(run.run_id)
        with ScopedSession() as db:
            saved = db.get(LiveRunRecord, run.run_id)
            assert saved is not None
            saved.worker_heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=2)
            saved.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
            db.commit()
        before = live_run_claim_state(ScopedSession, run.run_id)
        claimant = LiveRunRegistry(
            live_store=ObservableClaimStore(ScopedSession),
            worker_id="worker-pg-claimant",
        )
        modifier = ScopedSession()
        claim_thread: threading.Thread | None = None
        try:
            event = modifier.scalar(
                select(LiveEventRecord)
                .where(
                    LiveEventRecord.run_id == run.run_id,
                    LiveEventRecord.event_id == 1,
                )
                .with_for_update()
            )
            assert event is not None
            modifier.delete(event)
            modifier.flush()

            def claim() -> None:
                try:
                    claim_results.append(claimant.try_claim_stale_run(run.run_id))
                except BaseException as exc:
                    errors.append(exc)
                    claim_entered.set()

            claim_thread = threading.Thread(target=claim)
            claim_thread.start()
            assert claim_entered.wait(timeout=5)
            assert claim_pid

            deadline = time.monotonic() + 5
            observed_lock_wait = False
            while time.monotonic() < deadline:
                with admin_engine.connect() as observer:
                    activity = observer.execute(
                        text(
                            "SELECT wait_event_type, query FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": claim_pid[0]},
                    ).one_or_none()
                if activity is not None and activity.wait_event_type == "Lock":
                    blocked_query = activity.query.lower()
                    assert "live_events" in blocked_query
                    assert "for update" in blocked_query
                    observed_lock_wait = True
                    break
                time.sleep(0.01)
            assert observed_lock_wait
            assert claim_results == []
            assert claimant._runs == {}

            modifier.commit()
            claim_thread.join(timeout=5)
            assert not claim_thread.is_alive()
        finally:
            modifier.rollback()
            modifier.close()
            if claim_thread is not None:
                claim_thread.join(timeout=5)

        assert errors == []
        assert claim_results == [None]
        assert claimant._runs == {}
        assert live_run_claim_state(ScopedSession, run.run_id) == before
        with ScopedSession() as observer:
            remaining_event_ids = [
                event.event_id
                for event in observer.query(LiveEventRecord)
                .filter(LiveEventRecord.run_id == run.run_id)
                .order_by(LiveEventRecord.event_id)
            ]
        assert remaining_event_ids == [2]
    finally:
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.parametrize(
    ("claim_kind", "mutation"),
    [("stale", "append"), ("orphan", "update")],
)
@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL_URL"),
    reason="requires an explicitly disposable PostgreSQL URL",
)
def test_claim_waits_for_locked_structurally_valid_stream_change(
    claim_kind: str,
    mutation: str,
) -> None:
    database_url = os.environ["TEST_POSTGRESQL_URL"]
    schema = f"task3_expected_stream_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_engine(
        database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    ScopedSession = sessionmaker(bind=scoped_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(scoped_engine)
    claim_entered = threading.Event()
    claim_pid: list[int] = []
    claim_results: list[object] = []
    errors: list[BaseException] = []

    class ObservableClaimStore(SessionLiveStore):
        def _claim(self, method_name: str, run_id: str, **kwargs):
            db = self.session_factory()
            try:
                pid = db.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                claim_pid.append(pid)
                claim_entered.set()
                method = getattr(DatabaseLiveStore(db), method_name)
                return method(run_id, **kwargs)
            finally:
                db.close()

        def acquire_lease(self, run_id: str, **kwargs):
            return self._claim("acquire_lease", run_id, **kwargs)

        def acquire_recovery_lease(self, run_id: str, **kwargs):
            return self._claim("acquire_recovery_lease", run_id, **kwargs)

    try:
        owner = LiveRunRegistry(
            live_store=SessionLiveStore(ScopedSession),
            worker_id="worker-pg-stream-owner",
        )
        run = owner.create_run(
            session_id="game_pg_expected_stream",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
        )
        owner.mark_running(run.run_id)
        with ScopedSession() as db:
            saved = db.get(LiveRunRecord, run.run_id)
            assert saved is not None
            saved.worker_heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=2)
            saved.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
            if mutation == "update":
                event = db.get(LiveEventRecord, (run.run_id, 2))
                assert event is not None
                event.payload = {"flag": True}
                flag_modified(event, "payload")
            db.commit()
        before = live_run_claim_state(ScopedSession, run.run_id)
        claimant = LiveRunRegistry(
            live_store=ObservableClaimStore(ScopedSession),
            worker_id="worker-pg-stream-claimant",
        )
        modifier = ScopedSession()
        claim_thread: threading.Thread | None = None
        try:
            locked_event = modifier.scalar(
                select(LiveEventRecord)
                .where(
                    LiveEventRecord.run_id == run.run_id,
                    LiveEventRecord.event_id == 1,
                )
                .with_for_update()
            )
            assert locked_event is not None
            if mutation == "append":
                modifier.add(
                    LiveEventRecord(
                        run_id=run.run_id,
                        event_id=3,
                        session_id=run.session_id,
                        type="phase_started",
                        phase="day",
                        payload={"external": True},
                    )
                )
            else:
                changed_event = modifier.get(LiveEventRecord, (run.run_id, 2))
                assert changed_event is not None
                changed_event.payload = {"flag": 1}
                flag_modified(changed_event, "payload")
            modifier.flush()

            def claim() -> None:
                try:
                    if claim_kind == "stale":
                        result = claimant.try_claim_stale_run(run.run_id)
                    else:
                        now = datetime.now(tz=UTC)
                        result = claimant.try_claim_orphan(
                            RunRecoveryCandidate(
                                run_id=run.run_id,
                                session_id=run.session_id,
                                recovery_attempts=0,
                            ),
                            stale_before=(now - timedelta(seconds=1)).isoformat(),
                            recovery_not_before=(now + timedelta(seconds=30)).isoformat(),
                            max_attempts=3,
                        )
                    claim_results.append(result)
                except BaseException as exc:
                    errors.append(exc)
                    claim_entered.set()

            claim_thread = threading.Thread(target=claim)
            claim_thread.start()
            assert claim_entered.wait(timeout=5)
            assert claim_pid

            deadline = time.monotonic() + 5
            observed_lock_wait = False
            while time.monotonic() < deadline:
                with admin_engine.connect() as observer:
                    activity = observer.execute(
                        text(
                            "SELECT wait_event_type, query FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": claim_pid[0]},
                    ).one_or_none()
                if activity is not None and activity.wait_event_type == "Lock":
                    blocked_query = activity.query.lower()
                    expected_relation = "live_runs" if mutation == "append" else "live_events"
                    assert expected_relation in blocked_query
                    if mutation == "append":
                        assert "lease_expires_at" in blocked_query
                    else:
                        assert "for update" in blocked_query
                    observed_lock_wait = True
                    break
                time.sleep(0.01)
            assert observed_lock_wait
            assert claim_results == []
            assert claimant._runs == {}

            modifier.commit()
            claim_thread.join(timeout=5)
            assert not claim_thread.is_alive()
        finally:
            modifier.rollback()
            modifier.close()
            if claim_thread is not None:
                claim_thread.join(timeout=5)

        assert errors == []
        assert claim_results == [None]
        assert claimant._runs == {}
        assert live_run_claim_state(ScopedSession, run.run_id) == before
        with ScopedSession() as observer:
            events = (
                observer.query(LiveEventRecord)
                .filter(LiveEventRecord.run_id == run.run_id)
                .order_by(LiveEventRecord.event_id)
                .all()
            )
        if mutation == "append":
            assert [event.event_id for event in events] == [1, 2, 3]
        else:
            assert [event.event_id for event in events] == [1, 2]
            assert events[1].payload == {"flag": 1}
            assert type(events[1].payload["flag"]) is int
    finally:
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL_URL"),
    reason="requires an explicitly disposable PostgreSQL URL",
)
def test_activation_waits_for_event_lock_then_rejects_a_changed_expected_stream() -> None:
    database_url = os.environ["TEST_POSTGRESQL_URL"]
    schema = f"task3_atomic_activation_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_engine(
        database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    ScopedSession = sessionmaker(bind=scoped_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(scoped_engine)
    activation_entered = threading.Event()
    activation_pid: list[int] = []
    results: list[LiveEvent] = []
    errors: list[BaseException] = []

    class ObservableActivationStore(SessionLiveStore):
        def activate_run(self, run_id: str, **kwargs) -> None:
            db = self.session_factory()
            try:
                pid = db.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                activation_pid.append(pid)
                activation_entered.set()
                DatabaseLiveStore(db).activate_run(run_id, **kwargs)
            finally:
                db.close()

    try:
        store = ObservableActivationStore(ScopedSession)
        registry = LiveRunRegistry(
            live_store=store,
            worker_id="worker-pg-activation",
            lease_seconds=30,
        )
        run = registry.create_run(
            session_id="game_pg_atomic_activation",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
        )
        heartbeat_at = datetime.now(tz=UTC)
        lease_state = store.acquire_lease(
            run.run_id,
            expected_events=tuple(run.events),
            worker_id=registry.worker_id,
            heartbeat_at=heartbeat_at.isoformat(),
            lease_expires_at=(heartbeat_at + timedelta(seconds=30)).isoformat(),
        )
        assert lease_state is not None
        registry._apply_lease_state_locked(run, lease_state)
        modifier = ScopedSession()
        activation_thread: threading.Thread | None = None
        try:
            event = modifier.scalar(
                select(LiveEventRecord)
                .where(
                    LiveEventRecord.run_id == run.run_id,
                    LiveEventRecord.event_id == 1,
                )
                .with_for_update()
            )
            assert event is not None
            event.action = "external-update"
            modifier.flush()

            def activate() -> None:
                try:
                    results.append(registry.mark_running(run.run_id))
                except BaseException as exc:
                    errors.append(exc)
                    activation_entered.set()

            activation_thread = threading.Thread(target=activate)
            activation_thread.start()
            assert activation_entered.wait(timeout=5)
            assert activation_pid

            deadline = time.monotonic() + 5
            observed_lock_wait = False
            while time.monotonic() < deadline:
                with admin_engine.connect() as observer:
                    activity = observer.execute(
                        text(
                            "SELECT wait_event_type, query FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": activation_pid[0]},
                    ).one_or_none()
                if activity is not None and activity.wait_event_type == "Lock":
                    blocked_query = activity.query.lower()
                    assert "live_events" in blocked_query
                    assert "for update" in blocked_query
                    observed_lock_wait = True
                    break
                time.sleep(0.01)
            assert observed_lock_wait
            assert results == []
            assert errors == []

            modifier.commit()
            activation_thread.join(timeout=5)
            assert not activation_thread.is_alive()
        finally:
            modifier.rollback()
            modifier.close()
            if activation_thread is not None:
                activation_thread.join(timeout=5)

        assert results == []
        assert len(errors) == 1
        assert isinstance(errors[0], RunLeaseUnavailable)
        assert run.status == "queued"
        assert run.started_at is None
        assert run.fence_token == 1
        assert run.lease_lost is True
        assert run.next_event_id == 2
        assert [(event.id, event.type) for event in run.events] == [(1, "run_created")]
        assert registry._activation_events == {}
        with ScopedSession() as observer:
            saved = observer.get(LiveRunRecord, run.run_id)
            events = list(
                observer.scalars(
                    select(LiveEventRecord)
                    .where(LiveEventRecord.run_id == run.run_id)
                    .order_by(LiveEventRecord.event_id)
                )
            )
        assert saved is not None
        assert saved.status == "queued"
        assert saved.worker_id == registry.worker_id
        assert saved.fence_token == 1
        assert [(event.event_id, event.type, event.action) for event in events] == [
            (1, "run_created", "external-update")
        ]
    finally:
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL_URL"),
    reason="requires an explicitly disposable PostgreSQL URL",
)
def test_activation_ack_verifier_locks_run_then_events_before_stop_control_update() -> None:
    database_url = os.environ["TEST_POSTGRESQL_URL"]
    schema = f"task3_activation_ack_lock_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_engine(
        database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    armed = False
    acknowledgement_lost = False
    verifier_context = threading.local()
    verifier_run_locked = threading.Event()
    release_verifier = threading.Event()
    verifier_statements: list[str] = []

    class AckLostActivationSession(Session):
        saw_activation = False

        def flush(self, objects=None) -> None:
            if armed and any(
                isinstance(item, LiveEventRecord) and item.type in {"run_started", "run_recovered"}
                for item in self.new
            ):
                self.saw_activation = True
            super().flush(objects)

        def commit(self) -> None:
            nonlocal acknowledgement_lost
            super().commit()
            if armed and self.saw_activation and not acknowledgement_lost:
                acknowledgement_lost = True
                raise RuntimeError("activation commit acknowledgement lost")

    ScopedSession = sessionmaker(
        bind=scoped_engine,
        class_=AckLostActivationSession,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(scoped_engine)

    class ObservableAckVerifierStore(SessionLiveStore):
        def __init__(self) -> None:
            super().__init__(ScopedSession)
            self.activation_verification_calls = 0

        def activation_was_committed(self, expected_state):
            self.activation_verification_calls += 1
            verifier_context.active = True
            try:
                return super().activation_was_committed(expected_state)
            finally:
                verifier_context.active = False

    def observe_verifier_statement(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if not getattr(verifier_context, "active", False):
            return
        verifier_statements.append(statement)
        normalized = statement.lower()
        if "from live_runs" in normalized and "for update" in normalized:
            verifier_run_locked.set()
            assert release_verifier.wait(timeout=5)

    sqlalchemy_event.listen(scoped_engine, "after_cursor_execute", observe_verifier_statement)
    activation_results: list[LiveEvent] = []
    activation_errors: list[BaseException] = []
    mutator_errors: list[BaseException] = []
    mutator_pid: list[int] = []
    mutator_entered = threading.Event()
    mutator_committed = threading.Event()
    activation_thread: threading.Thread | None = None
    mutator_thread: threading.Thread | None = None
    try:
        store = ObservableAckVerifierStore()
        registry = LiveRunRegistry(
            live_store=store,
            worker_id="worker-pg-activation-ack",
            lease_seconds=30,
        )
        run = registry.create_run(
            session_id="game_pg_activation_ack_lock",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
        )
        armed = True

        def activate() -> None:
            try:
                activation_results.append(registry.mark_running(run.run_id))
            except BaseException as exc:
                activation_errors.append(exc)
                verifier_run_locked.set()

        activation_thread = threading.Thread(target=activate)
        activation_thread.start()
        assert verifier_run_locked.wait(timeout=5)

        def mutate_stop_control() -> None:
            try:
                with ScopedSession() as mutator:
                    pid = mutator.scalar(text("SELECT pg_backend_pid()"))
                    assert isinstance(pid, int)
                    mutator_pid.append(pid)
                    mutator_entered.set()
                    mutator.execute(
                        update(LiveRunRecord)
                        .where(LiveRunRecord.run_id == run.run_id)
                        .values(
                            stop_requested_at=datetime.now(tz=UTC),
                            control_version=LiveRunRecord.control_version + 1,
                        )
                    )
                    mutator.commit()
                    mutator_committed.set()
            except BaseException as exc:
                mutator_errors.append(exc)
                mutator_entered.set()

        mutator_thread = threading.Thread(target=mutate_stop_control)
        mutator_thread.start()
        assert mutator_entered.wait(timeout=5)
        assert mutator_pid

        deadline = time.monotonic() + 5
        observed_lock_wait = False
        while time.monotonic() < deadline:
            with admin_engine.connect() as observer:
                activity = observer.execute(
                    text("SELECT wait_event_type, query FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": mutator_pid[0]},
                ).one_or_none()
            if activity is not None and activity.wait_event_type == "Lock":
                blocked_query = activity.query.lower()
                assert "update live_runs" in blocked_query
                observed_lock_wait = True
                break
            time.sleep(0.01)
        assert observed_lock_wait
        assert activation_results == []
        assert activation_errors == []
        assert mutator_committed.is_set() is False

        release_verifier.set()
        activation_thread.join(timeout=5)
        mutator_thread.join(timeout=5)
        assert not activation_thread.is_alive()
        assert not mutator_thread.is_alive()

        assert acknowledgement_lost is True
        assert store.activation_verification_calls == 1
        assert activation_errors == []
        assert mutator_errors == []
        assert len(activation_results) == 1
        assert activation_results[0] is run.events[1]
        assert mutator_committed.is_set() is True
        locked_statements = [
            statement.lower()
            for statement in verifier_statements
            if "for update" in statement.lower()
        ]
        assert len(locked_statements) == 2
        assert "from live_runs" in locked_statements[0]
        assert "from live_events" in locked_statements[1]
        assert all(
            statement.lstrip().lower().startswith("select") for statement in verifier_statements
        )
        with ScopedSession() as observer:
            saved = observer.get(LiveRunRecord, run.run_id)
            events = list(
                observer.scalars(
                    select(LiveEventRecord)
                    .where(LiveEventRecord.run_id == run.run_id)
                    .order_by(LiveEventRecord.event_id)
                )
            )
        assert saved is not None
        assert saved.status == "running"
        assert saved.stop_requested_at is not None
        assert saved.control_version == 1
        assert [(event.event_id, event.type) for event in events] == [
            (1, "run_created"),
            (2, "run_started"),
        ]
    finally:
        release_verifier.set()
        if activation_thread is not None:
            activation_thread.join(timeout=5)
        if mutator_thread is not None:
            mutator_thread.join(timeout=5)
        sqlalchemy_event.remove(scoped_engine, "after_cursor_execute", observe_verifier_statement)
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_live_store_loads_backfilled_pinned_scalars_with_legacy_snapshot(
    db_session: Session,
) -> None:
    legacy_snapshot = {"id": "classic_8", "name": "legacy"}
    run = LiveRunRegistry().create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set_revision_id="revision-2",
        rule_set_revision_no=2,
        rule_set_content_hash="a" * 64,
        rule_set=legacy_snapshot,
    )
    store = DatabaseLiveStore(db_session)

    store.save_run(run)
    loaded = store.load_run(run.run_id)

    assert loaded is not None
    assert loaded.rule_set_revision_id == "revision-2"
    assert loaded.rule_set_revision_no == 2
    assert loaded.rule_set_content_hash == "a" * 64
    assert loaded.rule_set == legacy_snapshot


def test_live_store_loads_legacy_null_rule_snapshot_as_an_empty_snapshot(
    db_session: Session,
) -> None:
    db_session.add(
        LiveRunRecord(
            run_id="run_123456789abc",
            session_id="game_1200abcd",
            status="completed",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
            rule_set_id="classic_8",
            rule_set=None,
        )
    )
    db_session.commit()

    loaded = DatabaseLiveStore(db_session).load_run("run_123456789abc")

    assert loaded is not None
    assert loaded.rule_set_revision_id is None
    assert loaded.rule_set_revision_no is None
    assert loaded.rule_set_content_hash is None
    assert loaded.rule_set == {}


@pytest.mark.parametrize(
    "stored_rule_set",
    [[], "", False, 0],
    ids=("empty-list", "empty-string", "false", "zero"),
)
def test_live_store_rejects_non_null_falsy_rule_snapshots(
    db_session: Session,
    stored_rule_set: object,
) -> None:
    db_session.add(
        LiveRunRecord(
            run_id="run_123456789abc",
            session_id="game_1200abcd",
            status="completed",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
            rule_set_id="classic_8",
            rule_set=stored_rule_set,
        )
    )
    db_session.commit()

    with pytest.raises(ValueError, match="rule_set must be a dictionary"):
        DatabaseLiveStore(db_session).load_run("run_123456789abc")


def test_live_store_replaces_and_clears_pinned_rule_metadata_on_update(
    db_session: Session,
) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={"id": "classic_8", "name": "legacy"},
    )
    store = DatabaseLiveStore(db_session)
    store.save_run(run)

    run.rule_set_revision_id = "revision-2"
    run.rule_set_revision_no = 2
    run.rule_set_content_hash = "a" * 64
    run.rule_set = pinned_rule_snapshot()
    store.save_run(run)

    managed = db_session.get(LiveRunRecord, run.run_id)
    assert managed is not None
    assert managed.rule_set_revision_id == "revision-2"
    assert managed.rule_set_revision_no == 2
    assert managed.rule_set_content_hash == "a" * 64
    assert managed.rule_set == pinned_rule_snapshot()

    run.rule_set_revision_id = None
    run.rule_set_revision_no = None
    run.rule_set_content_hash = None
    run.rule_set = {"id": "classic_8", "name": "legacy again"}
    store.save_run(run)

    db_session.expire_all()
    legacy = db_session.get(LiveRunRecord, run.run_id)
    assert legacy is not None
    assert legacy.rule_set_revision_id is None
    assert legacy.rule_set_revision_no is None
    assert legacy.rule_set_content_hash is None
    assert legacy.rule_set == {"id": "classic_8", "name": "legacy again"}


def test_live_store_rejects_partial_pinned_rule_metadata_before_insert(
    db_session: Session,
) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    run.rule_set_revision_id = "revision-2"

    with pytest.raises(ValueError, match="all present or all absent"):
        DatabaseLiveStore(db_session).save_run(run)

    assert db_session.get(LiveRunRecord, run.run_id) is None


def test_live_store_rejects_loading_a_partial_pinned_rule_metadata_row(
    db_session: Session,
) -> None:
    db_session.add(
        LiveRunRecord(
            run_id="run_123456789abc",
            session_id="game_1200abcd",
            status="queued",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
            rule_set_id="classic_8",
            rule_set_revision_id="revision-2",
            rule_set={"id": "classic_8", "name": "legacy"},
        )
    )
    db_session.commit()

    with pytest.raises(ValueError, match="all present or all absent"):
        DatabaseLiveStore(db_session).load_run("run_123456789abc")


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
    store.append_event(event, worker_id=run.worker_id, fence_token=run.fence_token)
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
    store.append_event(first, worker_id=run.worker_id, fence_token=run.fence_token)
    store.append_event(second, worker_id=run.worker_id, fence_token=run.fence_token)

    assert [event.id for event in store.events_after(run.run_id, after_id=first.id)] == [second.id]


def test_live_store_returns_latest_eventful_playback_events_for_session(
    db_session: Session,
) -> None:
    first_registry = LiveRunRegistry()
    first_run = first_registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    first_event = first_registry.publish(first_run.run_id, "phase_started", phase="night")

    empty_registry = LiveRunRegistry()
    empty_run = empty_registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=8,
        max_rounds=8,
    )

    latest_registry = LiveRunRegistry()
    latest_run = latest_registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=9,
        max_rounds=8,
    )
    latest_event = latest_registry.publish(
        latest_run.run_id,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-1", "visible_text": "我不是狼", "is_public": True},
    )
    store = DatabaseLiveStore(db_session)

    first_run.status = "completed"
    empty_run.status = "completed"
    latest_run.status = "completed"
    store.save_run(first_run)
    store.append_event(
        first_event,
        worker_id=first_run.worker_id,
        fence_token=first_run.fence_token,
    )
    store.save_run(empty_run)
    store.save_run(latest_run)
    store.append_event(
        latest_event,
        worker_id=latest_run.worker_id,
        fence_token=latest_run.fence_token,
    )

    playback_events = store.playback_events_for_session("game_1200abcd")

    assert [event["id"] for event in playback_events] == [latest_event.id]
    assert {event["run_id"] for event in playback_events} == {"playback_game_1200abcd"}
    assert playback_events[-1]["payload"]["visible_text"] == "我不是狼"


def test_live_store_duplicate_event_raises_and_preserves_original(
    db_session: Session,
) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    event = registry.publish(
        run.run_id,
        "model_response_delta",
        payload={"visible_text": "original"},
    )
    duplicate = LiveEvent(
        id=event.id,
        type=event.type,
        run_id=event.run_id,
        session_id=event.session_id,
        created_at=event.created_at,
        payload={"visible_text": "overwritten"},
    )
    store = DatabaseLiveStore(db_session)

    store.save_run(run)
    store.append_event(event, worker_id=run.worker_id, fence_token=run.fence_token)
    with pytest.raises(IntegrityError):
        store.append_event(duplicate, worker_id=run.worker_id, fence_token=run.fence_token)

    loaded_events = store.events_after(run.run_id)
    assert [item.id for item in loaded_events] == [event.id]
    assert loaded_events[0].payload["visible_text"] == "original"


def test_live_store_rolls_back_duplicate_append_before_next_append(
    db_session: Session,
) -> None:
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
    duplicate = LiveEvent(
        id=first.id,
        type=first.type,
        run_id=first.run_id,
        session_id=first.session_id,
        created_at=first.created_at,
        phase="duplicate",
    )
    store = DatabaseLiveStore(db_session)

    store.save_run(run)
    store.append_event(first, worker_id=run.worker_id, fence_token=run.fence_token)
    with pytest.raises(IntegrityError):
        store.append_event(duplicate, worker_id=run.worker_id, fence_token=run.fence_token)
    store.append_event(second, worker_id=run.worker_id, fence_token=run.fence_token)

    assert [event.id for event in store.events_after(run.run_id)] == [first.id, second.id]


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


def test_live_run_stop_is_cooperative_and_persists_canceled_terminal_state(
    db_session: Session,
) -> None:
    registry = LiveRunRegistry(live_store=DatabaseLiveStore(db_session))
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    registry.mark_running(run.run_id)

    requested = registry.request_stop(run.run_id)

    assert requested.type == "run_stop_requested"
    assert registry.get_run(run.run_id).stop_requested_at is not None
    with pytest.raises(GameRunCanceled):
        EventSink(registry, run.run_id).publish("phase_started", phase="day")

    canceled = registry.mark_canceled(run.run_id)
    saved = db_session.get(LiveRunRecord, run.run_id)
    assert canceled.type == "game_canceled"
    assert saved is not None
    assert saved.status == "canceled"
    assert saved.stop_requested_at is not None
    assert saved.error is None


@pytest.mark.parametrize("failure_stage", ["status", "event"])
def test_session_store_activation_failure_rolls_back_and_retries_without_a_phantom(
    db_session: Session,
    failure_stage: str,
) -> None:
    failure = RuntimeError(f"injected activation {failure_stage} failure")
    armed = False
    injected = False

    class FailingActivationSession(Session):
        def flush(self, objects=None) -> None:
            nonlocal injected
            if armed and not injected:
                has_running_status = any(
                    isinstance(item, LiveRunRecord) and item.status == "running"
                    for item in self.dirty
                )
                has_activation_event = any(
                    isinstance(item, LiveEventRecord)
                    and item.type in {"run_started", "run_recovered"}
                    for item in self.new
                )
                if (failure_stage == "status" and has_running_status) or (
                    failure_stage == "event" and has_activation_event
                ):
                    injected = True
                    raise failure
            super().flush(objects)

    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        class_=FailingActivationSession,
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-activation-retry",
    )
    run = registry.create_run(
        session_id=f"game_activation_{failure_stage}_failure",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    subscriber = registry.subscribe(run.run_id, after_id=1)
    armed = True

    with pytest.raises(RuntimeError) as raised:
        registry.mark_running(run.run_id)

    assert raised.value is failure
    assert injected is True
    assert run.status == "queued"
    assert run.started_at is None
    assert run.fence_token == 1
    assert run.next_event_id == 2
    assert [(event.id, event.type) for event in run.events] == [(1, "run_created")]
    assert (run.run_id, run.fence_token) not in registry._activation_events
    assert subscriber.empty()
    with session_factory() as observer:
        saved = observer.get(LiveRunRecord, run.run_id)
        events = list(
            observer.scalars(
                select(LiveEventRecord)
                .where(LiveEventRecord.run_id == run.run_id)
                .order_by(LiveEventRecord.event_id)
            )
        )
        assert saved is not None
        assert saved.status == "queued"
        assert saved.started_at is None
        assert saved.worker_id == "worker-activation-retry"
        assert saved.fence_token == 1
        assert [(event.event_id, event.type) for event in events] == [(1, "run_created")]

    activation = registry.mark_running(run.run_id)
    repeated = registry.mark_running(run.run_id)

    assert activation is repeated is run.events[1]
    assert run.status == "running"
    assert run.started_at is not None
    assert run.fence_token == 1
    assert run.next_event_id == 3
    assert [(event.id, event.type) for event in run.events] == [
        (1, "run_created"),
        (2, "run_started"),
    ]
    assert subscriber.get_nowait() is activation
    assert subscriber.empty()
    with session_factory() as observer:
        saved = observer.get(LiveRunRecord, run.run_id)
        events = list(
            observer.scalars(
                select(LiveEventRecord)
                .where(LiveEventRecord.run_id == run.run_id)
                .order_by(LiveEventRecord.event_id)
            )
        )
        assert saved is not None
        assert saved.status == "running"
        assert saved.started_at is not None
        assert saved.fence_token == 1
        assert [(event.event_id, event.type) for event in events] == [
            (1, "run_created"),
            (2, "run_started"),
        ]


def test_session_store_recovers_an_exact_activation_after_commit_ack_loss(
    db_session: Session,
) -> None:
    failure = RuntimeError("activation commit acknowledgement lost")
    armed = False
    acknowledgement_lost = False

    class AckLostActivationSession(Session):
        saw_activation = False

        def flush(self, objects=None) -> None:
            if armed and any(
                isinstance(item, LiveEventRecord) and item.type in {"run_started", "run_recovered"}
                for item in self.new
            ):
                self.saw_activation = True
            super().flush(objects)

        def commit(self) -> None:
            nonlocal acknowledgement_lost
            super().commit()
            if armed and self.saw_activation and not acknowledgement_lost:
                acknowledgement_lost = True
                raise failure

    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        class_=AckLostActivationSession,
        autoflush=False,
        autocommit=False,
    )

    class ObservedSessionLiveStore(SessionLiveStore):
        def __init__(self) -> None:
            super().__init__(session_factory)
            self.load_run_calls = 0
            self.events_after_calls = 0
            self.activation_verification_calls = 0

        def load_run(self, run_id: str):
            self.load_run_calls += 1
            return super().load_run(run_id)

        def events_after(self, run_id: str, *, after_id=None):
            self.events_after_calls += 1
            return super().events_after(run_id, after_id=after_id)

        def activation_was_committed(self, expected_state):
            self.activation_verification_calls += 1
            return super().activation_was_committed(expected_state)

    store = ObservedSessionLiveStore()
    registry = LiveRunRegistry(live_store=store, worker_id="worker-activation-ack")
    run = registry.create_run(
        session_id="game_activation_ack_loss",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    subscriber = registry.subscribe(run.run_id, after_id=1)
    armed = True

    activation = registry.mark_running(run.run_id)
    repeated = registry.mark_running(run.run_id)

    assert acknowledgement_lost is True
    assert store.activation_verification_calls == 1
    assert store.load_run_calls == 0
    assert store.events_after_calls == 0
    assert activation is repeated is run.events[1]
    assert subscriber.get_nowait() is activation
    assert subscriber.empty()
    assert run.status == "running"
    assert run.fence_token == 1
    assert [(event.id, event.type) for event in run.events] == [
        (1, "run_created"),
        (2, "run_started"),
    ]
    with session_factory() as observer:
        saved = observer.get(LiveRunRecord, run.run_id)
        events = list(
            observer.scalars(
                select(LiveEventRecord)
                .where(LiveEventRecord.run_id == run.run_id)
                .order_by(LiveEventRecord.event_id)
            )
        )
        assert saved is not None
        assert saved.status == "running"
        assert saved.fence_token == 1
        assert [(event.event_id, event.type) for event in events] == [
            (1, "run_created"),
            (2, "run_started"),
        ]


@pytest.mark.parametrize("mutation", ["full-row", "expired-lease"])
def test_session_store_rejects_activation_ack_when_durable_run_state_changed(
    db_session: Session,
    mutation: str,
) -> None:
    failure = RuntimeError(f"activation {mutation} acknowledgement lost")
    armed = False
    acknowledgement_lost = False
    plain_session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )

    class MutatingAckLostActivationSession(Session):
        saw_activation = False

        def flush(self, objects=None) -> None:
            if armed and any(
                isinstance(item, LiveEventRecord) and item.type in {"run_started", "run_recovered"}
                for item in self.new
            ):
                self.saw_activation = True
            super().flush(objects)

        def commit(self) -> None:
            nonlocal acknowledgement_lost
            super().commit()
            if armed and self.saw_activation and not acknowledgement_lost:
                acknowledgement_lost = True
                with plain_session_factory() as mutator:
                    record = mutator.get(LiveRunRecord, run.run_id)
                    assert record is not None
                    if mutation == "full-row":
                        record.villager_model = "mutated-model"
                        record.control_version += 7
                        record.recovery_last_error = "mutated-recovery"
                        changed_rule_set = copy.deepcopy(record.rule_set)
                        assert changed_rule_set is not None
                        assert type(changed_rule_set["sheriff_enabled"]) is bool
                        changed_rule_set["sheriff_enabled"] = 0
                        changed_rule_set["roles"][0]["count"] = 2.0
                        record.rule_set = changed_rule_set
                        flag_modified(record, "rule_set")
                        record.player_configs = [{"seat": 1, "name": "durable-only-player"}]
                        flag_modified(record, "player_configs")
                    else:
                        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
                    mutator.commit()
                raise failure

    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        class_=MutatingAckLostActivationSession,
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id=f"worker-activation-{mutation}",
    )
    run = registry.create_run(
        session_id=f"game_activation_ack_{mutation}",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    subscriber = registry.subscribe(run.run_id, after_id=1)
    armed = True

    with pytest.raises(RuntimeError) as raised:
        registry.mark_running(run.run_id)

    assert raised.value is failure
    assert acknowledgement_lost is True
    assert run.status == "queued"
    assert run.started_at is None
    assert run.fence_token == 1
    assert run.next_event_id == 2
    assert [(event.id, event.type) for event in run.events] == [(1, "run_created")]
    assert (run.run_id, run.fence_token) not in registry._activation_events
    assert subscriber.empty()
    with plain_session_factory() as observer:
        saved = observer.get(LiveRunRecord, run.run_id)
        events = list(
            observer.scalars(
                select(LiveEventRecord)
                .where(LiveEventRecord.run_id == run.run_id)
                .order_by(LiveEventRecord.event_id)
            )
        )
        assert saved is not None
        assert saved.status == "running"
        if mutation == "full-row":
            assert saved.villager_model == "mutated-model"
            assert saved.control_version == 7
            assert type(saved.rule_set["sheriff_enabled"]) is int
            assert type(saved.rule_set["roles"][0]["count"]) is float
            assert saved.player_configs[0]["name"] == "durable-only-player"
        else:
            assert saved.lease_expires_at is not None
            assert saved.lease_expires_at <= datetime.now(tz=UTC).replace(tzinfo=None)
        assert [(event.event_id, event.type) for event in events] == [
            (1, "run_created"),
            (2, "run_started"),
        ]


def test_atomic_activation_ack_verifier_rejects_the_legacy_stop_control_read_seam(
    db_session: Session,
) -> None:
    failure = RuntimeError("activation acknowledgement lost across read seam")
    armed = False
    acknowledgement_lost = False
    plain_session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )

    class AckLostActivationSession(Session):
        saw_activation = False

        def flush(self, objects=None) -> None:
            if armed and any(
                isinstance(item, LiveEventRecord) and item.type in {"run_started", "run_recovered"}
                for item in self.new
            ):
                self.saw_activation = True
            super().flush(objects)

        def commit(self) -> None:
            nonlocal acknowledgement_lost
            super().commit()
            if armed and self.saw_activation and not acknowledgement_lost:
                acknowledgement_lost = True
                raise failure

    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        class_=AckLostActivationSession,
        autoflush=False,
        autocommit=False,
    )

    class StopControlReadSeamStore(SessionLiveStore):
        def __init__(self) -> None:
            super().__init__(session_factory)
            self.mutated = False
            self.load_run_calls = 0
            self.events_after_calls = 0
            self.activation_verification_calls = 0

        def _mutate_stop_control(self, run_id: str) -> None:
            if self.mutated:
                return
            self.mutated = True
            with plain_session_factory() as mutator:
                record = mutator.get(LiveRunRecord, run_id)
                assert record is not None
                record.stop_requested_at = datetime.now(tz=UTC)
                record.control_version += 1
                mutator.commit()

        def load_run(self, run_id: str):
            self.load_run_calls += 1
            stale = super().load_run(run_id)
            self._mutate_stop_control(run_id)
            return stale

        def events_after(self, run_id: str, *, after_id=None):
            self.events_after_calls += 1
            return super().events_after(run_id, after_id=after_id)

        def activation_was_committed(self, expected_state):
            self.activation_verification_calls += 1
            self._mutate_stop_control(expected_state.run_id)
            return super().activation_was_committed(expected_state)

    store = StopControlReadSeamStore()
    registry = LiveRunRegistry(live_store=store, worker_id="worker-activation-read-seam")
    run = registry.create_run(
        session_id="game_activation_ack_read_seam",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    subscriber = registry.subscribe(run.run_id, after_id=1)
    armed = True

    with pytest.raises(RuntimeError) as raised:
        registry.mark_running(run.run_id)

    assert raised.value is failure
    assert acknowledgement_lost is True
    assert store.mutated is True
    assert store.activation_verification_calls == 1
    assert store.load_run_calls == 0
    assert store.events_after_calls == 0
    assert run.status == "queued"
    assert run.stop_requested_at is None
    assert run.control_version == 0
    assert run.next_event_id == 2
    assert [(event.id, event.type) for event in run.events] == [(1, "run_created")]
    assert registry._activation_events == {}
    assert subscriber.empty()
    with plain_session_factory() as observer:
        saved = observer.get(LiveRunRecord, run.run_id)
        assert saved is not None
        assert saved.status == "running"
        assert saved.stop_requested_at is not None
        assert saved.control_version == 1


def test_session_store_recovery_activation_failure_retries_the_same_fence(
    db_session: Session,
) -> None:
    failure = RuntimeError("injected recovery activation event failure")
    armed = False
    injected = False

    class FailingRecoveryActivationSession(Session):
        def flush(self, objects=None) -> None:
            nonlocal injected
            if (
                armed
                and not injected
                and any(
                    isinstance(item, LiveEventRecord) and item.type == "run_recovered"
                    for item in self.new
                )
            ):
                injected = True
                raise failure
            super().flush(objects)

    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        class_=FailingRecoveryActivationSession,
        autoflush=False,
        autocommit=False,
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-recovery-owner",
    )
    recovery = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-recovery-retry",
    )
    run = owner.create_run(
        session_id="game_recovery_activation_failure",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)
    with session_factory() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        db.commit()

    claimed = recovery.try_claim_stale_run(run.run_id)
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.fence_token == 2
    subscriber = recovery.subscribe(run.run_id, after_id=2)
    armed = True

    with pytest.raises(RuntimeError) as raised:
        recovery.mark_running(run.run_id)

    assert raised.value is failure
    assert injected is True
    assert claimed.status == "running"
    assert claimed.fence_token == 2
    assert claimed.next_event_id == 3
    assert [(event.id, event.type) for event in claimed.events] == [
        (1, "run_created"),
        (2, "run_started"),
    ]
    assert (claimed.run_id, claimed.fence_token) not in recovery._activation_events
    assert subscriber.empty()

    activation = recovery.mark_running(run.run_id)
    repeated = recovery.mark_running(run.run_id)

    assert activation is repeated is claimed.events[2]
    assert activation.type == "run_recovered"
    assert activation.payload == {"fence_token": 2}
    assert claimed.fence_token == 2
    assert claimed.next_event_id == 4
    assert subscriber.get_nowait() is activation
    assert subscriber.empty()
    with session_factory() as observer:
        saved = observer.get(LiveRunRecord, run.run_id)
        events = list(
            observer.scalars(
                select(LiveEventRecord)
                .where(LiveEventRecord.run_id == run.run_id)
                .order_by(LiveEventRecord.event_id)
            )
        )
        assert saved is not None
        assert saved.status == "running"
        assert saved.fence_token == 2
        assert [(event.event_id, event.type) for event in events] == [
            (1, "run_created"),
            (2, "run_started"),
            (3, "run_recovered"),
        ]


def test_two_registries_share_run_events_lease_and_stop_signal(
    db_session: Session,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-owner",
        lease_seconds=5,
        event_poll_seconds=0.01,
    )
    observer = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-observer",
        lease_seconds=5,
        event_poll_seconds=0.01,
    )
    run = owner.create_run(
        session_id="game_2200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=22,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)

    persisted = observer.try_get_run(run.run_id)
    active, created = observer.get_or_create_active_run(
        session_id=run.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=22,
        max_rounds=8,
    )
    assert persisted is not None
    assert persisted.run_id == run.run_id
    assert active.run_id == run.run_id
    assert created is False

    subscriber = observer.subscribe(run.run_id, after_id=run.events[-1].id)
    owner.publish(run.run_id, "phase_started", phase="night")
    observed = subscriber.get(timeout=1)
    observer.unsubscribe(run.run_id, subscriber)
    assert observed.type == "phase_started"

    with session_factory() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.stop_requested_at = datetime.now(tz=UTC)
        record.control_version += 1
        db.commit()
        competing_lease = DatabaseLiveStore(db).acquire_lease(
            run.run_id,
            expected_events=tuple(run.events),
            worker_id="worker-observer",
            heartbeat_at="2026-07-11T08:00:00Z",
            lease_expires_at="2026-07-11T08:00:05Z",
        )
    assert competing_lease is None

    lease_state = owner.refresh_lease(run.run_id)
    assert lease_state is not None
    assert owner.stop_requested(run.run_id) is True
    assert owner.events_after(run.run_id)[-1].type == "run_stop_requested"
    with pytest.raises(GameRunCanceled):
        EventSink(owner, run.run_id).publish("phase_started", phase="day")
    owner.mark_canceled(run.run_id)


def test_stale_worker_state_cannot_erase_newer_database_control_signal(
    db_session: Session,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-owner",
    )
    run = owner.create_run(
        session_id="game_3300abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=33,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)
    requested_at = datetime.now(tz=UTC)
    with session_factory() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.stop_requested_at = requested_at
        record.control_version = 1
        db.commit()

    owner.mark_completed(run.run_id, winner="好人阵营")

    with session_factory() as db:
        saved = db.get(LiveRunRecord, run.run_id)
        assert saved is not None
        assert saved.status == "completed"
        assert saved.control_version == 1
        assert saved.stop_requested_at is not None
    assert run.control_version == 1
    assert run.stop_requested_at is not None


def test_stale_run_takeover_increments_fence_and_rejects_old_worker_writes(
    db_session: Session,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-owner",
    )
    recovery = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-recovery",
    )
    run = owner.create_run(
        session_id="game_4400abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=44,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)
    original_fence = run.fence_token
    assert original_fence == 1

    with session_factory() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        db.commit()

    claimed = recovery.try_claim_stale_run(run.run_id)
    assert claimed is not None
    assert claimed.run_id == run.run_id
    assert claimed.worker_id == "worker-recovery"
    assert claimed.fence_token == original_fence + 1

    with pytest.raises(RunLeaseUnavailable):
        owner.publish(run.run_id, "phase_started", phase="day")
    with pytest.raises(RunLeaseUnavailable):
        owner.mark_completed(run.run_id, winner="狼人阵营")

    recovered = recovery.mark_running(run.run_id)
    assert recovered.type == "run_recovered"
    assert recovered.payload["fence_token"] == original_fence + 1
    with session_factory() as db:
        events = DatabaseLiveStore(db).events_after(run.run_id)
        saved = db.get(LiveRunRecord, run.run_id)
        assert [event.type for event in events] == [
            "run_created",
            "run_started",
            "run_recovered",
        ]
        assert saved is not None
        assert saved.status == "running"
        assert saved.worker_id == "worker-recovery"
        assert saved.fence_token == original_fence + 1


def test_same_registry_takeover_fences_the_old_engine_event_sink(
    db_session: Session,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-same-process",
    )
    run = registry.create_run(
        session_id="game_5500abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=55,
        max_rounds=8,
    )
    registry.mark_running(run.run_id)
    old_fence = run.fence_token
    old_engine_sink = EventSink(registry, run.run_id, fence_token=old_fence)

    with session_factory() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        db.commit()

    claimed = registry.try_claim_stale_run(run.run_id)
    assert claimed is run
    assert run.fence_token == old_fence + 1
    with pytest.raises(RunLeaseUnavailable):
        old_engine_sink.publish("phase_started", phase="day")

    recovered = registry.mark_running(run.run_id)
    assert recovered.type == "run_recovered"
