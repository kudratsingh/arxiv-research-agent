/**
 * WO-06 — the global preview. Every story in the repository inherits this
 * file; no story adds decorators, globals or a11y wiring of its own.
 *
 * WHAT A STORY AUTHOR GETS FOR FREE (criterion 1). Declaring a `meta` and
 * exporting a `StoryObj` is the whole contract. From that alone the story
 * receives:
 *
 *   - the theme toolbar      light / dark / forced-colours, written to
 *                            `data-theme` on :root exactly as the product's
 *                            pre-paint script writes it
 *   - the viewport toolbar   the five RC-14 widths (320 / 412 / 768 / 1024
 *                            / 1440)
 *   - the motion toolbar     prefers-reduced-motion, emulated at the
 *                            duration tokens
 *   - the three self-hosted families, from the real next/font/local objects
 *   - an axe run on the baseline's tag set, failing the story on a violation
 *
 * The stylesheet imports below are the product's own, in the product's own
 * order (app/layout.tsx imports fonts/fallback.css then globals.css, and
 * globals.css imports tokens.css first). Storybook therefore resolves every
 * token through the same cascade the browser does -- there is no Storybook
 * copy of any value.
 */

import type { Preview } from "@storybook/nextjs-vite";

import { AXE_TAGS } from "./axe";
import {
  DEFAULT_MOTION,
  DEFAULT_THEME,
  MOTION_GLOBAL,
  THEME_GLOBAL,
  VIEWPORTS,
  motionGlobalType,
  themeGlobalType,
  withFonts,
  withReducedMotion,
  withTheme,
} from "./decorators";

import "../app/fonts/fallback.css";
import "../app/globals.css";
import "./preview.css";

const preview: Preview = {
  parameters: {
    /**
     * Criterion 2. `options.runOnly` is handed straight to axe.run(), so
     * this is the same `toolOptions.runOnly` shape every file in
     * docs/revamp/baseline/axe/ records -- a Storybook result and a
     * baseline result cover the same rules.
     *
     * `test: "error"` is what turns the axe run into a gate rather than a
     * panel: with the Vitest addon active, a violation fails the story's
     * component test (criterion 3), not merely a tab nobody opened.
     */
    a11y: {
      test: "error",
      options: {
        runOnly: { type: "tag", values: [...AXE_TAGS] },
      },
    },

    /** Criterion 1, viewport. RC-14's five widths; see decorators/viewport.ts. */
    viewport: {
      options: VIEWPORTS,
    },

    /**
     * Storybook's backgrounds toolbar would paint over the canvas the theme
     * decorator is responsible for, giving two controls one job. The theme
     * toolbar is the only thing that changes what a story is painted on.
     */
    backgrounds: { disable: true },

    /**
     * globals.css already puts `bg-canvas` on the preview body, so the story
     * root needs no padding of Storybook's own; each story owns its layout
     * in token space.
     */
    layout: "fullscreen",
  },

  globalTypes: {
    [THEME_GLOBAL]: themeGlobalType,
    [MOTION_GLOBAL]: motionGlobalType,
  },

  initialGlobals: {
    [THEME_GLOBAL]: DEFAULT_THEME,
    [MOTION_GLOBAL]: DEFAULT_MOTION,
    // No viewport is pinned: "responsive" lets a story fill the canvas and
    // the five RC-14 modes stay one click away. See decorators/viewport.ts.
  },

  /**
   * Order is immaterial -- all three write attributes or classes on
   * :root and none of them reads another's output -- but it is listed
   * outermost-first for readability: fonts, then theme, then motion.
   */
  decorators: [withFonts, withTheme, withReducedMotion],
};

export default preview;
