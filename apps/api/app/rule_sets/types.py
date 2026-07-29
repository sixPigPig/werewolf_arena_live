from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal


if TYPE_CHECKING:
    from app.werewolf.rules import RuleSet


RuleRoleId = Literal["werewolf", "villager", "seer", "guard", "witch", "hunter", "idiot"]


@dataclass(frozen=True)
class RuleSetConfig:
    name: str
    description: str
    complexity: str
    estimated_duration: str
    rule_tags: tuple[str, ...]
    role_counts: dict[RuleRoleId, int]
    win_condition: Literal["wolves_gte_others", "slaughter_side"]
    sheriff_enabled: bool
    sheriff_vote_weight: float
    speech_policy: Literal["sequential", "sheriff_directed"]
    werewolf_self_explosion_enabled: bool
    first_night_last_words_enabled: bool
    sheriff_badge_bomb_policy: Literal["none", "double"]

    @property
    def player_count(self) -> int:
        return sum(self.role_counts.values())


@dataclass(frozen=True)
class CompiledRuleSet:
    rule_set: RuleSet
    snapshot: dict[str, Any]
    schema_version: int
    revision_id: str | None
    revision_no: int | None
    content_hash: str


@dataclass(frozen=True)
class RuleValidationIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class RuleSetValidationResult:
    errors: tuple[RuleValidationIssue, ...]
    warnings: tuple[RuleValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors
