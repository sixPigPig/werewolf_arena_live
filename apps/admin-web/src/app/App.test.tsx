import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "@/routes";

function renderRoute(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

describe("admin app scaffold", () => {
  it("renders the overview inside the independent admin shell", async () => {
    renderRoute("/overview");

    expect(
      await screen.findByRole("heading", { name: "运营总览" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "后台主导航" }),
    ).toBeInTheDocument();
    expect(screen.getByText("未连接 Admin API")).toBeInTheDocument();
  });

  it("navigates to a planned module without calling legacy APIs", async () => {
    const user = userEvent.setup();
    renderRoute("/overview");

    await user.click(await screen.findByRole("link", { name: /虚拟玩家/ }));

    expect(
      await screen.findByRole("heading", { name: "虚拟玩家" }),
    ).toBeInTheDocument();
    expect(screen.getByText("等待 Admin API")).toBeInTheDocument();
  });

  it("renders an admin-specific not found page", async () => {
    renderRoute("/not-a-real-admin-route");

    expect(
      await screen.findByRole("heading", { name: "后台页面不存在" }),
    ).toBeInTheDocument();
  });
});
