import { AdminApiError } from "@/api/problem-details";
import type {
  AdminPlayerProfile,
  AdminPlayerProfileAiDraft,
  AdminPlayerProfileList,
  CreatePlayerProfileRequest,
  PlayerProfileListParams,
  PlayerProfileOptions,
  PlayerTtsSpeakerOptions,
  PlayerProfileTransitionRequest,
  PlayerVoicePreviewRequest,
  UpdatePlayerProfileRequest,
} from "@/features/player-profiles/types";

const PREVIEW_AVATAR_DATA_URL =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 96'%3E%3Crect width='96' height='96' rx='20' fill='%23d1e9ff'/%3E%3Ccircle cx='48' cy='38' r='17' fill='%23175cd3'/%3E%3Cpath d='M18 88c3-19 15-29 30-29s27 10 30 29' fill='%231849a9'/%3E%3C/svg%3E";
const PREVIEW_PLAYER_SPEAKER = "zh_female_gaolengyujie_uranus_bigtts";
const PREVIEW_AUDIO_BASE64 = "cHJldmlldy1hdWRpbw==";
const PREVIEW_ALLOWED_DELIVERY_CUES = [
  "克制",
  "平静",
  "坚定",
  "自信",
  "质疑",
  "犹豫",
  "紧张",
  "激动",
  "悲伤",
  "低落",
  "轻松",
  "自然",
  "低沉",
  "果断",
  "不满",
  "急切",
  "急促",
  "停顿",
  "反问",
  "短句",
  "清晰",
] as const;

const PREVIEW_OPTIONS: PlayerProfileOptions = {
  models: [
    { id: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
    { id: "doubao-seed-1-8-251228", label: "Doubao Seed 1.8" },
  ],
  personalities: [
    { id: "balanced", label: "均衡", description: "稳健观察，按证据推进。" },
    { id: "analytical", label: "分析", description: "重视票型与行为一致性。" },
    { id: "aggressive", label: "进攻", description: "主动施压并推动投票。" },
  ],
  appearances: [
    {
      id: "default",
      label: "默认形象",
      description: "系统默认人物形象。",
      avatar_asset_id: null,
      avatar_image_url: "",
    },
    {
      id: "gothic-female-1",
      label: "霜银骑士",
      description: "内设不可变资产。",
      avatar_asset_id: "system-gothic-female-1",
      avatar_image_url: PREVIEW_AVATAR_DATA_URL,
    },
  ],
  strategies: [
    { id: "balanced", label: "均衡观察", description: "稳健观察，按证据推进。" },
    { id: "logic_leader", label: "逻辑带队", description: "主动整理票型和矛盾链。" },
    { id: "pressure_attacker", label: "强压进攻", description: "用快速提问制造信息。" },
  ],
  constraints: {
    tags_max_items: 8,
    tag_max_length: 20,
    catchphrases_max_items: 6,
    catchphrase_max_length: 40,
    example_messages_max_items: 5,
    example_message_max_length: 240,
  },
};

const PREVIEW_TTS_SPEAKERS: PlayerTtsSpeakerOptions = {
  resource_id: "seed-tts-2.0",
  items: [
    { voice_type: "zh_female_vv_uranus_bigtts", name: "Vivi 2.0" },
    {
      voice_type: "zh_female_gaolengyujie_uranus_bigtts",
      name: "高冷御姐 2.0",
    },
    { voice_type: "en_male_tim_uranus_bigtts", name: "Tim" },
  ],
};

const FIXTURE_PROFILES: AdminPlayerProfile[] = [
  fixtureProfile({
    id: "preview-published-1",
    display_name: "暮鸦归票",
    short_description: "沉稳控场，擅长整理票型。",
    status: "published",
    featured: true,
    version: 4,
    published_at: "2026-07-08T09:30:00Z",
    published_by: "1",
    updated_at: "2026-07-09T12:20:00Z",
    tags: ["控场", "复盘"],
  }),
  fixtureProfile({
    id: "preview-draft-1",
    display_name: "雾灯听风",
    model: "doubao-seed-1-8-251228",
    personality_id: "balanced",
    strategy_profile: "pressure_attacker",
    short_description: "正在打磨的高压问询型玩家。",
    tts_speaker: null,
    base_delivery_mood: "restrained",
    base_delivery_intensity: "medium",
    base_delivery_pace: "natural",
    base_delivery_instruction: "像桌边真人一样克制接话，不要播音腔。",
    voice_enabled: true,
    voice_config_version: 3,
    status: "draft",
    version: 2,
    published_at: null,
    published_by: null,
    updated_at: "2026-07-10T03:10:00Z",
    tags: ["草稿", "强压"],
  }),
  fixtureProfile({
    id: "preview-archived-1",
    display_name: "旧夜观星",
    short_description: "已从 C 端下线的历史玩家。",
    status: "archived",
    version: 7,
    published_at: "2026-06-18T08:00:00Z",
    deleted_at: "2026-07-01T08:00:00Z",
    published_by: "1",
    updated_at: "2026-07-01T08:00:00Z",
    tags: ["历史"],
  }),
];

let previewProfiles = FIXTURE_PROFILES.map(cloneProfile);
let previewSequence = 1;

export async function generatePreviewPlayerProfileAiDraft(): Promise<AdminPlayerProfileAiDraft> {
  return Promise.resolve({
    display_name: "月影听风",
    personality_id: "analytical",
    personality_text: "谨慎核对发言与票型，在关键轮次给出清晰结论。",
    short_description: "擅长从票型变化中寻找矛盾的复盘型玩家。",
    background_story: "长期记录圆桌对局，习惯用时间线还原每一次立场变化。",
    speaking_style: "先复述事实，再指出矛盾，最后明确给出归票建议。",
    catchphrases: ["先把时间线对齐", "这一票要解释"],
    strategy_profile: "logic_leader",
    risk_tolerance: 2,
    bluffing_tendency: 2,
    trust_tendency: 3,
    leadership_tendency: 4,
    talkativeness: 4,
    example_messages: ["我先按发言顺序复盘，再看这轮票型有没有冲突。"],
    tags: ["AI 草稿", "复盘"],
  });
}

export async function listPreviewPlayerProfiles(
  params: PlayerProfileListParams,
): Promise<AdminPlayerProfileList> {
  const query = params.q?.trim().toLocaleLowerCase("zh-Hans-CN") ?? "";
  const filtered = previewProfiles.filter((profile) => {
    const haystack = [
      profile.display_name,
      profile.short_description,
      profile.model,
      profile.personality_id,
      profile.strategy_profile,
      ...profile.tags,
    ]
      .join(" ")
      .toLocaleLowerCase("zh-Hans-CN");
    return (
      (!query || haystack.includes(query)) &&
      (!params.status || profile.status === params.status) &&
      (!params.model || profile.model === params.model) &&
      (!params.personality_id || profile.personality_id === params.personality_id)
    );
  });
  const sorted = filtered.toSorted((left, right) =>
    compareProfiles(left, right, params.sort, params.direction),
  );
  const start = (params.page - 1) * params.page_size;
  return Promise.resolve({
    items: sorted.slice(start, start + params.page_size).map(cloneProfile),
    pagination: {
      page: params.page,
      page_size: params.page_size,
      total: sorted.length,
      pages: sorted.length === 0 ? 0 : Math.ceil(sorted.length / params.page_size),
    },
  });
}

export async function getPreviewPlayerProfile(profileId: string) {
  const profile = findPreviewProfile(profileId);
  return Promise.resolve(cloneProfile(profile));
}

export async function getPreviewPlayerProfileOptions() {
  return Promise.resolve(structuredClone(PREVIEW_OPTIONS));
}

export async function getPreviewPlayerTtsSpeakerOptions() {
  return Promise.resolve(structuredClone(PREVIEW_TTS_SPEAKERS));
}

export async function previewPlayerProfileVoice(
  request: PlayerVoicePreviewRequest,
) {
  const say = request.say.trim();
  if (!say) {
    throw validationError("say", "请输入试听文本");
  }
  const speaker = request.speaker?.trim() || PREVIEW_PLAYER_SPEAKER;
  if (!/^[a-z0-9_]+_uranus_bigtts$/.test(speaker)) {
    throw new AdminApiError({
      problem: {
        type: "about:blank",
        title: "试听音色不支持",
        status: 422,
        detail: "当前仅支持 seed-tts-2.0 预置大模型音色的安全演绎试听。",
        code: "admin_player_voice_preview_context_unsupported",
        request_id: "preview-voice-unsupported",
      },
    });
  }
  const base = {
    mood: request.base_delivery.mood || "neutral",
    intensity: request.base_delivery.intensity || "medium",
    pace: request.base_delivery.pace || "natural",
    instruction: safePreviewInstruction(request.base_delivery.instruction),
  };
  const turnInstruction = safePreviewInstruction(
    request.turn_delivery.instruction,
  );
  const effectiveDelivery = {
    schema_version: 1 as const,
    mood: request.turn_delivery.mood || base.mood,
    intensity: request.turn_delivery.intensity || base.intensity,
    pace: request.turn_delivery.pace || base.pace,
    instruction: turnInstruction || base.instruction,
  };
  const extra = effectiveDelivery.instruction
    ? `；演绎提示为${effectiveDelivery.instruction}`
    : "";
  return Promise.resolve({
    speaker,
    effective_delivery: effectiveDelivery,
    context_texts: [
      `像真人在狼人杀现场自然接话，不要使用播音腔。情绪${effectiveDelivery.mood}；表达力度${effectiveDelivery.intensity}；语速${effectiveDelivery.pace}${extra}。`,
    ],
    delivery_mapping_version: "delivery-v1",
    audio_format: "mp3",
    mime_type: "audio/mpeg",
    sample_rate: 24_000,
    elapsed_ms: 12,
    audio_byte_length: 13,
    audio_base64: PREVIEW_AUDIO_BASE64,
  });
}

export async function createPreviewPlayerProfile(
  request: CreatePlayerProfileRequest,
) {
  if (request.featured) {
    throw validationError("featured", "草稿不能设为推荐");
  }
  const now = new Date().toISOString();
  const profile = fixtureProfile({
    ...request,
    id: `preview-created-${previewSequence++}`,
    display_order: previewProfiles.length + 1,
    status: "draft",
    version: 1,
    created_at: now,
    updated_at: now,
    published_at: null,
    deleted_at: null,
    published_by: null,
    updated_by: "preview-super-admin",
  });
  previewProfiles = [profile, ...previewProfiles];
  return cloneProfile(profile);
}

export async function updatePreviewPlayerProfile(
  profileId: string,
  request: UpdatePlayerProfileRequest,
) {
  const current = findPreviewProfile(profileId);
  assertVersion(current, request.expected_version);
  if (current.status === "archived") {
    throw invalidState("已归档玩家不能直接编辑，请先恢复发布。");
  }
  if (current.status === "draft" && request.featured) {
    throw validationError("featured", "草稿不能设为推荐");
  }
  const changes = Object.fromEntries(
    Object.entries(request).filter(([field]) => field !== "expected_version"),
  ) as Partial<AdminPlayerProfile>;
  const updated: AdminPlayerProfile = {
    ...current,
    ...changes,
    version: current.version + 1,
    updated_at: new Date().toISOString(),
    updated_by: "preview-super-admin",
  };
  replacePreviewProfile(updated);
  return cloneProfile(updated);
}

export async function transitionPreviewPlayerProfile(
  profileId: string,
  action: "archive" | "publish" | "restore",
  request: PlayerProfileTransitionRequest,
) {
  const current = findPreviewProfile(profileId);
  assertVersion(current, request.expected_version);
  const reason = request.reason.trim();
  if (reason.length < 3 || reason.length > 500) {
    throw validationError("reason", "操作原因需为 3 到 500 个字符");
  }
  const expectedStatus =
    action === "publish"
      ? "draft"
      : action === "archive"
        ? "published"
        : "archived";
  if (current.status !== expectedStatus) {
    throw invalidState("玩家当前状态不允许执行该操作。");
  }
  const now = new Date().toISOString();
  const updated: AdminPlayerProfile = {
    ...current,
    status:
      action === "archive"
        ? "archived"
        : "published",
    published_at: action === "archive" ? current.published_at : now,
    deleted_at: action === "archive" ? now : null,
    published_by:
      action === "archive" ? current.published_by : "preview-super-admin",
    featured: action === "archive" ? false : current.featured,
    updated_by: "preview-super-admin",
    updated_at: now,
    version: current.version + 1,
  };
  replacePreviewProfile(updated);
  return cloneProfile(updated);
}

export function resetPreviewPlayerProfiles() {
  previewProfiles = FIXTURE_PROFILES.map(cloneProfile);
  previewSequence = 1;
}

function fixtureProfile(
  overrides: Partial<AdminPlayerProfile>,
): AdminPlayerProfile {
  return {
    id: "preview-profile",
    display_name: "预览玩家",
    model: "deepseek-v4-flash",
    personality_id: "analytical",
    personality_text: "重视票型、发言顺序和行为一致性。",
    appearance_id: "gothic-female-1",
    avatar_asset_id: "system-gothic-female-1",
    avatar_image_url: PREVIEW_AVATAR_DATA_URL,
    avatar_image_mime: "image/png",
    short_description: "预览玩家简介",
    background_story: "长期观察圆桌局的复盘型玩家。",
    speaking_style: "先列证据，再给结论。",
    catchphrases: ["我先盘票型"],
    strategy_profile: "logic_leader",
    risk_tolerance: 2,
    bluffing_tendency: 2,
    trust_tendency: 3,
    leadership_tendency: 5,
    talkativeness: 4,
    example_messages: ["这一轮先听后置位补充。"],
    display_order: 1,
    featured: false,
    tags: ["预览"],
    status: "published",
    version: 1,
    created_at: "2026-06-01T08:00:00Z",
    updated_at: "2026-06-01T08:00:00Z",
    published_at: "2026-06-01T08:00:00Z",
    deleted_at: null,
    published_by: "1",
    updated_by: "1",
    ...overrides,
  };
}

function cloneProfile(profile: AdminPlayerProfile): AdminPlayerProfile {
  return {
    ...profile,
    catchphrases: [...profile.catchphrases],
    example_messages: [...profile.example_messages],
    tags: [...profile.tags],
  };
}

function findPreviewProfile(profileId: string) {
  const profile = previewProfiles.find((item) => item.id === profileId);
  if (!profile) {
    throw new AdminApiError({
      problem: {
        type: "about:blank",
        title: "玩家不存在",
        status: 404,
        detail: "没有找到该虚拟玩家。",
        code: "admin_player_profile_not_found",
        request_id: null,
      },
    });
  }
  return profile;
}

function replacePreviewProfile(profile: AdminPlayerProfile) {
  previewProfiles = previewProfiles.map((item) =>
    item.id === profile.id ? profile : item,
  );
}

function safePreviewInstruction(value: string | null | undefined) {
  const normalized = value?.trim() ?? "";
  if (
    /\d|号|玩家|狼人|身份|阵营|投票|出局|死亡|自爆|reasoning/i.test(
      normalized,
    )
  ) {
    return "";
  }
  return PREVIEW_ALLOWED_DELIVERY_CUES.filter((cue) =>
    normalized.includes(cue),
  ).join("、");
}

function assertVersion(profile: AdminPlayerProfile, expectedVersion: number) {
  if (profile.version === expectedVersion) {
    return;
  }
  throw new AdminApiError({
    problem: {
      type: "about:blank",
      title: "玩家资料已更新",
      status: 409,
      detail: "其他操作者已经更新该玩家，请重新加载后再提交。",
      code: "admin_player_profile_version_conflict",
      request_id: null,
      current_version: profile.version,
    },
  });
}

function validationError(field: string, message: string) {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "玩家资料校验失败",
      status: 422,
      detail: message,
      code: "admin_player_profile_validation_failed",
      request_id: null,
      errors: [{ field, message }],
    },
  });
}

function invalidState(message: string) {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "玩家状态已变化",
      status: 409,
      detail: message,
      code: "admin_player_profile_invalid_state",
      request_id: null,
    },
  });
}

function compareProfiles(
  left: AdminPlayerProfile,
  right: AdminPlayerProfile,
  field: PlayerProfileListParams["sort"],
  direction: PlayerProfileListParams["direction"],
) {
  const multiplier = direction === "asc" ? 1 : -1;
  const leftValue = left[field];
  const rightValue = right[field];
  if (typeof leftValue === "number" && typeof rightValue === "number") {
    return (leftValue - rightValue) * multiplier;
  }
  return String(leftValue).localeCompare(String(rightValue), "zh-Hans-CN") * multiplier;
}
