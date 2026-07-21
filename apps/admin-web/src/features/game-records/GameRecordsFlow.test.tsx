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
  contractGameModelRequestDetail,
  contractGameModelRequests,
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

function modelRequestFixtureResponse(url: string) {
  if (url.endsWith("/api/v1/admin/games/game_1234abcd/model-requests")) {
    return jsonResponse(contractGameModelRequests);
  }
  if (
    url.endsWith(
      "/api/v1/admin/games/game_1234abcd/model-requests/req_contract_model_1",
    )
  ) {
    return jsonResponse(contractGameModelRequestDetail);
  }
  return null;
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
    expect(
      screen.queryByRole("button", { name: "删除对局 game_1234abcd" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "打断对局 game_1234abcd" }),
    ).not.toBeInTheDocument();

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

  it("lets a privileged admin confirm deletion and refreshes the list", async () => {
    let deleted = false;
    let listCalls = 0;
    let deleteCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read", "games.delete"]));
      }
      if (url.includes("/api/v1/admin/games?")) {
        listCalls += 1;
        return jsonResponse({
          items: deleted ? [] : [contractGameItem],
          pagination: {
            page: 1,
            page_size: 20,
            total: deleted ? 0 : 1,
            pages: deleted ? 0 : 1,
          },
        });
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        deleteCalls += 1;
        expect(init?.method).toBe("DELETE");
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe(
          "csrf-games",
        );
        deleted = true;
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/games");

    const opener = await screen.findByRole("button", {
      name: "删除对局 game_1234abcd",
    });
    await user.click(opener);
    const dialog = screen.getByRole("alertdialog", { name: "删除对局" });
    expect(dialog).toHaveAccessibleDescription();
    expect(within(dialog).getByText("game_1234abcd")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toHaveFocus();
    expect(deleteCalls).toBe(0);

    await user.click(screen.getByRole("button", { name: "确认删除" }));

    expect(
      await screen.findByRole("heading", { name: "还没有对局记录" }),
    ).toBeInTheDocument();
    expect(deleteCalls).toBe(1);
    expect(listCalls).toBeGreaterThanOrEqual(2);
  });

  it("interrupts an active game from the game list to protect API quota", async () => {
    let stopRequested = false;
    let listCalls = 0;
    const activeGame = {
      ...contractGameItem,
      status: "partial",
      winner: null,
      resumable: true,
      latest_run: {
        ...contractGameItem.latest_run,
        status: "running",
        completed_at: null,
        stop_requested_at: null,
      },
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read", "runs.control"]));
      }
      if (url.includes("/api/v1/admin/games?")) {
        listCalls += 1;
        return jsonResponse({
          items: [
            {
              ...activeGame,
              latest_run: {
                ...activeGame.latest_run,
                stop_requested_at: stopRequested
                  ? "2026-07-21T04:00:00Z"
                  : null,
              },
            },
          ],
          pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
        });
      }
      if (url.endsWith("/api/v1/admin/live-runs/run_1234abcd/stop")) {
        expect(init?.method).toBe("POST");
        const headers = new Headers(init?.headers);
        expect(headers.get("X-CSRF-Token")).toBe("csrf-games");
        expect(headers.get("Idempotency-Key")).toBeTruthy();
        expect(JSON.parse(String(init?.body))).toEqual({
          reason: "人工打断异常对局，避免继续消耗 API 额度",
        });
        stopRequested = true;
        return jsonResponse(
          {
            action: "stop",
            target_run_id: "run_1234abcd",
            run_id: "run_1234abcd",
            session_id: "game_1234abcd",
            run_status: "running",
            stop_requested_at: "2026-07-21T04:00:00Z",
            replayed: false,
          },
          202,
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/games");

    await user.click(
      await screen.findByRole("button", { name: "打断对局 game_1234abcd" }),
    );
    const dialog = screen.getByRole("alertdialog", { name: "打断对局" });
    expect(dialog).toHaveAccessibleDescription();
    expect(within(dialog).getByText("game_1234abcd")).toBeInTheDocument();
    expect(within(dialog).getByText(/run_1234abcd/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "确认打断" }));

    expect(await screen.findByText("正在打断")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "打断对局 game_1234abcd" }),
    ).not.toBeInTheDocument();
    expect(listCalls).toBeGreaterThanOrEqual(2);
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
      },
      players: [
        { ...contractGameDetail.players[0], role: null },
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
      ).getByText("deepseek-v4-flash"),
    ).toBeInTheDocument();
    expect(screen.getByText("雾灯听风")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "P2 对局质量" }),
    ).toBeInTheDocument();
    expect(screen.getByText("自动修复")).toBeInTheDocument();
    expect(screen.getByText("Provider attempt")).toBeInTheDocument();
    expect(screen.getByText("Logical action 来源")).toBeInTheDocument();
    expect(
      screen.getByText(/模型完成 22 · 系统 fallback 1 · 取消 0 · 失败 1/),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "P2 质量门槛" })).toHaveClass(
      "game-quality-list",
    );
    expect(screen.getByLabelText("赛后复盘任务状态")).toHaveTextContent(
      "已完成 / 2",
    );
    expect(screen.getByLabelText("赛后复盘任务状态")).toHaveTextContent(
      "source-revis · p3-v1",
    );
    expect(screen.getByLabelText("赛后复盘任务状态")).toHaveTextContent(
      "最近成功结果",
    );
    expect(screen.getByLabelText("赛后复盘任务状态")).toHaveTextContent(
      "不可重试",
    );
    expect(screen.getByLabelText("P3 来源覆盖")).toHaveClass(
      "game-quality-coverage",
    );
    const criticalDecisions = screen.getByRole("list", {
      name: "P3 关键决策",
    });
    expect(
      within(criticalDecisions).getByText("第 1 轮 · 放逐投票"),
    ).toBeInTheDocument();
    expect(within(criticalDecisions).getByText("缺少规则条款")).toBeInTheDocument();
    expect(within(criticalDecisions).getByText("合法且已执行")).toBeInTheDocument();
    expect(within(criticalDecisions).getByText("使用了未提供规则")).toBeInTheDocument();
    expect(within(criticalDecisions).getByText("票型已记录")).toBeInTheDocument();
    expect(
      within(criticalDecisions).getByText(/模型判断与规则输入共同影响/),
    ).toBeInTheDocument();
    expect(
      within(criticalDecisions).getByText(/规则覆盖：缺失 0\/1/),
    ).toBeInTheDocument();
    expect(screen.getByText("分析 · 控场")).toBeInTheDocument();
    expect(
      screen.getByText("我会先听完大家的上警理由。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("结合票型，我认为灰塔更可疑。"),
    ).toBeInTheDocument();
    expect(screen.getByText("结算与摘要一致")).toBeInTheDocument();
    expect(screen.getByText("样本不足")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "P2 质量门槛" }).children).toHaveLength(5);
    expect(
      screen.getByRole("heading", { name: "公开结算链" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "公开结算链" })).toHaveClass(
      "game-public-outcome-list",
    );
    expect(screen.getByText(/2号玩家夜间出局/)).toBeInTheDocument();
    expect(
      screen.getByText(/2号玩家发动猎人技能带走5号玩家/),
    ).toBeInTheDocument();
    expect(screen.getByText("因果来源 outcome_fixture_1")).toBeInTheDocument();
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

  it("renders game detail when the quality evaluation has no source revision", async () => {
    const detailWithoutEvaluation = {
      ...contractGameDetail,
      quality_evaluation: {
        ...contractGameDetail.quality_evaluation,
        evaluation_status: "not_scheduled",
        data_status: "legacy",
        verdict: "unavailable",
        source_revision: null,
        created_at: null,
        started_at: null,
        completed_at: null,
        attempt_count: 0,
        latest_successful_result: null,
        critical_actions: [],
      },
    };
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse(detailWithoutEvaluation);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/games/game_1234abcd");

    expect(
      await screen.findByRole("heading", { level: 1, name: "game_1234abcd" }),
    ).toBeInTheDocument();
    expect(screen.getByText("旧对局尚未生成 P3 质量评估。")).toBeInTheDocument();
    expect(screen.getByLabelText("赛后复盘任务状态")).toHaveTextContent(
      "来源修订暂无",
    );
    expect(
      screen.queryByRole("heading", { name: "无法读取对局详情" }),
    ).not.toBeInTheDocument();
  });

  it("opens model request input and output in an audited right drawer", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read", "games.debug.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse(contractGameDetail);
      }
      const modelResponse = modelRequestFixtureResponse(url);
      if (modelResponse) return modelResponse;
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/games/game_1234abcd");

    expect(await screen.findByText("2 次")).toBeInTheDocument();
    await user.click(screen.getByText("第 1 轮", { selector: "summary span" }));
    const requestButton = screen.getByRole("button", {
      name: "查看模型请求 req_contract_model_1",
    });
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith("/model-requests/req_contract_model_1"),
      ),
    ).toBe(false);

    await user.click(requestButton);
    const drawer = await screen.findByRole("dialog", {
      name: "暮鸦归票 · 白天发言",
    });
    expect(within(drawer).getByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(
      within(drawer).getByText("你正在进行一局狼人杀。请发表白天发言。"),
    ).toBeInTheDocument();
    expect(
      within(drawer).getByText(
        '{"reasoning":"分析票型","say":"我会投给灰塔。"}',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "关闭模型请求详情" }),
    ).toHaveFocus();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/model-requests/req_contract_model_1"),
      ),
    ).toHaveLength(1);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: /暮鸦归票/ })).toBeNull();
    expect(requestButton).toHaveFocus();
  });

  it("renders unavailable P2 quality and outcome empty states", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse({
          ...contractGameDetail,
          p2_quality: {
            ...contractGameDetail.p2_quality,
            data_status: "unavailable",
            public_outcomes: [],
            quality_gates: contractGameDetail.p2_quality.quality_gates.map(
              (gate) => ({
                ...gate,
                status: "unavailable",
                code: `${gate.gate}_data_unavailable`,
                actual: null,
              }),
            ),
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/games/game_1234abcd");

    expect(
      await screen.findByText("该对局没有可用的 P2 质量数据。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("旧对局没有结构化公开结算链。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/lineup · 通过/)).not.toBeInTheDocument();
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
      const modelResponse = modelRequestFixtureResponse(url);
      if (modelResponse) return modelResponse;
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

  it("loads only safe P3 issue coordinates after an explicit authorized click", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read", "games.debug.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse(contractGameDetail);
      }
      if (url.endsWith("/quality-evaluation/issues")) {
        return jsonResponse({
          session_id: "game_1234abcd",
          evaluation_id: "quality_fixture_1",
          items: [
            {
              issue_id: "quality_issue_fixture_1",
              code: "private_voice_materialized",
              severity: "P0",
              channel: "voice",
              round_number: 1,
              event_id: 5,
              utterance_id: "utterance_fixture_1",
              first_detected_at: "2026-07-10T01:04:00Z",
            },
          ],
        });
      }
      const modelResponse = modelRequestFixtureResponse(url);
      if (modelResponse) return modelResponse;
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/games/game_1234abcd");

    expect(
      await screen.findByRole("heading", { name: "P3 质量评估" }),
    ).toBeInTheDocument();
    expect(screen.getByText("对局完成")).toBeInTheDocument();
    expect(screen.getByText(/第 1 轮 · 总结/)).toBeInTheDocument();
    expect(screen.queryByText("game_completed")).not.toBeInTheDocument();
    expect(screen.getByText("100.0% (4/4)")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith("/quality-evaluation/issues"),
      ),
    ).toBe(false);

    await user.click(
      screen.getByRole("button", { name: "加载安全问题坐标" }),
    );
    expect(
      await screen.findByText("P0 严重 · 私密内容被合成为语音"),
    ).toBeInTheDocument();
    expect(screen.getByText(/语音 · 轮次 1 · 事件 5/)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/quality-evaluation/issues"),
      ),
    ).toHaveLength(1);
    expect(document.body.textContent).not.toContain("private wolf plan");
  });

  it("retries eligible P3 evaluation with the admin CSRF token", async () => {
    let detailCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read", "games.debug.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        detailCalls += 1;
        return jsonResponse({
          ...contractGameDetail,
          quality_evaluation: {
            ...contractGameDetail.quality_evaluation,
            data_status: "partial",
            can_retry: true,
          },
        });
      }
      if (url.endsWith("/quality-evaluation/retry")) {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe(
          "csrf-games",
        );
        return jsonResponse({
          session_id: "game_1234abcd",
          evaluation_id: "quality_fixture_retry",
          status: "pending",
        });
      }
      const modelResponse = modelRequestFixtureResponse(url);
      if (modelResponse) return modelResponse;
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute("/operations/games/game_1234abcd");

    await user.click(
      await screen.findByRole("button", { name: "重试质量评估" }),
    );
    await waitFor(() => expect(detailCalls).toBeGreaterThan(1));
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/quality-evaluation/retry"),
      ),
    ).toHaveLength(1);
  });

  it("honors server retry eligibility instead of legacy status heuristics", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse(session(["games.read", "games.debug.read"]));
      }
      if (url.endsWith("/api/v1/admin/games/game_1234abcd")) {
        return jsonResponse({
          ...contractGameDetail,
          quality_evaluation: {
            ...contractGameDetail.quality_evaluation,
            evaluation_status: "failed",
            data_status: "partial",
            failure_reason: "worker_unavailable",
            can_retry: false,
          },
        });
      }
      const modelResponse = modelRequestFixtureResponse(url);
      if (modelResponse) return modelResponse;
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/operations/games/game_1234abcd");

    expect(
      await screen.findByText("worker_unavailable"),
    ).toBeInTheDocument();
    expect(screen.getByText("不可重试")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "关键决策" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "重试质量评估" }),
    ).not.toBeInTheDocument();
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
      const modelResponse = modelRequestFixtureResponse(url);
      if (modelResponse) return modelResponse;
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
