/**
 * WO-19's retirement clause, as a ratchet.
 *
 * The work order's scope says it "retires `JobSummary.tsx` and
 * `ExportDropdown.tsx` from the render path (files deleted in WO-31)", and
 * RC-21 says the same thing in more words: what survives is the CONTRACT —
 * five real fields, the `<dl>`, the three formats, the same-origin anchors —
 * not the modules. `MetricsStrip` and `ExportDisclosure` are those
 * contracts' new home.
 *
 * WHAT THIS FILE CAN AND CANNOT ASSERT, STATED PLAINLY. Both legacy modules
 * are reachable today from exactly two places, and both of those are
 * themselves legacy: `ReportView.tsx:37` and `ConversationThread.tsx:239`
 * and `:308`. `ConversationThread` is the whole of `/c/[id]`'s body
 * (`app/(workspace)/c/[id]/page.tsx`), and WO-20 — not this work order —
 * "rewrites `web/app/(workspace)/page.tsx` and
 * `web/app/(workspace)/c/[id]/page.tsx` against the new features. Retires
 * `ConversationThread.tsx` from the render path." So the last DOM these two
 * modules render disappears when WO-20 lands, and the browser tier already
 * schedules it that way: `e2e/support/states.ts` keeps §4 row 23 in
 * `DEFERRED_STATES` naming WO-19's `ExportDisclosure/UnavailableNoReport` as
 * the surface, and `reflow.spec.ts` fails the partition until the row moves
 * into `STATES`.
 *
 * What this work order CAN hold, and what this file holds, is the ratchet:
 * the two doomed modules are confined to the two doomed modules that render
 * them, and nothing built after them may pick either one up again. Without
 * it, "retired" would be a claim about today's imports rather than a
 * property a later PR cannot quietly undo.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
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
 * The retired modules, and every spelling an import of them can take.
 *
 * WO-20 EXTENDED THIS LIST FROM TWO TO SEVEN. The work order's scope is
 * "retires `ConversationThread.tsx` from the render path", and that sentence
 * is only true if everything it was the last render path FOR goes with it:
 * `ConversationThread` rendered `EventLog`, `PlanReview`, `QueryForm`,
 * `JobSummary` and (through `ReportView`) `ExportDropdown`. Their replacements
 * — `Diagnostics`, `PlanEditor`, `QueryComposer`, `MetricsStrip`,
 * `ExportDisclosure`, `ReportReader` — are all merged and all composed by
 * `ThreadTimeline` and `ActiveRunPanel`. Deletion is still WO-31's.
 */
const RETIRED = {
  "JobSummary.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)JobSummary["']/,
  "ExportDropdown.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ExportDropdown["']/,
  "EventLog.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)EventLog["']/,
  "PlanReview.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)PlanReview["']/,
  "QueryForm.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)QueryForm["']/,
  "ReportView.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ReportView["']/,
  "ConversationThread.tsx":
    /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ConversationThread["']/,
} as const;

/**
 * The modules WO-20 stops composing and WO-31 deletes.
 *
 * Enumerated rather than pattern-matched: the point of the list is that it
 * may only ever get shorter. After WO-20 the two entries here are the last
 * two legacy modules with any importer at all, and both of them are
 * themselves on the list — which is the shape "retired from the render path"
 * has when nothing renders it: a closed cycle no route can reach.
 */
const DOOMED = ["components/ConversationThread.tsx", "components/ReportView.tsx"];

/** The route files whose composition WO-20 owns. */
const ROUTES = [
  "app/(workspace)/page.tsx",
  "app/(workspace)/c/[id]/page.tsx",
];

function importersOf(pattern: RegExp): string[] {
  return SOURCES.filter((file) =>
    pattern.test(readFileSync(path.join(WEB_ROOT, file), "utf8")),
  ).sort();
}

describe("the replacements exist", () => {
  it.each([
    "components/patterns/MetricsStrip.tsx",
    "components/patterns/ExportDisclosure.tsx",
    "components/features/ThreadTimeline.tsx",
    "components/features/ActiveRunPanel.tsx",
  ])("%s is committed", (file) => {
    expect(SOURCES).toContain(file);
  });

  it("keeps the retired files on disk — deletion is WO-31's, not this one's", () => {
    // RC-21 and WO-31's equivalence-table criterion both depend on the old
    // modules and their tests still being here to compare against.
    for (const name of Object.keys(RETIRED)) {
      expect(SOURCES).toContain(`components/${name}`);
    }
  });
});

describe("the retired pair is confined to the modules that are themselves retired", () => {
  it.each(Object.entries(RETIRED))("%s is imported only by the doomed modules", (_name, pattern) => {
    const importers = importersOf(pattern);
    for (const importer of importers) {
      expect(DOOMED, `${importer} imports a module WO-31 deletes`).toContain(importer);
    }
  });

  it("is imported by nothing in the new layers", () => {
    const newLayers = SOURCES.filter(
      (file) =>
        file.startsWith("app/") ||
        file.startsWith("components/patterns/") ||
        file.startsWith("components/features/") ||
        file.startsWith("lib/"),
    );

    for (const [name, pattern] of Object.entries(RETIRED)) {
      const offenders = newLayers.filter((file) =>
        pattern.test(readFileSync(path.join(WEB_ROOT, file), "utf8")),
      );
      expect(offenders, `${name} has been picked up again`).toEqual([]);
    }
  });

  it("has one importer left per module, so WO-20 had one edit site each", () => {
    // ConversationThread rendered both (`:239`, `:308`); ReportView rendered
    // the dropdown (`:37`). Three call sites, two files, and both files were
    // on WO-20's list. After the rewrite the only importer of either is a
    // module that is itself retired.
    expect(importersOf(RETIRED["JobSummary.tsx"])).toEqual([
      "components/ConversationThread.tsx",
    ]);
    expect(importersOf(RETIRED["ExportDropdown.tsx"])).toEqual(DOOMED);
  });
});

// ---------------------------------------------------------------------------
// WO-20 — the render path itself.
//
// The ratchet above is about IMPORTS, which is a property of the tree. This
// one is about the two files that decide what a browser actually renders, and
// it is the assertion that makes "retired from the render path" checkable:
// neither route may reach any of the seven legacy modules, directly or
// through one hop.
// ---------------------------------------------------------------------------

describe("WO-20 — no route renders a retired module", () => {
  it.each(ROUTES)("%s imports none of them", (route) => {
    const source = readFileSync(path.join(WEB_ROOT, route), "utf8");
    for (const [name, pattern] of Object.entries(RETIRED)) {
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

  it("leaves ConversationThread with no importer outside the doomed set", () => {
    // The last render path was `app/(workspace)/c/[id]/page.tsx`. Nothing
    // outside the modules WO-31 deletes may import it again.
    expect(importersOf(RETIRED["ConversationThread.tsx"])).toEqual([]);
  });
});
