from __future__ import annotations

from collections import Counter
from threading import Lock


_PHASES = frozenset({"day", "night", "summary"})
_SEVERITIES = frozenset({"accepted", "warning", "rewrite", "exhausted"})
_RETRY_RESULTS = frozenset({"not_retried", "passed_after_retry", "exhausted"})
_QUALITY_CODES = frozenset(
    {
        "none",
        "repeated_debate_phrase",
        "low_proposition_novelty",
        "group_agreement_without_evidence",
        "catchphrase_dominates_speech",
        "catchphrase_overuse",
        "mission_not_completed",
        "unknown",
    }
)
_LOCK = Lock()
_QUALITY_COUNTER: Counter[tuple[str, str, str]] = Counter()
_RETRY_COUNTER: Counter[tuple[str, str]] = Counter()
_NOVELTY_SUM: Counter[tuple[str]] = Counter()
_NOVELTY_COUNT: Counter[tuple[str]] = Counter()
_RETRY_DURATION_SUM: Counter[tuple[str, str]] = Counter()
_RETRY_DURATION_COUNT: Counter[tuple[str, str]] = Counter()


def record_speech_quality(
    *,
    phase: str,
    report: dict[str, object],
    attempt_count: int,
    retry_exhausted: bool,
    retry_duration_ms: int = 0,
) -> None:
    phase_label = phase if phase in _PHASES else "other"
    novelty = report.get("novelty_score")
    novelty_score = (
        min(1.0, max(0.0, float(novelty)))
        if type(novelty) in {int, float}
        else 0.0
    )
    raw_issues = report.get("issues")
    issues = raw_issues if isinstance(raw_issues, list) else []
    quality_rows: list[tuple[str, str, str]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        raw_code = str(issue.get("code") or "unknown")
        code = raw_code if raw_code in _QUALITY_CODES else "unknown"
        raw_severity = str(issue.get("severity") or "warning")
        severity = raw_severity if raw_severity in _SEVERITIES else "warning"
        if retry_exhausted and severity == "rewrite":
            severity = "exhausted"
        quality_rows.append((code, severity, phase_label))
    if not quality_rows:
        quality_rows.append(("none", "accepted", phase_label))

    retry_result = (
        "exhausted"
        if retry_exhausted
        else "passed_after_retry"
        if attempt_count > 1
        else "not_retried"
    )
    if retry_result not in _RETRY_RESULTS:
        retry_result = "not_retried"
    with _LOCK:
        _QUALITY_COUNTER.update(quality_rows)
        _RETRY_COUNTER[(retry_result, phase_label)] += 1
        _NOVELTY_SUM[(phase_label,)] += novelty_score
        _NOVELTY_COUNT[(phase_label,)] += 1
        if attempt_count > 1:
            _RETRY_DURATION_SUM[(retry_result, phase_label)] += (
                max(0, retry_duration_ms) / 1000
            )
            _RETRY_DURATION_COUNT[(retry_result, phase_label)] += 1


def render_speech_quality_metrics() -> str:
    with _LOCK:
        quality = _QUALITY_COUNTER.copy()
        retry = _RETRY_COUNTER.copy()
        novelty_sum = _NOVELTY_SUM.copy()
        novelty_count = _NOVELTY_COUNT.copy()
        retry_duration_sum = _RETRY_DURATION_SUM.copy()
        retry_duration_count = _RETRY_DURATION_COUNT.copy()
    lines = [
        "# HELP werewolf_speech_quality_total Final speech quality outcomes.",
        "# TYPE werewolf_speech_quality_total counter",
    ]
    for (code, result, phase), count in sorted(quality.items()):
        lines.append(
            "werewolf_speech_quality_total"
            f'{{code="{code}",result="{result}",phase="{phase}"}} {count}'
        )
    lines.extend(
        [
            "# HELP werewolf_speech_quality_retry_total Final speech retry outcomes.",
            "# TYPE werewolf_speech_quality_retry_total counter",
        ]
    )
    for (result, phase), count in sorted(retry.items()):
        lines.append(
            "werewolf_speech_quality_retry_total"
            f'{{result="{result}",phase="{phase}"}} {count}'
        )
    lines.extend(
        [
            "# HELP werewolf_speech_novelty_score Speech novelty score summary.",
            "# TYPE werewolf_speech_novelty_score summary",
        ]
    )
    phases = sorted({phase for (phase,) in novelty_count})
    for phase in phases:
        lines.append(
            f'werewolf_speech_novelty_score_sum{{phase="{phase}"}} '
            f"{novelty_sum[(phase,)]}"
        )
        lines.append(
            f'werewolf_speech_novelty_score_count{{phase="{phase}"}} '
            f"{novelty_count[(phase,)]}"
        )
    lines.extend(
        [
            "# HELP werewolf_speech_quality_retry_extra_duration_seconds "
            "Additional model time spent on one quality rewrite.",
            "# TYPE werewolf_speech_quality_retry_extra_duration_seconds summary",
        ]
    )
    for result, phase in sorted(retry_duration_count):
        labels = f'result="{result}",phase="{phase}"'
        lines.append(
            "werewolf_speech_quality_retry_extra_duration_seconds_sum"
            f"{{{labels}}} {retry_duration_sum[(result, phase)]}"
        )
        lines.append(
            "werewolf_speech_quality_retry_extra_duration_seconds_count"
            f"{{{labels}}} {retry_duration_count[(result, phase)]}"
        )
    lines.append("")
    return "\n".join(lines)


def reset_speech_quality_metrics_for_tests() -> None:
    with _LOCK:
        _QUALITY_COUNTER.clear()
        _RETRY_COUNTER.clear()
        _NOVELTY_SUM.clear()
        _NOVELTY_COUNT.clear()
        _RETRY_DURATION_SUM.clear()
        _RETRY_DURATION_COUNT.clear()
