import { afterEach, describe, expect, it, vi } from "vitest";

import { clearPublicSessionCache, ensurePublicSession } from "./publicSession";

const session = {
  viewer: { kind: "guest" as const },
  csrf_token: "csrf-public-session",
  session_expires_at: "2999-07-10T00:00:00.000Z",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status,
  });
}

describe("public session bootstrap", () => {
  afterEach(() => {
    clearPublicSessionCache();
    vi.unstubAllGlobals();
  });

  it("shares one bootstrap request across concurrent callers and caches the session", async () => {
    let resolveFetch!: (response: Response) => void;
    const response = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });
    const fetchMock = vi.fn(() => response);
    vi.stubGlobal("fetch", fetchMock);

    const first = ensurePublicSession();
    const second = ensurePublicSession();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveFetch(jsonResponse(session));
    await expect(Promise.all([first, second])).resolves.toEqual([session, session]);
    await expect(ensurePublicSession()).resolves.toEqual(session);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/public/session", {
      credentials: "include",
      method: "POST",
    });
  });

  it("clears a failed bootstrap so the next caller can retry", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "unavailable" }, 503))
      .mockResolvedValueOnce(jsonResponse(session));
    vi.stubGlobal("fetch", fetchMock);

    await expect(ensurePublicSession()).rejects.toThrow(
      "Request failed with status 503",
    );
    await expect(ensurePublicSession()).resolves.toEqual(session);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retain an already expired session", async () => {
    const expiredSession = {
      ...session,
      csrf_token: "expired-token",
      session_expires_at: "2000-01-01T00:00:00.000Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(expiredSession))
      .mockResolvedValueOnce(jsonResponse(session));
    vi.stubGlobal("fetch", fetchMock);

    await expect(ensurePublicSession()).resolves.toEqual(expiredSession);
    await expect(ensurePublicSession()).resolves.toEqual(session);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
