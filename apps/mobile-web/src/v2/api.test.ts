import { afterEach, describe, expect, it, vi } from "vitest";

import { createV2Game, fetchV2LiveSnapshot } from "./api";


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("createV2Game", () => {
  it("posts the existing lobby snapshot and accepts only a V2 ready game", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          game_id: "v2_game_0123456789abcdef",
          run_id: "v2_run_0123456789abcdef",
          status: "ready",
          snapshot_url:
            "/api/v2/live/games/v2_game_0123456789abcdef/snapshot",
          websocket_url: "/api/v2/live/games/v2_game_0123456789abcdef/ws",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = {
      title: "经典 8 人",
      lobby_snapshot: {
        schema_version: 1 as const,
        rule_set: {
          id: "classic_8",
          version: "1",
          name: "经典 8 人",
          player_count: 2,
          roles: [
            { role: "werewolf", count: 1 },
            { role: "villager", count: 1 },
          ],
        },
        rule_set_revision_id: "rule_rev_123",
        seed: null,
        max_rounds: 8,
        player_configs: [
          { seat: 1, profile_id: "profile-1" },
          { seat: 2, profile_id: "profile-2" },
        ],
        lineup_quality_report: {
          schema_version: 1 as const,
          policy_mode: "repair" as const,
          player_count: 2,
          configured_count: 2,
          is_blocked: false,
          was_repaired: false,
          style_bucket_count: 2,
          required_style_bucket_count: 2,
          violations: [],
        },
        allow_lineup_quality_warnings: false,
      },
    };

    const result = await createV2Game(request);

    expect(result.game_id).toBe("v2_game_0123456789abcdef");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe("/api/v2/games");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(request);
  });

  it("rejects a non-V2 creation response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            game_id: "old-game",
            run_id: "old-run",
            status: "ready",
            snapshot_url: "/api/v1/snapshot",
            websocket_url: "/api/v1/ws",
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      createV2Game({
        title: "非法响应",
        lobby_snapshot: {
          schema_version: 1,
          rule_set: {
            id: "classic_8",
            version: "1",
            name: "经典 8 人",
            player_count: 1,
            roles: [{ role: "villager", count: 1 }],
          },
          rule_set_revision_id: null,
          seed: null,
          max_rounds: 8,
          player_configs: [{ seat: 1, profile_id: "profile-1" }],
          lineup_quality_report: {
            schema_version: 1,
            policy_mode: "observe",
            player_count: 1,
            configured_count: 1,
            is_blocked: false,
            was_repaired: false,
            style_bucket_count: 1,
            required_style_bucket_count: 1,
            violations: [],
          },
          allow_lineup_quality_warnings: false,
        },
      }),
    ).rejects.toThrow("V2 实时直播协议无效");
  });
});

describe("fetchV2LiveSnapshot", () => {
  it("loads the ordered public seat projection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          protocol_version: 1,
          type: "live.snapshot",
          api_version: "v2",
          audience: "player_public",
          game_id: "v2_game_0123456789abcdef",
          run_id: "v2_run_0123456789abcdef",
          live_state: "ready",
          latest_presentation_seq: 0,
          server_time: "2026-07-22T12:00:00Z",
          public_players: [
            {
              seat: 1,
              player_id: "profile-1",
              display_name: "阿青",
              avatar_url: null,
            },
          ],
          current_presentation: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = await fetchV2LiveSnapshot("v2_game_0123456789abcdef");

    expect(snapshot.public_players).toEqual([
      {
        seat: 1,
        player_id: "profile-1",
        display_name: "阿青",
        avatar_url: null,
      },
    ]);
    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe(
      "/api/v2/live/games/v2_game_0123456789abcdef/snapshot",
    );
  });

  it("rejects private player fields in a public seat", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            protocol_version: 1,
            type: "live.snapshot",
            api_version: "v2",
            audience: "player_public",
            game_id: "v2_game_0123456789abcdef",
            run_id: "v2_run_0123456789abcdef",
            live_state: "ready",
            latest_presentation_seq: 0,
            server_time: "2026-07-22T12:00:00Z",
            public_players: [
              {
                seat: 1,
                player_id: "profile-1",
                display_name: "阿青",
                avatar_url: null,
                role: "werewolf",
              },
            ],
            current_presentation: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      fetchV2LiveSnapshot("v2_game_0123456789abcdef"),
    ).rejects.toThrow("V2 实时直播协议无效");
  });
});
