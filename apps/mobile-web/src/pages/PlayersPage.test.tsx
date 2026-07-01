import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlayersPage } from "./PlayersPage";
import type { VirtualPlayerProfile } from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  listPlayerProfiles: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    listPlayerProfiles: gameClientMocks.listPlayerProfiles,
  };
});

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
    avatar_asset_id: profileOverrides.avatar_asset_id ?? null,
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

function renderWithQueryClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("PlayersPage", () => {
  beforeEach(() => {
    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [
        buildProfile({
          id: "moon-hunter",
          display_name: "月下猎人",
          model: "deepseek-v4-flash",
          short_description: "冷静复盘型玩家",
          speaking_style: "短句推进",
          favorite: true,
          tags: ["控场"],
        }),
      ],
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
    const tags = screen.getByRole("list", { name: "玩家标签" });
    expect(within(tags).getByRole("listitem")).toHaveTextContent("控场");
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeVisible();
  });

  it("renders player avatars through API asset URLs", async () => {
    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [
        buildProfile({
          id: "moon-hunter",
          display_name: "月下猎人",
          avatar_asset_id: "system-gothic-female-1",
          avatar_image_url: "/player-avatars/gothic-female-1.png",
          avatar_image_mime: "image/png",
        }),
      ],
    });

    renderWithQueryClient(<PlayersPage />);

    const avatar = await screen.findByRole("img", { name: "月下猎人 头像" });
    expect(avatar).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });

  it("shows loading copy while reading player profiles", () => {
    gameClientMocks.listPlayerProfiles.mockReturnValue(new Promise(() => undefined));

    renderWithQueryClient(<PlayersPage />);

    expect(screen.getByText("正在读取玩家档案...")).toBeVisible();
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeVisible();
  });

  it("shows an alert when player profiles cannot be read", async () => {
    gameClientMocks.listPlayerProfiles.mockRejectedValue(new Error("network down"));

    renderWithQueryClient(<PlayersPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("无法读取玩家档案");
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeVisible();
  });

  it("shows empty copy when the player library has no profiles", async () => {
    gameClientMocks.listPlayerProfiles.mockResolvedValue({ profiles: [] });

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
    expect(source).toContain(
      'useQuery({\n    queryKey: ["player-profiles"],\n    queryFn: listPlayerProfiles,\n  })',
    );
  });
});
