import { afterEach, describe, expect, it, vi } from "vitest";

import {
  favoritePlayerProfile,
  listPlayerProfileFavorites,
  unfavoritePlayerProfile,
} from "./playerProfileFavorites";
import { clearPublicSessionCache } from "./publicSession";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

describe("public player profile favorites endpoints", () => {
  afterEach(() => {
    clearPublicSessionCache();
    vi.unstubAllGlobals();
  });

  it("bootstraps a guest session before reading favorites with credentials", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          viewer: { kind: "guest" },
          csrf_token: "csrf-token",
          session_expires_at: "2999-07-10T00:00:00.000Z",
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ profile_ids: ["profile-1"] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPlayerProfileFavorites()).resolves.toEqual({
      profile_ids: ["profile-1"],
    });
    expect(fetchMock.mock.calls).toEqual([
      [
        "/api/v1/public/session",
        { credentials: "include", method: "POST" },
      ],
      [
        "/api/v1/public/me/favorite-player-profiles",
        { credentials: "include" },
      ],
    ]);
  });

  it("uses idempotent PUT and DELETE writes with the cached CSRF token", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/public/session") {
        return jsonResponse({
          viewer: { kind: "guest" },
          csrf_token: "csrf-token",
          session_expires_at: "2999-07-10T00:00:00.000Z",
        });
      }
      return jsonResponse({
        profile_id: "profile one",
        is_favorite: init?.method === "PUT",
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(favoritePlayerProfile("profile one")).resolves.toEqual({
      profile_id: "profile one",
      is_favorite: true,
    });
    await expect(favoritePlayerProfile("profile one")).resolves.toEqual({
      profile_id: "profile one",
      is_favorite: true,
    });
    await expect(unfavoritePlayerProfile("profile one")).resolves.toEqual({
      profile_id: "profile one",
      is_favorite: false,
    });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls.slice(1)).toEqual([
      [
        "/api/v1/public/me/favorite-player-profiles/profile%20one",
        {
          credentials: "include",
          headers: { "X-CSRF-Token": "csrf-token" },
          method: "PUT",
        },
      ],
      [
        "/api/v1/public/me/favorite-player-profiles/profile%20one",
        {
          credentials: "include",
          headers: { "X-CSRF-Token": "csrf-token" },
          method: "PUT",
        },
      ],
      [
        "/api/v1/public/me/favorite-player-profiles/profile%20one",
        {
          credentials: "include",
          headers: { "X-CSRF-Token": "csrf-token" },
          method: "DELETE",
        },
      ],
    ]);
  });

  it("rebuilds a stale cross-tab session once after a CSRF rejection", async () => {
    let sessionCount = 0;
    let writeCount = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/public/session") {
        sessionCount += 1;
        return jsonResponse({
          viewer: { kind: "guest" },
          csrf_token: `csrf-${sessionCount}`,
          session_expires_at: "2999-07-10T00:00:00.000Z",
        });
      }

      writeCount += 1;
      if (writeCount === 1) {
        return new Response(JSON.stringify({ detail: "stale csrf" }), {
          headers: { "content-type": "application/json" },
          status: 403,
        });
      }
      return jsonResponse({ profile_id: "profile-1", is_favorite: true });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(favoritePlayerProfile("profile-1")).resolves.toEqual({
      profile_id: "profile-1",
      is_favorite: true,
    });
    expect(sessionCount).toBe(2);
    expect(writeCount).toBe(2);
    expect(fetchMock.mock.calls[3]).toEqual([
      "/api/v1/public/me/favorite-player-profiles/profile-1",
      {
        credentials: "include",
        headers: { "X-CSRF-Token": "csrf-2" },
        method: "PUT",
      },
    ]);
  });

  it("recovers a favorites GET once when the guest session was revoked", async () => {
    let sessionCount = 0;
    let readCount = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/public/session") {
        sessionCount += 1;
        return jsonResponse({
          viewer: { kind: "guest" },
          csrf_token: `csrf-${sessionCount}`,
          session_expires_at: "2999-07-10T00:00:00.000Z",
        });
      }

      readCount += 1;
      if (readCount === 1) {
        return new Response(JSON.stringify({ detail: "expired" }), {
          headers: { "content-type": "application/json" },
          status: 401,
        });
      }
      return jsonResponse({ profile_ids: ["profile-1"] });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPlayerProfileFavorites()).resolves.toEqual({
      profile_ids: ["profile-1"],
    });
    expect(sessionCount).toBe(2);
    expect(readCount).toBe(2);
  });

  it("shares one recovery bootstrap across concurrent stale-session writes", async () => {
    let sessionCount = 0;
    let initialWriteCount = 0;
    let recoveredWriteCount = 0;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/public/session") {
        sessionCount += 1;
        return jsonResponse({
          viewer: { kind: "guest" },
          csrf_token: `csrf-${sessionCount}`,
          session_expires_at: "2999-07-10T00:00:00.000Z",
        });
      }
      if (init?.method === undefined) {
        return jsonResponse({ profile_ids: [] });
      }

      const csrfToken = (init.headers as Record<string, string>)["X-CSRF-Token"];
      if (csrfToken === "csrf-1") {
        initialWriteCount += 1;
        return new Response(JSON.stringify({ detail: "stale" }), {
          headers: { "content-type": "application/json" },
          status: 403,
        });
      }

      recoveredWriteCount += 1;
      const profileId = decodeURIComponent(url.split("/").at(-1) ?? "");
      return jsonResponse({ profile_id: profileId, is_favorite: true });
    });
    vi.stubGlobal("fetch", fetchMock);

    await listPlayerProfileFavorites();
    await expect(
      Promise.all([
        favoritePlayerProfile("profile-1"),
        favoritePlayerProfile("profile-2"),
      ]),
    ).resolves.toEqual([
      { profile_id: "profile-1", is_favorite: true },
      { profile_id: "profile-2", is_favorite: true },
    ]);
    expect(sessionCount).toBe(2);
    expect(initialWriteCount).toBe(2);
    expect(recoveredWriteCount).toBe(2);
  });

  it("does not retry a second session rejection", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/public/session") {
        return jsonResponse({
          viewer: { kind: "guest" },
          csrf_token: "csrf-token",
          session_expires_at: "2999-07-10T00:00:00.000Z",
        });
      }
      return new Response(JSON.stringify({ detail: "rejected" }), {
        headers: { "content-type": "application/json" },
        status: 403,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(favoritePlayerProfile("profile-1")).rejects.toThrow(
      "Request failed with status 403",
    );
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});
