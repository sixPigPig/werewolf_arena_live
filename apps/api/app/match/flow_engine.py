from __future__ import annotations

import asyncio
import logging

from app.match.action_engine import ActionEngine, BroadcastPort, SpeechSpec
from app.match.day_engine import DayEngine
from app.match.first_night_engine import NightEngine
from app.match.match_repository import MatchRepository
from app.match.night_repository import NightRepository
from app.match.protocol import game_phase_changed, live_state
from app.match.repository import (
    ActionRepository,
    ExecutionOwnershipLost,
    RepositoryError,
)


logger = logging.getLogger(__name__)


class LiveFlowEngine:
    def __init__(
        self,
        *,
        action_repository: ActionRepository,
        night_repository: NightRepository,
        match_repository: MatchRepository,
        action_engine: ActionEngine,
        first_night_engine: NightEngine,
        day_engine: DayEngine,
    ) -> None:
        self._action_repository = action_repository
        self._night_repository = night_repository
        self._match_repository = match_repository
        self._actions = action_engine
        self._first_night = first_night_engine
        self._day = day_engine

    async def run(self, *, game_id: str, broadcaster: BroadcastPort) -> None:
        try:
            await self._run_active(game_id=game_id, broadcaster=broadcaster)
            await self._actions.drain_presentations(game_id)
        except asyncio.CancelledError:
            await self._actions.abort_presentations(game_id)
            if not self._action_repository.stop_requested(game_id):
                raise
            result = self._action_repository.cancel_game(game_id)
            await broadcaster.set_current(None, 0)
            await broadcaster.broadcast_json(
                live_state(
                    game_id=game_id,
                    run_id=result.run_id,
                    state="canceled",
                    reason="operator_interrupted",
                )
            )
        except Exception:
            await self._actions.abort_presentations(game_id)
            raise

    async def _run_active(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> None:
        try:
            opening_state = self._match_repository.snapshot(game_id)
        except ExecutionOwnershipLost:
            raise
        except RepositoryError:
            opening_setup = None
        else:
            opening_setup = {
                "rule_name": opening_state.rule.get("name"),
                "player_count": len(opening_state.players),
                "role_summary": opening_state.rule.get("role_summary"),
                "max_rounds": opening_state.max_rounds,
            }
        opening_ok = await self._actions.run_judge_speech(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=SpeechSpec(
                action_type="judge_opening_speech",
                phase_id="opening",
                required_phase_state="opening_ready",
                objective="播报本场直播的固定法官开场词",
                success_live_state="ready",
                success_phase_state="opening_speech_closed",
                context={"game_setup": opening_setup} if opening_setup is not None else None,
            ),
        )
        if not opening_ok:
            return
        self._action_repository.check_cancellation(game_id)
        try:
            transition = self._action_repository.transition_to_first_night(game_id=game_id)
        except ExecutionOwnershipLost:
            raise
        except Exception as exc:
            logger.warning(
                "Live V2 phase transition failed",
                extra={"game_id": game_id, "failure_code": str(exc)},
            )
            run_id = self._action_repository.fail_phase_transition(
                game_id=game_id,
                failure_kind="protocol",
                failure_code="first_night_transition_failed",
            )
            await broadcaster.broadcast_json(
                live_state(
                    game_id=game_id,
                    run_id=run_id,
                    state="failed",
                    reason="first_night_transition_failed",
                )
            )
            await self._actions.abort_presentations(game_id)
            return
        await broadcaster.broadcast_json(game_phase_changed(transition))
        if not self._night_repository.execution_enabled(game_id):
            await self._announce_nightfall(
                game_id=game_id,
                phase_id="first_night",
                round_no=1,
                broadcaster=broadcaster,
                terminal=True,
            )
            return
        phase_id = "first_night"
        round_no = 1
        while True:
            self._action_repository.check_cancellation(game_id)
            if not await self._announce_nightfall(
                game_id=game_id,
                phase_id=phase_id,
                round_no=round_no,
                broadcaster=broadcaster,
                terminal=False,
            ):
                return
            day_transition = await self._first_night.run(
                game_id=game_id,
                broadcaster=broadcaster,
            )
            if day_transition is None or day_transition.phase_state == "game_completed":
                return
            self._action_repository.check_cancellation(game_id)
            await self._day.resolve_pending_death_aftermath(
                game_id=game_id,
                broadcaster=broadcaster,
            )
            night_transition = await self._day.run(
                game_id=game_id,
                broadcaster=broadcaster,
            )
            if night_transition is None or night_transition.phase_state in {
                "game_completed",
                "failed",
            }:
                return
            self._action_repository.check_cancellation(game_id)
            phase_id = night_transition.phase_id
            round_no += 1

    async def _announce_nightfall(
        self,
        *,
        game_id: str,
        phase_id: str,
        round_no: int,
        broadcaster: BroadcastPort,
        terminal: bool,
    ) -> bool:
        return await self._actions.run_judge_speech(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=SpeechSpec(
                action_type="judge_nightfall_announcement",
                phase_id=phase_id,
                required_phase_state="nightfall_ready",
                objective=(
                    "播报本局进入首夜并提醒所有玩家闭眼"
                    if round_no == 1
                    else f"播报本局进入第{round_no}夜并提醒存活玩家闭眼"
                ),
                success_live_state="awaiting_observation" if terminal else "ready",
                success_phase_state="nightfall_announced",
                context={"round_no": round_no},
            ),
        )
