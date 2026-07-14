from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

_PUBLIC_SPEECH_ACTIONS = {"debate", "sheriff_speech", "sheriff_pk_speech"}
_PRIVATE_TEXT_ACTIONS = {"werewolf_discuss", "summarize"}
_OUTCOME_KINDS = {
    "night_death",
    "hunter_shot",
    "self_explosion",
    "exile",
    "idiot_reveal",
    "badge_transferred",
    "badge_lost",
}
_LINEUP_VIOLATION_CODES = {
    "lineup_incomplete",
    "personality_overrepresented",
    "strategy_profile_overrepresented",
    "catchphrase_overrepresented",
    "avatar_overrepresented",
    "tag_overrepresented",
    "insufficient_style_buckets",
}
_PUBLIC_OUTCOME_VALUES = {
    "eliminated",
    "self_exploded",
    "elected",
    "survived",
    "transferred",
    "destroyed",
    "lost_no_target",
    "badge_lost",
    "no_candidates",
    "all_candidates_withdrew",
    "no_off_sheriff_voters",
    "first_vote_empty",
    "runoff_tied",
    "double_pre_election_self_explosion",
}
_PUBLIC_OUTCOME_PHASES = {"night", "day", "vote", "unknown"}
_OUTCOME_EVENT_ID = re.compile(r"^(?:outcome_[0-9a-f]{16}|legacy:r\d+:\d+)$")


def build_run_p2_diagnostics(
    *,
    logs: list[Any],
    status: str,
    diagnostic_events: list[dict[str, Any]],
    started_at: datetime | None,
    completed_at: datetime | None,
    safe_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if safe_diagnostics:
        return _stored_run_diagnostics(
            safe_diagnostics,
            status=status,
            diagnostic_events=diagnostic_events,
            started_at=started_at,
            completed_at=completed_at,
        )
    actions = list(_action_logs(logs))
    performance = _performance(
        actions,
        diagnostic_events=diagnostic_events,
        started_at=started_at,
        completed_at=completed_at,
    )
    has_p2_data = _has_p2_action_data(actions)
    return {
        "schema_version": 1,
        "data_status": _data_status(
            status=status,
            has_payload=bool(logs),
            has_p2_data=has_p2_data,
        ),
        "performance": performance,
        "speech_quality": _speech_quality(actions),
        "choice_normalization": _choice_normalization(actions),
    }


def build_game_p2_quality(
    *,
    state: dict[str, Any],
    logs: list[Any],
    lineup_quality_report: dict[str, Any],
    status: str,
    terminal: bool,
    diagnostic_events: list[dict[str, Any]],
    started_at: datetime | None,
    completed_at: datetime | None,
    safe_run_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actions = list(_action_logs(logs))
    lineup = _safe_lineup_quality(lineup_quality_report)
    outcomes, summary_mismatches = _public_outcomes(state)
    stored_run = (
        _stored_run_diagnostics(
            safe_run_diagnostics,
            status="completed" if terminal else status,
            diagnostic_events=diagnostic_events,
            started_at=started_at,
            completed_at=completed_at,
        )
        if safe_run_diagnostics
        else None
    )
    has_p2_data = bool(
        stored_run
        or _has_p2_action_data(actions)
        or lineup_quality_report.get("schema_version") == 1
        or outcomes
    )
    data_status = _data_status(
        status="completed" if terminal else status,
        has_payload=bool(state or logs),
        has_p2_data=has_p2_data,
    )
    performance = (
        stored_run["performance"]
        if stored_run
        else _performance(
            actions,
            diagnostic_events=diagnostic_events,
            started_at=started_at,
            completed_at=completed_at,
        )
    )
    speech = stored_run["speech_quality"] if stored_run else _speech_quality(actions)
    choice = (
        stored_run["choice_normalization"]
        if stored_run
        else _choice_normalization(actions)
    )
    return {
        "schema_version": 1,
        "data_status": data_status,
        "lineup_quality": lineup,
        "speech_quality": speech,
        "performance": performance,
        "choice_normalization": choice,
        "public_outcomes": outcomes if terminal else [],
        "public_outcome_summary_mismatch_count": (
            summary_mismatches if terminal else 0
        ),
        "quality_gates": _quality_gates(
            data_status=data_status,
            lineup=lineup,
            speech=speech,
            performance=performance,
            choice=choice,
            outcome_count=len(outcomes) if terminal else 0,
            summary_mismatches=summary_mismatches if terminal else 0,
        ),
    }


def _stored_run_diagnostics(
    value: dict[str, Any],
    *,
    status: str,
    diagnostic_events: list[dict[str, Any]],
    started_at: datetime | None,
    completed_at: datetime | None,
) -> dict[str, Any]:
    raw_performance = value.get("performance")
    raw_speech = value.get("speech_quality")
    raw_choice = value.get("choice_normalization")
    performance_data = raw_performance if isinstance(raw_performance, dict) else {}
    speech_data = raw_speech if isinstance(raw_speech, dict) else {}
    choice_data = raw_choice if isinstance(raw_choice, dict) else {}
    request_count, active_request_count = _request_counts(diagnostic_events)
    duration_ms = None
    if started_at is not None and completed_at is not None:
        duration_ms = max(0, round((completed_at - started_at).total_seconds() * 1000))
    performance = {
        "request_count": request_count
        or _non_negative_int(performance_data.get("request_count"), default=0),
        "discrete_action_sample_count": _non_negative_int(
            performance_data.get("discrete_action_sample_count"), default=0
        ),
        "discrete_action_p50_ms": _non_negative_int(
            performance_data.get("discrete_action_p50_ms")
        ),
        "discrete_action_p95_ms": _non_negative_int(
            performance_data.get("discrete_action_p95_ms")
        ),
        "discrete_action_max_ms": _non_negative_int(
            performance_data.get("discrete_action_max_ms")
        ),
        "speech_first_token_sample_count": _non_negative_int(
            performance_data.get("speech_first_token_sample_count"), default=0
        ),
        "speech_first_token_p95_ms": _non_negative_int(
            performance_data.get("speech_first_token_p95_ms")
        ),
        "speech_first_token_max_ms": _non_negative_int(
            performance_data.get("speech_first_token_max_ms")
        ),
        "timeout_count": _non_negative_int(
            performance_data.get("timeout_count"), default=0
        ),
        "fallback_count": _non_negative_int(
            performance_data.get("fallback_count"), default=0
        ),
        "active_request_count": active_request_count,
        "game_duration_ms": duration_ms,
    }
    speech = {
        key: _non_negative_int(speech_data.get(key), default=0)
        for key in {
            "checked_count",
            "retry_count",
            "exhausted_count",
            "low_novelty_window_count",
        }
    }
    choice = {
        key: _non_negative_int(choice_data.get(key), default=0)
        for key in {
            "exact_count",
            "seat_alias_count",
            "public_label_count",
            "invalid_count",
            "other_count",
        }
    }
    return {
        "schema_version": 1,
        "data_status": _data_status(
            status=status,
            has_payload=True,
            has_p2_data=value.get("schema_version") == 1,
        ),
        "performance": performance,
        "speech_quality": speech,
        "choice_normalization": choice,
    }


def _action_logs(logs: list[Any]) -> Iterable[dict[str, Any]]:
    stack = list(reversed(logs))
    while stack:
        value = stack.pop()
        if isinstance(value, list):
            stack.extend(reversed(value))
            continue
        if not isinstance(value, dict):
            continue
        if isinstance(value.get("action"), str) and isinstance(
            value.get("lm_log"), dict
        ):
            yield value
            continue
        stack.extend(reversed(list(value.values())))


def _performance(
    actions: list[dict[str, Any]],
    *,
    diagnostic_events: list[dict[str, Any]],
    started_at: datetime | None,
    completed_at: datetime | None,
) -> dict[str, Any]:
    discrete_durations = sorted(
        _non_negative_int(action.get("duration_ms"))
        for action in actions
        if str(action.get("action"))
        not in _PUBLIC_SPEECH_ACTIONS | _PRIVATE_TEXT_ACTIONS
        and _non_negative_int(action.get("duration_ms")) is not None
    )
    discrete_durations = [value for value in discrete_durations if value is not None]
    first_tokens = sorted(
        value
        for action in actions
        if str(action.get("action")) in _PUBLIC_SPEECH_ACTIONS
        and (value := _non_negative_int(action.get("first_token_ms"))) is not None
    )
    request_count, active_request_count = _request_counts(diagnostic_events)
    timeout_count = sum(
        1
        for action in actions
        if str(action.get("fallback_reason") or "").startswith(
            ("timeout_", "batch_deadline_")
        )
    )
    fallback_count = sum(1 for action in actions if action.get("fallback_reason"))
    duration_ms = None
    if started_at is not None and completed_at is not None:
        duration_ms = max(0, round((completed_at - started_at).total_seconds() * 1000))
    return {
        "request_count": request_count or len(actions),
        "discrete_action_sample_count": len(discrete_durations),
        "discrete_action_p50_ms": _percentile(discrete_durations, 0.5),
        "discrete_action_p95_ms": (
            _percentile(discrete_durations, 0.95)
            if len(discrete_durations) >= 20
            else None
        ),
        "discrete_action_max_ms": max(discrete_durations, default=None),
        "speech_first_token_sample_count": len(first_tokens),
        "speech_first_token_p95_ms": (
            _percentile(first_tokens, 0.95) if len(first_tokens) >= 20 else None
        ),
        "speech_first_token_max_ms": max(first_tokens, default=None),
        "timeout_count": timeout_count,
        "fallback_count": fallback_count,
        "active_request_count": active_request_count,
        "game_duration_ms": duration_ms,
    }


def _request_counts(events: list[dict[str, Any]]) -> tuple[int, int]:
    active: set[str] = set()
    request_count = 0
    anonymous_completed = 0
    for event in events:
        event_type = str(event.get("type") or "")
        payload = event.get("payload")
        request_id = (
            str(payload.get("request_id"))
            if isinstance(payload, dict) and payload.get("request_id")
            else None
        )
        if event_type == "model_request_started":
            request_count += 1
            if request_id:
                active.add(request_id)
        elif event_type in {
            "model_request_failed",
            "model_response_received",
        }:
            if request_id:
                active.discard(request_id)
            else:
                anonymous_completed += 1
    anonymous_active = max(0, request_count - anonymous_completed - len(active))
    return request_count, len(active) + anonymous_active


def _speech_quality(actions: list[dict[str, Any]]) -> dict[str, int]:
    speech_actions = [
        action
        for action in actions
        if isinstance(action.get("speech_quality_report"), dict)
    ]
    return {
        "checked_count": len(speech_actions),
        "retry_count": sum(
            1
            for action in speech_actions
            if _non_negative_int(action.get("speech_quality_attempt_count"), default=0)
            > 1
        ),
        "exhausted_count": sum(
            1
            for action in speech_actions
            if action.get("speech_quality_retry_exhausted") is True
        ),
        "low_novelty_window_count": sum(
            1
            for action in speech_actions
            if _report_has_issue(action.get("speech_quality_report"), "low_proposition_novelty")
        ),
    }


def _choice_normalization(actions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "exact_count": 0,
        "seat_alias_count": 0,
        "public_label_count": 0,
        "invalid_count": 0,
        "other_count": 0,
    }
    for action in actions:
        if action.get("invalid_value") is not None:
            counts["invalid_count"] += 1
            continue
        kind = action.get("choice_normalization_kind")
        if kind is None:
            counts["exact_count"] += 1
        elif kind == "seat_alias":
            counts["seat_alias_count"] += 1
        elif kind == "public_label":
            counts["public_label_count"] += 1
        else:
            counts["other_count"] += 1
    return counts


def _safe_lineup_quality(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != 1:
        return {
            "policy_mode": None,
            "was_repaired": None,
            "is_blocked": None,
            "style_bucket_count": None,
            "required_style_bucket_count": None,
            "violations": [],
        }
    mode = report.get("policy_mode")
    violations = []
    raw_violations = report.get("violations")
    if isinstance(raw_violations, list):
        for violation in raw_violations[:20]:
            if not isinstance(violation, dict):
                continue
            severity = violation.get("severity")
            violations.append(
                {
                    "code": _bounded_code(violation.get("code")),
                    "severity": severity if severity in {"warning", "error"} else "warning",
                    "count": _non_negative_int(violation.get("count"), default=0),
                    "limit": _non_negative_int(violation.get("limit"), default=0),
                    "seat_numbers": [
                        seat
                        for value in (
                            violation.get("seat_numbers")
                            if isinstance(violation.get("seat_numbers"), list)
                            else []
                        )[:24]
                        if (seat := _positive_int(value)) is not None
                    ],
                }
            )
    return {
        "policy_mode": mode if mode in {"observe", "repair", "enforce"} else None,
        "was_repaired": bool(report.get("was_repaired")),
        "is_blocked": bool(report.get("is_blocked")),
        "style_bucket_count": _non_negative_int(report.get("style_bucket_count")),
        "required_style_bucket_count": _non_negative_int(
            report.get("required_style_bucket_count")
        ),
        "violations": violations,
    }


def _public_outcomes(state: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    from app.werewolf.public_outcomes import (  # noqa: PLC0415
        public_outcome_event_from_dict,
        render_public_round_summary,
    )

    rounds = state.get("rounds")
    if not isinstance(rounds, list):
        return [], 0
    public_player_ids = _public_player_ids(state, rounds)
    rows: list[dict[str, Any]] = []
    mismatches = 0
    for round_data in rounds[:100]:
        if not isinstance(round_data, dict):
            continue
        round_number = _non_negative_int(round_data.get("number"), default=0)
        raw_events = round_data.get("public_outcome_events")
        if not isinstance(raw_events, list):
            continue
        parsed = []
        for raw_event in raw_events[:100]:
            if not isinstance(raw_event, dict) or raw_event.get("kind") not in _OUTCOME_KINDS:
                continue
            event = public_outcome_event_from_dict(raw_event)
            if not _OUTCOME_EVENT_ID.fullmatch(event.event_id):
                continue
            parsed.append(event)
        event_ids = {event.event_id for event in parsed}
        for event in parsed:
            rows.append(
                {
                    "round_number": round_number,
                    "schema_version": 1,
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "kind": event.kind,
                    "actor_player_id": (
                        event.actor_player_id
                        if event.actor_player_id in public_player_ids
                        else None
                    ),
                    "target_player_id": (
                        event.target_player_id
                        if event.target_player_id in public_player_ids
                        else None
                    ),
                    "outcome": (
                        event.outcome
                        if event.outcome in _PUBLIC_OUTCOME_VALUES
                        else "unknown"
                    ),
                    "caused_by_event_id": (
                        event.caused_by_event_id
                        if event.caused_by_event_id in event_ids
                        else None
                    ),
                    "occurred_phase": (
                        event.occurred_phase
                        if event.occurred_phase in _PUBLIC_OUTCOME_PHASES
                        else "unknown"
                    ),
                }
            )
        if parsed:
            expected = f"第{round_number}轮；{render_public_round_summary(parsed)}"
            actual = str(round_data.get("public_summary") or "")
            if actual and actual != expected:
                mismatches += 1
    rows.sort(key=lambda item: (item["round_number"], item["sequence"]))
    return rows, mismatches


def _quality_gates(
    *,
    data_status: str,
    lineup: dict[str, Any],
    speech: dict[str, int],
    performance: dict[str, Any],
    choice: dict[str, int],
    outcome_count: int,
    summary_mismatches: int,
) -> list[dict[str, str | None]]:
    unavailable = data_status in {"legacy", "collecting", "unavailable"}
    lineup_status = "unavailable"
    lineup_code = "lineup_data_unavailable"
    if lineup["is_blocked"] is not None:
        lineup_status = "fail" if lineup["is_blocked"] else "pass"
        lineup_code = "lineup_blocked" if lineup["is_blocked"] else "lineup_passed"
    speech_status = (
        "unavailable"
        if speech["checked_count"] == 0
        else "fail"
        if speech["exhausted_count"] > 0
        else "warn"
        if speech["low_novelty_window_count"] > 0
        else "pass"
    )
    sample_count = performance["discrete_action_sample_count"]
    latency_status = (
        "unavailable"
        if sample_count == 0
        else "warn"
        if sample_count < 20
        else "fail"
        if (performance["discrete_action_p95_ms"] or 0) > 15000
        else "pass"
    )
    gates = [
        _gate("lineup", lineup_status, lineup_code, "无阻断违规", str(lineup["is_blocked"])),
        _gate(
            "speech_quality",
            speech_status,
            "speech_data_unavailable" if speech_status == "unavailable" else "speech_checked",
            "重写耗尽=0",
            str(speech["exhausted_count"]),
        ),
        _gate(
            "performance",
            latency_status,
            "insufficient_latency_sample" if sample_count < 20 else "latency_checked",
            "离散动作P95<=15000ms且样本>=20",
            f"samples={sample_count},p95={performance['discrete_action_p95_ms']}",
        ),
        _gate(
            "choice_normalization",
            "unavailable" if unavailable and not sum(choice.values()) else "warn" if choice["invalid_count"] else "pass",
            "choice_data_unavailable" if unavailable and not sum(choice.values()) else "choice_checked",
            "invalid=0",
            str(choice["invalid_count"]),
        ),
        _gate(
            "public_outcomes",
            "unavailable" if outcome_count == 0 else "fail" if summary_mismatches else "pass",
            "outcome_data_unavailable" if outcome_count == 0 else "outcome_summary_checked",
            "摘要不一致=0",
            str(summary_mismatches),
        ),
    ]
    return gates


def _gate(
    key: str,
    status: str,
    code: str,
    threshold: str | None,
    actual: str | None,
) -> dict[str, str | None]:
    return {
        "gate": key,
        "status": status,
        "code": code,
        "threshold": threshold,
        "actual": actual,
    }


def _data_status(*, status: str, has_payload: bool, has_p2_data: bool) -> str:
    if status in {"queued", "running", "partial"}:
        return "collecting"
    if has_p2_data:
        return "available"
    if has_payload:
        return "legacy"
    return "unavailable"


def _has_p2_action_data(actions: list[dict[str, Any]]) -> bool:
    return any(
        any(
            key in action
            for key in {
                "duration_ms",
                "budget_ms",
                "first_token_ms",
                "speech_quality_report",
                "choice_normalization_kind",
            }
        )
        for action in actions
    )


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * fraction) - 1)
    return values[index]


def _report_has_issue(report: object, code: str) -> bool:
    if not isinstance(report, dict) or not isinstance(report.get("issues"), list):
        return False
    return any(
        isinstance(issue, dict) and issue.get("code") == code
        for issue in report["issues"]
    )


def _bounded_code(value: object) -> str:
    text = str(value or "unknown")
    return text if text in _LINEUP_VIOLATION_CODES else "unknown"


def _public_player_ids(
    state: dict[str, Any], rounds: list[object]
) -> set[str]:
    result: set[str] = set()
    players = state.get("players")
    if isinstance(players, list):
        for player in players:
            if isinstance(player, dict) and isinstance(player.get("name"), str):
                result.add(player["name"])
    for round_data in rounds:
        if not isinstance(round_data, dict) or not isinstance(
            round_data.get("players"), list
        ):
            continue
        result.update(
            player for player in round_data["players"] if isinstance(player, str)
        )
    return result


def _non_negative_int(value: object, *, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return default


def _positive_int(value: object) -> int | None:
    parsed = _non_negative_int(value)
    return parsed if parsed is not None and parsed > 0 else None
