import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText("控场")).toBeVisible();
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeVisible();
  });
});
