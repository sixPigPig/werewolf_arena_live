import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createGameRun, listGames, listRuleSets } from "../api/gamesApi";
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
  listRuleSets: vi.fn(),
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
    id: "classic_12_seer_witch_hunter_idiot",
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
    id: "classic_12_seer_witch_hunter_idiot",
    version: "1",
    name: "经典 12 人",
    player_count: 12,
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
    vi.mocked(listRuleSets).mockReset();
    navigateMock.mockReset();
    vi.mocked(listGames).mockResolvedValue({ sessions: [] });
    vi.mocked(listRuleSets).mockResolvedValue({
      rule_sets: [
        {
          id: "classic_8",
          version: "1",
          name: "经典 8 人",
          player_count: 8,
          role_summary: "狼人 2 · 好人 6",
        },
        {
          id: "classic_12_seer_witch_hunter_idiot",
          version: "1",
          name: "经典 12 人",
          player_count: 12,
          role_summary: "预女猎白",
        },
      ],
    });
  });

  it("starts a quick game only after confirming the selected rule", async () => {
    vi.mocked(createGameRun).mockResolvedValue({
      ...gameRunFixture,
      rule_set_id: "classic_8",
      rule_set: {
        id: "classic_8",
        version: "1",
        name: "经典 8 人",
        player_count: 8,
        roles: [],
      },
    });

    renderGameHomePage();

    await screen.findByRole("radio", { name: /经典 8 人/ });

    expect(
      screen.queryByRole("button", { name: "快速开局" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: /经典 8 人/ }));
    await userEvent.click(screen.getByRole("button", { name: "确认规则" }));
    await userEvent.click(screen.getByRole("button", { name: "快速开局" }));

    expect(createGameRun).toHaveBeenCalledWith({
      max_rounds: 8,
      player_configs: [],
      rule_set_id: "classic_8",
    });
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/live/run_mobile_1");
    });
  });

  it("links custom start to the confirmed rule", async () => {
    renderGameHomePage();

    await screen.findByRole("radio", { name: /经典 8 人/ });
    await userEvent.click(screen.getByRole("radio", { name: /经典 8 人/ }));
    await userEvent.click(screen.getByRole("button", { name: "确认规则" }));

    expect(screen.getByRole("link", { name: "自定义开局" })).toHaveAttribute(
      "href",
      "/custom-game?ruleSetId=classic_8",
    );
  });

  it("renders the recent game status", async () => {
    vi.mocked(listGames).mockResolvedValue({
      sessions: [recentSessionFixture],
    });

    renderGameHomePage();

    expect(screen.getByText("最近对局")).toBeInTheDocument();
    expect(await screen.findByText("session_recent")).toBeInTheDocument();
  });

  it("does not render the old scaffold copy", () => {
    renderGameHomePage();

    expect(screen.queryByText("手机版 Web 正在搭建中")).not.toBeInTheDocument();
  });
});
