import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../tests/renderWithClient";
import { GamesPage } from "./GamesPage";

function ruleSetsResponse() {
  return {
    rule_sets: [
      {
        id: "classic_8",
        version: "2026.04",
        name: "经典 8 人局",
        description: "标准配置，适合完整推演。",
        player_count: 8,
        roles: [
          { role: "werewolf", count: 2, team: "werewolves" },
          { role: "villager", count: 4, team: "villagers" },
          { role: "seer", count: 1, team: "villagers" },
          { role: "guard", count: 1, team: "villagers" },
        ],
        role_summary: "2 狼人 / 4 村民 / 1 预言家 / 1 守卫",
        complexity: "标准",
        estimated_duration: "中",
        rule_tags: ["无警长", "顺序发言", "屠边"],
        sheriff_enabled: false,
        speech_policy: "sequential",
        speech_rounds: 1,
      },
      {
        id: "starter_6",
        version: "2026.04",
        name: "新手 6 人快局",
        description: "更短流程，适合快速验证。",
        player_count: 6,
        roles: [
          { role: "werewolf", count: 2, team: "werewolves" },
          { role: "villager", count: 3, team: "villagers" },
          { role: "seer", count: 1, team: "villagers" },
        ],
        role_summary: "2 狼人 / 3 村民 / 1 预言家",
        complexity: "入门",
        estimated_duration: "短",
        rule_tags: ["无警长", "顺序发言"],
        sheriff_enabled: false,
        speech_policy: "sequential",
        speech_rounds: 1,
      },
      {
        id: "sheriff_12",
        version: "2026.04",
        name: "标准 12 人警长局",
        description: "带警长竞选、警徽流与加权投票。",
        player_count: 12,
        roles: [
          { role: "werewolf", count: 4, team: "werewolves" },
          { role: "villager", count: 4, team: "villagers" },
          { role: "seer", count: 1, team: "villagers" },
          { role: "witch", count: 1, team: "villagers" },
          { role: "hunter", count: 1, team: "villagers" },
          { role: "idiot", count: 1, team: "villagers" },
        ],
        role_summary: "4 狼人 / 4 村民 / 1 预言家 / 1 女巫 / 1 猎人 / 1 白痴",
        complexity: "进阶",
        estimated_duration: "长",
        rule_tags: ["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
        sheriff_enabled: true,
        speech_policy: "sheriff_directed",
        speech_rounds: 2,
      },
    ],
  };
}

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
        tags: ["控场"],
        created_at: "2026-05-16T00:00:00Z",
        updated_at: "2026-05-16T00:00:00Z",
      },
    ],
  };
}

describe("GamesPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the lobby without the game history list", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/player-profiles")) {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            sessions: [
              {
                session_id: "session_20260424_001",
                status: "complete",
                winner: "狼人阵营",
                round_count: 4,
                created_at: "2026-04-24T10:00:00Z",
              },
            ],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    });

    const { container } = renderWithClient(<GamesPage />, "/games");

    expect(
      screen.getByRole("heading", { name: "狼人杀对局大厅" }),
    ).toBeInTheDocument();
    const nav = screen.getByTestId("arena-global-nav");
    expect(nav).toHaveAttribute("data-variant", "global");
    expect(nav).toHaveAttribute("data-surface", "transparent");
    expect(nav).toHaveClass(
      "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "min-h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "bg-transparent",
      "border-transparent",
    );
    expect(screen.getByTestId("arena-brand-logo")).toHaveClass(
      "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "w-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
    );
    expect(screen.getByTestId("arena-brand-logo").getAttribute("src")).toContain(
      "langrensha-c-logo",
    );
    expect(screen.getByTestId("arena-brand-wordmark").getAttribute("src")).toContain(
      "langrensha-title-wordmark",
    );
    expect(screen.getByRole("link", { name: "狼人杀竞技场" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(screen.getByRole("link", { name: "对局历史" })).toHaveAttribute(
      "href",
      "/games/history",
    );
    expect(
      screen.queryByRole("button", { name: "刷新列表" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建对局" })).toHaveClass(
      "gothic-button",
    );
    expect(screen.getByRole("link", { name: "对局历史" })).toHaveClass(
      "gothic-button",
    );
    expect(screen.queryByRole("link", { name: "返回大厅" })).not.toBeInTheDocument();
    expect(container.querySelector("main")).toHaveClass(
      "max-w-none",
      "w-full",
    );
    expect(container.querySelector("main")?.className).not.toContain("bg-");
    expect(container.querySelector("main")).not.toHaveClass("max-w-4xl");
    expect(screen.getByTestId("games-workspace-module")).toHaveClass(
      "games-workspace-module",
    );
    const playerLibrary = await screen.findByTestId("virtual-player-library");
    expect(
      within(playerLibrary).getByRole("heading", { name: "虚拟玩家库" }),
    ).toBeInTheDocument();
    expect(await within(playerLibrary).findByText("冷静的阿夜")).toBeInTheDocument();
    expect(within(playerLibrary).getByText("MiniMax-M2.7")).toBeInTheDocument();
    expect(within(playerLibrary).getByText("谨慎")).toBeInTheDocument();
    expect(
      within(playerLibrary).getByRole("button", { name: "新建虚拟玩家" }),
    ).toBeInTheDocument();
    const createModule = screen.getByTestId("games-create-module");
    expect(createModule).toHaveClass(
      "games-create-module",
      "lobby-console-form",
    );
    expect(createModule).not.toHaveClass("glass-panel");

    const consoleBar = within(createModule).getByTestId("lobby-console-bar");
    expect(
      within(consoleBar).getByRole("heading", { name: "狼人杀对局大厅" }),
    ).toBeInTheDocument();
    expect(within(consoleBar).getByLabelText("随机种子")).toBeInTheDocument();
    expect(within(consoleBar).getByLabelText("最大轮数")).toBeInTheDocument();
    expect(
      within(consoleBar).getByRole("combobox", { name: "演示慢速" }),
    ).toBeInTheDocument();
    expect(
      within(consoleBar).getByRole("button", { name: "发起对局" }),
    ).toHaveClass("gothic-button");

    const rulesPanel = within(createModule).getByTestId("lobby-rules-panel");
    expect(rulesPanel).toHaveClass(
      "lobby-rules-panel",
      "gothic-night-container",
      "gothic-night-container-md",
    );
    expect(
      rulesPanel.querySelector(".gothic-night-container-frame"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(
      rulesPanel.querySelectorAll(".gothic-night-container-frame-piece"),
    ).toHaveLength(8);
    expect(
      within(rulesPanel).getByRole("heading", { name: "官方规则" }),
    ).toBeInTheDocument();
    expect(within(rulesPanel).getByText("官方规则")).toBeInTheDocument();
    expect(screen.queryByTestId("games-sessions-module")).not.toBeInTheDocument();
    expect(screen.queryByText("session_20260424_001")).not.toBeInTheDocument();
    const officialRuleCards = await screen.findByRole("radiogroup", {
      name: "官方规则",
    });
    expect(officialRuleCards).toHaveClass("lobby-rule-grid");
    expect(screen.getByTestId("lobby-rules-panel")).toContainElement(
      officialRuleCards,
    );
    expect(screen.getByTestId("games-create-module")).toContainElement(
      screen.getByTestId("selected-rule-details"),
    );
    expect(screen.getByTestId("selected-rule-details")).toHaveClass(
      "lobby-rule-details",
    );
    expect(
      within(officialRuleCards).getByLabelText("经典 8 人局"),
    ).toBeInTheDocument();
    expect(within(officialRuleCards).getByLabelText("经典 8 人局")).toHaveClass(
      "lobby-rule-card",
      "lobby-rule-card-selected",
    );
    expect(
      within(officialRuleCards).getByLabelText("新手 6 人快局"),
    ).toBeInTheDocument();
    expect(within(officialRuleCards).getByLabelText("新手 6 人快局")).toHaveClass(
      "lobby-rule-card",
    );
    expect(
      within(officialRuleCards).getByLabelText("标准 12 人警长局"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("无警长")[0]).toBeInTheDocument();
    expect(screen.getAllByText("顺序发言")[0]).toBeInTheDocument();
    expect(screen.getByText("警徽 1.5 票")).toBeInTheDocument();
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        String(input).endsWith("/api/v1/games"),
      ),
    ).toBe(false);
  });

  it("shows the selected rule details below the official rule cards", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/player-profiles")) {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(<GamesPage />, "/games");

    const initialDetails = within(
      await screen.findByTestId("selected-rule-details"),
    );
    expect(
      initialDetails.getByRole("heading", { name: "经典 8 人局规则" }),
    ).toBeInTheDocument();
    expect(initialDetails.getByText("阵营配置")).toBeInTheDocument();
    expect(
      initialDetails.getByText("2 狼人 / 4 村民 / 1 预言家 / 1 守卫"),
    ).toBeInTheDocument();
    expect(initialDetails.getByText("无警长")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("标准 12 人警长局"));

    const updatedDetails = within(screen.getByTestId("selected-rule-details"));
    expect(
      updatedDetails.getByRole("heading", { name: "标准 12 人警长局规则" }),
    ).toBeInTheDocument();
    expect(
      updatedDetails.getByText(
        "4 狼人 / 4 村民 / 1 预言家 / 1 女巫 / 1 猎人 / 1 白痴",
      ),
    ).toBeInTheDocument();
    expect(updatedDetails.getByText("有警长，警徽 1.5 票")).toBeInTheDocument();
  });

  it("creates a live game run and navigates to the live page", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/player-profiles")) {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_1234abcd",
              session_id: "session_20260424_120000_ab12cd34",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              seed: null,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-04-24T12:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route
          path="/games/live/:runId"
          element={<p>实时观战 run_1234abcd</p>}
        />
      </Routes>,
      "/games",
    );

    await screen.findByLabelText("经典 8 人局");
    const launchButton = screen.getByRole("button", { name: "发起对局" });
    expect(launchButton).toBeEnabled();
    await userEvent.click(launchButton);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        body: JSON.stringify({
          rule_set_id: "classic_8",
          seed: null,
          max_rounds: 8,
          event_pacing: "off",
        }),
        method: "POST",
      }),
    );
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("creates a live game run with the selected official rule set", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/player-profiles")) {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_1234abcd",
              session_id: "session_20260424_120000_ab12cd34",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              rule_set_id: "starter_6",
              rule_set: {
                id: "starter_6",
                version: "2026.04",
                name: "新手 6 人快局",
                player_count: 6,
                roles: [],
              },
              seed: null,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-04-24T12:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route
          path="/games/live/:runId"
          element={<p>实时观战 run_1234abcd</p>}
        />
      </Routes>,
      "/games",
    );

    await userEvent.click(await screen.findByLabelText("新手 6 人快局"));
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        body: JSON.stringify({
          rule_set_id: "starter_6",
          seed: null,
          max_rounds: 8,
          event_pacing: "off",
        }),
        method: "POST",
      }),
    );
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("manages virtual player profiles from the library", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/player-profiles") && method === "GET") {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
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
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(<GamesPage />, "/games");

    await screen.findByText("冷静的阿夜");
    await userEvent.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
    await userEvent.type(screen.getByLabelText("虚拟玩家昵称"), "新玩家");
    await userEvent.type(screen.getByLabelText("默认模型"), "deepseek-chat");
    await userEvent.click(
      screen.getByRole("button", { name: "保存虚拟玩家" }),
    );

    await userEvent.click(
      await screen.findByRole("button", { name: "复制 冷静的阿夜" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "编辑 冷静的阿夜" }),
    );
    await userEvent.clear(screen.getByLabelText("虚拟玩家昵称"));
    await userEvent.type(screen.getByLabelText("虚拟玩家昵称"), "冷静的阿夜二号");
    await userEvent.click(
      screen.getByRole("button", { name: "保存虚拟玩家" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "删除 冷静的阿夜" }),
    );

    const postCalls = fetchSpy.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/api/v1/player-profiles") &&
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
    expect(patchCalls).toHaveLength(1);
    expect(deleteCalls).toHaveLength(1);
    expect(JSON.parse(String(postCalls[1][1]?.body))).toEqual(
      expect.objectContaining({
        display_name: "冷静的阿夜 副本",
        model: "MiniMax-M2.7",
      }),
    );
  });

  it("creates a live game run with standard event pacing", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/player-profiles")) {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_1234abcd",
              session_id: "session_20260424_120000_ab12cd34",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              seed: null,
              max_rounds: 8,
              event_pacing: "standard",
              status: "queued",
              created_at: "2026-04-24T12:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route
          path="/games/live/:runId"
          element={<p>实时观战 run_1234abcd</p>}
        />
      </Routes>,
      "/games",
    );

    await userEvent.selectOptions(
      await screen.findByRole("combobox", { name: "演示慢速" }),
      "standard",
    );
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        body: JSON.stringify({
          rule_set_id: "classic_8",
          seed: null,
          max_rounds: 8,
          event_pacing: "standard",
        }),
        method: "POST",
      }),
    );
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("blocks launch when max rounds is empty", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/player-profiles")) {
        return Promise.resolve(
          new Response(JSON.stringify(playerProfilesResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(<GamesPage />, "/games");

    await userEvent.clear(
      await screen.findByRole("spinbutton", { name: "最大轮数" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    expect(screen.getByText("最大轮数必须是 1 到 20 的整数")).toBeInTheDocument();
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        String(input).endsWith("/api/v1/games/runs"),
      ),
    ).toBe(false);
  });

});
