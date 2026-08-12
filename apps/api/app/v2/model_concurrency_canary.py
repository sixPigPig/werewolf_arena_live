from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

from app.v2.model_client import build_model_request_payload
from app.v2.model_context_compaction import (
    build_known_events_v7_compaction_metadata,
    encode_known_events_v7,
)
from app.v2.model_context_contract import (
    KNOWN_EVENTS_SCHEMA_VERSION,
    MODEL_CONTEXT_SCHEMA_VERSION,
    PROMPT_TEMPLATE_VERSION,
)
from app.v2.model_context_selector import select_known_events_v13
from app.v2.model_parameters import (
    V2FrozenModelParametersError,
    validate_frozen_model_parameters,
)


E1_CANARY_SCHEMA_VERSION = 1
E1_CANARY_REPORT_SCHEMA_VERSION = 1
E1_CANARY_BUDGET_LEDGER_SCHEMA_VERSION = 1
E1_CANARY_ALLOWED_CAPS = (3, 4, 6)
E1_CANARY_ATTEMPTS_PER_CAP = 120
E1_CANARY_STAGE_WALL_SECONDS = 2 * 60 * 60
E1_CANARY_GLOBAL_REQUEST_LIMIT = 770
E1_CANARY_GLOBAL_WALL_SECONDS = 14 * 60 * 60
E1_CANARY_GLOBAL_CONFIGURED_OUTPUT_TOKENS = 6_400_000
E1_CANARY_GLOBAL_ACTUAL_TOKENS = 12_000_000
E1_CANARY_PINNED_CORPUS_SHA256 = "544587d04353c815561f044cf4cee4f060b8dda3d82fab976e3d602bd1f8390a"
E1_CANARY_PINNED_SCHEDULE_SHA256 = (
    "99d467bcf901f1ab09f2b55b284159334e8e2ae4474e3d5fb5b7e5f9e05f67ea"
)

DEFAULT_E1_CANARY_CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "v2-model-canary"
    / "seat_only_v13_workload_v1.json"
)

_RESPONSE_KINDS = frozenset({"boolean", "speech", "target"})
_SEAT_REF = re.compile(r"^seat_(?:[1-9]|1[0-2])$")
_PLAYER_REF_KEYS = frozenset(
    {
        "actor_id",
        "actor_player_id",
        "actor_ref",
        "current_speaker_ref",
        "hunter_ref",
        "owner_ref",
        "player_id",
        "player_ref",
        "reported_speaker_ref",
        "sheriff_ref",
        "speaker_ref",
        "target_player_id",
        "target_ref",
        "unknown_player_ref",
        "voter_ref",
    }
)
_PLAYER_REF_LIST_KEYS = frozenset(
    {
        "allowed_target_ids",
        "allowed_targets",
        "candidate_ids",
        "candidate_refs",
        "candidates",
        "eligible_voter_refs",
        "eliminated_player_refs",
        "ineligible_voter_refs",
        "leader_refs",
        "living_teammate_refs",
        "mentioned_player_refs",
        "remaining_speaker_refs",
        "scheduled_before_refs",
        "speech_order",
        "subject_refs",
        "teammate_refs",
    }
)
_FORBIDDEN_CONTEXT_MARKERS = (
    "v2_game_",
    "v2_run_",
    "v2_action_",
    "v2_model_",
    "system-player-",
    "profile_",
)
_CAP_SUMMARY_KEYS = frozenset(
    {
        "corpus_sha256",
        "schedule_sha256",
        "canary_run_id",
        "cap",
        "planned_attempt_count",
        "admitted_attempt_count",
        "pre_admission_failure_count",
        "batch_wall_ms",
        "queue",
        "active",
        "wall",
        "success_count",
        "success_rate",
        "output_budget_count",
        "hard_timeout_count",
        "http_429_or_5xx_count",
        "http_429_or_5xx_rate",
        "provider_in_flight_peak",
        "actual_total_tokens",
        "invariant_failures",
    }
)


class E1CanaryContractError(ValueError):
    """Stable fail-closed error for the offline E1 canary contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class E1CanaryModelSpec:
    provider: str
    model_id: str
    supports_thinking: bool
    parameters: dict[str, Any]
    quota_by_response_kind: dict[str, int]

    @property
    def attempt_count(self) -> int:
        return sum(self.quota_by_response_kind.values())

    @property
    def configured_max_tokens(self) -> int:
        value = self.parameters.get("max_tokens")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            _fail("canary_model_max_tokens_invalid")
        return value


@dataclass(frozen=True)
class E1CanaryContextSpec:
    context_id: str
    response_kind: str
    action_context: dict[str, Any]
    canonical_known_events_char_count: int
    compact_known_events_char_count: int
    canonical_known_events_sha256: str


@dataclass(frozen=True)
class E1CanaryAttemptPlan:
    attempt_id: str
    ordinal: int
    wave_index: int
    provider: str
    model_id: str
    supports_thinking: bool
    parameters: dict[str, Any]
    response_kind: str
    context_id: str
    action_context: dict[str, Any]
    request_payload_sha256: str
    configured_max_tokens: int

    def audit_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "ordinal": self.ordinal,
            "wave_index": self.wave_index,
            "provider": self.provider,
            "model_id": self.model_id,
            "response_kind": self.response_kind,
            "context_id": self.context_id,
            "request_payload_sha256": self.request_payload_sha256,
            "configured_max_tokens": self.configured_max_tokens,
        }


@dataclass(frozen=True)
class E1CanaryCorpus:
    corpus_id: str
    seed: int
    wave_size: int
    expected_attempt_count: int
    corpus_sha256: str
    schedule_sha256: str
    models: tuple[E1CanaryModelSpec, ...]
    contexts: tuple[E1CanaryContextSpec, ...]
    attempts: tuple[E1CanaryAttemptPlan, ...]

    @property
    def configured_output_tokens_per_cap(self) -> int:
        return sum(attempt.configured_max_tokens for attempt in self.attempts)


@dataclass(frozen=True)
class E1CanaryBudgetLedger:
    requests_used: int
    wall_seconds_used: int
    configured_output_tokens_used: int
    actual_total_tokens_used: int | None
    billing_authorization_id: str


@dataclass(frozen=True)
class E1CanaryAttemptObservation:
    attempt_id: str
    canary_run_id: str
    cap: int
    admitted: bool
    queue_wait_ms: int | None
    active_elapsed_ms: int | None
    wall_elapsed_ms: int | None
    outcome: str
    http_status: int | None = None
    provider_in_flight: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class E1CanaryDistribution:
    p50_ms: int | None
    p95_ms: int | None
    max_ms: int | None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "max_ms": self.max_ms,
        }


@dataclass(frozen=True)
class E1CanaryCapSummary:
    corpus_sha256: str
    schedule_sha256: str
    canary_run_id: str
    cap: int
    planned_attempt_count: int
    admitted_attempt_count: int
    pre_admission_failure_count: int
    batch_wall_ms: int
    queue: E1CanaryDistribution
    active: E1CanaryDistribution
    wall: E1CanaryDistribution
    success_count: int
    success_rate: float
    output_budget_count: int
    hard_timeout_count: int
    http_429_or_5xx_count: int
    http_429_or_5xx_rate: float
    provider_in_flight_peak: int | None
    actual_total_tokens: int | None
    invariant_failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus_sha256": self.corpus_sha256,
            "schedule_sha256": self.schedule_sha256,
            "canary_run_id": self.canary_run_id,
            "cap": self.cap,
            "planned_attempt_count": self.planned_attempt_count,
            "admitted_attempt_count": self.admitted_attempt_count,
            "pre_admission_failure_count": self.pre_admission_failure_count,
            "batch_wall_ms": self.batch_wall_ms,
            "queue": self.queue.as_dict(),
            "active": self.active.as_dict(),
            "wall": self.wall.as_dict(),
            "success_count": self.success_count,
            "success_rate": self.success_rate,
            "output_budget_count": self.output_budget_count,
            "hard_timeout_count": self.hard_timeout_count,
            "http_429_or_5xx_count": self.http_429_or_5xx_count,
            "http_429_or_5xx_rate": self.http_429_or_5xx_rate,
            "provider_in_flight_peak": self.provider_in_flight_peak,
            "actual_total_tokens": self.actual_total_tokens,
            "invariant_failures": list(self.invariant_failures),
        }


@dataclass(frozen=True)
class E1CanaryGoNoGoReport:
    corpus_sha256: str
    schedule_sha256: str
    baseline_cap: int
    candidate_cap: int
    passed: bool
    checks: dict[str, dict[str, Any]]
    baseline_summary: dict[str, Any] | None
    candidate_summary: dict[str, Any] | None
    skipped_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": E1_CANARY_REPORT_SCHEMA_VERSION,
            "corpus_sha256": self.corpus_sha256,
            "schedule_sha256": self.schedule_sha256,
            "baseline_cap": self.baseline_cap,
            "candidate_cap": self.candidate_cap,
            "passed": self.passed,
            "checks": deepcopy(self.checks),
            "baseline_summary": deepcopy(self.baseline_summary),
            "candidate_summary": deepcopy(self.candidate_summary),
            "skipped_reason": self.skipped_reason,
        }


def load_e1_canary_corpus(
    path: Path = DEFAULT_E1_CANARY_CORPUS_PATH,
) -> E1CanaryCorpus:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise E1CanaryContractError("canary_corpus_unreadable") from exc
    if not isinstance(raw, dict):
        _fail("canary_corpus_shape")
    expected_keys = {
        "schema_version",
        "corpus_id",
        "seed",
        "wave_size",
        "expected_attempt_count",
        "models",
        "known_event_corpora",
        "contexts",
    }
    if set(raw) != expected_keys or raw.get("schema_version") != E1_CANARY_SCHEMA_VERSION:
        _fail("canary_corpus_contract_unsupported")
    contexts_value = raw.get("contexts")
    if isinstance(contexts_value, list) and any(
        isinstance(item, dict)
        and isinstance(item.get("action_context"), dict)
        and (
            item["action_context"].get("model_context_schema_version")
            != MODEL_CONTEXT_SCHEMA_VERSION
            or item["action_context"].get("prompt_template_version") != PROMPT_TEMPLATE_VERSION
        )
        for item in contexts_value
    ):
        _fail("canary_corpus_model_context_contract_unsupported")

    corpus_id = _non_empty_string(raw.get("corpus_id"), "canary_corpus_id_invalid")
    seed = _positive_int(raw.get("seed"), "canary_seed_invalid")
    wave_size = _positive_int(raw.get("wave_size"), "canary_wave_size_invalid")
    expected_attempt_count = _positive_int(
        raw.get("expected_attempt_count"),
        "canary_expected_attempt_count_invalid",
    )
    if expected_attempt_count != E1_CANARY_ATTEMPTS_PER_CAP:
        _fail("canary_attempt_count_not_120")
    if expected_attempt_count % wave_size != 0:
        _fail("canary_wave_size_not_divisible")

    models = _parse_models(raw.get("models"))
    known_event_corpora = _parse_known_event_corpora(raw.get("known_event_corpora"))
    contexts = _parse_contexts(raw.get("contexts"), known_event_corpora)
    if sum(model.attempt_count for model in models) != expected_attempt_count:
        _fail("canary_model_quota_total_mismatch")

    corpus_sha256 = _sha256_json(raw)
    attempts = _build_attempt_schedule(
        seed=seed,
        wave_size=wave_size,
        models=models,
        contexts=contexts,
    )
    if len(attempts) != expected_attempt_count:
        _fail("canary_schedule_count_mismatch")
    schedule_sha256 = _sha256_json([attempt.audit_dict() for attempt in attempts])
    return E1CanaryCorpus(
        corpus_id=corpus_id,
        seed=seed,
        wave_size=wave_size,
        expected_attempt_count=expected_attempt_count,
        corpus_sha256=corpus_sha256,
        schedule_sha256=schedule_sha256,
        models=models,
        contexts=contexts,
        attempts=attempts,
    )


def build_e1_canary_dry_run_report(
    corpus: E1CanaryCorpus,
    *,
    caps: Sequence[int] = E1_CANARY_ALLOWED_CAPS,
) -> dict[str, Any]:
    normalized_caps = _normalized_caps(caps)
    model_counts = Counter(attempt.model_id for attempt in corpus.attempts)
    kind_counts = Counter(attempt.response_kind for attempt in corpus.attempts)
    configured_per_cap = corpus.configured_output_tokens_per_cap
    return {
        "schema_version": E1_CANARY_REPORT_SCHEMA_VERSION,
        "mode": "dry_run",
        "live_execution_implemented": False,
        "http_client_created": False,
        "external_model_requests": 0,
        "database_accessed": False,
        "database_writes": 0,
        "tts_capability_enabled": False,
        "corpus_id": corpus.corpus_id,
        "corpus_sha256": corpus.corpus_sha256,
        "schedule_sha256": corpus.schedule_sha256,
        "seed": corpus.seed,
        "wave_size": corpus.wave_size,
        "wave_count": corpus.expected_attempt_count // corpus.wave_size,
        "attempts_per_cap": corpus.expected_attempt_count,
        "caps": list(normalized_caps),
        "cap_6_requires_cap_4_pass": 6 in normalized_caps,
        "model_context_contract": {
            "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "known_events_schema_version": KNOWN_EVENTS_SCHEMA_VERSION,
        },
        "model_attempt_counts": dict(sorted(model_counts.items())),
        "response_kind_attempt_counts": dict(sorted(kind_counts.items())),
        "configured_output_tokens_per_cap": configured_per_cap,
        "configured_output_tokens_for_plan": configured_per_cap * len(normalized_caps),
        "stage_limits": {
            "requests": E1_CANARY_ATTEMPTS_PER_CAP,
            "wall_seconds": E1_CANARY_STAGE_WALL_SECONDS,
        },
        "global_limits": {
            "requests": E1_CANARY_GLOBAL_REQUEST_LIMIT,
            "wall_seconds": E1_CANARY_GLOBAL_WALL_SECONDS,
            "configured_output_tokens": E1_CANARY_GLOBAL_CONFIGURED_OUTPUT_TOKENS,
            "actual_total_tokens": E1_CANARY_GLOBAL_ACTUAL_TOKENS,
        },
        "contexts": [
            {
                "context_id": context.context_id,
                "response_kind": context.response_kind,
                "canonical_known_events_char_count": (context.canonical_known_events_char_count),
                "compact_known_events_char_count": context.compact_known_events_char_count,
                "canonical_known_events_sha256": context.canonical_known_events_sha256,
            }
            for context in corpus.contexts
        ],
        "attempts": [attempt.audit_dict() for attempt in corpus.attempts],
    }


def load_e1_canary_budget_ledger(path: Path) -> E1CanaryBudgetLedger:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise E1CanaryContractError("canary_budget_ledger_unreadable") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "requests_used",
        "wall_seconds_used",
        "configured_output_tokens_used",
        "actual_total_tokens_used",
        "billing_authorization_id",
    }:
        _fail("canary_budget_ledger_shape")
    if raw.get("schema_version") != E1_CANARY_BUDGET_LEDGER_SCHEMA_VERSION:
        _fail("canary_budget_ledger_version_unsupported")
    actual_tokens = raw.get("actual_total_tokens_used")
    if actual_tokens is not None:
        actual_tokens = _non_negative_int(
            actual_tokens,
            "canary_budget_actual_tokens_invalid",
        )
    return E1CanaryBudgetLedger(
        requests_used=_non_negative_int(
            raw.get("requests_used"),
            "canary_budget_requests_invalid",
        ),
        wall_seconds_used=_non_negative_int(
            raw.get("wall_seconds_used"),
            "canary_budget_wall_invalid",
        ),
        configured_output_tokens_used=_non_negative_int(
            raw.get("configured_output_tokens_used"),
            "canary_budget_configured_tokens_invalid",
        ),
        actual_total_tokens_used=actual_tokens,
        billing_authorization_id=_non_empty_string(
            raw.get("billing_authorization_id"),
            "canary_budget_billing_authorization_missing",
        ),
    )


def validate_e1_canary_live_prerequisites(
    corpus: E1CanaryCorpus,
    *,
    caps: Sequence[int],
    confirm_external_model_calls: bool,
    confirm_billing_authorized: bool,
    ledger: E1CanaryBudgetLedger,
    cap4_report: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Validate future live execution without creating any network client.

    Cap 6 intentionally has no external-report authorization path. A future live
    runner must own cap 3/4 observations and the cap 6 transition in one process.
    """

    if (
        corpus.corpus_sha256 != E1_CANARY_PINNED_CORPUS_SHA256
        or corpus.schedule_sha256 != E1_CANARY_PINNED_SCHEDULE_SHA256
    ):
        _fail("canary_live_corpus_not_pinned")
    _validate_corpus_schedule_integrity(
        corpus,
        code="canary_live_corpus_integrity_invalid",
    )
    normalized_caps = _normalized_caps(caps)
    if 6 in normalized_caps:
        _fail("canary_cap6_requires_same_process_cap4_result")
    if normalized_caps not in {(3,), (3, 4)}:
        _fail("canary_live_cap_plan_invalid")
    if cap4_report is not None:
        _fail("canary_external_cap4_report_not_authoritative")
    if not confirm_external_model_calls:
        _fail("canary_external_model_calls_not_confirmed")
    if not confirm_billing_authorized:
        _fail("canary_billing_not_confirmed")
    _validate_budget_ledger_instance(ledger)

    planned_requests = corpus.expected_attempt_count * len(normalized_caps)
    planned_wall_seconds = E1_CANARY_STAGE_WALL_SECONDS * len(normalized_caps)
    planned_configured_tokens = corpus.configured_output_tokens_per_cap * len(normalized_caps)
    if ledger.requests_used + planned_requests > E1_CANARY_GLOBAL_REQUEST_LIMIT:
        _fail("canary_global_request_budget_exceeded")
    if ledger.wall_seconds_used + planned_wall_seconds > E1_CANARY_GLOBAL_WALL_SECONDS:
        _fail("canary_global_wall_budget_exceeded")
    if (
        ledger.configured_output_tokens_used + planned_configured_tokens
        > E1_CANARY_GLOBAL_CONFIGURED_OUTPUT_TOKENS
    ):
        _fail("canary_global_configured_output_budget_exceeded")
    if (
        ledger.actual_total_tokens_used is not None
        and ledger.actual_total_tokens_used >= E1_CANARY_GLOBAL_ACTUAL_TOKENS
    ):
        _fail("canary_global_actual_token_budget_exhausted")
    return {
        "planned_requests": planned_requests,
        "planned_wall_seconds": planned_wall_seconds,
        "planned_configured_output_tokens": planned_configured_tokens,
        "remaining_requests_after_reservation": (
            E1_CANARY_GLOBAL_REQUEST_LIMIT - ledger.requests_used - planned_requests
        ),
        "remaining_wall_seconds_after_reservation": (
            E1_CANARY_GLOBAL_WALL_SECONDS - ledger.wall_seconds_used - planned_wall_seconds
        ),
        "remaining_configured_output_tokens_after_reservation": (
            E1_CANARY_GLOBAL_CONFIGURED_OUTPUT_TOKENS
            - ledger.configured_output_tokens_used
            - planned_configured_tokens
        ),
    }


def _validate_budget_ledger_instance(ledger: E1CanaryBudgetLedger) -> None:
    if not isinstance(ledger, E1CanaryBudgetLedger):
        _fail("canary_budget_ledger_invalid")
    _non_negative_int(ledger.requests_used, "canary_budget_requests_invalid")
    _non_negative_int(ledger.wall_seconds_used, "canary_budget_wall_invalid")
    _non_negative_int(
        ledger.configured_output_tokens_used,
        "canary_budget_configured_tokens_invalid",
    )
    if ledger.actual_total_tokens_used is not None:
        _non_negative_int(
            ledger.actual_total_tokens_used,
            "canary_budget_actual_tokens_invalid",
        )
    _non_empty_string(
        ledger.billing_authorization_id,
        "canary_budget_billing_authorization_missing",
    )


def summarize_e1_canary_cap(
    *,
    corpus: E1CanaryCorpus,
    cap: int,
    observations: Sequence[E1CanaryAttemptObservation],
    batch_wall_ms: int,
    invariant_failures: Iterable[str] = (),
) -> E1CanaryCapSummary:
    _require_cap(cap)
    _validate_corpus_schedule_integrity(
        corpus,
        code="canary_corpus_attempt_plan_invalid",
    )
    if batch_wall_ms < 0:
        _fail("canary_batch_wall_invalid")
    planned_attempt_count = corpus.expected_attempt_count
    if planned_attempt_count != E1_CANARY_ATTEMPTS_PER_CAP:
        _fail("canary_planned_attempt_count_not_120")
    if len(corpus.attempts) != planned_attempt_count:
        _fail("canary_corpus_attempt_plan_invalid")
    if any(observation.cap != cap for observation in observations):
        _fail("canary_observation_cap_mismatch")
    attempt_ids = [observation.attempt_id for observation in observations]
    if len(attempt_ids) != len(set(attempt_ids)):
        _fail("canary_observation_attempt_duplicate")
    expected_attempt_ids = {attempt.attempt_id for attempt in corpus.attempts}
    if len(expected_attempt_ids) != planned_attempt_count:
        _fail("canary_corpus_attempt_plan_invalid")
    if set(attempt_ids) != expected_attempt_ids or len(attempt_ids) != len(expected_attempt_ids):
        _fail("canary_observation_attempt_set_mismatch")
    run_ids = [observation.canary_run_id for observation in observations]
    if (
        not run_ids
        or any(not isinstance(run_id, str) or not run_id.strip() for run_id in run_ids)
        or len(set(run_ids)) != 1
    ):
        _fail("canary_observation_run_id_invalid")
    canary_run_id = run_ids[0].strip()

    admitted = [observation for observation in observations if observation.admitted]
    if len(admitted) > planned_attempt_count:
        _fail("canary_observation_admitted_overflow")
    for observation in admitted:
        if (
            observation.queue_wait_ms is None
            or observation.active_elapsed_ms is None
            or observation.wall_elapsed_ms is None
            or min(
                observation.queue_wait_ms,
                observation.active_elapsed_ms,
                observation.wall_elapsed_ms,
            )
            < 0
        ):
            _fail("canary_admitted_timing_missing")
        if (
            not isinstance(observation.provider_in_flight, int)
            or isinstance(observation.provider_in_flight, bool)
            or not 1 <= observation.provider_in_flight <= cap
        ):
            _fail("canary_provider_in_flight_invalid")
        if observation.wall_elapsed_ms < observation.active_elapsed_ms:
            _fail("canary_wall_elapsed_less_than_active")
    denominator = len(admitted)
    success_count = sum(item.outcome == "success" for item in admitted)
    http_error_count = sum(
        item.http_status == 429
        or (isinstance(item.http_status, int) and 500 <= item.http_status <= 599)
        for item in admitted
    )
    token_values = [item.total_tokens for item in admitted]
    actual_total_tokens = (
        sum(int(value) for value in token_values if value is not None)
        if token_values and all(value is not None for value in token_values)
        else None
    )
    in_flight_values = [
        int(item.provider_in_flight) for item in admitted if item.provider_in_flight is not None
    ]
    return E1CanaryCapSummary(
        corpus_sha256=corpus.corpus_sha256,
        schedule_sha256=corpus.schedule_sha256,
        canary_run_id=canary_run_id,
        cap=cap,
        planned_attempt_count=planned_attempt_count,
        admitted_attempt_count=denominator,
        pre_admission_failure_count=len(observations) - denominator,
        batch_wall_ms=batch_wall_ms,
        queue=_distribution(int(item.queue_wait_ms) for item in admitted),
        active=_distribution(int(item.active_elapsed_ms) for item in admitted),
        wall=_distribution(int(item.wall_elapsed_ms) for item in admitted),
        success_count=success_count,
        success_rate=success_count / denominator if denominator else 0.0,
        output_budget_count=sum(item.outcome == "output_budget" for item in admitted),
        hard_timeout_count=sum(item.outcome == "hard_timeout" for item in admitted),
        http_429_or_5xx_count=http_error_count,
        http_429_or_5xx_rate=http_error_count / denominator if denominator else 0.0,
        provider_in_flight_peak=max(in_flight_values) if in_flight_values else None,
        actual_total_tokens=actual_total_tokens,
        invariant_failures=tuple(sorted(set(invariant_failures))),
    )


def compare_e1_canary_caps(
    *,
    corpus: E1CanaryCorpus,
    baseline: E1CanaryCapSummary,
    candidate: E1CanaryCapSummary,
) -> E1CanaryGoNoGoReport:
    _validate_corpus_schedule_integrity(
        corpus,
        code="canary_comparison_corpus_integrity_invalid",
    )
    if not isinstance(baseline, E1CanaryCapSummary) or not isinstance(
        candidate, E1CanaryCapSummary
    ):
        _fail("canary_comparison_summary_invalid")
    if (baseline.cap, candidate.cap) not in {(3, 4), (4, 6)}:
        _fail("canary_comparison_cap_pair_invalid")
    if any(
        summary.corpus_sha256 != corpus.corpus_sha256
        or summary.schedule_sha256 != corpus.schedule_sha256
        for summary in (baseline, candidate)
    ):
        _fail("canary_comparison_summary_not_bound_to_corpus")
    _validate_cap_summary_binding(corpus, baseline)
    _validate_cap_summary_binding(corpus, candidate)

    complete = (
        baseline.admitted_attempt_count == E1_CANARY_ATTEMPTS_PER_CAP
        and candidate.admitted_attempt_count == E1_CANARY_ATTEMPTS_PER_CAP
    )
    queue_check = _improvement_check(
        baseline.queue.p95_ms,
        candidate.queue.p95_ms,
        minimum=0.30,
    )
    batch_check = _improvement_check(
        baseline.batch_wall_ms,
        candidate.batch_wall_ms,
        minimum=0.15,
    )
    active_check = _regression_check(
        baseline.active.p95_ms,
        candidate.active.p95_ms,
        maximum=0.10,
    )
    success_drop = baseline.success_rate - candidate.success_rate
    http_increment = candidate.http_429_or_5xx_rate - baseline.http_429_or_5xx_rate
    invariant_passed = not baseline.invariant_failures and not candidate.invariant_failures
    checks = {
        "complete_120_admitted_each": {
            "passed": complete,
            "baseline": baseline.admitted_attempt_count,
            "candidate": candidate.admitted_attempt_count,
            "required": E1_CANARY_ATTEMPTS_PER_CAP,
        },
        "queue_p95_improvement": queue_check,
        "batch_wall_improvement": batch_check,
        "active_p95_regression": active_check,
        "success_rate_drop": {
            "passed": success_drop <= 0.01 + 1e-12,
            "observed": success_drop,
            "maximum": 0.01,
        },
        "http_429_or_5xx_increment": {
            "passed": http_increment <= 0.01 + 1e-12,
            "observed": http_increment,
            "maximum": 0.01,
        },
        "runtime_invariants": {
            "passed": invariant_passed,
            "baseline_failures": list(baseline.invariant_failures),
            "candidate_failures": list(candidate.invariant_failures),
        },
    }
    passed = all(bool(check["passed"]) for check in checks.values())
    return E1CanaryGoNoGoReport(
        corpus_sha256=corpus.corpus_sha256,
        schedule_sha256=corpus.schedule_sha256,
        baseline_cap=baseline.cap,
        candidate_cap=candidate.cap,
        passed=passed,
        checks=checks,
        baseline_summary=baseline.as_dict(),
        candidate_summary=candidate.as_dict(),
    )


def build_e1_cap6_skipped_report(
    *,
    corpus: E1CanaryCorpus,
    cap4_report: E1CanaryGoNoGoReport,
) -> E1CanaryGoNoGoReport:
    if (
        cap4_report.corpus_sha256 != corpus.corpus_sha256
        or cap4_report.schedule_sha256 != corpus.schedule_sha256
        or cap4_report.baseline_cap != 3
        or cap4_report.candidate_cap != 4
    ):
        _fail("canary_cap4_report_invalid")
    try:
        baseline = _cap_summary_from_report(
            corpus,
            cap4_report.baseline_summary,
            expected_cap=3,
            code="canary_cap4_report_invalid",
        )
        candidate = _cap_summary_from_report(
            corpus,
            cap4_report.candidate_summary,
            expected_cap=4,
            code="canary_cap4_report_invalid",
        )
        canonical = compare_e1_canary_caps(
            corpus=corpus,
            baseline=baseline,
            candidate=candidate,
        )
    except E1CanaryContractError as exc:
        raise E1CanaryContractError("canary_cap4_report_invalid") from exc
    if cap4_report.as_dict() != canonical.as_dict():
        _fail("canary_cap4_report_invalid")
    if cap4_report.passed:
        _fail("canary_cap6_not_skipped_after_cap4_pass")
    return E1CanaryGoNoGoReport(
        corpus_sha256=corpus.corpus_sha256,
        schedule_sha256=corpus.schedule_sha256,
        baseline_cap=4,
        candidate_cap=6,
        passed=False,
        checks={},
        baseline_summary=deepcopy(cap4_report.candidate_summary),
        candidate_summary=None,
        skipped_reason="cap4_go_no_go_failed",
    )


def _parse_models(value: Any) -> tuple[E1CanaryModelSpec, ...]:
    if not isinstance(value, list) or not value:
        _fail("canary_models_shape")
    output: list[E1CanaryModelSpec] = []
    model_ids: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "provider",
            "model_id",
            "supports_thinking",
            "parameters",
            "quota_by_response_kind",
        }:
            _fail("canary_model_shape")
        provider = _non_empty_string(raw.get("provider"), "canary_model_provider_invalid")
        if provider != "agent_plan":
            _fail("canary_model_provider_not_agent_plan")
        model_id = _non_empty_string(raw.get("model_id"), "canary_model_id_invalid")
        if model_id in model_ids:
            _fail("canary_model_id_duplicate")
        model_ids.add(model_id)
        supports_thinking = raw.get("supports_thinking")
        if not isinstance(supports_thinking, bool):
            _fail("canary_model_supports_thinking_invalid")
        try:
            parameters = validate_frozen_model_parameters(
                raw.get("parameters"),
                provider=provider,
                model_id=model_id,
                supports_thinking=supports_thinking,
            )
        except V2FrozenModelParametersError as exc:
            raise E1CanaryContractError("canary_model_parameters_invalid") from exc
        raw_quota = raw.get("quota_by_response_kind")
        if not isinstance(raw_quota, dict) or set(raw_quota) != _RESPONSE_KINDS:
            _fail("canary_model_quota_shape")
        quota = {
            kind: _non_negative_int(
                raw_quota.get(kind),
                "canary_model_quota_invalid",
            )
            for kind in sorted(_RESPONSE_KINDS)
        }
        if sum(quota.values()) <= 0:
            _fail("canary_model_quota_empty")
        output.append(
            E1CanaryModelSpec(
                provider=provider,
                model_id=model_id,
                supports_thinking=supports_thinking,
                parameters=parameters,
                quota_by_response_kind=quota,
            )
        )
    return tuple(output)


def _parse_known_event_corpora(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not value:
        _fail("canary_known_event_corpora_shape")
    output: dict[str, dict[str, Any]] = {}
    for corpus_ref, canonical in value.items():
        if not isinstance(corpus_ref, str) or not corpus_ref:
            _fail("canary_known_event_corpus_ref_invalid")
        if not isinstance(canonical, dict):
            _fail("canary_known_event_corpus_shape")
        _validate_seat_only_context(canonical)
        output[corpus_ref] = {
            "canonical": deepcopy(canonical),
        }
    return output


def _parse_contexts(
    value: Any,
    known_event_corpora: dict[str, dict[str, Any]],
) -> tuple[E1CanaryContextSpec, ...]:
    if not isinstance(value, list) or not value:
        _fail("canary_contexts_shape")
    output: list[E1CanaryContextSpec] = []
    context_ids: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "context_id",
            "response_kind",
            "known_events_ref",
            "action_context",
        }:
            _fail("canary_context_shape")
        context_id = _non_empty_string(raw.get("context_id"), "canary_context_id_invalid")
        if context_id in context_ids:
            _fail("canary_context_id_duplicate")
        context_ids.add(context_id)
        response_kind = _non_empty_string(
            raw.get("response_kind"),
            "canary_context_response_kind_invalid",
        )
        if response_kind not in _RESPONSE_KINDS:
            _fail("canary_context_response_kind_invalid")
        known_events_ref = _non_empty_string(
            raw.get("known_events_ref"),
            "canary_context_known_events_ref_invalid",
        )
        known_events = known_event_corpora.get(known_events_ref)
        if known_events is None:
            _fail("canary_context_known_events_ref_missing")
        action_context = raw.get("action_context")
        if not isinstance(action_context, dict):
            _fail("canary_action_context_shape")
        action_context = deepcopy(action_context)
        if "known_events" in action_context:
            _fail("canary_action_context_known_events_embedded")
        if (
            action_context.get("model_context_schema_version") != MODEL_CONTEXT_SCHEMA_VERSION
            or action_context.get("prompt_template_version") != PROMPT_TEMPLATE_VERSION
        ):
            _fail("canary_action_context_contract_unsupported")
        canonical_source = known_events["canonical"]
        task = action_context.get("task")
        state = action_context.get("state")
        if not isinstance(task, dict) or not isinstance(state, dict):
            _fail("canary_action_context_task_state_invalid")
        actor_ref = task.get("actor_id")
        current_round_no = state.get("current_round_no", state.get("round_no"))
        if not isinstance(actor_ref, str) or not actor_ref:
            _fail("canary_action_context_actor_ref_invalid")
        if (
            not isinstance(current_round_no, int)
            or isinstance(current_round_no, bool)
            or current_round_no <= 0
        ):
            _fail("canary_action_context_round_invalid")
        candidates_value = action_context.get("candidates")
        candidates = candidates_value if isinstance(candidates_value, list) else []
        candidate_refs = [
            candidate["player_id"]
            for candidate in candidates
            if isinstance(candidate, dict) and isinstance(candidate.get("player_id"), str)
        ]
        selection = select_known_events_v13(
            canonical_source.get("events", []),
            actor_ref=actor_ref,
            current_round_no=current_round_no,
            candidate_refs=candidate_refs,
            model_view=canonical_source,
        )
        canonical_known_events = {
            "schema_version": canonical_source.get("schema_version"),
            "events": selection.events,
            "questions": [],
            "relations": [],
        }
        compact_known_events = encode_known_events_v7(canonical_known_events)
        compaction_metadata = build_known_events_v7_compaction_metadata(
            canonical_known_events,
            compact_known_events,
        )
        action_context["known_events"] = compact_known_events
        response = action_context.get("response")
        if not isinstance(response, dict) or response.get("kind") != response_kind:
            _fail("canary_action_context_response_mismatch")
        _validate_seat_only_context(action_context)
        output.append(
            E1CanaryContextSpec(
                context_id=context_id,
                response_kind=response_kind,
                action_context=action_context,
                canonical_known_events_char_count=int(
                    compaction_metadata["canonical_serialized_char_count"]
                ),
                compact_known_events_char_count=int(
                    compaction_metadata["compact_serialized_char_count"]
                ),
                canonical_known_events_sha256=str(compaction_metadata["canonical_sha256"]),
            )
        )
    if {context.response_kind for context in output} != _RESPONSE_KINDS:
        _fail("canary_context_response_kind_coverage")
    return tuple(output)


def _build_attempt_schedule(
    *,
    seed: int,
    wave_size: int,
    models: tuple[E1CanaryModelSpec, ...],
    contexts: tuple[E1CanaryContextSpec, ...],
) -> tuple[E1CanaryAttemptPlan, ...]:
    contexts_by_kind = {
        kind: tuple(context for context in contexts if context.response_kind == kind)
        for kind in _RESPONSE_KINDS
    }
    pending: list[dict[str, Any]] = []
    for model in models:
        for response_kind in sorted(_RESPONSE_KINDS):
            kind_contexts = contexts_by_kind[response_kind]
            for quota_index in range(model.quota_by_response_kind[response_kind]):
                context = kind_contexts[quota_index % len(kind_contexts)]
                pending.append(
                    {
                        "model": model,
                        "response_kind": response_kind,
                        "context": context,
                        "quota_index": quota_index,
                        "sort_key": hashlib.sha256(
                            (
                                f"{seed}:{model.model_id}:{response_kind}:"
                                f"{quota_index}:{context.context_id}"
                            ).encode()
                        ).hexdigest(),
                    }
                )
    pending.sort(key=lambda item: str(item["sort_key"]))
    output: list[E1CanaryAttemptPlan] = []
    for zero_based_ordinal, item in enumerate(pending):
        model = item["model"]
        context = item["context"]
        assert isinstance(model, E1CanaryModelSpec)
        assert isinstance(context, E1CanaryContextSpec)
        request_payload = build_model_request_payload(
            context.action_context,
            decision=True,
            model_provider=model.provider,
            model_id=model.model_id,
            parameters=model.parameters,
            supports_thinking=model.supports_thinking,
            supports_strict_json_schema=False,
        )
        ordinal = zero_based_ordinal + 1
        output.append(
            E1CanaryAttemptPlan(
                attempt_id=f"e1_canary_{ordinal:03d}",
                ordinal=ordinal,
                wave_index=zero_based_ordinal // wave_size + 1,
                provider=model.provider,
                model_id=model.model_id,
                supports_thinking=model.supports_thinking,
                parameters=deepcopy(model.parameters),
                response_kind=str(item["response_kind"]),
                context_id=context.context_id,
                action_context=deepcopy(context.action_context),
                request_payload_sha256=_sha256_json(request_payload),
                configured_max_tokens=model.configured_max_tokens,
            )
        )
    return tuple(output)


def _validate_seat_only_context(value: Any, *, key: str | None = None) -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                _fail("canary_context_non_string_key")
            _validate_seat_only_context(child, key=child_key)
        return
    if isinstance(value, list):
        for child in value:
            _validate_seat_only_context(child, key=key)
        return
    if isinstance(value, str):
        if any(marker in value for marker in _FORBIDDEN_CONTEXT_MARKERS):
            _fail("canary_context_contains_real_identifier_marker")
        if _is_player_ref_key(key) and _SEAT_REF.fullmatch(value) is None:
            _fail("canary_context_player_ref_not_seat_only")
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    _fail("canary_context_non_json_value")


def _is_player_ref_key(key: str | None) -> bool:
    if key is None:
        return False
    return (
        key in _PLAYER_REF_KEYS
        or key in _PLAYER_REF_LIST_KEYS
        or key.endswith("_player_id")
        or key.endswith("_player_ids")
        or key.endswith("_player_ref")
        or key.endswith("_player_refs")
        or key.endswith("_speech_order")
    )


def _validate_cap_summary_binding(
    corpus: E1CanaryCorpus,
    summary: E1CanaryCapSummary,
) -> None:
    try:
        parsed = _cap_summary_from_report(
            corpus,
            summary.as_dict(),
            expected_cap=summary.cap,
            code="canary_comparison_summary_invalid",
        )
    except (AttributeError, TypeError, E1CanaryContractError) as exc:
        raise E1CanaryContractError("canary_comparison_summary_invalid") from exc
    if parsed != summary:
        _fail("canary_comparison_summary_invalid")


def _validate_corpus_schedule_integrity(
    corpus: E1CanaryCorpus,
    *,
    code: str,
) -> None:
    try:
        if (
            corpus.expected_attempt_count != E1_CANARY_ATTEMPTS_PER_CAP
            or len(corpus.attempts) != E1_CANARY_ATTEMPTS_PER_CAP
            or len({attempt.attempt_id for attempt in corpus.attempts})
            != E1_CANARY_ATTEMPTS_PER_CAP
        ):
            _fail(code)
        for attempt in corpus.attempts:
            _validate_seat_only_context(attempt.action_context)
            request_payload = build_model_request_payload(
                attempt.action_context,
                decision=True,
                model_provider=attempt.provider,
                model_id=attempt.model_id,
                parameters=attempt.parameters,
                supports_thinking=attempt.supports_thinking,
                supports_strict_json_schema=False,
            )
            if _sha256_json(
                request_payload
            ) != attempt.request_payload_sha256 or attempt.configured_max_tokens != _positive_int(
                attempt.parameters.get("max_tokens"),
                code,
            ):
                _fail(code)
        if (
            _sha256_json([attempt.audit_dict() for attempt in corpus.attempts])
            != corpus.schedule_sha256
        ):
            _fail(code)
    except E1CanaryContractError as exc:
        if exc.code == code:
            raise
        raise E1CanaryContractError(code) from exc
    except Exception as exc:
        raise E1CanaryContractError(code) from exc


def _cap_summary_from_report(
    corpus: E1CanaryCorpus,
    value: Any,
    *,
    expected_cap: int,
    code: str,
) -> E1CanaryCapSummary:
    if not isinstance(value, dict) or set(value) != _CAP_SUMMARY_KEYS:
        _fail(code)
    if (
        value.get("corpus_sha256") != corpus.corpus_sha256
        or value.get("schedule_sha256") != corpus.schedule_sha256
        or value.get("cap") != expected_cap
    ):
        _fail(code)
    planned = _non_negative_int(value.get("planned_attempt_count"), code)
    admitted = _non_negative_int(value.get("admitted_attempt_count"), code)
    pre_admission_failures = _non_negative_int(value.get("pre_admission_failure_count"), code)
    if (
        planned != E1_CANARY_ATTEMPTS_PER_CAP
        or admitted > planned
        or pre_admission_failures != planned - admitted
    ):
        _fail(code)
    batch_wall_ms = _non_negative_int(value.get("batch_wall_ms"), code)
    queue = _distribution_from_report(value.get("queue"), admitted=admitted, code=code)
    active = _distribution_from_report(value.get("active"), admitted=admitted, code=code)
    wall = _distribution_from_report(value.get("wall"), admitted=admitted, code=code)
    if admitted and (
        wall.p50_ms < active.p50_ms or wall.p95_ms < active.p95_ms or wall.max_ms < active.max_ms
    ):
        _fail(code)

    success_count = _non_negative_int(value.get("success_count"), code)
    output_budget_count = _non_negative_int(value.get("output_budget_count"), code)
    hard_timeout_count = _non_negative_int(value.get("hard_timeout_count"), code)
    http_error_count = _non_negative_int(value.get("http_429_or_5xx_count"), code)
    if (
        success_count + output_budget_count + hard_timeout_count > admitted
        or http_error_count > admitted
    ):
        _fail(code)
    success_rate = _report_rate(value.get("success_rate"), code)
    http_error_rate = _report_rate(value.get("http_429_or_5xx_rate"), code)
    expected_success_rate = success_count / admitted if admitted else 0.0
    expected_http_error_rate = http_error_count / admitted if admitted else 0.0
    if not math.isclose(success_rate, expected_success_rate, abs_tol=1e-12) or not math.isclose(
        http_error_rate,
        expected_http_error_rate,
        abs_tol=1e-12,
    ):
        _fail(code)

    provider_peak = value.get("provider_in_flight_peak")
    if admitted:
        provider_peak = _positive_int(provider_peak, code)
        if provider_peak > expected_cap:
            _fail(code)
    elif provider_peak is not None:
        _fail(code)
    actual_total_tokens = value.get("actual_total_tokens")
    if actual_total_tokens is not None:
        actual_total_tokens = _non_negative_int(actual_total_tokens, code)
    failures = value.get("invariant_failures")
    if (
        not isinstance(failures, list)
        or any(not isinstance(item, str) or not item for item in failures)
        or failures != sorted(set(failures))
    ):
        _fail(code)

    return E1CanaryCapSummary(
        corpus_sha256=corpus.corpus_sha256,
        schedule_sha256=corpus.schedule_sha256,
        canary_run_id=_non_empty_string(value.get("canary_run_id"), code),
        cap=expected_cap,
        planned_attempt_count=planned,
        admitted_attempt_count=admitted,
        pre_admission_failure_count=pre_admission_failures,
        batch_wall_ms=batch_wall_ms,
        queue=queue,
        active=active,
        wall=wall,
        success_count=success_count,
        success_rate=success_rate,
        output_budget_count=output_budget_count,
        hard_timeout_count=hard_timeout_count,
        http_429_or_5xx_count=http_error_count,
        http_429_or_5xx_rate=http_error_rate,
        provider_in_flight_peak=provider_peak,
        actual_total_tokens=actual_total_tokens,
        invariant_failures=tuple(failures),
    )


def _distribution_from_report(
    value: Any,
    *,
    admitted: int,
    code: str,
) -> E1CanaryDistribution:
    if not isinstance(value, dict) or set(value) != {"p50_ms", "p95_ms", "max_ms"}:
        _fail(code)
    raw_values = (value.get("p50_ms"), value.get("p95_ms"), value.get("max_ms"))
    if not admitted:
        if raw_values != (None, None, None):
            _fail(code)
        return E1CanaryDistribution(None, None, None)
    parsed = tuple(_non_negative_int(item, code) for item in raw_values)
    if not parsed[0] <= parsed[1] <= parsed[2]:
        _fail(code)
    return E1CanaryDistribution(*parsed)


def _report_rate(value: Any, code: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0.0 <= float(value) <= 1.0
    ):
        _fail(code)
    return float(value)


def _normalized_caps(caps: Sequence[int]) -> tuple[int, ...]:
    if not caps:
        _fail("canary_caps_empty")
    normalized = tuple(caps)
    if len(normalized) != len(set(normalized)):
        _fail("canary_caps_duplicate")
    for cap in normalized:
        _require_cap(cap)
    if normalized != tuple(sorted(normalized)):
        _fail("canary_caps_order_invalid")
    return normalized


def _require_cap(cap: Any) -> None:
    if not isinstance(cap, int) or isinstance(cap, bool) or cap not in E1_CANARY_ALLOWED_CAPS:
        _fail("canary_cap_invalid")


def _distribution(values: Iterable[int]) -> E1CanaryDistribution:
    ordered = sorted(values)
    if not ordered:
        return E1CanaryDistribution(None, None, None)
    return E1CanaryDistribution(
        p50_ms=_nearest_rank(ordered, 0.50),
        p95_ms=_nearest_rank(ordered, 0.95),
        max_ms=ordered[-1],
    )


def _nearest_rank(ordered: Sequence[int], percentile: float) -> int:
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _improvement_check(
    baseline: int | None,
    candidate: int | None,
    *,
    minimum: float,
) -> dict[str, Any]:
    observed = (
        (baseline - candidate) / baseline
        if isinstance(baseline, int) and baseline > 0 and isinstance(candidate, int)
        else None
    )
    return {
        "passed": observed is not None and observed + 1e-12 >= minimum,
        "baseline": baseline,
        "candidate": candidate,
        "observed": observed,
        "minimum": minimum,
    }


def _regression_check(
    baseline: int | None,
    candidate: int | None,
    *,
    maximum: float,
) -> dict[str, Any]:
    observed = (
        (candidate - baseline) / baseline
        if isinstance(baseline, int) and baseline > 0 and isinstance(candidate, int)
        else None
    )
    return {
        "passed": observed is not None and observed <= maximum + 1e-12,
        "baseline": baseline,
        "candidate": candidate,
        "observed": observed,
        "maximum": maximum,
    }


def _sha256_json(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise E1CanaryContractError("canary_canonical_json_invalid") from exc
    return hashlib.sha256(payload).hexdigest()


def _non_empty_string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(code)
    return value.strip()


def _positive_int(value: Any, code: str) -> int:
    parsed = _non_negative_int(value, code)
    if parsed <= 0:
        _fail(code)
    return parsed


def _non_negative_int(value: Any, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _fail(code)
    return value


def _fail(code: str) -> None:
    raise E1CanaryContractError(code)
