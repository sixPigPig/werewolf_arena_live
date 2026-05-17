import {
  TENDENCY_LABELS,
  type TendencyField,
} from "./playerStrategyOptions";
import type { PlayerProfileRequest } from "./types";

export const PROFILE_PROMPT_SECTION_LABELS = {
  short_description: "角色简介",
  background_story: "背景设定",
  speaking_style: "发言风格",
  strategy_profile: "狼人杀策略",
  catchphrases: "常用表达",
  example_messages: "示例发言",
} as const;

const STRATEGY_PROMPT_TEXT: Record<string, string> = {
  balanced: "稳健观察，按证据推进，不轻易极端站边。",
  logic_leader: "偏逻辑带队，主动整理票型、发言顺序和矛盾链。",
  shadow_wolf: "擅长隐藏动机，低调拆票，避免过早成为焦点。",
  social_reader: "偏社交阅读，重视情绪变化、关系线和发言姿态。",
  pressure_attacker: "喜欢强压和快速验人式提问，用压力制造信息。",
  cautious_observer: "谨慎慢热，先收集信息，再给出明确判断。",
};

export function composeProfilePromptPreview(
  profile: Partial<PlayerProfileRequest>,
  basePersonality = profile.personality_text ?? "",
) {
  const sections: string[] = [];
  const baseText = normalizeText(basePersonality);

  if (baseText) {
    sections.push(baseText);
  }

  appendTextSection(
    sections,
    PROFILE_PROMPT_SECTION_LABELS.short_description,
    profile.short_description,
  );
  appendTextSection(
    sections,
    PROFILE_PROMPT_SECTION_LABELS.background_story,
    profile.background_story,
  );
  appendTextSection(
    sections,
    PROFILE_PROMPT_SECTION_LABELS.speaking_style,
    profile.speaking_style,
  );

  sections.push(
    `${PROFILE_PROMPT_SECTION_LABELS.strategy_profile}: ${strategyPromptText(
      profile.strategy_profile,
    )}`,
  );

  (
    Object.entries(TENDENCY_LABELS) as Array<[TendencyField, string]>
  ).forEach(([fieldName, label]) => {
    sections.push(`${label}: ${normalizeTendency(profile[fieldName])}/5`);
  });

  appendListSection(
    sections,
    PROFILE_PROMPT_SECTION_LABELS.catchphrases,
    profile.catchphrases,
  );
  appendListSection(
    sections,
    PROFILE_PROMPT_SECTION_LABELS.example_messages,
    profile.example_messages,
  );

  return sections.join("\n");
}

export function normalizeTendency(value: unknown) {
  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return 3;
  }

  return Math.min(5, Math.max(1, Math.round(parsed)));
}

function strategyPromptText(strategyProfile = "balanced") {
  return STRATEGY_PROMPT_TEXT[strategyProfile] ?? STRATEGY_PROMPT_TEXT.balanced;
}

function appendTextSection(
  sections: string[],
  label: string,
  value: unknown,
) {
  const text = normalizeText(value);

  if (text) {
    sections.push(`${label}: ${text}`);
  }
}

function appendListSection(
  sections: string[],
  label: string,
  value: string[] | undefined,
) {
  const items = (Array.isArray(value) ? value : [])
    .map((item) => normalizeText(item))
    .filter(Boolean);

  if (items.length > 0) {
    sections.push(`${label}: ${items.join("；")}`);
  }
}

function normalizeText(value: unknown) {
  return value == null ? "" : String(value).trim();
}
