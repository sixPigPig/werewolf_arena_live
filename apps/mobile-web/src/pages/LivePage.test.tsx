import { readFileSync } from "node:fs";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LivePage } from "./LivePage";
import type { GameRun, LiveGameEvent } from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  getGameRun: vi.fn(),
  resumeGameRun: vi.fn(),
  useGameRunEvents: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    getGameRun: gameClientMocks.getGameRun,
    resumeGameRun: gameClientMocks.resumeGameRun,
    useGameRunEvents: gameClientMocks.useGameRunEvents,
  };
});

const run: GameRun = {
  run_id: "run-1",
  session_id: "session-1",
  villager_model: "test-model",
  werewolf_model: "test-model",
  rule_set: {
    id: "classic_8",
    version: "test",
    name: "经典 8 人",
    player_count: 8,
    roles: [],
  },
  seed: null,
  max_rounds: 8,
  winner: null,
  status: "running",
  created_at: "2026-06-19T00:00:00Z",
  started_at: "2026-06-19T00:00:01Z",
  completed_at: null,
  error: null,
  event_count: 1,
};

const gameStartedEvent: LiveGameEvent = {
  id: 1,
  type: "game_started",
  run_id: "run-1",
  session_id: "session-1",
  created_at: "2026-06-19T00:00:02Z",
  round: 1,
  phase: "day",
  actor: null,
  action: null,
  payload: {
    players: [
      {
        name: "阿青",
        role: "villager",
        model: "test-model",
        avatar_image_url: "/player-avatars/gothic-female-1.png",
      },
      { name: "白石", role: "werewolf", model: "test-model" },
      { name: "南风", role: "seer", model: "test-model" },
      { name: "木子", role: "witch", model: "test-model" },
    ],
  },
};

function renderLiveRoute() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      { path: "/games/:gameId/live", element: <LivePage /> },
      { path: "/games/:gameId/replay", element: <h1>移动复盘</h1> },
    ],
    { initialEntries: ["/games/run-1/live"] },
  );

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { router };
}

describe("LivePage", () => {
  beforeEach(() => {
    gameClientMocks.getGameRun.mockResolvedValue(run);
    gameClientMocks.resumeGameRun.mockResolvedValue(run);
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent],
      latestEvent: gameStartedEvent,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders mobile live details for the route game id", async () => {
    renderLiveRoute();

    expect(
      await screen.findByRole("heading", { name: "实时观战" }),
    ).toHaveClass("mobile-sr-only");
    expect(
      screen.getByRole("button", { name: "返回对局大厅" }),
    ).toBeVisible();
    expect((await screen.findAllByText("经典 8 人"))[0]).toBeVisible();
    expect(screen.getByText("连接正常")).toBeVisible();
    expect(screen.getByText("game_started")).toBeVisible();
    expect(screen.getByText("第 1 天")).toBeVisible();
    expect(
      screen.getByRole("region", { name: "玩家席位" }),
    ).toBeVisible();
    expect(
      screen.getByRole("article", { name: "1号 阿青 平民 存活" }),
    ).toBeVisible();
    expect(
      screen.getByRole("article", { name: "4号 木子 女巫 存活" }),
    ).toBeVisible();
    expect(gameClientMocks.getGameRun).toHaveBeenCalledWith("run-1");
    expect(gameClientMocks.useGameRunEvents).toHaveBeenCalledWith("run-1");
  });

  it("renders live seat avatars through API asset URLs", async () => {
    renderLiveRoute();

    const seat = await screen.findByRole("article", {
      name: "1号 阿青 平民 存活",
    });
    const avatar = seat.querySelector("img");

    expect(avatar).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });

  it("hides the bottom mobile tab bar on the immersive live page", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const tabBarRule =
      styles.match(
        /\.mobile-app-shell:has\(\.mobile-live-page\) \.mobile-tab-bar\s*{[^}]+}/,
      )?.[0] ?? "";
    const contentRegionRule =
      styles.match(
        /\.mobile-app-shell:has\(\.mobile-live-page\) \.mobile-content-region\s*{[^}]+}/,
      )?.[0] ?? "";

    expect(tabBarRule).toContain("display: none");
    expect(contentRegionRule).toContain("padding-bottom: 0");
  });

  it("compresses theater seats on short phone screens", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");

    expect(styles).toMatch(
      /@media \(max-height: 700px\) {[\s\S]*?\.mobile-live-seat-avatar\s*{[^}]+width: clamp\(32px, 10\.8vw, 40px\)/,
    );
    expect(styles).toMatch(
      /@media \(max-height: 700px\) {[\s\S]*?\.mobile-live-seat small\s*{[^}]+display: none/,
    );
  });
});
