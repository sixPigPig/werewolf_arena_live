import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createV2Game,
  fetchV2DirectorLiveSnapshot,
  fetchV2GodViewIdentitySnapshot,
  fetchV2LiveSnapshot,
} from "./api";


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("createV2Game", () => {
  it("posts the existing lobby snapshot and accepts only a waiting V2 game", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          game_id: "v2_game_0123456789abcdef",
          run_id: "v2_run_0123456789abcdef",
          status: "waiting_to_start",
          audio_mode: "text_only",
          snapshot_url:
            "/api/v2/live/games/v2_game_0123456789abcdef/snapshot",
          websocket_url: "/api/v2/live/games/v2_game_0123456789abcdef/ws",
          director_snapshot_url:
            "/api/v2/director/games/v2_game_0123456789abcdef/snapshot",
          director_websocket_url:
            "/api/v2/director/games/v2_game_0123456789abcdef/ws",
          god_view_snapshot_url:
            "/api/v2/god-view/games/v2_game_0123456789abcdef/identity-snapshot",
          god_view_websocket_url:
            "/api/v2/god-view/games/v2_game_0123456789abcdef/ws",
          god_view_access_token: "a".repeat(43),
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = {
      title: "经典 8 人",
      audio_mode: "text_only" as const,
      lobby_snapshot: {
        schema_version: 1 as const,
        model_binding_mode: "profile_library" as const,
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
          {
            seat: 1,
            profile_id: "profile-1",
          },
          {
            seat: 2,
            profile_id: "profile-2",
          },
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
    expect(result.audio_mode).toBe("text_only");
    expect(result.god_view_access_token).toBe("a".repeat(43));
    expect(result.director_websocket_url).toBe(
      "/api/v2/director/games/v2_game_0123456789abcdef/ws",
    );
    expect(result.god_view_websocket_url).toBe(
      "/api/v2/god-view/games/v2_game_0123456789abcdef/ws",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe("/api/v2/games");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(request);
  });

  it("preserves a stale rule revision conflict for lobby recovery", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "rule_revision_changed",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      createV2Game({ title: "过期规则" } as Parameters<typeof createV2Game>[0]),
    ).rejects.toMatchObject({
      name: "V2GameCreateError",
      status: 409,
      code: "rule_revision_changed",
    });
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
        audio_mode: "tts",
        lobby_snapshot: {
          schema_version: 1,
          model_binding_mode: "profile_library",
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
          player_configs: [
            {
              seat: 1,
              profile_id: "profile-1",
            },
          ],
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

describe("fetchV2DirectorLiveSnapshot", () => {
  it("accepts the contextual identity projection without a God View token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          protocol_version: 1,
          type: "director.live_snapshot",
          api_version: "v2",
          audience: "spectator_directed",
          game_id: "v2_game_0123456789abcdef",
          run_id: "v2_run_0123456789abcdef",
          live_state: "ready",
          game_phase: openingPhase(),
          match_state: {
            round_no: 1,
            sheriff_player_id: null,
            sheriff_badge_state: "disabled",
            winner: null,
          },
          latest_presentation_seq: 0,
          server_time: "2026-07-22T12:00:00Z",
          rule: null,
          players: [
            {
              seat: 1,
              player_id: "profile-1",
              display_name: "阿青",
              avatar_url: null,
              role: "werewolf",
              team: "werewolves",
              alive: true,
              death_cause: null,
            },
          ],
          current_scene: {
            scene_kind: "opening",
            action_id: null,
            action_type: null,
            ability_id: null,
            actor_player_id: null,
          },
          current_presentation: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = await fetchV2DirectorLiveSnapshot(
      "v2_game_0123456789abcdef",
    );

    expect(snapshot.audience).toBe("spectator_directed");
    expect(snapshot.players[0].role).toBe("werewolf");
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has("Authorization"))
      .toBe(false);
    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe(
      "/api/v2/director/games/v2_game_0123456789abcdef/snapshot",
    );
  });
});

describe("fetchV2GodViewIdentitySnapshot", () => {
  it("sends the capability token and accepts only the strict God View projection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          protocol_version: 1,
          type: "god_view.identity_snapshot",
          api_version: "v2",
          audience: "spectator_god_view",
          game_id: "v2_game_0123456789abcdef",
          run_id: "v2_run_0123456789abcdef",
          live_state: "waiting_to_start",
          game_phase: openingPhase(),
          match_state: {
            round_no: 1,
            sheriff_player_id: null,
            sheriff_badge_state: "disabled",
            winner: null,
          },
          server_time: "2026-07-22T12:00:00Z",
          rule: {
            rule_id: "classic_2",
            name: "测试两人局",
            version: "1",
            player_count: 2,
            roles: [
              { role: "狼人", count: 1 },
              { role: "村民", count: 1 },
            ],
            max_rounds: 8,
            sheriff_enabled: false,
            werewolf_self_explosion_enabled: false,
            exile_last_words_enabled: true,
            first_night_last_words_enabled: false,
          },
          players: [
            {
              seat: 1,
              player_id: "profile-1",
              display_name: "阿青",
              avatar_url: null,
              role: "狼人",
              team: "werewolves",
              alive: true,
              death_cause: null,
            },
            {
              seat: 2,
              player_id: "profile-2",
              display_name: "白石",
              avatar_url: null,
              role: "村民",
              team: "villagers",
              alive: true,
              death_cause: null,
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = await fetchV2GodViewIdentitySnapshot(
      "v2_game_0123456789abcdef",
      "a".repeat(43),
    );

    expect(snapshot.players.map((player) => player.role)).toEqual(["狼人", "村民"]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe(
      "/api/v2/god-view/games/v2_game_0123456789abcdef/identity-snapshot",
    );
    expect(new Headers(init.headers).get("Authorization")).toBe(
      `Bearer ${"a".repeat(43)}`,
    );
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
          game_phase: openingPhase(),
          match_state: {
            round_no: 1,
            sheriff_player_id: null,
            sheriff_badge_state: "disabled",
            winner: null,
          },
          latest_presentation_seq: 0,
          server_time: "2026-07-22T12:00:00Z",
          public_rule: {
            rule_id: "classic_2",
            name: "测试两人局",
            version: "1",
            player_count: 2,
            roles: [
              { role: "狼人", count: 1 },
              { role: "村民", count: 1 },
            ],
            max_rounds: 8,
            sheriff_enabled: false,
            werewolf_self_explosion_enabled: true,
            exile_last_words_enabled: true,
            first_night_last_words_enabled: false,
          },
          public_players: [
            {
              seat: 1,
              player_id: "profile-1",
              display_name: "阿青",
              avatar_url: null,
              alive: true,
            },
          ],
          public_role_assignment: { state: "sealed", assigned_count: 2 },
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
        alive: true,
      },
    ]);
    expect(snapshot.public_rule?.roles).toEqual([
      { role: "狼人", count: 1 },
      { role: "村民", count: 1 },
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
            game_phase: openingPhase(),
            latest_presentation_seq: 0,
            server_time: "2026-07-22T12:00:00Z",
            public_rule: null,
            public_players: [
              {
                seat: 1,
                player_id: "profile-1",
                display_name: "阿青",
                avatar_url: null,
                alive: true,
                role: "werewolf",
              },
            ],
            public_role_assignment: { state: "sealed", assigned_count: 1 },
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

  it("rejects private fields in a public rule snapshot", async () => {
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
            game_phase: openingPhase(),
            latest_presentation_seq: 0,
            server_time: "2026-07-22T12:00:00Z",
            public_rule: {
              rule_id: "classic_1",
              name: "测试规则",
              version: "1",
              player_count: 1,
              roles: [{ role: "村民", count: 1 }],
              max_rounds: 8,
              sheriff_enabled: false,
              werewolf_self_explosion_enabled: false,
              exile_last_words_enabled: true,
              first_night_last_words_enabled: false,
              content_hash: "must-not-leak",
            },
            public_players: [],
            public_role_assignment: { state: "unavailable", assigned_count: 0 },
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

  it("rejects private fields in the public role assignment status", async () => {
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
            game_phase: openingPhase(),
            latest_presentation_seq: 0,
            server_time: "2026-07-22T12:00:00Z",
            public_rule: null,
            public_players: [],
            public_role_assignment: {
              state: "sealed",
              assigned_count: 1,
              assignments: [{ seat: 1, role: "狼人" }],
            },
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

  it("rejects private role assignments beside the public snapshot contract", async () => {
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
            game_phase: openingPhase(),
            latest_presentation_seq: 0,
            server_time: "2026-07-22T12:00:00Z",
            public_rule: null,
            public_players: [],
            public_role_assignment: { state: "sealed", assigned_count: 1 },
            private_role_assignments: [{ seat: 1, role: "狼人" }],
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

function openingPhase() {
  return {
    phase_seq: 1,
    phase_id: "opening",
    phase_state: "opening_ready",
  };
}
