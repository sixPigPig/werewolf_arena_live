from __future__ import annotations

import copy
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.game_session import GameSessionRecord
from app.models.judge_voice_asset import JudgeVoiceAssetRecord
from app.models.live import LiveRunRecord
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.rule_sets.snapshots import rule_set_content_hash
from app.rule_sets.validation import normalize_rule_set_config


@dataclass(frozen=True)
class AdminRuleSetsContext:
    client: TestClient
    session_factory: sessionmaker[Session]


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> Generator[AdminRuleSetsContext, None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "rules-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Rules Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "viewer")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "rules_admin_session")
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
        yield AdminRuleSetsContext(client=client, session_factory=testing_session)
    engine.dispose()


def _login(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "viewer",
) -> dict:
    monkeypatch.setattr(settings, "admin_dev_auth_role", role)
    response = context.client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text
    return response.json()


def _config(*, name: str, player_count: int = 8) -> dict[str, object]:
    return {
        "name": name,
        "description": f"{name} description",
        "complexity": "标准",
        "estimated_duration": "中",
        "rule_tags": ["标准"],
        "role_counts": {
            "werewolf": 2,
            "villager": player_count - 4,
            "seer": 1,
            "guard": 1,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": False,
        "sheriff_badge_bomb_policy": "none",
    }


def _create_payload(*, rule_set_id: str, name: str) -> dict[str, object]:
    return {
        "id": rule_set_id,
        "display_order": 10,
        "config": _config(name=name),
    }


def _revision(
    *,
    revision_id: str,
    rule_set_id: str,
    revision_no: int,
    state: str,
    name: str,
    player_count: int,
    now: datetime,
) -> RuleSetRevisionRecord:
    published = state != "draft"
    config = _config(name=name, player_count=player_count)
    return RuleSetRevisionRecord(
        id=revision_id,
        rule_set_id=rule_set_id,
        revision_no=revision_no,
        state=state,
        schema_version=1,
        content_hash=(
            rule_set_content_hash(normalize_rule_set_config(config)) if published else None
        ),
        lock_version=1,
        name=name,
        description=f"{name} description",
        player_count=player_count,
        role_summary=f"2 狼人 / {player_count - 4} 村民 / 1 预言家 / 1 守卫",
        complexity="标准",
        estimated_duration="中",
        config=config,
        created_at=now,
        updated_at=now,
        published_at=now if published else None,
        published_by_user_id=1 if published else None,
    )


def _seed_rule(
    db: Session,
    *,
    rule_set_id: str,
    name: str,
    status: str,
    display_order: int,
    player_count: int,
    is_default: bool = False,
) -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    revision_id = f"{rule_set_id}-revision"[:36]
    revision_state = "draft" if status == "draft" else "published"
    db.add(
        RuleSetRecord(
            id=rule_set_id,
            status=status,
            current_published_revision_id=(revision_id if revision_state == "published" else None),
            draft_revision_id=revision_id if revision_state == "draft" else None,
            is_default=is_default,
            display_order=display_order,
            lock_version=1,
            created_at=now,
            updated_at=now,
            archived_at=now if status == "archived" else None,
        )
    )
    db.add(
        _revision(
            revision_id=revision_id,
            rule_set_id=rule_set_id,
            revision_no=1,
            state=revision_state,
            name=name,
            player_count=player_count,
            now=now,
        )
    )


def _seed_detail(context: AdminRuleSetsContext) -> None:
    rule_set_id = "history_rule"
    now = datetime(2026, 7, 12, tzinfo=UTC)
    current_revision_id = "00000000-0000-0000-0000-000000000056"
    with context.session_factory() as db:
        db.add(
            RuleSetRecord(
                id=rule_set_id,
                status="published",
                current_published_revision_id=current_revision_id,
                draft_revision_id=None,
                is_default=False,
                display_order=30,
                lock_version=4,
                created_at=now,
                updated_at=now,
                archived_at=None,
            )
        )
        for revision_no in range(1, 57):
            state = "published" if revision_no == 56 else "superseded"
            db.add(
                _revision(
                    revision_id=f"00000000-0000-0000-0000-{revision_no:012d}",
                    rule_set_id=rule_set_id,
                    revision_no=revision_no,
                    state=state,
                    name=f"History {revision_no}",
                    player_count=8,
                    now=now,
                )
            )
        for index in range(3):
            db.add(
                VirtualPlayerProfile(
                    id=f"published-profile-{index}",
                    display_name=f"Published {index}",
                    model="test-model",
                    status="published",
                    published_at=now,
                    deleted_at=None,
                )
            )
        db.add(
            VirtualPlayerProfile(
                id="draft-profile",
                display_name="Draft",
                model="test-model",
                status="draft",
                published_at=None,
                deleted_at=None,
            )
        )
        for seat_number in range(1, 6):
            db.add(
                JudgeVoiceAssetRecord(
                    id=f"speech_prompt_seat_{seat_number:02d}",
                    text=f"{seat_number}号玩家请发言。",
                    category="发言",
                    template_id="speech_prompt",
                    seat_number=seat_number,
                    audio_format="mp3",
                    sample_rate=24000,
                    mime_type="audio/mpeg",
                    data=b"audio",
                    sha256=f"{seat_number:064x}",
                    size_bytes=5,
                    subtitle_timings=[],
                    source="generated",
                )
            )
        for index, current_id in enumerate((rule_set_id, rule_set_id, "other_rule")):
            db.add(
                LiveRunRecord(
                    run_id=f"run-{index}",
                    session_id=f"live-session-{index}",
                    status="completed",
                    villager_model="test-model",
                    werewolf_model="test-model",
                    max_rounds=10,
                    rule_set_id=current_id,
                    rule_set={"id": current_id, "config": {"must": "not leak"}},
                    player_configs=[],
                    lineup_quality_warnings=[],
                )
            )
            db.add(
                GameSessionRecord(
                    session_id=f"game-session-{index}",
                    status="completed",
                    rule_set={"id": current_id, "snapshot": {"must": "not leak"}},
                )
            )
        db.commit()


@pytest.mark.parametrize(
    "path",
    ["/api/v1/admin/rule-set-options", "/api/v1/admin/rule-sets"],
)
def test_rule_set_reads_require_authentication(
    context: AdminRuleSetsContext,
    path: str,
) -> None:
    response = context.client.get(path)

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "admin_auth_required"


def test_rule_set_create_requires_csrf_before_any_write(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        "/api/v1/admin/rule-sets",
        json=_create_payload(rule_set_id="csrf_guarded", name="CSRF Guarded"),
    )

    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "admin_csrf_invalid"
    with context.session_factory() as db:
        assert db.get(RuleSetRecord, "csrf_guarded") is None
        assert (
            db.scalars(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.create")).all()
            == []
        )


def test_content_editor_creates_revision_one_draft_with_one_bounded_audit(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        "/api/v1/admin/rule-sets",
        json=_create_payload(rule_set_id="created_rule", name="Created Rule"),
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["id"] == "created_rule"
    assert payload["status"] == "draft"
    assert payload["is_default"] is False
    assert payload["lock_version"] == 1
    assert payload["draft_revision"]["revision_no"] == 1
    assert payload["draft_revision"]["state"] == "draft"
    assert payload["draft_revision"]["config"]["name"] == "Created Rule"
    assert payload["published_revision"] is None

    with context.session_factory() as db:
        record = db.get(RuleSetRecord, "created_rule")
        assert record is not None
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "admin.rule_set.create")
        ).all()
    assert len(events) == 1
    event = events[0]
    assert event.resource_type == "rule_set"
    assert event.resource_id == "created_rule"
    assert event.result == "success"
    assert event.before is None
    assert event.after == {
        "id": "created_rule",
        "status": "draft",
        "lock_version": 1,
        "draft_revision": {
            "id": payload["draft_revision"]["id"],
            "rule_set_id": "created_rule",
            "revision_no": 1,
            "state": "draft",
            "schema_version": 1,
            "content_hash": None,
            "lock_version": 1,
        },
        "published_revision": None,
        "changed_fields": ["created"],
    }
    assert "config" not in str(event.after)
    assert "description" not in str(event.after)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "PATCH",
            "/api/v1/admin/rule-sets/csrf_target/draft",
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "display_order": 20,
                "config": _config(name="Updated without CSRF"),
            },
        ),
        (
            "POST",
            "/api/v1/admin/rule-sets/csrf_target/validate",
            {"expected_revision_lock_version": 1},
        ),
        (
            "POST",
            "/api/v1/admin/rule-sets/csrf_target/publish",
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "publish safely",
            },
        ),
        (
            "POST",
            "/api/v1/admin/rule-sets/csrf_target/archive",
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "archive safely",
            },
        ),
        (
            "POST",
            "/api/v1/admin/rule-sets/csrf_target/restore",
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "restore safely",
            },
        ),
        (
            "POST",
            "/api/v1/admin/rule-sets/csrf_target/set-default",
            {
                "expected_rule_set_lock_version": 1,
                "previous_default_expected_lock_version": None,
                "reason": "set default safely",
            },
        ),
        (
            "POST",
            "/api/v1/admin/rule-sets/csrf_target/duplicate",
            {
                "expected_source_lock_version": 1,
                "new_rule_set_id": "csrf_duplicate",
                "new_name": "CSRF Duplicate",
            },
        ),
    ],
    ids=("draft", "validate", "publish", "archive", "restore", "default", "duplicate"),
)
def test_every_existing_rule_set_mutation_requires_csrf(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict[str, object],
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="csrf_target",
            name="CSRF Target",
            status="draft",
            display_order=10,
            player_count=8,
        )
        db.commit()
    _login(context, monkeypatch, role="super_admin")

    response = context.client.request(method, path, json=body)

    assert response.status_code == 403
    assert response.json()["code"] == "admin_csrf_invalid"
    with context.session_factory() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.resource_type == "rule_set")) is None


@pytest.mark.parametrize(
    ("suffix", "body", "permission"),
    [
        (
            "publish",
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "publish denied",
            },
            "rules.publish",
        ),
        (
            "archive",
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "archive denied",
            },
            "rules.archive",
        ),
        (
            "restore",
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "restore denied",
            },
            "rules.archive",
        ),
        (
            "set-default",
            {
                "expected_rule_set_lock_version": 1,
                "previous_default_expected_lock_version": None,
                "reason": "default denied",
            },
            "rules.set_default",
        ),
    ],
)
def test_content_editor_cannot_execute_high_risk_rule_transitions(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    body: dict[str, object],
    permission: str,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="editor_rule",
            name="Editor Rule",
            status="draft",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        f"/api/v1/admin/rule-sets/editor_rule/{suffix}",
        json=body,
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "admin_permission_denied"
    assert permission in response.json()["detail"]
    with context.session_factory() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.resource_type == "rule_set")) is None


def test_draft_update_clones_published_revision_before_editing(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="forked_rule",
            name="Published Original",
            status="published",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="content_editor")

    response = context.client.patch(
        "/api/v1/admin/rule-sets/forked_rule/draft",
        json={
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": None,
            "display_order": 21,
            "config": _config(name="Editable Revision"),
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "published"
    assert payload["display_order"] == 21
    assert payload["published_revision"]["revision_no"] == 1
    assert payload["published_revision"]["config"]["name"] == "Published Original"
    assert payload["draft_revision"]["revision_no"] == 2
    assert payload["draft_revision"]["config"]["name"] == "Editable Revision"
    with context.session_factory() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "admin.rule_set.update")
        ).all()
    assert len(events) == 1
    assert events[0].result == "success"
    assert "config" not in str(events[0].before)
    assert "description" not in str(events[0].after)


def test_validate_valid_draft_returns_compiled_preview_and_success_audit(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="valid_draft",
            name="Valid Draft",
            status="draft",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        "/api/v1/admin/rule-sets/valid_draft/validate",
        json={"expected_revision_lock_version": 1},
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {
        "valid",
        "errors",
        "warnings",
        "compiled_snapshot",
        "content_hash",
        "rule_text_preview",
    }
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert payload["compiled_snapshot"]["id"] == "valid_draft"
    assert payload["compiled_snapshot"]["revision_no"] == 1
    assert len(payload["content_hash"]) == 64
    assert "Valid Draft" in payload["rule_text_preview"]
    with context.session_factory() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.validate"))
    assert event is not None
    assert event.result == "success"
    assert "snapshot" not in str(event.after)


def test_validate_invalid_draft_returns_200_without_compiled_fields_and_rejected_audit(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="invalid_draft",
            name="Invalid Draft",
            status="draft",
            display_order=10,
            player_count=5,
        )
        db.commit()
    login = _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        "/api/v1/admin/rule-sets/invalid_draft/validate",
        json={"expected_revision_lock_version": 1},
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"valid", "errors", "warnings"}
    assert payload["valid"] is False
    assert payload["errors"] == [
        {
            "code": "player_count_out_of_range",
            "path": "role_counts",
            "message": "Player count must be between 6 and 12.",
        }
    ]
    with context.session_factory() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.validate"))
    assert event is not None
    assert event.result == "rejected"
    assert event.reason == "rule_set_validation_failed"
    assert "config" not in str(event.after)


def test_duplicate_creates_only_a_new_revision_one_draft(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="duplicate_source",
            name="Duplicate Source",
            status="published",
            display_order=13,
            player_count=8,
            is_default=True,
        )
        db.commit()
    login = _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        "/api/v1/admin/rule-sets/duplicate_source/duplicate",
        json={
            "expected_source_lock_version": 1,
            "new_rule_set_id": "duplicate_copy",
            "new_name": "Duplicate Copy",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["id"] == "duplicate_copy"
    assert payload["status"] == "draft"
    assert payload["is_default"] is False
    assert payload["display_order"] == 13
    assert payload["draft_revision"]["revision_no"] == 1
    assert payload["draft_revision"]["config"]["name"] == "Duplicate Copy"
    assert payload["published_revision"] is None
    with context.session_factory() as db:
        source = db.get(RuleSetRecord, "duplicate_source")
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.duplicate"))
    assert source is not None and source.is_default is True
    assert event is not None
    assert event.resource_id == "duplicate_copy"
    assert event.result == "success"
    assert event.before["id"] == "duplicate_source"
    assert event.after["id"] == "duplicate_copy"


def test_super_admin_publishes_validated_draft_with_reason_and_success_audit(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="publishable_rule",
            name="Publishable Rule",
            status="draft",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="super_admin")

    response = context.client.post(
        "/api/v1/admin/rule-sets/publishable_rule/publish",
        json={
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": 1,
            "reason": "release approved",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "published"
    assert payload["draft_revision"] is None
    assert payload["published_revision"]["state"] == "published"
    assert len(payload["published_revision"]["content_hash"]) == 64
    with context.session_factory() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.publish"))
    assert event is not None
    assert event.result == "success"
    assert event.reason == "release approved"
    assert event.before["status"] == "draft"
    assert event.after["status"] == "published"
    assert "config" not in str(event.after)


def test_publish_validation_failure_rolls_back_and_records_rejected_attempt(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="rejected_publish",
            name="Rejected Publish",
            status="draft",
            display_order=10,
            player_count=5,
        )
        db.commit()
    login = _login(context, monkeypatch, role="super_admin")

    response = context.client.post(
        "/api/v1/admin/rule-sets/rejected_publish/publish",
        json={
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": 1,
            "reason": "try invalid release",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "rule_set_validation_failed"
    assert payload["detail"] == "The rule set has validation errors."
    assert payload["errors"][0]["code"] == "player_count_out_of_range"
    assert "Rejected Publish description" not in response.text
    with context.session_factory() as db:
        record = db.get(RuleSetRecord, "rejected_publish")
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.publish"))
    assert record is not None and record.status == "draft"
    assert event is not None
    assert event.result == "rejected"
    assert event.reason == "try invalid release"
    assert "config" not in str(event.after)


def test_super_admin_archives_and_restores_without_changing_published_revision(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="lifecycle_rule",
            name="Lifecycle Rule",
            status="published",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="super_admin")

    archived = context.client.post(
        "/api/v1/admin/rule-sets/lifecycle_rule/archive",
        json={
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": 1,
            "reason": "temporarily retire",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )
    assert archived.status_code == 200, archived.text
    archived_payload = archived.json()
    revision_id = archived_payload["published_revision"]["id"]
    assert archived_payload["status"] == "archived"

    restored = context.client.post(
        "/api/v1/admin/rule-sets/lifecycle_rule/restore",
        json={
            "expected_rule_set_lock_version": archived_payload["lock_version"],
            "expected_revision_lock_version": None,
            "reason": "return to catalog",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )
    assert restored.status_code == 200, restored.text
    restored_payload = restored.json()
    assert restored_payload["status"] == "published"
    assert restored_payload["published_revision"]["id"] == revision_id
    with context.session_factory() as db:
        events = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource_id == "lifecycle_rule")
            .order_by(AuditEvent.created_at.asc(), AuditEvent.action.asc())
        ).all()
    assert {event.action: event.result for event in events} == {
        "admin.rule_set.archive": "success",
        "admin.rule_set.restore": "success",
    }
    assert {event.reason for event in events} == {
        "temporarily retire",
        "return to catalog",
    }


def test_archiving_default_switches_replacement_in_same_successful_transaction(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="z_current_default",
            name="Current Default",
            status="published",
            display_order=10,
            player_count=8,
            is_default=True,
        )
        _seed_rule(
            db,
            rule_set_id="a_replacement",
            name="Replacement",
            status="published",
            display_order=20,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="super_admin")

    response = context.client.post(
        "/api/v1/admin/rule-sets/z_current_default/archive",
        json={
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": None,
            "reason": "replace default safely",
            "replacement_default_rule_set_id": "a_replacement",
            "replacement_expected_lock_version": 1,
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "archived"
    assert response.json()["is_default"] is False
    with context.session_factory() as db:
        current = db.get(RuleSetRecord, "z_current_default")
        replacement = db.get(RuleSetRecord, "a_replacement")
        defaults = db.scalars(select(RuleSetRecord).where(RuleSetRecord.is_default.is_(True))).all()
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.archive"))
    assert current is not None and current.status == "archived"
    assert replacement is not None and replacement.is_default is True
    assert [record.id for record in defaults] == ["a_replacement"]
    assert event is not None and event.result == "success"
    assert event.after["changed_fields"] == [
        "status",
        "is_default",
        "replacement_default_rule_set_id",
    ]


def test_super_admin_sets_published_default_atomically(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="old_default",
            name="Old Default",
            status="published",
            display_order=10,
            player_count=8,
            is_default=True,
        )
        _seed_rule(
            db,
            rule_set_id="new_default",
            name="New Default",
            status="published",
            display_order=20,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="super_admin")

    response = context.client.post(
        "/api/v1/admin/rule-sets/new_default/set-default",
        json={
            "expected_rule_set_lock_version": 1,
            "previous_default_expected_lock_version": 1,
            "reason": "promote new default",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "new_default"
    assert response.json()["is_default"] is True
    with context.session_factory() as db:
        old = db.get(RuleSetRecord, "old_default")
        new = db.get(RuleSetRecord, "new_default")
        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.rule_set.set_default")
        )
    assert old is not None and old.is_default is False
    assert new is not None and new.is_default is True
    assert event is not None
    assert event.result == "success"
    assert event.reason == "promote new default"


def test_stale_draft_update_returns_bounded_conflict_and_persists_one_attempt(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="stale_draft",
            name="Stored Draft",
            status="draft",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="content_editor")
    config = _config(name="Client Draft")
    config["description"] = "private client config must never leak"

    response = context.client.patch(
        "/api/v1/admin/rule-sets/stale_draft/draft",
        json={
            "expected_rule_set_lock_version": 999,
            "expected_revision_lock_version": 999,
            "display_order": 25,
            "config": config,
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["code"] == "rule_set_version_conflict"
    assert payload["current_rule_set_lock_version"] == 1
    assert payload["current_revision_lock_version"] == 1
    assert "private client config" not in response.text
    with context.session_factory() as db:
        record = db.get(RuleSetRecord, "stale_draft")
        revision = db.scalar(
            select(RuleSetRevisionRecord).where(RuleSetRevisionRecord.rule_set_id == "stale_draft")
        )
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "admin.rule_set.update")
        ).all()
    assert record is not None and record.display_order == 10
    assert revision is not None and revision.name == "Stored Draft"
    assert len(events) == 1
    assert events[0].result == "conflict"
    assert events[0].after["expected_rule_set_lock_version"] == 999
    assert events[0].after["current_rule_set_lock_version"] == 1
    assert "config" not in str(events[0].after)
    assert "private client config" not in str(events[0].after)


def test_validate_missing_draft_maps_to_rule_revision_changed_attempt(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="published_only",
            name="Published Only",
            status="published",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        "/api/v1/admin/rule-sets/published_only/validate",
        json={"expected_revision_lock_version": 1},
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "rule_revision_changed"
    assert response.json()["current_revision_id"] == "published_only-revision"
    assert "Published Only description" not in response.text
    with context.session_factory() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.validate"))
    assert event is not None
    assert event.result == "conflict"
    assert "config" not in str(event.after)


def test_set_default_rejects_unpublished_rule_with_exact_unavailable_problem(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="unavailable_default",
            name="Unavailable Default",
            status="draft",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="super_admin")

    response = context.client.post(
        "/api/v1/admin/rule-sets/unavailable_default/set-default",
        json={
            "expected_rule_set_lock_version": 1,
            "previous_default_expected_lock_version": None,
            "reason": "try unavailable default",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "rule_set_unavailable"
    assert response.json()["current_status"] == "draft"
    with context.session_factory() as db:
        record = db.get(RuleSetRecord, "unavailable_default")
        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.rule_set.set_default")
        )
    assert record is not None and record.is_default is False
    assert event is not None and event.result == "conflict"
    assert event.reason == "try unavailable default"


def test_archiving_only_default_requires_replacement_and_records_conflict(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="required_default",
            name="Required Default",
            status="published",
            display_order=10,
            player_count=8,
            is_default=True,
        )
        db.commit()
    login = _login(context, monkeypatch, role="super_admin")

    response = context.client.post(
        "/api/v1/admin/rule-sets/required_default/archive",
        json={
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": None,
            "reason": "archive without replacement",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "default_rule_required"
    with context.session_factory() as db:
        record = db.get(RuleSetRecord, "required_default")
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.archive"))
    assert record is not None and record.status == "published" and record.is_default is True
    assert event is not None and event.result == "conflict"
    assert event.reason == "archive without replacement"


def test_stale_archive_replacement_reports_and_audits_replacement_versions(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="archive_primary",
            name="Archive Primary",
            status="published",
            display_order=10,
            player_count=8,
            is_default=True,
        )
        _seed_rule(
            db,
            rule_set_id="stale_replacement",
            name="Stale Replacement",
            status="published",
            display_order=20,
            player_count=8,
        )
        db.flush()
        replacement = db.get(RuleSetRecord, "stale_replacement")
        assert replacement is not None
        replacement.lock_version = 7
        db.commit()
    login = _login(context, monkeypatch, role="super_admin")

    response = context.client.post(
        "/api/v1/admin/rule-sets/archive_primary/archive",
        json={
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": None,
            "reason": "stale replacement attempt",
            "replacement_default_rule_set_id": "stale_replacement",
            "replacement_expected_lock_version": 2,
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "rule_set_version_conflict"
    assert response.json()["current_rule_set_lock_version"] == 7
    with context.session_factory() as db:
        primary = db.get(RuleSetRecord, "archive_primary")
        replacement = db.get(RuleSetRecord, "stale_replacement")
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.archive"))
    assert primary is not None and primary.status == "published" and primary.is_default is True
    assert replacement is not None and replacement.is_default is False
    assert event is not None and event.result == "conflict"
    assert event.after["current_rule_set_id"] == "stale_replacement"
    assert event.after["current_rule_set_lock_version"] == 7
    assert event.after["replacement_expected_lock_version"] == 2


def test_storage_failure_returns_sanitized_problem_and_bounded_failure_audit(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import admin_rule_sets as route_module

    login = _login(context, monkeypatch, role="content_editor")
    raw_storage_text = "SELECT secret_config FROM rule_sets -- raw storage detail"

    def fail_create(*_args: object, **_kwargs: object) -> None:
        raise OperationalError(
            raw_storage_text,
            {"description": "must not leak"},
            RuntimeError("raw exception chain"),
        )

    monkeypatch.setattr(route_module, "create_rule_set", fail_create)

    response = context.client.post(
        "/api/v1/admin/rule-sets",
        json=_create_payload(rule_set_id="storage_failure", name="Storage Failure"),
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "rule_set_store_unavailable"
    assert raw_storage_text not in response.text
    assert "must not leak" not in response.text
    assert "raw exception chain" not in response.text
    with context.session_factory() as db:
        assert db.get(RuleSetRecord, "storage_failure") is None
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "admin.rule_set.create")
        ).all()
    assert len(events) == 1
    assert events[0].result == "failure"
    persisted = f"{events[0].reason} {events[0].before} {events[0].after}"
    assert raw_storage_text not in persisted
    assert "must not leak" not in persisted
    assert "raw exception chain" not in persisted
    assert "description" not in persisted


def test_success_audit_failure_rolls_back_business_then_commits_one_failure_attempt(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import admin_rule_sets as route_module

    login = _login(context, monkeypatch, role="content_editor")
    real_record_audit_event = route_module.record_audit_event
    calls = 0

    def fail_success_audit_once(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if kwargs.get("result") == "success":
            raise OperationalError(
                "INSERT INTO audit_events secret payload",
                {},
                RuntimeError("audit backend detail"),
            )
        return real_record_audit_event(*args, **kwargs)

    monkeypatch.setattr(route_module, "record_audit_event", fail_success_audit_once)

    response = context.client.post(
        "/api/v1/admin/rule-sets",
        json=_create_payload(rule_set_id="atomic_failure", name="Atomic Failure"),
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "rule_set_store_unavailable"
    with context.session_factory() as db:
        assert db.get(RuleSetRecord, "atomic_failure") is None
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "admin.rule_set.create")
        ).all()
    assert calls == 2
    assert len(events) == 1
    assert events[0].result == "failure"
    assert "secret" not in str(events[0].after)
    assert "backend detail" not in str(events[0].after)


def test_successful_mutation_uses_exactly_one_route_level_commit(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _login(context, monkeypatch, role="content_editor")
    real_commit = Session.commit
    commit_calls: list[Session] = []

    def tracked_commit(db: Session) -> None:
        commit_calls.append(db)
        real_commit(db)

    monkeypatch.setattr(Session, "commit", tracked_commit)

    response = context.client.post(
        "/api/v1/admin/rule-sets",
        json=_create_payload(rule_set_id="one_commit", name="One Commit"),
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 201, response.text
    assert len(commit_calls) == 1
    with context.session_factory() as db:
        assert db.get(RuleSetRecord, "one_commit") is not None
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.create"))
    assert event is not None and event.result == "success"


def test_domain_text_validation_is_a_bounded_rejected_create_attempt(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _login(context, monkeypatch, role="content_editor")
    body = _create_payload(rule_set_id="unsafe_text", name="Unsafe\u0000Name")

    response = context.client.post(
        "/api/v1/admin/rule-sets",
        json=body,
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "rule_set_validation_failed"
    assert response.json()["errors"] == [
        {
            "code": "rule_configuration_invalid",
            "path": "config",
            "message": "Rule configuration is invalid.",
        }
    ]
    assert "Unsafe" not in response.text
    with context.session_factory() as db:
        assert db.get(RuleSetRecord, "unsafe_text") is None
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.create"))
    assert event is not None
    assert event.result == "rejected"
    assert event.reason == "rule_set_validation_failed"
    assert "Unsafe" not in str(event.after)
    assert "description" not in str(event.after)


def test_duplicate_invalid_normalized_name_is_rejected_without_copying(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="safe_source",
            name="Safe Source",
            status="draft",
            display_order=10,
            player_count=8,
        )
        db.commit()
    login = _login(context, monkeypatch, role="content_editor")

    response = context.client.post(
        "/api/v1/admin/rule-sets/safe_source/duplicate",
        json={
            "expected_source_lock_version": 1,
            "new_rule_set_id": "unsafe_copy",
            "new_name": "   ",
        },
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "rule_set_validation_failed"
    with context.session_factory() as db:
        assert db.get(RuleSetRecord, "unsafe_copy") is None
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.rule_set.duplicate"))
    assert event is not None and event.result == "rejected"
    assert "Safe Source description" not in str(event.after)


def test_viewer_can_read_rule_set_options_without_csrf(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _login(context, monkeypatch)
    assert "rules.read" in login["permissions"]

    response = context.client.get(
        "/api/v1/admin/rule-set-options",
        headers={"X-CSRF-Token": "intentionally-not-the-session-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["constraints"]["player_count_min"] == 6
    assert response.json()["constraints"]["player_count_max"] == 12


def test_viewer_can_read_empty_rule_set_list_without_csrf(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch)

    response = context.client.get("/api/v1/admin/rule-sets")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "items": [],
        "pagination": {"page": 1, "page_size": 20, "total": 0, "pages": 0},
    }


@pytest.mark.parametrize("role", ["viewer", "operator", "content_editor"])
def test_fixed_admin_roles_can_read_rule_sets(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    login = _login(context, monkeypatch, role=role)

    assert "rules.read" in login["permissions"]
    assert context.client.get("/api/v1/admin/rule-sets").status_code == 200


def test_rule_set_reads_require_rules_read_permission(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch)
    with context.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "rules-admin@example.test"))
        assert user is not None
        user.admin_role = None
        db.commit()

    response = context.client.get("/api/v1/admin/rule-sets")

    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "admin_permission_denied"


def test_rule_set_options_are_complete_and_bounded(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch, role="operator")

    response = context.client.get("/api/v1/admin/rule-set-options")

    assert response.status_code == 200
    payload = response.json()
    assert [(role["id"], role["label"]) for role in payload["roles"]] == [
        ("werewolf", "狼人"),
        ("villager", "村民"),
        ("seer", "预言家"),
        ("guard", "守卫"),
        ("witch", "女巫"),
        ("hunter", "猎人"),
        ("idiot", "白痴"),
    ]
    assert all(role["min_count"] >= 0 for role in payload["roles"])
    assert all(role["max_count"] <= 12 for role in payload["roles"])
    assert {item["value"] for item in payload["win_conditions"]} == {
        "wolves_gte_others",
        "slaughter_side",
    }
    assert payload["sheriff_vote_weights"] == [1.0, 1.5, 2.0]
    assert {item["value"] for item in payload["speech_policies"]} == {
        "sequential",
        "sheriff_directed",
    }
    assert {item["value"] for item in payload["sheriff_badge_bomb_policies"]} == {
        "none",
        "double",
    }
    assert payload["constraints"] == {
        "player_count_min": 6,
        "player_count_max": 12,
        "tags_max_items": 8,
        "tag_max_length": 20,
        "id_pattern": "^[a-z][a-z0-9_]{2,79}$",
        "reason_min_length": 3,
        "reason_max_length": 500,
    }


def test_rule_set_list_filters_sorts_and_paginates_safe_snapshots(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with context.session_factory() as db:
        _seed_rule(
            db,
            rule_set_id="zeta_draft",
            name="Zeta Draft",
            status="draft",
            display_order=20,
            player_count=6,
        )
        _seed_rule(
            db,
            rule_set_id="alpha_published",
            name="Alpha Published",
            status="published",
            display_order=10,
            player_count=8,
            is_default=True,
        )
        _seed_rule(
            db,
            rule_set_id="middle_archived",
            name="Middle Archived",
            status="archived",
            display_order=30,
            player_count=10,
        )
        db.commit()
    _login(context, monkeypatch, role="content_editor")

    first = context.client.get(
        "/api/v1/admin/rule-sets",
        params={"page": 1, "page_size": 1, "sort": "name"},
    )
    filtered = context.client.get(
        "/api/v1/admin/rule-sets",
        params={
            "q": "published",
            "status": "published",
            "player_count": 8,
            "sort": "-updated_at",
        },
    )

    assert first.status_code == 200
    assert first.json()["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total": 3,
        "pages": 3,
    }
    assert [item["id"] for item in first.json()["items"]] == ["alpha_published"]
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == ["alpha_published"]
    item = filtered.json()["items"][0]
    assert item["published_revision"]["config"]["name"] == "Alpha Published"
    assert item["revisions"] == []
    assert "created_by_user_id" not in item
    assert "updated_by_user_id" not in item


@pytest.mark.parametrize(
    ("params", "expected_field", "contains_giant_input"),
    [
        ({"page": 10**100}, "query.page", True),
        ({"player_count": 10**100}, "query.player_count", True),
        ({"player_count": 0}, "query.player_count", False),
        ({"player_count": 13}, "query.player_count", False),
    ],
    ids=("huge-page", "huge-player-count", "player-count-zero", "player-count-thirteen"),
)
def test_rule_set_list_rejects_unsafe_integer_filters_before_repository_access(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, int],
    expected_field: str,
    contains_giant_input: bool,
) -> None:
    from app.api.routes import admin_rule_sets as route_module

    repository_calls: list[dict[str, object]] = []

    def repository_sentinel(*_args: object, **kwargs: object) -> SimpleNamespace:
        repository_calls.append(kwargs)
        return SimpleNamespace(
            items=(),
            page=1,
            page_size=20,
            total=0,
            pages=0,
        )

    monkeypatch.setattr(route_module, "list_rule_sets", repository_sentinel)
    _login(context, monkeypatch)

    response = context.client.get("/api/v1/admin/rule-sets", params=params)

    assert response.status_code == 422
    assert repository_calls == []
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    request_id = response.headers["x-request-id"]
    assert 1 <= len(request_id) <= 80
    payload = response.json()
    assert payload["code"] == "admin_request_invalid"
    assert payload["detail"] == "One or more request fields are invalid."
    assert {error["field"] for error in payload["errors"]} == {expected_field}
    if contains_giant_input:
        assert str(10**100) not in response.text


def test_rule_set_detail_is_bounded_and_uses_current_storage_counts_and_warnings(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_detail(context)
    _login(context, monkeypatch)

    response = context.client.get("/api/v1/admin/rule-sets/history_rule")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["id"] == "history_rule"
    assert payload["published_revision"]["id"] == ("00000000-0000-0000-0000-000000000056")
    assert payload["published_revision"]["config"]["role_counts"]["werewolf"] == 2
    assert len(payload["revisions"]) == 50
    assert [revision["revision_no"] for revision in payload["revisions"]] == list(range(56, 6, -1))
    assert all(revision["config"] is None for revision in payload["revisions"])
    assert payload["usage"] == {"game_count": 2, "live_count": 2}
    warnings = {warning["code"]: warning for warning in payload["warnings"]}
    assert warnings["published_player_shortage"] == {
        "code": "published_player_shortage",
        "path": "player_profiles",
        "message": "Only 3 published player profiles are available for 8 seats.",
    }
    assert warnings["judge_seat_coverage"] == {
        "code": "judge_seat_coverage",
        "path": "judge_voice_assets",
        "message": "Judge voice assets cover 5 of 8 required seats.",
    }
    assert len(payload["warnings"]) <= 10
    assert all(len(warning["message"]) <= 500 for warning in payload["warnings"])
    assert "rule_set" not in payload["usage"]
    assert "snapshot" not in str(payload["usage"])


def test_rule_set_detail_returns_bounded_not_found_problem(
    context: AdminRuleSetsContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch)

    response = context.client.get("/api/v1/admin/rule-sets/missing_rule")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "admin_rule_set_not_found"
    assert "missing_rule" not in response.json()["detail"]


def test_rule_set_request_contracts_are_strict_and_bounded() -> None:
    from app.api.schemas.admin_rule_sets import (
        AdminRuleRoleCounts,
        AdminRuleSetArchive,
        AdminRuleSetDraftUpdate,
        AdminRuleSetTransition,
    )

    assert tuple(AdminRuleRoleCounts.model_fields) == (
        "werewolf",
        "villager",
        "seer",
        "guard",
        "witch",
        "hunter",
        "idiot",
    )
    valid_config = _config(name="Strict Contract")
    update = AdminRuleSetDraftUpdate.model_validate(
        {
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": None,
            "display_order": 0,
            "config": valid_config,
        }
    )
    assert tuple(type(update).model_fields) == (
        "expected_rule_set_lock_version",
        "expected_revision_lock_version",
        "display_order",
        "config",
    )

    for model, payload in (
        (
            AdminRuleSetDraftUpdate,
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": None,
                "display_order": 0,
                "config": valid_config,
                "status": "published",
            },
        ),
        (
            AdminRuleSetTransition,
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "ok reason",
                "config": valid_config,
            },
        ),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)

    with pytest.raises(ValidationError):
        AdminRuleSetTransition.model_validate(
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "no",
            }
        )
    with pytest.raises(ValidationError):
        AdminRuleSetTransition.model_validate(
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "x" * 501,
            }
        )
    with pytest.raises(ValidationError):
        AdminRuleSetArchive.model_validate(
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": None,
                "reason": "archive rule",
                "replacement_default_rule_set_id": "UPPERCASE",
                "replacement_expected_lock_version": 1,
            }
        )
    archive = AdminRuleSetArchive.model_validate(
        {
            "expected_rule_set_lock_version": 1,
            "expected_revision_lock_version": None,
            "reason": "archive rule",
            "replacement_default_rule_set_id": "replacement_rule",
            "replacement_expected_lock_version": 2,
        }
    )
    assert archive.replacement_default_rule_set_id == "replacement_rule"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, value)
        for field in (
            "expected_rule_set_lock_version",
            "expected_revision_lock_version",
            "display_order",
        )
        for value in (True, False, "1", 1.0)
    ],
)
def test_rule_set_draft_integer_fields_reject_coerced_scalars(
    field: str,
    value: object,
) -> None:
    from app.api.schemas.admin_rule_sets import AdminRuleSetDraftUpdate

    payload = {
        "expected_rule_set_lock_version": 1,
        "expected_revision_lock_version": 1,
        "display_order": 0,
        "config": _config(name="Strict integers"),
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        AdminRuleSetDraftUpdate.model_validate(payload)


@pytest.mark.parametrize(
    "role_id",
    ["werewolf", "villager", "seer", "guard", "witch", "hunter", "idiot"],
)
@pytest.mark.parametrize("value", [True, False, "1", 1.0])
def test_each_rule_role_count_rejects_coerced_scalars(
    role_id: str,
    value: object,
) -> None:
    from app.api.schemas.admin_rule_sets import AdminRuleSetDraftUpdate

    payload = {
        "expected_rule_set_lock_version": 1,
        "expected_revision_lock_version": 1,
        "display_order": 0,
        "config": _config(name="Strict roles"),
    }
    role_counts = payload["config"]["role_counts"]
    assert isinstance(role_counts, dict)
    role_counts[role_id] = value

    with pytest.raises(ValidationError):
        AdminRuleSetDraftUpdate.model_validate(payload)


@pytest.mark.parametrize(
    ("model_name", "field", "value"),
    [
        ("validate", "expected_revision_lock_version", "1"),
        ("transition", "expected_rule_set_lock_version", True),
        ("transition", "expected_revision_lock_version", 1.0),
        ("archive", "replacement_expected_lock_version", "2"),
        ("default", "expected_rule_set_lock_version", 1.0),
        ("default", "previous_default_expected_lock_version", "1"),
        ("duplicate", "expected_source_lock_version", True),
    ],
)
def test_every_rule_request_lock_version_layer_is_strict(
    model_name: str,
    field: str,
    value: object,
) -> None:
    from app.api.schemas.admin_rule_sets import (
        AdminRuleSetArchive,
        AdminRuleSetDefaultTransition,
        AdminRuleSetDuplicate,
        AdminRuleSetTransition,
        AdminRuleSetValidate,
    )

    cases = {
        "validate": (
            AdminRuleSetValidate,
            {"expected_revision_lock_version": 1},
        ),
        "transition": (
            AdminRuleSetTransition,
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "reason": "publish rule",
            },
        ),
        "archive": (
            AdminRuleSetArchive,
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": None,
                "reason": "archive rule",
                "replacement_default_rule_set_id": "replacement_rule",
                "replacement_expected_lock_version": 2,
            },
        ),
        "default": (
            AdminRuleSetDefaultTransition,
            {
                "expected_rule_set_lock_version": 1,
                "previous_default_expected_lock_version": 1,
                "reason": "set default rule",
            },
        ),
        "duplicate": (
            AdminRuleSetDuplicate,
            {
                "expected_source_lock_version": 1,
                "new_rule_set_id": "copied_rule",
                "new_name": "Copied Rule",
            },
        ),
    }
    model, valid_payload = cases[model_name]
    payload = copy.deepcopy(valid_payload)
    payload[field] = value

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sheriff_enabled", 1),
        ("sheriff_enabled", "true"),
        ("werewolf_self_explosion_enabled", 0),
        ("werewolf_self_explosion_enabled", "false"),
    ],
)
def test_rule_config_booleans_reject_integer_and_string_values(
    field: str,
    value: object,
) -> None:
    from app.api.schemas.admin_rule_sets import AdminRuleSetDraftUpdate

    config = _config(name="Strict booleans")
    config[field] = value

    with pytest.raises(ValidationError):
        AdminRuleSetDraftUpdate.model_validate(
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "display_order": 0,
                "config": config,
            }
        )


def test_rule_config_vote_weight_rejects_numeric_string() -> None:
    from app.api.schemas.admin_rule_sets import AdminRuleSetDraftUpdate

    config = _config(name="Strict vote weight")
    config["sheriff_vote_weight"] = "1.0"

    with pytest.raises(ValidationError):
        AdminRuleSetDraftUpdate.model_validate(
            {
                "expected_rule_set_lock_version": 1,
                "expected_revision_lock_version": 1,
                "display_order": 0,
                "config": config,
            }
        )


def test_fully_exact_typed_nested_rule_request_remains_valid() -> None:
    from app.api.schemas.admin_rule_sets import AdminRuleSetDraftUpdate

    request = AdminRuleSetDraftUpdate.model_validate(
        {
            "expected_rule_set_lock_version": 3,
            "expected_revision_lock_version": 2,
            "display_order": 1,
            "config": _config(name="Exact typed request"),
        }
    )

    assert type(request.expected_rule_set_lock_version) is int
    assert type(request.expected_revision_lock_version) is int
    assert type(request.display_order) is int
    assert type(request.config.sheriff_vote_weight) is float
    assert type(request.config.sheriff_enabled) is bool
    assert all(type(value) is int for value in request.config.role_counts.model_dump().values())


def test_strict_request_models_preserve_extra_length_and_range_rejections() -> None:
    from app.api.schemas.admin_rule_sets import AdminRuleSetDraftUpdate

    base = {
        "expected_rule_set_lock_version": 1,
        "expected_revision_lock_version": 1,
        "display_order": 0,
        "config": _config(name="Bounded request"),
    }
    invalid_payloads = []
    for field, value in (
        ("display_order", -1),
        ("unexpected", "field"),
    ):
        payload = copy.deepcopy(base)
        payload[field] = value
        invalid_payloads.append(payload)
    too_long_name = copy.deepcopy(base)
    too_long_name["config"]["name"] = "x" * 121
    invalid_payloads.append(too_long_name)
    negative_role = copy.deepcopy(base)
    negative_role["config"]["role_counts"]["werewolf"] = -1
    invalid_payloads.append(negative_role)

    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            AdminRuleSetDraftUpdate.model_validate(payload)
