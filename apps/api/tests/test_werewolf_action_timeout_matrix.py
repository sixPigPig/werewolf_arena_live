from __future__ import annotations

import pytest

from app.werewolf.engine import (
    GameEngine,
    PlayerActionRequest,
    PlayerActionResult,
    SHERIFF_BADGE_DESTROY,
    SHERIFF_SKIP,
    SPEECH_FROM_LEFT,
    SPEECH_FROM_RIGHT,
    initialize_game_state,
)
from app.werewolf.lm import FakeProvider, LmLog
from app.werewolf.models import RoundState
from app.werewolf.rules import (
    ACTION_INVESTIGATE,
    ACTION_PROTECT,
    ACTION_SHERIFF_BADGE,
    ACTION_SHERIFF_RUN,
    ACTION_SPEECH_ORDER,
    ACTION_VOTE,
    get_rule_set,
)


def _engine_request(
    *,
    action: str,
    options: list[str],
    result_key: str,
) -> tuple[GameEngine, PlayerActionRequest]:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id=f"session_{action}",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=91,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=FakeProvider([]),
        max_rounds=8,
        rule_set=rule_set,
        fallback_seed=91,
    )
    round_state = RoundState(number=1, players=[player.name for player in state.players])
    request = engine._build_player_action_request(
        player=state.players[0],
        action=action,
        options=options,
        result_key=result_key,
        round_state=round_state,
        phase="day" if action not in {ACTION_INVESTIGATE, ACTION_PROTECT} else "night",
    )
    return engine, request


@pytest.mark.parametrize(
    ("action", "result_key", "options", "expected", "expected_reason"),
    [
        (
            ACTION_VOTE,
            "vote",
            ["2号玩家", "3号玩家"],
            None,
            "invalid_exhausted",
        ),
        (
            ACTION_SPEECH_ORDER,
            "speech_order",
            [SPEECH_FROM_LEFT, SPEECH_FROM_RIGHT],
            None,
            "rule_default",
        ),
        (
            ACTION_SHERIFF_BADGE,
            "badge",
            ["2号玩家", SHERIFF_BADGE_DESTROY],
            SHERIFF_BADGE_DESTROY,
            "rule_default",
        ),
        (
            ACTION_SHERIFF_RUN,
            "run",
            ["上警", SHERIFF_SKIP],
            SHERIFF_SKIP,
            "invalid_exhausted",
        ),
        (
            ACTION_INVESTIGATE,
            "investigate",
            ["2号玩家"],
            None,
            "invalid_exhausted",
        ),
        (
            ACTION_PROTECT,
            "protect",
            ["2号玩家"],
            None,
            "invalid_exhausted",
        ),
    ],
)
def test_invalid_action_exhaustion_uses_declared_safe_result(
    action: str,
    result_key: str,
    options: list[str],
    expected: str | None,
    expected_reason: str,
) -> None:
    engine, request = _engine_request(
        action=action,
        options=options,
        result_key=result_key,
    )
    result = PlayerActionResult(
        request=request,
        value="非法选项",
        lm_log=LmLog(
            prompt="",
            raw_response='{"reasoning":"x"}',
            result={result_key: "非法选项"},
            invalid_attempts=[{"value": "非法选项"}],
        ),
    )

    value, action_log = engine._finalize_player_action_result(result)

    if action in {ACTION_VOTE, ACTION_SPEECH_ORDER}:
        assert value in options
    else:
        assert value == expected
    assert action_log.execution_status == "fallback"
    assert action_log.effective_origin == "system_fallback"
    assert action_log.reason_code == expected_reason
    assert action_log.invalid_value == "非法选项"


@pytest.mark.parametrize(
    ("action", "result_key", "options", "expected"),
    [
        (
            ACTION_SHERIFF_BADGE,
            "badge",
            ["2号玩家", SHERIFF_BADGE_DESTROY],
            SHERIFF_BADGE_DESTROY,
        ),
        (
            ACTION_SPEECH_ORDER,
            "speech_order",
            [SPEECH_FROM_LEFT, SPEECH_FROM_RIGHT],
            None,
        ),
    ],
)
def test_timeout_rule_defaults_have_low_cardinality_reason(
    action: str,
    result_key: str,
    options: list[str],
    expected: str | None,
) -> None:
    engine, request = _engine_request(
        action=action,
        options=options,
        result_key=result_key,
    )
    result = engine._timeout_fallback_result(
        request,
        started_at=engine.monotonic(),
        budget_ms=1,
    )

    value, action_log = engine._finalize_player_action_result(result)

    if expected is None:
        assert value in options
    else:
        assert value == expected
    assert action_log.execution_status == "fallback"
    assert action_log.effective_origin == "system_fallback"
    assert action_log.reason_code == "rule_default"
    assert action_log.fallback_reason is not None
