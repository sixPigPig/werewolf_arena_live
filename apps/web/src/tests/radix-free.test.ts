/// <reference types="node" />

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("Radix dependency removal", () => {
  it("does not depend on or import Radix UI", () => {
    const packageJson = readFileSync("package.json", "utf-8");
    const forbiddenPackageScope = "@radix" + "-ui";

    expect(packageJson).not.toContain(forbiddenPackageScope);

    const sourceFiles = listSourceFiles(join(process.cwd(), "src"));
    const importedRadix = sourceFiles.filter((file) =>
      readFileSync(file, "utf-8").includes(forbiddenPackageScope),
    );

    expect(importedRadix).toEqual([]);
  });
});

function listSourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const fullPath = join(directory, entry);
    const stat = statSync(fullPath);

    if (stat.isDirectory()) {
      return listSourceFiles(fullPath);
    }

    return /\.(css|ts|tsx)$/.test(entry) ? [fullPath] : [];
  });
}
