import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

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
});
