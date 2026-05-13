import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { Link, MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Button } from "../components/ui";
import { AppTopNav } from "./AppTopNav";

function renderNav(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("AppTopNav", () => {
  it("renders the global navigation contract with full brand and standard slots", () => {
    renderNav(
      <AppTopNav
        actions={
          <Button highContrast size="1" type="button">
            新建对局
          </Button>
        }
        utilityActions={
          <Button asChild color="gray" highContrast size="1" variant="surface">
            <Link to="/games/history">对局历史</Link>
          </Button>
        }
      />,
    );

    expect(screen.getByTestId("app-top-nav")).toHaveAttribute(
      "data-variant",
      "global",
    );
    expect(screen.getByTestId("app-top-nav")).toHaveAttribute(
      "data-density",
      "regular",
    );
    expect(screen.getByTestId("app-top-nav")).toHaveClass(
      "h-[var(--app-top-nav-height)]",
      "min-h-[var(--app-top-nav-height)]",
      "bg-slate-950/[0.08]",
      "backdrop-blur-xl",
    );
    expect(screen.getByTestId("app-brand-link")).not.toHaveClass(
      "focus:ring-2",
      "focus:ring-amber-300/70",
    );
    expect(screen.getByTestId("app-brand-logo").getAttribute("src")).toContain(
      "langrensha-arena-nav-logo",
    );
    expect(screen.getByTestId("app-brand-logo")).toHaveClass("h-16");
    expect(within(screen.getByTestId("app-top-nav-primary-actions")).getByRole(
      "button",
      { name: "新建对局" },
    )).toBeInTheDocument();
    expect(within(screen.getByTestId("app-top-nav-utility-actions")).getByRole(
      "link",
      { name: "对局历史" },
    )).toBeInTheDocument();
  });

  it("renders the command navigation contract with compact brand and context", () => {
    renderNav(
      <AppTopNav
        actions={
          <Button highContrast size="1" type="button">
            暂停
          </Button>
        }
        brand="compact"
        context={<span>实时状态</span>}
        density="compact"
        utilityActions={
          <Button asChild color="gray" highContrast size="1" variant="surface">
            <Link to="/games">返回大厅</Link>
          </Button>
        }
        variant="command"
      />,
    );

    expect(screen.getByTestId("app-top-nav")).toHaveAttribute(
      "data-variant",
      "command",
    );
    expect(screen.getByTestId("app-top-nav")).toHaveAttribute(
      "data-density",
      "compact",
    );
    expect(screen.getByTestId("app-top-nav")).toHaveClass(
      "bg-slate-950/[0.08]",
      "backdrop-blur-xl",
    );
    expect(screen.getByTestId("app-top-nav-context")).toHaveTextContent(
      "实时状态",
    );
    expect(screen.getByTestId("app-brand-logo").getAttribute("src")).toContain(
      "langrensha-c-logo",
    );
    expect(screen.getByTestId("app-brand-logo")).toHaveClass("h-12", "w-12");
    expect(within(screen.getByTestId("app-top-nav-primary-actions")).getByRole(
      "button",
      { name: "暂停" },
    )).toBeInTheDocument();
    expect(within(screen.getByTestId("app-top-nav-utility-actions")).getByRole(
      "link",
      { name: "返回大厅" },
    )).toBeInTheDocument();
  });
});
