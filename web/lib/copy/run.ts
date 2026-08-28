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

// ---------------------------------------------------------------------------
// Landing (03 §1.4, verbatim).
// ---------------------------------------------------------------------------

/** `MAX_QUERY_LEN` on `ResearchRequest` (`src/api/schemas.py:36-40`). */
export const MAX_QUERY_LEN = 8000;

/**
 * The landing surface, string for string as 03 §1.4 prints it.
 *
 * `disclosure` is persistent body copy directly above the button — "not a
 * tooltip, not a footnote, not revealed on hover". It says *billable*
 * because generating a plan is the moment money starts being spent, and
 * `button` says "Generate plan" rather than "Run research" because a
 * planner run that pauses is the action's true immediate effect.
 *
 * `process` is a legend for the trace spine the user is about to meet.
 * Four things that genuinely exist, in the lexicon's words (RC-12).
 */
export const LANDING = {
  eyebrow: "Evidence Workbench",
  heading: "What should the literature settle?",
  questionLabel: "Research question",
  questionPlaceholder:
    "e.g. How do current systems evaluate faithfulness in retrieval-augmented generation?",
  disclosure:
    "Generating a plan starts a billable run. You review and edit the plan before any arXiv search or paper reading happens.",
  submit: "Generate plan",
  submitPending: "Generating plan…",
  process: ["Question", "Plan you approve", "arXiv run", "Briefing"],
} as const;

/** Group thousands without `toLocaleString`, whose output is host-dependent. */
function groupDigits(value: number): string {
  return String(Math.trunc(Math.abs(value))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * The character counter, visible from zero characters (03 §1.4).
 *
 * A counter, not a percentage: 03 §5.5 forbids any `%`, and a fraction of
 * a character limit is the one place a `%` would look harmless.
 */
export function queryCounter(length: number): string {
  return `${groupDigits(length)} / ${groupDigits(MAX_QUERY_LEN)}`;
}

/** Over the bound, client-side, before a request is ever made. */
export function queryOverLimit(length: number): string {
  const over = Math.max(0, Math.trunc(length) - MAX_QUERY_LEN);
  return `${groupDigits(over)} character${over === 1 ? "" : "s"} over the limit. Shorten the question to send it.`;
}

// ---------------------------------------------------------------------------
// Status words and marks (03 §3.4).
// ---------------------------------------------------------------------------

/**
 * The word for each run state, from 03 §3.4's table.
 *
 * The table's order of precedence is word, then mark, then colour. This
 * object is the first of those three; `SEVERITY_MARK` in
 * `components/primitives/StatusBadge.tsx` is the second.
 */
export const RUN_STATUS_WORD = {
  observed: "observed",
  live: "Live",
  notObserved: "not observed",
  pendingReview: "Waiting for your review",
  succeeded: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
  expired: "No longer available",
} as const;

/** The spine legend, rendered once per session and then behind a disclosure. */
export const SPINE_LEGEND = [
  { mark: "circle", meaning: "observed on this connection" },
  { mark: "dashed-rule", meaning: "not observed" },
  { mark: "diamond", meaning: "waiting for your review" },
  { mark: "square", meaning: "complete" },
  { mark: "hollow-square", meaning: "cancelled" },
  { mark: "dashed-square", meaning: "no longer available" },
] as const;

/** The four spine segments (03 §5.3) — status transitions, not node names. */
export const SPINE_SEGMENTS = ["Question", "Plan", "Run", "Report"] as const;

// ---------------------------------------------------------------------------
// The status line, state by state (03 §5.4).
// ---------------------------------------------------------------------------

/**
 * The fixed status lines. Every one of them is a sentence about something
 * the contract actually reports.
 *
 * `rejoined` and `reconnecting` are the two that carry H2: after any
 * reload or reconnect the checkpoint is genuinely unknown, and the UI says
 * so instead of leaving the last tick on screen implying otherwise.
 */
export const RUN_STATUS_LINE = {
  submitting: LANDING.submitPending,
  awaitingReview: "Waiting for your review. The run is paused and not spending.",
  rejoined: "Rejoined this run. Earlier checkpoints are not replayed.",
  reconnecting: "Reconnecting. Checkpoints during the gap are not replayed.",
  recycled: "Connection recycled by the server. The run is still going.",
  cancelled: "Cancelled at plan review. Nothing was searched.",
  historic:
    "This briefing was produced outside this session. Its plan and checkpoints are not stored.",
  failedWithoutCheckpoints:
    "Failed. No checkpoints were observed on this connection.",
  positionNotReported: "Position after the last checkpoint is not reported.",
} as const;

/**
 * §5.4: the 404 sentence, and the only one for an aged-out run.
 *
 * RE-HOMED FROM `web/lib/job/machine.ts` BY WO-12. It lived there because
 * WO-10 needed it provable, and it lives here because criterion 1 says one
 * module is the single edit site; `machine.ts` now imports it, and the
 * allow-list and deny-list tests that guarded it travelled to
 * `web/tests/copy/forbidden.test.ts` with the wording.
 *
 * Never "deleted", never "no permission" (H8): a 404 covers both missing
 * and not-yours by design (`routes.py:59-84`), and retention is why a run
 * this browser watched an hour ago can be gone now
 * (`api_job_retention_sec`, `src/config.py:307`).
 */
export const UNAVAILABLE_COPY =
  "This run is no longer available. Run records are kept for a limited time.";

/**
 * The checkpoint count, with the qualifier that makes it true (03 §5.5).
 *
 * "on this connection" is not softening. The ledger is reset on every
 * open, including the browser's own retry (04 §4.4 rule 2), so the number
 * describes what this EventSource saw and nothing else.
 */
export function checkpointCount(count: number): string {
  const n = Math.max(0, Math.trunc(count));
  if (n === 0) return "No checkpoints observed on this connection";
  return `${n} checkpoint${n === 1 ? "" : "s"} observed on this connection`;
}

/**
 * A checkpoint's label, or the honest absence of one.
 *
 * The label is the event payload's `node`, verbatim (H11). It is never
 * looked up in a vocabulary, because `state_delta` is an open scalar map
 * (`runner.py:947-951`) and no node set is guaranteed.
 */
export function checkpointName(node: string | null | undefined): string {
  return typeof node === "string" && node !== "" ? node : NOT_REPORTED;
}

/** "observed <node>" — the qualifier travels with the name (03 §5.5). */
export function observedCheckpoint(node: string | null | undefined): string {
  return `observed ${checkpointName(node)}`;
}

/** "updated 41s ago", or nothing at all when no frame has ever arrived. */
export function lastUpdated(secondsAgo: number | null | undefined): string | null {
  if (typeof secondsAgo !== "number" || !Number.isFinite(secondsAgo)) return null;
  const seconds = Math.max(0, Math.trunc(secondsAgo));
  if (seconds < 60) return `updated ${seconds}s ago`;
  const minutes = Math.trunc(seconds / 60);
  if (minutes < 60) return `updated ${minutes}m ago`;
  return `updated ${Math.trunc(minutes / 60)}h ago`;
}

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

/**
 * The failure line for a settled run (H3).
 *
 * "Failed after the last observed checkpoint (`reader`)." when one was
 * seen; 03 §5.4's checkpoint-free sentence otherwise. Never "failed in",
 * never "failed during", never a stage: no terminal payload carries a node
 * (`runner.py:1063-1072`, `routes.py:857-867`), so any preposition that
 * attributes the failure *to* a node is invention.
 */
export function failedStatusLine(node: string | null | undefined): string {
  if (typeof node !== "string" || node === "") {
    return RUN_STATUS_LINE.failedWithoutCheckpoints;
  }
  return `Failed after the last observed checkpoint (${node}).`;
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
// Diagnostics (04 §9.2).
// ---------------------------------------------------------------------------

/**
 * The diagnostics disclosure — collapsed by default, so routine SSE frames
 * are never announced (03 §7.3).
 *
 * `copyNote` states the redaction rule as a promise the user can check:
 * no report text, no question text, no headers, no URLs beyond the path
 * template, and nothing transmitted anywhere.
 */
export const DIAGNOSTICS = {
  label: "Technical events",
  logLabel: "Received frames",
  empty: "No frames have been received on this connection.",
  copyAction: "Copy diagnostics",
  copyNote:
    "Copies the last 200 frames and the raw error strings to the clipboard. No question text, no briefing text, no headers and no keys, and nothing is sent anywhere.",
  copied: "Copied to the clipboard.",
} as const;
