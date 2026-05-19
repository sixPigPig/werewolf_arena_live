import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppTheme } from "../app/AppTheme";
import {
  createTestQueryClient,
  renderWithClient,
} from "../tests/renderWithClient";
import { GameHistoryPage } from "./GameHistoryPage";

describe("GameHistoryPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders available game sessions", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          sessions: [
            {
              session_id: "game_00000001",
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

    renderWithClient(<GameHistoryPage />, "/games/history");

    expect(screen.getByRole("heading", { name: "对局历史" })).toBeInTheDocument();
    const nav = screen.getByTestId("arena-global-nav");
    expect(nav).toHaveAttribute("data-variant", "global");
    expect(nav).toHaveAttribute("data-surface", "transparent");
    expect(nav).toHaveAttribute("data-tone", "ornate");
    expect(nav).toHaveClass(
      "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "min-h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "bg-transparent",
      "border-transparent",
    );
    expect(nav).not.toHaveClass("history-top-nav");
    expect(screen.getByTestId("arena-brand-logo")).toHaveClass(
      "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "w-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
    );
    expect(screen.getByTestId("arena-brand-logo").getAttribute("src")).toContain(
      "langrensha-c-logo",
    );
    expect(screen.getByTestId("arena-brand-wordmark").getAttribute("src")).toContain(
      "langrensha-title-wordmark",
    );
    expect(screen.getByRole("link", { name: "狼人杀竞技场" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(screen.getByRole("link", { name: "返回大厅" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(screen.getByRole("link", { name: "返回大厅" })).toHaveClass(
      "gothic-button",
    );
    expect(screen.getByRole("button", { name: "刷新列表" })).toHaveClass(
      "gothic-button",
    );
    expect(await screen.findByText("game_00000001")).toBeInTheDocument();
    expect(screen.getByText("狼人阵营")).toBeInTheDocument();
    expect(screen.getByTestId("games-sessions-module")).toHaveClass(
      "glass-panel",
    );
    expect(
      screen.getByRole("link", { name: "播放 game_00000001" }),
    ).toHaveAttribute("href", "/games/playback/game_00000001");
  });

  it("refreshes the history list", async () => {
    let gamesRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games")) {
        gamesRequests += 1;
        return Promise.resolve(
          new Response(
            JSON.stringify({
              sessions:
                gamesRequests === 1
                  ? []
                  : [
                      {
                        session_id: "game_00000002",
                        status: "complete",
                        winner: "好人阵营",
                        round_count: 5,
                        created_at: "2026-04-24T12:00:00Z",
                      },
                    ],
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }

      return Promise.resolve(new Response(null, { status: 404 }));
    });

    renderWithClient(<GameHistoryPage />, "/games/history");

    expect(await screen.findByText("还没有可复盘的对局")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "刷新列表" }));

    expect(await screen.findByText("game_00000002")).toBeInTheDocument();
    expect(screen.getByText("好人阵营")).toBeInTheDocument();
  });

  it("paginates long history lists", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          sessions: Array.from({ length: 8 }, (_, index) => ({
            session_id: `game_${String(index + 1).padStart(8, "0")}`,
            status: "complete",
            winner: index % 2 === 0 ? "狼人阵营" : "好人阵营",
            round_count: index + 1,
            created_at: "2026-04-24T10:00:00Z",
          })),
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderWithClient(<GameHistoryPage />, "/games/history");

    expect(await screen.findByText("game_00000001")).toBeInTheDocument();
    expect(screen.queryByText("game_00000008")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByText("game_00000008")).toBeInTheDocument();
    expect(screen.queryByText("game_00000001")).not.toBeInTheDocument();
  });

  it("resumes a resumable session from the list", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/game_1200abcd/resume")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_resumed",
              session_id: "game_1200abcd",
              villager_model: "Qwen3.6-Plus",
              werewolf_model: "MiniMax-M2.7",
              seed: 21,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-04-24T12:05:00Z",
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
        new Response(
          JSON.stringify({
            sessions: [
              {
                session_id: "game_1200abcd",
                status: "partial",
                winner: null,
                round_count: 1,
                created_at: "2026-04-24T12:00:00Z",
                resumable: true,
              },
            ],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games/history" element={<GameHistoryPage />} />
        <Route
          path="/games/live/run_resumed"
          element={<p>继续后的实时观战</p>}
        />
      </Routes>,
      "/games/history",
    );

    expect(
      await screen.findByText("game_1200abcd"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "播放 game_1200abcd" }),
    ).toHaveAttribute("href", "/games/playback/game_1200abcd");
    await userEvent.click(screen.getByRole("button", { name: "继续对局" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/game_1200abcd/resume",
      expect.objectContaining({ method: "POST" }),
    );
    expect(await screen.findByText("继续后的实时观战")).toBeInTheDocument();
  });

  it("renders an empty state when no sessions exist", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithClient(<GameHistoryPage />, "/games/history");

    expect(await screen.findByText("还没有可复盘的对局")).toBeInTheDocument();
  });

  it("renders only the error state when refreshing cached sessions fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 500 }),
    );

    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["games"], {
      sessions: [
        {
          session_id: "game_00000004",
          status: "complete",
          winner: "狼人阵营",
          round_count: 3,
          created_at: null,
        },
      ],
    });

    render(
      <AppTheme>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/games/history"]}>
            <GameHistoryPage />
          </MemoryRouter>
        </QueryClientProvider>
      </AppTheme>,
    );

    expect(await screen.findByText("无法读取对局列表")).toBeInTheDocument();
    expect(screen.queryByText("game_00000004")).not.toBeInTheDocument();
  });
});
