import { defineConfig, devices } from "@playwright/test";

import {
  ARTIFACT_DIR,
  DEV_BASE_URL,
  DEV_SERVER_PORT,
  DISABLED_API_KEY,
  E2E_API_SECRET,
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
/**
 * `@axe` joins the chromium-only set for the same reason `@slice` and
 * `@export` are in it, plus one of its own. The wall-clock reason: the sweep
 * is forty navigations and forty full-document axe runs, and running it three
 * times would treble the slowest tier for no new evidence. The evidence
 * reason: the twelve retained baseline reports were taken in Chrome
 * (`baseline/README.md`, "local Google Chrome 151"), and WO-22 criterion 1 is
 * that the new reports are *directly comparable* to them — a Firefox or
 * WebKit `color-contrast` measurement is a different measurement, not a
 * stricter one.
 *
 * `@cls` joins it for a harder reason than either: the `layout-shift`
 * performance entry does not exist outside Chromium. Firefox and WebKit
 * implement neither the entry type nor Cumulative Layout Shift, so the
 * observer in `cls.spec.ts` would collect nothing and the assertion would pass
 * without measuring anything — a green tick over an unmeasured surface, which
 * is worse than no test.
 *
 * `@csp` (WO-30) joins it for the wall-clock reason and one of evidence. A
 * CSP violation is a property of the policy and the markup, not of the
 * engine, so sweeping twenty-two states three times buys nothing; and the one
 * place the engines genuinely differ — whether `style-src-attr` is honoured —
 * was measured directly across chromium, firefox and webkit while the policy
 * was being chosen, with the result recorded on the directive in
 * `web/lib/server/csp.ts`. A sweep is the wrong instrument for that question
 * anyway: it would only show the difference as an unexplained violation.
 *
 * `@a11y` (WO-27) joins it for three reasons of its own. Its axe half is the
 * same argument `@axe` makes and has to make it for the same reports to be
 * comparable. Its forced-colours half depends on `emulateMedia({ forcedColors
 * })`, which Chromium implements as a real palette replacement and the other
 * two engines do not implement at all — a sweep there would match the media
 * query, force nothing, and pass without measuring anything, which is the
 * failure mode `@cls` is pinned to chromium to avoid. And its keyboard half
 * reads focus back through Playwright's ARIA snapshot: sequential focus
 * navigation genuinely differs between engines (WebKit's Tab skips links
 * unless full keyboard access is on), so a cross-engine walk would report
 * platform policy as product defects. The engine limit is recorded in
 * `docs/revamp/evidence/gate-4/manual/keyboard.md` rather than left implicit.
 *
 * `@visual` (WO-28) joins it for the reason that is hardest to argue with:
 * the artefact IS the engine's rasterisation. Text hinting, form-control
 * metrics, scrollbar geometry and antialiasing differ between Chromium,
 * Gecko and WebKit, so a cross-engine snapshot set is three sets of committed
 * bytes that go stale independently and disagree for reasons that are never
 * product defects — which is precisely the maintenance debt WO-28's risk note
 * scopes out ("a full-matrix visual baseline is maintenance debt
 * disproportionate to a single-deployment product"). The limit is recorded in
 * `docs/revamp/evidence/gate-4/residual-risks.md` rather than left implicit.
 */
const CHROMIUM_ONLY = /@slice|@export|@axe|@cls|@csp|@a11y|@visual/;

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

  /**
   * WO-28. Where the committed PNGs live, and why `{platform}` is in the path.
   *
   * The default template is `{testFilePath}-snapshots/…`, which would put a
   * directory called `visual.spec.ts-snapshots` beside the specs. This is the
   * same names, in one obvious place, with the platform as a directory rather
   * than a filename suffix — so `git status` after a capture on a new OS shows
   * a new *directory*, not forty-eight renamed files.
   *
   * THE PLATFORM SEGMENT IS LOAD-BEARING, NOT TIDINESS. macOS and Linux
   * rasterise the same font at the same size differently (different hinting,
   * different subpixel handling), and a single set shared between them fails
   * on whichever host did not produce it — a gate that goes red for the host
   * rather than for the change, which is the failure mode WO-28 exists to
   * avoid. The set committed here is `darwin`; `e2e/README.md`,
   * "Regenerating", says how a Linux set is produced when CI wants one.
   */
  snapshotPathTemplate: "{testDir}/__screenshots__/{platform}/{arg}{ext}",

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
          // WO-W13. The e2e stack runs with `ENABLE_API_AUTH=true` (the
          // session loop cannot be mounted without it), so the dev server's
          // proxy needs the same server-side credential the `web` container
          // gets. Not a secret: it is a local sentinel against a stack with
          // no reachable provider, and it never enters the browser bundle.
          ARXIV_API_KEY: E2E_API_SECRET,
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
