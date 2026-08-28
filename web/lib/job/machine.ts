// The job lifecycle reducer (04-ARCHITECTURE.md §4.2, §4.4).
//
// **Pure.** No clock, no network, no `EventSource`, no React. Every
// timestamp arrives on the event; every read arrives as a resolved
// `JobDetail`. That is what lets `web/tests/job/machine.test.ts` drive
// the whole table with zero mocking.
//
// The table below is TOTAL: `TRANSITIONS[phase][eventType]` exists for
// all 10 × 25 combinations, and a combination the machine deliberately
// ignores is written as `IGNORE`, not left out. There is no default
// branch and no fall-through — a new phase or a new event fails
// `npm run typecheck` until every cell is decided.
//
// ---------------------------------------------------------------------
// The four checkpoint rules (04-ARCHITECTURE.md §4.4), and where each
// one lives, because this is the file a reviewer should audit:
//
//   1. `checkpoint` is set ONLY by `node_completed` — the single
//      assignment is in `observeCheckpoint()`. Nothing else in this
//      file writes `checkpoint` to a non-null value. Grep it.
//   2. `checkpoint` is reset to `null` on EVERY open of a stream,
//      including the browser's own automatic retry, in
//      `beginConnection()`. `openConnection()` calls it for the
//      `stream_opened` event, and `ensureOpen()` calls it for the
//      pathological case of a frame arriving while the connection is
//      not known to be open — so a frame can never attach itself to a
//      connection that had already ended.
//   3. `checkpoint` is never persisted (nothing in `lib/job/` touches
//      `localStorage`/`sessionStorage`) and never derived from
//      `JobDetail` — `adoptDetail()` writes `detail`, `plan`, `phase`
//      and the poll bookkeeping, and touches neither `checkpoint` nor
//      `observed`. `JobDetail` has no node field anyway
//      (`schemas.py:98-124`).
//   4. Terminal copy is "failed after <checkpoint>" or plain "failed",
//      produced by `terminalPhrase()`. Never "failed in <node>": no
//      terminal payload carries a node (`runner.py:1063-1072`,
//      `routes.py:857-867`).

import { TERMINAL_EVENTS } from "@/lib/api";
import type { JobDetail, Plan } from "@/lib/api";
import {
  TERMINAL_PHRASE,
  UNAVAILABLE_COPY as COPY_UNAVAILABLE,
  failedPhrase,
} from "@/lib/copy/run";

import {
  JOB_EVENT_TYPES,
  JOB_PHASES,
  SETTLED_PHASES,
  TERMINAL_JOB_STATUSES,
  type JobEvent,
  type JobEventOf,
  type JobEventType,
  type JobFrame,
  type JobPhase,
  type JobState,
  type ObservedCheckpoint,
} from "./types";

// ---------------------------------------------------------------------------
// Initial state.
// ---------------------------------------------------------------------------

/** How many frames the log keeps (04-ARCHITECTURE.md §9.2). */
export const MAX_FRAMES = 200;

export const initialJobState: JobState = {
  phase: "idle",
  jobId: null,
  detail: null,
  plan: null,
  checkpoint: null,
  observed: [],
  connection: "closed",
  frames: [],
  terminal: null,
  failure: null,
  failureMessage: null,
  failureStatus: null,
  failureSource: null,
  unavailableReason: null,
  submission: null,
  review: null,
  unchangedPolls: 0,
  detailSignature: null,
  lastFrameAt: null,
  connectionOpenedAt: null,
  suspended: false,
};

// ---------------------------------------------------------------------------
// Payload readers.
//
// Every one of these is defensive on purpose: `state_delta` has no
// schema (`runner.py:947-951`), unknown keys must be tolerated, and a
// malformed body must not throw inside a frame handler.
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The opaque node label, or `null` when the frame carries none (H11). */
export function readNode(data: Record<string, unknown> | null): string | null {
  if (data === null) return null;
  const node = data.node;
  return typeof node === "string" && node !== "" ? node : null;
}

/** `state_delta` passed straight through. Unknown keys are kept. */
export function readStateDelta(
  data: Record<string, unknown> | null
): Record<string, unknown> {
  if (data === null) return {};
  return isRecord(data.state_delta) ? data.state_delta : {};
}

/** The plan out of a `plan_ready` frame (`runner.py:409-414`). */
export function readPlan(data: Record<string, unknown> | null): Plan | null {
  if (data === null || !isRecord(data.plan)) return null;
  return data.plan as unknown as Plan;
}

/**
 * `true` when a terminal frame is the attach-time replay shape.
 *
 * The discriminator is the presence of `status`: the replay carries it
 * and drops `llm_calls` (`routes.py:857-867`), the live frames carry
 * `llm_calls` and no `status` (`runner.py:1278-1288`). It is recorded
 * for diagnostics only — no branch in this file reads a terminal
 * payload's *values* (H9).
 */
export function isReplayShape(frame: JobFrame): boolean {
  return frame.data !== null && "status" in frame.data;
}

/** `true` for the three terminal event names (`streaming.py:89-103`). */
export function isTerminalFrameName(name: string): boolean {
  return (TERMINAL_EVENTS as ReadonlySet<string>).has(name);
}

/** `true` when the server's job status means the run is over. */
export function isTerminalJobStatus(status: JobDetail["status"]): boolean {
  return TERMINAL_JOB_STATUSES.has(status);
}

/**
 * What "the job detail changed" means for the liveness backoff (§4.4).
 *
 * `elapsed_sec` is deliberately excluded: for a job with no
 * `completed_at` the API computes it as `now() - started_at`
 * (`src/api/jobs.py:102-107`), so it differs on *every* poll and a
 * naive comparison would never back off. Everything a user can see is
 * in here; `result` is reduced to its length so the comparison stays
 * cheap on a report-sized body.
 */
export function detailSignature(detail: JobDetail): string {
  return JSON.stringify([
    detail.job_id,
    detail.status,
    detail.completed_at,
    detail.result === null ? null : detail.result.length,
    detail.error,
    detail.error_type,
    detail.cost_usd,
    detail.llm_calls,
    detail.iterations,
    detail.quality_score,
    detail.plan,
  ]);
}

// ---------------------------------------------------------------------------
// State helpers.
// ---------------------------------------------------------------------------

/** Clear every failure field. Called whenever a call succeeds. */
function cleared(state: JobState): JobState {
  return {
    ...state,
    failure: null,
    failureMessage: null,
    failureStatus: null,
    failureSource: null,
  };
}

/**
 * Start a fresh run: everything observational goes, the frame log with
 * it. Used by `submit_requested`, `attach_requested` and `reset`.
 */
function freshRun(state: JobState, jobId: string | null): JobState {
  return {
    ...initialJobState,
    phase: state.phase,
    jobId,
  };
}

/**
 * **Checkpoint rule 2.** A new connection observes nothing until it
 * says so itself: the checkpoint and the per-connection ledger are
 * dropped on every open, including the browser's automatic retry.
 *
 * There is no replay backlog (`routes.py:444-454`) and no
 * `Last-Event-ID` contract (`streaming.py:117-132` writes no `id:`
 * line), so anything published while nobody was subscribed is gone.
 * Carrying a checkpoint across an open would be inventing it.
 */
function beginConnection(state: JobState, at: number): JobState {
  return {
    ...state,
    connection: "open",
    connectionOpenedAt: at,
    checkpoint: null,
    observed: [],
    suspended: false,
  };
}

/**
 * A frame arrived, so the connection is by definition open.
 *
 * If we already knew that, nothing changes. If we did not — the
 * connection was `opening`, or worse, `reconnecting` — then this frame
 * belongs to a connection whose beginning we did not see, and rule 2
 * applies to it exactly as it applies to an observed open. That is the
 * belt to `beginConnection`'s braces, and it is what makes "no
 * invented checkpoint after a gap" hold even if an `open` event is
 * never delivered.
 */
function ensureOpen(state: JobState, at: number): JobState {
  if (state.connection === "open") return state;
  return beginConnection(state, at);
}

/** Append to the receive-ordered frame log, capped at `MAX_FRAMES`. */
function withFrame(state: JobState, frame: JobFrame): JobState {
  const frames = [...state.frames, frame];
  return {
    ...state,
    frames: frames.length > MAX_FRAMES ? frames.slice(-MAX_FRAMES) : frames,
    lastFrameAt: frame.receivedAt,
  };
}

/** The two things every frame does, in order: open the connection, log it. */
function noteFrame(state: JobState, frame: JobFrame): JobState {
  return withFrame(ensureOpen(state, frame.receivedAt), frame);
}

/**
 * **Checkpoint rule 1.** The one and only assignment of `checkpoint`
 * to a non-null value in this codebase.
 *
 * A `node_completed` frame with no usable `node` key contributes
 * nothing — the label would have to be invented, and
 * `terminal_replay_no_node.jsonl` exists to prove a stream like that
 * leaves the ledger empty.
 */
function observeCheckpoint(state: JobState, frame: JobFrame): JobState {
  const node = readNode(frame.data);
  if (node === null) return state;
  const observation: ObservedCheckpoint = {
    node,
    observedAt: frame.receivedAt,
    stateDelta: readStateDelta(frame.data),
  };
  return {
    ...state,
    checkpoint: observation,
    observed: [...state.observed, observation],
  };
}

/**
 * Adopt a `JobDetail` and move to the phase its status implies.
 *
 * **Checkpoint rule 3 lives here by omission**: this function writes
 * `detail`, `plan`, `phase`, `jobId` and the poll bookkeeping, and
 * never `checkpoint` or `observed`. `JobDetail` has no node field to
 * derive one from (`schemas.py:98-124`), and pretending otherwise —
 * "it was running, so it must have finished the planner" — is exactly
 * the invention REVIEW.md forbids.
 */
function adoptDetail(
  state: JobState,
  event: JobEventOf<"detail_resolved">
): JobState {
  const { detail, source } = event;
  const signature = detailSignature(detail);
  const unchanged = state.detailSignature === signature;
  const base = cleared({
    ...state,
    detail,
    jobId: detail.job_id,
    detailSignature: signature,
    // Only the liveness poll moves the backoff counter; an attach, a
    // reconcile or a manual refresh says nothing about how quiet the
    // job is.
    unchangedPolls:
      source === "poll"
        ? unchanged
          ? state.unchangedPolls + 1
          : 0
        : state.unchangedPolls,
  });

  if (isTerminalJobStatus(detail.status)) {
    return {
      ...base,
      phase: "settled",
      // The pause is over; a resolved plan is not a plan to review.
      plan: null,
      review: null,
      connection: "closed",
      submission: null,
    };
  }
  if (detail.status === "pending_review") {
    return {
      ...base,
      phase: "awaiting_review",
      plan: detail.plan ?? state.plan,
      submission: null,
    };
  }
  return { ...base, phase: "live", plan: null, review: null, submission: null };
}

/** A terminal frame: a signal to reconcile, and nothing else (H9). */
function signalTerminal(
  state: JobState,
  frame: JobFrame,
  name: "job_completed" | "job_failed" | "job_cancelled"
): JobState {
  return {
    ...noteFrame(state, frame),
    phase: "reconciling",
    connection: "closed",
    review: null,
    // Note what arrived and when. NOT what it said: `iterations`,
    // `quality_score`, `cost_usd`, `error`, `status`, `reason` and
    // `llm_calls` are all read from `GET /research/{id}` instead,
    // because one name has three shapes (§11.3) and only the GET has
    // all of them.
    terminal: { name, shape: isReplayShape(frame) ? "replay" : "live", receivedAt: frame.receivedAt },
  };
}

/** The browser is retrying on its own. Narrate it; never race it. */
function narrateInterruption(state: JobState, at: number): JobState {
  return withFrame(
    { ...state, connection: "reconnecting" },
    {
      name: "stream_note",
      data: { message: "connection interrupted; browser is retrying" },
      receivedAt: at,
    }
  );
}

function toUnavailable(
  state: JobState,
  reason: JobState["unavailableReason"],
  failure: JobState["failure"],
  message: string | null,
  status: number | null,
  source: JobState["failureSource"]
): JobState {
  return {
    ...state,
    phase: "unavailable",
    connection: "closed",
    plan: null,
    review: null,
    submission: null,
    unavailableReason: reason,
    failure,
    failureMessage: message,
    failureStatus: status,
    failureSource: source,
  };
}

// ---------------------------------------------------------------------------
// The transition table.
// ---------------------------------------------------------------------------

/** A decided cell: a transition, or a deliberate no-op. */
export type Transition = ((state: JobState, event: JobEvent) => JobState) | null;

/** A cell the machine deliberately ignores in this phase. */
export const IGNORE: Transition = null;

/** One row per phase; every event type present. */
export type TransitionRow = Record<JobEventType, Transition>;

/**
 * Bind a handler to the event type its cell is keyed by.
 *
 * The runtime guard is unreachable — the reducer only ever calls
 * `TRANSITIONS[phase][event.type]` — but it is what lets the body take
 * a narrowed event without an unchecked cast at every call site.
 */
function on<T extends JobEventType>(
  type: T,
  handler: (state: JobState, event: JobEventOf<T>) => JobState
): Transition {
  return (state, event) => {
    if (event.type !== type) return state;
    return handler(state, event as JobEventOf<T>);
  };
}

// -- Shared cells -----------------------------------------------------------

/**
 * A new question. Reachable from every phase except `submitting`,
 * which is the R-01 guard: a submission already in flight refuses a
 * second one rather than paying for it twice.
 */
const startSubmission = on("submit_requested", (state, event) => ({
  ...freshRun(state, null),
  phase: "submitting",
  submission: {
    token: event.token,
    query: event.query,
    conversationId: event.conversationId,
    startedAt: event.at,
  },
}));

/** Adopt the job named in the URL. Never POSTs (ADR 0053). */
const startAttach = on("attach_requested", (state, event) => ({
  ...freshRun(state, event.jobId),
  // `prefetch` is the GET-first path (§4.3): `attaching` means a
  // `GET /research/{id}` is in flight and the stream is not open yet.
  // `false` is `useResearchStream`'s legacy stream-first attach, which
  // has nothing to wait for and goes straight to `live`.
  phase: event.prefetch ? "attaching" : "live",
  // GET-first: nothing is connected until the read comes back. The
  // legacy path opens its stream in the same tick, so it is `opening`.
  connection: event.prefetch ? "closed" : "opening",
}));

/** A reset keeps nothing: the surface is showing no job at all. */
const resetAll: Transition = on("reset", () => initialJobState);

/** `stream_opened` — checkpoint rule 2, applied in every live phase. */
const openConnection = on("stream_opened", (state, event) =>
  beginConnection(state, event.at)
);

const interrupt = on("stream_interrupted", (state, event) =>
  narrateInterruption(state, event.at)
);

/**
 * `readyState === CLOSED` without a terminal frame: the browser failed
 * the connection and will not retry. In practice this is the stream
 * route's 404 on a job that has aged out of `api_job_retention_sec`.
 */
const failStream = on("stream_failed", (state) =>
  toUnavailable(state, "stream_failed", null, null, null, "stream")
);

/**
 * A frame that only ever contributes a log line.
 *
 * `"frame" in event` is the narrowing: every frame event carries one
 * and no other event does, so this is total over the frame names
 * without a per-name generic.
 */
const logFrame: Transition = (state, event) =>
  "frame" in event ? noteFrame(state, event.frame) : state;

/** `node_completed`: log it, then rule 1. */
const checkpointFrame = on("node_completed", (state, event) =>
  observeCheckpoint(noteFrame(state, event.frame), event.frame)
);

/**
 * `plan_ready`, idempotently.
 *
 * The frame can legitimately arrive twice on the in-memory path —
 * deliberate and documented (`routes.py:456-462`) — so a second one
 * lands on the same plan and the same phase, and shows no
 * duplicate-detection warning. The frame log still records both,
 * because the log is a record of what arrived.
 */
const planFrame = on("plan_ready", (state, event) => {
  const next = noteFrame(state, event.frame);
  const plan = readPlan(event.frame.data);
  if (plan === null) return next;
  return { ...next, phase: "awaiting_review", plan, review: null };
});

const terminalFrame =
  (name: "job_completed" | "job_failed" | "job_cancelled"): Transition =>
  (state, event) =>
    "frame" in event ? signalTerminal(state, event.frame, name) : state;

/**
 * `stream_timeout` — the stream hit `api_sse_max_duration_sec`; the
 * job did not stop (`streaming.py:300-308`).
 *
 * The phase is unchanged because nothing about the *run* changed. The
 * connection is marked `reconnecting` because the server has closed
 * the response, and `useJobStream` reopens immediately rather than
 * waiting out the browser's default retry — the gap the current client
 * has at `useResearchStream.ts:59-66`, where the name is not even
 * registered.
 */
const timeoutFrame = on("stream_timeout", (state, event) => ({
  ...noteFrame(state, event.frame),
  connection: "reconnecting",
}));

/** RC-18: `pagehide` closes the stream so `/c/[id]` can enter bfcache. */
const suspendPage = on("page_hidden", (state) => ({
  ...state,
  connection: "closed",
  // H2: the page is going away and the stream with it. Whatever we had
  // observed belonged to a connection that no longer exists.
  checkpoint: null,
  observed: [],
  suspended: true,
}));

/**
 * RC-18: `pageshow` from the back/forward cache. The re-attach itself
 * is an `attach_requested` for the same `?job=`; this only records
 * that the page is live again.
 */
const restorePage = on("page_restored", (state) => ({
  ...state,
  suspended: false,
}));

const acceptDetail = on("detail_resolved", adoptDetail);

const missingDetail = on("detail_not_found", (state, event) =>
  toUnavailable(
    state,
    "not_found",
    event.failure,
    event.message,
    event.status,
    "attach"
  )
);

// -- Rows -------------------------------------------------------------------

const idle: TransitionRow = {
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  detail_resolved: IGNORE,
  detail_not_found: IGNORE,
  detail_unreachable: IGNORE,
  stream_opened: IGNORE,
  stream_interrupted: IGNORE,
  stream_failed: IGNORE,
  job_started: IGNORE,
  node_completed: IGNORE,
  plan_ready: IGNORE,
  job_completed: IGNORE,
  job_failed: IGNORE,
  job_cancelled: IGNORE,
  stream_timeout: IGNORE,
  unknown_frame: IGNORE,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: IGNORE,
  page_restored: IGNORE,
  reset: resetAll,
};

const submitting: TransitionRow = {
  // **R-01, in the reducer.** Even if a caller's own guard fails, a
  // second submission while one is in flight is not a state this
  // machine has. `POST /research` has no idempotency key
  // (`routes.py:179-197`); a duplicate is a duplicate paid run.
  submit_requested: IGNORE,
  submit_accepted: on("submit_accepted", (state, event) => {
    // The token is the guard: a response that does not belong to the
    // submission in flight is a stale one, and adopting its job id
    // would put a job on screen the user did not just ask for.
    if (state.submission === null || state.submission.token !== event.token) {
      return state;
    }
    return {
      ...cleared(state),
      phase: "attaching",
      jobId: event.jobId,
      submission: null,
    };
  }),
  submit_rejected: on("submit_rejected", (state, event) => {
    if (state.submission === null || state.submission.token !== event.token) {
      return state;
    }
    return {
      ...state,
      phase: "submit_failed",
      submission: null,
      failure: event.failure,
      failureMessage: event.message,
      failureStatus: event.status,
      failureSource: "submit",
    };
  }),
  // The URL is truth. If the route names a job while a submission is
  // in flight, the route wins and the token is dropped, which makes
  // the in-flight response inert rather than adopted.
  attach_requested: startAttach,
  detail_resolved: IGNORE,
  detail_not_found: IGNORE,
  detail_unreachable: IGNORE,
  stream_opened: IGNORE,
  stream_interrupted: IGNORE,
  stream_failed: IGNORE,
  job_started: IGNORE,
  node_completed: IGNORE,
  plan_ready: IGNORE,
  job_completed: IGNORE,
  job_failed: IGNORE,
  job_cancelled: IGNORE,
  stream_timeout: IGNORE,
  unknown_frame: IGNORE,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: IGNORE,
  page_restored: IGNORE,
  reset: resetAll,
};

const submitFailed: TransitionRow = {
  // Terminal for this attempt. A retry is an explicit user action and
  // starts a NEW run (H6) — which is exactly what this cell is.
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  detail_resolved: IGNORE,
  detail_not_found: IGNORE,
  detail_unreachable: IGNORE,
  stream_opened: IGNORE,
  stream_interrupted: IGNORE,
  stream_failed: IGNORE,
  job_started: IGNORE,
  node_completed: IGNORE,
  plan_ready: IGNORE,
  job_completed: IGNORE,
  job_failed: IGNORE,
  job_cancelled: IGNORE,
  stream_timeout: IGNORE,
  unknown_frame: IGNORE,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: IGNORE,
  page_restored: IGNORE,
  reset: resetAll,
};

const attaching: TransitionRow = {
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  // §4.2's fan-out: 404 → unavailable, pending_review → awaiting_review
  // with the plan from `JobDetail.plan`, pending|running → live with
  // the checkpoint unknown, terminal → settled with no stream opened
  // at all.
  detail_resolved: on("detail_resolved", (state, event) => {
    const next = adoptDetail(state, event);
    // A non-terminal job is about to have its stream opened; say so,
    // so nothing renders "connected" a beat early.
    return next.phase === "settled" ? next : { ...next, connection: "opening" };
  }),
  detail_not_found: missingDetail,
  // A transport failure on the pre-flight read is NOT proof the run is
  // gone (H8 — only a 404 says that). Carry on to the stream with the
  // status genuinely unknown: `detail` stays null, which is how a
  // consumer knows not to claim one.
  detail_unreachable: on("detail_unreachable", (state, event) => ({
    ...state,
    phase: "live",
    connection: "opening",
    failure: event.failure,
    failureMessage: event.message,
    failureStatus: event.status,
    failureSource: "attach",
  })),
  // The legacy stream-first attach never enters `attaching`, so an
  // `open` here means the GET is still in flight and the stream beat
  // it. Take the connection; the GET's answer still lands.
  stream_opened: on("stream_opened", (state, event) => ({
    ...beginConnection(state, event.at),
    phase: "live",
  })),
  stream_interrupted: interrupt,
  stream_failed: failStream,
  job_started: logFrame,
  node_completed: checkpointFrame,
  plan_ready: planFrame,
  job_completed: terminalFrame("job_completed"),
  job_failed: terminalFrame("job_failed"),
  job_cancelled: terminalFrame("job_cancelled"),
  stream_timeout: timeoutFrame,
  unknown_frame: logFrame,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: suspendPage,
  page_restored: restorePage,
  reset: resetAll,
};

const unavailable: TransitionRow = {
  // "Ask the question again to start a new run" — the composer is
  // usable again, and using it is a new run, explicitly (H6).
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  detail_resolved: acceptDetail,
  detail_not_found: IGNORE,
  detail_unreachable: IGNORE,
  stream_opened: IGNORE,
  stream_interrupted: IGNORE,
  stream_failed: IGNORE,
  job_started: IGNORE,
  node_completed: IGNORE,
  plan_ready: IGNORE,
  job_completed: IGNORE,
  job_failed: IGNORE,
  job_cancelled: IGNORE,
  stream_timeout: IGNORE,
  unknown_frame: IGNORE,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: IGNORE,
  page_restored: IGNORE,
  reset: resetAll,
};

const live: TransitionRow = {
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  detail_resolved: acceptDetail,
  detail_not_found: missingDetail,
  // A failed poll is a failed poll. The stream is still open and the
  // run is still going; record it and keep streaming.
  detail_unreachable: on("detail_unreachable", (state, event) => ({
    ...state,
    failure: event.failure,
    failureMessage: event.message,
    failureStatus: event.status,
    failureSource: event.source === "poll" ? "poll" : "attach",
  })),
  stream_opened: openConnection,
  stream_interrupted: interrupt,
  stream_failed: failStream,
  job_started: logFrame,
  node_completed: checkpointFrame,
  plan_ready: planFrame,
  job_completed: terminalFrame("job_completed"),
  job_failed: terminalFrame("job_failed"),
  job_cancelled: terminalFrame("job_cancelled"),
  stream_timeout: timeoutFrame,
  unknown_frame: logFrame,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: suspendPage,
  page_restored: restorePage,
  reset: resetAll,
};

const awaitingReview: TransitionRow = {
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  detail_resolved: acceptDetail,
  detail_not_found: missingDetail,
  detail_unreachable: on("detail_unreachable", (state, event) => ({
    ...state,
    failure: event.failure,
    failureMessage: event.message,
    failureStatus: event.status,
    failureSource: event.source === "poll" ? "poll" : "attach",
  })),
  // Rule 2 applies here too: reopening while parked at the review does
  // reset the checkpoint. The plan does not go with it — it came from
  // `JobDetail.plan` or a replayed frame, not from this connection's
  // observations.
  stream_opened: openConnection,
  stream_interrupted: interrupt,
  stream_failed: failStream,
  job_started: logFrame,
  node_completed: checkpointFrame,
  plan_ready: planFrame,
  // `api_hitl_timeout_sec` fires here (`runner.py:1053-1057`).
  job_completed: terminalFrame("job_completed"),
  job_failed: terminalFrame("job_failed"),
  job_cancelled: terminalFrame("job_cancelled"),
  stream_timeout: timeoutFrame,
  unknown_frame: logFrame,
  review_requested: on("review_requested", (state, event) => ({
    ...cleared(state),
    review: { action: event.action, inFlight: true },
  })),
  // **A 200 does not mean resumed.** `ReviewResponse.status` is always
  // `pending_review` by design (`schemas.py:141-160`), so the machine
  // waits for an SSE frame or a poll rather than claiming progress.
  review_accepted: on("review_accepted", (state, event) => ({
    ...cleared(state),
    phase: "resolving",
    plan: null,
    review: { action: event.action, inFlight: false },
  })),
  // **409 means the truth moved**, not that something broke
  // (`routes.py:261-264`): another tab resolved it, or
  // `api_hitl_timeout_sec` fired. Refetch and re-render.
  review_conflict: on("review_conflict", (state, event) => ({
    ...state,
    phase: "attaching",
    review: null,
    failure: event.failure,
    failureMessage: event.message,
    failureStatus: event.status,
    failureSource: "review",
  })),
  review_rejected: on("review_rejected", (state, event) => ({
    ...state,
    review: null,
    failure: event.failure,
    failureMessage: event.message,
    failureStatus: event.status,
    failureSource: "review",
  })),
  page_hidden: suspendPage,
  page_restored: restorePage,
  reset: resetAll,
};

const resolving: TransitionRow = {
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  // "resolving ─ next SSE frame or poll ─► live | settled" (§4.2).
  detail_resolved: acceptDetail,
  detail_not_found: missingDetail,
  detail_unreachable: on("detail_unreachable", (state, event) => ({
    ...state,
    failure: event.failure,
    failureMessage: event.message,
    failureStatus: event.status,
    failureSource: event.source === "poll" ? "poll" : "attach",
  })),
  stream_opened: openConnection,
  stream_interrupted: interrupt,
  stream_failed: failStream,
  // The run resumed: the next frame is the proof, and it is what moves
  // the phase rather than the review's own 200.
  job_started: on("job_started", (state, event) => ({
    ...noteFrame(state, event.frame),
    phase: "live",
  })),
  node_completed: on("node_completed", (state, event) => ({
    ...observeCheckpoint(noteFrame(state, event.frame), event.frame),
    phase: "live",
  })),
  // The pause came back — another tab revised, or the runner re-asked.
  plan_ready: planFrame,
  job_completed: terminalFrame("job_completed"),
  job_failed: terminalFrame("job_failed"),
  job_cancelled: terminalFrame("job_cancelled"),
  stream_timeout: timeoutFrame,
  unknown_frame: logFrame,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: suspendPage,
  page_restored: restorePage,
  reset: resetAll,
};

const reconciling: TransitionRow = {
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  detail_resolved: acceptDetail,
  // The row aged out between the terminal frame and the read.
  detail_not_found: on("detail_not_found", (state, event) =>
    toUnavailable(
      state,
      "not_found",
      event.failure,
      event.message,
      event.status,
      "reconcile"
    )
  ),
  // The run IS over — the frame said so — but the values that describe
  // it could not be read. Settle with `detail: null` and the failure
  // recorded: no outcome is claimed from the frame's payload (H9).
  detail_unreachable: on("detail_unreachable", (state, event) => ({
    ...state,
    phase: "settled",
    connection: "closed",
    failure: event.failure,
    failureMessage: event.message,
    failureStatus: event.status,
    failureSource: "reconcile",
  })),
  // The stream was closed by the terminal handler. Anything arriving
  // on it now is the close itself echoing back.
  stream_opened: IGNORE,
  stream_interrupted: IGNORE,
  stream_failed: IGNORE,
  job_started: IGNORE,
  node_completed: IGNORE,
  plan_ready: IGNORE,
  job_completed: IGNORE,
  job_failed: IGNORE,
  job_cancelled: IGNORE,
  stream_timeout: IGNORE,
  unknown_frame: IGNORE,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: suspendPage,
  page_restored: restorePage,
  reset: resetAll,
};

const settled: TransitionRow = {
  submit_requested: startSubmission,
  submit_accepted: IGNORE,
  submit_rejected: IGNORE,
  attach_requested: startAttach,
  // A refresh of a settled job is fine and read-only.
  detail_resolved: acceptDetail,
  detail_not_found: IGNORE,
  detail_unreachable: IGNORE,
  // **Not a failure.** The terminal handler closed this stream itself,
  // and `readyState === CLOSED` is what that looks like. Treating it
  // as the fatal branch would overwrite a finished run with "stream
  // unavailable" and throw the report away.
  stream_opened: IGNORE,
  stream_interrupted: IGNORE,
  stream_failed: IGNORE,
  job_started: IGNORE,
  node_completed: IGNORE,
  plan_ready: IGNORE,
  job_completed: IGNORE,
  job_failed: IGNORE,
  job_cancelled: IGNORE,
  stream_timeout: IGNORE,
  unknown_frame: IGNORE,
  review_requested: IGNORE,
  review_accepted: IGNORE,
  review_conflict: IGNORE,
  review_rejected: IGNORE,
  page_hidden: IGNORE,
  page_restored: IGNORE,
  reset: resetAll,
};

/**
 * Phase × event, every cell decided.
 *
 * `Record<JobPhase, TransitionRow>` and `Record<JobEventType, …>` are
 * both total, so adding a phase or an event without deciding what it
 * does everywhere is a compile error rather than a silent no-op.
 */
export const TRANSITIONS: Record<JobPhase, TransitionRow> = {
  idle,
  submitting,
  submit_failed: submitFailed,
  attaching,
  unavailable,
  live,
  awaiting_review: awaitingReview,
  resolving,
  reconciling,
  settled,
};

// ---------------------------------------------------------------------------
// The reducer.
// ---------------------------------------------------------------------------

/**
 * Pure. One table lookup, no default branch.
 *
 * A cell of `IGNORE` returns the state object *identically*, so a
 * consumer comparing by reference sees no change at all — which is
 * what makes "deliberately inert" observable rather than merely
 * asserted.
 */
export function jobReducer(state: JobState, event: JobEvent): JobState {
  const cell = TRANSITIONS[state.phase][event.type];
  if (cell === null) return state;
  return cell(state, event);
}

/** `true` when this phase/event pair is a deliberate no-op. */
export function isIgnored(phase: JobPhase, type: JobEventType): boolean {
  return TRANSITIONS[phase][type] === null;
}

/** Every phase × event pair, for the table test. */
export function transitionMatrix(): Array<{
  phase: JobPhase;
  type: JobEventType;
  handled: boolean;
}> {
  return JOB_PHASES.flatMap((phase) =>
    JOB_EVENT_TYPES.map((type) => ({
      phase,
      type,
      handled: TRANSITIONS[phase][type] !== null,
    }))
  );
}

// ---------------------------------------------------------------------------
// Selectors.
// ---------------------------------------------------------------------------

/** Nothing more is expected from the server in this phase. */
export function isSettledPhase(phase: JobPhase): boolean {
  return SETTLED_PHASES.has(phase);
}

/** The liveness poll runs only while a job is on screen and unfinished. */
export function shouldPoll(state: JobState): boolean {
  return (
    state.jobId !== null &&
    state.phase !== "idle" &&
    state.phase !== "submitting" &&
    !isSettledPhase(state.phase) &&
    !state.suspended
  );
}

/**
 * The checkpoint's label, or the sentinel `"unknown"` for its absence.
 *
 * **NOT RENDERABLE COPY, AND NOT A ROUTE FOR IT.** 03 §5.5 requires "not
 * reported" rather than "unknown" wherever the API is simply silent, and
 * `web/tests/copy/forbidden.test.ts` bans the word outright. This helper
 * predates WO-12's dictionary and survives as a *diagnostic* — the string
 * `web/tests/job/checkpoint.test.ts` and `web/tests/job/stream.test.ts`
 * assert the absent case with. Changing its sentinel would edit those
 * suites, which is why the fix went the other way:
 * `observedNode()` below exposes the raw absence, and a surface turns that
 * into text with `checkpointName()` from `lib/copy/run`. WO-15's spine
 * calls `observedNode`; nothing renders `checkpointLabel`.
 */
export function checkpointLabel(state: JobState): string {
  return state.checkpoint?.node ?? "unknown";
}

/**
 * The last observed checkpoint's label **verbatim**, or `null` for absent.
 *
 * The raw-absent state rather than a stand-in string, so the module that
 * owns wording decides what absence reads as: `checkpointName(null)` is
 * "not reported" (03 §5.5), and no other spelling of it exists. The label
 * itself is passed through untouched (H11) — there is no vocabulary to
 * check it against.
 */
export function observedNode(state: JobState): string | null {
  return state.checkpoint?.node ?? null;
}

/**
 * `true` only while the checkpoint describes the connection we are on.
 *
 * The moment a connection ends, the last checkpoint stops being a
 * statement about *now* and becomes a statement about a connection
 * that is over. Consumers use this to say "checkpoints during the gap
 * are not replayed" instead of implying the run is still there.
 */
export function checkpointIsCurrent(state: JobState): boolean {
  return state.connection === "open" && state.checkpoint !== null;
}

// ---------------------------------------------------------------------------
// Copy.
//
// WO-12 owns the product's copy dictionary, and has now taken the
// wording: `UNAVAILABLE_COPY` and every phrase `terminalPhrase()` can
// return live in `web/lib/copy/run.ts`, which is the single edit site
// criterion 1 requires. The deny-list and the `/^failed( after
// [^\s]+)?$/` allow-list travelled with them to
// `web/tests/copy/forbidden.test.ts`; `web/tests/job/terminal.test.ts`
// keeps driving them from this reducer, unchanged, because the rule
// being provable from the state machine is why they were written here
// in the first place.
//
// The dependency is one-directional: machine → copy, never the reverse.
// Copy has no state and the machine has no wording.
// ---------------------------------------------------------------------------

/**
 * §5.4: the 404 sentence. Never "deleted", never "no permission" (H8).
 *
 * Re-exported rather than re-declared so existing importers
 * (`web/tests/job/attach.test.ts`) keep their import path while the
 * string itself has exactly one home.
 */
export const UNAVAILABLE_COPY = COPY_UNAVAILABLE;

/**
 * The terminal phrase, and the only sanctioned way to describe a
 * finished run's outcome.
 *
 * "failed after <checkpoint>" when one was observed on the connection
 * that ended, plain "failed" otherwise. **Never "failed in <node>"**:
 * no terminal payload carries a node — not the live failure
 * (`runner.py:1063-1072`) and not the replay (`routes.py:857-867`) —
 * so any preposition that attributes the failure *to* a stage is an
 * invention. The checkpoint is the last thing that was seen to
 * complete, which is a different and true claim.
 *
 * Returns `null` when the run is not over.
 */
export function terminalPhrase(state: JobState): string | null {
  if (state.phase === "unavailable") return TERMINAL_PHRASE.unavailable;
  if (state.phase === "submit_failed") return TERMINAL_PHRASE.notStarted;
  if (state.phase !== "settled") return null;

  // H9: the outcome comes from `GET /research/{id}`. Only when that
  // read itself failed do we fall back to the terminal frame's *name*
  // — never to its payload.
  const outcome = state.detail?.status ?? terminalNameFallback(state);
  switch (outcome) {
    case "succeeded":
      return TERMINAL_PHRASE.succeeded;
    case "cancelled":
      return TERMINAL_PHRASE.cancelled;
    case "failed":
      return failedPhrase(state.checkpoint?.node ?? null);
    default:
      // A terminal frame arrived, the read failed, and no name is
      // available either. Say only what is known.
      return TERMINAL_PHRASE.finished;
  }
}

function terminalNameFallback(state: JobState): string | null {
  switch (state.terminal?.name) {
    case "job_completed":
      // The live frame carries no `status` (`runner.py:1278-1288`), so
      // "completed" here means "the run stopped", not "it succeeded".
      // H9 forbids claiming success without the GET.
      return null;
    case "job_failed":
      return "failed";
    case "job_cancelled":
      return "cancelled";
    default:
      return null;
  }
}
