import { AdminApiError } from "@/api/problem-details";
import type {
  GameControlResult,
  GameEventPage,
  GamePresentation,
  GameRecordEvent,
  GameRecordList,
  GameRecordListItem,
  GameRecordSummary,
  GameRun,
  ModelRequest,
  ModelActionRetryResult,
  ModelRequestAudienceSource,
  ModelFailureImpact,
  ModelFailureResolution,
  ModelRequestPage,
  ModelRequestSummary,
  OutputEnforcementAudit,
  PlayerIdentity,
  PromptProjection,
  VoiceAsset,
} from "@/match/game-records/types";

export function parseGameControlResult(
  value: unknown,
): GameControlResult {
  const record = object(value);
  return {
    action: oneOf(record.action, ["stop"] as const),
    game_id: text(record.game_id),
    run_id: text(record.run_id),
    run_status: text(record.run_status),
    stop_requested_at: date(record.stop_requested_at),
    replayed: boolean(record.replayed),
  };
}

export function parseModelActionRetryResult(
  value: unknown,
): ModelActionRetryResult {
  const record = object(value);
  return {
    action: oneOf(record.action, ["retry_model_action"] as const),
    game_id: text(record.game_id),
    run_id: text(record.run_id),
    run_status: text(record.run_status),
    action_id: text(record.action_id),
    replayed: boolean(record.replayed),
  };
}

export function parseGameRecordList(value: unknown): GameRecordList {
  const record = object(value);
  const pagination = object(record.pagination);
  return {
    items: array(record.items).map(parseListItem),
    pagination: {
      page: integer(pagination.page, 1),
      page_size: integer(pagination.page_size, 1),
      total: integer(pagination.total, 0),
      pages: integer(pagination.pages, 0),
    },
  };
}

export function parseGameRecordSummary(value: unknown): GameRecordSummary {
  const record = object(value);
  return {
    ...parseListItem(record),
    rule_snapshot: object(record.rule_snapshot),
    players_snapshot: array(record.players_snapshot).map(object),
    judge_voice_snapshot: object(record.judge_voice_snapshot),
    delivery_snapshot:
      record.delivery_snapshot === null ? null : object(record.delivery_snapshot),
    ability_snapshot: object(record.ability_snapshot),
    match_state: record.match_state === null ? null : object(record.match_state),
    player_identities: array(record.player_identities).map(parsePlayerIdentity),
    runs: array(record.runs).map(parseRun),
    presentations: array(record.presentations).map(parsePresentation),
    voice_assets: array(record.voice_assets).map(parseVoiceAsset),
    player_states: array(record.player_states).map(object),
    action_windows: array(record.action_windows).map(object),
    ability_instances: array(record.ability_instances).map(object),
    ability_activations: array(record.ability_activations).map(object),
    effect_intents: array(record.effect_intents).map(object),
    knowledge_facts: array(record.knowledge_facts).map(object),
  };
}

export function parseGameEventPage(value: unknown): GameEventPage {
  const record = object(value);
  return {
    items: array(record.items).map(parseGameRecordEvent),
    after_record_seq: integer(record.after_record_seq, 0),
    next_after_record_seq: integer(record.next_after_record_seq, 0),
    has_more: boolean(record.has_more),
  };
}

export function parseModelRequestPage(
  value: unknown,
): ModelRequestPage {
  const record = object(value);
  return {
    items: array(record.items).map(parseModelRequestSummary),
    after_record_seq: integer(record.after_record_seq, 0),
    next_after_record_seq: integer(record.next_after_record_seq, 0),
    has_more: boolean(record.has_more),
  };
}

function parsePlayerIdentity(value: unknown): PlayerIdentity {
  const record = object(value);
  return {
    seat: integer(record.seat, 1),
    player_id: text(record.player_id),
    display_name: text(record.display_name),
    avatar_url: nullableText(record.avatar_url),
    role: text(record.role),
    team: nullableText(record.team),
    alive: boolean(record.alive),
    death_cause: nullableText(record.death_cause),
  };
}

function parseListItem(value: unknown): GameRecordListItem {
  const record = object(value);
  return {
    game_id: text(record.game_id),
    title: text(record.title),
    status: text(record.status),
    current_run_id: text(record.current_run_id),
    record_schema_version: integer(record.record_schema_version, 1),
    last_record_seq: integer(record.last_record_seq, 0),
    last_presentation_seq: integer(record.last_presentation_seq, 0),
    phase_seq: integer(record.phase_seq, 0),
    phase_id: text(record.phase_id),
    phase_state: text(record.phase_state),
    audio_mode: oneOf(record.audio_mode, ["tts", "text_only", "legacy_unknown"] as const),
    match_status: oneOf(
      record.match_status,
      ["waiting", "running", "completed", "failed", "canceled"] as const,
    ),
    execution_state: oneOf(
      record.execution_state,
      ["unowned", "owned", "stale", "stopped"] as const,
    ),
    winner:
      record.winner === null
        ? null
        : oneOf(record.winner, ["villagers", "werewolves"] as const),
    completion_reason: nullableText(record.completion_reason),
    completed_at: nullableDate(record.completed_at),
    created_at: date(record.created_at),
    updated_at: date(record.updated_at),
  };
}

function parseRun(value: unknown): GameRun {
  const record = object(value);
  return {
    run_id: text(record.run_id),
    attempt_no: integer(record.attempt_no, 1),
    status: text(record.status),
    started_at: nullableDate(record.started_at),
    completed_at: record.completed_at === null ? null : date(record.completed_at),
    stop_requested_at: nullableDate(record.stop_requested_at),
    worker_id: nullableText(record.worker_id),
    worker_heartbeat_at: nullableDate(record.worker_heartbeat_at),
    lease_expires_at: nullableDate(record.lease_expires_at),
    fence_token: integer(record.fence_token, 0),
  };
}

export function parseGameRecordEvent(
  value: unknown,
): GameRecordEvent {
  const record = object(value);
  return {
    event_id: integer(record.event_id, 1),
    record_seq: integer(record.record_seq, 1),
    run_id: text(record.run_id),
    event_type: text(record.event_type),
    payload_schema_version: integer(record.payload_schema_version, 1),
    payload: object(record.payload),
    created_at: date(record.created_at),
  };
}

function parsePresentation(value: unknown): GamePresentation {
  const record = object(value);
  return {
    presentation_seq: integer(record.presentation_seq, 1),
    presentation_id: text(record.presentation_id),
    action_id: nullableText(record.action_id),
    activation_id: nullableText(record.activation_id),
    phase_id: text(record.phase_id),
    actor_kind: text(record.actor_kind),
    actor_id: text(record.actor_id),
    audience: text(record.audience),
    speech_id: text(record.speech_id),
    segment_index: integer(record.segment_index, 0),
    source_event_id: integer(record.source_event_id, 1),
    state: text(record.state),
    subtitle_text: text(record.subtitle_text),
    voice_asset_id: nullableText(record.voice_asset_id),
    audio_duration_ms: nullableInteger(record.audio_duration_ms, 0),
    created_at: date(record.created_at),
    closed_at: nullableDate(record.closed_at),
  };
}

function parseVoiceAsset(value: unknown): VoiceAsset {
  const record = object(value);
  return {
    voice_asset_id: text(record.voice_asset_id),
    action_id: text(record.action_id),
    activation_id: nullableText(record.activation_id),
    audience: text(record.audience),
    presentation_id: text(record.presentation_id),
    speech_id: text(record.speech_id),
    segment_index: integer(record.segment_index, 0),
    state: text(record.state),
    mime_type: text(record.mime_type),
    sample_rate: integer(record.sample_rate, 1),
    channels: integer(record.channels, 1),
    sample_count: nullableInteger(record.sample_count, 0),
    duration_ms: nullableInteger(record.duration_ms, 0),
    pcm_sha256: nullableText(record.pcm_sha256),
    size_bytes: nullableInteger(record.size_bytes, 0),
    audio_url: nullableText(record.audio_url),
    created_at: date(record.created_at),
    completed_at: nullableDate(record.completed_at),
  };
}

export function parseModelRequestSummary(
  value: unknown,
): ModelRequestSummary {
  const record = object(value);
  const audience = text(record.audience);
  const storedAudience =
    record.stored_audience === undefined
      ? null
      : nullableText(record.stored_audience);
  const effectiveAudience =
    record.effective_audience === undefined
      ? audience
      : text(record.effective_audience);
  const modelContextSchemaVersion =
    record.model_context_schema_version === undefined
      ? null
      : nullableInteger(record.model_context_schema_version, 0);
  const promptTemplateVersion =
    record.prompt_template_version === undefined
      ? null
      : nullableInteger(record.prompt_template_version, 0);
  const modelViewSelectorVersion =
    record.model_view_selector_version === undefined
      ? null
      : nullableInteger(record.model_view_selector_version, 0);
  const audienceSource: ModelRequestAudienceSource =
    record.audience_source === undefined
      ? "legacy_unknown"
      : oneOf(
          record.audience_source,
          [
            "event_contract",
            "event_contract_narrowed",
            "presentation",
            "legacy_event",
            "action_context",
            "legacy_unknown",
          ] as const,
        );
  const failureResolution: ModelFailureResolution | null =
    record.failure_resolution === undefined
      ? record.failure_code === null || record.failure_code === undefined
        ? null
        : "legacy_unavailable"
      : record.failure_resolution === null
        ? null
        : oneOf(record.failure_resolution, [
            "automatic_retry_success",
            "technical_skip",
            "technical_false_fallback",
            "operator_pause",
            "isolated_action_failure",
            "run_failure",
            "run_canceled",
            "unresolved",
            "invariant_conflict",
            "legacy_unavailable",
          ] as const);
  const status = oneOf(record.status, [
    "running",
    "succeeded",
    "failed",
    "skipped",
    "canceled",
  ] as const);
  const failureImpact: ModelFailureImpact | null =
    record.failure_impact === undefined
      ? status === "failed"
        ? "operational_failure"
        : null
      : record.failure_impact === null
        ? null
        : oneOf(record.failure_impact, [
            "expected_control_flow",
            "user_visible_degradation",
            "operational_failure",
          ] as const);
  return {
    attempt_id: text(record.attempt_id),
    decision_family_id:
      record.decision_family_id === undefined
        ? null
        : nullableText(record.decision_family_id),
    retry_scope:
      record.retry_scope === undefined
        ? "action"
        : oneOf(record.retry_scope, [
            "action",
            "same_action",
            "batch_initial",
            "batch_recovery",
            "operator_retry",
          ] as const),
    vote_batch_stage:
      record.vote_batch_stage === undefined
        ? null
        : nullableText(record.vote_batch_stage),
    automatic_machine_format_attempt_count:
      record.automatic_machine_format_attempt_count === undefined
        ? null
        : nullableInteger(record.automatic_machine_format_attempt_count, 0),
    automatic_machine_format_budget:
      record.automatic_machine_format_budget === undefined
        ? null
        : nullableInteger(record.automatic_machine_format_budget, 0),
    prior_output_budget_failures:
      record.prior_output_budget_failures === undefined
        ? null
        : nullableInteger(record.prior_output_budget_failures, 0),
    output_budget_failure_count:
      record.output_budget_failure_count === undefined
        ? null
        : nullableInteger(record.output_budget_failure_count, 0),
    automatic_output_budget_attempt_count:
      record.automatic_output_budget_attempt_count === undefined
        ? null
        : nullableInteger(record.automatic_output_budget_attempt_count, 0),
    automatic_output_budget_budget:
      record.automatic_output_budget_budget === undefined
        ? null
        : nullableInteger(record.automatic_output_budget_budget, 0),
    attempt_no:
      record.attempt_no === undefined ? 1 : integer(record.attempt_no, 1),
    cycle_attempt_no:
      record.cycle_attempt_no === undefined
        ? integer(record.attempt_no ?? 1, 1)
        : integer(record.cycle_attempt_no, 1),
    retry_cycle:
      record.retry_cycle === undefined
        ? 1
        : integer(record.retry_cycle, 1),
    max_attempts:
      record.max_attempts === undefined ? 1 : integer(record.max_attempts, 1),
    retry_of_attempt_id:
      record.retry_of_attempt_id === undefined
        ? null
        : nullableText(record.retry_of_attempt_id),
    record_seq:
      record.record_seq === undefined ? 1 : integer(record.record_seq, 1),
    last_record_seq:
      record.last_record_seq === undefined
        ? integer(record.record_seq ?? 1, 1)
        : integer(record.last_record_seq, 1),
    action_id: text(record.action_id),
    run_id: text(record.run_id),
    phase_id: text(record.phase_id),
    action_type: text(record.action_type),
    actor_kind: text(record.actor_kind),
    actor_id: text(record.actor_id),
    audience,
    stored_audience: storedAudience,
    effective_audience: effectiveAudience,
    audience_source: audienceSource,
    request_kind: text(record.request_kind),
    model_id: nullableText(record.model_id),
    model_provider: nullableText(record.model_provider),
    judge_configuration_version: nullableInteger(
      record.judge_configuration_version,
      0,
    ),
    prompt_schema_version:
      record.prompt_schema_version === undefined
        ? null
        : nullableInteger(record.prompt_schema_version, 0),
    model_context_schema_version: modelContextSchemaVersion,
    prompt_template_version: promptTemplateVersion,
    model_view_selector_version: modelViewSelectorVersion,
    prompt_projection:
      record.prompt_projection === undefined ||
      record.prompt_projection === null
        ? null
        : parsePromptProjection(
            record.prompt_projection,
            {
              modelContextSchemaVersion,
              modelViewSelectorVersion,
              promptSchemaVersion:
                record.prompt_schema_version === undefined
                  ? null
                  : nullableInteger(record.prompt_schema_version, 0),
              promptTemplateVersion,
            },
          ),
    status,
    input_source: oneOf(
      record.input_source,
      ["persisted", "reconstructed", "unavailable"] as const,
    ),
    passive_observation_count:
      record.passive_observation_count === undefined
        ? Array.isArray(record.passive_observations)
          ? record.passive_observations.length
          : 0
        : integer(record.passive_observation_count, 0),
    output_source: oneOf(
      record.output_source,
      ["persisted", "legacy_inferred", "unavailable"] as const,
    ),
    provider_request_id: nullableText(record.provider_request_id),
    model_generation_policy_contract_status:
      record.model_generation_policy_contract_status === undefined ||
      record.model_generation_policy_contract_status === null
        ? null
        : oneOf(record.model_generation_policy_contract_status, [
            "supported",
            "legacy_disabled",
          ] as const),
    model_generation_policy_schema_version:
      record.model_generation_policy_schema_version === undefined
        ? null
        : nullableInteger(record.model_generation_policy_schema_version, 1),
    model_generation_policy_classification_version:
      record.model_generation_policy_classification_version === undefined
        ? null
        : nullableInteger(
            record.model_generation_policy_classification_version,
            1,
          ),
    model_generation_policy_enforcement:
      record.model_generation_policy_enforcement === undefined ||
      record.model_generation_policy_enforcement === null
        ? null
        : oneOf(record.model_generation_policy_enforcement, [
            "observe_only",
            "disabled",
          ] as const),
    model_generation_policy_reasoning_parameter_mode:
      record.model_generation_policy_reasoning_parameter_mode === undefined ||
      record.model_generation_policy_reasoning_parameter_mode === null
        ? null
        : oneOf(record.model_generation_policy_reasoning_parameter_mode, [
            "inherit_frozen_model_configuration",
          ] as const),
    model_generation_policy_profile:
      record.model_generation_policy_profile === undefined ||
      record.model_generation_policy_profile === null
        ? null
        : oneOf(record.model_generation_policy_profile, [
            "strategic_full",
            "recoverable_public_speech",
            "isolated_auxiliary",
          ] as const),
    model_generation_policy_profile_source:
      record.model_generation_policy_profile_source === undefined ||
      record.model_generation_policy_profile_source === null
        ? null
        : oneOf(record.model_generation_policy_profile_source, [
            "explicit_action_profile",
            "default_profile",
            "legacy_missing_contract",
          ] as const),
    reasoning_only_timeout_ms:
      record.reasoning_only_timeout_ms === undefined
        ? null
        : nullableInteger(record.reasoning_only_timeout_ms, 1),
    timeout_max_attempts:
      record.timeout_max_attempts === undefined
        ? null
        : nullableInteger(record.timeout_max_attempts, 1),
    shadow_would_timeout:
      record.shadow_would_timeout === undefined
        ? null
        : nullableBoolean(record.shadow_would_timeout),
    finish_reason:
      record.finish_reason === undefined || record.finish_reason === null
        ? null
        : oneOf(record.finish_reason, [
            "completed",
            "stop",
            "length",
            "max_output_tokens",
            "content_filter",
            "tool_calls",
            "unknown",
          ] as const),
    provider_usage:
      record.provider_usage === undefined || record.provider_usage === null
        ? null
        : parseProviderUsage(record.provider_usage),
    usage_update_count:
      record.usage_update_count === undefined
        ? null
        : nullableInteger(record.usage_update_count, 0),
    usage_conflict_observed:
      record.usage_conflict_observed === undefined
        ? null
        : nullableBoolean(record.usage_conflict_observed),
    usage_consistency:
      record.usage_consistency === undefined ||
      record.usage_consistency === null
        ? null
        : oneOf(record.usage_consistency, [
            "exact",
            "provider_total_mismatch",
            "unavailable",
          ] as const),
    queue_wait_ms:
      record.queue_wait_ms === undefined
        ? null
        : nullableInteger(record.queue_wait_ms, 0),
    provider_in_flight:
      record.provider_in_flight === undefined
        ? null
        : nullableInteger(record.provider_in_flight, 0),
    provider_concurrency_limit:
      record.provider_concurrency_limit === undefined
        ? null
        : nullableInteger(record.provider_concurrency_limit, 1),
    first_token_ms: nullableInteger(record.first_token_ms, 0),
    reasoning_only_elapsed_ms:
      record.reasoning_only_elapsed_ms === undefined
        ? null
        : nullableInteger(record.reasoning_only_elapsed_ms, 0),
    completed_ms: nullableInteger(record.completed_ms, 0),
    reasoning_delta_count:
      record.reasoning_delta_count === undefined
        ? null
        : nullableInteger(record.reasoning_delta_count, 0),
    text_delta_count:
      record.text_delta_count === undefined
        ? null
        : nullableInteger(record.text_delta_count, 0),
    max_inter_delta_ms:
      record.max_inter_delta_ms === undefined
        ? null
        : nullableInteger(record.max_inter_delta_ms, 0),
    last_progress_ms:
      record.last_progress_ms === undefined
        ? null
        : nullableInteger(record.last_progress_ms, 0),
    failure_kind: nullableText(record.failure_kind),
    failure_code: nullableText(record.failure_code),
    ...(record.failure_category === undefined
      ? {}
      : { failure_category: nullableText(record.failure_category) }),
    failure_impact: failureImpact,
    counts_as_failure:
      record.counts_as_failure === undefined
        ? status === "failed"
        : boolean(record.counts_as_failure),
    ...(record.repair_kind === undefined
      ? {}
      : { repair_kind: nullableText(record.repair_kind) }),
    ...(record.output_enforcement === undefined
      ? {}
      : {
          output_enforcement:
            record.output_enforcement === null
              ? null
              : parseOutputEnforcement(record.output_enforcement),
        }),
    ...(record.application_validation_result === undefined
      ? {}
      : {
          application_validation_result:
            record.application_validation_result === null
              ? null
              : oneOf(record.application_validation_result, [
                  "accepted",
                  "rejected",
                ] as const),
        }),
    retryable:
      record.retryable === undefined ? null : nullableBoolean(record.retryable),
    terminal:
      record.terminal === undefined ? null : nullableBoolean(record.terminal),
    failure_stage:
      record.failure_stage === undefined
        ? null
        : nullableText(record.failure_stage),
    exception_type:
      record.exception_type === undefined
        ? null
        : nullableText(record.exception_type),
    errno:
      record.errno === undefined ? null : nullableInteger(record.errno, 0),
    http_status:
      record.http_status === undefined
        ? null
        : nullableInteger(record.http_status, 100),
    first_token_seen:
      record.first_token_seen === undefined
        ? null
        : nullableBoolean(record.first_token_seen),
    response_headers_seen:
      record.response_headers_seen === undefined
        ? null
        : nullableBoolean(record.response_headers_seen),
    response_headers:
      record.response_headers === undefined || record.response_headers === null
        ? null
        : stringRecord(record.response_headers),
    first_token_kind:
      record.first_token_kind === undefined
        ? null
        : nullableText(record.first_token_kind),
    first_visible_text_ms:
      record.first_visible_text_ms === undefined
        ? null
        : nullableInteger(record.first_visible_text_ms, 0),
    timeout_scope:
      record.timeout_scope === undefined
        ? null
        : nullableText(record.timeout_scope),
    failure_elapsed_ms:
      record.failure_elapsed_ms === undefined
        ? null
        : nullableInteger(record.failure_elapsed_ms, 0),
    attempt_budget_ms:
      record.attempt_budget_ms === undefined
        ? null
        : nullableInteger(record.attempt_budget_ms, 0),
    action_budget_ms:
      record.action_budget_ms === undefined
        ? null
        : nullableInteger(record.action_budget_ms, 0),
    action_elapsed_ms:
      record.action_elapsed_ms === undefined
        ? null
        : nullableInteger(record.action_elapsed_ms, 0),
    action_remaining_ms:
      record.action_remaining_ms === undefined
        ? null
        : nullableInteger(record.action_remaining_ms, 0),
    effective_attempt_limit:
      record.effective_attempt_limit === undefined
        ? null
        : nullableInteger(record.effective_attempt_limit, 1),
    retry_delay_ms:
      record.retry_delay_ms === undefined
        ? null
        : nullableInteger(record.retry_delay_ms, 0),
    required_retry_window_ms:
      record.required_retry_window_ms === undefined
        ? null
        : nullableInteger(record.required_retry_window_ms, 0),
    automatic_retry_scheduled:
      record.automatic_retry_scheduled === undefined
        ? null
        : nullableBoolean(record.automatic_retry_scheduled),
    automatic_retry_stop_reason:
      record.automatic_retry_stop_reason === undefined ||
      record.automatic_retry_stop_reason === null
        ? null
        : oneOf(record.automatic_retry_stop_reason, [
            "not_retryable",
            "decision_family_budget_exhausted",
            "attempt_limit_reached",
            "insufficient_action_budget",
          ] as const),
    failure_episode_id:
      record.failure_episode_id === undefined
        ? null
        : nullableText(record.failure_episode_id),
    failure_resolution: failureResolution,
    failure_episode_source_attempt_ids:
      record.failure_episode_source_attempt_ids === undefined ||
      record.failure_episode_source_attempt_ids === null
        ? null
        : array(record.failure_episode_source_attempt_ids).map(text),
    failure_episode_source_event_refs:
      record.failure_episode_source_event_refs === undefined ||
      record.failure_episode_source_event_refs === null
        ? null
        : array(record.failure_episode_source_event_refs).map(
            parseFailureEpisodeEventRef,
          ),
    failure_episode_terminal_event_refs:
      record.failure_episode_terminal_event_refs === undefined ||
      record.failure_episode_terminal_event_refs === null
        ? null
        : array(record.failure_episode_terminal_event_refs).map(
            parseFailureEpisodeEventRef,
          ),
    resolution_event_type:
      record.resolution_event_type === undefined
        ? null
        : nullableText(record.resolution_event_type),
    resolution_event_id:
      record.resolution_event_id === undefined
        ? null
        : nullableInteger(record.resolution_event_id, 1),
    resolution_event_record_seq:
      record.resolution_event_record_seq === undefined
        ? null
        : nullableInteger(record.resolution_event_record_seq, 1),
    supporting_event_type:
      record.supporting_event_type === undefined
        ? null
        : nullableText(record.supporting_event_type),
    supporting_event_id:
      record.supporting_event_id === undefined
        ? null
        : nullableInteger(record.supporting_event_id, 1),
    supporting_event_record_seq:
      record.supporting_event_record_seq === undefined
        ? null
        : nullableInteger(record.supporting_event_record_seq, 1),
    resolution_updated_at_record_seq:
      record.resolution_updated_at_record_seq === undefined
        ? null
        : nullableInteger(record.resolution_updated_at_record_seq, 1),
    failure_episode_invariant_errors:
      record.failure_episode_invariant_errors === undefined ||
      record.failure_episode_invariant_errors === null
        ? null
        : array(record.failure_episode_invariant_errors).map(text),
    model_binding_failure_streak:
      record.model_binding_failure_streak === undefined
        ? null
        : nullableInteger(record.model_binding_failure_streak, 0),
    model_binding_health_status:
      record.model_binding_health_status === undefined ||
      record.model_binding_health_status === null
        ? null
        : oneOf(record.model_binding_health_status, [
            "healthy",
            "impaired",
            "degraded",
          ] as const),
    model_binding_recovered_after_failures:
      record.model_binding_recovered_after_failures === undefined
        ? null
        : nullableInteger(record.model_binding_recovered_after_failures, 1),
    started_at: date(record.started_at),
    completed_at: nullableDate(record.completed_at),
  };
}

function parsePromptProjection(
  value: unknown,
  contract: {
    modelContextSchemaVersion: number | null;
    modelViewSelectorVersion: number | null;
    promptSchemaVersion: number | null;
    promptTemplateVersion: number | null;
  },
): PromptProjection {
  const projection = object(value);
  const modelContextSchemaVersion = contract.modelContextSchemaVersion;
  const v13Contract =
    contract.promptSchemaVersion === 13 &&
    modelContextSchemaVersion === 13 &&
    contract.promptTemplateVersion === 6 &&
    contract.modelViewSelectorVersion === 3 &&
    projection.model_context_schema_version === 13 &&
    projection.prompt_template_version === 6 &&
    projection.known_events_schema_version === 7 &&
    projection.ledger_schema_version === 5 &&
    projection.model_view_schema_version === 5 &&
    projection.model_view_selector_version === 3;
  if (!v13Contract) {
    return projection;
  }
  for (const key of [
    "model_context_schema_version",
    "prompt_template_version",
    "known_events_schema_version",
    "ledger_schema_version",
    "model_view_schema_version",
    "model_view_selector_version",
  ]) {
    validateOptionalInteger(projection, key, 0, true);
  }
  for (const key of [
    "serialized_char_count",
    "ledger_statement_count",
    "ledger_statement_char_count",
    "ledger_claim_count",
    "ledger_question_count",
    "ledger_relation_count",
    "source_event_count",
    "emitted_event_count",
    "future_filtered_event_count",
    "source_claim_candidate_count",
    "emitted_claim_count",
    "out_of_scope_claim_count",
    "rejected_claim_count",
    "source_question_count",
    "current_scope_question_count",
    "emitted_question_count",
    "out_of_scope_question_count",
    "invalid_question_count",
    "source_relation_count",
    "emitted_relation_count",
    "invalid_relation_count",
    "budget_dropped_event_count",
    "none_detected_question_count",
    "response_detected_question_count",
    "awaiting_scheduled_turn_question_count",
    "current_round_statement_count",
    "current_round_statement_char_count",
  ]) {
    validateOptionalInteger(projection, key, 0);
  }
  for (const key of [
    "known_event_record_seq_min",
    "known_event_record_seq_max",
  ]) {
    validateOptionalInteger(projection, key, 1, true);
  }
  if (projection.section_char_counts !== undefined) {
    for (const count of Object.values(object(projection.section_char_counts))) {
      integer(count, 0);
    }
  }
  if (projection.derivation_rejections !== undefined) {
    for (const rejectionValue of array(projection.derivation_rejections)) {
      const rejection = object(rejectionValue);
      text(rejection.source_event_ref);
      text(rejection.kind);
      text(rejection.reason);
      if (rejection.missing_fields !== undefined) {
        array(rejection.missing_fields).forEach(text);
      }
    }
  }
  for (const key of [
    "canonical_serialized_char_count",
    "compact_serialized_char_count",
    "verbatim_speech_count",
    "verbatim_speech_chars",
  ]) {
    validateOptionalInteger(projection, key, 0);
  }
  validateOptionalInteger(
    projection,
    "compaction_saved_chars",
    Number.MIN_SAFE_INTEGER,
  );
  if (projection.compaction_ratio !== undefined) {
    finiteNumber(projection.compaction_ratio, 0);
  }
  if (projection.retained_event_refs !== undefined) {
    array(projection.retained_event_refs).forEach(text);
  }
  if (projection.dropped_event_refs !== undefined) {
    throw invalid();
  }
  if (projection.canonical_sha256 !== undefined) {
    const hash = text(projection.canonical_sha256);
    if (!/^[0-9a-f]{64}$/u.test(hash)) throw invalid();
  }
  if (projection.round_trip_verified !== undefined) {
    boolean(projection.round_trip_verified);
  }
  if (
    projection.lossless_scope !== undefined &&
    projection.lossless_scope !== "selector_retained_projection"
  ) {
    throw invalid();
  }
  validateMemorySelector(projection.selector);
  const retainedRefs = array(projection.retained_event_refs).map(text);
  const selectorRetainedRefs = array(
    object(projection.selector).retained,
  ).map((entry) => text(object(entry).event_ref));
  if (
    new Set(retainedRefs).size !== retainedRefs.length ||
    new Set(selectorRetainedRefs).size !== selectorRetainedRefs.length ||
    retainedRefs.length !== selectorRetainedRefs.length ||
    retainedRefs.some((ref) => !selectorRetainedRefs.includes(ref))
  ) {
    throw invalid();
  }
  return projection;
}

function validateMemorySelector(value: unknown) {
  const selector = object(value);
  if (selector.version !== 3) throw invalid();
  const sourceCount = integer(selector.source_count, 0);
  const retainedCount = integer(selector.retained_count, 0);
  const omittedCount = integer(selector.omitted_count, 0);
  const futureFilteredCount = integer(selector.future_filtered_count, 0);
  const retained = array(selector.retained);
  const omitted = array(selector.omitted);
  const futureFiltered = array(selector.future_filtered);
  for (const entryValue of [...retained, ...omitted]) {
    const entry = object(entryValue);
    text(entry.event_ref);
    text(entry.category);
    text(entry.reason);
  }
  for (const entryValue of futureFiltered) {
    const entry = object(entryValue);
    text(entry.event_ref);
    text(entry.reason);
  }
  if (
    retained.length !== retainedCount ||
    omitted.length !== omittedCount ||
    futureFiltered.length !== futureFilteredCount ||
    retainedCount + omittedCount + futureFilteredCount !== sourceCount
  ) {
    throw invalid();
  }
  nullableText(selector.latest_actor_memory_ref);
  nullableInteger(selector.latest_actor_memory_cutoff_seq, 1);
  const memoryHash = nullableText(selector.latest_actor_memory_hash);
  if (memoryHash !== null && !/^[0-9a-f]{64}$/u.test(memoryHash)) {
    throw invalid();
  }
  const sourceTypeCounts = nonnegativeIntegerRecord(selector.source_type_counts);
  const retainedTypeCounts = nonnegativeIntegerRecord(
    selector.retained_type_counts,
  );
  const omittedTypeCounts = nonnegativeIntegerRecord(selector.omitted_type_counts);
  if (
    sumRecordValues(sourceTypeCounts) !== sourceCount ||
    sumRecordValues(retainedTypeCounts) !== retainedCount ||
    sumRecordValues(omittedTypeCounts) !== omittedCount
  ) {
    throw invalid();
  }
}

function nonnegativeIntegerRecord(value: unknown): Record<string, number> {
  return Object.fromEntries(
    Object.entries(object(value)).map(([key, count]) => [
      text(key),
      integer(count, 0),
    ]),
  );
}

function sumRecordValues(value: Record<string, number>): number {
  return Object.values(value).reduce((total, count) => total + count, 0);
}

function parseOutputEnforcement(value: unknown): OutputEnforcementAudit {
  const enforcement = object(value);
  return {
    requested:
      enforcement.requested === undefined
        ? null
        : nullableText(enforcement.requested),
    actual:
      enforcement.actual === undefined ? null : nullableText(enforcement.actual),
    schema_name:
      enforcement.schema_name === undefined
        ? null
        : nullableText(enforcement.schema_name),
    schema_version:
      enforcement.schema_version === undefined
        ? null
        : nullableInteger(enforcement.schema_version, 1),
  };
}

function parseProviderUsage(value: unknown) {
  const usage = object(value);
  const normalized: {
    input_tokens?: number;
    output_tokens?: number;
    reasoning_tokens?: number;
    total_tokens?: number;
    cached_input_tokens?: number;
  } = {};
  for (const key of [
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "cached_input_tokens",
  ] as const) {
    if (usage[key] !== undefined) normalized[key] = integer(usage[key], 0);
  }
  return normalized;
}

function parseFailureEpisodeEventRef(value: unknown) {
  const ref = object(value);
  const rawEventId = ref.event_id;
  const eventId =
    rawEventId === null
      ? null
      : typeof rawEventId === "string"
        ? text(rawEventId)
        : integer(rawEventId, 1);
  return {
    event_type: text(ref.event_type),
    event_id: eventId,
    record_seq: integer(ref.record_seq, 1),
  };
}

function validateOptionalInteger(
  record: Record<string, unknown>,
  key: string,
  minimum: number,
  nullable = false,
) {
  const value = record[key];
  if (value === undefined || (nullable && value === null)) return;
  integer(value, minimum);
}

export function parseModelRequest(value: unknown): ModelRequest {
  const record = object(value);
  return {
    ...parseModelRequestSummary(record),
    request_payload:
      record.request_payload === null ? null : object(record.request_payload),
    expanded_known_events:
      record.expanded_known_events === undefined ||
      record.expanded_known_events === null
        ? null
        : object(record.expanded_known_events),
    known_events_expansion_status:
      record.known_events_expansion_status === undefined
        ? "unavailable"
        : oneOf(record.known_events_expansion_status, [
            "verified",
            "not_applicable",
            "unavailable",
            "invalid",
          ] as const),
    raw_response: nullableText(record.raw_response),
    parsed_output:
      record.parsed_output === null ? null : object(record.parsed_output),
    passive_observations:
      record.passive_observations === undefined
        ? []
        : array(record.passive_observations).map(object),
    stream_reasoning:
      record.stream_reasoning === undefined
        ? null
        : nullableText(record.stream_reasoning),
    stream_text:
      record.stream_text === undefined ? null : nullableText(record.stream_text),
    stream_reasoning_character_count:
      record.stream_reasoning_character_count === undefined
        ? 0
        : integer(record.stream_reasoning_character_count, 0),
    stream_text_character_count:
      record.stream_text_character_count === undefined
        ? 0
        : integer(record.stream_text_character_count, 0),
    stream_estimated_reasoning_tokens:
      record.stream_estimated_reasoning_tokens === undefined
        ? null
        : nullableInteger(record.stream_estimated_reasoning_tokens, 0),
    stream_estimated_output_tokens:
      record.stream_estimated_output_tokens === undefined
        ? null
        : nullableInteger(record.stream_estimated_output_tokens, 0),
    stream_content_truncated:
      record.stream_content_truncated === undefined
        ? false
        : boolean(record.stream_content_truncated),
    stream_progress_updated_at:
      record.stream_progress_updated_at === undefined
        ? null
        : nullableDate(record.stream_progress_updated_at),
  };
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  return value as Record<string, unknown>;
}

function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw invalid();
  return value;
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value) throw invalid();
  return value;
}

function integer(value: unknown, minimum: number): number {
  if (!Number.isInteger(value) || Number(value) < minimum) throw invalid();
  return Number(value);
}

function finiteNumber(value: unknown, minimum: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum) {
    throw invalid();
  }
  return value;
}

function nullableInteger(value: unknown, minimum: number): number | null {
  return value === null ? null : integer(value, minimum);
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function stringRecord(value: unknown): Record<string, string> {
  return Object.fromEntries(
    Object.entries(object(value)).map(([key, item]) => [key, text(item)]),
  );
}

function nullableBoolean(value: unknown): boolean | null {
  return value === null ? null : boolean(value);
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw invalid();
  return value;
}

function date(value: unknown): string {
  const result = text(value);
  if (!Number.isFinite(Date.parse(result))) throw invalid();
  return result;
}

function nullableDate(value: unknown): string | null {
  return value === null ? null : date(value);
}

function oneOf<const T extends readonly string[]>(
  value: unknown,
  options: T,
): T[number] {
  if (
    typeof value !== "string" ||
    !(options as readonly string[]).includes(value)
  ) {
    throw invalid();
  }
  return value as T[number];
}

function invalid() {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "V2 对局记录响应无效",
      status: 502,
      detail: "V2 对局记录数据不完整或格式错误。",
      code: "admin_invalid_v2_game_record_response",
      request_id: null,
    },
  });
}
