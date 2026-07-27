from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.game_session import GameSessionRecord
from app.models.judge_voice_asset import JudgeVoiceGenerationJob
from app.models.live import LiveRunRecord
from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.models.runtime_worker import RuntimeWorkerRecord
from app.models.virtual_player_profile import VirtualPlayerProfile


@pytest.fixture
def dashboard_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "dashboard@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Dashboard Viewer")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "viewer")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "dashboard_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "public_session_cookie_secure", False)

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application) as client:
        yield client, testing_session
    engine.dispose()


def _login(client: TestClient) -> None:
    response = client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text


def _seed_dashboard(session_factory: sessionmaker[Session]) -> dict[str, str]:
    now = datetime.now(tz=UTC)
    job_id = "11111111-1111-4111-8111-111111111111"
    queued_job_id = "22222222-2222-4222-8222-222222222222"
    with session_factory() as db:
        db.add_all(
            [
                VirtualPlayerProfile(
                    id="profile-night-owl",
                    display_name="夜枭",
                    model="model-a",
                    status="draft",
                    published_at=None,
                ),
                VirtualPlayerProfile(
                    id="profile-wolf-shadow",
                    display_name="狼影",
                    model="model-a",
                    status="published",
                    published_at=now,
                    featured=True,
                ),
                GameSessionRecord(
                    session_id="game-session-alpha",
                    status="complete",
                    winner="villagers",
                    round_count=3,
                    resumable=False,
                ),
                GameSessionRecord(
                    session_id="game-session-retry",
                    status="partial",
                    round_count=1,
                    resumable=True,
                ),
                LiveRunRecord(
                    run_id="run-stale-alpha",
                    session_id="game-session-retry",
                    status="running",
                    villager_model="model-a",
                    werewolf_model="model-b",
                    max_rounds=5,
                    rule_set_id="classic",
                    player_configs=[],
                    lease_expires_at=now - timedelta(minutes=5),
                    recovery_attempts=settings.live_run_reaper_max_attempts,
                ),
                LiveRunRecord(
                    run_id="run-complete-beta",
                    session_id="game-session-alpha",
                    status="completed",
                    villager_model="model-a",
                    werewolf_model="model-b",
                    max_rounds=5,
                    rule_set_id="classic",
                    player_configs=[],
                ),
                JudgeVoiceGenerationJob(
                    id=job_id,
                    actor_user_id=None,
                    mode="all",
                    requested_line_ids=None,
                    idempotency_key="dashboard-failed-job",
                    request_hash="a" * 64,
                    status="failed",
                    total_count=10,
                    processed_count=3,
                    generated_count=2,
                    skipped_count=0,
                    failed_count=1,
                    error_code="provider_unavailable",
                    created_at=now - timedelta(minutes=10),
                    completed_at=now - timedelta(minutes=9),
                ),
                JudgeVoiceGenerationJob(
                    id=queued_job_id,
                    actor_user_id=None,
                    mode="missing",
                    requested_line_ids=None,
                    idempotency_key="dashboard-queued-job",
                    request_hash="b" * 64,
                    status="queued",
                    created_at=now,
                ),
                RuntimeWorkerRecord(
                    worker_id="dashboard-reaper",
                    worker_type="live_run_reaper",
                    status="running",
                    started_at=now,
                    heartbeat_at=now,
                ),
            ]
        )
        db.commit()
    return {"job_id": job_id, "queued_job_id": queued_job_id}


@pytest.mark.parametrize("path", ["/overview", "/jobs", "/settings", "/search?q=run"])
def test_dashboard_endpoints_require_admin_session(dashboard_client, path: str) -> None:
    client, _session_factory = dashboard_client
    response = client.get(f"/api/v1/admin{path}")
    assert response.status_code == 401
    assert response.json()["code"] == "admin_auth_required"


def test_overview_returns_real_counts_and_actionable_alerts(dashboard_client) -> None:
    client, session_factory = dashboard_client
    _seed_dashboard(session_factory)
    _login(client)

    response = client.get("/api/v1/admin/overview")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["environment"] == "test"
    assert body["profiles"] == {
        "total": 2,
        "draft": 1,
        "published": 1,
        "archived": 0,
        "featured": 1,
    }
    assert body["games"] == {
        "total": 2,
        "complete": 1,
        "incomplete": 1,
        "resumable": 1,
    }
    assert body["runs"]["running"] == 1
    assert body["runs"]["stale"] == 1
    assert body["runs"]["recovery_exhausted"] == 1
    assert body["jobs"]["queued"] == 1
    assert body["jobs"]["failed"] == 1
    assert body["reaper_up"] is True
    assert {alert["code"] for alert in body["alerts"]} == {
        "live_run_recovery_exhausted",
        "voice_jobs_failed",
        "voice_jobs_queued",
    }
    assert "api_key" not in response.text.lower()


def test_overview_quality_uses_bounded_safe_aggregates_and_small_sample_semantics(
    dashboard_client,
) -> None:
    client, session_factory = dashboard_client
    _seed_dashboard(session_factory)
    now = datetime.now(tz=UTC)
    marker = "SENTINEL_PRIVATE_QUALITY_TEXT"
    with session_factory() as db:
        db.add_all(
            [
                GameSessionRecord(
                    session_id="game-quality-failed",
                    status="complete",
                    round_count=1,
                    resumable=False,
                    updated_at=now,
                ),
                GameSessionRecord(
                    session_id="game-quality-legacy",
                    status="complete",
                    round_count=1,
                    resumable=False,
                    updated_at=now,
                ),
                GameQualityEvaluationRecord(
                    id="quality-dashboard-fail",
                    session_id="game-session-alpha",
                    evaluator_version="p3-v1",
                    source_revision="a" * 64,
                    status="completed",
                    data_status="partial",
                    verdict="fail",
                    completed_at=now,
                    safe_summary={
                        "issue_counts": {"P0": 1, "P1": 0, "P2": 0},
                        "facts": {
                            "critical_opportunity_count": 4,
                            "critical_recorded_count": 3,
                            "prompt_expected_critical_count": 8,
                            "prompt_included_critical_count": 7,
                        },
                        "voice": {
                            "narratable_event_count": 5,
                            "effective_voice_event_count": 4,
                        },
                        "performance": {
                            "action_count": 10,
                            "action_duration_histogram": {
                                "count": 10,
                                "buckets": {"1": 2, "5": 10, "+Inf": 10},
                            },
                        },
                        "content": {
                            "speech_check_count": 6,
                            "repeated_speech_count": 1,
                            "speech_retry_exhausted_count": 1,
                            "lineup_warning_count": 2,
                        },
                        "private_text": marker,
                    },
                ),
                GameQualityEvaluationRecord(
                    id="quality-dashboard-pending",
                    session_id="game-session-retry",
                    evaluator_version="p3-v1",
                    source_revision="b" * 64,
                    status="pending",
                    data_status="collecting",
                    verdict="unavailable",
                    created_at=now - timedelta(minutes=2),
                    not_before=now - timedelta(minutes=2),
                ),
                GameQualityEvaluationRecord(
                    id="quality-dashboard-worker-failed",
                    session_id="game-quality-failed",
                    evaluator_version="p3-v1",
                    source_revision="c" * 64,
                    status="failed",
                    data_status="unavailable",
                    verdict="unavailable",
                    completed_at=now,
                ),
                RuntimeWorkerRecord(
                    worker_id="dashboard-quality-worker",
                    worker_type="quality_evaluation",
                    status="running",
                    started_at=now,
                    heartbeat_at=now,
                ),
            ]
        )
        db.commit()
    _login(client)

    response = client.get("/api/v1/admin/overview")

    assert response.status_code == 200, response.text
    quality = response.json()["quality"]
    assert quality["cohort_days"] == 7
    assert quality["sample_count"] == 1
    assert quality["fail_count"] == 1
    assert quality["partial_count"] == 1
    assert quality["legacy_count"] == 1
    assert quality["p0_game_count"] == 1
    assert quality["pending_count"] == 1
    assert quality["worker_failed_count"] == 1
    assert quality["worker_up"] is True
    assert quality["oldest_pending_seconds"] >= 119
    assert quality["critical_fact_expected"] == 4
    assert quality["critical_fact_recorded"] == 3
    assert quality["prompt_fact_expected"] == 8
    assert quality["prompt_fact_included"] == 7
    assert quality["voice_expected"] == 5
    assert quality["voice_covered"] == 4
    assert quality["action_sample_count"] == 10
    assert quality["action_p95_ms"] is None
    assert {alert["code"] for alert in response.json()["alerts"]} >= {
        "quality_p0_detected",
        "quality_evaluation_failed",
    }
    assert marker not in response.text


def test_jobs_list_filters_paginates_and_hides_request_payload(dashboard_client) -> None:
    client, session_factory = dashboard_client
    seeded = _seed_dashboard(session_factory)
    _login(client)

    response = client.get(
        "/api/v1/admin/jobs",
        params={"status": "failed", "page": 1, "page_size": 10},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pagination"] == {"page": 1, "page_size": 10, "total": 1, "pages": 1}
    assert body["items"][0]["id"] == seeded["job_id"]
    assert body["items"][0]["error_code"] == "provider_unavailable"
    for forbidden in ("requested_line_ids", "idempotency_key", "request_hash", "actor_user_id"):
        assert forbidden not in response.text


def test_settings_only_returns_safe_operational_configuration(dashboard_client) -> None:
    client, _session_factory = dashboard_client
    _login(client)

    response = client.get("/api/v1/admin/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "test"
    assert body["authentication"]["development_login_enabled"] is True
    assert body["compatibility"]["legacy_content_writes_enabled"] is False
    assert body["live_runs"]["heartbeat_seconds"] < body["live_runs"]["lease_seconds"]
    for forbidden in ("client_secret", "api_key", "database_url", "issuer_url"):
        assert forbidden not in response.text.lower()


def test_global_search_respects_safe_resource_projections(dashboard_client) -> None:
    client, session_factory = dashboard_client
    seeded = _seed_dashboard(session_factory)
    _login(client)

    run_response = client.get("/api/v1/admin/search", params={"q": "run-"})
    player_response = client.get("/api/v1/admin/search", params={"q": "夜"})
    job_response = client.get(
        "/api/v1/admin/search",
        params={"q": seeded["job_id"][:8]},
    )

    assert run_response.status_code == 200
    assert {item["type"] for item in run_response.json()["items"]} == {"run"}
    assert player_response.status_code == 200
    assert player_response.json()["items"][0]["href"] == (
        "/content/players/profile-night-owl"
    )
    assert job_response.json()["items"][0]["href"].startswith("/system/jobs?job=")
    assert "villager_model" not in run_response.text

    too_short = client.get("/api/v1/admin/search", params={"q": " "})
    assert too_short.status_code == 422
