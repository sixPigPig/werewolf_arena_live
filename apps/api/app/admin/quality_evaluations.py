from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math
import re
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.game_session import GameSessionRecord
from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.werewolf.quality_evaluation import DEFAULT_EVALUATOR_VERSION, P0_ISSUE_CODES
from app.werewolf.quality_store import QualityEvaluationSuccessReference
from app.werewolf.worker_telemetry import (
    QUALITY_EVALUATION_WORKER_TYPE,
    runtime_worker_is_alive,
)


QUALITY_COHORT_DAYS = 7
QUALITY_COHORT_LIMIT = 5000
QUALITY_PERCENTILE_MIN_SAMPLES = 20
QUALITY_SOURCE_STATUSES = {"complete", "partial", "missing", "unavailable", "unknown"}
QUALITY_ISSUE_CHANNELS = {"live_event", "voice", "subtitle", "replay", "public_state"}
QUALITY_ISSUE_CODES = set(P0_ISSUE_CODES) | {"suspicious_private_term"}
QUALITY_ISSUE_ID_RE = re.compile(r"^quality_[0-9a-f]{24}$")
QUALITY_COORDINATE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
QUALITY_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
QUALITY_SOURCE_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
QUALITY_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
QUALITY_CLAUSE_ID_RE = re.compile(r"^[a-z0-9_.-]{1,120}$")
QUALITY_CRITICAL_ACTION_LIMIT = 64
QUALITY_CRITICAL_CLAUSE_LIMIT = 16
QUALITY_CRITICAL_ORIGINS = {
    "canceled",
    "failed",
    "model_after_retry",
    "model_first_attempt",
    "rule_default",
    "state_machine",
    "system_fallback",
    "system_timeout",
}
QUALITY_CRITICAL_INPUT_COMPLETENESS = {
    "complete",
    "critical_public_fact_missing",
    "private_observation_missing",
    "rule_missing",
    "unknown",
}
QUALITY_CRITICAL_ACTION_LEGALITY = {
    "invalid_normalized",
    "invalid_not_executed",
    "invalid_system_fallback",
    "legal_but_canceled",
    "legal_executed",
    "legal_system_result",
    "not_executed",
    "unknown",
}
QUALITY_CRITICAL_REASONING_OBSERVATIONS = {
    "hard_rule_conflict",
    "identity_information_conflict",
    "internal_logic_contradiction",
    "not_assessed",
    "not_available",
    "used_unspecified_rule",
}
QUALITY_CRITICAL_DIRECT_IMPACTS = {
    "canceled_no_effect",
    "failed_no_effect",
    "game_state_effect_applied",
    "model_result_applied",
    "no_state_change",
    "phase_ended",
    "system_result_applied",
    "vote_recorded",
}
QUALITY_CRITICAL_ATTRIBUTIONS = {
    "canceled",
    "model_internal_logic_contradiction",
    "model_judgment_and_rule_input_gap",
    "model_reasoning_error",
    "not_determined",
    "runtime_fallback",
}
QUALITY_CRITICAL_COVERAGE_STATUSES = {"complete", "partial", "missing", "unknown"}


def build_admin_quality_summary(
    record: GameQualityEvaluationRecord | None,
    *,
    terminal: bool,
    latest_successful_record: (
        GameQualityEvaluationRecord | QualityEvaluationSuccessReference | None
    ) = None,
) -> dict[str, Any]:
    if record is None:
        return _empty_summary(
            data_status="legacy" if terminal else "unavailable",
            can_retry=terminal,
            latest_successful_result=_latest_successful_result(latest_successful_record),
        )

    raw = record.safe_summary if isinstance(record.safe_summary, dict) else {}
    completed = record.status == "completed"
    data_status = _enum_text(
        record.data_status,
        {"collecting", "available", "partial", "legacy", "unavailable"},
        "unavailable" if record.status == "failed" else "collecting",
    )
    verdict = _enum_text(
        record.verdict,
        {"pass", "warn", "fail", "unavailable"},
        "unavailable",
    )
    if not completed:
        verdict = "unavailable"

    summary = _empty_summary(
        evaluator_version=(
            record.evaluator_version
            if QUALITY_VERSION_RE.fullmatch(record.evaluator_version)
            else DEFAULT_EVALUATOR_VERSION
        ),
        evaluation_status=_admin_evaluation_status(record.status),
        data_status=data_status,
        verdict=verdict,
        evaluated_at=(
            _iso_datetime(record.completed_at)
            if completed and record.completed_at is not None
            else None
        ),
        source_revision=(
            record.source_revision
            if QUALITY_SOURCE_REVISION_RE.fullmatch(record.source_revision)
            else None
        ),
        created_at=_iso_datetime(record.created_at),
        started_at=_iso_datetime(record.started_at),
        completed_at=_iso_datetime(record.completed_at),
        attempt_count=max(0, record.attempt_count),
        failure_reason=(
            _safe_text(record.last_error_code, 64)
            if record.last_error_code
            else None
        ),
        can_retry=(
            terminal
            and record.status not in {"pending", "processing"}
            and (
                record.status == "failed"
                or record.data_status == "partial"
                or record.evaluator_version != DEFAULT_EVALUATOR_VERSION
            )
        ),
        latest_successful_result=_latest_successful_result(latest_successful_record),
    )
    if not completed:
        return summary

    summary["source_coverage"] = _source_coverage(raw.get("source_coverage"))
    summary["issue_counts"] = _counts(raw.get("issue_counts"), ("P0", "P1", "P2"))
    summary["facts"] = _facts(raw.get("facts"))
    summary["structure"] = _structure(raw.get("structure"))
    summary["voice"] = _voice(raw.get("voice"))
    summary["performance"] = _performance(raw.get("performance"))
    summary["content"] = _content(raw.get("content"))
    summary["liveness"] = _liveness(raw.get("liveness"))
    summary["critical_actions"] = (
        _critical_actions(raw.get("critical_actions"))
        if terminal and data_status != "legacy"
        else []
    )
    return summary


def build_admin_quality_issues(
    record: GameQualityEvaluationRecord | None,
) -> list[dict[str, Any]]:
    if record is None or record.status != "completed":
        return []
    summary = record.safe_summary if isinstance(record.safe_summary, dict) else {}
    raw_issues = summary.get("safe_issues")
    if not isinstance(raw_issues, list):
        return []
    issues: list[dict[str, Any]] = []
    for raw in raw_issues[:200]:
        if not isinstance(raw, dict):
            continue
        issue_id = _safe_text(raw.get("issue_id"), 40)
        code = _enum_text(raw.get("code"), QUALITY_ISSUE_CODES, "")
        severity = _enum_text(raw.get("severity"), {"P0", "P1", "P2"}, "")
        channel = _enum_text(raw.get("channel"), QUALITY_ISSUE_CHANNELS, "")
        detected_at = _safe_datetime(raw.get("first_detected_at"))
        if (
            not all((issue_id, code, severity, channel, detected_at))
            or QUALITY_ISSUE_ID_RE.fullmatch(issue_id) is None
        ):
            continue
        issues.append(
            {
                "issue_id": issue_id,
                "code": code,
                "severity": severity,
                "channel": channel,
                "round_number": _optional_count(raw.get("round_number")),
                "event_id": _optional_count(raw.get("event_id")),
                "utterance_id": _safe_coordinate_id(raw.get("utterance_id")),
                "first_detected_at": detected_at,
            }
        )
    return issues


def build_admin_quality_overview(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(tz=UTC)
    cutoff = current - timedelta(days=QUALITY_COHORT_DAYS)
    cohort = list(
        db.scalars(
            select(GameQualityEvaluationRecord)
            .where(
                GameQualityEvaluationRecord.status == "completed",
                GameQualityEvaluationRecord.completed_at >= cutoff,
            )
            .order_by(GameQualityEvaluationRecord.completed_at.desc())
            .limit(QUALITY_COHORT_LIMIT)
        )
    )
    status_counts = {
        status: _record_count(db, GameQualityEvaluationRecord.status == status)
        for status in ("pending", "processing", "failed")
    }
    oldest_pending = db.scalar(
        select(func.min(GameQualityEvaluationRecord.created_at)).where(
            GameQualityEvaluationRecord.status == "pending"
        )
    )
    expired_leases = _record_count(
        db,
        GameQualityEvaluationRecord.status == "processing",
        GameQualityEvaluationRecord.lease_expires_at < current,
    )
    legacy_count = int(
        db.scalar(
            select(func.count())
            .select_from(GameSessionRecord)
            .where(
                GameSessionRecord.status.in_(("complete", "partial")),
                GameSessionRecord.updated_at >= cutoff,
                ~exists(
                    select(GameQualityEvaluationRecord.id).where(
                        GameQualityEvaluationRecord.session_id
                        == GameSessionRecord.session_id
                    )
                ),
            )
        )
        or 0
    )

    verdict_counts = {key: 0 for key in ("pass", "warn", "fail", "unavailable")}
    data_counts = {key: 0 for key in ("partial", "unavailable")}
    p0_game_count = 0
    latest_p0_at: datetime | None = None
    aggregates = _empty_aggregates()
    action_buckets: dict[str, int] = {}
    for record in cohort:
        verdict = record.verdict if record.verdict in verdict_counts else "unavailable"
        verdict_counts[verdict] += 1
        if record.data_status in data_counts:
            data_counts[record.data_status] += 1
        summary = record.safe_summary if isinstance(record.safe_summary, dict) else {}
        issue_counts = summary.get("issue_counts")
        if isinstance(issue_counts, dict) and _count(issue_counts.get("P0")) > 0:
            p0_game_count += 1
            completed_at = _as_utc(record.completed_at) if record.completed_at else None
            if completed_at and (latest_p0_at is None or completed_at > latest_p0_at):
                latest_p0_at = completed_at
        _add_quality_aggregates(aggregates, summary)
        _add_histogram_buckets(action_buckets, summary, "action_duration_histogram")

    action_count = int(aggregates["action_count"])
    return {
        "cohort_days": QUALITY_COHORT_DAYS,
        "sample_count": len(cohort),
        "pass_count": verdict_counts["pass"],
        "warn_count": verdict_counts["warn"],
        "fail_count": verdict_counts["fail"],
        "unavailable_count": verdict_counts["unavailable"],
        "partial_count": data_counts["partial"],
        "legacy_count": legacy_count,
        "p0_game_count": p0_game_count,
        "latest_p0_at": _iso_datetime(latest_p0_at),
        "pending_count": status_counts["pending"],
        "processing_count": status_counts["processing"],
        "worker_failed_count": status_counts["failed"],
        "expired_lease_count": expired_leases,
        "oldest_pending_seconds": (
            max(0, int((current - _as_utc(oldest_pending)).total_seconds()))
            if oldest_pending is not None
            else None
        ),
        "worker_up": runtime_worker_is_alive(
            db,
            worker_type=QUALITY_EVALUATION_WORKER_TYPE,
            max_age_seconds=settings.quality_evaluation_probe_max_age_seconds,
        ),
        "critical_fact_expected": int(aggregates["critical_fact_expected"]),
        "critical_fact_recorded": int(aggregates["critical_fact_recorded"]),
        "prompt_fact_expected": int(aggregates["prompt_fact_expected"]),
        "prompt_fact_included": int(aggregates["prompt_fact_included"]),
        "voice_expected": int(aggregates["voice_expected"]),
        "voice_covered": int(aggregates["voice_covered"]),
        "action_sample_count": action_count,
        "action_p95_ms": (
            _histogram_percentile_ms(action_buckets, action_count, 0.95)
            if action_count >= QUALITY_PERCENTILE_MIN_SAMPLES
            else None
        ),
        "speech_check_count": int(aggregates["speech_check_count"]),
        "repeated_speech_count": int(aggregates["repeated_speech_count"]),
        "speech_retry_exhausted_count": int(
            aggregates["speech_retry_exhausted_count"]
        ),
        "lineup_warning_count": int(aggregates["lineup_warning_count"]),
    }


def _empty_summary(
    *,
    evaluator_version: str = DEFAULT_EVALUATOR_VERSION,
    evaluation_status: str = "not_scheduled",
    data_status: str = "unavailable",
    verdict: str = "unavailable",
    evaluated_at: str | None = None,
    source_revision: str | None = None,
    created_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    attempt_count: int = 0,
    failure_reason: str | None = None,
    can_retry: bool = False,
    latest_successful_result: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "evaluator_version": evaluator_version,
        "evaluation_status": evaluation_status,
        "data_status": data_status,
        "verdict": verdict,
        "source_coverage": {
            "state": "unknown",
            "logs": "unknown",
            "events": "unknown",
            "voice": "unknown",
            "subtitles": "unknown",
            "pending_voice_count": 0,
            "failed_voice_count": 0,
        },
        "issue_counts": {"P0": 0, "P1": 0, "P2": 0},
        "facts": {
            "critical_opportunity_count": 0,
            "critical_recorded_count": 0,
            "critical_fact_write_rate": None,
            "prompt_expected_critical_count": 0,
            "prompt_included_critical_count": 0,
            "prompt_missing_critical_count": 0,
            "critical_fact_prompt_coverage_rate": None,
            "deterministic_contradiction_count": 0,
        },
        "structure": {
            "max_consecutive_self_explosions": 0,
            "chain_three_count": 0,
            "normal_day_debate_round_count": 0,
            "sheriff_model_request_count": 0,
            "public_model_request_count": 0,
            "sheriff_model_request_rate": None,
        },
        "voice": {
            "narratable_event_count": 0,
            "effective_voice_event_count": 0,
            "missing_narratable_event_count": 0,
            "voice_coverage_rate": None,
            "voice_source_event_lag": None,
            "terminal_judge_voice_coverage": None,
            "pending_voice_count": 0,
            "failed_voice_count": 0,
            "interruption_count": 0,
            "replay_count": 0,
        },
        "performance": {
            "action_count": 0,
            "action_duration_ms_max": None,
            "action_duration_p95_ms": None,
            "first_token_count": 0,
            "first_token_ms_max": None,
            "first_token_p95_ms": None,
            "game_duration_ms": None,
            "timeout_count": 0,
            "retry_count": 0,
            "fallback_count": 0,
            "logical_action_counts": {},
            "provider_attempt_counts": {},
            "retry_counts": {},
        },
        "content": {
            "speech_check_count": 0,
            "repeated_speech_count": 0,
            "repeated_speech_rate": None,
            "speech_rewrite_count": 0,
            "speech_rewrite_recovered_count": 0,
            "speech_retry_exhausted_count": 0,
            "privacy_p0_issue_count": 0,
            "lineup_warning_count": 0,
        },
        "liveness": _liveness({}),
        "critical_actions": [],
        "evaluated_at": evaluated_at,
        "source_revision": source_revision,
        "created_at": created_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "attempt_count": attempt_count,
        "failure_reason": failure_reason,
        "can_retry": can_retry,
        "latest_successful_result": latest_successful_result,
    }


def _source_coverage(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "state": _enum_text(raw.get("state"), QUALITY_SOURCE_STATUSES, "unknown"),
        "logs": _enum_text(raw.get("logs"), QUALITY_SOURCE_STATUSES, "unknown"),
        "events": _enum_text(raw.get("events"), QUALITY_SOURCE_STATUSES, "unknown"),
        "voice": _enum_text(raw.get("voice"), QUALITY_SOURCE_STATUSES, "unknown"),
        "subtitles": _enum_text(raw.get("subtitles"), QUALITY_SOURCE_STATUSES, "unknown"),
        "pending_voice_count": _count(raw.get("pending_voice_count")),
        "failed_voice_count": _count(raw.get("failed_voice_count")),
    }


def _facts(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        **_counts(
            raw,
            (
                "critical_opportunity_count",
                "critical_recorded_count",
                "prompt_expected_critical_count",
                "prompt_included_critical_count",
                "prompt_missing_critical_count",
                "deterministic_contradiction_count",
            ),
        ),
        "critical_fact_write_rate": _rate(raw.get("critical_fact_write_rate")),
        "critical_fact_prompt_coverage_rate": _rate(
            raw.get("critical_fact_prompt_coverage_rate")
        ),
    }


def _structure(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        **_counts(
            raw,
            (
                "max_consecutive_self_explosions",
                "chain_three_count",
                "normal_day_debate_round_count",
                "sheriff_model_request_count",
                "public_model_request_count",
            ),
        ),
        "sheriff_model_request_rate": _rate(raw.get("sheriff_model_request_rate")),
    }


def _voice(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    terminal = raw.get("terminal_judge_voice_coverage")
    return {
        **_counts(
            raw,
            (
                "narratable_event_count",
                "effective_voice_event_count",
                "missing_narratable_event_count",
                "pending_voice_count",
                "failed_voice_count",
                "interruption_count",
                "replay_count",
            ),
        ),
        "voice_coverage_rate": _rate(raw.get("voice_coverage_rate")),
        "voice_source_event_lag": _optional_count(raw.get("voice_source_event_lag")),
        "terminal_judge_voice_coverage": terminal if isinstance(terminal, bool) else None,
    }


def _performance(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    action_count = _count(raw.get("action_count"))
    first_token_count = _count(raw.get("first_token_count"))
    return {
        **_counts(
            raw,
            (
                "action_count",
                "first_token_count",
                "timeout_count",
                "retry_count",
                "fallback_count",
            ),
        ),
        "action_duration_ms_max": _optional_count(raw.get("action_duration_ms_max")),
        "action_duration_p95_ms": (
            _histogram_percentile_ms(
                _histogram_buckets(raw.get("action_duration_histogram")),
                action_count,
                0.95,
            )
            if action_count >= QUALITY_PERCENTILE_MIN_SAMPLES
            else None
        ),
        "first_token_ms_max": _optional_count(raw.get("first_token_ms_max")),
        "first_token_p95_ms": (
            _histogram_percentile_ms(
                _histogram_buckets(raw.get("first_token_histogram")),
                first_token_count,
                0.95,
            )
            if first_token_count >= QUALITY_PERCENTILE_MIN_SAMPLES
            else None
        ),
        "game_duration_ms": _optional_count(raw.get("game_duration_ms")),
        "logical_action_counts": _count_map(raw.get("logical_action_counts")),
        "provider_attempt_counts": _count_map(raw.get("provider_attempt_counts")),
        "retry_counts": _count_map(raw.get("retry_counts")),
    }


def _latest_successful_result(
    record: GameQualityEvaluationRecord | QualityEvaluationSuccessReference | None,
) -> dict[str, str] | None:
    if record is None or record.status != "completed" or record.completed_at is None:
        return None
    if not QUALITY_VERSION_RE.fullmatch(record.evaluator_version):
        return None
    if not QUALITY_SOURCE_REVISION_RE.fullmatch(record.source_revision):
        return None
    return {
        "evaluator_version": record.evaluator_version,
        "source_revision": record.source_revision,
        "completed_at": _iso_datetime(record.completed_at) or "",
    }


def _admin_evaluation_status(value: object) -> str:
    if value == "pending":
        return "queued"
    if value == "processing":
        return "running"
    return _enum_text(value, {"completed", "failed", "superseded"}, "failed")


def _count_map(value: object) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    result: dict[str, int] = {}
    for key, count in list(raw.items())[:80]:
        safe_key = _safe_text(key, 64)
        if safe_key and re.fullmatch(r"[A-Za-z0-9_.:-]+", safe_key):
            result[safe_key] = _count(count)
    return result


def _content(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        **_counts(
            raw,
            (
                "speech_check_count",
                "repeated_speech_count",
                "speech_rewrite_count",
                "speech_rewrite_recovered_count",
                "speech_retry_exhausted_count",
                "privacy_p0_issue_count",
                "lineup_warning_count",
            ),
        ),
        "repeated_speech_rate": _rate(raw.get("repeated_speech_rate")),
    }


def _liveness(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    actor_mind = raw.get("actor_mind")
    safe_actor_mind = actor_mind if isinstance(actor_mind, dict) else {}
    return {
        "experience_revision": _safe_text(raw.get("experience_revision"), 40) or None,
        "experiment_id": _safe_text(raw.get("experiment_id"), 64) or None,
        "variant": _safe_text(raw.get("variant"), 64) or None,
        "feature_modes": _liveness_feature_modes(raw.get("feature_modes")),
        "public_speech_count": _count(raw.get("public_speech_count")),
        "timing_coverage": _timing_coverage(raw.get("timing_coverage")),
        "stage_latency_ms": _stage_latencies(raw.get("stage_latency_ms")),
        "prompt_chars": _latency_summary(raw.get("prompt_chars")),
        "hard_gate_duration_ms": _latency_summary(
            raw.get("hard_gate_duration_ms")
        ),
        "hard_retry_count": _count(raw.get("hard_retry_count")),
        "hard_retry_rate": _rate(raw.get("hard_retry_rate")),
        "hard_exhausted_count": _count(raw.get("hard_exhausted_count")),
        "hard_exhausted_rate": _rate(raw.get("hard_exhausted_rate")),
        "partial_speech_count": _count(raw.get("partial_speech_count")),
        "interrupted_speech_count": _count(raw.get("interrupted_speech_count")),
        "voice_timing_coverage": _count_map(raw.get("voice_timing_coverage")),
        "tts_to_first_audio_ms": _latency_summary(
            raw.get("tts_to_first_audio_ms")
        ),
        "turn_to_first_audio_ms": _latency_summary(
            raw.get("turn_to_first_audio_ms")
        ),
        "voice_status_counts": _count_map(raw.get("voice_status_counts")),
        "playback_timing_coverage": _count_map(
            raw.get("playback_timing_coverage")
        ),
        "playback_status_counts": _count_map(raw.get("playback_status_counts")),
        "speaker_gap_ms": _latency_summary(raw.get("speaker_gap_ms")),
        "actor_mind": {
            "snapshot_count": _count(safe_actor_mind.get("snapshot_count")),
            "update_count": _count(safe_actor_mind.get("update_count")),
            "source_complete_count": _count(
                safe_actor_mind.get("source_complete_count")
            ),
        },
    }


def _liveness_feature_modes(value: object) -> dict[str, object]:
    raw = value if isinstance(value, dict) else {}
    allowed = {
        "style_gate": {"legacy", "async_observe"},
        "actor_mind": {"off", "shadow", "read"},
        "sentence_stream": {
            "off",
            "committed_segments",
            "committed_segments_v2",
        },
        "affect_delivery": {"off", "shadow", "on"},
        "voice_preempt": {"off", "deterministic"},
    }
    result: dict[str, object] = {
        key: value if isinstance(value, str) and value in choices else None
        for key, choices in allowed.items()
        if (value := raw.get(key)) is not None
    }
    prefetch = raw.get("tts_prefetch_depth")
    if type(prefetch) is int and prefetch in {0, 1}:
        result["tts_prefetch_depth"] = prefetch
    return result


def _timing_coverage(value: object) -> dict[str, dict[str, Any]]:
    raw = value if isinstance(value, dict) else {}
    fields = (
        "turn_ready_at",
        "actor_brain_started_at",
        "turn_plan_ready_at",
        "renderer_started_at",
        "first_model_delta_at",
        "first_clause_committed_at",
    )
    result: dict[str, dict[str, Any]] = {}
    for field in fields:
        item = raw.get(field)
        safe = item if isinstance(item, dict) else {}
        result[field] = {
            "count": _count(safe.get("count")),
            "denominator": _count(safe.get("denominator")),
            "rate": _rate(safe.get("rate")),
        }
    return result


def _stage_latencies(value: object) -> dict[str, dict[str, int | None]]:
    raw = value if isinstance(value, dict) else {}
    return {
        name: _latency_summary(raw.get(name))
        for name in (
            "turn_to_actor_brain",
            "actor_brain_to_plan",
            "plan_to_renderer",
            "renderer_to_first_delta",
            "first_delta_to_clause",
        )
    }


def _latency_summary(value: object) -> dict[str, int | None]:
    raw = value if isinstance(value, dict) else {}
    return {
        "count": _count(raw.get("count")),
        "p50": _optional_count(raw.get("p50")),
        "p95": _optional_count(raw.get("p95")),
        "max": _optional_count(raw.get("max")),
    }


def _critical_actions(value: object) -> list[dict[str, Any]]:
    """Project only the bounded, versioned decision-card contract."""
    if not isinstance(value, list):
        return []
    actions: list[dict[str, Any]] = []
    seen_action_ids: set[str] = set()
    for raw in value[:QUALITY_CRITICAL_ACTION_LIMIT]:
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            continue
        action_id = _strict_identifier(raw.get("action_id"), QUALITY_COORDINATE_ID_RE)
        action = _strict_identifier(raw.get("action"), QUALITY_ACTION_RE)
        round_number = raw.get("round_number")
        if round_number is not None and (
            type(round_number) is not int or not 0 <= round_number <= 1_000_000
        ):
            continue
        if not action_id or action_id in seen_action_ids or not action:
            continue
        origin = _enum_text(raw.get("action_origin"), QUALITY_CRITICAL_ORIGINS, "")
        input_completeness = _enum_text(
            raw.get("input_completeness"),
            QUALITY_CRITICAL_INPUT_COMPLETENESS,
            "",
        )
        legality = _enum_text(
            raw.get("action_legality"), QUALITY_CRITICAL_ACTION_LEGALITY, ""
        )
        reasoning = _enum_text(
            raw.get("reasoning_observation"),
            QUALITY_CRITICAL_REASONING_OBSERVATIONS,
            "",
        )
        direct_impact = _enum_text(
            raw.get("direct_impact"), QUALITY_CRITICAL_DIRECT_IMPACTS, ""
        )
        attribution = _enum_text(
            raw.get("attribution"), QUALITY_CRITICAL_ATTRIBUTIONS, ""
        )
        clause_ids = _critical_clause_ids(raw.get("clause_ids"))
        coverage = _critical_clause_coverage(raw.get("coverage"), clause_ids=clause_ids)
        if not all(
            (origin, input_completeness, legality, reasoning, direct_impact, attribution)
        ) or clause_ids is None or coverage is None:
            continue
        seen_action_ids.add(action_id)
        actions.append(
            {
                "schema_version": 1,
                "action_id": action_id,
                "round_number": round_number,
                "action": action,
                "action_origin": origin,
                "input_completeness": input_completeness,
                "action_legality": legality,
                "reasoning_observation": reasoning,
                "direct_impact": direct_impact,
                "attribution": attribution,
                "clause_ids": clause_ids,
                "coverage": coverage,
            }
        )
    return actions


def _critical_clause_ids(value: object) -> list[str] | None:
    if not isinstance(value, list) or len(value) > QUALITY_CRITICAL_CLAUSE_LIMIT:
        return None
    result: list[str] = []
    for raw in value:
        clause_id = _strict_identifier(raw, QUALITY_CLAUSE_ID_RE)
        if not clause_id or clause_id in result:
            return None
        result.append(clause_id)
    return result


def _critical_clause_coverage(
    value: object,
    *,
    clause_ids: list[str] | None,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or clause_ids is None or value.get("schema_version") != 1:
        return None
    status = _enum_text(
        value.get("status"), QUALITY_CRITICAL_COVERAGE_STATUSES, ""
    )
    required = value.get("required_count")
    included = value.get("included_count")
    missing = value.get("missing_count")
    missing_ids = _critical_clause_ids(value.get("missing_clause_ids"))
    if (
        not status
        or missing_ids is None
        or any(type(count) is not int or not 0 <= count <= QUALITY_CRITICAL_CLAUSE_LIMIT for count in (required, included, missing))
        or required != len(clause_ids)
        or any(clause_id not in clause_ids for clause_id in missing_ids)
        or missing != len(missing_ids)
    ):
        return None
    valid_shape = {
        "complete": included == required and missing == 0,
        "partial": included > 0 and missing > 0 and included + missing == required,
        "missing": required > 0 and included == 0 and missing == required,
        "unknown": included == 0 and missing == 0,
    }[status]
    if not valid_shape:
        return None
    return {
        "schema_version": 1,
        "status": status,
        "required_count": required,
        "included_count": included,
        "missing_count": missing,
        "missing_clause_ids": missing_ids,
    }


def _strict_identifier(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _empty_aggregates() -> dict[str, int]:
    return {
        "critical_fact_expected": 0,
        "critical_fact_recorded": 0,
        "prompt_fact_expected": 0,
        "prompt_fact_included": 0,
        "voice_expected": 0,
        "voice_covered": 0,
        "action_count": 0,
        "speech_check_count": 0,
        "repeated_speech_count": 0,
        "speech_retry_exhausted_count": 0,
        "lineup_warning_count": 0,
    }


def _add_quality_aggregates(result: dict[str, int], summary: dict[str, Any]) -> None:
    facts = summary.get("facts") if isinstance(summary.get("facts"), dict) else {}
    voice = summary.get("voice") if isinstance(summary.get("voice"), dict) else {}
    performance = (
        summary.get("performance") if isinstance(summary.get("performance"), dict) else {}
    )
    content = summary.get("content") if isinstance(summary.get("content"), dict) else {}
    mappings = (
        ("critical_fact_expected", facts, "critical_opportunity_count"),
        ("critical_fact_recorded", facts, "critical_recorded_count"),
        ("prompt_fact_expected", facts, "prompt_expected_critical_count"),
        ("prompt_fact_included", facts, "prompt_included_critical_count"),
        ("voice_expected", voice, "narratable_event_count"),
        ("voice_covered", voice, "effective_voice_event_count"),
        ("action_count", performance, "action_count"),
        ("speech_check_count", content, "speech_check_count"),
        ("repeated_speech_count", content, "repeated_speech_count"),
        ("speech_retry_exhausted_count", content, "speech_retry_exhausted_count"),
        ("lineup_warning_count", content, "lineup_warning_count"),
    )
    for target, source, key in mappings:
        result[target] += _count(source.get(key))


def _add_histogram_buckets(
    result: dict[str, int],
    summary: dict[str, Any],
    histogram_key: str,
) -> None:
    performance = summary.get("performance")
    if not isinstance(performance, dict):
        return
    for boundary, count in _histogram_buckets(performance.get(histogram_key)).items():
        result[boundary] = result.get(boundary, 0) + count


def _histogram_buckets(value: object) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    buckets = raw.get("buckets")
    if not isinstance(buckets, dict):
        return {}
    return {
        str(boundary): _count(count)
        for boundary, count in buckets.items()
        if str(boundary) == "+Inf" or _non_negative_float(boundary) is not None
    }


def _histogram_percentile_ms(
    buckets: dict[str, int],
    count: int,
    quantile: float,
) -> int | None:
    if count <= 0:
        return None
    threshold = math.ceil(count * quantile)
    finite = sorted(
        (
            (boundary, bucket_count)
            for key, bucket_count in buckets.items()
            if (boundary := _non_negative_float(key)) is not None
        ),
        key=lambda item: item[0],
    )
    for boundary, bucket_count in finite:
        if bucket_count >= threshold:
            return int(boundary * 1000)
    return None


def _record_count(db: Session, *filters: object) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(GameQualityEvaluationRecord).where(*filters)
        )
        or 0
    )


def _counts(value: object, keys: tuple[str, ...]) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    return {key: _count(raw.get(key)) for key in keys}


def _count(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _optional_count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _rate(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    rate = float(value)
    return rate if math.isfinite(rate) and 0 <= rate <= 1 else None


def _non_negative_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _safe_text(value: object, max_length: int) -> str:
    return value.replace("\x00", "").strip()[:max_length] if isinstance(value, str) else ""


def _safe_coordinate_id(value: object) -> str | None:
    return value if isinstance(value, str) and QUALITY_COORDINATE_ID_RE.fullmatch(value) else None


def _enum_text(value: object, allowed: set[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _safe_datetime(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return _iso_datetime(datetime.fromisoformat(value))
    except ValueError:
        return None


def _iso_datetime(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
