import pytest

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


@pytest.mark.parametrize(
    ("role", "text"),
    [
        ("女巫", "3号，女巫，明牌打。警徽流先验警下1号，再验警下7号。"),
        ("狼人", "2号上警，身份村民。我的警徽流先验5号，再验10号。"),
        ("村民", "我的警徽流暂定验警下4号或7号。"),
    ],
)
def test_sheriff_speech_warns_on_investigation_plan_without_seer_claim(
    role: str,
    text: str,
) -> None:
    warnings = action_quality_warnings(
        action="sheriff_speech",
        text=text,
        role=role,
    )

    assert "sheriff_speech_investigation_plan_without_seer_claim" in warnings


@pytest.mark.parametrize(
    ("role", "text"),
    [
        ("预言家", "9号预言家，昨晚查验3号是好人。警徽流今晚验12号。"),
        ("狼人", "我是预言家，昨晚查验3号是好人。我的警徽流先验5号，再验10号。"),
        ("村民", "2号自己的警徽流先验5号、再验10号，缺乏依据。"),
    ],
)
def test_sheriff_speech_allows_seer_claims_and_other_player_plan_references(
    role: str,
    text: str,
) -> None:
    warnings = action_quality_warnings(
        action="sheriff_speech",
        text=text,
        role=role,
    )

    assert "sheriff_speech_investigation_plan_without_seer_claim" not in warnings


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


@pytest.mark.parametrize("action", ["debate", "exile_pk_speech", "exile_last_words"])
def test_sheriff_vote_eligibility_does_not_rewrite_exile_context(action: str) -> None:
    warnings = action_quality_warnings(
        action=action,
        text="今天放逐票我会投给8号，警长的1.5票也应投8号。",
        eligibility={
            "original_voters": [],
            "actor_can_sheriff_vote": False,
        },
    )

    assert "appeals_to_missing_sheriff_voters" not in warnings
    assert "promises_ineligible_sheriff_vote" not in warnings


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


@pytest.mark.parametrize(
    "text",
    [
        "3号是查杀，5号是好人，今天先出3号。",
        "预言家查杀3号，同时给5号发金水。",
        "3号像狼人，但5号是好人。",
        "3号是金水，5号更像狼人。",
    ],
)
def test_role_term_contradiction_binds_the_same_target(text: str) -> None:
    warnings = action_quality_warnings(action="debate", text=text)

    assert "role_term_contradiction" not in warnings


@pytest.mark.parametrize(
    "text",
    [
        "3号既是查杀又是好人，这个结论不变。",
        "预言家查杀5号，但5号也是金水。",
        "6号是金水，同时我认为6号是狼人。",
    ],
)
def test_role_term_contradiction_flags_conflicting_claims_for_same_target(
    text: str,
) -> None:
    warnings = action_quality_warnings(action="debate", text=text)

    assert "role_term_contradiction" in warnings


def test_role_term_contradiction_does_not_reject_a_reported_opinion() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="3号说5号是查杀，但我认为5号是好人。",
    )

    assert "role_term_contradiction" not in warnings


def test_hunter_future_voluntary_shot_is_a_hard_rule_error() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="今天先出6号，如果错了我下一晚再开枪带走8号。",
        role="猎人",
        hard_state={
            "actor_alive": True,
            "hunter_death_trigger_active": False,
        },
    )

    assert "hunter_claims_voluntary_future_shot" in warnings


def test_hunter_can_describe_legal_death_trigger() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="我是猎人，如果我死亡且法官触发技能，我会在当场开枪。",
        role="猎人",
        hard_state={
            "actor_alive": True,
            "hunter_death_trigger_active": False,
        },
    )

    assert "hunter_claims_voluntary_future_shot" not in warnings


def test_terminal_hard_state_rejects_future_round_claim() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="今天出错也没关系，下一夜我再查验8号。",
        role="预言家",
        hard_state={"terminal_after_current_action": True},
    )

    assert "claims_future_round_after_terminal" in warnings


def test_dead_player_cannot_promise_later_action_in_last_words() -> None:
    warnings = action_quality_warnings(
        action="exile_last_words",
        text="下一轮我会继续投8号，并在白天解释。",
        hard_state={"actor_alive": False},
    )

    assert "claims_illegal_post_death_action" in warnings


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
