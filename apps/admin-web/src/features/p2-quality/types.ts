export type AdminP2DataStatus =
  | "legacy"
  | "collecting"
  | "available"
  | "unavailable";

export type AdminP2Performance = {
  request_count: number;
  discrete_action_sample_count: number;
  discrete_action_p50_ms: number | null;
  discrete_action_p95_ms: number | null;
  discrete_action_max_ms: number | null;
  speech_first_token_sample_count: number;
  speech_first_token_p95_ms: number | null;
  speech_first_token_max_ms: number | null;
  timeout_count: number;
  fallback_count: number;
  active_request_count: number;
  game_duration_ms: number | null;
};

export type AdminP2SpeechQuality = {
  checked_count: number;
  retry_count: number;
  exhausted_count: number;
  low_novelty_window_count: number;
};

export type AdminP2ChoiceNormalization = {
  exact_count: number;
  seat_alias_count: number;
  public_label_count: number;
  invalid_count: number;
  other_count: number;
};

export type AdminP2ProviderAttemptOutcomes = {
  attempt_count: number;
  valid_response_count: number;
  invalid_response_count: number;
  timed_out_count: number;
  canceled_count: number;
  transport_failed_count: number;
};

export type AdminP2LogicalActionOutcomes = {
  action_count: number;
  completed_count: number;
  fallback_count: number;
  canceled_count: number;
  failed_count: number;
};

export type AdminRunP2Diagnostics = {
  schema_version: 1;
  data_status: AdminP2DataStatus;
  performance: AdminP2Performance;
  speech_quality: AdminP2SpeechQuality;
  choice_normalization: AdminP2ChoiceNormalization;
  provider_attempt_outcomes: AdminP2ProviderAttemptOutcomes | null;
  logical_action_outcomes: AdminP2LogicalActionOutcomes | null;
};

export type AdminP2LineupViolation = {
  code: string;
  severity: "warning" | "error";
  count: number;
  limit: number;
  seat_numbers: number[];
};

export type AdminP2LineupQuality = {
  policy_mode: "observe" | "repair" | "enforce" | null;
  was_repaired: boolean | null;
  is_blocked: boolean | null;
  style_bucket_count: number | null;
  required_style_bucket_count: number | null;
  violations: AdminP2LineupViolation[];
};

export type AdminP2QualityGate = {
  gate: string;
  status: "pass" | "warn" | "fail" | "unavailable";
  code: string;
  threshold: string | null;
  actual: string | null;
};

export type AdminPublicOutcome = {
  schema_version: 1;
  round_number: number;
  event_id: string;
  sequence: number;
  kind:
    | "night_death"
    | "hunter_shot"
    | "self_explosion"
    | "exile"
    | "idiot_reveal"
    | "badge_transferred"
    | "badge_lost";
  actor_player_id: string | null;
  target_player_id: string | null;
  outcome: string;
  caused_by_event_id: string | null;
  occurred_phase: string;
};

export type AdminGameP2Quality = AdminRunP2Diagnostics & {
  lineup_quality: AdminP2LineupQuality;
  public_outcomes: AdminPublicOutcome[];
  public_outcome_summary_mismatch_count: number;
  quality_gates: AdminP2QualityGate[];
};
