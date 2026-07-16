from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.werewolf.evaluation_bundle import (
    PRIVATE_ACTIONS,
    PublicArtifactV1,
    QualityEvaluationBundleV1,
)
from app.werewolf.execution_telemetry import (
    ACTION_DURATION_BUCKETS,
    FIRST_TOKEN_BUCKETS,
)
from app.werewolf.live import LiveEvent
from app.werewolf.voice import voice_job_candidate


EVALUATION_SCHEMA_VERSION = 1
DEFAULT_EVALUATOR_VERSION = "p3-v1"
Severity = Literal["P0", "P1", "P2"]

P0_ISSUE_CODES = frozenset(
    {
        "private_action_public_artifact",
        "private_text_public_overlap",
        "private_voice_materialized",
        "private_subtitle_materialized",
        "internal_death_cause_public",
        "hidden_role_public_before_reveal",
        "wolf_team_public_before_reveal",
        "private_role_result_public",
        "rejected_draft_public",
    }
)
PRIVATE_RESULT_KEYS = frozenset(
    {
        "attacked",
        "death_cause",
        "final_target",
        "investigated",
        "known_roles",
        "poisoned",
        "private_summaries",
        "protected",
        "raw_response",
        "wolf_teammates",
    }
)
PUBLIC_CONTENT_KEYS = frozenset(
    {"choice", "delta", "final_target", "result", "visible_result", "visible_text"}
)
REVEAL_EVENT_TYPES = frozenset(
    {"game_completed", "idiot_revealed", "role_revealed", "werewolf_self_exploded"}
)
SUSPICIOUS_TERMS = ("夜刀", "刀口", "狼队友", "毒药", "查验结果")


@dataclass(frozen=True)
class SafeQualityIssueV1:
    issue_id: str
    code: str
    severity: Severity
    channel: str
    round_number: int | None
    event_id: int | None
    utterance_id: str | None
    first_detected_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "code": self.code,
            "severity": self.severity,
            "channel": self.channel,
            "round_number": self.round_number,
            "event_id": self.event_id,
            "utterance_id": self.utterance_id,
            "first_detected_at": self.first_detected_at,
        }


@dataclass(frozen=True)
class GameQualityEvaluationV1:
    schema_version: int
    evaluator_version: str
    evaluation_status: str
    data_status: str
    verdict: str
    source_revision: str
    source_coverage: dict[str, Any]
    issue_counts: dict[str, int]
    facts: dict[str, Any]
    structure: dict[str, Any]
    voice: dict[str, Any]
    performance: dict[str, Any]
    content: dict[str, Any]
    safe_issues: tuple[SafeQualityIssueV1, ...]
    evaluated_at: str

    @property
    def has_p0(self) -> bool:
        return self.issue_counts.get("P0", 0) > 0

    def to_dict(self, *, include_issues: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "evaluator_version": self.evaluator_version,
            "evaluation_status": self.evaluation_status,
            "data_status": self.data_status,
            "verdict": self.verdict,
            "source_revision": self.source_revision,
            "source_coverage": self.source_coverage.copy(),
            "issue_counts": self.issue_counts.copy(),
            "facts": self.facts.copy(),
            "structure": self.structure.copy(),
            "voice": self.voice.copy(),
            "performance": self.performance.copy(),
            "content": self.content.copy(),
            "evaluated_at": self.evaluated_at,
        }
        if include_issues:
            payload["safe_issues"] = [issue.to_dict() for issue in self.safe_issues]
        return payload


class DisclosureLedgerV1:
    def __init__(self) -> None:
        self.revealed_players: set[str] = set()
        self.terminal_reached = False

    def role_is_revealed(self, player: str) -> bool:
        return self.terminal_reached or player in self.revealed_players

    def apply(self, artifact: PublicArtifactV1) -> None:
        if artifact.event_type == "game_completed":
            self.terminal_reached = True
            return
        if artifact.event_type not in REVEAL_EVENT_TYPES:
            return
        for key in ("actor", "player", "player_id", "target", "target_player_id"):
            value = artifact.payload.get(key)
            if isinstance(value, str) and value:
                self.revealed_players.add(value)


def evaluate_quality_bundle(
    bundle: QualityEvaluationBundleV1,
    *,
    hmac_key: str,
    evaluator_version: str = DEFAULT_EVALUATOR_VERSION,
    evaluated_at: datetime | None = None,
) -> GameQualityEvaluationV1:
    if not hmac_key:
        raise ValueError("quality evaluation HMAC key is required")
    timestamp = (evaluated_at or datetime.now(tz=UTC)).isoformat()
    issues: list[SafeQualityIssueV1] = []
    seen: set[tuple[str, str, int | None, str | None]] = set()
    ledger = DisclosureLedgerV1()
    normalized_evidence = [
        (evidence, _normalize_private_text(evidence.text))
        for evidence in bundle.private_evidence
        if len(_normalize_private_text(evidence.text)) >= 12
    ]

    for artifact in bundle.public_artifacts:
        for code, severity in _artifact_invariant_issues(artifact, ledger):
            _append_safe_issue(
                issues,
                seen,
                code=code,
                severity=severity,
                artifact=artifact,
                session_id=bundle.session_id,
                evaluator_version=evaluator_version,
                hmac_key=hmac_key,
                timestamp=timestamp,
            )
        normalized_public = _normalize_private_text(artifact.text)
        if normalized_public:
            for _evidence, private_text in normalized_evidence:
                if private_text in normalized_public:
                    code = {
                        "voice": "private_voice_materialized",
                        "subtitle": "private_subtitle_materialized",
                    }.get(artifact.channel, "private_text_public_overlap")
                    _append_safe_issue(
                        issues,
                        seen,
                        code=code,
                        severity="P0",
                        artifact=artifact,
                        session_id=bundle.session_id,
                        evaluator_version=evaluator_version,
                        hmac_key=hmac_key,
                        timestamp=timestamp,
                    )
                    break
            if not any(issue.channel == artifact.channel for issue in issues) and any(
                term in artifact.text for term in SUSPICIOUS_TERMS
            ):
                _append_safe_issue(
                    issues,
                    seen,
                    code="suspicious_private_term",
                    severity="P2",
                    artifact=artifact,
                    session_id=bundle.session_id,
                    evaluator_version=evaluator_version,
                    hmac_key=hmac_key,
                    timestamp=timestamp,
                )
        ledger.apply(artifact)

    issue_counts = {
        severity: sum(issue.severity == severity for issue in issues)
        for severity in ("P0", "P1", "P2")
    }
    data_status = bundle.source_coverage.data_status
    if data_status == "unavailable":
        verdict = "unavailable"
    elif issue_counts["P0"]:
        verdict = "fail"
    elif issue_counts["P1"] or issue_counts["P2"]:
        verdict = "warn"
    else:
        verdict = "pass"
    voice = _voice_metrics(bundle)
    structure = _structure_metrics(bundle.state, bundle.logs)
    content = _content_metrics(bundle, issues)
    return GameQualityEvaluationV1(
        schema_version=EVALUATION_SCHEMA_VERSION,
        evaluator_version=evaluator_version,
        evaluation_status="completed",
        data_status=data_status,
        verdict=verdict,
        source_revision=bundle.source_revision,
        source_coverage=bundle.source_coverage.to_dict(),
        issue_counts=issue_counts,
        facts=_fact_metrics(bundle.state, bundle.logs),
        structure=structure,
        voice=voice,
        performance=_performance_metrics(bundle),
        content=content,
        safe_issues=tuple(issues),
        evaluated_at=timestamp,
    )


def _artifact_invariant_issues(
    artifact: PublicArtifactV1,
    ledger: DisclosureLedgerV1,
) -> list[tuple[str, Severity]]:
    issues: list[tuple[str, Severity]] = []
    payload = artifact.payload
    action = artifact.action or ""
    has_public_content = payload.get("is_public") is True or any(
        key in payload and payload.get(key) not in (None, "", {}, [])
        for key in PUBLIC_CONTENT_KEYS
    )
    if action in PRIVATE_ACTIONS and has_public_content:
        code = {
            "voice": "private_voice_materialized",
            "subtitle": "private_subtitle_materialized",
        }.get(artifact.channel, "private_action_public_artifact")
        issues.append((code, "P0"))
    if _payload_has_private_result(payload):
        issues.append(("private_role_result_public", "P0"))
    if _payload_has_internal_death_cause(payload):
        issues.append(("internal_death_cause_public", "P0"))
    if _payload_marks_rejected(payload):
        issues.append(("rejected_draft_public", "P0"))
    for player, role in _role_pairs(payload):
        if role and not ledger.role_is_revealed(player) and artifact.event_type not in REVEAL_EVENT_TYPES:
            issues.append(("hidden_role_public_before_reveal", "P0"))
    if _payload_exposes_wolf_team(payload) and not ledger.terminal_reached:
        issues.append(("wolf_team_public_before_reveal", "P0"))
    return issues


def _append_safe_issue(
    issues: list[SafeQualityIssueV1],
    seen: set[tuple[str, str, int | None, str | None]],
    *,
    code: str,
    severity: Severity,
    artifact: PublicArtifactV1,
    session_id: str,
    evaluator_version: str,
    hmac_key: str,
    timestamp: str,
) -> None:
    key = (code, artifact.channel, artifact.event_id, artifact.utterance_id)
    if key in seen:
        return
    seen.add(key)
    coordinate = "\0".join(
        (
            session_id,
            evaluator_version,
            code,
            artifact.channel,
            str(artifact.round_number or ""),
            str(artifact.event_id or ""),
            artifact.utterance_id or "",
        )
    )
    digest = hmac.new(
        hmac_key.encode("utf-8"), coordinate.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:24]
    issues.append(
        SafeQualityIssueV1(
            issue_id=f"quality_{digest}",
            code=code,
            severity=severity,
            channel=artifact.channel,
            round_number=artifact.round_number,
            event_id=artifact.event_id,
            utterance_id=artifact.utterance_id,
            first_detected_at=timestamp,
        )
    )


def _normalize_private_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = re.sub(r"玩家\s*(\d+)\s*号|第?\s*(\d+)\s*号(?:玩家)?", _seat_token, normalized)
    return re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)


def _seat_token(match: re.Match[str]) -> str:
    number = match.group(1) or match.group(2) or ""
    return f"seat{number}"


def _payload_has_private_result(value: object, *, key: str = "") -> bool:
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            normalized_key = str(nested_key).lower()
            if normalized_key in PRIVATE_RESULT_KEYS and nested_value not in (None, "", [], {}):
                return True
            if _payload_has_private_result(nested_value, key=normalized_key):
                return True
    elif isinstance(value, list):
        return any(_payload_has_private_result(item, key=key) for item in value)
    return False


def _payload_has_internal_death_cause(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = str(key).lower()
            if normalized_key in {"cause", "death_cause", "caused_by"} and nested not in (
                None,
                "",
                "night_death",
                "public",
            ):
                return True
            if _payload_has_internal_death_cause(nested):
                return True
    elif isinstance(value, list):
        return any(_payload_has_internal_death_cause(item) for item in value)
    return False


def _payload_marks_rejected(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("rejected") is True or value.get("quality_status") == "rejected":
            return True
        return any(_payload_marks_rejected(item) for item in value.values())
    if isinstance(value, list):
        return any(_payload_marks_rejected(item) for item in value)
    return False


def _role_pairs(payload: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    roles = payload.get("roles")
    if isinstance(roles, dict):
        pairs.extend((str(player), str(role)) for player, role in roles.items())
    player = payload.get("player") or payload.get("player_id") or payload.get("actor")
    role = payload.get("role") or payload.get("true_role")
    if isinstance(player, str) and isinstance(role, str):
        pairs.append((player, role))
    return pairs


def _payload_exposes_wolf_team(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in {"wolf_teammates", "werewolves"} and nested:
                return True
            if _payload_exposes_wolf_team(nested):
                return True
    elif isinstance(value, list):
        return any(_payload_exposes_wolf_team(item) for item in value)
    return False


def _fact_metrics(state: dict[str, Any], logs: list[dict[str, Any]]) -> dict[str, Any]:
    opportunities = state.get("public_fact_opportunities")
    if not isinstance(opportunities, list):
        opportunities = []
    eligible = [
        item
        for item in opportunities
        if isinstance(item, dict)
        and item.get("retention") == "critical"
        and item.get("status") not in {"superseded", "not_applicable"}
    ]
    recorded = [item for item in eligible if item.get("status") == "recorded"]
    expected_prompt = 0
    included_prompt = 0
    missing_prompt = 0
    for action_log in _iter_action_logs(logs):
        coverage = action_log.get("fact_prompt_coverage")
        if not isinstance(coverage, dict):
            continue
        expected_prompt += _non_negative_int(coverage.get("expected_critical_count"))
        included_prompt += _non_negative_int(coverage.get("included_critical_count"))
        missing_prompt += _non_negative_int(coverage.get("missing_critical_count"))
    return {
        "critical_opportunity_count": len(eligible),
        "critical_recorded_count": len(recorded),
        "critical_fact_write_rate": len(recorded) / len(eligible) if eligible else None,
        "prompt_expected_critical_count": expected_prompt,
        "prompt_included_critical_count": included_prompt,
        "prompt_missing_critical_count": missing_prompt,
        "critical_fact_prompt_coverage_rate": (
            included_prompt / expected_prompt if expected_prompt else None
        ),
        "deterministic_contradiction_count": _contradiction_count(state),
    }


def _structure_metrics(state: dict[str, Any], logs: list[dict[str, Any]]) -> dict[str, Any]:
    rounds = state.get("rounds") if isinstance(state.get("rounds"), list) else []
    max_chain = 0
    chain = 0
    chain_three_count = 0
    normal_debate_rounds = 0
    for round_state in rounds:
        if not isinstance(round_state, dict):
            continue
        if round_state.get("werewolf_self_exploded"):
            chain += 1
            max_chain = max(max_chain, chain)
            if chain == 3:
                chain_three_count += 1
        else:
            chain = 0
        if (
            bool(round_state.get("debate"))
            and bool(round_state.get("votes"))
            and not round_state.get("day_ended_by_self_explosion")
        ):
            normal_debate_rounds += 1
    actions = [str(item.get("action") or "") for item in _iter_action_logs(logs)]
    sheriff_requests = sum(action.startswith("sheriff_") for action in actions)
    public_requests = sum(
        action
        in {
            "debate",
            "sheriff_run",
            "sheriff_speech",
            "sheriff_pk_speech",
            "exile_pk_speech",
            "exile_runoff_vote",
        }
        or action.startswith("sheriff_vote")
        for action in actions
    )
    return {
        "max_consecutive_self_explosions": max_chain,
        "chain_three_count": chain_three_count,
        "normal_day_debate_round_count": normal_debate_rounds,
        "sheriff_model_request_count": sheriff_requests,
        "public_model_request_count": public_requests,
        "sheriff_model_request_rate": (
            sheriff_requests / public_requests if public_requests else None
        ),
    }


def _voice_metrics(bundle: QualityEvaluationBundleV1) -> dict[str, Any]:
    coverage = bundle.source_coverage
    narratable_keys: set[tuple[int, str]] = set()
    terminal_keys: set[tuple[int, str]] = set()
    for event in bundle.live_events:
        live_event = _live_event(event)
        if live_event is None:
            continue
        speaker_kind = voice_job_candidate(live_event)
        if speaker_kind is None:
            continue
        key = (live_event.id, speaker_kind)
        narratable_keys.add(key)
        if live_event.type in {"game_completed", "game_failed", "game_canceled"}:
            terminal_keys.add(key)
    completed_voice_ranges = [
        (
            source_event_id,
            max(source_event_id, last_source_event_id),
            speaker_kind,
        )
        for voice in bundle.voice_utterances
        if voice.get("status", "complete") == "complete"
        and type(source_event_id := voice.get("source_event_id")) is int
        and type(
            last_source_event_id := voice.get("last_source_event_id", source_event_id)
        ) is int
        and isinstance((speaker_kind := voice.get("speaker_kind")), str)
    ]
    covered = {
        (event_id, speaker_kind)
        for event_id, speaker_kind in narratable_keys
        if any(
            voice_kind == speaker_kind and first_event_id <= event_id <= last_event_id
            for first_event_id, last_event_id, voice_kind in completed_voice_ranges
        )
    }
    max_event = max((event_id for event_id, _kind in narratable_keys), default=None)
    max_voice = max((event_id for event_id, _kind in covered), default=None)
    return {
        "narratable_event_count": len(narratable_keys),
        "effective_voice_event_count": len(covered),
        "missing_narratable_event_count": len(narratable_keys - covered),
        "voice_coverage_rate": len(covered) / len(narratable_keys) if narratable_keys else None,
        "max_event_id": max_event,
        "max_voice_source_event_id": max_voice,
        "voice_source_event_lag": (
            max(0, max_event - max_voice)
            if isinstance(max_event, int) and isinstance(max_voice, int)
            else None
        ),
        "terminal_judge_voice_coverage": bool(terminal_keys)
        and terminal_keys.issubset(covered),
        "pending_voice_count": coverage.pending_voice_count,
        "failed_voice_count": coverage.failed_voice_count,
        "interruption_count": sum(
            event.get("type") == "voice_interrupted" for event in bundle.live_events
        ),
        "replay_count": sum(
            event.get("type") == "voice_replayed" for event in bundle.live_events
        ),
    }


def _performance_metrics(bundle: QualityEvaluationBundleV1) -> dict[str, Any]:
    durations: list[int] = []
    first_tokens: list[int] = []
    timeout_count = 0
    retry_count = 0
    fallback_count = 0
    for action_log in _iter_action_logs(bundle.logs):
        duration = action_log.get("duration_ms")
        if type(duration) is int and duration >= 0:
            durations.append(duration)
        first_token = action_log.get("first_token_ms")
        if type(first_token) is int and first_token >= 0:
            first_tokens.append(first_token)
        if action_log.get("execution_status") == "timed_out":
            timeout_count += 1
        retry_count += max(0, _non_negative_int(action_log.get("attempt_count")) - 1)
        if action_log.get("fallback_reason"):
            fallback_count += 1
    game_duration_ms = _duration_between(bundle.started_at, bundle.completed_at)
    return {
        "action_count": len(durations),
        "action_duration_ms_sum": sum(durations),
        "action_duration_ms_max": max(durations, default=None),
        "first_token_count": len(first_tokens),
        "first_token_ms_sum": sum(first_tokens),
        "first_token_ms_max": max(first_tokens, default=None),
        "timeout_count": timeout_count,
        "retry_count": retry_count,
        "fallback_count": fallback_count,
        "action_duration_histogram": _histogram(
            durations,
            boundaries=ACTION_DURATION_BUCKETS,
        ),
        "first_token_histogram": _histogram(
            first_tokens,
            boundaries=FIRST_TOKEN_BUCKETS,
        ),
        "game_duration_ms": game_duration_ms,
        "game_duration_histogram": _histogram(
            [game_duration_ms] if game_duration_ms is not None else [],
            boundaries=(60, 180, 300, 600, 900, 1080, 1320, 1800),
        ),
    }


def _content_metrics(
    bundle: QualityEvaluationBundleV1,
    issues: list[SafeQualityIssueV1],
) -> dict[str, Any]:
    checked = 0
    repeated = 0
    rewrites = 0
    recovered = 0
    exhausted = 0
    for action_log in _iter_action_logs(bundle.logs):
        report = action_log.get("speech_quality_report")
        if not isinstance(report, dict):
            continue
        checked += 1
        codes = {
            str(item.get("code") or "")
            for item in report.get("issues", [])
            if isinstance(item, dict)
        }
        if {"repeated_debate_phrase", "low_proposition_novelty"} & codes:
            repeated += 1
        attempts = _non_negative_int(action_log.get("speech_quality_attempt_count"))
        if attempts > 1:
            rewrites += 1
            if not action_log.get("speech_quality_retry_exhausted"):
                recovered += 1
        if action_log.get("speech_quality_retry_exhausted"):
            exhausted += 1
    lineup_report = bundle.state.get("lineup_quality_report")
    warnings = (
        lineup_report.get("warnings", []) if isinstance(lineup_report, dict) else []
    )
    return {
        "speech_check_count": checked,
        "repeated_speech_count": repeated,
        "repeated_speech_rate": repeated / checked if checked else None,
        "speech_rewrite_count": rewrites,
        "speech_rewrite_recovered_count": recovered,
        "speech_retry_exhausted_count": exhausted,
        "privacy_p0_issue_count": sum(issue.severity == "P0" for issue in issues),
        "lineup_warning_count": len(warnings) if isinstance(warnings, list) else 0,
    }


def _iter_action_logs(value: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("action"), str) and isinstance(value.get("lm_log"), dict):
            found.append(value)
        else:
            for nested in value.values():
                found.extend(_iter_action_logs(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_action_logs(nested))
    return found


def _contradiction_count(state: dict[str, Any]) -> int:
    propositions = state.get("public_fact_propositions")
    if not isinstance(propositions, list):
        return 0
    seen: dict[tuple[str, str, str, str], bool] = {}
    contradictions: set[tuple[str, str, str, str]] = set()
    for proposition in propositions:
        if not isinstance(proposition, dict):
            continue
        if proposition.get("correction_of") or proposition.get("supersedes"):
            continue
        key = tuple(
            str(proposition.get(field) or "")
            for field in ("subject", "predicate", "object", "scope")
        )
        polarity = bool(proposition.get("polarity", True))
        if key in seen and seen[key] != polarity:
            contradictions.add(key)
        else:
            seen[key] = polarity
    return len(contradictions)


def _non_negative_int(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _live_event(data: dict[str, Any]) -> LiveEvent | None:
    try:
        if (
            type(data.get("id")) is not int
            or not isinstance(data.get("type"), str)
            or not isinstance(data.get("run_id"), str)
            or not isinstance(data.get("session_id"), str)
            or not isinstance(data.get("created_at"), str)
        ):
            return None
        return LiveEvent(
            id=data["id"],
            type=data["type"],
            run_id=data["run_id"],
            session_id=data["session_id"],
            created_at=data["created_at"],
            round=data.get("round") if type(data.get("round")) is int else None,
            phase=data.get("phase") if isinstance(data.get("phase"), str) else None,
            actor=data.get("actor") if isinstance(data.get("actor"), str) else None,
            action=data.get("action") if isinstance(data.get("action"), str) else None,
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
        )
    except (TypeError, ValueError):
        return None


def _duration_between(started_at: str | None, completed_at: str | None) -> int | None:
    if not started_at or not completed_at:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((completed - started).total_seconds() * 1000))


def _histogram(values_ms: list[int], *, boundaries: tuple[float, ...]) -> dict[str, Any]:
    values_seconds = [max(0, value) / 1000 for value in values_ms]
    buckets = {
        f"{boundary:g}": sum(value <= boundary for value in values_seconds)
        for boundary in boundaries
    }
    buckets["+Inf"] = len(values_seconds)
    return {
        "buckets": buckets,
        "count": len(values_seconds),
        "sum_seconds": sum(values_seconds),
    }
