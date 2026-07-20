from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Mapping


_ACTIONS = frozenset(
    {
        "debate",
        "sheriff_speech",
        "sheriff_pk_speech",
        "exile_pk_speech",
        "exile_last_words",
    }
)
_RESULTS = frozenset({"complete", "partial", "interrupted", "failed"})
_STAGE_PAIRS = {
    "turn_to_actor_brain": ("turn_ready_at", "actor_brain_started_at"),
    "actor_brain_to_plan": ("actor_brain_started_at", "turn_plan_ready_at"),
    "plan_to_renderer": ("turn_plan_ready_at", "renderer_started_at"),
    "renderer_to_first_delta": ("renderer_started_at", "first_model_delta_at"),
    "first_delta_to_clause": ("first_model_delta_at", "first_clause_committed_at"),
}
_LOCK = Lock()
_SPEECH_TOTAL: Counter[tuple[str, str, str]] = Counter()
_STAGE_SUM_MS: Counter[tuple[str, str, str]] = Counter()
_STAGE_COUNT: Counter[tuple[str, str, str]] = Counter()
_HARD_GATE_SUM_MS: Counter[tuple[str, str]] = Counter()
_HARD_GATE_COUNT: Counter[tuple[str, str]] = Counter()
_HARD_REJECTION_TOTAL: Counter[tuple[str, str]] = Counter()


def record_liveness_speech(
    *,
    action: str,
    experience_revision: str,
    result: str,
    timing: Mapping[str, object],
    hard_rejected_count: int,
) -> None:
    action_label = action if action in _ACTIONS else "other"
    mode = "legacy" if experience_revision == "legacy-v0" else "v1"
    result_label = result if result in _RESULTS else "failed"
    stage_values: list[tuple[tuple[str, str, str], int]] = []
    for stage, (started_field, finished_field) in _STAGE_PAIRS.items():
        started = timing.get(started_field)
        finished = timing.get(finished_field)
        if type(started) is int and type(finished) is int and finished >= started:
            stage_values.append(((stage, action_label, mode), finished - started))
    gate_ms = timing.get("hard_gate_duration_ms")
    with _LOCK:
        _SPEECH_TOTAL[(action_label, mode, result_label)] += 1
        for key, value in stage_values:
            _STAGE_SUM_MS[key] += value
            _STAGE_COUNT[key] += 1
        if type(gate_ms) is int and gate_ms >= 0:
            _HARD_GATE_SUM_MS[(action_label, mode)] += gate_ms
            _HARD_GATE_COUNT[(action_label, mode)] += 1
        _HARD_REJECTION_TOTAL[(action_label, mode)] += max(0, hard_rejected_count)


def render_liveness_metrics() -> str:
    with _LOCK:
        speech_total = _SPEECH_TOTAL.copy()
        stage_sum = _STAGE_SUM_MS.copy()
        stage_count = _STAGE_COUNT.copy()
        gate_sum = _HARD_GATE_SUM_MS.copy()
        gate_count = _HARD_GATE_COUNT.copy()
        hard_rejections = _HARD_REJECTION_TOTAL.copy()
    lines = [
        "# HELP werewolf_liveness_public_speech_total Public speech terminal outcomes.",
        "# TYPE werewolf_liveness_public_speech_total counter",
    ]
    for (action, mode, result), count in sorted(speech_total.items()):
        lines.append(
            "werewolf_liveness_public_speech_total"
            f'{{action="{action}",mode="{mode}",result="{result}"}} {count}'
        )
    lines.extend(
        [
            "# HELP werewolf_liveness_stage_latency_milliseconds Liveness stage latency.",
            "# TYPE werewolf_liveness_stage_latency_milliseconds summary",
        ]
    )
    for stage, action, mode in sorted(stage_count):
        labels = f'stage="{stage}",action="{action}",mode="{mode}"'
        lines.append(
            "werewolf_liveness_stage_latency_milliseconds_sum"
            f"{{{labels}}} {stage_sum[(stage, action, mode)]}"
        )
        lines.append(
            "werewolf_liveness_stage_latency_milliseconds_count"
            f"{{{labels}}} {stage_count[(stage, action, mode)]}"
        )
    lines.extend(
        [
            "# HELP werewolf_liveness_hard_gate_milliseconds Hard speech gate runtime.",
            "# TYPE werewolf_liveness_hard_gate_milliseconds summary",
        ]
    )
    for action, mode in sorted(gate_count):
        labels = f'action="{action}",mode="{mode}"'
        lines.append(
            "werewolf_liveness_hard_gate_milliseconds_sum"
            f"{{{labels}}} {gate_sum[(action, mode)]}"
        )
        lines.append(
            "werewolf_liveness_hard_gate_milliseconds_count"
            f"{{{labels}}} {gate_count[(action, mode)]}"
        )
    lines.extend(
        [
            "# HELP werewolf_liveness_hard_rejection_total Hard-gate rejected clauses.",
            "# TYPE werewolf_liveness_hard_rejection_total counter",
        ]
    )
    for (action, mode), count in sorted(hard_rejections.items()):
        lines.append(
            "werewolf_liveness_hard_rejection_total"
            f'{{action="{action}",mode="{mode}"}} {count}'
        )
    lines.append("")
    return "\n".join(lines)


def reset_liveness_metrics_for_tests() -> None:
    with _LOCK:
        _SPEECH_TOTAL.clear()
        _STAGE_SUM_MS.clear()
        _STAGE_COUNT.clear()
        _HARD_GATE_SUM_MS.clear()
        _HARD_GATE_COUNT.clear()
        _HARD_REJECTION_TOTAL.clear()
