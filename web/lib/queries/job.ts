"use client";

// Job detail and the plan-review mutation (04-ARCHITECTURE.md §4.4,
// §4.5).
//
// Two contract facts shape this file, and both are places where the
// obvious implementation would lie to the user:
//
//   A 200 from `POST /research/{id}/review` does **not** mean the run
//   resumed. `ReviewResponse.status` is always `pending_review`
//   (`schemas.py:141-160`) because the runner applies the action after
//   the response is written. So the outcome type carries `resumed: false`
//   on every branch and there is no branch that could say otherwise.
//
//   A 409 is not a failure. `job_not_awaiting_review`
//   (`routes.py:261-264`) means the truth moved — another tab resolved
//   the review, or `api_hitl_timeout_sec` fired (`src/config.py:354`).
//   The right response is to refetch the job and re-render, so the
//   conflict resolves to a `"stale"` outcome instead of throwing. The
//   mutation never enters an error state for it, and nothing shouts.
//
// **This module does not submit jobs.** `POST /research` is not here and
// is not a mutation anywhere (H6, R-01); it belongs to the job machine's
// guarded plain function in `web/lib/job/`.

import { useRef } from "react";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  ApiError,
  getJob,
  reviewPlan,
  type ApiFailure,
  type JobDetail,
  type JobStatus,
  type ReviewRequest,
  type ReviewResponse,
} from "@/lib/api/index";

import { mutationKeys, queryKeys } from "./keys";

// ---------------------------------------------------------------------------
// The liveness poll (§4.4).
// ---------------------------------------------------------------------------

/** Statuses after which nothing more will happen to the job. */
export const TERMINAL_JOB_STATUSES: readonly JobStatus[] = [
  "succeeded",
  "failed",
  "cancelled",
];

export function isTerminalJobStatus(status: JobStatus): boolean {
  return TERMINAL_JOB_STATUSES.includes(status);
}

export const JOB_POLL_INTERVAL_MS = 20_000;
export const JOB_POLL_SLOW_INTERVAL_MS = 60_000;
export const JOB_POLL_BACKOFF_AFTER = 5;

/**
 * How long to wait before the next poll.
 *
 * SSE heartbeats are comments (`streaming.py:142`) and invisible to
 * `EventSource`, so a client cannot tell an idle stream from a dead one.
 * This poll is the safety net. It backs off after five polls that
 * changed nothing, because at that point the stream is probably fine and
 * the poll is just traffic. It is read-only and costs no model spend.
 */
export function jobPollIntervalMs(unchangedPolls: number): number {
  return unchangedPolls >= JOB_POLL_BACKOFF_AFTER
    ? JOB_POLL_SLOW_INTERVAL_MS
    : JOB_POLL_INTERVAL_MS;
}

/** What the hook remembers between polls. */
export interface JobPollTracker {
  seen: JobDetail | undefined;
  polls: number;
}

/**
 * The whole poll decision, as a pure function of the last response and
 * the tracker — so it is testable without a timer, a cache or a clock.
 *
 * "Unchanged" is reference identity, not a deep comparison: TanStack's
 * structural sharing keeps `data` referentially stable across a fetch
 * that returned the same payload, so `===` is exactly the question
 * "did this poll learn anything?".
 */
export function jobRefetchInterval(
  data: JobDetail | undefined,
  tracker: JobPollTracker
): number | false {
  if (data === undefined) return JOB_POLL_INTERVAL_MS;
  if (isTerminalJobStatus(data.status)) return false;
  if (data === tracker.seen) tracker.polls += 1;
  else {
    tracker.seen = data;
    tracker.polls = 0;
  }
  return jobPollIntervalMs(tracker.polls);
}

export interface JobDetailOptions {
  /**
   * Run the liveness poll while the job is non-terminal. The job machine
   * turns this on for a live run and off once the job settles.
   */
  poll?: boolean;
  enabled?: boolean;
}

/**
 * `GET /research/{id}` — free, read-only (`routes.py:215-232`), and the
 * source of every displayed value (H9).
 */
export function useJobDetail(
  jobId: string | null,
  options: JobDetailOptions = {}
): UseQueryResult<JobDetail, Error> {
  const tracker = useRef<JobPollTracker>({ seen: undefined, polls: 0 });

  return useQuery({
    queryKey: queryKeys.jobs.detail(jobId ?? ""),
    queryFn: ({ signal }) => getJob(jobId as string, { signal }),
    enabled: jobId !== null && (options.enabled ?? true),
    refetchInterval:
      options.poll === true
        ? (query) => jobRefetchInterval(query.state.data, tracker.current)
        : false,
  });
}

// ---------------------------------------------------------------------------
// Plan review (§4.5).
// ---------------------------------------------------------------------------

/**
 * What a review attempt produced.
 *
 * `resumed` is `false` on **both** branches and is typed as the literal
 * `false`, so no caller can render "resumed" off the back of a 200. The
 * run resumes when an SSE frame or a poll says it did.
 */
export type ReviewOutcome =
  | { kind: "accepted"; resumed: false; response: ReviewResponse }
  | { kind: "stale"; resumed: false; failure: ApiFailure };

/** The 409 branch, for a caller that wants to narrow without a switch. */
export function isStaleReview(outcome: ReviewOutcome): boolean {
  return outcome.kind === "stale";
}

/**
 * Resolve the review pause.
 *
 * `approve` resumes billable work, so this is `retry: false` and
 * `networkMode: "always"` (the client default): an offline attempt fails
 * where the user can see it rather than being replayed later.
 *
 * Both outcomes invalidate the job so the next render comes from the
 * server's truth rather than from an assumption about what the review
 * did.
 */
export function useReviewPlan(
  jobId: string
): UseMutationResult<ReviewOutcome, Error, ReviewRequest> {
  const queryClient = useQueryClient();

  return useMutation<ReviewOutcome, Error, ReviewRequest>({
    mutationKey: mutationKeys.jobs.review(),
    retry: false,
    mutationFn: async (body) => {
      try {
        const response = await reviewPlan(jobId, body);
        // 200. The job is still `pending_review` on the wire; the
        // machine moves to `resolving` and waits.
        return { kind: "accepted", resumed: false, response };
      } catch (error) {
        if (error instanceof ApiError && error.failure.kind === "conflict") {
          return { kind: "stale", resumed: false, failure: error.failure };
        }
        throw error;
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.jobs.detail(jobId),
      });
    },
  });
}
