import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { dispatchAdminSessionExpired } from "@/api/client";
import { routes } from "@/routes";

const fullSession = {
  user: {
    id: "42",
    email: "admin@example.test",
    display_name: "Arena Admin",
    role: "super_admin",
  },
  permissions: [
    "overview.read",
    "runs.read",
    "games.read",
    "players.read",
    "voice.read",
    "users.manage",
    "roles.manage",
    "audit.read",
    "settings.read",
  ],
  csrf_token: "csrf-session",
  session_expires_at: "2999-01-01T00:00:00Z",
};

function renderAuthenticatedRoute(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { queryClient, router };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": status >= 400 ? "application/problem+json" : "application/json" },
    status,
  });
}

function authProblem(status: 401 | 403) {
  return {
    type: "about:blank",
    title: status === 401 ? "Authentication required" : "Permission denied",
    status,
    detail: status === 401 ? "Admin session required" : "Admin access denied",
    code: status === 401 ? "admin_auth_required" : "admin_permission_denied",
    request_id: `req-${status}`,
  };
}

describe("admin session flow", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "true");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("redirects a 401 to dev login, logs in without identity input, and logs out with CSRF", async () => {
    let authenticated = false;
    const fetchMock = vi.fn<typeof fetch>(
      async (input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith("/me")) {
          return authenticated
            ? jsonResponse(fullSession)
            : jsonResponse(authProblem(401), 401);
        }
        if (url.endsWith("/dev-login")) {
          authenticated = true;
          return jsonResponse(fullSession);
        }
        if (url.endsWith("/logout")) {
          authenticated = false;
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAuthenticatedRoute("/not-a-real-admin-route");

    await user.click(
      await screen.findByRole("button", { name: "使用开发身份登录" }),
    );
    expect(
      await screen.findByRole("heading", { name: "后台页面不存在" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Arena Admin")).toBeInTheDocument();

    const devLoginCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/dev-login"),
    );
    expect(devLoginCall?.[1]?.body).toBeUndefined();

    await user.click(screen.getByRole("button", { name: "退出" }));
    expect(
      await screen.findByText("已安全退出后台。"),
    ).toBeInTheDocument();

    const logoutCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/logout"),
    );
    expect(new Headers(logoutCall?.[1]?.headers).get("X-CSRF-Token")).toBe(
      "csrf-session",
    );
  });

  it("renders the dedicated 403 page when /me rejects the principal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(authProblem(403), 403)),
    );

    renderAuthenticatedRoute("/overview");

    expect(
      await screen.findByRole("heading", { name: "没有访问权限" }),
    ).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-403")).toBeInTheDocument();
  });

  it("does not render a dev login action without the explicit frontend flag", async () => {
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(authProblem(401), 401)),
    );

    renderAuthenticatedRoute("/overview");

    expect(
      await screen.findByRole("heading", { name: "登录管理后台" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "使用开发身份登录" }),
    ).not.toBeInTheDocument();
  });

  it("uses permissions, not roles, to protect deep links", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          ...fullSession,
          user: { ...fullSession.user, role: "super_admin" },
          permissions: ["overview.read"],
        }),
      ),
    );

    renderAuthenticatedRoute("/content/players");

    expect(
      await screen.findByRole("heading", { name: "没有访问权限" }),
    ).toBeInTheDocument();
  });

  it("clears authenticated state when another API reports session expiry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(fullSession)));
    renderAuthenticatedRoute("/not-a-real-admin-route");
    expect(
      await screen.findByRole("heading", { name: "后台页面不存在" }),
    ).toBeInTheDocument();

    act(() => dispatchAdminSessionExpired());

    expect(
      await screen.findByText("会话已过期。请重新登录后继续。"),
    ).toBeInTheDocument();
  });

  it("never renders protected content for an already expired /me response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          ...fullSession,
          session_expires_at: "2020-01-01T00:00:00Z",
        }),
      ),
    );
    renderAuthenticatedRoute("/overview");

    expect(
      await screen.findByRole("heading", { name: "登录管理后台" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "运营总览" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByText("会话已过期。请重新登录后继续。"),
    ).toBeInTheDocument();
  });
});
