from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
import hashlib
import json
import logging
from typing import Any, Literal

from app.v2.action_engine import (
    V2ActionEngine,
    V2ActionResult,
    V2BroadcastPort,
    V2DecisionContract,
    V2PreflightPauseFailure,
    V2SpeechSpec,
)
from app.v2.match_repository import (
    V2DayVoteCommit,
    V2ExileResult,
    V2MatchPlayer,
    V2MatchRepository,
    V2MatchSnapshot,
)
from app.v2.model_context import (
    V2ModelPlayerReference,
    build_actor_information,
    build_public_match_state,
    build_public_rule_contract,
    private_authoritative_facts,
)
from app.v2.model_context_contract import is_supported_model_context_contract
from app.v2.model_client import V2ModelDecision
from app.v2.protocol import (
    day_progress,
    game_phase_changed,
    live_state,
    match_state_changed,
    player_state_changed,
)
from app.v2.repository import V2ExecutionOwnershipLost, V2PhaseTransition


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
    voter: V2MatchPlayer,
    candidates: list[V2MatchPlayer],
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


class V2DayRuntimeError(RuntimeError):
    pass


def speech_order_from_start(
    alive_by_seat: Iterable[V2MatchPlayer],
    sheriff_player_id: str,
    start_player_id: str,
) -> list[str]:
    alive = sorted(tuple(alive_by_seat), key=lambda item: item.seat)
    alive_ids = [item.player_id for item in alive]
    if len(alive) < 2 or sheriff_player_id not in alive_ids:
        raise V2DayRuntimeError("sheriff_speech_order_invalid_state")
    sheriff_index = alive_ids.index(sheriff_player_id)
    left = alive[(sheriff_index - 1) % len(alive)]
    right = alive[(sheriff_index + 1) % len(alive)]
    if start_player_id not in {left.player_id, right.player_id}:
        raise V2DayRuntimeError("sheriff_speech_order_invalid_start")
    if start_player_id == right.player_id:
        ordered = alive[sheriff_index + 1 :] + alive[: sheriff_index + 1]
    else:
        ordered = list(reversed(alive[:sheriff_index])) + list(reversed(alive[sheriff_index:]))
    result = [item.player_id for item in ordered]
    if result[-1] != sheriff_player_id or set(result) != set(alive_ids):
        raise V2DayRuntimeError("sheriff_speech_order_invalid_result")
    return result


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
        self._actions.check_cancellation(game_id)
        await self._resolve_death_aftermath(game_id=game_id, broadcaster=broadcaster)

    async def run_pre_dawn_sheriff_election(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> None:
        self._actions.check_cancellation(game_id)
        state = self._repository.snapshot(game_id)
        actions = set(state.rule.get("day_actions") or [])
        if not self._should_run_sheriff_election(state, actions):
            raise V2DayRuntimeError("pre_dawn_sheriff_election_not_configured")
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
        broadcaster: V2BroadcastPort,
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
        broadcaster: V2BroadcastPort,
    ) -> V2PhaseTransition | None:
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

            self._actions.check_cancellation(game_id)
            return await self._close_day(
                game_id=game_id,
                broadcaster=broadcaster,
                reason="day_actions_completed",
                summarize="summarize" in actions,
            )
        except V2ExecutionOwnershipLost:
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
        broadcaster: V2BroadcastPort,
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
        broadcaster: V2BroadcastPort,
        state: V2MatchSnapshot,
        players: list[V2MatchPlayer],
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

        async def request_decision(player: V2MatchPlayer) -> V2ModelDecision | None:
            return await self._player_action(
                game_id=game_id,
                player=player,
                broadcaster=broadcaster,
                action_type=action_type,
                objective=objective,
                candidates=[],
                target_optional=None,
                output_kind=output_kind,
                decision_contract=V2DecisionContract(
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
                raise V2DayRuntimeError(f"{action_type}_invalid_decision")
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
        broadcaster: V2BroadcastPort,
    ) -> bool:
        self._actions.check_cancellation(game_id)
        state = self._repository.snapshot(game_id)
        order = await self._speech_order(state=state, broadcaster=broadcaster)
        rounds = max(1, int(state.rule.get("speech_rounds") or 1))
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
            for player_id in order:
                self._actions.check_cancellation(game_id)
                current = self._repository.snapshot(game_id)
                player = current.player(player_id)
                if not player.alive:
                    continue
                decision = await self._player_action(
                    game_id=game_id,
                    player=player,
                    broadcaster=broadcaster,
                    action_type="day_debate_speech",
                    objective="发表本轮白天讨论发言。",
                    candidates=[],
                    target_optional=None,
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
            raise V2DayRuntimeError("unsupported_model_context_contract")
        decision = await self._player_action(
            game_id=state.game_id,
            player=sheriff,
            broadcaster=broadcaster,
            action_type="sheriff_speech_order",
            objective="根据每个候选对应的完整发言顺序，选择本轮起始发言者。",
            candidates=candidates,
            target_optional=False,
            output_kind="public_decision",
            decision_contract=V2DecisionContract(
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
            raise V2DayRuntimeError("sheriff_speech_order_invalid_start")
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
        broadcaster: V2BroadcastPort,
    ) -> V2ExileResult | None:
        self._actions.check_cancellation(game_id)
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
        broadcaster: V2BroadcastPort,
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
                decision_contract=V2DecisionContract(
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
                    raise V2DayRuntimeError("hunter_announcement_failed")
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
        broadcaster: V2BroadcastPort,
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
            decision_contract=V2DecisionContract(
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
        self._actions.check_cancellation(game_id)
        totals: dict[str, float] = defaultdict(float)
        state = self._repository.snapshot(game_id)
        public_cutoff_record_seq = state.last_record_seq
        batch_id = f"{state.phase_id}:{action_type}:{public_cutoff_record_seq}:vote"
        prepared: list[tuple[V2MatchPlayer, list[V2MatchPlayer]]] = []
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
        latest_machine_format_failure_results: list[V2ActionResult | None] = [
            None for _item in prepared
        ]
        latest_output_budget_failure_results: list[V2ActionResult | None] = [
            None for _item in prepared
        ]
        machine_format_failure_episode_ids_by_voter: list[list[str]] = [[] for _item in prepared]
        output_budget_failure_episode_ids_by_voter: list[list[str]] = [[] for _item in prepared]

        async def request_vote(
            index: int,
            voter: V2MatchPlayer,
            eligible: list[V2MatchPlayer],
            *,
            stage: Literal[
                "concurrent_initial",
                "concurrent_recovery",
                "sequential_recovery",
            ],
            preflight_pause_failure: V2PreflightPauseFailure | None = None,
        ) -> V2ActionResult:
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
                decision_contract=V2DecisionContract(
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
                    "vote_batch_stage": stage,
                },
                frozen_state=state,
                projection_at_seq=public_cutoff_record_seq,
                defer_presentation=isolated,
                isolated_failure=isolated,
                allow_failure=isolated,
                batch_id=batch_id,
                decision_family_id=decision_family_ids[index],
                prior_machine_format_failures=machine_format_failure_counts[index],
                automatic_machine_format_budget=(_VOTE_MACHINE_FORMAT_AUTOMATIC_BUDGET),
                prior_output_budget_failures=output_budget_failure_counts[index],
                automatic_output_budget_budget=(_VOTE_OUTPUT_BUDGET_AUTOMATIC_BUDGET),
                preflight_pause_failure=preflight_pause_failure,
                return_result=True,
            )
            if not isinstance(result, V2ActionResult):
                return V2ActionResult(decision=result)
            return result

        def observe_failure(index: int, result: V2ActionResult) -> None:
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

        # All non-blocking attempts use the same frozen public cutoff. Initial
        # failures receive one more isolated concurrent attempt; only voters
        # still missing after that enter the blocking path one at a time. This
        # preserves durable pause/operator-retry semantics without publishing
        # a partial tally.
        initial_results = list(
            await asyncio.gather(
                *(
                    request_vote(index, voter, eligible, stage="concurrent_initial")
                    for index, (voter, eligible) in enumerate(prepared)
                )
            )
        )
        for index, result in enumerate(initial_results):
            observe_failure(index, result)
        decisions = [result.decision for result in initial_results]
        failed_indexes = [index for index, decision in enumerate(decisions) if decision is None]
        initial_failed_voter_ids = [prepared[index][0].player_id for index in failed_indexes]
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
                        request_vote(
                            index,
                            prepared[index][0],
                            prepared[index][1],
                            stage="concurrent_recovery",
                        )
                        for index in concurrent_recovery_indexes
                    )
                )
            )
            still_failed_indexes: list[int] = [
                index for index in failed_indexes if index not in concurrent_recovery_index_set
            ]
            concurrent_recovered_voter_ids: list[str] = []
            for index, result in zip(
                concurrent_recovery_indexes,
                concurrent_recovery_results,
                strict=True,
            ):
                observe_failure(index, result)
                decisions[index] = result.decision
                if result.decision is None:
                    still_failed_indexes.append(index)
                else:
                    concurrent_recovered_voter_ids.append(prepared[index][0].player_id)
            still_failed_indexes.sort()
            still_failed_voter_ids = [
                prepared[index][0].player_id for index in still_failed_indexes
            ]
            self._repository.append_event(
                game_id=game_id,
                event_type="day_vote_batch_concurrent_recovery_completed",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "action_type": action_type,
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                    "recovered_voter_ids": concurrent_recovered_voter_ids,
                    "still_failed_voter_ids": still_failed_voter_ids,
                },
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
                        raise V2DayRuntimeError("decision_family_retry_lineage_missing")
                    preflight_pause_failure = V2PreflightPauseFailure(
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
                        raise V2DayRuntimeError("decision_family_retry_lineage_missing")
                    preflight_pause_failure = V2PreflightPauseFailure(
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
            self._repository.append_event(
                game_id=game_id,
                event_type="day_vote_batch_recovery_completed",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "action_type": action_type,
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                    "recovered_voter_ids": initial_failed_voter_ids,
                },
            )

        committed: list[V2DayVoteCommit] = []
        for (voter, eligible), decision in zip(prepared, decisions, strict=True):
            if decision is None:
                raise V2DayRuntimeError(f"{action_type}_vote_batch_incomplete")
            target_id = _required_target(decision)
            if target_id not in {candidate.player_id for candidate in eligible}:
                raise V2DayRuntimeError(f"{action_type}_vote_target_invalid")
            weight = (
                float(state.rule.get("sheriff_vote_weight") or 1)
                if weighted and voter.player_id == state.sheriff_player_id
                else 1.0
            )
            totals[target_id] += weight
            committed.append(
                V2DayVoteCommit(
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
            "voter_weights": {
                voter.player_id: (
                    float(state.rule.get("sheriff_vote_weight") or 1)
                    if weighted and voter.player_id == state.sheriff_player_id
                    else 1.0
                )
                for voter in voters
            },
            "totals": dict(totals),
            "leaders": _leaders(dict(totals)),
            "identity_reveal": "none",
        }
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

        async def request_decision(wolf: V2MatchPlayer) -> V2ModelDecision | None:
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
                decision_contract=V2DecisionContract(
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
        affirmative: list[V2MatchPlayer] = []
        failed_player_ids: list[str] = []
        for wolf, decision in zip(wolves, decisions, strict=True):
            if decision is not None and not isinstance(decision.boolean_value, bool):
                raise V2DayRuntimeError("werewolf_self_explosion_invalid_decision")
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
            raise V2DayRuntimeError("self_explosion_announcement_failed")
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
        player: V2MatchPlayer,
        broadcaster: V2BroadcastPort,
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
            raise V2DayRuntimeError("sheriff_elected_announcement_failed")
        await self._broadcast_match_state(state, broadcaster)

    async def _destroy_badge(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
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
            raise V2DayRuntimeError("sheriff_badge_destroyed_announcement_failed")
        await self._broadcast_match_state(state, broadcaster)

    async def _announce_no_exile(
        self,
        *,
        state: V2MatchSnapshot,
        broadcaster: V2BroadcastPort,
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
            raise V2DayRuntimeError("no_exile_announcement_failed")

    async def _close_day(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
        reason: str,
        summarize: bool,
    ) -> V2PhaseTransition:
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
                spec=V2SpeechSpec(
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
                raise V2DayRuntimeError("day_summary_failed")
        self._actions.check_cancellation(game_id)
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
        state: V2MatchSnapshot,
        broadcaster: V2BroadcastPort,
    ) -> bool:
        if not is_supported_model_context_contract(state.model_context_contract):
            raise V2DayRuntimeError("unsupported_model_context_contract")

        players = tuple(
            sorted(
                (player for player in state.players if player.alive),
                key=lambda player: player.seat,
            )
        )
        batch_id = f"{state.game_id}:round_{state.round_no}:private_memories"
        self._repository.append_event(
            game_id=state.game_id,
            event_type="day_private_memory_batch_started",
            audience="god_view",
            payload={
                "round_no": state.round_no,
                "batch_id": batch_id,
                "public_cutoff_record_seq": state.last_record_seq,
                "player_ids": [player.player_id for player in players],
                "commit_order": [player.player_id for player in players],
            },
        )

        request_started = {player.player_id: asyncio.Event() for player in players}
        memory_tasks = {
            player.player_id: asyncio.create_task(
                self._generate_private_round_memory(
                    state=state,
                    player=player,
                    broadcaster=broadcaster,
                    batch_id=batch_id,
                    request_started=request_started[player.player_id],
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
                    },
                )
            except Exception:
                logger.exception("Live V2 could not persist private memory batch cancellation")
            raise

        if judge_task is None or not judge_task.result():
            self._repository.append_event(
                game_id=state.game_id,
                event_type="day_private_memory_batch_completed",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "batch_id": batch_id,
                    "public_summary_status": "failed",
                    "memories": [],
                    "commit_order": [player.player_id for player in players],
                },
            )
            return False

        committed: list[dict[str, Any]] = []
        for commit_index, player in enumerate(players, start=1):
            decision = memory_tasks[player.player_id].result()
            memory = decision.speech.strip() if decision is not None and decision.speech else ""
            if not memory:
                committed.append(
                    {
                        "player_id": player.player_id,
                        "status": "generation_failed",
                    }
                )
                continue
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
            fact_id, created = self._repository.record_private_round_memory(
                game_id=state.game_id,
                player_id=player.player_id,
                round_no=state.round_no,
                memory=normalized_memory,
                batch_id=batch_id,
                commit_index=commit_index,
            )
            committed.append(
                {
                    "player_id": player.player_id,
                    "status": "committed" if created else "reused",
                    "knowledge_fact_id": fact_id,
                }
            )

        self._repository.append_event(
            game_id=state.game_id,
            event_type="day_private_memory_batch_completed",
            audience="god_view",
            payload={
                "round_no": state.round_no,
                "batch_id": batch_id,
                "public_summary_status": "completed",
                "memories": committed,
                "commit_order": [player.player_id for player in players],
            },
        )
        return True

    async def _generate_private_round_memory(
        self,
        *,
        state: V2MatchSnapshot,
        player: V2MatchPlayer,
        broadcaster: V2BroadcastPort,
        batch_id: str,
        request_started: asyncio.Event,
    ) -> V2ModelDecision | None:
        request_started.set()
        return await self._player_action(
            game_id=state.game_id,
            player=player,
            broadcaster=broadcaster,
            action_type="private_round_memory",
            objective=(
                f"生成仅供你本人后续决策使用的第{state.round_no}轮私有记忆。"
                "概括本轮关键公开事实、你已知的私人事实、主要判断和下一轮待验证事项；"
                "不得编造未知身份或结果，使用第一人称并保持精简。"
            ),
            candidates=[],
            target_optional=None,
            output_kind="private_round_memory",
            decision_contract=V2DecisionContract(
                kind="speech",
                speech_mode="required",
                speech_max_chars=_PRIVATE_ROUND_MEMORY_MAX_CHARS,
                speech_max_sentences=4,
            ),
            audience="player_private",
            extra_context={
                "private_memory_batch_id": batch_id,
                "public_cutoff_record_seq": state.last_record_seq,
                "memory_round_no": state.round_no,
                "memory_visibility": "actor_only",
            },
            frozen_state=state,
            defer_presentation=True,
            isolated_failure=True,
            allow_failure=True,
            batch_id=batch_id,
        )

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
        self._actions.check_cancellation(state.game_id)
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
        target_optional: bool | None,
        output_kind: str,
        decision_contract: V2DecisionContract | None = None,
        audience: str = "all",
        extra_context: dict[str, Any] | None = None,
        frozen_state: V2MatchSnapshot | None = None,
        projection_at_seq: int | None = None,
        defer_presentation: bool = False,
        isolated_failure: bool = False,
        allow_failure: bool = False,
        batch_id: str | None = None,
        decision_family_id: str | None = None,
        prior_machine_format_failures: int = 0,
        automatic_machine_format_budget: int | None = None,
        prior_output_budget_failures: int = 0,
        automatic_output_budget_budget: int | None = None,
        preflight_pause_failure: V2PreflightPauseFailure | None = None,
        return_result: bool = False,
    ) -> V2ModelDecision | V2ActionResult | None:
        self._actions.check_cancellation(game_id)
        state = frozen_state or self._repository.snapshot(game_id)
        if projection_at_seq is not None and (
            frozen_state is None or projection_at_seq != frozen_state.last_record_seq
        ):
            raise V2DayRuntimeError(
                "projection_at_seq must equal the explicitly frozen state cutoff"
            )
        private_facts = self._repository.private_knowledge(
            game_id=game_id,
            player_id=player.player_id,
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
        resolved_contract = decision_contract or (
            V2DecisionContract(
                kind="speech",
                speech_max_chars=_PUBLIC_SPEECH_MAX_CHARS.get(action_type),
            )
            if output_kind == "public_speech"
            else V2DecisionContract(
                kind="target",
                target_mode="optional" if target_optional else "required",
            )
        )
        if resolved_contract.kind == "target" and target_optional is None:
            raise V2DayRuntimeError("target action requires target_optional")
        if resolved_contract.kind != "target" and target_optional is not None:
            raise V2DayRuntimeError("non-target action cannot set target_optional")
        spec = V2SpeechSpec(
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
            output_kind=output_kind,
            decision_contract=resolved_contract,
            allowed_target_ids=(
                tuple(item.player_id for item in candidates)
                if resolved_contract.kind == "target"
                else None
            ),
            model_players=tuple(
                V2ModelPlayerReference(
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
                **(extra_context or {}),
            },
            defer_presentation=defer_presentation,
            isolated_failure=isolated_failure,
            batch_id=batch_id,
            projection_at_seq=projection_at_seq,
            decision_family_id=decision_family_id,
            prior_machine_format_failures=prior_machine_format_failures,
            automatic_machine_format_budget=automatic_machine_format_budget,
            prior_output_budget_failures=prior_output_budget_failures,
            automatic_output_budget_budget=automatic_output_budget_budget,
            preflight_pause_failure=preflight_pause_failure,
        )
        if return_result and callable(getattr(self._actions, "run_player_decision_result", None)):
            result = await self._actions.run_player_decision_result(
                game_id=game_id,
                broadcaster=broadcaster,
                spec=spec,
            )
        else:
            decision = await self._actions.run_player_decision(
                game_id=game_id,
                broadcaster=broadcaster,
                spec=spec,
            )
            result = V2ActionResult(decision=decision)
        decision = result.decision if result is not None else None
        if decision is None and not allow_failure:
            raise V2DayRuntimeError(f"{action_type}_failed")
        if return_result:
            return result
        return decision

    def _record_speech(
        self,
        state: V2MatchSnapshot,
        player: V2MatchPlayer,
        decision: V2ModelDecision,
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


def _self_explosion_action_effect(
    *,
    state: V2MatchSnapshot,
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


def _required_target(decision: V2ModelDecision) -> str:
    if decision.target_player_id is None:
        raise V2DayRuntimeError("required vote target is missing")
    return decision.target_player_id


def _failure_code(exc: Exception) -> str:
    value = str(exc).strip()
    if not value:
        return "day_runtime_failed"
    return value[:120]
