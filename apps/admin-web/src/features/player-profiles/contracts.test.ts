import {
  createAdminPlayerProfile,
  getPlayerTtsSpeakerOptions,
  listAdminPlayerProfiles,
  previewAdminPlayerProfileVoice,
  transitionAdminPlayerProfile,
  updateAdminPlayerProfile,
} from "@/features/player-profiles/api";
import {
  parseAdminPlayerProfile,
  parseAdminPlayerProfileList,
  parseAdminPlayerVoicePreview,
  parsePlayerTtsSpeakerOptions,
} from "@/features/player-profiles/parsers";
import type {
  AdminPlayerProfile,
  CreatePlayerProfileRequest,
} from "@/features/player-profiles/types";

export const contractProfile: AdminPlayerProfile = {
  id: "profile-1",
  display_name: "暮鸦归票",
  model: "deepseek-v4-flash",
  personality_id: "analytical",
  personality_text: "重视票型。",
  appearance_id: "default",
  avatar_asset_id: null,
  avatar_image_url: "",
  avatar_image_mime: "",
  short_description: "逻辑控场",
  background_story: "长期复盘。",
  speaking_style: "先列证据。",
  gender: "female",
  catchphrases: ["我先盘票型"],
  strategy_profile: "logic_leader",
  risk_tolerance: 2,
  bluffing_tendency: 2,
  trust_tendency: 3,
  leadership_tendency: 5,
  talkativeness: 4,
  example_messages: ["先听后置位。"],
  display_order: 1,
  featured: false,
  tags: ["控场"],
  status: "draft",
  version: 2,
  created_at: "2026-07-01T08:00:00Z",
  updated_at: "2026-07-10T08:00:00Z",
  published_at: null,
  deleted_at: null,
  published_by: null,
  updated_by: "1",
};

const createRequest: CreatePlayerProfileRequest = {
  display_name: contractProfile.display_name,
  model: contractProfile.model,
  personality_id: contractProfile.personality_id,
  personality_text: contractProfile.personality_text,
  appearance_id: contractProfile.appearance_id,
  avatar_asset_id: contractProfile.avatar_asset_id,
  short_description: contractProfile.short_description,
  background_story: contractProfile.background_story,
  speaking_style: contractProfile.speaking_style,
  gender: contractProfile.gender,
  catchphrases: contractProfile.catchphrases,
  strategy_profile: contractProfile.strategy_profile,
  risk_tolerance: contractProfile.risk_tolerance,
  bluffing_tendency: contractProfile.bluffing_tendency,
  trust_tendency: contractProfile.trust_tendency,
  leadership_tendency: contractProfile.leadership_tendency,
  talkativeness: contractProfile.talkativeness,
  example_messages: contractProfile.example_messages,
  featured: false,
  tags: contractProfile.tags,
};

const voicePreviewResponse = {
  speaker: "zh_female_vv_uranus_bigtts",
  dialect: "sichuan" as const,
  effective_delivery: {
    schema_version: 1,
    mood: "tense",
    intensity: "medium",
    pace: "fast",
    instruction: "克制、清晰",
  },
  context_texts: ["安全 context"],
  delivery_mapping_version: "delivery-v1",
  audio_format: "mp3",
  mime_type: "audio/mpeg",
  sample_rate: 24_000,
  elapsed_ms: 18,
  audio_byte_length: 13,
  audio_base64: "cHJldmlldy1hdWRpbw==",
};

describe("admin player profile contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("strictly parses detail and paginated list DTOs", () => {
    const parsed = parseAdminPlayerProfile(contractProfile);
    expect(parsed).toEqual(contractProfile);
    expect("tts_speaker" in parsed).toBe(false);
    expect(
      parseAdminPlayerProfileList({
        items: [contractProfile],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toEqual({
      items: [contractProfile],
      pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
    });
  });

  it("parses optional voice configuration without changing legacy profiles", () => {
    const voiceProfile = {
      ...contractProfile,
      tts_speaker: "zh_female_vv_uranus_bigtts",
      tts_dialect: "sichuan" as const,
      base_delivery_mood: "restrained",
      base_delivery_intensity: "medium",
      base_delivery_pace: "natural",
      base_delivery_instruction: "克制、自然地表达，不使用播音腔。",
      voice_enabled: true,
      voice_config_version: 3,
    };

    expect(parseAdminPlayerProfile(voiceProfile)).toEqual(voiceProfile);
    expect(() =>
      parseAdminPlayerProfile({ ...voiceProfile, voice_enabled: "yes" }),
    ).toThrow(/voice_enabled/);
    expect(() =>
      parseAdminPlayerProfile({ ...voiceProfile, voice_config_version: 0 }),
    ).toThrow(/voice_config_version/);
  });

  it("strictly parses the bounded voice preview contract", () => {
    expect(parseAdminPlayerVoicePreview(voicePreviewResponse)).toEqual(
      voicePreviewResponse,
    );
    expect(() =>
      parseAdminPlayerVoicePreview({
        ...voicePreviewResponse,
        effective_delivery: {
          ...voicePreviewResponse.effective_delivery,
          mood: "invented",
        },
      }),
    ).toThrow(/mood/);
    expect(() =>
      parseAdminPlayerVoicePreview({
        ...voicePreviewResponse,
        audio_byte_length: 2 * 1024 * 1024 + 1,
      }),
    ).toThrow(/大小限制/);
  });

  it("parses and fetches the server-driven TTS speaker catalog", async () => {
    const response = {
      resource_id: "seed-tts-2.0",
      items: [
        {
          voice_type: "zh_female_vv_uranus_bigtts",
          name: "Vivi 2.0",
          gender: "female",
          dialects: [
            { id: "sichuan", label: "四川话" },
            { id: "shaanxi", label: "陕西话" },
            { id: "northeast", label: "东北话" },
          ],
        },
      ],
    };
    expect(parsePlayerTtsSpeakerOptions(response)).toEqual(response);
    expect(() =>
      parsePlayerTtsSpeakerOptions({ ...response, items: [{ name: "Vivi 2.0" }] }),
    ).toThrow(/字符串字段无效/);

    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(response));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getPlayerTtsSpeakerOptions()).resolves.toEqual(response);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/api/v1/admin/player-profile-tts-speakers",
    );
  });

  it("rejects legacy favorite and malformed lifecycle data", () => {
    expect(() =>
      parseAdminPlayerProfile({ ...contractProfile, favorite: true }),
    ).toThrow(/favorite/);
    expect(() =>
      parseAdminPlayerProfile({ ...contractProfile, status: "deleted" }),
    ).toThrow(/状态/);
    expect(() =>
      parseAdminPlayerProfile({ ...contractProfile, version: 0 }),
    ).toThrow(/version/);
  });

  it("serializes server pagination and signed sorting", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [contractProfile],
        pagination: { page: 2, page_size: 10, total: 11, pages: 2 },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listAdminPlayerProfiles({
      page: 2,
      page_size: 10,
      q: "暮鸦",
      status: "draft",
      model: "deepseek-v4-flash",
      personality_id: "analytical",
      sort: "updated_at",
      direction: "desc",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "https://admin.test");
    expect(parsed.pathname).toBe("/api/v1/admin/player-profiles");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      page: "2",
      page_size: "10",
      sort: "-updated_at",
      q: "暮鸦",
      status: "draft",
      model: "deepseek-v4-flash",
      personality_id: "analytical",
    });
    expect(options.credentials).toBe("include");
  });

  it("adds CSRF and expected_version to writes without legacy fields", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse(contractProfile)),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createAdminPlayerProfile(createRequest, "csrf-player");
    await updateAdminPlayerProfile(
      contractProfile.id,
      {
        expected_version: 2,
        display_name: "暮鸦归票二号",
        tts_speaker: null,
        base_delivery_mood: "restrained",
        base_delivery_intensity: "medium",
        base_delivery_pace: "natural",
        base_delivery_instruction: "克制表达",
        voice_enabled: true,
      },
      "csrf-player",
    );
    await transitionAdminPlayerProfile(
      contractProfile.id,
      "publish",
      { expected_version: 3, reason: "内容审核通过" },
      "csrf-player",
    );

    for (const [, options] of fetchMock.mock.calls as Array<
      [string, RequestInit]
    >) {
      expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(
        "csrf-player",
      );
      expect(options.credentials).toBe("include");
      expect(String(options.body)).not.toContain("favorite");
      expect(String(options.body)).not.toContain("avatar_image_url");
    }
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toMatchObject({
      expected_version: 2,
      tts_speaker: null,
      base_delivery_mood: "restrained",
      base_delivery_intensity: "medium",
      base_delivery_pace: "natural",
      base_delivery_instruction: "克制表达",
      voice_enabled: true,
    });
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({
      expected_version: 3,
      reason: "内容审核通过",
    });
  });

  it("posts an unsaved voice draft with CSRF and parses safe playback data", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(voicePreviewResponse));
    vi.stubGlobal("fetch", fetchMock);
    const request = {
      say: "我先听完这一轮。",
      speaker: null,
      dialect: null,
      base_delivery: {
        mood: "calm",
        intensity: "medium",
        pace: "natural",
        instruction: "克制、清晰",
      },
      turn_delivery: {
        mood: "tense",
        intensity: null,
        pace: "fast",
        instruction: null,
      },
    };

    await expect(
      previewAdminPlayerProfileVoice(request, "csrf-preview"),
    ).resolves.toEqual(voicePreviewResponse);

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/admin/player-profile-voice-previews");
    expect(options.method).toBe("POST");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(
      "csrf-preview",
    );
    expect(options.credentials).toBe("include");
    expect(JSON.parse(String(options.body))).toEqual(request);
  });
});

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status: 200,
  });
}
