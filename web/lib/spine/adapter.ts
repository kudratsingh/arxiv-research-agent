// The adapter: `JobState` → 03 §5.2's four inputs (WO-15).
//
// THIS IS THE ONLY PLACE THE SPINE'S INPUTS ARE READ OUT OF THE MACHINE,
// and it is deliberately NOT part of `lib/spine/state.ts`. Everything the
// machine knows that is not one of the four inputs stops here: the frame
// log, the failure fields, the poll bookkeeping, the submission token, the
// review state. A reviewer who wants to check "does the spine read anything
// it may not?" reads one 90-line file.
//
// IT IS ALSO A COVERAGE BOUNDARY, and that is not incidental.
// `web/vitest.config.mts` records the measurement hazard in full: a module
// loaded by BOTH the `unit` and `storybook` projects has its function list
// CONCATENATED in the merged report, so a story that drags in a module it
// only partly exercises inflates the denominator for free. This file is
// the one that imports `lib/job/machine` and `lib/api`'s runtime — a
// reducer with a hundred transition closures and a whole HTTP client — so
// keeping it out of `state.ts` keeps it out of every story's module graph.
// The stories import `lib/spine/state`; nothing in Storybook loads this.

import { STREAM_TIMEOUT_EVENT } from "@/lib/api";
import { checkpointIsCurrent } from "@/lib/job/machine";
import type { JobState } from "@/lib/job/types";

import type { SpineConnection, SpineInputs, SpineStatus } from "./state";

/** The newest frame's name, or `null`. One read, for one distinction. */
function lastFrameName(state: JobState): string | null {
  return state.frames[state.frames.length - 1]?.name ?? null;
}

/**
 * What the EventSource is doing, in the spine's vocabulary.
 *
 * `recycled` and `reconnecting` are indistinguishable at the transport —
 * the browser reconnects either way — so the discriminator is the frame the
 * server sent first. `stream_timeout` means the server hit
 * `api_sse_max_duration_sec` and the RUN did not stop
 * (`streaming.py:300-308`), which is a different sentence from a dropped
 * socket and the only reason the two are separate rows in 03 §5.4.
 */
function connectionOf(state: JobState): SpineConnection {
  if (state.connection === "open") return "open";
  if (state.connection === "reconnecting") {
    return lastFrameName(state) === STREAM_TIMEOUT_EVENT ? "recycled" : "reconnecting";
  }
  return "closed";
}

/** Input 1, out of the phase and the last `GET /research/{id}`. */
function statusOf(state: JobState): SpineStatus {
  if (state.phase === "submitting") return "submitting";
  if (state.phase === "unavailable") return "unavailable";
  // H9: the outcome comes from the GET, never from a terminal frame's
  // payload. `null` when that read has not landed — say nothing, honestly.
  return state.detail?.status ?? null;
}

/**
 * The four inputs, or `null` when there is no run on screen at all.
 *
 * `null` is not a thirteenth state: it is the absence of one. The composer
 * renders an inert spine for it (03 §1.4's four-word process legend is the
 * same shape), and nothing about a run is claimed.
 *
 * `now` is passed in rather than read, so this stays pure and a story can
 * pin "updated 41s ago" without faking a clock. `null` means "do not age
 * anything", which is what a static story wants.
 */
export function spineInputs(
  state: JobState,
  now: number | null = null,
): SpineInputs | null {
  const status = statusOf(state);
  if (status !== "submitting" && state.jobId === null) return null;

  const elapsed =
    now === null || state.lastFrameAt === null
      ? null
      : Math.max(0, Math.round((now - state.lastFrameAt) / 1000));

  return {
    status,
    observation: {
      checkpoints: state.observed,
      connection: connectionOf(state),
      // WO-10 built `checkpointIsCurrent` for 03 §5.4's reconnect row: it
      // is false the moment a connection ends, which is precisely how the
      // ledger keeps its ticks without the spine claiming they are now.
      current: checkpointIsCurrent(state),
    },
    plan: state.plan,
    secondsSinceLastFrame: elapsed,
  };
}
