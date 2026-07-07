from app.werewolf.live import LiveEvent
from app.werewolf.voice import (
    VoiceSpeakerConfig,
    build_voice_messages,
    chunk_text_for_tts,
    event_to_voice_utterance,
    is_public_speech_event,
)


def live_event(
    event_id: int,
    event_type: str,
    *,
    actor: str | None = None,
    action: str | None = None,
    payload: dict | None = None,
    phase: str | None = None,
) -> LiveEvent:
    return LiveEvent(
        id=event_id,
        type=event_type,
        run_id="run_1",
        session_id="game_1",
        created_at="2026-07-07T00:00:00Z",
        phase=phase,
        actor=actor,
        action=action,
        payload=payload or {},
    )


def test_public_speech_event_matches_supported_actions() -> None:
    event = live_event(
        4,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-1", "visible_text": "我先发言。"},
    )

    assert is_public_speech_event(event) is True


def test_private_or_non_speech_event_is_not_public_speech() -> None:
    night_event = live_event(
        5,
        "model_response_delta",
        actor="狼人",
        action="werewolf_discussion",
        payload={"request_id": "req-2", "visible_text": "今晚刀谁。"},
    )
    state_event = live_event(6, "state_updated", payload={"role": "werewolf"})

    assert is_public_speech_event(night_event) is False
    assert is_public_speech_event(state_event) is False


def test_chunk_text_for_tts_keeps_sentence_punctuation() -> None:
    chunks = chunk_text_for_tts("我是阿青，我先听后置位发言。警上信息不多！", max_chars=12)

    assert chunks == ["我是阿青，", "我先听后置位发言。", "警上信息不多！"]


def test_event_to_player_voice_utterance_uses_visible_text() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        8,
        "model_response_delta",
        actor="阿青",
        action="sheriff_speech",
        payload={"request_id": "req-8", "visible_text": "我竞选警长。"},
    )

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.source_event_id == 8
    assert utterance.request_id == "req-8"
    assert utterance.speaker_kind == "player"
    assert utterance.speaker_name == "阿青"
    assert utterance.speaker == "player"
    assert utterance.text == "我竞选警长。"


def test_event_to_judge_voice_utterance_for_phase_start_is_short() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(9, "phase_started", phase="night")

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.speaker_kind == "judge"
    assert utterance.speaker_name == "法官"
    assert utterance.speaker == "judge"
    assert utterance.text == "天黑请闭眼。"


def test_voice_messages_serialize_audio_chunks() -> None:
    start, chunk, end = build_voice_messages(
        utterance_id="voice_1",
        source_event_id=10,
        speaker_kind="player",
        speaker_name="阿青",
        audio=b"abc",
        mime_type="audio/mpeg",
        duration_ms=1200,
    )

    assert start["type"] == "voice_start"
    assert start["source_event_id"] == 10
    assert chunk == {
        "type": "audio_chunk",
        "utterance_id": "voice_1",
        "mime_type": "audio/mpeg",
        "data": "YWJj",
    }
    assert end == {"type": "voice_end", "utterance_id": "voice_1", "duration_ms": 1200}
