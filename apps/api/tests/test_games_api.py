import base64
import copy
import json
import logging
import os
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import StaticPool

from app.api.routes import games as games_routes
from app.api.routes.games import (
    CreatePlayerConfigRequest,
    SessionLiveStore,
    SessionVoiceStore,
    _run_game_in_background,
    complete_player_configs_from_library,
    get_live_registry,
    get_replay_store,
    list_available_player_profiles,
    normalize_player_config_requests,
)
from app.api.public.dependencies import public_problem
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceUtteranceRecord,
)
from app.models.model_configuration import ModelConfigurationRecord
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.rule_sets.snapshots import resolve_rule_set_snapshot
from app.rule_sets.service import (
    archive_rule_set,
    publish_rule_set,
    resolve_published_rule_set,
    update_rule_set_draft,
)
from app.rule_sets.telemetry import (
    _reset_rule_set_metrics_for_tests,
    render_rule_set_metrics,
)
from app.rule_sets.types import CompiledRuleSet
from app.rule_sets.validation import normalize_rule_set_config
from app.werewolf.checkpoint import ResumeCheckpointError, resolved_rule_set_from_checkpoint
from app.werewolf.live import LiveRunRegistry
from app.werewolf.player_presets import default_personality_text
from app.werewolf.providers import ARK_AGENT_PLAN_MODELS
from app.werewolf.replay import DatabaseReplayStore
from app.werewolf.voice import VoiceUtterance
from app.werewolf.voice_store import DatabaseVoiceStore
from tests.rule_set_fixtures import (
    OFFICIAL_RULE_SET_SEEDS,
    complete_resume_checkpoint,
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
            parameter_values={"thinking": "default"},
            source_details={"source": "test"},
        )
    )

client = TestClient(app)


class BrokenSession:
    def get(self, *_args: object) -> None:
        raise OperationalError("select", {}, Exception("database unavailable"))

    def query(self, *_args: object) -> None:
        raise OperationalError("select", {}, Exception("database unavailable"))

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def override_broken_db() -> Generator[BrokenSession, None, None]:
    yield BrokenSession()


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
    monkeypatch.setattr(games_routes, "runtime_worker_is_alive", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("app.api.routes.games.SessionLocal", TestingSessionLocal)
    with TestingSessionLocal() as session:
        session.query(VoiceAudioChunkRecord).delete()
        session.query(VoiceUtteranceRecord).delete()
        session.query(LiveEventRecord).delete()
        session.query(LiveRunRecord).delete()
        session.query(GameReplayPayload).delete()
        session.query(GameSessionRecord).delete()
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
        session.query(VoiceAudioChunkRecord).delete()
        session.query(VoiceUtteranceRecord).delete()
        session.query(LiveEventRecord).delete()
        session.query(LiveRunRecord).delete()
        session.query(GameReplayPayload).delete()
        session.query(GameSessionRecord).delete()
        session.query(RuleSetRevisionRecord).delete()
        session.query(RuleSetRecord).delete()
        session.query(VirtualPlayerProfile).delete()
        session.query(PlayerAvatarAsset).delete()
        session.query(User).delete()
        session.commit()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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


def override_replay_store() -> None:
    def _override() -> Generator[DatabaseReplayStore, None, None]:
        db = TestingSessionLocal()
        try:
            yield DatabaseReplayStore(db)
        finally:
            db.close()

    app.dependency_overrides[get_replay_store] = _override


def override_live_registry(registry: LiveRunRegistry) -> None:
    app.dependency_overrides[get_live_registry] = lambda: registry


def clear_overrides() -> None:
    app.dependency_overrides.clear()


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


def store_incomplete_live_run(
    *,
    session_id: str,
    run_id: str = "run_incomplete",
) -> None:
    stale_at = datetime.now(tz=UTC) - timedelta(minutes=5)
    with TestingSessionLocal() as session:
        session.add(
            LiveRunRecord(
                run_id=run_id,
                session_id=session_id,
                status="queued",
                villager_model="deepseek-chat",
                werewolf_model="deepseek-chat",
                seed=21,
                max_rounds=8,
                rule_set_id="starter_6",
                rule_set={"id": "starter_6"},
                created_at=stale_at,
                worker_id="worker-incomplete-owner",
                worker_heartbeat_at=stale_at,
                lease_expires_at=stale_at,
                fence_token=4,
                control_version=2,
            )
        )
        session.commit()


class ImmediateThread:
    def __init__(self, *, target, kwargs, daemon):
        self.target = target
        self.kwargs = kwargs
        self.daemon = daemon

    def start(self) -> None:
        self.target(**self.kwargs)


class RecordingSessionLiveStore(SessionLiveStore):
    def __init__(self) -> None:
        super().__init__(TestingSessionLocal)
        self.saved_runs: list[tuple[str, str]] = []
        self.events: list[tuple[str, int, str]] = []

    def save_new_run(self, run) -> None:
        event = run.events[0]
        self.saved_runs.append((run.run_id, run.status))
        self.events.append((event.run_id, event.id, event.type))
        super().save_new_run(run)

    def save_run(self, run) -> None:
        self.saved_runs.append((run.run_id, run.status))
        super().save_run(run)

    def append_event(self, event, **fence) -> None:
        self.events.append((event.run_id, event.id, event.type))
        super().append_event(event, **fence)


def test_session_voice_store_updates_subtitle_timings() -> None:
    store = SessionVoiceStore(
        session_id="game_1200abcd",
        session_factory=TestingSessionLocal,
    )
    utterance = VoiceUtterance(
        utterance_id="voice_session_subtitles",
        run_id="run_session_subtitles",
        source_event_id=1,
        request_id="req-session-subtitles",
        speaker_kind="judge",
        speaker_name="法官",
        speaker="judge",
        text="夜晚降临。",
        action="phase_start",
    )

    store.upsert_utterance(
        utterance,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.update_subtitle_timings(
        "voice_session_subtitles",
        subtitle_timings=[{"text": "夜晚降临。", "start_ms": 0, "end_ms": 800}],
    )

    with TestingSessionLocal() as session:
        loaded = DatabaseVoiceStore(session, session_id="game_1200abcd").load_utterance(
            "voice_session_subtitles"
        )

    assert loaded is not None
    assert loaded["subtitle_timings"] == [{"text": "夜晚降临。", "start_ms": 0, "end_ms": 800}]


def sample_state(session_id: str, *, winner: str = "狼人阵营", error: str = "") -> dict:
    return {
        "session_id": session_id,
        "players": [
            {"name": "张三", "role": "狼人", "model": "deepseek-chat", "observations": []},
            {"name": "李四", "role": "村民", "model": "deepseek-chat", "observations": []},
        ],
        "rounds": [
            {
                "number": 1,
                "players": ["张三", "李四"],
                "eliminated": "李四",
                "protected": None,
                "investigated": "张三",
                "exiled": None,
                "debate": [],
                "bids": [{"张三": 3}],
                "votes": [{"张三": "李四"}],
                "summaries": {"张三": "我会隐藏身份。"},
                "success": True,
            }
        ],
        "winner": winner,
        "error_message": error,
    }


def sample_logs() -> list[dict]:
    return [
        {
            "number": 1,
            "eliminate": {
                "actor": "张三",
                "action": "remove",
                "options": ["李四"],
                "choice": "李四",
                "lm_log": {
                    "prompt": "请选择今晚击杀对象。",
                    "raw_response": '{"choice":"李四"}',
                    "parsed": {"choice": "李四"},
                },
            },
            "protect": None,
            "investigate": None,
            "bid": [],
            "debate": [],
            "votes": [],
            "summaries": [],
        }
    ]


def sample_checkpoint(
    session_id: str,
    *,
    run_params: dict | None = None,
    state: dict | None = None,
    logs_before_round: list[dict] | None = None,
) -> dict:
    source_run_params = run_params or {
        "villager_model": "deepseek-chat",
        "werewolf_model": "deepseek-chat",
        "seed": 21,
        "max_rounds": 8,
        "rule_set_id": "starter_6",
        "player_configs": [],
    }
    rule_set_id = source_run_params.get("rule_set_id", "starter_6")
    compiled = managed_official_compiled_rule_set(str(rule_set_id))
    checkpoint = complete_resume_checkpoint(session_id, compiled)
    for name in (
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "player_configs",
    ):
        checkpoint["run_params"][name] = copy.deepcopy(source_run_params.get(name))
    checkpoint_state = copy.deepcopy(state or sample_state(session_id, winner="", error=""))
    checkpoint_state["rule_set"] = copy.deepcopy(compiled.snapshot)
    checkpoint["state_at_round_start"] = checkpoint_state
    checkpoint["logs_before_round"] = copy.deepcopy(
        logs_before_round if logs_before_round is not None else []
    )
    checkpoint["active_players"] = ["张三", "李四"]
    return checkpoint


def store_game_session(
    session_id: str,
    *,
    state: dict | None = None,
    logs: list[dict] | None = None,
    checkpoint: dict | None = None,
) -> None:
    with TestingSessionLocal() as session:
        store = DatabaseReplayStore(session)
        if checkpoint is not None:
            store.save_resume_checkpoint(session_id, checkpoint)
        store.save_game_payload(
            state=state or sample_state(session_id),
            logs=logs if logs is not None else sample_logs(),
        )
        if checkpoint is not None:
            store.save_resume_checkpoint(session_id, checkpoint)


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


@pytest.mark.parametrize(
    "reason",
    [
        "unsupported_schema",
        "invalid_structure",
        "invalid_rule_snapshot",
        "rule_snapshot_mismatch",
        "rule_metadata_mismatch",
    ],
)
def test_rule_metric_checkpoint_resolver_records_each_failure_once(reason: str) -> None:
    checkpoint = sample_checkpoint("game_1200abcd")
    if reason == "unsupported_schema":
        checkpoint["schema_version"] = 4
    elif reason == "invalid_structure":
        checkpoint.pop("schema_version")
    elif reason == "invalid_rule_snapshot":
        checkpoint["state_at_round_start"]["rule_set"].pop("name")
    elif reason == "rule_snapshot_mismatch":
        other = managed_official_compiled_rule_set("classic_8")
        checkpoint["state_at_round_start"]["rule_set"] = copy.deepcopy(other.snapshot)
    else:
        checkpoint["run_params"]["content_hash"] = "0" * 64

    with pytest.raises(ResumeCheckpointError) as caught:
        resolved_rule_set_from_checkpoint(checkpoint)

    assert caught.value.reason == reason
    assert f'werewolf_rule_checkpoint_failures_total{{reason="{reason}"}} 1' in _rule_metrics()


def test_checkpoint_error_construction_has_no_telemetry_side_effect() -> None:
    error = ResumeCheckpointError("invalid_structure")

    assert error.reason == "invalid_structure"
    assert (
        'werewolf_rule_checkpoint_failures_total{reason="invalid_structure"} 0' in _rule_metrics()
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
        "app.api.routes.games.list_published_rule_sets",
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
        "app.api.routes.games.list_published_rule_sets",
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
        games_routes._STATIC_RULE_REVISIONS,
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


def test_list_model_options_returns_configured_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.setenv("ARK_AGENT_PLAN_API_KEY", "agent-plan-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_MODEL", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_MODELS", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setenv("DASHSCOPE_MODEL", "qwen-test")

    response = client.get("/api/v1/games/model-options")

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            *[
                {
                    "id": model,
                    "provider": "agent_plan",
                    "model_id": model,
                    "label": f"火山方舟 Agent Plan · {model}",
                }
                for model in ARK_AGENT_PLAN_MODELS
            ],
            {
                "id": "deepseek-test",
                "provider": "deepseek",
                "model_id": "deepseek-test",
                "label": "DeepSeek · deepseek-test",
            },
            {
                "id": "qwen-test",
                "provider": "qwen",
                "model_id": "qwen-test",
                "label": "Qwen · qwen-test",
            },
        ]
    }


def test_list_model_options_prefers_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEREWOLF_DEFAULT_MODEL", "minimax-m3")
    monkeypatch.setenv("ARK_AGENT_PLAN_API_KEY", "agent-plan-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_MODEL", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_MODELS", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-test")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    response = client.get("/api/v1/games/model-options")

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {
                "id": "minimax-m3",
                "provider": "agent_plan",
                "model_id": "minimax-m3",
                "label": "火山方舟 Agent Plan · minimax-m3",
            },
            *[
                {
                    "id": model,
                    "provider": "agent_plan",
                    "model_id": model,
                    "label": f"火山方舟 Agent Plan · {model}",
                }
                for model in ARK_AGENT_PLAN_MODELS
                if model != "minimax-m3"
            ],
            {
                "id": "deepseek-test",
                "provider": "deepseek",
                "model_id": "deepseek-test",
                "label": "DeepSeek · deepseek-test",
            },
        ]
    }


def test_list_model_options_falls_back_to_default_without_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    response = client.get("/api/v1/games/model-options")

    assert response.status_code == 200
    assert response.json() == {"models": []}


def test_create_game_run_accepts_rule_set_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(6)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "starter_6", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["rule_set"]["id"] == "starter_6"
    assert "rule_set_id" not in captured[0]
    compiled = captured[0]["compiled"]
    assert isinstance(compiled, CompiledRuleSet)
    assert compiled.rule_set.id == "starter_6"


def test_create_game_run_uses_the_single_supported_liveness_experience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games._run_game_in_background", lambda **_: None)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)
    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201, response.text
    payload = response.json()
    with TestingSessionLocal() as session:
        saved = session.get(LiveRunRecord, payload["run_id"])
    assert saved is not None
    assert saved.liveness_experience_revision == "liveness-v1"
    assert saved.liveness_experience_snapshot["feature_modes"] == {
        "style_gate": "async_observe",
        "actor_mind": "read",
        "sentence_stream": "committed_segments_v2",
        "affect_delivery": "on",
        "tts_prefetch_depth": 1,
        "voice_preempt": "deterministic",
    }


def test_create_game_run_refuses_to_start_when_voice_persistence_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    monkeypatch.setattr(settings, "ark_tts_enabled", True)
    monkeypatch.setattr(games_routes, "runtime_worker_is_alive", lambda *_args, **_kwargs: False)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "live_voice_materializer_unavailable"
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        assert session.query(LiveRunRecord).count() == 0


def test_resume_game_run_refuses_to_continue_when_voice_persistence_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ark_tts_enabled", True)
    monkeypatch.setattr(games_routes, "runtime_worker_is_alive", lambda *_args, **_kwargs: False)

    response = client.post("/api/v1/games/game_1200abcd/resume")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "live_voice_materializer_unavailable"


def test_create_game_run_pins_expected_revision_and_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []
    lock_flags: list[bool] = []
    resolved: list[CompiledRuleSet] = []
    real_resolver = games_routes.resolve_published_rule_set

    def capturing_resolver(
        db: Session,
        rule_set_id: str,
        *,
        expected_revision_id: str | None,
        for_update: bool = False,
    ) -> CompiledRuleSet:
        lock_flags.append(for_update)
        compiled = real_resolver(
            db,
            rule_set_id,
            expected_revision_id=expected_revision_id,
            for_update=for_update,
        )
        resolved.append(compiled)
        return compiled

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(games_routes, "resolve_published_rule_set", capturing_resolver)
    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)
    revision_id = "e9fa678e-9b18-5079-91d2-f74835364fb6"

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": revision_id,
                "seed": 21,
                "max_rounds": 1,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["rule_set_revision_id"] == revision_id
    assert payload["rule_set_revision_no"] == 1
    assert payload["rule_set_content_hash"] == payload["rule_set"]["content_hash"]
    assert payload["rule_set"]["revision_id"] == revision_id
    assert len(captured) == 1
    compiled = captured[0]["compiled"]
    assert isinstance(compiled, CompiledRuleSet)
    assert compiled is resolved[0]
    assert compiled.snapshot == payload["rule_set"]
    assert compiled.content_hash == payload["rule_set_content_hash"]
    assert captured[0]["run_id"] == payload["run_id"]
    assert "rule_set_id" not in captured[0]
    assert lock_flags == [True]

    with TestingSessionLocal() as session:
        saved_run = session.get(LiveRunRecord, payload["run_id"])
        saved_events = (
            session.query(LiveEventRecord)
            .filter(LiveEventRecord.run_id == payload["run_id"])
            .order_by(LiveEventRecord.event_id.asc())
            .all()
        )
    assert saved_run is not None
    assert saved_run.rule_set_revision_id == compiled.revision_id
    assert saved_run.rule_set_revision_no == compiled.revision_no
    assert saved_run.rule_set_content_hash == compiled.content_hash
    assert saved_run.rule_set == compiled.snapshot
    assert [event.type for event in saved_events] == ["run_created"]
    assert saved_events[0].payload["rule_set"] == compiled.snapshot


def test_create_game_run_static_mode_pins_the_same_official_managed_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(6)
    monkeypatch.setattr(settings, "rule_set_catalog_source", "static", raising=False)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def reject_database_resolver(*_args: object, **_kwargs: object) -> CompiledRuleSet:
        raise AssertionError("static create must not resolve through the database catalog")

    class DeferredThread:
        def __init__(self, *, target, kwargs, daemon) -> None:
            del target, daemon
            captured.append(kwargs)

        def start(self) -> None:
            pass

    monkeypatch.setattr(games_routes, "resolve_published_rule_set", reject_database_resolver)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", DeferredThread)
    seed = next(item for item in OFFICIAL_RULE_SET_SEEDS if item["id"] == "starter_6")

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "starter_6",
                "expected_rule_revision_id": seed["revision_id"],
                "seed": 21,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["rule_set_revision_id"] == seed["revision_id"]
    assert payload["rule_set_content_hash"] == seed["content_hash"]
    assert payload["rule_set"]["description"] == ("更短的官方入门局,适合快速观察模型策略。")
    assert len(captured) == 1
    compiled = captured[0]["compiled"]
    assert isinstance(compiled, CompiledRuleSet)
    assert compiled.snapshot == payload["rule_set"]


def test_create_game_run_rejects_revision_changed_with_current_catalog_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    thread_constructions: list[object] = []

    class NeverThread:
        def __init__(self, **kwargs: object) -> None:
            thread_constructions.append(kwargs)

        def start(self) -> None:
            raise AssertionError("revision conflicts must not start a worker")

    monkeypatch.setattr("app.api.routes.games.threading.Thread", NeverThread)

    try:
        current_response = client.get("/api/v1/games/rule-sets")
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "00000000-0000-0000-0000-000000000000",
                "seed": 21,
            },
        )
    finally:
        clear_overrides()

    assert current_response.status_code == 200
    current = next(
        item for item in current_response.json()["rule_sets"] if item["id"] == "classic_8"
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "rule_revision_changed",
        "message": "The selected rule revision has changed.",
        "request_id": response.headers["X-Request-ID"],
        "current_rule_set": current,
    }
    assert thread_constructions == []
    with TestingSessionLocal() as session:
        assert session.query(LiveRunRecord).count() == 0
        assert session.query(LiveEventRecord).count() == 0
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        metrics = render_rule_set_metrics(session)
    assert (
        'werewolf_rule_create_conflicts_total{rule_set_id="classic_8",revision_no="1"} 1' in metrics
    )


def test_create_game_run_rejects_archived_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    with TestingSessionLocal() as session:
        classic = session.get(RuleSetRecord, "classic_8")
        social = session.get(RuleSetRecord, "social_8")
        assert classic is not None
        assert social is not None
        classic.is_default = False
        classic.status = "archived"
        classic.archived_at = datetime.now(UTC)
        session.flush()
        social.is_default = True
        session.commit()

    registry = LiveRunRegistry()
    override_live_registry(registry)
    thread_constructions: list[object] = []

    class NeverThread:
        def __init__(self, **kwargs: object) -> None:
            thread_constructions.append(kwargs)

        def start(self) -> None:
            raise AssertionError("archived rules must not start a worker")

    monkeypatch.setattr("app.api.routes.games.threading.Thread", NeverThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rule_set_unavailable"
    assert "current_rule_set" not in response.json()["detail"]
    assert thread_constructions == []
    with TestingSessionLocal() as session:
        assert session.query(LiveRunRecord).count() == 0
        assert session.query(LiveEventRecord).count() == 0
    assert registry._runs == {}


def test_create_game_run_without_expected_revision_records_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)

    class DeferredThread:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr("app.api.routes.games.threading.Thread", DeferredThread)

    try:
        with caplog.at_level(logging.INFO, logger="app.api.routes.games"):
            response = client.post(
                "/api/v1/games/runs",
                json={"rule_set_id": "classic_8", "seed": 21},
            )
    finally:
        clear_overrides()

    assert response.status_code == 201, response.text
    compatibility_records = [
        record
        for record in caplog.records
        if getattr(record, "event_code", None) == "legacy_rule_create"
    ]
    assert len(compatibility_records) == 1
    record = compatibility_records[0]
    assert record.rule_set_id == "classic_8"
    assert record.rule_set_revision_no == 1
    assert record.rule_set_schema_version == 1
    assert record.rule_set_content_hash_prefix == response.json()["rule_set_content_hash"][:12]
    assert "包含狼人" not in record.getMessage()
    assert response.json()["rule_set"] not in record.__dict__.values()
    with TestingSessionLocal() as session:
        metrics = render_rule_set_metrics(session)
    assert (
        'werewolf_rule_legacy_creates_total{rule_set_id="classic_8",revision_no="1"} 1' in metrics
    )


def test_background_thread_starts_only_after_run_transaction_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    db = TestingSessionLocal()
    order: list[str] = []
    observations: dict[str, object] = {}
    original_commit = db.commit

    def tracking_commit() -> None:
        assert registry._runs == {}
        order.append("commit")
        original_commit()
        assert registry._runs == {}

    monkeypatch.setattr(db, "commit", tracking_commit)

    def override_tracking_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_tracking_db

    class TrackingThread:
        def __init__(self, *, target, kwargs, daemon) -> None:
            del target, daemon
            order.append("thread_constructed")
            run_id = str(kwargs["run_id"])
            observations["attached"] = registry.try_get_run(run_id) is not None
            with TestingSessionLocal() as observer:
                observations["run_committed"] = observer.get(LiveRunRecord, run_id) is not None
                observations["event_committed"] = (
                    observer.query(LiveEventRecord).filter(LiveEventRecord.run_id == run_id).count()
                    == 1
                )

        def start(self) -> None:
            order.append("thread_started")

    monkeypatch.setattr("app.api.routes.games.threading.Thread", TrackingThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        db.close()
        clear_overrides()

    assert response.status_code == 201, response.text
    assert order == ["commit", "thread_constructed", "thread_started"]
    assert observations == {
        "attached": True,
        "run_committed": True,
        "event_committed": True,
    }


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL_URL"),
    reason="requires an explicitly disposable PostgreSQL URL",
)
def test_publish_waits_while_run_selection_holds_parent_lock() -> None:
    database_url = os.environ["TEST_POSTGRESQL_URL"]
    schema = f"task3_lock_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_engine(
        database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    ScopedSession = sessionmaker(bind=scoped_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(scoped_engine)
    errors: list[BaseException] = []
    selection_locked = threading.Event()
    release_selection = threading.Event()
    publish_entered = threading.Event()
    publish_completed = threading.Event()

    try:
        with ScopedSession() as setup:
            setup.add(
                User(
                    id=101,
                    email="task3-lock@example.test",
                    display_name="Task 3 Lock",
                    admin_role="super_admin",
                )
            )
            seed_official_rule_sets(setup)
            setup.commit()
            classic_seed = next(
                seed for seed in OFFICIAL_RULE_SET_SEEDS if seed["id"] == "classic_8"
            )
            draft_config = normalize_rule_set_config(
                {**classic_seed["config"], "name": "经典 8 人局 第二版"}
            )
            draft = update_rule_set_draft(
                setup,
                "classic_8",
                config=draft_config,
                display_order=1,
                expected_rule_set_lock_version=1,
                expected_revision_lock_version=None,
                actor_user_id=101,
            )
            assert draft.draft is not None
            parent_lock_version = draft.record.lock_version
            revision_lock_version = draft.draft.lock_version
            setup.commit()

        def hold_selection_lock() -> None:
            try:
                with ScopedSession() as selection_db:
                    resolve_published_rule_set(
                        selection_db,
                        "classic_8",
                        expected_revision_id=("e9fa678e-9b18-5079-91d2-f74835364fb6"),
                        for_update=True,
                    )
                    selection_locked.set()
                    if not release_selection.wait(timeout=5):
                        raise TimeoutError("selection lock release timed out")
                    selection_db.commit()
            except BaseException as exc:
                errors.append(exc)
                selection_locked.set()

        def publish_next_revision() -> None:
            try:
                if not selection_locked.wait(timeout=5):
                    raise TimeoutError("selection did not acquire its lock")
                with ScopedSession() as publish_db:
                    publish_entered.set()
                    publish_rule_set(
                        publish_db,
                        "classic_8",
                        expected_rule_set_lock_version=parent_lock_version,
                        expected_revision_lock_version=revision_lock_version,
                        reason="Verify run selection serialization",
                        actor_user_id=101,
                    )
                    publish_db.commit()
                    publish_completed.set()
            except BaseException as exc:
                errors.append(exc)
                publish_completed.set()

        selection_thread = threading.Thread(target=hold_selection_lock)
        publish_thread = threading.Thread(target=publish_next_revision)
        selection_thread.start()
        assert selection_locked.wait(timeout=5)
        publish_thread.start()
        assert publish_entered.wait(timeout=5)
        time.sleep(0.25)
        assert not publish_completed.is_set()
        release_selection.set()
        selection_thread.join(timeout=5)
        publish_thread.join(timeout=5)

        assert not selection_thread.is_alive()
        assert not publish_thread.is_alive()
        assert errors == []
        assert publish_completed.is_set()
    finally:
        release_selection.set()
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL_URL"),
    reason="requires an explicitly disposable PostgreSQL URL",
)
def test_compensation_waits_for_event_lock_and_keeps_the_committed_mutation() -> None:
    database_url = os.environ["TEST_POSTGRESQL_URL"]
    schema = f"task3_compensation_lock_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_engine(
        database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    ScopedSession = sessionmaker(bind=scoped_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(scoped_engine)
    run = LiveRunRegistry(worker_id="worker-compensation").prepare_run(
        session_id="game_compensation_lock",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    compensation_started = threading.Event()
    compensation_pid: list[int] = []
    compensation_results: list[bool] = []
    errors: list[BaseException] = []

    try:
        with ScopedSession() as setup:
            games_routes.DatabaseLiveStore(setup).stage_new_run(run)
            setup.commit()

        modifier = ScopedSession()
        compensation_thread: threading.Thread | None = None
        try:
            event = modifier.scalar(
                select(LiveEventRecord)
                .where(
                    LiveEventRecord.run_id == run.run_id,
                    LiveEventRecord.event_id == 1,
                )
                .with_for_update()
            )
            assert event is not None
            event.payload = {**event.payload, "externally_mutated": True}
            modifier.flush()

            def compensate() -> None:
                try:
                    with ScopedSession() as cleanup:
                        pid = cleanup.scalar(text("SELECT pg_backend_pid()"))
                        assert isinstance(pid, int)
                        compensation_pid.append(pid)
                        compensation_started.set()
                        compensation_results.append(
                            games_routes._compensate_committed_run(cleanup, run)
                        )
                except BaseException as exc:
                    errors.append(exc)
                    compensation_started.set()

            compensation_thread = threading.Thread(target=compensate)
            compensation_thread.start()
            assert compensation_started.wait(timeout=5)
            assert compensation_pid

            deadline = time.monotonic() + 5
            observed_lock_wait = False
            while time.monotonic() < deadline:
                with admin_engine.connect() as observer:
                    activity = observer.execute(
                        text(
                            "SELECT wait_event_type, query FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": compensation_pid[0]},
                    ).one_or_none()
                if activity is not None and activity.wait_event_type == "Lock":
                    blocked_query = activity.query.lower()
                    assert "live_events" in blocked_query
                    assert "for update" in blocked_query
                    observed_lock_wait = True
                    break
                time.sleep(0.01)
            assert observed_lock_wait
            assert compensation_results == []

            modifier.commit()
            compensation_thread.join(timeout=5)
            assert not compensation_thread.is_alive()
        finally:
            modifier.rollback()
            modifier.close()
            if compensation_thread is not None:
                compensation_thread.join(timeout=5)

        assert errors == []
        assert compensation_results == [False]
        with ScopedSession() as observer:
            saved_run = observer.get(LiveRunRecord, run.run_id)
            saved_event = observer.get(LiveEventRecord, (run.run_id, 1))
        assert saved_run is not None
        assert saved_event is not None
        assert saved_event.payload["externally_mutated"] is True
    finally:
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.parametrize(
    ("expected_value", "persisted_value"),
    [(False, 0), (True, 1), (1, 1.0)],
    ids=["false-to-zero", "true-to-one", "int-to-float"],
)
def test_compensation_rejects_type_coercive_nested_event_payload_changes(
    expected_value: object,
    persisted_value: object,
) -> None:
    run = LiveRunRegistry(worker_id="worker-compensation").prepare_run(
        session_id="game_compensation_strict",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set={
            "id": "classic_8",
            "strict_comparison_marker": {"value": expected_value},
        },
    )
    with TestingSessionLocal() as setup:
        games_routes.DatabaseLiveStore(setup).save_new_run(run)
    with TestingSessionLocal() as external:
        event = external.get(LiveEventRecord, (run.run_id, 1))
        assert event is not None
        payload = dict(event.payload)
        rule_set = dict(payload["rule_set"])
        marker = dict(rule_set["strict_comparison_marker"])
        marker["value"] = persisted_value
        rule_set["strict_comparison_marker"] = marker
        payload["rule_set"] = rule_set
        event.payload = payload
        flag_modified(event, "payload")
        external.commit()
    with TestingSessionLocal() as observer:
        changed_event = observer.get(LiveEventRecord, (run.run_id, 1))
        assert changed_event is not None
        changed_value = changed_event.payload["rule_set"]["strict_comparison_marker"]["value"]
        assert changed_value == persisted_value
        assert type(changed_value) is type(persisted_value)
        assert games_routes._stored_event_matches(changed_event, run.events[0]) is False

    with TestingSessionLocal() as cleanup:
        compensated = games_routes._compensate_committed_run(cleanup, run)

    assert compensated is False
    with TestingSessionLocal() as observer:
        saved_run = observer.get(LiveRunRecord, run.run_id)
        saved_event = observer.get(LiveEventRecord, (run.run_id, 1))
    assert saved_run is not None
    assert saved_event is not None
    assert saved_event.payload["rule_set"]["strict_comparison_marker"]["value"] == persisted_value
    assert type(saved_event.payload["rule_set"]["strict_comparison_marker"]["value"]) is type(
        persisted_value
    )


def test_create_game_run_stage_failure_rolls_back_without_local_or_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    thread_constructions: list[object] = []

    def fail_stage(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("insert", {}, Exception("stage failed"))

    class NeverThread:
        def __init__(self, **kwargs: object) -> None:
            thread_constructions.append(kwargs)

        def start(self) -> None:
            raise AssertionError("a failed stage must not start a worker")

    monkeypatch.setattr(
        "app.api.routes.games.DatabaseLiveStore.stage_new_run",
        fail_stage,
        raising=False,
    )
    monkeypatch.setattr("app.api.routes.games.threading.Thread", NeverThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rule_set_store_unavailable"
    assert thread_constructions == []
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        assert session.query(LiveRunRecord).count() == 0
        assert session.query(LiveEventRecord).count() == 0


def test_create_game_run_commit_failure_rolls_back_without_local_or_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    db = TestingSessionLocal()
    thread_constructions: list[object] = []

    def fail_commit() -> None:
        raise OperationalError("commit", {}, Exception("commit failed"))

    monkeypatch.setattr(db, "commit", fail_commit)

    def override_failing_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_failing_db

    class NeverThread:
        def __init__(self, **kwargs: object) -> None:
            thread_constructions.append(kwargs)

        def start(self) -> None:
            raise AssertionError("a failed commit must not start a worker")

    monkeypatch.setattr("app.api.routes.games.threading.Thread", NeverThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        db.close()
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rule_set_store_unavailable"
    assert thread_constructions == []
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        assert session.query(LiveRunRecord).count() == 0
        assert session.query(LiveEventRecord).count() == 0


def test_create_game_run_compensates_when_commit_succeeds_but_ack_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    db = TestingSessionLocal()
    original_commit = db.commit
    commit_calls = 0
    thread_constructions: list[object] = []

    def uncertain_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        original_commit()
        if commit_calls == 1:
            raise OperationalError("commit", {}, Exception("commit ack lost"))

    monkeypatch.setattr(db, "commit", uncertain_commit)

    def override_uncertain_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_uncertain_db

    class NeverThread:
        def __init__(self, **kwargs: object) -> None:
            thread_constructions.append(kwargs)

        def start(self) -> None:
            raise AssertionError("an uncertain commit must not start a worker")

    monkeypatch.setattr("app.api.routes.games.threading.Thread", NeverThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        db.close()
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rule_set_store_unavailable"
    assert commit_calls == 2
    assert thread_constructions == []
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        assert session.query(LiveRunRecord).count() == 0
        assert session.query(LiveEventRecord).count() == 0


def test_create_game_run_attach_failure_compensates_committed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    if not hasattr(registry, "attach_prepared_run"):
        pytest.fail("LiveRunRegistry.attach_prepared_run is missing")

    def fail_attach(_run: object) -> None:
        raise RuntimeError("attach failed")

    monkeypatch.setattr(registry, "attach_prepared_run", fail_attach)
    thread_constructions: list[object] = []

    class NeverThread:
        def __init__(self, **kwargs: object) -> None:
            thread_constructions.append(kwargs)

        def start(self) -> None:
            raise AssertionError("a failed attach must not start a worker")

    monkeypatch.setattr("app.api.routes.games.threading.Thread", NeverThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "game_run_start_unavailable"
    assert thread_constructions == []
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        assert session.query(LiveRunRecord).count() == 0
        assert session.query(LiveEventRecord).count() == 0


@pytest.mark.parametrize("failure_phase", ["construct", "start"])
def test_create_game_run_thread_failure_detaches_and_compensates_committed_rows(
    failure_phase: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    starts: list[str] = []

    class FailingThread:
        def __init__(self, **_kwargs: object) -> None:
            if failure_phase == "construct":
                raise RuntimeError("thread construction failed")

        def start(self) -> None:
            starts.append("attempted")
            raise RuntimeError("thread start failed")

    monkeypatch.setattr("app.api.routes.games.threading.Thread", FailingThread)
    non_raising_client = TestClient(app, raise_server_exceptions=False)

    try:
        response = non_raising_client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "game_run_start_unavailable"
    assert starts == ([] if failure_phase == "construct" else ["attempted"])
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        assert session.query(LiveRunRecord).count() == 0
        assert session.query(LiveEventRecord).count() == 0


@pytest.mark.parametrize("compensation_outcome", ["condition_mismatch", "storage_error"])
def test_create_game_run_thread_failure_keeps_recoverable_row_when_compensation_fails(
    compensation_outcome: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)

    class FailingThread:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread start failed")

    def fail_compensation(*_args: object, **_kwargs: object) -> bool:
        if compensation_outcome == "storage_error":
            raise OperationalError("delete", {}, Exception("cleanup unavailable"))
        return False

    monkeypatch.setattr("app.api.routes.games.threading.Thread", FailingThread)
    monkeypatch.setattr(
        "app.api.routes.games._compensate_committed_run",
        fail_compensation,
        raising=False,
    )
    non_raising_client = TestClient(app, raise_server_exceptions=False)

    try:
        response = non_raising_client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "game_run_start_unavailable"
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        saved_run = session.query(LiveRunRecord).one()
        saved_events = session.query(LiveEventRecord).all()
    assert saved_run.status == "queued"
    assert saved_run.fence_token == 0
    assert saved_run.worker_heartbeat_at is None
    assert [event.type for event in saved_events] == ["run_created"]


@pytest.mark.parametrize(
    "external_change",
    [
        "worker_id",
        "control_version",
        "stop_requested",
        "extra_event",
        "mutated_event",
        "payload_only",
        "created_at_only",
        "round_only",
        "phase_only",
        "actor_only",
        "action_only",
    ],
)
def test_create_game_run_thread_failure_does_not_delete_externally_changed_run(
    external_change: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_live_registry(registry)
    changed_at = datetime.now(UTC)

    class FailingThread:
        def __init__(self, *, target, kwargs, daemon) -> None:
            del target, daemon
            self.run_id = str(kwargs["run_id"])
            self.session_id = str(kwargs["session_id"])

        def start(self) -> None:
            with TestingSessionLocal() as external:
                record = external.get(LiveRunRecord, self.run_id)
                assert record is not None
                if external_change == "worker_id":
                    record.worker_id = "worker_external"
                elif external_change == "control_version":
                    record.control_version = 1
                elif external_change == "stop_requested":
                    record.stop_requested_at = changed_at
                elif external_change == "extra_event":
                    external.add(
                        LiveEventRecord(
                            run_id=self.run_id,
                            event_id=2,
                            session_id=self.session_id,
                            type="run_stop_requested",
                            payload={"requested_at": changed_at.isoformat()},
                        )
                    )
                elif external_change == "mutated_event":
                    event = external.get(LiveEventRecord, (self.run_id, 1))
                    assert event is not None
                    event.type = "externally_mutated"
                else:
                    event = external.get(LiveEventRecord, (self.run_id, 1))
                    assert event is not None
                    if external_change == "payload_only":
                        event.payload = {**event.payload, "externally_mutated": True}
                    elif external_change == "created_at_only":
                        event.created_at = datetime(2030, 1, 1, tzinfo=UTC)
                    elif external_change == "round_only":
                        event.round = 9
                    elif external_change == "phase_only":
                        event.phase = "externally_mutated"
                    elif external_change == "actor_only":
                        event.actor = "external"
                    elif external_change == "action_only":
                        event.action = "external"
                external.commit()
            raise RuntimeError("thread start failed after external control change")

    monkeypatch.setattr("app.api.routes.games.threading.Thread", FailingThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "expected_rule_revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
                "seed": 21,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "game_run_start_unavailable"
    assert registry._runs == {}
    with TestingSessionLocal() as session:
        saved_run = session.query(LiveRunRecord).one()
        saved_events = session.query(LiveEventRecord).order_by(LiveEventRecord.event_id.asc()).all()
    assert saved_run.status == "queued"
    assert saved_run.fence_token == 0
    if external_change == "worker_id":
        assert saved_run.worker_id == "worker_external"
    elif external_change == "control_version":
        assert saved_run.control_version == 1
        assert saved_run.stop_requested_at is None
    elif external_change == "stop_requested":
        assert saved_run.control_version == 0
        assert saved_run.stop_requested_at is not None
    elif external_change == "extra_event":
        assert [event.type for event in saved_events] == [
            "run_created",
            "run_stop_requested",
        ]
    elif external_change == "mutated_event":
        assert [event.type for event in saved_events] == ["externally_mutated"]
    else:
        assert [event.type for event in saved_events] == ["run_created"]
        event = saved_events[0]
        if external_change == "payload_only":
            assert event.payload["externally_mutated"] is True
        elif external_change == "created_at_only":
            assert event.created_at == datetime(2030, 1, 1)
        elif external_change == "round_only":
            assert event.round == 9
        elif external_change == "phase_only":
            assert event.phase == "externally_mutated"
        elif external_change == "actor_only":
            assert event.actor == "external"
        elif external_change == "action_only":
            assert event.action == "external"


def test_create_game_run_randomly_fills_profiles_when_no_lineup_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(6)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "starter_6", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    configs = response.json()["player_configs"]
    assert [config["seat"] for config in configs] == [1, 2, 3, 4, 5, 6]
    assert {config["profile_id"] for config in configs} == {
        f"profile-{index}" for index in range(1, 7)
    }
    assert len({config["name"] for config in configs}) == 6
    assert [config.to_dict() for config in captured[0]["player_configs"]] == configs
    report = response.json()["lineup_quality_report"]
    assert report["schema_version"] == 1
    assert report["is_blocked"] is False
    assert report["was_repaired"] is True
    assert report["style_bucket_count"] >= 3


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


def test_create_game_run_allows_explicit_manual_quality_override_in_repair_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_ids = add_virtual_profiles(6, diverse=False)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games._run_game_in_background", lambda **_kwargs: None)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "starter_6",
                "seed": 21,
                "max_rounds": 1,
                "allow_lineup_quality_warnings": True,
                "player_configs": [
                    {"seat": seat, "profile_id": profile_id}
                    for seat, profile_id in enumerate(profile_ids, start=1)
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    assert response.json()["lineup_quality_report"]["is_blocked"] is True


def test_enforce_mode_rejects_manual_quality_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_ids = add_virtual_profiles(6, diverse=False)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    monkeypatch.setattr(settings, "werewolf_lineup_quality_mode", "enforce")
    monkeypatch.setattr("app.api.routes.games._run_game_in_background", lambda **_kwargs: None)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "starter_6",
                "seed": 21,
                "max_rounds": 1,
                "allow_lineup_quality_warnings": True,
                "player_configs": [
                    {"seat": seat, "profile_id": profile_id}
                    for seat, profile_id in enumerate(profile_ids, start=1)
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "lineup_quality_gate_failed"


def test_create_game_run_returns_lineup_quality_warnings_for_homogeneous_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(6, diverse=False)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)

    def fake_background_run(**kwargs: object) -> None:
        del kwargs

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "starter_6", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    problem = response.json()["detail"]
    assert problem["code"] == "lineup_quality_gate_failed"
    assert problem["lineup_quality_report"]["is_blocked"] is True
    assert "personality_overrepresented" in {
        violation["code"] for violation in problem["lineup_quality_report"]["violations"]
    }


def test_create_game_run_rejects_when_player_library_is_too_small(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(1)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "classic_8", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Player profile library has 1 available players, but 8 seats require virtual players"
    )
    assert captured == []


def test_create_game_run_defaults_to_agent_plan_when_plan_key_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n"
        "ARK_AGENT_PLAN_API_KEY=agent-plan-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    registry = LiveRunRegistry()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post("/api/v1/games/runs", json={"seed": 21, "max_rounds": 1})
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["villager_model"] == "doubao-seed-2-0-lite-260215"
    assert payload["werewolf_model"] == "doubao-seed-2-0-lite-260215"
    assert captured[0]["villager_model"] == "doubao-seed-2-0-lite-260215"
    assert captured[0]["werewolf_model"] == "doubao-seed-2-0-lite-260215"


def test_create_game_run_rejects_unknown_rule_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "missing_rule", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rule_set_unavailable"
    assert "current_rule_set" not in response.json()["detail"]


def test_create_game_run_resolves_profile_configs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestingSessionLocal() as session:
        session.add(
            PlayerAvatarAsset(
                id="system-gothic-female-2",
                source="system",
                content_type="image/png",
                data_base64=base64.b64encode(b"png-bytes").decode("ascii"),
                sha256="0" * 64,
                size_bytes=9,
            )
        )
        session.add(
            VirtualPlayerProfile(
                id="profile-alpha",
                display_name="控场位",
                model_provider="deepseek",
                model="profile-model",
                personality_id="cautious",
                personality_text="谨慎控场，避免过早暴露身份。",
                appearance_id="gothic-female-2",
                avatar_image_url="/player-avatars/gothic-female-2.png",
                avatar_image_mime="image/png",
                avatar_asset_id="system-gothic-female-2",
                tags=["控场"],
                status="published",
                published_at=datetime.now(UTC),
                display_order=1,
            )
        )
        session.commit()
    add_virtual_profiles(7)

    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [
                    {
                        "seat": 2,
                        "profile_id": "profile-alpha",
                        "name": "覆盖名",
                        "personality_id": "aggressive",
                        "appearance_id": "crimson",
                        "tags": ["压迫", "控场"],
                    }
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    configs = response.json()["player_configs"]
    snapshot = next(config for config in configs if config["seat"] == 2)
    expected_personality = "\n".join(
        [
            default_personality_text("aggressive"),
            "狼人杀策略: 稳健观察，按证据推进，不轻易极端站边。",
            "冒险倾向: 3/5",
            "伪装倾向: 3/5",
            "信任倾向: 3/5",
            "领导倾向: 3/5",
            "发言活跃: 3/5",
        ]
    )
    assert snapshot == {
        "seat": 2,
        "profile_id": "profile-alpha",
        "name": "覆盖名",
        "model_provider": "deepseek",
        "model": "profile-model",
        "personality_id": "aggressive",
        "personality": expected_personality,
        "appearance_id": "crimson",
        "avatar_image_url": "/api/v1/player-profiles/avatar-assets/system-gothic-female-2",
        "avatar_asset_id": "system-gothic-female-2",
        "strategy_profile": "balanced",
        "tts_speaker": "zh_female_gaolengyujie_uranus_bigtts",
        "tts_dialect": "",
        "base_delivery_mood": "neutral",
        "base_delivery_intensity": "medium",
        "base_delivery_pace": "natural",
        "base_delivery_instruction": "",
        "voice_enabled": True,
        "voice_config_version": 1,
        "tags": ["压迫", "控场"],
    }
    background_configs = captured[0]["player_configs"]
    assert len(background_configs) == 8
    assert snapshot in [config.to_dict() for config in background_configs]


def test_create_game_run_returns_503_when_profile_database_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    app.dependency_overrides[get_db] = override_broken_db
    monkeypatch.setattr(settings, "rule_set_catalog_source", "static", raising=False)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [{"seat": 2, "profile_id": "profile-file"}],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json() == {"detail": "Player profile database unavailable"}
    assert captured == []


def test_game_run_player_config_composes_rich_profile_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "控场样本",
            "model_provider": "deepseek",
            "model": "deepseek-v4-flash",
            "personality_id": "analytical",
            "personality_text": "先找矛盾，再给站边。",
            "short_description": "逻辑控场玩家",
            "speaking_style": "发言会分点列证据。",
            "strategy_profile": "logic_leader",
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["我觉得 2 号的视角漏掉了昨晚信息。"],
        },
    ).json()
    add_virtual_profiles(7)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "player_configs": [{"seat": 1, "profile_id": created["id"]}],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    config = next(item for item in response.json()["player_configs"] if item["seat"] == 1)
    assert config["name"] == "控场样本"
    assert "先找矛盾，再给站边。" in config["personality"]
    assert "逻辑控场玩家" in config["personality"]
    assert "常用表达:" not in config["personality"]
    assert "领导倾向: 5/5" in config["personality"]
    assert config in [item.to_dict() for item in captured[0]["player_configs"]]


def test_game_run_player_config_keeps_explicit_personality_text_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "覆盖样本",
            "model_provider": "deepseek",
            "model": "deepseek-v4-flash",
            "personality_id": "analytical",
            "personality_text": "先找矛盾，再给站边。",
            "short_description": "这段不应进入运行配置",
            "leadership_tendency": 5,
        },
    ).json()
    add_virtual_profiles(7)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "player_configs": [
                    {
                        "seat": 1,
                        "profile_id": created["id"],
                        "personality_text": "只使用运行时覆盖。",
                    }
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    config = next(item for item in response.json()["player_configs"] if item["seat"] == 1)
    assert config["personality"] == "只使用运行时覆盖。"
    assert config in [item.to_dict() for item in captured[0]["player_configs"]]


def test_create_game_run_rejects_duplicate_effective_player_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [
                    {"seat": 1, "profile_id": "profile-1", "name": "同名玩家"},
                    {"seat": 2, "profile_id": "profile-2", "name": "同名玩家"},
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Duplicate player name: 同名玩家"
    assert captured == []


def test_create_game_run_rejects_missing_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [{"seat": 1, "profile_id": "missing"}],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown player profile: missing"


def test_resume_game_run_creates_live_run_from_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    run_params = {
        "villager_model": "Qwen3.6-Plus",
        "werewolf_model": "minimax-m3",
        "seed": 21,
        "max_rounds": 8,
        "rule_set_id": "starter_6",
        "player_configs": [
            {
                "seat": 2,
                "profile_id": "profile-alpha",
                "name": "控场位",
                "model_provider": "deepseek",
                "model": "profile-model",
                "personality_id": "cautious",
                "personality": "谨慎控场。",
                "appearance_id": "moonlit",
                "avatar_image_url": "/api/v1/player-profiles/avatar/profile-alpha.png",
                "avatar_asset_id": None,
                "strategy_profile": "balanced",
                "tags": ["控场"],
            }
        ],
    }
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Maximum rounds exceeded"),
        checkpoint=sample_checkpoint(
            session_id,
            run_params=run_params,
            state=sample_state(session_id, winner="", error=""),
        ),
    )
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_resume_background(**kwargs: object) -> None:
        run_id = str(kwargs["run_id"])
        assert registry.get_run(run_id).run_id == run_id
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._resume_game_in_background", fake_resume_background)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    def reject_catalog_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resume must use the checkpoint rule snapshot")

    monkeypatch.setattr("app.werewolf.rules.get_rule_set", reject_catalog_lookup)
    monkeypatch.setattr(
        "app.api.routes.games.resolve_published_rule_set",
        reject_catalog_lookup,
    )

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["villager_model"] == "Qwen3.6-Plus"
    assert payload["werewolf_model"] == "minimax-m3"
    assert payload["rule_set"]["id"] == "starter_6"
    compiled = managed_official_compiled_rule_set("starter_6")
    assert payload["rule_set"] == compiled.snapshot
    assert payload["rule_set_revision_id"] == compiled.revision_id
    assert payload["rule_set_revision_no"] == compiled.revision_no
    assert payload["rule_set_content_hash"] == compiled.content_hash
    assert payload["player_configs"] == [
        {
            "seat": 2,
            "profile_id": "profile-alpha",
            "name": "控场位",
            "model_provider": "deepseek",
            "model": "profile-model",
            "personality_id": "cautious",
            "personality": "谨慎控场。",
            "appearance_id": "moonlit",
            "avatar_image_url": "/api/v1/player-profiles/avatar/profile-alpha.png",
            "avatar_asset_id": None,
            "strategy_profile": "balanced",
            "tts_speaker": "",
            "tts_dialect": "",
            "base_delivery_mood": "neutral",
            "base_delivery_intensity": "medium",
            "base_delivery_pace": "natural",
            "base_delivery_instruction": "",
            "voice_enabled": True,
            "voice_config_version": 1,
            "tags": ["控场"],
        }
    ]
    assert captured[0]["session_id"] == session_id
    assert captured[0]["expected_compiled_rule_set"].snapshot == compiled.snapshot
    assert set(captured[0]) == {
        "run_id",
        "registry",
        "session_id",
        "expected_compiled_rule_set",
    }


@pytest.mark.parametrize(
    ("corruption", "metric_reason"),
    [
        ("content-hash", "rule_metadata_mismatch"),
        ("missing-schema", "invalid_structure"),
        ("untrimmed-revision-id", "rule_metadata_mismatch"),
    ],
)
def test_invalid_resume_checkpoint_does_not_return_or_claim_active_run(
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    metric_reason: str,
) -> None:
    session_id = "game_1200abcd"
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Worker unavailable"),
        checkpoint=sample_checkpoint(session_id),
    )
    with TestingSessionLocal() as db:
        payload = db.get(GameReplayPayload, session_id)
        assert payload is not None
        checkpoint = copy.deepcopy(payload.checkpoint)
        if corruption == "content-hash":
            checkpoint["run_params"]["content_hash"] = "0" * 64
        elif corruption == "missing-schema":
            checkpoint.pop("schema_version")
        else:
            untrimmed = f" {checkpoint['run_params']['revision_id']} "
            checkpoint["run_params"]["revision_id"] = untrimmed
            checkpoint["run_params"]["rule_set_snapshot"]["revision_id"] = untrimmed
            checkpoint["state_at_round_start"]["rule_set"]["revision_id"] = untrimmed
        payload.checkpoint = checkpoint
        flag_modified(payload, "checkpoint")
        db.commit()

    compiled = managed_official_compiled_rule_set("starter_6")
    registry = LiveRunRegistry()
    active = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id=compiled.rule_set.id,
        rule_set_revision_id=compiled.revision_id,
        rule_set_revision_no=compiled.revision_no,
        rule_set_content_hash=compiled.content_hash,
        rule_set=compiled.snapshot,
    )
    claims: list[str] = []
    starts: list[dict[str, object]] = []

    def fail_claim(run_id: str):
        claims.append(run_id)
        raise AssertionError("invalid checkpoint must not claim an active run")

    monkeypatch.setattr(registry, "try_claim_stale_run", fail_claim)
    monkeypatch.setattr(
        "app.api.routes.games._resume_game_in_background",
        lambda **kwargs: starts.append(kwargs),
    )
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)
    override_replay_store()
    override_live_registry(registry)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Resume checkpoint is invalid"
    assert claims == []
    assert starts == []
    assert registry.get_run(active.run_id).fence_token == active.fence_token
    assert (
        f'werewolf_rule_checkpoint_failures_total{{reason="{metric_reason}"}} 1' in _rule_metrics()
    )


def test_rule_metric_route_only_checkpoint_structure_failure_precedes_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Worker unavailable"),
        checkpoint=sample_checkpoint(session_id),
    )
    with TestingSessionLocal() as db:
        payload = db.get(GameReplayPayload, session_id)
        assert payload is not None and isinstance(payload.checkpoint, dict)
        checkpoint = copy.deepcopy(payload.checkpoint)
        checkpoint["run_params"]["player_configs"] = "SECRET player 张三"
        payload.checkpoint = checkpoint
        flag_modified(payload, "checkpoint")
        db.commit()

    registry = LiveRunRegistry()
    claims: list[str] = []
    monkeypatch.setattr(
        registry,
        "try_get_active_run_for_session",
        lambda candidate: claims.append(candidate),
    )
    override_replay_store()
    override_live_registry(registry)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Resume checkpoint is invalid"
    assert claims == []
    metrics = _rule_metrics()
    assert 'werewolf_rule_checkpoint_failures_total{reason="invalid_structure"} 1' in metrics
    assert "SECRET player" not in metrics
    assert "张三" not in metrics


def test_resume_rejects_active_live_snapshot_mismatch_without_starting_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Worker unavailable"),
        checkpoint=sample_checkpoint(session_id),
    )
    other = managed_official_compiled_rule_set("classic_8")
    registry = LiveRunRegistry()
    active = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id=other.rule_set.id,
        rule_set_revision_id=other.revision_id,
        rule_set_revision_no=other.revision_no,
        rule_set_content_hash=other.content_hash,
        rule_set=other.snapshot,
    )
    claims: list[str] = []
    starts: list[dict[str, object]] = []
    original_claim = registry.try_claim_stale_run

    def recording_claim(run_id: str):
        claims.append(run_id)
        return original_claim(run_id)

    monkeypatch.setattr(registry, "try_claim_stale_run", recording_claim)
    monkeypatch.setattr(
        "app.api.routes.games._resume_game_in_background",
        lambda **kwargs: starts.append(kwargs),
    )
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)
    override_replay_store()
    override_live_registry(registry)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Resume checkpoint is invalid"
    assert claims == []
    assert starts == []
    assert registry.get_run(active.run_id).rule_set == other.snapshot
    assert (
        'werewolf_rule_checkpoint_failures_total{reason="rule_metadata_mismatch"} 1'
        in _rule_metrics()
    )


@pytest.mark.parametrize("catalog_change", ["publish-newer", "archive"])
def test_resume_uses_exact_checkpoint_revision_after_catalog_change(
    monkeypatch: pytest.MonkeyPatch,
    catalog_change: str,
) -> None:
    session_id = "game_1200abcd"
    old_compiled = managed_official_compiled_rule_set("starter_6")
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Worker unavailable"),
        checkpoint=sample_checkpoint(session_id),
    )
    with TestingSessionLocal() as db:
        db.add(
            User(
                id=101,
                email=f"resume-{catalog_change}@example.test",
                display_name="Resume lifecycle",
                admin_role="super_admin",
            )
        )
        if catalog_change == "publish-newer":
            seed = next(item for item in OFFICIAL_RULE_SET_SEEDS if item["id"] == "starter_6")
            config = normalize_rule_set_config({**seed["config"], "name": "新手 6 人快局 第二版"})
            aggregate = update_rule_set_draft(
                db,
                "starter_6",
                config=config,
                display_order=int(seed["display_order"]),
                expected_rule_set_lock_version=1,
                expected_revision_lock_version=None,
                actor_user_id=101,
            )
            assert aggregate.draft is not None
            parent_lock = aggregate.record.lock_version
            revision_lock = aggregate.draft.lock_version
            db.commit()
            published = publish_rule_set(
                db,
                "starter_6",
                expected_rule_set_lock_version=parent_lock,
                expected_revision_lock_version=revision_lock,
                reason="Verify resume remains pinned",
                actor_user_id=101,
            )
            assert published.published is not None
            assert published.published.id != old_compiled.revision_id
        else:
            archived = archive_rule_set(
                db,
                "starter_6",
                expected_rule_set_lock_version=1,
                replacement_default_rule_set_id=None,
                replacement_expected_lock_version=None,
                reason="Verify archived resume remains pinned",
                actor_user_id=101,
            )
            assert archived.record.status == "archived"
        db.commit()

    registry = LiveRunRegistry()
    captured: list[dict[str, object]] = []

    def reject_catalog_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resume must not query current, static, or published catalogs")

    monkeypatch.setattr("app.werewolf.rules.get_rule_set", reject_catalog_lookup)
    monkeypatch.setattr(games_routes, "_resolve_selected_rule_set", reject_catalog_lookup)
    monkeypatch.setattr(games_routes, "_resolve_static_rule_set", reject_catalog_lookup)
    monkeypatch.setattr(games_routes, "resolve_published_rule_set", reject_catalog_lookup)
    monkeypatch.setattr(
        "app.api.routes.games._resume_game_in_background",
        lambda **kwargs: captured.append(kwargs),
    )
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)
    override_replay_store()
    override_live_registry(registry)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["rule_set_revision_id"] == old_compiled.revision_id
    assert payload["rule_set_revision_no"] == old_compiled.revision_no
    assert payload["rule_set_content_hash"] == old_compiled.content_hash
    assert payload["rule_set"] == old_compiled.snapshot
    assert len(captured) == 1
    expected = captured[0]["expected_compiled_rule_set"]
    assert isinstance(expected, CompiledRuleSet)
    assert expected.snapshot == old_compiled.snapshot


def test_resume_rejects_mismatched_concurrent_winner_from_get_or_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Worker unavailable"),
        checkpoint=sample_checkpoint(session_id),
    )
    other = managed_official_compiled_rule_set("classic_8")
    registry = LiveRunRegistry()
    mismatched = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id=other.rule_set.id,
        rule_set_revision_id=other.revision_id,
        rule_set_revision_no=other.revision_no,
        rule_set_content_hash=other.content_hash,
        rule_set=other.snapshot,
    )
    monkeypatch.setattr(registry, "try_get_active_run_for_session", lambda _session_id: None)
    monkeypatch.setattr(
        registry,
        "get_or_create_active_run",
        lambda **_kwargs: (mismatched, False),
    )
    starts: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.api.routes.games._resume_game_in_background",
        lambda **kwargs: starts.append(kwargs),
    )
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)
    override_replay_store()
    override_live_registry(registry)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Resume checkpoint is invalid"
    assert starts == []


def test_resume_game_run_recovers_commit_ack_loss_and_starts_one_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Maximum rounds exceeded"),
        checkpoint=sample_checkpoint(session_id),
    )
    commit_failure = RuntimeError("commit acknowledgement lost")

    class CommitAckLostSessionLiveStore(SessionLiveStore):
        def __init__(self) -> None:
            super().__init__(TestingSessionLocal)

        def save_new_run(self, run) -> None:
            db = TestingSessionLocal()
            original_commit = db.commit

            def commit_then_raise() -> None:
                original_commit()
                raise commit_failure

            setattr(db, "commit", commit_then_raise)
            try:
                games_routes.DatabaseLiveStore(db).save_new_run(run)
            finally:
                db.close()

    registry = LiveRunRegistry(
        live_store=CommitAckLostSessionLiveStore(),
        worker_id="worker-resume-candidate",
    )
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_resume_background(**kwargs: object) -> None:
        run_id = str(kwargs["run_id"])
        assert registry.get_run(run_id).run_id == run_id
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._resume_game_in_background", fake_resume_background)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 201, response.text
    payload = response.json()
    assert len(captured) == 1
    assert captured[0]["run_id"] == payload["run_id"]
    assert registry.get_run(payload["run_id"]).next_event_id == 2
    with TestingSessionLocal() as db:
        saved_runs = db.query(LiveRunRecord).all()
        saved_events = db.query(LiveEventRecord).all()
    assert len(saved_runs) == 1
    assert len(saved_events) == 1
    assert saved_events[0].run_id == saved_runs[0].run_id == payload["run_id"]
    assert saved_events[0].event_id == 1
    assert saved_events[0].type == "run_created"


def test_resume_without_checkpoint_does_not_return_an_incomplete_persisted_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    run_id = "run_incomplete_missing"
    store_incomplete_live_run(session_id=session_id, run_id=run_id)
    registry = LiveRunRegistry(
        live_store=SessionLiveStore(TestingSessionLocal),
        worker_id="worker-resume",
    )
    override_replay_store()
    override_live_registry(registry)
    background_starts: list[dict[str, object]] = []

    def fake_resume_background(**kwargs: object) -> None:
        background_starts.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._resume_game_in_background", fake_resume_background)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert background_starts == []
    assert registry._runs == {}
    with TestingSessionLocal() as db:
        saved = db.get(LiveRunRecord, run_id)
    assert saved is not None
    assert saved.worker_id == "worker-incomplete-owner"
    assert saved.fence_token == 4
    assert saved.control_version == 2


def test_resume_with_checkpoint_does_not_claim_or_start_an_incomplete_persisted_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    run_id = "run_incomplete_checkpoint"
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Maximum rounds exceeded"),
        checkpoint=sample_checkpoint(session_id),
    )
    store_incomplete_live_run(session_id=session_id, run_id=run_id)
    registry = LiveRunRegistry(
        live_store=SessionLiveStore(TestingSessionLocal),
        worker_id="worker-resume",
    )
    override_replay_store()
    override_live_registry(registry)
    background_starts: list[dict[str, object]] = []

    def fake_resume_background(**kwargs: object) -> None:
        background_starts.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._resume_game_in_background", fake_resume_background)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)
    non_raising_client = TestClient(app, raise_server_exceptions=False)

    try:
        response = non_raising_client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code not in {200, 201}
    assert background_starts == []
    assert registry._runs == {}
    with TestingSessionLocal() as db:
        saved = db.get(LiveRunRecord, run_id)
    assert saved is not None
    assert saved.worker_id == "worker-incomplete-owner"
    assert saved.fence_token == 4
    assert saved.control_version == 2


def test_resume_game_run_reuses_active_run_without_starting_another_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Maximum rounds exceeded"),
        checkpoint=sample_checkpoint(session_id),
    )
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_resume_background(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._resume_game_in_background", fake_resume_background)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        first_response = client.post(f"/api/v1/games/{session_id}/resume")
        second_response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["run_id"] == first_response.json()["run_id"]
    assert len(captured) == 1


def test_resume_game_run_claims_a_stale_active_run_instead_of_creating_a_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Worker unavailable"),
        checkpoint=sample_checkpoint(session_id),
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(TestingSessionLocal),
        worker_id="worker-owner",
    )
    compiled = managed_official_compiled_rule_set("starter_6")
    run = owner.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id=compiled.rule_set.id,
        rule_set_revision_id=compiled.revision_id,
        rule_set_revision_no=compiled.revision_no,
        rule_set_content_hash=compiled.content_hash,
        rule_set=compiled.snapshot,
    )
    owner.mark_running(run.run_id)
    with TestingSessionLocal() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        db.commit()

    recovery = LiveRunRegistry(
        live_store=SessionLiveStore(TestingSessionLocal),
        worker_id="worker-recovery",
    )
    override_replay_store()
    override_live_registry(recovery)
    captured: list[dict[str, object]] = []

    def fake_resume_background(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._resume_game_in_background", fake_resume_background)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 201, response.text
    assert response.json()["run_id"] == run.run_id
    assert captured[0]["run_id"] == run.run_id
    with TestingSessionLocal() as db:
        saved = db.get(LiveRunRecord, run.run_id)
        assert saved is not None
        assert saved.worker_id == "worker-recovery"
        assert saved.fence_token == run.fence_token + 1


def test_resume_stale_claim_rejects_locked_rule_snapshot_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    checkpoint_compiled = managed_official_compiled_rule_set("starter_6")
    changed_compiled = managed_official_compiled_rule_set("classic_8")
    store_game_session(
        session_id,
        state=sample_state(session_id, winner="", error="Worker unavailable"),
        checkpoint=sample_checkpoint(session_id),
    )
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(TestingSessionLocal),
        worker_id="worker-rule-owner",
    )
    run = owner.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set_id=checkpoint_compiled.rule_set.id,
        rule_set_revision_id=checkpoint_compiled.revision_id,
        rule_set_revision_no=checkpoint_compiled.revision_no,
        rule_set_content_hash=checkpoint_compiled.content_hash,
        rule_set=checkpoint_compiled.snapshot,
    )
    owner.mark_running(run.run_id)
    with TestingSessionLocal() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        original_fence = record.fence_token
        original_attempts = record.recovery_attempts
        db.commit()

    class RuleRaceSessionLiveStore(SessionLiveStore):
        mutated = False

        def acquire_lease(self, run_id: str, **kwargs):
            if not self.mutated:
                self.mutated = True
                with TestingSessionLocal() as db:
                    record = db.get(LiveRunRecord, run_id)
                    assert record is not None
                    record.rule_set_id = changed_compiled.rule_set.id
                    record.rule_set_revision_id = changed_compiled.revision_id
                    record.rule_set_revision_no = changed_compiled.revision_no
                    record.rule_set_content_hash = changed_compiled.content_hash
                    record.rule_set = copy.deepcopy(changed_compiled.snapshot)
                    event = db.get(LiveEventRecord, (run_id, 2))
                    assert event is not None
                    event.payload = {"combined-rule-event-race": True}
                    flag_modified(event, "payload")
                    db.commit()
            return super().acquire_lease(run_id, **kwargs)

    recovery = LiveRunRegistry(
        live_store=RuleRaceSessionLiveStore(TestingSessionLocal),
        worker_id="worker-rule-recovery",
    )
    starts: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.api.routes.games._resume_game_in_background",
        lambda **kwargs: starts.append(kwargs),
    )
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)
    override_replay_store()
    override_live_registry(recovery)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Resume checkpoint is invalid"
    assert starts == []
    assert recovery._runs == {}
    with TestingSessionLocal() as db:
        saved = db.get(LiveRunRecord, run.run_id)
        assert saved is not None
        assert saved.rule_set_id == changed_compiled.rule_set.id
        assert saved.rule_set == changed_compiled.snapshot
        assert saved.worker_id == "worker-rule-owner"
        assert saved.fence_token == original_fence
        assert saved.recovery_attempts == original_attempts


def test_resume_game_run_returns_404_without_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post("/api/v1/games/game_1200abcd/resume")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Resume checkpoint not found"
    assert 'werewolf_rule_checkpoint_failures_total{reason="missing"} 1' in _rule_metrics()


def test_list_games_includes_rule_set_summary(tmp_path: Path) -> None:
    session_id = "game_05095066"
    state = sample_state(session_id)
    state["rule_set"] = {
        "id": "social_8",
        "version": "2026.04",
        "name": "无神职心理局",
        "player_count": 8,
        "roles": [{"role": "狼人", "count": 2}, {"role": "村民", "count": 6}],
    }
    store_game_session(session_id, state=state)
    override_replay_store()

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["sessions"][0]["rule_set"]["id"] == "social_8"


def test_create_game_run_returns_live_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_replay_store()
    override_live_registry(registry)
    started: list[str] = []

    def fake_background_run(**kwargs: object) -> None:
        started.append(str(kwargs["run_id"]))

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["run_id"].startswith("run_")
    assert payload["session_id"].startswith("game_")
    assert payload["status"] in {"queued", "running", "completed", "failed"}
    assert payload["event_count"] >= 1
    assert started == [payload["run_id"]]


def test_create_game_run_persists_live_run_and_created_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    store = RecordingSessionLiveStore()
    registry = LiveRunRegistry(live_store=store)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    with TestingSessionLocal() as session:
        saved_run = session.get(LiveRunRecord, payload["run_id"])
        saved_events = (
            session.query(LiveEventRecord)
            .filter(LiveEventRecord.run_id == payload["run_id"])
            .order_by(LiveEventRecord.event_id.asc())
            .all()
        )

    assert saved_run is not None
    assert saved_run.session_id == payload["session_id"]
    assert [event.type for event in saved_events] == ["run_created"]
    assert store.saved_runs == []
    assert store.events == []
    assert captured[0]["run_id"] == payload["run_id"]


def test_get_game_run_returns_404_for_missing_run() -> None:
    registry = LiveRunRegistry()
    override_live_registry(registry)

    try:
        response = client.get("/api/v1/games/runs/run_missing")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game run not found"


def test_get_and_stream_game_run_from_a_different_registry_instance() -> None:
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(TestingSessionLocal),
        worker_id="worker-owner",
    )
    run = owner.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=12,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)
    owner.publish(run.run_id, "phase_started", phase="night")
    owner.mark_completed(run.run_id, winner="好人阵营")
    observer = LiveRunRegistry(
        live_store=SessionLiveStore(TestingSessionLocal),
        worker_id="worker-observer",
        event_poll_seconds=0.01,
    )
    override_live_registry(observer)

    try:
        summary_response = client.get(f"/api/v1/games/runs/{run.run_id}")
        events_response = client.get(f"/api/v1/games/runs/{run.run_id}/events")
    finally:
        clear_overrides()

    assert summary_response.status_code == 200
    assert summary_response.json()["status"] == "completed"
    assert summary_response.json()["event_count"] == 4
    assert events_response.status_code == 200
    assert "event: phase_started" in events_response.text
    assert "event: game_completed" in events_response.text


def test_run_game_in_background_publishes_registry_and_engine_events_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = managed_official_compiled_rule_set("classic_8")
    registry = LiveRunRegistry(live_store=SessionLiveStore(TestingSessionLocal))
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id=compiled.rule_set.id,
        rule_set_revision_id=compiled.revision_id,
        rule_set_revision_no=compiled.revision_no,
        rule_set_content_hash=compiled.content_hash,
        rule_set=compiled.snapshot,
    )

    def reject_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("background new-game execution must not query a rule catalog")

    def fake_run_game(
        *,
        event_sink,
        record_store,
        compiled_rule_set,
        **kwargs: object,
    ) -> SimpleNamespace:
        assert isinstance(record_store, DatabaseReplayStore)
        assert record_store.run_id == run.run_id
        assert record_store.worker_id == registry.worker_id
        assert record_store.fence_token == 1
        assert compiled_rule_set is compiled
        assert "rule_set_id" not in kwargs
        decisive_event = event_sink.publish("phase_started", phase="night")
        return SimpleNamespace(
            winner="狼人阵营",
            terminal_keep_from_event_id=decisive_event.id,
        )

    monkeypatch.setattr("app.api.routes.games.run_game", fake_run_game)
    monkeypatch.setattr("app.api.routes.games.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("app.werewolf.rules.get_rule_set", reject_lookup)
    monkeypatch.setattr(games_routes, "resolve_published_rule_set", reject_lookup)

    _run_game_in_background(
        run_id=run.run_id,
        registry=registry,
        session_id=run.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        compiled=compiled,
    )

    activated = registry.get_run(run.run_id)
    assert activated.worker_id == registry.worker_id
    assert activated.fence_token == 1
    assert [event.type for event in registry.events_after(run.run_id)] == [
        "run_created",
        "run_started",
        "phase_started",
        "game_completed",
    ]
    with TestingSessionLocal() as session:
        saved_events = (
            session.query(LiveEventRecord)
            .filter(LiveEventRecord.run_id == run.run_id)
            .order_by(LiveEventRecord.event_id.asc())
            .all()
        )
    assert [event.type for event in saved_events] == [
        "run_created",
        "run_started",
        "phase_started",
        "game_completed",
    ]
    assert saved_events[-1].payload == {
        "winner": "狼人阵营",
        "terminal_keep_from_event_id": 3,
    }


def test_run_game_in_background_rejects_completion_without_terminal_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = managed_official_compiled_rule_set("classic_8")
    registry = LiveRunRegistry(live_store=SessionLiveStore(TestingSessionLocal))
    run = registry.create_run(
        session_id="game_1200abce",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id=compiled.rule_set.id,
        rule_set_revision_id=compiled.revision_id,
        rule_set_revision_no=compiled.revision_no,
        rule_set_content_hash=compiled.content_hash,
        rule_set=compiled.snapshot,
    )

    def fake_run_game(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(winner="狼人阵营")

    monkeypatch.setattr("app.api.routes.games.run_game", fake_run_game)
    monkeypatch.setattr("app.api.routes.games.SessionLocal", TestingSessionLocal)

    _run_game_in_background(
        run_id=run.run_id,
        registry=registry,
        session_id=run.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        compiled=compiled,
    )

    failed = registry.get_run(run.run_id)
    assert failed.status == "failed"
    assert [event.type for event in failed.events] == [
        "run_created",
        "run_started",
        "game_failed",
    ]


def test_game_run_events_replays_existing_events() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    )
    registry.publish(run.run_id, "game_started", payload={"players": []})
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/runs/{run.run_id}/events")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: run_created" in body
    assert "event: game_started" in body
    assert "event: game_completed" in body


def test_public_run_events_redact_roles_and_private_night_actions() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )
    registry.publish(
        run.run_id,
        "game_started",
        payload={
            "players": [{"name": "阿青", "role": "secret-role", "observations": ["private-memory"]}]
        },
    )
    registry.publish(
        run.run_id,
        "action_parsed",
        phase="night",
        actor="阿青",
        action="werewolf_kill_vote",
        payload={"choice": "阿白"},
    )
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/runs/{run.run_id}/events")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert '"name": "阿青"' in response.text
    assert "secret-role" not in response.text
    assert "private-memory" not in response.text
    assert "werewolf_kill_vote" not in response.text


def test_god_view_events_require_session_and_keep_structured_roles() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )
    registry.publish(
        run.run_id,
        "game_started",
        payload={
            "players": [{"name": "阿青", "role": "secret-role", "observations": ["private-memory"]}]
        },
    )
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        unauthenticated = client.get(f"/api/v1/games/runs/{run.run_id}/god-view/events")
        app.dependency_overrides[games_routes.get_current_public_principal] = lambda: object()
        authenticated = client.get(f"/api/v1/games/runs/{run.run_id}/god-view/events")
    finally:
        clear_overrides()

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert '"role": "secret-role"' in authenticated.text
    assert "private-memory" not in authenticated.text


def test_game_run_events_honors_after_id_query() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    )
    registry.publish(run.run_id, "game_started", payload={"players": []})
    registry.publish(run.run_id, "round_started", round_number=1, payload={"round": 1})
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/runs/{run.run_id}/events?after_id=2")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.text
    assert "id: 1" not in body
    assert "id: 2" not in body
    assert "event: run_created" not in body
    assert "event: game_started" not in body
    assert "id: 3" in body
    assert "event: round_started" in body
    assert "id: 4" in body
    assert "event: game_completed" in body


def test_session_timeline_events_fold_resume_runs() -> None:
    session_id = "game_a110e120"
    registry = LiveRunRegistry(live_store=RecordingSessionLiveStore())
    first = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    registry.publish(first.run_id, "game_started", payload={"players": []})
    registry.publish(first.run_id, "round_started", round_number=1, payload={"round": 1})
    registry.publish(first.run_id, "round_started", round_number=2, payload={"round": 2})
    registry.mark_failed(first.run_id, error="temporary")

    resumed = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        parent_run_id=first.run_id,
        resume_from_round=2,
        attempt_no=2,
    )
    registry.publish(
        resumed.run_id,
        "game_resumed",
        payload={"players": [], "resume_from_round": 2},
    )
    registry.publish(resumed.run_id, "round_started", round_number=2, payload={"round": 2})
    registry.mark_completed(resumed.run_id, winner="好人阵营")

    response = client.get(f"/api/v1/games/runs/{resumed.run_id}/timeline-events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: game_started") == 1
    assert response.text.count("event: game_resumed") == 1
    streamed_events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["round"] for event in streamed_events if event["type"] == "round_started"] == [
        1,
        2,
    ]
    assert "event: game_failed" not in response.text
    assert "event: game_completed" in response.text


def test_game_run_events_honors_last_event_id_header() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    )
    registry.publish(run.run_id, "game_started", payload={"players": []})
    registry.publish(run.run_id, "round_started", round_number=1, payload={"round": 1})
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        response = client.get(
            f"/api/v1/games/runs/{run.run_id}/events",
            headers={"Last-Event-ID": "2"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.text
    assert "id: 1" not in body
    assert "id: 2" not in body
    assert "event: run_created" not in body
    assert "event: game_started" not in body
    assert "id: 3" in body
    assert "event: round_started" in body
    assert "id: 4" in body
    assert "event: game_completed" in body


def test_list_games_returns_complete_and_partial_sessions() -> None:
    complete_id = "game_05095066"
    partial_id = "game_0600abcd"
    store_game_session(complete_id, state=sample_state(complete_id), logs=sample_logs())
    store_game_session(
        partial_id,
        state=sample_state(partial_id, winner="", error="Maximum rounds exceeded"),
        logs=sample_logs(),
    )
    override_replay_store()

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert {item["session_id"] for item in payload["sessions"]} == {complete_id, partial_id}
    partial = next(item for item in payload["sessions"] if item["session_id"] == partial_id)
    complete = next(item for item in payload["sessions"] if item["session_id"] == complete_id)
    assert partial["status"] == "partial"
    assert complete["winner"] == "狼人阵营"
    assert complete["round_count"] == 1
    assert complete["created_at"].endswith("Z")


def test_get_game_detail_returns_state_and_logs() -> None:
    session_id = "game_05095066"
    state = sample_state(session_id)
    state["rounds"][0]["private_summaries"] = {"张三": "SENTINEL_WOLF_PRIVATE_PLAN_刀10号_嫁祸12号"}
    logs = sample_logs()
    logs[0]["summaries"] = [
        {
            "actor": "张三",
            "action": "summarize",
            "options": [],
            "choice": "SENTINEL_WOLF_PRIVATE_PLAN_刀10号_嫁祸12号",
            "lm_log": {"prompt": "私密总结", "raw_response": "私密总结", "parsed": {}},
        }
    ]
    store_game_session(session_id, state=state, logs=logs)
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "complete"
    assert payload["state"]["players"][0]["name"] == "张三"
    assert payload["logs"] == []
    assert "role" in payload["state"]["players"][0]
    assert "observations" not in payload["state"]["players"][0]
    assert "summaries" not in payload["state"]["rounds"][0]
    assert "private_summaries" not in payload["state"]["rounds"][0]
    assert "请选择今晚击杀对象。" not in response.text
    assert "SENTINEL_WOLF_PRIVATE_PLAN" not in response.text
    assert (
        'werewolf_rule_checkpoint_failures_total{reason="invalid_structure"} 0' in _rule_metrics()
    )


def test_get_game_playback_returns_complete_playback_events() -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="好人阵营")
    state["rule_set"] = {
        "id": "starter_6",
        "name": "新手 6 人快局",
        "player_count": 6,
        "roles": [],
    }
    state["players"][0]["observations"] = ["private observation secret"]
    state["players"][0]["gamestate"] = {"hidden": "private gamestate secret"}
    state["players"][0]["known_roles"] = {"李四": "村民"}
    state["players"][0]["bidding_rationale"] = "secret player reasoning"
    state["rounds"][0]["debate"] = [{"speaker": "张三", "message": "我认为李四身份偏低。"}]
    state["rounds"][0]["votes"] = [{"张三": "李四"}]
    logs = sample_logs()
    logs[0]["eliminate"]["lm_log"]["parsed"] = {
        "choice": "李四",
        "reasoning": "secret chain",
    }
    logs[0]["summaries"] = [
        {
            "actor": "张三",
            "action": "summarize",
            "options": [],
            "choice": "SENTINEL_WOLF_PRIVATE_PLAN_刀10号_嫁祸12号",
            "lm_log": {
                "prompt": "私密总结",
                "raw_response": "SENTINEL_WOLF_PRIVATE_PLAN_刀10号_嫁祸12号",
                "parsed": {"summary": "SENTINEL_WOLF_PRIVATE_PLAN_刀10号_嫁祸12号"},
            },
        }
    ]
    store_game_session(session_id, state=state, logs=logs)
    override_replay_store()

    try:
        app.dependency_overrides[games_routes.get_current_public_principal] = lambda: object()
        response = client.get(f"/api/v1/games/{session_id}/god-view/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "complete"
    assert payload["resumable"] is False
    assert payload["rule_set"]["id"] == "starter_6"
    event_types = [event["type"] for event in payload["events"]]
    events = payload["events"]
    assert event_types[:3] == ["run_created", "run_started", "game_started"]
    run_created, run_started, game_started = events[:3]
    assert run_created["payload"]["playback"] is True
    assert run_created["payload"]["session_id"] == session_id
    assert run_created["payload"]["status"] == "complete"
    assert run_created["payload"]["rule_set"]["id"] == "starter_6"
    assert run_created["payload"]["resumable"] is False
    assert run_started["payload"] == {"playback": True}
    assert game_started["payload"]["playback"] is True
    assert game_started["payload"]["rule_set"]["id"] == "starter_6"
    assert game_started["payload"]["players"][0] == {
        "name": "张三",
        "role": "狼人",
        "model": "deepseek-chat",
    }
    assert "round_started" in event_types
    assert "action_parsed" in event_types
    assert all(event.get("action") != "summarize" for event in events)
    assert "SENTINEL_WOLF_PRIVATE_PLAN" not in response.text
    assert not any(
        event["type"] == "action_requested" and event["action"] == "remove" for event in events
    )
    assert any(
        event["type"] == "action_parsed"
        and event["actor"] == "张三"
        and event["action"] == "remove"
        and event["payload"].get("choice") == "李四"
        for event in events
    )
    parsed_event = next(
        event
        for event in events
        if event["type"] == "action_parsed"
        and event["actor"] == "张三"
        and event["action"] == "remove"
    )
    assert parsed_event["payload"]["result"] == {"choice": "李四"}
    assert parsed_event["payload"]["visible_result"] == {"choice": "李四"}
    assert any(
        event["type"] == "state_updated"
        and event["phase"] == "day"
        and event["payload"].get("votes") == {"张三": "李四"}
        for event in events
    )
    assert event_types[-1] == "game_completed"
    assert payload["events"][-1]["payload"] == {"winner": "好人阵营"}
    event_ids = [event["id"] for event in payload["events"]]
    assert event_ids == sorted(set(event_ids))
    assert all(event["run_id"] == f"playback_{session_id}" for event in payload["events"])
    serialized_events = json.dumps(payload["events"], ensure_ascii=False)
    assert "请选择今晚击杀对象。" not in serialized_events
    assert "raw_response" not in serialized_events
    assert "prompt" not in serialized_events
    assert "reasoning" not in serialized_events
    assert "secret chain" not in serialized_events
    assert "observations" not in serialized_events
    assert "gamestate" not in serialized_events
    assert "known_roles" not in serialized_events
    assert "bidding_rationale" not in serialized_events
    assert "private observation secret" not in serialized_events
    assert "private gamestate secret" not in serialized_events
    assert "secret player reasoning" not in serialized_events
    assert "李四" in serialized_events


def test_public_playback_redacts_roles_and_private_night_actions() -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="好人阵营")
    state["players"][0]["role"] = "secret-role"
    logs = sample_logs()
    logs[0]["eliminate"]["lm_log"]["raw_response"] = "private-wolf-plan"
    store_game_session(session_id, state=state, logs=logs)
    override_replay_store()

    try:
        god_view_response = client.get(f"/api/v1/games/{session_id}/god-view/playback")
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert god_view_response.status_code == 401
    assert "secret-role" not in response.text
    assert "private-wolf-plan" not in response.text
    assert all(
        event.get("action")
        not in {"remove", "protect", "investigate", "witch_save", "witch_poison"}
        for event in response.json()["events"]
    )


def test_get_game_playback_returns_persisted_events_and_saved_voices() -> None:
    session_id = "game_a110e001"
    store_game_session(session_id)
    registry = LiveRunRegistry(live_store=RecordingSessionLiveStore())
    run = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    event = registry.publish(
        run.run_id,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-voice", "visible_text": "我不是狼", "is_public": True},
    )
    with TestingSessionLocal() as session:
        voice_store = DatabaseVoiceStore(session, session_id=session_id)
        voice_store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_api_1",
                run_id=run.run_id,
                source_event_id=event.id,
                request_id="req-voice",
                speaker_kind="player",
                speaker_name="阿青",
                speaker="player",
                text="我不是狼",
                action="debate",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        voice_store.append_chunk("voice_api_1", chunk_index=0, audio=b"abc")
        voice_store.complete_utterance("voice_api_1", duration_ms=123)

    response = client.get(f"/api/v1/games/{session_id}/playback")

    assert response.status_code == 200
    payload = response.json()
    assert [event["id"] for event in payload["events"]] == [1, event.id]
    assert {event["run_id"] for event in payload["events"]} == {f"playback_{session_id}"}
    assert payload["voices"] == [
        {
            "utterance_id": "voice_api_1",
            "audience": "player_public",
            "source_event_id": event.id,
            "last_source_event_id": event.id,
            "speaker_kind": "player",
            "speaker_name": "阿青",
            "mime_type": "audio/L16",
            "audio_format": "pcm",
            "sample_rate": 24000,
            "duration_ms": 123,
            "subtitle_timings": [{"text": "我不是狼", "start_ms": 0, "end_ms": 1}],
        }
    ]

    voice_response = client.get(f"/api/v1/games/{session_id}/playback/voices/voice_api_1")
    assert voice_response.status_code == 200
    assert voice_response.json()["chunks"] == [{"chunk_index": 0, "data": "YWJj"}]


def test_god_view_playback_includes_scoped_wolf_chat_voice_only() -> None:
    session_id = "game_a110e002"
    store_game_session(session_id)
    registry = LiveRunRegistry(live_store=RecordingSessionLiveStore())
    run = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    event = registry.publish(
        run.run_id,
        "action_parsed",
        actor="阿青",
        action="werewolf_discuss",
        payload={
            "choice": "3号玩家",
            "visible_result": {
                "target": "3号玩家",
                "message": "今晚建议刀3号。",
            },
        },
    )
    with TestingSessionLocal() as session:
        voice_store = DatabaseVoiceStore(session, session_id=session_id)
        voice_store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_wolf_chat_api",
                run_id=run.run_id,
                source_event_id=event.id,
                request_id=None,
                speaker_kind="player",
                speaker_name="1号玩家",
                speaker="player",
                text="今晚建议刀3号。",
                action="werewolf_discuss",
                audience="spectator_god_view",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        voice_store.append_chunk(
            "voice_wolf_chat_api",
            chunk_index=0,
            audio=b"wolf-chat",
        )
        voice_store.complete_utterance("voice_wolf_chat_api", duration_ms=120)

    public_response = client.get(f"/api/v1/games/{session_id}/playback")
    public_audio = client.get(f"/api/v1/games/{session_id}/playback/voices/voice_wolf_chat_api")
    app.dependency_overrides[games_routes.get_current_public_principal] = lambda: object()
    try:
        god_response = client.get(f"/api/v1/games/{session_id}/god-view/playback")
        god_audio = client.get(
            f"/api/v1/games/{session_id}/god-view/playback/voices/voice_wolf_chat_api"
        )
    finally:
        app.dependency_overrides.pop(
            games_routes.get_current_public_principal,
            None,
        )

    assert public_response.status_code == 200
    assert not any(
        voice["utterance_id"] == "voice_wolf_chat_api" for voice in public_response.json()["voices"]
    )
    assert public_audio.status_code == 404
    assert god_response.status_code == 200
    wolf_voice = next(
        voice
        for voice in god_response.json()["voices"]
        if voice["utterance_id"] == "voice_wolf_chat_api"
    )
    assert wolf_voice["source_event_id"] == event.id
    assert wolf_voice["audience"] == "spectator_god_view"
    assert wolf_voice["subtitle_timings"]
    assert god_audio.status_code == 200
    assert god_audio.json()["chunks"] == [{"chunk_index": 0, "data": "d29sZi1jaGF0"}]


def test_playback_player_voice_covers_the_full_streamed_request_cue() -> None:
    events = [
        {
            "id": 10,
            "source_run_id": "run_voice",
            "source_event_id": 20,
            "type": "model_request_started",
            "payload": {"request_id": "req_voice"},
        },
        {
            "id": 11,
            "source_run_id": "run_voice",
            "source_event_id": 21,
            "type": "model_response_delta",
            "payload": {"request_id": "req_voice", "visible_text": "我是好人"},
        },
        {
            "id": 12,
            "source_run_id": "run_voice",
            "source_event_id": 22,
            "type": "action_parsed",
            "payload": {"request_id": "req_voice"},
        },
    ]

    mapped = games_routes._map_playback_voices_to_timeline(
        [
            {
                "utterance_id": "voice_streamed",
                "run_id": "run_voice",
                "source_event_id": 22,
                "last_source_event_id": 22,
                "speaker_kind": "player",
            }
        ],
        events,
    )

    assert mapped == [
        {
            "utterance_id": "voice_streamed",
            "source_event_id": 10,
            "last_source_event_id": 12,
            "speaker_kind": "player",
        }
    ]


def test_get_game_playback_voice_rejects_cross_session_and_requires_god_view_session() -> None:
    session_id = "game_a110e011"
    other_session_id = "game_a110e012"
    store_game_session(session_id)
    store_game_session(other_session_id)
    registry = LiveRunRegistry(live_store=RecordingSessionLiveStore())
    run = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    event = registry.publish(
        run.run_id,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-voice", "visible_text": "公开发言", "is_public": True},
    )
    with TestingSessionLocal() as session:
        voice_store = DatabaseVoiceStore(session, session_id=session_id)
        voice_store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_scoped",
                run_id=run.run_id,
                source_event_id=event.id,
                request_id="req-voice",
                speaker_kind="player",
                speaker_name="阿青",
                speaker="player",
                text="公开发言",
                action="debate",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        voice_store.append_chunk("voice_scoped", chunk_index=0, audio=b"scoped")
        voice_store.complete_utterance("voice_scoped", duration_ms=100)

    assert (
        client.get(f"/api/v1/games/{other_session_id}/playback/voices/voice_scoped").status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/games/{session_id}/god-view/playback/voices/voice_scoped").status_code
        == 401
    )
    app.dependency_overrides[games_routes.get_current_public_principal] = lambda: object()
    try:
        god_view_response = client.get(
            f"/api/v1/games/{session_id}/god-view/playback/voices/voice_scoped"
        )
    finally:
        app.dependency_overrides.pop(
            games_routes.get_current_public_principal,
            None,
        )
    assert god_view_response.status_code == 200
    assert god_view_response.json()["chunks"] == [{"chunk_index": 0, "data": "c2NvcGVk"}]


def test_historical_summary_event_and_voice_are_filtered_on_read() -> None:
    session_id = "game_a110e099"
    sentinel = "SENTINEL_WOLF_PRIVATE_PLAN_刀10号_嫁祸12号"
    store_game_session(session_id)
    registry = LiveRunRegistry(live_store=RecordingSessionLiveStore())
    run = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    private_event = registry.publish(
        run.run_id,
        "model_response_delta",
        actor="10号玩家",
        action="summarize",
        payload={
            "request_id": "req-private-summary",
            "visible_text": sentinel,
            "is_public": True,
        },
    )
    public_event = registry.publish(
        run.run_id,
        "state_updated",
        action="public_round_brief",
        payload={"public_summary": "第4轮；1号玩家被放逐。"},
    )
    with TestingSessionLocal() as session:
        voice_store = DatabaseVoiceStore(session, session_id=session_id)
        voice_store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_private_summary",
                run_id=run.run_id,
                source_event_id=private_event.id,
                request_id="req-private-summary",
                speaker_kind="player",
                speaker_name="10号玩家",
                speaker="player",
                text=sentinel,
                action=None,
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        voice_store.append_chunk("voice_private_summary", chunk_index=0, audio=b"secret")
        voice_store.complete_utterance("voice_private_summary", duration_ms=100)

    response = client.get(f"/api/v1/games/{session_id}/playback")

    assert response.status_code == 200
    payload = response.json()
    assert all(event.get("action") != "summarize" for event in payload["events"])
    assert any(event["source_event_id"] == public_event.id for event in payload["events"])
    assert payload["voices"] == []
    assert sentinel not in response.text


def test_get_game_playback_repairs_incomplete_saved_subtitle_timings() -> None:
    session_id = "game_a110e003"
    store_game_session(session_id)
    registry = LiveRunRegistry(live_store=RecordingSessionLiveStore())
    run = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    event = registry.publish(
        run.run_id,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={
            "request_id": "req-voice",
            "visible_text": "我是村民，我先过。",
            "is_public": True,
        },
    )
    with TestingSessionLocal() as session:
        voice_store = DatabaseVoiceStore(session, session_id=session_id)
        voice_store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_api_partial_subtitle",
                run_id=run.run_id,
                source_event_id=event.id,
                request_id="req-voice",
                speaker_kind="player",
                speaker_name="阿青",
                speaker="player",
                text="我是村民，我先过。",
                action="debate",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        voice_store.update_subtitle_timings(
            "voice_api_partial_subtitle",
            subtitle_timings=[
                {"text": "我先过。", "start_ms": 700, "end_ms": 1320},
            ],
        )
        voice_store.append_chunk(
            "voice_api_partial_subtitle",
            chunk_index=0,
            audio=b"\0" * 48000,
        )
        voice_store.complete_utterance("voice_api_partial_subtitle", duration_ms=123)

    response = client.get(f"/api/v1/games/{session_id}/playback")

    assert response.status_code == 200
    voice = response.json()["voices"][0]
    assert "".join(cue["text"] for cue in voice["subtitle_timings"]) == "我是村民，我先过。"
    assert voice["subtitle_timings"][0]["start_ms"] == 0
    assert voice["subtitle_timings"][-1]["end_ms"] == 1000


def test_get_game_playback_adds_static_judge_voice_without_saved_voice_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_a110e002"
    store_game_session(session_id)
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    (asset_dir / "game_intro.mp3").write_bytes(b"static-intro")
    (asset_dir / "manifest.json").write_text(
        json.dumps(
            {
                "audio_format": "mp3",
                "sample_rate": 24000,
                "mime_type": "audio/mpeg",
                "lines": [
                    {
                        "id": "game_intro",
                        "filename": "game_intro.mp3",
                        "exists": True,
                        "subtitle_timings": [
                            {"text": "本局游戏开始，", "start_ms": 0, "end_ms": 600},
                            {"text": "请确认身份牌。", "start_ms": 600, "end_ms": 1200},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.api.routes.games.DEFAULT_JUDGE_VOICE_ASSET_DIR",
        asset_dir,
        raising=False,
    )

    response = client.get(f"/api/v1/games/{session_id}/playback")

    assert response.status_code == 200
    payload = response.json()
    game_started_event = next(
        event for event in payload["events"] if event["type"] == "game_started"
    )
    assert payload["voices"] == [
        {
            "utterance_id": f"static_judge_{game_started_event['id']}_game_intro",
            "audience": "player_public",
            "source_event_id": game_started_event["id"],
            "last_source_event_id": game_started_event["id"],
            "speaker_kind": "judge",
            "speaker_name": "法官",
            "mime_type": "audio/mpeg",
            "audio_format": "mp3",
            "sample_rate": 24000,
            "duration_ms": 1200,
            "subtitle_timings": [
                {"text": "本局游戏开始，", "start_ms": 0, "end_ms": 600},
                {"text": "请确认身份牌。", "start_ms": 600, "end_ms": 1200},
            ],
            "chunks": [{"chunk_index": 0, "data": "c3RhdGljLWludHJv"}],
        }
    ]


def test_get_game_playback_omits_saved_voices_without_persisted_live_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_b00ce002"
    store_game_session(session_id)
    empty_asset_dir = tmp_path / "judge-voice"
    empty_asset_dir.mkdir()
    monkeypatch.setattr(
        "app.api.routes.games.DEFAULT_JUDGE_VOICE_ASSET_DIR",
        empty_asset_dir,
        raising=False,
    )
    with TestingSessionLocal() as session:
        voice_store = DatabaseVoiceStore(session, session_id=session_id)
        voice_store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_unaligned",
                run_id="run_missing",
                source_event_id=99,
                request_id="req-missing",
                speaker_kind="player",
                speaker_name="阿青",
                speaker="player",
                text="不要错位播放",
                action="debate",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        voice_store.append_chunk("voice_unaligned", chunk_index=0, audio=b"abc")
        voice_store.complete_utterance("voice_unaligned", duration_ms=123)

    response = client.get(f"/api/v1/games/{session_id}/playback")

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"][0]["run_id"] == f"playback_{session_id}"
    assert payload["voices"] == []


def test_get_game_god_view_playback_exposes_safe_wolf_votes_and_final_target() -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="好人阵营")
    state["rounds"][0]["attacked"] = "李四"
    state["rounds"][0]["werewolf_vote_rounds"] = [
        {
            "round": 1,
            "candidates": ["李四"],
            "votes": {"张三": "李四"},
            "tally": {"李四": 1},
            "unanimous": True,
            "result": "李四",
        }
    ]
    logs = sample_logs()
    logs[0]["eliminate"] = {
        "actor": "张三",
        "action": "werewolf_kill_vote",
        "options": ["李四"],
        "choice": "李四",
        "lm_log": {
            "prompt": "请选择今晚狼刀对象。",
            "raw_response": '{"target":"李四"}',
            "parsed": {"target": "李四"},
        },
    }
    logs[0]["protect"] = {
        "actor": "王五",
        "action": "protect",
        "options": ["张三", "李四"],
        "choice": "张三",
        "lm_log": {
            "prompt": "请选择守护对象。",
            "raw_response": '{"protect":"张三"}',
            "parsed": {"protect": "张三"},
        },
    }
    logs[0]["witch_save"] = {
        "actor": "赵六",
        "action": "witch_save",
        "options": ["李四", "不使用解药"],
        "choice": "不使用解药",
        "lm_log": {
            "prompt": "是否使用解药。",
            "raw_response": '{"save":"不使用解药"}',
            "parsed": {"save": "不使用解药"},
        },
    }
    logs[0]["sheriff_run"] = [
        {
            "actor": "张三",
            "action": "sheriff_run",
            "options": ["上警", "不上警"],
            "choice": "上警",
            "lm_log": {
                "prompt": "是否竞选警长。",
                "raw_response": '{"run":"上警"}',
                "parsed": {"run": "上警"},
            },
        }
    ]
    store_game_session(session_id, state=state, logs=logs)
    override_replay_store()

    try:
        app.dependency_overrides[games_routes.get_current_public_principal] = lambda: object()
        response = client.get(f"/api/v1/games/{session_id}/god-view/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    events = response.json()["events"]
    assert not any(
        event["type"] == "action_requested" and event["action"] == "remove" for event in events
    )
    wolf_vote = next(
        event
        for event in events
        if event["type"] == "action_parsed" and event["action"] == "werewolf_kill_vote"
    )
    assert wolf_vote["actor"] == "张三"
    assert wolf_vote["payload"] == {
        "choice": "李四",
        "result": {"target": "李四"},
        "visible_result": {"target": "李四"},
        "decision_stage": "final",
        "vote_round": 1,
    }
    final_target = next(
        event
        for event in events
        if event["type"] == "action_parsed"
        and event["action"] == "remove"
        and event["payload"].get("final_target") is True
    )
    assert final_target["actor"] is None
    assert final_target["payload"]["choice"] == "李四"
    assert events.index(wolf_vote) < events.index(final_target)
    cue_actions = [event["action"] for event in events if event["type"] == "judge_cue"]
    assert cue_actions == [
        "werewolves_wake",
        "werewolves_sleep",
        "guard_wake",
        "guard_sleep",
        "witch_wake",
        "witch_death",
        "witch_sleep",
        "dawn_peaceful",
        "sheriff_raise_hands",
        "exile_no_result",
    ]
    witch_death = next(
        event
        for event in events
        if event["type"] == "judge_cue" and event["action"] == "witch_death"
    )
    assert witch_death["payload"]["target"] == "李四"
    assert not any(
        event["type"] == "action_requested" and event["action"] == "witch_save" for event in events
    )
    sheriff_cue = next(
        event
        for event in events
        if event["type"] == "judge_cue" and event["action"] == "sheriff_raise_hands"
    )
    sheriff_run_request = next(
        event
        for event in events
        if event["type"] == "action_requested" and event["action"] == "sheriff_run"
    )
    assert events.index(sheriff_cue) < events.index(sheriff_run_request)
    serialized_events = json.dumps(events, ensure_ascii=False)
    assert "请选择今晚狼刀对象" not in serialized_events
    assert "raw_response" not in serialized_events
    assert any(
        event["type"] == "action_parsed"
        and event["actor"] == "王五"
        and event["action"] == "protect"
        and event["payload"].get("choice") == "张三"
        for event in events
    )


def test_werewolf_tiebreak_playback_is_god_only_and_replays_trigger_order() -> None:
    session_id = "game_1200abce"
    state = sample_state(session_id, winner="好人阵营")
    state["players"] = [
        {"name": "张三", "role": "狼人", "model": "deepseek-chat", "observations": []},
        {"name": "王五", "role": "狼人", "model": "deepseek-chat", "observations": []},
        {"name": "李四", "role": "村民", "model": "deepseek-chat", "observations": []},
        {"name": "赵六", "role": "村民", "model": "deepseek-chat", "observations": []},
    ]
    round_state = state["rounds"][0]
    round_state["players"] = ["张三", "王五", "李四", "赵六"]
    round_state["attacked"] = "赵六"
    round_state["werewolf_discussion"] = [
        {
            "round": 1,
            "stage": "proposal",
            "speaker": "张三",
            "target": "李四",
            "message": "李四带队能力强，建议先处理。",
        },
        {
            "round": 1,
            "stage": "proposal",
            "speaker": "王五",
            "target": "赵六",
            "message": "赵六更像关键神职，我倾向改刀。",
        },
    ]
    round_state["werewolf_vote_rounds"] = [
        {
            "round": 1,
            "stage": "final_vote",
            "candidates": ["李四", "赵六"],
            "votes": {"张三": "李四", "王五": "赵六"},
            "tally": {"李四": 1, "赵六": 1},
            "unanimous": False,
            "result": "赵六",
            "tiebreak": {
                "triggered": True,
                "actor": "王五",
                "candidates": ["李四", "赵六"],
                "choice": "赵六",
                "source": "model",
            },
        }
    ]
    store_game_session(session_id, state=state, logs=sample_logs())
    override_replay_store()

    try:
        public_response = client.get(f"/api/v1/games/{session_id}/playback")
        app.dependency_overrides[games_routes.get_current_public_principal] = lambda: object()
        god_response = client.get(f"/api/v1/games/{session_id}/god-view/playback")
    finally:
        clear_overrides()

    assert public_response.status_code == 200
    public_events = public_response.json()["events"]
    assert not any(
        event.get("action")
        in {
            "werewolf_discuss",
            "werewolf_kill_vote",
            "werewolf_tiebreak_start",
            "werewolf_tiebreak_result",
        }
        for event in public_events
    )

    assert god_response.status_code == 200
    private_events = [
        event
        for event in god_response.json()["events"]
        if event.get("action")
        in {
            "werewolf_discuss",
            "werewolf_kill_vote",
            "werewolf_tiebreak_start",
            "werewolf_tiebreak_result",
        }
    ]
    assert [event["action"] for event in private_events] == [
        "werewolf_discuss",
        "werewolf_discuss",
        "werewolf_kill_vote",
        "werewolf_kill_vote",
        "werewolf_tiebreak_start",
        "werewolf_kill_vote",
        "werewolf_tiebreak_result",
    ]
    assert [
        event["payload"].get("decision_stage")
        for event in private_events
        if event["action"] == "werewolf_kill_vote"
    ] == ["final", "final", "tiebreak"]
    tiebreak_start = next(
        event for event in private_events if event["action"] == "werewolf_tiebreak_start"
    )
    assert tiebreak_start["payload"]["player"] == "王五"
    assert tiebreak_start["payload"]["players"] == ["李四", "赵六"]


def test_get_game_playback_suppresses_secret_wolf_self_explosion_check() -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="好人阵营")
    state["rounds"][0]["werewolf_self_exploded"] = "张三"
    state["rounds"][0]["day_ended_by_self_explosion"] = True
    logs = sample_logs()
    logs[0]["werewolf_self_explosion"] = {
        "actor": "张三",
        "action": "werewolf_self_explosion",
        "options": ["自爆", "不自爆"],
        "choice": "自爆",
        "lm_log": {
            "prompt": "行动：狼人自爆判断。",
            "raw_response": '{"reasoning":"秘密判断","self_explode":"自爆"}',
            "parsed": {"reasoning": "秘密判断", "self_explode": "自爆"},
        },
    }
    store_game_session(session_id, state=state, logs=logs)
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    events = response.json()["events"]
    private_event_types = {
        "action_requested",
        "model_request_started",
        "model_response_delta",
        "model_thinking_delta",
        "model_thinking_tick",
        "model_response_received",
        "action_parsed",
    }
    assert [
        event
        for event in events
        if event["action"] == "werewolf_self_explosion" and event["type"] in private_event_types
    ] == []
    day_state = next(
        event for event in events if event["type"] == "state_updated" and event["phase"] == "day"
    )
    assert day_state["payload"]["werewolf_self_exploded"] == "张三"
    serialized_events = json.dumps(events, ensure_ascii=False)
    assert "行动：狼人自爆判断。" not in serialized_events
    assert "秘密判断" not in serialized_events


def test_get_game_playback_preserves_public_day_stage_fields() -> None:
    session_id = "game_1200bcde"
    state = sample_state(session_id, winner="好人阵营")
    state["rounds"][0].update(
        {
            "sheriff": "张三",
            "sheriff_candidates": ["张三", "李四"],
            "sheriff_speech_order": ["张三", "李四"],
            "sheriff_speech_direction": "警左发言",
            "sheriff_speeches": [{"speaker": "张三", "message": "我要竞选警长。"}],
            "sheriff_withdrawn": ["李四"],
            "sheriff_final_candidates": ["张三"],
            "sheriff_voters": ["李四"],
            "sheriff_votes": {"李四": "张三"},
            "sheriff_pk_candidates": ["张三", "李四"],
            "sheriff_pk_speeches": [{"speaker": "李四", "message": "我进入 PK。"}],
            "sheriff_runoff_votes": {"李四": "张三"},
            "sheriff_elected": "张三",
            "speech_order": ["李四", "张三"],
            "speech_order_choice": "警左发言",
            "vote_weights": {"张三": 1.5, "李四": 1},
            "sheriff_badge_target": "李四",
            "sheriff_badge_lost": False,
            "werewolf_self_exploded": "李四",
            "day_ended_by_self_explosion": True,
            "interruption": {
                "stage": "sheriff_speech",
                "interrupted_by": "werewolf_self_explosion",
                "actor": "李四",
                "timing": "before_actor",
                "last_completed_speaker": "张三",
                "completed_actors": ["张三"],
                "pending_actors": ["李四"],
            },
            "sheriff_pre_election_bomb_count": 1,
            "sheriff_election_pending": True,
            "sheriff_badge_lost_reason": "首爆中断警长竞选",
        }
    )
    store_game_session(session_id, state=state, logs=sample_logs())
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    day_state = next(
        event
        for event in response.json()["events"]
        if event["type"] == "state_updated" and event["phase"] == "day"
    )
    assert day_state["payload"] == {
        "debate": [],
        "bids": [{"张三": 3}],
        "votes": {"张三": "李四"},
        "public_summary": "",
        "exiled": None,
        "day_deaths": [],
        "hunter_shot": None,
        "idiot_revealed": None,
        "sheriff": "张三",
        "sheriff_candidates": ["张三", "李四"],
        "sheriff_speech_order": ["张三", "李四"],
        "sheriff_speech_direction": "警左发言",
        "sheriff_speeches": [{"speaker": "张三", "message": "我要竞选警长。"}],
        "sheriff_withdrawn": ["李四"],
        "sheriff_final_candidates": ["张三"],
        "sheriff_voters": ["李四"],
        "sheriff_votes": {"李四": "张三"},
        "sheriff_pk_candidates": ["张三", "李四"],
        "sheriff_pk_speeches": [{"speaker": "李四", "message": "我进入 PK。"}],
        "sheriff_runoff_votes": {"李四": "张三"},
        "sheriff_elected": "张三",
        "speech_order": ["李四", "张三"],
        "speech_order_choice": "警左发言",
        "vote_weights": {"张三": 1.5, "李四": 1},
        "sheriff_badge_target": "李四",
        "sheriff_badge_lost": False,
        "werewolf_self_exploded": "李四",
        "day_ended_by_self_explosion": True,
        "interruption": {
            "stage": "sheriff_speech",
            "interrupted_by": "werewolf_self_explosion",
            "actor": "李四",
            "timing": "before_actor",
            "last_completed_speaker": "张三",
            "completed_actors": ["张三"],
            "pending_actors": ["李四"],
        },
        "sheriff_pre_election_bomb_count": 1,
        "sheriff_election_pending": True,
        "sheriff_badge_lost_reason": "首爆中断警长竞选",
        "narration_mode": "explicit_v1",
        "active_players": ["张三", "李四"],
    }

    cue_events = [event for event in response.json()["events"] if event["type"] == "judge_cue"]
    assert [event["action"] for event in cue_events[-5:]] == [
        "sheriff_result",
        "werewolf_self_explosion",
        "self_explosion_skip",
        "badge_owner_out",
        "badge_transfer",
    ]
    assert all(event["payload"]["schema_version"] == 1 for event in cue_events)
    assert cue_events[-4]["payload"]["params"]["pending_actors"] == ["李四"]


def test_get_game_playback_returns_partial_end_without_resuming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="", error="Maximum rounds exceeded")
    store_game_session(
        session_id,
        state=state,
        logs=sample_logs(),
        checkpoint=sample_checkpoint(
            session_id,
            state=state,
            logs_before_round=sample_logs(),
            run_params={
                "villager_model": "deepseek-chat",
                "werewolf_model": "deepseek-chat",
                "seed": 7,
                "max_rounds": 8,
                "rule_set_id": "classic_8",
                "player_configs": [],
            },
        ),
    )
    override_replay_store()
    registry = LiveRunRegistry()
    created_runs: list[dict[str, object]] = []

    def fail_create_run(**kwargs: object) -> object:
        created_runs.append(kwargs)
        raise AssertionError("playback must not create a live run")

    monkeypatch.setattr(registry, "create_run", fail_create_run)
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["resumable"] is True
    assert payload["events"][-1]["type"] == "game_failed"
    assert payload["events"][-1]["payload"]["playback_partial"] is True
    assert payload["events"][-1]["payload"]["message"] == "对局异常中断。"
    assert "Maximum rounds exceeded" not in response.text
    assert created_runs == []


def test_get_game_playback_returns_404_for_missing_session() -> None:
    override_replay_store()

    try:
        response = client.get("/api/v1/games/game_1200abcd/playback")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json() == {"detail": "Game session not found"}


def test_get_game_playback_returns_404_for_corrupt_replay_payload() -> None:
    session_id = "game_1200abcd"
    with TestingSessionLocal() as session:
        session.add(
            GameSessionRecord(
                session_id=session_id,
                status="complete",
                round_count=0,
                resumable=False,
            )
        )
        session.add(
            GameReplayPayload(
                session_id=session_id,
                state=[],
                logs=[],
            )
        )
        session.commit()
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json() == {"detail": "Game session not found"}


def test_get_game_detail_returns_404_for_missing_valid_session() -> None:
    override_replay_store()

    try:
        response = client.get("/api/v1/games/game_0000dead")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"


def test_get_game_detail_rejects_invalid_session_id() -> None:
    override_replay_store()

    try:
        response = client.get("/api/v1/games/invalid-session-id")
    finally:
        clear_overrides()

    assert response.status_code == 422


def test_list_games_returns_empty_when_no_records() -> None:
    override_replay_store()

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_list_games_ignores_legacy_file_directories(tmp_path: Path) -> None:
    legacy_id = "game_1200abcd"
    write_json(tmp_path / legacy_id / "game_complete.json", sample_state(legacy_id))
    override_replay_store()

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_game_api_reads_database_only_when_legacy_files_exist(tmp_path: Path) -> None:
    legacy_id = "game_1200abcd"
    database_id = "game_05095066"
    write_json(tmp_path / legacy_id / "game_complete.json", sample_state(legacy_id))
    store_game_session(database_id, state=sample_state(database_id), logs=sample_logs())
    override_replay_store()

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert [item["session_id"] for item in response.json()["sessions"]] == [database_id]


def test_get_game_detail_returns_empty_logs_when_logs_are_empty() -> None:
    session_id = "game_05095066"
    store_game_session(session_id, state=sample_state(session_id), logs=[])
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["logs"] == []


def test_partial_game_detail_never_reveals_roles_or_raw_failure_text() -> None:
    session_id = "game_0600abcd"
    state = sample_state(
        session_id,
        winner="",
        error="PRIVATE_PROVIDER_FAILURE role=狼人",
    )
    state["players"][0]["observations"] = ["PRIVATE_OBSERVATION"]
    store_game_session(session_id, state=state, logs=sample_logs())
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["state"]["error_message"] == "对局异常中断。"
    assert payload["logs"] == []
    assert all("role" not in player for player in payload["state"]["players"])
    assert "PRIVATE_PROVIDER_FAILURE" not in response.text
    assert "PRIVATE_OBSERVATION" not in response.text


def test_get_game_detail_returns_404_for_malformed_state() -> None:
    list_state_id = "game_0600abcd"
    null_rounds_id = "game_0700abcd"
    with TestingSessionLocal() as session:
        session.add_all(
            [
                GameSessionRecord(
                    session_id=list_state_id,
                    status="complete",
                    round_count=0,
                    resumable=False,
                ),
                GameReplayPayload(session_id=list_state_id, state=[], logs=[]),
                GameSessionRecord(
                    session_id=null_rounds_id,
                    status="complete",
                    round_count=0,
                    resumable=False,
                ),
                GameReplayPayload(
                    session_id=null_rounds_id,
                    state={"session_id": null_rounds_id, "rounds": None},
                    logs=[],
                ),
            ]
        )
        session.commit()
    override_replay_store()

    try:
        list_response = client.get(f"/api/v1/games/{list_state_id}")
        null_rounds_response = client.get(f"/api/v1/games/{null_rounds_id}")
    finally:
        clear_overrides()

    assert list_response.status_code == 404
    assert list_response.json()["detail"] == "Game session not found"
    assert null_rounds_response.status_code == 404
    assert null_rounds_response.json()["detail"] == "Game session not found"


def test_get_game_detail_returns_404_for_malformed_logs_schema() -> None:
    session_id = "game_05095066"
    with TestingSessionLocal() as session:
        session.add(
            GameSessionRecord(
                session_id=session_id,
                status="complete",
                round_count=1,
                resumable=False,
            )
        )
        session.add(
            GameReplayPayload(
                session_id=session_id,
                state=sample_state(session_id),
                logs={},
            )
        )
        session.commit()
    override_replay_store()

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"
