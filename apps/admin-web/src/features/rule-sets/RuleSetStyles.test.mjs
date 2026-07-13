import { readFileSync } from "node:fs";

describe("rule set responsive stylesheet contract", () => {
  it("switches list rows to unclipped cards by 720px", () => {
    const css = readFileSync(`${process.cwd()}/src/styles/index.css`, "utf8");
    const start = css.indexOf("@media (max-width: 720px)");
    const end = start < 0 ? -1 : css.indexOf("@media", start + 1);
    const compact = start < 0 ? "" : css.slice(start, end < 0 ? undefined : end);
    const listPanel = css.match(/\.rule-set-list-panel\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(compact).toContain(".rule-set-list");
    expect(compact).toContain(".rule-set-row");
    expect(compact).toContain(".rule-set-row-actions");
    expect(compact).toContain("grid-template-columns: minmax(0, 1fr) auto");
    expect(compact).not.toContain("overflow: hidden");
    expect(listPanel).not.toContain("overflow: hidden");
  });
});
