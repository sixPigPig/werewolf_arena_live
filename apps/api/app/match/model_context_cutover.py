from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.match.model_context_contract import (
    frozen_model_context_contract,
    is_current_model_context_contract,
    is_historical_v11_model_context_contract,
)
from app.match.models import (
    AbilityActivation,
    ActionWindow,
    GameRecord,
    GameRecordEvent,
    GameRun,
    LivePresentation,
    MatchState,
    ModelActionRecovery,
    VoiceAsset,
)
from app.match.runtime_state import project_runtime_state


CUTOVER_TERMINAL_MATCH_STATUSES = frozenset({"completed", "canceled", "failed"})
CUTOVER_TERMINAL_RECOVERY_STATES = frozenset({"resolved", "canceled"})
CUTOVER_TERMINAL_VOICE_STATES = frozenset({"ready", "failed", "canceled"})
CUTOVER_FAILURE_EVENT_TYPES = frozenset(
    {
        "action_failed",
        "ability_runtime_failed",
        "day_runtime_failed",
        "game_phase_transition_failed",
        "match_runtime_failed",
    }
)
CUTOVER_AUDIT_EVENT_TYPES = frozenset(
    {
        "game_completed",
        "game_canceled",
        "v2_run_execution_claimed",
        "v2_run_execution_released",
        *CUTOVER_FAILURE_EVENT_TYPES,
    }
)

CutoverMatchStatus = Literal["waiting", "running", "completed", "failed", "canceled"]
CutoverExecutionState = Literal["unowned", "owned", "stale", "stopped"]


@dataclass(frozen=True)
class ModelContextCutoverEventFact:
    event_type: str
    record_seq: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class ModelContextCutoverFacts:
    game_id: str
    current_run_id: str
    checked_run_id: str | None
    checked_run_game_id: str | None
    prompt_template_version: int | None
    game_status: str
    phase_state: str
    run_status: str | None
    match_status: CutoverMatchStatus
    execution_state: CutoverExecutionState
    winner: str | None
    completion_reason: str | None
    run_completed_at: datetime | None
    worker_id: str | None
    worker_heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    fence_token: int | None
    events: tuple[ModelContextCutoverEventFact, ...] = ()
    open_presentation_count: int = 0
    open_action_window_count: int = 0
    open_ability_activation_count: int = 0
    unsafe_recovery_count: int = 0
    leased_recovery_count: int = 0
    unfinished_voice_asset_count: int = 0


@dataclass(frozen=True)
class ModelContextCutoverFinding:
    game_id: str
    current_run_id: str
    prompt_template_version: int | None
    match_status: str
    execution_state: str
    reason_codes: tuple[str, ...]

    @property
    def is_safe_history(self) -> bool:
        return not self.reason_codes

    def as_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "current_run_id": self.current_run_id,
            "prompt_template_version": self.prompt_template_version,
            "match_status": self.match_status,
            "execution_state": self.execution_state,
            "safe_history": self.is_safe_history,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class ModelContextCutoverReport:
    scanned_game_count: int
    ignored_current_v12_game_count: int
    findings: tuple[ModelContextCutoverFinding, ...]

    @property
    def candidate_count(self) -> int:
        return len(self.findings)

    @property
    def safe_history_count(self) -> int:
        return sum(item.is_safe_history for item in self.findings)

    @property
    def blocking_count(self) -> int:
        return self.candidate_count - self.safe_history_count

    @property
    def deployable(self) -> bool:
        return self.blocking_count == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cutover": "v11_to_v12",
            "read_only": True,
            "deployable": self.deployable,
            "scanned_game_count": self.scanned_game_count,
            "ignored_current_v12_game_count": self.ignored_current_v12_game_count,
            "candidate_count": self.candidate_count,
            "safe_history_count": self.safe_history_count,
            "blocking_count": self.blocking_count,
            "findings": [item.as_dict() for item in self.findings],
        }


def evaluate_v11_model_context_cutover(
    facts: ModelContextCutoverFacts,
) -> ModelContextCutoverFinding:
    reasons: list[str] = []

    if facts.checked_run_id is None:
        reasons.append("current_run_missing")
    elif facts.checked_run_id != facts.current_run_id:
        reasons.append("current_run_id_mismatch")
    if facts.checked_run_game_id is not None and facts.checked_run_game_id != facts.game_id:
        reasons.append("current_run_game_id_mismatch")

    terminal_kind = _expected_terminal_kind(facts)
    terminal_event = _latest_terminal_event(facts.events, terminal_kind)

    if facts.match_status not in CUTOVER_TERMINAL_MATCH_STATUSES:
        reasons.append("match_status_not_terminal")
    if terminal_kind == "completed":
        if facts.phase_state != "game_completed":
            reasons.append("completed_phase_state_invalid")
        if facts.winner not in {"villagers", "werewolves"}:
            reasons.append("completed_winner_missing")
        if facts.completion_reason is None:
            reasons.append("completed_reason_missing")
        if facts.run_completed_at is None:
            reasons.append("completed_at_missing")
        if terminal_event is None:
            reasons.append("game_completed_event_missing")
    elif terminal_kind == "canceled":
        if facts.game_status != "canceled" or facts.run_status != "canceled":
            reasons.append("canceled_game_run_state_invalid")
        if terminal_event is None:
            reasons.append("game_canceled_event_missing")
    elif terminal_kind == "failed":
        if not (
            facts.game_status == "failed"
            and facts.phase_state == "failed"
            and facts.run_status == "failed"
        ):
            reasons.append("failed_game_phase_run_state_invalid")
        if terminal_event is None:
            reasons.append("terminal_failure_event_missing")
    else:
        reasons.append("terminal_state_evidence_missing")

    if facts.execution_state != "stopped":
        reasons.append("execution_state_not_stopped")
    if any(
        value is not None
        for value in (
            facts.worker_id,
            facts.worker_heartbeat_at,
            facts.lease_expires_at,
        )
    ):
        reasons.append("execution_owner_fields_not_clear")
    if facts.game_status == "finalizing" or facts.run_status == "finalizing":
        reasons.append("finalization_in_progress")

    if facts.open_presentation_count:
        reasons.append("open_live_presentation")
    if facts.open_action_window_count:
        reasons.append("open_action_window")
    if facts.open_ability_activation_count:
        reasons.append("open_ability_activation")
    if facts.unsafe_recovery_count:
        reasons.append("model_action_recovery_not_terminal")
    if facts.leased_recovery_count:
        reasons.append("model_action_recovery_lease_present")
    if facts.unfinished_voice_asset_count:
        reasons.append("unfinished_voice_asset")

    if terminal_kind == "canceled":
        if terminal_event is not None and not _cancellation_invalidated_fence(
            terminal_event,
            current_fence_token=facts.fence_token,
        ):
            reasons.append("cancellation_fence_not_advanced")
    elif terminal_kind in {"completed", "failed"}:
        _append_completed_or_failed_ownership_reasons(
            reasons,
            facts=facts,
            terminal_event=terminal_event,
        )

    return ModelContextCutoverFinding(
        game_id=facts.game_id,
        current_run_id=facts.current_run_id,
        prompt_template_version=facts.prompt_template_version,
        match_status=facts.match_status,
        execution_state=facts.execution_state,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def preflight_v12_model_context_cutover(
    db: Session,
    *,
    now: datetime | None = None,
) -> ModelContextCutoverReport:
    checked_at = now or datetime.now(UTC)
    findings: list[ModelContextCutoverFinding] = []
    ignored_current_v12_count = 0

    with db.no_autoflush:
        games = list(db.scalars(select(GameRecord).order_by(GameRecord.game_id)))
        for game in games:
            contract = frozen_model_context_contract(game.rule_snapshot)
            if is_current_model_context_contract(contract):
                ignored_current_v12_count += 1
                continue
            prompt_version = _int_or_none(
                contract.get("prompt_template_version") if contract is not None else None
            )
            if not is_historical_v11_model_context_contract(contract):
                reason_code = _unsupported_contract_reason(
                    rule_snapshot=game.rule_snapshot,
                    contract=contract,
                )
                findings.append(
                    ModelContextCutoverFinding(
                        game_id=game.game_id,
                        current_run_id=game.current_run_id,
                        prompt_template_version=prompt_version,
                        match_status="unknown",
                        execution_state="unknown",
                        reason_codes=(reason_code,),
                    )
                )
                continue
            facts = _load_cutover_facts(
                db,
                game=game,
                prompt_template_version=prompt_version,
                now=checked_at,
            )
            findings.append(evaluate_v11_model_context_cutover(facts))

    return ModelContextCutoverReport(
        scanned_game_count=len(games),
        ignored_current_v12_game_count=ignored_current_v12_count,
        findings=tuple(findings),
    )


def _load_cutover_facts(
    db: Session,
    *,
    game: GameRecord,
    prompt_template_version: int | None,
    now: datetime,
) -> ModelContextCutoverFacts:
    run = db.get(GameRun, game.current_run_id)
    match = db.get(MatchState, game.game_id)
    event_rows = list(
        db.execute(
            select(
                GameRecordEvent.event_type,
                GameRecordEvent.record_seq,
                GameRecordEvent.payload,
            )
            .where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.run_id == game.current_run_id,
                GameRecordEvent.event_type.in_(CUTOVER_AUDIT_EVENT_TYPES),
            )
            .order_by(GameRecordEvent.record_seq)
        )
    )
    events = tuple(
        ModelContextCutoverEventFact(
            event_type=str(event_type),
            record_seq=int(record_seq),
            payload=dict(payload) if isinstance(payload, dict) else {},
        )
        for event_type, record_seq, payload in event_rows
    )

    if run is None:
        match_status: CutoverMatchStatus = "running"
        execution_state: CutoverExecutionState = "stale"
    else:
        projection = project_runtime_state(
            game=game,
            run=run,
            match=match,
            now=now,
            completion_event_present=any(event.event_type == "game_completed" for event in events),
        )
        match_status = projection.match_status
        execution_state = projection.execution_state

    open_presentation_count = _count_rows(
        db,
        select(func.count())
        .select_from(LivePresentation)
        .where(
            LivePresentation.game_id == game.game_id,
            LivePresentation.closed_at.is_(None),
        ),
    )
    open_action_window_count = _count_rows(
        db,
        select(func.count())
        .select_from(ActionWindow)
        .where(
            ActionWindow.game_id == game.game_id,
            ActionWindow.closed_at.is_(None),
        ),
    )
    open_ability_activation_count = _count_rows(
        db,
        select(func.count())
        .select_from(AbilityActivation)
        .where(
            AbilityActivation.game_id == game.game_id,
            AbilityActivation.closed_at.is_(None),
        ),
    )
    unsafe_recovery_count = _count_rows(
        db,
        select(func.count())
        .select_from(ModelActionRecovery)
        .where(
            ModelActionRecovery.game_id == game.game_id,
            ~ModelActionRecovery.state.in_(tuple(sorted(CUTOVER_TERMINAL_RECOVERY_STATES))),
        ),
    )
    leased_recovery_count = _count_rows(
        db,
        select(func.count())
        .select_from(ModelActionRecovery)
        .where(
            ModelActionRecovery.game_id == game.game_id,
            or_(
                ModelActionRecovery.lease_owner.is_not(None),
                ModelActionRecovery.lease_expires_at.is_not(None),
            ),
        ),
    )
    unfinished_voice_asset_count = _count_rows(
        db,
        select(func.count())
        .select_from(VoiceAsset)
        .where(
            VoiceAsset.game_id == game.game_id,
            or_(
                ~VoiceAsset.state.in_(tuple(sorted(CUTOVER_TERMINAL_VOICE_STATES))),
                VoiceAsset.completed_at.is_(None),
            ),
        ),
    )

    return ModelContextCutoverFacts(
        game_id=game.game_id,
        current_run_id=game.current_run_id,
        checked_run_id=run.run_id if run is not None else None,
        checked_run_game_id=run.game_id if run is not None else None,
        prompt_template_version=prompt_template_version,
        game_status=game.status,
        phase_state=game.phase_state,
        run_status=run.status if run is not None else None,
        match_status=match_status,
        execution_state=execution_state,
        winner=match.winner if match is not None else None,
        completion_reason=match.completion_reason if match is not None else None,
        run_completed_at=run.completed_at if run is not None else None,
        worker_id=run.worker_id if run is not None else None,
        worker_heartbeat_at=run.worker_heartbeat_at if run is not None else None,
        lease_expires_at=run.lease_expires_at if run is not None else None,
        fence_token=run.fence_token if run is not None else None,
        events=events,
        open_presentation_count=open_presentation_count,
        open_action_window_count=open_action_window_count,
        open_ability_activation_count=open_ability_activation_count,
        unsafe_recovery_count=unsafe_recovery_count,
        leased_recovery_count=leased_recovery_count,
        unfinished_voice_asset_count=unfinished_voice_asset_count,
    )


def _expected_terminal_kind(
    facts: ModelContextCutoverFacts,
) -> Literal["completed", "canceled", "failed"] | None:
    if facts.game_status == "canceled" or facts.run_status == "canceled":
        return "canceled"
    if (
        facts.game_status == "failed"
        or facts.phase_state == "failed"
        or facts.run_status == "failed"
    ):
        return "failed"
    if facts.phase_state == "game_completed" or facts.match_status == "completed":
        return "completed"
    return None


def _latest_terminal_event(
    events: tuple[ModelContextCutoverEventFact, ...],
    terminal_kind: Literal["completed", "canceled", "failed"] | None,
) -> ModelContextCutoverEventFact | None:
    if terminal_kind == "completed":
        event_types = {"game_completed"}
    elif terminal_kind == "canceled":
        event_types = {"game_canceled"}
    elif terminal_kind == "failed":
        event_types = CUTOVER_FAILURE_EVENT_TYPES
    else:
        return None
    return max(
        (event for event in events if event.event_type in event_types),
        key=lambda event: event.record_seq,
        default=None,
    )


def _append_completed_or_failed_ownership_reasons(
    reasons: list[str],
    *,
    facts: ModelContextCutoverFacts,
    terminal_event: ModelContextCutoverEventFact | None,
) -> None:
    claims = tuple(
        event for event in facts.events if event.event_type == "v2_run_execution_claimed"
    )
    if not claims:
        if facts.fence_token != 0:
            reasons.append("never_owned_audit_inconsistent")
        return
    release_after_terminal = terminal_event is not None and any(
        event.event_type == "v2_run_execution_released"
        and event.record_seq > terminal_event.record_seq
        for event in facts.events
    )
    terminal_transaction_cleared_owner = (
        terminal_event is not None and terminal_event.payload.get("execution_owner_cleared") is True
    )
    if not release_after_terminal and not terminal_transaction_cleared_owner:
        reasons.append("execution_release_after_terminal_missing")


def _cancellation_invalidated_fence(
    terminal_event: ModelContextCutoverEventFact,
    *,
    current_fence_token: int | None,
) -> bool:
    invalidated = terminal_event.payload.get("invalidated_fence_token")
    return (
        isinstance(invalidated, int)
        and not isinstance(invalidated, bool)
        and isinstance(current_fence_token, int)
        and not isinstance(current_fence_token, bool)
        and current_fence_token == invalidated + 1
    )


def _unsupported_contract_reason(
    *,
    rule_snapshot: object,
    contract: dict[str, Any] | None,
) -> str:
    if not isinstance(rule_snapshot, dict) or "model_context_contract" not in rule_snapshot:
        return "model_context_contract_missing"
    if contract is None:
        return "model_context_contract_malformed"
    version = contract.get("model_context_schema_version")
    if isinstance(version, int) and not isinstance(version, bool) and version == 11:
        return "unrecognized_historical_v11_contract"
    return "unsupported_model_context_contract_for_cutover"


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _count_rows(db: Session, statement: Any) -> int:
    return int(db.scalar(statement) or 0)
