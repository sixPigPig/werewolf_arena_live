from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.v2.day_speech_pipeline_contract import (
    V2DaySpeechPipelineContractError,
    resolve_day_speech_pipeline_contract,
)
from app.v2.models import (
    V2AbilityActivation,
    V2ActionWindow,
    V2DaySpeechSlot,
    V2EffectIntent,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2LivePresentation,
    V2ModelActionRecovery,
    V2VoiceAsset,
)
from app.v2.model_context_contract import (
    frozen_model_context_contract,
    supports_model_context_contract,
)
from app.v2.model_generation_policy_contract import (
    V2ModelGenerationPolicyContractError,
    resolve_model_generation_policy_contract,
)
from app.v2.model_parameters import (
    V2FrozenModelParametersError,
    validate_players_snapshot_model_configurations,
)
from app.v2.model_failure_episode import (
    FailureEpisode,
    derive_failure_episodes,
    stable_failure_episode_id,
)
from app.v2.execution import (
    V2RunFence,
    V2RunFenceRejected,
    current_v2_run_fence,
    database_utc_now,
    require_v2_run_fence,
)
from app.v2.event_contract import canonical_event_payload, model_event_audience
from app.v2.runtime_state import V2AudioMode, delivery_audio_mode


class V2RepositoryError(RuntimeError):
    pass


class V2ExecutionOwnershipLost(V2RepositoryError):
    """The active runtime no longer owns the fenced game execution."""


class V2GameCanceled(asyncio.CancelledError):
    pass


@dataclass(frozen=True)
class V2ActionClaim:
    game_id: str
    run_id: str
    action_id: str
    phase_id: str
    audience: str
    activation_id: str | None = None
    best_effort: bool = False
    non_blocking: bool = False
    action_record_seq: int | None = None
    model_context_contract: dict[str, int] | None = None
    model_generation_policy_contract: dict[str, Any] | None = None
    audio_mode: V2AudioMode = "legacy_unknown"
    run_fence: V2RunFence | None = None


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
    voice_asset_id: str | None
    storage_key: str
    subtitle_text: str
    audience: str
    run_fence: V2RunFence | None = None
    activation_id: str | None = None
    actor_kind: str = "judge"
    actor_id: str = "judge"
    source_event_id: int | None = None
    source_record_seq: int | None = None


@dataclass(frozen=True)
class V2CancellationResult:
    run_id: str
    status: str
    changed: bool


@dataclass(frozen=True)
class V2ExecutionClaimResult:
    status: Literal["owned", "already_owned", "not_startable"]
    run_id: str
    fence: V2RunFence | None = None
    owner_hint: str | None = None
    current_state: str | None = None


class V2ActionRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        enforce_execution_fence: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._enforce_execution_fence = enforce_execution_fence

    def start_and_claim_execution(
        self,
        *,
        game_id: str,
        audience: str,
        worker_id: str,
        lease_seconds: float,
    ) -> V2ExecutionClaimResult:
        """Start a new game and acquire its only execution fence atomically."""
        if not worker_id or len(worker_id) > 64:
            raise V2RepositoryError("invalid V2 execution worker id")
        if lease_seconds <= 0:
            raise V2RepositoryError("invalid V2 execution lease duration")
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=False)
            _raise_if_stop_requested(db, game)
            if not supports_model_context_contract(game.rule_snapshot):
                raise V2RepositoryError("unsupported_model_context_contract")
            _resolved_model_generation_policy_contract(game.rule_snapshot)
            try:
                validate_players_snapshot_model_configurations(game.players_snapshot)
            except V2FrozenModelParametersError as exc:
                raise V2RepositoryError("invalid frozen player model configuration") from exc
            if game.status != "waiting_to_start":
                run = _run(db, game.current_run_id)
                return V2ExecutionClaimResult(
                    status=("already_owned" if run.worker_id is not None else "not_startable"),
                    run_id=run.run_id,
                    owner_hint=run.worker_id,
                    current_state=game.status,
                )
            if game.phase_id != "opening" or game.phase_state != "opening_ready":
                raise V2RepositoryError("waiting game is not ready for opening")
            run = _run(db, game.current_run_id)
            if run.status != "waiting_to_start" or run.started_at is not None:
                raise V2RepositoryError("waiting run has already been started")
            if run.worker_id is not None or run.lease_expires_at is not None:
                raise V2RepositoryError("waiting run already has an execution owner")
            started_at = database_utc_now(db)
            fence_token = run.fence_token + 1
            lease_expires_at = started_at + timedelta(seconds=lease_seconds)
            game.status = "ready"
            run.status = "ready"
            run.started_at = started_at
            run.worker_id = worker_id
            run.worker_heartbeat_at = started_at
            run.lease_expires_at = lease_expires_at
            run.fence_token = fence_token
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="v2_run_execution_claimed",
                audience="god_view",
                payload={
                    "run_id": run.run_id,
                    "worker_id": worker_id,
                    "fence_token": fence_token,
                    "lease_expires_at": lease_expires_at.isoformat(),
                    "reason": "initial_start",
                },
            )
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="game_started",
                audience="all",
                payload={
                    "run_id": run.run_id,
                    "start_mode": "first_ready_viewer",
                    "trigger_audience": audience,
                    "started_at": started_at.isoformat(),
                    "worker_id": worker_id,
                    "fence_token": fence_token,
                },
            )
            return V2ExecutionClaimResult(
                status="owned",
                run_id=run.run_id,
                fence=V2RunFence(
                    run_id=run.run_id,
                    worker_id=worker_id,
                    fence_token=fence_token,
                ),
            )

    def start_game(self, *, game_id: str, audience: str) -> bool:
        """Compatibility entry point for repository-only tests."""
        result = self.start_and_claim_execution(
            game_id=game_id,
            audience=audience,
            worker_id=f"v2_compat_{uuid4().hex[:20]}",
            lease_seconds=30.0,
        )
        return result.status == "owned"

    def heartbeat_execution(self, *, fence: V2RunFence, lease_seconds: float) -> bool:
        if lease_seconds <= 0:
            raise V2RepositoryError("invalid V2 execution lease duration")
        with self._session_factory.begin() as db:
            run = db.scalar(
                select(V2GameRun)
                .where(V2GameRun.run_id == fence.run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            heartbeat_at = database_utc_now(db)
            if (
                run is None
                or run.worker_id != fence.worker_id
                or run.fence_token != fence.fence_token
                or run.lease_expires_at is None
                or _as_utc(run.lease_expires_at) <= heartbeat_at
            ):
                return False
            run.worker_heartbeat_at = heartbeat_at
            run.lease_expires_at = heartbeat_at + timedelta(seconds=lease_seconds)
            return True

    def record_execution_heartbeat_lost(
        self,
        *,
        fence: V2RunFence,
        reason: str,
    ) -> bool:
        """Persist fail-closed ownership loss without clearing the stale owner."""
        with self._session_factory.begin() as db:
            game = db.scalar(
                select(V2GameRecord)
                .where(V2GameRecord.current_run_id == fence.run_id)
                .with_for_update()
            )
            if game is None:
                return False
            run = db.scalar(
                select(V2GameRun)
                .where(V2GameRun.run_id == fence.run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                run is None
                or run.worker_id != fence.worker_id
                or run.fence_token != fence.fence_token
            ):
                return False
            observed_at = database_utc_now(db)
            previous_lease_expires_at = run.lease_expires_at
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="v2_run_execution_heartbeat_lost",
                audience="god_view",
                payload={
                    "run_id": run.run_id,
                    "worker_id": fence.worker_id,
                    "fence_token": fence.fence_token,
                    "reason": reason,
                    "lease_expires_at": (
                        previous_lease_expires_at.isoformat()
                        if previous_lease_expires_at is not None
                        else None
                    ),
                    "observed_at": observed_at.isoformat(),
                },
            )
            run.lease_expires_at = observed_at
            return True

    def release_execution(self, *, fence: V2RunFence, reason: str) -> bool:
        with self._session_factory.begin() as db:
            game = db.scalar(
                select(V2GameRecord)
                .where(V2GameRecord.current_run_id == fence.run_id)
                .with_for_update()
            )
            if game is None:
                return False
            try:
                run = require_v2_run_fence(db, game, fence=fence)
            except V2RunFenceRejected:
                return False
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="v2_run_execution_released",
                audience="god_view",
                payload={
                    "run_id": run.run_id,
                    "worker_id": fence.worker_id,
                    "fence_token": fence.fence_token,
                    "reason": reason,
                    "lease_expires_at": run.lease_expires_at.isoformat(),
                },
            )
            run.worker_id = None
            run.worker_heartbeat_at = None
            run.lease_expires_at = None
            return True

    def model_binding_failure_streak(
        self,
        *,
        game_id: str,
        actor_id: str,
        model_provider: str,
        model_id: str,
    ) -> int:
        """Return the durable consecutive-failure count for one frozen binding."""
        with self._session_factory() as db:
            rows = list(
                db.scalars(
                    select(V2GameRecordEvent)
                    .where(
                        V2GameRecordEvent.game_id == game_id,
                        V2GameRecordEvent.event_type == "model_binding_health_updated",
                    )
                    .order_by(V2GameRecordEvent.record_seq.desc())
                    .limit(200)
                )
            )
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            if (
                payload.get("actor_id") == actor_id
                and payload.get("model_provider") == model_provider
                and payload.get("model_id") == model_id
            ):
                value = payload.get("consecutive_failure_count")
                return value if isinstance(value, int) and not isinstance(value, bool) else 0
        return 0

    def execution_release_reason(self, *, fence: V2RunFence) -> str:
        """Resolve the durable terminal reason before releasing an owned run."""
        with self._session_factory.begin() as db:
            game = db.scalar(
                select(V2GameRecord)
                .where(V2GameRecord.current_run_id == fence.run_id)
                .with_for_update()
            )
            if game is None:
                raise V2ExecutionOwnershipLost("v2_run_execution_run_changed")
            run = db.get(V2GameRun, fence.run_id)
            if (
                run is not None
                and game.current_run_id == fence.run_id
                and (game.status == "canceled" or run.status == "canceled")
            ):
                return "canceled"
            try:
                run = require_v2_run_fence(db, game, fence=fence)
            except V2RunFenceRejected as exc:
                raise V2ExecutionOwnershipLost(str(exc)) from exc
            if game.status == "canceled" or run.status == "canceled":
                return "canceled"
            if game.status == "failed" or game.phase_state == "failed" or run.status == "failed":
                return "failed"
            return "completed"

    def claim_action(
        self,
        *,
        game_id: str,
        action_id: str,
        context: dict[str, Any],
        expected_phase_id: str,
        expected_phase_state: str,
        audience: str,
        context_audience: str,
        activation_id: str | None = None,
        best_effort: bool = False,
        non_blocking: bool = False,
    ) -> V2ActionClaim | None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                game_id,
                require_fence=self._enforce_execution_fence,
            )
            _raise_if_stop_requested(db, game)
            if not supports_model_context_contract(game.rule_snapshot):
                raise V2RepositoryError("unsupported_model_context_contract")
            model_generation_policy_contract = _resolved_model_generation_policy_contract(
                game.rule_snapshot
            )
            expected_live_state = "awaiting_observation" if best_effort else "ready"
            run = _run(db, game.current_run_id)
            pipeline_generation = _is_pipeline_generation_context(context)
            if game.status == "broadcasting":
                if not pipeline_generation:
                    return None
                _bind_broadcast_pipeline_generation_claim(
                    db,
                    game=game,
                    run=run,
                    action_id=action_id,
                    context=context,
                    expected_phase_id=expected_phase_id,
                    expected_phase_state=expected_phase_state,
                    audience=audience,
                    context_audience=context_audience,
                    activation_id=activation_id,
                    best_effort=best_effort,
                    non_blocking=non_blocking,
                )
            elif pipeline_generation:
                raise V2RepositoryError(
                    "day speech pipeline generation requires an active broadcast"
                )
            elif (
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
            if not best_effort and not non_blocking:
                game.status = "generating"
                run.status = "generating"
            action_record_seq = game.last_record_seq + 1
            opened = _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="action_opened",
                audience=context_audience,
                payload={
                    "action_id": action_id,
                    "activation_id": activation_id,
                    "context": {
                        **context,
                        "run_id": run.run_id,
                        "action_record_seq": action_record_seq,
                    },
                },
            )
            if opened.record_seq != action_record_seq:
                raise V2RepositoryError("action record sequence changed while opening")
            return V2ActionClaim(
                game_id=game.game_id,
                run_id=run.run_id,
                action_id=action_id,
                phase_id=game.phase_id,
                audience=audience,
                activation_id=activation_id,
                best_effort=best_effort,
                non_blocking=non_blocking,
                action_record_seq=action_record_seq,
                model_context_contract=frozen_model_context_contract(game.rule_snapshot),
                model_generation_policy_contract=(model_generation_policy_contract),
                audio_mode=delivery_audio_mode(game.delivery_snapshot),
                run_fence=current_v2_run_fence(),
            )

    def append_event(
        self,
        *,
        game_id: str,
        event_type: str,
        audience: str,
        payload: dict[str, Any],
        fence: V2RunFence | None = None,
    ) -> int:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                game_id,
                require_fence=self._enforce_execution_fence,
                fence=fence,
            )
            _raise_if_stop_requested(db, game)
            event = _append_event(
                db,
                game=game,
                run_id=game.current_run_id,
                event_type=event_type,
                audience=audience,
                payload=payload,
            )
            return event.record_seq

    def open_presentation(
        self,
        *,
        claim: V2ActionClaim,
        presentation_id: str,
        speech_id: str,
        voice_asset_id: str | None,
        subtitle_text: str,
        sample_rate: int,
        actor_kind: str = "judge",
        actor_id: str = "judge",
    ) -> V2PresentationIdentity:
        audience = claim.audience
        storage_key = f"{claim.game_id}/{voice_asset_id}.wav" if voice_asset_id else ""
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                claim.game_id,
                require_fence=self._enforce_execution_fence,
                fence=claim.run_fence,
            )
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
                audience=audience,
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
                audience=audience,
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
            source_event_id = committed.event_id
            source_record_seq = committed.record_seq
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="speech_sealed",
                audience=audience,
                payload={
                    "action_id": claim.action_id,
                    "presentation_id": presentation_id,
                    "speech_id": speech_id,
                },
            )
            if voice_asset_id is not None:
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
            source_event_id=source_event_id,
            source_record_seq=source_record_seq,
            activation_id=claim.activation_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
            audience=audience,
            run_fence=claim.run_fence,
        )

    def complete_text_action(
        self,
        *,
        identity: V2PresentationIdentity,
        next_live_state: str,
        next_phase_state: str,
        best_effort: bool = False,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                identity.game_id,
                require_fence=self._enforce_execution_fence,
                fence=identity.run_fence,
            )
            _raise_if_stop_requested(db, game)
            presentation = db.get(
                V2LivePresentation,
                (identity.game_id, identity.presentation_seq),
            )
            if presentation is None or presentation.voice_asset_id is not None:
                raise V2RepositoryError("text action presentation is not closable")
            if presentation.state != "active":
                raise V2RepositoryError("text action presentation is not active")
            if game.phase_id != identity.phase_id:
                raise V2RepositoryError("action phase changed before text completion")
            presentation.state = "closed"
            presentation.closed_at = _now()
            run = _run(db, identity.run_id)
            if not best_effort:
                game.status = next_live_state
                game.phase_state = next_phase_state
                run.status = next_live_state
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="speech_closed",
                audience=identity.audience,
                payload={
                    "action_id": identity.action_id,
                    "activation_id": identity.activation_id,
                    "presentation_id": identity.presentation_id,
                    "speech_id": identity.speech_id,
                    "delivery_mode": "text_only",
                },
            )
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="action_succeeded",
                audience=identity.audience,
                payload={
                    "action_id": identity.action_id,
                    "presentation_id": identity.presentation_id,
                    "speech_id": identity.speech_id,
                    "delivery_mode": "text_only",
                },
            )

    def mark_finalizing(
        self,
        *,
        identity: V2PresentationIdentity,
        tts_attempt_id: str,
        sample_count: int,
        best_effort: bool = False,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                identity.game_id,
                require_fence=self._enforce_execution_fence,
                fence=identity.run_fence,
            )
            _raise_if_stop_requested(db, game)
            if not best_effort:
                game.status = "finalizing"
                _run(db, identity.run_id).status = "finalizing"
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="tts_stream_completed",
                audience=identity.audience,
                payload={
                    "action_id": identity.action_id,
                    "presentation_id": identity.presentation_id,
                    "tts_attempt_id": tts_attempt_id,
                    "sample_count": sample_count,
                },
            )

    def mark_voice_ready(
        self,
        *,
        identity: V2PresentationIdentity,
        tts_attempt_id: str,
        sample_count: int,
        duration_ms: int,
        pcm_sha256: str,
        size_bytes: int,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                identity.game_id,
                require_fence=self._enforce_execution_fence,
                fence=identity.run_fence,
            )
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
                audience=identity.audience,
                payload={
                    "action_id": identity.action_id,
                    "activation_id": identity.activation_id,
                    "presentation_id": identity.presentation_id,
                    "tts_attempt_id": tts_attempt_id,
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
        tts_attempt_id: str,
        final_chunk_index: int,
        final_sample_cursor: int,
        next_live_state: str,
        next_phase_state: str,
        best_effort: bool = False,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                identity.game_id,
                require_fence=self._enforce_execution_fence,
                fence=identity.run_fence,
            )
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
                audience=identity.audience,
                payload={
                    "action_id": identity.action_id,
                    "activation_id": identity.activation_id,
                    "presentation_id": identity.presentation_id,
                    "tts_attempt_id": tts_attempt_id,
                    "final_chunk_index": final_chunk_index,
                    "final_sample_cursor": final_sample_cursor,
                },
            )
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="speech_closed",
                audience=identity.audience,
                payload={
                    "action_id": identity.action_id,
                    "activation_id": identity.activation_id,
                    "presentation_id": identity.presentation_id,
                    "speech_id": identity.speech_id,
                    "tts_attempt_id": tts_attempt_id,
                },
            )
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="action_succeeded",
                audience=identity.audience,
                payload={
                    "action_id": identity.action_id,
                    "presentation_id": identity.presentation_id,
                    "tts_attempt_id": tts_attempt_id,
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
        failure_episode_id: str | None = None,
        technical_outcome_record_seq: int | None = None,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                claim.game_id,
                require_fence=self._enforce_execution_fence,
                fence=claim.run_fence,
            )
            _raise_if_stop_requested(db, game)
            if claim.non_blocking:
                if game.status in {"failed", "canceled"}:
                    raise V2RepositoryError(
                        f"cannot complete non-blocking action from {game.status}"
                    )
            else:
                expected_status = "awaiting_observation" if best_effort else "generating"
                if game.status != expected_status:
                    raise V2RepositoryError(f"cannot complete silent action from {game.status}")
            if game.phase_id != claim.phase_id:
                raise V2RepositoryError("action phase changed before completion")
            if not best_effort and not claim.non_blocking:
                game.status = next_live_state
                game.phase_state = next_phase_state
                _run(db, claim.run_id).status = next_live_state
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="action_succeeded",
                audience=claim.audience,
                payload={
                    "action_id": claim.action_id,
                    "activation_id": claim.activation_id,
                    "result": "decision_recorded_without_presentation",
                    "phase_id": claim.phase_id,
                    **(
                        {
                            "failure_episode_id": failure_episode_id,
                            "technical_outcome_record_seq": technical_outcome_record_seq,
                        }
                        if failure_episode_id is not None
                        else {}
                    ),
                },
            )

    def transition_to_first_night(self, *, game_id: str) -> V2PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
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
                audience="all",
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
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
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
                audience="all",
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
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            run = _run(db, game.current_run_id)
            game.status = "failed"
            game.phase_state = "failed"
            run.status = "failed"
            run.completed_at = _now()
            failed_failure_episode_ids = _open_failure_episode_ids_for_locked_run(
                db,
                game=game,
            )
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="game_phase_transition_failed",
                audience="god_view",
                payload={
                    "failure_kind": failure_kind,
                    "failure_code": failure_code,
                    "failed_failure_episode_ids": list(failed_failure_episode_ids),
                    "failure_episode_disposition": "run_failure",
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
        tts_attempt_id: str | None = None,
        best_effort: bool = False,
        failure_episode_id: str | None = None,
        failure_episode_disposition: Literal["isolated_action_failure", "run_failure"]
        | None = None,
    ) -> int:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                claim.game_id,
                require_fence=self._enforce_execution_fence,
                fence=claim.run_fence,
            )
            _raise_if_stop_requested(db, game)
            run = _run(db, claim.run_id)
            run_failure = not best_effort and not claim.non_blocking
            if run_failure:
                game.status = "failed"
                game.phase_state = "failed"
                run.status = "failed"
                run.completed_at = _now()
            open_episodes = {
                episode.failure_episode_id: episode
                for episode in _failure_episodes_for_locked_run(db, game=game)
                if episode.is_open
            }
            active_episode = open_episodes.get(failure_episode_id or "")
            expected_episode_disposition = (
                "run_failure" if run_failure else "isolated_action_failure"
            )
            attach_active_episode = (
                active_episode is not None
                and active_episode.action_id == claim.action_id
                and failure_episode_disposition == expected_episode_disposition
            )
            event_episode_disposition = (
                "run_failure"
                if run_failure
                else ("isolated_action_failure" if attach_active_episode else None)
            )
            failed_failure_episode_ids = tuple(sorted(open_episodes)) if run_failure else ()
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
                        audience=identity.audience,
                        payload={
                            "action_id": claim.action_id,
                            "presentation_id": identity.presentation_id,
                            "tts_attempt_id": tts_attempt_id,
                            "voice_asset_id": identity.voice_asset_id,
                            "failure_code": failure_code,
                        },
                    )
            failed = _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="action_failed",
                audience=claim.audience,
                payload={
                    "action_id": claim.action_id,
                    "activation_id": claim.activation_id,
                    "presentation_id": (identity.presentation_id if identity is not None else None),
                    "tts_attempt_id": tts_attempt_id,
                    "failure_kind": failure_kind,
                    "failure_code": failure_code,
                    **(
                        {
                            "failure_episode_id": failure_episode_id,
                        }
                        if attach_active_episode
                        else {}
                    ),
                    **(
                        {"failure_episode_disposition": (event_episode_disposition)}
                        if event_episode_disposition is not None
                        else {}
                    ),
                    **(
                        {"failed_failure_episode_ids": list(failed_failure_episode_ids)}
                        if run_failure
                        else {}
                    ),
                },
            )
            if claim.non_blocking and claim.activation_id is not None:
                activation = db.get(V2AbilityActivation, claim.activation_id)
                if (
                    activation is not None
                    and activation.status == "open"
                    and activation.action_id == claim.action_id
                ):
                    activation.action_id = None
                    _append_event(
                        db,
                        game=game,
                        run_id=claim.run_id,
                        event_type="ability_activation_action_released",
                        audience=claim.audience,
                        payload={
                            "activation_id": claim.activation_id,
                            "failed_action_id": claim.action_id,
                            "failure_code": failure_code,
                            "reason": "non_blocking_retry_allowed",
                        },
                    )
            return failed.record_seq

    def pause_model_action(
        self,
        *,
        claim: V2ActionClaim,
        attempt_id: str | None,
        failure_code: str,
        recovery: dict[str, Any],
        failure_episode_id: str | None = None,
        source_failure_episode_ids: tuple[str, ...] = (),
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                claim.game_id,
                require_fence=self._enforce_execution_fence,
                fence=claim.run_fence,
            )
            _raise_if_stop_requested(db, game)
            run = _run(db, claim.run_id)
            if game.status != "generating" or run.status != "generating":
                raise V2RepositoryError(
                    f"cannot pause model action from {game.status}/{run.status}"
                )
            game.status = "paused_model_error"
            run.status = "paused_model_error"
            existing = db.get(V2ModelActionRecovery, claim.action_id)
            if existing is None:
                existing = V2ModelActionRecovery(
                    action_id=claim.action_id,
                    recovery_id=f"v2_recovery_{uuid4().hex[:16]}",
                    game_id=claim.game_id,
                    run_id=claim.run_id,
                    action_type=str(recovery["action_type"]),
                    actor_id=str(recovery["actor_id"]),
                    model_provider=str(recovery["model_provider"]),
                    model_id=str(recovery["model_id"]),
                    request_payload=dict(recovery["request_payload"]),
                    request_hash=str(recovery["request_hash"]),
                    model_context=dict(recovery["model_context"]),
                    action_snapshot=dict(recovery["action_snapshot"]),
                    failure_code=failure_code,
                    failure_category=str(recovery["failure_category"]),
                    attempt_no=int(recovery["attempt_no"]),
                    retry_cycle=int(recovery["retry_cycle"]),
                    state="paused",
                )
                db.add(existing)
            else:
                if existing.request_hash != recovery["request_hash"]:
                    raise V2RepositoryError("paused model request hash changed")
                existing.failure_code = failure_code
                existing.failure_category = str(recovery["failure_category"])
                existing.attempt_no = int(recovery["attempt_no"])
                existing.retry_cycle = int(recovery["retry_cycle"])
                existing.state = "paused"
                existing.control_request_id = None
                existing.lease_owner = None
                existing.lease_expires_at = None
            recovery_audience = _model_action_recovery_audience(existing)
            decision_family_id = recovery.get("decision_family_id")
            automatic_machine_format_attempt_count = recovery.get(
                "automatic_machine_format_attempt_count"
            )
            automatic_output_budget_attempt_count = recovery.get(
                "automatic_output_budget_attempt_count"
            )
            prior_output_budget_failures = recovery.get("prior_output_budget_failures")
            automatic_output_budget_budget = recovery.get("automatic_output_budget_budget")
            exhaustion_scope = recovery.get("exhaustion_scope")
            exhaustion_scope = (
                exhaustion_scope if exhaustion_scope in {"action", "decision_family"} else "action"
            )
            source_action_id = recovery.get("source_action_id")
            source_attempt_id = recovery.get("source_attempt_id")
            reason_code = (
                "decision_family_budget_exhausted"
                if exhaustion_scope == "decision_family"
                else "model_attempts_exhausted"
            )
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="model_action_retry_exhausted",
                audience=recovery_audience,
                payload={
                    "action_id": claim.action_id,
                    "attempt_id": attempt_id,
                    "failure_code": failure_code,
                    "failure_category": existing.failure_category,
                    "attempt_no": existing.attempt_no,
                    "retry_cycle": existing.retry_cycle,
                    "decision_family_id": decision_family_id,
                    "automatic_machine_format_attempt_count": (
                        automatic_machine_format_attempt_count
                    ),
                    "automatic_output_budget_attempt_count": (
                        automatic_output_budget_attempt_count
                    ),
                    "prior_output_budget_failures": prior_output_budget_failures,
                    "automatic_output_budget_budget": automatic_output_budget_budget,
                    "exhaustion_scope": exhaustion_scope,
                    "source_action_id": source_action_id,
                    "source_attempt_id": source_attempt_id,
                    **(
                        {"failure_episode_id": failure_episode_id}
                        if failure_episode_id is not None
                        else {}
                    ),
                    **(
                        {"source_failure_episode_ids": list(source_failure_episode_ids)}
                        if source_failure_episode_ids
                        else {}
                    ),
                },
            )
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="model_action_recovery_queued",
                audience=recovery_audience,
                payload={
                    "action_id": claim.action_id,
                    "recovery_id": existing.recovery_id,
                    "request_hash": existing.request_hash,
                    "state": existing.state,
                    "decision_family_id": decision_family_id,
                    "automatic_machine_format_attempt_count": (
                        automatic_machine_format_attempt_count
                    ),
                    "automatic_output_budget_attempt_count": (
                        automatic_output_budget_attempt_count
                    ),
                    "prior_output_budget_failures": prior_output_budget_failures,
                    "automatic_output_budget_budget": automatic_output_budget_budget,
                    "exhaustion_scope": exhaustion_scope,
                    "source_action_id": source_action_id,
                    "source_attempt_id": source_attempt_id,
                    **(
                        {"failure_episode_id": failure_episode_id}
                        if failure_episode_id is not None
                        else {}
                    ),
                    **(
                        {"source_failure_episode_ids": list(source_failure_episode_ids)}
                        if source_failure_episode_ids
                        else {}
                    ),
                },
            )
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="model_action_paused",
                audience=recovery_audience,
                payload={
                    "action_id": claim.action_id,
                    "attempt_id": attempt_id,
                    "failure_code": failure_code,
                    "reason_code": reason_code,
                    "recovery_id": existing.recovery_id,
                    "request_hash": existing.request_hash,
                    "failure_category": existing.failure_category,
                    "decision_family_id": decision_family_id,
                    "automatic_machine_format_attempt_count": (
                        automatic_machine_format_attempt_count
                    ),
                    "automatic_output_budget_attempt_count": (
                        automatic_output_budget_attempt_count
                    ),
                    "prior_output_budget_failures": prior_output_budget_failures,
                    "automatic_output_budget_budget": automatic_output_budget_budget,
                    "exhaustion_scope": exhaustion_scope,
                    "source_action_id": source_action_id,
                    "source_attempt_id": source_attempt_id,
                    **(
                        {"failure_episode_id": failure_episode_id}
                        if failure_episode_id is not None
                        else {}
                    ),
                    **(
                        {"source_failure_episode_ids": list(source_failure_episode_ids)}
                        if source_failure_episode_ids
                        else {}
                    ),
                },
            )

    def pending_model_action_retry(self, *, game_id: str, action_id: str) -> str | None:
        with self._session_factory() as db:
            recovery = db.get(V2ModelActionRecovery, action_id)
            if (
                recovery is None
                or recovery.game_id != game_id
                or recovery.state != "retry_requested"
            ):
                return None
            return recovery.control_request_id

    def has_durable_model_action_retry(self, *, game_id: str, action_id: str) -> bool:
        return self.pending_model_action_retry(game_id=game_id, action_id=action_id) is not None

    def resume_model_action(
        self,
        *,
        claim: V2ActionClaim,
        control_request_id: str,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                claim.game_id,
                require_fence=self._enforce_execution_fence,
                fence=claim.run_fence,
            )
            _raise_if_stop_requested(db, game)
            run = _run(db, claim.run_id)
            if game.status != "paused_model_error" or run.status != "paused_model_error":
                raise V2RepositoryError(
                    f"cannot resume model action from {game.status}/{run.status}"
                )
            game.status = "generating"
            run.status = "generating"
            recovery = db.get(V2ModelActionRecovery, claim.action_id)
            if recovery is None or recovery.state not in {"retry_requested", "paused"}:
                raise V2RepositoryError("durable model action retry is not pending")
            recovery.state = "running"
            recovery.control_request_id = control_request_id
            recovery_audience = _model_action_recovery_audience(recovery)
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="model_action_recovery_leased",
                audience=recovery_audience,
                payload={
                    "action_id": claim.action_id,
                    "recovery_id": recovery.recovery_id,
                    "control_request_id": control_request_id,
                    "lease_mode": "originating_action_worker",
                },
            )
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="model_action_resumed",
                audience=recovery_audience,
                payload={
                    "action_id": claim.action_id,
                    "control_request_id": control_request_id,
                },
            )

    def resolve_model_action_recovery(
        self,
        *,
        claim: V2ActionClaim,
        attempt_id: str,
        attempt_no: int,
        retry_cycle: int,
    ) -> None:
        with self._session_factory.begin() as db:
            recovery = db.get(V2ModelActionRecovery, claim.action_id)
            if recovery is None or recovery.state == "resolved":
                return
            recovery.state = "resolved"
            recovery.resolved_attempt_id = attempt_id
            recovery.attempt_no = attempt_no
            recovery.retry_cycle = retry_cycle
            recovery.resolved_at = _now()
            game = _locked_game(
                db,
                recovery.game_id,
                require_fence=self._enforce_execution_fence,
                fence=claim.run_fence,
            )
            _append_event(
                db,
                game=game,
                run_id=recovery.run_id,
                event_type="model_action_recovery_resolved",
                audience=_model_action_recovery_audience(recovery),
                payload={
                    "action_id": claim.action_id,
                    "recovery_id": recovery.recovery_id,
                    "attempt_id": attempt_id,
                    "attempt_no": attempt_no,
                    "retry_cycle": retry_cycle,
                },
            )

    def check_cancellation(self, game_id: str) -> None:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            if self._enforce_execution_fence:
                try:
                    require_v2_run_fence(db, game, lock=False)
                except V2RunFenceRejected as exc:
                    raise V2ExecutionOwnershipLost(str(exc)) from exc
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
            game = _locked_game(db, game_id, require_fence=False)
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
                            audience=presentation.audience,
                            payload={
                                "action_id": presentation.action_id,
                                "presentation_id": presentation.presentation_id,
                                "voice_asset_id": voice.voice_asset_id,
                                "reason_code": "operator_interrupted",
                            },
                        )
                _append_event(
                    db,
                    game=game,
                    run_id=run.run_id,
                    event_type="speech_interrupted",
                    audience=presentation.audience,
                    payload={
                        "action_id": presentation.action_id,
                        "presentation_id": presentation.presentation_id,
                        "speech_id": presentation.speech_id,
                        "reason_code": "operator_interrupted",
                    },
                )

            canceled_day_speech_slots = list(
                db.scalars(
                    select(V2DaySpeechSlot)
                    .where(
                        V2DaySpeechSlot.game_id == game.game_id,
                        V2DaySpeechSlot.run_id == run.run_id,
                        V2DaySpeechSlot.state.in_(
                            ("reserved", "generating", "ready", "presenting")
                        ),
                    )
                    .order_by(V2DaySpeechSlot.slot_id)
                    .with_for_update()
                )
            )
            _terminalize_canceled_day_speech_actions(
                db,
                game=game,
                run=run,
                slots=canceled_day_speech_slots,
            )
            for slot in canceled_day_speech_slots:
                slot.state = "canceled"
                slot.failure = {
                    "kind": "canceled",
                    "reason_code": "operator_interrupted",
                }
                slot.terminal_at = canceled_at
                _append_event(
                    db,
                    game=game,
                    run_id=run.run_id,
                    event_type="day_speech_slot_canceled",
                    audience="god_view",
                    payload={
                        "slot_id": slot.slot_id,
                        "slot_run_id": slot.run_id,
                        "phase_id": slot.phase_id,
                        "round_no": slot.round_no,
                        "speech_round": slot.speech_round,
                        "turn_index": slot.turn_index,
                        "actor_player_id": slot.actor_player_id,
                        "state": slot.state,
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
                _append_event(
                    db,
                    game=game,
                    run_id=run.run_id,
                    event_type="ability_activation_canceled",
                    audience=_activation_audience(db, activation),
                    payload={
                        "action_id": activation.action_id,
                        "activation_id": activation.activation_id,
                        "reason_code": "operator_interrupted",
                    },
                )

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
                _append_event(
                    db,
                    game=game,
                    run_id=run.run_id,
                    event_type="effect_intent_canceled",
                    audience=_effect_audience(db, effect),
                    payload={
                        "activation_id": effect.activation_id,
                        "effect_intent_id": effect.effect_intent_id,
                        "effect_type": effect.effect_type,
                        "target_player_id": effect.target_player_id,
                        "reason_code": "operator_interrupted",
                    },
                )

            active_recoveries = list(
                db.scalars(
                    select(V2ModelActionRecovery).where(
                        V2ModelActionRecovery.game_id == game.game_id,
                        V2ModelActionRecovery.state.in_(("paused", "retry_requested", "running")),
                    )
                )
            )
            for recovery in active_recoveries:
                recovery.state = "canceled"
                recovery.resolved_at = canceled_at
                _append_event(
                    db,
                    game=game,
                    run_id=run.run_id,
                    event_type="model_action_recovery_canceled",
                    audience=_model_action_recovery_audience(recovery),
                    payload={
                        "action_id": recovery.action_id,
                        "recovery_id": recovery.recovery_id,
                        "reason_code": "operator_interrupted",
                    },
                )

            # The terminal failure events above are new in this transaction.
            # Production sessions disable autoflush, so flush before deriving
            # the open episodes that game_canceled resolves.
            db.flush()
            game.status = "canceled"
            run.status = "canceled"
            run.completed_at = canceled_at
            invalidated_worker_id = run.worker_id
            invalidated_fence_token = run.fence_token
            run.worker_id = None
            run.worker_heartbeat_at = None
            run.lease_expires_at = None
            run.fence_token += 1
            canceled_failure_episode_ids = _open_failure_episode_ids_for_locked_run(
                db,
                game=game,
            )
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="game_canceled",
                audience="all",
                payload={
                    "reason_code": "operator_interrupted",
                    "interrupted_presentation_count": len(interrupted_presentations),
                    "canceled_voice_count": canceled_voice_count,
                    "canceled_activation_count": len(open_activations),
                    "canceled_window_count": len(open_windows),
                    "canceled_effect_count": len(pending_effects),
                    "canceled_model_recovery_count": len(active_recoveries),
                    "canceled_day_speech_slot_count": len(canceled_day_speech_slots),
                    "invalidated_worker_id": invalidated_worker_id,
                    "invalidated_fence_token": invalidated_fence_token,
                    "canceled_failure_episode_ids": list(canceled_failure_episode_ids),
                },
            )
            return V2CancellationResult(
                run_id=run.run_id,
                status=run.status,
                changed=True,
            )


def _terminalize_canceled_day_speech_actions(
    db: Session,
    *,
    game: V2GameRecord,
    run: V2GameRun,
    slots: list[V2DaySpeechSlot],
) -> None:
    """Close hidden pipeline attempts/actions without bypassing stop globally."""

    action_ids = tuple(
        sorted(
            {
                action_id
                for slot in slots
                for action_id in (
                    slot.generation_action_id,
                    slot.presentation_action_id,
                )
                if isinstance(action_id, str) and action_id
            }
        )
    )
    if not action_ids:
        return

    events = list(
        db.scalars(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == game.game_id,
                V2GameRecordEvent.run_id == run.run_id,
            )
            .order_by(V2GameRecordEvent.record_seq)
        )
    )
    opened_by_action: dict[str, V2GameRecordEvent] = {}
    terminal_action_ids: set[str] = set()
    terminal_attempt_ids: set[str] = set()
    starts_by_action: dict[str, list[V2GameRecordEvent]] = {
        action_id: [] for action_id in action_ids
    }
    canceled_episode_ids_by_action: dict[str, set[str]] = {
        action_id: set() for action_id in action_ids
    }
    action_id_set = set(action_ids)
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        action_id = payload.get("action_id")
        if action_id not in action_id_set:
            continue
        if event.event_type == "action_opened":
            opened_by_action[str(action_id)] = event
        elif event.event_type in {"action_succeeded", "action_failed"}:
            terminal_action_ids.add(str(action_id))
        elif event.event_type == "model_request_started":
            starts_by_action[str(action_id)].append(event)
        elif event.event_type in {"model_response_received", "model_request_failed"}:
            attempt_id = payload.get("attempt_id")
            if isinstance(attempt_id, str) and attempt_id:
                terminal_attempt_ids.add(attempt_id)

    for episode in derive_failure_episodes(events):
        if episode.is_open and episode.action_id in action_id_set:
            canceled_episode_ids_by_action[episode.action_id].add(episode.failure_episode_id)

    for action_id in action_ids:
        opened = opened_by_action.get(action_id)
        action_audience = _event_payload_audience(opened) if opened is not None else "god_view"
        for started in starts_by_action[action_id]:
            payload = started.payload if isinstance(started.payload, dict) else {}
            attempt_id = payload.get("attempt_id")
            if (
                not isinstance(attempt_id, str)
                or not attempt_id
                or attempt_id in terminal_attempt_ids
            ):
                continue
            retry_cycle = _positive_event_int(payload.get("retry_cycle"), default=1)
            failure_episode_id = payload.get("failure_episode_id")
            if not isinstance(failure_episode_id, str) or not failure_episode_id:
                failure_episode_id = stable_failure_episode_id(
                    game_id=game.game_id,
                    run_id=run.run_id,
                    action_id=action_id,
                    retry_cycle=retry_cycle,
                    first_failed_attempt_id=attempt_id,
                )
            canceled_episode_ids_by_action[action_id].add(failure_episode_id)
            failure_payload: dict[str, Any] = {
                "action_id": action_id,
                "attempt_id": attempt_id,
                "attempt_no": _positive_event_int(payload.get("attempt_no"), default=1),
                "cycle_attempt_no": _positive_event_int(
                    payload.get("cycle_attempt_no"),
                    default=1,
                ),
                "retry_cycle": retry_cycle,
                "max_attempts": _positive_event_int(payload.get("max_attempts"), default=1),
                "failure_kind": "canceled",
                "failure_code": "day_speech_prefetch_canceled",
                "failure_category": "canceled",
                "failure_episode_id": failure_episode_id,
                "retryable": False,
                "attempt_terminal": True,
                "action_recoverable": False,
                "run_terminal": True,
                "terminal": True,
                "automatic_retry_scheduled": False,
                "automatic_retry_stop_reason": "not_retryable",
                "failure_stage": "operator_interrupted",
                "provider_outcome_unknown": True,
                "cancellation_reason_code": "operator_interrupted",
            }
            decision_family_id = payload.get("decision_family_id")
            if isinstance(decision_family_id, str) and decision_family_id:
                failure_payload["decision_family_id"] = decision_family_id
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="model_request_failed",
                audience=action_audience,
                payload=failure_payload,
            )
            terminal_attempt_ids.add(attempt_id)

        if action_id in terminal_action_ids:
            continue
        if opened is None:
            # Keep cancellation available across a historical binding gap,
            # without inventing an action lifecycle that was never opened.
            continue
        opened_payload = opened.payload if isinstance(opened.payload, dict) else {}
        canceled_failure_episode_ids = sorted(canceled_episode_ids_by_action[action_id])
        _append_event(
            db,
            game=game,
            run_id=run.run_id,
            event_type="action_failed",
            audience=_event_payload_audience(opened),
            payload={
                "action_id": action_id,
                "activation_id": opened_payload.get("activation_id"),
                "presentation_id": None,
                "tts_attempt_id": None,
                "failure_kind": "canceled",
                "failure_code": "day_speech_prefetch_canceled",
                "cancellation_reason_code": "operator_interrupted",
                "canceled_failure_episode_ids": canceled_failure_episode_ids,
            },
        )
        terminal_action_ids.add(action_id)


def _event_payload_audience(event: V2GameRecordEvent) -> str:
    payload = event.payload if isinstance(event.payload, dict) else {}
    audience = payload.get("audience")
    return audience if isinstance(audience, str) and audience else "god_view"


def _positive_event_int(value: object, *, default: int) -> int:
    return (
        value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default
    )


def _locked_game(
    db: Session,
    game_id: str,
    *,
    require_fence: bool,
    fence: V2RunFence | None = None,
) -> V2GameRecord:
    game = db.scalar(select(V2GameRecord).where(V2GameRecord.game_id == game_id).with_for_update())
    if game is None:
        raise V2RepositoryError(f"unknown game {game_id}")
    if require_fence:
        try:
            require_v2_run_fence(db, game, fence=fence)
        except V2RunFenceRejected as exc:
            raise V2ExecutionOwnershipLost(str(exc)) from exc
    return game


def _is_pipeline_generation_context(context: dict[str, Any]) -> bool:
    pipeline = context.get("pipeline")
    return type(pipeline) is dict and pipeline.get("stage") == "generation"


def _bind_broadcast_pipeline_generation_claim(
    db: Session,
    *,
    game: V2GameRecord,
    run: V2GameRun,
    action_id: str,
    context: dict[str, Any],
    expected_phase_id: str,
    expected_phase_state: str,
    audience: str,
    context_audience: str,
    activation_id: str | None,
    best_effort: bool,
    non_blocking: bool,
) -> None:
    """Validate and atomically bind the only action allowed during broadcast."""

    pipeline = context.get("pipeline")
    if type(pipeline) is not dict:
        raise V2RepositoryError("day speech pipeline generation context is invalid")
    try:
        contract = resolve_day_speech_pipeline_contract(game.rule_snapshot)
    except V2DaySpeechPipelineContractError as exc:
        raise V2RepositoryError(str(exc)) from exc
    expected_pipeline_keys = {"slot_id", "stage", "model_admission_mode"}
    if contract.schema_version == 2:
        expected_pipeline_keys.update({"retry_mode", "empty_stream_max_attempts"})
    if (
        set(pipeline) != expected_pipeline_keys
        or pipeline.get("stage") != "generation"
        or pipeline.get("model_admission_mode") != "idle_only"
        or not isinstance(pipeline.get("slot_id"), str)
        or not str(pipeline["slot_id"]).strip()
        or not non_blocking
        or best_effort
        or activation_id is not None
        or audience != "player_private"
        or context_audience != "player_private"
    ):
        raise V2RepositoryError("day speech pipeline generation claim is not isolated")
    if contract.schema_version == 2 and (
        pipeline.get("retry_mode") != "empty_stream_once_while_predecessor_active"
        or pipeline.get("empty_stream_max_attempts")
        != 1 + contract.early_transport_hidden_retry_max_retries
    ):
        raise V2RepositoryError("day speech pipeline retry policy is not frozen")
    if (
        not contract.enables("day_debate_speech")
        or contract.mode != "one_ahead"
        or contract.max_lookahead != 1
        or contract.context_source != "active_sealed_predecessor"
        or contract.admission_mode != "idle_only"
        or delivery_audio_mode(game.delivery_snapshot) != "tts"
    ):
        raise V2RepositoryError("day speech pipeline generation is not frozen and enabled")
    if (
        game.status != "broadcasting"
        or run.status != "broadcasting"
        or run.run_id != game.current_run_id
        or run.game_id != game.game_id
        or game.phase_id != expected_phase_id
        or game.phase_state != expected_phase_state
    ):
        raise V2RepositoryError("day speech pipeline generation phase changed")

    row = db.scalar(
        select(V2DaySpeechSlot)
        .where(V2DaySpeechSlot.slot_id == str(pipeline["slot_id"]))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise V2RepositoryError("unknown day speech pipeline slot")
    fence = current_v2_run_fence()
    if (
        row.game_id != game.game_id
        or row.run_id != run.run_id
        or row.fence_worker_id != run.worker_id
        or row.fence_token != run.fence_token
        or (
            fence is not None
            and (
                fence.run_id != row.run_id
                or fence.worker_id != row.fence_worker_id
                or fence.fence_token != row.fence_token
            )
        )
    ):
        raise V2ExecutionOwnershipLost("v2_day_speech_slot_fence_lost")
    if row.state != "generating":
        raise V2RepositoryError("day speech pipeline slot is not generating")
    if row.generation_action_id is not None:
        raise V2RepositoryError("day speech pipeline slot already claimed generation")
    if (
        row.phase_id != game.phase_id
        or row.action_type != "day_debate_speech"
        or type(context.get("schema_version")) is not int
        or context.get("schema_version") != 1
        or context.get("action_id") != action_id
        or context.get("action_type") != row.action_type
        or context.get("game_id") != game.game_id
        or context.get("phase_id") != row.phase_id
        or type(context.get("speech_round")) is not int
        or context.get("speech_round") != row.speech_round
        or type(context.get("projection_at_seq")) is not int
        or context.get("projection_at_seq") != row.context_cutoff_record_seq
        or type(context.get("public_cutoff_record_seq")) is not int
        or context.get("public_cutoff_record_seq") != row.context_cutoff_record_seq
        or type(context.get("output_contract")) is not dict
        or context["output_contract"].get("kind") != "speech"
    ):
        raise V2RepositoryError("day speech pipeline generation context lineage is invalid")
    actor = context.get("actor")
    speech_order = context.get("speech_order")
    batch_id = context.get("batch_id")
    if (
        actor != {"kind": "player", "id": row.actor_player_id}
        or type(speech_order) is not list
        or len(speech_order) < row.turn_index
        or speech_order[row.turn_index - 1] != row.actor_player_id
        or not isinstance(batch_id, str)
        or not batch_id.strip()
    ):
        raise V2RepositoryError("day speech pipeline generation actor/turn is invalid")

    _validate_pipeline_generation_predecessor(
        db,
        game=game,
        row=row,
        speech_order=speech_order,
    )
    row.generation_action_id = action_id


def _validate_pipeline_generation_predecessor(
    db: Session,
    *,
    game: V2GameRecord,
    row: V2DaySpeechSlot,
    speech_order: list[Any],
) -> None:
    active = list(
        db.scalars(
            select(V2LivePresentation)
            .where(
                V2LivePresentation.game_id == game.game_id,
                V2LivePresentation.state == "active",
            )
            .order_by(V2LivePresentation.presentation_seq)
        )
    )
    if len(active) != 1:
        raise V2RepositoryError(
            "day speech pipeline predecessor is not the unique active presentation"
        )
    predecessor = active[0]
    if row.turn_index < 2 or len(speech_order) < row.turn_index:
        raise V2RepositoryError("day speech pipeline predecessor identity is invalid")
    predecessor_turn_player_id = speech_order[row.turn_index - 2]
    technical_skip_predecessor = predecessor.actor_kind == "judge"
    predecessor_actor_valid = (
        predecessor.actor_id == "judge"
        if technical_skip_predecessor
        else (
            predecessor.actor_kind == "player"
            and predecessor.actor_id == predecessor_turn_player_id
        )
    )
    if (
        predecessor.presentation_id != row.predecessor_presentation_id
        or predecessor.action_id != row.predecessor_action_id
        or predecessor.source_event_id != row.predecessor_source_event_id
        or predecessor.run_id != row.run_id
        or predecessor.phase_id != row.phase_id
        or not predecessor_actor_valid
        or predecessor.audience != "all"
        or predecessor.closed_at is not None
        or predecessor.voice_asset_id is None
        or predecessor.presentation_seq != game.last_presentation_seq
    ):
        raise V2RepositoryError("day speech pipeline predecessor identity is invalid")
    voice = db.get(V2VoiceAsset, predecessor.voice_asset_id)
    if (
        voice is None
        or voice.game_id != row.game_id
        or voice.run_id != row.run_id
        or voice.action_id != row.predecessor_action_id
        or voice.presentation_id != row.predecessor_presentation_id
        or voice.audience != "all"
        or voice.state not in {"writing", "ready"}
    ):
        raise V2RepositoryError("day speech pipeline predecessor TTS lineage is invalid")
    source = db.get(
        V2GameRecordEvent,
        (row.game_id, row.predecessor_source_event_id),
    )
    source_payload = source.payload if source is not None else None
    if (
        source is None
        or source.run_id != row.run_id
        or source.record_seq != row.predecessor_source_record_seq
        or source.record_seq > row.context_cutoff_record_seq
        or source.event_type != "speech_segment_committed"
        or type(source_payload) is not dict
        or source_payload.get("audience") != "all"
        or source_payload.get("action_id") != row.predecessor_action_id
        or source_payload.get("presentation_id") != row.predecessor_presentation_id
        or source_payload.get("speech_id") != predecessor.speech_id
        or source_payload.get("segment_index") != predecessor.segment_index
        or source_payload.get("text") != predecessor.subtitle_text
        or not predecessor.subtitle_text.strip()
    ):
        raise V2RepositoryError("day speech pipeline predecessor source is invalid")

    lineage = list(
        db.scalars(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == row.game_id,
                V2GameRecordEvent.run_id == row.run_id,
                V2GameRecordEvent.record_seq <= row.context_cutoff_record_seq,
                V2GameRecordEvent.event_type.in_(
                    {
                        "action_opened",
                        "action_succeeded",
                        "action_failed",
                        "speech_opened",
                        "speech_segment_committed",
                        "speech_sealed",
                        "speech_closed",
                        "speech_interrupted",
                    }
                ),
            )
            .order_by(V2GameRecordEvent.record_seq)
        )
    )
    opened = [
        event
        for event in lineage
        if event.event_type == "action_opened"
        and event.payload.get("action_id") == row.predecessor_action_id
    ]
    if len(opened) != 1:
        raise V2RepositoryError("day speech pipeline predecessor action is invalid")
    predecessor_context = opened[0].payload.get("context")
    if (
        type(predecessor_context) is not dict
        or predecessor_context.get("action_id") != row.predecessor_action_id
        or predecessor_context.get("game_id") != row.game_id
        or predecessor_context.get("run_id") != row.run_id
        or predecessor_context.get("phase_id") != row.phase_id
        or predecessor_context.get("speech_round") != row.speech_round
        or predecessor_context.get("speech_order") != speech_order
        or predecessor_context.get("action_record_seq") != opened[0].record_seq
    ):
        raise V2RepositoryError("day speech pipeline predecessor action context is invalid")
    if technical_skip_predecessor:
        public_skip_record_seq = predecessor_context.get("public_skip_record_seq")
        if (
            predecessor_context.get("action_type") != "judge_day_speech_technical_skip"
            or predecessor_context.get("actor") != {"kind": "judge", "id": "judge"}
            or predecessor_context.get("skipped_player_id") != predecessor_turn_player_id
            or predecessor_context.get("round_no") != row.round_no
            or type(public_skip_record_seq) is not int
            or public_skip_record_seq <= 0
            or public_skip_record_seq >= opened[0].record_seq
        ):
            raise V2RepositoryError(
                "day speech pipeline technical skip predecessor context is invalid"
            )
        public_skip = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == row.game_id,
                V2GameRecordEvent.run_id == row.run_id,
                V2GameRecordEvent.record_seq == public_skip_record_seq,
                V2GameRecordEvent.event_type == "action_skipped_technical",
            )
        )
        public_skip_payload = public_skip.payload if public_skip is not None else None
        if (
            public_skip is None
            or type(public_skip_payload) is not dict
            or public_skip_payload.get("audience") != "all"
            or public_skip_payload.get("phase_id") != row.phase_id
            or public_skip_payload.get("round_no") != row.round_no
            or public_skip_payload.get("action_type") != row.action_type
            or public_skip_payload.get("actor_id") != predecessor_turn_player_id
            or public_skip_payload.get("reason") != "technical_failure"
        ):
            raise V2RepositoryError(
                "day speech pipeline technical skip predecessor public fact is invalid"
            )
    elif predecessor_context.get("action_type") != row.action_type or predecessor_context.get(
        "actor"
    ) != {"kind": "player", "id": predecessor.actor_id}:
        raise V2RepositoryError("day speech pipeline predecessor action context is invalid")
    speech_events = [
        event
        for event in lineage
        if event.payload.get("presentation_id") == row.predecessor_presentation_id
    ]
    speech_opened = [event for event in speech_events if event.event_type == "speech_opened"]
    segments = [event for event in speech_events if event.event_type == "speech_segment_committed"]
    sealed = [event for event in speech_events if event.event_type == "speech_sealed"]
    terminal_speech = [
        event
        for event in speech_events
        if event.event_type in {"speech_closed", "speech_interrupted"}
    ]
    terminal_action = [
        event
        for event in lineage
        if event.event_type in {"action_succeeded", "action_failed"}
        and event.payload.get("action_id") == row.predecessor_action_id
    ]
    if (
        len(speech_opened) != 1
        or len(segments) != 1
        or segments[0].event_id != source.event_id
        or len(sealed) != 1
        or terminal_speech
        or terminal_action
        or not (
            opened[0].record_seq
            < speech_opened[0].record_seq
            < source.record_seq
            < sealed[0].record_seq
            <= row.context_cutoff_record_seq
        )
    ):
        raise V2RepositoryError("day speech pipeline predecessor is not active and sealed")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
    audience: str,
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
        payload=canonical_event_payload(payload, audience=audience),
    )
    db.add(event)
    game.last_record_seq = next_seq
    return event


def _failure_episodes_for_locked_run(
    db: Session,
    *,
    game: V2GameRecord,
) -> tuple[FailureEpisode, ...]:
    events = tuple(
        db.scalars(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == game.game_id,
                V2GameRecordEvent.run_id == game.current_run_id,
            )
            .order_by(V2GameRecordEvent.record_seq)
        )
    )
    return derive_failure_episodes(events)


def _open_failure_episode_ids_for_locked_run(
    db: Session,
    *,
    game: V2GameRecord,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            episode.failure_episode_id
            for episode in _failure_episodes_for_locked_run(db, game=game)
            if episode.is_open
        )
    )


def _resolved_model_generation_policy_contract(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    try:
        return resolve_model_generation_policy_contract(rule_snapshot)
    except V2ModelGenerationPolicyContractError as exc:
        raise V2RepositoryError("unsupported_model_generation_policy_contract") from exc


def _action_snapshot_audience(snapshot: dict[str, Any]) -> str:
    audience = snapshot.get("audience")
    if isinstance(audience, str):
        return audience
    # Follow-up events for pre-contract records must remain operable without
    # guessing that an unknown historical action was public.
    return "god_view"


def _model_action_recovery_audience(recovery: V2ModelActionRecovery) -> str:
    snapshot = recovery.action_snapshot if isinstance(recovery.action_snapshot, dict) else {}
    actor_kind = snapshot.get("actor_kind")
    return model_event_audience(
        action_audience=_action_snapshot_audience(snapshot),
        actor_kind=actor_kind if isinstance(actor_kind, str) else "unknown",
    )


def _activation_audience(db: Session, activation: V2AbilityActivation) -> str:
    if activation.action_id is not None:
        action_event = db.scalar(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == activation.game_id,
                V2GameRecordEvent.event_type == "action_opened",
                V2GameRecordEvent.payload["action_id"].as_string() == activation.action_id,
            )
            .order_by(V2GameRecordEvent.record_seq.desc())
            .limit(1)
        )
        if action_event is not None:
            audience = (action_event.payload or {}).get("audience")
            if isinstance(audience, str):
                return audience
    activation_event = db.scalar(
        select(V2GameRecordEvent)
        .where(
            V2GameRecordEvent.game_id == activation.game_id,
            V2GameRecordEvent.event_type == "ability_activation_opened",
            V2GameRecordEvent.payload["activation_id"].as_string() == activation.activation_id,
        )
        .order_by(V2GameRecordEvent.record_seq.desc())
        .limit(1)
    )
    audience = (activation_event.payload or {}).get("audience") if activation_event else None
    if isinstance(audience, str):
        return audience
    return "god_view"


def _effect_audience(db: Session, effect: V2EffectIntent) -> str:
    audience = (effect.payload or {}).get("transport_audience")
    if isinstance(audience, str):
        return audience
    activation = db.get(V2AbilityActivation, effect.activation_id)
    if activation is None:
        raise V2RepositoryError("effect intent activation is missing")
    return _activation_audience(db, activation)


def _now() -> datetime:
    return datetime.now(tz=UTC)
