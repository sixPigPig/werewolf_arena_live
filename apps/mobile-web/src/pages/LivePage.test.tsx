import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { LivePage } from "./LivePage";

vi.mock("../api/gamesApi", () => ({
  getGameRun: vi.fn(async () => ({
    completed_at: null,
    created_at: "2026-06-18T00:00:00Z",
    error: null,
    event_count: 1,
    lineup_quality_warnings: [],
    max_rounds: 8,
    player_configs: [],
    rule_set: {
      id: "classic_12",
      name: "经典 12 人",
      player_count: 12,
      roles: [],
      version: "1",
    },
    rule_set_id: "classic_12",
    run_id: "run_live",
    seed: null,
    session_id: "session_live",
    started_at: "2026-06-18T00:00:01Z",
    status: "running",
    villager_model: "deepseek-v4-flash",
    werewolf_model: "deepseek-v4-flash",
    winner: null,
  })),
}));

vi.mock("../features/live/useMobileGameRunEvents", () => ({
  useMobileGameRunEvents: () => ({
    connectionState: "open",
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
  }),
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
  it("renders stage-first live information", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "实时舞台" }),
    ).toBeInTheDocument();
    expect(screen.getByText("连接正常")).toBeInTheDocument();
    expect(screen.getAllByText("phase_started").length).toBeGreaterThan(0);
    expect(await screen.findByText("经典 12 人")).toBeInTheDocument();
  });
});
