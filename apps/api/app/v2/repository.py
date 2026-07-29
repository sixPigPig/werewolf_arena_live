from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.v2.models import (
    V2AbilityActivation,
    V2ActionWindow,
    V2EffectIntent,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2LivePresentation,
    V2VoiceAsset,
)
from app.v2.model_context_contract import (
    supports_current_model_context_contract,
)


class V2RepositoryError(RuntimeError):
    pass


class V2GameCanceled(asyncio.CancelledError):
    pass


@dataclass(frozen=True)
class V2ActionClaim:
    game_id: str
    run_id: str
    action_id: str
    phase_id: str
    activation_id: str | None = None
    best_effort: bool = False


@dataclass(frozen=True)
class V2PhaseTransition:
    game_id: str
    run_id: str
    phase_seq: int
    previous_phase_id: str
    phase_id: str
    phase_state: str


@dataclass(frozen=True)
class V2PresentationIdentity:
    game_id: str
    run_id: str
    action_id: str
    phase_id: str
    presentation_seq: int
    presentation_id: str
    speech_id: str
    segment_index: int
    voice_asset_id: str
    storage_key: str
    subtitle_text: str
    activation_id: str | None = None
    actor_kind: str = "judge"
    actor_id: str = "judge"
    audience: str = "all"


@dataclass(frozen=True)
class V2CancellationResult:
    run_id: str
    status: str
    changed: bool


class V2ActionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def start_game(self, *, game_id: str, audience: str) -> bool:
        """Start a newly created game once, when its first viewer is ready."""
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            _raise_if_stop_requested(db, game)
            if not supports_current_model_context_contract(game.rule_snapshot):
                raise V2RepositoryError("unsupported_model_context_contract")
            if game.status != "waiting_to_start":
                return False
            if game.phase_id != "opening" or game.phase_state != "opening_ready":
                raise V2RepositoryError("waiting game is not ready for opening")
            run = _run(db, game.current_run_id)
            if run.status != "waiting_to_start" or run.started_at is not None:
                raise V2RepositoryError("waiting run has already been started")
            started_at = _now()
            game.status = "ready"
            run.status = "ready"
            run.started_at = started_at
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="game_started",
                payload={
                    "start_mode": "first_ready_viewer",
                    "trigger_audience": audience,
                    "started_at": started_at.isoformat(),
                },
            )
            return True

    def claim_action(
        self,
        *,
        game_id: str,
        action_id: str,
        context: dict[str, Any],
        expected_phase_id: str,
        expected_phase_state: str,
        activation_id: str | None = None,
        best_effort: bool = False,
    ) -> V2ActionClaim | None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            _raise_if_stop_requested(db, game)
            if not supports_current_model_context_contract(game.rule_snapshot):
                raise V2RepositoryError("unsupported_model_context_contract")
            expected_live_state = "awaiting_observation" if best_effort else "ready"
            if (
                game.status != expected_live_state
                or game.phase_id != expected_phase_id
                or game.phase_state != expected_phase_state
            ):
                return None
            if best_effort and context.get("action_type") == "judge_game_completed":
                existing = db.scalar(
                    select(V2GameRecordEvent.event_id).where(
                        V2GameRecordEvent.game_id == game_id,
                        V2GameRecordEvent.event_type == "action_opened",
                        V2GameRecordEvent.payload["context"]["action_type"].as_string()
                        == "judge_game_completed",
                    )
                )
                if existing is not None:
                    return None
            run = _run(db, game.current_run_id)
            if activation_id is not None:
                activation = db.get(V2AbilityActivation, activation_id)
                if (
                    activation is None
                    or activation.game_id != game.game_id
                    or activation.status != "open"
                    or activation.action_id is not None
                ):
                    raise V2RepositoryError("ability activation cannot claim action")
                activation.action_id = action_id
            if not best_effort:
                game.status = "generating"
                run.status = "generating"
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="action_opened",
                payload={
                    "action_id": action_id,
                    "activation_id": activation_id,
                    "context": {**context, "run_id": run.run_id},
                },
            )
            return V2ActionClaim(
                game_id=game.game_id,
                run_id=run.run_id,
                action_id=action_id,
                phase_id=game.phase_id,
                activation_id=activation_id,
                best_effort=best_effort,
            )

    def append_event(
        self,
        *,
        game_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            _raise_if_stop_requested(db, game)
            event = _append_event(
                db,
                game=game,
                run_id=game.current_run_id,
                event_type=event_type,
                payload=payload,
            )
            return event.record_seq

    def open_presentation(
        self,
        *,
        claim: V2ActionClaim,
        presentation_id: str,
        speech_id: str,
        voice_asset_id: str,
        subtitle_text: str,
        sample_rate: int,
        actor_kind: str = "judge",
        actor_id: str = "judge",
        audience: str = "all",
    ) -> V2PresentationIdentity:
        storage_key = f"{claim.game_id}/{voice_asset_id}.wav"
        with self._session_factory.begin() as db:
            game = _locked_game(db, claim.game_id)
            _raise_if_stop_requested(db, game)
            expected_status = "awaiting_observation" if claim.best_effort else "generating"
            if game.status != expected_status:
                raise V2RepositoryError(f"cannot open presentation from {game.status}")
            presentation_seq = game.last_presentation_seq + 1
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="speech_opened",
                payload={
                    "action_id": claim.action_id,
                    "activation_id": claim.activation_id,
                    "presentation_id": presentation_id,
                    "presentation_seq": presentation_seq,
                    "speech_id": speech_id,
                },
            )
            committed = _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="speech_segment_committed",
                payload={
                    "action_id": claim.action_id,
                    "activation_id": claim.activation_id,
                    "presentation_id": presentation_id,
                    "presentation_seq": presentation_seq,
                    "speech_id": speech_id,
                    "segment_index": 0,
                    "text": subtitle_text,
                },
            )
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="speech_sealed",
                payload={"action_id": claim.action_id, "speech_id": speech_id},
            )
            voice = V2VoiceAsset(
                voice_asset_id=voice_asset_id,
                game_id=claim.game_id,
                run_id=claim.run_id,
                action_id=claim.action_id,
                activation_id=claim.activation_id,
                audience=audience,
                presentation_id=presentation_id,
                speech_id=speech_id,
                segment_index=0,
                state="writing",
                storage_key=storage_key,
                mime_type="audio/wav",
                sample_rate=sample_rate,
                channels=1,
            )
            db.add(voice)
            db.flush()
            presentation = V2LivePresentation(
                game_id=claim.game_id,
                presentation_seq=presentation_seq,
                presentation_id=presentation_id,
                action_id=claim.action_id,
                activation_id=claim.activation_id,
                run_id=claim.run_id,
                phase_id=claim.phase_id,
                actor_kind=actor_kind,
                actor_id=actor_id,
                audience=audience,
                speech_id=speech_id,
                segment_index=0,
                source_event_id=committed.event_id,
                state="active",
                subtitle_text=subtitle_text,
                subtitle_timings=[],
                voice_asset_id=voice_asset_id,
                audio_asset_id=None,
                audio_mime_type=None,
                audio_duration_ms=None,
            )
            db.add(presentation)
            game.last_presentation_seq = presentation_seq
            if not claim.best_effort:
                game.status = "broadcasting"
                _run(db, claim.run_id).status = "broadcasting"
        return V2PresentationIdentity(
            game_id=claim.game_id,
            run_id=claim.run_id,
            action_id=claim.action_id,
            phase_id=claim.phase_id,
            presentation_seq=presentation_seq,
            presentation_id=presentation_id,
            speech_id=speech_id,
            segment_index=0,
            voice_asset_id=voice_asset_id,
            storage_key=storage_key,
            subtitle_text=subtitle_text,
            activation_id=claim.activation_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
            audience=audience,
        )

    def mark_finalizing(
        self,
        *,
        game_id: str,
        tts_attempt_id: str,
        sample_count: int,
        best_effort: bool = False,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            _raise_if_stop_requested(db, game)
            if not best_effort:
                game.status = "finalizing"
                _run(db, game.current_run_id).status = "finalizing"
            _append_event(
                db,
                game=game,
                run_id=game.current_run_id,
                event_type="tts_stream_completed",
                payload={"tts_attempt_id": tts_attempt_id, "sample_count": sample_count},
            )

    def mark_voice_ready(
        self,
        *,
        identity: V2PresentationIdentity,
        sample_count: int,
        duration_ms: int,
        pcm_sha256: str,
        size_bytes: int,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, identity.game_id)
            _raise_if_stop_requested(db, game)
            voice = db.get(V2VoiceAsset, identity.voice_asset_id)
            if voice is None or voice.state != "writing":
                raise V2RepositoryError("voice asset is not writable")
            voice.state = "ready"
            voice.sample_count = sample_count
            voice.duration_ms = duration_ms
            voice.pcm_sha256 = pcm_sha256
            voice.size_bytes = size_bytes
            voice.completed_at = _now()
            presentation = db.get(
                V2LivePresentation,
                (identity.game_id, identity.presentation_seq),
            )
            if presentation is None:
                raise V2RepositoryError("presentation disappeared")
            presentation.audio_asset_id = identity.voice_asset_id
            presentation.audio_mime_type = "audio/wav"
            presentation.audio_duration_ms = duration_ms
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="voice_asset_saved",
                payload={
                    "action_id": identity.action_id,
                    "activation_id": identity.activation_id,
                    "voice_asset_id": identity.voice_asset_id,
                    "sample_count": sample_count,
                    "duration_ms": duration_ms,
                    "pcm_sha256": pcm_sha256,
                    "size_bytes": size_bytes,
                },
            )

    def complete_action(
        self,
        *,
        identity: V2PresentationIdentity,
        final_chunk_index: int,
        final_sample_cursor: int,
        next_live_state: str,
        next_phase_state: str,
        best_effort: bool = False,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, identity.game_id)
            _raise_if_stop_requested(db, game)
            presentation = db.get(
                V2LivePresentation,
                (identity.game_id, identity.presentation_seq),
            )
            voice = db.get(V2VoiceAsset, identity.voice_asset_id)
            if presentation is None or voice is None or voice.state != "ready":
                raise V2RepositoryError("action cannot complete without ready voice")
            presentation.state = "closed"
            presentation.closed_at = _now()
            if game.phase_id != identity.phase_id:
                raise V2RepositoryError("action phase changed before completion")
            run = _run(db, identity.run_id)
            if not best_effort:
                game.status = next_live_state
                game.phase_state = next_phase_state
                run.status = next_live_state
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="audio_drained",
                payload={
                    "action_id": identity.action_id,
                    "activation_id": identity.activation_id,
                    "presentation_id": identity.presentation_id,
                    "final_chunk_index": final_chunk_index,
                    "final_sample_cursor": final_sample_cursor,
                },
            )
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="speech_closed",
                payload={
                    "action_id": identity.action_id,
                    "activation_id": identity.activation_id,
                    "presentation_id": identity.presentation_id,
                    "speech_id": identity.speech_id,
                },
            )
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="action_succeeded",
                payload={
                    "action_id": identity.action_id,
                    "voice_asset_id": identity.voice_asset_id,
                    "result": "audio_drained_and_voice_saved",
                    "phase_id": identity.phase_id,
                },
            )

    def complete_silent_action(
        self,
        *,
        claim: V2ActionClaim,
        next_live_state: str,
        next_phase_state: str,
        best_effort: bool = False,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, claim.game_id)
            _raise_if_stop_requested(db, game)
            expected_status = "awaiting_observation" if best_effort else "generating"
            if game.status != expected_status:
                raise V2RepositoryError(f"cannot complete silent action from {game.status}")
            if game.phase_id != claim.phase_id:
                raise V2RepositoryError("action phase changed before completion")
            if not best_effort:
                game.status = next_live_state
                game.phase_state = next_phase_state
                _run(db, claim.run_id).status = next_live_state
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="action_succeeded",
                payload={
                    "action_id": claim.action_id,
                    "activation_id": claim.activation_id,
                    "result": "decision_recorded_without_presentation",
                    "phase_id": claim.phase_id,
                },
            )

    def transition_to_first_night(self, *, game_id: str) -> V2PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            _raise_if_stop_requested(db, game)
            if (
                game.status != "ready"
                or game.phase_id != "opening"
                or game.phase_state != "opening_speech_closed"
            ):
                raise V2RepositoryError("opening is not ready to enter first night")
            previous_phase_id = game.phase_id
            game.phase_seq += 1
            game.phase_id = "first_night"
            game.phase_state = "nightfall_ready"
            transition = V2PhaseTransition(
                game_id=game.game_id,
                run_id=game.current_run_id,
                phase_seq=game.phase_seq,
                previous_phase_id=previous_phase_id,
                phase_id=game.phase_id,
                phase_state=game.phase_state,
            )
            _append_event(
                db,
                game=game,
                run_id=game.current_run_id,
                event_type="game_phase_changed",
                payload={
                    "phase_seq": transition.phase_seq,
                    "previous_phase_id": transition.previous_phase_id,
                    "phase_id": transition.phase_id,
                    "phase_state": transition.phase_state,
                },
            )
            return transition

    def record_phase_state_change(
        self,
        *,
        game_id: str,
        phase_id: str,
        previous_phase_state: str,
        phase_state: str,
    ) -> V2PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            if (
                game.status != "awaiting_observation"
                or game.phase_id != phase_id
                or game.phase_state != phase_state
            ):
                raise V2RepositoryError("completed action phase state does not match")
            transition = V2PhaseTransition(
                game_id=game.game_id,
                run_id=game.current_run_id,
                phase_seq=game.phase_seq,
                previous_phase_id=game.phase_id,
                phase_id=game.phase_id,
                phase_state=game.phase_state,
            )
            _append_event(
                db,
                game=game,
                run_id=game.current_run_id,
                event_type="game_phase_changed",
                payload={
                    "phase_seq": transition.phase_seq,
                    "previous_phase_id": transition.previous_phase_id,
                    "previous_phase_state": previous_phase_state,
                    "phase_id": transition.phase_id,
                    "phase_state": transition.phase_state,
                },
            )
            return transition

    def fail_phase_transition(
        self,
        *,
        game_id: str,
        failure_kind: str,
        failure_code: str,
    ) -> str:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            _raise_if_stop_requested(db, game)
            run = _run(db, game.current_run_id)
            game.status = "failed"
            game.phase_state = "failed"
            run.status = "failed"
            run.completed_at = _now()
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="game_phase_transition_failed",
                payload={
                    "failure_kind": failure_kind,
                    "failure_code": failure_code,
                },
            )
            return run.run_id

    def fail_action(
        self,
        *,
        claim: V2ActionClaim,
        failure_kind: str,
        failure_code: str,
        identity: V2PresentationIdentity | None,
        best_effort: bool = False,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, claim.game_id)
            _raise_if_stop_requested(db, game)
            run = _run(db, claim.run_id)
            if not best_effort:
                game.status = "failed"
                game.phase_state = "failed"
                run.status = "failed"
                run.completed_at = _now()
            if identity is not None:
                presentation = db.get(
                    V2LivePresentation,
                    (identity.game_id, identity.presentation_seq),
                )
                if presentation is not None and presentation.state == "active":
                    presentation.state = "failed"
                    presentation.closed_at = _now()
                voice = db.get(V2VoiceAsset, identity.voice_asset_id)
                if voice is not None and voice.state == "writing":
                    voice.state = "failed"
                    voice.completed_at = _now()
                    _append_event(
                        db,
                        game=game,
                        run_id=claim.run_id,
                        event_type="voice_recording_failed",
                        payload={
                            "action_id": claim.action_id,
                            "voice_asset_id": identity.voice_asset_id,
                            "failure_code": failure_code,
                        },
                    )
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="action_failed",
                payload={
                    "action_id": claim.action_id,
                    "failure_kind": failure_kind,
                    "failure_code": failure_code,
                },
            )

    def check_cancellation(self, game_id: str) -> None:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            _raise_if_stop_requested(db, game)

    def stop_requested(self, game_id: str) -> bool:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            run = _run(db, game.current_run_id)
            return run.stop_requested_at is not None

    def cancel_game(self, game_id: str) -> V2CancellationResult:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            run = _run(db, game.current_run_id)
            if run.stop_requested_at is None:
                raise V2RepositoryError("game cancellation was not requested")
            if game.status == "canceled":
                return V2CancellationResult(
                    run_id=run.run_id,
                    status=run.status,
                    changed=False,
                )
            if game.status in {"completed", "failed"}:
                return V2CancellationResult(
                    run_id=run.run_id,
                    status=run.status,
                    changed=False,
                )

            canceled_at = _now()
            interrupted_presentations = list(
                db.scalars(
                    select(V2LivePresentation).where(
                        V2LivePresentation.game_id == game.game_id,
                        V2LivePresentation.state == "active",
                    )
                )
            )
            canceled_voice_count = 0
            for presentation in interrupted_presentations:
                presentation.state = "canceled"
                presentation.closed_at = canceled_at
                if presentation.voice_asset_id is not None:
                    voice = db.get(V2VoiceAsset, presentation.voice_asset_id)
                    if voice is not None and voice.state == "writing":
                        voice.state = "canceled"
                        voice.completed_at = canceled_at
                        canceled_voice_count += 1
                        _append_event(
                            db,
                            game=game,
                            run_id=run.run_id,
                            event_type="voice_recording_canceled",
                            payload={
                                "action_id": presentation.action_id,
                                "voice_asset_id": voice.voice_asset_id,
                                "reason_code": "operator_interrupted",
                            },
                        )
                _append_event(
                    db,
                    game=game,
                    run_id=run.run_id,
                    event_type="speech_interrupted",
                    payload={
                        "action_id": presentation.action_id,
                        "presentation_id": presentation.presentation_id,
                        "speech_id": presentation.speech_id,
                        "reason_code": "operator_interrupted",
                    },
                )

            open_activations = list(
                db.scalars(
                    select(V2AbilityActivation).where(
                        V2AbilityActivation.game_id == game.game_id,
                        V2AbilityActivation.status == "open",
                    )
                )
            )
            for activation in open_activations:
                activation.status = "canceled"
                activation.skip_reason = "operator_interrupted"
                activation.closed_at = canceled_at
                activation.result = {"reason_code": "operator_interrupted"}

            open_windows = list(
                db.scalars(
                    select(V2ActionWindow).where(
                        V2ActionWindow.game_id == game.game_id,
                        V2ActionWindow.state == "open",
                    )
                )
            )
            for window in open_windows:
                window.state = "canceled"
                window.closed_at = canceled_at
                window.result = {"reason_code": "operator_interrupted"}

            pending_effects = list(
                db.scalars(
                    select(V2EffectIntent).where(
                        V2EffectIntent.game_id == game.game_id,
                        V2EffectIntent.state == "pending",
                    )
                )
            )
            for effect in pending_effects:
                effect.state = "canceled"
                effect.resolved_at = canceled_at

            game.status = "canceled"
            run.status = "canceled"
            run.completed_at = canceled_at
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="game_canceled",
                payload={
                    "reason_code": "operator_interrupted",
                    "interrupted_presentation_count": len(interrupted_presentations),
                    "canceled_voice_count": canceled_voice_count,
                    "canceled_activation_count": len(open_activations),
                    "canceled_window_count": len(open_windows),
                    "canceled_effect_count": len(pending_effects),
                },
            )
            return V2CancellationResult(
                run_id=run.run_id,
                status=run.status,
                changed=True,
            )


def _locked_game(db: Session, game_id: str) -> V2GameRecord:
    game = db.scalar(select(V2GameRecord).where(V2GameRecord.game_id == game_id).with_for_update())
    if game is None:
        raise V2RepositoryError(f"unknown game {game_id}")
    return game


def _run(db: Session, run_id: str) -> V2GameRun:
    run = db.get(V2GameRun, run_id)
    if run is None:
        raise V2RepositoryError(f"unknown run {run_id}")
    return run


def _raise_if_stop_requested(db: Session, game: V2GameRecord) -> None:
    run = _run(db, game.current_run_id)
    if run.stop_requested_at is not None:
        raise V2GameCanceled("V2 game was canceled by an administrator")


def _append_event(
    db: Session,
    *,
    game: V2GameRecord,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> V2GameRecordEvent:
    next_seq = game.last_record_seq + 1
    event = V2GameRecordEvent(
        game_id=game.game_id,
        event_id=next_seq,
        record_seq=next_seq,
        run_id=run_id,
        event_type=event_type,
        payload_schema_version=1,
        payload=payload,
    )
    db.add(event)
    game.last_record_seq = next_seq
    return event


def _now() -> datetime:
    return datetime.now(tz=UTC)
