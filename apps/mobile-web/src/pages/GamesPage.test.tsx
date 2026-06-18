import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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

  return { router };
}

describe("GamesPage", () => {
  beforeEach(() => {
    gameClientMocks.listRuleSets.mockResolvedValue({
      rule_sets: [classicRuleSet],
    });
    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [
        buildProfile({ id: "profile-1", display_name: "阿青", favorite: true }),
        buildProfile({ id: "profile-2", display_name: "白石" }),
      ],
    });
    gameClientMocks.createGameRun.mockResolvedValue(buildRun());
  });

  afterEach(() => {
    vi.clearAllMocks();
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

  it("blocks creation when the player library cannot fill the selected rule set", async () => {
    const user = userEvent.setup();
    gameClientMocks.listPlayerProfiles.mockResolvedValue({
      profiles: [buildProfile({ id: "profile-1", display_name: "阿青" })],
    });
    renderGamesPage();

    await user.click(await screen.findByRole("button", { name: "随机补齐" }));
    await user.click(screen.getByRole("button", { name: "发起对局" }));

    expect(await screen.findByText("玩家库玩家不足")).toBeVisible();
    expect(gameClientMocks.createGameRun).not.toHaveBeenCalled();
  });
});
