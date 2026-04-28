export type GameStatus = "complete" | "partial";

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
  night_actions?: string[];
  day_actions?: string[];
  win_condition?: string;
  reveal_policy?: string;
  complexity?: string;
  estimated_duration?: string;
  role_summary?: string;
  sheriff_enabled?: boolean;
  sheriff_vote_weight?: number;
  speech_policy?: "sequential" | "sheriff_directed" | string;
  speech_rounds?: number;
  rule_tags?: string[];
};

export type RuleSetsResponse = {
  rule_sets: RuleSetSummary[];
};

export type GameSessionSummary = {
  session_id: string;
  status: GameStatus;
  winner: string | null;
  round_count: number;
  created_at: string | null;
  rule_set?: RuleSetSummary | null;
};

export type GameSessionsResponse = {
  sessions: GameSessionSummary[];
};

export type RawLmLog = {
  prompt?: string;
  raw_response?: string;
  result?: unknown;
};

export type RawActionLog = {
  actor: string;
  action: string;
  options: string[];
  choice: string | null;
  lm_log: RawLmLog;
};

export type RawRoundLog = {
  number: number;
  eliminate: RawActionLog | null;
  protect: RawActionLog | null;
  investigate: RawActionLog | null;
  witch_save?: RawActionLog | null;
  witch_poison?: RawActionLog | null;
  hunter_shoot?: RawActionLog | null;
  sheriff_run?: RawActionLog[];
  sheriff_votes?: RawActionLog[];
  speech_order?: RawActionLog | null;
  sheriff_badge?: RawActionLog | null;
  bid: RawActionLog[][];
  debate: RawActionLog[];
  votes: RawActionLog[][];
  summaries: RawActionLog[];
};

export type DeathEvent = {
  player: string;
  cause: string;
  source?: string | null;
};

export type RawPlayer = {
  name: string;
  role: string;
  model: string;
  observations?: string[];
  bidding_rationale?: string;
  gamestate?: unknown;
  known_roles?: Record<string, string>;
  is_sheriff?: boolean;
};

export type RawRoundState = {
  number: number;
  players: string[];
  attacked?: string | null;
  eliminated: string | null;
  protected: string | null;
  investigated: string | null;
  exiled: string | null;
  night_deaths?: DeathEvent[];
  day_deaths?: DeathEvent[];
  saved_by_witch?: string | null;
  poisoned?: string | null;
  hunter_shot?: string | null;
  idiot_revealed?: string | null;
  sheriff?: string | null;
  sheriff_candidates?: string[];
  sheriff_votes?: Record<string, string>;
  speech_order?: string[];
  speech_order_choice?: string | null;
  vote_weights?: Record<string, number>;
  sheriff_badge_target?: string | null;
  sheriff_badge_lost?: boolean;
  debate: Array<{ speaker: string; message: string }>;
  bids: Array<Record<string, number>>;
  votes: Array<Record<string, string>>;
  summaries: Record<string, string>;
  success: boolean;
};

export type RawGameState = {
  session_id: string;
  players: RawPlayer[];
  rounds: RawRoundState[];
  winner: string;
  error_message: string;
  rule_set?: RuleSetSummary | null;
  sheriff?: string | null;
  sheriff_badge_lost?: boolean;
};

export type RawGameReplayResponse = {
  session_id: string;
  status: GameStatus;
  state: RawGameState;
  logs: RawRoundLog[];
};

export type BidEntry = {
  actor: string;
  score: number;
};

export type BidGroup = {
  turn: number;
  speaker: string | null;
  bids: BidEntry[];
};

export type VoteEntry = {
  voter: string;
  target: string;
  weight: number;
};

export type VoteTallyEntry = {
  target: string;
  count: number;
};

export type DebugItem = {
  id: string;
  roundNumber: number;
  phase: "night" | "day" | "summary";
  title: string;
  actor: string;
  action: string;
  choice: string | null;
  prompt: string;
  rawResponse: string;
  parsed: unknown;
};

export type GameRound = Omit<
  RawRoundState,
  | "attacked"
  | "eliminated"
  | "bids"
  | "votes"
  | "night_deaths"
  | "day_deaths"
  | "saved_by_witch"
  | "poisoned"
  | "hunter_shot"
  | "idiot_revealed"
  | "sheriff"
  | "sheriff_candidates"
  | "sheriff_votes"
  | "speech_order"
  | "speech_order_choice"
  | "vote_weights"
  | "sheriff_badge_target"
  | "sheriff_badge_lost"
> & {
  attacked: string | null;
  eliminated: string | null;
  night_deaths: DeathEvent[];
  day_deaths: DeathEvent[];
  saved_by_witch: string | null;
  poisoned: string | null;
  hunter_shot: string | null;
  idiot_revealed: string | null;
  sheriff: string | null;
  sheriff_candidates: string[];
  sheriff_votes: Record<string, string>;
  speech_order: string[];
  speech_order_choice: string | null;
  vote_weights: Record<string, number>;
  sheriff_badge_target: string | null;
  sheriff_badge_lost: boolean;
  bids: BidEntry[];
  bidGroups: BidGroup[];
  votes: VoteEntry[];
  voteTally: VoteTallyEntry[];
  voteCount: number;
  voteMajorityThreshold: number | null;
};

export type GameReplay = {
  sessionId: string;
  status: GameStatus;
  winner: string;
  errorMessage: string;
  ruleSet?: RuleSetSummary | null;
  sheriff: string | null;
  sheriffBadgeLost: boolean;
  players: RawPlayer[];
  rounds: GameRound[];
  logs: RawRoundLog[];
  debugItems: DebugItem[];
};

export type GameRunStatus = "queued" | "running" | "completed" | "failed";

export type EventPacingMode = "off" | "standard" | "slow";

export type GameRun = {
  run_id: string;
  session_id: string;
  villager_model: string;
  werewolf_model: string;
  rule_set?: RuleSetSummary | null;
  seed: number | null;
  max_rounds: number;
  winner: string | null;
  status: GameRunStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  event_count: number;
  event_pacing: EventPacingMode;
};

export type CreateGameRunRequest = {
  villager_model?: string;
  werewolf_model?: string;
  rule_set_id?: string;
  seed?: number | null;
  max_rounds?: number;
  event_pacing?: EventPacingMode;
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
