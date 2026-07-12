import { readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { gzipSync } from "node:zlib";

const manifestPath = process.argv[2];

if (!manifestPath) {
  throw new Error("usage: check-mobile-bundle.mjs <vite-manifest-path>");
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const distDir = join(dirname(manifestPath), "..");
const entry = Object.values(manifest).find((chunk) => chunk.isEntry);

if (!entry) {
  throw new Error("Vite manifest does not contain an entry chunk");
}

const initialFiles = new Set();

function collectInitialFiles(chunk) {
  if (initialFiles.has(chunk.file)) {
    return;
  }

  initialFiles.add(chunk.file);
  for (const importKey of chunk.imports ?? []) {
    const importedChunk = manifest[importKey];
    if (!importedChunk) {
      throw new Error(`Vite manifest import is missing: ${importKey}`);
    }
    collectInitialFiles(importedChunk);
  }
}

collectInitialFiles(entry);

const initialJsGzipBytes = [...initialFiles]
  .filter((file) => file.endsWith(".js"))
  .reduce(
    (total, file) => total + gzipSync(readFileSync(join(distDir, file))).byteLength,
    0,
  );
const imageFiles = Object.values(manifest)
  .map((chunk) => chunk.file)
  .filter((file) => /\.(?:avif|jpe?g|png|webp)$/i.test(file));
const largestImageBytes = Math.max(
  0,
  ...imageFiles.map((file) => statSync(join(distDir, file)).size),
);

const initialJsBudget = 200 * 1024;
const largestImageBudget = 3.2 * 1024 * 1024;

if (initialJsGzipBytes > initialJsBudget) {
  throw new Error(
    `Initial JavaScript gzip budget exceeded: ${initialJsGzipBytes} > ${initialJsBudget}`,
  );
}

if (largestImageBytes > largestImageBudget) {
  throw new Error(
    `Largest image budget exceeded: ${largestImageBytes} > ${largestImageBudget}`,
  );
}

console.log(
  `mobile bundle budgets passed: initial_js_gzip=${initialJsGzipBytes} largest_image=${largestImageBytes}`,
);
