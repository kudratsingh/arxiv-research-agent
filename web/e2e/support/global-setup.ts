import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { request } from "@playwright/test";
import type { FullConfig } from "@playwright/test";

import {
  DEV_BASE_URL,
  DISABLED_API_KEY,
  E2E_BASE_URL,
  FIXTURES,
  SKIP_DEV_SERVER,
} from "./env";
import { REPORT_HEADER, reportPathFrom } from "./paid-path";

/**
 * Refuse to start against the wrong stack.
 *
 * Two failure modes this exists to make loud rather than mysterious:
 *
 *   1. **A real key in the environment.** `playwright.config.ts` overwrites
 *      `ANTHROPIC_API_KEY` before any test loads, so this check can only fail
 *      if that line was removed or if something re-set it afterwards. It is
 *      cheap and it guards the one rule that cannot be walked back.
 *
 *   2. **An unseeded stack.** Every spec in the suite reads `baseline-*`
 *      fixtures. Without the seed, roughly forty assertions fail with
 *      "expected visible" and none of them says "you forgot
 *      `npm run e2e:stack:seed`". So the preflight probes four fixtures
 *      through the proxy — which also proves `API_INTERNAL_BASE` resolves,
 *      i.e. that the credential boundary the whole suite runs through is
 *      actually wired — and names the missing step.
 *
 * The probes are all GETs. Nothing here writes, and nothing here can start a
 * run: `POST /research` is never issued by any part of this tier.
 */
export default async function globalSetup(config: FullConfig): Promise<void> {
  // Truncate the paid-path report and write its header. Every scenario
  // appends one line; starting fresh per run is what stops a stale PASS from
  // a previous run being read as evidence for this one.
  const project = config.projects[0];
  if (project !== undefined) {
    const file = reportPathFrom(project.outputDir);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, `${REPORT_HEADER}\n`, "utf8");
  }

  if (process.env.ANTHROPIC_API_KEY !== DISABLED_API_KEY) {
    throw new Error(
      `refusing to run: ANTHROPIC_API_KEY must be ${DISABLED_API_KEY}, ` +
        `saw ${process.env.ANTHROPIC_API_KEY ? "a different value" : "nothing"}. ` +
        "The e2e tier never contacts a model provider (06-WORK-ORDERS.md §0).",
    );
  }

  const api = await request.newContext({ baseURL: E2E_BASE_URL });
  try {
    const healthz = await api.get("/api/healthz");
    if (!healthz.ok()) {
      throw new Error(
        `stack not reachable at ${E2E_BASE_URL} (/api/healthz -> ${healthz.status()}). ` +
          "Run `npm run e2e:stack:up` first.",
      );
    }

    // Present-and-seeded.
    for (const [what, path] of [
      ["conversation", `/api/conversations/${FIXTURES.populatedConversation}`],
      ["job", `/api/research/${FIXTURES.succeeded}`],
      ["plan-review job", `/api/research/${FIXTURES.planReview}`],
      ["stream-timeout job", `/api/research/${FIXTURES.streamTimeout}`],
    ] as const) {
      const response = await api.get(path);
      if (!response.ok()) {
        throw new Error(
          `seed fixture missing: ${what} at ${path} -> ${response.status()}. ` +
            "Run `npm run e2e:stack:seed`.",
        );
      }
    }

    // Absent-on-purpose. If something wrote this id, slice step 2's
    // "no longer available" assertion would silently stop testing anything.
    const expired = await api.get(`/api/research/${FIXTURES.expired}`);
    if (expired.status() !== 404) {
      throw new Error(
        `fixture ${FIXTURES.expired} must NOT exist (got ${expired.status()}). ` +
          "Re-run `npm run e2e:stack:seed`, which deletes it.",
      );
    }
    await warmDevServer();
  } finally {
    await api.dispose();
  }
}

/**
 * Compile the dev server's routes BEFORE any test runs.
 *
 * `next dev` compiles a route on its first request, using every core it can
 * get. Playwright's `webServer.url` only waits for `/`, so without this the
 * StrictMode scenario's first navigation kicks off a full compile of
 * `/c/[id]` and `/api/[...path]` *in the middle of the parallel phase* — and
 * on a machine already running four browser workers against one container,
 * that starves the container's own responses badly enough that a prerendered
 * page does not finish hydrating for tens of seconds. Two unrelated
 * paid-path tests failed that way with "Run research … element is not
 * enabled", which reads exactly like a product defect and is not one.
 *
 * Warming here moves that work into the serial phase, where nothing is
 * waiting on it. Failures are swallowed: a dev server that will not warm is
 * the StrictMode test's problem to report, not a reason to refuse to run the
 * other 150-odd assertions.
 */
async function warmDevServer(): Promise<void> {
  if (SKIP_DEV_SERVER) return;
  const dev = await request.newContext({ baseURL: DEV_BASE_URL });
  try {
    for (const path of [
      "/",
      `/c/${FIXTURES.populatedConversation}?job=${FIXTURES.running}`,
      "/api/healthz",
    ]) {
      await dev.get(path, { timeout: 180_000 }).catch(() => undefined);
    }
  } finally {
    await dev.dispose();
  }
}
