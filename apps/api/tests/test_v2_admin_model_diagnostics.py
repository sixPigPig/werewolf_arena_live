from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import app.v2.router as v2_router
from app.v2.model_failure_episode import stable_failure_episode_id
from app.v2.model_failure_impact import classify_model_failure_impact
from app.v2.model_context_compaction import encode_known_events_v6
from app.v2.model_context_contract import (
    CURRENT_DISCOURSE_LEDGER_SCHEMA_VERSION,
    DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
    KNOWN_EVENTS_SCHEMA_VERSION,
    MODEL_CONTEXT_SCHEMA_VERSION,
    MODEL_VIEW_SELECTOR_VERSION,
    PROMPT_TEMPLATE_VERSION,
)
from app.v2.router import (
    _admin_event_summary,
    _admin_expanded_known_events,
    _admin_model_requests,
)


GAME_ID = "v2_game_admin_diag"
RUN_ID = "v2_run_admin_diag"
ACTION_ID = "v2_action_admin_diag"
ATTEMPT_ID = "v2_model_admin_diag_1"
RETRY_ATTEMPT_ID = "v2_model_admin_diag_2"
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _current_prompt_projection() -> dict[str, int]:
    return {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "known_events_schema_version": KNOWN_EVENTS_SCHEMA_VERSION,
        "ledger_schema_version": CURRENT_DISCOURSE_LEDGER_SCHEMA_VERSION,
        "model_view_schema_version": DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
        "model_view_selector_version": MODEL_VIEW_SELECTOR_VERSION,
    }


def test_admin_expands_v12_known_events_on_the_backend_only() -> None:
    canonical = {
        "schema_version": 5,
        "events": [
            {
                "event_ref": "1",
                "kind": "private_round_memory",
                "authority": "actor_memory",
                "visibility": "actor_private",
                "owner_scope": "player",
                "owner_ref": "seat_2",
                "known_at_seq": 1,
                "speech": "仅管理员可见的展开校验文本。",
            }
        ],
        "questions": [],
        "relations": [],
    }
    context = {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "known_events": encode_known_events_v6(canonical),
    }
    request_payload = {
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "请完成这个实时动作："
                        + json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                    }
                ],
            }
        ]
    }

    expanded, status = _admin_expanded_known_events(
        request_payload,
        model_context_schema_version=MODEL_CONTEXT_SCHEMA_VERSION,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        prompt_projection=_current_prompt_projection(),
    )

    assert status == "verified"
    assert expanded == canonical


def test_admin_never_guesses_unknown_or_malformed_known_events() -> None:
    assert _admin_expanded_known_events(
        {"messages": [{"role": "user", "content": "{}"}]},
        model_context_schema_version=11,
        prompt_template_version=4,
        prompt_projection=None,
    ) == (None, "not_applicable")
    assert _admin_expanded_known_events(
        {"messages": [{"role": "user", "content": "{}"}]},
        model_context_schema_version=99,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        prompt_projection=_current_prompt_projection(),
    ) == (None, "invalid")
    assert _admin_expanded_known_events(
        {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
                            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                            "known_events": {"schema_version": 6},
                        }
                    ),
                }
            ]
        },
        model_context_schema_version=MODEL_CONTEXT_SCHEMA_VERSION,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        prompt_projection=_current_prompt_projection(),
    ) == (None, "invalid")


def test_admin_rejects_hybrid_outer_and_inner_prompt_contracts() -> None:
    canonical = {"schema_version": 5, "events": [], "questions": [], "relations": []}

    def payload(*, context_schema: int, context_prompt: int) -> dict[str, object]:
        return {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "model_context_schema_version": context_schema,
                            "prompt_template_version": context_prompt,
                            "known_events": encode_known_events_v6(canonical),
                        }
                    ),
                }
            ]
        }

    assert _admin_expanded_known_events(
        payload(context_schema=11, context_prompt=PROMPT_TEMPLATE_VERSION),
        model_context_schema_version=MODEL_CONTEXT_SCHEMA_VERSION,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        prompt_projection=_current_prompt_projection(),
    ) == (None, "invalid")
    assert _admin_expanded_known_events(
        payload(context_schema=MODEL_CONTEXT_SCHEMA_VERSION, context_prompt=4),
        model_context_schema_version=MODEL_CONTEXT_SCHEMA_VERSION,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        prompt_projection=_current_prompt_projection(),
    ) == (None, "invalid")
    assert _admin_expanded_known_events(
        payload(
            context_schema=MODEL_CONTEXT_SCHEMA_VERSION,
            context_prompt=PROMPT_TEMPLATE_VERSION,
        ),
        model_context_schema_version=MODEL_CONTEXT_SCHEMA_VERSION,
        prompt_template_version=4,
        prompt_projection=_current_prompt_projection(),
    ) == (None, "invalid")
    for key in _current_prompt_projection():
        wrong_projection = _current_prompt_projection()
        wrong_projection[key] += 1
        assert _admin_expanded_known_events(
            payload(
                context_schema=MODEL_CONTEXT_SCHEMA_VERSION,
                context_prompt=PROMPT_TEMPLATE_VERSION,
            ),
            model_context_schema_version=MODEL_CONTEXT_SCHEMA_VERSION,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            prompt_projection=wrong_projection,
        ) == (None, "invalid")


def test_admin_expands_known_events_only_for_the_requested_detail(monkeypatch) -> None:
    canonical = {"schema_version": 5, "events": [], "questions": [], "relations": []}
    context = {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "known_events": encode_known_events_v6(canonical),
    }
    request_payload = {
        "messages": [
            {
                "role": "user",
                "content": "请完成这个实时动作："
                + json.dumps(context, ensure_ascii=False, separators=(",", ":")),
            }
        ]
    }
    events = [
        _action_opened(),
        _event(
            2,
            "model_request_started",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "attempt_no": 1,
                "retry_cycle": 1,
                "audience": "private",
                "request_kind": "speech",
                "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
                "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                "prompt_projection": _current_prompt_projection(),
                "request_payload": request_payload,
            },
        ),
    ]
    original_expand = v2_router.expand_known_events_v6
    calls = 0

    def counted_expand(value: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return original_expand(value)

    monkeypatch.setattr(v2_router, "expand_known_events_v6", counted_expand)

    summary_rows = _admin_model_requests(events, [])
    assert calls == 0
    assert summary_rows[0].expanded_known_events is None

    detail_rows = _admin_model_requests(
        events,
        [],
        expanded_known_events_attempt_id=ATTEMPT_ID,
    )
    assert calls == 1
    assert detail_rows[0].known_events_expansion_status == "verified"
    assert detail_rows[0].expanded_known_events == canonical


def test_admin_does_not_reconstruct_missing_historical_or_unknown_payloads(
    monkeypatch,
) -> None:
    def reject_reconstruction(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("historical request must not use the current request builder")

    monkeypatch.setattr(v2_router, "build_model_request_payload", reject_reconstruction)

    for schema_version, prompt_version, expected_status in (
        (11, 4, "not_applicable"),
        (99, 99, "invalid"),
    ):
        events = [
            _action_opened(),
            _event(
                2,
                "model_request_started",
                {
                    "action_id": ACTION_ID,
                    "attempt_id": ATTEMPT_ID,
                    "attempt_no": 1,
                    "retry_cycle": 1,
                    "audience": "private",
                    "request_kind": "speech",
                    "model_context_schema_version": schema_version,
                    "prompt_template_version": prompt_version,
                },
            ),
        ]

        detail = _admin_model_requests(
            events,
            [],
            expanded_known_events_attempt_id=ATTEMPT_ID,
        )[0]
        assert detail.input_source == "unavailable"
        assert detail.request_payload is None
        assert detail.expanded_known_events is None
        assert detail.known_events_expansion_status == expected_status


def _event(
    record_seq: int,
    event_type: str,
    payload: dict[str, object],
    *,
    run_id: str = RUN_ID,
) -> SimpleNamespace:
    return SimpleNamespace(
        game_id=GAME_ID,
        run_id=run_id,
        event_id=record_seq,
        record_seq=record_seq,
        event_type=event_type,
        payload_schema_version=1,
        payload=payload,
        created_at=NOW + timedelta(milliseconds=record_seq),
    )


def _action_opened(
    *,
    run_id: str = RUN_ID,
    action_type: str = "judge_opening_speech",
) -> SimpleNamespace:
    return _event(
        1,
        "action_opened",
        {
            "action_id": ACTION_ID,
            "context": {
                "phase_id": "opening",
                "action_type": action_type,
                "actor": {"kind": "judge", "id": "judge"},
            },
        },
        run_id=run_id,
    )


def test_admin_model_request_reconstructs_live_reasoning_and_usage() -> None:
    events = [
        _action_opened(action_type="day_debate_speech"),
        _event(
            2,
            "model_request_started",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "attempt_no": 1,
                "retry_cycle": 1,
                "audience": "private",
                "request_kind": "speech",
                "request_payload": {"model": "test-model", "stream": True},
            },
        ),
        _event(
            3,
            "model_stream_progress",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "provider_request_id": "provider-live-1",
                "reasoning_delta": "第一步：核对身份。",
                "text_delta": None,
                "reasoning_character_count": 9,
                "text_character_count": 0,
                "estimated_reasoning_tokens": 9,
                "estimated_output_tokens": 9,
                "usage_update_count": 0,
            },
        ),
        _event(
            4,
            "model_stream_progress",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "provider_request_id": "provider-live-1",
                "reasoning_delta": "第二步：选择发言。",
                "text_delta": '{"speech":',
                "reasoning_character_count": 18,
                "text_character_count": 10,
                "estimated_reasoning_tokens": 18,
                "estimated_output_tokens": 24,
                "provider_usage": {
                    "output_tokens": 25,
                    "reasoning_tokens": 18,
                },
                "usage_update_count": 1,
            },
        ),
    ]

    request = _admin_model_requests(
        events,
        [],
        expanded_known_events_attempt_id=ATTEMPT_ID,
    )[0]

    assert request.status == "running"
    assert request.output_source == "unavailable"
    assert request.provider_request_id == "provider-live-1"
    assert request.stream_reasoning == "第一步：核对身份。第二步：选择发言。"
    assert request.stream_text == '{"speech":'
    assert request.stream_reasoning_character_count == 18
    assert request.stream_text_character_count == 10
    assert request.stream_estimated_reasoning_tokens == 18
    assert request.stream_estimated_output_tokens == 24
    assert request.stream_content_truncated is False
    assert request.stream_progress_updated_at == events[-1].created_at
    assert request.provider_usage == {"output_tokens": 25, "reasoning_tokens": 18}
    assert request.usage_update_count == 1


def test_admin_event_summary_omits_live_stream_content() -> None:
    summary = _admin_event_summary(
        _event(
            3,
            "model_stream_progress",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "reasoning_delta": "不应进入增量事件列表",
                "text_delta": "不应进入增量事件列表",
                "estimated_output_tokens": 12,
            },
        )
    )

    assert "reasoning_delta" not in summary.payload
    assert "text_delta" not in summary.payload
    assert summary.payload["estimated_output_tokens"] == 12


def test_admin_model_request_projects_stream_retry_and_episode_diagnostics() -> None:
    episode_id = stable_failure_episode_id(
        game_id=GAME_ID,
        run_id=RUN_ID,
        action_id=ACTION_ID,
        retry_cycle=1,
        first_failed_attempt_id=ATTEMPT_ID,
    )
    events = [
        _action_opened(action_type="day_debate_speech"),
        _event(
            2,
            "model_request_started",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "attempt_no": 1,
                "retry_cycle": 1,
                "audience": "private",
                "request_kind": "speech",
                "prior_output_budget_failures": 2,
                "automatic_output_budget_attempt_count": 2,
                "automatic_output_budget_budget": 3,
                "model_generation_policy_contract_status": "supported",
                "model_generation_policy_schema_version": 1,
                "model_generation_policy_classification_version": 1,
                "model_generation_policy_enforcement": "observe_only",
                "model_generation_policy_reasoning_parameter_mode": (
                    "inherit_frozen_model_configuration"
                ),
                "model_generation_policy_profile": "recoverable_public_speech",
                "model_generation_policy_profile_source": "explicit_action_profile",
                "reasoning_only_timeout_ms": 180_000,
                "timeout_max_attempts": 1,
                "shadow_would_timeout": None,
                "request_payload": {"model": "test-model", "stream": True},
            },
        ),
        _event(
            3,
            "model_request_failed",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "attempt_no": 1,
                "retry_cycle": 1,
                "audience": "private",
                "failure_episode_id": episode_id,
                "failure_kind": "model",
                "failure_code": "model_output_budget_exhausted",
                "failure_category": "output_budget",
                "finish_reason": "max_output_tokens",
                "provider_usage": {
                    "input_tokens": 120,
                    "output_tokens": 64,
                    "reasoning_tokens": 48,
                    "total_tokens": 184,
                    "cached_input_tokens": 20,
                },
                "usage_update_count": 2,
                "usage_conflict_observed": False,
                "usage_consistency": "exact",
                "queue_wait_ms": 11,
                "provider_in_flight": 2,
                "provider_concurrency_limit": 4,
                "first_token_ms": 19,
                "reasoning_only_elapsed_ms": 180_001,
                "elapsed_ms": 180_100,
                "reasoning_delta_count": 7,
                "text_delta_count": 2,
                "max_inter_delta_ms": 17,
                "last_progress_ms": 72,
                "effective_attempt_limit": 2,
                "retry_delay_ms": 250,
                "required_retry_window_ms": 1_250,
                "automatic_retry_scheduled": False,
                "automatic_retry_stop_reason": "insufficient_action_budget",
                "prior_output_budget_failures": 2,
                "output_budget_failure_count": 1,
                "automatic_output_budget_attempt_count": 3,
                "automatic_output_budget_budget": 3,
                "model_generation_policy_contract_status": "supported",
                "model_generation_policy_schema_version": 1,
                "model_generation_policy_classification_version": 1,
                "model_generation_policy_enforcement": "observe_only",
                "model_generation_policy_reasoning_parameter_mode": (
                    "inherit_frozen_model_configuration"
                ),
                "model_generation_policy_profile": "recoverable_public_speech",
                "model_generation_policy_profile_source": "explicit_action_profile",
                "reasoning_only_timeout_ms": 180_000,
                "timeout_max_attempts": 1,
                "shadow_would_timeout": True,
            },
        ),
        _event(
            4,
            "game_canceled",
            {"canceled_failure_episode_ids": [episode_id]},
        ),
    ]

    requests = _admin_model_requests(events, [])

    assert len(requests) == 1
    request = requests[0]
    assert request.status == "failed"
    assert request.finish_reason == "max_output_tokens"
    assert request.provider_usage is not None
    assert request.provider_usage["reasoning_tokens"] == 48
    assert request.usage_update_count == 2
    assert request.usage_conflict_observed is False
    assert request.usage_consistency == "exact"
    assert request.queue_wait_ms == 11
    assert request.reasoning_only_elapsed_ms == 180_001
    assert request.reasoning_delta_count == 7
    assert request.text_delta_count == 2
    assert request.max_inter_delta_ms == 17
    assert request.last_progress_ms == 72
    assert request.effective_attempt_limit == 2
    assert request.retry_delay_ms == 250
    assert request.required_retry_window_ms == 1_250
    assert request.automatic_retry_scheduled is False
    assert request.automatic_retry_stop_reason == "insufficient_action_budget"
    assert request.prior_output_budget_failures == 2
    assert request.output_budget_failure_count == 1
    assert request.automatic_output_budget_attempt_count == 3
    assert request.automatic_output_budget_budget == 3
    assert request.model_generation_policy_contract_status == "supported"
    assert request.model_generation_policy_schema_version == 1
    assert request.model_generation_policy_classification_version == 1
    assert request.model_generation_policy_enforcement == "observe_only"
    assert (
        request.model_generation_policy_reasoning_parameter_mode
        == "inherit_frozen_model_configuration"
    )
    assert request.model_generation_policy_profile == "recoverable_public_speech"
    assert request.model_generation_policy_profile_source == "explicit_action_profile"
    assert request.reasoning_only_timeout_ms == 180_000
    assert request.timeout_max_attempts == 1
    assert request.shadow_would_timeout is True
    assert request.failure_episode_id == episode_id
    assert request.failure_resolution == "run_canceled"
    assert request.failure_episode_source_attempt_ids == [ATTEMPT_ID]
    assert request.failure_episode_source_event_refs is not None
    assert [ref.event_type for ref in request.failure_episode_source_event_refs] == [
        "model_request_failed"
    ]
    assert request.failure_episode_terminal_event_refs is not None
    assert [ref.event_type for ref in request.failure_episode_terminal_event_refs] == [
        "game_canceled"
    ]
    assert request.resolution_event_type == "game_canceled"
    assert request.resolution_event_id == 4
    assert request.resolution_event_record_seq == 4
    assert request.resolution_updated_at_record_seq == 4
    assert request.last_record_seq == 4
    assert request.failure_episode_invariant_errors == []


def test_admin_model_request_keeps_legacy_failure_explicitly_unavailable() -> None:
    events = [
        _action_opened(),
        _event(
            2,
            "model_request_failed",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "attempt_no": 1,
                "retry_cycle": 1,
                "audience": "private",
                "failure_kind": "model",
                "failure_code": "model_not_configured",
                "failure_category": "provider_configuration",
            },
        ),
    ]

    requests = _admin_model_requests(events, [])

    assert len(requests) == 1
    request = requests[0]
    assert request.status == "failed"
    assert request.input_source == "unavailable"
    assert request.failure_episode_id is None
    assert request.failure_resolution == "legacy_unavailable"
    assert request.resolution_updated_at_record_seq is None
    assert request.prior_output_budget_failures is None
    assert request.output_budget_failure_count is None
    assert request.automatic_output_budget_attempt_count is None
    assert request.automatic_output_budget_budget is None
    assert request.model_generation_policy_contract_status is None
    assert request.model_generation_policy_schema_version is None
    assert request.model_generation_policy_classification_version is None
    assert request.model_generation_policy_enforcement is None
    assert request.model_generation_policy_reasoning_parameter_mode is None
    assert request.model_generation_policy_profile is None
    assert request.model_generation_policy_profile_source is None
    assert request.reasoning_only_timeout_ms is None
    assert request.timeout_max_attempts is None
    assert request.shadow_would_timeout is None


def test_admin_model_request_projects_success_diagnostics_symmetrically() -> None:
    events = [
        _action_opened(action_type="day_debate_speech"),
        _event(
            2,
            "model_request_started",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "retry_cycle": 1,
                "audience": "private",
                "prior_output_budget_failures": 0,
                "automatic_output_budget_attempt_count": 0,
                "automatic_output_budget_budget": 3,
                "model_generation_policy_contract_status": "supported",
                "model_generation_policy_schema_version": 1,
                "model_generation_policy_classification_version": 1,
                "model_generation_policy_enforcement": "observe_only",
                "model_generation_policy_reasoning_parameter_mode": (
                    "inherit_frozen_model_configuration"
                ),
                "model_generation_policy_profile": "recoverable_public_speech",
                "model_generation_policy_profile_source": "explicit_action_profile",
                "reasoning_only_timeout_ms": 180_000,
                "timeout_max_attempts": 1,
                "shadow_would_timeout": None,
                "request_payload": {},
            },
        ),
        _event(
            3,
            "model_response_received",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "retry_cycle": 1,
                "audience": "private",
                "application_validation_result": "accepted",
                "finish_reason": "completed",
                "provider_usage": {
                    "input_tokens": -1,
                    "output_tokens": 32,
                    "reasoning_tokens": True,
                    "unknown": 999,
                },
                "usage_update_count": 1,
                "usage_conflict_observed": False,
                "usage_consistency": "unavailable",
                "reasoning_only_elapsed_ms": 21,
                "model_generation_policy_contract_status": "supported",
                "model_generation_policy_schema_version": 1,
                "model_generation_policy_classification_version": 1,
                "model_generation_policy_enforcement": "observe_only",
                "model_generation_policy_reasoning_parameter_mode": (
                    "inherit_frozen_model_configuration"
                ),
                "model_generation_policy_profile": "recoverable_public_speech",
                "model_generation_policy_profile_source": "explicit_action_profile",
                "reasoning_only_timeout_ms": 180_000,
                "timeout_max_attempts": 1,
                "shadow_would_timeout": False,
                "reasoning_delta_count": 3,
                "text_delta_count": 1,
                "max_inter_delta_ms": 9,
                "last_progress_ms": 43,
                "completed_ms": 45,
            },
        ),
        _event(4, "action_succeeded", {"action_id": ACTION_ID}),
    ]

    request = _admin_model_requests(events, [])[0]

    assert request.status == "succeeded"
    assert request.finish_reason == "completed"
    assert request.provider_usage is not None
    assert request.provider_usage["output_tokens"] == 32
    assert request.model_dump()["provider_usage"] == {"output_tokens": 32}
    assert request.reasoning_only_elapsed_ms == 21
    assert request.reasoning_delta_count == 3
    assert request.text_delta_count == 1
    assert request.max_inter_delta_ms == 9
    assert request.last_progress_ms == 43
    assert request.model_generation_policy_contract_status == "supported"
    assert request.model_generation_policy_profile == "recoverable_public_speech"
    assert request.reasoning_only_timeout_ms == 180_000
    assert request.timeout_max_attempts == 1
    assert request.shadow_would_timeout is False
    assert request.failure_episode_id is None
    assert request.failure_resolution is None


def test_admin_model_request_maps_successful_retry_to_source_failure_episode() -> None:
    episode_id = stable_failure_episode_id(
        game_id=GAME_ID,
        run_id=RUN_ID,
        action_id=ACTION_ID,
        retry_cycle=1,
        first_failed_attempt_id=ATTEMPT_ID,
    )
    events = [
        _action_opened(),
        _event(
            2,
            "model_request_started",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "attempt_no": 1,
                "retry_cycle": 1,
                "audience": "private",
                "prior_output_budget_failures": 0,
                "automatic_output_budget_attempt_count": 0,
                "automatic_output_budget_budget": 3,
                "request_payload": {},
            },
        ),
        _event(
            3,
            "model_request_failed",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "attempt_no": 1,
                "retry_cycle": 1,
                "audience": "private",
                "failure_episode_id": episode_id,
                "failure_kind": "model",
                "failure_code": "model_output_budget_exhausted",
                "failure_category": "output_budget",
                "automatic_retry_scheduled": True,
                "terminal": False,
                "prior_output_budget_failures": 0,
                "output_budget_failure_count": 1,
                "automatic_output_budget_attempt_count": 1,
                "automatic_output_budget_budget": 3,
            },
        ),
        _event(
            4,
            "model_retry_scheduled",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "next_attempt_id": RETRY_ATTEMPT_ID,
                "retry_cycle": 1,
                "audience": "private",
                "failure_episode_id": episode_id,
                "prior_output_budget_failures": 0,
                "output_budget_failure_count": 1,
                "automatic_output_budget_attempt_count": 1,
                "automatic_output_budget_budget": 3,
            },
        ),
        _event(
            5,
            "model_request_started",
            {
                "action_id": ACTION_ID,
                "attempt_id": RETRY_ATTEMPT_ID,
                "attempt_no": 2,
                "retry_cycle": 1,
                "retry_of_attempt_id": ATTEMPT_ID,
                "audience": "private",
                "failure_episode_id": episode_id,
                "prior_output_budget_failures": 0,
                "automatic_output_budget_attempt_count": 1,
                "automatic_output_budget_budget": 3,
                "request_payload": {},
            },
        ),
        _event(
            6,
            "model_response_received",
            {
                "action_id": ACTION_ID,
                "attempt_id": RETRY_ATTEMPT_ID,
                "retry_cycle": 1,
                "audience": "private",
                "failure_episode_id": episode_id,
                "application_validation_result": "accepted",
                "finish_reason": "completed",
            },
        ),
    ]

    requests = _admin_model_requests(events, [])

    assert [request.attempt_id for request in requests] == [
        ATTEMPT_ID,
        RETRY_ATTEMPT_ID,
    ]
    assert [request.status for request in requests] == ["failed", "succeeded"]
    assert requests[0].prior_output_budget_failures == 0
    assert requests[0].output_budget_failure_count == 1
    assert requests[0].automatic_output_budget_attempt_count == 1
    assert requests[0].automatic_output_budget_budget == 3
    assert requests[1].prior_output_budget_failures == 0
    assert requests[1].output_budget_failure_count is None
    assert requests[1].automatic_output_budget_attempt_count == 1
    assert requests[1].automatic_output_budget_budget == 3
    for request in requests:
        assert request.failure_episode_id == episode_id
        assert request.failure_resolution == "automatic_retry_success"
        assert request.failure_episode_source_attempt_ids == [
            ATTEMPT_ID,
            RETRY_ATTEMPT_ID,
        ]
        assert request.resolution_event_type == "model_response_received"
        assert request.resolution_event_record_seq == 6
        assert request.resolution_updated_at_record_seq == 6
        assert request.last_record_seq == 6
        assert request.failure_episode_invariant_errors == []
    assert [request.attempt_id for request in requests if request.last_record_seq > 5] == [
        ATTEMPT_ID,
        RETRY_ATTEMPT_ID,
    ]


def test_admin_model_request_derives_episodes_per_run() -> None:
    other_run_id = "v2_run_admin_diag_other"
    episode_id = stable_failure_episode_id(
        game_id=GAME_ID,
        run_id=RUN_ID,
        action_id=ACTION_ID,
        retry_cycle=1,
        first_failed_attempt_id=ATTEMPT_ID,
    )
    events = [
        _action_opened(),
        _event(
            2,
            "model_request_started",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "retry_cycle": 1,
                "audience": "private",
                "request_payload": {},
            },
        ),
        _event(
            3,
            "model_request_failed",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "retry_cycle": 1,
                "audience": "private",
                "failure_episode_id": episode_id,
                "failure_code": "model_transport_failed",
            },
        ),
        _event(
            4,
            "game_canceled",
            {"canceled_failure_episode_ids": [episode_id]},
            run_id=other_run_id,
        ),
    ]

    request = _admin_model_requests(events, [])[0]

    assert request.failure_resolution == "unresolved"
    assert request.resolution_updated_at_record_seq == 3
    assert request.failure_episode_invariant_errors == []


def test_admin_model_request_normalizes_failure_status_by_impact() -> None:
    cases = (
        (
            "model_prefetch_capacity_unavailable",
            "admission_capacity",
            "provider_admission",
            "skipped",
            "expected_control_flow",
            False,
        ),
        (
            "pre_exile_pipeline_generation_canceled",
            "canceled",
            "pipeline_generation",
            "canceled",
            "expected_control_flow",
            False,
        ),
        (
            "pre_exile_pipeline_canceled",
            "canceled",
            "operator_interrupted",
            "canceled",
            "expected_control_flow",
            False,
        ),
        (
            "day_speech_prefetch_canceled",
            "canceled",
            "operator_interrupted",
            "canceled",
            "expected_control_flow",
            False,
        ),
        (
            "day_speech_prefetch_post_close_deadline",
            "timeout",
            "pipeline_generation",
            "failed",
            "user_visible_degradation",
            True,
        ),
        (
            "model_transport_failed",
            "transport",
            "stream",
            "failed",
            "operational_failure",
            True,
        ),
    )

    for (
        failure_code,
        failure_category,
        failure_stage,
        expected_status,
        impact,
        counts,
    ) in cases:
        events = [
            _action_opened(),
            _event(
                2,
                "model_request_started",
                {
                    "action_id": ACTION_ID,
                    "attempt_id": ATTEMPT_ID,
                    "retry_cycle": 1,
                    "audience": "private",
                    "request_payload": {},
                },
            ),
            _event(
                3,
                "model_request_failed",
                {
                    "action_id": ACTION_ID,
                    "attempt_id": ATTEMPT_ID,
                    "retry_cycle": 1,
                    "audience": "private",
                    "failure_code": failure_code,
                    "failure_category": failure_category,
                    "failure_stage": failure_stage,
                },
            ),
        ]

        request = _admin_model_requests(events, [])[0]

        assert request.status == expected_status
        assert request.failure_code == failure_code
        assert request.failure_impact == impact
        assert request.counts_as_failure is counts


def test_capacity_failure_with_provider_activity_counts_as_operational_failure() -> None:
    events = [
        _action_opened(),
        _event(
            2,
            "model_request_started",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "retry_cycle": 1,
                "audience": "private",
                "request_payload": {},
            },
        ),
        _event(
            3,
            "model_response_headers_received",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "provider_request_id": "provider-contacted",
            },
        ),
        _event(
            4,
            "model_request_failed",
            {
                "action_id": ACTION_ID,
                "attempt_id": ATTEMPT_ID,
                "retry_cycle": 1,
                "audience": "private",
                "failure_code": "model_prefetch_capacity_unavailable",
                "failure_category": "admission_capacity",
                "failure_stage": "provider_admission",
            },
        ),
    ]

    request = _admin_model_requests(events, [])[0]

    assert request.status == "failed"
    assert request.failure_impact == "operational_failure"
    assert request.counts_as_failure is True


def test_failure_impact_uses_durable_technical_resolution_when_available() -> None:
    impact = classify_model_failure_impact(
        has_failure=True,
        failure_code="model_empty_stream",
        failure_category="invalid_response",
        failure_stage="stream",
        failure_resolution="technical_skip",
    )

    assert impact.failure_impact == "user_visible_degradation"
    assert impact.counts_as_failure is True
    assert impact.display_status == "failed"
