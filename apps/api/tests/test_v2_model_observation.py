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


def test_later_public_speech_cannot_be_the_reason_for_an_earlier_private_investigation() -> None:
    observations = observe_model_speech(
        ("12号预言家，昨晚验6号查杀。我验人逻辑：6号在3号位发言，我选他是因为前几位发言太像模板。"),
        hard_rules={},
        model_context={
            "known_events": {
                "events": [
                    {
                        "authority": "judge_fact",
                        "data": {
                            "ability_id": "seer.investigate",
                            "decision": {"target_player_id": "seat_6"},
                            "result": {"alignment": "werewolves"},
                        },
                        "event_ref": "knowledge-seer-night-1",
                        "kind": "private_ability_action_committed",
                        "known_at_seq": 258,
                        "visibility": "actor_private",
                    },
                    {
                        "authority": "player_statement",
                        "event_ref": "472",
                        "kind": "player_statement",
                        "known_at_seq": 472,
                        "speaker_ref": "seat_6",
                        "speech": "6号上警，不跳预言家。",
                        "visibility": "public",
                    },
                ]
            }
        },
    )

    assert observations == [
        {
            "code": "private_action_causality_contradiction",
            "severity": "warning",
            "confidence": "high",
            "detector_version": 1,
            "authority": "judge_fact",
            "signals": [
                {
                    "ability_id": "seer.investigate",
                    "target_ref": "seat_6",
                    "private_event_ref": "knowledge-seer-night-1",
                    "private_action_known_at_seq": 258,
                    "later_public_event_ref": "472",
                    "later_public_known_at_seq": 472,
                    "evidence": ("我验人逻辑：6号在3号位发言，我选他是因为前几位发言太像模板。"),
                }
            ],
            "effect": "observed_only",
        }
    ]


def test_explicitly_rejecting_later_speech_as_an_investigation_reason_is_not_flagged() -> None:
    observations = observe_model_speech(
        "我昨晚验6号，我的验人逻辑不是因为6号警上发言。",
        hard_rules={},
        model_context={
            "known_events": {
                "events": [
                    {
                        "data": {
                            "target_player_id": "seat_6",
                            "alignment": "werewolves",
                        },
                        "event_ref": "knowledge-seer-night-1",
                        "kind": "investigation_alignment",
                        "known_at_seq": 258,
                        "visibility": "actor_private",
                    },
                    {
                        "event_ref": "472",
                        "kind": "player_statement",
                        "known_at_seq": 472,
                        "speaker_ref": "seat_6",
                    },
                ]
            }
        },
    )

    assert observations == []


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


def test_unfair_silence_claim_is_observed_when_target_has_not_reached_turn() -> None:
    observations = observe_model_speech(
        ("可5号你是警长了，拿着1.5票的归票权，总得开口吧？一个字都不解释，确实让人心里打鼓。"),
        hard_rules={},
        model_context={
            "task": {
                "speech_progress": {
                    "current_speaker_ref": "seat_8",
                    "remaining_speaker_refs": ["seat_7", "seat_6", "seat_5"],
                }
            },
            "history": {
                "questions": [
                    {
                        "question_id": "question_471_1",
                        "status": "open",
                        "addressed_to": "seat_5",
                        "reply_opportunity": "awaiting_scheduled_turn",
                        "prior_relevant_statement_refs": ["437"],
                    }
                ]
            },
        },
    )

    assert [observation["code"] for observation in observations] == [
        "premature_silence_accusation",
        "prior_explanation_denial",
    ]
    assert all(observation["effect"] == "observed_only" for observation in observations)
    assert observations[0]["signals"][0]["target_ref"] == "seat_5"
    assert observations[0]["signals"][0]["reply_opportunity"] == ("awaiting_scheduled_turn")
    assert observations[1]["signals"][0]["prior_relevant_statement_refs"] == ["437"]


def test_awaiting_turn_wording_is_not_misclassified_as_a_silence_accusation() -> None:
    model_context = {
        "task": {
            "speech_progress": {
                "current_speaker_ref": "seat_8",
                "remaining_speaker_refs": ["seat_7", "seat_6", "seat_5"],
            }
        },
        "history": {
            "questions": [
                {
                    "question_id": "question_471_1",
                    "status": "open",
                    "addressed_to": "seat_5",
                    "reply_opportunity": "awaiting_scheduled_turn",
                    "prior_relevant_statement_refs": ["437"],
                },
            ]
        },
    }

    for speech in (
        "还没轮到5号回应，不能说他一个字都没解释，等他发言再判断。",
        "9号说5号一个字都没解释，但我不同意这个说法。",
    ):
        assert (
            observe_model_speech(
                speech,
                hard_rules={},
                model_context=model_context,
            )
            == []
        )


def test_silence_claim_after_target_turn_is_not_premature() -> None:
    observations = observe_model_speech(
        "5号你这一轮还是没有正面回应9号的问题。",
        hard_rules={},
        model_context={
            "task": {
                "speech_progress": {
                    "current_speaker_ref": "seat_6",
                    "remaining_speaker_refs": [],
                }
            },
            "history": {
                "questions": [
                    {
                        "question_id": "question_471_1",
                        "status": "open",
                        "addressed_to": "seat_5",
                        "reply_opportunity": "scheduled_turn_passed",
                    }
                ]
            },
        },
    )

    assert observations == []
