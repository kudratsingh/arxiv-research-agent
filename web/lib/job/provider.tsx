"use client";

// `JobRunProvider` — one machine per route instance
// (04-ARCHITECTURE.md §4.1).
//
// The machine is per-route state, not application state: there is
// exactly one job on screen, and it is named by the URL's `?job=`. So
// this is a context over a `useReducer`, not a global store.
//
// The provider adds three things to `useJobStream`:
//
//   1. **The liveness poll** (§4.4). Heartbeats are SSE *comments*
//      (`streaming.py:142`) and are invisible to `EventSource`, so a
//      client cannot tell an idle stream from a dead one. While the
//      job is non-terminal the job detail is re-read every 20 s,
//      backing off to 60 s after five polls that changed nothing.
//      Read-only; no model spend.
//   2. **URL adoption.** Give it the `?job=` value and it attaches,
//      re-attaches when the value changes, and never POSTs.
//   3. **A subscribe/getSnapshot seam** so a consumer outside React's
//      render path — WO-11's query layer, in particular — can observe
//      the machine without the provider having to know it exists.
//
// It deliberately does NOT own the poll through TanStack Query. WO-11
// adds that library and will integrate against the seam below;
// `refetchInterval` is one line there, but it cannot be this work
// order's line, and adding a dependency here would put the machine's
// correctness downstream of a package that is still in flight.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
} from "react";
import type { ReactNode } from "react";

import type { JobDetail, Plan, ReviewAction } from "@/lib/api";

import { shouldPoll } from "./machine";
import { useJobStream } from "./useJobStream";
import type {
  AttachMode,
  JobStreamControls,
  SubmitOptions,
} from "./useJobStream";
import type { JobClient, JobState } from "./types";

// ---------------------------------------------------------------------------
// The liveness poll.
// ---------------------------------------------------------------------------

export interface LivenessPollOptions {
  /** §4.4's `refetchInterval: 20_000`. */
  intervalMs: number;
  /** What it backs off to. */
  backoffIntervalMs: number;
  /** How many unchanged polls trigger the backoff. */
  backoffAfterUnchanged: number;
  /** `false` disables the poll entirely (Storybook, some tests). */
  enabled: boolean;
}

export const DEFAULT_POLL: LivenessPollOptions = {
  intervalMs: 20_000,
  backoffIntervalMs: 60_000,
  backoffAfterUnchanged: 5,
  enabled: true,
};

/** The interval this state's poll should use next. */
export function pollIntervalFor(
  state: JobState,
  options: LivenessPollOptions = DEFAULT_POLL
): number {
  return state.unchangedPolls >= options.backoffAfterUnchanged
    ? options.backoffIntervalMs
    : options.intervalMs;
}

// ---------------------------------------------------------------------------
// Context.
// ---------------------------------------------------------------------------

export interface JobRunContextValue {
  /** The machine's state. Everything renderable comes from here. */
  state: JobState;
  submit: (query: string, options?: SubmitOptions) => Promise<void>;
  attach: (jobId: string) => void;
  review: (action: ReviewAction, plan?: Plan) => Promise<void>;
  /** Read-only `GET /research/{id}`, on demand. */
  refresh: () => Promise<JobDetail | null>;
  reset: () => void;
  /**
   * Observe the machine from outside React's render path.
   *
   * This pair is the WO-11 integration seam. The query layer can
   * `subscribe` to invalidate `['job', principal, id]` whenever the
   * machine settles, and `getSnapshot` gives it the current state
   * without a re-render — the `useSyncExternalStore` contract, so
   * `useSyncExternalStore(subscribe, getSnapshot, getSnapshot)` works
   * as written.
   */
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => JobState;
}

const JobRunContext = createContext<JobRunContextValue | null>(null);

export interface JobRunProviderProps {
  children: ReactNode;
  /**
   * The job to adopt, straight from the route's `?job=` (ADR 0053).
   * `null` is a surface with nothing in flight. Changing it attaches
   * to the new job; it never submits.
   */
  jobId?: string | null;
  /** Passed to `POST /research` when this provider submits. */
  conversationId?: string | null;
  /** Fires once per job, with the `JobDetail` that settled it. */
  onSettled?: (detail: JobDetail) => void;
  /** Fires for every `JobDetail` read. WO-11 seeds its cache here. */
  onDetail?: (detail: JobDetail) => void;
  /** Network seam; see `JobClient`. Read on the first render only. */
  client?: Partial<JobClient>;
  /** Overrides for the liveness poll. Tests shorten the intervals. */
  poll?: Partial<LivenessPollOptions>;
  /** `false` leaves `jobId` unattached until something calls `attach`. */
  autoAttach?: boolean;
  attachMode?: AttachMode;
}

export function JobRunProvider({
  children,
  jobId = null,
  conversationId = null,
  onSettled,
  onDetail,
  client,
  poll,
  autoAttach = true,
  attachMode = "get-first",
}: JobRunProviderProps): ReactNode {
  const controls: JobStreamControls = useJobStream({
    client,
    attachMode,
    onSettled,
    onDetail,
  });
  const { state, attach, refresh, reset, review } = controls;

  const pollOptions = useMemo<LivenessPollOptions>(
    () => ({ ...DEFAULT_POLL, ...poll }),
    [poll]
  );

  // -- Submission ------------------------------------------------------------

  const submit = useCallback(
    (query: string, options: SubmitOptions = {}) =>
      controls.submit(query, {
        conversationId: options.conversationId ?? conversationId,
      }),
    [controls, conversationId]
  );

  // -- URL adoption ----------------------------------------------------------

  useEffect(() => {
    if (!autoAttach || jobId === null) return;
    attach(jobId);
  }, [attach, autoAttach, jobId]);

  // -- The liveness poll -----------------------------------------------------

  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  const active = shouldPoll(state);
  const intervalMs = pollIntervalFor(state, pollOptions);

  useEffect(() => {
    if (!pollOptions.enabled || !active) return;
    // `setInterval` rather than a self-scheduling `setTimeout`: the
    // interval is derived from state, so a change to it re-runs this
    // effect and re-arms the timer. A chained timeout would need to
    // read the interval through a ref and would drift.
    const timer = setInterval(() => {
      void refreshRef.current("poll");
    }, intervalMs);
    return () => {
      clearInterval(timer);
    };
  }, [active, intervalMs, pollOptions.enabled]);

  // -- The external store seam ----------------------------------------------

  const snapshotRef = useRef(state);
  const listenersRef = useRef(new Set<() => void>());

  // Written before the listeners are told, so a subscriber that reads
  // `getSnapshot` from its callback sees the state the notification is
  // about. In an effect rather than during render, so a discarded
  // render never publishes a snapshot that did not happen.
  useEffect(() => {
    snapshotRef.current = state;
    for (const listener of listenersRef.current) listener();
  }, [state]);

  const subscribe = useCallback((listener: () => void) => {
    const listeners = listenersRef.current;
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const getSnapshot = useCallback(() => snapshotRef.current, []);

  const value = useMemo<JobRunContextValue>(
    () => ({
      state,
      submit,
      attach,
      review,
      refresh: () => refresh("refresh"),
      reset,
      subscribe,
      getSnapshot,
    }),
    [attach, getSnapshot, refresh, reset, review, state, submit, subscribe]
  );

  return (
    <JobRunContext.Provider value={value}>{children}</JobRunContext.Provider>
  );
}

/**
 * The machine, from inside a `JobRunProvider`.
 *
 * Throws outside one: a surface that reads job state without a
 * provider would render a permanent `idle`, which is a lie that is
 * hard to see.
 */
export function useJobRun(): JobRunContextValue {
  const value = useContext(JobRunContext);
  if (value === null) {
    throw new Error(
      "useJobRun must be used inside a <JobRunProvider>. The job machine " +
        "is per-route state and has no global fallback."
    );
  }
  return value;
}

/** The machine if there is one, for surfaces that render either way. */
export function useJobRunOptional(): JobRunContextValue | null {
  return useContext(JobRunContext);
}
