from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.werewolf.checkpoint import CHECKPOINT_SCHEMA_VERSION, ResumeCheckpointError
from app.werewolf.replay import DatabaseReplayStore, ReplayNotFoundError

_DEFAULT = object()


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


def sample_checkpoint(
    session_id: str = "game_1200abcd",
    *,
    checkpoint_session_id: str | None = None,
    state_session_id: str | None = None,
    state_at_round_start: Any = _DEFAULT,
    logs_before_round: Any = _DEFAULT,
    schema_version: Any = _DEFAULT,
) -> dict[str, Any]:
    if state_at_round_start is _DEFAULT:
        state_at_round_start = sample_state(
            state_session_id or session_id,
            winner="",
            error="",
        )
    if logs_before_round is _DEFAULT:
        logs_before_round = sample_logs()
    if schema_version is _DEFAULT:
        schema_version = CHECKPOINT_SCHEMA_VERSION
    return {
        "schema_version": schema_version,
        "session_id": checkpoint_session_id or session_id,
        "state_at_round_start": state_at_round_start,
        "logs_before_round": logs_before_round,
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


def test_list_sessions_skips_records_without_payload(db_session: Session) -> None:
    db_session.add(GameSessionRecord(session_id="game_1200abcd", status="partial"))
    db_session.commit()
    store = DatabaseReplayStore(db_session)

    assert store.list_sessions() == []


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


def test_save_resume_checkpoint_rejects_checkpoint_session_mismatch(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)
    checkpoint = sample_checkpoint(
        "game_1200abcd",
        checkpoint_session_id="game_deadbeef",
    )

    with pytest.raises(ResumeCheckpointError):
        store.save_resume_checkpoint("game_1200abcd", checkpoint)

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None
    assert db_session.get(GameSessionRecord, "game_deadbeef") is None


def test_save_resume_checkpoint_rejects_state_session_mismatch(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)
    checkpoint = sample_checkpoint(
        "game_1200abcd",
        state_session_id="game_deadbeef",
    )

    with pytest.raises(ResumeCheckpointError):
        store.save_resume_checkpoint("game_1200abcd", checkpoint)

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None


def test_save_game_payload_rejects_invalid_rounds_without_record(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)
    state = sample_state("game_1200abcd")
    state["rounds"] = {"bad": True}

    with pytest.raises(ReplayNotFoundError):
        store.save_game_payload(state=state, logs=sample_logs())

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None


def test_save_game_payload_rejects_invalid_logs_without_record(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)

    with pytest.raises(ReplayNotFoundError):
        store.save_game_payload(state=sample_state("game_1200abcd"), logs={"bad": True})

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None


def test_save_game_payload_rejects_invalid_state_shape(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)

    with pytest.raises(ReplayNotFoundError):
        store.save_game_payload(state=[], logs=sample_logs())


def test_save_game_payload_rolls_back_when_commit_fails(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = DatabaseReplayStore(db_session)

    def fail_commit() -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        store.save_game_payload(state=sample_state("game_1200abcd"), logs=sample_logs())

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None


def test_save_resume_checkpoint_rejects_malformed_state_and_logs(
    db_session: Session,
) -> None:
    store = DatabaseReplayStore(db_session)

    for checkpoint in [
        sample_checkpoint(state_at_round_start=None),
        sample_checkpoint(state_at_round_start={"session_id": "game_1200abcd", "rounds": {}}),
        sample_checkpoint(logs_before_round={"bad": True}),
        sample_checkpoint(schema_version=CHECKPOINT_SCHEMA_VERSION + 1),
    ]:
        with pytest.raises(ResumeCheckpointError):
            store.save_resume_checkpoint("game_1200abcd", checkpoint)
        assert db_session.get(GameSessionRecord, "game_1200abcd") is None


def test_save_resume_checkpoint_rejects_non_dict_checkpoint(db_session: Session) -> None:
    store = DatabaseReplayStore(db_session)

    with pytest.raises(ResumeCheckpointError):
        store.save_resume_checkpoint("game_1200abcd", [])

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None


def test_load_resume_checkpoint_rejects_malformed_stored_checkpoint(
    db_session: Session,
) -> None:
    db_session.add(GameSessionRecord(session_id="game_1200abcd", status="partial", resumable=True))
    db_session.add(
        GameReplayPayload(
            session_id="game_1200abcd",
            state=sample_state("game_1200abcd"),
            logs=[],
            checkpoint={"schema_version": CHECKPOINT_SCHEMA_VERSION},
        )
    )
    db_session.commit()
    store = DatabaseReplayStore(db_session)

    with pytest.raises(ResumeCheckpointError):
        store.load_resume_checkpoint("game_1200abcd")


def test_partial_game_ignores_invalid_existing_checkpoint_for_resumable(
    db_session: Session,
) -> None:
    db_session.add(GameSessionRecord(session_id="game_1200abcd", status="partial", resumable=True))
    db_session.add(
        GameReplayPayload(
            session_id="game_1200abcd",
            state=sample_state("game_1200abcd", winner="", error="failed"),
            logs=[],
            checkpoint={"schema_version": CHECKPOINT_SCHEMA_VERSION},
        )
    )
    db_session.commit()
    store = DatabaseReplayStore(db_session)

    store.save_game_payload(
        state=sample_state("game_1200abcd", winner="", error="failed"),
        logs=sample_logs(),
    )
    loaded_session = store.load_session("game_1200abcd")

    assert loaded_session["status"] == "partial"
    assert loaded_session["resumable"] is False


def test_clear_resume_checkpoint_clears_stale_record_without_payload(
    db_session: Session,
) -> None:
    db_session.add(GameSessionRecord(session_id="game_1200abcd", status="partial", resumable=True))
    db_session.commit()
    store = DatabaseReplayStore(db_session)

    store.clear_resume_checkpoint("game_1200abcd")

    record = db_session.get(GameSessionRecord, "game_1200abcd")
    assert record is not None
    assert record.resumable is False
