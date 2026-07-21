import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { contractGameDetail } from "@/features/game-records/test-fixtures";
import {
  contractActiveLiveRunDetail,
  contractLiveRunDebug,
  contractLiveRunDetail,
  contractLiveRunItem,
} from "@/features/live-runs/test-fixtures";
import { routes } from "@/routes";

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
  return { queryClient, router };
}

function session(permissions: string[]) {
  return {
    user: {
      id: "9",
      email: "operator@example.test",
      display_name: "运行观察员",
      role: "operator",
    },
    permissions,
    csrf_token: "csrf-runs",
    session_expires_at: "2999-01-01T00:00:00Z",
  };
}

describe("admin live run flow", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders real API rows, URL filters, manual refresh and read-only actions", async () => {
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read"]));
      }
      if (url.includes("/api/v1/admin/live-runs?")) {
        listCalls += 1;
        return jsonResponse({
          items: [contractLiveRunItem],
          pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { router } = renderRoute("/operations/runs");

    expect(
      await screen.findByRole("heading", { name: "运行监控" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("run_1234abcd")).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "后台主导航" });
    expect(within(navigation).getByText("运行监控")).toBeInTheDocument();
    expect(within(navigation).queryByText("对局记录")).toBeNull();
    expect(
      screen.getByRole("link", { name: "查看运行 run_1234abcd" }),
    ).toHaveAttribute("href", "/operations/runs/run_1234abcd");
    expect(
      screen.queryByRole("button", { name: /打断|停止|恢复|重试运行/ }),
    ).toBeNull();

    await user.selectOptions(screen.getByLabelText("运行状态"), "failed");
    await waitFor(() =>
      expect(router.state.location.search).toContain("status=failed"),
    );
    await user.type(screen.getByLabelText("搜索运行"), "run_1234");
    await user.click(screen.getByRole("button", { name: "应用筛选" }));
    await waitFor(() =>
      expect(router.state.location.search).toContain("q=run_1234"),
    );

    const callsBeforeRefresh = listCalls;
    await user.click(screen.getByRole("button", { name: "手动刷新" }));
    await waitFor(() => expect(listCalls).toBeGreaterThan(callsBeforeRefresh));
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("sort=-updated_at"),
      ),
    ).toBe(true);
  });

  it("blocks an invalid date range locally", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read"]));
      }
      throw new Error(`List request must not run: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(
      "/operations/runs?created_from=2026-07-11&created_to=2026-07-10",
    );

    expect(
      await screen.findByText("开始日期不能晚于结束日期，请调整后重新筛选。"),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/api/v1/admin/live-runs?"),
      ),
    ).toBe(false);
  });

  it("shows a structured list error and retries in place", async () => {
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read"]));
      }
      if (url.includes("/api/v1/admin/live-runs?")) {
        listCalls += 1;
        if (listCalls === 1) {
          return jsonResponse(
            {
              title: "Run service unavailable",
              status: 503,
              detail: "运行记录暂时不可用",
              code: "admin_live_runs_unavailable",
              request_id: "req-run-list",
            },
            503,
          );
        }
        return jsonResponse({
          items: [contractLiveRunItem],
          pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/runs");

    expect(
      await screen.findByRole("heading", { name: "无法读取运行记录" }),
    ).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-run-list")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("run_1234abcd")).toBeInTheDocument();
    expect(listCalls).toBe(2);
  });

  it("renders an active redacted detail without requesting restricted debug", async () => {
    const activeWithError = {
      ...contractActiveLiveRunDetail,
      has_error: false,
      voice_counts: {
        ...contractActiveLiveRunDetail.voice_counts,
        pending: 0,
        failed: 1,
      },
    };
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read"]));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_active123")) {
        return jsonResponse(activeWithError);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/runs/run_active123");

    expect(
      await screen.findByRole("heading", { name: "run_active123" }),
    ).toBeInTheDocument();
    expect(screen.getByText("可能失联")).toBeInTheDocument();
    expect(screen.getByText(/活动已归类以保护未终局身份/)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "P2 运行质量" }),
    ).toBeInTheDocument();
    expect(screen.getByText("采集中")).toBeInTheDocument();
    expect(screen.getByText("2 / 1")).toBeInTheDocument();
    expect(screen.getAllByText("样本不足")).toHaveLength(2);
    expect(screen.getByText(/样本 18 · 最大值 13200 ms/)).toBeInTheDocument();
    expect(screen.getByText("Provider attempt 终态")).toBeInTheDocument();
    expect(screen.getByText(/有效 24 · 非法 1 · 超时 1/)).toBeInTheDocument();
    expect(screen.getByText("Logical action 来源")).toBeInTheDocument();
    expect(
      screen.getByText(/模型完成 22 · 系统 fallback 1 · 取消 0 · 失败 1/),
    ).toBeInTheDocument();
    expect(screen.getByText(/需要 runs.debug.read 权限/)).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getByText("doubao-seed-1-6-flash")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith("/debug")),
    ).toBe(false);
    expect(
      screen.queryByRole("button", { name: /打断|停止|恢复|重试运行/ }),
    ).toBeNull();
  });

  it("does not synthesize attempt or logical-action distributions for older payloads", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read"]));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_active123")) {
        return jsonResponse({
          ...contractActiveLiveRunDetail,
          p2_diagnostics: {
            ...contractActiveLiveRunDetail.p2_diagnostics,
            provider_attempt_outcomes: undefined,
            logical_action_outcomes: undefined,
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/runs/run_active123");

    expect(
      await screen.findByRole("heading", { name: "P2 运行质量" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Provider 超时 / 系统降级")).toBeInTheDocument();
    expect(screen.getByText("1 / —")).toBeInTheDocument();
    expect(screen.queryByText("Provider attempt 终态")).not.toBeInTheDocument();
    expect(screen.queryByText("Logical action 来源")).not.toBeInTheDocument();
  });

  it("renders an explicit legacy P2 empty state without fake metrics", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read"]));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_1234abcd")) {
        return jsonResponse({
          ...contractLiveRunDetail,
          p2_diagnostics: {
            ...contractLiveRunDetail.p2_diagnostics,
            data_status: "legacy",
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/runs/run_1234abcd");

    expect(
      await screen.findByRole("heading", { name: "P2 运行质量" }),
    ).toBeInTheDocument();
    expect(screen.getByText("旧数据")).toBeInTheDocument();
    expect(
      screen.getByText("旧运行未采集 P2 指标，不能判定为通过。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("P95 0 ms")).not.toBeInTheDocument();
  });

  it("stops an active run with reason, csrf and idempotency protection", async () => {
    let stopRequested = false;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read", "runs.control"]));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_active123/stop")) {
        const headers = new Headers(init?.headers);
        expect(init?.method).toBe("POST");
        expect(headers.get("X-CSRF-Token")).toBe("csrf-runs");
        expect(headers.get("Idempotency-Key")).toBeTruthy();
        expect(JSON.parse(String(init?.body))).toEqual({
          reason: "模型持续超时，停止本次运行",
        });
        stopRequested = true;
        return jsonResponse(
          {
            action: "stop",
            target_run_id: "run_active123",
            run_id: "run_active123",
            session_id: "game_active123",
            run_status: "running",
            stop_requested_at: "2026-07-11T08:00:00Z",
            replayed: false,
          },
          202,
        );
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_active123")) {
        return jsonResponse({
          ...contractActiveLiveRunDetail,
          stop_requested_at: stopRequested
            ? "2026-07-11T08:00:00Z"
            : null,
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/runs/run_active123");

    await user.click(await screen.findByRole("button", { name: "打断对局" }));
    const reason = screen.getByLabelText("操作原因");
    await user.type(reason, "模型持续超时，停止本次运行");
    await user.click(screen.getByRole("button", { name: "确认打断" }));

    expect(
      await screen.findByText(/停止新请求并尽快关闭当前模型流/),
    ).toBeInTheDocument();
    expect(screen.getByText("打断请求已提交")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打断对局" })).toBeNull();
  });

  it("resumes a canceled checkpoint into a new run and navigates to it", async () => {
    const canceledDetail = {
      ...contractActiveLiveRunDetail,
      status: "canceled",
      completed_at: "2026-07-11T08:01:00Z",
      stop_requested_at: "2026-07-11T08:00:00Z",
      is_stale: false,
      worker_state: "released",
    } as const;
    const resumedDetail = {
      ...contractActiveLiveRunDetail,
      run_id: "run_resumed123",
      session_id: "game_active123",
      status: "queued",
      stop_requested_at: null,
      is_stale: false,
    } as const;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read", "runs.control"]));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_active123/resume")) {
        return jsonResponse(
          {
            action: "resume",
            target_run_id: "run_active123",
            run_id: "run_resumed123",
            session_id: "game_active123",
            run_status: "queued",
            stop_requested_at: null,
            replayed: false,
          },
          201,
        );
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_active123")) {
        return jsonResponse(canceledDetail);
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_resumed123")) {
        return jsonResponse(resumedDetail);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { router } = renderRoute("/operations/runs/run_active123");

    await user.click(
      await screen.findByRole("button", { name: "从检查点恢复" }),
    );
    await user.type(screen.getByLabelText("操作原因"), "服务恢复，继续执行");
    await user.click(screen.getByRole("button", { name: "确认恢复" }));

    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        "/operations/runs/run_resumed123",
      ),
    );
    expect(
      await screen.findByRole("heading", { name: "run_resumed123" }),
    ).toBeInTheDocument();
  });

  it("offers fenced checkpoint takeover for a stale active worker", async () => {
    const staleDetail = {
      ...contractActiveLiveRunDetail,
      worker_state: "stale",
      is_stale: true,
      recovery_attempts: 3,
      recovery_exhausted: true,
    } as const;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read", "runs.control"]));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_active123")) {
        return jsonResponse(staleDetail);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/runs/run_active123");

    await user.click(
      await screen.findByRole("button", { name: "从检查点恢复" }),
    );

    expect(screen.getByText(/自动恢复已耗尽，需要人工处理/)).toBeInTheDocument();
    expect(screen.queryByText(/下次自动认领不早于/)).toBeNull();
    expect(
      screen.getByText(/旧 Worker 的后续写入会被拒绝/),
    ).toBeInTheDocument();
  });

  it("requests debug only after an authorized click and links to the game", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read", "runs.debug.read", "games.read"]));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_1234abcd/debug")) {
        return jsonResponse(contractLiveRunDebug);
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_1234abcd")) {
        return jsonResponse(contractLiveRunDetail);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/runs/run_1234abcd");

    expect(
      await screen.findByRole("heading", { name: "run_1234abcd" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "查看关联对局" }),
    ).toHaveAttribute("href", "/operations/games/game_1234abcd");
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith("/debug")),
    ).toBe(false);

    await user.click(
      screen.getByRole("button", { name: "加载受限错误摘要" }),
    );
    expect(
      await screen.findByText("Upstream request timed out"),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith("/debug")),
    ).toBe(true);
  });

  it("keeps the base detail usable when the independent debug request fails", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["runs.read", "runs.debug.read"]));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_1234abcd/debug")) {
        return jsonResponse(
          {
            title: "Debug unavailable",
            status: 503,
            detail: "受限摘要暂时不可用",
            code: "admin_live_run_debug_unavailable",
            request_id: "req-run-debug",
          },
          503,
        );
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_1234abcd")) {
        return jsonResponse(contractLiveRunDetail);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/runs/run_1234abcd");

    await user.click(
      await screen.findByRole("button", { name: "加载受限错误摘要" }),
    );
    expect(
      await screen.findByText("错误摘要暂时不可用"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "run_1234abcd" }),
    ).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
  });

  it("renders a stable 404 and enforces runs.read", async () => {
    let permissions = ["runs.read"];
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(permissions));
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_missing")) {
        return jsonResponse(
          {
            title: "Live run not found",
            status: 404,
            detail: "运行不存在",
            code: "admin_live_run_not_found",
            request_id: "req-run-404",
          },
          404,
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/runs/run_missing");

    expect(
      await screen.findByRole("heading", { name: "运行不存在" }),
    ).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-run-404")).toBeInTheDocument();

    cleanup();
    vi.unstubAllGlobals();
    permissions = ["games.read"];
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/runs");
    expect(
      await screen.findByRole("heading", { name: "没有访问权限" }),
    ).toBeInTheDocument();
  });

  it("links from a game run summary back to the run monitor", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read", "runs.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse(contractGameDetail);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/games/game_1234abcd");

    expect(
      await screen.findByRole("heading", { name: "game_1234abcd" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "run_1234abcd" })).toHaveAttribute(
      "href",
      "/operations/runs/run_1234abcd",
    );
  });
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}
