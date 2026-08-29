/**
 * WO-17's copy gate — the plan editor's own half of WO-12's policy.
 *
 * `web/tests/copy/forbidden.test.ts` walks `lib/copy/errors`, `run` and
 * `threads` against a static module list, so a file that arrives a work
 * order later is not covered by it. This file is the same gate over
 * `lib/copy/plan`, built from the SAME exported utilities
 * (`DENY_LIST`, `LEXICON_PHRASES`, `collectCopyStrings`, `findForbidden`) so
 * there is one policy with two call sites rather than two policies:
 *
 *   1. every stored string is checked against 03 §5.5's deny-list and seam
 *      S6's ownership prohibition;
 *   2. every exported FUNCTION is driven and its output checked the same
 *      way, because `overItemLength(1)` is composed rather than stored;
 *   3. the set of functions driven is asserted equal to the set the walker
 *      found, so a new composer fails this file instead of slipping past it;
 *   4. RC-12's lexicon is applied on top;
 *   5. and the one rule that is specific to this surface — D-010 ruling 13,
 *      NO COUNTDOWN — is asserted as the absence of every duration, clock
 *      and deadline form over every string the module can produce.
 *
 * WO-17 criteria 1 and 8 are also pinned here, because both are claims about
 * wording: the two primary labels are 03 §4.6's, and the status line states
 * the two true facts.
 */

import { describe, expect, it } from "vitest";

import {
  DENY_LIST,
  LEXICON_PHRASES,
  collectCopyStrings,
  findForbidden,
  type CopyString,
} from "@/lib/copy";
import * as planCopy from "@/lib/copy/plan";
import { PLAN } from "@/lib/copy/plan";
// `REVIEW` is still the run surface's; `RUN_STATUS_LINE` and
// `RUN_STATUS_WORD` were re-homed to `./trace` by WO-15 and re-exported
// through `./run`. Both are imported from where they are DEFINED, so this
// file names the real counterpart rather than a re-export that could quietly
// start pointing somewhere else.
import { REVIEW } from "@/lib/copy/run";
import { RUN_STATUS_LINE, RUN_STATUS_WORD } from "@/lib/copy/trace";

// ---------------------------------------------------------------------------
// The module, walked.
// ---------------------------------------------------------------------------

const walked = collectCopyStrings(planCopy, "plan");

const STORED: CopyString[] = walked.strings;
const FUNCTION_PATHS = [...walked.functions].sort();

/**
 * Every exported function, driven deliberately.
 *
 * The arguments are the ones a surface really passes: a 1-based row
 * position, the two server bounds, and the boundary cases either side of
 * them. `0` and `-1` are here because `ordinal()` clamps and a clamp that is
 * never exercised is a comment.
 */
const COMPOSED: Record<string, string[]> = {
  "plan.subQuestionLabel": [0, 1, 2, 20].map(planCopy.subQuestionLabel),
  "plan.arxivQueryLabel": [0, 1, 2, 20].map(planCopy.arxivQueryLabel),
  "plan.removeSubQuestion": [-1, 1, 2, 20].map(planCopy.removeSubQuestion),
  "plan.removeArxivQuery": [-1, 1, 2, 20].map(planCopy.removeArxivQuery),
  "plan.atItemLimit": [20, 1000].map(planCopy.atItemLimit),
  "plan.overItemLength": [0, 1, 2, 1500].map(planCopy.overItemLength),
};

describe("WO-17 copy gate — coverage", () => {
  it("walks a module with strings in it", () => {
    expect(STORED.length).toBeGreaterThan(10);
  });

  it("drives every exported function, and only functions that exist", () => {
    expect(Object.keys(COMPOSED).sort()).toEqual(FUNCTION_PATHS);
  });

  it("produces a non-empty string from every composer", () => {
    for (const [path, outputs] of Object.entries(COMPOSED)) {
      expect(outputs.length, path).toBeGreaterThan(0);
      for (const output of outputs) {
        expect(typeof output, path).toBe("string");
        expect(output.length, `${path} produced an empty string`).toBeGreaterThan(0);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// The policy itself.
// ---------------------------------------------------------------------------

const EVERY_STRING: { path: string; value: string }[] = [
  ...STORED,
  ...Object.entries(COMPOSED).flatMap(([path, outputs]) =>
    outputs.map((value, index) => ({ path: `${path}(${index})`, value })),
  ),
];

describe("WO-17 copy gate — 03 §5.5 and seam S6", () => {
  it.each(EVERY_STRING)("$path says nothing the contract cannot support", ({ path, value }) => {
    expect(findForbidden(value, DENY_LIST), `${path}: ${value}`).toEqual([]);
  });

  it.each(EVERY_STRING)("$path uses the product's lexicon", ({ path, value }) => {
    expect(findForbidden(value, LEXICON_PHRASES), `${path}: ${value}`).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// D-010 ruling 13 — no countdown, anywhere.
// ---------------------------------------------------------------------------

/**
 * Every shape a deadline could take.
 *
 * `api_hitl_timeout_sec` is server configuration (`src/config.py:354`) and
 * appears in no API field, so the surface cannot know when the pause ends.
 * A countdown, a duration, a clock time or the word "deadline" would all be
 * inventions; this is the list that keeps them out, including the number
 * itself (1800 s / 30 minutes) in case somebody transcribes the default.
 */
const DEADLINE_FORMS: { id: string; pattern: RegExp }[] = [
  { id: "countdown", pattern: /\bcountdown\b/i },
  { id: "deadline", pattern: /\bdeadline\b/i },
  { id: "expires", pattern: /\bexpir(?:e|es|ing|ed|y)\b/i },
  { id: "minutes", pattern: /\bminutes?\b/i },
  { id: "seconds", pattern: /\bseconds?\b/i },
  { id: "hours", pattern: /\bhours?\b/i },
  { id: "within N", pattern: /\bwithin\s+\d/i },
  { id: "digits and a unit", pattern: /\b\d+\s*(?:s|m|h|sec|min|hr)\b/i },
  { id: "clock time", pattern: /\b\d{1,2}:\d{2}\b/i },
  { id: "the configured default", pattern: /\b1800\b|\bthirty\b/i },
];

describe("WO-17 criterion 8 / D-010 ruling 13 — no countdown", () => {
  it.each(EVERY_STRING)("$path names no duration or deadline", ({ path, value }) => {
    const hit = DEADLINE_FORMS.filter((form) => form.pattern.test(value)).map(
      (form) => form.id,
    );
    expect(hit, `${path}: ${value}`).toEqual([]);
  });

  it("states the two true facts and nothing else about the pause", () => {
    // Fact 1: paused and not spending. Fact 2: it stops on its own.
    expect(PLAN.status).toContain("paused and not spending");
    expect(PLAN.status).toMatch(/stops on its own/);
  });
});

// ---------------------------------------------------------------------------
// The overlap with the run surface, pinned.
//
// `lib/copy/plan.ts` deliberately does not import `lib/copy/run.ts` — see the
// header there: four sentences would drag the whole run dictionary into the
// plan surface's route JavaScript, which is the argument `lib/copy/index.ts`
// already makes about the barrel. What that costs is the risk of drift, and
// this block is what pays it back: every sentence the two surfaces share is
// asserted equal here, so a change to either file that moves one of them
// fails with the sentence named.
// ---------------------------------------------------------------------------

describe("the sentences the plan surface shares with the run surface", () => {
  it("opens the status line with the spine's own pause sentence", () => {
    expect(PLAN.status.startsWith(RUN_STATUS_LINE.awaitingReview)).toBe(true);
    expect(REVIEW.paused).toBe(RUN_STATUS_LINE.awaitingReview);
  });

  it.each([
    ["heading", PLAN.heading, REVIEW.heading],
    ["subQuestionsLabel", PLAN.subQuestionsLabel, REVIEW.subQuestionsLabel],
    ["arxivQueriesLabel", PLAN.arxivQueriesLabel, REVIEW.arxivQueriesLabel],
    ["cancel", PLAN.cancel, REVIEW.cancel],
    ["cancelHint", PLAN.cancelHint, REVIEW.cancelHint],
    ["conflict", PLAN.conflict, REVIEW.conflict],
    ["conflictRecovery", PLAN.conflictRecovery, REVIEW.conflictRecovery],
  ])("%s matches REVIEW's", (_name, mine, theirs) => {
    expect(mine).toBe(theirs);
  });

  it("uses the run vocabulary's own word for the pause", () => {
    expect(PLAN.statusWord).toBe(RUN_STATUS_WORD.pendingReview);
  });
});

// ---------------------------------------------------------------------------
// The wordings WO-17 names by hand.
// ---------------------------------------------------------------------------

describe("WO-17 criterion 1 — one control, two labels", () => {
  it("uses 03 §4.6's exact labels", () => {
    expect(PLAN.approve).toBe("Approve plan");
    expect(PLAN.revise).toBe("Save edits and approve");
  });

  it("keeps them distinct, so the relabel is visible", () => {
    expect(PLAN.approve).not.toBe(PLAN.revise);
  });
});

describe("WO-17 criterion 2 — cancel carries its consequence", () => {
  it("says nothing will be searched", () => {
    expect(PLAN.cancelConsequence).toMatch(/nothing will be searched/i);
  });

  it("keeps the one-chance hint: the review pause is the only stop", () => {
    expect(PLAN.cancelHint).toMatch(/only way to stop this run/i);
  });
});

describe("WO-17 criterion 6 — a 200 does not claim resumption", () => {
  /**
   * The words a surface would use if it believed the 200 meant the run had
   * restarted. `ReviewResponse.status` is always `pending_review`
   * (`schemas.py:141-160`), so every one of them would be a lie.
   */
  const RESUMPTION_CLAIMS = [
    /\bresumed\b/i,
    /\bresuming\b/i,
    /\bnow running\b/i,
    /\bhas started\b/i,
    /\bunderway\b/i,
    /\bapproved and running\b/i,
    /\bsearching now\b/i,
  ];

  it.each(RESUMPTION_CLAIMS)("the resolving line does not match %s", (pattern) => {
    expect(PLAN.resolving).not.toMatch(pattern);
  });

  it("says only that the decision was sent and that nothing has moved", () => {
    expect(PLAN.resolving).toMatch(/^Sent/);
    expect(PLAN.resolving).toMatch(/updates when the next event or read arrives/);
  });
});

describe("WO-17 criterion 9 — 03 §7.2's accessible names", () => {
  it("produces the brief's own example verbatim", () => {
    // 03 §7.2: "the plan editor's remove buttons keep a stable accessible
    // name (`Remove sub-question 2`)".
    expect(planCopy.removeSubQuestion(2)).toBe("Remove sub-question 2");
  });

  it("names the other column the way the API spells the service", () => {
    expect(planCopy.removeArxivQuery(2)).toBe("Remove arXiv query 2");
    expect(planCopy.arxivQueryLabel(1)).toBe("arXiv query 1");
  });
});

describe("D-010 ruling 8 — the aria-describedby fallback is load-bearing", () => {
  it("says the arXiv strings go to arXiv verbatim", () => {
    expect(PLAN.arxivQueriesHint).toMatch(/\barXiv\b/);
    expect(PLAN.arxivQueriesHint).toMatch(/verbatim/i);
  });

  it("says the sub-questions are the user's own prose", () => {
    // The other half of the distinction the typeface carries: if the
    // two-family decision ever falls, these two sentences are all that is
    // left of it, so both have to state their side.
    expect(PLAN.subQuestionsHint).toMatch(/rewrite/i);
    expect(PLAN.subQuestionsHint).toMatch(/no search is made from them/i);
  });
});
