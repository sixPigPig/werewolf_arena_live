from app.werewolf.action_quality import action_quality_warnings


def test_sheriff_speech_warns_when_player_announces_withdrawal() -> None:
    warnings = action_quality_warnings(
        action="sheriff_speech",
        text="我是3号，上警竞选警长。我退水，警徽投给8号。",
    )

    assert "sheriff_speech_mentions_withdraw" in warnings


def test_sheriff_speech_warns_on_conflicting_badge_goal() -> None:
    warnings = action_quality_warnings(
        action="sheriff_speech",
        text="我认8号真预言家。希望大家把警徽投给我。",
    )

    assert "sheriff_speech_conflicting_badge_goal" in warnings


def test_endgame_warning_for_tomorrow_without_pressure() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="今天先出6号，如果他是好人，明天再看情况。",
        endgame=True,
    )

    assert "endgame_tomorrow_without_pressure" in warnings
    assert "assumes_future_round_in_endgame" in warnings
    assert "ignores_terminal_risk" in warnings


def test_sheriff_eligibility_warnings_use_structured_context() -> None:
    eligibility = {
        "original_voters": [],
        "actor_can_sheriff_vote": False,
    }

    warnings = action_quality_warnings(
        action="sheriff_speech",
        text="警下玩家请把票投给我，我会投给8号。",
        eligibility=eligibility,
    )

    assert "appeals_to_missing_sheriff_voters" in warnings
    assert "promises_ineligible_sheriff_vote" in warnings


def test_endgame_future_reference_with_terminal_risk_is_allowed() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="如果还有明天再看8号，但本轮错误放逐可能直接结束游戏。",
        endgame=True,
    )

    assert "assumes_future_round_in_endgame" not in warnings
    assert "ignores_terminal_risk" not in warnings


def test_action_quality_flags_role_term_contradiction_and_self_reference() -> None:
    assert "role_term_contradiction" in action_quality_warnings(
        action="debate",
        text="3号预言家查杀5号好人，所以5号可信。",
    )
    assert "self_reference_as_group" in action_quality_warnings(
        action="debate",
        text="我10号是村民，后置位10、11、12都需要解释身份。",
        actor="10号玩家",
    )


def test_action_quality_flags_debate_repetition_with_context() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="我先盘票型。第一轮全票挂警徽定狼，这里不急着站死。",
        prior_texts=[
            "我先盘票型。第一轮全票挂警徽定狼，说明大家都觉得他发言差。",
            "第一轮全票挂警徽定狼，先听后置位。",
        ],
        personality="常用表达: 我先盘票型；这里不急着站死",
    )

    assert "catchphrase_overuse" in warnings
    assert "repeated_debate_phrase" in warnings
    assert "low_novelty_debate" in warnings
