import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getGameRun } from "../api/gamesApi";
import { useMobileGameRunEvents } from "../features/live/useMobileGameRunEvents";

import { LivePage } from "./LivePage";

const liveEventsFixture = {
  connectionState: "open" as const,
  events: [
    {
      action: null,
      actor: null,
      created_at: "2026-06-18T00:00:02Z",
      id: 1,
      payload: { phase: "day", round: 2 },
      phase: "day",
      round: 2,
      run_id: "run_live",
      session_id: "session_live",
      type: "phase_started",
    },
  ],
  latestEvent: {
    action: null,
    actor: null,
    created_at: "2026-06-18T00:00:02Z",
    id: 1,
    payload: { phase: "day", round: 2 },
    phase: "day",
    round: 2,
    run_id: "run_live",
    session_id: "session_live",
    type: "phase_started",
  },
};

vi.mock("../api/gamesApi", () => ({
  getGameRun: vi.fn(),
}));

vi.mock("../features/live/useMobileGameRunEvents", () => ({
  useMobileGameRunEvents: vi.fn(),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/live/run_live"]}>
        <Routes>
          <Route path="/live/:runId" element={<LivePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LivePage", () => {
  beforeEach(() => {
    vi.mocked(getGameRun).mockReset();
    vi.mocked(useMobileGameRunEvents).mockReset();
    vi.mocked(getGameRun).mockResolvedValue({
      completed_at: null,
      created_at: "2026-06-18T00:00:00Z",
      error: null,
      event_count: 1,
      lineup_quality_warnings: [],
      max_rounds: 8,
      player_configs: [],
      rule_set: {
        id: "classic_12_seer_witch_hunter_idiot",
        name: "经典 12 人",
        player_count: 12,
        roles: [],
        version: "1",
      },
      rule_set_id: "classic_12_seer_witch_hunter_idiot",
      run_id: "run_live",
      seed: null,
      session_id: "session_live",
      started_at: "2026-06-18T00:00:01Z",
      status: "running",
      villager_model: "deepseek-v4-flash",
      werewolf_model: "deepseek-v4-flash",
      winner: null,
    });
    vi.mocked(useMobileGameRunEvents).mockReturnValue(liveEventsFixture);
  });

  it("renders stage-first live information", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "实时舞台" }),
    ).toBeInTheDocument();
    expect(screen.getByText("连接正常")).toBeInTheDocument();
    expect(screen.getAllByText("phase_started").length).toBeGreaterThan(0);
    expect(await screen.findByText("经典 12 人")).toBeInTheDocument();
  });

  it("does not open the event stream until the run lookup succeeds", async () => {
    vi.mocked(getGameRun).mockRejectedValue(new Error("missing run"));
    vi.mocked(useMobileGameRunEvents).mockReturnValue({
      connectionState: "idle",
      events: [],
      latestEvent: null,
    });

    renderPage();

    expect(await screen.findByText("无法读取实时对局")).toBeInTheDocument();
    expect(useMobileGameRunEvents).toHaveBeenCalledWith(undefined);
  });
});
