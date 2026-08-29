/**
 * One definition of every address, port and sentinel the browser tier uses.
 *
 * These values have to agree in four places — `playwright.config.ts`, the
 * Compose overlay, `stack.sh`, and the specs — and a port that agrees in
 * three of them produces a suite that passes against the wrong stack. So they
 * are declared once here and read everywhere else.
 */

/**
 * The only `ANTHROPIC_API_KEY` any part of this tier is allowed to see.
 *
 * The same sentinel the Gate 1 baseline used (`baseline/README.md`, "Test
 * data and safety"). It is not a placeholder for a real key: the key is
 * deliberately *invalid*, so a job that somehow reached the workflow would
 * fail at the provider handshake rather than spend anything.
 */
export const DISABLED_API_KEY = "local-preview-disabled";

/** Host port the e2e stack's `web` container publishes on. */
export const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 13210);

/** Host port the e2e stack's `app` container publishes on. */
export const APP_PORT = Number(process.env.E2E_APP_PORT ?? 18210);

/** Where the browser goes. The Next container, so the proxy is in the loop. */
export const E2E_BASE_URL =
  process.env.E2E_BASE_URL ?? `http://127.0.0.1:${WEB_PORT}`;

/**
 * Where the *proxy* goes. Only the dev server needs this: inside Compose the
 * container resolves `http://app:8000` over the private network instead.
 */
export const UPSTREAM_BASE =
  process.env.E2E_UPSTREAM_BASE ?? `http://127.0.0.1:${APP_PORT}`;

/** Port for the StrictMode dev server. See `playwright.config.ts`. */
export const DEV_SERVER_PORT = Number(process.env.E2E_DEV_PORT ?? 13211);

/**
 * `localhost`, NOT `127.0.0.1`, and this is load-bearing.
 *
 * Next 16's dev server refuses to serve `/_next/static/chunks/*` to a host
 * that is not in `allowedDevOrigins`, and `127.0.0.1` is not allowed by
 * default while `localhost` is. Loading the dev server over the loopback IP
 * therefore returns the HTML and then 403s every JavaScript chunk, so the page
 * renders the server markup, never hydrates, and sits on "Loading
 * conversation…" forever — which looks exactly like a hung API call and is
 * not one. (Observed; the dev server logs "Blocked cross-origin request to
 * Next.js dev resource … from 127.0.0.1".)
 *
 * The alternative is adding `allowedDevOrigins: ['127.0.0.1']` to
 * `next.config.mjs`, which would put a development-only concession into the
 * production build config to satisfy a test. Using the hostname the dev
 * server already trusts costs nothing.
 */
export const DEV_BASE_URL =
  process.env.E2E_DEV_BASE_URL ?? `http://localhost:${DEV_SERVER_PORT}`;

/** `E2E_SKIP_DEV_SERVER=1` for a fast inner loop. */
export const SKIP_DEV_SERVER = process.env.E2E_SKIP_DEV_SERVER === "1";

/**
 * Where every artifact goes, relative to `web/`.
 *
 * Under `build/` on purpose: `web/tests/tokens.test.ts` walks all of `web/`
 * for literal colours and skips only `node_modules`, `.next`, `out`, `build`
 * and `.git`. Playwright's HTML report is full of them.
 */
export const ARTIFACT_DIR = process.env.E2E_ARTIFACT_DIR ?? "./build/e2e";

/**
 * The seeded ids, named once (`web/e2e/fixtures/seed.sh`).
 *
 * `expired` is seeded by its ABSENCE — `?job=` outlives the job it names, and
 * a clean 404 from `GET /research/{id}` (`src/api/routes.py:229`) is the
 * whole of slice step 2's second half.
 */
export const FIXTURES = {
  populatedConversation: "baseline-populated",
  emptyConversation: "baseline-empty",
  missingConversation: "baseline-not-found",
  succeeded: "baseline-succeeded",
  planReview: "baseline-plan-review",
  running: "baseline-running",
  cancelled: "baseline-cancelled",
  failedPartial: "baseline-failed-partial",
  /** WO-21: failed with NO result — §4 row 15, which the Gate 1 set lacked. */
  failed: "baseline-failed",
  /** WO-21: the failed-but-exportable turn slice step 5 needs. */
  partialExport: "baseline-partial-export",
  /** WO-21: the leased running row the `stream_timeout` frame lands on. */
  streamTimeout: "baseline-stream-timeout",
  expired: "baseline-expired",
} as const;

/** The three widths 04 §8.3 audits. */
export const NARROW_WIDTHS = [320, 360, 412] as const;

/**
 * 04 §8.3 / WO-08 criterion 4: at the 412 px audit width the work surface was
 * 156 px and must be at least 380 px. This is the assertion that actually
 * goes red→green — see `reflow.spec.ts` for why the reflow sweep does not.
 */
export const WORK_SURFACE_FLOOR_AT_412 = 380;
