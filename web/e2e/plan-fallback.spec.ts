import { expect, test, type Page } from "@playwright/test";

import { FIXTURES } from "./support/env";
import { interceptPaidPath } from "./support/paid-path";

/**
 * WO-S2b — the plan editor's Suspense fallback holds the place of the form.
 *
 * THE DEBT THIS PAYS. WO-S2 (PR 213) made the plan editor reachable by
 * taking `workspace.css`'s 14rem cap off the run row at the review pause, and
 * that cap was the thing that had been absorbing this component's arrival.
 * With the editor free to take its real height, a cold load at 1280x900 went:
 * t≈203ms the Suspense fallback mounts at 200px, t≈231ms the lazy
 * `PlanEditorFields` chunk resolves and the editor becomes 586px, and the
 * 161px of reading column still visible below it is pushed off screen —
 * cold-load CLS 0.05113 against 04 §8.2's 0.02 ceiling. The owner accepted
 * that breach to get the reachability and ordered it paid back here.
 *
 * NOTHING WAS SLOW AND NOTHING WAS UGLY. The fallback was 386px too short.
 * So the fix is a reservation, not a spinner, and the two tests below are the
 * outcome and the mechanism in that order.
 *
 * WHY THE MECHANISM TEST EXISTS AT ALL, given that the first one measures the
 * thing the budget is about. A CLS number is a measurement of a race: it is
 * charged only if the chunk lands after first paint, and on a fast enough
 * machine, or behind a warm HTTP cache, the growth can happen before anything
 * is painted and score zero over a fallback that reserves nothing. The second
 * test cannot pass that way — it holds the chunk, measures both boxes, and
 * compares them.
 *
 * WHY 1280x900 IS GATED AND 412x915 IS NOT. At 412 the review pause carries a
 * pre-existing, intermittent shift that S2b neither causes nor fixes: on
 * roughly a quarter of cold loads the run panel mounts after first paint and
 * pushes the whole reading column and the composer off screen at once
 * (`div.ew-thread__timeline` 435px at y=410 → out of view, 0.55191). It is
 * identical before and after this change — it is the panel APPEARING, not the
 * editor GROWING — and gating on it would pin a flake to this work order.
 * The number is recorded in `planning/08-assurance/S2b-CLS-FALLBACK.md`
 * instead. The gated device-profile sweep at that width is `cls.spec.ts`'s
 * `@device` block, which reads 0.00000 on this state.
 */

/** 04 §8.2's ceiling, the same constant `cls.spec.ts` gates on. */
const LOAD_CLS_CEILING = 0.02;

const REVIEW = `/c/${FIXTURES.populatedConversation}?job=${FIXTURES.planReview}`;

interface LoadShift {
  value: number;
  startTime: number;
  sources: { node: string; from: number[]; to: number[] }[];
}

interface LoadBucket {
  supported: boolean;
  total: number;
  entries: LoadShift[];
}

declare global {
  interface Window {
    __planFallbackCls?: LoadBucket;
  }
}

/**
 * Install the layout-shift accumulator BEFORE any page script.
 *
 * `buffered: true` hands over the entries the browser recorded before the
 * observer existed, which is what makes this a cold-load measurement rather
 * than a post-hydration one.
 */
async function observeLoadShift(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const supported =
      typeof PerformanceObserver !== "undefined" &&
      (PerformanceObserver.supportedEntryTypes ?? []).includes("layout-shift");
    const bucket: LoadBucket = { supported, total: 0, entries: [] };
    window.__planFallbackCls = bucket;
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
        // Excluded for the same reason CLS excludes them.
        if (shift.hadRecentInput) continue;
        bucket.total += shift.value;
        bucket.entries.push({
          value: Number(shift.value.toFixed(5)),
          startTime: Math.round(shift.startTime),
          // THE SOURCES, NOT JUST THE NUMBER. Whoever breaks this rule reads
          // this message first, and "0.05 exceeds 0.02" tells them nothing
          // about which box grew.
          sources: (shift.sources ?? []).map((source) => ({
            node:
              source.node === undefined || source.node === null
                ? "(detached)"
                : `${source.node.tagName.toLowerCase()}.${
                    String(source.node.className).trim().split(/\s+/)[0] ?? ""
                  }`,
            from: [
              Math.round(source.previousRect.y),
              Math.round(source.previousRect.height),
            ],
            to: [
              Math.round(source.currentRect.y),
              Math.round(source.currentRect.height),
            ],
          })),
        });
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
}

/** The height of one box, or -1 when it is not on the page. */
async function boxHeight(page: Page, selector: string): Promise<number> {
  return page.evaluate((sel) => {
    const element = document.querySelector(sel);
    return element === null
      ? -1
      : Number(element.getBoundingClientRect().height.toFixed(2));
  }, selector);
}

test.describe("WO-S2b — the review pause loads without moving the page", () => {
  test(
    "cold-loading the review pause at 1280x900 stays inside the CLS budget",
    { tag: "@cls" },
    async ({ page, browserName }, testInfo) => {
      test.skip(
        browserName !== "chromium",
        "`layout-shift` is a Chromium-only performance entry: Firefox and " +
          "WebKit implement neither it nor CLS, so this would collect nothing " +
          "and pass without measuring.",
      );
      const paid = await interceptPaidPath(page, testInfo);

      await page.setViewportSize({ width: 1280, height: 900 });
      await observeLoadShift(page);
      await page.goto(REVIEW, { waitUntil: "domcontentloaded" });

      // The form itself, not the fallback: the shift this test is about is
      // charged when the lazy chunk resolves, so nothing may be asserted
      // until it has.
      await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible();
      // A shift is reported on the frame after the one that caused it.
      await page.waitForTimeout(1_500);

      const cls = await page.evaluate(
        () => window.__planFallbackCls ?? { supported: false, total: 0, entries: [] },
      );

      expect(
        cls.supported,
        "the `layout-shift` entry type is not available, so nothing was " +
          "measured. This assertion must never pass by default.",
      ).toBe(true);
      expect(
        cls.total,
        `cold-load CLS on the review pause is ${cls.total.toFixed(5)} against ` +
          `04 §8.2's ${LOAD_CLS_CEILING} ceiling. Before WO-S2b this read ` +
          "0.05113, from `PlanEditor`'s Suspense fallback mounting 386px " +
          "shorter than the form that replaced it. If a `section.flex` or a " +
          "`div.ew-thread__timeline` is in the sources below, the fallback " +
          "has stopped being sized from the plan's row counts. Entries: " +
          JSON.stringify(cls.entries),
      ).toBeLessThanOrEqual(LOAD_CLS_CEILING);

      paid.expectExactly(0, "WO-S2b — cold-loading a paused run");
    },
  );

  for (const size of [
    { label: "1280x900", width: 1280, height: 900 },
    { label: "412x915", width: 412, height: 915 },
  ] as const) {
    test(
      `the fallback is exactly the height of the form it holds the place of, at ${size.label}`,
      { tag: "@cls" },
      async ({ page }, testInfo) => {
        const paid = await interceptPaidPath(page, testInfo);
        await page.setViewportSize({ width: size.width, height: size.height });

        // HOLD EVERY ROUTE CHUNK BY THE SAME DELAY, rather than trying to
        // name the lazy one. Chunk filenames carry content hashes and the
        // lazy chunk's bundled identifiers are minified, so any predicate
        // over the URL or the body is a guess that rots. A uniform delay
        // needs no predicate: the eager chunks all arrive `HOLD` late, React
        // then hydrates and asks for the lazy chunk, and that request pays
        // the delay a second time — so the fallback is on screen for `HOLD`
        // milliseconds whichever chunk it turns out to be.
        const HOLD = 600;
        await page.route(/\/_next\/static\/chunks\/.*\.js/, async (route) => {
          await new Promise((resolve) => setTimeout(resolve, HOLD));
          await route.continue();
        });

        await page.goto(REVIEW, { waitUntil: "domcontentloaded" });

        const loading = page.locator('[data-testid="plan-editor-loading"]');
        await expect(loading).toBeVisible();
        const reserved = await boxHeight(page, '[data-testid="plan-editor-loading"]');
        const sectionWhileLoading = await boxHeight(page, '[data-surface="plan-editor"]');

        await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible();
        await expect(loading).toHaveCount(0);
        const form = await boxHeight(page, 'form[data-edited]');
        const sectionLoaded = await boxHeight(page, '[data-surface="plan-editor"]');

        expect(reserved, "the fallback was never on screen — nothing measured").toBeGreaterThan(
          0,
        );
        // THE WHOLE CLAIM, IN ONE COMPARISON. Not "at least as tall":
        // over-reserving is the same defect with the sign flipped — the page
        // would shift UP when the shorter form arrived — so the two boxes
        // have to be equal, not ordered.
        expect(
          reserved,
          `at ${size.label} the fallback reserves ${reserved}px for a form ` +
            `that takes ${form}px. The reservation is built from the plan's ` +
            "own row counts and the form's own copy (`PlanEditor`'s " +
            "`PlanEditorFallback`); a difference here means one of the two " +
            "structures has changed and the other has not.",
        ).toBe(form);
        expect(
          sectionWhileLoading,
          "the plan editor's own box changed height when the chunk landed, " +
            "which is the shift this work order exists to remove.",
        ).toBe(sectionLoaded);

        paid.expectExactly(0, "WO-S2b — holding the lazy chunk");
      },
    );
  }
});
