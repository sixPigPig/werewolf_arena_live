from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.api.schemas.admin_rule_sets import AdminRuleContractResponse
from app.rule_sets import contracts
from app.werewolf.rules import CLASSIC_12_SEER_WITCH_HUNTER_IDIOT, CLASSIC_8


def test_admin_rule_contract_projects_code_owned_clause_coverage() -> None:
    report = contracts.build_admin_rule_contract(CLASSIC_12_SEER_WITCH_HUNTER_IDIOT)

    assert report.issues == ()
    assert report.payload["schema_version"] == 1
    assert report.payload["revision_id"] == "2026-07-18.1"
    assert len(str(report.payload["canonical_hash"])) == 64
    assert report.payload["publish_ready"] is True
    clauses = report.payload["clauses"]
    assert isinstance(clauses, list)
    hunter = next(
        clause
        for clause in clauses
        if clause["clause_id"] == "settlement.hunter.trigger_and_order.v1"
    )
    assert hunter["priority"] == "P0"
    assert hunter["roles"] == ["猎人"]
    assert hunter["actions"] == ["hunter_shoot"]
    assert hunter["coverage_status"] == "covered"
    internal = next(clause for clause in clauses if clause["audience"] == "internal_only")
    assert internal["model_rule_text"] is None


def test_missing_applicable_p0_clause_blocks_contract_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = contracts.rule_clauses_for_rule_set

    def without_attack_clause(*args: object, **kwargs: object):
        return tuple(
            clause
            for clause in original(*args, **kwargs)
            if clause.clause_id != "night.werewolf_attack.non_wolf_targets.v1"
        )

    monkeypatch.setattr(contracts, "rule_clauses_for_rule_set", without_attack_clause)

    report = contracts.build_admin_rule_contract(CLASSIC_8)

    assert report.payload["publish_ready"] is False
    assert report.payload["missing_p0_clause_ids"] == ["night.werewolf_attack.non_wolf_targets.v1"]
    assert {issue.code for issue in report.issues} >= {
        "rule_contract_p0_clause_missing",
        "rule_contract_engine_constraint_uncovered",
    }


def test_non_wolf_target_clause_is_not_injected_when_wolf_targets_are_allowed() -> None:
    rule_set = replace(CLASSIC_8, werewolf_allow_wolf_target=True)

    report = contracts.build_admin_rule_contract(rule_set)

    assert report.payload["publish_ready"] is True
    assert "night.werewolf_attack.non_wolf_targets.v1" not in {
        clause["clause_id"] for clause in report.payload["clauses"]
    }


def test_broken_engine_constraint_reverse_link_blocks_contract_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = contracts.clause_ids_for_engine_constraint
    broken_id = "projection.dawn.death_causes_hidden"
    monkeypatch.setattr(
        contracts,
        "clause_ids_for_engine_constraint",
        lambda constraint_id: () if constraint_id == broken_id else original(constraint_id),
    )

    report = contracts.build_admin_rule_contract(CLASSIC_8)

    assert report.payload["publish_ready"] is False
    assert report.payload["broken_engine_constraint_ids"] == [broken_id]
    dawn = next(
        clause
        for clause in report.payload["clauses"]
        if clause["clause_id"] == "night.dawn.hidden_causes.v1"
    )
    assert dawn["coverage_status"] == "broken"
    assert dawn["uncovered_engine_constraint_ids"] == [broken_id]
    assert [issue.code for issue in report.issues] == ["rule_contract_engine_constraint_uncovered"]


def test_admin_rule_contract_schema_rejects_internal_model_text_and_false_readiness() -> None:
    report = contracts.build_admin_rule_contract(CLASSIC_8)
    clauses = [dict(clause) for clause in report.payload["clauses"]]
    internal = next(clause for clause in clauses if clause["audience"] == "internal_only")
    internal["model_rule_text"] = "must not enter model rules"

    with pytest.raises(ValidationError):
        AdminRuleContractResponse.model_validate({**report.payload, "clauses": clauses})
    with pytest.raises(ValidationError):
        AdminRuleContractResponse.model_validate({**report.payload, "publish_ready": False})
