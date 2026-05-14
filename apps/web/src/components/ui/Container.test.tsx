import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { Container } from "./Container";

describe("Container", () => {
  it("renders the gothic night container with frame, texture, decoration, and content layers", () => {
    render(
      <Container
        aria-label="夜幕面板"
        className="custom-shell"
        contentClassName="custom-content"
        size="3"
      >
        <h2>对局信息</h2>
      </Container>,
    );

    const container = screen.getByLabelText("夜幕面板");

    expect(container).toHaveClass(
      "gothic-night-container",
      "gothic-night-container-lg",
      "custom-shell",
    );
    expect(container.querySelector(".gothic-night-container-center")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(
      container.querySelectorAll(".gothic-night-container-frame-piece"),
    ).toHaveLength(8);
    expect(container.querySelector(".gothic-night-container-moon")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(
      container.querySelector(".gothic-night-container-smoke-bottom"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(
      container.querySelector(".gothic-night-container-branch-left"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(
      container.querySelector(".gothic-night-container-branch-right"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("对局信息").parentElement).toHaveClass(
      "gothic-night-container-content",
      "custom-content",
    );
  });

  it("allows the base artwork opacity to be tuned", () => {
    render(
      <Container aria-label="半透明面板" baseOpacity={0.42}>
        内容
      </Container>,
    );

    expect(screen.getByLabelText("半透明面板")).toHaveStyle({
      "--gothic-night-container-base-opacity": "0.42",
    });
  });

  it("uses the sliced gothic container artwork assets", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain('url("../assets/gothic-container/gothic-frame-quality-final.png")');
    expect(css).toContain('url("../assets/gothic-container/gothic-center.webp")');
    expect(css).toContain('url("../assets/gothic-container/moon-decoration.webp")');
    expect(css).toContain('url("../assets/gothic-container/branch-left.webp")');
    expect(css).toContain('url("../assets/gothic-container/branch-right.webp")');
    expect(css).toContain('url("../assets/gothic-container/smoke-bottom.webp")');
    expect(css).toContain("--gothic-night-container-base-opacity");
  });

  it("keeps the nine-slice frame pieces constrained to their allowed axis", () => {
    const css = readFileSync("src/styles/index.css", "utf8");
    const containerBlock = css.match(
      /\.gothic-night-container \{(?<body>[\s\S]*?)\}/,
    )?.groups?.body;

    expect(css).toContain("--gothic-night-container-corner-inline: 92px");
    expect(css).toContain("--gothic-night-container-top-block: 156px");
    expect(css).toContain("--gothic-night-container-bottom-block: 132px");
    expect(css).toContain("background-repeat: repeat-x");
    expect(css).toContain("background-repeat: repeat-y");
    expect(css).toContain("background-size: auto 100%");
    expect(css).toContain("background-size: 100% auto");
    expect(containerBlock).not.toContain("border-image-source");
  });

  it("tiles the center texture instead of stretching it to the content box", () => {
    const css = readFileSync("src/styles/index.css", "utf8");
    const centerBlock = css.match(
      /\.gothic-night-container-center \{(?<body>[\s\S]*?)\}/,
    )?.groups?.body;

    expect(centerBlock).toContain("background-repeat: repeat");
    expect(centerBlock).toContain("background-size: min(1024px, 100%) auto");
    expect(centerBlock).not.toContain("100% 100%");
  });
});
