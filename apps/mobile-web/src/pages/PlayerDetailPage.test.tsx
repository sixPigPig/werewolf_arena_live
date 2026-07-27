import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlayerDetailPage } from "./PlayerDetailPage";
import {
  ApiError,
  type PublicPlayerProfile,
} from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  getPublicPlayerProfile: vi.fn(),
  listPlayerProfileFavorites: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    getPublicPlayerProfile: gameClientMocks.getPublicPlayerProfile,
    listPlayerProfileFavorites: gameClientMocks.listPlayerProfileFavorites,
  };
});

function buildProfile(
  overrides: Pick<PublicPlayerProfile, "display_name" | "id"> &
    Partial<PublicPlayerProfile>,
): PublicPlayerProfile {
  const { display_name, id, ...profileOverrides } = overrides;

  return {
    model_provider: overrides.model_provider ?? "deepseek",
    model: overrides.model ?? "test-model",
    personality_id: overrides.personality_id ?? "balanced",
    personality_text: overrides.personality_text ?? "稳健发言，优先找逻辑漏洞。",
    short_description: overrides.short_description ?? "冷静复盘型玩家",
    background_story: overrides.background_story ?? "来自古堡议事厅的旁观者。",
    speaking_style: overrides.speaking_style ?? "短句推进",
    catchphrases: overrides.catchphrases ?? ["先听后置位", "票型会说话"],
    strategy_profile: overrides.strategy_profile ?? "balanced",
    risk_tolerance: overrides.risk_tolerance ?? 3,
    bluffing_tendency: overrides.bluffing_tendency ?? 2,
    trust_tendency: overrides.trust_tendency ?? 4,
    leadership_tendency: overrides.leadership_tendency ?? 5,
    talkativeness: overrides.talkativeness ?? 3,
    example_messages: overrides.example_messages ?? ["我先归一下已知信息。"],
    display_order: overrides.display_order ?? 1,
    featured: overrides.featured ?? false,
    appearance_id: overrides.appearance_id ?? "default",
    avatar_image_url: "",
    tags: overrides.tags ?? ["控场", "复盘"],
    ...profileOverrides,
    id,
    display_name,
  };
}

function renderPlayerDetailRoute(initialPath = "/players/moon-hunter") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [{ path: "/players/:playerId", element: <PlayerDetailPage /> }],
    { initialEntries: [initialPath] },
  );

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("PlayerDetailPage", () => {
  beforeEach(() => {
    gameClientMocks.getPublicPlayerProfile.mockResolvedValue(
      buildProfile({
        id: "moon-hunter",
        display_name: "月下猎人",
        model: "deepseek-v4-flash",
        avatar_image_url:
          "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
      }),
    );
    gameClientMocks.listPlayerProfileFavorites.mockResolvedValue({
      profile_ids: ["moon-hunter"],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the selected player as a gothic dossier", async () => {
    renderPlayerDetailRoute();

    expect(await screen.findByRole("heading", { name: "玩家详情" })).toBeVisible();
    expect(await screen.findByText("月下猎人")).toBeVisible();
    expect(screen.getByText("角色档案")).toBeVisible();
    expect(screen.getByText("deepseek-v4-flash")).toBeVisible();
    expect(screen.getByText("稳健发言，优先找逻辑漏洞。")).toBeVisible();
    expect(screen.getAllByText("控场").length).toBeGreaterThan(0);
    expect(screen.getByText("票型会说话")).toBeVisible();
    expect(screen.getByRole("img", { name: "月下猎人 头像" })).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
    expect(screen.getByRole("region", { name: "玩家策略雷达" })).toHaveClass(
      "mobile-archive-card",
    );
  });

  it("shows an empty state when the player id is missing from the atlas", async () => {
    gameClientMocks.getPublicPlayerProfile.mockRejectedValue(new ApiError(404));
    renderPlayerDetailRoute("/players/unknown-player");

    expect(await screen.findByText("未找到玩家档案")).toBeVisible();
  });

  it("keeps profile content readable when favorites are unavailable", async () => {
    gameClientMocks.listPlayerProfileFavorites.mockRejectedValue(
      new Error("session unavailable"),
    );

    renderPlayerDetailRoute();

    expect(await screen.findByText("月下猎人")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("收藏状态暂不可用");
    expect(screen.getByText("玩家档案")).toBeVisible();
  });
});
