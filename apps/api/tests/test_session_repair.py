from __future__ import annotations

import copy
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.game_session import GameReplayPayload
from app.werewolf.replay import DatabaseReplayStore
from app.werewolf.session_repair import repair_resume_session
from tests.rule_set_fixtures import complete_resume_checkpoint, legacy_official_compiled_rule_set


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


def test_session_repair_drops_invalid_cached_response_only_on_apply(
    db_session: Session,
) -> None:
    session_id = "game_1200abcd"
    checkpoint = complete_resume_checkpoint(
        session_id,
        legacy_official_compiled_rule_set("starter_6"),
    )
    checkpoint["cached_model_responses"] = [
        {
            "actor": "林言",
            "action": "debate",
            "phase": "day",
            "model": "test-model",
            "raw_response": "\n--- retry ---\n",
        },
        {
            "actor": "阿青",
            "action": "vote",
            "phase": "day",
            "model": "test-model",
            "raw_response": '{"reasoning":"票型","vote":"2号玩家"}',
        },
    ]
    DatabaseReplayStore(db_session).save_resume_checkpoint(session_id, checkpoint)
    stored_payload = db_session.get(GameReplayPayload, session_id)
    assert stored_payload is not None and stored_payload.checkpoint is not None
    stored_payload.checkpoint = {
        **stored_payload.checkpoint,
        "state_at_round_start": {
            **stored_payload.checkpoint["state_at_round_start"],
            "rounds": [
                {"number": 1, "players": [], "debate": [], "bids": [], "votes": [], "summaries": {}, "success": True}
            ],
        },
        "logs_before_round": [],
    }
    db_session.commit()
    original = copy.deepcopy(stored_payload.checkpoint)

    dry_run = repair_resume_session(db_session, session_id=session_id, apply=False)
    assert dry_run["cached_responses"] == {"scanned": 2, "kept": 1, "removed": 1}
    assert db_session.get(GameReplayPayload, session_id).checkpoint == original

    applied = repair_resume_session(db_session, session_id=session_id, apply=True)
    db_session.commit()
    repaired = db_session.get(GameReplayPayload, session_id).checkpoint
    assert applied["mode"] == "apply"
    assert len(repaired["cached_model_responses"]) == 1
    assert repaired["cached_model_responses"][0]["actor"] == "阿青"
    assert repaired["logs_before_round"] == [{"number": 1}]
    assert applied["checkpoint_rounds"]["placeholders_added"] == 1
