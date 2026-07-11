import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { contractJudgeVoiceList } from "@/features/voice-assets/test-fixtures";
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
    const navigation = screen.getByRole("navigation", { name: "后台主导航" });
    expect(within(navigation).getByText("法官语音")).toBeInTheDocument();
    expect(within(navigation).queryByText("虚拟玩家")).toBeNull();
    expect(await screen.findByText("game_intro")).toBeInTheDocument();
    expect(screen.getByText("night_start")).toBeInTheDocument();
    expect(screen.getByLabelText("试听 game_intro")).toHaveAttribute(
      "src",
      "/api/v1/admin/judge-voice-lines/game_intro/audio",
    );
    expect(screen.getByText("等待后续生成任务")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /生成缺失|重新生成|删除/ }),
    ).toBeNull();

    await user.selectOptions(screen.getByLabelText("文件状态"), "missing");
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
