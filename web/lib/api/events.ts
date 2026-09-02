// SSE overlay — HAND-WRITTEN BY DESIGN, and pinned by WO-04.
//
// The stream is not described by the OpenAPI document: the snapshot in
// `web/contract/openapi.json` types `GET /research/{job_id}/stream` as
// an untyped 200 with no schema. Generating types without this overlay
// would produce exactly the false confidence risk R-06 names, so every
// shape below is transcribed by hand from the backend and cited.
//
// Wire format: `event:` + `data:` JSON, no `id:` line
// (`src/api/streaming.py:117-132`). The authoritative event list is the
// module docstring at `src/api/streaming.py:13-35`.
//
// Invariants the client must obey (04-ARCHITECTURE.md §3.2):
//   - The report body NEVER arrives over SSE. Every terminal frame is
//     reconciled with `GET /research/{job_id}`.
//   - There is no replay backlog and no `Last-Event-ID` contract; Redis
//     pub/sub drops messages with no subscriber (`routes.py:444-454`).
//   - `plan_ready` may arrive twice (`routes.py:456-462`); handlers must
//     be idempotent.
//   - Unknown event names and unknown `state_delta` keys must be
//     tolerated. Node names are opaque strings.

import type { Plan } from "./models";

// ---------------------------------------------------------------------------
// Names.
// ---------------------------------------------------------------------------

/**
 * Names the consuming UI dispatches on today.
 *
 * This is the union the M0 compatibility shim exports, and it mixes
 * two sources: six real server events plus `stream_note` and `error`,
 * which are client-side transport notes the stream hook synthesizes.
 * Kept byte-identical to the superseded `web/lib/types.ts` so M0 stays
 * behaviour-neutral — `components/EventLog.tsx:10` keys an exhaustive
 * `Record<SseEventName, string>` off it.
 */
export type SseEventName =
  | "job_started"
  | "node_completed"
  | "plan_ready"
  | "turn_ready"
  | "job_completed"
  | "job_failed"
  | "job_cancelled"
  | "stream_note"
  | "error";

/**
 * The names the server actually emits, additive to `SseEventName`.
 *
 * Note `stream_timeout` (`src/api/streaming.py:300-308`), which the
 * current UI does not listen for — it is a server-generated transport
 * event, **not** a job outcome (`streaming.py:108-114`). M2 adds the
 * listener; this constant is the contract WO-04 pins on both sides.
 */
export const SERVER_EVENT_NAMES = [
  "job_started",
  "node_completed",
  "plan_ready",
  "turn_ready",
  "job_completed",
  "job_failed",
  "job_cancelled",
  "stream_timeout",
] as const;

export type ServerSseEventName = (typeof SERVER_EVENT_NAMES)[number];

/** `src/api/streaming.py:75`. */
export const STREAM_TIMEOUT_EVENT = "stream_timeout";

/** Names synthesized by the client, never seen on the wire. */
export const CLIENT_EVENT_NAMES = ["stream_note", "error"] as const;

/**
 * Terminal job outcomes, pinned server-side at
 * `src/api/streaming.py:89-103`. `stream_timeout` is deliberately
 * absent: the stream ended, the job did not.
 */
export const TERMINAL_EVENTS: ReadonlySet<SseEventName> = new Set<SseEventName>(
  ["job_completed", "job_failed", "job_cancelled"]
);

// ---------------------------------------------------------------------------
// Frames.
// ---------------------------------------------------------------------------

/** One received frame, in receive order. */
export interface SseEvent {
  name: SseEventName;
  data: Record<string, unknown> | null;
  receivedAt: number;
}

/** `src/api/runner.py:986-990`. Not replayed on attach. */
export interface JobStartedPayload {
  job_id: string;
  query: string;
}

/**
 * `src/api/runner.py:952-956`. Not replayed, and there is no backlog:
 * a reconnect cannot reconstruct missed frames.
 *
 * `state_delta` is filtered to scalars with `messages` dropped
 * (`runner.py:947-951`) but is otherwise open-ended, and `node` is an
 * opaque string — no fixed vocabulary may be assumed.
 */
export interface NodeCompletedPayload {
  node: string;
  state_delta: Record<string, unknown>;
}

/**
 * `src/api/runner.py:409-414`; replayed byte-identically on attach when
 * the job is `pending_review` (`routes.py:463-464`, `routes.py:838-854`).
 */
export interface PlanReadyPayload {
  job_id: string;
  plan: Plan;
}

/** Live terminal frame, `src/api/runner.py:1278-1288`. No `status`. */
export interface JobCompletedPayload {
  job_id: string;
  iterations: number | null;
  quality_score: number | null;
  cost_usd: number | null;
  llm_calls: number | null;
  elapsed_sec: number | null;
}

/** Live terminal frame, `src/api/runner.py:1063-1072` and siblings. */
export interface JobFailedPayload {
  job_id: string;
  error: string;
  error_type: string;
  elapsed_sec: number | null;
}

/**
 * Live terminal frame, `src/api/runner.py:1128-1135` (`reason:
 * "hitl_cancelled"`) and `runner.py:1196-1199` (no `reason`).
 */
export interface JobCancelledPayload {
  job_id: string;
  elapsed_sec: number | null;
  reason?: string;
}

/**
 * Attach-time replay of a terminal outcome, `src/api/routes.py:857-867`.
 *
 * Deliberately a different shape from the live frames above: it adds
 * `status` and drops `llm_calls`. Reconciling through
 * `GET /research/{job_id}` is what makes the difference invisible.
 */
export interface TerminalReplayPayload {
  job_id: string;
  status: string;
  elapsed_sec: number | null;
  error: string | null;
  error_type: string | null;
  iterations: number | null;
  quality_score: number | null;
  cost_usd: number | null;
}

/**
 * `src/api/streaming.py:300-308`. The stream hit its duration ceiling;
 * the job keeps running and the client should reconnect.
 */
export interface StreamTimeoutPayload {
  job_id: string;
  reason: string;
  max_duration_sec: number;
  reconnect: boolean;
}
