export type PlayerProfileStatus = "draft" | "published" | "archived";

export type AdminPlayerProfile = {
  id: string;
  display_name: string;
  model: string;
  personality_id: string;
  personality_text: string;
  appearance_id: string;
  avatar_asset_id: string | null;
  avatar_image_url: string;
  avatar_image_mime: string;
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
  status: PlayerProfileStatus;
  version: number;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  deleted_at: string | null;
  published_by: string | null;
  updated_by: string | null;
};

export type PlayerProfilesPagination = {
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

export type AdminPlayerProfileList = {
  items: AdminPlayerProfile[];
  pagination: PlayerProfilesPagination;
};

export type PlayerProfileSortField =
  | "created_at"
  | "display_name"
  | "display_order"
  | "updated_at";

export type PlayerProfileListParams = {
  page: number;
  page_size: number;
  q?: string;
  status?: PlayerProfileStatus;
  model?: string;
  personality_id?: string;
  sort: PlayerProfileSortField;
  direction: "asc" | "desc";
};

export type PlayerProfileEditableFields = {
  display_name: string;
  model: string;
  personality_id: string;
  personality_text: string;
  appearance_id: string;
  avatar_asset_id: string | null;
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
  featured: boolean;
  tags: string[];
};

export type CreatePlayerProfileRequest = PlayerProfileEditableFields;

export type UpdatePlayerProfileRequest = Partial<PlayerProfileEditableFields> & {
  expected_version: number;
};

export type PlayerProfileTransitionRequest = {
  expected_version: number;
  reason: string;
};

export type PlayerProfileOption = {
  id: string;
  label: string;
  description: string;
};

export type PlayerProfileAppearanceOption = PlayerProfileOption & {
  avatar_asset_id: string | null;
  avatar_image_url: string;
};

export type PlayerProfileConstraints = {
  tags_max_items: number;
  tag_max_length: number;
  catchphrases_max_items: number;
  catchphrase_max_length: number;
  example_messages_max_items: number;
  example_message_max_length: number;
};

export type PlayerProfileOptions = {
  models: Array<{ id: string; label: string }>;
  personalities: PlayerProfileOption[];
  appearances: PlayerProfileAppearanceOption[];
  strategies: PlayerProfileOption[];
  constraints: PlayerProfileConstraints;
};

export const DEFAULT_PLAYER_PROFILE_INPUT: PlayerProfileEditableFields = {
  display_name: "",
  model: "",
  personality_id: "balanced",
  personality_text: "",
  appearance_id: "default",
  avatar_asset_id: null,
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
  featured: false,
  tags: [],
};
