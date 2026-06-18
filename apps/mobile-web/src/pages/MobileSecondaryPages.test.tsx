import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";
import { PlaybackPage } from "./PlaybackPage";
import { PlayersPage } from "./PlayersPage";
import { SettingsPage } from "./SettingsPage";

vi.mock("../api/playerProfilesApi", () => ({
  listPlayerProfiles: vi.fn(async () => ({
    profiles: [
      {
        appearance_id: "raven",
        avatar_image_url: "/avatars/raven.png",
        display_name: "夜鸦",
        favorite: true,
        id: "p1",
        model: "deepseek-v4-flash",
        personality_id: "oracle",
        short_description: "冷静观察者",
        tags: ["推理"],
        updated_at: "2026-06-18T00:00:00Z",
      },
    ],
  })),
}));

vi.mock("../api/gamesApi", () => ({
  getGamePlayback: vi.fn(async () => ({
    events: [
      {
        action: null,
        actor: null,
        created_at: "2026-06-18T00:00:00Z",
        id: 1,
        payload: { summary: "夜幕降临" },
        phase: "night",
        round: 1,
        run_id: "playback_session_1",
        session_id: "session_1",
        type: "game_started",
      },
    ],
    resumable: false,
    rule_set: {
      id: "classic_12",
      name: "经典 12 人",
      player_count: 12,
      roles: [],
      version: "1",
    },
    session_id: "session_1",
    status: "complete",
  })),
  listGames: vi.fn(async () => ({
    sessions: [
      {
        created_at: "2026-06-18T00:00:00Z",
        resumable: false,
        round_count: 4,
        session_id: "session_1",
        status: "complete",
        winner: "villagers",
      },
    ],
  })),
  listModelOptions: vi.fn(async () => ({
    models: [{ id: "deepseek-v4-flash", label: "DeepSeek" }],
  })),
  listRuleSets: vi.fn(async () => ({
    rule_sets: [
      {
        id: "classic_12",
        name: "经典 12 人",
        player_count: 12,
        roles: [],
        version: "1",
      },
    ],
  })),
  resumeGameRun: vi.fn(),
}));

vi.mock("../api/healthApi", () => ({
  getHealth: vi.fn(async () => ({ status: "ok" })),
}));

function renderWithClient(ui: ReactNode, path = "/") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("mobile secondary pages", () => {
  it("renders player library", async () => {
    renderWithClient(<PlayersPage />);

    expect(await screen.findByText("夜鸦")).toBeInTheDocument();
  });

  it("renders history cards", async () => {
    renderWithClient(<HistoryPage />);

    expect(await screen.findByText("session_1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "复盘" })).toHaveAttribute(
      "href",
      "/playback/session_1",
    );
  });

  it("renders playback events", async () => {
    renderWithClient(
      <Routes>
        <Route path="/playback/:sessionId" element={<PlaybackPage />} />
      </Routes>,
      "/playback/session_1",
    );

    expect(await screen.findByText("game_started")).toBeInTheDocument();
    expect(screen.getByText(/夜幕降临/)).toBeInTheDocument();
  });

  it("renders settings health and defaults", async () => {
    renderWithClient(<SettingsPage />);

    expect(await screen.findByText("API 正常")).toBeInTheDocument();
    expect(screen.getByText("经典 12 人")).toBeInTheDocument();
  });
});
