import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ArenaNavButton } from "./ArenaNavButton";

describe("ArenaNavButton", () => {
  it("renders navigation text actions with the gothic component button skin", () => {
    render(
      <ArenaNavButton intent="primary" onClick={() => undefined}>
        新建对局
      </ArenaNavButton>,
    );

    const button = screen.getByRole("button", { name: "新建对局" });

    expect(button).toHaveClass("gothic-button", "gothic-button-sm");
    expect(button).toHaveAttribute("data-intent", "primary");
  });

  it("renders navigation links through the component button asChild path", () => {
    render(
      <MemoryRouter>
        <ArenaNavButton to="/games/history">对局历史</ArenaNavButton>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "对局历史" });

    expect(link).toHaveClass("gothic-button", "gothic-button-sm");
    expect(link).toHaveAttribute("data-intent", "default");
    expect(link).toHaveAttribute("href", "/games/history");
  });

  it("keeps loading navigation actions disabled and labelled by Button", () => {
    render(<ArenaNavButton loading>刷新列表</ArenaNavButton>);

    const button = screen.getByRole("button", { name: "处理中..." });

    expect(button).toBeDisabled();
    expect(button).toHaveClass("gothic-button");
  });

  it("keeps loading navigation links disabled and labelled by Button", () => {
    render(
      <MemoryRouter>
        <ArenaNavButton loading to="/games/history">
          对局历史
        </ArenaNavButton>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "处理中..." });

    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveAttribute("tabindex", "-1");
    expect(link).toHaveClass("gothic-button");
  });

  it("prevents disabled navigation links from invoking click handlers or navigating", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <MemoryRouter initialEntries={["/games"]}>
        <ArenaNavButton disabled onClick={handleClick} to="/games/history">
          对局历史
        </ArenaNavButton>
        <Routes>
          <Route path="/games" element={<p>大厅</p>} />
          <Route path="/games/history" element={<p>历史</p>} />
        </Routes>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "对局历史" });

    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveAttribute("tabindex", "-1");

    await user.click(link);

    expect(handleClick).not.toHaveBeenCalled();
    expect(screen.getByText("大厅")).toBeInTheDocument();
    expect(screen.queryByText("历史")).not.toBeInTheDocument();
  });

  it("prevents loading navigation links from invoking click handlers or navigating", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <MemoryRouter initialEntries={["/games"]}>
        <ArenaNavButton loading onClick={handleClick} to="/games/history">
          对局历史
        </ArenaNavButton>
        <Routes>
          <Route path="/games" element={<p>大厅</p>} />
          <Route path="/games/history" element={<p>历史</p>} />
        </Routes>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "处理中..." });

    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveAttribute("tabindex", "-1");

    await user.click(link);

    expect(handleClick).not.toHaveBeenCalled();
    expect(screen.getByText("大厅")).toBeInTheDocument();
    expect(screen.queryByText("历史")).not.toBeInTheDocument();
  });

  it("forwards useful navigation link props through the component button", () => {
    render(
      <MemoryRouter>
        <ArenaNavButton
          ariaLabel="打开历史"
          className="nav-history"
          data-testid="history-link"
          disabled
          intent="primary"
          to="/games/history"
        >
          对局历史
        </ArenaNavButton>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "打开历史" });

    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveAttribute("data-testid", "history-link");
    expect(link).toHaveAttribute("data-intent", "primary");
    expect(link).toHaveClass(
      "gothic-button",
      "gothic-button-sm",
      "nav-history",
    );
  });

  it("forwards navigation link click handlers", () => {
    const handleClick = vi.fn();

    render(
      <MemoryRouter>
        <ArenaNavButton onClick={handleClick} to="/games/history">
          对局历史
        </ArenaNavButton>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "对局历史" });

    fireEvent.click(link);

    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
