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
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.admin.dependencies as admin_dependencies
from app.admin.quality_evaluations import build_admin_quality_summary
from app.admin.rbac import AdminPermission
from app.api.schemas.admin_games import (
    AdminGameQualityEvaluationSummary,
    AdminQualityLatestSuccessfulResult,
)
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceMaterializationJobRecord,
    VoiceUtteranceRecord,
)
from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.werewolf.quality_store import build_database_quality_bundle


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
                "sheriff_candidates": ["张三", "李四"],
                "sheriff_speech_order": ["张三", "李四"],
                "sheriff_speech_direction": "顺时针",
                "sheriff_speeches": [{"speaker": "张三", "message": "我会先听清大家的竞选理由。"}],
                "sheriff_withdrawn": ["李四"],
                "sheriff_final_candidates": ["张三"],
                "sheriff_votes": {"李四": "张三"},
                "sheriff_pk_candidates": [],
                "sheriff_pk_speeches": [],
                "sheriff_runoff_votes": {},
                "debate": [{"speaker": "张三", "message": "这是可以进入后台记录的公开发言。"}],
                "speech_order": ["李四", "张三"],
                "speech_order_choice": "警左发言",
                "votes": [
                    {
                        "张三": "李四",
                        "SENTINEL_BAD_VOTE": {"SENTINEL_VOTE_VALUE": "hidden"},
                    }
                ],
                "sheriff_elected": "张三",
                "sheriff_badge_target": None,
                "sheriff_badge_lost": False,
                "sheriff_badge_lost_reason": None,
                "werewolf_self_exploded": None,
                "day_ended_by_self_explosion": False,
                "public_outcome_events": [
                    {
                        "schema_version": 1,
                        "event_id": "outcome_1111111111111111",
                        "sequence": 1,
                        "kind": "night_death",
                        "actor_player_id": None,
                        "target_player_id": "2号玩家",
                        "outcome": "eliminated",
                        "caused_by_event_id": None,
                        "occurred_phase": "night",
                    }
                ],
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


def test_super_admin_deletes_game_and_all_owned_payloads(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 14, 10, tzinfo=UTC)
    session_id = "game_00000031"
    run_id = "run_000000000031"
    utterance_id = "utt_00000031_failed"
    _seed_game(
        context,
        session_id=session_id,
        run_id=run_id,
        created_at=created_at,
    )
    with context.session_factory() as db:
        db.add(
            VoiceAudioChunkRecord(
                utterance_id=utterance_id,
                chunk_index=0,
                audio=b"audio",
                byte_length=5,
                created_at=created_at,
            )
        )
        db.add(
            VoiceMaterializationJobRecord(
                run_id=run_id,
                source_event_id=1,
                speaker_kind="player",
                session_id=session_id,
                status="completed",
                created_at=created_at,
                updated_at=created_at,
                completed_at=created_at,
            )
        )
        db.add(
            GameQualityEvaluationRecord(
                id="quality_admin_delete_31",
                session_id=session_id,
                run_id=run_id,
                evaluator_version="p3-v1",
                source_revision="3" * 64,
                status="completed",
                data_status="available",
                verdict="pass",
                safe_summary={},
                completed_at=created_at,
            )
        )
        db.commit()

    viewer = _login(context, monkeypatch, role="viewer")
    forbidden = context.client.delete(
        f"/api/v1/admin/games/{session_id}",
        headers={"X-CSRF-Token": viewer["csrf_token"]},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "admin_permission_denied"
    assert "games.delete" in forbidden.json()["detail"]

    super_admin = _login(context, monkeypatch, role="super_admin")
    missing_csrf = context.client.delete(f"/api/v1/admin/games/{session_id}")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "admin_csrf_invalid"

    deleted = context.client.delete(
        f"/api/v1/admin/games/{session_id}",
        headers={
            "X-CSRF-Token": super_admin["csrf_token"],
            "X-Request-ID": "admin-game-delete-31",
        },
    )
    assert deleted.status_code == 204, deleted.text
    assert deleted.content == b""
    assert deleted.headers["cache-control"] == "no-store"
    assert deleted.headers["x-request-id"] == "admin-game-delete-31"

    with context.session_factory() as db:
        assert db.get(GameSessionRecord, session_id) is None
        assert db.get(GameReplayPayload, session_id) is None
        assert db.get(LiveRunRecord, run_id) is None
        assert db.get(VoiceAudioChunkRecord, (utterance_id, 0)) is None
        assert not list(
            db.scalars(
                select(LiveEventRecord).where(LiveEventRecord.session_id == session_id)
            )
        )
        assert not list(
            db.scalars(
                select(VoiceMaterializationJobRecord).where(
                    VoiceMaterializationJobRecord.session_id == session_id
                )
            )
        )
        assert not list(
            db.scalars(
                select(VoiceUtteranceRecord).where(
                    VoiceUtteranceRecord.session_id == session_id
                )
            )
        )
        assert not list(
            db.scalars(
                select(GameQualityEvaluationRecord).where(
                    GameQualityEvaluationRecord.session_id == session_id
                )
            )
        )
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.game.delete",
                AuditEvent.resource_id == session_id,
                AuditEvent.result == "success",
            )
        )
    assert audit is not None
    assert audit.before == {"status": "complete", "resumable": False}


def test_admin_game_delete_rejects_active_runs_and_missing_games(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_00000032"
    _seed_game(
        context,
        session_id=session_id,
        run_id="run_000000000032",
        created_at=datetime(2026, 7, 14, 11, tzinfo=UTC),
        status="partial",
        run_status="running",
    )
    login = _login(context, monkeypatch, role="super_admin")
    headers = {"X-CSRF-Token": login["csrf_token"]}

    conflict = context.client.delete(
        f"/api/v1/admin/games/{session_id}", headers=headers
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "admin_game_delete_active_run"

    missing = context.client.delete(
        "/api/v1/admin/games/game_deadbeef", headers=headers
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "admin_game_not_found"

    with context.session_factory() as db:
        assert db.get(GameSessionRecord, session_id) is not None
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.game.delete",
                AuditEvent.resource_id == session_id,
                AuditEvent.result == "rejected",
            )
        )
    assert audit is not None
    assert audit.reason == "active_run"
    assert audit.before == {
        "run_id": "run_000000000032",
        "run_status": "running",
    }


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
    assert combined_filters.json()["items"][0]["latest_run"]["stop_requested_at"] is None


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
                    parent_run_id="run_000000000040",
                    resume_from_round=1,
                    attempt_no=2,
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
    assert completed.json()["items"][0]["latest_run"]["villager_model"] == "model-new"
    assert completed.json()["items"][0]["latest_run"]["werewolf_model"] == "model-new"


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
        replay = db.get(GameReplayPayload, "game_00000010")
        assert replay is not None
        state = dict(replay.state)
        rounds = [dict(item) for item in state["rounds"]]
        rounds[0]["public_summary"] = ""
        state["rounds"] = rounds
        replay.state = state
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
    assert payload["rounds"][0]["public_summary"] == "第1轮；2号玩家夜间出局。"
    assert payload["rounds"][0]["votes"] == {"张三": "李四"}
    assert payload["rounds"][0]["sheriff_candidates"] == ["张三", "李四"]
    assert payload["rounds"][0]["sheriff_votes"] == {"李四": "张三"}
    assert payload["rounds"][0]["speech_order"] == ["李四", "张三"]
    assert payload["rounds"][0]["sheriff_speeches"] == [
        {"speaker": "张三", "message": "我会先听清大家的竞选理由。"}
    ]
    assert payload["rounds"][0]["debate"] == [
        {"speaker": "张三", "message": "这是可以进入后台记录的公开发言。"}
    ]
    assert payload["rounds"][0]["night_deaths"] == [
        {"player": "李四", "cause": None, "source": None}
    ]
    assert payload["p2_quality"]["public_outcomes"][0]["target_player_id"] == "2号玩家"
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
    assert [player["model"] for player in partial.json()["players"]] == [
        "SENTINEL_VILLAGER_MODEL",
        "SENTINEL_WOLF_MODEL",
    ]
    assert partial.json()["latest_run"]["villager_model"] == "SENTINEL_VILLAGER_MODEL"
    assert partial.json()["latest_run"]["werewolf_model"] == "SENTINEL_WOLF_MODEL"
    assert all(
        run["villager_model"] == "SENTINEL_VILLAGER_MODEL"
        for run in partial.json()["runs"]
    )
    assert all(
        run["werewolf_model"] == "SENTINEL_WOLF_MODEL"
        for run in partial.json()["runs"]
    )
    assert partial.json()["recent_events"] == []
    assert partial.json()["diagnostics"]["last_event"] is None
    assert partial.json()["diagnostics"]["event_count"] == 3
    assert [round_item["number"] for round_item in partial.json()["rounds"]] == [1]
    assert partial.json()["rounds"][0]["night_deaths"] == [
        {"player": "李四", "cause": None, "source": None}
    ]
    assert resumable.status_code == 200
    assert all(player["role"] is None for player in resumable.json()["players"])
    assert all(player["model"] == "model-alpha" for player in resumable.json()["players"])
    assert resumable.json()["latest_run"]["villager_model"] == "model-alpha"
    assert resumable.json()["latest_run"]["werewolf_model"] == "model-alpha"
    assert resumable.json()["recent_events"] == []
    assert resumable.json()["diagnostics"]["last_event"] is None

    partial_serialized = json.dumps(partial.json(), ensure_ascii=False)
    for private_marker in (
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
                        parent_run_id=f"run_0000000000{index - 1:02d}",
                        resume_from_round=1,
                        attempt_no=index - 19,
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


def test_game_model_requests_require_debug_permission_are_deduped_and_audited(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 10, 15, tzinfo=UTC)
    session_id = "game_00000021"
    run_id = "run_000000000021"
    request_id = "req_model_detail_21"
    event_only_request_id = "req_failed_event_21"
    _seed_game(
        context,
        session_id=session_id,
        run_id=run_id,
        created_at=created_at,
    )
    model_action = {
        "actor": "张三",
        "action": "debate",
        "attempt_count": 2,
        "raw_choice": "SENTINEL_RAW_CHOICE",
        "lm_log": {
            "request_id": request_id,
            "prompt": "SENTINEL_MODEL_PROMPT",
            "raw_response": '{"say":"SENTINEL_MODEL_OUTPUT"}',
            "result": {
                "reasoning": "SENTINEL_PRIVATE_REASONING",
                "say": "SENTINEL_MODEL_OUTPUT",
            },
            "invalid_attempts": [{"reason": "invalid json"}],
            "api_key": "SENTINEL_LOG_API_KEY",
        },
    }
    with context.session_factory() as db:
        replay = db.get(GameReplayPayload, session_id)
        assert replay is not None
        replay.logs = [
            {
                "number": 1,
                "debate": [model_action],
                "duplicate_reference": model_action,
            }
        ]
        db.add_all(
            [
                LiveEventRecord(
                    run_id=run_id,
                    event_id=2,
                    session_id=session_id,
                    type="model_request_started",
                    round=1,
                    phase="vote",
                    actor="李四",
                    action="vote",
                    payload={
                        "request_id": event_only_request_id,
                        "model": "model-event-only",
                    },
                    created_at=created_at + timedelta(seconds=2),
                ),
                LiveEventRecord(
                    run_id=run_id,
                    event_id=3,
                    session_id=session_id,
                    type="model_request_failed",
                    round=1,
                    phase="vote",
                    actor="李四",
                    action="vote",
                    payload={
                        "request_id": event_only_request_id,
                        "model": "model-event-only",
                        "message": "SENTINEL_MODEL_FAILURE",
                    },
                    created_at=created_at + timedelta(seconds=3),
                ),
            ]
        )
        db.commit()

    _login(context, monkeypatch, role="viewer")
    forbidden = context.client.get(
        f"/api/v1/admin/games/{session_id}/model-requests"
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "admin_permission_denied"

    _login(context, monkeypatch, role="operator")
    list_response = context.client.get(
        f"/api/v1/admin/games/{session_id}/model-requests",
        headers={"X-Request-ID": "game-model-requests-1"},
    )
    assert list_response.status_code == 200, list_response.text
    payload = list_response.json()
    assert payload["session_id"] == session_id
    assert len(payload["items"]) == 2
    items = {item["request_id"]: item for item in payload["items"]}
    assert items[request_id] == {
        "request_id": request_id,
        "round_number": 1,
        "phase": None,
        "actor": "张三",
        "action": "debate",
        "model": "model-alpha",
        "status": "completed",
        "attempt_count": 2,
        "invalid_attempt_count": 1,
        "run_id": None,
        "event_id": None,
        "created_at": None,
    }
    assert items[event_only_request_id]["status"] == "failed"
    assert items[event_only_request_id]["model"] == "model-event-only"
    list_serialized = json.dumps(payload, ensure_ascii=False)
    assert "SENTINEL_MODEL_PROMPT" not in list_serialized
    assert "SENTINEL_MODEL_OUTPUT" not in list_serialized
    assert list_response.headers["cache-control"] == "no-store"
    assert list_response.headers["x-request-id"] == "game-model-requests-1"

    detail_response = context.client.get(
        f"/api/v1/admin/games/{session_id}/model-requests/{request_id}",
        headers={"X-Request-ID": "game-model-request-detail-1"},
    )
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["prompt"] == "SENTINEL_MODEL_PROMPT"
    assert detail["raw_response"] == '{"say":"SENTINEL_MODEL_OUTPUT"}'
    assert json.loads(detail["parsed_output"]) == {
        "reasoning": "SENTINEL_PRIVATE_REASONING",
        "say": "SENTINEL_MODEL_OUTPUT",
    }
    assert detail["raw_choice"] == "SENTINEL_RAW_CHOICE"
    assert "SENTINEL_LOG_API_KEY" not in json.dumps(detail, ensure_ascii=False)
    assert detail_response.headers["cache-control"] == "no-store"

    missing = context.client.get(
        f"/api/v1/admin/games/{session_id}/model-requests/req_missing_21"
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "admin_game_model_request_not_found"

    with context.session_factory() as db:
        audits = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.action.in_(
                        (
                            "admin.game.model_requests.list",
                            "admin.game.model_request.read",
                        )
                    )
                )
                .order_by(AuditEvent.created_at.asc())
            )
        )
    audit_by_action = {audit.action: audit for audit in audits}
    assert set(audit_by_action) == {
        "admin.game.model_requests.list",
        "admin.game.model_request.read",
    }
    assert audit_by_action["admin.game.model_requests.list"].after == {
        "request_count": 2
    }
    detail_audit = audit_by_action["admin.game.model_request.read"]
    assert detail_audit.resource_type == "game_model_request"
    assert detail_audit.resource_id == request_id
    assert detail_audit.after == {"session_id": session_id}


def test_quality_summary_is_safe_and_issues_require_explicit_debug_read(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 14, 9, tzinfo=UTC)
    session_id = "game_00000030"
    _seed_game(
        context,
        session_id=session_id,
        run_id="run_000000000030",
        created_at=created_at,
    )
    marker = "SENTINEL_PRIVATE_WOLF_PLAN"
    with context.session_factory() as db:
        db.add(
            GameQualityEvaluationRecord(
                id="quality_admin_safe_30",
                session_id=session_id,
                run_id="run_000000000030",
                evaluator_version="p3-v1",
                source_revision="3" * 64,
                status="completed",
                data_status="available",
                verdict="fail",
                safe_summary={
                    "schema_version": 1,
                    "source_coverage": {
                        "state": "complete",
                        "logs": "complete",
                        "events": "complete",
                        "voice": "complete",
                        "subtitles": "complete",
                        "pending_voice_count": 0,
                        "failed_voice_count": 0,
                        "private_text": marker,
                    },
                    "issue_counts": {"P0": 1, "P1": 0, "P2": 0},
                    "facts": {
                        "critical_opportunity_count": 4,
                        "critical_recorded_count": 3,
                        "critical_fact_write_rate": 0.75,
                        "prompt_expected_critical_count": 8,
                        "prompt_included_critical_count": 7,
                        "prompt_missing_critical_count": 1,
                        "critical_fact_prompt_coverage_rate": 0.875,
                        "deterministic_contradiction_count": 0,
                    },
                    "critical_actions": [
                        {
                            "schema_version": 1,
                            "action_id": "action_safe_30",
                            "round_number": 1,
                            "action": "vote",
                            "action_origin": "model_first_attempt",
                            "input_completeness": "rule_missing",
                            "action_legality": "legal_executed",
                            "reasoning_observation": "used_unspecified_rule",
                            "direct_impact": "vote_recorded",
                            "attribution": "model_judgment_and_rule_input_gap",
                            "clause_ids": [
                                "day.exile.weighted_plurality_and_runoff.v1"
                            ],
                            "coverage": {
                                "schema_version": 1,
                                "status": "missing",
                                "required_count": 1,
                                "included_count": 0,
                                "missing_count": 1,
                                "missing_clause_ids": [
                                    "day.exile.weighted_plurality_and_runoff.v1"
                                ],
                            },
                            "reasoning": marker,
                            "prompt": marker,
                            "private_choice": marker,
                        },
                        {
                            "schema_version": 1,
                            "action_id": "action_invalid_30",
                            "round_number": 1,
                            "action": "vote",
                            "action_origin": "private_model_choice",
                            "input_completeness": "complete",
                            "action_legality": "legal_executed",
                            "reasoning_observation": "not_assessed",
                            "direct_impact": "vote_recorded",
                            "attribution": "not_determined",
                            "clause_ids": [],
                            "coverage": {
                                "schema_version": 1,
                                "status": "unknown",
                                "required_count": 0,
                                "included_count": 0,
                                "missing_count": 0,
                                "missing_clause_ids": [],
                            },
                        },
                    ],
                    "safe_issues": [
                        {
                            "issue_id": "quality_0123456789abcdef01234567",
                            "code": "private_voice_materialized",
                            "severity": "P0",
                            "channel": "voice",
                            "round_number": 1,
                            "event_id": 7,
                            "utterance_id": "utterance_safe_30",
                            "first_detected_at": created_at.isoformat(),
                            "text": marker,
                            "payload": {"target": marker},
                        }
                    ],
                    "private_evidence": marker,
                },
                completed_at=created_at + timedelta(minutes=3),
            )
        )
        db.commit()

    _login(context, monkeypatch, role="viewer")
    detail = context.client.get(f"/api/v1/admin/games/{session_id}")
    summary = context.client.get(
        f"/api/v1/admin/games/{session_id}/quality-evaluation"
    )
    forbidden = context.client.get(
        f"/api/v1/admin/games/{session_id}/quality-evaluation/issues"
    )

    assert detail.status_code == 200, detail.text
    assert summary.status_code == 200, summary.text
    quality = detail.json()["quality_evaluation"]
    assert quality["verdict"] == "fail"
    assert quality["source_revision"] == "3" * 64
    assert quality["latest_successful_result"] == {
        "evaluator_version": "p3-v1",
        "source_revision": "3" * 64,
        "completed_at": (created_at + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
    }
    assert quality["issue_counts"] == {"P0": 1, "P1": 0, "P2": 0}
    assert quality["facts"]["critical_fact_write_rate"] == 0.75
    assert quality["critical_actions"] == [
        {
            "schema_version": 1,
            "action_id": "action_safe_30",
            "round_number": 1,
            "action": "vote",
            "action_origin": "model_first_attempt",
            "input_completeness": "rule_missing",
            "action_legality": "legal_executed",
            "reasoning_observation": "used_unspecified_rule",
            "direct_impact": "vote_recorded",
            "attribution": "model_judgment_and_rule_input_gap",
            "clause_ids": ["day.exile.weighted_plurality_and_runoff.v1"],
            "coverage": {
                "schema_version": 1,
                "status": "missing",
                "required_count": 1,
                "included_count": 0,
                "missing_count": 1,
                "missing_clause_ids": [
                    "day.exile.weighted_plurality_and_runoff.v1"
                ],
            },
        }
    ]
    assert summary.json()["quality_evaluation"] == quality
    assert forbidden.status_code == 403
    assert "safe_issues" not in detail.text
    assert marker not in detail.text
    assert marker not in summary.text

    _login(context, monkeypatch, role="operator")
    issues = context.client.get(
        f"/api/v1/admin/games/{session_id}/quality-evaluation/issues",
        headers={"X-Request-ID": "quality-issues-30"},
    )

    assert issues.status_code == 200, issues.text
    assert issues.json()["items"] == [
        {
            "issue_id": "quality_0123456789abcdef01234567",
            "code": "private_voice_materialized",
            "severity": "P0",
            "channel": "voice",
            "round_number": 1,
            "event_id": 7,
            "utterance_id": "utterance_safe_30",
            "first_detected_at": created_at.isoformat().replace("+00:00", "Z"),
        }
    ]
    assert marker not in issues.text
    assert "text" not in issues.json()["items"][0]
    with context.session_factory() as db:
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.game.quality_issues.read"
            )
        )
    assert audit is not None
    assert audit.after == {
        "evaluation_id": "quality_admin_safe_30",
        "issue_count": 1,
    }


def test_quality_summary_bounds_critical_action_cards() -> None:
    completed_at = datetime(2026, 7, 14, 9, 3, tzinfo=UTC)
    cards = [
        {
            "schema_version": 1,
            "action_id": f"action_bounded_{index}",
            "round_number": 1,
            "action": "vote",
            "action_origin": "model_first_attempt",
            "input_completeness": "complete",
            "action_legality": "legal_executed",
            "reasoning_observation": "not_assessed",
            "direct_impact": "vote_recorded",
            "attribution": "not_determined",
            "clause_ids": [],
            "coverage": {
                "schema_version": 1,
                "status": "unknown",
                "required_count": 0,
                "included_count": 0,
                "missing_count": 0,
                "missing_clause_ids": [],
            },
        }
        for index in range(70)
    ]
    record = GameQualityEvaluationRecord(
        id="quality_bounded_actions",
        session_id="game_bounded_actions",
        run_id=None,
        evaluator_version="p3-v1",
        source_revision="b" * 64,
        status="completed",
        data_status="available",
        verdict="pass",
        safe_summary={"critical_actions": cards},
        attempt_count=1,
        completed_at=completed_at,
    )

    summary = build_admin_quality_summary(record, terminal=True)

    assert len(summary["critical_actions"]) == 64
    assert summary["critical_actions"][0]["action_id"] == "action_bounded_0"
    assert summary["critical_actions"][-1]["action_id"] == "action_bounded_63"
    AdminGameQualityEvaluationSummary.model_validate(summary)
    assert build_admin_quality_summary(record, terminal=False)["critical_actions"] == []
    record.data_status = "legacy"
    assert build_admin_quality_summary(record, terminal=True)["critical_actions"] == []


@pytest.mark.parametrize(
    "invalid_revision",
    ["a" * 63, "A" * 64, "g" * 64],
)
def test_quality_summary_rejects_non_sha256_source_revisions(
    invalid_revision: str,
) -> None:
    completed_at = datetime(2026, 7, 14, 9, 3, tzinfo=UTC)
    record = GameQualityEvaluationRecord(
        id="quality_invalid_revision",
        session_id="game_invalid_revision",
        run_id=None,
        evaluator_version="p3-v1",
        source_revision=invalid_revision,
        status="completed",
        data_status="available",
        verdict="pass",
        safe_summary={},
        attempt_count=0,
        completed_at=completed_at,
    )

    summary = build_admin_quality_summary(
        record,
        terminal=True,
        latest_successful_record=record,
    )

    assert summary["source_revision"] is None
    assert summary["latest_successful_result"] is None
    invalid_summary = {**summary, "source_revision": invalid_revision}
    with pytest.raises(ValidationError):
        AdminGameQualityEvaluationSummary.model_validate(invalid_summary)
    with pytest.raises(ValidationError):
        AdminQualityLatestSuccessfulResult(
            evaluator_version="p3-v1",
            source_revision=invalid_revision,
            completed_at=completed_at,
        )


@pytest.mark.parametrize(
    ("stored_status", "admin_status"),
    [("pending", "queued"), ("processing", "running")],
)
def test_quality_summary_maps_internal_active_status_for_admin_api(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
    stored_status: str,
    admin_status: str,
) -> None:
    created_at = datetime(2026, 7, 14, 9, tzinfo=UTC)
    session_id = "game_00000032"
    _seed_game(
        context,
        session_id=session_id,
        run_id="run_000000000032",
        created_at=created_at,
    )
    with context.session_factory() as db:
        db.add(
            GameQualityEvaluationRecord(
                id=f"quality_admin_{stored_status}_32",
                session_id=session_id,
                run_id="run_000000000032",
                evaluator_version="p3-v1",
                source_revision="4" * 64,
                status=stored_status,
                data_status="collecting",
                verdict="unavailable",
                safe_summary={},
                created_at=created_at,
                started_at=created_at if stored_status == "processing" else None,
            )
        )
        db.commit()
    _login(context, monkeypatch, role="viewer")

    response = context.client.get(f"/api/v1/admin/games/{session_id}/quality-evaluation")

    assert response.status_code == 200, response.text
    assert response.json()["quality_evaluation"]["evaluation_status"] == admin_status
    assert response.json()["quality_evaluation"]["critical_actions"] == []
    with context.session_factory() as db:
        record = db.get(
            GameQualityEvaluationRecord,
            f"quality_admin_{stored_status}_32",
        )
    assert record is not None
    assert record.status == stored_status


def test_quality_summary_keeps_latest_success_when_current_attempt_failed(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 14, 9, tzinfo=UTC)
    session_id = "game_00000033"
    run_id = "run_000000000033"
    successful_revision = "a" * 64
    failed_revision = "b" * 64
    successful_at = created_at + timedelta(minutes=2)
    _seed_game(
        context,
        session_id=session_id,
        run_id=run_id,
        created_at=created_at,
    )
    with context.session_factory() as db:
        db.add_all(
            [
                GameQualityEvaluationRecord(
                    id="quality_admin_success_33",
                    session_id=session_id,
                    run_id=run_id,
                    evaluator_version="p3-v1",
                    source_revision=successful_revision,
                    status="completed",
                    data_status="available",
                    verdict="pass",
                    safe_summary={},
                    created_at=created_at,
                    completed_at=successful_at,
                ),
                GameQualityEvaluationRecord(
                    id="quality_admin_failed_33",
                    session_id=session_id,
                    run_id=run_id,
                    evaluator_version="p3-v1",
                    source_revision=failed_revision,
                    status="failed",
                    data_status="unavailable",
                    verdict="unavailable",
                    safe_summary={},
                    created_at=created_at + timedelta(minutes=3),
                    completed_at=created_at + timedelta(minutes=4),
                    last_error_code="evaluation_failed",
                ),
            ]
        )
        db.commit()
    _login(context, monkeypatch, role="viewer")

    response = context.client.get(f"/api/v1/admin/games/{session_id}/quality-evaluation")

    assert response.status_code == 200, response.text
    quality = response.json()["quality_evaluation"]
    assert quality["evaluation_status"] == "failed"
    assert quality["source_revision"] == failed_revision
    assert quality["latest_successful_result"] == {
        "evaluator_version": "p3-v1",
        "source_revision": successful_revision,
        "completed_at": successful_at.isoformat().replace("+00:00", "Z"),
    }


def test_quality_retry_requires_csrf_and_requeues_only_eligible_results(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 14, 10, tzinfo=UTC)
    session_id = "game_00000031"
    _seed_game(
        context,
        session_id=session_id,
        run_id="run_000000000031",
        created_at=created_at,
    )
    with context.session_factory() as db:
        source_revision = build_database_quality_bundle(
            db, session_id=session_id
        ).source_revision
        db.add(
            GameQualityEvaluationRecord(
                id="quality_admin_retry_31",
                session_id=session_id,
                run_id="run_000000000031",
                evaluator_version="p3-v1",
                source_revision=source_revision,
                status="failed",
                data_status="unavailable",
                verdict="unavailable",
                safe_summary={"unsafe": "SENTINEL_RETRY_PRIVATE"},
                attempt_count=3,
                last_error_code="evaluation_failed",
                completed_at=created_at + timedelta(minutes=3),
            )
        )
        db.commit()
    login = _login(context, monkeypatch, role="operator")

    missing_csrf = context.client.post(
        f"/api/v1/admin/games/{session_id}/quality-evaluation/retry"
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "admin_csrf_invalid"

    response = context.client.post(
        f"/api/v1/admin/games/{session_id}/quality-evaluation/retry",
        headers={"X-CSRF-Token": login["csrf_token"]},
    )
    assert response.status_code == 202, response.text
    assert response.json() == {
        "session_id": session_id,
        "evaluation_id": "quality_admin_retry_31",
        "status": "pending",
    }

    duplicate = context.client.post(
        f"/api/v1/admin/games/{session_id}/quality-evaluation/retry",
        headers={"X-CSRF-Token": login["csrf_token"]},
    )
    assert duplicate.status_code == 409
    with context.session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, "quality_admin_retry_31")
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.game.quality_evaluation.retry"
            )
        )
    assert record is not None
    assert record.status == "pending"
    assert record.safe_summary == {}
    assert record.attempt_count == 0
    assert record.last_error_code is None
    assert audit is not None
    assert audit.after == {
        "evaluation_id": "quality_admin_retry_31",
        "status": "pending",
    }


def test_partial_quality_retry_keeps_latest_success_while_job_is_active(
    context: AdminGamesContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 14, 11, tzinfo=UTC)
    completed_at = created_at + timedelta(minutes=3)
    session_id = "game_00000034"
    run_id = "run_000000000034"
    evaluation_id = "quality_admin_retry_34"
    _seed_game(
        context,
        session_id=session_id,
        run_id=run_id,
        created_at=created_at,
    )
    with context.session_factory() as db:
        source_revision = build_database_quality_bundle(db, session_id=session_id).source_revision
        db.add(
            GameQualityEvaluationRecord(
                id=evaluation_id,
                session_id=session_id,
                run_id=run_id,
                evaluator_version="p3-v1",
                source_revision=source_revision,
                status="completed",
                data_status="partial",
                verdict="warn",
                safe_summary={"schema_version": 1},
                attempt_count=1,
                completed_at=completed_at,
            )
        )
        db.commit()
    login = _login(context, monkeypatch, role="operator")

    retried = context.client.post(
        f"/api/v1/admin/games/{session_id}/quality-evaluation/retry",
        headers={"X-CSRF-Token": login["csrf_token"]},
    )

    assert retried.status_code == 202, retried.text
    assert retried.json() == {
        "session_id": session_id,
        "evaluation_id": evaluation_id,
        "status": "pending",
    }
    expected_success = {
        "evaluator_version": "p3-v1",
        "source_revision": source_revision,
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
    }
    queued = context.client.get(f"/api/v1/admin/games/{session_id}/quality-evaluation")
    assert queued.status_code == 200, queued.text
    assert queued.json()["quality_evaluation"]["evaluation_status"] == "queued"
    assert queued.json()["quality_evaluation"]["latest_successful_result"] == expected_success
    assert "_previous_successful_result" not in queued.text

    with context.session_factory() as db:
        record = db.get(GameQualityEvaluationRecord, evaluation_id)
        assert record is not None
        assert record.safe_summary == {
            "_previous_successful_result": {
                "evaluator_version": "p3-v1",
                "source_revision": source_revision,
                "completed_at": completed_at.isoformat(),
            }
        }
        record.status = "processing"
        record.worker_id = "quality-worker-34"
        record.lease_expires_at = created_at + timedelta(hours=1)
        db.commit()

    running = context.client.get(f"/api/v1/admin/games/{session_id}/quality-evaluation")
    assert running.status_code == 200, running.text
    assert running.json()["quality_evaluation"]["evaluation_status"] == "running"
    assert running.json()["quality_evaluation"]["latest_successful_result"] == expected_success


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
    assert any(
        constraint.name == "uq_live_runs_session_attempt_no"
        for constraint in LiveRunRecord.__table__.constraints
    )

    quality_indexes = {index.name: index for index in GameQualityEvaluationRecord.__table__.indexes}
    latest_quality_index = quality_indexes["ix_game_quality_evaluations_session_created"]
    assert len(latest_quality_index.expressions) == 3
    assert latest_quality_index.expressions[0].name == "session_id"
    assert str(latest_quality_index.expressions[1]).endswith("created_at DESC")
    assert str(latest_quality_index.expressions[2]).endswith("id DESC")
    assert str(
        quality_indexes["ix_game_quality_evaluations_status_completed"].expressions[1]
    ).endswith("completed_at DESC")
    assert str(
        quality_indexes["ix_game_quality_evaluations_verdict_completed"].expressions[1]
    ).endswith("completed_at DESC")

    voice_job_indexes = {
        index.name: index for index in VoiceMaterializationJobRecord.__table__.indexes
    }
    audience_status_index = voice_job_indexes["ix_voice_materialization_jobs_audience_status"]
    assert [expression.name for expression in audience_status_index.expressions] == [
        "audience",
        "status",
    ]


def test_admin_quality_query_plans_use_bounded_cohort_indexes(
    context: AdminGamesContext,
) -> None:
    with context.engine.connect() as connection:
        latest_plan = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT id FROM game_quality_evaluations "
            "WHERE session_id = 'game_plan' "
            "ORDER BY CASE WHEN status IN ('pending', 'processing') "
            "THEN 0 ELSE 1 END, created_at DESC, id DESC LIMIT 1"
        ).all()
        overview_plan = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT id FROM game_quality_evaluations "
            "WHERE status = 'completed' AND completed_at >= '2026-07-07' "
            "ORDER BY completed_at DESC LIMIT 5000"
        ).all()

    assert "ix_game_quality_evaluations_session_created" in " ".join(
        str(row) for row in latest_plan
    )
    assert "ix_game_quality_evaluations_status_completed" in " ".join(
        str(row) for row in overview_plan
    )


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
