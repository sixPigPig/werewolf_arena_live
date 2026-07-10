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
                        "source": (
                            "SENTINEL_POISON_SOURCE" if adversarial_unfinished else None
                        ),
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
                "protected": (
                    "SENTINEL_PROTECTED_TARGET" if adversarial_unfinished else None
                ),
                "investigated": (
                    "SENTINEL_INVESTIGATED_TARGET" if adversarial_unfinished else None
                ),
                "poisoned": (
                    "SENTINEL_POISONED_TARGET" if adversarial_unfinished else None
                ),
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

    query_match = context.client.get("/api/v1/admin/games", params={"q": "model-beta"})
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

    assert [item["session_id"] for item in query_match.json()["items"]] == [
        "game_00000002"
    ]
    assert [item["session_id"] for item in combined_filters.json()["items"]] == [
        "game_00000003"
    ]
    assert {item["session_id"] for item in time_filter.json()["items"]} == {
        "game_00000002",
        "game_00000003",
    }
    assert combined_filters.json()["items"][0]["latest_run"]["status"] == "running"


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
    assert {item["error"] for item in payload["run_errors"]} == {
        "Upstream request timed out"
    }
    serialized = json.dumps(payload)
    assert "SENTINEL" not in serialized
    assert "Bearer" not in serialized
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "game-debug-1"

    with context.session_factory() as db:
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.game.debug.read")
        )
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
    assert any(
        item == ("ix_live_runs_session_created_run_desc", "live_runs")
        for item in dropped
    )


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            child_key
            for child in value.values()
            for child_key in _all_keys(child)
        }
    if isinstance(value, list):
        return {child_key for child in value for child_key in _all_keys(child)}
    return set()
