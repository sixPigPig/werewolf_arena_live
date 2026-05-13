import { act, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { ArenaCommandNav } from "./ArenaCommandNav";
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

describe("ArenaCommandNav", () => {
  it("renders live command context and actions with compact navigation metadata", () => {
    renderNav(
      <ArenaCommandNav
        actions={<ArenaNavButton to="/games">返回大厅</ArenaNavButton>}
        commands={<button type="button">暂停</button>}
        context={<span>实时状态</span>}
      />,
    );

    const nav = screen.getByTestId("arena-command-nav");

    expect(nav).toHaveAttribute("data-variant", "command");
    expect(nav).toHaveAttribute("data-density", "compact");
    expect(nav).toHaveAttribute("data-tone", "nocturne");
    expect(nav).toHaveAttribute("data-surface", "transparent");
    expect(nav).toHaveClass(
      "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "min-h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "bg-transparent",
      "border-transparent",
    );
    expect(screen.getByTestId("arena-command-context")).toHaveTextContent(
      "实时状态",
    );
    expect(
      within(screen.getByTestId("arena-command-controls")).getByRole("button", {
        name: "暂停",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "实时控制" }),
    ).toBe(screen.getByTestId("arena-command-controls"));
    expect(
      within(screen.getByTestId("arena-command-actions")).getByRole("link", {
        name: "返回大厅",
      }),
    ).toHaveClass("gothic-button");
    expect(screen.getByTestId("arena-command-brand-logo")).toHaveClass(
      "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))]",
      "w-auto",
      "max-w-full",
      "shrink",
    );
  });

  it("uses the same light frosted surface after scrolling", () => {
    setScrollY(0);
    renderNav(<ArenaCommandNav />);

    const nav = screen.getByTestId("arena-command-nav");

    act(() => {
      setScrollY(10);
      window.dispatchEvent(new Event("scroll"));
    });

    expect(nav).toHaveAttribute("data-surface", "frosted");
    expect(nav).toHaveClass(
      "bg-slate-950/[0.08]",
      "backdrop-blur-xl",
      "border-white/10",
    );
  });

  it("uses a non-yellow keyboard focus treatment and shrinkable brand area", () => {
    renderNav(
      <ArenaCommandNav
        actions={<ArenaNavButton to="/games">返回大厅</ArenaNavButton>}
      />,
    );

    const brandLink = screen.getByTestId("arena-command-brand-link");

    expect(brandLink).toHaveClass(
      "focus-visible:outline",
      "focus-visible:outline-2",
      "focus-visible:outline-offset-2",
      "focus-visible:outline-white/60",
      "flex-1",
      "min-w-0",
    );
    expect(brandLink.className).not.toMatch(/focus[^ ]*(amber|yellow)/);
    expect(screen.getByTestId("arena-command-action-region")).toHaveClass(
      "shrink-0",
    );
  });

  it("keeps command controls visible while only clipping non-interactive context", () => {
    renderNav(
      <ArenaCommandNav
        commands={<button type="button">发言顺序</button>}
        context={<span>很长的实时房间上下文</span>}
      />,
    );

    const controls = screen.getByTestId("arena-command-controls");

    expect(screen.getByTestId("arena-command-context")).toHaveClass(
      "overflow-hidden",
    );
    expect(
      screen.getByTestId("arena-command-nav").firstElementChild,
    ).toHaveClass("overflow-x-auto");
    expect(controls).not.toHaveClass("overflow-hidden");
    expect(controls.closest(".overflow-hidden")).toBeNull();
  });
});
