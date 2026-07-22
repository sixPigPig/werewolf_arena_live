from __future__ import annotations

from collections.abc import AsyncIterator, Generator
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.models.game_session import GameSessionRecord
from app.models.live import LiveRunRecord
from app.v2.live_runtime import V2LiveRuntime
from app.v2.model_client import V2ModelSpeech
from app.v2.models import (
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2LivePresentation,
    V2VoiceAsset,
)


PCM_CHUNK = b"\x10\x00" * 240


class FakeV2ModelClient:
    async def generate_first_sentence(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
    ) -> V2ModelSpeech:
        assert action_context["influence"] == {
            "schema_version": 1,
            "status": "disabled",
            "captured_at": None,
            "strength": 0,
            "signals": [],
        }
        assert attempt_id.startswith("v2_model_")
        return V2ModelSpeech(
            text="欢迎来到这场实时狼人杀对局。",
            provider_request_id="provider-response-test",
            first_token_ms=12,
            sentence_ms=34,
        )


class FakeV2TtsClient:
    async def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
    ) -> AsyncIterator[bytes]:
        assert text == "欢迎来到这场实时狼人杀对局。"
        assert attempt_id.startswith("v2_tts_")
        yield PCM_CHUNK
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
    application.state.v2_live_runtime = V2LiveRuntime(
        session_factory=testing_session,
        model_client=FakeV2ModelClient(),
        tts_client=FakeV2TtsClient(),
        voice_root=voice_root,
        sample_rate=24000,
    )
    with TestClient(application) as client:
        yield client, testing_session, voice_root
    engine.dispose()


def test_v2_meta_is_independent_from_v1(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context

    response = client.get("/api/v2/meta")

    assert response.status_code == 200
    assert response.json() == {
        "api_version": "v2",
        "status": "realtime_first_sentence",
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
        assert game is not None and game.title == "经典 8 人"
        assert game.status == "ready"
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
        assert [event.event_type for event in events] == ["game_created"]
        assert events[0].payload == {
            "title": "经典 8 人",
            "start_mode": "first_ready_viewer",
            "creation_source": "existing_mobile_lobby",
            "rule_set_id": "classic_8",
            "player_count": 2,
        }
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

    snapshot = client.get(created["snapshot_url"])
    assert snapshot.status_code == 200
    public_players = snapshot.json()["public_players"]
    assert public_players == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": "/api/v1/public/player-profiles/profile-1/avatar",
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "白石",
            "avatar_url": None,
        },
    ]
    assert all(
        set(player) == {"seat", "player_id", "display_name", "avatar_url"}
        for player in public_players
    )


def test_v2_lobby_create_rejects_incomplete_or_duplicate_lineups(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    incomplete = _lobby_create_request()
    incomplete["lobby_snapshot"]["player_configs"] = [{"seat": 1, "profile_id": "profile-1"}]
    duplicate = _lobby_create_request()
    duplicate["lobby_snapshot"]["player_configs"][1]["profile_id"] = "profile-1"

    assert client.post("/api/v2/games", json=incomplete).status_code == 422
    assert client.post("/api/v2/games", json=duplicate).status_code == 422


def test_first_ready_viewer_receives_one_realtime_sentence_and_voice_is_saved(
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
    assert snapshot.json()["public_players"] == []
    assert snapshot.json()["current_presentation"] is None

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
        assert websocket.receive_json()["live_state"] == "generating"
        opened = websocket.receive_json()
        committed = websocket.receive_json()
        broadcasting = websocket.receive_json()
        assert opened["type"] == "presentation.opened"
        assert committed["type"] == "speech.segment_committed"
        assert committed["text"] == "欢迎来到这场实时狼人杀对局。"
        assert broadcasting["live_state"] == "broadcasting"
        first_audio = websocket.receive_bytes()
        second_audio = websocket.receive_bytes()
        assert first_audio[:4] == b"LV2A"
        assert second_audio[:4] == b"LV2A"
        first_header, first_pcm = _decode_audio(first_audio)
        second_header, second_pcm = _decode_audio(second_audio)
        assert first_header["chunk_index"] == 0
        assert first_header["start_sample"] == 0
        assert second_header["chunk_index"] == 1
        assert second_header["start_sample"] == 240
        assert first_pcm == second_pcm == PCM_CHUNK
        assert websocket.receive_json()["live_state"] == "finalizing"
        closed = websocket.receive_json()
        stopped = websocket.receive_json()
        assert closed["type"] == "presentation.closed"
        assert closed["final_sample_cursor"] == 480
        assert stopped["live_state"] == "awaiting_observation"

    after = client.get(identifiers["snapshot_url"]).json()
    assert after["live_state"] == "awaiting_observation"
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
        presentation = db.scalar(
            select(V2LivePresentation).where(V2LivePresentation.game_id == game_id)
        )
        voice = db.scalar(select(V2VoiceAsset).where(V2VoiceAsset.game_id == game_id))
        assert game is not None and game.status == "awaiting_observation"
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
        ]
        assert presentation is not None and presentation.state == "closed"
        assert voice is not None and voice.state == "ready"
        assert voice.sample_count == 480
        assert voice.pcm_sha256 == hashlib.sha256(PCM_CHUNK * 2).hexdigest()
        voice_path = voice_root / voice.storage_key
        assert voice_path.is_file()
        assert voice_path.read_bytes()[:4] == b"RIFF"
        assert db.scalar(select(func.count()).select_from(GameSessionRecord)) == 0
        assert db.scalar(select(func.count()).select_from(LiveRunRecord)) == 0

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        reconnect = websocket.receive_json()
        assert reconnect["live_state"] == "awaiting_observation"
        assert reconnect["current_presentation"] is None


def test_admin_v2_record_exposes_saved_voice_only_through_authenticated_endpoint(
    v2_context,
) -> None:
    client, _session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json={"title": "Admin V2 语音"}).json()
    _run_first_sentence(client, identifiers["websocket_url"])

    unauthorized = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert unauthorized.status_code == 401
    session = client.post("/api/v1/admin/dev-login")
    assert session.status_code == 200, session.text

    detail = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["voice_assets"]) == 1
    voice = body["voice_assets"][0]
    assert voice["state"] == "ready"
    assert voice["pcm_sha256"] == hashlib.sha256(PCM_CHUNK * 2).hexdigest()
    assert voice["audio_url"].startswith("/api/v1/admin/v2/games/")
    audio = client.get(voice["audio_url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.content[:4] == b"RIFF"


def _run_first_sentence(client: TestClient, websocket_url: str) -> None:
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
