from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal


ChoiceNormalizationKind = Literal[
    "exact",
    "string_exact",
    "seat_alias",
    "special_alias",
    "invalid",
    "ambiguous",
]


@dataclass(frozen=True)
class ChoiceNormalizationResult:
    raw_value: object
    canonical_value: object | None
    kind: ChoiceNormalizationKind
    matched_alias: str | None = None


DEFAULT_SPECIAL_ALIASES: dict[str, tuple[str, ...]] = {
    "不使用解药": ("不用解药", "不救"),
    "不使用毒药": ("不用毒药", "不毒"),
    "不发动技能": ("不开枪", "不发动"),
    "不自爆": ("不爆",),
}

_SEAT_REFERENCE = re.compile(
    r"^(?:玩家\s*)?0*(?P<seat>[0-9]{1,3})\s*号(?:\s*玩家)?$"
)
_BARE_SEAT = re.compile(r"^0*(?P<seat>[0-9]{1,3})$")


def normalize_action_choice(
    raw_value: object,
    allowed_values: Sequence[object],
    *,
    aliases: Mapping[object, Sequence[str]] | None = None,
) -> ChoiceNormalizationResult:
    """Normalize a model choice without guessing between legal candidates.

    Exact typed values win first. String and seat aliases are accepted only when
    the normalized alias identifies exactly one allowed value.
    """

    candidates = list(allowed_values)
    for candidate in candidates:
        if type(raw_value) is type(candidate) and raw_value == candidate:
            return ChoiceNormalizationResult(
                raw_value=raw_value,
                canonical_value=candidate,
                kind="exact",
            )

    if not candidates or not all(isinstance(candidate, str) for candidate in candidates):
        return ChoiceNormalizationResult(
            raw_value=raw_value,
            canonical_value=None,
            kind="invalid",
        )
    if raw_value is None or isinstance(raw_value, (dict, list, tuple, set)):
        return ChoiceNormalizationResult(
            raw_value=raw_value,
            canonical_value=None,
            kind="invalid",
        )

    normalized_raw = _normalize_text(str(raw_value))
    exact_matches = [
        index
        for index, candidate in enumerate(candidates)
        if _normalize_text(candidate) == normalized_raw
    ]
    if len(exact_matches) == 1:
        return ChoiceNormalizationResult(
            raw_value=raw_value,
            canonical_value=candidates[exact_matches[0]],
            kind="string_exact",
            matched_alias=normalized_raw,
        )
    if len(exact_matches) > 1:
        return ChoiceNormalizationResult(
            raw_value=raw_value,
            canonical_value=None,
            kind="ambiguous",
            matched_alias=normalized_raw,
        )

    alias_index: dict[str, list[tuple[int, ChoiceNormalizationKind]]] = {}
    for index, candidate in enumerate(candidates):
        assert isinstance(candidate, str)
        for alias, kind in _aliases_for_candidate(candidate, aliases=aliases):
            alias_index.setdefault(alias, []).append((index, kind))

    matches = alias_index.get(normalized_raw, [])
    candidate_indexes = sorted({index for index, _kind in matches})
    if len(candidate_indexes) != 1:
        return ChoiceNormalizationResult(
            raw_value=raw_value,
            canonical_value=None,
            kind="ambiguous" if matches else "invalid",
            matched_alias=normalized_raw if matches else None,
        )

    candidate_index = candidate_indexes[0]
    kinds = {kind for index, kind in matches if index == candidate_index}
    kind: ChoiceNormalizationKind = (
        "seat_alias" if "seat_alias" in kinds else "special_alias"
    )
    return ChoiceNormalizationResult(
        raw_value=raw_value,
        canonical_value=candidates[candidate_index],
        kind=kind,
        matched_alias=normalized_raw,
    )


def _aliases_for_candidate(
    candidate: str,
    *,
    aliases: Mapping[object, Sequence[str]] | None,
) -> list[tuple[str, ChoiceNormalizationKind]]:
    result: list[tuple[str, ChoiceNormalizationKind]] = []
    normalized_candidate = _normalize_text(candidate)
    seat = _seat_number(normalized_candidate)
    if seat is not None:
        for value in (
            str(seat),
            f"{seat:02d}",
            f"{seat}号",
            f"{seat}号玩家",
            f"玩家{seat}号",
        ):
            result.append((_normalize_text(value), "seat_alias"))

    for value in DEFAULT_SPECIAL_ALIASES.get(candidate, ()):
        result.append((_normalize_text(value), "special_alias"))
    if aliases is not None:
        for value in aliases.get(candidate, ()):
            if isinstance(value, str) and value.strip():
                result.append((_normalize_text(value), "special_alias"))
    return result


def _seat_number(value: str) -> int | None:
    match = _SEAT_REFERENCE.fullmatch(value) or _BARE_SEAT.fullmatch(value)
    if match is None:
        return None
    return int(match.group("seat"))


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())
