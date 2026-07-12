import { defineConfig } from "@playwright/test";

const baseURL = "http://127.0.0.1:4174";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  outputDir: "test-results",
  preserveOutput: "always",
  use: {
    baseURL,
    browserName: "chromium",
    hasTouch: true,
    isMobile: true,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "small-mobile",
      use: { viewport: { width: 320, height: 568 }, deviceScaleFactor: 2 },
    },
    {
      name: "ios-mobile",
      use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3 },
    },
    {
      name: "android-mobile",
      use: { viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625 },
    },
  ],
  webServer: {
    command: "pnpm preview --host 127.0.0.1 --port 4174 --strictPort",
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
