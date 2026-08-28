/**
 * WO-18 criterion 9 — the double-render defect, closed structurally.
 *
 * The browser probe that CONFIRMED the defect is in the PR body: on the
 * legacy terminal path a settled run's briefing appears twice, once as the
 * refetched historical turn and once as the retained current-run detail. Two
 * `.report-prose` blocks, one job id.
 *
 * The committed browser assertion belongs to WO-21's Playwright tier, and
 * the legacy path keeps its defect until WO-20 stops composing
 * `ConversationThread`. What this file pins is the property that makes the
 * recurrence impossible on the new surface: the sequence below IS the
 * reproduced sequence, frame by frame, and at no point does one job id
 * produce two briefings.
 */

import { describe, expect, it } from "vitest";

import {
  selectBriefings,
  type CurrentRun,
  type HistoryTurn,
} from "@/lib/report/briefings";

const JOB = "wo18-terminal-job";

const HISTORY_BEFORE: HistoryTurn[] = [];

const HISTORY_AFTER: HistoryTurn[] = [
  {
    jobId: JOB,
    ordinal: 1,
    question: "How should research agents verify claims?",
    markdown: "# Retrieval-Augmented Verification\n\nPersisted body.",
  },
];

const SETTLED: CurrentRun = {
  jobId: JOB,
  question: "How should research agents verify claims?",
  markdown: "# Retrieval-Augmented Verification\n\nSettled body.",
  failure: null,
};

const jobIds = (turns: HistoryTurn[], current: CurrentRun | null): string[] =>
  selectBriefings(turns, current).map((entry) => entry.jobId);

describe("the reproduced sequence, step by step", () => {
  it("1. attached, nothing settled, history empty — one briefing, the live one", () => {
    const running: CurrentRun = { ...SETTLED, markdown: "" };
    const briefings = selectBriefings(HISTORY_BEFORE, running);

    expect(briefings).toHaveLength(1);
    expect(briefings[0]?.live).toBe(true);
    expect(briefings[0]?.ordinal).toBe(1);
  });

  it("2. terminal frame, GET settled, history NOT yet refetched — still one", () => {
    const briefings = selectBriefings(HISTORY_BEFORE, SETTLED);

    expect(briefings).toHaveLength(1);
    expect(briefings[0]?.markdown).toContain("Settled body.");
  });

  it("3. onDone refetched the thread and it now contains the run — STILL one", () => {
    // This is the exact frame the browser probe caught rendering twice.
    const briefings = selectBriefings(HISTORY_AFTER, SETTLED);

    expect(briefings).toHaveLength(1);
    expect(jobIds(HISTORY_AFTER, SETTLED)).toEqual([JOB]);
    expect(briefings[0]?.live).toBe(true);
    // The reconciling GET is the authority (H9), so its body is the one
    // rendered — but there is only ever one body.
    expect(briefings[0]?.markdown).toContain("Settled body.");
    expect(briefings[0]?.markdown).not.toContain("Persisted body.");
  });

  it("4. the browser leaves the run behind — one briefing, no longer live", () => {
    const briefings = selectBriefings(HISTORY_AFTER, null);

    expect(briefings).toHaveLength(1);
    expect(briefings[0]?.live).toBe(false);
    expect(briefings[0]?.markdown).toContain("Persisted body.");
  });
});

describe("one job id can never produce two briefings", () => {
  const OLDER: HistoryTurn[] = [
    { jobId: "turn-1", ordinal: 1, question: "First?", markdown: "First body." },
    { jobId: "turn-2", ordinal: 2, question: "Second?", markdown: "Second body." },
  ];

  it("holds for every arrangement of history and current run", () => {
    const arrangements: Array<[HistoryTurn[], CurrentRun | null]> = [
      [[], null],
      [[], SETTLED],
      [HISTORY_AFTER, null],
      [HISTORY_AFTER, SETTLED],
      [OLDER, null],
      [OLDER, SETTLED],
      [[...OLDER, ...HISTORY_AFTER], SETTLED],
      [[...HISTORY_AFTER, ...OLDER], SETTLED],
      [OLDER, { ...SETTLED, jobId: "turn-2" }],
      [OLDER, { ...SETTLED, jobId: "turn-1" }],
    ];

    for (const [turns, current] of arrangements) {
      const ids = jobIds(turns, current);
      expect(new Set(ids).size, JSON.stringify(ids)).toBe(ids.length);
    }
  });

  it("updates the matching turn in place rather than appending a second", () => {
    const briefings = selectBriefings(OLDER, { ...SETTLED, jobId: "turn-1" });

    expect(briefings.map((entry) => entry.jobId)).toEqual(["turn-1", "turn-2"]);
    expect(briefings[0]?.live).toBe(true);
    expect(briefings[1]?.live).toBe(false);
    // Position is history's, not the current run's: a run that finished
    // first does not jump to the end of the thread because it is on screen.
    expect(briefings[0]?.ordinal).toBe(1);
  });

  it("appends only when history genuinely does not know the run yet", () => {
    const briefings = selectBriefings(OLDER, SETTLED);

    expect(briefings.map((entry) => entry.jobId)).toEqual(["turn-1", "turn-2", JOB]);
    expect(briefings.at(-1)?.ordinal).toBe(3);
    expect(briefings.at(-1)?.live).toBe(true);
  });
});

describe("what it does not invent", () => {
  it("orders by ordinal, whatever order the response arrived in", () => {
    const shuffled: HistoryTurn[] = [
      { jobId: "c", ordinal: 3, question: "?", markdown: "c" },
      { jobId: "a", ordinal: 1, question: "?", markdown: "a" },
      { jobId: "b", ordinal: 2, question: "?", markdown: "b" },
    ];

    expect(jobIds(shuffled, null)).toEqual(["a", "b", "c"]);
    // The input is not mutated: the caller's cached array is React state.
    expect(shuffled.map((turn) => turn.jobId)).toEqual(["c", "a", "b"]);
  });

  it("never attaches a failure to a historical turn", () => {
    // `ConversationJobSummary` carries no status and no error
    // (`schemas.py:184-191`), so history cannot say a run failed and this
    // module does not guess.
    for (const entry of selectBriefings(HISTORY_AFTER, null)) {
      expect(entry.failure).toBeNull();
    }
  });

  it("carries the current run's failure, unedited, onto the run it belongs to", () => {
    const failed: CurrentRun = {
      ...SETTLED,
      failure: {
        errorType: "verification_incomplete",
        error: "Verification stopped before all claims could be checked.",
      },
    };
    const briefings = selectBriefings(HISTORY_AFTER, failed);

    expect(briefings).toHaveLength(1);
    expect(briefings[0]?.failure).toEqual(failed.failure);
    // H5: the retained body is still there. This is criterion 1's shape,
    // arriving through the selector rather than through a prop by hand.
    expect(briefings[0]?.markdown).toContain("Settled body.");
  });

  it("keeps history's body when the current run has not written one", () => {
    const briefings = selectBriefings(HISTORY_AFTER, { ...SETTLED, markdown: "" });

    expect(briefings).toHaveLength(1);
    expect(briefings[0]?.markdown).toContain("Persisted body.");
    expect(briefings[0]?.live).toBe(true);
  });

  it("keeps history's question when the current run has not got one", () => {
    const briefings = selectBriefings(HISTORY_AFTER, { ...SETTLED, question: "" });

    expect(briefings[0]?.question).toBe(HISTORY_AFTER[0]?.question);
  });
});
