import type {
  AdminPlayerProfile,
  PlayerProfileConstraints,
  PlayerProfileEditableFields,
} from "@/features/player-profiles/types";
import { DEFAULT_PLAYER_PROFILE_INPUT } from "@/features/player-profiles/types";

export type PlayerProfileFormErrors = Partial<
  Record<keyof PlayerProfileEditableFields | "form", string>
>;

export function inputFromProfile(
  profile: AdminPlayerProfile | null,
  defaults: Partial<PlayerProfileEditableFields> = {},
): PlayerProfileEditableFields {
  if (!profile) {
    return cloneInput({ ...DEFAULT_PLAYER_PROFILE_INPUT, ...defaults });
  }
  return cloneInput({
    display_name: profile.display_name,
    model: profile.model,
    personality_id: profile.personality_id,
    personality_text: profile.personality_text,
    appearance_id: profile.appearance_id,
    avatar_asset_id: profile.avatar_asset_id,
    short_description: profile.short_description,
    background_story: profile.background_story,
    speaking_style: profile.speaking_style,
    gender: profile.gender,
    catchphrases: profile.catchphrases,
    strategy_profile: profile.strategy_profile,
    risk_tolerance: profile.risk_tolerance,
    bluffing_tendency: profile.bluffing_tendency,
    trust_tendency: profile.trust_tendency,
    leadership_tendency: profile.leadership_tendency,
    talkativeness: profile.talkativeness,
    example_messages: profile.example_messages,
    ...voiceInputFromProfile(profile),
    featured: profile.featured,
    tags: profile.tags,
  });
}

export function cleanPlayerProfileInput(
  value: PlayerProfileEditableFields,
): PlayerProfileEditableFields {
  return {
    ...value,
    display_name: value.display_name.trim(),
    model: value.model.trim(),
    personality_id: value.personality_id.trim(),
    personality_text: value.personality_text.trim(),
    appearance_id: value.appearance_id.trim(),
    avatar_asset_id: value.avatar_asset_id?.trim() || null,
    short_description: value.short_description.trim(),
    background_story: value.background_story.trim(),
    speaking_style: value.speaking_style.trim(),
    catchphrases: cleanList(value.catchphrases),
    strategy_profile: value.strategy_profile.trim(),
    risk_tolerance: normalizeNumber(value.risk_tolerance),
    bluffing_tendency: normalizeNumber(value.bluffing_tendency),
    trust_tendency: normalizeNumber(value.trust_tendency),
    leadership_tendency: normalizeNumber(value.leadership_tendency),
    talkativeness: normalizeNumber(value.talkativeness),
    example_messages: cleanList(value.example_messages),
    ...cleanOptionalVoiceInput(value),
    tags: cleanList(value.tags),
  };
}

export function validatePlayerProfileInput(
  value: PlayerProfileEditableFields,
  constraints: PlayerProfileConstraints,
  status: "draft" | "published" | "archived" | "new",
) {
  const errors: PlayerProfileFormErrors = {};
  if (!value.display_name.trim()) {
    errors.display_name = "请输入玩家名称";
  } else if (value.display_name.trim().length > 80) {
    errors.display_name = "玩家名称不能超过 80 个字符";
  }
  if (!value.model.trim()) {
    errors.model = "请选择默认模型";
  } else if (value.model.trim().length > 120) {
    errors.model = "模型标识不能超过 120 个字符";
  }
  checkLength(errors, "short_description", value.short_description, 160);
  checkLength(errors, "background_story", value.background_story, 1200);
  checkLength(errors, "speaking_style", value.speaking_style, 800);
  checkList(
    errors,
    "tags",
    value.tags,
    constraints.tags_max_items,
    constraints.tag_max_length,
  );
  checkList(
    errors,
    "catchphrases",
    value.catchphrases,
    constraints.catchphrases_max_items,
    constraints.catchphrase_max_length,
  );
  checkList(
    errors,
    "example_messages",
    value.example_messages,
    constraints.example_messages_max_items,
    constraints.example_message_max_length,
  );
  (
    [
      "risk_tolerance",
      "bluffing_tendency",
      "trust_tendency",
      "leadership_tendency",
      "talkativeness",
    ] as const
  ).forEach((field) => {
    const tendency = value[field];
    if (!Number.isInteger(tendency) || tendency < 1 || tendency > 5) {
      errors[field] = "请输入 1 到 5 的整数";
    }
  });
  if (status !== "published" && value.featured) {
    errors.featured = "只有已发布玩家可以设为推荐";
  }
  return errors;
}

export function formErrorsFromApi(
  errors: Array<{ field: string; message: string }>,
) {
  const result: PlayerProfileFormErrors = {};
  errors.forEach(({ field, message }) => {
    const normalized = field.split(".").at(-1) as keyof PlayerProfileEditableFields;
    if (PLAYER_PROFILE_FORM_FIELDS.has(normalized)) {
      result[normalized] = message;
    } else {
      result.form = message;
    }
  });
  return result;
}

const PLAYER_PROFILE_FORM_FIELDS = new Set<keyof PlayerProfileEditableFields>([
  ...Object.keys(DEFAULT_PLAYER_PROFILE_INPUT) as Array<
    keyof PlayerProfileEditableFields
  >,
  "tts_speaker",
  "tts_dialect",
  "base_delivery_mood",
  "base_delivery_intensity",
  "base_delivery_pace",
  "base_delivery_instruction",
  "voice_enabled",
]);

export function parseCommaList(value: string) {
  return value
    .split(/[,，;；\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function formatCommaList(value: string[]) {
  return value.join("，");
}

export function parseMultilineList(value: string) {
  return value
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function formatMultilineList(value: string[]) {
  return value.join("\n");
}

function cloneInput(value: PlayerProfileEditableFields) {
  return {
    ...value,
    catchphrases: [...value.catchphrases],
    example_messages: [...value.example_messages],
    tags: [...value.tags],
  };
}

function cleanList(value: string[]) {
  return [...new Set(value.map((item) => item.trim()).filter(Boolean))];
}

function normalizeNumber(value: number) {
  return Number.isFinite(value) ? Math.round(value) : value;
}

function voiceInputFromProfile(
  profile: AdminPlayerProfile,
): Partial<PlayerProfileEditableFields> {
  const value: Partial<PlayerProfileEditableFields> = {};
  (
    [
      "tts_speaker",
      "tts_dialect",
      "base_delivery_mood",
      "base_delivery_intensity",
      "base_delivery_pace",
      "base_delivery_instruction",
      "voice_enabled",
    ] as const
  ).forEach((field) => {
    if (profile[field] !== undefined) {
      Object.assign(value, { [field]: profile[field] });
    }
  });
  return value;
}

function cleanOptionalVoiceInput(
  value: PlayerProfileEditableFields,
): Partial<PlayerProfileEditableFields> {
  const cleaned: Partial<PlayerProfileEditableFields> = {};
  (
    [
      "tts_speaker",
      "tts_dialect",
      "base_delivery_mood",
      "base_delivery_intensity",
      "base_delivery_pace",
      "base_delivery_instruction",
    ] as const
  ).forEach((field) => {
    const raw = value[field];
    if (raw !== undefined) {
      Object.assign(cleaned, { [field]: raw?.trim() || null });
    }
  });
  if (value.voice_enabled !== undefined) {
    cleaned.voice_enabled = value.voice_enabled;
  }
  return cleaned;
}

function checkLength(
  errors: PlayerProfileFormErrors,
  field: "background_story" | "short_description" | "speaking_style",
  value: string,
  maximum: number,
) {
  if (value.trim().length > maximum) {
    errors[field] = `不能超过 ${maximum} 个字符`;
  }
}

function checkList(
  errors: PlayerProfileFormErrors,
  field: "catchphrases" | "example_messages" | "tags",
  value: string[],
  maximumItems: number,
  maximumLength: number,
) {
  const items = value.map((item) => item.trim()).filter(Boolean);
  if (items.length > maximumItems) {
    errors[field] = `最多填写 ${maximumItems} 项`;
  } else if (items.some((item) => item.length > maximumLength)) {
    errors[field] = `每项不能超过 ${maximumLength} 个字符`;
  }
}
