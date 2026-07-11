import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "@/routes";

const rootSession = {
  user: { id: "1", email: "root@example.test", display_name: "Root Admin", role: "super_admin" },
  permissions: ["users.manage", "roles.manage", "audit.read"],
  csrf_token: "csrf-system",
  session_expires_at: "2999-01-01T00:00:00Z",
};

const operator = {
  id: "2",
  email: "operator@example.test",
  display_name: "Operations User",
  role: "operator",
  is_active: true,
  identity_status: "bound",
  active_session_count: 1,
  last_session_at: "2026-07-11T10:00:00Z",
  created_at: "2026-07-10T10:00:00Z",
  updated_at: "2026-07-11T10:00:00Z",
  version: 3,
};

function renderRoute(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
  return { router };
}

describe("admin system flows", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("provisions, edits and revokes sessions through real API contracts", async () => {
    let current = { ...operator };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) return json(rootSession);
      if (url.includes("/api/v1/admin/users?")) {
        return json({ items: [current], pagination: { page: 1, page_size: 20, total: 1, pages: 1 } });
      }
      if (url.endsWith("/api/v1/admin/users") && init?.method === "POST") {
        expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-system");
        expect(new Headers(init.headers).get("Idempotency-Key")).toBeTruthy();
        const body = JSON.parse(String(init.body));
        return json({ ...operator, id: "3", email: body.email, display_name: body.display_name, role: body.role, identity_status: "unbound", active_session_count: 0, last_session_at: null, version: 1 }, 201);
      }
      if (url.endsWith("/api/v1/admin/users/2") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        expect(body.expected_version).toBe(3);
        current = { ...current, display_name: body.display_name, role: body.role, version: 4 };
        return json(current);
      }
      if (url.endsWith("/api/v1/admin/users/2/revoke-sessions")) {
        current = { ...current, active_session_count: 0 };
        return json({ user_id: "2", revoked_count: 1 });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/system/users");

    expect(await screen.findByRole("heading", { name: "后台账号" })).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "后台主导航" });
    expect(within(navigation).getByText("后台账号")).toBeInTheDocument();
    expect(within(navigation).getByText("审计日志")).toBeInTheDocument();
    expect(await screen.findByText("operator@example.test")).toBeInTheDocument();
    expect(screen.queryByText(/auth_subject|provider-hash/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "开通账号" }));
    await user.type(screen.getByLabelText("邮箱"), "viewer@example.test");
    await user.type(screen.getByLabelText("显示名称"), "New Viewer");
    await user.selectOptions(screen.getByLabelText("固定角色"), "viewer");
    await user.type(screen.getByLabelText("操作原因"), "New support account");
    await user.click(screen.getByRole("button", { name: "确认开通" }));
    expect(await screen.findByText("已开通 viewer@example.test")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "管理 Operations User" }));
    await user.clear(screen.getByLabelText("显示名称"));
    await user.type(screen.getByLabelText("显示名称"), "Primary Operator");
    await user.selectOptions(screen.getByLabelText("固定角色"), "content_editor");
    await user.type(screen.getByLabelText("操作原因"), "Team responsibility changed");
    await user.click(screen.getByRole("button", { name: "保存账号" }));
    expect(await screen.findByText("已更新 operator@example.test")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "管理 Primary Operator" }));
    await user.type(screen.getByLabelText("操作原因"), "Security response revocation");
    await user.click(screen.getByRole("button", { name: "撤销全部会话" }));
    expect(await screen.findByText("已撤销 1 个会话")).toBeInTheDocument();
  });

  it("renders minimal audit records and URL-backed filters", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) return json(rootSession);
      if (url.includes("/api/v1/admin/audit-events?")) return json({
        items: [{
          id: "audit-1",
          actor: { id: "1", email: "root@example.test", display_name: "Root Admin" },
          action: "admin.user.update",
          resource_type: "user",
          resource_id: "2",
          result: "success",
          reason: "Role adjustment",
          request_id: "req-audit-1",
          created_at: "2026-07-11T10:00:00Z",
        }],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      });
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { router } = renderRoute("/system/audit");

    expect(await screen.findByRole("heading", { name: "审计日志" })).toBeInTheDocument();
    expect(await screen.findByText("admin.user.update")).toBeInTheDocument();
    expect(screen.getByText("Role adjustment")).toBeInTheDocument();
    expect(screen.queryByText(/before|after|ip_address/)).toBeNull();
    await user.selectOptions(screen.getByLabelText("审计结果"), "failure");
    await waitFor(() => expect(router.state.location.search).toContain("result=failure"));
  });

  it("enforces audit deep links and navigation permission", async () => {
    const fetchMock = vi.fn(async (input) => {
      if (String(input).endsWith("/api/v1/admin/me")) {
        return json({ ...rootSession, permissions: ["users.manage"] });
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/system/audit");

    expect(await screen.findByRole("heading", { name: "没有访问权限" })).toBeInTheDocument();
    expect(screen.queryByText("审计日志")).toBeNull();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/audit-events"))).toBe(false);
  });
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
