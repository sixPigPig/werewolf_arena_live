import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createTestQueryClient,
  renderWithClient,
} from "../tests/renderWithClient";
import { GamesPage } from "./GamesPage";

describe("GamesPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders available game sessions", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          sessions: [
            {
              session_id: "session_20260424_001",
              status: "complete",
              winner: "狼人阵营",
              round_count: 4,
              created_at: "2026-04-24T10:00:00Z",
            },
          ],
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderWithClient(<GamesPage />, "/games");

    expect(
      screen.getByRole("heading", { name: "狼人杀对局复盘" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("session_20260424_001")).toBeInTheDocument();
    expect(screen.getByText("狼人阵营")).toBeInTheDocument();
  });

  it("renders an empty state when no sessions exist", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithClient(<GamesPage />, "/games");

    expect(await screen.findByText("还没有可复盘的对局")).toBeInTheDocument();
  });

  it("creates a live game run and navigates to the live page", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_1234abcd",
              session_id: "session_20260424_120000_ab12cd34",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              seed: null,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-04-24T12:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route
          path="/games/live/:runId"
          element={<p>实时观战 run_1234abcd</p>}
        />
      </Routes>,
      "/games",
    );

    await userEvent.click(
      await screen.findByRole("button", { name: "发起对局" }),
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({ method: "POST" }),
    );
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("renders only the error state when refreshing cached sessions fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 500 }),
    );

    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["games"], {
      sessions: [
        {
          session_id: "session_cached",
          status: "complete",
          winner: "狼人阵营",
          round_count: 3,
          created_at: null,
        },
      ],
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/games"]}>
          <GamesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("无法读取对局列表")).toBeInTheDocument();
    expect(screen.queryByText("session_cached")).not.toBeInTheDocument();
  });
});
