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

function getRgbaAt(
  image: ReturnType<typeof readPngRgbaImage>,
  x: number,
  y: number,
) {
  const offset = (y * image.width + x) * 4;

  return {
    alpha: image.pixels[offset + 3],
    blue: image.pixels[offset + 2],
    green: image.pixels[offset + 1],
    red: image.pixels[offset],
  };
}

function getAlphaRunWidthAtRow(
  image: ReturnType<typeof readPngRgbaImage>,
  y: number,
  x: number,
  minAlpha: number,
) {
  let left = x;
  while (left > 0 && getAlphaAt(image, left - 1, y) > minAlpha) {
    left -= 1;
  }

  let right = x;
  while (right < image.width - 1 && getAlphaAt(image, right + 1, y) > minAlpha) {
    right += 1;
  }

  return right - left + 1;
}

function getOpaqueLuminancePercentile(
  image: ReturnType<typeof readPngRgbaImage>,
  percentile: number,
) {
  const luminanceValues: number[] = [];

  for (let offset = 0; offset < image.pixels.length; offset += 4) {
    if (image.pixels[offset + 3] <= 200) continue;

    luminanceValues.push(
      0.2126 * image.pixels[offset] +
        0.7152 * image.pixels[offset + 1] +
        0.0722 * image.pixels[offset + 2],
    );
  }

  luminanceValues.sort((left, right) => left - right);

  return luminanceValues[
    Math.min(
      luminanceValues.length - 1,
      Math.max(0, Math.floor(luminanceValues.length * percentile)),
    )
  ];
}

function countOpaquePixelsAboveLuminance(
  image: ReturnType<typeof readPngRgbaImage>,
  minLuminance: number,
) {
  let count = 0;

  for (let offset = 0; offset < image.pixels.length; offset += 4) {
    if (image.pixels[offset + 3] <= 200) continue;

    const luminance =
      0.2126 * image.pixels[offset] +
      0.7152 * image.pixels[offset + 1] +
      0.0722 * image.pixels[offset + 2];

    if (luminance >= minLuminance) count += 1;
  }

  return count;
}

function getLargestCentralGoldComponentBounds(
  image: ReturnType<typeof readPngRgbaImage>,
) {
  const left = 45;
  const top = 45;
  const right = image.width - 45;
  const bottom = image.height - 45;
  const width = right - left;
  const height = bottom - top;
  const mask = new Uint8Array(width * height);
  const seen = new Uint8Array(width * height);

  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      const { alpha, blue, green, red } = getRgbaAt(image, x, y);
      const luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;

      if (
        alpha > 200 &&
        red > 115 &&
        green > 65 &&
        blue < 95 &&
        red > green * 1.08 &&
        luminance > 90
      ) {
        mask[(y - top) * width + (x - left)] = 1;
      }
    }
  }

  let largest = {
    bottom: -1,
    left: width,
    pixelCount: 0,
    right: -1,
    top: height,
  };
  const queue: number[] = [];

  for (let startIndex = 0; startIndex < mask.length; startIndex += 1) {
    if (mask[startIndex] === 0 || seen[startIndex] === 1) continue;

    let head = 0;
    let componentLeft = width;
    let componentTop = height;
    let componentRight = -1;
    let componentBottom = -1;
    let pixelCount = 0;
    queue.length = 0;
    queue.push(startIndex);
    seen[startIndex] = 1;

    while (head < queue.length) {
      const index = queue[head];
      head += 1;
      const localX = index % width;
      const localY = Math.floor(index / width);

      componentLeft = Math.min(componentLeft, localX);
      componentTop = Math.min(componentTop, localY);
      componentRight = Math.max(componentRight, localX);
      componentBottom = Math.max(componentBottom, localY);
      pixelCount += 1;

      for (let neighborY = localY - 1; neighborY <= localY + 1; neighborY += 1) {
        for (
          let neighborX = localX - 1;
          neighborX <= localX + 1;
          neighborX += 1
        ) {
          if (
            neighborX < 0 ||
            neighborX >= width ||
            neighborY < 0 ||
            neighborY >= height
          ) {
            continue;
          }

          const neighborIndex = neighborY * width + neighborX;
          if (mask[neighborIndex] === 0 || seen[neighborIndex] === 1) {
            continue;
          }

          seen[neighborIndex] = 1;
          queue.push(neighborIndex);
        }
      }
    }

    if (pixelCount > largest.pixelCount) {
      largest = {
        bottom: componentBottom + top,
        left: componentLeft + left,
        pixelCount,
        right: componentRight + left,
        top: componentTop + top,
      };
    }
  }

  return largest;
}

function countPixelsAboveAlpha(
  image: ReturnType<typeof readPngRgbaImage>,
  left: number,
  top: number,
  right: number,
  bottom: number,
  alpha: number,
) {
  let count = 0;

  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      if (getAlphaAt(image, x, y) > alpha) {
        count += 1;
      }
    }
  }

  return count;
}

function getAlphaBounds(
  image: ReturnType<typeof readPngRgbaImage>,
  minAlpha = 0,
) {
  let left = image.width;
  let top = image.height;
  let right = -1;
  let bottom = -1;

  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      if (getAlphaAt(image, x, y) <= minAlpha) {
        continue;
      }

      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x);
      bottom = Math.max(bottom, y);
    }
  }

  return { bottom, left, right, top };
}

function expectLobbyButtonBackgroundAssets() {
  const styles = readFileSync("src/styles/index.css", "utf8");
  const actionButtonRule =
    styles.match(
      /\.mobile-lobby-action-bar\s+\.mobile-button\s*{[^}]+}/,
    )?.[0] ?? "";
  const actionButtonTextRule =
    styles.match(
      /\.mobile-lobby-action-bar\s+\.mobile-button\s+>\s+span\s*{[^}]+}/,
    )?.[0] ?? "";
  const buttonAssets = [
    [".mobile-lobby-favorite-fill", "button-favorite-fill.png"],
    [
      ".mobile-lobby-favorite-fill:disabled",
      "button-favorite-fill-disabled.png",
    ],
    [".mobile-lobby-clear-seats", "button-clear-seats.png"],
    [".mobile-lobby-clear-seats:disabled", "button-clear-disabled.png"],
    [".mobile-lobby-clear-confirming", "button-clear-confirm.png"],
    [".mobile-lobby-random-fill", "button-launch-autofill.png"],
    [".mobile-lobby-launch-ready", "button-launch-ready.png"],
    [".mobile-lobby-launch-shortage", "button-launch-shortage.png"],
    [".mobile-lobby-launch-pending", "button-launch-pending.png"],
  ];
  const expectedBoundsByAlpha = new Map<number, ReturnType<typeof getAlphaBounds>>();

  expect(actionButtonRule).toContain("width: 100%");
  expect(actionButtonRule).toContain("height: 42px");
  expect(actionButtonTextRule).toContain("display: block");

  for (const [selector, assetName] of buttonAssets) {
    expect(styles).toContain(selector);
    expect(styles).toContain(`lobby-buttons/${assetName}`);
    expect(readPngMetadata(`src/assets/lobby-buttons/${assetName}`)).toEqual({
      width: 480,
      height: 180,
      colorType: 6,
    });

    const image = readPngRgbaImage(`src/assets/lobby-buttons/${assetName}`);
    for (const minAlpha of [0, 16, 64, 128]) {
      const bounds = getAlphaBounds(image, minAlpha);
      const expectedBounds = expectedBoundsByAlpha.get(minAlpha);

      if (expectedBounds) {
        expect(bounds).toEqual(expectedBounds);
      } else {
        expectedBoundsByAlpha.set(minAlpha, bounds);
      }

      expect(bounds.left).toBeLessThanOrEqual(18);
      expect(image.width - 1 - bounds.right).toBeLessThanOrEqual(18);
      expect(bounds.top).toBe(image.height - 1 - bounds.bottom);
      expect(bounds.top).toBeGreaterThanOrEqual(12);
    }

    const highAlphaBounds = getAlphaBounds(image, 200);
    expect(highAlphaBounds.top).toBeGreaterThanOrEqual(12);
    expect(image.height - 1 - highAlphaBounds.bottom).toBeGreaterThanOrEqual(
      12,
    );
    expect(
      countPixelsAboveAlpha(image, 210, 134, 270, image.height - 12, 200),
    ).toBeGreaterThan(240);
  }

  const randomFillRule =
    styles.match(
      /\.mobile-lobby-action-bar\s+\.mobile-lobby-random-fill\s*{[^}]+}/,
    )?.[0] ?? "";
  expect(randomFillRule).toContain("color: #fff7d6");
  expect(randomFillRule).toContain("0 2px 2px rgb(0 0 0 / 92%)");
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
    expect(heroWrapperRule).toContain("width: min(54%, 230px)");
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
      screen.getByRole("button", { name: "选择 6 号座位，当前为 请选择" }),
    ).toBeVisible();
    expect(changeRuleButton).toHaveFocus();
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
        name: "选择 12 号座位，当前为 请选择",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "填充设置" }),
    ).toBeInTheDocument();

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
      "padding: 10px var(--mobile-page-padding-inline) calc(var(--mobile-tab-frame-height) + 128px + env(safe-area-inset-bottom))",
    );
  });

  it("adds gothic board backgrounds behind the lineup and settings headings", async () => {
    renderGamesPage();

    const headingNames = ["组建阵容", "填充设置"];

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

    expect(boardTitleRule).toContain("lobby-section-title-board.png");
    expect(boardTitleRule).toContain("background-size: 100% 100%");
    expect(boardTitleRule).toContain("min-height: 42px");
    expect(readPngMetadata("src/assets/lobby-section-title-board.png")).toEqual({
      width: 512,
      height: 156,
      colorType: 6,
    });

    const boardImage = readPngRgbaImage(
      "src/assets/lobby-section-title-board.png",
    );
    const alphaBounds = getAlphaBounds(boardImage);
    expect(getAlphaAt(boardImage, 4, 4)).toBe(0);
    expect(getAlphaAt(boardImage, 256, Math.floor(boardImage.height / 2))).toBe(
      255,
    );
    expect(alphaBounds.top).toBe(10);
    expect(boardImage.height - 1 - alphaBounds.bottom).toBe(10);
  });

  it("keeps lobby settings labels and inputs on the same row", async () => {
    renderGamesPage();

    expect(await screen.findByLabelText("种子")).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "最大轮数" })).toBeVisible();

    const styles = readFileSync("src/styles/index.css", "utf8");
    const fieldRule =
      styles.match(/\.mobile-lobby-field\s*{[^}]+}/)?.[0] ?? "";
    const fieldInputRule =
      styles.match(/\.mobile-lobby-field\s+input\s*{[^}]+}/)?.[0] ?? "";
    const fieldBackground = readPngRgbaImage(
      "src/assets/lobby-settings-field-bg.png",
    );

    expect(fieldRule).toContain("grid-template-columns: max-content minmax(0, 1fr)");
    expect(fieldRule).toContain("align-items: center");
    expect(fieldRule).toContain("gap: 8px");
    expect(fieldRule).toContain("lobby-settings-field-bg.png");
    expect(fieldRule).toContain("background-size: 100% 100%");
    expect(fieldRule).toContain("border: 0");
    expect(fieldRule).toContain("min-height: 44px");
    expect(fieldInputRule).toContain("width: 100%");
    expect(fieldInputRule).toContain("min-height: 28px");
    expect(readPngMetadata("src/assets/lobby-settings-field-bg.png")).toEqual({
      width: 336,
      height: 88,
      colorType: 6,
    });
    expect(getAlphaAt(fieldBackground, 0, 0)).toBe(0);
    expect(
      getAlphaAt(
        fieldBackground,
        Math.floor(fieldBackground.width / 2),
        Math.floor(fieldBackground.height / 2),
      ),
    ).toBe(255);
  });

  it("removes the rule count badge and frames the seat summary with the wide board", async () => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classic12RuleSet],
    });
    renderGamesPage();

    const ruleSummary = await screen.findByRole("region", { name: "当前规则" });
    expect(within(ruleSummary).queryByText("12 人局")).not.toBeInTheDocument();

    const seatSummary = await screen.findByText("12 人预女猎白局 · 12 个座位");
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

    expect(seatSummaryRule).toContain("lobby-wide-title-board.png");
    expect(seatSummaryRule).toContain("background-size: 100% 100%");
    expect(seatSummaryRule).toContain("flex: 0 1 160px");
    expect(seatSummaryRule).toContain("min-height: 28px");
    expect(seatSummaryRule).toContain("font-size: 9px");
    expect(boardTitleRule).toContain("min-height: 42px");
    expect(boardTitleRule).toContain("font-size: 12px");
    expect(readPngMetadata("src/assets/lobby-wide-title-board.png")).toEqual({
      width: 1685,
      height: 294,
      colorType: 6,
    });
  });

  it("shows only bold choose copy inside empty lobby seat cards", async () => {
    renderGamesPage();

    const seatButton = await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 请选择",
    });
    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatCardTextRule =
      styles.match(/\.mobile-lobby-seat-card\s+strong\s*{[^}]+}/)?.[0] ?? "";

    expect(within(seatButton).queryByText("1号座位")).not.toBeInTheDocument();
    expect(within(seatButton).getByText("请选择")).toBeVisible();
    expect(seatButton.querySelector(".mobile-lobby-seat-avatar")).toBeNull();
    expect(seatCardTextRule).toContain("font-weight: 800");
  });

  it("opens fill choices before creating from a completed lineup", async () => {
    const user = userEvent.setup();
    const { router } = renderGamesPage();

    expect(
      screen.queryByRole("button", { name: "随机补齐" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "收藏补齐" }),
    ).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "补齐席位" })).toHaveClass(
      "mobile-lobby-fill-toggle",
    );
    expect(screen.getByRole("button", { name: "清空席位" })).toHaveClass(
      "mobile-lobby-clear-seats",
    );

    await screen.findByText("已选 0/2 · 可自动补齐");
    const disabledLaunchButton = screen.getByRole("button", {
      name: "还差 2 位",
    });
    expect(disabledLaunchButton).toBeDisabled();
    expect(disabledLaunchButton).toHaveClass("mobile-lobby-launch-ready");
    expect(disabledLaunchButton).not.toHaveClass("mobile-lobby-launch-auto-fill");

    await user.click(screen.getByRole("button", { name: "补齐席位" }));

    expect(screen.getByRole("button", { name: "收藏补齐" })).toHaveClass(
      "mobile-lobby-favorite-fill",
    );
    expect(screen.getByRole("button", { name: "随机补齐" })).toHaveClass(
      "mobile-lobby-random-fill",
    );
    const styles = readFileSync("src/styles/index.css", "utf8");
    const fillOptionsRule =
      styles.match(/\.mobile-lobby-fill-options\s*{[^}]+}/)?.[0] ?? "";
    const fillOptionsArrowRule =
      styles.match(/\.mobile-lobby-fill-options::after\s*{[^}]+}/)?.[0] ?? "";
    expect(fillOptionsRule).toContain("position: absolute");
    expect(fillOptionsRule).not.toContain("grid-column");
    expect(fillOptionsRule).toContain("border:");
    expect(fillOptionsRule).toContain("padding:");
    expect(fillOptionsRule).toContain("background:");
    expect(fillOptionsArrowRule).toContain("position: absolute");
    expect(fillOptionsArrowRule).toContain("transform:");

    await user.click(screen.getByRole("button", { name: "随机补齐" }));

    expect(await screen.findByText("已选 2/2 · 阵容已就绪")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "随机补齐" }),
    ).not.toBeInTheDocument();
    const readyLaunchButton = screen.getByRole("button", { name: "开始对局" });
    expect(readyLaunchButton).toBeEnabled();
    expect(readyLaunchButton).toHaveClass("mobile-lobby-launch-ready");
    expect(readyLaunchButton).not.toHaveClass("mobile-lobby-launch-auto-fill");
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
        name: "选择 1 号座位，当前为 请选择",
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
        name: "选择 1 号座位，当前为 请选择",
      }),
    ).toBeVisible();
  });

  it("resets clear confirmation when submit validation fails", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
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

    await user.click(screen.getByRole("button", { name: "补齐席位" }));
    await user.click(screen.getByRole("button", { name: "随机补齐" }));
    await user.click(screen.getByRole("button", { name: "开始对局" }));

    expect(screen.getByText("最大轮数必须是 1 到 20 的整数")).toBeVisible();
    expect(screen.getByRole("button", { name: "清空席位" })).toBeVisible();
  });

  it("disables clear while game creation is pending", async () => {
    const user = userEvent.setup();
    gameClientMocks.createGameRun.mockReturnValue(
      new Promise(() => undefined),
    );
    renderGamesPage();

    await user.click(await screen.findByRole("button", { name: "补齐席位" }));
    await user.click(screen.getByRole("button", { name: "随机补齐" }));
    await user.click(screen.getByRole("button", { name: "开始对局" }));

    expect(screen.getByRole("button", { name: "发起中" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "发起中" })).toHaveClass(
      "mobile-lobby-launch-pending",
    );
    expect(screen.getByRole("button", { name: "清空席位" })).toBeDisabled();
  });

  it("blocks creation when the player library cannot fill the selected rule set", async () => {
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({ id: "profile-1", display_name: "阿青" }),
    ]);
    renderGamesPage();

    expect(
      screen.queryByRole("button", { name: "随机补齐" }),
    ).not.toBeInTheDocument();
    expect(await screen.findByText("已选 0/2 · 还差 1 名玩家")).toBeVisible();
    expect(screen.getByRole("button", { name: "还差 2 位" })).toBeDisabled();
    expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();
  });

  it("disables launch until empty seats are completed from the library", async () => {
    renderGamesPage();

    expect(await screen.findByText("已选 0/2 · 可自动补齐")).toBeVisible();
    expect(screen.getByRole("button", { name: "还差 2 位" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "还差 2 位" })).toHaveClass(
      "mobile-lobby-launch-ready",
    );

    expectLobbyButtonBackgroundAssets();
  });

  it("shows a confirm launch state when every seat has a player", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(await screen.findByRole("button", { name: "补齐席位" }));
    await user.click(screen.getByRole("button", { name: "随机补齐" }));

    expect(await screen.findByText("已选 2/2 · 阵容已就绪")).toBeVisible();
    expect(screen.getByRole("button", { name: "开始对局" })).toHaveClass(
      "mobile-lobby-launch-ready",
    );
  });

  it("blocks launch before submit when the player library cannot fill the lineup", async () => {
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({ id: "profile-1", display_name: "阿青" }),
    ]);
    renderGamesPage();

    expect(await screen.findByText("已选 0/2 · 还差 1 名玩家")).toBeVisible();
    expect(screen.getByRole("button", { name: "还差 2 位" })).toBeDisabled();
    expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();
  });

  it("opens the player card drawer from a selected seat", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      }),
    );

    expect(screen.getByRole("dialog", { name: "玩家卡牌库" })).toBeVisible();
    expect(screen.getByText("当前选择：1号座位")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    ).toBeVisible();
    expect(screen.getByText("雾夜里的分析者")).toHaveClass(
      "mobile-profile-card-description-line",
    );
    expect(
      screen.getByText("雾夜里的分析者"),
    ).not.toHaveClass("mobile-profile-card-description-text");

    const styles = readFileSync("src/styles/index.css", "utf8");
    const cardTextLayerRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-card-name-row,\s*\n\.mobile-profile-card-strategy,\s*\n\.mobile-profile-card-choice small\s*{[^}]+}/,
      )?.[0] ?? "";
    expect(cardTextLayerRule).toContain("z-index: 3");
    expect(styles).not.toContain(
      ".mobile-profile-card-select-button > :not(.mobile-profile-card-image)",
    );
  });

  it("renders the selected player check above the card artwork and frame", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      }),
    );
    const playerCard = screen.getByRole("button", {
      name: "为 1 号座位候选 阿青",
    });
    await user.click(playerCard);

    const check = playerCard.querySelector(".mobile-profile-card-check");

    expect(check).toBeInTheDocument();
    expect(check?.parentElement).toBe(playerCard);
    expect(check).toBeEmptyDOMElement();
    expect(
      playerCard.querySelector(
        ".mobile-profile-card-image .mobile-profile-card-check",
      ),
    ).not.toBeInTheDocument();
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
        name: "选择 1 号座位，当前为 请选择",
      }),
    );

    const favoriteButton = screen.getByRole("button", { name: "收藏 白石" });
    const styles = readFileSync("src/styles/index.css", "utf8");
    const favoriteButtonRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-card-favorite-button\s*{[^}]+}/,
      )?.[0] ?? "";
    const activeFavoriteButtonRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-card-favorite-button-active\s*{[^}]+}/,
      )?.[0] ?? "";
    const favoriteIconRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-card-favorite-icon\s*{[^}]+}/,
      )?.[0] ?? "";
    const inactiveFavoriteIcon = favoriteButton.querySelector(
      ".mobile-profile-card-favorite-icon",
    );

    expect(inactiveFavoriteIcon?.tagName.toLowerCase()).toBe("svg");
    expect(inactiveFavoriteIcon).toHaveClass("lucide");
    expect(inactiveFavoriteIcon).toHaveClass("lucide-star");
    expect(inactiveFavoriteIcon).toHaveAttribute("aria-hidden", "true");
    expect(favoriteButton).not.toHaveTextContent("☆");
    expect(favoriteButton).not.toHaveTextContent("★");
    expect(favoriteButtonRule).toContain("top: 14px");
    expect(favoriteButtonRule).toContain("width: 24px");
    expect(favoriteButtonRule).toContain("height: 24px");
    expect(favoriteButtonRule).toContain("border: 0");
    expect(favoriteButtonRule).toContain("background: transparent");
    expect(favoriteButtonRule).not.toContain("min-width");
    expect(favoriteButtonRule).not.toContain("box-shadow");
    expect(favoriteIconRule).toContain("width: 24px");
    expect(favoriteIconRule).toContain("height: 24px");
    expect(favoriteIconRule).toContain("fill: transparent");
    expect(activeFavoriteButtonRule).toContain("color: #b88a36");
    expect(styles).not.toContain(
      ".mobile-profile-card-favorite-button-active .mobile-profile-card-favorite-icon",
    );
    expect(styles).not.toContain("fill: currentColor");
    expect(styles).not.toContain("mobile-profile-card-frame");
    await user.click(favoriteButton);

    await waitFor(() => {
      expect(gameClientMocks.favoritePlayerProfile).toHaveBeenCalledWith("profile-2");
    });
    expect(screen.getByText("请选择玩家")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 白石" }),
    ).not.toHaveClass("mobile-profile-card-choice-active");
    const activeFavoriteButton = await screen.findByRole("button", {
      name: "取消收藏 白石",
    });
    const activeFavoriteIcon = activeFavoriteButton.querySelector(
      ".mobile-profile-card-favorite-icon",
    );
    expect(activeFavoriteIcon?.tagName.toLowerCase()).toBe("svg");
    expect(activeFavoriteIcon).toHaveClass("lucide");
    expect(activeFavoriteIcon).toHaveClass("lucide-star-check");
    expect(activeFavoriteButton).not.toHaveTextContent("★");
    expect(
      screen.getByRole("button", { name: "取消收藏 白石" }),
    ).not.toHaveFocus();
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
        name: "选择 1 号座位，当前为 请选择",
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
        name: "选择 1 号座位，当前为 请选择",
      }),
    );

    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    ).toBeEnabled();
    expect(screen.getByRole("status")).toHaveTextContent("收藏状态暂不可用");
    expect(screen.getByRole("button", { name: "收藏 阿青" })).toBeDisabled();
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
        name: "选择 1 号座位，当前为 请选择",
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
        name: "选择 1 号座位，当前为 请选择",
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
        name: "选择 1 号座位，当前为 请选择",
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
    const scrollRegion = drawer.querySelector(".mobile-profile-card-scroll");
    const refreshIndicator = drawer.querySelector(
      ".mobile-profile-refresh-indicator",
    );
    const styles = readFileSync("src/styles/index.css", "utf8");
    const refreshIndicatorRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-refresh-indicator\s*{[^}]+}/,
      )?.[0] ?? "";
    const refreshSpinnerRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-refresh-spinner\s*{[^}]+}/,
      )?.[0] ?? "";
    const refreshSpinner = refreshIndicator?.querySelector(
      ".mobile-profile-refresh-spinner",
    );

    expect(scrollRegion).toBeInstanceOf(HTMLElement);
    expect(refreshIndicator).toBeInTheDocument();
    expect(refreshIndicator).toHaveClass("mobile-profile-refresh-indicator-idle");
    expect(refreshSpinner?.tagName.toLowerCase()).toBe("svg");
    expect(refreshSpinner).toHaveClass("lucide");
    expect(refreshSpinner).toHaveClass("lucide-loader-circle");
    expect(refreshSpinner).toHaveAttribute("aria-hidden", "true");
    expect(refreshIndicatorRule).toContain("position: sticky");
    expect(refreshSpinnerRule).toContain(
      "animation: mobile-profile-refresh-spin",
    );
    expect(refreshSpinnerRule).toContain("width: 22px");
    expect(refreshSpinnerRule).toContain("height: 22px");
    expect(refreshSpinnerRule).toContain("color: #ffe6a4");
    expect(refreshSpinnerRule).not.toContain("background-image");
    expect(styles).not.toContain("lobby-profile-loading-spinner-alpha.png");
    expect(refreshSpinnerRule).not.toContain("border-top-color");
    expect(styles).toContain("@keyframes mobile-profile-refresh-spin");
    fireEvent.touchStart(scrollRegion as HTMLElement, {
      touches: [{ clientY: 12 }],
    });
    fireEvent.touchMove(scrollRegion as HTMLElement, {
      touches: [{ clientY: 92 }],
    });
    expect(refreshIndicator).toHaveClass("mobile-profile-refresh-indicator-ready");
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

  it("splits long player card descriptions into a shorter top line and longer bottom line", async () => {
    const user = userEvent.setup();
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({
        id: "profile-long-description",
        display_name: "长描述玩家",
        short_description: "沉稳控场，喜欢先盘逻辑再给站边。",
      }),
    ]);
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      }),
    );

    const card = screen.getByRole("button", {
      name: "为 1 号座位候选 长描述玩家",
    });
    const descriptionLines = Array.from(
      card.querySelectorAll(".mobile-profile-card-description-line"),
    );

    expect(descriptionLines).toHaveLength(2);
    expect(descriptionLines[0]).toHaveTextContent("沉稳控场，");
    expect(descriptionLines[1]).toHaveTextContent("喜欢先盘逻辑再给站边。");
    expect(descriptionLines[0].textContent?.length ?? 0).toBeLessThan(
      descriptionLines[1].textContent?.length ?? 0,
    );
    expect(
      card.querySelector(".mobile-profile-card-description-text"),
    ).not.toBeInTheDocument();
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
        name: "选择 1 号座位，当前为 请选择",
      }),
    );

    const drawer = await screen.findByRole("dialog", { name: "玩家卡牌库" });
    const avatar = drawer.querySelector(".mobile-profile-card-image img");
    expect(avatar).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
    );
  });

  it("keeps the player card drawer non-modal with a transparent click-through backdrop", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 请选择",
    }));

    const dialog = screen.getByRole("dialog", { name: "玩家卡牌库" });
    const styles = readFileSync("src/styles/index.css", "utf8");
    const drawerRule =
      styles.match(/(?:^|\n)\.mobile-profile-drawer\s*{[^}]+}/)?.[0] ?? "";
    const backdropRule =
      styles.match(/(?:^|\n)\.mobile-profile-drawer-backdrop\s*{[^}]+}/)?.[0] ??
      "";

    expect(dialog).toHaveAttribute("aria-modal", "false");
    expect(document.querySelector(".mobile-lobby-content")).not.toHaveAttribute(
      "inert",
    );
    expect(drawerRule).toContain("height: 78svh");
    expect(backdropRule).toContain("background: transparent");
    expect(backdropRule).toContain("pointer-events: none");

    const secondSeat = screen.getByRole("button", {
      name: "选择 2 号座位，当前为 请选择",
    });
    await user.click(secondSeat);

    expect(screen.getByRole("dialog", { name: "玩家卡牌库" })).toBeVisible();
    expect(screen.getByText("当前选择：2号座位")).toBeVisible();
    expect(secondSeat).toHaveFocus();
  });

  it("extends lobby scroll space while the player card drawer is open and restores it on close", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    const page = await screen.findByTestId("mobile-games-page");
    const styles = readFileSync("src/styles/index.css", "utf8");
    const baseLobbyPageRule =
      styles.match(/(?:^|\n)\.mobile-lobby-page\s*{[^}]+}/)?.[0] ?? "";
    const drawerOpenLobbyPageRule =
      styles.match(/(?:^|\n)\.mobile-lobby-page-drawer-open\s*{[^}]+}/)?.[0] ??
      "";

    expect(baseLobbyPageRule).toContain(
      "calc(var(--mobile-tab-frame-height) + 128px + env(safe-area-inset-bottom))",
    );
    expect(drawerOpenLobbyPageRule).toContain(
      "calc(78svh + var(--mobile-tab-frame-height) + 128px + env(safe-area-inset-bottom))",
    );
    expect(page).not.toHaveClass("mobile-lobby-page-drawer-open");

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      }),
    );

    expect(page).toHaveClass("mobile-lobby-page-drawer-open");

    await user.click(screen.getByRole("button", { name: "关闭玩家卡牌库" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "玩家卡牌库" }),
      ).not.toBeInTheDocument();
    });
    expect(page).not.toHaveClass("mobile-lobby-page-drawer-open");
  });

  it("lays out player drawer filters with bottom-sheet select triggers", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      }),
    );

    expect(screen.getByRole("searchbox", { name: "搜索玩家" })).toBeVisible();
    const favoriteFilterTrigger = screen.getByRole("button", {
      name: "收藏筛选，当前 全部玩家",
    });
    const strategyFilterTrigger = screen.getByRole("button", {
      name: "策略筛选，当前 全部策略",
    });
    expect(favoriteFilterTrigger).toBeVisible();
    expect(strategyFilterTrigger).toBeVisible();
    expect(favoriteFilterTrigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(favoriteFilterTrigger).toHaveAttribute("aria-expanded", "false");
    expect(strategyFilterTrigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.queryByRole("combobox", { name: "收藏筛选" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "策略筛选" })).not.toBeInTheDocument();
    const favoriteChevron = favoriteFilterTrigger
      .closest(".mobile-profile-select")
      ?.querySelector(".mobile-profile-select-chevron");
    const strategyChevron = strategyFilterTrigger
      .closest(".mobile-profile-select")
      ?.querySelector(".mobile-profile-select-chevron");
    expect(favoriteChevron?.tagName.toLowerCase()).toBe("svg");
    expect(favoriteChevron).toHaveClass("lucide");
    expect(favoriteChevron).toHaveClass("lucide-chevron-down");
    expect(favoriteChevron).toHaveAttribute("aria-hidden", "true");
    expect(strategyChevron?.tagName.toLowerCase()).toBe("svg");
    expect(strategyChevron).toHaveClass("lucide");
    expect(strategyChevron).toHaveClass("lucide-chevron-down");
    expect(strategyChevron).toHaveAttribute("aria-hidden", "true");

    const styles = readFileSync("src/styles/index.css", "utf8");
    const filtersRule =
      styles.match(/(?:^|\n)\.mobile-profile-drawer-filters\s*{[^}]+}/)?.[0] ??
      "";
    const searchRule =
      styles.match(/(?:^|\n)\.mobile-profile-search\s*{[^}]+}/)?.[0] ?? "";
    const selectRule =
      styles.match(/(?:^|\n)\.mobile-profile-select\s*{[^}]+}/)?.[0] ?? "";
    const searchInputRule =
      styles.match(/(?:^|\n)\.mobile-profile-search input\s*{[^}]+}/)?.[0] ??
      "";
    const selectTriggerRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-select-trigger\s*{[^}]+}/,
      )?.[0] ?? "";
    const selectLabelRule =
      styles.match(
        /(?:^|\n)\.mobile-lobby-field span,\s*\n\.mobile-profile-search span,\s*\n\.mobile-profile-select span\s*{[^}]+}/,
      )?.[0] ?? "";
    const selectTriggerTextRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-select-trigger span\s*{[^}]+}/,
      )?.[0] ?? "";
    const selectChevronRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-select-chevron\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectPopupRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectMaskRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-mask\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectPopupBodyRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-popup-body\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectPickerRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-picker\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectPickerViewRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-picker-view\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectPickerColumnRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-picker-view-column\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectPickerMaskTopRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-picker-view-mask-top\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectPickerMaskBottomRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-picker-view-mask-bottom\s*{[^}]+}/,
      )?.[0] ?? "";
    const bottomSelectPickerHeaderRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-picker-header\s*{[^}]+}/,
      )?.[0] ?? "";
    const inlineFilterRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-search,\s*\n\.mobile-profile-select\s*{[^}]+}/,
      )?.[0] ?? "";
    const searchBackground = readPngRgbaImage(
      "src/assets/lobby-profile-search-field-bg.png",
    );
    const favoriteBackground = readPngRgbaImage(
      "src/assets/lobby-profile-favorite-filter-bg.png",
    );
    const strategyBackground = readPngRgbaImage(
      "src/assets/lobby-profile-strategy-filter-bg.png",
    );

    expect(filtersRule).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(searchRule).toContain("grid-column: 1 / -1");
    expect(searchRule).toContain("lobby-profile-search-field-bg.png");
    expect(searchRule).toContain("min-height: 44px");
    expect(selectRule).toContain("min-height: 44px");
    expect(selectRule).toContain("lobby-profile-favorite-filter-bg.png");
    expect(styles).toContain(
      ".mobile-profile-select-strategy {\n  background-image: url(\"../assets/lobby-profile-strategy-filter-bg.png\");\n}",
    );
    expect(inlineFilterRule).toContain("grid-template-columns: max-content minmax(0, 1fr)");
    expect(inlineFilterRule).toContain("align-items: center");
    expect(selectRule).not.toContain("grid-column: 1 / -1");
    expect(searchInputRule).toContain("background: transparent");
    expect(searchInputRule).toContain("border: 0");
    expect(selectTriggerRule).toContain("background: transparent");
    expect(selectTriggerRule).toContain("border: 0");
    expect(selectTriggerRule).toContain("text-align: left");
    expect(selectLabelRule).toContain("font-size: 12px");
    expect(selectTriggerRule).toContain("font-size: 12px");
    expect(selectTriggerTextRule).toContain("font-size: 12px");
    expect(searchInputRule).toContain("min-height: 28px");
    expect(selectTriggerRule).toContain("min-height: 28px");
    expect(selectChevronRule).toContain("pointer-events: none");
    expect(selectChevronRule).toContain("width: 18px");
    expect(selectChevronRule).toContain("height: 18px");
    expect(bottomSelectPopupRule).toContain("z-index: 60");
    expect(bottomSelectMaskRule).toContain(
      "background: rgb(0 0 0 / 12%) !important",
    );
    expect(bottomSelectPopupBodyRule).toContain("bottom: 0");
    expect(bottomSelectPopupBodyRule).toContain("max-height: min(72svh, 420px)");
    expect(bottomSelectPopupBodyRule).toContain("border-radius: 0");
    expect(bottomSelectPopupBodyRule).not.toContain("12px 12px 0 0");
    expect(bottomSelectPopupBodyRule).toContain("rgb(12 20 28 / 62%)");
    expect(bottomSelectPopupBodyRule).toContain("rgb(5 9 15 / 68%)");
    expect(bottomSelectPopupBodyRule).toContain("backdrop-filter: blur(5px)");
    expect(bottomSelectPickerRule).toContain("--item-height: 44px");
    expect(bottomSelectPickerViewRule).toContain("background: rgb(5 9 16 / 42%)");
    expect(bottomSelectPickerColumnRule).toContain("background: transparent");
    expect(bottomSelectPickerMaskTopRule).toContain("linear-gradient");
    expect(bottomSelectPickerMaskTopRule).toContain("rgb(5 9 16 / 54%)");
    expect(bottomSelectPickerMaskTopRule).toContain("rgb(5 9 16 / 28%)");
    expect(bottomSelectPickerMaskBottomRule).toContain("linear-gradient");
    expect(bottomSelectPickerMaskBottomRule).toContain("rgb(5 9 16 / 54%)");
    expect(bottomSelectPickerMaskBottomRule).toContain("rgb(5 9 16 / 28%)");
    expect(bottomSelectPickerHeaderRule).toContain(
      "background: rgb(5 9 15 / 58%)",
    );
    expect(readPngMetadata("src/assets/lobby-profile-search-field-bg.png")).toEqual({
      width: 856,
      height: 88,
      colorType: 6,
    });
    expect(
      readPngMetadata("src/assets/lobby-profile-favorite-filter-bg.png"),
    ).toEqual({
      width: 420,
      height: 88,
      colorType: 6,
    });
    expect(
      readPngMetadata("src/assets/lobby-profile-strategy-filter-bg.png"),
    ).toEqual({
      width: 420,
      height: 88,
      colorType: 6,
    });
    for (const background of [
      searchBackground,
      favoriteBackground,
      strategyBackground,
    ]) {
      expect(getAlphaAt(background, 0, 0)).toBe(0);
      expect(getAlphaAt(background, background.width - 1, 0)).toBe(0);
      expect(getAlphaAt(background, 0, background.height - 1)).toBe(0);
      expect(
        getAlphaAt(
          background,
          Math.floor(background.width / 2),
          Math.floor(background.height / 2),
        ),
      ).toBe(255);
    }
  });

  it("lays out eight seats as two horizontal rows on mobile", async () => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [{ ...classicRuleSet, player_count: 8 }],
    });
    renderGamesPage();

    await screen.findByRole("button", {
      name: "选择 8 号座位，当前为 请选择",
    });

    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatGridRule = styles.match(/\.mobile-lobby-seat-grid\s*{[^}]+}/)?.[0];
    const seatCardRule = styles.match(/\.mobile-lobby-seat-card\s*{[^}]+}/)?.[0];
    const actionBarRule =
      styles.match(/\.mobile-lobby-action-bar\s*{[^}]+}/)?.[0] ?? "";
    const actionBarBackground = readPngRgbaImage(
      "src/assets/lobby-action-bar-bg.png",
    );

    expect(seatGridRule).toContain("grid-template-columns: repeat(4");
    expect(seatGridRule).toContain("grid-template-rows: repeat(2");
    expect(seatCardRule).toContain("aspect-ratio: 935 / 983");
    expect(seatCardRule).toContain("min-height: 0");
    expect(actionBarRule).toContain("grid-template-columns: repeat(3");
    expect(actionBarRule).toContain("bottom: calc(var(--mobile-tab-frame-height) + 6px");
    expect(actionBarRule).toContain("lobby-action-bar-bg.png");
    expect(actionBarRule).toContain("background-size: 100% 100%");
    expect(actionBarRule).toContain("border: 0");
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
        name: "选择 1 号座位，当前为 请选择",
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
        name: "选择 1 号座位，当前为 请选择",
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
    ).toHaveClass("mobile-lobby-seat-card-filled");
    const fillSettingsHeading = screen.getByRole("heading", {
      name: "填充设置",
    });
    const fillSettingsHeadingRow = fillSettingsHeading.closest(
      ".mobile-lobby-section-heading",
    );

    expect(fillSettingsHeadingRow).not.toBeNull();
    expect(
      within(fillSettingsHeadingRow as HTMLElement).queryByText("阿青"),
    ).not.toBeInTheDocument();

    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatCardRule =
      styles.match(/\.mobile-lobby-seat-card\s*{[^}]+}/)?.[0] ?? "";
    const filledSeatRule =
      styles.match(/\.mobile-lobby-seat-card-filled\s*{[^}]+}/)?.[0] ?? "";
    const filledSeatFrameRule =
      [...styles.matchAll(/\.mobile-lobby-seat-card-filled::after\s*{[^}]+}/g)]
        .map((match) => match[0])
        .find((rule) => rule.includes("background-image")) ?? "";
    const filledSeatAvatarRule =
      styles.match(
        /\.mobile-lobby-seat-card-filled\s+\.mobile-lobby-seat-avatar\s*{[^}]+}/,
      )?.[0] ?? "";
    const filledSeatAvatarImageRule =
      styles.match(
        /\.mobile-lobby-seat-card-filled\s+\.mobile-lobby-seat-avatar\s+img\s*{[^}]+}/,
      )?.[0] ?? "";
    const filledSeatNameRule =
      styles.match(
        /\.mobile-lobby-seat-card-filled\s+strong\s*{[^}]+}/,
      )?.[0] ?? "";
    const stoneSeatBackground = readPngRgbaImage(
      "src/assets/lobby-seat-card-stone-bg.png",
    );
    const selectedSeatFrame = readPngRgbaImage(
      "src/assets/lobby-seat-card-frame-alpha.png",
    );

    expect(seatCardRule).toContain("lobby-seat-card-frame-alpha.png");
    expect(seatCardRule).toContain("lobby-seat-card-stone-bg.png");
    expect(filledSeatRule).toContain("background-image: none");
    expect(filledSeatFrameRule).toContain("lobby-seat-card-frame-alpha.png");
    expect(filledSeatAvatarRule).toContain("position: absolute");
    expect(filledSeatAvatarRule).toContain("inset: 0");
    expect(filledSeatAvatarRule).toContain("width: 100%");
    expect(filledSeatAvatarRule).toContain("height: 100%");
    expect(filledSeatAvatarImageRule).toContain("object-position: center top");
    expect(filledSeatNameRule).toContain("position: absolute");
    expect(filledSeatNameRule).toContain("bottom: 7px");
    expect(
      getAlphaAt(
        stoneSeatBackground,
        Math.floor(stoneSeatBackground.width / 2),
        Math.floor(stoneSeatBackground.height / 2),
      ),
    ).toBe(255);
    expect(getAlphaAt(stoneSeatBackground, 0, 0)).toBe(0);
    expect(
      getAlphaAt(
        stoneSeatBackground,
        Math.floor(stoneSeatBackground.width / 2),
        40,
      ),
    ).toBe(0);
    expect(
      getAlphaAt(
        selectedSeatFrame,
        Math.floor(selectedSeatFrame.width / 2),
        Math.floor(selectedSeatFrame.height / 2),
      ),
    ).toBe(0);
    expect(getAlphaAt(selectedSeatFrame, 300, 300)).toBe(0);

    const decorativeRegions = [
      [0, 330, 150, 650],
      [selectedSeatFrame.width - 150, 330, selectedSeatFrame.width, 650],
      [330, 0, 605, 150],
      [330, selectedSeatFrame.height - 150, 605, selectedSeatFrame.height],
      [0, 0, 220, 220],
      [selectedSeatFrame.width - 220, 0, selectedSeatFrame.width, 220],
      [0, selectedSeatFrame.height - 220, 220, selectedSeatFrame.height],
      [
        selectedSeatFrame.width - 220,
        selectedSeatFrame.height - 220,
        selectedSeatFrame.width,
        selectedSeatFrame.height,
      ],
    ];
    for (const [left, top, right, bottom] of decorativeRegions) {
      expect(
        countPixelsAboveAlpha(
          selectedSeatFrame,
          left,
          top,
          right,
          bottom,
          200,
        ),
      ).toBeGreaterThan(1_000);
    }
  });

  it("labels player cards that are already assigned and confirms moves explicitly", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认选择" }));

    await user.click(
      await screen.findByRole("button", {
        name: "选择 2 号座位，当前为 请选择",
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
        name: "选择 1 号座位，当前为 请选择",
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
        name: "选择 1 号座位，当前为 请选择",
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
    expect(screen.getByText("请选择玩家")).toBeVisible();
  });

  it("focuses and scrolls the active outside seat row when opening and advancing", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    try {
      renderGamesPage();

      const firstSeat = await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      });
      await user.click(firstSeat);

      expect(firstSeat).toHaveFocus();
      await waitFor(() => {
        expect(scrollIntoView).toHaveBeenLastCalledWith({
          behavior: "smooth",
          block: "start",
          inline: "nearest",
        });
      });

      await user.click(
        screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
      );
      await user.click(screen.getByRole("button", { name: "确认并下一位" }));

      const secondSeat = screen.getByRole("button", {
        name: "选择 2 号座位，当前为 请选择",
      });
      expect(secondSeat).toHaveFocus();
      await waitFor(() => {
        expect(scrollIntoView).toHaveBeenLastCalledWith({
          behavior: "smooth",
          block: "start",
          inline: "nearest",
        });
      });
    } finally {
      if (originalScrollIntoView) {
        Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
          configurable: true,
          value: originalScrollIntoView,
        });
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
      }
    }
  });

  it("opens player drawer filters in a bottom sheet and applies the selected option", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
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

  it("keeps the player card drawer chrome fixed while snapping one row of cards", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      }),
    );

    expect(screen.getByRole("dialog", { name: "玩家卡牌库" })).toBeVisible();

    const styles = readFileSync("src/styles/index.css", "utf8");
    const drawerRule =
      styles.match(/(?:^|\n)\.mobile-profile-drawer\s*{[^}]+}/)?.[0] ?? "";
    const titleRowRule =
      styles.match(/(?:^|\n)\.mobile-profile-drawer-title-row\s*{[^}]+}/)
        ?.[0] ?? "";
    const headingTitleRule =
      styles.match(/(?:^|\n)\.mobile-profile-drawer-heading h2\s*{[^}]+}/)
        ?.[0] ?? "";
    const cardScrollRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-scroll\s*{[^}]+}/)?.[0] ??
      "";
    const cardGridRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-grid\s*{[^}]+}/)?.[0] ?? "";
    const cardChoiceRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-choice\s*{[^}]+}/)?.[0] ?? "";
    const footerRule =
      styles.match(/(?:^|\n)\.mobile-profile-drawer-footer\s*{[^}]+}/)?.[0] ??
      "";
    const footerDividerRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-drawer-footer::before\s*{[^}]+}/,
      )?.[0] ?? "";
    const closeButtonRule =
      styles.match(/(?:^|\n)\.mobile-profile-drawer-close\s*{[^}]+}/)?.[0] ??
      "";
    const footerButtonRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-drawer-footer\s+\.mobile-button\s*{[^}]+}/,
      )?.[0] ?? "";
    const footerPrimaryButtonRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-drawer-footer\s+\.mobile-button-primary\s*{[^}]+}/,
      )?.[0] ?? "";
    const footerButtonBackground = readPngRgbaImage(
      "src/assets/lobby-buttons/button-favorite-fill.png",
    );
    const footerPrimaryButtonBackground = readPngRgbaImage(
      "src/assets/lobby-buttons/button-launch-autofill.png",
    );
    const footerDividerBackground = readPngRgbaImage(
      "src/assets/lobby-profile-drawer-divider-alpha.png",
    );
    const closeButtonBackground = readPngRgbaImage(
      "src/assets/lobby-close-button-bg.png",
    );

    expect(drawerRule).toContain("height: 78svh");
    expect(drawerRule).toContain(
      "grid-template-rows: auto minmax(0, 1fr) auto",
    );
    expect(drawerRule).toContain("overflow: hidden");
    expect(drawerRule).toContain("padding: 20px 26px 0");
    expect(drawerRule).not.toContain("overflow-y: auto");
    expect(drawerRule).toContain("lobby-profile-drawer-bg.png");
    expect(drawerRule).toContain("background-size: 100% 100%");
    const titleRow = screen
      .getByRole("heading", { name: "玩家卡牌库" })
      .closest(".mobile-profile-drawer-title-row");
    expect(titleRow).toContainElement(
      screen.getByRole("button", { name: "关闭玩家卡牌库" }),
    );
    expect(titleRowRule).toContain("display: flex");
    expect(titleRowRule).toContain("align-items: center");
    expect(titleRowRule).toContain("justify-content: space-between");
    expect(headingTitleRule).toContain("font-size: 18px");
    expect(headingTitleRule).toContain("line-height: 18px");
    expect(headingTitleRule).toContain("font-weight: 900");
    expect(headingTitleRule).toContain(
      "background-image: linear-gradient(180deg, #fff7d6 0%, #f8ebc8 100%)",
    );
    expect(headingTitleRule).toContain("background-clip: text");
    expect(headingTitleRule).toContain("-webkit-text-fill-color: transparent");
    expect(headingTitleRule).toContain("text-shadow:");
    expect(cardScrollRule).toContain("height: 100%");
    expect(cardScrollRule).toContain("overflow-y: auto");
    expect(cardScrollRule).toContain("scroll-snap-type: y mandatory");
    expect(cardGridRule).toContain("grid-auto-rows: 100%");
    expect(cardChoiceRule).toContain("height: 100%");
    expect(cardChoiceRule).toContain("scroll-snap-align: start");
    expect(footerRule).toContain("position: relative");
    expect(footerRule).toContain("align-self: end");
    expect(footerRule).toContain("margin: 2px 0 0");
    expect(footerRule).toContain("padding: 24px 0 16px");
    expect(footerRule).toContain("border-top: 0");
    expect(footerRule).not.toContain("position: sticky");
    expect(footerRule).not.toContain("-26px");
    expect(footerDividerRule).toContain("lobby-profile-drawer-divider-alpha.png");
    expect(footerDividerRule).toContain("height: 34px");
    expect(footerDividerRule).toContain("background-size: 100% auto");
    expect(closeButtonRule).toContain("width: 30px");
    expect(closeButtonRule).toContain("height: 30px");
    expect(closeButtonRule).toContain("border: 0");
    expect(closeButtonRule).toContain("lobby-close-button-bg.png");
    expect(closeButtonRule).toContain("background-size: contain");
    expect(closeButtonRule).toContain("font-size: 0");
    expect(footerButtonRule).toContain("width: 120px");
    expect(footerButtonRule).toContain("height: 45px");
    expect(footerButtonRule).toContain("aspect-ratio: 8 / 3");
    expect(footerButtonRule).toContain("border: 0");
    expect(footerButtonRule).toContain("lobby-buttons/button-favorite-fill.png");
    expect(footerButtonRule).toContain("background-size: contain");
    expect(footerPrimaryButtonRule).toContain(
      "lobby-buttons/button-launch-autofill.png",
    );
    expect(
      readPngMetadata("src/assets/lobby-buttons/button-favorite-fill.png"),
    ).toEqual({
      width: 480,
      height: 180,
      colorType: 6,
    });
    expect(
      readPngMetadata("src/assets/lobby-buttons/button-launch-autofill.png"),
    ).toEqual({
      width: 480,
      height: 180,
      colorType: 6,
    });
    expect(readPngMetadata("src/assets/lobby-profile-drawer-bg.png")).toEqual({
      width: 942,
      height: 1434,
      colorType: 2,
    });
    expect(readPngMetadata("src/assets/lobby-close-button-bg.png")).toEqual({
      width: 216,
      height: 216,
      colorType: 6,
    });
    expect(
      readPngMetadata("src/assets/lobby-profile-drawer-divider-alpha.png"),
    ).toEqual({
      width: 2134,
      height: 196,
      colorType: 6,
    });
    expect(getAlphaAt(closeButtonBackground, 0, 0)).toBe(0);
    expect(
      getAlphaAt(
        closeButtonBackground,
        Math.floor(closeButtonBackground.width / 2),
        Math.floor(closeButtonBackground.height / 2),
      ),
    ).toBeGreaterThan(240);
    expect(getAlphaAt(footerButtonBackground, 0, 0)).toBe(0);
    expect(
      getAlphaAt(
        footerButtonBackground,
        Math.floor(footerButtonBackground.width / 2),
        Math.floor(footerButtonBackground.height / 2),
      ),
    ).toBe(255);
    expect(getAlphaAt(footerPrimaryButtonBackground, 0, 0)).toBe(0);
    expect(
      getAlphaAt(
        footerPrimaryButtonBackground,
        Math.floor(footerPrimaryButtonBackground.width / 2),
        Math.floor(footerPrimaryButtonBackground.height / 2),
      ),
    ).toBe(255);
    expect(getAlphaAt(footerDividerBackground, 0, 0)).toBe(0);
    expect(
      getAlphaAt(
        footerDividerBackground,
        Math.floor(footerDividerBackground.width / 2),
        Math.floor(footerDividerBackground.height / 2),
      ),
    ).toBeGreaterThan(240);
  });

  it("overlays the generated dark thin border on player cards without card padding", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const cardChoiceRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-choice\s*{[^}]+}/)?.[0] ?? "";
    const cardChoiceDirectChildRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-choice > \*\s*{[^}]+}/)
        ?.[0] ?? "";
    const cardSelectButtonRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-card-select-button\s*{[^}]+}/,
      )?.[0] ?? "";
    const cardFrameRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-choice::after\s*{[^}]+}/)
        ?.[0] ?? "";
    const cardShadeRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-choice::before\s*{[^}]+}/)
        ?.[0] ?? "";
    const cardImageRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-image\s*{[^}]+}/)?.[0] ??
      "";
    const cardCheckRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-check\s*{[^}]+}/)?.[0] ??
      "";
    const cardTextInsetRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-card-name-row,\s*\n\.mobile-profile-card-strategy,\s*\n\.mobile-profile-card-choice small\s*{[^}]+}/,
      )?.[0] ?? "";
    const cardNameRowRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-name-row\s*{[^}]+}/)?.[0] ??
      "";
    const cardActiveRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-choice-active\s*{[^}]+}/)
        ?.[0] ?? "";
    const cardActiveFrameRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-card-choice-active::after\s*{[^}]+}/,
      )?.[0] ?? "";
    const cardDescriptionRule =
      Array.from(
        styles.matchAll(
          /(?:^|\n)\.mobile-profile-card-choice small\s*{[^}]+}/g,
        ),
      )
        .map((match) => match[0])
        .find((rule) => rule.includes("margin-bottom")) ?? "";
    const cardDescriptionLineRule =
      styles.match(
        /(?:^|\n)\.mobile-profile-card-description-line\s*{[^}]+}/,
      )?.[0] ?? "";
    const frameImage = readPngRgbaImage(
      "src/assets/lobby-profile-card-light-frame-alpha.png",
    );
    const selectedMarkImage = readPngRgbaImage(
      "src/assets/lobby-profile-card-selected-mark-alpha.png",
    );
    const frameBounds = getAlphaBounds(frameImage);
    const selectedMarkCheckBounds =
      getLargestCentralGoldComponentBounds(selectedMarkImage);

    expect(cardChoiceRule).toContain("padding: 0");
    expect(cardChoiceRule).toContain("border: 0");
    expect(cardChoiceRule).toContain("border-radius: 8px");
    expect(cardChoiceRule).toContain("display: flex");
    expect(cardChoiceRule).toContain("flex-direction: column");
    expect(cardChoiceRule).toContain("justify-content: flex-end");
    expect(cardChoiceRule).toContain("text-align: center");
    expect(cardChoiceRule).toContain("isolation: isolate");
    expect(cardChoiceDirectChildRule).toContain("position: relative");
    expect(cardChoiceDirectChildRule).toContain("z-index: auto");
    expect(cardChoiceDirectChildRule).not.toContain("z-index: 1");
    expect(cardSelectButtonRule).toContain("z-index: auto");
    expect(cardShadeRule).toContain("content: \"\"");
    expect(cardShadeRule).toContain("position: absolute");
    expect(cardShadeRule).toContain("inset: 0");
    expect(cardShadeRule).toContain("z-index: 1");
    expect(cardShadeRule).toContain("linear-gradient");
    expect(cardFrameRule).toContain("content: \"\"");
    expect(cardFrameRule).toContain("position: absolute");
    expect(cardFrameRule).toContain("inset: 0");
    expect(cardFrameRule).toContain("pointer-events: none");
    expect(cardFrameRule).toContain("z-index: 2");
    expect(cardFrameRule).toContain("border-radius: inherit");
    expect(cardFrameRule).toContain("lobby-profile-card-light-frame-alpha.png");
    expect(cardFrameRule).toContain("background-size: 100% 100%");
    expect(cardActiveRule).toContain("z-index: 1");
    expect(cardActiveRule).toContain("rgb(177 135 61 / 16%)");
    expect(cardActiveRule).toContain("rgb(133 93 39 / 34%)");
    expect(cardActiveFrameRule).toContain("box-shadow:");
    expect(cardActiveFrameRule).toContain("inset 0 0 0 2px");
    expect(cardActiveFrameRule).toContain("rgb(172 128 54 / 58%)");
    expect(cardActiveFrameRule).toContain("rgb(128 89 36 / 24%)");
    expect(cardActiveFrameRule).toContain("filter:");
    expect(cardActiveFrameRule).toContain(
      "drop-shadow(0 0 5px rgb(145 103 41 / 34%))",
    );
    expect(cardActiveFrameRule).toContain(
      "drop-shadow(0 0 1px rgb(196 151 73 / 32%))",
    );
    expect(`${cardActiveRule}\n${cardActiveFrameRule}`).not.toContain(
      "rgb(255 229 161",
    );
    expect(`${cardActiveRule}\n${cardActiveFrameRule}`).not.toContain(
      "rgb(247 215 144",
    );
    expect(`${cardActiveRule}\n${cardActiveFrameRule}`).not.toContain(
      "rgb(255 241 204",
    );
    expect(cardImageRule).toContain("position: absolute");
    expect(cardImageRule).toContain("inset: 0");
    expect(cardImageRule).toContain("width: 100%");
    expect(cardImageRule).toContain("height: 100%");
    expect(cardImageRule).toContain("margin: 0");
    expect(cardImageRule).toContain("z-index: 0");
    expect(cardCheckRule).toContain("z-index: 3");
    expect(cardCheckRule).toContain("top: 10px");
    expect(cardCheckRule).toContain("left: 10px");
    expect(cardCheckRule).not.toContain("right:");
    expect(cardCheckRule).not.toContain("bottom:");
    expect(cardCheckRule).toContain("width: 32px");
    expect(cardCheckRule).toContain("height: 32px");
    expect(cardCheckRule).toContain("border: 0");
    expect(cardCheckRule).toContain(
      "background-image: url(\"../assets/lobby-profile-card-selected-mark-alpha.png\")",
    );
    expect(cardCheckRule).toContain("background-size: contain");
    expect(cardCheckRule).toContain("color: transparent");
    expect(cardCheckRule).toContain("font-size: 0");
    expect(cardCheckRule).not.toContain("✓");
    expect(cardTextInsetRule).toContain("margin-inline: 24px");
    expect(cardTextInsetRule).toContain("z-index: 3");
    expect(cardNameRowRule).toContain("justify-content: center");
    expect(cardDescriptionRule).toContain("display: flex");
    expect(cardDescriptionRule).toContain("flex-direction: column");
    expect(cardDescriptionRule).toContain("align-items: center");
    expect(cardDescriptionRule).toContain("max-height: 2.7em");
    expect(cardDescriptionRule).toContain("overflow: hidden");
    expect(cardDescriptionLineRule).toContain("display: block");
    expect(cardDescriptionLineRule).toContain("max-width: 100%");
    expect(cardDescriptionLineRule).toContain("white-space: nowrap");
    expect(styles).not.toContain("mobile-profile-card-description-text");
    expect(styles).not.toContain("background: rgb(2 5 10 / 68%)");
    expect(styles).not.toContain("box-decoration-break: clone");
    expect(styles).not.toContain("lobby-profile-card-thin-bg.png");
    expect(styles).not.toContain("lobby-profile-card-frame-alpha.png");
    expect(readPngMetadata("src/assets/lobby-profile-card-light-frame-alpha.png")).toEqual({
      width: 817,
      height: 1683,
      colorType: 6,
    });
    expect(readPngMetadata("src/assets/lobby-profile-card-selected-mark-alpha.png")).toEqual({
      width: 256,
      height: 256,
      colorType: 6,
    });
    expect(getAlphaAt(selectedMarkImage, 0, 0)).toBe(0);
    expect(getAlphaAt(selectedMarkImage, 32, 32)).toBeLessThan(32);
    expect(getAlphaAt(selectedMarkImage, 224, 32)).toBeLessThan(32);
    expect(getAlphaAt(selectedMarkImage, 32, 224)).toBeLessThan(32);
    expect(getAlphaAt(selectedMarkImage, 224, 224)).toBeLessThan(32);
    expect(getAlphaAt(selectedMarkImage, 128, 22)).toBeGreaterThan(120);
    expect(getAlphaAt(selectedMarkImage, 22, 128)).toBeGreaterThan(120);
    expect(getAlphaAt(selectedMarkImage, 234, 128)).toBeGreaterThan(120);
    expect(getAlphaAt(selectedMarkImage, 128, 234)).toBeGreaterThan(120);
    expect(
      getAlphaAt(
        selectedMarkImage,
        Math.floor(selectedMarkImage.width / 2),
        Math.floor(selectedMarkImage.height / 2),
      ),
    ).toBeGreaterThan(240);
    expect(getOpaqueLuminancePercentile(selectedMarkImage, 0.99)).toBeGreaterThan(
      200,
    );
    expect(countOpaquePixelsAboveLuminance(selectedMarkImage, 170)).toBeGreaterThan(
      900,
    );
    expect(countOpaquePixelsAboveLuminance(selectedMarkImage, 160)).toBeGreaterThan(
      900,
    );
    expect(selectedMarkCheckBounds.right - selectedMarkCheckBounds.left + 1).toBeLessThanOrEqual(
      125,
    );
    expect(selectedMarkCheckBounds.bottom - selectedMarkCheckBounds.top + 1).toBeLessThanOrEqual(
      125,
    );
    expect(selectedMarkCheckBounds.right - selectedMarkCheckBounds.left + 1).toBeGreaterThanOrEqual(
      90,
    );
    expect(selectedMarkCheckBounds.bottom - selectedMarkCheckBounds.top + 1).toBeGreaterThanOrEqual(
      90,
    );
    expect(selectedMarkCheckBounds.pixelCount).toBeGreaterThan(900);
    expect(frameBounds.left).toBeLessThanOrEqual(1);
    expect(frameBounds.top).toBeLessThanOrEqual(1);
    expect(frameBounds.right).toBeGreaterThanOrEqual(
      frameImage.width - 2,
    );
    expect(frameBounds.bottom).toBeGreaterThanOrEqual(
      frameImage.height - 2,
    );
    expect(getAlphaAt(frameImage, 0, 0)).toBe(0);
    expect(
      getAlphaAt(
        frameImage,
        Math.floor(frameImage.width / 2),
        Math.floor(frameImage.height / 2),
      ),
    ).toBe(0);
    expect(
      getAlphaAt(frameImage, 18, Math.floor(frameImage.height / 2)),
    ).toBeGreaterThan(240);
    expect(
      getAlphaAt(frameImage, Math.floor(frameImage.width / 2), 20),
    ).toBeGreaterThan(120);
    expect(
      getAlphaRunWidthAtRow(
        frameImage,
        Math.floor(frameImage.height / 2),
        8,
        128,
      ),
    ).toBeLessThanOrEqual(36);
    expect(
      Math.max(
        getRgbaAt(frameImage, 18, Math.floor(frameImage.height / 2)).red,
        getRgbaAt(frameImage, 18, Math.floor(frameImage.height / 2)).green,
        getRgbaAt(frameImage, 18, Math.floor(frameImage.height / 2)).blue,
      ),
    ).toBeLessThanOrEqual(180);
    expect(
      Math.max(
        getRgbaAt(frameImage, Math.floor(frameImage.width / 2), 20).red,
        getRgbaAt(frameImage, Math.floor(frameImage.width / 2), 20).green,
        getRgbaAt(frameImage, Math.floor(frameImage.width / 2), 20).blue,
      ),
    ).toBeLessThanOrEqual(180);
  });

  it("includes the current-seat status in assigned player card names", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
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

  it("shows occupied-seat status above the player name without reserving an empty row", async () => {
    const user = userEvent.setup();
    renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
    );
    await user.click(screen.getByRole("button", { name: "确认选择" }));

    await user.click(
      await screen.findByRole("button", {
        name: "选择 2 号座位，当前为 请选择",
      }),
    );

    const assignedCard = screen.getByRole("button", {
      name: "为 2 号座位候选 阿青，已在 1 号座位",
    });
    const unassignedCard = screen.getByRole("button", {
      name: "为 2 号座位候选 白石",
    });
    const assignedStatus = assignedCard.querySelector(
      ".mobile-profile-card-seat-status",
    );
    const emptyStatus = unassignedCard.querySelector(
      ".mobile-profile-card-seat-status",
    );
    const styles = readFileSync("src/styles/index.css", "utf8");
    const statusRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-seat-status\s*{[^}]+}/)?.[0] ??
      "";
    const nameRowRule =
      styles.match(/(?:^|\n)\.mobile-profile-card-name-row\s*{[^}]+}/)?.[0] ??
      "";
    const emptyStatusRule = styles.match(
      /(?:^|\n)\.mobile-profile-card-seat-status-empty\s*{[^}]+}/,
    );

    expect(assignedStatus).toHaveTextContent("已在 1 号座位");
    expect(
      assignedStatus?.closest(".mobile-profile-card-name-row"),
    ).not.toBeNull();
    const assignedName = within(assignedCard).getByText("阿青");
    expect(assignedName).toBeVisible();
    expect(assignedStatus?.nextElementSibling).toBe(assignedName);
    expect(emptyStatus).toBeNull();
    expect(nameRowRule).toContain("display: flex");
    expect(nameRowRule).toContain("flex-direction: column");
    expect(statusRule).not.toContain("min-height");
    expect(emptyStatusRule).toBeNull();
  });

  it("disables confirmation when the pending player is removed by refresh", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderGamesPage();

    await user.click(
      await screen.findByRole("button", {
        name: "选择 1 号座位，当前为 请选择",
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
      expect(within(drawer).getByText("请选择玩家")).toBeVisible();
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
        name: "选择 1 号座位，当前为 请选择",
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
        name: "选择 1 号座位，当前为 请选择",
      }),
    ).toBeVisible();
  });
});
