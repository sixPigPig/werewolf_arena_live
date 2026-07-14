from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.werewolf.worker_telemetry import (
    QUALITY_EVALUATION_WORKER_TYPE,
    runtime_worker_is_alive,
)


EVALUATION_DURATION_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)


def render_quality_evaluation_metrics(
    db: Session,
    *,
    worker_max_age_seconds: float,
) -> str:
    now = datetime.now(tz=UTC)
    status_counts = {
        status: _count(db, GameQualityEvaluationRecord.status == status)
        for status in ("pending", "processing", "completed", "failed", "superseded")
    }
    oldest = db.scalar(
        select(func.min(GameQualityEvaluationRecord.created_at)).where(
            GameQualityEvaluationRecord.status == "pending"
        )
    )
    oldest_age = (
        max(0.0, (now - _as_utc(oldest)).total_seconds()) if oldest is not None else 0.0
    )
    durations_ms = list(
        db.scalars(
            select(GameQualityEvaluationRecord.duration_ms)
            .where(
                GameQualityEvaluationRecord.status == "completed",
                GameQualityEvaluationRecord.completed_at >= now - timedelta(days=7),
                GameQualityEvaluationRecord.duration_ms.is_not(None),
            )
            .order_by(GameQualityEvaluationRecord.completed_at.desc())
            .limit(5000)
        )
    )
    durations = [max(0, value) / 1000 for value in durations_ms if value is not None]
    summaries = list(
        db.scalars(
            select(GameQualityEvaluationRecord.safe_summary)
            .where(
                GameQualityEvaluationRecord.status == "completed",
                GameQualityEvaluationRecord.completed_at >= now - timedelta(days=7),
            )
            .order_by(GameQualityEvaluationRecord.completed_at.desc())
            .limit(5000)
        )
    )
    lines = [
        "# HELP werewolf_quality_evaluator_up Whether an evaluator heartbeat is fresh.",
        "# TYPE werewolf_quality_evaluator_up gauge",
        "werewolf_quality_evaluator_up "
        + (
            "1"
            if runtime_worker_is_alive(
                db,
                worker_type=QUALITY_EVALUATION_WORKER_TYPE,
                max_age_seconds=worker_max_age_seconds,
            )
            else "0"
        ),
        "# HELP werewolf_quality_evaluation_jobs Current evaluation records by status.",
        "# TYPE werewolf_quality_evaluation_jobs gauge",
    ]
    for status, count in status_counts.items():
        lines.append(f'werewolf_quality_evaluation_jobs{{status="{status}"}} {count}')
    lines.extend(
        [
            "# HELP werewolf_quality_evaluation_backlog Pending evaluation jobs.",
            "# TYPE werewolf_quality_evaluation_backlog gauge",
            f"werewolf_quality_evaluation_backlog {status_counts['pending']}",
            "# HELP werewolf_quality_evaluation_oldest_pending_seconds Oldest pending age.",
            "# TYPE werewolf_quality_evaluation_oldest_pending_seconds gauge",
            f"werewolf_quality_evaluation_oldest_pending_seconds {oldest_age}",
            "# HELP werewolf_quality_evaluation_job_duration_seconds Recent job duration.",
            "# TYPE werewolf_quality_evaluation_job_duration_seconds histogram",
        ]
    )
    for boundary in EVALUATION_DURATION_BUCKETS:
        cumulative = sum(value <= boundary for value in durations)
        lines.append(
            "werewolf_quality_evaluation_job_duration_seconds_bucket"
            f'{{le="{boundary:g}"}} {cumulative}'
        )
    lines.append(
        "werewolf_quality_evaluation_job_duration_seconds_bucket"
        f'{{le="+Inf"}} {len(durations)}'
    )
    lines.append(
        f"werewolf_quality_evaluation_job_duration_seconds_sum {sum(durations)}"
    )
    lines.append(
        f"werewolf_quality_evaluation_job_duration_seconds_count {len(durations)}"
    )
    aggregates = _quality_aggregates(summaries)
    lines.extend(
        [
            "# HELP werewolf_quality_issues Recent safe issues by severity.",
            "# TYPE werewolf_quality_issues gauge",
            *[
                f'werewolf_quality_issues{{severity="{severity}"}} '
                f"{aggregates['issues'][severity]}"
                for severity in ("P0", "P1", "P2")
            ],
            "# HELP werewolf_fact_opportunities Recent critical fact opportunities.",
            "# TYPE werewolf_fact_opportunities gauge",
            "werewolf_fact_opportunities{status=\"expected\"} "
            f"{aggregates['fact_expected']}",
            "werewolf_fact_opportunities{status=\"recorded\"} "
            f"{aggregates['fact_recorded']}",
            "# HELP werewolf_prompt_fact_coverage Recent prompt critical fact coverage.",
            "# TYPE werewolf_prompt_fact_coverage gauge",
            "werewolf_prompt_fact_coverage{result=\"expected\"} "
            f"{aggregates['prompt_expected']}",
            "werewolf_prompt_fact_coverage{result=\"included\"} "
            f"{aggregates['prompt_included']}",
            "werewolf_prompt_fact_coverage{result=\"missing\"} "
            f"{aggregates['prompt_missing']}",
            "# HELP werewolf_fact_contradictions Recent deterministic contradictions.",
            "# TYPE werewolf_fact_contradictions gauge",
            f"werewolf_fact_contradictions {aggregates['contradictions']}",
            "# HELP werewolf_voice_events Recent narratable voice coverage.",
            "# TYPE werewolf_voice_events gauge",
            f"werewolf_voice_events{{status=\"expected\"}} {aggregates['voice_expected']}",
            f"werewolf_voice_events{{status=\"covered\"}} {aggregates['voice_covered']}",
            f"werewolf_voice_events{{status=\"missing\"}} {aggregates['voice_missing']}",
        ]
    )
    lines.append("")
    return "\n".join(lines)


def _count(db: Session, *filters: object) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(GameQualityEvaluationRecord).where(*filters)
        )
        or 0
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _quality_aggregates(summaries: list[object]) -> dict[str, object]:
    result: dict[str, object] = {
        "issues": {"P0": 0, "P1": 0, "P2": 0},
        "fact_expected": 0,
        "fact_recorded": 0,
        "prompt_expected": 0,
        "prompt_included": 0,
        "prompt_missing": 0,
        "contradictions": 0,
        "voice_expected": 0,
        "voice_covered": 0,
        "voice_missing": 0,
    }
    issue_totals = result["issues"]
    assert isinstance(issue_totals, dict)
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        issue_counts = summary.get("issue_counts")
        if isinstance(issue_counts, dict):
            for severity in ("P0", "P1", "P2"):
                issue_totals[severity] += _safe_count(issue_counts.get(severity))
        facts = summary.get("facts")
        if isinstance(facts, dict):
            result["fact_expected"] = int(result["fact_expected"]) + _safe_count(
                facts.get("critical_opportunity_count")
            )
            result["fact_recorded"] = int(result["fact_recorded"]) + _safe_count(
                facts.get("critical_recorded_count")
            )
            result["prompt_expected"] = int(result["prompt_expected"]) + _safe_count(
                facts.get("prompt_expected_critical_count")
            )
            result["prompt_included"] = int(result["prompt_included"]) + _safe_count(
                facts.get("prompt_included_critical_count")
            )
            result["prompt_missing"] = int(result["prompt_missing"]) + _safe_count(
                facts.get("prompt_missing_critical_count")
            )
            result["contradictions"] = int(result["contradictions"]) + _safe_count(
                facts.get("deterministic_contradiction_count")
            )
        voice = summary.get("voice")
        if isinstance(voice, dict):
            result["voice_expected"] = int(result["voice_expected"]) + _safe_count(
                voice.get("narratable_event_count")
            )
            result["voice_covered"] = int(result["voice_covered"]) + _safe_count(
                voice.get("effective_voice_event_count")
            )
            result["voice_missing"] = int(result["voice_missing"]) + _safe_count(
                voice.get("missing_narratable_event_count")
            )
    return result


def _safe_count(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0
