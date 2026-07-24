from __future__ import annotations

from collections import defaultdict
import logging
from typing import Any

from app.v2.action_engine import V2ActionEngine, V2BroadcastPort, V2SpeechSpec
from app.v2.match_repository import (
    V2ExileResult,
    V2MatchPlayer,
    V2MatchRepository,
    V2MatchSnapshot,
)
from app.v2.model_client import V2ModelDecision
from app.v2.protocol import (
    day_progress,
    game_phase_changed,
    live_state,
    match_state_changed,
    player_state_changed,
)
from app.v2.repository import V2PhaseTransition


logger = logging.getLogger(__name__)

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


class V2DayRuntimeError(RuntimeError):
    pass


class V2DayEngine:
    def __init__(
        self,
        *,
        repository: V2MatchRepository,
        action_engine: V2ActionEngine,
    ) -> None:
        self._repository = repository
        self._actions = action_engine

    async def resolve_pending_death_aftermath(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> None:
        """Resolve public death consequences left by the preceding night."""
        await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)

    async def run(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> V2PhaseTransition | None:
        try:
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
                raise V2DayRuntimeError(
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

            if "debate" in actions:
                exploded = await self._run_public_discussion(
                    game_id=game_id,
                    broadcaster=broadcaster,
                )
                if exploded:
                    await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)
                    return await self._close_day(
                        game_id=game_id,
                        broadcaster=broadcaster,
                        reason="discussion_self_explosion",
                        summarize=False,
                    )

            if "vote" in actions:
                exploded = await self._offer_all_wolves_explosion(
                    game_id=game_id,
                    broadcaster=broadcaster,
                    stage="before_exile_vote",
                )
                if exploded:
                    await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)
                    return await self._close_day(
                        game_id=game_id,
                        broadcaster=broadcaster,
                        reason="pre_vote_self_explosion",
                        summarize=False,
                    )
                exile = await self._run_exile_vote(game_id=game_id, broadcaster=broadcaster)
                if exile is not None:
                    await self._resolve_exile_aftermath(
                        game_id=game_id,
                        exile=exile,
                        broadcaster=broadcaster,
                    )

            return await self._close_day(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="day_actions_completed",
                summarize="summarize" in actions,
            )
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
        state: V2MatchSnapshot,
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
        state: V2MatchSnapshot,
        broadcaster: V2BroadcastPort,
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
            raise V2DayRuntimeError(f"{action_type}_failed")
        transition = self._repository.record_phase_state(
            game_id=state.game_id,
            previous_phase_state=previous_state,
        )
        await broadcaster.broadcast_json(game_phase_changed(transition))

    async def _run_sheriff_election(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> None:
        state = self._repository.snapshot(game_id)
        alive = [player for player in state.players if player.alive]
        candidates: list[V2MatchPlayer] = []
        for player in alive:
            decision = await self._player_action(
                game_id=game_id,
                player=player,
                broadcaster=broadcaster,
                action_type="sheriff_run",
                objective="决定是否竞选警长；参选则选择自己的 player_id，不参选则为 null",
                candidates=[player],
                optional=True,
                output_kind="public_decision",
            )
            is_running = decision.target_player_id == player.player_id
            self._repository.append_event(
                game_id=game_id,
                event_type="sheriff_run_decided",
                payload={
                    "round_no": state.round_no,
                    "player_id": player.player_id,
                    "is_running": is_running,
                    "speech": decision.speech,
                },
            )
            if is_running:
                candidates.append(player)

        original_candidates = tuple(candidates)
        original_off_sheriff = [
            player for player in alive if player.player_id not in {item.player_id for item in candidates}
        ]
        if not candidates:
            await self._destroy_badge(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="no_sheriff_candidates",
            )
            return

        for candidate in candidates:
            decision = await self._player_action(
                game_id=game_id,
                player=candidate,
                broadcaster=broadcaster,
                action_type="sheriff_campaign_speech",
                objective="发表警长竞选发言，说明竞选理由、判断和警徽流安排",
                candidates=[],
                optional=True,
                output_kind="public_speech",
            )
            self._record_speech(state, candidate, decision, "sheriff_campaign")

        remaining: list[V2MatchPlayer] = []
        for candidate in candidates:
            decision = await self._player_action(
                game_id=game_id,
                player=candidate,
                broadcaster=broadcaster,
                action_type="sheriff_withdraw",
                objective="决定是否退水；退水则选择自己的 player_id，不退水则为 null",
                candidates=[candidate],
                optional=True,
                output_kind="public_decision",
            )
            withdrew = decision.target_player_id == candidate.player_id
            self._repository.append_event(
                game_id=game_id,
                event_type="sheriff_withdraw_decided",
                payload={
                    "round_no": state.round_no,
                    "player_id": candidate.player_id,
                    "withdrew": withdrew,
                    "speech": decision.speech,
                },
            )
            if not withdrew:
                remaining.append(candidate)

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
            decision = await self._player_action(
                game_id=game_id,
                player=candidate,
                broadcaster=broadcaster,
                action_type="sheriff_pk_speech",
                objective="你进入警长竞选平票 PK，请发表补充竞选发言",
                candidates=[],
                optional=True,
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

    async def _run_public_discussion(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> bool:
        state = self._repository.snapshot(game_id)
        order = await self._speech_order(state=state, broadcaster=broadcaster)
        rounds = max(1, int(state.rule.get("speech_rounds") or 1))
        for speech_round in range(1, rounds + 1):
            for player_id in order:
                current = self._repository.snapshot(game_id)
                player = current.player(player_id)
                if not player.alive:
                    continue
                if player.role_key == "werewolf" and await self._offer_self_explosion(
                    game_id=game_id,
                    player=player,
                    broadcaster=broadcaster,
                    stage=f"discussion_round_{speech_round}",
                    pre_sheriff=False,
                ):
                    return True
                decision = await self._player_action(
                    game_id=game_id,
                    player=player,
                    broadcaster=broadcaster,
                    action_type="day_debate_speech",
                    objective="结合公开发言、票型和你掌握的合法私密信息发表本轮白天分析",
                    candidates=[],
                    optional=True,
                    output_kind="public_speech",
                    extra_context={"speech_round": speech_round, "speech_order": order},
                )
                self._record_speech(current, player, decision, "day_debate")
        return False

    async def _speech_order(
        self,
        *,
        state: V2MatchSnapshot,
        broadcaster: V2BroadcastPort,
    ) -> list[str]:
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
        decision = await self._player_action(
            game_id=state.game_id,
            player=sheriff,
            broadcaster=broadcaster,
            action_type="sheriff_speech_order",
            objective="选择警左或警右的相邻存活玩家作为第一位发言者",
            candidates=candidates,
            optional=False,
            output_kind="public_decision",
        )
        start = decision.target_player_id
        if start == right.player_id:
            ordered = alive[sheriff_index + 1 :] + alive[: sheriff_index + 1]
        else:
            ordered = list(reversed(alive[:sheriff_index])) + list(
                reversed(alive[sheriff_index:])
            )
        result = [item.player_id for item in ordered]
        self._repository.append_event(
            game_id=state.game_id,
            event_type="day_speech_order_selected",
            payload={"round_no": state.round_no, "order": result, "speech": decision.speech},
        )
        return result

    async def _run_exile_vote(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> V2ExileResult | None:
        state = self._repository.snapshot(game_id)
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
                decision = await self._player_action(
                    game_id=game_id,
                    player=candidate,
                    broadcaster=broadcaster,
                    action_type="exile_pk_speech",
                    objective="你进入放逐平票 PK，请针对质疑发表补充发言",
                    candidates=[],
                    optional=True,
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

        target = state.player(leaders[0])
        result = self._repository.resolve_exile(game_id=game_id, player_id=target.player_id)
        objective = (
            f"宣布{target.display_name}被投票放逐后翻开白痴身份并免于出局"
            if result.outcome == "idiot_revealed"
            else f"宣布{target.display_name}被投票放逐出局，不公开其身份"
        )
        current = self._repository.snapshot(game_id)
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_exile_result",
            objective=objective,
            success_phase_state=current.phase_state,
            context={"player_id": target.player_id, "outcome": result.outcome},
        ):
            raise V2DayRuntimeError("judge_exile_result_failed")
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
        exile: V2ExileResult,
        broadcaster: V2BroadcastPort,
    ) -> None:
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
                objective="发表被放逐后的最后遗言",
                candidates=[],
                optional=True,
                output_kind="public_speech",
            )
            self._record_speech(state, player, decision, "exile_last_words")
        await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)

    async def _resolve_death_aftermath(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> None:
        resolved_hunters: set[str] = set()
        while pending_hunters := tuple(
            hunter_id
            for hunter_id in self._repository.pending_hunters(game_id)
            if hunter_id not in resolved_hunters
        ):
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
                objective="你已死亡且可以发动猎人技能；选择一名存活玩家开枪，或返回 null 放弃",
                candidates=candidates,
                optional=True,
                output_kind="public_death_reaction",
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
                    objective=f"宣布猎人开枪带走了{target.display_name}，不公开其他身份",
                    success_phase_state=current.phase_state,
                    context={"target_player_id": target.player_id},
                ):
                    raise V2DayRuntimeError("hunter_announcement_failed")
                await self._broadcast_death(
                    state=current,
                    player_id=target.player_id,
                    cause="hunter_shot",
                    broadcaster=broadcaster,
                )
        await self._resolve_dead_sheriff(game_id=game_id, broadcaster=broadcaster)

    async def _resolve_dead_sheriff(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> None:
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
            objective="你已死亡；选择一名存活玩家移交警徽，或返回 null 撕毁警徽",
            candidates=candidates,
            optional=True,
            output_kind="public_death_reaction",
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
            else f"宣布警徽移交给{current.player(target_id).display_name}"
        )
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_sheriff_badge_result",
            objective=objective,
            success_phase_state=current.phase_state,
            context={"from_player_id": sheriff_id, "to_player_id": target_id},
        ):
            raise V2DayRuntimeError("sheriff_badge_announcement_failed")
        await self._broadcast_match_state(current, broadcaster)

    async def _collect_votes(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
        action_type: str,
        voters: list[V2MatchPlayer],
        candidates: list[V2MatchPlayer],
        weighted: bool,
        context: dict[str, Any],
    ) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        state = self._repository.snapshot(game_id)
        for voter in voters:
            eligible = [item for item in candidates if item.player_id != voter.player_id]
            if not eligible:
                continue
            decision = await self._player_action(
                game_id=game_id,
                player=voter,
                broadcaster=broadcaster,
                action_type=action_type,
                objective="从合法候选人中选择一名投票，并公开说明理由",
                candidates=eligible,
                optional=False,
                output_kind="public_vote",
                extra_context=context,
            )
            target_id = _required_target(decision)
            weight = (
                float(state.rule.get("sheriff_vote_weight") or 1)
                if weighted and voter.player_id == state.sheriff_player_id
                else 1.0
            )
            totals[target_id] += weight
            self._repository.append_event(
                game_id=game_id,
                event_type="day_vote_committed",
                payload={
                    "round_no": state.round_no,
                    "action_type": action_type,
                    "voter_player_id": voter.player_id,
                    "target_player_id": target_id,
                    "weight": weight,
                    "speech": decision.speech,
                },
            )
        self._repository.append_event(
            game_id=game_id,
            event_type="day_vote_resolved",
            payload={
                "round_no": state.round_no,
                "action_type": action_type,
                "totals": dict(totals),
                "leaders": _leaders(dict(totals)),
            },
        )
        return dict(totals)

    async def _offer_pre_sheriff_explosion(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
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
        broadcaster: V2BroadcastPort,
        stage: str,
        pre_sheriff: bool = False,
    ) -> bool:
        state = self._repository.snapshot(game_id)
        if not bool(state.rule.get("werewolf_self_explosion_enabled")):
            return False
        for wolf in state.players:
            if wolf.alive and wolf.role_key == "werewolf" and await self._offer_self_explosion(
                game_id=game_id,
                player=wolf,
                broadcaster=broadcaster,
                stage=stage,
                pre_sheriff=pre_sheriff,
            ):
                return True
        return False

    async def _offer_self_explosion(
        self,
        *,
        game_id: str,
        player: V2MatchPlayer,
        broadcaster: V2BroadcastPort,
        stage: str,
        pre_sheriff: bool,
    ) -> bool:
        state = self._repository.snapshot(game_id)
        if not bool(state.rule.get("werewolf_self_explosion_enabled")):
            return False
        decision = await self._player_action(
            game_id=game_id,
            player=player,
            broadcaster=broadcaster,
            action_type="werewolf_self_explosion",
            objective="秘密决定是否现在自爆；自爆则选择自己的 player_id，不自爆则为 null",
            candidates=[player],
            optional=True,
            audience="god_view",
            output_kind="private_decision",
            extra_context={"public_stage": stage},
        )
        exploded = decision.target_player_id == player.player_id
        self._repository.append_event(
            game_id=game_id,
            event_type="werewolf_self_explosion_decided",
            payload={
                "round_no": state.round_no,
                "player_id": player.player_id,
                "stage": stage,
                "exploded": exploded,
            },
        )
        if not exploded:
            return False
        if pre_sheriff:
            outcome = self._repository.record_pre_sheriff_explosion(
                game_id=game_id,
                player_id=player.player_id,
            )
        else:
            self._repository.record_day_explosion(
                game_id=game_id,
                player_id=player.player_id,
                stage=stage,
            )
            outcome = "day_ended"
        current = self._repository.snapshot(game_id)
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_werewolf_self_explosion",
            objective=f"公开宣布{player.display_name}发动狼人自爆并立即出局，当天剩余流程中止",
            success_phase_state=current.phase_state,
            context={"player_id": player.player_id, "stage": stage, "outcome": outcome},
        ):
            raise V2DayRuntimeError("self_explosion_announcement_failed")
        await self._broadcast_death(
            state=current,
            player_id=player.player_id,
            cause="werewolf_self_explosion",
            broadcaster=broadcaster,
        )
        await self._broadcast_match_state(self._repository.snapshot(game_id), broadcaster)
        return True

    async def _elect_sheriff(
        self,
        *,
        game_id: str,
        player: V2MatchPlayer,
        broadcaster: V2BroadcastPort,
        reason: str,
    ) -> None:
        self._repository.set_sheriff(game_id=game_id, player_id=player.player_id, reason=reason)
        state = self._repository.snapshot(game_id)
        if not await self._judge(
            state=state,
            broadcaster=broadcaster,
            action_type="judge_sheriff_elected",
            objective=f"宣布{player.display_name}当选警长并获得警徽",
            success_phase_state=state.phase_state,
            context={"player_id": player.player_id, "reason": reason},
        ):
            raise V2DayRuntimeError("sheriff_elected_announcement_failed")
        await self._broadcast_match_state(state, broadcaster)

    async def _destroy_badge(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
        reason: str,
    ) -> None:
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
            raise V2DayRuntimeError("sheriff_badge_destroyed_announcement_failed")
        await self._broadcast_match_state(state, broadcaster)

    async def _announce_no_exile(
        self,
        *,
        state: V2MatchSnapshot,
        broadcaster: V2BroadcastPort,
        reason: str,
    ) -> None:
        current = self._repository.snapshot(state.game_id)
        if not await self._judge(
            state=current,
            broadcaster=broadcaster,
            action_type="judge_no_exile",
            objective="宣布本轮放逐投票没有产生唯一结果，今天无人被放逐",
            success_phase_state=current.phase_state,
            context={"reason": reason},
        ):
            raise V2DayRuntimeError("no_exile_announcement_failed")

    async def _close_day(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
        reason: str,
        summarize: bool,
    ) -> V2PhaseTransition:
        state = self._repository.snapshot(game_id)
        winner = self._repository.current_winner(game_id)
        if winner is not None:
            winner_name = "好人阵营" if winner == "villagers" else "狼人阵营"
            if not await self._judge(
                state=state,
                broadcaster=broadcaster,
                action_type="judge_game_completed",
                objective=f"宣布本局结束，{winner_name}获胜",
                success_phase_state=state.phase_state,
                context={"winner": winner, "round_no": state.round_no},
            ):
                raise V2DayRuntimeError("game_completed_announcement_failed")
        elif summarize:
            if not await self._judge(
                state=state,
                broadcaster=broadcaster,
                action_type="judge_day_summary",
                objective=f"简洁总结第{state.round_no}天公开结果并宣布即将入夜，不添加未公开信息",
                success_phase_state=state.phase_state,
                context={"public_history": list(state.public_history[-20:])},
            ):
                raise V2DayRuntimeError("day_summary_failed")
        transition = self._repository.finish_day(game_id=game_id, reason=reason)
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
                    reason=(None if transition.phase_state == "game_completed" else "max_rounds_exceeded"),
                )
            )
        return transition

    async def _judge(
        self,
        *,
        state: V2MatchSnapshot,
        broadcaster: V2BroadcastPort,
        action_type: str,
        objective: str,
        success_phase_state: str,
        context: dict[str, Any],
    ) -> bool:
        return await self._actions.run_judge_speech(
            game_id=state.game_id,
            broadcaster=broadcaster,
            spec=V2SpeechSpec(
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
        player: V2MatchPlayer,
        broadcaster: V2BroadcastPort,
        action_type: str,
        objective: str,
        candidates: list[V2MatchPlayer],
        optional: bool,
        output_kind: str,
        audience: str = "all",
        extra_context: dict[str, Any] | None = None,
    ) -> V2ModelDecision:
        state = self._repository.snapshot(game_id)
        decision = await self._actions.run_player_decision(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=V2SpeechSpec(
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
                model_id=player.model_id,
                output_kind=output_kind,
                allowed_target_ids=(
                    None
                    if output_kind == "public_speech"
                    else tuple(item.player_id for item in candidates)
                ),
                target_optional=optional,
                context={
                    "round_no": state.round_no,
                    "actor_private": {
                        "player_id": player.player_id,
                        "seat": player.seat,
                        "role_key": player.role_key,
                        "team": player.team,
                        "persona": player.persona,
                        "knowledge": self._repository.private_knowledge(
                            game_id=game_id,
                            player_id=player.player_id,
                        ),
                    },
                    "candidates": [
                        {
                            "player_id": item.player_id,
                            "seat": item.seat,
                            "display_name": item.display_name,
                        }
                        for item in candidates
                    ],
                    "public_history": list(state.public_history[-60:]),
                    "sheriff_player_id": state.sheriff_player_id,
                    "public_rules": {
                        key: state.rule.get(key)
                        for key in (
                            "win_condition",
                            "sheriff_vote_weight",
                            "speech_policy",
                            "werewolf_self_explosion_enabled",
                            "exile_last_words_enabled",
                        )
                    },
                    **(extra_context or {}),
                },
            ),
        )
        if decision is None:
            raise V2DayRuntimeError(f"{action_type}_failed")
        return decision

    def _record_speech(
        self,
        state: V2MatchSnapshot,
        player: V2MatchPlayer,
        decision: V2ModelDecision,
        stage: str,
    ) -> None:
        self._repository.append_event(
            game_id=state.game_id,
            event_type="day_speech_committed",
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
        state: V2MatchSnapshot,
        player_id: str,
        cause: str,
        broadcaster: V2BroadcastPort,
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
        state: V2MatchSnapshot,
        broadcaster: V2BroadcastPort,
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


def _required_target(decision: V2ModelDecision) -> str:
    if decision.target_player_id is None:
        raise V2DayRuntimeError("required vote target is missing")
    return decision.target_player_id


def _failure_code(exc: Exception) -> str:
    value = str(exc).strip()
    if not value:
        return "day_runtime_failed"
    return value[:120]
