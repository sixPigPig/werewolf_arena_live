from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.game_session import GameSessionRecord
from app.models.live import (
    VoiceAudioChunkRecord,
    VoiceMaterializationJobRecord,
    VoiceUtteranceRecord,
)
from app.werewolf.live import LiveRunRegistry
from app.werewolf.live_store import DatabaseLiveStore
from app.werewolf.speech_gate import (
    stable_segment_id,
    stable_segment_presentation_id,
    stable_speech_id,
)
from app.werewolf.voice import VoiceUtterance, deterministic_voice_utterance_id
from app.werewolf.voice_materializer import VoiceMaterializer
from app.werewolf.voice_store import DatabaseVoiceStore
from app.werewolf.voice_stream import StaticJudgeVoiceAsset
from app.werewolf.volcengine_tts import VolcengineTtsConfig


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


def tts_config(
    *,
    enabled: bool = True,
    resource_id: str = "test-resource",
) -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=enabled,
        api_key="test-key",
        resource_id=resource_id,
        ws_url="wss://example.test/tts",
        player_speaker="player",
        judge_speaker="judge",
        audio_format="pcm",
        sample_rate=24000,
    )


def seed_event(
    session_factory: sessionmaker[Session],
    *,
    event_type: str,
    phase: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    payload: dict | None = None,
) -> tuple[str, int, str]:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_materializer",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    event = registry.publish(
        run.run_id,
        event_type,
        phase=phase,
        actor=actor,
        action=action,
        payload=payload,
    )
    with session_factory() as db:
        store = DatabaseLiveStore(db)
        store.save_run(run)
        db.add(GameSessionRecord(session_id=run.session_id, status="partial"))
        db.flush()
        store.append_event(event, worker_id=run.worker_id, fence_token=run.fence_token)
        job = db.query(VoiceMaterializationJobRecord).one()
        return (job.run_id, job.source_event_id, job.speaker_kind)


def committed_segment_payload(
    *,
    request_id: str,
    text: str,
    voice_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    action_id = f"act-{request_id}"
    speech_id = stable_speech_id("game_materializer", action_id, "speech-v2")
    segment_id = stable_segment_id(speech_id, 0, text)
    payload: dict[str, object] = {
        "schema_version": 2,
        "commit_state": "accepted_segment",
        "generation_stage": "renderer",
        "action_id": action_id,
        "request_id": request_id,
        "speech_id": speech_id,
        "speech_stream_mode": "segments_v2",
        "segment_id": segment_id,
        "segment_index": 0,
        "segment_final": False,
        "delta": text,
        "visible_text": text,
        "field": "say",
        "is_public": True,
        "presentation_id": stable_segment_presentation_id(segment_id),
        "experience_revision": "liveness-v1",
    }
    if voice_snapshot is not None:
        payload["voice_snapshot"] = voice_snapshot
    return payload


def test_static_judge_job_avoids_external_tts(
    session_factory: sessionmaker[Session],
) -> None:
    key = seed_event(
        session_factory,
        event_type="judge_cue",
        action="dawn_peaceful",
        payload={
            "visible_text": "昨夜平安夜。",
            "static_asset_id": "dawn_peaceful",
        },
    )

    def reject_external_tts(_config: VolcengineTtsConfig) -> object:
        raise AssertionError("static voice must not call external TTS")

    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(enabled=False),
        client_factory=reject_external_tts,
        asset_loader=lambda _db, _asset_id: StaticJudgeVoiceAsset(
            audio=b"static-audio",
            audio_format="mp3",
            mime_type="audio/mpeg",
            sample_rate=24000,
            subtitle_timings=[{"text": "昨夜平安夜。", "start_ms": 0, "end_ms": 800}],
            duration_ms=950,
        ),
    )
    claimed = materializer.claim_next_job(worker_id="worker-a")

    assert claimed == key
    assert asyncio.run(
        materializer.process_claimed_job(claimed, worker_id="worker-a")
    ) is True

    utterance_id = deterministic_voice_utterance_id(key[0], key[1], "judge")
    with session_factory() as db:
        job = db.get(VoiceMaterializationJobRecord, key)
        utterance = db.get(VoiceUtteranceRecord, utterance_id)
        chunk = db.get(VoiceAudioChunkRecord, (utterance_id, 0))
        assert job is not None and job.status == "complete"
        assert utterance is not None and utterance.status == "complete"
        assert utterance.duration_ms == 950
        assert utterance.tts_request_source == "judge_event"
        assert utterance.subtitle_timings == [
            {"text": "昨夜平安夜。", "start_ms": 0, "end_ms": 800}
        ]
        assert chunk is not None and bytes(chunk.audio) == b"static-audio"


def test_game_completed_materializes_exactly_one_terminal_judge_voice(
    session_factory: sessionmaker[Session],
) -> None:
    key = seed_event(
        session_factory,
        event_type="game_completed",
        payload={"winner": "好人阵营", "terminal_keep_from_event_id": 2},
    )
    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(enabled=False),
        asset_loader=lambda _db, asset_id: StaticJudgeVoiceAsset(
            audio=b"terminal-audio",
            audio_format="mp3",
            mime_type="audio/mpeg",
            sample_rate=24000,
            subtitle_timings=[
                {"text": "游戏结束，好人阵营获胜。", "start_ms": 0, "end_ms": 900}
            ],
            duration_ms=1000,
        )
        if asset_id == "game_over_villagers"
        else None,
    )

    claimed = materializer.claim_next_job(worker_id="worker-terminal")
    assert claimed == key
    assert asyncio.run(
        materializer.process_claimed_job(claimed, worker_id="worker-terminal")
    ) is True

    utterance_id = deterministic_voice_utterance_id(key[0], key[1], "judge")
    with session_factory() as db:
        utterances = db.query(VoiceUtteranceRecord).all()
        assert len(utterances) == 1
        assert utterances[0].utterance_id == utterance_id
        assert utterances[0].duration_ms == 1000
        assert db.query(VoiceMaterializationJobRecord).count() == 1


def test_canonical_hunter_result_enqueues_and_persists_semantic_voice_identity(
    session_factory: sessionmaker[Session],
) -> None:
    presentation_id = "hp_0123456789abcdef01234567"
    key = seed_event(
        session_factory,
        event_type="state_updated",
        action="hunter_shot_resolved",
        payload={
            "presentation_id": presentation_id,
            "hunter_shot_status": "skipped",
            "hunter_shot": None,
            "active_players": ["1号玩家", "2号玩家"],
        },
    )
    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(enabled=False),
        asset_loader=lambda _db, asset_id: StaticJudgeVoiceAsset(
            audio=b"hunter-skipped-audio",
            audio_format="mp3",
            mime_type="audio/mpeg",
            sample_rate=24000,
            subtitle_timings=[
                {"text": "猎人选择不发动技能。", "start_ms": 0, "end_ms": 800}
            ],
            duration_ms=900,
        )
        if asset_id == "hunter_shot_skipped"
        else None,
    )

    claimed = materializer.claim_next_job(worker_id="worker-hunter-result")
    assert claimed == key
    assert asyncio.run(
        materializer.process_claimed_job(
            claimed,
            worker_id="worker-hunter-result",
        )
    ) is True

    utterance_id = deterministic_voice_utterance_id(key[0], key[1], "judge")
    with session_factory() as db:
        job = db.get(VoiceMaterializationJobRecord, key)
        utterance = db.get(VoiceUtteranceRecord, utterance_id)
        assert job is not None and job.status == "complete"
        assert utterance is not None and utterance.status == "complete"
        assert utterance.presentation_id == presentation_id
        playback = DatabaseVoiceStore(
            db,
            session_id="game_materializer",
        ).load_playback_voice(utterance_id)
        assert playback is not None
        assert playback["presentation_id"] == presentation_id


class FailOnceTtsClient:
    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, *, speaker: str, text_chunks: list[str]):
        del speaker, text_chunks
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient")
        yield b"\x00\x01" * 2400


class SuccessfulTtsClient:
    async def synthesize(self, *, speaker: str, text_chunks: list[str]):
        del speaker, text_chunks
        yield b"\x00\x01" * 2400


class CapturingTtsClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
        context_texts: list[str] | None = None,
    ):
        self.calls.append(
            {
                "speaker": speaker,
                "text_chunks": text_chunks,
                "context_texts": context_texts,
            }
        )
        yield b"\x00\x01" * 2400


def test_dynamic_player_job_retries_without_duplicate_audio(
    session_factory: sessionmaker[Session],
) -> None:
    key = seed_event(
        session_factory,
        event_type="model_response_delta",
        actor="阿青",
        action="debate",
        payload=committed_segment_payload(
            request_id="req-final",
            text="这是最终公开发言。",
        ),
    )
    client = FailOnceTtsClient()
    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(),
        backoff_seconds=1,
        client_factory=lambda _config: client,
    )

    first = materializer.claim_next_job(worker_id="worker-a")
    assert first == key
    assert asyncio.run(materializer.process_claimed_job(first, worker_id="worker-a")) is False

    with session_factory() as db:
        pending = db.get(VoiceMaterializationJobRecord, key)
        assert pending is not None and pending.status == "pending"
        retry_at = pending.not_before + timedelta(milliseconds=1)

    second = materializer.claim_next_job(worker_id="worker-b", now=retry_at)
    assert second == key
    assert asyncio.run(materializer.process_claimed_job(second, worker_id="worker-b")) is True

    utterance_id = deterministic_voice_utterance_id(key[0], key[1], "player")
    with session_factory() as db:
        job = db.get(VoiceMaterializationJobRecord, key)
        assert job is not None and job.status == "complete" and job.attempt_count == 2
        assert db.query(VoiceUtteranceRecord).count() == 1
        assert db.query(VoiceAudioChunkRecord).count() == 1
        assert db.get(VoiceUtteranceRecord, utterance_id) is not None


def test_dynamic_player_job_uses_enqueue_time_voice_snapshot(
    session_factory: sessionmaker[Session],
) -> None:
    delivery = {
        "schema_version": 1,
        "mood": "skeptical",
        "intensity": "high",
        "pace": "fast",
        "instruction": "克制、反问",
    }
    contexts = ["像真人在桌上克制反问；语速稍快。"]
    key = seed_event(
        session_factory,
        event_type="model_response_delta",
        actor="阿青",
        action="debate",
        payload=committed_segment_payload(
            request_id="req-snapshot",
            text="我不同意这个票型。",
            voice_snapshot={
                "enabled": True,
                "speaker": "zh_female_gaolengyujie_uranus_bigtts",
                "effective_delivery": delivery,
                "effective_context_texts": contexts,
                "voice_config_version": 7,
                "delivery_mapping_version": "delivery-v1",
            },
        ),
    )
    client = CapturingTtsClient()
    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(resource_id="seed-tts-2.0"),
        client_factory=lambda _config: client,
    )

    claimed = materializer.claim_next_job(worker_id="worker-snapshot")
    assert claimed == key
    assert asyncio.run(
        materializer.process_claimed_job(claimed, worker_id="worker-snapshot")
    ) is True

    assert client.calls == [
        {
            "speaker": "zh_female_gaolengyujie_uranus_bigtts",
            "text_chunks": ["我不同意这个票型。"],
            "context_texts": contexts,
        }
    ]
    utterance_id = deterministic_voice_utterance_id(key[0], key[1], "player")
    with session_factory() as db:
        job = db.get(VoiceMaterializationJobRecord, key)
        utterance = db.get(VoiceUtteranceRecord, utterance_id)
        assert job is not None
        assert job.speaker == "zh_female_gaolengyujie_uranus_bigtts"
        assert job.effective_delivery == delivery
        assert job.effective_context_texts == contexts
        assert job.voice_config_version == 7
        assert job.delivery_mapping_version == "delivery-v1"
        assert job.tts_request_source == "committed_speech_segment"
        assert utterance is not None
        assert utterance.speaker == "zh_female_gaolengyujie_uranus_bigtts"
        assert utterance.effective_delivery == delivery
        assert utterance.effective_context_texts == contexts
        assert utterance.voice_config_version == 7
        assert utterance.delivery_mapping_version == "delivery-v1"
        assert utterance.tts_request_source == "committed_speech_segment"


def test_dynamic_clone_voice_keeps_say_but_omits_unsupported_context_texts(
    session_factory: sessionmaker[Session],
) -> None:
    contexts = ["像真人在桌上克制反问；语速稍快。"]
    key = seed_event(
        session_factory,
        event_type="model_response_delta",
        actor="阿青",
        action="debate",
        payload=committed_segment_payload(
            request_id="req-clone-context-gate",
            text="这句话仍然应当正常合成。",
            voice_snapshot={
                "enabled": True,
                "speaker": "S_clone_voice_001",
                "effective_delivery": {
                    "schema_version": 1,
                    "mood": "skeptical",
                    "intensity": "high",
                    "pace": "fast",
                    "instruction": "克制、反问",
                },
                "effective_context_texts": contexts,
                "voice_config_version": 4,
                "delivery_mapping_version": "delivery-v1",
            },
        ),
    )
    client = CapturingTtsClient()
    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(),
        client_factory=lambda _config: client,
    )

    claimed = materializer.claim_next_job(worker_id="worker-clone-context-gate")
    assert claimed == key
    assert asyncio.run(
        materializer.process_claimed_job(
            claimed,
            worker_id="worker-clone-context-gate",
        )
    ) is True

    assert client.calls == [
        {
            "speaker": "S_clone_voice_001",
            "text_chunks": ["这句话仍然应当正常合成。"],
            "context_texts": None,
        }
    ]
    utterance_id = deterministic_voice_utterance_id(key[0], key[1], "player")
    with session_factory() as db:
        utterance = db.get(VoiceUtteranceRecord, utterance_id)
        assert utterance is not None
        assert utterance.status == "complete"
        assert utterance.effective_context_texts == contexts


def test_disabled_player_voice_snapshot_does_not_enqueue_job(
    session_factory: sessionmaker[Session],
) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_materializer",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    event = registry.publish(
        run.run_id,
        "action_parsed",
        actor="阿青",
        action="debate",
        payload={
            "visible_result": {"say": "这一轮我先听。"},
            "voice_snapshot": {"enabled": False},
        },
    )

    with session_factory() as db:
        store = DatabaseLiveStore(db)
        store.save_run(run)
        store.append_event(event, worker_id=run.worker_id, fence_token=run.fence_token)
        assert db.query(VoiceMaterializationJobRecord).count() == 0


def test_god_view_wolf_chat_job_materializes_scoped_voice(
    session_factory: sessionmaker[Session],
) -> None:
    key = seed_event(
        session_factory,
        event_type="action_parsed",
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
    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(),
        client_factory=lambda _config: SuccessfulTtsClient(),
    )

    claimed = materializer.claim_next_job(worker_id="worker-god-view")

    assert claimed == key
    assert asyncio.run(
        materializer.process_claimed_job(claimed, worker_id="worker-god-view")
    ) is True

    utterance_id = deterministic_voice_utterance_id(
        key[0],
        key[1],
        "player",
        audience="spectator_god_view",
    )
    with session_factory() as db:
        job = db.get(VoiceMaterializationJobRecord, key)
        utterance = db.get(VoiceUtteranceRecord, utterance_id)
        assert job is not None and job.status == "complete"
        assert job.audience == "spectator_god_view"
        assert utterance is not None and utterance.status == "complete"
        assert utterance.audience == "spectator_god_view"
        assert utterance.action == "werewolf_discuss"
        assert utterance.text == "今晚建议刀3号。"


def test_god_view_only_judge_job_materializes_scoped_voice(
    session_factory: sessionmaker[Session],
) -> None:
    key = seed_event(
        session_factory,
        event_type="judge_cue",
        phase="night",
        action="werewolf_tiebreak_result",
        payload={
            "cue_id": "werewolf_tiebreak_result",
            "visible_text": "2号玩家最终归票3号玩家，狼人请确认刀口。",
            "static_asset_id": None,
        },
    )
    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(),
        client_factory=lambda _config: SuccessfulTtsClient(),
    )

    claimed = materializer.claim_next_job(worker_id="worker-god-view-judge")

    assert claimed == key
    assert asyncio.run(
        materializer.process_claimed_job(
            claimed,
            worker_id="worker-god-view-judge",
        )
    ) is True

    utterance_id = deterministic_voice_utterance_id(
        key[0],
        key[1],
        "judge",
        audience="spectator_god_view",
    )
    with session_factory() as db:
        job = db.get(VoiceMaterializationJobRecord, key)
        utterance = db.get(VoiceUtteranceRecord, utterance_id)
        assert job is not None and job.status == "complete"
        assert job.audience == "spectator_god_view"
        assert utterance is not None and utterance.status == "complete"
        assert utterance.audience == "spectator_god_view"
        assert utterance.speaker_kind == "judge"
        assert utterance.action == "werewolf_tiebreak_result"


def test_dynamic_player_job_reuses_equivalent_live_audio(
    session_factory: sessionmaker[Session],
) -> None:
    key = seed_event(
        session_factory,
        event_type="model_response_delta",
        actor="阿青",
        action="debate",
        payload=committed_segment_payload(
            request_id="req-live-saved",
            text="这段现场语音已经保存。",
        ),
    )
    with session_factory() as db:
        store = DatabaseVoiceStore(db, session_id="game_materializer")
        store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_live_saved",
                run_id=key[0],
                source_event_id=key[1],
                request_id="req-live-saved",
                speaker_kind="player",
                speaker_name="阿青",
                speaker="player",
                text="这段现场语音已经保存。",
                action="debate",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        store.append_chunk("voice_live_saved", chunk_index=0, audio=b"live-audio")
        store.complete_utterance("voice_live_saved", duration_ms=250)

    def reject_external_tts(_config: VolcengineTtsConfig) -> object:
        raise AssertionError("saved live audio must not be synthesized again")

    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(),
        client_factory=reject_external_tts,
    )
    claimed = materializer.claim_next_job(worker_id="worker-a")

    assert claimed == key
    assert asyncio.run(
        materializer.process_claimed_job(claimed, worker_id="worker-a")
    ) is True

    with session_factory() as db:
        job = db.get(VoiceMaterializationJobRecord, key)
        assert job is not None and job.status == "complete"
        assert db.query(VoiceUtteranceRecord).count() == 1
        assert db.query(VoiceAudioChunkRecord).count() == 1
        assert db.get(VoiceUtteranceRecord, "voice_live_saved") is not None


def test_expired_processing_lease_is_reclaimed(
    session_factory: sessionmaker[Session],
) -> None:
    key = seed_event(
        session_factory,
        event_type="game_completed",
        payload={"winner": "好人阵营"},
    )
    materializer = VoiceMaterializer(
        session_factory,
        config=tts_config(enabled=False),
        lease_seconds=10,
    )
    now = datetime.now(tz=UTC)

    assert materializer.claim_next_job(worker_id="worker-a", now=now) == key
    assert (
        materializer.claim_next_job(
            worker_id="worker-b",
            now=now + timedelta(seconds=9),
        )
        is None
    )
    assert materializer.claim_next_job(
        worker_id="worker-b",
        now=now + timedelta(seconds=11),
    ) == key

    with session_factory() as db:
        job = db.get(VoiceMaterializationJobRecord, key)
        assert job is not None
        assert job.worker_id == "worker-b"
        assert job.attempt_count == 2
