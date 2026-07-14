from __future__ import annotations

from collections import Counter
from threading import Lock

from app.werewolf.execution_budget import ActionBudgetKind


_ACTION_KINDS = frozenset(
    {"required_discrete", "optional_discrete", "public_speech", "private_text"}
)
_RESULTS = frozenset({"completed", "timed_out", "fallback", "failed"})
_BATCH_RESULTS = frozenset({"completed", "deadline", "failed"})
_FALLBACK_REASONS = frozenset(
    {
        "timeout_neutral_public_speech",
        "timeout_optional_abstain",
        "timeout_deterministic_legal_choice",
        "timeout_empty_private_text",
        "batch_deadline_optional_abstain",
        "batch_deadline_deterministic_legal_choice",
        "batch_deadline_empty_private_text",
        "no_legal_choice",
        "other",
    }
)
_PROGRESS_STAGES = frozenset(
    {"started", "thinking", "delta", "received", "retry", "failed"}
)
_LOCK = Lock()
_ACTION_DURATION_SUM: Counter[tuple[str, str, str]] = Counter()
_ACTION_DURATION_COUNT: Counter[tuple[str, str, str]] = Counter()
_FIRST_TOKEN_SUM: Counter[tuple[str, str, str]] = Counter()
_FIRST_TOKEN_COUNT: Counter[tuple[str, str, str]] = Counter()
_TIMEOUT_COUNTER: Counter[tuple[str, str]] = Counter()
_FALLBACK_COUNTER: Counter[tuple[str, str]] = Counter()
_BATCH_DURATION_SUM: Counter[tuple[str, str]] = Counter()
_BATCH_DURATION_COUNT: Counter[tuple[str, str]] = Counter()
_PROGRESS_COUNTER: Counter[tuple[str]] = Counter()


def record_action_execution(
    *,
    action_kind: ActionBudgetKind,
    model: str,
    result: str,
    duration_ms: int,
    first_token_ms: int | None,
    fallback_reason: str | None,
) -> None:
    kind = action_kind if action_kind in _ACTION_KINDS else "required_discrete"
    provider = _provider_label(model)
    result_label = result if result in _RESULTS else "failed"
    duration_seconds = max(0, duration_ms) / 1000
    with _LOCK:
        key = (kind, provider, result_label)
        _ACTION_DURATION_SUM[key] += duration_seconds
        _ACTION_DURATION_COUNT[key] += 1
        if first_token_ms is not None:
            _FIRST_TOKEN_SUM[key] += max(0, first_token_ms) / 1000
            _FIRST_TOKEN_COUNT[key] += 1
        if fallback_reason and (
            fallback_reason.startswith("timeout_")
            or fallback_reason.startswith("batch_deadline_")
        ):
            _TIMEOUT_COUNTER[(kind, provider)] += 1
        if fallback_reason:
            reason = (
                fallback_reason
                if fallback_reason in _FALLBACK_REASONS
                else "other"
            )
            _FALLBACK_COUNTER[(kind, reason)] += 1


def record_action_batch(
    *,
    action_kind: ActionBudgetKind,
    result: str,
    duration_ms: int,
) -> None:
    kind = action_kind if action_kind in _ACTION_KINDS else "required_discrete"
    result_label = result if result in _BATCH_RESULTS else "failed"
    key = (kind, result_label)
    with _LOCK:
        _BATCH_DURATION_SUM[key] += max(0, duration_ms) / 1000
        _BATCH_DURATION_COUNT[key] += 1


def record_model_progress_event(event_type: str) -> None:
    stage_by_event = {
        "model_request_started": "started",
        "model_thinking_tick": "thinking",
        "model_response_delta": "delta",
        "model_response_received": "received",
        "model_retry_scheduled": "retry",
        "model_request_failed": "failed",
    }
    stage = stage_by_event.get(event_type)
    if stage not in _PROGRESS_STAGES:
        return
    with _LOCK:
        _PROGRESS_COUNTER[(stage,)] += 1


def render_action_execution_metrics() -> str:
    with _LOCK:
        action_sum = _ACTION_DURATION_SUM.copy()
        action_count = _ACTION_DURATION_COUNT.copy()
        first_sum = _FIRST_TOKEN_SUM.copy()
        first_count = _FIRST_TOKEN_COUNT.copy()
        timeouts = _TIMEOUT_COUNTER.copy()
        fallbacks = _FALLBACK_COUNTER.copy()
        batch_sum = _BATCH_DURATION_SUM.copy()
        batch_count = _BATCH_DURATION_COUNT.copy()
        progress = _PROGRESS_COUNTER.copy()
    lines = [
        "# HELP werewolf_model_action_duration_seconds Model action duration.",
        "# TYPE werewolf_model_action_duration_seconds summary",
    ]
    _append_summary(lines, "werewolf_model_action_duration_seconds", action_sum, action_count)
    lines.extend(
        [
            "# HELP werewolf_model_first_token_seconds Model first token latency.",
            "# TYPE werewolf_model_first_token_seconds summary",
        ]
    )
    _append_summary(lines, "werewolf_model_first_token_seconds", first_sum, first_count)
    lines.extend(
        [
            "# HELP werewolf_model_timeout_total Model action timeouts.",
            "# TYPE werewolf_model_timeout_total counter",
        ]
    )
    for (kind, provider), count in sorted(timeouts.items()):
        lines.append(
            "werewolf_model_timeout_total"
            f'{{action_kind="{kind}",provider="{provider}"}} {count}'
        )
    lines.extend(
        [
            "# HELP werewolf_action_fallback_total Action fallbacks.",
            "# TYPE werewolf_action_fallback_total counter",
        ]
    )
    for (kind, reason), count in sorted(fallbacks.items()):
        lines.append(
            "werewolf_action_fallback_total"
            f'{{action_kind="{kind}",reason="{reason}"}} {count}'
        )
    lines.extend(
        [
            "# HELP werewolf_action_batch_duration_seconds Action batch duration.",
            "# TYPE werewolf_action_batch_duration_seconds summary",
        ]
    )
    for key in sorted(batch_count):
        kind, result = key
        labels = f'action_kind="{kind}",result="{result}"'
        lines.append(
            f"werewolf_action_batch_duration_seconds_sum{{{labels}}} {batch_sum[key]}"
        )
        lines.append(
            "werewolf_action_batch_duration_seconds_count"
            f"{{{labels}}} {batch_count[key]}"
        )
    lines.extend(
        [
            "# HELP werewolf_model_progress_event_total Model progress events.",
            "# TYPE werewolf_model_progress_event_total counter",
        ]
    )
    for (stage,), count in sorted(progress.items()):
        lines.append(
            f'werewolf_model_progress_event_total{{stage="{stage}"}} {count}'
        )
    lines.append("")
    return "\n".join(lines)


def reset_action_execution_metrics_for_tests() -> None:
    with _LOCK:
        _ACTION_DURATION_SUM.clear()
        _ACTION_DURATION_COUNT.clear()
        _FIRST_TOKEN_SUM.clear()
        _FIRST_TOKEN_COUNT.clear()
        _TIMEOUT_COUNTER.clear()
        _FALLBACK_COUNTER.clear()
        _BATCH_DURATION_SUM.clear()
        _BATCH_DURATION_COUNT.clear()
        _PROGRESS_COUNTER.clear()


def _provider_label(model: str) -> str:
    normalized = model.lower()
    if normalized.startswith("deepseek-"):
        return "deepseek"
    if normalized.startswith("qwen"):
        return "qwen"
    if normalized.startswith(("doubao-", "glm-", "kimi-", "minimax-")):
        return "ark_agent_plan"
    return "other"


def _append_summary(
    lines: list[str],
    metric: str,
    sums: Counter[tuple[str, str, str]],
    counts: Counter[tuple[str, str, str]],
) -> None:
    for key in sorted(counts):
        kind, provider, result = key
        labels = (
            f'action_kind="{kind}",provider="{provider}",result="{result}"'
        )
        lines.append(f"{metric}_sum{{{labels}}} {sums[key]}")
        lines.append(f"{metric}_count{{{labels}}} {counts[key]}")
