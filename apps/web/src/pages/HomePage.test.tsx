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
    expect(screen.getByTestId("app-top-nav")).toBeInTheDocument();
    expect(screen.getByTestId("app-logo-placeholder")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "狼人杀竞技场" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(screen.getByRole("link", { name: "进入大厅" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(screen.queryByRole("link", { name: "返回大厅" })).not.toBeInTheDocument();
    const hero = container.querySelector("section");
    expect(hero).toHaveClass("max-w-none", "w-full");
    expect(hero).not.toHaveClass("max-w-4xl");
  });
});
