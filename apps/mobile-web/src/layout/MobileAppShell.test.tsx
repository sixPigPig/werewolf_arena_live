import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { routes } from "../routes/definitions";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("MobileAppShell", () => {
  it("renders the phone shell with bottom tabs", () => {
    renderAt("/");

    expect(screen.getByTestId("mobile-app-shell")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "手机版主导航" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "对局" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "玩家" })).toHaveAttribute("href", "/players");
    expect(screen.getByRole("link", { name: "历史" })).toHaveAttribute("href", "/history");
    expect(screen.getByRole("link", { name: "设置" })).toHaveAttribute("href", "/settings");
  });

  it("marks the active bottom tab", () => {
    renderAt("/players");

    const nav = screen.getByRole("navigation", { name: "手机版主导航" });

    expect(within(nav).getByRole("link", { name: "玩家" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "对局" })).not.toHaveAttribute("aria-current");
  });
});
