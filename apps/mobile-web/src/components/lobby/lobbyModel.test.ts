import { describe, expect, it } from "vitest";

import type {
  PlayerConfig,
  PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";
import {
  buildLineupLaunchStatus,
  filterProfiles,
  findNextEmptySeat,
  normalizePlayerConfigs,
  upsertSeatProfile,
} from "./lobbyModel";

function buildProfile(
  id: string,
  overrides: Partial<PublicPlayerProfileWithFavorite> = {},
): PublicPlayerProfileWithFavorite {
  return {
    id,
    display_name: id,
    model_provider: "deepseek",
    model: "test-model",
    personality_id: "balanced",
    personality_text: "沉稳控场",
    appearance_id: "default",
    avatar_image_url: "",
    short_description: "先盘逻辑再站边",
    background_story: "",
    speaking_style: "",
    catchphrases: [],
    strategy_profile: "analysis",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    display_order: 1,
    featured: false,
    tags: ["逻辑"],
    is_favorite: false,
    ...overrides,
  };
}

describe("lobbyModel", () => {
  it("moves an already assigned profile to the requested seat", () => {
    const configs: PlayerConfig[] = [
      { seat: 1, profile_id: "profile-a" },
      { seat: 2, profile_id: "profile-b" },
    ];

    expect(upsertSeatProfile(configs, 2, "profile-a")).toEqual([
      { seat: 2, profile_id: "profile-a" },
    ]);
  });

  it("normalizes configured seats into sorted API payload entries", () => {
    expect(
      normalizePlayerConfigs(
        [
          { seat: 3, profile_id: "outside" },
          { seat: 2, model: "  model-b  " },
          { seat: 1, profile_id: "profile-a", name: "ignored" },
        ],
        2,
      ),
    ).toEqual([
      { seat: 1, profile_id: "profile-a" },
      { seat: 2, model: "model-b" },
    ]);
  });

  it("reports a disabled remaining-seat label until the lineup is full", () => {
    const profiles = [buildProfile("profile-a"), buildProfile("profile-b")];

    expect(buildLineupLaunchStatus([], profiles, 2)).toMatchObject({
      assignedCount: 0,
      emptySeatCount: 2,
      ctaLabel: "还差 2 位",
      canLaunch: false,
    });
    expect(
      buildLineupLaunchStatus(
        [
          { seat: 1, profile_id: "profile-a" },
          { seat: 2, profile_id: "profile-b" },
        ],
        profiles,
        2,
      ),
    ).toMatchObject({ ctaLabel: "开始对局", canLaunch: true });
  });

  it("wraps next-empty-seat search after the active seat", () => {
    expect(
      findNextEmptySeat(
        [
          { seat: 2, profile_id: "profile-b" },
          { seat: 3, profile_id: "profile-c" },
        ],
        3,
        2,
      ),
    ).toBe(1);
  });

  it("filters by search, favorite, and strategy together", () => {
    const profiles = [
      buildProfile("alpha", { is_favorite: true, strategy_profile: "analysis" }),
      buildProfile("beta", { strategy_profile: "aggressive" }),
    ];

    expect(
      filterProfiles(profiles, {
        favoriteFilter: "favorite",
        search: "逻辑",
        strategy: "analysis",
      }).map((profile) => profile.id),
    ).toEqual(["alpha"]);
  });
});
