from __future__ import annotations

from collections import Counter, OrderedDict
from threading import Lock

from app.werewolf.execution_budget import ActionBudgetKind


_ACTION_KINDS = frozenset(
    {"required_discrete", "optional_discrete", "public_speech", "private_text"}
)
_RESULTS = frozenset({"completed", "fallback", "canceled", "failed"})
_ATTEMPT_RESULTS = frozenset(
    {
        "valid_response",
        "invalid_response",
        "timed_out",
        "canceled",
        "transport_failed",
    }
)
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
    {
        "started",
        "thinking",
        "delta",
        "attempt_completed",
        "received",
        "retry",
        "failed",
    }
)
ACTION_DURATION_BUCKETS = (0.5, 1, 2, 3, 5, 8, 10, 12, 15, 20, 30, 45, 60)
FIRST_TOKEN_BUCKETS = (0.25, 0.5, 1, 2, 3, 5, 8, 10, 15, 20)
BATCH_DURATION_BUCKETS = ACTION_DURATION_BUCKETS
_LOCK = Lock()
_ACTION_DURATION_SUM: Counter[tuple[str, str, str]] = Counter()
_ACTION_DURATION_COUNT: Counter[tuple[str, str, str]] = Counter()
_ACTION_DURATION_BUCKET: Counter[tuple[str, str, str, float]] = Counter()
_ACTION_RESULT_COUNTER: Counter[tuple[str, str, str]] = Counter()
_FIRST_TOKEN_SUM: Counter[tuple[str, str, str]] = Counter()
_FIRST_TOKEN_COUNT: Counter[tuple[str, str, str]] = Counter()
_FIRST_TOKEN_BUCKET: Counter[tuple[str, str, str, float]] = Counter()
_TIMEOUT_COUNTER: Counter[tuple[str, str]] = Counter()
_FALLBACK_COUNTER: Counter[tuple[str, str]] = Counter()
_BATCH_DURATION_SUM: Counter[tuple[str, str]] = Counter()
_BATCH_DURATION_COUNT: Counter[tuple[str, str]] = Counter()
_BATCH_DURATION_BUCKET: Counter[tuple[str, str, float]] = Counter()
_PROGRESS_COUNTER: Counter[tuple[str]] = Counter()
_ATTEMPT_RESULT_COUNTER: Counter[tuple[str]] = Counter()
MAX_FINALIZED_ACTION_IDS = 65_536
_FINALIZED_ACTION_IDS: OrderedDict[str, None] = OrderedDict()


def record_action_execution(
    *,
    action_kind: ActionBudgetKind,
    model: str,
    result: str,
    duration_ms: int,
    first_token_ms: int | None,
    fallback_reason: str | None,
    action_id: str | None = None,
) -> None:
    kind = action_kind if action_kind in _ACTION_KINDS else "required_discrete"
    provider = _provider_label(model)
    result_label = result if result in _RESULTS else "failed"
    duration_seconds = max(0, duration_ms) / 1000
    with _LOCK:
        if action_id is not None:
            if action_id in _FINALIZED_ACTION_IDS:
                return
            _FINALIZED_ACTION_IDS[action_id] = None
            while len(_FINALIZED_ACTION_IDS) > MAX_FINALIZED_ACTION_IDS:
                _FINALIZED_ACTION_IDS.popitem(last=False)
        key = (kind, provider, result_label)
        _ACTION_DURATION_SUM[key] += duration_seconds
        _ACTION_DURATION_COUNT[key] += 1
        _ACTION_RESULT_COUNTER[key] += 1
        for boundary in ACTION_DURATION_BUCKETS:
            if duration_seconds <= boundary:
                _ACTION_DURATION_BUCKET[(*key, boundary)] += 1
        if first_token_ms is not None:
            first_token_seconds = max(0, first_token_ms) / 1000
            _FIRST_TOKEN_SUM[key] += first_token_seconds
            _FIRST_TOKEN_COUNT[key] += 1
            for boundary in FIRST_TOKEN_BUCKETS:
                if first_token_seconds <= boundary:
                    _FIRST_TOKEN_BUCKET[(*key, boundary)] += 1
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
        duration_seconds = max(0, duration_ms) / 1000
        _BATCH_DURATION_SUM[key] += duration_seconds
        _BATCH_DURATION_COUNT[key] += 1
        for boundary in BATCH_DURATION_BUCKETS:
            if duration_seconds <= boundary:
                _BATCH_DURATION_BUCKET[(*key, boundary)] += 1


def record_model_progress_event(
    event_type: str,
    *,
    attempt_result: str | None = None,
) -> None:
    stage_by_event = {
        "model_request_started": "started",
        "model_thinking_tick": "thinking",
        "model_response_delta": "delta",
        "model_attempt_completed": "attempt_completed",
        "model_response_received": "received",
        "model_retry_scheduled": "retry",
        "model_request_failed": "failed",
    }
    stage = stage_by_event.get(event_type)
    result = attempt_result if attempt_result in _ATTEMPT_RESULTS else None
    if stage not in _PROGRESS_STAGES and result is None:
        return
    with _LOCK:
        if stage in _PROGRESS_STAGES:
            _PROGRESS_COUNTER[(stage,)] += 1
        if result is not None:
            _ATTEMPT_RESULT_COUNTER[(result,)] += 1


def render_action_execution_metrics() -> str:
    with _LOCK:
        action_sum = _ACTION_DURATION_SUM.copy()
        action_count = _ACTION_DURATION_COUNT.copy()
        action_bucket = _ACTION_DURATION_BUCKET.copy()
        action_results = _ACTION_RESULT_COUNTER.copy()
        first_sum = _FIRST_TOKEN_SUM.copy()
        first_count = _FIRST_TOKEN_COUNT.copy()
        first_bucket = _FIRST_TOKEN_BUCKET.copy()
        timeouts = _TIMEOUT_COUNTER.copy()
        fallbacks = _FALLBACK_COUNTER.copy()
        batch_sum = _BATCH_DURATION_SUM.copy()
        batch_count = _BATCH_DURATION_COUNT.copy()
        batch_bucket = _BATCH_DURATION_BUCKET.copy()
        progress = _PROGRESS_COUNTER.copy()
        attempt_results = _ATTEMPT_RESULT_COUNTER.copy()
    lines = [
        "# HELP werewolf_model_action_duration_seconds Model action duration.",
        "# TYPE werewolf_model_action_duration_seconds histogram",
    ]
    _append_action_histogram(
        lines,
        "werewolf_model_action_duration_seconds",
        action_sum,
        action_count,
        action_bucket,
        ACTION_DURATION_BUCKETS,
    )
    lines.extend(
        [
            "# HELP werewolf_logical_action_total Terminal logical action results.",
            "# TYPE werewolf_logical_action_total counter",
        ]
    )
    for (kind, provider, result), count in sorted(action_results.items()):
        lines.append(
            "werewolf_logical_action_total"
            f'{{action_kind="{kind}",provider="{provider}",result="{result}"}} {count}'
        )
    lines.extend(
        [
            "# HELP werewolf_model_first_token_seconds Model first token latency.",
            "# TYPE werewolf_model_first_token_seconds histogram",
        ]
    )
    _append_action_histogram(
        lines,
        "werewolf_model_first_token_seconds",
        first_sum,
        first_count,
        first_bucket,
        FIRST_TOKEN_BUCKETS,
    )
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
            "# TYPE werewolf_action_batch_duration_seconds histogram",
        ]
    )
    for key in sorted(batch_count):
        kind, result = key
        labels = f'action_kind="{kind}",result="{result}"'
        for boundary in BATCH_DURATION_BUCKETS:
            count = batch_bucket[(kind, result, boundary)]
            lines.append(
                "werewolf_action_batch_duration_seconds_bucket"
                f'{{{labels},le="{boundary:g}"}} {count}'
            )
        lines.append(
            "werewolf_action_batch_duration_seconds_bucket"
            f'{{{labels},le="+Inf"}} {batch_count[key]}'
        )
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
    lines.extend(
        [
            "# HELP werewolf_model_attempt_total Terminal provider attempt results.",
            "# TYPE werewolf_model_attempt_total counter",
        ]
    )
    for (result,), count in sorted(attempt_results.items()):
        lines.append(f'werewolf_model_attempt_total{{result="{result}"}} {count}')
    lines.append("")
    return "\n".join(lines)


def reset_action_execution_metrics_for_tests() -> None:
    with _LOCK:
        _ACTION_DURATION_SUM.clear()
        _ACTION_DURATION_COUNT.clear()
        _ACTION_DURATION_BUCKET.clear()
        _ACTION_RESULT_COUNTER.clear()
        _FIRST_TOKEN_SUM.clear()
        _FIRST_TOKEN_COUNT.clear()
        _FIRST_TOKEN_BUCKET.clear()
        _TIMEOUT_COUNTER.clear()
        _FALLBACK_COUNTER.clear()
        _BATCH_DURATION_SUM.clear()
        _BATCH_DURATION_COUNT.clear()
        _BATCH_DURATION_BUCKET.clear()
        _PROGRESS_COUNTER.clear()
        _ATTEMPT_RESULT_COUNTER.clear()
        _FINALIZED_ACTION_IDS.clear()


def _provider_label(model: str) -> str:
    normalized = model.lower()
    if normalized.startswith("deepseek-"):
        return "deepseek"
    if normalized.startswith("qwen"):
        return "qwen"
    if normalized.startswith(("doubao-", "glm-", "kimi-", "minimax-")):
        return "ark_agent_plan"
    return "other"


def _append_action_histogram(
    lines: list[str],
    metric: str,
    sums: Counter[tuple[str, str, str]],
    counts: Counter[tuple[str, str, str]],
    buckets: Counter[tuple[str, str, str, float]],
    boundaries: tuple[float, ...],
) -> None:
    for key in sorted(counts):
        kind, provider, result = key
        labels = (
            f'action_kind="{kind}",provider="{provider}",result="{result}"'
        )
        for boundary in boundaries:
            lines.append(
                f"{metric}_bucket"
                f'{{{labels},le="{boundary:g}"}} {buckets[(*key, boundary)]}'
            )
        lines.append(f'{metric}_bucket{{{labels},le="+Inf"}} {counts[key]}')
        lines.append(f"{metric}_sum{{{labels}}} {sums[key]}")
        lines.append(f"{metric}_count{{{labels}}} {counts[key]}")
