/**
 * WO-18's half of WO-12's forbidden-string gate.
 *
 * `web/tests/copy/forbidden.test.ts` walks `lib/copy/{errors,run,threads}`
 * and is WO-12's committed file, so this work order does not edit it. What
 * it does instead is REUSE its machinery — `collectCopyStrings`,
 * `findForbidden`, `DENY_LIST`, `FORBIDDEN_PHRASES`, `OWNERSHIP_PHRASES`,
 * `LEXICON_PHRASES` are all imported from `@/lib/copy` here — so
 * `lib/copy/report.ts` is held to exactly the same list rather than to a
 * second copy of it that could drift. The three structural properties WO-12
 * built into its gate are reproduced:
 *
 *   1. every stored string is walked, recursively;
 *   2. every exported FUNCTION is driven, and the set of functions driven is
 *      asserted equal to the set the walker found, so a new composer cannot
 *      quietly skip the gate;
 *   3. the deny-list is shown to be non-vacuous on this module's own words.
 *
 * It adds one property WO-12's file cannot have: the five strings this
 * surface shares with `BRIEFING` are asserted character-identical. See the
 * header of `lib/copy/report.ts` for why they are declared twice — in short,
 * importing `./run` would put eleven functions the Storybook project never
 * calls into a coverage column with no headroom, and `web/vitest.config.mts`
 * is not this work order's file to edit.
 */

import { describe, expect, it } from "vitest";

import {
  DENY_LIST,
  FORBIDDEN_PHRASES,
  LEXICON_PHRASES,
  OWNERSHIP_PHRASES,
  collectCopyStrings,
  findForbidden,
  type CopyString,
} from "@/lib/copy";
import { BRIEFING } from "@/lib/copy/run";
import * as reportCopy from "@/lib/copy/report";

const walked = collectCopyStrings(reportCopy, "report");

/** Every stored string in the module. */
const STORED: CopyString[] = walked.strings;

/** Every exported function, by path. */
const FUNCTION_PATHS = [...walked.functions].sort();

/**
 * The composed strings, driven deliberately — one entry per exported
 * function, including the values that exercise every branch of each.
 */
const COMPOSED: Record<string, string[]> = {
  "report.tableRegionLabel": [0, 1, 2, 7, 1.9, -3].map((ordinal) =>
    reportCopy.tableRegionLabel(ordinal),
  ),
  "report.codeRegionLabel": [0, 1, 2, 7, 1.9, -3].map((ordinal) =>
    reportCopy.codeRegionLabel(ordinal),
  ),
};

const COMPOSED_STRINGS: CopyString[] = Object.entries(COMPOSED).flatMap(
  ([path, values]) => values.map((value) => ({ path, value })),
);

const EVERY_STRING = [...STORED, ...COMPOSED_STRINGS];

// ---------------------------------------------------------------------------

describe("the gate covers the whole of lib/copy/report.ts", () => {
  it("found the module's stored strings", () => {
    expect(STORED.length).toBeGreaterThan(5);
    for (const entry of STORED) expect(entry.value).not.toBe("");
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

  it("is the same list WO-12 enforces, not a copy of it", () => {
    // If `DENY_LIST` ever stops being the union this asserts, the import
    // above is no longer buying anything and this fails rather than drifting.
    expect(DENY_LIST).toEqual([...FORBIDDEN_PHRASES, ...OWNERSHIP_PHRASES]);
    expect(findForbidden("the position is unknown")).toEqual(["unknown"]);
  });
});

describe("seam S6's ownership prohibition", () => {
  it.each(OWNERSHIP_PHRASES)("nothing says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });
});

describe("RC-12 — the lexicon", () => {
  it.each(LEXICON_PHRASES)("no user-facing string says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("uses the lexicon's own nouns for the two concepts this surface names", () => {
    const all = EVERY_STRING.map((entry) => entry.value).join("\n");
    expect(all).toMatch(/\bbriefings?\b/i);
    expect(all).toMatch(/\bruns?\b/i);
  });

  it("promises no export filename (RC-12: those come from upstream)", () => {
    const filename = /[\w-]+\.(?:md|pdf|docx|json|txt|csv)\b/i;
    expect(EVERY_STRING.filter((entry) => filename.test(entry.value))).toEqual([]);
  });
});

describe("the five strings shared with WO-12's BRIEFING cannot drift", () => {
  const SHARED: ReadonlyArray<[keyof typeof reportCopy.REPORT, keyof typeof BRIEFING]> = [
    ["heading", "heading"],
    ["empty", "empty"],
    ["partial", "partial"],
    ["partialDetail", "partialDetail"],
    ["railLabel", "sectionRailLabel"],
  ];

  it.each(SHARED)("REPORT.%s is character-identical to BRIEFING.%s", (mine, theirs) => {
    expect(reportCopy.REPORT[mine]).toBe(BRIEFING[theirs]);
  });

  it("covers every key the two modules have in common", () => {
    // A sixth shared string added to either side without an entry above
    // would escape the equality check; this is what stops that.
    const briefingValues = new Set<string>(Object.values(BRIEFING));
    const shared = Object.entries(reportCopy.REPORT)
      .filter(([, value]) => briefingValues.has(value))
      .map(([key]) => key)
      .sort();
    expect(shared).toEqual(SHARED.map(([mine]) => mine).sort());
  });
});

describe("the strings this surface adds", () => {
  it("does not promise a briefing a failed run will never write", () => {
    expect(reportCopy.REPORT.noBriefing).not.toBe(reportCopy.REPORT.empty);
    expect(reportCopy.REPORT.empty).toMatch(/when the run finishes/);
    expect(reportCopy.REPORT.noBriefing).not.toMatch(/when the run finishes/);
    expect(findForbidden(reportCopy.REPORT.noBriefing)).toEqual([]);
  });

  it("says which of the two a banner over a briefing is, in a word", () => {
    expect(reportCopy.REPORT.partialWord).toBe("Partial");
    expect(findForbidden(reportCopy.REPORT.partialWord)).toEqual([]);
  });

  it("claims no position, fraction or finish time while the pipeline loads", () => {
    const loading = reportCopy.REPORT.loading;
    expect(findForbidden(loading)).toEqual([]);
    expect(loading).not.toMatch(/\d/);
  });

  it("numbers the scroll regions from one, whatever it is handed", () => {
    expect(reportCopy.tableRegionLabel(1)).toBe("Table 1 in this briefing");
    expect(reportCopy.codeRegionLabel(2)).toBe("Code block 2 in this briefing");
    // ScrollRegion throws on an empty name, so an ordinal that fell below 1
    // would be a defect the reader hears rather than one a test catches.
    expect(reportCopy.tableRegionLabel(0)).toBe("Table 1 in this briefing");
    expect(reportCopy.tableRegionLabel(-4)).toBe("Table 1 in this briefing");
    expect(reportCopy.codeRegionLabel(2.9)).toBe("Code block 2 in this briefing");
  });

  it("gives every region a distinct name, which is why they are numbered", () => {
    const names = [1, 2, 3].flatMap((ordinal) => [
      reportCopy.tableRegionLabel(ordinal),
      reportCopy.codeRegionLabel(ordinal),
    ]);
    expect(new Set(names).size).toBe(names.length);
  });
});
