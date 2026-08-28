// The TRACE half of the run dictionary — 03 §3.4's status words, §5.3's
// legend and segments, §5.4's status lines, and the four composers that
// name or count checkpoints.
//
// ============================================================================
// WHY THIS IS A SEPARATE FILE FROM `run.ts`, AND WHY NOT A WORD MOVED
//
// Every string and every function below was written by WO-12 and lives here
// BYTE-IDENTICAL. `run.ts` re-exports the whole module (`export * from
// "./trace"`), so `@/lib/copy/run`, `@/lib/copy` and every existing
// importer — `lib/job/machine.ts` included — see exactly the export set
// they saw before, and `web/tests/copy/forbidden.test.ts` walks exactly the
// same names. Nothing is renamed, nothing is reworded, nothing is added.
//
// THE REASON IS THE MEASUREMENT HAZARD `web/vitest.config.mts` RECORDS FOR
// WO-13 … WO-19, hit for real by WO-15:
//
//   "When a module under `include` is loaded by BOTH projects, the two Vite
//    pipelines produce two different transforms of it, and the merged
//    report unions statements, branches and lines correctly but
//    CONCATENATES the function lists. … The fix is not a lower floor — it
//    is for a story to import the modules it actually exercises."
//
// The trace spine's stories exercise the trace copy: they count
// checkpoints, name them, age the last frame and compose the failure
// sentence. They do NOT exercise the landing composer's character counter,
// the metrics line or the terminal phrase — those belong to WO-13 and
// WO-19 — and before this split, importing one string from `run.ts` dragged
// all eleven of its functions into the Storybook project, where seven of
// them were never called. Measured: `lib/copy/run.ts` fell from 100% to
// 68.18% functions and took the global floor from 95.00% to 93.72% without
// a line of product code changing.
//
// So the split is drawn where the SURFACES are, which is 06-WORK-ORDERS.md
// §5.6's file-ownership rule applied one level down:
//
//   trace.ts  what the spine and the ledger render        (WO-15)
//   run.ts    landing, metrics, terminal phrase, review,
//             briefing, diagnostics                       (WO-12, WO-13, WO-19)
//
// ============================================================================
// THE THREE STRUCTURAL RULES (03 §5.5), unchanged and still enforced by
// `web/tests/copy/forbidden.test.ts` through `run.ts`'s re-export:
//
//   - "on this connection" appears wherever a checkpoint COUNT appears.
//   - "observed" appears wherever a checkpoint is NAMED.
//   - "not reported" replaces "unknown", everywhere.

import { NOT_REPORTED } from "./errors";

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
 * `rejoined` and `reconnecting` are the two that carry H2: after any reload
 * or reconnect the checkpoint is genuinely unknown, and the UI says so
 * instead of leaving the last tick on screen implying otherwise.
 *
 * `submitting` IS THE ONE STRING IN THIS DIRECTORY WITH TWO DECLARATION
 * SITES, and the duplication is deliberate, guarded and worth explaining.
 *
 * WO-12 wrote it once, as `LANDING.submitPending`, and had `run.ts` read
 * `RUN_STATUS_LINE.submitting` from it — one file, one string, no cost.
 * The two halves then went to two files for two independent reasons: WO-13
 * moved `LANDING` to `./composer.ts` so a composer story would not drag
 * `run.ts`'s eleven functions into the Storybook project, and this work
 * order moved `RUN_STATUS_LINE` here so a SPINE story would not do the same
 * thing. An import between them would undo one of those moves whichever
 * way it pointed, and it would put the landing surface's copy on
 * `/c/[id]`'s first-load — the route WO-13's own header says has the least
 * headroom — for one 17-character sentence.
 *
 * They are also two different things wearing the same words: one is a
 * BUTTON LABEL while `POST /research` is in flight, the other is the
 * SPINE's status line for 03 §5.4's submitting row. `web/tests/copy/spine-copy.test.ts`
 * pins them equal, so a divergence is a decision somebody made rather than
 * a drift nobody noticed.
 */
export const RUN_STATUS_LINE = {
  submitting: "Generating plan…",
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
 * WO-10 needed it provable, and it lives in the dictionary because
 * criterion 1 says one module is the single edit site; `machine.ts` imports
 * it through `run.ts`, and the allow-list and deny-list tests that guarded
 * it travelled to `web/tests/copy/forbidden.test.ts` with the wording.
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
 * "on this connection" is not softening. The ledger is reset on every open,
 * including the browser's own retry (04 §4.4 rule 2), so the number
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
