from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.live import LiveRunRecord
from app.werewolf.live import EventSink, GameRunCanceled, LiveEvent, LiveRunRegistry
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

    store.save_run(first_run)
    store.append_event(first_event)
    store.save_run(empty_run)
    store.save_run(latest_run)
    store.append_event(latest_event)

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
    store.append_event(event)
    with pytest.raises(IntegrityError):
        store.append_event(duplicate)

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
    store.append_event(first)
    with pytest.raises(IntegrityError):
        store.append_event(duplicate)
    store.append_event(second)

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
