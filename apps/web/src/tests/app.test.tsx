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
    expect(screen.getByTestId("site-background").getAttribute("style")).toContain(
      "werewolf-site-background",
    );
  });

  it("routes the game history path to the history page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          sessions: [
            {
              session_id: "session_history_route",
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
    expect(await screen.findByText("session_history_route")).toBeInTheDocument();
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
