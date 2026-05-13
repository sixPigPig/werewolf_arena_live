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
      "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "min-h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "bg-transparent",
      "border-transparent",
    );
    expect(nav).not.toHaveClass("backdrop-blur-sm");
    expect(screen.getByTestId("arena-brand-logo")).toHaveClass(
      "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "w-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
    );
    expect(screen.getByTestId("arena-brand-logo").getAttribute("src")).toContain(
      "langrensha-c-logo",
    );
    expect(screen.getByTestId("arena-brand-wordmark")).toHaveClass(
      "hidden",
      "sm:block",
      "h-12",
      "w-auto",
    );
    expect(
      screen.getByTestId("arena-brand-wordmark").getAttribute("src"),
    ).toContain(
      "langrensha-title-wordmark",
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
      "backdrop-blur-sm",
      "border-white/10",
    );
  });

  it("exposes tone and density as explicit navigation state", () => {
    renderNav(<ArenaGlobalNav density="compact" tone="ornate" />);

    const nav = screen.getByTestId("arena-global-nav");

    expect(nav).toHaveAttribute("data-density", "compact");
    expect(nav).toHaveAttribute("data-tone", "ornate");
  });

  it("uses a non-yellow keyboard focus treatment for the brand link", () => {
    renderNav(<ArenaGlobalNav />);

    const brandLink = screen.getByTestId("arena-brand-link");

    expect(brandLink).toHaveClass(
      "focus-visible:outline",
      "focus-visible:outline-2",
      "focus-visible:outline-offset-2",
      "focus-visible:outline-white/60",
    );
    expect(brandLink.className).not.toMatch(/focus[^ ]*(amber|yellow)/);
  });

  it("keeps the brand area shrinkable while actions stay fixed", () => {
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

    expect(screen.getByTestId("arena-brand-link")).toHaveClass(
      "flex-1",
      "min-w-0",
    );
    expect(screen.getByTestId("arena-brand-logo")).toHaveClass(
      "max-w-full",
      "shrink-0",
    );
    expect(screen.getByTestId("arena-brand-wordmark")).toHaveClass("min-w-0");
    expect(screen.getByTestId("arena-brand-wordmark")).not.toHaveClass("shrink-0");
    expect(screen.getByTestId("arena-nav-actions")).toHaveClass("shrink-0");
  });
});
