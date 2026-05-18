import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { GothicPanel } from "./GothicPanel";

describe("GothicPanel", () => {
  it("renders a scalable gold gothic panel with frame, ornament, texture, and content layers", () => {
    render(
      <GothicPanel
        aria-label="金色议事面板"
        className="custom-panel"
        contentClassName="custom-content"
        size="3"
      >
        <h2>议事记录</h2>
      </GothicPanel>,
    );

    const panel = screen.getByLabelText("金色议事面板");

    expect(panel).toHaveClass(
      "gothic-panel",
      "gothic-panel-lg",
      "custom-panel",
    );
    expect(panel.querySelector(".gothic-panel-center")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(panel.querySelectorAll(".gothic-panel-frame-piece")).toHaveLength(8);
    expect(panel.querySelectorAll(".gothic-panel-ornament")).toHaveLength(4);
    expect(screen.getByText("议事记录").parentElement).toHaveClass(
      "gothic-panel-content",
      "custom-content",
    );
  });

  it("allows the base artwork opacity to be tuned", () => {
    render(
      <GothicPanel aria-label="半透明金色面板" baseOpacity={0.5}>
        内容
      </GothicPanel>,
    );

    expect(screen.getByLabelText("半透明金色面板")).toHaveStyle({
      "--gothic-panel-base-opacity": "0.5",
    });
  });

  it("uses sliced gold panel assets rather than stretching the source image", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain('url("../assets/gothic-panel/gothic-panel-center.webp")');
    expect(css).toContain('url("../assets/gothic-panel/frame-corner-tl.webp")');
    expect(css).toContain('url("../assets/gothic-panel/ornament-top.webp")');
    expect(css).toContain('url("../assets/gothic-panel/ornament-left.webp")');
    expect(css).toContain("--gothic-panel-base-opacity");
    expect(css).not.toContain("gothic-panel-source");
    expect(css).not.toContain("background-size: 100% 100%");
  });

  it("draws long frame rails as continuous CSS artwork", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain("--gothic-panel-corner-inline: 150px");
    expect(css).toContain("--gothic-panel-top-block: 132px");
    expect(css).toContain("--gothic-panel-bottom-block: 140px");
    expect(css).toContain("--gothic-panel-rail-highlight");
    expect(css).toContain("linear-gradient(90deg");
    expect(css).toContain("linear-gradient(180deg");
    expect(css).toContain("background-repeat: no-repeat");
  });

  it("draws long frame rails without tiled edge artwork seams", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).not.toContain('url("../assets/gothic-panel/frame-edge-top.webp")');
    expect(css).not.toContain('url("../assets/gothic-panel/frame-edge-bottom.webp")');
    expect(css).not.toContain('url("../assets/gothic-panel/frame-edge-left.webp")');
    expect(css).not.toContain('url("../assets/gothic-panel/frame-edge-right.webp")');
    expect(css).toContain("--gothic-panel-rail-highlight");
    expect(css).toContain(".gothic-panel-edge-top");
    expect(css).toContain("linear-gradient(90deg");
    expect(css).toContain("linear-gradient(180deg");
  });

  it("stores key frame artwork at retina-ready source resolution", () => {
    const assetsDir = "src/assets/gothic-panel";

    expect(readWebpSize(join(assetsDir, "frame-corner-tl.webp"))).toMatchObject({
      width: expect.any(Number),
      height: expect.any(Number),
    });
    expect(readWebpSize(join(assetsDir, "frame-corner-tl.webp")).width).toBeGreaterThanOrEqual(300);
    expect(readWebpSize(join(assetsDir, "ornament-top.webp")).width).toBeGreaterThanOrEqual(960);
    expect(readWebpSize(join(assetsDir, "ornament-bottom.webp")).width).toBeGreaterThanOrEqual(900);
    expect(readWebpSize(join(assetsDir, "ornament-left.webp")).height).toBeGreaterThanOrEqual(320);
  });
});

function readWebpSize(path: string) {
  const buffer = readFileSync(path);

  if (buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WEBP") {
    throw new Error(`${path} is not a WebP file`);
  }

  let offset = 12;
  while (offset + 8 <= buffer.length) {
    const chunkType = buffer.toString("ascii", offset, offset + 4);
    const chunkSize = buffer.readUInt32LE(offset + 4);
    const payload = offset + 8;

    if (chunkType === "VP8L") {
      const bits = buffer.readUInt32LE(payload + 1);

      return {
        height: ((bits >> 14) & 0x3fff) + 1,
        width: (bits & 0x3fff) + 1,
      };
    }

    if (chunkType === "VP8X") {
      return {
        height: readUInt24LE(buffer, payload + 7) + 1,
        width: readUInt24LE(buffer, payload + 4) + 1,
      };
    }

    offset = payload + chunkSize + (chunkSize % 2);
  }

  throw new Error(`${path} is not a supported WebP container`);
}

function readUInt24LE(buffer: Buffer, offset: number) {
  return buffer[offset] + (buffer[offset + 1] << 8) + (buffer[offset + 2] << 16);
}
