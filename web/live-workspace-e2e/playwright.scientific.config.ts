import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/** Explicit local public-PDF proof; the offline CI tier has no PDF fixture. */
export default defineConfig({
  ...base,
  testMatch: "scientific-sample.walkthrough.ts",
  outputDir: "../build/workspace-next-scientific/test-results",
  reporter: [
    ["list"],
    ["json", { outputFile: "build/workspace-next-scientific/results.json" }],
  ],
});
