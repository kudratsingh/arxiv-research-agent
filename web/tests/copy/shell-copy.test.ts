/**
 * WO-08's copy, held to WO-12's gate.
 *
 * `web/lib/copy/shell.ts` is a fourth surface file in WO-12's dictionary,
 * added by WO-08 under 06-WORK-ORDERS.md §5.6's one-file-per-surface rule so
 * that two concurrent work orders did not have to edit one module. A new
 * file in that directory is only safe if it is gated like the rest of it, so
 * this file re-uses WO-12's own exported machinery —
 * `collectCopyStrings`, `findForbidden`, `DENY_LIST`, `LEXICON_PHRASES` —
 * rather than restating any pattern. Nothing in
 * `web/tests/copy/forbidden.test.ts` is touched; if that gate's list grows,
 * this one grows with it automatically, because both read the same exports.
 *
 * It also pins the two claims WO-08's own criteria make about copy:
 *
 *   - criterion 9: the header carries 03 §6's workspace indicator, and the
 *     shell composes it from `WORKSPACE` rather than from a second copy of
 *     the sentence.
 *   - the shell renders no ownership language at all (seam S6), which is the
 *     half of D-009 that copy can break without rendering a single control.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  DENY_LIST,
  LEXICON_PHRASES,
  collectCopyStrings,
  findForbidden,
} from "@/lib/copy";
import * as shellCopy from "@/lib/copy/shell";
import { WORKSPACE } from "@/lib/copy/threads";
import { WORKSPACE_INDICATOR } from "@/components/app/WorkbenchShell";

const WEB_ROOT = path.resolve(__dirname, "..", "..");

const { strings, functions } = collectCopyStrings(shellCopy, "shell");

describe("web/lib/copy/shell.ts is inside WO-12's gate", () => {
  it("exports strings the walker can actually reach", () => {
    expect(strings.length).toBeGreaterThan(0);
    for (const entry of strings) {
      expect(entry.value.trim(), `${entry.path} is empty`).not.toBe("");
    }
  });

  it("exports no function, so there is no composed form to enumerate", () => {
    // The moment this file grows a composer, it owes the same
    // drive-every-function treatment forbidden.test.ts gives run.ts. Failing
    // here is how that obligation is noticed.
    expect(functions).toEqual([]);
  });

  it.each(strings.map((entry) => [entry.path, entry.value]))(
    "%s carries no forbidden phrase",
    (path_, value) => {
      expect(findForbidden(value, DENY_LIST), `${path_}: ${value}`).toEqual([]);
    },
  );

  it.each(strings.map((entry) => [entry.path, entry.value]))(
    "%s uses the RC-12 lexicon",
    (path_, value) => {
      expect(findForbidden(value, LEXICON_PHRASES), `${path_}: ${value}`).toEqual([]);
    },
  );
});

describe("criterion 9 — the workspace indicator comes from the dictionary", () => {
  it("is composed from WORKSPACE, not restated in the shell", () => {
    expect(WORKSPACE_INDICATOR).toContain(WORKSPACE.indicator);
    expect(WORKSPACE_INDICATOR).toContain(WORKSPACE.indicatorDetail);
  });

  it("says what 03 §6 says: the workspace is shared and there are no accounts", () => {
    expect(WORKSPACE_INDICATOR).toMatch(/^Shared workspace/);
    expect(WORKSPACE_INDICATOR).toMatch(/everyone with access to this deployment/i);
    expect(WORKSPACE_INDICATOR).toMatch(/no separate accounts/i);
  });

  it("carries no ownership language (seam S6)", () => {
    expect(findForbidden(WORKSPACE_INDICATOR, DENY_LIST)).toEqual([]);
  });
});

describe("the shell's own modules write no user-facing sentence of their own", () => {
  const sources = [
    "components/app/WorkbenchShell.tsx",
    "components/patterns/ThemeToggle.tsx",
    "components/features/ThreadDrawer.tsx",
  ];

  it.each(sources)("%s imports its words rather than typing them", (file) => {
    const source = readFileSync(path.join(WEB_ROOT, file), "utf8");
    expect(source).toMatch(/from "@\/lib\/copy\//);
  });

  it.each(sources)("%s contains no ownership phrasing anywhere, comments included", (file) => {
    const source = readFileSync(path.join(WEB_ROOT, file), "utf8");
    // Deliberately over-broad: the whole file, not only its rendered
    // strings. A comment that says "your threads" is a sentence somebody
    // will eventually paste into the UI.
    expect(findForbidden(source, DENY_LIST.filter((entry) => entry.id.startsWith("your") || entry.id.startsWith("my")))).toEqual([]);
  });
});
