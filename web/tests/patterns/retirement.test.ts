/**
 * WO-19's retirement clause, as a ratchet — now WO-31's deletion, as one.
 *
 * WHAT THIS FILE USED TO SAY, AND WHY IT SAID IT. WO-19 retired
 * `JobSummary.tsx` and `ExportDropdown.tsx` from the render path but could
 * not delete them: `ConversationThread.tsx` was still the whole of
 * `/c/[id]`'s body, so the two modules still had an importer. WO-20 rewrote
 * both routes and extended the list from two modules to seven; the files
 * stayed on disk because RC-03 and WO-31's equivalence-table criterion both
 * needed the old modules and their tests present to compare against
 * (D-012 ruling 2). Until this commit, therefore, the strongest thing that
 * could be asserted was CONFINEMENT: the doomed modules were imported only
 * by doomed modules — a closed cycle no route could reach.
 *
 * WO-31 RETIRED THAT REASON. The equivalence table is in the deletion PR's
 * body, the comparison is made, and the twelve files are gone. So the
 * confinement ratchet is gone with them and this file now holds the
 * property that replaces it, which is strictly stronger and is WO-31
 * acceptance criterion 1 as something a later PR cannot quietly undo:
 *
 *   - none of the twelve files exists;
 *   - nothing under app/, components/ or lib/ imports any of them by any
 *     spelling;
 *   - the replacements they were retired in favour of are all committed;
 *   - and neither route file reaches a retired module.
 *
 * The build and the typecheck prove criterion 1 for the tree as it stands.
 * They cannot prove it for a tree somebody adds `components/EventLog.tsx`
 * back to, because that tree would build. This file can.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { WEB_ROOT } from "../primitives/support/css";

/** Every source file under a directory, recursively. Paths relative to web/. */
function sourceFiles(relativeDir: string): string[] {
  const absolute = path.join(WEB_ROOT, relativeDir);
  const found: string[] = [];

  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
        continue;
      }
      if (/\.(?:ts|tsx)$/.test(entry)) {
        found.push(path.relative(WEB_ROOT, full));
      }
    }
  };

  walk(absolute);
  return found.sort();
}

const SOURCES = [...sourceFiles("app"), ...sourceFiles("components"), ...sourceFiles("lib")];

/**
 * The twelve files WO-31 deleted, and every spelling an import of each can
 * take.
 *
 * Enumerated rather than globbed, and the list may only ever get longer:
 * this is the record of what was removed, so a resurrection has a name.
 *
 * `lib/api.ts` and `lib/types.ts` are the M0 compatibility shims
 * (05-MIGRATION.md §1.1). Deleting `lib/api.ts` does NOT break the ~50
 * `from "@/lib/api"` imports in the tree — the specifier resolves to
 * `lib/api/index.ts`, the real module, which is what the shim only ever
 * re-exported. `@/lib/types` had no consumer outside the nine components,
 * so it resolves to nothing and a resurrected import is a build error.
 */
const DELETED = {
  "components/ConversationsShell.tsx":
    /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ConversationsShell["']/,
  "components/ConversationSidebar.tsx":
    /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ConversationSidebar["']/,
  "components/ConversationThread.tsx":
    /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ConversationThread["']/,
  "components/QueryForm.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)QueryForm["']/,
  "components/EventLog.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)EventLog["']/,
  "components/PlanReview.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)PlanReview["']/,
  "components/JobSummary.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)JobSummary["']/,
  "components/ReportView.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ReportView["']/,
  "components/ExportDropdown.tsx":
    /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ExportDropdown["']/,
  // The leading `/` is load-bearing on both: it matches a module SPECIFIER
  // and not the many prose references to `useResearchStream.ts:59-66` that
  // lib/job/ still carries in its comments — those are the record of where
  // the ported behaviour came from and should survive the module.
  //
  // `lib/types.ts` is matched by its `@/` spelling only. A relative `./types`
  // is how `lib/job/*` imports `lib/job/types.ts`, which is a live module.
  "lib/useResearchStream.ts": /["'][^"']*\/useResearchStream["']/,
  "lib/types.ts": /["']@\/lib\/types["']/,
} as const;

/** The route files whose composition WO-20 owns. */
const ROUTES = ["app/(workspace)/page.tsx", "app/(workspace)/c/[id]/page.tsx"];

/**
 * The modules the twelve were retired in favour of. WO-19's list, extended
 * by WO-20's two features — the same four this file has always named.
 */
const REPLACEMENTS = [
  "components/patterns/MetricsStrip.tsx",
  "components/patterns/ExportDisclosure.tsx",
  "components/features/ThreadTimeline.tsx",
  "components/features/ActiveRunPanel.tsx",
];

function importersOf(pattern: RegExp): string[] {
  return SOURCES.filter((file) =>
    pattern.test(readFileSync(path.join(WEB_ROOT, file), "utf8")),
  ).sort();
}

describe("the replacements exist", () => {
  it.each(REPLACEMENTS)("%s is committed", (file) => {
    expect(SOURCES).toContain(file);
  });
});

describe("WO-31 criterion 1 — the twelve are gone and stay gone", () => {
  it.each([...Object.keys(DELETED), "lib/api.ts"])("%s does not exist", (file) => {
    expect(existsSync(path.join(WEB_ROOT, file))).toBe(false);
  });

  it("leaves no top-level component file behind at all", () => {
    // The nine were the only `.tsx` directly under components/; what is
    // left is the four layer directories 04 §5.1 names, plus foundations.
    const stray = readdirSync(path.join(WEB_ROOT, "components")).filter((entry) =>
      /\.tsx?$/.test(entry),
    );
    expect(stray).toEqual([]);
  });

  it.each(Object.entries(DELETED))("%s is imported by nothing", (name, pattern) => {
    expect(importersOf(pattern), `${name} has been picked up again`).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// WO-20 — the render path itself.
//
// The ratchet above is about IMPORTS, which is a property of the tree. This
// one is about the two files that decide what a browser actually renders,
// and it is the assertion that makes "retired from the render path"
// checkable: neither route may reach any of the retired modules, directly
// or through one hop.
// ---------------------------------------------------------------------------

describe("WO-20 — no route renders a retired module", () => {
  it.each(ROUTES)("%s imports none of them", (route) => {
    const source = readFileSync(path.join(WEB_ROOT, route), "utf8");
    for (const [name, pattern] of Object.entries(DELETED)) {
      expect(pattern.test(source), `${route} still imports ${name}`).toBe(false);
    }
  });

  it("composes the two features the work order creates instead", () => {
    const thread = readFileSync(
      path.join(WEB_ROOT, "app/(workspace)/c/[id]/page.tsx"),
      "utf8",
    );
    expect(thread).toContain("ThreadTimeline");
    expect(thread).toContain("ActiveRunPanel");

    const landing = readFileSync(
      path.join(WEB_ROOT, "app/(workspace)/page.tsx"),
      "utf8",
    );
    expect(landing).toContain("LandingComposer");
  });
});
