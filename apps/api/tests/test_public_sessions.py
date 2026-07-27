from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.model_configuration import ModelConfigurationRecord
from app.models.public import PublicSession, UserFavoritePlayerProfile
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.public.rate_limit import (
    SlidingWindowRateLimiter,
    public_favorite_write_limiter,
    public_session_creation_limiter,
)
from app.public.session import hash_public_secret

MOBILE_ORIGIN = "http://localhost:5174"


@dataclass(frozen=True)
class PublicTestContext:
    client: TestClient
    application: object
    session_factory: sessionmaker[Session]


@pytest.fixture
def public_context(monkeypatch: pytest.MonkeyPatch) -> PublicTestContext:
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "public_session_cookie_name", "test_public_session")
    monkeypatch.setattr(settings, "public_session_cookie_secure", False)
    monkeypatch.setattr(settings, "public_session_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "public_cors_origins", [MOBILE_ORIGIN])
    monkeypatch.setattr(settings, "cors_origins", [MOBILE_ORIGIN])
    monkeypatch.setattr(settings, "legacy_player_profile_content_writes_enabled", False)
    monkeypatch.setattr(settings, "legacy_player_profile_favorite_writes_enabled", False)
    public_session_creation_limiter.reset()
    public_favorite_write_limiter.reset()

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    application = create_application()

    def override_get_db():
        with testing_session() as db:
            yield db

    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application) as client:
        yield PublicTestContext(
            client=client,
            application=application,
            session_factory=testing_session,
        )

    application.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
    public_session_creation_limiter.reset()
    public_favorite_write_limiter.reset()


def _bootstrap(client: TestClient):
    response = client.post(
        "/api/v1/public/session",
        headers={"Origin": MOBILE_ORIGIN, "X-Request-ID": "public-session-test"},
    )
    assert response.status_code == 200, response.text
    return response


def _seed_profiles(context: PublicTestContext) -> None:
    now = datetime.now(UTC)
    with context.session_factory() as db:
        db.add_all(
            [
                ModelConfigurationRecord(
                    provider="deepseek",
                    model_id="test-model",
                    source_model_id="test-model",
                    display_name="test-model",
                    available=True,
                    enabled=True,
                    is_default=True,
                    supports_thinking=True,
                    parameter_values={"thinking": "default"},
                    source_details={"source": "test"},
                ),
                VirtualPlayerProfile(
                    id="published-profile",
                    display_name="已发布玩家",
                    model_provider="deepseek",
                    model="test-model",
                    status="published",
                    published_at=now,
                    favorite=True,
                    featured=True,
                    display_order=17,
                    avatar_image_url="https://tracker.example/avatar.png",
                ),
                VirtualPlayerProfile(
                    id="draft-profile",
                    display_name="草稿玩家",
                    model_provider="deepseek",
                    model="test-model",
                    status="draft",
                    published_at=None,
                ),
                VirtualPlayerProfile(
                    id="archived-profile",
                    display_name="归档玩家",
                    model_provider="deepseek",
                    model="test-model",
                    status="archived",
                    published_at=now - timedelta(days=1),
                    deleted_at=now,
                ),
            ]
        )
        db.commit()


def _favorite_headers(csrf_token: str, *, origin: str = MOBILE_ORIGIN) -> dict[str, str]:
    return {"Origin": origin, "X-CSRF-Token": csrf_token}


def test_public_session_is_server_issued_hash_only_idempotent_and_private(
    public_context: PublicTestContext,
) -> None:
    first = _bootstrap(public_context.client)
    payload = first.json()
    raw_session_token = public_context.client.cookies.get("test_public_session")
    raw_csrf_cookie = public_context.client.cookies.get("test_public_session_csrf")

    assert payload["viewer"] == {"kind": "guest"}
    assert "id" not in payload["viewer"]
    assert payload["csrf_token"] == raw_csrf_cookie
    assert raw_session_token is not None
    assert first.headers["cache-control"] == "private, no-store"
    assert first.headers["x-request-id"] == "public-session-test"
    set_cookies = first.headers.get_list("set-cookie")
    assert any(
        "test_public_session=" in value
        and "HttpOnly" in value
        and "Path=/api/v1" in value
        and "SameSite=lax" in value
        for value in set_cookies
    )
    assert any(
        "test_public_session_csrf=" in value
        and "HttpOnly" not in value
        and "Path=/api/v1/public" in value
        for value in set_cookies
    )

    with public_context.session_factory() as db:
        session = db.scalar(select(PublicSession))
        user = db.scalar(select(User))
    assert session is not None
    assert user is not None
    assert user.auth_provider == "guest"
    assert user.auth_subject
    assert user.admin_role is None
    assert session.token_hash == hash_public_secret(raw_session_token)
    assert session.token_hash != raw_session_token
    assert session.csrf_token_hash == hash_public_secret(payload["csrf_token"])
    assert session.csrf_token_hash != payload["csrf_token"]

    second = _bootstrap(public_context.client)
    assert second.json()["csrf_token"] == payload["csrf_token"]
    with public_context.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(PublicSession)) == 1


def test_public_session_cookie_authenticates_god_view_routes(
    public_context: PublicTestContext,
) -> None:
    live_path = "/api/v1/games/runs/run_missing/god-view/events"
    playback_path = "/api/v1/games/game_deadbeef/god-view/playback"

    assert public_context.client.get(live_path).status_code == 401
    assert public_context.client.get(playback_path).status_code == 401

    _bootstrap(public_context.client)

    assert public_context.client.get(live_path).status_code == 404
    assert public_context.client.get(playback_path).status_code == 404


def test_public_bootstrap_rejects_foreign_origin_without_replacing_identity(
    public_context: PublicTestContext,
) -> None:
    first = _bootstrap(public_context.client)
    original_cookie = public_context.client.cookies.get("test_public_session")

    rejected = public_context.client.post(
        "/api/v1/public/session",
        headers={"Origin": "https://evil.example"},
    )

    assert rejected.status_code == 403
    assert rejected.json()["detail"]["code"] == "public_origin_invalid"
    assert rejected.headers["cache-control"] == "private, no-store"
    assert public_context.client.cookies.get("test_public_session") == original_cookie
    assert first.json()["viewer"] == {"kind": "guest"}


def test_admin_cookie_never_authenticates_or_creates_a_public_principal(
    public_context: PublicTestContext,
) -> None:
    public_context.client.cookies.set(
        settings.admin_session_cookie_name,
        "forged-admin-session",
        path="/",
    )

    response = public_context.client.get("/api/v1/public/me")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "public_session_required"
    assert response.headers["cache-control"] == "private, no-store"
    with public_context.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(PublicSession)) == 0


def test_favorites_are_isolated_idempotent_and_never_mutate_global_profile(
    public_context: PublicTestContext,
) -> None:
    _seed_profiles(public_context)
    client_a = public_context.client
    client_b = TestClient(public_context.application)
    session_a = _bootstrap(client_a).json()
    session_b = _bootstrap(client_b).json()

    first = client_a.put(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers={
            **_favorite_headers(session_a["csrf_token"]),
            "X-User-ID": "999999",
        },
        json={"user_id": 999999},
    )
    duplicate = client_a.put(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers=_favorite_headers(session_a["csrf_token"]),
    )
    list_a = client_a.get("/api/v1/public/me/favorite-player-profiles")
    list_b = client_b.get("/api/v1/public/me/favorite-player-profiles")
    delete_b = client_b.delete(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers=_favorite_headers(session_b["csrf_token"]),
    )
    delete_b_again = client_b.delete(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers=_favorite_headers(session_b["csrf_token"]),
    )
    list_a_after = client_a.get("/api/v1/public/me/favorite-player-profiles")

    assert first.status_code == duplicate.status_code == 200
    assert first.json() == {"profile_id": "published-profile", "is_favorite": True}
    assert list_a.json() == {"profile_ids": ["published-profile"]}
    assert list_b.json() == {"profile_ids": []}
    assert delete_b.json() == delete_b_again.json() == {
        "profile_id": "published-profile",
        "is_favorite": False,
    }
    assert list_a_after.json() == {"profile_ids": ["published-profile"]}
    assert list_a.headers["cache-control"] == "private, no-store"

    with public_context.session_factory() as db:
        profile = db.get(VirtualPlayerProfile, "published-profile")
        favorites = list(db.scalars(select(UserFavoritePlayerProfile)))
    assert profile is not None
    assert profile.favorite is True
    assert profile.featured is True
    assert profile.display_order == 17
    assert profile.version == 1
    assert len(favorites) == 1
    client_b.close()


def test_public_favorite_requires_session_csrf_allowed_origin_and_published_profile(
    public_context: PublicTestContext,
) -> None:
    _seed_profiles(public_context)
    anonymous = public_context.client.put(
        "/api/v1/public/me/favorite-player-profiles/published-profile"
    )
    session = _bootstrap(public_context.client).json()
    missing_csrf = public_context.client.put(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers={"Origin": MOBILE_ORIGIN},
    )
    wrong_csrf = public_context.client.put(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers=_favorite_headers("wrong-token"),
    )
    foreign_origin = public_context.client.put(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers=_favorite_headers(
            session["csrf_token"],
            origin="https://evil.example",
        ),
    )
    admin_origin = public_context.client.put(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers=_favorite_headers(
            session["csrf_token"],
            origin="http://localhost:5175",
        ),
    )
    draft = public_context.client.put(
        "/api/v1/public/me/favorite-player-profiles/draft-profile",
        headers=_favorite_headers(session["csrf_token"]),
    )
    archived = public_context.client.put(
        "/api/v1/public/me/favorite-player-profiles/archived-profile",
        headers=_favorite_headers(session["csrf_token"]),
    )

    assert anonymous.status_code == 401
    assert missing_csrf.status_code == wrong_csrf.status_code == 403
    assert foreign_origin.status_code == 403
    assert foreign_origin.json()["detail"]["code"] == "public_origin_invalid"
    assert admin_origin.status_code == 403
    assert admin_origin.json()["detail"]["code"] == "public_origin_invalid"
    assert draft.status_code == archived.status_code == 404
    assert draft.json()["detail"]["code"] == "public_player_profile_not_found"


def test_expired_public_session_never_resolves_to_another_guest_and_is_cleaned(
    public_context: PublicTestContext,
) -> None:
    _seed_profiles(public_context)
    session = _bootstrap(public_context.client).json()
    favorite = public_context.client.put(
        "/api/v1/public/me/favorite-player-profiles/published-profile",
        headers=_favorite_headers(session["csrf_token"]),
    )
    assert favorite.status_code == 200
    with public_context.session_factory() as db:
        old_session = db.scalar(select(PublicSession))
        assert old_session is not None
        old_user_id = old_session.user_id
        old_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    expired = public_context.client.get("/api/v1/public/me/favorite-player-profiles")
    replacement = _bootstrap(public_context.client)

    assert expired.status_code == 401
    assert replacement.json()["viewer"] == {"kind": "guest"}
    with public_context.session_factory() as db:
        assert db.get(User, old_user_id) is None
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert (
            db.scalar(select(func.count()).select_from(UserFavoritePlayerProfile))
            == 0
        )


def test_public_catalog_is_shared_cacheable_and_drops_legacy_external_avatars(
    public_context: PublicTestContext,
) -> None:
    _seed_profiles(public_context)

    response = public_context.client.get(
        "/api/v1/public/player-profiles?page=1&page_size=100",
        headers={"X-Request-ID": "public-catalog-test"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["x-request-id"] == "public-catalog-test"
    assert [item["id"] for item in response.json()["items"]] == [
        "published-profile"
    ]
    assert response.json()["items"][0]["avatar_image_url"] == ""
    assert "favorite" not in response.json()["items"][0]


def test_sliding_window_limiter_has_a_hard_key_cap_and_reclaims_expired_keys() -> None:
    limiter = SlidingWindowRateLimiter(max_keys=2)

    assert limiter.allow("a", limit=10, window_seconds=60, now=1)
    assert limiter.allow("b", limit=10, window_seconds=60, now=1)
    assert not limiter.allow("c", limit=10, window_seconds=60, now=1)
    assert limiter.allow("c", limit=10, window_seconds=60, now=62)
