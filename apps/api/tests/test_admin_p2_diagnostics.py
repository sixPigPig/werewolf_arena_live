from datetime import UTC, datetime, timedelta

from app.admin.p2_diagnostics import (
    build_game_p2_quality,
    build_run_p2_diagnostics,
)


PRIVATE_SENTINEL = "SENTINEL_PRIVATE_P2_VALUE"


def _action(
    *,
    duration_ms: int,
    action: str = "vote",
    normalization: str | None = None,
    fallback_reason: str | None = None,
) -> dict[str, object]:
    return {
        "action": action,
        "lm_log": {
            "prompt": PRIVATE_SENTINEL,
            "raw_response": PRIVATE_SENTINEL,
        },
        "duration_ms": duration_ms,
        "choice_normalization_kind": normalization,
        "fallback_reason": fallback_reason,
        "raw_choice": PRIVATE_SENTINEL,
        "private_candidates": [PRIVATE_SENTINEL],
        "rejected_draft": PRIVATE_SENTINEL,
    }


def test_run_projection_aggregates_metrics_without_private_values() -> None:
    started_at = datetime(2026, 7, 14, tzinfo=UTC)
    logs = [
        _action(duration_ms=index * 100, normalization="seat_alias")
        for index in range(1, 20)
    ]
    logs.append(
        {
            **_action(
                duration_ms=2_000,
                action="debate",
                fallback_reason="timeout_first_token",
            ),
            "first_token_ms": 900,
            "speech_quality_report": {
                "issues": [{"code": "low_proposition_novelty"}]
            },
            "speech_quality_attempt_count": 2,
            "speech_quality_retry_exhausted": True,
        }
    )

    result = build_run_p2_diagnostics(
        logs=logs,
        status="completed",
        diagnostic_events=[],
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=3),
    )

    assert result["data_status"] == "available"
    assert result["performance"] == {
        "request_count": 20,
        "discrete_action_sample_count": 19,
        "discrete_action_p50_ms": 1_000,
        "discrete_action_p95_ms": None,
        "discrete_action_max_ms": 1_900,
        "speech_first_token_sample_count": 1,
        "speech_first_token_p95_ms": None,
        "speech_first_token_max_ms": 900,
        "timeout_count": 1,
        "fallback_count": 1,
        "active_request_count": 0,
        "game_duration_ms": 3_000,
    }
    assert result["speech_quality"] == {
        "checked_count": 1,
        "retry_count": 1,
        "exhausted_count": 1,
        "low_novelty_window_count": 1,
    }
    assert result["choice_normalization"]["seat_alias_count"] == 19
    assert PRIVATE_SENTINEL not in str(result)


def test_run_projection_only_reports_p95_with_twenty_samples() -> None:
    result = build_run_p2_diagnostics(
        logs=[_action(duration_ms=index) for index in range(1, 21)],
        status="completed",
        diagnostic_events=[],
        started_at=None,
        completed_at=None,
    )

    assert result["performance"]["discrete_action_sample_count"] == 20
    assert result["performance"]["discrete_action_p95_ms"] == 19


def test_stored_projection_uses_whitelist_and_live_request_state() -> None:
    result = build_run_p2_diagnostics(
        logs=[],
        status="running",
        diagnostic_events=[
            {
                "type": "model_request_started",
                "payload": {
                    "request_id": "req-safe-count-only",
                    "prompt": PRIVATE_SENTINEL,
                },
            }
        ],
        started_at=None,
        completed_at=None,
        safe_diagnostics={
            "schema_version": 1,
            "performance": {
                "request_count": 99,
                "discrete_action_sample_count": 1,
                "discrete_action_max_ms": 450,
                "raw_response": PRIVATE_SENTINEL,
            },
            "speech_quality": {"checked_count": 1, "draft": PRIVATE_SENTINEL},
            "choice_normalization": {
                "seat_alias_count": 1,
                "raw_choice": PRIVATE_SENTINEL,
            },
            "prompt": PRIVATE_SENTINEL,
        },
    )

    assert result["data_status"] == "collecting"
    assert result["performance"]["request_count"] == 1
    assert result["performance"]["active_request_count"] == 1
    assert PRIVATE_SENTINEL not in str(result)


def test_game_projection_whitelists_lineup_and_orders_public_outcomes() -> None:
    state = {
        "players": [
            {"name": "2号玩家"},
            {"name": "5号玩家"},
        ],
        "rounds": [
            {
                "number": 2,
                "players": ["2号玩家", "5号玩家"],
                "public_summary": "intentionally mismatched",
                "public_outcome_events": [
                    {
                        "schema_version": 1,
                        "event_id": "outcome_2222222222222222",
                        "sequence": 2,
                        "kind": "hunter_shot",
                        "actor_player_id": "2号玩家",
                        "target_player_id": "5号玩家",
                        "outcome": "eliminated",
                        "caused_by_event_id": "outcome_1111111111111111",
                        "occurred_phase": "night",
                        "cause": PRIVATE_SENTINEL,
                    },
                    {
                        "schema_version": 1,
                        "event_id": "outcome_1111111111111111",
                        "sequence": 1,
                        "kind": "night_death",
                        "actor_player_id": None,
                        "target_player_id": "2号玩家",
                        "outcome": "eliminated",
                        "caused_by_event_id": None,
                        "occurred_phase": "night",
                        "source": PRIVATE_SENTINEL,
                    },
                ],
            }
        ]
    }
    result = build_game_p2_quality(
        state=state,
        logs=[_action(duration_ms=500)],
        lineup_quality_report={
            "schema_version": 1,
            "policy_mode": "repair",
            "was_repaired": True,
            "is_blocked": False,
            "style_bucket_count": 4,
            "required_style_bucket_count": 4,
            "violations": [
                {
                    "code": PRIVATE_SENTINEL,
                    "severity": "warning",
                    "count": 2,
                    "limit": 1,
                    "seat_numbers": [2, 5],
                    "key": PRIVATE_SENTINEL,
                }
            ],
        },
        status="complete",
        terminal=True,
        diagnostic_events=[],
        started_at=None,
        completed_at=None,
    )

    assert [event["event_id"] for event in result["public_outcomes"]] == [
        "outcome_1111111111111111",
        "outcome_2222222222222222",
    ]
    assert (
        result["public_outcomes"][1]["caused_by_event_id"]
        == "outcome_1111111111111111"
    )
    assert result["public_outcome_summary_mismatch_count"] == 1
    assert len(result["quality_gates"]) == 5
    assert result["lineup_quality"]["violations"][0]["seat_numbers"] == [2, 5]
    assert result["lineup_quality"]["violations"][0]["code"] == "unknown"
    assert PRIVATE_SENTINEL not in str(result)


def test_legacy_and_unavailable_states_do_not_report_passing_gates() -> None:
    for state, expected in [({}, "unavailable"), ({"rounds": []}, "legacy")]:
        result = build_game_p2_quality(
            state=state,
            logs=[],
            lineup_quality_report={},
            status="complete",
            terminal=True,
            diagnostic_events=[],
            started_at=None,
            completed_at=None,
        )

        assert result["data_status"] == expected
        assert all(gate["status"] != "pass" for gate in result["quality_gates"])
