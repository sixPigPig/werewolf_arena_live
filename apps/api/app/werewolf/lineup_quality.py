from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.werewolf.player_configs import PlayerConfig


LineupQualityMode = Literal["observe", "repair", "enforce"]
LineupRepairScope = Literal["empty_only", "unlocked_all"]
LineupViolationSeverity = Literal["warning", "error"]

_CATCHPHRASE_LINE = re.compile(r"^常用表达:\s*(.+)$", re.MULTILINE)
_CATCHPHRASE_SPLIT = re.compile(r"[；;、,，\n]+")

_PERSONALITY_STYLE_BUCKETS = {
    "balanced": "balanced",
    "aggressive": "pressure",
    "cautious": "cautious",
    "deceptive": "deceptive",
    "analytical": "analytical",
}
_STRATEGY_STYLE_BUCKETS = {
    "analysis": "analytical",
    "logic_leader": "analytical",
    "social_reader": "social",
    "aggressive": "pressure",
    "pressure_attacker": "pressure",
    "defensive": "cautious",
    "cautious_observer": "cautious",
    "deceptive": "deceptive",
    "shadow_wolf": "deceptive",
}


@dataclass(frozen=True)
class LineupQualityPolicyV1:
    schema_version: int = 1
    mode: LineupQualityMode = "repair"
    max_same_personality: int = 3
    max_same_catchphrase: int = 2
    max_same_avatar: int = 3
    max_same_strategy_profile: int = 3
    min_style_buckets: int = 4
    min_style_buckets_small: int = 3

    def required_style_buckets(self, player_count: int) -> int:
        if player_count >= 8:
            return min(self.min_style_buckets, player_count)
        if player_count >= 6:
            return min(self.min_style_buckets_small, player_count)
        return min(2, player_count)


@dataclass(frozen=True)
class LineupQualityViolationV1:
    code: str
    severity: LineupViolationSeverity
    key: str
    count: int
    limit: int
    seat_numbers: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "key": self.key,
            "count": self.count,
            "limit": self.limit,
            "seat_numbers": list(self.seat_numbers),
        }


@dataclass(frozen=True)
class LineupQualityReportV1:
    schema_version: int
    policy_mode: LineupQualityMode
    player_count: int
    configured_count: int
    is_blocked: bool
    was_repaired: bool
    style_bucket_count: int
    required_style_bucket_count: int
    violations: tuple[LineupQualityViolationV1, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_mode": self.policy_mode,
            "player_count": self.player_count,
            "configured_count": self.configured_count,
            "is_blocked": self.is_blocked,
            "was_repaired": self.was_repaired,
            "style_bucket_count": self.style_bucket_count,
            "required_style_bucket_count": self.required_style_bucket_count,
            "violations": [violation.to_dict() for violation in self.violations],
        }


def evaluate_lineup_quality(
    configs: Sequence[PlayerConfig],
    *,
    player_count: int | None = None,
    policy: LineupQualityPolicyV1 | None = None,
    was_repaired: bool = False,
) -> LineupQualityReportV1:
    active_policy = policy or LineupQualityPolicyV1()
    expected_count = player_count if player_count is not None else len(configs)
    ordered = sorted(configs, key=lambda config: config.seat)
    violations: list[LineupQualityViolationV1] = []

    if len(ordered) < expected_count:
        violations.append(
            LineupQualityViolationV1(
                code="lineup_incomplete",
                severity="error",
                key="missing_seats",
                count=expected_count - len(ordered),
                limit=0,
            )
        )

    _append_overrepresentation_violations(
        violations,
        ordered,
        values=((config.personality_id or "balanced") for config in ordered),
        code="personality_overrepresented",
        limit=active_policy.max_same_personality,
    )
    _append_overrepresentation_violations(
        violations,
        ordered,
        values=(_strategy_key(config) for config in ordered),
        code="strategy_profile_overrepresented",
        limit=active_policy.max_same_strategy_profile,
    )
    _append_multi_value_violations(
        violations,
        ordered,
        values=(_catchphrases(config) for config in ordered),
        code="catchphrase_overrepresented",
        limit=active_policy.max_same_catchphrase,
    )
    _append_overrepresentation_violations(
        violations,
        ordered,
        values=(_avatar_key(config) for config in ordered),
        code="avatar_overrepresented",
        limit=active_policy.max_same_avatar,
        ignore_empty=True,
    )
    _append_multi_value_violations(
        violations,
        ordered,
        values=(config.tags for config in ordered),
        code="tag_overrepresented",
        limit=3,
        severity="warning",
    )

    style_buckets = {_style_bucket(config) for config in ordered}
    style_buckets.discard("")
    required_style_buckets = active_policy.required_style_buckets(expected_count)
    if len(ordered) == expected_count and len(style_buckets) < required_style_buckets:
        violations.append(
            LineupQualityViolationV1(
                code="insufficient_style_buckets",
                severity="error",
                key="style_bucket",
                count=len(style_buckets),
                limit=required_style_buckets,
                seat_numbers=tuple(config.seat for config in ordered),
            )
        )

    return LineupQualityReportV1(
        schema_version=active_policy.schema_version,
        policy_mode=active_policy.mode,
        player_count=expected_count,
        configured_count=len(ordered),
        is_blocked=any(violation.severity == "error" for violation in violations),
        was_repaired=was_repaired,
        style_bucket_count=len(style_buckets),
        required_style_bucket_count=required_style_buckets,
        violations=tuple(violations),
    )


def plan_diverse_lineup(
    configs: Sequence[PlayerConfig],
    candidates: Sequence[PlayerConfig],
    *,
    player_count: int,
    seed: int | None,
    repair_scope: LineupRepairScope = "empty_only",
    locked_seats: Iterable[int] = (),
    policy: LineupQualityPolicyV1 | None = None,
) -> list[PlayerConfig]:
    active_policy = policy or LineupQualityPolicyV1()
    locked = {seat for seat in locked_seats if 1 <= seat <= player_count}
    configs_by_seat = {
        config.seat: config
        for config in configs
        if 1 <= config.seat <= player_count
    }
    if repair_scope == "unlocked_all":
        selected = [
            config
            for seat, config in configs_by_seat.items()
            if seat in locked and config.profile_id
        ]
    else:
        selected = [config for config in configs_by_seat.values() if config.profile_id]

    used_profile_ids = {
        config.profile_id for config in selected if config.profile_id is not None
    }
    available = [
        candidate
        for candidate in candidates
        if candidate.profile_id is not None and candidate.profile_id not in used_profile_ids
    ]
    missing_seats = [
        seat
        for seat in range(1, player_count + 1)
        if not any(config.seat == seat for config in selected)
    ]
    if len(available) < len(missing_seats):
        return sorted(selected, key=lambda config: config.seat)

    for seat in missing_seats:
        existing = configs_by_seat.get(seat) if repair_scope == "empty_only" else None
        ranked = sorted(
            available,
            key=lambda candidate: (
                _candidate_penalty(
                    [*selected, _config_for_seat(candidate, seat, existing)],
                    active_policy,
                ),
                _stable_candidate_rank(seed, seat, candidate.profile_id or ""),
                candidate.profile_id or "",
            ),
        )
        chosen = ranked[0]
        selected.append(_config_for_seat(chosen, seat, existing))
        available = [candidate for candidate in available if candidate is not chosen]

    return sorted(selected, key=lambda config: config.seat)


def legacy_lineup_warnings(report: LineupQualityReportV1) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    mapping = {
        "personality_overrepresented": (
            "homogeneous_personality_lineup",
            "personality_id",
        ),
        "catchphrase_overrepresented": (
            "shared_catchphrase_lineup",
            "catchphrase",
        ),
        "tag_overrepresented": ("shared_tag_lineup", "tag"),
    }
    for violation in report.violations:
        legacy = mapping.get(violation.code)
        if legacy is None:
            continue
        code, label = legacy
        if code in seen_codes:
            continue
        seen_codes.add(code)
        warnings.append(
            {
                "code": code,
                "detail": f"{violation.count} players share {label} {violation.key}.",
            }
        )
    return warnings


def _append_overrepresentation_violations(
    violations: list[LineupQualityViolationV1],
    configs: Sequence[PlayerConfig],
    *,
    values: Iterable[str],
    code: str,
    limit: int,
    severity: LineupViolationSeverity = "error",
    ignore_empty: bool = False,
) -> None:
    seats_by_value: dict[str, list[int]] = defaultdict(list)
    for config, value in zip(configs, values, strict=True):
        normalized = _normalize_key(value)
        if ignore_empty and not normalized:
            continue
        seats_by_value[normalized].append(config.seat)
    for key, seats in sorted(seats_by_value.items(), key=lambda item: -len(item[1])):
        if len(seats) <= limit:
            continue
        violations.append(
            LineupQualityViolationV1(
                code=code,
                severity=severity,
                key=key,
                count=len(seats),
                limit=limit,
                seat_numbers=tuple(sorted(seats)),
            )
        )


def _append_multi_value_violations(
    violations: list[LineupQualityViolationV1],
    configs: Sequence[PlayerConfig],
    *,
    values: Iterable[Sequence[str]],
    code: str,
    limit: int,
    severity: LineupViolationSeverity = "error",
) -> None:
    seats_by_value: dict[str, list[int]] = defaultdict(list)
    for config, items in zip(configs, values, strict=True):
        seen: set[str] = set()
        for item in items:
            normalized = _normalize_key(item)
            if not normalized or normalized in seen:
                continue
            seats_by_value[normalized].append(config.seat)
            seen.add(normalized)
    for key, seats in sorted(seats_by_value.items(), key=lambda item: -len(item[1])):
        if len(seats) <= limit:
            continue
        violations.append(
            LineupQualityViolationV1(
                code=code,
                severity=severity,
                key=key,
                count=len(seats),
                limit=limit,
                seat_numbers=tuple(sorted(seats)),
            )
        )


def _candidate_penalty(
    configs: Sequence[PlayerConfig],
    policy: LineupQualityPolicyV1,
) -> tuple[int, int, int, int, int, int]:
    personality = Counter(_normalize_key(config.personality_id) for config in configs)
    strategy = Counter(_strategy_key(config) for config in configs)
    avatars = Counter(value for config in configs if (value := _avatar_key(config)))
    catchphrases = Counter(
        phrase for config in configs for phrase in set(_catchphrases(config))
    )
    styles = {_style_bucket(config) for config in configs}
    styles.discard("")
    overage = (
        sum(max(0, count - policy.max_same_personality) for count in personality.values()),
        sum(max(0, count - policy.max_same_catchphrase) for count in catchphrases.values()),
        sum(max(0, count - policy.max_same_avatar) for count in avatars.values()),
        sum(max(0, count - policy.max_same_strategy_profile) for count in strategy.values()),
    )
    duplicate_pressure = sum(count * count for count in personality.values()) + sum(
        count * count for count in strategy.values()
    )
    return (*overage, -len(styles), duplicate_pressure)


def _config_for_seat(
    candidate: PlayerConfig,
    seat: int,
    existing: PlayerConfig | None,
) -> PlayerConfig:
    if existing is None:
        return replace(candidate, seat=seat)
    return replace(
        candidate,
        seat=seat,
        name=existing.name or candidate.name,
        model=existing.model or candidate.model,
    )


def _catchphrases(config: PlayerConfig) -> tuple[str, ...]:
    if config.catchphrases:
        return tuple(
            normalized
            for phrase in config.catchphrases
            if (normalized := _normalize_catchphrase(phrase))
        )
    match = _CATCHPHRASE_LINE.search(config.personality or "")
    if match is None:
        return ()
    return tuple(
        normalized
        for phrase in _CATCHPHRASE_SPLIT.split(match.group(1))
        if (normalized := _normalize_catchphrase(phrase))
    )


def _strategy_key(config: PlayerConfig) -> str:
    return _normalize_key(config.strategy_profile or "balanced") or "balanced"


def _avatar_key(config: PlayerConfig) -> str:
    if config.avatar_asset_id:
        return f"asset:{_normalize_key(config.avatar_asset_id)}"
    appearance = _normalize_key(config.appearance_id)
    if not appearance or appearance == "default":
        return ""
    return f"appearance:{appearance}"


def _style_bucket(config: PlayerConfig) -> str:
    strategy = _strategy_key(config)
    if strategy in _STRATEGY_STYLE_BUCKETS:
        return _STRATEGY_STYLE_BUCKETS[strategy]
    personality = _normalize_key(config.personality_id or "balanced")
    return _PERSONALITY_STYLE_BUCKETS.get(personality, "other")


def _stable_candidate_rank(seed: int | None, seat: int, profile_id: str) -> str:
    return hashlib.sha256(f"{seed}:lineup:{seat}:{profile_id}".encode()).hexdigest()


def _normalize_key(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value)).strip().split())


def _normalize_catchphrase(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value))
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in normalized
    )
    return " ".join(without_punctuation.strip().split())
