import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "@/routes";
import {
  expectAntdSelectLabel,
  getOpenAntdOptions,
  selectAntdOption,
} from "@/tests/antd-select";
import { expectAdminNotification } from "@/tests/admin-notification";
import { resetPreviewRuleSets } from "./preview-repository";
import { fixtureRuleSet, ruleContract, ruleSetOptions, standardConfig } from "./test-fixtures";

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
    expect(screen.getAllByText(/草稿修订/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/发布修订/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/展示顺序/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/更新时间/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("9 人").length).toBeGreaterThan(0);
    expect(screen.getAllByText("3 狼人 / 6 好人").length).toBeGreaterThan(0);
  });

  it("keeps search, filters, sort, page size, clear, and pagination in the URL", async () => {
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules?page_size=10");
    await screen.findByText("classic_9 规则");
    await user.type(screen.getByLabelText("搜索规则"), "classic");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await selectAntdOption(user, screen.getByLabelText("生命周期"), "已发布");
    await selectAntdOption(user, screen.getByLabelText("玩家人数"), "9 人");
    await selectAntdOption(user, screen.getByLabelText("排序"), "-updated_at");
    await selectAntdOption(user, screen.getByLabelText("每页"), "20 条");
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
    expect(screen.getByText("规则目录暂时不可用，请稍后重试。")).toBeInTheDocument();
    expect(screen.queryByText("规则服务暂时不可用")).not.toBeInTheDocument();
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
    const constrainedOptions = { ...ruleSetOptions, roles: ruleSetOptions.roles.map((role) => role.id === "villager" ? { ...role, max_count: 10 } : role) as typeof ruleSetOptions.roles, constraints: { ...ruleSetOptions.constraints, player_count_min: 8, player_count_max: 10, id_pattern: "^x_[a-z]{3}$" } };
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
    const playerCount = await screen.findByLabelText("玩家人数"); await user.click(playerCount); const playerCountOptions = getOpenAntdOptions().map((option) => option.textContent ?? "");
    expect(playerCountOptions).toContain("8 人"); expect(playerCountOptions).toContain("10 人"); expect(playerCountOptions).not.toContain("6 人"); expect(playerCountOptions).not.toContain("12 人"); await user.keyboard("{Escape}");
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

  it("uses only custom advertised lifecycle and signed sort choices", async () => {
    useServerSession(["rules.read"]); const customOptions = { ...ruleSetOptions, statuses: [{ value: "archived" as const, label: "仅归档" }], sorts: [{ value: "-name" as const, label: "名称倒序" }] }; let listUrl = "";
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => { const url = String(input); if (url.endsWith("/api/v1/admin/me")) return serverSession(); if (url.endsWith("/api/v1/admin/rule-set-options")) return json(customOptions); if (url.includes("/api/v1/admin/rule-sets?")) { listUrl = url; return json({ items: [], pagination: { page: 1, page_size: 20, total: 0, pages: 0 } }); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules?status=published&sort=updated_at&direction=asc"); await screen.findByRole("heading", { name: "还没有游戏规则" }); const status = screen.getByLabelText("生命周期"); const sort = screen.getByLabelText("排序"); await user.click(status); expect(getOpenAntdOptions().some((option) => option.textContent?.includes("仅归档"))).toBe(true); expect(getOpenAntdOptions().some((option) => option.textContent?.includes("草稿"))).toBe(false); await user.keyboard("{Escape}"); expectAntdSelectLabel(sort, "名称倒序"); expect(listUrl).toContain("sort=-name"); expect(listUrl).not.toContain("status=published");
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
    renderRoute("/content/rules");
    expect(await screen.findByText("正在读取游戏规则...")).toBeInTheDocument();
    expect(screen.queryByLabelText("玩家人数")).not.toBeInTheDocument();
    expect(screen.queryByText("source_rule 规则")).not.toBeInTheDocument();
  });

  it("keeps constraint-dependent actions disabled when options fail", async () => {
    useServerSession(["rules.read", "rules.write"]);
    let listCalls = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) return serverSession();
      if (url.endsWith("/api/v1/admin/rule-set-options")) return json({ title: "Unavailable", status: 503, detail: "选项不可用", code: "options_unavailable", request_id: "req-options" }, 503);
      if (url.includes("/api/v1/admin/rule-sets?")) { listCalls += 1; return json({ items: [fixtureRuleSet("source_rule", "published")], pagination: { page: 1, page_size: 20, total: 1, pages: 1 } }); }
      throw new Error(`Unexpected request: ${url}`);
    }));
    renderRoute("/content/rules");
    expect(await screen.findByRole("heading", { name: "规则选项暂时不可用" })).toBeInTheDocument();
    expect(screen.getByText("无法安全读取筛选与操作约束，暂不加载规则列表。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载规则选项" })).toBeInTheDocument();
    expect(screen.queryByText("source_rule 规则")).not.toBeInTheDocument();
    expect(listCalls).toBe(0);
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
    for (const name of ["规则 ID", "显示顺序", "规则名称", "规则说明", "复杂度", "预计时长", "规则标签", "胜利条件", "启用警长", "警长票权", "发言规则", "狼人刀口规则", "允许狼人主动空刀", "允许狼人选择狼队目标（含自刀）", "允许狼人自爆", "警徽规则"]) expect(screen.getByLabelText(name)).toBeInTheDocument();
    const roleInputs = screen.getAllByTestId("role-count");
    expect(roleInputs.map((node) => node.getAttribute("aria-label"))).toEqual(ruleSetOptions.roles.map((role) => `${role.label}数量`));
    await user.clear(screen.getByLabelText("村民数量")); await user.type(screen.getByLabelText("村民数量"), "5");
    expect(screen.getByText("总人数：6 人")).toBeInTheDocument();
    expect(screen.getByText("1 狼人 / 5 村民")).toBeInTheDocument();
    await user.click(screen.getByLabelText("启用警长"));
    expect(screen.getByLabelText("警长票权")).toBeDisabled();
    expect(screen.getByLabelText("警徽规则")).toBeDisabled();
    const editor = screen.getByRole("group", { name: "结构化规则配置" }).closest("form")!;
    for (const control of editor.querySelectorAll("button, input, select, textarea")) {
      expect(control).toHaveAccessibleName();
    }
  });

  it("makes the persisted ID read-only and shows status usage warnings and bounded history", async () => {
    renderRoute("/content/rules/classic_9");
    expect(await screen.findByRole("heading", { name: "游戏规则详情" })).toBeInTheDocument();
    expect(screen.getByLabelText("规则 ID")).toHaveAttribute("readonly");
    expect(screen.getByText("已发布")).toBeInTheDocument();
    expect(screen.getByText("累计使用：42 场游戏 / 2 场直播")).toBeInTheDocument();
    expect(screen.getByText(/当前草稿修订：无/)).toBeInTheDocument();
    expect(screen.getByText(/当前发布修订：1/)).toBeInTheDocument();
    expect(screen.getByText(/发布人：preview-super-admin/)).toBeInTheDocument();
    expect(screen.getByText(/发布时间：2026-07-01/)).toBeInTheDocument();
    expect(screen.getAllByText(/哈希前缀：111111111111/).length).toBeGreaterThan(0);
    expect(screen.getByRole("list", { name: "版本历史" }).children.length).toBeLessThanOrEqual(50);
    expect(screen.queryByText(/classic_9-r1/)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "规则契约与引擎覆盖" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "规则条款与引擎约束覆盖" })).toBeInTheDocument();
    expect(screen.getByText("night.werewolf_attack.non_wolf_targets.v1")).toBeInTheDocument();
    expect(screen.getByText("不进入模型规则")).toBeInTheDocument();
    expect(screen.queryByText("internal prompt")).not.toBeInTheDocument();
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
    for (const action of ["发布规则", "设为默认", "归档规则", "恢复规则"]) expect(screen.queryByRole("button", { name: action })).not.toBeInTheDocument();
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
    await user.click(screen.getByLabelText("允许首夜遗言"));
    await user.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(createBody).toBeDefined());
    expect(createBody).toEqual({ id: "new_clean", display_order: 4, config: { name: "清理后的规则", description: "说明", complexity: "简单", estimated_duration: "30 分钟", rule_tags: ["标签一", "标签二"], role_counts: { werewolf: 1, villager: 5, seer: 0, guard: 0, witch: 0, hunter: 0, idiot: 0 }, win_condition: "wolves_gte_others", sheriff_enabled: false, sheriff_vote_weight: 1.5, speech_policy: "sequential", werewolf_self_explosion_enabled: true, first_night_last_words_enabled: true, sheriff_badge_bomb_policy: "double", werewolf_attack_policy: { resolution: "plurality_rotating_tiebreak", allow_no_attack: false, allow_wolf_target: false } } });
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
    const firstSaveAnnouncement = await expectAdminNotification("草稿已保存");
    await user.click(within(firstSaveAnnouncement).getByRole("button", { name: "Close" }));
    await user.type(screen.getByLabelText("规则名称"), " again"); await user.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await expectAdminNotification("草稿已保存")).not.toBe(firstSaveAnnouncement);
    await act(async () => { await router.navigate("/content/rules"); });
    expect(screen.queryByRole("dialog", { name: "未保存规则" })).not.toBeInTheDocument();
  });

  it("unsaved rule changes block route navigation", async () => {
    const user = userEvent.setup(); const { router } = renderRoute("/content/rules/classic_9");
    const name = await screen.findByLabelText("规则名称"); await user.type(name, " 本地"); name.focus();
    await act(async () => { await router.navigate("/content/rules"); });
    const dialog = screen.getByRole("dialog", { name: "未保存规则" });
    const continueEditing = screen.getByRole("button", { name: "继续编辑" });
    const discard = screen.getByRole("button", { name: "放弃修改并离开" });
    expect(dialog).toHaveAccessibleDescription(); expect(continueEditing).toHaveFocus();
    discard.focus(); await user.tab(); expect(continueEditing).toHaveFocus();
    await user.keyboard("{Escape}"); expect(dialog).not.toBeInTheDocument(); expect(name).toHaveFocus();
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
    const user = userEvent.setup();
    renderRoute("/content/rules/new"); await screen.findByLabelText("规则 ID");
    await user.clear(screen.getByLabelText("狼人数量")); await user.type(screen.getByLabelText("狼人数量"), "0"); fireEvent.submit(screen.getByRole("button", { name: "保存草稿" }).closest("form")!);
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
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) { gets += 1; return gets === 1 ? json(base) : json({ title: "driver failure", status: 500, detail: "SELECT raw_reload FROM players", code: "driver_raw", request_id: "reload-1" }, 500); } if (url.endsWith("/api/v1/admin/rule-sets/classic_9/draft")) return json({ title: "Conflict", status: 412, detail: "版本变化", code: "rule_set_version_conflict", request_id: null }, 412); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); await user.type(await screen.findByLabelText("规则名称"), " local"); await user.click(screen.getByRole("button", { name: "保存草稿" }));
    const reload = await screen.findByRole("button", { name: "重新加载服务器版本" }); await user.click(reload); expect(await screen.findByText("无法重新加载游戏规则，请稍后重试。")).toBeInTheDocument(); expect(screen.queryByText(/SELECT raw_reload|players|driver failure/)).not.toBeInTheDocument(); expect(gets).toBe(2); expect(screen.getByLabelText("规则名称")).toHaveValue("classic_9 草稿 local");
  });

  it("keeps validation error context after pending clears without exposing raw detail", async () => {
    useServerSession(["rules.read", "rules.write"]); const base = { ...fixtureRuleSet("classic_9", "draft"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) return json(base); if (url.endsWith("/api/v1/admin/rule-sets/classic_9/validate")) return json({ title: "driver failure", status: 500, detail: "SELECT raw_validate FROM players", code: "driver_raw", request_id: null }, 500); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); await user.click(await screen.findByRole("button", { name: "校验规则" })); expect(await screen.findByText("无法校验游戏规则，请稍后重试。")).toBeInTheDocument(); expect(screen.queryByText(/SELECT raw_validate|players|driver failure/)).not.toBeInTheDocument();
  });

  it("validation gates publish on the saved revision and omits compiled snapshot", async () => {
    useServerSession(["rules.read", "rules.write", "rules.publish"]); const base = { ...fixtureRuleSet("classic_9", "draft"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; let validateBody: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input); const common = serverCommon(url); if (common) return common;
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) return json(base);
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9/validate")) { validateBody = JSON.parse(String(init?.body)); return json({ valid: true, errors: [], warnings: [{ code: "wording", path: "config.description", message: "建议补充说明" }], compiled_snapshot: { secret: "opaque" }, content_hash: "abcdef1234567890".padEnd(64, "a"), rule_text_preview: "规则预览正文" }); }
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

  it("announces valid and invalid server validation, including repeated outcomes", async () => {
    useServerSession(["rules.read", "rules.write", "rules.publish"]); const base = { ...fixtureRuleSet("classic_9", "draft"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; let validations = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const url = String(input); const common = serverCommon(url); if (common) return common;
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9")) return json(base);
      if (url.endsWith("/api/v1/admin/rule-sets/classic_9/validate")) { validations += 1; const valid = validations === 1; return json({ valid, errors: valid ? [] : [{ code: "invalid", path: "config.name", message: "名称未通过校验" }], warnings: [], compiled_snapshot: null, content_hash: valid ? "a".repeat(64) : null, rule_text_preview: valid ? "ok" : null }); }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); const validate = await screen.findByRole("button", { name: "校验规则" });
    await user.click(validate); const validAnnouncement = await expectAdminNotification("规则校验通过");
    await user.click(validate); const invalidAnnouncement = await expectAdminNotification("规则校验未通过"); expect(invalidAnnouncement).not.toBe(validAnnouncement);
    await user.click(within(invalidAnnouncement).getByRole("button", { name: "Close" }));
    await user.click(validate); expect(await expectAdminNotification("规则校验未通过")).not.toBe(invalidAnnouncement);
  });

  it("shows contract blockers and keeps publish disabled when P0 coverage is broken", async () => {
    useServerSession(["rules.read", "rules.write", "rules.publish"]); const base = { ...fixtureRuleSet("classic_9", "draft"), revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    const blockedContract = { ...ruleContract, coverage_status: "broken" as const, publish_ready: false, missing_p0_clause_ids: ["night.dawn.hidden_causes.v1"] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) return json(base); if (url.endsWith("/api/v1/admin/rule-sets/classic_9/validate")) return json({ valid: false, errors: [{ code: "rule_contract_p0_clause_missing", path: "rule_contract.clauses.night.dawn.hidden_causes.v1", message: "缺失 P0 条款" }], warnings: [], compiled_snapshot: { opaque: true }, content_hash: "a".repeat(64), rule_text_preview: "规则正文", rule_contract: blockedContract }); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); await user.click(await screen.findByRole("button", { name: "校验规则" }));
    expect(await screen.findByRole("heading", { name: "校验失败" })).toBeInTheDocument(); expect(screen.getByText("阻止发布")).toBeInTheDocument(); expect(screen.getByText("night.dawn.hidden_causes.v1")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "发布规则" })).toBeDisabled(); expect(screen.queryByText("opaque")).not.toBeInTheDocument();
  });

  it("publish rule requires its exact permission, trims a constrained reason, deduplicates, and refreshes from the server", async () => {
    useServerSession(["rules.read", "rules.write", "rules.publish"]); const draft = fixtureRuleSet("classic_9", "draft"); const detail = { ...draft, lock_version: 8, draft_revision: { ...draft.draft_revision!, lock_version: 7 }, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; const published = { ...fixtureRuleSet("classic_9", "published"), lock_version: 9 }; let publishBody: unknown; let publishCalls = 0; let gets = 0; let resolvePublish: ((value: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) { gets += 1; return json(gets === 1 ? detail : { ...published, revisions: [], usage: { game_count: 2, live_count: 0 }, warnings: [] }); } if (url.endsWith("/api/v1/admin/rule-sets/classic_9/validate")) return json({ valid: true, errors: [], warnings: [], compiled_snapshot: null, content_hash: "a".repeat(64), rule_text_preview: "ok" }); if (url.endsWith("/api/v1/admin/rule-sets/classic_9/publish")) { publishCalls += 1; publishBody = JSON.parse(String(init?.body)); return new Promise<Response>((resolve) => { resolvePublish = resolve; }); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); const { queryClient } = renderRoute("/content/rules/classic_9"); const invalidate = vi.spyOn(queryClient, "invalidateQueries"); await user.click(await screen.findByRole("button", { name: "校验规则" })); await user.click(await screen.findByRole("button", { name: "发布规则" }));
    const dialog = screen.getByRole("dialog", { name: "发布规则" }); expect(dialog).toHaveAccessibleDescription(); expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument(); const reason = screen.getByLabelText("操作原因"); expect(reason).toHaveAttribute("minlength", "3"); expect(reason).toHaveAttribute("maxlength", "500"); await user.type(reason, "  已完成评审  "); await user.click(screen.getByRole("button", { name: "确认发布" })); await user.click(screen.getByRole("button", { name: "正在发布..." })); expect(publishCalls).toBe(1); expect(publishBody).toEqual({ expected_rule_set_lock_version: 8, expected_revision_lock_version: 7, reason: "已完成评审" }); act(() => resolvePublish?.(json(published)));
    await expectAdminNotification("规则已发布"); expect(gets).toBeGreaterThanOrEqual(2); expect(screen.getByText(/规则锁版本 9/)).toBeInTheDocument(); expect(screen.queryByRole("heading", { name: "校验通过" })).not.toBeInTheDocument(); expect(invalidate).toHaveBeenCalledWith({ queryKey: ["rule-sets", "list"] }); expect(invalidate).toHaveBeenCalledWith({ queryKey: ["rule-sets", "detail", "classic_9"] });
  });

  it("publish rule dialog manages initial focus, tab containment, escape, and opener restoration", async () => {
    const user = userEvent.setup(); renderRoute("/content/rules/preview_draft"); await user.click(await screen.findByRole("button", { name: "校验规则" })); const opener = await screen.findByRole("button", { name: "发布规则" }); await user.click(opener);
    const reason = screen.getByLabelText("操作原因"); const confirm = screen.getByRole("button", { name: "确认发布" }); expect(reason).toHaveFocus(); confirm.focus(); await user.tab(); expect(reason).toHaveFocus(); await user.tab({ shift: true }); expect(confirm).toHaveFocus(); await user.keyboard("{Escape}"); expect(screen.queryByRole("dialog", { name: "发布规则" })).not.toBeInTheDocument(); expect(opener).toHaveFocus();
  });

  it("default rule requires rules.set_default and sends the listed current default lock", async () => {
    useServerSession(["rules.read", "rules.set_default"]); const target = { ...fixtureRuleSet("candidate", "published"), lock_version: 4, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; const current = { ...fixtureRuleSet("classic_9", "published", true), lock_version: 11 }; let body: unknown; let gets = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/candidate") && !init?.method) { gets += 1; return json(target); } if (url.includes("/api/v1/admin/rule-sets?") && !init?.method) return json({ items: [current, target], pagination: { page: 1, page_size: 100, total: 2, pages: 1 } }); if (url.endsWith("/api/v1/admin/rule-sets/candidate/set-default")) { body = JSON.parse(String(init?.body)); return json({ ...target, is_default: true, lock_version: 5 }); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/candidate"); expect(await screen.findByRole("button", { name: "设为默认" })).toBeInTheDocument(); expect(screen.queryByRole("button", { name: "归档规则" })).not.toBeInTheDocument(); await user.click(screen.getByRole("button", { name: "设为默认" })); expect(await screen.findByRole("dialog", { name: "设为默认规则" })).toHaveAccessibleDescription(); await user.type(screen.getByLabelText("操作原因"), "  调整默认规则  "); await user.click(screen.getByRole("button", { name: "确认设为默认" })); await waitFor(() => expect(body).toBeDefined()); expect(body).toEqual({ expected_rule_set_lock_version: 4, previous_default_expected_lock_version: 11, reason: "调整默认规则" }); expect(gets).toBeGreaterThanOrEqual(2); await expectAdminNotification("已设为默认规则");
  });

  it("default rule exhausts published pages and uses a later-page default lock", async () => {
    useServerSession(["rules.read", "rules.set_default"]); const target = { ...fixtureRuleSet("candidate", "published"), lock_version: 4 }; const detail = { ...target, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; const fillers = Array.from({ length: 100 }, (_, index) => fixtureRuleSet(`filler_${index}`, "published")); const laterDefault = { ...fixtureRuleSet("later_default", "published", true), lock_version: 77 }; const pages: number[] = []; const signals: (AbortSignal | null | undefined)[] = []; let body: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/candidate") && !init?.method) return json(detail); if (url.includes("/api/v1/admin/rule-sets?")) { const page = Number(new URL(url, "https://admin.test").searchParams.get("page")); pages.push(page); signals.push(init?.signal); return page === 1 ? json({ items: fillers, pagination: { page: 1, page_size: 100, total: 101, pages: 2 } }) : json({ items: [laterDefault], pagination: { page: 2, page_size: 100, total: 101, pages: 2 } }); } if (url.endsWith("/api/v1/admin/rule-sets/candidate/set-default")) { body = JSON.parse(String(init?.body)); return json({ ...target, is_default: true, lock_version: 5 }); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/candidate"); await user.click(await screen.findByRole("button", { name: "设为默认" })); await user.type(screen.getByLabelText("操作原因"), "切换默认规则"); await waitFor(() => expect(screen.getByRole("button", { name: "确认设为默认" })).toBeEnabled()); await user.click(screen.getByRole("button", { name: "确认设为默认" })); await waitFor(() => expect(body).toBeDefined()); expect(pages.slice(0, 2)).toEqual([1, 2]); expect(signals[0]).toBeInstanceOf(AbortSignal); expect(signals[1]).toBe(signals[0]); expect(body).toEqual({ expected_rule_set_lock_version: 4, previous_default_expected_lock_version: 77, reason: "切换默认规则" });
  });

  it("default rule blocks cached stale locks during background refresh and uses the refreshed lock", async () => {
    useServerSession(["rules.read", "rules.set_default"]); const target = { ...fixtureRuleSet("candidate", "published"), lock_version: 4 }; const detail = { ...target, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; const staleDefault = { ...fixtureRuleSet("old_default", "published", true), lock_version: 5 }; const freshDefault = { ...staleDefault, lock_version: 9 }; let resolveList: ((value: Response) => void) | undefined; let body: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/candidate") && !init?.method) return json(detail); if (url.includes("/api/v1/admin/rule-sets?")) return new Promise<Response>((resolve) => { resolveList = resolve; }); if (url.endsWith("/api/v1/admin/rule-sets/candidate/set-default")) { body = JSON.parse(String(init?.body)); return json({ ...target, is_default: true, lock_version: 5 }); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); const { queryClient } = renderRoute("/content/rules/candidate"); queryClient.setQueryData(["rule-sets", "list", "transition", "candidate"], { items: [staleDefault], pagination: { page: 1, page_size: 100, total: 1, pages: 1 } }); await user.click(await screen.findByRole("button", { name: "设为默认" })); await user.type(screen.getByLabelText("操作原因"), "刷新后切换"); expect(screen.getByRole("button", { name: "确认设为默认" })).toBeDisabled(); expect(body).toBeUndefined(); act(() => resolveList?.(json({ items: [freshDefault], pagination: { page: 1, page_size: 100, total: 1, pages: 1 } }))); await waitFor(() => expect(screen.getByRole("button", { name: "确认设为默认" })).toBeEnabled()); await user.click(screen.getByRole("button", { name: "确认设为默认" })); await waitFor(() => expect(body).toBeDefined()); expect(body).toEqual({ expected_rule_set_lock_version: 4, previous_default_expected_lock_version: 9, reason: "刷新后切换" });
  });

  it("set-default never queries or opens while a published rule has a dirty draft", async () => {
    useServerSession(["rules.read", "rules.write", "rules.set_default"]); const published = fixtureRuleSet("candidate", "published"); const detail = { ...published, draft_revision: fixtureRuleSet("candidate", "draft").draft_revision, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; let listCalls = 0; let transitionCalls = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/candidate") && !init?.method) return json(detail); if (url.includes("/api/v1/admin/rule-sets?")) { listCalls += 1; return json({ items: [], pagination: { page: 1, page_size: 100, total: 0, pages: 0 } }); } if (url.endsWith("/set-default")) { transitionCalls += 1; return json(detail); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/candidate"); const name = await screen.findByLabelText("规则名称"); await user.type(name, " 本地"); expect(screen.getByRole("button", { name: "设为默认" })).toBeDisabled(); expect(screen.queryByRole("dialog", { name: "设为默认规则" })).not.toBeInTheDocument(); expect(name).toHaveValue("candidate 草稿 本地"); expect(listCalls).toBe(0); expect(transitionCalls).toBe(0);
  });

  it("does not query lifecycle candidates with unadvertised status or sort values", async () => {
    useServerSession(["rules.read", "rules.set_default", "rules.archive"]); const target = fixtureRuleSet("candidate", "published", true); const detail = { ...target, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; const customOptions = { ...ruleSetOptions, statuses: [{ value: "archived", label: "仅归档" }], sorts: [{ value: "-name", label: "名称倒序" }] }; let listCalls = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => { const url = String(input); if (url.endsWith("/api/v1/admin/me")) return serverSession(); if (url.endsWith("/api/v1/admin/rule-set-options")) return json(customOptions); if (url.endsWith("/api/v1/admin/rule-sets/candidate")) return json(detail); if (url.includes("/api/v1/admin/rule-sets?")) { listCalls += 1; return json({ items: [], pagination: { page: 1, page_size: 100, total: 0, pages: 0 } }); } throw new Error(`Unexpected request: ${url}`); }));
    renderRoute("/content/rules/candidate"); expect(await screen.findByRole("button", { name: "归档规则" })).toBeDisabled(); expect(screen.getByText("规则选项未提供已发布规则查询，暂不能执行相关生命周期操作。")).toBeInTheDocument(); expect(listCalls).toBe(0);
  });

  it("archive rule never opens while a published rule has a dirty draft", async () => {
    useServerSession(["rules.read", "rules.write", "rules.archive"]); const current = { ...fixtureRuleSet("classic_9", "published", true), lock_version: 6, draft_revision: { ...fixtureRuleSet("classic_9", "draft").draft_revision!, lock_version: 3 }, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; const replacement = { ...fixtureRuleSet("classic_12", "published"), lock_version: 12 }; let body: unknown; let gets = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) { gets += 1; return json(current); } if (url.includes("/api/v1/admin/rule-sets?") && !init?.method) return json({ items: [current, replacement], pagination: { page: 1, page_size: 100, total: 2, pages: 1 } }); if (url.endsWith("/api/v1/admin/rule-sets/classic_9/archive")) { body = JSON.parse(String(init?.body)); return json({ ...current, status: "archived", is_default: false, lock_version: 7 }); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); const name = await screen.findByLabelText("规则名称"); await user.type(name, " 本地草稿");
    expect(screen.getByRole("button", { name: "归档规则" })).toBeDisabled();
    expect(screen.getByText("请先保存草稿或放弃修改，再执行生命周期操作。")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "归档规则" })).not.toBeInTheDocument(); expect(body).toBeUndefined(); expect(name).toHaveValue("classic_9 草稿 本地草稿"); expect(gets).toBe(1);
  });

  it("archive rule exhausts published pages and uses a deterministic later-page replacement lock", async () => {
    useServerSession(["rules.read", "rules.archive"]); const current = { ...fixtureRuleSet("current_default", "published", true), lock_version: 6 }; const detail = { ...current, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; const fillers = Array.from({ length: 99 }, (_, index) => fixtureRuleSet(`filler_${index}`, "published")); const replacementZ = { ...fixtureRuleSet("z_replacement", "published"), display_order: 2, lock_version: 88 }; const replacementA = { ...fixtureRuleSet("a_replacement", "published"), display_order: 2, lock_version: 99 }; const pages: number[] = []; let body: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/current_default") && !init?.method) return json(detail); if (url.includes("/api/v1/admin/rule-sets?")) { const page = Number(new URL(url, "https://admin.test").searchParams.get("page")); pages.push(page); return page === 1 ? json({ items: [current, ...fillers], pagination: { page: 1, page_size: 100, total: 102, pages: 2 } }) : json({ items: [replacementZ, replacementA], pagination: { page: 2, page_size: 100, total: 102, pages: 2 } }); } if (url.endsWith("/api/v1/admin/rule-sets/current_default/archive")) { body = JSON.parse(String(init?.body)); return json({ ...current, status: "archived", is_default: false, lock_version: 7 }); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/current_default"); await user.click(await screen.findByRole("button", { name: "归档规则" })); await waitFor(() => expect(screen.getByLabelText("替代默认规则")).toBeEnabled()); const replacementControl = screen.getByLabelText("替代默认规则"); await user.click(replacementControl); await user.type(replacementControl, "replacement"); await waitFor(() => expect(getOpenAntdOptions().map((option) => option.textContent ?? "")).toEqual([expect.stringContaining("a_replacement"), expect.stringContaining("z_replacement")])); await user.click(getOpenAntdOptions()[1]); await user.type(screen.getByLabelText("操作原因"), "替换默认规则"); await user.click(screen.getByRole("button", { name: "确认归档" })); await waitFor(() => expect(body).toBeDefined()); expect(pages.slice(0, 2)).toEqual([1, 2]); expect(body).toEqual({ expected_rule_set_lock_version: 6, replacement_default_rule_set_id: "z_replacement", replacement_expected_lock_version: 88, reason: "替换默认规则" });
  });

  it.each([
    ["rules.publish", "发布规则", ["设为默认", "归档规则"]],
    ["rules.set_default", "设为默认", ["发布规则", "归档规则"]],
    ["rules.archive", "归档规则", ["发布规则", "设为默认"]],
  ] as const)("removing %s hides only its exact lifecycle action", async (removed, hidden, visible) => {
    const permissions = ["rules.read", "rules.write", "rules.publish", "rules.set_default", "rules.archive"].filter((permission) => permission !== removed); useServerSession(permissions); const published = fixtureRuleSet("permission_rule", "published"); const detail = { ...published, draft_revision: fixtureRuleSet("permission_rule", "draft").draft_revision, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/permission_rule")) return json(detail); throw new Error(`Unexpected request: ${url}`); }));
    renderRoute("/content/rules/permission_rule"); await screen.findByLabelText("规则名称"); expect(screen.queryByRole("button", { name: hidden })).not.toBeInTheDocument(); for (const label of visible) expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
  });

  it("restore rule uses rules.archive, reports bounded transition errors, and trusts refreshed server lifecycle", async () => {
    useServerSession(["rules.read", "rules.archive"]); const archived = { ...fixtureRuleSet("legacy", "archived"), lock_version: 14, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; let calls = 0; let gets = 0; let restoreBody: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/legacy") && !init?.method) { gets += 1; return json(gets === 1 ? archived : { ...archived, status: "draft", lock_version: 15 }); } if (url.endsWith("/api/v1/admin/rule-sets/legacy/restore")) { calls += 1; restoreBody = JSON.parse(String(init?.body)); return calls === 1 ? json({ title: "private raw title", status: 503, detail: "database shard secret", code: "unavailable", request_id: "restore-503" }, 503) : json({ ...archived, status: "published", lock_version: 15 }); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/legacy"); await user.click(await screen.findByRole("button", { name: "恢复规则" })); expect(screen.queryByRole("button", { name: "归档规则" })).not.toBeInTheDocument(); expect(screen.getByRole("dialog", { name: "恢复规则" })).toHaveAccessibleDescription(); await user.type(screen.getByLabelText("操作原因"), "恢复历史规则"); await user.click(screen.getByRole("button", { name: "确认恢复" })); expect(restoreBody).toEqual({ expected_rule_set_lock_version: 14, reason: "恢复历史规则" }); const failure = await expectAdminNotification("规则生命周期操作失败"); expect(failure).toHaveTextContent("暂时无法完成操作，请稍后重试"); expect(screen.queryByText(/database shard|private raw/)).not.toBeInTheDocument(); await user.click(screen.getByRole("button", { name: "确认恢复" })); await expectAdminNotification("规则已恢复"); expect(screen.getByText("草稿")).toBeInTheDocument(); expect(gets).toBeGreaterThanOrEqual(2);
  });

  it.each((["publish", "default", "archive", "restore"] as const).flatMap((action) => ([409, 412] as const).map((status) => [action, status] as const)))("%s rule keeps its dialog and server state on %s", async (action, status) => {
    const permissions = action === "publish" ? ["rules.read", "rules.write", "rules.publish"] : action === "default" ? ["rules.read", "rules.set_default"] : ["rules.read", "rules.archive"]; useServerSession(permissions);
    const aggregate = action === "publish" ? { ...fixtureRuleSet("transition_rule", "draft"), lock_version: 5, draft_revision: { ...fixtureRuleSet("transition_rule", "draft").draft_revision!, lock_version: 4 } } : action === "restore" ? { ...fixtureRuleSet("transition_rule", "archived"), lock_version: 5 } : { ...fixtureRuleSet("transition_rule", "published"), lock_version: 5 };
    const detail = { ...aggregate, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; const suffix = { publish: "publish", default: "set-default", archive: "archive", restore: "restore" }[action];
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/transition_rule")) return json(detail); if (url.includes("/api/v1/admin/rule-sets?") && action === "default") return json({ items: [{ ...fixtureRuleSet("current", "published", true), lock_version: 9 }, aggregate], pagination: { page: 1, page_size: 100, total: 2, pages: 1 } }); if (url.endsWith("/validate") && action === "publish") return json({ valid: true, errors: [], warnings: [], compiled_snapshot: null, content_hash: "a".repeat(64), rule_text_preview: "ok" }); if (url.endsWith(`/transition_rule/${suffix}`)) return json({ title: "raw conflict", status, detail: "private lock detail", code: "rule_set_version_conflict", request_id: "conflict-secret" }, status); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/transition_rule"); if (action === "publish") await user.click(await screen.findByRole("button", { name: "校验规则" })); const openLabel = { publish: "发布规则", default: "设为默认", archive: "归档规则", restore: "恢复规则" }[action]; const dialogName = { publish: "发布规则", default: "设为默认规则", archive: "归档规则", restore: "恢复规则" }[action]; const confirmLabel = { publish: "确认发布", default: "确认设为默认", archive: "确认归档", restore: "确认恢复" }[action]; await user.click(await screen.findByRole("button", { name: openLabel })); await user.type(screen.getByLabelText("操作原因"), "有效原因"); await user.click(screen.getByRole("button", { name: confirmLabel }));
    expect(await screen.findByText(/规则状态已发生变化/)).toBeInTheDocument(); expect(screen.getByRole("dialog", { name: dialogName })).toBeInTheDocument(); expect(screen.getByText(/规则锁版本 5/)).toBeInTheDocument(); expect(screen.queryByText(/private lock|raw conflict|conflict-secret/)).not.toBeInTheDocument();
  });

  it("archive rule sends null replacement fields for a non-default rule and maps a 422 reason error", async () => {
    useServerSession(["rules.read", "rules.archive"]); const aggregate = { ...fixtureRuleSet("old_rule", "published"), lock_version: 7 }; const detail = { ...aggregate, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] }; let body: unknown;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/old_rule") && !init?.method) return json(detail); if (url.endsWith("/api/v1/admin/rule-sets/old_rule/archive")) { body = JSON.parse(String(init?.body)); return json({ title: "Invalid", status: 422, detail: "raw validation", code: "validation_error", request_id: null, errors: { reason: ["请说明归档原因"] } }, 422); } throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/old_rule"); await user.click(await screen.findByRole("button", { name: "归档规则" })); expect(screen.queryByLabelText("替代默认规则")).not.toBeInTheDocument(); await user.type(screen.getByLabelText("操作原因"), "不再使用"); await user.click(screen.getByRole("button", { name: "确认归档" })); const failure = await expectAdminNotification("规则生命周期操作失败"); expect(failure).toHaveTextContent("操作原因或规则状态不符合要求"); expect(screen.queryByText(/raw validation|请说明归档原因/)).not.toBeInTheDocument(); expect(body).toEqual({ expected_rule_set_lock_version: 7, replacement_default_rule_set_id: null, replacement_expected_lock_version: null, reason: "不再使用" });
  });

  it("archive rule disables confirmation when a default has no published replacement", async () => {
    useServerSession(["rules.read", "rules.archive"]); const aggregate = { ...fixtureRuleSet("only_rule", "published", true), lock_version: 3 }; const detail = { ...aggregate, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/only_rule")) return json(detail); if (url.includes("/api/v1/admin/rule-sets?")) return json({ items: [aggregate], pagination: { page: 1, page_size: 100, total: 1, pages: 1 } }); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/only_rule"); await user.click(await screen.findByRole("button", { name: "归档规则" })); expect(await screen.findByText("没有可用的替代规则，请先发布另一套规则。")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "确认归档" })).toBeDisabled();
  });

  it.each([
    ["name", "text", "规则名称", "变更名称"], ["description", "text", "规则说明", "变更说明"], ["complexity", "text", "复杂度", "困难"], ["duration", "text", "预计时长", "60 分钟"],
    ["tags", "text", "规则标签", "新标签"], ["order", "text", "显示顺序", "9"],
    ["werewolf count", "text", "狼人数量", "2"], ["villager count", "text", "村民数量", "4"], ["seer count", "text", "预言家数量", "0"], ["guard count", "text", "守卫数量", "1"], ["witch count", "text", "女巫数量", "0"], ["hunter count", "text", "猎人数量", "0"], ["idiot count", "text", "白痴数量", "1"],
    ["win condition", "select", "胜利条件", "屠边"], ["sheriff enabled", "check", "启用警长", ""], ["sheriff weight", "select", "警长票权", "2"], ["speech", "select", "发言规则", "顺序发言"], ["attack resolution", "select", "狼人刀口规则", "多数票，平票确定性随机"], ["allow no attack", "check", "允许狼人主动空刀", ""], ["allow wolf target", "check", "允许狼人选择狼队目标（含自刀）", ""], ["self explosion", "check", "允许狼人自爆", ""], ["badge policy", "select", "警徽规则", "不撕警徽"],
  ])("makes validation stale after editing %s and requires save plus revalidation", async (_name, kind, label, value) => {
    const user = userEvent.setup(); renderRoute("/content/rules/preview_draft");
    await user.click(await screen.findByRole("button", { name: "校验规则" })); expect(await screen.findByRole("button", { name: "发布规则" })).toBeEnabled();
    const control = screen.getByLabelText(label);
    if (kind === "check") await user.click(control);
    else if (kind === "select") await selectAntdOption(user, control, value);
    else { await user.clear(control); await user.type(control, value); }
    expect(screen.getByRole("button", { name: "发布规则" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "校验规则" })).toBeEnabled()); expect(screen.getByRole("button", { name: "发布规则" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "校验规则" })); await waitFor(() => expect(screen.getByRole("button", { name: "发布规则" })).toBeEnabled());
  });

  it("renders invalid server validation with associated path error and summary, without opaque snapshot", async () => {
    useServerSession(["rules.read", "rules.write", "rules.publish"]); const rule = fixtureRuleSet("classic_9", "draft"); const base = { ...rule, revisions: [], usage: { game_count: 0, live_count: 0 }, warnings: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { const url = String(input); const common = serverCommon(url); if (common) return common; if (url.endsWith("/api/v1/admin/rule-sets/classic_9") && !init?.method) return json(base); if (url.endsWith("/api/v1/admin/rule-sets/classic_9/validate")) return json({ valid: false, errors: [{ code: "name_invalid", path: "config.name", message: "规则名称被服务器拒绝" }, { code: "win_invalid", path: "config.win_condition", message: "胜利条件被服务器拒绝" }, { code: "speech_invalid", path: "config.speech_policy", message: "发言规则被服务器拒绝" }], warnings: [], compiled_snapshot: { opaque_secret: "must-not-render" }, content_hash: null, rule_text_preview: null }); throw new Error(`Unexpected request: ${url}`); }));
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); await user.click(await screen.findByRole("button", { name: "校验规则" }));
    expect(await screen.findByRole("heading", { name: "校验失败" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "校验错误" })).toHaveTextContent("config.name：规则名称被服务器拒绝");
    expect(screen.getByLabelText("规则名称")).toHaveAttribute("aria-invalid", "true"); expect(screen.getByLabelText("规则名称")).toHaveAccessibleDescription("规则名称被服务器拒绝");
    expect(screen.getByLabelText("胜利条件")).toHaveAttribute("aria-invalid", "true"); expect(screen.getByLabelText("胜利条件")).toHaveAccessibleDescription("胜利条件被服务器拒绝");
    expect(screen.getByLabelText("发言规则")).toHaveAttribute("aria-invalid", "true"); expect(screen.getByLabelText("发言规则")).toHaveAccessibleDescription("发言规则被服务器拒绝");
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
    const user = userEvent.setup(); renderRoute("/content/rules/classic_9"); expect(await screen.findByRole("heading", { name: "无法读取游戏规则" })).toBeInTheDocument(); expect(screen.getByText("规则目录暂时不可用，请稍后重试。")).toBeInTheDocument(); expect(screen.queryByText(/规则服务暂时不可用|internal_debug|do not show/)).not.toBeInTheDocument(); await user.click(screen.getByRole("button", { name: "重新加载" })); expect(await screen.findByDisplayValue("classic_9 草稿")).toBeInTheDocument(); expect(gets).toBe(2);
  });
});

function useServerSession(permissions: string[]) { vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true"); vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false"); sessionPermissions = permissions; }
let sessionPermissions: string[] = [];
function serverCommon(url: string) {
  if (url.endsWith("/api/v1/admin/me")) return serverSession();
  if (url.endsWith("/api/v1/admin/rule-set-options")) return json(ruleSetOptions);
}
function serverSession() { return json({ user: { id: "1", email: "r@test", display_name: "只读", role: "viewer" }, permissions: sessionPermissions, csrf_token: "csrf", session_expires_at: "2999-01-01T00:00:00Z" }); }
function json(body: unknown, status = 200) {
  let payload = body;
  if (typeof body === "object" && body !== null && !Array.isArray(body)) {
    const record = body as Record<string, unknown>;
    const isDetail = "usage" in record && "warnings" in record && "draft_revision" in record && "published_revision" in record;
    const isValidValidation = record.valid === true && "errors" in record && "warnings" in record;
    if ((isDetail || isValidValidation) && !("rule_contract" in record)) payload = { ...record, rule_contract: ruleContract };
  }
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}
