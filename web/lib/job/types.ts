// The job lifecycle machine's vocabulary (04-ARCHITECTURE.md §4.2).
//
// Two words that are easy to conflate live in this file, so they are
// named apart on purpose:
//
//   - **phase** (`JobPhase`) is the *machine's* state name — `idle`,
//     `attaching`, `live`, `settled`. It is client-side only.
//   - **status** (`JobStatus`, from `lib/api`) is the *server's* job
//     status — `pending`, `running`, `pending_review`, `succeeded`,
//     `failed`, `cancelled`. It is truth, and it arrives only from
//     `GET /research/{job_id}`.
//
// Keeping them apart is not cosmetic: checkpoint rule 4
// (04-ARCHITECTURE.md §4.4) is precisely "the checkpoint is never
// derived from `JobDetail`", and a single overloaded `status` field is
// how that rule gets broken by accident.

import type {
  ApiFailure,
  JobDetail,
  JobStatus,
  Plan,
  ReviewAction,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Phases.
// ---------------------------------------------------------------------------

/**
 * Every state in 04-ARCHITECTURE.md §4.2's diagram, in the order the
 * diagram walks them.
 *
 * `submit_failed` is terminal *for that attempt only* — retrying is a
 * new run, never an automatic one (H6, R-01). `unavailable` is the
 * honest 404 landing: "no longer available", never "deleted" and never
 * "no permission" (H8).
 */
export const JOB_PHASES = [
  "idle",
  "submitting",
  "submit_failed",
  "attaching",
  "unavailable",
  "live",
  "awaiting_review",
  "resolving",
  "reconciling",
  "settled",
] as const;

export type JobPhase = (typeof JOB_PHASES)[number];

/**
 * Phases in which no further server work is expected, so the liveness
 * poll stops and the stream is closed.
 *
 * `idle` is not here: nothing has started, so there is nothing to stop.
 */
export const SETTLED_PHASES: ReadonlySet<JobPhase> = new Set<JobPhase>([
  "submit_failed",
  "unavailable",
  "settled",
]);

/** Server job statuses that mean the run is over (`schemas.py:98-124`). */
export const TERMINAL_JOB_STATUSES: ReadonlySet<JobStatus> =
  new Set<JobStatus>(["succeeded", "failed", "cancelled"]);

// ---------------------------------------------------------------------------
// Connection.
// ---------------------------------------------------------------------------

/**
 * What the `EventSource` is doing.
 *
 * `reconnecting` is the browser's own retry (`readyState === CONNECTING`
 * after an `error`), which the client cannot influence and must only
 * narrate. It is separate from `closed`, which is a close *we* asked
 * for — a terminal frame, `pagehide`, or unmount.
 */
export const CONNECTION_PHASES = [
  "closed",
  "opening",
  "open",
  "reconnecting",
] as const;

export type ConnectionPhase = (typeof CONNECTION_PHASES)[number];

// ---------------------------------------------------------------------------
// Observations.
// ---------------------------------------------------------------------------

/**
 * One `node_completed` frame, observed on the currently-open stream.
 *
 * `node` is copied verbatim out of the payload and is an opaque string
 * (H11): there is no fixed node vocabulary, the graph is
 * configuration-dependent, and `state_delta` is an open scalar map
 * (`runner.py:947-956`).
 */
export interface ObservedCheckpoint {
  node: string;
  /** Client receive time. The frame carries no timestamp. */
  observedAt: number;
  /** Passed through untouched; unknown keys are tolerated, never parsed. */
  stateDelta: Record<string, unknown>;
}

/** One received frame, in receive order. Unknown names included. */
export interface JobFrame {
  name: string;
  data: Record<string, unknown> | null;
  receivedAt: number;
}

/**
 * A terminal frame, reduced to the only three things it may contribute.
 *
 * **No payload value is ever copied out of a terminal frame** (H9).
 * One event name has three shapes — live `job_completed` has
 * `llm_calls` and no `status` (`runner.py:1278-1288`), the attach-time
 * replay has `status` and no `llm_calls` (`routes.py:857-867`), and
 * live `job_cancelled` carries `reason` at `runner.py:1128-1135` but
 * not at `runner.py:1196-1199`. Treating all three as a *signal to go
 * and read `GET /research/{id}`* is what makes the asymmetry
 * invisible, and it is the only reading that cannot be wrong.
 *
 * `shape` is recorded for the diagnostics disclosure (WO-16) and is
 * never rendered as a value.
 */
export interface TerminalSignal {
  name: "job_completed" | "job_failed" | "job_cancelled";
  shape: "live" | "replay";
  receivedAt: number;
}

/** Which read produced a `JobDetail`. Only `poll` moves the backoff. */
export type DetailSource = "attach" | "reconcile" | "poll" | "refresh";

/** Why the run is `unavailable`. Both render the same sentence (H8). */
export type UnavailableReason = "not_found" | "stream_failed";

/** Which call failed, so a consumer can pick the right sentence. */
export type FailureSource =
  | "submit"
  | "attach"
  | "reconcile"
  | "poll"
  | "stream"
  | "review";

/** An in-flight `POST /research`, held only while it is in flight. */
export interface Submission {
  /**
   * The single-use guard against R-01.
   *
   * `submit_accepted` / `submit_rejected` are ignored unless they carry
   * the token of the submission still in flight, so a late or duplicated
   * response can never adopt a job the user did not ask for twice.
   */
  token: string;
  query: string;
  conversationId: string | null;
  startedAt: number;
}

/** An in-flight `POST /research/{id}/review`. */
export interface ReviewState {
  action: ReviewAction;
  inFlight: boolean;
}

// ---------------------------------------------------------------------------
// State.
// ---------------------------------------------------------------------------

/**
 * The whole of the machine's state. Serializable, and produced only by
 * `jobReducer` — no field here is written from anywhere else.
 */
export interface JobState {
  phase: JobPhase;
  /** The job on screen. The URL's `?job=` is the only persisted handle. */
  jobId: string | null;
  /**
   * The last `GET /research/{id}` body.
   *
   * **The only source of displayed values** (H9). `null` means the
   * status is genuinely unknown — say so rather than guessing.
   */
  detail: JobDetail | null;
  /** From `JobDetail.plan` or a `plan_ready` frame, whichever came first. */
  plan: Plan | null;
  /**
   * The last checkpoint observed **on the currently-open stream**, or
   * `null` for unknown. Governed by the four rules in
   * 04-ARCHITECTURE.md §4.4; see `machine.ts`.
   */
  checkpoint: ObservedCheckpoint | null;
  /** Every checkpoint on this connection, in order. Reset on every open. */
  observed: ObservedCheckpoint[];
  connection: ConnectionPhase;
  /** Receive-ordered frame log, capped at `MAX_FRAMES`. */
  frames: JobFrame[];
  /** Set by a terminal frame; cleared by nothing. A signal, not a value. */
  terminal: TerminalSignal | null;
  /** Normalized failure of the most recent failed call. */
  failure: ApiFailure | null;
  /** That call's thrown message, as thrown. Disclosure and legacy copy. */
  failureMessage: string | null;
  /**
   * The HTTP status of that call, or `null` when there was no response
   * at all (offline, timeout, abort). Kept separately from `failure`
   * because three `ApiFailure` variants have no `status` field by
   * construction, and the diagnostics disclosure wants the number.
   */
  failureStatus: number | null;
  failureSource: FailureSource | null;
  unavailableReason: UnavailableReason | null;
  submission: Submission | null;
  review: ReviewState | null;
  /** Consecutive liveness polls that changed nothing. Drives the backoff. */
  unchangedPolls: number;
  /** `detailSignature()` of `detail`, so "unchanged" is comparable. */
  detailSignature: string | null;
  /** Receive time of the newest frame — §5.4's "updated 41 s ago". */
  lastFrameAt: number | null;
  /** When the current connection opened. Reset with the checkpoint. */
  connectionOpenedAt: number | null;
  /** True between `pagehide` and the re-attach `pageshow` starts (RC-18). */
  suspended: boolean;
}

// ---------------------------------------------------------------------------
// Events.
// ---------------------------------------------------------------------------

/**
 * Every event the reducer accepts.
 *
 * The seven server frame names each get their own event rather than one
 * `frame` event with a name inside it, so the transition table in
 * `machine.ts` is exhaustive over the SSE vocabulary too and
 * `web/tests/job/machine.test.ts` can walk it as a real table.
 * `unknown_frame` is the eighth: the browser drops named events nobody
 * registered for, so it is only reachable through an *unnamed*
 * `message` frame, which is where a future server event would land.
 */
export const JOB_EVENT_TYPES = [
  // Submission — 04-ARCHITECTURE.md §4.1, H6, R-01.
  "submit_requested",
  "submit_accepted",
  "submit_rejected",
  // Attach — §4.3.
  "attach_requested",
  "detail_resolved",
  "detail_not_found",
  "detail_unreachable",
  // Connection — §4.4.
  "stream_opened",
  "stream_interrupted",
  "stream_failed",
  // Frames — §3.2, `streaming.py:13-35`.
  "job_started",
  "node_completed",
  "plan_ready",
  "job_completed",
  "job_failed",
  "job_cancelled",
  "stream_timeout",
  "unknown_frame",
  // Plan review — §4.5.
  "review_requested",
  "review_accepted",
  "review_conflict",
  "review_rejected",
  // Page lifecycle — RC-18.
  "page_hidden",
  "page_restored",
  // Provider.
  "reset",
] as const;

export type JobEventType = (typeof JOB_EVENT_TYPES)[number];

/** The frame events, in `SERVER_EVENT_NAMES` order plus the catch-all. */
export const FRAME_EVENT_TYPES = [
  "job_started",
  "node_completed",
  "plan_ready",
  "job_completed",
  "job_failed",
  "job_cancelled",
  "stream_timeout",
  "unknown_frame",
] as const;

export type FrameEventType = (typeof FRAME_EVENT_TYPES)[number];

/**
 * One member per frame name.
 *
 * Written as a distributed mapped type rather than
 * `{ type: FrameEventType; frame: JobFrame }` so each name is its own
 * union member and `Extract<JobEvent, { type: "plan_ready" }>` narrows
 * to something usable.
 */
export type FrameEvent = {
  [K in FrameEventType]: { type: K; frame: JobFrame };
}[FrameEventType];

export type JobEvent =
  | {
      type: "submit_requested";
      token: string;
      query: string;
      conversationId: string | null;
      at: number;
    }
  | { type: "submit_accepted"; token: string; jobId: string; at: number }
  | {
      type: "submit_rejected";
      token: string;
      failure: ApiFailure | null;
      message: string;
      status: number | null;
      at: number;
    }
  | {
      type: "attach_requested";
      jobId: string;
      /**
       * `true` issues `GET /research/{id}` first and lands in
       * `attaching` (§4.3). `false` is the legacy stream-first path
       * kept alive for `useResearchStream`; see `useJobStream.ts`.
       */
      prefetch: boolean;
      at: number;
    }
  | {
      type: "detail_resolved";
      detail: JobDetail;
      source: DetailSource;
      at: number;
    }
  | {
      type: "detail_not_found";
      jobId: string;
      failure: ApiFailure | null;
      message: string;
      status: number | null;
      source: DetailSource;
      at: number;
    }
  | {
      type: "detail_unreachable";
      jobId: string;
      failure: ApiFailure | null;
      message: string;
      status: number | null;
      source: DetailSource;
      at: number;
    }
  | { type: "stream_opened"; jobId: string; at: number }
  | { type: "stream_interrupted"; jobId: string; at: number }
  | { type: "stream_failed"; jobId: string; at: number }
  | FrameEvent
  | { type: "review_requested"; action: ReviewAction; at: number }
  | { type: "review_accepted"; action: ReviewAction; at: number }
  | {
      type: "review_conflict";
      failure: ApiFailure | null;
      message: string;
      status: number | null;
      at: number;
    }
  | {
      type: "review_rejected";
      failure: ApiFailure | null;
      message: string;
      status: number | null;
      at: number;
    }
  | { type: "page_hidden"; at: number }
  | { type: "page_restored"; at: number }
  | { type: "reset"; at: number };

/** Narrow `JobEvent` to one member by its `type`. */
export type JobEventOf<T extends JobEventType> = Extract<JobEvent, { type: T }>;

// ---------------------------------------------------------------------------
// The client seam.
// ---------------------------------------------------------------------------

/**
 * Everything the machine calls over the network.
 *
 * Injectable for two reasons. First, it is the seam WO-11 integrates
 * against: the query layer can supply a `getJob` that reads through its
 * cache without the machine knowing a cache exists. Second, it is how
 * every test in `web/tests/job/` avoids `POST /research` entirely — the
 * one non-idempotent, potentially billable call on the surface.
 *
 * `submitResearch` stays a plain function on this interface and is
 * *never* a query-library mutation: `networkMode: "online"` pauses a
 * mutation while offline and resumes it on reconnect, which is an
 * automatic replay of a paid submission (R-01, H6).
 */
export interface JobClient {
  getJob: (jobId: string) => Promise<JobDetail>;
  submitResearch: (
    query: string,
    options: { conversation_id?: string }
  ) => Promise<{ job_id: string }>;
  reviewPlan: (
    jobId: string,
    body: { action: ReviewAction; plan?: Plan }
  ) => Promise<unknown>;
  streamUrl: (jobId: string) => string;
}

export type { ApiFailure, JobDetail, JobStatus, Plan, ReviewAction };
