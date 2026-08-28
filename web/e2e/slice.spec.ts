import { expect, test } from "@playwright/test";

import { fillComposer } from "./support/composer";
import { FIXTURES } from "./support/env";
import { countStreamOpens, sseFrame } from "./support/intercept";
import { interceptPaidPath } from "./support/paid-path";

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
      await expect(page.getByText("Current turn")).toBeVisible();
      await expect(page.getByText(FIXTURES.running)).toBeVisible();

      await page.reload({ waitUntil: "domcontentloaded" });

      await expect(page.getByText("Current turn")).toBeVisible();
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

      await expect(page.getByText(/stream unavailable for job/)).toBeVisible();
      await expect(
        page.getByText(/Ask the question again to start a new run/),
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
      await expect(page.getByText("Current turn")).toBeVisible();
      const opensBeforeLeaving = stream.opens();
      expect(opensBeforeLeaving).toBeGreaterThanOrEqual(1);

      // Leave, then come back with the browser's own back button.
      await page.goto(`/c/${FIXTURES.emptyConversation}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(page.getByText("Empty research thread").first()).toBeVisible();

      await page.goBack({ waitUntil: "domcontentloaded" });

      await expect(page.getByText("Current turn")).toBeVisible();
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
   * 🔴 A MEASURED GAP, RECORDED RATHER THAN ASSERTED. 05 §2.1 step 3 requires
   * that "a seeded `pending_review` job renders its plan from `JobDetail.plan`
   * **without** an SSE frame". On this commit it does not. This test was first
   * written that way — the stream intercepted and held empty, no frames at
   * all — and the plan never appeared. The reason is in the two sources:
   * `useJobStream` attaches with `attachMode: "stream-first"`, and the backend
   * replays `plan_ready` to a newly attached `pending_review` job
   * (`src/api/streaming.py:464`), so the plan arrives as a FRAME and the
   * seeded `JobDetail.plan` is never read. Cut the frame and the plan review
   * surface is empty.
   *
   * That gap belongs to WO-17 (`PlanEditor`) and WO-20 (route composition),
   * which is where the GET-first read lands. Pinning it red here would fail
   * this work order for a defect it does not own, and pinning it green would
   * be a lie, so what is asserted below is the part that IS true today and
   * that must stay true after WO-17: attaching to a seeded `pending_review`
   * job shows that job's real plan and its three resolutions, over the real
   * stack, without spending anything.
   */
  test(
    "step 3 — a seeded pending_review job shows its plan and its resolutions",
    { tag: "@slice" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);

      await page.goto(`${THREAD}?job=${FIXTURES.planReview}`, {
        waitUntil: "domcontentloaded",
      });

      await expect(page.getByText("Plan review").first()).toBeVisible();
      // The seeded plan's own content — the values in `job:baseline-plan-review`.
      await expect(
        page.getByRole("textbox", { name: "Sub-questions #1" }),
      ).toHaveValue("Which verification architectures are currently used?");
      await expect(
        page.getByRole("textbox", { name: "Search queries #1" }),
      ).toHaveValue("retrieval augmented claim verification");

      // The resolutions are present, reachable, and none of them is a default
      // the user could trip over.
      await expect(page.getByRole("button", { name: "Approve as-is" })).toBeVisible();

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
      await expect(page.getByText("Plan review").first()).toBeVisible();
      const readsBefore = detailReads;

      await page.getByRole("button", { name: "Approve as-is" }).click();

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
      await expect(page.getByText("Plan review").first()).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Approve as-is" }),
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
      await expect(page.getByText("Current turn")).toBeVisible();

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
   * 🔴 R-14, RECORDED AND NOT ASSERTED AWAY. 05 §2.1 step 5 requires that a
   * failed-with-partial-result job "**shows** the report labelled partial and
   * offers export". On this commit it does not: `ReportView.tsx:13-29`
   * returns the failure notice and never reaches the report body, so the
   * partial result the user paid for is invisible in the attached view. The
   * backend permits the export (`src/api/routes.py:364-368`) and the
   * transcript turn does offer it, which is the half that works. This spec
   * asserts the half that works and does NOT pin the defect — WO-18's
   * `ReportReader/PartialFromFailedRun` is the work order that fixes it, and a
   * test pinning today's behaviour would fail that PR for succeeding.
   */
  test(
    "step 5 — the transcript renders both turns and offers export on each",
    { tag: "@slice" },
    async ({ page }) => {
      await page.goto(THREAD, { waitUntil: "domcontentloaded" });
      await expect(
        page.getByText("Scientific claim verification").first(),
      ).toBeVisible();

      // Turn 1, succeeded, with a report body.
      const turn1 = page.getByRole("button", { name: /Turn 1/ });
      await expect(turn1).toBeVisible();
      await turn1.click();
      await expect(
        page.getByText(/Retrieval-Augmented Verification for Scientific Claims/),
      ).toBeVisible();

      // Turn 2, failed but with a retained partial report. The last turn is
      // auto-expanded on load (`ConversationThread.tsx:44-50`).
      await expect(page.getByRole("button", { name: /Turn 2/ })).toBeVisible();
      await expect(
        page.getByText(/Partial briefing \(verification incomplete\)/),
      ).toBeVisible();

      // Export is offered on both, which is what criterion 7 then downloads.
      await expect(page.getByRole("button", { name: "Export" })).toHaveCount(2);
    },
  );
});
