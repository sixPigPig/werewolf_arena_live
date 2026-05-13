import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
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

  it("keeps global page overrides from erasing component backgrounds", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).not.toMatch(/\.site-content-layer\s+\.bg-slate-100/);
    expect(css).not.toMatch(/\.site-content-layer\s+\.bg-slate-950/);
  });

  it("uses the gothic button artwork from the buttons asset directory", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain('url("../assets/buttons/button-default.png")');
    expect(css).toContain('url("../assets/buttons/button-info.png")');
    expect(css).toContain('url("../assets/buttons/button-primary.png")');
    expect(css).toContain('url("../assets/buttons/button-danger.png")');
    expect(css).toContain('url("../assets/buttons/button-success.png")');
    expect(css).toContain('url("../assets/buttons/button-warning.png")');
    expect(css).not.toContain("../assets/gothic-buttons/");
  });
});
