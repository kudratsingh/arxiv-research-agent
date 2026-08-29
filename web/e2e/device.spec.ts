import { expect, test } from "@playwright/test";

import { FIXTURES, WORK_SURFACE_FLOOR_AT_412 } from "./support/env";
import {
  measureReflow,
  measureSafeArea,
  measureWorkSurface,
} from "./support/measure";
import { STATES, readyLocator } from "./support/states";

/**
 * The `Pixel 7` and `iPhone 15` projects — WO-08's deferred device proof.
 *
 * WO-08 criterion 7 ends: "The device-level proof is WO-21's `iPhone 15`
 * project." This file is that. It runs ONLY on the two device projects
 * (`playwright.config.ts` greps `@device`), at each device's own viewport,
 * device-scale-factor, touch capability and user agent — never at a viewport
 * this file chose, because a device profile whose viewport a test overrides
 * is a desktop browser wearing a costume.
 *
 * Pixel 7 is 412 × 915: the exact width 04 §8.3 audits and the width the
 * retained baseline mobile screenshots were taken at, so its numbers are
 * directly comparable to `baseline/screenshots/home-mobile-full.png`.
 * iPhone 15 is 393 × 852 and runs on WebKit, which is the engine where
 * `env(safe-area-inset-bottom)` actually matters.
 *
 * The 320/360/412 sweep across every §4 state is `reflow.spec.ts` on the
 * desktop projects. What is added here is the part only a device can say.
 */

/** Layout-distinct states, at the device's own width. */
const DEVICE_SWEEP = new Set([
  "landing",
  "thread-empty",
  "thread-populated",
  "plan-review",
  "running",
  "failed-partial",
  "expired",
  "thread-not-found-inline",
]);

test.describe("device projects — narrow-strip repair on real profiles", () => {
  for (const state of STATES.filter((entry) => DEVICE_SWEEP.has(entry.id))) {
    test(
      `${state.id} does not scroll horizontally at the device's own width`,
      { tag: "@device" },
      async ({ page }) => {
        await state.arrange?.(page);
        await page.goto(state.path, { waitUntil: "domcontentloaded" });
        await expect(readyLocator(page, state.ready)).toBeVisible();

        const sample = await measureReflow(page);
        expect(
          sample.scrollWidth,
          `${state.id}: scrollWidth ${sample.scrollWidth} > clientWidth ` +
            `${sample.clientWidth}` +
            (sample.widestOverflow === null
              ? ""
              : `; widest overflowing element is ${sample.widestOverflow.selector}`),
        ).toBeLessThanOrEqual(sample.clientWidth);
      },
    );
  }

  test(
    "the work surface is the whole viewport, not a strip beside a rail",
    { tag: "@device" },
    async ({ page }) => {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.locator("[data-workbench-shell]")).toBeVisible();

      const viewport = page.viewportSize();
      expect(viewport, "a device project must have a viewport").not.toBeNull();

      const surface = await measureWorkSurface(page);
      expect(
        surface.width,
        `work surface ${surface.width}px via "${surface.matched}" on a ` +
          `${viewport?.width}px device. 04 §8.3 measured 156px before WO-08: ` +
          "a 256px rail at every viewport with no breakpoint.",
      ).toBeGreaterThanOrEqual(WORK_SURFACE_FLOOR_AT_412);
      // Below `md` the rail is out of the layout entirely, so the surface is
      // the viewport — not "most of" it.
      expect(surface.width).toBe(viewport?.width);
    },
  );

  /**
   * WO-08 criterion 7's device half.
   *
   * What is asserted, and what deliberately is not, is argued in
   * `measureSafeArea`'s doc comment: Playwright emulates a viewport and a user
   * agent, not a display cutout, so `env(safe-area-inset-bottom)` resolves to
   * `0px` here and any non-zero expectation would be fiction. What IS
   * device-specific: whether the media query carrying the inset matches at
   * this device's width, and whether the composer slot is genuinely sticky in
   * the rendered document rather than only in the stylesheet source — which is
   * where WO-08's `layout.test.ts` had to stop.
   */
  test(
    "the safe-area inset and the sticky composer are live at this device width",
    { tag: "@device" },
    async ({ page }) => {
      await page.goto(`/c/${FIXTURES.populatedConversation}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(page.locator("[data-workbench-region='composer']")).toHaveCount(
        1,
      );

      const safeArea = await measureSafeArea(page);

      expect(
        safeArea.insetDeclarations,
        "the bottom inset must be declared EXACTLY once, on `.ew-shell__main` " +
          "— WO-08's own note is that it must not double when WO-20 fills the " +
          "composer slot",
      ).toBe(1);
      expect(
        safeArea.mediaMatchesHere,
        `the media condition carrying the inset (${safeArea.mediaCondition}) ` +
          "must actually match on a phone; a rule that never applies is not a " +
          "repair",
      ).toBe(true);
      expect(safeArea.composerPosition).toBe("sticky");
      expect(safeArea.composerBottom).toBe("0px");
    },
  );

  /**
   * The drawer, on a touch device.
   *
   * WO-08's `drawer.test.tsx` proves the APG behaviour in jsdom. What it
   * cannot prove is that the affordance exists and is operable where the rail
   * has actually been removed — which is only true at a real narrow viewport.
   */
  test(
    "the rail is reachable through a labelled header disclosure",
    { tag: "@device" },
    async ({ page }) => {
      await page.goto("/", { waitUntil: "domcontentloaded" });

      const shell = page.locator("[data-workbench-shell]");
      await expect(shell).toHaveAttribute("data-rail-mode", "drawer");
      await expect(shell.locator("nav")).toHaveCount(0);

      const trigger = page.locator("[data-drawer-trigger]").first();
      await expect(trigger).toBeVisible();
      await expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
      await expect(trigger).toHaveAttribute("aria-expanded", "false");

      await trigger.click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expect(trigger).toHaveAttribute("aria-expanded", "true");
      // The rail's content is what the drawer holds.
      await expect(
        dialog.getByRole("link", { name: "Scientific claim verification" }),
      ).toBeVisible();

      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      await expect(trigger).toBeFocused();

      // Opening a dialog must not make the page pan.
      const sample = await measureReflow(page);
      expect(sample.scrollWidth).toBeLessThanOrEqual(sample.clientWidth);
    },
  );
});
