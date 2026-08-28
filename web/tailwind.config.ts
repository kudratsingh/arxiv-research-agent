import type { Config } from "tailwindcss";

import {
  color,
  duration,
  ease,
  elevation,
  font,
  layout,
  radius,
  space,
  text,
} from "./lib/tokens";

/**
 * Tailwind is built FROM web/lib/tokens.ts, which is built from
 * web/app/tokens.css, so a utility class and a CSS custom property can
 * never disagree (04-ARCHITECTURE.md section 6.2 item 3). No literal
 * value appears below; every entry resolves to a `var(--...)`.
 *
 * web/tests/tokens.test.ts asserts the mapping in both directions,
 * including the deliberate non-mappings listed at the bottom of this file.
 */

/** Drop a token-family prefix so class names stay idiomatic (`p-4`, not `p-space-4`). */
function strip(
  tokens: Readonly<Record<string, string>>,
  prefix: string,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(tokens).map(([name, value]) => [
      name.startsWith(prefix) ? name.slice(prefix.length) : name,
      value,
    ]),
  );
}

/** Pick a subset of a token family and rename the keys. */
function pick(
  tokens: Readonly<Record<string, string>>,
  mapping: Readonly<Record<string, string>>,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(mapping).map(([from, to]) => [to, tokens[from] as string]),
  );
}

type FontSizeValue = [string, { lineHeight: string; letterSpacing?: string; fontWeight?: string }];

const fontSize: Record<string, FontSizeValue> = Object.fromEntries(
  Object.entries(text).map(([step, facets]) => {
    const options: FontSizeValue[1] = { lineHeight: facets.line };
    if ("tracking" in facets) options.letterSpacing = facets.tracking;
    if ("weight" in facets) options.fontWeight = facets.weight;
    return [step, [facets.size, options] satisfies FontSizeValue];
  }),
);

const config: Config = {
  // Both mechanisms in tokens.css are honoured: the media query is the
  // no-JS fallback for the raw custom properties, and this selector is
  // what makes Tailwind's own `dark:` variant follow the persisted
  // override that the pre-paint script writes.
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: { ...color },

      // The token scale is value-identical to Tailwind's default 4px
      // ramp at every shared key, so overriding these keys changes no
      // existing utility's computed value -- it only reroutes them
      // through the custom properties.
      spacing: {
        ...strip(space, "space-"),
        ...pick(layout, {
          "gutter-narrow": "gutter-narrow",
          "gutter-wide": "gutter-wide",
        }),
      },

      borderRadius: strip(radius, "radius-"),
      boxShadow: { ...elevation },
      fontFamily: {
        ...font,
        // Legacy `font-sans` (the default family for every existing
        // component) resolves to the UI stack rather than a second,
        // divergent system stack. WO-31 removes the alias with the last
        // legacy component.
        sans: font.ui,
      },
      fontSize,
      transitionDuration: strip(duration, "dur-"),
      transitionTimingFunction: strip(ease, "ease-"),

      maxWidth: pick(layout, {
        "content-max": "content",
        "report-measure": "measure",
      }),
      width: pick(layout, {
        "rail-width": "rail",
        "rail-collapsed-width": "rail-collapsed",
      }),
      minWidth: pick(layout, {
        "rail-collapsed-width": "rail-collapsed",
      }),
    },
  },
  plugins: [],
};

export default config;

/**
 * Deliberately NOT mapped into the Tailwind theme, asserted as such by
 * web/tests/tokens.test.ts so the omission stays a decision rather than
 * an oversight:
 *
 * - `--layout-breakpoint-*`. Tailwind's default `md`/`lg`/`xl` already
 *   equal 768/1024/1280px, but its `sm` is 640px against the token's
 *   480px. Overriding `screens` would silently move the one surviving
 *   `sm:` utility in the legacy components. WO-31 removes those; the
 *   breakpoints stay CSS-variable-only until then.
 * - `--size-*`. Hit targets, control heights, icon sizes and the focus
 *   ring are consumed as custom properties by the primitives in WO-07.
 *   Several would collide with a colour utility if mapped by name
 *   (`outline-focus` is already `outline-color: var(--color-focus)`).
 */
