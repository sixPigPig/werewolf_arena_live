import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { MemoryRouter, Link } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Button } from "./Button";

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
    expect(screen.getByText("处决玩家").parentElement).toHaveClass(
      "gothic-button-content",
    );
  });

  it("renders the gothic small size", () => {
    render(
      <Button size="1" skin="gothic">
        小号
      </Button>,
    );

    expect(screen.getByRole("button", { name: "小号" })).toHaveClass(
      "gothic-button",
      "gothic-button-sm",
    );
  });

  it("renders the default large size at the standard component height", () => {
    render(<Button size="3">大号</Button>);

    expect(screen.getByRole("button", { name: "大号" })).toHaveClass(
      "h-12",
      "px-5",
    );
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

  it("uses nine-slice artwork instead of stretching the whole button image", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain("--gothic-button-slice:");
    expect(css).toContain("--gothic-button-border:");
    expect(css).toContain("border-image-source: var(--gothic-button-image)");
    expect(css).toContain("border-image-slice: var(--gothic-button-slice) fill");
    expect(css).toContain("border-image-width: var(--gothic-button-border)");
    expect(css).not.toContain(
      "background: var(--gothic-button-image) center / 100% 100% no-repeat;",
    );
  });

  it("keeps gothic size padding vertically symmetric so labels stay centered", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    for (const size of ["sm", "md", "lg"]) {
      const block = css.match(
        new RegExp(`\\.gothic-button-${size} \\{(?<body>[\\s\\S]*?)\\}`),
      )?.groups?.body;
      const padding = block?.match(/padding:\s*(?<value>[^;]+);/)?.groups
        ?.value;

      expect(padding).toBeDefined();

      const values = padding?.trim().split(/\s+/) ?? [];
      const top = values[0];
      const bottom =
        values.length === 1 || values.length === 2 ? values[0] : values[2];

      expect(bottom).toBe(top);
    }
  });

  it("keeps gothic buttons at the designed component dimensions", () => {
    const css = readFileSync("src/styles/index.css", "utf8");
    const sizes = {
      lg: "3rem",
      md: "2.5rem",
      sm: "2rem",
    };

    for (const [size, expectedHeight] of Object.entries(sizes)) {
      const block = css.match(
        new RegExp(`\\.gothic-button-${size} \\{(?<body>[\\s\\S]*?)\\}`),
      )?.groups?.body;

      expect(block).toContain(`height: ${expectedHeight};`);
    }
  });
});
