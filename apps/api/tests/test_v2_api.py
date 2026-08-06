from __future__ import annotations

from collections.abc import AsyncIterator, Generator
import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.judge_configuration import configuration_from_voice_snapshot
from app.main import create_application
from app.models.admin import AuditEvent
from app.models.game_session import GameSessionRecord
from app.models.judge_configuration import JudgeConfigurationRecord
from app.models.live import LiveRunRecord
from app.models.model_configuration import ModelConfigurationRecord
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.models.user import User
from app.rule_sets.snapshots import compile_rule_set_config
from app.rule_sets.validation import normalize_rule_set_config
from app.v2.live_runtime import (
    V2ClientProtocolError,
    V2LiveRuntime,
    _GameChannel,
)
from app.v2 import match_repository as match_repository_module
from app.v2.action_engine import (
    V2ActionEngine,
    V2DecisionContract,
    V2ModelRetryPolicy,
    V2SpeechSpec,
)
from app.v2.day_engine import (
    V2DayEngine,
    _EXILE_PK_SPEECH_OBJECTIVE,
    _PUBLIC_SPEECH_MAX_CHARS,
    _SHERIFF_PK_SPEECH_OBJECTIVE,
    _leaders,
)
from app.v2.execution import bind_v2_run_fence
from app.v2.first_night_engine import V2NightEngine, _WorkingNight
from app.v2.match_repository import V2DayVoteCommit, V2MatchRepository
from app.v2.model_context import project_model_action_context
from app.v2.model_client import (
    V2ModelDecision,
    V2ModelError,
    V2ModelProgress,
    V2ModelTarget,
    V2QualityError,
    build_model_request_payload,
)
from app.v2.night_repository import V2NightRepository
from app.v2.models import (
    V2AbilityActivation,
    V2AbilityInstance,
    V2ActionWindow,
    V2EffectIntent,
    V2GameControlRequest,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2GodViewAccessGrant,
    V2LivePresentation,
    V2KnowledgeFact,
    V2MatchState,
    V2ModelActionRecovery,
    V2PlayerState,
    V2RoleAssignment,
    V2RoleAssignmentBatch,
    V2VoiceAsset,
)
from app.v2.repository import (
    V2ActionClaim,
    V2ActionRepository,
    V2ExecutionOwnershipLost,
    V2RepositoryError,
)
from app.v2.service import create_waiting_game


PCM_CHUNK = b"\x10\x00" * 240


def _nested_strings(value: Any) -> Generator[str, None, None]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _nested_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nested_strings(item)
    elif isinstance(value, str):
        yield value


def _private_known_facts(context: dict[str, Any]) -> list[dict[str, Any]]:
    known_events = context.get("known_events")
    known_events = known_events if isinstance(known_events, dict) else {}
    events = known_events.get("events")
    events = events if isinstance(events, list) else []
    return [
        {
            "fact_type": event.get("kind"),
            "payload": event.get("data"),
            "record_seq": event.get("record_seq"),
            "known_at_seq": event.get("known_at_seq"),
            "event_ref": event.get("event_ref"),
        }
        for event in events
        if isinstance(event, dict) and event.get("visibility") == "actor_private"
    ]


def _model_decision_stage(context: dict[str, Any]) -> str | None:
    return next(
        (
            str(event.get("data"))
            for event in context.get("known_events", {}).get("events", [])
            if event.get("kind") == "decision_stage"
        ),
        None,
    )


def _create_rotating_werewolf_game(
    *,
    session_factory: sessionmaker[Session],
    request: dict[str, Any],
    audio_mode: str,
) -> dict[str, str]:
    lobby = request["lobby_snapshot"]
    rule_set = dict(lobby["rule_set"])
    rule_set["werewolf_attack_policy"] = {
        "resolution": "plurality_rotating_tiebreak",
        "allow_no_attack": False,
        "allow_wolf_target": False,
    }
    rule_snapshot = {
        "schema_version": lobby["schema_version"],
        "source": "deterministic_integration_fixture",
        "model_binding_mode": lobby.get("model_binding_mode", "explicit_snapshot"),
        "rule_set_revision_id": lobby.get("rule_set_revision_id"),
        "seed": lobby.get("seed"),
        "max_rounds": lobby["max_rounds"],
        "allow_lineup_quality_warnings": lobby["allow_lineup_quality_warnings"],
        "lineup_quality_report": lobby["lineup_quality_report"],
        "rule_set": rule_set,
    }
    with session_factory() as db:
        players_snapshot: list[dict[str, Any]] = []
        for item in lobby["player_configs"]:
            model_configuration = db.get(
                ModelConfigurationRecord,
                (item["model_provider"], item["model"]),
            )
            assert model_configuration is not None
            players_snapshot.append(
                {
                    **item,
                    "model_parameters": dict(model_configuration.parameter_values),
                    "model_configuration_updated_at": (model_configuration.updated_at.isoformat()),
                }
            )
        game, run, god_view_access_token = create_waiting_game(
            db,
            title=request["title"],
            delivery_snapshot={
                "schema_version": 1,
                "mode": audio_mode,
                "source": "deterministic_integration_fixture",
            },
            rule_snapshot=rule_snapshot,
            players_snapshot=players_snapshot,
            judge_voice_snapshot={
                "schema_version": 1,
                "voice_mode": "fixed",
                "selected_tts_speaker": settings.live_v2_tts_judge_speaker,
                "random_tts_speakers": [],
                "configuration_version": 0,
            },
        )
        game_id = game.game_id
        run_id = run.run_id
    return {
        "game_id": game_id,
        "run_id": run_id,
        "snapshot_url": f"/api/v2/live/games/{game_id}/snapshot",
        "websocket_url": f"/api/v2/live/games/{game_id}/ws",
        "god_view_websocket_url": f"/api/v2/god-view/games/{game_id}/ws",
        "god_view_access_token": god_view_access_token,
    }


def _unfenced_text_only_night_engine(
    *,
    client: TestClient,
    session_factory: sessionmaker[Session],
    voice_root: Path,
) -> tuple[V2NightRepository, V2NightEngine]:
    runtime = client.app.state.v2_live_runtime
    action_engine = V2ActionEngine(
        repository=V2ActionRepository(session_factory),
        model_client=client.app.state.v2_test_model_client,
        tts_client=None,
        tts_client_factory=None,
        tts_capability_enabled=False,
        voice_root=voice_root,
        sample_rate=24000,
        judge_configuration_provider=(runtime._action_engine._judge_configuration_provider),
        model_retry_policy=V2ModelRetryPolicy(
            max_attempts=2,
            attempt_total_seconds=5,
            action_total_seconds=5,
            base_delay_seconds=0,
            jitter_seconds=0,
        ),
    )
    night_repository = V2NightRepository(session_factory)
    return night_repository, V2NightEngine(
        repository=night_repository,
        action_engine=action_engine,
        day_engine=runtime._day_engine,
    )


def _unfenced_text_only_day_engine(
    *,
    client: TestClient,
    session_factory: sessionmaker[Session],
    voice_root: Path,
) -> tuple[V2MatchRepository, V2DayEngine]:
    runtime = client.app.state.v2_live_runtime
    action_engine = V2ActionEngine(
        repository=V2ActionRepository(session_factory),
        model_client=client.app.state.v2_test_model_client,
        tts_client=None,
        tts_client_factory=None,
        tts_capability_enabled=False,
        voice_root=voice_root,
        sample_rate=24000,
        judge_configuration_provider=(runtime._action_engine._judge_configuration_provider),
        model_retry_policy=V2ModelRetryPolicy(
            max_attempts=2,
            attempt_total_seconds=5,
            action_total_seconds=5,
            base_delay_seconds=0,
            jitter_seconds=0,
        ),
    )
    repository = V2MatchRepository(session_factory)
    return repository, V2DayEngine(repository=repository, action_engine=action_engine)


class FakeV2ModelClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.contexts: list[dict[str, Any]] = []
        self.release = threading.Event()
        self.release.set()
        self.decision_contexts: list[dict[str, Any]] = []
        self.decline_action_types: set[str] = set()
        self.quality_failure_action_types: set[str] = set()
        self.quality_failures_remaining_by_action: dict[str, int] = {}
        self.unexpected_speech_target: str | None = None
        self.force_speech_action_types: set[str] = set()
        self.speech_by_action_type: dict[str, str] = {}
        self.speech_by_actor_and_action_type: dict[tuple[str, str], str] = {}
        self.decision_note_by_action_type: dict[str, str] = {}
        self.duplicate_json_action_types: set[str] = set()
        self.retryable_transport_failures_remaining = 0
        self.retryable_transport_failures_by_stage: dict[str, int] = {}
        self.split_werewolf_preferences = False
        self.werewolf_target_by_stage: dict[tuple[int, str, str], str | None] = {}
        self._preference_target_indexes: dict[str, int] = {}
        self.transport_failure = threading.Event()
        self.attempt_ids: list[str] = []
        self.call_delay_seconds = 0.0
        self.call_delays_seconds: list[float] = []
        self.concurrent_barrier_action_types: set[str] = set()
        self.concurrent_barrier_expected = 0
        self.concurrent_barrier_started = 0
        self.concurrent_barrier_in_flight = 0
        self.concurrent_barrier_max_in_flight = 0
        self.concurrent_barrier_all_started: asyncio.Event | None = None
        self.concurrent_barrier_first_started = threading.Event()

    def resolve_model_target(
        self,
        *,
        model_provider: str,
        model_id: str,
        model_parameters: dict[str, Any],
    ) -> V2ModelTarget:
        assert model_provider == "agent_plan"
        return V2ModelTarget(
            provider=model_provider,
            model_id=model_id,
            parameters=dict(model_parameters),
        )

    def build_request_payload(
        self,
        *,
        action_context: dict[str, Any],
        decision: bool,
        target: V2ModelTarget,
    ) -> dict[str, Any]:
        return build_model_request_payload(
            action_context,
            decision=decision,
            model_id=target.model_id,
            parameters=target.parameters,
        )

    async def generate_action_decision(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        target: V2ModelTarget,
        check_cancellation: Any = None,
    ) -> V2ModelDecision:
        if check_cancellation is not None:
            check_cancellation()
        self.call_count += 1
        self.contexts.append(action_context)
        self.decision_contexts.append(action_context)
        assert attempt_id.startswith("v2_model_")
        self.attempt_ids.append(attempt_id)
        assert target.provider == "agent_plan"
        assert target.model_id in {"private-model-id", "test-model"}
        call_delay_seconds = (
            self.call_delays_seconds.pop(0) if self.call_delays_seconds else self.call_delay_seconds
        )
        if call_delay_seconds > 0:
            await asyncio.sleep(call_delay_seconds)
        known_events = action_context.get("known_events", {})
        decision_stage = next(
            (
                event.get("data")
                for event in known_events.get("events", [])
                if event.get("kind") == "decision_stage"
            ),
            None,
        )
        stage_failures_remaining = self.retryable_transport_failures_by_stage.get(
            str(decision_stage),
            0,
        )
        if stage_failures_remaining > 0:
            self.retryable_transport_failures_by_stage[str(decision_stage)] = (
                stage_failures_remaining - 1
            )
            self.transport_failure.set()
            raise V2ModelError(
                "model_transport_failed",
                retryable=True,
                failure_stage="connect",
                exception_type="builtins.ConnectionResetError",
                errno=54,
                first_token_seen=False,
                elapsed_ms=5,
            )
        if self.retryable_transport_failures_remaining > 0:
            self.retryable_transport_failures_remaining -= 1
            self.transport_failure.set()
            raise V2ModelError(
                "model_transport_failed",
                retryable=True,
                failure_stage="connect",
                exception_type="builtins.ConnectionResetError",
                errno=54,
                first_token_seen=False,
                elapsed_ms=5,
            )
        action_type = action_context["task"]["type"]
        if (
            action_type in self.concurrent_barrier_action_types
            and self.concurrent_barrier_expected > 0
        ):
            if self.concurrent_barrier_all_started is None:
                self.concurrent_barrier_all_started = asyncio.Event()
            self.concurrent_barrier_first_started.set()
            self.concurrent_barrier_started += 1
            self.concurrent_barrier_in_flight += 1
            self.concurrent_barrier_max_in_flight = max(
                self.concurrent_barrier_max_in_flight,
                self.concurrent_barrier_in_flight,
            )
            if self.concurrent_barrier_started >= self.concurrent_barrier_expected:
                self.concurrent_barrier_all_started.set()
            await asyncio.wait_for(self.concurrent_barrier_all_started.wait(), timeout=5)
            self.concurrent_barrier_in_flight -= 1
        output_contract = action_context["response"]
        quality_failures_remaining = self.quality_failures_remaining_by_action.get(
            action_type,
            0,
        )
        if quality_failures_remaining > 0:
            self.quality_failures_remaining_by_action[action_type] = quality_failures_remaining - 1
        if action_type in self.quality_failure_action_types or quality_failures_remaining > 0:
            boolean_field = output_contract.get("field")
            raise V2QualityError(
                "model_decision_invalid_speech",
                raw_response=json.dumps(
                    {boolean_field or "decision": True},
                    separators=(",", ":"),
                ),
            )
        candidates = action_context["candidates"]
        boolean_field: str | None = None
        boolean_value: bool | None = None
        default_speech = "我先说明自己的判断。这是第二句话！\n现在执行这次实时决策。"
        if action_type == "private_round_memory":
            default_speech = (
                f"我是{action_context['self']['identity']['player_id']}，"
                "这一轮的判断只作为我下一轮继续验证的主观记忆。"
            )
        actor_id = str(action_context["self"]["identity"]["player_id"])
        speech: str | None = self.speech_by_actor_and_action_type.get(
            (actor_id, action_type),
            self.speech_by_action_type.get(action_type, default_speech),
        )
        if output_contract["speech"]["mode"] == "forbidden":
            speech = None
        if action_type in self.force_speech_action_types:
            speech = "这是模型违反禁言契约后额外返回的文本。"
        if output_contract["kind"] == "boolean":
            boolean_field = output_contract["field"]
            boolean_value = action_type not in self.decline_action_types
            target = None
            if not boolean_value and output_contract["speech"]["mode"] == "required_if_true":
                speech = None
        elif action_type in self.decline_action_types:
            target = None
        elif candidates:
            actor_id = str(action_context["self"]["identity"]["player_id"])
            night_no = int(action_context["task"].get("night_no") or 0)
            werewolf_stage_key = (night_no, str(decision_stage), actor_id)
            if werewolf_stage_key in self.werewolf_target_by_stage:
                target = self.werewolf_target_by_stage[werewolf_stage_key]
                candidate_ids = {str(candidate["player_id"]) for candidate in candidates}
                assert target is None or target in candidate_ids, (
                    werewolf_stage_key,
                    target,
                    sorted(candidate_ids),
                )
            elif (
                self.split_werewolf_preferences
                and decision_stage == "preference_probe"
                and len(candidates) > 1
            ):
                candidate_index = self._preference_target_indexes.setdefault(
                    actor_id,
                    len(self._preference_target_indexes) % 2,
                )
                target = candidates[candidate_index]["player_id"]
            else:
                target = candidates[0]["player_id"]
        elif output_contract["kind"] == "speech":
            target = self.unexpected_speech_target
        else:
            target = None
        decision_note = (
            self.decision_note_by_action_type.get(
                action_type,
                (
                    f"{action_context['self']['identity']['player_id']}在"
                    f"{action_type}动作发生时选择当前目标。"
                ),
            )
            if output_contract.get("decision_note", {}).get("mode") == "optional"
            else None
        )
        raw_output = (
            {
                boolean_field: boolean_value,
                **({"speech": speech} if speech is not None else {}),
                **({"decision_note": decision_note} if decision_note is not None else {}),
            }
            if boolean_field is not None
            else {
                "target_player_id": target,
                "speech": speech,
                **({"decision_note": decision_note} if decision_note is not None else {}),
            }
        )
        serialized_raw_output = json.dumps(raw_output, ensure_ascii=False)
        repair_kind: str | None = None
        if action_type in self.duplicate_json_action_types:
            serialized_raw_output = (
                f"{serialized_raw_output}\n```json\n"
                f"{json.dumps(raw_output, ensure_ascii=False, indent=2)}\n```"
            )
            repair_kind = "duplicate_identical_json_ignored"
        return V2ModelDecision(
            target_player_id=target,
            speech=speech,
            provider_request_id="provider-decision-test",
            first_token_ms=11,
            completed_ms=29,
            raw_response=serialized_raw_output,
            boolean_field=boolean_field,
            boolean_value=boolean_value,
            decision_note=decision_note,
            repair_kind=repair_kind,
        )


class _ProgressThenSlowModelClient(FakeV2ModelClient):
    def __init__(
        self,
        *,
        first_attempt_progress: tuple[V2ModelProgress, ...] | None = None,
    ) -> None:
        super().__init__()
        self.progress_calls = 0
        self.first_attempt_progress = (
            first_attempt_progress
            if first_attempt_progress is not None
            else (
                V2ModelProgress(
                    stage="response_headers",
                    provider_request_id="provider-header-progress",
                    elapsed_ms=3,
                    response_headers={
                        "x-request-id": "provider-header-progress",
                        "x-ratelimit-remaining-requests": "9",
                    },
                ),
                V2ModelProgress(
                    stage="first_token",
                    provider_request_id="provider-stream-progress",
                    elapsed_ms=7,
                    token_kind="reasoning",
                ),
                V2ModelProgress(
                    stage="first_text",
                    provider_request_id="provider-stream-progress",
                    elapsed_ms=9,
                    token_kind="text",
                ),
            )
        )

    async def generate_action_decision_with_progress(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        target: V2ModelTarget,
        check_cancellation: Any = None,
        on_progress: Any = None,
    ) -> V2ModelDecision:
        self.progress_calls += 1
        if self.progress_calls == 1:
            assert on_progress is not None
            for progress in self.first_attempt_progress:
                on_progress(progress)
            await asyncio.sleep(0.08)
            raise AssertionError("outer attempt timeout did not cancel the slow model call")
        return await super().generate_action_decision(
            action_context=action_context,
            attempt_id=attempt_id,
            target=target,
            check_cancellation=check_cancellation,
        )


class FakeV2TtsClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.speakers: list[str | None] = []
        self.dialects: list[str | None] = []
        self.first_chunk = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.failure_text_fragments: set[str] = set()

    async def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
        speaker: str | None = None,
        dialect: str | None = None,
        check_cancellation: Any = None,
    ) -> AsyncIterator[bytes]:
        self.call_count += 1
        self.speakers.append(speaker)
        self.dialects.append(dialect)
        assert text.endswith(("。", "！", "？"))
        assert attempt_id.startswith("v2_tts_")
        if any(fragment in text for fragment in self.failure_text_fragments):
            raise RuntimeError("scripted TTS failure")
        yield PCM_CHUNK
        self.first_chunk.set()
        if not self.release.is_set():
            released = await asyncio.to_thread(self.release.wait, 5)
            if not released:
                raise RuntimeError("test TTS release timed out")
        if check_cancellation is not None:
            check_cancellation()
        yield PCM_CHUNK


class _ScriptedDayActionEngine:
    def __init__(self, targets: dict[str, str | None]) -> None:
        self.targets = targets
        self.player_actions: list[str] = []
        self.judge_actions: list[str] = []

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision(self, *, spec, **_kwargs) -> V2ModelDecision:
        self.player_actions.append(spec.actor_id)
        assert spec.decision_contract.decision_note_mode == "optional"
        assert spec.decision_contract.decision_note_max_chars == 80
        return V2ModelDecision(
            target_player_id=self.targets[spec.actor_id],
            speech="我决定发动技能。",
            provider_request_id="provider-scripted-decision",
            first_token_ms=1,
            completed_ms=2,
            decision_note="这个终局理由只保留在动作审计中。",
        )

    async def run_judge_speech(self, *, spec, **_kwargs) -> bool:
        self.judge_actions.append(spec.action_type)
        return True


class _ConcurrentSelfExplosionActions:
    def __init__(
        self,
        *,
        expected_wolves: int,
        affirmative_actor_ids: set[str],
    ) -> None:
        self._expected_wolves = expected_wolves
        self._affirmative_actor_ids = affirmative_actor_ids
        self._started = 0
        self._in_flight = 0
        self._completed = 0
        self._all_started = asyncio.Event()
        self.batch_completed = asyncio.Event()
        self.max_in_flight = 0
        self.self_explosion_specs: list[Any] = []
        self.action_types: list[str] = []

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision(self, *, spec, **_kwargs) -> V2ModelDecision:
        self.action_types.append(spec.action_type)
        if spec.action_type != "werewolf_self_explosion":
            assert self.batch_completed.is_set()
            return V2ModelDecision(
                target_player_id=None,
                speech=f"{spec.actor_id}完成公开发言。",
                provider_request_id="provider-discussion",
                first_token_ms=1,
                completed_ms=2,
            )

        self.self_explosion_specs.append(spec)
        assert spec.defer_presentation is True
        assert spec.isolated_failure is True
        self._started += 1
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        if self._started == self._expected_wolves:
            self._all_started.set()
        await asyncio.wait_for(self._all_started.wait(), timeout=1)
        self._in_flight -= 1
        self._completed += 1
        if self._completed == self._expected_wolves:
            self.batch_completed.set()
        return V2ModelDecision(
            target_player_id=None,
            speech=None,
            provider_request_id=f"provider-{spec.actor_id}",
            first_token_ms=1,
            completed_ms=2,
            boolean_field="explode",
            boolean_value=spec.actor_id in self._affirmative_actor_ids,
            decision_note=f"{spec.actor_id}在当前阶段的自爆判断。",
        )

    async def run_judge_speech(self, **_kwargs) -> bool:
        return True


class _ConcurrentSheriffBooleanActions:
    def __init__(self, *, expected_players: int, surviving_candidate_id: str) -> None:
        self._expected_players = expected_players
        self._surviving_candidate_id = surviving_candidate_id
        self._started = {"sheriff_run": 0, "sheriff_withdraw": 0}
        self._in_flight = {"sheriff_run": 0, "sheriff_withdraw": 0}
        self._completed = {"sheriff_run": 0, "sheriff_withdraw": 0}
        self._all_started = {
            "sheriff_run": asyncio.Event(),
            "sheriff_withdraw": asyncio.Event(),
        }
        self.batch_completed = {
            "sheriff_run": asyncio.Event(),
            "sheriff_withdraw": asyncio.Event(),
        }
        self.max_in_flight = {"sheriff_run": 0, "sheriff_withdraw": 0}
        self.boolean_specs: dict[str, list[Any]] = {
            "sheriff_run": [],
            "sheriff_withdraw": [],
        }
        self.campaign_specs: list[Any] = []

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision(self, *, spec, **_kwargs) -> V2ModelDecision | None:
        action_type = spec.action_type
        if action_type == "sheriff_campaign_speech":
            assert self.batch_completed["sheriff_run"].is_set()
            self.campaign_specs.append(spec)
            return V2ModelDecision(
                target_player_id=None,
                speech=f"{spec.actor_id}竞选警长。",
                provider_request_id=f"provider-campaign-{spec.actor_id}",
                first_token_ms=1,
                completed_ms=2,
            )

        assert action_type in self.boolean_specs
        if action_type == "sheriff_withdraw":
            assert len(self.campaign_specs) == self._expected_players
        assert spec.defer_presentation is True
        assert spec.isolated_failure is True
        self.boolean_specs[action_type].append(spec)
        self._started[action_type] += 1
        self._in_flight[action_type] += 1
        self.max_in_flight[action_type] = max(
            self.max_in_flight[action_type],
            self._in_flight[action_type],
        )
        if self._started[action_type] == self._expected_players:
            self._all_started[action_type].set()
        await asyncio.wait_for(self._all_started[action_type].wait(), timeout=1)
        self._in_flight[action_type] -= 1
        self._completed[action_type] += 1
        if self._completed[action_type] == self._expected_players:
            self.batch_completed[action_type].set()

        if action_type == "sheriff_withdraw" and spec.actor_id == self._surviving_candidate_id:
            return None
        boolean_field = "run_for_sheriff" if action_type == "sheriff_run" else "withdraw"
        return V2ModelDecision(
            target_player_id=None,
            speech=None,
            provider_request_id=f"provider-{action_type}-{spec.actor_id}",
            first_token_ms=1,
            completed_ms=2,
            boolean_field=boolean_field,
            boolean_value=True,
        )

    async def run_judge_speech(self, **_kwargs) -> bool:
        return True


class _ConcurrentVoteActions:
    def __init__(
        self,
        *,
        expected_voters: int,
        initial_fail_actor_ids: set[str] | None = None,
        concurrent_recovery_fail_actor_ids: set[str] | None = None,
    ) -> None:
        self._expected_voters = expected_voters
        self._initial_fail_actor_ids = initial_fail_actor_ids or set()
        self._concurrent_recovery_fail_actor_ids = concurrent_recovery_fail_actor_ids or set()
        self._initial_started = 0
        self._initial_in_flight = 0
        self._initial_completed = 0
        self._initial_all_started = asyncio.Event()
        self._concurrent_recovery_started = 0
        self._concurrent_recovery_in_flight = 0
        self._concurrent_recovery_completed = 0
        self._concurrent_recovery_all_started = asyncio.Event()
        self.initial_batch_completed = asyncio.Event()
        self.concurrent_recovery_batch_completed = asyncio.Event()
        self.max_in_flight = 0
        self.concurrent_recovery_max_in_flight = 0
        self.initial_specs: list[Any] = []
        self.concurrent_recovery_specs: list[Any] = []
        self.sequential_recovery_specs: list[Any] = []

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision(self, *, spec, **_kwargs) -> V2ModelDecision | None:
        assert spec.action_type == "exile_vote"
        stage = spec.context["vote_batch_stage"]
        if stage == "concurrent_initial":
            assert spec.defer_presentation is True
            assert spec.isolated_failure is True
            self.initial_specs.append(spec)
            self._initial_started += 1
            self._initial_in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._initial_in_flight)
            if self._initial_started == self._expected_voters:
                self._initial_all_started.set()
            await asyncio.wait_for(self._initial_all_started.wait(), timeout=1)
            self._initial_in_flight -= 1
            self._initial_completed += 1
            if self._initial_completed == self._expected_voters:
                self.initial_batch_completed.set()
            if spec.actor_id in self._initial_fail_actor_ids:
                return None
        elif stage == "concurrent_recovery":
            assert self.initial_batch_completed.is_set()
            assert spec.actor_id in self._initial_fail_actor_ids
            assert spec.defer_presentation is True
            assert spec.isolated_failure is True
            self.concurrent_recovery_specs.append(spec)
            self._concurrent_recovery_started += 1
            self._concurrent_recovery_in_flight += 1
            self.concurrent_recovery_max_in_flight = max(
                self.concurrent_recovery_max_in_flight,
                self._concurrent_recovery_in_flight,
            )
            if self._concurrent_recovery_started == len(self._initial_fail_actor_ids):
                self._concurrent_recovery_all_started.set()
            await asyncio.wait_for(self._concurrent_recovery_all_started.wait(), timeout=1)
            self._concurrent_recovery_in_flight -= 1
            self._concurrent_recovery_completed += 1
            if self._concurrent_recovery_completed == len(self._initial_fail_actor_ids):
                self.concurrent_recovery_batch_completed.set()
            if spec.actor_id in self._concurrent_recovery_fail_actor_ids:
                return None
        else:
            assert stage == "sequential_recovery"
            assert self.concurrent_recovery_batch_completed.is_set()
            assert spec.actor_id in self._concurrent_recovery_fail_actor_ids
            assert spec.defer_presentation is False
            assert spec.isolated_failure is False
            self.sequential_recovery_specs.append(spec)
        assert spec.allowed_target_ids
        return V2ModelDecision(
            target_player_id=spec.allowed_target_ids[0],
            speech=None,
            provider_request_id=f"provider-{spec.actor_id}",
            first_token_ms=1,
            completed_ms=2,
            decision_note=f"{spec.actor_id}选择首个合法候选。",
        )


class _ConcurrentPrivateMemoryActions:
    def __init__(
        self,
        *,
        expected_players: int,
        failed_actor_ids: set[str] | None = None,
        canceled_actor_id: str | None = None,
    ) -> None:
        self._expected_players = expected_players
        self._failed_actor_ids = failed_actor_ids or set()
        self._canceled_actor_id = canceled_actor_id
        self._started = 0
        self._in_flight = 0
        self._all_started = asyncio.Event()
        self._release = asyncio.Event()
        self.max_in_flight = 0
        self.judge_overlapped = False
        self.memory_specs: list[Any] = []
        self.judge_specs: list[Any] = []

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision(self, *, spec, **_kwargs) -> V2ModelDecision | None:
        assert spec.action_type == "private_round_memory"
        assert spec.defer_presentation is True
        assert spec.isolated_failure is True
        assert spec.audience == "player_private"
        self.memory_specs.append(spec)
        self._started += 1
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        if self._started == self._expected_players:
            self._all_started.set()
        await asyncio.wait_for(self._all_started.wait(), timeout=1)
        if spec.actor_id == self._canceled_actor_id:
            raise asyncio.CancelledError
        await asyncio.wait_for(self._release.wait(), timeout=1)
        self._in_flight -= 1
        if spec.actor_id in self._failed_actor_ids:
            return None
        return V2ModelDecision(
            target_player_id=None,
            speech=f"我是{spec.actor_id}，这是我对第1轮的非公开记忆。",
            provider_request_id=f"provider-memory-{spec.actor_id}",
            first_token_ms=1,
            completed_ms=2,
        )

    async def run_judge_speech(self, *, spec, **_kwargs) -> bool:
        assert spec.action_type == "judge_day_summary"
        self.judge_specs.append(spec)
        await asyncio.wait_for(self._all_started.wait(), timeout=1)
        self.judge_overlapped = self._in_flight == self._expected_players
        self._release.set()
        return True


class _CollectingBroadcaster:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []
        self.audio: list[tuple[str, bytes]] = []
        self.currents: list[tuple[str, Any, int]] = []

    async def broadcast_json(self, value: dict[str, Any], *, audience: str = "all") -> None:
        self.messages.append((audience, value))

    async def broadcast_bytes(self, value: bytes, *, audience: str = "all") -> None:
        self.audio.append((audience, value))

    async def broadcast_audio(
        self,
        value: bytes,
        *,
        identity: Any,
        next_sample_cursor: int,
        audience: str = "all",
    ) -> None:
        self.audio.append((audience, value))

    async def set_current(
        self,
        identity: Any,
        sample_cursor: int,
        *,
        audience: str = "all",
    ) -> None:
        self.currents.append((audience, identity, sample_cursor))


class _BlockingWebSocket:
    def __init__(self, *, block_audio: bool = False) -> None:
        self.block_audio = block_audio
        self.audio_started = asyncio.Event()
        self.release_audio = asyncio.Event()
        self.json_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []

    async def send_json(self, value: dict[str, Any]) -> None:
        self.json_messages.append(value)

    async def send_bytes(self, value: bytes) -> None:
        self.audio_started.set()
        if self.block_audio:
            await self.release_audio.wait()
        self.binary_messages.append(value)


@pytest.fixture
def v2_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session], Path], None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "v2-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "V2 Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "viewer")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "v2_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    voice_root = tmp_path / "v2-voices"
    monkeypatch.setattr(settings, "live_v2_voice_storage_dir", str(voice_root))

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with testing_session.begin() as db:
        for model_id in ("private-model-id", "test-model"):
            db.add(
                ModelConfigurationRecord(
                    provider="agent_plan",
                    model_id=model_id,
                    source_model_id=model_id,
                    display_name=model_id,
                    available=True,
                    enabled=True,
                    is_default=model_id == "test-model",
                    supports_thinking=True,
                    parameter_values={
                        "thinking": "disabled",
                        "max_tokens": 512,
                    },
                    source_details={"source": "test"},
                )
            )

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    model_client = FakeV2ModelClient()
    tts_client = FakeV2TtsClient()

    def judge_configuration_provider(game_id: str):
        with testing_session() as db:
            game = db.get(V2GameRecord, game_id)
            assert game is not None
            configuration = configuration_from_voice_snapshot(game.judge_voice_snapshot)
            assert configuration is not None
            return configuration

    application.state.v2_live_runtime = V2LiveRuntime(
        session_factory=testing_session,
        model_client=model_client,
        tts_client=tts_client,
        voice_root=voice_root,
        sample_rate=24000,
        judge_configuration_provider=judge_configuration_provider,
        model_retry_policy=V2ModelRetryPolicy(
            max_attempts=2,
            attempt_total_seconds=5,
            action_total_seconds=5,
            base_delay_seconds=0,
            jitter_seconds=0,
        ),
    )
    application.state.v2_test_model_client = model_client
    application.state.v2_test_tts_client = tts_client
    with TestClient(application) as client:
        yield client, testing_session, voice_root
    engine.dispose()


def test_v2_meta_is_independent_from_v1(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context

    response = client.get("/api/v2/meta")

    assert response.status_code == 200
    assert response.json() == {
        "api_version": "v2",
        "status": "realtime_complete_match",
    }
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/health").status_code == 200


def test_existing_mobile_lobby_creates_one_waiting_v2_game_with_snapshots(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context

    response = client.post("/api/v2/games", json=_lobby_create_request())

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "waiting_to_start"
    assert created["game_id"].startswith("v2_game_")
    assert created["run_id"].startswith("v2_run_")
    assert created["websocket_url"].endswith(f"/{created['game_id']}/ws")
    assert created["director_snapshot_url"].endswith(f"/{created['game_id']}/snapshot")
    assert created["director_websocket_url"].endswith(f"/{created['game_id']}/ws")
    assert created["god_view_snapshot_url"].endswith(f"/{created['game_id']}/identity-snapshot")
    assert created["god_view_websocket_url"].endswith(f"/{created['game_id']}/ws")
    assert len(created["god_view_access_token"]) >= 32
    with session_factory() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == created["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assignment_batch = db.scalar(
            select(V2RoleAssignmentBatch).where(V2RoleAssignmentBatch.game_id == created["game_id"])
        )
        god_view_grant = db.get(V2GodViewAccessGrant, created["game_id"])
        assignments = list(
            db.scalars(
                select(V2RoleAssignment)
                .where(V2RoleAssignment.game_id == created["game_id"])
                .order_by(V2RoleAssignment.seat)
            )
        )
        assert game is not None and game.title == "经典 8 人"
        assert game.status == "waiting_to_start"
        assert (game.phase_seq, game.phase_id, game.phase_state) == (
            1,
            "opening",
            "opening_ready",
        )
        assert game.last_record_seq == 3
        assert game.rule_snapshot["source"] == "existing_mobile_lobby"
        assert game.rule_snapshot["rule_set"]["id"] == "classic_8"
        assert game.rule_snapshot["rule_set_revision_id"] == "rule_rev_123"
        assert game.rule_snapshot["seed"] == 42
        assert game.rule_snapshot["max_rounds"] == 8
        assert game.judge_voice_snapshot == {
            "schema_version": 1,
            "voice_mode": "fixed",
            "selected_tts_speaker": "zh_female_vv_uranus_bigtts",
            "random_tts_speakers": [],
            "configuration_version": 0,
        }
        assert [
            {key: value for key, value in item.items() if key != "model_configuration_updated_at"}
            for item in game.players_snapshot
        ] == [
            {
                "seat": 1,
                "profile_id": "profile-1",
                "name": "阿青",
                "model_provider": "agent_plan",
                "model": "private-model-id",
                "model_parameters": {
                    "thinking": "disabled",
                    "max_tokens": 512,
                },
                "personality": "private personality prompt",
                "avatar_image_url": "/api/v1/public/player-profiles/profile-1/avatar",
                "strategy_profile": "private-strategy",
                "tts_speaker": "private-speaker",
            },
            {
                "seat": 2,
                "profile_id": "profile-2",
                "name": "白石",
                "model_provider": "agent_plan",
                "model": "test-model",
                "model_parameters": {
                    "thinking": "disabled",
                    "max_tokens": 512,
                },
            },
        ]
        assert all(item["model_configuration_updated_at"] for item in game.players_snapshot)
        assert run is not None and run.status == "waiting_to_start"
        assert run.started_at is None
        assert created["audio_mode"] == "tts"
        assert game.delivery_snapshot == {
            "schema_version": 1,
            "mode": "tts",
            "source": "legacy_runtime_default",
        }
        assert god_view_grant is not None
        assert (
            god_view_grant.token_sha256
            == hashlib.sha256(created["god_view_access_token"].encode()).hexdigest()
        )
        assert god_view_grant.token_sha256 != created["god_view_access_token"]
        assert assignment_batch is not None
        assert assignment_batch.player_count == 2
        assert len(assignment_batch.seed_hex) == 64
        assert len(assignment_batch.assignment_digest) == 64
        assert [(item.seat, item.player_id) for item in assignments] == [
            (1, "profile-1"),
            (2, "profile-2"),
        ]
        assert sorted((item.role, item.team) for item in assignments) == [
            ("villager", "village"),
            ("werewolf", "werewolves"),
        ]
        assert sorted((item.role_key, item.team) for item in assignments) == [
            ("villager", "village"),
            ("werewolf", "werewolves"),
        ]
        assert all(item.assignment_id == assignment_batch.assignment_id for item in assignments)
        assert [event.event_type for event in events] == [
            "game_created",
            "roles_assigned",
            "ability_runtime_compiled",
        ]

        assert events[0].payload == {
            "audience": "all",
            "audience_contract_version": 1,
            "title": "经典 8 人",
            "start_mode": "first_ready_viewer",
            "creation_source": "existing_mobile_lobby",
            "rule_set_id": "classic_8",
            "player_count": 2,
            "judge_voice": game.judge_voice_snapshot,
            "delivery_snapshot": game.delivery_snapshot,
            "model_context_contract": {
                "model_context_schema_version": 9,
                "prompt_template_version": 2,
                "known_events_schema_version": 3,
                "ledger_schema_version": 3,
                "model_view_schema_version": 3,
                "model_view_selector_version": 1,
            },
        }
        assert events[1].payload == {
            "audience": "god_view",
            "audience_contract_version": 1,
            "assignment_id": assignment_batch.assignment_id,
            "assigned_count": 2,
            "visibility": "private_sealed",
        }
        assert events[2].payload == {
            "audience": "god_view",
            "audience_contract_version": 1,
            "ability_snapshot_hash": game.ability_snapshot_hash,
            "registry_version": 1,
            "instance_count": 1,
            "execution_enabled": False,
        }
        assert game.ability_snapshot["instances"][0]["ability_id"] == "werewolf.attack"
        assert len(game.ability_snapshot_hash or "") == 64
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2PlayerState)
                .where(V2PlayerState.game_id == created["game_id"])
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2AbilityInstance)
                .where(V2AbilityInstance.game_id == created["game_id"])
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2LivePresentation)
                .where(V2LivePresentation.game_id == created["game_id"])
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2VoiceAsset)
                .where(V2VoiceAsset.game_id == created["game_id"])
            )
            == 0
        )

    snapshot = client.get(
        created["snapshot_url"],
        headers={"Authorization": f"Bearer {created['god_view_access_token']}"},
    )
    assert snapshot.status_code == 200
    assert set(snapshot.json()) == {
        "protocol_version",
        "type",
        "api_version",
        "audience",
        "game_id",
        "run_id",
        "live_state",
        "audio_mode",
        "match_status",
        "execution_state",
        "winner",
        "completion_reason",
        "completed_at",
        "game_phase",
        "match_state",
        "latest_presentation_seq",
        "server_time",
        "public_rule",
        "public_players",
        "public_role_assignment",
        "current_presentation",
    }
    assert snapshot.json()["game_phase"] == {
        "phase_seq": 1,
        "phase_id": "opening",
        "phase_state": "opening_ready",
    }
    assert snapshot.json()["live_state"] == "waiting_to_start"
    assert snapshot.json()["match_state"] == {
        "round_no": 1,
        "sheriff_player_id": None,
        "sheriff_badge_state": "disabled",
        "winner": None,
    }
    public_rule = snapshot.json()["public_rule"]
    assert public_rule == {
        "rule_id": "classic_8",
        "name": "经典 8 人",
        "version": "1",
        "player_count": 2,
        "roles": [
            {"role": "werewolf", "count": 1},
            {"role": "villager", "count": 1},
        ],
        "max_rounds": 8,
        "sheriff_enabled": False,
        "werewolf_self_explosion_enabled": True,
        "exile_last_words_enabled": True,
        "first_night_last_words_enabled": False,
    }
    assert set(public_rule) == {
        "rule_id",
        "name",
        "version",
        "player_count",
        "roles",
        "max_rounds",
        "sheriff_enabled",
        "werewolf_self_explosion_enabled",
        "exile_last_words_enabled",
        "first_night_last_words_enabled",
    }
    public_players = snapshot.json()["public_players"]
    assert snapshot.json()["public_role_assignment"] == {
        "state": "sealed",
        "assigned_count": 2,
    }
    serialized_public_snapshot = json.dumps(snapshot.json())
    assert assignment_batch.assignment_id not in serialized_public_snapshot
    assert "seed_hex" not in serialized_public_snapshot
    assert "assignment_digest" not in serialized_public_snapshot
    assert '"team"' not in serialized_public_snapshot
    assert public_players == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": "/api/v1/public/player-profiles/profile-1/avatar",
            "alive": True,
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "白石",
            "avatar_url": None,
            "alive": True,
        },
    ]
    assert all(
        set(player) == {"seat", "player_id", "display_name", "avatar_url", "alive"}
        for player in public_players
    )

    director = client.get(created["director_snapshot_url"])
    assert director.status_code == 200, director.text
    assert director.headers["cache-control"] == "private, no-store"
    director_payload = director.json()
    assert set(director_payload) == {
        "protocol_version",
        "type",
        "api_version",
        "audience",
        "game_id",
        "run_id",
        "live_state",
        "audio_mode",
        "match_status",
        "execution_state",
        "winner",
        "completion_reason",
        "completed_at",
        "game_phase",
        "match_state",
        "latest_presentation_seq",
        "server_time",
        "rule",
        "players",
        "current_scene",
        "current_presentation",
    }
    assert director_payload["type"] == "director.live_snapshot"
    assert director_payload["audience"] == "spectator_directed"
    assert director_payload["current_scene"] == {
        "scene_kind": "opening",
        "action_id": None,
        "action_type": None,
        "ability_id": None,
        "actor_player_id": None,
    }
    assert [item["role"] for item in director_payload["players"]]
    serialized_director = json.dumps(director_payload)
    assert "private-model-id" not in serialized_director
    assert "private personality prompt" not in serialized_director
    assert "private-strategy" not in serialized_director
    assert "private-speaker" not in serialized_director

    god_view_url = created["god_view_snapshot_url"]
    assert client.get(god_view_url).status_code == 403
    assert (
        client.get(
            god_view_url,
            headers={"Authorization": f"Bearer {'x' * 43}"},
        ).status_code
        == 403
    )
    god_view = client.get(
        god_view_url,
        headers={"Authorization": f"Bearer {created['god_view_access_token']}"},
    )
    assert god_view.status_code == 200, god_view.text
    assert god_view.headers["cache-control"] == "private, no-store"
    god_payload = god_view.json()
    assert set(god_payload) == {
        "protocol_version",
        "type",
        "api_version",
        "audience",
        "game_id",
        "run_id",
        "live_state",
        "audio_mode",
        "match_status",
        "execution_state",
        "winner",
        "completion_reason",
        "completed_at",
        "game_phase",
        "match_state",
        "server_time",
        "rule",
        "players",
    }
    assert god_payload["type"] == "god_view.identity_snapshot"
    assert god_payload["audience"] == "spectator_god_view"
    assignment_by_seat = {item.seat: item for item in assignments}
    assert god_payload["players"] == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": "/api/v1/public/player-profiles/profile-1/avatar",
            "role": assignment_by_seat[1].role,
            "team": assignment_by_seat[1].team,
            "alive": True,
            "death_cause": None,
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "白石",
            "avatar_url": None,
            "role": assignment_by_seat[2].role,
            "team": assignment_by_seat[2].team,
            "alive": True,
            "death_cause": None,
        },
    ]
    serialized_god_view = json.dumps(god_payload)
    assert created["god_view_access_token"] not in serialized_god_view
    assert "private-model-id" not in serialized_god_view
    assert "private personality prompt" not in serialized_god_view
    assert "private-strategy" not in serialized_god_view
    assert "private-speaker" not in serialized_god_view


def test_v2_create_freezes_explicit_werewolf_attack_policy(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    policy = {
        "resolution": "plurality_seeded_random",
        "allow_no_attack": True,
        "allow_wolf_target": False,
    }
    request = _lobby_create_request()
    request["lobby_snapshot"]["rule_set"]["werewolf_attack_policy"] = policy

    response = client.post("/api/v2/games", json=request)

    assert response.status_code == 201, response.text
    with session_factory() as db:
        game = db.get(V2GameRecord, response.json()["game_id"])
        assert game is not None
        assert game.rule_snapshot["rule_set"]["werewolf_attack_policy"] == policy
        assert game.ability_snapshot["policies"]["werewolf_attack"] == policy


@pytest.mark.parametrize(
    "policy",
    [
        {
            "resolution": "unsupported_resolution",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        },
        {
            "resolution": "plurality_rotating_tiebreak",
            "allow_no_attack": False,
            "allow_wolf_target": False,
            "unexpected": True,
        },
        {
            "resolution": "plurality_rotating_tiebreak",
            "allow_no_attack": 0,
            "allow_wolf_target": "false",
        },
    ],
)
def test_v2_create_rejects_invalid_werewolf_attack_policy(
    v2_context,
    policy: dict[str, Any],
) -> None:
    client, session_factory, _voice_root = v2_context
    request = _lobby_create_request()
    request["lobby_snapshot"]["rule_set"]["werewolf_attack_policy"] = policy

    response = client.post("/api/v2/games", json=request)

    assert response.status_code == 422
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(V2GameRecord)) == 0


def test_v2_create_rejects_mismatched_rule_revision(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    request = _lobby_create_request()
    request["lobby_snapshot"]["rule_set"]["revision_id"] = "rule_rev_stale"

    response = client.post("/api/v2/games", json=request)

    assert response.status_code == 422
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(V2GameRecord)) == 0


def test_director_websocket_starts_with_its_own_ready_contract(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_lobby_create_request()).json()
    model_client = client.app.state.v2_test_model_client
    model_client.release.clear()

    with client.websocket_connect(created["director_websocket_url"]) as socket:
        initial = socket.receive_json()
        assert initial["type"] == "director.live_snapshot"
        assert initial["audience"] == "spectator_directed"
        assert initial["live_state"] == "waiting_to_start"
        assert [item["role"] for item in initial["players"]]

        socket.send_json(_ready_message("director.ready"))
        started = socket.receive_json()
        assert started["type"] == "director.live_snapshot"
        assert started["audience"] == "spectator_directed"
        assert started["live_state"] == "ready"


def test_public_and_god_view_share_two_realtime_actions_without_replay(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json=_lobby_create_request()).json()
    god_protocols = ["live-v2-god-view", identifiers["god_view_access_token"]]

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            identifiers["god_view_websocket_url"],
            subprotocols=["live-v2-god-view", "x" * 43],
        ):
            pass

    model_client = client.app.state.v2_test_model_client
    tts_client = client.app.state.v2_test_tts_client
    model_client.release.clear()
    with client.websocket_connect(identifiers["websocket_url"]) as public_socket:
        with client.websocket_connect(
            identifiers["god_view_websocket_url"],
            subprotocols=god_protocols,
        ) as god_socket:
            public_initial = public_socket.receive_json()
            god_initial = god_socket.receive_json()
            assert public_initial["type"] == "live.snapshot"
            assert public_initial["audience"] == "player_public"
            assert "players" not in public_initial
            assert god_socket.accepted_subprotocol == "live-v2-god-view"
            assert god_initial["type"] == "god_view.live_snapshot"
            assert god_initial["audience"] == "spectator_god_view"
            assert public_initial["live_state"] == "waiting_to_start"
            assert god_initial["live_state"] == "waiting_to_start"
            assert [item["role"] for item in god_initial["players"]]
            assert identifiers["god_view_access_token"] not in json.dumps(god_initial)

            god_socket.send_json(_ready_message("god_view.ready"))
            god_started = god_socket.receive_json()
            assert god_started["type"] == "god_view.live_snapshot"
            assert god_started["live_state"] == "ready"
            public_socket.send_json(_ready_message("client.ready"))
            public_started = public_socket.receive_json()
            assert public_started["type"] == "live.snapshot"
            assert public_started["live_state"] in {
                "ready",
                "generating",
                "broadcasting",
            }
            model_client.release.set()

            public_result = _receive_realtime_action(public_socket)
            god_result = _receive_realtime_action(god_socket)

    expected_texts = [
        "欢迎来到经典 8 人。本局共2名玩家，对局现在开始。",
        "首夜开始，请所有玩家闭眼。",
    ]
    assert god_result == {
        "committed_texts": expected_texts,
        "presentation_seqs": [1, 2],
        "phase_changes": ["first_night"],
        "audio_chunks": 4,
        "awaiting_observation": True,
    }
    assert public_result["committed_texts"][-1] == expected_texts[-1]
    assert public_result["presentation_seqs"][-1] == 2
    assert public_result["phase_changes"] == ["first_night"]
    assert public_result["awaiting_observation"] is True
    assert model_client.call_count == 0
    assert tts_client.call_count == 2
    assert tts_client.speakers == [
        "zh_female_vv_uranus_bigtts",
        "zh_female_vv_uranus_bigtts",
    ]
    assert model_client.contexts == []
    with session_factory() as db:
        run = db.get(V2GameRun, identifiers["run_id"])
        assert run is not None and run.started_at is not None
        started_event = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == identifiers["game_id"],
                V2GameRecordEvent.event_type == "game_started",
            )
        )
        assert started_event is not None
        assert started_event.payload["trigger_audience"] == "spectator_god_view"
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "game_started",
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "action_opened",
                )
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "judge_speech_rendered",
                )
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2VoiceAsset)
                .where(V2VoiceAsset.game_id == identifiers["game_id"])
            )
            == 2
        )

    with client.websocket_connect(
        identifiers["god_view_websocket_url"],
        subprotocols=god_protocols,
    ) as reconnect:
        snapshot = reconnect.receive_json()
        assert snapshot["type"] == "god_view.live_snapshot"
        assert snapshot["live_state"] == "awaiting_observation"
        assert snapshot["game_phase"] == {
            "phase_seq": 2,
            "phase_id": "first_night",
            "phase_state": "nightfall_announced",
        }
        assert snapshot["current_presentation"] is None
        assert [item["role"] for item in snapshot["players"]]


def _add_library_profiles(session_factory: sessionmaker[Session]) -> None:
    rule_config_payload = {
        "name": "权威双人测试规则",
        "description": "验证 V2 profile library 创建时冻结服务端发布规则。",
        "complexity": "测试",
        "estimated_duration": "短",
        "rule_tags": ["测试"],
        "role_counts": {
            "werewolf": 2,
            "villager": 4,
            "seer": 0,
            "guard": 0,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": True,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
        "werewolf_attack_policy": {
            "resolution": "unanimous_no_attack",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        },
    }
    rule_config = normalize_rule_set_config(rule_config_payload)
    compiled = compile_rule_set_config(
        "classic_8",
        rule_config,
        revision_id="rule_rev_123",
        revision_no=1,
    )
    published_at = datetime.now(UTC)
    with session_factory.begin() as db:
        db.add(
            RuleSetRecord(
                id="classic_8",
                status="published",
                current_published_revision_id="rule_rev_123",
                draft_revision_id=None,
                is_default=True,
                display_order=1,
                lock_version=1,
                created_at=published_at,
                updated_at=published_at,
            )
        )
        db.add(
            RuleSetRevisionRecord(
                id="rule_rev_123",
                rule_set_id="classic_8",
                revision_no=1,
                state="published",
                schema_version=1,
                content_hash=compiled.content_hash,
                lock_version=1,
                name=rule_config.name,
                description=rule_config.description,
                player_count=rule_config.player_count,
                role_summary="2 狼人 / 4 村民",
                complexity=rule_config.complexity,
                estimated_duration=rule_config.estimated_duration,
                config=rule_config_payload,
                published_at=published_at,
                created_at=published_at,
                updated_at=published_at,
            )
        )
        db.add_all(
            [
                VirtualPlayerProfile(
                    id="profile-1",
                    display_name="库内阿青",
                    model_provider="agent_plan",
                    model="private-model-id",
                    personality_id="balanced",
                    personality_text="库内人格一",
                    appearance_id="default",
                    strategy_profile="balanced",
                    display_order=1,
                    status="published",
                    published_at=datetime.now(UTC),
                ),
                VirtualPlayerProfile(
                    id="profile-2",
                    display_name="库内白石",
                    model_provider="agent_plan",
                    model="test-model",
                    personality_id="balanced",
                    personality_text="库内人格二",
                    appearance_id="default",
                    strategy_profile="balanced",
                    display_order=2,
                    status="published",
                    published_at=datetime.now(UTC),
                ),
                *[
                    VirtualPlayerProfile(
                        id=f"profile-{seat}",
                        display_name=f"库内玩家{seat}",
                        model_provider="agent_plan",
                        model="test-model",
                        personality_id="balanced",
                        personality_text=f"库内人格{seat}",
                        appearance_id="default",
                        strategy_profile="balanced",
                        display_order=seat,
                        status="published",
                        published_at=datetime.now(UTC),
                    )
                    for seat in range(3, 7)
                ],
            ]
        )


def _profile_library_create_request() -> dict[str, Any]:
    request = _six_player_create_request()
    lobby = request["lobby_snapshot"]
    lobby["model_binding_mode"] = "profile_library"
    lobby["rule_set"]["id"] = "classic_8"
    lobby["rule_set"]["revision_id"] = "rule_rev_123"
    lobby["rule_set_revision_id"] = "rule_rev_123"
    for seat, player in enumerate(lobby["player_configs"], start=1):
        player["profile_id"] = f"profile-{seat}"
        player.pop("model_provider")
        player.pop("model")
    return request


def test_profile_library_mode_freezes_authoritative_player_models(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    _add_library_profiles(session_factory)
    request = _profile_library_create_request()
    request["lobby_snapshot"]["rule_set"]["werewolf_attack_policy"] = {
        "resolution": "plurality_seeded_random",
        "allow_no_attack": True,
        "allow_wolf_target": True,
    }

    response = client.post("/api/v2/games", json=request)

    assert response.status_code == 201, response.text
    with session_factory() as db:
        game = db.get(V2GameRecord, response.json()["game_id"])
        assert game is not None
        assert game.rule_snapshot["model_binding_mode"] == "profile_library"
        assert game.rule_snapshot["rule_set_revision_id"] == "rule_rev_123"
        assert game.rule_snapshot["rule_set"]["werewolf_attack_policy"] == {
            "resolution": "unanimous_no_attack",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        }
        assert game.rule_snapshot["rule_set"]["name"] == "权威双人测试规则"
        assert [
            (item["profile_id"], item["model_provider"], item["model"])
            for item in game.players_snapshot
        ] == [
            ("profile-1", "agent_plan", "private-model-id"),
            ("profile-2", "agent_plan", "test-model"),
            ("profile-3", "agent_plan", "test-model"),
            ("profile-4", "agent_plan", "test-model"),
            ("profile-5", "agent_plan", "test-model"),
            ("profile-6", "agent_plan", "test-model"),
        ]
        assert [item["name"] for item in game.players_snapshot] == [
            "库内阿青",
            "库内白石",
            "库内玩家3",
            "库内玩家4",
            "库内玩家5",
            "库内玩家6",
        ]
        assert [item["personality"] for item in game.players_snapshot] == [
            "库内人格一",
            "库内人格二",
            "库内人格3",
            "库内人格4",
            "库内人格5",
            "库内人格6",
        ]


def test_profile_library_mode_rejects_submitted_model_override(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    _add_library_profiles(session_factory)
    request = _profile_library_create_request()
    request["lobby_snapshot"]["player_configs"][0]["model"] = "test-model"

    response = client.post("/api/v2/games", json=request)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "v2_player_model_binding_mismatch"
    assert response.json()["detail"]["profile_id"] == "profile-1"


def test_profile_library_mode_rejects_stale_rule_revision(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    _add_library_profiles(session_factory)
    request = _profile_library_create_request()
    request["lobby_snapshot"]["rule_set_revision_id"] = "stale_rule_revision"
    request["lobby_snapshot"]["rule_set"]["revision_id"] = "stale_rule_revision"

    response = client.post("/api/v2/games", json=request)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "rule_revision_changed",
        "rule_set_id": "classic_8",
        "expected_revision_id": "stale_rule_revision",
        "current_revision_id": "rule_rev_123",
    }
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(V2GameRecord)) == 0


def test_profile_library_mode_requires_inner_rule_revision(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    request = _lobby_create_request()
    request["lobby_snapshot"]["model_binding_mode"] = "profile_library"

    response = client.post("/api/v2/games", json=request)

    assert response.status_code == 422


def test_new_game_freezes_v9_prompt_v2_model_context_contract(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json={"title": "V9 契约冻结"})
    assert created.status_code == 201, created.text

    expected = {
        "model_context_schema_version": 9,
        "prompt_template_version": 2,
        "known_events_schema_version": 3,
        "ledger_schema_version": 3,
        "model_view_schema_version": 3,
        "model_view_selector_version": 1,
    }
    with session_factory() as db:
        game = db.get(V2GameRecord, created.json()["game_id"])
        assert game is not None
        assert game.rule_snapshot["model_context_contract"] == expected
        created_event = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == game.game_id,
                V2GameRecordEvent.event_type == "game_created",
            )
        )
        assert created_event is not None
    assert created_event.payload["model_context_contract"] == expected


def test_explicit_tts_request_is_rejected_before_game_creation_when_unavailable(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    original_runtime = client.app.state.v2_live_runtime
    with session_factory() as db:
        before_count = db.scalar(select(func.count()).select_from(V2GameRecord))
    client.app.state.v2_live_runtime = V2LiveRuntime(
        session_factory=session_factory,
        model_client=client.app.state.v2_test_model_client,
        tts_client=None,
        tts_client_factory=None,
        tts_capability_enabled=False,
        voice_root=voice_root,
        sample_rate=24000,
        judge_configuration_provider=(
            original_runtime._action_engine._judge_configuration_provider
        ),
    )
    try:
        request = _six_player_create_request()
        request["audio_mode"] = "tts"
        response = client.post("/api/v2/games", json=request)
    finally:
        client.app.state.v2_live_runtime = original_runtime

    assert response.status_code == 409
    assert response.json() == {
        "code": "v2_audio_mode_unavailable",
        "requested_audio_mode": "tts",
    }
    with session_factory() as db:
        after_count = db.scalar(select(func.count()).select_from(V2GameRecord))
    assert after_count == before_count


def test_audio_mode_is_frozen_when_runtime_default_changes(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    runtime = client.app.state.v2_live_runtime
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    assert created["audio_mode"] == "tts"
    original_capability = runtime._tts_capability_enabled
    runtime._tts_capability_enabled = False
    try:
        snapshot = client.get(created["snapshot_url"])
    finally:
        runtime._tts_capability_enabled = original_capability

    assert snapshot.status_code == 200
    assert snapshot.json()["audio_mode"] == "tts"
    with session_factory() as db:
        game = db.get(V2GameRecord, created["game_id"])
        assert game is not None
        assert game.delivery_snapshot == {
            "schema_version": 1,
            "mode": "tts",
            "source": "legacy_runtime_default",
        }


def test_runtime_execution_projection_uses_the_database_clock(
    v2_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory, _voice_root = v2_context
    request = _six_player_create_request()
    request["audio_mode"] = "text_only"
    created = client.post("/api/v2/games", json=request).json()
    database_now = datetime(2020, 1, 1, tzinfo=UTC)
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        assert game is not None and run is not None
        game.status = "ready"
        run.status = "ready"
        run.worker_id = "v2_worker_database_clock"
        run.worker_heartbeat_at = database_now
        run.lease_expires_at = database_now + timedelta(seconds=5)
        run.fence_token = 1

    monkeypatch.setattr("app.v2.router.database_utc_now", lambda _db: database_now)
    monkeypatch.setattr(
        "app.v2.live_runtime.database_utc_now",
        lambda _db: database_now,
    )

    response = client.get(created["snapshot_url"])
    assert response.status_code == 200
    assert response.json()["execution_state"] == "owned"
    runtime_snapshot = client.app.state.v2_live_runtime.snapshot(game_id=created["game_id"])
    assert runtime_snapshot["execution_state"] == "owned"


def test_live_snapshot_requires_complete_durable_terminal_evidence(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    completed_at = datetime.now(tz=UTC)
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        match = db.get(V2MatchState, created["game_id"])
        assert game is not None and run is not None and match is not None
        game.status = "awaiting_observation"
        game.phase_state = "game_completed"
        run.status = "awaiting_observation"
        run.completed_at = completed_at
        match.winner = "villagers"
        match.completion_reason = "deterministic_win_condition"

    incomplete = client.get(created["snapshot_url"])
    assert incomplete.status_code == 200
    assert incomplete.json()["match_status"] == "running"
    assert incomplete.json()["winner"] == "villagers"
    assert incomplete.json()["execution_state"] == "stopped"

    with session_factory.begin() as db:
        game = db.get(V2GameRecord, created["game_id"])
        assert game is not None
        next_seq = game.last_record_seq + 1
        db.add(
            V2GameRecordEvent(
                game_id=game.game_id,
                event_id=next_seq,
                record_seq=next_seq,
                run_id=created["run_id"],
                event_type="game_completed",
                payload_schema_version=1,
                payload={
                    "winner": "villagers",
                    "completion_reason": "deterministic_win_condition",
                    "audience": "all",
                    "audience_contract_version": 1,
                },
            )
        )
        game.last_record_seq = next_seq

    complete = client.get(created["snapshot_url"])
    assert complete.status_code == 200
    assert complete.json()["match_status"] == "completed"
    assert complete.json()["winner"] == "villagers"
    assert complete.json()["completion_reason"] == "deterministic_win_condition"
    assert complete.json()["completed_at"] is not None


def test_legacy_model_context_contracts_can_resume_but_unknown_contract_cannot(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json={"title": "旧契约只读"}).json()
    game_id = created["game_id"]
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, game_id)
        assert game is not None
        game.rule_snapshot = {
            "model_context_contract": {
                "prompt_schema_version": 7,
                "public_timeline_schema_version": 1,
                "ledger_schema_version": 2,
                "model_view_schema_version": 2,
            }
        }

    snapshot = client.get(created["snapshot_url"])
    assert snapshot.status_code == 200
    assert snapshot.json()["game_id"] == game_id

    runtime = client.app.state.v2_live_runtime
    channel = asyncio.run(runtime._channel(game_id))
    assert channel.game_id == game_id

    v8_created = client.post("/api/v2/games", json={"title": "V8 旧模板可续跑"}).json()
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, v8_created["game_id"])
        assert game is not None
        game.rule_snapshot = {
            "model_context_contract": {
                "model_context_schema_version": 8,
                "prompt_template_version": 1,
                "known_events_schema_version": 1,
                "ledger_schema_version": 2,
                "model_view_schema_version": 3,
                "model_view_selector_version": 1,
            }
        }

    v8_snapshot = client.get(v8_created["snapshot_url"])
    assert v8_snapshot.status_code == 200
    assert v8_snapshot.json()["game_id"] == v8_created["game_id"]
    v8_channel = asyncio.run(runtime._channel(v8_created["game_id"]))
    assert v8_channel.game_id == v8_created["game_id"]

    unsupported = client.post("/api/v2/games", json={"title": "未知契约"}).json()
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, unsupported["game_id"])
        assert game is not None
        game.rule_snapshot = {}

    with pytest.raises(
        V2ClientProtocolError,
        match="unsupported_model_context_contract",
    ):
        asyncio.run(runtime._channel(unsupported["game_id"]))

    repository = V2ActionRepository(session_factory)
    with pytest.raises(
        V2RepositoryError,
        match="unsupported_model_context_contract",
    ):
        repository.start_game(game_id=unsupported["game_id"], audience="player_public")


def test_join_sample_cursor_is_atomic_with_audio_broadcast() -> None:
    async def scenario() -> None:
        channel = _GameChannel(
            game_id="v2_game_0123456789abcdef",
            snapshot_factory=lambda **values: {
                "live_state": "failed",
                "current_presentation": {
                    "join_sample_cursor": values["sample_cursor"],
                },
            },
            game_starter=lambda **_values: False,
            engine=object(),  # type: ignore[arg-type]
        )
        first = _BlockingWebSocket(block_audio=True)
        first_id = await channel.connect(  # type: ignore[arg-type]
            first,
            audience="player_public",
        )
        await channel.ready(first_id, _ready_message("client.ready"))
        audio_task = asyncio.create_task(
            channel.broadcast_audio(
                b"first-frame",
                identity=object(),  # type: ignore[arg-type]
                next_sample_cursor=240,
            )
        )
        await first.audio_started.wait()

        second = _BlockingWebSocket()
        join_task = asyncio.create_task(
            channel.connect(second, audience="player_public")  # type: ignore[arg-type]
        )
        await asyncio.sleep(0)
        assert not join_task.done()
        first.release_audio.set()
        await audio_task
        second_id = await join_task

        assert second.json_messages[0]["current_presentation"]["join_sample_cursor"] == 240
        assert second.binary_messages == []
        await channel.ready(second_id, _ready_message("client.ready"))
        await channel.broadcast_audio(
            b"second-frame",
            identity=object(),  # type: ignore[arg-type]
            next_sample_cursor=480,
        )
        assert second.binary_messages == [b"second-frame"]

    asyncio.run(scenario())


def test_director_channel_receives_public_and_private_stage_events() -> None:
    async def scenario() -> None:
        channel = _GameChannel(
            game_id="v2_game_0123456789abcdef",
            snapshot_factory=lambda **values: {
                "live_state": "failed",
                "audience": values["audience"],
            },
            game_starter=lambda **_values: False,
            engine=object(),  # type: ignore[arg-type]
        )
        public = _BlockingWebSocket()
        director = _BlockingWebSocket()
        god = _BlockingWebSocket()
        public_id = await channel.connect(public, audience="player_public")  # type: ignore[arg-type]
        director_id = await channel.connect(  # type: ignore[arg-type]
            director,
            audience="spectator_directed",
        )
        god_id = await channel.connect(god, audience="spectator_god_view")  # type: ignore[arg-type]
        await channel.ready(public_id, _ready_message("client.ready"))
        await channel.ready(director_id, _ready_message("director.ready"))
        await channel.ready(god_id, _ready_message("god_view.ready"))
        public.json_messages.clear()
        director.json_messages.clear()
        god.json_messages.clear()

        public_event = {"type": "public"}
        private_event = {"type": "private"}
        director_event = {"type": "director"}
        await channel.broadcast_json(public_event, audience="public")
        await channel.broadcast_json(private_event, audience="god_view")
        await channel.broadcast_json(director_event, audience="director")

        assert public.json_messages == [public_event]
        assert director.json_messages == [
            public_event,
            private_event,
            director_event,
        ]
        assert god.json_messages == [private_event]

    asyncio.run(scenario())


def test_frozen_tts_game_is_rejected_before_execution_claim_when_runtime_has_no_tts(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    runtime = client.app.state.v2_live_runtime
    original_capability = runtime._tts_capability_enabled
    runtime._tts_capability_enabled = False

    async def scenario() -> None:
        channel = await runtime._channel(created["game_id"])
        assert channel._tts_capability_enabled is False
        socket = _BlockingWebSocket()
        subscriber_id = await channel.connect(  # type: ignore[arg-type]
            socket,
            audience="player_public",
        )

        with pytest.raises(V2ClientProtocolError, match="v2_audio_mode_unavailable"):
            await channel.ready(subscriber_id, _ready_message("client.ready"))

        assert channel._task is None
        assert channel._subscribers[subscriber_id].ready is False

    try:
        asyncio.run(scenario())
    finally:
        runtime._tts_capability_enabled = original_capability
    with session_factory() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        assert game is not None and run is not None
        assert game.status == "waiting_to_start"
        assert run.status == "waiting_to_start"
        assert run.worker_id is None
        event_types = list(
            db.scalars(
                select(V2GameRecordEvent.event_type).where(
                    V2GameRecordEvent.game_id == created["game_id"]
                )
            )
        )
    assert "v2_run_execution_claimed" not in event_types
    assert "game_started" not in event_types


def test_execution_task_is_registered_before_post_claim_snapshot_send(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    request = _six_player_create_request()
    request["audio_mode"] = "text_only"
    created = client.post("/api/v2/games", json=request).json()
    repository = V2ActionRepository(session_factory, enforce_execution_fence=True)

    async def scenario() -> None:
        class BlockingEngine:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def run(self, **_kwargs: Any) -> None:
                self.started.set()
                await self.release.wait()

        class FailingReadyWebSocket(_BlockingWebSocket):
            async def send_json(self, value: dict[str, Any]) -> None:
                if self.json_messages:
                    raise RuntimeError("post-claim snapshot send failed")
                await super().send_json(value)

        def snapshot(**_kwargs: Any) -> dict[str, Any]:
            with session_factory() as db:
                game = db.get(V2GameRecord, created["game_id"])
                assert game is not None
                return {"live_state": game.status, "audio_mode": "text_only"}

        engine = BlockingEngine()
        channel = _GameChannel(
            game_id=created["game_id"],
            snapshot_factory=snapshot,
            repository=repository,
            engine=engine,  # type: ignore[arg-type]
            worker_id="v2_worker_send_failure",
            lease_seconds=30,
            heartbeat_seconds=10,
        )
        socket = FailingReadyWebSocket()
        subscriber_id = await channel.connect(  # type: ignore[arg-type]
            socket,
            audience="player_public",
        )

        with pytest.raises(RuntimeError, match="post-claim snapshot send failed"):
            await channel.ready(subscriber_id, _ready_message("client.ready"))

        task = channel._task
        assert task is not None
        await asyncio.wait_for(engine.started.wait(), timeout=1)
        engine.release.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
    with session_factory() as db:
        run = db.get(V2GameRun, created["run_id"])
        assert run is not None and run.worker_id is None
        released = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "v2_run_execution_released",
            )
        )
        assert released is not None


def test_owned_engine_durable_failure_releases_with_failed_reason(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    request = _six_player_create_request()
    request["audio_mode"] = "text_only"
    created = client.post("/api/v2/games", json=request).json()
    repository = V2ActionRepository(session_factory, enforce_execution_fence=True)

    async def scenario() -> None:
        class DurableFailureEngine:
            async def run(self, **_kwargs: Any) -> None:
                with session_factory.begin() as db:
                    game = db.get(V2GameRecord, created["game_id"])
                    run = db.get(V2GameRun, created["run_id"])
                    assert game is not None and run is not None
                    game.status = "failed"
                    game.phase_state = "failed"
                    run.status = "failed"

        def snapshot(**_kwargs: Any) -> dict[str, Any]:
            with session_factory() as db:
                game = db.get(V2GameRecord, created["game_id"])
                assert game is not None
                return {"live_state": game.status, "audio_mode": "text_only"}

        channel = _GameChannel(
            game_id=created["game_id"],
            snapshot_factory=snapshot,
            repository=repository,
            engine=DurableFailureEngine(),  # type: ignore[arg-type]
            worker_id="v2_worker_durable_failure",
            lease_seconds=30,
            heartbeat_seconds=10,
        )
        socket = _BlockingWebSocket()
        subscriber_id = await channel.connect(  # type: ignore[arg-type]
            socket,
            audience="player_public",
        )
        await channel.ready(subscriber_id, _ready_message("client.ready"))
        task = channel._task
        assert task is not None
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
    with session_factory() as db:
        released = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "v2_run_execution_released",
            )
        )
        assert released is not None
        assert released.payload["reason"] == "failed"


def test_owned_channel_pushes_stopped_snapshot_after_awaiting_release(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    request = _six_player_create_request()
    request["audio_mode"] = "text_only"
    created = client.post("/api/v2/games", json=request).json()
    runtime = client.app.state.v2_live_runtime
    repository = V2ActionRepository(session_factory, enforce_execution_fence=True)

    async def scenario() -> list[dict[str, Any]]:
        class AwaitingEngine:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def run(self, **_kwargs: Any) -> None:
                self.started.set()
                await self.release.wait()
                with session_factory.begin() as db:
                    game = db.get(V2GameRecord, created["game_id"])
                    run = db.get(V2GameRun, created["run_id"])
                    assert game is not None and run is not None
                    game.status = "awaiting_observation"
                    run.status = "awaiting_observation"

        engine = AwaitingEngine()
        channel = _GameChannel(
            game_id=created["game_id"],
            snapshot_factory=runtime.snapshot,
            repository=repository,
            engine=engine,  # type: ignore[arg-type]
            worker_id="v2_worker_awaiting_release",
            lease_seconds=30,
            heartbeat_seconds=10,
        )
        socket = _BlockingWebSocket()
        subscriber_id = await channel.connect(  # type: ignore[arg-type]
            socket,
            audience="player_public",
        )
        await channel.ready(subscriber_id, _ready_message("client.ready"))
        task = channel._task
        assert task is not None
        await asyncio.wait_for(engine.started.wait(), timeout=1)
        assert socket.json_messages[-1]["live_state"] == "ready"
        assert socket.json_messages[-1]["execution_state"] == "owned"

        engine.release.set()
        await asyncio.wait_for(task, timeout=1)
        return socket.json_messages

    messages = asyncio.run(scenario())
    assert len(messages) == 3
    assert messages[-1]["type"] == "live.snapshot"
    assert messages[-1]["live_state"] == "awaiting_observation"
    assert messages[-1]["execution_state"] == "stopped"
    assert messages[-1]["winner"] is None
    with session_factory() as db:
        run = db.get(V2GameRun, created["run_id"])
        assert run is not None
        assert run.worker_id is None


def test_two_channels_compete_for_one_execution_owner_and_only_winner_runs(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    request = _six_player_create_request()
    request["audio_mode"] = "text_only"
    created = client.post("/api/v2/games", json=request).json()
    repository = V2ActionRepository(session_factory, enforce_execution_fence=True)

    async def scenario() -> tuple[int, int]:
        class BlockingEngine:
            def __init__(self) -> None:
                self.run_count = 0
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def run(self, **_kwargs: Any) -> None:
                self.run_count += 1
                self.started.set()
                await self.release.wait()

        def snapshot_factory() -> Any:
            calls = 0

            def snapshot(**_kwargs: Any) -> dict[str, Any]:
                nonlocal calls
                calls += 1
                if calls <= 2:
                    return {
                        "live_state": "waiting_to_start",
                        "audio_mode": "text_only",
                    }
                with session_factory() as db:
                    game = db.get(V2GameRecord, created["game_id"])
                    assert game is not None
                    return {
                        "live_state": game.status,
                        "audio_mode": "text_only",
                    }

            return snapshot

        first_engine = BlockingEngine()
        second_engine = BlockingEngine()
        first = _GameChannel(
            game_id=created["game_id"],
            snapshot_factory=snapshot_factory(),
            repository=repository,
            engine=first_engine,  # type: ignore[arg-type]
            worker_id="v2_worker_first",
            lease_seconds=30,
            heartbeat_seconds=10,
        )
        second = _GameChannel(
            game_id=created["game_id"],
            snapshot_factory=snapshot_factory(),
            repository=repository,
            engine=second_engine,  # type: ignore[arg-type]
            worker_id="v2_worker_second",
            lease_seconds=30,
            heartbeat_seconds=10,
        )
        first_socket = _BlockingWebSocket()
        second_socket = _BlockingWebSocket()
        first_id = await first.connect(  # type: ignore[arg-type]
            first_socket,
            audience="player_public",
        )
        second_id = await second.connect(  # type: ignore[arg-type]
            second_socket,
            audience="player_public",
        )

        await asyncio.gather(
            first.ready(first_id, _ready_message("client.ready")),
            second.ready(second_id, _ready_message("client.ready")),
        )
        active = [channel for channel in (first, second) if channel._task is not None]
        assert len(active) == 1
        winner = first_engine if first._task is not None else second_engine
        loser = second_engine if winner is first_engine else first_engine
        await asyncio.wait_for(winner.started.wait(), timeout=1)
        assert winner.run_count == 1
        assert loser.run_count == 0

        task = active[0]._task
        assert task is not None
        winner.release.set()
        await asyncio.wait_for(task, timeout=1)
        return first_engine.run_count, second_engine.run_count

    assert sum(asyncio.run(scenario())) == 1
    with session_factory() as db:
        run = db.get(V2GameRun, created["run_id"])
        assert run is not None
        assert run.worker_id is None
        events = list(
            db.scalars(
                select(V2GameRecordEvent).where(V2GameRecordEvent.game_id == created["game_id"])
            )
        )
    assert sum(event.event_type == "v2_run_execution_claimed" for event in events) == 1
    assert sum(event.event_type == "game_started" for event in events) == 1
    assert sum(event.event_type == "v2_run_execution_released" for event in events) == 1


def test_heartbeat_loss_is_durable_stale_and_does_not_release_owner(
    v2_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory, _voice_root = v2_context
    request = _six_player_create_request()
    request["audio_mode"] = "text_only"
    created = client.post("/api/v2/games", json=request).json()
    repository = V2ActionRepository(session_factory, enforce_execution_fence=True)

    def fail_heartbeat(**_kwargs: Any) -> bool:
        raise RuntimeError("transient heartbeat storage failure")

    monkeypatch.setattr(repository, "heartbeat_execution", fail_heartbeat)

    async def scenario() -> None:
        class BlockingEngine:
            def __init__(self) -> None:
                self.started = asyncio.Event()

            async def run(self, **_kwargs: Any) -> None:
                self.started.set()
                await asyncio.Event().wait()

        def snapshot(**_kwargs: Any) -> dict[str, Any]:
            with session_factory() as db:
                game = db.get(V2GameRecord, created["game_id"])
                assert game is not None
                return {"live_state": game.status, "audio_mode": "text_only"}

        engine = BlockingEngine()
        channel = _GameChannel(
            game_id=created["game_id"],
            snapshot_factory=snapshot,
            repository=repository,
            engine=engine,  # type: ignore[arg-type]
            worker_id="v2_worker_heartbeat",
            lease_seconds=30,
            heartbeat_seconds=0.01,
        )
        socket = _BlockingWebSocket()
        subscriber_id = await channel.connect(  # type: ignore[arg-type]
            socket,
            audience="player_public",
        )
        await channel.ready(subscriber_id, _ready_message("client.ready"))
        task = channel._task
        assert task is not None
        await asyncio.wait_for(engine.started.wait(), timeout=1)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=1)

    asyncio.run(scenario())
    with session_factory() as db:
        run = db.get(V2GameRun, created["run_id"])
        assert run is not None
        assert run.worker_id == "v2_worker_heartbeat"
        assert run.worker_heartbeat_at is not None
        assert run.lease_expires_at is not None
        assert run.lease_expires_at <= datetime.now(tz=UTC).replace(tzinfo=None)
        event_types = list(
            db.scalars(
                select(V2GameRecordEvent.event_type).where(
                    V2GameRecordEvent.game_id == created["game_id"]
                )
            )
        )
    assert "v2_run_execution_heartbeat_lost" in event_types
    assert "v2_run_execution_released" not in event_types
    snapshot = client.get(created["snapshot_url"])
    assert snapshot.status_code == 200
    assert snapshot.json()["execution_state"] == "stale"


def test_stale_fence_is_rejected_by_every_runtime_repository(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    action_repository = V2ActionRepository(
        session_factory,
        enforce_execution_fence=True,
    )
    claim = action_repository.start_and_claim_execution(
        game_id=created["game_id"],
        audience="player_public",
        worker_id="v2_worker_original",
        lease_seconds=30,
    )
    assert claim.fence is not None
    with bind_v2_run_fence(claim.fence):
        action_repository.append_event(
            game_id=created["game_id"],
            event_type="fence_probe_before_rotation",
            audience="god_view",
            payload={},
        )

    with session_factory.begin() as db:
        run = db.get(V2GameRun, created["run_id"])
        assert run is not None
        run.worker_id = "v2_worker_replacement"
        run.worker_heartbeat_at = datetime.now(tz=UTC)
        run.lease_expires_at = datetime.now(tz=UTC) + timedelta(seconds=30)
        run.fence_token += 1

    with pytest.raises(V2ExecutionOwnershipLost, match="v2_run_execution_lease_lost"):
        action_repository.append_event(
            game_id=created["game_id"],
            event_type="stale_fence_write_rejected",
            audience="god_view",
            payload={},
            fence=claim.fence,
        )
    with bind_v2_run_fence(claim.fence):
        with pytest.raises(
            V2ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            action_repository.check_cancellation(created["game_id"])

    repositories = (
        V2NightRepository(session_factory, enforce_execution_fence=True),
        V2MatchRepository(session_factory, enforce_execution_fence=True),
    )
    with bind_v2_run_fence(claim.fence):
        for repository_with_fence in repositories:
            with pytest.raises(
                V2ExecutionOwnershipLost,
                match="v2_run_execution_lease_lost",
            ):
                repository_with_fence.append_event(
                    game_id=created["game_id"],
                    event_type="stale_fence_write_rejected",
                    audience="god_view",
                    payload={},
                )

    with session_factory() as db:
        rejected = db.scalar(
            select(func.count())
            .select_from(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "stale_fence_write_rejected",
            )
        )
    assert rejected == 0


def test_execution_ownership_loss_does_not_fail_or_broadcast_failed_action(
    v2_context,
) -> None:
    client, _session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json={"title": "过期 owner 行为"}).json()
    runtime = client.app.state.v2_live_runtime

    class OwnershipLostRepository:
        def __init__(self) -> None:
            self.fail_action_called = False

        def claim_action(self, **values: Any) -> V2ActionClaim:
            return V2ActionClaim(
                game_id=values["game_id"],
                run_id=created["run_id"],
                action_id=values["action_id"],
                phase_id=values["expected_phase_id"],
                audience=values["audience"],
                audio_mode="text_only",
            )

        def check_cancellation(self, _game_id: str) -> None:
            return

        def append_event(self, **_values: Any) -> None:
            raise V2ExecutionOwnershipLost("v2_run_execution_lease_lost")

        def fail_action(self, **_values: Any) -> None:
            self.fail_action_called = True

    repository = OwnershipLostRepository()
    broadcaster = _CollectingBroadcaster()
    action_engine = runtime._action_engine
    original_repository = action_engine._repository
    action_engine._repository = repository  # type: ignore[assignment]
    try:
        with pytest.raises(V2ExecutionOwnershipLost, match="v2_run_execution_lease_lost"):
            asyncio.run(
                action_engine.run_judge_speech(
                    game_id=created["game_id"],
                    broadcaster=broadcaster,  # type: ignore[arg-type]
                    spec=V2SpeechSpec(
                        action_type="judge_opening_speech",
                        phase_id="opening",
                        required_phase_state="opening_ready",
                        objective="验证过期 owner 不得失败当前动作",
                        success_live_state="ready",
                        success_phase_state="opening_speech_closed",
                    ),
                )
            )
    finally:
        action_engine._repository = original_repository

    assert repository.fail_action_called is False
    assert not any(
        value.get("live_state") == "failed" or value.get("type") == "speech.presentation_failed"
        for _audience, value in broadcaster.messages
    )


def test_voice_file_is_discarded_when_ownership_is_lost_after_finalize(
    v2_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory, voice_root = v2_context
    created = client.post("/api/v2/games", json={"title": "语音落盘后丢失 owner"}).json()
    action_engine = client.app.state.v2_live_runtime._action_engine
    repository = action_engine._repository
    execution = repository.start_and_claim_execution(
        game_id=created["game_id"],
        audience="player_public",
        worker_id="v2_worker_voice_finalize_loss",
        lease_seconds=30,
    )
    assert execution.fence is not None
    observed_final_path: Path | None = None

    def lose_ownership_after_finalize(**values: Any) -> None:
        nonlocal observed_final_path
        identity = values["identity"]
        observed_final_path = voice_root / identity.storage_key
        assert observed_final_path.is_file()
        assert not observed_final_path.with_suffix(f"{observed_final_path.suffix}.writing").exists()
        raise V2ExecutionOwnershipLost("v2_run_execution_lease_lost")

    monkeypatch.setattr(repository, "mark_voice_ready", lose_ownership_after_finalize)
    with bind_v2_run_fence(execution.fence):
        with pytest.raises(
            V2ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            asyncio.run(
                action_engine.run_judge_speech(
                    game_id=created["game_id"],
                    broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
                    spec=V2SpeechSpec(
                        action_type="judge_opening_speech",
                        phase_id="opening",
                        required_phase_state="opening_ready",
                        objective="验证落盘后的未提交语音会被清理",
                        success_live_state="ready",
                        success_phase_state="opening_speech_closed",
                    ),
                )
            )

    assert observed_final_path is not None
    assert not observed_final_path.exists()
    assert not observed_final_path.with_suffix(f"{observed_final_path.suffix}.writing").exists()
    with session_factory() as db:
        voice = db.scalar(select(V2VoiceAsset).where(V2VoiceAsset.game_id == created["game_id"]))
        assert voice is not None
        assert voice.state == "writing"
        assert voice.completed_at is None


def test_voice_file_is_discarded_when_ready_persistence_fails(
    v2_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory, voice_root = v2_context
    created = client.post("/api/v2/games", json={"title": "语音 ready 持久化失败"}).json()
    action_engine = client.app.state.v2_live_runtime._action_engine
    repository = action_engine._repository
    execution = repository.start_and_claim_execution(
        game_id=created["game_id"],
        audience="player_public",
        worker_id="v2_worker_voice_ready_failure",
        lease_seconds=30,
    )
    assert execution.fence is not None
    observed_final_path: Path | None = None

    def fail_ready_persistence(**values: Any) -> None:
        nonlocal observed_final_path
        identity = values["identity"]
        observed_final_path = voice_root / identity.storage_key
        assert observed_final_path.is_file()
        assert not observed_final_path.with_suffix(f"{observed_final_path.suffix}.writing").exists()
        raise V2RepositoryError("voice ready persistence failed")

    monkeypatch.setattr(repository, "mark_voice_ready", fail_ready_persistence)
    with bind_v2_run_fence(execution.fence):
        result = asyncio.run(
            action_engine.run_judge_speech(
                game_id=created["game_id"],
                broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
                spec=V2SpeechSpec(
                    action_type="judge_opening_speech",
                    phase_id="opening",
                    required_phase_state="opening_ready",
                    objective="验证未提交语音在普通持久化失败后会被清理",
                    success_live_state="ready",
                    success_phase_state="opening_speech_closed",
                ),
            )
        )

    assert result is False
    assert observed_final_path is not None
    assert not observed_final_path.exists()
    assert not observed_final_path.with_suffix(f"{observed_final_path.suffix}.writing").exists()
    with session_factory() as db:
        voice = db.scalar(select(V2VoiceAsset).where(V2VoiceAsset.game_id == created["game_id"]))
        assert voice is not None
        assert voice.state == "failed"
        assert voice.completed_at is not None


def test_v2_lobby_create_rejects_incomplete_or_duplicate_lineups(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    incomplete = _lobby_create_request()
    incomplete["lobby_snapshot"]["player_configs"] = [{"seat": 1, "profile_id": "profile-1"}]
    duplicate = _lobby_create_request()
    duplicate["lobby_snapshot"]["player_configs"][1]["profile_id"] = "profile-1"
    invalid_roles = _lobby_create_request()
    invalid_roles["lobby_snapshot"]["rule_set"]["roles"][1]["count"] = 2

    assert client.post("/api/v2/games", json=incomplete).status_code == 422
    assert client.post("/api/v2/games", json=duplicate).status_code == 422
    assert client.post("/api/v2/games", json=invalid_roles).status_code == 422


def test_public_viewer_click_starts_game_then_receives_opening_and_nightfall(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    created = client.post("/api/v2/games", json={"title": "首句实时验收"})
    assert created.status_code == 201, created.text
    identifiers = created.json()
    game_id = identifiers["game_id"]

    snapshot = client.get(identifiers["snapshot_url"])
    assert snapshot.status_code == 200
    assert snapshot.json()["live_state"] == "waiting_to_start"
    assert snapshot.json()["game_phase"]["phase_state"] == "opening_ready"
    assert snapshot.json()["public_rule"] is None
    assert snapshot.json()["public_players"] == []
    assert snapshot.json()["public_role_assignment"] == {
        "state": "unavailable",
        "assigned_count": 0,
    }
    assert snapshot.json()["current_presentation"] is None
    assert (
        client.get(
            identifiers["god_view_snapshot_url"],
            headers={"Authorization": f"Bearer {identifiers['god_view_access_token']}"},
        ).status_code
        == 409
    )

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        assert websocket.receive_json()["live_state"] == "waiting_to_start"
        websocket.send_json(
            {
                "protocol_version": 1,
                "type": "client.ready",
                "audio": {
                    "encoding": "pcm_s16le",
                    "sample_rate": 24000,
                    "channels": 1,
                },
            }
        )
        started_snapshot = websocket.receive_json()
        assert started_snapshot["type"] == "live.snapshot"
        assert started_snapshot["live_state"] == "ready"
        result = _receive_realtime_action(websocket, include_audio_headers=True)
        assert result["committed_texts"] == [
            "欢迎来到本场实时狼人杀对局。对局现在开始。",
            "首夜开始，请所有玩家闭眼。",
        ]
        assert result["presentation_seqs"] == [1, 2]
        assert result["phase_changes"] == ["first_night"]
        assert result["audio_chunks"] == 4
        assert [header["presentation_seq"] for header in result["audio_headers"]] == [
            1,
            1,
            2,
            2,
        ]
        assert [header["chunk_index"] for header in result["audio_headers"]] == [
            0,
            1,
            0,
            1,
        ]
        assert [header["start_sample"] for header in result["audio_headers"]] == [
            0,
            240,
            0,
            240,
        ]

    after = client.get(identifiers["snapshot_url"]).json()
    assert after["live_state"] == "awaiting_observation"
    assert after["game_phase"] == {
        "phase_seq": 2,
        "phase_id": "first_night",
        "phase_state": "nightfall_announced",
    }
    assert after["current_presentation"] is None

    with session_factory() as db:
        game = db.get(V2GameRecord, game_id)
        run = db.get(V2GameRun, identifiers["run_id"])
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        presentations = list(
            db.scalars(
                select(V2LivePresentation)
                .where(V2LivePresentation.game_id == game_id)
                .order_by(V2LivePresentation.presentation_seq)
            )
        )
        voices = list(
            db.scalars(
                select(V2VoiceAsset)
                .where(V2VoiceAsset.game_id == game_id)
                .order_by(V2VoiceAsset.created_at)
            )
        )
        assert game is not None and game.status == "awaiting_observation"
        assert (game.phase_seq, game.phase_id, game.phase_state) == (
            2,
            "first_night",
            "nightfall_announced",
        )
        assert run is not None and run.status == "awaiting_observation"
        assert run.started_at is not None
        assert [item.event_type for item in events] == [
            "game_created",
            "v2_run_execution_claimed",
            "game_started",
            "action_opened",
            "judge_speech_rendered",
            "speech_opened",
            "speech_segment_committed",
            "speech_sealed",
            "tts_stream_started",
            "tts_first_chunk_received",
            "voice_recording_started",
            "audio_broadcast_started",
            "tts_stream_completed",
            "voice_asset_saved",
            "audio_drained",
            "speech_closed",
            "action_succeeded",
            "game_phase_changed",
            "action_opened",
            "judge_speech_rendered",
            "speech_opened",
            "speech_segment_committed",
            "speech_sealed",
            "tts_stream_started",
            "tts_first_chunk_received",
            "voice_recording_started",
            "audio_broadcast_started",
            "tts_stream_completed",
            "voice_asset_saved",
            "audio_drained",
            "speech_closed",
            "action_succeeded",
            "v2_run_execution_released",
        ]
        started_event = next(item for item in events if item.event_type == "game_started")
        assert started_event.payload["trigger_audience"] == "player_public"
        assert [item.phase_id for item in presentations] == ["opening", "first_night"]
        assert all(item.state == "closed" for item in presentations)
        assert len(voices) == 2
        assert all(item.state == "ready" and item.sample_count == 480 for item in voices)
        assert all(item.pcm_sha256 == hashlib.sha256(PCM_CHUNK * 2).hexdigest() for item in voices)
        for voice in voices:
            voice_path = voice_root / voice.storage_key
            assert voice_path.is_file()
            assert voice_path.read_bytes()[:4] == b"RIFF"
        assert not any("werewolf" in item.event_type for item in events)
        assert db.scalar(select(func.count()).select_from(GameSessionRecord)) == 0
        assert db.scalar(select(func.count()).select_from(LiveRunRecord)) == 0

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        reconnect = websocket.receive_json()
        assert reconnect["live_state"] == "awaiting_observation"
        assert reconnect["game_phase"]["phase_state"] == "nightfall_announced"
        assert reconnect["current_presentation"] is None


def test_admin_v2_record_exposes_saved_voice_only_through_authenticated_endpoint(
    v2_context,
) -> None:
    client, _session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json={"title": "Admin V2 语音"}).json()
    _run_opening_to_nightfall(client, identifiers["websocket_url"])

    unauthorized = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert unauthorized.status_code == 401
    session = client.post("/api/v1/admin/dev-login")
    assert session.status_code == 200, session.text

    detail = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert "events" not in body
    assert "model_requests" not in body
    model_requests = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/model-requests"
        "?after_record_seq=0&page_size=500"
    )
    assert model_requests.status_code == 200, model_requests.text
    assert model_requests.json()["items"] == []
    event_page = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/events?after_record_seq=0&page_size=500"
    )
    assert event_page.status_code == 200, event_page.text
    first_event_page = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/events?after_record_seq=0&page_size=1"
    )
    assert first_event_page.status_code == 200, first_event_page.text
    first_event_body = first_event_page.json()
    assert first_event_body["has_more"] is True
    assert first_event_body["next_after_record_seq"] == first_event_body["items"][0]["record_seq"]
    second_event_page = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/events"
        f"?after_record_seq={first_event_body['next_after_record_seq']}&page_size=1"
    )
    assert second_event_page.status_code == 200, second_event_page.text
    assert (
        second_event_page.json()["items"][0]["record_seq"]
        > (first_event_body["next_after_record_seq"])
    )
    template_events = [
        item for item in event_page.json()["items"] if item["event_type"] == "judge_speech_rendered"
    ]
    assert [item["payload"]["template_id"] for item in template_events] == [
        "judge_opening_speech",
        "judge_nightfall_announcement",
    ]
    assert all(
        item["payload"]["tts_speaker"] == "zh_female_vv_uranus_bigtts" for item in template_events
    )
    assert body["judge_voice_snapshot"]["selected_tts_speaker"] == ("zh_female_vv_uranus_bigtts")
    assert len(body["voice_assets"]) == 2
    for voice in body["voice_assets"]:
        assert voice["state"] == "ready"
        assert voice["pcm_sha256"] == hashlib.sha256(PCM_CHUNK * 2).hexdigest()
        assert voice["audio_url"].startswith("/api/v1/admin/v2/games/")
        audio = client.get(voice["audio_url"])
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert audio.content[:4] == b"RIFF"


def test_random_judge_voice_is_frozen_per_game_before_runtime_actions(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    tts_client = client.app.state.v2_test_tts_client
    configured_pool = ["judge-random-a", "judge-random-b"]
    with session_factory.begin() as db:
        db.add(
            JudgeConfigurationRecord(
                id="default",
                voice_mode="random",
                tts_speaker=configured_pool[0],
                random_tts_speakers=configured_pool,
                version=4,
            )
        )

    identifiers = client.post(
        "/api/v2/games",
        json={"title": "每局随机音色冻结"},
    ).json()
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None
        selected = game.judge_voice_snapshot["selected_tts_speaker"]
        assert selected in configured_pool
        assert game.judge_voice_snapshot["voice_mode"] == "random"
        assert game.judge_voice_snapshot["configuration_version"] == 4
        configured = db.get(JudgeConfigurationRecord, "default")
        assert configured is not None
        configured.voice_mode = "fixed"
        configured.tts_speaker = "judge-changed-after-creation"
        configured.random_tts_speakers = []
        configured.version = 5

    _run_opening_to_nightfall(client, identifiers["websocket_url"])

    assert tts_client.speakers == [selected, selected]
    with session_factory() as db:
        rendered = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "judge_speech_rendered",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert len(rendered) == 2
        assert all(item.payload["tts_speaker"] == selected for item in rendered)


def test_admin_v2_record_exposes_complete_private_identity_table(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    identifiers = client.post(
        "/api/v2/games",
        json=_lobby_create_request(),
    ).json()
    session = client.post("/api/v1/admin/dev-login")
    assert session.status_code == 200, session.text

    detail = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")

    assert detail.status_code == 200, detail.text
    identities = detail.json()["player_identities"]
    assert len(identities) == 2
    assert [
        {
            "seat": item["seat"],
            "player_id": item["player_id"],
            "display_name": item["display_name"],
            "alive": item["alive"],
            "death_cause": item["death_cause"],
        }
        for item in identities
    ] == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "alive": True,
            "death_cause": None,
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "白石",
            "alive": True,
            "death_cause": None,
        },
    ]
    assert {item["role"] for item in identities} == {"villager", "werewolf"}
    assert {item["team"] for item in identities} == {"village", "werewolves"}
    serialized = json.dumps(identities)
    assert "private-model-id" not in serialized
    assert "private personality prompt" not in serialized
    assert "private-speaker" not in serialized


def test_admin_operator_can_idempotently_stop_waiting_v2_game_without_private_leak(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    identifiers = client.post(
        "/api/v2/games",
        json=_lobby_create_request(),
    ).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-stop-waiting-1",
    )
    reason = "人工发现异常，立即停止额度消耗"

    stopped = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": reason},
        headers=headers,
    )

    assert stopped.status_code == 202, stopped.text
    assert stopped.json() == {
        "action": "stop",
        "game_id": identifiers["game_id"],
        "run_id": identifiers["run_id"],
        "run_status": "canceled",
        "stop_requested_at": stopped.json()["stop_requested_at"],
        "replayed": False,
    }
    replayed = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": reason},
        headers=headers,
    )
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    assert replayed.json()["run_status"] == "canceled"

    public_snapshot = client.get(identifiers["snapshot_url"]).json()
    assert public_snapshot["live_state"] == "canceled"
    assert public_snapshot["current_presentation"] is None
    assert reason not in json.dumps(public_snapshot, ensure_ascii=False)
    god_snapshot = client.get(
        identifiers["god_view_snapshot_url"],
        headers={"Authorization": f"Bearer {identifiers['god_view_access_token']}"},
    ).json()
    assert god_snapshot["live_state"] == "canceled"
    assert reason not in json.dumps(god_snapshot, ensure_ascii=False)

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        assert game is not None and game.status == "canceled"
        assert run is not None
        assert run.status == "canceled"
        assert run.stop_requested_at is not None
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == game.game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert [item.event_type for item in events][-2:] == [
            "game_stop_requested",
            "game_canceled",
        ]
        assert reason not in json.dumps(
            [item.payload for item in events],
            ensure_ascii=False,
        )
        assert db.scalar(select(func.count()).select_from(V2GameControlRequest)) == 1
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "admin.v2_game.stop",
                AuditEvent.resource_id == game.game_id,
            )
        )
        assert audit is not None
        assert audit.reason == reason


def test_admin_v2_stop_interrupts_active_voice_and_broadcasts_safe_terminal_state(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    identifiers = client.post(
        "/api/v2/games",
        json=_lobby_create_request(),
    ).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-stop-active-1",
    )
    tts_client = client.app.state.v2_test_tts_client
    tts_client.release.clear()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("bytes") is not None:
                break

        stopped = client.post(
            f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
            json={"reason": "当前语音异常，人工立即打断"},
            headers=headers,
        )
        tts_client.release.set()
        assert stopped.status_code == 202, stopped.text
        assert stopped.json()["run_status"] == "canceled"

        terminal = None
        while terminal is None:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") == "canceled":
                terminal = value
        assert terminal["reason"] == "operator_interrupted"
        assert "当前语音异常" not in json.dumps(terminal, ensure_ascii=False)

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None and game.status == "canceled"
        presentations = list(
            db.scalars(select(V2LivePresentation).where(V2LivePresentation.game_id == game.game_id))
        )
        voices = list(db.scalars(select(V2VoiceAsset).where(V2VoiceAsset.game_id == game.game_id)))
        assert len(presentations) == 1
        assert presentations[0].state == "canceled"
        assert len(voices) == 1
        assert voices[0].state == "canceled"
        event_types = list(
            db.scalars(
                select(V2GameRecordEvent.event_type)
                .where(V2GameRecordEvent.game_id == game.game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert "voice_recording_canceled" in event_types
        assert "speech_interrupted" in event_types
        assert "game_canceled" in event_types
        assert "action_failed" not in event_types
    assert client.app.state.v2_test_model_client.call_count == 0
    assert not list(voice_root.rglob("*.tmp"))


def test_admin_viewer_cannot_stop_v2_game(v2_context) -> None:
    client, _session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json={"title": "只读权限"}).json()
    session = client.post("/api/v1/admin/dev-login").json()

    response = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": "只读用户不应成功"},
        headers={
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": "v2-stop-viewer-1",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "admin_permission_denied"


def test_admin_operator_can_stop_awaiting_observation_without_terminal_evidence(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json={"title": "终局证据不完整"}).json()
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        assert game is not None and run is not None
        game.status = "awaiting_observation"
        run.status = "awaiting_observation"

    response = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": "人工终止无法确认完成的对局"},
        headers=_operator_control_headers(
            client,
            session_factory,
            idempotency_key="v2-stop-incomplete-terminal-1",
        ),
    )

    assert response.status_code == 202
    assert response.json()["run_status"] == "canceled"
    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        assert game is not None and game.status == "canceled"
        assert run is not None and run.status == "canceled"
        assert run.stop_requested_at is not None


def test_admin_operator_cannot_stop_v2_game_with_complete_terminal_evidence(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    identifiers = client.post(
        "/api/v2/games",
        json=_six_player_create_request(),
    ).json()
    completed_at = datetime.now(tz=UTC)
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        match = db.get(V2MatchState, identifiers["game_id"])
        assert game is not None and run is not None and match is not None
        game.status = "awaiting_observation"
        game.phase_state = "game_completed"
        run.status = "awaiting_observation"
        run.completed_at = completed_at
        match.winner = "villagers"
        match.completion_reason = "deterministic_win_condition"
        next_seq = game.last_record_seq + 1
        db.add(
            V2GameRecordEvent(
                game_id=game.game_id,
                event_id=next_seq,
                record_seq=next_seq,
                run_id=run.run_id,
                event_type="game_completed",
                payload_schema_version=1,
                payload={
                    "winner": "villagers",
                    "completion_reason": "deterministic_win_condition",
                    "audience": "all",
                    "audience_contract_version": 1,
                },
            )
        )
        game.last_record_seq = next_seq

    response = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
        json={"reason": "不应覆盖已完成对局"},
        headers=_operator_control_headers(
            client,
            session_factory,
            idempotency_key="v2-stop-complete-terminal-1",
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "admin_v2_game_not_active"
    with session_factory() as db:
        run = db.get(V2GameRun, identifiers["run_id"])
        assert run is not None and run.stop_requested_at is None


def test_executable_rule_runs_dynamic_first_night_without_leaking_private_actions(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.split_werewolf_preferences = True
    model_client.concurrent_barrier_action_types = {
        "ability_werewolf.attack_decision",
        "ability_guard.protect_decision",
        "ability_seer.investigate_decision",
    }
    model_client.concurrent_barrier_expected = 4
    tts_client = client.app.state.v2_test_tts_client
    create_request = _six_player_create_request()
    for profile in create_request["lobby_snapshot"]["player_configs"]:
        profile["tts_speaker"] = "zh_female_vv_uranus_bigtts"
        profile["tts_dialect"] = "sichuan"
    created = client.post("/api/v2/games", json=create_request)
    assert created.status_code == 201, created.text
    identifiers = created.json()

    public_texts: list[str] = []
    public_types: list[str] = []
    god_texts: list[str] = []
    god_types: list[str] = []
    with client.websocket_connect(identifiers["websocket_url"]) as public_socket:
        with client.websocket_connect(
            identifiers["god_view_websocket_url"],
            subprotocols=["live-v2-god-view", identifiers["god_view_access_token"]],
        ) as god_socket:
            public_socket.receive_json()
            god_socket.receive_json()
            public_socket.send_json(_ready_message("client.ready"))
            god_socket.send_json(_ready_message("god_view.ready"))
            assert public_socket.receive_json()["type"] == "live.snapshot"
            assert god_socket.receive_json()["type"] == "god_view.live_snapshot"
            _collect_until_observation(
                public_socket,
                message_types=public_types,
                committed_texts=public_texts,
            )
            _collect_until_observation(
                god_socket,
                message_types=god_types,
                committed_texts=god_texts,
            )

    assert public_texts[:2] == [
        "欢迎来到动态首夜 6 人。本局共6名玩家，对局现在开始。",
        "首夜开始，请所有玩家闭眼。",
    ]
    assert any(text.startswith("天亮了，昨夜") for text in public_texts)
    assert "第1天白天讨论现在开始，请存活玩家按照发言顺序依次发言。" in public_texts
    assert "第1天白天讨论现在开始，请存活玩家按照发言顺序依次发言。" in god_texts
    assert "这项首夜能力现在开始实时执行。" not in public_texts
    assert "night.progress_changed" in public_types
    assert "ability.progress_changed" not in public_types
    assert "god_view.night_resolved" not in public_types
    assert "ability.progress_changed" in god_types
    assert "god_view.night_resolved" in god_types
    assert "night.progress_changed" not in god_types
    assert "狼人请睁眼，请依次商议今晚的袭击目标。" in god_texts
    assert "我先说明自己的判断。这是第二句话！\n现在执行这次实时决策。" in god_texts
    assert "sichuan" in tts_client.dialects
    assert model_client.concurrent_barrier_max_in_flight >= 4
    assert model_client.concurrent_barrier_all_started is not None
    assert model_client.concurrent_barrier_all_started.is_set()
    player_contexts = model_client.decision_contexts
    assert player_contexts
    assert any(context["task"]["type"].startswith("ability_") for context in player_contexts)
    assert any(context["task"]["type"] == "day_debate_speech" for context in player_contexts)
    assert all(
        context["rules"]["player_count"] == 6
        and context["rules"]["werewolf_count"] == 2
        and context["rules"]["sheriff"]["enabled"] is False
        for context in player_contexts
    )
    assert all(
        context["model_context_schema_version"] == 9
        and context["prompt_template_version"] == 2
        and "private_judge_facts" not in context["self"]
        and "ability_runtime_state" in context["self"]
        and "mechanical_effect" in context["task"]
        and "state" in context
        and context["known_events"]["schema_version"] == 3
        and "events" in context["known_events"]
        and "questions" in context["known_events"]
        and "relations" in context["known_events"]
        and "public_timeline" not in context
        and "history" not in context
        and "role_information_boundaries" not in context
        and "canonical_public_timeline" not in context
        and "public_event_counters" not in context
        and "information_semantics" not in context
        and "public_rules" not in context
        and "allowed_knowledge" not in context
        for context in player_contexts
    )
    wolf_contexts = [
        context
        for context in player_contexts
        if context["self"]["identity"]["role_key"] == "werewolf"
    ]
    assert wolf_contexts
    for context in wolf_contexts:
        assert context["self"]["werewolf_coordination"] == {"mode": "team"}
        teammate_events = [
            event
            for event in context["known_events"]["events"]
            if event.get("kind") == "living_werewolf_teammates"
        ]
        assert len(teammate_events) == 1
        teammate_refs = teammate_events[0]["data"]["teammate_refs"]
        assert set(teammate_refs) <= set(context["state"]["alive_player_ids"])
        assert context["self"]["identity"]["player_id"] not in teammate_refs
        assert not any(
            event.get("kind") == "werewolf_teammates" for event in context["known_events"]["events"]
        )
    assert all(
        "knowledge" not in context["self"]["identity"]
        for context in player_contexts
        if context["self"].get("identity")
    )
    wolf_preference_contexts = [
        context
        for context in player_contexts
        if context["task"].get("ability_id") == "werewolf.attack"
        and any(
            fact.get("fact_type") == "coordination"
            and fact.get("payload") == "parallel_preference_probe"
            for fact in _private_known_facts(context)
        )
    ]
    assert wolf_preference_contexts
    assert all(
        any(
            fact.get("fact_type") == "decision_stage" and fact.get("payload") == "preference_probe"
            for fact in _private_known_facts(context)
        )
        and context["response"]["speech"]["mode"] == "forbidden"
        and context["response"]["decision_note"]
        == {"type": "string", "mode": "optional", "max_chars": 80}
        and all(
            fact.get("fact_type") not in {"werewolf_first_round", "werewolf_second_round_so_far"}
            for fact in _private_known_facts(context)
        )
        for context in wolf_preference_contexts
    )
    wolf_sequential_contexts = [
        context
        for context in player_contexts
        if context["task"].get("ability_id") == "werewolf.attack"
        and any(
            fact.get("fact_type") == "coordination"
            and fact.get("payload") == "sequential_shared_discussion"
            for fact in _private_known_facts(context)
        )
    ]
    assert wolf_sequential_contexts
    first_round_by_night: dict[int, set[str]] = {}
    for context in wolf_sequential_contexts:
        private_facts = _private_known_facts(context)
        first_round = next(
            fact["payload"]
            for fact in private_facts
            if fact.get("fact_type") == "werewolf_first_round"
        )
        second_round_so_far = next(
            fact["payload"]
            for fact in private_facts
            if fact.get("fact_type") == "werewolf_second_round_so_far"
        )
        speaking_position = next(
            fact["payload"]
            for fact in private_facts
            if fact.get("fact_type") == "speaking_position"
        )
        assert len(first_round) == 2
        assert all(
            item["player_id"].startswith("seat_")
            and item["target_player_id"].startswith("seat_")
            and item["status"] == "completed"
            and "speech" not in item
            and "decision_note" not in item
            for item in first_round
        )
        own_blind_decisions = [
            fact["payload"]
            for fact in private_facts
            if fact.get("fact_type") == "private_ability_action_committed"
            and fact.get("payload", {}).get("ability_id") == "werewolf.attack"
            and fact.get("payload", {}).get("night_no") == context["task"]["night_no"]
            and fact.get("payload", {}).get("decision", {}).get("decision_stage")
            == "preference_probe"
        ]
        assert len(own_blind_decisions) == 1
        assert own_blind_decisions[0]["declared_reason"] == {
            "text": (
                f"{context['self']['identity']['player_id']}在"
                "ability_werewolf.attack_decision动作发生时选择当前目标。"
            ),
            "epistemic_status": "actor_declared_reason",
        }
        assert "decision_note" not in own_blind_decisions[0]["decision"]
        assert context["response"]["speech"] == {
            "type": "string",
            "mode": "required",
            "min_length": 1,
            "max_sentences": 1,
        }
        assert "decision_note" not in context["response"]
        assert len(second_round_so_far) == speaking_position - 1
        first_round_by_night.setdefault(
            context["task"]["night_no"],
            set(),
        ).add(json.dumps(first_round, ensure_ascii=False, sort_keys=True))
    assert all(len(transcripts) == 1 for transcripts in first_round_by_night.values())
    seer_contexts = [
        context
        for context in player_contexts
        if context.get("self", {}).get("identity", {}).get("role_key") == "seer"
    ]
    assert seer_contexts
    assert all(
        [item["ability_id"] for item in context["self"]["role_capabilities"]["abilities"]]
        == ["seer.investigate"]
        for context in seer_contexts
    )
    surviving_seer_day_contexts = [
        context for context in seer_contexts if not context["task"]["type"].startswith("ability_")
    ]
    if surviving_seer_day_contexts:
        assert any(
            fact.get("fact_type") == "investigation_alignment"
            for context in surviving_seer_day_contexts
            for fact in _private_known_facts(context)
        )
    contexts_after_heal_use = [
        context
        for context in player_contexts
        if any(
            fact.get("fact_type") == "private_ability_action_committed"
            and fact.get("payload", {}).get("ability_id") == "witch.heal"
            and fact.get("payload", {}).get("result", {}).get("heal_used") is True
            for fact in _private_known_facts(context)
        )
    ]
    if contexts_after_heal_use:
        assert all(
            next(
                item
                for item in context["self"]["ability_runtime_state"]["abilities"]
                if item["ability_id"] == "witch.heal"
            )["resource_status"]
            == "consumed"
            for context in contexts_after_heal_use
        )
    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None
        assert game.status == "awaiting_observation"
        assert game.phase_id.startswith("day_")
        assert game.phase_state == "game_completed"
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == game.game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        first_batch_started = next(
            event for event in events if event.event_type == "night_parallel_batch_started"
        )
        first_batch_id = first_batch_started.payload["batch_id"]
        first_batch_cutoff = first_batch_started.payload["public_cutoff_record_seq"]
        first_batch_actions = [
            event
            for event in events
            if event.event_type == "action_opened"
            and event.payload.get("context", {}).get("night_parallel_batch_id") == first_batch_id
        ]
        first_batch_action_types = {
            event.payload["context"]["action_type"] for event in first_batch_actions
        }
        assert first_batch_action_types >= {
            "ability_werewolf.attack_decision",
            "ability_guard.protect_decision",
            "ability_seer.investigate_decision",
        }
        assert {
            event.payload["context"]["public_cutoff_record_seq"] for event in first_batch_actions
        } == {first_batch_cutoff}
        guard_and_seer_actions = [
            event
            for event in first_batch_actions
            if event.payload["context"]["action_type"]
            in {"ability_guard.protect_decision", "ability_seer.investigate_decision"}
        ]
        assert all(
            "werewolf_attack_resolved"
            not in json.dumps(event.payload["context"], ensure_ascii=False)
            and "final_target_player_id"
            not in json.dumps(event.payload["context"], ensure_ascii=False)
            for event in guard_and_seer_actions
        )
        first_batch_resolved = next(
            event
            for event in events
            if event.event_type == "night_parallel_batch_resolved"
            and event.payload["batch_id"] == first_batch_id
        )
        ability_completion_seqs = {
            ability_id: [
                event.record_seq
                for event in events
                if event.event_type == "ability_activation_completed"
                and event.record_seq < first_batch_resolved.record_seq
                and event.payload.get("ability_id") == ability_id
            ]
            for ability_id in (
                "werewolf.attack",
                "guard.protect",
                "seer.investigate",
            )
        }
        assert all(ability_completion_seqs.values())
        assert max(ability_completion_seqs["werewolf.attack"]) < min(
            ability_completion_seqs["guard.protect"]
        )
        assert max(ability_completion_seqs["guard.protect"]) < min(
            ability_completion_seqs["seer.investigate"]
        )
        opening_event = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == game.game_id,
                V2GameRecordEvent.event_type == "action_opened",
                V2GameRecordEvent.payload["context"]["action_type"].as_string()
                == "judge_opening_speech",
            )
        )
        assert opening_event is not None
        assert opening_event.payload["context"]["game_setup"] == {
            "rule_name": "动态首夜 6 人",
            "player_count": 6,
            "role_summary": None,
            "max_rounds": 8,
        }
        windows = list(
            db.scalars(
                select(V2ActionWindow)
                .where(V2ActionWindow.game_id == game.game_id)
                .order_by(V2ActionWindow.window_seq)
            )
        )
        assert windows and all(item.state == "closed" for item in windows)
        activations = list(
            db.scalars(
                select(V2AbilityActivation).where(V2AbilityActivation.game_id == game.game_id)
            )
        )
        assert len(activations) >= 4
        assert all(item.status in {"completed", "skipped"} for item in activations)
        effects = list(
            db.scalars(select(V2EffectIntent).where(V2EffectIntent.game_id == game.game_id))
        )
        assert {item.effect_type for item in effects} >= {
            "attack",
            "protect",
            "investigate",
        }
        assert all(item.state == "resolved" for item in effects)
        shoot_effects = [item for item in effects if item.effect_type == "shoot"]
        assert all(
            item.resolved_at is not None and item.payload.get("outcome") == "killed"
            for item in shoot_effects
        )
        resolved_effect_ids = {
            event.payload.get("effect_intent_id")
            for event in events
            if event.event_type == "effect_intent_resolved"
        }
        assert {item.effect_intent_id for item in shoot_effects} <= resolved_effect_ids
        facts = list(
            db.scalars(select(V2KnowledgeFact).where(V2KnowledgeFact.game_id == game.game_id))
        )
        assert len(facts) >= 5
        assert sum(item.fact_type == "investigation_alignment" for item in facts) >= 1
        assert sum(item.fact_type == "private_ability_action_committed" for item in facts) >= 4
        assert any(
            item.fact_type == "private_ability_action_committed"
            and item.payload.get("ability_id") == "seer.investigate"
            and item.payload.get("declared_reason", {}).get("epistemic_status")
            == "actor_declared_reason"
            for item in facts
        )
        assert all(
            item.payload["resolution_scope"].startswith("法官已接受本次私有动作")
            for item in facts
            if item.fact_type == "private_ability_action_committed"
        )
        assert all(
            len(item.payload["normalized_sha256"]) == 64
            for item in facts
            if item.fact_type == "action_context_projection"
        )
        presentations = list(
            db.scalars(
                select(V2LivePresentation)
                .where(V2LivePresentation.game_id == game.game_id)
                .order_by(V2LivePresentation.presentation_seq)
            )
        )
        assert {item.audience for item in presentations} == {"all", "god_view"}
        assert any(item.actor_kind == "player" for item in presentations)
        assert all(item.state == "closed" for item in presentations)
        assert all(
            item.activation_id is not None
            for item in presentations
            if item.actor_kind == "player"
            and (item.phase_id == "first_night" or item.phase_id.startswith("night_"))
        )


def test_text_only_sustained_werewolf_disagreement_is_private_and_durable(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    external_tts = client.app.state.v2_test_tts_client
    request = _six_player_create_request()
    request["audio_mode"] = "text_only"
    identifiers = _create_rotating_werewolf_game(
        session_factory=session_factory,
        request=request,
        audio_mode="text_only",
    )

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assignments = list(
            db.scalars(
                select(V2RoleAssignment)
                .where(V2RoleAssignment.game_id == identifiers["game_id"])
                .order_by(V2RoleAssignment.seat)
            )
        )
        assert game is not None
        assert game.delivery_snapshot["mode"] == "text_only"
        assert game.rule_snapshot["rule_set"]["werewolf_attack_policy"] == {
            "resolution": "plurality_rotating_tiebreak",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        }
        assert (
            game.ability_snapshot["policies"]["werewolf_attack"]
            == (game.rule_snapshot["rule_set"]["werewolf_attack_policy"])
        )
        assert game.ability_snapshot_hash == game.ability_snapshot["snapshot_hash"]
        wolf_players = [
            (assignment.player_id, assignment.seat)
            for assignment in assignments
            if assignment.role_key == "werewolf"
        ]
        non_wolf_players = [
            (assignment.player_id, assignment.seat)
            for assignment in assignments
            if assignment.role_key != "werewolf"
        ]
    assert len(wolf_players) == 2 and len(non_wolf_players) >= 2
    wolf_refs = [f"seat_{seat}" for _player_id, seat in wolf_players]
    target_refs = [f"seat_{seat}" for _player_id, seat in non_wolf_players[:2]]
    for actor_ref, target_ref in zip(wolf_refs, target_refs, strict=True):
        model_client.werewolf_target_by_stage[(1, "preference_probe", actor_ref)] = target_ref
        model_client.werewolf_target_by_stage[(1, "sequential_final_vote", actor_ref)] = target_ref
    model_client.werewolf_target_by_stage[(1, "tiebreak", wolf_refs[0])] = target_refs[0]

    private_note = "狼队盲选私密理由，不得进入公开或非狼人上下文。"
    private_speeches = {actor_ref: f"{actor_ref}坚持自己的私密刀口。" for actor_ref in wolf_refs}
    model_client.decision_note_by_action_type["ability_werewolf.attack_decision"] = private_note
    for actor_ref, speech in private_speeches.items():
        model_client.speech_by_actor_and_action_type[
            (actor_ref, "ability_werewolf.attack_decision")
        ] = speech

    public_texts: list[str] = []
    public_types: list[str] = []
    god_texts: list[str] = []
    god_types: list[str] = []
    with client.websocket_connect(identifiers["websocket_url"]) as public_socket:
        with client.websocket_connect(
            identifiers["god_view_websocket_url"],
            subprotocols=["live-v2-god-view", identifiers["god_view_access_token"]],
        ) as god_socket:
            public_socket.receive_json()
            god_socket.receive_json()
            public_socket.send_json(_ready_message("client.ready"))
            god_socket.send_json(_ready_message("god_view.ready"))
            public_socket.receive_json()
            god_socket.receive_json()
            _collect_until_observation(
                public_socket,
                message_types=public_types,
                committed_texts=public_texts,
            )
            _collect_until_observation(
                god_socket,
                message_types=god_types,
                committed_texts=god_texts,
            )

    assert external_tts.call_count == 0
    assert "ability.progress_changed" not in public_types
    assert "god_view.night_resolved" not in public_types
    assert "ability.progress_changed" in god_types
    assert set(private_speeches.values()) <= set(god_texts)
    assert set(private_speeches.values()).isdisjoint(public_texts)

    night_one_wolf_contexts = [
        context
        for context in model_client.decision_contexts
        if context["task"].get("ability_id") == "werewolf.attack"
        and context["task"].get("night_no") == 1
    ]
    assert night_one_wolf_contexts
    assert {_model_decision_stage(context) for context in night_one_wolf_contexts} == {
        "preference_probe",
        "sequential_final_vote",
        "tiebreak",
    }
    tiebreak_contexts = [
        context
        for context in night_one_wolf_contexts
        if _model_decision_stage(context) == "tiebreak"
    ]
    assert len(tiebreak_contexts) == 1
    assert tiebreak_contexts[0]["self"]["identity"]["player_id"] == wolf_refs[0]
    assert {candidate["player_id"] for candidate in tiebreak_contexts[0]["candidates"]} == set(
        target_refs
    )
    assert any(
        fact.get("fact_type") == "werewolf_final_votes"
        and {item["target_player_id"] for item in fact["payload"]} == set(target_refs)
        for fact in _private_known_facts(tiebreak_contexts[0])
    )

    sensitive_values = {private_note, *private_speeches.values()}
    non_wolf_contexts = [
        context
        for context in model_client.decision_contexts
        if context.get("self", {}).get("identity", {}).get("role_key") != "werewolf"
    ]
    assert non_wolf_contexts
    for context in non_wolf_contexts:
        serialized = json.dumps(context, ensure_ascii=False)
        assert sensitive_values.isdisjoint(_nested_strings(context))
        assert "werewolf_first_round" not in serialized
        assert "werewolf_second_round_so_far" not in serialized
        assert "werewolf_final_votes" not in serialized

    public_snapshot = client.get(identifiers["snapshot_url"])
    assert public_snapshot.status_code == 200
    serialized_snapshot = json.dumps(public_snapshot.json(), ensure_ascii=False)
    assert all(value not in serialized_snapshot for value in sensitive_values)
    assert "werewolf_first_round" not in serialized_snapshot
    assert "werewolf_final_votes" not in serialized_snapshot

    with session_factory() as db:
        activations = list(
            db.scalars(
                select(V2AbilityActivation).where(
                    V2AbilityActivation.game_id == identifiers["game_id"]
                )
            )
        )
        team_resolution = next(
            activation
            for activation in activations
            if (activation.decision or {}).get("decision_stage") == "team_resolution"
            and (activation.result or {}).get("resolution_reason") == "explicit_rotating_tiebreak"
        )
        tiebreak = next(
            activation
            for activation in activations
            if (activation.decision or {}).get("decision_stage") == "tiebreak"
        )
        effects = list(
            db.scalars(
                select(V2EffectIntent).where(
                    V2EffectIntent.game_id == identifiers["game_id"],
                    V2EffectIntent.activation_id == team_resolution.activation_id,
                )
            )
        )
        team_facts = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.source_activation_id == team_resolution.activation_id,
                    V2KnowledgeFact.fact_type == "private_ability_action_committed",
                )
            )
        )
        private_wolf_presentations = list(
            db.scalars(
                select(V2LivePresentation).where(
                    V2LivePresentation.game_id == identifiers["game_id"],
                    V2LivePresentation.actor_id.in_(
                        [player_id for player_id, _seat in wolf_players]
                    ),
                    V2LivePresentation.audience == "god_view",
                )
            )
        )
        private_action_ids = {item.action_id for item in private_wolf_presentations}
        private_events = list(
            db.scalars(
                select(V2GameRecordEvent).where(V2GameRecordEvent.game_id == identifiers["game_id"])
            )
        )
        voice_count = db.scalar(
            select(func.count())
            .select_from(V2VoiceAsset)
            .where(V2VoiceAsset.game_id == identifiers["game_id"])
        )

    assert tiebreak.actor_player_id == wolf_players[0][0]
    assert len(effects) == 1
    assert effects[0].effect_type == "attack"
    assert effects[0].target_player_id == team_resolution.result["final_target_player_id"]
    assert len(team_facts) == len(wolf_players)
    assert {fact.payload["decision"]["final_target_player_id"] for fact in team_facts} == {
        team_resolution.result["final_target_player_id"]
    }
    assert all(activation.status in {"completed", "skipped"} for activation in activations)
    assert private_wolf_presentations
    assert all(
        item.state == "closed" and item.voice_asset_id is None
        for item in private_wolf_presentations
    )
    assert private_action_ids
    assert all(
        event.payload.get("audience") == "god_view"
        for event in private_events
        if event.payload.get("action_id") in private_action_ids
    )
    assert voice_count == 0


def test_tts_werewolf_private_presentations_keep_one_audience_across_lifecycle(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    external_tts = client.app.state.v2_test_tts_client
    request = _six_player_create_request()
    request["audio_mode"] = "tts"
    identifiers = _create_rotating_werewolf_game(
        session_factory=session_factory,
        request=request,
        audio_mode="tts",
    )

    with session_factory() as db:
        assignments = list(
            db.scalars(
                select(V2RoleAssignment)
                .where(V2RoleAssignment.game_id == identifiers["game_id"])
                .order_by(V2RoleAssignment.seat)
            )
        )
        wolf_players = [
            (assignment.player_id, assignment.seat)
            for assignment in assignments
            if assignment.role_key == "werewolf"
        ]
        non_wolf_players = [
            (assignment.player_id, assignment.seat)
            for assignment in assignments
            if assignment.role_key != "werewolf"
        ]
    assert len(wolf_players) == 2 and len(non_wolf_players) >= 2
    wolf_refs = [f"seat_{seat}" for _player_id, seat in wolf_players]
    target_refs = [f"seat_{seat}" for _player_id, seat in non_wolf_players[:2]]
    for actor_ref, target_ref in zip(wolf_refs, target_refs, strict=True):
        model_client.werewolf_target_by_stage[(1, "preference_probe", actor_ref)] = target_ref
        model_client.werewolf_target_by_stage[(1, "sequential_final_vote", actor_ref)] = target_ref
        model_client.speech_by_actor_and_action_type[
            (actor_ref, "ability_werewolf.attack_decision")
        ] = f"{actor_ref}坚持自己的私密刀口。"
    model_client.werewolf_target_by_stage[(1, "tiebreak", wolf_refs[0])] = target_refs[0]

    public_texts: list[str] = []
    public_types: list[str] = []
    god_texts: list[str] = []
    god_types: list[str] = []
    with client.websocket_connect(identifiers["websocket_url"]) as public_socket:
        with client.websocket_connect(
            identifiers["god_view_websocket_url"],
            subprotocols=["live-v2-god-view", identifiers["god_view_access_token"]],
        ) as god_socket:
            public_socket.receive_json()
            god_socket.receive_json()
            public_socket.send_json(_ready_message("client.ready"))
            god_socket.send_json(_ready_message("god_view.ready"))
            public_socket.receive_json()
            god_socket.receive_json()
            _collect_until_observation(
                public_socket,
                message_types=public_types,
                committed_texts=public_texts,
            )
            _collect_until_observation(
                god_socket,
                message_types=god_types,
                committed_texts=god_texts,
            )

    private_speeches = {f"{actor_ref}坚持自己的私密刀口。" for actor_ref in wolf_refs}
    assert external_tts.call_count > 0
    assert private_speeches <= set(god_texts)
    assert private_speeches.isdisjoint(public_texts)

    with session_factory() as db:
        activations = list(
            db.scalars(
                select(V2AbilityActivation).where(
                    V2AbilityActivation.game_id == identifiers["game_id"]
                )
            )
        )
        tiebreak = next(
            activation
            for activation in activations
            if (activation.decision or {}).get("decision_stage") == "tiebreak"
        )
        spoken_activations = [
            activation
            for activation in activations
            if activation.window_id == tiebreak.window_id
            and (activation.decision or {}).get("decision_stage")
            in {"sequential_final_vote", "tiebreak"}
        ]
        activation_ids = {activation.activation_id for activation in spoken_activations}
        presentations = list(
            db.scalars(
                select(V2LivePresentation)
                .where(
                    V2LivePresentation.game_id == identifiers["game_id"],
                    V2LivePresentation.activation_id.in_(activation_ids),
                )
                .order_by(V2LivePresentation.presentation_seq)
            )
        )
        voice_ids = {
            presentation.voice_asset_id
            for presentation in presentations
            if presentation.voice_asset_id is not None
        }
        voices = list(
            db.scalars(
                select(V2VoiceAsset).where(
                    V2VoiceAsset.game_id == identifiers["game_id"],
                    V2VoiceAsset.voice_asset_id.in_(voice_ids),
                )
            )
        )
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )

    assert len(spoken_activations) == len(presentations) == len(voices) == 3
    assert {presentation.activation_id for presentation in presentations} == activation_ids
    voices_by_id = {voice.voice_asset_id: voice for voice in voices}
    expected_event_types = [
        "speech_opened",
        "speech_segment_committed",
        "speech_sealed",
        "tts_stream_started",
        "tts_first_chunk_received",
        "voice_recording_started",
        "audio_broadcast_started",
        "tts_stream_completed",
        "voice_asset_saved",
        "audio_drained",
        "speech_closed",
    ]
    expected_pcm_sha256 = hashlib.sha256(PCM_CHUNK * 2).hexdigest()
    for presentation in presentations:
        assert presentation.state == "closed"
        assert presentation.audience == "god_view"
        assert presentation.voice_asset_id is not None
        assert presentation.audio_asset_id == presentation.voice_asset_id
        assert presentation.audio_mime_type == "audio/wav"
        assert presentation.closed_at is not None
        voice = voices_by_id[presentation.voice_asset_id]
        assert voice.state == "ready"
        assert voice.audience == presentation.audience
        assert voice.action_id == presentation.action_id
        assert voice.activation_id == presentation.activation_id
        assert voice.presentation_id == presentation.presentation_id
        assert voice.speech_id == presentation.speech_id
        assert voice.segment_index == presentation.segment_index
        assert voice.sample_count == 480
        assert voice.pcm_sha256 == expected_pcm_sha256
        assert voice.mime_type == presentation.audio_mime_type
        assert voice.duration_ms == presentation.audio_duration_ms
        wav_path = voice_root / voice.storage_key
        assert wav_path.exists()
        assert wav_path.read_bytes().startswith(b"RIFF")

        presentation_events = [
            event
            for event in events
            if event.payload.get("presentation_id") == presentation.presentation_id
            and event.event_type in expected_event_types
        ]
        assert [event.event_type for event in presentation_events] == expected_event_types
        assert all(
            event.payload.get("audience") == "god_view"
            and event.payload.get("audience_contract_version") == 1
            and event.payload.get("action_id") == presentation.action_id
            for event in presentation_events
        )
        committed = next(
            event for event in presentation_events if event.event_type == "speech_segment_committed"
        )
        assert committed.event_id == presentation.source_event_id
        assert committed.payload["text"] == presentation.subtitle_text
        assert all(
            event.payload.get("voice_asset_id") == presentation.voice_asset_id
            for event in presentation_events
            if "voice_asset_id" in event.payload
        )


def test_rotating_werewolf_tiebreaker_changes_on_second_night_with_real_repository(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    external_tts = client.app.state.v2_test_tts_client
    request = _advanced_create_request()
    request["audio_mode"] = "text_only"
    identifiers = _create_rotating_werewolf_game(
        session_factory=session_factory,
        request=request,
        audio_mode="text_only",
    )

    with session_factory.begin() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        match = db.get(V2MatchState, identifiers["game_id"])
        assignments = list(
            db.scalars(
                select(V2RoleAssignment)
                .where(V2RoleAssignment.game_id == identifiers["game_id"])
                .order_by(V2RoleAssignment.seat)
            )
        )
        assert game is not None and run is not None and match is not None
        wolf_players = [
            (assignment.player_id, assignment.seat)
            for assignment in assignments
            if assignment.role_key == "werewolf"
        ]
        non_wolf_players = [
            (assignment.player_id, assignment.seat)
            for assignment in assignments
            if assignment.role_key != "werewolf"
        ]
        assert len(wolf_players) == 4 and len(non_wolf_players) >= 2
        game.status = "ready"
        game.phase_id = "first_night"
        game.phase_state = "nightfall_announced"
        run.status = "ready"
        match.round_no = 1

    wolf_refs = [f"seat_{seat}" for _player_id, seat in wolf_players]
    target_refs = [f"seat_{seat}" for _player_id, seat in non_wolf_players[:2]]
    split_targets = [target_refs[0], target_refs[0], target_refs[1], target_refs[1]]
    for night_no in (1, 2):
        for actor_ref, target_ref in zip(wolf_refs, split_targets, strict=True):
            model_client.werewolf_target_by_stage[(night_no, "preference_probe", actor_ref)] = (
                target_ref
            )
            model_client.werewolf_target_by_stage[
                (night_no, "sequential_final_vote", actor_ref)
            ] = target_ref
    model_client.werewolf_target_by_stage[(1, "tiebreak", wolf_refs[0])] = target_refs[0]
    model_client.werewolf_target_by_stage[(2, "tiebreak", wolf_refs[1])] = target_refs[1]

    night_repository, night_engine = _unfenced_text_only_night_engine(
        client=client,
        session_factory=session_factory,
        voice_root=voice_root,
    )

    async def scenario() -> tuple[Any, Any, _WorkingNight, _WorkingNight]:
        first_state = night_repository.start_night(
            identifiers["game_id"],
            audience="god_view",
        )
        first_working = _WorkingNight()
        await night_engine._run_werewolves(
            first_state,
            _CollectingBroadcaster(),
            first_working,
        )
        with session_factory.begin() as db:
            first_window = db.get(V2ActionWindow, first_state.window_id)
            game = db.get(V2GameRecord, identifiers["game_id"])
            run = db.get(V2GameRun, identifiers["run_id"])
            match = db.get(V2MatchState, identifiers["game_id"])
            assert (
                first_window is not None
                and game is not None
                and run is not None
                and match is not None
            )
            first_window.state = "closed"
            first_window.result = {"fixture_transition": "night_2"}
            first_window.closed_at = datetime.now(tz=UTC)
            game.status = "ready"
            game.phase_id = "night_2"
            game.phase_state = "nightfall_announced"
            run.status = "ready"
            match.round_no = 2
        second_state = night_repository.start_night(
            identifiers["game_id"],
            audience="god_view",
        )
        second_working = _WorkingNight()
        await night_engine._run_werewolves(
            second_state,
            _CollectingBroadcaster(),
            second_working,
        )
        return first_state, second_state, first_working, second_working

    first_state, second_state, first_working, second_working = asyncio.run(scenario())

    assert (first_state.round_no, second_state.round_no) == (1, 2)
    assert first_working.attack_target is not None
    assert second_working.attack_target is not None
    assert external_tts.call_count == 0
    tiebreak_contexts = [
        context
        for context in model_client.decision_contexts
        if context["task"].get("ability_id") == "werewolf.attack"
        and _model_decision_stage(context) == "tiebreak"
    ]
    assert [context["task"]["night_no"] for context in tiebreak_contexts] == [1, 2]
    assert [context["self"]["identity"]["player_id"] for context in tiebreak_contexts] == wolf_refs[
        :2
    ]

    with session_factory() as db:
        for state, expected_actor_id, working in (
            (first_state, wolf_players[0][0], first_working),
            (second_state, wolf_players[1][0], second_working),
        ):
            activations = list(
                db.scalars(
                    select(V2AbilityActivation).where(
                        V2AbilityActivation.game_id == identifiers["game_id"],
                        V2AbilityActivation.window_id == state.window_id,
                    )
                )
            )
            assert activations and all(
                activation.status == "completed" for activation in activations
            )
            tiebreak = next(
                activation
                for activation in activations
                if (activation.decision or {}).get("decision_stage") == "tiebreak"
            )
            team_resolution = next(
                activation
                for activation in activations
                if (activation.decision or {}).get("decision_stage") == "team_resolution"
            )
            effect = db.scalar(
                select(V2EffectIntent).where(
                    V2EffectIntent.activation_id == team_resolution.activation_id
                )
            )
            assert tiebreak.actor_player_id == expected_actor_id
            assert team_resolution.result["resolution_reason"] == ("explicit_rotating_tiebreak")
            assert effect is not None and effect.effect_type == "attack"
            assert (
                effect.target_player_id
                == team_resolution.result["final_target_player_id"]
                == working.attack_target
            )
        voice_count = db.scalar(
            select(func.count())
            .select_from(V2VoiceAsset)
            .where(V2VoiceAsset.game_id == identifiers["game_id"])
        )
    assert voice_count == 0


def test_rotating_werewolf_order_skips_dead_wolf_with_real_repository(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    request = _advanced_create_request()
    request["audio_mode"] = "text_only"
    identifiers = _create_rotating_werewolf_game(
        session_factory=session_factory,
        request=request,
        audio_mode="text_only",
    )

    with session_factory.begin() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        match = db.get(V2MatchState, identifiers["game_id"])
        assignments = list(
            db.scalars(
                select(V2RoleAssignment)
                .where(V2RoleAssignment.game_id == identifiers["game_id"])
                .order_by(V2RoleAssignment.seat)
            )
        )
        assert game is not None and run is not None and match is not None
        wolf_players = [
            (assignment.player_id, assignment.seat)
            for assignment in assignments
            if assignment.role_key == "werewolf"
        ]
        non_wolf_players = [
            (assignment.player_id, assignment.seat)
            for assignment in assignments
            if assignment.role_key != "werewolf"
        ]
        assert len(wolf_players) == 4 and len(non_wolf_players) >= 3
        dead_wolf_id = wolf_players[1][0]
        dead_wolf_state = db.get(
            V2PlayerState,
            (identifiers["game_id"], dead_wolf_id),
        )
        assert dead_wolf_state is not None
        dead_wolf_state.alive = False
        dead_wolf_state.death_cause = "exile"
        dead_wolf_state.death_window_seq = 1
        game.status = "ready"
        game.phase_id = "night_2"
        game.phase_state = "nightfall_announced"
        run.status = "ready"
        match.round_no = 2

    wolf_refs = [f"seat_{seat}" for _player_id, seat in wolf_players]
    target_refs = [f"seat_{seat}" for _player_id, seat in non_wolf_players[:3]]
    expected_survivor_order = [wolf_refs[2], wolf_refs[3], wolf_refs[0]]
    for actor_ref, target_ref in zip(
        expected_survivor_order,
        target_refs,
        strict=True,
    ):
        model_client.werewolf_target_by_stage[(2, "preference_probe", actor_ref)] = target_ref
        model_client.werewolf_target_by_stage[(2, "sequential_final_vote", actor_ref)] = target_ref
    model_client.werewolf_target_by_stage[(2, "tiebreak", expected_survivor_order[0])] = (
        target_refs[0]
    )

    night_repository, night_engine = _unfenced_text_only_night_engine(
        client=client,
        session_factory=session_factory,
        voice_root=voice_root,
    )

    async def scenario() -> tuple[Any, _WorkingNight]:
        state = night_repository.start_night(
            identifiers["game_id"],
            audience="god_view",
        )
        working = _WorkingNight()
        await night_engine._run_werewolves(
            state,
            _CollectingBroadcaster(),
            working,
        )
        return state, working

    state, working = asyncio.run(scenario())
    assert state.round_no == 2
    assert working.attack_target is not None
    assert (
        next(player for player in state.players if player.player_id == dead_wolf_id).alive is False
    )

    wolf_contexts = [
        context
        for context in model_client.decision_contexts
        if context["task"].get("ability_id") == "werewolf.attack"
        and context["task"].get("night_no") == 2
    ]
    preference_actor_refs = {
        context["self"]["identity"]["player_id"]
        for context in wolf_contexts
        if _model_decision_stage(context) == "preference_probe"
    }
    sequential_actor_refs = [
        context["self"]["identity"]["player_id"]
        for context in wolf_contexts
        if _model_decision_stage(context) == "sequential_final_vote"
    ]
    tiebreak_context = next(
        context for context in wolf_contexts if _model_decision_stage(context) == "tiebreak"
    )
    assert preference_actor_refs == set(expected_survivor_order)
    assert sequential_actor_refs == expected_survivor_order
    assert tiebreak_context["self"]["identity"]["player_id"] == (expected_survivor_order[0])
    assert {candidate["player_id"] for candidate in tiebreak_context["candidates"]} == set(
        target_refs
    )
    assert wolf_refs[1] not in {
        context["self"]["identity"]["player_id"] for context in wolf_contexts
    }

    with session_factory() as db:
        activations = list(
            db.scalars(
                select(V2AbilityActivation).where(
                    V2AbilityActivation.game_id == identifiers["game_id"],
                    V2AbilityActivation.window_id == state.window_id,
                )
            )
        )
        assert activations and all(activation.status == "completed" for activation in activations)
        tiebreak = next(
            activation
            for activation in activations
            if (activation.decision or {}).get("decision_stage") == "tiebreak"
        )
        team_resolution = next(
            activation
            for activation in activations
            if (activation.decision or {}).get("decision_stage") == "team_resolution"
        )
        effect = db.scalar(
            select(V2EffectIntent).where(
                V2EffectIntent.activation_id == team_resolution.activation_id
            )
        )
    assert tiebreak.actor_player_id == wolf_players[2][0]
    assert [item["player_id"] for item in team_resolution.decision["votes"]] == [
        wolf_players[2][0],
        wolf_players[3][0],
        wolf_players[0][0],
    ]
    assert dead_wolf_id not in {item["player_id"] for item in team_resolution.decision["votes"]}
    assert team_resolution.result["resolution_reason"] == "explicit_rotating_tiebreak"
    assert effect is not None and effect.effect_type == "attack"
    assert (
        effect.target_player_id
        == team_resolution.result["final_target_player_id"]
        == working.attack_target
    )


def test_night_parallel_guard_failure_reuses_activation_and_frozen_knowledge(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.quality_failures_remaining_by_action["ability_guard.protect_decision"] = 2
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()

    with client.websocket_connect(created["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        _collect_until_observation(
            websocket,
            message_types=[],
            committed_texts=[],
        )

    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == created["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        recovery_started = next(
            event for event in events if event.event_type == "night_parallel_batch_recovery_started"
        )
        batch_id = recovery_started.payload["batch_id"]
        assert recovery_started.payload["failed_groups"] == ["guard"]
        recovery_completed = next(
            event
            for event in events
            if event.event_type == "night_parallel_batch_recovery_completed"
            and event.payload["batch_id"] == batch_id
        )
        released = next(
            event
            for event in events
            if event.event_type == "ability_activation_action_released"
            and event.payload["failure_code"] == "model_decision_invalid_speech"
        )
        activation_id = released.payload["activation_id"]
        reused = next(
            event
            for event in events
            if event.event_type == "activation_knowledge_reused"
            and event.payload["activation_id"] == activation_id
        )
        activation = db.get(V2AbilityActivation, activation_id)
        assert activation is not None
        assert activation.status == "completed"
        assert activation.action_id != released.payload["failed_action_id"]
        projection_facts = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.source_activation_id == activation_id,
                    V2KnowledgeFact.fact_type == "action_context_projection",
                )
            )
        )
    assert len(projection_facts) == 1
    assert reused.payload["knowledge_fact_ids"] == [projection_facts[0].knowledge_fact_id]
    guard_completed = next(
        event
        for event in events
        if event.event_type == "ability_activation_completed"
        and event.payload["activation_id"] == activation_id
    )
    assert recovery_completed.record_seq < guard_completed.record_seq
    assert not any(event.event_type == "ability_runtime_failed" for event in events)


def test_night_parallel_cancellation_closes_all_open_activations(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.concurrent_barrier_action_types = {
        "ability_werewolf.attack_decision",
        "ability_guard.protect_decision",
        "ability_seer.investigate_decision",
    }
    model_client.concurrent_barrier_expected = 99
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-stop-night-parallel-batch",
    )

    with client.websocket_connect(created["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        assert model_client.concurrent_barrier_first_started.wait(5)
        stopped = client.post(
            f"/api/v1/admin/v2/games/{created['game_id']}/stop",
            json={"reason": "验证夜间并发批次取消清理"},
            headers=headers,
        )
        assert stopped.status_code == 202, stopped.text
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "canceled":
                break

    with session_factory() as db:
        activations = list(
            db.scalars(
                select(V2AbilityActivation).where(V2AbilityActivation.game_id == created["game_id"])
            )
        )
        events = list(
            db.scalars(
                select(V2GameRecordEvent).where(V2GameRecordEvent.game_id == created["game_id"])
            )
        )
    assert activations
    assert not any(activation.status == "open" for activation in activations)
    assert any(activation.status == "canceled" for activation in activations)
    assert any(event.event_type == "game_canceled" for event in events)


def test_single_wolf_no_sheriff_rule_reaches_day_and_night_model_inputs(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    contradictory_speech = "甲" * 299 + "。我判断1号和2号是双狼，今天先出1号。"
    model_client.speech_by_action_type["day_debate_speech"] = contradictory_speech
    model_client.decision_note_by_action_type["ability_guard.protect_decision"] = "守" * 130
    request = _six_player_create_request()
    request["lobby_snapshot"]["rule_set"]["roles"] = [
        {"role": "werewolf", "count": 1, "team": "werewolves"},
        {"role": "seer", "count": 1, "team": "villagers"},
        {"role": "guard", "count": 1, "team": "villagers"},
        {"role": "villager", "count": 3, "team": "villagers"},
    ]
    created = client.post("/api/v2/games", json=request)
    assert created.status_code == 201, created.text
    identifiers = created.json()
    with session_factory() as db:
        assignments = list(
            db.scalars(
                select(V2RoleAssignment).where(V2RoleAssignment.game_id == identifiers["game_id"])
            )
        )
    wolf = next(item for item in assignments if item.role_key == "werewolf")
    safe_target = next(item for item in assignments if item.role_key == "villager")
    model_client.werewolf_target_by_stage[(1, "sequential_final_vote", f"seat_{wolf.seat}")] = (
        f"seat_{safe_target.seat}"
    )

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        _collect_until_observation(
            websocket,
            message_types=[],
            committed_texts=[],
        )

    contexts = model_client.decision_contexts
    assert all(
        "wolf_cardinality_contradiction" not in json.dumps(context, ensure_ascii=False)
        for context in contexts
    )
    night_contexts = [
        context for context in contexts if context["task"]["type"].startswith("ability_")
    ]
    day_contexts = [
        context for context in contexts if context["task"]["type"] == "day_debate_speech"
    ]
    assert night_contexts
    assert day_contexts
    assert all(
        context["rules"]["werewolf_count"] == 1
        and context["rules"]["reveal_policy"] == "hidden"
        and "不会公开其身份或阵营" in context["rules"]["role_reveal_rule"]
        and context["rules"]["sheriff"]["enabled"] is False
        for context in contexts
    )
    assert all(
        context["state"]["alive_player_count"] == len(context["state"]["alive_player_ids"])
        and context["state"]["eliminated_player_count"]
        == len(context["state"]["eliminated_player_ids"])
        and context["state"]["identity_information_included"] is False
        for context in contexts
    )
    wolf_night_contexts = [
        context
        for context in night_contexts
        if context["task"].get("ability_id") == "werewolf.attack"
    ]
    assert wolf_night_contexts
    assert all(
        context["self"]["werewolf_coordination"] == {"mode": "solo"}
        and all(
            event.get("kind") not in {"werewolf_teammates", "living_werewolf_teammates"}
            for event in context["known_events"]["events"]
        )
        and context["rules"]["current_ability"]["can_target_self"] is False
        and context["rules"]["current_ability"]["coordination"] == "solo"
        and "can_target_werewolf_teammates" not in context["rules"]["current_ability"]
        for context in wolf_night_contexts
    )
    assert all(
        any(
            event.get("kind") == "coordination" and event.get("data") == "solo"
            for event in context["known_events"]["events"]
        )
        for context in wolf_night_contexts
    )
    seer_day_contexts = [
        context for context in day_contexts if context["self"]["identity"]["role_key"] == "seer"
    ]
    if not seer_day_contexts:
        with session_factory() as db:
            failures = [
                event.payload
                for event in db.scalars(
                    select(V2GameRecordEvent).where(
                        V2GameRecordEvent.game_id == identifiers["game_id"],
                        V2GameRecordEvent.event_type == "action_failed",
                    )
                )
            ]
        pytest.fail(f"seer never reached a day action; failures={failures!r}")
    assert any(
        event.get("kind") == "investigation_alignment"
        for context in seer_day_contexts
        for event in context["known_events"]["events"]
    )
    committed_investigations = [
        (context, event)
        for context in seer_day_contexts
        for event in context["known_events"]["events"]
        if event.get("kind") == "private_ability_action_committed"
        and event.get("data", {}).get("ability_id") == "seer.investigate"
    ]
    assert committed_investigations
    assert all(
        "last_committed_action" not in ability
        for context in seer_day_contexts
        for ability in context["self"]["ability_runtime_state"]["abilities"]
    )
    invalid_investigations = [
        {
            "task_at_seq": context["task"]["at_seq"],
            "event": event,
        }
        for context, event in committed_investigations
        if not (
            event["visibility"] == "actor_private"
            and event["authority"] == "judge_fact"
            and event["known_at_seq"] < context["task"]["at_seq"]
            and event["occurred_in"].get("period") == "night"
            and event["occurred_in"].get("round_no", 0) > 0
            and "decision_note" not in event["data"]["decision"]
            and event["data"]["declared_reason"]["epistemic_status"] == "actor_declared_reason"
        )
    ]
    assert not invalid_investigations, invalid_investigations
    with session_factory() as db:
        committed_wolf_facts = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == identifiers["game_id"],
                    V2KnowledgeFact.fact_type == "private_ability_action_committed",
                )
            )
        )
        assert any(
            fact.payload.get("ability_id") == "werewolf.attack"
            and fact.payload.get("decision", {}).get("decision_stage") == "team_resolution"
            for fact in committed_wolf_facts
        )
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        model_request_events = [
            event for event in events if event.event_type == "model_request_started"
        ]
        assert model_request_events
        assert all(
            event.payload["prompt_schema_version"] == 9
            and event.payload["model_context_schema_version"] == 9
            and event.payload["prompt_template_version"] == 2
            and event.payload["model_view_selector_version"] == 1
            and event.payload["prompt_projection"]["known_events_schema_version"] == 3
            and "known_event_count" in event.payload["prompt_projection"]
            and "known_event_total_count" in event.payload["prompt_projection"]
            and "known_event_record_seq_min" in event.payload["prompt_projection"]
            and "known_event_record_seq_max" in event.payload["prompt_projection"]
            and event.payload["prompt_projection"]["ledger_schema_version"] == 3
            and event.payload["prompt_projection"]["model_view_schema_version"] == 3
            and event.payload["prompt_projection"]["model_view_selector_version"] == 1
            and "current_round_statement_count" in event.payload["prompt_projection"]
            and "open_question_count" in event.payload["prompt_projection"]
            and "question_count" in event.payload["prompt_projection"]
            and "relation_count" in event.payload["prompt_projection"]
            and event.payload["prompt_projection"]["dropped_question_count"] == 0
            and event.payload["prompt_projection"]["dropped_relation_count"] == 0
            and event.payload["prompt_projection"]["dropped_event_count"] == 0
            and "selection_budget_chars" not in event.payload["prompt_projection"]
            and "retained_event_refs" not in event.payload["prompt_projection"]
            and "dropped_event_refs" not in event.payload["prompt_projection"]
            and "retention_reasons" not in event.payload["prompt_projection"]
            and "section_char_counts" in event.payload["prompt_projection"]
            for event in model_request_events
        )
        observed_responses = [
            event
            for event in events
            if event.event_type == "model_response_received"
            and contradictory_speech in str(event.payload.get("raw_response") or "")
        ]
        assert observed_responses
        observed_action_ids = {event.payload["action_id"] for event in observed_responses}
        assert all(
            event.payload["passive_observations"][0]["code"] == "wolf_cardinality_contradiction"
            and event.payload["passive_observations"][0]["effect"] == "observed_only"
            for event in observed_responses
        )
        assert all(
            sum(
                event.event_type == "model_request_started"
                and event.payload.get("action_id") == action_id
                for event in events
            )
            == 1
            and sum(
                event.event_type == "model_response_received"
                and event.payload.get("action_id") == action_id
                for event in events
            )
            == 1
            for action_id in observed_action_ids
        )
        adopted_presentations = list(
            db.scalars(
                select(V2LivePresentation).where(
                    V2LivePresentation.game_id == identifiers["game_id"],
                    V2LivePresentation.action_id.in_(observed_action_ids),
                )
            )
        )
        assert {
            presentation.action_id for presentation in adopted_presentations
        } == observed_action_ids
        assert all(
            presentation.subtitle_text == contradictory_speech
            for presentation in adopted_presentations
        )
        length_normalized_action_ids = {
            event.payload["action_id"]
            for event in events
            if event.event_type == "model_decision_speech_normalized"
            and event.payload.get("reason") == "speech_constraint"
            and event.payload.get("constraints") == ["max_chars_exceeded"]
        }
        assert observed_action_ids.isdisjoint(length_normalized_action_ids)
        note_normalizations = [
            event for event in events if event.event_type == "model_decision_note_normalized"
        ]
        assert note_normalizations
        assert all(
            event.payload["constraints"] == ["max_chars_exceeded"]
            and event.payload["original_chars"] == 130
            and event.payload["normalized_chars"] == 80
            for event in note_normalizations
        )
        guard_responses = [
            event
            for event in events
            if event.event_type == "model_response_received"
            and "守" * 130 in str(event.payload.get("raw_response") or "")
        ]
        assert guard_responses
        assert all(
            event.payload["parsed_output"]["decision_note"] == "守" * 80
            for event in guard_responses
        )


def test_advanced_rule_runs_pre_dawn_election_private_abilities_and_terminal_cutoff(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.decline_action_types.add("ability_witch.heal_decision")
    model_client.decline_action_types.add("werewolf_self_explosion")
    model_client.unexpected_speech_target = "model-added-irrelevant-target"
    model_client.force_speech_action_types.update({"ability_witch.heal_decision", "exile_vote"})
    request = _advanced_create_request()
    request["lobby_snapshot"]["rule_set"]["werewolf_self_explosion_enabled"] = True
    created = client.post("/api/v2/games", json=request)
    assert created.status_code == 201, created.text
    identifiers = created.json()

    public_types: list[str] = []
    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            public_types.append(value["type"])
            if value.get("live_state") in {"awaiting_observation", "failed"}:
                break

    assert "ability.progress_changed" not in public_types
    assert "god_view.night_resolved" not in public_types
    campaign_contexts = [
        context
        for context in model_client.decision_contexts
        if context["task"]["type"] == "sheriff_campaign_speech"
    ]
    assert campaign_contexts
    assert all(context["task"]["goal"] == "发表警长竞选发言。" for context in campaign_contexts)
    debate_contexts = [
        context
        for context in model_client.decision_contexts
        if context["task"]["type"] == "day_debate_speech"
    ]
    assert debate_contexts
    assert all(
        context["task"]["goal"] == "发表本轮白天讨论发言。"
        and "instruction" not in context["task"]["speech_progress"]
        and context["task"]["speech_progress"]["current_speaker_ref"]
        == context["self"]["identity"]["player_id"]
        for context in debate_contexts
    )
    speech_contexts = campaign_contexts + debate_contexts
    assert all(
        context["model_context_schema_version"] == 9
        and context["prompt_template_version"] == 2
        and context["known_events"]["schema_version"] == 3
        and "questions" in context["known_events"]
        and "relations" in context["known_events"]
        and "source_rules" not in context["known_events"]
        and context["response"]["speech"]
        == {
            "type": "string",
            "mode": "required",
            "min_length": 1,
            "max_chars": 300,
        }
        for context in speech_contexts
    )
    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None
        assert game.phase_id.startswith("day_")
        assert game.phase_state == "game_completed"
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "judge_speech_rendered",
                    V2GameRecordEvent.payload["template_id"].as_string()
                    == "judge_sheriff_election_opening",
                )
            )
            == 1
        )
        judge_speeches = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "judge_speech_rendered",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        dawn = next(
            item
            for item in judge_speeches
            if item.payload["template_id"] == "judge_dawn_announcement"
        )
        sheriff_opening = next(
            item
            for item in judge_speeches
            if item.payload["template_id"] == "judge_sheriff_election_opening"
        )
        discussion = next(
            item
            for item in judge_speeches
            if item.payload["template_id"] == "judge_public_discussion_opening"
        )
        assert all("进阶玩家" not in item.payload["text"] for item in judge_speeches)
        assert sheriff_opening.record_seq < dawn.record_seq
        assert dawn.record_seq < discussion.record_seq
        assert dawn.payload["action_id"] != discussion.payload["action_id"]
        assert "白天讨论现在开始" not in dawn.payload["text"]
        assert "平安夜" not in discussion.payload["text"]
        if "出局" in dawn.payload["text"]:
            assert "平安夜" not in dawn.payload["text"]
        sheriff_run_contexts = [
            context
            for context in model_client.decision_contexts
            if context["task"]["type"] == "sheriff_run"
        ]
        assert sheriff_run_contexts
        assert all(
            context["response"]["kind"] == "boolean"
            and context["response"]["field"] == "run_for_sheriff"
            and context["response"]["speech"]["mode"] == "forbidden"
            and context["response"]["decision_note"]
            == {"type": "string", "mode": "optional", "max_chars": 80}
            for context in sheriff_run_contexts
        )
        withdraw_contexts = [
            context
            for context in model_client.decision_contexts
            if context["task"]["type"] == "sheriff_withdraw"
        ]
        assert withdraw_contexts
        assert all(
            context["candidates"] == []
            and context["response"]
            == {
                "kind": "boolean",
                "presentation_kind": "sheriff_withdraw_decision",
                "language": "zh-CN",
                "speech": {
                    "type": "string",
                    "mode": "forbidden",
                },
                "decision_note": {
                    "type": "string",
                    "mode": "optional",
                    "max_chars": 80,
                },
                "field": "withdraw",
                "required_fields": ["withdraw"],
                "boolean": {
                    "type": "boolean",
                    "true_means": "退水",
                    "false_means": "不退水",
                },
            }
            for context in withdraw_contexts
        )
        withdraw_events = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "sheriff_withdraw_decided",
                )
            )
        )
        withdraw_responses = [
            event
            for event in db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "model_response_received",
                )
            )
            if isinstance(event.payload.get("parsed_output"), dict)
            and isinstance(event.payload["parsed_output"].get("withdraw"), bool)
        ]
        assert withdraw_events
        assert len(withdraw_responses) == len(withdraw_events)
        assert all(event.payload["withdrew"] is True for event in withdraw_events)
        assert all(
            event.payload["parsed_output"]["withdraw"] is True for event in withdraw_responses
        )
        self_explosion_responses = [
            event
            for event in db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "model_response_received",
                )
            )
            if isinstance(event.payload.get("parsed_output"), dict)
            and event.payload["parsed_output"].get("explode") is False
        ]
        assert self_explosion_responses
        silent_action_ids = {event.payload["action_id"] for event in self_explosion_responses}
        action_events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == game.game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        action_openings = [
            event
            for event in action_events
            if event.event_type == "action_opened"
            and isinstance(event.payload.get("context"), dict)
        ]
        vote_action_types = {
            "sheriff_vote",
            "sheriff_runoff_vote",
            "exile_vote",
            "exile_runoff_vote",
        }
        vote_openings = [
            event
            for event in action_openings
            if event.payload["context"].get("action_type") in vote_action_types
        ]
        assert vote_openings
        assert all(
            event.payload["context"]["output_contract"]["speech"]["mode"] == "forbidden"
            and event.payload["context"]["output_contract"]["presentation_kind"] == "private_vote"
            and event.payload["context"]["output_contract"]["decision_note"]
            == {"type": "string", "mode": "optional", "max_chars": 80}
            for event in vote_openings
        )
        vote_action_ids = {event.payload["context"]["action_id"] for event in vote_openings}
        assert all(
            not (
                event.event_type in {"speech_opened", "tts_stream_started"}
                and event.payload.get("action_id") in vote_action_ids
            )
            for event in action_events
        )
        forced_forbidden_action_ids = {
            event.payload["context"]["action_id"]
            for event in action_openings
            if event.payload["context"].get("action_type") in model_client.force_speech_action_types
        }
        assert forced_forbidden_action_ids
        assert forced_forbidden_action_ids <= {
            event.payload["action_id"]
            for event in action_events
            if event.event_type == "model_decision_speech_normalized"
            and event.payload.get("reason") == "speech_forbidden"
        }
        assert all(
            not (
                event.event_type in {"speech_opened", "tts_stream_started"}
                and event.payload.get("action_id") in forced_forbidden_action_ids
            )
            for event in action_events
        )
        committed_votes = [
            event for event in action_events if event.event_type == "day_vote_committed"
        ]
        assert committed_votes
        assert all("speech" not in event.payload for event in committed_votes)
        vote_context_batches: dict[tuple[str, str, int | None], list[dict[str, Any]]] = {}
        for context in model_client.decision_contexts:
            action_type = context["task"]["type"]
            if action_type not in vote_action_types:
                continue
            batch_key = (
                action_type,
                context["task"]["phase_id"],
                context["task"].get("vote_round"),
            )
            vote_context_batches.setdefault(batch_key, []).append(context)
        for contexts in vote_context_batches.values():
            if not contexts:
                continue
            visible_vote_ids = [
                tuple(
                    item["source_event_id"]
                    for item in context["known_events"]["events"]
                    if item["kind"] in {"day_vote", "vote_result"}
                )
                for context in contexts
            ]
            assert len(set(visible_vote_ids)) == 1

        night_window = db.scalar(
            select(V2ActionWindow).where(
                V2ActionWindow.game_id == game.game_id,
                V2ActionWindow.window_type == "night",
            )
        )
        assert night_window is not None
        direct_first_night_deaths = {item["player_id"] for item in night_window.result["deaths"]}
        first_night_last_words = [
            event
            for event in action_openings
            if event.payload["context"].get("action_type") == "first_night_last_words"
        ]
        assert {
            event.payload["context"]["actor"]["id"] for event in first_night_last_words
        } == direct_first_night_deaths
        first_night_last_word_seats = [
            next(
                item.seat
                for item in db.scalars(
                    select(V2PlayerState).where(V2PlayerState.game_id == game.game_id)
                )
                if item.player_id == event.payload["context"]["actor"]["id"]
            )
            for event in first_night_last_words
        ]
        assert first_night_last_word_seats == sorted(first_night_last_word_seats)
        sheriff_run_actor_ids = {
            event.payload["context"]["actor"]["id"]
            for event in action_openings
            if event.payload["context"].get("action_type") == "sheriff_run"
        }
        assert direct_first_night_deaths <= sheriff_run_actor_ids

        private_ability_action_ids = {
            event.payload["context"]["action_id"]
            for event in action_openings
            if str(event.payload["context"].get("action_type", "")).startswith("ability_")
            and event.payload["context"].get("action_type") != "ability_werewolf.attack_decision"
        }
        assert private_ability_action_ids
        assert all(
            not (
                event.event_type in {"speech_opened", "tts_stream_started"}
                and event.payload.get("action_id") in private_ability_action_ids
            )
            for event in action_events
        )
        witch_observations = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == game.game_id,
                    V2KnowledgeFact.fact_type == "witch_attack_observation",
                )
            )
        )
        assert witch_observations
        assert all(
            isinstance(item.payload.get("night_no"), int) and "attacked_player_id" in item.payload
            for item in witch_observations
        )
        private_action_decisions = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == game.game_id,
                    V2KnowledgeFact.fact_type == "private_action_decision",
                )
            )
        )
        assert private_action_decisions
        assert {item.payload["action_type"] for item in private_action_decisions} >= {
            "sheriff_run",
            "sheriff_withdraw",
            "werewolf_self_explosion",
            "exile_vote",
        }
        assert all(
            item.owner_scope == "player"
            and item.payload["declared_reason"]["epistemic_status"] == "actor_declared_reason"
            and item.payload["declared_reason"]["text"]
            for item in private_action_decisions
        )

        completion_events = [
            event for event in action_events if event.event_type == "game_completed"
        ]
        assert len(completion_events) == 1
        completion_seq = completion_events[0].record_seq
        terminal_openings = [
            event
            for event in action_openings
            if event.payload["context"].get("action_type") == "judge_game_completed"
        ]
        assert len(terminal_openings) == 1
        assert completion_seq < terminal_openings[0].record_seq
        assert all(
            event.payload["context"].get("action_type") == "judge_game_completed"
            for event in action_openings
            if event.record_seq > completion_seq
        )
        assert all(
            not (
                event.event_type in {"speech_opened", "tts_stream_started"}
                and event.payload.get("action_id") in silent_action_ids
            )
            for event in action_events
        )
        assert silent_action_ids <= {
            event.payload["action_id"]
            for event in action_events
            if event.event_type == "action_succeeded"
            and event.payload.get("result") == "decision_recorded_without_presentation"
        }
        self_explosion_contexts = [
            context
            for context in model_client.decision_contexts
            if context["task"]["type"] == "werewolf_self_explosion"
        ]
        assert self_explosion_contexts
        assert all(
            context["response"]["kind"] == "boolean"
            and context["response"]["field"] == "explode"
            and context["response"]["speech"]["mode"] == "forbidden"
            and context["response"]["decision_note"]
            == {"type": "string", "mode": "optional", "max_chars": 80}
            and context["task"]["mechanical_effect"]["target_mode"] == "none"
            and context["task"]["mechanical_effect"]["if_executed"]["actor_eliminated"] is True
            and context["task"]["mechanical_effect"]["if_executed"]["target_allowed"] is False
            and context["task"]["mechanical_effect"]["if_executed"]["other_players_affected"]
            is False
            and context["task"]["mechanical_effect"]["if_executed"]["other_players_eliminated"]
            is False
            and context["task"]["mechanical_effect"]["if_executed"]["remaining_day_flow"]
            == (
                "sheriff_election_interrupted"
                if context["task"]["public_stage"] == "pre_sheriff_election"
                else "terminated"
            )
            and context["task"]["goal"] == "决定是否立即自爆。"
            for context in self_explosion_contexts
        )
        ability_contexts = [
            context
            for context in model_client.decision_contexts
            if context["task"]["type"].startswith("ability_")
        ]
        assert ability_contexts
        assert all(context["response"]["kind"] == "target" for context in ability_contexts)
        blind_wolf_contexts = [
            context
            for context in ability_contexts
            if context["task"]["type"] == "ability_werewolf.attack_decision"
            and any(
                fact.get("fact_type") == "decision_stage"
                and fact.get("payload") == "preference_probe"
                for fact in _private_known_facts(context)
            )
        ]
        speaking_wolf_contexts = [
            context
            for context in ability_contexts
            if context["task"]["type"] == "ability_werewolf.attack_decision"
            and context not in blind_wolf_contexts
        ]
        non_wolf_ability_contexts = [
            context
            for context in ability_contexts
            if context["task"]["type"] != "ability_werewolf.attack_decision"
        ]
        assert blind_wolf_contexts
        assert all(
            context["response"]["speech"]["mode"] == "forbidden"
            and context["response"]["decision_note"]
            == {"type": "string", "mode": "optional", "max_chars": 80}
            for context in blind_wolf_contexts
        )
        assert all(
            context["response"]["speech"]["mode"] == "required"
            and context["response"]["speech"]["max_sentences"] == 1
            and "decision_note" not in context["response"]
            for context in speaking_wolf_contexts
        )
        assert all(
            context["response"]["speech"]["mode"] == "forbidden"
            and context["response"]["decision_note"]
            == {"type": "string", "mode": "optional", "max_chars": 80}
            for context in non_wolf_ability_contexts
        )
        instances = {
            item.ability_instance_id: item.ability_id
            for item in db.scalars(
                select(V2AbilityInstance).where(V2AbilityInstance.game_id == game.game_id)
            )
        }
        activations = list(
            db.scalars(
                select(V2AbilityActivation).where(V2AbilityActivation.game_id == game.game_id)
            )
        )
        heal = next(
            item for item in activations if instances[item.ability_instance_id] == "witch.heal"
        )
        poison = next(
            item for item in activations if instances[item.ability_instance_id] == "witch.poison"
        )
        assert heal.status == "completed"
        assert heal.decision["target_player_id"] is None
        assert poison.status == "completed"
        assert poison.decision["target_player_id"] is not None
        effects = list(
            db.scalars(select(V2EffectIntent).where(V2EffectIntent.game_id == game.game_id))
        )
        attack = next(item for item in effects if item.effect_type == "attack")
        poison_effect = next(item for item in effects if item.effect_type == "poison")
        assert poison_effect.target_player_id not in {
            poison_effect.actor_id,
            attack.target_player_id,
        }
        assert poison_effect.state == "resolved"
        normalized_targets = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == game.game_id,
                    V2GameRecordEvent.event_type == "model_decision_target_normalized",
                )
            )
        )
        assert any(
            event.payload["reason"] == "targetless_action"
            and event.payload["normalized_target_player_id"] is None
            for event in normalized_targets
        )
    assert all("influence" not in context for context in model_client.contexts)
    serialized_model_contexts = json.dumps(model_client.contexts, ensure_ascii=False)
    if "进阶玩家" in serialized_model_contexts:
        pytest.fail("player display name leaked into model context")
    if "advanced-player-" in serialized_model_contexts:
        leaked_value = next(
            value
            for context in model_client.contexts
            for value in _nested_strings(context)
            if "advanced-player-" in value
        )
        pytest.fail(f"internal player id leaked into model context: {leaked_value}")
    assert all(
        context["self"]["identity"]["player_id"].startswith("seat_")
        for context in model_client.contexts
    )
    assert all(
        candidate["player_id"].startswith("seat_")
        and candidate["display_name"] == f"{candidate['seat']}号"
        for context in model_client.contexts
        for candidate in context.get("candidates", [])
    )
    fact_contexts = [
        context
        for context in model_client.contexts
        if any(
            event.get("authority") == "judge_fact"
            for event in context.get("known_events", {}).get("events", [])
        )
    ]
    assert fact_contexts
    assert all(
        "public_history" not in context
        and "judge_facts" not in context.get("state", {})
        and "latest_vote_snapshot" not in context.get("state", {})
        for context in fact_contexts
    )


def test_terminal_tts_failure_does_not_rollback_completed_match(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    tts_client = client.app.state.v2_test_tts_client
    tts_client.failure_text_fragments.add("本局结束")
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()

    observed_live_states: list[str] = []
    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if isinstance(value.get("live_state"), str):
                observed_live_states.append(value["live_state"])
            if value.get("live_state") in {"awaiting_observation", "failed"}:
                break

    assert observed_live_states[-1] == "awaiting_observation"
    assert "failed" not in observed_live_states
    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        assert game is not None and run is not None
        assert game.status == run.status == "awaiting_observation"
        assert game.phase_state == "game_completed"
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == game.game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        completion = [event for event in events if event.event_type == "game_completed"]
        terminal_openings = [
            event
            for event in events
            if event.event_type == "action_opened"
            and event.payload.get("context", {}).get("action_type") == "judge_game_completed"
        ]
        assert len(completion) == len(terminal_openings) == 1
        assert completion[0].record_seq < terminal_openings[0].record_seq
        terminal_action_id = terminal_openings[0].payload["context"]["action_id"]
        assert any(
            event.event_type == "action_failed"
            and event.payload.get("action_id") == terminal_action_id
            for event in events
        )
        assert not any(
            event.event_type in {"night_runtime_failed", "day_runtime_failed"} for event in events
        )


def test_retryable_model_transport_failure_recovers_same_action(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.retryable_transport_failures_remaining = 1
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()

    terminal_state = None
    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while terminal_state is None:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") in {"awaiting_observation", "failed"}:
                terminal_state = value["live_state"]

    assert terminal_state == "awaiting_observation"
    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        retry = next(event for event in events if event.event_type == "model_retry_scheduled")
        action_id = retry.payload["action_id"]
        starts = [
            event
            for event in events
            if event.event_type == "model_request_started"
            and event.payload.get("action_id") == action_id
        ]
        failures = [
            event
            for event in events
            if event.event_type == "model_request_failed"
            and event.payload.get("action_id") == action_id
        ]
        responses = [
            event
            for event in events
            if event.event_type == "model_response_received"
            and event.payload.get("action_id") == action_id
        ]
        assert len(starts) == 2
        assert starts[0].payload["attempt_no"] == 1
        assert starts[1].payload["attempt_no"] == 2
        assert starts[1].payload["retry_of_attempt_id"] == starts[0].payload["attempt_id"]
        assert starts[0].payload["request_payload"] == starts[1].payload["request_payload"]
        assert retry.payload["attempt_id"] == starts[0].payload["attempt_id"]
        assert retry.payload["next_attempt_id"] == starts[1].payload["attempt_id"]
        assert len(failures) == 1
        expected_failure = {
            "action_id": action_id,
            "attempt_id": starts[0].payload["attempt_id"],
            "attempt_no": 1,
            "max_attempts": 2,
            "failure_kind": "model",
            "failure_code": "model_transport_failed",
            "retryable": True,
            "terminal": False,
            "failure_stage": "connect",
            "exception_type": "builtins.ConnectionResetError",
            "errno": 54,
            "first_token_seen": False,
            "elapsed_ms": 5,
        }
        assert {key: failures[0].payload[key] for key in expected_failure} == expected_failure
        assert failures[0].payload["attempt_budget_ms"] == 5000
        assert failures[0].payload["action_budget_ms"] == 5000
        assert failures[0].payload["action_elapsed_ms"] >= 0
        assert failures[0].payload["action_remaining_ms"] > 0
        assert failures[0].payload["response_headers_seen"] is False
        assert len(responses) == 1
        assert responses[0].payload["attempt_id"] == starts[1].payload["attempt_id"]
        assert any(
            event.event_type == "action_succeeded" and event.payload.get("action_id") == action_id
            for event in events
        )
        assert not any(
            event.event_type == "action_failed" and event.payload.get("action_id") == action_id
            for event in events
        )

    assert client.post("/api/v1/admin/dev-login").status_code == 200
    detail = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert detail.status_code == 200, detail.text
    request_page = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/model-requests"
        "?after_record_seq=0&page_size=500"
    )
    assert request_page.status_code == 200, request_page.text
    boundary_page = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/model-requests"
        "?after_record_seq=0&page_size=1"
    )
    assert boundary_page.status_code == 200, boundary_page.text
    boundary_items = boundary_page.json()["items"]
    assert boundary_items
    boundary_action_id = boundary_items[0]["action_id"]
    assert {item["attempt_id"] for item in boundary_items} == {
        item["attempt_id"]
        for item in request_page.json()["items"]
        if item["action_id"] == boundary_action_id
    }
    requests = [
        request for request in request_page.json()["items"] if request["action_id"] == action_id
    ]
    assert [request["status"] for request in requests] == ["failed", "succeeded"]
    assert all("request_payload" not in request for request in requests)
    assert all("raw_response" not in request for request in requests)
    assert requests[0]["terminal"] is False
    assert requests[0]["retryable"] is True
    assert requests[0]["exception_type"] == "builtins.ConnectionResetError"
    assert requests[1]["retry_of_attempt_id"] == requests[0]["attempt_id"]
    request_detail = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/model-requests/"
        f"{requests[0]['attempt_id']}"
    )
    assert request_detail.status_code == 200, request_detail.text
    assert request_detail.json()["request_payload"]

    event_page = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/events?after_record_seq=0&page_size=500"
    )
    assert event_page.status_code == 200, event_page.text
    started_event = next(
        event
        for event in event_page.json()["items"]
        if event["event_type"] == "model_request_started"
        and event["payload"].get("attempt_id") == requests[0]["attempt_id"]
    )
    assert "request_payload" not in started_event["payload"]
    event_detail = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/events/{started_event['event_id']}"
    )
    assert event_detail.status_code == 200, event_detail.text
    assert event_detail.json()["payload"]["request_payload"]


def test_duplicate_json_repair_and_public_causality_observation_do_not_retry(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.duplicate_json_action_types.add("day_debate_speech")
    for seat in range(1, 7):
        clauses = [f"{seat}号发言。"]
        if seat > 1:
            clauses.append(f"我昨晚验了{seat - 1}号，查杀。")
        if seat < 6:
            clauses.append(f"我先猛打{seat + 1}号。")
        if seat > 2:
            clauses.append(f"{seat - 2}号先猛打{seat - 1}号，这个顺序太像被查杀后的应激。")
        model_client.speech_by_actor_and_action_type[(f"seat_{seat}", "day_debate_speech")] = (
            "".join(clauses)
        )
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()

    public_committed_texts: list[str] = []
    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        _collect_until_observation(
            websocket,
            message_types=[],
            committed_texts=public_committed_texts,
        )

    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        repair_events = [
            event
            for event in events
            if event.event_type == "model_response_repair_applied"
            and event.payload.get("repair_kind") == "duplicate_identical_json_ignored"
        ]
        assert repair_events
        repaired_action_ids = {event.payload["action_id"] for event in repair_events}
        repaired_actions = [
            event
            for event in events
            if event.event_type == "action_opened"
            and event.payload.get("action_id") in repaired_action_ids
        ]
        repaired_requests = [
            event
            for event in events
            if event.event_type == "model_request_started"
            and event.payload.get("action_id") in repaired_action_ids
        ]
        repaired_responses = [
            event
            for event in events
            if event.event_type == "model_response_received"
            and event.payload.get("action_id") in repaired_action_ids
        ]
        assert {event.payload["action_id"] for event in repaired_requests} == (repaired_action_ids)
        assert {event.payload["action_id"] for event in repaired_responses} == (repaired_action_ids)
        assert {event.payload["action_id"] for event in repaired_actions} == (repaired_action_ids)
        assert all(
            event.payload["audience"] == "player_private"
            and event.payload["audience_contract_version"] == 1
            and event.payload["context"]["self_identity"]["role_key"]
            for event in repaired_actions
        )
        assert all(
            event.payload["audience"] == "player_private"
            and event.payload["audience_contract_version"] == 1
            and bool(event.payload["request_payload"])
            for event in repaired_requests
        )
        assert all(
            event.payload["repair_kind"] == "duplicate_identical_json_ignored"
            and "```json" in event.payload["raw_response"]
            and "decision_note" in event.payload["parsed_output"]
            and event.payload["audience"] == "player_private"
            and event.payload["audience_contract_version"] == 1
            for event in repaired_responses
        )
        assert all(
            event.payload["audience"] == "player_private"
            and event.payload["audience_contract_version"] == 1
            for event in repair_events
        )
        for action_id in repaired_action_ids:
            assert (
                sum(
                    event.event_type == "model_request_started"
                    and event.payload.get("action_id") == action_id
                    for event in events
                )
                == 1
            )
            assert not any(
                event.event_type in {"model_request_failed", "model_retry_scheduled"}
                and event.payload.get("action_id") == action_id
                for event in events
            )

        repaired_presentations = list(
            db.scalars(
                select(V2LivePresentation).where(
                    V2LivePresentation.game_id == identifiers["game_id"],
                    V2LivePresentation.action_id.in_(repaired_action_ids),
                )
            )
        )
        assert {item.action_id for item in repaired_presentations} == repaired_action_ids
        assert all(item.audience == "all" for item in repaired_presentations)
        assert all(
            event.payload["parsed_output"]["speech"] in public_committed_texts
            for event in repaired_responses
        )

        causality_responses = [
            event
            for event in events
            if event.event_type == "model_response_received"
            and any(
                observation.get("code") == "public_event_causality_contradiction"
                for observation in event.payload.get("passive_observations", [])
            )
        ]
        assert causality_responses
        causality_action_ids = {event.payload["action_id"] for event in causality_responses}
        assert all(
            any(
                observation.get("code") == "public_event_causality_contradiction"
                and observation.get("effect") == "observed_only"
                for observation in event.payload["passive_observations"]
            )
            for event in causality_responses
        )
        assert all(
            sum(
                event.event_type == "model_request_started"
                and event.payload.get("action_id") == action_id
                for event in events
            )
            == 1
            and not any(
                event.event_type in {"model_request_failed", "model_retry_scheduled"}
                and event.payload.get("action_id") == action_id
                for event in events
            )
            for action_id in causality_action_ids
        )
        presentations = list(
            db.scalars(
                select(V2LivePresentation).where(
                    V2LivePresentation.game_id == identifiers["game_id"],
                    V2LivePresentation.action_id.in_(causality_action_ids),
                )
            )
        )
        assert {item.action_id for item in presentations} == causality_action_ids
        parsed_speech_by_action = {
            event.payload["action_id"]: event.payload["parsed_output"]["speech"]
            for event in causality_responses
        }
        assert all(
            item.subtitle_text == parsed_speech_by_action[item.action_id] for item in presentations
        )


def test_tts_disabled_match_uses_text_only_presentations(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    external_tts = client.app.state.v2_test_tts_client
    request = _six_player_create_request()
    request["audio_mode"] = "text_only"
    identifiers = client.post("/api/v2/games", json=request).json()
    assert identifiers["audio_mode"] == "text_only"

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "awaiting_observation":
                break

    assert external_tts.call_count == 0
    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None and game.status == "awaiting_observation"
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2VoiceAsset)
                .where(V2VoiceAsset.game_id == identifiers["game_id"])
            )
            == 0
        )
        presentations = list(
            db.scalars(
                select(V2LivePresentation).where(
                    V2LivePresentation.game_id == identifiers["game_id"]
                )
            )
        )
        assert presentations
        assert all(item.state == "closed" and item.voice_asset_id is None for item in presentations)
        event_types = list(
            db.scalars(
                select(V2GameRecordEvent.event_type).where(
                    V2GameRecordEvent.game_id == identifiers["game_id"]
                )
            )
        )
        assert "tts_skipped" in event_types
        assert "tts_stream_started" not in event_types
        skipped = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "tts_skipped",
                )
            )
        )
        assert skipped
        assert all(item.payload.get("configured_audio_mode") == "text_only" for item in skipped)


def test_one_runtime_routes_text_only_without_constructing_its_lazy_tts_client(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    original_runtime = client.app.state.v2_live_runtime
    constructed: list[FakeV2TtsClient] = []

    def tts_factory() -> FakeV2TtsClient:
        client = FakeV2TtsClient()
        constructed.append(client)
        return client

    runtime = V2LiveRuntime(
        session_factory=session_factory,
        model_client=client.app.state.v2_test_model_client,
        tts_client=None,
        tts_client_factory=tts_factory,
        tts_capability_enabled=True,
        voice_root=voice_root,
        sample_rate=24000,
        judge_configuration_provider=(
            original_runtime._action_engine._judge_configuration_provider
        ),
    )
    text_claim = V2ActionClaim(
        game_id="v2_game_textonly0001",
        run_id="v2_run_textonly0001",
        action_id="v2_action_textonly01",
        phase_id="opening",
        audience="all",
        audio_mode="text_only",
    )
    tts_claim = V2ActionClaim(
        game_id="v2_game_ttsmode00001",
        run_id="v2_run_ttsmode00001",
        action_id="v2_action_ttsmode001",
        phase_id="opening",
        audience="all",
        audio_mode="tts",
    )

    assert runtime._action_engine._tts_client_for_claim(text_claim) is None
    assert constructed == []
    resolved = runtime._action_engine._tts_client_for_claim(tts_claim)
    assert resolved is constructed[0]
    assert len(constructed) == 1
    assert runtime._action_engine._tts_client_for_claim(text_claim) is None
    assert len(constructed) == 1


def test_public_speech_format_exhaustion_is_audited_and_skipped(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.quality_failure_action_types.add("day_debate_speech")
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "awaiting_observation":
                break

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None and game.status == "awaiting_observation"
        events = list(
            db.scalars(
                select(V2GameRecordEvent).where(V2GameRecordEvent.game_id == identifiers["game_id"])
            )
        )
        skipped = [
            event
            for event in events
            if event.event_type == "action_skipped_technical"
            and event.payload.get("action_type") == "day_debate_speech"
        ]
        assert skipped
        skipped_action_ids = {event.payload["action_id"] for event in skipped}
        assert skipped_action_ids <= {
            event.payload["action_id"] for event in events if event.event_type == "action_succeeded"
        }
        assert not any(event.event_type == "day_runtime_failed" for event in events)


def test_optional_boolean_format_exhaustion_uses_false_fallback(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.quality_failure_action_types.add("werewolf_self_explosion")
    request = _advanced_create_request()
    request["lobby_snapshot"]["rule_set"]["werewolf_self_explosion_enabled"] = True
    identifiers = client.post("/api/v2/games", json=request).json()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "awaiting_observation":
                break

    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent).where(V2GameRecordEvent.game_id == identifiers["game_id"])
            )
        )
        fallbacks = [
            event
            for event in events
            if event.event_type == "technical_fallback_applied"
            and event.payload.get("action_type") == "werewolf_self_explosion"
        ]
        assert fallbacks
        assert not any(event.event_type == "werewolf_self_exploded" for event in events)


def test_required_vote_batch_pauses_without_random_vote_and_resumes(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.decline_action_types.add("exile_vote")
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-retry-required-vote-batch",
    )

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "paused_model_error":
                break

        with session_factory() as db:
            recovery = db.scalar(
                select(V2ModelActionRecovery).where(
                    V2ModelActionRecovery.game_id == identifiers["game_id"],
                    V2ModelActionRecovery.state == "paused",
                )
            )
            assert recovery is not None
            assert recovery.action_type == "exile_vote"
            assert recovery.failure_code == "model_decision_required_target_missing"
            assert recovery.action_snapshot["context"]["vote_batch_stage"] == "sequential_recovery"
            recovery_action_id = recovery.action_id
            batch_recovery_started = db.scalar(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "day_vote_batch_recovery_started",
                )
                .order_by(V2GameRecordEvent.record_seq.desc())
            )
            assert batch_recovery_started is not None
            batch_id = batch_recovery_started.payload["batch_id"]
            failed_voter_ids = batch_recovery_started.payload["failed_voter_ids"]
            assert recovery.actor_id in failed_voter_ids
            concurrent_recovery_completed = db.scalar(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "day_vote_batch_concurrent_recovery_completed",
                )
                .order_by(V2GameRecordEvent.record_seq.desc())
            )
            assert concurrent_recovery_completed is not None
            assert concurrent_recovery_completed.payload["batch_id"] == batch_id
            assert concurrent_recovery_completed.payload["recovered_voter_ids"] == []
            assert concurrent_recovery_completed.payload["still_failed_voter_ids"] == (
                failed_voter_ids
            )
            assert not any(
                event.event_type == "day_vote_committed"
                and event.payload.get("action_type") == "exile_vote"
                and event.payload.get("batch_id") == batch_id
                for event in db.scalars(
                    select(V2GameRecordEvent).where(
                        V2GameRecordEvent.game_id == identifiers["game_id"]
                    )
                )
            )

        model_client.decline_action_types.discard("exile_vote")
        retried = client.post(
            f"/api/v1/admin/v2/games/{identifiers['game_id']}/retry-model-action",
            json={"reason": "恢复同一冻结投票批次"},
            headers=headers,
        )
        assert retried.status_code == 202, retried.text
        assert retried.json()["action_id"] == recovery_action_id

        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            terminal_live_state = json.loads(message["text"]).get("live_state")
            if terminal_live_state in {"awaiting_observation", "failed"}:
                break
        assert terminal_live_state == "awaiting_observation"

    with session_factory() as db:
        recovery = db.get(V2ModelActionRecovery, recovery_action_id)
        assert recovery is not None and recovery.state == "resolved"
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    batch_recovery_completed = next(
        event
        for event in events
        if event.event_type == "day_vote_batch_recovery_completed"
        and event.payload.get("batch_id") == batch_id
    )
    concurrent_recovery_completed = next(
        event
        for event in events
        if event.event_type == "day_vote_batch_concurrent_recovery_completed"
        and event.payload.get("batch_id") == batch_id
    )
    committed = [
        event
        for event in events
        if event.event_type == "day_vote_committed" and event.payload.get("batch_id") == batch_id
    ]
    assert {event.payload["voter_player_id"] for event in committed} == set(failed_voter_ids)
    assert concurrent_recovery_completed.record_seq < batch_recovery_completed.record_seq
    assert batch_recovery_completed.record_seq < min(event.record_seq for event in committed)


def test_operator_stop_cancels_model_retry_backoff(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    runtime = client.app.state.v2_live_runtime
    runtime._action_engine._model_retry_policy = V2ModelRetryPolicy(
        max_attempts=2,
        attempt_total_seconds=5,
        action_total_seconds=5,
        base_delay_seconds=2,
        jitter_seconds=0,
    )
    model_client = client.app.state.v2_test_model_client
    model_client.retryable_transport_failures_remaining = 1
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-stop-model-retry-backoff",
    )

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        assert model_client.transport_failure.wait(5)

        stopped = client.post(
            f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
            json={"reason": "模型代理链异常，人工停止重试"},
            headers=headers,
        )
        assert stopped.status_code == 202, stopped.text
        assert stopped.json()["run_status"] == "canceled"

        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") == "canceled":
                break

    assert len(model_client.attempt_ids) == 2
    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert sum(event.event_type == "model_request_started" for event in events) == 2
        assert sum(event.event_type == "model_retry_scheduled" for event in events) == 1
        assert "game_canceled" in {event.event_type for event in events}
        assert "action_failed" not in {event.event_type for event in events}


def test_model_retry_receives_a_separate_attempt_budget(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    runtime = client.app.state.v2_live_runtime
    runtime._action_engine._model_retry_policy = V2ModelRetryPolicy(
        max_attempts=2,
        attempt_total_seconds=0.25,
        action_total_seconds=0.6,
        base_delay_seconds=0,
        jitter_seconds=0,
    )
    model_client = client.app.state.v2_test_model_client
    model_client.retryable_transport_failures_remaining = 1
    model_client.call_delay_seconds = 0.15
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()

    terminal_state = None
    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while terminal_state is None:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") in {"awaiting_observation", "failed"}:
                terminal_state = value["live_state"]

    assert terminal_state == "awaiting_observation"
    with session_factory() as db:
        failures = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "model_request_failed",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert len(failures) == 1
        action_id = failures[0].payload["action_id"]
        starts = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "model_request_started",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert sum(event.payload.get("action_id") == action_id for event in starts) == 2
        assert failures[0].payload["terminal"] is False
        assert failures[0].payload["attempt_budget_ms"] == 250
        assert failures[0].payload["action_budget_ms"] == 600
        assert failures[0].payload["action_remaining_ms"] > 0
        game = db.get(V2GameRecord, identifiers["game_id"])
        assert game is not None and game.status == "awaiting_observation"


def test_attempt_budget_timeout_is_retryable_within_action_budget(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    runtime = client.app.state.v2_live_runtime
    runtime._action_engine._model_retry_policy = V2ModelRetryPolicy(
        max_attempts=2,
        attempt_total_seconds=0.05,
        action_total_seconds=0.2,
        base_delay_seconds=0,
        jitter_seconds=0,
    )
    model_client = client.app.state.v2_test_model_client
    model_client.call_delays_seconds = [0.08, 0]
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "awaiting_observation":
                break

    with session_factory() as db:
        failure = db.scalar(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == identifiers["game_id"],
                V2GameRecordEvent.event_type == "model_request_failed",
            )
            .order_by(V2GameRecordEvent.record_seq)
        )
        assert failure is not None
        assert failure.payload["failure_code"] == "model_total_timeout"
        assert failure.payload["failure_stage"] == "attempt_budget"
        assert failure.payload["retryable"] is True
        assert failure.payload["terminal"] is False
        action_id = failure.payload["action_id"]
        attempts = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == identifiers["game_id"],
                    V2GameRecordEvent.event_type == "model_request_started",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert sum(event.payload.get("action_id") == action_id for event in attempts) == 2


@pytest.mark.parametrize(
    ("first_attempt_progress", "expected_stage", "headers_seen"),
    [
        ((), "response_headers", False),
        (
            (
                V2ModelProgress(
                    stage="response_headers",
                    provider_request_id="provider-headers-only",
                    elapsed_ms=3,
                    response_headers={"x-request-id": "provider-headers-only"},
                ),
            ),
            "first_token",
            True,
        ),
    ],
)
def test_progress_capability_preserves_pre_token_outer_timeout_stage(
    v2_context,
    first_attempt_progress: tuple[V2ModelProgress, ...],
    expected_stage: str,
    headers_seen: bool,
) -> None:
    client, session_factory, _voice_root = v2_context
    runtime = client.app.state.v2_live_runtime
    runtime._action_engine._model_retry_policy = V2ModelRetryPolicy(
        max_attempts=2,
        attempt_total_seconds=0.05,
        action_total_seconds=0.2,
        base_delay_seconds=0,
        jitter_seconds=0,
    )
    runtime._action_engine._model_client = _ProgressThenSlowModelClient(
        first_attempt_progress=first_attempt_progress
    )
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "awaiting_observation":
                break

    with session_factory() as db:
        failure = db.scalar(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == identifiers["game_id"],
                V2GameRecordEvent.event_type == "model_request_failed",
            )
            .order_by(V2GameRecordEvent.record_seq)
        )
        assert failure is not None
        assert failure.payload["failure_stage"] == expected_stage
        assert failure.payload["timeout_scope"] == "attempt_budget"
        assert failure.payload["response_headers_seen"] is headers_seen
        assert failure.payload["first_token_seen"] is False


def test_progress_aware_outer_timeout_preserves_real_stream_stage_and_admin_fields(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    runtime = client.app.state.v2_live_runtime
    runtime._action_engine._model_retry_policy = V2ModelRetryPolicy(
        max_attempts=2,
        attempt_total_seconds=0.05,
        action_total_seconds=0.2,
        base_delay_seconds=0,
        jitter_seconds=0,
    )
    model_client = _ProgressThenSlowModelClient()
    runtime._action_engine._model_client = model_client
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "awaiting_observation":
                break

    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        failure = next(event for event in events if event.event_type == "model_request_failed")
        attempt_id = failure.payload["attempt_id"]
        attempt_events = [
            event for event in events if event.payload.get("attempt_id") == attempt_id
        ]
        event_types = [event.event_type for event in attempt_events]
        assert event_types.index("model_response_headers_received") < event_types.index(
            "model_first_token_received"
        )
        assert event_types.index("model_first_token_received") < event_types.index(
            "model_first_text_delta_received"
        )
        assert event_types.index("model_first_text_delta_received") < event_types.index(
            "model_request_failed"
        )
        assert failure.payload["failure_stage"] == "stream"
        assert failure.payload["timeout_scope"] == "attempt_budget"
        assert failure.payload["provider_request_id"] == "provider-stream-progress"
        assert failure.payload["response_headers_seen"] is True
        assert failure.payload["response_headers"] == {
            "x-request-id": "provider-header-progress",
            "x-ratelimit-remaining-requests": "9",
        }
        assert failure.payload["first_token_seen"] is True
        assert failure.payload["first_token_ms"] == 7
        assert failure.payload["first_token_kind"] == "reasoning"
        assert failure.payload["first_visible_text_ms"] == 9
        starts = [
            event
            for event in events
            if event.event_type == "model_request_started"
            and event.payload.get("action_id") == failure.payload["action_id"]
        ]
        assert len(starts) == 2
        first_tokens_by_attempt = {
            item.payload["attempt_id"]: [
                event
                for event in events
                if event.event_type == "model_first_token_received"
                and event.payload.get("attempt_id") == item.payload["attempt_id"]
            ]
            for item in starts
        }
        assert all(len(rows) == 1 for rows in first_tokens_by_attempt.values())
        assert (
            first_tokens_by_attempt[starts[1].payload["attempt_id"]][0].payload[
                "observation_source"
            ]
            == "decision_result_fallback"
        )

    assert client.post("/api/v1/admin/dev-login").status_code == 200
    request_page = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/model-requests"
        "?after_record_seq=0&page_size=500"
    )
    assert request_page.status_code == 200, request_page.text
    failed_attempt = next(
        item for item in request_page.json()["items"] if item["attempt_id"] == attempt_id
    )
    assert failed_attempt["provider_request_id"] == "provider-stream-progress"
    assert failed_attempt["response_headers"] == {
        "x-request-id": "provider-header-progress",
        "x-ratelimit-remaining-requests": "9",
    }
    assert failed_attempt["first_token_kind"] == "reasoning"
    assert failed_attempt["first_visible_text_ms"] == 9
    assert failed_attempt["failure_stage"] == "stream"
    assert failed_attempt["timeout_scope"] == "attempt_budget"


def test_admin_retries_the_same_paused_model_action(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.split_werewolf_preferences = True
    model_client.retryable_transport_failures_by_stage["sequential_final_vote"] = 2
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-retry-paused-model-action",
    )
    reason = "模型链路恢复，继续同一冻结动作"

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") == "paused_model_error":
                break

        with session_factory.begin() as db:
            game = db.get(V2GameRecord, identifiers["game_id"])
            run = db.get(V2GameRun, identifiers["run_id"])
            assert game is not None and game.status == "paused_model_error"
            assert run is not None and run.status == "paused_model_error"
            paused_events = list(
                db.scalars(
                    select(V2GameRecordEvent)
                    .where(
                        V2GameRecordEvent.game_id == identifiers["game_id"],
                        V2GameRecordEvent.event_type == "model_action_paused",
                    )
                    .order_by(V2GameRecordEvent.record_seq)
                )
            )
            assert len(paused_events) == 1
            action_id = paused_events[0].payload["action_id"]
            legacy_payload = dict(paused_events[0].payload)
            legacy_payload.pop("audience", None)
            legacy_payload.pop("audience_contract_version", None)
            paused_events[0].payload = legacy_payload

        retried = client.post(
            f"/api/v1/admin/v2/games/{identifiers['game_id']}/retry-model-action",
            json={"reason": reason},
            headers=headers,
        )
        assert retried.status_code == 202, retried.text
        assert retried.json()["action"] == "retry_model_action"
        assert retried.json()["action_id"] == action_id
        assert retried.json()["replayed"] is False
        assert retried.json()["run_status"] != "paused_model_error"

        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") == "awaiting_observation":
                break

    replayed = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/retry-model-action",
        json={"reason": reason},
        headers=headers,
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True
    assert replayed.json()["action_id"] == action_id

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        assert game is not None and game.status == "awaiting_observation"
        assert run is not None and run.status == "awaiting_observation"
        recovery = db.get(V2ModelActionRecovery, action_id)
        assert recovery is not None
        assert recovery.state == "resolved"
        assert recovery.request_hash
        assert recovery.request_payload
        assert recovery.model_context
        assert recovery.action_snapshot["action_type"]
        assert recovery.resolved_attempt_id is not None
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        action_events = [event for event in events if event.payload.get("action_id") == action_id]
        assert [
            event.event_type
            for event in action_events
            if event.event_type
            in {
                "model_action_paused",
                "model_action_retry_requested",
                "model_action_resumed",
            }
        ] == [
            "model_action_paused",
            "model_action_retry_requested",
            "model_action_resumed",
        ]
        retry_event = next(
            event for event in action_events if event.event_type == "model_action_retry_requested"
        )
        assert retry_event.payload["audience"] == "god_view"
        assert retry_event.payload["audience_contract_version"] == 1
        assert any(
            event.event_type == "model_action_recovery_resolved"
            and event.payload.get("action_id") == action_id
            for event in events
        )
        starts = [event for event in action_events if event.event_type == "model_request_started"]
        assert [event.payload["attempt_no"] for event in starts] == [1, 2, 3]
        assert [event.payload["retry_cycle"] for event in starts] == [1, 1, 2]
        assert starts[2].payload["retry_of_attempt_id"] == starts[1].payload["attempt_id"]
        assert (
            len({json.dumps(event.payload["request_payload"], sort_keys=True) for event in starts})
            == 1
        )
        assert not any(
            event.event_type
            in {
                "action_failed",
                "ability_runtime_failed",
                "day_runtime_failed",
            }
            for event in action_events
        )


def test_durable_model_retry_can_be_accepted_by_another_runtime(v2_context) -> None:
    client, session_factory, voice_root = v2_context
    original_runtime = client.app.state.v2_live_runtime
    model_client = client.app.state.v2_test_model_client
    tts_client = client.app.state.v2_test_tts_client
    model_client.split_werewolf_preferences = True
    model_client.retryable_transport_failures_by_stage["sequential_final_vote"] = 2
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-cross-runtime-model-retry",
    )

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "paused_model_error":
                break

        with session_factory() as db:
            recovery = db.scalar(
                select(V2ModelActionRecovery).where(
                    V2ModelActionRecovery.game_id == identifiers["game_id"],
                    V2ModelActionRecovery.state == "paused",
                )
            )
            assert recovery is not None
            action_id = recovery.action_id

        client.app.state.v2_live_runtime = V2LiveRuntime(
            session_factory=session_factory,
            model_client=model_client,
            tts_client=tts_client,
            voice_root=voice_root,
            sample_rate=24000,
            judge_configuration_provider=(
                original_runtime._action_engine._judge_configuration_provider
            ),
            model_retry_policy=original_runtime._action_engine._model_retry_policy,
        )
        retried = client.post(
            f"/api/v1/admin/v2/games/{identifiers['game_id']}/retry-model-action",
            json={"reason": "由另一个 API worker 接受持久恢复请求"},
            headers=headers,
        )
        assert retried.status_code == 202, retried.text
        assert retried.json()["action_id"] == action_id

        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "awaiting_observation":
                break

    client.app.state.v2_live_runtime = original_runtime
    with session_factory() as db:
        recovery = db.get(V2ModelActionRecovery, action_id)
        assert recovery is not None and recovery.state == "resolved"
        event_types = {
            event.event_type
            for event in db.scalars(
                select(V2GameRecordEvent).where(V2GameRecordEvent.game_id == identifiers["game_id"])
            )
        }
        assert "model_action_retry_requested" in event_types
        assert "model_action_resumed" in event_types
        assert "model_action_recovery_resolved" in event_types


def test_admin_can_stop_a_game_paused_after_model_attempts_exhausted(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.split_werewolf_preferences = True
    model_client.retryable_transport_failures_by_stage["sequential_final_vote"] = 2
    identifiers = client.post("/api/v2/games", json=_six_player_create_request()).json()
    headers = _operator_control_headers(
        client,
        session_factory,
        idempotency_key="v2-stop-paused-model-action",
    )

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "paused_model_error":
                break

        with session_factory.begin() as db:
            recovery = db.scalar(
                select(V2ModelActionRecovery).where(
                    V2ModelActionRecovery.game_id == identifiers["game_id"],
                    V2ModelActionRecovery.state == "paused",
                )
            )
            assert recovery is not None
            legacy_snapshot = dict(recovery.action_snapshot)
            legacy_snapshot.pop("audience", None)
            recovery.action_snapshot = legacy_snapshot

        stopped = client.post(
            f"/api/v1/admin/v2/games/{identifiers['game_id']}/stop",
            json={"reason": "模型链路持续异常，停止当前暂停对局"},
            headers=headers,
        )
        assert stopped.status_code == 202, stopped.text
        assert stopped.json()["run_status"] == "canceled"

        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            if json.loads(message["text"]).get("live_state") == "canceled":
                break

    with session_factory() as db:
        game = db.get(V2GameRecord, identifiers["game_id"])
        run = db.get(V2GameRun, identifiers["run_id"])
        assert game is not None and game.status == "canceled"
        assert run is not None and run.status == "canceled"
        event_types = list(
            db.scalars(
                select(V2GameRecordEvent.event_type)
                .where(V2GameRecordEvent.game_id == identifiers["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        assert "model_action_paused" in event_types
        assert [
            event_type
            for event_type in event_types
            if event_type
            in {
                "game_stop_requested",
                "model_action_recovery_canceled",
                "game_canceled",
            }
        ][-3:] == [
            "game_stop_requested",
            "model_action_recovery_canceled",
            "game_canceled",
        ]
        recovery = db.scalar(
            select(V2ModelActionRecovery).where(
                V2ModelActionRecovery.game_id == identifiers["game_id"]
            )
        )
        assert recovery is not None and recovery.state == "canceled"
        recovery_canceled = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == identifiers["game_id"],
                V2GameRecordEvent.event_type == "model_action_recovery_canceled",
            )
        )
        assert recovery_canceled is not None
        assert recovery_canceled.payload["audience"] == "god_view"
        assert recovery_canceled.payload["audience_contract_version"] == 1
        assert "model_action_resumed" not in event_types
        assert "action_failed" not in event_types


def test_admin_cannot_retry_model_action_when_game_is_not_paused(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    identifiers = client.post("/api/v2/games", json=_lobby_create_request()).json()

    response = client.post(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/retry-model-action",
        json={"reason": "当前对局并未因模型错误暂停"},
        headers=_operator_control_headers(
            client,
            session_factory,
            idempotency_key="v2-retry-action-not-paused",
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "admin_v2_model_action_not_paused"
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(V2GameControlRequest)) == 0


def test_withdraw_quality_failure_persists_exact_raw_model_response(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    model_client = client.app.state.v2_test_model_client
    model_client.decline_action_types.update(
        {
            "ability_witch.heal_decision",
            "werewolf_self_explosion",
        }
    )
    model_client.quality_failures_remaining_by_action["sheriff_withdraw"] = 1
    identifiers = client.post("/api/v2/games", json=_advanced_create_request()).json()

    with client.websocket_connect(identifiers["websocket_url"]) as websocket:
        websocket.receive_json()
        websocket.send_json(_ready_message("client.ready"))
        websocket.receive_json()
        while True:
            message = websocket.receive()
            if message.get("text") is None:
                continue
            value = json.loads(message["text"])
            if value.get("live_state") == "awaiting_observation":
                break

    with session_factory() as db:
        failure = db.scalar(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == identifiers["game_id"],
                V2GameRecordEvent.event_type == "model_request_failed",
            )
            .order_by(V2GameRecordEvent.record_seq.desc())
        )
        assert failure is not None
        assert failure.payload["failure_code"] == "model_decision_invalid_speech"
        assert failure.payload["raw_response"] == '{"withdraw":true}'
        assert failure.payload["failure_category"] == "machine_format"
        assert failure.payload["terminal"] is False

    assert client.post("/api/v1/admin/dev-login").status_code == 200
    detail = client.get(f"/api/v1/admin/v2/games/{identifiers['game_id']}")
    assert detail.status_code == 200, detail.text
    request_page = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/model-requests"
        "?after_record_seq=0&page_size=500"
    )
    assert request_page.status_code == 200, request_page.text
    failed_request = next(
        request
        for request in request_page.json()["items"]
        if request["status"] == "failed" and request["action_type"] == "sheriff_withdraw"
    )
    assert failed_request["failure_code"] == "model_decision_invalid_speech"
    assert failed_request["output_source"] == "persisted"
    assert "request_payload" not in failed_request
    assert "raw_response" not in failed_request
    assert "parsed_output" not in failed_request
    assert "passive_observations" not in failed_request
    request_detail = client.get(
        f"/api/v1/admin/v2/games/{identifiers['game_id']}/model-requests/"
        f"{failed_request['attempt_id']}"
    )
    assert request_detail.status_code == 200, request_detail.text
    assert request_detail.json()["raw_response"] == '{"withdraw":true}'


def test_complete_match_vote_resolution_preserves_ties_and_sheriff_weight() -> None:
    assert _leaders({"player-a": 1.0, "player-b": 1.0}) == [
        "player-a",
        "player-b",
    ]
    assert _leaders({"player-a": 1.0, "player-b": 1.5}) == ["player-b"]
    assert _leaders({}) == []


@pytest.mark.parametrize(
    ("objective", "expected"),
    [
        (_SHERIFF_PK_SPEECH_OBJECTIVE, "发表警长竞选平票 PK 发言。"),
        (_EXILE_PK_SPEECH_OBJECTIVE, "发表放逐平票 PK 发言。"),
    ],
)
def test_v2_pk_speech_objectives_only_state_the_current_task(
    objective: str,
    expected: str,
) -> None:
    assert objective == expected
    assert "应" not in objective
    assert "不得" not in objective


def test_v2_public_speech_limits_cover_all_bounded_day_speech_actions() -> None:
    assert _PUBLIC_SPEECH_MAX_CHARS == {
        "first_night_last_words": 200,
        "sheriff_campaign_speech": 300,
        "sheriff_pk_speech": 300,
        "day_debate_speech": 300,
        "exile_pk_speech": 300,
        "exile_last_words": 200,
    }


def test_complete_match_idiot_reveal_survives_and_loses_vote(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_advanced_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory() as db:
        idiot_id = db.scalar(
            select(V2RoleAssignment.player_id).where(
                V2RoleAssignment.game_id == created["game_id"],
                V2RoleAssignment.role_key == "idiot",
            )
        )
    assert idiot_id is not None

    result = repository.resolve_exile(game_id=created["game_id"], player_id=idiot_id)

    assert result.outcome == "idiot_revealed"
    player = repository.snapshot(created["game_id"]).player(idiot_id)
    assert player.alive is True
    assert player.state["idiot_revealed"] is True
    assert player.state["can_vote"] is False


def test_complete_match_double_pre_sheriff_explosion_destroys_badge(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_advanced_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        assert game is not None and run is not None
        game.ability_snapshot = {
            **game.ability_snapshot,
            "day_policies": {
                **game.ability_snapshot["day_policies"],
                "sheriff_badge_bomb_policy": "double",
            },
        }
        game.phase_id = "day_1"
        game.phase_state = "sheriff_election_open"
        game.status = "ready"
        run.status = "ready"
        wolf_ids = list(
            db.scalars(
                select(V2RoleAssignment.player_id)
                .where(
                    V2RoleAssignment.game_id == created["game_id"],
                    V2RoleAssignment.role_key == "werewolf",
                )
                .order_by(V2RoleAssignment.seat)
                .limit(2)
            )
        )
    assert len(wolf_ids) == 2

    first = repository.record_pre_sheriff_explosion(
        game_id=created["game_id"], player_id=wolf_ids[0]
    )
    second = repository.record_pre_sheriff_explosion(
        game_id=created["game_id"], player_id=wolf_ids[1]
    )

    snapshot = repository.snapshot(created["game_id"])
    assert first == "election_interrupted"
    assert second == "badge_destroyed"
    assert snapshot.pre_sheriff_explosion_count == 2
    assert snapshot.sheriff_badge_state == "destroyed"
    assert all(not snapshot.player(player_id).alive for player_id in wolf_ids)


def test_complete_match_badge_transfer_has_distinct_audit_event(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_advanced_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory() as db:
        wolf_ids = list(
            db.scalars(
                select(V2RoleAssignment.player_id)
                .where(
                    V2RoleAssignment.game_id == created["game_id"],
                    V2RoleAssignment.role_key == "werewolf",
                )
                .order_by(V2RoleAssignment.seat)
                .limit(2)
            )
        )
    assert len(wolf_ids) == 2
    repository.set_sheriff(
        game_id=created["game_id"],
        player_id=wolf_ids[0],
        reason="elected_for_test",
    )
    repository.record_day_explosion(
        game_id=created["game_id"],
        player_id=wolf_ids[0],
        stage="test",
    )
    repository.set_sheriff(
        game_id=created["game_id"],
        player_id=wolf_ids[1],
        reason="dead_sheriff_badge_resolution",
    )

    with session_factory() as db:
        event_row = db.scalar(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "sheriff_badge_transferred",
            )
            .order_by(V2GameRecordEvent.record_seq.desc())
        )
    assert event_row is not None
    assert event_row.payload["from_player_id"] == wolf_ids[0]
    assert event_row.payload["player_id"] == wolf_ids[1]
    night_history = V2NightRepository(session_factory).public_history(created["game_id"])
    assert any(
        item["event_type"] == "sheriff_badge_transferred"
        and item["source_event_id"] == event_row.event_id
        and item["record_seq"] == event_row.record_seq
        for item in night_history
    )


def test_complete_match_hunter_shot_chain_resolves_every_new_death(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_advanced_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory.begin() as db:
        assignments = list(
            db.scalars(
                select(V2RoleAssignment)
                .where(V2RoleAssignment.game_id == created["game_id"])
                .order_by(V2RoleAssignment.seat)
            )
        )
        first_hunter = next(item for item in assignments if item.role_key == "hunter")
        second_hunter = next(
            item for item in assignments if item.role_key not in {"hunter", "werewolf"}
        )
        final_target = next(
            item
            for item in assignments
            if item.player_id not in {first_hunter.player_id, second_hunter.player_id}
            and item.role_key != "werewolf"
        )
        second_hunter.role_key = "hunter"
        second_hunter.role = "hunter"
        first_hunter_id = first_hunter.player_id
        second_hunter_id = second_hunter.player_id
        final_target_id = final_target.player_id
        first_state = db.get(
            V2PlayerState,
            (created["game_id"], first_hunter_id),
        )
        assert first_state is not None
        first_state.alive = False
        first_state.death_cause = "exile"

    scripted_actions = _ScriptedDayActionEngine(
        {
            first_hunter_id: second_hunter_id,
            second_hunter_id: final_target_id,
        }
    )
    broadcaster = _CollectingBroadcaster()
    engine = V2DayEngine(
        repository=repository,
        action_engine=scripted_actions,  # type: ignore[arg-type]
    )

    asyncio.run(
        engine.resolve_pending_death_aftermath(
            game_id=created["game_id"],
            broadcaster=broadcaster,  # type: ignore[arg-type]
        )
    )

    snapshot = repository.snapshot(created["game_id"])
    assert scripted_actions.player_actions == [
        first_hunter_id,
        second_hunter_id,
    ]
    assert not snapshot.player(second_hunter_id).alive
    assert not snapshot.player(final_target_id).alive
    assert repository.pending_hunters(created["game_id"]) == ()
    public_deaths = [
        value
        for audience, value in broadcaster.messages
        if audience == "public" and value["type"] == "player.state_changed"
    ]
    assert [value["player_id"] for value in public_deaths] == [
        second_hunter_id,
        final_target_id,
    ]
    assert all(value["cause"] is None for value in public_deaths)


def _prepare_day_state(
    session_factory: sessionmaker[Session],
    game_id: str,
    *,
    phase_state: str = "public_discussion_open",
) -> None:
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, game_id)
        assert game is not None
        run = db.get(V2GameRun, game.current_run_id)
        match = db.get(V2MatchState, game_id)
        assert run is not None and match is not None
        frozen_rule = dict(game.rule_snapshot)
        rule_set = dict(frozen_rule["rule_set"])
        rule_set.update(
            {
                "werewolf_self_explosion_enabled": True,
                "speech_policy": "sequential",
                "speech_rounds": 1,
            }
        )
        game.rule_snapshot = {**frozen_rule, "rule_set": rule_set}
        game.phase_id = "day_1"
        game.phase_state = phase_state
        game.status = "ready"
        run.status = "ready"
        match.round_no = 1


def test_private_action_decision_is_owner_only_and_never_public(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    state = repository.snapshot(created["game_id"])
    first, second = sorted(state.players, key=lambda player: player.seat)[:2]

    fact_id = repository.record_private_action_decision(
        game_id=created["game_id"],
        player_id=first.player_id,
        round_no=state.round_no,
        action_type="exile_vote",
        decision={"target_player_id": second.player_id},
        decision_note="当前票型下先投2号，后续可按新信息修正。",
        context={"vote_round": 1},
    )

    assert fact_id is not None
    first_knowledge = repository.private_knowledge(
        game_id=created["game_id"], player_id=first.player_id
    )
    second_knowledge = repository.private_knowledge(
        game_id=created["game_id"], player_id=second.player_id
    )
    fact = next(item for item in first_knowledge if item["knowledge_fact_id"] == fact_id)
    assert fact["fact_type"] == "private_action_decision"
    assert fact["payload"]["decision"] == {"target_player_id": second.player_id}
    assert fact["payload"]["declared_reason"] == {
        "text": "当前票型下先投2号，后续可按新信息修正。",
        "epistemic_status": "actor_declared_reason",
    }
    assert all(item["knowledge_fact_id"] != fact_id for item in second_knowledge)
    assert all(
        fact["payload"]["declared_reason"]["text"] not in json.dumps(item, ensure_ascii=False)
        for item in repository.snapshot(created["game_id"]).public_history
    )


def test_day_summary_and_private_memories_run_concurrently_and_commit_in_seat_order(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    players = sorted(
        (player for player in before.players if player.alive),
        key=lambda player: player.seat,
    )
    actions = _ConcurrentPrivateMemoryActions(expected_players=len(players))
    broadcaster = _CollectingBroadcaster()
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    transition = asyncio.run(
        engine._close_day(
            game_id=created["game_id"],
            broadcaster=broadcaster,  # type: ignore[arg-type]
            reason="test_private_memories",
            summarize=True,
        )
    )

    assert transition.phase_id == "night_2"
    assert actions.max_in_flight == len(players)
    assert actions.judge_overlapped is True
    assert len(actions.judge_specs) == 1
    assert [spec.actor_id for spec in actions.memory_specs] == [
        player.player_id for player in players
    ]
    assert len({spec.batch_id for spec in actions.memory_specs}) == 1
    assert {spec.context["public_cutoff_record_seq"] for spec in actions.memory_specs} == {
        before.last_record_seq
    }
    assert all(
        spec.context["public_history"] == list(before.public_history)
        and spec.context["memory_visibility"] == "actor_only"
        and spec.decision_contract.speech_max_chars == 400
        and spec.decision_contract.speech_max_sentences == 4
        for spec in actions.memory_specs
    )

    with session_factory() as db:
        facts = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == created["game_id"],
                    V2KnowledgeFact.fact_type == "private_round_memory",
                )
            )
        )
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == created["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    committed_events = [
        event
        for event in events
        if event.event_type == "private_knowledge_recorded"
        and event.payload.get("fact_type") == "private_round_memory"
    ]
    assert [event.payload["owner_id"] for event in committed_events] == [
        player.player_id for player in players
    ]
    assert [event.payload["commit_index"] for event in committed_events] == list(
        range(1, len(players) + 1)
    )
    assert {fact.owner_id for fact in facts} == {player.player_id for player in players}
    assert all(
        fact.payload["round_no"] == 1
        and fact.payload["epistemic_status"] == "actor_subjective_memory"
        for fact in facts
    )
    batch_completed = next(
        event for event in events if event.event_type == "day_private_memory_batch_completed"
    )
    assert batch_completed.payload["public_summary_status"] == "completed"
    assert [item["status"] for item in batch_completed.payload["memories"]] == ["committed"] * len(
        players
    )
    assert repository.snapshot(created["game_id"]).public_history == ()
    for player in players:
        knowledge = repository.private_knowledge(
            game_id=created["game_id"],
            player_id=player.player_id,
        )
        memory = next(item for item in knowledge if item["fact_type"] == "private_round_memory")
        assert memory["authority"] == "actor_memory"
        assert memory["occurred_in"] == {"period": "day", "round_no": 1}
    assert "非公开记忆" not in json.dumps(broadcaster.messages, ensure_ascii=False)


def test_private_round_memory_generation_failure_is_isolated(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    players = sorted(before.players, key=lambda player: player.seat)
    failed_player = players[1]
    actions = _ConcurrentPrivateMemoryActions(
        expected_players=len(players),
        failed_actor_ids={failed_player.player_id},
    )
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    transition = asyncio.run(
        engine._close_day(
            game_id=created["game_id"],
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
            reason="test_private_memory_failure",
            summarize=True,
        )
    )

    assert transition.phase_id == "night_2"
    with session_factory() as db:
        facts = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == created["game_id"],
                    V2KnowledgeFact.fact_type == "private_round_memory",
                )
            )
        )
        completed = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "day_private_memory_batch_completed",
            )
        )
    assert {fact.owner_id for fact in facts} == {
        player.player_id for player in players if player.player_id != failed_player.player_id
    }
    assert completed is not None
    status_by_player = {item["player_id"]: item["status"] for item in completed.payload["memories"]}
    assert status_by_player[failed_player.player_id] == "generation_failed"
    assert all(
        status == "committed"
        for player_id, status in status_by_player.items()
        if player_id != failed_player.player_id
    )


def test_private_round_memory_batch_cancellation_commits_nothing(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    state = repository.snapshot(created["game_id"])
    players = sorted(state.players, key=lambda player: player.seat)
    actions = _ConcurrentPrivateMemoryActions(
        expected_players=len(players),
        canceled_actor_id=players[0].player_id,
    )
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            engine._run_day_summary_and_private_memories(
                state=state,
                broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
            )
        )

    with session_factory() as db:
        facts = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == created["game_id"],
                    V2KnowledgeFact.fact_type == "private_round_memory",
                )
            )
        )
        canceled = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "day_private_memory_batch_canceled",
            )
        )
    assert facts == []
    assert canceled is not None


def test_self_explosion_batch_is_concurrent_and_resolves_one_wolf(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    wolves = sorted(
        (player for player in before.players if player.role_key == "werewolf"),
        key=lambda player: player.seat,
    )
    assert len(wolves) == 2
    actions = _ConcurrentSelfExplosionActions(
        expected_wolves=len(wolves),
        affirmative_actor_ids={wolf.player_id for wolf in wolves},
    )
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    exploded = asyncio.run(
        engine._offer_all_wolves_explosion(
            game_id=created["game_id"],
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
            stage="before_exile_vote",
        )
    )

    assert exploded is True
    assert actions.max_in_flight == len(wolves)
    assert len({spec.batch_id for spec in actions.self_explosion_specs}) == 1
    assert {spec.context["public_cutoff_record_seq"] for spec in actions.self_explosion_specs} == {
        before.last_record_seq
    }
    after = repository.snapshot(created["game_id"])
    assert not after.player(wolves[0].player_id).alive
    assert all(after.player(wolf.player_id).alive for wolf in wolves[1:])

    with session_factory() as db:
        decisions = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == created["game_id"],
                    V2GameRecordEvent.event_type == "werewolf_self_explosion_decided",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        resolution = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "werewolf_self_explosion_batch_resolved",
            )
        )
        private_decisions = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == created["game_id"],
                    V2KnowledgeFact.fact_type == "private_action_decision",
                )
            )
        )
    assert [event.payload["player_id"] for event in decisions] == [
        wolf.player_id for wolf in wolves
    ]
    assert all(event.payload["exploded"] is True for event in decisions)
    assert [event.payload["selected_for_resolution"] for event in decisions] == [True, False]
    assert resolution is not None
    assert resolution.payload["affirmative_player_ids"] == [wolf.player_id for wolf in wolves]
    assert resolution.payload["selected_player_id"] == wolves[0].player_id
    assert resolution.payload["selection_policy"] == "lowest_seat_affirmative"
    assert resolution.payload["public_cutoff_record_seq"] == before.last_record_seq
    assert {item.owner_id for item in private_decisions} == {wolves[1].player_id}
    assert private_decisions[0].payload["decision"] == {"explode": True}
    assert private_decisions[0].payload["declared_reason"]["epistemic_status"] == (
        "actor_declared_reason"
    )


def test_discussion_waits_for_one_round_start_self_explosion_batch(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    wolves = [player for player in before.players if player.role_key == "werewolf"]
    assert len(wolves) == 2
    actions = _ConcurrentSelfExplosionActions(
        expected_wolves=len(wolves),
        affirmative_actor_ids=set(),
    )
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    exploded = asyncio.run(
        engine._run_public_discussion(
            game_id=created["game_id"],
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
        )
    )

    assert exploded is False
    assert actions.batch_completed.is_set()
    assert actions.max_in_flight == len(wolves)
    assert actions.action_types[: len(wolves)] == ["werewolf_self_explosion"] * len(wolves)
    assert actions.action_types[len(wolves) :] == ["day_debate_speech"] * len(before.players)
    assert {spec.context["public_stage"] for spec in actions.self_explosion_specs} == {
        "discussion_round_1"
    }
    assert all(
        spec.context["speech_round"] == 1
        and spec.context["speech_order"]
        == [player.player_id for player in sorted(before.players, key=lambda player: player.seat)]
        for spec in actions.self_explosion_specs
    )
    assert all(
        spec.context["public_history"] == list(before.public_history)
        for spec in actions.self_explosion_specs
    )


def test_sheriff_run_and_withdraw_batches_are_concurrent_at_separate_public_cutoffs(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(
        session_factory,
        created["game_id"],
        phase_state="sheriff_election_open",
    )
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    players = sorted(before.players, key=lambda player: player.seat)
    surviving_candidate = players[-1]
    actions = _ConcurrentSheriffBooleanActions(
        expected_players=len(players),
        surviving_candidate_id=surviving_candidate.player_id,
    )
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    asyncio.run(
        engine._run_sheriff_election(
            game_id=created["game_id"],
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
        )
    )

    assert actions.max_in_flight == {
        "sheriff_run": len(players),
        "sheriff_withdraw": len(players),
    }
    assert all(event.is_set() for event in actions.batch_completed.values())
    run_specs = actions.boolean_specs["sheriff_run"]
    withdraw_specs = actions.boolean_specs["sheriff_withdraw"]
    assert len({spec.batch_id for spec in run_specs}) == 1
    assert len({spec.batch_id for spec in withdraw_specs}) == 1
    assert run_specs[0].batch_id != withdraw_specs[0].batch_id
    assert {spec.context["public_cutoff_record_seq"] for spec in run_specs} == {
        before.last_record_seq
    }
    withdraw_cutoffs = {spec.context["public_cutoff_record_seq"] for spec in withdraw_specs}
    assert len(withdraw_cutoffs) == 1
    assert next(iter(withdraw_cutoffs)) > before.last_record_seq
    assert all(spec.context["public_history"] == list(before.public_history) for spec in run_specs)
    assert all(
        len(
            [
                event
                for event in spec.context["public_history"]
                if event["event_type"] == "day_speech_committed"
                and event["payload"].get("stage") == "sheriff_campaign"
            ]
        )
        == len(players)
        for spec in withdraw_specs
    )

    after = repository.snapshot(created["game_id"])
    assert after.sheriff_player_id == surviving_candidate.player_id
    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == created["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    run_decisions = [event for event in events if event.event_type == "sheriff_run_decided"]
    withdraw_decisions = [
        event for event in events if event.event_type == "sheriff_withdraw_decided"
    ]
    assert [event.payload["player_id"] for event in run_decisions] == [
        player.player_id for player in players
    ]
    assert [event.payload["player_id"] for event in withdraw_decisions] == [
        player.player_id for player in players
    ]
    assert all(event.payload["is_running"] is True for event in run_decisions)
    assert [event.payload["withdrew"] for event in withdraw_decisions] == [
        True,
        True,
        True,
        True,
        True,
        False,
    ]
    assert withdraw_decisions[-1].payload["decision_status"] == "failed"
    withdraw_resolution = next(
        event for event in events if event.event_type == "sheriff_withdraw_batch_resolved"
    )
    assert withdraw_resolution.payload["failed_player_ids"] == [surviving_candidate.player_id]
    assert withdraw_resolution.record_seq < min(
        event.record_seq for event in events if event.event_type == "sheriff_elected"
    )


def test_model_projection_override_requires_a_valid_frozen_batch_cutoff() -> None:
    base = {
        "action_type": "exile_vote",
        "phase_id": "day_1",
        "required_phase_state": "public_discussion_open",
        "objective": "投票",
        "success_live_state": "ready",
        "success_phase_state": "public_discussion_open",
    }

    with pytest.raises(ValueError, match="positive integer"):
        V2SpeechSpec(
            **base,
            batch_id="vote-batch",
            context={"public_cutoff_record_seq": 0},
            projection_at_seq=0,
        )
    with pytest.raises(ValueError, match="dedicated spec field"):
        V2SpeechSpec(
            **base,
            context={"projection_at_seq": 40},
        )
    with pytest.raises(ValueError, match="requires a batch_id"):
        V2SpeechSpec(
            **base,
            context={"public_cutoff_record_seq": 40},
            projection_at_seq=40,
        )
    with pytest.raises(ValueError, match="must match public_cutoff_record_seq"):
        V2SpeechSpec(
            **base,
            batch_id="vote-batch",
            context={"public_cutoff_record_seq": 39},
            projection_at_seq=40,
        )
    with pytest.raises(ValueError, match="must match public_cutoff_record_seq"):
        V2SpeechSpec(
            **base,
            batch_id="vote-batch",
            context={"public_cutoff_record_seq": True},
            projection_at_seq=1,
        )

    frozen = V2SpeechSpec(
        **base,
        batch_id="vote-batch",
        context={"public_cutoff_record_seq": 40},
        projection_at_seq=40,
    )
    assert frozen.projection_at_seq == 40
    assert (
        project_model_action_context(
            {},
            players=(),
            action_record_seq=41,
            projection_at_seq=40,
        )
        == {}
    )
    with pytest.raises(ValueError, match="cannot be later"):
        project_model_action_context(
            {},
            players=(),
            action_record_seq=39,
            projection_at_seq=40,
        )


def test_vote_projection_uses_one_cutoff_for_initial_and_both_recovery_stages(
    v2_context,
) -> None:
    client, session_factory, voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository, engine = _unfenced_text_only_day_engine(
        client=client,
        session_factory=session_factory,
        voice_root=voice_root,
    )
    frozen = repository.snapshot(created["game_id"])
    cutoff = frozen.last_record_seq
    batch_id = f"{frozen.phase_id}:exile_vote:{cutoff}:projection-test"
    voter = min(frozen.players, key=lambda item: item.seat)
    candidates = [item for item in frozen.players if item.player_id != voter.player_id]
    model_client = client.app.state.v2_test_model_client
    first_context_index = len(model_client.decision_contexts)
    broadcaster = _CollectingBroadcaster()

    for stage in (
        "concurrent_initial",
        "concurrent_recovery",
        "sequential_recovery",
    ):
        isolated = stage != "sequential_recovery"
        decision = asyncio.run(
            engine._player_action(
                game_id=created["game_id"],
                player=voter,
                broadcaster=broadcaster,  # type: ignore[arg-type]
                action_type="exile_vote",
                objective="投票选择一名合法候选人。",
                candidates=candidates,
                target_optional=False,
                output_kind="private_vote",
                decision_contract=V2DecisionContract(
                    kind="target",
                    target_mode="required",
                    speech_mode="forbidden",
                ),
                audience="god_view",
                extra_context={
                    "vote_round": 1,
                    "public_cutoff_record_seq": cutoff,
                    "vote_batch_stage": stage,
                },
                frozen_state=frozen,
                projection_at_seq=cutoff,
                defer_presentation=isolated,
                isolated_failure=isolated,
                allow_failure=isolated,
                batch_id=batch_id,
            )
        )
        assert decision is not None

    projected = model_client.decision_contexts[first_context_index:]
    assert len(projected) == 3
    assert [context["task"]["type"] for context in projected] == ["exile_vote"] * 3
    assert {context["task"]["at_seq"] for context in projected} == {cutoff}
    assert {context["state"]["as_of_seq"] for context in projected} == {cutoff}

    with session_factory() as db:
        opened = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == created["game_id"],
                    V2GameRecordEvent.event_type == "action_opened",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    batch_opened = [
        event for event in opened if event.payload["context"].get("batch_id") == batch_id
    ]
    assert len(batch_opened) == 3
    assert [event.payload["context"]["vote_batch_stage"] for event in batch_opened] == [
        "concurrent_initial",
        "concurrent_recovery",
        "sequential_recovery",
    ]
    assert all(
        event.payload["context"]["projection_at_seq"] == cutoff
        and event.payload["context"]["action_record_seq"] > cutoff
        for event in batch_opened
    )
    assert len({event.payload["context"]["action_record_seq"] for event in batch_opened}) == 3


def test_unbatched_player_action_still_projects_at_its_action_record_seq(v2_context) -> None:
    client, session_factory, voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository, engine = _unfenced_text_only_day_engine(
        client=client,
        session_factory=session_factory,
        voice_root=voice_root,
    )
    state = repository.snapshot(created["game_id"])
    voter = min(state.players, key=lambda item: item.seat)
    candidates = [item for item in state.players if item.player_id != voter.player_id]
    model_client = client.app.state.v2_test_model_client
    first_context_index = len(model_client.decision_contexts)

    decision = asyncio.run(
        engine._player_action(
            game_id=created["game_id"],
            player=voter,
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
            action_type="unbatched_projection_probe",
            objective="验证普通动作投影时点。",
            candidates=candidates,
            target_optional=False,
            output_kind="private_vote",
            decision_contract=V2DecisionContract(
                kind="target",
                target_mode="required",
                speech_mode="forbidden",
            ),
            audience="god_view",
        )
    )

    assert decision is not None
    projected = model_client.decision_contexts[first_context_index:]
    assert len(projected) == 1
    with session_factory() as db:
        opened = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "action_opened",
            )
        )
    assert opened is not None
    action_record_seq = opened.payload["context"]["action_record_seq"]
    assert "projection_at_seq" not in opened.payload["context"]
    assert projected[0]["task"]["at_seq"] == action_record_seq
    assert projected[0]["state"]["as_of_seq"] == action_record_seq


def test_vote_batch_is_concurrent_at_one_public_cutoff(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    voters = list(before.players)
    actions = _ConcurrentVoteActions(expected_voters=len(voters))
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    totals = asyncio.run(
        engine._collect_votes(
            game_id=created["game_id"],
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
            action_type="exile_vote",
            voters=voters,
            candidates=voters,
            weighted=True,
            context={"vote_round": 1},
        )
    )

    assert sum(totals.values()) == len(voters)
    assert actions.max_in_flight == len(voters)
    assert actions.initial_batch_completed.is_set()
    assert actions.concurrent_recovery_specs == []
    assert actions.sequential_recovery_specs == []
    assert len({spec.batch_id for spec in actions.initial_specs}) == 1
    assert {spec.context["public_cutoff_record_seq"] for spec in actions.initial_specs} == {
        before.last_record_seq
    }
    assert all(
        spec.projection_at_seq == before.last_record_seq
        and spec.context["public_history"] == list(before.public_history)
        and spec.context["vote_batch_stage"] == "concurrent_initial"
        for spec in actions.initial_specs
    )

    with session_factory() as db:
        committed = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == created["game_id"],
                    V2GameRecordEvent.event_type == "day_vote_committed",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        resolved = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == created["game_id"],
                V2GameRecordEvent.event_type == "day_vote_resolved",
            )
        )
        private_decisions = list(
            db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == created["game_id"],
                    V2KnowledgeFact.fact_type == "private_action_decision",
                )
            )
        )
        ordered_events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == created["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    expected_voter_ids = [player.player_id for player in sorted(voters, key=lambda item: item.seat)]
    assert [event.payload["voter_player_id"] for event in committed] == expected_voter_ids
    assert len({event.payload["batch_id"] for event in committed}) == 1
    assert resolved is not None
    assert resolved.payload["public_cutoff_record_seq"] == before.last_record_seq
    batch_id = committed[0].payload["batch_id"]
    facts_by_owner = {fact.owner_id: fact for fact in private_decisions}
    assert set(facts_by_owner) == set(expected_voter_ids)
    assert all(
        fact.payload["action_type"] == "exile_vote"
        and fact.payload["decision"]
        == {
            "target_player_id": next(
                event.payload["target_player_id"]
                for event in committed
                if event.payload["voter_player_id"] == fact.owner_id
            )
        }
        and fact.payload["declared_reason"]
        == {
            "text": f"{fact.owner_id}选择首个合法候选。",
            "epistemic_status": "actor_declared_reason",
        }
        and fact.payload["context"]
        == {
            "vote_round": 1,
            "batch_id": batch_id,
            "public_cutoff_record_seq": before.last_record_seq,
        }
        for fact in private_decisions
    )
    private_fact_ids = {fact.knowledge_fact_id for fact in private_decisions}
    batch_events = [
        event
        for event in ordered_events
        if (
            event.event_type in {"day_vote_committed", "day_vote_resolved"}
            and event.payload.get("batch_id") == batch_id
        )
        or (
            event.event_type == "private_knowledge_recorded"
            and event.payload.get("knowledge_fact_id") in private_fact_ids
        )
    ]
    assert [event.event_type for event in batch_events] == [
        event_type
        for _voter_id in expected_voter_ids
        for event_type in ("day_vote_committed", "private_knowledge_recorded")
    ] + ["day_vote_resolved"]
    assert [
        event.payload.get("voter_player_id") or event.payload.get("owner_id")
        for event in batch_events[:-1]
    ] == [voter_id for voter_id in expected_voter_ids for _event in range(2)]


def test_vote_batch_finalize_failure_rolls_back_and_same_batch_retries_cleanly(
    v2_context,
    monkeypatch,
) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    voters = list(before.players)
    batch_id = f"{before.phase_id}:exile_vote:{before.last_record_seq}:vote"

    original_append_event = match_repository_module._append_event
    committed_calls = 0

    def fail_during_second_vote(*args, **kwargs) -> None:
        nonlocal committed_calls
        if kwargs.get("event_type") == "day_vote_committed":
            committed_calls += 1
            if committed_calls == 2:
                raise RuntimeError("injected vote batch finalize failure")
        original_append_event(*args, **kwargs)

    monkeypatch.setattr(match_repository_module, "_append_event", fail_during_second_vote)
    failed_engine = V2DayEngine(
        repository=repository,
        action_engine=_ConcurrentVoteActions(expected_voters=len(voters)),  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="injected vote batch finalize failure"):
        asyncio.run(
            failed_engine._collect_votes(
                game_id=created["game_id"],
                broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
                action_type="exile_vote",
                voters=voters,
                candidates=voters,
                weighted=True,
                context={"vote_round": 1},
            )
        )
    monkeypatch.setattr(match_repository_module, "_append_event", original_append_event)

    with session_factory() as db:
        failed_batch_events = [
            event
            for event in db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == created["game_id"],
                    V2GameRecordEvent.event_type.in_(("day_vote_committed", "day_vote_resolved")),
                )
            )
            if event.payload.get("batch_id") == batch_id
        ]
        failed_batch_facts = [
            fact
            for fact in db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == created["game_id"],
                    V2KnowledgeFact.fact_type == "private_action_decision",
                )
            )
            if fact.payload.get("context", {}).get("batch_id") == batch_id
        ]
    assert failed_batch_events == []
    assert failed_batch_facts == []
    assert repository.snapshot(created["game_id"]).last_record_seq == before.last_record_seq

    retry_engine = V2DayEngine(
        repository=repository,
        action_engine=_ConcurrentVoteActions(expected_voters=len(voters)),  # type: ignore[arg-type]
    )
    totals = asyncio.run(
        retry_engine._collect_votes(
            game_id=created["game_id"],
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
            action_type="exile_vote",
            voters=voters,
            candidates=voters,
            weighted=True,
            context={"vote_round": 1},
        )
    )
    assert sum(totals.values()) == len(voters)

    with session_factory() as db:
        retried_batch_events = [
            event
            for event in db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == created["game_id"],
                    V2GameRecordEvent.event_type.in_(("day_vote_committed", "day_vote_resolved")),
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
            if event.payload.get("batch_id") == batch_id
        ]
        retried_batch_facts = [
            fact
            for fact in db.scalars(
                select(V2KnowledgeFact).where(
                    V2KnowledgeFact.game_id == created["game_id"],
                    V2KnowledgeFact.fact_type == "private_action_decision",
                )
            )
            if fact.payload.get("context", {}).get("batch_id") == batch_id
        ]
    assert [event.event_type for event in retried_batch_events] == [
        *["day_vote_committed" for _voter in voters],
        "day_vote_resolved",
    ]
    assert len(retried_batch_facts) == len(voters)


def test_vote_batch_finalize_accepts_sorted_tie_leaders_independent_of_vote_order(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    state = repository.snapshot(created["game_id"])
    voters = list(state.players)
    low_leader_id, high_leader_id = sorted((voters[-2].player_id, voters[-1].player_id))
    target_ids = [
        high_leader_id,
        low_leader_id,
        high_leader_id,
        low_leader_id,
        voters[-1].player_id,
        voters[-2].player_id,
    ]
    totals = {high_leader_id: 3.0, low_leader_id: 3.0}
    batch_id = f"{state.phase_id}:exile_vote:{state.last_record_seq}:vote"

    repository.finalize_day_vote_batch(
        game_id=state.game_id,
        phase_id=state.phase_id,
        phase_state=state.phase_state,
        round_no=state.round_no,
        action_type="exile_vote",
        batch_id=batch_id,
        public_cutoff_record_seq=state.last_record_seq,
        expected_voter_ids=tuple(voter.player_id for voter in voters),
        votes=tuple(
            V2DayVoteCommit(
                voter_player_id=voter.player_id,
                target_player_id=target_id,
                weight=1.0,
                decision_note=f"{voter.player_id}形成平票。",
            )
            for voter, target_id in zip(voters, target_ids, strict=True)
        ),
        decision_context={
            "vote_round": 1,
            "batch_id": batch_id,
            "public_cutoff_record_seq": state.last_record_seq,
        },
        resolution_payload={
            "round_no": state.round_no,
            "action_type": "exile_vote",
            "batch_id": batch_id,
            "public_cutoff_record_seq": state.last_record_seq,
            "eligible_voter_ids": [voter.player_id for voter in voters],
            "ineligible_voter_ids": [],
            "candidate_player_ids": [player.player_id for player in state.players],
            "weighted": False,
            "sheriff_player_id": state.sheriff_player_id,
            "sheriff_vote_weight": None,
            "voter_weights": {voter.player_id: 1.0 for voter in voters},
            "totals": totals,
            "leaders": [low_leader_id, high_leader_id],
            "identity_reveal": "none",
        },
    )

    with session_factory() as db:
        resolved = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == state.game_id,
                V2GameRecordEvent.event_type == "day_vote_resolved",
            )
        )
    assert resolved is not None
    assert list(totals) == [high_leader_id, low_leader_id]
    assert resolved.payload["leaders"] == [low_leader_id, high_leader_id]


def test_vote_batch_recovers_two_missing_votes_concurrently_before_commit(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    voters = sorted(before.players, key=lambda item: item.seat)
    failed_voter_ids = [voters[1].player_id, voters[3].player_id]
    actions = _ConcurrentVoteActions(
        expected_voters=len(voters),
        initial_fail_actor_ids=set(failed_voter_ids),
    )
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    totals = asyncio.run(
        engine._collect_votes(
            game_id=created["game_id"],
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
            action_type="exile_vote",
            voters=voters,
            candidates=voters,
            weighted=True,
            context={"vote_round": 1},
        )
    )

    assert sum(totals.values()) == len(voters)
    assert actions.max_in_flight == len(voters)
    assert actions.concurrent_recovery_max_in_flight == len(failed_voter_ids)
    assert [spec.actor_id for spec in actions.concurrent_recovery_specs] == failed_voter_ids
    assert actions.sequential_recovery_specs == []
    assert all(
        spec.batch_id == actions.initial_specs[0].batch_id
        and spec.projection_at_seq == before.last_record_seq
        and spec.context["public_cutoff_record_seq"] == before.last_record_seq
        and spec.context["public_history"] == list(before.public_history)
        and spec.context["vote_batch_stage"] == "concurrent_recovery"
        and spec.defer_presentation is True
        and spec.isolated_failure is True
        for spec in actions.concurrent_recovery_specs
    )

    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == created["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    recovery_started = next(
        event for event in events if event.event_type == "day_vote_batch_recovery_started"
    )
    concurrent_recovery_completed = next(
        event
        for event in events
        if event.event_type == "day_vote_batch_concurrent_recovery_completed"
    )
    recovery_completed = next(
        event for event in events if event.event_type == "day_vote_batch_recovery_completed"
    )
    committed = [event for event in events if event.event_type == "day_vote_committed"]
    assert recovery_started.payload["failed_voter_ids"] == failed_voter_ids
    assert concurrent_recovery_completed.payload["recovered_voter_ids"] == failed_voter_ids
    assert concurrent_recovery_completed.payload["still_failed_voter_ids"] == []
    assert recovery_completed.payload["recovered_voter_ids"] == failed_voter_ids
    assert concurrent_recovery_completed.record_seq < recovery_completed.record_seq
    assert recovery_completed.record_seq < min(event.record_seq for event in committed)
    assert {
        event.payload["voter_player_id"]
        for event in committed
        if event.payload["voter_player_id"] in set(failed_voter_ids)
    } == set(failed_voter_ids)


def test_vote_batch_only_sequentially_recovers_voter_still_missing_after_concurrency(
    v2_context,
) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    _prepare_day_state(session_factory, created["game_id"])
    repository = V2MatchRepository(session_factory)
    before = repository.snapshot(created["game_id"])
    voters = sorted(before.players, key=lambda item: item.seat)
    initial_failed_voter_ids = [voters[1].player_id, voters[3].player_id]
    still_failed_voter_id = initial_failed_voter_ids[1]
    actions = _ConcurrentVoteActions(
        expected_voters=len(voters),
        initial_fail_actor_ids=set(initial_failed_voter_ids),
        concurrent_recovery_fail_actor_ids={still_failed_voter_id},
    )
    engine = V2DayEngine(
        repository=repository,
        action_engine=actions,  # type: ignore[arg-type]
    )

    totals = asyncio.run(
        engine._collect_votes(
            game_id=created["game_id"],
            broadcaster=_CollectingBroadcaster(),  # type: ignore[arg-type]
            action_type="exile_vote",
            voters=voters,
            candidates=voters,
            weighted=True,
            context={"vote_round": 1},
        )
    )

    assert sum(totals.values()) == len(voters)
    assert actions.concurrent_recovery_max_in_flight == len(initial_failed_voter_ids)
    assert [spec.actor_id for spec in actions.concurrent_recovery_specs] == (
        initial_failed_voter_ids
    )
    assert [spec.actor_id for spec in actions.sequential_recovery_specs] == [still_failed_voter_id]
    sequential_spec = actions.sequential_recovery_specs[0]
    assert sequential_spec.batch_id == actions.initial_specs[0].batch_id
    assert sequential_spec.projection_at_seq == before.last_record_seq
    assert sequential_spec.context["public_cutoff_record_seq"] == before.last_record_seq
    assert sequential_spec.context["public_history"] == list(before.public_history)
    assert sequential_spec.context["vote_batch_stage"] == "sequential_recovery"
    assert sequential_spec.defer_presentation is False
    assert sequential_spec.isolated_failure is False

    with session_factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == created["game_id"])
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    concurrent_recovery_completed = next(
        event
        for event in events
        if event.event_type == "day_vote_batch_concurrent_recovery_completed"
    )
    recovery_completed = next(
        event for event in events if event.event_type == "day_vote_batch_recovery_completed"
    )
    committed = [event for event in events if event.event_type == "day_vote_committed"]
    assert concurrent_recovery_completed.payload["recovered_voter_ids"] == [
        initial_failed_voter_ids[0]
    ]
    assert concurrent_recovery_completed.payload["still_failed_voter_ids"] == [
        still_failed_voter_id
    ]
    assert recovery_completed.payload["recovered_voter_ids"] == initial_failed_voter_ids
    assert concurrent_recovery_completed.record_seq < recovery_completed.record_seq
    assert recovery_completed.record_seq < min(event.record_seq for event in committed)


def test_complete_match_max_rounds_fails_explicitly(v2_context) -> None:
    client, session_factory, _voice_root = v2_context
    created = client.post("/api/v2/games", json=_six_player_create_request()).json()
    repository = V2MatchRepository(session_factory)
    with session_factory.begin() as db:
        game = db.get(V2GameRecord, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        match = db.get(V2MatchState, created["game_id"])
        assert game is not None and run is not None and match is not None
        game.phase_id = "day_8"
        game.phase_state = "public_discussion_open"
        game.status = "ready"
        run.status = "ready"
        match.round_no = 8

    transition = repository.finish_day(
        game_id=created["game_id"],
        reason="day_actions_completed",
    )

    assert transition.phase_id == "day_8"
    assert transition.phase_state == "failed"
    with session_factory() as db:
        match = db.get(V2MatchState, created["game_id"])
        run = db.get(V2GameRun, created["run_id"])
        assert match is not None and run is not None
        assert match.completion_reason == "max_rounds_exceeded"
        assert run.status == "failed"
        assert run.completed_at is not None


def _run_opening_to_nightfall(client: TestClient, websocket_url: str) -> None:
    with client.websocket_connect(websocket_url) as websocket:
        websocket.receive_json()
        websocket.send_json(
            {
                "protocol_version": 1,
                "type": "client.ready",
                "audio": {
                    "encoding": "pcm_s16le",
                    "sample_rate": 24000,
                    "channels": 1,
                },
            }
        )
        while True:
            message = websocket.receive()
            if message.get("text"):
                value = json.loads(message["text"])
                if value.get("live_state") == "awaiting_observation":
                    return


def _collect_until_observation(
    websocket: Any,
    *,
    message_types: list[str],
    committed_texts: list[str],
) -> None:
    while True:
        message = websocket.receive()
        if message.get("text") is None:
            continue
        value = json.loads(message["text"])
        message_types.append(value["type"])
        if value["type"] == "speech.segment_committed":
            committed_texts.append(value["text"])
        if value.get("live_state") in {"awaiting_observation", "failed"}:
            return


def _ready_message(message_type: str) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "type": message_type,
        "audio": {
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
        },
    }


def _operator_control_headers(
    client: TestClient,
    session_factory: sessionmaker[Session],
    *,
    idempotency_key: str,
) -> dict[str, str]:
    session = client.post("/api/v1/admin/dev-login")
    assert session.status_code == 200, session.text
    with session_factory.begin() as db:
        user = db.scalar(select(User).where(User.email == "v2-admin@example.test"))
        assert user is not None
        user.admin_role = "operator"
    return {
        "X-CSRF-Token": session.json()["csrf_token"],
        "Idempotency-Key": idempotency_key,
    }


def _receive_realtime_action(
    websocket: Any,
    *,
    include_audio_headers: bool = False,
) -> dict[str, Any]:
    committed_texts: list[str] = []
    presentation_seqs: list[int] = []
    phase_changes: list[str] = []
    audio_chunks = 0
    audio_headers: list[dict[str, Any]] = []
    while True:
        message = websocket.receive()
        if message.get("bytes") is not None:
            audio_chunks += 1
            if include_audio_headers:
                header, pcm = _decode_audio(message["bytes"])
                assert pcm == PCM_CHUNK
                audio_headers.append(header)
            continue
        if message.get("text") is None:
            continue
        value = json.loads(message["text"])
        if value.get("type") == "speech.segment_committed":
            committed_texts.append(value["text"])
            presentation_seqs.append(value["presentation_seq"])
        if value.get("type") == "game.phase_changed":
            phase_changes.append(value["phase_id"])
        if value.get("live_state") == "awaiting_observation":
            result = {
                "committed_texts": committed_texts,
                "presentation_seqs": presentation_seqs,
                "phase_changes": phase_changes,
                "audio_chunks": audio_chunks,
                "awaiting_observation": True,
            }
            if include_audio_headers:
                result["audio_headers"] = audio_headers
            return result


def _decode_audio(value: bytes) -> tuple[dict[str, Any], bytes]:
    header_size = int.from_bytes(value[4:6], "big")
    header = json.loads(value[6 : 6 + header_size])
    return header, value[6 + header_size :]


def _lobby_create_request() -> dict[str, Any]:
    return {
        "title": "经典 8 人",
        "lobby_snapshot": {
            "schema_version": 1,
            "rule_set": {
                "id": "classic_8",
                "version": "1",
                "name": "经典 8 人",
                "player_count": 2,
                "roles": [
                    {"role": "werewolf", "count": 1, "team": "werewolves"},
                    {"role": "villager", "count": 1, "team": "village"},
                ],
                "sheriff_enabled": False,
                "werewolf_self_explosion_enabled": True,
                "exile_last_words_enabled": True,
                "first_night_last_words_enabled": False,
            },
            "rule_set_revision_id": "rule_rev_123",
            "seed": 42,
            "max_rounds": 8,
            "player_configs": [
                {
                    "seat": 1,
                    "profile_id": "profile-1",
                    "name": "阿青",
                    "model_provider": "agent_plan",
                    "model": "private-model-id",
                    "personality": "private personality prompt",
                    "avatar_image_url": "/api/v1/public/player-profiles/profile-1/avatar",
                    "strategy_profile": "private-strategy",
                    "tts_speaker": "private-speaker",
                },
                {
                    "seat": 2,
                    "profile_id": "profile-2",
                    "name": "白石",
                    "model_provider": "agent_plan",
                    "model": "test-model",
                },
            ],
            "lineup_quality_report": {
                "schema_version": 1,
                "policy_mode": "repair",
                "player_count": 2,
                "configured_count": 2,
                "is_blocked": False,
                "was_repaired": False,
                "style_bucket_count": 2,
                "required_style_bucket_count": 2,
                "violations": [],
            },
            "allow_lineup_quality_warnings": False,
        },
    }


def _six_player_create_request() -> dict[str, Any]:
    roles = [
        {"role": "werewolf", "count": 2, "team": "werewolves"},
        {"role": "villager", "count": 1, "team": "villagers"},
        {"role": "guard", "count": 1, "team": "villagers"},
        {"role": "seer", "count": 1, "team": "villagers"},
        {"role": "hunter", "count": 1, "team": "villagers"},
    ]
    return {
        "title": "动态首夜 6 人验收",
        "lobby_snapshot": {
            "schema_version": 1,
            "rule_set": {
                "id": "dynamic_first_night_6",
                "version": "1",
                "name": "动态首夜 6 人",
                "player_count": 6,
                "roles": roles,
                "night_actions": ["remove", "protect", "investigate"],
                "win_condition": "wolves_gte_others",
                "sheriff_enabled": False,
            },
            "rule_set_revision_id": "rule_rev_dynamic_6",
            "seed": 7,
            "max_rounds": 8,
            "player_configs": [
                {
                    "seat": seat,
                    "profile_id": f"dynamic-player-{seat}",
                    "name": f"玩家{seat}",
                    "model_provider": "agent_plan",
                    "model": "test-model",
                    "personality": f"这是玩家{seat}的独立性格。",
                    "tts_speaker": f"speaker-{seat}",
                }
                for seat in range(1, 7)
            ],
            "lineup_quality_report": {
                "schema_version": 1,
                "policy_mode": "observe",
                "player_count": 6,
                "configured_count": 6,
                "is_blocked": False,
                "was_repaired": False,
                "style_bucket_count": 6,
                "required_style_bucket_count": 3,
                "violations": [],
            },
            "allow_lineup_quality_warnings": False,
        },
    }


def _advanced_create_request() -> dict[str, Any]:
    roles = [
        {"role": "werewolf", "count": 4, "team": "werewolves"},
        {"role": "villager", "count": 4, "team": "villagers"},
        {"role": "seer", "count": 1, "team": "villagers"},
        {"role": "witch", "count": 1, "team": "villagers"},
        {"role": "hunter", "count": 1, "team": "villagers"},
        {"role": "idiot", "count": 1, "team": "villagers"},
    ]
    return {
        "title": "进阶十二人首夜验收",
        "lobby_snapshot": {
            "schema_version": 1,
            "rule_set": {
                "id": "classic_12_seer_witch_hunter_idiot",
                "version": "1",
                "name": "经典十二人",
                "player_count": 12,
                "roles": roles,
                "night_actions": [
                    "remove",
                    "investigate",
                    "witch_save",
                    "witch_poison",
                ],
                "win_condition": "wolves_gte_others",
                "sheriff_enabled": True,
                "first_night_last_words_enabled": True,
            },
            "rule_set_revision_id": "rule_rev_advanced_12",
            "seed": 12,
            "max_rounds": 12,
            "player_configs": [
                {
                    "seat": seat,
                    "profile_id": f"advanced-player-{seat}",
                    "name": f"进阶玩家{seat}",
                    "model_provider": "agent_plan",
                    "model": "test-model",
                    "personality": f"进阶玩家{seat}会独立权衡风险。",
                    "tts_speaker": f"speaker-{seat}",
                }
                for seat in range(1, 13)
            ],
            "lineup_quality_report": {
                "schema_version": 1,
                "policy_mode": "observe",
                "player_count": 12,
                "configured_count": 12,
                "is_blocked": False,
                "was_repaired": False,
                "style_bucket_count": 8,
                "required_style_bucket_count": 3,
                "violations": [],
            },
            "allow_lineup_quality_warnings": False,
        },
    }
