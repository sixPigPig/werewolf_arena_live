from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import app.match.action_engine as action_engine_module
from app.judge_configuration import RuntimeJudgeConfiguration
from app.match.action_engine import (
    ActionEngine,
    ActionFailure,
    ActionResult,
    DecisionContract,
    SpeechSpec,
)
from app.match.model_client import ModelDecision, ModelError, ModelTarget
from app.match.model_context import ProjectedModelContext
from app.match.model_context_contract import current_model_context_contract
from app.match.model_generation_policy_contract import (
    current_model_generation_policy_contract,
)
from app.match.repository import (
    ActionClaim,
    ExecutionOwnershipLost,
    PresentationIdentity,
)


class _Repository:
    def __init__(
        self,
        *,
        cancel_error: asyncio.CancelledError | None = None,
        fail_action_result: int | None = None,
        fail_action_error: BaseException | None = None,
    ) -> None:
        self._record_seq = 100
        self.cancel_error = cancel_error
        self.fail_action_result = fail_action_result
        self.fail_action_error = fail_action_error
        self.events: list[tuple[int, dict[str, Any]]] = []
        self.failures: list[dict[str, Any]] = []
        self.completed_silently = False
        self.completed_text = False

    def claim_action(self, **values: Any) -> ActionClaim:
        return ActionClaim(
            game_id=values["game_id"],
            run_id="v2_run_action_lineage",
            action_id=values["action_id"],
            phase_id=values["expected_phase_id"],
            audience=values["audience"],
            best_effort=values["best_effort"],
            non_blocking=values["non_blocking"],
            action_record_seq=42,
            model_context_contract=current_model_context_contract(),
            model_generation_policy_contract=current_model_generation_policy_contract(),
            audio_mode="text_only",
        )

    def check_cancellation(self, _game_id: str) -> None:
        if self.cancel_error is not None:
            raise self.cancel_error

    def append_event(self, **values: Any) -> int:
        self._record_seq += 1
        self.events.append((self._record_seq, values))
        return self._record_seq

    def model_binding_failure_streak(self, **_values: Any) -> int:
        return 0

    def resolve_model_action_recovery(self, **_values: Any) -> None:
        return

    def complete_silent_action(self, **_values: Any) -> int:
        self.completed_silently = True
        self._record_seq += 1
        return self._record_seq

    def open_presentation(self, **values: Any) -> PresentationIdentity:
        claim = values["claim"]
        return PresentationIdentity(
            game_id=claim.game_id,
            run_id=claim.run_id,
            action_id=claim.action_id,
            phase_id=claim.phase_id,
            presentation_seq=1,
            presentation_id=values["presentation_id"],
            speech_id=values["speech_id"],
            segment_index=0,
            voice_asset_id=None,
            storage_key="",
            subtitle_text=values["subtitle_text"],
            audience=claim.audience,
            source_event_id=201,
            source_record_seq=102,
            actor_kind=values["actor_kind"],
            actor_id=values["actor_id"],
        )

    def complete_text_action(self, **_values: Any) -> None:
        self.completed_text = True

    def fail_action(self, **values: Any) -> int | None:
        self.failures.append(values)
        if self.fail_action_error is not None:
            raise self.fail_action_error
        return self.fail_action_result


class _ModelClient:
    def __init__(
        self,
        *,
        decision: ModelDecision | None = None,
        error: ModelError | None = None,
    ) -> None:
        self.decision = decision
        self.error = error
        self.calls = 0
        self.admission_modes: list[str] = []

    def resolve_model_target(
        self,
        *,
        model_provider: str,
        model_id: str,
        model_supports_thinking: bool,
        model_parameters: dict[str, Any],
    ) -> ModelTarget:
        return ModelTarget(
            provider=model_provider,
            model_id=model_id,
            supports_thinking=model_supports_thinking,
            parameters=dict(model_parameters),
        )

    def build_request_payload(self, **_values: Any) -> dict[str, Any]:
        return {"max_output_tokens": 512}

    def output_enforcement_metadata(self, **_values: Any) -> dict[str, Any]:
        return {
            "requested_output_enforcement": "strict_json_schema",
            "provider_output_enforcement": "prompt_and_application_validation",
            "output_schema_name": None,
            "output_schema_version": None,
        }

    async def generate_action_decision(
        self,
        *,
        check_cancellation: Any = None,
        admission_mode: str = "normal",
        **_values: Any,
    ) -> ModelDecision:
        if check_cancellation is not None:
            check_cancellation()
        self.admission_modes.append(admission_mode)
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.decision is not None
        return self.decision


class _SequenceModelClient(_ModelClient):
    def __init__(self, outcomes: list[ModelDecision | ModelError]) -> None:
        super().__init__()
        self.outcomes = list(outcomes)

    async def generate_action_decision(
        self,
        *,
        check_cancellation: Any = None,
        admission_mode: str = "normal",
        **_values: Any,
    ) -> ModelDecision:
        if check_cancellation is not None:
            check_cancellation()
        self.admission_modes.append(admission_mode)
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, ModelError):
            raise outcome
        return outcome


class _BlockingModelClient(_ModelClient):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def generate_action_decision(
        self,
        *,
        check_cancellation: Any = None,
        admission_mode: str = "normal",
        **_values: Any,
    ) -> ModelDecision:
        if check_cancellation is not None:
            check_cancellation()
        self.admission_modes.append(admission_mode)
        self.calls += 1
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _Broadcaster:
    async def broadcast_json(self, *_args: Any, **_kwargs: Any) -> None:
        return

    async def broadcast_pcm(self, *_args: Any, **_kwargs: Any) -> None:
        return

    async def set_current(self, *_args: Any, **_kwargs: Any) -> None:
        return


@pytest.fixture(autouse=True)
def projected_model_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        action_engine_module,
        "project_model_action_context_with_metadata",
        lambda *_args, **_kwargs: ProjectedModelContext(
            context={
                "model_context_schema_version": 12,
                "prompt_template_version": 5,
            },
            observation_context={"hard_rules": {}},
            projection_metadata={},
        ),
    )
    monkeypatch.setattr(
        action_engine_module,
        "model_prompt_metadata",
        lambda *_args, **_kwargs: {},
    )


def test_generation_result_carries_exact_model_response_record_seq(tmp_path: Path) -> None:
    repository = _Repository()
    model_client = _ModelClient(
        decision=ModelDecision(
            target_player_id=None,
            speech="提前生成的第二位玩家发言。",
            provider_request_id="provider-prefetch-success",
            first_token_ms=3,
            completed_ms=8,
            raw_response='{"speech":"提前生成的第二位玩家发言。"}',
        )
    )
    engine = _engine(repository, model_client, tmp_path)

    result = asyncio.run(
        engine.run_player_decision_result(
            game_id="v2_game_action_lineage",
            broadcaster=_Broadcaster(),
            spec=_generation_spec(),
        )
    )

    assert result is not None and result.decision is not None
    response_seq, response = next(
        (record_seq, event)
        for record_seq, event in repository.events
        if event["event_type"] == "model_response_received"
    )
    assert result.model_response_record_seq == response_seq
    assert result.terminal_event_record_seq == repository._record_seq
    assert response["payload"]["application_validation_result"] == "accepted"
    assert repository.completed_silently is True
    assert model_client.admission_modes == ["idle_only"]


def test_precomputed_presentation_has_no_model_response_record_seq(tmp_path: Path) -> None:
    repository = _Repository()
    model_client = _ModelClient()
    engine = _engine(repository, model_client, tmp_path)
    spec = SpeechSpec(
        action_type="day_debate_speech",
        phase_id="day_1",
        required_phase_state="public_discussion_open",
        objective="展示已预生成的发言。",
        success_live_state="ready",
        success_phase_state="public_discussion_open",
        actor_kind="player",
        actor_id="player_2",
        model_provider="agent_plan",
        model_id="test-model",
        model_supports_thinking=False,
        model_parameters=_model_parameters(),
        pipeline_slot_id="v2_slot_action_lineage",
        pipeline_stage="presentation",
    )

    result = asyncio.run(
        engine.present_player_decision_result(
            game_id="v2_game_action_lineage",
            broadcaster=_Broadcaster(),
            spec=spec,
            decision=ModelDecision(
                target_player_id=None,
                speech="直接展示此前生成的发言。",
                provider_request_id="provider-prefetch-source",
                first_token_ms=3,
                completed_ms=8,
            ),
        )
    )

    assert result is not None
    assert result.model_response_record_seq is None
    assert result.terminal_event_record_seq is None
    assert model_client.calls == 0
    assert repository.completed_text is True
    assert not any(
        event["event_type"] == "model_response_received" for _record_seq, event in repository.events
    )


@pytest.mark.parametrize("return_result", [False, True])
def test_foreground_player_entrypoints_forward_presentation_opened_callback(
    tmp_path: Path,
    return_result: bool,
) -> None:
    repository = _Repository()
    model_client = _ModelClient(
        decision=ModelDecision(
            target_player_id=None,
            speech="当前顺序生成并公开展示的发言。",
            provider_request_id="provider-foreground-success",
            first_token_ms=2,
            completed_ms=6,
        )
    )
    engine = _engine(repository, model_client, tmp_path)
    opened: list[PresentationIdentity] = []
    arguments = {
        "game_id": "v2_game_action_lineage",
        "broadcaster": _Broadcaster(),
        "spec": _foreground_spec(),
        "on_presentation_opened": opened.append,
    }

    if return_result:
        result = asyncio.run(engine.run_player_decision_result(**arguments))
        assert result is not None and result.decision is not None
        response_seq = next(
            record_seq
            for record_seq, event in repository.events
            if event["event_type"] == "model_response_received"
        )
        assert result.model_response_record_seq == response_seq
    else:
        decision = asyncio.run(engine.run_player_decision(**arguments))
        assert decision is not None

    assert len(opened) == 1
    assert opened[0].actor_id == "player_1"
    assert repository.completed_text is True
    assert model_client.admission_modes == ["normal"]


def test_isolated_failure_carries_action_failed_record_seq(tmp_path: Path) -> None:
    repository = _Repository(fail_action_result=777)
    model_client = _ModelClient(
        error=ModelError(
            "model_prefetch_capacity_unavailable",
            retryable=False,
            failure_stage="provider_admission",
        )
    )
    engine = _engine(repository, model_client, tmp_path)

    result = asyncio.run(
        engine.run_player_decision_result(
            game_id="v2_game_action_lineage",
            broadcaster=_Broadcaster(),
            spec=_generation_spec(),
        )
    )

    assert result is not None and result.failure is not None
    assert result.failure.code == "model_prefetch_capacity_unavailable"
    assert result.model_response_record_seq is None
    assert result.terminal_event_record_seq == 777
    assert repository.failures[-1]["failure_episode_disposition"] == ("isolated_action_failure")
    request_failure = next(
        event
        for _record_seq, event in repository.events
        if event["event_type"] == "model_request_failed"
    )
    assert request_failure["payload"]["failure_category"] == "admission_capacity"
    assert request_failure["payload"]["model_binding_health_counted"] is False
    assert not any(
        event["event_type"] == "model_binding_health_updated"
        for _record_seq, event in repository.events
    )


def test_pipeline_technical_skip_uses_fixed_judge_cue_without_player_model_request(
    tmp_path: Path,
) -> None:
    repository = _Repository()
    model_client = _ModelClient()
    engine = _engine(
        repository,
        model_client,
        tmp_path,
        judge_configuration=RuntimeJudgeConfiguration(
            voice_mode="fixed",
            tts_speaker="judge-speaker",
            random_tts_speakers=(),
            version=1,
        ),
    )
    source_failure = ActionFailure(
        code="model_output_budget_exhausted",
        category="output_budget",
        terminal_attempt_id="v2_model_source_failure",
        failure_episode_id="v2_failure_episode_source",
    )

    result = asyncio.run(
        engine.complete_pipeline_speech_technical_skip(
            game_id="v2_game_action_lineage",
            broadcaster=_Broadcaster(),
            player_id="player_2",
            player_seat=2,
            action_type="day_debate_speech",
            phase_id="day_1",
            required_phase_state="public_discussion_open",
            round_no=1,
            speech_round=1,
            speech_order=["player_1", "player_2", "player_3"],
            source_slot_id="v2_slot_source_failure",
            source_action_id="v2_action_source_failure",
            source_failure=source_failure,
            source_terminal_event_record_seq=700,
        )
    )

    assert result is not None and result.failure is None and result.decision is None
    assert model_client.calls == 0
    assert repository.completed_text is True
    events = [event for _record_seq, event in repository.events]
    public_skip = next(
        event for event in events if event["event_type"] == "action_skipped_technical"
    )
    assert public_skip["audience"] == "all"
    assert public_skip["payload"] == {
        "action_id": "v2_action_source_failure",
        "phase_id": "day_1",
        "round_no": 1,
        "action_type": "day_debate_speech",
        "actor_id": "player_2",
        "player_seat": 2,
        "reason": "technical_failure",
    }
    rendered = next(event for event in events if event["event_type"] == "judge_speech_rendered")
    assert rendered["payload"]["text"] == "2号本轮因技术原因未能完成发言，流程继续。"
    assert not any(event["event_type"] == "model_request_started" for event in events)


def test_prefetch_empty_stream_retries_once_inside_same_action_while_predecessor_active(
    tmp_path: Path,
) -> None:
    repository = _Repository()
    model_client = _SequenceModelClient(
        [
            ModelError(
                "model_empty_stream",
                retryable=True,
                failure_stage="stream",
                first_token_seen=True,
            ),
            ModelDecision(
                target_player_id=None,
                speech="隐藏重试成功的发言。",
                provider_request_id="provider-hidden-retry-success",
                first_token_ms=2,
                completed_ms=5,
            ),
        ]
    )
    engine = _engine(repository, model_client, tmp_path)
    guard_calls: list[int] = []

    result = asyncio.run(
        engine.run_player_decision_result(
            game_id="v2_game_action_lineage",
            broadcaster=_Broadcaster(),
            spec=replace(
                _generation_spec(),
                pipeline_empty_stream_max_attempts=2,
                pipeline_retry_mode="empty_stream_once_while_predecessor_active",
            ),
            model_retry_guard=lambda _exc, attempt_no: guard_calls.append(attempt_no) or True,
        )
    )

    assert result is not None and result.decision is not None
    assert result.decision.speech == "隐藏重试成功的发言。"
    assert model_client.calls == 2
    assert guard_calls == [1]
    started = [
        event
        for _record_seq, event in repository.events
        if event["event_type"] == "model_request_started"
    ]
    failed = next(
        event
        for _record_seq, event in repository.events
        if event["event_type"] == "model_request_failed"
    )
    retry = next(
        event
        for _record_seq, event in repository.events
        if event["event_type"] == "model_retry_scheduled"
    )
    assert len(started) == 2
    assert {event["payload"]["action_id"] for event in started} == {failed["payload"]["action_id"]}
    assert failed["payload"]["pipeline_retry_guard_allowed"] is True
    assert failed["payload"]["effective_attempt_limit"] == 2
    assert retry["payload"]["next_attempt_id"] == started[1]["payload"]["attempt_id"]


def test_prefetch_empty_stream_does_not_retry_after_predecessor_closed(tmp_path: Path) -> None:
    repository = _Repository(fail_action_result=778)
    model_client = _SequenceModelClient(
        [
            ModelError(
                "model_empty_stream",
                retryable=True,
                failure_stage="stream",
                first_token_seen=True,
            )
        ]
    )
    engine = _engine(repository, model_client, tmp_path)

    result = asyncio.run(
        engine.run_player_decision_result(
            game_id="v2_game_action_lineage",
            broadcaster=_Broadcaster(),
            spec=replace(
                _generation_spec(),
                pipeline_empty_stream_max_attempts=2,
                pipeline_retry_mode="empty_stream_once_while_predecessor_active",
            ),
            model_retry_guard=lambda _exc, _attempt_no: False,
        )
    )

    assert result is not None and result.failure is not None
    assert result.failure.code == "model_empty_stream"
    assert model_client.calls == 1
    failure = next(
        event
        for _record_seq, event in repository.events
        if event["event_type"] == "model_request_failed"
    )
    assert failure["payload"]["pipeline_retry_guard_allowed"] is False
    assert failure["payload"]["effective_attempt_limit"] == 1
    assert failure["payload"]["automatic_retry_scheduled"] is False
    assert not any(
        event["event_type"] == "model_retry_scheduled" for _record_seq, event in repository.events
    )


def test_pipeline_retry_mode_never_retries_output_budget_exhaustion(tmp_path: Path) -> None:
    class _LegacyGenerationPolicyRepository(_Repository):
        def claim_action(self, **values: Any) -> ActionClaim:
            return replace(
                super().claim_action(**values),
                model_generation_policy_contract=None,
            )

    repository = _LegacyGenerationPolicyRepository()
    model_client = _SequenceModelClient(
        [
            ModelError(
                "model_output_budget_exhausted",
                retryable=True,
                failure_stage="stream",
                first_token_seen=True,
            ),
            ModelDecision(
                target_player_id=None,
                speech=None,
                provider_request_id="must-not-run-same-budget-retry",
                first_token_ms=2,
                completed_ms=5,
                boolean_field="explode",
                boolean_value=True,
            ),
        ]
    )
    engine = _engine(repository, model_client, tmp_path)
    guard_calls: list[int] = []

    result = asyncio.run(
        engine.run_player_decision_result(
            game_id="v2_game_action_lineage",
            broadcaster=_Broadcaster(),
            spec=_pre_exile_self_explosion_generation_spec(),
            model_retry_guard=lambda _exc, attempt_no: guard_calls.append(attempt_no) or True,
        )
    )

    assert result is not None and result.decision is not None
    assert result.decision.boolean_field == "explode"
    assert result.decision.boolean_value is False
    assert model_client.calls == 1
    assert guard_calls == []
    failure = next(
        event
        for _record_seq, event in repository.events
        if event["event_type"] == "model_request_failed"
    )
    assert failure["payload"]["failure_code"] == "model_output_budget_exhausted"
    assert failure["payload"]["effective_attempt_limit"] == 1
    assert failure["payload"]["automatic_retry_scheduled"] is False
    assert failure["payload"]["pipeline_retry_guard_allowed"] is None
    assert not any(
        event["event_type"] == "model_retry_scheduled" for _record_seq, event in repository.events
    )


def test_prefetch_post_close_deadline_terminalizes_attempt_action_and_result(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[ActionResult, _Repository, _BlockingModelClient]:
        repository = _Repository(fail_action_result=779)
        model_client = _BlockingModelClient()
        engine = _engine(repository, model_client, tmp_path)
        task = asyncio.create_task(
            engine.run_player_decision_result(
                game_id="v2_game_action_lineage",
                broadcaster=_Broadcaster(),
                spec=replace(
                    _generation_spec(),
                    pipeline_empty_stream_max_attempts=2,
                    pipeline_retry_mode="empty_stream_once_while_predecessor_active",
                ),
                model_retry_guard=lambda _exc, _attempt_no: True,
            )
        )
        await asyncio.wait_for(model_client.started.wait(), timeout=0.5)
        assert task.cancel("day_speech_prefetch_post_close_deadline") is True
        result = await task
        assert result is not None
        return result, repository, model_client

    result, repository, model_client = asyncio.run(scenario())

    assert result.failure is not None
    assert result.failure.code == "day_speech_prefetch_post_close_deadline"
    assert result.failure.category == "timeout"
    assert result.terminal_event_record_seq == 779
    assert model_client.calls == 1
    request_failure = next(
        event
        for _record_seq, event in repository.events
        if event["event_type"] == "model_request_failed"
    )
    payload = request_failure["payload"]
    assert payload["failure_code"] == "day_speech_prefetch_post_close_deadline"
    assert payload["failure_category"] == "timeout"
    assert payload["attempt_terminal"] is True
    assert payload["run_terminal"] is False
    assert payload["automatic_retry_scheduled"] is False
    assert repository.failures[-1]["failure_episode_id"] == payload["failure_episode_id"]
    assert repository.failures[-1]["failure_episode_disposition"] == ("isolated_action_failure")


@pytest.mark.parametrize(
    ("secondary_failure", "expect_original_cancel"),
    [
        (ExecutionOwnershipLost("v2_run_execution_lease_lost"), False),
        (asyncio.CancelledError("stop_requested"), True),
    ],
)
def test_prefetch_cancellation_is_durable_without_masking_original_cancel(
    tmp_path: Path,
    secondary_failure: BaseException,
    expect_original_cancel: bool,
) -> None:
    original_cancel = asyncio.CancelledError("original_prefetch_cancel")
    repository = _Repository(
        cancel_error=original_cancel,
        fail_action_error=secondary_failure,
    )
    engine = _engine(repository, _ModelClient(), tmp_path)

    expected_type = asyncio.CancelledError if expect_original_cancel else ExecutionOwnershipLost
    with pytest.raises(expected_type) as captured:
        asyncio.run(
            engine.run_player_decision_result(
                game_id="v2_game_action_lineage",
                broadcaster=_Broadcaster(),
                spec=_generation_spec(),
            )
        )

    assert captured.value is (original_cancel if expect_original_cancel else secondary_failure)
    assert len(repository.failures) == 1
    failure = repository.failures[0]
    assert failure["failure_kind"] == "canceled"
    assert failure["failure_code"] == "day_speech_prefetch_canceled"
    assert failure["failure_episode_disposition"] == "isolated_action_failure"


@pytest.mark.parametrize("field_name", ["model_response_record_seq", "terminal_event_record_seq"])
def test_action_result_record_sequences_must_be_positive(field_name: str) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must be a positive integer"):
        ActionResult(action_id="v2_action_invalid_seq", **{field_name: 0})


def _engine(
    repository: _Repository,
    model_client: _ModelClient,
    voice_root: Path,
    *,
    judge_configuration: RuntimeJudgeConfiguration | None = None,
) -> ActionEngine:
    return ActionEngine(
        repository=repository,  # type: ignore[arg-type]
        model_client=model_client,
        tts_client=None,
        tts_client_factory=None,
        tts_capability_enabled=False,
        voice_root=voice_root,
        sample_rate=24_000,
        judge_configuration_provider=lambda _game_id: judge_configuration,
    )


def _generation_spec() -> SpeechSpec:
    return SpeechSpec(
        action_type="day_debate_speech",
        phase_id="day_1",
        required_phase_state="public_discussion_open",
        objective="在前驱音频播放时提前生成下一位发言。",
        success_live_state="ready",
        success_phase_state="public_discussion_open",
        actor_kind="player",
        actor_id="player_2",
        model_provider="agent_plan",
        model_id="test-model",
        model_supports_thinking=False,
        model_parameters=_model_parameters(),
        context={"public_cutoff_record_seq": 41},
        defer_presentation=True,
        isolated_failure=True,
        batch_id="v2_slot_action_lineage:generation",
        projection_at_seq=41,
        model_admission_mode="idle_only",
        pipeline_slot_id="v2_slot_action_lineage",
        pipeline_stage="generation",
    )


def _foreground_spec() -> SpeechSpec:
    return SpeechSpec(
        action_type="day_debate_speech",
        phase_id="day_1",
        required_phase_state="public_discussion_open",
        objective="顺序生成并展示当前发言。",
        success_live_state="ready",
        success_phase_state="public_discussion_open",
        actor_kind="player",
        actor_id="player_1",
        model_provider="agent_plan",
        model_id="test-model",
        model_supports_thinking=False,
        model_parameters=_model_parameters(),
    )


def _pre_exile_self_explosion_generation_spec() -> SpeechSpec:
    return SpeechSpec(
        action_type="werewolf_self_explosion",
        phase_id="day_1",
        required_phase_state="public_discussion_open",
        objective="在最后公开发言播放期间决定是否自爆。",
        success_live_state="ready",
        success_phase_state="public_discussion_open",
        actor_kind="player",
        actor_id="wolf_1",
        audience="god_view",
        model_provider="agent_plan",
        model_id="test-model",
        model_supports_thinking=False,
        model_parameters=_model_parameters(),
        output_kind="private_decision",
        decision_contract=DecisionContract(
            kind="boolean",
            boolean_field="explode",
            speech_mode="forbidden",
            true_meaning="立即自爆",
            false_meaning="不自爆",
        ),
        context={"public_history_cutoff_record_seq": 41},
        defer_presentation=True,
        isolated_failure=True,
        batch_id="v2_preex_pipeline",
        pipeline_slot_id="v2_preex_pipeline",
        pipeline_stage="generation",
        pipeline_kind="pre_exile",
        pipeline_result_kind="self_explosion",
        pipeline_empty_stream_max_attempts=2,
        pipeline_retry_mode="empty_stream_once_while_predecessor_active",
    )


def _model_parameters() -> dict[str, Any]:
    return {
        "thinking": "disabled",
        "reasoning_effort": None,
        "max_tokens_mode": "explicit",
        "max_tokens": 512,
    }
