import { defineConfig } from "@playwright/test";

/** Existing isolated loopback stack; never starts or stops an owner's services. */
export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  outputDir: "../build/workspace-live/test-results",
  reporter: [
    ["list"],
    ["json", { outputFile: "build/workspace-live/results.json" }],
  ],
  use: {
    baseURL: process.env.WORKSPACE_LIVE_URL ?? "http://127.0.0.1:3137",
    browserName: "chromium",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    {
      name: "mobile",
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
