/**
 * WO-06 acceptance criterion 2 — the axe tag set.
 *
 * The Gate 1 baseline ran axe-core 4.13.0 from Playwright with WCAG 2 A/AA,
 * WCAG 2.1 A/AA, WCAG 2.2 AA and best-practice
 * (docs/revamp/baseline/README.md; every file in docs/revamp/baseline/axe/
 * records the same list under `toolOptions.runOnly.values`). Storybook's
 * per-story axe run uses this identical list so a Storybook result and a
 * baseline result are comparable rule-for-rule rather than merely
 * "both accessible".
 *
 * The order is the baseline's, verbatim. web/tests/storybook.test.ts
 * asserts this array against docs/revamp/baseline/axe/*.json, so a drift in
 * either direction fails the suite.
 */
export const AXE_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
  "best-practice",
] as const;

export type AxeTag = (typeof AXE_TAGS)[number];
