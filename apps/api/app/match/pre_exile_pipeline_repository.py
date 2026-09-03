from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.match.day_speech_pipeline_contract import resolve_day_speech_pipeline_contract
from app.match.event_contract import canonical_event_payload
from app.match.execution import RunFence, RunFenceRejected, require_run_fence
from app.match.model_failure_episode import derive_failure_episodes, stable_failure_episode_id
from app.match.models import (
    GameRecord,
    GameRecordEvent,
    GameRun,
    KnowledgeFact,
    LivePresentation,
    MatchState,
    PlayerState,
    PreExilePipeline,
    PreExileResult,
    RoleAssignment,
)
from app.match.pre_exile_pipeline_contract import (
    RECOVERABLE_PRE_EXILE_VOTE_CATEGORIES,
    resolve_pre_exile_pipeline_contract,
)
from app.match.repository import ExecutionOwnershipLost, RepositoryError


PreExilePipelineState = Literal[
    "collecting",
    "no_explosion",
    "explosion_selected",
    "votes_accepted",
    "consumed",
    "canceled",
    "invalidated",
]
PreExileResultKind = Literal["self_explosion", "exile_vote"]
PreExileResultState = Literal[
    "reserved",
    "generating",
    "ready",
    "failed",
    "accepted",
    "committed",
    "discarded",
]

_PIPELINE_TERMINAL_STATES = frozenset({"explosion_selected", "consumed", "canceled", "invalidated"})
_RESULT_TERMINAL_STATES = frozenset({"committed", "discarded"})
_PUBLIC_AUDIENCES = frozenset({"all", "public"})
_LIVE_MATCH_STATUSES = frozenset(
    {
        "ready",
        "generating",
        "broadcasting",
        "finalizing",
    }
)
_OPEN_PRESENTATION_STATES = frozenset({"queued", "active"})


class PreExilePipelineRepositoryError(RepositoryError):
    pass


@dataclass(frozen=True)
class PreExilePipelineSnapshot:
    pipeline_id: str
    game_id: str
    run_id: str
    fence_worker_id: str
    fence_token: int
    phase_id: str
    round_no: int
    predecessor_action_id: str
    predecessor_presentation_id: str
    predecessor_source_event_id: int
    predecessor_source_record_seq: int
    predecessor_sealed_record_seq: int
    public_cutoff_record_seq: int
    public_history_sha256: str
    state: PreExilePipelineState
    selected_explosion_player_id: str | None
    vote_batch_id: str | None
    vote_decision_context_sha256: str | None
    failure: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    explosion_resolved_at: datetime | None
    votes_accepted_at: datetime | None
    consumed_at: datetime | None
    terminal_at: datetime | None


@dataclass(frozen=True)
class PreExileResultSnapshot:
    result_id: str
    pipeline_id: str
    game_id: str
    actor_player_id: str
    result_kind: PreExileResultKind
    state: PreExileResultState
    action_id: str | None
    recovery_action_id: str | None
    recovery_attempt_id: str | None
    recovery_response_record_seq: int | None
    recovery_terminal_record_seq: int | None
    attempt_id: str | None
    response_record_seq: int | None
    terminal_record_seq: int | None
    result_record_seq: int | None
    decision: dict[str, Any] | None
    failure_record_seq: int | None
    failure: dict[str, Any] | None
    private_fact_id: str | None
    private_fact_record_seq: int | None
    created_at: datetime
    updated_at: datetime
    generation_started_at: datetime | None
    ready_at: datetime | None
    terminal_at: datetime | None


@dataclass(frozen=True)
class PreExileExplosionResolution:
    outcome: Literal["no_explosion", "explosion_selected"]
    selected_player_id: str | None
    failed_player_ids: tuple[str, ...]


class PreExilePipelineRepository:
    """Durable, fenced state for last-speech/pre-exile overlap."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_pipeline(self, pipeline_id: str) -> PreExilePipelineSnapshot:
        with self._session_factory() as db:
            row = db.get(PreExilePipeline, pipeline_id)
            if row is None:
                raise PreExilePipelineRepositoryError(f"unknown pre-exile pipeline {pipeline_id}")
            return _pipeline_snapshot(row)

    def list_results(self, pipeline_id: str) -> tuple[PreExileResultSnapshot, ...]:
        with self._session_factory() as db:
            if db.get(PreExilePipeline, pipeline_id) is None:
                raise PreExilePipelineRepositoryError(f"unknown pre-exile pipeline {pipeline_id}")
            rows = list(
                db.scalars(
                    select(PreExileResult)
                    .where(PreExileResult.pipeline_id == pipeline_id)
                    .order_by(
                        PreExileResult.result_kind,
                        PreExileResult.actor_player_id,
                    )
                )
            )
            return tuple(_result_snapshot(row) for row in rows)

    def get_provisional_self_explosion_fact(
        self,
        *,
        pipeline_id: str,
        actor_player_id: str,
        private_fact_id: str,
        fence: RunFence | None = None,
    ) -> dict[str, Any]:
        """Return only this wolf's durable false fact for its speculative vote."""

        _canonical_id(private_fact_id, field="private_fact_id", maximum=48)
        with self._session_factory.begin() as db:
            _game, _run, pipeline, row = _locked_result(
                db,
                pipeline_id=pipeline_id,
                actor_player_id=actor_player_id,
                result_kind="self_explosion",
                fence=fence,
            )
            fact = db.get(KnowledgeFact, private_fact_id)
            if (
                not (
                    pipeline.state == "collecting"
                    and row.state in {"ready", "failed"}
                    or pipeline.state == "no_explosion"
                    and row.state == "committed"
                )
                or row.private_fact_id != private_fact_id
                or type(row.private_fact_record_seq) is not int
                or bool((row.decision or {}).get("explode"))
                or fact is None
                or fact.game_id != pipeline.game_id
                or fact.owner_scope != "player"
                or fact.owner_id != actor_player_id
                or fact.fact_type != "private_action_decision"
            ):
                raise PreExilePipelineRepositoryError(
                    "pre_exile_provisional_self_explosion_fact_unavailable"
                )
            payload = deepcopy(fact.payload or {})
            context = payload.get("context")
            if (
                payload.get("action_type") != "werewolf_self_explosion"
                or not isinstance(context, dict)
                or context.get("pipeline_id") != pipeline.pipeline_id
                or context.get("public_history_cutoff_record_seq")
                != pipeline.public_cutoff_record_seq
                or context.get("visibility_mode") != "pre_exile_provisional_until_atomic_arbiter"
                or (payload.get("decision") or {}).get("explode") is not False
            ):
                raise PreExilePipelineRepositoryError(
                    "pre_exile_provisional_self_explosion_fact_invalid"
                )
            recorded = _event_at(
                db,
                game_id=pipeline.game_id,
                run_id=pipeline.run_id,
                record_seq=row.private_fact_record_seq,
                event_type="private_knowledge_recorded",
            )
            if _payload(recorded).get("knowledge_fact_id") != private_fact_id:
                raise PreExilePipelineRepositoryError(
                    "pre_exile_provisional_self_explosion_fact_clock_invalid"
                )
            return {
                "knowledge_fact_id": fact.knowledge_fact_id,
                "source_activation_id": fact.source_activation_id,
                "owner_scope": fact.owner_scope,
                "owner_id": fact.owner_id,
                "fact_type": fact.fact_type,
                "payload": payload,
                "source_event_id": recorded.event_id,
                "source_event_type": recorded.event_type,
                "record_seq": recorded.record_seq,
                "known_at_seq": recorded.record_seq,
                "occurred_in": {"period": "day", "round_no": pipeline.round_no},
            }

    def reserve_pipeline(
        self,
        *,
        game_id: str,
        phase_id: str,
        round_no: int,
        predecessor_action_id: str,
        predecessor_presentation_id: str,
        predecessor_source_event_id: int,
        predecessor_source_record_seq: int,
        predecessor_sealed_record_seq: int,
        public_cutoff_record_seq: int,
        public_history_sha256: str,
        fence: RunFence | None = None,
    ) -> PreExilePipelineSnapshot:
        _canonical_id(game_id, field="game_id", maximum=40)
        _canonical_id(phase_id, field="phase_id", maximum=40)
        _canonical_id(predecessor_action_id, field="predecessor_action_id", maximum=48)
        _canonical_id(
            predecessor_presentation_id,
            field="predecessor_presentation_id",
            maximum=48,
        )
        for field, value in (
            ("round_no", round_no),
            ("predecessor_source_event_id", predecessor_source_event_id),
            ("predecessor_source_record_seq", predecessor_source_record_seq),
            ("predecessor_sealed_record_seq", predecessor_sealed_record_seq),
            ("public_cutoff_record_seq", public_cutoff_record_seq),
        ):
            _positive_int(value, field=field)
        if not (
            predecessor_source_record_seq
            < predecessor_sealed_record_seq
            <= public_cutoff_record_seq
        ):
            raise PreExilePipelineRepositoryError(
                "pre-exile predecessor cutoff lineage is invalid"
            )
        if (
            not isinstance(public_history_sha256, str)
            or len(public_history_sha256) != 64
            or any(char not in "0123456789abcdef" for char in public_history_sha256)
        ):
            raise PreExilePipelineRepositoryError("pre-exile public history hash is invalid")

        with self._session_factory.begin() as db:
            game, run = _locked_game_and_fence(db, game_id=game_id, fence=fence)
            _raise_if_stop_requested(run)
            contract = resolve_pre_exile_pipeline_contract(game.rule_snapshot)
            if not all(
                contract.enables(action_type)
                for action_type in ("werewolf_self_explosion", "exile_vote")
            ):
                raise PreExilePipelineRepositoryError("pre_exile_pipeline_contract_disabled")
            match = db.get(MatchState, game_id)
            if (
                match is None
                or match.round_no != round_no
                or phase_id != f"day_{round_no}"
                or game.phase_id != phase_id
            ):
                raise PreExilePipelineRepositoryError("pre-exile pipeline day changed")
            if game.status not in _LIVE_MATCH_STATUSES or run.status != game.status:
                raise PreExilePipelineRepositoryError(
                    "pre-exile reservation requires a sealed last speech on a live match"
                )
            if public_cutoff_record_seq > game.last_record_seq:
                raise PreExilePipelineRepositoryError(
                    "pre-exile public cutoff is ahead of durable history"
                )
            _validate_sealed_last_speech(
                db,
                game=game,
                round_no=round_no,
                predecessor_action_id=predecessor_action_id,
                predecessor_presentation_id=predecessor_presentation_id,
                predecessor_source_event_id=predecessor_source_event_id,
                predecessor_source_record_seq=predecessor_source_record_seq,
                predecessor_sealed_record_seq=predecessor_sealed_record_seq,
                public_cutoff_record_seq=public_cutoff_record_seq,
            )
            pipeline_id = _deterministic_id(
                "v2_preex_",
                game_id,
                run.run_id,
                phase_id,
                str(round_no),
                predecessor_presentation_id,
                str(public_cutoff_record_seq),
            )
            existing = db.scalar(
                select(PreExilePipeline)
                .where(
                    PreExilePipeline.game_id == game_id,
                    PreExilePipeline.run_id == run.run_id,
                    PreExilePipeline.phase_id == phase_id,
                    PreExilePipeline.round_no == round_no,
                )
                .with_for_update()
            )
            immutable = {
                "pipeline_id": pipeline_id,
                "predecessor_action_id": predecessor_action_id,
                "predecessor_presentation_id": predecessor_presentation_id,
                "predecessor_source_event_id": predecessor_source_event_id,
                "predecessor_source_record_seq": predecessor_source_record_seq,
                "predecessor_sealed_record_seq": predecessor_sealed_record_seq,
                "public_cutoff_record_seq": public_cutoff_record_seq,
                "public_history_sha256": public_history_sha256,
            }
            if existing is not None:
                if any(getattr(existing, key) != value for key, value in immutable.items()):
                    raise PreExilePipelineRepositoryError(
                        "pre-exile reservation conflicts with durable pipeline"
                    )
                _require_owned_pipeline(existing, run)
                return _pipeline_snapshot(existing)
            row = PreExilePipeline(
                pipeline_id=pipeline_id,
                game_id=game_id,
                run_id=run.run_id,
                fence_worker_id=_required_worker_id(run),
                fence_token=run.fence_token,
                phase_id=phase_id,
                round_no=round_no,
                predecessor_action_id=predecessor_action_id,
                predecessor_presentation_id=predecessor_presentation_id,
                predecessor_source_event_id=predecessor_source_event_id,
                predecessor_source_record_seq=predecessor_source_record_seq,
                predecessor_sealed_record_seq=predecessor_sealed_record_seq,
                public_cutoff_record_seq=public_cutoff_record_seq,
                public_history_sha256=public_history_sha256,
                state="collecting",
            )
            db.add(row)
            _append_pipeline_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="pre_exile_pipeline_reserved",
                row=row,
                payload={
                    "predecessor_action_id": predecessor_action_id,
                    "predecessor_presentation_id": predecessor_presentation_id,
                    "predecessor_source_event_id": predecessor_source_event_id,
                    "predecessor_source_record_seq": predecessor_source_record_seq,
                    "predecessor_sealed_record_seq": predecessor_sealed_record_seq,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                    "public_history_sha256": public_history_sha256,
                },
            )
            db.flush()
            return _pipeline_snapshot(row)

    def reserve_result(
        self,
        *,
        pipeline_id: str,
        actor_player_id: str,
        result_kind: PreExileResultKind,
        fence: RunFence | None = None,
    ) -> PreExileResultSnapshot:
        _canonical_id(actor_player_id, field="actor_player_id", maximum=80)
        _result_kind(result_kind)
        with self._session_factory.begin() as db:
            game, run, pipeline = _locked_owned_pipeline(db, pipeline_id=pipeline_id, fence=fence)
            _raise_if_stop_requested(run)
            if result_kind == "self_explosion":
                _require_pipeline_state(pipeline, "collecting")
            else:
                _require_pipeline_state(pipeline, "collecting", "no_explosion")
            player = db.get(PlayerState, (game.game_id, actor_player_id))
            assignment = db.scalar(
                select(RoleAssignment).where(
                    RoleAssignment.game_id == game.game_id,
                    RoleAssignment.player_id == actor_player_id,
                )
            )
            if player is None or assignment is None or not player.alive:
                raise PreExilePipelineRepositoryError("pre-exile result actor must be alive")
            if result_kind == "self_explosion" and assignment.role_key != "werewolf":
                raise PreExilePipelineRepositoryError(
                    "self-explosion result actor must be a werewolf"
                )
            if result_kind == "exile_vote" and not bool((player.state or {}).get("can_vote", True)):
                raise PreExilePipelineRepositoryError("pre-exile vote actor cannot vote")
            result_id = _deterministic_id(
                "v2_prexr_", pipeline.pipeline_id, result_kind, actor_player_id
            )
            existing = db.scalar(
                select(PreExileResult)
                .where(
                    PreExileResult.pipeline_id == pipeline.pipeline_id,
                    PreExileResult.actor_player_id == actor_player_id,
                    PreExileResult.result_kind == result_kind,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.result_id != result_id or existing.game_id != game.game_id:
                    raise PreExilePipelineRepositoryError(
                        "pre-exile result reservation conflicts with durable member"
                    )
                return _result_snapshot(existing)
            row = PreExileResult(
                result_id=result_id,
                pipeline_id=pipeline.pipeline_id,
                game_id=game.game_id,
                actor_player_id=actor_player_id,
                result_kind=result_kind,
                state="reserved",
            )
            db.add(row)
            _append_pipeline_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="pre_exile_result_reserved",
                row=pipeline,
                payload={
                    "result_id": result_id,
                    "result_kind": result_kind,
                    "actor_player_id": actor_player_id,
                },
            )
            db.flush()
            return _result_snapshot(row)

    def record_result(
        self,
        *,
        pipeline_id: str,
        actor_player_id: str,
        result_kind: PreExileResultKind,
        action_id: str,
        response_record_seq: int | None = None,
        terminal_record_seq: int | None = None,
        technical_outcome_record_seq: int | None = None,
        fence: RunFence | None = None,
    ) -> PreExileResultSnapshot:
        _canonical_id(action_id, field="action_id", maximum=48)
        if response_record_seq is not None:
            _positive_int(response_record_seq, field="response_record_seq")
        if terminal_record_seq is not None:
            _positive_int(terminal_record_seq, field="terminal_record_seq")
        if technical_outcome_record_seq is not None:
            _positive_int(
                technical_outcome_record_seq,
                field="technical_outcome_record_seq",
            )
        with self._session_factory.begin() as db:
            game, run, pipeline, row = _locked_result(
                db,
                pipeline_id=pipeline_id,
                actor_player_id=actor_player_id,
                result_kind=result_kind,
                fence=fence,
            )
            if row.action_id != action_id:
                raise PreExilePipelineRepositoryError(
                    "pre-exile result action changed after claim"
                )
            resolved_response = response_record_seq
            if resolved_response is None:
                accepted = _find_accepted_model_response(
                    db,
                    game_id=pipeline.game_id,
                    run_id=pipeline.run_id,
                    action_id=action_id,
                )
                resolved_response = accepted.record_seq if accepted is not None else None
            resolved_terminal = terminal_record_seq
            terminal = _find_event(
                db,
                game_id=pipeline.game_id,
                run_id=pipeline.run_id,
                event_type="action_succeeded",
                action_id=action_id,
                latest=True,
            )
            if resolved_terminal is None and terminal is not None:
                resolved_terminal = terminal.record_seq
            resolved_technical = technical_outcome_record_seq
            if resolved_technical is None and terminal is not None:
                candidate = _payload(terminal).get("technical_outcome_record_seq")
                if type(candidate) is int and candidate > 0:
                    resolved_technical = candidate
            if resolved_terminal is None:
                raise PreExilePipelineRepositoryError(
                    "pre-exile result has no durable action success"
                )
            if row.state in {"ready", "failed", "accepted", "committed", "discarded"}:
                stored_technical = (
                    (row.failure or {}).get("technical_outcome_record_seq")
                    if isinstance(row.failure, dict)
                    else None
                )
                if (
                    row.action_id == action_id
                    and row.response_record_seq == resolved_response
                    and row.terminal_record_seq == resolved_terminal
                    and stored_technical == resolved_technical
                    and (stored_technical is None or row.failure_record_seq == stored_technical)
                ):
                    return _result_snapshot(row)
                raise PreExilePipelineRepositoryError(
                    "pre-exile result has different durable success lineage"
                )
            _require_result_state(row, "generating")
            if resolved_response is not None:
                if resolved_terminal <= resolved_response:
                    raise PreExilePipelineRepositoryError(
                        "pre-exile result terminal event precedes response"
                    )
                attempt_id, decision = _validate_success_result(
                    db,
                    pipeline=pipeline,
                    row=row,
                    action_id=action_id,
                    response_record_seq=resolved_response,
                    terminal_record_seq=resolved_terminal,
                    last_record_seq=game.last_record_seq,
                )
                row.attempt_id = attempt_id
                row.response_record_seq = resolved_response
                row.decision = decision
                row.state = "ready"
                decision_status = "completed"
            else:
                if resolved_technical is None:
                    raise PreExilePipelineRepositoryError(
                        "pre-exile technical result has no supporting event"
                    )
                technical = _event_at_any(
                    db,
                    game_id=pipeline.game_id,
                    run_id=pipeline.run_id,
                    record_seq=resolved_technical,
                    event_types={
                        "technical_fallback_applied",
                        "technical_target_outcome_applied",
                    },
                )
                technical_payload = _payload(technical)
                if technical_payload.get("action_id") != action_id:
                    raise PreExilePipelineRepositoryError(
                        "pre-exile technical result action changed"
                    )
                attempt_id = technical_payload.get("attempt_id")
                if attempt_id is not None:
                    _canonical_id(attempt_id, field="attempt_id", maximum=48)
                row.attempt_id = attempt_id
                row.failure_record_seq = resolved_technical
                row.failure = {
                    "technical_outcome_record_seq": resolved_technical,
                    "technical_outcome": deepcopy(technical_payload),
                }
                row.decision = (
                    {"explode": False, "decision_status": "technical_failure"}
                    if result_kind == "self_explosion"
                    else None
                )
                row.state = "failed"
                decision_status = "technical_failure"
            row.terminal_record_seq = resolved_terminal
            row.ready_at = _now()
            if result_kind == "self_explosion":
                fact_id, fact_record_seq = _persist_self_explosion_fact(
                    db,
                    game=game,
                    pipeline=pipeline,
                    row=row,
                    decision=dict(row.decision or {}),
                    decision_status=decision_status,
                )
                row.private_fact_id = fact_id
                row.private_fact_record_seq = fact_record_seq
            result_event = _append_result_recorded_event(
                db,
                game=game,
                run_id=run.run_id,
                pipeline=pipeline,
                row=row,
            )
            row.result_record_seq = result_event.record_seq
            db.flush()
            return _result_snapshot(row)

    def record_failure(
        self,
        *,
        pipeline_id: str,
        actor_player_id: str,
        result_kind: PreExileResultKind,
        action_id: str,
        failure_record_seq: int,
        fence: RunFence | None = None,
    ) -> PreExileResultSnapshot:
        _canonical_id(action_id, field="action_id", maximum=48)
        _positive_int(failure_record_seq, field="failure_record_seq")
        with self._session_factory.begin() as db:
            game, run, pipeline, row = _locked_result(
                db,
                pipeline_id=pipeline_id,
                actor_player_id=actor_player_id,
                result_kind=result_kind,
                fence=fence,
            )
            if row.state == "failed":
                if row.action_id == action_id and row.failure_record_seq == failure_record_seq:
                    return _result_snapshot(row)
                raise PreExilePipelineRepositoryError(
                    "pre-exile result has different durable failure lineage"
                )
            _require_result_state(row, "generating")
            if row.action_id != action_id:
                raise PreExilePipelineRepositoryError(
                    "pre-exile result failure action changed after claim"
                )
            failure, attempt_id = _validate_failure_result(
                db,
                pipeline=pipeline,
                row=row,
                action_id=action_id,
                failure_record_seq=failure_record_seq,
                last_record_seq=game.last_record_seq,
            )
            row.failure_record_seq = failure_record_seq
            row.terminal_record_seq = failure_record_seq
            row.failure = failure
            row.attempt_id = attempt_id
            row.decision = (
                {"explode": False, "decision_status": "technical_failure"}
                if result_kind == "self_explosion"
                else None
            )
            row.state = "failed"
            row.ready_at = _now()
            if result_kind == "self_explosion":
                fact_id, fact_record_seq = _persist_self_explosion_fact(
                    db,
                    game=game,
                    pipeline=pipeline,
                    row=row,
                    decision=dict(row.decision or {}),
                    decision_status="technical_failure",
                )
                row.private_fact_id = fact_id
                row.private_fact_record_seq = fact_record_seq
            result_event = _append_result_recorded_event(
                db,
                game=game,
                run_id=run.run_id,
                pipeline=pipeline,
                row=row,
            )
            row.result_record_seq = result_event.record_seq
            db.flush()
            return _result_snapshot(row)

    def resolve_self_explosions(
        self,
        *,
        pipeline_id: str,
        expected_wolf_ids: tuple[str, ...],
        fence: RunFence | None = None,
    ) -> PreExileExplosionResolution:
        del pipeline_id, expected_wolf_ids, fence
        raise PreExilePipelineRepositoryError("pre_exile_atomic_arbiter_required")

    def adopt_vote_recovery_result(
        self,
        *,
        pipeline_id: str,
        actor_player_id: str,
        source_action_id: str,
        recovery_action_id: str,
        response_record_seq: int | None = None,
        terminal_record_seq: int | None = None,
        technical_outcome_record_seq: int | None = None,
        fence: RunFence | None = None,
    ) -> PreExileResultSnapshot:
        """Adopt the sole normal recovery allowed after idle admission rejection."""

        for field, value in (
            ("source_action_id", source_action_id),
            ("recovery_action_id", recovery_action_id),
        ):
            _canonical_id(value, field=field, maximum=48)
        for field, value in (
            ("response_record_seq", response_record_seq),
            ("terminal_record_seq", terminal_record_seq),
            ("technical_outcome_record_seq", technical_outcome_record_seq),
        ):
            if value is not None:
                _positive_int(value, field=field)
        with self._session_factory.begin() as db:
            game, run, pipeline, row = _locked_result(
                db,
                pipeline_id=pipeline_id,
                actor_player_id=actor_player_id,
                result_kind="exile_vote",
                fence=fence,
            )
            if row.action_id != source_action_id:
                raise PreExilePipelineRepositoryError(
                    "pre-exile vote recovery source action changed"
                )
            if row.recovery_action_id is not None:
                if (
                    row.recovery_action_id == recovery_action_id
                    and row.recovery_terminal_record_seq is not None
                    and row.state in {"ready", "failed", "committed", "discarded"}
                ):
                    stored_technical_seq = (row.failure or {}).get("technical_outcome_record_seq")
                    if (
                        response_record_seq is not None
                        and response_record_seq != row.recovery_response_record_seq
                        or terminal_record_seq is not None
                        and terminal_record_seq != row.recovery_terminal_record_seq
                        or technical_outcome_record_seq is not None
                        and technical_outcome_record_seq != stored_technical_seq
                    ):
                        raise PreExilePipelineRepositoryError(
                            "pre-exile vote recovery retry changed durable lineage"
                        )
                    return _result_snapshot(row)
                if row.recovery_action_id != recovery_action_id:
                    raise PreExilePipelineRepositoryError(
                        "pre-exile vote already has durable recovery lineage"
                    )
            _require_result_state(row, "failed")
            _validate_vote_recovery_source(
                db,
                pipeline=pipeline,
                row=row,
            )
            opened = _validate_vote_recovery_action_opened(
                db,
                pipeline=pipeline,
                row=row,
                source_action_id=source_action_id,
                recovery_action_id=recovery_action_id,
            )
            response = (
                _event_at(
                    db,
                    game_id=pipeline.game_id,
                    run_id=pipeline.run_id,
                    record_seq=response_record_seq,
                    event_type="model_response_received",
                )
                if response_record_seq is not None
                else _find_accepted_model_response(
                    db,
                    game_id=pipeline.game_id,
                    run_id=pipeline.run_id,
                    action_id=recovery_action_id,
                )
            )
            terminal = (
                _event_at(
                    db,
                    game_id=pipeline.game_id,
                    run_id=pipeline.run_id,
                    record_seq=terminal_record_seq,
                    event_type="action_succeeded",
                )
                if terminal_record_seq is not None
                else _find_event(
                    db,
                    game_id=pipeline.game_id,
                    run_id=pipeline.run_id,
                    event_type="action_succeeded",
                    action_id=recovery_action_id,
                    latest=True,
                )
            )
            terminal_payload = _payload(terminal) if terminal is not None else {}
            if (
                terminal is None
                or terminal_payload.get("action_id") != recovery_action_id
                or opened.record_seq >= terminal.record_seq
            ):
                raise PreExilePipelineRepositoryError(
                    "pre-exile vote recovery has no durable action success"
                )
            recovery_failure: dict[str, Any] | None = None
            if response is not None:
                response_payload = _payload(response)
                parsed = response_payload.get("parsed_output")
                attempt_id = response_payload.get("attempt_id")
                target_id = parsed.get("target_player_id") if isinstance(parsed, dict) else None
                decision_note = parsed.get("decision_note") if isinstance(parsed, dict) else None
                candidates = _payload(opened).get("context", {}).get("candidates")
                candidate_ids = {
                    item.get("player_id")
                    for item in candidates or []
                    if isinstance(item, dict) and isinstance(item.get("player_id"), str)
                }
                if (
                    response_payload.get("action_id") != recovery_action_id
                    or not opened.record_seq < response.record_seq < terminal.record_seq
                    or response_payload.get("application_validation_result") != "accepted"
                    or not isinstance(attempt_id, str)
                    or not isinstance(target_id, str)
                    or target_id == actor_player_id
                    or target_id not in candidate_ids
                    or decision_note is not None
                    and not isinstance(decision_note, str)
                ):
                    raise PreExilePipelineRepositoryError(
                        "pre-exile vote recovery result is invalid"
                    )
                row.decision = {
                    "target_player_id": target_id,
                    "decision_note": decision_note,
                }
                row.state = "ready"
            else:
                supporting_seq = technical_outcome_record_seq
                if supporting_seq is None:
                    candidate = terminal_payload.get("technical_outcome_record_seq")
                    supporting_seq = candidate if type(candidate) is int else None
                if supporting_seq is None:
                    raise PreExilePipelineRepositoryError(
                        "pre-exile vote recovery has no response or technical outcome"
                    )
                technical = _event_at(
                    db,
                    game_id=pipeline.game_id,
                    run_id=pipeline.run_id,
                    record_seq=supporting_seq,
                    event_type="technical_target_outcome_applied",
                )
                technical_payload = _payload(technical)
                attempt_id = technical_payload.get("attempt_id")
                if (
                    technical_payload.get("action_id") != recovery_action_id
                    or terminal_payload.get("technical_outcome_record_seq") != supporting_seq
                    or not opened.record_seq < technical.record_seq < terminal.record_seq
                    or technical_payload.get("technical_outcome") != "technical_abstain"
                    or not isinstance(attempt_id, str)
                ):
                    raise PreExilePipelineRepositoryError(
                        "pre-exile vote recovery technical outcome is invalid"
                    )
                recovery_failure = {
                    "technical_outcome_record_seq": supporting_seq,
                    "technical_outcome": deepcopy(technical_payload),
                }
                row.decision = None
                row.state = "failed"
            initial_failure = deepcopy(row.failure or {})
            row.failure = (
                {
                    **(recovery_failure or {}),
                    "initial_admission_failure": initial_failure,
                }
                if recovery_failure is not None
                else {"initial_admission_failure": initial_failure}
            )
            row.recovery_action_id = recovery_action_id
            row.recovery_attempt_id = attempt_id
            row.recovery_response_record_seq = response.record_seq if response is not None else None
            row.recovery_terminal_record_seq = terminal.record_seq
            row.ready_at = _now()
            result_event = _append_result_recorded_event(
                db,
                game=game,
                run_id=run.run_id,
                pipeline=pipeline,
                row=row,
            )
            row.result_record_seq = result_event.record_seq
            db.flush()
            return _result_snapshot(row)

    def accept_votes(
        self,
        *,
        pipeline_id: str,
        expected_voter_ids: tuple[str, ...],
        fence: RunFence | None = None,
    ) -> tuple[PreExileResultSnapshot, ...]:
        del pipeline_id, expected_voter_ids, fence
        raise PreExilePipelineRepositoryError("pre_exile_atomic_vote_commit_required")

    def record_vote_degraded_abstain(
        self,
        *,
        pipeline_id: str,
        actor_player_id: str,
        source_action_id: str,
        recovery_action_id: str | None,
        failure_code: str,
        failure_category: str | None,
        failure_episode_id: str | None,
        fence: RunFence | None = None,
    ) -> PreExileResultSnapshot:
        """Degrade an unrecoverable failed vote into a durable technical abstain.

        A vote whose speculative attempt and its single recovery re-drive both
        failed must not kill the day runtime.  This records the degraded
        outcome durably so the commit gate sees the same technical-outcome
        lineage it expects from target-exhaustion abstains.
        """

        _canonical_id(source_action_id, field="source_action_id", maximum=48)
        if recovery_action_id is not None:
            _canonical_id(recovery_action_id, field="recovery_action_id", maximum=48)
        if not isinstance(failure_code, str) or not failure_code.strip():
            raise PreExilePipelineRepositoryError(
                "pre-exile degraded abstain requires a failure code"
            )
        with self._session_factory.begin() as db:
            game, run, pipeline, row = _locked_result(
                db,
                pipeline_id=pipeline_id,
                actor_player_id=actor_player_id,
                result_kind="exile_vote",
                fence=fence,
            )
            if pipeline.state not in {"collecting", "no_explosion"}:
                raise PreExilePipelineRepositoryError(
                    "pre-exile degraded abstain requires an open pipeline"
                )
            if row.action_id != source_action_id:
                raise PreExilePipelineRepositoryError(
                    "pre-exile degraded abstain source action changed"
                )
            if row.recovery_action_id != recovery_action_id:
                raise PreExilePipelineRepositoryError(
                    "pre-exile degraded abstain recovery lineage changed"
                )
            if (
                row.state == "failed"
                and isinstance(row.failure, dict)
                and row.failure.get("degraded_abstain") is True
            ):
                return _result_snapshot(row)
            _require_result_state(row, "failed")
            episode_id = failure_episode_id
            if not isinstance(episode_id, str) or not episode_id:
                episode_id = f"v2_episode_degraded_{row.result_id}"
            degraded_outcome = {
                "technical_outcome": "technical_abstain",
                "failure_code": failure_code,
                "failure_category": failure_category,
                "failure_episode_id": episode_id,
                "target_exhaustion_failure_mode": "model_failure_degraded",
                "action_id": source_action_id,
                "actor_id": actor_player_id,
                "degraded_from": (
                    "recovery_failed" if recovery_action_id is not None else "source_not_recoverable"
                ),
            }
            degraded_event = _append_raw_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="pre_exile_vote_degraded_to_abstain",
                payload={
                    "pipeline_id": pipeline.pipeline_id,
                    "pipeline_run_id": pipeline.run_id,
                    "phase_id": pipeline.phase_id,
                    "round_no": pipeline.round_no,
                    "result_id": row.result_id,
                    "actor_player_id": actor_player_id,
                    "action_id": source_action_id,
                    "recovery_action_id": recovery_action_id,
                    **degraded_outcome,
                },
            )
            row.failure = {
                "technical_outcome_record_seq": degraded_event.record_seq,
                "technical_outcome": degraded_outcome,
                "degraded_abstain": True,
                "initial_admission_failure": deepcopy(row.failure or {}),
            }
            row.decision = None
            row.terminal_record_seq = degraded_event.record_seq
            row.ready_at = _now()
            result_event = _append_result_recorded_event(
                db,
                game=game,
                run_id=run.run_id,
                pipeline=pipeline,
                row=row,
            )
            row.result_record_seq = result_event.record_seq
            db.flush()
            return _result_snapshot(row)

    def mark_consumed(
        self,
        *,
        pipeline_id: str,
        vote_batch_id: str,
        fence: RunFence | None = None,
    ) -> PreExilePipelineSnapshot:
        _canonical_id(vote_batch_id, field="vote_batch_id", maximum=180)
        with self._session_factory.begin() as db:
            game, run, pipeline = _locked_owned_pipeline(db, pipeline_id=pipeline_id, fence=fence)
            if pipeline.state == "consumed":
                if pipeline.vote_batch_id == vote_batch_id:
                    return _pipeline_snapshot(pipeline)
                raise PreExilePipelineRepositoryError(
                    "consumed pre-exile pipeline has different vote batch"
                )
            raise PreExilePipelineRepositoryError("pre_exile_atomic_vote_commit_required")

    def cancel_pipeline(
        self,
        *,
        pipeline_id: str,
        reason_code: str,
        fence: RunFence | None = None,
    ) -> PreExilePipelineSnapshot:
        return self._terminalize_pipeline(
            pipeline_id=pipeline_id,
            reason_code=reason_code,
            target_state="canceled",
            fence=fence,
        )

    def invalidate_pipeline(
        self,
        *,
        pipeline_id: str,
        reason_code: str,
        fence: RunFence | None = None,
    ) -> PreExilePipelineSnapshot:
        return self._terminalize_pipeline(
            pipeline_id=pipeline_id,
            reason_code=reason_code,
            target_state="invalidated",
            fence=fence,
        )

    def _terminalize_pipeline(
        self,
        *,
        pipeline_id: str,
        reason_code: str,
        target_state: Literal["canceled", "invalidated"],
        fence: RunFence | None,
    ) -> PreExilePipelineSnapshot:
        _canonical_id(reason_code, field="reason_code", maximum=120)
        with self._session_factory.begin() as db:
            if target_state == "canceled":
                game, run, pipeline = _locked_owned_pipeline(
                    db, pipeline_id=pipeline_id, fence=fence
                )
            else:
                game, run, pipeline = _locked_pipeline_for_invalidation(
                    db, pipeline_id=pipeline_id, fence=fence
                )
            if pipeline.state == target_state:
                if (pipeline.failure or {}).get("reason_code") == reason_code:
                    return _pipeline_snapshot(pipeline)
                raise PreExilePipelineRepositoryError(
                    f"{target_state} pre-exile pipeline has different reason"
                )
            if pipeline.state in _PIPELINE_TERMINAL_STATES:
                raise PreExilePipelineRepositoryError(
                    f"pre-exile pipeline is terminal ({pipeline.state})"
                )
            rows = list(
                db.scalars(
                    select(PreExileResult)
                    .where(PreExileResult.pipeline_id == pipeline.pipeline_id)
                    .with_for_update()
                )
            )
            _terminalize_result_actions(
                db,
                game=game,
                pipeline=pipeline,
                rows=rows,
                failure_code=f"pre_exile_pipeline_{target_state}",
                failure_stage=reason_code,
                failure_episode_disposition="isolated_action_failure",
            )
            now = _now()
            for row in rows:
                if row.state not in _RESULT_TERMINAL_STATES:
                    row.state = "discarded"
                    row.terminal_at = now
            pipeline.state = target_state
            pipeline.failure = {
                "kind": target_state,
                "reason_code": reason_code,
                "terminalized_by_run_id": run.run_id,
                "terminalized_by_worker_id": _required_worker_id(run),
                "terminalized_by_fence_token": run.fence_token,
            }
            pipeline.terminal_at = now
            _append_pipeline_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type=f"pre_exile_pipeline_{target_state}",
                row=pipeline,
                payload={
                    "reason_code": reason_code,
                    "pipeline_run_id": pipeline.run_id,
                    "discarded_result_count": sum(row.state == "discarded" for row in rows),
                },
            )
            db.flush()
            return _pipeline_snapshot(pipeline)


def _locked_game_and_fence(
    db: Session,
    *,
    game_id: str,
    fence: RunFence | None,
) -> tuple[GameRecord, GameRun]:
    game = db.scalar(select(GameRecord).where(GameRecord.game_id == game_id).with_for_update())
    if game is None:
        raise PreExilePipelineRepositoryError(f"unknown game {game_id}")
    try:
        run = require_run_fence(db, game, fence=fence)
    except RunFenceRejected as exc:
        raise ExecutionOwnershipLost(str(exc)) from exc
    return game, run


def _locked_owned_pipeline(
    db: Session,
    *,
    pipeline_id: str,
    fence: RunFence | None,
) -> tuple[GameRecord, GameRun, PreExilePipeline]:
    probe = db.get(PreExilePipeline, pipeline_id)
    if probe is None:
        raise PreExilePipelineRepositoryError(f"unknown pre-exile pipeline {pipeline_id}")
    game, run = _locked_game_and_fence(db, game_id=probe.game_id, fence=fence)
    row = db.scalar(
        select(PreExilePipeline)
        .where(PreExilePipeline.pipeline_id == pipeline_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    _require_owned_pipeline(row, run)
    if game.phase_id != row.phase_id:
        raise PreExilePipelineRepositoryError("pre-exile pipeline phase changed")
    return game, run, row


def _locked_pipeline_for_invalidation(
    db: Session,
    *,
    pipeline_id: str,
    fence: RunFence | None,
) -> tuple[GameRecord, GameRun, PreExilePipeline]:
    probe = db.get(PreExilePipeline, pipeline_id)
    if probe is None:
        raise PreExilePipelineRepositoryError(f"unknown pre-exile pipeline {pipeline_id}")
    game, run = _locked_game_and_fence(db, game_id=probe.game_id, fence=fence)
    row = db.scalar(
        select(PreExilePipeline)
        .where(PreExilePipeline.pipeline_id == pipeline_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return game, run, row


def _locked_result(
    db: Session,
    *,
    pipeline_id: str,
    actor_player_id: str,
    result_kind: PreExileResultKind,
    fence: RunFence | None,
) -> tuple[GameRecord, GameRun, PreExilePipeline, PreExileResult]:
    _result_kind(result_kind)
    game, run, pipeline = _locked_owned_pipeline(db, pipeline_id=pipeline_id, fence=fence)
    row = db.scalar(
        select(PreExileResult)
        .where(
            PreExileResult.pipeline_id == pipeline_id,
            PreExileResult.actor_player_id == actor_player_id,
            PreExileResult.result_kind == result_kind,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise PreExilePipelineRepositoryError(
            "pre-exile result must be reserved before recording"
        )
    return game, run, pipeline, row


def _validate_sealed_last_speech(
    db: Session,
    *,
    game: GameRecord,
    round_no: int,
    predecessor_action_id: str,
    predecessor_presentation_id: str,
    predecessor_source_event_id: int,
    predecessor_source_record_seq: int,
    predecessor_sealed_record_seq: int,
    public_cutoff_record_seq: int,
) -> None:
    open_presentations = list(
        db.scalars(
            select(LivePresentation).where(
                LivePresentation.game_id == game.game_id,
                LivePresentation.state.in_(tuple(_OPEN_PRESENTATION_STATES)),
            )
        )
    )
    if len(open_presentations) != 1:
        raise PreExilePipelineRepositoryError(
            "pre-exile predecessor is not the unique active presentation"
        )
    presentation = open_presentations[0]
    if (
        presentation.run_id != game.current_run_id
        or presentation.phase_id != game.phase_id
        or presentation.presentation_id != predecessor_presentation_id
        or presentation.action_id != predecessor_action_id
        or presentation.source_event_id != predecessor_source_event_id
        or presentation.audience not in _PUBLIC_AUDIENCES
        or presentation.closed_at is not None
    ):
        raise PreExilePipelineRepositoryError(
            "pre-exile predecessor presentation lineage is invalid"
        )
    source = _event_by_id(
        db,
        game_id=game.game_id,
        run_id=str(game.current_run_id),
        event_id=predecessor_source_event_id,
        event_type="speech_segment_committed",
    )
    if source.record_seq != predecessor_source_record_seq:
        raise PreExilePipelineRepositoryError("pre-exile predecessor source record changed")
    source_payload = _payload(source)
    if (
        source_payload.get("action_id") != predecessor_action_id
        or source_payload.get("presentation_id") != predecessor_presentation_id
        or source_payload.get("audience") not in _PUBLIC_AUDIENCES
        or source_payload.get("text") != presentation.subtitle_text
    ):
        raise PreExilePipelineRepositoryError("pre-exile predecessor source payload is invalid")
    sealed = _event_at(
        db,
        game_id=game.game_id,
        run_id=str(game.current_run_id),
        record_seq=predecessor_sealed_record_seq,
        event_type="speech_sealed",
    )
    sealed_payload = _payload(sealed)
    if (
        sealed_payload.get("action_id") != predecessor_action_id
        or sealed_payload.get("presentation_id") != predecessor_presentation_id
        or sealed_payload.get("audience") not in _PUBLIC_AUDIENCES
    ):
        raise PreExilePipelineRepositoryError("pre-exile predecessor sealed event is invalid")
    opened = _find_event(
        db,
        game_id=game.game_id,
        run_id=str(game.current_run_id),
        event_type="action_opened",
        action_id=predecessor_action_id,
        maximum_record_seq=predecessor_source_record_seq - 1,
    )
    context = _payload(opened).get("context") if opened is not None else None
    if type(context) is not dict:
        raise PreExilePipelineRepositoryError(
            "pre-exile predecessor action has no durable context"
        )
    speech_order = context.get("speech_order")
    speech_round = context.get("speech_round")
    final_round = max(1, int((game.rule_snapshot.get("rule_set") or {}).get("speech_rounds") or 1))
    actor = context.get("actor")
    action_type = context.get("action_type")
    technical_skip = action_type == "judge_day_speech_technical_skip"
    turn_player_id = (
        context.get("skipped_player_id")
        if technical_skip
        else (actor or {}).get("id")
        if isinstance(actor, dict)
        else None
    )
    if (
        type(speech_order) is not list
        or not speech_order
        or speech_order[-1] != turn_player_id
        or speech_round != final_round
    ):
        raise PreExilePipelineRepositoryError(
            "pre-exile predecessor is not the final discussion turn"
        )
    if technical_skip:
        public_skip_record_seq = context.get("public_skip_record_seq")
        if (
            resolve_day_speech_pipeline_contract(game.rule_snapshot).schema_version not in {2, 3}
            or actor != {"kind": "judge", "id": "judge"}
            or presentation.actor_kind != "judge"
            or presentation.actor_id != "judge"
            or type(public_skip_record_seq) is not int
            or public_skip_record_seq <= 0
            or public_skip_record_seq >= opened.record_seq
        ):
            raise PreExilePipelineRepositoryError(
                "pre-exile technical-skip predecessor identity is invalid"
            )
        public_skip = _event_at(
            db,
            game_id=game.game_id,
            run_id=str(game.current_run_id),
            record_seq=public_skip_record_seq,
            event_type="action_skipped_technical",
        )
        public_skip_payload = _payload(public_skip)
        if (
            public_skip_payload.get("audience") not in _PUBLIC_AUDIENCES
            or public_skip_payload.get("phase_id") != game.phase_id
            or public_skip_payload.get("round_no") != round_no
            or public_skip_payload.get("action_type") != "day_debate_speech"
            or public_skip_payload.get("actor_id") != turn_player_id
        ):
            raise PreExilePipelineRepositoryError(
                "pre-exile technical-skip predecessor has no public skip fact"
            )
    elif (
        action_type != "day_debate_speech"
        or actor != {"kind": "player", "id": turn_player_id}
        or presentation.actor_kind != "player"
        or presentation.actor_id != turn_player_id
    ):
        raise PreExilePipelineRepositoryError("pre-exile player predecessor identity is invalid")
    later_public = _find_public_speech_after(
        db,
        game_id=game.game_id,
        run_id=str(game.current_run_id),
        minimum_record_seq=predecessor_source_record_seq + 1,
        maximum_record_seq=public_cutoff_record_seq,
        excluding_presentation_id=predecessor_presentation_id,
    )
    if later_public is not None:
        raise PreExilePipelineRepositoryError("pre-exile cutoff contains a later public speech")


def _validate_success_result(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    row: PreExileResult,
    action_id: str,
    response_record_seq: int,
    terminal_record_seq: int,
    last_record_seq: int,
) -> tuple[str, dict[str, Any]]:
    if terminal_record_seq > last_record_seq:
        raise PreExilePipelineRepositoryError("pre-exile result is ahead of durable history")
    opened = _validate_result_action_opened(db, pipeline=pipeline, row=row, action_id=action_id)
    response = _event_at(
        db,
        game_id=pipeline.game_id,
        run_id=pipeline.run_id,
        record_seq=response_record_seq,
        event_type="model_response_received",
    )
    terminal = _event_at(
        db,
        game_id=pipeline.game_id,
        run_id=pipeline.run_id,
        record_seq=terminal_record_seq,
        event_type="action_succeeded",
    )
    response_payload = _payload(response)
    terminal_payload = _payload(terminal)
    parsed = response_payload.get("parsed_output")
    attempt_id = response_payload.get("attempt_id")
    if (
        opened.record_seq >= response_record_seq
        or response_payload.get("action_id") != action_id
        or response_payload.get("application_validation_result") != "accepted"
        or type(parsed) is not dict
        or not isinstance(attempt_id, str)
        or not attempt_id
        or terminal_payload.get("action_id") != action_id
    ):
        raise PreExilePipelineRepositoryError("pre-exile model result lineage is invalid")
    _canonical_id(attempt_id, field="attempt_id", maximum=48)
    decision_note = parsed.get("decision_note")
    if decision_note is not None and not isinstance(decision_note, str):
        raise PreExilePipelineRepositoryError("pre-exile result decision note is invalid")
    if row.result_kind == "self_explosion":
        explode = parsed.get("explode")
        if not isinstance(explode, bool):
            raise PreExilePipelineRepositoryError("pre-exile self-explosion result is invalid")
        decision = {"explode": explode, "decision_note": decision_note}
    else:
        target_id = parsed.get("target_player_id")
        _canonical_id(target_id, field="target_player_id", maximum=80)
        context = _payload(opened).get("context")
        candidates = context.get("candidates") if isinstance(context, dict) else None
        candidate_ids = {
            item.get("player_id")
            for item in candidates or []
            if isinstance(item, dict) and isinstance(item.get("player_id"), str)
        }
        if target_id == row.actor_player_id or target_id not in candidate_ids:
            raise PreExilePipelineRepositoryError(
                "pre-exile vote target left its frozen candidate set"
            )
        decision = {"target_player_id": target_id, "decision_note": decision_note}
    return attempt_id, decision


def _validate_failure_result(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    row: PreExileResult,
    action_id: str,
    failure_record_seq: int,
    last_record_seq: int,
) -> tuple[dict[str, Any], str | None]:
    if failure_record_seq > last_record_seq:
        raise PreExilePipelineRepositoryError("pre-exile failure is ahead of durable history")
    opened = _validate_result_action_opened(db, pipeline=pipeline, row=row, action_id=action_id)
    failed = _event_at(
        db,
        game_id=pipeline.game_id,
        run_id=pipeline.run_id,
        record_seq=failure_record_seq,
        event_type="action_failed",
    )
    payload = _payload(failed)
    if opened.record_seq >= failure_record_seq or payload.get("action_id") != action_id:
        raise PreExilePipelineRepositoryError("pre-exile action failure lineage is invalid")
    request_failure = _find_event(
        db,
        game_id=pipeline.game_id,
        run_id=pipeline.run_id,
        event_type="model_request_failed",
        action_id=action_id,
        minimum_record_seq=opened.record_seq + 1,
        maximum_record_seq=failure_record_seq - 1,
        latest=True,
    )
    request_payload = deepcopy(_payload(request_failure)) if request_failure is not None else None
    attempt_id = request_payload.get("attempt_id") if isinstance(request_payload, dict) else None
    if attempt_id is not None:
        _canonical_id(attempt_id, field="attempt_id", maximum=48)
    return (
        {
            "action_failed_record_seq": failure_record_seq,
            "action_failed": deepcopy(payload),
            "model_request_failed_record_seq": (
                request_failure.record_seq if request_failure is not None else None
            ),
            "model_request_failed": request_payload,
        },
        attempt_id,
    )


def _validate_result_action_opened(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    row: PreExileResult,
    action_id: str,
) -> GameRecordEvent:
    opened = _find_event(
        db,
        game_id=pipeline.game_id,
        run_id=pipeline.run_id,
        event_type="action_opened",
        action_id=action_id,
    )
    context = _payload(opened).get("context") if opened is not None else None
    pipeline_context = context.get("pipeline") if isinstance(context, dict) else None
    expected_action_type = (
        "werewolf_self_explosion" if row.result_kind == "self_explosion" else "exile_vote"
    )
    game = db.get(GameRecord, pipeline.game_id)
    if game is None:
        raise PreExilePipelineRepositoryError("pre-exile action game is missing")
    contract = resolve_pre_exile_pipeline_contract(game.rule_snapshot)
    expected_admission = (
        contract.self_explosion_admission_mode
        if row.result_kind == "self_explosion"
        else contract.speculative_vote_admission_mode
    )
    guarded_self_explosion_retry = (
        row.result_kind == "self_explosion"
        and contract.self_explosion_early_empty_stream_hidden_retry_max_retries == 1
    )
    expected_pipeline_context = {
        "kind": "pre_exile",
        "pipeline_id": pipeline.pipeline_id,
        "result_kind": row.result_kind,
        "stage": "generation",
        "model_admission_mode": expected_admission,
        **(
            {
                "retry_mode": "empty_stream_once_while_predecessor_active",
                "empty_stream_max_attempts": (
                    1 + contract.self_explosion_early_empty_stream_hidden_retry_max_retries
                ),
            }
            if guarded_self_explosion_retry
            else {}
        ),
    }
    if (
        opened is None
        or type(context) is not dict
        or type(pipeline_context) is not dict
        or pipeline_context != expected_pipeline_context
        or context.get("action_id") != action_id
        or context.get("action_type") != expected_action_type
        or context.get("game_id") != pipeline.game_id
        or context.get("phase_id") != pipeline.phase_id
        or context.get("actor") != {"kind": "player", "id": row.actor_player_id}
        or context.get("public_history_cutoff_record_seq") != pipeline.public_cutoff_record_seq
    ):
        raise PreExilePipelineRepositoryError(
            "pre-exile action opened context lineage is invalid"
        )
    return opened


def _validate_vote_recovery_source(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    row: PreExileResult,
) -> None:
    failure = row.failure or {}
    request_failure = failure.get("model_request_failed")
    if (
        not isinstance(request_failure, dict)
        or request_failure.get("action_id") != row.action_id
    ):
        raise PreExilePipelineRepositoryError(
            "pre-exile vote recovery requires a recorded model request failure"
        )
    category = request_failure.get("failure_category")
    if category not in RECOVERABLE_PRE_EXILE_VOTE_CATEGORIES:
        raise PreExilePipelineRepositoryError(
            "pre-exile vote recovery requires a recoverable failure category"
        )
    if category != "admission_capacity":
        # Transport/timeout failures already completed a full attempt against
        # the provider; re-driving starts a fresh request, so the
        # never-reached-provider guard below does not apply to them.
        return
    if (
        request_failure.get("failure_stage") != "provider_admission"
        or request_failure.get("failure_code") != "model_prefetch_capacity_unavailable"
    ):
        raise PreExilePipelineRepositoryError(
            "pre-exile vote recovery requires an admission-capacity source"
        )
    forbidden_types = {
        "model_request_admitted",
        "model_response_headers_received",
        "model_first_token_received",
        "model_response_received",
    }
    events = list(
        db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == pipeline.game_id,
                GameRecordEvent.run_id == pipeline.run_id,
                GameRecordEvent.event_type.in_(forbidden_types),
            )
        )
    )
    if any(
        isinstance(event.payload, dict) and event.payload.get("action_id") == row.action_id
        for event in events
    ):
        raise PreExilePipelineRepositoryError(
            "pre-exile vote source reached the provider and cannot be repeated"
        )


def _validate_vote_recovery_action_opened(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    row: PreExileResult,
    source_action_id: str,
    recovery_action_id: str,
) -> GameRecordEvent:
    opened = _find_event(
        db,
        game_id=pipeline.game_id,
        run_id=pipeline.run_id,
        event_type="action_opened",
        action_id=recovery_action_id,
    )
    context = _payload(opened).get("context") if opened is not None else None
    recovery = context.get("pre_exile_recovery") if isinstance(context, dict) else None
    expected_batch_id = f"{pipeline.phase_id}:exile_vote:{pipeline.public_cutoff_record_seq}:vote"
    if (
        opened is None
        or type(context) is not dict
        or context.get("action_type") != "exile_vote"
        or context.get("game_id") != pipeline.game_id
        or context.get("phase_id") != pipeline.phase_id
        or context.get("actor") != {"kind": "player", "id": row.actor_player_id}
        or context.get("batch_id") != expected_batch_id
        or context.get("public_history_cutoff_record_seq") != pipeline.public_cutoff_record_seq
        or "pipeline" in context
        or recovery
        != {
            "pipeline_id": pipeline.pipeline_id,
            "result_id": row.result_id,
            "source_action_id": source_action_id,
            "model_admission_mode": "normal",
        }
    ):
        raise PreExilePipelineRepositoryError("pre-exile vote recovery action lineage is invalid")
    return opened


def _persist_self_explosion_fact(
    db: Session,
    *,
    game: GameRecord,
    pipeline: PreExilePipeline,
    row: PreExileResult,
    decision: dict[str, Any],
    decision_status: str,
) -> tuple[str, int]:
    fact_id = _deterministic_id("v2_fact_", row.result_id, "self_explosion")
    existing = db.get(KnowledgeFact, fact_id)
    payload = {
        "schema_version": 1,
        "round_no": pipeline.round_no,
        "action_type": "werewolf_self_explosion",
        "decision": {"explode": bool(decision.get("explode"))},
        "decision_status": decision_status,
        "source_action_id": row.action_id,
        "context": {
            "pipeline_id": pipeline.pipeline_id,
            "public_history_cutoff_record_seq": pipeline.public_cutoff_record_seq,
            "visibility_mode": "pre_exile_provisional_until_atomic_arbiter",
        },
        **(
            {
                "declared_reason": {
                    "text": decision["decision_note"].strip(),
                    "epistemic_status": "actor_declared_reason",
                }
            }
            if isinstance(decision.get("decision_note"), str) and decision["decision_note"].strip()
            else {}
        ),
    }
    if existing is not None:
        if (
            existing.game_id != game.game_id
            or existing.owner_scope != "player"
            or existing.owner_id != row.actor_player_id
            or existing.fact_type != "private_action_decision"
            or existing.payload != payload
        ):
            raise PreExilePipelineRepositoryError(
                "pre-exile private fact conflicts with durable fact"
            )
        matching_events = [
            event
            for event in db.scalars(
                select(GameRecordEvent).where(
                    GameRecordEvent.game_id == game.game_id,
                    GameRecordEvent.run_id == pipeline.run_id,
                    GameRecordEvent.event_type == "private_knowledge_recorded",
                    GameRecordEvent.record_seq > pipeline.public_cutoff_record_seq,
                )
            )
            if _payload(event).get("knowledge_fact_id") == fact_id
        ]
        if len(matching_events) != 1:
            raise PreExilePipelineRepositoryError(
                "pre-exile private fact has no durable record event"
            )
        event = matching_events[0]
        return fact_id, event.record_seq
    db.add(
        KnowledgeFact(
            knowledge_fact_id=fact_id,
            game_id=game.game_id,
            source_activation_id=None,
            owner_scope="player",
            owner_id=row.actor_player_id,
            fact_type="private_action_decision",
            payload=payload,
        )
    )
    event = _append_pipeline_event(
        db,
        game=game,
        run_id=pipeline.run_id,
        event_type="private_knowledge_recorded",
        row=pipeline,
        payload={
            "knowledge_fact_id": fact_id,
            "owner_scope": "player",
            "owner_id": row.actor_player_id,
            "fact_type": "private_action_decision",
            "round_no": pipeline.round_no,
            "action_type": "werewolf_self_explosion",
            "source_action_id": row.action_id,
        },
    )
    return fact_id, event.record_seq


def _append_result_recorded_event(
    db: Session,
    *,
    game: GameRecord,
    run_id: str,
    pipeline: PreExilePipeline,
    row: PreExileResult,
) -> GameRecordEvent:
    return _append_pipeline_event(
        db,
        game=game,
        run_id=run_id,
        event_type="pre_exile_result_recorded",
        row=pipeline,
        payload={
            "result_id": row.result_id,
            "result_kind": row.result_kind,
            "actor_player_id": row.actor_player_id,
            "result_state": row.state,
            "action_id": row.action_id,
            "recovery_action_id": row.recovery_action_id,
            "recovery_attempt_id": row.recovery_attempt_id,
            "recovery_response_record_seq": row.recovery_response_record_seq,
            "recovery_terminal_record_seq": row.recovery_terminal_record_seq,
            "attempt_id": row.attempt_id,
            "response_record_seq": row.response_record_seq,
            "terminal_record_seq": row.terminal_record_seq,
            "failure_record_seq": row.failure_record_seq,
            "private_fact_id": row.private_fact_id,
            "private_fact_record_seq": row.private_fact_record_seq,
            "result_sha256": _json_sha256(
                row.decision if row.decision is not None else row.failure or {}
            ),
        },
    )


def _validate_predecessor_closed(
    db: Session,
    *,
    pipeline: PreExilePipeline,
) -> int:
    presentation = db.scalar(
        select(LivePresentation).where(
            LivePresentation.game_id == pipeline.game_id,
            LivePresentation.presentation_id == pipeline.predecessor_presentation_id,
        )
    )
    if (
        presentation is None
        or presentation.run_id != pipeline.run_id
        or presentation.action_id != pipeline.predecessor_action_id
        or presentation.state != "closed"
        or presentation.closed_at is None
    ):
        raise PreExilePipelineRepositoryError(
            "pre-exile votes cannot be accepted before predecessor close"
        )
    closed = _find_event(
        db,
        game_id=pipeline.game_id,
        run_id=pipeline.run_id,
        event_type="speech_closed",
        action_id=pipeline.predecessor_action_id,
        presentation_id=pipeline.predecessor_presentation_id,
        minimum_record_seq=pipeline.predecessor_sealed_record_seq + 1,
    )
    if closed is None:
        raise PreExilePipelineRepositoryError("pre-exile predecessor has no durable close event")
    return closed.record_seq


def _terminalize_result_actions(
    db: Session,
    *,
    game: GameRecord,
    pipeline: PreExilePipeline,
    rows: list[PreExileResult],
    failure_code: str,
    failure_stage: str,
    failure_episode_disposition: Literal["isolated_action_failure"] | None = None,
) -> None:
    action_ids = tuple(
        sorted(
            {
                action_id
                for row in rows
                for action_id in (
                    row.action_id if row.state == "generating" else None,
                    (
                        row.recovery_action_id
                        if row.recovery_action_id is not None
                        and row.recovery_terminal_record_seq is None
                        else None
                    ),
                )
                if isinstance(action_id, str)
            }
        )
    )
    if not action_ids:
        return
    events = list(
        db.scalars(
            select(GameRecordEvent)
            .where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.run_id == pipeline.run_id,
            )
            .order_by(GameRecordEvent.record_seq)
        )
    )
    terminal_actions: set[str] = set()
    terminal_attempts: set[str] = set()
    starts: dict[str, list[GameRecordEvent]] = {action_id: [] for action_id in action_ids}
    opened: dict[str, GameRecordEvent] = {}
    open_episode_ids: dict[str, set[str]] = {action_id: set() for action_id in action_ids}
    for episode in derive_failure_episodes(events):
        if episode.is_open and episode.action_id in open_episode_ids:
            open_episode_ids[str(episode.action_id)].add(episode.failure_episode_id)
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        action_id = payload.get("action_id")
        if action_id not in starts:
            continue
        if event.event_type == "action_opened":
            opened[str(action_id)] = event
        elif event.event_type in {"action_succeeded", "action_failed"}:
            terminal_actions.add(str(action_id))
        elif event.event_type == "model_request_started":
            starts[str(action_id)].append(event)
        elif event.event_type in {"model_response_received", "model_request_failed"}:
            attempt_id = payload.get("attempt_id")
            if isinstance(attempt_id, str):
                terminal_attempts.add(attempt_id)
    for action_id in action_ids:
        for started in starts[action_id]:
            payload = _payload(started)
            attempt_id = payload.get("attempt_id")
            if not isinstance(attempt_id, str) or attempt_id in terminal_attempts:
                continue
            retry_cycle = _positive_event_int(payload.get("retry_cycle"), default=1)
            failure_episode_id = payload.get("failure_episode_id")
            if not isinstance(failure_episode_id, str) or not failure_episode_id:
                failure_episode_id = stable_failure_episode_id(
                    game_id=game.game_id,
                    run_id=pipeline.run_id,
                    action_id=action_id,
                    retry_cycle=retry_cycle,
                    first_failed_attempt_id=attempt_id,
                )
            open_episode_ids[action_id].add(failure_episode_id)
            _append_raw_event(
                db,
                game=game,
                run_id=pipeline.run_id,
                event_type="model_request_failed",
                payload={
                    "action_id": action_id,
                    "attempt_id": attempt_id,
                    "attempt_no": _positive_event_int(payload.get("attempt_no"), default=1),
                    "cycle_attempt_no": _positive_event_int(
                        payload.get("cycle_attempt_no"), default=1
                    ),
                    "retry_cycle": retry_cycle,
                    "max_attempts": _positive_event_int(payload.get("max_attempts"), default=1),
                    "failure_kind": "canceled",
                    "failure_code": failure_code,
                    "failure_category": "canceled",
                    "failure_episode_id": failure_episode_id,
                    "retryable": False,
                    "attempt_terminal": True,
                    "action_recoverable": False,
                    "run_terminal": False,
                    "terminal": True,
                    "automatic_retry_scheduled": False,
                    "automatic_retry_stop_reason": "not_retryable",
                    "failure_stage": failure_stage,
                    "provider_outcome_unknown": True,
                },
            )
            terminal_attempts.add(attempt_id)
        if action_id in terminal_actions or action_id not in opened:
            continue
        action_episode_ids = open_episode_ids[action_id]
        if failure_episode_disposition is not None and len(action_episode_ids) > 1:
            raise PreExilePipelineRepositoryError(
                "pre-exile action has multiple open failure episodes"
            )
        failure_episode_id = (
            next(iter(action_episode_ids)) if len(action_episode_ids) == 1 else None
        )
        _append_raw_event(
            db,
            game=game,
            run_id=pipeline.run_id,
            event_type="action_failed",
            payload={
                "action_id": action_id,
                "activation_id": _payload(opened[action_id]).get("activation_id"),
                "presentation_id": None,
                "tts_attempt_id": None,
                "failure_kind": "canceled",
                "failure_code": failure_code,
                "cancellation_reason_code": failure_stage,
                **(
                    {
                        "failure_episode_id": failure_episode_id,
                        "failure_episode_disposition": failure_episode_disposition,
                    }
                    if failure_episode_id is not None and failure_episode_disposition is not None
                    else {}
                ),
            },
        )


def _validate_expected_wolves(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    expected: tuple[str, ...],
) -> None:
    rows = list(
        db.execute(
            select(RoleAssignment.player_id, PlayerState.alive)
            .join(
                PlayerState,
                (PlayerState.game_id == RoleAssignment.game_id)
                & (PlayerState.player_id == RoleAssignment.player_id),
            )
            .where(
                RoleAssignment.game_id == pipeline.game_id,
                RoleAssignment.role_key == "werewolf",
            )
        )
    )
    alive_wolves = {player_id for player_id, alive in rows if alive}
    if set(expected) != alive_wolves:
        raise PreExilePipelineRepositoryError(
            "expected pre-exile wolves changed from durable roster"
        )


def _existing_explosion_resolution(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    expected: tuple[str, ...],
) -> PreExileExplosionResolution:
    rows = list(
        db.scalars(
            select(PreExileResult).where(
                PreExileResult.pipeline_id == pipeline.pipeline_id,
                PreExileResult.result_kind == "self_explosion",
            )
        )
    )
    by_actor = {row.actor_player_id: row for row in rows}
    if set(by_actor) != set(expected):
        raise PreExilePipelineRepositoryError("resolved pre-exile wolf membership changed")
    failed = tuple(actor_id for actor_id in expected if by_actor[actor_id].state == "failed")
    selected = pipeline.selected_explosion_player_id
    return PreExileExplosionResolution(
        outcome="explosion_selected" if selected is not None else "no_explosion",
        selected_player_id=selected,
        failed_player_ids=failed,
    )


def _ordered_vote_results(
    db: Session,
    *,
    pipeline_id: str,
    lock: bool = False,
) -> list[PreExileResult]:
    statement = (
        select(PreExileResult)
        .where(
            PreExileResult.pipeline_id == pipeline_id,
            PreExileResult.result_kind == "exile_vote",
        )
        .order_by(PreExileResult.actor_player_id)
    )
    if lock:
        statement = statement.with_for_update()
    return list(db.scalars(statement))


def _require_expected_results(
    rows: list[PreExileResult],
    *,
    expected: tuple[str, ...],
    states: set[str],
) -> None:
    by_actor = {row.actor_player_id: row for row in rows}
    if set(by_actor) != set(expected) or any(row.state not in states for row in rows):
        raise PreExilePipelineRepositoryError("pre-exile speculative vote batch is incomplete")


def _require_no_day_vote_events(
    db: Session,
    *,
    pipeline: PreExilePipeline,
) -> None:
    event = db.scalar(
        select(GameRecordEvent).where(
            GameRecordEvent.game_id == pipeline.game_id,
            GameRecordEvent.run_id == pipeline.run_id,
            GameRecordEvent.record_seq > pipeline.predecessor_sealed_record_seq,
            GameRecordEvent.event_type.in_(("day_vote_committed", "day_vote_resolved")),
        )
    )
    if event is not None:
        raise PreExilePipelineRepositoryError(
            "self-explosion cannot discard votes after public vote commit"
        )


def _seat_by_player(
    db: Session,
    *,
    game_id: str,
    player_ids: tuple[str, ...],
) -> dict[str, int]:
    rows = list(
        db.execute(
            select(RoleAssignment.player_id, RoleAssignment.seat).where(
                RoleAssignment.game_id == game_id,
                RoleAssignment.player_id.in_(player_ids),
            )
        )
    )
    seats = {player_id: seat for player_id, seat in rows}
    if set(seats) != set(player_ids):
        raise PreExilePipelineRepositoryError("pre-exile result roster is incomplete")
    return seats


def _find_public_speech_after(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    minimum_record_seq: int,
    maximum_record_seq: int,
    excluding_presentation_id: str,
) -> GameRecordEvent | None:
    statement = (
        select(GameRecordEvent)
        .where(
            GameRecordEvent.game_id == game_id,
            GameRecordEvent.run_id == run_id,
            GameRecordEvent.event_type == "speech_segment_committed",
            GameRecordEvent.record_seq >= minimum_record_seq,
            GameRecordEvent.record_seq <= maximum_record_seq,
        )
        .order_by(GameRecordEvent.record_seq)
    )
    for event in db.scalars(statement):
        payload = _payload(event)
        if (
            payload.get("audience") in _PUBLIC_AUDIENCES
            and payload.get("presentation_id") != excluding_presentation_id
        ):
            return event
    return None


def _event_at(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    record_seq: int,
    event_type: str,
) -> GameRecordEvent:
    event = db.scalar(
        select(GameRecordEvent).where(
            GameRecordEvent.game_id == game_id,
            GameRecordEvent.record_seq == record_seq,
        )
    )
    if event is None or event.run_id != run_id or event.event_type != event_type:
        raise PreExilePipelineRepositoryError(
            f"invalid {event_type} lineage at record {record_seq}"
        )
    return event


def _event_at_any(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    record_seq: int,
    event_types: set[str],
) -> GameRecordEvent:
    event = db.scalar(
        select(GameRecordEvent).where(
            GameRecordEvent.game_id == game_id,
            GameRecordEvent.record_seq == record_seq,
        )
    )
    if event is None or event.run_id != run_id or event.event_type not in event_types:
        raise PreExilePipelineRepositoryError(
            f"invalid technical result lineage at record {record_seq}"
        )
    return event


def _event_by_id(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    event_id: int,
    event_type: str,
) -> GameRecordEvent:
    event = db.get(GameRecordEvent, (game_id, event_id))
    if event is None or event.run_id != run_id or event.event_type != event_type:
        raise PreExilePipelineRepositoryError(f"invalid {event_type} lineage at event {event_id}")
    return event


def _find_event(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    event_type: str,
    action_id: str | None = None,
    presentation_id: str | None = None,
    minimum_record_seq: int | None = None,
    maximum_record_seq: int | None = None,
    latest: bool = False,
) -> GameRecordEvent | None:
    statement = select(GameRecordEvent).where(
        GameRecordEvent.game_id == game_id,
        GameRecordEvent.run_id == run_id,
        GameRecordEvent.event_type == event_type,
    )
    if minimum_record_seq is not None:
        statement = statement.where(GameRecordEvent.record_seq >= minimum_record_seq)
    if maximum_record_seq is not None:
        statement = statement.where(GameRecordEvent.record_seq <= maximum_record_seq)
    statement = statement.order_by(
        GameRecordEvent.record_seq.desc() if latest else GameRecordEvent.record_seq
    )
    for event in db.scalars(statement):
        payload = _payload(event)
        if action_id is not None and payload.get("action_id") != action_id:
            continue
        if presentation_id is not None and payload.get("presentation_id") != presentation_id:
            continue
        return event
    return None


def _find_accepted_model_response(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    action_id: str,
) -> GameRecordEvent | None:
    rows = db.scalars(
        select(GameRecordEvent)
        .where(
            GameRecordEvent.game_id == game_id,
            GameRecordEvent.run_id == run_id,
            GameRecordEvent.event_type == "model_response_received",
        )
        .order_by(GameRecordEvent.record_seq.desc())
    )
    for event in rows:
        payload = _payload(event)
        if (
            payload.get("action_id") == action_id
            and payload.get("application_validation_result") == "accepted"
        ):
            return event
    return None


def _append_pipeline_event(
    db: Session,
    *,
    game: GameRecord,
    run_id: str,
    event_type: str,
    row: PreExilePipeline,
    payload: dict[str, Any],
) -> GameRecordEvent:
    return _append_raw_event(
        db,
        game=game,
        run_id=run_id,
        event_type=event_type,
        payload={
            "pipeline_id": row.pipeline_id,
            "pipeline_run_id": row.run_id,
            "phase_id": row.phase_id,
            "round_no": row.round_no,
            "state": row.state,
            **payload,
        },
    )


def _append_raw_event(
    db: Session,
    *,
    game: GameRecord,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> GameRecordEvent:
    next_seq = game.last_record_seq + 1
    event = GameRecordEvent(
        game_id=game.game_id,
        event_id=next_seq,
        record_seq=next_seq,
        run_id=run_id,
        event_type=event_type,
        payload_schema_version=1,
        payload=canonical_event_payload(payload, audience="god_view"),
    )
    db.add(event)
    game.last_record_seq = next_seq
    return event


def _pipeline_snapshot(row: PreExilePipeline) -> PreExilePipelineSnapshot:
    return PreExilePipelineSnapshot(
        pipeline_id=row.pipeline_id,
        game_id=row.game_id,
        run_id=row.run_id,
        fence_worker_id=row.fence_worker_id,
        fence_token=row.fence_token,
        phase_id=row.phase_id,
        round_no=row.round_no,
        predecessor_action_id=row.predecessor_action_id,
        predecessor_presentation_id=row.predecessor_presentation_id,
        predecessor_source_event_id=row.predecessor_source_event_id,
        predecessor_source_record_seq=row.predecessor_source_record_seq,
        predecessor_sealed_record_seq=row.predecessor_sealed_record_seq,
        public_cutoff_record_seq=row.public_cutoff_record_seq,
        public_history_sha256=row.public_history_sha256,
        state=row.state,  # type: ignore[arg-type]
        selected_explosion_player_id=row.selected_explosion_player_id,
        vote_batch_id=row.vote_batch_id,
        vote_decision_context_sha256=row.vote_decision_context_sha256,
        failure=deepcopy(row.failure),
        created_at=row.created_at,
        updated_at=row.updated_at,
        explosion_resolved_at=row.explosion_resolved_at,
        votes_accepted_at=row.votes_accepted_at,
        consumed_at=row.consumed_at,
        terminal_at=row.terminal_at,
    )


def _result_snapshot(row: PreExileResult) -> PreExileResultSnapshot:
    return PreExileResultSnapshot(
        result_id=row.result_id,
        pipeline_id=row.pipeline_id,
        game_id=row.game_id,
        actor_player_id=row.actor_player_id,
        result_kind=row.result_kind,  # type: ignore[arg-type]
        state=row.state,  # type: ignore[arg-type]
        action_id=row.action_id,
        recovery_action_id=row.recovery_action_id,
        recovery_attempt_id=row.recovery_attempt_id,
        recovery_response_record_seq=row.recovery_response_record_seq,
        recovery_terminal_record_seq=row.recovery_terminal_record_seq,
        attempt_id=row.attempt_id,
        response_record_seq=row.response_record_seq,
        terminal_record_seq=row.terminal_record_seq,
        result_record_seq=row.result_record_seq,
        decision=deepcopy(row.decision),
        failure_record_seq=row.failure_record_seq,
        failure=deepcopy(row.failure),
        private_fact_id=row.private_fact_id,
        private_fact_record_seq=row.private_fact_record_seq,
        created_at=row.created_at,
        updated_at=row.updated_at,
        generation_started_at=row.generation_started_at,
        ready_at=row.ready_at,
        terminal_at=row.terminal_at,
    )


def _require_owned_pipeline(row: PreExilePipeline, run: GameRun) -> None:
    if (
        row.run_id != run.run_id
        or row.fence_worker_id != run.worker_id
        or row.fence_token != run.fence_token
    ):
        raise ExecutionOwnershipLost("v2_pre_exile_pipeline_fence_lost")


def _required_worker_id(run: GameRun) -> str:
    if not isinstance(run.worker_id, str) or not run.worker_id:
        raise ExecutionOwnershipLost("v2_run_execution_lease_missing")
    return run.worker_id


def _raise_if_stop_requested(run: GameRun) -> None:
    if run.stop_requested_at is not None:
        raise PreExilePipelineRepositoryError("V2 game stop was requested")


def _require_pipeline_state(row: PreExilePipeline, *expected: str) -> None:
    if row.state not in expected:
        raise PreExilePipelineRepositoryError(
            f"pre-exile pipeline {row.pipeline_id} cannot transition from {row.state}; "
            f"expected {','.join(expected)}"
        )


def _require_result_state(row: PreExileResult, *expected: str) -> None:
    if row.state not in expected:
        raise PreExilePipelineRepositoryError(
            f"pre-exile result {row.result_id} cannot transition from {row.state}; "
            f"expected {','.join(expected)}"
        )


def _result_kind(value: Any) -> PreExileResultKind:
    if value not in {"self_explosion", "exile_vote"}:
        raise PreExilePipelineRepositoryError("invalid result_kind")
    return value


def _canonical_member_ids(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise PreExilePipelineRepositoryError(f"invalid {field}")
    normalized = tuple(_canonical_id(value, field=field, maximum=80) for value in values)
    if len(set(normalized)) != len(normalized):
        raise PreExilePipelineRepositoryError(f"duplicate {field}")
    return normalized


def _canonical_id(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > maximum:
        raise PreExilePipelineRepositoryError(f"invalid {field}")
    return value


def _positive_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise PreExilePipelineRepositoryError(f"invalid {field}")
    return value


def _positive_event_int(value: object, *, default: int) -> int:
    return value if type(value) is int and value > 0 else default


def _payload(event: GameRecordEvent) -> dict[str, Any]:
    if type(event.payload) is not dict:
        raise PreExilePipelineRepositoryError(
            f"invalid payload for {event.event_type} at record {event.record_seq}"
        )
    return event.payload


def _deterministic_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}{digest}"


def _json_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_set_sha256(rows: list[PreExileResult]) -> str:
    return _json_sha256(
        {
            row.result_id: {
                "state": row.state,
                "result_sha256": _json_sha256(
                    row.decision if row.decision is not None else row.failure or {}
                ),
            }
            for row in rows
        }
    )


def _now() -> datetime:
    return datetime.now(tz=UTC)


__all__ = [
    "PreExileExplosionResolution",
    "PreExilePipelineRepository",
    "PreExilePipelineRepositoryError",
    "PreExilePipelineSnapshot",
    "PreExileResultKind",
    "PreExileResultSnapshot",
]
