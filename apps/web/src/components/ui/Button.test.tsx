import { render, screen } from "@testing-library/react";
import { MemoryRouter, Link } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Button } from ".";

describe("Button", () => {
  it("renders the gothic skin with the requested intent", () => {
    render(
      <Button intent="danger" skin="gothic">
        处决玩家
      </Button>,
    );

    const button = screen.getByRole("button", { name: "处决玩家" });

    expect(button).toHaveClass("gothic-button");
    expect(button).toHaveAttribute("data-intent", "danger");
    expect(screen.getByText("处决玩家")).toHaveClass("gothic-button-label");
  });

  it("keeps gothic classes when rendering as a child link", () => {
    render(
      <MemoryRouter>
        <Button asChild intent="primary" skin="gothic">
          <Link to="/games">开始游戏</Link>
        </Button>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "开始游戏" });

    expect(link).toHaveClass("gothic-button");
    expect(link).toHaveAttribute("data-intent", "primary");
    expect(link).toHaveAttribute("href", "/games");
  });

  it("maps legacy colors to gothic intent when intent is omitted", () => {
    render(
      <Button color="green" skin="gothic">
        确认
      </Button>,
    );

    expect(screen.getByRole("button", { name: "确认" })).toHaveAttribute(
      "data-intent",
      "success",
    );
  });

  it("preserves the existing loading behavior for gothic buttons", () => {
    render(
      <Button loading skin="gothic">
        继续对局
      </Button>,
    );

    const button = screen.getByRole("button", { name: "处理中..." });

    expect(button).toBeDisabled();
    expect(button).toHaveClass("gothic-button");
  });
});
