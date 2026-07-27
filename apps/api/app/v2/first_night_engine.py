from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Awaitable, Callable

from app.v2.action_engine import (
    V2ActionEngine,
    V2BroadcastPort,
    V2SpeechSpec,
)
from app.v2.model_client import V2ModelDecision
from app.v2.model_context import V2ModelPlayerReference
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
from app.v2.repository import V2PhaseTransition


logger = logging.getLogger(__name__)


class V2NightError(RuntimeError):
    pass


@dataclass
class _WorkingNight:
    attack_target: str | None = None
    protected_target: str | None = None
    healed_target: str | None = None
    poisoned_target: str | None = None


GroupHandler = Callable[[V2NightRuntimeState, V2BroadcastPort, _WorkingNight], Awaitable[None]]


class V2NightEngine:
    def __init__(
        self,
        *,
        repository: V2NightRepository,
        action_engine: V2ActionEngine,
    ) -> None:
        self._repository = repository
        self._actions = action_engine
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
            state = self._repository.start_night(game_id)
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
            for group in groups:
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
            death_seats = [
                state.player(item["player_id"]).seat for item in resolution.deaths
            ]
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
                self._actions.check_cancellation(game_id)
                hunter_id = pending_hunters[0]
                resolved_hunters.add(hunter_id)
                await self._run_hunter_response(
                    state=state,
                    hunter_id=hunter_id,
                    broadcaster=broadcaster,
                )
            self._actions.check_cancellation(game_id)
            winner = self._repository.current_winner(game_id)
            if winner is not None:
                current_phase_state = self._repository.current_phase_state(game_id)
                winner_name = "好人阵营" if winner == "villagers" else "狼人阵营"
                completed_ok = await self._actions.run_judge_speech(
                    game_id=game_id,
                    broadcaster=broadcaster,
                    spec=V2SpeechSpec(
                        action_type="judge_game_completed",
                        phase_id=f"day_{state.round_no}",
                        required_phase_state=current_phase_state,
                        objective=f"宣布本局结束，{winner_name}获胜",
                        success_live_state="ready",
                        success_phase_state=current_phase_state,
                        context={"winner": winner, "round_no": state.round_no},
                    ),
                )
                if not completed_ok:
                    raise V2NightError("game_completed_announcement_failed")
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
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        state="awaiting_observation",
                    )
                )
            return final_transition
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

    async def _run_werewolves(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
    ) -> None:
        ability_id = "werewolf.attack"
        wolves = [
            player for player in state.players if player.alive and player.role_key == "werewolf"
        ]
        candidates = [
            player for player in state.players if player.alive and player.role_key != "werewolf"
        ]
        if not wolves or not candidates:
            self._repository.skip_activation(
                state=state,
                ability_id=ability_id,
                reason="no_eligible_actor_or_target",
            )
            return
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="werewolf_attack_wake",
            objective="唤醒狼人团队并请他们依次实时商议袭击目标",
            context={"ability_id": ability_id},
        )
        prior_proposals: list[dict[str, Any]] = []
        occurrence = 0
        consensus_target: str | None = None
        final_activation: V2ActivationRef | None = None
        final_decision: V2ModelDecision | None = None
        for round_no in (1, 2):
            round_items: list[tuple[V2ActivationRef, V2ModelDecision]] = []
            for wolf in wolves:
                occurrence += 1
                activation = self._repository.open_activation(
                    state=state,
                    ability_id=ability_id,
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
                        "选择本轮狼人团队建议袭击的一名非狼人存活玩家；你可以参考本轮此前狼人的建议"
                    ),
                    knowledge={
                        "werewolf_teammates": [item.player_id for item in wolves],
                        "prior_team_proposals": prior_proposals,
                        "round_no": round_no,
                        "consensus_rule": "全员同一目标才生效；最多两轮；第二轮仍不一致则空刀",
                    },
                    optional=False,
                )
                round_items.append((activation, decision))
                prior_proposals.append(
                    {
                        "round_no": round_no,
                        "player_id": wolf.player_id,
                        "target_player_id": decision.target_player_id,
                    }
                )
                await broadcaster.broadcast_json(
                    ability_progress(
                        game_id=state.game_id,
                        run_id=state.run_id,
                        ability_id=ability_id,
                        status="decision_committed",
                        actor_player_id=wolf.player_id,
                        target_player_id=decision.target_player_id,
                        round_no=round_no,
                    ),
                    audience="god_view",
                )
            proposed = {item.target_player_id for _activation, item in round_items}
            if len(proposed) == 1:
                consensus_target = next(iter(proposed))
            for index, (activation, decision) in enumerate(round_items):
                is_final = consensus_target is not None and index == len(round_items) - 1
                self._repository.complete_activation(
                    state=state,
                    activation=activation,
                    decision={
                        "round_no": round_no,
                        "target_player_id": decision.target_player_id,
                        "speech": decision.speech,
                    },
                    result={"consensus_reached": consensus_target is not None},
                    effect_type="attack" if is_final else None,
                    target_player_id=consensus_target if is_final else None,
                )
                if is_final:
                    final_activation = activation
                    final_decision = decision
            if consensus_target is not None:
                break
        working.attack_target = consensus_target
        await broadcaster.broadcast_json(
            ability_progress(
                game_id=state.game_id,
                run_id=state.run_id,
                ability_id=ability_id,
                status="completed" if consensus_target else "no_consensus_no_attack",
                actor_player_id=(final_activation.actor_player_id if final_activation else None),
                target_player_id=(final_decision.target_player_id if final_decision else None),
            ),
            audience="god_view",
        )
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="werewolf_attack_sleep",
            objective="宣布狼人行动结束并请狼人闭眼，不公开目标",
            context={"ability_id": ability_id},
        )

    async def _run_guard(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
    ) -> None:
        ability_id = "guard.protect"
        guard = _single_owner(state, "guard")
        if guard is None or not guard.alive:
            self._repository.skip_activation(
                state=state,
                ability_id=ability_id,
                reason="owner_not_alive",
            )
            return
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
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="guard_protect_wake",
            objective="唤醒守卫并请其选择今晚守护的存活玩家",
            context={"ability_id": ability_id, "night_no": state.round_no},
        )
        activation = self._repository.open_activation(
            state=state,
            ability_id=ability_id,
            actor_player_id=guard.player_id,
            occurrence=1,
        )
        decision = await self._player_decision(
            state=state,
            broadcaster=broadcaster,
            activation=activation,
            player=guard,
            candidates=candidates,
            objective="选择一名今晚要守护的存活玩家；不能连续两夜守护同一目标",
            knowledge={
                "night_no": state.round_no,
                "previous_protected_target": previous_target,
            },
            optional=False,
        )
        working.protected_target = decision.target_player_id
        self._repository.complete_activation(
            state=state,
            activation=activation,
            decision={"target_player_id": decision.target_player_id, "speech": decision.speech},
            result={"effect": "protect_registered"},
            effect_type="protect",
            target_player_id=decision.target_player_id,
            ability_state_patch={"previous_target_player_id": decision.target_player_id},
        )
        await self._ability_completed(state, broadcaster, ability_id, guard, decision)
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="guard_protect_sleep",
            objective="宣布守卫行动结束并请守卫闭眼，不公开守护目标",
            context={"ability_id": ability_id},
        )

    async def _run_seer(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        working: _WorkingNight,
    ) -> None:
        del working
        ability_id = "seer.investigate"
        seer = _single_owner(state, "seer")
        if seer is None or not seer.alive:
            self._repository.skip_activation(
                state=state,
                ability_id=ability_id,
                reason="owner_not_alive",
            )
            return
        candidates = [
            player
            for player in state.players
            if player.alive and player.player_id != seer.player_id
        ]
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="seer_investigate_wake",
            objective="唤醒预言家并请其选择今晚查验的一名其他存活玩家",
            context={"ability_id": ability_id},
        )
        activation = self._repository.open_activation(
            state=state,
            ability_id=ability_id,
            actor_player_id=seer.player_id,
            occurrence=1,
        )
        decision = await self._player_decision(
            state=state,
            broadcaster=broadcaster,
            activation=activation,
            player=seer,
            candidates=candidates,
            objective="选择一名其他存活玩家进行查验",
            knowledge={
                "known_investigations": self._repository.player_knowledge(
                    game_id=state.game_id,
                    player_id=seer.player_id,
                )
            },
            optional=False,
        )
        target = state.player(_required_target(decision))
        alignment = "werewolves" if target.role_key == "werewolf" else "villagers"
        self._repository.complete_activation(
            state=state,
            activation=activation,
            decision={"target_player_id": target.player_id, "speech": decision.speech},
            result={"alignment": alignment},
            effect_type="investigate",
            target_player_id=target.player_id,
            knowledge=(
                (
                    "player",
                    seer.player_id,
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
                "ability_id": ability_id,
                "target_player_id": target.player_id,
                "target_player_seat": target.seat,
                "alignment": alignment,
            },
        )
        await self._ability_completed(state, broadcaster, ability_id, seer, decision)
        await self._private_judge(
            state=state,
            broadcaster=broadcaster,
            action_type="seer_investigate_sleep",
            objective="宣布预言家行动结束并请预言家闭眼",
            context={"ability_id": ability_id},
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
                    reason="owner_not_alive",
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
                    reason="heal_already_used",
                )
            elif attacked is None:
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.heal",
                    reason="no_provisional_attack",
                )
            elif attacked.player_id == witch.player_id and state.round_no > 1:
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.heal",
                    reason="self_heal_only_allowed_first_night",
                )
            else:
                activation = self._repository.open_activation(
                    state=state,
                    ability_id="witch.heal",
                    actor_player_id=witch.player_id,
                    occurrence=1,
                )
                decision = await self._player_decision(
                    state=state,
                    broadcaster=broadcaster,
                    activation=activation,
                    player=witch,
                    candidates=[attacked],
                    objective="决定是否使用唯一解药救下今晚被袭击的玩家；放弃则 target_player_id 为 null",
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
                    decision={
                        "target_player_id": decision.target_player_id,
                        "speech": decision.speech,
                    },
                    result={"heal_used": heal_used},
                    effect_type="heal" if heal_used else None,
                    target_player_id=decision.target_player_id,
                    ability_state_patch=(
                        {"available": False, "remaining": 0} if heal_used else None
                    ),
                )
                await self._ability_completed(state, broadcaster, "witch.heal", witch, decision)
        poison_state = self._repository.ability_state(
            game_id=state.game_id,
            ability_id="witch.poison",
        )
        if "witch.poison" in configured:
            if not poison_state.get("available", True):
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.poison",
                    reason="poison_already_used",
                )
            elif heal_used:
                self._repository.skip_activation(
                    state=state,
                    ability_id="witch.poison",
                    reason="heal_poison_mutually_exclusive",
                )
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
                        reason="no_eligible_target",
                    )
                else:
                    activation = self._repository.open_activation(
                        state=state,
                        ability_id="witch.poison",
                        actor_player_id=witch.player_id,
                        occurrence=1,
                    )
                    decision = await self._player_decision(
                        state=state,
                        broadcaster=broadcaster,
                        activation=activation,
                        player=witch,
                        candidates=poison_candidates,
                        objective="决定是否使用唯一毒药；放弃则 target_player_id 为 null",
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
                        decision={
                            "target_player_id": decision.target_player_id,
                            "speech": decision.speech,
                        },
                        result={"poison_used": poison_used},
                        effect_type="poison" if poison_used else None,
                        target_player_id=decision.target_player_id,
                        ability_state_patch=(
                            {"available": False, "remaining": 0} if poison_used else None
                        ),
                    )
                    await self._ability_completed(
                        state, broadcaster, "witch.poison", witch, decision
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
            actor_player_id=hunter_id,
            occurrence=1,
        )
        decision = await self._player_decision(
            state=reaction_state,
            broadcaster=broadcaster,
            activation=activation,
            player=hunter,
            candidates=candidates,
            objective="你已在黎明死亡，决定是否发动猎人技能带走一名存活玩家；放弃则 target_player_id 为 null",
            knowledge={"death_cause_allows_shot": True},
            optional=True,
            audience="all",
        )
        self._repository.complete_activation(
            state=reaction_state,
            activation=activation,
            decision={"target_player_id": decision.target_player_id, "speech": decision.speech},
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
    ) -> V2ModelDecision:
        knowledge_fact_ids, knowledge_hash = self._repository.register_activation_knowledge(
            state=state,
            activation=activation,
            owner_player_id=player.player_id,
            allowed_knowledge=knowledge,
        )
        decision = await self._actions.run_player_decision(
            game_id=state.game_id,
            broadcaster=broadcaster,
            spec=V2SpeechSpec(
                action_type=f"ability_{activation.ability_id}_decision",
                phase_id=(f"day_{state.round_no}" if audience == "all" else state.phase_id),
                required_phase_state=(
                    "dawn_reactions_ready" if audience == "all" else "night_running"
                ),
                objective=objective,
                success_live_state="ready",
                success_phase_state=(
                    "dawn_reactions_ready" if audience == "all" else "night_running"
                ),
                actor_kind="player",
                actor_id=player.player_id,
                audience=audience,
                speaker=player.tts_speaker,
                model_id=player.model_id,
                activation_id=activation.activation_id,
                output_kind="decision_and_speech",
                allowed_target_ids=tuple(item.player_id for item in candidates),
                target_optional=optional,
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
                    "actor_profile": player.persona,
                    "allowed_knowledge": knowledge,
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
                    "public_history": self._repository.public_history(state.game_id),
                },
            ),
        )
        if decision is None:
            raise V2NightError(f"{activation.ability_id}_decision_failed")
        return decision

    async def _ability_completed(
        self,
        state: V2NightRuntimeState,
        broadcaster: V2BroadcastPort,
        ability_id: str,
        player: V2NightPlayer,
        decision: V2ModelDecision,
    ) -> None:
        await broadcaster.broadcast_json(
            ability_progress(
                game_id=state.game_id,
                run_id=state.run_id,
                ability_id=ability_id,
                status="completed",
                actor_player_id=player.player_id,
                target_player_id=decision.target_player_id,
            ),
            audience="god_view",
        )


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
