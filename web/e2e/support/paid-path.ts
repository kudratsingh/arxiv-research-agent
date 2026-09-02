import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

import { expect } from "@playwright/test";
import type { Page, TestInfo } from "@playwright/test";

import { FIXTURES } from "./env";
import { assertMockModeStack } from "./mock-mode";

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
 * WHY THE TWO SESSION ROUTES ARE COUNTED (WO-W13). A guided session spends
 * on both of its writes. `POST /api/learn/sessions` starts a graph run
 * (`src/api/sessions.py:create_session` hands the job straight to `run_job`),
 * and `POST /api/learn/sessions/{id}/turn` resumes one — a tutor inference
 * per turn. Neither carries an idempotency key, for exactly the reason
 * `POST /research` does not, so a duplicate is a duplicate paid turn and
 * cannot be taken back. `session_max_turns` and WO-W06's per-session cost
 * ceiling bound the TOTAL a session can spend; neither makes a duplicate
 * free, and neither is a reason to stop counting. Both are FULFILLED rather
 * than observed, on the same argument as the research POST: a counted-but-
 * forwarded write would resume a real graph and leave the seeded session in
 * a state the next run does not expect, which would make `seed.sh`
 * non-idempotent.
 *
 * THE ONE EXCEPTION, AND ITS PRECONDITION (WO-W13b). The two SESSION routes
 * have a second mode — `sessionMode: "mock-pass-through"` — in which they are
 * counted and recorded exactly as before and then FORWARDED to the backend.
 * It exists for one test: Gate W1 row 1's full guided-read run, which needs
 * the graph to actually start, park, checkpoint and resume. A fulfilled
 * write starts nothing, so under the default mode that row is unprovable.
 *
 * Forwarding is gated on `support/mock-mode.ts`, which refuses unless the
 * stack pins `USE_MOCK_DATA=true` AND `ANTHROPIC_API_KEY=local-preview-
 * disabled` — checked in the overlay the stack is brought up from and, when
 * a daemon is reachable, in the running container too. Under mock mode the
 * session graph constructs no model client on any path (`src/agents/tutor.py`
 * `:159` and `:248`, `src/agents/assessment.py:178`), so the pass-through
 * spends nothing BY CONSTRUCTION rather than because a key would have been
 * rejected. `/api/research` and `/api/conversations` have no such mode and
 * never will: a research run under mock mode is still a run, and the claim
 * this file exists to make about them is structural.
 *
 * The report says which mode each row was taken in, so a reader cannot
 * mistake a forwarded count for an interdicted one.
 *
 * PATH MATCHING IS EXACT, NOT GLOB. `**​/api/research` would also catch
 * `/api/research/{id}/export` and `/api/research/{id}/stream` in some
 * matchers; a URL predicate on `pathname` cannot.
 */

/**
 * How the two session writes are answered.
 *
 * `"fulfil"` — the harness answers them; nothing reaches the backend. The
 * default, and the posture every spec but `session-flow.spec.ts` uses.
 *
 * `"mock-pass-through"` — counted, recorded, then forwarded to a stack that
 * has been asserted to be in mock mode. See the header.
 */
export type PaidSessionMode = "fulfil" | "mock-pass-through";

/** One recorded write attempt, in order. */
export interface PaidPathAttempt {
  path:
    | "/api/research"
    | "/api/conversations"
    | "/api/learn/sessions"
    | "/api/learn/sessions/{id}/turn";
  query: string | null;
  conversationId: string | null;
  at: number;
}

export interface PaidPathInterceptor {
  /** `POST /api/research` seen so far. The number criterion 3 is about. */
  researchPosts(): number;
  /** `POST /api/conversations` seen so far. */
  conversationPosts(): number;
  sessionCreates(): number;
  sessionTurns(): number;
  attempts(): readonly PaidPathAttempt[];
  /**
   * Assert the count and record the scenario in `research-post-count.txt`.
   * Recording happens whether the assertion passes or fails — a red run's
   * artifact is the interesting one.
   */
  expectExactly(expected: number, scenario: string): void;
  expectSessionExactly(
    expectedCreates: number,
    expectedTurns: number,
    scenario: string
  ): void;
  /** How the two session writes are being answered on this page. */
  readonly sessionMode: PaidSessionMode;
  /** The `job_id` this interceptor hands back to the app. */
  readonly acceptedJobId: string;
  readonly acceptedSessionId: string;
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
 * Everything a caller may vary. An object rather than three positional
 * arguments because the third would otherwise be a bare mode string at the
 * end of two numbers, and a call site nobody can read is a call site nobody
 * checks. No existing caller passed any of these.
 */
export interface PaidPathOptions {
  /**
   * The `job_id` handed back to the app. Defaults to the seeded running job,
   * so the `?job=` handoff attaches to something real.
   */
  acceptedJobId?: string;
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
  writeLatencyMs?: number;
  /**
   * How the two session writes are answered. See `PaidSessionMode` and the
   * header. `"mock-pass-through"` asserts the stack's mock-mode pins first
   * and throws if either is missing.
   */
  sessionMode?: PaidSessionMode;
}

/** Install the interceptor on a page. */
export async function interceptPaidPath(
  page: Page,
  testInfo: TestInfo,
  options: PaidPathOptions = {},
): Promise<PaidPathInterceptor> {
  const {
    acceptedJobId = FIXTURES.running,
    writeLatencyMs = 250,
    sessionMode = "fulfil",
  } = options;
  const attempts: PaidPathAttempt[] = [];
  let offline = false;
  const settle = (): Promise<void> =>
    new Promise((resolve) => setTimeout(resolve, writeLatencyMs));

  if (sessionMode === "mock-pass-through") {
    // Throws with the fix if either pin is missing. Printed AND recorded, so
    // the precondition is visible in the run output rather than inferable
    // from the absence of a failure.
    const summary = assertMockModeStack();
    // Printed, not only recorded: the check has to be readable in the run
    // log, because a passing assertion that leaves no trace is not evidence.
    console.log(summary);
    record(testInfo, `# ${testInfo.project.name}\t${testInfo.title}\t${summary}`);
  }

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

  const acceptedSessionId = "e2e-guided-session";
  await page.route(
    (url) => url.pathname === "/api/learn/sessions",
    async (route) => {
      const request = route.request();
      if (request.method() !== "POST") {
        await route.fallback();
        return;
      }
      attempts.push({
        path: "/api/learn/sessions",
        query: null,
        conversationId: null,
        at: Date.now(),
      });
      await settle();
      if (offline) {
        await route.abort("internetdisconnected");
        return;
      }
      if (sessionMode === "mock-pass-through") {
        // Counted above, then forwarded. The precondition was asserted before
        // any route was installed, so reaching this line means the stack
        // constructs no model client for what happens next.
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: acceptedSessionId,
          status: "pending",
          status_url: `/learn/sessions/${acceptedSessionId}`,
          stream_url: `/research/${acceptedSessionId}/stream`,
        }),
      });
    },
  );

  await page.route(
    (url) => /^\/api\/learn\/sessions\/[^/]+\/turn$/.test(url.pathname),
    async (route) => {
      const request = route.request();
      if (request.method() !== "POST") {
        await route.fallback();
        return;
      }
      attempts.push({
        path: "/api/learn/sessions/{id}/turn",
        query: null,
        conversationId: null,
        at: Date.now(),
      });
      await settle();
      if (offline) {
        await route.abort("internetdisconnected");
        return;
      }
      if (sessionMode === "mock-pass-through") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: acceptedSessionId,
          status: "awaiting_learner",
          accepted: true,
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
  const sessionCreates = (): number =>
    attempts.filter((a) => a.path === "/api/learn/sessions").length;
  const sessionTurns = (): number =>
    attempts.filter((a) => a.path === "/api/learn/sessions/{id}/turn").length;

  return {
    researchPosts,
    conversationPosts,
    sessionCreates,
    sessionTurns,
    attempts: () => attempts,
    acceptedJobId,
    acceptedSessionId,
    sessionMode,
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
    expectSessionExactly(expectedCreates, expectedTurns, scenario): void {
      const creates = sessionCreates();
      const turns = sessionTurns();
      record(
        testInfo,
        [
          creates === expectedCreates && turns === expectedTurns ? "PASS" : "FAIL",
          testInfo.project.name,
          scenario,
          `expected_session_creates=${expectedCreates}`,
          `POST /api/learn/sessions=${creates}`,
          `expected_session_turns=${expectedTurns}`,
          `POST /api/learn/sessions/{id}/turn=${turns}`,
          // WO-W13b. Which posture the counts were taken under, so a
          // forwarded row can never be read as an interdicted one.
          `mode=${sessionMode}`,
        ].join("\t"),
      );
      expect(creates, `${scenario}: unexpected session-create request count`).toBe(
        expectedCreates
      );
      expect(turns, `${scenario}: unexpected session-turn request count`).toBe(
        expectedTurns
      );
    },
  };
}

/**
 * Header for the report, written once per run by the global setup.
 *
 * TWO ROW SHAPES, AND THE LEGEND SAYS SO. `expectExactly` writes the
 * research row WO-21 defined; `expectSessionExactly` writes WO-W13's session
 * row, which counts two endpoints rather than one and therefore has a
 * different column list. They share a file because they are the same claim
 * about the same boundary — no automated tier issues a paid write — and a
 * reader looking for that claim should find all of it in one place.
 *
 * WO-W13b ADDS A COLUMN, NOT A THIRD SHAPE. `mode=` says how the two session
 * writes were answered. Without it a `POST /api/learn/sessions=1` row is
 * ambiguous between "the harness answered it" and "it reached the backend",
 * and those are different claims — so the column is part of the evidence
 * rather than decoration. Lines beginning `#` inside the body are the
 * mock-mode preconditions, one per pass-through scenario.
 */
export const REPORT_HEADER = [
  "# research-post-count.txt — WO-21 criterion 3, WO-W13 criterion 4,",
  "# WO-W13b criterion 3",
  "#",
  "# One line per intentional-submission scenario. Every paid write is",
  "# counted in the browser by web/e2e/support/paid-path.ts and must be",
  "# exactly 1 per intentional submission: none of these endpoints has an",
  "# idempotency key, so a duplicate is a duplicate paid run (R-01,",
  "# MUST-KEEP #3).",
  "#",
  "# research rows:",
  "#   verdict\tproject\tscenario\texpected\tresearch POSTs\tconversation POSTs",
  "# session rows (WO-W13, + mode since WO-W13b):",
  "#   verdict\tproject\tscenario\texpected creates\tsession POSTs" +
    "\texpected turns\tturn POSTs\tmode",
  "#",
  "# mode=fulfil            the harness answered both session writes; nothing",
  "#                        reached the backend. Every scenario but the",
  "#                        end-to-end guided run.",
  "# mode=mock-pass-through counted, then FORWARDED to a stack asserted to",
  "#                        pin USE_MOCK_DATA=true and the disabled key, under",
  "#                        which the session graph constructs no model client",
  "#                        at all (WO-W13b, Gate W1 row 1). The preconditions",
  "#                        for each such scenario are the `#` lines below.",
  "#",
  "# `POST /api/research` is fulfilled in EVERY mode and has no pass-through:",
  "# its count is 0 on every row above, which is criterion 3's claim.",
].join("\n");
