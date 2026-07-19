from __future__ import annotations

from app.werewolf.speech_repetition_audit import build_speech_repetition_audit


def _action(
    *,
    action_id: str,
    actor: str,
    text: str,
    mission: str | None,
    reason_code: str = "",
    attempts: int | None = 1,
    exhausted: bool = False,
    issues: list[dict[str, object]] | None = None,
    initial_codes: list[str] | None = None,
    novelty: float = 1.0,
    similarity: float = 0.0,
    new_propositions: int = 1,
) -> dict[str, object]:
    report = (
        {
            "mission_completed": True,
            "novelty_score": novelty,
            "lexical_similarity": similarity,
            "new_proposition_count": new_propositions,
            "issues": issues or [],
            "requires_rewrite": exhausted,
        }
        if mission is not None
        else None
    )
    return {
        "actor": actor,
        "action": "debate",
        "choice": text or None,
        "reason_code": reason_code or None,
        "lm_log": {"action_id": action_id},
        "speech_mission": (
            {"kind": mission, "reason_code": "round_robin"} if mission is not None else None
        ),
        "speech_quality_report": report,
        "speech_quality_attempt_count": attempts,
        "speech_quality_retry_exhausted": exhausted,
        "speech_quality_initial_codes": initial_codes or [],
    }


def test_audit_separates_no_speech_from_repetition_and_detects_paradox() -> None:
    repeated_rewrite = {
        "code": "repeated_debate_phrase",
        "severity": "rewrite",
        "score": 0.02,
    }
    repeated_warning = {
        "code": "repeated_debate_phrase",
        "severity": "warning",
        "score": 0.03,
    }
    logs = [
        {
            "number": 1,
            "debate": [
                _action(
                    action_id="one",
                    actor="甲",
                    text="今天我投3号，因为他的发言前后矛盾。",
                    mission="risk_controller",
                ),
                _action(
                    action_id="two",
                    actor="乙",
                    text="",
                    mission="risk_controller",
                    reason_code="quality_exhausted",
                    attempts=2,
                    exhausted=True,
                    issues=[repeated_rewrite],
                    initial_codes=["repeated_debate_phrase"],
                    novelty=0.98,
                    similarity=0.02,
                    new_propositions=0,
                ),
                _action(
                    action_id="three",
                    actor="丙",
                    text="今天我投3号，因为他的发言前后矛盾。",
                    mission="risk_controller",
                    issues=[repeated_warning],
                    novelty=0.97,
                    similarity=0.03,
                ),
                _action(
                    action_id="four",
                    actor="丁",
                    text="",
                    mission=None,
                    reason_code="timeout",
                    attempts=None,
                ),
            ],
        }
    ]
    profiles = [
        {"seat": index, "name": actor, "model": f"model-{index}"}
        for index, actor in enumerate(("甲", "乙", "丙", "丁"), start=1)
    ]
    live_events = [
        {"public_reason_code": "quality_exhausted"},
        {"public_reason_code": "timeout"},
    ]

    report = build_speech_repetition_audit(
        run_id="run_test",
        session_id="game_test",
        logs=logs,
        player_configs=profiles,
        live_no_speech_events=live_events,
    )

    summary = report["summary"]
    assert summary["public_speech_request_count"] == 4
    assert summary["spoken_count"] == 2
    assert summary["not_spoken_reason_counts"] == {
        "quality_exhausted": 1,
        "timeout": 1,
    }
    assert summary["quality_retry_count"] == 1
    assert summary["quality_retry_exhausted_count"] == 1
    assert summary["repetition_flagged_turn_count"] == 2
    assert summary["accepted_repetition_warning_count"] == 1
    assert summary["low_similarity_high_novelty_rewrite_count"] == 1
    assert summary["low_similarity_high_novelty_dropped_count"] == 1
    assert summary["repetition_rewrite_threshold"] == 0.3
    assert summary["historical_repetition_rewrite_count"] == 1
    assert summary["current_boundary_repetition_rewrite_count"] == 0
    assert summary["counterfactual_avoided_repetition_drop_count"] == 1
    assert report["turns"][1]["quality_rewrite_codes"] == ["repeated_debate_phrase"]
    assert report["live_event_crosscheck"]["matches_action_log_reasons"] is True


def test_audit_reports_mission_collisions_and_only_pairs_spoken_turns() -> None:
    logs = [
        {
            "number": 2,
            "debate": [
                _action(
                    action_id="one",
                    actor="甲",
                    text="第一轮为什么投3号？请解释票型。",
                    mission="consolidator",
                ),
                _action(
                    action_id="two",
                    actor="乙",
                    text="第一轮为什么投3号？请解释票型。",
                    mission="consolidator",
                ),
                _action(
                    action_id="three",
                    actor="丙",
                    text="",
                    mission="consolidator",
                    reason_code="quality_exhausted",
                ),
            ],
        }
    ]

    report = build_speech_repetition_audit(
        run_id="run_test",
        session_id="game_test",
        logs=logs,
    )

    summary = report["summary"]
    assert summary["mission_assigned_count"] == 3
    assert summary["mission_collision_count"] == 2
    assert summary["max_consecutive_same_mission"] == 3
    assert summary["counterfactual_mission_collision_count"] == 0
    assert summary["counterfactual_avoided_mission_collision_count"] == 2
    assert summary["counterfactual_max_consecutive_same_mission"] == 1
    assert summary["speech_pair_count"] == 1
    assert summary["exact_duplicate_pair_count"] == 1
    assert report["top_overlap_pairs"][0]["bigram_cosine"] == 1.0
    assert report["mission_rounds"][0]["mission_sequence"] == [
        "consolidator",
        "consolidator",
        "consolidator",
    ]


def test_audit_deduplicates_replayed_action_ids_and_ignores_non_speech() -> None:
    speech = _action(
        action_id="same",
        actor="甲",
        text="我今天投3号。",
        mission="vote_analyst",
    )
    logs = [
        {
            "number": 1,
            "debate": [speech, speech],
            "resolution": {
                "last_words": _action(
                    action_id="last-words",
                    actor="丙",
                    text="最后提醒好人关注3号的票型。",
                    mission="contradiction_hunter",
                )
                | {"action": "exile_last_words"}
            },
            "votes": [
                {
                    "actor": "乙",
                    "action": "vote",
                    "choice": "3号玩家",
                    "lm_log": {"action_id": "vote-one"},
                }
            ],
        }
    ]

    report = build_speech_repetition_audit(
        run_id="run_test",
        session_id="game_test",
        logs=logs,
    )

    assert report["summary"]["public_speech_request_count"] == 2
    assert report["turns"][0]["turn_id"] == "same"
    assert report["turns"][1]["turn_id"] == "last-words"
