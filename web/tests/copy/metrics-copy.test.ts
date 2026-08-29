/**
 * WO-19's half of WO-12's forbidden-string gate.
 *
 * `web/tests/copy/forbidden.test.ts` walks `lib/copy/{errors,run,threads}`
 * and is WO-12's committed file, so this work order does not edit it. What
 * it does instead is REUSE its machinery — `collectCopyStrings`,
 * `findForbidden`, `DENY_LIST`, `FORBIDDEN_PHRASES`, `OWNERSHIP_PHRASES` and
 * `LEXICON_PHRASES` are all imported from `@/lib/copy` here — so
 * `lib/copy/metrics.ts` and `lib/copy/exports.ts` are held to exactly the
 * same list rather than to a second copy of it that could drift. The three
 * structural properties WO-12 built into its gate are reproduced:
 *
 *   1. every stored string is walked, recursively;
 *   2. every exported FUNCTION is driven, and the set driven is asserted
 *      equal to the set the walker found — neither module exports one today,
 *      and the assertion is what makes that a fact rather than an assumption;
 *   3. the deny-list is shown to be non-vacuous on this surface's own words.
 *
 * It adds the property `report-copy.test.ts` added for WO-18: the strings
 * these two modules share with `BRIEFING` are asserted character-identical.
 * See the header of `lib/copy/metrics.ts` for why they are declared twice.
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
import { NOT_REPORTED } from "@/lib/copy/errors";
import * as exportCopy from "@/lib/copy/exports";
import * as metricsCopy from "@/lib/copy/metrics";
import { BRIEFING } from "@/lib/copy/run";

const walkedMetrics = collectCopyStrings(metricsCopy, "metrics");
const walkedExport = collectCopyStrings(exportCopy, "exports");

/** Every stored string in both modules. */
const STORED: CopyString[] = [...walkedMetrics.strings, ...walkedExport.strings];

/** Every exported function, by path. */
const FUNCTION_PATHS = [...walkedMetrics.functions, ...walkedExport.functions].sort();

// ---------------------------------------------------------------------------

describe("the gate covers the whole of WO-19's copy", () => {
  it("found both modules' stored strings", () => {
    expect(walkedMetrics.strings.length).toBeGreaterThan(5);
    expect(walkedExport.strings.length).toBeGreaterThan(3);
    for (const entry of STORED) expect(entry.value).not.toBe("");
  });

  /**
   * Neither module composes.
   *
   * A metric's format is not a sentence — `$0.4200` is how a quantity is
   * written — so the formatting lives in `MetricsStrip.tsx` and is driven by
   * `tests/patterns/MetricsStrip.test.tsx`. If a composer ever arrives here,
   * this assertion fails until it is driven above, which is the same
   * structural property WO-12's gate has.
   */
  it("has no exported function that could skip the gate", () => {
    expect(FUNCTION_PATHS).toEqual([]);
  });
});

describe("03 §5.5's forbidden strings", () => {
  it.each(FORBIDDEN_PHRASES)("nothing says $id", (phrase) => {
    const offenders = STORED.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("is the same list WO-12 enforces, not a copy of it", () => {
    expect(DENY_LIST).toEqual([...FORBIDDEN_PHRASES, ...OWNERSHIP_PHRASES]);
    expect(findForbidden("the score is unknown")).toEqual(["unknown"]);
  });
});

describe("seam S6's ownership prohibition", () => {
  it.each(OWNERSHIP_PHRASES)("nothing says $id", (phrase) => {
    const offenders = STORED.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });
});

describe("RC-12 — the lexicon", () => {
  it.each(LEXICON_PHRASES)("no user-facing string says $id", (phrase) => {
    const offenders = STORED.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("uses the lexicon's own nouns for the two concepts this surface names", () => {
    const all = STORED.map((entry) => entry.value).join("\n");
    expect(all).toMatch(/\bruns?\b/i);
    expect(all).toMatch(/\bbriefings?\b/i);
  });

  /**
   * RC-12's risk note, as an assertion.
   *
   * "The filename shown to the user comes from upstream Content-Disposition
   * and cannot follow the lexicon; only the link label is ours." So no
   * string here may name a file: promising `briefing.md` on screen when the
   * browser saves `research-{job_id}.md` would be the lie the note warns
   * about.
   */
  it("names no export filename and no extension", () => {
    const filename = /[\w-]+\.(?:md|pdf|docx|json|txt|csv)\b/i;
    expect(STORED.filter((entry) => filename.test(entry.value))).toEqual([]);
  });
});

describe("the strings shared with WO-12's BRIEFING cannot drift", () => {
  const SHARED_METRICS: ReadonlyArray<
    [keyof typeof metricsCopy.METRICS, keyof typeof BRIEFING]
  > = [
    ["label", "metricsLabel"],
    ["iterationsLabel", "iterationsLabel"],
    ["qualityLabel", "qualityLabel"],
    ["costLabel", "costLabel"],
    ["callsLabel", "callsLabel"],
    ["durationLabel", "durationLabel"],
  ];

  const SHARED_EXPORT: ReadonlyArray<
    [keyof typeof exportCopy.EXPORT, keyof typeof BRIEFING]
  > = [
    ["label", "exportLabel"],
    ["markdown", "exportMarkdown"],
    ["pdf", "exportPdf"],
    ["refused", "exportRefused"],
  ];

  it.each(SHARED_METRICS)("METRICS.%s is character-identical to BRIEFING.%s", (mine, theirs) => {
    expect(metricsCopy.METRICS[mine]).toBe(BRIEFING[theirs]);
  });

  it.each(SHARED_EXPORT)("EXPORT.%s is character-identical to BRIEFING.%s", (mine, theirs) => {
    expect(exportCopy.EXPORT[mine]).toBe(BRIEFING[theirs]);
  });

  it("covers every key the modules have in common", () => {
    // A shared string added to either side without an entry above would
    // escape the equality check; this is what stops that.
    const briefingValues = new Set<string>(Object.values(BRIEFING));

    const sharedMetrics = Object.entries(metricsCopy.METRICS)
      .filter(([, value]) => briefingValues.has(value))
      .map(([key]) => key)
      .sort();
    expect(sharedMetrics).toEqual(SHARED_METRICS.map(([mine]) => mine).sort());

    const sharedExport = Object.entries(exportCopy.EXPORT)
      .filter(([, value]) => briefingValues.has(value))
      .map(([key]) => key)
      .sort();
    expect(sharedExport).toEqual(SHARED_EXPORT.map(([mine]) => mine).sort());
  });

  it("adds the one label WO-12 never wrote", () => {
    // `BRIEFING` names Markdown and PDF and stops, so `word` is new here
    // rather than duplicated — and it must not collide with an existing one.
    expect(Object.values(BRIEFING)).not.toContain(exportCopy.EXPORT.word);
  });
});

describe("criterion 2 — the strings a missing number is made of", () => {
  it("is an em dash, and not a hyphen-minus", () => {
    expect(metricsCopy.METRICS.absent).toBe("—");
    expect(metricsCopy.METRICS.absent).not.toBe("-");
  });

  it("reads it out as the API's silence, not as our ignorance", () => {
    // 03 §5.5: "not reported" describes the response; "unknown" describes us.
    expect(metricsCopy.METRICS.absentReading).toBe(NOT_REPORTED);
    expect(findForbidden(metricsCopy.METRICS.absentReading)).toEqual([]);
  });

  it("explains the symbol in a sentence, which is what a title cannot do", () => {
    expect(metricsCopy.METRICS.absentNote).toMatch(/dash/i);
    expect(findForbidden(metricsCopy.METRICS.absentNote)).toEqual([]);
  });
});

describe("criterion 4 — the 409 sentence", () => {
  it("names the cause rather than the status code", () => {
    expect(exportCopy.EXPORT.refused).not.toMatch(/409|conflict/i);
    // `export_research` refuses on an empty `result` (routes.py:364-368),
    // which is what the sentence says in the product's own nouns.
    expect(exportCopy.EXPORT.refused).toMatch(/briefing/i);
    expect(findForbidden(exportCopy.EXPORT.refused)).toEqual([]);
  });
});
