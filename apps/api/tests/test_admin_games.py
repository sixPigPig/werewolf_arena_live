from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.admin.dependencies as admin_dependencies
from app.admin.rbac import AdminPermission
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import LiveEventRecord, LiveRunRecord, VoiceUtteranceRecord
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord


HISTORY_RULE_ID = "history_rule"
HISTORY_REVISION_1_ID = "10000000-0000-0000-0000-000000000001"
HISTORY_REVISION_2_ID = "10000000-0000-0000-0000-000000000002"
OTHER_RULE_ID = "other_rule"
OTHER_REVISION_ID = "20000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class AdminGamesContext:
    client: TestClient
    session_factory: sessionmaker[Session]
    engine: Engine


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> Generator[AdminGamesContext, None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "games-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Games Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "super_admin")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "games_admin_session")
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
        yield AdminGamesContext(
            client=client,
            session_factory=testing_session,
            engine=engine,
        )
    engine.dispose()


def _login(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "super_admin",
) -> dict:
    monkeypatch.setattr(settings, "admin_dev_auth_role", role)
    response = context.client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text
    return response.json()


def _seed_game(
    context: AdminGamesContext,
    *,
    session_id: str,
    run_id: str,
    created_at: datetime,
    status: str = "complete",
    winner: str | None = "好人阵营",
    rule_set_id: str = "starter_6",
    run_status: str = "completed",
    model: str = "model-alpha",
    wolf_model: str | None = None,
    event_count: int = 1,
    run_error: str | None = None,
    game_error: str = "",
    adversarial_unfinished: bool = False,
    rule_set_revision_id: str | None = None,
    rule_set_revision_no: int | None = None,
    rule_set_content_hash: str | None = None,
) -> None:
    resolved_wolf_model = wolf_model or model
    state = {
        "session_id": session_id,
        "players": [
            {
                "name": "张三",
                "role": "预言家",
                "model": model,
                "profile_id": "profile-1",
                "personality_id": "balanced",
                "appearance_id": "default",
                "avatar_image_url": "/api/v1/player-profiles/avatar-assets/default-avatar",
                "avatar_prompt": "SENTINEL_AVATAR_PROMPT",
                "tags": ["冷静", {"SENTINEL_NESTED_TAG": "hidden"}],
                "observations": ["SENTINEL_OBSERVATION"],
                "known_roles": {"李四": "SENTINEL_KNOWN_ROLE"},
                "gamestate": {"SENTINEL_GAMESTATE": "hidden"},
            },
            {
                "name": "李四",
                "role": "狼人",
                "model": resolved_wolf_model,
                "profile_id": None,
                "personality_id": "aggressive",
                "appearance_id": "mysterious",
                "avatar_image_url": "https://tracker.example/SENTINEL_EXTERNAL_AVATAR",
                "tags": [],
            },
        ],
        "rounds": [
            {
                "number": 1,
                "success": True,
                "players": ["张三", "李四", {"SENTINEL_ROUND_PLAYER": "hidden"}],
                "public_summary": "第一轮公开摘要",
                "private_summaries": {"张三": "SENTINEL_PRIVATE_SUMMARY"},
                "night_deaths": [
                    {
                        "player": "李四",
                        "cause": "witch_poison" if adversarial_unfinished else "wolf_attack",
                        "source": ("SENTINEL_POISON_SOURCE" if adversarial_unfinished else None),
                    },
                    {"player": {"SENTINEL_DEATH": "hidden"}, "cause": "invalid"},
                ],
                "day_deaths": [],
                "exiled": "李四",
                "hunter_shot": None,
                "idiot_revealed": None,
                "sheriff": "张三",
                "votes": [
                    {
                        "张三": "李四",
                        "SENTINEL_BAD_VOTE": {"SENTINEL_VOTE_VALUE": "hidden"},
                    }
                ],
                "sheriff_elected": "张三",
                "werewolf_self_exploded": None,
                "protected": ("SENTINEL_PROTECTED_TARGET" if adversarial_unfinished else None),
                "investigated": (
                    "SENTINEL_INVESTIGATED_TARGET" if adversarial_unfinished else None
                ),
                "poisoned": ("SENTINEL_POISONED_TARGET" if adversarial_unfinished else None),
            }
        ],
        "winner": winner or "",
        "error_message": game_error,
        "SENTINEL_UNKNOWN_STATE_KEY": {"deep": "SENTINEL_UNKNOWN_STATE_VALUE"},
    }
    if adversarial_unfinished:
        state["rounds"].append(
            {
                "number": 2,
                "success": False,
                "players": ["张三", "李四"],
                "public_summary": "SENTINEL_CURRENT_ROUND_SUMMARY",
                "night_deaths": [],
                "day_deaths": [],
                "exiled": "SENTINEL_CURRENT_EXILE",
                "votes": [{"SENTINEL_CURRENT_VOTER": "SENTINEL_CURRENT_TARGET"}],
            }
        )
    rule_set = {
        "id": rule_set_id,
        "name": f"Rule {rule_set_id}",
        "player_count": 6,
    }
    with context.session_factory() as db:
        db.add(
            GameSessionRecord(
                session_id=session_id,
                status=status,
                winner=winner,
                round_count=1,
                rule_set_id=rule_set_id,
                rule_set_revision_id=rule_set_revision_id,
                rule_set_revision_no=rule_set_revision_no,
                rule_set_content_hash=rule_set_content_hash,
                rule_set=rule_set,
                resumable=status == "partial",
                created_at=created_at,
                updated_at=created_at + timedelta(minutes=5),
            )
        )
        db.add(
            GameReplayPayload(
                session_id=session_id,
                state=state,
                logs=[
                    {
                        "lm_log": {
                            "prompt": "SENTINEL_PROMPT",
                            "raw_response": "SENTINEL_RAW_RESPONSE",
                            "api_key": "SENTINEL_LOG_API_KEY",
                        }
                    }
                ],
                checkpoint={
                    "token": "SENTINEL_CHECKPOINT_TOKEN",
                    "deep": {"secret": "SENTINEL_CHECKPOINT_SECRET"},
                },
            )
        )
        db.add(
            LiveRunRecord(
                run_id=run_id,
                session_id=session_id,
                status=run_status,
                villager_model=model,
                werewolf_model=resolved_wolf_model,
                seed=42,
                max_rounds=8,
                rule_set_id=rule_set_id,
                rule_set_revision_id=rule_set_revision_id,
                rule_set_revision_no=rule_set_revision_no,
                rule_set_content_hash=rule_set_content_hash,
                rule_set=rule_set,
                player_configs=[],
                lineup_quality_warnings=[],
                winner=winner,
                error=run_error,
                created_at=created_at,
                started_at=created_at + timedelta(seconds=1),
                completed_at=(
                    created_at + timedelta(minutes=2)
                    if run_status in {"completed", "failed"}
                    else None
                ),
                updated_at=created_at + timedelta(minutes=2),
            )
        )
        for event_id in range(1, event_count + 1):
            private_event_metadata = (
                ("SENTINEL_GUARD_ACTOR", "protect"),
                ("SENTINEL_SEER_ACTOR", "investigate"),
                ("SENTINEL_WITCH_ACTOR", "witch_poison"),
            )
            event_actor, event_action = (
                private_event_metadata[(event_id - 1) % len(private_event_metadata)]
                if adversarial_unfinished
                else ("张三", "vote")
            )
            db.add(
                LiveEventRecord(
                    run_id=run_id,
                    event_id=event_id,
                    session_id=session_id,
                    type="state_updated",
                    round=1,
                    phase="night" if adversarial_unfinished else "day",
                    actor=event_actor,
                    action=event_action,
                    payload={
                        "api_key": "SENTINEL_EVENT_API_KEY",
                        "nested": {"token": "SENTINEL_EVENT_TOKEN"},
                    },
                    created_at=created_at + timedelta(seconds=event_id),
                )
            )
        for suffix, voice_status in (("failed", "failed"), ("ok", "completed")):
            db.add(
                VoiceUtteranceRecord(
                    utterance_id=f"utt_{session_id[-8:]}_{suffix}",
                    run_id=run_id,
                    session_id=session_id,
                    source_event_id=1,
                    last_source_event_id=1,
                    request_id=f"voice_{suffix}",
                    speaker_kind="player",
                    speaker_name="张三",
                    speaker="speaker-1",
                    action="debate",
                    text="测试语音",
                    text_hash=f"hash-{session_id}-{suffix}",
                    audio_format="mp3",
                    sample_rate=24000,
                    mime_type="audio/mpeg",
                    status=voice_status,
                    error_message=(
                        "SENTINEL_VOICE_ERROR api_key=SENTINEL_VOICE_KEY"
                        if voice_status == "failed"
                        else None
                    ),
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
        db.commit()


def _revision(
    *,
    revision_id: str,
    rule_set_id: str,
    revision_no: int,
    state: str,
    name: str,
    player_count: int,
    content_hash: str,
    now: datetime,
) -> RuleSetRevisionRecord:
    return RuleSetRevisionRecord(
        id=revision_id,
        rule_set_id=rule_set_id,
        revision_no=revision_no,
        state=state,
        schema_version=1,
        content_hash=content_hash,
        lock_version=1,
        name=name,
        description=f"{name} description",
        player_count=player_count,
        role_summary=f"{player_count} player history rule",
        complexity="history",
        estimated_duration="medium",
        config={"name": name},
        created_at=now,
        updated_at=now,
        published_at=now,
    )


def _seed_historical_revisions(context: AdminGamesContext) -> None:
    now = datetime(2026, 7, 9, tzinfo=UTC)
    with context.session_factory() as db:
        db.add_all(
            [
                RuleSetRecord(
                    id=HISTORY_RULE_ID,
                    status="archived",
                    current_published_revision_id=HISTORY_REVISION_2_ID,
                    draft_revision_id=None,
                    is_default=False,
                    display_order=10,
                    lock_version=3,
                    created_at=now,
                    updated_at=now + timedelta(days=2),
                    archived_at=now + timedelta(days=2),
                ),
                RuleSetRecord(
                    id=OTHER_RULE_ID,
                    status="published",
                    current_published_revision_id=OTHER_REVISION_ID,
                    draft_revision_id=None,
                    is_default=False,
                    display_order=20,
                    lock_version=1,
                    created_at=now,
                    updated_at=now,
                ),
                _revision(
                    revision_id=HISTORY_REVISION_1_ID,
                    rule_set_id=HISTORY_RULE_ID,
                    revision_no=1,
                    state="superseded",
                    name="Historical Revision One",
                    player_count=6,
                    content_hash="1" * 64,
                    now=now,
                ),
                _revision(
                    revision_id=HISTORY_REVISION_2_ID,
                    rule_set_id=HISTORY_RULE_ID,
                    revision_no=2,
                    state="published",
                    name="Current Revision Two",
                    player_count=8,
                    content_hash="2" * 64,
                    now=now + timedelta(days=1),
                ),
                _revision(
                    revision_id=OTHER_REVISION_ID,
                    rule_set_id=OTHER_RULE_ID,
                    revision_no=1,
                    state="published",
                    name="Other Rule",
                    player_count=10,
                    content_hash="4" * 64,
                    now=now,
                ),
            ]
        )
        db.commit()


def test_admin_games_requires_authentication_and_games_read_permission(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unauthenticated = context.client.get("/api/v1/admin/games")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["code"] == "admin_auth_required"

    _login(context, monkeypatch, role="viewer")
    allowed = context.client.get("/api/v1/admin/games")
    assert allowed.status_code == 200

    monkeypatch.setattr(
        admin_dependencies,
        "permissions_for_role",
        lambda _role: frozenset({AdminPermission.PLAYERS_READ}),
    )
    forbidden = context.client.get("/api/v1/admin/games")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "admin_permission_denied"
    assert "games.read" in forbidden.json()["detail"]


def test_admin_games_list_paginates_sorts_and_filters_without_loading_replay_payload(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 7, 10, 10, tzinfo=UTC)
    _seed_game(
        context,
        session_id="game_00000001",
        run_id="run_000000000001",
        created_at=base,
        winner="狼人阵营",
        model="model-alpha",
    )
    _seed_game(
        context,
        session_id="game_00000002",
        run_id="run_000000000002",
        created_at=base + timedelta(hours=1),
        status="partial",
        winner=None,
        rule_set_id="classic_8",
        run_status="failed",
        model="model-beta",
        run_error="connection failed",
    )
    _seed_game(
        context,
        session_id="game_00000003",
        run_id="run_000000000003",
        created_at=base + timedelta(hours=2),
        winner="好人阵营",
        run_status="running",
        model="model-gamma",
    )
    _login(context, monkeypatch, role="viewer")

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lower())

    event.listen(context.engine, "before_cursor_execute", capture_sql)
    try:
        page = context.client.get(
            "/api/v1/admin/games",
            params={"page": 1, "page_size": 2, "sort": "created_at"},
            headers={"X-Request-ID": "admin-games-list-1"},
        )
    finally:
        event.remove(context.engine, "before_cursor_execute", capture_sql)

    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-request-id"] == "admin-games-list-1"
    assert [item["session_id"] for item in page.json()["items"]] == [
        "game_00000001",
        "game_00000002",
    ]
    assert page.json()["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 3,
        "pages": 2,
    }
    assert all("game_replay_payloads" not in statement for statement in statements)
    assert all("game_sessions.rule_set as" not in statement for statement in statements)
    assert all("live_runs.rule_set," not in statement for statement in statements)
    assert all("rule_set_revisions.config" not in statement for statement in statements)
    assert all("rule_set_revisions.description" not in statement for statement in statements)
    assert all("live_events.payload" not in statement for statement in statements)
    data_statements = [
        statement
        for statement in statements
        if any(table in statement for table in ("game_sessions", "live_runs", "live_events"))
    ]
    assert len(data_statements) == 4

    query_match = context.client.get("/api/v1/admin/games", params={"q": "model-alpha"})
    combined_filters = context.client.get(
        "/api/v1/admin/games",
        params={
            "status": "complete",
            "winner": "好人阵营",
            "rule_set_id": "starter_6",
            "run_status": "running",
        },
    )
    time_filter = context.client.get(
        "/api/v1/admin/games",
        params={"created_from": "2026-07-10T10:30:00+00:00"},
    )

    assert [item["session_id"] for item in query_match.json()["items"]] == ["game_00000001"]
    assert [item["session_id"] for item in combined_filters.json()["items"]] == ["game_00000003"]
    assert {item["session_id"] for item in time_filter.json()["items"]} == {
        "game_00000002",
        "game_00000003",
    }
    assert combined_filters.json()["items"][0]["latest_run"]["status"] == "running"


def test_admin_games_filter_and_render_exact_historical_rule_revisions(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_historical_revisions(context)
    base = datetime(2026, 7, 10, tzinfo=UTC)
    _seed_game(
        context,
        session_id="game_00000101",
        run_id="run_000000000101",
        created_at=base,
        rule_set_id=HISTORY_RULE_ID,
        rule_set_revision_id=HISTORY_REVISION_1_ID,
        rule_set_revision_no=1,
        rule_set_content_hash="1" * 64,
    )
    _seed_game(
        context,
        session_id="game_00000102",
        run_id="run_000000000102",
        created_at=base + timedelta(hours=1),
        rule_set_id=HISTORY_RULE_ID,
        rule_set_revision_id=HISTORY_REVISION_2_ID,
        rule_set_revision_no=2,
        rule_set_content_hash="2" * 64,
    )
    _seed_game(
        context,
        session_id="game_00000103",
        run_id="run_000000000103",
        created_at=base + timedelta(hours=2),
        rule_set_id=HISTORY_RULE_ID,
        rule_set_content_hash="3" * 64,
    )
    _seed_game(
        context,
        session_id="game_00000104",
        run_id="run_000000000104",
        created_at=base + timedelta(hours=3),
        rule_set_id=OTHER_RULE_ID,
        rule_set_revision_id=OTHER_REVISION_ID,
        rule_set_revision_no=1,
        rule_set_content_hash="4" * 64,
    )
    _seed_game(
        context,
        session_id="game_00000105",
        run_id="run_000000000105",
        created_at=base + timedelta(hours=4),
        rule_set_id=HISTORY_RULE_ID,
        rule_set_revision_id=HISTORY_REVISION_1_ID,
        rule_set_revision_no=1,
        rule_set_content_hash="1" * 64,
    )
    with context.session_factory() as db:
        revision_one = db.get(GameSessionRecord, "game_00000101")
        revision_two = db.get(GameSessionRecord, "game_00000102")
        legacy = db.get(GameSessionRecord, "game_00000103")
        fallback = db.get(GameSessionRecord, "game_00000105")
        assert revision_one is not None
        assert revision_two is not None
        assert legacy is not None
        assert fallback is not None
        revision_one.rule_set = {
            "id": HISTORY_RULE_ID,
            "name": "Saved Revision One Snapshot",
            "player_count": 7,
        }
        revision_two.rule_set = {
            "id": OTHER_RULE_ID,
            "name": "SENTINEL_DISAGREEING_JSON_NAME",
            "player_count": 12,
        }
        legacy.rule_set = {
            "id": HISTORY_RULE_ID,
            "name": "SENTINEL_LEGACY_SNAPSHOT_NAME",
            "player_count": 9,
        }
        fallback.rule_set_id = None
        fallback.rule_set_revision_id = None
        fallback.rule_set_revision_no = None
        fallback.rule_set_content_hash = None
        fallback.rule_set = None
        db.commit()

    import app.werewolf.rules as static_rules

    monkeypatch.setattr(
        static_rules,
        "get_rule_set",
        lambda _rule_set_id: pytest.fail("Admin history must not use the static rule catalog"),
    )
    _login(context, monkeypatch, role="viewer")

    stable = context.client.get(
        "/api/v1/admin/games",
        params={"rule_set_id": HISTORY_RULE_ID, "sort": "created_at"},
    )
    exact = context.client.get(
        "/api/v1/admin/games",
        params={"rule_set_revision_id": HISTORY_REVISION_1_ID},
    )
    impossible_pair = context.client.get(
        "/api/v1/admin/games",
        params={
            "rule_set_id": HISTORY_RULE_ID,
            "rule_set_revision_id": OTHER_REVISION_ID,
        },
    )
    json_id_probe = context.client.get(
        "/api/v1/admin/games",
        params={"rule_set_id": OTHER_RULE_ID},
    )
    detail = context.client.get("/api/v1/admin/games/game_00000101")
    mismatch_detail = context.client.get("/api/v1/admin/games/game_00000102")
    fallback_page = context.client.get(
        "/api/v1/admin/games",
        params={"sort": "created_at", "page_size": 100},
    )

    assert stable.status_code == 200, stable.text
    by_session = {item["session_id"]: item for item in stable.json()["items"]}
    assert list(by_session) == ["game_00000101", "game_00000102", "game_00000103"]
    assert by_session["game_00000101"]["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": "Historical Revision One",
        "player_count": 6,
        "revision_id": HISTORY_REVISION_1_ID,
        "revision_no": 1,
        "content_hash": "1" * 64,
    }
    assert by_session["game_00000102"]["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": "Current Revision Two",
        "player_count": 8,
        "revision_id": HISTORY_REVISION_2_ID,
        "revision_no": 2,
        "content_hash": "2" * 64,
    }
    assert by_session["game_00000103"]["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": HISTORY_RULE_ID,
        "player_count": None,
        "revision_id": None,
        "revision_no": None,
        "content_hash": "3" * 64,
    }
    assert exact.status_code == 200
    assert [item["session_id"] for item in exact.json()["items"]] == ["game_00000101"]
    assert impossible_pair.status_code == 200
    assert impossible_pair.json()["items"] == []
    assert json_id_probe.status_code == 200
    assert [item["session_id"] for item in json_id_probe.json()["items"]] == ["game_00000104"]
    assert detail.status_code == 200
    assert detail.json()["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": "Saved Revision One Snapshot",
        "player_count": 7,
        "revision_id": HISTORY_REVISION_1_ID,
        "revision_no": 1,
        "content_hash": "1" * 64,
    }
    assert mismatch_detail.status_code == 200
    assert mismatch_detail.json()["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": "Current Revision Two",
        "player_count": 8,
        "revision_id": HISTORY_REVISION_2_ID,
        "revision_no": 2,
        "content_hash": "2" * 64,
    }
    fallback_item = next(
        item for item in fallback_page.json()["items"] if item["session_id"] == "game_00000105"
    )
    assert fallback_item["rule_set"] == {
        "id": HISTORY_RULE_ID,
        "name": "Historical Revision One",
        "player_count": 6,
        "revision_id": HISTORY_REVISION_1_ID,
        "revision_no": 1,
        "content_hash": "1" * 64,
    }


def test_admin_games_rejects_invalid_pagination_status_and_time_range(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch, role="viewer")

    invalid_page = context.client.get("/api/v1/admin/games", params={"page_size": 101})
    invalid_status = context.client.get("/api/v1/admin/games", params={"status": "running"})
    missing_timezone = context.client.get(
        "/api/v1/admin/games",
        params={"created_from": "2026-07-10T10:00:00"},
    )
    reversed_range = context.client.get(
        "/api/v1/admin/games",
        params={
            "created_from": "2026-07-11T10:00:00+00:00",
            "created_to": "2026-07-10T10:00:00+00:00",
        },
    )

    assert invalid_page.status_code == 422
    assert invalid_page.json()["code"] == "admin_request_invalid"
    assert invalid_status.status_code == 422
    assert invalid_status.json()["code"] == "admin_request_invalid"
    assert missing_timezone.status_code == 422
    assert missing_timezone.json()["code"] == "admin_game_filter_invalid"
    assert reversed_range.status_code == 422
    assert reversed_range.json()["code"] == "admin_game_filter_invalid"


def test_run_status_filter_only_matches_the_latest_run(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 10, 11, tzinfo=UTC)
    session_id = "game_00000004"
    _seed_game(
        context,
        session_id=session_id,
        run_id="run_000000000040",
        created_at=created_at,
        status="partial",
        winner=None,
        run_status="failed",
        run_error="connection failed",
    )
    with context.session_factory() as db:
        db.add(
            LiveRunRecord(
                run_id="run_000000000041",
                session_id=session_id,
                status="completed",
                villager_model="model-new",
                werewolf_model="model-new",
                max_rounds=8,
                rule_set_id="starter_6",
                player_configs=[],
                lineup_quality_warnings=[],
                created_at=created_at + timedelta(minutes=1),
                completed_at=created_at + timedelta(minutes=2),
                updated_at=created_at + timedelta(minutes=2),
            )
        )
        db.commit()
    _login(context, monkeypatch, role="viewer")

    failed = context.client.get(
        "/api/v1/admin/games",
        params={"run_status": "failed"},
    )
    completed = context.client.get(
        "/api/v1/admin/games",
        params={"run_status": "completed"},
    )

    assert failed.status_code == 200
    assert failed.json()["items"] == []
    assert completed.status_code == 200
    assert [item["session_id"] for item in completed.json()["items"]] == [session_id]
    assert completed.json()["items"][0]["latest_run"]["run_id"] == "run_000000000041"
    assert completed.json()["items"][0]["latest_run"]["status"] == "completed"
    assert completed.json()["items"][0]["latest_run"]["villager_model"] is None
    assert completed.json()["items"][0]["latest_run"]["werewolf_model"] is None


def test_admin_game_detail_is_strictly_whitelisted_bounded_and_hides_partial_roles(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 10, 12, tzinfo=UTC)
    _seed_game(
        context,
        session_id="game_00000010",
        run_id="run_000000000010",
        created_at=created_at,
        event_count=55,
        run_error="api_key=SENTINEL_RUN_KEY timeout",
        game_error="Authorization: Bearer SENTINEL_GAME_TOKEN",
    )
    _seed_game(
        context,
        session_id="game_00000011",
        run_id="run_000000000011",
        created_at=created_at + timedelta(hours=1),
        status="partial",
        winner=None,
        model="SENTINEL_VILLAGER_MODEL",
        wolf_model="SENTINEL_WOLF_MODEL",
        event_count=3,
        adversarial_unfinished=True,
    )
    _seed_game(
        context,
        session_id="game_00000012",
        run_id="run_000000000012",
        created_at=created_at + timedelta(hours=2),
    )
    with context.session_factory() as db:
        resumable_record = db.get(GameSessionRecord, "game_00000012")
        assert resumable_record is not None
        resumable_record.resumable = True
        db.commit()
    _login(context, monkeypatch, role="viewer")

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lower())

    event.listen(context.engine, "before_cursor_execute", capture_sql)
    try:
        response = context.client.get("/api/v1/admin/games/game_00000010")
    finally:
        event.remove(context.engine, "before_cursor_execute", capture_sql)
    partial_statements: list[str] = []

    def capture_partial_sql(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        partial_statements.append(statement.lower())

    event.listen(context.engine, "before_cursor_execute", capture_partial_sql)
    try:
        partial = context.client.get("/api/v1/admin/games/game_00000011")
    finally:
        event.remove(context.engine, "before_cursor_execute", capture_partial_sql)
    resumable = context.client.get("/api/v1/admin/games/game_00000012")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["players"][0]["role"] == "预言家"
    assert payload["players"][0]["tags"] == ["冷静"]
    assert payload["players"][1]["avatar_image_url"] == ""
    assert payload["rounds"][0]["votes"] == {"张三": "李四"}
    assert payload["rounds"][0]["night_deaths"] == [
        {"player": "李四", "cause": "wolf_attack", "source": None}
    ]
    assert len(payload["recent_events"]) == 50
    assert payload["recent_events"][0]["event_id"] == 6
    assert payload["recent_events"][-1]["event_id"] == 55
    assert payload["diagnostics"] == {
        "run_count": 1,
        "event_count": 55,
        "failed_voice_count": 1,
        "last_event": payload["recent_events"][-1],
    }
    assert partial.status_code == 200
    assert all(player["role"] is None for player in partial.json()["players"])
    assert all(player["model"] is None for player in partial.json()["players"])
    assert partial.json()["latest_run"]["villager_model"] is None
    assert partial.json()["latest_run"]["werewolf_model"] is None
    assert all(run["villager_model"] is None for run in partial.json()["runs"])
    assert all(run["werewolf_model"] is None for run in partial.json()["runs"])
    assert partial.json()["recent_events"] == []
    assert partial.json()["diagnostics"]["last_event"] is None
    assert partial.json()["diagnostics"]["event_count"] == 3
    assert [round_item["number"] for round_item in partial.json()["rounds"]] == [1]
    assert partial.json()["rounds"][0]["night_deaths"] == [
        {"player": "李四", "cause": None, "source": None}
    ]
    assert resumable.status_code == 200
    assert all(player["role"] is None for player in resumable.json()["players"])
    assert all(player["model"] is None for player in resumable.json()["players"])
    assert resumable.json()["latest_run"]["villager_model"] is None
    assert resumable.json()["latest_run"]["werewolf_model"] is None
    assert resumable.json()["recent_events"] == []
    assert resumable.json()["diagnostics"]["last_event"] is None

    partial_serialized = json.dumps(partial.json(), ensure_ascii=False)
    for private_marker in (
        "SENTINEL_VILLAGER_MODEL",
        "SENTINEL_WOLF_MODEL",
        "SENTINEL_GUARD_ACTOR",
        "SENTINEL_SEER_ACTOR",
        "SENTINEL_WITCH_ACTOR",
        "SENTINEL_POISON_SOURCE",
        "SENTINEL_PROTECTED_TARGET",
        "SENTINEL_INVESTIGATED_TARGET",
        "SENTINEL_POISONED_TARGET",
        "SENTINEL_CURRENT_ROUND_SUMMARY",
        "SENTINEL_CURRENT_EXILE",
        "SENTINEL_CURRENT_VOTER",
        "SENTINEL_CURRENT_TARGET",
    ):
        assert private_marker not in partial_serialized
    assert "protect" not in partial_serialized
    assert "investigate" not in partial_serialized
    assert "witch_poison" not in partial_serialized
    for private_event_column in (
        "live_events.event_id",
        "live_events.type",
        "live_events.round",
        "live_events.phase",
        "live_events.actor",
        "live_events.action",
        "live_events.payload",
        "live_events.created_at",
    ):
        assert all(private_event_column not in sql for sql in partial_statements)

    serialized = json.dumps(payload, ensure_ascii=False)
    for marker in (
        "SENTINEL_AVATAR_PROMPT",
        "SENTINEL_NESTED_TAG",
        "SENTINEL_OBSERVATION",
        "SENTINEL_KNOWN_ROLE",
        "SENTINEL_GAMESTATE",
        "SENTINEL_PRIVATE_SUMMARY",
        "SENTINEL_PROMPT",
        "SENTINEL_RAW_RESPONSE",
        "SENTINEL_LOG_API_KEY",
        "SENTINEL_CHECKPOINT_TOKEN",
        "SENTINEL_CHECKPOINT_SECRET",
        "SENTINEL_EVENT_API_KEY",
        "SENTINEL_EVENT_TOKEN",
        "SENTINEL_RUN_KEY",
        "SENTINEL_GAME_TOKEN",
        "SENTINEL_VOICE_ERROR",
        "SENTINEL_EXTERNAL_AVATAR",
        "SENTINEL_UNKNOWN_STATE_VALUE",
    ):
        assert marker not in serialized
    forbidden_keys = {
        "payload",
        "logs",
        "checkpoint",
        "prompt",
        "raw_response",
        "observations",
        "known_roles",
        "gamestate",
        "private_summaries",
        "avatar_prompt",
        "debug",
        "game_error",
        "error",
    }
    assert forbidden_keys.isdisjoint(_all_keys(payload))
    replay_queries = [sql for sql in statements if "game_replay_payloads" in sql]
    assert len(replay_queries) == 1
    assert "game_replay_payloads.state" in replay_queries[0]
    assert "game_replay_payloads.logs" not in replay_queries[0]
    assert "game_replay_payloads.checkpoint" not in replay_queries[0]
    assert all("live_events.payload" not in sql for sql in statements)
    assert all("live_runs.player_configs" not in sql for sql in statements)
    assert all("live_runs.lineup_quality_warnings" not in sql for sql in statements)
    assert all("voice_audio_chunks" not in sql for sql in statements)


def test_admin_game_detail_returns_problem_404_for_missing_game(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(context, monkeypatch, role="viewer")

    response = context.client.get(
        "/api/v1/admin/games/game_deadbeef",
        headers={"X-Request-ID": "missing-game-1"},
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "missing-game-1"
    assert response.json()["code"] == "admin_game_not_found"


def test_game_debug_requires_debug_permission_returns_safe_summaries_and_audits(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 10, 14, tzinfo=UTC)
    _seed_game(
        context,
        session_id="game_00000020",
        run_id="run_000000000020",
        created_at=created_at,
        run_status="failed",
        run_error="401 authorization=Bearer SENTINEL_AUTH_TOKEN",
        game_error="api_key=SENTINEL_GAME_KEY invalid json response",
    )
    with context.session_factory() as db:
        for index in range(21, 44):
            db.add(
                LiveRunRecord(
                    run_id=f"run_0000000000{index:02d}",
                    session_id="game_00000020",
                    status="failed",
                    villager_model="model-alpha",
                    werewolf_model="model-alpha",
                    max_rounds=8,
                    rule_set_id="starter_6",
                    player_configs=[],
                    lineup_quality_warnings=[],
                    error=f"token=SENTINEL_RUN_TOKEN_{index} timeout",
                    created_at=created_at + timedelta(seconds=index),
                    updated_at=created_at + timedelta(seconds=index),
                )
            )
        db.commit()

    _login(context, monkeypatch, role="viewer")
    forbidden = context.client.get("/api/v1/admin/games/game_00000020/debug")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "admin_permission_denied"

    _login(context, monkeypatch, role="operator")
    response = context.client.get(
        "/api/v1/admin/games/game_00000020/debug",
        headers={"X-Request-ID": "game-debug-1"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session_id"] == "game_00000020"
    assert payload["game_error"] == "Model response validation failed"
    assert len(payload["run_errors"]) == 20
    assert {item["error"] for item in payload["run_errors"]} == {"Upstream request timed out"}
    serialized = json.dumps(payload)
    assert "SENTINEL" not in serialized
    assert "Bearer" not in serialized
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "game-debug-1"

    with context.session_factory() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "admin.game.debug.read"))
    assert audit is not None
    assert audit.resource_type == "game_session"
    assert audit.resource_id == "game_00000020"
    assert audit.result == "success"
    assert audit.after == {"game_error_present": True, "run_error_count": 20}


def test_admin_game_query_indexes_are_registered_in_model_metadata() -> None:
    indexes = {index.name: index for index in GameSessionRecord.__table__.indexes}

    assert "ix_game_sessions_created_at_session_id_desc" in indexes
    assert "ix_game_sessions_status_created_at_session_id_desc" in indexes
    assert len(indexes["ix_game_sessions_created_at_session_id_desc"].expressions) == 2
    assert len(indexes["ix_game_sessions_status_created_at_session_id_desc"].expressions) == 3

    live_run_indexes = {index.name: index for index in LiveRunRecord.__table__.indexes}
    latest_run_index = live_run_indexes["ix_live_runs_session_created_run_desc"]
    assert len(latest_run_index.expressions) == 3
    assert latest_run_index.expressions[0].name == "session_id"
    assert str(latest_run_index.expressions[1]).endswith("created_at DESC")
    assert str(latest_run_index.expressions[2]).endswith("run_id DESC")


def test_admin_game_query_index_migration_creates_and_drops_latest_run_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260710_04_add_admin_game_query_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("admin_game_query_indexes", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert isinstance(module, ModuleType)
    spec.loader.exec_module(module)

    created: list[tuple[str, str, list[object]]] = []
    dropped: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        module.op,
        "create_index",
        lambda name, table_name, columns: created.append((name, table_name, columns)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_index",
        lambda name, table_name=None: dropped.append((name, table_name)),
    )

    module.upgrade()
    module.downgrade()

    latest_created = next(
        item for item in created if item[0] == "ix_live_runs_session_created_run_desc"
    )
    assert latest_created[1] == "live_runs"
    assert len(latest_created[2]) == 3
    assert any(item == ("ix_live_runs_session_created_run_desc", "live_runs") for item in dropped)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            child_key for child in value.values() for child_key in _all_keys(child)
        }
    if isinstance(value, list):
        return {child_key for child in value for child_key in _all_keys(child)}
    return set()
