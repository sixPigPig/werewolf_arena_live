from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Iterable
import copy
from dataclasses import dataclass, field
import hashlib
import json
import logging
import time
from typing import Any, Literal

from app.core.config import settings
from app.match.action_engine import (
    ActionEngine,
    ActionFailure,
    ActionResult,
    BroadcastPort,
    DecisionContract,
    PreflightPauseFailure,
    SpeechSpec,
)
from app.match.day_speech_pipeline_repository import (
    DaySpeechPipelineRepository,
    DaySpeechSlotSnapshot,
)
from app.match.match_repository import (
    DayVoteCommit,
    ExileResult,
    MatchPlayer,
    MatchRepository,
    MatchSnapshot,
    PrivateRoundMemoryCommit,
    private_round_memory_source_refs_sha256,
)
from app.match.model_context import (
    ModelPlayerReference,
    build_actor_information,
    build_private_round_memory_source_context,
    build_public_match_state,
    build_public_rule_contract,
    private_round_memory_objective,
    private_authoritative_facts,
)
from app.match.model_context_contract import is_supported_model_context_contract
from app.match.model_generation_policy_contract import (
    resolve_model_generation_action_policy,
)
from app.match.model_client import ModelDecision, ModelError, ProviderAdmissionMode
from app.match.protocol import (
    day_progress,
    game_phase_changed,
    live_state,
    match_state_changed,
    player_state_changed,
)
from app.match.pre_exile_pipeline_contract import (
    RECOVERABLE_PRE_EXILE_VOTE_CATEGORIES,
    pre_exile_context_sha256,
)
from app.match.pre_exile_pipeline_repository import PreExilePipelineRepository
from app.match.repository import (
    ExecutionOwnershipLost,
    PhaseTransition,
    PresentationIdentity,
)


logger = logging.getLogger(__name__)

_BACKGROUND_MEMORY_JOIN_SECONDS = 1.0


@dataclass
class _BackgroundPrivateMemoryJob:
    game_id: str
    batch_id: str
    round_no: int
    started_at: float
    timeout_ms: int
    player_done: dict[str, asyncio.Event]
    task: asyncio.Task[None] | None = None
    memories: list[dict[str, Any]] = field(default_factory=list)
    commit_phase_ids: list[str] = field(default_factory=list)

_SUPPORTED_DAY_ACTIONS = {
    "sheriff_run",
    "sheriff_speech",
    "sheriff_withdraw",
    "sheriff_vote",
    "sheriff_pk_speech",
    "sheriff_runoff_vote",
    "werewolf_self_explosion",
    "speech_order",
    "sheriff_badge",
    "debate",
    "vote",
    "exile_pk_speech",
    "exile_runoff_vote",
    "exile_last_words",
    "hunter_shoot",
    "summarize",
}
# Batch target votes: the phases whose fan-out drives provider admission load.
_VOTE_PHASE_ACTION_TYPES = frozenset(
    {
        "exile_vote",
        "sheriff_vote",
        "sheriff_runoff_vote",
        "exile_runoff_vote",
    }
)
_SHERIFF_PK_SPEECH_OBJECTIVE = "发表警长竞选平票 PK 发言。"
_EXILE_PK_SPEECH_OBJECTIVE = "发表放逐平票 PK 发言。"
_VOTE_MACHINE_FORMAT_AUTOMATIC_BUDGET = 2
_VOTE_OUTPUT_BUDGET_AUTOMATIC_BUDGET = 3
_PUBLIC_SPEECH_MAX_CHARS = {
    "first_night_last_words": 200,
    "sheriff_campaign_speech": 300,
    "sheriff_pk_speech": 300,
    "day_debate_speech": 300,
    "exile_pk_speech": 300,
    "exile_last_words": 200,
}


def _vote_decision_family_id(
    *,
    batch_id: str,
    action_type: str,
    voter: MatchPlayer,
    candidates: list[MatchPlayer],
    projection_at_seq: int,
    model_context_contract: dict[str, Any] | None,
) -> str:
    canonical = json.dumps(
        {
            "batch_id": batch_id,
            "action_type": action_type,
            "actor_id": voter.player_id,
            "candidate_ids": [candidate.player_id for candidate in candidates],
            "projection_at_seq": projection_at_seq,
            "model_provider": voter.model_provider,
            "model_id": voter.model_id,
            "model_context_contract": model_context_contract,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"v2_decision_{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


_PRIVATE_ROUND_MEMORY_MAX_CHARS = 400
_DECISION_NOTE_MAX_CHARS = 80
_DAY_SPEECH_PREFETCH_POST_CLOSE_DEADLINE = "day_speech_prefetch_post_close_deadline"


class DayRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class _PreparedDaySpeech:
    slot: DaySpeechSlotSnapshot
    decision: ModelDecision


@dataclass(frozen=True)
class _FailedDaySpeechPrefetch:
    slot: DaySpeechSlotSnapshot
    source_action_id: str | None
    failure: ActionFailure
    terminal_event_record_seq: int | None


_DaySpeechPrefetchOutcome = _PreparedDaySpeech | _FailedDaySpeechPrefetch


@dataclass
class _DaySpeechPrefetchLaunch:
    slot: DaySpeechSlotSnapshot | None = None
    task: asyncio.Task[None] | None = None
    outcome: _DaySpeechPrefetchOutcome | None = None
    fatal: BaseException | None = None


@dataclass
class _PreExileLaunch:
    presentation_closed: asyncio.Event
    predecessor_committed: asyncio.Event
    pipeline: Any | None = None
    frozen: Any | None = None
    run_fence: Any | None = None
    task: asyncio.Task[Any] | None = None
    preparation_error: BaseException | None = None


@dataclass(frozen=True)
class _PreparedPreExileVote:
    pipeline_id: str
    run_fence: Any | None
    frozen_state: MatchSnapshot
    public_history_cutoff_record_seq: int
    initial_results_by_voter: dict[str, ActionResult]
    frozen_private_facts_by_voter: dict[str, list[dict[str, Any]]]


@dataclass(frozen=True)
class _PreExileOutcome:
    pipeline_id: str
    selected_explosion_player_id: str | None = None
    prepared_vote: _PreparedPreExileVote | None = None


@dataclass(frozen=True)
class _PublicDiscussionResult:
    exploded: bool
    pre_exile_launch: _PreExileLaunch | None = None


def _prepared_day_speech_from_slot(
    slot: DaySpeechSlotSnapshot,
) -> _PreparedDaySpeech:
    decision = slot.decision if isinstance(slot.decision, dict) else {}
    speech = decision.get("speech")
    if not isinstance(speech, str) or not speech.strip():
        raise DayRuntimeError("ready day speech slot has no reusable speech")
    target_player_id = decision.get("target_player_id")
    decision_note = decision.get("decision_note")
    return _PreparedDaySpeech(
        slot=slot,
        decision=ModelDecision(
            target_player_id=(target_player_id if isinstance(target_player_id, str) else None),
            speech=speech,
            provider_request_id=(
                slot.generation_attempt_id or slot.generation_action_id or slot.slot_id
            ),
            first_token_ms=0,
            completed_ms=0,
            decision_note=(decision_note if isinstance(decision_note, str) else None),
        ),
    )


def _failed_day_speech_prefetch_from_slot(
    slot: DaySpeechSlotSnapshot,
) -> _FailedDaySpeechPrefetch:
    persisted = slot.failure if isinstance(slot.failure, dict) else {}
    action_failed = persisted.get("action_failed")
    action_failed = action_failed if isinstance(action_failed, dict) else {}
    request_failed = persisted.get("model_request_failed")
    request_failed = request_failed if isinstance(request_failed, dict) else {}
    reason_code = persisted.get("reason_code")
    failure_code = action_failed.get("failure_code") or request_failed.get("failure_code")
    if not isinstance(failure_code, str) or not failure_code:
        failure_code = (
            reason_code
            if isinstance(reason_code, str) and reason_code
            else "day_speech_prefetch_terminal_without_failure_lineage"
        )
    failure_category = request_failed.get("failure_category")
    if failure_code == _DAY_SPEECH_PREFETCH_POST_CLOSE_DEADLINE:
        failure_category = "timeout"
    if not isinstance(failure_category, str):
        failure_category = None
    source_action_id = slot.generation_action_id or action_failed.get("action_id")
    if not isinstance(source_action_id, str):
        source_action_id = None
    failure_episode_id = action_failed.get("failure_episode_id") or request_failed.get(
        "failure_episode_id"
    )
    if not isinstance(failure_episode_id, str):
        failure_episode_id = None
    return _FailedDaySpeechPrefetch(
        slot=slot,
        source_action_id=source_action_id,
        failure=ActionFailure(
            code=failure_code,
            category=failure_category,
            terminal_attempt_id=slot.generation_attempt_id,
            failure_episode_id=failure_episode_id,
        ),
        terminal_event_record_seq=slot.failure_record_seq,
    )


def speech_order_from_start(
    alive_by_seat: Iterable[MatchPlayer],
    sheriff_player_id: str,
    start_player_id: str,
) -> list[str]:
    alive = sorted(tuple(alive_by_seat), key=lambda item: item.seat)
    alive_ids = [item.player_id for item in alive]
    if len(alive) < 2 or sheriff_player_id not in alive_ids:
        raise DayRuntimeError("sheriff_speech_order_invalid_state")
    sheriff_index = alive_ids.index(sheriff_player_id)
    left = alive[(sheriff_index - 1) % len(alive)]
    right = alive[(sheriff_index + 1) % len(alive)]
    if start_player_id not in {left.player_id, right.player_id}:
        raise DayRuntimeError("sheriff_speech_order_invalid_start")
    if start_player_id == right.player_id:
        ordered = alive[sheriff_index + 1 :] + alive[: sheriff_index + 1]
    else:
        ordered = list(reversed(alive[:sheriff_index])) + list(reversed(alive[sheriff_index:]))
    result = [item.player_id for item in ordered]
    if result[-1] != sheriff_player_id or set(result) != set(alive_ids):
        raise DayRuntimeError("sheriff_speech_order_invalid_result")
    return result


class DayEngine:
    def __init__(
        self,
        *,
        repository: MatchRepository,
        action_engine: ActionEngine,
        day_speech_pipeline_repository: DaySpeechPipelineRepository | None = None,
        pre_exile_pipeline_repository: PreExilePipelineRepository | None = None,
    ) -> None:
        self._repository = repository
        self._actions = action_engine
        self._day_speech_pipeline = day_speech_pipeline_repository
        self._pre_exile_pipeline = pre_exile_pipeline_repository
        self._background_memory_jobs: dict[str, _BackgroundPrivateMemoryJob] = {}

    async def join_background_private_memory_jobs(
        self,
        *,
        game_id: str | None = None,
        timeout: float | None = _BACKGROUND_MEMORY_JOIN_SECONDS,
        cancel: bool = False,
    ) -> None:
        jobs = [
            job
            for job in list(self._background_memory_jobs.values())
            if game_id is None or job.game_id == game_id
        ]
        tasks = [job.task for job in jobs if job.task is not None]
        if cancel:
            for task in tasks:
                if not task.done():
                    task.cancel()
        if not tasks:
            for job in jobs:
                self._background_memory_jobs.pop(job.batch_id, None)
            return
        try:
            if timeout is None:
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for job in jobs:
            if job.task is None or job.task.done():
                self._background_memory_jobs.pop(job.batch_id, None)

    async def resolve_pending_death_aftermath(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> None:
        """Resolve public death consequences left by the preceding night."""
        self._actions.check_cancellation(game_id)
        await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)

    async def run_pre_dawn_sheriff_election(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> None:
        self._actions.check_cancellation(game_id)
        state = self._repository.snapshot(game_id)
        actions = set(state.rule.get("day_actions") or [])
        if not self._should_run_sheriff_election(state, actions):
            raise DayRuntimeError("pre_dawn_sheriff_election_not_configured")
        await self._open_day_window(
            state=state,
            broadcaster=broadcaster,
            opening_state="sheriff_election_open",
            action_type="judge_sheriff_election_opening",
            objective=f"宣布第{state.round_no}天警长竞选开始，并请所有公开存活玩家决定是否参选",
        )
        await self._run_sheriff_election(game_id=game_id, broadcaster=broadcaster)

    async def run_first_night_last_words(
        self,
        *,
        game_id: str,
        player_ids: tuple[str, ...],
        broadcaster: BroadcastPort,
    ) -> None:
        state = self._repository.snapshot(game_id)
        for player_id in sorted(player_ids, key=lambda value: state.player(value).seat):
            player = state.player(player_id)
            decision = await self._player_action(
                game_id=game_id,
                player=player,
                broadcaster=broadcaster,
                action_type="first_night_last_words",
                objective="发表首夜遗言；你不知道具体死亡原因。",
                candidates=[],
                target_optional=None,
                output_kind="public_speech",
                extra_context={"death_cause_reveal_policy": "hidden"},
            )
            self._record_speech(state, player, decision, "first_night_last_words")

    async def run(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> PhaseTransition | None:
        try:
            self._actions.check_cancellation(game_id)
            state = self._repository.snapshot(game_id)
            await broadcaster.broadcast_json(
                day_progress(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    round_no=state.round_no,
                    stage="day_started",
                )
            )
            actions = set(state.rule.get("day_actions") or [])
            unknown_actions = actions - _SUPPORTED_DAY_ACTIONS
            if unknown_actions:
                raise DayRuntimeError(
                    "unsupported_day_actions:" + ",".join(sorted(unknown_actions))
                )
            if self._should_run_sheriff_election(state, actions):
                await self._open_day_window(
                    state=state,
                    broadcaster=broadcaster,
                    opening_state="sheriff_election_open",
                    action_type="judge_sheriff_election_opening",
                    objective=f"宣布第{state.round_no}天警长竞选开始，并请存活玩家准备决定是否参选",
                )
                exploded = await self._offer_pre_sheriff_explosion(
                    game_id=game_id,
                    broadcaster=broadcaster,
                )
                if exploded:
                    await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)
                    return await self._close_day(
                        game_id=game_id,
                        broadcaster=broadcaster,
                        reason="pre_sheriff_self_explosion",
                        summarize=False,
                    )
                await self._run_sheriff_election(game_id=game_id, broadcaster=broadcaster)
                current = self._repository.snapshot(game_id)
                await self._open_day_window(
                    state=current,
                    broadcaster=broadcaster,
                    opening_state="public_discussion_open",
                    action_type="judge_public_discussion_opening",
                    objective=f"宣布第{current.round_no}天正式白天讨论开始",
                )
            else:
                await self._open_day_window(
                    state=state,
                    broadcaster=broadcaster,
                    opening_state="public_discussion_open",
                    action_type="judge_public_discussion_opening",
                    objective=f"宣布第{state.round_no}天白天讨论开始，并请存活玩家依次公开发言",
                )

            discussion = _PublicDiscussionResult(exploded=False)
            if "debate" in actions:
                discussion_result = await self._run_public_discussion(
                    game_id=game_id,
                    broadcaster=broadcaster,
                )
                discussion = (
                    discussion_result
                    if isinstance(discussion_result, _PublicDiscussionResult)
                    else _PublicDiscussionResult(exploded=discussion_result)
                )
                if discussion.exploded:
                    await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)
                    return await self._close_day(
                        game_id=game_id,
                        broadcaster=broadcaster,
                        reason="discussion_self_explosion",
                        summarize=False,
                    )

            if "vote" in actions:
                pre_exile = (
                    await self._consume_pre_exile_launch(
                        launch=discussion.pre_exile_launch,
                        broadcaster=broadcaster,
                    )
                    if discussion.pre_exile_launch is not None
                    else None
                )
                if pre_exile is None:
                    exploded = await self._offer_all_wolves_explosion(
                        game_id=game_id,
                        broadcaster=broadcaster,
                        stage="before_exile_vote",
                    )
                else:
                    exploded = pre_exile.selected_explosion_player_id is not None
                    if exploded:
                        await self._commit_pre_exile_explosion(
                            outcome=pre_exile,
                            broadcaster=broadcaster,
                        )
                if exploded:
                    await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)
                    return await self._close_day(
                        game_id=game_id,
                        broadcaster=broadcaster,
                        reason="pre_vote_self_explosion",
                        summarize=False,
                    )
                prepared_vote = pre_exile.prepared_vote if pre_exile is not None else None
                exile = await self._run_exile_vote(
                    game_id=game_id,
                    broadcaster=broadcaster,
                    pre_exile_pipeline_id=(prepared_vote.pipeline_id if prepared_vote else None),
                    pre_exile_run_fence=(prepared_vote.run_fence if prepared_vote else None),
                    frozen_state=(prepared_vote.frozen_state if prepared_vote else None),
                    frozen_private_facts_by_voter=(
                        prepared_vote.frozen_private_facts_by_voter if prepared_vote else None
                    ),
                    initial_results_by_voter=(
                        prepared_vote.initial_results_by_voter if prepared_vote else None
                    ),
                    public_history_cutoff_record_seq=(
                        prepared_vote.public_history_cutoff_record_seq if prepared_vote else None
                    ),
                )
                if exile is not None:
                    await self._resolve_exile_aftermath(
                        game_id=game_id,
                        exile=exile,
                        broadcaster=broadcaster,
                    )

            self._actions.check_cancellation(game_id)
            return await self._close_day(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="day_actions_completed",
                summarize="summarize" in actions,
            )
        except ExecutionOwnershipLost:
            raise
        except Exception as exc:
            logger.warning(
                "Live V2 day runtime failed: %s",
                exc,
                extra={"game_id": game_id, "failure_code": str(exc)},
            )
            try:
                run_id = self._repository.fail_runtime(
                    game_id=game_id,
                    failure_code=_failure_code(exc),
                )
                state = self._repository.snapshot(game_id)
            except Exception:
                logger.exception("Live V2 could not persist day runtime failure")
                return None
            await broadcaster.broadcast_json(
                live_state(
                    game_id=state.game_id,
                    run_id=run_id,
                    state="failed",
                    reason=_failure_code(exc),
                )
            )
            return None

    def _should_run_sheriff_election(
        self,
        state: MatchSnapshot,
        actions: set[str],
    ) -> bool:
        return (
            bool(state.rule.get("sheriff_enabled"))
            and "sheriff_run" in actions
            and state.sheriff_badge_state == "pending"
        )

    async def _open_day_window(
        self,
        *,
        state: MatchSnapshot,
        broadcaster: BroadcastPort,
        opening_state: str,
        action_type: str,
        objective: str,
    ) -> None:
        previous_state = state.phase_state
        ok = await self._judge(
            state=state,
            broadcaster=broadcaster,
            action_type=action_type,
            objective=objective,
            success_phase_state=opening_state,
            context={"round_no": state.round_no},
        )
        if not ok:
            raise DayRuntimeError(f"{action_type}_failed")
        self._actions.check_cancellation(state.game_id)
        transition = self._repository.record_phase_state(
            game_id=state.game_id,
            previous_phase_state=previous_state,
        )
        await broadcaster.broadcast_json(game_phase_changed(transition))

    async def _run_sheriff_election(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> None:
        self._actions.check_cancellation(game_id)
        state = self._repository.snapshot(game_id)
        alive = sorted(
            (player for player in state.players if player.alive),
            key=lambda player: player.seat,
        )
        sheriff_run = await self._collect_boolean_decisions(
            game_id=game_id,
            broadcaster=broadcaster,
            state=state,
            players=alive,
            action_type="sheriff_run",
            objective="决定是否竞选警长。",
            output_kind="public_decision",
            boolean_field="run_for_sheriff",
            true_meaning="竞选警长",
            false_meaning="不竞选警长",
            decision_event_type="sheriff_run_decided",
            decision_payload_field="is_running",
        )
        candidates = [player for player in alive if sheriff_run[player.player_id]]

        original_candidates = tuple(candidates)
        original_off_sheriff = [
            player
            for player in alive
            if player.player_id not in {item.player_id for item in candidates}
        ]
        if not candidates:
            await self._destroy_badge(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="no_sheriff_candidates",
            )
            return

        for candidate in candidates:
            self._actions.check_cancellation(game_id)
            decision = await self._player_action(
                game_id=game_id,
                player=candidate,
                broadcaster=broadcaster,
                action_type="sheriff_campaign_speech",
                objective="发表警长竞选发言。",
                candidates=[],
                target_optional=None,
                output_kind="public_speech",
            )
            self._record_speech(state, candidate, decision, "sheriff_campaign")

        # Every candidate has now heard the same complete campaign transcript.
        # Freeze that public boundary before collecting any private withdrawal.
        withdraw_state = self._repository.snapshot(game_id)
        sheriff_withdraw = await self._collect_boolean_decisions(
            game_id=game_id,
            broadcaster=broadcaster,
            state=withdraw_state,
            players=candidates,
            action_type="sheriff_withdraw",
            objective="决定是否退水。",
            output_kind="sheriff_withdraw_decision",
            boolean_field="withdraw",
            true_meaning="退水",
            false_meaning="不退水",
            decision_event_type="sheriff_withdraw_decided",
            decision_payload_field="withdrew",
        )
        remaining = [
            candidate for candidate in candidates if not sheriff_withdraw[candidate.player_id]
        ]

        if not remaining:
            await self._destroy_badge(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="all_candidates_withdrew",
            )
            return
        if len(remaining) == 1:
            await self._elect_sheriff(
                game_id=game_id,
                player=remaining[0],
                broadcaster=broadcaster,
                reason="sole_remaining_candidate",
            )
            return
        if not original_off_sheriff:
            await self._destroy_badge(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="no_off_sheriff_voters",
            )
            return

        votes = await self._collect_votes(
            game_id=game_id,
            broadcaster=broadcaster,
            action_type="sheriff_vote",
            voters=original_off_sheriff,
            candidates=remaining,
            weighted=False,
            context={
                "original_candidate_ids": [item.player_id for item in original_candidates],
                "original_off_sheriff_voter_ids": [item.player_id for item in original_off_sheriff],
            },
        )
        leaders = _leaders(votes)
        if not leaders:
            await self._destroy_badge(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="no_valid_sheriff_votes",
            )
            return
        if len(leaders) == 1:
            winner = next(item for item in remaining if item.player_id == leaders[0])
            await self._elect_sheriff(
                game_id=game_id,
                player=winner,
                broadcaster=broadcaster,
                reason="sheriff_vote_unique_leader",
            )
            return

        tied = [item for item in remaining if item.player_id in set(leaders)]
        for candidate in tied:
            self._actions.check_cancellation(game_id)
            decision = await self._player_action(
                game_id=game_id,
                player=candidate,
                broadcaster=broadcaster,
                action_type="sheriff_pk_speech",
                objective=_SHERIFF_PK_SPEECH_OBJECTIVE,
                candidates=[],
                target_optional=None,
                output_kind="public_speech",
            )
            self._record_speech(state, candidate, decision, "sheriff_pk")
        runoff = await self._collect_votes(
            game_id=game_id,
            broadcaster=broadcaster,
            action_type="sheriff_runoff_vote",
            voters=original_off_sheriff,
            candidates=tied,
            weighted=False,
            context={"pk_candidate_ids": [item.player_id for item in tied]},
        )
        runoff_leaders = _leaders(runoff)
        if len(runoff_leaders) != 1:
            await self._destroy_badge(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="sheriff_runoff_tie",
            )
            return
        winner = next(item for item in tied if item.player_id == runoff_leaders[0])
        await self._elect_sheriff(
            game_id=game_id,
            player=winner,
            broadcaster=broadcaster,
            reason="sheriff_runoff_unique_leader",
        )

    async def _collect_boolean_decisions(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        state: MatchSnapshot,
        players: list[MatchPlayer],
        action_type: str,
        objective: str,
        output_kind: str,
        boolean_field: str,
        true_meaning: str,
        false_meaning: str,
        decision_event_type: str,
        decision_payload_field: str,
    ) -> dict[str, bool]:
        ordered = sorted(players, key=lambda player: player.seat)
        public_cutoff_record_seq = state.last_record_seq
        batch_id = f"{state.phase_id}:{action_type}:{public_cutoff_record_seq}:boolean"

        async def request_decision(player: MatchPlayer) -> ModelDecision | None:
            return await self._player_action(
                game_id=game_id,
                player=player,
                broadcaster=broadcaster,
                action_type=action_type,
                objective=objective,
                candidates=[],
                target_optional=None,
                output_kind=output_kind,
                decision_contract=DecisionContract(
                    kind="boolean",
                    boolean_field=boolean_field,
                    speech_mode="forbidden",
                    decision_note_mode="optional",
                    decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
                    true_meaning=true_meaning,
                    false_meaning=false_meaning,
                ),
                extra_context={
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                    "boolean_batch_stage": "concurrent_initial",
                },
                frozen_state=state,
                defer_presentation=True,
                isolated_failure=True,
                allow_failure=True,
                batch_id=batch_id,
            )

        decisions = await asyncio.gather(*(request_decision(player) for player in ordered))
        resolved: dict[str, bool] = {}
        failed_player_ids: list[str] = []
        for player, decision in zip(ordered, decisions, strict=True):
            if decision is not None and not isinstance(decision.boolean_value, bool):
                raise DayRuntimeError(f"{action_type}_invalid_decision")
            if decision is None:
                failed_player_ids.append(player.player_id)
            resolved[player.player_id] = bool(decision and decision.boolean_value)

        # Keep settlement deterministic and invisible to peers until every
        # participant has completed the same frozen decision batch.
        for player in ordered:
            self._repository.append_event(
                game_id=game_id,
                event_type=decision_event_type,
                audience="all",
                payload={
                    "round_no": state.round_no,
                    "player_id": player.player_id,
                    decision_payload_field: resolved[player.player_id],
                    "decision_status": (
                        "failed" if player.player_id in failed_player_ids else "completed"
                    ),
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                },
            )
        self._repository.append_event(
            game_id=game_id,
            event_type=f"{action_type}_batch_resolved",
            audience="all",
            payload={
                "round_no": state.round_no,
                "action_type": action_type,
                "batch_id": batch_id,
                "public_cutoff_record_seq": public_cutoff_record_seq,
                "eligible_player_ids": [player.player_id for player in ordered],
                "failed_player_ids": failed_player_ids,
                "affirmative_player_ids": [
                    player.player_id for player in ordered if resolved[player.player_id]
                ],
                "failure_policy": "false",
                "commit_order": "seat_ascending",
            },
        )
        for player, decision in zip(ordered, decisions, strict=True):
            if decision is None:
                continue
            self._repository.record_private_action_decision(
                game_id=game_id,
                player_id=player.player_id,
                round_no=state.round_no,
                action_type=action_type,
                decision={boolean_field: resolved[player.player_id]},
                decision_note=decision.decision_note,
                context={
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                },
            )
        return resolved

    async def _run_public_discussion(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> _PublicDiscussionResult | bool:
        self._actions.check_cancellation(game_id)
        state = self._repository.snapshot(game_id)
        order = await self._speech_order(state=state, broadcaster=broadcaster)
        rounds = max(1, int(state.rule.get("speech_rounds") or 1))
        pre_exile_launch: _PreExileLaunch | None = None
        for speech_round in range(1, rounds + 1):
            if await self._offer_all_wolves_explosion(
                game_id=game_id,
                broadcaster=broadcaster,
                stage=f"discussion_round_{speech_round}",
                public_window_context={
                    "speech_round": speech_round,
                    "speech_order": order,
                },
            ):
                return True
            round_state = self._repository.snapshot(game_id)
            if not self._day_speech_pipeline_enabled(round_state):
                for player_id in order:
                    self._actions.check_cancellation(game_id)
                    current = self._repository.snapshot(game_id)
                    player = current.player(player_id)
                    if not player.alive:
                        continue
                    final_public_turn = speech_round == rounds and player_id == order[-1]
                    if final_public_turn and self._pre_exile_pipeline_enabled(current):
                        pre_exile_launch = _PreExileLaunch(
                            presentation_closed=asyncio.Event(),
                            predecessor_committed=asyncio.Event(),
                        )
                    try:
                        decision = await self._player_action(
                            game_id=game_id,
                            player=player,
                            broadcaster=broadcaster,
                            action_type="day_debate_speech",
                            objective="发表本轮白天讨论发言。",
                            candidates=[],
                            target_optional=None,
                            output_kind="public_speech",
                            extra_context={
                                "speech_round": speech_round,
                                "speech_order": order,
                            },
                            on_presentation_opened=(
                                lambda identity, launch=pre_exile_launch: (
                                    (
                                        self._launch_pre_exile_pipeline(
                                            launch=launch,
                                            identity=identity,
                                            phase_state=current.phase_state,
                                            speech_round=speech_round,
                                            speech_order=order,
                                            broadcaster=broadcaster,
                                        )
                                        if launch is not None
                                        else None
                                    )
                                    if final_public_turn
                                    else None
                                )
                            ),
                            on_presentation_closed=(
                                lambda _identity, launch=pre_exile_launch: (
                                    (
                                        launch.presentation_closed.set()
                                        if launch is not None
                                        else None
                                    )
                                    if final_public_turn
                                    else None
                                )
                            ),
                        )
                    except asyncio.CancelledError:
                        if final_public_turn and pre_exile_launch is not None:
                            await self._abort_pre_exile_launch(
                                pre_exile_launch,
                                reason_code="predecessor_presentation_canceled",
                            )
                        raise
                    except BaseException:
                        if final_public_turn and pre_exile_launch is not None:
                            await self._abort_pre_exile_launch(
                                pre_exile_launch,
                                reason_code="predecessor_presentation_failed",
                            )
                        raise
                    assert isinstance(decision, ModelDecision)
                    try:
                        self._record_speech(current, player, decision, "day_debate")
                    except BaseException:
                        if final_public_turn and pre_exile_launch is not None:
                            await self._abort_pre_exile_launch(
                                pre_exile_launch,
                                reason_code="predecessor_canonical_speech_commit_failed",
                            )
                        raise
                    if final_public_turn and pre_exile_launch is not None:
                        pre_exile_launch.predecessor_committed.set()
                continue

            prepared: _DaySpeechPrefetchOutcome | None = None
            for turn_offset, player_id in enumerate(order):
                self._actions.check_cancellation(game_id)
                current = self._repository.snapshot(game_id)
                player = current.player(player_id)
                if not player.alive:
                    if prepared is not None and prepared.slot.actor_player_id == player_id:
                        self._cancel_day_speech_slot(
                            prepared.slot.slot_id,
                            reason_code="prefetched_actor_no_longer_alive",
                        )
                        prepared = None
                    continue
                if prepared is not None and (
                    prepared.slot.actor_player_id != player_id
                    or prepared.slot.speech_round != speech_round
                    or prepared.slot.turn_index != turn_offset + 1
                ):
                    self._cancel_day_speech_slot(
                        prepared.slot.slot_id,
                        reason_code="prefetched_turn_no_longer_matches",
                    )
                    prepared = None
                next_player_id = order[turn_offset + 1] if turn_offset + 1 < len(order) else None
                final_public_turn = speech_round == rounds and next_player_id is None
                if final_public_turn and self._pre_exile_pipeline_enabled(current):
                    pre_exile_launch = _PreExileLaunch(
                        presentation_closed=asyncio.Event(),
                        predecessor_committed=asyncio.Event(),
                    )
                decision, next_prepared = await self._run_day_speech_pipeline_turn(
                    state=current,
                    player=player,
                    prepared=prepared,
                    next_player_id=next_player_id,
                    next_turn_index=turn_offset + 2,
                    speech_round=speech_round,
                    speech_order=order,
                    broadcaster=broadcaster,
                    pre_exile_launch=(pre_exile_launch if final_public_turn else None),
                )
                try:
                    self._record_speech(current, player, decision, "day_debate")
                except BaseException:
                    if final_public_turn and pre_exile_launch is not None:
                        await self._abort_pre_exile_launch(
                            pre_exile_launch,
                            reason_code="predecessor_canonical_speech_commit_failed",
                        )
                    if next_prepared is not None:
                        self._cancel_day_speech_slot(
                            next_prepared.slot.slot_id,
                            reason_code="prefetch_predecessor_commit_failed",
                        )
                    raise
                if final_public_turn and pre_exile_launch is not None:
                    pre_exile_launch.predecessor_committed.set()
                prepared = next_prepared
        if pre_exile_launch is None or pre_exile_launch.task is None:
            return False
        return _PublicDiscussionResult(exploded=False, pre_exile_launch=pre_exile_launch)

    def _day_speech_pipeline_enabled(self, state: MatchSnapshot) -> bool:
        return bool(
            self._day_speech_pipeline is not None
            and state.audio_mode == "tts"
            and state.day_speech_pipeline_contract.max_lookahead == 1
            and state.day_speech_pipeline_contract.enables("day_debate_speech")
        )

    def _pre_exile_pipeline_enabled(self, state: MatchSnapshot) -> bool:
        contract = getattr(state, "pre_exile_pipeline_contract", None)
        return bool(
            self._pre_exile_pipeline is not None
            and contract is not None
            and callable(getattr(contract, "enables", None))
            and contract.enables("werewolf_self_explosion")
            and contract.enables("exile_vote")
            and bool(state.rule.get("werewolf_self_explosion_enabled"))
            and any(player.alive and player.role_key == "werewolf" for player in state.players)
            and "vote" in set(state.rule.get("day_actions") or [])
        )

    def _launch_pre_exile_pipeline(
        self,
        *,
        launch: _PreExileLaunch,
        identity: PresentationIdentity,
        phase_state: str,
        speech_round: int,
        speech_order: list[str],
        broadcaster: BroadcastPort,
        predecessor_turn_player_id: str | None = None,
    ) -> None:
        pipeline_repository = self._pre_exile_pipeline
        if pipeline_repository is None or launch.task is not None:
            return
        try:
            frozen = self._repository.snapshot_for_pre_exile_pipeline(
                game_id=identity.game_id,
                run_id=identity.run_id,
                phase_id=identity.phase_id,
                phase_state=phase_state,
                predecessor_presentation_id=identity.presentation_id,
                predecessor_action_id=identity.action_id,
                predecessor_source_event_id=identity.source_event_id,
                predecessor_turn_player_id=predecessor_turn_player_id,
            )
            if not self._pre_exile_pipeline_enabled(frozen.match_snapshot):
                return
            if (
                speech_round
                != max(
                    1,
                    int(frozen.match_snapshot.rule.get("speech_rounds") or 1),
                )
                or not speech_order
                or frozen.predecessor_actor_id != speech_order[-1]
            ):
                raise DayRuntimeError("pre_exile_predecessor_is_not_final_public_turn")
            pipeline = pipeline_repository.reserve_pipeline(
                game_id=identity.game_id,
                phase_id=identity.phase_id,
                round_no=frozen.match_snapshot.round_no,
                predecessor_action_id=frozen.predecessor_action_id,
                predecessor_presentation_id=frozen.predecessor_presentation_id,
                predecessor_source_event_id=frozen.predecessor_source_event_id,
                predecessor_source_record_seq=frozen.predecessor_source_record_seq,
                predecessor_sealed_record_seq=frozen.predecessor_sealed_record_seq,
                public_cutoff_record_seq=frozen.public_cutoff_record_seq,
                public_history_sha256=pre_exile_context_sha256(
                    list(frozen.match_snapshot.public_history)
                ),
                fence=identity.run_fence,
            )
            launch.frozen = frozen
            launch.pipeline = pipeline
            launch.run_fence = identity.run_fence
            sealed_private_facts = {
                player.player_id: [
                    copy.deepcopy(fact)
                    for fact in self._repository.private_knowledge(
                        game_id=identity.game_id,
                        player_id=player.player_id,
                    )
                    if _private_fact_visible_at_public_cutoff(
                        fact,
                        frozen.public_cutoff_record_seq,
                    )
                ]
                for player in frozen.match_snapshot.players
                if player.alive
            }
            launch.task = asyncio.create_task(
                self._generate_pre_exile_pipeline(
                    launch=launch,
                    sealed_private_facts=sealed_private_facts,
                    broadcaster=broadcaster,
                ),
                name=f"pre-exile:{pipeline.pipeline_id}",
            )
        except (asyncio.CancelledError, ExecutionOwnershipLost):
            raise
        except BaseException as exc:
            launch.preparation_error = exc
            if launch.pipeline is not None:
                try:
                    pipeline_repository.invalidate_pipeline(
                        pipeline_id=launch.pipeline.pipeline_id,
                        reason_code="pre_exile_launch_preparation_failed",
                        fence=identity.run_fence,
                    )
                except BaseException:
                    logger.exception(
                        "Live V2 could not invalidate failed pre-exile launch",
                        extra={"game_id": identity.game_id},
                    )
            logger.exception(
                "Live V2 pre-exile launch failed before member generation",
                extra={
                    "game_id": identity.game_id,
                    "action_id": identity.action_id,
                    "presentation_id": identity.presentation_id,
                },
            )

    async def _abort_pre_exile_launch(
        self,
        launch: _PreExileLaunch,
        *,
        reason_code: str,
    ) -> None:
        task = launch.task
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        if launch.pipeline is None or self._pre_exile_pipeline is None:
            return
        try:
            self._pre_exile_pipeline.invalidate_pipeline(
                pipeline_id=launch.pipeline.pipeline_id,
                reason_code=reason_code,
                fence=launch.run_fence,
            )
        except ExecutionOwnershipLost:
            raise
        except Exception:
            logger.exception(
                "Live V2 could not invalidate abandoned pre-exile pipeline",
                extra={
                    "pipeline_id": launch.pipeline.pipeline_id,
                    "reason_code": reason_code,
                },
            )

    async def _generate_pre_exile_pipeline(
        self,
        *,
        launch: _PreExileLaunch,
        sealed_private_facts: dict[str, list[dict[str, Any]]],
        broadcaster: BroadcastPort,
    ) -> _PreExileOutcome:
        pipeline_repository = self._pre_exile_pipeline
        if pipeline_repository is None or launch.pipeline is None or launch.frozen is None:
            raise DayRuntimeError("pre_exile_pipeline_launch_incomplete")
        pipeline = launch.pipeline
        frozen = launch.frozen
        state: MatchSnapshot = frozen.match_snapshot
        self._actions.check_cancellation(state.game_id)
        await broadcaster.broadcast_json(
            day_progress(
                game_id=state.game_id,
                run_id=state.run_id,
                round_no=state.round_no,
                stage="pre_exile_special_action",
            )
        )
        alive = sorted(
            (player for player in state.players if player.alive), key=lambda item: item.seat
        )
        wolves = (
            [player for player in alive if player.role_key == "werewolf"]
            if bool(state.rule.get("werewolf_self_explosion_enabled"))
            else []
        )
        voters = [player for player in alive if player.state.get("can_vote", True)]
        vote_batch_id = f"{state.phase_id}:exile_vote:{frozen.public_cutoff_record_seq}:vote"
        result_slots = {
            ("self_explosion", wolf.player_id): pipeline_repository.reserve_result(
                pipeline_id=pipeline.pipeline_id,
                actor_player_id=wolf.player_id,
                result_kind="self_explosion",
                fence=launch.run_fence,
            )
            for wolf in wolves
        }
        result_slots.update(
            {
                ("exile_vote", voter.player_id): pipeline_repository.reserve_result(
                    pipeline_id=pipeline.pipeline_id,
                    actor_player_id=voter.player_id,
                    result_kind="exile_vote",
                    fence=launch.run_fence,
                )
                for voter in voters
            }
        )
        vote_results: dict[str, ActionResult] = {}
        vote_private_facts_by_voter: dict[str, list[dict[str, Any]]] = {}
        self_explosion_rows: dict[str, Any] = {}
        vote_tasks: dict[str, asyncio.Task[tuple[ActionResult, Any]]] = {}
        discard_votes = asyncio.Event()
        vote_progress_visible = asyncio.Event()
        vote_progress_lock = asyncio.Lock()
        completed_vote_count = 0
        pre_exile_contract = state.pre_exile_pipeline_contract
        self_explosion_hidden_retry_count = (
            pre_exile_contract.self_explosion_early_empty_stream_hidden_retry_max_retries
        )
        guarded_self_explosion_retry = self_explosion_hidden_retry_count == 1

        def predecessor_is_still_active(_exc: ModelError, _attempt_no: int) -> bool:
            return not launch.presentation_closed.is_set()

        async def publish_member_terminal(result_kind: str, recorded: Any) -> None:
            nonlocal completed_vote_count
            if result_kind == "self_explosion":
                await broadcaster.broadcast_json(
                    day_progress(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        round_no=state.round_no,
                        stage="pre_exile_special_action",
                    )
                )
                return
            if (
                recorded.failure is not None
                and _persisted_pre_exile_failure_category(recorded.failure)
                in RECOVERABLE_PRE_EXILE_VOTE_CATEGORIES
            ):
                return
            async with vote_progress_lock:
                completed_vote_count += 1
                if vote_progress_visible.is_set():
                    await broadcaster.broadcast_json(
                        day_progress(
                            game_id=state.game_id,
                            run_id=state.run_id,
                            round_no=state.round_no,
                            stage="pre_exile_vote_collecting",
                            completed_count=completed_vote_count,
                            total_count=len(voters),
                        )
                    )

        async def run_member(
            *,
            player: MatchPlayer,
            result_kind: Literal["self_explosion", "exile_vote"],
            private_facts: list[dict[str, Any]],
            on_model_admission_pending: Callable[[], None] | None = None,
        ) -> tuple[ActionResult, Any]:
            slot = result_slots[(result_kind, player.player_id)]
            if slot.state != "reserved":
                raise DayRuntimeError(
                    f"pre_exile_member_not_resumable:{slot.result_id}:{slot.state}"
                )
            if result_kind == "self_explosion":
                action_result = await self._player_action(
                    game_id=state.game_id,
                    player=player,
                    broadcaster=broadcaster,
                    action_type="werewolf_self_explosion",
                    objective="决定是否立即自爆。",
                    candidates=[],
                    target_optional=None,
                    audience="god_view",
                    output_kind="private_decision",
                    decision_contract=DecisionContract(
                        kind="boolean",
                        boolean_field="explode",
                        speech_mode="forbidden",
                        decision_note_mode="optional",
                        decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
                        true_meaning="立即自爆",
                        false_meaning="不自爆",
                    ),
                    extra_context={
                        "public_stage": "before_exile_vote",
                        "public_cutoff_record_seq": frozen.public_cutoff_record_seq,
                        "public_history_cutoff_record_seq": (frozen.public_cutoff_record_seq),
                        "current_action_effect": _self_explosion_action_effect(
                            state=state,
                            stage="before_exile_vote",
                            pre_sheriff=False,
                        ),
                        "batch_resolution_policy": "lowest_seat_affirmative",
                    },
                    frozen_state=state,
                    frozen_private_facts=private_facts,
                    defer_presentation=True,
                    isolated_failure=True,
                    allow_failure=True,
                    batch_id=pipeline.pipeline_id,
                    model_admission_mode="normal",
                    pipeline_slot_id=pipeline.pipeline_id,
                    pipeline_stage="generation",
                    pipeline_kind="pre_exile",
                    pipeline_result_kind="self_explosion",
                    pipeline_empty_stream_max_attempts=(
                        1 + self_explosion_hidden_retry_count
                    ),
                    pipeline_retry_mode=(
                        "empty_stream_once_while_predecessor_active"
                        if guarded_self_explosion_retry
                        else "disabled"
                    ),
                    model_retry_guard=(
                        predecessor_is_still_active if guarded_self_explosion_retry else None
                    ),
                    on_model_admission_pending=on_model_admission_pending,
                    return_result=True,
                )
            else:
                candidates = [
                    candidate for candidate in alive if candidate.player_id != player.player_id
                ]
                decision_family_id = _vote_decision_family_id(
                    batch_id=vote_batch_id,
                    action_type="exile_vote",
                    voter=player,
                    candidates=candidates,
                    projection_at_seq=frozen.public_cutoff_record_seq,
                    model_context_contract=state.model_context_contract,
                )
                action_result = await self._player_action(
                    game_id=state.game_id,
                    player=player,
                    broadcaster=broadcaster,
                    action_type="exile_vote",
                    objective="投票选择一名合法候选人。",
                    candidates=candidates,
                    target_optional=False,
                    output_kind="private_vote",
                    decision_contract=DecisionContract(
                        kind="target",
                        target_mode="required",
                        speech_mode="forbidden",
                        decision_note_mode="optional",
                        decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
                    ),
                    audience="god_view",
                    extra_context={
                        "vote_round": 1,
                        "public_cutoff_record_seq": frozen.public_cutoff_record_seq,
                        "public_history_cutoff_record_seq": (frozen.public_cutoff_record_seq),
                        "vote_batch_stage": "concurrent_initial",
                        **(
                            {"own_self_explosion_decision": False}
                            if player.role_key == "werewolf"
                            else {}
                        ),
                    },
                    frozen_state=state,
                    frozen_private_facts=private_facts,
                    defer_presentation=True,
                    isolated_failure=True,
                    allow_failure=True,
                    batch_id=vote_batch_id,
                    decision_family_id=decision_family_id,
                    automatic_machine_format_budget=(_VOTE_MACHINE_FORMAT_AUTOMATIC_BUDGET),
                    automatic_output_budget_budget=(_VOTE_OUTPUT_BUDGET_AUTOMATIC_BUDGET),
                    target_exhaustion_outcome="technical_abstain",
                    model_admission_mode="idle_only",
                    pipeline_slot_id=pipeline.pipeline_id,
                    pipeline_stage="generation",
                    pipeline_kind="pre_exile",
                    pipeline_result_kind="exile_vote",
                    return_result=True,
                )
            if not isinstance(action_result, ActionResult) or action_result.action_id is None:
                raise DayRuntimeError("pre_exile_member_action_result_missing")
            if (
                action_result.failure is not None
                and action_result.failure.category == "canceled"
                and not discard_votes.is_set()
            ):
                self._actions.check_cancellation(state.game_id)
                raise DayRuntimeError("pre_exile_member_canceled_without_discard")
            try:
                if action_result.failure is not None:
                    if action_result.terminal_event_record_seq is None:
                        raise DayRuntimeError("pre_exile_member_failure_terminal_lineage_missing")
                    recorded = pipeline_repository.record_failure(
                        pipeline_id=pipeline.pipeline_id,
                        actor_player_id=player.player_id,
                        result_kind=result_kind,
                        action_id=action_result.action_id,
                        failure_record_seq=action_result.terminal_event_record_seq,
                        fence=launch.run_fence,
                    )
                else:
                    recorded = pipeline_repository.record_result(
                        pipeline_id=pipeline.pipeline_id,
                        actor_player_id=player.player_id,
                        result_kind=result_kind,
                        action_id=action_result.action_id,
                        response_record_seq=action_result.model_response_record_seq,
                        terminal_record_seq=(
                            action_result.terminal_event_record_seq
                            if action_result.model_response_record_seq is not None
                            else None
                        ),
                        technical_outcome_record_seq=(
                            action_result.technical_outcome.supporting_event_record_seq
                            if action_result.technical_outcome is not None
                            else None
                        ),
                        fence=launch.run_fence,
                    )
            except Exception:
                if discard_votes.is_set() and result_kind == "exile_vote":
                    return action_result, slot
                raise
            await publish_member_terminal(result_kind, recorded)
            return action_result, recorded

        vote_fanout_slots = {
            voter.player_id: slot for slot, voter in enumerate(voters)
        }

        async def start_vote(
            player: MatchPlayer,
            private_facts: list[dict[str, Any]],
        ) -> tuple[ActionResult, Any]:
            fanout_delay = _vote_fanout_delay_seconds(
                vote_fanout_slots.get(player.player_id, 0)
            )
            if fanout_delay > 0:
                await asyncio.sleep(fanout_delay)
            vote_private_facts_by_voter[player.player_id] = copy.deepcopy(private_facts)
            result, recorded = await run_member(
                player=player,
                result_kind="exile_vote",
                private_facts=private_facts,
            )
            vote_results[player.player_id] = result
            return result, recorded

        normal_admission_pending = {wolf.player_id: asyncio.Event() for wolf in wolves}
        normal_batch_admission_ready = asyncio.Event()

        async def run_wolf_chain(wolf: MatchPlayer) -> tuple[ActionResult, Any]:
            admission_pending = normal_admission_pending[wolf.player_id]
            try:
                result, recorded = await run_member(
                    player=wolf,
                    result_kind="self_explosion",
                    private_facts=sealed_private_facts[wolf.player_id],
                    on_model_admission_pending=admission_pending.set,
                )
            finally:
                # A pre-admission terminal failure also releases the idle
                # launch barrier; there is then no normal waiter to protect.
                admission_pending.set()
            self_explosion_rows[wolf.player_id] = recorded
            decision = recorded.decision if isinstance(recorded.decision, dict) else {}
            if not bool(decision.get("explode")):
                await normal_batch_admission_ready.wait()
                private_fact_id = recorded.private_fact_id
                provisional_fact = pipeline_repository.get_provisional_self_explosion_fact(
                    pipeline_id=pipeline.pipeline_id,
                    actor_player_id=wolf.player_id,
                    private_fact_id=private_fact_id,
                    fence=launch.run_fence,
                )
                vote_private_facts = _pre_exile_wolf_vote_private_facts(
                    base=sealed_private_facts[wolf.player_id],
                    owner_facts=[provisional_fact],
                    owner_player_id=wolf.player_id,
                    pipeline_id=pipeline.pipeline_id,
                    private_fact_id=private_fact_id,
                    private_fact_record_seq=recorded.private_fact_record_seq,
                    public_cutoff_record_seq=frozen.public_cutoff_record_seq,
                )
                vote_tasks[wolf.player_id] = asyncio.create_task(
                    start_vote(wolf, vote_private_facts),
                    name=f"pre-exile-wolf-vote:{wolf.player_id}",
                )
            return result, recorded

        wolf_tasks = [
            asyncio.create_task(
                run_wolf_chain(wolf),
                name=f"pre-exile-self-explosion:{wolf.player_id}",
            )
            for wolf in wolves
        ]
        try:
            await asyncio.gather(*(event.wait() for event in normal_admission_pending.values()))
            for task in wolf_tasks:
                if task.done() and not task.cancelled():
                    task_error = task.exception()
                    if task_error is not None:
                        raise task_error
            normal_batch_admission_ready.set()
            for voter in voters:
                if voter.role_key != "werewolf":
                    vote_tasks[voter.player_id] = asyncio.create_task(
                        start_vote(voter, sealed_private_facts[voter.player_id]),
                        name=f"pre-exile-vote:{voter.player_id}",
                    )
            await asyncio.gather(*wolf_tasks)
            affirmative_ids = [
                wolf.player_id
                for wolf in wolves
                if bool(
                    (
                        self_explosion_rows[wolf.player_id].decision
                        if isinstance(
                            self_explosion_rows[wolf.player_id].decision,
                            dict,
                        )
                        else {}
                    ).get("explode")
                )
            ]
            if affirmative_ids:
                discard_votes.set()
                for task in vote_tasks.values():
                    if not task.done():
                        task.cancel("pre_exile_vote_discarded_by_self_explosion")
                await asyncio.gather(*vote_tasks.values(), return_exceptions=True)
            # The model work may finish while the final speech is still being
            # presented.  The arbiter must not mutate match state until that
            # predecessor has also been committed to the canonical day log.
            await launch.predecessor_committed.wait()
            self._actions.check_cancellation(state.game_id)
            resolution = self._repository.resolve_pre_exile_self_explosions(
                game_id=state.game_id,
                pipeline_id=pipeline.pipeline_id,
                expected_wolf_ids=tuple(wolf.player_id for wolf in wolves),
            )
            if resolution.outcome == "explosion_selected":
                await broadcaster.broadcast_json(
                    day_progress(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        round_no=state.round_no,
                        stage="pre_exile_special_action",
                    )
                )
                return _PreExileOutcome(
                    pipeline_id=pipeline.pipeline_id,
                    selected_explosion_player_id=resolution.selected_player_id,
                )
            async with vote_progress_lock:
                vote_progress_visible.set()
                await broadcaster.broadcast_json(
                    day_progress(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        round_no=state.round_no,
                        stage="pre_exile_vote_collecting",
                        completed_count=completed_vote_count,
                        total_count=len(voters),
                    )
                )
            await asyncio.gather(*vote_tasks.values())
            if set(vote_results) != {voter.player_id for voter in voters}:
                raise DayRuntimeError("pre_exile_vote_result_set_incomplete")
            if set(vote_private_facts_by_voter) != {voter.player_id for voter in voters}:
                raise DayRuntimeError("pre_exile_vote_private_context_set_incomplete")
            self._actions.check_cancellation(state.game_id)
            vote_rows = {
                row.actor_player_id: row
                for row in pipeline_repository.list_results(pipeline.pipeline_id)
                if row.result_kind == "exile_vote"
            }
            if set(vote_rows) != {voter.player_id for voter in voters}:
                raise DayRuntimeError("pre_exile_vote_durable_result_set_incomplete")
            # Non-recoverable persisted failures are degraded to durable
            # abstains inside the vote batch instead of failing the day.
            has_recoverable_vote_failure = any(
                row.failure is not None
                and _persisted_pre_exile_failure_category(row.failure)
                in RECOVERABLE_PRE_EXILE_VOTE_CATEGORIES
                for row in vote_rows.values()
            )
            if not has_recoverable_vote_failure:
                await broadcaster.broadcast_json(
                    day_progress(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        round_no=state.round_no,
                        stage="before_exile_vote",
                        completed_count=len(voters),
                        total_count=len(voters),
                    )
                )
            return _PreExileOutcome(
                pipeline_id=pipeline.pipeline_id,
                prepared_vote=_PreparedPreExileVote(
                    pipeline_id=pipeline.pipeline_id,
                    run_fence=launch.run_fence,
                    frozen_state=state,
                    public_history_cutoff_record_seq=frozen.public_cutoff_record_seq,
                    initial_results_by_voter=vote_results,
                    frozen_private_facts_by_voter=vote_private_facts_by_voter,
                ),
            )
        except BaseException:
            for task in [*wolf_tasks, *vote_tasks.values()]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                *wolf_tasks,
                *vote_tasks.values(),
                return_exceptions=True,
            )
            raise

    async def _consume_pre_exile_launch(
        self,
        *,
        launch: _PreExileLaunch,
        broadcaster: BroadcastPort,
    ) -> _PreExileOutcome | None:
        if launch.task is None:
            if launch.pipeline is None:
                return None
            raise DayRuntimeError("pre_exile_pipeline_reserved_without_task") from (
                launch.preparation_error
            )
        try:
            outcome = await launch.task
        except ExecutionOwnershipLost:
            raise
        except BaseException:
            if launch.pipeline is not None and self._pre_exile_pipeline is not None:
                try:
                    self._pre_exile_pipeline.invalidate_pipeline(
                        pipeline_id=launch.pipeline.pipeline_id,
                        reason_code="pre_exile_generation_failed",
                        fence=launch.run_fence,
                    )
                except ExecutionOwnershipLost:
                    raise
                except Exception:
                    logger.exception(
                        "Live V2 could not invalidate failed pre-exile generation",
                        extra={"pipeline_id": launch.pipeline.pipeline_id},
                    )
            raise
        self._actions.check_cancellation(
            outcome.prepared_vote.frozen_state.game_id
            if outcome.prepared_vote
            else launch.frozen.match_snapshot.game_id
        )
        return outcome

    async def _commit_pre_exile_explosion(
        self,
        *,
        outcome: _PreExileOutcome,
        broadcaster: BroadcastPort,
    ) -> None:
        pipeline_repository = self._pre_exile_pipeline
        selected_id = outcome.selected_explosion_player_id
        if pipeline_repository is None or selected_id is None:
            raise DayRuntimeError("pre_exile_explosion_outcome_incomplete")
        pipeline = pipeline_repository.get_pipeline(outcome.pipeline_id)
        state = self._repository.snapshot(pipeline.game_id)
        self._actions.check_cancellation(state.game_id)
        selected = state.player(selected_id)
        if (
            pipeline.state != "explosion_selected"
            or pipeline.selected_explosion_player_id != selected_id
            or selected.alive
        ):
            raise DayRuntimeError("pre_exile_explosion_was_not_atomically_committed")
        current = state
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_werewolf_self_explosion",
            objective=(f"公开宣布{selected.seat}号发动狼人自爆并立即出局，当天剩余流程中止"),
            success_phase_state=current.phase_state,
            context={
                "player_id": selected.player_id,
                "player_seat": selected.seat,
                "stage": "before_exile_vote",
                "outcome": "day_ended",
                "batch_id": pipeline.pipeline_id,
            },
        ):
            raise DayRuntimeError("self_explosion_announcement_failed")
        await self._broadcast_death(
            state=current,
            player_id=selected.player_id,
            cause="werewolf_self_explosion",
            broadcaster=broadcaster,
        )
        await self._broadcast_match_state(
            self._repository.snapshot(state.game_id),
            broadcaster,
        )

    async def _run_day_speech_pipeline_turn(
        self,
        *,
        state: MatchSnapshot,
        player: MatchPlayer,
        prepared: _DaySpeechPrefetchOutcome | None,
        next_player_id: str | None,
        next_turn_index: int,
        speech_round: int,
        speech_order: list[str],
        broadcaster: BroadcastPort,
        pre_exile_launch: _PreExileLaunch | None = None,
    ) -> tuple[ModelDecision, _DaySpeechPrefetchOutcome | None]:
        pipeline = self._day_speech_pipeline
        if pipeline is None:
            raise DayRuntimeError("day speech pipeline repository is unavailable")
        if isinstance(prepared, _FailedDaySpeechPrefetch):
            if self._day_speech_prefetch_requires_technical_skip(state, prepared):
                return await self._run_day_speech_technical_skip_turn(
                    state=state,
                    player=player,
                    failed_prefetch=prepared,
                    next_player_id=next_player_id,
                    next_turn_index=next_turn_index,
                    speech_round=speech_round,
                    speech_order=speech_order,
                    broadcaster=broadcaster,
                    pre_exile_launch=pre_exile_launch,
                )
            # Schema v1 and the schema-v2 capacity rejection policy preserve
            # the original foreground sequential fallback.
            prepared = None
        launch = _DaySpeechPrefetchLaunch()
        current_task = asyncio.current_task()
        presentation_closed_at: float | None = None

        def on_presentation_opened(identity: PresentationIdentity) -> None:
            if prepared is not None:
                pipeline.mark_presenting(
                    slot_id=prepared.slot.slot_id,
                    presentation_action_id=identity.action_id,
                    presentation_id=identity.presentation_id,
                )
            if next_player_id is None:
                if pre_exile_launch is not None:
                    self._launch_pre_exile_pipeline(
                        launch=pre_exile_launch,
                        identity=identity,
                        phase_state=state.phase_state,
                        speech_round=speech_round,
                        speech_order=speech_order,
                        broadcaster=broadcaster,
                    )
            else:
                self._launch_day_speech_prefetch(
                    launch=launch,
                    task_group=task_group,
                    parent_task=current_task,
                    identity=identity,
                    phase_state=state.phase_state,
                    next_player_id=next_player_id,
                    next_turn_index=next_turn_index,
                    speech_round=speech_round,
                    speech_order=speech_order,
                    broadcaster=broadcaster,
                )

        def on_presentation_closed(_identity: PresentationIdentity) -> None:
            nonlocal presentation_closed_at
            presentation_closed_at = asyncio.get_running_loop().time()
            if pre_exile_launch is not None:
                pre_exile_launch.presentation_closed.set()

        action_result: ActionResult | None = None
        body_error: BaseException | None = None
        try:
            async with asyncio.TaskGroup() as task_group:
                try:
                    candidate_result = await self._player_action(
                        game_id=state.game_id,
                        player=player,
                        broadcaster=broadcaster,
                        action_type="day_debate_speech",
                        objective="发表本轮白天讨论发言。",
                        candidates=[],
                        target_optional=None,
                        output_kind="public_speech",
                        extra_context={
                            "speech_round": speech_round,
                            "speech_order": speech_order,
                        },
                        precomputed_decision=(prepared.decision if prepared is not None else None),
                        on_presentation_opened=on_presentation_opened,
                        on_presentation_closed=on_presentation_closed,
                        pipeline_slot_id=(prepared.slot.slot_id if prepared is not None else None),
                        pipeline_stage=("presentation" if prepared is not None else None),
                        isolated_failure=prepared is not None,
                        allow_failure=prepared is not None,
                        return_result=True,
                    )
                    if not isinstance(candidate_result, ActionResult):
                        body_error = DayRuntimeError("day_debate_speech_failed")
                    else:
                        action_result = candidate_result
                        if action_result.failure is not None:
                            if (
                                prepared is not None
                                and action_result.terminal_event_record_seq is not None
                            ):
                                pipeline.mark_failed(
                                    slot_id=prepared.slot.slot_id,
                                    failure_record_seq=(action_result.terminal_event_record_seq),
                                )
                            body_error = DayRuntimeError(
                                "day_debate_speech_pipeline_presentation_failed"
                            )
                        elif action_result.decision is None:
                            body_error = DayRuntimeError("day_debate_speech_failed")
                        elif prepared is not None:
                            pipeline.mark_consumed(slot_id=prepared.slot.slot_id)
                except BaseException as exc:
                    body_error = exc
                if body_error is not None and launch.task is not None:
                    launch.task.cancel()
                elif launch.task is not None:
                    await self._await_day_speech_prefetch_after_close(
                        state=state,
                        launch=launch,
                        presentation_closed_at=presentation_closed_at,
                    )
            if launch.fatal is not None:
                raise launch.fatal
            if body_error is not None:
                raise body_error
        except asyncio.CancelledError:
            if pre_exile_launch is not None:
                await self._abort_pre_exile_launch(
                    pre_exile_launch,
                    reason_code="predecessor_presentation_canceled",
                )
            if prepared is not None:
                self._cancel_day_speech_slot(
                    prepared.slot.slot_id,
                    reason_code="prefetched_presentation_canceled",
                )
            if launch.slot is not None:
                self._cancel_day_speech_slot(
                    launch.slot.slot_id,
                    reason_code="prefetch_parent_canceled",
                )
            if launch.fatal is not None:
                raise launch.fatal
            raise
        except BaseException:
            if pre_exile_launch is not None:
                await self._abort_pre_exile_launch(
                    pre_exile_launch,
                    reason_code="predecessor_presentation_failed",
                )
            if prepared is not None:
                self._cancel_day_speech_slot(
                    prepared.slot.slot_id,
                    reason_code="prefetched_presentation_failed",
                )
            if launch.slot is not None:
                self._cancel_day_speech_slot(
                    launch.slot.slot_id,
                    reason_code="prefetch_predecessor_failed",
                )
            raise

        if action_result is None or action_result.decision is None:
            raise DayRuntimeError("day_debate_speech_failed")
        return action_result.decision, launch.outcome

    async def _await_day_speech_prefetch_after_close(
        self,
        *,
        state: MatchSnapshot,
        launch: _DaySpeechPrefetchLaunch,
        presentation_closed_at: float | None,
    ) -> None:
        pipeline = self._day_speech_pipeline
        if pipeline is None or launch.task is None:
            return
        contract = state.day_speech_pipeline_contract
        if contract.post_predecessor_close_wait_mode == "await_same_inflight_to_terminal":
            await launch.task
            return
        grace_ms = contract.post_predecessor_close_grace_ms
        if grace_ms is None:
            return
        loop = asyncio.get_running_loop()
        closed_at = presentation_closed_at or loop.time()
        remaining_seconds = max(
            0.0,
            closed_at + (grace_ms / 1000) - loop.time(),
        )
        try:
            await asyncio.wait_for(
                asyncio.shield(launch.task),
                timeout=remaining_seconds,
            )
        except TimeoutError:
            cancel_requested = launch.task.cancel(_DAY_SPEECH_PREFETCH_POST_CLOSE_DEADLINE)
            try:
                await launch.task
            except asyncio.CancelledError:
                pass
            if launch.slot is None:
                return
            launch.slot = pipeline.get_slot(launch.slot.slot_id)
            if launch.slot.state == "ready":
                launch.outcome = _prepared_day_speech_from_slot(launch.slot)
            elif launch.slot.state == "failed" or (
                launch.slot.state == "canceled"
                and (launch.slot.failure or {}).get("reason_code")
                == _DAY_SPEECH_PREFETCH_POST_CLOSE_DEADLINE
            ):
                launch.outcome = _failed_day_speech_prefetch_from_slot(launch.slot)
            else:
                raise DayRuntimeError(
                    "day speech prefetch deadline did not durably terminate "
                    f"its slot (cancel_requested={cancel_requested})"
                )

    def _day_speech_prefetch_requires_technical_skip(
        self,
        state: MatchSnapshot,
        failed_prefetch: _FailedDaySpeechPrefetch,
    ) -> bool:
        contract = state.day_speech_pipeline_contract
        if contract.schema_version not in {2, 3}:
            return False
        failure = failed_prefetch.failure
        if (
            failure.code == "model_prefetch_capacity_unavailable"
            or failure.category == "admission_capacity"
        ):
            return False
        if (
            failure.category in contract.duplicate_foreground_fallback_forbidden_failure_categories
            or failure.code == "model_empty_stream"
            or failure.code == _DAY_SPEECH_PREFETCH_POST_CLOSE_DEADLINE
        ):
            return True
        return False

    async def _run_day_speech_technical_skip_turn(
        self,
        *,
        state: MatchSnapshot,
        player: MatchPlayer,
        failed_prefetch: _FailedDaySpeechPrefetch,
        next_player_id: str | None,
        next_turn_index: int,
        speech_round: int,
        speech_order: list[str],
        broadcaster: BroadcastPort,
        pre_exile_launch: _PreExileLaunch | None = None,
    ) -> tuple[ModelDecision, _DaySpeechPrefetchOutcome | None]:
        launch = _DaySpeechPrefetchLaunch()
        current_task = asyncio.current_task()
        presentation_closed_at: float | None = None

        def on_presentation_opened(identity: PresentationIdentity) -> None:
            if next_player_id is None:
                if pre_exile_launch is not None:
                    self._launch_pre_exile_pipeline(
                        launch=pre_exile_launch,
                        identity=identity,
                        phase_state=state.phase_state,
                        speech_round=speech_round,
                        speech_order=speech_order,
                        broadcaster=broadcaster,
                        predecessor_turn_player_id=player.player_id,
                    )
                return
            self._launch_day_speech_prefetch(
                launch=launch,
                task_group=task_group,
                parent_task=current_task,
                identity=identity,
                phase_state=state.phase_state,
                next_player_id=next_player_id,
                next_turn_index=next_turn_index,
                speech_round=speech_round,
                speech_order=speech_order,
                broadcaster=broadcaster,
                predecessor_turn_player_id=player.player_id,
            )

        def on_presentation_closed(_identity: PresentationIdentity) -> None:
            nonlocal presentation_closed_at
            presentation_closed_at = asyncio.get_running_loop().time()
            if pre_exile_launch is not None:
                pre_exile_launch.presentation_closed.set()

        decision: ModelDecision | None = None
        body_error: BaseException | None = None
        try:
            async with asyncio.TaskGroup() as task_group:
                try:
                    decision = await self._complete_day_speech_technical_skip(
                        state=state,
                        player=player,
                        failed_prefetch=failed_prefetch,
                        speech_round=speech_round,
                        speech_order=speech_order,
                        broadcaster=broadcaster,
                        on_presentation_opened=on_presentation_opened,
                        on_presentation_closed=on_presentation_closed,
                    )
                except BaseException as exc:
                    body_error = exc
                if body_error is not None and launch.task is not None:
                    launch.task.cancel()
                elif launch.task is not None:
                    await self._await_day_speech_prefetch_after_close(
                        state=state,
                        launch=launch,
                        presentation_closed_at=presentation_closed_at,
                    )
            if launch.fatal is not None:
                raise launch.fatal
            if body_error is not None:
                raise body_error
        except asyncio.CancelledError:
            if pre_exile_launch is not None:
                await self._abort_pre_exile_launch(
                    pre_exile_launch,
                    reason_code="technical_skip_presentation_canceled",
                )
            if launch.slot is not None:
                self._cancel_day_speech_slot(
                    launch.slot.slot_id,
                    reason_code="technical_skip_prefetch_parent_canceled",
                )
            if launch.fatal is not None:
                raise launch.fatal
            raise
        except BaseException:
            if pre_exile_launch is not None:
                await self._abort_pre_exile_launch(
                    pre_exile_launch,
                    reason_code="technical_skip_presentation_failed",
                )
            if launch.slot is not None:
                self._cancel_day_speech_slot(
                    launch.slot.slot_id,
                    reason_code="technical_skip_cue_failed",
                )
            raise
        if decision is None:
            raise DayRuntimeError("pipeline technical skip did not complete")
        return decision, launch.outcome

    async def _complete_day_speech_technical_skip(
        self,
        *,
        state: MatchSnapshot,
        player: MatchPlayer,
        failed_prefetch: _FailedDaySpeechPrefetch,
        speech_round: int,
        speech_order: list[str],
        broadcaster: BroadcastPort,
        on_presentation_opened: Callable[[PresentationIdentity], None] | None = None,
        on_presentation_closed: Callable[[PresentationIdentity], None] | None = None,
    ) -> ModelDecision:
        complete = getattr(
            self._actions,
            "complete_pipeline_speech_technical_skip",
            None,
        )
        if not callable(complete):
            raise DayRuntimeError("pipeline technical skip is unsupported")
        if (
            failed_prefetch.source_action_id is None
            or failed_prefetch.terminal_event_record_seq is None
        ):
            raise DayRuntimeError("pipeline technical skip has incomplete source lineage")
        result = await complete(
            game_id=state.game_id,
            broadcaster=broadcaster,
            player_id=player.player_id,
            player_seat=player.seat,
            action_type="day_debate_speech",
            phase_id=state.phase_id,
            required_phase_state=state.phase_state,
            round_no=state.round_no,
            speech_round=speech_round,
            speech_order=speech_order,
            source_slot_id=failed_prefetch.slot.slot_id,
            source_action_id=failed_prefetch.source_action_id,
            source_failure=failed_prefetch.failure,
            source_terminal_event_record_seq=(failed_prefetch.terminal_event_record_seq),
            on_presentation_opened=on_presentation_opened,
            on_presentation_closed=on_presentation_closed,
        )
        if not isinstance(result, ActionResult) or result.failure is not None:
            raise DayRuntimeError("pipeline technical skip cue did not complete")
        return ModelDecision(
            target_player_id=None,
            speech=None,
            provider_request_id=(
                failed_prefetch.failure.terminal_attempt_id or failed_prefetch.source_action_id
            ),
            first_token_ms=0,
            completed_ms=0,
        )

    def _launch_day_speech_prefetch(
        self,
        *,
        launch: _DaySpeechPrefetchLaunch,
        task_group: asyncio.TaskGroup,
        parent_task: asyncio.Task[Any] | None,
        identity: PresentationIdentity,
        phase_state: str,
        next_player_id: str,
        next_turn_index: int,
        speech_round: int,
        speech_order: list[str],
        broadcaster: BroadcastPort,
        predecessor_turn_player_id: str | None = None,
    ) -> None:
        pipeline = self._day_speech_pipeline
        if pipeline is None:
            return
        try:
            if (
                type(identity.source_event_id) is not int
                or identity.source_event_id <= 0
                or type(identity.source_record_seq) is not int
                or identity.source_record_seq <= 0
            ):
                raise DayRuntimeError("day speech predecessor has no durable source lineage")
            frozen = self._repository.snapshot_for_day_speech_prefetch(
                game_id=identity.game_id,
                run_id=identity.run_id,
                phase_id=identity.phase_id,
                phase_state=phase_state,
                predecessor_presentation_id=identity.presentation_id,
                predecessor_action_id=identity.action_id,
                predecessor_source_event_id=identity.source_event_id,
                predecessor_turn_player_id=predecessor_turn_player_id,
            )
            if (
                not self._day_speech_pipeline_enabled(frozen.match_snapshot)
                or frozen.predecessor_source_record_seq != identity.source_record_seq
            ):
                raise DayRuntimeError("day speech prefetch contract or lineage changed")
            next_player = frozen.match_snapshot.player(next_player_id)
            if not next_player.alive:
                return
            slot = pipeline.reserve_slot(
                game_id=identity.game_id,
                phase_id=identity.phase_id,
                round_no=frozen.match_snapshot.round_no,
                speech_round=speech_round,
                turn_index=next_turn_index,
                actor_player_id=next_player.player_id,
                predecessor_action_id=identity.action_id,
                predecessor_presentation_id=identity.presentation_id,
                predecessor_source_event_id=identity.source_event_id,
                predecessor_source_record_seq=identity.source_record_seq,
                context_cutoff_record_seq=frozen.public_cutoff_record_seq,
                predecessor_turn_player_id=predecessor_turn_player_id,
            )
            launch.slot = slot
            if slot.state == "ready":
                launch.outcome = _prepared_day_speech_from_slot(slot)
                return
            if slot.state == "failed" or (
                slot.state == "canceled"
                and (slot.failure or {}).get("reason_code")
                == _DAY_SPEECH_PREFETCH_POST_CLOSE_DEADLINE
            ):
                launch.outcome = _failed_day_speech_prefetch_from_slot(slot)
                return
            if slot.state != "reserved":
                self._cancel_day_speech_slot(
                    slot.slot_id,
                    reason_code="prefetch_slot_not_resumable",
                )
                return
            slot = pipeline.mark_generating(slot_id=slot.slot_id)
            launch.slot = slot

            async def generate_guarded() -> None:
                try:
                    launch.outcome = await self._generate_prefetched_day_speech(
                        frozen_state=frozen.match_snapshot,
                        player=next_player,
                        slot=slot,
                        speech_round=speech_round,
                        speech_order=speech_order,
                        broadcaster=broadcaster,
                    )
                except asyncio.CancelledError:
                    raise
                except ExecutionOwnershipLost as exc:
                    launch.fatal = exc
                    if parent_task is not None and not parent_task.done():
                        parent_task.cancel()

            launch.task = task_group.create_task(generate_guarded())
        except (asyncio.CancelledError, ExecutionOwnershipLost):
            if launch.slot is not None:
                self._cancel_day_speech_slot(
                    launch.slot.slot_id,
                    reason_code="prefetch_preparation_interrupted",
                )
            raise
        except Exception:
            logger.exception(
                "Live V2 day speech prefetch preparation failed; using foreground fallback",
                extra={
                    "game_id": identity.game_id,
                    "run_id": identity.run_id,
                    "phase_id": identity.phase_id,
                    "predecessor_action_id": identity.action_id,
                    "next_player_id": next_player_id,
                    "speech_round": speech_round,
                    "turn_index": next_turn_index,
                },
            )
            if launch.slot is not None:
                self._cancel_day_speech_slot(
                    launch.slot.slot_id,
                    reason_code="prefetch_preparation_failed",
                )

    async def _generate_prefetched_day_speech(
        self,
        *,
        frozen_state: MatchSnapshot,
        player: MatchPlayer,
        slot: DaySpeechSlotSnapshot,
        speech_round: int,
        speech_order: list[str],
        broadcaster: BroadcastPort,
    ) -> _DaySpeechPrefetchOutcome | None:
        pipeline = self._day_speech_pipeline
        if pipeline is None:
            return None
        contract = frozen_state.day_speech_pipeline_contract
        guarded_empty_stream_retry = contract.early_transport_hidden_retry_max_retries == 1
        model_retry_guard: Callable[[ModelError, int], bool] | None = None
        if guarded_empty_stream_retry:

            def predecessor_is_still_active(
                _exc: ModelError,
                _attempt_no: int,
            ) -> bool:
                return pipeline.predecessor_is_active(slot.slot_id)

            model_retry_guard = predecessor_is_still_active
        try:
            action_result = await self._player_action(
                game_id=frozen_state.game_id,
                player=player,
                broadcaster=broadcaster,
                action_type="day_debate_speech",
                objective="发表本轮白天讨论发言。",
                candidates=[],
                target_optional=None,
                output_kind="public_speech",
                audience="player_private",
                extra_context={
                    "speech_round": speech_round,
                    "speech_order": speech_order,
                    "public_cutoff_record_seq": frozen_state.last_record_seq,
                },
                frozen_state=frozen_state,
                projection_at_seq=frozen_state.last_record_seq,
                defer_presentation=True,
                isolated_failure=True,
                allow_failure=True,
                batch_id=slot.slot_id,
                model_admission_mode="idle_only",
                pipeline_slot_id=slot.slot_id,
                pipeline_stage="generation",
                pipeline_empty_stream_max_attempts=(
                    1 + contract.early_transport_hidden_retry_max_retries
                ),
                pipeline_retry_mode=(
                    "empty_stream_once_while_predecessor_active"
                    if guarded_empty_stream_retry
                    else "disabled"
                ),
                model_retry_guard=model_retry_guard,
                return_result=True,
            )
            if not isinstance(action_result, ActionResult):
                self._cancel_day_speech_slot(
                    slot.slot_id,
                    reason_code="prefetch_generation_not_claimed",
                )
                return None
            if action_result.failure is not None:
                if action_result.terminal_event_record_seq is None:
                    self._cancel_day_speech_slot(
                        slot.slot_id,
                        reason_code="prefetch_failure_lineage_missing",
                    )
                    return None
                failed_slot = pipeline.mark_failed(
                    slot_id=slot.slot_id,
                    failure_record_seq=action_result.terminal_event_record_seq,
                )
                return _FailedDaySpeechPrefetch(
                    slot=failed_slot,
                    source_action_id=action_result.action_id,
                    failure=action_result.failure,
                    terminal_event_record_seq=action_result.terminal_event_record_seq,
                )
            if (
                action_result.action_id is None
                or action_result.decision is None
                or not action_result.decision.speech
                or action_result.model_response_record_seq is None
            ):
                self._cancel_day_speech_slot(
                    slot.slot_id,
                    reason_code="prefetch_generation_lineage_incomplete",
                )
                return None
            ready = pipeline.mark_ready(
                slot_id=slot.slot_id,
                generation_action_id=action_result.action_id,
                generation_response_record_seq=action_result.model_response_record_seq,
            )
            return _PreparedDaySpeech(slot=ready, decision=action_result.decision)
        except asyncio.CancelledError as exc:
            cancellation_reason = (
                exc.args[0]
                if exc.args and exc.args[0] == _DAY_SPEECH_PREFETCH_POST_CLOSE_DEADLINE
                else "prefetch_generation_canceled"
            )
            self._cancel_day_speech_slot(
                slot.slot_id,
                reason_code=cancellation_reason,
            )
            raise
        except ExecutionOwnershipLost:
            self._cancel_day_speech_slot(
                slot.slot_id,
                reason_code="prefetch_generation_ownership_lost",
            )
            raise
        except Exception:
            logger.exception(
                "Live V2 day speech prefetch generation failed; using foreground fallback",
                extra={
                    "game_id": frozen_state.game_id,
                    "run_id": frozen_state.run_id,
                    "slot_id": slot.slot_id,
                    "player_id": player.player_id,
                    "speech_round": speech_round,
                },
            )
            self._cancel_day_speech_slot(
                slot.slot_id,
                reason_code="prefetch_generation_failed",
            )
            return None

    def _cancel_day_speech_slot(self, slot_id: str, *, reason_code: str) -> None:
        pipeline = self._day_speech_pipeline
        if pipeline is None:
            return
        try:
            slot = pipeline.get_slot(slot_id)
            if slot.state in {"consumed", "failed", "canceled", "invalidated"}:
                return
            pipeline.cancel_slot(slot_id=slot_id, reason_code=reason_code)
        except Exception:
            logger.exception(
                "Live V2 day speech slot cleanup failed",
                extra={"slot_id": slot_id, "reason_code": reason_code},
            )

    async def _speech_order(
        self,
        *,
        state: MatchSnapshot,
        broadcaster: BroadcastPort,
    ) -> list[str]:
        self._actions.check_cancellation(state.game_id)
        alive = sorted((item for item in state.players if item.alive), key=lambda item: item.seat)
        if (
            str(state.rule.get("speech_policy") or "sequential") != "sheriff_directed"
            or state.sheriff_player_id is None
            or state.sheriff_player_id not in {item.player_id for item in alive}
            or len(alive) < 2
        ):
            return [item.player_id for item in alive]
        sheriff_index = next(
            index for index, item in enumerate(alive) if item.player_id == state.sheriff_player_id
        )
        left = alive[(sheriff_index - 1) % len(alive)]
        right = alive[(sheriff_index + 1) % len(alive)]
        sheriff = alive[sheriff_index]
        candidates = [left] if left.player_id == right.player_id else [left, right]
        options = [
            {
                "target_player_id": candidate.player_id,
                "resulting_speech_order": speech_order_from_start(
                    alive,
                    sheriff.player_id,
                    candidate.player_id,
                ),
                "sheriff_position": len(alive),
            }
            for candidate in candidates
        ]
        option_by_start = {str(option["target_player_id"]): option for option in options}
        if not is_supported_model_context_contract(state.model_context_contract):
            raise DayRuntimeError("unsupported_model_context_contract")
        decision = await self._player_action(
            game_id=state.game_id,
            player=sheriff,
            broadcaster=broadcaster,
            action_type="sheriff_speech_order",
            objective="根据每个候选对应的完整发言顺序，选择本轮起始发言者。",
            candidates=candidates,
            target_optional=False,
            output_kind="public_decision",
            decision_contract=DecisionContract(
                kind="target",
                target_mode="required",
                speech_mode="forbidden",
                decision_note_mode="optional",
                decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
            ),
            extra_context={
                "v11_action_extension": {
                    "mechanical_effect": {
                        "action_type": "sheriff_speech_order",
                        "target_mode": "required",
                        "selected_target_becomes_first_speaker": True,
                        "sheriff_speaks_last": True,
                        "options": options,
                        "speech_has_gameplay_effect": False,
                    }
                }
            },
        )
        start = decision.target_player_id
        selected_option = option_by_start.get(str(start))
        if selected_option is None:
            raise DayRuntimeError("sheriff_speech_order_invalid_start")
        result = selected_option["resulting_speech_order"]
        assert isinstance(result, list)
        self._repository.record_private_action_decision(
            game_id=state.game_id,
            player_id=sheriff.player_id,
            round_no=state.round_no,
            action_type="sheriff_speech_order",
            decision={"target_player_id": start},
            decision_note=decision.decision_note,
            context={"speech_order": result},
        )
        self._repository.append_event(
            game_id=state.game_id,
            event_type="day_speech_order_selected",
            audience="all",
            payload={"round_no": state.round_no, "order": result},
        )
        return result

    async def _run_exile_vote(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        pre_exile_pipeline_id: str | None = None,
        pre_exile_run_fence: Any | None = None,
        frozen_state: MatchSnapshot | None = None,
        frozen_private_facts_by_voter: dict[str, list[dict[str, Any]]] | None = None,
        initial_results_by_voter: dict[str, ActionResult] | None = None,
        public_history_cutoff_record_seq: int | None = None,
    ) -> ExileResult | None:
        self._actions.check_cancellation(game_id)
        state = frozen_state or self._repository.snapshot(game_id)
        alive = [item for item in state.players if item.alive]
        voters = [item for item in alive if item.state.get("can_vote", True)]
        votes = await self._collect_votes(
            game_id=game_id,
            broadcaster=broadcaster,
            action_type="exile_vote",
            voters=voters,
            candidates=alive,
            weighted=True,
            context={"vote_round": 1},
            pre_exile_pipeline_id=pre_exile_pipeline_id,
            pre_exile_run_fence=pre_exile_run_fence,
            frozen_state=frozen_state,
            frozen_private_facts_by_voter=frozen_private_facts_by_voter,
            initial_results_by_voter=initial_results_by_voter,
            public_history_cutoff_record_seq=public_history_cutoff_record_seq,
        )
        leaders = _leaders(votes)
        if len(leaders) != 1:
            tied = [item for item in alive if item.player_id in set(leaders)]
            if not tied:
                await self._announce_no_exile(
                    state=state,
                    broadcaster=broadcaster,
                    reason="no_valid_votes",
                )
                return None
            for candidate in tied:
                self._actions.check_cancellation(game_id)
                decision = await self._player_action(
                    game_id=game_id,
                    player=candidate,
                    broadcaster=broadcaster,
                    action_type="exile_pk_speech",
                    objective=_EXILE_PK_SPEECH_OBJECTIVE,
                    candidates=[],
                    target_optional=None,
                    output_kind="public_speech",
                )
                self._record_speech(state, candidate, decision, "exile_pk")
            runoff_voters = [item for item in voters if item.player_id not in set(leaders)]
            runoff = await self._collect_votes(
                game_id=game_id,
                broadcaster=broadcaster,
                action_type="exile_runoff_vote",
                voters=runoff_voters,
                candidates=tied,
                weighted=True,
                context={"vote_round": 2, "pk_candidate_ids": leaders},
            )
            leaders = _leaders(runoff)
            if len(leaders) != 1:
                await self._announce_no_exile(
                    state=state,
                    broadcaster=broadcaster,
                    reason="exile_runoff_tie",
                )
                return None

        self._actions.check_cancellation(game_id)
        target = state.player(leaders[0])
        result = self._repository.resolve_exile(game_id=game_id, player_id=target.player_id)
        objective = (
            f"宣布{target.seat}号被投票放逐后翻开白痴身份并免于出局"
            if result.outcome == "idiot_revealed"
            else f"宣布{target.seat}号被投票放逐出局，不公开其身份"
        )
        current = self._repository.snapshot(game_id)
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_exile_result",
            objective=objective,
            success_phase_state=current.phase_state,
            context={
                "player_id": target.player_id,
                "player_seat": target.seat,
                "outcome": result.outcome,
            },
        ):
            raise DayRuntimeError("judge_exile_result_failed")
        if result.outcome == "eliminated":
            await self._broadcast_death(
                state=current,
                player_id=target.player_id,
                cause="exile",
                broadcaster=broadcaster,
            )
        return result

    async def _resolve_exile_aftermath(
        self,
        *,
        game_id: str,
        exile: ExileResult,
        broadcaster: BroadcastPort,
    ) -> None:
        self._actions.check_cancellation(game_id)
        if exile.outcome != "eliminated":
            return
        state = self._repository.snapshot(game_id)
        actions = set(state.rule.get("day_actions") or [])
        if (
            exile.winner_after_exile is None
            and bool(state.rule.get("exile_last_words_enabled"))
            and "exile_last_words" in actions
        ):
            player = state.player(exile.player_id)
            decision = await self._player_action(
                game_id=game_id,
                player=player,
                broadcaster=broadcaster,
                action_type="exile_last_words",
                objective="发表被放逐后的遗言。",
                candidates=[],
                target_optional=None,
                output_kind="public_speech",
            )
            self._record_speech(state, player, decision, "exile_last_words")
        await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)

    async def _resolve_death_aftermath(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> None:
        self._actions.check_cancellation(game_id)
        resolved_hunters: set[str] = set()
        while pending_hunters := tuple(
            hunter_id
            for hunter_id in self._repository.pending_hunters(game_id)
            if hunter_id not in resolved_hunters
        ):
            if self._repository.current_winner(
                game_id
            ) is not None and not self._repository.hunter_settlement_can_change_winner(game_id):
                break
            self._actions.check_cancellation(game_id)
            hunter_id = pending_hunters[0]
            resolved_hunters.add(hunter_id)
            state = self._repository.snapshot(game_id)
            hunter = state.player(hunter_id)
            candidates = [
                item for item in state.players if item.alive and item.player_id != hunter_id
            ]
            decision = await self._player_action(
                game_id=game_id,
                player=hunter,
                broadcaster=broadcaster,
                action_type="hunter_death_shot",
                objective="决定是否发动猎人技能；发动时选择目标。",
                candidates=candidates,
                target_optional=True,
                output_kind="private_decision",
                decision_contract=DecisionContract(
                    kind="target",
                    target_mode="optional",
                    speech_mode="forbidden",
                    decision_note_mode="optional",
                    decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
                ),
                audience="god_view",
            )
            self._repository.apply_hunter_shot(
                game_id=game_id,
                hunter_id=hunter_id,
                target_player_id=decision.target_player_id,
            )
            if decision.target_player_id is not None:
                target = state.player(decision.target_player_id)
                current = self._repository.snapshot(game_id)
                if not await self._judge(
                    state=current,
                    broadcaster=broadcaster,
                    action_type="judge_hunter_shot_announcement",
                    objective=f"宣布猎人开枪带走了{target.seat}号，不公开其他身份",
                    success_phase_state=current.phase_state,
                    context={
                        "target_player_id": target.player_id,
                        "target_player_seat": target.seat,
                    },
                ):
                    raise DayRuntimeError("hunter_announcement_failed")
                await self._broadcast_death(
                    state=current,
                    player_id=target.player_id,
                    cause="hunter_shot",
                    broadcaster=broadcaster,
                )
        if self._repository.current_winner(game_id) is not None:
            return
        await self._resolve_dead_sheriff(game_id=game_id, broadcaster=broadcaster)

    async def _resolve_dead_sheriff(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> None:
        self._actions.check_cancellation(game_id)
        state = self._repository.snapshot(game_id)
        sheriff_id = state.sheriff_player_id
        if sheriff_id is None or state.player(sheriff_id).alive:
            return
        sheriff = state.player(sheriff_id)
        candidates = [item for item in state.players if item.alive]
        decision = await self._player_action(
            game_id=game_id,
            player=sheriff,
            broadcaster=broadcaster,
            action_type="sheriff_badge_resolution",
            objective="决定移交警徽给谁，或撕毁警徽。",
            candidates=candidates,
            target_optional=True,
            output_kind="public_death_reaction",
            decision_contract=DecisionContract(
                kind="target",
                target_mode="optional",
                speech_mode="forbidden",
                decision_note_mode="optional",
                decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
            ),
        )
        target_id = decision.target_player_id
        self._repository.set_sheriff(
            game_id=game_id,
            player_id=target_id,
            reason="dead_sheriff_badge_resolution",
        )
        current = self._repository.snapshot(game_id)
        objective = (
            "宣布警长撕毁警徽，本局不再有警长"
            if target_id is None
            else f"宣布警徽移交给{current.player(target_id).seat}号"
        )
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_sheriff_badge_result",
            objective=objective,
            success_phase_state=current.phase_state,
            context={
                "from_player_id": sheriff_id,
                "to_player_id": target_id,
                "target_player_seat": (
                    current.player(target_id).seat if target_id is not None else None
                ),
            },
        ):
            raise DayRuntimeError("sheriff_badge_announcement_failed")
        await self._broadcast_match_state(current, broadcaster)

    async def _collect_votes(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        action_type: str,
        voters: list[MatchPlayer],
        candidates: list[MatchPlayer],
        weighted: bool,
        context: dict[str, Any],
        pre_exile_pipeline_id: str | None = None,
        pre_exile_run_fence: Any | None = None,
        frozen_state: MatchSnapshot | None = None,
        frozen_private_facts_by_voter: dict[str, list[dict[str, Any]]] | None = None,
        initial_results_by_voter: dict[str, ActionResult] | None = None,
        public_history_cutoff_record_seq: int | None = None,
    ) -> dict[str, float]:
        self._actions.check_cancellation(game_id)
        totals: dict[str, float] = defaultdict(float)
        state = frozen_state or self._repository.snapshot(game_id)
        public_cutoff_record_seq = (
            public_history_cutoff_record_seq
            if public_history_cutoff_record_seq is not None
            else state.last_record_seq
        )
        if public_cutoff_record_seq != state.last_record_seq:
            raise DayRuntimeError("day_vote_frozen_public_cutoff_mismatch")
        batch_id = f"{state.phase_id}:{action_type}:{public_cutoff_record_seq}:vote"
        prepared: list[tuple[MatchPlayer, list[MatchPlayer]]] = []
        for voter in sorted(voters, key=lambda item: item.seat):
            eligible = [item for item in candidates if item.player_id != voter.player_id]
            if eligible:
                prepared.append((voter, eligible))
        decision_family_ids = [
            _vote_decision_family_id(
                batch_id=batch_id,
                action_type=action_type,
                voter=voter,
                candidates=eligible,
                projection_at_seq=public_cutoff_record_seq,
                model_context_contract=state.model_context_contract,
            )
            for voter, eligible in prepared
        ]
        machine_format_failure_counts = [0 for _item in prepared]
        output_budget_failure_counts = [0 for _item in prepared]
        latest_machine_format_failure_results: list[ActionResult | None] = [
            None for _item in prepared
        ]
        latest_output_budget_failure_results: list[ActionResult | None] = [
            None for _item in prepared
        ]
        machine_format_failure_episode_ids_by_voter: list[list[str]] = [[] for _item in prepared]
        output_budget_failure_episode_ids_by_voter: list[list[str]] = [[] for _item in prepared]
        technical_abstain_reasons: list[str | None] = [None for _item in prepared]
        technical_abstain_results: list[ActionResult | None] = [None for _item in prepared]
        degraded_abstain_lineage: dict[int, dict[str, Any]] = {}
        pre_exile_vote_rows: dict[str, Any] = {}
        if pre_exile_pipeline_id is not None:
            if self._pre_exile_pipeline is None or initial_results_by_voter is None:
                raise DayRuntimeError("pre_exile_vote_recovery_context_missing")
            pre_exile_vote_rows = {
                row.actor_player_id: row
                for row in self._pre_exile_pipeline.list_results(pre_exile_pipeline_id)
                if row.result_kind == "exile_vote"
            }
            if set(pre_exile_vote_rows) != {voter.player_id for voter, _eligible in prepared}:
                raise DayRuntimeError("pre_exile_vote_durable_result_set_changed")

        async def request_vote(
            index: int,
            voter: MatchPlayer,
            eligible: list[MatchPlayer],
            *,
            stage: Literal[
                "concurrent_initial",
                "concurrent_recovery",
                "sequential_recovery",
            ],
            preflight_pause_failure: PreflightPauseFailure | None = None,
            pre_exile_recovery: dict[str, Any] | None = None,
            pause_on_model_failure: bool = False,
        ) -> ActionResult:
            isolated = stage != "sequential_recovery"
            result = await self._player_action(
                game_id=game_id,
                player=voter,
                broadcaster=broadcaster,
                action_type=action_type,
                objective="投票选择一名合法候选人。",
                candidates=eligible,
                target_optional=False,
                output_kind="private_vote",
                decision_contract=DecisionContract(
                    kind="target",
                    target_mode="required",
                    speech_mode="forbidden",
                    decision_note_mode="optional",
                    decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
                ),
                audience="god_view",
                extra_context={
                    **context,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                    **(
                        {"public_history_cutoff_record_seq": (public_cutoff_record_seq)}
                        if frozen_state is not None
                        else {}
                    ),
                    "vote_batch_stage": stage,
                    **(
                        {"pre_exile_recovery": pre_exile_recovery}
                        if pre_exile_recovery is not None
                        else {}
                    ),
                },
                frozen_state=state,
                frozen_private_facts=(
                    frozen_private_facts_by_voter.get(voter.player_id)
                    if frozen_private_facts_by_voter is not None
                    else None
                ),
                projection_at_seq=(None if frozen_state is not None else public_cutoff_record_seq),
                defer_presentation=isolated,
                isolated_failure=isolated,
                pause_on_model_failure=pause_on_model_failure,
                allow_failure=isolated,
                batch_id=batch_id,
                decision_family_id=decision_family_ids[index],
                prior_machine_format_failures=machine_format_failure_counts[index],
                automatic_machine_format_budget=(_VOTE_MACHINE_FORMAT_AUTOMATIC_BUDGET),
                prior_output_budget_failures=output_budget_failure_counts[index],
                automatic_output_budget_budget=(_VOTE_OUTPUT_BUDGET_AUTOMATIC_BUDGET),
                preflight_pause_failure=preflight_pause_failure,
                target_exhaustion_outcome="technical_abstain",
                return_result=True,
            )
            if not isinstance(result, ActionResult):
                return ActionResult(decision=result)
            return result

        def observe_failure(index: int, result: ActionResult) -> None:
            failure = result.failure
            if failure is None:
                return
            if failure.machine_format_failure_count:
                machine_format_failure_counts[index] += failure.machine_format_failure_count
                latest_machine_format_failure_results[index] = result
                if (
                    failure.failure_episode_id is not None
                    and failure.failure_episode_id
                    not in machine_format_failure_episode_ids_by_voter[index]
                ):
                    machine_format_failure_episode_ids_by_voter[index].append(
                        failure.failure_episode_id
                    )
            if failure.output_budget_failure_count:
                output_budget_failure_counts[index] += failure.output_budget_failure_count
                latest_output_budget_failure_results[index] = result
                if (
                    failure.failure_episode_id is not None
                    and failure.failure_episode_id
                    not in output_budget_failure_episode_ids_by_voter[index]
                ):
                    output_budget_failure_episode_ids_by_voter[index].append(
                        failure.failure_episode_id
                    )

        def observe_technical_outcome(index: int, result: ActionResult) -> bool:
            outcome = result.technical_outcome
            if outcome is None:
                return False
            if (
                outcome.kind != "technical_abstain"
                or result.decision is not None
                or result.action_id is None
                or not outcome.failure.code
                or not outcome.failure.failure_episode_id
            ):
                raise DayRuntimeError("day_vote_technical_outcome_invalid")
            technical_abstain_reasons[index] = outcome.failure.code
            technical_abstain_results[index] = result
            return True

        # All non-blocking attempts use the same frozen public cutoff. Initial
        # failures receive one more isolated concurrent attempt; only voters
        # still missing after that enter the blocking path one at a time. This
        # preserves durable pause/operator-retry semantics without publishing
        # a partial tally.
        if initial_results_by_voter is None:
            initial_results = list(
                await asyncio.gather(
                    *(
                        request_vote(index, voter, eligible, stage="concurrent_initial")
                        for index, (voter, eligible) in enumerate(prepared)
                    )
                )
            )
        else:
            missing_voter_ids = [
                voter.player_id
                for voter, _eligible in prepared
                if voter.player_id not in initial_results_by_voter
            ]
            if missing_voter_ids:
                raise DayRuntimeError(
                    "pre_exile_vote_results_incomplete:" + ",".join(missing_voter_ids)
                )
            initial_results = [
                initial_results_by_voter[voter.player_id] for voter, _eligible in prepared
            ]
        for index, result in enumerate(initial_results):
            observe_failure(index, result)
            observe_technical_outcome(index, result)
        decisions = [result.decision for result in initial_results]
        failed_indexes = [
            index
            for index, decision in enumerate(decisions)
            if decision is None and technical_abstain_reasons[index] is None
        ]
        initial_failed_voter_ids = [prepared[index][0].player_id for index in failed_indexes]
        if failed_indexes and pre_exile_pipeline_id is not None:
            pipeline_repository = self._pre_exile_pipeline
            if pipeline_repository is None:
                raise DayRuntimeError("pre_exile_pipeline_repository_missing")

            def degrade_vote_to_abstain(
                index: int,
                *,
                source_action_id: str,
                recovery_action_id: str | None,
                failure_code: str,
                failure_category: str | None,
                failure_episode_id: str | None,
                degraded_from: str,
            ) -> None:
                voter = prepared[index][0]
                snapshot = pipeline_repository.record_vote_degraded_abstain(
                    pipeline_id=pre_exile_pipeline_id,
                    actor_player_id=voter.player_id,
                    source_action_id=source_action_id,
                    recovery_action_id=recovery_action_id,
                    failure_code=failure_code,
                    failure_category=failure_category,
                    failure_episode_id=failure_episode_id,
                    fence=pre_exile_run_fence,
                )
                self._repository.append_event(
                    game_id=game_id,
                    event_type="day_vote_degraded_to_abstain",
                    audience="god_view",
                    payload={
                        "round_no": state.round_no,
                        "action_type": action_type,
                        "batch_id": batch_id,
                        "public_cutoff_record_seq": public_cutoff_record_seq,
                        "voter_player_id": voter.player_id,
                        "source_action_id": source_action_id,
                        "recovery_action_id": recovery_action_id,
                        "failure_code": failure_code,
                        "degraded_from": degraded_from,
                    },
                )
                failure_meta = snapshot.failure if isinstance(snapshot.failure, dict) else {}
                technical = (
                    failure_meta.get("technical_outcome")
                    if isinstance(failure_meta.get("technical_outcome"), dict)
                    else {}
                )
                technical_abstain_reasons[index] = str(
                    technical.get("failure_code") or failure_code
                )
                degraded_abstain_lineage[index] = {
                    "source_action_id": source_action_id,
                    "supporting_event_record_seq": failure_meta.get(
                        "technical_outcome_record_seq"
                    ),
                    "failure_episode_id": technical.get("failure_episode_id"),
                }

            if (
                getattr(
                    state.pre_exile_pipeline_contract,
                    "speculative_vote_capacity_recovery_mode",
                    None,
                )
                != "normal_batch_after_close_once"
            ):
                raise DayRuntimeError("pre_exile_capacity_recovery_contract_unsupported")
            recovery_inputs: list[tuple[int, dict[str, Any]]] = []
            degraded_source_indexes: list[int] = []
            for index in failed_indexes:
                voter = prepared[index][0]
                row = pre_exile_vote_rows[voter.player_id]
                category = _persisted_pre_exile_failure_category(row.failure or {})
                if (
                    category not in RECOVERABLE_PRE_EXILE_VOTE_CATEGORIES
                    or not isinstance(row.action_id, str)
                    or not row.action_id
                ):
                    # A failure the sole recovery re-drive cannot touch must
                    # degrade to a durable abstain instead of killing the day.
                    degraded_source_indexes.append(index)
                    continue
                recovery_inputs.append(
                    (
                        index,
                        {
                            "pipeline_id": pre_exile_pipeline_id,
                            "result_id": row.result_id,
                            "source_action_id": row.action_id,
                            "model_admission_mode": "normal",
                        },
                    )
                )
            for index in degraded_source_indexes:
                voter = prepared[index][0]
                row = pre_exile_vote_rows[voter.player_id]
                failure = row.failure if isinstance(row.failure, dict) else {}
                action_payload = (
                    failure.get("action_failed")
                    if isinstance(failure.get("action_failed"), dict)
                    else {}
                )
                request_payload = (
                    failure.get("model_request_failed")
                    if isinstance(failure.get("model_request_failed"), dict)
                    else {}
                )
                degrade_vote_to_abstain(
                    index,
                    source_action_id=row.action_id,
                    recovery_action_id=row.recovery_action_id,
                    failure_code=str(
                        action_payload.get("failure_code")
                        or request_payload.get("failure_code")
                        or "model_failure_unrecoverable"
                    ),
                    failure_category=_persisted_pre_exile_failure_category(failure),
                    failure_episode_id=(
                        action_payload.get("failure_episode_id")
                        or request_payload.get("failure_episode_id")
                    ),
                    degraded_from="source_not_recoverable",
                )
            self._repository.append_event(
                game_id=game_id,
                event_type="day_vote_batch_recovery_started",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "action_type": action_type,
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                    "failed_voter_ids": initial_failed_voter_ids,
                    "recovery_mode": "pre_exile_idle_capacity_normal_once",
                },
            )
            recovery_results = list(
                await asyncio.gather(
                    *(
                        _staggered_vote_request(
                            slot,
                            request_vote,
                            index,
                            prepared[index][0],
                            prepared[index][1],
                            stage="concurrent_recovery",
                            pre_exile_recovery=recovery,
                            pause_on_model_failure=True,
                        )
                        for slot, (index, recovery) in enumerate(recovery_inputs)
                    )
                )
            )
            recovered_voter_ids: list[str] = []
            technical_voter_ids: list[str] = []
            degraded_recovery_voter_ids: list[str] = []
            for (index, _recovery), result in zip(
                recovery_inputs,
                recovery_results,
                strict=True,
            ):
                voter = prepared[index][0]
                source = pre_exile_vote_rows[voter.player_id]
                if result.action_id is None:
                    raise DayRuntimeError(
                        f"pre_exile_vote_recovery_action_missing:{voter.player_id}"
                    )
                if result.failure is not None:
                    if result.failure.category == "canceled":
                        self._actions.check_cancellation(game_id)
                    # The sole durable recovery re-drive failed (e.g. the
                    # provider stalled past the auto-retry).  Degrade this
                    # vote to a durable abstain; the batch must not die here.
                    degrade_vote_to_abstain(
                        index,
                        source_action_id=source.action_id,
                        recovery_action_id=result.action_id,
                        failure_code=result.failure.code,
                        failure_category=result.failure.category,
                        failure_episode_id=result.failure.failure_episode_id,
                        degraded_from="recovery_failed",
                    )
                    degraded_recovery_voter_ids.append(voter.player_id)
                    continue
                adopted = pipeline_repository.adopt_vote_recovery_result(
                    pipeline_id=pre_exile_pipeline_id,
                    actor_player_id=voter.player_id,
                    source_action_id=source.action_id,
                    recovery_action_id=result.action_id,
                    response_record_seq=result.model_response_record_seq,
                    terminal_record_seq=(
                        result.terminal_event_record_seq
                        if result.model_response_record_seq is not None
                        else None
                    ),
                    technical_outcome_record_seq=(
                        result.technical_outcome.supporting_event_record_seq
                        if result.technical_outcome is not None
                        else None
                    ),
                    fence=pre_exile_run_fence,
                )
                if adopted.action_id != source.action_id:
                    raise DayRuntimeError(
                        f"pre_exile_vote_recovery_source_changed:{voter.player_id}"
                    )
                decisions[index] = result.decision
                if observe_technical_outcome(index, result):
                    technical_voter_ids.append(voter.player_id)
                elif result.decision is None:
                    raise DayRuntimeError(
                        f"pre_exile_vote_recovery_result_missing:{voter.player_id}"
                    )
                else:
                    recovered_voter_ids.append(voter.player_id)
            recovery_payload: dict[str, Any] = {
                "round_no": state.round_no,
                "action_type": action_type,
                "batch_id": batch_id,
                "public_cutoff_record_seq": public_cutoff_record_seq,
                "recovered_voter_ids": recovered_voter_ids,
                "recovery_mode": "pre_exile_idle_capacity_normal_once",
            }
            if technical_voter_ids:
                recovery_payload["technical_abstained_voter_ids"] = technical_voter_ids
            if degraded_recovery_voter_ids:
                recovery_payload["degraded_abstained_voter_ids"] = degraded_recovery_voter_ids
            self._repository.append_event(
                game_id=game_id,
                event_type="day_vote_batch_recovery_completed",
                audience="god_view",
                payload=recovery_payload,
            )
            await broadcaster.broadcast_json(
                day_progress(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    round_no=state.round_no,
                    stage="before_exile_vote",
                    completed_count=len(prepared),
                    total_count=len(prepared),
                )
            )
            failed_indexes = []
        if failed_indexes:
            self._repository.append_event(
                game_id=game_id,
                event_type="day_vote_batch_recovery_started",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "action_type": action_type,
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                    "failed_voter_ids": initial_failed_voter_ids,
                },
            )

            concurrent_recovery_indexes = [
                index
                for index in failed_indexes
                if machine_format_failure_counts[index] < _VOTE_MACHINE_FORMAT_AUTOMATIC_BUDGET
                and output_budget_failure_counts[index] < _VOTE_OUTPUT_BUDGET_AUTOMATIC_BUDGET
            ]
            concurrent_recovery_index_set = set(concurrent_recovery_indexes)
            concurrent_recovery_results = list(
                await asyncio.gather(
                    *(
                        _staggered_vote_request(
                            slot,
                            request_vote,
                            index,
                            prepared[index][0],
                            prepared[index][1],
                            stage="concurrent_recovery",
                        )
                        for slot, index in enumerate(concurrent_recovery_indexes)
                    )
                )
            )
            still_failed_indexes: list[int] = [
                index for index in failed_indexes if index not in concurrent_recovery_index_set
            ]
            concurrent_recovered_voter_ids: list[str] = []
            concurrent_technical_abstained_voter_ids: list[str] = []
            for index, result in zip(
                concurrent_recovery_indexes,
                concurrent_recovery_results,
                strict=True,
            ):
                observe_failure(index, result)
                decisions[index] = result.decision
                if observe_technical_outcome(index, result):
                    concurrent_technical_abstained_voter_ids.append(prepared[index][0].player_id)
                elif result.decision is None:
                    still_failed_indexes.append(index)
                else:
                    concurrent_recovered_voter_ids.append(prepared[index][0].player_id)
            still_failed_indexes.sort()
            still_failed_voter_ids = [
                prepared[index][0].player_id for index in still_failed_indexes
            ]
            concurrent_recovery_payload = {
                "round_no": state.round_no,
                "action_type": action_type,
                "batch_id": batch_id,
                "public_cutoff_record_seq": public_cutoff_record_seq,
                "recovered_voter_ids": concurrent_recovered_voter_ids,
                "still_failed_voter_ids": still_failed_voter_ids,
            }
            if concurrent_technical_abstained_voter_ids:
                concurrent_recovery_payload["technical_abstained_voter_ids"] = (
                    concurrent_technical_abstained_voter_ids
                )
            self._repository.append_event(
                game_id=game_id,
                event_type="day_vote_batch_concurrent_recovery_completed",
                audience="god_view",
                payload=concurrent_recovery_payload,
            )

            for index in still_failed_indexes:
                self._actions.check_cancellation(game_id)
                voter, eligible = prepared[index]
                preflight_pause_failure = None
                if machine_format_failure_counts[index] >= (_VOTE_MACHINE_FORMAT_AUTOMATIC_BUDGET):
                    latest_failure_result = latest_machine_format_failure_results[index]
                    latest_failure = (
                        latest_failure_result.failure if latest_failure_result is not None else None
                    )
                    if (
                        latest_failure_result is None
                        or latest_failure is None
                        or latest_failure_result.action_id is None
                        or latest_failure.last_machine_format_attempt_id is None
                        or latest_failure.last_machine_format_failure_code is None
                        or not machine_format_failure_episode_ids_by_voter[index]
                    ):
                        raise DayRuntimeError("decision_family_retry_lineage_missing")
                    preflight_pause_failure = PreflightPauseFailure(
                        failure_code=(latest_failure.last_machine_format_failure_code),
                        failure_category="machine_format",
                        source_action_id=latest_failure_result.action_id,
                        source_attempt_id=(latest_failure.last_machine_format_attempt_id),
                        automatic_machine_format_attempt_count=(
                            machine_format_failure_counts[index]
                        ),
                        automatic_output_budget_attempt_count=(output_budget_failure_counts[index]),
                        source_failure_episode_ids=tuple(
                            machine_format_failure_episode_ids_by_voter[index]
                        ),
                    )
                elif output_budget_failure_counts[index] >= (_VOTE_OUTPUT_BUDGET_AUTOMATIC_BUDGET):
                    latest_failure_result = latest_output_budget_failure_results[index]
                    latest_failure = (
                        latest_failure_result.failure if latest_failure_result is not None else None
                    )
                    if (
                        latest_failure_result is None
                        or latest_failure is None
                        or latest_failure_result.action_id is None
                        or latest_failure.last_output_budget_attempt_id is None
                        or latest_failure.last_output_budget_failure_code is None
                        or not output_budget_failure_episode_ids_by_voter[index]
                    ):
                        raise DayRuntimeError("decision_family_retry_lineage_missing")
                    preflight_pause_failure = PreflightPauseFailure(
                        failure_code=(latest_failure.last_output_budget_failure_code),
                        failure_category="output_budget",
                        source_action_id=latest_failure_result.action_id,
                        source_attempt_id=(latest_failure.last_output_budget_attempt_id),
                        automatic_machine_format_attempt_count=(
                            machine_format_failure_counts[index]
                        ),
                        automatic_output_budget_attempt_count=(output_budget_failure_counts[index]),
                        source_failure_episode_ids=tuple(
                            output_budget_failure_episode_ids_by_voter[index]
                        ),
                    )
                result = await request_vote(
                    index,
                    voter,
                    eligible,
                    stage="sequential_recovery",
                    preflight_pause_failure=preflight_pause_failure,
                )
                decisions[index] = result.decision
                observe_failure(index, result)
                observe_technical_outcome(index, result)
            recovered_voter_ids = [
                prepared[index][0].player_id
                for index in failed_indexes
                if decisions[index] is not None
            ]
            recovery_technical_abstained_voter_ids = [
                prepared[index][0].player_id
                for index in failed_indexes
                if technical_abstain_reasons[index] is not None
            ]
            recovery_payload = {
                "round_no": state.round_no,
                "action_type": action_type,
                "batch_id": batch_id,
                "public_cutoff_record_seq": public_cutoff_record_seq,
                "recovered_voter_ids": recovered_voter_ids,
            }
            if recovery_technical_abstained_voter_ids:
                recovery_payload["technical_abstained_voter_ids"] = (
                    recovery_technical_abstained_voter_ids
                )
            self._repository.append_event(
                game_id=game_id,
                event_type="day_vote_batch_recovery_completed",
                audience="god_view",
                payload=recovery_payload,
            )

        committed: list[DayVoteCommit] = []
        for index, ((voter, eligible), decision) in enumerate(
            zip(prepared, decisions, strict=True)
        ):
            technical_reason = technical_abstain_reasons[index]
            if technical_reason is not None and index in degraded_abstain_lineage:
                lineage = degraded_abstain_lineage[index]
                committed.append(
                    DayVoteCommit(
                        voter_player_id=voter.player_id,
                        target_player_id=None,
                        weight=0.0,
                        decision_note=None,
                        technical_status="technical_abstain",
                        technical_reason=technical_reason,
                        source_action_id=lineage["source_action_id"],
                        supporting_event_record_seq=lineage["supporting_event_record_seq"],
                        failure_episode_id=lineage["failure_episode_id"],
                        failure_mode="model_failure_degraded",
                    )
                )
                continue
            if technical_reason is not None:
                technical_result = technical_abstain_results[index]
                technical_outcome = (
                    technical_result.technical_outcome if technical_result is not None else None
                )
                if (
                    decision is not None
                    or technical_result is None
                    or technical_result.action_id is None
                    or technical_outcome is None
                    or technical_outcome.failure.failure_episode_id is None
                ):
                    raise DayRuntimeError("day_vote_technical_outcome_invalid")
                committed.append(
                    DayVoteCommit(
                        voter_player_id=voter.player_id,
                        target_player_id=None,
                        weight=0.0,
                        decision_note=None,
                        technical_status="technical_abstain",
                        technical_reason=technical_reason,
                        source_action_id=technical_result.action_id,
                        supporting_event_record_seq=(technical_outcome.supporting_event_record_seq),
                        failure_episode_id=(technical_outcome.failure.failure_episode_id),
                        failure_mode=technical_outcome.failure_mode,
                    )
                )
                continue
            if decision is None:
                raise DayRuntimeError(f"{action_type}_vote_batch_incomplete")
            target_id = _required_target(decision)
            if target_id not in {candidate.player_id for candidate in eligible}:
                raise DayRuntimeError(f"{action_type}_vote_target_invalid")
            weight = (
                float(state.rule.get("sheriff_vote_weight") or 1)
                if weighted and voter.player_id == state.sheriff_player_id
                else 1.0
            )
            totals[target_id] += weight
            committed.append(
                DayVoteCommit(
                    voter_player_id=voter.player_id,
                    target_player_id=target_id,
                    weight=weight,
                    decision_note=decision.decision_note,
                )
            )

        # No vote is made public until every eligible virtual player has
        # completed the same voting batch.  This keeps later model contexts
        # independent from earlier choices while preserving the durable
        # per-voter audit records once the batch is complete. The repository
        # finalizes all public votes, private reasons, and the tally in one
        # transaction so no retry can observe or extend a partial batch.
        decision_context = {
            **context,
            "batch_id": batch_id,
            "public_cutoff_record_seq": public_cutoff_record_seq,
        }
        resolution_payload = {
            "round_no": state.round_no,
            "action_type": action_type,
            "batch_id": batch_id,
            "public_cutoff_record_seq": public_cutoff_record_seq,
            "eligible_voter_ids": [item.player_id for item in voters],
            "ineligible_voter_ids": [
                item.player_id
                for item in state.players
                if item.alive and item.player_id not in {voter.player_id for voter in voters}
            ],
            "candidate_player_ids": [item.player_id for item in candidates],
            "weighted": weighted,
            "sheriff_player_id": state.sheriff_player_id,
            "sheriff_vote_weight": (
                float(state.rule.get("sheriff_vote_weight") or 1)
                if weighted and state.sheriff_player_id is not None
                else None
            ),
            "voter_weights": {vote.voter_player_id: vote.weight for vote in committed},
            "totals": dict(totals),
            "leaders": _leaders(dict(totals)),
            "identity_reveal": "none",
        }
        technical_abstentions = [
            {
                "voter_player_id": vote.voter_player_id,
                "technical_status": vote.technical_status,
                "technical_reason": vote.technical_reason,
            }
            for vote in committed
            if vote.technical_status is not None
        ]
        if technical_abstentions:
            resolution_payload["technical_abstentions"] = technical_abstentions
        self._repository.finalize_day_vote_batch(
            game_id=game_id,
            phase_id=state.phase_id,
            phase_state=state.phase_state,
            round_no=state.round_no,
            action_type=action_type,
            batch_id=batch_id,
            public_cutoff_record_seq=public_cutoff_record_seq,
            expected_voter_ids=tuple(voter.player_id for voter, _eligible in prepared),
            votes=tuple(committed),
            decision_context=decision_context,
            resolution_payload=resolution_payload,
            pre_exile_pipeline_id=pre_exile_pipeline_id,
        )
        return dict(totals)

    async def _offer_pre_sheriff_explosion(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> bool:
        return await self._offer_all_wolves_explosion(
            game_id=game_id,
            broadcaster=broadcaster,
            stage="pre_sheriff_election",
            pre_sheriff=True,
        )

    async def _offer_all_wolves_explosion(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        stage: str,
        pre_sheriff: bool = False,
        public_window_context: dict[str, Any] | None = None,
    ) -> bool:
        self._actions.check_cancellation(game_id)
        state = self._repository.snapshot(game_id)
        if not bool(state.rule.get("werewolf_self_explosion_enabled")):
            return False
        wolves = sorted(
            (player for player in state.players if player.alive and player.role_key == "werewolf"),
            key=lambda player: player.seat,
        )
        if not wolves:
            return False
        action_effect = _self_explosion_action_effect(
            state=state,
            stage=stage,
            pre_sheriff=pre_sheriff,
        )
        public_cutoff_record_seq = state.last_record_seq
        batch_id = f"{state.phase_id}:{stage}:{public_cutoff_record_seq}:werewolf_self_explosion"

        async def request_decision(wolf: MatchPlayer) -> ModelDecision | None:
            return await self._player_action(
                game_id=game_id,
                player=wolf,
                broadcaster=broadcaster,
                action_type="werewolf_self_explosion",
                objective="决定是否立即自爆。",
                candidates=[],
                target_optional=None,
                audience="god_view",
                output_kind="private_decision",
                decision_contract=DecisionContract(
                    kind="boolean",
                    boolean_field="explode",
                    speech_mode="forbidden",
                    decision_note_mode="optional",
                    decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
                    true_meaning="立即自爆",
                    false_meaning="不自爆",
                ),
                extra_context={
                    "public_stage": stage,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                    "current_action_effect": action_effect,
                    "batch_resolution_policy": "lowest_seat_affirmative",
                    **(public_window_context or {}),
                },
                frozen_state=state,
                defer_presentation=True,
                isolated_failure=True,
                allow_failure=True,
                batch_id=batch_id,
            )

        decisions = await asyncio.gather(*(request_decision(wolf) for wolf in wolves))
        affirmative: list[MatchPlayer] = []
        failed_player_ids: list[str] = []
        for wolf, decision in zip(wolves, decisions, strict=True):
            if decision is not None and not isinstance(decision.boolean_value, bool):
                raise DayRuntimeError("werewolf_self_explosion_invalid_decision")
            if decision is None:
                failed_player_ids.append(wolf.player_id)
            elif decision.boolean_value:
                affirmative.append(wolf)

        selected = affirmative[0] if affirmative else None
        for wolf, decision in zip(wolves, decisions, strict=True):
            self._repository.append_event(
                game_id=game_id,
                event_type="werewolf_self_explosion_decided",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "player_id": wolf.player_id,
                    "stage": stage,
                    "exploded": bool(decision and decision.boolean_value),
                    "decision_status": "failed" if decision is None else "completed",
                    "selected_for_resolution": (
                        selected is not None and wolf.player_id == selected.player_id
                    ),
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                },
            )

        self._repository.append_event(
            game_id=game_id,
            event_type="werewolf_self_explosion_batch_resolved",
            audience="god_view",
            payload={
                "round_no": state.round_no,
                "stage": stage,
                "batch_id": batch_id,
                "public_cutoff_record_seq": public_cutoff_record_seq,
                "eligible_wolf_ids": [wolf.player_id for wolf in wolves],
                "failed_player_ids": failed_player_ids,
                "affirmative_player_ids": [wolf.player_id for wolf in affirmative],
                "selected_player_id": selected.player_id if selected is not None else None,
                "selection_policy": "lowest_seat_affirmative",
                "outcome": "self_explosion" if selected is not None else "continued",
            },
        )
        for wolf, decision in zip(wolves, decisions, strict=True):
            if decision is None or (selected is not None and wolf.player_id == selected.player_id):
                continue
            self._repository.record_private_action_decision(
                game_id=game_id,
                player_id=wolf.player_id,
                round_no=state.round_no,
                action_type="werewolf_self_explosion",
                decision={"explode": bool(decision.boolean_value)},
                decision_note=decision.decision_note,
                context={
                    "stage": stage,
                    "selected_for_resolution": False,
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                },
            )
        if selected is None:
            return False

        self._actions.check_cancellation(game_id)
        if pre_sheriff:
            outcome = self._repository.record_pre_sheriff_explosion(
                game_id=game_id,
                player_id=selected.player_id,
            )
        else:
            self._repository.record_day_explosion(
                game_id=game_id,
                player_id=selected.player_id,
                stage=stage,
            )
            outcome = "day_ended"
        current = self._repository.snapshot(game_id)
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_werewolf_self_explosion",
            objective=f"公开宣布{selected.seat}号发动狼人自爆并立即出局，当天剩余流程中止",
            success_phase_state=current.phase_state,
            context={
                "player_id": selected.player_id,
                "player_seat": selected.seat,
                "stage": stage,
                "outcome": outcome,
                "batch_id": batch_id,
            },
        ):
            raise DayRuntimeError("self_explosion_announcement_failed")
        await self._broadcast_death(
            state=current,
            player_id=selected.player_id,
            cause="werewolf_self_explosion",
            broadcaster=broadcaster,
        )
        await self._broadcast_match_state(self._repository.snapshot(game_id), broadcaster)
        return True

    async def _elect_sheriff(
        self,
        *,
        game_id: str,
        player: MatchPlayer,
        broadcaster: BroadcastPort,
        reason: str,
    ) -> None:
        self._actions.check_cancellation(game_id)
        self._repository.set_sheriff(game_id=game_id, player_id=player.player_id, reason=reason)
        state = self._repository.snapshot(game_id)
        if not await self._judge(
            state=state,
            broadcaster=broadcaster,
            action_type="judge_sheriff_elected",
            objective=f"宣布{player.seat}号当选警长并获得警徽",
            success_phase_state=state.phase_state,
            context={
                "player_id": player.player_id,
                "player_seat": player.seat,
                "reason": reason,
            },
        ):
            raise DayRuntimeError("sheriff_elected_announcement_failed")
        await self._broadcast_match_state(state, broadcaster)

    async def _destroy_badge(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        reason: str,
    ) -> None:
        self._actions.check_cancellation(game_id)
        self._repository.set_sheriff(game_id=game_id, player_id=None, reason=reason)
        state = self._repository.snapshot(game_id)
        if not await self._judge(
            state=state,
            broadcaster=broadcaster,
            action_type="judge_sheriff_badge_destroyed",
            objective="宣布本次警长竞选没有产生警长，警徽流失",
            success_phase_state=state.phase_state,
            context={"reason": reason},
        ):
            raise DayRuntimeError("sheriff_badge_destroyed_announcement_failed")
        await self._broadcast_match_state(state, broadcaster)

    async def _announce_no_exile(
        self,
        *,
        state: MatchSnapshot,
        broadcaster: BroadcastPort,
        reason: str,
    ) -> None:
        self._actions.check_cancellation(state.game_id)
        current = self._repository.snapshot(state.game_id)
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_no_exile",
            objective="宣布本轮放逐投票没有产生唯一结果，今天无人被放逐",
            success_phase_state=current.phase_state,
            context={"reason": reason},
        ):
            raise DayRuntimeError("no_exile_announcement_failed")

    async def _close_day(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        reason: str,
        summarize: bool,
    ) -> PhaseTransition:
        self._actions.check_cancellation(game_id)
        state = self._repository.snapshot(game_id)
        winner = self._repository.current_winner(game_id)
        if winner is not None:
            transition = self._repository.finish_day(game_id=game_id, reason=reason)
            await broadcaster.broadcast_json(game_phase_changed(transition))
            current = self._repository.snapshot(game_id)
            await self._broadcast_match_state(current, broadcaster)
            winner_name = "好人阵营" if winner == "villagers" else "狼人阵营"
            await self._actions.run_judge_speech(
                game_id=game_id,
                broadcaster=broadcaster,
                spec=SpeechSpec(
                    action_type="judge_game_completed",
                    phase_id=current.phase_id,
                    required_phase_state="game_completed",
                    objective=f"宣布本局结束，{winner_name}获胜",
                    success_live_state="awaiting_observation",
                    success_phase_state="game_completed",
                    context={"winner": winner, "round_no": current.round_no},
                    best_effort=True,
                ),
            )
            await broadcaster.broadcast_json(
                live_state(
                    game_id=current.game_id,
                    run_id=current.run_id,
                    state="awaiting_observation",
                )
            )
            return transition
        if summarize:
            if not await self._run_day_summary_and_private_memories(
                state=state,
                broadcaster=broadcaster,
            ):
                raise DayRuntimeError("day_summary_failed")
        self._actions.check_cancellation(game_id)
        try:
            transition = self._repository.finish_day(game_id=game_id, reason=reason)
        except BaseException:
            await self.join_background_private_memory_jobs(
                game_id=game_id,
                timeout=_BACKGROUND_MEMORY_JOIN_SECONDS,
                cancel=True,
            )
            raise
        await broadcaster.broadcast_json(game_phase_changed(transition))
        current = self._repository.snapshot(game_id)
        await self._broadcast_match_state(current, broadcaster)
        if transition.phase_state in {"game_completed", "failed"}:
            await broadcaster.broadcast_json(
                live_state(
                    game_id=current.game_id,
                    run_id=current.run_id,
                    state=(
                        "awaiting_observation"
                        if transition.phase_state == "game_completed"
                        else "failed"
                    ),
                    reason=(
                        None
                        if transition.phase_state == "game_completed"
                        else "max_rounds_exceeded"
                    ),
                )
            )
        return transition

    async def _run_day_summary_and_private_memories(
        self,
        *,
        state: MatchSnapshot,
        broadcaster: BroadcastPort,
    ) -> bool:
        if not is_supported_model_context_contract(state.model_context_contract):
            raise DayRuntimeError("unsupported_model_context_contract")

        players = tuple(
            sorted(
                (player for player in state.players if player.alive),
                key=lambda player: player.seat,
            )
        )
        memory_policy = resolve_model_generation_action_policy(
            state.model_generation_policy_contract,
            action_type="private_round_memory",
        )
        memory_mode = memory_policy.private_round_memory_mode
        batch_id = f"{state.game_id}:round_{state.round_no}:private_memories"
        terminal_status = self._repository.private_round_memory_batch_terminal_status(
            game_id=state.game_id,
            run_id=state.run_id,
            phase_id=state.phase_id,
            phase_state=state.phase_state,
            round_no=state.round_no,
            batch_id=batch_id,
            private_round_memory_mode=memory_mode,
        )
        if terminal_status is not None:
            return terminal_status == "completed"
        if batch_id in self._background_memory_jobs:
            return True
        started_payload: dict[str, Any] = {
            "round_no": state.round_no,
            "batch_id": batch_id,
            "phase_id": state.phase_id,
            "phase_state": state.phase_state,
            "public_cutoff_record_seq": state.last_record_seq,
            "player_ids": [player.player_id for player in players],
            "commit_order": [player.player_id for player in players],
            "private_round_memory_mode": memory_mode,
        }
        if memory_mode == "background_generation":
            started_payload.update(
                {
                    "origin_phase_id": state.phase_id,
                    "origin_phase_state": state.phase_state,
                    "source_cutoff_record_seq": state.last_record_seq,
                    "origin_sheriff_player_id": state.sheriff_player_id,
                    "origin_sheriff_badge_state": state.sheriff_badge_state,
                    "origin_player_states": {
                        player.player_id: dict(player.state) for player in state.players
                    },
                }
            )
        self._repository.append_event(
            game_id=state.game_id,
            event_type="day_private_memory_batch_started",
            audience="god_view",
            payload=started_payload,
        )

        request_started = {player.player_id: asyncio.Event() for player in players}
        memory_sources = {
            player.player_id: self._rolling_private_memory_sources(
                state=state,
                player=player,
            )
            for player in players
        }
        memory_states = {
            player.player_id: self._rolling_private_memory_state(
                state=state,
                previous_source_cutoff_record_seq=memory_sources[player.player_id][
                    "previous_source_cutoff_record_seq"
                ],
            )
            for player in players
        }
        memory_private_facts = {
            player.player_id: [
                dict(item) for item in memory_sources[player.player_id]["private_facts"]
            ]
            for player in players
        }
        memory_tasks = {
            player.player_id: asyncio.create_task(
                self._generate_private_round_memory(
                    state=state,
                    player=player,
                    broadcaster=broadcaster,
                    batch_id=batch_id,
                    request_started=request_started[player.player_id],
                    sources=memory_sources[player.player_id],
                    memory_state=memory_states[player.player_id],
                    frozen_private_facts=memory_private_facts[player.player_id],
                )
            )
            for player in players
        }
        judge_task: asyncio.Task[bool] | None = None
        try:
            if request_started:
                await asyncio.gather(*(event.wait() for event in request_started.values()))
            judge_task = asyncio.create_task(
                self._judge(
                    state=state,
                    broadcaster=broadcaster,
                    action_type="judge_day_summary",
                    objective=f"播报第{state.round_no}天流程结束并即将入夜",
                    success_phase_state=state.phase_state,
                    context={},
                )
            )
            if memory_mode == "background_generation":
                await judge_task
            else:
                await asyncio.gather(judge_task, *memory_tasks.values())
        except BaseException:
            for task in [*memory_tasks.values(), *([judge_task] if judge_task is not None else [])]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                *memory_tasks.values(),
                *([judge_task] if judge_task is not None else []),
                return_exceptions=True,
            )
            try:
                self._repository.append_event(
                    game_id=state.game_id,
                    event_type="day_private_memory_batch_canceled",
                    audience="god_view",
                    payload={
                        "round_no": state.round_no,
                        "batch_id": batch_id,
                        "private_round_memory_mode": memory_mode,
                    },
                )
            except Exception:
                logger.exception("Live V2 could not persist private memory batch cancellation")
            raise

        if judge_task is None or not judge_task.result():
            for task in memory_tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*memory_tasks.values(), return_exceptions=True)
            self._repository.append_event(
                game_id=state.game_id,
                event_type="day_private_memory_batch_completed",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "batch_id": batch_id,
                    "phase_id": state.phase_id,
                    "phase_state": state.phase_state,
                    "source_cutoff_record_seq": state.last_record_seq,
                    "public_summary_status": "failed",
                    "private_round_memory_mode": memory_mode,
                    "memories": [],
                    "commit_order": [player.player_id for player in players],
                },
            )
            return False

        if memory_mode == "background_generation":
            timeout_ms = memory_policy.reasoning_only_timeout_ms or 240_000
            job = _BackgroundPrivateMemoryJob(
                game_id=state.game_id,
                batch_id=batch_id,
                round_no=state.round_no,
                started_at=time.monotonic(),
                timeout_ms=timeout_ms,
                player_done={player.player_id: asyncio.Event() for player in players},
            )
            job.task = asyncio.create_task(
                self._finalize_background_private_memories(
                    state=state,
                    players=players,
                    batch_id=batch_id,
                    memory_mode=memory_mode,
                    memory_tasks=memory_tasks,
                    memory_sources=memory_sources,
                    job=job,
                )
            )
            self._background_memory_jobs[batch_id] = job
            return True

        committed: list[dict[str, Any]] = []
        pending_commits: list[PrivateRoundMemoryCommit] = []
        for commit_index, player in enumerate(players, start=1):
            action_result = memory_tasks[player.player_id].result()
            decision = action_result.decision if action_result is not None else None
            memory = decision.speech.strip() if decision is not None and decision.speech else ""
            if not memory:
                committed.append(
                    {
                        "player_id": player.player_id,
                        "status": "generation_failed",
                    }
                )
                continue
            if (
                action_result is None
                or not action_result.action_id
                or action_result.model_response_record_seq is None
                or action_result.terminal_event_record_seq is None
                or action_result.model_attempt_id is None
                or action_result.request_payload_sha256 is None
                or action_result.projected_context_sha256 is None
                or action_result.projected_known_event_refs is None
                or action_result.projected_known_events_sha256 is None
            ):
                raise DayRuntimeError("private_round_memory_lineage_missing")
            normalized_memory = memory[:_PRIVATE_ROUND_MEMORY_MAX_CHARS].rstrip()
            if normalized_memory != memory:
                self._repository.append_event(
                    game_id=state.game_id,
                    event_type="private_round_memory_normalized",
                    audience="god_view",
                    payload={
                        "round_no": state.round_no,
                        "batch_id": batch_id,
                        "owner_id": player.player_id,
                        "reason": "max_chars",
                        "max_chars": _PRIVATE_ROUND_MEMORY_MAX_CHARS,
                        "original_chars": len(memory),
                        "normalized_chars": len(normalized_memory),
                    },
                )
            pending_commits.append(
                PrivateRoundMemoryCommit(
                    player_id=player.player_id,
                    memory=normalized_memory,
                    commit_index=commit_index,
                    source_refs=tuple(memory_sources[player.player_id]["source_refs"]),
                    source_refs_sha256=memory_sources[player.player_id]["source_refs_sha256"],
                    previous_snapshot_fact_id=memory_sources[player.player_id][
                        "previous_snapshot_fact_id"
                    ],
                    action_id=action_result.action_id,
                    model_response_record_seq=action_result.model_response_record_seq,
                    terminal_event_record_seq=action_result.terminal_event_record_seq,
                    provider_request_id=decision.provider_request_id,
                    attempt_id=action_result.model_attempt_id,
                    request_payload_sha256=action_result.request_payload_sha256,
                    projected_context_sha256=action_result.projected_context_sha256,
                    projected_known_event_refs=(action_result.projected_known_event_refs),
                    projected_known_events_sha256=(
                        action_result.projected_known_events_sha256
                    ),
                )
            )

        completed_payload = {
            "round_no": state.round_no,
            "batch_id": batch_id,
            "phase_id": state.phase_id,
            "phase_state": state.phase_state,
            "source_cutoff_record_seq": state.last_record_seq,
            "public_summary_status": "completed",
            "memories": [
                *[item for item in committed if item["status"] == "generation_failed"],
            ],
            "commit_order": [player.player_id for player in players],
            "private_round_memory_mode": memory_mode,
        }
        commit_results = self._repository.record_private_round_memories(
            game_id=state.game_id,
            run_id=state.run_id,
            phase_id=state.phase_id,
            phase_state=state.phase_state,
            round_no=state.round_no,
            batch_id=batch_id,
            source_cutoff_record_seq=state.last_record_seq,
            commits=tuple(pending_commits),
            batch_completed_payload=completed_payload,
        )
        result_by_player = {
            commit.player_id: result
            for commit, result in zip(pending_commits, commit_results, strict=True)
        }
        committed = [item for item in committed if item["status"] == "generation_failed"]
        for player in players:
            result = result_by_player.get(player.player_id)
            if result is None:
                continue
            fact_id, created = result
            committed.append(
                {
                    "player_id": player.player_id,
                    "status": "committed" if created else "reused",
                    "knowledge_fact_id": fact_id,
                }
            )

        return True

    async def _finalize_background_private_memories(
        self,
        *,
        state: MatchSnapshot,
        players: tuple[MatchPlayer, ...],
        batch_id: str,
        memory_mode: str,
        memory_tasks: dict[str, asyncio.Task[ActionResult | None]],
        memory_sources: dict[str, dict[str, Any]],
        job: _BackgroundPrivateMemoryJob,
    ) -> None:
        truncated_by: str | None = None
        try:
            pending = dict(memory_tasks)
            player_by_id = {player.player_id: player for player in players}
            while pending:
                done, _ = await asyncio.wait(
                    pending.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                finished_ids = [
                    player_id for player_id, task in list(pending.items()) if task in done
                ]
                for player_id in finished_ids:
                    task = pending.pop(player_id)
                    player = player_by_id[player_id]
                    try:
                        action_result = task.result()
                    except asyncio.CancelledError:
                        job.memories.append(
                            {"player_id": player_id, "status": "generation_failed"}
                        )
                        job.player_done[player_id].set()
                        raise
                    except Exception:
                        logger.exception(
                            "Live V2 background private memory failed",
                            extra={"game_id": state.game_id, "player_id": player_id},
                        )
                        job.memories.append(
                            {"player_id": player_id, "status": "generation_failed"}
                        )
                        job.player_done[player_id].set()
                        continue
                    self._commit_background_private_memory_result(
                        state=state,
                        player=player,
                        batch_id=batch_id,
                        action_result=action_result,
                        sources=memory_sources[player_id],
                        commit_index=players.index(player) + 1,
                        job=job,
                    )
                    job.player_done[player_id].set()
            current = self._repository.snapshot(state.game_id)
            if current.phase_state == "game_completed":
                truncated_by = "game_completed"
            memories = list(job.memories)
            remembered_ids = {
                str(item.get("player_id"))
                for item in memories
                if isinstance(item.get("player_id"), str)
            }
            for player in players:
                if player.player_id not in remembered_ids:
                    memories.append(
                        {"player_id": player.player_id, "status": "generation_failed"}
                    )
            self._repository.complete_private_round_memory_batch(
                game_id=state.game_id,
                batch_completed_payload={
                    "round_no": state.round_no,
                    "batch_id": batch_id,
                    "phase_id": state.phase_id,
                    "phase_state": state.phase_state,
                    "source_cutoff_record_seq": state.last_record_seq,
                    "public_summary_status": "completed",
                    "private_round_memory_mode": memory_mode,
                    "memories": memories,
                    "commit_order": [player.player_id for player in players],
                    "commit_phase_ids": list(dict.fromkeys(job.commit_phase_ids)),
                    **({"truncated_by": truncated_by} if truncated_by is not None else {}),
                },
            )
        except asyncio.CancelledError:
            for task in memory_tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*memory_tasks.values(), return_exceptions=True)
            try:
                self._repository.append_event(
                    game_id=state.game_id,
                    event_type="day_private_memory_batch_canceled",
                    audience="god_view",
                    payload={
                        "round_no": state.round_no,
                        "batch_id": batch_id,
                        "private_round_memory_mode": memory_mode,
                        "truncated_by": truncated_by or "canceled",
                    },
                )
            except Exception:
                logger.exception("Live V2 could not persist background memory cancellation")
            raise
        except Exception:
            logger.exception(
                "Live V2 background private memory batch failed",
                extra={"game_id": state.game_id, "batch_id": batch_id},
            )
        finally:
            for event in job.player_done.values():
                event.set()

    def _commit_background_private_memory_result(
        self,
        *,
        state: MatchSnapshot,
        player: MatchPlayer,
        batch_id: str,
        action_result: ActionResult | None,
        sources: dict[str, Any],
        commit_index: int,
        job: _BackgroundPrivateMemoryJob,
    ) -> None:
        decision = action_result.decision if action_result is not None else None
        memory = decision.speech.strip() if decision is not None and decision.speech else ""
        if not memory:
            job.memories.append({"player_id": player.player_id, "status": "generation_failed"})
            return
        if (
            action_result is None
            or not action_result.action_id
            or action_result.model_response_record_seq is None
            or action_result.terminal_event_record_seq is None
            or action_result.model_attempt_id is None
            or action_result.request_payload_sha256 is None
            or action_result.projected_context_sha256 is None
            or action_result.projected_known_event_refs is None
            or action_result.projected_known_events_sha256 is None
        ):
            job.memories.append({"player_id": player.player_id, "status": "generation_failed"})
            return
        normalized_memory = memory[:_PRIVATE_ROUND_MEMORY_MAX_CHARS].rstrip()
        if normalized_memory != memory:
            self._repository.append_event(
                game_id=state.game_id,
                event_type="private_round_memory_normalized",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "batch_id": batch_id,
                    "owner_id": player.player_id,
                    "reason": "max_chars",
                    "max_chars": _PRIVATE_ROUND_MEMORY_MAX_CHARS,
                    "original_chars": len(memory),
                    "normalized_chars": len(normalized_memory),
                },
            )
        commit = PrivateRoundMemoryCommit(
            player_id=player.player_id,
            memory=normalized_memory,
            commit_index=commit_index,
            source_refs=tuple(sources["source_refs"]),
            source_refs_sha256=sources["source_refs_sha256"],
            previous_snapshot_fact_id=sources["previous_snapshot_fact_id"],
            action_id=action_result.action_id,
            model_response_record_seq=action_result.model_response_record_seq,
            terminal_event_record_seq=action_result.terminal_event_record_seq,
            provider_request_id=decision.provider_request_id,
            attempt_id=action_result.model_attempt_id,
            request_payload_sha256=action_result.request_payload_sha256,
            projected_context_sha256=action_result.projected_context_sha256,
            projected_known_event_refs=action_result.projected_known_event_refs,
            projected_known_events_sha256=action_result.projected_known_events_sha256,
        )
        try:
            fact_id, created = self._repository.record_private_round_memory(
                game_id=state.game_id,
                run_id=state.run_id,
                phase_id=state.phase_id,
                phase_state=state.phase_state,
                round_no=state.round_no,
                batch_id=batch_id,
                source_cutoff_record_seq=state.last_record_seq,
                commit=commit,
            )
        except Exception:
            logger.exception(
                "Live V2 could not commit background private memory",
                extra={"game_id": state.game_id, "player_id": player.player_id},
            )
            job.memories.append({"player_id": player.player_id, "status": "generation_failed"})
            return
        current = self._repository.snapshot(state.game_id)
        job.commit_phase_ids.append(current.phase_id)
        job.memories.append(
            {
                "player_id": player.player_id,
                "status": "committed" if created else "reused",
                "knowledge_fact_id": fact_id,
            }
        )

    async def _await_player_previous_round_memory(
        self,
        *,
        game_id: str,
        player_id: str,
        previous_round_no: int,
    ) -> None:
        if previous_round_no < 1:
            return
        job = next(
            (
                item
                for item in self._background_memory_jobs.values()
                if item.game_id == game_id and item.round_no == previous_round_no
            ),
            None,
        )
        if job is None:
            return
        event = job.player_done.get(player_id)
        if event is None or event.is_set():
            return
        remaining = (job.timeout_ms / 1000) - (time.monotonic() - job.started_at)
        if remaining <= 0:
            self._repository.append_event(
                game_id=game_id,
                event_type="private_round_memory_wait_expired",
                audience="god_view",
                payload={
                    "owner_id": player_id,
                    "round_no": previous_round_no,
                    "batch_id": job.batch_id,
                },
            )
            return
        try:
            await asyncio.wait_for(event.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            self._repository.append_event(
                game_id=game_id,
                event_type="private_round_memory_wait_expired",
                audience="god_view",
                payload={
                    "owner_id": player_id,
                    "round_no": previous_round_no,
                    "batch_id": job.batch_id,
                },
            )

    async def _generate_private_round_memory(
        self,
        *,
        state: MatchSnapshot,
        player: MatchPlayer,
        broadcaster: BroadcastPort,
        batch_id: str,
        request_started: asyncio.Event,
        sources: dict[str, Any],
        memory_state: MatchSnapshot,
        frozen_private_facts: list[dict[str, Any]],
    ) -> ActionResult | None:
        request_started.set()
        canonical_source_context = build_private_round_memory_source_context(
            round_no=state.round_no,
            batch_id=batch_id,
            source_cutoff_record_seq=state.last_record_seq,
            player_id=player.player_id,
            seat=player.seat,
            role_key=player.role_key,
            team=player.team,
            persona=player.persona,
            alive=player.alive,
            sheriff_player_id=state.sheriff_player_id,
            sheriff_badge_state=state.sheriff_badge_state,
            rule=memory_state.rule,
            max_rounds=memory_state.max_rounds,
            player_state=player.state,
            players=memory_state.players,
            private_facts=[
                item
                for item in frozen_private_facts
                if item.get("fact_type") != "living_werewolf_teammates"
            ],
            public_history=memory_state.public_history,
            previous_memory_snapshot=sources["previous_snapshot"],
            previous_memory_fact_id=sources["previous_snapshot_fact_id"],
            previous_memory_source_cutoff_record_seq=sources[
                "previous_source_cutoff_record_seq"
            ],
            memory_source_refs=sources["source_refs"],
            memory_source_refs_sha256=sources["source_refs_sha256"],
        )
        return await self._player_action(
            game_id=state.game_id,
            player=player,
            broadcaster=broadcaster,
            action_type="private_round_memory",
            objective=private_round_memory_objective(state.round_no),
            candidates=[],
            target_optional=None,
            output_kind="private_round_memory",
            decision_contract=DecisionContract(
                kind="speech",
                speech_mode="required",
                speech_max_chars=_PRIVATE_ROUND_MEMORY_MAX_CHARS,
                speech_max_sentences=4,
            ),
            audience="player_private",
            extra_context={
                key: canonical_source_context[key]
                for key in (
                    "private_memory_batch_id",
                    "public_cutoff_record_seq",
                    "memory_round_no",
                    "memory_visibility",
                    "rolling_memory_schema_version",
                    "previous_memory_snapshot",
                    "previous_memory_fact_id",
                    "previous_memory_source_cutoff_record_seq",
                    "memory_source_refs",
                    "memory_source_refs_sha256",
                )
            },
            frozen_state=memory_state,
            frozen_private_facts=frozen_private_facts,
            projection_at_seq=state.last_record_seq,
            defer_presentation=True,
            isolated_failure=True,
            allow_failure=True,
            batch_id=batch_id,
            return_result=True,
        )

    def _rolling_private_memory_sources(
        self,
        *,
        state: MatchSnapshot,
        player: MatchPlayer,
    ) -> dict[str, Any]:
        private_facts = self._repository.private_knowledge(
            game_id=state.game_id,
            player_id=player.player_id,
            at_or_before_record_seq=state.last_record_seq,
        )
        previous = next(
            (item for item in private_facts if item.get("fact_type") == "private_round_memory"),
            None,
        )
        previous_payload = (
            previous.get("payload")
            if isinstance(previous, dict) and isinstance(previous.get("payload"), dict)
            else {}
        )
        previous_fact_id = (
            previous.get("knowledge_fact_id") if isinstance(previous, dict) else None
        )
        previous_fact_id = previous_fact_id if isinstance(previous_fact_id, str) else None
        previous_cutoff = previous_payload.get("source_cutoff_record_seq")
        previous_cutoff = (
            previous_cutoff
            if isinstance(previous_cutoff, int)
            and not isinstance(previous_cutoff, bool)
            and previous_cutoff > 0
            else 0
        )
        public_refs = [
            f"event:{item['source_event_id']}"
            for item in state.public_history
            if isinstance(item.get("source_event_id"), int)
            and isinstance(item.get("record_seq"), int)
            and item["record_seq"] > previous_cutoff
        ]
        private_refs = [
            f"fact:{item['knowledge_fact_id']}"
            for item in private_facts
            if item.get("fact_type") != "private_round_memory"
            and isinstance(item.get("knowledge_fact_id"), str)
        ]
        source_refs = [
            *([f"fact:{previous_fact_id}"] if previous_fact_id is not None else []),
            f"state:{state.last_record_seq}",
            *public_refs,
            *private_refs,
        ]
        source_refs_sha256 = private_round_memory_source_refs_sha256(
            owner_id=player.player_id,
            round_no=state.round_no,
            previous_snapshot_fact_id=previous_fact_id,
            source_cutoff_record_seq=state.last_record_seq,
            source_refs=source_refs,
        )
        return {
            "previous_snapshot": dict(previous) if isinstance(previous, dict) else None,
            "previous_snapshot_fact_id": previous_fact_id,
            "previous_source_cutoff_record_seq": previous_cutoff or None,
            "source_refs": source_refs,
            "source_refs_sha256": source_refs_sha256,
            "private_facts": private_facts,
        }

    @staticmethod
    def _rolling_private_memory_state(
        *,
        state: MatchSnapshot,
        previous_source_cutoff_record_seq: int | None,
    ) -> MatchSnapshot:
        cutoff = previous_source_cutoff_record_seq or 0
        return MatchSnapshot(
            **{
                **state.__dict__,
                "public_history": tuple(
                    item
                    for item in state.public_history
                    if isinstance(item.get("record_seq"), int)
                    and item["record_seq"] > cutoff
                ),
            }
        )

    async def _judge(
        self,
        *,
        state: MatchSnapshot,
        broadcaster: BroadcastPort,
        action_type: str,
        objective: str,
        success_phase_state: str,
        context: dict[str, Any],
    ) -> bool:
        self._actions.check_cancellation(state.game_id)
        return await self._actions.run_judge_speech(
            game_id=state.game_id,
            broadcaster=broadcaster,
            spec=SpeechSpec(
                action_type=action_type,
                phase_id=state.phase_id,
                required_phase_state=state.phase_state,
                objective=objective,
                success_live_state="ready",
                success_phase_state=success_phase_state,
                context={"round_no": state.round_no, **context},
            ),
        )

    async def _player_action(
        self,
        *,
        game_id: str,
        player: MatchPlayer,
        broadcaster: BroadcastPort,
        action_type: str,
        objective: str,
        candidates: list[MatchPlayer],
        target_optional: bool | None,
        output_kind: str,
        decision_contract: DecisionContract | None = None,
        audience: str = "all",
        extra_context: dict[str, Any] | None = None,
        frozen_state: MatchSnapshot | None = None,
        frozen_private_facts: list[dict[str, Any]] | None = None,
        projection_at_seq: int | None = None,
        defer_presentation: bool = False,
        isolated_failure: bool = False,
        pause_on_model_failure: bool = False,
        allow_failure: bool = False,
        batch_id: str | None = None,
        decision_family_id: str | None = None,
        prior_machine_format_failures: int = 0,
        automatic_machine_format_budget: int | None = None,
        prior_output_budget_failures: int = 0,
        automatic_output_budget_budget: int | None = None,
        preflight_pause_failure: PreflightPauseFailure | None = None,
        target_exhaustion_outcome: Literal["technical_abstain"] | None = None,
        precomputed_decision: ModelDecision | None = None,
        on_presentation_opened: Callable[[PresentationIdentity], None] | None = None,
        on_presentation_closed: Callable[[PresentationIdentity], None] | None = None,
        model_admission_mode: ProviderAdmissionMode = "normal",
        pipeline_slot_id: str | None = None,
        pipeline_stage: Literal["generation", "presentation"] | None = None,
        pipeline_kind: Literal["pre_exile"] | None = None,
        pipeline_result_kind: Literal["self_explosion", "exile_vote"] | None = None,
        pipeline_empty_stream_max_attempts: Literal[1, 2] = 1,
        pipeline_retry_mode: Literal[
            "disabled",
            "empty_stream_once_while_predecessor_active",
        ] = "disabled",
        model_retry_guard: Callable[[ModelError, int], bool] | None = None,
        on_model_admission_pending: Callable[[], None] | None = None,
        return_result: bool = False,
    ) -> ModelDecision | ActionResult | None:
        self._actions.check_cancellation(game_id)
        if action_type != "private_round_memory":
            wait_state = frozen_state or self._repository.snapshot(game_id)
            await self._await_player_previous_round_memory(
                game_id=game_id,
                player_id=player.player_id,
                previous_round_no=wait_state.round_no - 1,
            )
        state = frozen_state or self._repository.snapshot(game_id)
        if projection_at_seq is not None and (
            frozen_state is None or projection_at_seq != frozen_state.last_record_seq
        ):
            raise DayRuntimeError(
                "projection_at_seq must equal the explicitly frozen state cutoff"
            )
        private_facts = (
            [dict(item) for item in frozen_private_facts]
            if frozen_private_facts is not None
            else self._repository.private_knowledge(
                game_id=game_id,
                player_id=player.player_id,
                at_or_before_record_seq=state.last_record_seq,
            )
        )
        if player.role_key == "werewolf":
            private_facts = [
                *private_facts,
                {
                    "fact_type": "living_werewolf_teammates",
                    "payload": [
                        item.player_id
                        for item in state.players
                        if item.alive
                        and item.role_key == "werewolf"
                        and item.player_id != player.player_id
                    ],
                },
            ]
        has_actor_memory = any(
            isinstance(item, dict) and item.get("fact_type") == "private_round_memory"
            for item in private_facts
        )
        memory_gap_context = (
            {"unarchived_memory_source_cutoff_record_seq": 0}
            if action_type != "private_round_memory"
            and state.round_no > 1
            and not has_actor_memory
            else {}
        )
        resolved_contract = decision_contract or (
            DecisionContract(
                kind="speech",
                speech_max_chars=_PUBLIC_SPEECH_MAX_CHARS.get(action_type),
            )
            if output_kind == "public_speech"
            else DecisionContract(
                kind="target",
                target_mode="optional" if target_optional else "required",
            )
        )
        if resolved_contract.kind == "target" and target_optional is None:
            raise DayRuntimeError("target action requires target_optional")
        if resolved_contract.kind != "target" and target_optional is not None:
            raise DayRuntimeError("non-target action cannot set target_optional")
        spec = SpeechSpec(
            action_type=action_type,
            phase_id=state.phase_id,
            required_phase_state=state.phase_state,
            objective=objective,
            success_live_state="ready",
            success_phase_state=state.phase_state,
            actor_kind="player",
            actor_id=player.player_id,
            audience=audience,
            speaker=player.tts_speaker,
            dialect=player.tts_dialect,
            model_provider=player.model_provider,
            model_id=player.model_id,
            model_supports_thinking=player.model_supports_thinking,
            model_parameters=player.model_parameters,
            # Vote-phase thinking offload is applied at the payload layer after
            # frozen-parameter validation, never by mutating the frozen dict.
            disable_provider_thinking=(
                settings.live_v2_vote_disable_thinking
                and action_type in _VOTE_PHASE_ACTION_TYPES
            ),
            output_kind=output_kind,
            decision_contract=resolved_contract,
            allowed_target_ids=(
                tuple(item.player_id for item in candidates)
                if resolved_contract.kind == "target"
                else None
            ),
            model_players=tuple(
                ModelPlayerReference(
                    player_id=item.player_id,
                    seat=item.seat,
                    display_name=item.display_name,
                )
                for item in state.players
            ),
            context={
                "round_no": state.round_no,
                **build_actor_information(
                    player_id=player.player_id,
                    seat=player.seat,
                    role_key=player.role_key,
                    team=player.team,
                    persona=player.persona,
                    alive=player.alive,
                    sheriff_player_id=state.sheriff_player_id,
                    sheriff_badge_state=state.sheriff_badge_state,
                    rule=state.rule,
                    player_state=player.state,
                    private_facts=private_facts,
                    current_action_type=action_type,
                ),
                "private_authoritative_facts": private_authoritative_facts(
                    private_facts,
                    owner_scope="player",
                    owner_id=player.player_id,
                ),
                "public_match_state": build_public_match_state(
                    round_no=state.round_no,
                    players=state.players,
                ),
                "candidates": [
                    {
                        "player_id": item.player_id,
                        "seat": item.seat,
                        "display_name": item.display_name,
                    }
                    for item in candidates
                ],
                "public_history": list(state.public_history),
                "sheriff_player_id": state.sheriff_player_id,
                "public_rule_contract": build_public_rule_contract(
                    rule=state.rule,
                    max_rounds=state.max_rounds,
                ),
                **memory_gap_context,
                **(extra_context or {}),
            },
            defer_presentation=defer_presentation,
            isolated_failure=isolated_failure,
            pause_on_model_failure=pause_on_model_failure,
            batch_id=batch_id,
            projection_at_seq=projection_at_seq,
            decision_family_id=decision_family_id,
            prior_machine_format_failures=prior_machine_format_failures,
            automatic_machine_format_budget=automatic_machine_format_budget,
            prior_output_budget_failures=prior_output_budget_failures,
            automatic_output_budget_budget=automatic_output_budget_budget,
            preflight_pause_failure=preflight_pause_failure,
            target_exhaustion_outcome=target_exhaustion_outcome,
            model_admission_mode=model_admission_mode,
            pipeline_slot_id=pipeline_slot_id,
            pipeline_stage=pipeline_stage,
            pipeline_kind=pipeline_kind,
            pipeline_result_kind=pipeline_result_kind,
            pipeline_empty_stream_max_attempts=pipeline_empty_stream_max_attempts,
            pipeline_retry_mode=pipeline_retry_mode,
        )
        if precomputed_decision is not None:
            present_result = getattr(self._actions, "present_player_decision_result", None)
            if not callable(present_result):
                raise DayRuntimeError("pipeline presentation is unsupported")
            result = await present_result(
                game_id=game_id,
                broadcaster=broadcaster,
                spec=spec,
                decision=precomputed_decision,
                on_presentation_opened=on_presentation_opened,
                on_presentation_closed=on_presentation_closed,
            )
        elif return_result and callable(getattr(self._actions, "run_player_decision_result", None)):
            result_method = self._actions.run_player_decision_result
            result_kwargs: dict[str, Any] = {
                "game_id": game_id,
                "broadcaster": broadcaster,
                "spec": spec,
            }
            if on_presentation_opened is not None:
                result_kwargs["on_presentation_opened"] = on_presentation_opened
            if on_presentation_closed is not None:
                result_kwargs["on_presentation_closed"] = on_presentation_closed
            if model_retry_guard is not None:
                result_kwargs["model_retry_guard"] = model_retry_guard
            if on_model_admission_pending is not None:
                result_kwargs["on_model_admission_pending"] = on_model_admission_pending
            result = await result_method(**result_kwargs)
        else:
            decision_kwargs: dict[str, Any] = {
                "game_id": game_id,
                "broadcaster": broadcaster,
                "spec": spec,
            }
            if on_presentation_opened is not None:
                decision_kwargs["on_presentation_opened"] = on_presentation_opened
            if on_presentation_closed is not None:
                decision_kwargs["on_presentation_closed"] = on_presentation_closed
            decision = await self._actions.run_player_decision(**decision_kwargs)
            result = ActionResult(decision=decision)
        decision = result.decision if result is not None else None
        if (
            decision is None
            and not allow_failure
            and (result is None or result.technical_outcome is None)
        ):
            raise DayRuntimeError(f"{action_type}_failed")
        if return_result:
            return result
        return decision

    def _record_speech(
        self,
        state: MatchSnapshot,
        player: MatchPlayer,
        decision: ModelDecision,
        stage: str,
    ) -> None:
        if not decision.speech:
            return
        self._repository.append_event(
            game_id=state.game_id,
            event_type="day_speech_committed",
            audience="all",
            payload={
                "round_no": state.round_no,
                "stage": stage,
                "player_id": player.player_id,
                "speech": decision.speech,
            },
        )

    async def _broadcast_death(
        self,
        *,
        state: MatchSnapshot,
        player_id: str,
        cause: str,
        broadcaster: BroadcastPort,
    ) -> None:
        await broadcaster.broadcast_json(
            player_state_changed(
                game_id=state.game_id,
                run_id=state.run_id,
                player_id=player_id,
                alive=False,
                cause=None,
            ),
            audience="public",
        )
        await broadcaster.broadcast_json(
            player_state_changed(
                game_id=state.game_id,
                run_id=state.run_id,
                player_id=player_id,
                alive=False,
                cause=cause,
            ),
            audience="god_view",
        )

    async def _broadcast_match_state(
        self,
        state: MatchSnapshot,
        broadcaster: BroadcastPort,
    ) -> None:
        match = match_state_changed(
            game_id=state.game_id,
            run_id=state.run_id,
            round_no=state.round_no,
            sheriff_player_id=state.sheriff_player_id,
            sheriff_badge_state=state.sheriff_badge_state,
            winner=self._repository.current_winner(state.game_id)
            if state.phase_state == "game_completed"
            else None,
        )
        await broadcaster.broadcast_json(match)


def _leaders(totals: dict[str, float]) -> list[str]:
    if not totals:
        return []
    highest = max(totals.values())
    return sorted(player_id for player_id, value in totals.items() if value == highest)


def _self_explosion_action_effect(
    *,
    state: MatchSnapshot,
    stage: str,
    pre_sheriff: bool,
) -> dict[str, Any]:
    if pre_sheriff:
        policy = str(state.rule.get("sheriff_badge_bomb_policy") or "none")
        next_explosion_count = state.pre_sheriff_explosion_count + 1
        badge_result = (
            "destroyed" if policy == "double" and next_explosion_count >= 2 else "pending"
        )
        remaining_day_flow = "sheriff_election_interrupted"
    else:
        policy = None
        next_explosion_count = None
        badge_result = state.sheriff_badge_state
        remaining_day_flow = "terminated"
    return {
        "action_type": "werewolf_self_explosion",
        "source": "frozen_rules_and_current_stage",
        "target_mode": "none",
        "if_executed": {
            "actor_eliminated": True,
            "actor_role_publicly_confirmed": "werewolf",
            "target_allowed": False,
            "other_players_affected": False,
            "other_players_eliminated": False,
            "remaining_day_flow": remaining_day_flow,
            "sheriff_badge_result": badge_result,
            "pre_sheriff_explosion_policy": policy,
            "pre_sheriff_explosion_count_after_action": next_explosion_count,
        },
        "public_stage": stage,
        "speech_has_gameplay_effect": False,
        "instruction": (
            "自爆只会让行动狼人本人出局并公开确认狼人身份；"
            "不会选择、杀死或带走其他玩家，speech 也不会产生额外游戏效果。"
        ),
    }


def _required_target(decision: ModelDecision) -> str:
    if decision.target_player_id is None:
        raise DayRuntimeError("required vote target is missing")
    return decision.target_player_id


def _private_fact_visible_at_public_cutoff(
    fact: dict[str, Any],
    public_cutoff_record_seq: int,
) -> bool:
    known_at_seq = fact.get("known_at_seq")
    record_seq = fact.get("record_seq")
    clock = known_at_seq if type(known_at_seq) is int else record_seq
    return type(clock) is int and clock <= public_cutoff_record_seq


def _vote_fanout_delay_seconds(slot: int) -> float:
    """Per-slot delay that spaces out a vote fan-out.

    A whole vote batch hitting provider admission in the same instant showed
    up as `model_prefetch_capacity_unavailable` storms; staggering each slot
    by a few hundred milliseconds spreads the admission pressure.
    """
    stagger_ms = int(settings.live_v2_vote_fanout_stagger_ms)
    if stagger_ms <= 0 or slot <= 0:
        return 0.0
    return min(slot * stagger_ms, 10_000) / 1000.0


async def _staggered_vote_request(
    slot: int,
    request: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    delay = _vote_fanout_delay_seconds(slot)
    if delay > 0:
        await asyncio.sleep(delay)
    return await request(*args, **kwargs)


def _persisted_pre_exile_failure_category(failure: dict[str, Any]) -> str | None:
    request = failure.get("model_request_failed")
    if isinstance(request, dict):
        category = request.get("failure_category")
        if isinstance(category, str):
            return category
    action = failure.get("action_failed")
    if isinstance(action, dict):
        category = action.get("failure_category") or action.get("failure_kind")
        if isinstance(category, str):
            return category
    return None


def _pre_exile_wolf_vote_private_facts(
    *,
    base: list[dict[str, Any]],
    owner_facts: list[dict[str, Any]],
    owner_player_id: str,
    pipeline_id: str,
    private_fact_id: str | None,
    private_fact_record_seq: int | None,
    public_cutoff_record_seq: int,
) -> list[dict[str, Any]]:
    if (
        not isinstance(private_fact_id, str)
        or not private_fact_id
        or type(private_fact_record_seq) is not int
        or private_fact_record_seq <= public_cutoff_record_seq
    ):
        raise DayRuntimeError("pre_exile_wolf_false_private_fact_missing")
    own = [
        copy.deepcopy(fact)
        for fact in owner_facts
        if fact.get("knowledge_fact_id") == private_fact_id
    ]
    if len(own) != 1:
        raise DayRuntimeError("pre_exile_wolf_false_private_fact_missing")
    fact = own[0]
    payload = fact.get("payload")
    decision = payload.get("decision") if isinstance(payload, dict) else None
    fact_context = payload.get("context") if isinstance(payload, dict) else None
    if (
        fact.get("owner_scope") != "player"
        or fact.get("owner_id") != owner_player_id
        or fact.get("fact_type") != "private_action_decision"
        or fact.get("source_event_type") != "private_knowledge_recorded"
        or fact.get("record_seq") != private_fact_record_seq
        or fact.get("known_at_seq") != private_fact_record_seq
        or not isinstance(payload, dict)
        or payload.get("action_type") != "werewolf_self_explosion"
        or not isinstance(fact_context, dict)
        or fact_context.get("pipeline_id") != pipeline_id
        or fact_context.get("public_history_cutoff_record_seq") != public_cutoff_record_seq
        or fact_context.get("visibility_mode") != "pre_exile_provisional_until_atomic_arbiter"
        or not isinstance(decision, dict)
        or decision.get("explode") is not False
    ):
        raise DayRuntimeError("pre_exile_wolf_false_private_fact_invalid")
    return [*copy.deepcopy(base), fact]


def _failure_code(exc: Exception) -> str:
    value = str(exc).strip()
    if not value:
        return "day_runtime_failed"
    return value[:120]
