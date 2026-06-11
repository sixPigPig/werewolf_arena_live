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
        avatar_image_url: "/api/v1/player-profiles/avatar/profile-1.png",
        avatar_image_mime: "image/png",
        tags: ["控场"],
        created_at: "2026-05-16T00:00:00Z",
        updated_at: "2026-05-16T00:00:00Z",
      },
    ],
  };
}

function fullPlayerProfilesResponse(count = 8) {
  const [firstProfile] = playerProfilesResponse().profiles;

  return {
    profiles: Array.from({ length: count }, (_, index) => ({
      ...firstProfile,
      id: `profile-${index + 1}`,
      display_name: index === 0 ? "冷静的阿夜" : `随机玩家${index + 1}`,
      avatar_image_url: `/api/v1/player-profiles/avatar/profile-${index + 1}.png`,
      favorite: index === 0,
      short_description: index === 0 ? "谨慎控场玩家" : "",
      strategy_profile: "balanced",
    })),
  };
}

function mockLobbyRequests(
  profilesResponse = fullPlayerProfilesResponse(8),
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
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
        new Response(JSON.stringify(profilesResponse), {
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
}

function multiPlayerProfilesResponse() {
  return {
    profiles: [
      {
        ...playerProfilesResponse().profiles[0],
        favorite: true,
        short_description: "谨慎控场玩家",
        strategy_profile: "cautious_observer",
      },
      {
        ...playerProfilesResponse().profiles[0],
        id: "profile-2",
        display_name: "影刃",
        model: "Qwen",
        personality_id: "aggressive",
        personality_text: "主动施压。",
        favorite: false,
        short_description: "高压进攻玩家",
        strategy_profile: "pressure_attacker",
        avatar_image_url: "/api/v1/player-profiles/avatar/profile-2.png",
        tags: ["进攻"],
      },
    ],
  };
}

function lineupWorkbenchProfilesResponse() {
  const response = fullPlayerProfilesResponse(8);
  response.profiles[1] = {
    ...response.profiles[1],
    display_name: "影刃",
    model: "Qwen",
    personality_id: "aggressive",
    personality_text: "主动施压。",
    favorite: false,
    short_description: "高压进攻玩家",
    strategy_profile: "pressure_attacker",
    tags: ["进攻"],
  };
  return response;
}

function findGameRunRequest(fetchSpy: {
  mock: { calls: Array<[unknown, RequestInit?]> };
}) {
  const call = fetchSpy.mock.calls.find((mockCall) =>
    String(mockCall[0]).endsWith("/api/v1/games/runs"),
  );
  if (!call) {
    throw new Error("Expected a game run request");
  }
  return JSON.parse(String(call[1]?.body));
}

function emptyPlayerProfilesResponse() {
  return { profiles: [] };
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
                session_id: "game_00000001",
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
    expect(screen.getByRole("link", { name: "玩家库" })).toHaveAttribute(
      "href",
      "/players",
    );
    expect(
      screen.queryByRole("heading", { name: "虚拟玩家工作台" }),
    ).not.toBeInTheDocument();
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
    expect(
      screen.queryByTestId("virtual-player-library"),
    ).not.toBeInTheDocument();
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
      within(consoleBar).getByRole("button", { name: "发起对局" }),
    ).toHaveClass("gothic-button");
    const workbench = await screen.findByTestId("lobby-lineup-workbench");
    expect(
      within(workbench).getByTestId("lobby-lineup-column"),
    ).toBeInTheDocument();
    expect(
      within(workbench).getByTestId("lobby-player-column"),
    ).toBeInTheDocument();
    expect(
      within(workbench).getByRole("heading", { name: "组建阵容" }),
    ).toBeInTheDocument();
    expect(
      within(workbench).getByRole("heading", { name: "玩家卡牌库" }),
    ).toBeInTheDocument();
    expect(
      within(workbench).getByRole("button", { name: "1号空席" }),
    ).toBeInTheDocument();
    expect(
      within(workbench).getByText("当前席位 · 1 号"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "选择虚拟玩家" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "为 1 号座位选择 冷静的阿夜" }),
    ).toBeInTheDocument();

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
    expect(screen.queryByText("game_00000001")).not.toBeInTheDocument();
    const officialRuleCards = await screen.findByRole("radiogroup", {
      name: "官方规则",
    });
    expect(officialRuleCards).toHaveClass("lobby-rule-grid");
    expect(screen.getByTestId("lobby-rules-panel")).toContainElement(
      officialRuleCards,
    );
    expect(screen.getByTestId("games-create-module")).toContainElement(
      screen.getByRole("button", { name: "规则详情" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "经典 8 人局规则" }),
    ).not.toBeInTheDocument();
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

  it("renders seat assignment profile cards in the game lobby", async () => {
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
          new Response(JSON.stringify(fullPlayerProfilesResponse(8)), {
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

    const playerColumn = within(
      await screen.findByTestId("lobby-lineup-workbench"),
    ).getByTestId("lobby-player-column");
    expect(
      within(playerColumn).getByRole("button", {
        name: "为 1 号座位选择 冷静的阿夜",
      }),
    ).toBeInTheDocument();
  });

  it("applies player cards immediately and summarizes the lineup", async () => {
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
          new Response(JSON.stringify(lineupWorkbenchProfilesResponse()), {
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

    expect(await screen.findByText("已选 0 / 8")).toBeInTheDocument();
    expect(screen.getByText("空席将由系统随机补齐")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "2号空席" }));
    expect(screen.getByText("当前席位 · 2 号")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "为 2 号座位选择 影刃" }),
    );

    expect(
      screen.getByRole("button", { name: "2号影刃" }),
    ).toBeInTheDocument();
    expect(screen.getByText("已选 1 / 8")).toBeInTheDocument();
    expect(screen.getByText("已在 2 号位")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "1号空席" }));
    await userEvent.click(
      screen.getByRole("button", { name: "为 1 号座位选择 冷静的阿夜" }),
    );

    expect(
      screen.getByRole("button", { name: "1号冷静的阿夜" }),
    ).toBeInTheDocument();
    expect(screen.getByText("已选 2 / 8")).toBeInTheDocument();
    expect(screen.getByText("已在 1 号位")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    const body = findGameRunRequest(fetchSpy);
    expect(body.rule_set_id).toBe("classic_8");
    expect(body.player_configs).toHaveLength(8);
    expect(body.player_configs[0]).toEqual({ seat: 1, profile_id: "profile-1" });
    expect(body.player_configs[1]).toEqual({ seat: 2, profile_id: "profile-2" });
    expect(
      new Set(body.player_configs.map((config: { profile_id: string }) => config.profile_id)).size,
    ).toBe(8);
  });

  it("filters the player picker by search and favorites", async () => {
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
          new Response(JSON.stringify(multiPlayerProfilesResponse()), {
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

    await screen.findByRole("button", { name: "为 1 号座位选择 冷静的阿夜" });
    expect(
      screen.getByRole("button", { name: "为 1 号座位选择 影刃" }),
    ).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("搜索可选虚拟玩家"), "影");

    expect(
      screen.queryByRole("button", { name: "为 1 号座位选择 冷静的阿夜" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "为 1 号座位选择 影刃" }),
    ).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("搜索可选虚拟玩家"));
    await userEvent.click(screen.getByRole("button", { name: "只看收藏" }));

    expect(
      screen.getByRole("button", { name: "为 1 号座位选择 冷静的阿夜" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "为 1 号座位选择 影刃" }),
    ).not.toBeInTheDocument();
  });

  it("links to the player library when seat assignment has no profiles", async () => {
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
          new Response(JSON.stringify(emptyPlayerProfilesResponse()), {
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

    const createLink = await screen.findByRole("link", {
      name: "去玩家库创建",
    });
    expect(createLink).toHaveAttribute("href", "/players");
    expect(
      screen.queryByRole("button", { name: /为 1 号座位选择/ }),
    ).not.toBeInTheDocument();
  });

  it("shows that seat profiles are still loading separately from an empty library", async () => {
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
        return new Promise<Response>(() => undefined);
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(<GamesPage />, "/games");

    expect(
      screen.getByText("正在读取虚拟玩家资料，席位选择加载完成后可用。"),
    ).toBeInTheDocument();
    expect(
      await screen.findByTestId("lobby-lineup-workbench"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "去玩家库创建" }),
    ).not.toBeInTheDocument();
  });

  it("shows when seat profiles failed to load separately from an empty library", async () => {
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
        return Promise.resolve(new Response(null, { status: 500 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(<GamesPage />, "/games");

    expect(
      await screen.findByRole("alert", {
        name: "无法读取虚拟玩家资料，暂时不能发起对局。",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "去玩家库创建" }),
    ).not.toBeInTheDocument();
  });

  it("shows the selected rule details in a drawer", async () => {
    mockLobbyRequests(fullPlayerProfilesResponse(12));

    renderWithClient(<GamesPage />, "/games");

    await screen.findByRole("radiogroup", { name: "官方规则" });
    expect(
      screen.queryByRole("dialog", { name: "经典 8 人局规则" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "规则详情" }));

    const initialDetails = within(
      screen.getByRole("dialog", { name: "经典 8 人局规则" }),
    );
    expect(
      initialDetails.getByText("2 狼人 / 4 村民 / 1 预言家 / 1 守卫"),
    ).toBeInTheDocument();

    await userEvent.click(
      initialDetails.getByRole("button", { name: "关闭规则详情" }),
    );

    await userEvent.click(screen.getByLabelText("标准 12 人警长局"));
    await userEvent.click(screen.getByRole("button", { name: "规则详情" }));

    const updatedDetails = within(
      screen.getByRole("dialog", { name: "标准 12 人警长局规则" }),
    );
    expect(updatedDetails.getByText("有警长，警徽 1.5 票")).toBeInTheDocument();
  });

  it("randomly fills all seats from the virtual player library when launching without manual selections", async () => {
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
          new Response(JSON.stringify(fullPlayerProfilesResponse(8)), {
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
              session_id: "game_1200abcd",
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

    await screen.findByText("已选 0 / 8");
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    const body = findGameRunRequest(fetchSpy);
    expect(body.player_configs).toHaveLength(8);
    expect(body.player_configs.map((config: { seat: number }) => config.seat)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8,
    ]);
    expect(
      new Set(body.player_configs.map((config: { profile_id: string }) => config.profile_id)).size,
    ).toBe(8);
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("opens a player-library shortage dialog instead of launching when not enough virtual players exist", async () => {
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

    await screen.findByText("已选 0 / 8");
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    const dialog = screen.getByRole("dialog", { name: "玩家库玩家不足" });
    expect(dialog).toHaveTextContent("当前规则需要 8 名虚拟玩家");
    expect(dialog).toHaveTextContent("玩家库当前只有 1 名可用玩家");
    expect(within(dialog).getByRole("link", { name: "去新建玩家" })).toHaveAttribute(
      "href",
      "/players",
    );
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        String(input).endsWith("/api/v1/games/runs"),
      ),
    ).toBe(false);
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
          new Response(JSON.stringify(fullPlayerProfilesResponse(8)), {
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
              session_id: "game_1200abcd",
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

    const body = findGameRunRequest(fetchSpy);
    expect(body.rule_set_id).toBe("classic_8");
    expect(body.player_configs).toHaveLength(8);
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
          new Response(JSON.stringify(fullPlayerProfilesResponse(8)), {
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
              session_id: "game_1200abcd",
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

    const body = findGameRunRequest(fetchSpy);
    expect(body.rule_set_id).toBe("starter_6");
    expect(body.player_configs).toHaveLength(6);
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("clears the selected seat profile and overrides", async () => {
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
          new Response(JSON.stringify(fullPlayerProfilesResponse(8)), {
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
              session_id: "game_1200abcd",
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

    await userEvent.type(
      await screen.findByLabelText("1 号座位模型覆盖"),
      "qwen3.6-plus",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "为 1 号座位选择 冷静的阿夜" }),
    );
    expect(screen.getByText("已选 1 / 8")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "清空当前座位" }));
    expect(screen.getByText("已选 0 / 8")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    const body = findGameRunRequest(fetchSpy);
    expect(body.rule_set_id).toBe("classic_8");
    expect(body.player_configs).toHaveLength(8);
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
