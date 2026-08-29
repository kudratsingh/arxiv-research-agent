import { expect, test } from "@playwright/test";

import { FIXTURES } from "./support/env";
import { sseFrame } from "./support/intercept";
import { interceptPaidPath } from "./support/paid-path";
import { REPORT_READER, RUN_PANEL, STATES, readyLocator } from "./support/states";

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

/* =========================================================================
 * Gate 3 criterion 7 — the COLD LOAD, on a phone.
 *
 * WHY THIS BLOCK EXISTS, AND WHY THE TEST ABOVE DID NOT CATCH WHAT IT MISSED.
 * The Gate 3 evidence pack measured mobile CLS **0.134** against 04 §8.2's
 * 0.02 ceiling on all four audited states, from a single shift of
 * `body > div.ew-shell > main#main` with the same score to five decimal
 * places everywhere — the shell's header gaining its drawer disclosure at
 * hydration (`lighthouse-diff.md` §4.1). The block above is right and stayed
 * green through all of it, because it is two different measurements away
 * from this one:
 *
 *   1. it is tagged `@cls`, which `playwright.config.ts` pins to the chromium
 *      DESKTOP project, and the defect was mobile-only — at ≥768px neither
 *      the server snapshot nor the client one renders a header trigger;
 *   2. it zeroes its accumulator AFTER the page has settled, on purpose, so
 *      that it measures checkpoints rather than page load.
 *
 * So this block is the other half: `@device`, which runs it at the Pixel 7
 * profile's own 412px — the width 04 §8.3 audits and the width Lighthouse
 * emulated — and it measures from before the first byte of page script to
 * after the route has settled.
 *
 * IT CANNOT PASS VACUOUSLY. `layout-shift` exists only in Chromium, so on
 * WebKit an observer would collect nothing and the assertion would be a green
 * tick over an unmeasured surface. The `iPhone 15` project therefore skips
 * explicitly rather than passing, and the Chromium run asserts that the entry
 * type is supported before it asserts anything about the number.
 *
 * Lighthouse is not in CI until WO-29 (`lighthouse-diff.md` §7), so until it
 * is, THIS is the gate on that budget.
 * ========================================================================= */

/** 04 §8.2's ceiling. The design intent, and the baseline, are 0.000. */
const LOAD_CLS_CEILING = 0.02;

/**
 * The four states the Gate 3 pack audited, taken from the same `STATES`
 * table the reflow sweep walks so the two cannot describe different pages.
 */
const AUDITED = ["landing", "thread-empty", "thread-populated", "plan-review"];

interface LoadShiftSource {
  node: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
}

interface LoadShiftBucket {
  supported: boolean;
  total: number;
  entries: { value: number; startTime: number; sources: LoadShiftSource[] }[];
}

declare global {
  interface Window {
    __loadCls?: LoadShiftBucket;
  }
}

test.describe("Gate 3 criterion 7 — a cold load does not move the mobile shell", () => {
  for (const state of STATES.filter((entry) => AUDITED.includes(entry.id))) {
    test(
      `${state.id} loads with no layout shift at this device's width`,
      { tag: "@device" },
      async ({ page, browserName }) => {
        test.skip(
          browserName !== "chromium",
          "`layout-shift` is a Chromium-only performance entry: Firefox and " +
            "WebKit implement neither it nor CLS, so this would collect " +
            "nothing and pass without measuring.",
        );

        // BEFORE ANY PAGE SCRIPT. `addInitScript` is what makes this a
        // cold-load measurement rather than a post-hydration one, and
        // `buffered: true` hands over the entries the browser recorded
        // before the observer existed.
        await page.addInitScript(() => {
          const supported =
            typeof PerformanceObserver !== "undefined" &&
            (PerformanceObserver.supportedEntryTypes ?? []).includes("layout-shift");
          const bucket: LoadShiftBucket = { supported, total: 0, entries: [] };
          window.__loadCls = bucket;
          if (!supported) return;
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              const shift = entry as PerformanceEntry & {
                value: number;
                hadRecentInput: boolean;
                sources?: {
                  node?: Element | null;
                  previousRect: DOMRectReadOnly;
                  currentRect: DOMRectReadOnly;
                }[];
              };
              // Excluded for the same reason CLS excludes them: a shift the
              // user asked for by tapping is not the defect.
              if (shift.hadRecentInput) continue;
              bucket.total += shift.value;
              bucket.entries.push({
                value: shift.value,
                startTime: Math.round(shift.startTime),
                // THE SOURCES, NOT JUST THE NUMBER. A CLS figure with no node
                // attached is unactionable, and this message is the first
                // thing whoever breaks this rule will read.
                sources: (shift.sources ?? []).map((source) => ({
                  node:
                    source.node === undefined || source.node === null
                      ? "(detached)"
                      : `${source.node.tagName.toLowerCase()}${
                          source.node.id === "" ? "" : `#${source.node.id}`
                        }.${String(source.node.className).trim().split(/\s+/)[0] ?? ""}`,
                  fromX: Math.round(source.previousRect.x),
                  fromY: Math.round(source.previousRect.y),
                  toX: Math.round(source.currentRect.x),
                  toY: Math.round(source.currentRect.y),
                })),
              });
            }
          }).observe({ type: "layout-shift", buffered: true });
        });

        await state.arrange?.(page);
        await page.goto(state.path, { waitUntil: "domcontentloaded" });

        // The mode has to have RESOLVED, not merely been server-guessed:
        // `drawer` is the client snapshot, so this is the exact moment the
        // 0.134 shift used to be charged.
        await expect(page.locator("[data-workbench-shell]")).toHaveAttribute(
          "data-rail-mode",
          "drawer",
        );
        // …and the route's own content has to be on screen, or "nothing
        // moved" would be true of a document that never arrived.
        await expect(readyLocator(page, state.ready)).toBeVisible();
        // A shift is reported on the frame after the one that caused it.
        await page.waitForTimeout(1_500);

        const cls = await page.evaluate(
          () => window.__loadCls ?? { supported: false, total: 0, entries: [] },
        );

        expect(
          cls.supported,
          "the `layout-shift` entry type is not available in this browser, so " +
            "nothing was measured. This assertion must never pass by default.",
        ).toBe(true);

        const detail = JSON.stringify(cls.entries);
        expect(
          cls.total,
          `${state.id}: load-time CLS ${cls.total.toFixed(5)} exceeds 04 §8.2's ` +
            `${LOAD_CLS_CEILING} ceiling. The Gate 3 pack measured 0.13357 here, ` +
            "from `main#main` dropping when the header gained its drawer " +
            'disclosure at hydration; if that is what came back, the trigger is ' +
            'being rendered from `mode === "drawer"` again instead of always ' +
            "being rendered and hidden at ≥768px by `.ew-shell__disclosure`. " +
            `Entries: ${detail}`,
        ).toBeLessThanOrEqual(LOAD_CLS_CEILING);

        // The specific regression, named. The budget above is the contract;
        // this is the defect, and it is worth failing separately so the
        // message says which one came back.
        const shellMovers = cls.entries.flatMap((entry) =>
          entry.sources
            .filter(
              (source) =>
                source.node.startsWith("main#main") ||
                source.node.includes("ew-shell__"),
            )
            .map((source) => source.node),
        );
        expect(
          shellMovers,
          `${state.id}: the shell moved after first paint — ${detail}. Nothing ` +
            "in `.ew-shell` may depend on hydration for its geometry.",
        ).toEqual([]);
      },
    );
  }
});
