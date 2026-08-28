/**
 * The Tailwind class that selects each family, keyed by token name.
 *
 * WHY A CLASS AND NOT `style={{ fontFamily }}`. WO-02's rule is that no
 * file outside app/tokens.css may name or set a family: components reach
 * the three ramps through the `font-ui` / `font-report` / `font-mono`
 * utilities, and web/tests/fonts.test.ts scans every file under web/ to
 * prove it. The utilities are built from web/lib/tokens.ts's `font` object
 * by tailwind.config.ts, so a class and a custom property cannot disagree
 * -- which makes this map a lookup over the same token names the rest of
 * the foundations stories iterate, not a second source of truth.
 *
 * The keys are checked against `FontToken` by the `satisfies` clause, so
 * adding a family to the token layer without adding it here is a type
 * error rather than a silently unstyled specimen.
 */

import type { FontToken } from "../../lib/tokens";

export const FAMILY_CLASS = {
  ui: "font-ui",
  report: "font-report",
  mono: "font-mono",
} as const satisfies Record<FontToken, string>;
