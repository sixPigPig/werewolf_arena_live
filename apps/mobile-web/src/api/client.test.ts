import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("returns parsed JSON for successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 })));

    await expect(apiFetch<{ status: string }>("/api/v1/health")).resolves.toEqual({ status: "ok" });
  });

  it("returns undefined for 204 responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));

    await expect(apiFetch<void>("/api/v1/games/runs/run_1/events")).resolves.toBeUndefined();
  });

  it("raises ApiError with status and detail for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Player profile database unavailable" }), { status: 503 })));

    await expect(apiFetch("/api/v1/player-profiles")).rejects.toMatchObject({
      name: "ApiError",
      status: 503,
      detail: "Player profile database unavailable",
    });
  });

  it("unstubs fetch after each test", () => {
    expect(vi.isMockFunction(fetch)).toBe(false);
  });
});
