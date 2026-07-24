from __future__ import annotations

from collections.abc import AsyncIterator, Generator
import asyncio
import hashlib
import json
from pathlib import Path
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.judge_configuration import RuntimeJudgeConfiguration
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.game_session import GameSessionRecord
from app.models.live import LiveRunRecord
from app.models.user import User
from app.v2.live_runtime import V2LiveRuntime
from app.v2.model_client import V2ModelDecision, V2ModelSpeech
from app.v2.models import (
    V2AbilityActivation,
    V2AbilityInstance,
    V2ActionWindow,
    V2EffectIntent,
    V2GameControlRequest,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2GodViewAccessGrant,
    V2LivePresentation,
    V2KnowledgeFact,
    V2PlayerState,
    V2RoleAssignment,
    V2RoleAssignmentBatch,
    V2VoiceAsset,
)


PCM_CHUNK = b"\x10\x00" * 240


class FakeV2ModelClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.contexts: list[dict[str, Any]] = []
        self.release = threading.Event()
        self.release.set()
        self.decision_contexts: list[dict[str, Any]] = []
        self.decline_action_types: set[str] = set()

    async def generate_judge_sentence(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        model_id: str | None = None,
        check_cancellation: Any = None,
    ) -> V2ModelSpeech:
        if check_cancellation is not None:
            check_cancellation()
        self.call_count += 1
        self.contexts.append(action_context)
        if not self.release.is_set():
            released = await asyncio.to_thread(self.release.wait, 5)
            if not released:
                raise RuntimeError("test model release timed out")
        if check_cancellation is not None:
            check_cancellation()
        assert action_context["influence"] == {
            "schema_version": 1,
            "status": "disabled",
            "captured_at": None,
            "strength": 0,
            "signals": [],
        }
        assert attempt_id.startswith("v2_model_")
        assert model_id == "judge-configured-model"
        text_by_action = {
            "judge_opening_speech": "欢迎来到这场实时狼人杀对局。",
            "judge_nightfall_announcement": "夜幕已经降临，请所有玩家闭眼。",
            "judge_dawn_announcement": "天亮了，请大家确认昨夜的结果。",
            "judge_hunter_shot_announcement": "猎人的枪声已经带走一名玩家。",
        }
        text = text_by_action.get(
            action_context["action_type"],
            "这项首夜能力现在开始实时执行。",
        )
        return V2ModelSpeech(
            text=text,
            provider_request_id="provider-response-test",
            first_token_ms=12,
            sentence_ms=34,
        )

    async def generate_action_decision(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        model_id: str | None = None,
        check_cancellation: Any = None,
    ) -> V2ModelDecision:
        if check_cancellation is not None:
            check_cancellation()
        self.call_count += 1
        self.contexts.append(action_context)
        self.decision_contexts.append(action_context)
        assert attempt_id.startswith("v2_model_")
        assert model_id is None
        candidates = action_context["candidates"]
        target = (
            None
            if action_context["action_type"] in self.decline_action_types
            else candidates[0]["player_id"] if candidates else None
        )
        return V2ModelDecision(
            target_player_id=target,
            speech="我先说明自己的判断。这是第二句话！\n现在执行这次实时决策。",
            provider_request_id="provider-decision-test",
            first_token_ms=11,
            completed_ms=29,
        )


class FakeV2TtsClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.speakers: list[str | None] = []
        self.first_chunk = threading.Event()
        self.release = threading.Event()
        self.release.set()

    async def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
        speaker: str | None = None,
        check_cancellation: Any = None,
    ) -> AsyncIterator[bytes]:
        self.call_count += 1
        self.speakers.append(speaker)
        assert text.endswith(("。", "！", "？"))
        assert attempt_id.startswith("v2_tts_")
        yield PCM_CHUNK
        self.first_chunk.set()
        if not self.release.is_set():
            released = await asyncio.to_thread(self.release.wait, 5)
            if not released:
                raise RuntimeError("test TTS release timed out")
        if check_cancellation is not None:
            check_cancellation()
        yield PCM_CHUNK


@pytest.fixture
def v2_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session], Path], None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "v2-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "V2 Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "viewer")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "v2_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    voice_root = tmp_path / "v2-voices"
    monkeypatch.setattr(settings, "live_v2_voice_storage_dir", str(voice_root))

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    model_client = FakeV2ModelClient()
    tts_client = FakeV2TtsClient()
    application.state.v2_live_runtime = V2LiveRuntime(
        session_factory=testing_session,
        model_client=model_client,
        tts_client=tts_client,
        voice_root=voice_root,
        sample_rate=24000,
        judge_configuration_provider=lambda: RuntimeJudgeConfiguration(
            model_provider="agent_plan",
            model_id="judge-configured-model",
            tts_speaker="judge-configured-speaker",
            version=1,
        ),
    )
    application.state.v2_test_model_client = model_client
    application.state.v2_test_tts_client = tts_client
    with TestClient(application) as client:
        yield client, testing_session, voice_root
    engine.dispose()


def test_v2_meta_is_independent_from_v1(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context

    response = client.get("/api/v2/meta")

    assert response.status_code == 200
    assert response.json() == {
        "api_version": "v2",
        "status": "realtime_first_night",
    }
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/health").status_code == 200


def test_existing_mobile_lobby_creates_one_ready_v2_game_with_snapshots(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context

    response = client.post("/api/v2/games", json=_lobby_create_request())

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "ready"
    assert created["game_id"].startswith("v2_game_")
    assert created["run_id"].startswith("v2_run_")
    assert created["websocket_url"].endswith(f"/{created['game_id']}/ws")
    assert created["god_view_snapshot_url"].endswith(f"/{created['game_id']}/identity-snapshot")
    assert created["god_view_websocket_url"].endswith(f"/{created['game_id']}/ws")
    assert len(created["god_view_access_token"]) >= 32
    with session_factory() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == created["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assignment_batch = db.scalar(
            select(V2RoleAssignmentBatch).where(V2RoleAssignmentBatch.game_id == created["game_id"])
        )
        god_view_grant = db.get(V2GodViewAccessGrant, created["game_id"])
        assignments = list(
            db.scalars(
                select(V2RoleAssignment)
                .where(V2RoleAssignment.game_id == created["game_id"])
                .order_by(V2RoleAssignment.seat)
            )
        )
        assert game is not None and game.title == "经典 8 人"
        assert game.status == "ready"
        assert (game.phase_seq, game.phase_id, game.phase_state) == (
            1,
            "opening",
            "opening_ready",
        )
        assert game.last_record_seq == 3
        assert game.rule_snapshot["source"] == "existing_mobile_lobby"
        assert game.rule_snapshot["rule_set"]["id"] == "classic_8"
        assert game.rule_snapshot["rule_set_revision_id"] == "rule_rev_123"
        assert game.rule_snapshot["seed"] == 42
        assert game.rule_snapshot["max_rounds"] == 8
        assert game.players_snapshot == [
            {
                "seat": 1,
                "profile_id": "profile-1",
                "name": "阿青",
                "model": "private-model-id",
                "personality": "private personality prompt",
                "avatar_image_url": "/api/v1/public/player-profiles/profile-1/avatar",
                "strategy_profile": "private-strategy",
                "tts_speaker": "private-speaker",
            },
            {"seat": 2, "profile_id": "profile-2", "name": "白石"},
        ]
        assert run is not None and run.status == "ready"
        assert god_view_grant is not None
        assert (
            god_view_grant.token_sha256
            == hashlib.sha256(created["god_view_access_token"].encode()).hexdigest()
        )
        assert god_view_grant.token_sha256 != created["god_view_access_token"]
        assert assignment_batch is not None
        assert assignment_batch.player_count == 2
        assert len(assignment_batch.seed_hex) == 64
        assert len(assignment_batch.assignment_digest) == 64
        assert [(item.seat, item.player_id) for item in assignments] == [
            (1, "profile-1"),
            (2, "profile-2"),
        ]
        assert sorted((item.role, item.team) for item in assignments) == [
            ("villager", "village"),
            ("werewolf", "werewolves"),
        ]
        assert sorted((item.role_key, item.team) for item in assignments) == [
            ("villager", "village"),
            ("werewolf", "werewolves"),
        ]
        assert all(item.assignment_id == assignment_batch.assignment_id for item in assignments)
        assert [event.event_type for event in events] == [
            "game_created",
            "roles_assigned",
            "ability_runtime_compiled",
        ]
        assert events[0].payload == {
            "title": "经典 8 人",
            "start_mode": "first_ready_viewer",
            "creation_source": "existing_mobile_lobby",
            "rule_set_id": "classic_8",
            "player_count": 2,
        }
        assert events[1].payload == {
            "assignment_id": assignment_batch.assignment_id,
            "assigned_count": 2,
            "visibility": "private_sealed",
        }
        assert events[2].payload == {
            "ability_snapshot_hash": game.ability_snapshot_hash,
            "registry_version": 1,
            "instance_count": 1,
            "execution_enabled": False,
        }
        assert game.ability_snapshot["instances"][0]["ability_id"] == "werewolf.attack"
        assert len(game.ability_snapshot_hash or "") == 64
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2PlayerState)
                .where(V2PlayerState.game_id == created["game_id"])
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2AbilityInstance)
                .where(V2AbilityInstance.game_id == created["game_id"])
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2LivePresentation)
                .where(V2LivePresentation.game_id == created["game_id"])
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2VoiceAsset)
                .where(V2VoiceAsset.game_id == created["game_id"])
            )
            == 0
        )

    snapshot = client.get(
        created["snapshot_url"],
        headers={"Authorization": f"Bearer {created['god_view_access_token']}"},
    )
    assert snapshot.status_code == 200
    assert set(snapshot.json()) == {
        "protocol_version",
        "type",
        "api_version",
        "audience",
        "game_id",
        "run_id",
        "live_state",
        "game_phase",
        "latest_presentation_seq",
        "server_time",
        "public_rule",
        "public_players",
        "public_role_assignment",
        "current_presentation",
    }
    assert snapshot.json()["game_phase"] == {
        "phase_seq": 1,
        "phase_id": "opening",
        "phase_state": "opening_ready",
    }
    public_rule = snapshot.json()["public_rule"]
    assert public_rule == {
        "rule_id": "classic_8",
        "name": "经典 8 人",
        "version": "1",
        "player_count": 2,
        "roles": [
            {"role": "werewolf", "count": 1},
            {"role": "villager", "count": 1},
        ],
        "max_rounds": 8,
        "sheriff_enabled": False,
        "werewolf_self_explosion_enabled": True,
        "exile_last_words_enabled": True,
    }
    assert set(public_rule) == {
        "rule_id",
        "name",
        "version",
        "player_count",
        "roles",
        "max_rounds",
        "sheriff_enabled",
        "werewolf_self_explosion_enabled",
        "exile_last_words_enabled",
    }
    public_players = snapshot.json()["public_players"]
    assert snapshot.json()["public_role_assignment"] == {
        "state": "sealed",
        "assigned_count": 2,
    }
    serialized_public_snapshot = json.dumps(snapshot.json())
    assert assignment_batch.assignment_id not in serialized_public_snapshot
    assert "seed_hex" not in serialized_public_snapshot
    assert "assignment_digest" not in serialized_public_snapshot
    assert '"team"' not in serialized_public_snapshot
    assert public_players == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": "/api/v1/public/player-profiles/profile-1/avatar",
            "alive": True,
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "白石",
            "avatar_url": None,
            "alive": True,
        },
    ]
    assert all(
        set(player) == {"seat", "player_id", "display_name", "avatar_url", "alive"}
        for player in public_players
    )

    god_view_url = created["god_view_snapshot_url"]
    assert client.get(god_view_url).status_code == 403
    assert (
        client.get(
            god_view_url,
            headers={"Authorization": f"Bearer {'x' * 43}"},
        ).status_code
        == 403
    )
    god_view = client.get(
        god_view_url,
        headers={"Authorization": f"Bearer {created['god_view_access_token']}"},
    )
    assert god_view.status_code == 200, god_view.text
    assert god_view.headers["cache-control"] == "private, no-store"
    god_payload = god_view.json()
    assert set(god_payload) == {
        "protocol_version",
        "type",
        "api_version",
        "audience",
        "game_id",
        "run_id",
        "live_state",
        "game_phase",
        "server_time",
        "rule",
        "players",
    }
    assert god_payload["type"] == "god_view.identity_snapshot"
    assert god_payload["audience"] == "spectator_god_view"
    assignment_by_seat = {item.seat: item for item in assignments}
    assert god_payload["players"] == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": "/api/v1/public/player-profiles/profile-1/avatar",
            "role": assignment_by_seat[1].role,
            "team": assignment_by_seat[1].team,
            "alive": True,
            "death_cause": None,
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "白石",
            "avatar_url": None,
            "role": assignment_by_seat[2].role,
            "team": assignment_by_seat[2].team,
            "alive": True,
            "death_cause": None,
        },
    ]
    serialized_god_view = json.dumps(god_payload)
    assert created["god_view_access_token"] not in serialized_god_view
    assert "private-model-id" not in serialized_god_view
    assert "private personality prompt" not in serialized_god_view
    assert "private-strategy" not in serialized_god_view
    assert "private-speaker" not in serialized_god_view


def test_public_and_god_view_share_two_realtime_actions_without_replay(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json=_lobby_create_request()).json()
    god_protocols = ["live-v2-god-view", identifiers["god_view_access_token"]]

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            identifiers["god_view_websocket_url"],
            subprotocols=["live-v2-god-view", "x" * 43],
        ):
            pass

    model_client = client.app.state.v2_test_model_client
    tts_client = client.app.state.v2_test_tts_client
    model_client.release.clear()
    with client.websocket_connect(identifiers["websocket_url"]) as public_socket:
        with client.websocket_connect(
            identifiers["god_view_websocket_url"],
            subprotocols=god_protocols,
        ) as god_socket:
            public_initial = public_socket.receive_json()
            god_initial = god_socket.receive_json()
            assert public_initial["type"] == "live.snapshot"
            assert public_initial["audience"] == "player_public"
            assert "players" not in public_initial
            assert god_socket.accepted_subprotocol == "live-v2-god-view"
            assert god_initial["type"] == "god_view.live_snapshot"
            assert god_initial["audience"] == "spectator_god_view"
            assert [item["role"] for item in god_initial["players"]]
            assert identifiers["god_view_access_token"] not in json.dumps(god_initial)

            public_socket.send_json(_ready_message("client.ready"))
            god_socket.send_json(_ready_message("god_view.ready"))
            assert public_socket.receive_json()["type"] == "live.snapshot"
            assert god_socket.receive_json()["type"] == "god_view.live_snapshot"
            model_client.release.set()

            public_result = _receive_realtime_action(public_socket)
            god_result = _receive_realtime_action(god_socket)

    assert (
        public_result
        == god_result
        == {
            "committed_texts": [
                "欢迎来到这场实时狼人杀对局。",
                "夜幕已经降临，请所有玩家闭眼。",
            ],
            "presentation_seqs": [1, 2],
            "phase_changes": ["first_night"],
            "audio_chunks": 4,
            "awaiting_observation": True,
        }
    )
    assert model_client.call_count == 2
    assert tts_client.call_count == 2
    assert tts_client.speakers == [
        "judge-configured-speaker",
        "judge-configured-speaker",
    ]
    assert [context["action_type"] for context in model_client.contexts] == [
        "judge_opening_speech",
        "judge_nightfall_announcement",
    ]
    with session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "action_opened",
                )
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2VoiceAsset)
                .where(V2VoiceAsset.game_id == identifiers["game_id"])
            )
            == 2
        )

    with client.websocket_connect(
        identifiers["god_view_websocket_url"],
        subprotocols=god_protocols,
    ) as reconnect:
        snapshot = reconnect.receive_json()
        assert snapshot["type"] == "god_view.live_snapshot"
        assert snapshot["live_state"] == "awaiting_observation"
        assert snapshot["game_phase"] == {
            "phase_seq": 2,
            "phase_id": "first_night",
            "phase_state": "nightfall_announced",
        }
        assert snapshot["current_presentation"] is None
        assert [item["role"] for item in snapshot["players"]]


def test_v2_lobby_create_rejects_incomplete_or_duplicate_lineups(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    incomplete = _lobby_create_request()
    incomplete["lobby_snapshot"]["player_configs"] = [{"seat": 1, "profile_id": "profile-1"}]
    duplicate = _lobby_create_request()
    duplicate["lobby_snapshot"]["player_configs"][1]["profile_id"] = "profile-1"
    invalid_roles = _lobby_create_request()
    invalid_roles["lobby_snapshot"]["rule_set"]["roles"][1]["count"] = 2

    assert client.post("/api/v2/games", json=incomplete).status_code == 422
    assert client.post("/api/v2/games", json=duplicate).status_code == 422
    assert client.post("/api/v2/games", json=invalid_roles).status_code == 422


def test_first_ready_viewer_receives_opening_then_nightfall_and_both_voices_are_saved(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    created = client.post("/api/v2/games", json={"title": "首句实时验收"})
    assert created.status_code == 201, created.text
    identifiers = created.json()
    game_id = identifiers["game_id"]

    snapshot = client.get(identifiers["snapshot_url"])
    assert snapshot.status_code == 200
    assert snapshot.json()["live_state"] == "ready"
    assert snapshot.json()["game_phase"]["phase_state"] == "opening_ready"
    assert snapshot.json()["public_rule"] is None
    assert snapshot.json()["public_players"] == []
    assert snapshot.json()["public_role_assignment"] == {
        "state": "unavailable",
        "assigned_count": 0,
    }
    assert snapshot.json()["current_presentation"] is None
    assert (
        client.get(
            identifiers["god_view_snapshot_url"],
            headers={"Authorization": f"Bearer {identifiers['god_view_access_token']}"},
        ).status_code
        == 409
    )

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        assert websocket.receive_json()["live_state"] == "ready"
        websocket.send_json(
            {
                "protocol_version": 1,
                "type": "client.ready",
                "audio": {
                    "encoding": "pcm_s16le",
                    "sample_rate": 24000,
                    "channels": 1,
                },
            }
        )
        assert websocket.receive_json()["type"] == "live.snapshot"
        result = _receive_realtime_action(websocket, include_audio_headers=True)
        assert result["committed_texts"] == [
            "欢迎来到这场实时狼人杀对局。",
            "夜幕已经降临，请所有玩家闭眼。",
        ]
        assert result["presentation_seqs"] == [1, 2]
        assert result["phase_changes"] == ["first_night"]
        assert result["audio_chunks"] == 4
        assert [header["presentation_seq"] for header in result["audio_headers"]] == [
            1,
            1,
            2,
            2,
        ]
        assert [header["chunk_index"] for header in result["audio_headers"]] == [0, 1, 0, 1]
        assert [header["start_sample"] for header in result["audio_headers"]] == [
            0,
            240,
            0,
            240,
        ]

    after = client.get(identifiers["snapshot_url"]).json()
    assert after["live_state"] == "awaiting_observation"
    assert after["game_phase"] == {
        "phase_seq": 2,
        "phase_id": "first_night",
        "phase_state": "nightfall_announced",
    }
    assert after["current_presentation"] is None

    with session_factory() as db:
        game = db.get(V2GameRecord, game_id)
        run = db.get(V2GameRun, identifiers["run_id"])
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        presentations = list(
            db.scalars(
                select(V2LivePresentation)
                .where(V2LivePresentation.game_id == game_id)
                .order_by(V2LivePresentation.presentation_seq)
            )
        )
        voices = list(
            db.scalars(
                select(V2VoiceAsset)
                .where(V2VoiceAsset.game_id == game_id)
                .order_by(V2VoiceAsset.created_at)
            )
        )
        assert game is not None and game.status == "awaiting_observation"
        assert (game.phase_seq, game.phase_id, game.phase_state) == (
            2,
            "first_night",
            "nightfall_announced",
        )
        assert run is not None and run.status == "awaiting_observation"
        assert [item.event_type for item in events] == [
            "game_created",
            "action_opened",
            "model_request_started",
            "model_first_token_received",
            "speech_opened",
            "speech_segment_committed",
            "speech_sealed",
            "tts_stream_started",
            "tts_first_chunk_received",
            "voice_recording_started",
            "audio_broadcast_started",
            "tts_stream_completed",
            "voice_asset_saved",
            "audio_drained",
            "speech_closed",
            "action_succeeded",
            "game_phase_changed",
            "action_opened",
            "model_request_started",
            "model_first_token_received",
            "speech_opened",
            "speech_segment_committed",
            "speech_sealed",
            "tts_stream_started",
            "tts_first_chunk_received",
            "voice_recording_started",
            "audio_broadcast_started",
            "tts_stream_completed",
            "voice_asset_saved",
            "audio_drained",
            "speech_closed",
            "action_succeeded",
        ]
        assert [item.phase_id for item in presentations] == ["opening", "first_night"]
        assert all(item.state == "closed" for item in presentations)
        assert len(voices) == 2
        assert all(item.state == "ready" and item.sample_count == 480 for item in voices)
        assert all(
            item.pcm_sha256 == hashlib.sha256(PCM_CHUNK * 2).hexdigest()
            for item in voices
        )
        for voice in voices:
            voice_path = voice_root / voice.storage_key
            assert voice_path.is_file()
            assert voice_path.read_bytes()[:4] == b"RIFF"
        assert not any("werewolf" in item.event_type for item in events)
        assert db.scalar(select(func.count()).select_from(GameSessionRecord)) == 0
        assert db.scalar(select(func.count()).select_from(LiveRunRecord)) == 0

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        reconnect = websocket.receive_json()
        assert reconnect["live_state"] == "awaiting_observation"
        assert reconnect["game_phase"]["phase_state"] == "nightfall_announced"
        assert reconnect["current_presentation"] is None


def test_admin_v2_record_exposes_saved_voice_only_through_authenticated_endpoint(
    v2_context,
) -> None:
    client, _session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json={"title": "Admin V2 语音"}).json()
    _run_opening_to_nightfall(client, identifiers["websocket_url"])

    unauthorized = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert unauthorized.status_code == 401
    session = client.post("/api/v1/admin/dev-login")
    assert session.status_code == 200, session.text

    detail = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["voice_assets"]) == 2
    for voice in body["voice_assets"]:
        assert voice["state"] == "ready"
        assert voice["pcm_sha256"] == hashlib.sha256(PCM_CHUNK * 2).hexdigest()
        assert voice["audio_url"].startswith("/api/v1/admin/v2/games/")
        audio = client.get(voice["audio_url"])
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert audio.content[:4] == b"RIFF"


def test_admin_operator_can_idempotently_stop_ready_v2_game_without_private_leak(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    identifiers = client.post(
        "/api/v2/games",
        json=_lobby_create_request(),
    ).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-stop-ready-1",
    )
    reason = "人工发现异常，立即停止额度消耗"

    stopped = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": reason},
        headers=headers,
    )

    assert stopped.status_code == 202, stopped.text
    assert stopped.json() == {
        "action": "stop",
        "game_id": identifiers["game_id"],
        "run_id": identifiers["run_id"],
        "run_status": "canceled",
        "stop_requested_at": stopped.json()["stop_requested_at"],
        "replayed": False,
    }
    replayed = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": reason},
        headers=headers,
    )
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    assert replayed.json()["run_status"] == "canceled"

    public_snapshot = client.get(identifiers["snapshot_url"]).json()
    assert public_snapshot["live_state"] == "canceled"
    assert public_snapshot["current_presentation"] is None
    assert reason not in json.dumps(public_snapshot, ensure_ascii=False)
    god_snapshot = client.get(
        identifiers["god_view_snapshot_url"],
        headers={"Authorization": f"Bearer {identifiers['god_view_access_token']}"},
    ).json()
    assert god_snapshot["live_state"] == "canceled"
    assert reason not in json.dumps(god_snapshot, ensure_ascii=False)

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        assert game is not None and game.status == "canceled"
        assert run is not None
        assert run.status == "canceled"
        assert run.stop_requested_at is not None
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == game.game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert [item.event_type for item in events][-2:] == [
            "game_stop_requested",
            "game_canceled",
        ]
        assert reason not in json.dumps(
            [item.payload for item in events],
            ensure_ascii=False,
        )
        assert (
            db.scalar(
                select(func.count()).select_from(V2GameControlRequest)
            )
            == 1
        )
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.v2_game.stop",
                AuditEvent.resource_id == game.game_id,
            )
        )
        assert audit is not None
        assert audit.reason == reason


def test_admin_v2_stop_interrupts_active_voice_and_broadcasts_safe_terminal_state(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    identifiers = client.post(
        "/api/v2/games",
        json=_lobby_create_request(),
    ).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-stop-active-1",
    )
    tts_client = client.app.state.v2_test_tts_client
    tts_client.release.clear()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("bytes") is not None:
                break

        stopped = client.post(
            f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
            json={"reason": "当前语音异常，人工立即打断"},
            headers=headers,
        )
        tts_client.release.set()
        assert stopped.status_code == 202, stopped.text
        assert stopped.json()["run_status"] == "canceled"

        terminal = None
        while terminal is None:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") == "canceled":
                terminal = value
        assert terminal["reason"] == "operator_interrupted"
        assert "当前语音异常" not in json.dumps(terminal, ensure_ascii=False)

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None and game.status == "canceled"
        presentations = list(
            db.scalars(
                select(V2LivePresentation).where(
                    V2LivePresentation.game_id == game.game_id
                )
            )
        )
        voices = list(
            db.scalars(
                select(V2VoiceAsset).where(V2VoiceAsset.game_id == game.game_id)
            )
        )
        assert len(presentations) == 1
        assert presentations[0].state == "canceled"
        assert len(voices) == 1
        assert voices[0].state == "canceled"
        event_types = list(
            db.scalars(
                select(V2GameRecordEvent.event_type)
                .where(V2GameRecordEvent.game_id == game.game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert "voice_recording_canceled" in event_types
        assert "speech_interrupted" in event_types
        assert "game_canceled" in event_types
        assert "action_failed" not in event_types
    assert client.app.state.v2_test_model_client.call_count == 1
    assert not list(voice_root.rglob("*.tmp"))


def test_admin_viewer_cannot_stop_v2_game(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json={"title": "只读权限"}).json()
    session = client.post("/api/v1/admin/dev-login").json()

    response = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": "只读用户不应成功"},
        headers={
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": "v2-stop-viewer-1",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "admin_permission_denied"


def test_executable_rule_runs_dynamic_first_night_without_leaking_private_actions(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request())
    assert created.status_code == 201, created.text
    identifiers = created.json()

    public_texts: list[str] = []
    public_types: list[str] = []
    god_texts: list[str] = []
    god_types: list[str] = []
    with client.websocket_connect(identifiers["websocket_url"]) as public_socket:
        with client.websocket_connect(
            identifiers["god_view_websocket_url"],
            subprotocols=["live-v2-god-view", identifiers["god_view_access_token"]],
        ) as god_socket:
            public_socket.receive_json()
            god_socket.receive_json()
            public_socket.send_json(_ready_message("client.ready"))
            god_socket.send_json(_ready_message("god_view.ready"))
            assert public_socket.receive_json()["type"] == "live.snapshot"
            assert god_socket.receive_json()["type"] == "god_view.live_snapshot"
            _collect_until_observation(
                public_socket,
                message_types=public_types,
                committed_texts=public_texts,
            )
            _collect_until_observation(
                god_socket,
                message_types=god_types,
                committed_texts=god_texts,
            )

    assert public_texts[:2] == [
        "欢迎来到这场实时狼人杀对局。",
        "夜幕已经降临，请所有玩家闭眼。",
    ]
    assert "天亮了，请大家确认昨夜的结果。" in public_texts
    assert "这项首夜能力现在开始实时执行。" not in public_texts
    assert "night.progress_changed" in public_types
    assert "ability.progress_changed" not in public_types
    assert "god_view.night_resolved" not in public_types
    assert "ability.progress_changed" in god_types
    assert "god_view.night_resolved" in god_types
    assert "night.progress_changed" not in god_types
    assert "这项首夜能力现在开始实时执行。" in god_texts
    assert "我先说明自己的判断。这是第二句话！\n现在执行这次实时决策。" in god_texts

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None
        assert game.status == "awaiting_observation"
        assert (game.phase_id, game.phase_state) == ("day_1", "public_day_ready")
        windows = list(
            db.scalars(
                select(V2ActionWindow)
                .where(V2ActionWindow.game_id == game.game_id)
                .order_by(V2ActionWindow.window_seq)
            )
        )
        assert windows and all(item.state == "closed" for item in windows)
        activations = list(
            db.scalars(
                select(V2AbilityActivation).where(V2AbilityActivation.game_id == game.game_id)
            )
        )
        assert len(activations) >= 4
        assert all(item.status in {"completed", "skipped"} for item in activations)
        effects = list(
            db.scalars(
                select(V2EffectIntent).where(V2EffectIntent.game_id == game.game_id)
            )
        )
        assert {item.effect_type for item in effects} >= {
            "attack",
            "protect",
            "investigate",
        }
        assert all(item.state == "resolved" for item in effects if item.effect_type != "shoot")
        facts = list(
            db.scalars(
                select(V2KnowledgeFact).where(V2KnowledgeFact.game_id == game.game_id)
            )
        )
        assert len(facts) >= 5
        assert sum(item.fact_type == "investigation_alignment" for item in facts) == 1
        assert all(
            len(item.payload["normalized_sha256"]) == 64
            for item in facts
            if item.fact_type == "action_context_projection"
        )
        presentations = list(
            db.scalars(
                select(V2LivePresentation)
                .where(V2LivePresentation.game_id == game.game_id)
                .order_by(V2LivePresentation.presentation_seq)
            )
        )
        assert {item.audience for item in presentations} == {"all", "god_view"}
        assert any(item.actor_kind == "player" for item in presentations)
        assert all(item.state == "closed" for item in presentations)
        assert all(item.activation_id is not None for item in presentations if item.actor_kind == "player")


def test_advanced_rule_executes_witch_policies_and_stops_before_sheriff_window(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.decline_action_types.add("ability_witch.heal_decision")
    created = client.post("/api/v2/games", json=_advanced_create_request())
    assert created.status_code == 201, created.text
    identifiers = created.json()

    public_types: list[str] = []
    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            public_types.append(value["type"])
            if value.get("live_state") == "awaiting_observation":
                break

    assert "ability.progress_changed" not in public_types
    assert "god_view.night_resolved" not in public_types
    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None
        assert (game.phase_id, game.phase_state) == (
            "day_1",
            "sheriff_election_ready",
        )
        instances = {
            item.ability_instance_id: item.ability_id
            for item in db.scalars(
                select(V2AbilityInstance).where(V2AbilityInstance.game_id == game.game_id)
            )
        }
        activations = list(
            db.scalars(
                select(V2AbilityActivation).where(V2AbilityActivation.game_id == game.game_id)
            )
        )
        heal = next(
            item
            for item in activations
            if instances[item.ability_instance_id] == "witch.heal"
        )
        poison = next(
            item
            for item in activations
            if instances[item.ability_instance_id] == "witch.poison"
        )
        assert heal.status == "completed"
        assert heal.decision["target_player_id"] is None
        assert poison.status == "completed"
        assert poison.decision["target_player_id"] is not None
        effects = list(
            db.scalars(
                select(V2EffectIntent).where(V2EffectIntent.game_id == game.game_id)
            )
        )
        attack = next(item for item in effects if item.effect_type == "attack")
        poison_effect = next(item for item in effects if item.effect_type == "poison")
        assert poison_effect.target_player_id not in {
            poison_effect.actor_id,
            attack.target_player_id,
        }
        assert poison_effect.state == "resolved"
    assert all(
        context["influence"]["status"] == "disabled"
        for context in model_client.contexts
    )


def _run_opening_to_nightfall(client: TestClient, websocket_url: str) -> None:
    with client.websocket_connect(websocket_url) as websocket:
        websocket.receive_json()
        websocket.send_json(
            {
                "protocol_version": 1,
                "type": "client.ready",
                "audio": {
                    "encoding": "pcm_s16le",
                    "sample_rate": 24000,
                    "channels": 1,
                },
            }
        )
        while True:
            message = websocket.receive()
            if message.get("text"):
                value = json.loads(message["text"])
                if value.get("live_state") == "awaiting_observation":
                    return


def _collect_until_observation(
    websocket: Any,
    *,
    message_types: list[str],
    committed_texts: list[str],
) -> None:
    while True:
        message = websocket.receive()
        if message.get("text") is None:
            continue
        value = json.loads(message["text"])
        message_types.append(value["type"])
        if value["type"] == "speech.segment_committed":
            committed_texts.append(value["text"])
        if value.get("live_state") == "awaiting_observation":
            return


def _ready_message(message_type: str) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "type": message_type,
        "audio": {
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
        },
    }


def _operator_control_headers(
    client: TestClient,
    session_factory: sessionmaker[Session],
    *,
    idempotency_key: str,
) -> dict[str, str]:
    session = client.post("/api/v1/admin/dev-login")
    assert session.status_code == 200, session.text
    with session_factory.begin() as db:
        user = db.scalar(
            select(User).where(User.email == "v2-admin@example.test")
        )
        assert user is not None
        user.admin_role = "operator"
    return {
        "X-CSRF-Token": session.json()["csrf_token"],
        "Idempotency-Key": idempotency_key,
    }


def _receive_realtime_action(
    websocket: Any,
    *,
    include_audio_headers: bool = False,
) -> dict[str, Any]:
    committed_texts: list[str] = []
    presentation_seqs: list[int] = []
    phase_changes: list[str] = []
    audio_chunks = 0
    audio_headers: list[dict[str, Any]] = []
    while True:
        message = websocket.receive()
        if message.get("bytes") is not None:
            audio_chunks += 1
            if include_audio_headers:
                header, pcm = _decode_audio(message["bytes"])
                assert pcm == PCM_CHUNK
                audio_headers.append(header)
            continue
        if message.get("text") is None:
            continue
        value = json.loads(message["text"])
        if value.get("type") == "speech.segment_committed":
            committed_texts.append(value["text"])
            presentation_seqs.append(value["presentation_seq"])
        if value.get("type") == "game.phase_changed":
            phase_changes.append(value["phase_id"])
        if value.get("live_state") == "awaiting_observation":
            result = {
                "committed_texts": committed_texts,
                "presentation_seqs": presentation_seqs,
                "phase_changes": phase_changes,
                "audio_chunks": audio_chunks,
                "awaiting_observation": True,
            }
            if include_audio_headers:
                result["audio_headers"] = audio_headers
            return result


def _decode_audio(value: bytes) -> tuple[dict[str, Any], bytes]:
    header_size = int.from_bytes(value[4:6], "big")
    header = json.loads(value[6 : 6 + header_size])
    return header, value[6 + header_size :]


def _lobby_create_request() -> dict[str, Any]:
    return {
        "title": "经典 8 人",
        "lobby_snapshot": {
            "schema_version": 1,
            "rule_set": {
                "id": "classic_8",
                "version": "1",
                "name": "经典 8 人",
                "player_count": 2,
                "roles": [
                    {"role": "werewolf", "count": 1, "team": "werewolves"},
                    {"role": "villager", "count": 1, "team": "village"},
                ],
                "sheriff_enabled": False,
                "werewolf_self_explosion_enabled": True,
                "exile_last_words_enabled": True,
            },
            "rule_set_revision_id": "rule_rev_123",
            "seed": 42,
            "max_rounds": 8,
            "player_configs": [
                {
                    "seat": 1,
                    "profile_id": "profile-1",
                    "name": "阿青",
                    "model": "private-model-id",
                    "personality": "private personality prompt",
                    "avatar_image_url": "/api/v1/public/player-profiles/profile-1/avatar",
                    "strategy_profile": "private-strategy",
                    "tts_speaker": "private-speaker",
                },
                {"seat": 2, "profile_id": "profile-2", "name": "白石"},
            ],
            "lineup_quality_report": {
                "schema_version": 1,
                "policy_mode": "repair",
                "player_count": 2,
                "configured_count": 2,
                "is_blocked": False,
                "was_repaired": False,
                "style_bucket_count": 2,
                "required_style_bucket_count": 2,
                "violations": [],
            },
            "allow_lineup_quality_warnings": False,
        },
    }


def _six_player_create_request() -> dict[str, Any]:
    roles = [
        {"role": "werewolf", "count": 2, "team": "werewolves"},
        {"role": "villager", "count": 1, "team": "villagers"},
        {"role": "guard", "count": 1, "team": "villagers"},
        {"role": "seer", "count": 1, "team": "villagers"},
        {"role": "hunter", "count": 1, "team": "villagers"},
    ]
    return {
        "title": "动态首夜 6 人验收",
        "lobby_snapshot": {
            "schema_version": 1,
            "rule_set": {
                "id": "dynamic_first_night_6",
                "version": "1",
                "name": "动态首夜 6 人",
                "player_count": 6,
                "roles": roles,
                "night_actions": ["remove", "protect", "investigate"],
                "win_condition": "wolves_gte_others",
                "sheriff_enabled": False,
            },
            "rule_set_revision_id": "rule_rev_dynamic_6",
            "seed": 7,
            "max_rounds": 8,
            "player_configs": [
                {
                    "seat": seat,
                    "profile_id": f"dynamic-player-{seat}",
                    "name": f"玩家{seat}",
                    "personality": f"这是玩家{seat}的独立性格。",
                    "tts_speaker": f"speaker-{seat}",
                }
                for seat in range(1, 7)
            ],
            "lineup_quality_report": {
                "schema_version": 1,
                "policy_mode": "observe",
                "player_count": 6,
                "configured_count": 6,
                "is_blocked": False,
                "was_repaired": False,
                "style_bucket_count": 6,
                "required_style_bucket_count": 3,
                "violations": [],
            },
            "allow_lineup_quality_warnings": False,
        },
    }


def _advanced_create_request() -> dict[str, Any]:
    roles = [
        {"role": "werewolf", "count": 4, "team": "werewolves"},
        {"role": "villager", "count": 4, "team": "villagers"},
        {"role": "seer", "count": 1, "team": "villagers"},
        {"role": "witch", "count": 1, "team": "villagers"},
        {"role": "hunter", "count": 1, "team": "villagers"},
        {"role": "idiot", "count": 1, "team": "villagers"},
    ]
    return {
        "title": "进阶十二人首夜验收",
        "lobby_snapshot": {
            "schema_version": 1,
            "rule_set": {
                "id": "classic_12_seer_witch_hunter_idiot",
                "version": "1",
                "name": "经典十二人",
                "player_count": 12,
                "roles": roles,
                "night_actions": [
                    "remove",
                    "investigate",
                    "witch_save",
                    "witch_poison",
                ],
                "win_condition": "wolves_gte_others",
                "sheriff_enabled": True,
            },
            "rule_set_revision_id": "rule_rev_advanced_12",
            "seed": 12,
            "max_rounds": 12,
            "player_configs": [
                {
                    "seat": seat,
                    "profile_id": f"advanced-player-{seat}",
                    "name": f"进阶玩家{seat}",
                    "personality": f"进阶玩家{seat}会独立权衡风险。",
                    "tts_speaker": f"speaker-{seat}",
                }
                for seat in range(1, 13)
            ],
            "lineup_quality_report": {
                "schema_version": 1,
                "policy_mode": "observe",
                "player_count": 12,
                "configured_count": 12,
                "is_blocked": False,
                "was_repaired": False,
                "style_bucket_count": 8,
                "required_style_bucket_count": 3,
                "violations": [],
            },
            "allow_lineup_quality_warnings": False,
        },
    }
