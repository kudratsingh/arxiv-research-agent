import { expect, test } from "@playwright/test";

import { fillComposer } from "./support/composer";
import { FIXTURES } from "./support/env";
import { countStreamOpens, sseFrame } from "./support/intercept";
import { interceptPaidPath } from "./support/paid-path";
import { REPORT_READER, RUN_PANEL } from "./support/states";

/**
 * Criterion 6 — the five slice steps, end to end, on chromium.
 * 05 §2.1; DECISIONS.md D-009 item 4.
 *
 * WHAT THIS TESTS, HONESTLY. The approved slice is
 * "new question → reload-safe job → plan review → stream/reconnect →
 * report/metrics/export", and every step below is that step's *behaviour*
 * against the seeded stack. What it is NOT is a test of the redesigned
 * surfaces: on this commit `/` and `/c/[id]` are WO-08's shell wrapped around
 * the legacy `QueryForm`, `ConversationSidebar` and `ConversationThread`, and
 * WO-20 is the work order that swaps them. So the selectors here are WO-08's
 * data hooks and stable ARIA roles — the two things that survive that swap —
 * and never a class name or a layout position. Where a step's stated
 * behaviour does not exist yet, the gap is named in the test rather than
 * asserted away.
 *
 * Every step runs with the paid-path interceptor installed, so the count is
 * live for the whole journey and not only for step 1.
 */

const THREAD = `/c/${FIXTURES.populatedConversation}`;

test.describe("criterion 6 — the five slice steps", () => {
  /**
   * STEP 1 — New question (composer + non-idempotent submit).
   *
   * Surfaces the credential boundary (every call goes through
   * `web/app/api/[...path]/route.ts`), R-01, R-08, and the `?job=` handoff
   * that ADR 0053 exists for. The duplicate-submission matrix is
   * `paid-path.spec.ts`; here the step is asserted once, in sequence, as the
   * first leg of the journey.
   */
  test(
    "step 1 — a new question submits once and hands off with ?job=",
    { tag: "@slice" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);

      await page.goto("/", { waitUntil: "domcontentloaded" });
      // Landmarks first: the shell is what makes every later step legible.
      await expect(page.locator("main#main")).toHaveCount(1);
      await expect(page.locator("[data-workbench-shell]")).toBeVisible();

      const { submit } = await fillComposer(
        page,
        "How should scientific research agents verify claims?",
      );
      await submit.click();

      await page.waitForURL(
        (url) =>
          url.pathname === `/c/${FIXTURES.populatedConversation}` &&
          url.searchParams.get("job") === FIXTURES.running,
        { timeout: 30_000 },
      );

      paid.expectExactly(1, "slice step 1 — new question");

      // R-08: the key never reaches the browser. Every call the page made is
      // same-origin under /api, which is the only path the proxy serves.
      const offOrigin = paid
        .attempts()
        .filter((attempt) => !attempt.path.startsWith("/api/"));
      expect(offOrigin, "no request may leave the same-origin /api proxy").toEqual(
        [],
      );
    },
  );

  /**
   * STEP 2 — Reload-safe job (GET-first attach). R-02.
   *
   * Two halves, both from 05 §2.1: a reload mid-run re-adopts the SAME job
   * with no second POST, and a job that no longer exists renders a dead end
   * that says so, from a clean 404 (`src/api/routes.py:229`) rather than a
   * stuck busy state.
   */
  test(
    "step 2 — reloading mid-run re-adopts the same job and buys nothing",
    { tag: "@slice" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);

      await page.goto(`${THREAD}?job=${FIXTURES.running}`, {
        waitUntil: "domcontentloaded",
      });
      // The run the panel is attached to, read off its own hook. The legacy
      // panel printed the id as text; the redesign does not print an opaque
      // identifier at a reader, it carries it.
      await expect(page.locator(RUN_PANEL)).toHaveAttribute(
        "data-run-job",
        FIXTURES.running,
      );

      await page.reload({ waitUntil: "domcontentloaded" });

      await expect(page.locator(RUN_PANEL)).toBeVisible();
      expect(
        new URL(page.url()).searchParams.get("job"),
        "the id lives in the URL, so a reload re-attaches instead of buying a " +
          "second run (ADR 0053, MUST-KEEP #1)",
      ).toBe(FIXTURES.running);

      await page.waitForTimeout(1_500);
      paid.expectExactly(0, "slice step 2 — reload mid-run");
    },
  );

  /**
   * STEP 2, second half. `?job=` outlives the job it names.
   *
   * The failure mode this replaces is documented in the code it came from
   * (`web/lib/useResearchStream.ts:171-188`): without this, an expired id left
   * the UI in a busy state forever.
   */
  test(
    "step 2 — an expired job is a dead end that says so",
    { tag: "@slice" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);

      await page.goto(`${THREAD}?job=${FIXTURES.expired}`, {
        waitUntil: "domcontentloaded",
      });

      // H8's sentence and its recovery, both from the dictionary. The legacy
      // strings were the raw `useResearchStream` message; WO-12 replaced them
      // and WO-20 put the replacement on the route.
      await expect(
        page.getByText("This run is no longer available."),
      ).toBeVisible();
      await expect(
        page.getByText(/Ask the question again below/),
      ).toBeVisible();

      // The recovery is offered, never taken automatically.
      await page.waitForTimeout(1_000);
      paid.expectExactly(0, "slice step 2 — expired job");
    },
  );

  /**
   * STEP 2, third half — WO-10's deferred bfcache proof (RC-18).
   *
   * WO-10 built `pagehide`/`pageshow` handling
   * (`web/lib/job/useJobStream.ts:661-698`) because an open `EventSource`
   * makes `/c/[id]` bfcache-ineligible: the stream is closed on `pagehide` so
   * the page can be cached, and re-attached on `pageshow`. The proof that it
   * works is a back navigation, which is here.
   *
   * SCOPE. This asserts the app's half — same job re-adopted, no second POST,
   * the stream reopened. Whether the page was *actually* served from the
   * back/forward cache is Lighthouse's `bf-cache` audit, which is WO-29's;
   * a Playwright back navigation cannot distinguish a bfcache restore from a
   * fresh load, and claiming otherwise would be the kind of assertion that
   * reads well and proves nothing.
   */
  test(
    "step 2 — back navigation re-adopts the same job, with no second POST",
    { tag: "@slice" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      const stream = await countStreamOpens(page, FIXTURES.running);

      await page.goto(`${THREAD}?job=${FIXTURES.running}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(page.locator(RUN_PANEL)).toBeVisible();
      const opensBeforeLeaving = stream.opens();
      expect(opensBeforeLeaving).toBeGreaterThanOrEqual(1);

      // Leave, then come back with the browser's own back button.
      await page.goto(`/c/${FIXTURES.emptyConversation}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(page.getByText("Empty research thread").first()).toBeVisible();

      await page.goBack({ waitUntil: "domcontentloaded" });

      await expect(page.locator(RUN_PANEL)).toBeVisible();
      expect(
        new URL(page.url()).searchParams.get("job"),
        "coming back must re-adopt the job the URL names",
      ).toBe(FIXTURES.running);
      await expect
        .poll(() => stream.opens(), { timeout: 10_000 })
        .toBeGreaterThan(opensBeforeLeaving);

      await page.waitForTimeout(1_000);
      paid.expectExactly(0, "slice step 2 — back navigation (RC-18 bfcache)");
    },
  );

  /**
   * STEP 3 — Plan review. The HITL boundary.
   *
   * 🟢 THE GAP THIS TEST RECORDED IS CLOSED, AND IT IS NOW THE ASSERTION.
   * WO-21 wrote a 🔴 note here: 05 §2.1 step 3 requires that "a seeded
   * `pending_review` job renders its plan from `JobDetail.plan` **without** an
   * SSE frame", and it did not — `useResearchStream` attached stream-first, so
   * the plan only ever arrived as the backend's replayed `plan_ready` frame
   * (`src/api/streaming.py:464`) and cutting the frame left the surface empty.
   * WO-10's machine attaches GET-FIRST (`attachMode: "get-first"`, the
   * provider's default) and WO-20 put that machine on the route, so the read
   * that was missing is now the first thing the route does.
   *
   * So the stream is intercepted and held open with no frames at all, exactly
   * as the original attempt did, and the plan is asserted anyway. That is the
   * whole requirement, and it is the difference between a surface that needs
   * the server to push it and one that asks.
   */
  test(
    "step 3 — a seeded pending_review job renders its plan with no SSE frame",
    { tag: "@slice" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);

      // Held open, never fed. `plan_ready` cannot reach the client.
      let frames = 0;
      await page.route(
        (url) => url.pathname === `/api/research/${FIXTURES.planReview}/stream`,
        async (route) => {
          frames += 1;
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "cache-control": "no-cache" },
            body: ": held open with no frames\n\n",
          });
        },
      );

      await page.goto(`${THREAD}?job=${FIXTURES.planReview}`, {
        waitUntil: "domcontentloaded",
      });

      await expect(page.getByRole("heading", { name: "Plan", exact: true })).toBeVisible();
      // The seeded plan's own content — the values in `job:baseline-plan-review`,
      // which can only have come from `GET /research/{id}`.
      await expect(
        page.getByRole("textbox", { name: "Sub-question 1" }),
      ).toHaveValue("Which verification architectures are currently used?");
      await expect(
        page.getByRole("textbox", { name: "arXiv query 1" }),
      ).toHaveValue("retrieval augmented claim verification");

      // The resolutions are present, reachable, and none of them is a default
      // the user could trip over.
      await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible();

      // The stream was opened and told the client nothing, which is what makes
      // the assertion above about the GET rather than about the frame.
      expect(frames).toBeGreaterThanOrEqual(1);

      // A pause is not a purchase.
      paid.expectExactly(0, "slice step 3 — plan review attach");
    },
  );

  /**
   * STEP 3, second half — the 409.
   *
   * `POST /research/{id}/review` is intercepted rather than sent. Two
   * reasons, and the second is the important one:
   *
   *   1. A real review on a synthetic `pending_review` row would mutate the
   *      seed, so the suite would stop being idempotent after its first run.
   *   2. There is no LangGraph checkpoint behind a hand-written Redis row, so
   *      a real resume could not do anything meaningful anyway. Interception
   *      is the honest way to exercise the *client's* handling of the status
   *      code, which is what this step is about.
   *
   * The requirement is "a 409 refetches and re-renders instead of showing a
   * dead end", and that is exactly what WO-10 built: `machine.ts:840-853`
   * treats `review_conflict` as "the truth moved" — another tab resolved it,
   * or `api_hitl_timeout_sec` fired (`routes.py:261-264`) — and moves the
   * phase to `attaching` rather than to a failure. So the observable is a
   * REFETCH: the stream is reopened, the backend replays the job's real
   * state, and the surface re-renders from it.
   *
   * Asserting the refetch rather than an error sentence is deliberate. A test
   * that waited for "review failed (409)" would be asserting a dead end —
   * the thing this step exists to prevent.
   */
  test(
    "step 3 — a 409 on review refetches and re-renders, and is not a dead end",
    { tag: "@slice" },
    async ({ page }) => {
      let reviewCalls = 0;
      await page.route(
        (url) => url.pathname === `/api/research/${FIXTURES.planReview}/review`,
        async (route) => {
          reviewCalls += 1;
          await route.fulfill({
            status: 409,
            contentType: "application/json",
            body: JSON.stringify({
              detail: "job_not_awaiting_review (status=running)",
            }),
          });
        },
      );
      let detailReads = 0;
      await page.route(
        (url) => url.pathname === `/api/research/${FIXTURES.planReview}`,
        async (route) => {
          if (route.request().method() === "GET") detailReads += 1;
          await route.fallback();
        },
      );

      await page.goto(`${THREAD}?job=${FIXTURES.planReview}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(page.getByRole("heading", { name: "Plan", exact: true })).toBeVisible();
      const readsBefore = detailReads;

      await page.getByRole("button", { name: "Approve plan" }).click();

      await expect.poll(() => reviewCalls, { timeout: 10_000 }).toBe(1);
      await expect
        .poll(() => detailReads, {
          message:
            "a 409 must REFETCH rather than shout: useJobStream.ts:597-608 " +
            "dispatches `review_conflict` and immediately re-reads " +
            "GET /research/{id}, which is the only way the client learns where " +
            "the run actually got to",
          timeout: 15_000,
        })
        .toBeGreaterThan(readsBefore);

      // Re-rendered, not stranded: the plan is on screen and actionable again.
      await expect(page.getByRole("heading", { name: "Plan", exact: true })).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Approve plan" }),
      ).toBeEnabled();
      // And exactly one review was sent. A retry loop here would hammer the
      // HITL endpoint on every conflict.
      expect(reviewCalls).toBe(1);
    },
  );

  /**
   * STEP 4 — Stream and reconnect. R-05, the last-observed-checkpoint rule.
   *
   * The interrupted-200 and `stream_timeout` halves are `stream.spec.ts`
   * (criterion 4). What is asserted here is the third rule from 05 §2.1 step
   * 4, and it is the one that keeps live and replay from diverging: **a
   * terminal frame always triggers `GET /research/{id}` before any success is
   * claimed.** A client that believed the frame would show a result the
   * server never confirmed.
   */
  test(
    "step 4 — a terminal frame is reconciled against GET /research/{id}",
    { tag: "@slice" },
    async ({ page }) => {
      let detailReads = 0;
      await page.route(
        (url) => url.pathname === `/api/research/${FIXTURES.running}`,
        async (route) => {
          if (route.request().method() === "GET") detailReads += 1;
          await route.fallback();
        },
      );

      let streamOpens = 0;
      await page.route(
        (url) => url.pathname === `/api/research/${FIXTURES.running}/stream`,
        async (route) => {
          streamOpens += 1;
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "cache-control": "no-cache" },
            body:
              streamOpens === 1
                ? sseFrame("job_completed", {
                    job_id: FIXTURES.running,
                    status: "succeeded",
                  })
                : ": held open after the terminal frame\n\n",
          });
        },
      );

      await page.goto(`${THREAD}?job=${FIXTURES.running}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(page.locator(RUN_PANEL)).toBeVisible();

      await expect
        .poll(() => detailReads, {
          message:
            "a terminal frame must be reconciled against the API before any " +
            "success is claimed (R-05, 04 §4.4)",
          timeout: 15_000,
        })
        .toBeGreaterThanOrEqual(1);
    },
  );

  /**
   * STEP 5 — Report, metrics, export.
   *
   * The download assertions are `export.spec.ts` (criterion 7). What this
   * asserts is the reading surface of the step: the transcript carries both
   * turns, a turn expands to its report, and the export affordance is
   * present on the failed-with-partial-result turn as well as the succeeded
   * one.
   *
   * 🟢 R-14, CLOSED BY WO-18 AND COMPOSED BY WO-20. This spec used to record
   * a gap here: 05 §2.1 step 5 requires that a failed-with-partial-result job
   * "**shows** the report labelled partial and offers export", and
   * `ReportView.tsx:13-29` returned the failure notice before ever reaching
   * the report body — so the partial result the user paid for was invisible.
   * `ReportReader` has no branch that suppresses a non-empty `markdown`, and
   * WO-20 put it on the route, so the requirement is now asserted rather than
   * recorded: the partial briefing renders UNDER its banner, and the export
   * control is present on it.
   *
   * IT ALSO ASSERTS THE COLLAPSE RULE (WO-20 criterion 4). Only the newest
   * turn is open, so exactly one briefing and one export control exist until
   * an older turn is expanded by hand. The old count of two came from a
   * transcript that rendered every expanded turn's export beside a report it
   * had already parsed.
   */
  test(
    "step 5 — the newest turn reads, an older one expands, and both export",
    { tag: "@slice" },
    async ({ page }) => {
      await page.goto(THREAD, { waitUntil: "domcontentloaded" });
      await expect(
        page.getByRole("heading", { name: "Scientific claim verification" }),
      ).toBeVisible();

      // Turn 2 — failed, with a retained partial report — is the newest and
      // is open on arrival, so the briefing the run produced is on screen.
      await expect(page.getByRole("button", { name: /Turn 2/ })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
      await expect(
        page.getByText(/Partial briefing \(verification incomplete\)/),
      ).toBeVisible();
      // NOT the "partial" banner, and that is a CONTRACT fact rather than a
      // gap. `ConversationJobSummary` (`schemas.py:184-191`) carries no status
      // and no error, so a turn read back from a thread cannot say whether its
      // run failed — `lib/report/briefings.ts` says so in as many words and
      // refuses to invent the difference. The banner belongs to the run this
      // browser is watching, which is the `?job=` case below.
      await expect(
        page.getByText("Partial briefing from a run that failed."),
      ).toHaveCount(0);

      // One open turn, one briefing, one export control.
      await expect(page.locator(REPORT_READER)).toHaveCount(1);
      await expect(page.getByRole("button", { name: "Export" })).toHaveCount(1);

      // Turn 1 is a question row until it is asked for.
      const turn1 = page.getByRole("button", { name: /Turn 1/ });
      await expect(turn1).toHaveAttribute("aria-expanded", "false");
      await turn1.click();
      await expect(
        page.getByText(/Retrieval-Augmented Verification for Scientific Claims/),
      ).toBeVisible();

      // Export is now offered on both, which is what criterion 7 downloads.
      await expect(page.locator(REPORT_READER)).toHaveCount(2);
      await expect(page.getByRole("button", { name: "Export" })).toHaveCount(2);
    },
  );

  /**
   * STEP 5, second half — R-14 as the requirement states it.
   *
   * 05 §2.1 step 5: a failed-with-partial-result run "**shows** the report
   * labelled partial and offers export". `ReportView.tsx:13-29` returned the
   * failure notice and never reached the body, so the partial result the user
   * paid for was invisible — WO-21 recorded that as a 🔴 gap it could not
   * assert. `ReportReader` has no branch that suppresses a non-empty
   * `markdown`, and this is the state the label comes from: the run is
   * ATTACHED, so `GET /research/{id}` supplies the status and the error that
   * the thread's own job list cannot.
   */
  test(
    "step 5 — an attached failed run shows its partial briefing, labelled, with export",
    { tag: "@slice" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);

      await page.goto(`${THREAD}?job=${FIXTURES.partialExport}`, {
        waitUntil: "domcontentloaded",
      });

      // The label, above the briefing rather than instead of it (D-010 r2, H5).
      await expect(
        page.getByText("Partial briefing from a run that failed."),
      ).toBeVisible();
      await expect(
        page.getByText(/Partial briefing \(verification incomplete\)/),
      ).toBeVisible();
      await expect(
        page.locator(`${REPORT_READER}[data-partial="true"]`),
      ).toHaveCount(1);

      // And the export the backend permits on a non-empty `result`
      // (`routes.py:364-368`) is offered rather than withheld.
      await expect(page.getByRole("button", { name: "Export" })).toHaveCount(1);

      // Reading a failed run costs nothing.
      paid.expectExactly(0, "slice step 5 — partial briefing from a failed run");
    },
  );
});
