from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.werewolf.voice import VoiceUtterance
from app.werewolf.voice_store import DatabaseVoiceStore, text_hash_for_voice


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as session:
        yield session


def utterance(text: str = "我不是狼") -> VoiceUtterance:
    return VoiceUtterance(
        utterance_id="voice_1",
        run_id="run_1",
        source_event_id=4,
        request_id="req-1",
        speaker_kind="player",
        speaker_name="阿青",
        speaker="zh_female_vv_uranus_bigtts",
        text=text,
        action="debate",
    )


def test_voice_store_creates_updates_chunks_and_completes(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")

    store.upsert_utterance(
        utterance(),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="synthesizing",
    )
    store.append_chunk("voice_1", chunk_index=0, audio=b"abc")
    store.append_chunk("voice_1", chunk_index=1, audio=b"def")
    store.complete_utterance("voice_1", duration_ms=1200)

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "complete"
    assert loaded["text"] == "我不是狼"
    assert store.load_chunks("voice_1") == [b"abc", b"def"]


def test_voice_store_finds_recent_utterance_for_request(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    first = utterance("第一句")
    second = utterance("第二句")
    second = VoiceUtterance(
        utterance_id="voice_2",
        run_id=second.run_id,
        source_event_id=8,
        request_id=second.request_id,
        speaker_kind=second.speaker_kind,
        speaker_name=second.speaker_name,
        speaker=second.speaker,
        text=second.text,
        action=second.action,
    )

    store.upsert_utterance(first, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.upsert_utterance(second, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")

    found = store.find_recent_utterance(run_id="run_1", current_event_id=9)
    assert found is not None
    assert found["utterance_id"] == "voice_2"


def test_voice_store_updates_existing_utterance(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("第一段"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="synthesizing",
    )
    store.upsert_utterance(
        VoiceUtterance(
            utterance_id="voice_1",
            run_id="run_1",
            source_event_id=6,
            request_id="req-2",
            speaker_kind="player",
            speaker_name="阿青",
            speaker="speaker-updated",
            text="第一段，补充",
            action="debate",
        ),
        audio_format="wav",
        sample_rate=48000,
        mime_type="audio/wav",
        status="synthesizing",
    )

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["last_source_event_id"] == 6
    assert loaded["request_id"] == "req-2"
    assert loaded["speaker"] == "speaker-updated"
    assert loaded["text"] == "第一段，补充"
    assert loaded["audio_format"] == "wav"
    assert loaded["sample_rate"] == 48000


def test_voice_store_duplicate_chunk_index_raises_and_session_remains_usable(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance(),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.append_chunk("voice_1", chunk_index=0, audio=b"abc")

    with pytest.raises(IntegrityError):
        store.append_chunk("voice_1", chunk_index=0, audio=b"overwrite")

    store.append_chunk("voice_1", chunk_index=1, audio=b"def")
    assert store.load_chunks("voice_1") == [b"abc", b"def"]


def test_voice_store_marks_utterance_failed(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance(),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )

    store.fail_utterance("voice_1", error_message="tts failed")

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "failed"
    assert loaded["error_message"] == "tts failed"


def test_text_hash_includes_voice_settings() -> None:
    assert text_hash_for_voice(
        speaker="speaker-a",
        audio_format="pcm",
        sample_rate=24000,
        text="hello",
    ) != text_hash_for_voice(
        speaker="speaker-b",
        audio_format="pcm",
        sample_rate=24000,
        text="hello",
    )
