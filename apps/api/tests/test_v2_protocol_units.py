from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any
import wave

import pytest

from app.v2 import tts_client as v2_tts
from app.v2.action_engine import (
    V2ActionFailure,
    V2ActionResult,
    V2DecisionContract,
    V2ModelRetryPolicy,
    V2SpeechSpec,
    _action_model_parameters,
    _constrain_model_speech,
    _effective_model_attempt_limit,
    _enrich_model_error_from_decision,
    _is_blocking_required_target,
    _model_generation_policy_audit_payload,
    _required_retry_window_seconds,
    _resolved_reasoning_only_elapsed_ms,
    _validate_model_target_decision,
)
from app.v2.director_projection import project_director_scene
from app.v2.god_view_access import (
    issue_god_view_access_token,
    verify_god_view_access_token,
)
from app.v2.god_view_projection import (
    V2GodViewProjectionError,
    project_god_view_player_identities,
)
from app.v2.model_client import (
    V2ModelDecision,
    V2ModelError,
    V2QualityError,
    _decision_model_input,
    _decision_object,
    _decision_repair_kind,
    _decision_fields,
    _speech_output_instruction,
    _required_speech,
    _sse_data,
    _next_with_cancellation,
    model_failure_disposition,
)
from app.v2.model_failure_episode import (
    derive_failure_episodes,
    open_failure_episode_ids,
    stable_failure_episode_id,
)
from app.v2.model_context_compaction import encode_known_events_v6
from app.v2.model_context_contract import (
    MODEL_CONTEXT_SCHEMA_VERSION,
    PROMPT_TEMPLATE_VERSION,
)
from app.v2.model_generation_policy_contract import (
    V2ModelGenerationPolicyContractError,
    current_model_generation_policy_contract,
    freeze_model_generation_policy_contract,
    is_supported_model_generation_policy_contract,
    resolve_model_generation_action_policy,
    resolve_model_generation_policy_contract,
)
from app.v2.live_runtime import _audience_targets
from app.v2.protocol import V2LiveProtocolError, audio_frame
from app.v2.public_projection import (
    V2PublicProjectionError,
    project_public_player_seats,
    project_public_role_assignment_status,
    project_public_rule_snapshot,
)
from app.v2.repository import V2GameCanceled, V2PresentationIdentity
from app.v2.role_assignment import V2RoleAssignmentError, assign_private_roles
from app.v2.tts_client import (
    _AUDIO_SERVER,
    _CONNECTION_STARTED,
    _FULL_SERVER,
    _SESSION_FINISHED,
    _START_SESSION,
    _TASK_REQUEST,
    _WITH_EVENT,
    V2TtsClient,
    _TtsFrame,
    _decode_frame,
    _encode_event,
    _receive,
)
from app.v2.voice_recorder import V2VoiceRecorder, V2VoiceRecordingError


def _empty_v12_known_events() -> dict[str, Any]:
    return encode_known_events_v6(
        {
            "schema_version": 5,
            "events": [],
            "questions": [],
            "relations": [],
        }
    )


def _failure_episode_event(
    record_seq: int,
    event_type: str,
    *,
    payload: dict[str, Any],
    game_id: str = "v2_game_episode",
    run_id: str = "v2_run_episode",
) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "run_id": run_id,
        "event_id": record_seq,
        "record_seq": record_seq,
        "event_type": event_type,
        "payload": payload,
    }


def test_v2_failure_episode_id_and_unresolved_pre_provider_failure_are_stable() -> None:
    episode_id = stable_failure_episode_id(
        game_id="v2_game_episode",
        run_id="v2_run_episode",
        action_id="v2_action_episode",
        retry_cycle=1,
        first_failed_attempt_id="v2_model_episode_1",
    )
    events = [
        _failure_episode_event(
            1,
            "model_request_failed",
            payload={
                "action_id": "v2_action_episode",
                "attempt_id": "v2_model_episode_1",
                "retry_cycle": 1,
                "failure_code": "model_not_configured",
                "failure_episode_id": episode_id,
                "audience": "player_private",
            },
        )
    ]

    episodes = derive_failure_episodes(events)

    assert (
        stable_failure_episode_id(
            game_id="v2_game_episode",
            run_id="v2_run_episode",
            action_id="v2_action_episode",
            retry_cycle=1,
            first_failed_attempt_id="v2_model_episode_1",
        )
        == episode_id
    )
    assert len(episodes) == 1
    assert episodes[0].resolution == "unresolved"
    assert episodes[0].invariant_errors == ()
    assert episodes[0].source_attempt_ids == ("v2_model_episode_1",)
    assert open_failure_episode_ids(events) == (episode_id,)


def test_v2_failure_episode_derives_accepted_retry_success() -> None:
    episode_id = stable_failure_episode_id(
        game_id="v2_game_episode",
        run_id="v2_run_episode",
        action_id="v2_action_episode",
        retry_cycle=1,
        first_failed_attempt_id="v2_model_episode_1",
    )
    common = {
        "action_id": "v2_action_episode",
        "retry_cycle": 1,
        "failure_episode_id": episode_id,
        "audience": "player_private",
    }
    events = [
        _failure_episode_event(
            1,
            "model_request_started",
            payload={
                **{key: value for key, value in common.items() if key != "failure_episode_id"},
                "attempt_id": "v2_model_episode_1",
            },
        ),
        _failure_episode_event(
            2,
            "model_request_failed",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "failure_code": "model_empty_stream",
            },
        ),
        _failure_episode_event(
            3,
            "model_retry_scheduled",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "next_attempt_id": "v2_model_episode_2",
            },
        ),
        _failure_episode_event(
            4,
            "model_request_started",
            payload={
                **common,
                "attempt_id": "v2_model_episode_2",
                "retry_of_attempt_id": "v2_model_episode_1",
            },
        ),
        _failure_episode_event(
            5,
            "model_response_received",
            payload={
                **common,
                "attempt_id": "v2_model_episode_2",
                "application_validation_result": "accepted",
            },
        ),
    ]

    episode = derive_failure_episodes(events)[0]

    assert episode.resolution == "automatic_retry_success"
    assert episode.resolution_event_record_seq == 5
    assert episode.resolution_updated_at_record_seq == 5
    assert episode.invariant_errors == ()
    assert episode.source_attempt_ids == (
        "v2_model_episode_1",
        "v2_model_episode_2",
    )
    assert open_failure_episode_ids(events) == ()


def test_v2_failure_episode_rejects_accepted_response_for_failed_attempt() -> None:
    episode_id = stable_failure_episode_id(
        game_id="v2_game_episode",
        run_id="v2_run_episode",
        action_id="v2_action_episode",
        retry_cycle=1,
        first_failed_attempt_id="v2_model_episode_1",
    )
    common = {
        "action_id": "v2_action_episode",
        "retry_cycle": 1,
        "audience": "player_private",
    }
    events = [
        _failure_episode_event(
            1,
            "model_request_started",
            payload={**common, "attempt_id": "v2_model_episode_1"},
        ),
        _failure_episode_event(
            2,
            "model_request_failed",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "failure_code": "model_empty_stream",
                "failure_episode_id": episode_id,
            },
        ),
        _failure_episode_event(
            3,
            "model_response_received",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "failure_episode_id": episode_id,
                "application_validation_result": "accepted",
            },
        ),
    ]

    episode = derive_failure_episodes(events)[0]

    assert episode.resolution == "invariant_conflict"
    assert "response_attempt_already_failed" in episode.invariant_errors
    assert "response_lineage_discontinuous" in episode.invariant_errors


def test_v2_failure_episode_rejects_retry_schedule_before_failure() -> None:
    episode_id = stable_failure_episode_id(
        game_id="v2_game_episode",
        run_id="v2_run_episode",
        action_id="v2_action_episode",
        retry_cycle=1,
        first_failed_attempt_id="v2_model_episode_1",
    )
    common = {
        "action_id": "v2_action_episode",
        "retry_cycle": 1,
        "audience": "player_private",
    }
    events = [
        _failure_episode_event(
            1,
            "model_request_started",
            payload={**common, "attempt_id": "v2_model_episode_1"},
        ),
        _failure_episode_event(
            2,
            "model_retry_scheduled",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "next_attempt_id": "v2_model_episode_2",
                "failure_episode_id": episode_id,
            },
        ),
        _failure_episode_event(
            3,
            "model_request_failed",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "failure_code": "model_empty_stream",
                "failure_episode_id": episode_id,
            },
        ),
    ]

    episode = derive_failure_episodes(events)[0]

    assert episode.resolution == "invariant_conflict"
    assert "retry_schedule_precedes_failure" in episode.invariant_errors


def test_v2_failure_episode_rejects_retry_start_with_wrong_predecessor() -> None:
    episode_id = stable_failure_episode_id(
        game_id="v2_game_episode",
        run_id="v2_run_episode",
        action_id="v2_action_episode",
        retry_cycle=1,
        first_failed_attempt_id="v2_model_episode_1",
    )
    common = {
        "action_id": "v2_action_episode",
        "retry_cycle": 1,
        "audience": "player_private",
    }
    events = [
        _failure_episode_event(
            1,
            "model_request_started",
            payload={**common, "attempt_id": "v2_model_episode_1"},
        ),
        _failure_episode_event(
            2,
            "model_request_failed",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "failure_code": "model_empty_stream",
                "failure_episode_id": episode_id,
            },
        ),
        _failure_episode_event(
            3,
            "model_retry_scheduled",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "next_attempt_id": "v2_model_episode_2",
                "failure_episode_id": episode_id,
            },
        ),
        _failure_episode_event(
            4,
            "model_request_started",
            payload={
                **common,
                "attempt_id": "v2_model_episode_2",
                "retry_of_attempt_id": "v2_model_wrong",
                "failure_episode_id": episode_id,
            },
        ),
    ]

    episode = derive_failure_episodes(events)[0]

    assert episode.resolution == "invariant_conflict"
    assert "physical_start_retry_of_mismatch" in episode.invariant_errors


def test_v2_failure_episode_rejects_duplicate_retry_successor() -> None:
    episode_id = stable_failure_episode_id(
        game_id="v2_game_episode",
        run_id="v2_run_episode",
        action_id="v2_action_episode",
        retry_cycle=1,
        first_failed_attempt_id="v2_model_episode_1",
    )
    common = {
        "action_id": "v2_action_episode",
        "retry_cycle": 1,
        "audience": "player_private",
    }
    events = [
        _failure_episode_event(
            1,
            "model_request_started",
            payload={**common, "attempt_id": "v2_model_episode_1"},
        ),
        _failure_episode_event(
            2,
            "model_request_failed",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "failure_code": "model_empty_stream",
                "failure_episode_id": episode_id,
            },
        ),
        _failure_episode_event(
            3,
            "model_retry_scheduled",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "next_attempt_id": "v2_model_episode_2",
                "failure_episode_id": episode_id,
            },
        ),
        _failure_episode_event(
            4,
            "model_retry_scheduled",
            payload={
                **common,
                "attempt_id": "v2_model_unrelated",
                "next_attempt_id": "v2_model_episode_2",
                "failure_episode_id": episode_id,
            },
        ),
    ]

    episode = derive_failure_episodes(events)[0]

    assert episode.resolution == "invariant_conflict"
    assert "duplicate_retry_successor" in episode.invariant_errors


def test_v2_failure_episode_requires_technical_support_and_action_success_pair() -> None:
    episode_id = stable_failure_episode_id(
        game_id="v2_game_episode",
        run_id="v2_run_episode",
        action_id="v2_action_episode",
        retry_cycle=1,
        first_failed_attempt_id="v2_model_episode_1",
    )
    common = {
        "action_id": "v2_action_episode",
        "retry_cycle": 1,
        "failure_episode_id": episode_id,
        "audience": "player_private",
    }
    events = [
        _failure_episode_event(
            1,
            "model_request_started",
            payload={
                **{key: value for key, value in common.items() if key != "failure_episode_id"},
                "attempt_id": "v2_model_episode_1",
            },
        ),
        _failure_episode_event(
            2,
            "model_request_failed",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "failure_code": "model_total_timeout",
            },
        ),
        _failure_episode_event(
            3,
            "action_skipped_technical",
            payload={
                "action_id": "v2_action_episode",
                "failure_episode_id": episode_id,
                "audience": "public",
            },
        ),
    ]

    assert derive_failure_episodes(events)[0].resolution == "unresolved"

    events.append(
        _failure_episode_event(
            4,
            "action_succeeded",
            payload={
                "action_id": "v2_action_episode",
                "failure_episode_id": episode_id,
                "technical_outcome_record_seq": 3,
                "audience": "public",
            },
        )
    )
    episode = derive_failure_episodes(events)[0]

    assert episode.resolution == "technical_skip"
    assert episode.resolution_event_record_seq == 4
    assert episode.supporting_event_record_seq == 3
    assert episode.invariant_errors == ()


def test_v2_failure_episode_reports_terminal_conflict_without_guessing_priority() -> None:
    episode_id = stable_failure_episode_id(
        game_id="v2_game_episode",
        run_id="v2_run_episode",
        action_id="v2_action_episode",
        retry_cycle=1,
        first_failed_attempt_id="v2_model_episode_1",
    )
    common = {
        "action_id": "v2_action_episode",
        "retry_cycle": 1,
        "failure_episode_id": episode_id,
        "audience": "player_private",
    }
    events = [
        _failure_episode_event(
            1,
            "model_request_started",
            payload={
                **{key: value for key, value in common.items() if key != "failure_episode_id"},
                "attempt_id": "v2_model_episode_1",
            },
        ),
        _failure_episode_event(
            2,
            "model_request_failed",
            payload={
                **common,
                "attempt_id": "v2_model_episode_1",
                "failure_code": "model_empty_stream",
            },
        ),
        _failure_episode_event(
            3,
            "model_action_paused",
            payload={
                "action_id": "v2_action_episode",
                "failure_episode_id": episode_id,
                "audience": "player_private",
            },
        ),
        _failure_episode_event(
            4,
            "game_canceled",
            payload={
                "canceled_failure_episode_ids": [episode_id],
                "audience": "all",
            },
        ),
    ]

    episode = derive_failure_episodes(events)[0]

    assert episode.resolution == "invariant_conflict"
    assert "mutually_exclusive_terminal_evidence" in episode.invariant_errors
    assert [ref.record_seq for ref in episode.terminal_event_refs] == [3, 4]


def test_v2_model_retry_policy_uses_extended_timeouts_by_default() -> None:
    policy = V2ModelRetryPolicy()

    assert policy.max_attempts == 3
    assert policy.attempt_total_seconds == 180.0
    assert policy.action_total_seconds == 300.0


def test_model_generation_policy_v1_is_frozen_observe_only_and_legacy_missing_is_disabled() -> None:
    expected = {
        "schema_version": 1,
        "classification_version": 1,
        "enforcement": "observe_only",
        "reasoning_parameter_mode": "inherit_frozen_model_configuration",
        "default_profile": "strategic_full",
        "profiles": {
            "strategic_full": {
                "reasoning_only_timeout_ms": None,
                "timeout_max_attempts": 2,
            },
            "recoverable_public_speech": {
                "reasoning_only_timeout_ms": 180_000,
                "timeout_max_attempts": 1,
            },
            "isolated_auxiliary": {
                "reasoning_only_timeout_ms": 240_000,
                "timeout_max_attempts": 1,
            },
        },
        "action_profiles": {
            "day_debate_speech": "recoverable_public_speech",
            "sheriff_campaign_speech": "recoverable_public_speech",
            "sheriff_pk_speech": "recoverable_public_speech",
            "exile_pk_speech": "recoverable_public_speech",
            "exile_last_words": "recoverable_public_speech",
            "first_night_last_words": "recoverable_public_speech",
            "private_round_memory": "isolated_auxiliary",
        },
    }

    assert current_model_generation_policy_contract() == expected
    assert resolve_model_generation_policy_contract({}) is None
    frozen = freeze_model_generation_policy_contract(
        {
            "rule_set": {"id": "classic"},
            "model_generation_policy_contract": {"schema_version": 999},
        }
    )
    assert frozen["model_generation_policy_contract"] == expected
    resolved = resolve_model_generation_policy_contract(frozen)
    assert resolved == expected
    assert resolved is not frozen["model_generation_policy_contract"]
    assert is_supported_model_generation_policy_contract(resolved) is True
    assert (
        project_public_rule_snapshot(
            {
                "model_context_contract": {"model_context_schema_version": 11},
                "model_generation_policy_contract": expected,
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(schema_version=2),
        lambda value: value.update(enforcement="enabled"),
        lambda value: value.update(extra=True),
        lambda value: value["profiles"]["strategic_full"].update(timeout_max_attempts=True),
        lambda value: value["profiles"]["strategic_full"].update(reasoning_only_timeout_ms=1),
        lambda value: value["profiles"]["recoverable_public_speech"].update(
            reasoning_only_timeout_ms=0
        ),
        lambda value: value["profiles"]["isolated_auxiliary"].update(timeout_max_attempts=4),
        lambda value: value["action_profiles"].pop("private_round_memory"),
    ],
)
def test_model_generation_policy_present_unknown_or_malformed_fails_closed(
    mutate: Any,
) -> None:
    contract = current_model_generation_policy_contract()
    mutate(contract)

    assert is_supported_model_generation_policy_contract(contract) is False
    with pytest.raises(
        V2ModelGenerationPolicyContractError,
        match="unsupported_model_generation_policy_contract",
    ):
        resolve_model_generation_policy_contract({"model_generation_policy_contract": contract})


def test_frozen_model_generation_policy_resolves_after_current_emitter_threshold_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = freeze_model_generation_policy_contract({})
    original = frozen["model_generation_policy_contract"]
    changed = current_model_generation_policy_contract()
    changed["profiles"]["recoverable_public_speech"]["reasoning_only_timeout_ms"] = 195_000
    changed["profiles"]["isolated_auxiliary"]["reasoning_only_timeout_ms"] = 255_000
    changed["profiles"]["recoverable_public_speech"]["timeout_max_attempts"] = 2
    monkeypatch.setattr(
        "app.v2.model_generation_policy_contract.current_model_generation_policy_contract",
        lambda: changed,
    )

    assert resolve_model_generation_policy_contract(frozen) == original
    assert (
        freeze_model_generation_policy_contract({})["model_generation_policy_contract"] == changed
    )
    resolved = resolve_model_generation_action_policy(
        original,
        action_type="day_debate_speech",
    )
    assert resolved.reasoning_only_timeout_ms == 180_000
    assert resolved.timeout_max_attempts == 1


@pytest.mark.parametrize(
    ("action_type", "profile"),
    [
        ("day_debate_speech", "recoverable_public_speech"),
        ("sheriff_campaign_speech", "recoverable_public_speech"),
        ("sheriff_pk_speech", "recoverable_public_speech"),
        ("exile_pk_speech", "recoverable_public_speech"),
        ("exile_last_words", "recoverable_public_speech"),
        ("first_night_last_words", "recoverable_public_speech"),
        ("private_round_memory", "isolated_auxiliary"),
    ],
)
def test_model_generation_policy_resolves_explicit_action_profiles(
    action_type: str,
    profile: str,
) -> None:
    resolved = resolve_model_generation_action_policy(
        current_model_generation_policy_contract(),
        action_type=action_type,
    )

    assert resolved.status == "supported"
    assert resolved.enforcement == "observe_only"
    assert resolved.profile == profile
    assert resolved.source == "explicit_action_profile"
    assert resolved.schema_version == 1
    assert resolved.classification_version == 1
    assert resolved.reasoning_parameter_mode == ("inherit_frozen_model_configuration")
    assert resolved.reasoning_only_timeout_ms == (
        240_000 if profile == "isolated_auxiliary" else 180_000
    )
    assert resolved.timeout_max_attempts == 1


@pytest.mark.parametrize(
    "action_type",
    [
        "exile_vote",
        "ability_guard.protect_decision",
        "werewolf_self_explosion",
        "unknown_future_action",
    ],
)
def test_model_generation_policy_unknown_actions_fall_back_to_strategic_full(
    action_type: str,
) -> None:
    resolved = resolve_model_generation_action_policy(
        current_model_generation_policy_contract(),
        action_type=action_type,
    )

    assert resolved.status == "supported"
    assert resolved.enforcement == "observe_only"
    assert resolved.profile == "strategic_full"
    assert resolved.source == "default_profile"
    assert resolved.reasoning_only_timeout_ms is None
    assert resolved.timeout_max_attempts == 2


def test_model_generation_policy_legacy_missing_resolves_disabled_metadata() -> None:
    resolved = resolve_model_generation_action_policy(
        None,
        action_type="day_debate_speech",
    )

    assert resolved.status == "legacy_disabled"
    assert resolved.enforcement == "disabled"
    assert resolved.profile is None
    assert resolved.source == "legacy_missing_contract"
    assert resolved.schema_version is None
    assert resolved.classification_version is None
    assert resolved.reasoning_parameter_mode is None
    assert resolved.reasoning_only_timeout_ms is None
    assert resolved.timeout_max_attempts is None


def test_generation_policy_audit_uses_active_reasoning_elapsed_and_shadow_threshold() -> None:
    policy = resolve_model_generation_action_policy(
        current_model_generation_policy_contract(),
        action_type="day_debate_speech",
    )

    started = _model_generation_policy_audit_payload(
        policy=policy,
        action_type="day_debate_speech",
        model_provider="agent_plan",
        model_id="glm-test",
    )
    assert started["reasoning_only_elapsed_ms"] is None
    assert started["shadow_would_timeout"] is None

    completed = _model_generation_policy_audit_payload(
        policy=policy,
        action_type="day_debate_speech",
        model_provider="agent_plan",
        model_id="glm-test",
        first_token_ms=2_000,
        first_visible_text_ms=182_000,
        terminal_elapsed_ms=190_000,
    )
    assert completed == {
        "model_provider": "agent_plan",
        "model_id": "glm-test",
        "action_type": "day_debate_speech",
        "model_generation_policy_contract_status": "supported",
        "model_generation_policy_schema_version": 1,
        "model_generation_policy_classification_version": 1,
        "model_generation_policy_enforcement": "observe_only",
        "model_generation_policy_profile": "recoverable_public_speech",
        "model_generation_policy_profile_source": "explicit_action_profile",
        "model_generation_policy_reasoning_parameter_mode": ("inherit_frozen_model_configuration"),
        "reasoning_only_timeout_ms": 180_000,
        "timeout_max_attempts": 1,
        "reasoning_only_elapsed_ms": 180_000,
        "shadow_would_timeout": True,
    }


def test_generation_policy_audit_preserves_explicit_elapsed_and_legacy_null_shadow() -> None:
    assert (
        _resolved_reasoning_only_elapsed_ms(
            explicit=7,
            first_token_ms=20,
            first_visible_text_ms=30,
            terminal_elapsed_ms=40,
        )
        == 7
    )
    assert (
        _resolved_reasoning_only_elapsed_ms(
            explicit=None,
            first_token_ms=20,
            first_visible_text_ms=None,
            terminal_elapsed_ms=55,
        )
        == 35
    )
    legacy = resolve_model_generation_action_policy(
        None,
        action_type="day_debate_speech",
    )
    audit = _model_generation_policy_audit_payload(
        policy=legacy,
        action_type="day_debate_speech",
        model_provider="agent_plan",
        model_id="glm-test",
        explicit_reasoning_only_elapsed_ms=250_000,
    )
    assert audit["model_generation_policy_contract_status"] == "legacy_disabled"
    assert audit["reasoning_only_elapsed_ms"] == 250_000
    assert audit["reasoning_only_timeout_ms"] is None
    assert audit["shadow_would_timeout"] is None


def _blocking_required_target_spec() -> V2SpeechSpec:
    return V2SpeechSpec(
        action_type="ability_werewolf.attack_decision",
        phase_id="night_1",
        required_phase_state="werewolf_action_open",
        objective="选择袭击目标并说明理由。",
        success_live_state="ready",
        success_phase_state="werewolf_action_closed",
        actor_kind="player",
        actor_id="player-wolf",
        allowed_target_ids=("player-1", "player-2"),
        decision_contract=V2DecisionContract(
            kind="target",
            target_mode="required",
            speech_mode="required",
        ),
    )


def test_blocking_required_target_predicate_uses_frozen_contract_not_action_name() -> None:
    eligible = _blocking_required_target_spec()

    assert _is_blocking_required_target(eligible) is True
    assert _is_blocking_required_target(replace(eligible, action_type="unlisted_target")) is True
    assert _is_blocking_required_target(replace(eligible, defer_presentation=True)) is True
    assert _is_blocking_required_target(replace(eligible, allowed_target_ids=())) is False
    assert _is_blocking_required_target(replace(eligible, best_effort=True)) is False
    assert _is_blocking_required_target(replace(eligible, isolated_failure=True)) is False
    assert (
        _is_blocking_required_target(
            replace(
                eligible,
                decision_contract=V2DecisionContract(kind="speech"),
            )
        )
        is False
    )
    assert (
        _is_blocking_required_target(
            replace(
                eligible,
                decision_contract=V2DecisionContract(
                    kind="boolean",
                    boolean_field="withdraw",
                ),
            )
        )
        is False
    )
    assert (
        _is_blocking_required_target(
            replace(
                eligible,
                decision_contract=V2DecisionContract(
                    kind="target",
                    target_mode="optional",
                ),
            )
        )
        is False
    )


def test_effective_model_attempt_limit_only_expands_eligible_output_budget() -> None:
    eligible = _blocking_required_target_spec()
    policy = V2ModelRetryPolicy(max_attempts=3)
    exhausted = V2ModelError("model_output_budget_exhausted")
    disposition = model_failure_disposition(exhausted)

    assert disposition.category == "output_budget"
    assert (
        _effective_model_attempt_limit(
            spec=eligible,
            exc=exhausted,
            disposition=disposition,
            policy=policy,
        )
        == 3
    )
    assert (
        _effective_model_attempt_limit(
            spec=replace(eligible, isolated_failure=True),
            exc=exhausted,
            disposition=disposition,
            policy=policy,
        )
        == 2
    )
    for ineligible_contract in (
        V2DecisionContract(kind="speech"),
        V2DecisionContract(kind="boolean", boolean_field="withdraw"),
    ):
        assert (
            _effective_model_attempt_limit(
                spec=replace(eligible, decision_contract=ineligible_contract),
                exc=exhausted,
                disposition=disposition,
                policy=policy,
            )
            == 2
        )
    assert (
        _effective_model_attempt_limit(
            spec=eligible,
            exc=exhausted,
            disposition=disposition,
            policy=replace(policy, max_attempts=2),
        )
        == 2
    )

    timeout = V2ModelError("model_attempt_hard_timeout")
    assert (
        _effective_model_attempt_limit(
            spec=eligible,
            exc=timeout,
            disposition=model_failure_disposition(timeout),
            policy=policy,
        )
        == 2
    )
    transport = V2ModelError("model_transport_failed")
    assert (
        _effective_model_attempt_limit(
            spec=eligible,
            exc=transport,
            disposition=model_failure_disposition(transport),
            policy=policy,
        )
        == 3
    )


@pytest.mark.parametrize("elapsed_ms", [None, 0, -1, True])
def test_third_output_budget_window_fails_closed_for_invalid_elapsed(
    elapsed_ms: int | None,
) -> None:
    policy = V2ModelRetryPolicy(
        max_attempts=3,
        attempt_total_seconds=180,
        action_total_seconds=300,
    )
    exhausted = V2ModelError(
        "model_output_budget_exhausted",
        elapsed_ms=elapsed_ms,
    )

    assert (
        _required_retry_window_seconds(
            spec=_blocking_required_target_spec(),
            disposition=model_failure_disposition(exhausted),
            exc=exhausted,
            policy=policy,
            cycle_output_budget_failure_count=2,
        )
        == policy.attempt_total_seconds
    )


def test_only_second_cycle_output_budget_failure_requires_observed_third_window() -> None:
    policy = V2ModelRetryPolicy(
        max_attempts=3,
        attempt_total_seconds=180,
        action_total_seconds=300,
    )
    exhausted = V2ModelError(
        "model_output_budget_exhausted",
        elapsed_ms=42_500,
    )
    disposition = model_failure_disposition(exhausted)
    eligible = _blocking_required_target_spec()

    assert (
        _required_retry_window_seconds(
            spec=eligible,
            disposition=disposition,
            exc=exhausted,
            policy=policy,
            cycle_output_budget_failure_count=1,
        )
        == 0
    )
    assert (
        _required_retry_window_seconds(
            spec=eligible,
            disposition=disposition,
            exc=exhausted,
            policy=policy,
            cycle_output_budget_failure_count=2,
        )
        == 42.5
    )
    assert (
        _required_retry_window_seconds(
            spec=replace(eligible, isolated_failure=True),
            disposition=disposition,
            exc=exhausted,
            policy=policy,
            cycle_output_budget_failure_count=2,
        )
        == 0
    )


@pytest.mark.parametrize(
    ("error", "category", "max_attempts", "pausable"),
    [
        (V2ModelError("model_empty_stream"), "transport", 3, True),
        (V2ModelError("model_first_token_timeout"), "timeout", 2, True),
        (
            V2QualityError("model_decision_invalid_json", raw_response="not-json"),
            "machine_format",
            2,
            True,
        ),
        (
            V2QualityError(
                "model_decision_ambiguous_multiple_objects",
                raw_response='{"target_player_id":"seat_1"}{"target_player_id":"seat_2"}',
            ),
            "machine_format",
            2,
            True,
        ),
        (
            V2ModelError("model_provider_credentials_missing"),
            "provider_configuration",
            1,
            False,
        ),
    ],
)
def test_v2_model_failure_disposition_is_explicit(
    error: V2ModelError,
    category: str,
    max_attempts: int,
    pausable: bool,
) -> None:
    disposition = model_failure_disposition(error)

    assert disposition.category == category
    assert disposition.max_attempts == max_attempts
    assert disposition.pausable is pausable


def test_v2_required_target_validation_preserves_returned_stream_diagnostics() -> None:
    decision = V2ModelDecision(
        target_player_id=None,
        speech=None,
        provider_request_id="provider-required-target",
        first_token_ms=12,
        completed_ms=98,
        raw_response='{"target_player_id":null}',
        first_visible_text_ms=73,
        reasoning_delta_count=7,
        text_delta_count=2,
        max_inter_delta_ms=31,
        last_progress_ms=97,
        finish_reason="completed",
        provider_usage={
            "input_tokens": 100,
            "output_tokens": 20,
            "reasoning_tokens": 12,
            "total_tokens": 120,
        },
        usage_update_count=2,
        usage_conflict_observed=True,
        usage_consistency="exact",
        reasoning_only_elapsed_ms=61,
    )
    spec = V2SpeechSpec(
        action_type="exile_vote",
        phase_id="day_1",
        required_phase_state="exile_vote_open",
        objective="选择放逐目标。",
        success_live_state="ready",
        success_phase_state="exile_vote_closed",
        actor_kind="player",
        actor_id="player-1",
        decision_contract=V2DecisionContract(
            kind="target",
            speech_mode="forbidden",
            target_mode="required",
        ),
        allowed_target_ids=("player-2",),
    )

    with pytest.raises(V2QualityError) as captured:
        _validate_model_target_decision(decision, spec=spec)
    _enrich_model_error_from_decision(captured.value, decision)

    error = captured.value
    assert error.finish_reason == "completed"
    assert error.provider_usage == decision.provider_usage
    assert error.usage_update_count == 2
    assert error.usage_conflict_observed is True
    assert error.usage_consistency == "exact"
    assert error.reasoning_only_elapsed_ms == 61
    assert error.reasoning_delta_count == 7
    assert error.text_delta_count == 2
    assert error.max_inter_delta_ms == 31
    assert error.last_progress_ms == 97


def test_v2_decision_parser_repairs_one_extra_trailing_brace() -> None:
    raw = '{"explode": false}}'
    contract = {
        "kind": "boolean",
        "field": "explode",
        "speech": {"mode": "required_if_true"},
    }

    assert _decision_object(raw) == {"explode": False}
    assert _decision_repair_kind(raw, contract) == "single_trailing_brace_removed"


def test_v2_decision_parser_repairs_identical_plain_and_fenced_json() -> None:
    raw = (
        '{"target_player_id":"seat_6","decision_note":"首夜优先覆盖中置位。"}'
        "\n\n```json\n"
        "{\n"
        '  "decision_note": "首夜优先覆盖中置位。",\n'
        '  "target_player_id": "seat_6"\n'
        "}\n```"
    )
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
        "decision_note": {"mode": "optional", "max_chars": 120},
    }

    assert _decision_fields(raw, contract) == ("seat_6", None, None, None)
    assert _decision_repair_kind(raw, contract) == "duplicate_identical_json_ignored"


@pytest.mark.parametrize(
    "second",
    [
        '{"target_player_id":"seat_5","decision_note":"相同理由。"}',
        '{"target_player_id":"seat_6","decision_note":"不同理由。"}',
    ],
)
def test_v2_decision_parser_rejects_distinct_valid_json_objects(second: str) -> None:
    first = '{"target_player_id":"seat_6","decision_note":"相同理由。"}'
    raw = f"{first}\n```json\n{second}\n```"
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
        "decision_note": {"mode": "optional", "max_chars": 120},
    }

    with pytest.raises(
        V2QualityError,
        match="model_decision_ambiguous_multiple_objects",
    ):
        _decision_fields(raw, contract)


@pytest.mark.parametrize(
    "raw",
    [
        (
            '{"target_player_id":"seat_6"}\n```json\n'
            '{"model_context_schema_version":8,"known_events":{"events":[]}}\n```'
        ),
        ('{"target_player_id":"seat_6"}\n```json\n{"target_player_id":"seat_6"}\n```\n额外解释'),
        ('{"target_player_id":"seat_6"}\n```json\n{"target_player_id":"seat_6"}'),
        ('{"target_player_id":"seat_6"}{"target_player_id":"seat_6"}{"target_player_id":"seat_6"}'),
    ],
)
def test_v2_decision_parser_does_not_repair_unsafe_duplicate_shapes(raw: str) -> None:
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
    }

    with pytest.raises(V2QualityError):
        _decision_fields(raw, contract)


@pytest.mark.parametrize(
    "raw",
    [
        '{"speech":"第一句"}{"speech":"第二句"',
        '{"speech":"第一句"}\n```json\n{"speech":"第一句"',
        '{"speech":"第一句"}\n```json\n{"speech":"第一句"}\n```\n额外说明',
        '{"speech":"第一句"}{"speech":"第一句"}{"speech":"第一句"}',
    ],
)
def test_v2_speech_contract_does_not_fragment_recover_unsafe_json_documents(
    raw: str,
) -> None:
    contract = {
        "kind": "speech",
        "speech": {"mode": "required"},
    }

    with pytest.raises(V2QualityError, match="model_decision_invalid_json_document"):
        _decision_fields(raw, contract)


def _identity() -> V2PresentationIdentity:
    return V2PresentationIdentity(
        game_id="v2_game_0000000000000001",
        run_id="v2_run_0000000000000001",
        action_id="v2_action_0000000000000001",
        phase_id="opening",
        presentation_seq=1,
        presentation_id="v2_pres_0000000000000001",
        speech_id="v2_speech_0000000000000001",
        segment_index=0,
        voice_asset_id="v2_voice_0000000000000001",
        storage_key="v2_game_0000000000000001/v2_voice_0000000000000001.wav",
        subtitle_text="欢迎来到这场实时狼人杀对局。",
        audience="all",
    )


def test_v2_tts_sends_documented_explicit_dialect_in_additions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[int, dict[str, Any]]] = []
    frames = iter(
        [
            _TtsFrame(message_type=_AUDIO_SERVER, event=None, payload=b"pcm"),
            _TtsFrame(
                message_type=_FULL_SERVER,
                event=_SESSION_FINISHED,
                payload=b"",
            ),
        ]
    )

    class FakeWebsocket:
        async def close(self) -> None:
            return None

    async def connect(*_args: object, **_kwargs: object) -> FakeWebsocket:
        return FakeWebsocket()

    async def send_event(
        _websocket: object,
        event: int,
        payload: bytes,
        _session_id: str | None = None,
    ) -> None:
        sent.append((event, json.loads(payload)))

    async def expect_event(*_args: object, **_kwargs: object) -> _TtsFrame:
        return _TtsFrame(
            message_type=_FULL_SERVER,
            event=_CONNECTION_STARTED,
            payload=b"",
        )

    async def receive(*_args: object, **_kwargs: object) -> _TtsFrame:
        return next(frames)

    monkeypatch.setattr(v2_tts.websockets, "connect", connect)
    monkeypatch.setattr(v2_tts, "_send_event", send_event)
    monkeypatch.setattr(v2_tts, "_expect_event", expect_event)
    monkeypatch.setattr(v2_tts, "_receive", receive)
    client = V2TtsClient(
        enabled=True,
        api_key="key",
        resource_id="seed-tts-2.0",
        ws_url="wss://example.test",
        speaker="zh_female_vv_uranus_bigtts",
        sample_rate=24000,
        first_chunk_seconds=1,
        idle_seconds=1,
    )

    async def collect_audio() -> list[bytes]:
        return [
            chunk
            async for chunk in client.synthesize(
                text="这是一句四川话测试。",
                attempt_id="v2_tts_test",
                dialect="northeast",
            )
        ]

    audio = asyncio.run(collect_audio())

    assert audio == [b"pcm"]
    start_session = next(payload for event, payload in sent if event == _START_SESSION)
    assert json.loads(start_session["req_params"]["additions"]) == {"explicit_dialect": "dongbei"}


def test_directed_audience_merges_public_and_private_stage_events_only() -> None:
    assert _audience_targets("all") == (
        "player_public",
        "spectator_directed",
        "spectator_god_view",
    )
    assert _audience_targets("public") == (
        "player_public",
        "spectator_directed",
    )
    assert _audience_targets("god_view") == (
        "spectator_directed",
        "spectator_god_view",
    )
    assert _audience_targets("director") == ("spectator_directed",)


def test_director_scene_projection_exposes_context_without_raw_action_data() -> None:
    scene = project_director_scene(
        phase_id="first_night",
        phase_state="night_running",
        action_context={
            "action_id": "v2_action_0000000000000001",
            "action_type": "seer_check",
            "ability_id": "seer_check",
            "actor": {"kind": "player", "id": "player-3"},
            "prompt": "must-not-leak",
            "model_id": "must-not-leak",
            "private_state": {"must": "not-leak"},
        },
    )

    assert scene.model_dump(mode="json") == {
        "scene_kind": "seer",
        "action_id": "v2_action_0000000000000001",
        "action_type": "seer_check",
        "ability_id": "seer_check",
        "actor_player_id": "player-3",
    }
    public_scene = project_director_scene(
        phase_id="day_2",
        phase_state="public_discussion_open",
        action_context={
            "action_id": "v2_action_0000000000000002",
            "action_type": "werewolf_self_explosion",
            "actor": {"kind": "player", "id": "player-5"},
        },
    )
    assert public_scene.scene_kind == "public_stage"


def test_speech_validation_only_requires_non_empty_text() -> None:
    speech = "“先听我说完。然后我们再决定！”\n#这是自然发言的一部分"
    assert _required_speech(f"  {speech}  ", error_code="invalid") == speech
    with pytest.raises(V2QualityError, match="invalid"):
        _required_speech("  \n  ", error_code="invalid")


def test_decision_fields_accept_multi_sentence_text_and_extra_fields() -> None:
    raw = """模型结果如下：
```json
{"target_player_id":" player-2 ","speech":"先听二号怎么说。之后我再判断！","note":"ignored"}
```"""
    assert _decision_fields(raw, _target_contract()) == (
        "player-2",
        "先听二号怎么说。之后我再判断！",
        None,
        None,
    )


def test_decision_fields_ignore_scalar_identity_metadata_from_real_response() -> None:
    raw = json.dumps(
        {
            "target_player_id": "seat_9",
            "speech": "这一票投给9号。",
            "self_identity": "villager",
        },
        ensure_ascii=False,
    )

    assert _decision_fields(raw, _target_contract()) == (
        "seat_9",
        "这一票投给9号。",
        None,
        None,
    )


def test_decision_fields_repairs_structural_smart_quote_from_real_response() -> None:
    raw = """```json
{
  "target_player_id": "system-player-03",
  "speech": "3号周野，你先把自己的逻辑补齐。你到底想带什么节奏？”
}
```"""

    assert _decision_fields(raw, _target_contract()) == (
        "system-player-03",
        "3号周野，你先把自己的逻辑补齐。你到底想带什么节奏？",
        None,
        None,
    )


def test_decision_fields_keep_only_fundamental_failures() -> None:
    assert _decision_fields(
        "我先保留意见，再听后面的发言。",
        _target_contract(),
    ) == (
        None,
        "我先保留意见，再听后面的发言。",
        None,
        None,
    )
    assert _decision_fields(
        '{"speech":"我先保留意见。"}',
        _target_contract(),
    ) == (
        None,
        "我先保留意见。",
        None,
        None,
    )
    with pytest.raises(V2QualityError, match="model_decision_invalid_target"):
        _decision_fields(
            '{"target_player_id":3,"speech":"我投三号。"}',
            _target_contract(),
        )
    with pytest.raises(V2QualityError, match="model_decision_invalid_speech"):
        _decision_fields(
            '{"target_player_id":null,"speech":"  "}',
            _target_contract(),
        )


def test_decision_fields_recovers_clean_speech_from_truncated_json_wrapper() -> None:
    raw = '{"speech":"我是7号，今天站边12号。\\n2号昨天的票型需要解释，我暂时不会跟票'
    assert _decision_fields(raw, {"kind": "speech", "speech": {"mode": "required"}}) == (
        None,
        "我是7号，今天站边12号。\n2号昨天的票型需要解释，我暂时不会跟票",
        None,
        None,
    )


def test_decision_fields_recovers_target_and_speech_from_truncated_json() -> None:
    raw = '{"target_player_id":"seat_4","speech":"我选择查验4号，因为他的站边变化最明显'
    assert _decision_fields(raw, _target_contract()) == (
        "seat_4",
        "我选择查验4号，因为他的站边变化最明显",
        None,
        None,
    )


def test_decision_fields_extracts_speech_from_safe_nested_output_wrapper() -> None:
    raw = json.dumps(
        {
            "action_id": "v2_action_real",
            "action_type": "sheriff_campaign_speech",
            "output": {"speech": "8号竞选警长，我会把票型和站边讲清楚。"},
            "actor_id": "seat_8",
        },
        ensure_ascii=False,
    )

    assert _decision_fields(
        raw,
        {"kind": "speech", "speech": {"mode": "required"}},
    ) == (
        None,
        "8号竞选警长，我会把票型和站边讲清楚。",
        None,
        None,
    )


def test_decision_fields_extracts_target_from_safe_nested_decision_wrapper() -> None:
    raw = json.dumps(
        {
            "action_id": "v2_action_real",
            "action_type": "ability_witch.heal_decision",
            "actor": {"kind": "player", "id": "seat_7"},
            "decision": {"target_player_id": "seat_1"},
            "speech": None,
        },
        ensure_ascii=False,
    )

    assert _decision_fields(
        raw,
        {
            "kind": "target",
            "target_policy": {"mode": "optional"},
            "speech": {"mode": "optional"},
        },
    ) == (
        "seat_1",
        None,
        None,
        None,
    )


def test_decision_fields_extracts_target_from_exact_response_wrapper() -> None:
    raw = json.dumps(
        {
            "response": {
                "target_player_id": "seat_1",
                "decision_note": "警徽票给1号。",
            }
        },
        ensure_ascii=False,
    )
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
        "decision_note": {"mode": "optional", "max_chars": 80},
    }

    assert _decision_fields(raw, contract) == ("seat_1", None, None, None)
    assert _decision_repair_kind(raw, contract) == "response_wrapper_recovered"


@pytest.mark.parametrize(
    ("raw", "contract", "expected"),
    [
        (
            '{"response":{"speech":"我会继续听取后续发言。"}}',
            {"kind": "speech", "speech": {"mode": "required"}},
            (None, "我会继续听取后续发言。", None, None),
        ),
        (
            '{"response":{"withdraw":false,"speech":"我继续参选。"}}',
            {
                "kind": "boolean",
                "field": "withdraw",
                "speech": {"mode": "required"},
            },
            (None, "我继续参选。", "withdraw", False),
        ),
    ],
)
def test_decision_fields_recovers_exact_response_wrapper_for_all_contract_kinds(
    raw: str,
    contract: dict[str, Any],
    expected: tuple[str | None, str | None, str | None, bool | None],
) -> None:
    assert _decision_fields(raw, contract) == expected
    assert _decision_repair_kind(raw, contract) == "response_wrapper_recovered"


@pytest.mark.parametrize(
    "response",
    [
        {
            "kind": "target",
            "target_player_id": "seat_1",
            "speech": {"mode": "forbidden"},
        },
        {
            "target_player_id": "seat_1",
            "target_policy": {"mode": "required"},
        },
        {"target_player_id": "seat_1", "speech": "不应进入私密投票"},
        {"target_player_id": "seat_1", "speech": None},
    ],
)
def test_decision_fields_rejects_response_wrapper_contract_echo(
    response: dict[str, Any],
) -> None:
    raw = json.dumps({"response": response}, ensure_ascii=False)
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
        "decision_note": {"mode": "optional", "max_chars": 80},
    }

    with pytest.raises(
        V2QualityError,
        match="model_decision_structured_speech_leak",
    ):
        _decision_fields(raw, contract)


@pytest.mark.parametrize(
    "raw",
    [
        '{"response":null}',
        '{"response":{}}',
        '{"response":{"target_player_id":"seat_1"},"target_player_id":"seat_1"}',
        '{"response":{"target_player_id":"seat_1"},"output":{"target_player_id":"seat_1"}}',
        '{"response":{"response":{"target_player_id":"seat_1"}}}',
    ],
)
def test_decision_fields_rejects_unsafe_response_wrapper_shapes(raw: str) -> None:
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
    }

    with pytest.raises(
        V2QualityError,
        match="model_decision_structured_speech_leak",
    ):
        _decision_fields(raw, contract)


def test_decision_fields_rejects_long_truncated_response_wrapper_without_fragment_recovery() -> (
    None
):
    raw = "x" * 1_601 + '{"response":{"target_player_id":"seat_1"'
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
    }

    with pytest.raises(
        V2QualityError,
        match="model_decision_structured_speech_leak",
    ):
        _decision_fields(raw, contract)


@pytest.mark.parametrize(
    "raw",
    [
        '｛＂response＂：｛"target_player_id":"seat_1"',
        "x" * 1_601 + '{“response”:{"target_player_id":"seat_1"',
        '{"Response":{"target_player_id":"seat_1"',
        '{"\\u0072esponse":{"target_player_id":"seat_1"',
    ],
)
def test_decision_fields_rejects_compatibility_response_wrapper_without_fragment_recovery(
    raw: str,
) -> None:
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
    }

    with pytest.raises(
        V2QualityError,
        match="model_decision_structured_speech_leak",
    ):
        _decision_fields(raw, contract)


@pytest.mark.parametrize(
    ("raw", "contract"),
    [
        (
            '{"wrapper":{"speech":"嵌套发言"',
            {"kind": "speech", "speech": {"mode": "required"}},
        ),
        (
            '{"wrapper":{"withdraw":true,"speech":"嵌套退水"',
            {
                "kind": "boolean",
                "field": "withdraw",
                "speech": {"mode": "required_if_true"},
            },
        ),
    ],
)
def test_decision_fields_rejects_nested_truncated_fragments_for_all_contract_kinds(
    raw: str,
    contract: dict[str, Any],
) -> None:
    with pytest.raises(
        V2QualityError,
        match="model_decision_structured_speech_leak",
    ):
        _decision_fields(raw, contract)


def test_machine_format_failure_result_requires_complete_lineage() -> None:
    with pytest.raises(ValueError, match="machine-format failure lineage is required"):
        V2ActionFailure(
            code="model_decision_invalid_json",
            category="machine_format",
            terminal_attempt_id="v2_model_terminal",
            machine_format_failure_count=2,
        )

    failure = V2ActionFailure(
        code="model_decision_invalid_json",
        category="machine_format",
        terminal_attempt_id="v2_model_terminal",
        machine_format_failure_count=2,
        last_machine_format_attempt_id="v2_model_terminal",
        last_machine_format_failure_code="model_decision_invalid_json",
    )
    with pytest.raises(ValueError, match="failed action result requires an action_id"):
        V2ActionResult(failure=failure)


def test_output_budget_failure_result_requires_independent_lineage() -> None:
    with pytest.raises(ValueError, match="output-budget failure lineage is required"):
        V2ActionFailure(
            code="model_output_budget_exhausted",
            category="output_budget",
            terminal_attempt_id="v2_model_terminal",
            output_budget_failure_count=2,
        )

    failure = V2ActionFailure(
        code="model_output_budget_exhausted",
        category="output_budget",
        terminal_attempt_id="v2_model_terminal",
        output_budget_failure_count=2,
        last_output_budget_attempt_id="v2_model_terminal",
        last_output_budget_failure_code="model_output_budget_exhausted",
    )
    assert failure.machine_format_failure_count == 0


def test_decision_prompt_requires_flat_json_and_omits_forbidden_speech_from_example() -> None:
    context = {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "task": {"type": "sheriff_vote", "at_seq": 42, "round_no": 1},
        "self": {},
        "rules": {},
        "state": {"as_of_seq": 42, "current_round_no": 1},
        "known_events": _empty_v12_known_events(),
        "persona": {},
        "candidates": [{"player_id": "seat_1", "seat": 1, "display_name": "1号"}],
        "response": {
            "kind": "target",
            "presentation_kind": "private_vote",
            "speech": {"mode": "forbidden"},
            "decision_note": {"mode": "optional", "max_chars": 80},
            "target_policy": {"mode": "required", "candidate_source": "candidates"},
        },
        "player_reference_format": "seat_N",
    }

    prompt = _decision_model_input(context)[0]["content"][0]["text"]

    assert "response 仅用于描述本次输出合同，不是输出包装字段" in prompt
    assert "不得使用 response、output 或 decision 包装层" in prompt
    assert (
        '本动作合格输出示例：{"target_player_id":"<candidate_player_id>","decision_note"' in prompt
    )
    example = prompt.split("本动作合格输出示例：", 1)[1].split("。只输出", 1)[0]
    assert '"speech"' not in example


def test_historical_v11_decision_prompt_fails_closed() -> None:
    context = {
        "model_context_schema_version": 11,
        "prompt_template_version": 3,
        "task": {"type": "sheriff_vote", "at_seq": 42, "round_no": 1},
        "self": {},
        "rules": {},
        "state": {"as_of_seq": 42, "current_round_no": 1},
        "known_events": {
            "schema_version": 5,
            "events": [],
            "questions": [],
            "relations": [],
        },
        "persona": {},
        "candidates": [{"player_id": "seat_1", "seat": 1, "display_name": "1号"}],
        "response": {
            "kind": "target",
            "presentation_kind": "private_vote",
            "speech": {"mode": "forbidden"},
            "target_policy": {"mode": "required", "candidate_source": "candidates"},
        },
        "player_reference_format": "seat_N",
    }

    with pytest.raises(V2ModelError, match="model_prompt_template_unsupported"):
        _decision_model_input(context)


def test_v5_boolean_prompt_shows_both_values_without_strategy_anchor() -> None:
    context = {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "task": {"type": "sheriff_withdraw", "at_seq": 42, "round_no": 1},
        "self": {},
        "rules": {},
        "state": {"as_of_seq": 42, "current_round_no": 1},
        "known_events": _empty_v12_known_events(),
        "persona": {},
        "candidates": [],
        "response": {
            "kind": "boolean",
            "field": "withdraw",
            "speech": {"mode": "required_if_true"},
        },
        "player_reference_format": "seat_N",
    }

    prompt = _decision_model_input(context)[0]["content"][0]["text"]

    assert "以下示例仅示范格式，不代表任何策略选择" in prompt
    assert '{"withdraw":true,"speech":"本次动作要求的自然中文"}' in prompt
    assert '{"withdraw":false}' in prompt


def test_decision_fields_extracts_speech_from_safe_metadata_wrapper() -> None:
    raw = json.dumps(
        {
            "schema_version": 1,
            "action_id": "v2_action_real",
            "action_type": "day_debate_speech",
            "speech": "12号接着盘，先把上一轮票型摆出来。",
        },
        ensure_ascii=False,
    )

    assert _decision_fields(
        raw,
        {"kind": "speech", "speech": {"mode": "required"}},
    ) == (
        None,
        "12号接着盘，先把上一轮票型摆出来。",
        None,
        None,
    )


def test_decision_fields_ignores_structured_metadata_when_output_fields_are_valid() -> None:
    raw = json.dumps(
        {
            "target_player_id": "seat_3",
            "speech": "今晚建议选择3号。",
            "self_identity": {
                "player_id": "seat_1",
                "role_key": "werewolf",
                "team": "werewolves",
            },
        },
        ensure_ascii=False,
    )

    assert _decision_fields(raw, _target_contract()) == (
        "seat_3",
        "今晚建议选择3号。",
        None,
        None,
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"speech":"{\\"schema_version\\":1,\\"action_id\\":\\"v2_action_echo\\"}"}',
        '```json\n{"schema_version":1,"output_contract":{"kind":"speech"}',
    ],
)
def test_decision_fields_rejects_structured_context_as_broadcast_speech(
    raw: str,
) -> None:
    with pytest.raises(
        V2QualityError,
        match="model_decision_structured_speech_leak",
    ):
        _decision_fields(raw, {"kind": "speech", "speech": {"mode": "required"}})


def test_boolean_decisions_use_semantic_field_and_speech_policy() -> None:
    withdraw_contract = _boolean_contract("withdraw", "required")
    assert _decision_fields(
        '{"withdraw":true,"speech":"9号选择退水。"}',
        withdraw_contract,
    ) == (None, "9号选择退水。", "withdraw", True)
    assert _decision_fields(
        '{"withdraw":false,"speech":"9号不退水，继续参选。"}',
        withdraw_contract,
    ) == (None, "9号不退水，继续参选。", "withdraw", False)

    for raw in (
        '{"speech":"9号选择退水。"}',
        '{"withdraw":"true","speech":"9号选择退水。"}',
        '{"withdraw":null,"speech":"9号选择退水。"}',
    ):
        with pytest.raises(V2QualityError, match="model_decision_invalid_boolean"):
            _decision_fields(raw, withdraw_contract)
    with pytest.raises(V2QualityError, match="model_decision_invalid_speech"):
        _decision_fields(
            '{"withdraw":true,"speech":"  "}',
            withdraw_contract,
        )


def test_boolean_decision_recovers_real_truncated_json_response() -> None:
    raw = '{"run_for_sheriff":true,"speech":"9号上警。我会把发言顺序和矛盾一条条捋清楚。"'

    assert _decision_fields(
        raw,
        _boolean_contract("run_for_sheriff", "required"),
    ) == (
        None,
        "9号上警。我会把发言顺序和矛盾一条条捋清楚。",
        "run_for_sheriff",
        True,
    )


@pytest.mark.parametrize(
    ("raw", "expected_speech"),
    [
        (
            '{"run_for_sheriff"：false，"speech"："12号不上警，先听发言。"}',
            "12号不上警，先听发言。",
        ),
        (
            '{"run_for_sheriff": false, "speech："我是12号，这轮不上警。"}',
            "我是12号，这轮不上警。",
        ),
    ],
)
def test_boolean_decision_nfkc_recovers_fullwidth_json_punctuation(
    raw: str,
    expected_speech: str,
) -> None:
    assert _decision_fields(
        raw,
        _boolean_contract("run_for_sheriff", "required"),
    ) == (
        None,
        expected_speech,
        "run_for_sheriff",
        False,
    )


def test_required_if_true_allows_silent_false_but_requires_true_speech() -> None:
    contract = _boolean_contract("explode", "required_if_true")
    assert _decision_fields('{"explode":false}', contract) == (
        None,
        None,
        "explode",
        False,
    )
    assert _decision_fields(
        '{"explode":false,"speech":"我暂时不自爆。"}',
        contract,
    ) == (None, None, "explode", False)
    with pytest.raises(V2QualityError, match="model_decision_invalid_speech"):
        _decision_fields('{"explode":true}', contract)
    assert _decision_fields(
        '{"explode":true,"speech":"我选择自爆！"}',
        contract,
    ) == (None, "我选择自爆！", "explode", True)


def test_forbidden_speech_is_preserved_for_action_normalization() -> None:
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
    }

    assert _decision_fields(
        '{"target_player_id":"seat_6","speech":"这段违规发言只用于审计。"}',
        contract,
    ) == (
        "seat_6",
        "这段违规发言只用于审计。",
        None,
        None,
    )


def test_model_speech_constraints_cap_characters_and_sentences() -> None:
    long_speech = "甲" * 299 + "。" + "乙" * 20

    assert _constrain_model_speech(
        long_speech,
        max_chars=300,
        max_sentences=None,
    ) == ("甲" * 299 + "。", ("max_chars_exceeded",))
    assert _constrain_model_speech(
        "我建议袭击3号。因为他的身份最可疑。",
        max_chars=None,
        max_sentences=1,
    ) == ("我建议袭击3号。", ("max_sentences_exceeded",))
    assert _constrain_model_speech(
        "我建议袭击3号",
        max_chars=None,
        max_sentences=1,
    ) == ("我建议袭击3号", ())


def test_model_speech_instructions_include_hard_contract_limits() -> None:
    assert _speech_output_instruction(
        {
            "speech": {
                "mode": "required",
                "max_chars": 300,
                "max_sentences": 1,
            }
        }
    ) == ("speech 必须是准备直接播报的非空自然中文。speech 不得超过300字。speech 只能包含一句话。")


def test_boolean_actions_keep_configured_thinking() -> None:
    parameters, source = _action_model_parameters(
        V2SpeechSpec(
            action_type="werewolf_self_explosion",
            phase_id="day_1",
            required_phase_state="public_discussion_open",
            objective="决定是否自爆",
            success_live_state="ready",
            success_phase_state="public_discussion_open",
            model_parameters={"thinking": "enabled", "max_tokens": 16384},
            decision_contract=V2DecisionContract(
                kind="boolean",
                boolean_field="explode",
                speech_mode="forbidden",
            ),
        )
    )

    assert parameters == {"thinking": "enabled", "max_tokens": 16384}
    assert source == "model_configuration"


def test_non_boolean_actions_keep_configured_thinking() -> None:
    parameters, source = _action_model_parameters(
        V2SpeechSpec(
            action_type="day_debate_speech",
            phase_id="day_1",
            required_phase_state="public_discussion_open",
            objective="发表分析",
            success_live_state="ready",
            success_phase_state="public_discussion_open",
            model_parameters={"thinking": "enabled", "max_tokens": 16384},
        )
    )

    assert parameters == {"thinking": "enabled", "max_tokens": 16384}
    assert source == "model_configuration"


def _target_contract() -> dict[str, Any]:
    return {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "required"},
    }


def _boolean_contract(field: str, speech_mode: str) -> dict[str, Any]:
    return {
        "kind": "boolean",
        "field": field,
        "speech": {"mode": speech_mode},
    }


def test_sse_parser_rejects_malformed_provider_events() -> None:
    assert _sse_data("event: response.output_text.delta") is None
    assert _sse_data("data: [DONE]") is None
    assert _sse_data('data: {"type":"response.output_text.delta","delta":"欢迎"}') == {
        "type": "response.output_text.delta",
        "delta": "欢迎",
    }
    with pytest.raises(V2ModelError, match="model_invalid_sse"):
        _sse_data("data: {")


def test_model_stream_wait_checks_durable_cancellation() -> None:
    async def delayed_lines():
        await asyncio.sleep(5)
        yield "data: [DONE]"

    def check_cancellation() -> None:
        raise V2GameCanceled("operator stop")

    with pytest.raises(V2GameCanceled):
        asyncio.run(
            _next_with_cancellation(
                delayed_lines().__aiter__(),
                timeout=5,
                check_cancellation=check_cancellation,
            )
        )


def test_tts_receive_wait_checks_durable_cancellation() -> None:
    class DelayedWebSocket:
        async def recv(self) -> bytes:
            await asyncio.sleep(5)
            return b""

    def check_cancellation() -> None:
        raise V2GameCanceled("operator stop")

    with pytest.raises(V2GameCanceled):
        asyncio.run(
            _receive(
                DelayedWebSocket(),
                timeout=5,
                check_cancellation=check_cancellation,
            )
        )


def test_public_player_projection_is_ordered_and_fail_closed() -> None:
    projected = project_public_player_seats(
        [
            {
                "seat": 2,
                "profile_id": "profile-2",
                "name": "",
                "model": "must-not-leak",
            },
            {
                "seat": 1,
                "profile_id": "profile-1",
                "name": "阿青",
                "avatar_image_url": "/avatar/profile-1",
                "personality": "must-not-leak",
            },
        ]
    )

    assert [item.model_dump(mode="json") for item in projected] == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": "/avatar/profile-1",
            "alive": True,
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "2号玩家",
            "avatar_url": None,
            "alive": True,
        },
    ]
    with pytest.raises(V2PublicProjectionError, match="duplicate player seat"):
        project_public_player_seats(
            [
                {"seat": 1, "profile_id": "profile-1"},
                {"seat": 1, "profile_id": "profile-2"},
            ]
        )
    with pytest.raises(V2PublicProjectionError, match="duplicate public player id"):
        project_public_player_seats(
            [
                {"seat": 1, "profile_id": "profile-1"},
                {"seat": 2, "profile_id": "profile-1"},
            ]
        )


def test_public_rule_projection_excludes_internal_rule_fields() -> None:
    projected = project_public_rule_snapshot(
        {
            "max_rounds": 8,
            "rule_set_revision_id": "private-revision",
            "lineup_quality_report": {"private": True},
            "rule_set": {
                "id": "classic_2",
                "name": "测试两人局",
                "version": "1",
                "player_count": 2,
                "content_hash": "private-hash",
                "roles": [
                    {"role": "狼人", "count": 1, "team": "private-team"},
                    {"role": "村民", "count": 1, "model_group": "private-model-group"},
                ],
                "sheriff_enabled": False,
                "werewolf_self_explosion_enabled": True,
                "exile_last_words_enabled": True,
                "first_night_last_words_enabled": True,
            },
        }
    )

    assert projected is not None
    assert projected.model_dump(mode="json") == {
        "rule_id": "classic_2",
        "name": "测试两人局",
        "version": "1",
        "player_count": 2,
        "roles": [{"role": "狼人", "count": 1}, {"role": "村民", "count": 1}],
        "max_rounds": 8,
        "sheriff_enabled": False,
        "werewolf_self_explosion_enabled": True,
        "exile_last_words_enabled": True,
        "first_night_last_words_enabled": True,
    }
    with pytest.raises(V2PublicProjectionError, match="does not match"):
        project_public_rule_snapshot(
            {
                "max_rounds": 8,
                "rule_set": {
                    "id": "broken",
                    "name": "错误规则",
                    "version": "1",
                    "player_count": 2,
                    "roles": [{"role": "村民", "count": 1}],
                },
            }
        )


def test_private_role_assignment_is_deterministic_and_public_status_is_sealed() -> None:
    players = [
        {"seat": 2, "profile_id": "profile-2"},
        {"seat": 1, "profile_id": "profile-1"},
    ]
    rule = {
        "rule_set": {
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "村民", "count": 1, "team": "village"},
            ]
        }
    }
    first = assign_private_roles(
        players_snapshot=players,
        rule_snapshot=rule,
        seed_hex="01" * 32,
    )
    second = assign_private_roles(
        players_snapshot=list(reversed(players)),
        rule_snapshot=rule,
        seed_hex="01" * 32,
    )

    assert first == second
    assert [item.seat for item in first.assignments] == [1, 2]
    assert sorted((item.role, item.team) for item in first.assignments) == [
        ("村民", "village"),
        ("狼人", "werewolves"),
    ]
    assert len(first.digest) == 64
    assert project_public_role_assignment_status(2).model_dump(mode="json") == {
        "state": "sealed",
        "assigned_count": 2,
    }
    assert project_public_role_assignment_status(None).model_dump(mode="json") == {
        "state": "unavailable",
        "assigned_count": 0,
    }
    with pytest.raises(V2RoleAssignmentError, match="does not match"):
        assign_private_roles(
            players_snapshot=players,
            rule_snapshot={"rule_set": {"roles": [{"role": "村民", "count": 1}]}},
            seed_hex="01" * 32,
        )


def test_god_view_access_and_projection_are_separate_and_fail_closed() -> None:
    token, token_hash = issue_god_view_access_token()
    assert token != token_hash
    assert verify_god_view_access_token(token=token, expected_sha256=token_hash)
    assert not verify_god_view_access_token(
        token="wrong-token-that-is-long-enough-to-be-valid",
        expected_sha256=token_hash,
    )

    projected = project_god_view_player_identities(
        players_snapshot=[
            {
                "seat": 1,
                "profile_id": "profile-1",
                "name": "阿青",
                "model": "must-not-leak",
                "personality": "must-not-leak",
            }
        ],
        assignments=[
            SimpleNamespace(
                seat=1,
                player_id="profile-1",
                role="狼人",
                team="werewolves",
            )
        ],
        player_states={
            "profile-1": SimpleNamespace(alive=True, death_cause=None),
        },
    )
    assert [item.model_dump(mode="json") for item in projected] == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": None,
            "role": "狼人",
            "team": "werewolves",
            "alive": True,
            "death_cause": None,
        }
    ]
    with pytest.raises(V2GodViewProjectionError, match="does not match"):
        project_god_view_player_identities(
            players_snapshot=[{"seat": 1, "profile_id": "profile-1"}],
            assignments=[
                SimpleNamespace(
                    seat=1,
                    player_id="profile-2",
                    role="狼人",
                    team="werewolves",
                )
            ],
            player_states={
                "profile-1": SimpleNamespace(alive=True, death_cause=None),
            },
        )


def test_live_audio_frame_binds_pcm_to_one_presentation() -> None:
    pcm = b"\x01\x00\x02\x00"
    packet = audio_frame(
        _identity(),
        chunk_index=2,
        start_sample=4,
        sample_count=2,
        sample_rate=24000,
        pcm=pcm,
    )
    assert packet[:4] == b"LV2A"
    header_size = int.from_bytes(packet[4:6], "big")
    header = json.loads(packet[6 : 6 + header_size])
    assert header["presentation_id"] == "v2_pres_0000000000000001"
    assert header["speech_id"] == "v2_speech_0000000000000001"
    assert header["chunk_index"] == 2
    assert header["start_sample"] == 4
    assert packet[6 + header_size :] == pcm
    with pytest.raises(V2LiveProtocolError, match="sample_count"):
        audio_frame(
            _identity(),
            chunk_index=0,
            start_sample=0,
            sample_count=3,
            sample_rate=24000,
            pcm=pcm,
        )


def test_voice_recorder_atomically_saves_exact_pcm(tmp_path: Path) -> None:
    recorder = V2VoiceRecorder(
        root=tmp_path,
        storage_key="game/voice.wav",
        sample_rate=24000,
    )
    chunks = (b"\x01\x00" * 120, b"\x02\x00" * 240)
    assert recorder.append(chunks[0]) == 120
    assert recorder.append(chunks[1]) == 240
    result = recorder.finalize()

    final_path = tmp_path / "game/voice.wav"
    assert final_path.is_file()
    assert not (tmp_path / "game/voice.wav.writing").exists()
    with wave.open(str(final_path), "rb") as saved:
        assert saved.getframerate() == 24000
        assert saved.getnchannels() == 1
        assert saved.getnframes() == 360
        assert saved.readframes(360) == b"".join(chunks)
    assert result.sample_count == 360
    assert result.duration_ms == 15
    assert result.pcm_sha256 == hashlib.sha256(b"".join(chunks)).hexdigest()


def test_voice_recorder_abort_leaves_no_partial_asset(tmp_path: Path) -> None:
    recorder = V2VoiceRecorder(
        root=tmp_path,
        storage_key="game/voice.wav",
        sample_rate=24000,
    )
    recorder.append(b"\x01\x00")
    recorder.abort()
    assert not (tmp_path / "game/voice.wav").exists()
    assert not (tmp_path / "game/voice.wav.writing").exists()
    with pytest.raises(V2VoiceRecordingError, match="closed"):
        recorder.append(b"\x01\x00")


def test_voice_recorder_discards_only_an_uncommitted_finalized_asset(tmp_path: Path) -> None:
    recorder = V2VoiceRecorder(
        root=tmp_path,
        storage_key="game/uncommitted.wav",
        sample_rate=24000,
    )
    recorder.append(b"\x01\x00")
    recorder.finalize()
    final_path = tmp_path / "game/uncommitted.wav"
    assert final_path.is_file()

    recorder.discard_finalized()

    assert not final_path.exists()
    assert not (tmp_path / "game/uncommitted.wav.writing").exists()


def test_tts_v3_client_frame_layout_matches_event_protocol() -> None:
    request = _encode_event(
        event=_START_SESSION,
        payload=b'{"event":100}',
        session_id="session-1",
    )
    assert request[:4] == bytes((0x11, 0x14, 0x10, 0x00))
    assert struct.unpack_from(">i", request, 4)[0] == _START_SESSION
    session_size = struct.unpack_from(">I", request, 8)[0]
    assert request[12 : 12 + session_size] == b"session-1"

    session = b"session-1"
    pcm = b"\x01\x00\x02\x00"
    response = bytearray((0x11, (_AUDIO_SERVER << 4) | _WITH_EVENT, 0x00, 0x00))
    response.extend(struct.pack(">i", 352))
    response.extend(struct.pack(">I", len(session)))
    response.extend(session)
    response.extend(struct.pack(">I", len(pcm)))
    response.extend(pcm)
    decoded = _decode_frame(bytes(response))
    assert decoded.message_type == _AUDIO_SERVER
    assert decoded.event == 352
    assert decoded.payload == pcm

    connection_id = b"connection-1"
    metadata = b'{"status_code":20000000}'
    started = bytearray((0x11, 0x94, 0x10, 0x00))
    started.extend(struct.pack(">i", _CONNECTION_STARTED))
    started.extend(struct.pack(">I", len(connection_id)))
    started.extend(connection_id)
    started.extend(struct.pack(">I", len(metadata)))
    started.extend(metadata)
    assert _decode_frame(bytes(started)).event == _CONNECTION_STARTED

    assert _TASK_REQUEST == 200
