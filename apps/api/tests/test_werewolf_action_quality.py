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
