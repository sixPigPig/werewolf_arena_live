import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthCard } from "./HealthCard";

describe("HealthCard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the backend health status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <HealthCard />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByText(/api status:/i)).toHaveTextContent("ok"),
    );
  });
});
