import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "@/routes";
import type { AdminPermission } from "@/app/admin-navigation";

const expectedPermissions = [
  "rules.read", "rules.write", "rules.publish", "rules.archive", "rules.set_default",
] as const satisfies readonly AdminPermission[];

function renderRoute(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("admin app routes", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "true");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("redirects the root to the operational overview", async () => {
    const router = renderRoute("/");

    expect(
      await screen.findByRole("heading", { name: "运营总览" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "后台主导航" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/overview");
    expect(screen.getByText("没有活动告警")).toBeInTheDocument();
  });

  it("navigates from the connected player list to its detail route", async () => {
    const user = userEvent.setup();
    const router = renderRoute("/content/players");

    await user.click(
      await screen.findByRole("link", { name: "编辑 雾灯听风" }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "雾灯听风" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(
      "/content/players/preview-draft-1",
    );
  });

  it("exposes rule permissions and preview navigation", async () => {
    expect(expectedPermissions).toHaveLength(5);
    renderRoute("/overview");
    expect(await screen.findByRole("link", { name: /游戏规则/ })).toHaveAttribute("href", "/content/rules");
  });

  it.each([
    ["/content/rules", "规则内容库"],
    ["/content/rules/new", "新建游戏规则"],
    ["/content/rules/classic_9", "游戏规则详情"],
  ])("resolves the lazy rule route %s", async (path, heading) => {
    renderRoute(path);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("forbids a connected session without rules.read", async () => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      if (String(input).endsWith("/api/v1/admin/me")) {
        return new Response(JSON.stringify({ user: { id: "viewer", email: "viewer@example.test", display_name: "观察员", role: "viewer" }, permissions: ["overview.read"], csrf_token: "csrf", session_expires_at: "2999-01-01T00:00:00Z" }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    }));
    const router = renderRoute("/content/rules");
    expect(await screen.findByRole("heading", { name: "没有访问权限" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/403");
  });

  it.each([
    ["/overview", "运营总览"],
    ["/content/players", "虚拟玩家"],
    ["/content/voice-assets", "法官语音资产"],
    ["/content/models", "模型管理"],
    ["/operations/games", "对局记录"],
    ["/operations/runs", "运行监控"],
    ["/system/settings", "运行设置"],
    ["/system/liveness-rollout", "灰度控制"],
  ])("keeps the existing route %s connected", async (path, heading) => {
    renderRoute(path);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("renders an admin-specific not found page", async () => {
    renderRoute("/not-a-real-admin-route");

    expect(
      await screen.findByRole("heading", { name: "后台页面不存在" }),
    ).toBeInTheDocument();
  });
});
