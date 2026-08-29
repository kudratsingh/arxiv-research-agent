import { expect, test } from "@playwright/test";

import { FIXTURES } from "./support/env";
import { sseFrame } from "./support/intercept";
import { interceptPaidPath } from "./support/paid-path";
import { REPORT_READER, RUN_PANEL } from "./support/states";

/**
 * WO-20 criterion 5 — "incoming events never move the report column, CLS
 * 0.000 during a live run". 03 §2.2 row 10, 03 §5.6, WO-15 criterion 7.
 *
 * WHY THIS NEEDS A BROWSER AND NOT A UNIT TEST. The claim is about layout, and
 * layout is the one thing jsdom does not have: `getBoundingClientRect` returns
 * zeroes and `PerformanceObserver` reports no `layout-shift` entries there. So
 * the measurement is Chromium's own — the same entries CLS is computed from —
 * taken over the window in which checkpoints actually arrive.
 *
 * HOW THE WINDOW IS ISOLATED, AND WHY THAT IS THE HONEST FORM. Page-load CLS
 * is a different claim with a different owner (WO-29's Lighthouse budget), and
 * folding it in here would make this test pass or fail for reasons that have
 * nothing to do with checkpoints. So the stream is intercepted and HELD with
 * no frames at all until the thread has fully arrived; the accumulator is then
 * zeroed at a mark; and only then are three `node_completed` frames released.
 * Everything measured after the mark is caused by the frames.
 *
 * WHAT MAKES IT TRUE, in the two files that own it. `spine.css` gives the run
 * row and the ledger a `min-height` so the first tick fades in rather than
 * pushing anything, and its entrance animates `opacity` and nothing else.
 * `workspace.css` puts the run panel in its own grid row above a reading
 * column that is `minmax(0, 1fr)` and scrolls inside itself, and bounds that
 * row so it cannot take the column. `ActiveRunPanel` passes `now = null` to
 * `spineInputs`, so there is no per-second clock re-wrapping a sentence in the
 * row directly above the reader.
 */

const THREAD = `/c/${FIXTURES.populatedConversation}`;

/** Three checkpoints, in one release, exactly as the runner emits them. */
const CHECKPOINTS = ["retrieve", "read", "synthesize"]
  .map((node) =>
    sseFrame("node_completed", {
      job_id: FIXTURES.running,
      node,
      state_delta: { papers_seen: 3 },
    }),
  )
  .join("");

test.describe("WO-20 criterion 5 — a live run does not move the reading column", () => {
  test(
    "three checkpoints arrive and the cumulative layout shift is 0.000",
    { tag: "@cls" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);

      // The handler holds the stream until the test says the page has
      // settled, then releases every frame at once. Holding is what separates
      // "the page arrived" from "an event arrived".
      let release = (): void => {};
      const released = new Promise<void>((resolve) => {
        release = resolve;
      });
      await page.route(
        (url) => url.pathname === `/api/research/${FIXTURES.running}/stream`,
        async (route) => {
          await released;
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "cache-control": "no-cache" },
            body: CHECKPOINTS,
          });
        },
      );

      await page.goto(`${THREAD}?job=${FIXTURES.running}`, {
        waitUntil: "domcontentloaded",
      });

      // The whole surface, not just the panel: the column this criterion is
      // about is the one holding the briefing.
      await expect(page.locator(RUN_PANEL)).toBeVisible();
      await expect(page.locator(REPORT_READER)).toHaveCount(1);
      // A REAL BRIEFING HAS TO BE ON SCREEN, or this measures nothing. The
      // attached run is still going and has written no `result`, so the turn
      // it appends is the "no briefing yet" note; the thing this criterion
      // protects is a briefing the reader is ALREADY READING while a run goes
      // on above it. So the first turn — the succeeded one, whose report
      // carries the widest thing in the corpus, a table — is opened by hand
      // first. Its own arrival is before the mark and is not measured.
      await page.getByRole("button", { name: /Turn 1/ }).click();
      // The Markdown pipeline is a dynamic `import()`
      // (`lib/report/renderer.ts`); until it resolves the reader is showing a
      // skeleton, and zeroing the accumulator before the real body lands would
      // charge this test for the pipeline's arrival — page load, and WO-29's
      // to budget.
      await expect(page.locator("[data-briefing]")).toHaveCount(1);
      await expect(page.getByRole("table").first()).toBeVisible();
      // Nothing may still be arriving when the accumulator is zeroed.
      await page.waitForTimeout(1_500);

      // Zero the accumulator. `hadRecentInput` shifts are excluded for the
      // same reason CLS excludes them: a shift the user asked for by clicking
      // is not the defect.
      await page.evaluate(() => {
        const bucket: { total: number; entries: unknown[] } = {
          total: 0,
          entries: [],
        };
        (window as unknown as { __clsBucket: typeof bucket }).__clsBucket = bucket;
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            const shift = entry as PerformanceEntry & {
              value: number;
              hadRecentInput: boolean;
            };
            if (shift.hadRecentInput) continue;
            bucket.total += shift.value;
            // The SOURCES, not just the number. A CLS figure with no node
            // attached to it is unactionable, and this message is the first
            // thing whoever breaks this rule will read.
            const sources = (
              shift as unknown as {
                sources?: { node?: Element; previousRect: DOMRectReadOnly; currentRect: DOMRectReadOnly }[];
              }
            ).sources;
            bucket.entries.push({
              value: shift.value,
              startTime: shift.startTime,
              moved: (sources ?? []).map((source) => ({
                node:
                  source.node === undefined || source.node === null
                    ? "(detached)"
                    : `${source.node.tagName.toLowerCase()}.${source.node.className}`,
                from: source.previousRect.top,
                to: source.currentRect.top,
              })),
            });
          }
        }).observe({ type: "layout-shift", buffered: false });
      });

      // Release the checkpoints.
      release();

      // They arrived: the ledger carries the newest one by name, verbatim
      // (H11 — the node is an opaque string and is never looked up).
      await expect(page.getByText("synthesize").first()).toBeVisible();
      // And let the observer drain — a shift is reported on the frame after
      // the one that caused it.
      await page.waitForTimeout(1_500);

      const cls = await page.evaluate(
        () =>
          (
            window as unknown as {
              __clsBucket: { total: number; entries: unknown[] };
            }
          ).__clsBucket,
      );

      expect(
        cls.total.toFixed(3),
        "a checkpoint arriving moved the page. 03 §5.6: 'the last observed " +
          "tick fades in over dur-fast, opacity only, no translation — a " +
          "checkpoint arriving must never move the reading column'. Entries: " +
          JSON.stringify(cls.entries),
      ).toBe("0.000");

      // Watching a run costs nothing.
      paid.expectExactly(0, "criterion 5 — checkpoints during a live run");
    },
  );
});
