from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace

import pytest
from sqlalchemy import create_engine
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


def stored_utterance(
    *,
    utterance_id: str,
    source_event_id: int,
    text: str,
    speaker_kind: str = "player",
    action: str = "debate",
    audience: str = "player_public",
) -> VoiceUtterance:
    return VoiceUtterance(
        utterance_id=utterance_id,
        run_id="run_1",
        source_event_id=source_event_id,
        request_id=f"req-{utterance_id}",
        speaker_kind=speaker_kind,
        speaker_name="阿青",
        speaker="zh_female_vv_uranus_bigtts",
        text=text,
        action=action,
        audience=audience,
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


def test_voice_store_persists_semantic_presentation_id(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    semantic_utterance = replace(
        utterance(),
        presentation_id="hp_0123456789abcdef01234567",
    )

    store.upsert_utterance(
        semantic_utterance,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["presentation_id"] == "hp_0123456789abcdef01234567"


def test_voice_store_merges_subtitle_timing_updates(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("我是村民，我先过。"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="synthesizing",
    )

    store.update_subtitle_timings(
        "voice_1",
        subtitle_timings=[
            {"text": "我是", "start_ms": 0, "end_ms": 240},
            {"text": "村民，", "start_ms": 240, "end_ms": 700},
        ],
    )
    store.update_subtitle_timings(
        "voice_1",
        subtitle_timings=[
            {"text": "我先", "start_ms": 700, "end_ms": 1040},
            {"text": "过。", "start_ms": 1040, "end_ms": 1320},
        ],
    )

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["subtitle_timings"] == [
        {"text": "我是", "start_ms": 0, "end_ms": 240},
        {"text": "村民，", "start_ms": 240, "end_ms": 700},
        {"text": "我先", "start_ms": 700, "end_ms": 1040},
        {"text": "过。", "start_ms": 1040, "end_ms": 1320},
    ]


def test_voice_store_never_completes_before_the_last_subtitle_cue(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("游戏结束，好人阵营获胜。"),
        audio_format="mp3",
        sample_rate=24000,
        mime_type="audio/mpeg",
    )
    store.update_subtitle_timings(
        "voice_1",
        subtitle_timings=[
            {"text": "游戏结束，", "start_ms": 0, "end_ms": 400},
            {"text": "好人阵营获胜。", "start_ms": 400, "end_ms": 1250},
        ],
    )

    store.complete_utterance("voice_1", duration_ms=3)

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["duration_ms"] == 1250


def test_voice_store_finds_recent_utterance_for_request(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    first = stored_utterance(utterance_id="voice_1", source_event_id=4, text="第一句")
    second = stored_utterance(utterance_id="voice_2", source_event_id=8, text="第二句")

    store.upsert_utterance(first, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.upsert_utterance(second, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_1", chunk_index=0, audio=b"old")
    store.complete_utterance("voice_1", duration_ms=100)
    store.append_chunk("voice_2", chunk_index=0, audio=b"new")
    store.complete_utterance("voice_2", duration_ms=200)

    found = store.find_recent_utterance(run_id="run_1", current_event_id=9)
    assert found is not None
    assert found["utterance_id"] == "voice_2"


def test_voice_store_finds_recent_replayable_utterance_when_newer_rows_are_invalid(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    complete = stored_utterance(utterance_id="voice_complete", source_event_id=4, text="可回放")
    failed = stored_utterance(utterance_id="voice_failed", source_event_id=7, text="失败")
    chunkless = stored_utterance(utterance_id="voice_chunkless", source_event_id=8, text="无音频")
    invalid_kind = stored_utterance(
        utterance_id="voice_invalid_kind",
        source_event_id=9,
        text="角色类型异常",
        speaker_kind="moderator",
    )

    store.upsert_utterance(complete, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_complete", chunk_index=0, audio=b"complete-audio")
    store.complete_utterance("voice_complete", duration_ms=300)
    store.upsert_utterance(failed, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_failed", chunk_index=0, audio=b"failed-audio")
    store.fail_utterance("voice_failed", message="tts failed")
    store.upsert_utterance(chunkless, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.complete_utterance("voice_chunkless", duration_ms=100)
    store.upsert_utterance(
        invalid_kind,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.append_chunk("voice_invalid_kind", chunk_index=0, audio=b"invalid-kind-audio")
    store.complete_utterance("voice_invalid_kind", duration_ms=100)

    found = store.find_recent_utterance(run_id="run_1", current_event_id=9)

    assert found is not None
    assert found["utterance_id"] == "voice_complete"


def test_voice_store_lists_playback_voices_with_base64_chunks(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    first = stored_utterance(utterance_id="voice_first", source_event_id=4, text="第一句")
    second = stored_utterance(utterance_id="voice_second", source_event_id=8, text="第二句")
    failed = stored_utterance(utterance_id="voice_failed", source_event_id=9, text="失败")
    chunkless = stored_utterance(utterance_id="voice_chunkless", source_event_id=10, text="无音频")
    invalid_kind = stored_utterance(
        utterance_id="voice_invalid_kind",
        source_event_id=11,
        text="无效类型",
        speaker_kind="moderator",
    )

    store.upsert_utterance(second, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_second", chunk_index=0, audio=b"second-0")
    store.complete_utterance("voice_second", duration_ms=200)
    store.upsert_utterance(first, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_first", chunk_index=1, audio=b"first-1")
    store.append_chunk("voice_first", chunk_index=0, audio=b"first-0")
    store.complete_utterance("voice_first", duration_ms=100)
    store.upsert_utterance(failed, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_failed", chunk_index=0, audio=b"failed")
    store.fail_utterance("voice_failed", message="tts failed")
    store.upsert_utterance(chunkless, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.complete_utterance("voice_chunkless", duration_ms=50)
    store.upsert_utterance(
        invalid_kind,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.append_chunk("voice_invalid_kind", chunk_index=0, audio=b"invalid")
    store.complete_utterance("voice_invalid_kind", duration_ms=50)

    voices = store.list_playback_voices()

    assert [voice["utterance_id"] for voice in voices] == ["voice_first", "voice_second"]
    assert voices[0]["source_event_id"] == 4
    assert voices[0]["audience"] == "player_public"
    assert voices[0]["duration_ms"] == 100
    assert voices[0]["chunks"] == [
        {"chunk_index": 0, "data": "Zmlyc3QtMA=="},
        {"chunk_index": 1, "data": "Zmlyc3QtMQ=="},
    ]
    assert voices[1]["chunks"] == [{"chunk_index": 0, "data": "c2Vjb25kLTA="}]


def test_voice_store_loads_one_public_complete_playback_voice(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    public = stored_utterance(
        utterance_id="voice_public",
        source_event_id=4,
        text="公开发言",
    )
    private = stored_utterance(
        utterance_id="voice_private",
        source_event_id=5,
        text="私有总结",
        action="summarize",
    )
    for item in (public, private):
        store.upsert_utterance(
            item,
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        store.append_chunk(item.utterance_id, chunk_index=0, audio=b"audio")
        store.complete_utterance(item.utterance_id, duration_ms=100)

    loaded = store.load_playback_voice(
        "voice_public",
        excluded_actions=frozenset({"summarize"}),
    )

    assert loaded is not None
    assert loaded["utterance_id"] == "voice_public"
    assert loaded["chunks"] == [{"chunk_index": 0, "data": "YXVkaW8="}]
    assert (
        store.load_playback_voice(
            "voice_private",
            excluded_actions=frozenset({"summarize"}),
        )
        is None
    )
    assert (
        DatabaseVoiceStore(
            db_session,
            session_id="game_other000",
        ).load_playback_voice("voice_public")
        is None
    )


def test_voice_store_scopes_god_view_voice_away_from_public_playback(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    public = stored_utterance(
        utterance_id="voice_public",
        source_event_id=4,
        text="公开发言",
    )
    god_view = stored_utterance(
        utterance_id="voice_wolf_chat",
        source_event_id=5,
        text="今晚刀三号。",
        action="werewolf_discuss",
        audience="spectator_god_view",
    )
    for item in (public, god_view):
        store.upsert_utterance(
            item,
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        store.append_chunk(item.utterance_id, chunk_index=0, audio=b"audio")
        store.complete_utterance(item.utterance_id, duration_ms=100)

    assert [
        voice["utterance_id"] for voice in store.list_playback_voices()
    ] == ["voice_public"]
    assert store.load_playback_voice("voice_wolf_chat") is None

    god_view_audiences = frozenset({"player_public", "spectator_god_view"})
    assert [
        voice["utterance_id"]
        for voice in store.list_playback_voices(
            allowed_audiences=god_view_audiences,
        )
    ] == ["voice_public", "voice_wolf_chat"]
    loaded = store.load_playback_voice(
        "voice_wolf_chat",
        allowed_audiences=god_view_audiences,
    )
    assert loaded is not None
    assert loaded["audience"] == "spectator_god_view"
    assert loaded["subtitle_timings"] == [
        {"text": "今晚刀三号。", "start_ms": 0, "end_ms": 1}
    ]


def test_voice_store_lists_playback_metadata_without_loading_chunks(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    item = stored_utterance(
        utterance_id="voice_metadata",
        source_event_id=4,
        text="公开发言",
    )
    store.upsert_utterance(
        item,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.append_chunk(item.utterance_id, chunk_index=0, audio=b"large-sentinel")
    store.complete_utterance(item.utterance_id, duration_ms=100)

    voices = store.list_playback_voices(include_chunks=False)

    assert [voice["utterance_id"] for voice in voices] == ["voice_metadata"]
    assert "chunks" not in voices[0]


def test_voice_store_defaults_new_utterance_to_synthesizing(db_session: Session) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")

    store.upsert_utterance(
        utterance(),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "synthesizing"


def test_voice_store_updates_existing_utterance_text_and_recency(db_session: Session) -> None:
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
            request_id="req-1",
            speaker_kind="player",
            speaker_name="阿青",
            speaker="zh_female_vv_uranus_bigtts",
            text="第一段，补充",
            action="debate",
        ),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="synthesizing",
    )

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["source_event_id"] == 4
    assert loaded["last_source_event_id"] == 6
    assert loaded["request_id"] == "req-1"
    assert loaded["speaker"] == "zh_female_vv_uranus_bigtts"
    assert loaded["text"] == "第一段，补充"
    assert loaded["audio_format"] == "pcm"
    assert loaded["sample_rate"] == 24000


def test_voice_store_ignores_stale_upsert_without_overwriting_fields(
    db_session: Session,
) -> None:
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
            request_id="req-1",
            speaker_kind="player",
            speaker_name="阿青",
            speaker="zh_female_vv_uranus_bigtts",
            text="较新的文本",
            action="debate",
        ),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="synthesizing",
    )
    store.upsert_utterance(
        VoiceUtterance(
            utterance_id="voice_1",
            run_id="run_1",
            source_event_id=5,
            request_id="req-stale",
            speaker_kind="player",
            speaker_name="阿青",
            speaker="speaker-stale",
            text="过期文本",
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
    assert loaded["request_id"] == "req-1"
    assert loaded["speaker"] == "zh_female_vv_uranus_bigtts"
    assert loaded["text"] == "较新的文本"
    assert loaded["text_hash"] == text_hash_for_voice(
        speaker="zh_female_vv_uranus_bigtts",
        audio_format="pcm",
        sample_rate=24000,
        text="较新的文本",
    )
    assert loaded["audio_format"] == "pcm"
    assert loaded["sample_rate"] == 24000
    assert loaded["mime_type"] == "audio/L16"
    assert loaded["status"] == "synthesizing"


def test_voice_store_upsert_after_complete_keeps_terminal_metadata(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("原始文本"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.complete_utterance("voice_1", duration_ms=1200)
    completed = store.load_utterance("voice_1")
    assert completed is not None

    store.upsert_utterance(
        VoiceUtterance(
            utterance_id="voice_1",
            run_id="run_1",
            source_event_id=6,
            request_id="req-1",
            speaker_kind="player",
            speaker_name="阿青",
            speaker="zh_female_vv_uranus_bigtts",
            text="不应重开",
            action="debate",
        ),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "complete"
    assert loaded["text"] == "原始文本"
    assert loaded["duration_ms"] == 1200
    assert loaded["completed_at"] == completed["completed_at"]
    assert loaded["error_message"] is None


def test_voice_store_upsert_after_failure_keeps_terminal_metadata(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("原始文本"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.fail_utterance("voice_1", message="tts failed")
    failed = store.load_utterance("voice_1")
    assert failed is not None

    store.upsert_utterance(
        VoiceUtterance(
            utterance_id="voice_1",
            run_id="run_1",
            source_event_id=6,
            request_id="req-1",
            speaker_kind="player",
            speaker_name="阿青",
            speaker="zh_female_vv_uranus_bigtts",
            text="不应重开",
            action="debate",
        ),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "failed"
    assert loaded["text"] == "原始文本"
    assert loaded["error_message"] == "tts failed"
    assert loaded["completed_at"] == failed["completed_at"]


def test_voice_store_upsert_after_cancel_keeps_terminal_metadata(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("原始文本"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="canceled",
    )

    store.upsert_utterance(
        VoiceUtterance(
            utterance_id="voice_1",
            run_id="run_1",
            source_event_id=6,
            request_id="req-1",
            speaker_kind="player",
            speaker_name="阿青",
            speaker="zh_female_vv_uranus_bigtts",
            text="不应重开",
            action="debate",
        ),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "canceled"
    assert loaded["text"] == "原始文本"
    assert loaded["last_source_event_id"] == 4
    assert loaded["duration_ms"] is None
    assert loaded["completed_at"] is None
    assert loaded["error_message"] is None


def test_voice_store_complete_after_failure_keeps_failure_metadata(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("原始文本"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.fail_utterance("voice_1", message="tts failed")
    failed = store.load_utterance("voice_1")
    assert failed is not None

    store.complete_utterance("voice_1", duration_ms=1200)

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "failed"
    assert loaded["error_message"] == "tts failed"
    assert loaded["duration_ms"] is None
    assert loaded["completed_at"] == failed["completed_at"]


def test_voice_store_fail_after_complete_keeps_completion_metadata(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("原始文本"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.complete_utterance("voice_1", duration_ms=1200)
    completed = store.load_utterance("voice_1")
    assert completed is not None

    store.fail_utterance("voice_1", message="tts failed")

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "complete"
    assert loaded["duration_ms"] == 1200
    assert loaded["error_message"] is None
    assert loaded["completed_at"] == completed["completed_at"]


def test_voice_store_complete_after_cancel_keeps_canceled_status(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("原始文本"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="canceled",
    )

    store.complete_utterance("voice_1", duration_ms=1200)

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "canceled"
    assert loaded["duration_ms"] is None
    assert loaded["completed_at"] is None
    assert loaded["error_message"] is None


def test_voice_store_fail_after_cancel_keeps_canceled_status(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance("原始文本"),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
        status="canceled",
    )

    store.fail_utterance("voice_1", message="tts failed")

    loaded = store.load_utterance("voice_1")
    assert loaded is not None
    assert loaded["status"] == "canceled"
    assert loaded["duration_ms"] is None
    assert loaded["completed_at"] is None
    assert loaded["error_message"] is None


def test_voice_store_rejects_incompatible_existing_utterance(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    store.upsert_utterance(
        utterance(),
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )

    with pytest.raises(ValueError):
        store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_1",
                run_id="run_1",
                source_event_id=4,
                request_id="req-1",
                speaker_kind="player",
                speaker_name="阿青",
                speaker="speaker-incompatible",
                text="同一条不同声音",
                action="debate",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )


def test_voice_store_incompatible_duplicate_chunk_raises_and_session_remains_usable(
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

    with pytest.raises(ValueError, match="incompatible audio"):
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

    store.fail_utterance("voice_1", message="tts failed")

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
