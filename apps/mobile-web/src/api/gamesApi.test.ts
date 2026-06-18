import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun, listRuleSets } from "./gamesApi";

afterEach(() => {
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
});
