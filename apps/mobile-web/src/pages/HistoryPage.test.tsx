import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";
import type { GameRun, GameSessionSummary } from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  listGames: vi.fn(),
  resumeGameRun: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    listGames: gameClientMocks.listGames,
    resumeGameRun: gameClientMocks.resumeGameRun,
  };
});

const resumedRun: GameRun = {
  run_id: "run-resumed",
  session_id: "session-1",
  villager_model: "test-model",
  werewolf_model: "test-model",
  seed: null,
  max_rounds: 8,
  winner: null,
  status: "queued",
  created_at: "2026-06-19T00:00:00Z",
  started_at: null,
  completed_at: null,
  error: null,
  event_count: 0,
};

function renderHistoryRoute() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      { path: "/history", element: <HistoryPage /> },
      { path: "/games/:gameId/live", element: <h1>实时观战</h1> },
      { path: "/games/:gameId/replay", element: <h1>移动复盘</h1> },
    ],
    { initialEntries: ["/history"] },
  );

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { router };
}

function buildSession(overrides: Partial<GameSessionSummary> = {}): GameSessionSummary {
  return {
    session_id: "session-1",
    status: "partial",
    winner: null,
    round_count: 3,
    created_at: "2026-06-19T00:00:00Z",
    rule_set: {
      id: "classic_8",
      version: "test",
      name: "经典 8 人",
      player_count: 8,
      roles: [],
    },
    resumable: true,
    ...overrides,
  };
}

describe("HistoryPage", () => {
  beforeEach(() => {
    gameClientMocks.listGames.mockResolvedValue({ sessions: [buildSession()] });
    gameClientMocks.resumeGameRun.mockResolvedValue(resumedRun);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders resumable sessions with resume and replay actions", async () => {
    const user = userEvent.setup();
    const { router } = renderHistoryRoute();

    expect(await screen.findByText("session-1")).toBeVisible();
    expect(screen.getByText("经典 8 人")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "查看复盘 session-1" }),
    ).toHaveAttribute("href", "/games/session-1/replay");

    await user.click(screen.getByRole("button", { name: "继续对局 session-1" }));

    await waitFor(() => {
      expect(gameClientMocks.resumeGameRun).toHaveBeenCalledWith("session-1");
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/games/run-resumed/live");
    });
  });

  it("does not show resume for partial sessions without a checkpoint", async () => {
    gameClientMocks.listGames.mockResolvedValue({
      sessions: [buildSession({ resumable: false })],
    });

    renderHistoryRoute();

    expect(await screen.findByText("session-1")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "继续对局 session-1" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "查看复盘 session-1" }),
    ).toHaveAttribute("href", "/games/session-1/replay");
  });

  it("shows replay for complete non-resumable sessions", async () => {
    gameClientMocks.listGames.mockResolvedValue({
      sessions: [
        buildSession({
          resumable: false,
          status: "complete",
          winner: "villagers",
        }),
      ],
    });

    renderHistoryRoute();

    expect(await screen.findByText("session-1")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "继续对局 session-1" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "查看复盘 session-1" }),
    ).toHaveAttribute("href", "/games/session-1/replay");
  });
});
