import pytest

from app.werewolf.action_choice import normalize_action_choice


@pytest.mark.parametrize(
    ("raw_value", "kind"),
    [
        ("5号玩家", "exact"),
        (5, "seat_alias"),
        ("5", "seat_alias"),
        ("05", "seat_alias"),
        ("5号", "seat_alias"),
        ("玩家5号", "seat_alias"),
        ("５号玩家", "string_exact"),
    ],
)
def test_normalize_action_choice_accepts_unique_seat_aliases(
    raw_value: object,
    kind: str,
) -> None:
    result = normalize_action_choice(raw_value, ["3号玩家", "5号玩家", "12号玩家"])

    assert result.canonical_value == "5号玩家"
    assert result.kind == kind


def test_normalize_action_choice_accepts_numeric_string_candidate() -> None:
    result = normalize_action_choice(2, ["1", "2"])

    assert result.canonical_value == "2"
    assert result.kind == "string_exact"


@pytest.mark.parametrize(
    ("raw_value", "canonical"),
    [
        ("不用毒药", "不使用毒药"),
        ("不毒", "不使用毒药"),
        ("不开枪", "不发动技能"),
        ("不爆", "不自爆"),
    ],
)
def test_normalize_action_choice_accepts_registered_special_aliases(
    raw_value: str,
    canonical: str,
) -> None:
    result = normalize_action_choice(
        raw_value,
        ["5号玩家", canonical],
    )

    assert result.canonical_value == canonical
    assert result.kind == "special_alias"


@pytest.mark.parametrize("raw_value", ["5abc", "五号", "小明", 7, None, {"seat": 5}])
def test_normalize_action_choice_rejects_unregistered_or_illegal_values(
    raw_value: object,
) -> None:
    result = normalize_action_choice(raw_value, ["3号玩家", "5号玩家"])

    assert result.canonical_value is None
    assert result.kind == "invalid"


def test_normalize_action_choice_rejects_ambiguous_explicit_alias() -> None:
    result = normalize_action_choice(
        "弃权",
        ["不使用毒药", "不发动技能"],
        aliases={
            "不使用毒药": ["弃权"],
            "不发动技能": ["弃权"],
        },
    )

    assert result.canonical_value is None
    assert result.kind == "ambiguous"


def test_normalize_action_choice_is_independent_of_candidate_order() -> None:
    first = normalize_action_choice("05", ["3号玩家", "5号玩家", "12号玩家"])
    second = normalize_action_choice("05", ["12号玩家", "5号玩家", "3号玩家"])

    assert first == second
