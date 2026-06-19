import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlaybackPage } from "./PlaybackPage";
import type { GamePlayback, LiveGameEvent } from "@werewolf-arena/game-client";

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
    const events: LiveGameEvent[] = [
      {
        id: 1,
        type: "game_started",
        run_id: "playback_session-1",
        session_id: "session-1",
        created_at: "2026-06-19T00:00:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: {
          players: [
            { name: "阿青", role: "villager", model: "test-model" },
            { name: "白石", role: "werewolf", model: "test-model" },
          ],
        },
      },
      {
        id: 2,
        type: "round_started",
        run_id: "playback_session-1",
        session_id: "session-1",
        created_at: "2026-06-19T00:00:01Z",
        round: 1,
        phase: null,
        actor: null,
        action: null,
        payload: {
          active_players: ["阿青", "白石"],
        },
      },
      {
        id: 3,
        type: "state_updated",
        run_id: "playback_session-1",
        session_id: "session-1",
        created_at: "2026-06-19T00:00:02Z",
        round: 1,
        phase: "day",
        actor: null,
        action: null,
        payload: {
          exiled: "白石",
          public_summary: "白石被投票放逐。",
          summaries: { 阿青: "锁定狼人" },
          active_players: ["阿青"],
        },
      },
      {
        id: 4,
        type: "game_completed",
        run_id: "playback_session-1",
        session_id: "session-1",
        created_at: "2026-06-19T00:00:03Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: {
          winner: "villagers",
        },
      },
    ];
    const playback: GamePlayback = {
      session_id: "session-1",
      status: "complete",
      rule_set: null,
      resumable: false,
      events,
    };

    gameClientMocks.getGamePlayback.mockResolvedValue(playback);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders mobile playback details for the replay route game id", async () => {
    renderPlaybackRoute();

    expect(await screen.findByRole("heading", { name: "移动复盘" })).toBeVisible();
    expect(await screen.findByText("session-1")).toBeVisible();
    expect(screen.getByText("villagers")).toBeVisible();
    expect(screen.getByText("第 1 轮")).toBeVisible();
    expect(screen.getByText("白石被投票放逐。")).toBeInTheDocument();
    expect(gameClientMocks.getGamePlayback).toHaveBeenCalledWith("session-1");
  });
});
