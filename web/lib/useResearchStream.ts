"use client";

// M2 compatibility adapter (RC-03, 05-MIGRATION.md §1.1).
//
// The lifecycle this hook used to implement now lives in
// `web/lib/job/` — a pure reducer (`machine.ts`), the imperative
// stream/attach/submit side (`useJobStream.ts`), and a provider
// (`provider.tsx`). What survives here is the hook's *public shape*,
// so `components/ConversationThread.tsx` and the tests that pin its
// behaviour keep working unchanged while the surfaces migrate.
//
// That is the RC-03 ruling in force: the MUST-KEEP from
// `00-DISCOVERY.md` #6 is the *behaviour* — named SSE event handling,
// unknown-event tolerance, reconnect, and final `GET JobDetail`
// reconciliation — not the filename. The behaviour moved; the tests
// that guard it did not move with it, and they still pass, which is
// the evidence that the port was faithful. WO-31 deletes this file
// once its last consumer is gone.
//
// Two deliberate legacy pins, both scoped to this adapter and both
// deleted with it:
//
//   1. `attachMode: "stream-first"`. The machine's own contract is
//      GET-first (04-ARCHITECTURE.md §4.3), but this hook's callers
//      pin the old request ordering — `attach()` opens the
//      `EventSource` synchronously, and the only
//      `GET /research/{id}` in a run is the one a terminal frame
//      triggers. New surfaces use `JobRunProvider`, which is GET-first.
//   2. The sentences below. The machine exposes structured state
//      (`phase`, `unavailableReason`, `failureSource`); the strings
//      that state used to be rendered as are reproduced here so the
//      legacy components render exactly what they rendered before.
//      WO-12's dictionary is where the new copy lives.

import { useCallback, useMemo, useRef, useState } from "react";

import { useJobStream } from "./job/useJobStream";
import type { JobPhase, JobState } from "./job/types";
import {
  JobDetail,
  Plan,
  ReviewAction,
  SseEvent,
  SseEventName,
} from "./types";

/**
 * Own the full research lifecycle for a single query:
 *
 *   1. POST /research to accept the query and get a job_id.
 *   2. Open an `EventSource` on the stream URL; each frame lands in
 *      `events` in receive order.
 *   3. If a `plan_ready` frame arrives (HITL, ADR 0030), expose the
 *      plan via `plan` and wait for the caller to invoke `review()`.
 *   4. On a terminal event, GET the status URL for the settled
 *      JobDetail (the report body + metrics).
 *
 * `attach` is step 2 onwards for a job someone else started (ADR
 * 0053) — the landing page submits and hands the id over in the URL,
 * and a reload of that URL rejoins the same job instead of paying for
 * a second one.
 *
 * Idempotent to caller re-submissions — a fresh submit closes any
 * open stream and resets state before starting.
 */
export interface UseResearchStreamState {
  status: "idle" | "submitting" | "streaming" | "awaiting_review" | "done";
  jobId: string | null;
  events: SseEvent[];
  detail: JobDetail | null;
  plan: Plan | null;
  error: string | null;
  submit: (query: string, options?: SubmitOptions) => Promise<void>;
  attach: (jobId: string, options?: AttachOptions) => void;
  review: (action: ReviewAction, plan?: Plan) => Promise<void>;
}

export interface AttachOptions {
  onDone?: (detail: JobDetail) => void;
}

export interface SubmitOptions extends AttachOptions {
  conversation_id?: string;
}

/**
 * Ten machine phases collapsed onto five legacy statuses.
 *
 * The three that are not one-to-one:
 *
 *   - `submit_failed` and `unavailable` both become `"idle"`, which is
 *     what unlocks the composer. That is the whole point of the
 *     fatal-close branch this hook grew: a dead end has to leave the
 *     thread usable.
 *   - `attaching`, `resolving` and `reconciling` are all `"streaming"`
 *     — the caller's `busy` flag must stay true across a review
 *     resolution and across the settling GET.
 */
const LEGACY_STATUS: Record<JobPhase, UseResearchStreamState["status"]> = {
  idle: "idle",
  submitting: "submitting",
  submit_failed: "idle",
  attaching: "streaming",
  unavailable: "idle",
  live: "streaming",
  awaiting_review: "awaiting_review",
  resolving: "streaming",
  reconciling: "streaming",
  settled: "done",
};

/**
 * The names this hook has always surfaced.
 *
 * `stream_timeout` is deliberately absent even though the machine now
 * registers it: `SseEventName` does not include it and
 * `components/EventLog.tsx:10` keys an exhaustive
 * `Record<SseEventName, string>` off that union, so surfacing it here
 * would render an undefined label. The frame is still handled — it
 * reopens the stream — it is just not part of this hook's contract.
 */
const LEGACY_EVENT_NAMES: ReadonlySet<string> = new Set<SseEventName>([
  "job_started",
  "node_completed",
  "plan_ready",
  "job_completed",
  "job_failed",
  "job_cancelled",
  "stream_note",
  "error",
]);

/** The error sentence this hook used to compose, from machine state. */
function legacyError(state: JobState): string | null {
  if (state.phase === "unavailable") {
    // `useResearchStream.ts:183-186`, preserved verbatim: `?job=`
    // outlives the job itself, and the dead end has to say so.
    return (
      `stream unavailable for job ${state.jobId} — it may have expired. ` +
      "Ask the question again to start a new run."
    );
  }
  if (state.failureMessage === null) return null;
  switch (state.failureSource) {
    case "submit":
      return state.failureMessage;
    case "reconcile":
      return `fetch result failed (${state.failureStatus ?? 0}): ${state.failureMessage}`;
    case "review":
      return `review failed (${state.failureStatus ?? 0}): ${state.failureMessage}`;
    default:
      // An attach or poll read that failed without ending the run. The
      // legacy hook had no such path — it never read the job except to
      // settle it — so it showed nothing, and neither does this.
      return null;
  }
}

export function useResearchStream(): UseResearchStreamState {
  const onDoneRef = useRef<AttachOptions["onDone"] | null>(null);
  // The one error this hook raises that the machine has no event for:
  // `review()` called with no job. The machine cannot review nothing,
  // so it does nothing; the sentence is the adapter's.
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSettled = useCallback((detail: JobDetail) => {
    onDoneRef.current?.(detail);
  }, []);

  const {
    state,
    submit: machineSubmit,
    attach: machineAttach,
    review: machineReview,
  } = useJobStream({
    attachMode: "stream-first",
    onSettled: handleSettled,
  });

  const submit = useCallback(
    async (query: string, options: SubmitOptions = {}) => {
      onDoneRef.current = options.onDone ?? null;
      setLocalError(null);
      await machineSubmit(query, {
        conversationId: options.conversation_id ?? null,
      });
    },
    [machineSubmit]
  );

  const attach = useCallback(
    (jobId: string, options: AttachOptions = {}) => {
      onDoneRef.current = options.onDone ?? null;
      setLocalError(null);
      machineAttach(jobId);
    },
    [machineAttach]
  );

  const jobId = state.jobId;
  const review = useCallback(
    async (action: ReviewAction, planEdits?: Plan) => {
      if (jobId === null) {
        setLocalError("no active job to review");
        return;
      }
      setLocalError(null);
      await machineReview(action, planEdits);
    },
    [jobId, machineReview]
  );

  const events = useMemo<SseEvent[]>(
    () =>
      state.frames
        .filter((frame) => LEGACY_EVENT_NAMES.has(frame.name))
        .map((frame) => ({
          name: frame.name as SseEventName,
          data: frame.data,
          receivedAt: frame.receivedAt,
        })),
    [state.frames]
  );

  return {
    status: LEGACY_STATUS[state.phase],
    jobId,
    events,
    detail: state.detail,
    plan: state.plan,
    error: localError ?? legacyError(state),
    submit,
    attach,
    review,
  };
}
