import {
  createAdminDevSession,
  deleteAdminSession,
  parseAdminSession,
} from "@/features/auth/auth-api";

const validSession = {
  user: {
    id: "42",
    email: "admin@example.test",
    display_name: "Arena Admin",
    role: "operator",
  },
  permissions: ["overview.read", "runs.read"],
  csrf_token: "csrf-123",
  session_expires_at: "2027-01-01T00:00:00Z",
};

describe("admin auth API contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses the server session DTO", () => {
    expect(parseAdminSession(validSession)).toEqual(validSession);
  });

  it("rejects malformed users instead of trusting an untyped payload", () => {
    expect(() =>
      parseAdminSession({
        ...validSession,
        user: { ...validSession.user, id: 42 },
      }),
    ).toThrowError(expect.objectContaining({ code: "admin_invalid_session_response" }));
  });

  it("sends no browser-selected identity when creating a dev session", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(validSession), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createAdminDevSession();

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/admin/dev-login");
    expect(options.method).toBe("POST");
    expect(options.body).toBeUndefined();
    expect(options.credentials).toBe("include");
  });

  it("uses the in-memory session CSRF token for logout", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await deleteAdminSession("csrf-from-session");

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(
      "csrf-from-session",
    );
  });
});
