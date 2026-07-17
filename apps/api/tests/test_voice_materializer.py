from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.live import (
    VoiceAudioChunkRecord,
    VoiceMaterializationJobRecord,
    VoiceUtteranceRecord,
)
from app.werewolf.live import LiveRunRegistry
from app.werewolf.live_store import DatabaseLiveStore
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


def tts_config(*, enabled: bool = True) -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=enabled,
        api_key="test-key",
        resource_id="test-resource",
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
        store.append_event(event, worker_id=run.worker_id, fence_token=run.fence_token)
        job = db.query(VoiceMaterializationJobRecord).one()
        return (job.run_id, job.source_event_id, job.speaker_kind)


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
        assert utterance.subtitle_timings == [
            {"text": "昨夜平安夜。", "start_ms": 0, "end_ms": 800}
        ]
        assert chunk is not None and bytes(chunk.audio) == b"static-audio"


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


def test_dynamic_player_job_retries_without_duplicate_audio(
    session_factory: sessionmaker[Session],
) -> None:
    key = seed_event(
        session_factory,
        event_type="action_parsed",
        actor="阿青",
        action="debate",
        payload={
            "request_id": "req-final",
            "visible_result": {"say": "这是最终公开发言。"},
        },
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
        event_type="action_parsed",
        actor="阿青",
        action="debate",
        payload={
            "request_id": "req-live-saved",
            "visible_result": {"say": "这段现场语音已经保存。"},
        },
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
