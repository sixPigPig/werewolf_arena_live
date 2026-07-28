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
