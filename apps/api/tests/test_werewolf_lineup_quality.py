import pytest

from app.shared.lineup_quality import (
    LineupQualityPolicyV1,
    evaluate_lineup_quality,
    plan_diverse_lineup,
)
from app.shared.player_configs import PlayerConfig


def _config(
    seat: int,
    *,
    profile_id: str | None = None,
    personality: str = "balanced",
    strategy: str = "balanced",
    appearance: str = "default",
    avatar_asset_id: str | None = None,
) -> PlayerConfig:
    return PlayerConfig(
        seat=seat,
        profile_id=profile_id or f"profile-{seat}",
        name=f"玩家{seat}",
        model="model",
        personality_id=personality,
        personality="",
        appearance_id=appearance,
        tags=(),
        avatar_asset_id=avatar_asset_id,
        strategy_profile=strategy,
    )


def test_lineup_quality_report_detects_all_blocking_dimensions() -> None:
    configs = [
        _config(
            seat,
            personality="analytical",
            strategy="logic_leader",
            avatar_asset_id="shared-avatar",
        )
        for seat in range(1, 13)
    ]

    report = evaluate_lineup_quality(configs, player_count=12)

    assert report.is_blocked is True
    assert report.style_bucket_count == 1
    assert {violation.code for violation in report.violations} >= {
        "personality_overrepresented",
        "strategy_profile_overrepresented",
        "avatar_overrepresented",
        "insufficient_style_buckets",
    }
    payload = report.to_dict()
    assert payload["schema_version"] == 1
    assert payload["required_style_bucket_count"] == 4


def test_lineup_quality_report_accepts_diverse_six_player_lineup() -> None:
    personalities = ["balanced", "aggressive", "cautious"] * 2
    strategies = ["balanced", "pressure_attacker", "cautious_observer"] * 2
    configs = [
        _config(
            seat,
            personality=personalities[seat - 1],
            strategy=strategies[seat - 1],
            avatar_asset_id=f"avatar-{seat}",
        )
        for seat in range(1, 7)
    ]

    report = evaluate_lineup_quality(configs, player_count=6)

    assert report.is_blocked is False
    assert report.style_bucket_count == 3
    assert report.required_style_bucket_count == 3


@pytest.mark.parametrize(
    ("player_count", "expected_style_buckets"),
    [(6, 3), (8, 4), (12, 4)],
)
def test_lineup_quality_policy_scales_style_thresholds(
    player_count: int,
    expected_style_buckets: int,
) -> None:
    assert (
        LineupQualityPolicyV1().required_style_buckets(player_count)
        == expected_style_buckets
    )


def test_lineup_quality_uses_appearance_fallback() -> None:
    configs = [
        _config(
            seat,
            personality=("balanced", "aggressive", "cautious")[seat % 3],
            strategy=("balanced", "pressure_attacker", "cautious_observer")[seat % 3],
            appearance="system-gothic-male-1",
        )
        for seat in range(1, 7)
    ]

    report = evaluate_lineup_quality(configs, player_count=6)
    violations = {violation.code: violation for violation in report.violations}

    assert violations["avatar_overrepresented"].key == (
        "appearance:system-gothic-male-1"
    )


def test_lineup_quality_ignores_default_avatars() -> None:
    configs = [
        _config(
            seat,
            personality=("balanced", "aggressive", "cautious")[seat % 3],
            strategy=("balanced", "pressure_attacker", "cautious_observer")[seat % 3],
            appearance="default",
        )
        for seat in range(1, 7)
    ]

    report = evaluate_lineup_quality(configs, player_count=6)
    codes = {violation.code for violation in report.violations}

    assert "avatar_overrepresented" not in codes


def test_unknown_profile_ids_do_not_invent_new_style_buckets() -> None:
    configs = [
        _config(
            seat,
            personality=f"custom-personality-{seat}",
            strategy=f"custom-strategy-{seat}",
            avatar_asset_id=f"avatar-{seat}",
        )
        for seat in range(1, 7)
    ]

    report = evaluate_lineup_quality(configs, player_count=6)

    assert report.style_bucket_count == 1
    assert "insufficient_style_buckets" in {
        violation.code for violation in report.violations
    }


def test_default_avatar_is_not_treated_as_a_shared_rendered_asset() -> None:
    configs = [
        _config(
            seat,
            personality=("balanced", "aggressive", "cautious")[seat % 3],
            strategy=("balanced", "pressure_attacker", "cautious_observer")[seat % 3],
        )
        for seat in range(1, 7)
    ]

    report = evaluate_lineup_quality(configs, player_count=6)

    assert "avatar_overrepresented" not in {
        violation.code for violation in report.violations
    }


def test_lineup_planner_is_deterministic_and_preserves_locked_seats() -> None:
    candidates = [
        _config(
            0,
            profile_id=f"profile-{index}",
            personality=personality,
            strategy=strategy,
            avatar_asset_id=f"avatar-{index}",
        )
        for index, (personality, strategy) in enumerate(
            [
                ("balanced", "balanced"),
                ("aggressive", "pressure_attacker"),
                ("cautious", "cautious_observer"),
                ("deceptive", "shadow_wolf"),
                ("analytical", "logic_leader"),
                ("balanced", "social_reader"),
                ("aggressive", "pressure_attacker"),
                ("cautious", "cautious_observer"),
            ],
            start=1,
        )
    ]
    locked = _config(
        2,
        profile_id="profile-2",
        personality="aggressive",
        strategy="pressure_attacker",
        avatar_asset_id="avatar-2",
    )

    first = plan_diverse_lineup(
        [locked],
        candidates,
        player_count=6,
        seed=42,
        repair_scope="unlocked_all",
        locked_seats=[2],
    )
    second = plan_diverse_lineup(
        [locked],
        list(reversed(candidates)),
        player_count=6,
        seed=42,
        repair_scope="unlocked_all",
        locked_seats=[2],
    )

    assert [config.to_dict() for config in first] == [
        config.to_dict() for config in second
    ]
    assert next(config for config in first if config.seat == 2).profile_id == "profile-2"
    assert len({config.profile_id for config in first}) == 6
    assert evaluate_lineup_quality(first, player_count=6).is_blocked is False


def test_lineup_planner_returns_incomplete_result_when_library_is_too_small() -> None:
    result = plan_diverse_lineup(
        [],
        [_config(0, profile_id="only-profile")],
        player_count=6,
        seed=1,
    )

    assert result == []
    report = evaluate_lineup_quality(
        result,
        player_count=6,
        policy=LineupQualityPolicyV1(mode="enforce"),
    )
    assert report.is_blocked is True
    assert report.violations[0].code == "lineup_incomplete"
