import { defineConfig, devices } from "@playwright/test";

import {
  ARTIFACT_DIR,
  DISABLED_API_KEY,
  E2E_PILOT_BASE_URL,
} from "./e2e/support/env";

/**
 * WO-W17 — the two-pilot browser tier, and why it is a second config file.
 *
 * IT CANNOT SHARE `playwright.config.ts`, FOR A REASON THAT IS NOT TIDINESS.
 * The pilot stack (`e2e/support/compose.pilot.yml`) empties `ARXIV_API_KEY`,
 * turns `PILOT_EDGE_AUTH` on, and issues two principals instead of one. Under
 * it, three things the main config depends on stop being true:
 *
 *   1. `E2E_BASE_URL` — the `web` container — no longer answers an
 *      unauthenticated request at all. Every browser goes through the edge.
 *   2. `global-setup.ts` probes four `baseline-*` fixtures through that URL.
 *      They are stamped with `E2E_PRINCIPAL`, which the pilot stack does not
 *      issue, so ADR 0036's `_check_ownership` correctly hides all four and
 *      the preflight would refuse to start the suite.
 *   3. The StrictMode dev server would need a fourth set of credentials to
 *      prove something this spec is not about.
 *
 * So this config runs one spec against the edge, with no global setup and no
 * dev server. The spec ALSO carries `test.skip` on `E2E_PILOT` for the case
 * the main config collects it in CI, where the pilot overlay is not applied —
 * a skip with a reason, which is what WO-W17 criterion 3 asks for when the
 * e2e job cannot run it without a workflow change (and no Phase W card edits
 * a workflow).
 *
 *     E2E_PILOT=1 bash e2e/support/stack.sh up
 *     E2E_PILOT=1 bash e2e/support/stack.sh seed
 *     E2E_PILOT=1 npx playwright test -c playwright.pilot.config.ts
 *
 * THE COST BOUNDARY. Same as the main config: `ANTHROPIC_API_KEY` is
 * overwritten in this process before any test loads, and the stack itself is
 * pinned to the same sentinel by `compose.e2e.yml`, which the pilot overlay
 * does not touch. This suite issues no `POST` of any kind, so it needs no
 * paid-path interception to prove it spends nothing — there is nothing to
 * intercept.
 */

// Overwrite, never default. A developer with a real key exported must not be
// able to hand it to a browser by accident.
process.env.ANTHROPIC_API_KEY = DISABLED_API_KEY;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /pilot\.spec\.ts$/,
  outputDir: `${ARTIFACT_DIR}-pilot/test-results`,

  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },

  reporter: [
    ["list"],
    ["json", { outputFile: `${ARTIFACT_DIR}-pilot/results.json` }],
  ],

  use: {
    // The EDGE, not the web container. `basic_auth` is the first hop, and a
    // suite that skipped it would be testing a header the test itself set.
    baseURL: E2E_PILOT_BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  // One engine. The claim under test is about credential resolution on the
  // server, which no rendering engine can disagree about.
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
