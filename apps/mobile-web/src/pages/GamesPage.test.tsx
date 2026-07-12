import { readFileSync } from "node:fs";
import { inflateSync } from "node:zlib";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import { routes } from "../routes/definitions";
import type {
  GameRun,
  PublicPlayerProfile,
  RuleSetSummary,
} from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  createGameRun: vi.fn(),
  favoritePlayerProfile: vi.fn(),
  listPlayerProfileFavorites: vi.fn(),
  listPublicPlayerProfiles: vi.fn(),
  listRuleSets: vi.fn(),
  unfavoritePlayerProfile: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    createGameRun: gameClientMocks.createGameRun,
    favoritePlayerProfile: gameClientMocks.favoritePlayerProfile,
    listPlayerProfileFavorites: gameClientMocks.listPlayerProfileFavorites,
    listPublicPlayerProfiles: gameClientMocks.listPublicPlayerProfiles,
    listRuleSets: gameClientMocks.listRuleSets,
    unfavoritePlayerProfile: gameClientMocks.unfavoritePlayerProfile,
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

const classic12RuleSet: RuleSetSummary = {
  ...classicRuleSet,
  id: "classic_12_seer_witch_hunter_idiot",
  name: "12 人预女猎白局",
  player_count: 12,
  role_summary: "4 狼人 / 1 猎人 / 1 女巫 / 1 预言家 / 1 白痴 / 4 村民",
};

function buildProfile(
  overrides: Pick<PublicPlayerProfile, "display_name" | "id"> &
    Partial<PublicPlayerProfile>,
): PublicPlayerProfile {
  const { display_name, id, ...profileOverrides } = overrides;

  return {
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
    display_order: overrides.display_order ?? 1,
    featured: overrides.featured ?? false,
    appearance_id: overrides.appearance_id ?? "default",
    avatar_image_url: "",
    tags: [],
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

function readPngRgbaImage(path: string) {
  const image = readFileSync(path);
  const signature = image.subarray(0, 8).toString("hex");
  if (signature !== "89504e470d0a1a0a") {
    throw new Error("Expected a PNG image");
  }

  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idatChunks: Buffer[] = [];

  while (offset < image.length) {
    const length = image.readUInt32BE(offset);
    const type = image.subarray(offset + 4, offset + 8).toString("ascii");
    const data = image.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length;

    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data.readUInt8(8);
      colorType = data.readUInt8(9);
    }
    if (type === "IDAT") {
      idatChunks.push(Buffer.from(data));
    }
    if (type === "IEND") {
      break;
    }
  }

  if (bitDepth !== 8 || colorType !== 6) {
    throw new Error("Expected an 8-bit RGBA PNG");
  }

  const raw = inflateSync(Buffer.concat(idatChunks));
  const bytesPerPixel = 4;
  const stride = width * bytesPerPixel;
  const pixels = Buffer.alloc(height * stride);
  let rawOffset = 0;

  for (let y = 0; y < height; y += 1) {
    const filter = raw[rawOffset];
    rawOffset += 1;
    for (let x = 0; x < stride; x += 1) {
      const current = raw[rawOffset + x];
      const left = x >= bytesPerPixel ? pixels[y * stride + x - bytesPerPixel] : 0;
      const up = y > 0 ? pixels[(y - 1) * stride + x] : 0;
      const upLeft =
        y > 0 && x >= bytesPerPixel
          ? pixels[(y - 1) * stride + x - bytesPerPixel]
          : 0;
      let value = current;

      if (filter === 1) {
        value = current + left;
      } else if (filter === 2) {
        value = current + up;
      } else if (filter === 3) {
        value = current + Math.floor((left + up) / 2);
      } else if (filter === 4) {
        value = current + paeth(left, up, upLeft);
      } else if (filter !== 0) {
        throw new Error(`Unsupported PNG filter ${filter}`);
      }

      pixels[y * stride + x] = value & 0xff;
    }
    rawOffset += stride;
  }

  return { width, height, pixels };
}

function paeth(left: number, up: number, upLeft: number) {
  const estimate = left + up - upLeft;
  const leftDistance = Math.abs(estimate - left);
  const upDistance = Math.abs(estimate - up);
  const upLeftDistance = Math.abs(estimate - upLeft);

  if (leftDistance <= upDistance && leftDistance <= upLeftDistance) return left;
  if (upDistance <= upLeftDistance) return up;
  return upLeft;
}

function getAlphaAt(
  image: ReturnType<typeof readPngRgbaImage>,
  x: number,
  y: number,
) {
  return image.pixels[(y * image.width + x) * 4 + 3];
}

describe("GamesPage", () => {
  beforeEach(() => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classicRuleSet],
    });
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({
        id: "profile-1",
        display_name: "阿青",
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
    ]);
    gameClientMocks.listPlayerProfileFavorites.mockResolvedValue({
      profile_ids: ["profile-1"],
    });
    gameClientMocks.createGameRun.mockResolvedValue(buildRun());
    gameClientMocks.favoritePlayerProfile.mockImplementation((profileId: string) =>
      Promise.resolve({ profile_id: profileId, is_favorite: true }),
    );
    gameClientMocks.unfavoritePlayerProfile.mockImplementation((profileId: string) =>
      Promise.resolve({ profile_id: profileId, is_favorite: false }),
    );
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
    expect(heroWrapperRule).toContain("width: min(44%, 180px)");
    expect(heroWrapperRule).toContain("justify-self: start");
    expect(heroRule).toContain("width: 100%");
    expect(heroRule).toContain("height: auto");
    expect(heroRule).toContain("object-fit: contain");
    expect(heroRule).toContain("object-position: left center");
  });

  it("shows one current rule summary and changes rules in a modal picker", async () => {
    const user = userEvent.setup();
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classicRuleSet, starterRuleSet],
    });
    renderGamesPage();

    const summary = await screen.findByRole("region", { name: "当前规则" });
    expect(await within(summary).findByText("经典 8 人")).toBeVisible();
    expect(within(summary).getByText(/测试阵容/)).toBeVisible();
    expect(
      screen.queryByRole("group", { name: "规则选择指示" }),
    ).not.toBeInTheDocument();

    const changeRuleButton = within(summary).getByRole("button", {
      name: "更换规则",
    });
    await user.click(changeRuleButton);
    const picker = screen.getByRole("dialog", { name: "选择规则" });
    expect(picker).toHaveAttribute("aria-modal", "true");
    await user.click(
      within(picker).getByRole("button", { name: "选择规则 新手 6 人快局" }),
    );

    expect(
      screen.queryByRole("dialog", { name: "选择规则" }),
    ).not.toBeInTheDocument();
    expect(within(summary).getByText("新手 6 人快局")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "选择 6 号座位，当前为 待选择" }),
    ).toBeVisible();
    expect(changeRuleButton).toHaveFocus();
  });

  it("shrinks to exactly six seats and drops assignments outside the new rule", async () => {
    const user = userEvent.setup();
    const eightPlayerRuleSet = { ...classicRuleSet, player_count: 8 };
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [eightPlayerRuleSet, starterRuleSet],
    });
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 7 号座位，当前为 待选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 7 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认并下一位" }));
    await user.keyboard("{Escape}");
    expect(
      await screen.findByRole("button", {
        name: "选择 7 号座位，当前为 阿青",
      }),
    ).toBeVisible();

    const summary = screen.getByRole("region", { name: "当前规则" });
    await user.click(
      within(summary).getByRole("button", { name: "更换规则" }),
    );
    await user.click(
      screen.getByRole("button", { name: "选择规则 新手 6 人快局" }),
    );

    expect(
      screen.getByRole("button", { name: "选择 6 号座位，当前为 待选择" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /选择 7 号座位/ }),
    ).not.toBeInTheDocument();

    await user.click(
      within(summary).getByRole("button", { name: "更换规则" }),
    );
    await user.click(
      screen.getByRole("button", { name: "选择规则 经典 8 人" }),
    );
    expect(
      screen.getByRole("button", {
        name: "选择 7 号座位，当前为 待选择",
      }),
    ).toBeVisible();
  });

  it("presents known artwork and an unknown-rule fallback with modal focus behavior", async () => {
    const user = userEvent.setup();
    const unknownRuleSet: RuleSetSummary = {
      ...classicRuleSet,
      id: "custom_10",
      name: "自定义 10 人局",
      player_count: 10,
      role_summary: "3 狼人 / 7 好人",
      complexity: "自定义",
    };
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classicRuleSet, unknownRuleSet],
    });
    renderGamesPage();

    const summary = await screen.findByRole("region", { name: "当前规则" });
    await within(summary).findByText("经典 8 人");
    const changeRuleButton = within(summary).getByRole("button", {
      name: "更换规则",
    });
    await user.click(changeRuleButton);

    const picker = screen.getByRole("dialog", { name: "选择规则" });
    const selectedRule = within(picker).getByRole("button", {
      name: "选择规则 经典 8 人",
    });
    const unknownRule = within(picker).getByRole("button", {
      name: "选择规则 自定义 10 人局",
    });
    expect(selectedRule).toHaveAttribute("aria-pressed", "true");
    expect(selectedRule.querySelector("img")).toHaveAttribute(
      "src",
      expect.stringContaining("classic-8-selected"),
    );
    expect(unknownRule).toHaveAttribute("aria-pressed", "false");
    expect(unknownRule.querySelector("img")).not.toBeInTheDocument();
    expect(unknownRule).toHaveTextContent("自定义 10 人局");
    expect(unknownRule).toHaveTextContent("10 人");
    expect(unknownRule).toHaveTextContent("3 狼人 / 7 好人");
    await waitFor(() => expect(selectedRule).toHaveFocus());

    await user.click(
      within(picker).getByRole("button", { name: "关闭规则选择" }),
    );
    expect(changeRuleButton).toHaveFocus();

    await user.click(changeRuleButton);
    await user.click(
      screen.getByRole("button", { name: "选择规则 自定义 10 人局" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "选择规则" }),
    ).not.toBeInTheDocument();
    expect(changeRuleButton).toHaveFocus();
  });

  it("disables rule changes while a cached rule query refreshes", async () => {
    let resolveRefresh!: (value: { rule_sets: RuleSetSummary[] }) => void;
    const refreshResponse = new Promise<{ rule_sets: RuleSetSummary[] }>(
      (resolve) => {
        resolveRefresh = resolve;
      },
    );
    gameClientMocks.listRuleSets
      .mockResolvedValueOnce({ rule_sets: [classicRuleSet] })
      .mockReturnValueOnce(refreshResponse);
    const { queryClient } = renderGamesPage();

    const summary = await screen.findByRole("region", { name: "当前规则" });
    await within(summary).findByText("经典 8 人");
    const changeRuleButton = within(summary).getByRole("button", {
      name: "更换规则",
    });
    let refreshPromise!: Promise<void>;
    act(() => {
      refreshPromise = queryClient.refetchQueries({ queryKey: ["rule-sets"] });
    });

    try {
      await waitFor(() => expect(changeRuleButton).toBeDisabled());
    } finally {
      resolveRefresh({ rule_sets: [classicRuleSet] });
      await act(async () => {
        await refreshPromise;
      });
    }
    await waitFor(() => expect(changeRuleButton).toBeEnabled());
  });

  it("retries a failed rule query from the summary", async () => {
    const user = userEvent.setup();
    gameClientMocks.listRuleSets
      .mockRejectedValueOnce(new Error("rules unavailable"))
      .mockResolvedValueOnce({ rule_sets: [starterRuleSet] });
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", { name: "重新加载规则" }),
    );

    expect(await screen.findByText("新手 6 人快局")).toBeVisible();
    expect(gameClientMocks.listRuleSets).toHaveBeenCalledTimes(2);
  });

  it("disables the retry action while the rule query refetches", async () => {
    const user = userEvent.setup();
    let resolveRetry!: (value: { rule_sets: RuleSetSummary[] }) => void;
    const retryResponse = new Promise<{ rule_sets: RuleSetSummary[] }>(
      (resolve) => {
        resolveRetry = resolve;
      },
    );
    gameClientMocks.listRuleSets
      .mockRejectedValueOnce(new Error("rules unavailable"))
      .mockReturnValueOnce(retryResponse);
    renderGamesPage();

    const retryButton = await screen.findByRole("button", {
      name: "重新加载规则",
    });
    await user.click(retryButton);

    try {
      expect(retryButton).toBeDisabled();
    } finally {
      resolveRetry({ rule_sets: [starterRuleSet] });
      await screen.findByText("新手 6 人快局");
    }
  });

  it("lets the twelve-seat lobby scroll clear of the fixed action bar", async () => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classic12RuleSet],
    });
    renderGamesPage();

    expect(
      await screen.findByRole("button", {
        name: "选择 12 号座位，当前为 待选择",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("高级设置 · 随机种子 / 8轮")).toBeVisible();

    const styles = readFileSync("src/styles/index.css", "utf8");
    const lobbyContentRegionRule =
      styles.match(
        /\.mobile-app-shell:has\(\.mobile-lobby-page\) \.mobile-content-region\s*{[^}]+}/,
      )?.[0] ?? "";
    const lobbyPageRule =
      styles.match(/(?:^|\n)\.mobile-lobby-page\s*{[^}]+}/)?.[0] ?? "";
    expect(lobbyContentRegionRule).toContain("overflow-y: auto");
    expect(lobbyContentRegionRule).not.toContain("overflow: hidden");
    expect(lobbyPageRule).toContain("min-height: 100%");
    expect(lobbyPageRule).not.toContain("\n  height: 100%;");
    expect(lobbyPageRule).not.toContain("max-height: 100%");
    expect(lobbyPageRule).not.toContain("overflow: hidden");
    expect(lobbyPageRule).toContain(
      "padding: 10px var(--mobile-page-padding-inline) calc(var(--mobile-tab-frame-height) + 156px + env(safe-area-inset-bottom))",
    );
  });

  it("uses a lower-contrast panel for the lineup", async () => {
    renderGamesPage();

    const headingNames = ["组建阵容"];

    for (const headingName of headingNames) {
      const heading = await screen.findByRole("heading", { name: headingName });
      const section = heading.closest("section");
      const headingRow = heading.closest(".mobile-lobby-section-heading");

      expect(section).toHaveClass("mobile-lobby-board-section");
      expect(headingRow).toHaveClass("mobile-lobby-section-heading");
    }

    const styles = readFileSync("src/styles/index.css", "utf8");
    const boardTitleRule =
      styles.match(
        /\.mobile-lobby-board-section\s+\.mobile-lobby-section-heading\s+h2\s*{[^}]+}/,
      )?.[0] ?? "";
    const lineupRule =
      styles.match(/\.mobile-lobby-lineup-section\s*{[^}]+}/)?.[0] ?? "";

    expect(boardTitleRule).not.toContain("background-image");
    expect(boardTitleRule).toContain("font-size: 14px");
    expect(lineupRule).toContain("padding: 12px");
    expect(lineupRule).toContain("border-radius: 12px");
    expect(lineupRule).toContain("background: rgb(5 10 16 / 78%)");
  });

  it("keeps lobby settings labels and inputs on the same row", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(await screen.findByText("高级设置 · 随机种子 / 8轮"));
    expect(await screen.findByLabelText("种子")).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "最大轮数" })).toBeVisible();

    const styles = readFileSync("src/styles/index.css", "utf8");
    const fieldRule =
      styles.match(/\.mobile-lobby-field\s*{[^}]+}/)?.[0] ?? "";
    const fieldInputRule =
      styles.match(/\.mobile-lobby-field\s+input\s*{[^}]+}/)?.[0] ?? "";
    expect(fieldRule).toContain("grid-template-columns: max-content minmax(0, 1fr)");
    expect(fieldRule).toContain("align-items: center");
    expect(fieldRule).toContain("gap: 8px");
    expect(fieldRule).not.toContain("background-image");
    expect(fieldRule).toContain("border: 1px solid");
    expect(fieldRule).toContain("background: rgb(8 15 23 / 88%)");
    expect(fieldRule).toContain("min-height: 44px");
    expect(fieldInputRule).toContain("width: 100%");
    expect(fieldInputRule).toContain("min-height: 28px");
  });

  it("shows launch progress beside the numbered lineup", async () => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classic12RuleSet],
    });
    renderGamesPage();

    const ruleSummary = await screen.findByRole("region", { name: "当前规则" });
    expect(within(ruleSummary).queryByText("12 人局")).not.toBeInTheDocument();

    const lineup = await screen.findByRole("region", { name: "组建阵容" });
    const seatSummary = await within(lineup).findByText(/已选 0\/12/);
    expect(seatSummary).toHaveClass("mobile-lobby-seat-summary");

    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatSummaryRule =
      styles.match(
        /\.mobile-lobby-section-heading\s+\.mobile-lobby-seat-summary\s*{[^}]+}/,
      )?.[0] ?? "";
    const boardTitleRule =
      styles.match(
        /\.mobile-lobby-board-section\s+\.mobile-lobby-section-heading\s+h2\s*{[^}]+}/,
      )?.[0] ?? "";

    expect(seatSummaryRule).not.toContain("background-image");
    expect(seatSummaryRule).toContain("border-radius: 999px");
    expect(seatSummaryRule).toContain("flex: 0 1 160px");
    expect(seatSummaryRule).toContain("min-height: 28px");
    expect(seatSummaryRule).toContain("font-size: 12px");
    expect(boardTitleRule).toContain("font-size: 14px");
  });

  it("shows visible two-digit numbers and empty-state copy in seat cards", async () => {
    renderGamesPage();

    const seatButton = await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    });
    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatCardTextRule =
      styles.match(/\.mobile-lobby-seat-card\s+strong\s*{[^}]+}/)?.[0] ?? "";

    expect(within(seatButton).getByText("01")).toBeVisible();
    expect(within(seatButton).getByText("待选择")).toBeVisible();
    expect(seatButton.querySelector(".mobile-lobby-seat-avatar")).toBeNull();
    expect(seatCardTextRule).toContain("font-weight: 800");
  });

  it("fills from the lineup section before creating", async () => {
    const user = userEvent.setup();
    const { router } = renderGamesPage();

    expect(
      screen.queryByRole("button", { name: "随机补齐" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "收藏补齐" }),
    ).not.toBeInTheDocument();
    const lineup = await screen.findByRole("region", { name: "组建阵容" });
    expect(within(lineup).getByRole("button", { name: "智能补齐" })).toBeVisible();
    expect(
      within(lineup).getByRole("button", { name: "阵容更多操作" }),
    ).toBeVisible();

    await within(lineup).findByText("已选 0/2 · 可自动补齐");
    const disabledLaunchButton = screen.getByRole("button", {
      name: "还差 2 位",
    });
    expect(disabledLaunchButton).toBeDisabled();
    expect(disabledLaunchButton).toHaveClass("mobile-lobby-launch-button");

    await user.click(within(lineup).getByRole("button", { name: "智能补齐" }));
    const fillMenu = within(lineup).getByRole("group", { name: "智能补齐方式" });

    await user.click(within(fillMenu).getByRole("button", { name: "随机补齐" }));

    expect(
      await within(lineup).findByText("已选 2/2 · 阵容已就绪"),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "随机补齐" }),
    ).not.toBeInTheDocument();
    const readyLaunchButton = screen.getByRole("button", { name: "开始对局" });
    expect(readyLaunchButton).toBeEnabled();
    expect(readyLaunchButton).toHaveClass("mobile-lobby-launch-button");
    expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();

    await user.click(readyLaunchButton);

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
    await user.click(screen.getByRole("button", { name: "确认并下一位" }));
    await user.keyboard("{Escape}");
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 阿青",
      }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "阵容更多操作" }));
    await user.click(screen.getByRole("button", { name: "清空阵容" }));
    expect(screen.getByRole("button", { name: "确认清空阵容" })).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 阿青",
      }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "确认清空阵容" }));
    expect(
      screen.getByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    ).toBeVisible();
  });

  it("disables lineup actions while game creation is pending", async () => {
    const user = userEvent.setup();
    gameClientMocks.createGameRun.mockReturnValue(
      new Promise(() => undefined),
    );
    renderGamesPage();

    await user.click(await screen.findByRole("button", { name: "智能补齐" }));
    await user.click(screen.getByRole("button", { name: "随机补齐" }));
    await user.click(screen.getByText("高级设置 · 随机种子 / 8轮"));
    await user.click(screen.getByRole("button", { name: "开始对局" }));

    expect(screen.getByRole("button", { name: "发起中…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "更换规则" })).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: "种子" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "阵容更多操作" }),
    ).toBeDisabled();
  });

  it("blocks creation when the player library cannot fill the selected rule set", async () => {
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({ id: "profile-1", display_name: "阿青" }),
    ]);
    renderGamesPage();
    const lineup = await screen.findByRole("region", { name: "组建阵容" });

    expect(
      screen.queryByRole("button", { name: "随机补齐" }),
    ).not.toBeInTheDocument();
    expect(
      await within(lineup).findByText("已选 0/2 · 还差 1 名玩家"),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "还差 2 位" })).toBeDisabled();
    expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();
  });

  it("disables launch until empty seats are completed from the library", async () => {
    renderGamesPage();
    const lineup = await screen.findByRole("region", { name: "组建阵容" });

    expect(
      await within(lineup).findByText("已选 0/2 · 可自动补齐"),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "还差 2 位" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "还差 2 位" })).toHaveClass(
      "mobile-lobby-launch-button",
    );
  });

  it("shows a confirm launch state when every seat has a player", async () => {
    const user = userEvent.setup();
    renderGamesPage();
    const lineup = await screen.findByRole("region", { name: "组建阵容" });

    await user.click(await screen.findByRole("button", { name: "智能补齐" }));
    await user.click(screen.getByRole("button", { name: "随机补齐" }));

    expect(
      await within(lineup).findByText("已选 2/2 · 阵容已就绪"),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "开始对局" })).toHaveClass(
      "mobile-lobby-launch-button",
    );
  });

  it("blocks launch before submit when the player library cannot fill the lineup", async () => {
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({ id: "profile-1", display_name: "阿青" }),
    ]);
    renderGamesPage();
    const lineup = await screen.findByRole("region", { name: "组建阵容" });

    expect(
      await within(lineup).findByText("已选 0/2 · 还差 1 名玩家"),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "还差 2 位" })).toBeDisabled();
    expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();
  });

  it("opens the full-screen modal player picker from a selected seat", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );

    const dialog = screen.getByRole("dialog", { name: "玩家卡牌库" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent("当前选择：1号座位");
    expect(document.querySelector(".mobile-lobby-content")).toHaveAttribute("inert");
    await waitFor(() => {
      expect(screen.getByRole("searchbox", { name: "搜索玩家" })).toHaveFocus();
    });
    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    ).toBeVisible();
    expect(dialog).toHaveClass("mobile-profile-picker");
  });


  it("toggles a player favorite from a compact card-corner button without selecting the card", async () => {
    const user = userEvent.setup();
    let favoriteIds = ["profile-1"];
    gameClientMocks.listPlayerProfileFavorites.mockImplementation(() =>
      Promise.resolve({ profile_ids: [...favoriteIds] }),
    );
    gameClientMocks.favoritePlayerProfile.mockImplementation((profileId: string) => {
      favoriteIds = [...favoriteIds, profileId];
      return Promise.resolve({ profile_id: profileId, is_favorite: true });
    });
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );

    const favoriteButton = screen.getByRole("button", { name: "收藏 白石" });
    const inactiveFavoriteIcon = favoriteButton.querySelector(
      ".mobile-profile-row-favorite-icon",
    );

    expect(inactiveFavoriteIcon?.tagName.toLowerCase()).toBe("svg");
    expect(inactiveFavoriteIcon).toHaveClass("lucide");
    expect(inactiveFavoriteIcon).toHaveClass("lucide-star");
    expect(inactiveFavoriteIcon).toHaveAttribute("aria-hidden", "true");
    expect(favoriteButton).toHaveAttribute("aria-pressed", "false");
    await user.click(favoriteButton);

    await waitFor(() => {
      expect(gameClientMocks.favoritePlayerProfile).toHaveBeenCalledWith("profile-2");
    });
    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 白石" }),
    ).toHaveAttribute("aria-pressed", "false");
    const activeFavoriteButton = await screen.findByRole("button", {
      name: "取消收藏 白石",
    });
    const activeFavoriteIcon = activeFavoriteButton.querySelector(
      ".mobile-profile-row-favorite-icon",
    );
    expect(activeFavoriteIcon?.tagName.toLowerCase()).toBe("svg");
    expect(activeFavoriteIcon).toHaveClass("lucide");
    expect(activeFavoriteIcon).toHaveClass("lucide-star-check");
    expect(activeFavoriteButton).toHaveAttribute("aria-pressed", "true");
    expect(activeFavoriteButton).toHaveFocus();
    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 白石" }),
    ).not.toHaveFocus();
    expect(
      within(screen.getByRole("dialog", { name: "玩家卡牌库" }))
        .getAllByRole("button")
        .filter((button) =>
          button.getAttribute("aria-label")?.startsWith("为 1 号座位候选"),
        )
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(["为 1 号座位候选 阿青", "为 1 号座位候选 白石"]);
    await waitFor(() => {
      expect(gameClientMocks.listPlayerProfileFavorites).toHaveBeenCalledTimes(2);
    });
    expect(gameClientMocks.listPublicPlayerProfiles).toHaveBeenCalledTimes(1);
  });

  it("keeps unrelated favorite buttons enabled while one favorite update is pending", async () => {
    const user = userEvent.setup();
    gameClientMocks.favoritePlayerProfile.mockImplementation(
      () => new Promise(() => undefined),
    );
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );

    await user.click(screen.getByRole("button", { name: "收藏 白石" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "取消收藏 白石" })).toBeDisabled();
    });
    expect(
      screen.getByRole("button", { name: "取消收藏 阿青" }),
    ).not.toBeDisabled();
  });

  it("keeps the catalog usable but makes favorite controls read-only when favorites fail", async () => {
    const user = userEvent.setup();
    gameClientMocks.listPlayerProfileFavorites.mockRejectedValue(
      new Error("guest session unavailable"),
    );
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );

    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    ).toBeEnabled();
    expect(screen.getByRole("status")).toHaveTextContent("收藏状态暂不可用");
    expect(screen.getByRole("button", { name: "收藏 阿青" })).toBeDisabled();
    await user.click(
      screen.getByRole("button", {
        name: "筛选玩家，当前 全部玩家、全部策略",
      }),
    );
    expect(
      screen.getByRole("button", { name: "收藏筛选，当前 全部玩家" }),
    ).toBeDisabled();
    expect(gameClientMocks.listPublicPlayerProfiles).toHaveBeenCalledTimes(1);
  });

  it("rolls back an optimistic favorite and shows a light error", async () => {
    const user = userEvent.setup();
    gameClientMocks.favoritePlayerProfile.mockRejectedValue(new Error("write failed"));
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(screen.getByRole("button", { name: "收藏 白石" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("收藏更新失败");
    });
    expect(screen.getByRole("button", { name: "收藏 白石" })).toBeEnabled();
  });

  it("replaces stale favorite ids with the authoritative list after session recovery", async () => {
    const user = userEvent.setup();
    let favoriteReadCount = 0;
    gameClientMocks.listPlayerProfileFavorites.mockImplementation(() => {
      favoriteReadCount += 1;
      return Promise.resolve({
        profile_ids: favoriteReadCount === 1 ? ["profile-1"] : ["profile-2"],
      });
    });
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    await user.click(screen.getByRole("button", { name: "收藏 白石" }));

    await waitFor(() => {
      expect(gameClientMocks.listPlayerProfileFavorites).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByRole("button", { name: "收藏 阿青" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "取消收藏 白石" })).toBeEnabled();
    expect(gameClientMocks.listPublicPlayerProfiles).toHaveBeenCalledTimes(1);
  });

  it("refreshes the player drawer order with a pull-down gesture", async () => {
    const user = userEvent.setup();
    const alpha = buildProfile({
      id: "profile-1",
      display_name: "阿青",
    });
    const whiteStone = buildProfile({
      id: "profile-2",
      display_name: "白石",
    });
    let serverProfiles = [alpha, whiteStone];
    let serverFavoriteIds = ["profile-1"];
    gameClientMocks.listPublicPlayerProfiles.mockImplementation(() =>
      Promise.resolve(serverProfiles),
    );
    gameClientMocks.listPlayerProfileFavorites.mockImplementation(() =>
      Promise.resolve({ profile_ids: serverFavoriteIds }),
    );
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );
    const drawer = screen.getByRole("dialog", { name: "玩家卡牌库" });
    expect(
      within(drawer)
        .getAllByRole("button")
        .filter((button) =>
          button.getAttribute("aria-label")?.startsWith("为 1 号座位候选"),
        )
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(["为 1 号座位候选 阿青", "为 1 号座位候选 白石"]);

    serverProfiles = [whiteStone, alpha];
    serverFavoriteIds = ["profile-2"];
    const scrollRegion = drawer.querySelector(".mobile-profile-picker-list");
    const refreshStatus = drawer.querySelector(".mobile-profile-refresh-status");

    expect(scrollRegion).toBeInstanceOf(HTMLElement);
    expect(refreshStatus).toBeInTheDocument();
    fireEvent.touchStart(scrollRegion as HTMLElement, {
      touches: [{ clientY: 12 }],
    });
    fireEvent.touchMove(scrollRegion as HTMLElement, {
      touches: [{ clientY: 92 }],
    });
    expect(refreshStatus).toHaveTextContent("松开刷新玩家");
    fireEvent.touchEnd(scrollRegion as HTMLElement);

    await waitFor(() => {
      expect(gameClientMocks.listPublicPlayerProfiles).toHaveBeenCalledTimes(2);
      expect(gameClientMocks.listPlayerProfileFavorites).toHaveBeenCalledTimes(2);
    });
    expect(
      within(drawer)
        .getAllByRole("button")
        .filter((button) =>
          button.getAttribute("aria-label")?.startsWith("为 1 号座位候选"),
        )
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(["为 1 号座位候选 白石", "为 1 号座位候选 阿青"]);
    expect(screen.getByRole("button", { name: "取消收藏 白石" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "收藏 阿青" })).toBeEnabled();
  });


  it("renders player card drawer avatars through API asset URLs", async () => {
    const user = userEvent.setup();
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({
        id: "profile-1",
        display_name: "阿青",
        avatar_image_url:
          "/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
      }),
      buildProfile({
        id: "profile-2",
        display_name: "白石",
      }),
    ]);
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );

    const drawer = await screen.findByRole("dialog", { name: "玩家卡牌库" });
    const avatar = drawer.querySelector(".mobile-profile-row-select img");
    expect(avatar).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
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
      styles.match(/\.mobile-lobby-launch-bar\s*{[^}]+}/)?.[0] ?? "";
    const actionBarBackground = readPngRgbaImage(
      "src/assets/lobby-action-bar-bg.png",
    );

    expect(seatGridRule).toContain("grid-template-columns: repeat(4");
    expect(seatGridRule).toContain("grid-template-rows: repeat(2");
    expect(seatCardRule).toContain("aspect-ratio: 1");
    expect(seatCardRule).toContain("min-height: 0");
    expect(actionBarRule).toContain("grid-template-columns: minmax(0, 1fr)");
    expect(actionBarRule).toContain("lobby-action-bar-bg.png");
    expect(readPngMetadata("src/assets/lobby-action-bar-bg.png")).toEqual({
      width: 1146,
      height: 244,
      colorType: 6,
    });
    expect(getAlphaAt(actionBarBackground, 0, 0)).toBe(0);
    expect(
      getAlphaAt(
        actionBarBackground,
        Math.floor(actionBarBackground.width / 2),
        Math.floor(actionBarBackground.height / 2),
      ),
    ).toBe(255);
  });

  it("searches profiles when a profile has no tags", async () => {
    const user = userEvent.setup();
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({
        id: "profile-1",
        display_name: "无标签玩家",
        model: "tagless-model",
        tags: undefined as unknown as string[],
      }),
    ]);
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

  it("confirms through empty seats and closes only after completing the lineup", async () => {
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

    const picker = screen.getByRole("dialog", { name: "玩家卡牌库" });
    expect(within(picker).getByText(/当前选择：2号座位/)).toBeVisible();
    await waitFor(() => {
      expect(screen.getByRole("searchbox", { name: "搜索玩家" })).toHaveFocus();
    });

    await user.click(
      within(picker).getByRole("button", { name: "为 2 号座位候选 白石" }),
    );
    await user.click(within(picker).getByRole("button", { name: "完成阵容" }));

    expect(
      screen.queryByRole("dialog", { name: "玩家卡牌库" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "选择 1 号座位，当前为 阿青" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "选择 2 号座位，当前为 白石" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "开始对局" })).toBeEnabled();
  });

  it("moves an occupied profile and continues with the next empty seat", async () => {
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
    await user.click(
      screen.getByRole("button", {
        name: "为 2 号座位候选 阿青，已在 1 号座位",
      }),
    );

    expect(
      screen.getByRole("button", { name: "移动到 2 号座位" }),
    ).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "移动到 2 号座位" }));
    await user.keyboard("{Escape}");

    expect(
      screen.getByRole("button", { name: "选择 1 号座位，当前为 待选择" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "选择 2 号座位，当前为 阿青" }),
    ).toBeVisible();
  });

  it("renders a confirmed player in the active seat", async () => {
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
    await user.keyboard("{Escape}");

    const filledSeat = screen.getByRole("button", {
      name: "选择 1 号座位，当前为 阿青",
    });
    expect(filledSeat).toHaveClass("mobile-lobby-seat-card-filled");
    expect(filledSeat.querySelector(".mobile-lobby-seat-avatar")).not.toBeNull();

    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatCardRule =
      styles.match(/\.mobile-lobby-seat-card\s*{[^}]+}/)?.[0] ?? "";
    expect(seatCardRule).not.toContain("background-image");
    expect(seatCardRule).toContain("background: linear-gradient");
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
    await user.click(screen.getByRole("button", { name: "确认并下一位" }));

    expect(screen.getByText("已在 1 号座位")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "为 2 号座位候选 阿青，已在 1 号座位" }),
    );
    expect(screen.getByRole("button", { name: "移动到 2 号座位" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "移动到 2 号座位" }));

    await user.keyboard("{Escape}");
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



  it("opens player picker filters in a bottom sheet and applies the selected option", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 待选择",
      }),
    );

    await user.click(
      screen.getByRole("button", {
        name: "筛选玩家，当前 全部玩家、全部策略",
      }),
    );

    const favoriteTrigger = screen.getByRole("button", {
      name: "收藏筛选，当前 全部玩家",
    });
    await user.click(favoriteTrigger);

    expect(document.querySelector(".mobile-bottom-select-picker-popup")).toBeInTheDocument();
    expect(screen.getByText("选择收藏筛选")).toBeVisible();
    expect(favoriteTrigger).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: "当前选择的是：全部玩家" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "选择下一项：只看收藏" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "选择下一项：只看收藏" }),
    );
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "当前选择的是：只看收藏" }),
      ).toBeInTheDocument();
    });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    fireEvent.click(screen.getAllByRole("button", { name: "确定" }).at(-1)!);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "收藏筛选，当前 只看收藏" }),
      ).toHaveAttribute("aria-expanded", "false");
    });

    await user.click(
      screen.getByRole("button", { name: "策略筛选，当前 全部策略" }),
    );
    expect(screen.getByText("选择策略筛选")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "当前选择的是：全部策略" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "选择下一项：分析型" }));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "当前选择的是：分析型" }),
      ).toBeInTheDocument();
    });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    fireEvent.click(screen.getAllByRole("button", { name: "确定" }).at(-1)!);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "策略筛选，当前 分析型" }),
      ).toBeVisible();
    });
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
    await user.click(screen.getByRole("button", { name: "确认并下一位" }));
    await user.keyboard("{Escape}");

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
        { name: "确认并下一位" },
      ),
    ).toBeEnabled();

    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({
        id: "profile-2",
        display_name: "白石",
        short_description: "稳健守序的观察者",
        strategy_profile: "balanced",
        tags: ["均衡"],
      }),
    ]);
    await act(async () => {
      await queryClient.invalidateQueries({
        queryKey: ["public-player-profiles"],
      });
    });

    const drawer = screen.getByRole("dialog", { name: "玩家卡牌库" });
    await waitFor(() => {
      expect(
        within(drawer).getByText("候选已失效，请重新选择"),
      ).toBeVisible();
    });
    expect(
      within(drawer).getByRole("button", { name: "请选择玩家" }),
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
