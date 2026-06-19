import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlaybackPage } from "./PlaybackPage";

const gameClientMocks = vi.hoisted(() => ({
  getGamePlayback: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    getGamePlayback: gameClientMocks.getGamePlayback,
  };
});

function renderPlaybackRoute() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [{ path: "/games/:gameId/replay", element: <PlaybackPage /> }],
    { initialEntries: ["/games/session-1/replay"] },
  );

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("PlaybackPage", () => {
  beforeEach(() => {
    gameClientMocks.getGamePlayback.mockResolvedValue({
      session_id: "session-1",
      status: "complete",
      state: {
        session_id: "session-1",
        players: [
          { name: "阿青", role: "villager", model: "test-model" },
          { name: "白石", role: "werewolf", model: "test-model" },
        ],
        rounds: [
          {
            number: 1,
            players: ["阿青", "白石"],
            eliminated: null,
            protected: null,
            investigated: null,
            exiled: "白石",
            debate: [],
            bids: [],
            votes: [],
            summaries: { 阿青: "锁定狼人" },
            success: true,
          },
        ],
        winner: "villagers",
        error_message: "",
      },
      logs: [],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders mobile playback details for the replay route game id", async () => {
    renderPlaybackRoute();

    expect(await screen.findByRole("heading", { name: "移动复盘" })).toBeVisible();
    expect(await screen.findByText("session-1")).toBeVisible();
    expect(screen.getByText("villagers")).toBeVisible();
    expect(gameClientMocks.getGamePlayback).toHaveBeenCalledWith("session-1");
  });
});
