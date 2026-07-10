import { adminApiFetch } from "@/api/client";
import { AdminApiError } from "@/api/problem-details";

describe("adminApiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("always sends cookie credentials and accepts JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(adminApiFetch<{ ok: boolean }>("/api/check")).resolves.toEqual(
      { ok: true },
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(options.credentials).toBe("include");
    expect(new Headers(options.headers).get("Accept")).toBe("application/json");
  });

  it("surfaces Problem Details with stable code and request id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            type: "https://example.test/problems/permission",
            title: "Permission denied",
            status: 403,
            detail: "Missing players.write",
            code: "admin_permission_denied",
            request_id: "req-403",
          }),
          {
            headers: { "Content-Type": "application/problem+json" },
            status: 403,
          },
        ),
      ),
    );

    const request = adminApiFetch("/api/v1/admin/protected");
    await expect(request).rejects.toMatchObject({
      code: "admin_permission_denied",
      message: "Missing players.write",
      requestId: "req-403",
      status: 403,
    });
    await expect(request).rejects.toBeInstanceOf(AdminApiError);
  });

  it("normalizes network failures without exposing the original error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("socket details")));

    await expect(adminApiFetch("/api/v1/admin/me")).rejects.toMatchObject({
      code: "admin_network_error",
      status: 0,
    });
  });

  it("preserves conflict versions and structured field errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            title: "Version conflict",
            status: 409,
            detail: "Profile changed",
            code: "admin_player_profile_version_conflict",
            request_id: "req-conflict",
            current_version: 8,
          }),
          { status: 409 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            title: "Invalid request",
            status: 422,
            detail: "Validation failed",
            code: "admin_request_invalid",
            request_id: "req-invalid",
            errors: [{ field: "display_name", message: "名称已存在" }],
          }),
          { status: 422 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(adminApiFetch("/conflict")).rejects.toMatchObject({
      currentVersion: 8,
      requestId: "req-conflict",
    });
    await expect(adminApiFetch("/invalid")).rejects.toMatchObject({
      fieldErrors: [{ field: "display_name", message: "名称已存在" }],
      requestId: "req-invalid",
    });
  });
});
