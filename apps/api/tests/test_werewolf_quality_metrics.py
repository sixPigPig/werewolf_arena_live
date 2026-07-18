from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.game_session import GameSessionRecord
from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.evaluation_bundle import build_quality_evaluation_bundle
from app.werewolf.execution_telemetry import (
    record_action_execution,
    render_action_execution_metrics,
    reset_action_execution_metrics_for_tests,
)
from app.werewolf.public_facts import PublicFact, fact_prompt_coverage
from app.werewolf.quality_evaluation import evaluate_quality_bundle
from app.werewolf.quality_evaluation_telemetry import render_quality_evaluation_metrics
from app.werewolf.rules import get_rule_set


def test_engine_links_public_fact_to_stable_recorded_opportunity() -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="game_factop",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=object(),  # type: ignore[arg-type]
        max_rounds=1,
        rule_set=rule_set,
    )

    engine._add_public_fact(
        1,
        "claim",
        "1号玩家警上声明自己是预言家。",
        stage="sheriff_speech",
        actor="1号玩家",
        retention="critical",
    )

    fact = state.public_facts[0]
    opportunity = state.public_fact_opportunities[0]
    assert opportunity["status"] == "recorded"
    assert opportunity["fact_id"] == fact["fact_id"]
    assert fact["source_opportunity_id"] == opportunity["opportunity_id"]
    assert fact["schema_version"] == 3


def test_prompt_fact_coverage_has_explicit_expected_and_missing_denominators() -> None:
    facts = [
        PublicFact(
            round_number=1,
            category="claim",
            text="1号玩家声明自己是预言家。",
            fact_id="fact-1",
            retention="critical",
        ),
        PublicFact(
            round_number=1,
            category="vote",
            text="第一轮票型已经公开。",
            fact_id="fact-2",
            retention="critical",
        ),
    ]

    coverage = fact_prompt_coverage(facts, ["第一轮票型已经公开。"])

    assert coverage == {
        "schema_version": 1,
        "expected_critical_count": 2,
        "included_critical_count": 1,
        "missing_critical_count": 1,
        "coverage_status": "available",
        "missing_reason_counts": {"assembly_error": 1},
    }


def test_terminal_quality_metrics_have_exact_denominators_histograms_and_voice_states() -> None:
    state = {
        "session_id": "game_metrics",
        "winner": "好人阵营",
        "public_fact_opportunities": [
            {"retention": "critical", "status": "recorded"},
            {"retention": "critical", "status": "expected"},
        ],
        "public_fact_propositions": [
            {
                "subject": "1号玩家",
                "predicate": "alive",
                "object": "",
                "scope": "game",
                "polarity": True,
            },
            {
                "subject": "1号玩家",
                "predicate": "alive",
                "object": "",
                "scope": "game",
                "polarity": False,
            },
        ],
        "rounds": [
            {
                "number": number,
                "werewolf_self_exploded": f"{number}号玩家",
                "day_ended_by_self_explosion": True,
                "private_summaries": {},
                "debate": [],
                "votes": {},
            }
            for number in (1, 2, 3)
        ],
        "public_facts": [],
    }
    logs = [
        {
            "number": 1,
            "debate": [
                {
                    "actor": "1号玩家",
                    "action": "debate",
                    "duration_ms": 1250,
                    "first_token_ms": 250,
                    "attempt_count": 2,
                    "fact_prompt_coverage": {
                        "expected_critical_count": 2,
                        "included_critical_count": 1,
                        "missing_critical_count": 1,
                    },
                    "speech_quality_report": {"issues": [{"code": "repeated_debate_phrase"}]},
                    "speech_quality_attempt_count": 2,
                    "speech_quality_retry_exhausted": False,
                    "lm_log": {"result": {"say": "公开发言"}},
                }
            ],
        }
    ]
    events = [
        {
            "id": 1,
            "type": "game_started",
            "run_id": "run_metrics",
            "session_id": "game_metrics",
            "created_at": "2026-07-14T00:00:00+00:00",
            "payload": {},
        },
        {
            "id": 2,
            "type": "voice_interrupted",
            "run_id": "run_metrics",
            "session_id": "game_metrics",
            "created_at": "2026-07-14T00:09:58+00:00",
            "payload": {},
        },
        {
            "id": 3,
            "type": "voice_replayed",
            "run_id": "run_metrics",
            "session_id": "game_metrics",
            "created_at": "2026-07-14T00:09:59+00:00",
            "payload": {},
        },
        {
            "id": 4,
            "type": "game_completed",
            "run_id": "run_metrics",
            "session_id": "game_metrics",
            "created_at": "2026-07-14T00:10:00+00:00",
            "payload": {"winner": "好人阵营"},
        },
    ]
    voices = [
        {
            "utterance_id": "voice_terminal",
            "source_event_id": 4,
            "speaker_kind": "judge",
            "status": "complete",
            "text": "好人阵营获胜。",
            "subtitle_timings": [],
        }
    ]
    bundle = build_quality_evaluation_bundle(
        state=state,
        logs=logs,
        live_events=events,
        voice_utterances=voices,
        run_id="run_metrics",
        started_at="2026-07-14T00:00:00+00:00",
        completed_at="2026-07-14T00:10:00+00:00",
    )

    report = evaluate_quality_bundle(bundle, hmac_key="test-key")

    assert report.facts["critical_fact_write_rate"] == 0.5
    assert report.facts["critical_fact_prompt_coverage_rate"] == 0.5
    assert report.facts["deterministic_contradiction_count"] == 1
    assert report.structure["max_consecutive_self_explosions"] == 3
    assert report.structure["chain_three_count"] == 1
    assert report.voice["narratable_event_count"] == 2
    assert report.voice["effective_voice_event_count"] == 1
    assert report.voice["terminal_judge_voice_coverage"] is True
    assert report.voice["interruption_count"] == 1
    assert report.voice["replay_count"] == 1
    assert report.performance["game_duration_ms"] == 600_000
    assert report.performance["action_duration_histogram"]["buckets"]["+Inf"] == 1
    assert report.performance["first_token_histogram"]["buckets"]["0.25"] == 1
    assert report.performance["logical_action_counts"] == {
        "completed_by_model": 1,
        "completed_by_system_fallback": 0,
        "canceled": 0,
        "failed": 0,
    }
    assert report.performance["provider_attempt_counts"] == {
        "valid": 0,
        "invalid": 0,
        "timeout": 0,
        "transport_failure": 0,
        "canceled": 0,
    }
    assert report.performance["retry_counts"] == {
        "provider_retry": 0,
        "format_retry": 0,
        "quality_rewrite": 1,
    }
    assert report.content["repeated_speech_rate"] == 1.0
    assert report.content["speech_rewrite_recovered_count"] == 1


def test_action_histograms_are_cumulative_and_keep_inf_equal_to_count() -> None:
    reset_action_execution_metrics_for_tests()
    record_action_execution(
        action_kind="public_speech",
        model="deepseek-chat",
        result="completed",
        duration_ms=1250,
        first_token_ms=250,
        fallback_reason=None,
    )

    metrics = render_action_execution_metrics()

    assert "# TYPE werewolf_model_action_duration_seconds histogram" in metrics
    assert (
        'werewolf_model_action_duration_seconds_bucket{action_kind="public_speech",'
        'provider="deepseek",result="completed",le="1"} 0'
    ) in metrics
    assert (
        'werewolf_model_action_duration_seconds_bucket{action_kind="public_speech",'
        'provider="deepseek",result="completed",le="2"} 1'
    ) in metrics
    assert (
        'werewolf_model_action_duration_seconds_bucket{action_kind="public_speech",'
        'provider="deepseek",result="completed",le="+Inf"} 1'
    ) in metrics


def test_timeout_metrics_separate_provider_attempts_from_logical_fallbacks() -> None:
    logs = [
        {
            "number": 1,
            "actions": [
                {
                    "actor": "1号玩家",
                    "action": "vote",
                    "options": ["2号玩家"],
                    "choice": "2号玩家",
                    "lifecycle_status": "fallback",
                    "fallback_reason": "timeout_deterministic_legal_choice",
                    "lm_log": {
                        "action_id": "act_timeout_fallback",
                        "request_id": "req_timeout_2",
                        "prompt": "",
                        "result": None,
                        "attempt_outcomes": [
                            {
                                "action_id": "act_timeout_fallback",
                                "request_id": "req_timeout_1",
                                "attempt_result": "timed_out",
                            },
                            {
                                "action_id": "act_timeout_fallback",
                                "request_id": "req_timeout_2",
                                "attempt_result": "timed_out",
                            },
                        ],
                    },
                },
                {
                    "actor": "2号玩家",
                    "action": "vote",
                    "options": ["1号玩家"],
                    "choice": "1号玩家",
                    "lifecycle_status": "completed",
                    "lm_log": {
                        "action_id": "act_retry_recovered",
                        "request_id": "req_retry_2",
                        "prompt": "",
                        "result": {"reasoning": "", "vote": "1号玩家"},
                        "attempt_outcomes": [
                            {
                                "action_id": "act_retry_recovered",
                                "request_id": "req_retry_1",
                                "attempt_result": "timed_out",
                            },
                            {
                                "action_id": "act_retry_recovered",
                                "request_id": "req_retry_2",
                                "attempt_result": "valid_response",
                            },
                        ],
                    },
                },
                {
                    "actor": "3号玩家",
                    "action": "vote",
                    "options": ["1号玩家"],
                    "choice": None,
                    "lifecycle_status": "timed_out",
                    "lm_log": {
                        "action_id": "act_legacy_lifecycle_timeout",
                        "request_id": None,
                        "prompt": "",
                        "result": None,
                    },
                },
                {
                    "actor": "4号玩家",
                    "action": "vote",
                    "options": ["1号玩家"],
                    "choice": "1号玩家",
                    "lifecycle_status": "fallback",
                    "fallback_reason": "invalid_deterministic_legal_choice",
                    "lm_log": {
                        "action_id": "act_invalid_after_timeout",
                        "request_id": "req_invalid_2",
                        "prompt": "",
                        "result": None,
                        "attempt_outcomes": [
                            {
                                "action_id": "act_invalid_after_timeout",
                                "request_id": "req_invalid_1",
                                "attempt_result": "timed_out",
                            },
                            {
                                "action_id": "act_invalid_after_timeout",
                                "request_id": "req_invalid_2",
                                "attempt_result": "invalid_response",
                            },
                        ],
                    },
                },
            ],
        }
    ]
    bundle = build_quality_evaluation_bundle(
        state={"session_id": "game_timeout_split", "rounds": []},
        logs=logs,
    )

    performance = evaluate_quality_bundle(bundle, hmac_key="test-key").performance

    assert performance["timeout_count"] == 4
    assert performance["provider_timeout_count"] == 4
    assert performance["logical_timeout_fallback_count"] == 1
    assert performance["provider_attempt_counts"]["timeout"] == 4
    assert performance["logical_action_counts"] == {
        "completed_by_model": 1,
        "completed_by_system_fallback": 2,
        "canceled": 0,
        "failed": 1,
    }


def test_quality_prometheus_aggregates_only_fixed_safe_fields() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    marker = 'PRIVATE_METRIC_SENTINEL{session="secret"}'
    now = datetime.now(tz=UTC)
    with factory() as db:
        db.add(GameSessionRecord(session_id="game_metrics", status="complete"))
        db.flush()
        db.add(
            GameQualityEvaluationRecord(
                id="quality_metrics",
                session_id="game_metrics",
                evaluator_version="p3-v1",
                source_revision="a" * 64,
                status="completed",
                data_status="available",
                verdict="warn",
                duration_ms=500,
                completed_at=now,
                safe_summary={
                    "issue_counts": {"P0": 0, "P1": 0, "P2": 1},
                    "facts": {
                        "critical_opportunity_count": 2,
                        "critical_recorded_count": 1,
                        "prompt_expected_critical_count": 2,
                        "prompt_included_critical_count": 1,
                        "prompt_missing_critical_count": 1,
                        "deterministic_contradiction_count": 1,
                    },
                    "voice": {
                        "narratable_event_count": 2,
                        "effective_voice_event_count": 1,
                        "missing_narratable_event_count": 1,
                    },
                    "ignored": marker,
                },
            )
        )
        db.commit()
        metrics = render_quality_evaluation_metrics(db, worker_max_age_seconds=45)

    assert 'werewolf_quality_issues{severity="P2"} 1' in metrics
    assert 'werewolf_fact_opportunities{status="expected"} 2' in metrics
    assert 'werewolf_prompt_fact_coverage{result="missing"} 1' in metrics
    assert 'werewolf_voice_events{status="covered"} 1' in metrics
    assert marker not in metrics
