import pytest

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
        payload={"request_id": "req-1", "visible_text": "我先发言。", "is_public": True},
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


def test_missing_or_false_public_flag_is_not_public_speech() -> None:
    missing_flag = live_event(
        7,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-7", "visible_text": "这段看起来能播。"},
    )
    false_flag = live_event(
        8,
        "model_response_delta",
        actor="阿青",
        action="sheriff_speech",
        payload={
            "request_id": "req-8",
            "visible_text": "这段也看起来能播。",
            "is_public": False,
        },
    )

    assert is_public_speech_event(missing_flag) is False
    assert is_public_speech_event(false_flag) is False


def test_chunk_text_for_tts_keeps_sentence_punctuation() -> None:
    chunks = chunk_text_for_tts("我是阿青，我先听后置位发言。警上信息不多！", max_chars=12)

    assert chunks == ["我是阿青，", "我先听后置位发言。", "警上信息不多！"]


def test_chunk_text_for_tts_rejects_non_positive_max_chars() -> None:
    with pytest.raises(ValueError, match="^max_chars must be positive$"):
        chunk_text_for_tts("我是阿青。", max_chars=0)


def test_event_to_player_voice_utterance_uses_visible_text() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        8,
        "model_response_delta",
        actor="阿青",
        action="sheriff_speech",
        payload={"request_id": "req-8", "visible_text": "我竞选警长。", "is_public": True},
    )

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.source_event_id == 8
    assert utterance.request_id == "req-8"
    assert utterance.speaker_kind == "player"
    assert utterance.speaker_name == "阿青"
    assert utterance.speaker == "player"
    assert utterance.text == "我竞选警长。"


def test_event_to_voice_utterance_ignores_non_public_visible_text() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    missing_flag = live_event(
        11,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-11", "visible_text": "别把我私下说的话播出去。"},
    )
    false_flag = live_event(
        12,
        "model_response_delta",
        actor="阿青",
        action="sheriff_pk_speech",
        payload={
            "request_id": "req-12",
            "visible_text": "这个 payload 很诱人但不是公开文本。",
            "is_public": False,
        },
    )

    assert event_to_voice_utterance(missing_flag, config) is None
    assert event_to_voice_utterance(false_flag, config) is None


def test_event_to_voice_utterance_ignores_private_action_visible_text() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        13,
        "model_response_delta",
        actor="狼人",
        action="werewolf_discussion",
        payload={
            "request_id": "req-13",
            "visible_text": "今晚刀谁。",
            "is_public": True,
        },
    )

    assert event_to_voice_utterance(event, config) is None


def test_event_to_judge_voice_utterance_for_phase_start_is_short() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(9, "phase_started", phase="night")

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.speaker_kind == "judge"
    assert utterance.speaker_name == "法官"
    assert utterance.speaker == "judge"
    assert utterance.text == "天黑请闭眼。"


def test_game_completed_judge_voice_whitelists_winner_label() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    known_winner = live_event(14, "game_completed", payload={"winner": "狼人阵营"})
    unknown_winner = live_event(
        15,
        "game_completed",
        payload={"winner": "狼人阵营，隐藏调试信息"},
    )

    known_utterance = event_to_voice_utterance(known_winner, config)
    unknown_utterance = event_to_voice_utterance(unknown_winner, config)

    assert known_utterance is not None
    assert known_utterance.text == "对局结束，狼人阵营获胜。"
    assert unknown_utterance is not None
    assert unknown_utterance.text == "对局结束，胜利阵营获胜。"


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
