import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "@/routes";
import { resetPreviewRuleSets } from "./preview-repository";
import { fixtureRuleSet, ruleSetOptions } from "./test-fixtures";

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
});

function useServerSession(permissions: string[]) { vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true"); vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false"); sessionPermissions = permissions; }
let sessionPermissions: string[] = [];
function serverCommon(url: string) {
  if (url.endsWith("/api/v1/admin/me")) return json({ user: { id: "1", email: "r@test", display_name: "只读", role: "viewer" }, permissions: sessionPermissions, csrf_token: "csrf", session_expires_at: "2999-01-01T00:00:00Z" });
  if (url.endsWith("/api/v1/admin/rule-set-options")) return json(ruleSetOptions);
}
function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }
