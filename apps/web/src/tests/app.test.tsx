import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

  it("routes the root path to the replay workbench", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderRoute(["/"]);

    expect(
      await screen.findByRole("heading", { name: "狼人杀对局复盘" }),
    ).toBeInTheDocument();
    expect(document.querySelector(".radix-themes")).toBeInTheDocument();
  });

  it("routes a game session path to the replay detail", async () => {
    const sessionId = "session_20260424_050950_66ea9f38";

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
