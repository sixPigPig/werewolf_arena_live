from __future__ import annotations

import pytest

from app.v2.model_observation import observe_model_speech


@pytest.mark.parametrize(
    "speech",
    [
        "我得和狼队友统一一下口径。",
        "这局双狼，我认为1号和2号就是两张狼牌。",
        "狼就是1号和2号，今天先出1号。",
    ],
)
def test_single_wolf_contradictions_are_observed_without_an_effect(
    speech: str,
) -> None:
    observations = observe_model_speech(
        speech,
        hard_rules={"werewolf_count": 1},
    )

    assert len(observations) == 1
    assert observations[0]["code"] == "wolf_cardinality_contradiction"
    assert observations[0]["configured_werewolf_count"] == 1
    assert observations[0]["effect"] == "observed_only"
    assert observations[0]["signals"]


@pytest.mark.parametrize(
    "speech",
    [
        "1号、2号里面开一狼。",
        "我的狼坑暂时放在3号、4号、6号。",
        "3号说双狼，但这不符合本局规则。",
        "本局只有我一个狼，不存在狼队友。",
    ],
)
def test_single_wolf_compatible_or_rejected_claims_are_not_flagged(
    speech: str,
) -> None:
    assert (
        observe_model_speech(
            speech,
            hard_rules={"werewolf_count": 1},
        )
        == []
    )


def test_unrelated_negation_does_not_hide_a_later_contradiction() -> None:
    observations = observe_model_speech(
        "我不是预言家，但我判断这局双狼。",
        hard_rules={"werewolf_count": 1},
    )

    assert observations[0]["code"] == "wolf_cardinality_contradiction"


def test_multi_wolf_speech_is_not_checked_by_single_wolf_detector() -> None:
    assert (
        observe_model_speech(
            "我和狼队友商量后认为1号、2号是双狼。",
            hard_rules={"werewolf_count": 2},
        )
        == []
    )


def test_public_vote_claim_is_compared_with_authoritative_timeline() -> None:
    observations = observe_model_speech(
        "2号、5号都给6号投了票，你却还要验自己的支持者。",
        hard_rules={"werewolf_count": 4},
        model_context={
            "public_timeline": {
                "schema_version": 1,
                "events": [
                    {
                        "kind": "day_vote",
                        "authority": "judge_fact",
                        "source_event_id": "562",
                        "record_seq": 562,
                        "action_type": "sheriff_vote",
                        "voter_ref": "seat_2",
                        "target_ref": "seat_7",
                    },
                    {
                        "kind": "day_vote",
                        "authority": "judge_fact",
                        "source_event_id": "564",
                        "record_seq": 564,
                        "action_type": "sheriff_vote",
                        "voter_ref": "seat_5",
                        "target_ref": "seat_7",
                    },
                ],
            }
        },
    )

    assert len(observations) == 1
    observation = observations[0]
    assert observation["code"] == "public_vote_fact_contradiction"
    assert observation["effect"] == "observed_only"
    assert observation["authority"] == "judge_fact"
    assert observation["conflicts"] == [
        {
            "voter_ref": "seat_2",
            "claimed_target_ref": "seat_6",
            "authoritative_target_ref": "seat_7",
            "source_event_id": "562",
            "record_seq": 562,
            "action_type": "sheriff_vote",
            "evidence": "2号、5号都给6号投了票，你却还要验自己的支持者。",
        },
        {
            "voter_ref": "seat_5",
            "claimed_target_ref": "seat_6",
            "authoritative_target_ref": "seat_7",
            "source_event_id": "564",
            "record_seq": 564,
            "action_type": "sheriff_vote",
            "evidence": "2号、5号都给6号投了票，你却还要验自己的支持者。",
        },
    ]


def test_real_response_wording_detects_both_sheriff_vote_conflicts() -> None:
    observations = observe_model_speech(
        (
            "我先回应6号，你查杀我当然不认。6号你预言家验人凭感觉的？"
            "再说你警徽流验2号5号，2号警上给你投了票，"
            "5号也给你投了票，你验自己支持者？"
        ),
        hard_rules={},
        model_context={
            "public_timeline": {
                "events": [
                    {
                        "kind": "day_vote",
                        "authority": "judge_fact",
                        "source_event_id": "562",
                        "record_seq": 562,
                        "action_type": "sheriff_vote",
                        "voter_ref": "seat_2",
                        "target_ref": "seat_7",
                    },
                    {
                        "kind": "day_vote",
                        "authority": "judge_fact",
                        "source_event_id": "564",
                        "record_seq": 564,
                        "action_type": "sheriff_vote",
                        "voter_ref": "seat_5",
                        "target_ref": "seat_7",
                    },
                ]
            }
        },
    )

    assert observations[0]["code"] == "public_vote_fact_contradiction"
    assert len(observations[0]["conflicts"]) == 2
    assert {conflict["voter_ref"] for conflict in observations[0]["conflicts"]} == {
        "seat_2",
        "seat_5",
    }
    assert {conflict["claimed_target_ref"] for conflict in observations[0]["conflicts"]} == {
        "seat_6"
    }


def test_public_vote_claim_can_resolve_you_from_direct_response() -> None:
    observations = observe_model_speech(
        "我先回应6号：2号、5号给你投了票，你还要验自己的支持者？",
        hard_rules={"werewolf_count": 4},
        model_context={
            "public_timeline": [
                {
                    "kind": "day_vote",
                    "authority": "judge_fact",
                    "voter_ref": "seat_2",
                    "target_ref": "seat_7",
                },
                {
                    "kind": "day_vote",
                    "authority": "judge_fact",
                    "voter_ref": "seat_5",
                    "target_ref": "seat_7",
                },
            ]
        },
    )

    assert observations[0]["code"] == "public_vote_fact_contradiction"
    assert {item["claimed_target_ref"] for item in observations[0]["conflicts"]} == {"seat_6"}


def test_legacy_judge_facts_are_still_checked() -> None:
    observations = observe_model_speech(
        "2号和5号都投给了6号。",
        hard_rules={},
        model_context={
            "public_state": {
                "judge_facts": [
                    {
                        "kind": "day_vote",
                        "source_event_id": "vote-2",
                        "voter_ref": "seat_2",
                        "target_ref": "seat_7",
                    },
                    {
                        "kind": "day_vote",
                        "source_event_id": "vote-5",
                        "voter_ref": "seat_5",
                        "target_ref": "seat_7",
                    },
                ]
            }
        },
    )

    assert observations[0]["code"] == "public_vote_fact_contradiction"
    assert len(observations[0]["conflicts"]) == 2


def test_multi_digit_seat_without_suffix_is_not_truncated() -> None:
    observations = observe_model_speech(
        "12投10。",
        hard_rules={},
        model_context={
            "public_timeline": {
                "events": [
                    {
                        "kind": "day_vote",
                        "authority": "judge_fact",
                        "voter_ref": "seat_12",
                        "target_ref": "seat_11",
                    }
                ]
            }
        },
    )

    conflict = observations[0]["conflicts"][0]
    assert conflict["voter_ref"] == "seat_12"
    assert conflict["claimed_target_ref"] == "seat_10"


@pytest.mark.parametrize(
    "speech",
    [
        "2号、5号都给7号投了票。",
        "2号、5号没有给6号投票。",
        "如果2号、5号给6号投票，我再重新判断。",
        "2号、5号是不是给6号投了票？",
        "我想确认，2号、5号给6号投票了吗？",
        "下一轮2号、5号应该给6号投票。",
        "2号、5号支持6号的发言，但票投给了7号。",
        "8号刚才说，2号、5号给6号投了票。",
        "2号、5号给6号投票是错误信息。",
        "我不认为2号、5号给6号投了票。",
        "2号、5号给6号投票的可能性很低。",
        "别再说2号、5号给6号投了票了。",
    ],
)
def test_correct_uncertain_or_non_vote_statements_are_not_flagged(
    speech: str,
) -> None:
    assert (
        observe_model_speech(
            speech,
            hard_rules={},
            model_context={
                "public_timeline": {
                    "events": [
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "voter_ref": "seat_2",
                            "target_ref": "seat_7",
                        },
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "voter_ref": "seat_5",
                            "target_ref": "seat_7",
                        },
                    ]
                }
            },
        )
        == []
    )


def test_second_person_vote_target_does_not_reuse_stale_cross_sentence_addressee() -> None:
    assert (
        observe_model_speech(
            "我先回应6号，这部分说完。接着聊7号：2号给你投了票。",
            hard_rules={},
            model_context={
                "public_timeline": {
                    "events": [
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "voter_ref": "seat_2",
                            "target_ref": "seat_7",
                        }
                    ]
                }
            },
        )
        == []
    )


def test_malformed_fact_fields_cannot_break_passive_observation() -> None:
    observations = observe_model_speech(
        "2号给6号投了票。",
        hard_rules={},
        model_context={
            "public_timeline": {
                "events": [
                    {
                        "kind": "day_vote",
                        "authority": "judge_fact",
                        "source_event_id": [],
                        "record_seq": [],
                        "action_type": [],
                        "voter_ref": "seat_2",
                        "target_ref": "seat_7",
                    }
                ]
            }
        },
    )

    assert observations[0]["code"] == "public_vote_fact_contradiction"
    assert observations[0]["effect"] == "observed_only"


def test_detector_failure_is_reported_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_detector(*_args, **_kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(
        "app.v2.model_observation._observe_public_vote_facts",
        fail_detector,
    )

    assert observe_model_speech("正常模型原话", hard_rules={}) == [
        {
            "code": "model_observation_failed",
            "severity": "warning",
            "confidence": "unknown",
            "detector_version": 1,
            "error_type": "RuntimeError",
            "effect": "observed_only",
        }
    ]


def test_vote_observation_does_not_disable_wolf_cardinality_observation() -> None:
    observations = observe_model_speech(
        "这局是双狼，而且2号和5号都给6号投了票。",
        hard_rules={"werewolf_count": 1},
        model_context={
            "public_timeline": {
                "events": [
                    {
                        "kind": "day_vote",
                        "authority": "judge_fact",
                        "voter_ref": "seat_2",
                        "target_ref": "seat_7",
                    },
                    {
                        "kind": "day_vote",
                        "authority": "judge_fact",
                        "voter_ref": "seat_5",
                        "target_ref": "seat_7",
                    },
                ]
            }
        },
    )

    assert [item["code"] for item in observations] == [
        "wolf_cardinality_contradiction",
        "public_vote_fact_contradiction",
    ]


def test_unverified_vote_claim_in_timeline_is_not_authoritative() -> None:
    assert (
        observe_model_speech(
            "2号给6号投了票。",
            hard_rules={},
            model_context={
                "public_timeline": {
                    "events": [
                        {
                            "kind": "day_vote",
                            "authority": "player_claim_unverified",
                            "voter_ref": "seat_2",
                            "target_ref": "seat_7",
                        }
                    ]
                }
            },
        )
        == []
    )


def test_matching_historical_vote_prevents_ambiguous_cross_round_warning() -> None:
    assert (
        observe_model_speech(
            "2号投了6号。",
            hard_rules={},
            model_context={
                "public_timeline": {
                    "events": [
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "record_seq": 10,
                            "voter_ref": "seat_2",
                            "target_ref": "seat_6",
                        },
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "record_seq": 20,
                            "voter_ref": "seat_2",
                            "target_ref": "seat_7",
                        },
                    ]
                }
            },
        )
        == []
    )
