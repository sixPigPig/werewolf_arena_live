from __future__ import annotations

import re

import pytest

from app.werewolf.self_explosion_audit import (
    build_self_explosion_audit_payload,
    build_self_explosion_window_id,
    normalize_self_explosion_benefit_type,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("immediate_win", "immediate_win"),
        (" ＩＭＭＥＤＩＡＴＥ－ＷＩＮ ", "immediate_win"),
        ("立即获胜", "immediate_win"),
        ("吞警徽", "secure_badge_denial"),
        ("protect last hidden wolf", "protect_last_hidden_wolf"),
        ("保护最后一狼", "protect_last_hidden_wolf"),
        ("阻断公开信息", "deny_confirmed_public_information"),
        ("force-valuable-night", "force_valuable_night"),
        ("强制进入夜晚", "force_valuable_night"),
        ("无收益", "none"),
        (" NO BENEFIT ", "none"),
    ],
)
def test_normalize_self_explosion_benefit_type(
    value: object,
    expected: str,
) -> None:
    assert normalize_self_explosion_benefit_type(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, "", "SENTINEL_PRIVATE_BENEFIT", 1, object()],
)
def test_unknown_benefit_type_returns_none_without_echoing(value: object) -> None:
    result = normalize_self_explosion_benefit_type(value)

    assert result is None
    assert "SENTINEL_PRIVATE_BENEFIT" not in str(result)


def test_window_id_is_deterministic_and_only_hashes_player_identity() -> None:
    arguments = {
        "round_number": 3,
        "stage": "Sheriff Speech",
        "timing": "Before Actor",
        "ordered_actors": ("SENTINEL_PLAYER_A", "SENTINEL_PLAYER_B"),
        "completed_actors": ("SENTINEL_PLAYER_A",),
        "current_actor": "SENTINEL_PLAYER_B",
    }

    first = build_self_explosion_window_id(**arguments)
    second = build_self_explosion_window_id(**arguments)

    assert first == second
    assert re.fullmatch(
        r"r3:self-explosion:sheriff-speech:before-actor:[0-9a-f]{12}",
        first,
    )
    assert "SENTINEL_PLAYER" not in first
    assert first != build_self_explosion_window_id(
        **{**arguments, "current_actor": "SENTINEL_PLAYER_A"}
    )
    assert first != build_self_explosion_window_id(
        **{
            **arguments,
            "ordered_actors": ("SENTINEL_PLAYER_B", "SENTINEL_PLAYER_A"),
        }
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("round_number", 0),
        ("round_number", True),
        ("stage", ""),
        ("timing", ""),
        ("ordered_actors", "not-a-player-sequence"),
        ("completed_actors", ("",)),
        ("current_actor", 7),
    ],
)
def test_window_id_rejects_invalid_context(field: str, value: object) -> None:
    arguments: dict[str, object] = {
        "round_number": 3,
        "stage": "debate",
        "timing": "before_actor",
        "ordered_actors": ("1号玩家", "2号玩家"),
        "completed_actors": ("1号玩家",),
        "current_actor": "2号玩家",
    }
    arguments[field] = value

    with pytest.raises((TypeError, ValueError)):
        build_self_explosion_window_id(**arguments)  # type: ignore[arg-type]


def test_build_current_self_explosion_audit_payload() -> None:
    window_id = build_self_explosion_window_id(
        round_number=3,
        stage="debate",
        timing="before_actor",
        ordered_actors=("1号玩家", "2号玩家"),
        completed_actors=("1号玩家",),
        current_actor="2号玩家",
    )

    payload = build_self_explosion_audit_payload(
        result={
            "self_explode": "不自爆",
            "benefit_type": "保护最后一狼",
            "expected_gain": "保留最后一名狼人",
            "primary_risk": "错失当前窗口",
        },
        window_id=window_id,
        execution_status="COMPLETED",
        duration_ms=845,
    )

    assert payload == {
        "decision_schema": "v2",
        "window_id": window_id,
        "execution_status": "completed",
        "duration_ms": 845,
        "benefit_type": "protect_last_hidden_wolf",
    }


@pytest.mark.parametrize(
    ("overrides", "missing_field"),
    [
        ({"result": {"benefit_type": "unknown-private-value"}}, "benefit_type"),
        ({"window_id": "SENTINEL_PRIVATE_WINDOW"}, "window_id"),
        ({"execution_status": "SENTINEL_PRIVATE_STATUS"}, "execution_status"),
        ({"duration_ms": -1}, "duration_ms"),
    ],
)
def test_incomplete_audit_payload_is_legacy_and_does_not_echo_raw_values(
    overrides: dict[str, object],
    missing_field: str,
) -> None:
    window_id = build_self_explosion_window_id(
        round_number=1,
        stage="debate",
        timing="before_actor",
        ordered_actors=("1号玩家",),
        completed_actors=(),
        current_actor="1号玩家",
    )
    arguments: dict[str, object] = {
        "result": {
            "benefit_type": "none",
            "expected_gain": "保留白天空间",
            "primary_risk": "失去夜间机会",
        },
        "window_id": window_id,
        "execution_status": "fallback",
        "duration_ms": 50,
    }
    arguments.update(overrides)

    payload = build_self_explosion_audit_payload(**arguments)  # type: ignore[arg-type]

    assert payload["decision_schema"] == "legacy"
    assert payload[missing_field] is None
    assert "SENTINEL_PRIVATE" not in str(payload)


def test_missing_current_response_fields_downgrades_to_legacy() -> None:
    window_id = build_self_explosion_window_id(
        round_number=1,
        stage="debate",
        timing="before_actor",
        ordered_actors=("1号玩家",),
        completed_actors=(),
        current_actor="1号玩家",
    )

    payload = build_self_explosion_audit_payload(
        result={"benefit_type": "none", "expected_gain": "保留白天空间"},
        window_id=window_id,
        execution_status="completed",
        duration_ms=50,
    )

    assert payload["decision_schema"] == "legacy"
    assert payload["benefit_type"] == "none"
