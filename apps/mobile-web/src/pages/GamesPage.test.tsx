import { readFileSync } from "node:fs";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import { routes } from "../routes/definitions";
import type {
  GameRun,
  RuleSetSummary,
  VirtualPlayerProfile,
} from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  createGameRun: vi.fn(),
  listPlayerProfiles: vi.fn(),
  listRuleSets: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    createGameRun: gameClientMocks.createGameRun,
    listPlayerProfiles: gameClientMocks.listPlayerProfiles,
    listRuleSets: gameClientMocks.listRuleSets,
  };
});

const classicRuleSet: RuleSetSummary = {
  id: "classic_8",
  version: "test",
  name: "经典 8 人",
  player_count: 2,
  role_summary: "测试阵容",
  roles: [],
};

const starterRuleSet: RuleSetSummary = {
  ...classicRuleSet,
  id: "starter_6",
  name: "新手 6 人快局",
  player_count: 6,
  role_summary: "1 狼人 / 1 预言家 / 1 守卫 / 3 村民",
};

const socialRuleSet: RuleSetSummary = {
  ...classicRuleSet,
  id: "social_8",
  name: "社交 8 人局",
  player_count: 8,
  role_summary: "2 狼人 / 1 女巫 / 1 猎人 / 4 村民",
};

const classic12RuleSet: RuleSetSummary = {
  ...classicRuleSet,
  id: "classic_12_seer_witch_hunter_idiot",
  name: "12 人预女猎白局",
  player_count: 12,
  role_summary: "4 狼人 / 1 猎人 / 1 女巫 / 1 预言家 / 1 白痴 / 4 村民",
};

function buildProfile(
  overrides: Pick<VirtualPlayerProfile, "display_name" | "id"> &
    Partial<VirtualPlayerProfile>,
): VirtualPlayerProfile {
  const { display_name, id, ...profileOverrides } = overrides;

  return {
    owner_user_id: null,
    model: overrides.model ?? "test-model",
    personality_id: overrides.personality_id ?? "balanced",
    personality_text: "",
    short_description: "",
    background_story: "",
    speaking_style: "",
    catchphrases: [],
    strategy_profile: "balanced",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    favorite: overrides.favorite ?? false,
    appearance_id: overrides.appearance_id ?? "default",
    avatar_prompt: "",
    avatar_image_url: "",
    avatar_image_mime: "",
    tags: [],
    created_at: "2026-06-19T00:00:00.000Z",
    updated_at: "2026-06-19T00:00:00.000Z",
    ...profileOverrides,
    id,
    display_name,
  };
}

function buildRun(overrides: Partial<GameRun> = {}): GameRun {
  return {
    run_id: "run-123",
    session_id: "session-123",
    villager_model: "test-model",
    werewolf_model: "test-model",
    seed: null,
    max_rounds: 8,
    winner: null,
    status: "queued",
    created_at: "2026-06-19T00:00:00.000Z",
    started_at: null,
    completed_at: null,
    error: null,
    event_count: 0,
    ...overrides,
  };
}

function renderGamesPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(routes, { initialEntries: ["/games"] });

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { queryClient, router };
}

function readPngMetadata(path: string) {
  const image = readFileSync(path);

  return {
    width: image.readUInt32BE(16),
    height: image.readUInt32BE(20),
    colorType: image.readUInt8(25),
  };
}

describe("GamesPage", () => {
  beforeEach(() => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classicRuleSet],
    });
    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [
        buildProfile({
          id: "profile-1",
          display_name: "阿青",
          favorite: true,
          short_description: "雾夜里的分析者",
          strategy_profile: "analysis",
          tags: ["分析"],
        }),
        buildProfile({
          id: "profile-2",
          display_name: "白石",
          short_description: "稳健守序的观察者",
          strategy_profile: "balanced",
          tags: ["均衡"],
        }),
      ],
    });
    gameClientMocks.createGameRun.mockResolvedValue(buildRun());
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows the branded lobby banner image in the hero", async () => {
    renderGamesPage();

    const banner = await screen.findByRole("img", { name: "狼人杀对局大厅" });
    const styles = readFileSync("src/styles/index.css", "utf8");
    const heroWrapperRule = styles.match(/\.mobile-lobby-hero\s*{[^}]+}/)?.[0];
    const heroRule = styles.match(/\.mobile-lobby-hero-image\s*{[^}]+}/)?.[0];

    expect(banner).toHaveClass("mobile-lobby-hero-image");
    expect(banner).toHaveAttribute(
      "src",
      expect.stringContaining("mobile-lobby-hero"),
    );
    expect(heroWrapperRule).toContain("width: min(54%, 230px)");
    expect(heroWrapperRule).toContain("justify-self: start");
    expect(heroRule).toContain("width: 100%");
    expect(heroRule).toContain("height: auto");
    expect(heroRule).toContain("object-fit: contain");
    expect(heroRule).toContain("object-position: left center");
  });

  it("uses cropped rule card images instead of text inside rule choices", async () => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [
        { ...classicRuleSet, player_count: 8, role_summary: "2 狼人 / 1 预言家 / 1 守卫 / 4 村民" },
        starterRuleSet,
      ],
    });
    renderGamesPage();

    const selectedRule = await screen.findByRole("radio", {
      name: "选择规则 经典 8 人",
    });
    const unselectedRule = screen.getByRole("radio", {
      name: "选择规则 新手 6 人快局",
    });
    const selectedCard = selectedRule.closest(".mobile-lobby-rule-card");
    const unselectedCard = unselectedRule.closest(".mobile-lobby-rule-card");

    expect(selectedCard).not.toHaveTextContent("经典 8 人局");
    expect(selectedCard).not.toHaveTextContent("2 狼人");
    expect(selectedCard?.querySelector(".mobile-lobby-rule-card-image")).toHaveAttribute(
      "src",
      expect.stringContaining("selected"),
    );
    expect(unselectedCard).not.toHaveTextContent("新手 6 人快局");
    expect(unselectedCard).not.toHaveTextContent("1 狼人");
    expect(unselectedCard?.querySelector(".mobile-lobby-rule-card-image")).toHaveAttribute(
      "src",
      expect.stringContaining("unselected"),
    );

    const styles = readFileSync("src/styles/index.css", "utf8");
    const scrollRule = styles.match(/\.mobile-lobby-rule-scroll\s*{[^}]+}/)?.[0];
    const imageRule = styles.match(/\.mobile-lobby-rule-card-image\s*{[^}]+}/)?.[0];
    const pickerRule = styles.match(/\.mobile-lobby-rule-picker\s*{[^}]+}/)?.[0];

    expect(pickerRule).toContain("gap: 0");
    expect(scrollRule).toContain("grid-auto-columns: calc((100% - 8px) / 3)");
    expect(scrollRule).toContain("gap: 4px");
    expect(scrollRule).toContain("padding: 0 1px 0");
    expect(imageRule).toContain("aspect-ratio: 3 / 4");
    expect(styles).not.toContain(".mobile-lobby-rule-card:focus-within");
    [
      "classic-8-selected",
      "classic-8-unselected",
      "starter-6-selected",
      "starter-6-unselected",
      "social-8-selected",
      "social-8-unselected",
      "classic-12-selected",
      "classic-12-unselected",
    ].forEach((assetName) => {
      expect(readPngMetadata(`src/assets/rule-cards/${assetName}.png`)).toEqual({
        width: 1080,
        height: 1440,
        colorType: 6,
      });
    });
  });

  it("renders a text fallback instead of classic artwork for unknown rule card assets", async () => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [
        {
          ...classicRuleSet,
          id: "custom_10",
          name: "自定义 10 人局",
          player_count: 10,
          role_summary: "3 狼人 / 7 好人",
          complexity: "自定义",
        },
      ],
    });
    renderGamesPage();

    const selectedRule = await screen.findByRole("radio", {
      name: "选择规则 自定义 10 人局，10 人局，3 狼人 / 7 好人",
    });
    const selectedCard = selectedRule.closest(".mobile-lobby-rule-card");

    expect(selectedCard).toHaveTextContent("自定义 10 人局");
    expect(selectedCard).toHaveTextContent("10 人局");
    expect(selectedCard).toHaveTextContent("3 狼人 / 7 好人");
    expect(
      selectedCard?.querySelector(".mobile-lobby-rule-card-image"),
    ).not.toBeInTheDocument();
  });

  it("centers rule indicator dots and highlights the selected rule color", async () => {
    const user = userEvent.setup();
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classicRuleSet, starterRuleSet, socialRuleSet, classic12RuleSet],
    });
    renderGamesPage();

    const indicators = await screen.findByLabelText("规则选择指示");
    const dots = within(indicators).getAllByRole("button");

    expect(dots).toHaveLength(4);
    expect(dots[0]).toHaveAttribute("aria-current", "true");
    expect(dots[0]).toHaveClass("mobile-lobby-rule-dot-classic");
    expect(dots[1]).toHaveClass("mobile-lobby-rule-dot-starter");
    expect(dots[2]).toHaveClass("mobile-lobby-rule-dot-social");
    expect(dots[3]).toHaveClass("mobile-lobby-rule-dot-advanced");

    await user.click(dots[1]);

    expect(
      screen.getByRole("radio", { name: "选择规则 新手 6 人快局" }),
    ).toBeChecked();
    expect(scrollTo).toHaveBeenCalledWith({
      behavior: "smooth",
      left: expect.any(Number),
    });
    expect(dots[1]).toHaveAttribute("aria-current", "true");
    expect(dots[0]).not.toHaveAttribute("aria-current");

    const styles = readFileSync("src/styles/index.css", "utf8");
    const dotsRule = styles.match(/\.mobile-lobby-rule-dots\s*{[^}]+}/)?.[0];
    const dotRule = styles.match(/\.mobile-lobby-rule-dot\s*{[^}]+}/)?.[0] ?? "";
    const dotBeforeRule =
      styles.match(/\.mobile-lobby-rule-dot::before\s*{[^}]+}/)?.[0] ?? "";
    const activeDotBeforeRule =
      styles.match(/\.mobile-lobby-rule-dot-active::before\s*{[^}]+}/)?.[0] ?? "";

    expect(dotsRule).toContain("justify-content: center");
    expect(dotsRule).toContain("gap: 4px");
    expect(dotsRule).toContain("min-height: 20px");
    expect(dotRule).toContain("width: 22px");
    expect(dotRule).toContain("height: 20px");
    expect(dotRule).toContain("background: transparent");
    expect(dotBeforeRule).toContain("width: 7px");
    expect(dotBeforeRule).toContain("height: 7px");
    expect(activeDotBeforeRule).toContain("width: 18px");
    expect(styles).toContain(".mobile-lobby-rule-dot-classic");
    expect(styles).toContain(".mobile-lobby-rule-dot-starter");
    expect(styles).toContain(".mobile-lobby-rule-dot-social");
    expect(styles).toContain(".mobile-lobby-rule-dot-advanced");
  });

  it("fills empty seats and creates a live game run", async () => {
    const user = userEvent.setup();
    const { router } = renderGamesPage();

    await user.click(await screen.findByRole("button", { name: "随机补齐" }));
    await user.click(screen.getByRole("button", { name: "发起对局" }));

    await waitFor(() => {
      expect(gameClientMocks.createGameRun).toHaveBeenCalledWith({
        rule_set_id: "classic_8",
        seed: null,
        max_rounds: 8,
        player_configs: [
          { seat: 1, profile_id: expect.any(String) },
          { seat: 2, profile_id: expect.any(String) },
        ],
      });
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/games/run-123/live");
    });
  });

  it("requires a second tap before clearing assigned seats", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认选择" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "玩家卡牌库" }),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 阿青",
      }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "清空席位" }));
    expect(screen.getByRole("button", { name: "确认清空" })).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 阿青",
      }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "确认清空" }));
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    ).toBeVisible();
  });

  it("resets clear confirmation when submit validation fails", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认选择" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "玩家卡牌库" }),
      ).not.toBeInTheDocument();
    });
    await user.clear(screen.getByRole("spinbutton", { name: "最大轮数" }));
    await user.type(screen.getByRole("spinbutton", { name: "最大轮数" }), "0");
    await user.click(screen.getByRole("button", { name: "清空席位" }));
    expect(screen.getByRole("button", { name: "确认清空" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "补齐并发起" }));

    expect(screen.getByText("最大轮数必须是 1 到 20 的整数")).toBeVisible();
    expect(screen.getByRole("button", { name: "清空席位" })).toBeVisible();
  });

  it("disables clear while game creation is pending", async () => {
    const user = userEvent.setup();
    gameClientMocks.createGameRun.mockReturnValue(
      new Promise(() => undefined),
    );
    renderGamesPage();

    await user.click(await screen.findByRole("button", { name: "随机补齐" }));
    await user.click(screen.getByRole("button", { name: "发起对局" }));

    expect(screen.getByRole("button", { name: "发起中" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "清空席位" })).toBeDisabled();
  });

  it("blocks creation when the player library cannot fill the selected rule set", async () => {
    const user = userEvent.setup();
    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [buildProfile({ id: "profile-1", display_name: "阿青" })],
    });
    renderGamesPage();

    await user.click(await screen.findByRole("button", { name: "随机补齐" }));

    expect(await screen.findByText("已选 1/2 · 还差 1 名玩家")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "还差 1 名玩家" }),
    ).toBeDisabled();
    expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();
  });

  it("labels launch as auto-fill when empty seats can be completed from the library", async () => {
    renderGamesPage();

    expect(await screen.findByText("已选 0/2 · 可自动补齐")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "补齐并发起" }),
    ).toBeEnabled();
  });

  it("shows a ready launch state when every seat has a player", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(await screen.findByRole("button", { name: "随机补齐" }));

    expect(await screen.findByText("已选 2/2 · 阵容已就绪")).toBeVisible();
    expect(screen.getByRole("button", { name: "发起对局" })).toBeEnabled();
  });

  it("blocks launch before submit when the player library cannot fill the lineup", async () => {
    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [buildProfile({ id: "profile-1", display_name: "阿青" })],
    });
    renderGamesPage();

    expect(await screen.findByText("已选 0/2 · 还差 1 名玩家")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "还差 1 名玩家" }),
    ).toBeDisabled();
    expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();
  });

  it("opens the player card drawer from a selected seat", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );

    expect(screen.getByRole("dialog", { name: "玩家卡牌库" })).toBeVisible();
    expect(screen.getByText("当前选择：1号座位")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    ).toBeVisible();
  });

  it("keeps keyboard focus inside the player card drawer and restores it", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    const seatButton = await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    });
    await user.click(seatButton);

    const dialog = screen.getByRole("dialog", { name: "玩家卡牌库" });
    await waitFor(() => {
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    });
    expect(document.querySelector(".mobile-lobby-content")).toHaveAttribute(
      "inert",
    );

    for (let index = 0; index < 12; index += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }

    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await user.click(screen.getByRole("button", { name: "关闭玩家卡牌库" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "玩家卡牌库" }),
      ).not.toBeInTheDocument();
    });
    expect(seatButton).toHaveFocus();
    expect(document.querySelector(".mobile-lobby-content")).not.toHaveAttribute(
      "inert",
    );
  });

  it("lays out eight seats as two horizontal rows on mobile", async () => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [{ ...classicRuleSet, player_count: 8 }],
    });
    renderGamesPage();

    await screen.findByRole("button", {
      name: "选择 8 号座位，当前为 待选择",
    });

    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatGridRule = styles.match(/\.mobile-lobby-seat-grid\s*{[^}]+}/)?.[0];
    const seatCardRule = styles.match(/\.mobile-lobby-seat-card\s*{[^}]+}/)?.[0];
    const actionBarRule =
      styles.match(/\.mobile-lobby-action-bar\s*{[^}]+}/)?.[0] ?? "";

    expect(seatGridRule).toContain("grid-template-columns: repeat(4");
    expect(seatGridRule).toContain("grid-template-rows: repeat(2");
    expect(seatCardRule).toContain("min-height: 52px");
    expect(actionBarRule).toContain("grid-template-columns: repeat(4");
    expect(actionBarRule).toContain("bottom: calc(var(--mobile-tab-frame-height) + 6px");
  });

  it("searches profiles when a profile has no tags", async () => {
    const user = userEvent.setup();
    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [
        buildProfile({
          id: "profile-1",
          display_name: "无标签玩家",
          model: "tagless-model",
          tags: undefined as unknown as string[],
        }),
      ],
    });
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.type(screen.getByLabelText("搜索玩家"), "tagless");

    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 无标签玩家" }),
    ).toBeVisible();
  });

  it("confirms a player card into the active seat", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认选择" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "玩家卡牌库" }),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 阿青",
      }),
    ).toBeVisible();
  });

  it("labels player cards that are already assigned and confirms moves explicitly", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认选择" }));

    await user.click(
      await screen.findByRole("button", {
        name: "选择 2 号座位，当前为 待选择",
      }),
    );

    expect(screen.getByText("已在 1 号座位")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "为 2 号座位候选 阿青，已在 1 号座位" }),
    );
    expect(screen.getByRole("button", { name: "移动到 2 号座位" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "移动到 2 号座位" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "玩家卡牌库" }),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: "选择 2 号座位，当前为 阿青",
      }),
    ).toBeVisible();
  });

  it("can confirm a player and advance to the next empty seat without closing the drawer", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认并下一位" }));

    expect(screen.getByRole("dialog", { name: "玩家卡牌库" })).toBeVisible();
    expect(screen.getByText("当前选择：2号座位")).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 阿青",
      }),
    ).toBeVisible();
    expect(screen.getByText("请选择一张玩家卡")).toBeVisible();
  });

  it("includes the current-seat status in assigned player card names", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认选择" }));

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 阿青",
      }),
    );

    const currentSeatCard = screen.getByRole("button", {
      name: "为 1 号座位候选 阿青，当前座位",
    });
    expect(currentSeatCard).toBeVisible();
    expect(within(currentSeatCard).getByText("当前座位")).toBeVisible();
  });

  it("disables confirmation when the pending player is removed by refresh", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    expect(
      within(screen.getByRole("dialog", { name: "玩家卡牌库" })).getByRole(
        "button",
        { name: "确认选择" },
      ),
    ).toBeEnabled();

    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [
        buildProfile({
          id: "profile-2",
          display_name: "白石",
          short_description: "稳健守序的观察者",
          strategy_profile: "balanced",
          tags: ["均衡"],
        }),
      ],
    });
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["player-profiles"] });
    });

    const drawer = screen.getByRole("dialog", { name: "玩家卡牌库" });
    await waitFor(() => {
      expect(within(drawer).getByText("请选择一张玩家卡")).toBeVisible();
    });
    expect(
      within(drawer).getByRole("button", { name: "确认选择" }),
    ).toBeDisabled();
  });

  it("closes the player card drawer without changing the seat", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    expect(
      screen.getAllByRole("button", { name: "关闭玩家卡牌库" }),
    ).toHaveLength(1);
    await user.click(
      within(screen.getByRole("dialog", { name: "玩家卡牌库" })).getByRole(
        "button",
        { name: "关闭玩家卡牌库" },
      ),
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "玩家卡牌库" }),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    ).toBeVisible();
  });
});
