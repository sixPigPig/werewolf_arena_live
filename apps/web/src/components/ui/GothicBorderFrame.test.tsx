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
