from __future__ import annotations

import json
from pathlib import Path

from app.admin.p2_diagnostics import build_run_p2_diagnostics
from app.werewolf.evaluation_bundle import build_quality_evaluation_bundle
from app.werewolf.quality_evaluation import evaluate_quality_bundle
from app.werewolf.rules import get_rule_set, rule_contract_snapshot


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "game_16060126_evidence.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_game_16060126_runtime_and_replay_evidence_is_frozen() -> None:
    evidence = _fixture()
    session = evidence["session"]
    run = evidence["run"]

    assert session == {
        "session_id": "game_16060126",
        "status": "complete",
        "winner": "狼人阵营",
        "round_count": 3,
        "rule_set_id": "classic_12_seer_witch_hunter_idiot",
        "rule_set_revision_no": 2,
        "rule_set_content_hash": (
            "65befd4c3389ef37e592884d0aa7993fb0193d3304e0aa2b41fe8d0de4be4aeb"
        ),
    }
    assert run["status"] == "completed"
    assert run["recovery_attempts"] == 0
    assert run["live_event_count"] == 957
    assert run["minimum_event_id"] == 1
    assert run["maximum_event_id"] == run["distinct_event_id_count"] == 957
    assert run["replay_winner"] == session["winner"]
    assert run["replay_round_count"] == session["round_count"]
    assert run["quality_evaluation_record_count"] == 0


def test_game_16060126_attempt_and_logical_action_counts_stay_separate() -> None:
    diagnostics = _fixture()["p2_diagnostics"]

    projected = build_run_p2_diagnostics(
        logs=[],
        status="completed",
        diagnostic_events=[],
        started_at=None,
        completed_at=None,
        safe_diagnostics=diagnostics,
    )

    assert projected["provider_attempt_outcomes"] == {
        "attempt_count": 235,
        "valid_response_count": 221,
        "invalid_response_count": 2,
        "timed_out_count": 11,
        "canceled_count": 1,
        "transport_failed_count": 0,
    }
    assert projected["logical_action_outcomes"] == {
        "action_count": 377,
        "completed_count": 206,
        "fallback_count": 11,
        "canceled_count": 160,
        "failed_count": 0,
    }
    assert diagnostics["performance"]["fallback_count"] == (
        projected["logical_action_outcomes"]["fallback_count"]
        + projected["logical_action_outcomes"]["canceled_count"]
    )


def test_game_16060126_three_reasoning_attributions_are_stable() -> None:
    samples = {item["sample_id"]: item for item in _fixture()["reasoning_samples"]}

    self_explosion = samples["r1-seat2-self-explosion"]
    assert self_explosion["prompt_private_wolf_teammates"] == ["林砚", "老周", "沈雾"]
    assert "阿烈" not in self_explosion["prompt_private_wolf_teammates"]
    assert self_explosion["expected_attribution"] == "model_reasoning_error"

    witch_save = samples["r2-seat3-witch-save"]
    assert witch_save["known_attack_target"] == "祁野"
    assert witch_save["legal_options"] == ["祁野", "不使用解药"]
    assert witch_save["expected_attribution"] == "model_internal_logic_contradiction"

    public_vote = samples["r3-seat8-vote"]
    assert public_vote["engine_wolf_kill_candidate_policy"] == "non_werewolf_only"
    assert public_vote["historical_prompt_clause_present"] is False
    assert public_vote["expected_attribution"] == "model_judgment_and_rule_input_gap"

    current_contract = rule_contract_snapshot(get_rule_set("classic_12_seer_witch_hunter_idiot"))
    assert "night.werewolf_attack.non_wolf_targets.v1" in current_contract["injected_clause_ids"]


def test_game_16060126_decision_cards_match_the_three_manual_attributions() -> None:
    evidence = _fixture()
    samples = evidence["reasoning_samples"]
    roles = evidence["roles"]
    sentinel = "PRIVATE_REASONING_SENTINEL_GAME_16060126"
    logs: list[dict[str, object]] = []
    for sample in samples:
        sample_id = sample["sample_id"]
        markers = sample["reasoning_evidence_markers"]
        if sample_id == "r1-seat2-self-explosion":
            prompt = (
                "狼人白天公开阶段可以自爆，自爆会结束当日。"
                f"你的狼人队友名单是：{'、'.join(sample['prompt_private_wolf_teammates'])}。"
            )
            reasoning = f"{markers[0]}是我的{markers[1]}。{sentinel}"
            options = ["自爆", "不自爆"]
        elif sample_id == "r2-seat3-witch-save":
            prompt = (
                "女巫拥有一瓶解药。"
                f"今晚被狼人袭击的是{sample['known_attack_target']}。"
                f"候选人：{'、'.join(sample['legal_options'])}。"
            )
            reasoning = f"{'，'.join(markers)}。{sentinel}"
            options = sample["legal_options"]
        else:
            assert sample["historical_prompt_clause_present"] is False
            prompt = "白天放逐按唯一最高票结算，最高票平票时进入PK二轮投票。"
            reasoning = f"{'，'.join(markers)}。{sentinel}"
            options = [sample["effective_choice"]]
        logs.append(
            {
                "number": sample["round"],
                "actions": [
                    {
                        "actor": sample["actor"],
                        "action": sample["action"],
                        "options": options,
                        "choice": sample["effective_choice"],
                        "lifecycle_status": "completed",
                        "effective_origin": "model",
                        "attempt_count": 1,
                        "lm_log": {
                            "action_id": sample["action_id"],
                            "request_id": sample["request_id"],
                            "prompt": prompt,
                            "raw_response": sentinel,
                            "result": {
                                "reasoning": reasoning,
                                sample["action"]: sample["effective_choice"],
                            },
                            "attempt_outcomes": [
                                {
                                    "action_id": sample["action_id"],
                                    "request_id": sample["request_id"],
                                    "attempt_result": "valid_response",
                                }
                            ],
                        },
                    }
                ],
            }
        )
    bundle = build_quality_evaluation_bundle(
        state={
            "session_id": evidence["session"]["session_id"],
            "winner": evidence["session"]["winner"],
            "players": roles,
            "rounds": [],
        },
        logs=logs,
    )

    report = evaluate_quality_bundle(bundle, hmac_key="game-16060126-test-key")
    cards = {card.action_id: card.to_dict() for card in report.critical_actions}

    assert set(cards) == {sample["action_id"] for sample in samples}
    for sample in samples:
        card = cards[sample["action_id"]]
        assert card["attribution"] == sample["expected_attribution"]
        assert card["action_legality"] == "legal_executed"
        assert card["coverage"]["required_count"] == len(card["clause_ids"])
    assert cards["act_a2fc48858239"]["input_completeness"] == "complete"
    assert cards["act_a2fc48858239"]["reasoning_observation"] == "identity_information_conflict"
    assert cards["act_a2fc48858239"]["direct_impact"] == "phase_ended"
    assert cards["act_848fc2daefeb"]["input_completeness"] == "complete"
    assert cards["act_848fc2daefeb"]["reasoning_observation"] == "internal_logic_contradiction"
    assert cards["act_848fc2daefeb"]["direct_impact"] == "no_state_change"
    vote_card = cards["act_a46631561655"]
    assert vote_card["input_completeness"] == "rule_missing"
    assert vote_card["reasoning_observation"] == "used_unspecified_rule"
    assert vote_card["direct_impact"] == "vote_recorded"
    assert vote_card["coverage"]["missing_clause_ids"] == [
        "night.werewolf_attack.non_wolf_targets.v1"
    ]
    assert sentinel not in json.dumps(report.to_dict(), ensure_ascii=False)
