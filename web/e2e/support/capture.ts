import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

import { settleForAudit } from "./axe";

/**
 * The capture-determinism preamble, shared by the two suites that commit PNGs.
 *
 * WO-28's `visual.spec.ts` wrote this and was its only caller. WO-D2's
 * `readme.spec.ts` is the second: the README's screenshots became Playwright
 * snapshots, and a second copy of these four measures would have been a
 * second thing to keep in step with the first. The measures are the whole of
 * why a committed PNG reproduces, so they live in one place and are cited
 * from both.
 */

/**
 * Everything between "the page has arrived" and "the pixels will not move
 * again", with the drift each step removes.
 *
 * 1. **No placeholder is on screen.** `[data-skeleton-lines]` is the
 *    `Skeleton` primitive's own hook and every loading placeholder in the
 *    product is one — the rail's list, the thread route's shell, the plan
 *    editor's fields, the report's body. THIS IS THE MEASURE THAT WAS
 *    MISSING, AND IT IS WORTH SAYING WHY, BECAUSE THE OBVIOUS ONE IS NOT
 *    ENOUGH: a skeleton is *static*, so a DOM-quiescence check agrees with
 *    itself immediately and returns a page that is still waiting for its
 *    data. The first run of this suite captured `landing` with the rail's
 *    two threads loaded and the second captured it with the rail's two
 *    skeleton bars, 527 pixels apart — a flake that looks exactly like a
 *    visual regression and is not one. `Skeleton` deliberately does not
 *    animate (03 §3.7), which is what makes its absence the right signal
 *    rather than its stillness.
 * 2. **`settleForAudit`** — WO-22's two-consecutive-agreeing-samples loop over
 *    the serialised DOM, reused rather than re-implemented. A thread route
 *    paints its header from cache and fills the run panel and the event list
 *    afterwards; a capture between those moments photographs a page that
 *    never exists for a user, and photographs a *different* one next run.
 * 3. **`document.fonts.ready`** — the three families are self-hosted with
 *    `font-display: swap` (`evidence/gate-3/fonts.md`), so a capture taken
 *    before the swap is drawn in the metric-matched fallback and one taken
 *    after it is drawn in the real face. Both are real renders; only one is
 *    reproducible. The status is then asserted afterwards, because
 *    `fonts.ready` also resolves when loading FAILED.
 *    (No family is named here on purpose — `tests/fonts.test.ts` forbids it
 *    outside `app/tokens.css` and four other files, and this file is not one
 *    of them.)
 * 4. **Two `requestAnimationFrame`s** — the frame after the frame that
 *    applied the last style recalculation, so the compositor has painted what
 *    the DOM settled on.
 *
 * Three further measures are not here because they belong elsewhere:
 * `reducedMotion: "reduce"` and `colorScheme` are set on the page before
 * navigation (below); `animations: "disabled"`, `caret: "hide"` and
 * `scale: "css"` are passed to `toHaveScreenshot` itself; and the data is the
 * seeded `baseline-*` fixture set, which is the same on every run by
 * construction (`fixtures/seed.sh`, safety property 2).
 */
export async function settleForCapture(page: Page): Promise<void> {
  await expect(
    page.locator("[data-skeleton-lines]"),
    "a loading placeholder was still on screen. Whatever this snapshot is a " +
      "picture of, it is not a state — see measure 1 above.",
  ).toHaveCount(0, { timeout: 20_000 });
  await settleForAudit(page);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    });
  });
  expect(
    await page.evaluate(() => document.fonts.status),
    "the web fonts had not finished loading when the capture was taken, so " +
      "this snapshot is of the fallback metrics and will not reproduce",
  ).toBe("loaded");
}
