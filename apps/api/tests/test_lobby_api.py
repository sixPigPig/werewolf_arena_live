import copy
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.lobby import (
    CreatePlayerConfigRequest,
    complete_player_configs_from_library,
    list_available_player_profiles,
    normalize_player_config_requests,
)
from app.api.public.dependencies import public_problem
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.model_configuration import ModelConfigurationRecord
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.rule_sets.snapshots import resolve_rule_set_snapshot
from app.rule_sets.static_catalog import STATIC_RULE_REVISIONS
from app.rule_sets.service import publish_rule_set, update_rule_set_draft
from app.rule_sets.telemetry import (
    _reset_rule_set_metrics_for_tests,
    render_rule_set_metrics,
)
from app.rule_sets.validation import normalize_rule_set_config
from tests.rule_set_fixtures import (
    OFFICIAL_RULE_SET_SEEDS,
    managed_official_compiled_rule_set,
    seed_official_rule_sets,
)


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)
with TestingSessionLocal.begin() as session:
    session.add(
        ModelConfigurationRecord(
            provider="deepseek",
            model_id="deepseek-v4-flash",
            source_model_id="deepseek-v4-flash",
            display_name="deepseek-v4-flash",
            available=True,
            enabled=True,
            is_default=True,
            supports_thinking=True,
            parameter_values={
                "thinking": "enabled",
                "reasoning_effort": "high",
                "max_tokens_mode": "auto",
                "max_tokens": 8_192,
            },
            source_details={"source": "test"},
        )
    )

client = TestClient(app)


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    _reset_rule_set_metrics_for_tests()
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "legacy_player_profile_content_writes_enabled", True)
    with TestingSessionLocal() as session:
        session.query(RuleSetRevisionRecord).delete()
        session.query(RuleSetRecord).delete()
        session.query(VirtualPlayerProfile).delete()
        session.query(PlayerAvatarAsset).delete()
        session.query(User).delete()
        seed_official_rule_sets(session)
        session.commit()
    yield
    _reset_rule_set_metrics_for_tests()
    app.dependency_overrides.clear()
    with TestingSessionLocal() as session:
        session.query(RuleSetRevisionRecord).delete()
        session.query(RuleSetRecord).delete()
        session.query(VirtualPlayerProfile).delete()
        session.query(PlayerAvatarAsset).delete()
        session.query(User).delete()
        session.commit()


def test_game_profile_selection_only_uses_published_profiles() -> None:
    with TestingSessionLocal() as session:
        session.add_all(
            [
                VirtualPlayerProfile(
                    id="published-for-game",
                    display_name="公开玩家",
                    model_provider="deepseek",
                    model="model-a",
                    status="published",
                    published_at=datetime.now(UTC),
                    display_order=1,
                ),
                VirtualPlayerProfile(
                    id="draft-for-game",
                    display_name="草稿玩家",
                    model_provider="deepseek",
                    model="model-a",
                    status="draft",
                    published_at=None,
                    display_order=None,
                ),
                VirtualPlayerProfile(
                    id="archived-for-game",
                    display_name="归档玩家",
                    model_provider="deepseek",
                    model="model-a",
                    status="archived",
                    published_at=datetime.now(UTC),
                    deleted_at=datetime.now(UTC),
                    display_order=None,
                ),
            ]
        )
        session.commit()

        available = list_available_player_profiles(session)

        assert [profile.id for profile in available] == ["published-for-game"]
        with pytest.raises(HTTPException, match="Unknown player profile: draft-for-game"):
            normalize_player_config_requests(
                [CreatePlayerConfigRequest(seat=1, profile_id="draft-for-game")],
                1,
                session,
            )
        with pytest.raises(HTTPException, match="1 available players"):
            complete_player_configs_from_library(
                requests=[],
                player_count=2,
                seed=1,
                db=session,
            )

def test_game_profile_config_drops_unmanaged_external_avatar_url() -> None:
    with TestingSessionLocal() as session:
        session.add(
            VirtualPlayerProfile(
                id="external-avatar-for-game",
                display_name="旧外链头像玩家",
                model_provider="deepseek",
                model="model-a",
                avatar_image_url="https://tracker.example/avatar.png",
                status="published",
                published_at=datetime.now(UTC),
                display_order=1,
            )
        )
        session.commit()

        configs = complete_player_configs_from_library(
            requests=[
                CreatePlayerConfigRequest(
                    seat=1,
                    profile_id="external-avatar-for-game",
                )
            ],
            player_count=1,
            seed=1,
            db=session,
        )

    assert configs[0].avatar_image_url == ""

def add_virtual_profiles(
    count: int,
    *,
    prefix: str = "profile",
    diverse: bool = True,
) -> list[str]:
    profile_ids = [f"{prefix}-{index}" for index in range(1, count + 1)]
    personalities = ["balanced", "aggressive", "cautious", "deceptive", "analytical"]
    strategies = [
        "balanced",
        "pressure_attacker",
        "cautious_observer",
        "shadow_wolf",
        "logic_leader",
        "social_reader",
    ]
    appearances = [
        "default",
        "crimson",
        "moonlit",
        "ember",
        "verdant",
        "gothic-male-1",
        "gothic-male-2",
        "gothic-female-1",
        "gothic-female-2",
    ]
    with TestingSessionLocal() as session:
        first_display_order = (
            session.query(func.max(VirtualPlayerProfile.display_order)).scalar() or 0
        )
        session.add_all(
            [
                VirtualPlayerProfile(
                    id=profile_id,
                    display_name=f"虚拟玩家{index}",
                    model_provider="deepseek",
                    model="profile-model",
                    personality_id=(
                        personalities[(index - 1) % len(personalities)] if diverse else "balanced"
                    ),
                    personality_text="稳健推进。",
                    strategy_profile=(
                        strategies[(index - 1) % len(strategies)] if diverse else "balanced"
                    ),
                    appearance_id=(
                        appearances[(index - 1) % len(appearances)] if diverse else "default"
                    ),
                    tags=[],
                    status="published",
                    published_at=datetime.now(UTC),
                    display_order=first_display_order + index,
                )
                for index, profile_id in enumerate(profile_ids, start=1)
            ]
        )
        session.commit()
    return profile_ids

def _rule_metrics() -> str:
    with TestingSessionLocal() as session:
        return render_rule_set_metrics(session)

@pytest.mark.parametrize(
    ("corruption", "reason"),
    [
        ("structure", "invalid_snapshot"),
        ("content_hash", "content_hash_mismatch"),
        ("schema_version", "schema_version_unsupported"),
    ],
)
def test_rule_metric_snapshot_parser_records_one_fixed_reason_and_reraises(
    corruption: str,
    reason: str,
) -> None:
    snapshot = copy.deepcopy(managed_official_compiled_rule_set("starter_6").snapshot)
    if corruption == "structure":
        snapshot.pop("name")
    elif corruption == "content_hash":
        snapshot["content_hash"] = "0" * 64
    else:
        snapshot["schema_version"] = 2

    with pytest.raises(ValueError) as caught:
        resolve_rule_set_snapshot(snapshot)

    assert type(caught.value) is ValueError
    assert f'werewolf_rule_snapshot_failures_total{{reason="{reason}"}} 1' in _rule_metrics()

def test_rule_metric_catalog_corruption_is_counted_once_at_public_boundary() -> None:
    with TestingSessionLocal() as session:
        session.execute(
            update(RuleSetRevisionRecord)
            .where(RuleSetRevisionRecord.id == "e9fa678e-9b18-5079-91d2-f74835364fb6")
            .values(content_hash="0" * 64)
        )
        session.commit()

    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 503
    assert (
        'werewolf_rule_snapshot_failures_total{reason="content_hash_mismatch"} 1' in _rule_metrics()
    )

def test_list_rule_sets_returns_official_rules() -> None:
    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 200
    payload = response.json()
    assert [rule["id"] for rule in payload["rule_sets"]] == [
        "classic_8",
        "starter_6",
        "social_8",
        "classic_12_seer_witch_hunter_idiot",
    ]
    assert payload["rule_sets"][0]["role_summary"] == "2 狼人 / 1 预言家 / 1 守卫 / 4 村民"
    assert any(rule["id"] == "classic_12_seer_witch_hunter_idiot" for rule in payload["rule_sets"])

def test_list_rule_sets_returns_published_database_revisions_default_first() -> None:
    with TestingSessionLocal() as session:
        classic = session.get(RuleSetRecord, "classic_8")
        social = session.get(RuleSetRecord, "social_8")
        assert classic is not None
        assert social is not None
        classic.is_default = False
        session.flush()
        social.is_default = True
        social.display_order = 99
        session.commit()

    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 200, response.text
    items = response.json()["rule_sets"]
    assert [item["id"] for item in items] == [
        "social_8",
        "classic_8",
        "starter_6",
        "classic_12_seer_witch_hunter_idiot",
    ]
    expected_fields = {
        "id",
        "version",
        "name",
        "description",
        "player_count",
        "roles",
        "night_actions",
        "day_actions",
        "win_condition",
        "reveal_policy",
        "complexity",
        "estimated_duration",
        "role_summary",
        "sheriff_enabled",
        "sheriff_vote_weight",
        "speech_policy",
        "speech_rounds",
        "rule_tags",
        "werewolf_self_explosion_enabled",
        "exile_last_words_enabled",
        "first_night_last_words_enabled",
        "sheriff_badge_bomb_policy",
        "werewolf_attack_policy",
        "revision_id",
        "revision_no",
        "schema_version",
        "content_hash",
        "is_default",
    }
    assert all(set(item) == expected_fields for item in items)
    assert all(item["version"] == str(item["revision_no"]) for item in items)
    assert all(len(item["content_hash"]) == 64 for item in items)
    assert all(item["werewolf_attack_policy"] is None for item in items)
    assert items[0]["is_default"] is True
    assert "internal.werewolf.collective_fallback.v1" not in response.text
    assert "狼队集体无有效刀口时" not in response.text
    assert set(items[0]["roles"][0]) == {
        "role",
        "count",
        "team",
        "model_group",
        "category",
    }

def test_list_rule_sets_preserves_explicit_werewolf_attack_policy() -> None:
    policy = {
        "resolution": "plurality_seeded_random",
        "allow_no_attack": True,
        "allow_wolf_target": False,
    }
    seed = next(item for item in OFFICIAL_RULE_SET_SEEDS if item["id"] == "classic_8")
    with TestingSessionLocal() as db:
        db.add(
            User(
                id=101,
                email="catalog-policy@example.test",
                display_name="Catalog policy publisher",
                admin_role="super_admin",
            )
        )
        aggregate = update_rule_set_draft(
            db,
            "classic_8",
            config=normalize_rule_set_config({**seed["config"], "werewolf_attack_policy": policy}),
            display_order=int(seed["display_order"]),
            expected_rule_set_lock_version=1,
            expected_revision_lock_version=None,
            actor_user_id=101,
        )
        assert aggregate.draft is not None
        parent_lock_version = aggregate.record.lock_version
        revision_lock_version = aggregate.draft.lock_version
        db.commit()
        publish_rule_set(
            db,
            "classic_8",
            expected_rule_set_lock_version=parent_lock_version,
            expected_revision_lock_version=revision_lock_version,
            reason="Verify public V2 policy transport",
            actor_user_id=101,
        )
        db.commit()

    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 200, response.text
    classic = next(item for item in response.json()["rule_sets"] if item["id"] == "classic_8")
    assert classic["werewolf_attack_policy"] == policy

def test_list_rule_sets_returns_503_without_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_catalog(*_args: object, **_kwargs: object) -> object:
        raise OperationalError("select", {}, Exception("database unavailable"))

    monkeypatch.setattr(
        "app.api.routes.lobby.list_published_rule_sets",
        fail_catalog,
        raising=False,
    )

    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rule_set_store_unavailable"
    assert "rule_sets" not in response.json()["detail"]

def test_list_rule_sets_returns_503_for_corrupt_catalog_without_stale_snapshot() -> None:
    with TestingSessionLocal() as session:
        session.execute(
            RuleSetRevisionRecord.__table__.update()
            .where(RuleSetRevisionRecord.id == "e9fa678e-9b18-5079-91d2-f74835364fb6")
            .values(content_hash="0" * 64)
        )
        session.commit()

    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rule_set_store_unavailable"
    assert "current_rule_set" not in response.json()["detail"]

def test_list_rule_sets_static_mode_synthesizes_official_revision_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rule_set_catalog_source", "static", raising=False)

    def reject_database_read(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("static compatibility mode must not read the catalog database")

    monkeypatch.setattr(
        "app.api.routes.lobby.list_published_rule_sets",
        reject_database_read,
        raising=False,
    )

    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 200, response.text
    items = response.json()["rule_sets"]
    assert [item["revision_id"] for item in items] == [
        seed["revision_id"] for seed in OFFICIAL_RULE_SET_SEEDS
    ]
    assert [item["content_hash"] for item in items] == [
        seed["content_hash"] for seed in OFFICIAL_RULE_SET_SEEDS
    ]
    starter = next(item for item in items if item["id"] == "starter_6")
    assert starter["description"] == "更短的官方入门局,适合快速观察模型策略。"

def test_list_rule_sets_static_mode_rejects_revision_hash_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rule_set_catalog_source", "static")
    monkeypatch.setitem(
        STATIC_RULE_REVISIONS,
        "classic_8",
        (
            "e9fa678e-9b18-5079-91d2-f74835364fb6",
            "0" * 64,
            True,
        ),
    )

    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rule_set_store_unavailable"

def test_rule_set_catalog_openapi_schema_requires_the_exact_client_contract() -> None:
    schema = app.openapi()["components"]["schemas"]["PublicRuleSetCatalogItem"]

    assert set(schema["required"]) == set(schema["properties"])
    assert "display_order" not in schema["properties"]
    assert {
        "revision_id",
        "revision_no",
        "schema_version",
        "content_hash",
        "is_default",
        "roles",
    }.issubset(schema["required"])

def test_public_problem_extensions_cannot_override_core_problem_fields() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/games/rule-sets",
            "headers": [(b"x-request-id", b"request-safe")],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    problem = public_problem(
        request,
        status_code=409,
        code="safe_code",
        detail="Safe detail.",
        extensions={
            "code": "overridden",
            "message": "Overridden.",
            "request_id": "overridden",
            "current_rule_set": {"id": "classic_8"},
        },
    )

    assert problem.detail == {
        "code": "safe_code",
        "message": "Safe detail.",
        "request_id": "request-safe",
        "current_rule_set": {"id": "classic_8"},
    }

def test_lineup_preview_is_deterministic_and_preserves_locked_seats() -> None:
    add_virtual_profiles(8)
    payload = {
        "rule_set_id": "starter_6",
        "seed": 42,
        "player_configs": [{"seat": 2, "profile_id": "profile-2"}],
        "locked_seats": [2],
        "repair_scope": "unlocked_all",
    }

    first = client.post("/api/v1/games/lineup-preview", json=payload)
    second = client.post("/api/v1/games/lineup-preview", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    configs = first.json()["player_configs"]
    assert len(configs) == 6
    assert next(config for config in configs if config["seat"] == 2)["profile_id"] == "profile-2"
    assert len({config["profile_id"] for config in configs}) == 6
    assert first.json()["lineup_quality_report"]["is_blocked"] is False

def test_lineup_preview_returns_explainable_failure_when_repair_is_unsatisfied() -> None:
    add_virtual_profiles(6, diverse=False)

    response = client.post(
        "/api/v1/games/lineup-preview",
        json={"rule_set_id": "starter_6", "seed": 42},
    )

    assert response.status_code == 422
    problem = response.json()["detail"]
    assert problem["code"] == "lineup_quality_unsatisfied"
    assert problem["lineup_quality_report"]["is_blocked"] is True
    assert "insufficient_style_buckets" in problem["missing_dimensions"]

def test_lineup_preview_reports_locked_manual_risk_for_confirmation() -> None:
    profile_ids = add_virtual_profiles(6, diverse=False)
    player_configs = [
        {"seat": seat, "profile_id": profile_id}
        for seat, profile_id in enumerate(profile_ids, start=1)
    ]

    response = client.post(
        "/api/v1/games/lineup-preview",
        json={
            "rule_set_id": "starter_6",
            "seed": 42,
            "player_configs": player_configs,
            "locked_seats": list(range(1, 7)),
        },
    )

    assert response.status_code == 200
    assert response.json()["lineup_quality_report"]["is_blocked"] is True

