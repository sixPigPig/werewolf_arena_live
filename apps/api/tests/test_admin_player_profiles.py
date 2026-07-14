from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin.rbac import AdminPermission
from app.api.admin.errors import admin_request_validation_handler
from app.api.routes.player_profiles import get_player_profile_ai_provider
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.player_profiles.errors import PlayerProfileVersionConflict
from app.player_profiles.service import update_player_profile
from app.werewolf.providers import configured_model_options


@dataclass(frozen=True)
class AdminProfilesContext:
    client: TestClient
    session_factory: sessionmaker[Session]


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> Generator[AdminProfilesContext, None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "profiles-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Profiles Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "super_admin")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "profiles_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "admin_session_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "legacy_player_profile_content_writes_enabled", False)

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
        yield AdminProfilesContext(client=client, session_factory=testing_session)
    engine.dispose()


def _login(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "super_admin",
) -> tuple[dict, str]:
    monkeypatch.setattr(settings, "admin_dev_auth_role", role)
    response = context.client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload, payload["csrf_token"]


def _model_name() -> str:
    return configured_model_options()[0]["id"]


class StubAiDraftProvider:
    def __init__(self, response: str | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _create_draft(
    context: AdminProfilesContext,
    csrf_token: str,
    *,
    display_name: str = "雾夜司南",
) -> dict:
    response = context.client.post(
        "/api/v1/admin/player-profiles",
        headers={"X-CSRF-Token": csrf_token},
        json={"display_name": display_name, "model": _model_name()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _transition(
    context: AdminProfilesContext,
    csrf_token: str,
    profile: dict,
    action: str,
) -> dict:
    response = context.client.post(
        f"/api/v1/admin/player-profiles/{profile['id']}/{action}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_version": profile["version"],
            "reason": f"测试{action}玩家档案",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_admin_validation_problem_uses_the_configured_api_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_v1_prefix", "/custom/v2")
    application = FastAPI()
    application.add_exception_handler(
        RequestValidationError,
        admin_request_validation_handler,
    )

    @application.get("/custom/v2/admin/probe")
    def probe(value: int) -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(application).get(
        "/custom/v2/admin/probe",
        params={"value": "not-an-integer"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "admin_request_invalid"
    assert response.json()["errors"][0]["field"] == "query.value"


def test_admin_create_is_draft_and_uses_exact_safe_response_contract(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)

    response = context.client.post(
        "/api/v1/admin/player-profiles",
        headers={"X-CSRF-Token": csrf_token, "X-Request-ID": "profiles-create-1"},
        json={
            "display_name": "  雾夜司南  ",
            "model": _model_name(),
            "short_description": "冷静盘票",
        },
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "profiles-create-1"
    payload = response.json()
    assert payload["display_name"] == "雾夜司南"
    assert payload["status"] == "draft"
    assert payload["version"] == 1
    assert payload["published_at"] is None
    assert payload["published_by"] is None
    assert payload["featured"] is False
    assert {
        "favorite",
        "owner_user_id",
        "avatar_prompt",
        "avatar_image_path",
    }.isdisjoint(payload)

    with context.session_factory() as db:
        profile = db.get(VirtualPlayerProfile, payload["id"])
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.player_profile.create")
        )
    assert profile is not None
    assert profile.published_at is None
    assert audit is not None
    assert audit.result == "success"


@pytest.mark.parametrize(
    "forbidden_field",
    ["favorite", "avatar_image_url", "avatar_image_path", "owner_user_id", "status", "version"],
)
def test_admin_create_rejects_forbidden_mass_assignment_fields(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
    forbidden_field: str,
) -> None:
    _, csrf_token = _login(context, monkeypatch)
    value: object = "https://tracker.example/avatar.png"
    if forbidden_field in {"favorite"}:
        value = True
    if forbidden_field in {"owner_user_id", "version"}:
        value = 1
    if forbidden_field == "status":
        value = "published"

    response = context.client.post(
        "/api/v1/admin/player-profiles",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "display_name": "越权字段测试",
            "model": _model_name(),
            forbidden_field: value,
        },
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "admin_request_invalid"
    assert any(
        error["field"] == forbidden_field for error in response.json()["errors"]
    )


def test_admin_create_rejects_unconfigured_model_and_missing_csrf(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)

    invalid_model = context.client.post(
        "/api/v1/admin/player-profiles",
        headers={"X-CSRF-Token": csrf_token},
        json={"display_name": "未知模型", "model": "not-configured-model"},
    )
    missing_csrf = context.client.post(
        "/api/v1/admin/player-profiles",
        json={"display_name": "无 CSRF", "model": _model_name()},
    )

    assert invalid_model.status_code == 422
    assert invalid_model.json()["code"] == "admin_player_profile_invalid"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "admin_csrf_invalid"
    with context.session_factory() as db:
        failures = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "admin.player_profile.create",
                    AuditEvent.result == "failure",
                )
            )
        )
    assert len(failures) == 1
    assert failures[0].resource_id is None
    assert failures[0].reason == (
        "The selected model is not configured for this deployment."
    )
    assert failures[0].after == {
        "display_name": "未知模型",
        "model": "not-configured-model",
        "target_status": "draft",
    }


def test_admin_update_and_transition_reject_extra_fields(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)
    draft = _create_draft(context, csrf_token)

    update = context.client.patch(
        f"/api/v1/admin/player-profiles/{draft['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_version": draft["version"],
            "display_name": "新名字",
            "avatar_image_url": "https://tracker.example/avatar.png",
            "favorite": True,
            "status": "published",
        },
    )
    transition = context.client.post(
        f"/api/v1/admin/player-profiles/{draft['id']}/publish",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_version": draft["version"],
            "reason": "准备发布档案",
            "featured": True,
        },
    )

    assert update.status_code == 422
    assert update.json()["code"] == "admin_request_invalid"
    assert {error["field"] for error in update.json()["errors"]} >= {
        "avatar_image_url",
        "favorite",
        "status",
    }
    assert transition.status_code == 422
    assert transition.json()["code"] == "admin_request_invalid"
    assert {error["field"] for error in transition.json()["errors"]} == {"featured"}


def test_lifecycle_controls_public_visibility_versions_and_audit(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)
    draft = _create_draft(context, csrf_token)
    hidden = context.client.get(f"/api/v1/public/player-profiles/{draft['id']}")

    published = _transition(context, csrf_token, draft, "publish")
    visible = context.client.get(f"/api/v1/public/player-profiles/{draft['id']}")
    archived = _transition(context, csrf_token, published, "archive")
    hidden_again = context.client.get(f"/api/v1/public/player-profiles/{draft['id']}")
    restored = _transition(context, csrf_token, archived, "restore")
    visible_again = context.client.get(f"/api/v1/public/player-profiles/{draft['id']}")

    assert hidden.status_code == 404
    assert published["status"] == "published"
    assert published["version"] == 2
    assert published["published_at"] is not None
    assert published["published_by"] == "1"
    assert visible.status_code == 200
    assert archived["status"] == "archived"
    assert archived["version"] == 3
    assert archived["deleted_at"] is not None
    assert archived["featured"] is False
    assert hidden_again.status_code == 404
    assert restored["status"] == "published"
    assert restored["version"] == 4
    assert restored["deleted_at"] is None
    assert restored["published_at"] != published["published_at"]
    assert visible_again.status_code == 200

    with context.session_factory() as db:
        actions = list(
            db.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.resource_id == draft["id"])
                .order_by(AuditEvent.created_at.asc())
            )
        )
    assert actions == [
        "admin.player_profile.create",
        "admin.player_profile.publish",
        "admin.player_profile.archive",
        "admin.player_profile.restore",
    ]


def test_stale_update_returns_409_current_version_and_audits_both_versions(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)
    draft = _create_draft(context, csrf_token)
    first = context.client.patch(
        f"/api/v1/admin/player-profiles/{draft['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 1, "short_description": "第一次更新"},
    )

    stale = context.client.patch(
        f"/api/v1/admin/player-profiles/{draft['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 1, "short_description": "过期更新"},
    )

    assert first.status_code == 200
    assert first.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["code"] == "admin_player_profile_version_conflict"
    assert stale.json()["current_version"] == 2
    with context.session_factory() as db:
        conflict = db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.action == "admin.player_profile.update",
                AuditEvent.result == "conflict",
            )
            .order_by(AuditEvent.created_at.desc())
        )
    assert conflict is not None
    assert conflict.after == {"expected_version": 1, "current_version": 2}


def test_mapper_version_rejects_a_real_two_session_lost_update(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'version-race.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as seed:
        seed.add(
            VirtualPlayerProfile(
                id="concurrent-profile",
                display_name="并发玩家",
                model="legacy-model",
                status="published",
                published_at=datetime.now(UTC),
            )
        )
        seed.commit()

    first = factory()
    second = factory()
    try:
        first_loaded = first.get(VirtualPlayerProfile, "concurrent-profile")
        second_loaded = second.get(VirtualPlayerProfile, "concurrent-profile")
        assert first_loaded is not None
        assert second_loaded is not None
        update_player_profile(
            first,
            "concurrent-profile",
            updates={"short_description": "first writer"},
            expected_version=None,
            actor_user_id=None,
            allow_external_avatar_url=True,
        )
        first.commit()

        with pytest.raises(PlayerProfileVersionConflict):
            update_player_profile(
                second,
                "concurrent-profile",
                updates={"short_description": "stale writer"},
                expected_version=None,
                actor_user_id=None,
                allow_external_avatar_url=True,
            )
        second.rollback()
    finally:
        first.close()
        second.close()

    with factory() as verify:
        persisted = verify.get(VirtualPlayerProfile, "concurrent-profile")
    assert persisted is not None
    assert persisted.short_description == "first writer"
    assert persisted.version == 2
    engine.dispose()


def test_transition_requires_reason_and_rejects_invalid_state_with_409(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)
    draft = _create_draft(context, csrf_token)

    missing_reason = context.client.post(
        f"/api/v1/admin/player-profiles/{draft['id']}/publish",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": draft["version"]},
    )
    invalid_archive = context.client.post(
        f"/api/v1/admin/player-profiles/{draft['id']}/archive",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": draft["version"], "reason": "草稿不能归档"},
    )

    assert missing_reason.status_code == 422
    assert missing_reason.json()["code"] == "admin_request_invalid"
    assert invalid_archive.status_code == 409
    assert invalid_archive.json()["code"] == "admin_player_profile_transition_conflict"
    assert invalid_archive.json()["current_version"] == 1


def test_admin_list_filters_sorts_and_paginates(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)
    first = _create_draft(context, csrf_token, display_name="Alpha 分析")
    _create_draft(context, csrf_token, display_name="Beta 控场")
    _transition(context, csrf_token, first, "publish")

    response = context.client.get(
        "/api/v1/admin/player-profiles",
        params={
            "page": 1,
            "page_size": 1,
            "q": "Alpha",
            "status": "published",
            "personality_id": "balanced",
            "sort": "-updated_at",
        },
    )

    assert response.status_code == 200
    assert [item["display_name"] for item in response.json()["items"]] == ["Alpha 分析"]
    assert response.json()["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total": 1,
        "pages": 1,
    }


def test_options_and_role_permission_matrix(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, viewer_csrf = _login(context, monkeypatch, role="viewer")
    options = context.client.get("/api/v1/admin/player-profile-options")
    create_as_viewer = context.client.post(
        "/api/v1/admin/player-profiles",
        headers={"X-CSRF-Token": viewer_csrf},
        json={"display_name": "Viewer", "model": _model_name()},
    )

    assert options.status_code == 200
    assert options.json()["models"]
    assert options.json()["personalities"]
    assert options.json()["appearances"]
    assert options.json()["strategies"]
    assert {option["id"]: option["label"] for option in options.json()["strategies"]} == {
        "balanced": "均衡观察",
        "logic_leader": "逻辑带队",
        "shadow_wolf": "阴影潜伏",
        "social_reader": "社交阅读",
        "pressure_attacker": "强压进攻",
        "cautious_observer": "谨慎观察",
    }
    assert all(
        isinstance(option["avatar_image_url"], str)
        for option in options.json()["appearances"]
    )
    assert create_as_viewer.status_code == 403
    assert create_as_viewer.json()["code"] == "admin_permission_denied"

    _, editor_csrf = _login(context, monkeypatch, role="content_editor")
    created = _create_draft(context, editor_csrf, display_name="Editor")
    assert created["status"] == "draft"

    _login(context, monkeypatch, role="operator")
    assert context.client.get("/api/v1/admin/player-profiles").status_code == 200
    operator_write = context.client.patch(
        f"/api/v1/admin/player-profiles/{created['id']}",
        headers={"X-CSRF-Token": context.client.cookies.get("profiles_admin_session_csrf") or ""},
        json={"expected_version": created["version"], "display_name": "Nope"},
    )
    assert operator_write.status_code == 403


def test_published_update_needs_publish_permission_in_addition_to_write(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)
    draft = _create_draft(context, csrf_token)
    published = _transition(context, csrf_token, draft, "publish")

    monkeypatch.setattr(
        "app.api.admin.dependencies.permissions_for_role",
        lambda _role: frozenset(
            {AdminPermission.PLAYERS_READ, AdminPermission.PLAYERS_WRITE}
        ),
    )
    response = context.client.patch(
        f"/api/v1/admin/player-profiles/{published['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_version": published["version"],
            "short_description": "不应成功",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "admin_permission_denied"
    with context.session_factory() as db:
        persisted = db.get(VirtualPlayerProfile, published["id"])
    assert persisted is not None
    assert persisted.short_description == ""


def test_admin_can_preserve_an_existing_unconfigured_model_but_cannot_change_to_one(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, csrf_token = _login(context, monkeypatch)
    with context.session_factory() as db:
        db.add(
            VirtualPlayerProfile(
                id="legacy-model-profile",
                display_name="旧模型玩家",
                model="retired-model",
                status="published",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

    unchanged = context.client.patch(
        "/api/v1/admin/player-profiles/legacy-model-profile",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_version": 1,
            "model": "retired-model",
            "short_description": "保留旧模型并更新说明",
        },
    )
    changed = context.client.patch(
        "/api/v1/admin/player-profiles/legacy-model-profile",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 2, "model": "another-retired-model"},
    )

    assert unchanged.status_code == 200
    assert unchanged.json()["version"] == 2
    assert changed.status_code == 422
    assert changed.json()["code"] == "admin_player_profile_invalid"
    with context.session_factory() as db:
        failed_update = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.player_profile.update",
                AuditEvent.resource_id == "legacy-model-profile",
                AuditEvent.result == "failure",
            )
        )
    assert failed_update is not None
    assert failed_update.reason == (
        "The selected model is not configured for this deployment."
    )


def test_public_response_is_published_only_and_recursively_omits_internal_fields(
    context: AdminProfilesContext,
) -> None:
    now = datetime.now(UTC)
    with context.session_factory() as db:
        db.add_all(
            [
                VirtualPlayerProfile(
                    id="published-profile",
                    display_name="公开玩家",
                    model="legacy-model",
                    personality_id="balanced",
                    personality_text="公开人格",
                    appearance_id="default",
                    avatar_prompt="internal prompt",
                    avatar_image_url="https://legacy.example/avatar.png",
                    avatar_image_path="/secret/path.png",
                    avatar_image_mime="image/png",
                    status="published",
                    published_at=now,
                    owner_user_id=42,
                    display_order=1,
                ),
                VirtualPlayerProfile(
                    id="draft-profile",
                    display_name="草稿玩家",
                    model="legacy-model",
                    status="draft",
                    published_at=None,
                    display_order=2,
                ),
            ]
        )
        db.commit()

    response = context.client.get("/api/v1/public/player-profiles?page_size=100")
    admin_response = context.client.get("/api/v1/admin/player-profiles/published-profile")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["published-profile"]
    forbidden = {
        "owner_user_id",
        "avatar_prompt",
        "avatar_image_path",
        "avatar_asset_id",
        "avatar_image_mime",
        "favorite",
        "status",
        "version",
        "published_by",
        "updated_by",
        "deleted_at",
    }
    assert forbidden.isdisjoint(response.json()["items"][0])
    assert admin_response.status_code == 401


def test_admin_never_returns_legacy_external_avatar_url(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch)
    with context.session_factory() as db:
        db.add(
            VirtualPlayerProfile(
                id="external-avatar-profile",
                display_name="旧外链头像",
                model="legacy-model",
                avatar_image_url="https://tracker.example/avatar.png",
                status="published",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

    response = context.client.get(
        "/api/v1/admin/player-profiles/external-avatar-profile"
    )

    assert response.status_code == 200
    assert response.json()["avatar_image_url"] == ""


def test_legacy_gate_blocks_content_and_favorite_writes_by_default(
    context: AdminProfilesContext,
) -> None:
    with context.session_factory() as db:
        db.add(
            VirtualPlayerProfile(
                id="legacy-profile",
                display_name="兼容玩家",
                model="legacy-model",
                status="published",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

    create = context.client.post(
        "/api/v1/player-profiles",
        json={"display_name": "匿名创建", "model": "legacy-model"},
    )
    content_patch = context.client.patch(
        "/api/v1/player-profiles/legacy-profile",
        json={"display_name": "匿名篡改"},
    )
    favorite_patch = context.client.patch(
        "/api/v1/player-profiles/legacy-profile",
        json={"favorite": True},
    )
    delete = context.client.delete("/api/v1/player-profiles/legacy-profile")
    avatar = context.client.post(
        "/api/v1/player-profiles/avatar",
        json={"filename": "x.png", "content_type": "image/png", "data_base64": "AA=="},
    )
    ai_draft = context.client.post(
        "/api/v1/player-profiles/ai-draft",
        json={"mode": "name", "existing_names": []},
    )

    assert create.status_code == 403
    assert content_patch.status_code == 403
    assert favorite_patch.status_code == 403
    assert delete.status_code == 403
    assert avatar.status_code == 403
    assert ai_draft.status_code == 403
    with context.session_factory() as db:
        persisted = db.get(VirtualPlayerProfile, "legacy-profile")
    assert persisted is not None
    assert persisted.display_name == "兼容玩家"
    assert persisted.favorite is False
    assert persisted.version == 1


def test_admin_ai_draft_requires_permission_csrf_and_audits_success(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StubAiDraftProvider(
        '{"display_name":"夜枭","personality_id":"analytical",'
        '"short_description":"擅长追踪票型",'
        '"strategy_profile":"logic_leader","tags":["票型","推理"]}'
    )
    context.client.app.dependency_overrides[get_player_profile_ai_provider] = lambda: provider
    with context.session_factory() as db:
        db.add(
            VirtualPlayerProfile(
                id="existing-ai-name",
                display_name="夜枭",
                model="legacy-model",
                status="draft",
                published_at=None,
            )
        )
        db.commit()

    _viewer, viewer_csrf = _login(context, monkeypatch, role="viewer")
    forbidden = context.client.post(
        "/api/v1/admin/player-profile-ai-drafts",
        headers={"X-CSRF-Token": viewer_csrf},
        json={"mode": "template"},
    )
    assert forbidden.status_code == 403
    assert provider.calls == []

    context.client.cookies.clear()
    _editor, editor_csrf = _login(context, monkeypatch, role="content_editor")
    missing_csrf = context.client.post(
        "/api/v1/admin/player-profile-ai-drafts",
        json={"mode": "template"},
    )
    response = context.client.post(
        "/api/v1/admin/player-profile-ai-drafts",
        headers={"X-CSRF-Token": editor_csrf},
        json={"mode": "template"},
    )

    assert missing_csrf.status_code == 403
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["display_name"] == "夜枭 2"
    assert response.json()["strategy_profile"] == "logic_leader"
    assert len(provider.calls) == 1
    with context.session_factory() as db:
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.player_profile.ai_draft.generate",
                AuditEvent.result == "success",
            )
        )
    assert audit is not None
    assert audit.after == {"mode": "template", "display_name": "夜枭 2"}


def test_admin_ai_draft_hides_provider_failure_and_audits_stable_code(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StubAiDraftProvider(RuntimeError("secret provider response"))
    context.client.app.dependency_overrides[get_player_profile_ai_provider] = lambda: provider
    _session, csrf_token = _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        "/api/v1/admin/player-profile-ai-drafts",
        headers={"X-CSRF-Token": csrf_token},
        json={"mode": "name"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "admin_player_ai_provider_unavailable"
    assert "secret" not in response.text
    with context.session_factory() as db:
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.player_profile.ai_draft.generate",
                AuditEvent.result == "failure",
            )
        )
    assert audit is not None
    assert audit.reason == "provider_unavailable"


def test_legacy_delete_soft_archives_when_explicitly_enabled(
    context: AdminProfilesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "legacy_player_profile_content_writes_enabled", True)
    with context.session_factory() as db:
        db.add(
            VirtualPlayerProfile(
                id="legacy-delete-profile",
                display_name="待兼容删除",
                model="legacy-model",
                status="published",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

    response = context.client.delete("/api/v1/player-profiles/legacy-delete-profile")
    hidden = context.client.get("/api/v1/player-profiles/legacy-delete-profile")

    assert response.status_code == 204
    assert hidden.status_code == 404
    with context.session_factory() as db:
        profile = db.get(VirtualPlayerProfile, "legacy-delete-profile")
    assert profile is not None
    assert profile.status == "archived"
    assert profile.deleted_at is not None
    assert profile.version == 2
