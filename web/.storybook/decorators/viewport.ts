/**
 * WO-06 acceptance criterion 1 (viewport), RC-14.
 *
 * 04-ARCHITECTURE.md section 5.2 proposed 320 / 412 / 768 / 1440.
 * 03-DESIGN-BRIEF.md section 7.5 makes 1024 a layout-mode boundary, so
 * nothing sampled 1024-1279 -- the "rail expanded, no section rail" mode
 * had no story. RC-14 resolves the set to five widths, and this is it.
 *
 * Widths are literals here, and deliberately so. Storybook applies these
 * as inline `width`/`height` on the preview iframe from the MANAGER
 * document, which never loads app/tokens.css -- a `var(--layout-breakpoint-lg)`
 * would resolve to nothing there. The three that coincide with tokens are
 * annotated below and web/tests/storybook.test.ts pins the whole set
 * against RC-14's list, so the numbers cannot drift unnoticed.
 *
 * Heights are the conventional device heights for each class. They are not
 * a reconciliation output and nothing is gated on them; they exist because
 * Storybook's Viewport type requires both dimensions.
 *
 * No initial viewport is pinned. Storybook's "responsive" default lets a
 * story fill the canvas, which is what a primitive wants; the five RC-14
 * modes are one toolbar click away on every story, with no per-story
 * wiring, which is what criterion 1 asks for.
 */

import type { Viewport } from "storybook/viewport";

export const VIEWPORTS = {
  "w320": {
    name: "320 — narrow phone",
    styles: { width: "320px", height: "568px" },
    type: "mobile",
  },
  "w412": {
    name: "412 — phone (the mobile repair target)",
    styles: { width: "412px", height: "915px" },
    type: "mobile",
  },
  "w768": {
    name: "768 — tablet (--layout-breakpoint-md)",
    styles: { width: "768px", height: "1024px" },
    type: "tablet",
  },
  "w1024": {
    name: "1024 — rail expanded, no section rail (--layout-breakpoint-lg)",
    styles: { width: "1024px", height: "768px" },
    type: "desktop",
  },
  "w1440": {
    name: "1440 — desktop (the baseline axe window)",
    styles: { width: "1440px", height: "900px" },
    type: "desktop",
  },
} as const satisfies Record<string, Viewport>;

export type ViewportKey = keyof typeof VIEWPORTS;

/** RC-14's five widths, in order, as plain numbers for the test to pin. */
export const RC14_WIDTHS = [320, 412, 768, 1024, 1440] as const;
