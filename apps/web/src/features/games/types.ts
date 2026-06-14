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

export type ModelOption = {
  id: string;
  label: string;
};

export type ModelOptionsResponse = {
  models: ModelOption[];
};

export type GameSessionSummary = {
  session_id: string;
  status: GameStatus;
  winner: string | null;
  round_count: number;
  created_at: string | null;
  rule_set?: RuleSetSummary | null;
  resumable?: boolean;
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

export type SpeechEntry = {
  speaker: string;
  message: string;
};

export type RawRoundLog = {
  number: number;
  eliminate: RawActionLog | null;
  protect: RawActionLog | null;
  investigate: RawActionLog | null;
  werewolf_discussion?: RawActionLog[];
  werewolf_votes?: RawActionLog[][];
  witch_save?: RawActionLog | null;
  witch_poison?: RawActionLog | null;
  hunter_shoot?: RawActionLog | null;
  sheriff_run?: RawActionLog[];
  sheriff_speech?: RawActionLog[];
  sheriff_withdraw?: RawActionLog[];
  sheriff_votes?: RawActionLog[];
  sheriff_pk_speech?: RawActionLog[];
  sheriff_runoff_votes?: RawActionLog[];
  werewolf_self_explosion?: RawActionLog | null;
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

export type PublicFact = {
  round_number: number;
  category: string;
  text: string;
};

export type WerewolfDiscussionEntry = {
  round: number;
  speaker: string;
  target: string;
  message: string;
};

export type WerewolfVoteRound = {
  round: number;
  candidates: string[];
  votes: Record<string, string>;
  tally: Record<string, number>;
  unanimous: boolean;
  result: string | null;
};

export type RawPlayer = {
  name: string;
  role: string;
  model: string;
  personality_id?: string;
  personality?: string;
  appearance_id?: string;
  avatar_prompt?: string;
  avatar_image_url?: string;
  profile_id?: string | null;
  tags?: string[];
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
  werewolf_discussion?: WerewolfDiscussionEntry[];
  werewolf_vote_rounds?: WerewolfVoteRound[];
  saved_by_witch?: string | null;
  poisoned?: string | null;
  hunter_shot?: string | null;
  idiot_revealed?: string | null;
  sheriff?: string | null;
  sheriff_candidates?: string[];
  sheriff_speech_order?: string[];
  sheriff_speech_direction?: string | null;
  sheriff_speeches?: SpeechEntry[];
  sheriff_withdrawn?: string[];
  sheriff_final_candidates?: string[];
  sheriff_voters?: string[];
  sheriff_votes?: Record<string, string>;
  sheriff_pk_candidates?: string[];
  sheriff_pk_speeches?: SpeechEntry[];
  sheriff_runoff_votes?: Record<string, string>;
  sheriff_elected?: string | null;
  speech_order?: string[];
  speech_order_choice?: string | null;
  vote_weights?: Record<string, number>;
  sheriff_badge_target?: string | null;
  sheriff_badge_lost?: boolean;
  werewolf_self_exploded?: string | null;
  day_ended_by_self_explosion?: boolean;
  sheriff_pre_election_bomb_count?: number;
  sheriff_election_pending?: boolean;
  sheriff_badge_lost_reason?: string | null;
  debate: SpeechEntry[];
  bids: Array<Record<string, number>>;
  votes: Array<Record<string, string>>;
  summaries: Record<string, string>;
  private_summaries?: Record<string, string>;
  public_summary?: string;
  public_facts?: PublicFact[];
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
  | "werewolf_discussion"
  | "werewolf_vote_rounds"
  | "saved_by_witch"
  | "poisoned"
  | "hunter_shot"
  | "idiot_revealed"
  | "sheriff"
  | "sheriff_candidates"
  | "sheriff_speech_order"
  | "sheriff_speech_direction"
  | "sheriff_speeches"
  | "sheriff_withdrawn"
  | "sheriff_final_candidates"
  | "sheriff_voters"
  | "sheriff_votes"
  | "sheriff_pk_candidates"
  | "sheriff_pk_speeches"
  | "sheriff_runoff_votes"
  | "sheriff_elected"
  | "speech_order"
  | "speech_order_choice"
  | "vote_weights"
  | "sheriff_badge_target"
  | "sheriff_badge_lost"
  | "werewolf_self_exploded"
  | "day_ended_by_self_explosion"
  | "sheriff_pre_election_bomb_count"
  | "sheriff_election_pending"
  | "sheriff_badge_lost_reason"
> & {
  attacked: string | null;
  eliminated: string | null;
  night_deaths: DeathEvent[];
  day_deaths: DeathEvent[];
  werewolf_discussion: WerewolfDiscussionEntry[];
  werewolf_vote_rounds: WerewolfVoteRound[];
  saved_by_witch: string | null;
  poisoned: string | null;
  hunter_shot: string | null;
  idiot_revealed: string | null;
  sheriff: string | null;
  sheriff_candidates: string[];
  sheriff_speech_order: string[];
  sheriff_speech_direction: string | null;
  sheriff_speeches: SpeechEntry[];
  sheriff_withdrawn: string[];
  sheriff_final_candidates: string[];
  sheriff_voters: string[];
  sheriff_votes: Record<string, string>;
  sheriff_pk_candidates: string[];
  sheriff_pk_speeches: SpeechEntry[];
  sheriff_runoff_votes: Record<string, string>;
  sheriff_elected: string | null;
  speech_order: string[];
  speech_order_choice: string | null;
  vote_weights: Record<string, number>;
  sheriff_badge_target: string | null;
  sheriff_badge_lost: boolean;
  werewolf_self_exploded: string | null;
  day_ended_by_self_explosion: boolean;
  sheriff_pre_election_bomb_count: number;
  sheriff_election_pending: boolean;
  sheriff_badge_lost_reason: string | null;
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

export type VirtualPlayerProfile = {
  id: string;
  owner_user_id: number | null;
  display_name: string;
  model: string;
  personality_id: string;
  personality_text: string;
  short_description: string;
  background_story: string;
  speaking_style: string;
  catchphrases: string[];
  strategy_profile: string;
  risk_tolerance: number;
  bluffing_tendency: number;
  trust_tendency: number;
  leadership_tendency: number;
  talkativeness: number;
  example_messages: string[];
  favorite: boolean;
  appearance_id: string;
  avatar_prompt: string;
  avatar_image_url: string;
  avatar_image_mime: string;
  tags: string[];
  created_at: string;
  updated_at: string;
};

export type PlayerProfilesResponse = {
  profiles: VirtualPlayerProfile[];
};

export type PlayerAvatarUploadResponse = {
  avatar_image_url: string;
  avatar_image_mime: string;
};

export type PlayerProfileAiDraftMode = "name" | "template";

export type PlayerProfileAiDraftRequest = {
  mode: PlayerProfileAiDraftMode;
  existing_names: string[];
};

export type PlayerProfileAiDraftResponse = {
  display_name: string;
  personality_id?: string;
  personality_text?: string;
  short_description?: string;
  background_story?: string;
  speaking_style?: string;
  catchphrases?: string[];
  strategy_profile?: string;
  risk_tolerance?: number;
  bluffing_tendency?: number;
  trust_tendency?: number;
  leadership_tendency?: number;
  talkativeness?: number;
  example_messages?: string[];
  tags?: string[];
};

export type PlayerProfileRequest = {
  display_name: string;
  model: string;
  personality_id?: string;
  personality_text?: string;
  short_description?: string;
  background_story?: string;
  speaking_style?: string;
  catchphrases?: string[];
  strategy_profile?: string;
  risk_tolerance?: number;
  bluffing_tendency?: number;
  trust_tendency?: number;
  leadership_tendency?: number;
  talkativeness?: number;
  example_messages?: string[];
  favorite?: boolean;
  appearance_id?: string;
  avatar_prompt?: string;
  avatar_image_url?: string;
  avatar_image_mime?: string;
  tags?: string[];
};

export const DEFAULT_PLAYER_PROFILE_DRAFT: PlayerProfileRequest = {
  display_name: "",
  model: "",
  personality_id: "balanced",
  personality_text: "",
  short_description: "",
  background_story: "",
  speaking_style: "",
  catchphrases: [],
  strategy_profile: "balanced",
  risk_tolerance: 3,
  bluffing_tendency: 3,
  trust_tendency: 3,
  leadership_tendency: 3,
  talkativeness: 3,
  example_messages: [],
  favorite: false,
  appearance_id: "default",
  avatar_prompt: "",
  avatar_image_url: "",
  avatar_image_mime: "",
  tags: [],
};

export type UpdatePlayerProfileRequest = Partial<PlayerProfileRequest>;

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
  player_configs?: PlayerConfig[];
};

export type CreateGameRunRequest = {
  villager_model?: string;
  werewolf_model?: string;
  rule_set_id?: string;
  seed?: number | null;
  max_rounds?: number;
  player_configs?: PlayerConfig[];
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

export type GamePlayback = {
  session_id: string;
  status: GameStatus;
  rule_set?: RuleSetSummary | null;
  resumable?: boolean;
  events: LiveGameEvent[];
};

export type LiveStageRun = Pick<
  GameRun,
  | "run_id"
  | "session_id"
  | "status"
  | "rule_set"
  | "winner"
  | "error"
  | "created_at"
  | "started_at"
  | "completed_at"
  | "event_count"
> & {
  villager_model?: string;
  werewolf_model?: string;
  seed?: number | null;
  max_rounds?: number;
};
