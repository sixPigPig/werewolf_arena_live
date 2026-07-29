import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlayersPage } from "./PlayersPage";
import type { PublicPlayerProfile } from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  listPlayerProfileFavorites: vi.fn(),
  listPublicPlayerProfiles: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    listPlayerProfileFavorites: gameClientMocks.listPlayerProfileFavorites,
    listPublicPlayerProfiles: gameClientMocks.listPublicPlayerProfiles,
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
    personality_text: "",
    short_description: "",
    background_story: "",
    speaking_style: "",
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

function renderWithQueryClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PlayersPage", () => {
  beforeEach(() => {
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({
        id: "moon-hunter",
        display_name: "月下猎人",
        model: "deepseek-v4-flash",
        short_description: "冷静复盘型玩家",
        speaking_style: "短句推进",
        tags: ["控场"],
      }),
    ]);
    gameClientMocks.listPlayerProfileFavorites.mockResolvedValue({
      profile_ids: ["moon-hunter"],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders player profile cards from the player library", async () => {
    renderWithQueryClient(<PlayersPage />);

    expect(await screen.findByText("月下猎人")).toBeVisible();
    expect(screen.getByText("deepseek-v4-flash")).toBeVisible();
    expect(screen.getByText("冷静复盘型玩家")).toBeVisible();
    expect(screen.getByRole("link", { name: "查看月下猎人档案" })).toHaveAttribute(
      "href",
      "/players/moon-hunter",
    );
    const tags = screen.getByRole("list", { name: "玩家标签" });
    expect(within(tags).getByRole("listitem")).toHaveTextContent("控场");
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeVisible();
  });

  it("renders player avatars through API asset URLs", async () => {
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({
        id: "moon-hunter",
        display_name: "月下猎人",
        avatar_image_url:
          "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
      }),
    ]);

    renderWithQueryClient(<PlayersPage />);

    const avatar = await screen.findByRole("img", { name: "月下猎人 头像" });
    expect(avatar).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });

  it("shows admin recommendations independently from user favorites", async () => {
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([
      buildProfile({
        id: "moon-hunter",
        display_name: "月下猎人",
        featured: true,
      }),
    ]);

    renderWithQueryClient(<PlayersPage />);

    expect(await screen.findByText("推荐")).toBeVisible();
    expect(screen.getByText("收藏")).toBeVisible();
  });

  it("shows loading copy while reading player profiles", () => {
    gameClientMocks.listPublicPlayerProfiles.mockReturnValue(
      new Promise(() => undefined),
    );

    renderWithQueryClient(<PlayersPage />);

    expect(screen.getByText("正在读取玩家档案...")).toBeVisible();
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeVisible();
  });

  it("shows an alert when player profiles cannot be read", async () => {
    gameClientMocks.listPublicPlayerProfiles.mockRejectedValue(
      new Error("network down"),
    );

    renderWithQueryClient(<PlayersPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("无法读取玩家档案");
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeVisible();
  });

  it("shows empty copy when the player library has no profiles", async () => {
    gameClientMocks.listPublicPlayerProfiles.mockResolvedValue([]);

    renderWithQueryClient(<PlayersPage />);

    expect(await screen.findByText("暂无玩家档案")).toBeVisible();
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeVisible();
  });

  it("keeps the first version read-only", async () => {
    renderWithQueryClient(<PlayersPage />);

    expect(await screen.findByText("编辑能力不在第一版范围内")).toBeVisible();
    expect(screen.queryByRole("button", { name: /编辑|新增|创建|保存|删除/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /编辑|新增|创建|保存|删除/ })).not.toBeInTheDocument();
  });

  it("relies on the surrounding QueryClientProvider", () => {
    const source = readFileSync("src/pages/PlayersPage.tsx", "utf8");

    expect(source).not.toContain("QueryClientContext");
    expect(source).not.toContain("../lib/query-client");
    expect(source).not.toContain(
      'useQuery({\n    queryKey: ["player-profiles"],\n    queryFn: listPlayerProfiles,\n  })',
    );
    expect(source).toContain("queryKey: publicPlayerProfilesQueryKey");
    expect(source).toContain("queryFn: listPublicPlayerProfiles");
  });

  it("keeps the public catalog readable when favorites are unavailable", async () => {
    gameClientMocks.listPlayerProfileFavorites.mockRejectedValue(
      new Error("session unavailable"),
    );

    renderWithQueryClient(<PlayersPage />);

    expect(await screen.findByText("月下猎人")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("收藏状态暂不可用");
    expect(screen.queryByText("收藏")).not.toBeInTheDocument();
  });

  it("uses the gothic player atlas card system", async () => {
    renderWithQueryClient(<PlayersPage />);

    const card = await screen.findByRole("article", { name: "月下猎人 档案" });
    expect(card).toHaveClass("mobile-archive-card");
    expect(card).toHaveClass("mobile-player-dossier-card");
    expect(screen.getByText("角色档案库")).toBeVisible();
  });
});
