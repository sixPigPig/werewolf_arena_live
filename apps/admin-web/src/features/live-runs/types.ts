export type AdminLiveRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "canceled";

export type AdminLiveRunSortField = "created_at" | "updated_at";

export type AdminLiveRunListParams = {
  page: number;
  page_size: number;
  q?: string;
  status?: AdminLiveRunStatus;
  rule_set_id?: string;
  created_from?: string;
  created_to?: string;
  sort: AdminLiveRunSortField;
  direction: "asc" | "desc";
};

export type AdminLiveRunPagination = {
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

export type AdminLiveRunRuleSet = {
  id: string;
  name: string;
  player_count: number | null;
};

export type AdminLiveRunVoiceCounts = {
  total: number;
  pending: number;
  synthesizing: number;
  complete: number;
  failed: number;
  canceled: number;
  other: number;
};

export type AdminLiveRunGame = {
  status: "complete" | "partial";
  resumable: boolean;
  terminal: boolean;
};

export type AdminLiveRunListItem = {
  run_id: string;
  session_id: string;
  status: AdminLiveRunStatus;
  winner: string | null;
  villager_model: string | null;
  werewolf_model: string | null;
  max_rounds: number;
  rule_set: AdminLiveRunRuleSet | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  stop_requested_at: string | null;
  updated_at: string;
  event_count: number;
  last_activity_at: string;
  is_stale: boolean;
  voice_counts: AdminLiveRunVoiceCounts;
  has_error: boolean;
  game: AdminLiveRunGame | null;
};

export type AdminLiveRunList = {
  items: AdminLiveRunListItem[];
  pagination: AdminLiveRunPagination;
};

export type AdminLiveRunEvent = {
  event_id: number;
  type: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  created_at: string;
};

export type AdminLiveRunDetail = AdminLiveRunListItem & {
  recent_events: AdminLiveRunEvent[];
};

export type AdminLiveRunDebug = {
  run_id: string;
  run_error: string | null;
  voice_error_total: number;
  voice_errors: Array<{
    utterance_id: string;
    error: string;
  }>;
  truncated: boolean;
};

export type AdminLiveRunControlAction = "stop" | "resume";

export type AdminLiveRunControlResult = {
  action: AdminLiveRunControlAction;
  target_run_id: string;
  run_id: string;
  session_id: string;
  run_status: AdminLiveRunStatus;
  stop_requested_at: string | null;
  replayed: boolean;
};
