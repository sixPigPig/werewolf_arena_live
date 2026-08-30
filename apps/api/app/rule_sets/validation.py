from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from typing import Literal, cast

from app.rule_sets.types import (
    RuleRoleId,
    RuleSetConfig,
    RuleSetValidationResult,
    RuleValidationIssue,
    WEREWOLF_ATTACK_RESOLUTIONS,
    WerewolfAttackResolution,
)
from app.shared.rules import (
    SPEECH_POLICY_SEQUENTIAL,
    SPEECH_POLICY_SHERIFF_DIRECTED,
    WIN_CONDITION_SLAUGHTER_SIDE,
    WIN_CONDITION_WOLVES_GTE_OTHERS,
)


RULE_ROLE_IDS: tuple[RuleRoleId, ...] = (
    "werewolf",
    "villager",
    "seer",
    "guard",
    "witch",
    "hunter",
    "idiot",
)
SPECIAL_ROLE_IDS: tuple[RuleRoleId, ...] = ("seer", "guard", "witch", "hunter", "idiot")
SHERIFF_VOTE_WEIGHTS = (1.0, 1.5, 2.0)

CONFIG_FIELDS = frozenset(
    {
        "name",
        "description",
        "complexity",
        "estimated_duration",
        "rule_tags",
        "role_counts",
        "win_condition",
        "sheriff_enabled",
        "sheriff_vote_weight",
        "speech_policy",
        "werewolf_self_explosion_enabled",
        "first_night_last_words_enabled",
        "sheriff_badge_bomb_policy",
        "werewolf_attack_policy",
    }
)
WEREWOLF_ATTACK_POLICY_FIELDS = frozenset(
    {"resolution", "allow_no_attack", "allow_wolf_target"}
)


def normalize_rule_set_config(value: Mapping[str, object]) -> RuleSetConfig:
    if not isinstance(value, Mapping):
        raise ValueError("rule configuration must be a mapping")

    unknown = set(value) - CONFIG_FIELDS
    if unknown:
        raise ValueError(f"Unsupported rule fields: {', '.join(sorted(unknown))}")

    raw_counts = value.get("role_counts")
    if not isinstance(raw_counts, Mapping) or set(raw_counts) != set(RULE_ROLE_IDS):
        raise ValueError("role_counts must contain exactly the supported role ids")
    counts: dict[RuleRoleId, int] = {}
    for role_id in RULE_ROLE_IDS:
        count = raw_counts[role_id]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"role_counts.{role_id} must be a non-negative integer")
        counts[role_id] = count

    weight = value.get("sheriff_vote_weight")
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise ValueError("sheriff_vote_weight must be numeric")
    try:
        normalized_weight = float(weight)
    except OverflowError as error:
        raise ValueError("sheriff_vote_weight must be finite") from error
    if not math.isfinite(normalized_weight):
        raise ValueError("sheriff_vote_weight must be finite")

    (
        werewolf_attack_resolution,
        werewolf_allow_no_attack,
        werewolf_allow_wolf_target,
    ) = _werewolf_attack_policy(value.get("werewolf_attack_policy"))

    return RuleSetConfig(
        name=_text(value.get("name"), 1, 120, "name"),
        description=_text(value.get("description", ""), 0, 1000, "description"),
        complexity=_text(value.get("complexity"), 1, 40, "complexity"),
        estimated_duration=_text(value.get("estimated_duration"), 1, 40, "estimated_duration"),
        rule_tags=_tags(value.get("rule_tags", [])),
        role_counts=counts,
        win_condition=cast(
            Literal["wolves_gte_others", "slaughter_side"],
            _literal(
                value.get("win_condition"),
                {WIN_CONDITION_WOLVES_GTE_OTHERS, WIN_CONDITION_SLAUGHTER_SIDE},
                "win_condition",
            ),
        ),
        sheriff_enabled=_bool(value.get("sheriff_enabled"), "sheriff_enabled"),
        sheriff_vote_weight=normalized_weight,
        speech_policy=cast(
            Literal["sequential", "sheriff_directed"],
            _literal(
                value.get("speech_policy"),
                {SPEECH_POLICY_SEQUENTIAL, SPEECH_POLICY_SHERIFF_DIRECTED},
                "speech_policy",
            ),
        ),
        werewolf_self_explosion_enabled=_bool(
            value.get("werewolf_self_explosion_enabled"),
            "werewolf_self_explosion_enabled",
        ),
        first_night_last_words_enabled=_bool(
            value.get("first_night_last_words_enabled"),
            "first_night_last_words_enabled",
        ),
        sheriff_badge_bomb_policy=cast(
            Literal["none", "double"],
            _literal(
                value.get("sheriff_badge_bomb_policy"),
                {"none", "double"},
                "sheriff_badge_bomb_policy",
            ),
        ),
        werewolf_attack_resolution=werewolf_attack_resolution,
        werewolf_allow_no_attack=werewolf_allow_no_attack,
        werewolf_allow_wolf_target=werewolf_allow_wolf_target,
    )


def validate_rule_set_config(config: RuleSetConfig) -> RuleSetValidationResult:
    errors: list[RuleValidationIssue] = []
    wolf_count = config.role_counts["werewolf"]
    good_count = config.player_count - wolf_count

    if not 6 <= config.player_count <= 12:
        errors.append(
            _issue(
                "player_count_out_of_range",
                "role_counts",
                "Player count must be between 6 and 12.",
            )
        )

    if wolf_count == 0:
        errors.append(
            _issue(
                "werewolf_required",
                "role_counts.werewolf",
                "At least one werewolf is required.",
            )
        )
    if good_count == 0:
        errors.append(
            _issue(
                "good_player_required",
                "role_counts",
                "At least one good player is required.",
            )
        )

    if wolf_count >= good_count:
        errors.append(
            _issue(
                "wolves_must_be_fewer_than_good_players",
                "role_counts.werewolf",
                "Werewolves must be fewer than good players.",
            )
        )

    for role_id in SPECIAL_ROLE_IDS:
        if config.role_counts[role_id] > 1:
            errors.append(
                _issue(
                    "special_role_count_exceeded",
                    f"role_counts.{role_id}",
                    "Each special role may appear at most once.",
                )
            )

    if config.win_condition == WIN_CONDITION_SLAUGHTER_SIDE:
        if not any(config.role_counts[role_id] for role_id in SPECIAL_ROLE_IDS):
            errors.append(
                _issue(
                    "slaughter_side_requires_god",
                    "role_counts",
                    "Slaughter-side rules require at least one god role.",
                )
            )
        if config.role_counts["villager"] == 0:
            errors.append(
                _issue(
                    "slaughter_side_requires_villager",
                    "role_counts.villager",
                    "Slaughter-side rules require at least one villager.",
                )
            )

    if config.sheriff_vote_weight not in SHERIFF_VOTE_WEIGHTS:
        errors.append(
            _issue(
                "unsupported_sheriff_vote_weight",
                "sheriff_vote_weight",
                "Sheriff vote weight must be 1, 1.5, or 2.",
            )
        )

    if not config.sheriff_enabled:
        if config.sheriff_vote_weight != 1.0:
            errors.append(
                _issue(
                    "sheriff_disabled_vote_weight",
                    "sheriff_vote_weight",
                    "Sheriff vote weight must be 1 when sheriff rules are disabled.",
                )
            )
        if config.speech_policy != SPEECH_POLICY_SEQUENTIAL:
            errors.append(
                _issue(
                    "sheriff_disabled_speech_policy",
                    "speech_policy",
                    "Speech must be sequential when sheriff rules are disabled.",
                )
            )

    if config.speech_policy == SPEECH_POLICY_SHERIFF_DIRECTED and not config.sheriff_enabled:
        errors.append(
            _issue(
                "sheriff_directed_requires_sheriff",
                "speech_policy",
                "Sheriff-directed speech requires sheriff rules.",
            )
        )

    badge_requires_self_explosion = (
        not config.werewolf_self_explosion_enabled and config.sheriff_badge_bomb_policy != "none"
    )
    if badge_requires_self_explosion:
        errors.append(
            _issue(
                "badge_policy_requires_self_explosion",
                "sheriff_badge_bomb_policy",
                "Badge bomb rules require werewolf self-explosion.",
            )
        )

    if (
        config.sheriff_badge_bomb_policy == "double"
        and not badge_requires_self_explosion
        and not config.sheriff_enabled
    ):
        errors.append(
            _issue(
                "badge_policy_requires_sheriff",
                "sheriff_badge_bomb_policy",
                "Double badge bomb rules require sheriff rules.",
            )
        )

    return RuleSetValidationResult(errors=tuple(errors))


def _text(value: object, minimum: int, maximum: int, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"{field} must not contain control characters")
    normalized = normalized.strip()
    if not minimum <= len(normalized) <= maximum:
        raise ValueError(f"{field} must contain between {minimum} and {maximum} characters")
    return normalized


def _tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("rule_tags must be a list or tuple")
    if len(value) > 8:
        raise ValueError("rule_tags must contain at most 8 items")

    tags: list[str] = []
    seen: set[str] = set()
    for index, raw_tag in enumerate(value):
        tag = _text(raw_tag, 1, 20, f"rule_tags[{index}]")
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tuple(tags)


def _literal(value: object, supported: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in supported:
        raise ValueError(f"{field} has an unsupported value")
    return value


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _werewolf_attack_policy(
    value: object,
) -> tuple[WerewolfAttackResolution | None, bool, bool]:
    if value is None:
        return None, False, False
    if not isinstance(value, Mapping):
        raise ValueError("werewolf_attack_policy must be a mapping")
    fields = set(value)
    if fields != WEREWOLF_ATTACK_POLICY_FIELDS:
        raise ValueError(
            "werewolf_attack_policy must contain exactly resolution, "
            "allow_no_attack, and allow_wolf_target"
        )
    resolution = cast(
        WerewolfAttackResolution,
        _literal(
            value.get("resolution"),
            set(WEREWOLF_ATTACK_RESOLUTIONS),
            "werewolf_attack_policy.resolution",
        ),
    )
    return (
        resolution,
        _bool(
            value.get("allow_no_attack"),
            "werewolf_attack_policy.allow_no_attack",
        ),
        _bool(
            value.get("allow_wolf_target"),
            "werewolf_attack_policy.allow_wolf_target",
        ),
    )


def _issue(code: str, path: str, message: str) -> RuleValidationIssue:
    return RuleValidationIssue(code=code, path=path, message=message)
