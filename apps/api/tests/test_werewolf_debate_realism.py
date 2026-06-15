from app.werewolf.debate_realism import (
    catchphrases_from_personality,
    debate_guidance_for_turn,
    dialogue_quality_warnings,
    lineup_quality_warnings,
    lineup_quality_warnings_from_players,
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
