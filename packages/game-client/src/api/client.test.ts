import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("prefixes requests with the configured base URL and parses JSON", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ status: "ok" }), {
        headers: { "content-type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiFetch<{ status: string }>("/api/v1/health", undefined, {
        baseUrl: "http://api.test",
      }),
    ).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/api/v1/health",
      undefined,
    );
  });

  it("throws a useful error when the response is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 503 })),
    );

    await expect(apiFetch("/api/v1/player-profiles")).rejects.toThrow(
      "Request failed with status 503",
    );
  });

  it("returns undefined for empty 204 responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );

    await expect(apiFetch<void>("/api/v1/empty")).resolves.toBeUndefined();
  });
});
