from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.v2.action_engine import V2ActionFailure, V2ActionResult, V2SpeechSpec
from app.v2.day_engine import V2DayEngine
from app.v2.day_speech_pipeline_contract import (
    freeze_day_speech_pipeline_contract,
    resolve_day_speech_pipeline_contract,
)
from app.v2.day_speech_pipeline_repository import V2DaySpeechSlotSnapshot
from app.v2.live_runtime import V2LiveRuntime
from app.v2.match_repository import (
    V2DaySpeechPrefetchSnapshot,
    V2MatchPlayer,
    V2MatchSnapshot,
)
from app.v2.model_client import V2ModelDecision
from app.v2.repository import V2PresentationIdentity


GAME_ID = "v2_game_pipeline_orchestration"
RUN_ID = "v2_run_pipeline_orchestration"
PHASE_ID = "day_1"
PHASE_STATE = "public_discussion_open"


class _Broadcaster:
    async def broadcast_json(self, _value: dict[str, Any], *, audience: str = "all") -> None:
        del audience

    async def broadcast_bytes(self, _value: bytes, *, audience: str = "all") -> None:
        del audience

    async def broadcast_audio(
        self,
        _value: bytes,
        *,
        identity: V2PresentationIdentity,
        next_sample_cursor: int,
        audience: str = "all",
    ) -> None:
        del identity, next_sample_cursor, audience

    async def set_current(
        self,
        _identity: V2PresentationIdentity | None,
        _sample_cursor: int,
        *,
        audience: str = "all",
    ) -> None:
        del audience


class _MatchRepository:
    def __init__(self, snapshot: V2MatchSnapshot) -> None:
        self.state = snapshot
        self.record_seq = snapshot.last_record_seq
        self.presentation_seq = 0
        self.public_commits: list[dict[str, Any]] = []
        self.prefetch_cutoffs: list[dict[str, Any]] = []
        self.fail_next_public_commit = False
        self.action_failures: dict[int, tuple[str, V2ActionFailure]] = {}

    def snapshot(self, game_id: str) -> V2MatchSnapshot:
        assert game_id == GAME_ID
        return self.state

    def private_knowledge(self, *, game_id: str, player_id: str) -> list[dict[str, Any]]:
        assert game_id == GAME_ID and player_id
        return []

    def append_event(
        self,
        *,
        game_id: str,
        event_type: str,
        audience: str,
        payload: dict[str, Any],
    ) -> int:
        assert game_id == GAME_ID
        if event_type == "day_speech_committed" and self.fail_next_public_commit:
            self.fail_next_public_commit = False
            raise RuntimeError("synthetic public commit failure")
        self.record_seq += 1
        item = {
            "source_event_id": self.record_seq,
            "record_seq": self.record_seq,
            "event_type": event_type,
            "payload": {**payload, "audience": audience},
        }
        history = tuple(
            sorted((*self.state.public_history, item), key=lambda row: row["record_seq"])
        )
        self.state = replace(
            self.state,
            last_record_seq=self.record_seq,
            public_history=history,
        )
        if event_type == "day_speech_committed":
            self.public_commits.append(payload)
        return self.record_seq

    def open_presentation(
        self,
        *,
        actor_id: str,
        action_id: str,
        speech: str,
        actor_kind: str = "player",
    ) -> V2PresentationIdentity:
        self.presentation_seq += 1
        self.record_seq += 4
        source_record_seq = self.record_seq - 1
        self.state = replace(self.state, last_record_seq=self.record_seq)
        return V2PresentationIdentity(
            game_id=GAME_ID,
            run_id=RUN_ID,
            action_id=action_id,
            phase_id=PHASE_ID,
            presentation_seq=self.presentation_seq,
            presentation_id=f"v2_pres_{self.presentation_seq}",
            speech_id=f"v2_speech_{self.presentation_seq}",
            segment_index=0,
            voice_asset_id=f"v2_voice_{self.presentation_seq}",
            storage_key=f"{GAME_ID}/v2_voice_{self.presentation_seq}.wav",
            subtitle_text=speech,
            audience="all",
            actor_kind=actor_kind,  # type: ignore[arg-type]
            actor_id=actor_id,
            source_event_id=10_000 + source_record_seq,
            source_record_seq=source_record_seq,
        )

    def close_presentation(self, identity: V2PresentationIdentity) -> None:
        assert identity.source_record_seq is not None
        self.record_seq += 2
        if identity.actor_kind != "player":
            self.state = replace(self.state, last_record_seq=self.record_seq)
            return
        item = {
            "source_event_id": identity.source_event_id,
            "record_seq": identity.source_record_seq,
            "event_type": "public_player_speech_presented",
            "payload": {
                "round_no": 1,
                "stage": "day_debate_speech",
                "action_id": identity.action_id,
                "phase_id": identity.phase_id,
                "player_id": identity.actor_id,
                "speech": identity.subtitle_text,
            },
        }
        history = tuple(
            sorted((*self.state.public_history, item), key=lambda row: row["record_seq"])
        )
        self.state = replace(
            self.state,
            last_record_seq=self.record_seq,
            public_history=history,
        )

    def allocate_event(self) -> int:
        self.record_seq += 1
        self.state = replace(self.state, last_record_seq=self.record_seq)
        return self.record_seq

    def allocate_failure_event(
        self,
        *,
        action_id: str,
        failure: V2ActionFailure,
    ) -> int:
        record_seq = self.allocate_event()
        self.action_failures[record_seq] = (action_id, failure)
        return record_seq

    def snapshot_for_day_speech_prefetch(
        self,
        *,
        game_id: str,
        run_id: str,
        phase_id: str,
        phase_state: str,
        predecessor_presentation_id: str,
        predecessor_action_id: str,
        predecessor_source_event_id: int,
        predecessor_turn_player_id: str | None = None,
    ) -> V2DaySpeechPrefetchSnapshot:
        assert (game_id, run_id, phase_id, phase_state) == (
            GAME_ID,
            RUN_ID,
            PHASE_ID,
            PHASE_STATE,
        )
        source_record_seq = predecessor_source_event_id - 10_000
        cutoff = self.state.last_record_seq
        active_items: tuple[dict[str, Any], ...] = ()
        if predecessor_turn_player_id is None:
            active_items = (
                {
                    "source_event_id": predecessor_source_event_id,
                    "record_seq": source_record_seq,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "action_id": predecessor_action_id,
                        "phase_id": phase_id,
                        "player_id": "predecessor",
                        "speech": f"active:{predecessor_action_id}",
                    },
                },
            )
        frozen = replace(
            self.state,
            last_record_seq=cutoff,
            public_history=tuple(
                sorted(
                    (*self.state.public_history, *active_items), key=lambda row: row["record_seq"]
                )
            ),
        )
        self.prefetch_cutoffs.append(
            {
                "predecessor_action_id": predecessor_action_id,
                "source_record_seq": source_record_seq,
                "cutoff": cutoff,
            }
        )
        return V2DaySpeechPrefetchSnapshot(
            match_snapshot=frozen,
            public_cutoff_record_seq=cutoff,
            predecessor_presentation_id=predecessor_presentation_id,
            predecessor_action_id=predecessor_action_id,
            predecessor_source_event_id=predecessor_source_event_id,
            predecessor_source_record_seq=source_record_seq,
            predecessor_sealed_record_seq=cutoff,
            predecessor_actor_id=(predecessor_turn_player_id or "predecessor"),
        )


class _PipelineRepository:
    def __init__(self, repository: _MatchRepository) -> None:
        self.repository = repository
        self.slots: dict[str, V2DaySpeechSlotSnapshot] = {}
        self.reserve_calls: list[dict[str, Any]] = []
        self.events: list[tuple[str, str]] = []

    def reserve_slot(self, **kwargs: Any) -> V2DaySpeechSlotSnapshot:
        self.reserve_calls.append(dict(kwargs))
        slot = _slot(
            slot_id=f"v2_slot_{len(self.slots) + 1}",
            actor_player_id=str(kwargs["actor_player_id"]),
            speech_round=int(kwargs["speech_round"]),
            turn_index=int(kwargs["turn_index"]),
            predecessor_action_id=str(kwargs["predecessor_action_id"]),
            predecessor_presentation_id=str(kwargs["predecessor_presentation_id"]),
            predecessor_source_event_id=int(kwargs["predecessor_source_event_id"]),
            predecessor_source_record_seq=int(kwargs["predecessor_source_record_seq"]),
            context_cutoff_record_seq=int(kwargs["context_cutoff_record_seq"]),
        )
        self.slots[slot.slot_id] = slot
        self.events.append((slot.slot_id, "reserved"))
        return slot

    def get_slot(self, slot_id: str) -> V2DaySpeechSlotSnapshot:
        return self.slots[slot_id]

    def predecessor_is_active(self, slot_id: str) -> bool:
        return self.slots[slot_id].state in {"reserved", "generating"}

    def mark_generating(self, *, slot_id: str) -> V2DaySpeechSlotSnapshot:
        return self._state(slot_id, "generating")

    def mark_ready(
        self,
        *,
        slot_id: str,
        generation_action_id: str,
        generation_response_record_seq: int,
    ) -> V2DaySpeechSlotSnapshot:
        slot = self.slots[slot_id]
        updated = replace(
            slot,
            state="ready",
            generation_action_id=generation_action_id,
            generation_attempt_id=f"attempt_{slot.actor_player_id}",
            generation_response_record_seq=generation_response_record_seq,
            decision={"speech": f"prefetch:{slot.actor_player_id}"},
        )
        self.slots[slot_id] = updated
        self.events.append((slot_id, "ready"))
        return updated

    def mark_presenting(
        self,
        *,
        slot_id: str,
        presentation_action_id: str,
        presentation_id: str,
    ) -> V2DaySpeechSlotSnapshot:
        slot = self.slots[slot_id]
        updated = replace(
            slot,
            state="presenting",
            presentation_action_id=presentation_action_id,
            presentation_id=presentation_id,
        )
        self.slots[slot_id] = updated
        self.events.append((slot_id, "presenting"))
        return updated

    def mark_consumed(self, *, slot_id: str) -> V2DaySpeechSlotSnapshot:
        return self._state(slot_id, "consumed")

    def mark_failed(
        self,
        *,
        slot_id: str,
        failure_record_seq: int,
    ) -> V2DaySpeechSlotSnapshot:
        slot = self.slots[slot_id]
        action_id, action_failure = self.repository.action_failures[failure_record_seq]
        failure = {
            "stage": "generation" if slot.state == "generating" else "presentation",
            "action_failed": {
                "action_id": action_id,
                "failure_code": action_failure.code,
                "failure_episode_id": action_failure.failure_episode_id,
            },
            "model_request_failed": {
                "failure_code": action_failure.code,
                "failure_category": action_failure.category,
                "failure_episode_id": action_failure.failure_episode_id,
            },
            "generation_attempt_id": action_failure.terminal_attempt_id,
        }
        updated = replace(
            slot,
            state="failed",
            generation_action_id=(
                action_id if slot.state == "generating" else slot.generation_action_id
            ),
            generation_attempt_id=(
                action_failure.terminal_attempt_id
                if slot.state == "generating"
                else slot.generation_attempt_id
            ),
            failure_record_seq=failure_record_seq,
            failure=failure,
        )
        self.slots[slot_id] = updated
        self.events.append((slot_id, "failed"))
        return updated

    def cancel_slot(
        self,
        *,
        slot_id: str,
        reason_code: str,
    ) -> V2DaySpeechSlotSnapshot:
        slot = self.slots[slot_id]
        if slot.state in {"consumed", "failed", "canceled", "invalidated"}:
            return slot
        updated = replace(
            slot,
            state="canceled",
            failure={"kind": "canceled", "reason_code": reason_code},
        )
        self.slots[slot_id] = updated
        self.events.append((slot_id, "canceled"))
        return updated

    def _state(self, slot_id: str, state: str) -> V2DaySpeechSlotSnapshot:
        updated = replace(self.slots[slot_id], state=state)
        self.slots[slot_id] = updated
        self.events.append((slot_id, state))
        return updated


class _Actions:
    def __init__(
        self,
        repository: _MatchRepository,
        *,
        failed_prefetch_actors: set[str] | None = None,
        prefetch_failures: dict[str, tuple[str, str | None]] | None = None,
        failed_presentation_actors: set[str] | None = None,
        block_generation: bool = False,
        block_prefetch_generation: bool = False,
        complete_prefetch_on_cancel: bool = False,
        prefetch_generation_release: asyncio.Event | None = None,
    ) -> None:
        self.repository = repository
        self.failed_prefetch_actors = set(failed_prefetch_actors or ())
        self.prefetch_failures = dict(prefetch_failures or {})
        self.failed_presentation_actors = set(failed_presentation_actors or ())
        self.block_generation = block_generation
        self.block_prefetch_generation = block_prefetch_generation
        self.complete_prefetch_on_cancel = complete_prefetch_on_cancel
        self.prefetch_generation_release = prefetch_generation_release
        self.foreground_actors: list[str] = []
        self.prefetched_actors: list[str] = []
        self.precomputed_actors: list[str] = []
        self.overlaps: list[tuple[str, str]] = []
        self.generation_specs: list[V2SpeechSpec] = []
        self.active_presentations: set[str] = set()
        self.generation_started = asyncio.Event()
        self.presentation_closed = asyncio.Event()
        self.active_generation_count = 0
        self.generation_action_ids: list[str] = []
        self.technical_skips: list[dict[str, Any]] = []
        self.model_retry_guards: list[Any] = []
        self._action_index = 0

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision(
        self,
        *,
        game_id: str,
        broadcaster: Any,
        spec: V2SpeechSpec,
        on_presentation_opened: Any = None,
        on_presentation_closed: Any = None,
    ) -> V2ModelDecision | None:
        result = await self.run_player_decision_result(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=spec,
            on_presentation_opened=on_presentation_opened,
            on_presentation_closed=on_presentation_closed,
        )
        return result.decision if result is not None else None

    async def run_player_decision_result(
        self,
        *,
        game_id: str,
        broadcaster: Any,
        spec: V2SpeechSpec,
        on_presentation_opened: Any = None,
        on_presentation_closed: Any = None,
        model_retry_guard: Any = None,
    ) -> V2ActionResult | None:
        if spec.pipeline_stage == "generation":
            self.model_retry_guards.append(model_retry_guard)
        assert game_id == GAME_ID
        if spec.pipeline_stage == "generation":
            return await self._generate(spec)
        self.foreground_actors.append(spec.actor_id)
        decision = _decision(f"foreground:{spec.actor_id}")
        return await self._present(
            spec=spec,
            decision=decision,
            on_presentation_opened=on_presentation_opened,
            on_presentation_closed=on_presentation_closed,
        )

    async def present_player_decision_result(
        self,
        *,
        game_id: str,
        broadcaster: Any,
        spec: V2SpeechSpec,
        decision: V2ModelDecision,
        on_presentation_opened: Any = None,
        on_presentation_closed: Any = None,
    ) -> V2ActionResult | None:
        del broadcaster
        assert game_id == GAME_ID and spec.pipeline_stage == "presentation"
        self.precomputed_actors.append(spec.actor_id)
        return await self._present(
            spec=spec,
            decision=decision,
            on_presentation_opened=on_presentation_opened,
            on_presentation_closed=on_presentation_closed,
        )

    async def _generate(self, spec: V2SpeechSpec) -> V2ActionResult:
        self.prefetched_actors.append(spec.actor_id)
        self.generation_specs.append(spec)
        self.active_generation_count += 1
        self.generation_started.set()
        for predecessor in self.active_presentations:
            self.overlaps.append((predecessor, spec.actor_id))
        self._action_index += 1
        action_id = f"v2_generation_{self._action_index}_{spec.actor_id}"
        self.generation_action_ids.append(action_id)
        try:
            if self.prefetch_generation_release is not None:
                await self.prefetch_generation_release.wait()
            elif self.block_generation or self.block_prefetch_generation:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError as exc:
                    if self.complete_prefetch_on_cancel:
                        pass
                    elif exc.args and exc.args[0] == ("day_speech_prefetch_post_close_deadline"):
                        failure = V2ActionFailure(
                            code="day_speech_prefetch_post_close_deadline",
                            category="timeout",
                            terminal_attempt_id=f"attempt_{spec.actor_id}",
                        )
                        return V2ActionResult(
                            action_id=action_id,
                            failure=failure,
                            terminal_event_record_seq=(
                                self.repository.allocate_failure_event(
                                    action_id=action_id,
                                    failure=failure,
                                )
                            ),
                        )
                    else:
                        raise
            await asyncio.sleep(0)
            if spec.actor_id in self.failed_prefetch_actors:
                self.failed_prefetch_actors.remove(spec.actor_id)
                failure = V2ActionFailure(
                    code="model_prefetch_capacity_unavailable",
                    category="transport",
                    terminal_attempt_id=f"attempt_{spec.actor_id}",
                )
                return V2ActionResult(
                    action_id=action_id,
                    failure=failure,
                    terminal_event_record_seq=self.repository.allocate_failure_event(
                        action_id=action_id,
                        failure=failure,
                    ),
                )
            configured_failure = self.prefetch_failures.pop(spec.actor_id, None)
            if configured_failure is not None:
                failure_code, failure_category = configured_failure
                failure = V2ActionFailure(
                    code=failure_code,
                    category=failure_category,
                    terminal_attempt_id=f"attempt_{spec.actor_id}",
                )
                return V2ActionResult(
                    action_id=action_id,
                    failure=failure,
                    terminal_event_record_seq=self.repository.allocate_failure_event(
                        action_id=action_id,
                        failure=failure,
                    ),
                )
            decision = _decision(f"prefetch:{spec.actor_id}")
            return V2ActionResult(
                action_id=action_id,
                decision=decision,
                model_response_record_seq=self.repository.allocate_event(),
                terminal_event_record_seq=self.repository.allocate_event(),
            )
        finally:
            self.active_generation_count -= 1

    async def _present(
        self,
        *,
        spec: V2SpeechSpec,
        decision: V2ModelDecision,
        on_presentation_opened: Any,
        on_presentation_closed: Any,
    ) -> V2ActionResult:
        self._action_index += 1
        action_id = f"v2_presentation_{self._action_index}_{spec.actor_id}"
        identity = self.repository.open_presentation(
            actor_id=spec.actor_id,
            action_id=action_id,
            speech=decision.speech or "",
        )
        self.active_presentations.add(spec.actor_id)
        try:
            if on_presentation_opened is not None:
                on_presentation_opened(identity)
            if spec.actor_id in self.failed_presentation_actors:
                self.failed_presentation_actors.remove(spec.actor_id)
                await asyncio.sleep(0)
                failure = V2ActionFailure(
                    code="synthetic_tts_failure",
                    category=None,
                    terminal_attempt_id=None,
                )
                return V2ActionResult(
                    action_id=action_id,
                    failure=failure,
                    terminal_event_record_seq=self.repository.allocate_failure_event(
                        action_id=action_id,
                        failure=failure,
                    ),
                )
            if self.block_generation:
                await asyncio.Event().wait()
            else:
                await asyncio.sleep(0.01)
        finally:
            self.active_presentations.discard(spec.actor_id)
        self.repository.close_presentation(identity)
        self.presentation_closed.set()
        terminal_event_record_seq = self.repository.allocate_event()
        if on_presentation_closed is not None:
            on_presentation_closed(identity)
        return V2ActionResult(
            action_id=action_id,
            decision=decision,
            terminal_event_record_seq=terminal_event_record_seq,
        )

    async def complete_pipeline_speech_technical_skip(
        self,
        **kwargs: Any,
    ) -> V2ActionResult:
        self._action_index += 1
        action_id = f"v2_judge_technical_skip_{self._action_index}_{kwargs['player_id']}"
        self.technical_skips.append(dict(kwargs))
        self.repository.append_event(
            game_id=kwargs["game_id"],
            event_type="action_skipped_technical",
            audience="all",
            payload={
                "action_id": kwargs["source_action_id"],
                "phase_id": kwargs["phase_id"],
                "action_type": kwargs["action_type"],
                "actor_id": kwargs["player_id"],
                "player_seat": kwargs["player_seat"],
                "round_no": kwargs["round_no"],
                "reason": "technical_failure",
            },
        )
        identity = self.repository.open_presentation(
            actor_id="judge",
            actor_kind="judge",
            action_id=action_id,
            speech=f"{kwargs['player_seat']}号本轮因技术原因未能完成发言，流程继续",
        )
        on_presentation_opened = kwargs.get("on_presentation_opened")
        self.active_presentations.add("judge")
        try:
            if on_presentation_opened is not None:
                on_presentation_opened(identity)
            await asyncio.sleep(0.01)
        finally:
            self.active_presentations.discard("judge")
        self.repository.close_presentation(identity)
        terminal_record_seq = self.repository.allocate_event()
        on_presentation_closed = kwargs.get("on_presentation_closed")
        if on_presentation_closed is not None:
            on_presentation_closed(identity)
        return V2ActionResult(
            action_id=action_id,
            terminal_event_record_seq=terminal_record_seq,
        )


class _DayEngine(V2DayEngine):
    async def _offer_all_wolves_explosion(self, **_kwargs: Any) -> bool:
        return False


def _player(player_id: str, seat: int) -> V2MatchPlayer:
    return V2MatchPlayer(
        player_id=player_id,
        seat=seat,
        display_name=f"{seat}号玩家",
        role_key="villager",
        team="villagers",
        alive=True,
        tts_speaker=f"speaker-{seat}",
        tts_dialect=None,
        model_provider="agent_plan",
        model_id="test-model",
        model_supports_thinking=False,
        model_parameters={},
        persona={},
        state={},
    )


def _snapshot(
    *,
    audio_mode: str = "tts",
    pipeline_enabled: bool = True,
    speech_rounds: int = 1,
    player_count: int = 3,
    schema_version: int = 3,
    post_close_grace_ms: int | None = None,
) -> V2MatchSnapshot:
    rule_snapshot: dict[str, Any] = {}
    if pipeline_enabled:
        if schema_version == 1:
            rule_snapshot["day_speech_pipeline_contract"] = {
                "schema_version": 1,
                "mode": "one_ahead",
                "action_types": ["day_debate_speech"],
                "max_lookahead": 1,
                "context_source": "active_sealed_predecessor",
                "admission_mode": "idle_only",
                "fallback_mode": "fallback_sequential",
            }
        elif schema_version == 2:
            rule_snapshot["day_speech_pipeline_contract"] = {
                "schema_version": 2,
                "mode": "one_ahead",
                "action_types": ["day_debate_speech"],
                "max_lookahead": 1,
                "context_source": "active_sealed_predecessor",
                "admission_mode": "idle_only",
                "fallback_mode": "fallback_sequential",
                "post_predecessor_close_grace_ms": 30_000,
                "duplicate_foreground_fallback_forbidden_failure_categories": [
                    "output_budget",
                    "timeout",
                ],
                "early_transport_hidden_retry_max_retries": 1,
                "prefetch_capacity_unavailable_fallback_mode": "fallback_sequential",
            }
        elif schema_version == 3:
            rule_snapshot = freeze_day_speech_pipeline_contract(rule_snapshot)
        else:
            raise ValueError("unsupported test day speech pipeline schema")
    resolved_pipeline_contract = resolve_day_speech_pipeline_contract(rule_snapshot)
    if post_close_grace_ms is not None:
        resolved_pipeline_contract = replace(
            resolved_pipeline_contract,
            post_predecessor_close_grace_ms=post_close_grace_ms,
        )
    return V2MatchSnapshot(
        game_id=GAME_ID,
        run_id=RUN_ID,
        last_record_seq=1,
        phase_id=PHASE_ID,
        phase_state=PHASE_STATE,
        round_no=1,
        sheriff_player_id=None,
        sheriff_badge_state="disabled",
        pre_sheriff_explosion_count=0,
        rule={
            "id": "pipeline-orchestration-test",
            "sheriff_enabled": False,
            "speech_policy": "sequential",
            "speech_rounds": speech_rounds,
            "day_actions": [],
            "ability_policies": {},
        },
        max_rounds=8,
        model_context_contract={},
        model_generation_policy_contract=None,
        day_speech_pipeline_contract=resolved_pipeline_contract,
        audio_mode=audio_mode,  # type: ignore[arg-type]
        players=tuple(_player(f"player_{index}", index) for index in range(1, player_count + 1)),
        public_history=(),
    )


def _slot(
    *,
    slot_id: str,
    actor_player_id: str,
    speech_round: int,
    turn_index: int,
    predecessor_action_id: str,
    predecessor_presentation_id: str,
    predecessor_source_event_id: int,
    predecessor_source_record_seq: int,
    context_cutoff_record_seq: int,
) -> V2DaySpeechSlotSnapshot:
    now = datetime.now(tz=UTC)
    return V2DaySpeechSlotSnapshot(
        slot_id=slot_id,
        game_id=GAME_ID,
        run_id=RUN_ID,
        fence_worker_id="v2_test_worker",
        fence_token=1,
        phase_id=PHASE_ID,
        round_no=1,
        speech_round=speech_round,
        turn_index=turn_index,
        action_type="day_debate_speech",
        actor_player_id=actor_player_id,
        predecessor_action_id=predecessor_action_id,
        predecessor_presentation_id=predecessor_presentation_id,
        predecessor_source_event_id=predecessor_source_event_id,
        predecessor_source_record_seq=predecessor_source_record_seq,
        context_cutoff_record_seq=context_cutoff_record_seq,
        state="reserved",
        generation_action_id=None,
        generation_attempt_id=None,
        generation_response_record_seq=None,
        decision=None,
        presentation_action_id=None,
        presentation_id=None,
        failure_record_seq=None,
        failure=None,
        created_at=now,
        updated_at=now,
        generation_started_at=None,
        ready_at=None,
        presenting_at=None,
        consumed_at=None,
        terminal_at=None,
    )


def _decision(speech: str) -> V2ModelDecision:
    return V2ModelDecision(
        target_player_id=None,
        speech=speech,
        provider_request_id=f"request:{speech}",
        first_token_ms=1,
        completed_ms=2,
    )


def _engine(
    snapshot: V2MatchSnapshot,
    *,
    failed_prefetch_actors: set[str] | None = None,
    prefetch_failures: dict[str, tuple[str, str | None]] | None = None,
    failed_presentation_actors: set[str] | None = None,
    block_generation: bool = False,
    block_prefetch_generation: bool = False,
    complete_prefetch_on_cancel: bool = False,
    prefetch_generation_release: asyncio.Event | None = None,
) -> tuple[_DayEngine, _MatchRepository, _PipelineRepository, _Actions]:
    repository = _MatchRepository(snapshot)
    pipeline = _PipelineRepository(repository)
    actions = _Actions(
        repository,
        failed_prefetch_actors=failed_prefetch_actors,
        prefetch_failures=prefetch_failures,
        failed_presentation_actors=failed_presentation_actors,
        block_generation=block_generation,
        block_prefetch_generation=block_prefetch_generation,
        complete_prefetch_on_cancel=complete_prefetch_on_cancel,
        prefetch_generation_release=prefetch_generation_release,
    )
    engine = _DayEngine(
        repository=repository,  # type: ignore[arg-type]
        action_engine=actions,  # type: ignore[arg-type]
        day_speech_pipeline_repository=pipeline,  # type: ignore[arg-type]
    )
    return engine, repository, pipeline, actions


def test_one_ahead_overlaps_generation_and_preserves_public_order_and_cutoff() -> None:
    engine, repository, pipeline, actions = _engine(_snapshot())

    assert (
        asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))
        is False
    )

    assert actions.foreground_actors == ["player_1"]
    assert actions.prefetched_actors == ["player_2", "player_3"]
    assert actions.precomputed_actors == ["player_2", "player_3"]
    assert actions.overlaps == [("player_1", "player_2"), ("player_2", "player_3")]
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_2",
        "player_3",
    ]
    assert [call["turn_index"] for call in pipeline.reserve_calls] == [2, 3]
    assert all(slot.state == "consumed" for slot in pipeline.slots.values())
    for spec, cutoff in zip(
        actions.generation_specs,
        repository.prefetch_cutoffs,
        strict=True,
    ):
        assert spec.audience == "player_private"
        assert spec.model_admission_mode == "idle_only"
        assert spec.defer_presentation is True and spec.isolated_failure is True
        assert spec.projection_at_seq == cutoff["cutoff"]
        assert spec.context is not None
        assert spec.context["public_cutoff_record_seq"] == cutoff["cutoff"]
        active = spec.context["public_history"][-1]
        assert active["event_type"] == "public_player_speech_presented"
        assert active["record_seq"] == cutoff["source_record_seq"]


def test_capacity_rejection_marks_slot_failed_and_falls_back_to_foreground() -> None:
    engine, repository, pipeline, actions = _engine(
        _snapshot(),
        failed_prefetch_actors={"player_2"},
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1", "player_2"]
    assert actions.prefetched_actors == ["player_2", "player_3"]
    assert actions.precomputed_actors == ["player_3"]
    assert pipeline.slots["v2_slot_1"].state == "failed"
    assert pipeline.slots["v2_slot_2"].state == "consumed"
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_2",
        "player_3",
    ]


@pytest.mark.parametrize(
    ("failure_code", "failure_category"),
    [
        ("model_output_budget_exhausted", "output_budget"),
        ("model_attempt_hard_timeout", "timeout"),
        ("model_empty_stream", "transport"),
    ],
)
def test_schema_v2_prefetch_failure_technically_skips_without_foreground_request(
    failure_code: str,
    failure_category: str,
) -> None:
    engine, repository, pipeline, actions = _engine(
        _snapshot(player_count=2, schema_version=2),
        prefetch_failures={"player_2": (failure_code, failure_category)},
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1"]
    assert actions.prefetched_actors == ["player_2"]
    assert actions.precomputed_actors == []
    assert len(actions.technical_skips) == 1
    assert actions.technical_skips[0]["player_id"] == "player_2"
    assert actions.technical_skips[0]["source_failure"].code == failure_code
    assert pipeline.slots["v2_slot_1"].state == "failed"
    assert [item["player_id"] for item in repository.public_commits] == ["player_1"]
    technical = next(
        item
        for item in repository.state.public_history
        if item["event_type"] == "action_skipped_technical"
    )
    assert technical["payload"]["actor_id"] == "player_2"
    assert technical["payload"]["reason"] == "technical_failure"
    assert "failure_code" not in technical["payload"]


def test_schema_v2_unfrozen_failure_preserves_foreground_fallback() -> None:
    engine, repository, pipeline, actions = _engine(
        _snapshot(player_count=2, schema_version=2),
        prefetch_failures={"player_2": ("model_decision_contract_invalid", "internal_invariant")},
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1", "player_2"]
    assert actions.technical_skips == []
    assert pipeline.slots["v2_slot_1"].state == "failed"
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_2",
    ]


def test_technical_skip_judge_cue_prefetches_the_immediate_next_turn() -> None:
    engine, repository, pipeline, actions = _engine(
        _snapshot(player_count=3),
        prefetch_failures={"player_2": ("model_output_budget_exhausted", "output_budget")},
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1"]
    assert actions.prefetched_actors == ["player_2", "player_3"]
    assert actions.precomputed_actors == ["player_3"]
    assert actions.overlaps == [("player_1", "player_2"), ("judge", "player_3")]
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_3",
    ]
    assert pipeline.slots["v2_slot_1"].state == "failed"
    assert pipeline.slots["v2_slot_2"].state == "consumed"
    assert pipeline.reserve_calls[1]["predecessor_turn_player_id"] == "player_2"
    third_context = actions.generation_specs[1].context
    assert third_context is not None
    technical_events = [
        item
        for item in third_context["public_history"]
        if item["event_type"] == "action_skipped_technical"
    ]
    assert len(technical_events) == 1
    assert technical_events[0]["payload"]["actor_id"] == "player_2"
    assert all(
        item.get("payload", {}).get("player_id") != "judge"
        for item in third_context["public_history"]
    )


def test_schema_v1_prefetch_failure_preserves_foreground_fallback() -> None:
    engine, repository, pipeline, actions = _engine(
        _snapshot(player_count=2, schema_version=1),
        prefetch_failures={"player_2": ("model_output_budget_exhausted", "output_budget")},
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1", "player_2"]
    assert actions.technical_skips == []
    assert pipeline.slots["v2_slot_1"].state == "failed"
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_2",
    ]


def test_schema_v2_post_close_grace_cancels_prefetch_and_technically_skips() -> None:
    engine, repository, pipeline, actions = _engine(
        _snapshot(player_count=2, schema_version=2, post_close_grace_ms=5),
        block_prefetch_generation=True,
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1"]
    assert actions.prefetched_actors == ["player_2"]
    assert actions.active_generation_count == 0
    assert pipeline.slots["v2_slot_1"].state == "failed"
    assert len(actions.technical_skips) == 1
    failure = actions.technical_skips[0]["source_failure"]
    assert failure.code == "day_speech_prefetch_post_close_deadline"
    assert failure.category == "timeout"
    assert [item["player_id"] for item in repository.public_commits] == ["player_1"]


def test_schema_v2_deadline_race_keeps_result_that_durably_became_ready() -> None:
    engine, repository, pipeline, actions = _engine(
        _snapshot(player_count=2, schema_version=2, post_close_grace_ms=5),
        block_prefetch_generation=True,
        complete_prefetch_on_cancel=True,
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1"]
    assert actions.precomputed_actors == ["player_2"]
    assert actions.technical_skips == []
    assert pipeline.slots["v2_slot_1"].state == "consumed"
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_2",
    ]


@pytest.mark.parametrize("schema_version", [2, 3])
def test_guarded_empty_stream_retry_policy_is_preserved(
    schema_version: int,
) -> None:
    engine, _repository, _pipeline, actions = _engine(
        _snapshot(player_count=2, schema_version=schema_version)
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert len(actions.generation_specs) == 1
    spec = actions.generation_specs[0]
    assert spec.pipeline_empty_stream_max_attempts == 2
    assert spec.pipeline_retry_mode == "empty_stream_once_while_predecessor_active"
    assert len(actions.model_retry_guards) == 1
    assert callable(actions.model_retry_guards[0])


def test_schema_v3_waits_for_same_inflight_prefetch_after_predecessor_closes() -> None:
    async def scenario() -> tuple[_MatchRepository, _PipelineRepository, _Actions]:
        release = asyncio.Event()
        engine, repository, pipeline, actions = _engine(
            _snapshot(player_count=2, schema_version=3),
            prefetch_generation_release=release,
        )
        task = asyncio.create_task(
            engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster())
        )
        await asyncio.wait_for(actions.generation_started.wait(), timeout=0.5)
        await asyncio.wait_for(actions.presentation_closed.wait(), timeout=0.5)
        await asyncio.sleep(0)

        assert task.done() is False
        assert actions.active_generation_count == 1
        assert actions.generation_action_ids == ["v2_generation_2_player_2"]
        assert actions.foreground_actors == ["player_1"]
        assert actions.prefetched_actors == ["player_2"]
        assert actions.technical_skips == []
        assert pipeline.slots["v2_slot_1"].state == "generating"

        release.set()
        await asyncio.wait_for(task, timeout=0.5)
        return repository, pipeline, actions

    repository, pipeline, actions = asyncio.run(scenario())

    assert actions.active_generation_count == 0
    assert actions.generation_action_ids == ["v2_generation_2_player_2"]
    assert actions.precomputed_actors == ["player_2"]
    assert actions.technical_skips == []
    assert pipeline.slots["v2_slot_1"].state == "consumed"
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_2",
    ]


@pytest.mark.parametrize(
    ("audio_mode", "pipeline_enabled"),
    [("text_only", True), ("tts", False)],
)
def test_text_and_legacy_games_remain_strictly_sequential(
    audio_mode: str,
    pipeline_enabled: bool,
) -> None:
    engine, repository, pipeline, actions = _engine(
        _snapshot(audio_mode=audio_mode, pipeline_enabled=pipeline_enabled)
    )

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1", "player_2", "player_3"]
    assert actions.prefetched_actors == []
    assert actions.precomputed_actors == []
    assert pipeline.reserve_calls == []
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_2",
        "player_3",
    ]


def test_canceling_current_turn_cancels_prefetch_without_orphan_task() -> None:
    async def scenario() -> tuple[_PipelineRepository, _Actions]:
        engine, _repository, pipeline, actions = _engine(
            _snapshot(player_count=2),
            block_generation=True,
        )
        task = asyncio.create_task(
            engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster())
        )
        await asyncio.wait_for(actions.generation_started.wait(), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        return pipeline, actions

    pipeline, actions = asyncio.run(scenario())
    assert actions.active_generation_count == 0
    assert list(pipeline.slots.values())[0].state == "canceled"


def test_pipeline_never_prefetches_across_speech_round_boundary() -> None:
    engine, repository, pipeline, actions = _engine(_snapshot(speech_rounds=2, player_count=2))

    asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert actions.foreground_actors == ["player_1", "player_1"]
    assert actions.prefetched_actors == ["player_2", "player_2"]
    assert [(call["speech_round"], call["turn_index"]) for call in pipeline.reserve_calls] == [
        (1, 2),
        (2, 2),
    ]
    assert [item["player_id"] for item in repository.public_commits] == [
        "player_1",
        "player_2",
        "player_1",
        "player_2",
    ]


def test_public_commit_failure_cancels_already_ready_successor() -> None:
    engine, repository, pipeline, _actions = _engine(_snapshot())
    repository.fail_next_public_commit = True

    with pytest.raises(RuntimeError, match="synthetic public commit failure"):
        asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert list(pipeline.slots.values())[0].state == "canceled"


def test_prefetched_presentation_failure_marks_current_and_cancels_successor() -> None:
    engine, _repository, pipeline, _actions = _engine(
        _snapshot(),
        failed_presentation_actors={"player_2"},
    )

    with pytest.raises(Exception, match="day_debate_speech_pipeline_presentation_failed"):
        asyncio.run(engine._run_public_discussion(game_id=GAME_ID, broadcaster=_Broadcaster()))

    assert pipeline.slots["v2_slot_1"].state == "failed"
    assert pipeline.slots["v2_slot_2"].state == "canceled"


def test_live_runtime_injects_real_day_speech_pipeline_repository(tmp_path: Path) -> None:
    runtime = V2LiveRuntime(
        session_factory=sessionmaker[Session](),
        model_client=object(),  # type: ignore[arg-type]
        tts_client=None,
        tts_capability_enabled=False,
        voice_root=tmp_path,
        sample_rate=24_000,
        judge_configuration_provider=lambda _game_id: None,  # type: ignore[arg-type,return-value]
    )

    assert runtime._day_engine._day_speech_pipeline is (runtime._day_speech_pipeline_repository)
