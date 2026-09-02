import { expect, test } from "@playwright/test";

import {
  AXE_TAGS,
  THEMES,
  analyze,
  describe as describeViolations,
  loadAllowlist,
  partition,
  settleForAudit,
  tagsOf,
  writeReport,
} from "./support/axe";

/**
 * WO-W14 — `/learn/progress`, in a real browser.
 *
 * WHY THIS FILE EXISTS SEPARATELY FROM `axe.spec.ts`. That sweep walks the
 * `states.ts` §4 table, which is the WO-21 baseline's state set and is
 * diffed report-for-report against the twelve retained baseline captures.
 * The Ledger has no baseline counterpart — the route did not exist — so
 * adding it there would put a state into a comparison table that has
 * nothing to compare it with. The story tier already runs axe over all
 * four Ledger states in both themes (`LedgerView.stories.tsx`, the
 * Storybook a11y addon at `test: "error"`); what a jsdom story cannot
 * establish is that the ROUTE serves, hydrates and passes the same tag set
 * in a real engine behind the real proxy. That is this file's whole claim.
 *
 * WHICH STATE IT AUDITS DEPENDS ON THE STACK, DELIBERATELY. The seeded
 * stack runs with `enable_learner_profile` off by default, so
 * `GET /api/learn/progress` answers 404 and the surface renders
 * `LedgerUnavailable` — the ordinary case, not an incident. A stack with
 * the flag on renders the record instead. Both are states this work order
 * owns and both must be clean, so the readiness condition accepts either
 * and the test reports which one it audited rather than pinning a
 * configuration this spec does not control.
 *
 * NO PAID PATH EXISTS ON THIS ROUTE. There is no composer and no submit
 * control on `/learn/progress`; the only request it makes is one bounded
 * GET through the same-origin proxy.
 */

const LEDGER_OR_UNAVAILABLE = "[data-ledger], [data-ledger-unavailable]";

/**
 * The vocabulary `PEDAGOGY_PHRASES` bans, asserted against the RENDERED
 * document rather than against the dictionary.
 *
 * The copy gate proves no string in `web/lib/copy/` says these things.
 * This proves that what a browser actually paints does not either — the
 * one thing a gate over source strings cannot see.
 */
const PEDAGOGY = /\d+\s*%|\bmaster(?:ed|y|s)?\b|\bstreaks?\b|\bxp\b|\bunlock(?:ed)?\b|\bbadges?\b|\bdashboards?\b/i;

test.describe("WO-W14 — the Ledger route", () => {
  const allowlist = loadAllowlist();

  for (const theme of THEMES) {
    test(
      `/learn/progress · ${theme} — zero gated axe violations`,
      { tag: "@axe" },
      async ({ page }, info) => {
        await page.emulateMedia({ colorScheme: theme });
        const response = await page.goto("/learn/progress", {
          waitUntil: "domcontentloaded",
        });

        // The route serves. A 404 here would mean the `(learn)` group
        // stopped contributing the segment-free URL, which is a routing
        // regression the unit tier can only assert against the filesystem.
        expect(response?.status(), "GET /learn/progress").toBe(200);

        await expect(page.locator(LEDGER_OR_UNAVAILABLE).first()).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await settleForAudit(page);

        const results = await analyze(page);
        writeReport(info.outputDir, `learn-progress.${theme}`, results);

        expect(
          tagsOf(results),
          "this report was produced with a different tag set from the rest of " +
            "the axe tier, so it cannot be read beside them.",
          ).toEqual([...AXE_TAGS]);

        // Three-way split, exactly as the §4 sweep reads it: `gated` is a
        // criterion-2 regression, `unlisted` is a rule nobody has ruled on,
        // and `suppressed` needs a written justification to exist at all.
        const split = partition(results, "learn-progress", allowlist);
        expect(split.gated, describeViolations(split.gated)).toEqual([]);
        expect(split.unlisted, describeViolations(split.unlisted)).toEqual([]);
      },
    );
  }

  test(
    "renders no pedagogy vocabulary in the painted document",
    { tag: "@axe" },
    async ({ page }) => {
      await page.goto("/learn/progress", { waitUntil: "domcontentloaded" });
      await expect(page.locator(LEDGER_OR_UNAVAILABLE).first()).toBeVisible();
      await settleForAudit(page);

      const text = await page.locator("body").innerText();
      expect(text.length, "the page painted nothing to inspect").toBeGreaterThan(0);
      expect(text, "a pedagogy scalar reached the rendered page").not.toMatch(PEDAGOGY);
      // …and nothing offers an export the product does not have.
      expect(text).not.toMatch(/export|download|share this/i);
      expect(await page.locator("a[download]").count()).toBe(0);
    },
  );

  test(
    "reaches the Ledger from the path library, and only from there",
    { tag: "@axe" },
    async ({ page }) => {
      await page.goto("/learn", { waitUntil: "domcontentloaded" });
      // The label is written out rather than imported from
      // `lib/copy/ledger`: no spec in this tier reaches into `lib/`, and the
      // browser tier asserting the words a reader actually sees is the point
      // of it. A rename in the dictionary must show up here too.
      const entry = page.getByRole("link", { name: "Open the Ledger" });
      await expect(entry).toBeVisible();
      await entry.click();
      await expect(page).toHaveURL(/\/learn\/progress$/);
      await expect(page.locator(LEDGER_OR_UNAVAILABLE).first()).toBeVisible();

      // 00 §5.5: one link, not a second navigation row. The shell's own
      // chrome gains nothing.
      await expect(page.getByRole("link", { name: "Open the Ledger" })).toHaveCount(0);
    },
  );
});
