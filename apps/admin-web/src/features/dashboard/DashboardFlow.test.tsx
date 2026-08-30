import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "@/routes";

const session = {
  user: {
    id: "42",
    email: "admin@example.test",
    display_name: "Arena Admin",
    role: "super_admin",
  },
  permissions: ["overview.read", "voice.read", "settings.read"],
  csrf_token: "csrf-dashboard",
  session_expires_at: "2999-01-01T00:00:00Z",
};

const overview = {
  generated_at: "2026-07-12T00:00:00Z",
  environment: "staging",
  profiles: { total: 9, draft: 2, published: 6, archived: 1, featured: 2 },
  jobs: { total: 4, queued: 0, running: 1, completed: 2, failed: 1 },
  alerts: [
    {
      code: "failed_jobs",
      severity: "warning",
      title: "语音任务失败",
      detail: "有法官语音生成任务失败。",
      count: 1,
      href: "/system/jobs?status=failed",
    },
  ],
};

const settings = {
  environment: "staging",
  api_prefix: "/api/v1",
  tts_enabled: true,
  authentication: {
    oidc_enabled: true,
    development_login_enabled: false,
    secure_admin_cookie: true,
    secure_public_cookie: true,
    admin_session_ttl_seconds: 28800,
    public_session_ttl_seconds: 2592000,
  },
  compatibility: {
    legacy_content_writes_enabled: false,
    legacy_voice_generation_enabled: false,
  },
  workers: {
    judge_voice_poll_seconds: 2,
    judge_voice_heartbeat_seconds: 10,
    judge_voice_probe_max_age_seconds: 45,
  },
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status: 200,
  });
}

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

describe("admin dashboard flow", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = String(input);
        if (url.endsWith("/api/v1/admin/me")) return jsonResponse(session);
        if (url.endsWith("/api/v1/admin/overview")) return jsonResponse(overview);
        if (url.endsWith("/api/v1/admin/settings")) return jsonResponse(settings);
        if (url.includes("/api/v1/admin/jobs?")) {
          return jsonResponse({
            items: [
              {
                id: "job-voice-01",
                type: "judge_voice_generation",
                mode: "missing",
                status: "running",
                total_count: 10,
                processed_count: 4,
                generated_count: 4,
                failed_count: 0,
                error_code: null,
                created_at: "2026-07-12T00:00:00Z",
                started_at: "2026-07-12T00:00:01Z",
                completed_at: null,
              },
            ],
            pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
          });
        }
        if (url.includes("/api/v1/admin/search?")) {
          return jsonResponse({
            query: "job-voice",
            items: [
              {
                type: "job",
                id: "job-voice-01",
                label: "语音生成任务 job-voice-01",
                description: "生成缺失语音",
                status: "running",
                href: "/system/jobs?job=job-voice-01",
              },
            ],
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("renders real overview metrics and an anomaly reminder", async () => {
    renderRoute("/overview");
    expect(await screen.findByRole("heading", { name: "运营总览" })).toBeInTheDocument();
    expect(screen.getByText("语音任务失败")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "1 项异常" })).toBeInTheDocument();
    expect(screen.getAllByText("STAGING").length).toBeGreaterThan(0);
  });

  it("opens persistent jobs and read-only settings from navigation", async () => {
    const user = userEvent.setup();
    const router = renderRoute("/overview");
    await screen.findByRole("heading", { name: "运营总览" });

    await user.click(screen.getByRole("link", { name: /任务中心/ }));
    expect(await screen.findByRole("heading", { name: "后台任务" })).toBeInTheDocument();
    expect(await screen.findByText("job-voice-01")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /系统设置/ }));
    expect(await screen.findByRole("heading", { name: "运行设置" })).toBeInTheDocument();
    expect(screen.getByText("认证边界")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/system/settings");
  });

  it("searches IDs globally and navigates to the safe internal result", async () => {
    const user = userEvent.setup();
    const router = renderRoute("/overview");
    const search = await screen.findByLabelText("全局 ID 搜索");
    const searchControl = search.closest(".ant-input-affix-wrapper");
    const logoutButton = screen.getByRole("button", { name: "退出" });

    expect(searchControl).not.toHaveClass("ant-input-affix-wrapper-sm");
    expect(searchControl).not.toHaveClass("ant-input-affix-wrapper-lg");
    expect(logoutButton).not.toHaveClass("ant-btn-sm");
    expect(logoutButton).not.toHaveClass("ant-btn-lg");

    await user.type(search, "j");

    const result = await screen.findByRole("link", {
      name: /语音生成任务 job-voice-01/,
    });
    await user.click(result);
    await waitFor(() => expect(router.state.location.pathname).toBe("/system/jobs"));
    expect(router.state.location.search).toBe("?job=job-voice-01");
  });
});
