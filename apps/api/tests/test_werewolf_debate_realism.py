from app.werewolf.debate_realism import (
    SpeechMissionV1,
    assign_speech_mission,
    catchphrases_from_personality,
    debate_guidance_for_turn,
    dialogue_quality_warnings,
    evaluate_speech_quality,
    lineup_quality_warnings,
    lineup_quality_warnings_from_players,
    proposition_signatures,
    repeated_phrase_candidates,
)
from app.werewolf.player_configs import PlayerConfig


ANALYTICAL_PERSONALITY = (
    "重视票型、发言顺序和行为一致性。\n"
    "角色简介: 沉稳控场，喜欢先盘逻辑再给站边。\n"
    "常用表达: 我先盘票型；这里不急着站死"
)


def test_repeated_phrase_candidates_detects_round_level_repetition() -> None:
    messages = [
        "守夜潜行第一夜出局，狼人刀法值得关注。先听一圈发言，我盘逻辑不急着站边。",
        "守夜潜行第一夜出局，刀法很有针对性。先不站死，听后面发言再盘票型。",
        "守夜潜行第一夜被刀，刀法有指向性。我不急着站边，但会留意谁在带节奏。",
    ]

    phrases = repeated_phrase_candidates(messages, min_chars=4, min_count=2)

    assert "守夜潜行" in phrases
    assert "不急着站" in phrases
    assert len(phrases) <= 8


def test_catchphrases_from_personality_reads_profile_line() -> None:
    assert catchphrases_from_personality(ANALYTICAL_PERSONALITY) == [
        "我先盘票型",
        "这里不急着站死",
    ]


def test_dialogue_quality_warnings_detects_repetition_and_catchphrase_overuse() -> None:
    warnings = dialogue_quality_warnings(
        text="我先盘票型。第一轮全票挂警徽定狼，这里不急着站死，先听后置位补充。",
        prior_texts=[
            "我先盘票型。第一轮全票挂警徽定狼，说明大家都觉得他发言差。",
            "第一轮全票挂警徽定狼，但我不急着站边。",
        ],
        personality=ANALYTICAL_PERSONALITY,
    )

    assert "catchphrase_overuse" in warnings
    assert "repeated_debate_phrase" in warnings
    assert "low_novelty_debate" in warnings


def test_dialogue_quality_allows_first_catchphrase_use() -> None:
    warnings = dialogue_quality_warnings(
        text="我先盘票型。今晚5号玩家倒牌，先看票型。",
        prior_texts=[],
        personality=ANALYTICAL_PERSONALITY,
    )

    assert "catchphrase_overuse" not in warnings


def test_dialogue_quality_flags_repeated_catchphrase_use() -> None:
    warnings = dialogue_quality_warnings(
        text="我先盘票型。第二轮继续看投票。",
        prior_texts=["我先盘票型。第一轮先听发言。"],
        personality=ANALYTICAL_PERSONALITY,
    )

    assert "catchphrase_overuse" in warnings


def test_repeated_phrase_ignores_player_reference_only() -> None:
    warnings = dialogue_quality_warnings(
        text="我怀疑5号玩家，因为他的投票位置靠后。",
        prior_texts=["5号玩家需要解释自己的投票。"],
        personality="",
    )

    assert "repeated_debate_phrase" not in warnings


def test_repeated_phrase_ignores_predicate_plus_player_reference() -> None:
    warnings = dialogue_quality_warnings(
        text="我怀疑5号玩家。",
        prior_texts=["我也怀疑5号玩家。"],
        personality="",
    )

    assert "repeated_debate_phrase" not in warnings


def test_repeated_phrase_ignores_shared_role_vote_vocabulary() -> None:
    warnings = dialogue_quality_warnings(
        text="我认为预言家查验要先放一放，今天投票位置更能说明问题。",
        prior_texts=["预言家查验先听完，投票位置需要每个人解释清楚。"],
        personality="",
    )

    assert "repeated_debate_phrase" not in warnings


def test_repeated_phrase_still_flags_actual_phrase_reuse() -> None:
    warnings = dialogue_quality_warnings(
        text="第一轮全票挂警徽定狼，我现在还是这个判断。",
        prior_texts=["第一轮全票挂警徽定狼，所以先把他放进狼坑。"],
        personality="",
    )

    assert "repeated_debate_phrase" in warnings


def test_debate_guidance_for_turn_assigns_distinct_speaker_jobs() -> None:
    first = debate_guidance_for_turn(
        speaker="票台换票",
        active_players=["票台换票", "狼啸听风", "烛火潜行"],
        prior_messages=[],
        personality=ANALYTICAL_PERSONALITY,
    )
    final = debate_guidance_for_turn(
        speaker="烛火潜行",
        active_players=["票台换票", "狼啸听风", "烛火潜行"],
        prior_messages=[
            "票台换票：我先盘票型。第一轮全票挂警徽定狼。",
            "狼啸听风：盘票型。票台换票行为矛盾。",
        ],
        personality=ANALYTICAL_PERSONALITY,
    )

    assert any("第 1/3 位" in line for line in first)
    assert any("开一个新信息点" in line for line in first)
    assert any("第 3/3 位" in line for line in final)
    assert any("明确票口" in line for line in final)
    assert any("避免复用" in line for line in final)


def test_debate_guidance_for_turn_uses_known_speaker_position() -> None:
    guidance = debate_guidance_for_turn(
        speaker="烛火潜行",
        active_players=["票台换票", "狼啸听风", "烛火潜行"],
        prior_messages=[],
        personality=ANALYTICAL_PERSONALITY,
    )

    assert any("第 3/3 位" in line for line in guidance)
    assert any("明确票口" in line for line in guidance)


def test_speech_mission_scheduler_is_deterministic_and_spreads_round_tasks() -> None:
    order = [f"玩家{seat}" for seat in range(1, 7)]
    first = [
        assign_speech_mission(
            round_number=2,
            stage="debate",
            speaker=speaker,
            speech_order=order,
            personality_id="balanced",
        )
        for speaker in order
    ]
    second = [
        assign_speech_mission(
            round_number=2,
            stage="debate",
            speaker=speaker,
            speech_order=order,
            personality_id="balanced",
        )
        for speaker in order
    ]

    assert [mission.to_dict() for mission in first] == [
        mission.to_dict() for mission in second
    ]
    assert len({mission.kind for mission in first}) == 6


def test_speech_mission_scheduler_inserts_counterpoint_after_unsupported_agreement() -> None:
    mission = assign_speech_mission(
        round_number=1,
        stage="debate",
        speaker="玩家3",
        speech_order=["玩家1", "玩家2", "玩家3"],
        prior_messages=[
            "我同意前面，今天也投5号玩家。",
            "我赞同这个方向，继续跟票5号玩家。",
        ],
    )

    assert mission.kind == "devil_advocate"
    assert mission.reason_code == "consecutive_agreement_without_evidence"


def test_speech_mission_uses_consolidator_when_public_evidence_is_missing() -> None:
    missions = [
        assign_speech_mission(
            round_number=round_number,
            stage="sheriff_speech",
            speaker="玩家1",
            speech_order=["玩家1"],
            has_public_evidence=False,
        )
        for round_number in range(1, 20)
    ]

    assert any(mission.reason_code == "limited_public_evidence" for mission in missions)
    assert all(
        mission.kind == "consolidator"
        for mission in missions
        if mission.reason_code == "limited_public_evidence"
    )


def test_proposition_signatures_capture_vote_identity_and_polarity() -> None:
    signatures = proposition_signatures(
        "3号玩家改票5号玩家，我不投7号玩家；8号玩家不像狼人。",
        actor="seat:2",
    )
    semantic_keys = {signature.semantic_key() for signature in signatures}

    assert ("seat:3", "vote", "seat:5", "positive") in semantic_keys
    assert ("seat:2", "vote", "seat:7", "negative") in semantic_keys
    assert ("seat:8", "identity", "狼人", "negative") in semantic_keys


def test_speech_quality_requires_rewrite_for_copy_without_new_proposition() -> None:
    mission = SpeechMissionV1(
        schema_version=1,
        kind="contradiction_hunter",
        instruction="指出具体矛盾。",
        reason_code="test",
    )
    report = evaluate_speech_quality(
        text="第一轮全票挂警徽定狼，所以我仍然保持这个判断。",
        prior_texts=["第一轮全票挂警徽定狼，所以先把他放进狼坑。"],
        mission=mission,
    )

    assert report.requires_rewrite is True
    assert "repeated_debate_phrase" in report.hard_failure_codes
    assert report.new_proposition_count == 0
    assert report.to_dict()["schema_version"] == 1


def test_speech_quality_allows_similar_opening_with_new_public_fact() -> None:
    mission = SpeechMissionV1(
        schema_version=1,
        kind="vote_analyst",
        instruction="解释票型变化。",
        reason_code="test",
    )
    report = evaluate_speech_quality(
        text="我也先盘票型，但3号玩家刚刚改票5号玩家，这个变化需要解释。",
        prior_texts=["我先盘票型，目前重点听5号玩家的发言。"],
        mission=mission,
    )

    assert report.new_proposition_count >= 1
    assert report.requires_rewrite is False
    assert report.mission_completed is True


def test_speech_quality_flags_group_agreement_for_counterpoint_mission() -> None:
    mission = SpeechMissionV1(
        schema_version=1,
        kind="devil_advocate",
        instruction="提出反例。",
        reason_code="consecutive_agreement_without_evidence",
    )
    report = evaluate_speech_quality(
        text="我同意前面，今天继续跟票5号玩家。",
        prior_texts=["我赞同这个方向，今天也投5号玩家。"],
        mission=mission,
    )

    assert "group_agreement_without_evidence" in report.hard_failure_codes
    assert all(
        0 <= start <= end <= len("我同意前面，今天继续跟票5号玩家。")
        for issue in report.issues
        for start, end in issue.evidence_spans
    )


def test_lineup_quality_warnings_detects_homogeneous_profiles() -> None:
    configs = [
        PlayerConfig(
            seat=seat,
            profile_id=f"profile-{seat}",
            name=f"玩家{seat}",
            model="model",
            personality_id="analytical",
            personality=ANALYTICAL_PERSONALITY,
            appearance_id="default",
            avatar_prompt="",
            tags=("控场", "复盘"),
        )
        for seat in range(1, 5)
    ]

    warnings = lineup_quality_warnings(configs)

    assert warnings == [
        {
            "code": "homogeneous_personality_lineup",
            "detail": "4 players share personality_id analytical.",
        },
        {
            "code": "shared_catchphrase_lineup",
            "detail": "4 players share catchphrase 我先盘票型.",
        },
        {
            "code": "shared_tag_lineup",
            "detail": "4 players share tag 控场.",
        },
    ]


def test_lineup_quality_warnings_from_players_handles_normal_player_dict_tags() -> None:
    players = [
        {
            "seat": seat,
            "profile_id": f"profile-{seat}",
            "name": f"玩家{seat}",
            "model": "model",
            "personality_id": "analytical",
            "personality": ANALYTICAL_PERSONALITY,
            "appearance_id": "default",
            "avatar_prompt": "",
            "tags": ["控场", "复盘"],
        }
        for seat in range(1, 5)
    ]

    warnings = lineup_quality_warnings_from_players(players)

    assert warnings == [
        {
            "code": "homogeneous_personality_lineup",
            "detail": "4 players share personality_id analytical.",
        },
        {
            "code": "shared_catchphrase_lineup",
            "detail": "4 players share catchphrase 我先盘票型.",
        },
        {
            "code": "shared_tag_lineup",
            "detail": "4 players share tag 控场.",
        },
    ]


def test_lineup_quality_warnings_from_players_ignores_malformed_or_missing_tags() -> None:
    players = [
        {
            "seat": 1,
            "profile_id": "profile-1",
            "name": "玩家1",
            "model": "model",
            "personality_id": "analytical",
            "personality": ANALYTICAL_PERSONALITY,
            "appearance_id": "default",
            "avatar_prompt": "",
            "tags": "控场",
        },
        {
            "seat": 2,
            "profile_id": "profile-2",
            "name": "玩家2",
            "model": "model",
            "personality_id": "analytical",
            "personality": ANALYTICAL_PERSONALITY,
            "appearance_id": "default",
            "avatar_prompt": "",
            "tags": 7,
        },
        {
            "seat": 3,
            "profile_id": "profile-3",
            "name": "玩家3",
            "model": "model",
            "personality_id": "analytical",
            "personality": ANALYTICAL_PERSONALITY,
            "appearance_id": "default",
            "avatar_prompt": "",
            "tags": None,
        },
        {
            "seat": 4,
            "profile_id": "profile-4",
            "name": "玩家4",
            "model": "model",
            "personality_id": "analytical",
            "personality": ANALYTICAL_PERSONALITY,
            "appearance_id": "default",
            "avatar_prompt": "",
        },
    ]

    warnings = lineup_quality_warnings_from_players(players)

    assert warnings == [
        {
            "code": "homogeneous_personality_lineup",
            "detail": "4 players share personality_id analytical.",
        },
        {
            "code": "shared_catchphrase_lineup",
            "detail": "4 players share catchphrase 我先盘票型.",
        },
    ]
