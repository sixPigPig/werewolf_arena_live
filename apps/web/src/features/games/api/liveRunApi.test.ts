import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun } from "./createGameRun";
import { getGameRun } from "./getGameRun";

describe("live run api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a game run", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1234abcd",
          session_id: "session_20260424_120000_ab12cd34",
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
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );

    const run = await createGameRun({
      rule_set_id: "starter_6",
      seed: 21,
      max_rounds: 8,
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
        }),
      }),
    );
    expect(run.run_id).toBe("run_1234abcd");
    expect(run.max_rounds).toBe(8);
  });

  it("gets a game run", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1234abcd",
          session_id: "session_20260424_120000_ab12cd34",
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
});
