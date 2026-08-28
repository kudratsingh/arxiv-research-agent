// The component tier's entry point (04-ARCHITECTURE.md §7.1).
//
// Testing Library's `render` mounts into a bare `<div>` attached to
// `document.body`, which means the tree under test inherits whatever
// `<html>` happens to look like. Every token in `web/app/tokens.css` resolves
// off `:root` and its `[data-theme]` override (WO-01), so a component test
// that never sets the attribute is silently asserting against the *light*
// theme only — and would keep passing if the dark values disappeared.
//
// This module is that one line of setup, in one place: `render(ui)` writes
// the theme attributes the pre-paint script writes, and `web/vitest.setup.ts`
// clears them after every test so nothing leaks between files.
//
// It re-exports the rest of Testing Library so a component test has exactly
// one import, and so swapping in a provider later (WO-08's `JobRunProvider`,
// for instance) is a change here rather than in every test file.

import type { ReactElement } from "react";

import {
  render as testingLibraryRender,
  type RenderOptions as TestingLibraryRenderOptions,
  type RenderResult,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  THEME_ATTRIBUTE,
  THEME_PREFERENCE_ATTRIBUTE,
  type ResolvedTheme,
  type ThemePreference,
} from "@/lib/tokens";

export interface RenderOptions extends TestingLibraryRenderOptions {
  /**
   * Resolved theme written onto `<html>`, exactly as `themeInitScript` does
   * before paint. Defaults to `"light"`.
   */
  theme?: ResolvedTheme;
  /**
   * The stored preference the theme was resolved from. Defaults to the
   * resolved theme, so `theme: "dark"` reads as an explicit user choice;
   * pass `"system"` for the media-query path.
   */
  themePreference?: ThemePreference;
}

/** Write the theme attributes the pre-paint script writes. */
export function applyTestTheme(
  theme: ResolvedTheme = "light",
  preference: ThemePreference = theme
): void {
  document.documentElement.setAttribute(THEME_ATTRIBUTE, theme);
  document.documentElement.setAttribute(THEME_PREFERENCE_ATTRIBUTE, preference);
}

/** Remove them again. Called from `web/vitest.setup.ts` after every test. */
export function clearTestTheme(): void {
  document.documentElement.removeAttribute(THEME_ATTRIBUTE);
  document.documentElement.removeAttribute(THEME_PREFERENCE_ATTRIBUTE);
}

/** Testing Library's `render`, with the theme attributes applied first. */
export function render(
  ui: ReactElement,
  options: RenderOptions = {}
): RenderResult {
  const { theme = "light", themePreference, ...rest } = options;
  applyTestTheme(theme, themePreference ?? theme);
  return testingLibraryRender(ui, rest);
}

/**
 * `userEvent.setup()`, so a test does not have to remember that every
 * interaction in this suite is `await`ed.
 */
export function user(): ReturnType<typeof userEvent.setup> {
  return userEvent.setup();
}

export {
  act,
  cleanup,
  fireEvent,
  renderHook,
  screen,
  waitFor,
  waitForElementToBeRemoved,
  within,
  type RenderHookOptions,
  type RenderHookResult,
  type RenderResult,
} from "@testing-library/react";
export { default as userEvent } from "@testing-library/user-event";
