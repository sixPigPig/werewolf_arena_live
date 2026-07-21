from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from app.werewolf.action_quality import (
    DETERMINISTIC_HARD_RULE_CODES,
    action_quality_warnings,
)
from app.werewolf.actor_mind import (
    ActorMindReducer,
    ActorMindStimulusV1,
    ActorMindV1,
    EventCoordinateV1,
    public_affect_projection,
)
from app.werewolf.checkpoint import (
    ResumeCheckpointError,
    lifecycle_event_entry,
    merge_lifecycle_event_entries,
)
from app.werewolf.config import (
    DEFAULT_DEBATE_TURNS,
    DOCTOR,
    HUNTER,
    IDIOT,
    SEER,
    WITCH,
    WINNER_VILLAGERS,
    WINNER_WEREWOLVES,
    choose_player_names,
)
from app.werewolf.debate_realism import (
    SpeechQualityReportV1,
    assign_speech_mission,
    debate_guidance_for_turn,
    evaluate_speech_quality,
    speech_character_limit,
    speech_length_violation,
    speech_mission_from_dict,
    truncate_speech_to_complete_sentence,
)
from app.werewolf.execution_budget import (
    ActionExecutionBudgetV1,
    ModelCallOptions,
    ModelDeadlineExceeded,
)
from app.werewolf.execution_telemetry import (
    record_action_batch,
    record_action_execution,
    record_model_progress_event,
)
from app.werewolf.live import NullEventSink
from app.werewolf.liveness import (
    LivenessExperienceSnapshotV1,
    liveness_experience_from_storage,
)
from app.werewolf.judge_narration import (
    JudgeCueSpec,
    cue_spec,
    dawn_result_cue,
    exile_no_result_cue,
    exile_last_words_cue,
    exile_last_words_skipped_cue,
    exile_result_cue,
    exile_runoff_tied_cue,
    exile_tie_cues,
    hunter_start_cues,
    idiot_reveal_cues,
    self_explosion_cues,
    seat_asset_id,
    sheriff_badge_cues,
    sheriff_election_cues,
    sheriff_tie_cues,
)
from app.werewolf.lm import (
    LmLog,
    ModelActionCanceled,
    ModelProvider,
    VisibleTextCommitResult,
    generate_action_with_events,
    safe_attempt_outcomes,
)
from app.werewolf.streaming import action_visible_stream_field
from app.werewolf.models import (
    ActionLog,
    DeathEvent,
    DebateEntry,
    GameState,
    GameView,
    Player,
    PublicActionEligibility,
    PublicOutcomeEventV1,
    PublicOutcomeKind,
    RoundLog,
    RoundState,
    SelfExplosionDecisionContext,
    SheriffBadgeOutcome,
    SheriffBadgeResolution,
    SheriffElectionOutcome,
    SheriffElectionReason,
    SheriffElectionResolution,
    StageInterruption,
)
from app.werewolf.player_configs import (
    PlayerConfig,
    validate_unique_effective_player_names,
)
from app.werewolf.public_facts import (
    FactRetention,
    PublicFact,
    PublicFactOpportunityV1,
    compressed_public_fact_records,
    compressed_public_facts,
    fact_prompt_coverage,
    public_fact_from_dict,
)
from app.werewolf.public_outcomes import (
    append_public_outcome,
    latest_player_outcome_event,
    render_public_round_summary,
)
from app.werewolf.scene_packet import build_actor_scene_packet, build_public_speech_scene
from app.werewolf.speech_gate import (
    HardSpeechGateReportV1,
    IncrementalSpeechSegmenter,
    hard_speech_gate,
    split_complete_speech_segments,
    stable_segment_id,
    stable_segment_presentation_id,
    stable_speech_id,
)
from app.werewolf.quality_telemetry import record_speech_quality
from app.werewolf.liveness_telemetry import record_liveness_speech
from app.werewolf.speech_delivery import (
    AFFECT_DELIVERY_MAPPING_VERSION,
    DELIVERY_MAPPING_VERSION,
    compile_affect_delivery_v2,
    compile_context_texts,
    delivery_from_result,
)
from app.werewolf.turn_planning import (
    fallback_public_turn_plan,
    public_turn_plan_from_model,
)
from app.werewolf.rules import (
    ACTION_DEBATE,
    ACTION_EXILE_LAST_WORDS,
    ACTION_EXILE_PK_SPEECH,
    ACTION_EXILE_RUNOFF_VOTE,
    ACTION_SHERIFF_BADGE,
    ACTION_SHERIFF_PK_SPEECH,
    ACTION_SHERIFF_RUN,
    ACTION_SHERIFF_RUNOFF_VOTE,
    ACTION_SHERIFF_SPEECH,
    ACTION_SHERIFF_VOTE,
    ACTION_SHERIFF_WITHDRAW,
    ACTION_WEREWOLF_DISCUSS,
    ACTION_WEREWOLF_KILL_VOTE,
    ACTION_WEREWOLF_SELF_EXPLOSION,
    ACTION_INVESTIGATE,
    ACTION_HUNTER_SHOOT,
    ACTION_PROTECT,
    ACTION_REMOVE,
    ACTION_SPEECH_ORDER,
    ACTION_VOTE,
    ACTION_WITCH_POISON,
    ACTION_WITCH_SAVE,
    MODEL_GROUP_WEREWOLF,
    ROLE_CATEGORY_CIVILIAN,
    ROLE_CATEGORY_GOD,
    SPEECH_POLICY_SHERIFF_DIRECTED,
    TEAM_WEREWOLVES,
    WIN_CONDITION_SLAUGHTER_SIDE,
    RuleSet,
    role_category,
    rule_set_snapshot,
    rule_text_from_snapshot,
)
from app.werewolf.self_explosion_audit import (
    build_self_explosion_audit_payload,
    build_self_explosion_window_id,
)


WEREWOLF_DISCUSSION_TIMEOUT_SECONDS = 15.0
WEREWOLF_FINAL_VOTE_TIMEOUT_SECONDS = 15.0
WEREWOLF_TIEBREAK_TIMEOUT_SECONDS = 10.0
EventVisibility = Literal["public", "private"]
HARD_ACTION_QUALITY_CODES: frozenset[str] = DETERMINISTIC_HARD_RULE_CODES
BUFFERED_QUALITY_ACTIONS = frozenset(
    {
        ACTION_SHERIFF_SPEECH,
        ACTION_SHERIFF_PK_SPEECH,
        ACTION_EXILE_PK_SPEECH,
        ACTION_EXILE_LAST_WORDS,
        ACTION_DEBATE,
    }
)
PRIVATE_LENGTH_BUDGETED_ACTIONS = frozenset(
    {ACTION_WEREWOLF_DISCUSS, ACTION_WEREWOLF_KILL_VOTE}
)
SHERIFF_SPEECH_CONTEXT_MAX_CHARS = 180


def _compact_sheriff_speech_context(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= SHERIFF_SPEECH_CONTEXT_MAX_CHARS:
        return compact
    return compact[: SHERIFF_SPEECH_CONTEXT_MAX_CHARS - 1].rstrip() + "…"


class MaxRoundsExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class _LifecycleEventReceipt:
    id: int


class GameCheckpointManager(Protocol):
    def start_round(
        self,
        *,
        state: GameState,
        logs: list[RoundLog],
        round_number: int,
        active_players: list[str],
        rng_state: object,
    ) -> None:
        pass

    def record_success(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        raw_response: str,
        prompt: str | None = None,
        actor_minds: Mapping[str, ActorMindV1] | None = None,
        logical_action_id: str | None = None,
        speech_turn_receipt: Mapping[str, object] | None = None,
    ) -> None:
        pass

    def record_failure(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        error: str,
    ) -> None:
        pass

    def record_terminal_settlement(
        self,
        *,
        state: GameState,
        logs: list[RoundLog],
        active_players: list[str],
        terminal_settlement: Mapping[str, object],
    ) -> None:
        pass


@dataclass(frozen=True)
class PlayerActionRequest:
    player: Player
    action: str
    options: list[str]
    public_options: list[str]
    public_choice_to_internal: dict[str, str]
    result_key: str
    round_state: RoundState
    phase: str
    world_state: dict[str, object]
    event_visibility: EventVisibility
    fact_prompt_coverage: dict[str, object]
    action_id: str
    terminal_settlement_allowed: bool = False


@dataclass(frozen=True)
class PlayerActionResult:
    request: PlayerActionRequest
    value: object | None
    lm_log: LmLog
    execution_status: Literal[
        "completed", "timed_out", "fallback", "canceled", "failed"
    ] = "completed"
    duration_ms: int = 0
    budget_ms: int | None = None
    fallback_reason: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class PendingSelfExplosionBatch:
    round_number: int
    active_wolves: tuple[str, ...]
    requests: tuple[PlayerActionRequest, ...]
    futures: tuple[Future[PlayerActionResult], ...]
    started_at: float
    cursor: PublicStageCursor


@dataclass(frozen=True)
class PublicStageCursor:
    stage: str
    ordered_actors: tuple[str, ...] = ()
    completed_actors: tuple[str, ...] = ()
    current_actor: str | None = None
    timing: Literal["before_stage", "before_actor", "after_actor"] = "before_stage"

    @property
    def pending_actors(self) -> list[str]:
        completed = set(self.completed_actors)
        return [actor for actor in self.ordered_actors if actor not in completed]


@dataclass(frozen=True)
class ActivePublicActionContext:
    round_state: RoundState
    round_log: RoundLog
    active_players: list[str]
    cursor: PublicStageCursor
    actor: str
    action: str
    action_id: str


class _PublicActionInterruptedBySelfExplosion(ModelActionCanceled):
    pass


class _BufferedEventSink:
    _LIFECYCLE_EVENT_TYPES = frozenset(
        {
            "model_request_started",
            "model_attempt_completed",
            "model_request_failed",
            "model_retry_scheduled",
        }
    )

    def __init__(
        self,
        before_publish: Callable[[str], None] | None = None,
        lifecycle_destination: object | None = None,
    ) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self._before_publish = before_publish
        self._lifecycle_destination = lifecycle_destination

    def publish(self, event_type: str, **kwargs: object) -> object | None:
        if self._before_publish is not None:
            self._before_publish(event_type)
        if (
            self._lifecycle_destination is not None
            and event_type in self._LIFECYCLE_EVENT_TYPES
        ):
            publish = getattr(self._lifecycle_destination, "publish")
            publish(event_type, **kwargs)
            return
        self.events.append((event_type, kwargs))

    def flush_to(
        self,
        event_sink: object,
        *,
        accepted_visible_text: str | None = None,
    ) -> None:
        publish = getattr(event_sink, "publish")
        visible_text_published = False
        for event_type, kwargs in self.events:
            if event_type == "model_response_delta" and accepted_visible_text is not None:
                if visible_text_published or not accepted_visible_text:
                    continue
                payload = kwargs.get("payload")
                safe_payload = dict(payload) if isinstance(payload, dict) else {}
                safe_payload["delta"] = accepted_visible_text
                safe_payload["visible_text"] = accepted_visible_text
                publish(event_type, **{**kwargs, "payload": safe_payload})
                visible_text_published = True
                continue
            publish(event_type, **kwargs)

    def flush_lifecycle_to(self, event_sink: object) -> None:
        publish = getattr(event_sink, "publish")
        for event_type, kwargs in self.events:
            if event_type in self._LIFECYCLE_EVENT_TYPES:
                publish(event_type, **kwargs)


class _CommittedSpeechObserver:
    def __init__(
        self,
        *,
        character_limit: int,
        gate: Callable[[str], HardSpeechGateReportV1],
        commit: Callable[[int, str, str, bool], dict[str, object]],
    ) -> None:
        self.character_limit = character_limit
        self._gate = gate
        self._commit = commit
        self._segmenter = IncrementalSpeechSegmenter()
        self._request_id = ""
        self.segments: list[str] = []
        self.receipt_segments: list[dict[str, object]] = []
        self.rejected_count = 0
        self.codes: list[str] = []
        self.stopped = False
        self.length_truncated = False
        self.first_committed_at_ms: int | None = None
        self.hard_gate_duration_ms = 0

    @property
    def committed_text(self) -> str:
        return "".join(self.segments)

    def start_attempt(self, *, action_id: str, request_id: str) -> None:
        del action_id
        if self.segments:
            return
        self._request_id = request_id
        self._segmenter = IncrementalSpeechSegmenter()
        self.stopped = False

    def append(self, text: str) -> None:
        if self.stopped:
            return
        for segment in self._segmenter.append(text):
            if not self._accept(segment, final=False):
                break

    def finish(self, final_text: str) -> VisibleTextCommitResult:
        if not self.stopped:
            bounded_text = truncate_speech_to_complete_sentence(
                final_text,
                max_chars=self.character_limit,
                fallback="",
            )
            if bounded_text != final_text.strip():
                self.length_truncated = True
                if not bounded_text.startswith(self.committed_text):
                    self._reject(("invalid_public_speech",))
                    final_segments = []
                else:
                    remaining = bounded_text[len(self.committed_text) :].strip()
                    final_segments = split_complete_speech_segments(remaining)
            else:
                try:
                    final_segments = self._segmenter.finish(final_text)
                except ValueError:
                    self._reject(("invalid_public_speech",))
                    final_segments = []
            for index, segment in enumerate(final_segments):
                if not self._accept(
                    segment,
                    final=index == len(final_segments) - 1,
                ):
                    break
        if self.segments:
            return VisibleTextCommitResult(
                text=self.committed_text,
                status=(
                    "partial_hard_gate_stop"
                    if self.stopped
                    else "complete"
                ),
            )
        return VisibleTextCommitResult(
            text="",
            status="partial_hard_gate_stop",
            should_retry=True,
        )

    def fail(self, reason_code: str) -> VisibleTextCommitResult:
        if self.segments:
            return VisibleTextCommitResult(
                text=self.committed_text,
                status=(
                    "interrupted"
                    if reason_code == "canceled"
                    else "partial_provider_failure"
                ),
            )
        if reason_code == "hard_gate_rejected":
            self._reject((reason_code,))
        return VisibleTextCommitResult(
            text="",
            status="partial_provider_failure",
            should_retry=True,
        )

    def _accept(self, segment: str, *, final: bool) -> bool:
        if len(self.committed_text) + len(segment) > self.character_limit:
            self.length_truncated = True
            self.stopped = True
            return False
        gate_started_ns = time.perf_counter_ns()
        report = self._gate(self.committed_text + segment)
        self.hard_gate_duration_ms += max(
            0,
            round((time.perf_counter_ns() - gate_started_ns) / 1_000_000),
        )
        if not report.accepted:
            self._reject(report.codes)
            return False
        receipt = self._commit(
            len(self.segments),
            segment,
            self._request_id,
            final,
        )
        self.segments.append(segment)
        self.receipt_segments.append(copy.deepcopy(receipt))
        if self.first_committed_at_ms is None:
            self.first_committed_at_ms = round(time.time() * 1000)
        return True

    def _reject(self, codes: tuple[str, ...]) -> None:
        self.rejected_count += 1
        for code in codes:
            if code not in self.codes:
                self.codes.append(code)
        self.stopped = True


class _PrivateLifecycleEventSink:
    """Persist private model lifecycle without private prompts, deltas, or choices."""

    _ALLOWED_EVENT_TYPES = frozenset(
        {
            "model_request_started",
            "model_attempt_completed",
            "model_request_failed",
            "model_retry_scheduled",
            "late_result_discarded",
        }
    )
    _ALLOWED_PAYLOAD_KEYS = frozenset(
        {
            "action_id",
            "request_id",
            "model",
            "attempt",
            "attempt_result",
            "generation_stage",
            "reason_code",
            "discard_reason",
        }
    )

    def __init__(self, destination: object) -> None:
        self._destination = destination

    def publish(self, event_type: str, **kwargs: object) -> object | None:
        if event_type not in self._ALLOWED_EVENT_TYPES:
            return
        payload = kwargs.get("payload")
        safe_payload = {
            key: value
            for key, value in (payload.items() if isinstance(payload, dict) else ())
            if key in self._ALLOWED_PAYLOAD_KEYS
            and isinstance(value, (str, int, float, bool))
        }
        publish = getattr(self._destination, "publish")
        publish(event_type, **{**kwargs, "payload": safe_payload})


class _PublishGateSink:
    def __init__(
        self,
        destination: object,
        *,
        deadline_at_monotonic: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._destination = destination
        self._deadline_at_monotonic = deadline_at_monotonic
        self._monotonic = monotonic
        self._active = True
        self._lock = threading.Lock()
        self._active_attempts: dict[str, str] = {}
        self._closed_attempts: dict[str, str] = {}
        self._last_attempt: tuple[str, str] | None = None
        self._attempt_outcomes: list[dict[str, str]] = []
        self._late_discarded_requests: set[str] = set()

    def publish(self, event_type: str, **kwargs: object) -> object | None:
        with self._lock:
            deadline_expired = (
                self._deadline_at_monotonic is not None
                and self._monotonic() >= self._deadline_at_monotonic
            )
            if not self._active or deadline_expired:
                payload = kwargs.get("payload")
                if isinstance(payload, dict):
                    action_id = payload.get("action_id")
                    request_id = payload.get("request_id")
                    if (
                        isinstance(action_id, str)
                        and action_id
                        and isinstance(request_id, str)
                        and request_id
                    ):
                        self._last_attempt = (request_id, action_id)
                        self._closed_attempts[request_id] = action_id
                    if (
                        event_type in {
                            "model_attempt_completed",
                            "model_request_failed",
                        }
                        and isinstance(action_id, str)
                        and action_id
                        and isinstance(request_id, str)
                        and request_id
                        and request_id not in self._late_discarded_requests
                    ):
                        self._late_discarded_requests.add(request_id)
                        publish = getattr(self._destination, "publish")
                        publish(
                            "late_result_discarded",
                            **{
                                **kwargs,
                                "payload": {
                                    "action_id": action_id,
                                    "request_id": request_id,
                                    "discard_reason": "deadline_result_already_committed",
                                },
                            },
                        )
                return None
            payload = kwargs.get("payload")
            if isinstance(payload, dict):
                action_id = payload.get("action_id")
                request_id = payload.get("request_id")
                if (
                    event_type == "model_request_started"
                    and isinstance(action_id, str)
                    and action_id
                    and isinstance(request_id, str)
                    and request_id
                ):
                    self._active_attempts[request_id] = action_id
                    self._last_attempt = (request_id, action_id)
                elif event_type in {
                    "model_attempt_completed",
                    "model_request_failed",
                }:
                    attempt_result = payload.get("attempt_result")
                    if (
                        isinstance(action_id, str)
                        and action_id
                        and isinstance(request_id, str)
                        and request_id
                        and isinstance(attempt_result, str)
                    ):
                        self._attempt_outcomes = safe_attempt_outcomes(
                            [
                                *self._attempt_outcomes,
                                {
                                    "action_id": action_id,
                                    "request_id": request_id,
                                    "attempt_result": attempt_result,
                                },
                            ]
                        )
                        self._active_attempts.pop(request_id, None)
            publish = getattr(self._destination, "publish")
            return publish(event_type, **kwargs)

    def close(self) -> None:
        with self._lock:
            self._attempt_outcomes = safe_attempt_outcomes(
                [
                    *self._attempt_outcomes,
                    *(
                        {
                            "action_id": action_id,
                            "request_id": request_id,
                            "attempt_result": "timed_out",
                        }
                        for request_id, action_id in self._active_attempts.items()
                    ),
                ]
            )
            self._closed_attempts = dict(self._active_attempts)
            if not self._closed_attempts and self._last_attempt is not None:
                request_id, action_id = self._last_attempt
                self._closed_attempts[request_id] = action_id
            self._active_attempts.clear()
            self._active = False

    def publish_late_discard(self, request: PlayerActionRequest) -> None:
        with self._lock:
            pending_attempt = next(iter(self._closed_attempts.items()), None)
            if pending_attempt is None:
                return
            request_id, action_id = pending_attempt
            if request_id in self._late_discarded_requests:
                return
            self._late_discarded_requests.add(request_id)
            publish = getattr(self._destination, "publish")
            publish(
                "late_result_discarded",
                round_number=request.round_state.number,
                phase=request.phase,
                actor=request.player.name,
                action=request.action,
                payload={
                    "action_id": action_id,
                    "request_id": request_id,
                    "discard_reason": "deadline_result_already_committed",
                },
            )

    def attempt_outcomes(self) -> list[dict[str, str]]:
        with self._lock:
            return safe_attempt_outcomes(self._attempt_outcomes)

    def result_was_late(self) -> bool:
        with self._lock:
            return bool(self._late_discarded_requests)


class _OrderedBatchProvider:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        index: int,
        condition: threading.Condition,
        next_index: dict[str, int],
    ) -> None:
        self._provider = provider
        self._index = index
        self._condition = condition
        self._next_index = next_index
        self._started = False

    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> str:
        self._await_turn()
        return self._call_provider_method(
            self._provider.complete_json,
            model=model,
            prompt=prompt,
            temperature=temperature,
            call_options=call_options,
        )

    def __getattr__(self, name: str) -> object:
        if name != "stream_json":
            raise AttributeError(name)
        stream_json = getattr(self._provider, "stream_json", None)
        if not callable(stream_json):
            raise AttributeError(name)

        def ordered_stream_json(
            *,
            model: str,
            prompt: str,
            temperature: float,
            call_options: ModelCallOptions | None = None,
        ) -> object:
            self._await_turn()
            return self._call_provider_method(
                stream_json,
                model=model,
                prompt=prompt,
                temperature=temperature,
                call_options=call_options,
            )

        return ordered_stream_json

    def _await_turn(self) -> None:
        self.release_turn_if_not_started()

    def release_turn_if_not_started(self) -> None:
        with self._condition:
            if self._started:
                return
            self._condition.wait_for(lambda: self._next_index["value"] == self._index)
            self._started = True
            self._next_index["value"] += 1
            self._condition.notify_all()

    def _call_provider_method(
        self,
        method: Callable[..., object],
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None,
    ) -> object:
        try:
            return method(
                model=model,
                prompt=prompt,
                temperature=temperature,
                call_options=call_options,
            )
        except TypeError as exc:
            if "call_options" not in str(exc):
                raise
            return method(model=model, prompt=prompt, temperature=temperature)


NO_WITCH_SAVE = "不使用解药"
NO_WITCH_POISON = "不使用毒药"
NO_HUNTER_SHOT = "不发动技能"
SHERIFF_RUN = "上警"
SHERIFF_SKIP = "不上警"
SHERIFF_WITHDRAW = "退水"
SHERIFF_STAY = "不退水"
SPEECH_FROM_LEFT = "警左发言"
SPEECH_FROM_RIGHT = "警右发言"
SHERIFF_BADGE_DESTROY = "撕毁警徽"
WEREWOLF_SELF_EXPLODE = "自爆"
WEREWOLF_NO_SELF_EXPLODE = "不自爆"
SHERIFF_BADGE_LOST_DOUBLE_BOMB = "双爆吞警徽"
SHERIFF_BADGE_PENDING_FIRST_BOMB = "首爆中断警长竞选"
SHERIFF_SPEECH_CLOCKWISE = "顺时针"
SHERIFF_SPEECH_COUNTERCLOCKWISE = "逆时针"
SELF_EXPLOSION_HANDOFF_TIMEOUT_SECONDS = 0.005
SHERIFF_ELECTION_REASON_TEXT: dict[SheriffElectionReason, str] = {
    "single_candidate": "仅剩一名候选人",
    "first_vote_winner": "首轮投票产生唯一领先者",
    "runoff_vote_winner": "二轮投票产生唯一领先者",
    "no_candidates": "无人上警",
    "all_candidates_withdrew": "警上候选全部退水",
    "no_off_sheriff_voters": "警下无人可投票",
    "first_vote_empty": "警长投票无人得票",
    "runoff_tied": "警长二轮投票未产生唯一领先者",
    "first_pre_election_self_explosion": SHERIFF_BADGE_PENDING_FIRST_BOMB,
    "double_pre_election_self_explosion": SHERIFF_BADGE_LOST_DOUBLE_BOMB,
}
OPTIONAL_ACTION_FALLBACKS = {
    ACTION_WITCH_SAVE: NO_WITCH_SAVE,
    ACTION_WITCH_POISON: NO_WITCH_POISON,
    ACTION_HUNTER_SHOOT: NO_HUNTER_SHOT,
    ACTION_WEREWOLF_SELF_EXPLOSION: WEREWOLF_NO_SELF_EXPLODE,
    ACTION_SHERIFF_WITHDRAW: SHERIFF_STAY,
    ACTION_SHERIFF_BADGE: SHERIFF_BADGE_DESTROY,
    ACTION_SHERIFF_RUN: SHERIFF_SKIP,
}
OPTIONAL_NO_ACTIONS = frozenset({ACTION_INVESTIGATE, ACTION_PROTECT})
DETERMINISTIC_PUBLIC_FALLBACK_ACTIONS = frozenset(
    {
        ACTION_VOTE,
        ACTION_SHERIFF_VOTE,
        ACTION_SHERIFF_RUNOFF_VOTE,
        ACTION_EXILE_RUNOFF_VOTE,
        ACTION_SPEECH_ORDER,
    }
)
RULE_DEFAULT_FALLBACK_ACTIONS = frozenset(
    {ACTION_SHERIFF_BADGE, ACTION_SPEECH_ORDER}
)


def initialize_game_state(
    *,
    session_id: str,
    villager_model: str,
    werewolf_model: str,
    seed: int | None,
    rule_set: RuleSet,
    player_configs: list[PlayerConfig] | None = None,
) -> GameState:
    player_names = choose_player_names(seed, player_count=rule_set.player_count)
    validate_unique_effective_player_names(
        default_names=player_names,
        player_configs=player_configs,
    )
    configs_by_seat = {config.seat: config for config in player_configs or []}
    role_cards = [role_spec for role_spec in rule_set.roles for _ in range(role_spec.count)]
    role_rng = random.Random(f"{seed}:roles") if seed is not None else random.Random()
    role_rng.shuffle(role_cards)
    players: list[Player] = []
    for seat, (player_name, role_spec) in enumerate(
        zip(player_names, role_cards, strict=True),
        start=1,
    ):
        player_config = configs_by_seat.get(seat)
        model = werewolf_model if role_spec.model_group == MODEL_GROUP_WEREWOLF else villager_model
        if player_config is not None:
            player_name = player_config.name or player_name
            model = player_config.model or model
        player = Player(
            player_name,
            role_spec.role,
            model,
            personality_id=player_config.personality_id if player_config else "balanced",
            personality=player_config.personality if player_config else "",
            appearance_id=player_config.appearance_id if player_config else "default",
            avatar_prompt=player_config.avatar_prompt if player_config else "",
            avatar_image_url=player_config.avatar_image_url if player_config else "",
            profile_id=player_config.profile_id if player_config else None,
            tts_speaker=player_config.tts_speaker if player_config else "",
            tts_dialect=player_config.tts_dialect if player_config else "",
            base_delivery_mood=(
                player_config.base_delivery_mood if player_config else "neutral"
            ),
            base_delivery_intensity=(
                player_config.base_delivery_intensity if player_config else "medium"
            ),
            base_delivery_pace=(
                player_config.base_delivery_pace if player_config else "natural"
            ),
            base_delivery_instruction=(
                player_config.base_delivery_instruction if player_config else ""
            ),
            voice_enabled=player_config.voice_enabled if player_config else True,
            voice_config_version=(
                player_config.voice_config_version if player_config else 1
            ),
            tags=list(player_config.tags) if player_config else [],
        )
        if role_spec.role == WITCH:
            player.witch_antidote_available = True
            player.witch_poison_available = True
        elif role_spec.role == HUNTER:
            player.hunter_can_shoot = True
        players.append(player)

    werewolves = [
        player for player in players if _role_team(rule_set, player.role) == TEAM_WEREWOLVES
    ]
    current_players = [player.name for player in players]

    for player in players:
        wolf_teammates: list[str] = []
        if _role_team(rule_set, player.role) == TEAM_WEREWOLVES and len(werewolves) > 1:
            wolf_teammates = [wolf.name for wolf in werewolves if wolf.name != player.name]
        other_wolf = wolf_teammates[0] if wolf_teammates else None
        player.gamestate = GameView(
            round_number=1,
            current_players=current_players.copy(),
            other_wolf=other_wolf,
            wolf_teammates=wolf_teammates,
        )

    return GameState(session_id=session_id, players=players, rule_set=rule_set_snapshot(rule_set))


def _role_team(rule_set: RuleSet, role: str) -> str:
    return next(role_spec.team for role_spec in rule_set.roles if role_spec.role == role)


class GameEngine:
    def __init__(
        self,
        *,
        state: GameState,
        provider: ModelProvider,
        max_rounds: int,
        rule_set: RuleSet,
        debate_turns: int = DEFAULT_DEBATE_TURNS,
        event_sink: object | None = None,
        rng: random.Random | None = None,
        starting_active_players: list[str] | None = None,
        checkpoint_manager: GameCheckpointManager | None = None,
        speech_quality_retry_enabled: bool = False,
        action_budgets_enabled: bool = False,
        action_execution_budget: ActionExecutionBudgetV1 | None = None,
        fallback_seed: int | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        execution_mode: Literal["new", "resume"] = "new",
        resume_from_round: int | None = None,
        liveness_experience_snapshot: dict[str, object] | None = None,
    ) -> None:
        self.state = state
        self.provider = provider
        self.max_rounds = max_rounds
        self.rule_set = rule_set
        self.debate_turns = debate_turns
        self.event_sink = event_sink or NullEventSink()
        self.rng = rng or random.Random()
        self.starting_active_players = starting_active_players
        self.checkpoint_manager = checkpoint_manager
        self.speech_quality_retry_enabled = speech_quality_retry_enabled
        self.action_budgets_enabled = action_budgets_enabled
        self.action_execution_budget = action_execution_budget or ActionExecutionBudgetV1()
        self.fallback_seed = fallback_seed
        self.monotonic = monotonic
        self.execution_mode = execution_mode
        self.resume_from_round = resume_from_round
        self.liveness_experience: LivenessExperienceSnapshotV1 = (
            liveness_experience_from_storage(liveness_experience_snapshot)
        )
        self._actor_minds: dict[str, ActorMindV1] = {
            player.name: ActorMindV1(actor=player.name)
            for player in state.players
            if self.liveness_experience.feature_modes.actor_mind != "off"
        }
        if self.checkpoint_manager is not None and self._actor_minds:
            loader = getattr(self.checkpoint_manager, "actor_minds", None)
            if callable(loader):
                restored_minds = loader()
                if isinstance(restored_minds, dict):
                    for actor, mind in restored_minds.items():
                        if actor in self._actor_minds and isinstance(mind, ActorMindV1):
                            self._actor_minds[actor] = mind
        self.logs: list[RoundLog] = []
        self._self_explosion_executor: ThreadPoolExecutor | None = None
        self._pending_self_explosion: PendingSelfExplosionBatch | None = None
        self._active_public_action: ActivePublicActionContext | None = None
        self._active_committed_speech: dict[str, dict[str, object]] = {}
        self._self_explosion_locked = False
        self.terminal_keep_from_event_id: int | None = None
        self._terminal_primary_event: object | None = None
        self._terminal_settlement: dict[str, object] | None = None
        self._prepared_terminal_settlement: Mapping[str, object] | None = None
        self._prepared_terminal_logs: list[RoundLog] | None = None
        self._has_unsettled_deferred_night_deaths = False
        self._logical_action_occurrences: Counter[tuple[int, str, str, str]] = Counter()
        self._provider_attempt_occurrences: Counter[str] = Counter()
        self._phase_occurrences: Counter[tuple[int, str]] = Counter()
        self._active_phase_instances: dict[tuple[int, str], tuple[str, int | None]] = {}
        self._known_lifecycle_events: dict[
            tuple[str, str], dict[str, object]
        ] = {}
        self._suppressed_phase_replays: set[tuple[int, str]] = set()
        self._reusable_phase_occurrences: dict[tuple[int, str], int] = {}
        self._max_persisted_phase_occurrences: dict[tuple[int, str], int] = {}
        self._initialized_phase_occurrences: set[tuple[int, str]] = set()
        self._restore_lifecycle_contract()

    def run(self) -> list[RoundLog]:
        logs: list[RoundLog] = []
        self.logs = logs
        active_players = (
            self.starting_active_players.copy()
            if self.starting_active_players is not None
            else [player.name for player in self.state.players]
        )
        if self._prepared_terminal_settlement is None:
            self._refresh_winner(active_players)
        start_event_type = "game_resumed" if self.execution_mode == "resume" else "game_started"
        start_payload: dict[str, object] = {
            "players": [player.to_dict() for player in self.state.players],
            "active_players": active_players.copy(),
        }
        if self.execution_mode == "resume":
            start_payload["resume_from_round"] = self.resume_from_round
            if self._prepared_terminal_settlement is not None:
                start_payload["terminal_recovery"] = True
        start_event = self._publish(start_event_type, payload=start_payload)
        if self.state.winner and self._prepared_terminal_settlement is None:
            self._remember_terminal_keep_event(start_event)

        try:
            if self._prepared_terminal_settlement is not None:
                self.recover_terminal_settlement(
                    self._prepared_terminal_settlement,
                    logs=self._prepared_terminal_logs or [],
                    active_players=active_players,
                )
                if self.state.winner:
                    recovered_state_event = self._publish_recovered_terminal_state(
                        active_players
                    )
                    self._remember_terminal_keep_event(recovered_state_event)
                    self._close_recovered_terminal_lifecycle(active_players)
                    return logs
            while not self.state.winner:
                if len(self.state.rounds) >= self.max_rounds:
                    raise MaxRoundsExceeded("Maximum rounds exceeded before a winner was found.")

                round_number = len(self.state.rounds) + 1
                self._sync_game_views(active_players, round_number)
                round_state = RoundState(number=round_number, players=active_players.copy())
                round_log = RoundLog(number=round_number)
                self._terminal_settlement = None
                self._terminal_primary_event = None
                self._checkpoint_round_start(
                    round_number=round_number,
                    active_players=active_players,
                    logs=logs,
                )
                self.state.rounds.append(round_state)
                logs.append(round_log)
                self._publish(
                    "round_started",
                    round_number=round_number,
                    payload={"active_players": active_players.copy()},
                )

                pending_deaths = self._run_night_phase(round_state, round_log, active_players)
                if self.state.winner:
                    round_state.success = True
                    break

                self._run_day_phase(round_state, round_log, active_players, pending_deaths)
                self._refresh_winner(active_players)
                round_state.success = True

            return logs
        except BaseException:
            try:
                self._cancel_active_phases(completion_reason="forced_failure")
            except Exception:
                # Preserve the original game failure. A failed lifecycle publish
                # remains retryable because _complete_phase keeps its active entry.
                pass
            raise
        finally:
            self._shutdown_self_explosion_worker()

    def _run_night_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> list[DeathEvent] | None:
        self._start_phase(
            round_number=round_state.number,
            phase="night",
            payload={"active_players": active_players.copy()},
        )
        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        non_wolves = [
            name for name in active_players if not self._is_werewolf(players_by_name[name])
        ]

        if ACTION_REMOVE in self.rule_set.night_actions:
            round_state.attacked = self._run_werewolf_kill_consensus(
                round_state,
                round_log,
                active_players,
                active_wolves,
                non_wolves,
            )

        if ACTION_PROTECT in self.rule_set.night_actions and self._is_role_active(
            DOCTOR, active_players
        ):
            doctor = players_by_name[self._active_player_for_role(DOCTOR, active_players)]
            self._publish_night_judge_cue(
                round_state,
                "guard_wake",
                "守卫请睁眼。",
            )
            protected, round_log.protect = self._player_action(
                player=doctor,
                action=ACTION_PROTECT,
                options=active_players,
                result_key=ACTION_PROTECT,
                round_state=round_state,
                phase="night",
            )
            round_state.protected = protected
            self._publish_night_judge_cue(
                round_state,
                "guard_sleep",
                "守卫请闭眼。",
            )

        if ACTION_INVESTIGATE in self.rule_set.night_actions and self._is_role_active(
            SEER, active_players
        ):
            seer = players_by_name[self._active_player_for_role(SEER, active_players)]
            investigate_options = [
                name
                for name in active_players
                if name != seer.name and name not in seer.known_roles
            ]
            if investigate_options:
                self._publish_night_judge_cue(
                    round_state,
                    "seer_wake",
                    "预言家请睁眼。",
                )
                investigated, round_log.investigate = self._player_action(
                    player=seer,
                    action=ACTION_INVESTIGATE,
                    options=investigate_options,
                    result_key=ACTION_INVESTIGATE,
                    round_state=round_state,
                    phase="night",
                )
                round_state.investigated = investigated
                if investigated:
                    alignment = self._investigation_alignment(players_by_name[investigated].role)
                    seer.known_roles[investigated] = alignment
                    seer.add_observation(
                        f"第{round_state.number}轮：我查验了{investigated}，阵营是{alignment}。"
                    )
                self._publish_night_judge_cue(
                    round_state,
                    "seer_sleep",
                    "预言家请闭眼。",
                )

        self._run_witch_phase(round_state, round_log, active_players)
        pending_deaths = self._pending_night_deaths(round_state, active_players)
        should_defer_deaths = self._should_run_sheriff_election(round_state) and not (
            pending_deaths
            and self._deferred_deaths_are_inevitably_terminal(
                pending_deaths,
                active_players,
            )
        )
        self._complete_phase(
            round_number=round_state.number,
            phase="night",
            completion_status="completed",
            completion_reason="night_actions_resolved",
            next_phase=("sheriff_election" if should_defer_deaths else "dawn_reveal"),
            terminal=False,
        )
        if should_defer_deaths:
            return pending_deaths

        self._finish_deferred_night_deaths_if_needed(
            pending_deaths,
            round_state,
            round_log,
            active_players,
        )

        return None

    def _run_werewolf_kill_consensus(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        active_wolves: list[str],
        non_wolves: list[str],
    ) -> str | None:
        if not active_wolves or not non_wolves:
            return None

        self._publish_night_judge_cue(
            round_state,
            "werewolves_wake",
            "狼人请睁眼，请互相确认队友。",
        )
        self._publish(
            "action_requested",
            round_number=round_state.number,
            phase="night",
            actor=None,
            action=ACTION_REMOVE,
            payload={},
        )
        players_by_name = self.state.player_by_name()
        candidates = non_wolves.copy()
        speaking_order = self._rotating_werewolf_order(
            active_wolves,
            round_number=round_state.number,
            purpose="discussion",
        )
        discussion_requests = [
            self._build_player_action_request(
                player=players_by_name[wolf_name],
                action=ACTION_WEREWOLF_DISCUSS,
                options=candidates,
                result_key="target",
                round_state=round_state,
                phase="night",
                extra_world_state={"werewolf_discussion_stage": "proposal"},
            )
            for wolf_name in speaking_order
        ]
        discussion_results = self._run_werewolf_vote_round(
            discussion_requests,
            deadline_at_monotonic=(
                self.monotonic() + WEREWOLF_DISCUSSION_TIMEOUT_SECONDS
            ),
        )
        proposals: dict[str, str] = {}
        latest_logs: dict[str, ActionLog] = {}
        discussion_lines: list[str] = []
        for wolf_name, target, action_log in discussion_results:
            latest_logs[wolf_name] = action_log
            round_log.werewolf_discussion.append(action_log)
            if target is None:
                self._publish_werewolf_private_abstention(
                    round_state=round_state,
                    actor=wolf_name,
                    action=ACTION_WEREWOLF_DISCUSS,
                    decision_stage="proposal",
                    action_log=action_log,
                )
                continue
            message = self._werewolf_action_message(action_log)
            proposals[wolf_name] = target
            round_state.werewolf_discussion.append(
                {
                    "round": 1,
                    "stage": "proposal",
                    "speaker": wolf_name,
                    "target": target,
                    "message": message,
                }
            )
            discussion_lines.append(
                f"{wolf_name}：建议袭击{target}。{message}".strip()
            )
            self._publish_werewolf_private_action(
                round_state=round_state,
                actor=wolf_name,
                action=ACTION_WEREWOLF_DISCUSS,
                target=target,
                message=message,
                decision_stage="proposal",
                action_log=action_log,
            )

        complete_unanimous_proposal = (
            len(proposals) == len(active_wolves)
            and len(set(proposals.values())) == 1
        )
        if complete_unanimous_proposal:
            votes = proposals.copy()
            decision_stage = "discussion_consensus"
        else:
            vote_requests = [
                self._build_player_action_request(
                    player=players_by_name[wolf_name],
                    action=ACTION_WEREWOLF_KILL_VOTE,
                    options=candidates,
                    result_key="target",
                    round_state=round_state,
                    phase="night",
                    extra_world_state={
                        "werewolf_discussion": discussion_lines,
                        "werewolf_kill_vote_stage": "final",
                    },
                )
                for wolf_name in speaking_order
            ]
            vote_results = self._run_werewolf_vote_round(
                vote_requests,
                deadline_at_monotonic=(
                    self.monotonic() + WEREWOLF_FINAL_VOTE_TIMEOUT_SECONDS
                ),
            )
            votes: dict[str, str] = {}
            vote_logs = []
            for wolf_name, target, action_log in vote_results:
                latest_logs[wolf_name] = action_log
                vote_logs.append(action_log)
                if target is None:
                    self._publish_werewolf_private_abstention(
                        round_state=round_state,
                        actor=wolf_name,
                        action=ACTION_WEREWOLF_KILL_VOTE,
                        decision_stage="final",
                        action_log=action_log,
                    )
                    continue
                message = self._werewolf_action_message(action_log)
                votes[wolf_name] = target
                self._publish_werewolf_private_action(
                    round_state=round_state,
                    actor=wolf_name,
                    action=ACTION_WEREWOLF_KILL_VOTE,
                    target=target,
                    message=message,
                    decision_stage="final",
                    action_log=action_log,
                )
            round_log.werewolf_votes.append(vote_logs)
            decision_stage = "final_vote"

        vote_record = self._record_werewolf_vote_round(
            1,
            candidates,
            votes,
            expected_voters=len(active_wolves),
        )
        vote_record["stage"] = decision_stage
        round_state.werewolf_vote_rounds.append(vote_record)

        leaders = self._werewolf_highest_vote_targets(votes)
        resolution_log: ActionLog | None = None
        if len(leaders) == 1:
            final_target = leaders[0]
        elif leaders:
            final_target, tiebreak_log, tiebreak_source = self._run_werewolf_tiebreak(
                round_state=round_state,
                active_wolves=active_wolves,
                candidates=leaders,
                discussion_lines=discussion_lines,
                votes=votes,
            )
            if tiebreak_log is not None:
                round_log.werewolf_votes.append([tiebreak_log])
                latest_logs[tiebreak_log.actor] = tiebreak_log
                resolution_log = tiebreak_log
            vote_record["tiebreak"] = {
                "triggered": True,
                "actor": self._werewolf_tiebreaker(active_wolves, round_state.number),
                "candidates": leaders.copy(),
                "choice": final_target,
                "source": tiebreak_source,
            }
        else:
            final_target = None

        if final_target is None:
            final_target = self._deterministic_werewolf_vote_choice(
                round_state=round_state,
                wolf_name="collective",
                candidates=candidates,
            )
            resolution_log = ActionLog(
                actor="system",
                action=ACTION_REMOVE,
                options=candidates.copy(),
                choice=final_target,
                lm_log=LmLog(
                    prompt="",
                    raw_response="",
                    result={"target": final_target},
                    action_id=self._next_logical_action_id(
                        round_number=round_state.number,
                        phase="night",
                        actor="system",
                        action=ACTION_REMOVE,
                    ),
                ),
                fallback_choice=final_target,
                fallback_reason="collective_no_result",
                reason_code="collective_no_result",
                effective_origin="system_fallback",
                execution_status="fallback",
            )
            round_log.werewolf_votes.append([resolution_log])
            vote_record["fallback"] = {
                "source": "system_fallback",
                "reason_code": "collective_no_result",
            }

        vote_record["result"] = final_target
        round_log.eliminate = resolution_log or next(
            (
                latest_logs[wolf_name]
                for wolf_name in reversed(speaking_order)
                if votes.get(wolf_name) == final_target and wolf_name in latest_logs
            ),
            round_log.werewolf_discussion[0] if round_log.werewolf_discussion else None,
        )
        self._publish_final_werewolf_target(
            round_state=round_state,
            target=final_target,
            vote_round=1,
            action_origin=(
                "system_fallback"
                if resolution_log is not None
                and resolution_log.effective_origin == "system_fallback"
                else "model"
            ),
            public_reason_code=(
                resolution_log.reason_code
                if resolution_log is not None
                and resolution_log.effective_origin == "system_fallback"
                else None
            ),
        )
        return final_target

    def _run_werewolf_vote_round(
        self,
        requests: list[PlayerActionRequest],
        *,
        deadline_at_monotonic: float,
    ) -> list[tuple[str, str | None, ActionLog]]:
        if not requests:
            return []

        condition = threading.Condition()
        next_index = {"value": 0}
        batch_started_at = self.monotonic()
        gates = [
            _PublishGateSink(
                _PrivateLifecycleEventSink(self.event_sink),
                deadline_at_monotonic=deadline_at_monotonic,
                monotonic=self.monotonic,
            )
            for _request in requests
        ]
        executor = ThreadPoolExecutor(max_workers=len(requests))
        futures = {
            executor.submit(
                self._execute_player_action_request,
                request,
                _OrderedBatchProvider(
                    provider=self.provider,
                    index=index,
                    condition=condition,
                    next_index=next_index,
                ),
                gates[index],
                deadline_at_monotonic=deadline_at_monotonic,
                timeout_fallback=False,
                private_lifecycle_events=True,
            ): index
            for index, request in enumerate(requests)
        }
        wait_seconds = max(0.0, deadline_at_monotonic - self.monotonic())
        done, pending = wait(futures, timeout=wait_seconds)
        results: list[PlayerActionResult | None] = [None] * len(requests)
        failures: dict[int, tuple[str, list[dict[str, str]]]] = {}
        for future in done:
            index = futures[future]
            try:
                candidate_result = future.result()
                if gates[index].result_was_late():
                    gates[index].close()
                    failures[index] = (
                        "batch_deadline",
                        gates[index].attempt_outcomes(),
                    )
                else:
                    results[index] = candidate_result
            except Exception as exc:
                if gates[index].result_was_late():
                    gates[index].close()
                    failures[index] = (
                        "batch_deadline",
                        gates[index].attempt_outcomes(),
                    )
                    continue
                outcomes = safe_attempt_outcomes(
                    getattr(exc, "attempt_outcomes", gates[index].attempt_outcomes())
                )
                reason_code = (
                    "timeout"
                    if isinstance(exc, ModelDeadlineExceeded)
                    or (outcomes and outcomes[-1]["attempt_result"] == "timed_out")
                    else "provider_failure"
                )
                failures[index] = (reason_code, outcomes)
        for future in pending:
            index = futures[future]
            gates[index].close()
            canceled = future.cancel()
            request = requests[index]
            if not canceled:
                future.add_done_callback(
                    lambda _future, gate=gates[index], late_request=request: (
                        gate.publish_late_discard(late_request)
                    )
                )
            failures[index] = ("batch_deadline", gates[index].attempt_outcomes())
        executor.shutdown(wait=not pending, cancel_futures=bool(pending))

        completed: list[tuple[str, str | None, ActionLog]] = []
        for index, request in enumerate(requests):
            if index in failures:
                reason_code, outcomes = failures[index]
                completed.append(
                    (
                        request.player.name,
                        None,
                        self._failed_werewolf_action_log(
                            request,
                            reason_code=reason_code,
                            attempt_outcomes=outcomes,
                            started_at=batch_started_at,
                        ),
                    )
                )
                continue
            result = results[index]
            if result is None:
                completed.append(
                    (
                        request.player.name,
                        None,
                        self._failed_werewolf_action_log(
                            request,
                            reason_code="missing_result",
                            attempt_outcomes=gates[index].attempt_outcomes(),
                            started_at=batch_started_at,
                        ),
                    )
                )
                continue
            try:
                target, action_log = self._finalize_player_action_result(result)
            except Exception:
                completed.append(
                    (
                        request.player.name,
                        None,
                        self._failed_werewolf_action_log(
                            request,
                            reason_code="invalid_exhausted",
                            attempt_outcomes=result.lm_log.attempt_outcomes,
                            started_at=batch_started_at,
                        ),
                    )
                )
                continue
            if isinstance(target, str) and target in request.options:
                completed.append((request.player.name, target, action_log))
            else:
                action_log.choice = None
                action_log.execution_status = "failed"
                action_log.effective_origin = "none"
                action_log.reason_code = action_log.reason_code or "invalid_exhausted"
                action_log.fallback_choice = None
                action_log.fallback_reason = None
                completed.append((request.player.name, None, action_log))
        return completed

    def _failed_werewolf_action_log(
        self,
        request: PlayerActionRequest,
        *,
        reason_code: str,
        attempt_outcomes: object,
        started_at: float,
    ) -> ActionLog:
        safe_outcomes = safe_attempt_outcomes(attempt_outcomes)
        action_log = ActionLog(
            actor=request.player.name,
            action=request.action,
            options=request.options.copy(),
            choice=None,
            lm_log=LmLog(
                prompt="",
                raw_response="",
                result={},
                action_id=request.action_id,
                request_id=(safe_outcomes[-1]["request_id"] if safe_outcomes else None),
                attempt_outcomes=safe_outcomes,
            ),
            reason_code=reason_code,
            effective_origin="none",
            attempt_count=len(safe_outcomes),
            execution_status="failed",
            duration_ms=max(0, round((self.monotonic() - started_at) * 1000)),
            budget_ms=max(0, round((self.monotonic() - started_at) * 1000)),
            fact_prompt_coverage=copy.deepcopy(request.fact_prompt_coverage),
            voice_config_version=request.player.voice_config_version,
        )
        if self.action_budgets_enabled:
            record_action_execution(
                action_kind=self.action_execution_budget.for_action(request.action).kind,
                model=request.player.model,
                result="failed",
                duration_ms=action_log.duration_ms,
                first_token_ms=None,
                fallback_reason=(
                    "batch_deadline_empty_private_text"
                    if reason_code == "batch_deadline"
                    else "timeout_empty_private_text"
                    if reason_code == "timeout"
                    else None
                ),
                action_id=request.action_id,
            )
        return action_log

    def _rotating_werewolf_order(
        self,
        active_wolves: list[str],
        *,
        round_number: int,
        purpose: str,
    ) -> list[str]:
        original_wolves = [
            player.name for player in self.state.players if self._is_werewolf(player)
        ]
        if not original_wolves:
            return []
        digest = hashlib.sha256(
            f"{self.fallback_seed}:{purpose}".encode()
        ).hexdigest()
        start = (int(digest[:8], 16) + max(0, round_number - 1)) % len(
            original_wolves
        )
        active = set(active_wolves)
        return [
            name
            for offset in range(len(original_wolves))
            if (name := original_wolves[(start + offset) % len(original_wolves)]) in active
        ]

    def _werewolf_tiebreaker(
        self,
        active_wolves: list[str],
        round_number: int,
    ) -> str:
        order = self._rotating_werewolf_order(
            active_wolves,
            round_number=round_number,
            purpose="tiebreak",
        )
        if not order:
            raise RuntimeError("Cannot assign werewolf tiebreak without an active werewolf")
        return order[0]

    def _run_werewolf_tiebreak(
        self,
        *,
        round_state: RoundState,
        active_wolves: list[str],
        candidates: list[str],
        discussion_lines: list[str],
        votes: dict[str, str],
    ) -> tuple[str, ActionLog | None, str]:
        tiebreaker = self._werewolf_tiebreaker(active_wolves, round_state.number)
        player_label = self._public_player_reference(tiebreaker)
        candidate_labels = [self._public_player_reference(name) for name in candidates]
        self._publish_werewolf_tiebreak_cue(
            round_state=round_state,
            cue_id="werewolf_tiebreak_start",
            visible_text=(
                "狼队刀口出现平票。"
                f"本夜由{player_label}行使归票权，请从"
                f"{'、'.join(candidate_labels)}中确认最终刀口。"
            ),
            player=player_label,
            candidates=candidate_labels,
        )

        vote_context = "；".join(
            f"{self._public_player_reference(actor)}投"
            f"{self._public_player_reference(target)}"
            for actor, target in votes.items()
        )
        request = self._build_player_action_request(
            player=self.state.player_by_name()[tiebreaker],
            action=ACTION_WEREWOLF_KILL_VOTE,
            options=candidates,
            result_key="target",
            round_state=round_state,
            phase="night",
            extra_world_state={
                "werewolf_discussion": discussion_lines,
                "werewolf_final_vote_context": vote_context,
                "werewolf_kill_vote_stage": "tiebreak",
            },
        )
        results = self._run_werewolf_vote_round(
            [request],
            deadline_at_monotonic=(
                self.monotonic() + WEREWOLF_TIEBREAK_TIMEOUT_SECONDS
            ),
        )
        if results and results[0][1] is not None:
            _actor, target, action_log = results[0]
            assert target is not None
            source = "model"
            message = self._werewolf_action_message(action_log)
            self._publish_werewolf_private_action(
                round_state=round_state,
                actor=tiebreaker,
                action=ACTION_WEREWOLF_KILL_VOTE,
                target=target,
                message=message,
                decision_stage="tiebreak",
                action_log=action_log,
            )
        else:
            target = self._deterministic_werewolf_tiebreak_choice(
                round_state=round_state,
                tiebreaker=tiebreaker,
                candidates=candidates,
            )
            source = "system_fallback"
            failed_log = results[0][2] if results else None
            fallback_reason = (
                "tiebreak_timeout_seeded_choice"
                if failed_log is not None
                and failed_log.reason_code in {"timeout", "batch_deadline"}
                else "tiebreak_missing_seeded_choice"
            )
            action_log = ActionLog(
                actor=tiebreaker,
                action=ACTION_WEREWOLF_KILL_VOTE,
                options=candidates.copy(),
                choice=target,
                lm_log=LmLog(
                    prompt="",
                    raw_response="",
                    result={"target": target, "message": ""},
                    action_id=(
                        failed_log.lm_log.action_id
                        if failed_log is not None
                        else request.action_id
                    ),
                    request_id=(
                        failed_log.lm_log.request_id
                        if failed_log is not None
                        else None
                    ),
                    attempt_outcomes=(
                        failed_log.lm_log.attempt_outcomes.copy()
                        if failed_log is not None
                        else []
                    ),
                ),
                fallback_choice=target,
                fallback_reason=fallback_reason,
                reason_code=(
                    failed_log.reason_code
                    if failed_log is not None
                    else "system_fallback"
                ),
                effective_origin="system_fallback",
                execution_status="fallback",
                duration_ms=(failed_log.duration_ms if failed_log is not None else 0),
                budget_ms=(failed_log.budget_ms if failed_log is not None else None),
                fact_prompt_coverage=(
                    copy.deepcopy(failed_log.fact_prompt_coverage)
                    if failed_log is not None
                    else copy.deepcopy(request.fact_prompt_coverage)
                ),
                voice_config_version=(
                    failed_log.voice_config_version
                    if failed_log is not None
                    else request.player.voice_config_version
                ),
            )
            self._publish_werewolf_private_action(
                round_state=round_state,
                actor=tiebreaker,
                action=ACTION_WEREWOLF_KILL_VOTE,
                target=target,
                message="",
                decision_stage="tiebreak",
                fallback_reason=fallback_reason,
                action_origin="system_fallback",
                public_reason_code=action_log.reason_code,
                action_log=action_log,
            )

        target_label = self._public_player_reference(target)
        self._publish_werewolf_tiebreak_cue(
            round_state=round_state,
            cue_id="werewolf_tiebreak_result",
            visible_text=f"{player_label}最终归票{target_label}，狼人请确认刀口。",
            player=player_label,
            candidates=candidate_labels,
            target=target_label,
        )
        return target, action_log, source

    def _deterministic_werewolf_tiebreak_choice(
        self,
        *,
        round_state: RoundState,
        tiebreaker: str,
        candidates: list[str],
    ) -> str:
        material = (
            f"{self.fallback_seed}:{round_state.number}:{tiebreaker}:werewolf_tiebreak"
        )
        return min(
            candidates,
            key=lambda candidate: hashlib.sha256(
                f"{material}:{candidate}".encode()
            ).hexdigest(),
        )

    def _deterministic_werewolf_vote_choice(
        self,
        *,
        round_state: RoundState,
        wolf_name: str,
        candidates: list[str],
    ) -> str:
        material = f"{self.fallback_seed}:{round_state.number}:{wolf_name}:werewolf_final_vote"
        return min(
            candidates,
            key=lambda candidate: hashlib.sha256(
                f"{material}:{candidate}".encode()
            ).hexdigest(),
        )

    def _werewolf_action_message(self, action_log: ActionLog) -> str:
        result = action_log.lm_log.result or {}
        message = result.get("message")
        return self._public_text(str(message).strip()) if isinstance(message, str) else ""

    def _publish_werewolf_private_action(
        self,
        *,
        round_state: RoundState,
        actor: str,
        action: str,
        target: str,
        message: str,
        decision_stage: str,
        fallback_reason: str | None = None,
        action_origin: str = "model",
        public_reason_code: str | None = None,
        action_log: ActionLog | None = None,
    ) -> None:
        public_target = self._public_player_reference(target)
        public_result: dict[str, object] = {"target": public_target}
        if message:
            public_result["message"] = message
        payload: dict[str, object] = {
            "action_id": (
                action_log.lm_log.action_id if action_log is not None else None
            ),
            "request_id": (
                action_log.lm_log.request_id if action_log is not None else None
            ),
            "choice": public_target,
            "result": public_result,
            "visible_result": public_result,
            "message": message,
            "decision_stage": decision_stage,
            "vote_round": 1,
            "action_origin": action_origin,
            "public_reason_code": public_reason_code,
            **({"fallback_reason": fallback_reason} if fallback_reason else {}),
        }
        if (
            message
            and action_log is not None
            and action_log.effective_delivery is not None
        ):
            player = self.state.player_by_name()[actor]
            payload["voice_snapshot"] = {
                "enabled": player.voice_enabled,
                "speaker": player.tts_speaker,
                "effective_delivery": copy.deepcopy(
                    action_log.effective_delivery
                ),
                "effective_context_texts": (
                    action_log.effective_context_texts.copy()
                ),
                "voice_config_version": action_log.voice_config_version,
                "delivery_mapping_version": action_log.delivery_mapping_version,
            }
        self._publish(
            "action_parsed",
            round_number=round_state.number,
            phase="night",
            actor=actor,
            action=action,
            payload=payload,
        )

    def _publish_werewolf_private_abstention(
        self,
        *,
        round_state: RoundState,
        actor: str,
        action: str,
        decision_stage: str,
        action_log: ActionLog,
    ) -> None:
        self._publish(
            "action_parsed",
            round_number=round_state.number,
            phase="night",
            actor=actor,
            action=action,
            payload={
                "action_id": action_log.lm_log.action_id,
                "request_id": action_log.lm_log.request_id,
                "choice": None,
                "result": {},
                "visible_result": {},
                "message": "",
                "decision_stage": decision_stage,
                "vote_round": 1,
                "action_origin": "none",
                "public_reason_code": action_log.reason_code,
            },
        )

    def _publish_werewolf_tiebreak_cue(
        self,
        *,
        round_state: RoundState,
        cue_id: str,
        visible_text: str,
        player: str,
        candidates: list[str],
        target: str | None = None,
    ) -> None:
        params: dict[str, object] = {
            "player": player,
            "players": candidates.copy(),
        }
        if target is not None:
            params["target"] = target
        self._publish_judge_cue(
            round_state,
            "night",
            cue_spec(cue_id, visible_text, params=params),
        )

    def _publish_final_werewolf_target(
        self,
        *,
        round_state: RoundState,
        target: str,
        vote_round: int,
        action_origin: str = "model",
        public_reason_code: str | None = None,
    ) -> None:
        public_target = self._public_player_reference(target)
        public_result = {"target": public_target}
        self._publish(
            "action_parsed",
            round_number=round_state.number,
            phase="night",
            actor=None,
            action=ACTION_REMOVE,
            payload={
                "choice": public_target,
                "result": public_result,
                "visible_result": public_result,
                "vote_round": vote_round,
                "final_target": True,
                "action_origin": action_origin,
                "public_reason_code": public_reason_code,
            },
        )
        self._publish_night_judge_cue(
            round_state,
            "werewolves_sleep",
            "狼人请闭眼。",
        )

    def _record_werewolf_vote_round(
        self,
        vote_round: int,
        candidates: list[str],
        votes: dict[str, str],
        *,
        expected_voters: int,
    ) -> dict[str, object]:
        tally: dict[str, int] = {}
        for target in votes.values():
            tally[target] = tally.get(target, 0) + 1
        voted_targets = list(dict.fromkeys(votes.values()))
        unanimous = len(votes) == expected_voters and len(voted_targets) == 1
        return {
            "round": vote_round,
            "candidates": candidates.copy(),
            "votes": votes.copy(),
            "tally": tally,
            "unanimous": unanimous,
            "result": voted_targets[0] if unanimous else None,
        }

    def _werewolf_vote_round_context(
        self,
        vote_round: dict[str, object] | None,
    ) -> str:
        if not vote_round:
            return "暂无。"
        tally = vote_round.get("tally")
        if not isinstance(tally, dict) or not tally:
            return "暂无。"
        vote_text = "；".join(f"{target}：{count}票" for target, count in tally.items())
        return f"第{vote_round.get('round')}轮匿名刀口：{vote_text}。"

    def _werewolf_majority_target(self, votes: dict[str, str]) -> str | None:
        leaders = self._werewolf_highest_vote_targets(votes)
        return leaders[0] if len(leaders) == 1 else None

    def _werewolf_highest_vote_targets(self, votes: dict[str, str]) -> list[str]:
        tally = Counter(votes.values())
        if not tally:
            return []
        highest_count = max(tally.values())
        return [target for target, count in tally.items() if count == highest_count]

    def _run_witch_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        if (
            ACTION_WITCH_SAVE not in self.rule_set.night_actions
            and ACTION_WITCH_POISON not in self.rule_set.night_actions
        ):
            return

        players_by_name = self.state.player_by_name()
        witch_name = self._active_player_for_role(WITCH, active_players)
        if not witch_name:
            return
        witch = players_by_name[witch_name]

        poison_options = [
            name for name in active_players if name != witch.name and name != round_state.attacked
        ] + [NO_WITCH_POISON]
        can_offer_save = (
            ACTION_WITCH_SAVE in self.rule_set.night_actions
            and bool(round_state.attacked)
            and witch.witch_antidote_available
        )
        can_offer_poison = (
            ACTION_WITCH_POISON in self.rule_set.night_actions
            and witch.witch_poison_available
            and poison_options != [NO_WITCH_POISON]
        )
        if not can_offer_save and not can_offer_poison:
            return

        self._publish_night_judge_cue(
            round_state,
            "witch_wake",
            "女巫请睁眼。",
        )
        if round_state.attacked:
            public_target = self._public_player_reference(round_state.attacked)
            self._publish_night_judge_cue(
                round_state,
                "witch_death",
                f"今晚被狼人袭击的玩家是{public_target}。",
                target=public_target,
            )

        used_antidote = False
        if can_offer_save:
            save_choice, round_log.witch_save = self._player_action(
                player=witch,
                action=ACTION_WITCH_SAVE,
                options=[round_state.attacked, NO_WITCH_SAVE],
                result_key="save",
                round_state=round_state,
                phase="night",
            )
            if save_choice == round_state.attacked:
                round_state.saved_by_witch = round_state.attacked
                witch.witch_antidote_available = False
                used_antidote = True

        if not used_antidote and can_offer_poison:
            poison_choice, round_log.witch_poison = self._player_action(
                player=witch,
                action=ACTION_WITCH_POISON,
                options=poison_options,
                result_key="poison",
                round_state=round_state,
                phase="night",
            )
            if poison_choice and poison_choice != NO_WITCH_POISON:
                round_state.poisoned = str(poison_choice)
                witch.witch_poison_available = False

        self._publish_night_judge_cue(
            round_state,
            "witch_sleep",
            "女巫请闭眼。",
        )

    def _pending_night_deaths(
        self, round_state: RoundState, active_players: list[str]
    ) -> list[DeathEvent]:
        deaths: list[DeathEvent] = []
        if (
            round_state.attacked
            and round_state.attacked != round_state.protected
            and round_state.attacked != round_state.saved_by_witch
        ):
            deaths.append(DeathEvent(round_state.attacked, "werewolf_attack", "狼人"))

        witch_name = self._active_player_for_role(WITCH, active_players)
        if round_state.poisoned:
            deaths.append(DeathEvent(round_state.poisoned, "witch_poison", witch_name or None))

        seen: set[str] = set()
        unique_deaths: list[DeathEvent] = []
        for death in deaths:
            if death.player in seen:
                continue
            seen.add(death.player)
            unique_deaths.append(death)
        return unique_deaths

    def _announce_night_deaths(
        self,
        deaths: list[DeathEvent],
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        *,
        transfer_sheriff_badge: bool = True,
        settlement_phase: str = "night",
    ) -> None:
        pending_night_deaths = self._record_night_deaths(deaths, round_state, active_players)
        self._resolve_night_death_aftermath(
            deaths,
            pending_night_deaths,
            round_state,
            round_log,
            active_players,
            transfer_sheriff_badge=transfer_sheriff_badge,
            phase=settlement_phase,
        )

    def _record_night_deaths(
        self,
        deaths: list[DeathEvent],
        round_state: RoundState,
        active_players: list[str],
    ) -> set[str]:
        existing_dead_players = {
            death.player for death in [*round_state.night_deaths, *round_state.day_deaths]
        }
        recorded_night_deaths: set[str] = set()
        for death in deaths:
            if death.player in existing_dead_players:
                continue
            round_state.night_deaths.append(death)
            self._append_public_outcome(
                round_state=round_state,
                kind="night_death",
                target_player=death.player,
                outcome="eliminated",
                phase="night",
            )
            existing_dead_players.add(death.player)
            recorded_night_deaths.add(death.player)
            self._remove_player(active_players, death.player)

        round_state.eliminated = (
            round_state.night_deaths[0].player if round_state.night_deaths else None
        )
        return recorded_night_deaths

    def _resolve_night_death_aftermath(
        self,
        deaths: list[DeathEvent],
        pending_night_deaths: set[str],
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        transfer_sheriff_badge: bool = True,
        phase: str = "night",
    ) -> None:
        hunter_contexts = self._hunter_settlement_contexts(
            deaths,
            phase=phase,
            death_phase="night",
            excluded_shot_targets=pending_night_deaths,
            excluded_badge_targets=pending_night_deaths,
            transfer_sheriff_badge=False,
        )
        terminal_candidate = bool(self._get_winner(active_players))
        hunter_may_make_terminal = self._hunter_death_chain_may_be_terminal(
            deaths,
            active_players,
            excluded_shot_targets=pending_night_deaths,
        )
        if terminal_candidate or hunter_may_make_terminal:
            self._begin_terminal_settlement(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                primary_actor=None,
                hunter_contexts=hunter_contexts,
                continuation_kind="night_death_aftermath",
                continuation_transfer_sheriff_badge=True,
            )
            self._publish_terminal_primary_presentation(
                round_state=round_state,
                active_players=active_players,
            )
        for death in deaths:
            self._maybe_run_hunter_shot(
                dead_player=death.player,
                death_cause=death.cause,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase=phase,
                excluded_shot_targets=pending_night_deaths,
                excluded_badge_targets=pending_night_deaths,
                transfer_sheriff_badge=False,
            )

        if self._commit_terminal_winner(active_players, round_state):
            return

        if transfer_sheriff_badge:
            night_death_players = {death.player for death in round_state.night_deaths}
            for death in list(round_state.night_deaths):
                self._maybe_transfer_sheriff_badge(
                    dead_player=death.player,
                    round_state=round_state,
                    round_log=round_log,
                    active_players=active_players,
                    phase=phase,
                    excluded_badge_targets=night_death_players,
                )
            self._complete_cleared_terminal_continuation(active_players)

    def _maybe_run_hunter_shot(
        self,
        *,
        dead_player: str,
        death_cause: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        phase: str,
        death_phase: Literal["night", "day"] | None = None,
        excluded_shot_targets: set[str] | None = None,
        excluded_badge_targets: set[str] | None = None,
        transfer_sheriff_badge: bool = True,
    ) -> None:
        players_by_name = self.state.player_by_name()
        hunter = players_by_name[dead_player]
        if hunter.role != HUNTER or not hunter.hunter_can_shoot:
            return
        if death_cause == "witch_poison":
            return

        excluded_shot_targets = excluded_shot_targets or set()
        options = [
            name
            for name in active_players
            if name != hunter.name and name not in excluded_shot_targets
        ] + [NO_HUNTER_SHOT]
        if options == [NO_HUNTER_SHOT]:
            self._accept_terminal_hunter_choice(
                hunter=hunter,
                shot=NO_HUNTER_SHOT,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                death_cause=death_cause,
                phase=phase,
                death_phase=death_phase,
                excluded_shot_targets=excluded_shot_targets,
                excluded_badge_targets=excluded_badge_targets,
                transfer_sheriff_badge=transfer_sheriff_badge,
            )
            self._apply_hunter_shot_choice(
                hunter=hunter,
                shot=NO_HUNTER_SHOT,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase=phase,
                death_phase=death_phase,
                excluded_badge_targets=excluded_badge_targets,
                transfer_sheriff_badge=transfer_sheriff_badge,
            )
            return

        self._publish_judge_cues(
            round_state,
            phase,
            hunter_start_cues(self._public_player_reference(hunter.name)),
        )
        shot, action_log = self._player_action(
            player=hunter,
            action=ACTION_HUNTER_SHOOT,
            options=options,
            result_key="shoot",
            round_state=round_state,
            phase=phase,
            terminal_settlement_allowed=True,
            extra_world_state={
                "hard_state": {
                    "actor_alive": False,
                    "death_cause": death_cause,
                    "current_action": "猎人死亡技能结算",
                    "hunter_death_trigger_active": True,
                    "terminal_after_current_action": self._hunter_settlement_is_terminal(
                        active_players,
                        options,
                    ),
                }
            },
        )
        if self._hunter_reasoning_claims_alive(action_log):
            shot, action_log = self._player_action(
                player=hunter,
                action=ACTION_HUNTER_SHOOT,
                options=options,
                result_key="shoot",
                round_state=round_state,
                phase=phase,
                terminal_settlement_allowed=True,
                extra_world_state={
                    "hard_state": {
                        "actor_alive": False,
                        "death_cause": death_cause,
                        "current_action": "猎人死亡技能结算",
                        "hunter_death_trigger_active": True,
                        "terminal_after_current_action": self._hunter_settlement_is_terminal(
                            active_players,
                            options,
                        ),
                    },
                    "quality_feedback": (
                        "你的上一份推理错误地声称自己仍存活。引擎已确认你死亡，"
                        "请基于死亡技能状态重新选择。"
                    ),
                },
            )
        round_log.hunter_shoot = action_log
        self._accept_terminal_hunter_choice(
            hunter=hunter,
            shot=shot,
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
            death_cause=death_cause,
            phase=phase,
            death_phase=death_phase,
            excluded_shot_targets=excluded_shot_targets,
            excluded_badge_targets=excluded_badge_targets,
            transfer_sheriff_badge=transfer_sheriff_badge,
        )
        self._apply_hunter_shot_choice(
            hunter=hunter,
            shot=shot,
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
            phase=phase,
            death_phase=death_phase,
            excluded_badge_targets=excluded_badge_targets,
            transfer_sheriff_badge=transfer_sheriff_badge,
        )

    def _apply_hunter_shot_choice(
        self,
        *,
        hunter: Player,
        shot: object | None,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        phase: str,
        death_phase: Literal["night", "day"] | None = None,
        excluded_badge_targets: set[str] | None,
        transfer_sheriff_badge: bool,
    ) -> None:
        hunter.hunter_can_shoot = False
        if shot and shot != NO_HUNTER_SHOT:
            shot_player = str(shot)
            round_state.hunter_shot = shot_player
            self._remove_player(active_players, shot_player)
            death = DeathEvent(shot_player, "hunter_shot", hunter.name)
            effective_death_phase = death_phase or (
                "night" if phase in {"night", "dawn_reveal"} else "day"
            )
            if effective_death_phase == "night":
                round_state.night_deaths.append(death)
            else:
                round_state.day_deaths.append(death)
            self._append_public_outcome(
                round_state=round_state,
                kind="hunter_shot",
                actor_player=hunter.name,
                target_player=shot_player,
                outcome="eliminated",
                phase=phase,
                caused_by_event=self._latest_player_outcome(
                    round_state,
                    hunter.name,
                ),
            )
            self._add_public_fact(
                round_state.number,
                "death",
                f"第{round_state.number}轮：{hunter.name}发动猎人技能，{shot_player}出局。",
                stage="hunter_shot",
                actor=hunter.name,
                retention="critical",
                details={"target": shot_player},
            )
            if transfer_sheriff_badge and not self._get_winner(active_players):
                self._maybe_transfer_sheriff_badge(
                    dead_player=shot_player,
                    round_state=round_state,
                    round_log=round_log,
                    active_players=active_players,
                    phase=phase,
                    excluded_badge_targets=excluded_badge_targets,
                )
            self._mark_terminal_hunter_applied(
                actor=hunter.name,
                active_players=active_players,
            )
            self._publish_terminal_hunter_presentation(
                actor=hunter.name,
                round_state=round_state,
                phase=phase,
                active_players=active_players,
                shot=shot_player,
            )
            return
        self._mark_terminal_hunter_applied(
            actor=hunter.name,
            active_players=active_players,
        )
        self._publish_terminal_hunter_presentation(
            actor=hunter.name,
            round_state=round_state,
            phase=phase,
            active_players=active_players,
            shot=NO_HUNTER_SHOT,
        )

    def _hunter_reasoning_claims_alive(self, action_log: ActionLog) -> bool:
        result = action_log.lm_log.result or {}
        reasoning = result.get("reasoning")
        if not isinstance(reasoning, str):
            return False
        return re.search(r"我.{0,8}(?:仍|还|尚).{0,5}(?:存活|活着|在场)", reasoning) is not None

    def _run_day_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        pending_night_deaths: list[DeathEvent] | None = None,
    ) -> None:
        skip_sheriff_election = bool(
            pending_night_deaths
            and self._deferred_deaths_are_inevitably_terminal(
                pending_night_deaths,
                active_players,
            )
        )
        sheriff_election_interrupted = False
        self._has_unsettled_deferred_night_deaths = bool(pending_night_deaths)
        try:
            if not skip_sheriff_election:
                sheriff_election_interrupted = self._run_sheriff_election_if_needed(
                    round_state,
                    round_log,
                    active_players,
                    "dawn_reveal" if pending_night_deaths is not None else "day",
                )
        finally:
            self._has_unsettled_deferred_night_deaths = False

        self._finish_deferred_night_deaths_if_needed(
            pending_night_deaths,
            round_state,
            round_log,
            active_players,
        )
        if sheriff_election_interrupted:
            self._finish_self_explosion_day(round_state, round_log, active_players)
            return
        if self.state.winner:
            return

        self._start_phase(
            round_number=round_state.number,
            phase="day",
            payload={
                "active_players": active_players.copy(),
                "narration_mode": "explicit_v1",
            },
        )
        if self._run_debate_phase(round_state, round_log, active_players):
            self._finish_self_explosion_day(round_state, round_log, active_players)
            return

        self._cancel_pending_self_explosion()
        self._self_explosion_locked = True
        self._complete_phase(
            round_number=round_state.number,
            phase="day",
            completion_status="completed",
            completion_reason="day_speech_completed",
            next_phase="vote",
            terminal=False,
        )
        self._start_phase(
            round_number=round_state.number,
            phase="vote",
            payload={"active_players": active_players.copy()},
        )
        try:
            votes, vote_logs = self._run_voting(round_state, active_players)
            round_state.votes.append(votes)
            round_log.votes.append(vote_logs)
            round_state.vote_origins = _vote_origins(vote_logs)
            if votes:
                self._add_public_fact(
                    round_state.number,
                    "vote",
                    f"第{round_state.number}轮票型："
                    + "；".join(
                        _public_vote_line(
                            voter,
                            target,
                            round_state.vote_origins.get(voter),
                        )
                        for voter, target in votes.items()
                    ),
                    stage="vote",
                    retention="important",
                    details={
                        "votes": votes.copy(),
                        "vote_origins": copy.deepcopy(round_state.vote_origins),
                    },
                )
            self._publish_state_updated(
                round_state=round_state,
                phase="vote",
                action="vote",
                payload={
                    "votes": votes,
                    "vote_origins": copy.deepcopy(round_state.vote_origins),
                },
            )

            interrupted_by_self_explosion = self._run_exile_vote_resolution(
                votes,
                round_state,
                round_log,
                active_players,
            )
        finally:
            self._self_explosion_locked = False
        if interrupted_by_self_explosion:
            self._finish_self_explosion_day(round_state, round_log, active_players)
            return
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            action="day_resolution_completed",
            payload={
                "narration_mode": "explicit_v1",
                "exiled": round_state.exiled,
                "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                "hunter_shot": round_state.hunter_shot,
                "idiot_revealed": round_state.idiot_revealed,
                "exile_pk_candidates": round_state.exile_pk_candidates.copy(),
                "exile_pk_speeches": copy.deepcopy(round_state.exile_pk_speeches),
                "exile_runoff_votes": round_state.exile_runoff_votes.copy(),
                "exile_runoff_vote_origins": copy.deepcopy(
                    round_state.exile_runoff_vote_origins
                ),
                "vote_origins": copy.deepcopy(round_state.vote_origins),
                "exile_resolution_reason": round_state.exile_resolution_reason,
                "active_players": active_players.copy(),
            },
        )
        self._complete_phase(
            round_number=round_state.number,
            phase="vote",
            completion_status="terminal" if self._get_winner(active_players) else "completed",
            completion_reason=round_state.exile_resolution_reason or "vote_resolved",
            next_phase=None if self._get_winner(active_players) else "summary",
            terminal=bool(self._get_winner(active_players)),
        )
        if self._commit_terminal_winner(active_players, round_state):
            return
        self._publish_public_round_brief(round_state, active_players)
        self._run_private_round_memories(round_state, round_log, active_players)

    def _finish_self_explosion_day(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        active_phase = next(
            (
                phase
                for phase in ("vote", "day")
                if (round_state.number, phase) in self._active_phase_instances
            ),
            None,
        )
        if active_phase is None:
            active_phase = "day"
            self._start_phase(
                round_number=round_state.number,
                phase=active_phase,
                payload={
                    "active_players": active_players.copy(),
                    "narration_mode": "explicit_v1",
                },
            )
        self._publish_self_explosion_update(
            round_state,
            active_players,
            phase=active_phase,
        )
        terminal = bool(self.state.winner or self._get_winner(active_players))
        self._complete_phase(
            round_number=round_state.number,
            phase=active_phase,
            completion_status="terminal" if terminal else "canceled",
            completion_reason="self_explosion",
            next_phase=None if terminal else "summary",
            terminal=terminal,
        )
        if self._commit_terminal_winner(active_players, round_state):
            return
        self._publish_public_round_brief(round_state, active_players)
        self._run_private_round_memories(round_state, round_log, active_players)

    def _finish_deferred_night_deaths_if_needed(
        self,
        pending_night_deaths: list[DeathEvent] | None,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        if pending_night_deaths is None:
            return

        self._start_phase(
            round_number=round_state.number,
            phase="dawn_reveal",
            payload={"active_players": active_players.copy()},
        )
        pending_night_death_players = self._record_night_deaths(
            pending_night_deaths,
            round_state,
            active_players,
        )
        self._resolve_night_death_aftermath(
            pending_night_deaths,
            pending_night_death_players,
            round_state,
            round_log,
            active_players,
            transfer_sheriff_badge=False,
            phase="dawn_reveal",
        )
        if round_state.night_deaths:
            eliminated_names = "、".join(death.player for death in round_state.night_deaths)
            self._announce(
                active_players, f"第{round_state.number}轮：夜晚，{eliminated_names}出局。"
            )
            self._add_public_fact(
                round_state.number,
                "death",
                f"第{round_state.number}轮：夜晚，{eliminated_names}出局。",
                stage="night_resolution",
                retention="critical",
                details={
                    "players": [death.player for death in round_state.night_deaths],
                },
            )
        else:
            self._announce(active_players, f"第{round_state.number}轮：夜晚无人出局。")

        night_result_event = self._publish_state_updated(
            round_state=round_state,
            phase="night",
            action="night_resolved",
            payload={
                "narration_mode": "explicit_v1",
                "attacked": round_state.attacked,
                "eliminated": round_state.eliminated,
                "protected": round_state.protected,
                "investigated": round_state.investigated,
                "saved_by_witch": round_state.saved_by_witch,
                "poisoned": round_state.poisoned,
                "night_deaths": [death.to_dict() for death in round_state.night_deaths],
                "active_players": active_players.copy(),
            },
        )
        if self.state.winner:
            self._remember_terminal_keep_event(night_result_event)
        self._publish_dawn_result(round_state)
        if not self._commit_terminal_winner(active_players, round_state):
            self._transfer_sheriff_badge_after_night_deaths(
                round_state,
                round_log,
                active_players,
            )
        terminal = bool(self.state.winner) and not round_state.day_ended_by_self_explosion
        self._complete_phase(
            round_number=round_state.number,
            phase="dawn_reveal",
            completion_status="terminal" if terminal else "completed",
            completion_reason="night_result_presented",
            next_phase=None if terminal else "day",
            terminal=terminal,
        )

    def _transfer_sheriff_badge_after_night_deaths(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        if self.state.winner or self._get_winner(active_players):
            return
        night_death_players = {death.player for death in round_state.night_deaths}
        for death in list(round_state.night_deaths):
            self._maybe_transfer_sheriff_badge(
                dead_player=death.player,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="dawn_reveal",
                excluded_badge_targets=night_death_players,
            )
        self._complete_cleared_terminal_continuation(active_players)

    def _publish_dawn_result(self, round_state: RoundState) -> None:
        self._start_phase(
            round_number=round_state.number,
            phase="dawn_reveal",
            payload={},
        )
        primary_presentation = self._terminal_primary_presentation(round_state)
        if (
            primary_presentation is not None
            and primary_presentation.get("kind") == "night_result"
        ):
            return
        public_players = [
            event.target_player_id
            for event in round_state.public_outcome_events
            if event.kind == "night_death" and event.target_player_id
        ]
        self._publish_judge_cue(
            round_state,
            "dawn_reveal",
            dawn_result_cue(public_players),
        )

    def _publish_self_explosion_update(
        self,
        round_state: RoundState,
        active_players: list[str],
        *,
        phase: str = "day",
    ) -> None:
        primary_presentation = self._terminal_primary_presentation(round_state)
        self_explosion_payload: dict[str, object] = {
            "werewolf_self_exploded": round_state.werewolf_self_exploded,
            "day_ended_by_self_explosion": round_state.day_ended_by_self_explosion,
            "day_deaths": [death.to_dict() for death in round_state.day_deaths],
            "sheriff_pre_election_bomb_count": (
                round_state.sheriff_pre_election_bomb_count
            ),
            "sheriff_election_pending": round_state.sheriff_election_pending,
            "sheriff_badge_lost": round_state.sheriff_badge_lost,
            "sheriff_badge_lost_reason": round_state.sheriff_badge_lost_reason,
            "interruption": (
                round_state.interruption.to_dict() if round_state.interruption else None
            ),
            "active_players": active_players.copy(),
        }
        if (
            primary_presentation is not None
            and primary_presentation.get("kind") == "self_explosion_result"
        ):
            self_explosion_payload["presentation_id"] = primary_presentation[
                "presentation_id"
            ]
        else:
            self_explosion_payload["narration_mode"] = "explicit_v1"
        self_explosion_event = self._publish_state_updated(
            round_state=round_state,
            phase=phase,
            actor=round_state.werewolf_self_exploded,
            action=ACTION_WEREWOLF_SELF_EXPLOSION,
            payload=self_explosion_payload,
        )
        if "presentation_id" in self_explosion_payload:
            self._terminal_primary_event = self_explosion_event
        if self.state.winner:
            self._remember_terminal_keep_event(self_explosion_event)
        self_explosion_outcome = next(
            (
                event
                for event in reversed(round_state.public_outcome_events)
                if event.kind == "self_explosion"
            ),
            None,
        )
        if (
            "presentation_id" not in self_explosion_payload
            and self_explosion_outcome
            and self_explosion_outcome.actor_player_id
        ):
            interruption = round_state.interruption
            self._publish_judge_cues(
                round_state,
                phase,
                self_explosion_cues(
                    self_explosion_outcome.actor_player_id,
                    stage=interruption.stage if interruption else "day",
                    completed_actors=(
                        [
                            self._public_player_reference(name)
                            for name in interruption.completed_actors
                        ]
                        if interruption
                        else []
                    ),
                    pending_actors=(
                        [
                            self._public_player_reference(name)
                            for name in interruption.pending_actors
                        ]
                        if interruption
                        else []
                    ),
                ),
            )

    def _run_debate_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> bool:
        speech_order = self._speech_order(round_state, round_log, active_players)
        round_state.speech_order = speech_order
        players_by_name = self.state.player_by_name()
        completed_speakers: list[str] = []

        for speaker in speech_order:
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="debate",
                    ordered_actors=tuple(speech_order),
                    completed_actors=tuple(completed_speakers),
                    current_actor=speaker,
                    timing="before_actor",
                ),
            ):
                return True
            player = players_by_name[speaker]
            action_result = self._interruptible_public_speech_action(
                player=player,
                action=ACTION_DEBATE,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="day",
                cursor=PublicStageCursor(
                    stage="debate",
                    ordered_actors=tuple(speech_order),
                    completed_actors=tuple(completed_speakers),
                    current_actor=speaker,
                    timing="before_actor",
                ),
            )
            if action_result is None:
                return True
            message, action_log = action_result
            round_log.debate.append(action_log)
            if not isinstance(message, str) or not message:
                completed_speakers.append(speaker)
                if self._maybe_run_werewolf_self_explosion(
                    round_state,
                    round_log,
                    active_players,
                    PublicStageCursor(
                        stage="debate",
                        ordered_actors=tuple(speech_order),
                        completed_actors=tuple(completed_speakers),
                        current_actor=speaker,
                        timing="after_actor",
                    ),
                ):
                    return True
                continue
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="day",
                actor=speaker,
                action=ACTION_DEBATE,
                text=message,
                prior_texts=[entry.message for entry in round_state.debate],
                personality=player.personality,
            )

            entry = DebateEntry(speaker=speaker, message=message)
            round_state.debate.append(entry)
            completed_speakers.append(speaker)
            self._record_public_debate(active_players, entry)
            self._add_public_fact(
                round_state.number,
                "claim",
                f"第{round_state.number}轮白天发言第{len(completed_speakers)}位："
                f"{speaker}：{message}",
                stage="debate",
                actor=speaker,
                retention="important",
                details={"turn_index": len(completed_speakers)},
            )
            self._publish_state_updated(
                round_state=round_state,
                phase="day",
                actor=speaker,
                action=ACTION_DEBATE,
                payload={
                    "debate_entry": entry.to_dict(),
                    "debate": [debate_entry.to_dict() for debate_entry in round_state.debate],
                    "speech_order": round_state.speech_order.copy(),
                },
            )
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="debate",
                    ordered_actors=tuple(speech_order),
                    completed_actors=tuple(completed_speakers),
                    current_actor=speaker,
                    timing="after_actor",
                ),
            ):
                return True
        return False

    def _interruptible_public_speech_action(
        self,
        *,
        player: Player,
        action: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        phase: str,
        cursor: PublicStageCursor,
    ) -> tuple[object | None, ActionLog] | None:
        request = self._build_player_action_request(
            player=player,
            action=action,
            options=[],
            result_key="say",
            round_state=round_state,
            phase=phase,
        )
        started_at = self.monotonic()
        self._active_public_action = ActivePublicActionContext(
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
            cursor=cursor,
            actor=player.name,
            action=action,
            action_id=request.action_id,
        )
        try:
            return self._player_action_single(request)
        except _PublicActionInterruptedBySelfExplosion as exc:
            canceled_log = self._canceled_player_action_log(
                request,
                started_at=started_at,
            )
            canceled_log.lm_log.attempt_outcomes = safe_attempt_outcomes(
                getattr(exc, "attempt_outcomes", [])
            )
            if canceled_log.lm_log.attempt_outcomes:
                canceled_log.lm_log.request_id = canceled_log.lm_log.attempt_outcomes[-1][
                    "request_id"
                ]
            canceled_log.reason_code = "self_explosion_cancelled"
            canceled_log.effective_origin = "none"
            round_log.canceled_actions.append(canceled_log)
            self._record_synthetic_logical_action(
                canceled_log,
                request,
                result="canceled",
            )
            return None
        finally:
            self._active_public_action = None

    def _speech_order(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> list[str]:
        if (
            self.rule_set.speech_policy == SPEECH_POLICY_SHERIFF_DIRECTED
            and self.state.sheriff
            and self.state.sheriff in active_players
        ):
            return self._sheriff_directed_speech_order(round_state, round_log, active_players)
        return active_players.copy()

    def _maybe_run_werewolf_self_explosion(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        cursor: PublicStageCursor,
    ) -> bool:
        if not self.rule_set.werewolf_self_explosion_enabled:
            return False
        if self.state.winner or self._self_explosion_locked:
            self._cancel_pending_self_explosion(
                reason=("canceled_terminal" if self.state.winner else "superseded")
            )
            return False

        pending = self._pending_self_explosion
        if pending is not None and pending.round_number != round_state.number:
            self._cancel_pending_self_explosion()
            pending = None

        if pending is not None and not self._self_explosion_window_accepts(
            pending.cursor,
            cursor,
        ):
            self._cancel_pending_self_explosion()
            pending = None

        if pending is not None:
            if not all(future.done() for future in pending.futures):
                wait(pending.futures, timeout=SELF_EXPLOSION_HANDOFF_TIMEOUT_SECONDS)
            if pending is not None and self._accept_ready_self_explosion(
                pending,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                cursor=cursor,
            ):
                self._pending_self_explosion = None
                return True
            if pending is not None and not all(
                future.done() for future in pending.futures
            ):
                if pending.cursor == cursor:
                    return False
                self._cancel_pending_self_explosion()
                pending = None
            if pending is not None:
                self._pending_self_explosion = None
                if self._accept_completed_self_explosion(
                    pending,
                    round_state=round_state,
                    round_log=round_log,
                    active_players=active_players,
                    cursor=cursor,
                ):
                    return True

        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        action_phase = self._public_stage_phase(cursor)
        requests = tuple(
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_WEREWOLF_SELF_EXPLOSION,
                options=[WEREWOLF_SELF_EXPLODE, WEREWOLF_NO_SELF_EXPLODE],
                result_key="self_explode",
                round_state=round_state,
                phase=action_phase,
                extra_world_state={
                    "self_explosion_stage": self._self_explosion_stage_description(cursor),
                    "self_explosion_decision_context": (
                        self._self_explosion_decision_context(
                            actor=name,
                            round_state=round_state,
                            active_players=active_players,
                            active_wolves=active_wolves,
                            cursor=cursor,
                        ).to_dict()
                    ),
                    "self_explosion_stage_context": {
                        "stage": cursor.stage,
                        "timing": cursor.timing,
                        "current_actor": cursor.current_actor,
                        "completed_actors": list(cursor.completed_actors),
                        "pending_actors": cursor.pending_actors,
                    },
                },
            )
            for name in active_wolves
        )
        self._start_pending_self_explosion(
            round_number=round_state.number,
            active_wolves=tuple(active_wolves),
            requests=requests,
            cursor=cursor,
        )
        return False

    def _accept_ready_self_explosion(
        self,
        pending: PendingSelfExplosionBatch,
        *,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        cursor: PublicStageCursor,
    ) -> bool:
        """Accept a completed self-explosion intent without waiting for the batch."""
        completed_results: list[PlayerActionResult | None] = [None] * len(
            pending.futures
        )
        accepted_index: int | None = None
        for index, future in enumerate(pending.futures):
            if not future.done():
                continue
            try:
                result = future.result()
            except Exception as exc:
                self._checkpoint_player_action_failure(pending.requests[index], exc)
                raise
            completed_results[index] = result
            if result.value == WEREWOLF_SELF_EXPLODE and accepted_index is None:
                accepted_index = index

        if accepted_index is None:
            return False

        self._checkpoint_player_action_results(completed_results)
        finalized: dict[int, tuple[object | None, ActionLog]] = {}
        for index, result in enumerate(completed_results):
            if result is None:
                continue
            try:
                finalized[index] = self._finalize_player_action_result(
                    result,
                    checkpoint=False,
                )
            except Exception as exc:
                self._checkpoint_player_action_failure(result.request, exc)
                raise
            self._record_self_explosion_decision(
                action_log=finalized[index][1],
                round_state=round_state,
                round_log=round_log,
                cursor=pending.cursor,
            )
        for index, future in enumerate(pending.futures):
            if future.done():
                continue
            future.cancel()
            canceled_log = self._canceled_player_action_log(
                pending.requests[index],
                started_at=pending.started_at,
            )
            canceled_log.reason_code = "phase_advanced"
            canceled_log.effective_origin = "none"
            self._record_self_explosion_decision(
                action_log=canceled_log,
                round_state=round_state,
                round_log=round_log,
                cursor=pending.cursor,
                audit_execution_status="superseded",
            )
            self._record_synthetic_logical_action(
                canceled_log,
                pending.requests[index],
                result="canceled",
            )
        choice, action_log = finalized[accepted_index]
        return self._accept_self_explosion_choice(
            name=pending.active_wolves[accepted_index],
            choice=choice,
            action_log=action_log,
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
            cursor=cursor,
        )

    def _accept_completed_self_explosion(
        self,
        pending: PendingSelfExplosionBatch,
        *,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        cursor: PublicStageCursor,
    ) -> bool:
        decisions = self._finish_pending_self_explosion(pending)
        for name, (choice, action_log) in zip(
            pending.active_wolves,
            decisions,
            strict=True,
        ):
            self._record_self_explosion_decision(
                action_log=action_log,
                round_state=round_state,
                round_log=round_log,
                cursor=pending.cursor,
            )
            if self._accept_self_explosion_choice(
                name=name,
                choice=choice,
                action_log=action_log,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                cursor=cursor,
            ):
                return True
        return False

    def _record_self_explosion_decision(
        self,
        *,
        action_log: ActionLog,
        round_state: RoundState,
        round_log: RoundLog,
        cursor: PublicStageCursor,
        audit_execution_status: str | None = None,
    ) -> None:
        action_id = action_log.lm_log.action_id
        if action_id is not None and any(
            existing.lm_log.action_id == action_id
            for existing in round_log.werewolf_self_explosion_decisions
        ):
            return
        window_id = build_self_explosion_window_id(
            round_number=round_state.number,
            stage=cursor.stage,
            timing=cursor.timing,
            ordered_actors=cursor.ordered_actors,
            completed_actors=cursor.completed_actors,
            current_actor=cursor.current_actor,
        )
        audit = build_self_explosion_audit_payload(
            result=action_log.lm_log.result,
            window_id=window_id,
            execution_status=(audit_execution_status or action_log.execution_status),
            duration_ms=action_log.duration_ms,
        )
        action_log.decision_schema = audit["decision_schema"]
        action_log.decision_audit = dict(audit)
        round_log.werewolf_self_explosion_decisions.append(action_log)

    def _canceled_player_action_log(
        self,
        request: PlayerActionRequest,
        *,
        started_at: float,
    ) -> ActionLog:
        return ActionLog(
            actor=request.player.name,
            action=request.action,
            options=request.options.copy(),
            choice=None,
            lm_log=LmLog(
                prompt="",
                raw_response="",
                result=None,
                action_id=request.action_id,
            ),
            execution_status="canceled",
            duration_ms=max(0, round((self.monotonic() - started_at) * 1000)),
            budget_ms=(
                round(
                    self.action_execution_budget.for_action(
                        request.action
                    ).total_budget_seconds
                    * 1000
                )
                if self.action_budgets_enabled
                else None
            ),
            fact_prompt_coverage=copy.deepcopy(request.fact_prompt_coverage),
        )

    def _record_synthetic_logical_action(
        self,
        action_log: ActionLog,
        request: PlayerActionRequest,
        *,
        result: Literal["canceled", "failed"],
    ) -> None:
        if not self.action_budgets_enabled:
            return
        record_action_execution(
            action_kind=self.action_execution_budget.for_action(request.action).kind,
            model=request.player.model,
            result=result,
            duration_ms=action_log.duration_ms,
            first_token_ms=None,
            fallback_reason=None,
            action_id=request.action_id,
        )

    def _accept_self_explosion_choice(
        self,
        *,
        name: str,
        choice: object | None,
        action_log: ActionLog,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        cursor: PublicStageCursor,
    ) -> bool:
        players_by_name = self.state.player_by_name()
        if (
            choice != WEREWOLF_SELF_EXPLODE
            or name not in active_players
            or not self._is_werewolf(players_by_name[name])
        ):
            return False
        round_log.werewolf_self_explosion = action_log
        round_state.interruption = self._stage_interruption_from_cursor(cursor, actor=name)
        self._resolve_werewolf_self_explosion(
            wolf=name,
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
            phase=self._public_stage_phase(cursor),
        )
        interruption_text = self._stage_interruption_text(
            round_state.number,
            round_state.interruption,
        )
        self._add_public_fact(
            round_state.number,
            "interruption",
            interruption_text,
            stage=cursor.stage,
            actor=name,
            retention="critical",
            details=round_state.interruption.to_dict(),
        )
        return True

    def _self_explosion_window_accepts(
        self,
        origin: PublicStageCursor,
        current: PublicStageCursor,
    ) -> bool:
        if origin.stage != current.stage or origin.ordered_actors != current.ordered_actors:
            return False
        if origin == current:
            return True
        if (
            origin.timing == "before_stage"
            and current.timing == "before_actor"
            and bool(current.ordered_actors)
            and not current.completed_actors
            and current.current_actor == current.ordered_actors[0]
        ):
            return True
        if (
            origin.timing == "after_actor"
            and current.timing == "before_actor"
            and origin.completed_actors == current.completed_actors
            and origin.current_actor in origin.ordered_actors
            and current.current_actor in current.ordered_actors
        ):
            origin_index = origin.ordered_actors.index(origin.current_actor)
            current_index = current.ordered_actors.index(current.current_actor)
            return current_index == origin_index + 1
        return False

    def _interrupt_public_action_if_self_explosion_ready(self, event_type: str) -> None:
        if event_type == "model_thinking_tick":
            return
        context = self._active_public_action
        pending = self._pending_self_explosion
        if context is None or pending is None or self._self_explosion_locked:
            return
        if not all(future.done() for future in pending.futures):
            wait(pending.futures, timeout=SELF_EXPLOSION_HANDOFF_TIMEOUT_SECONDS)
        if not self._self_explosion_window_accepts(pending.cursor, context.cursor):
            self._cancel_pending_self_explosion()
            return
        accepted = self._accept_ready_self_explosion(
            pending,
            round_state=context.round_state,
            round_log=context.round_log,
            active_players=context.active_players,
            cursor=context.cursor,
        )
        if not accepted:
            if not all(future.done() for future in pending.futures):
                return
            accepted = self._accept_completed_self_explosion(
                pending,
                round_state=context.round_state,
                round_log=context.round_log,
                active_players=context.active_players,
                cursor=context.cursor,
            )
        if not accepted:
            self._pending_self_explosion = None
            return
        self._pending_self_explosion = None
        committed = self._active_committed_speech.get(context.action_id)
        segments = committed.get("segments") if isinstance(committed, dict) else None
        if isinstance(segments, list) and segments:
            trigger_source = self._latest_live_event_coordinate()
            committed["trigger_source"] = copy.deepcopy(trigger_source)
            committed["interruption_reason"] = "self_explosion"
            self._publish(
                "speech_playback_preempted",
                round_number=context.round_state.number,
                phase=self._public_stage_phase(context.cursor),
                actor=context.actor,
                action=context.action,
                payload={
                    "schema_version": 1,
                    "action_id": context.action_id,
                    "speech_id": committed["speech_id"],
                    "reason": "self_explosion",
                    "trigger_source": trigger_source,
                    "cut_after_segment_index": len(segments) - 1,
                    "audience": "player_public",
                },
            )
        else:
            self._publish(
                "public_action_cancelled",
                round_number=context.round_state.number,
                phase=self._public_stage_phase(context.cursor),
                actor=context.actor,
                payload={
                    "action_id": context.action_id,
                    "canceled_action": context.action,
                    "reason_code": "werewolf_self_explosion",
                },
            )
        raise _PublicActionInterruptedBySelfExplosion()

    def _latest_live_event_coordinate(self) -> dict[str, object]:
        run_id = getattr(self.event_sink, "run_id", None)
        registry = getattr(self.event_sink, "registry", None)
        if isinstance(run_id, str) and registry is not None:
            events_after = getattr(registry, "events_after", None)
            if callable(events_after):
                events = events_after(run_id)
                if events:
                    return {
                        "source_run_id": run_id,
                        "source_event_id": events[-1].id,
                    }
        captured = getattr(self.event_sink, "events", None)
        return {
            "source_run_id": run_id if isinstance(run_id, str) else "local",
            "source_event_id": max(1, len(captured) if isinstance(captured, list) else 1),
        }

    def _start_pending_self_explosion(
        self,
        *,
        round_number: int,
        active_wolves: tuple[str, ...],
        requests: tuple[PlayerActionRequest, ...],
        cursor: PublicStageCursor,
    ) -> None:
        if not requests:
            return
        if self._self_explosion_executor is None:
            self._self_explosion_executor = ThreadPoolExecutor(
                max_workers=max(1, len(self.state.players)),
                thread_name_prefix="werewolf-self-explosion",
            )

        condition = threading.Condition()
        next_index = {"value": 0}
        futures = tuple(
            self._self_explosion_executor.submit(
                self._execute_player_action_request,
                request,
                _OrderedBatchProvider(
                    provider=self.provider,
                    index=index,
                    condition=condition,
                    next_index=next_index,
                ),
                NullEventSink(),
            )
            for index, request in enumerate(requests)
        )
        self._pending_self_explosion = PendingSelfExplosionBatch(
            round_number=round_number,
            active_wolves=active_wolves,
            requests=requests,
            futures=futures,
            started_at=self.monotonic(),
            cursor=cursor,
        )

    def _finish_pending_self_explosion(
        self,
        pending: PendingSelfExplosionBatch,
    ) -> list[tuple[object | None, ActionLog]]:
        results: list[PlayerActionResult | None] = [None] * len(pending.futures)
        exceptions: dict[int, Exception] = {}
        for index, future in enumerate(pending.futures):
            try:
                results[index] = future.result()
            except Exception as exc:
                exceptions[index] = exc

        if self.action_budgets_enabled:
            record_action_batch(
                action_kind=self.action_execution_budget.for_action(
                    ACTION_WEREWOLF_SELF_EXPLOSION
                ).kind,
                result="failed" if exceptions else "completed",
                duration_ms=max(
                    0,
                    round((self.monotonic() - pending.started_at) * 1000),
                ),
            )
        self._checkpoint_player_action_results(results)
        if exceptions:
            first_failed_index = min(exceptions)
            request = pending.requests[first_failed_index]
            exc = exceptions[first_failed_index]
            self._checkpoint_player_action_failure(request, exc)
            raise exc

        finalized: list[tuple[object | None, ActionLog]] = []
        for result in results:
            if result is None:
                raise RuntimeError("Self-explosion batch completed without a result.")
            try:
                finalized.append(self._finalize_player_action_result(result, checkpoint=False))
            except Exception as exc:
                self._checkpoint_player_action_failure(result.request, exc)
                raise
        return finalized

    def _cancel_pending_self_explosion(
        self,
        *,
        reason: Literal["canceled_terminal", "expired", "superseded"] = "expired",
    ) -> None:
        pending = self._pending_self_explosion
        self._pending_self_explosion = None
        if pending is None:
            return
        round_state = next(
            (
                item
                for item in self.state.rounds
                if item.number == pending.round_number
            ),
            None,
        )
        round_log = next(
            (item for item in self.logs if item.number == pending.round_number),
            None,
        )
        for index, future in enumerate(pending.futures):
            request = pending.requests[index]
            if round_log is not None and any(
                item.lm_log.action_id == request.action_id
                for item in round_log.werewolf_self_explosion_decisions
            ):
                continue
            if (
                reason != "canceled_terminal"
                and future.done()
                and not future.cancelled()
            ):
                try:
                    result = future.result()
                    _choice, action_log = self._finalize_player_action_result(
                        result,
                        checkpoint=False,
                    )
                except Exception:
                    action_log = self._canceled_player_action_log(
                        request,
                        started_at=pending.started_at,
                    )
                    action_log.execution_status = "failed"
                    self._record_synthetic_logical_action(
                        action_log,
                        request,
                        result="failed",
                    )
                if round_state is not None and round_log is not None:
                    self._record_self_explosion_decision(
                        action_log=action_log,
                        round_state=round_state,
                        round_log=round_log,
                        cursor=pending.cursor,
                    )
                continue
            future.cancel()
            action_log = self._canceled_player_action_log(
                request,
                started_at=pending.started_at,
            )
            action_log.reason_code = (
                "phase_advanced" if reason != "canceled_terminal" else "terminal"
            )
            action_log.effective_origin = "none"
            if round_state is not None and round_log is not None:
                self._record_self_explosion_decision(
                    action_log=action_log,
                    round_state=round_state,
                    round_log=round_log,
                    cursor=pending.cursor,
                    audit_execution_status=(
                        "canceled" if reason == "canceled_terminal" else reason
                    ),
                )
            self._record_synthetic_logical_action(
                action_log,
                request,
                result="canceled",
            )

    def _shutdown_self_explosion_worker(self) -> None:
        self._cancel_pending_self_explosion(
            reason=("canceled_terminal" if self.state.winner else "superseded")
        )
        executor = self._self_explosion_executor
        self._self_explosion_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _self_explosion_decision_context(
        self,
        *,
        actor: str,
        round_state: RoundState,
        active_players: list[str],
        active_wolves: list[str],
        cursor: PublicStageCursor,
    ) -> SelfExplosionDecisionContext:
        prior_rounds = [
            existing for existing in self.state.rounds if existing.number < round_state.number
        ]
        total_self_explosions = sum(
            existing.werewolf_self_exploded is not None for existing in prior_rounds
        )
        explosions_by_round = {
            existing.number: existing.werewolf_self_exploded is not None
            for existing in prior_rounds
        }
        consecutive_self_explosions = 0
        prior_number = round_state.number - 1
        while explosions_by_round.get(prior_number) is True:
            consecutive_self_explosions += 1
            prior_number -= 1

        speech_stage = cursor.stage in {
            "debate",
            "sheriff_speech",
            "sheriff_pk_speech",
            "exile_pk_speech",
        }
        active_after = [name for name in active_players if name != actor]
        return SelfExplosionDecisionContext(
            total_self_explosions=total_self_explosions,
            consecutive_self_explosion_rounds=consecutive_self_explosions,
            active_wolves_before=len(active_wolves),
            actor_is_last_wolf=len(active_wolves) == 1 and actor in active_wolves,
            active_players_before=len(active_players),
            current_stage=cursor.stage,
            completed_public_speakers=(len(cursor.completed_actors) if speech_stage else 0),
            pending_public_speakers=(len(cursor.pending_actors) if speech_stage else 0),
            sheriff_election_open=self._should_run_sheriff_election(round_state),
            pre_election_bomb_count=self.state.sheriff_pre_election_bomb_count,
            badge_impact=self._self_explosion_badge_impact(actor, round_state),
            explosion_would_end_game=bool(self._get_winner(active_after)),
        )

    def _self_explosion_badge_impact(
        self,
        actor: str,
        round_state: RoundState,
    ) -> str:
        if not self.rule_set.sheriff_enabled:
            return "none"
        if self.state.sheriff == actor:
            return "owner_must_transfer_or_destroy"
        if self.state.sheriff:
            return "none"
        if not self._should_run_sheriff_election(round_state):
            return "none"
        if self.rule_set.sheriff_badge_bomb_policy == "double":
            if self.state.sheriff_pre_election_bomb_count >= 1:
                return "badge_will_be_lost"
            return "election_postponed"
        return "election_interrupted"

    def _stage_interruption_from_cursor(
        self,
        cursor: PublicStageCursor,
        *,
        actor: str,
    ) -> StageInterruption:
        speech_stages = {
            "debate",
            "sheriff_speech",
            "sheriff_pk_speech",
            "exile_pk_speech",
        }
        last_completed_speaker = (
            cursor.completed_actors[-1]
            if cursor.stage in speech_stages and cursor.completed_actors
            else None
        )
        return StageInterruption(
            stage=cursor.stage,
            interrupted_by="werewolf_self_explosion",
            actor=actor,
            timing=cursor.timing,
            last_completed_speaker=last_completed_speaker,
            completed_actors=list(cursor.completed_actors),
            pending_actors=cursor.pending_actors,
        )

    def _stage_interruption_text(
        self,
        round_number: int,
        interruption: StageInterruption,
    ) -> str:
        stage_labels = {
            "debate": "白天发言",
            "sheriff_speech": "警上发言",
            "sheriff_withdraw": "退水",
            "sheriff_vote": "警下投票",
            "sheriff_pk_speech": "警长PK发言",
            "sheriff_runoff_vote": "二轮警下投票",
            "exile_pk_speech": "放逐PK发言",
            "exile_runoff_vote": "放逐二轮投票",
        }
        label = stage_labels.get(interruption.stage, interruption.stage)
        parts = [f"第{round_number}轮{label}因{interruption.actor}自爆而中断"]
        is_speech = interruption.stage in {
            "debate",
            "sheriff_speech",
            "sheriff_pk_speech",
            "exile_pk_speech",
        }
        if interruption.completed_actors:
            completed_label = "已完成发言" if is_speech else "已完成动作"
            parts.append(f"{completed_label}：{'、'.join(interruption.completed_actors)}")
        if interruption.pending_actors:
            if is_speech:
                parts.append(
                    f"{'、'.join(interruption.pending_actors)}尚未获得发言机会，"
                    "不能将其视为主动沉默"
                )
            else:
                parts.append(f"尚未完成动作：{'、'.join(interruption.pending_actors)}")
        return "；".join(parts) + "。"

    def _self_explosion_stage_description(self, cursor: PublicStageCursor) -> str:
        stage_labels = {
            "debate": "发言",
            "sheriff_speech": "警上发言",
            "sheriff_withdraw": "退水",
            "sheriff_vote": "警下投票",
            "sheriff_pk_speech": "PK 发言",
            "sheriff_runoff_vote": "二轮警下投票",
            "exile_pk_speech": "放逐 PK 发言",
            "exile_runoff_vote": "放逐二轮投票",
        }
        label = stage_labels.get(cursor.stage, cursor.stage)
        if cursor.timing == "before_actor" and cursor.current_actor:
            return f"{cursor.current_actor} {label}前"
        if cursor.timing == "after_actor" and cursor.current_actor:
            return f"{cursor.current_actor} {label}后"
        return f"{label}前"

    def _public_stage_phase(self, cursor: PublicStageCursor) -> str:
        if cursor.stage.startswith("sheriff_"):
            return "sheriff_election"
        if cursor.stage.startswith("exile_"):
            return "vote"
        return "day"

    def _resolve_werewolf_self_explosion(
        self,
        *,
        wolf: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        phase: str = "day",
    ) -> None:
        players_by_name = self.state.player_by_name()
        players_by_name[wolf].revealed_role = True
        round_state.werewolf_self_exploded = wolf
        round_state.day_ended_by_self_explosion = True
        round_state.day_deaths.append(DeathEvent(wolf, "werewolf_self_explosion", wolf))
        self._append_public_outcome(
            round_state=round_state,
            kind="self_explosion",
            actor_player=wolf,
            outcome="self_exploded",
            phase="day",
        )
        self._remove_player(active_players, wolf)
        self._announce(
            active_players, f"第{round_state.number}轮：{wolf}自爆为狼人，白天立即结束。"
        )
        self._add_public_fact(
            round_state.number,
            "reveal",
            f"第{round_state.number}轮：{wolf}自爆为狼人，白天立即结束。",
            stage="werewolf_self_explosion",
            actor=wolf,
            retention="critical",
            details={"player": wolf},
        )

        terminal_candidate = bool(self._get_winner(active_players))
        if terminal_candidate and not self._has_unsettled_deferred_night_deaths:
            self._begin_terminal_settlement(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                primary_actor=wolf,
            )
        if terminal_candidate and self._has_unsettled_deferred_night_deaths:
            return
        if terminal_candidate and self._commit_terminal_winner(active_players, round_state):
            return

        if self.state.sheriff == wolf:
            self._maybe_transfer_sheriff_badge(
                dead_player=wolf,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase=phase,
            )
            return

        if self.state.sheriff or self.state.sheriff_badge_lost:
            return

        self.state.sheriff_pre_election_bomb_count += 1
        round_state.sheriff_pre_election_bomb_count = self.state.sheriff_pre_election_bomb_count
        if (
            self.rule_set.sheriff_badge_bomb_policy == "double"
            and self.state.sheriff_pre_election_bomb_count >= 2
        ):
            round_state.sheriff_badge_lost_reason = SHERIFF_BADGE_LOST_DOUBLE_BOMB
            self.state.sheriff_election_pending = False
            round_state.sheriff_election_pending = False
            self._lose_sheriff_badge(
                round_state,
                active_players,
                "double_pre_election_self_explosion",
            )
            return

        self._resolve_sheriff_election(
            round_state,
            active_players,
            outcome="postponed",
            reason_code="first_pre_election_self_explosion",
        )

    def _run_sheriff_election_if_needed(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        next_phase: str = "day",
    ) -> bool:
        if not self._should_run_sheriff_election(round_state):
            round_state.sheriff = self.state.sheriff
            return False
        self._start_phase(
            round_number=round_state.number,
            phase="sheriff_election",
            payload={"active_players": active_players.copy()},
        )
        try:
            interrupted = self._run_sheriff_election_core(
                round_state,
                round_log,
                active_players,
            )
        except BaseException:
            self._complete_phase(
                round_number=round_state.number,
                phase="sheriff_election",
                completion_status="canceled",
                completion_reason="forced_failure",
                next_phase=None,
                terminal=bool(self._get_winner(active_players)),
            )
            raise
        self._complete_phase(
            round_number=round_state.number,
            phase="sheriff_election",
            completion_status="canceled" if interrupted else "completed",
            completion_reason=("self_explosion" if interrupted else "election_resolved"),
            next_phase=next_phase,
            terminal=False,
        )
        return interrupted

    def _run_sheriff_election_core(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> bool:
        round_state.sheriff = self.state.sheriff
        if not self._should_run_sheriff_election(round_state):
            return False

        self._publish_judge_cue(
            round_state,
            "sheriff_election",
            cue_spec(
                "sheriff_raise_hands",
                static_asset_id="sheriff_raise_hands",
            ),
        )
        players_by_name = self.state.player_by_name()
        candidates: list[str] = []
        voters: list[str] = []
        run_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_SHERIFF_RUN,
                options=[SHERIFF_RUN, SHERIFF_SKIP],
                result_key="run",
                round_state=round_state,
                phase="sheriff_election",
            )
            for name in active_players
        ]
        for name, (run_choice, action_log) in zip(
            active_players,
            self._player_actions_batch(run_requests),
            strict=True,
        ):
            round_log.sheriff_run.append(action_log)
            if run_choice == SHERIFF_RUN:
                candidates.append(name)
            else:
                voters.append(name)

        round_state.sheriff_candidates = candidates
        round_state.sheriff_voters = voters
        if not candidates:
            round_state.sheriff_final_candidates = []
            self._lose_sheriff_badge(round_state, active_players, "no_candidates")
            return False

        sheriff_speech_order = self._choose_sheriff_speech_order(
            round_state,
            active_players,
            candidates,
        )
        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_speech",
                ordered_actors=tuple(sheriff_speech_order),
                timing="before_stage",
            ),
        ):
            return True

        completed_sheriff_speakers: list[str] = []
        for name in sheriff_speech_order:
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="sheriff_speech",
                    ordered_actors=tuple(sheriff_speech_order),
                    completed_actors=tuple(completed_sheriff_speakers),
                    current_actor=name,
                    timing="before_actor",
                ),
            ):
                return True
            action_result = self._interruptible_public_speech_action(
                player=players_by_name[name],
                action=ACTION_SHERIFF_SPEECH,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="sheriff_election",
                cursor=PublicStageCursor(
                    stage="sheriff_speech",
                    ordered_actors=tuple(sheriff_speech_order),
                    completed_actors=tuple(completed_sheriff_speakers),
                    current_actor=name,
                    timing="before_actor",
                ),
            )
            if action_result is None:
                return True
            message, action_log = action_result
            round_log.sheriff_speech.append(action_log)
            if not isinstance(message, str) or not message:
                completed_sheriff_speakers.append(name)
                if self._maybe_run_werewolf_self_explosion(
                    round_state,
                    round_log,
                    active_players,
                    PublicStageCursor(
                        stage="sheriff_speech",
                        ordered_actors=tuple(sheriff_speech_order),
                        completed_actors=tuple(completed_sheriff_speakers),
                        current_actor=name,
                        timing="after_actor",
                    ),
                ):
                    return True
                continue
            round_state.sheriff_speeches.append({"speaker": name, "message": message})
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="sheriff_election",
                actor=name,
                action=ACTION_SHERIFF_SPEECH,
                text=message,
            )
            self._add_public_fact(
                round_state.number,
                "claim",
                f"第{round_state.number}轮警上发言：{name}：{message}",
                stage="sheriff_speech",
                actor=name,
                retention="important",
            )
            completed_sheriff_speakers.append(name)
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="sheriff_speech",
                    ordered_actors=tuple(sheriff_speech_order),
                    completed_actors=tuple(completed_sheriff_speakers),
                    current_actor=name,
                    timing="after_actor",
                ),
            ):
                return True

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_withdraw",
                ordered_actors=tuple(candidates),
                timing="before_stage",
            ),
        ):
            return True

        withdrawn: list[str] = []
        withdraw_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_SHERIFF_WITHDRAW,
                options=[SHERIFF_WITHDRAW, SHERIFF_STAY],
                result_key="withdraw",
                round_state=round_state,
                phase="sheriff_election",
            )
            for name in candidates
        ]
        for name, (withdraw_choice, action_log) in zip(
            candidates,
            self._player_actions_batch(withdraw_requests),
            strict=True,
        ):
            round_log.sheriff_withdraw.append(action_log)
            if withdraw_choice == SHERIFF_WITHDRAW:
                withdrawn.append(name)

        round_state.sheriff_withdrawn = withdrawn
        final_candidates = [name for name in candidates if name not in set(withdrawn)]
        round_state.sheriff_final_candidates = final_candidates

        if not final_candidates:
            self._lose_sheriff_badge(
                round_state,
                active_players,
                "all_candidates_withdrew",
            )
            return False

        if len(final_candidates) == 1:
            self._elect_sheriff(
                final_candidates[0],
                round_state,
                active_players,
                reason_code="single_candidate",
            )
            return False

        if not voters:
            self._lose_sheriff_badge(
                round_state,
                active_players,
                "no_off_sheriff_voters",
            )
            return False

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_vote",
                ordered_actors=tuple(voters),
                timing="before_stage",
            ),
        ):
            return True

        vote_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_SHERIFF_VOTE,
                options=final_candidates,
                result_key="sheriff_vote",
                round_state=round_state,
                phase="sheriff_election",
            )
            for name in voters
        ]
        for name, (vote, action_log) in zip(
            voters,
            self._player_actions_batch(vote_requests),
            strict=True,
        ):
            round_log.sheriff_votes.append(action_log)
            if isinstance(vote, str) and vote in final_candidates:
                round_state.sheriff_votes[name] = vote
        round_state.sheriff_vote_origins = _vote_origins(round_log.sheriff_votes)
        if round_state.sheriff_votes:
            self._add_public_fact(
                round_state.number,
                "vote",
                f"第{round_state.number}轮警长票型："
                + "；".join(
                    _public_vote_line(
                        voter,
                        target,
                        round_state.sheriff_vote_origins.get(voter),
                    )
                    for voter, target in round_state.sheriff_votes.items()
                ),
                stage="sheriff_vote",
                retention="important",
                details={
                    "votes": round_state.sheriff_votes.copy(),
                    "vote_origins": copy.deepcopy(
                        round_state.sheriff_vote_origins
                    ),
                },
            )

        first_round_winners = self._plurality_winners(round_state.sheriff_votes)
        if not first_round_winners:
            self._lose_sheriff_badge(round_state, active_players, "first_vote_empty")
            return False

        if len(first_round_winners) == 1:
            self._elect_sheriff(
                first_round_winners[0],
                round_state,
                active_players,
                reason_code="first_vote_winner",
            )
            return False

        tied_candidates = set(first_round_winners)
        pk_candidates = [name for name in final_candidates if name in tied_candidates]
        round_state.sheriff_pk_candidates = pk_candidates
        self._publish_state_updated(
            round_state=round_state,
            phase="sheriff_election",
            action="sheriff_pk_started",
            payload={
                "narration_mode": "explicit_v1",
                "sheriff_pk_candidates": pk_candidates.copy(),
                "sheriff_voters": round_state.sheriff_voters.copy(),
                "sheriff_votes": round_state.sheriff_votes.copy(),
                "sheriff_vote_origins": copy.deepcopy(
                    round_state.sheriff_vote_origins
                ),
            },
        )
        tie_cues = sheriff_tie_cues([self._public_player_reference(name) for name in pk_candidates])
        self._publish_judge_cues(round_state, "sheriff_election", tie_cues[:2])

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_pk_speech",
                ordered_actors=tuple(pk_candidates),
                timing="before_stage",
            ),
        ):
            return True

        completed_pk_speakers: list[str] = []
        for name in pk_candidates:
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="sheriff_pk_speech",
                    ordered_actors=tuple(pk_candidates),
                    completed_actors=tuple(completed_pk_speakers),
                    current_actor=name,
                    timing="before_actor",
                ),
            ):
                return True
            action_result = self._interruptible_public_speech_action(
                player=players_by_name[name],
                action=ACTION_SHERIFF_PK_SPEECH,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="sheriff_election",
                cursor=PublicStageCursor(
                    stage="sheriff_pk_speech",
                    ordered_actors=tuple(pk_candidates),
                    completed_actors=tuple(completed_pk_speakers),
                    current_actor=name,
                    timing="before_actor",
                ),
            )
            if action_result is None:
                return True
            message, action_log = action_result
            round_log.sheriff_pk_speech.append(action_log)
            if not isinstance(message, str) or not message:
                completed_pk_speakers.append(name)
                if self._maybe_run_werewolf_self_explosion(
                    round_state,
                    round_log,
                    active_players,
                    PublicStageCursor(
                        stage="sheriff_pk_speech",
                        ordered_actors=tuple(pk_candidates),
                        completed_actors=tuple(completed_pk_speakers),
                        current_actor=name,
                        timing="after_actor",
                    ),
                ):
                    return True
                continue
            round_state.sheriff_pk_speeches.append({"speaker": name, "message": message})
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="sheriff_election",
                actor=name,
                action=ACTION_SHERIFF_PK_SPEECH,
                text=message,
            )
            self._add_public_fact(
                round_state.number,
                "claim",
                f"第{round_state.number}轮警长PK发言：{name}：{message}",
                stage="sheriff_pk_speech",
                actor=name,
                retention="critical",
            )
            completed_pk_speakers.append(name)
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="sheriff_pk_speech",
                    ordered_actors=tuple(pk_candidates),
                    completed_actors=tuple(completed_pk_speakers),
                    current_actor=name,
                    timing="after_actor",
                ),
            ):
                return True

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_runoff_vote",
                ordered_actors=tuple(voters),
                timing="before_stage",
            ),
        ):
            return True

        self._publish_judge_cue(round_state, "sheriff_election", tie_cues[2])

        runoff_vote_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_SHERIFF_RUNOFF_VOTE,
                options=pk_candidates,
                result_key="sheriff_vote",
                round_state=round_state,
                phase="sheriff_election",
            )
            for name in voters
        ]
        for name, (vote, action_log) in zip(
            voters,
            self._player_actions_batch(runoff_vote_requests),
            strict=True,
        ):
            round_log.sheriff_runoff_votes.append(action_log)
            if isinstance(vote, str) and vote in pk_candidates:
                round_state.sheriff_runoff_votes[name] = vote
        round_state.sheriff_runoff_vote_origins = _vote_origins(
            round_log.sheriff_runoff_votes
        )
        if round_state.sheriff_runoff_votes:
            self._add_public_fact(
                round_state.number,
                "vote",
                f"第{round_state.number}轮警长PK票型："
                + "；".join(
                    _public_vote_line(
                        voter,
                        target,
                        round_state.sheriff_runoff_vote_origins.get(voter),
                    )
                    for voter, target in round_state.sheriff_runoff_votes.items()
                ),
                stage="sheriff_runoff_vote",
                retention="important",
                details={
                    "votes": round_state.sheriff_runoff_votes.copy(),
                    "vote_origins": copy.deepcopy(
                        round_state.sheriff_runoff_vote_origins
                    ),
                },
            )

        sheriff = self._plurality_winner(round_state.sheriff_runoff_votes)
        if sheriff is None:
            self._lose_sheriff_badge(round_state, active_players, "runoff_tied")
            return False

        self._elect_sheriff(
            sheriff,
            round_state,
            active_players,
            reason_code="runoff_vote_winner",
        )
        return False

    def _should_run_sheriff_election(self, round_state: RoundState) -> bool:
        return (
            self.rule_set.sheriff_enabled
            and not self.state.sheriff
            and not self.state.sheriff_badge_lost
            and (round_state.number == 1 or self.state.sheriff_election_pending)
        )

    def _choose_sheriff_speech_order(
        self,
        round_state: RoundState,
        active_players: list[str],
        candidates: list[str],
    ) -> list[str]:
        if len(candidates) <= 1:
            round_state.sheriff_speech_order = candidates.copy()
            round_state.sheriff_speech_direction = None
            return candidates.copy()

        start = candidates[self.rng.randrange(len(candidates))]
        direction = self.rng.choice([SHERIFF_SPEECH_CLOCKWISE, SHERIFF_SPEECH_COUNTERCLOCKWISE])
        seated_players = (
            list(reversed(active_players))
            if direction == SHERIFF_SPEECH_COUNTERCLOCKWISE
            else active_players.copy()
        )
        start_index = seated_players.index(start)
        rotated_players = seated_players[start_index:] + seated_players[:start_index]
        candidate_names = set(candidates)
        speech_order = [name for name in rotated_players if name in candidate_names]
        round_state.sheriff_speech_order = speech_order
        round_state.sheriff_speech_direction = direction
        return speech_order

    def _elect_sheriff(
        self,
        sheriff: str,
        round_state: RoundState,
        active_players: list[str],
        *,
        reason_code: SheriffElectionReason,
    ) -> None:
        self._resolve_sheriff_election(
            round_state,
            active_players,
            outcome="elected",
            reason_code=reason_code,
            sheriff=sheriff,
        )

    def _lose_sheriff_badge(
        self,
        round_state: RoundState,
        active_players: list[str],
        reason_code: SheriffElectionReason,
    ) -> None:
        self._resolve_sheriff_election(
            round_state,
            active_players,
            outcome="badge_lost",
            reason_code=reason_code,
        )

    def _resolve_sheriff_election(
        self,
        round_state: RoundState,
        active_players: list[str],
        *,
        outcome: SheriffElectionOutcome,
        reason_code: SheriffElectionReason,
        sheriff: str | None = None,
    ) -> None:
        reason_text = SHERIFF_ELECTION_REASON_TEXT[reason_code]
        badge_lost = outcome == "badge_lost"
        election_pending = outcome == "postponed"
        self._set_sheriff(sheriff if outcome == "elected" else None)
        self.state.sheriff_badge_lost = badge_lost
        self.state.sheriff_election_pending = election_pending
        round_state.sheriff = sheriff if outcome == "elected" else None
        round_state.sheriff_elected = sheriff if outcome == "elected" else None
        round_state.sheriff_badge_lost = badge_lost
        round_state.sheriff_election_pending = election_pending
        round_state.sheriff_badge_lost_reason = reason_text if outcome != "elected" else None
        resolution = SheriffElectionResolution(
            schema_version=1,
            outcome=outcome,
            reason_code=reason_code,
            reason_text=reason_text,
            sheriff=sheriff if outcome == "elected" else None,
            candidates=round_state.sheriff_candidates.copy(),
            withdrawn=round_state.sheriff_withdrawn.copy(),
            final_candidates=round_state.sheriff_final_candidates.copy(),
            voters=round_state.sheriff_voters.copy(),
            votes=round_state.sheriff_votes.copy(),
            pk_candidates=round_state.sheriff_pk_candidates.copy(),
            runoff_votes=round_state.sheriff_runoff_votes.copy(),
            badge_lost=badge_lost,
            election_pending=election_pending,
        )
        round_state.sheriff_election_resolution = resolution
        public_outcome: PublicOutcomeEventV1 | None = None
        if outcome == "elected" and sheriff:
            public_outcome = self._append_public_outcome(
                round_state=round_state,
                kind="badge_transferred",
                target_player=sheriff,
                outcome="elected",
                phase="day",
            )
        elif outcome == "badge_lost":
            public_outcome = self._append_public_outcome(
                round_state=round_state,
                kind="badge_lost",
                outcome=reason_code,
                phase="day",
                caused_by_event=(
                    round_state.public_outcome_events[-1]
                    if reason_code == "double_pre_election_self_explosion"
                    and round_state.public_outcome_events
                    and round_state.public_outcome_events[-1].kind == "self_explosion"
                    else None
                ),
            )
        if outcome == "elected":
            text = (
                f"第{round_state.number}轮：警长竞选，{sheriff}当选警长，"
                f"投票计为{self.rule_set.sheriff_vote_weight:g}票。"
            )
            stage = "sheriff_elected"
            details: dict[str, object] = {
                "sheriff": sheriff,
                "vote_weight": self.rule_set.sheriff_vote_weight,
                "reason_code": reason_code,
            }
        elif outcome == "postponed":
            text = f"第{round_state.number}轮：{reason_text}，警长竞选顺延。"
            stage = "sheriff_election_postponed"
            details = {"reason": reason_text, "reason_code": reason_code}
        else:
            text = f"第{round_state.number}轮：{reason_text}，警徽流失。"
            stage = "sheriff_badge_lost"
            details = {"reason": reason_text, "reason_code": reason_code}
        self._announce(active_players, text)
        self._add_public_fact(
            round_state.number,
            "sheriff",
            text,
            stage=stage,
            actor=sheriff,
            retention="critical",
            details=details,
        )
        self._publish_state_updated(
            round_state=round_state,
            phase="sheriff_election",
            actor=sheriff,
            action="sheriff_election_resolved",
            payload={
                "narration_mode": "explicit_v1",
                "sheriff_election": resolution.to_dict(),
                "sheriff": resolution.sheriff,
                "sheriff_elected": resolution.sheriff,
                "sheriff_candidates": resolution.candidates.copy(),
                "sheriff_final_candidates": resolution.final_candidates.copy(),
                "sheriff_voters": resolution.voters.copy(),
                "sheriff_votes": resolution.votes.copy(),
                "sheriff_vote_origins": copy.deepcopy(
                    round_state.sheriff_vote_origins
                ),
                "sheriff_runoff_votes": resolution.runoff_votes.copy(),
                "sheriff_runoff_vote_origins": copy.deepcopy(
                    round_state.sheriff_runoff_vote_origins
                ),
                "sheriff_badge_lost": resolution.badge_lost,
                "sheriff_badge_lost_reason": round_state.sheriff_badge_lost_reason,
                "sheriff_election_pending": resolution.election_pending,
                "active_players": active_players.copy(),
            },
        )
        public_resolution = SheriffElectionResolution(
            **{
                **resolution.to_dict(),
                "sheriff": (
                    public_outcome.target_player_id
                    if public_outcome and public_outcome.kind == "badge_transferred"
                    else None
                ),
                "candidates": [
                    self._public_player_reference(name) for name in resolution.candidates
                ],
                "withdrawn": [self._public_player_reference(name) for name in resolution.withdrawn],
                "final_candidates": [
                    self._public_player_reference(name) for name in resolution.final_candidates
                ],
                "voters": [self._public_player_reference(name) for name in resolution.voters],
                "votes": {
                    self._public_player_reference(voter): self._public_player_reference(target)
                    for voter, target in resolution.votes.items()
                },
                "pk_candidates": [
                    self._public_player_reference(name) for name in resolution.pk_candidates
                ],
                "runoff_votes": {
                    self._public_player_reference(voter): self._public_player_reference(target)
                    for voter, target in resolution.runoff_votes.items()
                },
            }
        )
        self._publish_judge_cues(
            round_state,
            "sheriff_election",
            sheriff_election_cues(public_resolution),
        )

    def _sheriff_directed_speech_order(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> list[str]:
        sheriff = self.state.sheriff
        if sheriff not in active_players:
            return active_players.copy()

        players_by_name = self.state.player_by_name()
        choice, action_log = self._player_action(
            player=players_by_name[sheriff],
            action=ACTION_SPEECH_ORDER,
            options=[SPEECH_FROM_LEFT, SPEECH_FROM_RIGHT],
            result_key="speech_order",
            round_state=round_state,
            phase="day",
        )
        round_log.speech_order = action_log
        round_state.speech_order_choice = str(choice) if choice else None

        sheriff_index = active_players.index(sheriff)
        before_sheriff = active_players[:sheriff_index]
        after_sheriff = active_players[sheriff_index + 1 :]
        if choice == SPEECH_FROM_RIGHT:
            return list(reversed(before_sheriff)) + list(reversed(after_sheriff)) + [sheriff]
        return after_sheriff + before_sheriff + [sheriff]

    def _plurality_winner(self, votes: dict[str, str]) -> str | None:
        winners = self._plurality_winners(votes)
        return winners[0] if len(winners) == 1 else None

    def _plurality_winners(self, votes: dict[str, str]) -> list[str]:
        if not votes:
            return []
        tally = Counter(votes.values())
        top_count = max(tally.values())
        return [name for name, count in tally.items() if count == top_count]

    def _set_sheriff(self, sheriff: str | None) -> None:
        players_by_name = self.state.player_by_name()
        for player in players_by_name.values():
            player.is_sheriff = player.name == sheriff
        self.state.sheriff = sheriff
        if sheriff:
            self.state.sheriff_badge_lost = False

    def _run_voting(
        self,
        round_state: RoundState,
        active_players: list[str],
    ) -> tuple[dict[str, str], list[ActionLog]]:
        votes: dict[str, str] = {}
        logs: list[ActionLog] = []
        players_by_name = self.state.player_by_name()
        voters = self._eligible_voters(active_players)
        vote_requests = [
            self._build_player_action_request(
                player=players_by_name[voter],
                action="vote",
                options=[name for name in active_players if name != voter],
                result_key="vote",
                round_state=round_state,
                phase="vote",
            )
            for voter in voters
        ]
        for voter, (vote, action_log) in zip(
            voters,
            self._player_actions_batch(vote_requests),
            strict=True,
        ):
            if not isinstance(vote, str) or not vote:
                raise ValueError(f"{voter} did not return a valid vote.")
            votes[voter] = vote
            round_state.vote_weights[voter] = self._vote_weight(voter)
            logs.append(action_log)
        return votes, logs

    def _run_exile_vote_resolution(
        self,
        votes: dict[str, str],
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> bool:
        winners = self._weighted_plurality_winners(
            votes,
            round_state.vote_weights,
            active_players,
        )
        if not winners:
            self._record_no_exile(
                round_state,
                active_players,
                reason_code="no_valid_votes",
            )
            return False
        if len(winners) == 1:
            round_state.exile_resolution_reason = "first_vote_winner"
            self._resolve_day_exile(winners[0], round_state, round_log, active_players)
            return False

        pk_candidates = winners
        round_state.exile_pk_candidates = pk_candidates.copy()
        round_state.exile_resolution_reason = "first_vote_tied"
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            action="exile_pk_started",
            payload={
                "narration_mode": "explicit_v1",
                "exile_pk_candidates": pk_candidates.copy(),
                "votes": votes.copy(),
                "vote_weights": round_state.vote_weights.copy(),
                "exile_resolution_reason": round_state.exile_resolution_reason,
                "active_players": active_players.copy(),
            },
        )
        public_pk_candidates = [
            self._public_player_reference(name) for name in pk_candidates
        ]
        tie_cues = exile_tie_cues(public_pk_candidates)
        self._publish_judge_cues(round_state, "vote", tie_cues[:2])
        self._self_explosion_locked = False

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="exile_pk_speech",
                ordered_actors=tuple(pk_candidates),
                timing="before_stage",
            ),
        ):
            return True

        players_by_name = self.state.player_by_name()
        completed_pk_speakers: list[str] = []
        for name in pk_candidates:
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="exile_pk_speech",
                    ordered_actors=tuple(pk_candidates),
                    completed_actors=tuple(completed_pk_speakers),
                    current_actor=name,
                    timing="before_actor",
                ),
            ):
                return True
            action_result = self._interruptible_public_speech_action(
                player=players_by_name[name],
                action=ACTION_EXILE_PK_SPEECH,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="vote",
                cursor=PublicStageCursor(
                    stage="exile_pk_speech",
                    ordered_actors=tuple(pk_candidates),
                    completed_actors=tuple(completed_pk_speakers),
                    current_actor=name,
                    timing="before_actor",
                ),
            )
            if action_result is None:
                return True
            message, action_log = action_result
            round_log.exile_pk_speech.append(action_log)
            if not isinstance(message, str) or not message:
                completed_pk_speakers.append(name)
                if self._maybe_run_werewolf_self_explosion(
                    round_state,
                    round_log,
                    active_players,
                    PublicStageCursor(
                        stage="exile_pk_speech",
                        ordered_actors=tuple(pk_candidates),
                        completed_actors=tuple(completed_pk_speakers),
                        current_actor=name,
                        timing="after_actor",
                    ),
                ):
                    return True
                continue
            round_state.exile_pk_speeches.append({"speaker": name, "message": message})
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="vote",
                actor=name,
                action=ACTION_EXILE_PK_SPEECH,
                text=message,
            )
            self._add_public_fact(
                round_state.number,
                "claim",
                f"第{round_state.number}轮放逐PK发言：{name}：{message}",
                stage="exile_pk_speech",
                actor=name,
                retention="critical",
            )
            completed_pk_speakers.append(name)
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="exile_pk_speech",
                    ordered_actors=tuple(pk_candidates),
                    completed_actors=tuple(completed_pk_speakers),
                    current_actor=name,
                    timing="after_actor",
                ),
            ):
                return True

        runoff_voters = [
            name
            for name in self._eligible_voters(active_players)
            if name not in set(pk_candidates)
        ]
        self._cancel_pending_self_explosion()
        self._self_explosion_locked = True
        if not runoff_voters:
            self._record_no_exile(
                round_state,
                active_players,
                reason_code="no_runoff_voters",
            )
            return False

        self._publish_judge_cue(round_state, "vote", tie_cues[2])
        runoff_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_EXILE_RUNOFF_VOTE,
                options=pk_candidates,
                result_key="vote",
                round_state=round_state,
                phase="vote",
            )
            for name in runoff_voters
        ]
        for name, (vote, action_log) in zip(
            runoff_voters,
            self._player_actions_batch(runoff_requests),
            strict=True,
        ):
            if not isinstance(vote, str) or vote not in pk_candidates:
                raise ValueError(f"{name} did not return a valid exile runoff vote.")
            round_state.exile_runoff_votes[name] = vote
            round_log.exile_runoff_votes.append(action_log)

        round_state.exile_runoff_vote_origins = _vote_origins(
            round_log.exile_runoff_votes
        )

        self._add_public_fact(
            round_state.number,
            "vote",
            f"第{round_state.number}轮放逐PK票型："
            + "；".join(
                _public_vote_line(
                    voter,
                    target,
                    round_state.exile_runoff_vote_origins.get(voter),
                )
                for voter, target in round_state.exile_runoff_votes.items()
            ),
            stage="exile_runoff_vote",
            retention="important",
            details={
                "votes": round_state.exile_runoff_votes.copy(),
                "vote_origins": copy.deepcopy(
                    round_state.exile_runoff_vote_origins
                ),
            },
        )
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            action="exile_runoff_vote",
            payload={
                "narration_mode": "explicit_v1",
                "exile_pk_candidates": pk_candidates.copy(),
                "exile_pk_speeches": copy.deepcopy(round_state.exile_pk_speeches),
                "exile_runoff_votes": round_state.exile_runoff_votes.copy(),
                "exile_runoff_vote_origins": copy.deepcopy(
                    round_state.exile_runoff_vote_origins
                ),
                "vote_weights": round_state.vote_weights.copy(),
                "active_players": active_players.copy(),
            },
        )

        runoff_winners = self._weighted_plurality_winners(
            round_state.exile_runoff_votes,
            round_state.vote_weights,
            pk_candidates,
        )
        if len(runoff_winners) == 1:
            round_state.exile_resolution_reason = "runoff_vote_winner"
            self._resolve_day_exile(
                runoff_winners[0],
                round_state,
                round_log,
                active_players,
            )
            return False

        round_state.exile_resolution_reason = "runoff_tied"
        self._announce(
            active_players,
            f"第{round_state.number}轮：放逐二轮投票仍为平票，无人被放逐。",
        )
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            action="exile_runoff_tied",
            payload={
                "narration_mode": "explicit_v1",
                "exile_pk_candidates": pk_candidates.copy(),
                "exile_runoff_votes": round_state.exile_runoff_votes.copy(),
                "exile_runoff_vote_origins": copy.deepcopy(
                    round_state.exile_runoff_vote_origins
                ),
                "exile_resolution_reason": round_state.exile_resolution_reason,
                "active_players": active_players.copy(),
            },
        )
        self._publish_judge_cue(
            round_state,
            "vote",
            exile_runoff_tied_cue(public_pk_candidates),
        )
        return False

    def _record_no_exile(
        self,
        round_state: RoundState,
        active_players: list[str],
        *,
        reason_code: str,
    ) -> None:
        round_state.exile_resolution_reason = reason_code
        if reason_code == "no_runoff_voters":
            message = "放逐PK没有可参与二轮投票的玩家，无人被放逐。"
        else:
            message = "白天没有形成有效放逐票，无人被放逐。"
        self._announce(active_players, f"第{round_state.number}轮：{message}")
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            action="exile_no_result",
            payload={
                "narration_mode": "explicit_v1",
                "exile_pk_candidates": round_state.exile_pk_candidates.copy(),
                "exile_pk_speeches": copy.deepcopy(round_state.exile_pk_speeches),
                "exile_runoff_votes": round_state.exile_runoff_votes.copy(),
                "exile_runoff_vote_origins": copy.deepcopy(
                    round_state.exile_runoff_vote_origins
                ),
                "vote_origins": copy.deepcopy(round_state.vote_origins),
                "exile_resolution_reason": reason_code,
                "active_players": active_players.copy(),
            },
        )
        self._publish_judge_cue(
            round_state,
            "vote",
            exile_no_result_cue(reason_code),
        )

    def _weighted_plurality_winners(
        self,
        votes: dict[str, str],
        vote_weights: dict[str, float],
        candidate_order: list[str],
    ) -> list[str]:
        if not votes:
            return []
        candidates = set(candidate_order)
        tally: dict[str, float] = {}
        for voter, target in votes.items():
            if target not in candidates:
                continue
            tally[target] = tally.get(target, 0.0) + vote_weights.get(voter, 1.0)
        if not tally:
            return []
        top_weight = max(tally.values())
        return [
            candidate
            for candidate in candidate_order
            if tally.get(candidate) == top_weight
        ]

    def _vote_weight(self, voter: str) -> float:
        if self.rule_set.sheriff_enabled and voter == self.state.sheriff:
            return self.rule_set.sheriff_vote_weight
        return 1.0

    def _resolve_day_exile(
        self,
        exiled: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        player = self.state.player_by_name()[exiled]
        if player.role == IDIOT and not player.revealed_role:
            player.revealed_role = True
            player.can_vote = False
            round_state.idiot_revealed = exiled
            idiot_outcome = self._append_public_outcome(
                round_state=round_state,
                kind="idiot_reveal",
                actor_player=exiled,
                outcome="survived",
                phase="vote",
            )
            self._announce(
                active_players,
                f"第{round_state.number}轮：白天投票，{exiled}翻开白痴身份，免于出局但失去投票权。",
            )
            self._publish_state_updated(
                round_state=round_state,
                phase="vote",
                actor=exiled,
                action="idiot_revealed",
                payload={
                    "narration_mode": "explicit_v1",
                    "idiot_revealed": exiled,
                    "active_players": active_players.copy(),
                },
            )
            self._publish_judge_cues(
                round_state,
                "vote",
                idiot_reveal_cues(idiot_outcome.actor_player_id or ""),
            )
            return

        round_state.exiled = exiled
        self._remove_player(active_players, exiled)
        round_state.day_deaths.append(DeathEvent(exiled, "vote_exile", "投票"))
        exile_outcome = self._append_public_outcome(
            round_state=round_state,
            kind="exile",
            target_player=exiled,
            outcome="eliminated",
            phase="vote",
        )
        exile_text = f"第{round_state.number}轮：白天投票，{exiled}被放逐。"
        self._announce(active_players, exile_text)
        self._add_public_fact(
            round_state.number,
            "death",
            exile_text,
            stage="vote_exile",
            actor=exiled,
            retention="critical",
            details={"player": exiled},
        )
        terminal_candidate = bool(self._get_winner(active_players))
        exile_deaths = [DeathEvent(exiled, "vote_exile", "投票")]
        hunter_contexts = self._hunter_settlement_contexts(
            exile_deaths,
            phase="vote",
            transfer_sheriff_badge=False,
        )
        hunter_may_make_terminal = self._hunter_death_chain_may_be_terminal(
            exile_deaths,
            active_players,
        )
        needs_terminal_presentation = terminal_candidate or hunter_may_make_terminal
        if needs_terminal_presentation:
            self._begin_terminal_settlement(
                round_state=round_state,
                active_players=active_players,
                phase="vote",
                primary_actor=exiled,
                hunter_contexts=hunter_contexts,
                continuation_kind="day_exile_aftermath",
                continuation_transfer_sheriff_badge=True,
                skip_exile_last_words=(
                    terminal_candidate
                    or not self.rule_set.exile_last_words_enabled
                ),
            )
        exile_payload: dict[str, object] = {
            "exiled": exiled,
            "day_deaths": [death.to_dict() for death in round_state.day_deaths],
            "active_players": active_players.copy(),
        }
        primary_presentation = self._terminal_primary_presentation(round_state)
        if needs_terminal_presentation and primary_presentation is not None:
            exile_payload["presentation_id"] = primary_presentation[
                "presentation_id"
            ]
        else:
            exile_payload["narration_mode"] = "explicit_v1"
        exile_result_event = self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            actor=exiled,
            action="exile_resolved",
            payload=exile_payload,
        )
        if needs_terminal_presentation:
            self._terminal_primary_event = exile_result_event
        if not terminal_candidate:
            if not needs_terminal_presentation:
                self._publish_judge_cue(
                    round_state,
                    "vote",
                    exile_result_cue(exile_outcome.target_player_id or ""),
                )
            self._run_exile_last_words(
                exiled=exiled,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
            )

        self._maybe_run_hunter_shot(
            dead_player=exiled,
            death_cause="vote_exile",
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
            phase="vote",
            transfer_sheriff_badge=False,
        )
        if self._commit_terminal_winner(active_players, round_state):
            self._remember_terminal_keep_event(exile_result_event)
            return

        for death in list(round_state.day_deaths):
            self._maybe_transfer_sheriff_badge(
                dead_player=death.player,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="vote",
            )
        self._complete_cleared_terminal_continuation(active_players)

    def _run_exile_last_words(
        self,
        *,
        exiled: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        if self.state.winner or self._get_winner(active_players):
            return
        if not self.rule_set.exile_last_words_enabled:
            return
        if round_state.exile_last_words is not None:
            return
        self._cancel_pending_self_explosion()
        public_player = self._public_player_reference(exiled)
        self._publish_judge_cue(
            round_state,
            "vote",
            exile_last_words_cue(public_player),
        )
        message: object | None = None
        action_log: ActionLog | None = None
        reason_code = "completed"
        try:
            message, action_log = self._player_action(
                player=self.state.player_by_name()[exiled],
                action=ACTION_EXILE_LAST_WORDS,
                options=[],
                result_key="say",
                round_state=round_state,
                phase="vote",
                extra_world_state={
                    "hard_state": {
                        "actor_alive": False,
                        "death_cause": "vote_exile",
                        "current_action": "驱逐遗言",
                    }
                },
            )
        except Exception:
            reason_code = "model_failure"
        if action_log is not None:
            round_log.exile_last_words = action_log
            reason_code = (
                action_log.fallback_reason
                or action_log.reason_code
                or reason_code
            )
        accepted_message = message.strip() if isinstance(message, str) else ""
        status = "completed" if accepted_message else "skipped"
        round_state.exile_last_words = {
            "player": exiled,
            "message": accepted_message,
            "status": status,
            "reason_code": reason_code,
        }
        if accepted_message:
            text = f"第{round_state.number}轮驱逐遗言：{exiled}：{accepted_message}"
            self._announce(active_players, text)
            self._add_public_fact(
                round_state.number,
                "claim",
                text,
                stage="exile_last_words",
                actor=exiled,
                retention="critical",
            )
        else:
            self._publish_judge_cue(
                round_state,
                "vote",
                exile_last_words_skipped_cue(public_player, reason_code),
            )
        # A potential hunter shot can make this exile terminal. Persist the
        # completed last words before publishing its result so either side of
        # the publish boundary recovers the same semantic presentation.
        self._persist_terminal_settlement(active_players)
        self._publish_terminal_exile_last_words_result(
            exiled=exiled,
            round_state=round_state,
            round_log=round_log,
            reemit_action_parsed=False,
        )

    def _publish_terminal_exile_last_words_result(
        self,
        *,
        exiled: str,
        round_state: RoundState,
        round_log: RoundLog,
        reemit_action_parsed: bool,
    ) -> None:
        if reemit_action_parsed and round_log.exile_last_words is not None:
            action_log = round_log.exile_last_words
            visible_result = _visible_action_result(
                ACTION_EXILE_LAST_WORDS,
                action_log.lm_log.result,
            )
            parsed_payload: dict[str, object] = {
                "action_id": action_log.lm_log.action_id,
                "request_id": action_log.lm_log.request_id,
                "choice": self._public_action_value(action_log.choice),
                "result": visible_result,
                "visible_result": visible_result,
                "options": [
                    self._public_player_reference(option)
                    for option in action_log.options
                ],
                "action_origin": _effective_action_origin(action_log),
                "public_reason_code": _public_action_reason_code(action_log),
                "speech_status": (
                    "not_spoken"
                    if action_log.execution_status == "failed"
                    else "spoken"
                ),
                "retry_completed": len(action_log.lm_log.attempt_outcomes) > 1
                or action_log.lm_log.speech_quality_attempt_count > 1,
            }
            if action_log.lm_log.speech_id is not None:
                receipt = action_log.lm_log.speech_turn_receipt
                stream_mode = (
                    receipt.get("speech_stream_mode")
                    if isinstance(receipt, dict)
                    else None
                )
                if stream_mode != "segments_v2":
                    raise RuntimeError("recovered speech receipt has invalid stream mode")
                segment_count = len(action_log.lm_log.committed_speech_segments)
                parsed_payload.update(
                    {
                        "schema_version": 1,
                        "speech_id": action_log.lm_log.speech_id,
                        "speech_stream_mode": stream_mode,
                        "segment_count": segment_count,
                        "final_segment_index": segment_count - 1,
                        "speech_status": (
                            "partial"
                            if receipt.get("status") == "partial"
                            else "interrupted"
                            if receipt.get("status") == "interrupted"
                            else "spoken"
                        ),
                        "tts_suppressed_by_segments": True,
                    }
                )
            if action_log.effective_delivery is not None:
                player = self.state.player_by_name()[exiled]
                parsed_payload["voice_snapshot"] = {
                    "enabled": player.voice_enabled,
                    "speaker": player.tts_speaker,
                    "effective_delivery": copy.deepcopy(
                        action_log.effective_delivery
                    ),
                    "effective_context_texts": (
                        action_log.effective_context_texts.copy()
                    ),
                    "voice_config_version": action_log.voice_config_version,
                    "delivery_mapping_version": action_log.delivery_mapping_version,
                }
            if action_log.fallback_choice is not None:
                parsed_payload.update(
                    {
                        "invalid_value": action_log.invalid_value,
                        "fallback_choice": self._public_action_value(
                            action_log.fallback_choice
                        ),
                        "fallback_reason": action_log.fallback_reason,
                        "attempt_count": action_log.attempt_count,
                    }
                )
            speech_presentation_id = (
                self._terminal_exile_last_words_presentation_id("speech")
            )
            if speech_presentation_id is not None:
                parsed_payload["presentation_id"] = speech_presentation_id
            self._publish(
                "action_parsed",
                round_number=round_state.number,
                phase="vote",
                actor=exiled,
                action=ACTION_EXILE_LAST_WORDS,
                payload=parsed_payload,
            )
        state_payload: dict[str, object] = {
            "exile_last_words": copy.deepcopy(round_state.exile_last_words)
        }
        state_presentation_id = self._terminal_exile_last_words_presentation_id(
            "state"
        )
        if state_presentation_id is not None:
            state_payload["presentation_id"] = state_presentation_id
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            actor=exiled,
            action=ACTION_EXILE_LAST_WORDS,
            payload=state_payload,
        )

    def _terminal_exile_last_words_presentation_id(
        self,
        channel: str,
    ) -> str | None:
        continuation = self._terminal_continuation()
        if (
            self._terminal_settlement is None
            or continuation is None
            or continuation.get("kind") != "day_exile_aftermath"
            or continuation.get("skip_exile_last_words") is not False
        ):
            return None
        primary_action_id = self._terminal_settlement.get(
            "primary_outcome_action_id"
        )
        if not isinstance(primary_action_id, str) or not primary_action_id:
            return None
        digest = hashlib.sha256(
            (
                f"{self.state.session_id}:{primary_action_id}:"
                f"exile_last_words:{channel}"
            ).encode()
        ).hexdigest()[:24]
        prefix = "lws" if channel == "speech" else "lwr"
        return f"{prefix}_{digest}"
    def _maybe_transfer_sheriff_badge(
        self,
        *,
        dead_player: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        phase: str,
        excluded_badge_targets: set[str] | None = None,
    ) -> None:
        if self.state.winner or self._get_winner(active_players):
            return
        if (
            not self.rule_set.sheriff_enabled
            or dead_player != self.state.sheriff
            or self.state.sheriff_badge_lost
            or dead_player in active_players
            or not self._is_recorded_round_death(dead_player, round_state)
        ):
            return

        self._publish_judge_cue(
            round_state,
            phase,
            cue_spec(
                "badge_owner_out",
                static_asset_id="badge_owner_out",
                params={"from_player": self._public_player_reference(dead_player)},
            ),
        )
        if not active_players:
            self._resolve_sheriff_badge(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                from_player=dead_player,
                outcome="lost_no_target",
                to_player=None,
                reason_code="no_eligible_target",
            )
            return

        excluded_badge_targets = excluded_badge_targets or set()
        badge_options = [name for name in active_players if name not in excluded_badge_targets]
        if not badge_options:
            self._resolve_sheriff_badge(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                from_player=dead_player,
                outcome="lost_no_target",
                to_player=None,
                reason_code="no_eligible_target",
            )
            return
        old_sheriff = self.state.player_by_name()[dead_player]
        choice, action_log = self._player_action(
            player=old_sheriff,
            action=ACTION_SHERIFF_BADGE,
            options=badge_options + [SHERIFF_BADGE_DESTROY],
            result_key="badge",
            round_state=round_state,
            phase=phase,
        )
        round_log.sheriff_badge = action_log

        if isinstance(choice, str) and choice in badge_options:
            self._resolve_sheriff_badge(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                from_player=dead_player,
                outcome="transferred",
                to_player=choice,
                reason_code="owner_selected_target",
            )
            return

        self._resolve_sheriff_badge(
            round_state=round_state,
            active_players=active_players,
            phase=phase,
            from_player=dead_player,
            outcome="destroyed",
            to_player=None,
            reason_code="destroyed_by_owner",
        )

    def _resolve_sheriff_badge(
        self,
        *,
        round_state: RoundState,
        active_players: list[str],
        phase: str,
        from_player: str,
        outcome: SheriffBadgeOutcome,
        to_player: str | None,
        reason_code: str,
    ) -> None:
        transferred = outcome == "transferred" and to_player is not None
        self._set_sheriff(to_player if transferred else None)
        self.state.sheriff_badge_lost = not transferred
        round_state.sheriff = to_player if transferred else None
        round_state.sheriff_badge_target = to_player if transferred else None
        round_state.sheriff_badge_lost = not transferred
        resolution = SheriffBadgeResolution(
            schema_version=1,
            outcome=outcome,
            from_player=from_player,
            to_player=to_player if transferred else None,
            reason_code=reason_code,
        )
        round_state.sheriff_badge_resolution = resolution
        public_outcome = self._append_public_outcome(
            round_state=round_state,
            kind="badge_transferred" if transferred else "badge_lost",
            actor_player=from_player,
            target_player=to_player if transferred else None,
            outcome=outcome,
            phase=phase,
            caused_by_event=self._latest_player_outcome(
                round_state,
                from_player,
            ),
        )
        if transferred:
            text = f"第{round_state.number}轮：{from_player}出局，将警徽移交给{to_player}。"
            stage = "sheriff_badge_transfer"
            details: dict[str, object] = {"target": to_player, "reason_code": reason_code}
        elif outcome == "lost_no_target":
            text = f"第{round_state.number}轮：{from_player}出局，无可移交目标，警徽流失。"
            stage = "sheriff_badge_lost"
            details = {"reason": "no_eligible_target", "reason_code": reason_code}
        else:
            text = f"第{round_state.number}轮：{from_player}出局，警徽被撕毁。"
            stage = "sheriff_badge_destroyed"
            details = {"reason": "destroyed", "reason_code": reason_code}
        self._announce(active_players, text)
        self._add_public_fact(
            round_state.number,
            "sheriff",
            text,
            stage=stage,
            actor=from_player,
            retention="critical",
            details=details,
        )
        self._publish_state_updated(
            round_state=round_state,
            phase=phase,
            actor=from_player,
            action="sheriff_badge_resolved",
            payload={
                "narration_mode": "explicit_v1",
                "sheriff_badge": resolution.to_dict(),
                "sheriff": round_state.sheriff,
                "sheriff_badge_target": round_state.sheriff_badge_target,
                "sheriff_badge_lost": round_state.sheriff_badge_lost,
                "active_players": active_players.copy(),
            },
        )
        public_resolution = SheriffBadgeResolution(
            schema_version=resolution.schema_version,
            outcome=resolution.outcome,
            from_player=public_outcome.actor_player_id or "",
            to_player=public_outcome.target_player_id,
            reason_code=resolution.reason_code,
        )
        self._publish_judge_cues(
            round_state,
            phase,
            sheriff_badge_cues(public_resolution)[1:],
        )

    def _is_recorded_round_death(self, player: str, round_state: RoundState) -> bool:
        return any(
            death.player == player for death in [*round_state.night_deaths, *round_state.day_deaths]
        )

    def _run_summaries(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        self._publish_public_round_brief(round_state, active_players)
        self._run_private_round_memories(round_state, round_log, active_players)

    def _publish_public_round_brief(
        self,
        round_state: RoundState,
        active_players: list[str],
    ) -> None:
        self._start_phase(
            round_number=round_state.number,
            phase="summary",
            payload={"active_players": active_players.copy()},
        )
        round_state.public_summary = self._public_round_brief(round_state)
        self._publish_state_updated(
            round_state=round_state,
            phase="summary",
            action="public_round_brief",
            payload={"public_summary": round_state.public_summary},
        )

    def _run_private_round_memories(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        players_by_name = self.state.player_by_name()
        requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action="summarize",
                options=[],
                result_key="summary",
                round_state=round_state,
                phase="summary",
            )
            for name in active_players
        ]
        if not requests:
            self._complete_round_summary_phase(round_state, active_players)
            return

        condition = threading.Condition()
        next_index = {"value": 0}
        executor = ThreadPoolExecutor(max_workers=len(requests))
        futures = [
            executor.submit(
                self._execute_player_action_request,
                request,
                _OrderedBatchProvider(
                    provider=self.provider,
                    index=index,
                    condition=condition,
                    next_index=next_index,
                ),
            )
            for index, request in enumerate(requests)
        ]
        try:
            for index, (name, request, future) in enumerate(
                zip(active_players, requests, futures, strict=True)
            ):
                try:
                    result = future.result()
                    summary, action_log = self._finalize_player_action_result(result)
                except Exception as exc:
                    self._checkpoint_player_action_failure(request, exc)
                    for pending_future in futures[index + 1 :]:
                        pending_future.cancel()
                    raise
                if isinstance(summary, str) and summary:
                    round_state.private_summaries[name] = summary
                round_log.summaries.append(action_log)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        self._complete_round_summary_phase(round_state, active_players)

    def _complete_round_summary_phase(
        self,
        round_state: RoundState,
        active_players: list[str],
    ) -> None:
        self._complete_phase(
            round_number=round_state.number,
            phase="summary",
            completion_status="completed",
            completion_reason="round_memories_recorded",
            next_phase="night" if not self._get_winner(active_players) else None,
            terminal=bool(self._get_winner(active_players)),
        )

    def _public_round_brief(self, round_state: RoundState) -> str:
        if round_state.public_outcome_events:
            return (
                f"第{round_state.number}轮；"
                f"{render_public_round_summary(round_state.public_outcome_events)}"
            )
        parts = [f"第{round_state.number}轮"]
        if round_state.night_deaths:
            deaths = "、".join(death.player for death in round_state.night_deaths)
            parts.append(f"夜晚{deaths}出局")
        if round_state.werewolf_self_exploded:
            parts.append(f"{round_state.werewolf_self_exploded}自爆，白天结束")
        if round_state.exiled:
            parts.append(f"{round_state.exiled}被放逐")
        if round_state.hunter_shot:
            parts.append(f"猎人带走{round_state.hunter_shot}")
        if round_state.idiot_revealed:
            parts.append(f"{round_state.idiot_revealed}翻牌免死")
        if len(parts) == 1:
            parts.append("没有公开出局")
        return "；".join(parts) + "。"

    def _eligible_voters(self, active_players: list[str]) -> list[str]:
        players_by_name = self.state.player_by_name()
        return [name for name in active_players if players_by_name[name].can_vote]

    def _player_action(
        self,
        *,
        player: Player,
        action: str,
        options: list[str],
        result_key: str,
        round_state: RoundState,
        phase: str,
        extra_world_state: dict[str, object] | None = None,
        terminal_settlement_allowed: bool = False,
    ) -> tuple[object | None, ActionLog]:
        request = self._build_player_action_request(
            player=player,
            action=action,
            options=options,
            result_key=result_key,
            round_state=round_state,
            phase=phase,
            extra_world_state=extra_world_state,
            terminal_settlement_allowed=terminal_settlement_allowed,
        )
        return self._player_action_single(request)

    def _build_player_action_request(
        self,
        *,
        player: Player,
        action: str,
        options: list[str],
        result_key: str,
        round_state: RoundState,
        phase: str,
        extra_world_state: dict[str, object] | None = None,
        terminal_settlement_allowed: bool = False,
    ) -> PlayerActionRequest:
        self._require_non_terminal_player_action(
            action=action,
            player=player,
            terminal_settlement_allowed=terminal_settlement_allowed,
        )
        options_snapshot = options.copy()
        public_options = [self._public_player_reference(option) for option in options_snapshot]
        public_choice_to_internal = dict(zip(public_options, options_snapshot, strict=True))
        world_state = self._world_state(player, options_snapshot, round_state)
        if action == ACTION_SHERIFF_SPEECH:
            world_state["public_facts"] = self._public_fact_lines(
                sheriff_speech_context_round=round_state.number,
            )
            world_state["sheriff_election"] = self._sheriff_election_context(
                round_state,
                compact_prior_speeches=True,
            )
            world_state["compact_sheriff_speech_context"] = True
        if extra_world_state:
            world_state.update(extra_world_state)
        if action in BUFFERED_QUALITY_ACTIONS:
            prior_speeches, speech_order = self._speech_stage_context(
                action,
                round_state,
                player,
            )
            public_prior_speeches = [self._public_text(message) for message in prior_speeches]
            mission = assign_speech_mission(
                round_number=round_state.number,
                stage=action,
                speaker=player.name,
                speech_order=speech_order,
                prior_messages=public_prior_speeches,
                personality_id=player.personality_id,
                has_public_evidence=bool(
                    public_prior_speeches
                    or self.state.public_facts
                    or round_state.night_deaths
                    or round_state.day_deaths
                ),
            )
            world_state["speech_mission"] = mission.to_dict()
            world_state["speech_prior_texts"] = public_prior_speeches
        world_state = self._public_model_world_state(copy.deepcopy(world_state))
        world_state["options"] = "、".join(public_options)
        facts = [
            replace(
                public_fact_from_dict(item),
                text=self._public_text(str(item.get("text") or "")),
            )
            for item in self.state.public_facts
            if isinstance(item, dict)
        ]
        coverage = fact_prompt_coverage(
            facts,
            list(world_state.get("public_facts", [])),
        )
        event_visibility = self._player_action_event_visibility(phase, action)
        action_id = self._next_logical_action_id(
            round_number=round_state.number,
            phase=phase,
            actor=player.name,
            action=action,
        )
        if (
            action in BUFFERED_QUALITY_ACTIONS
            and self.liveness_experience.scene_packet_version == "scene-packet-v1"
        ):
            mind = self._actor_minds.get(player.name)
            actor_packet = build_actor_scene_packet(
                world_state,
                actor_mind=(
                    mind
                    if self.liveness_experience.feature_modes.actor_mind == "read"
                    else None
                ),
            )
            mission_payload = world_state.get("speech_mission")
            mission_kind = (
                str(mission_payload.get("kind") or "")
                if isinstance(mission_payload, dict)
                else None
            )
            recent_turns = world_state.get("debate")
            response_target = None
            if isinstance(recent_turns, list) and recent_turns:
                latest = str(recent_turns[-1])
                candidate = latest.split("：", 1)[0].strip()
                if candidate and candidate != str(world_state.get("name") or ""):
                    response_target = candidate
            plan = fallback_public_turn_plan(
                action_id=action_id,
                fence={
                    "action_id": action_id,
                    "round": round_state.number,
                    "phase": phase,
                    "active_roster_hash": hashlib.sha256(
                        "|".join(sorted(public_options)).encode()
                    ).hexdigest()[:16],
                },
                mission_kind=mission_kind,
                response_target=response_target,
            )
            public_scene = build_public_speech_scene(world_state, turn_plan=plan)
            world_state["actor_scene_packet"] = actor_packet.to_dict()
            world_state["scene_packet_hash"] = actor_packet.content_hash()
            world_state["public_turn_plan"] = plan.to_dict()
            world_state["public_speech_scene"] = public_scene.to_dict()
        return PlayerActionRequest(
            player=player,
            action=action,
            options=options_snapshot,
            public_options=public_options,
            public_choice_to_internal=public_choice_to_internal,
            result_key=result_key,
            round_state=round_state,
            phase=phase,
            world_state=world_state,
            event_visibility=event_visibility,
            fact_prompt_coverage=coverage,
            action_id=action_id,
            terminal_settlement_allowed=terminal_settlement_allowed,
        )

    def _next_logical_action_id(
        self,
        *,
        round_number: int,
        phase: str,
        actor: str,
        action: str,
    ) -> str:
        key = (round_number, phase, actor, action)
        self._logical_action_occurrences[key] += 1
        occurrence = self._logical_action_occurrences[key]
        material = ":".join(
            (
                self.state.session_id,
                str(round_number),
                phase,
                actor,
                action,
                str(occurrence),
            )
        )
        return f"act_{hashlib.sha256(material.encode()).hexdigest()[:12]}"

    def _next_provider_attempt_id(self, action_id: str) -> str:
        self._provider_attempt_occurrences[action_id] += 1
        attempt = self._provider_attempt_occurrences[action_id]
        material = f"{action_id}:{attempt}"
        return f"req_{hashlib.sha256(material.encode()).hexdigest()[:12]}"

    def _plan_public_speech_request(
        self,
        request: PlayerActionRequest,
        provider: ModelProvider,
        *,
        event_sink: object,
        call_options: ModelCallOptions | None,
    ) -> None:
        if (
            request.event_visibility != "public"
            or request.action not in BUFFERED_QUALITY_ACTIONS
            or self.liveness_experience.experience_revision == "legacy-v0"
            or not isinstance(request.world_state.get("actor_scene_packet"), dict)
        ):
            return
        current_plan = request.world_state.get("public_turn_plan")
        fallback_plan = current_plan if isinstance(current_plan, dict) else {}
        fence = fallback_plan.get("fence")
        safe_fence = dict(fence) if isinstance(fence, Mapping) else {}
        planner_started_at = round(time.time() * 1000)
        plan_log: LmLog | None = None
        plan_value: object = None
        try:
            plan_value, plan_log = generate_action_with_events(
                provider=provider,
                action="actor_plan",
                world_state={
                    "actor_scene_packet": copy.deepcopy(
                        request.world_state["actor_scene_packet"]
                    )
                },
                model=request.player.model,
                event_sink=_PrivateLifecycleEventSink(event_sink),
                event_context={
                    "round_number": request.round_state.number,
                    "phase": request.phase,
                    "actor": request.player.name,
                    "action": request.action,
                },
                action_id_factory=lambda: request.action_id,
                request_id_factory=lambda: self._next_provider_attempt_id(
                    request.action_id
                ),
                retries=1,
                enable_progress_ticks=False,
                call_options=call_options,
                generation_stage="planner",
            )
        except ModelActionCanceled:
            raise
        except ModelDeadlineExceeded:
            plan_value = None
        except Exception:
            plan_value = None
        recognized_plan_fields = {
            "primary_speech_act",
            "secondary_speech_act",
            "social_goal",
            "public_points",
            "length_band",
            "affect_impulse",
        }
        if isinstance(plan_value, Mapping) and recognized_plan_fields & set(plan_value):
            allowed_sources, allowed_fact_ids = self._public_plan_references(request)
            plan = public_turn_plan_from_model(
                plan_value,
                action_id=request.action_id,
                fence=safe_fence,
                allowed_targets={
                    name
                    for name in request.round_state.players
                    if name != request.player.name
                },
                allowed_sources=allowed_sources,
                allowed_fact_ids=allowed_fact_ids,
            )
            request.world_state["public_turn_plan"] = plan.to_dict()
        else:
            plan = public_turn_plan_from_model(
                fallback_plan,
                action_id=request.action_id,
                fence=safe_fence,
                allowed_targets={
                    name
                    for name in request.round_state.players
                    if name != request.player.name
                },
                allowed_sources=set(),
                allowed_fact_ids=set(),
            )
            request.world_state["public_turn_plan"] = plan.to_dict()
        request.world_state["public_speech_scene"] = build_public_speech_scene(
            request.world_state,
            turn_plan=plan,
        ).to_dict()
        if plan_log is not None:
            request.world_state["planner_request_id"] = plan_log.request_id
            request.world_state["planner_attempts"] = safe_attempt_outcomes(
                plan_log.attempt_outcomes
            )
        request.world_state["_liveness_timing"] = {
            "actor_brain_started_at": planner_started_at,
            "turn_plan_ready_at": round(time.time() * 1000),
        }

    def _public_plan_references(
        self,
        request: PlayerActionRequest,
    ) -> tuple[set[tuple[str, int]], set[str]]:
        sources: set[tuple[str, int]] = set()
        fact_ids: set[str] = set()
        public_facts = request.world_state.get("public_facts")
        if not isinstance(public_facts, list):
            return sources, fact_ids
        for item in public_facts:
            if not isinstance(item, Mapping):
                continue
            fact_id = item.get("fact_id")
            if isinstance(fact_id, str) and fact_id:
                fact_ids.add(fact_id)
            source = item.get("source")
            if not isinstance(source, Mapping):
                continue
            source_run_id = source.get("source_run_id")
            source_event_id = source.get("source_event_id")
            if isinstance(source_run_id, str) and type(source_event_id) is int:
                sources.add((source_run_id, source_event_id))
        return sources, fact_ids

    def _execute_player_action_request(
        self,
        request: PlayerActionRequest,
        provider: ModelProvider | None = None,
        event_sink: object | None = None,
        deadline_at_monotonic: float | None = None,
        timeout_fallback: bool = True,
        private_lifecycle_events: bool = False,
    ) -> PlayerActionResult:
        self._require_non_terminal_player_action(
            action=request.action,
            player=request.player,
            terminal_settlement_allowed=request.terminal_settlement_allowed,
        )
        action_provider = provider or self.provider
        public_event_sink = event_sink or self.event_sink
        model_event_sink = (
            public_event_sink
            if request.event_visibility == "public" or private_lifecycle_events
            else NullEventSink()
        )
        started_at = self.monotonic()
        actor_brain_started_at_ms = round(time.time() * 1000)
        budget_spec = self.action_execution_budget.for_action(request.action)
        call_options = budget_spec.call_options(started_at) if self.action_budgets_enabled else None
        if deadline_at_monotonic is not None:
            remaining_seconds = max(0.0, deadline_at_monotonic - started_at)
            if remaining_seconds <= 0:
                if not timeout_fallback:
                    raise ModelDeadlineExceeded("model action deadline exceeded")
                return self._timeout_fallback_result(
                    request,
                    started_at=started_at,
                    budget_ms=0,
                )
            if call_options is None:
                call_options = ModelCallOptions(
                    deadline_at_monotonic=deadline_at_monotonic,
                    request_timeout_seconds=remaining_seconds,
                )
            else:
                effective_deadline = min(
                    call_options.deadline_at_monotonic,
                    deadline_at_monotonic,
                )
                effective_remaining = max(0.0, effective_deadline - started_at)
                call_options = replace(
                    call_options,
                    deadline_at_monotonic=effective_deadline,
                    request_timeout_seconds=min(
                        call_options.request_timeout_seconds,
                        effective_remaining,
                    ),
                )
        renderer_started_at_ms = actor_brain_started_at_ms
        try:
            self._plan_public_speech_request(
                request,
                action_provider,
                event_sink=model_event_sink,
                call_options=call_options,
            )
            renderer_started_at_ms = round(time.time() * 1000)
            if self._should_buffer_quality_action(request):
                value, lm_log = self._generate_buffered_quality_action(
                    request,
                    action_provider,
                    call_options=call_options,
                    event_sink=model_event_sink,
                )
            else:
                value, lm_log = self._generate_action_for_request(
                    request,
                    action_provider,
                    event_sink=model_event_sink,
                    call_options=call_options,
                )
        except ModelDeadlineExceeded as exc:
            if not timeout_fallback:
                raise
            return self._timeout_fallback_result(
                request,
                started_at=started_at,
                budget_ms=(
                    round(budget_spec.total_budget_seconds * 1000)
                    if self.action_budgets_enabled
                    else None
                ),
                attempt_outcomes=getattr(exc, "attempt_outcomes", []),
            )
        except _PublicActionInterruptedBySelfExplosion:
            raise
        except Exception:
            release_turn = getattr(action_provider, "release_turn_if_not_started", None)
            if callable(release_turn):
                release_turn()
            raise
        if isinstance(value, str) and request.public_choice_to_internal:
            value = request.public_choice_to_internal.get(value, value)
        if self.liveness_experience.experience_revision != "legacy-v0":
            prepared_timing = request.world_state.get("_liveness_timing")
            safe_prepared_timing = (
                prepared_timing if isinstance(prepared_timing, dict) else {}
            )
            lm_log.liveness_timing = {
                **lm_log.liveness_timing,
                "turn_ready_at": actor_brain_started_at_ms,
                "actor_brain_started_at": int(
                    safe_prepared_timing.get(
                        "actor_brain_started_at",
                        actor_brain_started_at_ms,
                    )
                ),
                "turn_plan_ready_at": int(
                    safe_prepared_timing.get(
                        "turn_plan_ready_at",
                        actor_brain_started_at_ms,
                    )
                ),
                "renderer_started_at": renderer_started_at_ms,
                **(
                    {
                        "first_model_delta_at": actor_brain_started_at_ms
                        + lm_log.first_token_ms
                    }
                    if lm_log.first_token_ms is not None
                    else {}
                ),
            }
        return PlayerActionResult(
            request=request,
            value=value,
            lm_log=lm_log,
            duration_ms=(
                max(0, round((self.monotonic() - started_at) * 1000))
                if self.action_budgets_enabled
                else 0
            ),
            budget_ms=(
                round(budget_spec.total_budget_seconds * 1000)
                if self.action_budgets_enabled
                else None
            ),
        )

    def _generate_action_for_request(
        self,
        request: PlayerActionRequest,
        provider: ModelProvider,
        *,
        event_sink: object,
        world_state: dict[str, object] | None = None,
        call_options: ModelCallOptions | None = None,
        visible_text_observer: _CommittedSpeechObserver | None = None,
        retries: int = 3,
    ) -> tuple[object | None, LmLog]:
        return generate_action_with_events(
            provider=provider,
            action=request.action,
            world_state=world_state or request.world_state,
            model=request.player.model,
            allowed_values=request.public_options if request.public_options else None,
            result_key=request.result_key,
            retries=retries,
            event_sink=event_sink,
            event_context={
                "round_number": request.round_state.number,
                "phase": request.phase,
                "actor": request.player.name,
                "action": request.action,
            },
            action_id_factory=lambda: request.action_id,
            request_id_factory=lambda: self._next_provider_attempt_id(
                request.action_id
            ),
            call_options=call_options,
            visible_text_observer=visible_text_observer,
            generation_stage=(
                "renderer" if visible_text_observer is not None else None
            ),
        )

    def _should_buffer_quality_action(self, request: PlayerActionRequest) -> bool:
        return (
            (
                request.event_visibility == "public"
                and request.action in BUFFERED_QUALITY_ACTIONS
            )
            or request.action in PRIVATE_LENGTH_BUDGETED_ACTIONS
        )

    def _committed_speech_stream_mode(
        self,
        request: PlayerActionRequest,
    ) -> Literal["segments_v2"] | None:
        if request.event_visibility != "public":
            return None
        return "segments_v2"

    def _committed_speech_observer(
        self,
        request: PlayerActionRequest,
        *,
        event_sink: object,
        speech_id: str,
        speech_stream_mode: Literal["segments_v2"],
        voice_snapshot: dict[str, object] | None,
    ) -> _CommittedSpeechObserver:
        character_limit = speech_character_limit(request.action) or 220

        def gate(candidate: str) -> HardSpeechGateReportV1:
            candidate_log = LmLog(
                prompt="",
                raw_response="",
                result={request.result_key: candidate},
                action_id=request.action_id,
            )
            return hard_speech_gate(
                candidate,
                deterministic_codes=tuple(
                    self._hard_quality_warnings(request, candidate_log)
                ),
            )

        def commit(
            segment_index: int,
            text: str,
            request_id: str,
            segment_final: bool,
        ) -> dict[str, object]:
            return self._commit_speech_segment(
                request=request,
                event_sink=event_sink,
                speech_id=speech_id,
                segment_index=segment_index,
                text=text,
                request_id=request_id,
                segment_final=False,
                speech_stream_mode=speech_stream_mode,
                voice_snapshot=voice_snapshot,
            )

        return _CommittedSpeechObserver(
            character_limit=character_limit,
            gate=gate,
            commit=commit,
        )

    def _commit_speech_segment(
        self,
        *,
        request: PlayerActionRequest,
        event_sink: object,
        speech_id: str,
        segment_index: int,
        text: str,
        request_id: str,
        segment_final: bool,
        speech_stream_mode: Literal["segments_v2"],
        voice_snapshot: dict[str, object] | None,
        renderer_attempts: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        self._interrupt_public_action_if_self_explosion_ready(
            "model_response_delta"
        )
        plan = request.world_state.get("public_turn_plan")
        safe_plan = plan if isinstance(plan, dict) else {}
        segment_id = stable_segment_id(speech_id, segment_index, text)
        payload: dict[str, object] = {
            "schema_version": 2,
            "commit_state": "accepted_segment",
            "generation_stage": "renderer",
            "action_id": request.action_id,
            "request_id": request_id,
            "model": request.player.model,
            "speech_id": speech_id,
            "speech_stream_mode": speech_stream_mode,
            "segment_id": segment_id,
            "segment_index": segment_index,
            "segment_final": segment_final,
            "delta": text,
            "visible_text": text,
            "field": request.result_key,
            "is_public": True,
            "presentation_id": stable_segment_presentation_id(segment_id),
            "experience_revision": self.liveness_experience.experience_revision,
            "quality_gate_version": self.liveness_experience.quality_gate_version,
            "plan_id": safe_plan.get("plan_id"),
            "fence": copy.deepcopy(safe_plan.get("fence")),
            "scene_packet_hash": request.world_state.get("scene_packet_hash"),
            "planner_request_id": request.world_state.get("planner_request_id"),
            "renderer_attempts": copy.deepcopy(renderer_attempts or []),
        }
        if voice_snapshot is not None:
            payload["voice_snapshot"] = copy.deepcopy(voice_snapshot)
        publish = getattr(event_sink, "publish")
        published = publish(
            "model_response_delta",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload=payload,
        )
        if isinstance(event_sink, _PublishGateSink) and published is None:
            raise ModelDeadlineExceeded("speech segment missed publication fence")
        self._reduce_actor_minds_from_public_event(
            published,
            event_type="model_response_delta",
            phase=request.phase,
            payload=payload,
        )
        receipt_segment: dict[str, object] = {
            "segment_id": segment_id,
            "segment_index": segment_index,
            "text": text,
            "presentation_id": payload["presentation_id"],
        }
        source_event_id = getattr(published, "id", None)
        source_run_id = getattr(published, "run_id", None)
        if type(source_event_id) is int:
            receipt_segment["source_event_id"] = source_event_id
        if isinstance(source_run_id, str) and source_run_id:
            receipt_segment["source_run_id"] = source_run_id
        active_speech = self._active_committed_speech.get(request.action_id)
        prior_segments = (
            active_speech.get("segments", [])
            if isinstance(active_speech, dict)
            else []
        )
        if not isinstance(prior_segments, list):
            prior_segments = []
        prior_visible_text = (
            active_speech.get("visible_text", "")
            if isinstance(active_speech, dict)
            else ""
        )
        self._active_committed_speech[request.action_id] = {
            "speech_id": speech_id,
            "segments": [
                *copy.deepcopy(prior_segments),
                copy.deepcopy(receipt_segment),
            ],
            "visible_text": str(prior_visible_text) + text,
        }
        return receipt_segment

    def _attach_committed_speech_observer(
        self,
        *,
        lm_log: LmLog,
        observer: _CommittedSpeechObserver,
        speech_id: str,
        speech_stream_mode: Literal["segments_v2"],
    ) -> None:
        if not observer.segments:
            return
        status = lm_log.speech_generation_status or "complete"
        receipt_status = (
            "complete"
            if status == "complete"
            else "interrupted"
            if status == "interrupted"
            else "partial"
        )
        lm_log.speech_id = speech_id
        lm_log.committed_speech_segments = observer.segments.copy()
        lm_log.hard_speech_gate_codes = observer.codes.copy()
        lm_log.hard_speech_gate_rejected_count = observer.rejected_count
        if observer.first_committed_at_ms is not None:
            lm_log.liveness_timing.setdefault(
                "first_clause_committed_at",
                observer.first_committed_at_ms,
            )
        lm_log.liveness_timing["hard_gate_duration_ms"] = (
            observer.hard_gate_duration_ms
        )
        lm_log.speech_turn_receipt = {
            "speech_id": speech_id,
            "speech_stream_mode": speech_stream_mode,
            "status": receipt_status,
            "segment_count": len(observer.receipt_segments),
            "segments": copy.deepcopy(observer.receipt_segments),
            "final_text": observer.committed_text,
            "accepted_renderer_request_id": lm_log.request_id,
            "final_status": status,
        }
        if observer.length_truncated:
            lm_log.speech_turn_receipt["length_truncated"] = True

    def _liveness_voice_snapshot(
        self,
        request: PlayerActionRequest,
    ) -> dict[str, object]:
        player = request.player
        plan = request.world_state.get("public_turn_plan")
        safe_plan = plan if isinstance(plan, dict) else {}
        mind = self._actor_minds.get(player.name)
        if (
            self.liveness_experience.feature_modes.affect_delivery == "on"
            and mind is not None
        ):
            effective_delivery = compile_affect_delivery_v2(
                base_mood=player.base_delivery_mood,
                base_intensity=player.base_delivery_intensity,
                base_pace=player.base_delivery_pace,
                base_instruction=player.base_delivery_instruction,
                public_affect=public_affect_projection(mind),
                speech_act=(
                    str(safe_plan.get("primary_speech_act"))
                    if safe_plan.get("primary_speech_act") is not None
                    else None
                ),
                phase=request.phase,
            )
            mapping_version = AFFECT_DELIVERY_MAPPING_VERSION
        else:
            effective_delivery = delivery_from_result(
                None,
                base_mood=player.base_delivery_mood,
                base_intensity=player.base_delivery_intensity,
                base_pace=player.base_delivery_pace,
                base_instruction=player.base_delivery_instruction,
            )
            mapping_version = DELIVERY_MAPPING_VERSION
        return {
            "enabled": player.voice_enabled,
            "speaker": player.tts_speaker,
            "effective_delivery": copy.deepcopy(effective_delivery),
            "effective_context_texts": compile_context_texts(
                effective_delivery,
                dialect=player.tts_dialect,
            ),
            "voice_config_version": player.voice_config_version,
            "delivery_mapping_version": mapping_version,
        }

    def _generate_buffered_quality_action(
        self,
        request: PlayerActionRequest,
        provider: ModelProvider,
        *,
        call_options: ModelCallOptions | None,
        event_sink: object,
    ) -> tuple[object | None, LmLog]:
        world_state = copy.deepcopy(request.world_state)
        async_style_observe = (
            request.event_visibility == "public"
            and self.liveness_experience.feature_modes.style_gate == "async_observe"
        )
        speech_stream_mode = self._committed_speech_stream_mode(request)
        committed_segment_mode = speech_stream_mode is not None
        if committed_segment_mode:
            assert speech_stream_mode is not None
        liveness_hard_gate = self.liveness_experience.experience_revision != "legacy-v0"
        if committed_segment_mode:
            restored = self._restored_committed_speech(request)
            if restored is not None:
                return restored
        speech_id = (
            stable_speech_id(
                self.state.session_id,
                request.action_id,
                self.liveness_experience.speech_stream_version,
            )
            if committed_segment_mode
            else None
        )
        voice_snapshot = (
            self._liveness_voice_snapshot(request)
            if committed_segment_mode
            else None
        )
        initial_codes: list[str] = []
        quality_retry_started_at: float | None = None
        quality_attempt_outcomes: list[dict[str, str]] = []
        for quality_attempt in range(2):
            buffer = _BufferedEventSink(
                self._interrupt_public_action_if_self_explosion_ready,
                lifecycle_destination=(
                    event_sink
                    if committed_segment_mode
                    or isinstance(event_sink, _PublishGateSink)
                    else None
                ),
            )
            observer = (
                self._committed_speech_observer(
                    request,
                    event_sink=event_sink,
                    speech_id=speech_id,
                    speech_stream_mode=speech_stream_mode,
                    voice_snapshot=voice_snapshot,
                )
                if speech_id is not None
                else None
            )
            try:
                value, lm_log = self._generate_action_for_request(
                    request,
                    provider,
                    event_sink=buffer,
                    world_state=world_state,
                    call_options=call_options,
                    visible_text_observer=observer,
                    retries=1 if observer is not None else 3,
                )
            except Exception as exc:
                setattr(
                    exc,
                    "attempt_outcomes",
                    safe_attempt_outcomes(
                        [
                            *quality_attempt_outcomes,
                            *getattr(exc, "attempt_outcomes", []),
                        ]
                    ),
                )
                raise
            if observer is not None and speech_id is not None:
                self._attach_committed_speech_observer(
                    lm_log=lm_log,
                    observer=observer,
                    speech_id=speech_id,
                    speech_stream_mode=speech_stream_mode,
                )
            quality_attempt_outcomes = safe_attempt_outcomes(
                [*quality_attempt_outcomes, *lm_log.attempt_outcomes]
            )
            lm_log.attempt_outcomes = quality_attempt_outcomes.copy()
            quality_report = self._speech_quality_report(request, lm_log)
            hard_warnings = (
                self._hard_quality_warnings(request, lm_log)
                if request.event_visibility == "public"
                and liveness_hard_gate
                and not (observer is not None and observer.segments)
                else []
            )
            speech_text, speech_result_key = self._speech_text_for_length_budget(
                request,
                value,
                lm_log,
            )
            if request.event_visibility == "public" and (
                not isinstance(value, str) or not value.strip()
            ):
                hard_warnings.append("invalid_public_speech")
            if isinstance(speech_text, str):
                length_warning = speech_length_violation(request.action, speech_text)
                if length_warning is not None and async_style_observe:
                    character_limit = speech_character_limit(request.action)
                    if character_limit is None:
                        raise RuntimeError("missing speech character limit")
                    accepted_text = truncate_speech_to_complete_sentence(
                        speech_text,
                        max_chars=character_limit,
                        fallback="本轮暂不追加判断。",
                    )
                    value = accepted_text
                    normalized_result = dict(lm_log.result or {})
                    normalized_result[speech_result_key] = accepted_text
                    lm_log.result = normalized_result
                    speech_text = accepted_text
                elif length_warning is not None:
                    hard_warnings.append(length_warning)
            hard_warnings = list(dict.fromkeys(hard_warnings))
            if (
                request.event_visibility == "public"
                and liveness_hard_gate
                and isinstance(speech_text, str)
                and not (observer is not None and observer.segments)
            ):
                gate_report = hard_speech_gate(
                    speech_text,
                    deterministic_codes=tuple(hard_warnings),
                )
                hard_warnings = list(gate_report.codes)
            if (
                self.speech_quality_retry_enabled
                and not async_style_observe
                and quality_report is not None
            ):
                hard_warnings = list(
                    dict.fromkeys([*hard_warnings, *quality_report.hard_failure_codes])
                )
            if not hard_warnings:
                if committed_segment_mode and isinstance(speech_text, str):
                    if lm_log.speech_id is None:
                        lm_log.speech_id = speech_id
                        lm_log.committed_speech_segments = split_complete_speech_segments(
                            speech_text
                        )
                self._attach_speech_quality_metadata(
                    request=request,
                    lm_log=lm_log,
                    report=quality_report,
                    attempt_count=quality_attempt + 1,
                    retry_exhausted=bool(hard_warnings and quality_attempt == 1),
                    initial_codes=initial_codes,
                    retry_duration_ms=self._quality_retry_duration_ms(
                        quality_retry_started_at
                    ),
                )
                if committed_segment_mode:
                    buffer.flush_lifecycle_to(event_sink)
                else:
                    buffer.flush_to(
                        event_sink,
                        accepted_visible_text=(
                            speech_text
                            if async_style_observe and isinstance(speech_text, str)
                            else None
                        ),
                    )
                return value, lm_log
            if quality_attempt == 1:
                self._attach_speech_quality_metadata(
                    request=request,
                    lm_log=lm_log,
                    report=quality_report,
                    attempt_count=2,
                    retry_exhausted=True,
                    initial_codes=initial_codes,
                    retry_duration_ms=self._quality_retry_duration_ms(
                        quality_retry_started_at
                    ),
                )
                buffer.flush_lifecycle_to(event_sink)
                if (
                    request.action in PRIVATE_LENGTH_BUDGETED_ACTIONS
                    and length_warning is not None
                    and isinstance(speech_text, str)
                ):
                    character_limit = speech_character_limit(request.action)
                    if character_limit is None:
                        raise RuntimeError("missing speech character limit")
                    accepted_text = truncate_speech_to_complete_sentence(
                        speech_text,
                        max_chars=character_limit,
                        fallback="",
                    )
                    accepted_result: dict[str, object] = {
                        speech_result_key: accepted_text,
                    }
                    if speech_result_key != request.result_key:
                        accepted_result[request.result_key] = value
                    lm_log.result = accepted_result
                    lm_log.raw_response = ""
                    if speech_result_key == request.result_key:
                        value = accepted_text
                    return value, lm_log
                if request.event_visibility == "public":
                    value = ""
                    result = dict(lm_log.result or {})
                    result[request.result_key] = ""
                    lm_log.result = result
                    lm_log.raw_response = ""
                    return value, lm_log
                return value, lm_log
            initial_codes = hard_warnings.copy()
            quality_retry_started_at = self.monotonic()
            buffer.flush_lifecycle_to(event_sink)
            publish = getattr(event_sink, "publish")
            record_model_progress_event("model_retry_scheduled")
            publish(
                "model_retry_scheduled",
                round_number=request.round_state.number,
                phase=request.phase,
                actor=request.player.name,
                action=request.action,
                payload={
                    "action_id": lm_log.action_id,
                    "request_id": lm_log.request_id,
                    "model": request.player.model,
                    "attempt": quality_attempt + 2,
                    "quality_codes": hard_warnings,
                    "message": "发言质量未通过，正在带反馈重写一次。",
                },
            )
            world_state["quality_feedback"] = self._quality_feedback(hard_warnings)
        raise RuntimeError("buffered quality retry loop ended unexpectedly")

    def _speech_text_for_length_budget(
        self,
        request: PlayerActionRequest,
        value: object | None,
        lm_log: LmLog,
    ) -> tuple[object | None, str]:
        if request.action in PRIVATE_LENGTH_BUDGETED_ACTIONS:
            result = lm_log.result or {}
            return result.get("message"), "message"
        return value, request.result_key

    def _restored_committed_speech(
        self,
        request: PlayerActionRequest,
    ) -> tuple[str, LmLog] | None:
        if self.checkpoint_manager is None:
            return None
        loader = getattr(self.checkpoint_manager, "speech_turn_receipt", None)
        if not callable(loader):
            return None
        receipt = loader(request.action_id)
        if not isinstance(receipt, dict):
            return None
        speech_id = receipt.get("speech_id")
        segments = receipt.get("segments")
        status = receipt.get("status")
        expected_stream_mode = self._committed_speech_stream_mode(request)
        stored_stream_mode = receipt.get("speech_stream_mode")
        if (
            not isinstance(speech_id, str)
            or not speech_id
            or not isinstance(segments, list)
            or not segments
            or status not in {"partial", "complete", "interrupted"}
            or stored_stream_mode != expected_stream_mode
        ):
            raise ResumeCheckpointError("invalid_structure")
        ordered_text: list[str] = []
        for index, item in enumerate(segments):
            if (
                not isinstance(item, dict)
                or type(item.get("segment_index")) is not int
                or item.get("segment_index") != index
                or not isinstance(item.get("segment_id"), str)
                or not isinstance(item.get("text"), str)
                or not item["text"]
            ):
                raise ResumeCheckpointError("invalid_structure")
            ordered_text.append(str(item["text"]))
        final_text = "".join(ordered_text)
        if receipt.get("final_text") != final_text:
            raise ResumeCheckpointError("invalid_structure")
        request_id = receipt.get("accepted_renderer_request_id")
        lm_log = LmLog(
            prompt="",
            raw_response="",
            result={request.result_key: final_text},
            action_id=request.action_id,
            request_id=request_id if isinstance(request_id, str) else None,
            committed_speech_segments=ordered_text,
            speech_id=speech_id,
            speech_turn_receipt=copy.deepcopy(receipt),
        )
        return final_text, lm_log

    def _publish_committed_speech_segments(
        self,
        *,
        request: PlayerActionRequest,
        lm_log: LmLog,
        voice_snapshot: dict[str, object] | None,
    ) -> None:
        if (
            not lm_log.speech_id
            or not lm_log.committed_speech_segments
            or lm_log.speech_turn_receipt is not None
        ):
            return
        speech_stream_mode = self._committed_speech_stream_mode(request)
        if speech_stream_mode is None:
            raise RuntimeError("committed speech has no stream mode")
        plan = request.world_state.get("public_turn_plan")
        safe_plan = plan if isinstance(plan, dict) else {}
        renderer_attempts = [
            {
                "request_id": item["request_id"],
                "outcome": item["attempt_result"],
            }
            for item in safe_attempt_outcomes(lm_log.attempt_outcomes)
        ]
        committed_at = round(time.time() * 1000)
        lm_log.liveness_timing.setdefault("first_clause_committed_at", committed_at)
        receipt_segments: list[dict[str, object]] = []
        for segment_index, text in enumerate(lm_log.committed_speech_segments):
            segment_id = stable_segment_id(lm_log.speech_id, segment_index, text)
            payload: dict[str, object] = {
                "schema_version": 2,
                "commit_state": "accepted_segment",
                "generation_stage": "renderer",
                "action_id": request.action_id,
                "request_id": lm_log.request_id,
                "model": request.player.model,
                "speech_id": lm_log.speech_id,
                "speech_stream_mode": speech_stream_mode,
                "segment_id": segment_id,
                "segment_index": segment_index,
                "segment_final": False,
                "delta": text,
                "visible_text": text,
                "field": request.result_key,
                "is_public": True,
                "presentation_id": stable_segment_presentation_id(segment_id),
                "experience_revision": self.liveness_experience.experience_revision,
                "plan_id": safe_plan.get("plan_id"),
                "fence": copy.deepcopy(safe_plan.get("fence")),
                "scene_packet_hash": request.world_state.get("scene_packet_hash"),
                "renderer_attempts": copy.deepcopy(renderer_attempts),
            }
            if voice_snapshot is not None:
                payload["voice_snapshot"] = copy.deepcopy(voice_snapshot)
            published = self._publish(
                "model_response_delta",
                round_number=request.round_state.number,
                phase=request.phase,
                actor=request.player.name,
                action=request.action,
                payload=payload,
            )
            receipt_segment: dict[str, object] = {
                "segment_id": segment_id,
                "segment_index": segment_index,
                "text": text,
                "presentation_id": payload["presentation_id"],
            }
            source_event_id = getattr(published, "id", None)
            source_run_id = getattr(published, "run_id", None)
            if type(source_event_id) is int:
                receipt_segment["source_event_id"] = source_event_id
            if isinstance(source_run_id, str) and source_run_id:
                receipt_segment["source_run_id"] = source_run_id
            receipt_segments.append(receipt_segment)
            lm_log.speech_turn_receipt = {
                "speech_id": lm_log.speech_id,
                "speech_stream_mode": speech_stream_mode,
                "status": (
                    "complete"
                    if segment_index == len(lm_log.committed_speech_segments) - 1
                    else "partial"
                ),
                "segment_count": len(receipt_segments),
                "segments": copy.deepcopy(receipt_segments),
                "final_text": "".join(
                    item["text"] for item in receipt_segments if isinstance(item["text"], str)
                ),
                "accepted_renderer_request_id": lm_log.request_id,
            }
            if self.checkpoint_manager is not None:
                recorder = getattr(
                    self.checkpoint_manager,
                    "record_speech_turn_receipt",
                    None,
                )
                if callable(recorder):
                    recorder(request.action_id, lm_log.speech_turn_receipt)

    def _hard_quality_warnings(
        self,
        request: PlayerActionRequest,
        lm_log: LmLog,
    ) -> list[str]:
        result = lm_log.result or {}
        text = result.get(request.result_key)
        if not isinstance(text, str):
            return []
        active_players = (
            request.player.gamestate.current_players
            if request.player.gamestate
            else request.round_state.players
        )
        eligibility = request.world_state.get("public_action_eligibility")
        warnings = action_quality_warnings(
            action=request.action,
            text=text,
            actor=request.player.name,
            endgame=len(active_players) <= 4,
            prior_texts=[entry.message for entry in request.round_state.debate],
            personality=request.player.personality,
            eligibility=eligibility if isinstance(eligibility, dict) else None,
            role=request.player.role,
            hard_state=(
                request.world_state.get("hard_state")
                if isinstance(request.world_state.get("hard_state"), dict)
                else None
            ),
        )
        if self._speech_contradicts_latest_vote_tally(request, text):
            warnings.append("contradicts_public_vote_tally")
        return [warning for warning in warnings if warning in HARD_ACTION_QUALITY_CODES]

    def _quality_feedback(self, warnings: list[str]) -> str:
        guidance = {
            "appeals_to_missing_sheriff_voters": "本轮没有警下投票者，不要向警下拉票。",
            "promises_ineligible_sheriff_vote": "你没有警长投票资格，不要承诺自己的警长票。",
            "sheriff_speech_investigation_plan_without_seer_claim": (
                "只有预言家或明确公开跳预言家的玩家才能给出查验式警徽流；"
                "否则请改为说明发言方向、归票和警徽移交原则，不要承诺先验、再验或今晚验人。"
            ),
            "assumes_future_round_in_endgame": "不能假定一定存在明天或下一轮。",
            "ignores_terminal_risk": "说明本轮错误放逐可能立即结束游戏。",
            "repeated_debate_phrase": "不要复述已有长句，加入一个新的公开事实、票型变化或具体反问。",
            "low_proposition_novelty": "给出一个此前没有出现过的明确判断，并说明可验证依据。",
            "group_agreement_without_evidence": "不要继续无依据附和；提出当前多数结论的反例或风险。",
            "catchphrase_dominates_speech": "减少个人口头禅，用具体事实和结论替代。",
            "contradicts_public_vote_tally": "你写出的确定票数与引擎票型不一致，请按公开票型改写。",
            "invalid_public_speech": "必须返回非空的公开发言。",
            "last_words_too_long": "遗言不得超过 150 个汉字，请只保留最后判断和依据。",
            "speech_too_long": "发言超出当前阶段长度上限，请只保留结论和最关键的依据。",
            "hunter_claims_voluntary_future_shot": (
                "猎人只能在合法死亡技能触发时开枪，存活时不能承诺之后主动开枪。"
            ),
            "claims_future_round_after_terminal": (
                "当前动作结算后对局会立即结束，不得声称下一轮或下一夜再行动。"
            ),
            "claims_illegal_post_death_action": (
                "你已经出局，不得承诺之后投票、查验、用药或发言。"
            ),
        }
        return "；".join(guidance[warning] for warning in warnings if warning in guidance)

    def _speech_contradicts_latest_vote_tally(
        self,
        request: PlayerActionRequest,
        text: str,
    ) -> bool:
        patterns = (
            r"(?:票型|投票结果|票数)[^0-9]{0,8}(\d+)\s*(?:[:：比-])\s*(\d+)",
            r"(\d+)\s*(?:[:：比-])\s*(\d+)\s*(?:票型|票)",
        )
        asserted: tuple[int, int] | None = None
        for pattern in patterns:
            match = re.search(pattern, text)
            if match is not None:
                asserted = tuple(sorted((int(match.group(1)), int(match.group(2))), reverse=True))
                break
        if asserted is None:
            return False

        candidate_rounds = list(self.state.rounds)
        if all(existing is not request.round_state for existing in candidate_rounds):
            candidate_rounds.append(request.round_state)
        latest_votes: dict[str, str] | None = None
        for existing in reversed(candidate_rounds):
            if existing.exile_runoff_votes:
                latest_votes = existing.exile_runoff_votes
                break
            if existing.votes:
                latest_votes = existing.votes[-1]
                break
        if not latest_votes:
            return False
        counts = sorted(Counter(latest_votes.values()).values(), reverse=True)
        expected = (counts[0], counts[1] if len(counts) > 1 else 0)
        return asserted != expected

    def _speech_stage_context(
        self,
        action: str,
        round_state: RoundState,
        player: Player,
    ) -> tuple[list[str], list[str]]:
        active_players = (
            player.gamestate.current_players if player.gamestate else round_state.players
        )
        if action == ACTION_SHERIFF_SPEECH:
            return (
                [
                    str(entry.get("message") or "")
                    for entry in round_state.sheriff_speeches
                    if isinstance(entry, dict) and entry.get("message")
                ],
                round_state.sheriff_speech_order
                or round_state.sheriff_candidates
                or active_players,
            )
        if action == ACTION_SHERIFF_PK_SPEECH:
            return (
                [
                    str(entry.get("message") or "")
                    for entry in round_state.sheriff_pk_speeches
                    if isinstance(entry, dict) and entry.get("message")
                ],
                round_state.sheriff_pk_candidates or active_players,
            )
        if action == ACTION_EXILE_PK_SPEECH:
            return (
                [
                    str(entry.get("message") or "")
                    for entry in round_state.exile_pk_speeches
                    if isinstance(entry, dict) and entry.get("message")
                ],
                round_state.exile_pk_candidates or active_players,
            )
        return (
            [entry.message for entry in round_state.debate],
            round_state.speech_order or active_players,
        )

    def _speech_quality_report(
        self,
        request: PlayerActionRequest,
        lm_log: LmLog,
    ) -> SpeechQualityReportV1 | None:
        result = lm_log.result or {}
        text = result.get(request.result_key)
        if not isinstance(text, str) or not text.strip():
            return None
        prior_texts = request.world_state.get("speech_prior_texts")
        return evaluate_speech_quality(
            text=text,
            mission=speech_mission_from_dict(request.world_state.get("speech_mission")),
            prior_texts=(
                [str(item) for item in prior_texts] if isinstance(prior_texts, list) else []
            ),
            personality=request.player.personality,
        )

    def _attach_speech_quality_metadata(
        self,
        *,
        request: PlayerActionRequest,
        lm_log: LmLog,
        report: SpeechQualityReportV1 | None,
        attempt_count: int,
        retry_exhausted: bool,
        initial_codes: list[str],
        retry_duration_ms: int = 0,
    ) -> None:
        if request.action not in BUFFERED_QUALITY_ACTIONS:
            return
        mission = request.world_state.get("speech_mission")
        lm_log.speech_mission = copy.deepcopy(mission) if isinstance(mission, dict) else None
        lm_log.speech_quality_report = report.to_dict() if report else None
        lm_log.speech_quality_attempt_count = attempt_count
        lm_log.speech_quality_retry_exhausted = retry_exhausted
        lm_log.speech_quality_initial_codes = initial_codes.copy()
        lm_log.speech_quality_retry_duration_ms = max(0, retry_duration_ms)

    def _quality_retry_duration_ms(self, started_at: float | None) -> int:
        if started_at is None:
            return 0
        return max(0, round((self.monotonic() - started_at) * 1000))

    def _timeout_fallback_result(
        self,
        request: PlayerActionRequest,
        *,
        started_at: float,
        budget_ms: int | None,
        timeout_source: Literal["action", "batch"] = "action",
        attempt_outcomes: object = None,
    ) -> PlayerActionResult:
        result: dict[str, object]
        execution_status: Literal["fallback", "failed"] = "fallback"
        failure_reason: str | None = None
        if request.action == ACTION_EXILE_LAST_WORDS:
            value = ""
            result = {request.result_key: value}
            reason = "timeout_last_words_skipped"
        elif request.action in BUFFERED_QUALITY_ACTIONS:
            value = ""
            result = {request.result_key: value}
            reason = "timeout"
            failure_reason = reason
            execution_status = "failed"
        elif request.action in OPTIONAL_NO_ACTIONS:
            value = None
            result = {request.result_key: None}
            reason = "timeout_optional_no_action"
        else:
            optional_fallback = self._optional_fallback_choice(request)
            if optional_fallback is not None:
                value = optional_fallback
                result = {request.result_key: self._public_action_value(value)}
                reason = "timeout_optional_abstain"
            elif request.options:
                value = self._deterministic_timeout_choice(request)
                result = {request.result_key: self._public_action_value(value)}
                if request.action in PRIVATE_LENGTH_BUDGETED_ACTIONS:
                    result["message"] = ""
                reason = "timeout_deterministic_legal_choice"
            else:
                value = ""
                result = {request.result_key: value}
                reason = "timeout_empty_private_text"
        if timeout_source == "batch":
            reason = (
                "batch_deadline"
                if reason == "timeout"
                else reason.replace("timeout_", "batch_deadline_", 1)
            )
            if failure_reason is not None:
                failure_reason = reason
        if request.action in RULE_DEFAULT_FALLBACK_ACTIONS:
            reason_code = "rule_default"
        elif timeout_source == "batch":
            reason_code = "batch_deadline"
        else:
            reason_code = "timeout"
        safe_outcomes = safe_attempt_outcomes(attempt_outcomes)
        return PlayerActionResult(
            request=request,
            value=value,
            lm_log=LmLog(
                prompt="",
                raw_response="",
                result=result,
                action_id=request.action_id,
                request_id=(
                    safe_outcomes[-1]["request_id"]
                    if safe_outcomes
                    else None
                ),
                attempt_outcomes=safe_outcomes,
            ),
            execution_status=execution_status,
            duration_ms=max(
                0,
                round((self.monotonic() - started_at) * 1000),
            ),
            budget_ms=budget_ms,
            fallback_reason=reason if execution_status == "fallback" else None,
            reason_code=failure_reason or reason_code,
        )

    def _deterministic_timeout_choice(
        self,
        request: PlayerActionRequest,
    ) -> str:
        material = ":".join(
            [
                str(self.fallback_seed),
                str(request.round_state.number),
                request.phase,
                request.player.name,
                request.action,
            ]
        )
        return min(
            request.options,
            key=lambda option: hashlib.sha256(f"{material}:{option}".encode()).hexdigest(),
        )

    def _finalize_player_action_result(
        self,
        result: PlayerActionResult,
        *,
        checkpoint: bool = True,
    ) -> tuple[object | None, ActionLog]:
        request = result.request
        player = request.player
        value = result.value
        lm_log = result.lm_log
        if request.action in BUFFERED_QUALITY_ACTIONS and lm_log.speech_quality_report is None:
            self._attach_speech_quality_metadata(
                request=request,
                lm_log=lm_log,
                report=self._speech_quality_report(request, lm_log),
                attempt_count=1,
                retry_exhausted=False,
                initial_codes=[],
            )
        effective_delivery: dict[str, object] | None = None
        effective_context_texts: list[str] = []
        speech_text = (
            value
            if request.action in BUFFERED_QUALITY_ACTIONS
            else (lm_log.result or {}).get("message")
            if request.action in PRIVATE_LENGTH_BUDGETED_ACTIONS
            else None
        )
        delivery_mapping_version = DELIVERY_MAPPING_VERSION
        if isinstance(speech_text, str) and speech_text.strip():
            mind = self._actor_minds.get(player.name)
            plan = request.world_state.get("public_turn_plan")
            safe_plan = plan if isinstance(plan, dict) else {}
            if (
                self.liveness_experience.feature_modes.affect_delivery == "on"
                and mind is not None
            ):
                effective_delivery = compile_affect_delivery_v2(
                    base_mood=player.base_delivery_mood,
                    base_intensity=player.base_delivery_intensity,
                    base_pace=player.base_delivery_pace,
                    base_instruction=player.base_delivery_instruction,
                    public_affect=public_affect_projection(mind),
                    speech_act=(
                        str(safe_plan.get("primary_speech_act"))
                        if safe_plan.get("primary_speech_act") is not None
                        else None
                    ),
                    phase=request.phase,
                )
                delivery_mapping_version = AFFECT_DELIVERY_MAPPING_VERSION
            else:
                effective_delivery = delivery_from_result(
                    lm_log.result,
                    base_mood=player.base_delivery_mood,
                    base_intensity=player.base_delivery_intensity,
                    base_pace=player.base_delivery_pace,
                    base_instruction=player.base_delivery_instruction,
                )
            effective_context_texts = compile_context_texts(
                effective_delivery,
                dialect=player.tts_dialect,
            )
            normalized_result = dict(lm_log.result or {})
            normalized_result["delivery"] = copy.deepcopy(effective_delivery)
            lm_log.result = normalized_result
        voice_snapshot = (
            {
                "enabled": player.voice_enabled,
                "speaker": player.tts_speaker,
                "effective_delivery": copy.deepcopy(effective_delivery),
                "effective_context_texts": effective_context_texts.copy(),
                "voice_config_version": player.voice_config_version,
                "delivery_mapping_version": delivery_mapping_version,
            }
            if effective_delivery is not None
            else None
        )
        if request.event_visibility == "public":
            self._publish_committed_speech_segments(
                request=request,
                lm_log=lm_log,
                voice_snapshot=voice_snapshot,
            )
        if (
            self.liveness_experience.experience_revision != "legacy-v0"
            and isinstance(speech_text, str)
            and speech_text.strip()
        ):
            lm_log.liveness_timing.setdefault(
                "first_clause_committed_at",
                round(time.time() * 1000),
            )
        action_log = ActionLog(
            actor=player.name,
            action=request.action,
            options=request.options,
            choice=str(value) if value is not None else None,
            lm_log=lm_log,
            raw_choice=lm_log.raw_choice,
            choice_normalization_kind=lm_log.choice_normalization_kind,
            speech_mission=copy.deepcopy(lm_log.speech_mission),
            speech_quality_report=copy.deepcopy(lm_log.speech_quality_report),
            speech_quality_attempt_count=lm_log.speech_quality_attempt_count,
            speech_quality_retry_exhausted=lm_log.speech_quality_retry_exhausted,
            speech_quality_initial_codes=lm_log.speech_quality_initial_codes.copy(),
            speech_quality_retry_duration_ms=lm_log.speech_quality_retry_duration_ms,
            execution_status=result.execution_status,
            duration_ms=result.duration_ms,
            budget_ms=result.budget_ms,
            reason_code=result.reason_code,
            first_token_ms=(lm_log.first_token_ms if self.action_budgets_enabled else None),
            fact_prompt_coverage=copy.deepcopy(request.fact_prompt_coverage),
            effective_delivery=copy.deepcopy(effective_delivery),
            effective_context_texts=effective_context_texts.copy(),
            voice_config_version=player.voice_config_version,
            delivery_mapping_version=(
                delivery_mapping_version if effective_delivery is not None else None
            ),
            liveness_experience_revision=self.liveness_experience.experience_revision,
            prompt_chars=len(lm_log.prompt),
            scene_packet_chars=(
                len(
                    json.dumps(
                        request.world_state.get("actor_scene_packet"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                if isinstance(request.world_state.get("actor_scene_packet"), dict)
                else None
            ),
            liveness_timing=lm_log.liveness_timing.copy(),
            speech_turn_receipt=copy.deepcopy(lm_log.speech_turn_receipt),
        )
        if result.fallback_reason is not None:
            action_log.fallback_reason = result.fallback_reason
            action_log.fallback_choice = value
            action_log.effective_origin = "system_fallback"
        if lm_log.speech_quality_report is not None:
            record_speech_quality(
                phase=request.phase,
                report=lm_log.speech_quality_report,
                attempt_count=lm_log.speech_quality_attempt_count,
                retry_exhausted=lm_log.speech_quality_retry_exhausted,
                retry_duration_ms=lm_log.speech_quality_retry_duration_ms,
            )
        invalid_error = self._invalid_player_action_error(result)
        if invalid_error is not None:
            if request.action in BUFFERED_QUALITY_ACTIONS:
                invalid_value = self._invalid_value_from_result(result)
                value = ""
                normalized_result = {request.result_key: ""}
                lm_log.result = normalized_result
                effective_delivery = None
                effective_context_texts = []
                action_log.choice = None
                action_log.invalid_value = invalid_value
                action_log.fallback_choice = None
                action_log.fallback_reason = None
                action_log.reason_code = (
                    result.reason_code
                    or (
                        "quality_exhausted"
                        if lm_log.speech_quality_retry_exhausted
                        else "invalid_exhausted"
                    )
                )
                action_log.execution_status = "failed"
                action_log.effective_origin = "none"
                action_log.effective_delivery = None
                action_log.effective_context_texts = []
                action_log.delivery_mapping_version = None
            else:
                fallback_choice = self._optional_fallback_choice(request)
                fallback_reason = "optional_action_invalid"
                allow_none_fallback = request.action in OPTIONAL_NO_ACTIONS
                if allow_none_fallback:
                    fallback_reason = "invalid_optional_no_action"
                elif request.action in DETERMINISTIC_PUBLIC_FALLBACK_ACTIONS:
                    fallback_choice = self._deterministic_timeout_choice(request)
                    fallback_reason = "invalid_deterministic_legal_choice"
                if request.action == ACTION_EXILE_LAST_WORDS:
                    fallback_choice = ""
                    fallback_reason = "last_words_invalid_skipped"
                if request.action in RULE_DEFAULT_FALLBACK_ACTIONS:
                    fallback_reason = "invalid_rule_default"
                if fallback_choice is None and not allow_none_fallback:
                    raise invalid_error
                invalid_value = self._invalid_value_from_result(result)
                value = fallback_choice
                fallback_result = dict(lm_log.result or {})
                fallback_result[request.result_key] = fallback_choice
                lm_log.result = fallback_result
                action_log.choice = (
                    str(fallback_choice) if fallback_choice is not None else None
                )
                action_log.invalid_value = invalid_value
                action_log.fallback_choice = fallback_choice
                action_log.fallback_reason = fallback_reason
                action_log.reason_code = (
                    "rule_default"
                    if request.action in RULE_DEFAULT_FALLBACK_ACTIONS
                    else "invalid_exhausted"
                )
                action_log.execution_status = "fallback"
                action_log.effective_origin = "system_fallback"
                action_log.attempt_count = max(1, len(lm_log.invalid_attempts))
                if request.event_visibility == "public":
                    self._publish_invalid_action_fallback_warning(
                        request=request,
                        invalid_value=invalid_value,
                        fallback_choice=fallback_choice,
                        warning="off_option_fallback",
                    )
        elif checkpoint and self._is_checkpointable_player_action_result(result):
            self._record_accepted_actor_behavior(request, lm_log)
            self._checkpoint_player_action_success(result)
        if self.action_budgets_enabled:
            record_action_execution(
                action_kind=self.action_execution_budget.for_action(request.action).kind,
                model=player.model,
                result=action_log.execution_status,
                duration_ms=action_log.duration_ms,
                first_token_ms=action_log.first_token_ms,
                fallback_reason=action_log.fallback_reason,
                action_id=lm_log.action_id or request.action_id,
            )
        if request.event_visibility == "public":
            if (
                request.action in BUFFERED_QUALITY_ACTIONS
                and action_log.execution_status == "failed"
            ):
                self._publish_player_did_not_speak(request, action_log)
            record_model_progress_event("model_response_received")
            self._publish(
                "model_response_received",
                round_number=request.round_state.number,
                phase=request.phase,
                actor=player.name,
                action=request.action,
                payload={
                    "action_id": lm_log.action_id,
                    "request_id": lm_log.request_id,
                    "model": player.model,
                    "message": "模型返回已接收，正在解析行动",
                },
            )
            visible_result = _visible_action_result(request.action, lm_log.result)
            parsed_payload = {
                "action_id": lm_log.action_id,
                "request_id": lm_log.request_id,
                "choice": self._public_action_value(action_log.choice),
                "result": visible_result,
                "visible_result": visible_result,
                "options": request.public_options.copy(),
                "action_origin": _effective_action_origin(action_log),
                "public_reason_code": _public_action_reason_code(action_log),
                "speech_status": (
                    "not_spoken"
                    if request.action in BUFFERED_QUALITY_ACTIONS
                    and action_log.execution_status == "failed"
                    else "spoken"
                    if request.action in BUFFERED_QUALITY_ACTIONS
                    else None
                ),
                "retry_completed": len(lm_log.attempt_outcomes) > 1
                or lm_log.speech_quality_attempt_count > 1,
            }
            if lm_log.speech_id is not None:
                receipt_status = (
                    lm_log.speech_turn_receipt.get("status")
                    if isinstance(lm_log.speech_turn_receipt, dict)
                    else None
                )
                speech_stream_mode = (
                    lm_log.speech_turn_receipt.get("speech_stream_mode")
                    if isinstance(lm_log.speech_turn_receipt, dict)
                    else None
                )
                if speech_stream_mode != "segments_v2":
                    raise RuntimeError("committed speech receipt has invalid stream mode")
                segment_count = len(lm_log.committed_speech_segments)
                parsed_payload.update(
                    {
                        "schema_version": 1,
                        "speech_id": lm_log.speech_id,
                        "speech_stream_mode": speech_stream_mode,
                        "segment_count": segment_count,
                        "speech_status": (
                            "partial"
                            if receipt_status == "partial"
                            else "interrupted"
                            if receipt_status == "interrupted"
                            else "spoken"
                        ),
                        "tts_suppressed_by_segments": True,
                        "final_segment_index": segment_count - 1,
                    }
                )
            if voice_snapshot is not None:
                parsed_payload["voice_snapshot"] = copy.deepcopy(voice_snapshot)
            if request.action == ACTION_EXILE_LAST_WORDS:
                speech_presentation_id = (
                    self._terminal_exile_last_words_presentation_id("speech")
                )
                if speech_presentation_id is not None:
                    parsed_payload["presentation_id"] = speech_presentation_id
            if action_log.fallback_choice is not None:
                parsed_payload.update(
                    {
                        "invalid_value": action_log.invalid_value,
                        "fallback_choice": self._public_action_value(
                            action_log.fallback_choice,
                        ),
                        "fallback_reason": action_log.fallback_reason,
                        "attempt_count": action_log.attempt_count,
                    }
                )
            parsed_event = self._publish(
                "action_parsed",
                round_number=request.round_state.number,
                phase=request.phase,
                actor=player.name,
                action=request.action,
                payload=parsed_payload,
            )
            self._checkpoint_segments_v2_seal(
                request=request,
                lm_log=lm_log,
                parsed_event=parsed_event,
            )
            if (
                lm_log.speech_id is not None
                and isinstance(lm_log.speech_turn_receipt, dict)
                and lm_log.speech_turn_receipt.get("status") == "interrupted"
            ):
                active_speech = self._active_committed_speech.get(
                    request.action_id,
                    {},
                )
                self._publish(
                    "speech_turn_interrupted",
                    round_number=request.round_state.number,
                    phase=request.phase,
                    actor=player.name,
                    action=request.action,
                    payload={
                        "schema_version": 1,
                        "action_id": request.action_id,
                        "speech_id": lm_log.speech_id,
                        "speech_status": "interrupted",
                        "visible_text": "".join(lm_log.committed_speech_segments),
                        "committed_segment_count": len(
                            lm_log.committed_speech_segments
                        ),
                        "interruption_mode": "sentence_boundary",
                        "reason": active_speech.get(
                            "interruption_reason",
                            "phase_advanced",
                        ),
                        "trigger_source": copy.deepcopy(
                            active_speech.get("trigger_source")
                        ),
                    },
                )
            self._active_committed_speech.pop(request.action_id, None)
        if request.action in BUFFERED_QUALITY_ACTIONS:
            receipt_status = (
                lm_log.speech_turn_receipt.get("status")
                if isinstance(lm_log.speech_turn_receipt, dict)
                else None
            )
            liveness_result = (
                receipt_status
                if receipt_status in {"complete", "partial", "interrupted"}
                else "failed"
                if action_log.execution_status in {"failed", "timed_out", "canceled"}
                else "complete"
            )
            record_liveness_speech(
                action=request.action,
                experience_revision=self.liveness_experience.experience_revision,
                result=liveness_result,
                timing=action_log.liveness_timing,
                hard_rejected_count=lm_log.hard_speech_gate_rejected_count,
            )
        return value, action_log

    def _player_actions_batch(
        self,
        requests: list[PlayerActionRequest],
    ) -> list[tuple[object | None, ActionLog]]:
        if not requests:
            return []
        for request in requests:
            self._require_non_terminal_player_action(
                action=request.action,
                player=request.player,
                terminal_settlement_allowed=request.terminal_settlement_allowed,
            )
        if len(requests) == 1:
            return [self._player_action_single(requests[0])]

        for request in requests:
            self._publish_player_action_requested(request)

        batch_started_at = self.monotonic()
        batch_timeout = self._batch_deadline_seconds(requests)
        batch_deadline_at = (
            batch_started_at + batch_timeout if batch_timeout is not None else None
        )
        results: list[PlayerActionResult | None] = [None] * len(requests)
        exceptions: dict[int, Exception] = {}
        condition = threading.Condition()
        next_index = {"value": 0}
        gates = [
            _PublishGateSink(
                self.event_sink,
                deadline_at_monotonic=batch_deadline_at,
                monotonic=self.monotonic,
            )
            for _request in requests
        ]
        executor = ThreadPoolExecutor(max_workers=len(requests))
        futures = {
            executor.submit(
                self._execute_player_action_request,
                request,
                _OrderedBatchProvider(
                    provider=self.provider,
                    index=index,
                    condition=condition,
                    next_index=next_index,
                ),
                gates[index],
            ): index
            for index, request in enumerate(requests)
        }
        done, pending = wait(futures, timeout=batch_timeout)
        late_done: set[Future[PlayerActionResult]] = set()
        for future in done:
            index = futures[future]
            try:
                candidate_result = future.result()
                if gates[index].result_was_late():
                    late_done.add(future)
                else:
                    results[index] = candidate_result
            except Exception as exc:
                if gates[index].result_was_late():
                    late_done.add(future)
                else:
                    exceptions[index] = exc
        deadline_futures = set(pending) | late_done
        for future in deadline_futures:
            index = futures[future]
            gates[index].close()
            canceled = future.cancel()
            request = requests[index]
            if not canceled:
                future.add_done_callback(
                    lambda _future, gate=gates[index], late_request=request: (
                        gate.publish_late_discard(late_request)
                    )
                )
            budget_spec = self.action_execution_budget.for_action(request.action)
            results[index] = self._timeout_fallback_result(
                request,
                started_at=batch_started_at,
                budget_ms=round(budget_spec.total_budget_seconds * 1000),
                timeout_source="batch",
                attempt_outcomes=gates[index].attempt_outcomes(),
            )
        if self.action_budgets_enabled:
            record_action_batch(
                action_kind=self.action_execution_budget.for_action(requests[0].action).kind,
                result=(
                    "deadline"
                    if deadline_futures
                    else "failed"
                    if exceptions
                    else "completed"
                ),
                duration_ms=max(
                    0,
                    round((self.monotonic() - batch_started_at) * 1000),
                ),
            )
        executor.shutdown(
            wait=not deadline_futures,
            cancel_futures=bool(deadline_futures),
        )

        if exceptions:
            self._checkpoint_player_action_results(results)
            first_failed_index = min(exceptions)
            request = requests[first_failed_index]
            exc = exceptions[first_failed_index]
            self._checkpoint_player_action_failure(request, exc)
            raise exc

        self._checkpoint_player_action_results(results)
        finalized: list[tuple[object | None, ActionLog]] = []
        for result in results:
            if result is None:
                raise RuntimeError("Player action batch completed without a result.")
            try:
                finalized.append(self._finalize_player_action_result(result, checkpoint=False))
            except Exception as exc:
                self._checkpoint_player_action_failure(result.request, exc)
                raise
        return finalized

    def _batch_deadline_seconds(
        self,
        requests: list[PlayerActionRequest],
    ) -> float | None:
        if not self.action_budgets_enabled:
            return None
        deadlines = [
            deadline
            for request in requests
            if (
                deadline := self.action_execution_budget.for_action(
                    request.action
                ).batch_deadline_seconds
            )
            is not None
        ]
        return min(deadlines) if deadlines else None

    def _player_action_single(
        self,
        request: PlayerActionRequest,
    ) -> tuple[object | None, ActionLog]:
        self._require_non_terminal_player_action(
            action=request.action,
            player=request.player,
            terminal_settlement_allowed=request.terminal_settlement_allowed,
        )
        self._publish_player_action_requested(request)
        try:
            result = self._execute_player_action_request(request)
        except _PublicActionInterruptedBySelfExplosion:
            raise
        except Exception as exc:
            self._checkpoint_player_action_failure(request, exc)
            raise
        try:
            return self._finalize_player_action_result(result)
        except Exception as exc:
            self._checkpoint_player_action_failure(request, exc)
            raise

    def _checkpoint_player_action_success(self, result: PlayerActionResult) -> None:
        request = result.request
        checkpoint_receipt = copy.deepcopy(result.lm_log.speech_turn_receipt)
        if (
            isinstance(checkpoint_receipt, dict)
            and checkpoint_receipt.get("speech_stream_mode") == "segments_v2"
        ):
            checkpoint_receipt["status"] = "partial"
            checkpoint_receipt.pop("final_segment_index", None)
            checkpoint_receipt.pop("sealed_source_run_id", None)
            checkpoint_receipt.pop("sealed_source_event_id", None)
        self._checkpoint_model_success(
            actor=request.player.name,
            action=request.action,
            phase=request.phase,
            model=request.player.model,
            raw_response=result.lm_log.raw_response,
            prompt=result.lm_log.prompt,
            logical_action_id=request.action_id,
            speech_turn_receipt=checkpoint_receipt,
        )

    def _checkpoint_segments_v2_seal(
        self,
        *,
        request: PlayerActionRequest,
        lm_log: LmLog,
        parsed_event: object | None,
    ) -> None:
        receipt = lm_log.speech_turn_receipt
        if (
            not isinstance(receipt, dict)
            or receipt.get("speech_stream_mode") != "segments_v2"
            or self.checkpoint_manager is None
        ):
            return
        source_run_id = getattr(parsed_event, "run_id", None)
        source_event_id = getattr(parsed_event, "id", None)
        if (
            not isinstance(source_run_id, str)
            or not source_run_id
            or type(source_event_id) is not int
        ):
            return
        recorder = getattr(
            self.checkpoint_manager,
            "record_speech_turn_receipt",
            None,
        )
        if not callable(recorder):
            return
        sealed_receipt = copy.deepcopy(receipt)
        sealed_receipt.update(
            {
                "final_segment_index": len(lm_log.committed_speech_segments) - 1,
                "sealed_source_run_id": source_run_id,
                "sealed_source_event_id": source_event_id,
            }
        )
        recorder(request.action_id, sealed_receipt)

    def _checkpoint_player_action_results(
        self,
        results: list[PlayerActionResult | None],
    ) -> None:
        for result in results:
            if result is not None and self._is_checkpointable_player_action_result(result):
                self._checkpoint_player_action_success(result)

    def _is_checkpointable_player_action_result(
        self,
        result: PlayerActionResult,
    ) -> bool:
        return (
            result.execution_status == "completed"
            and result.fallback_reason is None
            and self._invalid_player_action_error(result) is None
        )

    def _publish_player_action_requested(self, request: PlayerActionRequest) -> None:
        if request.event_visibility == "private":
            return
        self._publish(
            "action_requested",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload={
                "action_id": request.action_id,
                "options": request.public_options.copy(),
                "result_key": request.result_key,
            },
        )

    def _require_non_terminal_player_action(
        self,
        *,
        action: str | None = None,
        player: Player | None = None,
        terminal_settlement_allowed: bool = False,
    ) -> None:
        if self.state.winner:
            raise RuntimeError("Cannot request player action after game is terminal")
        active_players = self._current_active_players()
        if not active_players or not self._get_winner(active_players):
            return
        if (
            action == ACTION_HUNTER_SHOOT
            and player is not None
            and player.role == HUNTER
            and player.hunter_can_shoot
            and player.name not in active_players
            and terminal_settlement_allowed
        ):
            return
        raise RuntimeError("Cannot request player action after game is terminal")

    def _checkpoint_player_action_failure(
        self,
        request: PlayerActionRequest,
        exc: Exception,
    ) -> None:
        self._checkpoint_model_failure(
            actor=request.player.name,
            action=request.action,
            phase=request.phase,
            model=request.player.model,
            error=str(exc),
        )

    def _invalid_player_action_error(self, result: PlayerActionResult) -> ValueError | None:
        request = result.request
        if (
            request.action in OPTIONAL_NO_ACTIONS
            and result.execution_status == "fallback"
            and result.value is None
        ):
            return None
        if request.action in BUFFERED_QUALITY_ACTIONS and (
            not isinstance(result.value, str) or not result.value.strip()
        ):
            return ValueError(
                f"{request.player.name} did not return a valid {request.action} message."
            )
        if request.options and result.value not in request.options:
            return ValueError(
                f"{request.player.name} returned invalid {request.action}: {result.value}"
            )
        return None

    def _optional_fallback_choice(self, request: PlayerActionRequest) -> object | None:
        fallback = OPTIONAL_ACTION_FALLBACKS.get(request.action)
        if fallback is not None and fallback in request.options:
            return fallback
        return None

    def _invalid_value_from_result(self, result: PlayerActionResult) -> object | None:
        if result.value is not None:
            return result.value
        if result.lm_log.invalid_attempts:
            return result.lm_log.invalid_attempts[-1].get("value")
        return None

    def _publish_invalid_action_fallback_warning(
        self,
        *,
        request: PlayerActionRequest,
        invalid_value: object | None,
        fallback_choice: object,
        warning: str,
    ) -> None:
        self._publish(
            "action_quality_warning",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload={
                "warnings": [warning],
                "invalid_value": invalid_value,
                "fallback_choice": self._public_action_value(fallback_choice),
                "allowed_values": request.public_options.copy(),
            },
        )

    def _publish_player_did_not_speak(
        self,
        request: PlayerActionRequest,
        action_log: ActionLog,
    ) -> None:
        public_player = self._public_player_reference(request.player.name)
        reason_code = _public_action_reason_code(action_log) or "failed"
        visible_text = f"{public_player}本轮未发言。"
        self._publish(
            "player_did_not_speak",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload={
                "schema_version": 1,
                "visible_text": visible_text,
                "speech_status": "not_spoken",
                "action_origin": "none",
                "public_reason_code": reason_code,
            },
        )
        self._add_public_fact(
            request.round_state.number,
            "interruption",
            f"第{request.round_state.number}轮：{visible_text}",
            stage=request.action,
            actor=request.player.name,
            retention="important",
            details={
                "speech_status": "not_spoken",
                "public_reason_code": reason_code,
            },
        )

    def _checkpoint_round_start(
        self,
        *,
        round_number: int,
        active_players: list[str],
        logs: list[RoundLog],
    ) -> None:
        if self.checkpoint_manager is None:
            return
        self.checkpoint_manager.start_round(
            state=copy.deepcopy(self.state),
            logs=copy.deepcopy(logs),
            round_number=round_number,
            active_players=active_players.copy(),
            rng_state=self.rng.getstate(),
        )
        recorder = getattr(self.checkpoint_manager, "record_actor_minds", None)
        if callable(recorder) and self._actor_minds:
            recorder(self._actor_minds, at_round_start=True)

    def _record_accepted_actor_behavior(
        self,
        request: PlayerActionRequest,
        lm_log: LmLog,
    ) -> None:
        mind = self._actor_minds.get(request.player.name)
        if mind is None or request.action not in BUFFERED_QUALITY_ACTIONS:
            return
        if self.checkpoint_manager is not None:
            recorded = getattr(
                self.checkpoint_manager,
                "cached_model_response_exists",
                None,
            )
            if callable(recorded) and recorded(
                actor=request.player.name,
                action=request.action,
                phase=request.phase,
                model=request.player.model,
                prompt=lm_log.prompt,
            ):
                return
        plan = request.world_state.get("public_turn_plan")
        safe_plan = plan if isinstance(plan, dict) else {}
        updated = ActorMindReducer().record_behavior(
            mind,
            speech_act=str(safe_plan.get("primary_speech_act") or "respond"),
            length_band=str(safe_plan.get("length_band") or "normal"),
            opening_fingerprint=hashlib.sha256(
                str((request.world_state.get("speech_prior_texts") or [""])[-1]).encode()
            ).hexdigest()[:16],
        )
        self._actor_minds[request.player.name] = updated

    def _checkpoint_model_success(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        raw_response: str,
        prompt: str | None = None,
        logical_action_id: str | None = None,
        speech_turn_receipt: Mapping[str, object] | None = None,
    ) -> None:
        if self.checkpoint_manager is None:
            return
        self.checkpoint_manager.record_success(
            actor=actor,
            action=action,
            phase=phase,
            model=model,
            raw_response=raw_response,
            prompt=prompt,
            actor_minds=self._actor_minds,
            logical_action_id=logical_action_id,
            speech_turn_receipt=speech_turn_receipt,
        )

    def _checkpoint_model_failure(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        error: str,
    ) -> None:
        if self.checkpoint_manager is None:
            return
        self.checkpoint_manager.record_failure(
            actor=actor,
            action=action,
            phase=phase,
            model=model,
            error=error,
        )

    def _restore_lifecycle_contract(self) -> None:
        checkpoint_events: list[Mapping[str, object]] = []
        if self.checkpoint_manager is not None:
            loader = getattr(self.checkpoint_manager, "lifecycle_events", None)
            if callable(loader):
                loaded = loader()
                if not isinstance(loaded, list):
                    raise ResumeCheckpointError("invalid_structure")
                checkpoint_events = loaded

        persisted_events: list[Mapping[str, object]] = []
        persisted_loader = getattr(self.event_sink, "lifecycle_events", None)
        if callable(persisted_loader):
            for event in persisted_loader():
                event_type = (
                    event.get("type")
                    if isinstance(event, Mapping)
                    else getattr(event, "type", None)
                )
                event_id = (
                    event.get("id")
                    if isinstance(event, Mapping)
                    else getattr(event, "id", None)
                )
                round_number = (
                    event.get("round_number", event.get("round"))
                    if isinstance(event, Mapping)
                    else getattr(event, "round", None)
                )
                phase = (
                    event.get("phase")
                    if isinstance(event, Mapping)
                    else getattr(event, "phase", None)
                )
                payload = (
                    event.get("payload")
                    if isinstance(event, Mapping)
                    else getattr(event, "payload", None)
                )
                stream_id = (
                    event.get("run_id")
                    if isinstance(event, Mapping)
                    else getattr(event, "run_id", None)
                )
                if stream_id is None:
                    stream_id = getattr(self.event_sink, "run_id", None)
                if (
                    event_type not in {"phase_started", "phase_completed"}
                    or type(event_id) is not int
                    or type(round_number) is not int
                    or type(phase) is not str
                    or not isinstance(payload, Mapping)
                    or type(payload.get("phase_instance_id")) is not str
                ):
                    continue
                persisted_events.append(
                    lifecycle_event_entry(
                        lifecycle_kind=event_type,
                        phase_instance_id=str(payload["phase_instance_id"]),
                        round_number=round_number,
                        phase=phase,
                        event_id=event_id,
                        payload=payload,
                        stream_id=(stream_id if isinstance(stream_id, str) else None),
                    )
                )

        merged = merge_lifecycle_event_entries(
            checkpoint_events,
            persisted_events,
        )
        merged_events = merged.get("events", [])
        if not isinstance(merged_events, list):
            raise ResumeCheckpointError("invalid_structure")
        self._known_lifecycle_events = {
            (
                str(entry["phase_instance_id"]),
                str(entry["lifecycle_kind"]),
            ): copy.deepcopy(entry)
            for entry in merged_events
        }
        lifecycle_by_instance: dict[str, dict[str, dict[str, object]]] = {}
        for entry in merged_events:
            phase_instance_id = str(entry["phase_instance_id"])
            lifecycle_by_instance.setdefault(phase_instance_id, {})[
                str(entry["lifecycle_kind"])
            ] = entry
        for phase_instance_id, instance in lifecycle_by_instance.items():
            started = instance.get("phase_started")
            if started is None:
                continue
            key = (int(started["round_number"]), str(started["phase"]))
            try:
                occurrence = int(phase_instance_id.rsplit(":", 1)[1])
            except (IndexError, ValueError) as exc:
                raise ResumeCheckpointError("invalid_structure") from exc
            self._max_persisted_phase_occurrences[key] = max(
                occurrence,
                self._max_persisted_phase_occurrences.get(key, 0),
            )
            completed = instance.get("phase_completed")
            completion_payload = (
                completed.get("payload")
                if isinstance(completed, Mapping)
                else None
            )
            forced_failure = bool(
                isinstance(completion_payload, Mapping)
                and completion_payload.get("completion_status") == "canceled"
                and completion_payload.get("completion_reason") == "forced_failure"
            )
            if not forced_failure:
                self._reusable_phase_occurrences[key] = max(
                    occurrence,
                    self._reusable_phase_occurrences.get(key, 0),
                )
        if self.checkpoint_manager is not None and persisted_events:
            reconcile = getattr(
                self.checkpoint_manager,
                "reconcile_lifecycle_events",
                None,
            )
            if callable(reconcile):
                reconcile(persisted_events)

    def _next_phase_occurrence(self, key: tuple[int, str]) -> int:
        if key not in self._initialized_phase_occurrences:
            self._initialized_phase_occurrences.add(key)
            occurrence = self._reusable_phase_occurrences.get(key)
            if occurrence is None:
                occurrence = self._max_persisted_phase_occurrences.get(key, 0) + 1
            self._phase_occurrences[key] = occurrence
            return occurrence
        self._phase_occurrences[key] += 1
        return self._phase_occurrences[key]

    def _close_recovered_terminal_lifecycle(
        self,
        active_players: list[str],
    ) -> None:
        completed_instances = {
            phase_instance_id
            for phase_instance_id, lifecycle_kind in self._known_lifecycle_events
            if lifecycle_kind == "phase_completed"
        }
        open_starts = [
            entry
            for (phase_instance_id, lifecycle_kind), entry in self._known_lifecycle_events.items()
            if lifecycle_kind == "phase_started"
            and phase_instance_id not in completed_instances
        ]
        if not open_starts:
            return
        if len(open_starts) != 1 or not self.state.rounds:
            raise RuntimeError("Terminal recovery has an ambiguous open lifecycle phase")
        started = open_starts[0]
        round_number = int(started["round_number"])
        phase = str(started["phase"])
        phase_instance_id = str(started["phase_instance_id"])
        source_event_id = int(started["event_id"])
        key = (round_number, phase)
        self._active_phase_instances[key] = (phase_instance_id, source_event_id)
        round_state = self.state.rounds[-1]

        if phase == "sheriff_election" and round_state.werewolf_self_exploded:
            self._complete_phase(
                round_number=round_number,
                phase=phase,
                completion_status="canceled",
                completion_reason="self_explosion",
                next_phase="day",
                terminal=False,
            )
            self._start_phase(
                round_number=round_number,
                phase="day",
                payload={
                    "active_players": active_players.copy(),
                    "narration_mode": "explicit_v1",
                },
            )
            self._complete_phase(
                round_number=round_number,
                phase="day",
                completion_status="terminal",
                completion_reason="self_explosion",
                next_phase=None,
                terminal=True,
            )
            return

        completion_reason = (
            round_state.exile_resolution_reason or "vote_resolved"
            if phase == "vote"
            else "self_explosion"
            if phase == "day" and round_state.werewolf_self_exploded
            else "night_result_presented"
            if phase in {"night", "dawn_reveal"}
            else "terminal_recovery_completed"
        )
        self._complete_phase(
            round_number=round_number,
            phase=phase,
            completion_status="terminal",
            completion_reason=completion_reason,
            next_phase=None,
            terminal=True,
        )

    def _publish_lifecycle(
        self,
        event_type: Literal["phase_started", "phase_completed"],
        *,
        round_number: int,
        phase: str,
        actor: str | None,
        payload: dict[str, object],
    ) -> object | None:
        publisher = getattr(self.event_sink, "publish_lifecycle", None)
        if callable(publisher):
            return publisher(
                event_type,
                round_number=round_number,
                phase=phase,
                actor=actor,
                payload=payload,
            )
        return self.event_sink.publish(
            event_type,
            round_number=round_number,
            phase=phase,
            actor=actor,
            action=None,
            payload=payload,
        )

    def _known_lifecycle_receipt(
        self,
        *,
        lifecycle_kind: Literal["phase_started", "phase_completed"],
        phase_instance_id: str,
        round_number: int,
        phase: str,
        payload: Mapping[str, object],
    ) -> _LifecycleEventReceipt | None:
        entry = self._known_lifecycle_events.get(
            (phase_instance_id, lifecycle_kind)
        )
        if entry is None:
            return None
        if (
            entry.get("round_number") != round_number
            or entry.get("phase") != phase
            or entry.get("payload") != dict(payload)
            or type(entry.get("event_id")) is not int
        ):
            raise RuntimeError("Lifecycle replay conflicts with the persisted contract")
        return _LifecycleEventReceipt(id=int(entry["event_id"]))

    def _record_lifecycle_receipt(
        self,
        *,
        lifecycle_kind: Literal["phase_started", "phase_completed"],
        phase_instance_id: str,
        round_number: int,
        phase: str,
        payload: Mapping[str, object],
        event: object | None,
    ) -> None:
        event_id = getattr(event, "id", None)
        if type(event_id) is not int:
            return
        key = (phase_instance_id, lifecycle_kind)
        existing = self._known_lifecycle_events.get(key)
        existing_stream_id = (
            existing.get("stream_id") if isinstance(existing, Mapping) else None
        )
        entry = lifecycle_event_entry(
            lifecycle_kind=lifecycle_kind,
            phase_instance_id=phase_instance_id,
            round_number=round_number,
            phase=phase,
            event_id=event_id,
            payload=payload,
            stream_id=(
                str(existing_stream_id)
                if isinstance(existing_stream_id, str)
                else str(self.event_sink.run_id)
                if isinstance(getattr(self.event_sink, "run_id", None), str)
                else None
            ),
        )
        if existing is not None and existing != entry:
            raise RuntimeError("Lifecycle event identity is not unique")
        self._known_lifecycle_events[key] = entry
        if self.checkpoint_manager is None:
            return
        recorder = getattr(self.checkpoint_manager, "record_lifecycle_event", None)
        if callable(recorder):
            recorder(
                lifecycle_kind=lifecycle_kind,
                phase_instance_id=phase_instance_id,
                round_number=round_number,
                phase=phase,
                event_id=event_id,
                payload=payload,
                stream_id=(
                    str(entry["stream_id"])
                    if isinstance(entry.get("stream_id"), str)
                    else None
                ),
            )

    def _publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> object | None:
        if (
            type(round_number) is int
            and type(phase) is str
            and (round_number, phase) in self._suppressed_phase_replays
            and event_type not in {"phase_started", "phase_completed"}
        ):
            return None
        published = self.event_sink.publish(
            event_type,
            round_number=round_number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
        )
        self._reduce_actor_minds_from_public_event(
            published,
            event_type=event_type,
            phase=phase,
            payload=payload or {},
        )
        return published

    def _reduce_actor_minds_from_public_event(
        self,
        published: object | None,
        *,
        event_type: str,
        phase: str | None,
        payload: dict[str, object],
    ) -> None:
        if not self._actor_minds or event_type not in {"phase_started", "state_updated"}:
            return
        source_run_id = getattr(published, "run_id", None)
        source_event_id = getattr(published, "id", None)
        if (
            not isinstance(source_run_id, str)
            or not source_run_id
            or type(source_event_id) is not int
            or source_event_id < 1
        ):
            return
        source = EventCoordinateV1(source_run_id, source_event_id)
        reducer = ActorMindReducer()
        stimuli: dict[str, ActorMindStimulusV1] = {}

        if event_type == "phase_started":
            urgency = 72 if phase in {"day", "sheriff_election", "exile"} else 45
            for target in self._actor_minds:
                stimuli[target] = ActorMindStimulusV1(
                    source=source,
                    kind="stage_pressure" if urgency >= 70 else "phase_decay",
                    urgency=urgency,
                )

        debate_entry = payload.get("debate_entry")
        if event_type == "state_updated" and isinstance(debate_entry, dict):
            speaker = debate_entry.get("speaker")
            message = debate_entry.get("message")
            if isinstance(speaker, str) and isinstance(message, str):
                compact = message.replace(" ", "")
                for target in self._actor_minds:
                    if target == speaker or target not in compact:
                        continue
                    kind: Literal["direct_question", "accusation", "support"] | None = None
                    if any(mark in compact for mark in ("?", "？", "回答", "解释")):
                        kind = "direct_question"
                    elif any(mark in compact for mark in ("同意", "认同", "站边", "支持")):
                        kind = "support"
                    elif any(mark in compact for mark in ("狼", "踩", "怀疑", "不信", "出")):
                        kind = "accusation"
                    if kind is not None:
                        stimuli[target] = ActorMindStimulusV1(
                            source=source,
                            kind=kind,
                            source_actor=speaker,
                            target=target,
                            urgency=78 if kind == "direct_question" else 66,
                        )

        votes = payload.get("votes")
        if event_type == "state_updated" and isinstance(votes, dict):
            for voter, target in votes.items():
                if (
                    isinstance(voter, str)
                    and isinstance(target, str)
                    and target in self._actor_minds
                    and voter != target
                ):
                    stimuli[target] = ActorMindStimulusV1(
                        source=source,
                        kind="vote",
                        source_actor=voter,
                        target=target,
                        urgency=82,
                    )

        for target, stimulus in stimuli.items():
            self._actor_minds[target] = reducer.apply(
                self._actor_minds[target],
                stimulus,
            )
        if stimuli and self.checkpoint_manager is not None:
            recorder = getattr(self.checkpoint_manager, "record_actor_minds", None)
            if callable(recorder):
                recorder(self._actor_minds)

    def _start_phase(
        self,
        *,
        round_number: int,
        phase: str,
        payload: dict[str, object],
        actor: str | None = None,
    ) -> str:
        key = (round_number, phase)
        current = self._active_phase_instances.get(key)
        if current is not None:
            return current[0]
        occurrence = self._next_phase_occurrence(key)
        phase_instance_id = f"phase:r{round_number}:{phase}:{occurrence}"
        event_payload = {**payload, "phase_instance_id": phase_instance_id}
        event = self._known_lifecycle_receipt(
            lifecycle_kind="phase_started",
            phase_instance_id=phase_instance_id,
            round_number=round_number,
            phase=phase,
            payload=event_payload,
        )
        if event is None:
            event = self._publish_lifecycle(
                "phase_started",
                round_number=round_number,
                phase=phase,
                actor=actor,
                payload=event_payload,
            )
        source_event_id = getattr(event, "id", None)
        self._active_phase_instances[key] = (
            phase_instance_id,
            source_event_id if type(source_event_id) is int else None,
        )
        if (phase_instance_id, "phase_completed") in self._known_lifecycle_events:
            self._suppressed_phase_replays.add(key)
        self._record_lifecycle_receipt(
            lifecycle_kind="phase_started",
            phase_instance_id=phase_instance_id,
            round_number=round_number,
            phase=phase,
            payload=event_payload,
            event=event,
        )
        return phase_instance_id

    def _complete_phase(
        self,
        *,
        round_number: int,
        phase: str,
        completion_status: Literal["completed", "skipped", "canceled", "terminal"],
        completion_reason: str,
        next_phase: str | None,
        terminal: bool,
    ) -> object | None:
        key = (round_number, phase)
        active = self._active_phase_instances.get(key)
        if active is None:
            return None
        phase_instance_id, source_event_id = active
        event_payload = {
            "phase_instance_id": phase_instance_id,
            "completion_status": completion_status,
            "completion_reason": completion_reason,
            "next_phase": next_phase,
            "terminal": terminal,
            "source_event_id": source_event_id,
            "audience_policy": "public_lifecycle_v1",
        }
        event = self._known_lifecycle_receipt(
            lifecycle_kind="phase_completed",
            phase_instance_id=phase_instance_id,
            round_number=round_number,
            phase=phase,
            payload=event_payload,
        )
        if event is None:
            event = self._publish_lifecycle(
                "phase_completed",
                round_number=round_number,
                phase=phase,
                actor=None,
                payload=event_payload,
            )
        self._record_lifecycle_receipt(
            lifecycle_kind="phase_completed",
            phase_instance_id=phase_instance_id,
            round_number=round_number,
            phase=phase,
            payload=event_payload,
            event=event,
        )
        if self._active_phase_instances.get(key) == active:
            self._active_phase_instances.pop(key, None)
            self._suppressed_phase_replays.discard(key)
        return event

    def _cancel_active_phases(self, *, completion_reason: str) -> None:
        active_phases = sorted(
            self._active_phase_instances.items(),
            key=lambda item: (
                item[1][1] if item[1][1] is not None else -1,
                item[0][0],
                item[0][1],
            ),
            reverse=True,
        )
        for (round_number, phase), _active in active_phases:
            self._complete_phase(
                round_number=round_number,
                phase=phase,
                completion_status="canceled",
                completion_reason=completion_reason,
                next_phase=None,
                terminal=bool(self.state.winner),
            )

    def _remember_terminal_keep_event(self, event: object | None) -> None:
        event_id = getattr(event, "id", None)
        if type(event_id) is not int:
            return
        if (
            self.terminal_keep_from_event_id is None
            or event_id < self.terminal_keep_from_event_id
        ):
            self.terminal_keep_from_event_id = event_id

    def _publish_night_judge_cue(
        self,
        round_state: RoundState,
        cue: str,
        visible_text: str,
        *,
        target: str | None = None,
    ) -> None:
        params: dict[str, object] = {}
        if target:
            params["target"] = target
        static_asset_id = seat_asset_id(cue, target) if cue == "witch_death" and target else cue
        self._publish_judge_cue(
            round_state,
            "night",
            cue_spec(cue, visible_text, static_asset_id=static_asset_id, params=params),
        )

    def _publish_judge_cue(
        self,
        round_state: RoundState,
        phase: str,
        cue: JudgeCueSpec,
    ) -> object | None:
        return self._publish(
            "judge_cue",
            round_number=round_state.number,
            phase=phase,
            actor=None,
            action=cue.cue_id,
            payload=cue.to_payload(),
        )

    def _publish_judge_cues(
        self,
        round_state: RoundState,
        phase: str,
        cues: list[JudgeCueSpec],
    ) -> None:
        for cue in cues:
            self._publish_judge_cue(round_state, phase, cue)

    def _publish_state_updated(
        self,
        *,
        round_state: RoundState,
        phase: str,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> object | None:
        public_payload = dict(payload or {})
        if round_state.public_summary:
            public_payload.setdefault("public_summary", round_state.public_summary)
        if round_state.public_outcome_events:
            public_payload.setdefault(
                "public_outcome_events",
                [event.to_dict() for event in round_state.public_outcome_events],
            )
            public_payload.setdefault(
                "public_outcome_next_sequence",
                round_state.public_outcome_next_sequence,
            )
        return self._publish(
            "state_updated",
            round_number=round_state.number,
            phase=phase,
            actor=actor,
            action=action,
            payload=public_payload,
        )

    def _publish_action_quality_warnings(
        self,
        *,
        round_state: RoundState,
        phase: str,
        actor: str,
        action: str,
        text: str,
        prior_texts: list[str] | tuple[str, ...] = (),
        personality: str = "",
    ) -> None:
        player = self.state.player_by_name().get(actor)
        active_players = (
            player.gamestate.current_players
            if player is not None and player.gamestate
            else round_state.players
        )
        eligibility = (
            self._public_action_eligibility(player, active_players, round_state).to_dict()
            if player is not None
            else None
        )
        warnings = action_quality_warnings(
            action=action,
            text=text,
            actor=actor,
            endgame=len(active_players) <= 4,
            prior_texts=prior_texts,
            personality=personality,
            eligibility=eligibility,
            role=player.role if player is not None else "",
        )
        if not warnings:
            return
        self._publish(
            "action_quality_warning",
            round_number=round_state.number,
            phase=phase,
            actor=actor,
            action=action,
            payload={"warnings": warnings, "text": text},
        )

    def _is_secret_werewolf_action(self, phase: str, action: str) -> bool:
        if action == ACTION_WEREWOLF_SELF_EXPLOSION:
            return True
        if phase == "night" and action in {
            ACTION_WEREWOLF_DISCUSS,
            ACTION_WEREWOLF_KILL_VOTE,
        }:
            return True
        return False

    def _player_action_event_visibility(
        self,
        phase: str,
        action: str,
    ) -> EventVisibility:
        if action == "summarize" or self._is_secret_werewolf_action(phase, action):
            return "private"
        return "public"

    def _world_state(
        self,
        player: Player,
        options: list[str],
        round_state: RoundState,
    ) -> dict[str, object]:
        active_players = (
            player.gamestate.current_players if player.gamestate else round_state.players
        )
        debate = [f"{entry.speaker}：{entry.message}" for entry in round_state.debate]
        world_state: dict[str, object] = {
            "name": player.name,
            "role": player.role,
            "round": round_state.number,
            "observations": [
                observation
                for observation in player.observations
                if re.match(r"第\d+轮总结：", observation) is None
            ],
            "model_memory": self._model_memory(player.name, player.observations),
            "public_facts": self._public_fact_lines(),
            "public_self_history": self._public_self_history(player.name),
            "stage_interruptions": self._stage_interruption_lines(round_state),
            "endgame_context": self._endgame_context(active_players),
            "remaining_players": "、".join(active_players),
            "debate": debate,
            "debate_guidance": self._debate_guidance(player, active_players, round_state),
            "personality": player.personality,
            "rule_text": rule_text_from_snapshot(
                self.state.rule_set,
                fallback_rule_set=self.rule_set,
            ),
            "rule_set_snapshot": copy.deepcopy(self.state.rule_set),
            "werewolf_context": self._werewolf_context(player, active_players),
            "sheriff_election": self._sheriff_election_context(round_state),
            "public_action_eligibility": self._public_action_eligibility(
                player,
                active_players,
                round_state,
            ).to_dict(),
            "sheriff": self.state.sheriff,
            "sheriff_election_open": self._should_run_sheriff_election(round_state),
            "sheriff_pre_election_bomb_count": self.state.sheriff_pre_election_bomb_count,
            "debate_turns_left": max(0, self.debate_turns - len(round_state.debate)),
            "options": "、".join(options),
        }
        if player.role == HUNTER:
            world_state["hard_state"] = {
                "actor_alive": player.name in active_players,
                "hunter_death_trigger_active": False,
                "terminal_after_current_action": False,
            }
        return world_state

    def _public_model_world_state(self, world_state: dict[str, object]) -> dict[str, object]:
        public_state = self._public_model_value(world_state)
        if not isinstance(public_state, dict):
            raise TypeError("world state must remain a dictionary")
        return public_state

    def _public_model_value(self, value: object) -> object:
        if isinstance(value, str):
            return self._public_text(value)
        if isinstance(value, list):
            return [self._public_model_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._public_model_value(item) for item in value)
        if isinstance(value, dict):
            return {
                self._public_text(str(key)): self._public_model_value(item)
                for key, item in value.items()
            }
        return value

    def _public_action_value(self, value: object | None) -> object | None:
        if isinstance(value, str):
            return self._public_player_reference(value)
        return value

    def _public_player_reference(self, name: str | None) -> str:
        if not name:
            return ""
        labels = self._player_public_labels()
        return labels.get(name, name)

    def _append_public_outcome(
        self,
        *,
        round_state: RoundState,
        kind: PublicOutcomeKind,
        outcome: str,
        phase: str,
        actor_player: str | None = None,
        target_player: str | None = None,
        caused_by_event: PublicOutcomeEventV1 | None = None,
    ) -> PublicOutcomeEventV1:
        return append_public_outcome(
            round_state=round_state,
            session_id=self.state.session_id,
            kind=kind,
            actor_player_id=(self._public_player_reference(actor_player) if actor_player else None),
            target_player_id=(
                self._public_player_reference(target_player) if target_player else None
            ),
            outcome=outcome,
            occurred_phase=phase,
            caused_by_event_id=(caused_by_event.event_id if caused_by_event else None),
        )

    def _latest_player_outcome(
        self,
        round_state: RoundState,
        player: str,
    ) -> PublicOutcomeEventV1 | None:
        return latest_player_outcome_event(
            round_state.public_outcome_events,
            self._public_player_reference(player),
        )

    def _public_text(self, text: str) -> str:
        normalized_text = text
        for name, label in sorted(
            self._player_public_labels().items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if name and name != label:
                normalized_text = normalized_text.replace(name, label)
        return normalized_text

    def _player_public_labels(self) -> dict[str, str]:
        return {
            player.name: f"{index}号玩家"
            for index, player in enumerate(self.state.players, start=1)
        }

    def _debate_guidance(
        self,
        player: Player,
        active_players: list[str],
        round_state: RoundState,
    ) -> list[str]:
        speech_order = round_state.speech_order or active_players
        return debate_guidance_for_turn(
            speaker=player.name,
            active_players=speech_order,
            prior_messages=[f"{entry.speaker}：{entry.message}" for entry in round_state.debate],
            personality=player.personality,
        )

    def _add_public_fact(
        self,
        round_number: int,
        category: str,
        text: str,
        *,
        stage: str | None = None,
        actor: str | None = None,
        retention: FactRetention | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        ordinal = len(self.state.public_facts)
        fact_stage = stage or category
        fact_actor = actor or "system"
        opportunity_id = (
            f"op:r{round_number}:{fact_stage}:{fact_actor}:"
            f"{len(self.state.public_fact_opportunities)}"
        )
        opportunity = PublicFactOpportunityV1(
            opportunity_id=opportunity_id,
            round_number=round_number,
            stage=fact_stage,
            category=category,
            retention=retention
            or (
                "important"
                if category in {"claim", "sheriff", "death", "vote", "reveal", "interruption"}
                else "recent"
            ),
            status="expected",
        ).to_dict()
        self.state.public_fact_opportunities.append(opportunity)
        fact_id = f"r{round_number}:{fact_stage}:{fact_actor}:{ordinal}"
        self.state.public_facts.append(
            PublicFact(
                round_number=round_number,
                category=category,
                text=text,
                fact_id=fact_id,
                stage=stage,
                actor=actor,
                retention=retention,
                source_opportunity_id=opportunity_id,
                details=details or {},
            ).to_dict()
        )
        opportunity["status"] = "recorded"
        opportunity["fact_id"] = fact_id
        self.state.public_fact_propositions.extend(
            self._public_fact_propositions(
                round_number=round_number,
                category=category,
                stage=fact_stage,
                details=details or {},
            )
        )

    def _public_fact_propositions(
        self,
        *,
        round_number: int,
        category: str,
        stage: str,
        details: dict[str, object],
    ) -> list[dict[str, object]]:
        propositions: list[dict[str, object]] = []
        if category == "death":
            raw_players = details.get("players")
            players = raw_players if isinstance(raw_players, list) else [details.get("target")]
            for player in players:
                if isinstance(player, str) and player:
                    propositions.append(
                        {
                            "subject": player,
                            "predicate": "alive",
                            "object": "",
                            "scope": "game",
                            "polarity": False,
                            "round_number": round_number,
                            "stage": stage,
                        }
                    )
        if category == "reveal" and isinstance(details.get("player"), str):
            propositions.append(
                {
                    "subject": details["player"],
                    "predicate": "role_revealed",
                    "object": "werewolf" if stage == "werewolf_self_explosion" else "public",
                    "scope": "game",
                    "polarity": True,
                    "round_number": round_number,
                    "stage": stage,
                }
            )
        return propositions

    def _public_fact_lines(
        self,
        *,
        sheriff_speech_context_round: int | None = None,
    ) -> list[dict[str, object]]:
        facts = [public_fact_from_dict(item) for item in self.state.public_facts]
        if sheriff_speech_context_round is not None:
            compacted_facts: list[PublicFact] = []
            for fact in facts:
                if fact.stage != "sheriff_speech":
                    compacted_facts.append(fact)
                    continue
                if fact.round_number == sheriff_speech_context_round:
                    continue
                compacted_facts.append(
                    replace(fact, text=_compact_sheriff_speech_context(fact.text))
                )
            facts = compacted_facts
        return compressed_public_fact_records(facts)

    def _public_self_history(self, player_name: str) -> list[str]:
        public_speech_stages = {
            "sheriff_speech",
            "sheriff_pk_speech",
            "exile_pk_speech",
            "exile_last_words",
            "debate",
        }
        facts = [
            public_fact_from_dict(item)
            for item in self.state.public_facts
            if isinstance(item, dict)
        ]
        own_public_speech = [
            fact
            for fact in facts
            if fact.actor == player_name
            and (fact.stage in public_speech_stages or fact.category in {"claim", "speech"})
        ]
        return compressed_public_facts(own_public_speech, max_lines=12)

    def _model_memory(self, player_name: str, observations: list[str]) -> list[str]:
        memories = [
            observation
            for observation in observations
            if re.match(r"第\d+轮总结：", observation) is not None
        ]
        memories.extend(
            f"第{round_state.number}轮：{summary}"
            for round_state in self.state.rounds
            if (summary := round_state.private_summaries.get(player_name))
        )
        return list(dict.fromkeys(memories))[-8:]

    def _stage_interruption_lines(self, round_state: RoundState) -> list[str]:
        rounds = list(self.state.rounds)
        if all(existing is not round_state for existing in rounds):
            rounds.append(round_state)
        return [
            self._stage_interruption_text(existing.number, existing.interruption)
            for existing in rounds
            if existing.interruption is not None
        ]

    def _endgame_context(self, active_players: list[str]) -> list[str]:
        total_wolves = sum(
            role_spec.count
            for role_spec in self.rule_set.roles
            if role_spec.team == TEAM_WEREWOLVES
        )
        revealed_wolves = [
            player.name
            for player in self.state.players
            if self._is_werewolf(player)
            and player.revealed_role
            and player.name not in active_players
        ]
        max_remaining_wolves = max(0, total_wolves - len(revealed_wolves))
        lines = [
            f"当前存活 {len(active_players)} 人，公开已出 {len(revealed_wolves)} 名狼人，最多可能还剩 {max_remaining_wolves} 狼。",
        ]
        if len(active_players) <= 4 and max_remaining_wolves > 0:
            lines.append("本轮放逐可能直接触发任一阵营胜利，不能假定一定存在下一夜或下一轮。")
            lines.append("如果讨论明天，必须同时说明本轮错误放逐可能立即结束游戏。")
        return lines

    def _sheriff_election_context(
        self,
        round_state: RoundState,
        *,
        compact_prior_speeches: bool = False,
    ) -> list[str]:
        lines: list[str] = []
        if round_state.sheriff_candidates:
            lines.append(f"上警名单：{'、'.join(round_state.sheriff_candidates)}")
            voters = "、".join(round_state.sheriff_voters) or "无"
            lines.append(f"警下名单：{voters}")
        if round_state.sheriff_speeches:
            if compact_prior_speeches:
                speech_lines = [
                    (
                        f"{entry.get('speaker', '')}（前置位观点摘要，勿复用措辞或格式）："
                        f"{_compact_sheriff_speech_context(str(entry.get('message', '')))}"
                    )
                    for entry in round_state.sheriff_speeches
                    if entry.get("speaker") and entry.get("message")
                ]
            else:
                speech_lines = [
                    f"{entry.get('speaker', '')}：{entry.get('message', '')}"
                    for entry in round_state.sheriff_speeches
                    if entry.get("speaker") and entry.get("message")
                ]
            if speech_lines:
                lines.append(f"警上发言：{'；'.join(speech_lines)}")
        if round_state.sheriff_withdrawn:
            lines.append(f"退水名单：{'、'.join(round_state.sheriff_withdrawn)}")
        if round_state.sheriff_final_candidates:
            lines.append(f"最终候选：{'、'.join(round_state.sheriff_final_candidates)}")
        if round_state.sheriff_pk_candidates:
            lines.append(f"PK 候选：{'、'.join(round_state.sheriff_pk_candidates)}")
        if round_state.sheriff_pk_speeches:
            pk_speech_lines = [
                f"{entry.get('speaker', '')}：{entry.get('message', '')}"
                for entry in round_state.sheriff_pk_speeches
                if entry.get("speaker") and entry.get("message")
            ]
            if pk_speech_lines:
                lines.append(f"PK 发言：{'；'.join(pk_speech_lines)}")
        if round_state.sheriff_elected:
            lines.append(f"已当选警长：{round_state.sheriff_elected}")
        elif round_state.sheriff_badge_lost:
            lines.append("警徽流失")
        return lines

    def _public_action_eligibility(
        self,
        player: Player,
        active_players: list[str],
        round_state: RoundState,
    ) -> PublicActionEligibility:
        candidates = round_state.sheriff_candidates.copy()
        voters = round_state.sheriff_voters.copy()
        final_candidates = round_state.sheriff_final_candidates.copy()
        actor_was_candidate = player.name in candidates
        actor_withdrew = player.name in round_state.sheriff_withdrawn
        election_active = self._should_run_sheriff_election(round_state)
        if not self.rule_set.sheriff_enabled:
            reason = "sheriff_disabled"
        elif round_state.sheriff_election_resolution is not None and not election_active:
            reason = "election_resolved"
        elif player.name in voters:
            reason = "eligible_original_voter"
        elif actor_withdrew:
            reason = "withdrew_candidate_not_original_voter"
        elif actor_was_candidate:
            reason = "candidate_not_eligible"
        elif candidates and not voters:
            reason = "no_off_sheriff_voters"
        else:
            reason = "election_resolved"
        return PublicActionEligibility(
            sheriff_election_active=election_active,
            original_candidates=candidates,
            original_voters=voters,
            final_candidates=final_candidates,
            actor_was_candidate=actor_was_candidate,
            actor_withdrew=actor_withdrew,
            actor_can_sheriff_vote=election_active and player.name in voters,
            sheriff_vote_reason=reason,  # type: ignore[arg-type]
            actor_can_exile_vote=player.can_vote and player.name in active_players,
        )

    def _werewolf_context(self, player: Player, active_players: list[str]) -> str:
        if not self._is_werewolf(player) or not player.gamestate:
            return ""
        teammates = player.gamestate.wolf_teammates
        if not teammates and player.gamestate.other_wolf:
            teammates = [player.gamestate.other_wolf]
        if not teammates:
            return ""

        living_teammates = [name for name in teammates if name in active_players]
        if living_teammates:
            return f"你的狼人队友是{'、'.join(living_teammates)}。"
        return f"你的狼人队友{'、'.join(teammates)}已经出局，只剩你独自行动。"

    def _investigation_alignment(self, role: str) -> str:
        if _role_team(self.rule_set, role) == TEAM_WEREWOLVES:
            return WINNER_WEREWOLVES
        return WINNER_VILLAGERS

    def _get_winner(self, active_players: list[str]) -> str:
        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        active_villagers = [name for name in active_players if name not in active_wolves]

        if self.rule_set.win_condition == WIN_CONDITION_SLAUGHTER_SIDE:
            active_gods = [
                name
                for name in active_players
                if role_category(self.rule_set, players_by_name[name].role) == ROLE_CATEGORY_GOD
            ]
            active_civilians = [
                name
                for name in active_players
                if role_category(self.rule_set, players_by_name[name].role)
                == ROLE_CATEGORY_CIVILIAN
            ]
            if not active_wolves:
                return WINNER_VILLAGERS
            if not active_gods or not active_civilians:
                return WINNER_WEREWOLVES
            return ""

        if not active_wolves:
            return WINNER_VILLAGERS
        if len(active_wolves) >= len(active_villagers):
            return WINNER_WEREWOLVES
        return ""

    def _current_active_players(self) -> list[str]:
        for player in self.state.players:
            if player.gamestate is not None:
                return player.gamestate.current_players.copy()
        return []

    def _begin_terminal_settlement(
        self,
        *,
        round_state: RoundState,
        active_players: list[str],
        phase: str,
        primary_actor: str | None,
        hunter_contexts: list[dict[str, object]] | None = None,
        continuation_kind: str = "none",
        continuation_transfer_sheriff_badge: bool = False,
        skip_exile_last_words: bool = False,
    ) -> None:
        if self._terminal_settlement is not None:
            return
        identity = ":".join(
            [
                self.state.session_id,
                str(round_state.number),
                phase,
                primary_actor or "death_batch",
            ]
        )
        primary_action_id = f"outcome:{identity}"
        settlements: list[dict[str, object]] = [
            {
                "settlement_id": f"settlement:{identity}:primary",
                "kind": "death_batch",
                "actor": primary_actor,
                "status": "applied",
                "accepted_choice": None,
                "details": {"phase": phase},
            }
        ]
        for context in hunter_contexts or []:
            actor = context.get("actor")
            if not isinstance(actor, str) or not actor:
                continue
            settlements.append(
                {
                    "settlement_id": f"settlement:{identity}:hunter:{actor}",
                    "kind": "hunter_shot",
                    "actor": actor,
                    "status": "pending",
                    "accepted_choice": None,
                    "details": copy.deepcopy(context),
                }
            )
        self._terminal_settlement = {
            "settlement_schema_version": "settlement_v1",
            "stage": "outcome_applied",
            "primary_outcome_action_id": primary_action_id,
            "settlement_cursor": 1,
            "settlements": settlements,
            "canceled_action_ids": [],
            "continuation": {
                "kind": continuation_kind,
                "status": "pending",
                "skip_exile_last_words": skip_exile_last_words,
                "transfer_sheriff_badge": continuation_transfer_sheriff_badge,
            },
        }
        primary_presentation = self._terminal_primary_presentation_payload(
            round_state=round_state,
            primary_action_id=primary_action_id,
            phase=phase,
        )
        if primary_presentation is not None:
            self._terminal_settlement["primary_presentation"] = primary_presentation
            self._terminal_settlement["primary_presentation_payload"] = (
                self._build_terminal_primary_presentation_payload(
                    kind=str(primary_presentation["kind"]),
                    round_state=round_state,
                    active_players=active_players,
                )
            )
        self._persist_terminal_settlement(active_players)

    def _terminal_primary_presentation_payload(
        self,
        *,
        round_state: RoundState,
        primary_action_id: str,
        phase: str | None = None,
    ) -> dict[str, object] | None:
        if phase == "night" and round_state.night_deaths:
            kind = "night_result"
        elif phase in {"day", "vote"} and round_state.werewolf_self_exploded:
            kind = "self_explosion_result"
        elif phase in {"day", "vote"} and round_state.exiled:
            kind = "exile_result"
        elif round_state.werewolf_self_exploded:
            kind = "self_explosion_result"
        elif round_state.exiled:
            kind = "exile_result"
        elif round_state.night_deaths:
            kind = "night_result"
        else:
            return None
        digest = hashlib.sha256(
            f"{self.state.session_id}:{primary_action_id}:presentation".encode()
        ).hexdigest()[:24]
        return {"presentation_id": f"pp_{digest}", "kind": kind}

    def _build_terminal_primary_presentation_payload(
        self,
        *,
        kind: str,
        round_state: RoundState,
        active_players: list[str],
    ) -> dict[str, object]:
        relevant_deaths = (
            round_state.night_deaths
            if kind == "night_result"
            else round_state.day_deaths
        )
        hunter_targets = {
            death.player for death in relevant_deaths if death.cause == "hunter_shot"
        }
        primary_active_set = {*active_players, *hunter_targets}
        primary_active_players = [
            name for name in round_state.players if name in primary_active_set
        ]
        primary_active_players.extend(
            name
            for name in sorted(primary_active_set)
            if name not in primary_active_players
        )
        primary_deaths = [
            death.to_dict()
            for death in relevant_deaths
            if death.cause != "hunter_shot"
        ]
        hunter_outcome_sequences = [
            event.sequence
            for event in round_state.public_outcome_events
            if event.kind == "hunter_shot"
        ]
        outcome_cutoff = (
            min(hunter_outcome_sequences) if hunter_outcome_sequences else None
        )
        primary_outcomes = [
            event.to_dict()
            for event in round_state.public_outcome_events
            if outcome_cutoff is None or event.sequence < outcome_cutoff
        ]
        payload: dict[str, object] = {
            "active_players": primary_active_players,
            "public_outcome_events": primary_outcomes,
            "public_outcome_next_sequence": (
                outcome_cutoff
                if outcome_cutoff is not None
                else round_state.public_outcome_next_sequence
            ),
        }
        if kind == "exile_result":
            payload.update(
                {
                    "exiled": round_state.exiled,
                    "day_deaths": primary_deaths,
                }
            )
        elif kind == "night_result":
            payload["night_deaths"] = primary_deaths
        elif kind == "self_explosion_result":
            payload.update(
                {
                    "werewolf_self_exploded": round_state.werewolf_self_exploded,
                    "day_ended_by_self_explosion": (
                        round_state.day_ended_by_self_explosion
                    ),
                    "day_deaths": primary_deaths,
                }
            )
        else:
            raise RuntimeError(f"Unsupported terminal primary presentation kind: {kind}")
        return payload

    def _terminal_primary_presentation(
        self,
        round_state: RoundState,
    ) -> dict[str, object] | None:
        if self._terminal_settlement is None:
            return None
        raw = self._terminal_settlement.get("primary_presentation")
        if isinstance(raw, dict):
            return raw
        primary_action_id = self._terminal_settlement.get("primary_outcome_action_id")
        if not isinstance(primary_action_id, str) or not primary_action_id:
            return None
        primary_phase: str | None = None
        settlements = self._terminal_settlement.get("settlements")
        if isinstance(settlements, list) and settlements:
            primary = settlements[0]
            if isinstance(primary, dict):
                details = primary.get("details")
                if isinstance(details, dict) and isinstance(details.get("phase"), str):
                    primary_phase = details["phase"]
        if primary_phase is None:
            primary_phase = next(
                (
                    candidate
                    for candidate in ("night", "vote", "day")
                    if f":{candidate}:" in primary_action_id
                ),
                None,
            )
        presentation = self._terminal_primary_presentation_payload(
            round_state=round_state,
            primary_action_id=primary_action_id,
            phase=primary_phase,
        )
        if presentation is not None:
            self._terminal_settlement["primary_presentation"] = copy.deepcopy(
                presentation
            )
        return presentation

    def _terminal_primary_presentation_event_payload(
        self,
        *,
        presentation: Mapping[str, object],
        round_state: RoundState,
        active_players: list[str],
    ) -> dict[str, object]:
        if self._terminal_settlement is None:
            raise RuntimeError("Terminal primary presentation has no settlement")
        frozen = self._terminal_settlement.get("primary_presentation_payload")
        if isinstance(frozen, dict):
            return copy.deepcopy(frozen)
        kind = presentation.get("kind")
        if not isinstance(kind, str):
            raise RuntimeError("Terminal primary presentation has no kind")
        payload = self._build_terminal_primary_presentation_payload(
            kind=kind,
            round_state=round_state,
            active_players=active_players,
        )
        self._terminal_settlement["primary_presentation_payload"] = copy.deepcopy(
            payload
        )
        return payload

    def _publish_terminal_primary_presentation(
        self,
        *,
        round_state: RoundState,
        active_players: list[str],
    ) -> object | None:
        presentation = self._terminal_primary_presentation(round_state)
        if presentation is None:
            return None
        kind = presentation.get("kind")
        payload = self._terminal_primary_presentation_event_payload(
            presentation=presentation,
            round_state=round_state,
            active_players=active_players,
        )
        payload["presentation_id"] = presentation["presentation_id"]
        actor: str | None = None
        phase = "day"
        action: str
        if kind == "exile_result" and isinstance(payload.get("exiled"), str):
            actor = str(payload["exiled"])
            phase = "vote"
            action = "exile_resolved"
        elif kind == "night_result" and isinstance(
            payload.get("night_deaths"), list
        ):
            phase = "night"
            action = "night_resolved"
        elif kind == "self_explosion_result" and isinstance(
            payload.get("werewolf_self_exploded"), str
        ):
            actor = str(payload["werewolf_self_exploded"])
            action = ACTION_WEREWOLF_SELF_EXPLOSION
        else:
            return None
        event = self._publish_state_updated(
            round_state=round_state,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
        )
        self._terminal_primary_event = event
        return event

    def _hunter_settlement_contexts(
        self,
        deaths: list[DeathEvent],
        *,
        phase: str,
        death_phase: Literal["night", "day"] | None = None,
        excluded_shot_targets: set[str] | None = None,
        excluded_badge_targets: set[str] | None = None,
        transfer_sheriff_badge: bool = False,
    ) -> list[dict[str, object]]:
        players_by_name = self.state.player_by_name()
        return [
            {
                "actor": death.player,
                "death_cause": death.cause,
                "phase": phase,
                **({"death_phase": death_phase} if death_phase else {}),
                "excluded_shot_targets": sorted(excluded_shot_targets or set()),
                "excluded_badge_targets": sorted(excluded_badge_targets or set()),
                "transfer_sheriff_badge": transfer_sheriff_badge,
            }
            for death in deaths
            if death.cause != "witch_poison"
            and players_by_name[death.player].role == HUNTER
            and players_by_name[death.player].hunter_can_shoot
        ]

    def _terminal_hunter_settlement(
        self,
        actor: str,
    ) -> dict[str, object] | None:
        if self._terminal_settlement is None:
            return None
        settlements = self._terminal_settlement.get("settlements")
        if not isinstance(settlements, list):
            return None
        return next(
            (
                item
                for item in settlements
                if isinstance(item, dict)
                and item.get("kind") == "hunter_shot"
                and item.get("actor") == actor
            ),
            None,
        )

    def _accept_terminal_hunter_choice(
        self,
        *,
        hunter: Player,
        shot: object | None,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        death_cause: str,
        phase: str,
        death_phase: Literal["night", "day"] | None = None,
        excluded_shot_targets: set[str],
        excluded_badge_targets: set[str] | None,
        transfer_sheriff_badge: bool,
    ) -> None:
        projected_active = active_players.copy()
        if isinstance(shot, str) and shot and shot != NO_HUNTER_SHOT:
            if shot in projected_active:
                projected_active.remove(shot)
        if self._terminal_settlement is None and not self._get_winner(projected_active):
            return
        if self._terminal_settlement is None:
            self._begin_terminal_settlement(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                primary_actor=(round_state.exiled or hunter.name),
                hunter_contexts=[
                    {
                        "actor": hunter.name,
                        "death_cause": death_cause,
                        "phase": phase,
                        **({"death_phase": death_phase} if death_phase else {}),
                        "excluded_shot_targets": sorted(excluded_shot_targets),
                        "excluded_badge_targets": sorted(excluded_badge_targets or set()),
                        "transfer_sheriff_badge": transfer_sheriff_badge,
                    }
                ],
            )
        settlement = self._terminal_hunter_settlement(hunter.name)
        if settlement is None:
            return
        settlement["status"] = "choice_accepted"
        settlement["accepted_choice"] = (
            shot
            if isinstance(shot, str) and shot and shot != NO_HUNTER_SHOT
            else NO_HUNTER_SHOT
        )
        settlement["presentation"] = self._terminal_hunter_presentation_payload(
            settlement
        )
        self._terminal_settlement["stage"] = "hunter_choice_accepted"
        self._persist_terminal_settlement(active_players)

    def _terminal_hunter_presentation_payload(
        self,
        settlement: Mapping[str, object],
    ) -> dict[str, object]:
        settlement_id = settlement.get("settlement_id")
        accepted_choice = settlement.get("accepted_choice")
        if not isinstance(settlement_id, str) or not settlement_id:
            raise RuntimeError("Hunter settlement has no stable identity")
        shot_target = (
            accepted_choice
            if isinstance(accepted_choice, str)
            and accepted_choice
            and accepted_choice != NO_HUNTER_SHOT
            else None
        )
        digest = hashlib.sha256(
            f"{self.state.session_id}:{settlement_id}:presentation".encode()
        ).hexdigest()[:24]
        return {
            "presentation_id": f"hp_{digest}",
            "kind": "hunter_shot_result",
            "hunter_shot_status": "shot" if shot_target is not None else "skipped",
            "hunter_shot": shot_target,
        }

    def _publish_terminal_hunter_presentation(
        self,
        *,
        actor: str,
        round_state: RoundState,
        phase: str,
        active_players: list[str],
        shot: object | None = None,
    ) -> object | None:
        settlement = self._terminal_hunter_settlement(actor)
        presentation: dict[str, object] | None = None
        if settlement is not None:
            raw_presentation = settlement.get("presentation")
            presentation = (
                copy.deepcopy(raw_presentation)
                if isinstance(raw_presentation, dict)
                else self._terminal_hunter_presentation_payload(settlement)
            )
            # Backfill only the in-memory recovery envelope. New
            # choice_accepted checkpoints persisted it before applying choice.
            settlement["presentation"] = copy.deepcopy(presentation)
        resolved_shot = (
            shot
            if isinstance(shot, str) and shot and shot != NO_HUNTER_SHOT
            else (
                presentation.get("hunter_shot")
                if presentation is not None
                else None
            )
        )
        shot_status = "shot" if isinstance(resolved_shot, str) else "skipped"
        deaths = [
            death.to_dict()
            for death in [*round_state.night_deaths, *round_state.day_deaths]
        ]
        payload: dict[str, object] = {
            "hunter_shot_status": shot_status,
            "hunter_shot": resolved_shot,
            "deaths": deaths,
            "night_deaths": [death.to_dict() for death in round_state.night_deaths],
            "day_deaths": [death.to_dict() for death in round_state.day_deaths],
            "active_players": active_players.copy(),
        }
        if presentation is not None:
            payload["presentation_id"] = presentation["presentation_id"]
        event = self._publish_state_updated(
            round_state=round_state,
            phase=phase,
            actor=actor,
            action="hunter_shot_resolved",
            payload=payload,
        )
        if self._get_winner(active_players):
            self._remember_terminal_keep_event(event)
        return event

    def _mark_terminal_hunter_applied(
        self,
        *,
        actor: str,
        active_players: list[str],
    ) -> None:
        settlement = self._terminal_hunter_settlement(actor)
        if settlement is None or self._terminal_settlement is None:
            return
        settlement["status"] = "applied"
        settlements = self._terminal_settlement.get("settlements")
        if isinstance(settlements, list):
            cursor = 0
            for item in settlements:
                if not isinstance(item, dict) or item.get("status") != "applied":
                    break
                cursor += 1
            self._terminal_settlement["settlement_cursor"] = cursor
        self._terminal_settlement["stage"] = "outcome_applied"
        self._persist_terminal_settlement(active_players)

    def _persist_terminal_settlement(self, active_players: list[str]) -> None:
        if self._terminal_settlement is None or self.checkpoint_manager is None:
            return
        record = getattr(self.checkpoint_manager, "record_terminal_settlement", None)
        if not callable(record):
            return
        record(
            state=self.state,
            logs=self.logs,
            active_players=active_players,
            terminal_settlement=self._terminal_settlement,
        )

    def _terminal_continuation(self) -> dict[str, object] | None:
        if self._terminal_settlement is None:
            return None
        value = self._terminal_settlement.get("continuation")
        return value if isinstance(value, dict) else None

    def _complete_cleared_terminal_continuation(
        self,
        active_players: list[str],
    ) -> None:
        if self._terminal_settlement is None or self._get_winner(active_players):
            return
        continuation = self._terminal_continuation()
        if continuation is None or continuation.get("kind") == "none":
            return
        continuation["status"] = "applied"
        self._terminal_settlement["stage"] = "candidate_cleared"
        self._persist_terminal_settlement(active_players)
        # The durable checkpoint remains recoverable until the next normal
        # round checkpoint replaces it. In memory, release the stale candidate
        # so the resumed/current day can create a later independent settlement.
        self._terminal_settlement = None
        self._terminal_primary_event = None

    def prepare_terminal_settlement_recovery(
        self,
        terminal_settlement: Mapping[str, object],
        *,
        logs: list[RoundLog],
    ) -> None:
        self._prepared_terminal_settlement = copy.deepcopy(terminal_settlement)
        self._prepared_terminal_logs = logs

    def recover_terminal_settlement(
        self,
        terminal_settlement: Mapping[str, object],
        *,
        logs: list[RoundLog],
        active_players: list[str],
    ) -> None:
        """Continue a persisted outcome settlement without replaying its round."""

        self._terminal_settlement = {
            key: copy.deepcopy(value)
            for key, value in terminal_settlement.items()
            if key not in {"state", "logs", "active_players"}
        }
        prior_logs = self.logs
        self.logs = logs
        if not self.state.rounds or not logs:
            raise RuntimeError("Terminal settlement snapshot has no current round")
        round_state = self.state.rounds[-1]
        round_log = logs[-1]
        settlements = self._terminal_settlement.get("settlements")
        if not isinstance(settlements, list):
            raise RuntimeError("Terminal settlement snapshot is malformed")
        self._publish_terminal_primary_presentation(
            round_state=round_state,
            active_players=active_players,
        )
        self._recover_terminal_exile_last_words_if_needed(
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
        )
        for item in settlements:
            if not isinstance(item, dict) or item.get("kind") != "hunter_shot":
                continue
            status = item.get("status")
            actor = item.get("actor")
            details = item.get("details")
            if not isinstance(actor, str) or not isinstance(details, dict):
                raise RuntimeError("Hunter settlement snapshot is malformed")
            death_cause = str(details.get("death_cause") or "vote_exile")
            phase = str(details.get("phase") or "vote")
            raw_death_phase = details.get("death_phase")
            death_phase: Literal["night", "day"] = (
                raw_death_phase
                if raw_death_phase in {"night", "day"}
                else "night"
                if phase in {"night", "dawn_reveal"}
                else "day"
            )
            excluded_shot_targets = {
                str(value) for value in details.get("excluded_shot_targets", [])
            }
            excluded_badge_targets = {
                str(value) for value in details.get("excluded_badge_targets", [])
            }
            transfer_badge = bool(details.get("transfer_sheriff_badge", False))
            if status == "applied":
                self._publish_terminal_hunter_presentation(
                    actor=actor,
                    round_state=round_state,
                    phase=phase,
                    active_players=active_players,
                    shot=item.get("accepted_choice"),
                )
                continue
            if status == "pending":
                self._maybe_run_hunter_shot(
                    dead_player=actor,
                    death_cause=death_cause,
                    round_state=round_state,
                    round_log=round_log,
                    active_players=active_players,
                    phase=phase,
                    death_phase=death_phase,
                    excluded_shot_targets=excluded_shot_targets,
                    excluded_badge_targets=excluded_badge_targets,
                    transfer_sheriff_badge=transfer_badge,
                )
                continue
            if status != "choice_accepted":
                raise RuntimeError("Hunter settlement status is unsupported")
            self._apply_hunter_shot_choice(
                hunter=self.state.player_by_name()[actor],
                shot=item.get("accepted_choice"),
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase=phase,
                death_phase=death_phase,
                excluded_badge_targets=excluded_badge_targets,
                transfer_sheriff_badge=transfer_badge,
            )
        try:
            if self._commit_terminal_winner(active_players, round_state):
                return
            self._resume_cleared_terminal_candidate(
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
            )
        finally:
            self.logs = prior_logs

    def _recover_terminal_exile_last_words_if_needed(
        self,
        *,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        continuation = self._terminal_continuation()
        settlements = (
            self._terminal_settlement.get("settlements")
            if self._terminal_settlement is not None
            else None
        )
        has_pending_hunter = isinstance(settlements, list) and any(
            isinstance(item, dict)
            and item.get("kind") == "hunter_shot"
            and item.get("status") == "pending"
            for item in settlements
        )
        if (
            continuation is None
            or continuation.get("kind") != "day_exile_aftermath"
            or continuation.get("skip_exile_last_words") is not False
            or not has_pending_hunter
        ):
            return
        exiled = round_state.exiled
        if not isinstance(exiled, str) or not exiled:
            raise RuntimeError("Pending terminal hunter has no exiled player")
        if round_state.exile_last_words is None:
            self._run_exile_last_words(
                exiled=exiled,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
            )
            if round_state.exile_last_words is None:
                raise RuntimeError("Pending terminal hunter last words did not settle")
            return
        self._publish_terminal_exile_last_words_result(
            exiled=exiled,
            round_state=round_state,
            round_log=round_log,
            reemit_action_parsed=True,
        )

    def _resume_cleared_terminal_candidate(
        self,
        *,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        if self._terminal_settlement is None:
            raise RuntimeError("Cleared terminal candidate has no settlement")
        continuation = self._terminal_continuation()
        if continuation is None:
            if round_state.exiled:
                kind = "day_exile_aftermath"
                skip_last_words = True
            elif round_state.night_deaths:
                kind = "night_death_aftermath"
                skip_last_words = False
            else:
                kind = "none"
                skip_last_words = False
            continuation = {
                "kind": kind,
                "status": "pending",
                "skip_exile_last_words": skip_last_words,
                "transfer_sheriff_badge": kind != "none",
            }
            self._terminal_settlement["continuation"] = continuation
        kind = continuation.get("kind")
        should_transfer_badge = continuation.get("transfer_sheriff_badge") is True
        if continuation.get("status") != "applied" and should_transfer_badge:
            if kind == "day_exile_aftermath":
                for death in list(round_state.day_deaths):
                    self._maybe_transfer_sheriff_badge(
                        dead_player=death.player,
                        round_state=round_state,
                        round_log=round_log,
                        active_players=active_players,
                        phase="vote",
                    )
            elif kind == "night_death_aftermath":
                night_death_players = {
                    death.player for death in round_state.night_deaths
                }
                for death in list(round_state.night_deaths):
                    self._maybe_transfer_sheriff_badge(
                        dead_player=death.player,
                        round_state=round_state,
                        round_log=round_log,
                        active_players=active_players,
                        phase="night",
                        excluded_badge_targets=night_death_players,
                    )
        self._complete_cleared_terminal_continuation(active_players)
        if self._terminal_settlement is not None:
            # A legacy "none" continuation is safe to release once the
            # candidate is known to be non-terminal.
            self._terminal_settlement = None
            self._terminal_primary_event = None

        if kind == "day_exile_aftermath":
            self._publish_state_updated(
                round_state=round_state,
                phase="vote",
                action="day_resolution_completed",
                payload={
                    "narration_mode": "explicit_v1",
                    "exiled": round_state.exiled,
                    "day_deaths": [
                        death.to_dict() for death in round_state.day_deaths
                    ],
                    "hunter_shot": round_state.hunter_shot,
                    "idiot_revealed": round_state.idiot_revealed,
                    "exile_pk_candidates": round_state.exile_pk_candidates.copy(),
                    "exile_pk_speeches": copy.deepcopy(
                        round_state.exile_pk_speeches
                    ),
                    "exile_runoff_votes": round_state.exile_runoff_votes.copy(),
                    "exile_runoff_vote_origins": copy.deepcopy(
                        round_state.exile_runoff_vote_origins
                    ),
                    "vote_origins": copy.deepcopy(round_state.vote_origins),
                    "exile_resolution_reason": round_state.exile_resolution_reason,
                    "active_players": active_players.copy(),
                },
            )
            self._publish_public_round_brief(round_state, active_players)
            self._run_private_round_memories(
                round_state,
                round_log,
                active_players,
            )
            round_state.success = True
            return
        if kind == "night_death_aftermath":
            self._run_day_phase(
                round_state,
                round_log,
                active_players,
                pending_night_deaths=None,
            )
            self._refresh_winner(active_players)
            round_state.success = True

    def _publish_recovered_terminal_state(
        self,
        active_players: list[str],
    ) -> object | None:
        if not self.state.rounds:
            raise RuntimeError("Terminal settlement recovery has no final round")
        round_state = self.state.rounds[-1]
        is_night_resolution = bool(round_state.night_deaths) and not (
            round_state.exiled
            or round_state.day_deaths
            or round_state.werewolf_self_exploded
        )
        if is_night_resolution:
            return self._publish_state_updated(
                round_state=round_state,
                phase="night",
                action="night_resolved",
                payload={
                    "narration_mode": "explicit_v1",
                    "night_deaths": [
                        death.to_dict() for death in round_state.night_deaths
                    ],
                    "hunter_shot": round_state.hunter_shot,
                    "active_players": active_players.copy(),
                    "public_summary": round_state.public_summary,
                },
            )
        return self._publish_state_updated(
            round_state=round_state,
            phase="vote" if round_state.exiled else "day",
            action="day_resolution_completed",
            payload={
                "narration_mode": "explicit_v1",
                "exiled": round_state.exiled,
                "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                "hunter_shot": round_state.hunter_shot,
                "idiot_revealed": round_state.idiot_revealed,
                "werewolf_self_exploded": round_state.werewolf_self_exploded,
                "active_players": active_players.copy(),
                "public_summary": round_state.public_summary,
            },
        )

    def _commit_terminal_winner(
        self,
        active_players: list[str],
        round_state: RoundState | None = None,
    ) -> bool:
        if not self._refresh_winner(active_players):
            return False
        if self._terminal_settlement is None and round_state is not None:
            phase = (
                "vote"
                if round_state.exiled
                else "night"
                if round_state.night_deaths
                else "day"
            )
            self._begin_terminal_settlement(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                primary_actor=(
                    round_state.exiled
                    or round_state.werewolf_self_exploded
                    or None
                ),
            )
        if round_state is not None and not round_state.public_summary:
            round_state.public_summary = self._public_round_brief(round_state)
        if self._terminal_settlement is not None:
            self._terminal_settlement["stage"] = "winner_committed"
            self._persist_terminal_settlement(active_players)
        self._remember_terminal_keep_event(self._terminal_primary_event)
        return True

    def _deferred_deaths_are_inevitably_terminal(
        self,
        deaths: list[DeathEvent],
        active_players: list[str],
    ) -> bool:
        """Return true only when every legal deferred-death branch ends the game.

        First-night deaths normally remain hidden until after the sheriff election.
        The only safe exception is a batch whose no-shot branch and every legal
        hunter-shot branch are terminal.  The check is deliberately conservative
        for custom rule sets with more than one shootable hunter.
        """

        pending_players = {death.player for death in deaths}
        projected_active = [
            name for name in active_players if name not in pending_players
        ]
        shootable_hunters = [
            death.player
            for death in deaths
            if death.cause != "witch_poison"
            and self.state.player_by_name()[death.player].role == HUNTER
            and self.state.player_by_name()[death.player].hunter_can_shoot
        ]
        if len(shootable_hunters) > 1:
            return False

        branches = [projected_active]
        if shootable_hunters:
            branches.extend(
                [name for name in projected_active if name != target]
                for target in projected_active
            )
        return all(bool(self._get_winner(branch)) for branch in branches)

    def _hunter_settlement_is_terminal(
        self,
        active_players: list[str],
        options: list[str],
    ) -> bool:
        branches = [active_players]
        branches.extend(
            [name for name in active_players if name != target]
            for target in options
            if target != NO_HUNTER_SHOT
        )
        return all(bool(self._get_winner(branch)) for branch in branches)

    def _hunter_death_chain_may_be_terminal(
        self,
        deaths: list[DeathEvent],
        active_players: list[str],
        *,
        excluded_shot_targets: set[str] | None = None,
    ) -> bool:
        players_by_name = self.state.player_by_name()
        if not any(
            death.cause != "witch_poison"
            and players_by_name[death.player].role == HUNTER
            and players_by_name[death.player].hunter_can_shoot
            for death in deaths
        ):
            return False
        excluded = excluded_shot_targets or set()
        return any(
            bool(
                self._get_winner(
                    [name for name in active_players if name != shot_target]
                )
            )
            for shot_target in active_players
            if shot_target not in excluded
        )

    def _refresh_winner(self, active_players: list[str]) -> bool:
        if self.state.winner:
            return True
        winner = self._get_winner(active_players)
        if not winner:
            return False
        self.state.winner = winner
        return True

    def _is_werewolf(self, player: Player) -> bool:
        return _role_team(self.rule_set, player.role) == TEAM_WEREWOLVES

    def _is_role_active(self, role: str, active_players: list[str]) -> bool:
        return bool(self._active_player_for_role(role, active_players))

    def _active_player_for_role(self, role: str, active_players: list[str]) -> str:
        players_by_name = self.state.player_by_name()
        return next(
            (name for name in active_players if players_by_name[name].role == role),
            "",
        )

    def _remove_player(self, active_players: list[str], player: str) -> None:
        if player in active_players:
            active_players.remove(player)
        self._sync_game_views(active_players, len(self.state.rounds))

    def _announce(self, active_players: list[str], announcement: str) -> None:
        players_by_name = self.state.player_by_name()
        for name in active_players:
            players_by_name[name].add_observation(announcement)

    def _record_public_debate(self, active_players: list[str], entry: DebateEntry) -> None:
        players_by_name = self.state.player_by_name()
        for name in active_players:
            if players_by_name[name].gamestate:
                players_by_name[name].gamestate.debate.append(entry)

    def _sync_game_views(self, active_players: list[str], round_number: int) -> None:
        for player in self.state.players:
            if player.gamestate:
                player.gamestate.round_number = round_number
                player.gamestate.current_players = active_players.copy()
                if player.name not in active_players:
                    player.gamestate.debate = []


def _effective_action_origin(action_log: ActionLog) -> str:
    if action_log.effective_origin is not None:
        return action_log.effective_origin
    if action_log.execution_status in {"canceled", "failed", "timed_out"}:
        return "none"
    if action_log.execution_status == "fallback" or action_log.fallback_reason:
        return "system_fallback"
    return "model"


def _vote_origins(
    action_logs: list[ActionLog],
) -> dict[str, dict[str, str | None]]:
    return {
        action_log.actor: {
            "origin": _effective_action_origin(action_log),
            "reason_code": _public_action_reason_code(action_log),
        }
        for action_log in action_logs
    }


def _public_vote_line(
    voter: str,
    target: str,
    origin: Mapping[str, object] | None,
) -> str:
    label = f"{voter}->{target}"
    if isinstance(origin, Mapping) and origin.get("origin") == "system_fallback":
        return f"{label}（系统代投）"
    return label


def _public_action_reason_code(action_log: ActionLog) -> str | None:
    reason = action_log.reason_code or action_log.fallback_reason
    if not reason:
        return None
    if reason.startswith("batch_deadline"):
        return "batch_deadline"
    if reason.startswith("timeout"):
        return "timeout"
    if "invalid" in reason:
        return "invalid_exhausted"
    if "quality" in reason:
        return "quality_exhausted"
    if "self_explosion" in reason:
        return "self_explosion_cancelled"
    if reason in {"superseded", "expired", "canceled_terminal"}:
        return "phase_advanced"
    if "badge" in reason or "rule" in reason:
        return "rule_default"
    return reason


def _visible_action_result(
    action: str,
    result: dict[str, object] | None,
) -> dict[str, object]:
    if result is None:
        return {}
    visible_field = action_visible_stream_field(action)
    if visible_field is None:
        return {}
    visible_value = result.get(visible_field)
    if isinstance(visible_value, str):
        return {visible_field: visible_value}
    return {}
