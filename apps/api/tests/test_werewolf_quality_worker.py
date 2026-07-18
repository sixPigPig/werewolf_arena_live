from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import LiveEventRecord, LiveRunRecord
from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.werewolf.quality_store import (
    enqueue_quality_evaluation,
    enqueue_recent_missing_evaluations,
    latest_quality_evaluation,
    latest_successful_quality_evaluation,
)
from app.werewolf.quality_worker import QualityEvaluationWorker
from app.werewolf.replay import DatabaseReplayStore


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


def _state(session_id: str = "game_1234abcd") -> dict:
    return {
        "session_id": session_id,
        "players": [],
        "rounds": [
            {
                "number": 1,
                "private_summaries": {},
                "public_summary": "游戏结束。",
                "debate": [],
                "summaries": {},
            }
        ],
        "public_facts": [],
        "winner": "好人阵营",
        "error_message": "",
        "rule_set": {"id": "starter_6", "name": "新手 6 人快局"},
    }


def _seed_terminal_game(
    session_factory: sessionmaker[Session],
    *,
    with_live_run: bool = True,
) -> tuple[str, str | None]:
    session_id = "game_1234abcd"
    run_id = "run_1234abcd" if with_live_run else None
    with session_factory() as db:
        db.add(
            GameSessionRecord(
                session_id=session_id,
                status="complete",
                winner="好人阵营",
                round_count=1,
            )
        )
        db.add(GameReplayPayload(session_id=session_id, state=_state(), logs=[]))
        if run_id:
            db.add(
                LiveRunRecord(
                    run_id=run_id,
                    session_id=session_id,
                    status="completed",
                    villager_model="deepseek-chat",
                    werewolf_model="deepseek-chat",
                    max_rounds=8,
                    rule_set_id="starter_6",
                    player_configs=[],
                    lineup_quality_warnings=[],
                    lineup_quality_report={},
                    p2_diagnostics={},
                    winner="好人阵营",
                    completed_at=datetime.now(tz=UTC),
                )
            )
            db.flush()
            db.add(
                LiveEventRecord(
                    run_id=run_id,
                    event_id=1,
                    session_id=session_id,
                    type="game_completed",
                    round=1,
                    phase="terminal",
                    payload={"winner": "好人阵营"},
                )
            )
        db.commit()
    return session_id, run_id


def test_quality_enqueue_is_idempotent_and_worker_completes(
    session_factory: sessionmaker[Session],
) -> None:
    session_id, run_id = _seed_terminal_game(session_factory)
    with session_factory() as db:
        first = enqueue_quality_evaluation(db, session_id=session_id, run_id=run_id)
        second = enqueue_quality_evaluation(db, session_id=session_id, run_id=run_id)
        assert first.id == second.id
        db.commit()

    worker = QualityEvaluationWorker(session_factory, hmac_key="test-key")
    evaluation_id = worker.claim_next_job(worker_id="worker-a")

    assert evaluation_id is not None
    assert worker.process_claimed_job(evaluation_id, worker_id="worker-a") is True
    with session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        assert record.status == "completed"
        assert record.verdict == "pass"
        assert record.safe_summary["schema_version"] == 1
        assert record.worker_id is None


def test_expired_quality_lease_is_reclaimed(
    session_factory: sessionmaker[Session],
) -> None:
    session_id, run_id = _seed_terminal_game(session_factory)
    with session_factory() as db:
        record = enqueue_quality_evaluation(db, session_id=session_id, run_id=run_id)
        record.status = "processing"
        record.worker_id = "dead-worker"
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        db.commit()
        evaluation_id = record.id

    worker = QualityEvaluationWorker(session_factory, hmac_key="test-key")
    claimed = worker.claim_next_job(worker_id="replacement-worker")

    assert claimed == evaluation_id
    with session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        assert record.worker_id == "replacement-worker"
        assert record.attempt_count == 1


def test_repeated_crashes_stop_reclaiming_at_max_attempts(
    session_factory: sessionmaker[Session],
) -> None:
    session_id, run_id = _seed_terminal_game(session_factory)
    with session_factory() as db:
        record = enqueue_quality_evaluation(db, session_id=session_id, run_id=run_id)
        db.commit()
        evaluation_id = record.id

    worker = QualityEvaluationWorker(
        session_factory,
        hmac_key="test-key",
        max_attempts=2,
    )
    assert worker.claim_next_job(worker_id="worker-one") == evaluation_id
    with session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        db.commit()

    assert worker.claim_next_job(worker_id="worker-two") == evaluation_id
    with session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        record.safe_summary = {
            "_previous_successful_result": {
                "evaluator_version": record.evaluator_version,
                "source_revision": record.source_revision,
                "completed_at": "2026-07-18T01:02:03+00:00",
            }
        }
        db.commit()

    assert worker.claim_next_job(worker_id="worker-three") is None
    with session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        assert record.status == "failed"
        assert record.attempt_count == 2
        assert record.worker_id is None
        assert record.lease_expires_at is None
        assert record.last_error_code == "lease_expired_max_attempts"
        assert record.completed_at is not None
        successful = latest_successful_quality_evaluation(db, session_id=session_id)
        assert successful is not None
        assert successful.source_revision == record.source_revision


def test_lost_lease_fences_old_worker_completion(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, run_id = _seed_terminal_game(session_factory)
    with session_factory() as db:
        record = enqueue_quality_evaluation(db, session_id=session_id, run_id=run_id)
        db.commit()
        evaluation_id = record.id

    worker = QualityEvaluationWorker(
        session_factory,
        hmac_key="test-key",
        lease_seconds=60,
    )
    assert worker.claim_next_job(worker_id="worker-old") == evaluation_id

    from app.werewolf.quality_evaluation import (
        evaluate_quality_bundle as real_evaluate_quality_bundle,
    )

    def reclaim_before_old_worker_commit(*args: object, **kwargs: object) -> object:
        with session_factory() as db:
            record = db.get(GameQualityEvaluationRecord, evaluation_id)
            assert record is not None
            record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
            db.commit()
        assert worker.claim_next_job(worker_id="worker-new") == evaluation_id
        return real_evaluate_quality_bundle(*args, **kwargs)

    monkeypatch.setattr(
        "app.werewolf.quality_worker.evaluate_quality_bundle",
        reclaim_before_old_worker_commit,
    )

    assert worker.process_claimed_job(evaluation_id, worker_id="worker-old") is False
    with session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        assert record.status == "processing"
        assert record.worker_id == "worker-new"
        assert record.attempt_count == 2
        assert record.safe_summary == {}


def test_expired_lease_cannot_be_renewed_by_old_owner(
    session_factory: sessionmaker[Session],
) -> None:
    session_id, run_id = _seed_terminal_game(session_factory)
    expired_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    with session_factory() as db:
        record = enqueue_quality_evaluation(db, session_id=session_id, run_id=run_id)
        record.status = "processing"
        record.worker_id = "worker-old"
        record.lease_expires_at = expired_at
        db.commit()
        evaluation_id = record.id

    worker = QualityEvaluationWorker(session_factory, hmac_key="test-key")

    assert worker.renew_lease(evaluation_id, worker_id="worker-old") is False
    with session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        assert record.worker_id == "worker-old"
        assert record.lease_expires_at is not None
        assert record.lease_expires_at.replace(tzinfo=UTC) == expired_at


def test_source_revision_drift_supersedes_old_job_and_enqueues_new(
    session_factory: sessionmaker[Session],
) -> None:
    session_id, run_id = _seed_terminal_game(session_factory)
    with session_factory() as db:
        record = enqueue_quality_evaluation(db, session_id=session_id, run_id=run_id)
        db.commit()
        old_id = record.id
    worker = QualityEvaluationWorker(session_factory, hmac_key="test-key")
    assert worker.claim_next_job(worker_id="worker-a") == old_id
    with session_factory() as db:
        db.add(
            LiveEventRecord(
                run_id=run_id,
                event_id=2,
                session_id=session_id,
                    type="judge_cue",
                    round=1,
                    phase="terminal",
                    action="dawn_peaceful",
                    payload={
                        "schema_version": 1,
                        "cue_id": "dawn_peaceful",
                        "cue": "dawn_peaceful",
                        "visible_text": "昨夜平安夜。",
                    },
            )
        )
        db.commit()

    assert worker.process_claimed_job(old_id, worker_id="worker-a") is True
    with session_factory() as db:
        old = db.get(GameQualityEvaluationRecord, old_id)
        rows = db.query(GameQualityEvaluationRecord).all()
        assert old is not None and old.status == "superseded"
        assert len(rows) == 2
        assert {row.status for row in rows} == {"superseded", "pending"}
        assert latest_quality_evaluation(db, session_id=session_id).status == "pending"


def test_worker_failure_is_bounded_and_stores_only_error_code(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, run_id = _seed_terminal_game(session_factory)
    with session_factory() as db:
        record = enqueue_quality_evaluation(db, session_id=session_id, run_id=run_id)
        db.commit()
        evaluation_id = record.id
    worker = QualityEvaluationWorker(
        session_factory,
        hmac_key="test-key",
        max_attempts=1,
    )
    assert worker.claim_next_job(worker_id="worker-a") == evaluation_id

    def fail_bundle(*_args: object, **_kwargs: object) -> object:
        raise ValueError("PRIVATE ERROR CONTENT")

    monkeypatch.setattr(
        "app.werewolf.quality_worker.build_database_quality_bundle",
        fail_bundle,
    )
    assert worker.process_claimed_job(evaluation_id, worker_id="worker-a") is False
    with session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        assert record.status == "failed"
        assert record.last_error_code == "invalid_evaluation_input"
        assert "PRIVATE" not in record.last_error_code


def test_backfill_is_bounded_and_dry_run_does_not_write(
    session_factory: sessionmaker[Session],
) -> None:
    session_id, _run_id = _seed_terminal_game(session_factory, with_live_run=False)
    with session_factory() as db:
        result = enqueue_recent_missing_evaluations(
            db,
            evaluator_version="p3-v1",
            session_id=session_id,
            limit=1,
            dry_run=True,
        )
        assert result == {"matched": 1, "enqueued": 1, "skipped": 0}
        assert db.query(GameQualityEvaluationRecord).count() == 0


def test_terminal_replay_enqueue_is_best_effort_and_feature_gated(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "quality_evaluation_enabled", True)
    monkeypatch.setattr(settings, "quality_evaluation_version", "p3-v1")
    with session_factory() as db:
        DatabaseReplayStore(db).save_game_payload(state=_state(), logs=[])
    with session_factory() as db:
        record = db.query(GameQualityEvaluationRecord).one()
        assert record.session_id == "game_1234abcd"
        assert record.status == "pending"


def test_partial_replay_is_enqueued_for_privacy_evaluation(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "quality_evaluation_enabled", True)
    monkeypatch.setattr(settings, "quality_evaluation_version", "p3-v1")
    state = _state()
    state["winner"] = ""
    state["error_message"] = "model request failed"

    with session_factory() as db:
        DatabaseReplayStore(db).save_game_payload(state=state, logs=[])

    with session_factory() as db:
        game = db.get(GameSessionRecord, "game_1234abcd")
        evaluation = db.query(GameQualityEvaluationRecord).one()
        assert game is not None
        assert game.status == "partial"
        assert evaluation.status == "pending"
