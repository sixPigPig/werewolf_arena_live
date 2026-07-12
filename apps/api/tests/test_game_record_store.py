from __future__ import annotations

import copy
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import LiveRunRecord
from app.rule_sets import compile_rule_set_config, rule_set_config_from_snapshot
from app.werewolf.checkpoint import CHECKPOINT_SCHEMA_VERSION, ResumeCheckpointError
from app.werewolf.replay import (
    DatabaseReplayStore,
    ReplayNotFoundError,
    ReplayWriteFencedError,
)
from app.werewolf.rules import get_rule_set, rule_set_snapshot

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


def managed_rule_snapshot(
    *, revision_id: str = "revision-2", revision_no: int = 2
) -> dict[str, Any]:
    legacy = rule_set_snapshot(get_rule_set("starter_6"))
    config = rule_set_config_from_snapshot(legacy)
    return compile_rule_set_config(
        "starter_6",
        config,
        revision_id=revision_id,
        revision_no=revision_no,
    ).snapshot


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
    record = db_session.get(GameSessionRecord, "game_1200abcd")
    assert record is not None
    assert record.rule_set_id == "starter_6"
    assert record.rule_set_revision_id is None
    assert record.rule_set_revision_no is None
    assert record.rule_set_content_hash is None


def test_replay_store_saves_pre_rule_set_legacy_state_without_projection(
    db_session: Session,
) -> None:
    store = DatabaseReplayStore(db_session)
    state = sample_state("game_1200abcd")
    del state["rule_set"]

    store.save_game_payload(state=state, logs=sample_logs())

    record = db_session.get(GameSessionRecord, "game_1200abcd")
    payload = db_session.get(GameReplayPayload, "game_1200abcd")
    assert record is not None
    assert payload is not None
    assert record.rule_set_id is None
    assert record.rule_set_revision_id is None
    assert record.rule_set_revision_no is None
    assert record.rule_set_content_hash is None
    assert record.rule_set is None
    assert payload.state == state


def test_replay_store_projects_pinned_rule_metadata_without_rewriting_snapshot(
    db_session: Session,
) -> None:
    store = DatabaseReplayStore(db_session)
    state = sample_state("game_1200abcd")
    state["rule_set"] = managed_rule_snapshot()
    original_state = copy.deepcopy(state)

    store.save_game_payload(state=state, logs=sample_logs())

    record = db_session.get(GameSessionRecord, "game_1200abcd")
    payload = db_session.get(GameReplayPayload, "game_1200abcd")
    assert record is not None
    assert payload is not None
    assert record.rule_set_id == state["rule_set"]["id"]
    assert record.rule_set_revision_id == state["rule_set"]["revision_id"]
    assert record.rule_set_revision_no == state["rule_set"]["revision_no"]
    assert record.rule_set_content_hash == state["rule_set"]["content_hash"]
    assert record.rule_set == original_state["rule_set"]
    assert payload.state == original_state
    assert state == original_state


def test_replay_store_replaces_and_clears_pinned_rule_metadata_on_update(
    db_session: Session,
) -> None:
    store = DatabaseReplayStore(db_session)
    legacy_state = sample_state("game_1200abcd")
    store.save_game_payload(state=legacy_state, logs=sample_logs())

    managed_state = sample_state("game_1200abcd")
    managed_state["rule_set"] = managed_rule_snapshot()
    store.save_game_payload(state=managed_state, logs=sample_logs())

    managed = db_session.get(GameSessionRecord, "game_1200abcd")
    assert managed is not None
    assert managed.rule_set_revision_id == managed_state["rule_set"]["revision_id"]
    assert managed.rule_set_revision_no == managed_state["rule_set"]["revision_no"]
    assert managed.rule_set_content_hash == managed_state["rule_set"]["content_hash"]

    legacy_again = sample_state("game_1200abcd")
    legacy_again["rule_set"] = {"id": "classic_8", "name": "legacy again"}
    store.save_game_payload(state=legacy_again, logs=sample_logs())

    db_session.expire_all()
    cleared = db_session.get(GameSessionRecord, "game_1200abcd")
    assert cleared is not None
    assert cleared.rule_set_id == "classic_8"
    assert cleared.rule_set_revision_id is None
    assert cleared.rule_set_revision_no is None
    assert cleared.rule_set_content_hash is None
    assert cleared.rule_set == legacy_again["rule_set"]


@pytest.mark.parametrize(
    "metadata_change",
    [
        {"missing": "revision_id"},
        {"missing": "revision_no"},
        {"missing": "schema_version"},
        {"missing": "content_hash"},
        {"field": "revision_id", "value": " revision-2"},
        {"field": "revision_no", "value": True},
        {"field": "schema_version", "value": True},
        {"field": "schema_version", "value": 2},
        {"field": "content_hash", "value": "A" * 64},
        {"field": "content_hash", "value": "0" * 64},
    ],
    ids=(
        "missing-revision-id",
        "missing-revision-no",
        "missing-schema-version",
        "missing-content-hash",
        "untrimmed-revision-id",
        "boolean-revision-no",
        "boolean-schema-version",
        "wrong-schema-version",
        "uppercase-content-hash",
        "content-hash-mismatch",
    ),
)
def test_replay_store_rejects_partial_or_malformed_pinned_rule_metadata(
    db_session: Session,
    metadata_change: dict[str, Any],
) -> None:
    snapshot = managed_rule_snapshot()
    missing = metadata_change.get("missing")
    if missing is not None:
        del snapshot[missing]
    else:
        snapshot[metadata_change["field"]] = metadata_change["value"]
    state = sample_state("game_1200abcd")
    state["rule_set"] = snapshot

    with pytest.raises(ReplayNotFoundError):
        DatabaseReplayStore(db_session).save_game_payload(state=state, logs=sample_logs())

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None
    assert db_session.get(GameReplayPayload, "game_1200abcd") is None


@pytest.mark.parametrize("rule_set", [None, [], {"id": 7}, {"id": " starter_6"}])
def test_replay_store_rejects_invalid_legacy_rule_snapshot_shape(
    db_session: Session,
    rule_set: object,
) -> None:
    state = sample_state("game_1200abcd")
    state["rule_set"] = rule_set

    with pytest.raises(ReplayNotFoundError):
        DatabaseReplayStore(db_session).save_game_payload(state=state, logs=sample_logs())

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None
    assert db_session.get(GameReplayPayload, "game_1200abcd") is None


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


def test_checkpoint_write_projects_and_clears_pinned_rule_metadata(
    db_session: Session,
) -> None:
    store = DatabaseReplayStore(db_session)
    managed_state = sample_state("game_1200abcd", winner="", error="")
    managed_state["rule_set"] = managed_rule_snapshot()
    managed_checkpoint = sample_checkpoint(state_at_round_start=managed_state)

    store.save_resume_checkpoint("game_1200abcd", managed_checkpoint)

    managed = db_session.get(GameSessionRecord, "game_1200abcd")
    assert managed is not None
    assert managed.rule_set_id == managed_state["rule_set"]["id"]
    assert managed.rule_set_revision_id == managed_state["rule_set"]["revision_id"]
    assert managed.rule_set_revision_no == managed_state["rule_set"]["revision_no"]
    assert managed.rule_set_content_hash == managed_state["rule_set"]["content_hash"]
    assert managed.rule_set == managed_state["rule_set"]

    legacy_checkpoint = sample_checkpoint()
    store.save_resume_checkpoint("game_1200abcd", legacy_checkpoint)

    db_session.expire_all()
    cleared = db_session.get(GameSessionRecord, "game_1200abcd")
    payload = db_session.get(GameReplayPayload, "game_1200abcd")
    assert cleared is not None
    assert payload is not None
    assert cleared.rule_set_id == "starter_6"
    assert cleared.rule_set_revision_id is None
    assert cleared.rule_set_revision_no is None
    assert cleared.rule_set_content_hash is None
    assert cleared.rule_set == legacy_checkpoint["state_at_round_start"]["rule_set"]
    assert payload.checkpoint == legacy_checkpoint


def test_checkpoint_write_rejects_partial_pinned_rule_metadata(
    db_session: Session,
) -> None:
    state = sample_state("game_1200abcd", winner="", error="")
    state["rule_set"] = managed_rule_snapshot()
    del state["rule_set"]["content_hash"]
    checkpoint = sample_checkpoint(state_at_round_start=state)

    with pytest.raises(ReplayNotFoundError):
        DatabaseReplayStore(db_session).save_resume_checkpoint(
            "game_1200abcd",
            checkpoint,
        )

    assert db_session.get(GameSessionRecord, "game_1200abcd") is None
    assert db_session.get(GameReplayPayload, "game_1200abcd") is None


def test_replay_writes_require_the_current_live_run_fence_token(
    db_session: Session,
) -> None:
    now = datetime.now(tz=UTC)
    run = LiveRunRecord(
        run_id="run_123456789abc",
        session_id="game_1200abcd",
        status="running",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id="starter_6",
        worker_id="worker-owner",
        worker_heartbeat_at=now,
        lease_expires_at=now + timedelta(minutes=1),
        fence_token=1,
    )
    db_session.add(run)
    db_session.commit()
    checkpoint = sample_checkpoint()
    owner_store = DatabaseReplayStore(
        db_session,
        run_id=run.run_id,
        worker_id="worker-owner",
        fence_token=1,
    )
    owner_store.save_resume_checkpoint(run.session_id, checkpoint)

    run.worker_id = "worker-recovery"
    run.worker_heartbeat_at = now + timedelta(seconds=2)
    run.lease_expires_at = now + timedelta(minutes=2)
    run.fence_token = 2
    db_session.commit()

    stale_checkpoint = sample_checkpoint()
    stale_checkpoint["last_error"] = "stale worker overwrite"
    with pytest.raises(ReplayWriteFencedError):
        owner_store.save_resume_checkpoint(run.session_id, stale_checkpoint)

    recovered_checkpoint = sample_checkpoint()
    recovered_checkpoint["last_error"] = "recovered worker checkpoint"
    recovery_store = DatabaseReplayStore(
        db_session,
        run_id=run.run_id,
        worker_id="worker-recovery",
        fence_token=2,
    )
    recovery_store.save_resume_checkpoint(run.session_id, recovered_checkpoint)

    assert recovery_store.load_resume_checkpoint(run.session_id)["last_error"] == (
        "recovered worker checkpoint"
    )


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
