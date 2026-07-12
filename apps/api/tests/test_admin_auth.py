from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.admin.audit import record_audit_event
from app.admin.rbac import AdminPermission
from app.admin.session import hash_admin_secret
from app.api.admin.dependencies import AdminPrincipal, require_admin_permission
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AdminSession, AuditEvent
from app.models.user import User


@dataclass
class AdminTestContext:
    client: TestClient
    session_factory: sessionmaker[Session]


@pytest.fixture
def admin_context(monkeypatch) -> Generator[AdminTestContext, None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", False)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "configured-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Configured Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "super_admin")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "werewolf_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "admin_session_ttl_seconds", 3600)

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

    @application.get("/api/v1/admin/_test/overview")
    def overview_permission_probe(
        principal: Annotated[
            AdminPrincipal,
            Depends(require_admin_permission(AdminPermission.OVERVIEW_READ)),
        ],
    ) -> dict[str, str]:
        return {"email": principal.user.email}

    @application.get("/api/v1/admin/_test/users")
    def users_permission_probe(
        principal: Annotated[
            AdminPrincipal,
            Depends(require_admin_permission(AdminPermission.USERS_MANAGE)),
        ],
    ) -> dict[str, str]:
        return {"email": principal.user.email}

    with TestClient(application) as client:
        yield AdminTestContext(client=client, session_factory=testing_session)

    engine.dispose()


def _enable_dev_login(monkeypatch, *, role: str = "super_admin") -> None:
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_role", role)


def _login(context: AdminTestContext) -> tuple[dict, str]:
    response = context.client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload, payload["csrf_token"]


def test_me_requires_an_admin_session_and_returns_problem_details(
    admin_context: AdminTestContext,
) -> None:
    response = admin_context.client.get(
        "/api/v1/admin/me",
        headers={"X-Request-ID": "request-test-1"},
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-request-id"] == "request-test-1"
    assert response.json() == {
        "type": "urn:werewolf-arena:admin-problem:admin_auth_required",
        "title": "Authentication required",
        "status": 401,
        "detail": "A valid admin session is required.",
        "code": "admin_auth_required",
        "request_id": "request-test-1",
    }


def test_dev_login_is_disabled_by_default(admin_context: AdminTestContext) -> None:
    response = admin_context.client.post("/api/v1/admin/dev-login")

    assert response.status_code == 404
    assert response.json()["code"] == "admin_dev_login_disabled"
    assert response.headers["cache-control"] == "no-store"
    with admin_context.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(AdminSession)) == 0


def test_dev_login_remains_unavailable_in_production_when_flag_is_true(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "app_environment", "production")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_session_cookie_secure", True)

    response = admin_context.client.post("/api/v1/admin/dev-login")

    assert response.status_code == 404
    assert response.json()["code"] == "admin_dev_login_disabled"


def test_dev_login_rejects_request_selected_identity_and_role(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    _enable_dev_login(monkeypatch)

    response = admin_context.client.post(
        "/api/v1/admin/dev-login",
        json={
            "email": "attacker@example.test",
            "display_name": "Attacker",
            "role": "super_admin",
        },
    )

    assert response.status_code == 422
    with admin_context.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(AdminSession)) == 0


def test_dev_login_uses_server_identity_and_stores_only_secret_hashes(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    _enable_dev_login(monkeypatch)

    response = admin_context.client.post("/api/v1/admin/dev-login")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"] == {
        "id": "1",
        "email": "configured-admin@example.test",
        "display_name": "Configured Admin",
        "role": "super_admin",
    }
    assert set(payload["permissions"]) == {permission.value for permission in AdminPermission}
    assert payload["csrf_token"]
    assert payload["session_expires_at"].endswith(("Z", "+00:00"))
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"

    set_cookie = response.headers["set-cookie"]
    assert "werewolf_admin_session=" in set_cookie
    assert "werewolf_admin_session_csrf=" in set_cookie
    assert "Path=/api/v1/admin" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie

    raw_session_token = admin_context.client.cookies.get("werewolf_admin_session")
    raw_csrf_cookie = admin_context.client.cookies.get("werewolf_admin_session_csrf")
    assert raw_session_token is not None
    assert raw_csrf_cookie == payload["csrf_token"]
    assert len(raw_session_token) >= 64

    with admin_context.session_factory() as db:
        session = db.scalar(select(AdminSession))
        assert session is not None
        assert session.token_hash == hash_admin_secret(raw_session_token)
        assert session.token_hash != raw_session_token
        assert session.csrf_token_hash == hash_admin_secret(payload["csrf_token"])
        assert session.csrf_token_hash != payload["csrf_token"]

        audit_event = db.scalar(select(AuditEvent))
        assert audit_event is not None
        persisted_audit = json.dumps(
            {"before": audit_event.before, "after": audit_event.after, "reason": audit_event.reason}
        )
        assert raw_session_token not in persisted_audit
        assert payload["csrf_token"] not in persisted_audit


def test_me_returns_configured_identity_permissions_and_existing_csrf_token(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    _enable_dev_login(monkeypatch, role="operator")
    login_payload, csrf_token = _login(admin_context)

    response = admin_context.client.get("/api/v1/admin/me")

    assert response.status_code == 200
    assert response.json()["user"]["id"] == "1"
    assert response.json()["user"]["role"] == "operator"
    assert response.json()["csrf_token"] == csrf_token
    assert response.json()["session_expires_at"].endswith(("Z", "+00:00"))
    assert set(response.json()["permissions"]) == {
        "overview.read",
        "runs.read",
        "runs.debug.read",
        "runs.control",
        "games.read",
        "games.debug.read",
        "players.read",
        "rules.read",
        "voice.read",
        "settings.read",
    }
    assert response.json()["session_expires_at"] == login_payload["session_expires_at"]


@pytest.mark.parametrize("invalid_state", ["expired", "revoked", "inactive"])
def test_me_rejects_invalid_session_or_account_state_as_unauthenticated(
    admin_context: AdminTestContext,
    monkeypatch,
    invalid_state: str,
) -> None:
    _enable_dev_login(monkeypatch)
    _login(admin_context)

    with admin_context.session_factory() as db:
        session = db.scalar(select(AdminSession))
        assert session is not None
        user = db.get(User, session.user_id)
        assert user is not None
        if invalid_state == "expired":
            session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif invalid_state == "revoked":
            session.revoked_at = datetime.now(UTC)
        else:
            user.is_active = False
        db.commit()

    response = admin_context.client.get("/api/v1/admin/me")

    assert response.status_code == 401
    assert response.json()["code"] == "admin_auth_required"


def test_account_without_admin_role_is_forbidden(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    _enable_dev_login(monkeypatch)
    _login(admin_context)
    with admin_context.session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None
        user.admin_role = None
        db.commit()

    response = admin_context.client.get("/api/v1/admin/me")

    assert response.status_code == 403
    assert response.json()["code"] == "admin_permission_denied"


def test_permission_dependency_allows_and_denies_server_side(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    _enable_dev_login(monkeypatch, role="viewer")
    _login(admin_context)

    allowed = admin_context.client.get("/api/v1/admin/_test/overview")
    denied = admin_context.client.get("/api/v1/admin/_test/users")

    assert allowed.status_code == 200
    assert allowed.json() == {"email": "configured-admin@example.test"}
    assert denied.status_code == 403
    assert denied.headers["content-type"].startswith("application/problem+json")
    assert denied.json()["code"] == "admin_permission_denied"
    assert "users.manage" in denied.json()["detail"]


def test_logout_requires_valid_csrf_and_does_not_revoke_on_failure(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    _enable_dev_login(monkeypatch)
    _, csrf_token = _login(admin_context)

    missing = admin_context.client.post("/api/v1/admin/logout")
    invalid = admin_context.client.post(
        "/api/v1/admin/logout",
        headers={"X-CSRF-Token": f"{csrf_token}-invalid"},
    )

    assert missing.status_code == 403
    assert missing.json()["code"] == "admin_csrf_invalid"
    assert invalid.status_code == 403
    assert invalid.json()["code"] == "admin_csrf_invalid"
    with admin_context.session_factory() as db:
        session = db.scalar(select(AdminSession))
        assert session is not None
        assert session.revoked_at is None


def test_logout_revokes_session_clears_cookies_and_is_audited(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    _enable_dev_login(monkeypatch)
    _, csrf_token = _login(admin_context)

    response = admin_context.client.post(
        "/api/v1/admin/logout",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert admin_context.client.cookies.get("werewolf_admin_session") is None
    assert admin_context.client.cookies.get("werewolf_admin_session_csrf") is None
    assert admin_context.client.get("/api/v1/admin/me").status_code == 401

    with admin_context.session_factory() as db:
        session = db.scalar(select(AdminSession))
        assert session is not None
        assert session.revoked_at is not None
        events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at)))
        assert [event.action for event in events] == [
            "admin.session.dev_login",
            "admin.session.logout",
        ]
        assert events[-1].resource_id == session.id


def test_custom_cookie_name_does_not_accept_default_cookie_alias(
    admin_context: AdminTestContext,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "admin_session_cookie_name", "custom_admin_session")
    _enable_dev_login(monkeypatch)
    _login(admin_context)
    raw_token = admin_context.client.cookies.get("custom_admin_session")
    assert raw_token is not None

    admin_context.client.cookies.clear()
    rejected = admin_context.client.get(
        "/api/v1/admin/me",
        headers={"Cookie": f"werewolf_admin_session={raw_token}"},
    )
    accepted = admin_context.client.get(
        "/api/v1/admin/me",
        headers={"Cookie": f"custom_admin_session={raw_token}"},
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_audit_event_redacts_nested_secrets_and_free_text(
    admin_context: AdminTestContext,
) -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/admin/test",
            "headers": [(b"x-request-id", b"audit-redaction-test")],
            "client": ("127.0.0.1", 1234),
        }
    )
    raw_values = {
        "access": "raw-access-token",
        "refresh": "raw-refresh-token",
        "csrf": "raw-csrf-token",
        "password": "raw-password",
        "authorization": "raw-bearer-value",
        "cookie": "raw-cookie-value",
    }

    with admin_context.session_factory() as db:
        record_audit_event(
            db,
            request=request,
            actor_user_id=None,
            action="admin.test",
            resource_type="test",
            resource_id="safe-resource-id",
            result="failure",
            reason=json.dumps(
                {
                    "message": f"upstream ?access_token={raw_values['access']}&x=1",
                    "authorization": f"Bearer {raw_values['authorization']}",
                    "bearer_note": f"Bearer {raw_values['authorization']}",
                }
            ),
            before={
                "access_token": raw_values["access"],
                "nested": {
                    "refresh-token": raw_values["refresh"],
                    "note": f"Cookie={raw_values['cookie']}",
                    "description": f"refresh_token={raw_values['refresh']}",
                    "safe": "visible",
                },
            },
            after={
                "csrf_token": raw_values["csrf"],
                "password": raw_values["password"],
                "status": "rejected",
            },
        )
        db.commit()
        event = db.scalar(select(AuditEvent))
        assert event is not None
        serialized = json.dumps(
            {"before": event.before, "after": event.after, "reason": event.reason}
        )

    for raw_value in raw_values.values():
        assert raw_value not in serialized
    assert event.before["access_token"] == "[REDACTED]"
    assert event.before["nested"]["refresh-token"] == "[REDACTED]"
    assert event.before["nested"]["note"] == "Cookie=[REDACTED]"
    assert event.before["nested"]["description"] == "refresh_token=[REDACTED]"
    assert event.before["nested"]["safe"] == "visible"
    assert event.after["csrf_token"] == "[REDACTED]"
    assert json.loads(event.reason) == {
        "message": "upstream ?access_token=[REDACTED]",
        "authorization": "[REDACTED]",
        "bearer_note": "Bearer [REDACTED]",
    }


def test_configured_api_prefix_is_used_for_auth_cookie_path(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/internal/v2/")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "prefix-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Prefix Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "viewer")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "prefix_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "admin_session_ttl_seconds", 3600)

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
        login = client.post("/internal/v2/admin/dev-login")
        me = client.get("/internal/v2/admin/me")

    assert login.status_code == 200
    assert "Path=/internal/v2/admin" in login.headers["set-cookie"]
    assert me.status_code == 200
    engine.dispose()
