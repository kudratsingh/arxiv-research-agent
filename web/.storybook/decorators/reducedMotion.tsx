/**
 * WO-06 acceptance criterion 1 (reduced motion).
 *
 * `prefers-reduced-motion` is an OS setting behind a media query, so a page
 * cannot enter it from script any more than it can enter forced colours.
 * web/app/tokens.css implements the policy at the token level --
 * `@media (prefers-reduced-motion: reduce)` collapses --duration-fast,
 * --duration-base, --duration-slow and --duration-ambient to 1ms, which is
 * docs/revamp/design/tokens.json motion.reducedMotion.policy item 1 -- and
 * this decorator reproduces that same collapse behind a
 * `data-reduced-motion="reduce"` attribute (see ../preview.css).
 *
 * Because the product's policy lives in the tokens rather than in each
 * component, emulating it at the tokens is a faithful emulation and not an
 * approximation: any component that animates through `var(--duration-*)`
 * -- which is the only sanctioned way -- goes still. A component that
 * hardcodes a duration would keep moving here, and that is a true signal,
 * not a gap in the decorator.
 *
 * A reader whose OS really does prefer reduced motion gets the media query
 * as well; the two mechanisms agree because they set the same variables to
 * the same value.
 */

import type { Decorator } from "@storybook/nextjs-vite";

/** The toolbar global's key. */
export const MOTION_GLOBAL = "motion";

/** The attribute ../preview.css keys off. */
export const REDUCED_MOTION_ATTRIBUTE = "data-reduced-motion";

export const MOTION_OPTIONS = ["no-preference", "reduce"] as const;
export type MotionPreference = (typeof MOTION_OPTIONS)[number];

export const DEFAULT_MOTION: MotionPreference = "no-preference";

const MOTION_TITLES: Record<MotionPreference, string> = {
  "no-preference": "Motion: full",
  reduce: "Motion: reduced",
};

export const motionGlobalType = {
  name: "Motion",
  description: "prefers-reduced-motion, emulated at the duration tokens",
  defaultValue: DEFAULT_MOTION,
  toolbar: {
    title: "Motion",
    // See decorators/theme.tsx for why the literal type is preserved.
    icon: "play" as const,
    dynamicTitle: true,
    items: MOTION_OPTIONS.map((value) => ({ value, title: MOTION_TITLES[value] })),
  },
};

export const withReducedMotion: Decorator = (Story, context) => {
  const motion = (context.globals[MOTION_GLOBAL] ?? DEFAULT_MOTION) as MotionPreference;
  const root = document.documentElement;

  if (motion === "reduce") {
    root.setAttribute(REDUCED_MOTION_ATTRIBUTE, "reduce");
  } else {
    root.removeAttribute(REDUCED_MOTION_ATTRIBUTE);
  }

  return <Story />;
};
