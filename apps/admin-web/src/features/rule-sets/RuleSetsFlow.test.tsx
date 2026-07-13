import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "@/routes";
import { resetPreviewRuleSets } from "./preview-repository";
import { fixtureRuleSet, ruleSetOptions, standardConfig } from "./test-fixtures";

function renderRoute(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
  return { queryClient, router };
}

describe("admin rule set list flow", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "true");
    resetPreviewRuleSets();
  });
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

  it("renders the total and rule summaries", async () => {
    renderRoute("/content/rules");
    expect(await screen.findByRole("heading", { name: "规则内容库" })).toBeInTheDocument();
    expect(await screen.findByText("共 4 套规则")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "游戏规则列表" })).toBeInTheDocument();
    expect(screen.getByText("默认规则")).toBeInTheDocument();
    expect(screen.getAllByText("已发布").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/版本 1/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("9 人").length).toBeGreaterThan(0);
    expect(screen.getAllByText("3 狼人 / 6 好人").length).toBeGreaterThan(0);
  });

  it("keeps search, filters, sort, page size, clear, and pagination in the URL", async () => {
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules?page_size=10");
    await screen.findByText("classic_9 规则");
    await user.type(screen.getByLabelText("搜索规则"), "classic");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await user.selectOptions(screen.getByLabelText("生命周期"), "published");
    await user.selectOptions(screen.getByLabelText("玩家人数"), "9");
    await user.selectOptions(screen.getByLabelText("排序"), "updated_at:desc");
    await user.selectOptions(screen.getByLabelText("每页"), "20");
    await waitFor(() => expect(router.state.location.search).toContain("q=classic"));
    for (const part of ["status=published", "player_count=9", "sort=updated_at", "direction=desc", "page_size=20"]) expect(router.state.location.search).toContain(part);
    await user.click(screen.getByRole("button", { name: "清除筛选" }));
    await waitFor(() => expect(router.state.location.search).not.toContain("q="));
    expect(screen.getByText("第 1 / 1 页")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("shows loading, empty, and a retryable repository error", async () => {
    useServerSession(["rules.read"]);
    let resolveList: ((value: Response) => void) | undefined; let calls = 0;
    const pending = new Promise<Response>((resolve) => { resolveList = resolve; });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const url = String(input); const common = serverCommon(url); if (common) return common;
      if (url.includes("/api/v1/admin/rule-sets?")) { calls += 1; return calls === 1 ? pending : json({ items: [], pagination: { page: 1, page_size: 20, total: 0, pages: 0 } }); }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); renderRoute("/content/rules");
    expect(await screen.findByText("正在读取游戏规则...")).toBeInTheDocument();
    act(() => resolveList?.(json({ title: "Unavailable", status: 503, detail: "规则服务暂时不可用", code: "rules_unavailable", request_id: "req-rules" }, 503)));
    expect(await screen.findByRole("heading", { name: "无法读取游戏规则" })).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-rules")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByRole("heading", { name: "还没有游戏规则" })).toBeInTheDocument();
  });

  it("hides create and duplicate actions from a read-only user", async () => {
    useServerSession(["rules.read"]);
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const url = String(input); const common = serverCommon(url); if (common) return common;
      if (url.includes("/api/v1/admin/rule-sets?")) { const page = Number(new URL(url, "https://admin.test").searchParams.get("page")); return json({ items: [fixtureRuleSet(`server_rule_${page}`, "published")], pagination: { page, page_size: 20, total: 21, pages: 2 } }); }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules");
    expect(await screen.findByText("server_rule_1 规则")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "新建规则草稿" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /复制/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(router.state.location.search).toContain("page=2"));
    expect(await screen.findByText("server_rule_2 规则")).toBeInTheDocument();
  });

  it("lets writers open new and duplicate flows with validation and source lock version", async () => {
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules");
    expect(await screen.findByRole("link", { name: "新建规则草稿" })).toHaveAttribute("href", "/content/rules/new");
    await user.click(await screen.findByRole("button", { name: "复制 classic_9 规则" }));
    await user.click(screen.getByRole("button", { name: "确认复制" }));
    expect(screen.getByText("请输入有效的新规则 ID")).toBeInTheDocument();
    expect(screen.getByText("请输入新规则名称")).toBeInTheDocument();
    await user.type(screen.getByLabelText("新规则 ID"), "copy_classic_9");
    await user.type(screen.getByLabelText("新规则名称"), "九人局副本");
    await user.click(screen.getByRole("button", { name: "确认复制" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/content/rules/copy_classic_9"));
    expect(await screen.findByRole("heading", { name: "游戏规则详情" })).toBeInTheDocument();
  });

  it("uses fetched player and ID constraints and sends the source lock version", async () => {
    useServerSession(["rules.read", "rules.write"]);
    const constrainedOptions = { ...ruleSetOptions, constraints: { ...ruleSetOptions.constraints, player_count_min: 8, player_count_max: 10, id_pattern: "^x_[a-z]{3}$" } };
    let duplicateBody: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) return serverSession();
      if (url.endsWith("/api/v1/admin/rule-set-options")) return json(constrainedOptions);
      if (url.includes("/api/v1/admin/rule-sets?") && !init?.method) return json({ items: [fixtureRuleSet("source_rule", "published")], pagination: { page: 1, page_size: 20, total: 1, pages: 1 } });
      if (url.endsWith("/api/v1/admin/rule-sets/source_rule/duplicate")) { duplicateBody = JSON.parse(String(init?.body)); return json(fixtureRuleSet("x_abc", "draft")); }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules");
    const playerCount = await screen.findByLabelText("玩家人数"); await waitFor(() => expect(playerCount).toHaveTextContent("8 人"));
    expect(playerCount).toHaveTextContent("8 人"); expect(playerCount).toHaveTextContent("10 人"); expect(playerCount).not.toHaveTextContent("6 人"); expect(playerCount).not.toHaveTextContent("12 人");
    await user.click(await screen.findByRole("button", { name: "复制 source_rule 规则" }));
    await user.type(screen.getByLabelText("新规则 ID"), "copy_rule");
    await user.type(screen.getByLabelText("新规则名称"), "动态约束副本");
    await user.click(screen.getByRole("button", { name: "确认复制" }));
    expect(screen.getByLabelText("新规则 ID")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("请输入有效的新规则 ID")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("新规则 ID")); await user.type(screen.getByLabelText("新规则 ID"), "x_abc");
    await user.click(screen.getByRole("button", { name: "确认复制" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/content/rules/x_abc"));
    expect(duplicateBody).toEqual({ expected_source_lock_version: 1, new_rule_set_id: "x_abc", new_name: "动态约束副本" });
  });

  it("does not guess constraints while options are unavailable", async () => {
    useServerSession(["rules.read", "rules.write"]);
    const never = new Promise<Response>(() => undefined);
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) return serverSession();
      if (url.endsWith("/api/v1/admin/rule-set-options")) return never;
      if (url.includes("/api/v1/admin/rule-sets?")) return json({ items: [fixtureRuleSet("source_rule", "published")], pagination: { page: 1, page_size: 20, total: 1, pages: 1 } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); renderRoute("/content/rules");
    expect(await screen.findByLabelText("玩家人数")).toBeDisabled();
    await user.click(await screen.findByRole("button", { name: "复制 source_rule 规则" }));
    expect(screen.getByRole("button", { name: "确认复制" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("正在读取规则约束");
  });

  it("keeps constraint-dependent actions disabled when options fail", async () => {
    useServerSession(["rules.read", "rules.write"]);
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) return serverSession();
      if (url.endsWith("/api/v1/admin/rule-set-options")) return json({ title: "Unavailable", status: 503, detail: "选项不可用", code: "options_unavailable", request_id: "req-options" }, 503);
      if (url.includes("/api/v1/admin/rule-sets?")) return json({ items: [fixtureRuleSet("source_rule", "published")], pagination: { page: 1, page_size: 20, total: 1, pages: 1 } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); renderRoute("/content/rules");
    expect(await screen.findByText("筛选选项暂时不可用，规则列表仍可浏览。")).toBeInTheDocument();
    expect(screen.getByLabelText("玩家人数")).toBeDisabled();
    await user.click(await screen.findByRole("button", { name: "复制 source_rule 规则" }));
    expect(screen.getByRole("button", { name: "确认复制" })).toBeDisabled();
    expect(screen.getByText("规则约束暂时不可用，无法复制。")).toBeInTheDocument();
  });

  it("manages duplicate dialog focus, keyboard containment, escape, and error associations", async () => {
    const user = userEvent.setup(); renderRoute("/content/rules");
    const opener = await screen.findByRole("button", { name: "复制 classic_9 规则" });
    await user.click(opener);
    const id = screen.getByLabelText("新规则 ID"); const name = screen.getByLabelText("新规则名称");
    expect(id).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "确认复制" }));
    expect(id).toHaveAttribute("aria-invalid", "true"); expect(name).toHaveAttribute("aria-invalid", "true");
    expect(id).toHaveAccessibleDescription("请输入有效的新规则 ID"); expect(name).toHaveAccessibleDescription("请输入新规则名称");
    screen.getByRole("button", { name: "确认复制" }).focus(); await user.tab(); expect(id).toHaveFocus();
    await user.tab({ shift: true }); expect(screen.getByRole("button", { name: "确认复制" })).toHaveFocus();
    await user.keyboard("{Escape}"); expect(screen.queryByRole("dialog", { name: "复制游戏规则" })).not.toBeInTheDocument(); expect(opener).toHaveFocus();
  });
});

describe("rule editor", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "true");
    resetPreviewRuleSets();
  });
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

  it("renders every structured field in server role order and updates its summary", async () => {
    const user = userEvent.setup();
    renderRoute("/content/rules/new");
    expect(await screen.findByRole("heading", { name: "新建游戏规则" })).toBeInTheDocument();
    for (const name of ["规则 ID", "显示顺序", "规则名称", "规则说明", "复杂度", "预计时长", "规则标签", "胜利条件", "启用警长", "警长票权", "发言规则", "允许狼人自爆", "警徽规则"]) expect(screen.getByLabelText(name)).toBeInTheDocument();
    const roleInputs = screen.getAllByTestId("role-count");
    expect(roleInputs.map((node) => node.getAttribute("aria-label"))).toEqual(ruleSetOptions.roles.map((role) => `${role.label}数量`));
    await user.clear(screen.getByLabelText("村民数量")); await user.type(screen.getByLabelText("村民数量"), "5");
    expect(screen.getByText("总人数：6 人")).toBeInTheDocument();
    expect(screen.getByText("1 狼人 / 5 村民")).toBeInTheDocument();
    await user.click(screen.getByLabelText("启用警长"));
    expect(screen.getByLabelText("警长票权")).toBeDisabled();
    expect(screen.getByLabelText("警徽规则")).toBeDisabled();
  });

  it("makes the persisted ID read-only and shows status usage warnings and bounded history", async () => {
    renderRoute("/content/rules/classic_9");
    expect(await screen.findByRole("heading", { name: "游戏规则详情" })).toBeInTheDocument();
    expect(screen.getByLabelText("规则 ID")).toHaveAttribute("readonly");
    expect(screen.getByText("已发布")).toBeInTheDocument();
    expect(screen.getByText("累计使用：42 场游戏 / 2 场直播")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "版本历史" }).children.length).toBeLessThanOrEqual(50);
    expect(screen.queryByText(/classic_9-r1/)).not.toBeInTheDocument();
  });

  it("lets read-only users inspect but not edit", async () => {
    useServerSession(["rules.read"]);
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const url = String(input); const common = serverCommon(url); if (common) return common;
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9")) return json({ ...fixtureRuleSet("classic_9", "published"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] });
      throw new Error(`Unexpected request: ${url}`);
    }));
    renderRoute("/content/rules/classic_9");
    expect(await screen.findByLabelText("规则名称")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "保存草稿" })).not.toBeInTheDocument();
  });

  it("save rule draft blocks invalid input and creates a valid rule", async () => {
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules/new");
    await screen.findByLabelText("规则 ID");
    await user.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(screen.getByText("规则 ID 格式不正确")).toBeInTheDocument();
    await user.type(screen.getByLabelText("规则 ID"), "new_rule");
    await user.type(screen.getByLabelText("规则名称"), "新规则"); await user.type(screen.getByLabelText("复杂度"), "简单"); await user.type(screen.getByLabelText("预计时长"), "30 分钟");
    await user.clear(screen.getByLabelText("村民数量")); await user.type(screen.getByLabelText("村民数量"), "5");
    await user.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/content/rules/new_rule"));
  });

  it("sends the exact cleaned create body, using server sheriff-off defaults", async () => {
    useServerSession(["rules.read", "rules.write"]);
    const options = { ...ruleSetOptions, sheriff_vote_weights: [1.5, 2], sheriff_badge_bomb_policies: [{ value: "double" as const, label: "双爆吞警徽" }] };
    let createBody: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) return serverSession();
      if (url.endsWith("/api/v1/admin/rule-set-options")) return json(options);
      if (url.endsWith("/api/v1/admin/rule-sets") && init?.method === "POST") { createBody = JSON.parse(String(init.body)); return json(fixtureRuleSet("new_clean", "draft")); }
      if (url.endsWith("/api/v1/admin/rule-sets/new_clean") && !init?.method) return json({ ...fixtureRuleSet("new_clean", "draft"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); renderRoute("/content/rules/new");
    await user.type(await screen.findByLabelText("规则 ID"), "  new_clean  ");
    await user.type(screen.getByLabelText("规则名称"), "  清理后的规则  ");
    await user.type(screen.getByLabelText("规则说明"), "  说明  ");
    await user.type(screen.getByLabelText("复杂度"), "  简单  ");
    await user.type(screen.getByLabelText("预计时长"), "  30 分钟  ");
    await user.type(screen.getByLabelText("规则标签"), " 标签一，标签二，标签一 ");
    await user.clear(screen.getByLabelText("显示顺序")); await user.type(screen.getByLabelText("显示顺序"), "4");
    await user.clear(screen.getByLabelText("村民数量")); await user.type(screen.getByLabelText("村民数量"), "5");
    await user.click(screen.getByLabelText("启用警长"));
    await user.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(createBody).toBeDefined());
    expect(createBody).toEqual({ id: "new_clean", display_order: 4, config: { name: "清理后的规则", description: "说明", complexity: "简单", estimated_duration: "30 分钟", rule_tags: ["标签一", "标签二"], role_counts: { werewolf: 1, villager: 5, seer: 0, guard: 0, witch: 0, hunter: 0, idiot: 0 }, win_condition: "wolves_gte_others", sheriff_enabled: false, sheriff_vote_weight: 1.5, speech_policy: "sequential", werewolf_self_explosion_enabled: true, sheriff_badge_bomb_policy: "double" } });
  });

  it.each([
    ["current draft", fixtureRuleSet("classic_9", "draft"), 7],
    ["no draft", fixtureRuleSet("classic_9", "published"), null],
  ])("sends exact update locks for %s", async (_label, baseRule, expectedRevisionLock) => {
    useServerSession(["rules.read", "rules.write"]); let updateBody: unknown; let gets = 0;
    const base = { ...baseRule, lock_version: 8, draft_revision: baseRule.draft_revision ? { ...baseRule.draft_revision, lock_version: 7 } : null, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input); const common = serverCommon(url); if (common) return common;
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) { gets += 1; return json(base); }
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9/draft") && init?.method === "PATCH") { updateBody = JSON.parse(String(init.body)); return json(fixtureRuleSet("classic_9", "draft")); }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9");
    await user.clear(await screen.findByLabelText("规则名称")); await user.type(screen.getByLabelText("规则名称"), "更新名称");
    await user.click(screen.getByRole("button", { name: "保存草稿" })); await waitFor(() => expect(gets).toBeGreaterThanOrEqual(2));
    expect(updateBody).toEqual({ expected_rule_set_lock_version: 8, expected_revision_lock_version: expectedRevisionLock, display_order: 1, config: { ...standardConfig, name: "更新名称" } });
  });

  it("resets the dirty baseline after save and invalidates list and detail queries", async () => {
    useServerSession(["rules.read", "rules.write"]); const baseRule = fixtureRuleSet("classic_9", "draft"); const base = { ...baseRule, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) return json(base); if (url.endsWith("/api/v1/admin/rule-sets/classic_9/draft")) return json(baseRule); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); const { router, queryClient } = renderRoute("/content/rules/classic_9"); const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    await user.type(await screen.findByLabelText("规则名称"), " saved"); await user.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["rule-sets", "list"] })); expect(invalidate).toHaveBeenCalledWith({ queryKey: ["rule-sets", "detail", "classic_9"] });
    await act(async () => { await router.navigate("/content/rules"); });
    expect(screen.queryByRole("dialog", { name: "未保存规则" })).not.toBeInTheDocument();
  });

  it("unsaved rule changes block route navigation", async () => {
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules/classic_9");
    const name = await screen.findByLabelText("规则名称"); await user.type(name, " 本地");
    await act(async () => { await router.navigate("/content/rules"); });
    expect(screen.getByRole("dialog", { name: "未保存规则" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(router.state.location.pathname).toBe("/content/rules/classic_9");
  });

  it("blocks dirty search/hash navigation, supports proceed, and registers beforeunload", async () => {
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules/classic_9");
    await user.type(await screen.findByLabelText("规则名称"), " dirty");
    const unload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unload); expect(unload.defaultPrevented).toBe(true);
    await act(async () => { await router.navigate("/content/rules/classic_9?tab=history#r1"); });
    expect(screen.getByRole("dialog", { name: "未保存规则" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "放弃修改并离开" }));
    await waitFor(() => expect(router.state.location.search).toBe("?tab=history")); expect(router.state.location.hash).toBe("#r1");
  });

  it("resets cached editor state when navigating from rule A to rule B", async () => {
    const user = userEvent.setup(); const { router, queryClient } = renderRoute("/content/rules/classic_9");
    await screen.findByDisplayValue("classic_9 规则");
    await queryClient.prefetchQuery({ queryKey: ["rule-sets", "detail", "classic_12"], queryFn: async () => ({ ...fixtureRuleSet("classic_12", "draft"), lock_version: 8, draft_revision: { ...fixtureRuleSet("classic_12", "draft").draft_revision!, lock_version: 7, config: { ...fixtureRuleSet("classic_12", "draft").draft_revision!.config!, name: "规则 B" } }, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }) });
    await act(async () => { await router.navigate("/content/rules/classic_12"); });
    expect(await screen.findByDisplayValue("规则 B")).toBeInTheDocument(); expect(screen.getByText(/规则锁版本 8/)).toBeInTheDocument(); expect(screen.queryByDisplayValue("classic_9 规则")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("规则名称"), " changed");
  });

  it("associates field and role-group errors with their controls", async () => {
    renderRoute("/content/rules/new"); await screen.findByLabelText("规则 ID");
    fireEvent.change(screen.getByLabelText("狼人数量"), { target: { value: "0" } }); fireEvent.submit(screen.getByRole("button", { name: "保存草稿" }).closest("form")!);
    await waitFor(() => expect(screen.getByLabelText("规则 ID")).toHaveAttribute("aria-invalid", "true")); expect(screen.getByLabelText("规则 ID")).toHaveAccessibleDescription("规则 ID 格式不正确");
    expect(screen.getByRole("group", { name: "角色数量" })).toHaveAttribute("aria-invalid", "true"); expect(screen.getByLabelText("狼人数量")).toHaveAccessibleDescription(/角色数量/);
  });

  it("rule conflict keeps the local draft and offers explicit reload", async () => {
    useServerSession(["rules.read", "rules.write"]); const base = { ...fixtureRuleSet("classic_9", "draft"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input); const common = serverCommon(url); if (common) return common;
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) return json(base);
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9/draft")) return json({ title: "Conflict", status: 409, detail: "草稿已更新", code: "rule_set_version_conflict", request_id: "req-conflict" }, 409);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); const name = await screen.findByLabelText("规则名称");
    await user.clear(name); await user.type(name, "保留的本地草稿"); await user.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByRole("heading", { name: "规则版本冲突" })).toBeInTheDocument();
    expect(name).toHaveValue("保留的本地草稿"); expect(screen.getByRole("button", { name: "重新加载服务器版本" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新加载服务器版本" })); await waitFor(() => expect(screen.queryByRole("heading", { name: "规则版本冲突" })).not.toBeInTheDocument()); expect(name).toHaveValue("classic_9 草稿");
  });

  it("shows a bounded error when conflict reload fails and prevents duplicate reloads", async () => {
    useServerSession(["rules.read", "rules.write"]); const base = { ...fixtureRuleSet("classic_9", "draft"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; let gets = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) { gets += 1; return gets === 1 ? json(base) : json({ title: "Unavailable", status: 503, detail: "重载失败", code: "unavailable", request_id: "reload-1" }, 503); } if (url.endsWith("/api/v1/admin/rule-sets/classic_9/draft")) return json({ title: "Conflict", status: 412, detail: "版本变化", code: "rule_set_version_conflict", request_id: null }, 412); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); await user.type(await screen.findByLabelText("规则名称"), " local"); await user.click(screen.getByRole("button", { name: "保存草稿" }));
    const reload = await screen.findByRole("button", { name: "重新加载服务器版本" }); await user.click(reload); expect(await screen.findByText("重载失败")).toBeInTheDocument(); expect(gets).toBe(2); expect(screen.getByLabelText("规则名称")).toHaveValue("classic_9 草稿 local");
  });

  it("validation gates publish on the saved revision and omits compiled snapshot", async () => {
    useServerSession(["rules.read", "rules.write"]); const base = { ...fixtureRuleSet("classic_9", "draft"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; let validateBody: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input); const common = serverCommon(url); if (common) return common;
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) return json(base);
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9/validate")) { validateBody = JSON.parse(String(init?.body)); return json({ valid: true, errors: [], warnings: [{ code: "wording", path: "config.description", message: "建议补充说明" }], compiled_snapshot: { secret: "opaque" }, content_hash: "abcdef1234567890", rule_text_preview: "规则预览正文" }); }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9");
    const validate = await screen.findByRole("button", { name: "校验规则" }); expect(validate).toBeEnabled(); expect(screen.getByRole("button", { name: "发布规则" })).toBeDisabled();
    await user.click(validate); expect(await screen.findByRole("heading", { name: "校验通过" })).toBeInTheDocument();
    expect(validateBody).toEqual({ expected_revision_lock_version: 1 });
    expect(screen.getByRole("list", { name: "校验警告" })).toHaveTextContent("建议补充说明");
    expect(screen.getByText("内容哈希：abcdef123456")).toBeInTheDocument(); expect(screen.getByText("规则预览正文")).toBeInTheDocument(); expect(screen.queryByText(/opaque|secret/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发布规则" })).toBeEnabled();
    await user.type(screen.getByLabelText("规则名称"), " 修改"); expect(screen.getByRole("button", { name: "发布规则" })).toBeDisabled();
  });

  it.each([
    ["name", "text", "规则名称", "变更名称"], ["description", "text", "规则说明", "变更说明"], ["complexity", "text", "复杂度", "困难"], ["duration", "text", "预计时长", "60 分钟"],
    ["tags", "text", "规则标签", "新标签"], ["order", "text", "显示顺序", "9"],
    ["werewolf count", "text", "狼人数量", "2"], ["villager count", "text", "村民数量", "4"], ["seer count", "text", "预言家数量", "0"], ["guard count", "text", "守卫数量", "1"], ["witch count", "text", "女巫数量", "0"], ["hunter count", "text", "猎人数量", "0"], ["idiot count", "text", "白痴数量", "1"],
    ["win condition", "select", "胜利条件", "slaughter_side"], ["sheriff enabled", "check", "启用警长", ""], ["sheriff weight", "select", "警长票权", "2"], ["speech", "select", "发言规则", "sequential"], ["self explosion", "check", "允许狼人自爆", ""], ["badge policy", "select", "警徽规则", "none"],
  ])("makes validation stale after editing %s and requires save plus revalidation", async (_name, kind, label, value) => {
    const user = userEvent.setup(); renderRoute("/content/rules/preview_draft");
    await user.click(await screen.findByRole("button", { name: "校验规则" })); expect(await screen.findByRole("button", { name: "发布规则" })).toBeEnabled();
    const control = screen.getByLabelText(label);
    if (kind === "check") await user.click(control);
    else if (kind === "select") await user.selectOptions(control, value);
    else { await user.clear(control); await user.type(control, value); }
    expect(screen.getByRole("button", { name: "发布规则" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "校验规则" })).toBeEnabled()); expect(screen.getByRole("button", { name: "发布规则" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "校验规则" })); await waitFor(() => expect(screen.getByRole("button", { name: "发布规则" })).toBeEnabled());
  });

  it("renders invalid server validation with associated path error and summary, without opaque snapshot", async () => {
    useServerSession(["rules.read", "rules.write"]); const rule = fixtureRuleSet("classic_9", "draft"); const base = { ...rule, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) return json(base); if (url.endsWith("/api/v1/admin/rule-sets/classic_9/validate")) return json({ valid: false, errors: [{ code: "name_invalid", path: "config.name", message: "规则名称被服务器拒绝" }], warnings: [], compiled_snapshot: { opaque_secret: "must-not-render" }, content_hash: null, rule_text_preview: null }); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); await user.click(await screen.findByRole("button", { name: "校验规则" }));
    expect(await screen.findByRole("heading", { name: "校验失败" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "校验错误" })).toHaveTextContent("config.name：规则名称被服务器拒绝");
    expect(screen.getByLabelText("规则名称")).toHaveAttribute("aria-invalid", "true"); expect(screen.getByLabelText("规则名称")).toHaveAccessibleDescription("规则名称被服务器拒绝");
    expect(screen.getAllByRole("alert").some((node) => node.textContent?.includes("规则名称被服务器拒绝"))).toBe(true);
    expect(screen.queryByText(/opaque_secret|must-not-render/)).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "发布规则" })).toBeDisabled();
  });

  it("shows a dedicated editor 404 without leaking server detail", async () => {
    useServerSession(["rules.read", "rules.write"]); vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/missing")) return json({ title: "Not found", status: 404, detail: "internal missing row detail", code: "not_found", request_id: "secret-request" }, 404); throw new Error(`Unexpected request: ${url}`); }));
    renderRoute("/content/rules/missing"); expect(await screen.findByRole("heading", { name: "没有找到该游戏规则" })).toBeInTheDocument(); expect(screen.getByText("规则可能已被删除或 ID 不正确。")).toBeInTheDocument(); expect(screen.queryByText(/internal missing|secret-request/)).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "重新加载" })).not.toBeInTheDocument();
  });

  it("shows a bounded retryable editor 503 and recovers", async () => {
    useServerSession(["rules.read", "rules.write"]); const rule = fixtureRuleSet("classic_9", "draft"); const base = { ...rule, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; let gets = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9")) { gets += 1; return gets === 1 ? json({ title: "Unavailable", status: 503, detail: "规则服务暂时不可用", code: "rules_unavailable", request_id: "req-editor-503", internal_debug: "do not show" }, 503) : json(base); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); expect(await screen.findByRole("heading", { name: "无法读取游戏规则" })).toBeInTheDocument(); expect(screen.getByText("规则服务暂时不可用")).toBeInTheDocument(); expect(screen.queryByText(/internal_debug|do not show/)).not.toBeInTheDocument(); await user.click(screen.getByRole("button", { name: "重新加载" })); expect(await screen.findByDisplayValue("classic_9 草稿")).toBeInTheDocument(); expect(gets).toBe(2);
  });
});

function useServerSession(permissions: string[]) { vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true"); vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false"); sessionPermissions = permissions; }
let sessionPermissions: string[] = [];
function serverCommon(url: string) {
  if (url.endsWith("/api/v1/admin/me")) return serverSession();
  if (url.endsWith("/api/v1/admin/rule-set-options")) return json(ruleSetOptions);
}
function serverSession() { return json({ user: { id: "1", email: "r@test", display_name: "只读", role: "viewer" }, permissions: sessionPermissions, csrf_token: "csrf", session_expires_at: "2999-01-01T00:00:00Z" }); }
function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }
