import pytest

from app.werewolf.live import LiveEvent
from app.werewolf.voice import (
    VoiceSpeakerConfig,
    build_voice_messages,
    chunk_text_for_tts,
    deterministic_voice_utterance_id,
    event_to_voice_materialization,
    event_to_voice_utterance,
    is_public_complete_speech_event,
    is_public_speech_event,
    is_static_judge_voice_asset_used,
    voice_job_candidate,
)
from app.werewolf.voice_stream import build_voice_playback_coverage


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


def test_complete_public_speech_is_materialized_from_action_parsed() -> None:
    event = live_event(
        9,
        "action_parsed",
        actor="阿青",
        action="debate",
        payload={
            "request_id": "req-final",
            "visible_result": {"say": "这是最终完整发言。"},
        },
    )

    utterance = event_to_voice_materialization(
        event,
        VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge"),
        player_seats={"阿青": 1},
    )

    assert is_public_complete_speech_event(event) is True
    assert voice_job_candidate(event) == "player"
    assert utterance is not None
    assert utterance.utterance_id == deterministic_voice_utterance_id("run_1", 9, "player")
    assert utterance.request_id == "req-final"
    assert utterance.speaker_name == "1号玩家"
    assert utterance.text == "这是最终完整发言。"


def test_game_resumed_uses_resume_judge_voice() -> None:
    event = live_event(10, "game_resumed", payload={"resume_from_round": 4})

    utterance = event_to_voice_materialization(
        event,
        VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge"),
        player_seats={},
    )

    assert voice_job_candidate(event) == "judge"
    assert utterance is not None
    assert utterance.text == "本局游戏继续。"
    assert utterance.static_asset_id == "game_resume"
    assert is_static_judge_voice_asset_used("game_resume") is True


def test_voice_job_candidate_rejects_private_and_delta_events() -> None:
    public_delta = live_event(
        10,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"is_public": True, "visible_text": "临时增量"},
    )
    private_action = live_event(
        11,
        "action_parsed",
        actor="狼人",
        action="werewolf_discuss",
        payload={"visible_result": {"say": "秘密讨论"}},
    )
    explicit_day = live_event(
        12,
        "phase_started",
        phase="day",
        payload={"narration_mode": "explicit_v1"},
    )

    assert voice_job_candidate(public_delta) is None
    assert voice_job_candidate(private_action) is None
    assert voice_job_candidate(explicit_day) is None


def test_terminal_effective_voice_coverage_counts_static_fallback() -> None:
    events = [
        {
            "id": 7,
            "type": "game_completed",
            "run_id": "run_1",
            "session_id": "game_1",
            "created_at": "2026-07-07T00:00:00Z",
            "payload": {"winner": "好人阵营"},
        }
    ]
    fallback_voice = {
        "utterance_id": "static_judge_7_game_over_villagers",
        "source_event_id": 7,
        "speaker_kind": "judge",
    }

    covered = build_voice_playback_coverage(events, [fallback_voice])
    missing = build_voice_playback_coverage(events, [])

    assert covered == {
        "narratable_event_count": 1,
        "effective_voice_event_count": 1,
        "missing_narratable_event_count": 0,
        "terminal_judge_voice_present": True,
        "voice_materialization_lag_ms": None,
    }
    assert missing["missing_narratable_event_count"] == 1
    assert missing["terminal_judge_voice_present"] is False


def test_private_summary_delta_is_never_a_voice_speech_event() -> None:
    event = live_event(
        14,
        "model_response_delta",
        actor="阿青",
        action="summarize",
        payload={
            "request_id": "req-summary",
            "visible_text": "这一轮重点复盘票型。",
            "is_public": True,
        },
        phase="summary",
    )

    utterance = event_to_voice_utterance(
        event,
        VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge"),
        player_seats={"阿青": 1},
    )

    assert is_public_speech_event(event) is False
    assert utterance is None


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
    assert utterance.speaker_name == "当前玩家"
    assert utterance.speaker == "player"
    assert utterance.text == "我竞选警长。"


def test_event_to_player_voice_utterance_uses_seat_label_when_available() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        8,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-8", "visible_text": "我先发言。", "is_public": True},
    )

    utterance = event_to_voice_utterance(event, config, player_seats={"阿青": 1})

    assert utterance is not None
    assert utterance.speaker_kind == "player"
    assert utterance.speaker_name == "1号玩家"
    assert utterance.text == "我先发言。"


def test_event_to_player_voice_utterance_preserves_model_visible_text() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        8,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={
            "request_id": "req-8",
            "visible_text": "我觉得白石像狼，先听南风发言。",
            "is_public": True,
        },
    )

    utterance = event_to_voice_utterance(
        event,
        config,
        player_seats={"阿青": 1, "白石": 2, "南风": 3},
    )

    assert utterance is not None
    assert utterance.speaker_name == "1号玩家"
    assert utterance.text == "我觉得白石像狼，先听南风发言。"


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
    assert utterance.text == "夜晚降临，所有玩家请闭眼。"
    assert utterance.static_asset_id == "night_start"


@pytest.mark.parametrize(
    ("action", "expected_text", "expected_asset_id"),
    [
        ("remove", "狼人请选择今晚袭击的目标。", "werewolves_choose"),
        ("protect", "请选择今晚守护的玩家。", "guard_choose"),
        ("investigate", "请选择今晚查验的玩家。", "seer_choose"),
        ("witch_save", "你是否使用解药？", "witch_save"),
        (
            "witch_poison",
            "你是否使用毒药？如果使用，请选择毒杀目标。",
            "witch_poison",
        ),
    ],
)
def test_night_action_request_uses_managed_judge_voice_asset(
    action: str,
    expected_text: str,
    expected_asset_id: str,
) -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(10, "action_requested", action=action, phase="night")

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.speaker_kind == "judge"
    assert utterance.text == expected_text
    assert utterance.static_asset_id == expected_asset_id


@pytest.mark.parametrize(
    ("cue", "expected_text"),
    [
        ("werewolves_wake", "狼人请睁眼，请互相确认队友。"),
        ("werewolves_sleep", "狼人请闭眼。"),
        ("guard_wake", "守卫请睁眼。"),
        ("guard_sleep", "守卫请闭眼。"),
        ("seer_wake", "预言家请睁眼。"),
        ("seer_sleep", "预言家请闭眼。"),
        ("witch_wake", "女巫请睁眼。"),
        ("witch_sleep", "女巫请闭眼。"),
    ],
)
def test_night_role_cue_uses_managed_judge_voice_asset(
    cue: str,
    expected_text: str,
) -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(11, "judge_cue", action=cue, phase="night")

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.text == expected_text
    assert utterance.static_asset_id == cue


def test_witch_death_cue_names_attacked_seat_before_save_prompt() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        12,
        "judge_cue",
        action="witch_death",
        phase="night",
        payload={"target": "8号玩家"},
    )

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.text == "今晚被狼人袭击的玩家是8号玩家。"
    assert utterance.static_asset_id == "witch_death_seat_08"


def test_sheriff_raise_hands_cue_uses_managed_static_asset() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        13,
        "judge_cue",
        action="sheriff_raise_hands",
        phase="day",
    )

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.text == "想要竞选警长的玩家请举手。"
    assert utterance.static_asset_id == "sheriff_raise_hands"


def test_explicit_judge_cue_is_authoritative_and_state_fallback_is_suppressed() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    state_event = live_event(
        14,
        "state_updated",
        action="exile_resolved",
        phase="vote",
        payload={
            "narration_mode": "explicit_v1",
            "exiled": "8号玩家",
        },
    )
    cue_event = live_event(
        15,
        "judge_cue",
        action="exile_result",
        phase="vote",
        payload={
            "schema_version": 1,
            "cue_id": "exile_result",
            "visible_text": "8号玩家得票最高，被放逐出局。",
            "static_asset_id": "exile_result_seat_08",
            "params": {"player": "8号玩家"},
        },
    )

    assert event_to_voice_utterance(state_event, config) is None
    utterance = event_to_voice_utterance(cue_event, config)
    assert utterance is not None
    assert utterance.text == "8号玩家得票最高，被放逐出局。"
    assert utterance.static_asset_id == "exile_result_seat_08"


def test_speech_order_request_prompts_sheriff_with_managed_static_asset() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        15,
        "action_requested",
        actor="阿青",
        action="speech_order",
        phase="day",
    )

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.speaker_kind == "judge"
    assert utterance.text == "请警长选择从警左或警右开始发言。"
    assert utterance.static_asset_id == "sheriff_choose_badge_side"
    assert is_static_judge_voice_asset_used("sheriff_choose_badge_side") is True


def test_sheriff_election_result_uses_managed_seat_asset() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        16,
        "state_updated",
        actor="阿青",
        phase="day",
        payload={"sheriff": "阿青", "sheriff_elected": "阿青"},
    )

    utterance = event_to_voice_utterance(
        event,
        config,
        player_seats={"阿青": 3},
    )

    assert utterance is not None
    assert utterance.speaker_kind == "judge"
    assert utterance.text == "3号玩家 当选警长，获得警徽。"
    assert utterance.static_asset_id == "sheriff_result_seat_03"


def test_summary_phase_judge_voice_announces_public_resolution() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(16, "phase_started", phase="summary")

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.speaker_kind == "judge"
    assert utterance.speaker_name == "法官"
    assert utterance.text == "现在公布本轮结算。"
    assert utterance.static_asset_id is None


def test_day_phase_with_multiple_night_deaths_uses_dynamic_seat_line() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(10, "phase_started", phase="day")

    utterance = event_to_voice_utterance(
        event,
        config,
        player_seats={"阿青": 1, "白石": 2},
        previous_night_deaths=("阿青", "白石"),
    )

    assert utterance is not None
    assert utterance.speaker_kind == "judge"
    assert utterance.text == "昨夜死亡的玩家是 1号玩家、2号玩家。"
    assert utterance.static_asset_id is None


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
    assert known_utterance.text == "游戏结束，狼人阵营获胜。"
    assert known_utterance.static_asset_id == "game_over_wolves"
    assert unknown_utterance is not None
    assert unknown_utterance.text == "游戏结束，胜利阵营获胜。"
    assert unknown_utterance.static_asset_id is None


def test_voice_messages_serialize_audio_chunks() -> None:
    start, chunk, end = build_voice_messages(
        utterance_id="voice_1",
        source_event_id=10,
        speaker_kind="player",
        speaker_name="阿青",
        audio=b"abc",
        mime_type="audio/L16",
        duration_ms=1200,
        audio_format="pcm",
        sample_rate=24000,
        chunk_index=3,
    )

    assert start["type"] == "voice_start"
    assert start["source_event_id"] == 10
    assert start["audio_format"] == "pcm"
    assert start["sample_rate"] == 24000
    assert chunk == {
        "type": "audio_chunk",
        "utterance_id": "voice_1",
        "chunk_index": 3,
        "mime_type": "audio/L16",
        "audio_format": "pcm",
        "sample_rate": 24000,
        "data": "YWJj",
    }
    assert end == {"type": "voice_end", "utterance_id": "voice_1", "duration_ms": 1200}
