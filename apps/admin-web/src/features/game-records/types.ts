export type GameSessionStatus = "complete" | "partial";

export type LiveRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "canceled";

export type AdminGameSortField = "created_at" | "updated_at";

export type AdminGameListParams = {
  page: number;
  page_size: number;
  q?: string;
  status?: GameSessionStatus;
  run_status?: LiveRunStatus;
  winner?: string;
  rule_set_id?: string;
  created_from?: string;
  created_to?: string;
  sort: AdminGameSortField;
  direction: "asc" | "desc";
};

export type AdminGamePagination = {
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

export type AdminGameRuleSet = {
  id: string;
  name: string;
  player_count: number | null;
};

export type AdminGameRun = {
  run_id: string;
  status: LiveRunStatus;
  villager_model: string | null;
  werewolf_model: string | null;
  max_rounds: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  event_count: number;
  has_error: boolean;
};

export type AdminGameListItem = {
  session_id: string;
  status: GameSessionStatus;
  winner: string | null;
  round_count: number;
  rule_set: AdminGameRuleSet | null;
  resumable: boolean;
  created_at: string;
  updated_at: string;
  latest_run: AdminGameRun | null;
};

export type AdminGameList = {
  items: AdminGameListItem[];
  pagination: AdminGamePagination;
};

export type AdminGamePlayer = {
  seat: number;
  name: string;
  role: string | null;
  model: string | null;
  profile_id: string | null;
  personality_id: string;
  appearance_id: string;
  avatar_image_url: string;
  tags: string[];
};

export type AdminGameRound = {
  number: number;
  success: boolean;
  players: string[];
  night_deaths: AdminGameDeath[];
  day_deaths: AdminGameDeath[];
  exiled: string | null;
  hunter_shot: string | null;
  idiot_revealed: string | null;
  sheriff: string | null;
  votes: Record<string, string>;
  sheriff_elected: string | null;
  werewolf_self_exploded: string | null;
  sheriff_candidates: string[];
  sheriff_withdrawn: string[];
  sheriff_final_candidates: string[];
  sheriff_votes: Record<string, string>;
  sheriff_pk_candidates: string[];
  sheriff_runoff_votes: Record<string, string>;
  exile_pk_candidates: string[];
  exile_runoff_votes: Record<string, string>;
  exile_resolution_reason: string | null;
  sheriff_speech_order: string[];
  sheriff_speech_direction: string | null;
  speech_order: string[];
  speech_order_choice: string | null;
  sheriff_speeches: AdminGameSpeech[];
  sheriff_pk_speeches: AdminGameSpeech[];
  exile_pk_speeches: AdminGameSpeech[];
  debate: AdminGameSpeech[];
  sheriff_badge_target: string | null;
  sheriff_badge_lost: boolean;
  sheriff_badge_lost_reason: string | null;
  day_ended_by_self_explosion: boolean;
  public_summary: string;
};

export type AdminGameSpeech = {
  speaker: string;
  message: string;
};

export type AdminGameDeath = {
  player: string;
  cause: string | null;
  source: string | null;
};

export type AdminGameEvent = {
  run_id: string;
  event_id: number;
  type: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  created_at: string;
};

export type AdminGameDiagnostics = {
  run_count: number;
  event_count: number;
  failed_voice_count: number;
  last_event: AdminGameEvent | null;
};

export type AdminGameDebug = {
  session_id: string;
  game_error: string | null;
  run_errors: Array<{ run_id: string; error: string }>;
};

export type AdminGameModelRequestStatus =
  | "pending"
  | "completed"
  | "failed"
  | "response_missing";

export type AdminGameModelRequestSummary = {
  request_id: string;
  round_number: number | null;
  phase: string | null;
  actor: string | null;
  action: string;
  model: string | null;
  status: AdminGameModelRequestStatus;
  attempt_count: number;
  invalid_attempt_count: number;
  run_id: string | null;
  event_id: number | null;
  created_at: string | null;
};

export type AdminGameModelRequestList = {
  session_id: string;
  items: AdminGameModelRequestSummary[];
};

export type AdminGameModelRequestDetail = AdminGameModelRequestSummary & {
  prompt: string | null;
  raw_response: string | null;
  parsed_output: string | null;
  raw_choice: string | null;
  error: string | null;
};

export type AdminQualityEvaluationStatus =
  | "not_scheduled"
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "superseded";

export type AdminQualityDataStatus =
  | "collecting"
  | "available"
  | "partial"
  | "legacy"
  | "unavailable";

export type AdminGameQualityEvaluation = {
  schema_version: 1;
  evaluator_version: string;
  evaluation_status: AdminQualityEvaluationStatus;
  data_status: AdminQualityDataStatus;
  verdict: "pass" | "warn" | "fail" | "unavailable";
  source_coverage: {
    state: string;
    logs: string;
    events: string;
    voice: string;
    subtitles: string;
    pending_voice_count: number;
    failed_voice_count: number;
  };
  issue_counts: { P0: number; P1: number; P2: number };
  facts: {
    critical_opportunity_count: number;
    critical_recorded_count: number;
    critical_fact_write_rate: number | null;
    prompt_expected_critical_count: number;
    prompt_included_critical_count: number;
    prompt_missing_critical_count: number;
    critical_fact_prompt_coverage_rate: number | null;
    deterministic_contradiction_count: number;
  };
  structure: {
    max_consecutive_self_explosions: number;
    chain_three_count: number;
    normal_day_debate_round_count: number;
    sheriff_model_request_count: number;
    public_model_request_count: number;
    sheriff_model_request_rate: number | null;
  };
  voice: {
    narratable_event_count: number;
    effective_voice_event_count: number;
    missing_narratable_event_count: number;
    voice_coverage_rate: number | null;
    voice_source_event_lag: number | null;
    terminal_judge_voice_coverage: boolean | null;
    pending_voice_count: number;
    failed_voice_count: number;
    interruption_count: number;
    replay_count: number;
  };
  performance: {
    action_count: number;
    action_duration_ms_max: number | null;
    action_duration_p95_ms: number | null;
    first_token_count: number;
    first_token_ms_max: number | null;
    first_token_p95_ms: number | null;
    game_duration_ms: number | null;
    timeout_count: number;
    retry_count: number;
    fallback_count: number;
  };
  content: {
    speech_check_count: number;
    repeated_speech_count: number;
    repeated_speech_rate: number | null;
    speech_rewrite_count: number;
    speech_rewrite_recovered_count: number;
    speech_retry_exhausted_count: number;
    privacy_p0_issue_count: number;
    lineup_warning_count: number;
  };
  evaluated_at: string | null;
};

export type AdminGameQualityIssue = {
  issue_id: string;
  code: string;
  severity: "P0" | "P1" | "P2";
  channel: string;
  round_number: number | null;
  event_id: number | null;
  utterance_id: string | null;
  first_detected_at: string;
};

export type AdminGameQualityIssues = {
  session_id: string;
  evaluation_id: string | null;
  items: AdminGameQualityIssue[];
};

export type AdminGameQualityRetry = {
  session_id: string;
  evaluation_id: string;
  status: "pending";
};

export type AdminGameDetail = AdminGameListItem & {
  players: AdminGamePlayer[];
  rounds: AdminGameRound[];
  runs: AdminGameRun[];
  diagnostics: AdminGameDiagnostics;
  recent_events: AdminGameEvent[];
  p2_quality: AdminGameP2Quality;
  quality_evaluation: AdminGameQualityEvaluation;
};
import type { AdminGameP2Quality } from "@/features/p2-quality/types";
