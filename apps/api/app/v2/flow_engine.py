from __future__ import annotations

import asyncio
import logging

from app.v2.action_engine import V2ActionEngine, V2BroadcastPort, V2SpeechSpec
from app.v2.first_night_engine import V2FirstNightEngine
from app.v2.night_repository import V2NightRepository
from app.v2.protocol import game_phase_changed, live_state
from app.v2.repository import V2ActionRepository


logger = logging.getLogger(__name__)


class V2LiveFlowEngine:
    def __init__(
        self,
        *,
        action_repository: V2ActionRepository,
        night_repository: V2NightRepository,
        action_engine: V2ActionEngine,
        first_night_engine: V2FirstNightEngine,
    ) -> None:
        self._action_repository = action_repository
        self._night_repository = night_repository
        self._actions = action_engine
        self._first_night = first_night_engine

    async def run(self, *, game_id: str, broadcaster: V2BroadcastPort) -> None:
        try:
            await self._run_active(game_id=game_id, broadcaster=broadcaster)
        except asyncio.CancelledError:
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

    async def _run_active(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> None:
        opening_ok = await self._actions.run_judge_speech(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=V2SpeechSpec(
                action_type="judge_opening_speech",
                phase_id="opening",
                required_phase_state="opening_ready",
                objective="生成本场直播的法官开场播报",
                success_live_state="ready",
                success_phase_state="opening_speech_closed",
            ),
        )
        if not opening_ok:
            return
        self._action_repository.check_cancellation(game_id)
        try:
            transition = self._action_repository.transition_to_first_night(game_id=game_id)
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
            return
        await broadcaster.broadcast_json(game_phase_changed(transition))
        execute_first_night = self._night_repository.execution_enabled(game_id)
        nightfall_ok = await self._actions.run_judge_speech(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=V2SpeechSpec(
                action_type="judge_nightfall_announcement",
                phase_id="first_night",
                required_phase_state="nightfall_ready",
                objective="生成宣布本局进入首夜并提醒所有玩家闭眼的法官播报",
                success_live_state=("ready" if execute_first_night else "awaiting_observation"),
                success_phase_state="nightfall_announced",
            ),
        )
        if not nightfall_ok:
            return
        self._action_repository.check_cancellation(game_id)
        if not execute_first_night:
            return
        await self._first_night.run(game_id=game_id, broadcaster=broadcaster)
