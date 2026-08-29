import { expect, test } from "@playwright/test";

import {
  A11Y_HEIGHTS,
  AXE_SWEEP_WIDTHS,
  openRailDrawer,
  retainAxe,
  writeArtifact,
} from "./support/a11y";
import {
  ALLOWLIST_PATH,
  AXE_TAGS,
  GATED_RULES,
  THEMES,
  analyze,
  describe as describeViolations,
  loadAllowlist,
  partition,
  settleForAudit,
  tagsOf,
} from "./support/axe";
import { STATES, readyLocator } from "./support/states";

/**
 * WO-27 criterion 1 — the full accessibility matrix.
 *
 * "Full-matrix axe: every state × light/dark × 320/412/1440, zero
 * violations, allowlist still empty."
 *
 * WHY THIS IS A SEPARATE FILE FROM `axe.spec.ts`. WO-22's sweep is pinned to
 * a **1440 × 1200** window on purpose, and its header says why: comparability
 * with the twelve retained baseline reports "is not only about the tag set:
 * `color-contrast` and `landmark-one-main` both depend on what is on screen,
 * and a report taken at a different width can differ from the baseline for
 * reasons that have nothing to do with the redesign." Widening that sweep
 * would trade WO-22's claim for this one. So the 1440 leg of the matrix stays
 * where it is, this file adds the two narrow legs, and one `npm run e2e`
 * produces all three.
 *
 * WHAT THE NARROW LEGS FIND THAT 1440 CANNOT. Below `md` the product is
 * structurally a different document, not a narrower one — the rail is removed
 * from the layout entirely (04 §8.3 repair step 1) and reached through a modal
 * drawer instead. So at 320 and 412 there are landmarks that do not exist at
 * 1440, a dialog that does not exist at 1440, and a set of composited
 * backgrounds `color-contrast` has never been measured against. An axe pass at
 * one width says nothing about the other two, which is exactly why criterion 1
 * asks for three.
 *
 * THE ASSERTIONS ARE WO-22'S, DELIBERATELY UNCHANGED. Same tag set, same six
 * gated rules, same empty allowlist, same partition. A second gate with
 * slightly different thresholds would be two standards, and the one that
 * mattered would be whichever ran last.
 */

const allowlist = loadAllowlist();

test.describe("WO-27 criterion 1 — every state, both themes, 320 and 412", () => {
  for (const width of AXE_SWEEP_WIDTHS) {
    for (const theme of THEMES) {
      for (const state of STATES) {
        test(
          `${state.id} · ${theme} · ${width}px (§4 ${state.rows.join(", ")})`,
          { tag: "@a11y" },
          async ({ page }, info) => {
            await page.setViewportSize({ width, height: A11Y_HEIGHTS[width] });
            await page.emulateMedia({ colorScheme: theme });
            await state.arrange?.(page);
            await page.goto(state.path, { waitUntil: "domcontentloaded" });

            // Below `md` the rail is not in the layout and `ThreadRailBridge`
            // is not mounted until the drawer is asked for, so a rail state
            // audited without this is an audit of a page the state does not
            // occur on. `reflow.spec.ts` opens it for the same reason.
            if (state.inRail === true) await openRailDrawer(page);

            // Never audit a blank page — axe finds nothing wrong with nothing.
            await expect(readyLocator(page, state.ready)).toBeVisible();
            // …and never audit the wrong theme.
            await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
            await settleForAudit(page);

            const results = await analyze(page);

            writeArtifact(
              info.outputDir,
              `axe/${state.id}.${theme}.${width}.json`,
              JSON.stringify(
                retainAxe(results, { state: state.id, theme, width }),
                null,
                2,
              ),
            );

            expect(
              tagsOf(results),
              "this report was produced with a different tag set from the " +
                "retained baseline and from WO-22's 1440 leg, so the three " +
                "widths of the matrix are not comparable to each other.",
            ).toEqual([...AXE_TAGS]);
            expect(results.testEngine.version).toMatch(/^4\.13\./);

            const split = partition(results, state.id, allowlist);

            expect(
              split.gated,
              `${state.id} · ${theme} · ${width}px fails a rule WO-22 gates at ` +
                "zero. These six are the defects the redesign exists to fix and " +
                `none may be allowlisted (${GATED_RULES.join(", ")}):\n` +
                describeViolations(split.gated),
            ).toEqual([]);

            expect(
              split.unlisted,
              `${state.id} · ${theme} · ${width}px violates a rule the baseline ` +
                "never failed. Criterion 1 says the allowlist stays empty, so " +
                `fix the surface rather than adding an entry to ${ALLOWLIST_PATH}:\n` +
                describeViolations(split.unlisted),
            ).toEqual([]);

            // The matrix row, appended by every worker (see `appendSummaryRow`
            // in support/axe.ts for why an exclusive-create header plus
            // O_APPEND is safe from several processes).
            writeArtifact(
              info.outputDir,
              `axe/rows/${state.id}.${theme}.${width}.tsv`,
              [
                state.id,
                theme,
                width,
                state.rows.join("+"),
                results.violations.length,
                split.gated.length,
                split.unlisted.length,
                results.incomplete.length,
                results.passes.length,
              ].join("\t"),
            );
          },
        );
      }
    }
  }
});

test.describe("WO-27 criterion 1 — the matrix is the whole matrix", () => {
  test("the allowlist is still empty", { tag: "@a11y" }, () => {
    expect(
      allowlist,
      `criterion 1 is "allowlist still empty", not "allowlist small". A first ` +
        `entry in ${ALLOWLIST_PATH} is a Gate 4 decision that belongs in review ` +
        "with a written justification, not in a passing run.",
    ).toEqual([]);
  });

  test("every §4 state is swept at both narrow widths in both themes", { tag: "@a11y" }, () => {
    // The arithmetic, asserted rather than left to whoever counts the test
    // list: a state silently dropped from `STATES` would shrink the matrix
    // and nothing else would notice. `reflow.spec.ts` asserts the other half
    // — that `STATES ∪ DEFERRED_STATES` is the whole of §4 — so pinning the
    // count here is a guard against silent shrinkage, not a second
    // definition of the state table.
    expect(AXE_SWEEP_WIDTHS).toHaveLength(2);
    expect(THEMES).toHaveLength(2);
    expect(
      STATES.length,
      "the number of reachable §4 states changed. If a state was ADDED, " +
        "update this number and re-take the evidence; if one was REMOVED, " +
        "the matrix just got smaller and somebody has to say why.",
    ).toBe(20);
    // 20 states × 2 themes × 2 widths, plus WO-22's 20 × 2 at 1440.
    expect(STATES.length * THEMES.length * AXE_SWEEP_WIDTHS.length).toBe(80);
  });
});
