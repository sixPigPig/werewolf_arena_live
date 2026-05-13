import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { Container } from ".";

describe("Container", () => {
  it("renders the gothic night container with a content layer", () => {
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

  it("uses the gothic night base and transparent frame artwork", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain(
      'url("../assets/werewolf-gothic-night/werewolf_gothic_night_base.png")',
    );
    expect(css).toContain(
      'url("../assets/werewolf-gothic-night/werewolf_gothic_night_frame_transparent.png")',
    );
    expect(css).toContain("--gothic-night-container-base-opacity");
  });

  it("uses nine-slice border layout so content is inset from the frame", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain("border-image-source: url(\"../assets/werewolf-gothic-night/werewolf_gothic_night_frame_transparent.png\")");
    expect(css).toContain("border-image-slice: 156 92 132 92");
    expect(css).toContain("border-width: var(--gothic-night-container-frame-top) var(--gothic-night-container-frame-inline) var(--gothic-night-container-frame-bottom)");
    expect(css).toContain("inset: var(--gothic-night-container-frame-top) var(--gothic-night-container-frame-inline) var(--gothic-night-container-frame-bottom)");
  });
});
