from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from collections import defaultdict
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

MAX_CRITICAL_ACTIONS = 64
MAX_CRITICAL_CLAUSE_IDS = 16
CRITICAL_DECISION_ACTIONS = frozenset(
    {
        "remove",
        "protect",
        "investigate",
        "witch_save",
        "witch_poison",
        "hunter_shoot",
        "sheriff_run",
        "sheriff_withdraw",
        "sheriff_vote",
        "sheriff_runoff_vote",
        "werewolf_self_explosion",
        "speech_order",
        "sheriff_badge",
        "vote",
        "exile_runoff_vote",
        "werewolf_kill_vote",
    }
)
_KNOWN_ACTION_CLAUSE_IDS: dict[str, tuple[str, ...]] = {
    "remove": ("night.werewolf_attack.non_wolf_targets.v1",),
    "werewolf_kill_vote": ("night.werewolf_attack.non_wolf_targets.v1",),
    "werewolf_self_explosion": (
        "day.self_explosion.interruption.v1",
        "private.werewolf.team_knowledge.v1",
    ),
    "witch_save": (
        "night.witch.resources_and_targets.v1",
        "private.witch.attack_observation.v1",
    ),
    "witch_poison": (
        "night.witch.resources_and_targets.v1",
        "private.witch.attack_observation.v1",
    ),
    "vote": ("day.exile.weighted_plurality_and_runoff.v1",),
    "exile_runoff_vote": ("day.exile.weighted_plurality_and_runoff.v1",),
    "hunter_shoot": ("settlement.hunter.trigger_and_order.v1",),
    "sheriff_run": ("day.sheriff.eligibility_and_runoff.v1",),
    "sheriff_withdraw": ("day.sheriff.eligibility_and_runoff.v1",),
    "sheriff_vote": ("day.sheriff.eligibility_and_runoff.v1",),
    "sheriff_runoff_vote": ("day.sheriff.eligibility_and_runoff.v1",),
}
_NO_EFFECT_CHOICES = frozenset(
    {
        "",
        "不使用解药",
        "不使用毒药",
        "不开枪",
        "不发动",
        "不自爆",
        "不竞选",
        "不退水",
        "弃权",
        "跳过",
        "skip",
        "none",
    }
)

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
class SafeCriticalActionV1:
    """Bounded post-game decision attribution without private evidence text."""

    action_id: str
    round_number: int | None
    action: str
    action_origin: str
    input_completeness: str
    action_legality: str
    reasoning_observation: str
    direct_impact: str
    attribution: str
    clause_ids: tuple[str, ...]
    coverage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "action_id": self.action_id,
            "round_number": self.round_number,
            "action": self.action,
            "action_origin": self.action_origin,
            "input_completeness": self.input_completeness,
            "action_legality": self.action_legality,
            "reasoning_observation": self.reasoning_observation,
            "direct_impact": self.direct_impact,
            "attribution": self.attribution,
            "clause_ids": list(self.clause_ids),
            "coverage": self.coverage.copy(),
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
    liveness: dict[str, Any]
    critical_actions: tuple[SafeCriticalActionV1, ...]
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
            "liveness": self.liveness.copy(),
            "critical_actions": [action.to_dict() for action in self.critical_actions],
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
        liveness=_liveness_metrics(bundle),
        critical_actions=_critical_action_cards(bundle),
        safe_issues=tuple(issues),
        evaluated_at=timestamp,
    )


def _liveness_metrics(bundle: QualityEvaluationBundleV1) -> dict[str, Any]:
    runtime = bundle.liveness_runtime if isinstance(bundle.liveness_runtime, dict) else {}
    snapshot = runtime.get("experience_snapshot")
    safe_snapshot = snapshot if isinstance(snapshot, dict) else {}
    feature_modes = safe_snapshot.get("feature_modes")
    action_logs = [
        item
        for item in _iter_action_logs(bundle.logs)
        if item.get("action")
        in {
            "debate",
            "sheriff_speech",
            "sheriff_pk_speech",
            "exile_pk_speech",
            "exile_last_words",
        }
    ]
    timing_fields = (
        "turn_ready_at",
        "actor_brain_started_at",
        "turn_plan_ready_at",
        "renderer_started_at",
        "first_model_delta_at",
        "first_clause_committed_at",
    )
    timing_coverage = {field: 0 for field in timing_fields}
    prompt_chars: list[int] = []
    hard_gate_ms: list[int] = []
    hard_retry_count = 0
    hard_exhausted_count = 0
    partial_count = 0
    interrupted_count = 0
    stage_values: dict[str, list[int]] = {
        "turn_to_actor_brain": [],
        "actor_brain_to_plan": [],
        "plan_to_renderer": [],
        "renderer_to_first_delta": [],
        "first_delta_to_clause": [],
        "turn_to_first_clause": [],
    }
    stage_pairs = (
        ("turn_to_actor_brain", "turn_ready_at", "actor_brain_started_at"),
        ("actor_brain_to_plan", "actor_brain_started_at", "turn_plan_ready_at"),
        ("plan_to_renderer", "turn_plan_ready_at", "renderer_started_at"),
        ("renderer_to_first_delta", "renderer_started_at", "first_model_delta_at"),
        ("first_delta_to_clause", "first_model_delta_at", "first_clause_committed_at"),
        ("turn_to_first_clause", "turn_ready_at", "first_clause_committed_at"),
    )
    turn_ready_by_speech: dict[str, int] = {}
    for action_log in action_logs:
        timing = action_log.get("liveness_timing")
        safe_timing = timing if isinstance(timing, dict) else {}
        for field in timing_fields:
            if type(safe_timing.get(field)) is int:
                timing_coverage[field] += 1
        for name, started_field, finished_field in stage_pairs:
            started = safe_timing.get(started_field)
            finished = safe_timing.get(finished_field)
            if type(started) is int and type(finished) is int and finished >= started:
                stage_values[name].append(finished - started)
        prompt_size = action_log.get("prompt_chars")
        if type(prompt_size) is int and prompt_size >= 0:
            prompt_chars.append(prompt_size)
        gate_duration = safe_timing.get("hard_gate_duration_ms")
        if type(gate_duration) is int and gate_duration >= 0:
            hard_gate_ms.append(gate_duration)
        lm_log = action_log.get("lm_log")
        safe_lm_log = lm_log if isinstance(lm_log, dict) else {}
        hard_retry_count += max(
            0,
            _non_negative_int(safe_lm_log.get("hard_speech_gate_rejected_count")),
        )
        if safe_lm_log.get("speech_generation_status") == "partial_hard_gate_stop":
            hard_exhausted_count += 1
        receipt = action_log.get("speech_turn_receipt")
        safe_receipt = receipt if isinstance(receipt, dict) else {}
        speech_id = safe_receipt.get("speech_id") or safe_lm_log.get("speech_id")
        turn_ready_at = safe_timing.get("turn_ready_at")
        if isinstance(speech_id, str) and type(turn_ready_at) is int:
            turn_ready_by_speech[speech_id] = turn_ready_at
        partial_count += safe_receipt.get("status") == "partial"
        interrupted_count += safe_receipt.get("status") == "interrupted"

    voice_timings = runtime.get("voice_timings")
    safe_voice_timings = voice_timings if isinstance(voice_timings, list) else []
    tts_to_audio_ms: list[int] = []
    turn_to_audio_by_speech: dict[str, int] = {}
    voice_status_counts: dict[str, int] = {}
    voice_timing_coverage = {"tts_started_at": 0, "first_audio_chunk_at": 0}
    for item in safe_voice_timings:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown")
        voice_status_counts[status] = voice_status_counts.get(status, 0) + 1
        started = _datetime_ms(item.get("tts_started_at"))
        first_audio = _datetime_ms(item.get("first_audio_chunk_at"))
        if started is not None:
            voice_timing_coverage["tts_started_at"] += 1
        if first_audio is not None:
            voice_timing_coverage["first_audio_chunk_at"] += 1
        if started is not None and first_audio is not None and first_audio >= started:
            tts_to_audio_ms.append(first_audio - started)
        speech_id = item.get("speech_id")
        turn_ready_at = turn_ready_by_speech.get(speech_id) if isinstance(speech_id, str) else None
        if (
            isinstance(speech_id, str)
            and turn_ready_at is not None
            and first_audio is not None
            and first_audio >= turn_ready_at
        ):
            latency = first_audio - turn_ready_at
            current = turn_to_audio_by_speech.get(speech_id)
            turn_to_audio_by_speech[speech_id] = (
                latency if current is None else min(current, latency)
            )

    observations = runtime.get("playback_observations")
    safe_observations = observations if isinstance(observations, list) else []
    playback_status_counts: dict[str, int] = {}
    playback_timing_coverage = {
        "playback_started_at": 0,
        "playback_finished_at": 0,
        "ack_received_at": 0,
    }
    playback_windows: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for item in safe_observations:
        if not isinstance(item, dict):
            continue
        client_status = str(item.get("client_status") or "unknown")
        playback_status_counts[client_status] = (
            playback_status_counts.get(client_status, 0) + 1
        )
        for field in playback_timing_coverage:
            if _datetime_ms(item.get(field)) is not None:
                playback_timing_coverage[field] += 1
        playback_session_id = item.get("playback_session_id")
        playback_started = _datetime_ms(item.get("playback_started_at"))
        playback_finished = _datetime_ms(item.get("playback_finished_at"))
        if (
            isinstance(playback_session_id, str)
            and playback_started is not None
            and playback_finished is not None
            and playback_finished >= playback_started
        ):
            playback_windows[playback_session_id].append(
                (playback_started, playback_finished)
            )

    speaker_gap_ms: list[int] = []
    for windows in playback_windows.values():
        ordered = sorted(windows)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current[0] >= previous[1]:
                speaker_gap_ms.append(current[0] - previous[1])

    actor_mind = runtime.get("actor_mind")
    safe_actor_mind = actor_mind if isinstance(actor_mind, dict) else {}
    denominator = len(action_logs)
    return {
        "experience_revision": runtime.get("experience_revision"),
        "experiment_id": runtime.get("experiment_id"),
        "variant": runtime.get("variant"),
        "feature_modes": feature_modes if isinstance(feature_modes, dict) else {},
        "public_speech_count": denominator,
        "timing_coverage": {
            field: {
                "count": count,
                "denominator": denominator,
                "rate": count / denominator if denominator else None,
            }
            for field, count in timing_coverage.items()
        },
        "stage_latency_ms": {
            name: _latency_summary(values) for name, values in stage_values.items()
        },
        "prompt_chars": _latency_summary(prompt_chars),
        "hard_gate_duration_ms": _latency_summary(hard_gate_ms),
        "hard_retry_count": hard_retry_count,
        "hard_retry_rate": hard_retry_count / denominator if denominator else None,
        "hard_exhausted_count": hard_exhausted_count,
        "hard_exhausted_rate": (
            hard_exhausted_count / denominator if denominator else None
        ),
        "partial_speech_count": partial_count,
        "interrupted_speech_count": interrupted_count,
        "voice_timing_coverage": {
            **voice_timing_coverage,
            "denominator": len(safe_voice_timings),
        },
        "tts_to_first_audio_ms": _latency_summary(tts_to_audio_ms),
        "turn_to_first_audio_ms": _latency_summary(
            list(turn_to_audio_by_speech.values())
        ),
        "voice_status_counts": voice_status_counts,
        "playback_timing_coverage": {
            **playback_timing_coverage,
            "denominator": len(safe_observations),
        },
        "playback_status_counts": playback_status_counts,
        "speaker_gap_ms": _latency_summary(speaker_gap_ms),
        "actor_mind": {
            "snapshot_count": _non_negative_int(safe_actor_mind.get("snapshot_count")),
            "update_count": _non_negative_int(safe_actor_mind.get("update_count")),
            "source_complete_count": _non_negative_int(
                safe_actor_mind.get("source_complete_count")
            ),
        },
    }


def _latency_summary(values: list[int]) -> dict[str, int | None]:
    ordered = sorted(value for value in values if value >= 0)
    return {
        "count": len(ordered),
        "p50": _nearest_rank(ordered, 0.50),
        "p95": _nearest_rank(ordered, 0.95),
        "max": max(ordered, default=None),
    }


def _nearest_rank(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int((len(values) * quantile) - 1e-9)))
    return values[index]


def _datetime_ms(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return round(parsed.timestamp() * 1000)


def _artifact_invariant_issues(
    artifact: PublicArtifactV1,
    ledger: DisclosureLedgerV1,
) -> list[tuple[str, Severity]]:
    issues: list[tuple[str, Severity]] = []
    payload = artifact.payload
    action = artifact.action or ""
    has_public_content = payload.get("is_public") is True or any(
        key in payload and payload.get(key) not in (None, "", {}, []) for key in PUBLIC_CONTENT_KEYS
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
        if (
            role
            and not ledger.role_is_revealed(player)
            and artifact.event_type not in REVEAL_EVENT_TYPES
        ):
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
            "exile_last_words",
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
        and type(last_source_event_id := voice.get("last_source_event_id", source_event_id)) is int
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
        "terminal_judge_voice_coverage": bool(terminal_keys) and terminal_keys.issubset(covered),
        "pending_voice_count": coverage.pending_voice_count,
        "failed_voice_count": coverage.failed_voice_count,
        "interruption_count": sum(
            event.get("type") == "voice_interrupted" for event in bundle.live_events
        ),
        "replay_count": sum(event.get("type") == "voice_replayed" for event in bundle.live_events),
    }


def _critical_action_cards(
    bundle: QualityEvaluationBundleV1,
) -> tuple[SafeCriticalActionV1, ...]:
    candidates: list[tuple[int, int, SafeCriticalActionV1]] = []
    seen_action_ids: set[str] = set()
    player_roles, seat_players = _terminal_player_roles(bundle.state)
    terminal = bool(bundle.state.get("winner")) or any(
        event.get("type") == "game_completed" for event in bundle.live_events
    )
    for sequence, (round_number, action_log) in enumerate(
        _iter_action_logs_with_round(bundle.logs)
    ):
        action = str(action_log.get("action") or "")
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", action) is None:
            continue
        lm_log = action_log.get("lm_log")
        action_id = lm_log.get("action_id") if isinstance(lm_log, dict) else None
        if not isinstance(action_id, str) or re.fullmatch(
            r"[A-Za-z0-9_-]{1,80}", action_id
        ) is None:
            action_id = _derived_safe_action_id(
                bundle,
                action_log=action_log,
                action=action,
                round_number=round_number,
                sequence=sequence,
            )
        if action_id in seen_action_ids:
            continue
        seen_action_ids.add(action_id)
        reasoning = _private_model_reasoning(action_log) if terminal else ""
        actor = str(action_log.get("actor") or "")
        clause_ids, coverage = _rule_clause_coverage(
            bundle.state,
            action_log,
            action=action,
            actor_role=player_roles.get(actor),
            reasoning=reasoning,
        )
        input_completeness = _input_completeness(action_log, coverage)
        action_origin = _safe_action_origin(action_log)
        legality = _safe_action_legality(action_log, action_origin=action_origin)
        observation = _reasoning_observation(
            action_log,
            action=action,
            actor=actor,
            actor_role=player_roles.get(actor),
            reasoning=reasoning,
            seat_players=seat_players,
            coverage=coverage,
        )
        card = SafeCriticalActionV1(
            action_id=action_id,
            round_number=round_number,
            action=action,
            action_origin=action_origin,
            input_completeness=input_completeness,
            action_legality=legality,
            reasoning_observation=observation,
            direct_impact=_direct_action_impact(
                action_log,
                action=action,
                action_origin=action_origin,
            ),
            attribution=_decision_attribution(
                action_origin=action_origin,
                input_completeness=input_completeness,
                reasoning_observation=observation,
            ),
            clause_ids=tuple(clause_ids),
            coverage=coverage,
        )
        priority = _critical_action_priority(card)
        if priority > 0:
            candidates.append((priority, sequence, card))

    selected = sorted(candidates, key=lambda item: (-item[0], item[1]))[:MAX_CRITICAL_ACTIONS]
    return tuple(card for _priority, _sequence, card in sorted(selected, key=lambda item: item[1]))


def _derived_safe_action_id(
    bundle: QualityEvaluationBundleV1,
    *,
    action_log: dict[str, Any],
    action: str,
    round_number: int | None,
    sequence: int,
) -> str:
    material = "|".join(
        (
            str(bundle.state.get("session_id") or "legacy"),
            str(round_number if round_number is not None else "unknown"),
            str(sequence),
            str(action_log.get("actor") or "unknown"),
            action,
        )
    )
    return f"act_safe_{hashlib.sha256(material.encode()).hexdigest()[:16]}"


def _iter_action_logs_with_round(
    value: object,
    *,
    round_number: int | None = None,
) -> list[tuple[int | None, dict[str, Any]]]:
    found: list[tuple[int | None, dict[str, Any]]] = []
    if isinstance(value, dict):
        current_round = round_number
        raw_number = value.get("number")
        if type(raw_number) is int and raw_number >= 0:
            current_round = raw_number
        if isinstance(value.get("action"), str) and isinstance(value.get("lm_log"), dict):
            found.append((current_round, value))
        else:
            for nested in value.values():
                found.extend(_iter_action_logs_with_round(nested, round_number=current_round))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_action_logs_with_round(nested, round_number=round_number))
    return found


def _terminal_player_roles(
    state: dict[str, Any],
) -> tuple[dict[str, str], dict[int, tuple[str, str]]]:
    by_name: dict[str, str] = {}
    by_seat: dict[int, tuple[str, str]] = {}
    players = state.get("players")
    if not isinstance(players, list):
        return by_name, by_seat
    for index, player in enumerate(players, start=1):
        if not isinstance(player, dict):
            continue
        name = player.get("name")
        role = player.get("role")
        if not isinstance(name, str) or not name or not isinstance(role, str) or not role:
            continue
        by_name[name] = role
        seat = player.get("seat")
        effective_seat = seat if type(seat) is int and seat > 0 else index
        by_seat[effective_seat] = (name, role)
    return by_name, by_seat


def _private_model_reasoning(action_log: dict[str, Any]) -> str:
    model_result = action_log.get("model_result")
    if isinstance(model_result, dict) and isinstance(model_result.get("reasoning"), str):
        return str(model_result["reasoning"])
    lm_log = action_log.get("lm_log")
    result = lm_log.get("result") if isinstance(lm_log, dict) else None
    if isinstance(result, dict) and isinstance(result.get("reasoning"), str):
        return str(result["reasoning"])
    return ""


def _rule_clause_coverage(
    state: dict[str, Any],
    action_log: dict[str, Any],
    *,
    action: str,
    actor_role: str | None,
    reasoning: str,
) -> tuple[list[str], dict[str, Any]]:
    clause_texts, frozen_ids = _frozen_action_clauses(
        state,
        action=action,
        actor_role=actor_role,
    )
    required_ids = [*frozen_ids, *_KNOWN_ACTION_CLAUSE_IDS.get(action, ())]
    if action in {"vote", "exile_runoff_vote"} and _mentions_wolf_self_attack(reasoning):
        required_ids.append("night.werewolf_attack.non_wolf_targets.v1")
    clause_ids = _bounded_unique_strings(required_ids, limit=MAX_CRITICAL_CLAUSE_IDS)
    if not clause_ids:
        return [], {
            "schema_version": 1,
            "status": "unknown",
            "required_count": 0,
            "included_count": 0,
            "missing_count": 0,
            "missing_clause_ids": [],
        }

    explicit_ids = _explicit_prompt_clause_ids(action_log)
    lm_log = action_log.get("lm_log")
    prompt = str(lm_log.get("prompt") or "") if isinstance(lm_log, dict) else ""
    if explicit_ids is None and not prompt:
        return clause_ids, {
            "schema_version": 1,
            "status": "unknown",
            "required_count": len(clause_ids),
            "included_count": 0,
            "missing_count": 0,
            "missing_clause_ids": [],
        }

    included: list[str] = []
    missing: list[str] = []
    for clause_id in clause_ids:
        present = (
            clause_id in explicit_ids
            if explicit_ids is not None
            else _prompt_supports_clause(
                prompt,
                clause_id=clause_id,
                frozen_text=clause_texts.get(clause_id, ""),
                action_log=action_log,
            )
        )
        (included if present else missing).append(clause_id)
    status = "complete" if not missing else "missing" if not included else "partial"
    return clause_ids, {
        "schema_version": 1,
        "status": status,
        "required_count": len(clause_ids),
        "included_count": len(included),
        "missing_count": len(missing),
        "missing_clause_ids": missing,
    }


def _frozen_action_clauses(
    state: dict[str, Any],
    *,
    action: str,
    actor_role: str | None,
) -> tuple[dict[str, str], list[str]]:
    snapshot = state.get("rule_set_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = state.get("rule_set")
    contract = snapshot.get("rule_contract") if isinstance(snapshot, dict) else None
    raw_clauses = contract.get("clauses") if isinstance(contract, dict) else None
    if not isinstance(raw_clauses, list):
        return {}, []
    texts: dict[str, str] = {}
    clause_ids: list[str] = []
    for raw in raw_clauses:
        if not isinstance(raw, dict) or raw.get("audience") == "internal_only":
            continue
        clause_id = raw.get("clause_id")
        actions = raw.get("actions")
        roles = raw.get("roles")
        if not isinstance(clause_id, str) or not clause_id:
            continue
        if isinstance(actions, list) and actions and action not in actions:
            continue
        if isinstance(roles, list) and roles and actor_role not in roles:
            continue
        clause_ids.append(clause_id)
        text = raw.get("neutral_text_zh")
        if isinstance(text, str):
            texts[clause_id] = text
    return texts, clause_ids


def _explicit_prompt_clause_ids(action_log: dict[str, Any]) -> set[str] | None:
    lm_log = action_log.get("lm_log")
    for container in (action_log, lm_log if isinstance(lm_log, dict) else {}):
        for key in ("prompt_clause_ids", "rule_clause_ids", "injected_clause_ids"):
            value = container.get(key)
            if isinstance(value, list):
                return {
                    item
                    for item in value
                    if isinstance(item, str)
                    and re.fullmatch(r"[a-z0-9_.-]{1,120}", item) is not None
                }
    return None


def _prompt_supports_clause(
    prompt: str,
    *,
    clause_id: str,
    frozen_text: str,
    action_log: dict[str, Any],
) -> bool:
    if frozen_text and frozen_text in prompt:
        return True
    compact = re.sub(r"\s+", "", prompt)
    if clause_id == "night.werewolf_attack.non_wolf_targets.v1":
        return (
            re.search(
                r"狼人.{0,18}(?:只能袭击非狼人|不能.{0,8}(?:自己|狼人队友|狼队友))",
                compact,
            )
            is not None
        )
    if clause_id == "day.self_explosion.interruption.v1":
        return "自爆" in compact and any(
            term in compact for term in ("结束当日", "当日不再投票", "剩余公开动作")
        )
    if clause_id == "private.werewolf.team_knowledge.v1":
        return any(term in compact for term in ("狼人队友", "狼队友", "队友名单"))
    if clause_id == "night.witch.resources_and_targets.v1":
        action = str(action_log.get("action") or "")
        resource = "解药" if action == "witch_save" else "毒药"
        return resource in compact and f"不使用{resource}" in compact
    if clause_id == "private.witch.attack_observation.v1":
        return any(term in compact for term in ("被狼人袭击", "狼人袭击目标", "狼人袭击的是"))
    if clause_id == "day.exile.weighted_plurality_and_runoff.v1":
        return "最高票" in compact and any(term in compact for term in ("平票", "PK", "二轮"))
    if clause_id == "settlement.hunter.trigger_and_order.v1":
        return "猎人" in compact and any(
            term in compact for term in ("开枪", "不能发动", "死亡结算")
        )
    if clause_id == "day.sheriff.eligibility_and_runoff.v1":
        return "警长" in compact and any(term in compact for term in ("警下", "退水", "平票", "PK"))
    return False


def _input_completeness(action_log: dict[str, Any], coverage: dict[str, Any]) -> str:
    missing_ids = coverage.get("missing_clause_ids")
    safe_missing = missing_ids if isinstance(missing_ids, list) else []
    if any(str(item).startswith("private.") for item in safe_missing):
        return "private_observation_missing"
    if safe_missing:
        return "rule_missing"
    fact_coverage = action_log.get("fact_prompt_coverage")
    if isinstance(fact_coverage, dict) and _non_negative_int(
        fact_coverage.get("missing_critical_count")
    ):
        return "critical_public_fact_missing"
    if coverage.get("status") == "complete":
        return "complete"
    return "unknown"


def _safe_action_origin(action_log: dict[str, Any]) -> str:
    lifecycle = str(
        action_log.get("lifecycle_status") or action_log.get("execution_status") or "completed"
    )
    if lifecycle == "canceled":
        return "canceled"
    effective_result = action_log.get("effective_result")
    origin = (
        effective_result.get("origin")
        if isinstance(effective_result, dict)
        else action_log.get("effective_origin")
    )
    reason = str(
        (effective_result.get("reason_code") if isinstance(effective_result, dict) else None)
        or action_log.get("reason_code")
        or action_log.get("fallback_reason")
        or ""
    )
    if origin == "state_machine":
        return "state_machine"
    if origin == "system_fallback" or lifecycle == "fallback":
        if _action_ended_with_provider_timeout(action_log) or reason.startswith(
            ("timeout", "batch_deadline")
        ):
            return "system_timeout"
        if reason == "rule_default" or "default" in reason:
            return "rule_default"
        return "system_fallback"
    if origin == "none" or lifecycle in {"failed", "timed_out"}:
        return "failed"
    if _non_negative_int(action_log.get("attempt_count")) > 1:
        return "model_after_retry"
    return "model_first_attempt"


def _safe_action_legality(action_log: dict[str, Any], *, action_origin: str) -> str:
    lifecycle = str(
        action_log.get("lifecycle_status") or action_log.get("execution_status") or "completed"
    )
    model_result = action_log.get("model_result")
    model_status = str(model_result.get("status") or "") if isinstance(model_result, dict) else ""
    invalid = action_log.get("invalid_value") is not None or model_status == "invalid"
    normalized = action_log.get("choice_normalization_kind") not in (None, "exact")
    if lifecycle == "canceled":
        return "legal_but_canceled"
    if invalid and action_origin in {"system_timeout", "system_fallback", "rule_default"}:
        return "invalid_system_fallback"
    if invalid or normalized:
        return "invalid_normalized" if lifecycle == "completed" else "invalid_not_executed"
    if action_origin in {"system_timeout", "system_fallback", "rule_default", "state_machine"}:
        return "legal_system_result"
    if lifecycle in {"failed", "timed_out"}:
        return "not_executed"
    options = action_log.get("options")
    choice = _effective_choice(action_log)
    if isinstance(options, list) and options:
        return "legal_executed" if choice in options else "unknown"
    return "legal_executed" if action_origin.startswith("model_") else "unknown"


def _reasoning_observation(
    action_log: dict[str, Any],
    *,
    action: str,
    actor: str,
    actor_role: str | None,
    reasoning: str,
    seat_players: dict[int, tuple[str, str]],
    coverage: dict[str, Any],
) -> str:
    del actor
    if not reasoning.strip():
        return "not_available"
    compact = re.sub(r"\s+", "", reasoning)
    if actor_role == "狼人" and _claims_non_wolf_teammate(compact, seat_players):
        return "identity_information_conflict"
    if action == "witch_save" and _witch_reasoning_is_internally_contradictory(
        compact,
        action_log=action_log,
        seat_players=seat_players,
    ):
        return "internal_logic_contradiction"
    if _mentions_wolf_self_attack(compact):
        missing = coverage.get("missing_clause_ids")
        if isinstance(missing, list) and "night.werewolf_attack.non_wolf_targets.v1" in missing:
            return "used_unspecified_rule"
        return "hard_rule_conflict"
    return "not_assessed"


def _claims_non_wolf_teammate(reasoning: str, seat_players: dict[int, tuple[str, str]]) -> bool:
    for seat, (name, role) in seat_players.items():
        if role == "狼人":
            continue
        references = (rf"{seat}号", re.escape(name))
        if any(
            re.search(rf"{reference}.{{0,12}}(?:狼人队友|狼队友|我的队友)", reasoning)
            or re.search(rf"(?:狼人队友|狼队友|我的队友).{{0,12}}{reference}", reasoning)
            for reference in references
        ):
            return True
    return False


def _witch_reasoning_is_internally_contradictory(
    reasoning: str,
    *,
    action_log: dict[str, Any],
    seat_players: dict[int, tuple[str, str]],
) -> bool:
    claims_non_wolf_attack_rule = (
        re.search(
            r"(?:狼人|狼).{0,10}(?:不能|不可能|不会).{0,10}(?:自刀|刀自己|刀队友|袭击自己|袭击队友)",
            reasoning,
        )
        is not None
    )
    if not claims_non_wolf_attack_rule:
        return False
    raw_options = action_log.get("options")
    target_names = (
        {item for item in raw_options if isinstance(item, str) and item not in _NO_EFFECT_CHOICES}
        if isinstance(raw_options, list)
        else set()
    )
    for seat, (name, _role) in seat_players.items():
        if name not in target_names:
            continue
        for reference in (rf"{seat}号", re.escape(name)):
            if re.search(rf"{reference}.{{0,8}}(?:是|为).{{0,3}}(?:狼人|狼)", reasoning):
                return True
    return False


def _mentions_wolf_self_attack(reasoning: str) -> bool:
    compact = re.sub(r"\s+", "", reasoning)
    return (
        re.search(
            r"(?:狼人|狼).{0,10}(?:可以|可能|能够|会).{0,8}(?:自刀|刀自己|刀队友|袭击自己|袭击队友)",
            compact,
        )
        is not None
    )


def _direct_action_impact(action_log: dict[str, Any], *, action: str, action_origin: str) -> str:
    lifecycle = str(
        action_log.get("lifecycle_status") or action_log.get("execution_status") or "completed"
    )
    if lifecycle == "canceled":
        return "canceled_no_effect"
    if lifecycle in {"failed", "timed_out"} or action_origin == "failed":
        return "failed_no_effect"
    choice = _effective_choice(action_log)
    if str(choice or "").strip().lower() in _NO_EFFECT_CHOICES:
        return "no_state_change"
    if action == "werewolf_self_explosion":
        return "phase_ended"
    if action in {"vote", "exile_runoff_vote", "sheriff_vote", "sheriff_runoff_vote"}:
        return "vote_recorded"
    if action in {"witch_save", "witch_poison", "hunter_shoot", "remove", "protect", "investigate"}:
        return "game_state_effect_applied"
    if action_origin in {"system_timeout", "system_fallback", "rule_default", "state_machine"}:
        return "system_result_applied"
    return "model_result_applied"


def _decision_attribution(
    *,
    action_origin: str,
    input_completeness: str,
    reasoning_observation: str,
) -> str:
    if reasoning_observation == "identity_information_conflict":
        return "model_reasoning_error"
    if reasoning_observation == "internal_logic_contradiction":
        return "model_internal_logic_contradiction"
    if reasoning_observation == "used_unspecified_rule" or (
        reasoning_observation == "hard_rule_conflict" and input_completeness != "complete"
    ):
        return "model_judgment_and_rule_input_gap"
    if reasoning_observation == "hard_rule_conflict":
        return "model_reasoning_error"
    if action_origin == "canceled":
        return "canceled"
    if action_origin in {"system_timeout", "system_fallback", "rule_default", "failed"}:
        return "runtime_fallback"
    return "not_determined"


def _critical_action_priority(card: SafeCriticalActionV1) -> int:
    if card.reasoning_observation not in {"not_available", "not_assessed"}:
        return 100
    if card.input_completeness not in {"complete", "unknown"}:
        return 90
    if card.action_origin in {
        "system_timeout",
        "system_fallback",
        "rule_default",
        "failed",
        "canceled",
    }:
        return 80
    if card.action_legality not in {"legal_executed", "unknown"}:
        return 70
    return 40 if card.action in CRITICAL_DECISION_ACTIONS else 0


def _effective_choice(action_log: dict[str, Any]) -> object:
    effective = action_log.get("effective_result")
    if isinstance(effective, dict) and "choice" in effective:
        return effective.get("choice")
    return action_log.get("choice")


def _action_ended_with_provider_timeout(action_log: dict[str, Any]) -> bool:
    results = _provider_attempt_results(action_log)
    return bool(results) and results[-1] == "timed_out"


def _provider_attempt_results(action_log: dict[str, Any]) -> list[str]:
    lm_log = action_log.get("lm_log")
    attempts = lm_log.get("attempt_outcomes") if isinstance(lm_log, dict) else None
    if not isinstance(attempts, list):
        return []
    return [
        str(item.get("attempt_result"))
        for item in attempts
        if isinstance(item, dict) and isinstance(item.get("attempt_result"), str)
    ]


def _bounded_unique_strings(value: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if item in seen or re.fullmatch(r"[a-z0-9_.-]{1,120}", item) is None:
            continue
        seen.add(item)
        result.append(item)
        if len(result) == limit:
            break
    return result


def _performance_metrics(bundle: QualityEvaluationBundleV1) -> dict[str, Any]:
    durations: list[int] = []
    first_tokens: list[int] = []
    retry_count = 0
    fallback_count = 0
    logical_timeout_fallback_count = 0
    action_logs = list(_iter_action_logs(bundle.logs))
    logical_status_counts = {
        "completed_by_model": 0,
        "completed_by_system_fallback": 0,
        "canceled": 0,
        "failed": 0,
    }
    provider_attempt_counts = {
        "valid": 0,
        "invalid": 0,
        "timeout": 0,
        "transport_failure": 0,
        "canceled": 0,
    }
    retry_counts = {"provider_retry": 0, "format_retry": 0, "quality_rewrite": 0}
    attempt_result_names = {
        "valid_response": "valid",
        "invalid_response": "invalid",
        "timed_out": "timeout",
        "transport_failed": "transport_failure",
        "canceled": "canceled",
    }
    for action_log in action_logs:
        duration = action_log.get("duration_ms")
        if type(duration) is int and duration >= 0:
            durations.append(duration)
        first_token = action_log.get("first_token_ms")
        if type(first_token) is int and first_token >= 0:
            first_tokens.append(first_token)
        execution_status = str(
            action_log.get("lifecycle_status") or action_log.get("execution_status") or "completed"
        )
        retry_count += max(0, _non_negative_int(action_log.get("attempt_count")) - 1)
        if execution_status == "fallback":
            fallback_count += 1
            logical_status_counts["completed_by_system_fallback"] += 1
            if _action_ended_with_provider_timeout(action_log) or str(
                action_log.get("reason_code") or action_log.get("fallback_reason") or ""
            ).startswith(("timeout", "batch_deadline")):
                logical_timeout_fallback_count += 1
        elif execution_status == "canceled":
            logical_status_counts["canceled"] += 1
        elif execution_status in {"failed", "timed_out"}:
            logical_status_counts["failed"] += 1
        else:
            logical_status_counts["completed_by_model"] += 1

        lm_log = action_log.get("lm_log")
        attempts = lm_log.get("attempt_outcomes") if isinstance(lm_log, dict) else None
        safe_attempts = attempts if isinstance(attempts, list) else []
        retry_counts["provider_retry"] += max(0, len(safe_attempts) - 1)
        for attempt in safe_attempts:
            if not isinstance(attempt, dict):
                continue
            mapped = attempt_result_names.get(str(attempt.get("attempt_result") or ""))
            if mapped is not None:
                provider_attempt_counts[mapped] += 1
        invalid_attempts = lm_log.get("invalid_attempts") if isinstance(lm_log, dict) else None
        retry_counts["format_retry"] += max(
            0,
            len(invalid_attempts) if isinstance(invalid_attempts, list) else 0,
        )
        retry_counts["quality_rewrite"] += max(
            0,
            _non_negative_int(action_log.get("speech_quality_attempt_count")) - 1,
        )
    game_duration_ms = _duration_between(bundle.started_at, bundle.completed_at)
    return {
        "action_count": len(action_logs),
        "action_duration_ms_sum": sum(durations),
        "action_duration_ms_max": max(durations, default=None),
        "first_token_count": len(first_tokens),
        "first_token_ms_sum": sum(first_tokens),
        "first_token_ms_max": max(first_tokens, default=None),
        # Compatibility alias: timeout_count is explicitly a provider-attempt
        # count. One logical fallback may contain multiple timed-out attempts.
        "timeout_count": provider_attempt_counts["timeout"],
        "provider_timeout_count": provider_attempt_counts["timeout"],
        "logical_timeout_fallback_count": logical_timeout_fallback_count,
        "retry_count": retry_count,
        "fallback_count": fallback_count,
        "logical_action_counts": logical_status_counts,
        "provider_attempt_counts": provider_attempt_counts,
        "retry_counts": retry_counts,
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
    warnings = lineup_report.get("warnings", []) if isinstance(lineup_report, dict) else []
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


def _iter_action_logs(
    value: object,
    _seen_action_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    seen_action_ids = _seen_action_ids if _seen_action_ids is not None else set()
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("action"), str) and isinstance(value.get("lm_log"), dict):
            action_id = value["lm_log"].get("action_id")
            if not isinstance(action_id, str) or not action_id or action_id not in seen_action_ids:
                if isinstance(action_id, str) and action_id:
                    seen_action_ids.add(action_id)
                found.append(value)
        else:
            for nested in value.values():
                found.extend(_iter_action_logs(nested, seen_action_ids))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_action_logs(nested, seen_action_ids))
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
