/**
 * WO-W13 criterion 3, second half — "the at-cap and judge-unassessed states
 * render the honest copy (snapshot tests on the copy module)".
 *
 * WHY A SNAPSHOT AND NOT A `toContain`. These sentences are the whole of
 * what the product says when it has nothing good to report: the cap bound,
 * or the judge produced nothing. A substring assertion would go on passing
 * through a rewrite that quietly turned "no assessment was recorded" into an
 * apology or a provisional grade. An inline snapshot puts the exact wording
 * in the diff, where a reviewer reads it as prose.
 *
 * `tests/copy/forbidden.test.ts` already walks `lib/copy/learn` for
 * 03 §5.5's deny-list, so the mastery/percentage prohibition is gated
 * globally and is not restated here. What is added below is the `(learn)`
 * lexicon check (Path / Session / Ledger, never "dashboard"), because that
 * list is this route group's and WO-W14 owns the shared pedagogy section.
 */

import { describe, expect, it } from "vitest";

import { LEARN } from "@/lib/copy/learn";

describe("guided-session honesty copy", () => {
  it("pins cost and assessment facts without mastery language", () => {
    expect({
      costCapRefused: LEARN.costCapRefused,
      costCapDegraded: LEARN.costCapDegraded,
      unassessed: LEARN.unassessedBody,
      ungraded: LEARN.recordedUngraded,
      complete: LEARN.completeAdvance,
    }).toMatchInlineSnapshot(`
      {
        "complete": "This session advanced one guided reading and preserved your own explain-back as evidence.",
        "costCapDegraded": "The session closed with a bounded fallback instead of spending beyond its limit.",
        "costCapRefused": "The next model call was refused before spending beyond this session’s limit.",
        "unassessed": "This is an explicit missing assessment, not a grade or a claim of mastery.",
        "ungraded": "Your explain-back was saved as evidence. It has not been turned into a grade.",
      }
    `);
  });

  it("pins the headings those two states are announced under", () => {
    // The heading is what a screen reader reaches first and what the story's
    // axe run finds. A body sentence that stayed honest under a heading that
    // did not would still mislead.
    expect({
      atCap: LEARN.costCapHeading,
      unassessed: LEARN.unassessedHeading,
      complete: LEARN.completeHeading,
      stopped: LEARN.failedHeading,
    }).toMatchInlineSnapshot(`
      {
        "atCap": "Session cost limit reached",
        "complete": "Session complete",
        "stopped": "The session stopped",
        "unassessed": "No assessment was recorded",
      }
    `);
  });

  it("says what a working turn does NOT know, rather than estimating it", () => {
    expect({
      workingHeading: LEARN.workingHeading,
      workingBody: LEARN.workingBody,
      reconnecting: LEARN.reconnecting,
      resumed: LEARN.resumed,
      transcriptUnavailable: LEARN.transcriptUnavailable,
    }).toMatchInlineSnapshot(`
      {
        "reconnecting": "Connection interrupted. The browser is reattaching to the same session.",
        "resumed": "Session restored from its durable checkpoint.",
        "transcriptUnavailable": "The session is available, but its saved reading margin could not be loaded. Nothing has been reconstructed from stream events.",
        "workingBody": "No percentage or completion estimate is shown. The next observed checkpoint will appear when the service publishes it.",
        "workingHeading": "The tutor is preparing the next prompt",
      }
    `);
  });

  it("keeps the (learn) lexicon: Path / Session / Ledger, never dashboard", () => {
    // Word-boundary matched: a substring search would also fire on unrelated
    // prose, and a gate that cries wolf is a gate that gets relaxed.
    const banned = /\b(dashboards?|mastered|mastery)\b/i;
    const offenders = Object.entries(LEARN)
      // `unassessedBody` says "a claim of mastery" — it is the sentence that
      // REFUSES the claim, which is exactly the copy this rule wants.
      .filter(([key, value]) => key !== "unassessedBody" && banned.test(value))
      .map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it("shows no progress percentage anywhere in the session surface", () => {
    // Not a deny-list of words but of SHAPES: any digit followed by a
    // percent sign, and any "N of M" progress claim.
    const shapes = [/\d\s*%/, /\b\d+\s+of\s+\d+\b/i];
    for (const [key, value] of Object.entries(LEARN)) {
      for (const shape of shapes) {
        expect(`${key}: ${shape.test(value)}`).toBe(`${key}: false`);
      }
    }
  });
});
