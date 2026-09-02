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
  /**
   * WO-W13: the guided-read session, parked mid-session.
   *
   * Two writes back it (`e2e/fixtures/seed.sh`): the `awaiting_learner` job
   * row, and a real LangGraph checkpoint carrying the reading margin. The
   * second is what criterion 2 is about — a reload that re-renders the
   * transcript is only evidence if the transcript came out of durable state.
   */
  guidedSession: "baseline-guided-session",
} as const;

/**
 * The single principal the e2e stack issues (WO-W13).
 *
 * `web/e2e/support/compose.e2e.yml` turns `ENABLE_API_AUTH` on, because the
 * session loop cannot be mounted without it, and stamps every seeded row
 * with this key_id. The browser never sees either half: the `web` service's
 * server-side proxy injects the secret. Declared here for the same reason
 * every other address in this file is — the seed, the overlay and the specs
 * have to agree, and a value that agrees in two of three places is a suite
 * passing against the wrong stack.
 */
export const E2E_PRINCIPAL = process.env.E2E_PRINCIPAL ?? "e2e";
export const E2E_API_SECRET =
  process.env.E2E_API_SECRET ?? "sk_e2e_local_preview_disabled";

// --------------------------------------------------------------- WO-W17

/**
 * The pilot tier is OFF unless this is exactly `1`.
 *
 * `E2E_PILOT=1` selects a materially different stack: `support/compose.pilot.yml`
 * puts a Caddy edge in front of `web`, turns `PILOT_EDGE_AUTH` on, empties
 * `ARXIV_API_KEY`, and issues TWO principals instead of one. Under it the
 * `baseline-*` fixtures — stamped with `E2E_PRINCIPAL` — are invisible to
 * both pilots, so the ordinary suite has nothing to assert against. That is
 * why the pilot spec has its own Playwright config (`playwright.pilot.config.ts`)
 * rather than a tag inside the main one.
 */
export const E2E_PILOT_ENABLED = process.env.E2E_PILOT === "1";

/** Host port the pilot edge publishes. Distinct from every other port here. */
export const E2E_PILOT_EDGE_PORT = Number(
  process.env.E2E_PILOT_EDGE_PORT ?? 13290,
);

/** Where a pilot's browser goes: the edge, so `basic_auth` is in the loop. */
export const E2E_PILOT_BASE_URL =
  process.env.E2E_PILOT_BASE_URL ??
  `http://127.0.0.1:${E2E_PILOT_EDGE_PORT}`;

/**
 * The edge secret the local pilot stack uses.
 *
 * NOT A SECRET, AND SAYS SO IN ITS OWN VALUE — the same posture as
 * `E2E_API_SECRET` above. It is 51 characters because
 * `web/lib/server/pilot.ts` refuses anything under 32, and refusing a toy
 * secret is one of the behaviours this tier exists to exercise.
 */
export const E2E_PILOT_EDGE_SECRET =
  process.env.E2E_PILOT_EDGE_SECRET ??
  "pilot_edge_secret_local_preview_disabled_0000000000";

/**
 * The two pilot principals the local stack issues.
 *
 * `password` is committed on purpose and is committed ONLY here: the edge
 * never sees a plaintext password, it sees a bcrypt hash that
 * `support/stack.sh` generates at `up` time into `build/e2e/`, which is
 * git-ignored. So the repository contains a local sentinel that a spec can
 * type, and contains no credential material for any deployment — which is the
 * rule `deploy/pilot/README.md` states for the real thing.
 *
 * `keyId` is the NAME half of the stack's `API_KEYS` entry, which is what
 * lands on a row (ADR 0036) and what `fixtures/seed.sh` stamps. `apiKey` is
 * the secret half, and it is the value `web/tests/pilotPrincipal.test.ts`
 * greps the built client bundle for.
 */
export const E2E_PILOTS = {
  a: {
    user: "pilot-a",
    password: "pilot-a-local-preview-disabled",
    keyId: "pilot-a",
    apiKey: "sk_pilot_a_local_preview_disabled",
    conversation: "baseline-pilot-a-thread",
    session: "baseline-pilot-a-session",
  },
  b: {
    user: "pilot-b",
    password: "pilot-b-local-preview-disabled",
    keyId: "pilot-b",
    apiKey: "sk_pilot_b_local_preview_disabled",
    conversation: "baseline-pilot-b-thread",
    session: "baseline-pilot-b-session",
  },
} as const;

/** The three widths 04 §8.3 audits. */
export const NARROW_WIDTHS = [320, 360, 412] as const;

/**
 * 04 §8.3 / WO-08 criterion 4: at the 412 px audit width the work surface was
 * 156 px and must be at least 380 px. This is the assertion that actually
 * goes red→green — see `reflow.spec.ts` for why the reflow sweep does not.
 */
export const WORK_SURFACE_FLOOR_AT_412 = 380;
