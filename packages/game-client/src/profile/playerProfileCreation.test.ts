import { describe, expect, it } from "vitest";

import {
  applyPlayerCreationPreset,
  DEFAULT_PLAYER_CREATION_PRESET_ID,
  getPlayerProfileCreationReadiness,
  nextAvailableProfileName,
  PLAYER_CREATION_PRESETS,
} from "./playerProfileCreation";
import {
  DEFAULT_PLAYER_PROFILE_DRAFT,
  type VirtualPlayerProfile,
} from "../types";

function profile(
  overrides: Pick<VirtualPlayerProfile, "id" | "display_name"> &
    Partial<VirtualPlayerProfile>,
): VirtualPlayerProfile {
  const { id, display_name, ...rest } = overrides;

  return {
    id,
    owner_user_id: null,
    display_name,
    model: "deepseek-chat",
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
    display_order: 1,
    favorite: false,
    appearance_id: "default",
    avatar_prompt: "",
    avatar_asset_id: null,
    avatar_image_url: "",
    avatar_image_mime: "",
    tags: [],
    created_at: "2026-05-18T00:00:00Z",
    updated_at: "2026-05-18T00:00:00Z",
    ...rest,
  };
}

describe("player profile creation helpers", () => {
  it("applies creation presets without replacing identity, model or portrait", () => {
    const baseDraft = {
      ...DEFAULT_PLAYER_PROFILE_DRAFT,
      display_name: "新玩家",
      model: "deepseek-chat",
      appearance_id: "gothic-male-1",
      avatar_asset_id: "system-gothic-male-1",
      avatar_image_url: "/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
      avatar_image_mime: "image/png",
    };

    const draft = applyPlayerCreationPreset(baseDraft, "pressure-attacker");

    expect(draft).toMatchObject({
      display_name: "新玩家",
      model: "deepseek-chat",
      appearance_id: "gothic-male-1",
      avatar_asset_id: "system-gothic-male-1",
      avatar_image_url: "/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
      avatar_image_mime: "image/png",
      personality_id: "aggressive",
      strategy_profile: "pressure_attacker",
      short_description: "用连续提问制造压力，快速逼出视角漏洞。",
      risk_tolerance: 4,
      leadership_tendency: 4,
      talkativeness: 5,
      tags: ["强压", "提问"],
    });

    draft.tags?.push("污染");
    const cleanDraft = applyPlayerCreationPreset(baseDraft, "pressure-attacker");

    expect(cleanDraft.tags).toEqual(["强压", "提问"]);
  });

  it("falls back to the default preset when an unknown preset id is requested", () => {
    const draft = applyPlayerCreationPreset(
      {
        ...DEFAULT_PLAYER_PROFILE_DRAFT,
        display_name: "默认玩家",
        model: "deepseek-chat",
      },
      "unknown-preset",
    );
    const defaultPreset = PLAYER_CREATION_PRESETS.find(
      (preset) => preset.id === DEFAULT_PLAYER_CREATION_PRESET_ID,
    );

    expect(defaultPreset).toBeDefined();
    expect(draft.strategy_profile).toBe(defaultPreset?.draft.strategy_profile);
    expect(draft.personality_id).toBe(defaultPreset?.draft.personality_id);
  });

  it("generates the next available name while respecting edit exclusions", () => {
    const profiles = [
      profile({ id: "profile-1", display_name: "冷静的阿夜" }),
      profile({ id: "profile-2", display_name: "冷静的阿夜 2" }),
      profile({ id: "profile-3", display_name: "Alpha Scout" }),
    ];

    expect(nextAvailableProfileName("冷静的阿夜", profiles)).toBe("冷静的阿夜 3");
    expect(nextAvailableProfileName(" alpha scout ", profiles)).toBe(
      "alpha scout 2",
    );
    expect(nextAvailableProfileName("Alpha Scout", profiles, "profile-3")).toBe(
      "Alpha Scout",
    );
  });

  it("reports readiness for missing and duplicate profile names", () => {
    const profiles = [
      profile({ id: "profile-alpha", display_name: "Alpha 阿夜" }),
    ];
    const duplicateDraft = {
      ...DEFAULT_PLAYER_PROFILE_DRAFT,
      display_name: " alpha 阿夜 ",
      model: "deepseek-chat",
      strategy_profile: "logic_leader",
      avatar_asset_id: "system-gothic-male-1",
      avatar_image_url: "",
    };

    expect(
      getPlayerProfileCreationReadiness(duplicateDraft, profiles),
    ).toMatchObject({
      canSave: false,
      issueText: "已有同名虚拟玩家",
    });
    expect(
      getPlayerProfileCreationReadiness(
        duplicateDraft,
        profiles,
        "profile-alpha",
      ).canSave,
    ).toBe(true);

    expect(
      getPlayerProfileCreationReadiness(
        { ...duplicateDraft, display_name: "新玩家", model: "" },
        profiles,
      ),
    ).toMatchObject({
      canSave: false,
      issueText: "需要默认模型",
    });
  });
});
