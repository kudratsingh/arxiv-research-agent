import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

import { expect } from "@playwright/test";
import type { Page, TestInfo } from "@playwright/test";

import { FIXTURES } from "./env";

/**
 * The paid-path interceptor (criterion 3; 04 §7.3 "The one paid-path rule";
 * 05 §2.1 step 1; R-01; MUST-KEEP #3).
 *
 * WHAT IT IS FOR. `POST /research` has no idempotency key — the client says
 * so at `web/lib/api/client.ts:170` ("never retry this automatically") and
 * the server has none to offer (`src/api/routes.py:179-197`). So a second
 * POST is a second paid run, and there is no way to take it back. The only
 * honest gate is a count, taken in the browser, on a path the app cannot see.
 *
 * WHY IT FULFILS RATHER THAN OBSERVES. Counting with `page.on("request")`
 * would leave the request to reach the backend, which would create a real job
 * row per assertion and make the seed non-idempotent. Fulfilling is also what
 * 04 §7.3 asks for: "The submit + stream leg runs against route
 * interception". The fulfilled `job_id` is a **seeded** id, so the handoff
 * `router.push('/c/{id}?job={job_id}')` lands on a thread that really exists
 * and the run continues into slice step 2 instead of dead-ending on a 404.
 *
 * WHY `POST /api/conversations` IS COUNTED TOO. The landing journey is two
 * writes, not one: `web/app/(workspace)/page.tsx` creates the conversation
 * and then submits. Both spend from the same hourly bucket
 * (`src/api/routes.py:157` and `:545`), which 05 §2.1 step 1 names
 * explicitly. A duplicate-suppression bug that fixed the research POST and
 * left the conversation POST doubled would still cost the user their budget,
 * so both are gated.
 *
 * PATH MATCHING IS EXACT, NOT GLOB. `**​/api/research` would also catch
 * `/api/research/{id}/export` and `/api/research/{id}/stream` in some
 * matchers; a URL predicate on `pathname` cannot.
 */

/** One recorded write attempt, in order. */
export interface PaidPathAttempt {
  path: "/api/research" | "/api/conversations";
  query: string | null;
  conversationId: string | null;
  at: number;
}

export interface PaidPathInterceptor {
  /** `POST /api/research` seen so far. The number criterion 3 is about. */
  researchPosts(): number;
  /** `POST /api/conversations` seen so far. */
  conversationPosts(): number;
  attempts(): readonly PaidPathAttempt[];
  /**
   * Assert the count and record the scenario in `research-post-count.txt`.
   * Recording happens whether the assertion passes or fails — a red run's
   * artifact is the interesting one.
   */
  expectExactly(expected: number, scenario: string): void;
  /** The `job_id` this interceptor hands back to the app. */
  readonly acceptedJobId: string;
  /**
   * Make the two writes fail the way a disconnected network makes them fail,
   * while still counting the attempt.
   *
   * `BrowserContext.setOffline` alone is not enough and the reason is
   * mechanical: Playwright's route interception sits ABOVE the network layer
   * that `setOffline` disables, so an intercepted request is fulfilled from
   * the harness and succeeds even though the page believes it is offline. The
   * app then tries to navigate, Next fetches the next route's payload over
   * the network that IS disabled, and the tab lands on the browser's
   * "no internet" page — which is what happened the first time this scenario
   * was written, and which was measuring the harness rather than the app.
   *
   * So the two are used together: `setOffline` for `navigator.onLine` and the
   * shell's `data-workbench-offline`, this for the request outcome.
   */
  setOffline(offline: boolean): void;
}

/**
 * The report criterion 3 names. Appended to, so every project shows up.
 *
 * Derived from `outputDir` rather than from `process.cwd()` or `rootDir`:
 * `playwright.config.ts` sets `outputDir` to `<web>/build/e2e/test-results`,
 * Playwright resolves it to an absolute path, and its parent is the one
 * directory both this module and `global-setup.ts` can agree on without
 * either of them knowing where the runner was started from.
 */
export function reportPathFrom(outputDir: string): string {
  return join(outputDir, "..", "research-post-count.txt");
}

function record(testInfo: TestInfo, line: string): void {
  const file = reportPathFrom(testInfo.project.outputDir);
  mkdirSync(dirname(file), { recursive: true });
  // Append rather than rewrite: workers run in parallel and each scenario
  // owns exactly one line, so no worker can lose another's result.
  appendFileSync(file, `${line}\n`, "utf8");
}

/**
 * Install the interceptor on a page.
 *
 * @param acceptedJobId the `job_id` handed back to the app. Defaults to the
 *   seeded running job, so the `?job=` handoff attaches to something real.
 */
export async function interceptPaidPath(
  page: Page,
  testInfo: TestInfo,
  acceptedJobId: string = FIXTURES.running,
  /**
   * Latency added to both writes.
   *
   * Not padding. A route fulfilled in microseconds closes the duplicate-submit
   * window by accident — the page navigates away before a second click can
   * land — so a zero-latency harness would report PASS for a page that has no
   * guard at all. The default is in the range a real `POST /conversations`
   * takes against the seeded stack, which is the window a real double click
   * has to squeeze into.
   */
  writeLatencyMs = 250,
): Promise<PaidPathInterceptor> {
  const attempts: PaidPathAttempt[] = [];
  let offline = false;
  const settle = (): Promise<void> =>
    new Promise((resolve) => setTimeout(resolve, writeLatencyMs));

  const readBody = (raw: string | null): Record<string, unknown> => {
    if (raw === null) return {};
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return {};
    }
  };

  await page.route(
    (url) => url.pathname === "/api/research",
    async (route) => {
      const request = route.request();
      if (request.method() !== "POST") {
        await route.fallback();
        return;
      }
      const body = readBody(request.postData());
      attempts.push({
        path: "/api/research",
        query: typeof body.query === "string" ? body.query : null,
        conversationId:
          typeof body.conversation_id === "string" ? body.conversation_id : null,
        at: Date.now(),
      });
      await settle();
      if (offline) {
        await route.abort("internetdisconnected");
        return;
      }
      // The shape of `ResearchAccepted` (contract/openapi.json), so the
      // client's `json<ResearchAccepted>` parse is exercised for real.
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: acceptedJobId,
          status: "queued",
          status_url: `/research/${acceptedJobId}`,
          stream_url: `/research/${acceptedJobId}/stream`,
        }),
      });
    },
  );

  await page.route(
    (url) => url.pathname === "/api/conversations",
    async (route) => {
      const request = route.request();
      if (request.method() !== "POST") {
        // GETs are the rail's list. Let them reach the seeded stack.
        await route.fallback();
        return;
      }
      attempts.push({
        path: "/api/conversations",
        query: null,
        conversationId: FIXTURES.populatedConversation,
        at: Date.now(),
      });
      await settle();
      if (offline) {
        await route.abort("internetdisconnected");
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          conversation_id: FIXTURES.populatedConversation,
          title: "Scientific claim verification",
          created_at: 1787883362,
          updated_at: 1787883424,
          jobs: [],
        }),
      });
    },
  );

  const researchPosts = (): number =>
    attempts.filter((a) => a.path === "/api/research").length;
  const conversationPosts = (): number =>
    attempts.filter((a) => a.path === "/api/conversations").length;

  return {
    researchPosts,
    conversationPosts,
    attempts: () => attempts,
    acceptedJobId,
    setOffline(next: boolean): void {
      offline = next;
    },
    expectExactly(expected: number, scenario: string): void {
      const seen = researchPosts();
      record(
        testInfo,
        [
          seen === expected ? "PASS" : "FAIL",
          testInfo.project.name,
          scenario,
          `expected=${expected}`,
          `POST /api/research=${seen}`,
          `POST /api/conversations=${conversationPosts()}`,
        ].join("\t"),
      );
      expect(
        seen,
        `${scenario}: expected exactly ${expected} POST /api/research, saw ${seen}. ` +
          "POST /research has no idempotency key (client.ts:170, routes.py:179-197), " +
          "so every extra one is a second paid run that cannot be refunded.",
      ).toBe(expected);
    },
  };
}

/** Header for the report, written once per run by the global setup. */
export const REPORT_HEADER = [
  "# research-post-count.txt — WO-21 criterion 3",
  "#",
  "# One line per intentional-submission scenario. `POST /api/research` is",
  "# counted in the browser by web/e2e/support/paid-path.ts and must be",
  "# exactly 1 per intentional submission: the endpoint has no idempotency",
  "# key, so a duplicate is a duplicate paid run (R-01, MUST-KEEP #3).",
  "#",
  "# verdict\tproject\tscenario\texpected\tresearch POSTs\tconversation POSTs",
].join("\n");
