import { expect, test, type Locator, type Page } from "@playwright/test";

import { FIXTURES } from "./support/env";

/**
 * WO-S2 — the two surfaces the frontend survey measured out of reach, and the
 * assertion that stops them going back.
 *
 * WHAT WENT WRONG, AND WHY NOTHING ALREADY HERE CAUGHT IT. The shell is a
 * fixed application frame (`100dvh` plus `overflow: hidden` twice,
 * `workbench.css`) with two nested scrollers inside it: the run row, capped at
 * 14rem, and the reading column. Every gate this suite already owns was green
 * throughout, and each of them for a good reason:
 *
 *   `reflow.spec.ts` measures the HORIZONTAL axis — `scrollWidth <=
 *   clientWidth`. A porthole does not pan; it clips, and a clip is invisible
 *   to that measurement (that file's own header says so about the pre-WO-08
 *   shell).
 *
 *   `axe.spec.ts` / `axe-matrix.spec.ts` audit the accessibility tree. A
 *   control inside a scroll region IS in the tree, IS focusable, and IS
 *   named; `scrollable-region-focusable` even passes, because the region can
 *   be reached by keyboard. Nothing in the tree records that the region's
 *   scrollbar is an overlay the platform paints only while it is moving,
 *   inside a page the reader has already learned does not scroll.
 *
 *   `cls.spec.ts` asks the opposite question — that things do NOT move — and
 *   the fixed box that hid the editor is exactly what made that true.
 *
 * So the missing measurement is the vertical one, and it is the one below:
 * how much of a surface is hidden inside a scroller, and whether the page
 * itself can be scrolled to reach what is past the fold.
 *
 * THE FOUR NUMBERS, measured on `origin/main` at 30d40b2 against this seeded
 * stack, and re-measured on this branch:
 *
 *                                          before        after
 *   run row hidden px, 1280x900            771            0
 *   run row hidden px, 412x915             1545           0
 *   `Approve plan` viewport top, 1280x900  1007 (of 900)  1007, page scrolls
 *   `Approve plan` viewport top, 412x915   1785 (of 915)  1785, page scrolls
 *   document scrollHeight at 412x915       915 == viewport 1931
 *   reading column hidden px at 412x915    1016           0
 *
 * WHY "REACHABLE" AND NOT "ON SCREEN". A 994px editor cannot be on screen at
 * once on a 900px viewport, and pretending otherwise would mean shrinking the
 * editor — a design change this work order does not make. What the product
 * owes the reader is that the control EXISTS SOMEWHERE THEY CAN GET TO with
 * the one gesture every page teaches: scrolling the page. So each assertion
 * below scrolls the DOCUMENT and nothing else. That is what makes it red on
 * `main`, where the document is exactly one viewport tall and a page scroll
 * is a no-op — Playwright's own `scrollIntoViewIfNeeded` would scroll the
 * hidden inner scroller instead and pass against the defect.
 */

/** The two widths 04 §8.3 and the survey both use. */
const WIDTHS = [
  { label: "1280x900", width: 1280, height: 900 },
  { label: "412x915", width: 412, height: 915 },
] as const;

const THREAD = `/c/${FIXTURES.populatedConversation}`;
const REVIEW = `${THREAD}?job=${FIXTURES.planReview}`;
const SUCCEEDED = `${THREAD}?job=${FIXTURES.succeeded}`;

/** `scrollHeight - clientHeight` for one box, plus the numbers behind it. */
async function hiddenInside(
  page: Page,
  selector: string,
): Promise<{ hidden: number; clientHeight: number; scrollHeight: number }> {
  return page.evaluate((sel) => {
    const element = document.querySelector(sel);
    if (element === null) {
      return { hidden: -1, clientHeight: -1, scrollHeight: -1 };
    }
    return {
      hidden: element.scrollHeight - element.clientHeight,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    };
  }, selector);
}

/** The document's own scroll geometry. */
async function pageScroll(
  page: Page,
): Promise<{ scrollHeight: number; clientHeight: number; bodyScrollHeight: number }> {
  return page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return {
      scrollHeight: root.scrollHeight,
      clientHeight: root.clientHeight,
      bodyScrollHeight: document.body.scrollHeight,
    };
  });
}

/**
 * Scroll the PAGE — never an inner scroller — until `element` is as close to
 * the middle of the viewport as the document allows.
 *
 * Written as a document scroll on purpose: see the header. A locator method
 * would scroll whatever ancestor happens to be scrollable, which is precisely
 * the thing under test.
 */
async function scrollPageTo(page: Page, target: Locator): Promise<void> {
  await target.evaluate((element) => {
    const root = document.scrollingElement ?? document.documentElement;
    const box = element.getBoundingClientRect();
    const wanted =
      root.scrollTop + box.top - root.clientHeight / 2 + box.height / 2;
    root.scrollTop = Math.max(0, wanted);
  });
  // One frame, so the assertion reads the scrolled position rather than the
  // one it asked for.
  await page.waitForTimeout(150);
}

test.describe("WO-S2 — the plan editor and the briefing are reachable", () => {
  for (const size of WIDTHS) {
    test(
      `the review pause hides none of the plan editor at ${size.label}`,
      { tag: "@reflow" },
      async ({ page }) => {
        await page.setViewportSize({ width: size.width, height: size.height });
        await page.goto(REVIEW, { waitUntil: "domcontentloaded" });

        const approve = page.getByRole("button", { name: "Approve plan" });
        await expect(approve).toBeAttached();

        // 1. NOTHING IS HIDDEN INSIDE THE ROW. This is the assertion that
        //    fails on `main`: 771 at 1280x900 and 1545 at 412x915, from
        //    `.ew-thread__run[data-run="attached"] { height: 14rem }` applying
        //    to a paused run it was never written for.
        const row = await hiddenInside(page, ".ew-thread__run");
        expect(
          row.hidden,
          `the run row hides ${row.hidden}px of the plan editor at ` +
            `${size.label} (clientHeight ${row.clientHeight}, scrollHeight ` +
            `${row.scrollHeight}). At the review pause the run is stopped and ` +
            "spending nothing, and the only control that can resume it is in " +
            "this box — it may not be capped. See `data-run=\"review\"` in " +
            "ThreadTimeline and the two rules keyed on it.",
        ).toBe(0);

        // 2. …AND THE PAGE, NOT AN INNER SCROLLER, IS WHAT REACHES IT.
        const doc = await pageScroll(page);
        expect(
          doc.scrollHeight,
          `the document is ${doc.scrollHeight}px tall against a ` +
            `${doc.clientHeight}px viewport at ${size.label}, so the plan ` +
            "editor below the fold cannot be reached by scrolling the page.",
        ).toBeGreaterThan(doc.clientHeight);

        await scrollPageTo(page, approve);
        await expect(
          approve,
          `\`Approve plan\` is not in the viewport at ${size.label} after the ` +
            "PAGE has been scrolled to it. On `main` it sits at y=1007 " +
            "(1280x900) and y=1785 (412x915) inside a 224px box, and no page " +
            "scroll can move it.",
        ).toBeInViewport();
        await expect(
          page.getByRole("button", { name: "Cancel this run" }),
        ).toBeInViewport();

        // 3. THE MECHANISM, so that a future change cannot satisfy 1 and 2 by
        //    accident. The row's third `data-run` value is what both CSS rules
        //    key on, and `ThreadTimeline` writes it from the panel's own
        //    predicate — a row in the pause reporting `attached` would be the
        //    two halves of the repair drifting apart.
        await expect(page.locator(".ew-thread__run")).toHaveAttribute(
          "data-run",
          "review",
        );
      },
    );
  }

  /**
   * The second defect, at the width 04 §8.3 audits.
   *
   * `baseline-succeeded` rather than the bare thread because it is the state
   * the survey measured: a run attached, its briefing open, and `Export`
   * beside the heading — 219px of porthole over 1,235px of column, with the
   * two controls at y=655 and y=650 against a porthole whose bottom edge was
   * y=629.
   */
  test(
    "the briefing and Export are reachable on a phone, by scrolling the page",
    { tag: "@reflow" },
    async ({ page }) => {
      await page.setViewportSize({ width: 412, height: 915 });
      await page.goto(SUCCEEDED, { waitUntil: "domcontentloaded" });

      const briefing = page.getByRole("heading", { name: "Briefing" }).first();
      const exportControl = page.getByRole("button", { name: "Export" }).first();
      await expect(briefing).toBeAttached();
      await expect(exportControl).toBeAttached();

      // 1. THE PAGE SCROLLS. On `main` `document.body.scrollHeight` is exactly
      //    915 — the viewport — so there is no page scroll at all and the
      //    journey cannot be finished on a phone.
      const doc = await pageScroll(page);
      expect(
        doc.bodyScrollHeight,
        `document.body.scrollHeight is ${doc.bodyScrollHeight} against a ` +
          `${doc.clientHeight}px viewport: the page does not scroll, so ` +
          "everything past the fold is reachable only through a nested " +
          "scroller with no visible scrollbar.",
      ).toBeGreaterThan(doc.clientHeight);

      // 2. THE READING COLUMN IS A COLUMN, NOT A PORTHOLE. 1016px hidden on
      //    `main`; nothing hidden here, because the page is what scrolls.
      const column = await hiddenInside(page, ".ew-thread__timeline");
      expect(
        column.hidden,
        `the reading column hides ${column.hidden}px of the briefing at ` +
          `412x915 (clientHeight ${column.clientHeight}, scrollHeight ` +
          `${column.scrollHeight}). Below md the briefing gets the column's ` +
          "height and the document carries the scroll.",
      ).toBe(0);

      // 3. …and both controls come into view under a page scroll.
      await scrollPageTo(page, briefing);
      await expect(
        briefing,
        "the `Briefing` heading is not in the viewport at 412x915 after the " +
          "page has been scrolled to it.",
      ).toBeInViewport();
      await expect(exportControl).toBeInViewport();
    },
  );

  /**
   * The mechanism, not just the outcome — the same shape `reflow.spec.ts`
   * ends on.
   *
   * A future change could satisfy everything above by deleting the frame
   * outright, which would also delete criterion 5's guarantee. So: at desktop
   * widths, with a LIVE run rather than a paused one, the frame is still a
   * frame and the run row is still the bounded box the CLS contract needs.
   */
  test(
    "a live run at desktop width keeps the bounded row the CLS contract needs",
    { tag: "@reflow" },
    async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.goto(`${THREAD}?job=${FIXTURES.running}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(page.locator('[data-surface="active-run"]')).toBeVisible();

      await expect(page.locator(".ew-thread__run")).toHaveAttribute(
        "data-run",
        "attached",
      );
      const doc = await pageScroll(page);
      expect(
        doc.scrollHeight,
        "the desktop shell stopped being a fixed frame during a live run. " +
          "WO-S2 lifts the frame at the review pause and below md, and " +
          "nowhere else: a live run at 1280x900 must still be the bounded " +
          "geometry `cls.spec.ts` measures.",
      ).toBe(doc.clientHeight);
      expect(
        await page.locator(".ew-thread__run").evaluate((el) => el.clientHeight),
      ).toBeLessThan(300);
    },
  );
});
