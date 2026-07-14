from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.live import GodViewLiveEventRecord, LiveRunRecord, PublicLiveEventRecord
from app.werewolf.live import LiveRunRegistry
from app.werewolf.live_store import DatabaseLiveStore
from app.werewolf.projection_backfill import rebuild_live_event_projections


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db
    engine.dispose()


def test_projection_rebuild_is_dry_run_capable_and_idempotent(db_session: Session) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_backfill",
        villager_model="test-model",
        werewolf_model="test-model",
        seed=1,
        max_rounds=8,
    )
    vote = registry.publish(
        run.run_id,
        "action_parsed",
        phase="night",
        actor="1号玩家",
        action="werewolf_kill_vote",
        payload={"choice": "2号玩家"},
    )
    store = DatabaseLiveStore(db_session)
    store.save_run(run)
    store.append_event(vote, worker_id=run.worker_id, fence_token=run.fence_token)
    db_session.query(PublicLiveEventRecord).delete()
    db_session.query(GodViewLiveEventRecord).delete()
    db_session.commit()

    dry_run = rebuild_live_event_projections(
        db_session,
        apply=False,
        run_id=run.run_id,
    )
    assert dry_run["player_public"]["omitted"] == 1
    assert dry_run["spectator_god_view"]["created"] == 1
    assert db_session.query(PublicLiveEventRecord).count() == 0
    assert db_session.query(GodViewLiveEventRecord).count() == 0

    rebuild_live_event_projections(db_session, apply=True, run_id=run.run_id)
    db_session.commit()
    second = rebuild_live_event_projections(db_session, apply=True, run_id=run.run_id)
    db_session.commit()

    assert db_session.get(LiveRunRecord, run.run_id) is not None
    assert db_session.get(PublicLiveEventRecord, (run.run_id, vote.id)) is None
    assert db_session.get(GodViewLiveEventRecord, (run.run_id, vote.id)) is not None
    assert second["spectator_god_view"]["unchanged"] == 1
