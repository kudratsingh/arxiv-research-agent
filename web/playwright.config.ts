import { defineConfig, devices } from "@playwright/test";

import {
  ARTIFACT_DIR,
  DEV_BASE_URL,
  DEV_SERVER_PORT,
  DISABLED_API_KEY,
  E2E_BASE_URL,
  SKIP_DEV_SERVER,
  UPSTREAM_BASE,
} from "./e2e/support/env";

/**
 * WO-21 — the browser tier (04-ARCHITECTURE.md §7.3).
 *
 * WHAT THIS RUNS AGAINST. Not a mock server: the seeded local Compose stack
 * from `web/e2e/support/compose.e2e.yml`, seeded by
 * `web/e2e/fixtures/seed.sh`. Bring it up first —
 *
 *     npm run e2e:stack:up && npm run e2e:stack:seed && npm run e2e
 *
 * — or point `E2E_BASE_URL` at a stack you already have. WO-24 wires the
 * same three steps into the `web-e2e` CI job; nothing in this file assumes
 * CI, and nothing in CI needs to re-describe the stack.
 *
 * THE COST BOUNDARY IS STRUCTURAL, NOT POLITE. `ANTHROPIC_API_KEY` is
 * overwritten in this process before any test loads, so nothing the runner
 * spawns can inherit a real key from the shell, and `global-setup.ts` refuses
 * to start if the value is anything else. The stack itself is pinned to the
 * same sentinel by the overlay. `POST /api/research` is additionally
 * intercepted and fulfilled in-browser by `e2e/support/paid-path.ts`, so the
 * submit leg never reaches the backend at all
 * (`06-WORK-ORDERS.md` §0, "Cost boundary"; §7.3, "The one paid-path rule").
 *
 * WHY THE OUTPUT DIRECTORIES LIVE UNDER `build/`. `web/tests/tokens.test.ts`
 * walks the whole of `web/` looking for literal colours in `.ts/.tsx/.css/
 * .mjs/.js/.svg`, skipping only `node_modules`, `.next`, `out`, `build` and
 * `.git`. Playwright's HTML report is a bundle of `.js` full of literal
 * colours, so a report written to the default `playwright-report/` turns the
 * unit suite red. WO-06 put the Storybook static build under `build/` for
 * exactly this reason, and `web/.gitignore` already ignores it.
 */

// Overwrite, never default. A developer with a real key exported must not be
// able to hand it to a browser or a spawned dev server by accident.
process.env.ANTHROPIC_API_KEY = DISABLED_API_KEY;

/** Tags, so one spec file can serve several projects without duplication. */
const MOBILE_ONLY = /@device/;
const CHROMIUM_ONLY = /@slice|@export/;

export default defineConfig({
  testDir: "./e2e",
  // Everything Playwright writes goes under build/ — see the note above.
  outputDir: `${ARTIFACT_DIR}/test-results`,
  globalSetup: "./e2e/support/global-setup.ts",

  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Capped rather than left to `undefined` (half the cores). The whole suite
  // points at ONE Next container in front of ONE uvicorn worker, so past a
  // handful of parallel contexts the extra workers do not go faster — they
  // just make every navigation slower and turn timeouts into flakes that look
  // like product defects.
  workers: process.env.CI ? 2 : 4,
  timeout: 60_000,
  expect: { timeout: 10_000 },

  reporter: [
    ["list"],
    ["html", { outputFolder: `${ARTIFACT_DIR}/report`, open: "never" }],
    ["json", { outputFile: `${ARTIFACT_DIR}/results.json` }],
  ],

  use: {
    baseURL: E2E_BASE_URL,
    // Criterion 8. `retain-on-failure` rather than `on-first-retry`, because
    // locally `retries` is 0 and an on-retry-only trace would mean the first
    // red run — the one a developer actually looks at — produced nothing.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    // The seeded stack answers from Docker on loopback; a request that has
    // not answered in 15s is a broken stack, not a slow one.
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  /**
   * The dev server exists for ONE assertion, and it is honest about why.
   *
   * Criterion 3 requires the paid-path count to hold "across double-click,
   * Enter-key, React StrictMode double-mount, and offline→online". Three of
   * those are observable against the production container. The fourth is not:
   * `next.config.mjs` sets `reactStrictMode: true`, but React's double
   * invocation of effects is a **development-only** behaviour — in a
   * production build `<StrictMode>` is inert, so a test that claimed to prove
   * it against the container would be proving nothing.
   *
   * So the StrictMode case runs against a real `next dev` on its own port,
   * proxying to the same seeded stack. `E2E_SKIP_DEV_SERVER=1` turns it off
   * for a fast inner loop; the spec then skips itself rather than passing
   * vacuously.
   */
  webServer: SKIP_DEV_SERVER
    ? undefined
    : {
        command: `npx next dev -p ${DEV_SERVER_PORT}`,
        url: DEV_BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
        stdout: "ignore",
        stderr: "pipe",
        env: {
          // Same proxy target as the container, reached over the published
          // host port instead of the Compose network.
          API_INTERNAL_BASE: UPSTREAM_BASE,
          ANTHROPIC_API_KEY: DISABLED_API_KEY,
        },
      },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      grepInvert: MOBILE_ONLY,
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
      // The slice and the export downloads are pinned to chromium by
      // criteria 6 and 7; running them three times would add wall clock and
      // no evidence.
      grepInvert: new RegExp(`${MOBILE_ONLY.source}|${CHROMIUM_ONLY.source}`),
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
      grepInvert: new RegExp(`${MOBILE_ONLY.source}|${CHROMIUM_ONLY.source}`),
    },
    {
      // 412 × 915 — the exact width 04 §8.3 audits, and the width the
      // retained baseline screenshots were taken at.
      name: "Pixel 7",
      use: { ...devices["Pixel 7"] },
      grep: /@device|@theme/,
    },
    {
      // 393 × 852, and the reason `env(safe-area-inset-bottom)` exists.
      name: "iPhone 15",
      use: { ...devices["iPhone 15"] },
      grep: /@device|@theme/,
    },
  ],
});
