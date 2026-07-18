from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from app.rule_sets.types import RuleValidationIssue
from app.werewolf.rules import (
    ACTION_EXILE_LAST_WORDS,
    ACTION_HUNTER_SHOOT,
    ACTION_REMOVE,
    RULE_AUDIENCE_INTERNAL_ONLY,
    RULE_AUDIENCE_PLAYER_PUBLIC,
    RULE_AUDIENCES,
    RULE_CLAUSES,
    RULE_CONTRACT_REVISION_ID,
    RULE_CONTRACT_SCHEMA_VERSION,
    RuleConfigurationError,
    RuleSet,
    clause_ids_for_engine_constraint,
    rule_clauses_for_rule_set,
    rule_contract_hash,
    validate_rule_clauses,
)


RuleClausePriority = Literal["P0", "P1", "P2"]


@dataclass(frozen=True)
class AdminRuleContractReport:
    payload: dict[str, object]
    issues: tuple[RuleValidationIssue, ...]


@dataclass(frozen=True)
class _P0Requirement:
    clause_id: str
    engine_constraint_ids: tuple[str, ...]
    applies: Callable[[RuleSet], bool]


_P0_REQUIREMENTS = (
    _P0Requirement(
        clause_id="night.werewolf_attack.non_wolf_targets.v1",
        engine_constraint_ids=("engine.night.werewolf_attack.candidates_non_wolves",),
        applies=lambda rule_set: ACTION_REMOVE in rule_set.night_actions,
    ),
    _P0Requirement(
        clause_id="night.dawn.hidden_causes.v1",
        engine_constraint_ids=("projection.dawn.death_causes_hidden",),
        applies=lambda _rule_set: True,
    ),
    _P0Requirement(
        clause_id="day.exile.last_words_and_terminal.v1",
        engine_constraint_ids=(
            "engine.day.exile.last_words_eligible",
            "engine.day.exile.terminal_skips_last_words",
            "engine.day.exile.aftermath_order",
        ),
        applies=lambda rule_set: (
            rule_set.exile_last_words_enabled and ACTION_EXILE_LAST_WORDS in rule_set.day_actions
        ),
    ),
    _P0Requirement(
        clause_id="settlement.hunter.trigger_and_order.v1",
        engine_constraint_ids=(
            "engine.settlement.hunter.death_trigger_only",
            "engine.settlement.hunter.poison_disables_shot",
        ),
        applies=lambda rule_set: ACTION_HUNTER_SHOOT in rule_set.day_actions,
    ),
)
_P0_CLAUSE_IDS = frozenset(item.clause_id for item in _P0_REQUIREMENTS)


def build_admin_rule_contract(rule_set: RuleSet) -> AdminRuleContractReport:
    """Build the code-owned Admin projection and its publish blockers.

    The projection deliberately contains no persisted prompt text. Model-visible
    text comes only from the canonical rule-clause registry, and internal-only
    clauses are represented with a null model text.
    """

    registry_issue: RuleValidationIssue | None = None
    try:
        validate_rule_clauses(RULE_CLAUSES)
    except RuleConfigurationError:
        registry_issue = RuleValidationIssue(
            code="rule_contract_registry_invalid",
            path="rule_contract.clauses",
            message="The canonical rule-clause registry is invalid.",
        )

    clauses = rule_clauses_for_rule_set(rule_set, audiences=RULE_AUDIENCES)
    clauses_by_id = {clause.clause_id: clause for clause in clauses}
    requirements = tuple(item for item in _P0_REQUIREMENTS if item.applies(rule_set))
    missing_p0_clause_ids = tuple(
        item.clause_id for item in requirements if item.clause_id not in clauses_by_id
    )

    required_constraints_by_clause = {
        item.clause_id: item.engine_constraint_ids for item in requirements
    }
    broken_by_clause: dict[str, tuple[str, ...]] = {}
    for clause in clauses:
        expected = required_constraints_by_clause.get(clause.clause_id, ())
        missing_expected = set(expected) - set(clause.engine_constraint_ids)
        missing_reverse_links = {
            constraint_id
            for constraint_id in clause.engine_constraint_ids
            if clause.clause_id not in clause_ids_for_engine_constraint(constraint_id)
        }
        broken_by_clause[clause.clause_id] = tuple(sorted(missing_expected | missing_reverse_links))

    for requirement in requirements:
        if requirement.clause_id not in clauses_by_id:
            broken_by_clause[requirement.clause_id] = requirement.engine_constraint_ids

    broken_engine_constraint_ids = tuple(
        sorted(
            {
                constraint_id
                for constraint_ids in broken_by_clause.values()
                for constraint_id in constraint_ids
            }
        )
    )
    issues = [
        RuleValidationIssue(
            code="rule_contract_p0_clause_missing",
            path=f"rule_contract.clauses.{clause_id}",
            message=f"Required P0 rule clause {clause_id} is missing.",
        )
        for clause_id in missing_p0_clause_ids
    ]
    issues.extend(
        RuleValidationIssue(
            code="rule_contract_engine_constraint_uncovered",
            path=f"rule_contract.engine_constraint_ids.{constraint_id}",
            message=f"Engine constraint {constraint_id} is not covered by its rule clause.",
        )
        for constraint_id in broken_engine_constraint_ids
    )
    if registry_issue is not None:
        issues.append(registry_issue)

    publish_ready = not issues
    payload: dict[str, object] = {
        "schema_version": RULE_CONTRACT_SCHEMA_VERSION,
        "revision_id": RULE_CONTRACT_REVISION_ID,
        "canonical_hash": rule_contract_hash(rule_set),
        "coverage_status": "covered" if publish_ready else "broken",
        "publish_ready": publish_ready,
        "missing_p0_clause_ids": list(missing_p0_clause_ids),
        "broken_engine_constraint_ids": list(broken_engine_constraint_ids),
        "clauses": [
            {
                "clause_id": clause.clause_id,
                "priority": _clause_priority(clause.clause_id, clause.audience),
                "roles": list(clause.roles),
                "phases": list(clause.phases),
                "actions": list(clause.actions),
                "audience": clause.audience,
                "engine_constraint_ids": list(clause.engine_constraint_ids),
                "model_rule_text": (
                    None
                    if clause.audience == RULE_AUDIENCE_INTERNAL_ONLY
                    else clause.neutral_text_zh
                ),
                "coverage_status": (
                    "broken" if broken_by_clause.get(clause.clause_id) else "covered"
                ),
                "uncovered_engine_constraint_ids": list(broken_by_clause.get(clause.clause_id, ())),
            }
            for clause in clauses
        ],
    }
    return AdminRuleContractReport(payload=payload, issues=tuple(issues))


def _clause_priority(clause_id: str, audience: str) -> RuleClausePriority:
    if clause_id in _P0_CLAUSE_IDS:
        return "P0"
    if audience == RULE_AUDIENCE_PLAYER_PUBLIC:
        return "P1"
    return "P2"
