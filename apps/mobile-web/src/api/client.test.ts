import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("returns parsed JSON for successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 })));

    await expect(apiFetch<{ status: string }>("/api/v1/health")).resolves.toEqual({ status: "ok" });
  });

  it("raises ApiError with status and detail for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Player profile database unavailable" }), { status: 503 })));

    await expect(apiFetch("/api/v1/player-profiles")).rejects.toMatchObject({
      name: "ApiError",
      status: 503,
      detail: "Player profile database unavailable",
    });
  });
});
