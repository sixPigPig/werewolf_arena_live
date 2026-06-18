import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createGameRun, listGames } from "../api/gamesApi";
import type { GameRun, GameSessionSummary } from "../api/types";
import { GameHomePage } from "./GameHomePage";

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
  listGames: vi.fn(),
}));

const gameRunFixture = {
  run_id: "run_mobile_1",
  session_id: "session_mobile_1",
  villager_model: "deepseek-v4-flash",
  werewolf_model: "deepseek-v4-flash",
  seed: null,
  max_rounds: 8,
  rule_set_id: "classic_12",
  rule_set: {
    id: "classic_12",
    version: "1",
    name: "经典 12 人",
    player_count: 12,
    roles: [],
  },
  player_configs: [],
  lineup_quality_warnings: [],
  status: "queued",
  created_at: "2026-06-18T00:00:00Z",
  started_at: null,
  completed_at: null,
  winner: null,
  error: null,
  event_count: 1,
} satisfies GameRun;

const recentSessionFixture = {
  session_id: "session_recent",
  status: "complete",
  winner: "werewolves",
  round_count: 6,
  created_at: "2026-06-17T00:00:00Z",
  rule_set: {
    id: "classic_12",
    version: "1",
    name: "经典 12 人",
    player_count: 12,
    roles: [],
  },
  resumable: false,
} satisfies GameSessionSummary;

function renderGameHomePage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <GameHomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GameHomePage", () => {
  beforeEach(() => {
    vi.mocked(createGameRun).mockReset();
    vi.mocked(listGames).mockReset();
    navigateMock.mockReset();
    vi.mocked(listGames).mockResolvedValue({ sessions: [] });
  });

  it("starts a one-click game and navigates to the live run", async () => {
    vi.mocked(createGameRun).mockResolvedValue(gameRunFixture);

    renderGameHomePage();

    await userEvent.click(screen.getByRole("button", { name: "一键开局" }));

    expect(createGameRun).toHaveBeenCalledWith({
      max_rounds: 8,
      player_configs: [],
    });
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/live/run_mobile_1");
    });
  });

  it("renders the recent game status", async () => {
    vi.mocked(listGames).mockResolvedValue({
      sessions: [recentSessionFixture],
    });

    renderGameHomePage();

    expect(screen.getByText("最近对局")).toBeInTheDocument();
    expect(await screen.findByText("session_recent")).toBeInTheDocument();
  });
});
