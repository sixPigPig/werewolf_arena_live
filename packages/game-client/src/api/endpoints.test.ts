import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun } from "./createGameRun";
import { listGames } from "./listGames";
import { listPlayerProfiles } from "./listPlayerProfiles";
import { resumeGameRun } from "./resumeGameRun";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

describe("game API endpoints", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists games from the existing backend contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ sessions: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listGames()).resolves.toEqual({ sessions: [] });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games", undefined);
  });

  it("lists player profiles from the existing backend contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ profiles: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPlayerProfiles()).resolves.toEqual({ profiles: [] });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/player-profiles", undefined);
  });

  it("creates a run with the current web request body", async () => {
    const run = {
      run_id: "run-1",
      session_id: "session-1",
      villager_model: "",
      werewolf_model: "",
      rule_set: null,
      seed: null,
      max_rounds: 8,
      winner: null,
      status: "queued",
      created_at: "2026-06-19T00:00:00Z",
      started_at: null,
      completed_at: null,
      error: null,
      event_count: 0,
    };
    const fetchMock = vi.fn(async () => jsonResponse(run));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createGameRun({
        rule_set_id: "classic_8",
        max_rounds: 8,
        player_configs: [{ seat: 1, profile_id: "profile-1" }],
      }),
    ).resolves.toEqual(run);

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rule_set_id: "classic_8",
        max_rounds: 8,
        player_configs: [{ seat: 1, profile_id: "profile-1" }],
      }),
    });
  });

  it("resumes a failed session by session id", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        run_id: "run-2",
        session_id: "session-2",
        villager_model: "",
        werewolf_model: "",
        rule_set: null,
        seed: null,
        max_rounds: 8,
        winner: null,
        status: "queued",
        created_at: "2026-06-19T00:00:00Z",
        started_at: null,
        completed_at: null,
        error: null,
        event_count: 0,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await resumeGameRun("session-2");

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/session-2/resume", {
      method: "POST",
    });
  });
});
