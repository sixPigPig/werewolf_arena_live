import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "@/routes";

function renderRoute(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("admin app routes", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "true");
  });

  afterEach(() => vi.unstubAllEnvs());

  it("redirects the root to the operational overview", async () => {
    const router = renderRoute("/");

    expect(
      await screen.findByRole("heading", { name: "运营总览" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "后台主导航" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/overview");
    expect(screen.getByText("没有活动告警")).toBeInTheDocument();
  });

  it("navigates from the connected player list to its detail route", async () => {
    const user = userEvent.setup();
    const router = renderRoute("/content/players");

    await user.click(
      await screen.findByRole("link", { name: "编辑 雾灯听风" }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "雾灯听风" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(
      "/content/players/preview-draft-1",
    );
  });

  it("renders an admin-specific not found page", async () => {
    renderRoute("/not-a-real-admin-route");

    expect(
      await screen.findByRole("heading", { name: "后台页面不存在" }),
    ).toBeInTheDocument();
  });
});
