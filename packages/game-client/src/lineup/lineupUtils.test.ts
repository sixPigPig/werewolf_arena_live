import { describe, expect, it } from "vitest";

import type { PlayerConfig, VirtualPlayerProfile } from "../types";
import {
  applyProfileToSeat,
  clearAllSeats,
  clearSeat,
  findDuplicateProfileSelections,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
  resizeLineupForPlayerCount,
  summarizeLineup,
} from "./lineupUtils";

function profile(
  overrides: Partial<VirtualPlayerProfile>,
): VirtualPlayerProfile {
  return {
    id: "profile-1",
    owner_user_id: null,
    display_name: "冷静的阿夜",
    model: "DeepSeek",
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
    appearance_id: "moonlit",
    avatar_prompt: "",
    avatar_image_url: "",
    avatar_image_mime: "",
    tags: [],
    created_at: "2026-05-18T00:00:00Z",
    updated_at: "2026-05-18T00:00:00Z",
    ...overrides,
  };
}

describe("lineupUtils", () => {
  const profiles = [
    profile({
      id: "profile-1",
      display_name: "冷静的阿夜",
      model: "DeepSeek",
      personality_id: "cautious",
      favorite: true,
    }),
    profile({
      id: "profile-2",
      display_name: "影刃",
      model: "Qwen",
      personality_id: "aggressive",
    }),
    profile({
      id: "profile-3",
      display_name: "霜卫",
      model: "DeepSeek",
      personality_id: "balanced",
    }),
  ];

  it("applies a profile to a seat and keeps configs sorted", () => {
    const result = applyProfileToSeat(
      [{ seat: 3, profile_id: "profile-3" }],
      1,
      "profile-1",
    );

    expect(result).toEqual([
      { seat: 1, profile_id: "profile-1" },
      { seat: 3, profile_id: "profile-3" },
    ]);
  });

  it("does not apply a duplicate profile that is already assigned elsewhere", () => {
    const configs: PlayerConfig[] = [
      { seat: 1, profile_id: "profile-1" },
      { seat: 2, profile_id: "profile-2" },
    ];

    expect(applyProfileToSeat(configs, 2, "profile-1")).toEqual(configs);
  });

  it("clears one seat or all seats", () => {
    const configs: PlayerConfig[] = [
      { seat: 1, profile_id: "profile-1", model: "Qwen" },
      { seat: 2, profile_id: "profile-2" },
    ];

    expect(clearSeat(configs, 1)).toEqual([{ seat: 2, profile_id: "profile-2" }]);
    expect(clearAllSeats()).toEqual([]);
  });

  it("removes invalid profile references without discarding model-only overrides", () => {
    const configs: PlayerConfig[] = [
      { seat: 1, profile_id: "profile-1" },
      { seat: 2, profile_id: "missing-profile", model: "Qwen" },
      { seat: 3, profile_id: "missing-only" },
    ];

    expect(removeInvalidProfileRefs(configs, new Set(["profile-1"]))).toEqual([
      { seat: 1, profile_id: "profile-1" },
      { seat: 2, model: "Qwen" },
    ]);
  });

  it("removes configured seats outside a smaller player count", () => {
    const configs: PlayerConfig[] = [
      { seat: 12, appearance_id: "moonlit" },
      { seat: 8, model: "Kimi" },
      { seat: 10 },
      { seat: 9, profile_id: "profile-2" },
      { seat: 1, profile_id: "profile-1" },
    ];

    expect(resizeLineupForPlayerCount(configs, 8)).toEqual({
      configs: [
        { seat: 1, profile_id: "profile-1" },
        { seat: 8, model: "Kimi" },
      ],
      removedSeats: [9, 12],
    });
  });

  it("preserves configured seats when growing the player count", () => {
    const configs: PlayerConfig[] = [
      { seat: 6, model: "Kimi" },
      { seat: 1, profile_id: "profile-1" },
    ];

    expect(resizeLineupForPlayerCount(configs, 12)).toEqual({
      configs: [
        { seat: 1, profile_id: "profile-1" },
        { seat: 6, model: "Kimi" },
      ],
      removedSeats: [],
    });
  });

  it("finds duplicate profile selections", () => {
    expect(
      findDuplicateProfileSelections([
        { seat: 1, profile_id: "profile-1" },
        { seat: 2, profile_id: "profile-2" },
        { seat: 3, profile_id: "profile-1" },
      ]),
    ).toEqual([{ profileId: "profile-1", seats: [1, 3] }]);
  });

  it("randomly fills empty seats with unused profiles", () => {
    const result = randomFillEmptySeats(
      [{ seat: 2, profile_id: "profile-2" }],
      profiles,
      4,
      { random: () => 0 },
    );

    expect(result).toEqual([
      { seat: 1, profile_id: "profile-1" },
      { seat: 2, profile_id: "profile-2" },
      { seat: 3, profile_id: "profile-3" },
    ]);
  });

  it("fills seats that only have overrides with a virtual player", () => {
    const result = randomFillEmptySeats(
      [{ seat: 1, model: "Kimi" }],
      profiles,
      2,
      { random: () => 0 },
    );

    expect(result).toEqual([
      { seat: 1, model: "Kimi", profile_id: "profile-1" },
      { seat: 2, profile_id: "profile-2" },
    ]);
  });

  it("can fill empty seats with favorites only", () => {
    const result = randomFillEmptySeats([], profiles, 3, {
      favoritesOnly: true,
      random: () => 0,
    });

    expect(result).toEqual([{ seat: 1, profile_id: "profile-1" }]);
  });

  it("summarizes selected profiles, empty seats, favorites, models and personalities", () => {
    expect(
      summarizeLineup(
        [
          { seat: 1, profile_id: "profile-1" },
          { seat: 2, profile_id: "profile-2", model: "Kimi" },
        ],
        profiles,
        4,
      ),
    ).toEqual({
      assignedCount: 2,
      emptySeatCount: 2,
      favoriteCount: 1,
      invalidSeatCount: 0,
      modelCounts: [
        { label: "DeepSeek", count: 1 },
        { label: "Kimi", count: 1 },
      ],
      personalityCounts: [
        { label: "aggressive", count: 1 },
        { label: "cautious", count: 1 },
      ],
    });
  });
});
