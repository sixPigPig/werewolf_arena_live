import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import {
  resetPreviewPlayerProfiles,
  updatePreviewPlayerProfile,
} from "@/features/player-profiles/preview-repository";
import type { AdminPlayerProfile } from "@/features/player-profiles/types";
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

describe("admin player profile flow", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "true");
    resetPreviewPlayerProfiles();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("renders responsive semantic preview data without any API request or API image", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/content/players");

    expect(
      await screen.findByRole("list", { name: "虚拟玩家列表" }),
    ).toBeInTheDocument();
    expect(screen.getByText("暮鸦归票")).toBeInTheDocument();
    expect(screen.getByText("雾灯听风")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(
      Array.from(document.querySelectorAll<HTMLImageElement>("img")).every(
        (image) => image.src.startsWith("data:"),
      ),
    ).toBe(true);
  });

  it("keeps server filter and empty state in the URL", async () => {
    const user = userEvent.setup();
    const { router } = renderRoute("/content/players");
    await screen.findByText("暮鸦归票");

    await user.selectOptions(screen.getByLabelText("生命周期"), "draft");
    await waitFor(() =>
      expect(router.state.location.search).toContain("status=draft"),
    );
    expect(await screen.findByText("雾灯听风")).toBeInTheDocument();
    expect(screen.queryByText("暮鸦归票")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("搜索玩家"), "不存在的简介");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    expect(
      await screen.findByRole("heading", { name: "没有符合条件的玩家" }),
    ).toBeInTheDocument();
    expect(router.state.location.search).toContain(
      `q=${encodeURIComponent("不存在的简介")}`,
    );
  });

  it("focuses the first invalid field when creating a draft", async () => {
    const user = userEvent.setup();
    renderRoute("/content/players/new");
    const nameInput = await screen.findByLabelText("玩家名称");

    await user.click(screen.getByRole("button", { name: "保存草稿" }));

    expect(await screen.findByText("请输入玩家名称")).toBeInTheDocument();
    await waitFor(() => expect(nameInput).toHaveFocus());
  });

  it("creates a draft and opens its independent detail route", async () => {
    const user = userEvent.setup();
    const { router } = renderRoute("/content/players/new");
    const nameInput = await screen.findByLabelText("玩家名称");
    await user.type(nameInput, "新建测试玩家");

    await user.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() =>
      expect(router.state.location.pathname).toMatch(
        /^\/content\/players\/preview-created-/,
      ),
    );
    expect(
      await screen.findByRole("heading", { level: 1, name: "新建测试玩家" }),
    ).toBeInTheDocument();
  });

  it("requires saving dirty changes and an audit reason before publishing", async () => {
    const user = userEvent.setup();
    renderRoute("/content/players/preview-draft-1");
    const nameInput = await screen.findByLabelText("玩家名称");
    const publishButton = screen.getByRole("button", { name: "发布" });

    await user.type(nameInput, " 本地修改");
    expect(publishButton).toBeDisabled();
    expect(
      screen.getByText("请先保存修改，再执行生命周期操作。"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "保存修改" }));
    expect(await screen.findByText("玩家资料已保存")).toBeInTheDocument();
    expect(publishButton).toBeEnabled();

    await user.click(publishButton);
    const dialog = screen.getByRole("alertdialog", { name: "发布虚拟玩家" });
    const reason = screen.getByLabelText("操作原因");
    await user.type(reason, "短");
    await user.click(
      screen.getByRole("button", { name: "确认发布" }),
    );
    expect(screen.getByText("操作原因需为 3 到 500 个字符")).toBeInTheDocument();
    expect(dialog).toBeInTheDocument();
    expect(reason).toHaveFocus();

    await user.clear(reason);
    await user.type(reason, "内容审核已经通过");
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    expect(await screen.findByText("玩家已发布")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog", { name: "发布虚拟玩家" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "归档" })).toBeInTheDocument();
  });

  it("keeps dirty form content when expected_version conflicts", async () => {
    const user = userEvent.setup();
    renderRoute("/content/players/preview-draft-1");
    const nameInput = await screen.findByLabelText("玩家名称");
    await user.clear(nameInput);
    await user.type(nameInput, "本地尚未提交的名字");

    await act(async () => {
      await updatePreviewPlayerProfile("preview-draft-1", {
        expected_version: 2,
        display_name: "另一位操作者的名字",
      });
    });
    await user.click(screen.getByRole("button", { name: "保存修改" }));

    expect(
      await screen.findByText("其他操作者已经更新了该玩家"),
    ).toBeInTheDocument();
    expect(nameInput).toHaveValue("本地尚未提交的名字");
    expect(screen.getByText(/服务器当前版本为 3/)).toBeInTheDocument();
  });

  it("archives and restores a published player through audited dialogs", async () => {
    const user = userEvent.setup();
    renderRoute("/content/players/preview-published-1");
    await screen.findByLabelText("玩家名称");

    await user.click(screen.getByRole("button", { name: "归档" }));
    await user.type(screen.getByLabelText("操作原因"), "内容运营下线");
    await user.click(screen.getByRole("button", { name: "确认归档" }));
    expect(await screen.findByText("玩家已归档")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "恢复发布" }));
    await user.type(screen.getByLabelText("操作原因"), "内容重新审核通过");
    await user.click(screen.getByRole("button", { name: "确认恢复" }));
    expect(await screen.findByText("玩家已恢复发布")).toBeInTheDocument();
  });

  it("uses authenticated server pagination and hides writes from a read-only principal", async () => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse({
          user: {
            id: "7",
            email: "viewer@example.test",
            display_name: "只读观察员",
            role: "viewer",
          },
          permissions: ["players.read"],
          csrf_token: "csrf-viewer",
          session_expires_at: "2999-01-01T00:00:00Z",
        });
      }
      if (url.endsWith("/api/v1/admin/player-profile-options")) {
        return jsonResponse(contractOptions);
      }
      if (url.includes("/api/v1/admin/player-profiles?")) {
        const requestUrl = new URL(url, "https://admin.test");
        const page = Number(requestUrl.searchParams.get("page"));
        return jsonResponse({
          items: [{ ...serverProfile, id: `server-page-${page}` }],
          pagination: { page, page_size: 10, total: 11, pages: 2 },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { router } = renderRoute("/content/players?page_size=10");

    expect(await screen.findByText("服务器玩家")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "新建玩家草稿" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看 服务器玩家" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(router.state.location.search).toContain("page=2"));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => String(input).includes("page=2")),
      ).toBe(true),
    );
  });

  it("shows loading and a retryable structured server error", async () => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    let failList: ((response: Response) => void) | undefined;
    const listResponse = new Promise<Response>((resolve) => {
      failList = resolve;
    });
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse({
          user: {
            id: "7",
            email: "viewer@example.test",
            display_name: "只读观察员",
            role: "viewer",
          },
          permissions: ["players.read"],
          csrf_token: "csrf-viewer",
          session_expires_at: "2999-01-01T00:00:00Z",
        });
      }
      if (url.endsWith("/api/v1/admin/player-profile-options")) {
        return jsonResponse(contractOptions);
      }
      if (url.includes("/api/v1/admin/player-profiles?")) {
        return listResponse;
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/content/players");

    expect(
      await screen.findByText("正在读取玩家内容..."),
    ).toBeInTheDocument();
    act(() =>
      failList?.(
        jsonResponse(
          {
            title: "Player service unavailable",
            status: 503,
            detail: "玩家服务暂时不可用",
            code: "admin_player_profiles_unavailable",
            request_id: "req-player-error",
          },
          503,
        ),
      ),
    );

    expect(
      await screen.findByRole("heading", { name: "无法读取玩家内容" }),
    ).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-player-error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });
});

const serverProfile: AdminPlayerProfile = {
  id: "server-profile",
  display_name: "服务器玩家",
  model: "deepseek-v4-flash",
  personality_id: "analytical",
  personality_text: "重视票型。",
  appearance_id: "default",
  avatar_asset_id: null,
  avatar_image_url: "",
  avatar_image_mime: "",
  short_description: "来自服务器",
  background_story: "",
  speaking_style: "",
  catchphrases: [],
  strategy_profile: "logic_leader",
  risk_tolerance: 3,
  bluffing_tendency: 3,
  trust_tendency: 3,
  leadership_tendency: 3,
  talkativeness: 3,
  example_messages: [],
  display_order: 1,
  featured: false,
  tags: [],
  status: "published",
  version: 1,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-10T00:00:00Z",
  published_at: "2026-07-01T00:00:00Z",
  deleted_at: null,
  published_by: "1",
  updated_by: "1",
};

const contractOptions = {
  models: [{ id: "deepseek-v4-flash", label: "DeepSeek V4 Flash" }],
  personalities: [
    { id: "analytical", label: "分析", description: "重视票型。" },
  ],
  appearances: [
    {
      id: "default",
      label: "默认",
      description: "默认形象",
      avatar_asset_id: null,
      avatar_image_url: "",
    },
  ],
  strategies: [
    { id: "logic_leader", label: "逻辑带队", description: "整理票型。" },
  ],
  constraints: {
    tags_max_items: 8,
    tag_max_length: 20,
    catchphrases_max_items: 6,
    catchphrase_max_length: 40,
    example_messages_max_items: 5,
    example_message_max_length: 240,
  },
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": status >= 400 ? "application/problem+json" : "application/json",
    },
    status,
  });
}
