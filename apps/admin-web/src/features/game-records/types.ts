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
  public_summary: string;
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

export type AdminGameDetail = AdminGameListItem & {
  players: AdminGamePlayer[];
  rounds: AdminGameRound[];
  runs: AdminGameRun[];
  diagnostics: AdminGameDiagnostics;
  recent_events: AdminGameEvent[];
};
