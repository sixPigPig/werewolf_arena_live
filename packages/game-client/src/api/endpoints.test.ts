import { afterEach, describe, expect, it, vi } from "vitest";

import { listPlayerProfiles } from "./listPlayerProfiles";
import { previewGameLineup } from "./previewGameLineup";
import { clearPublicSessionCache } from "./publicSession";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

describe("game API endpoints", () => {
  afterEach(() => {
    clearPublicSessionCache();
    vi.unstubAllGlobals();
  });

  it("lists player profiles from the existing backend contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ profiles: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPlayerProfiles()).resolves.toEqual({ profiles: [] });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/player-profiles", undefined);
  });

  it("previews a diverse lineup before creation", async () => {
    const preview = {
      player_configs: [{ seat: 1, profile_id: "profile-1" }],
      lineup_quality_report: {
        schema_version: 1,
        policy_mode: "repair",
        player_count: 1,
        configured_count: 1,
        is_blocked: false,
        was_repaired: true,
        style_bucket_count: 1,
        required_style_bucket_count: 1,
        violations: [],
      },
      rule_set_revision_id: "revision-1",
    } as const;
    const fetchMock = vi.fn(async () => jsonResponse(preview));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      previewGameLineup({
        rule_set_id: "starter_6",
        seed: 21,
        player_configs: [],
        locked_seats: [],
        repair_scope: "empty_only",
      }),
    ).resolves.toEqual(preview);

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/lineup-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rule_set_id: "starter_6",
        seed: 21,
        player_configs: [],
        locked_seats: [],
        repair_scope: "empty_only",
      }),
    });
  });
});
