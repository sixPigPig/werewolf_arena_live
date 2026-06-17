import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { GothicBorderFrame } from "./GothicBorderFrame";

describe("GothicBorderFrame", () => {
  it("renders a transparent eight-piece gothic border around a content layer", () => {
    render(
      <GothicBorderFrame
        aria-label="大厅边框"
        className="custom-frame"
        contentClassName="custom-content"
      >
        <h2>规则选择</h2>
      </GothicBorderFrame>,
    );

    const frame = screen.getByLabelText("大厅边框");

    expect(frame).toHaveClass(
      "gothic-border-frame",
      "gothic-border-frame-default",
      "custom-frame",
    );
    expect(frame.querySelectorAll(".gothic-border-frame-piece")).toHaveLength(8);
    expect(
      frame.querySelector(".gothic-border-frame-decoration"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("规则选择").parentElement).toHaveClass(
      "gothic-border-frame-content",
      "custom-content",
    );
  });

  it("supports compact density for short action bars", () => {
    render(
      <GothicBorderFrame aria-label="底部操作条" as="footer" density="compact">
        操作
      </GothicBorderFrame>,
    );

    expect(screen.getByLabelText("底部操作条").tagName).toBe("FOOTER");
    expect(screen.getByLabelText("底部操作条")).toHaveClass(
      "gothic-border-frame-compact",
    );
  });

  it("uses sliced lobby border assets without stretching the source image", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain("--gothic-border-frame-safe-block");
    expect(css).toContain("--gothic-border-frame-safe-inline");
    expect(css).toContain("padding:");
    expect(css).toContain("var(--gothic-border-frame-safe-block)");
    expect(css).toContain("var(--gothic-border-frame-safe-inline)");
    expect(css).toContain("--gothic-border-frame-edge-seam-overlap");
    expect(css).toContain("--gothic-border-frame-edge-seam-offset");
    expect(css).toContain(
      "calc(var(--gothic-border-frame-corner-inline) - var(--gothic-border-frame-edge-seam-overlap))",
    );
    expect(css).toContain("top: var(--gothic-border-frame-edge-seam-offset)");
    expect(css).toContain("left: var(--gothic-border-frame-edge-seam-offset)");
    expect(css).toContain("z-index: 1;");
    expect(css).toContain("z-index: 2;");
    expect(css).toContain(".lobby-action-bar.gothic-border-frame-compact");
    expect(css).toContain(
      "--gothic-border-frame-safe-inline: clamp(1.35rem, 3.2vw, 3.6rem);",
    );
    expect(css).toContain(
      'url("../assets/lobby-border-frame/frame-corner-tl.png")',
    );
    expect(css).toContain(
      'url("../assets/lobby-border-frame/frame-edge-top.png")',
    );
    expect(css).toContain(
      'url("../assets/lobby-border-frame/frame-edge-left.png")',
    );
    expect(css).toContain("background-repeat: repeat-x");
    expect(css).toContain("background-repeat: repeat-y");
    expect(css).not.toContain(
      'source-transparent.png") 0 0 / 100% 100%',
    );
  });
});
