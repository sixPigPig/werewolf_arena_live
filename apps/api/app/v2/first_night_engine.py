from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
import hashlib
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from app.v2.action_engine import (
    V2ActionEngine,
    V2BroadcastPort,
    V2DecisionContract,
    V2SpeechSpec,
)
from app.v2.model_client import V2ModelDecision
from app.v2.model_context import (
    V2ModelPlayerReference,
    build_actor_information,
    build_public_match_state,
    build_public_rule_contract,
    private_authoritative_facts,
)
from app.v2.night_repository import (
    V2ActivationRef,
    V2NightPlayer,
    V2NightRepository,
    V2NightRuntimeState,
)
from app.v2.protocol import (
    ability_progress,
    game_phase_changed,
    god_view_night_resolution,
    live_state,
    match_state_changed,
    night_progress,
    public_dawn_result,
)
from app.v2.repository import V2ExecutionOwnershipLost, V2PhaseTransition

if TYPE_CHECKING:
    from app.v2.day_engine import V2DayEngine


logger = logging.getLogger(__name__)

_PARALLEL_NIGHT_GROUPS = ("werewolves", "guard", "seer")
_DECISION_NOTE_MAX_CHARS = 80


class V2NightError(RuntimeError):
    pass


@dataclass
class _WorkingNight:
    attack_target: str | None = None
    protected_target: str | None = None
    healed_target: str | None = None
    poisoned_target: str | None = None


@dataclass(frozen=True)
class _WerewolfAttackResolution:
    target_player_id: str | None
    reason: str
    tiebreaker_player_id: str | None = None
    tied_target_player_ids: tuple[str | None, ...] = ()


@dataclass(frozen=True)
class _NightParallelBatch:
    batch_id: str
    public_cutoff_record_seq: int
    public_history: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class _PreparedRoleDecision:
    group: str
    ability_id: str
    player: V2NightPlayer | None
    candidates: tuple[V2NightPlayer, ...]
    objective: str
    knowledge: dict[str, Any]
    optional: bool
    skip_reason: str | None = None


@dataclass(frozen=True)
class _BufferedRoleDecision:
    prepared: _PreparedRoleDecision
    activation: V2ActivationRef | None
    decision: V2ModelDecision | None


GroupHandler = Callable[[V2NightRuntimeState, V2BroadcastPort, _WorkingNight], Awaitable[None]]


class V2NightEngine:
    def __init__(
        self,
        *,
        repository: V2NightRepository,
        action_engine: V2ActionEngine,
        day_engine: V2DayEngine,
    ) -> None:
        self._repository = repository
        self._actions = action_engine
        self._day = day_engine
        self._handlers: dict[str, GroupHandler] = {
            "werewolves": self._run_werewolves,
            "guard": self._run_guard,
            "seer": self._run_seer,
            "witch": self._run_witch,
        }

    async def run(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> V2PhaseTransition | None:
        try:
            self._actions.check_cancellation(game_id)
            state = self._repository.start_night(game_id, audience="god_view")
            working = _WorkingNight()
            await broadcaster.broadcast_json(
                night_progress(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    stage="night_started",
                    latest_presentation_seq=self._repository.latest_presentation_seq(game_id),
                ),
                audience="public",
            )
            groups = _activation_groups(state.snapshot)
            parallel_groups = tuple(group for group in _PARALLEL_NIGHT_GROUPS if group in groups)
            if parallel_groups:
                await self._run_parallel_independent_groups(
                    state=state,
                    broadcaster=broadcaster,
                    working=working,
                    groups=parallel_groups,
                )
            for group in groups:
                if group in parallel_groups:
                    continue
                self._actions.check_cancellation(game_id)
                handler = self._handlers.get(group)
                if handler is None:
                    raise V2NightError(f"unsupported_activation_group:{group}")
                await handler(state, broadcaster, working)
                self._actions.check_cancellation(game_id)
                await broadcaster.broadcast_json(
                    night_progress(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        stage="actions_in_progress",
                        latest_presentation_seq=self._repository.latest_presentation_seq(game_id),
                    ),
                    audience="public",
                )
            self._actions.check_cancellation(game_id)
            resolution = self._repository.resolve_night(
                state=state,
                attack_target=working.attack_target,
                protected_target=working.protected_target,
                healed_target=working.healed_target,
                poisoned_target=working.poisoned_target,
            )
            await broadcaster.broadcast_json(
                ability_progress(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    ability_id="night.resolve",
                    status="completed",
                ),
                audience="god_view",
            )
            await broadcaster.broadcast_json(
                god_view_night_resolution(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    deaths=list(resolution.deaths),
                    attack_prevented_by=resolution.attack_prevented_by,
                ),
                audience="god_view",
            )
            await broadcaster.broadcast_json(
                night_progress(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    stage="night_resolved",
                    latest_presentation_seq=self._repository.latest_presentation_seq(game_id),
                ),
                audience="public",
            )
            await broadcaster.broadcast_json(game_phase_changed(resolution.transition))
            if resolution.transition.phase_state == "sheriff_election_ready":
                await self._day.run_pre_dawn_sheriff_election(
                    game_id=game_id,
                    broadcaster=broadcaster,
                )
                dawn_transition = self._repository.ready_dawn_announcement(game_id=game_id)
                await broadcaster.broadcast_json(game_phase_changed(dawn_transition))
            self._repository.reveal_pending_dawn_deaths(
                game_id=game_id,
                expected_player_ids=tuple(item["player_id"] for item in resolution.deaths),
            )
            death_seats = [state.player(item["player_id"]).seat for item in resolution.deaths]
            dawn_ok = await self._actions.run_judge_speech(
                game_id=game_id,
                broadcaster=broadcaster,
                spec=V2SpeechSpec(
                    action_type="judge_dawn_announcement",
                    phase_id=f"day_{state.round_no}",
                    required_phase_state="dawn_announcement_ready",
                    objective=(
                        "播报天亮结果：昨夜平安夜，不得提及任何私密原因"
                        if not death_seats
                        else "播报天亮结果，只公布昨夜死亡玩家座位号，不得说明死亡原因："
                        + "、".join(f"{seat}号" for seat in death_seats)
                    ),
                    success_live_state="ready",
                    success_phase_state="dawn_announced",
                    context={"public_death_seats": death_seats},
                ),
            )
            if not dawn_ok:
                raise V2NightError("dawn_announcement_failed")
            await broadcaster.broadcast_json(
                public_dawn_result(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    dead_player_ids=[item["player_id"] for item in resolution.deaths],
                ),
                audience="public",
            )
            if (
                state.round_no == 1
                and bool(state.rule.get("first_night_last_words_enabled"))
                and self._repository.current_winner(game_id) is None
            ):
                await self._day.run_first_night_last_words(
                    game_id=game_id,
                    player_ids=tuple(
                        item["player_id"]
                        for item in resolution.deaths
                        if item["cause"] in {"werewolf_attack", "witch_poison"}
                    ),
                    broadcaster=broadcaster,
                )
            await broadcaster.broadcast_json(
                night_progress(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    stage="dawn_announced",
                    latest_presentation_seq=self._repository.latest_presentation_seq(game_id),
                ),
                audience="public",
            )
            resolved_hunters: set[str] = set()
            while pending_hunters := tuple(
                hunter_id
                for hunter_id in self._repository.hunter_reactions(game_id)
                if hunter_id not in resolved_hunters
            ):
                if self._repository.current_winner(
                    game_id
                ) is not None and not self._repository.hunter_settlement_can_change_winner(game_id):
                    break
                self._actions.check_cancellation(game_id)
                hunter_id = pending_hunters[0]
                resolved_hunters.add(hunter_id)
                await self._run_hunter_response(
                    state=state,
                    hunter_id=hunter_id,
                    broadcaster=broadcaster,
                )
            self._actions.check_cancellation(game_id)
            final_transition = self._repository.finish_night(game_id=game_id)
            await broadcaster.broadcast_json(game_phase_changed(final_transition))
            match = self._repository.match_state(game_id)
            await broadcaster.broadcast_json(
                match_state_changed(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    round_no=match["round_no"],
                    sheriff_player_id=match["sheriff_player_id"],
                    sheriff_badge_state=match["sheriff_badge_state"],
                    winner=match["winner"],
                )
            )
            if final_transition.phase_state == "game_completed":
                winner = match["winner"]
                if winner is None:
                    raise V2NightError("completed_night_has_no_winner")
                winner_name = "好人阵营" if winner == "villagers" else "狼人阵营"
                await self._actions.run_judge_speech(
                    game_id=game_id,
                    broadcaster=broadcaster,
                    spec=V2SpeechSpec(
                        action_type="judge_game_completed",
                        phase_id=final_transition.phase_id,
                        required_phase_state="game_completed",
                        objective=f"宣布本局结束，{winner_name}获胜",
                        success_live_state="awaiting_observation",
                        success_phase_state="game_completed",
                        context={"winner": winner, "round_no": state.round_no},
                        best_effort=True,
                    ),
                )
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        state="awaiting_observation",
                    )
                )
            return final_transition
        except V2ExecutionOwnershipLost:
            raise
        except Exception as exc:
            logger.warning(
                "Live V2 night runtime failed: %s",
                exc,
                extra={"game_id": game_id, "failure_code": str(exc)},
            )
            try:
                run_id = self._repository.fail_runtime(
                    game_id=game_id,
                    failure_code=_failure_code(exc),
                )
            except Exception:
                logger.exception("Live V2 could not persist night failure")
                return None
            await broadcaster.broadcast_json(
                live_state(
                    game_id=game_id,
                    run_id=run_id,
                    state="failed",
                    reason=_failure_code(exc),
                )
            )
            return None

    async def _run_parallel_independent_groups(
        self,
        *,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
        groups: tuple[str, ...],
    ) -> None:
        public_cutoff_record_seq = self._repository.latest_record_seq(state.game_id)
        batch = _NightParallelBatch(
            batch_id=(f"{state.window_id}:{public_cutoff_record_seq}:night_independent_decisions"),
            public_cutoff_record_seq=public_cutoff_record_seq,
            public_history=tuple(self._repository.public_history(state.game_id)),
        )
        prepared: dict[str, _PreparedRoleDecision] = {}
        if "guard" in groups:
            prepared["guard"] = self._prepare_guard_decision(state)
        if "seer" in groups:
            prepared["seer"] = self._prepare_seer_decision(state)
        self._repository.append_event(
            game_id=state.game_id,
            event_type="night_parallel_batch_started",
            audience="god_view",
            payload={
                "round_no": state.round_no,
                "window_id": state.window_id,
                "batch_id": batch.batch_id,
                "public_cutoff_record_seq": batch.public_cutoff_record_seq,
                "groups": list(groups),
                "commit_order": list(groups),
            },
        )

        tasks: dict[str, asyncio.Task[Any]] = {}
        prefetch_started: list[asyncio.Event] = []
        for group in ("guard", "seer"):
            if group in prepared:
                request_started = asyncio.Event() if prepared[group].skip_reason is None else None
                if request_started is not None:
                    prefetch_started.append(request_started)
                tasks[group] = asyncio.create_task(
                    self._request_prepared_role_decision(
                        state=state,
                        broadcaster=broadcaster,
                        prepared=prepared[group],
                        batch=batch,
                        concurrent_initial=True,
                        request_started=request_started,
                    )
                )
        try:
            if prefetch_started:
                await asyncio.gather(*(event.wait() for event in prefetch_started))
            if "werewolves" in groups:
                tasks["werewolves"] = asyncio.create_task(
                    self._run_werewolves(
                        state,
                        broadcaster,
                        working,
                        batch=batch,
                    )
                )
            await asyncio.gather(*tasks.values())
        except BaseException:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            try:
                self._repository.cancel_open_activations(
                    state=state,
                    reason="night_parallel_batch_canceled",
                    audience="god_view",
                    batch_id=batch.batch_id,
                    groups=groups,
                )
            except Exception:
                logger.exception("Live V2 could not persist night batch cancellation")
            try:
                await asyncio.gather(*tasks.values(), return_exceptions=True)
            except BaseException:
                pass
            raise

        buffered = {
            group: task.result() for group, task in tasks.items() if group in {"guard", "seer"}
        }
        failed_groups = [
            group
            for group in ("guard", "seer")
            if group in buffered
            and buffered[group].prepared.skip_reason is None
            and buffered[group].decision is None
        ]
        if failed_groups:
            self._repository.append_event(
                game_id=state.game_id,
                event_type="night_parallel_batch_recovery_started",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "window_id": state.window_id,
                    "batch_id": batch.batch_id,
                    "failed_groups": failed_groups,
                },
            )
            for group in failed_groups:
                self._actions.check_cancellation(state.game_id)
                previous = buffered[group]
                recovered = await self._request_prepared_role_decision(
                    state=state,
                    broadcaster=broadcaster,
                    prepared=previous.prepared,
                    batch=batch,
                    concurrent_initial=False,
                    activation=previous.activation,
                )
                if recovered.decision is None:
                    raise V2NightError(f"{recovered.prepared.ability_id}_decision_failed")
                buffered[group] = recovered
            self._repository.append_event(
                game_id=state.game_id,
                event_type="night_parallel_batch_recovery_completed",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "window_id": state.window_id,
                    "batch_id": batch.batch_id,
                    "recovered_groups": failed_groups,
                },
            )

        if "werewolves" in groups:
            await self._broadcast_night_actions_progress(state, broadcaster)
        if "guard" in buffered:
            await self._commit_guard_decision(
                state=state,
                broadcaster=broadcaster,
                working=working,
                buffered=buffered["guard"],
                present_wake=True,
            )
            await self._broadcast_night_actions_progress(state, broadcaster)
        if "seer" in buffered:
            await self._commit_seer_decision(
                state=state,
                broadcaster=broadcaster,
                buffered=buffered["seer"],
                present_wake=True,
            )
            await self._broadcast_night_actions_progress(state, broadcaster)

        self._repository.append_event(
            game_id=state.game_id,
            event_type="night_parallel_batch_resolved",
            audience="god_view",
            payload={
                "round_no": state.round_no,
                "window_id": state.window_id,
                "batch_id": batch.batch_id,
                "public_cutoff_record_seq": batch.public_cutoff_record_seq,
                "lanes": [
                    {
                        "group": group,
                        "status": (
                            "skipped"
                            if group in buffered
                            and buffered[group].prepared.skip_reason is not None
                            else "completed"
                        ),
                        "activation_id": (
                            buffered[group].activation.activation_id
                            if group in buffered and buffered[group].activation is not None
                            else None
                        ),
                    }
                    for group in groups
                ],
                "commit_order": list(groups),
            },
        )

    async def _broadcast_night_actions_progress(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
    ) -> None:
        await broadcaster.broadcast_json(
            night_progress(
                game_id=state.game_id,
                run_id=state.run_id,
                stage="actions_in_progress",
                latest_presentation_seq=self._repository.latest_presentation_seq(state.game_id),
            ),
            audience="public",
        )

    async def _run_werewolves(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
        *,
        batch: _NightParallelBatch | None = None,
    ) -> None:
        ability_id = "werewolf.attack"
        policy = _werewolf_attack_policy(state)
        allow_no_attack = policy["allow_no_attack"] is True
        allow_wolf_target = policy["allow_wolf_target"] is True
        living_wolves = sorted(
            (player for player in state.players if player.alive and player.role_key == "werewolf"),
            key=lambda player: player.seat,
        )
        wolves = _rotating_werewolf_order(state, living_wolves)
        candidates = [
            player
            for player in state.players
            if player.alive and (allow_wolf_target or player.role_key != "werewolf")
        ]
        if not wolves or not candidates:
            self._repository.skip_activation(
                state=state,
                ability_id=ability_id,
                audience="god_view",
                reason="no_eligible_actor_or_target",
            )
            return
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="werewolf_attack_wake",
            objective=(
                "唤醒本局唯一狼人并请其选择袭击目标"
                if len(wolves) == 1
                else "唤醒狼人团队；先分别盲选刀口，出现分歧后再进行狼人私聊归票"
            ),
            context={"ability_id": ability_id, "werewolf_attack_policy": policy},
        )
        occurrence = 0
        blind_choices: list[dict[str, Any]] = []
        proposal_items: list[tuple[V2NightPlayer, V2ActivationRef, V2ModelDecision | None]] = []

        if len(wolves) > 1:
            proposal_batch_id = f"{state.window_id}:werewolf_attack:preference_probe"
            prepared: list[tuple[V2NightPlayer, V2ActivationRef]] = []
            for wolf in wolves:
                occurrence += 1
                prepared.append(
                    (
                        wolf,
                        self._repository.open_activation(
                            state=state,
                            ability_id=ability_id,
                            audience="god_view",
                            actor_player_id=wolf.player_id,
                            occurrence=occurrence,
                        ),
                    )
                )

            async def request_preference(
                wolf: V2NightPlayer,
                activation: V2ActivationRef,
            ) -> V2ModelDecision | None:
                return await self._player_decision(
                    state=state,
                    broadcaster=broadcaster,
                    activation=activation,
                    player=wolf,
                    candidates=candidates,
                    objective="独立盲选本夜初步袭击目标，并用 decision_note 记录一句简短理由。",
                    knowledge={
                        "werewolf_teammates": [
                            item.player_id for item in wolves if item.player_id != wolf.player_id
                        ],
                        "coordination": "parallel_preference_probe",
                        "decision_stage": "preference_probe",
                        "proposal_visibility": "targets_shared_only_after_disagreement",
                        "decision_note_visibility": "actor_only",
                        "werewolf_attack_policy": policy,
                    },
                    optional=allow_no_attack,
                    decision_contract=V2DecisionContract(
                        kind="target",
                        target_mode="optional" if allow_no_attack else "required",
                        speech_mode="forbidden",
                        decision_note_mode="optional",
                        decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
                    ),
                    defer_presentation=True,
                    isolated_failure=True,
                    allow_failure=True,
                    batch_id=proposal_batch_id,
                    batch=batch,
                )

            decisions = await asyncio.gather(
                *(request_preference(wolf, activation) for wolf, activation in prepared)
            )
            proposal_items = [
                (wolf, activation, decision)
                for (wolf, activation), decision in zip(prepared, decisions, strict=True)
            ]
            for wolf, _activation, decision in proposal_items:
                blind_choices.append(
                    {
                        "player_id": wolf.player_id,
                        "target_player_id": (
                            decision.target_player_id if decision is not None else None
                        ),
                        "status": "completed" if decision is not None else "failed",
                    }
                )

        complete_unanimous_proposal = (
            len(wolves) > 1
            and len(proposal_items) == len(wolves)
            and all(decision is not None for _wolf, _activation, decision in proposal_items)
            and len(
                {
                    decision.target_player_id
                    for _wolf, _activation, decision in proposal_items
                    if decision is not None
                }
            )
            == 1
        )
        for wolf, activation, decision in proposal_items:
            self._repository.complete_activation(
                state=state,
                activation=activation,
                decision={
                    "decision_stage": "preference_probe",
                    "player_id": wolf.player_id,
                    "target_player_id": (
                        decision.target_player_id if decision is not None else None
                    ),
                    "decision_note": decision.decision_note if decision is not None else None,
                },
                result={
                    "adopted": complete_unanimous_proposal,
                    "decision_stage": "preference_probe",
                    "status": "completed" if decision is not None else "failed",
                },
            )
            await broadcaster.broadcast_json(
                ability_progress(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    ability_id=ability_id,
                    status="preference_committed",
                    actor_player_id=wolf.player_id,
                    target_player_id=(decision.target_player_id if decision is not None else None),
                    round_no=1,
                ),
                audience="god_view",
            )

        second_round: list[dict[str, Any]] = []
        final_items: list[tuple[V2NightPlayer, V2ActivationRef, V2ModelDecision]] = []
        if complete_unanimous_proposal:
            unanimous = proposal_items[0][2]
            assert unanimous is not None
            resolution = _WerewolfAttackResolution(
                target_player_id=unanimous.target_player_id,
                reason=(
                    "blind_choice_unanimous_no_attack"
                    if unanimous.target_player_id is None
                    else "blind_choice_unanimous"
                ),
            )
            votes = [
                (wolf.player_id, decision.target_player_id)
                for wolf, _activation, decision in proposal_items
                if decision is not None
            ]
            resolution_stage = "blind_choice_consensus"
        else:
            for position, wolf in enumerate(wolves, start=1):
                occurrence += 1
                activation = self._repository.open_activation(
                    state=state,
                    ability_id=ability_id,
                    audience="god_view",
                    actor_player_id=wolf.player_id,
                    occurrence=occurrence,
                )
                decision = await self._player_decision(
                    state=state,
                    broadcaster=broadcaster,
                    activation=activation,
                    player=wolf,
                    candidates=candidates,
                    objective=(
                        "提交本夜最终袭击选择。"
                        if len(wolves) == 1
                        else (
                            "刀口出现分歧；查看全体狼人的盲选刀口和你自己的盲选理由，"
                            "重新选择刀口，并在狼人私聊中用一句话说明理由。"
                        )
                    ),
                    knowledge=(
                        {
                            "living_werewolf_teammates": [],
                            "coordination": "solo",
                            "decision_stage": "sequential_final_vote",
                            "werewolf_attack_policy": policy,
                        }
                        if len(wolves) == 1
                        else {
                            "werewolf_teammates": [
                                item.player_id
                                for item in wolves
                                if item.player_id != wolf.player_id
                            ],
                            "coordination": "sequential_shared_discussion",
                            "decision_stage": "sequential_final_vote",
                            "werewolf_first_round": [dict(item) for item in blind_choices],
                            "blind_choice_reason_visibility": "own_declared_reason_only",
                            "werewolf_second_round_so_far": [dict(item) for item in second_round],
                            "speaking_order": [item.player_id for item in wolves],
                            "speaking_position": position,
                            "werewolf_attack_policy": policy,
                        }
                    ),
                    optional=allow_no_attack,
                    batch=batch,
                )
                assert decision is not None
                final_items.append((wolf, activation, decision))
                second_round.append(
                    {
                        "player_id": wolf.player_id,
                        "target_player_id": decision.target_player_id,
                        "speech": decision.speech,
                        "speaking_position": position,
                    }
                )

            votes = [
                (wolf.player_id, decision.target_player_id)
                for wolf, _activation, decision in final_items
            ]
            resolution = _resolve_werewolf_attack(
                state=state,
                wolves=wolves,
                votes=votes,
                policy=policy,
            )
            resolution_stage = "sequential_final_vote"

            if resolution.reason == "explicit_rotating_tiebreak_required":
                tiebreaker = _rotating_werewolf_tiebreaker(state, wolves)
                tied_targets = list(resolution.tied_target_player_ids)
                occurrence += 1
                tiebreak_activation = self._repository.open_activation(
                    state=state,
                    ability_id=ability_id,
                    audience="god_view",
                    actor_player_id=tiebreaker.player_id,
                    occurrence=occurrence,
                )
                tiebreak_decision = await self._player_decision(
                    state=state,
                    broadcaster=broadcaster,
                    activation=tiebreak_activation,
                    player=tiebreaker,
                    candidates=[
                        state.player(target) for target in tied_targets if target is not None
                    ],
                    objective="提交本夜平票裁决选择。",
                    knowledge={
                        "werewolf_teammates": [
                            item.player_id
                            for item in wolves
                            if item.player_id != tiebreaker.player_id
                        ],
                        "coordination": "explicit_rotating_tiebreak",
                        "decision_stage": "tiebreak",
                        "werewolf_first_round": [dict(item) for item in blind_choices],
                        "werewolf_second_round": [dict(item) for item in second_round],
                        "werewolf_final_votes": [
                            {
                                "player_id": player_id,
                                "target_player_id": target_player_id,
                            }
                            for player_id, target_player_id in votes
                        ],
                        "tied_target_player_ids": list(tied_targets),
                        "werewolf_attack_policy": policy,
                    },
                    optional=None in tied_targets,
                    batch=batch,
                )
                assert tiebreak_decision is not None
                resolution = _WerewolfAttackResolution(
                    target_player_id=tiebreak_decision.target_player_id,
                    reason=(
                        "explicit_rotating_tiebreak_no_attack"
                        if tiebreak_decision.target_player_id is None
                        else "explicit_rotating_tiebreak"
                    ),
                    tiebreaker_player_id=tiebreaker.player_id,
                )
                resolution_stage = "tiebreak"
                self._repository.complete_activation(
                    state=state,
                    activation=tiebreak_activation,
                    decision={
                        "decision_stage": "tiebreak",
                        "target_player_id": tiebreak_decision.target_player_id,
                        "speech": tiebreak_decision.speech,
                    },
                    result={
                        "adopted": True,
                        "decision_stage": "tiebreak",
                        "final_target_player_id": resolution.target_player_id,
                        "resolution_reason": resolution.reason,
                    },
                )

        for wolf, activation, decision in final_items:
            self._repository.complete_activation(
                state=state,
                activation=activation,
                decision={
                    "decision_stage": "sequential_final_vote",
                    "target_player_id": decision.target_player_id,
                    "speech": decision.speech,
                },
                result={
                    "adopted": decision.target_player_id == resolution.target_player_id,
                    "decision_stage": "sequential_final_vote",
                    "final_target_player_id": resolution.target_player_id,
                    "resolution_reason": resolution.reason,
                    "tiebreaker_player_id": resolution.tiebreaker_player_id,
                },
            )
            await broadcaster.broadcast_json(
                ability_progress(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    ability_id=ability_id,
                    status="final_vote_committed",
                    actor_player_id=wolf.player_id,
                    target_player_id=decision.target_player_id,
                    round_no=2 if len(wolves) > 1 else 1,
                ),
                audience="god_view",
            )

        occurrence += 1
        resolution_activation = self._repository.open_activation(
            state=state,
            ability_id=ability_id,
            audience="god_view",
            actor_player_id=None,
            occurrence=occurrence,
        )
        resolution_knowledge = tuple(
            (
                "player",
                wolf.player_id,
                fact,
            )
            for wolf in wolves
            for fact in (
                {
                    "fact_type": "werewolf_attack_resolved",
                    "payload": {
                        "night_no": state.round_no,
                        "final_target_player_id": resolution.target_player_id,
                        "resolution_reason": resolution.reason,
                        "resolution_stage": resolution_stage,
                        "tiebreaker_player_id": resolution.tiebreaker_player_id,
                    },
                },
                {
                    "fact_type": "private_ability_action_committed",
                    "payload": {
                        "ability_id": ability_id,
                        "night_no": state.round_no,
                        "decision": {
                            "decision_stage": "team_resolution",
                            "final_target_player_id": resolution.target_player_id,
                        },
                        "result": {
                            "resolution_reason": resolution.reason,
                            "resolution_stage": resolution_stage,
                        },
                        "resolution_scope": (
                            "法官已接受本次私有动作；这里只记录狼队共同结算结果，"
                            "不向普通玩家公开刀口或票型。"
                        ),
                    },
                },
            )
        )
        self._repository.complete_activation(
            state=state,
            activation=resolution_activation,
            decision={
                "decision_stage": "team_resolution",
                "resolution_stage": resolution_stage,
                "votes": [
                    {
                        "player_id": player_id,
                        "target_player_id": target_player_id,
                    }
                    for player_id, target_player_id in votes
                ],
            },
            result={
                "final_target_player_id": resolution.target_player_id,
                "resolution_reason": resolution.reason,
                "tiebreaker_player_id": resolution.tiebreaker_player_id,
            },
            effect_type=("attack" if resolution.target_player_id is not None else None),
            target_player_id=resolution.target_player_id,
            knowledge=resolution_knowledge,
        )

        working.attack_target = resolution.target_player_id
        await broadcaster.broadcast_json(
            ability_progress(
                game_id=state.game_id,
                run_id=state.run_id,
                ability_id=ability_id,
                status=("completed" if resolution.target_player_id is not None else "no_attack"),
                actor_player_id=(
                    resolution.tiebreaker_player_id or resolution_activation.actor_player_id
                ),
                target_player_id=resolution.target_player_id,
            ),
            audience="god_view",
        )
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="werewolf_attack_sleep",
            objective="宣布狼人行动结束并请狼人闭眼，不公开目标",
            context={
                "ability_id": ability_id,
                "resolution_reason": resolution.reason,
            },
        )

    async def _run_guard(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
    ) -> None:
        prepared = self._prepare_guard_decision(state)
        if prepared.skip_reason is None:
            await self._private_judge(
                state=state,
                broadcaster=broadcaster,
                action_type="guard_protect_wake",
                objective="唤醒守卫并请其选择今晚守护的存活玩家",
                context={"ability_id": prepared.ability_id, "night_no": state.round_no},
            )
        buffered = await self._request_prepared_role_decision(
            state=state,
            broadcaster=broadcaster,
            prepared=prepared,
            batch=None,
            concurrent_initial=False,
        )
        await self._commit_guard_decision(
            state=state,
            broadcaster=broadcaster,
            working=working,
            buffered=buffered,
            present_wake=False,
        )

    def _prepare_guard_decision(self, state: V2NightRuntimeState) -> _PreparedRoleDecision:
        ability_id = "guard.protect"
        guard = _single_owner(state, "guard")
        if guard is None or not guard.alive:
            return _PreparedRoleDecision(
                group="guard",
                ability_id=ability_id,
                player=guard,
                candidates=(),
                objective="选择今晚的守护目标。",
                knowledge={},
                optional=False,
                skip_reason="owner_not_alive",
            )
        guard_state = self._repository.ability_state(
            game_id=state.game_id,
            ability_id=ability_id,
        )
        previous_target = guard_state.get("previous_target_player_id")
        candidates = [
            player
            for player in state.players
            if player.alive and (state.round_no == 1 or player.player_id != previous_target)
        ]
        return _PreparedRoleDecision(
            group="guard",
            ability_id=ability_id,
            player=guard,
            candidates=tuple(candidates),
            objective="选择今晚的守护目标。",
            knowledge={
                "night_no": state.round_no,
                "previous_protected_target": previous_target,
            },
            optional=False,
        )

    async def _request_prepared_role_decision(
        self,
        *,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        prepared: _PreparedRoleDecision,
        batch: _NightParallelBatch | None,
        concurrent_initial: bool,
        activation: V2ActivationRef | None = None,
        request_started: asyncio.Event | None = None,
    ) -> _BufferedRoleDecision:
        if prepared.skip_reason is not None:
            return _BufferedRoleDecision(prepared=prepared, activation=None, decision=None)
        if prepared.player is None:
            raise V2NightError(f"{prepared.ability_id}_owner_missing")
        if request_started is not None:
            request_started.set()
        current_activation = activation or self._repository.open_activation(
            state=state,
            ability_id=prepared.ability_id,
            audience="god_view",
            actor_player_id=prepared.player.player_id,
            occurrence=1,
        )
        try:
            decision = await self._player_decision(
                state=state,
                broadcaster=broadcaster,
                activation=current_activation,
                player=prepared.player,
                candidates=list(prepared.candidates),
                objective=prepared.objective,
                knowledge=prepared.knowledge,
                optional=prepared.optional,
                defer_presentation=concurrent_initial,
                isolated_failure=concurrent_initial,
                allow_failure=concurrent_initial,
                batch_id=batch.batch_id if batch is not None else None,
                batch=batch,
                batch_stage=("concurrent_initial" if concurrent_initial else "sequential_recovery"),
            )
        except asyncio.CancelledError:
            if concurrent_initial:
                self._repository.cancel_open_activation(
                    state=state,
                    activation=current_activation,
                    reason="night_parallel_batch_canceled",
                    batch_id=batch.batch_id if batch is not None else None,
                    group=prepared.group if batch is not None else None,
                )
            raise
        return _BufferedRoleDecision(
            prepared=prepared,
            activation=current_activation,
            decision=decision,
        )

    async def _commit_guard_decision(
        self,
        *,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
        buffered: _BufferedRoleDecision,
        present_wake: bool,
    ) -> None:
        prepared = buffered.prepared
        if prepared.skip_reason is not None:
            self._repository.skip_activation(
                state=state,
                ability_id=prepared.ability_id,
                audience="god_view",
                reason=prepared.skip_reason,
            )
            return
        if buffered.activation is None or buffered.decision is None or prepared.player is None:
            raise V2NightError(f"{prepared.ability_id}_decision_incomplete")
        if present_wake:
            await self._private_judge(
                state=state,
                broadcaster=broadcaster,
                action_type="guard_protect_wake",
                objective="唤醒守卫并请其选择今晚守护的存活玩家",
                context={"ability_id": prepared.ability_id, "night_no": state.round_no},
            )
        decision = buffered.decision
        working.protected_target = decision.target_player_id
        self._repository.complete_activation(
            state=state,
            activation=buffered.activation,
            decision=_private_decision_record(decision),
            result={"effect": "protect_registered"},
            effect_type="protect",
            target_player_id=decision.target_player_id,
            ability_state_patch={"previous_target_player_id": decision.target_player_id},
        )
        await self._ability_completed(
            state,
            broadcaster,
            prepared.ability_id,
            prepared.player,
            decision,
        )
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="guard_protect_sleep",
            objective="宣布守卫行动结束并请守卫闭眼，不公开守护目标",
            context={"ability_id": prepared.ability_id},
        )

    async def _run_seer(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
    ) -> None:
        del working
        prepared = self._prepare_seer_decision(state)
        if prepared.skip_reason is None:
            await self._private_judge(
                state=state,
                broadcaster=broadcaster,
                action_type="seer_investigate_wake",
                objective="唤醒预言家并请其选择今晚查验的一名其他存活玩家",
                context={"ability_id": prepared.ability_id},
            )
        buffered = await self._request_prepared_role_decision(
            state=state,
            broadcaster=broadcaster,
            prepared=prepared,
            batch=None,
            concurrent_initial=False,
        )
        await self._commit_seer_decision(
            state=state,
            broadcaster=broadcaster,
            buffered=buffered,
            present_wake=False,
        )

    def _prepare_seer_decision(self, state: V2NightRuntimeState) -> _PreparedRoleDecision:
        ability_id = "seer.investigate"
        seer = _single_owner(state, "seer")
        if seer is None or not seer.alive:
            return _PreparedRoleDecision(
                group="seer",
                ability_id=ability_id,
                player=seer,
                candidates=(),
                objective="选择今晚的查验目标。",
                knowledge={},
                optional=False,
                skip_reason="owner_not_alive",
            )
        candidates = [
            player
            for player in state.players
            if player.alive and player.player_id != seer.player_id
        ]
        return _PreparedRoleDecision(
            group="seer",
            ability_id=ability_id,
            player=seer,
            candidates=tuple(candidates),
            objective="选择今晚的查验目标。",
            knowledge={
                "known_investigations": self._repository.player_knowledge(
                    game_id=state.game_id,
                    player_id=seer.player_id,
                )
            },
            optional=False,
        )

    async def _commit_seer_decision(
        self,
        *,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        buffered: _BufferedRoleDecision,
        present_wake: bool,
    ) -> None:
        prepared = buffered.prepared
        if prepared.skip_reason is not None:
            self._repository.skip_activation(
                state=state,
                ability_id=prepared.ability_id,
                audience="god_view",
                reason=prepared.skip_reason,
            )
            return
        if buffered.activation is None or buffered.decision is None or prepared.player is None:
            raise V2NightError(f"{prepared.ability_id}_decision_incomplete")
        if present_wake:
            await self._private_judge(
                state=state,
                broadcaster=broadcaster,
                action_type="seer_investigate_wake",
                objective="唤醒预言家并请其选择今晚查验的一名其他存活玩家",
                context={"ability_id": prepared.ability_id},
            )
        decision = buffered.decision
        target = state.player(_required_target(decision))
        alignment = "werewolves" if target.role_key == "werewolf" else "villagers"
        self._repository.complete_activation(
            state=state,
            activation=buffered.activation,
            decision=_private_decision_record(
                decision,
                target_player_id=target.player_id,
            ),
            result={"alignment": alignment},
            effect_type="investigate",
            target_player_id=target.player_id,
            knowledge=(
                (
                    "player",
                    prepared.player.player_id,
                    {
                        "fact_type": "investigation_alignment",
                        "payload": {
                            "target_player_id": target.player_id,
                            "alignment": alignment,
                            "night_no": state.round_no,
                        },
                    },
                ),
            ),
        )
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="seer_investigate_result",
            objective=(
                f"只向预言家确认{target.seat}号的查验阵营是"
                f"{'狼人阵营' if alignment == 'werewolves' else '好人阵营'}"
            ),
            context={
                "ability_id": prepared.ability_id,
                "target_player_id": target.player_id,
                "target_player_seat": target.seat,
                "alignment": alignment,
            },
        )
        await self._ability_completed(
            state,
            broadcaster,
            prepared.ability_id,
            prepared.player,
            decision,
        )
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="seer_investigate_sleep",
            objective="宣布预言家行动结束并请预言家闭眼",
            context={"ability_id": prepared.ability_id},
        )

    async def _run_witch(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
    ) -> None:
        witch = _single_owner(state, "witch")
        configured = {
            item["ability_id"]
            for item in state.snapshot["instances"]
            if item["activation_group"] == "witch"
        }
        if witch is None or not witch.alive:
            for ability_id in sorted(configured):
                self._repository.skip_activation(
                    state=state,
                    ability_id=ability_id,
                    audience="god_view",
                    reason="owner_not_alive",
                )
                await broadcaster.broadcast_json(
                    ability_progress(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        ability_id=ability_id,
                        status="skipped",
                        actor_player_id=witch.player_id if witch is not None else None,
                    ),
                    audience="god_view",
                )
            return
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="witch_wake",
            objective=f"唤醒女巫并进入第{state.round_no}夜用药决策",
            context={"configured_abilities": sorted(configured)},
        )
        attacked = state.player(working.attack_target) if working.attack_target else None
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="witch_attack_observation",
            objective=(
                "只向女巫说明今晚目前没有狼人袭击目标"
                if attacked is None
                else f"只向女巫说明今晚被狼人袭击的是{attacked.seat}号"
            ),
            context={
                "attacked_player_id": working.attack_target,
                "attacked_player_seat": attacked.seat if attacked is not None else None,
            },
        )
        self._repository.record_player_knowledge(
            game_id=state.game_id,
            player_id=witch.player_id,
            fact_type="witch_attack_observation",
            payload={
                "night_no": state.round_no,
                "attacked_player_id": working.attack_target,
                "attacked_player_seat": attacked.seat if attacked is not None else None,
            },
        )
        heal_used = False
        heal_state = self._repository.ability_state(
            game_id=state.game_id,
            ability_id="witch.heal",
        )
        if "witch.heal" in configured:
            if not heal_state.get("available", True):
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.heal",
                    audience="god_view",
                    reason="heal_already_used",
                )
                await self._ability_status(state, broadcaster, "witch.heal", witch, "unavailable")
            elif attacked is None:
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.heal",
                    audience="god_view",
                    reason="no_provisional_attack",
                )
                await self._ability_status(state, broadcaster, "witch.heal", witch, "unavailable")
            elif attacked.player_id == witch.player_id and state.round_no > 1:
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.heal",
                    audience="god_view",
                    reason="self_heal_only_allowed_first_night",
                )
                await self._ability_status(state, broadcaster, "witch.heal", witch, "unavailable")
            else:
                activation = self._repository.open_activation(
                    state=state,
                    ability_id="witch.heal",
                    audience="god_view",
                    actor_player_id=witch.player_id,
                    occurrence=1,
                )
                decision = await self._player_decision(
                    state=state,
                    broadcaster=broadcaster,
                    activation=activation,
                    player=witch,
                    candidates=[attacked],
                    objective="决定是否使用解药。",
                    knowledge={
                        "attacked_player_id": attacked.player_id,
                        "heal_remaining": int(heal_state.get("remaining", 1)),
                        "self_heal_allowed": state.round_no == 1,
                    },
                    optional=True,
                )
                heal_used = decision.target_player_id is not None
                working.healed_target = decision.target_player_id
                self._repository.complete_activation(
                    state=state,
                    activation=activation,
                    decision=_private_decision_record(decision),
                    result={
                        "heal_used": heal_used,
                        "decision_status": "used" if heal_used else "declined",
                    },
                    effect_type="heal" if heal_used else None,
                    target_player_id=decision.target_player_id,
                    ability_state_patch=(
                        {"available": False, "remaining": 0} if heal_used else None
                    ),
                )
                await self._ability_completed(
                    state,
                    broadcaster,
                    "witch.heal",
                    witch,
                    decision,
                    status="used" if heal_used else "declined",
                )
        poison_state = self._repository.ability_state(
            game_id=state.game_id,
            ability_id="witch.poison",
        )
        if "witch.poison" in configured:
            if not poison_state.get("available", True):
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.poison",
                    audience="god_view",
                    reason="poison_already_used",
                )
                await self._ability_status(state, broadcaster, "witch.poison", witch, "unavailable")
            elif heal_used:
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.poison",
                    audience="god_view",
                    reason="heal_poison_mutually_exclusive",
                )
                await self._ability_status(state, broadcaster, "witch.poison", witch, "unavailable")
            else:
                poison_candidates = [
                    player
                    for player in state.players
                    if player.alive
                    and player.player_id != witch.player_id
                    and player.player_id != working.attack_target
                ]
                if not poison_candidates:
                    self._repository.skip_activation(
                        state=state,
                        ability_id="witch.poison",
                        audience="god_view",
                        reason="no_eligible_target",
                    )
                    await self._ability_status(
                        state, broadcaster, "witch.poison", witch, "unavailable"
                    )
                else:
                    activation = self._repository.open_activation(
                        state=state,
                        ability_id="witch.poison",
                        audience="god_view",
                        actor_player_id=witch.player_id,
                        occurrence=1,
                    )
                    decision = await self._player_decision(
                        state=state,
                        broadcaster=broadcaster,
                        activation=activation,
                        player=witch,
                        candidates=poison_candidates,
                        objective="决定是否使用毒药；使用时选择目标。",
                        knowledge={
                            "poison_remaining": int(poison_state.get("remaining", 1)),
                            "excluded_player_ids": [
                                item
                                for item in (witch.player_id, working.attack_target)
                                if item is not None
                            ],
                        },
                        optional=True,
                    )
                    poison_used = decision.target_player_id is not None
                    working.poisoned_target = decision.target_player_id
                    self._repository.complete_activation(
                        state=state,
                        activation=activation,
                        decision=_private_decision_record(decision),
                        result={
                            "poison_used": poison_used,
                            "decision_status": "used" if poison_used else "declined",
                        },
                        effect_type="poison" if poison_used else None,
                        target_player_id=decision.target_player_id,
                        ability_state_patch=(
                            {"available": False, "remaining": 0} if poison_used else None
                        ),
                    )
                    await self._ability_completed(
                        state,
                        broadcaster,
                        "witch.poison",
                        witch,
                        decision,
                        status="used" if poison_used else "declined",
                    )
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="witch_sleep",
            objective="宣布女巫行动结束并请女巫闭眼",
            context={"configured_abilities": sorted(configured)},
        )

    async def _run_hunter_response(
        self,
        *,
        state: V2NightRuntimeState,
        hunter_id: str,
        broadcaster: V2BroadcastPort,
    ) -> None:
        reaction_state = self._repository.open_dawn_reaction_window(state=state)
        players = self._repository.current_players(state.game_id)
        hunter = next(item for item in players if item.player_id == hunter_id)
        candidates = [item for item in players if item.alive and item.player_id != hunter_id]
        activation = self._repository.open_activation(
            state=reaction_state,
            ability_id="hunter.death_shot",
            audience="god_view",
            actor_player_id=hunter_id,
            occurrence=1,
        )
        decision = await self._player_decision(
            state=reaction_state,
            broadcaster=broadcaster,
            activation=activation,
            player=hunter,
            candidates=candidates,
            objective="决定是否发动猎人技能；发动时选择目标。",
            knowledge={"death_cause_allows_shot": True},
            optional=True,
            audience="god_view",
        )
        self._repository.complete_activation(
            state=reaction_state,
            activation=activation,
            decision=_private_decision_record(decision),
            result={"shot_used": decision.target_player_id is not None},
            effect_type="shoot" if decision.target_player_id else None,
            target_player_id=decision.target_player_id,
        )
        await self._ability_completed(
            reaction_state,
            broadcaster,
            "hunter.death_shot",
            hunter,
            decision,
        )
        if decision.target_player_id is not None:
            target = next(
                item for item in candidates if item.player_id == decision.target_player_id
            )
            self._repository.apply_hunter_shot(
                state=reaction_state,
                activation_id=activation.activation_id,
                hunter_player_id=hunter_id,
                target_player_id=target.player_id,
            )
            await broadcaster.broadcast_json(
                god_view_night_resolution(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    deaths=[{"player_id": target.player_id, "cause": "hunter_shot"}],
                    attack_prevented_by=None,
                ),
                audience="god_view",
            )
            ok = await self._actions.run_judge_speech(
                game_id=state.game_id,
                broadcaster=broadcaster,
                spec=V2SpeechSpec(
                    action_type="judge_hunter_shot_announcement",
                    phase_id=f"day_{state.round_no}",
                    required_phase_state="dawn_reactions_ready",
                    objective=f"公开播报猎人带走了{target.seat}号",
                    success_live_state="ready",
                    success_phase_state="dawn_reactions_ready",
                    context={
                        "target_player_id": target.player_id,
                        "target_player_seat": target.seat,
                    },
                ),
            )
            if not ok:
                raise V2NightError("hunter_announcement_failed")
            await broadcaster.broadcast_json(
                public_dawn_result(
                    game_id=state.game_id,
                    run_id=state.run_id,
                    dead_player_ids=[target.player_id],
                ),
                audience="public",
            )
        else:
            self._repository.mark_hunter_response_resolved(
                state=reaction_state,
                hunter_player_id=hunter_id,
            )

    async def _private_judge(
        self,
        *,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        action_type: str,
        objective: str,
        context: dict[str, Any],
    ) -> None:
        ok = await self._actions.run_judge_speech(
            game_id=state.game_id,
            broadcaster=broadcaster,
            spec=V2SpeechSpec(
                action_type=action_type,
                phase_id=state.phase_id,
                required_phase_state="night_running",
                objective=objective,
                success_live_state="ready",
                success_phase_state="night_running",
                audience="god_view",
                output_kind="private_speech",
                context=context,
            ),
        )
        if not ok:
            raise V2NightError(f"{action_type}_failed")

    async def _player_decision(
        self,
        *,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        activation: V2ActivationRef,
        player: V2NightPlayer,
        candidates: list[V2NightPlayer],
        objective: str,
        knowledge: dict[str, Any],
        optional: bool,
        audience: str = "god_view",
        defer_presentation: bool = False,
        isolated_failure: bool = False,
        allow_failure: bool = False,
        batch_id: str | None = None,
        batch: _NightParallelBatch | None = None,
        batch_stage: str | None = None,
        decision_contract: V2DecisionContract | None = None,
    ) -> V2ModelDecision | None:
        knowledge_fact_ids, knowledge_hash = self._repository.register_activation_knowledge(
            state=state,
            activation=activation,
            owner_player_id=player.player_id,
            allowed_knowledge=knowledge,
        )
        historical_private_facts = self._repository.player_knowledge(
            game_id=state.game_id,
            player_id=player.player_id,
        )
        current_action_knowledge = {
            fact_type: payload
            for fact_type, payload in knowledge.items()
            if fact_type != "known_investigations"
        }
        action_type = f"ability_{activation.ability_id}_decision"
        is_dawn_reaction = activation.ability_id == "hunter.death_shot"
        resolved_decision_contract = decision_contract or V2DecisionContract(
            kind="target",
            target_mode="optional" if optional else "required",
            speech_mode=("required" if activation.ability_id == "werewolf.attack" else "forbidden"),
            speech_max_sentences=(1 if activation.ability_id == "werewolf.attack" else None),
            decision_note_mode=(
                "none" if activation.ability_id == "werewolf.attack" else "optional"
            ),
            decision_note_max_chars=_DECISION_NOTE_MAX_CHARS,
        )
        decision = await self._actions.run_player_decision(
            game_id=state.game_id,
            broadcaster=broadcaster,
            spec=V2SpeechSpec(
                action_type=action_type,
                phase_id=(f"day_{state.round_no}" if is_dawn_reaction else state.phase_id),
                required_phase_state=(
                    "dawn_reactions_ready" if is_dawn_reaction else "night_running"
                ),
                objective=objective,
                success_live_state="ready",
                success_phase_state=(
                    "dawn_reactions_ready" if is_dawn_reaction else "night_running"
                ),
                actor_kind="player",
                actor_id=player.player_id,
                audience=audience,
                speaker=player.tts_speaker,
                dialect=player.tts_dialect,
                model_provider=player.model_provider,
                model_id=player.model_id,
                model_supports_thinking=player.model_supports_thinking,
                model_parameters=player.model_parameters,
                activation_id=activation.activation_id,
                output_kind=(
                    "decision_and_speech"
                    if resolved_decision_contract.speech_mode != "forbidden"
                    else "private_decision"
                ),
                decision_contract=resolved_decision_contract,
                allowed_target_ids=tuple(item.player_id for item in candidates),
                model_players=tuple(
                    V2ModelPlayerReference(
                        player_id=item.player_id,
                        seat=item.seat,
                        display_name=item.display_name,
                    )
                    for item in state.players
                ),
                context={
                    "ability_id": activation.ability_id,
                    "ability_instance_id": activation.ability_instance_id,
                    "activation_id": activation.activation_id,
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
                        private_facts=historical_private_facts,
                        current_action_type=action_type,
                        current_action_knowledge=current_action_knowledge,
                    ),
                    "private_authoritative_facts": [
                        *private_authoritative_facts(
                            historical_private_facts,
                            owner_scope="player",
                            owner_id=player.player_id,
                        ),
                        *private_authoritative_facts(
                            current_action_knowledge,
                            owner_scope="player",
                            owner_id=player.player_id,
                        ),
                    ],
                    "public_match_state": build_public_match_state(
                        round_no=state.round_no,
                        players=state.players,
                    ),
                    "sheriff_player_id": state.sheriff_player_id,
                    "knowledge_fact_ids": list(knowledge_fact_ids),
                    "knowledge_projection_hash": knowledge_hash,
                    "candidates": [
                        {
                            "player_id": item.player_id,
                            "seat": item.seat,
                            "display_name": item.display_name,
                        }
                        for item in candidates
                    ],
                    "decision_rules": {
                        "target_optional": optional,
                        "must_choose_exact_candidate_id": True,
                    },
                    "night_no": state.round_no,
                    "public_rule_contract": build_public_rule_contract(
                        rule=state.rule,
                        max_rounds=state.max_rounds,
                    ),
                    "public_history": (
                        list(batch.public_history)
                        if batch is not None
                        else self._repository.public_history(state.game_id)
                    ),
                    **(
                        {
                            "night_parallel_batch_id": batch.batch_id,
                            "public_cutoff_record_seq": batch.public_cutoff_record_seq,
                            "night_parallel_batch_stage": batch_stage or "blocking_lane",
                        }
                        if batch is not None
                        else {}
                    ),
                },
                defer_presentation=defer_presentation,
                isolated_failure=isolated_failure,
                batch_id=batch_id or (batch.batch_id if batch is not None else None),
            ),
        )
        if decision is None and not allow_failure:
            raise V2NightError(f"{activation.ability_id}_decision_failed")
        return decision

    async def _ability_completed(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        ability_id: str,
        player: V2NightPlayer,
        decision: V2ModelDecision,
        status: str = "completed",
    ) -> None:
        await broadcaster.broadcast_json(
            ability_progress(
                game_id=state.game_id,
                run_id=state.run_id,
                ability_id=ability_id,
                status=status,
                actor_player_id=player.player_id,
                target_player_id=decision.target_player_id,
            ),
            audience="god_view",
        )

    async def _ability_status(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        ability_id: str,
        player: V2NightPlayer,
        status: str,
    ) -> None:
        await broadcaster.broadcast_json(
            ability_progress(
                game_id=state.game_id,
                run_id=state.run_id,
                ability_id=ability_id,
                status=status,
                actor_player_id=player.player_id,
            ),
            audience="god_view",
        )


def _private_decision_record(
    decision: V2ModelDecision,
    *,
    target_player_id: str | None = None,
) -> dict[str, Any]:
    return {
        "target_player_id": (
            decision.target_player_id if target_player_id is None else target_player_id
        ),
        **({"decision_note": decision.decision_note} if decision.decision_note is not None else {}),
    }


def _werewolf_attack_policy(state: V2NightRuntimeState) -> dict[str, Any]:
    policies = state.snapshot.get("policies")
    raw = policies.get("werewolf_attack") if isinstance(policies, dict) else None
    if raw is None:
        return {
            "resolution": "unanimous_no_attack",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        }
    if not isinstance(raw, dict) or set(raw) != {
        "resolution",
        "allow_no_attack",
        "allow_wolf_target",
    }:
        raise V2NightError("werewolf_attack_policy_invalid")
    resolution = raw.get("resolution")
    if (
        resolution
        not in {
            "plurality_rotating_tiebreak",
            "plurality_seeded_random",
            "unanimous_no_attack",
        }
        or not isinstance(raw.get("allow_no_attack"), bool)
        or not isinstance(raw.get("allow_wolf_target"), bool)
    ):
        raise V2NightError("werewolf_attack_policy_invalid")
    return dict(raw)


def _resolve_werewolf_attack(
    *,
    state: V2NightRuntimeState,
    wolves: list[V2NightPlayer],
    votes: list[tuple[str, str | None]],
    policy: dict[str, Any],
) -> _WerewolfAttackResolution:
    if not votes or len(votes) != len(wolves):
        raise V2NightError("werewolf_final_votes_incomplete")
    resolution = policy["resolution"]
    targets = [target_player_id for _player_id, target_player_id in votes]
    if resolution == "unanimous_no_attack":
        if len(set(targets)) != 1:
            return _WerewolfAttackResolution(
                target_player_id=None,
                reason="no_consensus_no_attack",
            )
        target = targets[0]
        return _WerewolfAttackResolution(
            target_player_id=target,
            reason="voluntary_no_attack" if target is None else "unanimous",
        )

    counts = Counter(targets)
    highest = max(counts.values())
    tied_targets = [
        target_player_id for target_player_id, count in counts.items() if count == highest
    ]
    if len(tied_targets) == 1:
        target = tied_targets[0]
        return _WerewolfAttackResolution(
            target_player_id=target,
            reason="voluntary_no_attack" if target is None else "unique_highest",
        )

    if resolution == "plurality_rotating_tiebreak":
        tiebreaker = _rotating_werewolf_tiebreaker(state, wolves)
        return _WerewolfAttackResolution(
            target_player_id=None,
            reason="explicit_rotating_tiebreak_required",
            tiebreaker_player_id=tiebreaker.player_id,
            tied_target_player_ids=tuple(tied_targets),
        )

    if resolution == "plurality_seeded_random":
        target = _seeded_tie_choice(state, tied_targets)
        return _WerewolfAttackResolution(
            target_player_id=target,
            reason="seeded_tiebreak_no_attack" if target is None else "seeded_tiebreak",
        )
    raise V2NightError("werewolf_attack_resolution_unsupported")


def _rotating_werewolf_tiebreaker(
    state: V2NightRuntimeState,
    living_wolves: list[V2NightPlayer],
) -> V2NightPlayer:
    order = _rotating_werewolf_order(state, living_wolves)
    if order:
        return order[0]
    raise V2NightError("werewolf_tiebreaker_unavailable")


def _rotating_werewolf_order(
    state: V2NightRuntimeState,
    living_wolves: list[V2NightPlayer],
) -> list[V2NightPlayer]:
    living_by_id = {wolf.player_id: wolf for wolf in living_wolves}
    state_players = getattr(state, "players", ())
    original_ids = [
        player.player_id
        for player in sorted(state_players, key=lambda player: player.seat)
        if player.role_key == "werewolf"
    ]
    if not original_ids:
        original_ids = [wolf.player_id for wolf in living_wolves]
    if not original_ids:
        return []
    start = (state.round_no - 1) % len(original_ids)
    order: list[V2NightPlayer] = []
    for offset in range(len(original_ids)):
        player_id = original_ids[(start + offset) % len(original_ids)]
        if player_id in living_by_id:
            order.append(living_by_id[player_id])
    return order


def _seeded_tie_choice(
    state: V2NightRuntimeState,
    targets: list[str | None],
) -> str | None:
    ordered = sorted(targets, key=lambda item: (item is not None, item or ""))
    seed = "|".join(
        (
            state.game_id,
            str(state.round_no),
            "werewolf_attack",
            ",".join(item or "<no_attack>" for item in ordered),
        )
    )
    digest = hashlib.sha256(seed.encode()).digest()
    return ordered[int.from_bytes(digest[:8], "big") % len(ordered)]


def _activation_groups(snapshot: dict[str, Any]) -> tuple[str, ...]:
    ordered = sorted(
        (item for item in snapshot["instances"] if item["window_type"] == "night"),
        key=lambda item: (item["order"], item["ability_instance_id"]),
    )
    groups: list[str] = []
    for item in ordered:
        group = str(item["activation_group"])
        if group not in groups:
            groups.append(group)
    return tuple(groups)


def _single_owner(state: V2NightRuntimeState, role_key: str) -> V2NightPlayer | None:
    owners = [player for player in state.players if player.role_key == role_key]
    if not owners:
        return None
    if len(owners) != 1:
        raise V2NightError(f"multiple_{role_key}_owners_not_supported")
    return owners[0]


def _required_target(decision: V2ModelDecision) -> str:
    if decision.target_player_id is None:
        raise V2NightError("required_target_missing")
    return decision.target_player_id


def _failure_code(exc: Exception) -> str:
    value = str(exc).strip()
    if not value:
        return "night_runtime_failed"
    return value[:120].replace(" ", "_")


# Compatibility name for already-written V2 tests and records. The implementation
# is round-agnostic and is used for every night.
V2FirstNightEngine = V2NightEngine
