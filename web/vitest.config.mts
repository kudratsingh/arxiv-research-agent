import storybookTest from "@storybook/addon-vitest/vitest-plugin";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vitest/config";

/**
 * Two projects, one `vitest run` (WO-06 acceptance criterion 3).
 *
 * `unit` is the suite WO-05 left behind, moved verbatim into a named
 * project: same jsdom environment, same `vitest.setup.ts` (Testing Library
 * cleanup, FakeEventSource uninstall, theme-attribute reset), same
 * `next/font/local` stub, same `@` alias. Nothing about it changed except
 * that its file glob is now explicit, so the storybook project's
 * `*.stories.tsx` files can never be collected twice.
 *
 * `storybook` is the Storybook/Vitest addon. It reads .storybook/main.ts,
 * applies the framework's Vite plugins (which is how `next/font/local`
 * resolves for real rather than through the stub) and compiles every story
 * into a test that renders it with the global decorators and then runs axe
 * over the result. `css: true` is not decoration: the theme decorator's
 * whole claim is that `data-theme` drives app/tokens.css, and a project
 * that stubs CSS out would test that claim against an empty stylesheet.
 *
 * It has no `setupFiles`. Since Storybook 10.3 the addon provisions the
 * preview annotations itself -- .storybook/preview.tsx's decorators,
 * globals and parameters, plus every addon's own annotations -- and it
 * prints an explicit notice telling you to delete a setup file that calls
 * `setProjectAnnotations` by hand. So there is no hand-written bridge here
 * to drift from the browser preview: the same preview module configures
 * both. It also does not need `vitest.setup.ts`: the theme decorator
 * rewrites `data-theme` on every render, so there is nothing for
 * `clearTestTheme` to reset between stories, and no story installs an
 * EventSource.
 *
 * Coverage stays a single root-level configuration -- Vitest merges
 * coverage across projects and only honours the option at the root -- so
 * WO-05's include list, exclusions and seeded thresholds govern the
 * combined tree exactly as they governed the single project.
 */
export default defineConfig(async () => ({
  test: {
    coverage: {
      provider: "v8",
      // `text-summary` is the line `npm run test -- --coverage` prints;
      // `json-summary` is the machine-readable copy CI reads to ratchet the
      // thresholds below (05-MIGRATION.md C10, WO-31).
      reporter: ["text", "text-summary", "json-summary"],
      reportsDirectory: "./coverage",
      // Only shipped code counts. The test harness, the config files and the
      // build scripts are not the thing the thresholds are protecting.
      include: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
      exclude: [
        // Generated from `contract/openapi.json`; `npm run contract:check` is
        // what guards it, and a `.d.ts` has no statements to cover anyway.
        "lib/api/generated/**",
        // WO-06. Stories are harness, not shipped code: they document the
        // token layer and host the axe run, and nothing in the product
        // imports them. The first pattern covers WO-07's stories, which
        // will sit beside the primitives they document; the second covers
        // the foundations pages, whose helper module
        // (components/foundations/families.ts) is story-only too.
        "**/*.stories.{ts,tsx}",
        "components/foundations/**",
      ],
      // SEEDED AT THE MEASURED VALUE, to the decimal, on purpose.
      //
      // 06-WORK-ORDERS.md WO-05 risk note: "a threshold set aspirationally is
      // a threshold that gets skipped". These four numbers are exactly what
      // 456 tests cover as of this commit (re-measured after the rebase onto
      // WO-02's merge) — 533/605 statements, 306/403 branches, 117/135
      // functions, 493/556 lines — so the gate is "do not regress" and
      // nothing else. Raising them is WO-31's ratchet, not a number anyone
      // should edit to make a red run go green.
      //
      // WO-06 re-measured after splitting the run into two projects, and the
      // four numbers did not move — the counts above still hold at 510 tests
      // across `unit` and `storybook`. Two reasons, both worth recording: the
      // exclusions above keep every story out of the include scope, and the
      // three modules the Storybook preview newly loads — lib/tokens.ts,
      // app/fonts/fonts.ts and app/layout.tsx — were already at 100% from the
      // unit project, so the second project adds execution but no new
      // covered line.
      //
      // WO-11 RE-SEEDED all four, upward, at 583 tests: 668/739 statements,
      // 369/469 branches, 174/191 functions, 615/676 lines. The floor rose
      // because the query layer arrived with its tests — lib/queries is
      // 99.18/94.82/100/100 — so leaving the old numbers in place would have
      // banked a regression allowance nobody earned. Previous values, for the
      // audit trail: 88.09 / 75.93 / 86.66 / 88.66.
      //
      // WO-10 re-seeded them again, on the tree rebased onto WO-11, at 942
      // tests: 1020/1104 statements, 536/650 branches, 285/304 functions,
      // 944/1003 lines. The floor rose for the same reason it rose for WO-11:
      // `lib/job/` arrived with its own tests — the reducer's transition table
      // alone is 250 cases, and `lib/job` measures 93.92/87.24/97.43/97.13 —
      // and `lib/useResearchStream.ts` became a thin adapter over it. Leaving
      // WO-11's numbers would have banked ~2 points of regression allowance
      // nobody earned. Previous values, for the audit trail:
      // 90.39 / 78.67 / 91.09 / 90.97.
      thresholds: {
        statements: 92.39,
        branches: 82.46,
        functions: 93.75,
        lines: 94.11,
      },
    },
    projects: [
      {
        plugins: [react()],
        test: {
          name: "unit",
          environment: "jsdom",
          globals: true,
          setupFiles: ["./vitest.setup.ts"],
          css: false,
          include: ["tests/**/*.test.{ts,tsx}"],
        },
        resolve: {
          alias: {
            // `import.meta.dirname` rather than `__dirname`: Vite's
            // `configLoader: 'native'` cannot evaluate `__dirname` in an ESM
            // config and warns on every run (05-MIGRATION.md B2). Node 22
            // (`package.json` engines) has had `import.meta.dirname` since
            // 20.11.
            //
            // WO-02: `next/font/local` is a build-time transform, not a runtime
            // module, so every test that reaches app/layout.tsx needs a stand-in.
            // See tests/stubs/next-font-local.ts.
            "next/font/local": path.resolve(
              import.meta.dirname,
              "tests/stubs/next-font-local.ts",
            ),
            "@": path.resolve(import.meta.dirname, "."),
          },
        },
      },
      {
        plugins: await storybookTest({ configDir: ".storybook" }),
        test: {
          name: "storybook",
          environment: "jsdom",
          css: true,
          /**
           * Storybook's own packages must go through Vite rather than
           * Node's ESM resolver. The framework's Next mocks register
           * `module-alias` aliases (react -> next/dist/compiled/react) so
           * that Next's own compiled React is used; Node's ESM loader
           * cannot resolve that target, because it is a directory, and an
           * externalised @storybook/react therefore fails to import with
           * "Directory import ... is not supported". Inlined, Vite resolves
           * react itself and the alias never applies.
           */
          server: {
            deps: {
              inline: [/@storybook\//, /^storybook$/, /vite-plugin-storybook-nextjs/],
            },
          },
        },
      },
    ],
  },
}));
