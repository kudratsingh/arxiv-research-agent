/**
 * WO-06 — the three self-hosted families, in Storybook.
 *
 * WHY A DECORATOR AND NOT A WRAPPER ELEMENT. app/tokens.css declares each
 * family as a three-layer stack whose first layer is a variable:
 *
 *     --font-ui: var(--font-ui-face), <adjusted stand-in>, <generic stack>;
 *
 * Custom-property substitution happens where the property is DECLARED, not
 * where it is used. `--font-ui` is declared on `:root`, so `var(--font-ui-face)`
 * is resolved against `:root`'s value of `--font-ui-face`. Put the font
 * variables on a wrapper `<div>` and `--font-ui-face` is still undefined at
 * `:root`, which makes the whole `--font-ui` declaration invalid at
 * computed-value time -- every family in the story silently falls back to
 * the UA default. app/layout.tsx avoids this by putting `fontVariables` on
 * `<html>` itself, and this decorator does the same thing to the same
 * element.
 *
 * WHY app/fonts/fonts.ts IS IMPORTED UNCHANGED. `next/font/local` is a
 * build-time transform, not a runtime function -- which is why
 * web/tests/stubs/next-font-local.ts exists for the vitest unit project.
 * Storybook does not need that stub: `@storybook/nextjs-vite` carries
 * `vite-plugin-storybook-nextjs`, which implements the same transform on
 * Vite. It parses the `localFont({...})` call, emits real `@font-face`
 * rules pointing at the committed woff2 files, and returns `variable` as a
 * class that sets the requested custom property. Storybook therefore paints
 * the measured, subset faces WO-02 shipped, and the class names below are
 * the real ones rather than a stand-in's.
 */

import type { Decorator } from "@storybook/nextjs-vite";

import { fontVariables } from "../../app/fonts/fonts";

/** The class list app/layout.tsx puts on <html>. */
export const FONT_VARIABLE_CLASSES = fontVariables.split(" ").filter(Boolean);

export const withFonts: Decorator = (Story) => {
  document.documentElement.classList.add(...FONT_VARIABLE_CLASSES);
  return <Story />;
};
