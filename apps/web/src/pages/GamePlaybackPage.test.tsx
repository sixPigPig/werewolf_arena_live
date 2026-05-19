import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppTheme } from "../app/AppTheme";
import { GamePlaybackPage } from "./GamePlaybackPage";

function renderPlaybackRoute(initialEntry = "/games/playback/game_1200abcd") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  const router = createMemoryRouter(
    [
      {
        path: "/games/playback/:sessionId",
        element: <GamePlaybackPage />,
      },
      {
        path: "/games/live/run_resumed",
        element: <h1>继续后的实时观战</h1>,
      },
    ],
    { initialEntries: [initialEntry] },
  );

  render(
    <AppTheme>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AppTheme>,
  );

  return router;
}

function playbackResponse(overrides: Record<string, unknown> = {}) {
  return {
    session_id: "game_1200abcd",
    status: "complete",
    rule_set: {
      id: "starter_2",
      version: "2026.05",
      name: "双人测试局",
      player_count: 2,
      roles: [
        { role: "狼人", count: 1 },
        { role: "村民", count: 1 },
      ],
      role_summary: "1 狼人 / 1 村民",
      sheriff_enabled: false,
    },
    resumable: false,
    events: [
      {
        id: 1,
        type: "game_started",
        run_id: "run_original",
        session_id: "game_1200abcd",
        created_at: "2026-05-19T00:00:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: {
          players: [
            { name: "Alice", role: "狼人", model: "deepseek-chat" },
            { name: "Bob", role: "村民", model: "deepseek-chat" },
          ],
        },
      },
      {
        id: 2,
        type: "game_completed",
        run_id: "run_original",
        session_id: "game_1200abcd",
        created_at: "2026-05-19T00:00:10Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: { winner: "狼人阵营" },
      },
    ],
    ...overrides,
  };
}

describe("GamePlaybackPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders complete playback on the live stage", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(playbackResponse()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderPlaybackRoute();

    expect(await screen.findByText("历史回放")).toBeInTheDocument();
    expect(screen.queryByText("已结束")).not.toBeInTheDocument();
    expect(screen.queryByText("异常中断")).not.toBeInTheDocument();
    expect(screen.getByTestId("live-game-page")).toBeInTheDocument();
    expect(screen.getByText("观赛舞台")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看复盘" })).toHaveAttribute(
      "href",
      "/games/game_1200abcd",
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/games/game_1200abcd/playback",
      undefined,
    );
  });

  it("shows interrupted status for partial playback", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify(
          playbackResponse({
            status: "partial",
            resumable: false,
            events: [
              {
                id: 1,
                type: "game_failed",
                run_id: "playback_game_1200abcd",
                session_id: "game_1200abcd",
                created_at: "2026-05-19T00:00:00Z",
                round: null,
                phase: null,
                actor: null,
                action: null,
                payload: {
                  error: "Maximum rounds exceeded",
                  playback_partial: true,
                },
              },
            ],
          }),
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderPlaybackRoute();

    expect(await screen.findByText("异常中断")).toBeInTheDocument();
  });

  it("resumes resumable partial playback through the existing resume endpoint", async () => {
    const user = userEvent.setup();
    const fetch = vi.spyOn(globalThis, "fetch");
    fetch
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify(
            playbackResponse({
              status: "partial",
              resumable: true,
              events: [
                {
                  id: 1,
                  type: "game_started",
                  run_id: "run_original",
                  session_id: "game_1200abcd",
                  created_at: "2026-05-19T00:00:00Z",
                  round: null,
                  phase: null,
                  actor: null,
                  action: null,
                  payload: {
                    players: [
                      { name: "Alice", role: "狼人", model: "deepseek-chat" },
                      { name: "Bob", role: "村民", model: "deepseek-chat" },
                    ],
                  },
                },
                {
                  id: 2,
                  type: "game_failed",
                  run_id: "run_original",
                  session_id: "game_1200abcd",
                  created_at: "2026-05-19T00:00:10Z",
                  round: null,
                  phase: null,
                  actor: null,
                  action: null,
                  payload: { error: "model timeout" },
                },
              ],
            }),
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            run_id: "run_resumed",
            session_id: "game_1200abcd",
            villager_model: "deepseek-chat",
            werewolf_model: "deepseek-chat",
            seed: null,
            max_rounds: 8,
            rule_set: null,
            status: "running",
            created_at: "2026-05-19T00:00:11Z",
            started_at: "2026-05-19T00:00:12Z",
            completed_at: null,
            winner: null,
            error: null,
            event_count: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    renderPlaybackRoute();

    await user.click(await screen.findByRole("button", { name: "回放设置" }));
    let dialog = screen.getByRole("dialog", { name: "回放设置" });
    expect(within(dialog).getByRole("button", { name: "暂停" })).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: "继续对局" }),
    ).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "追到最新" }));
    dialog = screen.getByRole("dialog", { name: "回放设置" });
    await user.click(within(dialog).getByRole("button", { name: "继续对局" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/games/game_1200abcd/resume",
        { method: "POST" },
      ),
    );
    expect(
      await screen.findByRole("heading", { name: "继续后的实时观战" }),
    ).toBeInTheDocument();
  });
});
