/**
 * WO-06 — Storybook 10 on the Vite builder.
 *
 * 04-ARCHITECTURE.md section 5.2 names the stack: Storybook 10.5.10 with
 * `@storybook/nextjs-vite`, plus `addon-a11y` (axe per story) and the
 * Vitest addon so stories execute as component tests in the same run.
 * The production Next webpack build (`npm run build`) stays authoritative
 * for what ships; Storybook is documentation and a test host.
 *
 * `@storybook/nextjs-vite` matters for one concrete reason beyond
 * convenience: it carries `vite-plugin-storybook-nextjs`, which implements
 * `next/font/local` for real -- it reads the woff2 files in app/fonts/,
 * emits the @font-face rules and hands back the same `variable` class
 * names next/font would. Storybook therefore renders the three self-hosted
 * families WO-02 shipped rather than a fallback approximation, and
 * app/fonts/fonts.ts is imported unchanged (see decorators/fonts.tsx).
 * web/tests/stubs/next-font-local.ts stays the vitest-only stand-in for
 * the unit project, which does not load this config.
 *
 * OUTPUT DIRECTORY. `build-storybook` writes to `build/storybook`, not the
 * conventional `storybook-static`. web/tests/tokens.test.ts walks every
 * .ts/.tsx/.css/.mjs/.js/.svg file under web/ looking for literal colours
 * and skips only node_modules, .next, out, build and .git -- so a static
 * build under any other name turns a local `npm run test` red the moment
 * `npm run build-storybook` has been run. `build/` is already ignored by
 * the repository .gitignore and by eslint.config.mjs's globalIgnores, so
 * routing the bundle there keeps all three tools consistent without
 * touching WO-01's test.
 */

import type { StorybookConfig } from "@storybook/nextjs-vite";

const config: StorybookConfig = {
  // Foundations stories live in components/foundations/ and the WO-07
  // primitives will land beside their components; one glob covers both.
  // Keeping them under components/ also puts them inside `npm run lint`'s
  // scope (`eslint app components lib`), so the no-literal-colour rule
  // holds every story to the token layer.
  stories: ["../components/**/*.stories.@(ts|tsx)"],

  addons: ["@storybook/addon-a11y", "@storybook/addon-vitest"],

  framework: {
    name: "@storybook/nextjs-vite",
    options: {},
  },

  // No build-time or run-time phone-home from a dev tool in this repo.
  core: {
    disableTelemetry: true,
  },
};

export default config;
