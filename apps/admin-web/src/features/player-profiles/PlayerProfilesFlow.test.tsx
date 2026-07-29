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
import {
  expectAntdSelectLabel,
  getOpenAntdOptions,
  selectAntdOption,
} from "@/tests/antd-select";
import { expectAdminNotification } from "@/tests/admin-notification";

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

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "状态 / C 端" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("暮鸦归票")).toBeInTheDocument();
    expect(await screen.findByText("雾灯听风")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(
      Array.from(document.querySelectorAll<HTMLImageElement>("img")).every(
        (image) => image.src.startsWith("data:"),
      ),
    ).toBe(true);
  });

  it("defaults to C-end order and exposes the published position controls", async () => {
    renderRoute("/content/players");

    const playerName = await screen.findByText("暮鸦归票");
    expect(playerName.closest("table")).not.toBeNull();
    expectAntdSelectLabel(screen.getByLabelText("排序"), "C 端顺序");
    expect(await screen.findByText("C 端 #1")).toBeInTheDocument();
    const playerRow = playerName.closest("tr");
    expect(playerRow).not.toBeNull();
    const upButton = playerRow!.querySelector<HTMLButtonElement>(
      '[aria-label="上移 暮鸦归票"]',
    );
    const downButton = playerRow!.querySelector<HTMLButtonElement>(
      '[aria-label="下移 暮鸦归票"]',
    );
    const editButton = playerRow!.querySelector<HTMLButtonElement>(
      '[aria-label="编辑 暮鸦归票"]',
    );
    expect(upButton).not.toBeNull();
    expect(downButton).not.toBeNull();
    expect(editButton).not.toBeNull();
    expect(upButton).toBeDisabled();
    expect(downButton).toBeEnabled();
    expect(upButton).toHaveClass("ant-btn-sm");
    expect(downButton).toHaveClass("ant-btn-sm");
    expect(editButton).toHaveClass("ant-btn-sm");
    expect(screen.getAllByText("未进入 C 端顺序")).toHaveLength(2);
  });

  it("shows each player's configured speaker and dialect in the list", async () => {
    await updatePreviewPlayerProfile("preview-draft-1", {
      expected_version: 2,
      tts_speaker: "zh_female_vv_uranus_bigtts",
      tts_dialect: "sichuan",
    });

    renderRoute("/content/players");

    expect(
      await screen.findByText("音色：Vivi 2.0 · 四川话"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("音色：继承全局").length).toBeGreaterThan(0);
  });

  it("keeps server filter and empty state in the URL", async () => {
    const user = userEvent.setup();
    const { router } = renderRoute("/content/players");
    await screen.findByText("暮鸦归票");

    await selectAntdOption(
      user,
      screen.getByLabelText("生命周期"),
      "草稿",
    );
    await waitFor(() =>
      expect(router.state.location.search).toContain("status=draft"),
    );
    expect(await screen.findByText("雾灯听风")).toBeInTheDocument();
    expect(screen.queryByText("暮鸦归票")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("搜索玩家"), "不存在的简介");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    expect(
      await screen.findByText(/没有符合条件的玩家/),
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

  it("fills a new form with an AI draft but still requires manual save", async () => {
    const user = userEvent.setup();
    renderRoute("/content/players/new");
    const nameInput = await screen.findByLabelText("玩家名称");
    expect(nameInput).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "AI 生成草稿" }));

    const notification = await expectAdminNotification("AI 草稿已填入");
    expect(notification).toHaveTextContent("请审核生成内容后再保存");
    expect(nameInput).toHaveValue("月影听风");
    expectAntdSelectLabel(screen.getByLabelText("默认模型"), "DeepSeek V4 Flash");
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeEnabled();
    expect(screen.getByRole("heading", { level: 1, name: "新建玩家草稿" })).toBeInTheDocument();
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
    await expectAdminNotification("玩家草稿已创建");
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
    await expectAdminNotification("玩家资料已保存");
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
    await expectAdminNotification("玩家已发布");
    expect(screen.queryByRole("alertdialog", { name: "发布虚拟玩家" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "归档" })).toBeInTheDocument();
  });

  it("edits optional player voice fields and explains the snapshot boundary", async () => {
    const user = userEvent.setup();
    renderRoute("/content/players/preview-draft-1");

    expect(
      await screen.findByRole("heading", {
        name: "玩家音色与基础演绎",
      }),
    ).toBeInTheDocument();
    const speakerSelect = screen.getByRole("combobox", { name: "玩家音色" });
    const instructionInput = screen.getByRole("textbox", {
      name: /^基础演绎提示/,
    });
    expectAntdSelectLabel(speakerSelect, "继承全局玩家音色");
    expectAntdSelectLabel(
      screen.getByRole("combobox", { name: "基础情绪" }),
      "克制 · restrained",
    );
    expectAntdSelectLabel(
      screen.getByRole("combobox", { name: "基础强度" }),
      "中 · medium",
    );
    expectAntdSelectLabel(
      screen.getByRole("combobox", { name: "基础语速" }),
      "自然 · natural",
    );
    expect(screen.getByText(/配置版本 3/)).toBeInTheDocument();
    expect(
      screen.getByText("留空重置为内置中性情绪 neutral。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("留空重置为内置中等强度 medium。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("留空重置为内置自然语速 natural。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/进行中、恢复、已排队语音和历史 Replay/),
    ).toBeInTheDocument();

    await selectAntdOption(
      user,
      speakerSelect,
      /zh_female_vv_uranus_bigtts.*Vivi 2\.0/,
    );
    await user.clear(instructionInput);
    await user.type(instructionInput, "  自然接话  ");
    await user.click(screen.getByRole("button", { name: "保存修改" }));

    await expectAdminNotification("玩家资料已保存");
    expect(instructionInput).toHaveValue("自然接话");
    expect(
      screen.getByText(/当前生效：zh_female_vv_uranus_bigtts/),
    ).toBeInTheDocument();
  });

  it("links role gender to Chinese TTS 2.0 speakers and dialect controls", async () => {
    const user = userEvent.setup();
    renderRoute("/content/players/preview-draft-1");
    const gender = await screen.findByRole("combobox", { name: /^角色性别/ });
    const speaker = screen.getByRole("combobox", { name: "玩家音色" });

    await user.click(speaker);
    const dialectSpeaker = getOpenAntdOptions().find((option) =>
      option.textContent?.includes("zh_female_vv_uranus_bigtts"),
    );
    expect(dialectSpeaker).toHaveTextContent("支持方言");
    expect(
      getOpenAntdOptions().some((option) =>
        option.textContent?.includes("zh_male_m191_uranus_bigtts"),
      ),
    ).toBe(false);
    await user.keyboard("{Escape}");

    await selectAntdOption(user, gender, "男");
    await user.click(speaker);
    const standardSpeaker = getOpenAntdOptions().find((option) =>
      option.textContent?.includes("zh_male_m191_uranus_bigtts"),
    );
    expect(standardSpeaker).toBeDefined();
    expect(standardSpeaker).not.toHaveTextContent("支持方言");
    expect(
      getOpenAntdOptions().some((option) =>
        option.textContent?.includes("zh_female_vv_uranus_bigtts"),
      ),
    ).toBe(false);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("combobox", { name: /^中文方言/ })).toBeNull();

    await selectAntdOption(user, gender, "女");
    await selectAntdOption(
      user,
      speaker,
      /zh_female_vv_uranus_bigtts.*Vivi 2\.0/,
    );
    const dialect = screen.getByRole("combobox", { name: /^中文方言/ });
    expectAntdSelectLabel(dialect, "普通话 / 不指定方言");
    await selectAntdOption(user, dialect, "四川话");
    expectAntdSelectLabel(dialect, "四川话");
  });

  it("previews the current unsaved voice draft and shows bounded safe output", async () => {
    const user = userEvent.setup();
    renderRoute("/content/players/preview-draft-1");
    await screen.findByRole("heading", { name: "草稿语音试听" });
    const speakerSelect = screen.getByRole("combobox", { name: "玩家音色" });
    await selectAntdOption(
      user,
      speakerSelect,
      /zh_female_vv_uranus_bigtts.*Vivi 2\.0/,
    );
    await selectAntdOption(
      user,
      screen.getByRole("combobox", { name: "中文方言" }),
      "四川话",
    );
    const sayInput = screen.getByRole("textbox", { name: /^试听文本/ });
    await user.clear(sayInput);
    await user.type(sayInput, "这是尚未保存的试听文本。");
    await selectAntdOption(
      user,
      screen.getByRole("combobox", { name: "本轮情绪" }),
      "紧张 · tense",
    );
    await user.type(
      screen.getByRole("textbox", { name: /^本轮演绎提示/ }),
      "3号狼人要急切反驳",
    );

    await user.click(screen.getByRole("button", { name: "试听当前草稿" }));

    const audio = await screen.findByLabelText("玩家语音试听");
    expect(audio).toHaveAttribute(
      "src",
      expect.stringMatching(/^(data:audio\/mpeg;base64,|blob:)/),
    );
    expect(
      screen.getAllByText("zh_female_vv_uranus_bigtts").length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("24000 Hz")).toBeInTheDocument();
    const contextPanel = screen
      .getByText("安全 context_texts")
      .closest(".player-voice-context-texts");
    expect(contextPanel).toBeInTheDocument();
    expect(contextPanel).toHaveTextContent("四川话");
    expect(screen.getByText(/tense \/ medium \/ natural/)).toBeInTheDocument();
    expect(contextPanel).not.toHaveTextContent("3号狼人");
    expect(screen.getByRole("button", { name: "保存修改" })).toBeEnabled();
  });

  it("shows the backend-safe preview error code for unsupported speakers", async () => {
    const user = userEvent.setup();
    await act(async () => {
      await updatePreviewPlayerProfile("preview-draft-1", {
        expected_version: 2,
        tts_speaker: "clone-speaker",
      });
    });
    renderRoute("/content/players/preview-draft-1");
    const speakerSelect = await screen.findByRole("combobox", {
      name: "玩家音色",
    });
    expectAntdSelectLabel(speakerSelect, /clone-speaker.*当前已保存/);
    await user.click(screen.getByRole("button", { name: "试听当前草稿" }));

    const notification = await expectAdminNotification("语音试听失败");
    expect(notification).toHaveTextContent("试听音色不支持");
    expect(notification).toHaveTextContent(
      "错误码：admin_player_voice_preview_context_unsupported",
    );
    expect(notification).not.toHaveTextContent("API Key");
  });

  it("keeps the voice section absent for legacy profiles", async () => {
    renderRoute("/content/players/preview-published-1");
    expect(await screen.findByLabelText("玩家名称")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "玩家音色与基础演绎" }),
    ).not.toBeInTheDocument();
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
    await expectAdminNotification("玩家已归档");

    await user.click(screen.getByRole("button", { name: "恢复发布" }));
    await user.type(screen.getByLabelText("操作原因"), "内容重新审核通过");
    await user.click(screen.getByRole("button", { name: "确认恢复" }));
    await expectAdminNotification("玩家已恢复发布");
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
      if (url.endsWith("/api/v1/admin/player-profile-tts-speakers")) {
        return jsonResponse(contractTtsSpeakers);
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
    expect(
      screen.getByRole("button", { name: "查看 服务器玩家" }),
    ).toBeInTheDocument();

    await user.click(screen.getByTitle("下一页"));
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
      if (url.endsWith("/api/v1/admin/player-profile-tts-speakers")) {
        return jsonResponse(contractTtsSpeakers);
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
      await screen.findByText("无法读取玩家内容"),
    ).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-player-error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });
});

const serverProfile: AdminPlayerProfile = {
  id: "server-profile",
  display_name: "服务器玩家",
  model_provider: "deepseek",
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
  gender: "female",
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
  models: [
    {
      provider: "deepseek",
      model_id: "deepseek-v4-flash",
      label: "DeepSeek V4 Flash",
    },
  ],
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
    example_messages_max_items: 5,
    example_message_max_length: 240,
  },
};

const contractTtsSpeakers = {
  resource_id: "seed-tts-2.0",
  items: [
    {
      voice_type: "zh_female_vv_uranus_bigtts",
      name: "Vivi 2.0",
      gender: "female",
      dialects: [{ id: "sichuan", label: "四川话" }],
    },
  ],
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": status >= 400 ? "application/problem+json" : "application/json",
    },
    status,
  });
}
