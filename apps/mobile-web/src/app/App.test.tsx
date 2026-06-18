import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listGames } from "../api/gamesApi";
import { App } from "./App";

vi.mock("../api/gamesApi", () => ({
  createGameRun: vi.fn(),
  listGames: vi.fn(),
}));

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  beforeEach(() => {
    vi.mocked(listGames).mockReset();
    vi.mocked(listGames).mockResolvedValue({ sessions: [] });
  });

  it("renders the mobile game home", () => {
    renderApp();

    expect(
      screen.getByRole("heading", { name: "狼人杀竞技场" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "今晚开一局" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "一键开局" })).toBeInTheDocument();
    expect(screen.queryByText("手机版 Web 正在搭建中")).not.toBeInTheDocument();
  });
});
