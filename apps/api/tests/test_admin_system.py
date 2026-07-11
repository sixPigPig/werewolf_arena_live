from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin.session import create_admin_session
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AdminSession, AuditEvent
from app.models.user import User


@dataclass
class AdminSystemContext:
    client: TestClient
    session_factory: sessionmaker[Session]
    principal_id: int
    csrf_token: str


@pytest.fixture
def system_context(monkeypatch) -> Generator[AdminSystemContext, None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "root@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Root Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "super_admin")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "system_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "admin_session_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "admin_oidc_enabled", False)
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
        login = client.post("/api/v1/admin/dev-login")
        assert login.status_code == 200
        payload = login.json()
        yield AdminSystemContext(
            client=client,
            session_factory=testing_session,
            principal_id=int(payload["user"]["id"]),
            csrf_token=payload["csrf_token"],
        )
    engine.dispose()


def _headers(context: AdminSystemContext, *, key: str | None = None) -> dict[str, str]:
    headers = {"X-CSRF-Token": context.csrf_token}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _create_payload(**overrides) -> dict:
    return {
        "email": "operator@example.test",
        "display_name": "Operations User",
        "role": "operator",
        "reason": "On-call operations access",
        **overrides,
    }


def test_user_list_filters_admins_and_exposes_only_safe_identity_state(
    system_context: AdminSystemContext,
) -> None:
    with system_context.session_factory() as db:
        db.add(
            User(
                email="guest@example.test",
                display_name="Guest",
                auth_provider="guest",
                auth_subject="browser-secret-subject",
                admin_role=None,
            )
        )
        db.add(
            User(
                email="viewer@example.test",
                display_name="Bound Viewer",
                auth_provider="oidc:provider-hash",
                auth_subject="private-enterprise-subject",
                admin_role="viewer",
                is_active=True,
            )
        )
        db.commit()

    response = system_context.client.get(
        "/api/v1/admin/users",
        params={"q": "viewer", "identity_status": "bound"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["pagination"]["total"] == 1
    item = response.json()["items"][0]
    assert item["email"] == "viewer@example.test"
    assert item["identity_status"] == "bound"
    assert "auth_provider" not in item
    assert "auth_subject" not in item
    assert "private-enterprise-subject" not in response.text
    assert "guest@example.test" not in response.text


def test_create_user_requires_csrf_is_idempotent_and_audited(
    system_context: AdminSystemContext,
) -> None:
    missing_csrf = system_context.client.post(
        "/api/v1/admin/users",
        headers={"Idempotency-Key": "create-operator-1"},
        json=_create_payload(),
    )
    assert missing_csrf.status_code == 403

    first = system_context.client.post(
        "/api/v1/admin/users",
        headers=_headers(system_context, key="create-operator-1"),
        json=_create_payload(),
    )
    repeated = system_context.client.post(
        "/api/v1/admin/users",
        headers=_headers(system_context, key="create-operator-1"),
        json=_create_payload(),
    )
    conflict = system_context.client.post(
        "/api/v1/admin/users",
        headers=_headers(system_context, key="create-operator-1"),
        json=_create_payload(role="viewer"),
    )

    assert first.status_code == repeated.status_code == 201
    assert first.json()["id"] == repeated.json()["id"]
    assert first.json()["version"] == 1
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "admin_idempotency_conflict"
    with system_context.session_factory() as db:
        assert db.scalar(
            select(func.count()).select_from(User).where(User.email == "operator@example.test")
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "admin.user.create",
                AuditEvent.result == "success",
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "admin.user.create",
                AuditEvent.result == "failure",
            )
        ) == 1


def test_update_user_enforces_version_self_protection_and_revokes_on_disable(
    system_context: AdminSystemContext,
) -> None:
    created = system_context.client.post(
        "/api/v1/admin/users",
        headers=_headers(system_context, key="create-disable-target"),
        json=_create_payload(),
    ).json()
    target_id = int(created["id"])
    with system_context.session_factory() as db:
        issued = create_admin_session(
            db,
            user_id=target_id,
            ttl_seconds=3600,
            ip_address="127.0.0.1",
            user_agent="test",
        )
        db.commit()
        target_session_id = issued.record.id

    updated = system_context.client.patch(
        f"/api/v1/admin/users/{target_id}",
        headers=_headers(system_context),
        json={
            "expected_version": 1,
            "display_name": "Updated Operator",
            "is_active": False,
            "reason": "Access removed",
        },
    )
    stale = system_context.client.patch(
        f"/api/v1/admin/users/{target_id}",
        headers=_headers(system_context),
        json={
            "expected_version": 1,
            "display_name": "Stale Change",
            "reason": "Concurrent edit",
        },
    )
    self_disable = system_context.client.patch(
        f"/api/v1/admin/users/{system_context.principal_id}",
        headers=_headers(system_context),
        json={
            "expected_version": 1,
            "is_active": False,
            "reason": "Unsafe self change",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Updated Operator"
    assert updated.json()["is_active"] is False
    assert updated.json()["version"] == 2
    assert updated.json()["active_session_count"] == 0
    assert stale.status_code == 409
    assert stale.json()["code"] == "admin_user_version_conflict"
    assert stale.json()["current"]["version"] == 2
    assert self_disable.status_code == 409
    assert self_disable.json()["code"] == "admin_user_self_protection"
    with system_context.session_factory() as db:
        session = db.get(AdminSession, target_session_id)
        assert session is not None and session.revoked_at is not None


def test_explicit_session_revocation_is_idempotent_and_audited(
    system_context: AdminSystemContext,
) -> None:
    created = system_context.client.post(
        "/api/v1/admin/users",
        headers=_headers(system_context, key="create-revoke-target"),
        json=_create_payload(),
    ).json()
    target_id = int(created["id"])
    with system_context.session_factory() as db:
        for _ in range(2):
            create_admin_session(
                db,
                user_id=target_id,
                ttl_seconds=3600,
                ip_address=None,
                user_agent=None,
            )
        db.commit()

    first = system_context.client.post(
        f"/api/v1/admin/users/{target_id}/revoke-sessions",
        headers=_headers(system_context),
        json={"reason": "Suspected account compromise"},
    )
    second = system_context.client.post(
        f"/api/v1/admin/users/{target_id}/revoke-sessions",
        headers=_headers(system_context),
        json={"reason": "Confirm sessions remain revoked"},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["revoked_count"] == 2
    assert second.json()["revoked_count"] == 0


def test_fixed_roles_protect_user_and_audit_routes(
    system_context: AdminSystemContext,
) -> None:
    with system_context.session_factory() as db:
        principal = db.get(User, system_context.principal_id)
        assert principal is not None
        principal.admin_role = "viewer"
        db.commit()

    users = system_context.client.get("/api/v1/admin/users")
    audit = system_context.client.get("/api/v1/admin/audit-events")

    assert users.status_code == audit.status_code == 403
    assert users.json()["code"] == "admin_permission_denied"


def test_audit_list_supports_filters_and_excludes_payloads(
    system_context: AdminSystemContext,
) -> None:
    system_context.client.post(
        "/api/v1/admin/users",
        headers=_headers(system_context, key="create-audit-target"),
        json=_create_payload(reason="Provision for audit test"),
    )

    response = system_context.client.get(
        "/api/v1/admin/audit-events",
        params={"action": "admin.user.create", "result": "success"},
    )

    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1
    item = response.json()["items"][0]
    assert item["actor"]["email"] == "root@example.test"
    assert item["action"] == "admin.user.create"
    assert item["reason"] == "Provision for audit test"
    assert "before" not in item
    assert "after" not in item
    assert "ip_address" not in item
    assert "operator@example.test" not in response.text

    invalid_range = system_context.client.get(
        "/api/v1/admin/audit-events",
        params={
            "created_from": datetime(2026, 7, 12, tzinfo=UTC).isoformat(),
            "created_to": datetime(2026, 7, 11, tzinfo=UTC).isoformat(),
        },
    )
    assert invalid_range.status_code == 422
    assert invalid_range.json()["code"] == "admin_audit_filter_invalid"
