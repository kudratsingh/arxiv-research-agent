// The run half of the copy dictionary (WO-12 criteria 1, 2, 3).
//
// Everything a user reads about a *run* — the landing question, the trace
// spine's status line, the checkpoint ledger, the terminal phrase, the
// metrics strip — is a string in this file. That is the whole point: the
// honesty rules of 04 §9.1 are rules about sentences, and a sentence rule
// that lives in the component that renders it can only be enforced by
// remembering it.
//
// THREE THINGS ARE STRUCTURAL HERE, NOT STYLISTIC (03 §5.5):
//
//   - "on this connection" appears wherever a checkpoint COUNT appears,
//     because the count is a property of the open EventSource and not of
//     the run. There is no replay backlog (`routes.py:444-454`), so a
//     count without that qualifier is a claim about the run that nothing
//     in the contract supports.
//   - "observed" appears wherever a checkpoint is NAMED, because
//     `node_completed` fires after a node returns (`runner.py:952-956`)
//     and there is no `node_started`. A named node is a thing that
//     finished while we were watching — never a thing that is happening.
//   - "not reported" replaces "unknown" everywhere, because silence is
//     the API's behaviour rather than a gap in our knowledge of it.
//
// `web/tests/copy/forbidden.test.ts` proves all three over every key in
// this file and over every string its functions can compose.

import { NOT_REPORTED } from "./errors";
import { RUN_STATUS_LINE, checkpointCount, lastUpdated } from "./trace";

// ---------------------------------------------------------------------------
// The trace half, re-exported (WO-15). THE THIRD MOVE OUT OF THIS FILE, AND
// THE SAME REASON AS THE OTHER TWO.
//
// 03 §3.4's status words, §5.3's legend and segments, §5.4's status lines,
// `UNAVAILABLE_COPY` and the four checkpoint composers now live in
// `./trace.ts`, byte-identical and under the same names — the trace spine's
// surface, in the trace spine's file, exactly as WO-13 moved §1.4 to
// `./composer.ts` and WO-16 moved `DIAGNOSTICS` to `./diagnostics.ts`.
//
// RE-EXPORTED, unlike `DIAGNOSTICS` and like the landing block, because
// `web/tests/copy/forbidden.test.ts` DRIVES five of these as functions
// (`run.checkpointCount`, `run.checkpointName`, `run.observedCheckpoint`,
// `run.lastUpdated`, `run.failedStatusLine`) and asserts that the set it
// drives EQUALS the set its walk of this namespace finds. This module's
// export set is therefore unchanged: `@/lib/copy`, `@/lib/copy/run` and
// `lib/job/machine.ts` all still see every name where they saw it before.
//
// The measurement, in this work order's own numbers: before the split, a
// spine story importing one string from here put all eleven of this file's
// functions into the Storybook project while exercising four.
// `lib/copy/run.ts` fell from 100% to 68.18% functions and took the global
// floor from 95.00% to 93.72% with no product code changed. Same hazard,
// same page of `vitest.config.mts`, third file to hit it.
// ---------------------------------------------------------------------------

export * from "./trace";

// ---------------------------------------------------------------------------
// Landing (03 §1.4, verbatim). RE-HOMED TO `./composer` BY WO-13.
//
// The four names below were defined here by WO-12 because there was no
// composer file yet; this barrel's own layout rule is "one file per surface
// … so WO-13 … WO-19 add their own file", and 03 §1.4 IS the composer's
// surface. They moved for one measurable reason: `lib/copy/run.ts` is also
// the trace spine's and the metrics strip's dictionary, and a story that
// renders the composer would drag all eleven of its functions into the
// Storybook Vitest project while exercising three — the merged-coverage
// hazard `vitest.config.mts` records for WO-13 … WO-19, which cost eight
// function-coverage points when measured.
//
// They are re-exported rather than relocated-and-forgotten, so every
// existing consumer — `@/lib/copy`, `@/lib/copy/run`, and
// `web/tests/copy/forbidden.test.ts`'s walk of this module's namespace —
// keeps seeing them at exactly the paths it saw them at before.
// ---------------------------------------------------------------------------

export {
  LANDING,
  MAX_QUERY_LEN,
  queryCounter,
  queryOverLimit,
} from "./composer";

// ---------------------------------------------------------------------------
// The composed run lines that are NOT the spine's (03 §5.4, §4.8).
//
// `runningStatusLine` is the whole of §5.4's running row as one string. The
// trace spine does not render it: 03 §5.7 allows the live region to
// announce material transitions and "never individual checkpoints", so the
// spine splits the line and announces only "Running" — see
// `lib/copy/spine.ts`. This composed form stays here because it is the
// canonical §5.4 sentence and WO-16's diagnostics and WO-19's summary read
// it whole.
// ---------------------------------------------------------------------------

/**
 * "Running · 3 checkpoints observed on this connection · updated 41s ago"
 * (03 §5.4).
 *
 * No percentage, no denominator, no ETA and no current node — none of
 * those exist in any frame (H4). What is here is a status, a count of what
 * was seen, and when the last thing was seen.
 */
export function runningStatusLine(
  count: number,
  secondsAgo?: number | null,
): string {
  const updated = lastUpdated(secondsAgo);
  const parts = ["Running", checkpointCount(count)];
  if (updated !== null) parts.push(updated);
  return parts.join(" · ");
}

/** The settled-and-succeeded line: only values `GET /research/{id}` gave us. */
export function completedStatusLine(parts: {
  elapsedSec?: number | null;
  qualityScore?: number | null;
  costUsd?: number | null;
  llmCalls?: number | null;
}): string {
  const segments: string[] = [
    parts.elapsedSec === null || parts.elapsedSec === undefined
      ? `Complete · duration ${NOT_REPORTED}`
      : `Complete in ${parts.elapsedSec.toFixed(1)} s`,
  ];
  if (parts.qualityScore !== null && parts.qualityScore !== undefined) {
    segments.push(`quality ${parts.qualityScore.toFixed(2)}`);
  }
  if (parts.costUsd !== null && parts.costUsd !== undefined) {
    segments.push(`$${parts.costUsd.toFixed(4)}`);
  }
  if (parts.llmCalls !== null && parts.llmCalls !== undefined) {
    segments.push(`${parts.llmCalls} call${parts.llmCalls === 1 ? "" : "s"}`);
  }
  return segments.join(" · ");
}

// ---------------------------------------------------------------------------
// The terminal phrase (H3). RE-HOMED FROM `web/lib/job/machine.ts`.
// ---------------------------------------------------------------------------

/**
 * The five phrases a finished run can be described with, and no others.
 *
 * `machine.ts`'s `terminalPhrase()` selects between these from state; the
 * words themselves are here so that the allow-list
 * (`/^failed( after [^\s]+)?$/`) is testable against the dictionary rather
 * than only against one reducer's output.
 */
export const TERMINAL_PHRASE = {
  /** The run aged out, or never belonged to this principal (H8). */
  unavailable: "no longer available",
  /** `POST /research` itself failed: no run was created (H6, H7). */
  notStarted: "not started",
  succeeded: "complete",
  cancelled: "cancelled",
  /** A terminal frame arrived and the reconciling read failed (H9). */
  finished: "finished",
} as const;

/**
 * "failed", or "failed after <checkpoint>". Nothing else, ever.
 *
 * The node is appended verbatim and is never introduced by a preposition
 * that implies causation. `after` is a claim about ORDER — this is the
 * last thing that was seen to complete — which is exactly what the
 * contract supports and no more.
 */
export function failedPhrase(node: string | null | undefined): string {
  if (typeof node !== "string" || node === "") return "failed";
  return `failed after ${node}`;
}

// ---------------------------------------------------------------------------
// Plan review (03 §4.6) and the review pause.
// ---------------------------------------------------------------------------

/**
 * The review surface.
 *
 * `cancelHint` carries the one fact that makes cancelling a real choice:
 * the review pause is the only cancellation point in the whole lifecycle
 * (there is no general cancel endpoint), so a user who approves is
 * committing to the run.
 */
export const REVIEW = {
  heading: "Plan",
  subQuestionsLabel: "Sub-questions",
  arxivQueriesLabel: "arXiv queries",
  approve: "Approve and run",
  revise: "Save changes and run",
  cancel: "Cancel this run",
  paused: RUN_STATUS_LINE.awaitingReview,
  cancelHint:
    "Cancelling here is the only way to stop this run. Once it is approved there is no way to stop it.",
  conflict:
    "This plan was already resolved somewhere else, so this page is out of date.",
  conflictRecovery: "Reload to see where the run actually got to.",
} as const;

// ---------------------------------------------------------------------------
// Briefing, metrics and export (03 §4.7, §4.8, §8.1).
// ---------------------------------------------------------------------------

/**
 * The briefing surface.
 *
 * `partial` is D-010 ruling 2 and H5: a failed run whose `result` survived
 * shows the briefing, labelled, with export still available — the backend
 * refuses an export only on an empty `result` (`routes.py:364-368`), and
 * the user has already paid for the work.
 *
 * RC-12: the frontend renames the export LINK LABELS only. The filenames
 * come from `Content-Disposition` upstream (`src/api/routes.py:385`) and
 * pass through the proxy allowlist untouched.
 */
export const BRIEFING = {
  heading: "Briefing",
  empty: "No briefing yet. One is written when the run finishes.",
  partial: "Partial briefing from a run that failed.",
  partialDetail:
    "This is what the run had written when it stopped. It is kept because it was already paid for.",
  sectionRailLabel: "Sections",
  exportLabel: "Export",
  exportMarkdown: "Markdown",
  exportPdf: "PDF",
  exportRefused: "There is nothing to export yet: this run produced no briefing.",
  metricsLabel: "Run metrics",
  costLabel: "Cost",
  qualityLabel: "Quality score",
  callsLabel: "LLM calls",
  iterationsLabel: "Iterations",
  durationLabel: "Duration",
} as const;

// ---------------------------------------------------------------------------
// Diagnostics (04 §9.2) — MOVED to `lib/copy/diagnostics.ts` by WO-16.
//
// WO-12 wrote `DIAGNOSTICS` here as a handoff, before WO-16's own copy file
// existed. It now lives in that file, verbatim and unedited, for two
// reasons:
//
//   1. 06-WORK-ORDERS.md §5.6's file-ownership table gives each surface
//      work order one copy file, so the surface that renders a string and
//      the file that holds it stay together.
//   2. It is what keeps `components/patterns/Diagnostics.tsx` from pulling
//      this module into the Storybook project's graph. vitest.config.mts
//      records the consequence in full: a module loaded by BOTH vitest
//      projects has its function list CONCATENATED in the merged coverage
//      report, and `run.ts`'s ten composers are driven by
//      `tests/copy/forbidden.test.ts` in the unit project and by nothing at
//      all in the storybook one. The measured cost of the static import was
//      ten uncovered functions.
//
// Nothing else moved, and no wording changed.
// ---------------------------------------------------------------------------
