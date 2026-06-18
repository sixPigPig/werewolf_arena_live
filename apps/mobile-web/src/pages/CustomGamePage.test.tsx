import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createGameRun,
  listModelOptions,
  listRuleSets,
} from "../api/gamesApi";
import { listPlayerProfiles } from "../api/playerProfilesApi";
import type { GameRun } from "../api/types";
import { CustomGamePage } from "./CustomGamePage";

const navigateMock = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );

  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("../api/gamesApi", () => ({
  createGameRun: vi.fn(),
  listModelOptions: vi.fn(),
  listRuleSets: vi.fn(),
}));

vi.mock("../api/playerProfilesApi", () => ({
  listPlayerProfiles: vi.fn(),
}));

const gameRunFixture = {
  run_id: "custom_run",
  session_id: "session_custom",
  villager_model: "deepseek-v4-flash",
  werewolf_model: "deepseek-v4-flash",
  seed: null,
  max_rounds: 8,
  rule_set_id: "classic_12",
  rule_set: {
    id: "classic_12_seer_witch_hunter_idiot",
    version: "1",
    name: "经典 12 人",
    player_count: 12,
    roles: [],
  },
  player_configs: [{ seat: 1, profile_id: "p1" }],
  lineup_quality_warnings: [],
  status: "queued",
  created_at: "2026-06-18T00:00:00Z",
  started_at: null,
  completed_at: null,
  winner: null,
  error: null,
  event_count: 1,
} satisfies GameRun;

function renderCustomGamePage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CustomGamePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CustomGamePage", () => {
  beforeEach(() => {
    vi.mocked(createGameRun).mockReset();
    vi.mocked(listModelOptions).mockReset();
    vi.mocked(listRuleSets).mockReset();
    vi.mocked(listPlayerProfiles).mockReset();
    navigateMock.mockReset();

    vi.mocked(listRuleSets).mockResolvedValue({
      rule_sets: [
        {
          id: "classic_12",
          version: "1",
          name: "经典 12 人",
          player_count: 12,
        },
      ],
    });
    vi.mocked(listModelOptions).mockResolvedValue({
      models: [{ id: "deepseek-v4-flash", label: "DeepSeek V4 Flash" }],
    });
    vi.mocked(listPlayerProfiles).mockResolvedValue({
      profiles: [
        {
          id: "p1",
          display_name: "夜鸦",
          model: "deepseek-v4-flash",
          personality_id: "oracle",
          appearance_id: "raven",
          avatar_image_url: "/avatars/raven.png",
          short_description: "冷静观察的玩家",
          favorite: true,
          tags: ["推理"],
          updated_at: "2026-06-18T00:00:00Z",
        },
      ],
    });
    vi.mocked(createGameRun).mockResolvedValue(gameRunFixture);
  });

  it("creates a custom game from the wizard selections", async () => {
    renderCustomGamePage();

    await screen.findByText("经典 12 人");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /夜鸦/ }));
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "确认开局" }));

    expect(createGameRun).toHaveBeenCalledWith({
      rule_set_id: "classic_12",
      villager_model: "deepseek-v4-flash",
      werewolf_model: "deepseek-v4-flash",
      max_rounds: 8,
      player_configs: [{ seat: 1, profile_id: "p1" }],
    });
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/live/custom_run");
    });
  });

  it("caps custom max rounds before creating the game", async () => {
    const user = userEvent.setup();
    renderCustomGamePage();

    await screen.findByText("经典 12 人");
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("checkbox", { name: /夜鸦/ }));
    await user.click(screen.getByRole("button", { name: "下一步" }));

    const maxRoundsInput = screen.getByRole("spinbutton", {
      name: "最大轮数",
    });
    await user.clear(maxRoundsInput);
    await user.type(maxRoundsInput, "24");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "确认开局" }));

    expect(createGameRun).toHaveBeenCalledWith(
      expect.objectContaining({ max_rounds: 20 }),
    );
  });

  it("prevents selecting more players than the active rule supports", async () => {
    const user = userEvent.setup();
    vi.mocked(listRuleSets).mockResolvedValue({
      rule_sets: [
        {
          id: "solo_test",
          version: "1",
          name: "单人测试",
          player_count: 1,
        },
      ],
    });
    vi.mocked(listPlayerProfiles).mockResolvedValue({
      profiles: [
        {
          id: "p1",
          display_name: "夜鸦",
          model: "deepseek-v4-flash",
          personality_id: "oracle",
          appearance_id: "raven",
          avatar_image_url: "/avatars/raven.png",
          short_description: "冷静观察的玩家",
          favorite: true,
          tags: ["推理"],
          updated_at: "2026-06-18T00:00:00Z",
        },
        {
          id: "p2",
          display_name: "烛影",
          model: "deepseek-v4-flash",
          personality_id: "balanced",
          appearance_id: "default",
          avatar_image_url: "/avatars/candle.png",
          short_description: "谨慎发言的玩家",
          favorite: false,
          tags: ["发言"],
          updated_at: "2026-06-18T00:00:00Z",
        },
      ],
    });

    renderCustomGamePage();

    await screen.findByText("单人测试");
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("checkbox", { name: /夜鸦/ }));

    expect(screen.getByText("已选 1 / 1 人")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /烛影/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "确认开局" }));

    expect(createGameRun).toHaveBeenCalledWith(
      expect.objectContaining({
        player_configs: [{ seat: 1, profile_id: "p1" }],
        rule_set_id: "solo_test",
      }),
    );
  });
});
