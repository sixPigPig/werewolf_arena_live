from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.liveness_rollout import LivenessRolloutConfigRecord
from app.models.user import User


@pytest.fixture
def rollout_admin_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "rollout@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Rollout Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "super_admin")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "rollout_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "public_session_cookie_secure", False)
    monkeypatch.setattr(settings, "werewolf_liveness_experiment_id", "env-liveness-v1")
    monkeypatch.setattr(settings, "werewolf_liveness_rollout_percent", 17)

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


def _login(client: TestClient) -> dict:
    response = client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text
    return response.json()


def _payload(*, expected_revision: int = 0, percent: int = 25) -> dict:
    return {
        "expected_revision": expected_revision,
        "experience_revision": "liveness-v1",
        "experiment_id": "lifelike-july-canary",
        "treatment_percent": percent,
        "change_reason": "扩大活人感版本观察样本",
    }


def test_liveness_rollout_requires_admin_session(rollout_admin_client) -> None:
    client, _ = rollout_admin_client
    response = client.get("/api/v1/admin/liveness-rollout")
    assert response.status_code == 401


def test_liveness_rollout_reads_environment_until_first_admin_save(
    rollout_admin_client,
) -> None:
    client, _ = rollout_admin_client
    _login(client)

    response = client.get("/api/v1/admin/liveness-rollout")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "revision": 0,
        "experience_revision": "liveness-v1",
        "experiment_id": "env-liveness-v1",
        "treatment_percent": 17,
        "control_percent": 83,
        "source": "environment_fallback",
        "effective_scope": "new_sessions_only",
        "updated_at": None,
        "available_experiences": [
            {
                "revision": "liveness-v1",
                "label": "活人感体验 V1",
                "description": "角色心智、分句流式语音、情绪表达和可打断播报的第一版组合。",
                "control_summary": "保留异步质量观察与影子心智，不启用分句语音、情绪投递和打断。",
                "treatment_summary": "启用角色心智读取、分句语音、情绪投递、预取和确定性打断。",
            }
        ],
    }


def test_liveness_rollout_save_persists_audits_and_requires_csrf(
    rollout_admin_client,
) -> None:
    client, session_factory = rollout_admin_client
    login = _login(client)

    missing_csrf = client.put("/api/v1/admin/liveness-rollout", json=_payload())
    assert missing_csrf.status_code == 403

    saved = client.put(
        "/api/v1/admin/liveness-rollout",
        headers={"X-CSRF-Token": login["csrf_token"]},
        json=_payload(),
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert saved.json()["source"] == "database"
    assert saved.json()["treatment_percent"] == 25
    with session_factory() as db:
        record = db.get(LivenessRolloutConfigRecord, "default")
        assert record is not None
        assert record.experiment_id == "lifelike-july-canary"
        assert record.treatment_percent == 25
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.liveness_rollout.update")
        )
        assert audit is not None
        assert audit.reason == "扩大活人感版本观察样本"
        assert audit.before["source"] == "environment_fallback"
        assert audit.after["revision"] == 1


def test_liveness_rollout_rejects_stale_page_and_reports_current_revision(
    rollout_admin_client,
) -> None:
    client, _ = rollout_admin_client
    login = _login(client)
    headers = {"X-CSRF-Token": login["csrf_token"]}
    assert (
        client.put("/api/v1/admin/liveness-rollout", headers=headers, json=_payload()).status_code
        == 200
    )

    stale = client.put(
        "/api/v1/admin/liveness-rollout",
        headers=headers,
        json=_payload(expected_revision=0, percent=50),
    )

    assert stale.status_code == 409
    assert stale.json()["code"] == "admin_liveness_rollout_conflict"
    assert stale.json()["current_revision"] == 1


def test_liveness_rollout_write_requires_settings_manage(
    rollout_admin_client,
) -> None:
    client, session_factory = rollout_admin_client
    login = _login(client)
    with session_factory() as db:
        user = db.get(User, int(login["user"]["id"]))
        assert user is not None
        user.admin_role = "viewer"
        db.commit()

    readable = client.get("/api/v1/admin/liveness-rollout")
    denied = client.put(
        "/api/v1/admin/liveness-rollout",
        headers={"X-CSRF-Token": login["csrf_token"]},
        json=_payload(),
    )

    assert readable.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["code"] == "admin_permission_denied"


@pytest.mark.parametrize(
    "override",
    [
        {"experience_revision": "future-v9"},
        {"experiment_id": "bad experiment id"},
        {"treatment_percent": 101},
        {"expected_revision": 0.0},
    ],
)
def test_liveness_rollout_rejects_invalid_updates(
    rollout_admin_client,
    override: dict,
) -> None:
    client, _ = rollout_admin_client
    login = _login(client)
    payload = {**_payload(), **override}

    response = client.put(
        "/api/v1/admin/liveness-rollout",
        headers={"X-CSRF-Token": login["csrf_token"]},
        json=payload,
    )

    assert response.status_code == 422
