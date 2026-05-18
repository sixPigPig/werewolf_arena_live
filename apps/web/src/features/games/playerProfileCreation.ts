import type { PlayerProfileRequest, VirtualPlayerProfile } from "./types";

export type PlayerCreationPresetId = string;

type ProfileNameCandidate = Pick<VirtualPlayerProfile, "id" | "display_name">;

export type PlayerCreationPresetDraft = Required<
  Pick<
    PlayerProfileRequest,
    | "personality_id"
    | "personality_text"
    | "short_description"
    | "background_story"
    | "speaking_style"
    | "catchphrases"
    | "strategy_profile"
    | "risk_tolerance"
    | "bluffing_tendency"
    | "trust_tendency"
    | "leadership_tendency"
    | "talkativeness"
    | "example_messages"
    | "tags"
  >
>;

export type PlayerCreationPreset = {
  id: PlayerCreationPresetId;
  label: string;
  description: string;
  draft: PlayerCreationPresetDraft;
  isAiGenerated?: boolean;
  isCustom?: boolean;
};

export type PlayerProfileCreationChecklistItem = {
  id: "name" | "model" | "persona" | "appearance";
  label: string;
  isComplete: boolean;
};

export type PlayerProfileCreationReadiness = {
  canSave: boolean;
  issueText: string | null;
  items: PlayerProfileCreationChecklistItem[];
};

export const DEFAULT_PLAYER_CREATION_PRESET_ID: PlayerCreationPresetId =
  "logic-leader";
export const AI_PLAYER_CREATION_PRESET_ID: PlayerCreationPresetId =
  "ai-generated";

export const PLAYER_CREATION_PRESETS: PlayerCreationPreset[] = [
  {
    id: "logic-leader",
    label: "逻辑控场",
    description: "整理票型，稳住节奏。",
    draft: {
      personality_id: "analytical",
      personality_text:
        "重视票型、发言顺序和行为一致性，会先归纳证据，再推动全场形成可验证的判断。",
      short_description: "沉稳控场，喜欢先盘逻辑再给站边。",
      background_story: "长期观察圆桌局的复盘型玩家，习惯从细节里找出阵营压力点。",
      speaking_style: "短句推进，先列证据，再给结论。",
      catchphrases: ["我先盘票型", "这里不急着站死"],
      strategy_profile: "logic_leader",
      risk_tolerance: 2,
      bluffing_tendency: 2,
      trust_tendency: 3,
      leadership_tendency: 5,
      talkativeness: 4,
      example_messages: [
        "我认为 3 号这一轮的视角不完整，先听后置位补充。",
      ],
      tags: ["控场", "复盘"],
    },
  },
  {
    id: "pressure-attacker",
    label: "高压进攻",
    description: "连续追问，快速施压。",
    draft: {
      personality_id: "aggressive",
      personality_text:
        "进攻性强，会主动施压、抓矛盾、要求玩家解释发言动机，并推动尽快形成投票方向。",
      short_description: "用连续提问制造压力，快速逼出视角漏洞。",
      background_story: "擅长在混乱发言中抓住迟疑和改口，是局内最先点燃冲突的人。",
      speaking_style: "语速快，问题密集，喜欢直接要求对方给出明确站边。",
      catchphrases: ["这个回答太慢了", "别绕，给结论"],
      strategy_profile: "pressure_attacker",
      risk_tolerance: 4,
      bluffing_tendency: 3,
      trust_tendency: 2,
      leadership_tendency: 4,
      talkativeness: 5,
      example_messages: [
        "你刚才说不站边，现在又要保 5 号，这个逻辑我过不去。",
      ],
      tags: ["强压", "提问"],
    },
  },
  {
    id: "shadow-wolf",
    label: "阴影潜伏",
    description: "低调藏身，暗中改票。",
    draft: {
      personality_id: "deceptive",
      personality_text:
        "善于混淆视听，会隐藏真实动机，用温和语气引导别人替自己提出攻击点。",
      short_description: "低调观察局势，擅长在关键轮次暗中改变方向。",
      background_story: "习惯坐在话题边缘，等多数观点成形后再悄悄补上一刀。",
      speaking_style: "语气克制，不急着带队，常用疑问句制造弹性空间。",
      catchphrases: ["我先不打死", "这个视角可以再放一轮"],
      strategy_profile: "shadow_wolf",
      risk_tolerance: 3,
      bluffing_tendency: 5,
      trust_tendency: 2,
      leadership_tendency: 2,
      talkativeness: 2,
      example_messages: [
        "我不是要直接出他，但他这一轮的补充确实有点像补视角。",
      ],
      tags: ["潜伏", "伪装"],
    },
  },
  {
    id: "social-reader",
    label: "社交读心",
    description: "看姿态，读关系线。",
    draft: {
      personality_id: "balanced",
      personality_text:
        "重视玩家情绪、互动关系和发言姿态，会把逻辑线和社交线一起纳入判断。",
      short_description: "擅长从情绪变化和互保关系里找阵营线索。",
      background_story: "对发言气质很敏锐，常从谁在回避谁、谁在替谁补话里推断阵营。",
      speaking_style: "自然、有互动感，会把玩家之间的关系线说清楚。",
      catchphrases: ["这两个人不像同边", "我更看这个姿态"],
      strategy_profile: "social_reader",
      risk_tolerance: 3,
      bluffing_tendency: 3,
      trust_tendency: 4,
      leadership_tendency: 3,
      talkativeness: 4,
      example_messages: [
        "2 号刚才不是在保 6 号，而是在给自己留退路，这个姿态我会记一下。",
      ],
      tags: ["社交", "关系线"],
    },
  },
];

export const AI_PLAYER_CREATION_PRESET: PlayerCreationPreset = {
  id: AI_PLAYER_CREATION_PRESET_ID,
  label: "AI 生成",
  description: "请求 deepseek-v4-flash 即兴生成。",
  isAiGenerated: true,
  draft: {
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
    tags: [],
  },
};

export function applyPlayerCreationPreset(
  draft: PlayerProfileRequest,
  presetId: string | undefined,
  presets: PlayerCreationPreset[] = PLAYER_CREATION_PRESETS,
): PlayerProfileRequest {
  const preset = creationPresetById(presetId, presets);

  return {
    ...draft,
    personality_id: preset.draft.personality_id,
    personality_text: preset.draft.personality_text,
    short_description: preset.draft.short_description,
    background_story: preset.draft.background_story,
    speaking_style: preset.draft.speaking_style,
    catchphrases: [...preset.draft.catchphrases],
    strategy_profile: preset.draft.strategy_profile,
    risk_tolerance: preset.draft.risk_tolerance,
    bluffing_tendency: preset.draft.bluffing_tendency,
    trust_tendency: preset.draft.trust_tendency,
    leadership_tendency: preset.draft.leadership_tendency,
    talkativeness: preset.draft.talkativeness,
    example_messages: [...preset.draft.example_messages],
    tags: [...preset.draft.tags],
  };
}

export function createPlayerCreationPresetFromDraft(
  id: string,
  label: string,
  draft: PlayerProfileRequest,
): PlayerCreationPreset {
  return {
    id,
    label: label.trim(),
    description: draft.short_description?.trim() || "自定义玩家模板",
    isCustom: true,
    draft: playerCreationPresetDraftFromDraft(draft),
  };
}

export function playerCreationPresetDraftFromDraft(
  draft: PlayerProfileRequest,
): PlayerCreationPresetDraft {
  return {
    personality_id: draft.personality_id || "balanced",
    personality_text: draft.personality_text?.trim() ?? "",
    short_description: draft.short_description?.trim() ?? "",
    background_story: draft.background_story?.trim() ?? "",
    speaking_style: draft.speaking_style?.trim() ?? "",
    catchphrases: [...(draft.catchphrases ?? [])],
    strategy_profile: draft.strategy_profile || "balanced",
    risk_tolerance: normalizeTendency(draft.risk_tolerance),
    bluffing_tendency: normalizeTendency(draft.bluffing_tendency),
    trust_tendency: normalizeTendency(draft.trust_tendency),
    leadership_tendency: normalizeTendency(draft.leadership_tendency),
    talkativeness: normalizeTendency(draft.talkativeness),
    example_messages: [...(draft.example_messages ?? [])],
    tags: [...(draft.tags ?? [])],
  };
}

export function getPlayerProfileCreationReadiness(
  draft: PlayerProfileRequest,
  profiles: ProfileNameCandidate[],
  editingProfileId?: string | null,
): PlayerProfileCreationReadiness {
  const hasName = draft.display_name.trim().length > 0;
  const hasModel = draft.model.trim().length > 0;
  const hasDuplicateName =
    hasName &&
    hasDuplicateProfileName(profiles, draft.display_name, editingProfileId);
  const hasPersona = Boolean(draft.personality_id && draft.strategy_profile);
  const hasAppearance = Boolean(
    draft.avatar_image_url?.trim() || draft.appearance_id?.trim(),
  );
  const items: PlayerProfileCreationChecklistItem[] = [
    { id: "name", label: "昵称", isComplete: hasName && !hasDuplicateName },
    { id: "model", label: "模型", isComplete: hasModel },
    { id: "persona", label: "人设", isComplete: hasPersona },
    { id: "appearance", label: "形象", isComplete: hasAppearance },
  ];

  return {
    canSave: hasName && hasModel && !hasDuplicateName,
    issueText: creationIssueText({ hasName, hasModel, hasDuplicateName }),
    items,
  };
}

export function hasDuplicateProfileName(
  profiles: ProfileNameCandidate[],
  displayName: string,
  editingProfileId?: string | null,
) {
  const normalizedName = normalizeProfileName(displayName);
  if (!normalizedName) {
    return false;
  }

  return profiles.some(
    (profile) =>
      profile.id !== editingProfileId &&
      normalizeProfileName(profile.display_name) === normalizedName,
  );
}

export function nextAvailableProfileName(
  baseName: string,
  profiles: ProfileNameCandidate[],
  editingProfileId?: string | null,
) {
  const trimmedBaseName = baseName.trim() || "新玩家";
  const usedNames = new Set(
    profiles
      .filter((profile) => profile.id !== editingProfileId)
      .map((profile) => normalizeProfileName(profile.display_name))
      .filter(Boolean),
  );

  if (!usedNames.has(normalizeProfileName(trimmedBaseName))) {
    return trimmedBaseName;
  }

  let suffix = 2;
  while (usedNames.has(normalizeProfileName(`${trimmedBaseName} ${suffix}`))) {
    suffix += 1;
  }

  return `${trimmedBaseName} ${suffix}`;
}

function creationPresetById(
  presetId: string | undefined,
  presets: PlayerCreationPreset[],
) {
  return (
    presets.find((preset) => preset.id === presetId && !preset.isAiGenerated) ??
    presets.find(
      (preset) => preset.id === DEFAULT_PLAYER_CREATION_PRESET_ID,
    ) ??
    PLAYER_CREATION_PRESETS[0]
  );
}

function normalizeProfileName(value: string) {
  return value.trim().replace(/\s+/g, " ").toLocaleLowerCase("zh-Hans-CN");
}

function normalizeTendency(value: number | undefined) {
  if (!Number.isFinite(value)) {
    return 3;
  }
  return Math.min(5, Math.max(1, Math.round(Number(value))));
}

function creationIssueText({
  hasName,
  hasModel,
  hasDuplicateName,
}: {
  hasName: boolean;
  hasModel: boolean;
  hasDuplicateName: boolean;
}) {
  if (!hasName) {
    return "需要虚拟玩家昵称";
  }
  if (hasDuplicateName) {
    return "已有同名虚拟玩家";
  }
  if (!hasModel) {
    return "需要默认模型";
  }

  return null;
}
