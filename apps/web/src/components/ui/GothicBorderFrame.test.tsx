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

  it("uses image corners with continuous CSS rails instead of sliced edge images", () => {
    const css = readFileSync("src/styles/index.css", "utf8");
    const workbenchFrameRule =
      css.match(/\.lobby-workbench-frame \{[\s\S]*?\n\}/)?.[0] ?? "";
    const lobbyFrameShellRule =
      css.match(/\.lobby-workbench-column,\n\.lobby-action-bar \{[\s\S]*?\n\}/)?.[0] ??
      "";
    const frameCssStart = css.indexOf(".gothic-border-frame {");
    const frameCssEnd = css.indexOf(".gothic-button {", frameCssStart);
    const frameCss = css.slice(frameCssStart, frameCssEnd);

    expect(workbenchFrameRule).toContain("overflow: visible;");
    expect(lobbyFrameShellRule).toContain("overflow: visible;");
    expect(lobbyFrameShellRule).toContain("border: 0;");
    expect(lobbyFrameShellRule).not.toContain(
      "border: 1px solid rgb(185 147 92 / 44%);",
    );
    expect(frameCss).toContain("--gothic-border-frame-art-outset");
    expect(frameCss).toContain(
      "inset: calc(var(--gothic-border-frame-art-outset) * -1);",
    );
    expect(frameCss).toContain("--gothic-border-frame-safe-block");
    expect(frameCss).toContain("--gothic-border-frame-safe-inline");
    expect(frameCss).toContain("padding:");
    expect(frameCss).toContain("var(--gothic-border-frame-safe-block)");
    expect(frameCss).toContain("var(--gothic-border-frame-safe-inline)");
    expect(frameCss).toContain("--gothic-border-frame-edge-seam-overlap");
    expect(frameCss).toContain("--gothic-border-frame-edge-seam-offset");
    expect(frameCss).toContain("--gothic-border-frame-rail-highlight");
    expect(frameCss).toContain("--gothic-border-frame-rail-gold");
    expect(frameCss).toContain("--gothic-border-frame-rail-shadow");
    expect(frameCss).toContain(
      "calc(var(--gothic-border-frame-corner-inline) - var(--gothic-border-frame-edge-seam-overlap))",
    );
    expect(frameCss).toContain("top: var(--gothic-border-frame-edge-seam-offset)");
    expect(frameCss).toContain("left: var(--gothic-border-frame-edge-seam-offset)");
    expect(frameCss).toContain("z-index: 1;");
    expect(frameCss).toContain("z-index: 2;");
    expect(css).toContain(".lobby-action-bar.gothic-border-frame-compact");
    expect(css).toContain(
      "--gothic-border-frame-safe-inline: clamp(1.35rem, 3.2vw, 3.6rem);",
    );
    expect(frameCss).toContain(
      'url("../assets/lobby-border-frame/frame-corner-tl.png")',
    );
    expect(frameCss).toContain("linear-gradient(90deg");
    expect(frameCss).toContain("linear-gradient(180deg");
    expect(frameCss).not.toContain(
      'url("../assets/lobby-border-frame/frame-edge-top.png")',
    );
    expect(frameCss).not.toContain(
      'url("../assets/lobby-border-frame/frame-edge-left.png")',
    );
    expect(frameCss).not.toContain("background-repeat: repeat-x");
    expect(frameCss).not.toContain("background-repeat: repeat-y");
    expect(frameCss).not.toContain(
      'source-transparent.png") 0 0 / 100% 100%',
    );
  });
});
