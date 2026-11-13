import { defineConfig, devices } from "@playwright/test";
process.env.ANTHROPIC_API_KEY = "local-preview-disabled";
export default defineConfig({
  testDir: "./workspace-e2e",
  outputDir: "./build/workspace/test-results",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:3126", trace: "retain-on-failure" },
  webServer: {
    command: "npx next dev --hostname 127.0.0.1 --port 3126",
    url: "http://127.0.0.1:3126/today",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      WORKSPACE_PREVIEW: "1",
      ANTHROPIC_API_KEY: "local-preview-disabled",
      USE_MOCK_DATA: "true",
      API_INTERNAL_BASE: "http://127.0.0.1:9",
    },
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
      },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } },
    },
  ],
});
