from __future__ import annotations

import base64
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from urllib.parse import parse_qs, urlencode, urlparse

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import httpx
import jwt
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin.oidc import OidcIdentity, OidcProvider, oidc_provider_key
from app.api.routes import admin_auth
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AdminOidcLoginAttempt, AdminSession, AuditEvent
from app.models.user import User


@dataclass
class OidcTestContext:
    client: TestClient
    session_factory: sessionmaker[Session]
    provider: "FakeOidcProvider"


class FakeOidcProvider:
    def __init__(self) -> None:
        self.nonce = ""
        self.identity_email = "admin@example.test"
        self.identity_subject = "enterprise-subject-1"
        self.exchange_calls = 0

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        self.nonce = nonce
        return f"https://identity.example/authorize?{urlencode({'state': state})}"

    def exchange_code(self, *, code: str, code_verifier: str) -> OidcIdentity:
        self.exchange_calls += 1
        assert code == "authorization-code"
        assert len(code_verifier) >= 43
        return OidcIdentity(
            subject=self.identity_subject,
            email=self.identity_email,
            display_name="Enterprise Admin",
            nonce=self.nonce,
        )


@pytest.fixture
def oidc_context(monkeypatch) -> Generator[OidcTestContext, None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_oidc_enabled", True)
    monkeypatch.setattr(settings, "admin_oidc_issuer_url", "https://identity.example")
    monkeypatch.setattr(settings, "admin_oidc_client_id", "admin-web")
    monkeypatch.setattr(settings, "admin_oidc_client_secret", "secret")
    monkeypatch.setattr(
        settings,
        "admin_oidc_redirect_uri",
        "http://testserver/api/v1/admin/oidc/callback",
    )
    monkeypatch.setattr(settings, "admin_oidc_web_base_url", "https://admin.example")
    monkeypatch.setattr(settings, "admin_oidc_login_ttl_seconds", 600)
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

    provider = FakeOidcProvider()
    monkeypatch.setattr(admin_auth, "oidc_provider", provider)
    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application, follow_redirects=False) as client:
        yield OidcTestContext(client, testing_session, provider)
    engine.dispose()


def _provision(context: OidcTestContext) -> None:
    with context.session_factory() as db:
        db.add(
            User(
                email="admin@example.test",
                display_name="Provisioned Admin",
                admin_role="operator",
                is_active=True,
            )
        )
        db.commit()


def _start(context: OidcTestContext, return_to: str = "/operations/runs") -> str:
    response = context.client.get(
        "/api/v1/admin/oidc/start",
        params={"return_to": return_to},
    )
    assert response.status_code == 302, response.text
    assert response.headers["cache-control"] == "no-store"
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def test_oidc_login_binds_preprovisioned_user_and_issues_admin_session(
    oidc_context: OidcTestContext,
) -> None:
    _provision(oidc_context)
    options = oidc_context.client.get("/api/v1/admin/login-options")
    assert options.json() == {
        "oidc_enabled": True,
        "oidc_start_path": "/api/v1/admin/oidc/start",
    }
    state = _start(oidc_context)

    callback = oidc_context.client.get(
        "/api/v1/admin/oidc/callback",
        params={"code": "authorization-code", "state": state},
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == "https://admin.example/operations/runs"
    me = oidc_context.client.get("/api/v1/admin/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin@example.test"
    assert me.json()["user"]["role"] == "operator"
    with oidc_context.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.test"))
        assert user is not None
        assert user.auth_provider == oidc_provider_key()
        assert user.auth_subject == "enterprise-subject-1"
        assert db.scalar(select(func.count()).select_from(AdminSession)) == 1
        assert db.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "admin.session.oidc_login",
                AuditEvent.result == "success",
            )
        ) == 1


def test_oidc_callback_rejects_wrong_browser_binding_without_token_exchange(
    oidc_context: OidcTestContext,
) -> None:
    _provision(oidc_context)
    state = _start(oidc_context)
    oidc_context.client.cookies.clear()
    oidc_context.client.cookies.set(
        "werewolf_admin_session_oidc",
        "wrong-browser",
        path="/api/v1/admin",
    )

    response = oidc_context.client.get(
        "/api/v1/admin/oidc/callback",
        params={"code": "authorization-code", "state": state},
    )

    assert response.status_code == 303
    assert "oidcError=admin_oidc_invalid_state" in response.headers["location"]
    assert oidc_context.provider.exchange_calls == 0
    with oidc_context.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AdminSession)) == 0


def test_consumed_oidc_state_cannot_be_replayed(oidc_context: OidcTestContext) -> None:
    _provision(oidc_context)
    state = _start(oidc_context)
    browser_binding = oidc_context.client.cookies.get("werewolf_admin_session_oidc")
    first = oidc_context.client.get(
        "/api/v1/admin/oidc/callback",
        params={"code": "authorization-code", "state": state},
    )
    assert first.status_code == 303
    oidc_context.client.cookies.set(
        "werewolf_admin_session_oidc",
        browser_binding,
        path="/api/v1/admin",
    )

    replay = oidc_context.client.get(
        "/api/v1/admin/oidc/callback",
        params={"code": "authorization-code", "state": state},
    )

    assert replay.status_code == 303
    assert "oidcError=admin_oidc_invalid_state" in replay.headers["location"]
    assert oidc_context.provider.exchange_calls == 1
    with oidc_context.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AdminSession)) == 1


def test_oidc_login_rejects_unprovisioned_account_and_consumes_state(
    oidc_context: OidcTestContext,
) -> None:
    state = _start(oidc_context, return_to="//evil.example")

    response = oidc_context.client.get(
        "/api/v1/admin/oidc/callback",
        params={"code": "authorization-code", "state": state},
    )

    assert response.status_code == 303
    assert "oidcError=admin_oidc_account_not_provisioned" in response.headers["location"]
    assert "evil.example" not in response.headers["location"]
    with oidc_context.session_factory() as db:
        attempt = db.scalar(select(AdminOidcLoginAttempt))
        assert attempt is not None and attempt.consumed_at is not None
        assert db.scalar(select(func.count()).select_from(AdminSession)) == 0


def test_provider_verifies_signed_id_token_and_sends_pkce(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "admin_oidc_issuer_url", "https://identity.example")
    monkeypatch.setattr(settings, "admin_oidc_client_id", "admin-web")
    monkeypatch.setattr(settings, "admin_oidc_client_secret", "secret")
    monkeypatch.setattr(
        settings,
        "admin_oidc_redirect_uri",
        "https://api.example/api/v1/admin/oidc/callback",
    )
    monkeypatch.setattr(settings, "admin_oidc_client_auth_method", "client_secret_basic")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "signing-key", "alg": "RS256", "use": "sig"})
    now = datetime.now(UTC)
    id_token = jwt.encode(
        {
            "iss": "https://identity.example",
            "sub": "subject-1",
            "aud": "admin-web",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "nonce": "nonce-value-long-enough",
            "email": "Admin@Example.Test",
            "email_verified": True,
            "name": "Enterprise Admin",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "signing-key"},
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://identity.example",
                    "authorization_endpoint": "https://identity.example/authorize",
                    "token_endpoint": "https://identity.example/token",
                    "jwks_uri": "https://identity.example/jwks",
                },
            )
        if request.url.path == "/token":
            return httpx.Response(200, json={"id_token": id_token})
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    provider = OidcProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    authorize_url = provider.authorization_url(
        state="state-value",
        nonce="nonce-value-long-enough",
        code_verifier="v" * 64,
    )
    authorize_query = parse_qs(urlparse(authorize_url).query)
    identity = provider.exchange_code(code="authorization-code", code_verifier="v" * 64)

    assert authorize_query["code_challenge_method"] == ["S256"]
    assert authorize_query["nonce"] == ["nonce-value-long-enough"]
    assert identity.email == "admin@example.test"
    token_request = next(request for request in requests if request.url.path == "/token")
    assert token_request.headers["authorization"] == "Basic " + base64.b64encode(
        b"admin-web:secret"
    ).decode()
    assert b"code_verifier=" + (b"v" * 64) in token_request.content
