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

/** The retired pair, and every spelling an import of them can take. */
const RETIRED = {
  "JobSummary.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)JobSummary["']/,
  "ExportDropdown.tsx": /from\s+["'](?:\.\/|@\/components\/|\.\.\/)ExportDropdown["']/,
} as const;

/**
 * The two modules WO-20 stops composing and WO-31 deletes.
 *
 * Enumerated rather than pattern-matched: the point of the list is that it
 * may only ever get shorter.
 */
const DOOMED = ["components/ConversationThread.tsx", "components/ReportView.tsx"];

function importersOf(pattern: RegExp): string[] {
  return SOURCES.filter((file) =>
    pattern.test(readFileSync(path.join(WEB_ROOT, file), "utf8")),
  ).sort();
}

describe("the replacements exist", () => {
  it.each(["components/patterns/MetricsStrip.tsx", "components/patterns/ExportDisclosure.tsx"])(
    "%s is committed",
    (file) => {
      expect(SOURCES).toContain(file);
    },
  );

  it("keeps the retired files on disk — deletion is WO-31's, not this one's", () => {
    // RC-21 and WO-31's equivalence-table criterion both depend on the old
    // modules and their tests still being here to compare against.
    expect(SOURCES).toContain("components/JobSummary.tsx");
    expect(SOURCES).toContain("components/ExportDropdown.tsx");
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

  it("has one importer left per module, so WO-20 has one edit site each", () => {
    // ConversationThread renders both (`:239`, `:308`); ReportView renders
    // the dropdown (`:37`). Three call sites, two files, and both files are
    // on WO-20's list.
    expect(importersOf(RETIRED["JobSummary.tsx"])).toEqual([
      "components/ConversationThread.tsx",
    ]);
    expect(importersOf(RETIRED["ExportDropdown.tsx"])).toEqual(DOOMED);
  });
});
