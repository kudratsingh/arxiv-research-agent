/**
 * WO-12 criteria 6 and 8 — the `error_type` vocabulary and its disclosure.
 *
 *   6. "The `error_type` map covers all nine values in §8.3; the default
 *      branch renders the generic sentence **and** the raw `error` text — a
 *      test proves an unmapped value is never swallowed."
 *   8. "Raw `error_type` remains visible in diagnostics (RC-16)."
 *
 * RC-16 is the ruling both criteria implement, and it is two claims that
 * have to hold at the same time: the mapped sentence IS the primary
 * message, and the raw string NEVER is — while always remaining one
 * disclosure away. `describeErrorType()` keeps them apart structurally
 * rather than by convention, which is what these tests check: it returns
 * `sentence` and `rawError` as separate fields, so there is no composed
 * string in which the two could have been blended.
 *
 * The producible set is derived from the Python sources by
 * `errorTypeDrift.test.ts`; this file is about what the frontend does with
 * a value once it has one.
 */

import { describe, expect, it } from "vitest";

import {
  ERROR_TYPE_COPY,
  MAPPED_ERROR_TYPES,
  NOT_REPORTED,
  UNMAPPED_ERROR_TYPE_COPY,
  describeErrorType,
  rawErrorEvidence,
} from "@/lib/copy/errors";

/** 03 §8.3's table, transcribed. The mapping is the design, not an impl detail. */
const BRIEF_TABLE: Array<[string, string]> = [
  ["hitl_timeout", "The plan was not reviewed in time, so the run stopped."],
  ["cost_budget_exceeded", "The run reached this workspace's cost limit."],
  ["timeout", "The run took longer than this workspace allows."],
  [
    "orphaned",
    "The run was interrupted by a server restart and could not be resumed safely.",
  ],
  ["NoPapersFoundError", "No matching arXiv papers were found for these queries."],
  ["ArxivUnavailableError", "arXiv could not be reached."],
  ["AllPaperAnalysesFailedError", "Papers were found but none could be read."],
  [
    "SynthesizerOutputError",
    "The briefing could not be assembled from what was read.",
  ],
];

describe("criterion 6 — the nine mapped values", () => {
  it("maps nine values", () => {
    expect(MAPPED_ERROR_TYPES).toHaveLength(9);
  });

  it.each(BRIEF_TABLE)("%s reads exactly as 03 §8.3 wrote it", (value, sentence) => {
    expect(describeErrorType(value).sentence).toBe(sentence);
    expect(describeErrorType(value).mapped).toBe(true);
  });

  it("maps JobCancelledError too, which §8.3 names but does not tabulate", () => {
    // §8.3 lists it among the class names `type(exc).__name__` yields, but
    // gives it no row. Leaving it to the fall-through would print "The run
    // failed." for a run that was stopped on purpose — true of the job
    // record's status, wrong about what happened.
    const described = describeErrorType("JobCancelledError");
    expect(described.mapped).toBe(true);
    expect(described.sentence).not.toBe(UNMAPPED_ERROR_TYPE_COPY.sentence);
    expect(described.sentence).toMatch(/stopped/);
  });

  it("offers a recovery for every mapped value", () => {
    for (const value of MAPPED_ERROR_TYPES) {
      expect(ERROR_TYPE_COPY[value].recovery.length, value).toBeGreaterThan(0);
    }
  });

  it("never puts the raw text in the primary sentence (RC-16)", () => {
    for (const value of MAPPED_ERROR_TYPES) {
      const described = describeErrorType(value, "TypeError: NoneType is not iterable");
      expect(described.sentence).not.toContain("TypeError");
      expect(described.sentence).not.toContain(value);
      // ...and yet the raw text is still right there, one field away.
      expect(described.rawError).toBe("TypeError: NoneType is not iterable");
      expect(described.errorType).toBe(value);
    }
  });
});

describe("criterion 6 — the fall-through is visible, never a swallow", () => {
  const described = describeErrorType(
    "SomeFutureExceptionName",
    "SomeFutureExceptionName: the synthesiser buffer was empty",
  );

  it("uses the generic sentence", () => {
    expect(described.sentence).toBe("The run failed.");
    expect(described.mapped).toBe(false);
  });

  it("keeps the raw error text, unedited, and marks it for display", () => {
    expect(described.rawError).toBe(
      "SomeFutureExceptionName: the synthesiser buffer was empty",
    );
    expect(described.showRawError).toBe(true);
  });

  it("keeps the raw error_type, unedited", () => {
    expect(described.errorType).toBe("SomeFutureExceptionName");
  });

  it("still asks for the raw row when the backend sent no error text", () => {
    // The disclosure appears either way. An unmapped value with an empty
    // `error` is the case a naive `if (error) show()` would swallow
    // completely, leaving four words on screen and nothing to paste.
    const empty = describeErrorType("SomeFutureExceptionName", null);
    expect(empty.showRawError).toBe(true);
    expect(empty.rawError).toBeNull();
    expect(rawErrorEvidence(empty.errorType, empty.rawError)).toEqual([
      { label: "error_type", value: "SomeFutureExceptionName", present: true },
      { label: "error", value: NOT_REPORTED, present: false },
    ]);
  });

  it("treats an absent error_type as absent, not as a value", () => {
    for (const absent of [null, undefined, ""]) {
      const result = describeErrorType(absent, "boom");
      expect(result.errorType).toBeNull();
      expect(result.mapped).toBe(false);
      expect(result.showRawError).toBe(true);
    }
  });
});

describe("criterion 8 — the raw strings stay visible in diagnostics", () => {
  it("labels them with the API's own field names", () => {
    // Deliberate: the reader is about to quote these in an issue, and a
    // translated label would make the quote harder to act on.
    expect(rawErrorEvidence("orphaned", "Job was reclaimed")).toEqual([
      { label: "error_type", value: "orphaned", present: true },
      { label: "error", value: "Job was reclaimed", present: true },
    ]);
  });

  it("keeps the raw error_type even when the value IS mapped", () => {
    // RC-16's second half. A mapped sentence does not replace the string;
    // it precedes it.
    const rows = rawErrorEvidence("hitl_timeout", "pending_review exceeded 900s");
    expect(rows[0]).toEqual({
      label: "error_type",
      value: "hitl_timeout",
      present: true,
    });
    expect(describeErrorType("hitl_timeout").mapped).toBe(true);
  });

  it("says 'not reported' for silence, in both rows", () => {
    expect(rawErrorEvidence(null, null)).toEqual([
      { label: "error_type", value: NOT_REPORTED, present: false },
      { label: "error", value: NOT_REPORTED, present: false },
    ]);
  });

  it("returns both rows always, so the disclosure never changes shape", () => {
    for (const [type, error] of [
      ["orphaned", "x"],
      ["orphaned", null],
      [null, "x"],
      [null, null],
    ] as Array<[string | null, string | null]>) {
      expect(rawErrorEvidence(type, error)).toHaveLength(2);
    }
  });
});
