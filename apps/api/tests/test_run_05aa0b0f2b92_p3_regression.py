from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import time
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin.quality_evaluations import (
    build_admin_quality_issues,
    build_admin_quality_summary,
)
from app.api.schemas.admin_games import (
    AdminGameQualityEvaluationResponse,
    AdminGameQualityIssuesResponse,
)
from app.db.base import Base
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import LiveEventRecord, LiveRunRecord, VoiceUtteranceRecord
from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.werewolf.quality_store import enqueue_quality_evaluation
from app.werewolf.quality_worker import QualityEvaluationWorker


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "werewolf_quality"
SENTINEL = "P3_PRIVATE_SENTINEL_11号计划刀10号并嫁祸12号"
HMAC_KEY = "run-05aa0b0f2b92-p3-regression-key"


def test_target_game_leaking_fixture_flows_safely_through_worker_db_and_admin() -> None:
    started_at = time.perf_counter()
    first = _run_fixture("run_05aa0b0f2b92_leaking.json")
    second = _run_fixture("run_05aa0b0f2b92_leaking.json")

    assert first["record"]["verdict"] == "fail"
    assert first["summary"]["issue_counts"]["P0"] >= 5
    assert {issue["channel"] for issue in first["issues"]} >= {
        "live_event",
        "voice",
        "subtitle",
        "replay",
        "public_state",
    }
    assert first["source_revision"] == second["source_revision"]
    assert first["record"]["verdict"] == second["record"]["verdict"]
    assert [item["issue_id"] for item in first["issues"]] == [
        item["issue_id"] for item in second["issues"]
    ]
    for field in ("facts", "structure", "voice", "performance", "content"):
        assert first["record"][field] == second["record"][field]
    assert SENTINEL not in json.dumps(first, ensure_ascii=False)
    assert time.perf_counter() - started_at < 3.0


def test_target_game_sanitized_fixture_passes_worker_and_admin_projection() -> None:
    result = _run_fixture("run_05aa0b0f2b92_sanitized.json")

    assert result["record"]["verdict"] == "pass"
    assert result["summary"]["verdict"] == "pass"
    assert result["summary"]["issue_counts"]["P0"] == 0
    assert result["summary"]["voice"]["terminal_judge_voice_coverage"] is True
    assert result["issues"] == []
    assert SENTINEL not in json.dumps(result, ensure_ascii=False)


def _run_fixture(filename: str) -> dict[str, Any]:
    fixture = json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        _seed_fixture(factory, fixture)
        with factory() as db:
            queued = enqueue_quality_evaluation(
                db,
                session_id=fixture["state"]["session_id"],
                run_id=fixture["run_id"],
            )
            evaluation_id = queued.id
            source_revision = queued.source_revision
            db.commit()
        worker = QualityEvaluationWorker(factory, hmac_key=HMAC_KEY)
        assert worker.claim_next_job(worker_id="p3-regression-worker") == evaluation_id
        assert worker.process_claimed_job(
            evaluation_id, worker_id="p3-regression-worker"
        )
        with factory() as db:
            record = db.get(GameQualityEvaluationRecord, evaluation_id)
            assert record is not None
            safe_record = record.safe_summary
            summary = build_admin_quality_summary(record, terminal=True)
            issues = build_admin_quality_issues(record)
            summary_response = AdminGameQualityEvaluationResponse(
                session_id=record.session_id,
                quality_evaluation=summary,
            ).model_dump(mode="json")
            issues_response = AdminGameQualityIssuesResponse(
                session_id=record.session_id,
                evaluation_id=record.id,
                items=issues,
            ).model_dump(mode="json")
        result = {
            "source_revision": source_revision,
            "record": safe_record,
            "summary": summary_response["quality_evaluation"],
            "issues": issues_response["items"],
        }
        assert "safe_issues" not in result["summary"]
        return result
    finally:
        engine.dispose()


def _seed_fixture(
    factory: sessionmaker[Session],
    fixture: dict[str, Any],
) -> None:
    state = fixture["state"]
    session_id = state["session_id"]
    run_id = fixture["run_id"]
    started_at = datetime.fromisoformat("2026-07-14T00:00:00+00:00")
    with factory() as db:
        db.add(
            GameSessionRecord(
                session_id=session_id,
                status="complete",
                winner=state.get("winner"),
                round_count=len(state.get("rounds", [])),
                resumable=False,
            )
        )
        db.add(
            GameReplayPayload(
                session_id=session_id,
                state=state,
                logs=fixture["logs"],
            )
        )
        db.add(
            LiveRunRecord(
                run_id=run_id,
                session_id=session_id,
                status="completed",
                villager_model="fixture-model",
                werewolf_model="fixture-model",
                max_rounds=12,
                rule_set_id="fixture-rule",
                player_configs=[],
                lineup_quality_warnings=[],
                winner=state.get("winner"),
                created_at=started_at,
                started_at=started_at,
                completed_at=started_at + timedelta(minutes=12),
            )
        )
        db.flush()
        for event in fixture["live_events"]:
            db.add(
                LiveEventRecord(
                    run_id=run_id,
                    event_id=event["id"],
                    session_id=session_id,
                    type=event["type"],
                    round=event.get("round"),
                    phase=event.get("phase"),
                    actor=event.get("actor"),
                    action=event.get("action"),
                    payload=event.get("payload", {}),
                    created_at=datetime.fromisoformat(event["created_at"]),
                )
            )
        for voice in fixture["voice_utterances"]:
            text = voice["text"]
            db.add(
                VoiceUtteranceRecord(
                    utterance_id=voice["utterance_id"],
                    run_id=run_id,
                    session_id=session_id,
                    source_event_id=voice["source_event_id"],
                    last_source_event_id=voice["source_event_id"],
                    speaker_kind=voice["speaker_kind"],
                    speaker_name="fixture-speaker",
                    speaker="fixture-voice",
                    action=voice.get("action"),
                    text=text,
                    text_hash=hashlib.sha256(text.encode()).hexdigest(),
                    audio_format="mp3",
                    sample_rate=24000,
                    mime_type="audio/mpeg",
                    status=voice["status"],
                    subtitle_timings=voice.get("subtitle_timings"),
                )
            )
        db.commit()
