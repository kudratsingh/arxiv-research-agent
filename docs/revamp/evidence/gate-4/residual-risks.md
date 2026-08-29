# Gate 4 — residual risks accepted at ship

What is **knowingly not covered** when this ships, why that was accepted, and
what would change the decision. [`05-MIGRATION.md`
§4.2](../../05-MIGRATION.md#42-gate-4--quality-and-documentation-before-ship)
requires this file and names its contents: "field CWV still unmeasured,
visual-regression coverage depth, browser matrix limits, and the MT-01
dependency for real multi-tenancy".

**This file is a stub, opened by [WO-28](../../06-WORK-ORDERS.md#wo-28--visual-regression-baselines)
with the one entry that work order owns.**
[WO-33](../../06-WORK-ORDERS.md#wo-33--gate-4-evidence-pack-and-residual-risks) assembles
the Gate 4 pack and extends it; its criterion 3 is that all four risks above
are named with owners. Entries are appended in `RR-NN` order and each keeps the
same seven fields, so the list can be read as a table without reading the prose.

A residual risk is **not** a defect and **not** a gap that was missed. It is a
decision: something that could have been covered, was costed, and was
deliberately left uncovered — with the reasoning written down while the person
who made it still remembers why.

---

## Index

| # | Risk | Owner | Accepted by |
|---|---|---|---|
| [RR-01](#rr-01--visual-regression-coverage-is-the-slice-not-the-matrix) | Visual-regression coverage is the slice, not the matrix | WO-28 | Gate 4 |
| RR-02 … | *field CWV still unmeasured; browser matrix limits; the MT-01 dependency for real multi-tenancy* | WO-33 | — |

---

## RR-01 — Visual-regression coverage is the slice, not the matrix

| Field | |
|---|---|
| **Risk** | A visual regression in a state the snapshot suite does not cover ships unnoticed. |
| **Owner** | [WO-28](../../06-WORK-ORDERS.md#wo-28--visual-regression-baselines), and after ship whoever owns [`web/e2e/visual.spec.ts`](../../../../web/e2e/visual.spec.ts). |
| **Accepted at** | Gate 4, on the branch that introduced the tier. |
| **Covered** | Forty-eight committed PNGs: the five slice steps (`05` §2.1) plus every degraded state that has a retained Gate 1 screenshot — twelve renders × light/dark × 412/1440 px, Chromium on `darwin`. |
| **Not covered** | The other nine `states.ts` rows; the third audit width (320); every `DEFERRED_STATES` transition; Firefox and WebKit; Linux; forced-colours; reduced-motion as a *separate* axis; and every Storybook story. |
| **Why accepted** | Below. |
| **What would change it** | Below. |

### What is covered, exactly

The inventory is asserted rather than described:
`visual.spec.ts`'s "the inventory is what the criterion asks for" block fails if
the count moves, if a slice step is missing, if a degraded state is also
claimed as a slice step, if two renders would write one file, or if a named
retained baseline screenshot no longer exists under
[`docs/revamp/baseline/screenshots/`](../../baseline/screenshots).

| Half | States |
|---|---|
| The five slice steps | `landing`, `running`, `plan-review`, `reconnecting`, `thread-populated` |
| Degraded, with a retained Gate 1 screenshot | `cancelled`, `failed-partial`, `expired`, `submission-error-500`, `rail-error-upstream`, `thread-not-found-inline`, `route-not-found` |

### Why this depth was accepted

1. **The matrix is 20 states × 2 themes × 3 widths = 120 renders**, and WO-27's
   axe pack already walks exactly that. As *screenshots* those 120 PNGs are
   roughly 8 MB of committed binary that a single legitimate change to a shared
   token — one step on the space scale, one line-height — invalidates in one
   commit. The cost of a visual baseline is not taking it; it is re-taking it,
   and re-taking 120 files by hand is how a team learns to run
   `--update-snapshots` without looking at the diff. At that point the gate
   asserts nothing while still costing every reviewer a large binary diff.
   [WO-28's own risk note](../../06-WORK-ORDERS.md#wo-28--visual-regression-baselines)
   states the same conclusion: "a full-matrix visual baseline is maintenance
   debt disproportionate to a single-deployment product."
2. **This is a single-deployment product.** There is no matrix of customer
   themes, no white-labelling, no per-tenant CSS
   ([MT-01](../../DECISIONS.md), and see RR-0x when WO-33 writes it). One
   deployment renders one way, and a regression that escapes the slice is
   found by looking at the product rather than by a bisect across tenants.
3. **The uncovered states are not uncovered by every tier.** Each of the nine
   states without a snapshot is still swept by axe in both themes at three
   widths (WO-22, WO-27), measured for reflow and work-surface floor (WO-21),
   and rendered as a Storybook story with an a11y run (WO-06, `04` §5.3). What
   is missing for them is *pixel* comparison specifically — a class of
   regression that is real but narrow: spacing, colour and typography drift
   inside a component, which the token tests
   (`web/tests/tokens.test.ts` forbids literal colours outside
   `app/tokens.css`) already constrain from the other side.
4. **Chromium-only and `darwin`-only are the same argument, one level down.**
   A snapshot's artefact *is* the engine's rasterisation: text hinting,
   form-control metrics and scrollbar geometry differ between Chromium, Gecko
   and WebKit, and between macOS and Linux. Committing three engines × two
   platforms would be six sets of bytes that go stale independently and
   disagree for reasons that are never product defects. The platform is a
   directory segment (`e2e/__screenshots__/{platform}/`) rather than a silent
   assumption, so a second platform is *additive* and never a conflict; the
   engine limit is `@visual` in `CHROMIUM_ONLY` in
   [`web/playwright.config.ts`](../../../../web/playwright.config.ts).

### The tolerance, stated rather than buried

The comparison runs at Playwright's default per-pixel `threshold` (0.2) with
`maxDiffPixels: 200`. That is not a comfort margin: 45 of the 48 snapshots are
**byte-identical** between two forced regenerations, and the only render that
ever moved is `thread-populated` at 1440, by 124 (dark) / 131 (light) pixels,
bimodally, because the briefing's `position: sticky` `SectionRail` lays out at a
fractional x offset and is rasterised snapped or unsnapped depending on
compositor layer promotion. The reasoning, the measurements and the rejected
fixes are on `MAX_DIFF_PIXELS` in `visual.spec.ts`. For scale: a deliberate 2 px
shift moves **1,441 to 13,703** pixels, so the tolerance is between 7× and 68×
below the smallest regression the gate exists to catch.

### What would change this decision

Any one of these, and the depth should be revisited rather than defended:

- **The product stops being single-deployment.** Per-tenant theming (MT-01)
  turns "one deployment renders one way" into a false premise, and the visual
  tier would have to grow a theme axis before the first tenant ships.
- **A visual regression reaches a user in a state the suite does not cover.**
  One is an argument for adding that state; two in the same area is an argument
  for the full matrix.
- **The token layer stops being the only place values live.** The narrowness
  above leans on `web/tests/tokens.test.ts` — if literal colours or spacings
  start appearing in components, pixel comparison becomes the only check left.
- **CI gains a Linux visual leg.** That is additive under
  `e2e/__screenshots__/linux/` and costs a second set of bytes; it is worth it
  only once someone actually reviews the Linux diffs. Wiring is
  [`web/e2e/README.md`](../../../../web/e2e/README.md), "Regenerating".

### Evidence

| What | Where |
|---|---|
| The suite | [`web/e2e/visual.spec.ts`](../../../../web/e2e/visual.spec.ts) |
| The committed set | `web/e2e/__screenshots__/darwin/` — 48 PNGs |
| Determinism measures and the regeneration rule | [`web/e2e/README.md`](../../../../web/e2e/README.md), "Visual regression (WO-28)" |
| Engine and platform pinning | [`web/playwright.config.ts`](../../../../web/playwright.config.ts) — `CHROMIUM_ONLY`, `snapshotPathTemplate` |
| The 2 px demonstration | WO-28's PR body |
