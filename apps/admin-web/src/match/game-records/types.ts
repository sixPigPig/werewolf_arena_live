export type V2AudioMode = "tts" | "text_only" | "legacy_unknown";
export type V2MatchStatus =
  | "waiting"
  | "running"
  | "completed"
  | "failed"
  | "canceled";
export type V2ExecutionState = "unowned" | "owned" | "stale" | "stopped";

export type V2GameRecordListItem = {
  game_id: string;
  title: string;
  status: string;
  current_run_id: string;
  record_schema_version: number;
  last_record_seq: number;
  last_presentation_seq: number;
  phase_seq: number;
  phase_id: string;
  phase_state: string;
  audio_mode: V2AudioMode;
  match_status: V2MatchStatus;
  execution_state: V2ExecutionState;
  winner: "villagers" | "werewolves" | null;
  completion_reason: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type V2GameRecordList = {
  items: V2GameRecordListItem[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    pages: number;
  };
};

export type V2GameRun = {
  run_id: string;
  attempt_no: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  stop_requested_at: string | null;
  worker_id: string | null;
  worker_heartbeat_at: string | null;
  lease_expires_at: string | null;
  fence_token: number;
};

export type V2GameControlResult = {
  action: "stop";
  game_id: string;
  run_id: string;
  run_status: string;
  stop_requested_at: string;
  replayed: boolean;
};

export type V2ModelActionRetryResult = {
  action: "retry_model_action";
  game_id: string;
  run_id: string;
  run_status: string;
  action_id: string;
  replayed: boolean;
};

export type V2GameRecordEvent = {
  event_id: number;
  record_seq: number;
  run_id: string;
  event_type: string;
  payload_schema_version: number;
  payload: Record<string, unknown>;
  created_at: string;
};

export type V2GameEventPage = {
  items: V2GameRecordEvent[];
  after_record_seq: number;
  next_after_record_seq: number;
  has_more: boolean;
};

export type V2GamePresentation = {
  presentation_seq: number;
  presentation_id: string;
  action_id: string | null;
  activation_id: string | null;
  phase_id: string;
  actor_kind: string;
  actor_id: string;
  audience: string;
  speech_id: string;
  segment_index: number;
  source_event_id: number;
  state: string;
  subtitle_text: string;
  voice_asset_id: string | null;
  audio_duration_ms: number | null;
  created_at: string;
  closed_at: string | null;
};

export type V2VoiceAsset = {
  voice_asset_id: string;
  action_id: string;
  activation_id: string | null;
  audience: string;
  presentation_id: string;
  speech_id: string;
  segment_index: number;
  state: string;
  mime_type: string;
  sample_rate: number;
  channels: number;
  sample_count: number | null;
  duration_ms: number | null;
  pcm_sha256: string | null;
  size_bytes: number | null;
  audio_url: string | null;
  created_at: string;
  completed_at: string | null;
};

export type V2DerivationRejection = Record<string, unknown> & {
  source_event_ref: string;
  kind: string;
  reason: string;
  missing_fields?: string[];
};

export type V2MemorySelectorAuditEntry = {
  event_ref: string;
  category: string;
  reason: string;
};

export type V2MemorySelectorFutureFilteredEntry = {
  event_ref: string;
  reason: string;
};

export type V2MemorySelectorAudit = {
  version: 3;
  source_count: number;
  retained_count: number;
  omitted_count: number;
  future_filtered_count: number;
  retained: V2MemorySelectorAuditEntry[];
  omitted: V2MemorySelectorAuditEntry[];
  future_filtered: V2MemorySelectorFutureFilteredEntry[];
  latest_actor_memory_ref: string | null;
  latest_actor_memory_cutoff_seq: number | null;
  latest_actor_memory_hash: string | null;
  source_type_counts: Record<string, number>;
  retained_type_counts: Record<string, number>;
  omitted_type_counts: Record<string, number>;
};

export type V2PromptProjection = Record<string, unknown> & {
  model_context_schema_version?: number | null;
  prompt_template_version?: number | null;
  known_events_schema_version?: number | null;
  ledger_schema_version?: number | null;
  model_view_schema_version?: number | null;
  model_view_selector_version?: number | null;
  serialized_char_count?: number;
  section_char_counts?: Record<string, number>;
  ledger_statement_count?: number;
  ledger_statement_char_count?: number;
  ledger_claim_count?: number;
  ledger_question_count?: number;
  ledger_relation_count?: number;
  source_event_count?: number;
  emitted_event_count?: number;
  future_filtered_event_count?: number;
  source_claim_candidate_count?: number;
  emitted_claim_count?: number;
  out_of_scope_claim_count?: number;
  rejected_claim_count?: number;
  source_question_count?: number;
  current_scope_question_count?: number;
  emitted_question_count?: number;
  out_of_scope_question_count?: number;
  invalid_question_count?: number;
  source_relation_count?: number;
  emitted_relation_count?: number;
  invalid_relation_count?: number;
  budget_dropped_event_count?: number;
  none_detected_question_count?: number;
  response_detected_question_count?: number;
  awaiting_scheduled_turn_question_count?: number;
  current_round_statement_count?: number;
  current_round_statement_char_count?: number;
  derivation_rejections?: V2DerivationRejection[];
  known_event_record_seq_min?: number | null;
  known_event_record_seq_max?: number | null;
  canonical_serialized_char_count?: number;
  compact_serialized_char_count?: number;
  compaction_saved_chars?: number;
  compaction_ratio?: number;
  verbatim_speech_count?: number;
  verbatim_speech_chars?: number;
  retained_event_refs?: string[];
  canonical_sha256?: string;
  round_trip_verified?: boolean;
  lossless_scope?: "selector_retained_projection";
  selector?: V2MemorySelectorAudit;
};

export type V2OutputEnforcementAudit = {
  requested: string | null;
  actual: string | null;
  schema_name: string | null;
  schema_version: number | null;
};

export type V2ProviderUsage = {
  input_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  total_tokens?: number;
  cached_input_tokens?: number;
};

export type V2ModelFinishReason =
  | "completed"
  | "stop"
  | "length"
  | "max_output_tokens"
  | "content_filter"
  | "tool_calls"
  | "unknown";

export type V2ModelFailureResolution =
  | "automatic_retry_success"
  | "technical_skip"
  | "technical_false_fallback"
  | "operator_pause"
  | "isolated_action_failure"
  | "run_failure"
  | "run_canceled"
  | "unresolved"
  | "invariant_conflict"
  | "legacy_unavailable";

export type V2ModelFailureImpact =
  | "expected_control_flow"
  | "user_visible_degradation"
  | "operational_failure";

export type V2FailureEpisodeEventRef = {
  event_type: string;
  event_id: number | string | null;
  record_seq: number;
};

export type V2ModelRequestAudienceSource =
  | "event_contract"
  | "event_contract_narrowed"
  | "presentation"
  | "legacy_event"
  | "action_context"
  | "legacy_unknown";

export type V2ModelRequestSummary = {
  attempt_id: string;
  decision_family_id: string | null;
  retry_scope:
    | "action"
    | "same_action"
    | "batch_initial"
    | "batch_recovery"
    | "operator_retry";
  vote_batch_stage: string | null;
  automatic_machine_format_attempt_count: number | null;
  automatic_machine_format_budget: number | null;
  prior_output_budget_failures: number | null;
  output_budget_failure_count: number | null;
  automatic_output_budget_attempt_count: number | null;
  automatic_output_budget_budget: number | null;
  attempt_no: number;
  cycle_attempt_no: number;
  retry_cycle: number;
  max_attempts: number;
  retry_of_attempt_id: string | null;
  record_seq: number;
  last_record_seq: number;
  action_id: string;
  run_id: string;
  phase_id: string;
  action_type: string;
  actor_kind: string;
  actor_id: string;
  audience: string;
  stored_audience: string | null;
  effective_audience: string;
  audience_source: V2ModelRequestAudienceSource;
  request_kind: string;
  model_id: string | null;
  model_provider: string | null;
  judge_configuration_version: number | null;
  prompt_schema_version: number | null;
  model_context_schema_version: number | null;
  prompt_template_version: number | null;
  model_view_selector_version: number | null;
  prompt_projection: V2PromptProjection | null;
  status: "running" | "succeeded" | "failed" | "skipped" | "canceled";
  input_source: "persisted" | "reconstructed" | "unavailable";
  passive_observation_count: number;
  output_source: "persisted" | "legacy_inferred" | "unavailable";
  provider_request_id: string | null;
  model_generation_policy_contract_status:
    | "supported"
    | "legacy_disabled"
    | null;
  model_generation_policy_schema_version: number | null;
  model_generation_policy_classification_version: number | null;
  model_generation_policy_enforcement: "observe_only" | "disabled" | null;
  model_generation_policy_reasoning_parameter_mode:
    | "inherit_frozen_model_configuration"
    | null;
  model_generation_policy_profile:
    | "strategic_full"
    | "recoverable_public_speech"
    | "isolated_auxiliary"
    | null;
  model_generation_policy_profile_source:
    | "explicit_action_profile"
    | "default_profile"
    | "legacy_missing_contract"
    | null;
  reasoning_only_timeout_ms: number | null;
  timeout_max_attempts: number | null;
  shadow_would_timeout: boolean | null;
  finish_reason: V2ModelFinishReason | null;
  provider_usage: V2ProviderUsage | null;
  usage_update_count: number | null;
  usage_conflict_observed: boolean | null;
  usage_consistency:
    | "exact"
    | "provider_total_mismatch"
    | "unavailable"
    | null;
  queue_wait_ms: number | null;
  provider_in_flight: number | null;
  provider_concurrency_limit: number | null;
  first_token_ms: number | null;
  reasoning_only_elapsed_ms: number | null;
  completed_ms: number | null;
  reasoning_delta_count: number | null;
  text_delta_count: number | null;
  max_inter_delta_ms: number | null;
  last_progress_ms: number | null;
  failure_kind: string | null;
  failure_code: string | null;
  failure_category?: string | null;
  failure_impact: V2ModelFailureImpact | null;
  counts_as_failure: boolean;
  repair_kind?: string | null;
  output_enforcement?: V2OutputEnforcementAudit | null;
  application_validation_result?: "accepted" | "rejected" | null;
  retryable: boolean | null;
  terminal: boolean | null;
  failure_stage: string | null;
  exception_type: string | null;
  errno: number | null;
  http_status: number | null;
  first_token_seen: boolean | null;
  response_headers_seen: boolean | null;
  response_headers: Record<string, string> | null;
  first_token_kind: string | null;
  first_visible_text_ms: number | null;
  timeout_scope: string | null;
  failure_elapsed_ms: number | null;
  attempt_budget_ms: number | null;
  action_budget_ms: number | null;
  action_elapsed_ms: number | null;
  action_remaining_ms: number | null;
  effective_attempt_limit: number | null;
  retry_delay_ms: number | null;
  required_retry_window_ms: number | null;
  automatic_retry_scheduled: boolean | null;
  automatic_retry_stop_reason:
    | "not_retryable"
    | "decision_family_budget_exhausted"
    | "attempt_limit_reached"
    | "insufficient_action_budget"
    | null;
  failure_episode_id: string | null;
  failure_resolution: V2ModelFailureResolution | null;
  failure_episode_source_attempt_ids: string[] | null;
  failure_episode_source_event_refs: V2FailureEpisodeEventRef[] | null;
  failure_episode_terminal_event_refs: V2FailureEpisodeEventRef[] | null;
  resolution_event_type: string | null;
  resolution_event_id: number | null;
  resolution_event_record_seq: number | null;
  supporting_event_type: string | null;
  supporting_event_id: number | null;
  supporting_event_record_seq: number | null;
  resolution_updated_at_record_seq: number | null;
  failure_episode_invariant_errors: string[] | null;
  model_binding_failure_streak: number | null;
  model_binding_health_status: "healthy" | "impaired" | "degraded" | null;
  model_binding_recovered_after_failures: number | null;
  started_at: string;
  completed_at: string | null;
};

export type V2ModelRequest = V2ModelRequestSummary & {
  request_payload: Record<string, unknown> | null;
  expanded_known_events: Record<string, unknown> | null;
  known_events_expansion_status:
    | "verified"
    | "not_applicable"
    | "unavailable"
    | "invalid";
  raw_response: string | null;
  parsed_output: Record<string, unknown> | null;
  passive_observations: Array<Record<string, unknown>>;
  stream_reasoning: string | null;
  stream_text: string | null;
  stream_reasoning_character_count: number;
  stream_text_character_count: number;
  stream_estimated_reasoning_tokens: number | null;
  stream_estimated_output_tokens: number | null;
  stream_content_truncated: boolean;
  stream_progress_updated_at: string | null;
};

export type V2ModelRequestPage = {
  items: V2ModelRequestSummary[];
  after_record_seq: number;
  next_after_record_seq: number;
  has_more: boolean;
};

export type V2PlayerIdentity = {
  seat: number;
  player_id: string;
  display_name: string;
  avatar_url: string | null;
  role: string;
  team: string | null;
  alive: boolean;
  death_cause: string | null;
};

export type V2GameRecordSummary = V2GameRecordListItem & {
  rule_snapshot: Record<string, unknown>;
  players_snapshot: Array<Record<string, unknown>>;
  judge_voice_snapshot: Record<string, unknown>;
  delivery_snapshot: Record<string, unknown> | null;
  ability_snapshot: Record<string, unknown>;
  match_state: Record<string, unknown> | null;
  player_identities: V2PlayerIdentity[];
  runs: V2GameRun[];
  presentations: V2GamePresentation[];
  voice_assets: V2VoiceAsset[];
  player_states: Array<Record<string, unknown>>;
  action_windows: Array<Record<string, unknown>>;
  ability_instances: Array<Record<string, unknown>>;
  ability_activations: Array<Record<string, unknown>>;
  effect_intents: Array<Record<string, unknown>>;
  knowledge_facts: Array<Record<string, unknown>>;
};

export type V2GameRecordDetail = V2GameRecordSummary & {
  events: V2GameRecordEvent[];
  model_requests: V2ModelRequestSummary[];
};
