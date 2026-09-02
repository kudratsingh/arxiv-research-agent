/**
 * WO-W14's copy, held to WO-12's gate and pinned where it composes.
 *
 * `forbidden.test.ts` proves that nothing in `lib/copy/ledger.ts` says a
 * banned thing — including, now, a pedagogical one. This file pins the four
 * composers' *semantics*, which a deny-list cannot reach: a date that moves
 * between timezones, a plural that reads as a score, a footnote that
 * appears when there is nothing to footnote.
 *
 * It re-uses the dictionary's own exported machinery rather than restating
 * a pattern, the same way `shell-copy.test.ts` and `plan-copy.test.ts` do.
 */

import { describe, expect, it } from "vitest";

import {
  DENY_LIST,
  LEARN_DENY_LIST,
  LEXICON_PHRASES,
  collectCopyStrings,
  findForbidden,
} from "@/lib/copy";
import * as ledgerCopy from "@/lib/copy/ledger";

const { strings, functions } = collectCopyStrings(ledgerCopy, "ledger");

describe("web/lib/copy/ledger.ts is inside the gate", () => {
  it("exports strings the walker can reach, none of them blank", () => {
    expect(strings.length).toBeGreaterThan(15);
    for (const entry of strings) {
      expect(entry.value.trim(), `${entry.path} is empty`).not.toBe("");
    }
  });

  it("exports exactly the composers forbidden.test.ts drives", () => {
    // A composer with no entry in that file's table fails its coverage
    // assertion. This is the same obligation stated from the other side.
    expect(functions.sort()).toEqual([
      "ledger.assessmentCount",
      "ledger.evidenceKindLabel",
      "ledger.foldedFrom",
      "ledger.recordedOn",
      "ledger.scheduleFigure",
      "ledger.withheldEvidence",
    ]);
  });

  it.each(strings.map((entry) => [entry.path, entry.value]))(
    "%s carries no forbidden phrase, pedagogical or otherwise",
    (path, value) => {
      expect(findForbidden(value, LEARN_DENY_LIST), `${path}: ${value}`).toEqual([]);
      expect(findForbidden(value, LEXICON_PHRASES), `${path}: ${value}`).toEqual([]);
    },
  );
});

describe("the date is sliced, never parsed", () => {
  it("reports the UTC day the event carries", () => {
    expect(ledgerCopy.recordedOn("2026-08-24T09:40:00.000000Z")).toBe(
      "Recorded 2026-08-24",
    );
  });

  it("does not move when the reader's timezone does", () => {
    // The failure this forbids: `new Date(ts).toLocaleDateString()` renders
    // 2026-08-23 for a reader in UTC-5 and 2026-08-24 for one in UTC. A
    // ledger row that changes day depending on who is reading it is not a
    // record. Late and early instants on the same UTC day, both pinned.
    expect(ledgerCopy.recordedOn("2026-08-24T23:59:59.999999Z")).toBe(
      "Recorded 2026-08-24",
    );
    expect(ledgerCopy.recordedOn("2026-08-24T00:00:00.000000Z")).toBe(
      "Recorded 2026-08-24",
    );
  });

  it("renders no date at all rather than inventing one", () => {
    // `null` is the same shape `run.lastUpdated` returns, and for the same
    // reason: there is no sentence to render when there is nothing to say.
    for (const ts of ["", "not-a-timestamp", "24-08-2026"]) {
      expect(ledgerCopy.recordedOn(ts), ts).toBeNull();
    }
    expect(
      findForbidden(ledgerCopy.recordedOn("2026-08-24T00:00:00Z") as string, DENY_LIST),
    ).toEqual([]);
  });
});

describe("the composers say only what the events support", () => {
  it("translates the kinds it knows and neutralises the ones it does not", () => {
    expect(ledgerCopy.evidenceKindLabel("assessment")).toBe("Explain-back recorded");
    expect(ledgerCopy.evidenceKindLabel("artifact_produced")).toBe("Briefing produced");
    // 01 §4.4 reserves the full vocabulary; a kind with no producer must not
    // be described by a surface that has never seen one.
    expect(ledgerCopy.evidenceKindLabel("a_kind_with_no_producer")).toBe(
      ledgerCopy.EVIDENCE_KIND_FALLBACK,
    );
    expect(ledgerCopy.evidenceKindLabel("")).toBe(ledgerCopy.EVIDENCE_KIND_FALLBACK);
  });

  it("welds the schedule label onto the arithmetic, in that order", () => {
    expect(ledgerCopy.scheduleFigure("3 of 3 sessions")).toBe(
      "Schedule · 3 of 3 sessions",
    );
    expect(ledgerCopy.scheduleFigure("0 sessions recorded")).toMatch(
      new RegExp(`^${ledgerCopy.LEDGER.scheduleLabel}`),
    );
    // The backend's own label passes through unedited (01 §4.1's permitted
    // arithmetic); this composer adds a word and changes nothing.
    expect(ledgerCopy.scheduleFigure("1 session recorded")).toContain(
      "1 session recorded",
    );
  });

  it("counts events and never rates them", () => {
    expect(ledgerCopy.assessmentCount(1)).toBe("1 assessment recorded");
    expect(ledgerCopy.assessmentCount(3)).toBe("3 assessments recorded");
    expect(ledgerCopy.foldedFrom(0)).toBe("Folded from no recorded events.");
    expect(ledgerCopy.foldedFrom(1)).toBe("Folded from 1 recorded event.");
    expect(ledgerCopy.foldedFrom(8)).toBe("Folded from 8 recorded events.");
  });

  it("footnotes withheld events, and says nothing when there are none", () => {
    expect(ledgerCopy.withheldEvidence(0)).toBeNull();
    expect(ledgerCopy.withheldEvidence(1)).toContain("1 recorded event is");
    expect(ledgerCopy.withheldEvidence(2)).toContain("2 recorded events are");
  });
});
