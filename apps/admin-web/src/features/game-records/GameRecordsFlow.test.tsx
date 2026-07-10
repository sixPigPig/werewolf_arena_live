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

import {
  contractGameDebug,
  contractGameDetail,
  contractGameItem,
} from "@/features/game-records/test-fixtures";
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
      id: "7",
      email: "viewer@example.test",
      display_name: "只读观察员",
      role: "viewer",
    },
    permissions,
    csrf_token: "csrf-games",
    session_expires_at: "2999-01-01T00:00:00Z",
  };
}

describe("admin game record flow", () => {
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

  it("renders real API records and keeps server filters in the URL", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read"]));
      }
      if (url.includes("/api/v1/admin/games?")) {
        const requestUrl = new URL(url, "https://admin.test");
        const status = requestUrl.searchParams.get("status");
        const runStatus = requestUrl.searchParams.get("run_status");
        return jsonResponse({
          items: [
            status === "partial"
              ? {
                  ...contractGameItem,
                  status: "partial",
                  winner: null,
                  latest_run: {
                    ...contractGameItem.latest_run,
                    status: runStatus ?? "completed",
                    has_error: runStatus === "failed",
                    villager_model: null,
                    werewolf_model: null,
                  },
                }
              : contractGameItem,
          ],
          pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { router } = renderRoute("/operations/games");

    expect(
      await screen.findByRole("heading", { name: "对局记录" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("game_1234abcd")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "查看对局 game_1234abcd" }),
    ).toHaveAttribute("href", "/operations/games/game_1234abcd");

    await user.selectOptions(screen.getByLabelText("对局状态"), "partial");
    await waitFor(() =>
      expect(router.state.location.search).toContain("status=partial"),
    );
    await waitFor(() =>
      expect(
        within(
          screen.getByRole("list", { name: "对局记录列表" }),
        ).getByText("部分记录"),
      ).toBeInTheDocument(),
    );

    await user.selectOptions(
      screen.getByLabelText("最新运行状态"),
      "failed",
    );
    await waitFor(() =>
      expect(router.state.location.search).toContain("run_status=failed"),
    );

    await user.type(screen.getByLabelText("搜索对局"), "run_1234");
    await user.click(screen.getByRole("button", { name: "应用筛选" }));
    await waitFor(() =>
      expect(router.state.location.search).toContain("q=run_1234"),
    );
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("q=run_1234"),
      ),
    ).toBe(true);
  });

  it("shows filter-aware empty state and blocks invalid date ranges locally", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read"]));
      }
      if (url.includes("/api/v1/admin/games?")) {
        return jsonResponse({
          items: [],
          pagination: { page: 1, page_size: 20, total: 0, pages: 0 },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/games?status=complete");

    expect(
      await screen.findByRole("heading", { name: "没有符合条件的对局" }),
    ).toBeInTheDocument();

    cleanup();
    vi.unstubAllGlobals();
    const invalidFetch = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read"]));
      }
      throw new Error(`List request must not run: ${url}`);
    });
    vi.stubGlobal("fetch", invalidFetch);
    renderRoute(
      "/operations/games?created_from=2026-07-11&created_to=2026-07-10",
    );
    expect(
      await screen.findByText("开始日期不能晚于结束日期，请调整后重新筛选。"),
    ).toBeInTheDocument();
    expect(
      invalidFetch.mock.calls.some(([input]) =>
        String(input).includes("/api/v1/admin/games?"),
      ),
    ).toBe(false);
  });

  it("shows a structured list error and retries without leaving the page", async () => {
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read"]));
      }
      if (url.includes("/api/v1/admin/games?")) {
        listCalls += 1;
        if (listCalls === 1) {
          return jsonResponse(
            {
              title: "Game service unavailable",
              status: 503,
              detail: "对局记录暂时不可用",
              code: "admin_games_unavailable",
              request_id: "req-game-list",
            },
            503,
          );
        }
        return jsonResponse({
          items: [contractGameItem],
          pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/games");

    expect(
      await screen.findByRole("heading", { name: "无法读取对局记录" }),
    ).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-game-list")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("game_1234abcd")).toBeInTheDocument();
    expect(listCalls).toBe(2);
  });

  it("renders base detail for viewers without requesting restricted debug", async () => {
    const partialDetail = {
      ...contractGameDetail,
      status: "partial",
      winner: null,
      latest_run: {
        ...contractGameDetail.latest_run,
        has_error: true,
        villager_model: null,
        werewolf_model: null,
      },
      players: [
        { ...contractGameDetail.players[0], role: null, model: null },
      ],
      rounds: contractGameDetail.rounds.map((round) => ({
        ...round,
        night_deaths: round.night_deaths.map((death) => ({
          ...death,
          cause: null,
          source: null,
        })),
        day_deaths: round.day_deaths.map((death) => ({
          ...death,
          cause: null,
          source: null,
        })),
      })),
      recent_events: [],
      diagnostics: { ...contractGameDetail.diagnostics, last_event: null },
      runs: contractGameDetail.runs.map((run) => ({
        ...run,
        has_error: true,
        villager_model: null,
        werewolf_model: null,
      })),
    };
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse(partialDetail);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/games/game_1234abcd");

    expect(
      await screen.findByRole("heading", { level: 1, name: "game_1234abcd" }),
    ).toBeInTheDocument();
    expect(screen.getByText("首轮完成公开投票。")).toBeInTheDocument();
    expect(screen.getByText("未公开")).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("list", { name: "玩家与角色结果" }),
      ).getByText("模型未公开"),
    ).toBeInTheDocument();
    expect(screen.getByText("雾灯听风")).toBeInTheDocument();
    expect(screen.queryByText("werewolf_attack")).not.toBeInTheDocument();
    expect(
      screen.getByText("对局未终局或仍可恢复，事件元数据暂不公开。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("对局终局后才会公开事件元数据。"),
    ).toBeInTheDocument();
    expect(screen.getByText("该对局包含错误标记")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith("/debug")),
    ).toBe(false);
  });

  it("requests audited debug only after an authorized explicit click", async () => {
    const detailWithError = {
      ...contractGameDetail,
      latest_run: { ...contractGameDetail.latest_run, has_error: true },
      runs: contractGameDetail.runs.map((run) => ({ ...run, has_error: true })),
    };
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(
          session(["games.read", "games.debug.read"]),
        );
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse(detailWithError);
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd/debug")) {
        return jsonResponse(contractGameDebug);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/games/game_1234abcd");

    const loadDebug = await screen.findByRole("button", {
      name: "加载受限错误摘要",
    });
    expect(
      screen.getByText(
        "按需读取经过脱敏的错误分类；最多展示最近 20 条，读取行为会进入审计日志。",
      ),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith("/debug")),
    ).toBe(false);
    expect(screen.queryByText("Maximum rounds exceeded")).not.toBeInTheDocument();

    await user.click(loadDebug);
    expect(await screen.findByText("Maximum rounds exceeded")).toBeInTheDocument();
    expect(screen.getByText("Upstream request timed out")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/debug")),
    ).toHaveLength(1);
  });

  it("keeps base detail available when the optional debug request fails", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(
          session(["games.read", "games.debug.read"]),
        );
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse(contractGameDetail);
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd/debug")) {
        return jsonResponse(
          {
            title: "Debug unavailable",
            status: 503,
            detail: "错误摘要暂时不可读取",
            code: "admin_game_debug_unavailable",
            request_id: "req-debug",
          },
          503,
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/games/game_1234abcd");

    await user.click(
      await screen.findByRole("button", { name: "加载受限错误摘要" }),
    );
    expect(
      await screen.findByText("错误摘要暂时不可用"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "game_1234abcd" }),
    ).toBeInTheDocument();
    expect(screen.getByText("首轮完成公开投票。")).toBeInTheDocument();
  });

  it("shows 404 detail state and enforces route and navigation permissions", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_deadbeef")) {
        return jsonResponse(
          {
            title: "Game not found",
            status: 404,
            detail: "对局不存在",
            code: "admin_game_not_found",
            request_id: "req-missing-game",
          },
          404,
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/games/game_deadbeef");
    expect(
      await screen.findByRole("heading", { name: "对局不存在" }),
    ).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-missing-game")).toBeInTheDocument();

    cleanup();
    vi.unstubAllGlobals();
    const deniedFetch = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["players.read"]));
      }
      throw new Error(`Protected game endpoint called: ${url}`);
    });
    vi.stubGlobal("fetch", deniedFetch);
    renderRoute("/operations/games");
    expect(
      await screen.findByRole("heading", { name: "没有访问权限" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "对局记录" })).not.toBeInTheDocument();
    expect(
      deniedFetch.mock.calls.some(([input]) =>
        String(input).includes("/api/v1/admin/games"),
      ),
    ).toBe(false);
  });
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type":
        status >= 400 ? "application/problem+json" : "application/json",
    },
    status,
  });
}
