import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
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

    const createRoomLink = within(navigation).getByRole("link", { name: "创建对局" });
    const playerAtlasLink = within(navigation).getByRole("link", { name: "玩家图鉴" });

    expect(createRoomLink).toHaveAttribute("href", "/games");
    expect(playerAtlasLink).toHaveAttribute("href", "/players");
    expect(within(navigation).queryByRole("link", { name: "对局记录" })).toBeNull();

    expect(createRoomLink.querySelector("img")?.getAttribute("src")).toContain(
      "create-room-clean-alpha.png",
    );
    expect(playerAtlasLink.querySelector("img")?.getAttribute("src")).toContain(
      "player-atlas-clean-alpha.png",
    );
    expect(navigation.querySelector(".mobile-tab-glow")).not.toBeInTheDocument();
  });

  it("keeps the ornate tab frame compact and fully visible", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const rootRule = styles.match(/:root\s*{[^}]+}/)?.[0] ?? "";
    const tabBarRule =
      styles.match(/(?:^|\n)\.mobile-tab-bar\s*{[^}]+}/)?.[0] ?? "";

    expect(rootRule).toContain("--mobile-tab-frame-height: clamp(58px, 16.5vw, 80px)");
    expect(tabBarRule).toContain(
      "min-height: calc(var(--mobile-tab-frame-height) + env(safe-area-inset-bottom))",
    );
    expect(tabBarRule).toContain(
      "url(\"../assets/nav-bar/nav-frame.png\") center top / 100% var(--mobile-tab-frame-height) no-repeat",
    );
    expect(tabBarRule).not.toContain("linear-gradient");

    expect(styles).not.toContain(".mobile-tab-bar::before");
    expect(styles).not.toContain(".mobile-tab-bar::after");
    expect(styles).toContain(".mobile-tab-link-active::before");
    expect(styles).toContain(".mobile-tab-link-active::after");
    expect(styles).toContain("top: 50%");
    expect(styles).toContain("left: 50%");
    expect(styles).toContain("width: min(96%, 118px)");
    expect(styles).toContain("height: clamp(36px, 10vw, 48px)");
    expect(styles).toContain("radial-gradient(ellipse 62% 72% at 46% 50%");
    expect(styles).toContain("radial-gradient(ellipse 78% 82% at 22% 56%");
    expect(styles).toContain("radial-gradient(ellipse 54% 64% at 44% 52%");
    expect(styles).not.toContain("rgb(118 178 255 / 34%)");
    expect(styles).not.toContain("rgb(171 211 255 / 54%)");
    expect(styles).not.toContain("--mobile-tab-active-index");

    const tabImageRule =
      styles.match(/(?:^|\n)\.mobile-tab-image\s*{[^}]+}/)?.[0] ?? "";
    const activeImageRule =
      styles.match(/(?:^|\n)\.mobile-tab-link-active \.mobile-tab-image\s*{[^}]+}/)
        ?.[0] ?? "";

    expect(tabImageRule).toContain("width: min(76%, 92px)");
    expect(tabImageRule).toContain("height: clamp(26px, 7.45vw, 34px)");
    expect(activeImageRule).toContain("drop-shadow(0 0 4px");
    expect(activeImageRule).toContain("drop-shadow(0 0 12px");
  });
});
