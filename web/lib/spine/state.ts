// The trace spine's state derivation (WO-15 criteria 1, 3, 4; 03 §5.1-§5.5).
//
// ============================================================================
// THE BINDING CONSTRAINT (03 §5.1, REVIEW.md blocking finding 2)
//
//   "The trace may be driven ONLY by job status plus the last observed
//    completed `node_completed` checkpoint. It must never claim a live
//    'current stage' or that a run 'failed in stage X'. After a reload the
//    position may be unknown. Failure is *after the last observed
//    checkpoint*. Stage labels derive only from observed events — there is
//    no pre-labelled fixed node vocabulary."
//
// This module is where that is enforceable rather than remembered. It is
// PURE — no React, no clock, no network, no `EventSource` — and it takes
// exactly 03 §5.2's four inputs. `TraceSpine` renders `describeSpine()`'s
// output and reads nothing else, which is what makes criterion 1's purity
// test ("identical render given the same four inputs regardless of any
// other prop") a property of the code rather than a promise about it.
//
// ============================================================================
// THE FOUR INPUTS, AND THE TWO PLACES THE READING IS WIDER THAN THE TABLE
//
// 03 §5.2's table is: job status; checkpoints observed on this connection;
// plan; time since the last frame. Two clarifications, both stated here
// rather than discovered by a reader of the switch below:
//
//  1. INPUT 1's DOMAIN INCLUDES THE RUN'S EXISTENCE. `JobDetail.status` has
//     six values, and the product also knows two facts of the same kind
//     that are not among them: a `POST /research` is in flight and no run
//     exists yet (`submitting`), and a `GET` returned 404 so the run no
//     longer exists (`unavailable`, H8). Both are statements about the
//     job's existence, which is what a status is; neither is a stage.
//     Modelling them as a fifth input would be worse — it would put a
//     second authority beside the authoritative one.
//  2. INPUT 2 IS "…ON THIS CONNECTION", so the connection is part of it.
//     03 §5.4 needs four different sentences for the same ledger depending
//     on what the EventSource is doing (streaming, dropped, recycled by the
//     server, closed), and `checkpointIsCurrent()` — WO-10's selector,
//     which goes false the moment a connection ends — is the honest
//     mechanism for "ticks kept, then a broken rule". A ledger without its
//     connection is not the input the brief names.
//
// WHAT IS DELIBERATELY *NOT* READ, and where it went instead:
//
//   - `state.frames` beyond one name check. The frame log is WO-16's
//     Diagnostics surface.
//   - `cost_usd`, `quality_score`, `llm_calls`, `elapsed_sec`. 03 §5.4's
//     succeeded row prints them, and they are NOT among §5.2's four
//     inputs, so they belong to WO-19's MetricsStrip and not here. The
//     spine says "Complete"; the strip says what it cost.
//   - `error` / `error_type`. WO-12's StatusBanner renders those.
//
// ============================================================================
// TWELVE STATES, AND THE THREE PAIRS THAT LOOK ALIKE
//
// 03 §5.4's table has exactly twelve rows and `SPINE_STATES` is exactly
// those twelve. Three pairs share a job status and are told apart by the
// ledger alone, which is the only honest discriminator available:
//
//   succeeded / historic          — did WE watch it finish?
//   failed_observed / _unobserved — is there a last observed checkpoint?
//   running_observed / rejoined   — has this connection seen anything?
//
// "Loaded from thread history" and "reattached after a reload to a run that
// already finished" are the SAME situation to a client with no replay
// backlog, and they get the same sentence. That is D-010's `job.plan = None`
// permanence, rendered.

import type { JobStatus, Plan } from "@/lib/api";
import type { ObservedCheckpoint } from "@/lib/job/types";
// `@/lib/copy/trace` and not `@/lib/copy/run`: the spine renders the trace
// half of the dictionary and nothing else, and importing the whole of
// `run.ts` would drag the landing composer's and the metrics strip's
// functions into every story's module graph. See `lib/copy/trace.ts`'s
// header for the measurement that made the boundary necessary.
import {
  RUN_STATUS_LINE,
  RUN_STATUS_WORD,
  SPINE_SEGMENTS,
  UNAVAILABLE_COPY,
  failedStatusLine,
} from "@/lib/copy/trace";
import { SPINE, detailSeparator, observationDetail } from "@/lib/copy/spine";

// ---------------------------------------------------------------------------
// Vocabulary.
// ---------------------------------------------------------------------------

/** 03 §5.4's twelve rows, in the order the table prints them. */
export const SPINE_STATES = [
  "submitting",
  "awaiting_review",
  "running_observed",
  "rejoined",
  "reconnecting",
  "recycled",
  "succeeded",
  "historic",
  "failed_observed",
  "failed_unobserved",
  "cancelled",
  "expired",
] as const;

export type SpineStateId = (typeof SPINE_STATES)[number];

/**
 * Input 1's domain: the six server statuses, the two existence facts, and
 * `null` for "the API has not said" (H2 — say so, never guess).
 */
export type SpineStatus = JobStatus | "submitting" | "unavailable" | null;

/** Input 2's second half: what the connection that observed them is doing. */
export const SPINE_CONNECTIONS = [
  "open",
  "reconnecting",
  "recycled",
  "closed",
] as const;

export type SpineConnection = (typeof SPINE_CONNECTIONS)[number];

/**
 * 03 §3.4's eight statuses, which are also the eight marks.
 *
 * Seven of them can be a segment's status; `live` is the ambient receiving
 * indicator and is never a segment. All eight carry a distinct WORD, which
 * is the channel that survives colour and images being unavailable.
 */
export const SEGMENT_STATUSES = [
  "observed",
  "live",
  "not-observed",
  "awaiting-review",
  "complete",
  "failed",
  "cancelled",
  "unavailable",
] as const;

export type SegmentStatus = (typeof SEGMENT_STATUSES)[number];

/** 03 §3.4's word column, in this surface's own key space. */
export const SEGMENT_WORD: Record<SegmentStatus, string> = {
  observed: RUN_STATUS_WORD.observed,
  live: RUN_STATUS_WORD.live,
  "not-observed": RUN_STATUS_WORD.notObserved,
  "awaiting-review": RUN_STATUS_WORD.pendingReview,
  complete: RUN_STATUS_WORD.succeeded,
  failed: RUN_STATUS_WORD.failed,
  cancelled: RUN_STATUS_WORD.cancelled,
  unavailable: RUN_STATUS_WORD.expired,
};

// ---------------------------------------------------------------------------
// The four inputs.
// ---------------------------------------------------------------------------

/**
 * Input 2 in full: what this connection observed, and what it is doing.
 *
 * `current` is `checkpointIsCurrent()` — true only while the last
 * checkpoint still describes the connection we are on. It is what 03 §5.4's
 * reconnect row needs: the ticks are KEPT (they really were observed) and
 * the trailing rule breaks (they no longer describe now).
 */
export interface ObservationInput {
  /** Every `node_completed` label, in receive order, verbatim (H11). */
  checkpoints: readonly ObservedCheckpoint[];
  connection: SpineConnection;
  current: boolean;
}

/** 03 §5.2, and nothing else. */
export interface SpineInputs {
  /** Input 1 — `JobDetail.status`, or the terminal frame. Authoritative. */
  status: SpineStatus;
  /** Input 2 — observation, not history. */
  observation: ObservationInput;
  /** Input 3 — non-null only during `pending_review`; erased on resume. */
  plan: Plan | null;
  /** Input 4 — client clock, resolved to seconds by the caller. */
  secondsSinceLastFrame: number | null;
}

// ---------------------------------------------------------------------------
// The model a renderer needs.
// ---------------------------------------------------------------------------

export interface SpineSegment {
  /** "Question" | "Plan" | "Run" | "Report" (03 §5.3). */
  name: string;
  status: SegmentStatus;
  /** 03 §3.4's word. Rendered as text beside the mark, never instead of it. */
  word: string;
}

export interface SpineModel {
  id: SpineStateId;
  /** Always four, in `SPINE_SEGMENTS` order. */
  segments: readonly SpineSegment[];
  /** The ledger, verbatim and append-only. Never invented, never sorted. */
  ledger: readonly ObservedCheckpoint[];
  /**
   * The single `role="status"` sentence. Material transitions only — it is
   * identical before and after a checkpoint arrives (03 §5.7).
   */
  announcement: string;
  /** The count and the age. NOT announced; it moves on every frame. */
  detail: string | null;
  /** What joins the two. See `detailSeparator`. */
  separator: string;
  /** An EventSource is open: the one place ambient motion is allowed. */
  live: boolean;
  /**
   * The ticks still describe the connection we are on. `false` after a drop
   * — the ledger stays, the claim does not.
   */
  current: boolean;
}

// ---------------------------------------------------------------------------
// Deriving the state id.
// ---------------------------------------------------------------------------

/** Statuses that mean the run is over and nothing more will arrive. */
function isOver(status: SpineStatus): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

/**
 * Which of 03 §5.4's twelve rows this is.
 *
 * Total over `SpineInputs`: every combination lands on a row, so criterion
 * 4's "all seven contract fixtures render a defined state" cannot fail by
 * falling through a gap.
 */
export function spineStateId(inputs: SpineInputs): SpineStateId {
  const { status, observation, plan } = inputs;
  const observed = observation.checkpoints.length > 0;

  if (status === "submitting") return "submitting";
  if (status === "unavailable") return "expired";
  if (status === "cancelled") return "cancelled";
  if (status === "succeeded") return observed ? "succeeded" : "historic";
  if (status === "failed") return observed ? "failed_observed" : "failed_unobserved";

  // Not over. The plan is input 3 and it is only ever non-null while the
  // run is paused at the review (`schemas.py:98-124`), so its presence is
  // as good an authority for the pause as the status is — and it arrives
  // over SSE a poll earlier.
  if (status === "pending_review" || (plan !== null && !isOver(status))) {
    return "awaiting_review";
  }

  if (observation.connection === "recycled") return "recycled";
  if (observation.connection === "reconnecting") return "reconnecting";
  return observed ? "running_observed" : "rejoined";
}

// ---------------------------------------------------------------------------
// Segments.
//
// The table is the whole of 03 §5.4's "Spine" column, and exactly ONE cell
// is computed rather than written: RUN follows the ledger wherever the
// table's own value is one of the two observational ones, so
// `RunningNoCheckpoint` and `RunningWithCheckpoint` cannot disagree with
// the ledger printed beside them.
//
// THE PLAN CELL IS NOT COMPUTED, AND THAT IS THE INTERESTING ONE.
// 03 §5.3's sketch draws `Plan ──●  approved` through the middle of a run.
// This does not, because §5.1 and §5.2 govern the sketch: the plan is an
// OBSERVATION ("erased on resume") and `JobDetail.plan` is non-null only
// during `pending_review` (`schemas.py:98-124`). A `running` job may not
// have reached the planner at all, and one that HAS resumed no longer
// carries the plan that would prove it did. Filling that mark from the
// status alone is exactly the invention this surface exists not to commit.
// So the Plan segment is `awaiting-review` while the pause is on,
// `cancelled` for a run cancelled at it — the review pause is the only
// cancellation point there is — and `not-observed` otherwise.
// ---------------------------------------------------------------------------

type SegmentRow = readonly [SegmentStatus, SegmentStatus, SegmentStatus, SegmentStatus];

const SEGMENT_TABLE: Record<SpineStateId, SegmentRow> = {
  // 03 §5.4 "Submitting": `Question ─◌` and the rest inert. Nothing has
  // been observed, because there is not yet a run to observe.
  submitting: ["not-observed", "not-observed", "not-observed", "not-observed"],
  // "`pending_review`": `Question ──● Plan ──◇`.
  awaiting_review: ["observed", "awaiting-review", "not-observed", "not-observed"],
  // "Running, checkpoints seen": ticks appended, trailing dashed rule.
  running_observed: ["observed", "not-observed", "observed", "not-observed"],
  // "Running, rejoined after reload": run segment fully dashed, ledger empty.
  rejoined: ["observed", "not-observed", "not-observed", "not-observed"],
  // "Reconnecting": ticks kept, then a broken rule.
  reconnecting: ["observed", "not-observed", "observed", "not-observed"],
  // "Stream recycled": spine unchanged; only the sentence differs.
  recycled: ["observed", "not-observed", "observed", "not-observed"],
  // "Succeeded": `… Run ──● Report ■`.
  succeeded: ["observed", "not-observed", "observed", "complete"],
  // "Succeeded, loaded from thread history":
  // `Question ──? Plan ──? Run ──? Report ■`.
  historic: ["unavailable", "unavailable", "unavailable", "complete"],
  // "Failed, checkpoints seen": ticks then a slashed square.
  failed_observed: ["observed", "not-observed", "observed", "failed"],
  // "Failed, none seen": dashed run then a slashed square.
  failed_unobserved: ["observed", "not-observed", "not-observed", "failed"],
  // "Cancelled": `Question ──● Plan ──□`. The review pause is the only
  // cancellation point there is, so a cancelled run was reviewed.
  cancelled: ["observed", "cancelled", "not-observed", "not-observed"],
  // "Expired": every segment dashed with `?`.
  expired: ["unavailable", "unavailable", "unavailable", "unavailable"],
};

/** `true` for the two cells the ledger and the plan are allowed to move. */
function isObservational(status: SegmentStatus): boolean {
  return status === "observed" || status === "not-observed";
}

function segmentsFor(id: SpineStateId, inputs: SpineInputs): SpineSegment[] {
  const row = SEGMENT_TABLE[id];
  const observed = inputs.observation.checkpoints.length > 0;

  return SPINE_SEGMENTS.map((name, index) => {
    const declared = row[index] as SegmentStatus;
    // The ONE computed cell. Everything else is the table above, verbatim.
    const status =
      index === RUN_INDEX && isObservational(declared)
        ? observed
          ? "observed"
          : "not-observed"
        : declared;
    return { name, status, word: SEGMENT_WORD[status] };
  });
}

/** `Run`'s index in `SPINE_SEGMENTS`. The segment the ledger belongs to. */
const RUN_INDEX = 2;

// ---------------------------------------------------------------------------
// Sentences.
// ---------------------------------------------------------------------------

/** The four states in which frames are still expected to arrive. */
const STREAMING: ReadonlySet<SpineStateId> = new Set<SpineStateId>([
  "running_observed",
  "rejoined",
  "reconnecting",
  "recycled",
]);

/**
 * The material sentence, and only the material sentence.
 *
 * 03 §5.7: the live region announces "awaiting review, reconnecting,
 * recycled, complete, failed, cancelled, expired — never individual
 * checkpoints". So `running_observed` announces the bare word "Running",
 * which does not change when a tick arrives; the count and the age go to
 * `detail`, outside the live region.
 */
function announcementFor(id: SpineStateId, inputs: SpineInputs): string {
  const checkpoints = inputs.observation.checkpoints;
  const last = checkpoints[checkpoints.length - 1]?.node ?? null;

  switch (id) {
    case "submitting":
      return RUN_STATUS_LINE.submitting;
    case "awaiting_review":
      return RUN_STATUS_LINE.awaitingReview;
    case "running_observed":
      return SPINE.running;
    case "rejoined":
      // H2 with the status itself missing: state C of §4's coverage map.
      // "Rejoined" is a claim about the connection and is true either way;
      // when the API has said nothing at all, say that instead.
      return inputs.status === null ? SPINE.notReportedYet : RUN_STATUS_LINE.rejoined;
    case "reconnecting":
      return RUN_STATUS_LINE.reconnecting;
    case "recycled":
      return RUN_STATUS_LINE.recycled;
    case "succeeded":
      // 03 §5.4 prints duration, quality, cost and calls here. None of the
      // four is among §5.2's inputs; WO-19's MetricsStrip renders them.
      return SEGMENT_WORD.complete;
    case "historic":
      return RUN_STATUS_LINE.historic;
    case "failed_observed":
    case "failed_unobserved":
      // H3, in one call: "Failed after the last observed checkpoint (x)."
      // or 03 §5.4's checkpoint-free sentence. Never "failed in".
      return failedStatusLine(last);
    case "cancelled":
      return RUN_STATUS_LINE.cancelled;
    case "expired":
      return UNAVAILABLE_COPY;
  }
}

// ---------------------------------------------------------------------------
// The model.
// ---------------------------------------------------------------------------

/** 03 §5.4, as one pure function of 03 §5.2's four inputs. */
export function describeSpine(inputs: SpineInputs): SpineModel {
  const id = spineStateId(inputs);
  const count = inputs.observation.checkpoints.length;
  const streaming = STREAMING.has(id);
  const announcement = announcementFor(id, inputs);

  return {
    id,
    segments: segmentsFor(id, inputs),
    ledger: inputs.observation.checkpoints,
    announcement,
    // The age is only meaningful while frames are still expected; a settled
    // run's "updated 41s ago" would be a clock, not a fact about the run.
    detail:
      streaming || count > 0
        ? observationDetail(count, streaming ? inputs.secondsSinceLastFrame : null)
        : null,
    separator: detailSeparator(announcement),
    live: inputs.observation.connection === "open",
    current: inputs.observation.current,
  };
}
