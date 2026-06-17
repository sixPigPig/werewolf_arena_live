import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppTheme } from "../app/AppTheme";
import { routes } from "../routes/definitions";

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderRoute(initialEntries: string[]) {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    const router = createMemoryRouter(routes, { initialEntries });

    render(
      <AppTheme>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AppTheme>,
    );
  }

  it("routes the root path to the game lobby", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify({ rule_sets: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }

      return Promise.resolve(new Response(null, { status: 404 }));
    });

    renderRoute(["/"]);

    expect(
      await screen.findByRole("heading", { name: "狼人杀对局大厅" }),
    ).toBeInTheDocument();
    expect(document.querySelector(".app-theme")).toBeInTheDocument();
    expect(document.querySelector(".app-theme")?.className).not.toContain(
      "bg-",
    );
    expect(screen.getByTestId("site-background")).toHaveClass(
      "fixed",
      "inset-0",
      "bg-cover",
    );
    const backgroundStyle = screen.getByTestId("site-background").getAttribute("style");
    expect(backgroundStyle).toContain("werewolf-castle-background");
    expect(backgroundStyle).not.toContain("linear-gradient");
    expect(backgroundStyle).toContain("background-size: cover");
    expect(backgroundStyle).toContain("background-position: center top");
  });

  it("routes the game history path to the history page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          sessions: [
            {
              session_id: "game_00000003",
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

    renderRoute(["/games/history"]);

    expect(
      await screen.findByRole("heading", { name: "对局历史" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("game_00000003")).toBeInTheDocument();
  });

  it("routes a historical playback path to the playback page", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "game_1200abcd",
          status: "complete",
          rule_set: null,
          resumable: false,
          events: [
            {
              id: 1,
              type: "game_started",
              run_id: "playback_game_1200abcd",
              session_id: "game_1200abcd",
              created_at: "2026-05-19T00:00:00Z",
              round: null,
              phase: null,
              actor: null,
              action: null,
              payload: { players: [] },
            },
            {
              id: 2,
              type: "game_completed",
              run_id: "playback_game_1200abcd",
              session_id: "game_1200abcd",
              created_at: "2026-05-19T00:00:01Z",
              round: null,
              phase: null,
              actor: null,
              action: null,
              payload: { winner: "狼人阵营" },
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderRoute(["/games/playback/game_1200abcd"]);

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/games/game_1200abcd/playback",
        undefined,
      ),
    );
    expect(screen.getByRole("link", { name: "查看复盘" })).toHaveAttribute(
      "href",
      "/games/game_1200abcd",
    );
  });

  it("routes the gothic button showcase path to the component example page", async () => {
    renderRoute(["/components/buttons"]);

    expect(
      await screen.findByRole("heading", { name: "Gothic Button" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Primary" })).toHaveAttribute(
      "data-intent",
      "primary",
    );
    expect(screen.getByRole("button", { name: "Danger Disabled" })).toBeDisabled();
  });

  it("routes a game session path to the replay detail", async () => {
    const sessionId = "game_05095066";

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: sessionId,
          status: "complete",
          state: {
            session_id: sessionId,
            winner: "狼人阵营",
            error_message: "",
            players: [
              {
                name: "张三",
                role: "werewolf",
                model: "deepseek-chat",
              },
            ],
            rounds: [
              {
                number: 1,
                players: ["张三"],
                eliminated: null,
                protected: null,
                investigated: null,
                exiled: null,
                debate: [],
                bids: [],
                votes: [],
                summaries: {},
                success: true,
              },
            ],
          },
          logs: [
            {
              number: 1,
              eliminate: null,
              protect: null,
              investigate: null,
              bid: [],
              debate: [],
              votes: [],
              summaries: [],
            },
          ],
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderRoute([`/games/${sessionId}`]);

    expect(await screen.findByText("狼人阵营")).toBeInTheDocument();
    expect(screen.getByText(sessionId)).toBeInTheDocument();
  });
});
