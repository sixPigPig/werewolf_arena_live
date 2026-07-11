from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.games import SessionLiveStore
from app.db.base import Base
from app.models.live import LiveRunRecord
from app.werewolf.live import (
    EventSink,
    GameRunCanceled,
    LiveEvent,
    LiveRunRegistry,
    RunLeaseUnavailable,
)
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

    assert [event.id for event in store.events_after(run.run_id, after_id=first.id)] == [
        second.id
    ]


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
