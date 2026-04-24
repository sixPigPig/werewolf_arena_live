import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../app/App";

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("routes the root path to the replay workbench", async () => {
    window.history.pushState({}, "", "/");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "狼人杀对局复盘" }),
    ).toBeInTheDocument();
  });
});
