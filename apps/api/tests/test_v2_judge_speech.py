from __future__ import annotations

import pytest

from app.v2.judge_speech import V2JudgeTemplateError, render_judge_speech


def _render(action_type: str, **context):
    return render_judge_speech(action_type=action_type, context=context)


def test_dawn_template_uses_peaceful_wording_only_without_deaths() -> None:
    peaceful = _render("judge_dawn_announcement", public_death_seats=[])
    deaths = _render(
        "judge_dawn_announcement",
        public_death_seats=[2, 5],
    )

    assert peaceful.text == "天亮了，昨夜是平安夜。"
    assert deaths.text == "天亮了，昨夜出局的玩家是：2号、5号。"
    assert "平安夜" not in deaths.text


def test_public_discussion_opening_never_restates_dawn_result() -> None:
    rendered = _render(
        "judge_public_discussion_opening",
        round_no=1,
        public_death_seats=[2],
    )

    assert rendered.text == "第1天白天讨论现在开始，请存活玩家按照发言顺序依次发言。"
    assert "平安夜" not in rendered.text
    assert "2号" not in rendered.text


@pytest.mark.parametrize(
    ("action_type", "context", "expected"),
    [
        (
            "seer_investigate_result",
            {"target_player_seat": 4, "alignment": "werewolves"},
            "你查验的4号属于狼人阵营。",
        ),
        (
            "judge_exile_result",
            {"player_seat": 3, "outcome": "eliminated"},
            "3号被投票放逐出局。",
        ),
        (
            "judge_sheriff_badge_result",
            {"target_player_seat": 4},
            "警徽移交给4号。",
        ),
        (
            "judge_hunter_shot_announcement",
            {"target_player_seat": 6},
            "猎人开枪带走了6号。",
        ),
        (
            "judge_werewolf_self_explosion",
            {"player_seat": 2},
            "2号发动狼人自爆并立即出局，今天剩余流程结束。",
        ),
        (
            "judge_sheriff_elected",
            {"player_seat": 5},
            "5号当选警长并获得警徽。",
        ),
        (
            "witch_attack_observation",
            {"attacked_player_seat": 3},
            "今晚被狼人袭击的是3号。",
        ),
        (
            "judge_game_completed",
            {"winner": "villagers"},
            "本局结束，好人阵营获胜。",
        ),
        (
            "judge_day_summary",
            {"round_no": 2},
            "第2天流程结束，即将入夜。",
        ),
    ],
)
def test_fact_templates_render_only_supplied_engine_result(
    action_type: str,
    context: dict[str, object],
    expected: str,
) -> None:
    assert render_judge_speech(action_type=action_type, context=context).text == expected


def test_unknown_judge_action_fails_closed() -> None:
    with pytest.raises(V2JudgeTemplateError, match="missing judge template"):
        _render("judge_unregistered")
