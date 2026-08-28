// The plan-editor half of the copy dictionary (WO-17, 03 §4.6).
//
// WO-12 criterion 1 gives one module per surface behind `lib/copy/`, so the
// plan editor's own sentences live here rather than in `run.ts` — which
// WO-12 owns — and rather than in the component, which the
// `copy/no-inline-text` ESLint rule forbids for `components/patterns/**`.
// `web/tests/copy/plan-copy.test.ts` re-uses WO-12's own gate utilities
// (`DENY_LIST`, `LEXICON_PHRASES`, `collectCopyStrings`) over everything
// exported here, and drives every function, so nothing in this file escapes
// the 03 §5.5 / seam S6 policy just because it arrived a work order later.
//
// WHY THIS FILE DOES NOT IMPORT `lib/copy/run.ts`, EVEN THOUGH `REVIEW`
// THERE SAYS SOME OF THE SAME THINGS. `lib/copy/index.ts` states the cost of
// a copy import plainly: "every string in here is route JavaScript, and a
// barrel import pulls all three files into a route that needed one." The
// same argument applies one level down — importing `run.ts` for four
// sentences would put the whole run dictionary (the spine's status lines,
// the checkpoint composers, the metrics labels) into every route that
// renders the plan editor, which is the surface with the least headroom to
// spend (04 §8.1). WO-12's own layout rule is one file per surface, so this
// one holds the plan surface's strings.
//
// THE OVERLAP IS PINNED, NOT LEFT TO LUCK. Nine of these strings genuinely
// have to be identical to the run surface's, because the spine and the
// editor describe the same pause: `web/tests/copy/plan-copy.test.ts` asserts
// each one equals its `REVIEW` / `RUN_STATUS_*` counterpart, so the two files
// cannot drift without a red test naming which sentence moved.
//
// THE TWO PRIMARY LABELS ARE A DELIBERATE ADDITION. `REVIEW.approve` /
// `REVIEW.revise` ("Approve and run" / "Save changes and run") were authored
// by WO-12 before this surface existed. 03 §4.6 and WO-17 criterion 1 name
// the control's two labels exactly — "Approve plan", relabelling to "Save
// edits and approve" — and criterion 1 is tested on that wording, so the
// button's two strings live here. `REVIEW.approve` and `REVIEW.revise` stay
// where they are for any consumer that describes the action in a sentence
// rather than labelling the control.
//
// NO COUNTDOWN, ANYWHERE (D-010 ruling 13). `api_hitl_timeout_sec` is
// server configuration (`src/config.py:354`) and appears in no API field, so
// the status line states that the run stops on its own and says nothing at
// all about when. `web/tests/copy/plan-copy.test.ts` asserts the absence of
// any duration, clock or deadline form over every string in this file.

// ---------------------------------------------------------------------------
// The surface.
// ---------------------------------------------------------------------------

/**
 * The plan editor, string for string.
 *
 * `status` is WO-17 criterion 8's two true facts, and only those two: the
 * run is paused and not spending, and it stops on its own if it is not
 * reviewed. Its first sentence is word for word `RUN_STATUS_LINE.awaitingReview`
 * — the trace spine describes the same pause — and the gate test asserts
 * that, so the two surfaces cannot drift apart.
 *
 * `subQuestionsHint` and `arxivQueriesHint` are the load-bearing half of
 * D-010 ruling 8. The two-family typography (03 §3.5) carries the
 * prose-versus-literal distinction visually; these two sentences carry it
 * for everybody the typeface cannot reach, and `arxivQueriesHint` is what
 * every arXiv row's `aria-describedby` points at.
 *
 * `resolving` is 04 §4.5's async-settle contract as a sentence. A 200 from
 * `POST /research/{id}/review` does not mean the run resumed —
 * `ReviewResponse.status` is always `pending_review` by design
 * (`schemas.py:141-160`) — so there is no wording here that claims it did.
 */
export const PLAN = {
  heading: "Plan",
  statusWord: "Waiting for your review",
  status:
    "Waiting for your review. The run is paused and not spending. If it is not reviewed, it stops on its own.",
  intro:
    "Nothing has been searched yet. Edit anything below, then approve it to start the arXiv work.",

  subQuestionsLabel: "Sub-questions",
  subQuestionsHint:
    "Your own words. Rewrite these freely — they shape the reading, and no search is made from them.",
  arxivQueriesLabel: "arXiv queries",
  arxivQueriesHint:
    "Each line is sent to arXiv verbatim, exactly as it is written here.",

  approve: "Approve plan",
  revise: "Save edits and approve",
  cancel: "Cancel this run",
  cancelConsequence: "Nothing will be searched.",
  cancelHint:
    "Cancelling here is the only way to stop this run. Once it is approved there is no way to stop it.",

  sending: "Sending your decision…",
  resolving:
    "Sent and waiting. Nothing here has moved yet; this surface updates when the next event or read arrives.",

  emptyPlan:
    "Saved edits need at least one sub-question and at least one arXiv query.",
  noSubQuestions: "No sub-questions. Add one, or cancel the run.",
  noArxivQueries: "No arXiv queries. Add one, or cancel the run.",

  conflict:
    "This plan was already resolved somewhere else, so this page is out of date.",
  conflictRecovery: "Reload to see where the run actually got to.",
  refresh: "Check where the run got to",
} as const;

// ---------------------------------------------------------------------------
// Per-row strings.
//
// Every one of these is a FUNCTION OF THE ROW'S POSITION, and the position
// is 1-based because it is spoken aloud. 03 §7.2 prints the accessible name
// this has to produce — `Remove sub-question 2` — so `removeSubQuestion` is
// the sentence that clause is testable against.
// ---------------------------------------------------------------------------

/** 1-based, and never below 1: a row label is read out, not indexed into. */
function ordinal(position: number): number {
  const n = Math.trunc(position);
  return n < 1 ? 1 : n;
}

/** The visible label on a sub-question row. Never a placeholder (03 §4.6). */
export function subQuestionLabel(position: number): string {
  return `Sub-question ${ordinal(position)}`;
}

/** The visible label on an arXiv query row. */
export function arxivQueryLabel(position: number): string {
  return `arXiv query ${ordinal(position)}`;
}

/** 03 §7.2, verbatim: the remove control keeps a stable accessible name. */
export function removeSubQuestion(position: number): string {
  return `Remove sub-question ${ordinal(position)}`;
}

/** The same rule for the other column. */
export function removeArxivQuery(position: number): string {
  return `Remove arXiv query ${ordinal(position)}`;
}

export const ADD_SUB_QUESTION = "Add sub-question";
export const ADD_ARXIV_QUERY = "Add arXiv query";

// ---------------------------------------------------------------------------
// The bounds, as sentences.
// ---------------------------------------------------------------------------

/** Group thousands without `toLocaleString`, whose output is host-dependent. */
function groupDigits(value: number): string {
  return String(Math.trunc(Math.abs(value))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * The list is at — or past — its cap (`MAX_PLAN_ITEMS`,
 * `src/api/schemas.py:26`).
 *
 * ONE SENTENCE FOR BOTH SIDES OF THE BOUND, deliberately. At the cap it
 * explains why the add control is unavailable; past it — reachable only from
 * a pre-filled working copy, since the add control refuses at the cap — it
 * is the same fact and the same remedy. A second sentence counting the
 * overage would be a second wording of one rule.
 */
export function atItemLimit(limit: number): string {
  return `This list holds ${groupDigits(limit)} entries at most. Remove one to add another.`;
}

/**
 * Over `MAX_PLAN_ITEM_LEN` (`src/api/schemas.py:27`), client-side, before a
 * request is ever made (WO-17 criterion 3).
 *
 * The count is what the user has to act on, so it leads. This is the
 * refusal, not a truncation: the primitive keeps every character the user
 * typed (`Textarea`'s `limit` is not `maxLength`).
 */
export function overItemLength(over: number): string {
  const n = Math.max(0, Math.trunc(over));
  return `${groupDigits(n)} character${n === 1 ? "" : "s"} over the limit. Shorten this entry to send the plan.`;
}
