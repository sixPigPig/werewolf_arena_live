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
from app.judge_configuration import configuration_from_voice_snapshot
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.game_session import GameSessionRecord
from app.models.judge_configuration import JudgeConfigurationRecord
from app.models.live import LiveRunRecord
from app.models.model_configuration import ModelConfigurationRecord
from app.models.user import User
from app.v2.live_runtime import V2LiveRuntime, _GameChannel
from app.v2.day_engine import V2DayEngine, _leaders
from app.v2.match_repository import V2MatchRepository
from app.v2.model_client import (
    V2ModelDecision,
    V2ModelTarget,
    V2QualityError,
    build_model_request_payload,
)
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
    V2MatchState,
    V2PlayerState,
    V2RoleAssignment,
    V2RoleAssignmentBatch,
    V2VoiceAsset,
)


PCM_CHUNK = b"\x10\x00" * 240


def _nested_strings(value: Any) -> Generator[str, None, None]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _nested_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nested_strings(item)
    elif isinstance(value, str):
        yield value


class FakeV2ModelClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.contexts: list[dict[str, Any]] = []
        self.release = threading.Event()
        self.release.set()
        self.decision_contexts: list[dict[str, Any]] = []
        self.decline_action_types: set[str] = set()
        self.quality_failure_action_types: set[str] = set()
        self.unexpected_speech_target: str | None = None
        self.speech_by_action_type: dict[str, str] = {}

    def resolve_model_target(
        self,
        *,
        model_provider: str,
        model_id: str,
        model_parameters: dict[str, Any],
    ) -> V2ModelTarget:
        assert model_provider == "agent_plan"
        return V2ModelTarget(
            provider=model_provider,
            model_id=model_id,
            parameters=dict(model_parameters),
        )

    def build_request_payload(
        self,
        *,
        action_context: dict[str, Any],
        decision: bool,
        target: V2ModelTarget,
    ) -> dict[str, Any]:
        return build_model_request_payload(
            action_context,
            decision=decision,
            model_id=target.model_id,
            parameters=target.parameters,
        )

    async def generate_action_decision(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        target: V2ModelTarget,
        check_cancellation: Any = None,
    ) -> V2ModelDecision:
        if check_cancellation is not None:
            check_cancellation()
        self.call_count += 1
        self.contexts.append(action_context)
        self.decision_contexts.append(action_context)
        assert attempt_id.startswith("v2_model_")
        assert target.provider == "agent_plan"
        assert target.model_id in {"private-model-id", "test-model"}
        action_type = action_context["task"]["action_type"]
        if action_type in self.quality_failure_action_types:
            boolean_field = action_context["output_contract"].get("field")
            raise V2QualityError(
                "model_decision_invalid_speech",
                raw_response=json.dumps(
                    {boolean_field or "decision": True},
                    separators=(",", ":"),
                ),
            )
        candidates = action_context["candidates"]
        output_contract = action_context["output_contract"]
        boolean_field: str | None = None
        boolean_value: bool | None = None
        speech: str | None = self.speech_by_action_type.get(
            action_type,
            "我先说明自己的判断。这是第二句话！\n现在执行这次实时决策。",
        )
        if output_contract["kind"] == "boolean":
            boolean_field = output_contract["field"]
            boolean_value = action_type not in self.decline_action_types
            target = None
            if not boolean_value and output_contract["speech"]["mode"] == "required_if_true":
                speech = None
        elif action_type in self.decline_action_types:
            target = None
        elif candidates:
            target = candidates[0]["player_id"]
        elif output_contract["kind"] == "speech":
            target = self.unexpected_speech_target
        else:
            target = None
        raw_output = (
            {
                boolean_field: boolean_value,
                **({"speech": speech} if speech is not None else {}),
            }
            if boolean_field is not None
            else {
                "target_player_id": target,
                "speech": speech,
            }
        )
        return V2ModelDecision(
            target_player_id=target,
            speech=speech,
            provider_request_id="provider-decision-test",
            first_token_ms=11,
            completed_ms=29,
            raw_response=json.dumps(raw_output, ensure_ascii=False),
            boolean_field=boolean_field,
            boolean_value=boolean_value,
        )


class FakeV2TtsClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.speakers: list[str | None] = []
        self.dialects: list[str | None] = []
        self.first_chunk = threading.Event()
        self.release = threading.Event()
        self.release.set()

    async def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
        speaker: str | None = None,
        dialect: str | None = None,
        check_cancellation: Any = None,
    ) -> AsyncIterator[bytes]:
        self.call_count += 1
        self.speakers.append(speaker)
        self.dialects.append(dialect)
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


class _ScriptedDayActionEngine:
    def __init__(self, targets: dict[str, str | None]) -> None:
        self.targets = targets
        self.player_actions: list[str] = []
        self.judge_actions: list[str] = []

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision(self, *, spec, **_kwargs) -> V2ModelDecision:
        self.player_actions.append(spec.actor_id)
        return V2ModelDecision(
            target_player_id=self.targets[spec.actor_id],
            speech="我决定发动技能。",
            provider_request_id="provider-scripted-decision",
            first_token_ms=1,
            completed_ms=2,
        )

    async def run_judge_speech(self, *, spec, **_kwargs) -> bool:
        self.judge_actions.append(spec.action_type)
        return True


class _CollectingBroadcaster:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []

    async def broadcast_json(self, value: dict[str, Any], *, audience: str = "all") -> None:
        self.messages.append((audience, value))


class _BlockingWebSocket:
    def __init__(self, *, block_audio: bool = False) -> None:
        self.block_audio = block_audio
        self.audio_started = asyncio.Event()
        self.release_audio = asyncio.Event()
        self.json_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []

    async def send_json(self, value: dict[str, Any]) -> None:
        self.json_messages.append(value)

    async def send_bytes(self, value: bytes) -> None:
        self.audio_started.set()
        if self.block_audio:
            await self.release_audio.wait()
        self.binary_messages.append(value)


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
    with testing_session.begin() as db:
        for model_id in ("private-model-id", "test-model"):
            db.add(
                ModelConfigurationRecord(
                    provider="agent_plan",
                    model_id=model_id,
                    source_model_id=model_id,
                    display_name=model_id,
                    available=True,
                    enabled=True,
                    is_default=model_id == "test-model",
                    supports_thinking=True,
                    parameter_values={
                        "thinking": "disabled",
                        "max_tokens": 512,
                    },
                    source_details={"source": "test"},
                )
            )

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    model_client = FakeV2ModelClient()
    tts_client = FakeV2TtsClient()

    def judge_configuration_provider(game_id: str):
        with testing_session() as db:
            game = db.get(V2GameRecord, game_id)
            assert game is not None
            configuration = configuration_from_voice_snapshot(game.judge_voice_snapshot)
            assert configuration is not None
            return configuration

    application.state.v2_live_runtime = V2LiveRuntime(
        session_factory=testing_session,
        model_client=model_client,
        tts_client=tts_client,
        voice_root=voice_root,
        sample_rate=24000,
        judge_configuration_provider=judge_configuration_provider,
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
        "status": "realtime_complete_match",
    }
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/health").status_code == 200


def test_existing_mobile_lobby_creates_one_waiting_v2_game_with_snapshots(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context

    response = client.post("/api/v2/games", json=_lobby_create_request())

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "waiting_to_start"
    assert created["game_id"].startswith("v2_game_")
    assert created["run_id"].startswith("v2_run_")
    assert created["websocket_url"].endswith(f"/{created['game_id']}/ws")
    assert created["director_snapshot_url"].endswith(f"/{created['game_id']}/snapshot")
    assert created["director_websocket_url"].endswith(f"/{created['game_id']}/ws")
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
        assert game.status == "waiting_to_start"
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
        assert game.judge_voice_snapshot == {
            "schema_version": 1,
            "voice_mode": "fixed",
            "selected_tts_speaker": "zh_female_vv_uranus_bigtts",
            "random_tts_speakers": [],
            "configuration_version": 0,
        }
        assert [
            {key: value for key, value in item.items() if key != "model_configuration_updated_at"}
            for item in game.players_snapshot
        ] == [
            {
                "seat": 1,
                "profile_id": "profile-1",
                "name": "阿青",
                "model_provider": "agent_plan",
                "model": "private-model-id",
                "model_parameters": {
                    "thinking": "disabled",
                    "max_tokens": 512,
                },
                "personality": "private personality prompt",
                "avatar_image_url": "/api/v1/public/player-profiles/profile-1/avatar",
                "strategy_profile": "private-strategy",
                "tts_speaker": "private-speaker",
            },
            {
                "seat": 2,
                "profile_id": "profile-2",
                "name": "白石",
                "model_provider": "agent_plan",
                "model": "test-model",
                "model_parameters": {
                    "thinking": "disabled",
                    "max_tokens": 512,
                },
            },
        ]
        assert all(item["model_configuration_updated_at"] for item in game.players_snapshot)
        assert run is not None and run.status == "waiting_to_start"
        assert run.started_at is None
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
            "judge_voice": game.judge_voice_snapshot,
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
        "match_state",
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
    assert snapshot.json()["live_state"] == "waiting_to_start"
    assert snapshot.json()["match_state"] == {
        "round_no": 1,
        "sheriff_player_id": None,
        "sheriff_badge_state": "disabled",
        "winner": None,
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

    director = client.get(created["director_snapshot_url"])
    assert director.status_code == 200, director.text
    assert director.headers["cache-control"] == "private, no-store"
    director_payload = director.json()
    assert set(director_payload) == {
        "protocol_version",
        "type",
        "api_version",
        "audience",
        "game_id",
        "run_id",
        "live_state",
        "game_phase",
        "match_state",
        "latest_presentation_seq",
        "server_time",
        "rule",
        "players",
        "current_scene",
        "current_presentation",
    }
    assert director_payload["type"] == "director.live_snapshot"
    assert director_payload["audience"] == "spectator_directed"
    assert director_payload["current_scene"] == {
        "scene_kind": "opening",
        "action_id": None,
        "action_type": None,
        "ability_id": None,
        "actor_player_id": None,
    }
    assert [item["role"] for item in director_payload["players"]]
    serialized_director = json.dumps(director_payload)
    assert "private-model-id" not in serialized_director
    assert "private personality prompt" not in serialized_director
    assert "private-strategy" not in serialized_director
    assert "private-speaker" not in serialized_director

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
        "match_state",
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


def test_director_websocket_starts_with_its_own_ready_contract(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_lobby_create_request()).json()
    model_client = client.app.state.v2_test_model_client
    model_client.release.clear()

    with client.websocket_connect(created["director_websocket_url"]) as socket:
        initial = socket.receive_json()
        assert initial["type"] == "director.live_snapshot"
        assert initial["audience"] == "spectator_directed"
        assert initial["live_state"] == "waiting_to_start"
        assert [item["role"] for item in initial["players"]]

        socket.send_json(_ready_message("director.ready"))
        started = socket.receive_json()
        assert started["type"] == "director.live_snapshot"
        assert started["audience"] == "spectator_directed"
        assert started["live_state"] == "ready"


def test_public_and_god_view_share_two_realtime_actions_without_replay(
    v2_context,
) -> None:
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
            assert public_initial["live_state"] == "waiting_to_start"
            assert god_initial["live_state"] == "waiting_to_start"
            assert [item["role"] for item in god_initial["players"]]
            assert identifiers["god_view_access_token"] not in json.dumps(god_initial)

            god_socket.send_json(_ready_message("god_view.ready"))
            god_started = god_socket.receive_json()
            assert god_started["type"] == "god_view.live_snapshot"
            assert god_started["live_state"] == "ready"
            public_socket.send_json(_ready_message("client.ready"))
            public_started = public_socket.receive_json()
            assert public_started["type"] == "live.snapshot"
            assert public_started["live_state"] in {
                "ready",
                "generating",
                "broadcasting",
            }
            model_client.release.set()

            public_result = _receive_realtime_action(public_socket)
            god_result = _receive_realtime_action(god_socket)

    expected_texts = [
        "欢迎来到经典 8 人。本局共2名玩家，对局现在开始。",
        "首夜开始，请所有玩家闭眼。",
    ]
    assert god_result == {
        "committed_texts": expected_texts,
        "presentation_seqs": [1, 2],
        "phase_changes": ["first_night"],
        "audio_chunks": 4,
        "awaiting_observation": True,
    }
    assert public_result["committed_texts"][-1] == expected_texts[-1]
    assert public_result["presentation_seqs"][-1] == 2
    assert public_result["phase_changes"] == ["first_night"]
    assert public_result["awaiting_observation"] is True
    assert model_client.call_count == 0
    assert tts_client.call_count == 2
    assert tts_client.speakers == [
        "zh_female_vv_uranus_bigtts",
        "zh_female_vv_uranus_bigtts",
    ]
    assert model_client.contexts == []
    with session_factory() as db:
        run = db.get(V2GameRun, identifiers["run_id"])
        assert run is not None and run.started_at is not None
        started_event = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == identifiers["game_id"],
                V2GameRecordEvent.event_type == "game_started",
            )
        )
        assert started_event is not None
        assert started_event.payload["trigger_audience"] == "spectator_god_view"
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "game_started",
                )
            )
            == 1
        )
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
                .select_from(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "judge_speech_rendered",
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


def test_join_sample_cursor_is_atomic_with_audio_broadcast() -> None:
    async def scenario() -> None:
        channel = _GameChannel(
            game_id="v2_game_0123456789abcdef",
            snapshot_factory=lambda **values: {
                "live_state": "failed",
                "current_presentation": {
                    "join_sample_cursor": values["sample_cursor"],
                },
            },
            game_starter=lambda **_values: False,
            engine=object(),  # type: ignore[arg-type]
        )
        first = _BlockingWebSocket(block_audio=True)
        first_id = await channel.connect(  # type: ignore[arg-type]
            first,
            audience="player_public",
        )
        await channel.ready(first_id, _ready_message("client.ready"))
        audio_task = asyncio.create_task(
            channel.broadcast_audio(
                b"first-frame",
                identity=object(),  # type: ignore[arg-type]
                next_sample_cursor=240,
            )
        )
        await first.audio_started.wait()

        second = _BlockingWebSocket()
        join_task = asyncio.create_task(
            channel.connect(second, audience="player_public")  # type: ignore[arg-type]
        )
        await asyncio.sleep(0)
        assert not join_task.done()
        first.release_audio.set()
        await audio_task
        second_id = await join_task

        assert second.json_messages[0]["current_presentation"]["join_sample_cursor"] == 240
        assert second.binary_messages == []
        await channel.ready(second_id, _ready_message("client.ready"))
        await channel.broadcast_audio(
            b"second-frame",
            identity=object(),  # type: ignore[arg-type]
            next_sample_cursor=480,
        )
        assert second.binary_messages == [b"second-frame"]

    asyncio.run(scenario())


def test_director_channel_receives_public_and_private_stage_events() -> None:
    async def scenario() -> None:
        channel = _GameChannel(
            game_id="v2_game_0123456789abcdef",
            snapshot_factory=lambda **values: {
                "live_state": "failed",
                "audience": values["audience"],
            },
            game_starter=lambda **_values: False,
            engine=object(),  # type: ignore[arg-type]
        )
        public = _BlockingWebSocket()
        director = _BlockingWebSocket()
        god = _BlockingWebSocket()
        public_id = await channel.connect(public, audience="player_public")  # type: ignore[arg-type]
        director_id = await channel.connect(  # type: ignore[arg-type]
            director,
            audience="spectator_directed",
        )
        god_id = await channel.connect(god, audience="spectator_god_view")  # type: ignore[arg-type]
        await channel.ready(public_id, _ready_message("client.ready"))
        await channel.ready(director_id, _ready_message("director.ready"))
        await channel.ready(god_id, _ready_message("god_view.ready"))
        public.json_messages.clear()
        director.json_messages.clear()
        god.json_messages.clear()

        public_event = {"type": "public"}
        private_event = {"type": "private"}
        director_event = {"type": "director"}
        await channel.broadcast_json(public_event, audience="public")
        await channel.broadcast_json(private_event, audience="god_view")
        await channel.broadcast_json(director_event, audience="director")

        assert public.json_messages == [public_event]
        assert director.json_messages == [
            public_event,
            private_event,
            director_event,
        ]
        assert god.json_messages == [private_event]

    asyncio.run(scenario())


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


def test_public_viewer_click_starts_game_then_receives_opening_and_nightfall(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    created = client.post("/api/v2/games", json={"title": "首句实时验收"})
    assert created.status_code == 201, created.text
    identifiers = created.json()
    game_id = identifiers["game_id"]

    snapshot = client.get(identifiers["snapshot_url"])
    assert snapshot.status_code == 200
    assert snapshot.json()["live_state"] == "waiting_to_start"
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
        assert websocket.receive_json()["live_state"] == "waiting_to_start"
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
        started_snapshot = websocket.receive_json()
        assert started_snapshot["type"] == "live.snapshot"
        assert started_snapshot["live_state"] == "ready"
        result = _receive_realtime_action(websocket, include_audio_headers=True)
        assert result["committed_texts"] == [
            "欢迎来到本场实时狼人杀对局。对局现在开始。",
            "首夜开始，请所有玩家闭眼。",
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
        assert [header["chunk_index"] for header in result["audio_headers"]] == [
            0,
            1,
            0,
            1,
        ]
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
        assert run.started_at is not None
        assert [item.event_type for item in events] == [
            "game_created",
            "game_started",
            "action_opened",
            "judge_speech_rendered",
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
            "judge_speech_rendered",
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
        started_event = next(item for item in events if item.event_type == "game_started")
        assert started_event.payload["trigger_audience"] == "player_public"
        assert [item.phase_id for item in presentations] == ["opening", "first_night"]
        assert all(item.state == "closed" for item in presentations)
        assert len(voices) == 2
        assert all(item.state == "ready" and item.sample_count == 480 for item in voices)
        assert all(item.pcm_sha256 == hashlib.sha256(PCM_CHUNK * 2).hexdigest() for item in voices)
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
    assert body["model_requests"] == []
    template_events = [
        item for item in body["events"] if item["event_type"] == "judge_speech_rendered"
    ]
    assert [item["payload"]["template_id"] for item in template_events] == [
        "judge_opening_speech",
        "judge_nightfall_announcement",
    ]
    assert all(
        item["payload"]["tts_speaker"] == "zh_female_vv_uranus_bigtts" for item in template_events
    )
    assert body["judge_voice_snapshot"]["selected_tts_speaker"] == ("zh_female_vv_uranus_bigtts")
    assert len(body["voice_assets"]) == 2
    for voice in body["voice_assets"]:
        assert voice["state"] == "ready"
        assert voice["pcm_sha256"] == hashlib.sha256(PCM_CHUNK * 2).hexdigest()
        assert voice["audio_url"].startswith("/api/v1/admin/v2/games/")
        audio = client.get(voice["audio_url"])
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert audio.content[:4] == b"RIFF"


def test_random_judge_voice_is_frozen_per_game_before_runtime_actions(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    tts_client = client.app.state.v2_test_tts_client
    configured_pool = ["judge-random-a", "judge-random-b"]
    with session_factory.begin() as db:
        db.add(
            JudgeConfigurationRecord(
                id="default",
                voice_mode="random",
                tts_speaker=configured_pool[0],
                random_tts_speakers=configured_pool,
                version=4,
            )
        )

    identifiers = client.post(
        "/api/v2/games",
        json={"title": "每局随机音色冻结"},
    ).json()
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None
        selected = game.judge_voice_snapshot["selected_tts_speaker"]
        assert selected in configured_pool
        assert game.judge_voice_snapshot["voice_mode"] == "random"
        assert game.judge_voice_snapshot["configuration_version"] == 4
        configured = db.get(JudgeConfigurationRecord, "default")
        assert configured is not None
        configured.voice_mode = "fixed"
        configured.tts_speaker = "judge-changed-after-creation"
        configured.random_tts_speakers = []
        configured.version = 5

    _run_opening_to_nightfall(client, identifiers["websocket_url"])

    assert tts_client.speakers == [selected, selected]
    with session_factory() as db:
        rendered = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "judge_speech_rendered",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert len(rendered) == 2
        assert all(item.payload["tts_speaker"] == selected for item in rendered)


def test_admin_v2_record_exposes_complete_private_identity_table(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    identifiers = client.post(
        "/api/v2/games",
        json=_lobby_create_request(),
    ).json()
    session = client.post("/api/v1/admin/dev-login")
    assert session.status_code == 200, session.text

    detail = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")

    assert detail.status_code == 200, detail.text
    identities = detail.json()["player_identities"]
    assert len(identities) == 2
    assert [
        {
            "seat": item["seat"],
            "player_id": item["player_id"],
            "display_name": item["display_name"],
            "alive": item["alive"],
            "death_cause": item["death_cause"],
        }
        for item in identities
    ] == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "alive": True,
            "death_cause": None,
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "白石",
            "alive": True,
            "death_cause": None,
        },
    ]
    assert {item["role"] for item in identities} == {"villager", "werewolf"}
    assert {item["team"] for item in identities} == {"village", "werewolves"}
    serialized = json.dumps(identities)
    assert "private-model-id" not in serialized
    assert "private personality prompt" not in serialized
    assert "private-speaker" not in serialized


def test_admin_operator_can_idempotently_stop_waiting_v2_game_without_private_leak(
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
        idempotency_key="v2-stop-waiting-1",
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
        assert db.scalar(select(func.count()).select_from(V2GameControlRequest)) == 1
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
            db.scalars(select(V2LivePresentation).where(V2LivePresentation.game_id == game.game_id))
        )
        voices = list(db.scalars(select(V2VoiceAsset).where(V2VoiceAsset.game_id == game.game_id)))
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
    assert client.app.state.v2_test_model_client.call_count == 0
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


def test_admin_operator_cannot_stop_terminal_v2_game(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json={"title": "已结束对局"}).json()
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        assert game is not None and run is not None
        game.status = "awaiting_observation"
        run.status = "awaiting_observation"

    response = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": "不应覆盖已完成对局"},
        headers=_operator_control_headers(
            client,
            session_factory,
            idempotency_key="v2-stop-terminal-1",
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "admin_v2_game_not_active"
    with session_factory() as db:
        run = db.get(V2GameRun, identifiers["run_id"])
        assert run is not None and run.stop_requested_at is None


def test_executable_rule_runs_dynamic_first_night_without_leaking_private_actions(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    tts_client = client.app.state.v2_test_tts_client
    create_request = _six_player_create_request()
    for profile in create_request["lobby_snapshot"]["player_configs"]:
        profile["tts_speaker"] = "zh_female_vv_uranus_bigtts"
        profile["tts_dialect"] = "sichuan"
    created = client.post("/api/v2/games", json=create_request)
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
        "欢迎来到动态首夜 6 人。本局共6名玩家，对局现在开始。",
        "首夜开始，请所有玩家闭眼。",
    ]
    assert any(text.startswith("天亮了，昨夜") for text in public_texts)
    assert "第1天白天讨论现在开始，请存活玩家按照发言顺序依次发言。" in public_texts
    assert "第1天白天讨论现在开始，请存活玩家按照发言顺序依次发言。" in god_texts
    assert "这项首夜能力现在开始实时执行。" not in public_texts
    assert "night.progress_changed" in public_types
    assert "ability.progress_changed" not in public_types
    assert "god_view.night_resolved" not in public_types
    assert "ability.progress_changed" in god_types
    assert "god_view.night_resolved" in god_types
    assert "night.progress_changed" not in god_types
    assert "狼人请睁眼，请依次商议今晚的袭击目标。" in god_texts
    assert "我先说明自己的判断。这是第二句话！\n现在执行这次实时决策。" in god_texts
    assert "sichuan" in tts_client.dialects
    player_contexts = model_client.decision_contexts
    assert player_contexts
    assert any(context["task"]["action_type"].startswith("ability_") for context in player_contexts)
    assert any(context["task"]["action_type"] == "day_debate_speech" for context in player_contexts)
    assert all(
        context["hard_rules"]["player_count"] == 6
        and context["hard_rules"]["werewolf_count"] == 2
        and context["hard_rules"]["sheriff"]["enabled"] is False
        for context in player_contexts
    )
    assert all(
        context["prompt_schema_version"] == 2
        and "private_judge_facts" in context["self"]
        and "ability_runtime_state" in context["self"]
        and "mechanical_effect" in context["task"]
        and "public_state" in context
        and "history" in context
        and "role_information_boundaries" not in context
        and "canonical_public_timeline" not in context
        and "public_event_counters" not in context
        and "information_semantics" not in context
        and "public_rules" not in context
        and "allowed_knowledge" not in context
        for context in player_contexts
    )
    assert all(
        "knowledge" not in context["self"]["identity"]
        for context in player_contexts
        if context["self"].get("identity")
    )
    seer_contexts = [
        context
        for context in player_contexts
        if context.get("self", {}).get("identity", {}).get("role_key") == "seer"
    ]
    assert seer_contexts
    assert all(
        [item["ability_id"] for item in context["self"]["role_capabilities"]["abilities"]]
        == ["seer.investigate"]
        for context in seer_contexts
    )
    surviving_seer_day_contexts = [
        context
        for context in seer_contexts
        if not context["task"]["action_type"].startswith("ability_")
    ]
    if surviving_seer_day_contexts:
        assert any(
            fact.get("fact_type") == "investigation_alignment"
            for context in surviving_seer_day_contexts
            for fact in context["self"]["private_judge_facts"]
        )
    contexts_after_heal_use = [
        context
        for context in player_contexts
        if any(
            fact.get("fact_type") == "private_ability_action_committed"
            and fact.get("payload", {}).get("ability_id") == "witch.heal"
            and fact.get("payload", {}).get("result", {}).get("heal_used") is True
            for fact in context["self"]["private_judge_facts"]
        )
    ]
    if contexts_after_heal_use:
        assert all(
            next(
                item
                for item in context["self"]["ability_runtime_state"]["abilities"]
                if item["ability_id"] == "witch.heal"
            )["resource_status"]
            == "consumed"
            for context in contexts_after_heal_use
        )
    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None
        assert game.status == "awaiting_observation"
        assert game.phase_id.startswith("day_")
        assert game.phase_state == "game_completed"
        opening_event = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == game.game_id,
                V2GameRecordEvent.event_type == "action_opened",
                V2GameRecordEvent.payload["context"]["action_type"].as_string()
                == "judge_opening_speech",
            )
        )
        assert opening_event is not None
        assert opening_event.payload["context"]["game_setup"] == {
            "rule_name": "动态首夜 6 人",
            "player_count": 6,
            "role_summary": None,
            "max_rounds": 8,
        }
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
            db.scalars(select(V2EffectIntent).where(V2EffectIntent.game_id == game.game_id))
        )
        assert {item.effect_type for item in effects} >= {
            "attack",
            "protect",
            "investigate",
        }
        assert all(item.state == "resolved" for item in effects if item.effect_type != "shoot")
        facts = list(
            db.scalars(select(V2KnowledgeFact).where(V2KnowledgeFact.game_id == game.game_id))
        )
        assert len(facts) >= 5
        assert sum(item.fact_type == "investigation_alignment" for item in facts) >= 1
        assert sum(item.fact_type == "private_ability_action_committed" for item in facts) >= 4
        assert all(
            item.payload["resolution_scope"].startswith("法官已接受本次私有动作")
            for item in facts
            if item.fact_type == "private_ability_action_committed"
        )
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
        assert all(
            item.activation_id is not None
            for item in presentations
            if item.actor_kind == "player"
            and (item.phase_id == "first_night" or item.phase_id.startswith("night_"))
        )


def test_single_wolf_no_sheriff_rule_reaches_day_and_night_model_inputs(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    contradictory_speech = "我判断1号和2号是双狼，今天先出1号。"
    model_client.speech_by_action_type["day_debate_speech"] = contradictory_speech
    request = _six_player_create_request()
    request["lobby_snapshot"]["rule_set"]["roles"] = [
        {"role": "werewolf", "count": 1, "team": "werewolves"},
        {"role": "seer", "count": 1, "team": "villagers"},
        {"role": "guard", "count": 1, "team": "villagers"},
        {"role": "villager", "count": 3, "team": "villagers"},
    ]
    created = client.post("/api/v2/games", json=request)
    assert created.status_code == 201, created.text
    identifiers = created.json()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        _collect_until_observation(
            websocket,
            message_types=[],
            committed_texts=[],
        )

    contexts = model_client.decision_contexts
    assert all(
        "wolf_cardinality_contradiction"
        not in json.dumps(context, ensure_ascii=False)
        for context in contexts
    )
    night_contexts = [
        context for context in contexts if context["task"]["action_type"].startswith("ability_")
    ]
    day_contexts = [
        context for context in contexts if context["task"]["action_type"] == "day_debate_speech"
    ]
    assert night_contexts
    assert day_contexts
    assert all(
        context["hard_rules"]["werewolf_count"] == 1
        and context["hard_rules"]["reveal_policy"] == "hidden"
        and "不会公开其身份或阵营" in context["hard_rules"]["role_reveal_rule"]
        and context["hard_rules"]["sheriff"]["enabled"] is False
        and context["hard_rules"]["ability_rules"]["werewolf_attack"]["can_target_self"] is False
        and context["hard_rules"]["ability_rules"]["werewolf_attack"]["coordination"] == "solo"
        and "can_target_werewolf_teammates"
        not in context["hard_rules"]["ability_rules"]["werewolf_attack"]
        for context in contexts
    )
    assert all(
        context["public_state"]["alive_player_count"]
        == len(context["public_state"]["alive_player_ids"])
        and context["public_state"]["eliminated_player_count"]
        == len(context["public_state"]["eliminated_player_ids"])
        and context["public_state"]["identity_information_included"] is False
        for context in contexts
    )
    wolf_night_contexts = [
        context
        for context in night_contexts
        if context["task"].get("ability_id") == "werewolf.attack"
    ]
    assert wolf_night_contexts
    assert all(
        context["self"]["werewolf_coordination"] == {"mode": "solo"}
        and all(
            fact.get("fact_type")
            not in {"werewolf_teammates", "living_werewolf_teammates"}
            for fact in context["self"]["private_judge_facts"]
        )
        for context in wolf_night_contexts
    )
    assert all(
        any(
            fact.get("fact_type") == "coordination"
            and fact.get("payload") == "solo"
            for fact in context["self"]["private_judge_facts"]
        )
        for context in wolf_night_contexts
    )
    assert any(
        fact.get("fact_type") == "private_ability_action_committed"
        for context in wolf_night_contexts
        for fact in context["self"]["private_judge_facts"]
    )
    seer_day_contexts = [
        context for context in day_contexts if context["self"]["identity"]["role_key"] == "seer"
    ]
    assert seer_day_contexts
    assert any(
        fact.get("fact_type") == "investigation_alignment"
        for context in seer_day_contexts
        for fact in context["self"]["private_judge_facts"]
    )
    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        model_request_events = [
            event for event in events if event.event_type == "model_request_started"
        ]
        assert model_request_events
        assert all(
            event.payload["prompt_schema_version"] == 2
            and event.payload["prompt_projection"]["serialized_char_count"]
            < 15_000
            for event in model_request_events
        )
        observed_responses = [
            event
            for event in events
            if event.event_type == "model_response_received"
            and event.payload.get("parsed_output", {}).get("speech") == contradictory_speech
        ]
        assert observed_responses
        observed_action_ids = {event.payload["action_id"] for event in observed_responses}
        assert all(
            event.payload["passive_observations"][0]["code"] == "wolf_cardinality_contradiction"
            and event.payload["passive_observations"][0]["effect"] == "observed_only"
            for event in observed_responses
        )
        assert all(
            sum(
                event.event_type == "model_request_started"
                and event.payload.get("action_id") == action_id
                for event in events
            )
            == 1
            and sum(
                event.event_type == "model_response_received"
                and event.payload.get("action_id") == action_id
                for event in events
            )
            == 1
            for action_id in observed_action_ids
        )
        adopted_presentations = list(
            db.scalars(
                select(V2LivePresentation).where(
                    V2LivePresentation.game_id == identifiers["game_id"],
                    V2LivePresentation.action_id.in_(observed_action_ids),
                )
            )
        )
        assert {
            presentation.action_id for presentation in adopted_presentations
        } == observed_action_ids
        assert all(
            presentation.subtitle_text == contradictory_speech
            for presentation in adopted_presentations
        )


def test_advanced_rule_opens_sheriff_election_after_first_night(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.decline_action_types.add("ability_witch.heal_decision")
    model_client.decline_action_types.add("werewolf_self_explosion")
    model_client.decline_action_types.add("exile_vote")
    model_client.unexpected_speech_target = "model-added-irrelevant-target"
    request = _advanced_create_request()
    request["lobby_snapshot"]["rule_set"]["werewolf_self_explosion_enabled"] = True
    created = client.post("/api/v2/games", json=request)
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
            if value.get("live_state") in {"awaiting_observation", "failed"}:
                break

    assert "ability.progress_changed" not in public_types
    assert "god_view.night_resolved" not in public_types
    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None
        assert game.phase_id.startswith("day_")
        assert game.phase_state == "game_completed"
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "judge_speech_rendered",
                    V2GameRecordEvent.payload["template_id"].as_string()
                    == "judge_sheriff_election_opening",
                )
            )
            == 1
        )
        judge_speeches = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "judge_speech_rendered",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        dawn = next(
            item
            for item in judge_speeches
            if item.payload["template_id"] == "judge_dawn_announcement"
        )
        discussion = next(
            item
            for item in judge_speeches
            if item.payload["template_id"] == "judge_public_discussion_opening"
        )
        assert all("进阶玩家" not in item.payload["text"] for item in judge_speeches)
        assert dawn.record_seq < discussion.record_seq
        assert dawn.payload["action_id"] != discussion.payload["action_id"]
        assert "白天讨论现在开始" not in dawn.payload["text"]
        assert "平安夜" not in discussion.payload["text"]
        if "出局" in dawn.payload["text"]:
            assert "平安夜" not in dawn.payload["text"]
        sheriff_run_contexts = [
            context
            for context in model_client.decision_contexts
            if context["task"]["action_type"] == "sheriff_run"
        ]
        assert sheriff_run_contexts
        assert all(
            context["output_contract"]["kind"] == "boolean"
            and context["output_contract"]["field"] == "run_for_sheriff"
            and context["output_contract"]["speech"]["mode"] == "required"
            for context in sheriff_run_contexts
        )
        withdraw_contexts = [
            context
            for context in model_client.decision_contexts
            if context["task"]["action_type"] == "sheriff_withdraw"
        ]
        assert withdraw_contexts
        assert all(
            context["candidates"] == []
            and context["output_contract"]
            == {
                "kind": "boolean",
                "presentation_kind": "sheriff_withdraw_decision",
                "language": "zh-CN",
                "speech": {
                    "type": "string",
                    "mode": "required",
                    "min_length": 1,
                },
                "field": "withdraw",
                "required_fields": ["withdraw", "speech"],
                "boolean": {
                    "type": "boolean",
                    "true_means": "退水",
                    "false_means": "不退水",
                },
            }
            for context in withdraw_contexts
        )
        withdraw_events = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "sheriff_withdraw_decided",
                )
            )
        )
        withdraw_responses = [
            event
            for event in db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "model_response_received",
                )
            )
            if isinstance(event.payload.get("parsed_output"), dict)
            and isinstance(event.payload["parsed_output"].get("withdraw"), bool)
        ]
        assert withdraw_events
        assert len(withdraw_responses) == len(withdraw_events)
        assert all(event.payload["withdrew"] is True for event in withdraw_events)
        assert all(
            event.payload["parsed_output"]["withdraw"] is True for event in withdraw_responses
        )
        self_explosion_responses = [
            event
            for event in db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "model_response_received",
                )
            )
            if isinstance(event.payload.get("parsed_output"), dict)
            and event.payload["parsed_output"].get("explode") is False
        ]
        assert self_explosion_responses
        silent_action_ids = {event.payload["action_id"] for event in self_explosion_responses}
        action_events = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                )
            )
        )
        assert all(
            not (
                event.event_type in {"speech_opened", "tts_stream_started"}
                and event.payload.get("action_id") in silent_action_ids
            )
            for event in action_events
        )
        assert silent_action_ids <= {
            event.payload["action_id"]
            for event in action_events
            if event.event_type == "action_succeeded"
            and event.payload.get("result") == "decision_recorded_without_presentation"
        }
        self_explosion_contexts = [
            context
            for context in model_client.decision_contexts
            if context["task"]["action_type"] == "werewolf_self_explosion"
        ]
        assert self_explosion_contexts
        assert all(
            context["output_contract"]["kind"] == "boolean"
            and context["output_contract"]["field"] == "explode"
            and context["output_contract"]["speech"]["mode"] == "required_if_true"
            and context["task"]["mechanical_effect"]["target_mode"] == "none"
            and context["task"]["mechanical_effect"]["if_executed"]["actor_eliminated"] is True
            and context["task"]["mechanical_effect"]["if_executed"]["target_allowed"] is False
            and context["task"]["mechanical_effect"]["if_executed"]["other_players_affected"]
            is False
            and context["task"]["mechanical_effect"]["if_executed"]["other_players_eliminated"]
            is False
            and context["task"]["mechanical_effect"]["if_executed"]["remaining_day_flow"]
            == (
                "sheriff_election_interrupted"
                if context["task"]["public_stage"] == "pre_sheriff_election"
                else "terminated"
            )
            and "不会选择、杀死或带走其他玩家" in context["task"]["objective"]
            for context in self_explosion_contexts
        )
        ability_contexts = [
            context
            for context in model_client.decision_contexts
            if context["task"]["action_type"].startswith("ability_")
        ]
        assert ability_contexts
        assert all(context["output_contract"]["kind"] == "target" for context in ability_contexts)
        assert all(
            context["output_contract"]["speech"]["mode"]
            == (
                "required"
                if context["task"]["action_type"]
                in {
                    "ability_werewolf.attack_decision",
                    "ability_hunter.death_shot_decision",
                }
                else "optional"
            )
            for context in ability_contexts
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
            item for item in activations if instances[item.ability_instance_id] == "witch.heal"
        )
        poison = next(
            item for item in activations if instances[item.ability_instance_id] == "witch.poison"
        )
        assert heal.status == "completed"
        assert heal.decision["target_player_id"] is None
        assert poison.status == "completed"
        assert poison.decision["target_player_id"] is not None
        effects = list(
            db.scalars(select(V2EffectIntent).where(V2EffectIntent.game_id == game.game_id))
        )
        attack = next(item for item in effects if item.effect_type == "attack")
        poison_effect = next(item for item in effects if item.effect_type == "poison")
        assert poison_effect.target_player_id not in {
            poison_effect.actor_id,
            attack.target_player_id,
        }
        assert poison_effect.state == "resolved"
        normalized_targets = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "model_decision_target_normalized",
                )
            )
        )
        assert any(
            event.payload["reason"] == "required_target_missing"
            and event.payload["normalized_target_player_id"] is not None
            for event in normalized_targets
        )
        assert any(
            event.payload["reason"] == "targetless_action"
            and event.payload["normalized_target_player_id"] is None
            for event in normalized_targets
        )
    assert all("influence" not in context for context in model_client.contexts)
    serialized_model_contexts = json.dumps(model_client.contexts, ensure_ascii=False)
    if "进阶玩家" in serialized_model_contexts:
        pytest.fail("player display name leaked into model context")
    if "advanced-player-" in serialized_model_contexts:
        leaked_value = next(
            value
            for context in model_client.contexts
            for value in _nested_strings(context)
            if "advanced-player-" in value
        )
        pytest.fail(f"internal player id leaked into model context: {leaked_value}")
    assert all(
        context["self"]["identity"]["player_id"].startswith("seat_")
        for context in model_client.contexts
    )
    assert all(
        candidate["player_id"].startswith("seat_")
        and candidate["display_name"] == f"{candidate['seat']}号"
        for context in model_client.contexts
        for candidate in context.get("candidates", [])
    )
    fact_contexts = [
        context
        for context in model_client.contexts
        if context.get("public_state", {}).get("judge_facts")
    ]
    assert fact_contexts
    assert all("public_history" not in context for context in fact_contexts)


def test_withdraw_quality_failure_persists_exact_raw_model_response(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.decline_action_types.update(
        {
            "ability_witch.heal_decision",
            "werewolf_self_explosion",
        }
    )
    model_client.quality_failure_action_types.add("sheriff_withdraw")
    identifiers = client.post("/api/v2/games", json=_advanced_create_request()).json()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") == "failed":
                break

    with session_factory() as db:
        failure = db.scalar(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == identifiers["game_id"],
                V2GameRecordEvent.event_type == "model_request_failed",
            )
            .order_by(V2GameRecordEvent.record_seq.desc())
        )
        assert failure is not None
        assert failure.payload["failure_code"] == "model_decision_invalid_speech"
        assert failure.payload["raw_response"] == '{"withdraw":true}'

    assert client.post("/api/v1/admin/dev-login").status_code == 200
    detail = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert detail.status_code == 200, detail.text
    failed_request = next(
        request
        for request in detail.json()["model_requests"]
        if request["status"] == "failed" and request["action_type"] == "sheriff_withdraw"
    )
    assert failed_request["failure_code"] == "model_decision_invalid_speech"
    assert failed_request["raw_response"] == '{"withdraw":true}'
    assert failed_request["output_source"] == "persisted"


def test_complete_match_vote_resolution_preserves_ties_and_sheriff_weight() -> None:
    assert _leaders({"player-a": 1.0, "player-b": 1.0}) == [
        "player-a",
        "player-b",
    ]
    assert _leaders({"player-a": 1.0, "player-b": 1.5}) == ["player-b"]
    assert _leaders({}) == []


def test_complete_match_idiot_reveal_survives_and_loses_vote(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_advanced_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory() as db:
        idiot_id = db.scalar(
            select(V2RoleAssignment.player_id).where(
                V2RoleAssignment.game_id == created["game_id"],
                V2RoleAssignment.role_key == "idiot",
            )
        )
    assert idiot_id is not None

    result = repository.resolve_exile(game_id=created["game_id"], player_id=idiot_id)

    assert result.outcome == "idiot_revealed"
    player = repository.snapshot(created["game_id"]).player(idiot_id)
    assert player.alive is True
    assert player.state["idiot_revealed"] is True
    assert player.state["can_vote"] is False


def test_complete_match_double_pre_sheriff_explosion_destroys_badge(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_advanced_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        assert game is not None and run is not None
        game.ability_snapshot = {
            **game.ability_snapshot,
            "day_policies": {
                **game.ability_snapshot["day_policies"],
                "sheriff_badge_bomb_policy": "double",
            },
        }
        game.phase_id = "day_1"
        game.phase_state = "sheriff_election_open"
        game.status = "ready"
        run.status = "ready"
        wolf_ids = list(
            db.scalars(
                select(V2RoleAssignment.player_id)
                .where(
                    V2RoleAssignment.game_id == created["game_id"],
                    V2RoleAssignment.role_key == "werewolf",
                )
                .order_by(V2RoleAssignment.seat)
                .limit(2)
            )
        )
    assert len(wolf_ids) == 2

    first = repository.record_pre_sheriff_explosion(
        game_id=created["game_id"], player_id=wolf_ids[0]
    )
    second = repository.record_pre_sheriff_explosion(
        game_id=created["game_id"], player_id=wolf_ids[1]
    )

    snapshot = repository.snapshot(created["game_id"])
    assert first == "election_interrupted"
    assert second == "badge_destroyed"
    assert snapshot.pre_sheriff_explosion_count == 2
    assert snapshot.sheriff_badge_state == "destroyed"
    assert all(not snapshot.player(player_id).alive for player_id in wolf_ids)


def test_complete_match_badge_transfer_has_distinct_audit_event(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_advanced_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory() as db:
        wolf_ids = list(
            db.scalars(
                select(V2RoleAssignment.player_id)
                .where(
                    V2RoleAssignment.game_id == created["game_id"],
                    V2RoleAssignment.role_key == "werewolf",
                )
                .order_by(V2RoleAssignment.seat)
                .limit(2)
            )
        )
    assert len(wolf_ids) == 2
    repository.set_sheriff(
        game_id=created["game_id"],
        player_id=wolf_ids[0],
        reason="elected_for_test",
    )
    repository.record_day_explosion(
        game_id=created["game_id"],
        player_id=wolf_ids[0],
        stage="test",
    )
    repository.set_sheriff(
        game_id=created["game_id"],
        player_id=wolf_ids[1],
        reason="dead_sheriff_badge_resolution",
    )

    with session_factory() as db:
        event_row = db.scalar(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "sheriff_badge_transferred",
            )
            .order_by(V2GameRecordEvent.record_seq.desc())
        )
    assert event_row is not None
    assert event_row.payload["from_player_id"] == wolf_ids[0]
    assert event_row.payload["player_id"] == wolf_ids[1]


def test_complete_match_hunter_shot_chain_resolves_every_new_death(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_advanced_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory.begin() as db:
        assignments = list(
            db.scalars(
                select(V2RoleAssignment)
                .where(V2RoleAssignment.game_id == created["game_id"])
                .order_by(V2RoleAssignment.seat)
            )
        )
        first_hunter = next(item for item in assignments if item.role_key == "hunter")
        second_hunter = next(
            item for item in assignments if item.role_key not in {"hunter", "werewolf"}
        )
        final_target = next(
            item
            for item in assignments
            if item.player_id not in {first_hunter.player_id, second_hunter.player_id}
            and item.role_key != "werewolf"
        )
        second_hunter.role_key = "hunter"
        second_hunter.role = "hunter"
        first_hunter_id = first_hunter.player_id
        second_hunter_id = second_hunter.player_id
        final_target_id = final_target.player_id
        first_state = db.get(
            V2PlayerState,
            (created["game_id"], first_hunter_id),
        )
        assert first_state is not None
        first_state.alive = False
        first_state.death_cause = "exile"

    scripted_actions = _ScriptedDayActionEngine(
        {
            first_hunter_id: second_hunter_id,
            second_hunter_id: final_target_id,
        }
    )
    broadcaster = _CollectingBroadcaster()
    engine = V2DayEngine(
        repository=repository,
        action_engine=scripted_actions,  # type: ignore[arg-type]
    )

    asyncio.run(
        engine.resolve_pending_death_aftermath(
            game_id=created["game_id"],
            broadcaster=broadcaster,  # type: ignore[arg-type]
        )
    )

    snapshot = repository.snapshot(created["game_id"])
    assert scripted_actions.player_actions == [
        first_hunter_id,
        second_hunter_id,
    ]
    assert not snapshot.player(second_hunter_id).alive
    assert not snapshot.player(final_target_id).alive
    assert repository.pending_hunters(created["game_id"]) == ()
    public_deaths = [
        value
        for audience, value in broadcaster.messages
        if audience == "public" and value["type"] == "player.state_changed"
    ]
    assert [value["player_id"] for value in public_deaths] == [
        second_hunter_id,
        final_target_id,
    ]
    assert all(value["cause"] is None for value in public_deaths)


def test_complete_match_max_rounds_fails_explicitly(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        match = db.get(V2MatchState, created["game_id"])
        assert game is not None and run is not None and match is not None
        game.phase_id = "day_8"
        game.phase_state = "public_discussion_open"
        game.status = "ready"
        run.status = "ready"
        match.round_no = 8

    transition = repository.finish_day(
        game_id=created["game_id"],
        reason="day_actions_completed",
    )

    assert transition.phase_id == "day_8"
    assert transition.phase_state == "failed"
    with session_factory() as db:
        match = db.get(V2MatchState, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        assert match is not None and run is not None
        assert match.completion_reason == "max_rounds_exceeded"
        assert run.status == "failed"
        assert run.completed_at is not None


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
        if value.get("live_state") in {"awaiting_observation", "failed"}:
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
        user = db.scalar(select(User).where(User.email == "v2-admin@example.test"))
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
                    "model_provider": "agent_plan",
                    "model": "private-model-id",
                    "personality": "private personality prompt",
                    "avatar_image_url": "/api/v1/public/player-profiles/profile-1/avatar",
                    "strategy_profile": "private-strategy",
                    "tts_speaker": "private-speaker",
                },
                {
                    "seat": 2,
                    "profile_id": "profile-2",
                    "name": "白石",
                    "model_provider": "agent_plan",
                    "model": "test-model",
                },
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
                    "model_provider": "agent_plan",
                    "model": "test-model",
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
                    "model_provider": "agent_plan",
                    "model": "test-model",
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
