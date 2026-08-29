import { expect, test } from "@playwright/test";

import { NARROW_WIDTHS, WORK_SURFACE_FLOOR_AT_412 } from "./support/env";
import { measureReflow, measureWorkSurface } from "./support/measure";
import {
  DEFERRED_STATES,
  SECTION_4_ROWS,
  STATES,
  readyLocator,
} from "./support/states";

/**
 * Criterion 5 — the reflow sweep, and the honest correction to its premise.
 *
 * WHAT THE WORK ORDER SAYS. "`scrollWidth <= clientWidth` at 320 / 360 /
 * 412 px on every state in §4. **Fails before WO-08, passes after.**"
 *
 * WHAT THE BROWSER SAYS. The first half is right and is asserted below. The
 * second half is not, and WO-08 measured it before this work order ran (PR
 * #88, "Honest correction to criterion 5's premise"): the sweep is green on
 * `1f3f45a` too, on both routes and all three widths. This branch re-ran the
 * same sweep against a checkout of `1f3f45a` and reproduced that result; the
 * output is in the PR body.
 *
 * WHY IT IS GREEN ON A SHELL THAT WAS BROKEN. `ConversationsShell.tsx:27` was
 * `<div class="flex-1 overflow-hidden">`. A flex item whose `overflow` is not
 * `visible` has an automatic minimum size of **0**, so the content column
 * collapsed to whatever the 256 px rail left over instead of pushing the
 * document wider. The old shell **clipped**; it never panned. `scrollWidth`
 * cannot see a clip. That is also why Lighthouse scored 98–99 on a UI whose
 * usable content was 108 px wide — the baseline README says so in as many
 * words.
 *
 * SO WHAT IS THE RED→GREEN. The work surface, which WO-08's criterion 4
 * already states as a number: **156 px → ≥380 px at the 412 px audit width**.
 * That is `work surface at 412px` below, and it is red on `1f3f45a` and green
 * here. The sweep is kept beside it — not as the proof of the repair, but as
 * a genuine regression guard: the new shell is CSS Grid with
 * `minmax(0, 1fr)`, which CAN overflow if a future surface drops `min-w-0`,
 * and then this assertion is the one that catches it.
 */

test.describe("criterion 5 — reflow sweep and the work-surface floor", () => {
  test(
    "§4 is fully accounted for: every row is either swept or deferred with a reason",
    { tag: "@reflow" },
    async () => {
      const swept = new Set(STATES.flatMap((state) => state.rows));
      const deferred = new Set(DEFERRED_STATES.flatMap((entry) => entry.rows));

      const unaccounted = SECTION_4_ROWS.filter(
        (row) => !swept.has(row) && !deferred.has(row),
      );
      expect(
        unaccounted,
        "every §4 row must be swept by STATES or listed in DEFERRED_STATES with " +
          "the work order that creates its surface. An unaccounted row is a state " +
          "nobody is testing and nobody has admitted to not testing.",
      ).toEqual([]);

      // The other direction: nothing claims a row §4 does not have.
      const invented = [...swept, ...deferred].filter(
        (row) => !SECTION_4_ROWS.includes(row),
      );
      expect(invented, "these rows are not in §4").toEqual([]);
    },
  );

  for (const state of STATES) {
    test(
      `${state.id} (§4 ${state.rows.join(", ")}) does not scroll horizontally at 320 / 360 / 412`,
      { tag: "@reflow" },
      async ({ page }) => {
        await state.arrange?.(page);

        for (const width of NARROW_WIDTHS) {
          await page.setViewportSize({ width, height: 900 });
          await page.goto(state.path, { waitUntil: "domcontentloaded" });

          // Rail states below `md` live behind the header disclosure — the
          // rail is not in the layout, and `ThreadRailBridge` is not even
          // mounted, until it is opened. See `StateEntry.inRail`.
          if (state.inRail === true) {
            // WAIT FOR THE RESOLVED MODE FIRST, and this is not defensive
            // padding. The disclosure is now in the SERVER markup at every
            // width — it has to be, or its box arrives at hydration and that
            // is the 0.13357 shift the Gate 3 pack measured — so a click can
            // land on a button React has not attached a handler to yet, and
            // the drawer never opens. `data-rail-mode` is `expanded` in the
            // server snapshot and `drawer` only once the client store has
            // been read, so waiting for it IS waiting for hydration.
            // `device.spec.ts` already waits on the same attribute before its
            // own click, for the same reason.
            await expect(page.locator("[data-workbench-shell]")).toHaveAttribute(
              "data-rail-mode",
              "drawer",
            );
            await page.locator("[data-drawer-trigger]").first().click();
          }

          // Never measure a blank page: "no horizontal scroll" is trivially
          // true of one, and that is how a responsive gate rots into a
          // tautology.
          await expect(readyLocator(page, state.ready)).toBeVisible();

          const sample = await measureReflow(page);
          expect(
            sample.scrollWidth,
            `${state.id} @${width}px: scrollWidth ${sample.scrollWidth} > clientWidth ` +
              `${sample.clientWidth}` +
              (sample.widestOverflow === null
                ? ""
                : `; widest overflowing element is ${sample.widestOverflow.selector} ` +
                  `reaching ${sample.widestOverflow.width}px`),
          ).toBeLessThanOrEqual(sample.clientWidth);
        }
      },
    );
  }

  /**
   * The assertion that actually goes red→green (WO-08 criterion 4).
   *
   * Only the two routes that have a work surface: the states above include
   * error and not-found renders whose column is intentionally short.
   */
  for (const [path, ready] of [
    ["/", "What should the literature settle?"],
    [`/c/baseline-populated`, "Scientific claim verification"],
  ] as const) {
    test(
      `work surface on ${path} is at least ${WORK_SURFACE_FLOOR_AT_412}px at 412px`,
      { tag: "@reflow" },
      async ({ page }) => {
        await page.setViewportSize({ width: 412, height: 915 });
        await page.goto(path, { waitUntil: "domcontentloaded" });
        // Waits for CONTENT, not for `[data-workbench-shell]`, on purpose: the
        // "before" half of this criterion is taken against `1f3f45a`, where
        // that hook does not exist. Gating on it would turn the red run into
        // "locator not found" instead of the number — 156 px — that is the
        // actual evidence.
        //
        // WO-20 CHANGED THE LANDING STRING. `/`'s content sentinel was
        // "arxiv-research-agent", the legacy page's `h1`; the redesigned page
        // renders 03 §1.4's display prompt instead. Re-taking the "before"
        // measurement against `1f3f45a` therefore needs the old string, which
        // is what the retained figure in this header records — the 156 px is
        // evidence already taken, not a run this file can repeat unchanged.
        await expect(page.getByText(ready).first()).toBeVisible();

        const surface = await measureWorkSurface(page);
        expect(
          surface.width,
          `${path} @412px: work surface measured ${surface.width}px via ` +
            `"${surface.matched}". 04 §8.3 records 156px before WO-08 — a 256px ` +
            "rail with no breakpoint, minus 48px of px-6 padding — and requires " +
            `at least ${WORK_SURFACE_FLOOR_AT_412}px after.`,
        ).toBeGreaterThanOrEqual(WORK_SURFACE_FLOOR_AT_412);
      },
    );
  }

  /**
   * The mechanism, not just the outcome.
   *
   * A future change could satisfy the floor above by putting the rail back
   * and letting the page pan, which would pass both assertions and reproduce
   * the original defect in a new form. So: below `md` the rail must not be in
   * the layout at all (04 §8.3 repair step 1).
   */
  test(
    "below md the rail is absent from the layout, not merely narrow",
    { tag: "@reflow" },
    async ({ page }) => {
      await page.setViewportSize({ width: 412, height: 915 });
      await page.goto("/", { waitUntil: "domcontentloaded" });

      const shell = page.locator("[data-workbench-shell]");
      await expect(shell).toHaveAttribute("data-rail-mode", "drawer");
      await expect(page.locator("[data-workbench-shell] nav")).toHaveCount(0);
      // …and the way in is a labelled header button, not a hover affordance.
      await expect(page.locator("[data-drawer-trigger]").first()).toBeVisible();
    },
  );
});
