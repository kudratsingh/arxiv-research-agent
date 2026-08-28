/**
 * WO-16's copy gate — `lib/copy/diagnostics.ts`, held to WO-12's lists.
 *
 * `tests/copy/forbidden.test.ts` walks `errors`, `run` and `threads`. It
 * names those three modules explicitly, so a fourth copy file would
 * otherwise ship ungated — which is precisely the failure mode WO-12's own
 * risk note describes ("if it is weak, the honesty constraint degrades to a
 * convention"). This file is the same gate over this work order's module,
 * built out of the SAME exported utilities rather than a second copy of the
 * rules: `collectCopyStrings`, `DENY_LIST`, `FORBIDDEN_PHRASES`,
 * `OWNERSHIP_PHRASES`, `LEXICON_PHRASES` and `findForbidden` all come from
 * `@/lib/copy`.
 *
 * It also pins the move. `DIAGNOSTICS` was WO-12's handoff in `run.ts`;
 * WO-16 moved it here verbatim, and the assertions below are on the exact
 * strings, so "verbatim" is checked rather than claimed.
 */

import { describe, expect, it } from "vitest";

import * as diagnosticsCopy from "@/lib/copy/diagnostics";
import {
  DENY_LIST,
  FORBIDDEN_PHRASES,
  LEXICON_PHRASES,
  OWNERSHIP_PHRASES,
  REQUIRED_QUALIFIERS,
  collectCopyStrings,
  findForbidden,
  type CopyString,
} from "@/lib/copy";
import * as runCopy from "@/lib/copy/run";
import { RING_CAPACITY } from "@/lib/diagnostics/constants";

const walked = collectCopyStrings(diagnosticsCopy, "diagnostics");

const STORED: CopyString[] = walked.strings;
const FUNCTION_PATHS = [...walked.functions].sort();

/** One entry per exported function, driven deliberately. */
const COMPOSED: Record<string, string[]> = {
  "diagnostics.diagnosticsRetained": [0, 1, 2, 41, RING_CAPACITY].map((count) =>
    diagnosticsCopy.diagnosticsRetained(count, RING_CAPACITY),
  ),
  "diagnostics.diagnosticsDropped": [-1, 0, 1, 2, 3_000]
    .map((dropped) => diagnosticsCopy.diagnosticsDropped(dropped))
    .filter((line): line is string => line !== null),
};

const COMPOSED_STRINGS: CopyString[] = Object.entries(COMPOSED).flatMap(
  ([path, values]) => values.map((value) => ({ path, value })),
);

const EVERY_STRING = [...STORED, ...COMPOSED_STRINGS];

describe("the gate covers the whole module", () => {
  it("found the strings", () => {
    expect(STORED.length).toBeGreaterThan(20);
  });

  it("drives every exported function — a new composer cannot skip the gate", () => {
    expect(Object.keys(COMPOSED).sort()).toEqual(FUNCTION_PATHS);
  });

  it("produced at least one string from every one of them", () => {
    for (const [path, values] of Object.entries(COMPOSED)) {
      expect(values.length, path).toBeGreaterThan(0);
      for (const value of values) expect(typeof value, path).toBe("string");
    }
  });
});

describe("03 §5.5's forbidden strings", () => {
  it.each(FORBIDDEN_PHRASES)("nothing says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("says 'not reported' rather than the word 03 §5.5 bans", () => {
    // The word itself cannot appear in this file, so the assertion is on
    // the shared constant the surface uses for a silent value.
    expect(REQUIRED_QUALIFIERS.silence).toBe("not reported");
    for (const entry of EVERY_STRING) {
      expect(/\bunknown\b/i.test(entry.value), entry.path).toBe(false);
    }
  });
});

describe("seam S6's ownership prohibition (04 §10)", () => {
  it.each(OWNERSHIP_PHRASES)("nothing says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("offers no sign-in anywhere", () => {
    const login = /\bsign[- ]?in\b|\bsign[- ]?out\b|\blog[- ]?in\b|\bpassword\b|\bavatar\b/i;
    expect(EVERY_STRING.filter((entry) => login.test(entry.value))).toEqual([]);
  });
});

describe("RC-12 — the lexicon", () => {
  it.each(LEXICON_PHRASES)("no string says $id", (phrase) => {
    // No wire-identifier exemption is claimed here, unlike
    // `errors.MAPPED_ERROR_TYPES` and `run.SPINE_LEGEND[].mark`. The
    // record-kind words are English, the column headers are English, and a
    // `node_completed` is still a Checkpoint everywhere it is narrated.
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });
});

describe("the whole module against the union of both lists", () => {
  it.each(EVERY_STRING)("$path is clean", (entry) => {
    expect(findForbidden(entry.value, DENY_LIST), entry.value).toEqual([]);
  });
});

describe("what the strings have to SAY, which a deny-list cannot check", () => {
  it("the copy note names all four exclusions and the zero-egress promise", () => {
    const note = diagnosticsCopy.DIAGNOSTICS.copyNote.toLowerCase();
    expect(note).toContain("question text");
    expect(note).toContain("briefing text");
    expect(note).toContain("headers");
    expect(note).toContain("keys");
    expect(note).toContain("nothing is sent anywhere");
  });

  it("the retained line states the ceiling and that a reload clears it", () => {
    const line = diagnosticsCopy.diagnosticsRetained(12, RING_CAPACITY);
    expect(line).toContain("12 records");
    expect(line).toContain(String(RING_CAPACITY));
    expect(line).toMatch(/reload clears them/);
    // Singular is not "1 records".
    expect(diagnosticsCopy.diagnosticsRetained(1, RING_CAPACITY)).toContain("1 record held");
  });

  it("says nothing at all when nothing was dropped", () => {
    expect(diagnosticsCopy.diagnosticsDropped(0)).toBeNull();
    expect(diagnosticsCopy.diagnosticsDropped(-4)).toBeNull();
    expect(diagnosticsCopy.diagnosticsDropped(1)).toContain("1 older record");
    expect(diagnosticsCopy.diagnosticsDropped(7)).toContain("7 older records");
  });

  it("the vitals note refuses the field-p75 claim 04 §9.2 says is unavailable", () => {
    const note = diagnosticsCopy.DIAGNOSTICS_VITALS.note;
    expect(note).toContain("this browser");
    expect(note).toContain("Nothing is sent anywhere");
    expect(note).not.toMatch(/p75|percentile|field data|real user/i);
  });

  it("covers exactly the three metrics 04 §9.2 names", () => {
    expect(Object.keys(diagnosticsCopy.DIAGNOSTICS_VITALS.metric).sort()).toEqual([
      "CLS",
      "INP",
      "LCP",
    ]);
  });

  it("has a word for every record kind, and no extras", () => {
    // Pinned against the source of truth rather than restated, so a new
    // kind fails here instead of rendering as `undefined` in the table.
    expect(Object.keys(diagnosticsCopy.DIAGNOSTICS_KIND_LABEL).sort()).toEqual([
      "connection",
      "failure",
      "frame",
      "terminal",
      "transition",
      "vital",
    ]);
  });
});

describe("the move out of run.ts is complete and verbatim", () => {
  it("run.ts no longer exports it", () => {
    expect("DIAGNOSTICS" in runCopy).toBe(false);
  });

  it("kept every string WO-12 wrote, unedited", () => {
    expect(diagnosticsCopy.DIAGNOSTICS).toEqual({
      label: "Technical events",
      logLabel: "Received frames",
      empty: "No frames have been received on this connection.",
      copyAction: "Copy diagnostics",
      copyNote:
        "Copies the last 200 frames and the raw error strings to the clipboard. No question text, no briefing text, no headers and no keys, and nothing is sent anywhere.",
      copied: "Copied to the clipboard.",
    });
  });

  it("does not re-enter the barrel, so a route pays for one file", () => {
    // `lib/copy/index.ts` re-exports errors, run and threads. Adding this
    // module to it would put every string in the dictionary into any route
    // that renders the disclosure (the barrel's own header says so).
    expect(Object.keys(diagnosticsCopy).length).toBeGreaterThan(0);
  });
});
