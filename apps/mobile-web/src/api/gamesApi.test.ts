import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun, listRuleSets } from "./gamesApi";
import type { GamePlaybackResponse, GameRun, LiveGameEvent } from "./types";

const liveEventFixture = {
  id: 1,
  type: "run_created",
  run_id: "run_1",
  session_id: "session_1",
  created_at: "2026-06-18T00:00:00Z",
  round: null,
  phase: null,
  actor: null,
  action: null,
  payload: { session_id: "session_1" },
} satisfies LiveGameEvent;

const playbackFixture = {
  session_id: "session_1",
  status: "complete",
  rule_set: null,
  resumable: false,
  events: [liveEventFixture],
} satisfies GamePlaybackResponse;

const gameRunFixture = {
  run_id: "run_1",
  session_id: "session_1",
  villager_model: "openai/gpt-4.1-mini",
  werewolf_model: "openai/gpt-4.1-mini",
  seed: 1234,
  max_rounds: 8,
  rule_set_id: "classic_12",
  rule_set: {
    id: "classic_12",
    version: "1",
    name: "Classic 12",
    player_count: 12,
    roles: [],
  },
  player_configs: [],
  lineup_quality_warnings: [],
  status: "running",
  created_at: "2026-06-18T00:00:00Z",
  started_at: "2026-06-18T00:00:01Z",
  completed_at: null,
  winner: null,
  error: null,
  event_count: 1,
} satisfies GameRun;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("gamesApi", () => {
  it("lists rule sets from the existing backend path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ rule_sets: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await listRuleSets();

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/rule-sets", undefined);
  });

  it("creates game runs through the existing backend path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ run_id: "run_1", session_id: "session_1", status: "queued" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    await createGameRun({ rule_set_id: "classic_12", max_rounds: 8 });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rule_set_id: "classic_12", max_rounds: 8 }),
    });
  });

  it("tracks backend playback and run transport shapes", () => {
    expect(playbackFixture.events[0]).toMatchObject({
      run_id: "run_1",
      session_id: "session_1",
      created_at: "2026-06-18T00:00:00Z",
    });
    expect(gameRunFixture).toMatchObject({
      rule_set_id: "classic_12",
      event_count: 1,
    });
  });

  it("unstubs fetch after each test", () => {
    expect(vi.isMockFunction(fetch)).toBe(false);
  });
});
