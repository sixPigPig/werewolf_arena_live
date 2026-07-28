import { afterEach, describe, expect, it, vi } from "vitest";

import type { PublicPlayerProfile } from "../types";
import {
  getPublicPlayerProfile,
  listPublicPlayerProfiles,
  mergePlayerProfileFavorites,
} from "./publicPlayerProfiles";

function profile(id: string): PublicPlayerProfile {
  return {
    id,
    display_name: id,
    model_provider: "deepseek",
    model: "test-model",
    personality_id: "balanced",
    personality_text: "",
    appearance_id: "default",
    avatar_image_url: "",
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
    featured: false,
    tags: [],
  };
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

describe("public player profile endpoints", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("aggregates every public profile page in server order", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const page = Number(new URL(url, "https://local.test").searchParams.get("page"));
      return jsonResponse({
        items: [profile(`profile-${page}`)],
        pagination: { page, page_size: 100, total: 3, pages: 3 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPublicPlayerProfiles()).resolves.toEqual([
      profile("profile-1"),
      profile("profile-2"),
      profile("profile-3"),
    ]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/public/player-profiles?page=1&page_size=100",
      "/api/v1/public/player-profiles?page=2&page_size=100",
      "/api/v1/public/player-profiles?page=3&page_size=100",
    ]);
  });

  it("loads one public profile by its encoded id", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(profile("profile one")));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getPublicPlayerProfile("profile one")).resolves.toEqual(
      profile("profile one"),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/public/player-profiles/profile%20one",
      undefined,
    );
  });

  it("puts viewer favorites first without confusing them with editorial featured state", () => {
    const featured = { ...profile("featured"), featured: true };
    const favorite = profile("favorite");

    expect(
      mergePlayerProfileFavorites([featured, favorite], ["favorite"]),
    ).toEqual([
      { ...favorite, is_favorite: true },
      { ...featured, is_favorite: false },
    ]);
  });

});
