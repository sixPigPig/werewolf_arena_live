from unittest.mock import Mock

from sqlalchemy.exc import SQLAlchemyError
from fastapi.testclient import TestClient

from app.api.routes import health
from app.db.session import get_db
from app.main import app


client = TestClient(app)


def test_read_health_returns_ok() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_liveness_does_not_require_database() -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_readiness_returns_ready_for_current_database_revision(monkeypatch) -> None:
    session = Mock()
    session.execute.side_effect = [Mock(), _revision_result("current-head")]
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(health.settings, "ark_tts_enabled", False)
    monkeypatch.setattr(health, "_expected_database_revisions", lambda: {"current-head"})
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "migrations": "ok"},
    }


def test_readiness_rejects_outdated_database_revision(monkeypatch) -> None:
    session = Mock()
    session.execute.side_effect = [Mock(), _revision_result("old-head")]
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(health, "_expected_database_revisions", lambda: {"current-head"})
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", "migrations": "outdated"},
    }


def test_readiness_requires_live_voice_materializer_when_tts_is_enabled(
    monkeypatch,
) -> None:
    session = Mock()
    session.execute.side_effect = [Mock(), _revision_result("current-head")]
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(health.settings, "ark_tts_enabled", True)
    monkeypatch.setattr(health, "_expected_database_revisions", lambda: {"current-head"})
    monkeypatch.setattr(health, "runtime_worker_is_alive", lambda *_args, **_kwargs: False)
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "database": "ok",
            "migrations": "ok",
            "live_voice_materializer": "unavailable",
        },
    }


def test_readiness_reports_live_voice_materializer_when_available(monkeypatch) -> None:
    session = Mock()
    session.execute.side_effect = [Mock(), _revision_result("current-head")]
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(health.settings, "ark_tts_enabled", True)
    monkeypatch.setattr(health, "_expected_database_revisions", lambda: {"current-head"})
    monkeypatch.setattr(health, "runtime_worker_is_alive", lambda *_args, **_kwargs: True)
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "migrations": "ok",
            "live_voice_materializer": "ok",
        },
    }


def test_readiness_hides_database_error_details() -> None:
    session = Mock()
    session.execute.side_effect = SQLAlchemyError("secret connection details")
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable", "migrations": "unknown"},
    }
    assert "secret" not in response.text


def _revision_result(*revisions: str) -> Mock:
    result = Mock()
    result.scalars.return_value = revisions
    return result
