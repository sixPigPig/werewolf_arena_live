import { act, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { ArenaGlobalNav } from "./ArenaGlobalNav";
import { ArenaNavButton } from "./ArenaNavButton";

function setScrollY(value: number) {
  Object.defineProperty(window, "scrollY", {
    configurable: true,
    value,
  });
}

function renderNav(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

afterEach(() => {
  setScrollY(0);
});

describe("ArenaGlobalNav", () => {
  it("renders transparent and borderless at the top of the page", () => {
    setScrollY(0);

    renderNav(
      <ArenaGlobalNav
        primaryAction={
          <ArenaNavButton intent="primary">新建对局</ArenaNavButton>
        }
        secondaryAction={
          <ArenaNavButton to="/games/history">对局历史</ArenaNavButton>
        }
      />,
    );

    const nav = screen.getByTestId("arena-global-nav");

    expect(nav).toHaveAttribute("data-surface", "transparent");
    expect(nav).toHaveClass(
      "h-[var(--arena-nav-height)]",
      "min-h-[var(--arena-nav-height)]",
      "bg-transparent",
      "border-transparent",
    );
    expect(nav).not.toHaveClass("backdrop-blur-xl");
    expect(screen.getByTestId("arena-brand-logo")).toHaveClass(
      "h-[var(--arena-nav-height)]",
      "w-auto",
    );
    expect(screen.getByRole("link", { name: "狼人杀竞技场" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(
      within(screen.getByTestId("arena-nav-primary-action")).getByRole(
        "button",
        { name: "新建对局" },
      ),
    ).toHaveClass("gothic-button");
    expect(
      within(screen.getByTestId("arena-nav-secondary-action")).getByRole(
        "link",
        { name: "对局历史" },
      ),
    ).toHaveClass("gothic-button");
  });

  it("switches to a very light frosted glass surface after scrolling", () => {
    setScrollY(0);
    renderNav(<ArenaGlobalNav />);

    const nav = screen.getByTestId("arena-global-nav");

    act(() => {
      setScrollY(16);
      window.dispatchEvent(new Event("scroll"));
    });

    expect(nav).toHaveAttribute("data-surface", "frosted");
    expect(nav).toHaveClass(
      "bg-slate-950/[0.08]",
      "backdrop-blur-xl",
      "border-white/10",
    );
  });

  it("exposes tone and density as explicit navigation state", () => {
    renderNav(<ArenaGlobalNav density="compact" tone="ornate" />);

    const nav = screen.getByTestId("arena-global-nav");

    expect(nav).toHaveAttribute("data-density", "compact");
    expect(nav).toHaveAttribute("data-tone", "ornate");
  });
});
