"use client";

// The imperative half of the job machine (04-ARCHITECTURE.md §4.3, §4.4).
//
// `machine.ts` is pure and knows nothing about time, the network or the
// browser. This file is where all three live: it owns the
// `EventSource`, issues `GET /research/{id}`, calls `POST /research`
// exactly once per submission, and turns `pagehide`/`pageshow` into
// machine events. Everything it learns it hands to the reducer; it
// keeps no state of its own that a consumer can read.
//
// Three behaviours here are the reason this work order exists:
//
//   1. **GET-first attach.** `GET /research/{id}` runs BEFORE the
//      `EventSource` is opened. Today the stream is opened first
//      (`useResearchStream.ts:238-253`) and the job's status is learned
//      from whatever frame happens to arrive, which is why an expired
//      job arrives through the browser's failed-connection path
//      (`useResearchStream.ts:171-188`) instead of a clean 404.
//   2. **`stream_timeout` reopens immediately.** The name is registered
//      here — `useResearchStream.ts:59-66` registers six of the seven —
//      so the client no longer waits out the browser's default retry
//      after the server closes at `api_sse_max_duration_sec`.
//   3. **A terminal frame is a signal.** It closes the stream and
//      triggers `GET /research/{id}`; every displayed value comes from
//      that read (H9), which is what makes the three asymmetric
//      terminal shapes (§11.3) indistinguishable to the UI.

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import {
  ApiError,
  SERVER_EVENT_NAMES,
  getJob,
  reviewPlan,
  streamUrl,
  submitResearch,
} from "@/lib/api";
import type { ApiFailure, JobDetail, Plan, ReviewAction } from "@/lib/api";

import {
  initialJobState,
  isSettledPhase,
  isTerminalFrameName,
  isTerminalJobStatus,
  jobReducer,
} from "./machine";
import type {
  DetailSource,
  FrameEvent,
  FrameEventType,
  JobClient,
  JobFrame,
  JobState,
} from "./types";

// ---------------------------------------------------------------------------
// Options and controls.
// ---------------------------------------------------------------------------

/**
 * How `attach` reaches the stream.
 *
 * `get-first` is the contract (§4.3) and the default.
 *
 * `stream-first` exists for exactly one caller: the
 * `useResearchStream` adapter, whose consumers' tests pin the old
 * request ordering — `attach()` opens the `EventSource`
 * *synchronously*, and the only `GET /research/{id}` in the whole
 * lifecycle is the one a terminal frame triggers. Porting those tests
 * to GET-first would mean rewriting them, and "all existing tests pass
 * unmodified" is the evidence that the port is behaviour-neutral. The
 * mode dies with `useResearchStream.ts` in WO-31; nothing else may set
 * it.
 */
export type AttachMode = "get-first" | "stream-first";

export interface UseJobStreamOptions {
  /** Network seam. Defaults to `lib/api`; see `JobClient`. */
  client?: Partial<JobClient>;
  attachMode?: AttachMode;
  /** RC-18. `false` only for tests that assert the listeners' absence. */
  bfcache?: boolean;
  /** Called once per job, with the `JobDetail` that settled it. */
  onSettled?: (detail: JobDetail) => void;
  /** Called for every `JobDetail` read. The WO-11 cache-seeding seam. */
  onDetail?: (detail: JobDetail) => void;
}

export interface SubmitOptions {
  conversationId?: string | null;
}

export interface AttachOptions {
  /** Per-attach settle callback, replacing the hook-level one. */
  onSettled?: (detail: JobDetail) => void;
}

export interface JobStreamControls {
  state: JobState;
  /**
   * `POST /research`, guarded by a submission token.
   *
   * A plain async function — never a query-library mutation. Query's
   * default `networkMode: "online"` pauses a mutation while offline
   * and *resumes it when connectivity returns*, which is an automatic
   * replay of a paid, non-idempotent submission (R-01, H6). The
   * endpoint has no idempotency key (`routes.py:179-197`).
   *
   * Refuses while a submission is already in flight and resolves
   * without calling anything. The reducer refuses the same
   * combination independently, so the guard holds even if this one is
   * bypassed.
   */
  submit: (query: string, options?: SubmitOptions) => Promise<void>;
  /** Adopt an existing job. Never POSTs (ADR 0053). Re-entrant. */
  attach: (jobId: string, options?: AttachOptions) => void;
  /** Resolve the review pause. 409 refetches rather than shouting. */
  review: (action: ReviewAction, plan?: Plan) => Promise<void>;
  /** Read-only `GET /research/{id}`. The liveness poll's one call. */
  refresh: (source?: DetailSource) => Promise<JobDetail | null>;
  /** Drop the stream and the job. */
  reset: () => void;
}

// ---------------------------------------------------------------------------
// Small helpers.
// ---------------------------------------------------------------------------

/**
 * `EventSource.CLOSED`, by value.
 *
 * The numeric constants are pinned by the HTML spec, and reading them
 * off the global would couple this module to whichever `EventSource`
 * implementation is installed — including the test stub's.
 */
const READY_STATE_CLOSED = 2;

/** Named-frame event types, keyed by the wire name. Identity, but typed. */
function frameEvent(name: FrameEventType, frame: JobFrame): FrameEvent {
  // One cast, in one place: `FrameEvent` is a distributed union, so the
  // compiler cannot see that `{ type: name }` picks exactly one member
  // when `name` is the whole union. The mapping is the identity.
  return { type: name, frame } as FrameEvent;
}

interface NormalizedFailure {
  failure: ApiFailure | null;
  message: string;
  status: number | null;
}

/**
 * Split a thrown value into the normalized failure and the message as
 * thrown.
 *
 * Both are kept: `ApiFailure.message` is the user-facing sentence
 * WO-12's dictionary will replace, while the thrown message is what
 * the legacy surfaces render today and what the diagnostics
 * disclosure wants verbatim.
 */
function normalizeThrown(err: unknown): NormalizedFailure {
  if (err instanceof ApiError) {
    return {
      failure: err.failure,
      message: err.message,
      status: err.status,
    };
  }
  return {
    failure: null,
    message: err instanceof Error ? err.message : String(err),
    status: null,
  };
}

/** Module-level so it is not a changing dependency of every callback. */
function now(): number {
  return Date.now();
}

let tokenCounter = 0;

/**
 * A submission token.
 *
 * Uniqueness within one browser session is all this needs to be — it
 * is compared only against the token of the submission this machine
 * has in flight, never sent to the server, never persisted.
 * Hand-rolled rather than `crypto.randomUUID()` so it works in every
 * runtime this bundle targets without a feature check.
 */
function nextSubmissionToken(): string {
  tokenCounter += 1;
  return `submission-${Date.now().toString(36)}-${tokenCounter}`;
}

// ---------------------------------------------------------------------------
// The hook.
// ---------------------------------------------------------------------------

export function useJobStream(
  options: UseJobStreamOptions = {}
): JobStreamControls {
  const {
    attachMode = "get-first",
    bfcache = true,
    client: clientOverride,
    onSettled,
    onDetail,
  } = options;

  const [state, dispatch] = useReducer(jobReducer, initialJobState);

  // Everything below is machinery, not state: nothing here is rendered,
  // and the reducer is the only thing a consumer reads. Every one of
  // these refs is written from an event handler or an effect, never
  // during render.
  const sourceRef = useRef<EventSource | null>(null);
  /**
   * Bumped on every open and every close, so a listener from a stream
   * we have already replaced can recognise itself as stale and stay
   * quiet. Without it, closing a source during a reopen would still
   * let its `error` handler fire and report the reopen as a failure.
   */
  const generationRef = useRef(0);
  /** The job this hook is attached to. The re-entrancy guard. */
  const attachedRef = useRef<string | null>(null);
  /**
   * The id `review`/`refresh` act on.
   *
   * Written synchronously by `attach` and `submit` rather than read
   * off the rendered state, so a call made in the same tick as an
   * attach sees the job that attach adopted.
   */
  const jobIdRef = useRef<string | null>(null);
  /**
   * **The R-01 guard, and the reason it is a ref.**
   *
   * Two `submit()` calls in one tick — a double click, or Enter plus a
   * click — both run before React has re-rendered, so a guard that
   * read the rendered phase would let the second one through and buy a
   * second paid run. This flag flips synchronously, inside the call.
   * The reducer refuses `submit_requested` while `submitting`
   * independently; two layers, because `POST /research` has no
   * idempotency key (`routes.py:179-197`).
   */
  const submitInFlightRef = useRef(false);
  /** Cancels an in-flight pre-flight GET when the attach is superseded. */
  const attachGenerationRef = useRef(0);
  /** Set by `pagehide`, consumed by `pageshow` (RC-18). */
  const suspendedRef = useRef<string | null>(null);
  /** Job ids whose settle callback has already fired. */
  const settledNotifiedRef = useRef<string | null>(null);
  const submissionTokenRef = useRef<string | null>(null);

  const onSettledRef = useRef(onSettled);
  const onDetailRef = useRef(onDetail);
  useEffect(() => {
    onSettledRef.current = onSettled;
    onDetailRef.current = onDetail;
  }, [onDetail, onSettled]);
  const perAttachSettleRef = useRef<((detail: JobDetail) => void) | null>(null);

  /**
   * The network seam (`JobClient`), defaulted to `lib/api`.
   *
   * Memoized on the override so a caller that passes a stable object —
   * a module constant, or its own `useMemo` — gets stable callbacks
   * out of this hook, which is what `ConversationThread`'s attach
   * effect depends on. A caller passing a fresh literal every render
   * still behaves correctly: `attach` is re-created, the effect
   * re-runs, and the re-entrancy guard turns it into a no-op.
   */
  const client = useMemo<JobClient>(
    () => ({
      getJob,
      submitResearch: (query, opts) => submitResearch(query, opts),
      reviewPlan: (jobId, body) => reviewPlan(jobId, body),
      streamUrl,
      ...clientOverride,
    }),
    [clientOverride]
  );

  /**
   * `openStream` reaches itself for the `stream_timeout` reopen. The
   * ref breaks what would otherwise be a circular `useCallback`
   * dependency, and is assigned immediately below the definition.
   */
  const openStreamRef = useRef<(jobId: string) => void>(() => undefined);

  // -- Stream lifecycle ------------------------------------------------------

  const closeStream = useCallback((): void => {
    generationRef.current += 1;
    if (sourceRef.current !== null) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  const notifySettled = useCallback((detail: JobDetail): void => {
    if (settledNotifiedRef.current === detail.job_id) return;
    settledNotifiedRef.current = detail.job_id;
    const perAttach = perAttachSettleRef.current;
    if (perAttach) perAttach(detail);
    else onSettledRef.current?.(detail);
  }, []);

  const acceptDetail = useCallback(
    (detail: JobDetail, source: DetailSource): void => {
      dispatch({ type: "detail_resolved", detail, source, at: now() });
      onDetailRef.current?.(detail);
      if (isTerminalJobStatus(detail.status)) notifySettled(detail);
    },
    [notifySettled]
  );

  const rejectDetail = useCallback(
    (err: unknown, jobId: string, source: DetailSource): void => {
      const { failure, message, status } = normalizeThrown(err);
      // A 404 is the one answer that means "gone" — and it means both
      // "missing" and "not yours" (`routes.py:59-84`), which the UI
      // must never try to tell apart (H8). Everything else is a
      // transport problem and says nothing about the run.
      dispatch({
        type: status === 404 ? "detail_not_found" : "detail_unreachable",
        jobId,
        failure,
        message,
        status,
        source,
        at: now(),
      });
    },
    []
  );

  /** `GET /research/{id}`. Free, read-only, no model spend. */
  const read = useCallback(
    async (jobId: string, source: DetailSource): Promise<JobDetail | null> => {
      try {
        const detail = await client.getJob(jobId);
        acceptDetail(detail, source);
        return detail;
      } catch (err) {
        rejectDetail(err, jobId, source);
        return null;
      }
    },
    [acceptDetail, client, rejectDetail]
  );

  const openStream = useCallback(
    (jobId: string): void => {
      closeStream();
      const generation = generationRef.current;
      const source = new EventSource(client.streamUrl(jobId));
      sourceRef.current = source;

      /** False once this stream has been replaced or closed. */
      const live = (): boolean =>
        generationRef.current === generation && sourceRef.current === source;

      source.addEventListener("open", () => {
        if (!live()) return;
        // Checkpoint rule 2 fires in the reducer from here, and this
        // listener is also what the browser's OWN automatic retry
        // reaches: a reconnect dispatches `open` on the same object.
        dispatch({ type: "stream_opened", jobId, at: now() });
      });

      const receive = (name: FrameEventType) =>
        ((event: MessageEvent) => {
          if (!live()) return;
          let data: Record<string, unknown> | null = null;
          try {
            data = JSON.parse(event.data) as Record<string, unknown>;
          } catch {
            // A malformed body must not throw inside a listener; the
            // frame still happened and still belongs in the log.
            data = null;
          }
          const frame: JobFrame = { name, data, receivedAt: now() };

          if (name === "stream_timeout") {
            // The stream hit its ceiling; the JOB did not stop
            // (`streaming.py:300-308`). Reopen now rather than waiting
            // out the browser's default retry.
            dispatch(frameEvent(name, frame));
            openStreamRef.current(jobId);
            return;
          }

          if (isTerminalFrameName(name)) {
            // Close before dispatching: the run is over on this
            // connection, and a stream left open would keep the page
            // out of the bfcache for no reason.
            closeStream();
            dispatch(frameEvent(name, frame));
            void read(jobId, "reconcile");
            return;
          }

          dispatch(frameEvent(name, frame));
        }) as EventListener;

      for (const name of SERVER_EVENT_NAMES) {
        source.addEventListener(name, receive(name));
      }

      // Unnamed frames. The server names every event it emits, so this
      // is the seam a future one would arrive through — and named
      // events nobody registered for are dropped by the EventSource
      // itself, which is why `unknown_event_name.jsonl` needs no
      // handling at all.
      source.addEventListener("message", (event) => {
        if (!live()) return;
        let data: Record<string, unknown> | null = null;
        try {
          data = JSON.parse((event as MessageEvent).data) as Record<
            string,
            unknown
          >;
        } catch {
          data = null;
        }
        dispatch(
          frameEvent("unknown_frame", {
            name: "message",
            data,
            receivedAt: now(),
          })
        );
      });

      source.addEventListener("error", () => {
        if (!live()) return;
        if (source.readyState !== READY_STATE_CLOSED) {
          // CONNECTING: the browser owns this retry. Narrate it; the
          // reconnect replays nothing, so the checkpoint that survives
          // it is only a statement about a connection that ended.
          dispatch({ type: "stream_interrupted", jobId, at: now() });
          return;
        }
        // CLOSED without a terminal frame: a non-200 response, which in
        // practice is the stream route's 404 for a job that has aged
        // out of `api_job_retention_sec`. The browser will not retry.
        dispatch({ type: "stream_failed", jobId, at: now() });
      });
    },
    [client, closeStream, read]
  );

  // Assigned from an effect, not during render. `beginAttach` calls
  // `openStream` directly, so the ref is only ever read from a frame
  // handler — long after the first commit.
  useEffect(() => {
    openStreamRef.current = openStream;
  }, [openStream]);

  // -- Attach ----------------------------------------------------------------

  const beginAttach = useCallback(
    (jobId: string): void => {
      attachedRef.current = jobId;
      jobIdRef.current = jobId;
      settledNotifiedRef.current = null;
      attachGenerationRef.current += 1;
      const attachGeneration = attachGenerationRef.current;
      dispatch({
        type: "attach_requested",
        jobId,
        prefetch: attachMode === "get-first",
        at: now(),
      });

      if (attachMode === "stream-first") {
        openStream(jobId);
        return;
      }

      // GET-first (§4.3). The read decides whether a stream is opened
      // at all: a 404 renders "no longer available" and opens nothing,
      // and an already-terminal job settles from its `JobDetail`
      // without a connection.
      void (async () => {
        let detail: JobDetail | null = null;
        try {
          detail = await client.getJob(jobId);
        } catch (err) {
          if (attachGenerationRef.current !== attachGeneration) return;
          const { status } = normalizeThrown(err);
          rejectDetail(err, jobId, "attach");
          // Only a 404 is proof the run is gone (H8). A timeout or a
          // dropped connection says nothing, so the stream still gets
          // its chance to speak.
          if (status !== 404) openStream(jobId);
          return;
        }
        if (attachGenerationRef.current !== attachGeneration) return;
        acceptDetail(detail, "attach");
        if (isTerminalJobStatus(detail.status)) return;
        openStream(jobId);
      })();
    },
    [acceptDetail, attachMode, client, openStream, rejectDetail]
  );

  const attach = useCallback(
    (jobId: string, attachOptions: AttachOptions = {}): void => {
      perAttachSettleRef.current = attachOptions.onSettled ?? null;
      // Re-entrant on purpose: an effect that fires again on re-render,
      // or React StrictMode's double-invoked mount, must not open a
      // second `EventSource` on the same job — and must not re-issue
      // the pre-flight GET either.
      if (attachedRef.current === jobId) return;
      closeStream();
      beginAttach(jobId);
    },
    [beginAttach, closeStream]
  );

  // -- Submit ----------------------------------------------------------------

  const submit = useCallback(
    async (query: string, submitOptions: SubmitOptions = {}): Promise<void> => {
      // The guard. A submission already in flight is not a reason to
      // buy a second run; the reducer refuses the same pair.
      if (submitInFlightRef.current) return;
      submitInFlightRef.current = true;

      closeStream();
      attachedRef.current = null;
      jobIdRef.current = null;
      settledNotifiedRef.current = null;
      perAttachSettleRef.current = null;

      const token = nextSubmissionToken();
      submissionTokenRef.current = token;
      const conversationId = submitOptions.conversationId ?? null;
      dispatch({
        type: "submit_requested",
        token,
        query,
        conversationId,
        at: now(),
      });

      let jobId: string;
      try {
        const accepted = await client.submitResearch(
          query,
          conversationId === null ? {} : { conversation_id: conversationId }
        );
        jobId = accepted.job_id;
      } catch (err) {
        const { failure, message, status } = normalizeThrown(err);
        dispatch({
          type: "submit_rejected",
          token,
          failure,
          message,
          status,
          at: now(),
        });
        return;
      } finally {
        submitInFlightRef.current = false;
      }

      // A response for a submission that is no longer the one in flight
      // is dropped by the reducer's token check; stop here too rather
      // than opening a stream for it.
      if (submissionTokenRef.current !== token) return;
      dispatch({ type: "submit_accepted", token, jobId, at: now() });
      beginAttach(jobId);
    },
    [beginAttach, client, closeStream]
  );

  // -- Review ----------------------------------------------------------------

  const review = useCallback(
    async (action: ReviewAction, plan?: Plan): Promise<void> => {
      const jobId = jobIdRef.current;
      if (jobId === null) return;
      dispatch({ type: "review_requested", action, at: now() });
      try {
        await client.reviewPlan(jobId, {
          ...(action === "revise" && plan ? { plan } : {}),
          action,
        });
      } catch (err) {
        const { failure, message, status } = normalizeThrown(err);
        if (status === 409) {
          // `job_not_awaiting_review` (`routes.py:261-264`) is not an
          // error to shout about — the truth moved. Refetch it.
          dispatch({
            type: "review_conflict",
            failure,
            message,
            status,
            at: now(),
          });
          void read(jobId, "attach");
          return;
        }
        dispatch({
          type: "review_rejected",
          failure,
          message,
          status,
          at: now(),
        });
        return;
      }
      // The 200 does NOT mean resumed: `ReviewResponse.status` is
      // always `pending_review` (`schemas.py:141-160`). Wait for a
      // frame or a poll.
      dispatch({ type: "review_accepted", action, at: now() });
    },
    [client, read]
  );

  // -- Refresh and reset -----------------------------------------------------

  const refresh = useCallback(
    async (source: DetailSource = "refresh"): Promise<JobDetail | null> => {
      const jobId = jobIdRef.current;
      if (jobId === null) return null;
      return read(jobId, source);
    },
    [read]
  );

  const reset = useCallback((): void => {
    closeStream();
    attachedRef.current = null;
    jobIdRef.current = null;
    suspendedRef.current = null;
    settledNotifiedRef.current = null;
    submissionTokenRef.current = null;
    perAttachSettleRef.current = null;
    dispatch({ type: "reset", at: now() });
  }, [closeStream]);

  // -- Effects ---------------------------------------------------------------

  // A settled or unavailable run has no stream. This also covers the
  // path a terminal frame never touches: a liveness poll that finds
  // the job already finished.
  useEffect(() => {
    if (isSettledPhase(state.phase) && sourceRef.current !== null) {
      closeStream();
    }
  }, [closeStream, state.phase]);

  /**
   * RC-18. An open `EventSource` makes `/c/[id]` bfcache-ineligible —
   * a confirmed baseline finding — so the stream closes on `pagehide`
   * and is re-attached on `pageshow`.
   *
   * The re-attach is `attach(sameJobId)`, so the `?job=` contract is
   * preserved by construction: the machine never writes the URL and
   * never POSTs on this path. The end-to-end proof (a Playwright
   * back-navigation asserting the same `job_id` with no second
   * `POST /research`, plus the Lighthouse `bf-cache` audit) belongs to
   * WO-21's harness, which does not exist yet; the behaviour and its
   * unit tests are here.
   */
  useEffect(() => {
    if (!bfcache) return;
    const handlePageHide = (): void => {
      const jobId = attachedRef.current;
      if (jobId === null || sourceRef.current === null) return;
      closeStream();
      attachedRef.current = null;
      suspendedRef.current = jobId;
      dispatch({ type: "page_hidden", at: now() });
    };
    const handlePageShow = (): void => {
      const jobId = suspendedRef.current;
      // `pageshow` also fires on a normal first load, where there is
      // nothing to restore.
      if (jobId === null) return;
      suspendedRef.current = null;
      dispatch({ type: "page_restored", at: now() });
      attach(jobId);
    };
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", handlePageShow);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", handlePageShow);
    };
  }, [attach, bfcache, closeStream]);

  // Unmount closes the stream and forgets the attachment, so a
  // StrictMode remount re-attaches rather than being left dead.
  useEffect(
    () => () => {
      closeStream();
      attachedRef.current = null;
      attachGenerationRef.current += 1;
    },
    [closeStream]
  );

  return useMemo(
    () => ({ state, submit, attach, review, refresh, reset }),
    [attach, refresh, reset, review, state, submit]
  );
}
