import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { routes } from "../routes/definitions";

function renderWithQueryClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("MobileAppShell", () => {
  it("renders player pages with accessible bottom navigation", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/players"] });

    renderWithQueryClient(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "玩家图鉴" })).toBeInTheDocument();

    const navigation = screen.getByRole("navigation", { name: "移动端主导航" });

    expect(within(navigation).getByRole("link", { name: "大厅" })).toHaveAttribute("href", "/games");
    expect(within(navigation).getByRole("link", { name: "玩家" })).toHaveAttribute("href", "/players");
    expect(within(navigation).getByRole("link", { name: "历史" })).toHaveAttribute("href", "/history");
  });
});
