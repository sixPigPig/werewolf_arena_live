from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.admin.dependencies as admin_dependencies
import app.api.routes.admin_live_runs as live_run_routes
from app.admin.rbac import AdminPermission
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.game_session import GameSessionRecord
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceUtteranceRecord,
)
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.api.routes.games import SessionLiveStore, get_live_registry
from app.werewolf.live import LiveRunRegistry


HISTORY_RULE_ID = "history_rule"
HISTORY_REVISION_1_ID = "30000000-0000-0000-0000-000000000001"
HISTORY_REVISION_2_ID = "30000000-0000-0000-0000-000000000002"
OTHER_RULE_ID = "other_rule"
OTHER_REVISION_ID = "40000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class AdminLiveRunsContext:
    client: TestClient
    session_factory: sessionmaker[Session]
    engine: Engine
    registry: LiveRunRegistry


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> Generator[AdminLiveRunsContext, None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "runs-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Runs Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "super_admin")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "runs_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "admin_session_ttl_seconds", 3600)

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    registry = LiveRunRegistry(live_store=SessionLiveStore(testing_session))

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_live_registry] = lambda: registry
    with TestClient(application) as client:
        yield AdminLiveRunsContext(
            client=client,
            session_factory=testing_session,
            engine=engine,
            registry=registry,
        )
    engine.dispose()


def _login(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "super_admin",
) -> dict:
    monkeypatch.setattr(settings, "admin_dev_auth_role", role)
    response = context.client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text
    return response.json()


def _seed_run(
    context: AdminLiveRunsContext,
    *,
    run_id: str,
    session_id: str,
    created_at: datetime,
    updated_at: datetime | None = None,
    status: str = "completed",
    game_status: str | None = "complete",
    resumable: bool = False,
    rule_set_id: str = "classic_8",
    villager_model: str = "model-villager",
    werewolf_model: str = "model-werewolf",
    winner: str | None = "好人阵营",
    event_types: list[str] | None = None,
    event_phases: list[str | None] | None = None,
    voice_statuses: list[str] | None = None,
    run_error: str | None = None,
    voice_error_count: int = 0,
    rule_set_revision_id: str | None = None,
    rule_set_revision_no: int | None = None,
    rule_set_content_hash: str | None = None,
) -> None:
    resolved_updated_at = updated_at or created_at + timedelta(minutes=2)
    resolved_event_types = event_types or []
    resolved_event_phases = event_phases or ["day"] * len(resolved_event_types)
    assert len(resolved_event_types) == len(resolved_event_phases)
    with context.session_factory() as db:
        if game_status is not None:
            db.add(
                GameSessionRecord(
                    session_id=session_id,
                    status=game_status,
                    winner=winner,
                    round_count=2,
                    rule_set_id=rule_set_id,
                    rule_set_revision_id=rule_set_revision_id,
                    rule_set_revision_no=rule_set_revision_no,
                    rule_set_content_hash=rule_set_content_hash,
                    rule_set={
                        "id": rule_set_id,
                        "name": "SENTINEL_GAME_RULE_NAME",
                        "player_count": 8,
                    },
                    resumable=resumable,
                    created_at=created_at,
                    updated_at=resolved_updated_at,
                )
            )
        db.add(
            LiveRunRecord(
                run_id=run_id,
                session_id=session_id,
                status=status,
                villager_model=villager_model,
                werewolf_model=werewolf_model,
                seed=8675309,
                max_rounds=8,
                rule_set_id=rule_set_id,
                rule_set_revision_id=rule_set_revision_id,
                rule_set_revision_no=rule_set_revision_no,
                rule_set_content_hash=rule_set_content_hash,
                rule_set={
                    "id": rule_set_id,
                    "name": "SENTINEL_RUN_RULE_NAME",
                    "roles": {"SENTINEL_ROLE_MAPPING": "hidden"},
                },
                player_configs=[
                    {
                        "name": "SENTINEL_PLAYER_NAME",
                        "role": "SENTINEL_PLAYER_ROLE",
                        "prompt": "SENTINEL_PLAYER_PROMPT",
                    }
                ],
                lineup_quality_warnings=[{"warning": "SENTINEL_LINEUP_WARNING"}],
                winner=winner,
                error=run_error,
                created_at=created_at,
                started_at=(created_at + timedelta(seconds=1) if status != "queued" else None),
                completed_at=(
                    created_at + timedelta(minutes=2) if status in {"completed", "failed"} else None
                ),
                updated_at=resolved_updated_at,
            )
        )
        for index, (event_type, phase) in enumerate(
            zip(resolved_event_types, resolved_event_phases, strict=True),
            start=1,
        ):
            db.add(
                LiveEventRecord(
                    run_id=run_id,
                    event_id=index,
                    session_id=session_id,
                    type=event_type,
                    round=1,
                    phase=phase,
                    actor="SENTINEL_EVENT_ACTOR",
                    action="SENTINEL_EVENT_ACTION",
                    payload={
                        "prompt": "SENTINEL_EVENT_PROMPT",
                        "raw_response": "SENTINEL_RAW_RESPONSE",
                        "token": "SENTINEL_EVENT_TOKEN",
                    },
                    created_at=created_at + timedelta(seconds=index),
                )
            )
        all_voice_statuses = list(voice_statuses or [])
        all_voice_statuses.extend(["failed"] * voice_error_count)
        first_utterance_id: str | None = None
        for index, voice_status in enumerate(all_voice_statuses, start=1):
            utterance_id = f"utt_{run_id[-12:]}_{index:02d}"
            first_utterance_id = first_utterance_id or utterance_id
            db.add(
                VoiceUtteranceRecord(
                    utterance_id=utterance_id,
                    run_id=run_id,
                    session_id=session_id,
                    source_event_id=1,
                    last_source_event_id=1,
                    request_id=f"request-{index}",
                    speaker_kind="player",
                    speaker_name="SENTINEL_SPEAKER_NAME",
                    speaker="SENTINEL_SPEAKER_ID",
                    action="SENTINEL_VOICE_ACTION",
                    text="SENTINEL_VOICE_TEXT",
                    text_hash=f"hash-{run_id}-{index}",
                    audio_format="mp3",
                    sample_rate=24000,
                    mime_type="audio/mpeg",
                    status=voice_status,
                    error_message=(
                        f"tts api_key=SENTINEL_VOICE_KEY_{index}"
                        if voice_status == "failed"
                        else None
                    ),
                    created_at=created_at + timedelta(seconds=index),
                    updated_at=created_at + timedelta(seconds=index),
                )
            )
        if first_utterance_id is not None:
            db.add(
                VoiceAudioChunkRecord(
                    utterance_id=first_utterance_id,
                    chunk_index=0,
                    audio=b"SENTINEL_AUDIO_BYTES",
                    byte_length=20,
                    created_at=created_at,
                )
            )
        db.commit()


def _revision(
    *,
    revision_id: str,
    rule_set_id: str,
    revision_no: int,
    state: str,
    name: str,
    player_count: int,
    content_hash: str,
    now: datetime,
) -> RuleSetRevisionRecord:
    return RuleSetRevisionRecord(
        id=revision_id,
        rule_set_id=rule_set_id,
        revision_no=revision_no,
        state=state,
        schema_version=1,
        content_hash=content_hash,
        lock_version=1,
        name=name,
        description=f"{name} description",
        player_count=player_count,
        role_summary=f"{player_count} player history rule",
        complexity="history",
        estimated_duration="medium",
        config={"name": name},
        created_at=now,
        updated_at=now,
        published_at=now,
    )


def _seed_historical_revisions(context: AdminLiveRunsContext) -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    with context.session_factory() as db:
        db.add_all(
            [
                RuleSetRecord(
                    id=HISTORY_RULE_ID,
                    status="archived",
                    current_published_revision_id=HISTORY_REVISION_2_ID,
                    draft_revision_id=None,
                    is_default=False,
                    display_order=10,
                    lock_version=3,
                    created_at=now,
                    updated_at=now + timedelta(days=2),
                    archived_at=now + timedelta(days=2),
                ),
                RuleSetRecord(
                    id=OTHER_RULE_ID,
                    status="published",
                    current_published_revision_id=OTHER_REVISION_ID,
                    draft_revision_id=None,
                    is_default=False,
                    display_order=20,
                    lock_version=1,
                    created_at=now,
                    updated_at=now,
                ),
                _revision(
                    revision_id=HISTORY_REVISION_1_ID,
                    rule_set_id=HISTORY_RULE_ID,
                    revision_no=1,
                    state="superseded",
                    name="Historical Live Revision One",
                    player_count=6,
                    content_hash="5" * 64,
                    now=now,
                ),
                _revision(
                    revision_id=HISTORY_REVISION_2_ID,
                    rule_set_id=HISTORY_RULE_ID,
                    revision_no=2,
                    state="published",
                    name="Current Live Revision Two",
                    player_count=8,
                    content_hash="6" * 64,
                    now=now + timedelta(days=1),
                ),
                _revision(
                    revision_id=OTHER_REVISION_ID,
                    rule_set_id=OTHER_RULE_ID,
                    revision_no=1,
                    state="published",
                    name="Other Live Rule",
                    player_count=10,
                    content_hash="8" * 64,
                    now=now,
                ),
            ]
        )
        db.commit()


def test_admin_live_runs_requires_authentication_and_runs_read_permission(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unauthenticated = context.client.get("/api/v1/admin/live-runs")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["code"] == "admin_auth_required"

    _login(context, monkeypatch, role="viewer")
    allowed = context.client.get("/api/v1/admin/live-runs")
    assert allowed.status_code == 200

    monkeypatch.setattr(
        admin_dependencies,
        "permissions_for_role",
        lambda _role: frozenset({AdminPermission.GAMES_READ}),
    )
    forbidden = context.client.get("/api/v1/admin/live-runs")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "admin_permission_denied"
    assert "runs.read" in forbidden.json()["detail"]


def test_stop_live_run_requires_csrf_is_idempotent_and_audited(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _login(context, monkeypatch, role="operator")
    run = context.registry.create_run(
        session_id="game_10000001",
        villager_model="model-villager",
        werewolf_model="model-werewolf",
        seed=1,
        max_rounds=8,
    )
    context.registry.mark_running(run.run_id)
    path = f"/api/v1/admin/live-runs/{run.run_id}/stop"
    request_body = {"reason": "上游模型持续超时，人工停止"}

    missing_csrf = context.client.post(
        path,
        json=request_body,
        headers={"Idempotency-Key": "stop-live-run-001"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "admin_csrf_invalid"

    headers = {
        "X-CSRF-Token": login["csrf_token"],
        "Idempotency-Key": "stop-live-run-001",
    }
    foreign_registry = LiveRunRegistry(
        live_store=SessionLiveStore(context.session_factory),
        worker_id="worker-foreign-api",
    )
    context.client.app.dependency_overrides[get_live_registry] = lambda: foreign_registry
    accepted = context.client.post(path, json=request_body, headers=headers)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json() == {
        "action": "stop",
        "target_run_id": run.run_id,
        "run_id": run.run_id,
        "session_id": "game_10000001",
        "run_status": "running",
        "stop_requested_at": accepted.json()["stop_requested_at"],
        "replayed": False,
    }
    assert context.registry.stop_requested(run.run_id) is False
    context.registry.refresh_lease(run.run_id)
    assert context.registry.stop_requested(run.run_id) is True

    replay = context.client.post(path, json=request_body, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True

    conflict = context.client.post(
        path,
        json={"reason": "改用同一个键提交不同原因"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "admin_idempotency_conflict"

    with context.session_factory() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.live_run.stop"))
        persisted = db.get(LiveRunRecord, run.run_id)
        assert audit is not None
        assert audit.reason == request_body["reason"]
        assert persisted is not None
        assert persisted.stop_requested_at is not None


def test_resume_live_run_requires_persistent_resumable_state_and_returns_new_run(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _login(context, monkeypatch, role="operator")
    created_at = datetime(2026, 7, 11, 15, tzinfo=UTC)
    _seed_run(
        context,
        run_id="run_000000000090",
        session_id="game_00000090",
        created_at=created_at,
        status="failed",
        game_status="partial",
        resumable=True,
        winner=None,
    )

    def fake_start_resume_game_run(*, session_id, store, registry):
        del store
        return (
                registry.create_run(
                    session_id=session_id,
                    villager_model="model-villager",
                    werewolf_model="model-werewolf",
                    seed=90,
                    max_rounds=8,
                    parent_run_id="run_000000000090",
                    resume_from_round=1,
                    attempt_no=2,
                ),
            True,
        )

    monkeypatch.setattr(
        live_run_routes,
        "start_resume_game_run",
        fake_start_resume_game_run,
    )
    path = "/api/v1/admin/live-runs/run_000000000090/resume"
    headers = {
        "X-CSRF-Token": login["csrf_token"],
        "Idempotency-Key": "resume-live-run-001",
    }
    response = context.client.post(
        path,
        json={"reason": "模型服务恢复，继续检查点"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["action"] == "resume"
    assert payload["target_run_id"] == "run_000000000090"
    assert payload["run_id"] != payload["target_run_id"]
    assert payload["session_id"] == "game_00000090"
    assert payload["run_status"] == "queued"
    assert payload["replayed"] is False

    replay = context.client.post(
        path,
        json={"reason": "模型服务恢复，继续检查点"},
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["run_id"] == payload["run_id"]
    assert replay.json()["replayed"] is True

    with context.session_factory() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.live_run.resume"))
        assert audit is not None
        assert audit.after["run_id"] == payload["run_id"]


def test_resume_live_run_allows_a_stale_active_checkpoint_takeover(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _login(context, monkeypatch, role="operator")
    run_id = "run_000000000091"
    _seed_run(
        context,
        run_id=run_id,
        session_id="game_00000091",
        created_at=datetime(2026, 7, 11, 15, tzinfo=UTC),
        status="running",
        game_status="partial",
        resumable=True,
        winner=None,
        event_types=["run_created", "run_started"],
        event_phases=[None, None],
    )
    with context.session_factory() as db:
        record = db.get(LiveRunRecord, run_id)
        assert record is not None
        record.worker_id = "worker-missing"
        record.worker_heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=2)
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        record.fence_token = 1
        db.commit()

    def fake_start_resume_game_run(*, session_id, store, registry):
        del session_id, store
        resumed = registry.try_get_run(run_id)
        assert resumed is not None
        return resumed, True

    monkeypatch.setattr(
        live_run_routes,
        "start_resume_game_run",
        fake_start_resume_game_run,
    )
    response = context.client.post(
        f"/api/v1/admin/live-runs/{run_id}/resume",
        json={"reason": "Worker 已失联，从检查点安全接管"},
        headers={
            "X-CSRF-Token": login["csrf_token"],
            "Idempotency-Key": "resume-stale-run-001",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["run_id"] == run_id
    assert response.json()["run_status"] == "running"


def test_stop_claims_and_cancels_a_stale_run_with_a_new_fence_token(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _login(context, monkeypatch, role="operator")
    run = context.registry.create_run(
        session_id="game_10000002",
        villager_model="model-villager",
        werewolf_model="model-werewolf",
        seed=2,
        max_rounds=8,
    )
    context.registry.mark_running(run.run_id)
    original_fence = run.fence_token
    with context.session_factory() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.worker_heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=2)
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        record.recovery_attempts = 3
        db.commit()
    detail = context.client.get(f"/api/v1/admin/live-runs/{run.run_id}")
    assert detail.status_code == 200
    assert detail.json()["worker_state"] == "stale"
    assert detail.json()["is_stale"] is True
    assert detail.json()["recovery_exhausted"] is True

    response = context.client.post(
        f"/api/v1/admin/live-runs/{run.run_id}/stop",
        json={"reason": "Worker 租约过期，终止失联运行"},
        headers={
            "X-CSRF-Token": login["csrf_token"],
            "Idempotency-Key": "stop-stale-run-001",
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["run_status"] == "canceled"
    with context.session_factory() as db:
        saved = db.get(LiveRunRecord, run.run_id)
        assert saved is not None
        assert saved.status == "canceled"
        assert saved.winner is None
        assert saved.stop_requested_at is not None
        assert saved.worker_id == context.registry.worker_id
        assert saved.fence_token == original_fence + 1
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.live_run.stop",
                AuditEvent.resource_id == run.run_id,
            )
        )
        assert audit is not None
        assert audit.after["stale_worker"] is True


def test_admin_live_run_list_is_batched_filterable_stable_and_strictly_whitelisted(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 7, 11, 8, tzinfo=UTC)
    _seed_run(
        context,
        run_id="run_000000000001",
        session_id="game_00000001",
        created_at=base,
        updated_at=base + timedelta(hours=1),
        event_types=["run_started", "state_updated"],
        voice_statuses=[
            "pending",
            "synthesizing",
            "complete",
            "failed",
            "canceled",
            "SENTINEL_UNKNOWN_VOICE_STATUS",
        ],
    )
    _seed_run(
        context,
        run_id="run_000000000002",
        session_id="game_00000002",
        created_at=base + timedelta(hours=1),
        updated_at=base + timedelta(hours=2),
        status="running",
        game_status="partial",
        resumable=True,
        villager_model="SENTINEL_RUNNING_MODEL",
        werewolf_model="SENTINEL_RUNNING_WOLF_MODEL",
        winner="SENTINEL_RUNNING_WINNER",
        rule_set_id="starter_6",
        event_types=["model_thinking_tick"],
    )
    _seed_run(
        context,
        run_id="run_000000000003",
        session_id="game_00000003",
        created_at=base + timedelta(hours=2),
        updated_at=base + timedelta(hours=2),
        status="failed",
        villager_model="SENTINEL_FAILED_MODEL",
        werewolf_model="SENTINEL_FAILED_WOLF_MODEL",
        winner="SENTINEL_FAILED_WINNER",
        run_error="api_key=SENTINEL_RUN_KEY timeout",
    )
    monkeypatch.setattr(
        live_run_routes,
        "_utc_now",
        lambda: base + timedelta(hours=4),
    )
    _login(context, monkeypatch, role="viewer")

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lower())

    event.listen(context.engine, "before_cursor_execute", capture_sql)
    try:
        response = context.client.get(
            "/api/v1/admin/live-runs",
            params={"page": 1, "page_size": 2},
            headers={"X-Request-ID": "live-runs-list-1"},
        )
    finally:
        event.remove(context.engine, "before_cursor_execute", capture_sql)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "live-runs-list-1"
    payload = response.json()
    assert [item["run_id"] for item in payload["items"]] == [
        "run_000000000003",
        "run_000000000002",
    ]
    assert payload["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 3,
        "pages": 2,
    }
    failed_item, running_item = payload["items"]
    assert failed_item["villager_model"] is None
    assert failed_item["werewolf_model"] is None
    assert failed_item["winner"] is None
    assert failed_item["is_stale"] is False
    assert running_item["villager_model"] is None
    assert running_item["werewolf_model"] is None
    assert running_item["winner"] is None
    assert running_item["game"] == {
        "status": "partial",
        "resumable": True,
        "terminal": False,
    }
    assert running_item["event_count"] == 1
    assert running_item["last_activity_at"] == "2026-07-11T09:00:01Z"
    assert running_item["is_stale"] is True
    assert running_item["worker_state"] == "unassigned"
    assert running_item["worker_heartbeat_at"] is None

    data_statements = [
        sql
        for sql in statements
        if any(table in sql for table in ("live_runs", "live_events", "voice_utterances"))
    ]
    assert len(data_statements) == 4
    assert all("live_runs.player_configs" not in sql for sql in statements)
    assert all("live_runs.seed" not in sql for sql in statements)
    assert all("live_runs.lineup_quality_warnings" not in sql for sql in statements)
    assert all("live_runs.rule_set," not in sql for sql in statements)
    assert all("rule_set_revisions.config" not in sql for sql in statements)
    assert all("rule_set_revisions.description" not in sql for sql in statements)
    assert all("live_events.payload" not in sql for sql in statements)
    assert all("voice_utterances.text" not in sql for sql in statements)
    assert all("voice_utterances.error_message" not in sql for sql in statements)
    assert all("voice_audio_chunks" not in sql for sql in statements)
    count_sql = data_statements[0]
    assert "join game_sessions" not in count_sql
    assert "join rule_set_revisions" not in count_sql
    assert "live_runs.villager_model" not in count_sql

    first = context.client.get(
        "/api/v1/admin/live-runs",
        params={"page": 2, "page_size": 2},
    ).json()["items"][0]
    assert first["run_id"] == "run_000000000001"
    assert first["villager_model"] == "model-villager"
    assert first["winner"] == "好人阵营"
    assert first["worker_state"] == "released"
    assert first["voice_counts"] == {
        "total": 6,
        "pending": 1,
        "synthesizing": 1,
        "complete": 1,
        "failed": 1,
        "canceled": 1,
        "other": 1,
    }
    assert first["rule_set"] == {
        "id": "classic_8",
        "name": "classic_8",
        "player_count": None,
        "revision_id": None,
        "revision_no": None,
        "content_hash": None,
    }

    assert (
        context.client.get(
            "/api/v1/admin/live-runs",
            params={"q": "SENTINEL_RUNNING_MODEL"},
        ).json()["items"]
        == []
    )
    assert (
        len(
            context.client.get(
                "/api/v1/admin/live-runs",
                params={"q": "run_00000000000"},
            ).json()["items"]
        )
        == 3
    )
    assert [
        item["run_id"]
        for item in context.client.get(
            "/api/v1/admin/live-runs",
            params={"q": "game_00000002"},
        ).json()["items"]
    ] == ["run_000000000002"]
    assert [
        item["run_id"]
        for item in context.client.get(
            "/api/v1/admin/live-runs",
            params={"status": "running", "rule_set_id": "starter_6"},
        ).json()["items"]
    ] == ["run_000000000002"]
    assert [
        item["run_id"]
        for item in context.client.get(
            "/api/v1/admin/live-runs",
            params={"created_from": "2026-07-11T09:30:00+00:00"},
        ).json()["items"]
    ] == ["run_000000000003"]

    serialized = json.dumps(payload, ensure_ascii=False)
    for marker in (
        "SENTINEL_RUNNING_MODEL",
        "SENTINEL_RUNNING_WOLF_MODEL",
        "SENTINEL_RUNNING_WINNER",
        "SENTINEL_FAILED_MODEL",
        "SENTINEL_FAILED_WOLF_MODEL",
        "SENTINEL_FAILED_WINNER",
        "SENTINEL_RUN_KEY",
        "SENTINEL_PLAYER_NAME",
        "SENTINEL_PLAYER_ROLE",
        "SENTINEL_PLAYER_PROMPT",
        "SENTINEL_LINEUP_WARNING",
        "SENTINEL_RUN_RULE_NAME",
    ):
        assert marker not in serialized


def test_admin_live_runs_filter_and_render_exact_historical_rule_revisions(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_historical_revisions(context)
    base = datetime(2026, 7, 11, tzinfo=UTC)
    _seed_run(
        context,
        run_id="run_000000000201",
        session_id="game_00000201",
        created_at=base,
        rule_set_id=HISTORY_RULE_ID,
        rule_set_revision_id=HISTORY_REVISION_1_ID,
        rule_set_revision_no=1,
        rule_set_content_hash="5" * 64,
    )
    _seed_run(
        context,
        run_id="run_000000000202",
        session_id="game_00000202",
        created_at=base + timedelta(hours=1),
        rule_set_id=HISTORY_RULE_ID,
        rule_set_revision_id=HISTORY_REVISION_2_ID,
        rule_set_revision_no=2,
        rule_set_content_hash="6" * 64,
    )
    _seed_run(
        context,
        run_id="run_000000000203",
        session_id="game_00000203",
        created_at=base + timedelta(hours=2),
        rule_set_id=HISTORY_RULE_ID,
        rule_set_content_hash="7" * 64,
    )
    _seed_run(
        context,
        run_id="run_000000000204",
        session_id="game_00000204",
        created_at=base + timedelta(hours=3),
        rule_set_id=OTHER_RULE_ID,
        rule_set_revision_id=OTHER_REVISION_ID,
        rule_set_revision_no=1,
        rule_set_content_hash="8" * 64,
    )

    monkeypatch.setattr(
        live_run_routes,
        "get_rule_set",
        lambda _rule_set_id: (_ for _ in ()).throw(
            AssertionError("Admin history must not use the static rule catalog")
        ),
        raising=False,
    )
    _login(context, monkeypatch, role="viewer")

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lower())

    event.listen(context.engine, "before_cursor_execute", capture_sql)
    try:
        stable = context.client.get(
            "/api/v1/admin/live-runs",
            params={"rule_set_id": HISTORY_RULE_ID, "sort": "created_at"},
        )
    finally:
        event.remove(context.engine, "before_cursor_execute", capture_sql)
    exact = context.client.get(
        "/api/v1/admin/live-runs",
        params={"rule_set_revision_id": HISTORY_REVISION_1_ID},
    )
    impossible_pair = context.client.get(
        "/api/v1/admin/live-runs",
        params={
            "rule_set_id": HISTORY_RULE_ID,
            "rule_set_revision_id": OTHER_REVISION_ID,
        },
    )
    detail = context.client.get("/api/v1/admin/live-runs/run_000000000201")

    assert stable.status_code == 200, stable.text
    by_run = {item["run_id"]: item for item in stable.json()["items"]}
    assert list(by_run) == [
        "run_000000000201",
        "run_000000000202",
        "run_000000000203",
    ]
    assert by_run["run_000000000201"]["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": "Historical Live Revision One",
        "player_count": 6,
        "revision_id": HISTORY_REVISION_1_ID,
        "revision_no": 1,
        "content_hash": "5" * 64,
    }
    assert by_run["run_000000000202"]["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": "Current Live Revision Two",
        "player_count": 8,
        "revision_id": HISTORY_REVISION_2_ID,
        "revision_no": 2,
        "content_hash": "6" * 64,
    }
    assert by_run["run_000000000203"]["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": HISTORY_RULE_ID,
        "player_count": None,
        "revision_id": None,
        "revision_no": None,
        "content_hash": "7" * 64,
    }
    assert exact.status_code == 200
    assert [item["run_id"] for item in exact.json()["items"]] == ["run_000000000201"]
    assert impossible_pair.status_code == 200
    assert impossible_pair.json()["items"] == []
    assert detail.status_code == 200
    assert detail.json()["rule_set"] == by_run["run_000000000201"]["rule_set"]
    assert (
        len(
            [
                sql
                for sql in statements
                if any(
                    table in sql
                    for table in (
                        "live_runs",
                        "live_events",
                        "voice_utterances",
                        "rule_set_revisions",
                    )
                )
            ]
        )
        == 4
    )
    assert all("live_runs.rule_set," not in sql for sql in statements)
    assert all("rule_set_revisions.config" not in sql for sql in statements)
    assert all("rule_set_revisions.description" not in sql for sql in statements)


def test_admin_live_runs_rejects_invalid_pagination_status_and_time_range(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch, role="viewer")

    invalid_page = context.client.get("/api/v1/admin/live-runs", params={"page_size": 101})
    invalid_status = context.client.get("/api/v1/admin/live-runs", params={"status": "stopped"})
    missing_timezone = context.client.get(
        "/api/v1/admin/live-runs",
        params={"created_from": "2026-07-11T10:00:00"},
    )
    reversed_range = context.client.get(
        "/api/v1/admin/live-runs",
        params={
            "created_from": "2026-07-12T10:00:00+00:00",
            "created_to": "2026-07-11T10:00:00+00:00",
        },
    )

    assert invalid_page.status_code == 422
    assert invalid_page.json()["code"] == "admin_request_invalid"
    assert invalid_status.status_code == 422
    assert invalid_status.json()["code"] == "admin_request_invalid"
    assert missing_timezone.status_code == 422
    assert missing_timezone.json()["code"] == "admin_live_run_filter_invalid"
    assert reversed_range.status_code == 422
    assert reversed_range.json()["code"] == "admin_live_run_filter_invalid"


def test_completed_terminal_detail_returns_only_bounded_safe_event_metadata(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 11, 12, tzinfo=UTC)
    event_types = ["state_updated"] * 54 + ["SENTINEL_UNKNOWN_EVENT_TYPE"]
    event_phases = ["day"] * 54 + ["SENTINEL_UNKNOWN_PHASE"]
    _seed_run(
        context,
        run_id="run_000000000010",
        session_id="game_00000010",
        created_at=created_at,
        event_types=event_types,
        event_phases=event_phases,
        voice_statuses=["complete", "failed"],
        run_error="api_key=SENTINEL_RUN_ERROR",
    )
    with context.session_factory() as db:
        invalid_round = db.get(
            LiveEventRecord,
            {"run_id": "run_000000000010", "event_id": 54},
        )
        assert invalid_round is not None
        invalid_round.round = -7
        db.commit()
    _login(context, monkeypatch, role="viewer")

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lower())

    event.listen(context.engine, "before_cursor_execute", capture_sql)
    try:
        response = context.client.get("/api/v1/admin/live-runs/run_000000000010")
    finally:
        event.remove(context.engine, "before_cursor_execute", capture_sql)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["villager_model"] == "model-villager"
    assert payload["werewolf_model"] == "model-werewolf"
    assert payload["winner"] == "好人阵营"
    assert payload["event_count"] == 55
    assert len(payload["recent_events"]) == 50
    assert payload["recent_events"][0]["event_id"] == 6
    assert payload["recent_events"][-1]["event_id"] == 55
    assert payload["recent_events"][0]["type"] == "state_updated"
    assert payload["recent_events"][0]["actor"] == "SENTINEL_EVENT_ACTOR"
    assert payload["recent_events"][0]["action"] == "SENTINEL_EVENT_ACTION"
    assert payload["recent_events"][-2]["round"] is None
    assert payload["recent_events"][-1]["type"] == "unknown"
    assert payload["recent_events"][-1]["phase"] is None
    assert payload["is_stale"] is False

    serialized = json.dumps(payload, ensure_ascii=False)
    for marker in (
        "SENTINEL_UNKNOWN_EVENT_TYPE",
        "SENTINEL_UNKNOWN_PHASE",
        "SENTINEL_EVENT_PROMPT",
        "SENTINEL_RAW_RESPONSE",
        "SENTINEL_EVENT_TOKEN",
        "SENTINEL_RUN_ERROR",
        "SENTINEL_VOICE_TEXT",
        "SENTINEL_AUDIO_BYTES",
        "SENTINEL_RUN_RULE_NAME",
        "SENTINEL_ROLE_MAPPING",
    ):
        assert marker not in serialized
    assert all("live_events.payload" not in sql for sql in statements)
    assert all("live_runs.player_configs" not in sql for sql in statements)
    assert all("live_runs.seed" not in sql for sql in statements)
    assert all("live_runs.rule_set," not in sql for sql in statements)
    assert all("rule_set_revisions.config" not in sql for sql in statements)
    assert all("rule_set_revisions.description" not in sql for sql in statements)
    assert all("voice_audio_chunks" not in sql for sql in statements)


@pytest.mark.parametrize(
    ("run_status", "game_status", "resumable"),
    [
        ("running", "partial", True),
        ("failed", "complete", False),
        ("completed", "complete", True),
    ],
)
def test_non_revealable_detail_redacts_models_identity_and_generalizes_activity(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
    run_status: str,
    game_status: str,
    resumable: bool,
) -> None:
    suffix = {"running": "21", "failed": "22", "completed": "23"}[run_status]
    run_id = f"run_0000000000{suffix}"
    session_id = f"game_000000{suffix}"
    created_at = datetime(2026, 7, 11, 13, tzinfo=UTC)
    _seed_run(
        context,
        run_id=run_id,
        session_id=session_id,
        created_at=created_at,
        status=run_status,
        game_status=game_status,
        resumable=resumable,
        villager_model="SENTINEL_PRIVATE_MODEL",
        werewolf_model="SENTINEL_PRIVATE_WOLF_MODEL",
        winner="SENTINEL_PRIVATE_WINNER",
        event_types=[
            "run_started",
            "model_thinking_tick",
            "state_updated",
            "model_request_failed",
            "SENTINEL_PRIVATE_EVENT_TYPE",
            "action_requested",
            "phase_started",
        ],
        event_phases=[
            "night",
            "night",
            "night",
            "SENTINEL_PRIVATE_PHASE",
            "SENTINEL_PRIVATE_PHASE",
            "SENTINEL_PRIVATE_PHASE",
            "day",
        ],
    )
    _login(context, monkeypatch, role="viewer")
    monkeypatch.setattr(
        live_run_routes,
        "_utc_now",
        lambda: created_at + timedelta(hours=2),
    )

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lower())

    event.listen(context.engine, "before_cursor_execute", capture_sql)
    try:
        response = context.client.get(f"/api/v1/admin/live-runs/{run_id}")
    finally:
        event.remove(context.engine, "before_cursor_execute", capture_sql)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["villager_model"] is None
    assert payload["werewolf_model"] is None
    assert payload["winner"] is None
    assert [item["type"] for item in payload["recent_events"]] == [
        "run_started",
        "activity",
        "runtime_warning",
        "activity",
        "phase_started",
    ]
    assert all(item["actor"] is None for item in payload["recent_events"])
    assert all(item["action"] is None for item in payload["recent_events"])
    assert payload["recent_events"][3]["phase"] is None
    assert payload["is_stale"] is (run_status == "running")

    serialized = json.dumps(payload, ensure_ascii=False)
    for marker in (
        "SENTINEL_PRIVATE_MODEL",
        "SENTINEL_PRIVATE_WOLF_MODEL",
        "SENTINEL_PRIVATE_WINNER",
        "SENTINEL_EVENT_ACTOR",
        "SENTINEL_EVENT_ACTION",
        "SENTINEL_PRIVATE_EVENT_TYPE",
        "SENTINEL_PRIVATE_PHASE",
    ):
        assert marker not in serialized
    assert all("live_events.actor" not in sql for sql in statements)
    assert all("live_events.action" not in sql for sql in statements)
    assert all("live_events.payload" not in sql for sql in statements)

    model_probe = context.client.get(
        "/api/v1/admin/live-runs",
        params={"q": "SENTINEL_PRIVATE_MODEL"},
    )
    assert model_probe.status_code == 200
    assert model_probe.json()["items"] == []


def test_running_stale_uses_persisted_event_activity_and_injected_clock(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 11, 15, tzinfo=UTC)
    _seed_run(
        context,
        run_id="run_000000000030",
        session_id="game_00000030",
        created_at=now - timedelta(minutes=10),
        status="running",
        game_status="partial",
        resumable=True,
        event_types=["model_thinking_tick"],
    )
    with context.session_factory() as db:
        latest_event = db.get(
            LiveEventRecord,
            {"run_id": "run_000000000030", "event_id": 1},
        )
        assert latest_event is not None
        latest_event.created_at = now - timedelta(seconds=30)
        db.commit()
    monkeypatch.setattr(live_run_routes, "_utc_now", lambda: now)
    _login(context, monkeypatch, role="viewer")

    item = context.client.get("/api/v1/admin/live-runs").json()["items"][0]

    assert item["last_activity_at"] == "2026-07-11T14:59:30Z"
    assert item["is_stale"] is False


def test_live_run_debug_requires_minimal_permission_sanitizes_bounds_and_audits(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 11, 16, tzinfo=UTC)
    _seed_run(
        context,
        run_id="run_000000000040",
        session_id="game_00000040",
        created_at=created_at,
        status="failed",
        game_status="partial",
        resumable=True,
        run_error="401 authorization=Bearer SENTINEL_AUTH_TOKEN",
        voice_statuses=["failed"],
        voice_error_count=23,
    )
    with context.session_factory() as db:
        failed_without_message = db.get(
            VoiceUtteranceRecord,
            "utt_000000000040_01",
        )
        assert failed_without_message is not None
        failed_without_message.error_message = None
        db.commit()

    _login(context, monkeypatch, role="viewer")
    forbidden = context.client.get("/api/v1/admin/live-runs/run_000000000040/debug")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "admin_permission_denied"
    assert "runs.debug.read" in forbidden.json()["detail"]

    _login(context, monkeypatch, role="operator")
    response = context.client.get(
        "/api/v1/admin/live-runs/run_000000000040/debug",
        headers={"X-Request-ID": "live-run-debug-1"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["run_id"] == "run_000000000040"
    assert payload["run_error"] == "Upstream authentication or authorization failed"
    assert payload["voice_error_total"] == 24
    assert len(payload["voice_errors"]) == 20
    assert {item["error"] for item in payload["voice_errors"]} == {"Voice synthesis failed"}
    assert payload["truncated"] is True
    assert "SENTINEL" not in json.dumps(payload)
    assert "Bearer" not in json.dumps(payload)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "live-run-debug-1"

    with context.session_factory() as db:
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.live_run.debug.read")
        )
    assert audit is not None
    assert audit.resource_type == "live_run"
    assert audit.resource_id == "run_000000000040"
    assert audit.result == "success"
    assert audit.after == {
        "run_error_present": True,
        "voice_error_total": 24,
        "voice_error_returned": 20,
        "truncated": True,
    }


def test_live_run_detail_and_debug_return_problem_404(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch, role="super_admin")

    detail = context.client.get(
        "/api/v1/admin/live-runs/run_deadbeef0000",
        headers={"X-Request-ID": "missing-live-run-1"},
    )
    debug = context.client.get("/api/v1/admin/live-runs/run_deadbeef0000/debug")

    assert detail.status_code == 404
    assert detail.headers["content-type"].startswith("application/problem+json")
    assert detail.headers["cache-control"] == "no-store"
    assert detail.headers["x-request-id"] == "missing-live-run-1"
    assert detail.json()["code"] == "admin_live_run_not_found"
    assert debug.status_code == 404
    assert debug.json()["code"] == "admin_live_run_not_found"


def test_admin_games_do_not_expose_or_probe_partial_or_historical_run_metadata(
    context: AdminLiveRunsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_run(
        context,
        run_id="run_000000000050",
        session_id="game_00000050",
        created_at=datetime(2026, 7, 11, 17, tzinfo=UTC),
        status="running",
        game_status="partial",
        resumable=True,
        rule_set_id="starter_6",
        villager_model="SENTINEL_GAME_MODEL_ORACLE",
        werewolf_model="SENTINEL_GAME_WOLF_ORACLE",
        winner="SENTINEL_GAME_WINNER_ORACLE",
    )
    with context.session_factory() as db:
        game = db.get(GameSessionRecord, "game_00000050")
        assert game is not None
        game.rule_set = {
            "id": "classic_8",
            "name": "经典 8 人局",
            "player_count": 8,
        }
        db.commit()
    _login(context, monkeypatch, role="viewer")

    item = context.client.get("/api/v1/admin/games").json()["items"][0]
    model_probe = context.client.get(
        "/api/v1/admin/games", params={"q": "SENTINEL_GAME_MODEL_ORACLE"}
    )
    winner_probe = context.client.get(
        "/api/v1/admin/games", params={"q": "SENTINEL_GAME_WINNER_ORACLE"}
    )
    winner_filter = context.client.get(
        "/api/v1/admin/games",
        params={"winner": "SENTINEL_GAME_WINNER_ORACLE"},
    )
    historical_rule_filter = context.client.get(
        "/api/v1/admin/games", params={"rule_set_id": "starter_6"}
    )
    record_rule_filter = context.client.get(
        "/api/v1/admin/games", params={"rule_set_id": "classic_8"}
    )

    assert item["winner"] is None
    assert item["latest_run"]["villager_model"] is None
    assert item["latest_run"]["werewolf_model"] is None
    assert model_probe.json()["items"] == []
    assert winner_probe.json()["items"] == []
    assert winner_filter.json()["items"] == []
    assert [entry["session_id"] for entry in historical_rule_filter.json()["items"]] == [
        "game_00000050"
    ]
    assert record_rule_filter.json()["items"] == []


def test_admin_live_run_query_indexes_are_registered_and_migrated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_indexes = {index.name: index for index in LiveRunRecord.__table__.indexes}
    assert len(run_indexes["ix_live_runs_updated_at_run_id_desc"].expressions) == 2
    assert len(run_indexes["ix_live_runs_created_at_run_id_desc"].expressions) == 2
    assert len(run_indexes["ix_live_runs_status_updated_at_run_id_desc"].expressions) == 3
    voice_indexes = {index.name: index for index in VoiceUtteranceRecord.__table__.indexes}
    assert len(voice_indexes["ix_voice_utterances_run_status"].expressions) == 2

    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260711_05_add_admin_live_run_query_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("admin_live_run_query_indexes", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert isinstance(module, ModuleType)
    spec.loader.exec_module(module)

    created: list[tuple[str, str, list[object]]] = []
    dropped: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        module.op,
        "create_index",
        lambda name, table_name, columns: created.append((name, table_name, columns)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_index",
        lambda name, table_name=None: dropped.append((name, table_name)),
    )

    module.upgrade()
    module.downgrade()

    assert {item[0] for item in created} == {
        "ix_live_runs_updated_at_run_id_desc",
        "ix_live_runs_created_at_run_id_desc",
        "ix_live_runs_status_updated_at_run_id_desc",
        "ix_voice_utterances_run_status",
    }
    assert {
        ("ix_live_runs_updated_at_run_id_desc", "live_runs"),
        ("ix_live_runs_created_at_run_id_desc", "live_runs"),
        ("ix_live_runs_status_updated_at_run_id_desc", "live_runs"),
        ("ix_voice_utterances_run_status", "voice_utterances"),
    }.issubset(set(dropped))
