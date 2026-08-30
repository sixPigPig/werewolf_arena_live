export type RoleSpecSummary = {
  role: string;
  count: number;
  team?: string;
  model_group?: string;
  category?: string;
};

export type WerewolfAttackPolicy = {
  resolution:
    | "plurality_rotating_tiebreak"
    | "plurality_seeded_random"
    | "unanimous_no_attack";
  allow_no_attack: boolean;
  allow_wolf_target: boolean;
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
  first_night_last_words_enabled?: boolean;
  werewolf_attack_policy?: WerewolfAttackPolicy | null;
  revision_id?: string;
  revision_no?: number;
  schema_version?: number;
  content_hash?: string;
  is_default?: boolean;
};

export type RuleSetsResponse = {
  rule_sets: RuleSetSummary[];
};

export type VirtualPlayerProfile = {
  id: string;
  display_name: string;
  model_provider: string;
  model: string;
  personality_id: string;
  personality_text: string;
  short_description: string;
  background_story: string;
  speaking_style: string;
  strategy_profile: string;
  risk_tolerance: number;
  bluffing_tendency: number;
  trust_tendency: number;
  leadership_tendency: number;
  talkativeness: number;
  example_messages: string[];
  display_order: number;
  appearance_id: string;
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
  model_provider: string;
  model: string;
  personality_id: string;
  personality_text: string;
  appearance_id: string;
  avatar_image_url: string;
  short_description: string;
  background_story: string;
  speaking_style: string;
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
  model_provider: string;
  model: string;
  personality_id?: string;
  personality_text?: string;
  short_description?: string;
  background_story?: string;
  speaking_style?: string;
  strategy_profile?: string;
  risk_tolerance?: number;
  bluffing_tendency?: number;
  trust_tendency?: number;
  leadership_tendency?: number;
  talkativeness?: number;
  example_messages?: string[];
  appearance_id?: string;
  avatar_asset_id?: string | null;
  avatar_image_url?: string;
  avatar_image_mime?: string;
  tags?: string[];
};

export const DEFAULT_PLAYER_PROFILE_DRAFT: PlayerProfileRequest = {
  display_name: "",
  model_provider: "",
  model: "",
  personality_id: "balanced",
  personality_text: "",
  short_description: "",
  background_story: "",
  speaking_style: "",
  strategy_profile: "balanced",
  risk_tolerance: 3,
  bluffing_tendency: 3,
  trust_tendency: 3,
  leadership_tendency: 3,
  talkativeness: 3,
  example_messages: [],
  appearance_id: "default",
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
  model_provider?: string | null;
  model?: string | null;
  personality_id?: string;
  personality?: string;
  appearance_id?: string;
  avatar_image_url?: string;
  avatar_asset_id?: string | null;
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
