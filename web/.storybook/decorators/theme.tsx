/**
 * WO-06 acceptance criterion 1 (theme) and criterion 5 (forced colours).
 *
 * The product resolves its theme by writing `data-theme` onto the document
 * element before first paint (web/lib/tokens.ts `themeInitScript`, called
 * from web/app/layout.tsx). This decorator writes the SAME attribute to the
 * SAME element, so `:root[data-theme="dark"]` in web/app/tokens.css responds
 * in Storybook exactly as it does in the product -- no parallel theming
 * mechanism, no Storybook-only class, nothing a story can disagree with.
 *
 * `data-theme-preference` is written too, because the product writes both
 * and WO-08's ThemeToggle reads the second one to tell an explicit "light"
 * apart from a "system" that currently resolves to light.
 *
 * FORCED COLOURS is the third option and is an emulation, stated plainly:
 * `forced-colors: active` is a user-agent mode. No page can enter it from
 * script or CSS, and Storybook has no API for it -- only the browser's own
 * OS/DevTools setting does. What a forced-colors UA actually does is
 * substitute the author's colours with a handful of system colours, so the
 * decorator reproduces that substitution at the layer where the product's
 * colours are defined: `data-forced-colors="active"` rebinds every
 * `--color-*` token to the system-colour keyword the UA would supply
 * (see ../preview.css). Nothing else in the story changes.
 *
 * That is exactly the question criterion 5 asks of Foundations/Colour: when
 * twenty-three roles collapse onto Canvas / CanvasText / LinkText /
 * GrayText / Highlight, is the story still readable? It is the same
 * question RC-17 answers for StatusBanner -- severity must carry a distinct
 * word and mark, because the hue is the first thing a reader can lose.
 *
 * A reader who has forced colours switched on for real gets the genuine
 * substitution on top; the emulation is additive, never a mask.
 */

import type { Decorator } from "@storybook/nextjs-vite";

import {
  THEME_ATTRIBUTE,
  THEME_PREFERENCE_ATTRIBUTE,
  type ResolvedTheme,
} from "../../lib/tokens";

/** The toolbar global's key. Stories never set it; the toolbar does. */
export const THEME_GLOBAL = "theme";

/**
 * The attribute the forced-colours emulation keys off. Declared here rather
 * than inline so ../preview.css and web/tests/storybook.test.ts have one
 * name to agree with.
 */
export const FORCED_COLORS_ATTRIBUTE = "data-forced-colors";

export const THEME_OPTIONS = ["light", "dark", "forced-colors"] as const;
export type StorybookTheme = (typeof THEME_OPTIONS)[number];

export const DEFAULT_THEME: StorybookTheme = "light";

const THEME_TITLES: Record<StorybookTheme, string> = {
  light: "Light",
  dark: "Dark",
  "forced-colors": "Forced colours",
};

/**
 * Which of the two real themes a toolbar option resolves to. Forced colours
 * is not a fourth palette: a forced-colors UA overrides whichever theme is
 * underneath, and `ResolvedTheme` has exactly two members by design.
 */
function resolveTheme(theme: StorybookTheme): ResolvedTheme {
  return theme === "dark" ? "dark" : "light";
}

export const themeGlobalType = {
  name: "Theme",
  description: "data-theme on :root, as the product writes it",
  defaultValue: DEFAULT_THEME,
  toolbar: {
    title: "Theme",
    // `as const` keeps the literal type: Storybook's ToolbarConfig accepts
    // only the names in its own icon set, and a widened `string` is not
    // assignable to that union.
    icon: "contrast" as const,
    dynamicTitle: true,
    items: THEME_OPTIONS.map((value) => ({ value, title: THEME_TITLES[value] })),
  },
};

/**
 * Applied synchronously during render rather than from an effect: an effect
 * runs after the story has already painted once, which is the flash the
 * pre-paint script in app/layout.tsx exists to avoid. Writing an attribute
 * is idempotent, so a StrictMode double render costs nothing.
 */
export const withTheme: Decorator = (Story, context) => {
  const theme = (context.globals[THEME_GLOBAL] ?? DEFAULT_THEME) as StorybookTheme;
  const root = document.documentElement;

  root.setAttribute(THEME_ATTRIBUTE, resolveTheme(theme));
  root.setAttribute(THEME_PREFERENCE_ATTRIBUTE, resolveTheme(theme));

  if (theme === "forced-colors") {
    root.setAttribute(FORCED_COLORS_ATTRIBUTE, "active");
  } else {
    root.removeAttribute(FORCED_COLORS_ATTRIBUTE);
  }

  return <Story />;
};
