export type HealthResponse = {
  status: string;
};

export type RoleSpecSummary = {
  role: string;
  count: number;
  team?: string;
  model_group?: string;
  category?: string;
};

export type RuleSetSummary = {
  id: string;
  version: string;
  name: string;
  description?: string;
  player_count: number;
  roles: RoleSpecSummary[];
  sheriff_enabled?: boolean;
  role_summary?: string;
  estimated_duration?: string;
};

export type RuleSetsResponse = {
  rule_sets: RuleSetSummary[];
};

export type ModelOption = {
  id: string;
  label: string;
};

export type ModelOptionsResponse = {
  models: ModelOption[];
};

export type PlayerProfile = {
  id: string;
  display_name: string;
  model: string;
  personality_id: string;
  appearance_id: string;
  avatar_image_url: string;
  short_description: string;
  favorite: boolean;
  tags: string[];
  updated_at: string;
};

export type PlayerProfileListResponse = {
  profiles: PlayerProfile[];
};

export type CreatePlayerConfigRequest = {
  seat: number;
  profile_id?: string;
  name?: string;
  display_name?: string;
  model?: string;
};

export type CreateGameRunRequest = {
  villager_model?: string;
  werewolf_model?: string;
  seed?: number;
  max_rounds?: number;
  rule_set_id?: string;
  player_configs?: CreatePlayerConfigRequest[];
};

export type GameRunStatus = "queued" | "running" | "completed" | "failed";

export type PlayerConfig = {
  seat: number;
  profile_id?: string | null;
  name?: string | null;
  model?: string | null;
  personality_id?: string;
  personality?: string;
  appearance_id?: string;
  avatar_prompt?: string;
  avatar_image_url?: string;
  tags?: string[];
};

export type LineupQualityWarning = {
  code: string;
  detail: string;
};

export type GameRun = {
  run_id: string;
  session_id: string;
  villager_model: string;
  werewolf_model: string;
  seed: number | null;
  max_rounds: number;
  rule_set_id: string;
  rule_set: RuleSetSummary;
  player_configs: PlayerConfig[];
  lineup_quality_warnings: LineupQualityWarning[];
  status: GameRunStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  winner: string | null;
  error: string | null;
  event_count: number;
};

export type GameSessionStatus = "complete" | "partial";

export type GameSessionSummary = {
  session_id: string;
  status: GameSessionStatus;
  winner: string | null;
  round_count: number;
  created_at: string | null;
  rule_set?: RuleSetSummary | null;
  resumable?: boolean;
};

export type GameSessionsResponse = {
  sessions: GameSessionSummary[];
};

export type LiveGameEvent = {
  id: number;
  type: string;
  run_id: string;
  session_id: string;
  created_at: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  payload: Record<string, unknown>;
};

export type GamePlaybackResponse = {
  session_id: string;
  status: GameSessionStatus;
  rule_set?: RuleSetSummary | null;
  resumable: boolean;
  events: LiveGameEvent[];
};
