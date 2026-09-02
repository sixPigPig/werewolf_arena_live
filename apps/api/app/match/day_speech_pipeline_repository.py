from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.match.day_speech_pipeline_contract import resolve_day_speech_pipeline_contract
from app.match.event_contract import canonical_event_payload
from app.match.execution import RunFence, RunFenceRejected, require_run_fence
from app.match.models import (
    DaySpeechSlot,
    GameRecord,
    GameRecordEvent,
    GameRun,
    LivePresentation,
    PlayerState,
    VoiceAsset,
)
from app.match.repository import ExecutionOwnershipLost, RepositoryError


DaySpeechSlotState = Literal[
    "reserved",
    "generating",
    "ready",
    "presenting",
    "consumed",
    "failed",
    "canceled",
    "invalidated",
]

_TERMINAL_STATES = frozenset({"consumed", "failed", "canceled", "invalidated"})
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


class DaySpeechPipelineRepositoryError(RepositoryError):
    pass


@dataclass(frozen=True)
class DaySpeechSlotSnapshot:
    slot_id: str
    game_id: str
    run_id: str
    fence_worker_id: str
    fence_token: int
    phase_id: str
    round_no: int
    speech_round: int
    turn_index: int
    action_type: str
    actor_player_id: str
    predecessor_action_id: str
    predecessor_presentation_id: str
    predecessor_source_event_id: int
    predecessor_source_record_seq: int
    context_cutoff_record_seq: int
    state: DaySpeechSlotState
    generation_action_id: str | None
    generation_attempt_id: str | None
    generation_response_record_seq: int | None
    decision: dict[str, Any] | None
    presentation_action_id: str | None
    presentation_id: str | None
    failure_record_seq: int | None
    failure: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    generation_started_at: datetime | None
    ready_at: datetime | None
    presenting_at: datetime | None
    consumed_at: datetime | None
    terminal_at: datetime | None


class DaySpeechPipelineRepository:
    """Durable, fenced state machine for one-ahead public day speeches."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_slot(self, slot_id: str) -> DaySpeechSlotSnapshot:
        with self._session_factory() as db:
            row = db.get(DaySpeechSlot, slot_id)
            if row is None:
                raise DaySpeechPipelineRepositoryError(f"unknown day speech slot {slot_id}")
            return _snapshot(row)

    def predecessor_is_active(self, slot_id: str) -> bool:
        """Return whether a hidden retry still fits inside predecessor playback."""

        with self._session_factory() as db:
            row = db.get(DaySpeechSlot, slot_id)
            if row is None or row.state != "generating":
                return False
            game = db.get(GameRecord, row.game_id)
            run = db.get(GameRun, row.run_id)
            if (
                game is None
                or run is None
                or game.current_run_id != row.run_id
                or game.phase_id != row.phase_id
                or game.status not in _LIVE_MATCH_STATUSES
                or run.status != game.status
                or row.fence_worker_id != run.worker_id
                or row.fence_token != run.fence_token
            ):
                return False
            predecessor = db.scalar(
                select(LivePresentation).where(
                    LivePresentation.game_id == row.game_id,
                    LivePresentation.presentation_id == row.predecessor_presentation_id,
                )
            )
            return bool(
                predecessor is not None
                and predecessor.run_id == row.run_id
                and predecessor.action_id == row.predecessor_action_id
                and predecessor.state in _OPEN_PRESENTATION_STATES
                and predecessor.closed_at is None
            )

    def reserve_slot(
        self,
        *,
        game_id: str,
        phase_id: str,
        round_no: int,
        speech_round: int,
        turn_index: int,
        actor_player_id: str,
        predecessor_action_id: str,
        predecessor_presentation_id: str,
        predecessor_source_event_id: int,
        predecessor_source_record_seq: int,
        context_cutoff_record_seq: int,
        predecessor_turn_player_id: str | None = None,
        action_type: str = "day_debate_speech",
        fence: RunFence | None = None,
    ) -> DaySpeechSlotSnapshot:
        _canonical_id(game_id, field="game_id", maximum=40)
        _canonical_id(phase_id, field="phase_id", maximum=40)
        _canonical_id(actor_player_id, field="actor_player_id", maximum=80)
        if predecessor_turn_player_id is not None:
            _canonical_id(
                predecessor_turn_player_id,
                field="predecessor_turn_player_id",
                maximum=80,
            )
        _canonical_id(predecessor_action_id, field="predecessor_action_id", maximum=48)
        _canonical_id(
            predecessor_presentation_id,
            field="predecessor_presentation_id",
            maximum=48,
        )
        _positive_int(round_no, field="round_no")
        _positive_int(speech_round, field="speech_round")
        _positive_int(turn_index, field="turn_index")
        _positive_int(
            predecessor_source_event_id,
            field="predecessor_source_event_id",
        )
        _positive_int(
            predecessor_source_record_seq,
            field="predecessor_source_record_seq",
        )
        _positive_int(context_cutoff_record_seq, field="context_cutoff_record_seq")
        if action_type != "day_debate_speech":
            raise DaySpeechPipelineRepositoryError(
                "day speech slots only support day_debate_speech"
            )
        if turn_index < 2:
            raise DaySpeechPipelineRepositoryError(
                "one-ahead day speech slots require turn_index >= 2"
            )
        if context_cutoff_record_seq < predecessor_source_record_seq:
            raise DaySpeechPipelineRepositoryError(
                "day speech cutoff precedes its predecessor speech"
            )

        with self._session_factory.begin() as db:
            game, run = _locked_game_and_fence(db, game_id=game_id, fence=fence)
            _raise_if_stop_requested(run)
            contract = resolve_day_speech_pipeline_contract(game.rule_snapshot)
            if not contract.enables(action_type):
                raise DaySpeechPipelineRepositoryError("day_speech_pipeline_contract_disabled")
            if predecessor_turn_player_id is not None and contract.schema_version not in {2, 3}:
                raise DaySpeechPipelineRepositoryError(
                    "technical skip predecessor requires pipeline schema v2 or v3"
                )
            if game.status not in _LIVE_MATCH_STATUSES or run.status != game.status:
                raise DaySpeechPipelineRepositoryError(
                    "one-ahead reservation requires a live match"
                )
            if game.phase_id != phase_id or phase_id != f"day_{round_no}":
                raise DaySpeechPipelineRepositoryError("day speech reservation phase changed")
            if context_cutoff_record_seq > game.last_record_seq:
                raise DaySpeechPipelineRepositoryError(
                    "day speech cutoff is ahead of durable history"
                )
            player = db.get(PlayerState, (game_id, actor_player_id))
            if player is None or not player.alive:
                raise DaySpeechPipelineRepositoryError("day speech slot actor must be alive")
            predecessor = _validate_active_predecessor(
                db,
                game=game,
                phase_id=phase_id,
                round_no=round_no,
                speech_round=speech_round,
                turn_index=turn_index,
                actor_player_id=actor_player_id,
                predecessor_action_id=predecessor_action_id,
                predecessor_presentation_id=predecessor_presentation_id,
                predecessor_source_event_id=predecessor_source_event_id,
                predecessor_source_record_seq=predecessor_source_record_seq,
                context_cutoff_record_seq=context_cutoff_record_seq,
                predecessor_turn_player_id=predecessor_turn_player_id,
            )
            existing = db.scalar(
                select(DaySpeechSlot)
                .where(
                    DaySpeechSlot.game_id == game_id,
                    DaySpeechSlot.run_id == run.run_id,
                    DaySpeechSlot.phase_id == phase_id,
                    DaySpeechSlot.speech_round == speech_round,
                    DaySpeechSlot.turn_index == turn_index,
                )
                .with_for_update()
            )
            immutable = {
                "actor_player_id": actor_player_id,
                "action_type": action_type,
                "predecessor_action_id": predecessor_action_id,
                "predecessor_presentation_id": predecessor_presentation_id,
                "predecessor_source_event_id": predecessor_source_event_id,
                "predecessor_source_record_seq": predecessor_source_record_seq,
                "context_cutoff_record_seq": context_cutoff_record_seq,
            }
            if existing is not None:
                if any(getattr(existing, key) != value for key, value in immutable.items()):
                    raise DaySpeechPipelineRepositoryError(
                        "day speech slot reservation conflicts with durable slot"
                    )
                _require_owned_slot(existing, run)
                return _snapshot(existing)
            row = DaySpeechSlot(
                slot_id=f"v2_slot_{uuid4().hex[:16]}",
                game_id=game_id,
                run_id=run.run_id,
                fence_worker_id=_required_worker_id(run),
                fence_token=run.fence_token,
                phase_id=phase_id,
                round_no=round_no,
                speech_round=speech_round,
                turn_index=turn_index,
                action_type=action_type,
                actor_player_id=actor_player_id,
                predecessor_action_id=predecessor_action_id,
                predecessor_presentation_id=predecessor_presentation_id,
                predecessor_source_event_id=predecessor_source_event_id,
                predecessor_source_record_seq=predecessor_source_record_seq,
                context_cutoff_record_seq=context_cutoff_record_seq,
                state="reserved",
            )
            db.add(row)
            _append_slot_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="day_speech_slot_reserved",
                row=row,
                payload={
                    "predecessor_action_id": predecessor.action_id,
                    "predecessor_presentation_id": predecessor.presentation_id,
                    "predecessor_source_event_id": predecessor_source_event_id,
                    "predecessor_source_record_seq": predecessor_source_record_seq,
                    "context_cutoff_record_seq": context_cutoff_record_seq,
                },
            )
            db.flush()
            return _snapshot(row)

    def mark_generating(
        self,
        *,
        slot_id: str,
        fence: RunFence | None = None,
    ) -> DaySpeechSlotSnapshot:
        with self._session_factory.begin() as db:
            game, run, row = _locked_owned_slot(db, slot_id=slot_id, fence=fence)
            _raise_if_stop_requested(run)
            if row.state == "generating":
                return _snapshot(row)
            _require_state(row, "reserved")
            row.state = "generating"
            row.generation_started_at = _now()
            _append_slot_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="day_speech_slot_generation_started",
                row=row,
                payload={},
            )
            db.flush()
            return _snapshot(row)

    def mark_ready(
        self,
        *,
        slot_id: str,
        generation_action_id: str,
        generation_response_record_seq: int,
        fence: RunFence | None = None,
    ) -> DaySpeechSlotSnapshot:
        _canonical_id(
            generation_action_id,
            field="generation_action_id",
            maximum=48,
        )
        _positive_int(
            generation_response_record_seq,
            field="generation_response_record_seq",
        )
        with self._session_factory.begin() as db:
            game, run, row = _locked_owned_slot(db, slot_id=slot_id, fence=fence)
            _raise_if_stop_requested(run)
            if row.state == "ready":
                if (
                    row.generation_action_id == generation_action_id
                    and row.generation_response_record_seq == generation_response_record_seq
                ):
                    return _snapshot(row)
                raise DaySpeechPipelineRepositoryError(
                    "ready day speech slot has different generation lineage"
                )
            _require_state(row, "generating")
            attempt_id, decision, success_record_seq = _validate_generation_result(
                db,
                row=row,
                action_id=generation_action_id,
                response_record_seq=generation_response_record_seq,
                last_record_seq=game.last_record_seq,
            )
            row.generation_action_id = generation_action_id
            row.generation_attempt_id = attempt_id
            row.generation_response_record_seq = generation_response_record_seq
            row.decision = decision
            row.state = "ready"
            row.ready_at = _now()
            _append_slot_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="day_speech_slot_ready",
                row=row,
                payload={
                    "generation_action_id": generation_action_id,
                    "generation_attempt_id": attempt_id,
                    "generation_response_record_seq": generation_response_record_seq,
                    "generation_success_record_seq": success_record_seq,
                    "decision_sha256": _json_sha256(decision),
                    "speech_chars": len(str(decision["speech"])),
                },
            )
            db.flush()
            return _snapshot(row)

    def mark_presenting(
        self,
        *,
        slot_id: str,
        presentation_action_id: str,
        presentation_id: str,
        fence: RunFence | None = None,
    ) -> DaySpeechSlotSnapshot:
        _canonical_id(
            presentation_action_id,
            field="presentation_action_id",
            maximum=48,
        )
        _canonical_id(presentation_id, field="presentation_id", maximum=48)
        with self._session_factory.begin() as db:
            game, run, row = _locked_owned_slot(db, slot_id=slot_id, fence=fence)
            _raise_if_stop_requested(run)
            if row.state == "presenting":
                if (
                    row.presentation_action_id == presentation_action_id
                    and row.presentation_id == presentation_id
                ):
                    return _snapshot(row)
                raise DaySpeechPipelineRepositoryError(
                    "presenting day speech slot has different presentation lineage"
                )
            _require_state(row, "ready")
            if presentation_action_id == row.generation_action_id:
                raise DaySpeechPipelineRepositoryError(
                    "generation and presentation actions must be distinct"
                )
            predecessor_closed_seq = _validate_closed_predecessor(db, row=row)
            (
                presentation,
                presentation_source_record_seq,
                sealed_record_seq,
            ) = _validate_open_slot_presentation(
                db,
                row=row,
                action_id=presentation_action_id,
                presentation_id=presentation_id,
                predecessor_closed_record_seq=predecessor_closed_seq,
                last_record_seq=game.last_record_seq,
            )
            row.presentation_action_id = presentation_action_id
            row.presentation_id = presentation_id
            row.state = "presenting"
            row.presenting_at = _now()
            _append_slot_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="day_speech_slot_presenting",
                row=row,
                payload={
                    "presentation_action_id": presentation_action_id,
                    "presentation_id": presentation_id,
                    "presentation_source_event_id": presentation.source_event_id,
                    "presentation_source_record_seq": presentation_source_record_seq,
                    "presentation_sealed_record_seq": sealed_record_seq,
                    "predecessor_closed_record_seq": predecessor_closed_seq,
                },
            )
            db.flush()
            return _snapshot(row)

    def mark_consumed(
        self,
        *,
        slot_id: str,
        fence: RunFence | None = None,
    ) -> DaySpeechSlotSnapshot:
        with self._session_factory.begin() as db:
            game, run, row = _locked_owned_slot(db, slot_id=slot_id, fence=fence)
            _raise_if_stop_requested(run)
            if row.state == "consumed":
                return _snapshot(row)
            _require_state(row, "presenting")
            closed_seq, success_seq, audio_drained_seq = _validate_consumed_presentation(
                db,
                row=row,
                last_record_seq=game.last_record_seq,
            )
            completed_at = _now()
            row.state = "consumed"
            row.consumed_at = completed_at
            row.terminal_at = completed_at
            _append_slot_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="day_speech_slot_consumed",
                row=row,
                payload={
                    "presentation_action_id": row.presentation_action_id,
                    "presentation_id": row.presentation_id,
                    "speech_closed_record_seq": closed_seq,
                    "action_success_record_seq": success_seq,
                    "audio_drained_record_seq": audio_drained_seq,
                },
            )
            db.flush()
            return _snapshot(row)

    def mark_failed(
        self,
        *,
        slot_id: str,
        failure_record_seq: int,
        fence: RunFence | None = None,
    ) -> DaySpeechSlotSnapshot:
        _positive_int(failure_record_seq, field="failure_record_seq")
        with self._session_factory.begin() as db:
            game, run, row = _locked_owned_slot(db, slot_id=slot_id, fence=fence)
            if row.state == "failed":
                if row.failure_record_seq == failure_record_seq:
                    return _snapshot(row)
                raise DaySpeechPipelineRepositoryError(
                    "failed day speech slot has different failure lineage"
                )
            if row.state not in {"generating", "presenting"}:
                _require_state(row, "generating", "presenting")
            failure = _validate_slot_failure(
                db,
                row=row,
                failure_record_seq=failure_record_seq,
                last_record_seq=game.last_record_seq,
            )
            action_id = str(failure["action_failed"]["action_id"])
            if row.state == "generating":
                row.generation_action_id = action_id
                attempt_id = failure.get("generation_attempt_id")
                row.generation_attempt_id = str(attempt_id) if isinstance(attempt_id, str) else None
            row.state = "failed"
            row.failure_record_seq = failure_record_seq
            row.failure = failure
            row.terminal_at = _now()
            action_failure = failure["action_failed"]
            _append_slot_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="day_speech_slot_failed",
                row=row,
                payload={
                    "failure_stage": failure["stage"],
                    "failure_record_seq": failure_record_seq,
                    "failure_action_id": action_id,
                    "failure_kind": action_failure.get("failure_kind"),
                    "failure_code": action_failure.get("failure_code"),
                },
            )
            db.flush()
            return _snapshot(row)

    def cancel_slot(
        self,
        *,
        slot_id: str,
        reason_code: str,
        fence: RunFence | None = None,
    ) -> DaySpeechSlotSnapshot:
        _canonical_id(reason_code, field="reason_code", maximum=120)
        with self._session_factory.begin() as db:
            game, run, row = _locked_owned_slot(db, slot_id=slot_id, fence=fence)
            if row.state == "canceled":
                if (row.failure or {}).get("reason_code") == reason_code:
                    return _snapshot(row)
                raise DaySpeechPipelineRepositoryError(
                    "canceled day speech slot has different reason"
                )
            _require_nonterminal(row)
            _require_no_active_slot_presentation(db, row=row)
            row.state = "canceled"
            row.failure = {"kind": "canceled", "reason_code": reason_code}
            row.terminal_at = _now()
            _append_slot_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="day_speech_slot_canceled",
                row=row,
                payload={"reason_code": reason_code},
            )
            db.flush()
            return _snapshot(row)

    def invalidate_slot(
        self,
        *,
        slot_id: str,
        reason_code: str,
        fence: RunFence | None = None,
    ) -> DaySpeechSlotSnapshot:
        _canonical_id(reason_code, field="reason_code", maximum=120)
        with self._session_factory.begin() as db:
            game, current_run, row = _locked_slot_for_invalidation(
                db,
                slot_id=slot_id,
                fence=fence,
            )
            if row.state == "invalidated":
                if (row.failure or {}).get("reason_code") == reason_code:
                    return _snapshot(row)
                raise DaySpeechPipelineRepositoryError(
                    "invalidated day speech slot has different reason"
                )
            _require_nonterminal(row)
            _require_no_active_slot_presentation(db, row=row)
            row.state = "invalidated"
            row.failure = {
                "kind": "invalidated",
                "reason_code": reason_code,
                "invalidated_by_run_id": current_run.run_id,
                "invalidated_by_worker_id": _required_worker_id(current_run),
                "invalidated_by_fence_token": current_run.fence_token,
            }
            row.terminal_at = _now()
            _append_slot_event(
                db,
                game=game,
                run_id=current_run.run_id,
                event_type="day_speech_slot_invalidated",
                row=row,
                payload={
                    "reason_code": reason_code,
                    "slot_run_id": row.run_id,
                    "slot_fence_worker_id": row.fence_worker_id,
                    "slot_fence_token": row.fence_token,
                    "invalidated_by_run_id": current_run.run_id,
                    "invalidated_by_worker_id": _required_worker_id(current_run),
                    "invalidated_by_fence_token": current_run.fence_token,
                },
            )
            db.flush()
            return _snapshot(row)


def _locked_game_and_fence(
    db: Session,
    *,
    game_id: str,
    fence: RunFence | None,
) -> tuple[GameRecord, GameRun]:
    game = db.scalar(select(GameRecord).where(GameRecord.game_id == game_id).with_for_update())
    if game is None:
        raise DaySpeechPipelineRepositoryError(f"unknown game {game_id}")
    try:
        run = require_run_fence(db, game, fence=fence)
    except RunFenceRejected as exc:
        raise ExecutionOwnershipLost(str(exc)) from exc
    return game, run


def _locked_owned_slot(
    db: Session,
    *,
    slot_id: str,
    fence: RunFence | None,
) -> tuple[GameRecord, GameRun, DaySpeechSlot]:
    probe = db.get(DaySpeechSlot, slot_id)
    if probe is None:
        raise DaySpeechPipelineRepositoryError(f"unknown day speech slot {slot_id}")
    game, run = _locked_game_and_fence(db, game_id=probe.game_id, fence=fence)
    row = db.scalar(
        select(DaySpeechSlot).where(DaySpeechSlot.slot_id == slot_id).with_for_update()
    )
    if row is None:
        raise DaySpeechPipelineRepositoryError(f"unknown day speech slot {slot_id}")
    _require_owned_slot(row, run)
    if game.phase_id != row.phase_id:
        raise DaySpeechPipelineRepositoryError("day speech slot phase changed")
    return game, run, row


def _locked_slot_for_invalidation(
    db: Session,
    *,
    slot_id: str,
    fence: RunFence | None,
) -> tuple[GameRecord, GameRun, DaySpeechSlot]:
    probe = db.get(DaySpeechSlot, slot_id)
    if probe is None:
        raise DaySpeechPipelineRepositoryError(f"unknown day speech slot {slot_id}")
    game, run = _locked_game_and_fence(db, game_id=probe.game_id, fence=fence)
    row = db.scalar(
        select(DaySpeechSlot).where(DaySpeechSlot.slot_id == slot_id).with_for_update()
    )
    if row is None:
        raise DaySpeechPipelineRepositoryError(f"unknown day speech slot {slot_id}")
    return game, run, row


def _require_owned_slot(row: DaySpeechSlot, run: GameRun) -> None:
    if (
        row.run_id != run.run_id
        or row.fence_worker_id != run.worker_id
        or row.fence_token != run.fence_token
    ):
        raise ExecutionOwnershipLost("v2_day_speech_slot_fence_lost")


def _required_worker_id(run: GameRun) -> str:
    if not isinstance(run.worker_id, str) or not run.worker_id:
        raise ExecutionOwnershipLost("v2_run_execution_lease_missing")
    return run.worker_id


def _raise_if_stop_requested(run: GameRun) -> None:
    if run.stop_requested_at is not None:
        raise DaySpeechPipelineRepositoryError("V2 game stop was requested")


def _validate_active_predecessor(
    db: Session,
    *,
    game: GameRecord,
    phase_id: str,
    round_no: int,
    speech_round: int,
    turn_index: int,
    actor_player_id: str,
    predecessor_action_id: str,
    predecessor_presentation_id: str,
    predecessor_source_event_id: int,
    predecessor_source_record_seq: int,
    context_cutoff_record_seq: int,
    predecessor_turn_player_id: str | None,
) -> LivePresentation:
    predecessor = db.scalar(
        select(LivePresentation).where(
            LivePresentation.game_id == game.game_id,
            LivePresentation.presentation_id == predecessor_presentation_id,
        )
    )
    technical_skip_predecessor = predecessor_turn_player_id is not None
    if (
        predecessor is None
        or predecessor.run_id != game.current_run_id
        or predecessor.phase_id != phase_id
        or predecessor.action_id != predecessor_action_id
        or predecessor.source_event_id != predecessor_source_event_id
        or predecessor.actor_kind != ("judge" if technical_skip_predecessor else "player")
        or (technical_skip_predecessor and predecessor.actor_id != "judge")
        or predecessor.audience not in _PUBLIC_AUDIENCES
        or predecessor.state not in _OPEN_PRESENTATION_STATES
        or predecessor.voice_asset_id is None
    ):
        raise DaySpeechPipelineRepositoryError(
            "day speech predecessor is not an active public TTS presentation"
        )
    voice = db.get(VoiceAsset, predecessor.voice_asset_id)
    if (
        voice is None
        or voice.game_id != game.game_id
        or voice.run_id != game.current_run_id
        or voice.action_id != predecessor_action_id
        or voice.presentation_id != predecessor_presentation_id
        or voice.state not in {"writing", "ready"}
    ):
        raise DaySpeechPipelineRepositoryError("day speech predecessor has no active TTS asset")
    source = _event_by_id(
        db,
        game_id=game.game_id,
        run_id=game.current_run_id,
        event_id=predecessor_source_event_id,
        event_type="speech_segment_committed",
    )
    if source.record_seq != predecessor_source_record_seq:
        raise DaySpeechPipelineRepositoryError(
            "day speech predecessor event id/record seq lineage is invalid"
        )
    _require_event_lineage(
        source,
        action_id=predecessor_action_id,
        presentation_id=predecessor_presentation_id,
    )
    source_payload = _payload(source)
    if source_payload.get("audience") not in _PUBLIC_AUDIENCES:
        raise DaySpeechPipelineRepositoryError("day speech predecessor source is not public")
    sealed = _find_event(
        db,
        game_id=game.game_id,
        run_id=game.current_run_id,
        event_type="speech_sealed",
        action_id=predecessor_action_id,
        presentation_id=predecessor_presentation_id,
        minimum_record_seq=predecessor_source_record_seq + 1,
        maximum_record_seq=context_cutoff_record_seq,
    )
    if sealed is None:
        raise DaySpeechPipelineRepositoryError(
            "day speech predecessor was not sealed by the context cutoff"
        )
    opened = _pipeline_source_action_opened(
        db,
        game_id=game.game_id,
        run_id=game.current_run_id,
        action_id=predecessor_action_id,
        maximum_record_seq=predecessor_source_record_seq,
    )
    context = _action_context(opened)
    predecessor_turn_actor_id = predecessor.actor_id
    if technical_skip_predecessor:
        public_skip_record_seq = context.get("public_skip_record_seq")
        if (
            context.get("action_type") != "judge_day_speech_technical_skip"
            or context.get("actor") != {"kind": "judge", "id": "judge"}
            or context.get("skipped_player_id") != predecessor_turn_player_id
            or type(public_skip_record_seq) is not int
            or public_skip_record_seq <= 0
            or public_skip_record_seq >= opened.record_seq
        ):
            raise DaySpeechPipelineRepositoryError(
                "day speech technical skip predecessor action is invalid"
            )
        public_skip = _event_at(
            db,
            game_id=game.game_id,
            run_id=game.current_run_id,
            record_seq=public_skip_record_seq,
            event_type="action_skipped_technical",
        )
        public_skip_payload = _payload(public_skip)
        if (
            public_skip_payload.get("audience") not in _PUBLIC_AUDIENCES
            or public_skip_payload.get("phase_id") != phase_id
            or public_skip_payload.get("round_no") != round_no
            or public_skip_payload.get("action_type") != "day_debate_speech"
            or public_skip_payload.get("actor_id") != predecessor_turn_player_id
        ):
            raise DaySpeechPipelineRepositoryError(
                "day speech technical skip predecessor has no public fact"
            )
        predecessor_turn_actor_id = predecessor_turn_player_id
    elif context.get("action_type") != "day_debate_speech":
        raise DaySpeechPipelineRepositoryError("day speech predecessor is not a debate speech")
    if context.get("speech_round") != speech_round:
        raise DaySpeechPipelineRepositoryError("one-ahead day speech cannot cross speech rounds")
    speech_order = context.get("speech_order")
    if (
        type(speech_order) is not list
        or not all(isinstance(item, str) and item for item in speech_order)
        or predecessor_turn_actor_id not in speech_order
    ):
        raise DaySpeechPipelineRepositoryError(
            "day speech predecessor has no durable speech order"
        )
    predecessor_index = speech_order.index(predecessor_turn_actor_id)
    if (
        predecessor_index + 1 >= len(speech_order)
        or speech_order[predecessor_index + 1] != actor_player_id
        or turn_index != predecessor_index + 2
    ):
        raise DaySpeechPipelineRepositoryError(
            "day speech slot is not the predecessor's immediate next turn"
        )
    later_public_speech = _find_public_speech_after(
        db,
        game_id=game.game_id,
        run_id=game.current_run_id,
        minimum_record_seq=predecessor_source_record_seq + 1,
        maximum_record_seq=context_cutoff_record_seq,
        excluding_presentation_id=predecessor_presentation_id,
    )
    if later_public_speech is not None:
        raise DaySpeechPipelineRepositoryError(
            "day speech predecessor is not the latest public speech at cutoff"
        )
    return predecessor


def _validate_generation_result(
    db: Session,
    *,
    row: DaySpeechSlot,
    action_id: str,
    response_record_seq: int,
    last_record_seq: int,
) -> tuple[str, dict[str, Any], int]:
    opened = _validate_pipeline_action_opened(
        db,
        row=row,
        action_id=action_id,
        stage="generation",
        maximum_record_seq=response_record_seq - 1,
    )
    response = _event_at(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        record_seq=response_record_seq,
        event_type="model_response_received",
    )
    payload = _payload(response)
    if (
        payload.get("action_id") != action_id
        or payload.get("application_validation_result") != "accepted"
        or payload.get("audience") != "player_private"
    ):
        raise DaySpeechPipelineRepositoryError(
            "day speech generation response lineage is invalid"
        )
    attempt_id = payload.get("attempt_id")
    _canonical_id(attempt_id, field="generation_attempt_id", maximum=48)
    decision = payload.get("parsed_output")
    if type(decision) is not dict:
        raise DaySpeechPipelineRepositoryError(
            "day speech generation response has no parsed decision"
        )
    speech = decision.get("speech")
    if not isinstance(speech, str) or not speech.strip():
        raise DaySpeechPipelineRepositoryError(
            "day speech generation response has no public speech"
        )
    success = _find_event(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_type="action_succeeded",
        action_id=action_id,
        minimum_record_seq=response_record_seq + 1,
        maximum_record_seq=last_record_seq,
    )
    if success is None or _payload(success).get("result") != (
        "decision_recorded_without_presentation"
    ):
        raise DaySpeechPipelineRepositoryError(
            "day speech generation action was not durably completed"
        )
    failed = _find_event(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_type="action_failed",
        action_id=action_id,
        minimum_record_seq=opened.record_seq + 1,
        maximum_record_seq=last_record_seq,
    )
    if failed is not None:
        raise DaySpeechPipelineRepositoryError("day speech generation action also has a failure")
    return str(attempt_id), deepcopy(decision), success.record_seq


def _validate_pipeline_action_opened(
    db: Session,
    *,
    row: DaySpeechSlot,
    action_id: str,
    stage: Literal["generation", "presentation"],
    maximum_record_seq: int,
) -> GameRecordEvent:
    opened = _pipeline_source_action_opened(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        action_id=action_id,
        maximum_record_seq=maximum_record_seq,
    )
    payload = _payload(opened)
    context = _action_context(opened)
    pipeline = context.get("pipeline")
    game = db.get(GameRecord, row.game_id)
    contract = (
        resolve_day_speech_pipeline_contract(game.rule_snapshot)
        if game is not None
        else None
    )
    expected_admission = (
        contract.admission_mode
        if stage == "generation" and contract is not None
        else "normal"
    )
    if (
        payload.get("audience") != "player_private"
        or context.get("action_type") != row.action_type
        or context.get("phase_id") != row.phase_id
        or context.get("run_id") != row.run_id
        or context.get("action_record_seq") != opened.record_seq
        or context.get("speech_round") != row.speech_round
        or type(pipeline) is not dict
        or pipeline.get("slot_id") != row.slot_id
        or pipeline.get("stage") != stage
        or pipeline.get("model_admission_mode") != expected_admission
    ):
        raise DaySpeechPipelineRepositoryError(
            f"day speech {stage} action has invalid pipeline lineage"
        )
    actor = context.get("actor")
    if type(actor) is not dict or actor != {
        "kind": "player",
        "id": row.actor_player_id,
    }:
        raise DaySpeechPipelineRepositoryError(
            f"day speech {stage} action has invalid actor lineage"
        )
    speech_order = context.get("speech_order")
    if (
        type(speech_order) is not list
        or len(speech_order) < row.turn_index
        or speech_order[row.turn_index - 1] != row.actor_player_id
    ):
        raise DaySpeechPipelineRepositoryError(
            f"day speech {stage} action has invalid turn lineage"
        )
    if stage == "generation":
        batch_id = context.get("batch_id")
        if (
            context.get("projection_at_seq") != row.context_cutoff_record_seq
            or context.get("public_cutoff_record_seq") != row.context_cutoff_record_seq
            or not isinstance(batch_id, str)
            or not batch_id.strip()
        ):
            raise DaySpeechPipelineRepositoryError(
                "day speech generation action changed its frozen context cutoff"
            )
    return opened


def _validate_closed_predecessor(db: Session, *, row: DaySpeechSlot) -> int:
    predecessor = db.scalar(
        select(LivePresentation).where(
            LivePresentation.game_id == row.game_id,
            LivePresentation.presentation_id == row.predecessor_presentation_id,
        )
    )
    if (
        predecessor is None
        or predecessor.run_id != row.run_id
        or predecessor.action_id != row.predecessor_action_id
        or predecessor.state != "closed"
        or predecessor.closed_at is None
    ):
        raise DaySpeechPipelineRepositoryError(
            "day speech predecessor is not closed before presentation"
        )
    closed = _find_event(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_type="speech_closed",
        action_id=row.predecessor_action_id,
        presentation_id=row.predecessor_presentation_id,
        minimum_record_seq=row.predecessor_source_record_seq + 1,
    )
    if closed is None:
        raise DaySpeechPipelineRepositoryError(
            "day speech predecessor has no durable close event"
        )
    predecessor_slot = db.scalar(
        select(DaySpeechSlot).where(
            DaySpeechSlot.game_id == row.game_id,
            DaySpeechSlot.run_id == row.run_id,
            DaySpeechSlot.presentation_id == row.predecessor_presentation_id,
        )
    )
    if predecessor_slot is not None and predecessor_slot.state != "consumed":
        raise DaySpeechPipelineRepositoryError(
            "predecessor pipeline slot was not consumed in public order"
        )
    return closed.record_seq


def _validate_open_slot_presentation(
    db: Session,
    *,
    row: DaySpeechSlot,
    action_id: str,
    presentation_id: str,
    predecessor_closed_record_seq: int,
    last_record_seq: int,
) -> tuple[LivePresentation, int, int]:
    opened = _validate_pipeline_action_opened(
        db,
        row=row,
        action_id=action_id,
        stage="presentation",
        maximum_record_seq=last_record_seq,
    )
    presentation = db.scalar(
        select(LivePresentation).where(
            LivePresentation.game_id == row.game_id,
            LivePresentation.presentation_id == presentation_id,
        )
    )
    if (
        presentation is None
        or presentation.run_id != row.run_id
        or presentation.phase_id != row.phase_id
        or presentation.action_id != action_id
        or presentation.actor_kind != "player"
        or presentation.actor_id != row.actor_player_id
        or presentation.audience not in _PUBLIC_AUDIENCES
        or presentation.state not in _OPEN_PRESENTATION_STATES
    ):
        raise DaySpeechPipelineRepositoryError("day speech slot presentation lineage is invalid")
    source = _event_by_id(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_id=presentation.source_event_id,
        event_type="speech_segment_committed",
    )
    if source.record_seq <= predecessor_closed_record_seq or source.record_seq <= opened.record_seq:
        raise DaySpeechPipelineRepositoryError(
            "day speech slot presentation source is out of public order"
        )
    _require_event_lineage(source, action_id=action_id, presentation_id=presentation_id)
    source_payload = _payload(source)
    if source_payload.get("audience") not in _PUBLIC_AUDIENCES or source_payload.get("text") != (
        row.decision or {}
    ).get("speech"):
        raise DaySpeechPipelineRepositoryError(
            "day speech slot presentation changed the generated speech"
        )
    sealed = _find_event(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_type="speech_sealed",
        action_id=action_id,
        presentation_id=presentation_id,
        minimum_record_seq=source.record_seq + 1,
        maximum_record_seq=last_record_seq,
    )
    if sealed is None:
        raise DaySpeechPipelineRepositoryError("day speech slot presentation was not sealed")
    later_public_speech = _find_public_speech_after(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        minimum_record_seq=predecessor_closed_record_seq + 1,
        maximum_record_seq=source.record_seq - 1,
        excluding_presentation_id=presentation_id,
    )
    if later_public_speech is not None:
        raise DaySpeechPipelineRepositoryError(
            "day speech slot presentation would violate public order"
        )
    return presentation, source.record_seq, sealed.record_seq


def _validate_consumed_presentation(
    db: Session,
    *,
    row: DaySpeechSlot,
    last_record_seq: int,
) -> tuple[int, int, int | None]:
    presentation = db.scalar(
        select(LivePresentation).where(
            LivePresentation.game_id == row.game_id,
            LivePresentation.presentation_id == row.presentation_id,
        )
    )
    if (
        presentation is None
        or presentation.run_id != row.run_id
        or presentation.action_id != row.presentation_action_id
        or presentation.state != "closed"
        or presentation.closed_at is None
    ):
        raise DaySpeechPipelineRepositoryError(
            "day speech slot presentation is not durably closed"
        )
    source = _event_by_id(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_id=presentation.source_event_id,
        event_type="speech_segment_committed",
    )
    _require_event_lineage(
        source,
        action_id=str(row.presentation_action_id),
        presentation_id=str(row.presentation_id),
    )
    closed = _find_event(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_type="speech_closed",
        action_id=row.presentation_action_id,
        presentation_id=row.presentation_id,
        minimum_record_seq=source.record_seq + 1,
        maximum_record_seq=last_record_seq,
    )
    if closed is None:
        raise DaySpeechPipelineRepositoryError("day speech slot presentation has no close event")
    success = _find_event(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_type="action_succeeded",
        action_id=row.presentation_action_id,
        presentation_id=row.presentation_id,
        minimum_record_seq=source.record_seq + 1,
        maximum_record_seq=last_record_seq,
    )
    if success is None:
        raise DaySpeechPipelineRepositoryError(
            "day speech slot presentation action did not succeed"
        )
    audio_drained_seq: int | None = None
    if presentation.voice_asset_id is not None:
        drained = _find_event(
            db,
            game_id=row.game_id,
            run_id=row.run_id,
            event_type="audio_drained",
            action_id=row.presentation_action_id,
            presentation_id=row.presentation_id,
            minimum_record_seq=source.record_seq + 1,
            maximum_record_seq=closed.record_seq - 1,
        )
        if drained is None:
            raise DaySpeechPipelineRepositoryError(
                "day speech slot audio was not drained before close"
            )
        audio_drained_seq = drained.record_seq
    return closed.record_seq, success.record_seq, audio_drained_seq


def _validate_slot_failure(
    db: Session,
    *,
    row: DaySpeechSlot,
    failure_record_seq: int,
    last_record_seq: int,
) -> dict[str, Any]:
    if failure_record_seq > last_record_seq:
        raise DaySpeechPipelineRepositoryError("day speech failure is ahead of durable history")
    failed = _event_at(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        record_seq=failure_record_seq,
        event_type="action_failed",
    )
    failure_payload = _payload(failed)
    action_id = failure_payload.get("action_id")
    _canonical_id(action_id, field="failure_action_id", maximum=48)
    stage: Literal["generation", "presentation"] = (
        "generation" if row.state == "generating" else "presentation"
    )
    opened = _validate_pipeline_action_opened(
        db,
        row=row,
        action_id=str(action_id),
        stage=stage,
        maximum_record_seq=failure_record_seq - 1,
    )
    if stage == "generation":
        if row.generation_action_id not in {None, action_id}:
            raise DaySpeechPipelineRepositoryError("day speech generation failure action changed")
        if failure_payload.get("presentation_id") is not None:
            raise DaySpeechPipelineRepositoryError(
                "deferred day speech generation unexpectedly opened a presentation"
            )
    elif (
        row.presentation_action_id != action_id
        or failure_payload.get("presentation_id") != row.presentation_id
    ):
        raise DaySpeechPipelineRepositoryError("day speech presentation failure lineage changed")
    request_failure = _find_event(
        db,
        game_id=row.game_id,
        run_id=row.run_id,
        event_type="model_request_failed",
        action_id=str(action_id),
        minimum_record_seq=opened.record_seq + 1,
        maximum_record_seq=failure_record_seq - 1,
        latest=True,
    )
    request_failure_payload = (
        deepcopy(_payload(request_failure)) if request_failure is not None else None
    )
    attempt_id = (
        request_failure_payload.get("attempt_id")
        if isinstance(request_failure_payload, dict)
        else None
    )
    if attempt_id is not None:
        _canonical_id(attempt_id, field="generation_attempt_id", maximum=48)
    return {
        "stage": stage,
        "action_opened_record_seq": opened.record_seq,
        "action_failed_record_seq": failure_record_seq,
        "action_failed": deepcopy(failure_payload),
        "model_request_failed_record_seq": (
            request_failure.record_seq if request_failure is not None else None
        ),
        "model_request_failed": request_failure_payload,
        "generation_attempt_id": attempt_id,
    }


def _require_no_active_slot_presentation(db: Session, *, row: DaySpeechSlot) -> None:
    if row.presentation_id is None:
        return
    presentation = db.scalar(
        select(LivePresentation).where(
            LivePresentation.game_id == row.game_id,
            LivePresentation.presentation_id == row.presentation_id,
        )
    )
    if presentation is not None and presentation.state in _OPEN_PRESENTATION_STATES:
        raise DaySpeechPipelineRepositoryError(
            "active presentation must be closed before slot cleanup"
        )


def _pipeline_source_action_opened(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    action_id: str,
    maximum_record_seq: int,
) -> GameRecordEvent:
    opened = _find_event(
        db,
        game_id=game_id,
        run_id=run_id,
        event_type="action_opened",
        action_id=action_id,
        maximum_record_seq=maximum_record_seq,
    )
    if opened is None:
        raise DaySpeechPipelineRepositoryError("day speech action has no durable open event")
    return opened


def _action_context(event: GameRecordEvent) -> dict[str, Any]:
    context = _payload(event).get("context")
    if type(context) is not dict:
        raise DaySpeechPipelineRepositoryError("day speech action has no durable context")
    return context


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
    if (
        event is None
        or event.record_seq != record_seq
        or event.run_id != run_id
        or event.event_type != event_type
    ):
        raise DaySpeechPipelineRepositoryError(
            f"invalid {event_type} event lineage at record {record_seq}"
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
    if (
        event is None
        or event.event_id != event_id
        or event.run_id != run_id
        or event.event_type != event_type
    ):
        raise DaySpeechPipelineRepositoryError(
            f"invalid {event_type} event id lineage at event {event_id}"
        )
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


def _find_public_speech_after(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    minimum_record_seq: int,
    maximum_record_seq: int,
    excluding_presentation_id: str,
) -> GameRecordEvent | None:
    if maximum_record_seq < minimum_record_seq:
        return None
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


def _require_event_lineage(
    event: GameRecordEvent,
    *,
    action_id: str,
    presentation_id: str,
) -> None:
    payload = _payload(event)
    if payload.get("action_id") != action_id or payload.get("presentation_id") != presentation_id:
        raise DaySpeechPipelineRepositoryError(
            f"invalid {event.event_type} action/presentation lineage"
        )


def _payload(event: GameRecordEvent) -> dict[str, Any]:
    if type(event.payload) is not dict:
        raise DaySpeechPipelineRepositoryError(
            f"invalid payload for {event.event_type} at record {event.record_seq}"
        )
    return event.payload


def _append_slot_event(
    db: Session,
    *,
    game: GameRecord,
    run_id: str,
    event_type: str,
    row: DaySpeechSlot,
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
        payload=canonical_event_payload(
            {
                "slot_id": row.slot_id,
                "slot_run_id": row.run_id,
                "phase_id": row.phase_id,
                "round_no": row.round_no,
                "speech_round": row.speech_round,
                "turn_index": row.turn_index,
                "actor_player_id": row.actor_player_id,
                "state": row.state,
                **payload,
            },
            audience="god_view",
        ),
    )
    db.add(event)
    game.last_record_seq = next_seq
    return event


def _snapshot(row: DaySpeechSlot) -> DaySpeechSlotSnapshot:
    return DaySpeechSlotSnapshot(
        slot_id=row.slot_id,
        game_id=row.game_id,
        run_id=row.run_id,
        fence_worker_id=row.fence_worker_id,
        fence_token=row.fence_token,
        phase_id=row.phase_id,
        round_no=row.round_no,
        speech_round=row.speech_round,
        turn_index=row.turn_index,
        action_type=row.action_type,
        actor_player_id=row.actor_player_id,
        predecessor_action_id=row.predecessor_action_id,
        predecessor_presentation_id=row.predecessor_presentation_id,
        predecessor_source_event_id=row.predecessor_source_event_id,
        predecessor_source_record_seq=row.predecessor_source_record_seq,
        context_cutoff_record_seq=row.context_cutoff_record_seq,
        state=row.state,  # type: ignore[arg-type]
        generation_action_id=row.generation_action_id,
        generation_attempt_id=row.generation_attempt_id,
        generation_response_record_seq=row.generation_response_record_seq,
        decision=deepcopy(row.decision),
        presentation_action_id=row.presentation_action_id,
        presentation_id=row.presentation_id,
        failure_record_seq=row.failure_record_seq,
        failure=deepcopy(row.failure),
        created_at=row.created_at,
        updated_at=row.updated_at,
        generation_started_at=row.generation_started_at,
        ready_at=row.ready_at,
        presenting_at=row.presenting_at,
        consumed_at=row.consumed_at,
        terminal_at=row.terminal_at,
    )


def _require_state(row: DaySpeechSlot, *expected: str) -> None:
    if row.state not in expected:
        raise DaySpeechPipelineRepositoryError(
            f"day speech slot {row.slot_id} cannot transition from {row.state}; "
            f"expected {','.join(expected)}"
        )


def _require_nonterminal(row: DaySpeechSlot) -> None:
    if row.state in _TERMINAL_STATES:
        raise DaySpeechPipelineRepositoryError(
            f"day speech slot {row.slot_id} is terminal ({row.state})"
        )


def _canonical_id(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > maximum:
        raise DaySpeechPipelineRepositoryError(f"invalid {field}")
    return value


def _positive_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise DaySpeechPipelineRepositoryError(f"invalid {field}")
    return value


def _json_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now() -> datetime:
    return datetime.now(tz=UTC)
