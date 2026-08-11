from __future__ import annotations

import asyncio
from copy import deepcopy
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
    V2KnowledgeFact,
    V2LivePresentation,
    V2ModelActionRecovery,
    V2PlayerState,
    V2PreExilePipeline,
    V2PreExileResult,
    V2RoleAssignment,
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
from app.v2.pre_exile_pipeline_contract import (
    V2PreExilePipelineContractError,
    pre_exile_context_sha256,
    resolve_pre_exile_pipeline_contract,
)
from app.v2.knowledge_timeline import player_private_knowledge
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
            pre_exile_generation = _is_pre_exile_pipeline_context(context)
            if pre_exile_generation and game.status in {
                "broadcasting",
                "finalizing",
                "ready",
            }:
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
            elif game.status == "broadcasting":
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
            if "pre_exile_recovery" in context:
                _bind_pre_exile_vote_recovery_claim(
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

            canceled_pre_exile_pipelines = list(
                db.scalars(
                    select(V2PreExilePipeline)
                    .where(
                        V2PreExilePipeline.game_id == game.game_id,
                        V2PreExilePipeline.run_id == run.run_id,
                        V2PreExilePipeline.state.in_(
                            ("collecting", "no_explosion", "votes_accepted")
                        ),
                    )
                    .order_by(V2PreExilePipeline.pipeline_id)
                    .with_for_update()
                )
            )
            canceled_pre_exile_results: list[V2PreExileResult] = []
            if canceled_pre_exile_pipelines:
                from app.v2.pre_exile_pipeline_repository import (
                    _terminalize_result_actions,
                )

                for pipeline in canceled_pre_exile_pipelines:
                    results = list(
                        db.scalars(
                            select(V2PreExileResult)
                            .where(V2PreExileResult.pipeline_id == pipeline.pipeline_id)
                            .with_for_update()
                        )
                    )
                    canceled_pre_exile_results.extend(results)
                    _terminalize_result_actions(
                        db,
                        game=game,
                        pipeline=pipeline,
                        rows=results,
                        failure_code="pre_exile_pipeline_canceled",
                        failure_stage="operator_interrupted",
                    )
                    for result in results:
                        if result.state not in {"committed", "discarded"}:
                            result.state = "discarded"
                            result.terminal_at = canceled_at
                    pipeline.state = "canceled"
                    pipeline.failure = {
                        "kind": "canceled",
                        "reason_code": "operator_interrupted",
                    }
                    pipeline.terminal_at = canceled_at
                    _append_event(
                        db,
                        game=game,
                        run_id=run.run_id,
                        event_type="pre_exile_pipeline_canceled",
                        audience="god_view",
                        payload={
                            "pipeline_id": pipeline.pipeline_id,
                            "pipeline_run_id": pipeline.run_id,
                            "phase_id": pipeline.phase_id,
                            "round_no": pipeline.round_no,
                            "state": pipeline.state,
                            "reason_code": "operator_interrupted",
                            "discarded_result_count": len(results),
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
                    "canceled_pre_exile_pipeline_count": len(canceled_pre_exile_pipelines),
                    "canceled_pre_exile_result_count": len(canceled_pre_exile_results),
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


def _is_pre_exile_pipeline_context(context: dict[str, Any]) -> bool:
    pipeline = context.get("pipeline")
    return (
        type(pipeline) is dict
        and pipeline.get("kind") == "pre_exile"
        and pipeline.get("stage") == "generation"
    )


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
    if pipeline.get("kind") == "pre_exile":
        _bind_pre_exile_pipeline_generation_claim(
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
        return
    if "kind" in pipeline:
        raise V2RepositoryError("unsupported broadcast pipeline kind")
    try:
        contract = resolve_day_speech_pipeline_contract(game.rule_snapshot)
    except V2DaySpeechPipelineContractError as exc:
        raise V2RepositoryError(str(exc)) from exc
    expected_pipeline_keys = {"slot_id", "stage", "model_admission_mode"}
    guarded_retry_enabled = contract.early_transport_hidden_retry_max_retries == 1
    if guarded_retry_enabled:
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
    if guarded_retry_enabled and (
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


def _bind_pre_exile_pipeline_generation_claim(
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
    pipeline_context = context.get("pipeline")
    if type(pipeline_context) is not dict:
        raise V2RepositoryError("pre-exile pipeline context is invalid")
    result_kind = pipeline_context.get("result_kind")
    expected_action_type = (
        "werewolf_self_explosion"
        if result_kind == "self_explosion"
        else "exile_vote"
        if result_kind == "exile_vote"
        else None
    )
    expected_admission = "normal" if result_kind == "self_explosion" else "idle_only"
    try:
        contract = resolve_pre_exile_pipeline_contract(game.rule_snapshot)
    except V2PreExilePipelineContractError as exc:
        raise V2RepositoryError(str(exc)) from exc
    guarded_self_explosion_retry = (
        result_kind == "self_explosion"
        and contract.self_explosion_early_empty_stream_hidden_retry_max_retries == 1
    )
    expected_empty_stream_max_attempts = (
        1 + contract.self_explosion_early_empty_stream_hidden_retry_max_retries
    )
    expected_keys = {
        "kind",
        "pipeline_id",
        "result_kind",
        "stage",
        "model_admission_mode",
    }
    if guarded_self_explosion_retry:
        expected_keys.update({"retry_mode", "empty_stream_max_attempts"})
    if (
        set(pipeline_context) != expected_keys
        or pipeline_context.get("kind") != "pre_exile"
        or pipeline_context.get("stage") != "generation"
        or pipeline_context.get("model_admission_mode") != expected_admission
        or not isinstance(pipeline_context.get("pipeline_id"), str)
        or not str(pipeline_context["pipeline_id"]).strip()
        or expected_action_type is None
        or not non_blocking
        or best_effort
        or activation_id is not None
        or audience != "god_view"
        or context_audience != "god_view"
        or (
            guarded_self_explosion_retry
            and (
                pipeline_context.get("retry_mode")
                != "empty_stream_once_while_predecessor_active"
                or pipeline_context.get("empty_stream_max_attempts")
                != expected_empty_stream_max_attempts
            )
        )
    ):
        raise V2RepositoryError("pre-exile pipeline generation claim is not isolated")
    if (
        not contract.enables(expected_action_type)
        or contract.self_explosion_admission_mode != "normal"
        or contract.speculative_vote_admission_mode != "idle_only"
        or contract.speculative_vote_capacity_recovery_mode != "normal_batch_after_close_once"
        or contract.private_context_mode != "sealed_snapshot_plus_own_no_explosion_fact"
        or contract.result_commit_mode != "durable_atomic_arbiter"
        or contract.inflight_recovery_mode != "no_duplicate_provider"
    ):
        raise V2RepositoryError("pre-exile pipeline contract is not enabled")
    if (
        game.status not in {"broadcasting", "finalizing", "ready"}
        or run.status != game.status
        or run.run_id != game.current_run_id
        or run.game_id != game.game_id
        or game.phase_id != expected_phase_id
        or game.phase_state != expected_phase_state
        or not game.phase_id.startswith("day_")
    ):
        raise V2RepositoryError("pre-exile pipeline generation phase changed")
    pipeline = db.scalar(
        select(V2PreExilePipeline)
        .where(V2PreExilePipeline.pipeline_id == str(pipeline_context["pipeline_id"]))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if pipeline is None:
        raise V2RepositoryError("unknown pre-exile pipeline")
    fence = current_v2_run_fence()
    if (
        pipeline.game_id != game.game_id
        or pipeline.run_id != run.run_id
        or pipeline.fence_worker_id != run.worker_id
        or pipeline.fence_token != run.fence_token
        or (
            fence is not None
            and (
                fence.run_id != pipeline.run_id
                or fence.worker_id != pipeline.fence_worker_id
                or fence.fence_token != pipeline.fence_token
            )
        )
    ):
        raise V2ExecutionOwnershipLost("v2_pre_exile_pipeline_fence_lost")
    if pipeline.state not in {"collecting", "no_explosion"}:
        raise V2RepositoryError("pre-exile pipeline is not collecting results")
    actor = context.get("actor")
    actor_player_id = actor.get("id") if isinstance(actor, dict) else None
    result = db.scalar(
        select(V2PreExileResult)
        .where(
            V2PreExileResult.pipeline_id == pipeline.pipeline_id,
            V2PreExileResult.actor_player_id == actor_player_id,
            V2PreExileResult.result_kind == result_kind,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise V2RepositoryError("pre-exile result was not reserved")
    if result.state != "reserved" or result.action_id is not None:
        raise V2RepositoryError("pre-exile result already has durable provider lineage")
    output_contract = context.get("output_contract")
    output_valid = type(output_contract) is dict and (
        (
            result_kind == "self_explosion"
            and output_contract.get("kind") == "boolean"
            and output_contract.get("field") == "explode"
        )
        or (
            result_kind == "exile_vote"
            and output_contract.get("kind") == "target"
            and (output_contract.get("target_policy") or {}).get("mode") == "required"
        )
    )
    if (
        pipeline.phase_id != game.phase_id
        or type(context.get("schema_version")) is not int
        or context.get("schema_version") != 1
        or context.get("action_id") != action_id
        or context.get("action_type") != expected_action_type
        or context.get("game_id") != game.game_id
        or context.get("phase_id") != pipeline.phase_id
        or actor != {"kind": "player", "id": result.actor_player_id}
        or context.get("public_history_cutoff_record_seq") != pipeline.public_cutoff_record_seq
        or "projection_at_seq" in context
        or not output_valid
    ):
        raise V2RepositoryError("pre-exile pipeline action lineage is invalid")
    active = list(
        db.scalars(
            select(V2LivePresentation).where(
                V2LivePresentation.game_id == game.game_id,
                V2LivePresentation.state == "active",
            )
        )
    )
    if game.status in {"broadcasting", "finalizing"}:
        if (
            len(active) != 1
            or active[0].presentation_id != pipeline.predecessor_presentation_id
            or active[0].action_id != pipeline.predecessor_action_id
            or active[0].source_event_id != pipeline.predecessor_source_event_id
            or active[0].closed_at is not None
        ):
            raise V2RepositoryError("pre-exile predecessor is no longer active")
    else:
        if active:
            raise V2RepositoryError("pre-exile closed-stage claim found an active presentation")
        predecessor = db.scalar(
            select(V2LivePresentation).where(
                V2LivePresentation.game_id == game.game_id,
                V2LivePresentation.presentation_id == pipeline.predecessor_presentation_id,
            )
        )
        if (
            predecessor is None
            or predecessor.run_id != pipeline.run_id
            or predecessor.action_id != pipeline.predecessor_action_id
            or predecessor.source_event_id != pipeline.predecessor_source_event_id
            or predecessor.state != "closed"
            or predecessor.closed_at is None
        ):
            raise V2RepositoryError("pre-exile predecessor is not durably closed")
        closed_events = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.run_id == run.run_id,
                    V2GameRecordEvent.event_type == "speech_closed",
                    V2GameRecordEvent.record_seq > pipeline.predecessor_sealed_record_seq,
                )
            )
        )
        if (
            sum(
                isinstance(event.payload, dict)
                and event.payload.get("action_id") == pipeline.predecessor_action_id
                and event.payload.get("presentation_id") == pipeline.predecessor_presentation_id
                for event in closed_events
            )
            != 1
        ):
            raise V2RepositoryError("pre-exile predecessor has no unique close event")
        later_events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.run_id == run.run_id,
                    V2GameRecordEvent.record_seq > pipeline.predecessor_sealed_record_seq,
                    V2GameRecordEvent.event_type.in_(
                        (
                            "speech_segment_committed",
                            "day_vote_committed",
                            "day_vote_resolved",
                        )
                    ),
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        for event in later_events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            if event.event_type in {"day_vote_committed", "day_vote_resolved"} or (
                payload.get("audience") in {"all", "public"}
                and payload.get("presentation_id") != pipeline.predecessor_presentation_id
            ):
                raise V2RepositoryError("pre-exile closed-stage claim crossed a public boundary")
    assignment = db.scalar(
        select(V2RoleAssignment).where(
            V2RoleAssignment.game_id == game.game_id,
            V2RoleAssignment.player_id == result.actor_player_id,
        )
    )
    if assignment is None:
        raise V2RepositoryError("pre-exile result actor has no role assignment")
    if result_kind == "self_explosion" and (
        assignment.role_key != "werewolf" or pipeline.state != "collecting"
    ):
        raise V2RepositoryError("invalid pre-exile self-explosion member")
    own_result: V2PreExileResult | None = None
    if result_kind == "exile_vote" and assignment.role_key == "werewolf":
        own_result = db.scalar(
            select(V2PreExileResult).where(
                V2PreExileResult.pipeline_id == pipeline.pipeline_id,
                V2PreExileResult.actor_player_id == result.actor_player_id,
                V2PreExileResult.result_kind == "self_explosion",
            )
        )
        if (
            own_result is None
            or own_result.state not in {"ready", "failed", "committed"}
            or bool((own_result.decision or {}).get("explode"))
            or own_result.private_fact_id is None
            or own_result.private_fact_record_seq is None
        ):
            raise V2RepositoryError(
                "werewolf speculative vote requires own durable no-explosion fact"
            )
    _validate_pre_exile_frozen_action_context(
        db,
        game=game,
        pipeline=pipeline,
        result=result,
        actor_role_key=assignment.role_key,
        own_self_result=own_result,
        context=context,
    )
    result.action_id = action_id
    result.state = "generating"
    result.generation_started_at = datetime.now(tz=UTC)
    _append_event(
        db,
        game=game,
        run_id=run.run_id,
        event_type="pre_exile_result_generation_started",
        audience="god_view",
        payload={
            "pipeline_id": pipeline.pipeline_id,
            "result_id": result.result_id,
            "result_kind": result.result_kind,
            "actor_player_id": result.actor_player_id,
            "action_id": action_id,
            "public_history_cutoff_record_seq": (pipeline.public_cutoff_record_seq),
        },
    )


def _bind_pre_exile_vote_recovery_claim(
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
    recovery = context.get("pre_exile_recovery")
    expected_recovery_keys = {
        "pipeline_id",
        "result_id",
        "source_action_id",
        "model_admission_mode",
    }
    if (
        type(recovery) is not dict
        or set(recovery) != expected_recovery_keys
        or recovery.get("model_admission_mode") != "normal"
        or game.status != "ready"
        or run.status != "ready"
        or game.phase_id != expected_phase_id
        or game.phase_state != expected_phase_state
        or audience != "god_view"
        or context_audience != "god_view"
        or activation_id is not None
        or best_effort
        or not non_blocking
        or "pipeline" in context
        or "projection_at_seq" in context
    ):
        raise V2RepositoryError("pre-exile vote recovery claim is invalid")
    try:
        contract = resolve_pre_exile_pipeline_contract(game.rule_snapshot)
    except V2PreExilePipelineContractError as exc:
        raise V2RepositoryError(str(exc)) from exc
    if (
        not contract.enables("exile_vote")
        or contract.speculative_vote_admission_mode != "idle_only"
        or contract.speculative_vote_capacity_recovery_mode != "normal_batch_after_close_once"
        or contract.fallback_mode != "before_launch_sequential_only"
        or contract.inflight_recovery_mode != "no_duplicate_provider"
    ):
        raise V2RepositoryError("pre-exile vote recovery contract is not enabled")
    pipeline = db.scalar(
        select(V2PreExilePipeline)
        .where(V2PreExilePipeline.pipeline_id == recovery.get("pipeline_id"))
        .with_for_update()
    )
    result = db.scalar(
        select(V2PreExileResult)
        .where(V2PreExileResult.result_id == recovery.get("result_id"))
        .with_for_update()
    )
    if (
        pipeline is None
        or result is None
        or pipeline.game_id != game.game_id
        or pipeline.run_id != run.run_id
        or pipeline.fence_worker_id != run.worker_id
        or pipeline.fence_token != run.fence_token
        or pipeline.phase_id != game.phase_id
        or pipeline.state not in {"collecting", "no_explosion"}
        or result.pipeline_id != pipeline.pipeline_id
        or result.result_kind != "exile_vote"
        or result.state != "failed"
        or result.action_id != recovery.get("source_action_id")
        or result.recovery_action_id is not None
        or context.get("action_id") != action_id
        or context.get("action_type") != "exile_vote"
        or context.get("game_id") != game.game_id
        or context.get("phase_id") != game.phase_id
        or context.get("actor") != {"kind": "player", "id": result.actor_player_id}
        or context.get("public_history_cutoff_record_seq") != pipeline.public_cutoff_record_seq
        or context.get("batch_id")
        != f"{pipeline.phase_id}:exile_vote:{pipeline.public_cutoff_record_seq}:vote"
    ):
        raise V2RepositoryError("pre-exile vote recovery lineage is invalid")
    from app.v2.pre_exile_pipeline_repository import (
        _validate_admission_capacity_recovery_source,
    )

    _validate_admission_capacity_recovery_source(
        db,
        pipeline=pipeline,
        row=result,
    )
    predecessor = db.scalar(
        select(V2LivePresentation).where(
            V2LivePresentation.game_id == game.game_id,
            V2LivePresentation.presentation_id == pipeline.predecessor_presentation_id,
        )
    )
    if predecessor is None or predecessor.state != "closed" or predecessor.closed_at is None:
        raise V2RepositoryError("pre-exile vote recovery requires closed predecessor")
    later_public = list(
        db.scalars(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == game.game_id,
                V2GameRecordEvent.run_id == run.run_id,
                V2GameRecordEvent.record_seq > pipeline.predecessor_sealed_record_seq,
                V2GameRecordEvent.event_type.in_(
                    (
                        "speech_segment_committed",
                        "day_vote_committed",
                        "day_vote_resolved",
                    )
                ),
            )
        )
    )
    if any(
        event.event_type in {"day_vote_committed", "day_vote_resolved"}
        or (
            isinstance(event.payload, dict)
            and event.payload.get("audience") in {"all", "public"}
            and event.payload.get("presentation_id") != pipeline.predecessor_presentation_id
        )
        for event in later_public
    ):
        raise V2RepositoryError("pre-exile vote recovery crossed a public boundary")
    assignment = db.scalar(
        select(V2RoleAssignment).where(
            V2RoleAssignment.game_id == game.game_id,
            V2RoleAssignment.player_id == result.actor_player_id,
        )
    )
    if assignment is None:
        raise V2RepositoryError("pre-exile recovery actor has no role assignment")
    own_result = (
        db.scalar(
            select(V2PreExileResult).where(
                V2PreExileResult.pipeline_id == pipeline.pipeline_id,
                V2PreExileResult.actor_player_id == result.actor_player_id,
                V2PreExileResult.result_kind == "self_explosion",
            )
        )
        if assignment.role_key == "werewolf"
        else None
    )
    _validate_pre_exile_frozen_action_context(
        db,
        game=game,
        pipeline=pipeline,
        result=result,
        actor_role_key=assignment.role_key,
        own_self_result=own_result,
        context=context,
    )
    result.recovery_action_id = action_id
    _append_event(
        db,
        game=game,
        run_id=run.run_id,
        event_type="pre_exile_vote_recovery_started",
        audience="god_view",
        payload={
            "pipeline_id": pipeline.pipeline_id,
            "result_id": result.result_id,
            "actor_player_id": result.actor_player_id,
            "source_action_id": result.action_id,
            "recovery_action_id": action_id,
            "recovery_reason": "idle_admission_capacity_unavailable",
            "provider_repeat_policy": "before_provider_only_once",
        },
    )


def _validate_pre_exile_frozen_action_context(
    db: Session,
    *,
    game: V2GameRecord,
    pipeline: V2PreExilePipeline,
    result: V2PreExileResult,
    actor_role_key: str,
    own_self_result: V2PreExileResult | None,
    context: dict[str, Any],
) -> None:
    public_history = context.get("public_history")
    if (
        type(public_history) is not list
        or any(type(item) is not dict for item in public_history)
        or pre_exile_context_sha256(public_history) != pipeline.public_history_sha256
    ):
        raise V2RepositoryError("pre-exile public history changed from frozen snapshot")
    for item in public_history:
        record_seq = item.get("record_seq")
        known_at_seq = item.get("known_at_seq")
        if (
            type(record_seq) is not int
            or record_seq <= 0
            or record_seq > pipeline.public_cutoff_record_seq
            or known_at_seq is not None
            and (
                type(known_at_seq) is not int
                or known_at_seq <= 0
                or known_at_seq > pipeline.public_cutoff_record_seq
            )
        ):
            raise V2RepositoryError("pre-exile public history crossed its cutoff")

    sealed_private = [
        fact
        for fact in player_private_knowledge(
            db,
            game_id=game.game_id,
            player_id=result.actor_player_id,
        )
        if _pre_exile_fact_clock(fact) is not None
        and int(_pre_exile_fact_clock(fact) or 0) <= pipeline.public_cutoff_record_seq
    ]
    expected_private = [deepcopy(fact) for fact in sealed_private]
    provisional_fact: dict[str, Any] | None = None
    if actor_role_key == "werewolf" and result.result_kind == "exile_vote":
        provisional_fact = _pre_exile_provisional_fact_for_claim(
            db,
            pipeline=pipeline,
            actor_player_id=result.actor_player_id,
            own_self_result=own_self_result,
        )
        expected_private.append(provisional_fact)
    if actor_role_key == "werewolf":
        teammates = list(
            db.execute(
                select(V2RoleAssignment.player_id, V2RoleAssignment.seat)
                .join(
                    V2PlayerState,
                    (V2PlayerState.game_id == V2RoleAssignment.game_id)
                    & (V2PlayerState.player_id == V2RoleAssignment.player_id),
                )
                .where(
                    V2RoleAssignment.game_id == game.game_id,
                    V2RoleAssignment.role_key == "werewolf",
                    V2PlayerState.alive.is_(True),
                    V2RoleAssignment.player_id != result.actor_player_id,
                )
                .order_by(V2RoleAssignment.seat)
            )
        )
        expected_private.append(
            {
                "fact_type": "living_werewolf_teammates",
                "payload": [player_id for player_id, _seat in teammates],
                "owner_scope": "player",
                "owner_id": result.actor_player_id,
            }
        )
    private_facts = context.get("private_authoritative_facts")
    if type(private_facts) is not list or any(type(item) is not dict for item in private_facts):
        raise V2RepositoryError("pre-exile private authoritative facts are invalid")
    durable_fact_ids: set[str] = set()
    provisional_id = (
        provisional_fact.get("knowledge_fact_id") if provisional_fact is not None else None
    )
    provisional_clock = (
        _pre_exile_fact_clock(provisional_fact) if provisional_fact is not None else None
    )
    for fact in private_facts:
        if fact.get("owner_scope") != "player" or fact.get("owner_id") != result.actor_player_id:
            raise V2RepositoryError("pre-exile private fact owner changed")
        fact_id = fact.get("knowledge_fact_id")
        if fact_id is None:
            continue
        if not isinstance(fact_id, str) or not fact_id or fact_id in durable_fact_ids:
            raise V2RepositoryError("pre-exile private fact identity is invalid")
        durable_fact_ids.add(fact_id)
        clock = _pre_exile_fact_clock(fact)
        if clock is None:
            raise V2RepositoryError("pre-exile private fact has no durable clock")
        if clock > pipeline.public_cutoff_record_seq and not (
            fact_id == provisional_id and clock == provisional_clock
        ):
            raise V2RepositoryError("pre-exile private fact crossed its cutoff")
    if pre_exile_context_sha256(private_facts) != pre_exile_context_sha256(expected_private):
        raise V2RepositoryError("pre-exile private facts changed from sealed snapshot")


def _pre_exile_fact_clock(fact: dict[str, Any] | None) -> int | None:
    if not isinstance(fact, dict):
        return None
    known_at_seq = fact.get("known_at_seq")
    record_seq = fact.get("record_seq")
    value = known_at_seq if type(known_at_seq) is int else record_seq
    return value if type(value) is int and value > 0 else None


def _pre_exile_provisional_fact_for_claim(
    db: Session,
    *,
    pipeline: V2PreExilePipeline,
    actor_player_id: str,
    own_self_result: V2PreExileResult | None,
) -> dict[str, Any]:
    if (
        own_self_result is None
        or own_self_result.actor_player_id != actor_player_id
        or own_self_result.result_kind != "self_explosion"
        or own_self_result.state not in {"ready", "failed", "committed"}
        or bool((own_self_result.decision or {}).get("explode"))
        or not isinstance(own_self_result.private_fact_id, str)
        or type(own_self_result.private_fact_record_seq) is not int
    ):
        raise V2RepositoryError("werewolf speculative vote requires exact provisional false fact")
    fact = db.get(V2KnowledgeFact, own_self_result.private_fact_id)
    event = db.scalar(
        select(V2GameRecordEvent).where(
            V2GameRecordEvent.game_id == pipeline.game_id,
            V2GameRecordEvent.run_id == pipeline.run_id,
            V2GameRecordEvent.record_seq == own_self_result.private_fact_record_seq,
            V2GameRecordEvent.event_type == "private_knowledge_recorded",
        )
    )
    payload = deepcopy(fact.payload or {}) if fact is not None else {}
    fact_context = payload.get("context")
    event_payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    if (
        fact is None
        or event is None
        or fact.game_id != pipeline.game_id
        or fact.owner_scope != "player"
        or fact.owner_id != actor_player_id
        or fact.fact_type != "private_action_decision"
        or event_payload.get("knowledge_fact_id") != fact.knowledge_fact_id
        or payload.get("action_type") != "werewolf_self_explosion"
        or (payload.get("decision") or {}).get("explode") is not False
        or not isinstance(fact_context, dict)
        or fact_context.get("pipeline_id") != pipeline.pipeline_id
        or fact_context.get("public_history_cutoff_record_seq") != pipeline.public_cutoff_record_seq
        or fact_context.get("visibility_mode") != "pre_exile_provisional_until_atomic_arbiter"
    ):
        raise V2RepositoryError("pre-exile provisional false fact lineage changed")
    return {
        "knowledge_fact_id": fact.knowledge_fact_id,
        "source_activation_id": fact.source_activation_id,
        "owner_scope": fact.owner_scope,
        "owner_id": fact.owner_id,
        "fact_type": fact.fact_type,
        "payload": payload,
        "source_event_id": event.event_id,
        "source_event_type": event.event_type,
        "record_seq": event.record_seq,
        "known_at_seq": event.record_seq,
        "occurred_in": {"period": "day", "round_no": pipeline.round_no},
    }


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
