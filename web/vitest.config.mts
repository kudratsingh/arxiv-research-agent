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
      //
      // WO-07 re-seeded all four again, measured on the tree rebased onto
      // WO-10 — the union of the primitives, the job machine and the query
      // layer. Neither branch's number was right for that union, so nothing
      // was carried forward. The eleven primitives sit inside the include
      // scope above and land at 100% statements, 100% functions, 100% lines
      // and 97.40% branches over 238 new unit tests, which lifts three of the
      // four columns; branches gains the most ground because a primitive's
      // whole state set is prop-reachable and the tests walk it. 1,275 tests
      // now cover 1148/1232 statements, 724/843 branches, 319/338 functions,
      // 1039/1098 lines. Nothing was lowered, and no exclusion was added to
      // reach these. Previous values, for the audit trail:
      // 92.39 / 82.46 / 93.75 / 94.11.
      // WO-12 re-seeded all four, upward, at 1,439 tests: 1296/1379
      // statements, 872/991 branches, 361/380 functions, 1168/1226 lines.
      // The copy dictionary and StatusBanner arrive fully covered
      // (lib/copy and components/patterns are both 100% statements,
      // functions and lines), so leaving WO-07's numbers would have banked
      // regression allowance nobody earned. Previous values, for the audit
      // trail: 93.18 / 85.88 / 94.37 / 94.62.
      //
      // ONE MEASUREMENT HAZARD, RECORDED FOR WO-13 … WO-19. When a module
      // under `include` is loaded by BOTH projects, the two Vite pipelines
      // produce two different transforms of it, and the merged report
      // unions statements, branches and lines correctly but CONCATENATES
      // the function lists. A module a story imports and only partly
      // exercises therefore has its function denominator doubled while its
      // numerator does not move: an early draft of WO-12's stories
      // imported `@/lib/api` and `@/lib/copy/run` and drove the functions
      // column from 94.7% (unit alone) to 85.08% (both) without changing a
      // line of product code. The fix is not a lower floor — it is for a
      // story to import the modules it actually exercises. WO-12's stories
      // read `lib/copy/errors` only, and take the twelve `ApiFailure`
      // kinds from `FAILURE_COPY`'s keys rather than from `lib/api`.
      //
      // WO-08 re-seeded all four, upward, at 1,570 tests: 1461/1545
      // statements, 955/1079 branches, 442/465 functions, 1300/1355 lines.
      // Previous values, for the audit trail: 93.98 / 87.99 / 95 / 95.26.
      //
      // Two notes a later work order will need.
      //
      // (1) The hazard above bit this branch twice and both fixes were
      // structural, not numeric. `WorkbenchShell` originally defaulted its
      // `rail` prop to `ConversationSidebar`, which pulled `lib/api` into
      // the storybook project and took the functions column from 94.89%
      // (unit alone) to 85.62% (both). The rail is now passed in by
      // `app/(workspace)/layout.tsx` through `ThreadRailBridge`, which is
      // the only module in the shell that reaches the data layer — so the
      // shell's stories load layout and nothing else. The residual cost is
      // `lib/copy/threads.ts`: the shell renders WO-12's `WORKSPACE` and
      // `THREAD_RAIL` strings, so both projects load that module and its
      // two composers report 50%. That is the correct trade — the
      // alternative was a second copy of 03 §6's workspace sentence
      // outside the dictionary's gate.
      //
      // (2) Four functions in this branch can never be covered by the
      // storybook project, and no story should be contorted to try: the
      // `getServerSnapshot` argument of each `useSyncExternalStore` — rail
      // mode, rail collapse, offline, theme preference — runs during
      // hydration only. They are pinned directly in
      // web/tests/shell/wiring.test.tsx instead.
      //
      // THE FUNCTIONS FLOOR WAS RE-SEEDED DOWNWARD — 95.05 → 87.5 — AND IT
      // IS THE ONLY ONE OF THE FOUR THAT MOVED. This is the one re-seed in
      // this file's history that is not a ratchet, so it says why at length.
      //
      // WHAT HAPPENED. The Gate 3 evidence pack's criterion 1 failed on
      // three RC-10 modules with no story: `ThreadTimeline`,
      // `ActiveRunPanel` and `EmptyState`
      // (docs/revamp/evidence/gate-3/storybook-states.md §3). Writing those
      // stories made the Storybook project load `lib/queries/` and
      // `lib/job/` for the first time — a story of a `features/` component
      // that reads the data layer cannot not do that; those modules ARE its
      // import graph. So the MEASUREMENT HAZARD documented above, which had
      // only ever nipped at this file in single modules, fired across the
      // whole data layer at once: a module under `include` loaded by BOTH
      // projects has its function list CONCATENATED in the merged report,
      // and the newly doubly-instrumented set is `lib/job/machine.ts`
      // (100% → 65.07), `lib/api/client.ts` (100% → 58.82),
      // `lib/api/errors.ts` (95 → 53.84), `lib/queries/keys.ts`
      // (100 → 61.11), plus `lib/diagnostics/ring.ts`, `vitals.ts`,
      // `lib/spine/adapter.ts` and `lib/copy/run.ts`.
      //
      // WHY IT IS STRUCTURAL AND NOT A QUALITY DROP. The denominator grew
      // by 233 and the numerator by 130, so 103 functions joined the
      // denominator that nothing newly failed to cover — the same functions
      // are still covered, counted twice. The other three columns move the
      // other way over the same commit: statements 96.01 → 96.27, lines
      // 96.90 → 97.00, branches 91.14 → 90.98. And the two files the change
      // is about — two of the six lowest-covered in the pack's
      // coverage-summary.md §4 — improve in every column:
      // `ThreadTimeline.tsx` 88.88/71.42/86.66/90.00 → 94.91/78.57/92.30/95.12
      // and `ActiveRunPanel.tsx` 70.58/55.55/57.14/74.19 → 72.22/57.77/61.53/74.19.
      //
      // WHAT IS *NOT* THE FIX. `coverage.exclude` was considered and
      // rejected: hiding `lib/api` or `lib/job` from the report to keep a
      // number would trade a visible artefact for an invisible blind spot.
      // The hazard note above says the remedy is "for a story to import the
      // modules it actually exercises" — these stories do; they have no
      // other graph to import. The PROPER fix is de-duplicating the two
      // projects' function lists in the merged report, which is this
      // config's own problem and not a story branch's; it belongs with
      // WO-31's ratchet, which should raise this floor again once the
      // double count is gone.
      //
      // 87.5 is just under the measured 87.83, the same small headroom the
      // other three carry. Ruled by the coordinator under the standing
      // delegation; to be recorded in DECISIONS.md at Gate 3 close.
      // Previous value, for the audit trail: functions 95.05.
      //
      // ---------------------------------------------------------------
      //
      // WO-31 RE-SEEDED ALL FOUR, UPWARD, ON THE POST-CLEANUP TREE, at
      // 3,013 tests across `unit` and `storybook`: 2460/2520 statements,
      // 1677/1796 branches, 920/1043 functions, 2005/2034 lines. Previous
      // values, for the audit trail: 94.56 / 88.5 / 87.5 / 95.94.
      //
      // MEASURED ON THE TREE REBASED ONTO MAIN AT d3460a7, deliberately and
      // not incidentally. The first measurement was taken on 8f0d738 and
      // read 97.65/93.42/88.2/98.62; `fix/mobile-shell-cls-lcp` then merged
      // as #111, and re-measuring after the rebase cost three of the four
      // columns 0.05 of a point (97.61/93.37/88.2/98.57). That fix carries
      // its evidence in the browser tier — `e2e/cls.spec.ts` and
      // `e2e/reflow.spec.ts` — rather than in vitest, so it adds five
      // statements and two branches to the denominator that the unit
      // projects do not reach. Seeding the pre-rebase numbers would have
      // made this PR's own merge red for a reason that has nothing to do
      // with it.
      //
      // WHY EVERY COLUMN ROSE, WHEN THIS WORK ORDER WROTE ALMOST NO TESTS.
      // It deleted the nine legacy components, `lib/useResearchStream.ts`
      // and the two M0 shims — twelve modules that were inside `include`
      // above and that WO-20 had already stopped composing, so they were
      // carrying their statements, branches and functions in the
      // DENOMINATOR while nothing rendered them. Deleting a module nothing
      // exercises raises the ratio without covering a single new line, and
      // that is exactly what happened: statements 94.56 → 97.61, branches
      // 88.50 → 93.37, lines 95.94 → 98.57.
      //
      // THE FUNCTIONS COLUMN MOVED LEAST — 87.5 → 88.2 — AND THE HAZARD
      // DOCUMENTED ABOVE IS STILL WHY. PR #108's re-seed was caused by the
      // dual-project function-list CONCATENATION, not by uncovered code,
      // and this work order does not fix that: the stories that made
      // `lib/queries/` and `lib/job/` doubly-instrumented are still there
      // and still the right stories. So the denominator is still inflated
      // by the double count, the column still lags the other three by ten
      // points, and the proper fix is still de-duplicating the two
      // projects' function lists in the merged report — which is this
      // config's own problem, is not a deletion, and is not in a removal
      // work order's licence. It stays queued.
      //
      // Three of the four are seeded AT the measurement, to the decimal,
      // per this file's convention. `functions` is seeded at 88.1, just
      // under its measured 88.2 — the same small headroom PR #108 gave it,
      // and for the same reason: it is the one column whose denominator
      // depends on which stories run rather than on what the tests cover.
      //
      // ONE OBSERVED VARIANCE, SO THE NEXT READER DOES NOT "CORRECT" IT.
      // `branches` was measured twice on the same tree and read 93.37 then
      // 93.42; the storybook project's `play` functions do not always walk
      // the same branch set under load. It is seeded at the LOWER of the
      // two. A column seeded at the luckier run is a column that goes red
      // on somebody else's PR for no reason of theirs.
      //
      // ---------------------------------------------------------------
      //
      // WO-W14 RE-SEEDED ALL FOUR, UPWARD, ON THE TREE REBASED ONTO WO-W13
      // (main 4fbe239), at 3,313 tests across `unit` and `storybook`:
      // 2721/2774 statements, 1869/1991 branches, 1040/1173 functions,
      // 2216/2237 lines. Previous values, for the audit trail:
      // 97.61 / 93.37 / 88.1 / 98.57.
      //
      // MEASURED ON THE UNION, NOT ON EITHER BRANCH. WO-W13 measured
      // 98.04 / 93.67 / 88.16 / 99.04 on its own tree and did not re-seed;
      // 05-WEDGE-WORK-ORDERS.md §5.4 gives the re-seed to whichever of the
      // three Phase-W surface PRs merges last, which is this one, and the
      // union is above WO-W13's figure in every column. Seeding either
      // branch's own numbers would have made the other's merge red for a
      // reason that has nothing to do with it — the mistake WO-31's note
      // records about measuring before a rebase rather than after.
      //
      // WHY THEY ROSE. Two surfaces arrived with their tests rather than
      // after them. All four Ledger modules — `lib/copy/ledger.ts`,
      // `components/patterns/LedgerView.tsx`,
      // `components/features/LedgerSurface.tsx` and
      // `app/(learn)/learn/progress/page.tsx` — measure 100 in every column,
      // including the two defensive branches the recorded contract fixture
      // cannot reach (an event with no `path_id`, a timestamp with no date),
      // which are driven from summaries derived from that fixture rather
      // than left uncovered.
      //
      // THE FUNCTIONS HAZARD DOCUMENTED ABOVE DID NOT FIRE ON THIS BRANCH,
      // and that is worth recording because it is the mechanism the hazard
      // note prescribes rather than luck. `LedgerView.stories.tsx` imports
      // `lib/copy/ledger` and the contract fixture and nothing else from
      // `lib/` at runtime — the `LearnerProgressSummary` import is type-only
      // and erased — so no module became newly doubly instrumented.
      // `functions` still lags the other three by ten points for the reason
      // the hazard note gives, and de-duplicating the two projects' function
      // lists is still queued.
      //
      // MEASURED THREE TIMES ON THE REBASED TREE. `statements`, `functions`
      // and `lines` read identically every time (98.08 / 88.66 / 99.06);
      // `branches` read 93.82, 93.87 and 93.82 — WO-31's observed variance,
      // in the same column, for the reason its note gives: the storybook
      // project's `play` functions do not always walk the same branch set.
      // The same variance appeared on this branch before the rebase (93.59,
      // 93.59, 93.64), so it is a property of the suite rather than of one
      // tree. `statements` and `lines` are therefore seeded AT the
      // measurement; `branches` is seeded at 93.8, just under the LOWEST of
      // the three, and `functions` keeps the small headroom this file has
      // given it since PR #108 — 88.6 against a measured 88.66. A column
      // seeded at the luckier run goes red on somebody else's PR for no
      // reason of theirs. Even so both of those floors rise: branches
      // +0.43, functions +0.5.
      //
      // WO-W13b RE-SEEDED ALL FOUR, on the tree that adds the path view's
      // start action REBASED ONTO WO-W17's merge (#149) — the last surface PR
      // of the §5.4 group, which is the one the re-seed belongs to. 3,380
      // tests across 155 files: 2874/2928 statements, 2002/2128 branches,
      // 1058/1191 functions, 2357/2378 lines. Previous values, for the audit
      // trail: 98.08 / 93.8 / 88.6 / 99.06.
      //
      // MEASURED ON THE UNION, NOT ON THIS BRANCH ALONE — the mistake WO-31's
      // note records. On the pre-rebase tree this branch read
      // 98.08 / 93.9 / 88.76 / 99.07; the union with WO-W17 is above that in
      // every column, so seeding this branch's own numbers would have banked
      // an allowance the tree does not need.
      //
      // WHY THEY ROSE. Two sets of code arrived with their tests. The start
      // action: `lib/copy/learn.ts` is 100 in every column (its refusal mapper
      // is driven over every `ApiFailure` kind AND every `detail` code
      // `src/api/sessions.py` raises), `PathView.tsx` is 100/97.67/100/100,
      // `PathDetailSurface.tsx` 96.96/86.66/100/100. And WO-W17's
      // `lib/server/pilot.ts`, whose 623-test suite is what lifts `branches`
      // the furthest.
      //
      // MEASURED THREE TIMES ON THE REBASED TREE, IDENTICAL EVERY TIME
      // (98.15 / 94.07 / 88.83 / 99.11) — the `branches` variance WO-31 and
      // WO-W14 both record did not appear here, but it appeared on this branch
      // BEFORE the rebase (93.9, 93.95, 93.9, 93.95) and is a property of the
      // storybook project's `play` functions rather than of one tree. So
      // `statements` and `lines` are seeded AT the measurement; `branches` at
      // 94.0, which clears the widest run-to-run swing this file has recorded
      // in that column (0.05) rather than the swing this particular set of
      // runs happened to show; and `functions` keeps the small headroom it has
      // carried since PR #108 — 88.8 against a measured 88.83.
      //
      // ONE DISCARDED RUN, RECORDED RATHER THAN AVERAGED IN. A run taken while
      // a Compose stack was building on the same machine failed four stories
      // on 5 s interaction timeouts (`CheckpointLedger/Empty`,
      // `Diagnostics/Expanded`, `Field/Dark`, `Textarea/Disabled`). That is
      // load, not coverage, and its numbers were thrown away.
      thresholds: {
        statements: 98.15,
        branches: 94.0,
        functions: 88.8,
        lines: 99.11,
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
           *
           * WO-07 adds `@radix-ui/*` and `@floating-ui/*` for exactly the
           * same reason and with exactly the same symptom:
           * `@radix-ui/react-dialog`, `@radix-ui/react-dropdown-menu` and
           * the `@floating-ui/react-dom` the menu's popper depends on all
           * import `react`, and when Node resolves that import the
           * `module-alias` registration above sends it to a directory it
           * cannot load. This is the whole of WO-07's edit to this file
           * besides the re-seeded coverage floors; it adds no package to the
           * product and changes nothing about the `unit` project.
           */
          server: {
            deps: {
              inline: [
                /@storybook\//,
                /^storybook$/,
                /vite-plugin-storybook-nextjs/,
                /@radix-ui\//,
                /@floating-ui\//,
              ],
            },
          },
        },
      },
    ],
  },
}));
