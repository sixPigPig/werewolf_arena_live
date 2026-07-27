export type PlayerProfileStatus = "draft" | "published" | "archived";
export type PlayerGender = "female" | "male";
export type PlayerTtsDialect = "sichuan" | "shaanxi" | "northeast";

export type AdminPlayerProfile = {
  id: string;
  display_name: string;
  model_provider: string;
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
  gender: PlayerGender;
  catchphrases: string[];
  strategy_profile: string;
  risk_tolerance: number;
  bluffing_tendency: number;
  trust_tendency: number;
  leadership_tendency: number;
  talkativeness: number;
  example_messages: string[];
  tts_speaker?: string | null;
  tts_dialect?: PlayerTtsDialect | null;
  base_delivery_mood?: string | null;
  base_delivery_intensity?: string | null;
  base_delivery_pace?: string | null;
  base_delivery_instruction?: string | null;
  voice_enabled?: boolean;
  voice_config_version?: number;
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
  model_provider: string;
  model: string;
  personality_id: string;
  personality_text: string;
  appearance_id: string;
  avatar_asset_id: string | null;
  short_description: string;
  background_story: string;
  speaking_style: string;
  gender: PlayerGender;
  catchphrases: string[];
  strategy_profile: string;
  risk_tolerance: number;
  bluffing_tendency: number;
  trust_tendency: number;
  leadership_tendency: number;
  talkativeness: number;
  example_messages: string[];
  tts_speaker?: string | null;
  tts_dialect?: PlayerTtsDialect | null;
  base_delivery_mood?: string | null;
  base_delivery_intensity?: string | null;
  base_delivery_pace?: string | null;
  base_delivery_instruction?: string | null;
  voice_enabled?: boolean;
  featured: boolean;
  tags: string[];
};

export type AdminPlayerProfileAiDraft = Omit<
  PlayerProfileEditableFields,
  | "appearance_id"
  | "avatar_asset_id"
  | "featured"
  | "gender"
  | "model_provider"
  | "model"
>;

export type CreatePlayerProfileRequest = PlayerProfileEditableFields;

export type UpdatePlayerProfileRequest = Partial<PlayerProfileEditableFields> & {
  expected_version: number;
};

export type PlayerProfileTransitionRequest = {
  expected_version: number;
  reason: string;
};

export type PlayerVoicePreviewDeliveryInput = {
  mood?: string | null;
  intensity?: string | null;
  pace?: string | null;
  instruction?: string | null;
};

export type PlayerVoicePreviewRequest = {
  say: string;
  speaker: string | null;
  dialect: PlayerTtsDialect | null;
  base_delivery: PlayerVoicePreviewDeliveryInput;
  turn_delivery: PlayerVoicePreviewDeliveryInput;
};

export type AdminPlayerVoicePreview = {
  speaker: string;
  dialect: PlayerTtsDialect | null;
  effective_delivery: {
    schema_version: 1;
    mood: string;
    intensity: string;
    pace: string;
    instruction: string;
  };
  context_texts: string[];
  delivery_mapping_version: string;
  audio_format: string;
  mime_type: string;
  sample_rate: number;
  elapsed_ms: number;
  audio_byte_length: number;
  audio_base64: string;
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
  models: Array<{ provider: string; model_id: string; label: string }>;
  personalities: PlayerProfileOption[];
  appearances: PlayerProfileAppearanceOption[];
  strategies: PlayerProfileOption[];
  constraints: PlayerProfileConstraints;
};

export type PlayerTtsSpeakerOption = {
  voice_type: string;
  name: string;
  gender: PlayerGender;
  dialects: Array<{ id: PlayerTtsDialect; label: string }>;
};

export type PlayerTtsSpeakerOptions = {
  resource_id: string;
  items: PlayerTtsSpeakerOption[];
};

export const DEFAULT_PLAYER_PROFILE_INPUT: PlayerProfileEditableFields = {
  display_name: "",
  model_provider: "",
  model: "",
  personality_id: "balanced",
  personality_text: "",
  appearance_id: "default",
  avatar_asset_id: null,
  short_description: "",
  background_story: "",
  speaking_style: "",
  gender: "female",
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
