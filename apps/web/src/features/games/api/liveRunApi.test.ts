import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun } from "./createGameRun";
import { getGameRun } from "./getGameRun";
import { resumeGameRun } from "./resumeGameRun";

describe("live run api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a game run", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1234abcd",
          session_id: "game_1200abcd",
          villager_model: "deepseek",
          werewolf_model: "minimax",
          rule_set_id: "starter_6",
          rule_set: {
            id: "starter_6",
            version: "2026.04",
            name: "新手 6 人快局",
            player_count: 6,
            roles: [],
          },
          seed: 21,
          max_rounds: 8,
          winner: null,
          status: "queued",
          created_at: "2026-04-24T12:00:00Z",
          started_at: null,
          completed_at: null,
          error: null,
          event_count: 1,
          event_pacing: "standard",
          player_configs: [
            {
              seat: 1,
              profile_id: "profile-1",
              name: "冷静的阿夜",
              model: "deepseek-chat",
              personality_id: "cautious",
              personality: "谨慎观察局势。",
              appearance_id: "moonlit",
              avatar_prompt: "银发观察者",
              tags: ["控场"],
            },
          ],
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );

    const run = await createGameRun({
      rule_set_id: "starter_6",
      seed: 21,
      max_rounds: 8,
      player_configs: [
        {
          seat: 1,
          profile_id: "profile-1",
          name: "冷静的阿夜",
          model: "deepseek-chat",
          personality_id: "cautious",
          appearance_id: "moonlit",
          avatar_prompt: "银发观察者",
        },
      ],
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rule_set_id: "starter_6",
          seed: 21,
          max_rounds: 8,
          player_configs: [
            {
              seat: 1,
              profile_id: "profile-1",
              name: "冷静的阿夜",
              model: "deepseek-chat",
              personality_id: "cautious",
              appearance_id: "moonlit",
              avatar_prompt: "银发观察者",
            },
          ],
        }),
      }),
    );
    expect(run.run_id).toBe("run_1234abcd");
    expect(run.max_rounds).toBe(8);
    expect(run.player_configs?.[0]?.profile_id).toBe("profile-1");
  });

  it("gets a game run", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1234abcd",
          session_id: "game_1200abcd",
          villager_model: "deepseek",
          werewolf_model: "minimax",
          seed: 21,
          max_rounds: 8,
          winner: "Villagers",
          status: "running",
          created_at: "2026-04-24T12:00:00Z",
          started_at: "2026-04-24T12:00:01Z",
          completed_at: null,
          error: null,
          event_count: 4,
          event_pacing: "slow",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const run = await getGameRun("run_1234abcd");

    expect(run.status).toBe("running");
    expect(run.event_count).toBe(4);
    expect(run.event_pacing).toBe("slow");
    expect(run.winner).toBe("Villagers");
  });

  it("resumes a game run from a saved checkpoint", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_resumed",
          session_id: "game_1200abcd",
          villager_model: "Qwen3.6-Plus",
          werewolf_model: "MiniMax-M2.7",
          seed: 21,
          max_rounds: 8,
          winner: null,
          status: "queued",
          created_at: "2026-04-24T12:05:00Z",
          started_at: null,
          completed_at: null,
          error: null,
          event_count: 1,
          event_pacing: "off",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );

    const run = await resumeGameRun("game_1200abcd");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/game_1200abcd/resume",
      expect.objectContaining({ method: "POST" }),
    );
    expect(run.run_id).toBe("run_resumed");
    expect(run.session_id).toBe("game_1200abcd");
  });
});
