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
  exile_last_words_enabled?: boolean;
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
  invalid_value?: unknown;
  fallback_choice?: unknown;
  fallback_reason?: string | null;
  attempt_count?: number;
};

export type SpeechEntry = {
  speaker: string;
  message: string;
};

export type SheriffElectionResolution = {
  schema_version: number;
  outcome: "elected" | "badge_lost" | "postponed";
  reason_code: string;
  reason_text: string;
  sheriff: string | null;
  candidates: string[];
  withdrawn: string[];
  final_candidates: string[];
  voters: string[];
  votes: Record<string, string>;
  pk_candidates: string[];
  runoff_votes: Record<string, string>;
  badge_lost: boolean;
  election_pending: boolean;
};

export type SheriffBadgeResolution = {
  schema_version: number;
  outcome: "transferred" | "destroyed" | "lost_no_target";
  from_player: string;
  to_player: string | null;
  reason_code: string;
};

export type NarrationMode = "explicit_v1";

export type JudgeCuePayloadV1 = {
  schema_version: 1;
  cue_id: string;
  cue?: string;
  visible_text: string;
  static_asset_id: string | null;
  params: Record<string, unknown>;
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
  exile_pk_speech?: RawActionLog[];
  exile_runoff_votes?: RawActionLog[];
  exile_last_words?: RawActionLog | null;
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

export type ExileLastWords = {
  player: string;
  message: string;
  status: "completed" | "skipped" | string;
  reason_code: string;
};

export type PublicFact = {
  round_number: number;
  category: string;
  text: string;
  schema_version?: number;
  fact_id?: string;
  stage?: string | null;
  actor?: string | null;
  retention?: string;
  trust_class?: string;
  source_opportunity_id?: string | null;
  source_event_id?: string | null;
};

export type WerewolfDiscussionEntry = {
  round: number;
  stage?: "proposal" | string;
  speaker: string;
  target: string;
  message: string;
};

export type WerewolfVoteRound = {
  round: number;
  stage?: "discussion_consensus" | "final_vote" | string;
  candidates: string[];
  votes: Record<string, string>;
  tally: Record<string, number>;
  unanimous: boolean;
  result: string | null;
  tiebreak?: {
    triggered: boolean;
    actor: string;
    candidates: string[];
    choice: string;
    source: "model" | "existing_vote" | "seeded_fallback" | string;
  };
};

export type RawPlayer = {
  name: string;
  role: string;
  model: string;
  personality_id?: string;
  personality?: string;
  appearance_id?: string;
  avatar_prompt?: string;
  avatar_asset_id?: string | null;
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
  exile_pk_candidates?: string[];
  exile_pk_speeches?: SpeechEntry[];
  exile_runoff_votes?: Record<string, string>;
  exile_resolution_reason?: string | null;
  exile_last_words?: ExileLastWords | null;
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
  sheriff_election_resolution?: SheriffElectionResolution | null;
  sheriff_badge_resolution?: SheriffBadgeResolution | null;
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
  invalidValue?: unknown;
  fallbackChoice?: unknown;
  fallbackReason?: string | null;
  attemptCount?: number;
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
  | "exile_pk_candidates"
  | "exile_pk_speeches"
  | "exile_runoff_votes"
  | "exile_resolution_reason"
  | "exile_last_words"
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
  | "sheriff_election_resolution"
  | "sheriff_badge_resolution"
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
  exile_pk_candidates: string[];
  exile_pk_speeches: SpeechEntry[];
  exile_runoff_votes: Record<string, string>;
  exile_resolution_reason: string | null;
  exile_last_words: ExileLastWords | null;
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
  sheriff_election_resolution: SheriffElectionResolution | null;
  sheriff_badge_resolution: SheriffBadgeResolution | null;
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

export type GameRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "canceled";

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
  display_order: number;
  favorite: boolean;
  appearance_id: string;
  avatar_prompt: string;
  avatar_asset_id: string | null;
  avatar_image_url: string;
  avatar_image_mime: string;
  tags: string[];
  created_at: string;
  updated_at: string;
};

export type PlayerProfilesResponse = {
  profiles: VirtualPlayerProfile[];
};

export type PublicPlayerProfile = {
  id: string;
  display_name: string;
  model: string;
  personality_id: string;
  personality_text: string;
  appearance_id: string;
  avatar_image_url: string;
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
  display_order: number;
  featured: boolean;
  tags: string[];
};

export type PaginationResponse = {
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

export type PublicPlayerProfileListResponse = {
  items: PublicPlayerProfile[];
  pagination: PaginationResponse;
};

export type PublicPlayerProfileWithFavorite = PublicPlayerProfile & {
  is_favorite: boolean;
};

export type PublicViewer = {
  kind: "guest";
};

export type PublicSessionResponse = {
  viewer: PublicViewer;
  csrf_token: string;
  session_expires_at: string;
};

export type PlayerProfileFavoritesResponse = {
  profile_ids: string[];
};

export type PlayerProfileFavoriteMutationResponse = {
  profile_id: string;
  is_favorite: boolean;
};

export type PlayerAvatarUploadResponse = {
  avatar_asset_id: string;
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
  avatar_asset_id?: string | null;
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
  avatar_asset_id: "",
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
  avatar_asset_id?: string | null;
  catchphrases?: string[];
  strategy_profile?: string;
  tags?: string[];
};

export type LineupQualityWarning = {
  code: string;
  detail: string;
};

export type LineupQualityViolation = {
  code: string;
  severity: "warning" | "error";
  key: string;
  count: number;
  limit: number;
  seat_numbers: number[];
};

export type LineupQualityReport = {
  schema_version: 1;
  policy_mode: "observe" | "repair" | "enforce";
  player_count: number;
  configured_count: number;
  is_blocked: boolean;
  was_repaired: boolean;
  style_bucket_count: number;
  required_style_bucket_count: number;
  violations: LineupQualityViolation[];
};

export type LineupPreviewRequest = {
  rule_set_id: string;
  expected_rule_revision_id?: string | null;
  seed?: number | null;
  player_configs?: PlayerConfig[];
  locked_seats?: number[];
  repair_scope?: "empty_only" | "unlocked_all";
  lineup_quality_policy_version?: 1;
};

export type LineupPreviewResponse = {
  player_configs: PlayerConfig[];
  lineup_quality_report: LineupQualityReport;
  rule_set_revision_id: string | null;
};

export type GameRun = {
  run_id: string;
  session_id: string;
  villager_model: string;
  werewolf_model: string;
  rule_set?: RuleSetSummary | null;
  seed: number | null;
  max_rounds: number;
  parent_run_id?: string | null;
  resume_from_round?: number | null;
  attempt_no?: number;
  winner: string | null;
  status: GameRunStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  event_count: number;
  player_configs?: PlayerConfig[];
  lineup_quality_warnings?: LineupQualityWarning[];
  lineup_quality_report?: LineupQualityReport;
};

export type CreateGameRunRequest = {
  villager_model?: string;
  werewolf_model?: string;
  rule_set_id?: string;
  seed?: number | null;
  max_rounds?: number;
  player_configs?: PlayerConfig[];
  lineup_quality_policy_version?: 1;
  allow_lineup_quality_warnings?: boolean;
};

export type PublicActionOrigin =
  | "model"
  | "model_retry"
  | "system_fallback"
  | "rule_default"
  | "state_machine"
  | "none"
  | "canceled"
  | "legacy_unknown"
  | (string & {});

export type PublicPhaseCompletionStatus =
  | "completed"
  | "skipped"
  | "canceled"
  | "terminal"
  | (string & {});

export type PublicSpeechStatus =
  | "spoken"
  | "not_spoken"
  | "canceled"
  | (string & {});

export type LiveGameEvent = {
  id: number;
  source_run_id?: string;
  source_event_id?: number;
  audience?: "player_public" | "spectator_god_view";
  projection_version?: number;
  timeline_version?: "session-timeline-v1";
  type: string;
  run_id: string;
  session_id: string;
  created_at: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  /** Public-safe lifecycle/provenance fields. Older events may only carry these in payload. */
  phase_instance_id?: string | null;
  completion_status?: PublicPhaseCompletionStatus | null;
  completion_reason?: string | null;
  action_origin?: PublicActionOrigin | null;
  public_reason_code?: string | null;
  speech_status?: PublicSpeechStatus | null;
  payload: Record<string, unknown>;
};

export type PlaybackVoiceChunk = {
  chunk_index: number;
  data: string;
};

export type PlaybackVoiceSubtitleCue = {
  end_ms: number;
  start_ms: number;
  text: string;
};

export type PlaybackVoiceUtterance = {
  utterance_id: string;
  audience?: "player_public" | "spectator_god_view";
  source_event_id: number;
  last_source_event_id: number;
  speech_id?: string | null;
  segment_id?: string | null;
  segment_index?: number | null;
  segment_final?: boolean | null;
  presentation_id?: string;
  speaker_kind: "player" | "judge";
  speaker_name: string;
  mime_type: string;
  audio_format: string;
  sample_rate: number;
  duration_ms: number | null;
  subtitle_timings: PlaybackVoiceSubtitleCue[];
  chunks?: PlaybackVoiceChunk[];
};

export type GamePlayback = {
  session_id: string;
  status: GameStatus;
  rule_set?: RuleSetSummary | null;
  resumable?: boolean;
  events: LiveGameEvent[];
  voices: PlaybackVoiceUtterance[];
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
