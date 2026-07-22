import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { contractJudgeVoiceList } from "@/features/voice-assets/test-fixtures";
import { routes } from "@/routes";
import { selectAntdOption } from "@/tests/antd-select";

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
  return { router };
}

function session(permissions: string[]) {
  return {
    user: {
      id: "10",
      email: "voice@example.test",
      display_name: "语音资产观察员",
      role: "viewer",
    },
    permissions,
    csrf_token: "csrf-voice",
    session_expires_at: "2999-01-01T00:00:00Z",
  };
}

describe("admin voice asset flow", () => {
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

  it("renders real inventory, safe audio URLs, filters and read-only actions", async () => {
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["voice.read"]));
      }
      if (url.includes("/api/v1/admin/judge-voice-lines?")) {
        listCalls += 1;
        return jsonResponse(contractJudgeVoiceList);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { router } = renderRoute("/content/voice-assets");

    expect(
      await screen.findByRole("heading", { name: "法官语音资产" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/玩家音色与基础演绎在玩家档案中配置/),
    ).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "后台主导航" });
    expect(within(navigation).getByText("法官语音")).toBeInTheDocument();
    expect(within(navigation).queryByText("虚拟玩家")).toBeNull();
    expect(await screen.findByText("game_intro")).toBeInTheDocument();
    expect(screen.getByText("night_start")).toBeInTheDocument();
    expect(
      within(screen.getByText("game_intro").closest("li")!).getByText("已使用"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByText("werewolves_confirm").closest("li")!).getByText("未使用"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("试听 game_intro")).toHaveAttribute(
      "src",
      "/api/v1/admin/judge-voice-lines/game_intro/audio",
    );
    expect(screen.getAllByText("等待后续生成任务")).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: /生成缺失|重新生成|删除/ }),
    ).toBeNull();

    await selectAntdOption(user, screen.getByLabelText("文件状态"), "缺失");
    await waitFor(() =>
      expect(router.state.location.search).toContain("availability=missing"),
    );
    await user.type(screen.getByLabelText("搜索台词"), "night");
    await user.click(screen.getByRole("button", { name: "应用筛选" }));
    await waitFor(() => expect(router.state.location.search).toContain("q=night"));
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("availability=missing"),
      ),
    ).toBe(true);

    const callsBeforeRefresh = listCalls;
    await user.click(screen.getByRole("button", { name: "手动刷新" }));
    await waitFor(() => expect(listCalls).toBeGreaterThan(callsBeforeRefresh));
  });

  it("shows a structured error and retries in place", async () => {
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["voice.read"]));
      }
      if (url.includes("/api/v1/admin/judge-voice-lines?")) {
        listCalls += 1;
        if (listCalls === 1) {
          return jsonResponse(
            {
              title: "Voice inventory unavailable",
              status: 503,
              detail: "语音资产目录暂时不可用",
              code: "admin_voice_asset_unavailable",
              request_id: "req-voice-list",
            },
            503,
          );
        }
        return jsonResponse(contractJudgeVoiceList);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/content/voice-assets");

    expect(
      await screen.findByRole("heading", { name: "无法读取语音资产" }),
    ).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-voice-list")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("game_intro")).toBeInTheDocument();
    expect(listCalls).toBe(2);
  });

  it("announces persistent generation job progress to assistive technology", async () => {
    const job = {
      id: "voice-job-1",
      mode: "missing",
      status: "completed",
      requested_line_ids: null,
      total_count: 2,
      processed_count: 2,
      generated_count: 2,
      skipped_count: 0,
      failed_count: 0,
      error_code: null,
      created_at: "2026-07-11T10:00:00Z",
      started_at: "2026-07-11T10:00:01Z",
      completed_at: "2026-07-11T10:00:03Z",
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["voice.read", "voice.generate_missing"]));
      }
      if (url.includes("/api/v1/admin/judge-voice-lines?")) {
        return jsonResponse(contractJudgeVoiceList);
      }
      if (url.endsWith("/api/v1/admin/judge-voice-generation-jobs")) {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-voice");
        expect(new Headers(init?.headers).get("Idempotency-Key")).toBeTruthy();
        return jsonResponse({ ...job, status: "queued", processed_count: 0 });
      }
      if (url.endsWith("/api/v1/admin/jobs/voice-job-1")) {
        return jsonResponse(job);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/content/voice-assets");

    await screen.findByRole("heading", { name: "法官语音资产" });
    await user.click(screen.getByRole("button", { name: "生成缺失语音" }));

    const status = await screen.findByRole("status", { name: "语音生成任务" });
    expect(status).toHaveTextContent("生成任务：已完成");
    expect(status).toHaveTextContent("2 / 2");
  });

  it("enforces deep-link and navigation permission", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["players.read"]));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/content/voice-assets");

    expect(
      await screen.findByRole("heading", { name: "没有访问权限" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("法官语音资产")).toBeNull();
    expect(screen.queryByText("法官语音")).toBeNull();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/api/v1/admin/judge-voice-lines"),
      ),
    ).toBe(false);
  });
});

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
