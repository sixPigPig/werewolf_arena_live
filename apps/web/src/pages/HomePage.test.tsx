import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../tests/renderWithClient";
import { HomePage } from "./HomePage";

describe("HomePage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses the shared full-width page container", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const { container } = renderWithClient(<HomePage />);

    expect(
      screen.getByRole("heading", {
        name: "Python + React monorepo is ready.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("app-top-nav")).toHaveClass(
      "fixed",
      "inset-x-0",
      "top-0",
      "z-50",
      "h-[var(--app-top-nav-height)]",
      "min-h-[var(--app-top-nav-height)]",
    );
    expect(document.querySelector(".site-content-layer")).toHaveClass(
      "pt-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
    );
    expect(screen.queryByTestId("app-logo-placeholder")).not.toBeInTheDocument();
    expect(screen.queryByTestId("app-logo-image")).not.toBeInTheDocument();
    expect(screen.getByTestId("app-brand-logo")).toHaveClass(
      "h-16",
      "w-auto",
    );
    expect(screen.getByTestId("app-brand-logo").getAttribute("src")).toContain(
      "langrensha-arena-nav-logo",
    );
    expect(screen.getByRole("link", { name: "狼人杀竞技场" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(screen.getByRole("link", { name: "进入大厅" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(screen.getByRole("link", { name: "进入大厅" })).toHaveClass(
      "gothic-button",
    );
    expect(screen.queryByRole("link", { name: "返回大厅" })).not.toBeInTheDocument();
    expect(container.querySelector("main")?.className).not.toContain("bg-");
    expect(screen.getByTestId("home-hero-module")).toHaveClass(
      "home-hero-module",
      "glass-panel",
    );
    const hero = container.querySelector("section");
    expect(hero).toHaveClass("max-w-none", "w-full");
    expect(hero).not.toHaveClass("max-w-4xl");
  });
});
