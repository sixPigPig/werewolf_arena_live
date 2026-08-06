from __future__ import annotations

import pytest

from app.v2.model_observation import _vote_claims, observe_model_speech


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


@pytest.mark.parametrize(
    "speech,target_ref",
    [
        (
            "今天全票出3号！3号要是真女巫，晚上直接毒我就好，轮次不亏。",
            "seat_3",
        ),
        (
            "今天出3号，就算推错了，你真女巫有毒药，也不算血亏。",
            "seat_3",
        ),
        (
            "全票冲3号，推错了3号真女巫有毒药，也不耽误轮次。",
            "seat_3",
        ),
    ],
)
def test_post_elimination_witch_poison_claim_is_observed_without_an_effect(
    speech: str,
    target_ref: str,
) -> None:
    observations = observe_model_speech(
        speech,
        hard_rules={
            "ability_lifecycle": {
                "active_abilities_require_alive": True,
                "eliminated_players_can_act_in_later_windows": False,
                "death_triggered_exceptions": ["hunter.death_shot"],
            }
        },
    )

    assert len(observations) == 1
    observation = observations[0]
    assert observation["code"] == "post_elimination_ability_contradiction"
    assert observation["severity"] == "warning"
    assert observation["confidence"] == "high"
    assert observation["authority"] == "judge_fact"
    assert observation["effect"] == "observed_only"
    assert observation["signals"][0]["target_ref"] == target_ref
    assert observation["signals"][0]["ability_id"] == "witch.poison"
    assert observation["signals"][0]["contradiction"] == ("eliminated_player_later_active_ability")
    assert "女巫" in observation["signals"][0]["evidence"]


@pytest.mark.parametrize(
    "speech",
    [
        "今天全票出7号，我是真女巫，晚上会毒8号。",
        "今天出3号；如果她是真女巫，出局后也没法再用毒药。",
        "今天出3号，她自称女巫，但毒药是否还在不能坐实。",
    ],
)
def test_compatible_witch_poison_claim_is_not_flagged(speech: str) -> None:
    assert (
        observe_model_speech(
            speech,
            hard_rules={
                "ability_lifecycle": {
                    "active_abilities_require_alive": True,
                    "eliminated_players_can_act_in_later_windows": False,
                    "death_triggered_exceptions": ["hunter.death_shot"],
                }
            },
        )
        == []
    )


def test_legacy_rules_without_ability_lifecycle_do_not_enable_the_observer() -> None:
    assert (
        observe_model_speech(
            "今天出3号，推错了3号真女巫晚上还能毒我。",
            hard_rules={},
        )
        == []
    )


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


def _public_check_chronology_events() -> list[dict[str, object]]:
    return [
        {
            "kind": "player_statement",
            "visibility": "public",
            "authority": "player_claim_unverified",
            "speaker_ref": "seat_9",
            "event_ref": "984",
            "known_at_seq": 984,
            "record_seq": 984,
            "speech": "9号发言。3号倒牌后我认为6号是悍跳，今天先出6号。",
        },
        {
            "kind": "player_statement",
            "visibility": "public",
            "authority": "player_claim_unverified",
            "speaker_ref": "seat_6",
            "event_ref": "1014",
            "known_at_seq": 1014,
            "record_seq": 1014,
            "speech": "6号发言。我昨晚验了9号，查杀。9号就是狼。",
        },
    ]


@pytest.mark.parametrize(
    "speech",
    [
        (
            "4号发言。6号今天敢报9号查杀，而9号正好第一个回头猛打6号，"
            "这个顺序和力度太像被查杀后的应激。"
        ),
        (
            "11号发言。6号今天报查杀9号，时机确实微妙，但9号恰好在6号"
            "报验人之前就第一个咬死要出6号，这个顺序更像是被查杀后的应激。"
        ),
    ],
)
def test_public_statement_cannot_be_a_reaction_to_a_later_check_claim(
    speech: str,
) -> None:
    observations = observe_model_speech(
        speech,
        hard_rules={},
        model_context={
            "known_events": {"events": _public_check_chronology_events()},
        },
    )

    assert observations == [
        {
            "code": "public_event_causality_contradiction",
            "severity": "warning",
            "confidence": "high",
            "detector_version": 1,
            "authority": "event_chronology",
            "signals": [
                {
                    "reaction_actor_ref": "seat_9",
                    "trigger_actor_ref": "seat_6",
                    "reaction_event_ref": "984",
                    "trigger_event_ref": "1014",
                    "reaction_known_at_seq": 984,
                    "trigger_known_at_seq": 1014,
                    "reaction_source_record_seq": 984,
                    "trigger_source_record_seq": 1014,
                    "evidence": "claimed_reaction_precedes_claimed_trigger",
                }
            ],
            "effect": "observed_only",
        }
    ]


@pytest.mark.parametrize(
    "speech",
    [
        "10号发言。9号先打6号，不是被查杀后的应激。",
        "如果9号听到6号报查杀后反咬6号，才算被查杀后的应激。",
        "4号说9号猛打6号像被查杀后的应激，但我只是在复述。",
    ],
)
def test_rejected_hypothetical_or_attributed_public_causality_is_not_flagged(
    speech: str,
) -> None:
    assert (
        observe_model_speech(
            speech,
            hard_rules={},
            model_context={
                "known_events": {"events": _public_check_chronology_events()},
            },
        )
        == []
    )


def test_actual_post_check_statement_prevents_public_causality_warning() -> None:
    events = _public_check_chronology_events()
    events.append(
        {
            "kind": "player_statement",
            "visibility": "public",
            "speaker_ref": "seat_9",
            "event_ref": "1020",
            "known_at_seq": 1020,
            "speech": "9号回应6号刚才的查杀，我不认可这个验人。",
        }
    )

    assert (
        observe_model_speech(
            "4号发言。9号猛打6号，这个动作太像被查杀后的应激。",
            hard_rules={},
            model_context={"known_events": {"events": events}},
        )
        == []
    )


def test_repeated_check_after_a_legal_response_does_not_reorder_the_original_trigger() -> None:
    events = [
        {
            "kind": "player_statement",
            "visibility": "public",
            "speaker_ref": "seat_6",
            "event_ref": "970",
            "known_at_seq": 970,
            "speech": "我昨晚验了9号，查杀。",
        },
        {
            "kind": "player_statement",
            "visibility": "public",
            "speaker_ref": "seat_9",
            "event_ref": "984",
            "known_at_seq": 984,
            "speech": "6号是悍跳，我今天先出6号。",
        },
        {
            "kind": "player_statement",
            "visibility": "public",
            "speaker_ref": "seat_6",
            "event_ref": "1014",
            "known_at_seq": 1014,
            "speech": "我再报查杀9号。",
        },
    ]

    assert (
        observe_model_speech(
            "9号猛打6号，像被6号查杀后的应激。",
            hard_rules={},
            model_context={"known_events": {"events": events}},
        )
        == []
    )


def test_public_causality_requires_one_unambiguous_reaction_event() -> None:
    events = _public_check_chronology_events()
    events.insert(
        1,
        {
            "kind": "player_statement",
            "visibility": "public",
            "speaker_ref": "seat_9",
            "event_ref": "990",
            "known_at_seq": 990,
            "speech": "我继续打6号，6号还是悍跳。",
        },
    )

    assert (
        observe_model_speech(
            "9号猛打6号，像被6号查杀后的应激。",
            hard_rules={},
            model_context={"known_events": {"events": events}},
        )
        == []
    )


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
    assert observation["detector_version"] == 2
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
    ["7票归12。", "7.5票归12。", "7号投了1票给12。"],
)
def test_numeric_vote_expression_is_not_parsed_as_a_voter_claim(speech: str) -> None:
    assert _vote_claims(speech, model_context=None) == []


@pytest.mark.parametrize("speech", ["7的票归12。", "7号的票归12。"])
def test_explicit_voter_possessive_vote_claim_is_preserved(speech: str) -> None:

    assert _vote_claims(speech, model_context=None) == [
        {
            "claimed_voter_refs": ["seat_7"],
            "claimed_target_ref": "seat_12",
            "evidence": speech,
        }
    ]


@pytest.mark.parametrize(
    "speech",
    ["7票归12。", "7.5票归12。", "7号投了1票给12。"],
)
def test_numeric_vote_expression_does_not_emit_vote_fact_contradiction(speech: str) -> None:
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
                            "voter_ref": "seat_5",
                            "target_ref": "seat_10",
                        },
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "voter_ref": "seat_7",
                            "target_ref": "seat_10",
                        },
                    ]
                }
            },
        )
        == []
    )


def test_plain_multi_voter_give_claim_is_preserved() -> None:
    speech = "2号、5号给10号。"

    assert _vote_claims(speech, model_context=None) == [
        {
            "claimed_voter_refs": ["seat_2", "seat_5"],
            "claimed_target_ref": "seat_10",
            "evidence": speech,
        }
    ]


def test_real_vote_sentence_preserves_both_claims_without_inventing_target_as_voter() -> None:
    speech = "4号、5号、11号跟我出9，1号也投了9。"

    assert _vote_claims(speech, model_context=None) == [
        {
            "claimed_voter_refs": ["seat_4", "seat_5", "seat_11"],
            "claimed_target_ref": "seat_9",
            "evidence": speech,
        },
        {
            "claimed_voter_refs": ["seat_1"],
            "claimed_target_ref": "seat_9",
            "evidence": speech,
        },
    ]
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
                            "voter_ref": "seat_4",
                            "target_ref": "seat_9",
                        },
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "voter_ref": "seat_5",
                            "target_ref": "seat_9",
                        },
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "voter_ref": "seat_11",
                            "target_ref": "seat_9",
                        },
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "voter_ref": "seat_1",
                            "target_ref": "seat_9",
                        },
                        {
                            "kind": "day_vote",
                            "authority": "judge_fact",
                            "voter_ref": "seat_9",
                            "target_ref": "seat_6",
                        },
                    ]
                }
            },
        )
        == []
    )


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


def test_v9_silence_observation_uses_only_projected_questions_and_event_refs() -> None:
    speech = "5号到现在一个字都没解释。"
    observations = observe_model_speech(
        speech,
        hard_rules={},
        model_context={
            "task": {
                "speech_progress": {
                    "current_speaker_ref": "seat_8",
                    "remaining_speaker_refs": ["seat_5"],
                }
            },
            "history": {
                "questions": [
                    {
                        "question_id": "unprojected_question",
                        "status": "open",
                        "addressed_to": "seat_5",
                        "reply_opportunity": "scheduled_turn_passed",
                        "prior_relevant_statement_refs": ["unprojected_event"],
                    }
                ]
            },
            "known_events": {
                "schema_version": 3,
                "events": [
                    {"event_ref": "437", "kind": "player_statement"},
                    {"event_ref": "471", "kind": "player_statement"},
                ],
                "questions": [
                    {
                        "question_id": "question_471_1",
                        "source_event_ref": "471",
                        "status": "open",
                        "addressed_to": "seat_5",
                        "reply_opportunity": "awaiting_scheduled_turn",
                        "prior_relevant_event_refs": ["437", "not_projected"],
                    }
                ],
                "relations": [],
            },
        },
    )

    assert [item["code"] for item in observations] == [
        "premature_silence_accusation",
        "prior_explanation_denial",
    ]
    assert observations[0]["signals"][0]["question_refs"] == ["question_471_1"]
    assert observations[1]["signals"][0]["prior_relevant_event_refs"] == ["437"]
    assert "prior_relevant_statement_refs" not in observations[1]["signals"][0]


def test_v9_silence_observation_ignores_unprojected_history_questions() -> None:
    observations = observe_model_speech(
        "5号始终没有回应。",
        hard_rules={},
        model_context={
            "task": {"speech_progress": {"remaining_speaker_refs": []}},
            "history": {
                "questions": [
                    {
                        "question_id": "old_question",
                        "status": "open",
                        "addressed_to": "seat_5",
                        "reply_opportunity": "awaiting_scheduled_turn",
                        "prior_relevant_statement_refs": ["old_event"],
                    }
                ]
            },
            "known_events": {
                "schema_version": 3,
                "events": [{"event_ref": "current_question_source"}],
                "questions": [
                    {
                        "question_id": "current_question",
                        "source_event_ref": "current_question_source",
                        "status": "open",
                        "addressed_to": "seat_6",
                    }
                ],
                "relations": [],
            },
        },
    )

    assert observations == []


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
