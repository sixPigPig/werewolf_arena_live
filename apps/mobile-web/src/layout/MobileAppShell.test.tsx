/// <reference types="node" />

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { routes } from "../routes/definitions";

const mobileStyles = readFileSync(
  "src/styles/index.css",
  "utf8",
);
const routeDefinitions = readFileSync(
  "src/routes/definitions.tsx",
  "utf8",
);

function cssBlock(selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = mobileStyles.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`));

  return match?.[1] ?? "";
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
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

  it("keeps fixed bottom chrome inside the phone viewport", () => {
    expect(cssBlock(":root")).toContain("--mobile-tab-bar-offset");
    expect(cssBlock(".mobile-app-frame")).toContain("overflow: hidden");
    expect(cssBlock(".mobile-app-shell")).toContain("height: 100svh");
    expect(cssBlock(".mobile-app-shell")).toContain("max-height: 100svh");
    expect(cssBlock(".mobile-tab-bar")).toContain("box-sizing: border-box");
    expect(cssBlock(".mobile-tab-bar")).toContain("max-width: 100vw");
    expect(cssBlock(".mobile-fixed-action-bar")).toContain(
      "bottom: var(--mobile-tab-bar-offset)",
    );
  });

  it("keeps status and legacy shell styles aligned with supported UI", () => {
    expect(cssBlock(".mobile-status-banner-success")).toContain("border-color");
    expect(mobileStyles).not.toContain(".mobile-page-surface");
  });

  it("keeps route definitions provider-free", () => {
    expect(routeDefinitions).not.toContain("QueryClientProvider");
    expect(routeDefinitions).not.toContain("queryClient");
  });
});
