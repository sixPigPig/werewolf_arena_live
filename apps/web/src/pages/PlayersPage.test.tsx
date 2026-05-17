import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppTheme } from "../app/AppTheme";
import { routes } from "../routes/definitions";
import { PlayersPage } from "./PlayersPage";

function playerProfilesResponse() {
  return {
    profiles: [
      {
        id: "profile-1",
        owner_user_id: null,
        display_name: "冷静的阿夜",
        model: "MiniMax-M2.7",
        personality_id: "cautious",
        personality_text: "谨慎保守。",
        appearance_id: "moonlit",
        avatar_prompt: "银发观察者",
        avatar_image_url: "/api/v1/player-profiles/avatar/profile-1.png",
        avatar_image_mime: "image/png",
        tags: ["控场"],
        created_at: "2026-05-16T00:00:00Z",
        updated_at: "2026-05-16T00:00:00Z",
      },
    ],
  };
}

function modelOptionsResponse() {
  return {
    models: [
      { id: "deepseek-chat", label: "DeepSeek · deepseek-chat" },
      { id: "MiniMax-M2.7", label: "MiniMax · MiniMax-M2.7" },
    ],
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PlayersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderRoute(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });

  render(
    <AppTheme>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AppTheme>,
  );
}

describe("PlayersPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the dedicated virtual player workbench", async () => {
    renderPage();

    expect(
      screen.getByRole("heading", { name: "虚拟玩家工作台" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "返回大厅" }),
    ).toHaveAttribute("href", "/games");
  });

  it("routes /players to the dedicated virtual player workbench", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/player-profiles")) {
        return Promise.resolve(
          new Response(JSON.stringify({ profiles: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/model-options")) {
        return Promise.resolve(
          new Response(JSON.stringify({ models: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }

      return Promise.resolve(new Response(null, { status: 404 }));
    });

    renderRoute("/players");

    expect(
      await screen.findByRole("heading", { name: "虚拟玩家工作台" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "返回大厅" }),
    ).toHaveAttribute("href", "/games");
  });

  it("opens the player editor from the nav-level create action", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/player-profiles")) {
        return Promise.resolve(
          new Response(JSON.stringify({ profiles: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/model-options")) {
        return Promise.resolve(
          new Response(JSON.stringify(modelOptionsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }

      return Promise.resolve(new Response(null, { status: 404 }));
    });

    renderPage();

    await userEvent.click(
      within(screen.getByTestId("arena-global-nav")).getByRole("button", {
        name: "新建虚拟玩家",
      }),
    );

    expect(screen.getByLabelText("虚拟玩家昵称")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "保存虚拟玩家" }),
    ).toBeInTheDocument();
  });

  it("manages virtual player profiles from the player workbench", async () => {
    let avatarUploadCount = 0;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/v1/player-profiles") && method === "GET") {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/model-options")) {
        return Promise.resolve(
          new Response(JSON.stringify(modelOptionsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (
        url.endsWith("/api/v1/player-profiles/avatar") &&
        method === "POST"
      ) {
        avatarUploadCount += 1;
        const filename = avatarUploadCount === 1 ? "uploaded.png" : "edited.png";
        return Promise.resolve(
          new Response(
            JSON.stringify({
              avatar_image_url: `/api/v1/player-profiles/avatar/${filename}`,
              avatar_image_mime: "image/png",
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.endsWith("/api/v1/player-profiles") && method === "POST") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...playerProfilesResponse().profiles[0],
              id: "profile-new",
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (
        url.endsWith("/api/v1/player-profiles/profile-1") &&
        method === "PATCH"
      ) {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse().profiles[0]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (
        url.endsWith("/api/v1/player-profiles/profile-1") &&
        method === "DELETE"
      ) {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(new Response(null, { status: 404 }));
    });

    renderPage();

    const playerLibrary = await screen.findByTestId("virtual-player-library");
    expect(await within(playerLibrary).findByText("冷静的阿夜")).toBeInTheDocument();
    expect(within(playerLibrary).getByText("MiniMax-M2.7")).toBeInTheDocument();
    expect(within(playerLibrary).getByText("谨慎")).toBeInTheDocument();
    expect(
      within(playerLibrary).getByRole("img", { name: "冷静的阿夜 人物形象" }),
    ).toHaveAttribute("src", "/api/v1/player-profiles/avatar/profile-1.png");

    await userEvent.click(
      within(playerLibrary).getByRole("button", { name: "新建虚拟玩家" }),
    );
    const generatedNameInput = screen.getByLabelText("虚拟玩家昵称") as HTMLInputElement;
    expect(generatedNameInput.value.trim().length).toBeGreaterThan(0);
    await userEvent.clear(generatedNameInput);
    await userEvent.type(generatedNameInput, "新玩家");
    const modelSelect = screen.getByRole("combobox", { name: "默认模型" });
    expect(modelSelect).toHaveValue("deepseek-chat");
    expect(
      within(modelSelect).getByRole("option", {
        name: "MiniMax · MiniMax-M2.7",
      }),
    ).toBeInTheDocument();
    await userEvent.selectOptions(modelSelect, "deepseek-chat");
    await userEvent.type(screen.getByLabelText("性格描述"), "谨慎发言，先听后判");
    await userEvent.upload(
      screen.getByLabelText("人物形象"),
      new File([new Uint8Array([137, 80, 78, 71])], "avatar.png", {
        type: "image/png",
      }),
    );
    expect(
      await screen.findByRole("img", { name: "新玩家 人物形象" }),
    ).toHaveAttribute("src", "/api/v1/player-profiles/avatar/uploaded.png");
    await userEvent.type(screen.getByLabelText("标签"), "控场 慢热");
    const saveNewProfileButton = screen.getByRole("button", {
      name: "保存虚拟玩家",
    });
    await waitFor(() => expect(saveNewProfileButton).toBeEnabled());
    await userEvent.click(saveNewProfileButton);

    const copyProfileButton = await screen.findByRole("button", {
      name: "复制 冷静的阿夜",
    });
    await waitFor(() => expect(copyProfileButton).toBeEnabled());
    await userEvent.click(copyProfileButton);

    const editProfileButton = await screen.findByRole("button", {
      name: "编辑 冷静的阿夜",
    });
    await waitFor(() => expect(editProfileButton).toBeEnabled());
    await userEvent.click(editProfileButton);
    await userEvent.clear(screen.getByLabelText("虚拟玩家昵称"));
    await userEvent.type(screen.getByLabelText("虚拟玩家昵称"), "冷静的阿夜二号");
    await userEvent.clear(screen.getByLabelText("性格描述"));
    await userEvent.type(screen.getByLabelText("性格描述"), "二号更谨慎");
    await userEvent.upload(
      screen.getByLabelText("人物形象"),
      new File([new Uint8Array([137, 80, 78, 71])], "edited.png", {
        type: "image/png",
      }),
    );
    expect(
      await screen.findByRole("img", { name: "冷静的阿夜二号 人物形象" }),
    ).toHaveAttribute("src", "/api/v1/player-profiles/avatar/edited.png");
    await userEvent.clear(screen.getByLabelText("标签"));
    await userEvent.type(screen.getByLabelText("标签"), "控场 追刀");
    const saveEditedProfileButton = screen.getByRole("button", {
      name: "保存虚拟玩家",
    });
    await waitFor(() => expect(saveEditedProfileButton).toBeEnabled());
    await userEvent.click(saveEditedProfileButton);

    const deleteProfileButton = await screen.findByRole("button", {
      name: "删除 冷静的阿夜",
    });
    await waitFor(() => expect(deleteProfileButton).toBeEnabled());
    await userEvent.click(deleteProfileButton);

    const confirmDeleteProfileButton = await screen.findByRole("button", {
      name: "确认删除 冷静的阿夜",
    });
    await waitFor(() => expect(confirmDeleteProfileButton).toBeEnabled());
    await userEvent.click(confirmDeleteProfileButton);

    const postCalls = fetchSpy.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/api/v1/player-profiles") &&
        init?.method === "POST",
    );
    const uploadCalls = fetchSpy.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/api/v1/player-profiles/avatar") &&
        init?.method === "POST",
    );
    const patchCalls = fetchSpy.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/api/v1/player-profiles/profile-1") &&
        init?.method === "PATCH",
    );
    const deleteCalls = fetchSpy.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/api/v1/player-profiles/profile-1") &&
        init?.method === "DELETE",
    );

    expect(postCalls).toHaveLength(2);
    expect(uploadCalls).toHaveLength(2);
    expect(patchCalls).toHaveLength(1);
    expect(deleteCalls).toHaveLength(1);
    expect(JSON.parse(String(postCalls[0][1]?.body))).toEqual(
      expect.objectContaining({
        display_name: "新玩家",
        model: "deepseek-chat",
        personality_text: "谨慎发言，先听后判",
        avatar_image_url: "/api/v1/player-profiles/avatar/uploaded.png",
        avatar_image_mime: "image/png",
        tags: ["控场", "慢热"],
      }),
    );
    expect(JSON.parse(String(postCalls[1][1]?.body))).toEqual(
      expect.objectContaining({
        display_name: "冷静的阿夜 副本",
        model: "MiniMax-M2.7",
        avatar_image_url: "/api/v1/player-profiles/avatar/profile-1.png",
        avatar_image_mime: "image/png",
      }),
    );
    expect(JSON.parse(String(patchCalls[0][1]?.body))).toEqual(
      expect.objectContaining({
        display_name: "冷静的阿夜二号",
        personality_text: "二号更谨慎",
        avatar_image_url: "/api/v1/player-profiles/avatar/edited.png",
        avatar_image_mime: "image/png",
        tags: ["控场", "追刀"],
      }),
    );
  });
});
