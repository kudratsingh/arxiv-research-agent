"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  getJob,
  reviewPlan,
  streamUrl,
  submitResearch,
} from "./api";
import {
  JobDetail,
  Plan,
  ReviewAction,
  SseEvent,
  SseEventName,
  TERMINAL_EVENTS,
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

const EVENT_NAMES: readonly SseEventName[] = [
  "job_started",
  "node_completed",
  "plan_ready",
  "job_completed",
  "job_failed",
  "job_cancelled",
] as const;

export function useResearchStream(): UseResearchStreamState {
  const [status, setStatus] = useState<UseResearchStreamState["status"]>(
    "idle"
  );
  const [jobId, setJobId] = useState<string | null>(null);
  const [events, setEvents] = useState<SseEvent[]>([]);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sourceRef = useRef<EventSource | null>(null);
  const jobIdRef = useRef<string | null>(null);

  const cleanup = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const onDoneRef = useRef<SubmitOptions["onDone"] | null>(null);

  const finalize = useCallback(async (id: string) => {
    try {
      const settled = await getJob(id);
      setDetail(settled);
      if (onDoneRef.current) onDoneRef.current(settled);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `fetch result failed (${err.status}): ${err.message}`
          : String(err)
      );
    } finally {
      setStatus("done");
    }
  }, []);

  /**
   * Open the SSE stream for `id` and wire every frame into state.
   *
   * Shared by `submit` and `attach` (ADR 0053) so a job the landing
   * page started and a job this hook started are consumed by exactly
   * the same code — the attach path is not a second, thinner reader
   * that quietly drops `plan_ready`.
   *
   * The caller owns `jobIdRef`/`status`: this only touches the
   * EventSource and the frame-derived state.
   */
  const openStream = useCallback(
    (id: string) => {
      const source = new EventSource(streamUrl(id));
      sourceRef.current = source;

      const handleFrame = (name: SseEventName) => (evt: MessageEvent) => {
        let data: Record<string, unknown> | null = null;
        try {
          data = JSON.parse(evt.data);
        } catch {
          data = null;
        }
        setEvents((prev) => [
          ...prev,
          { name, data, receivedAt: Date.now() },
        ]);
        if (name === "plan_ready" && data && data.plan) {
          setPlan(data.plan as Plan);
          setStatus("awaiting_review");
          return;
        }
        if (TERMINAL_EVENTS.has(name)) {
          source.close();
          sourceRef.current = null;
          void finalize(id);
        }
      };

      for (const name of EVENT_NAMES) {
        source.addEventListener(name, handleFrame(name) as EventListener);
      }
      source.addEventListener("error", () => {
        if (source.readyState === EventSource.CLOSED) return;
        setEvents((prev) => [
          ...prev,
          {
            name: "stream_note",
            data: { message: "connection interrupted; browser is retrying" },
            receivedAt: Date.now(),
          },
        ]);
      });
    },
    [finalize]
  );

  const submit = useCallback(
    async (query: string, options: SubmitOptions = {}) => {
      cleanup();
      onDoneRef.current = options.onDone ?? null;
      setStatus("submitting");
      setEvents([]);
      setDetail(null);
      setPlan(null);
      setError(null);

      let submission;
      try {
        submission = await submitResearch(query, {
          conversation_id: options.conversation_id,
        });
      } catch (err) {
        setStatus("idle");
        setError(err instanceof Error ? err.message : String(err));
        return;
      }

      setJobId(submission.job_id);
      jobIdRef.current = submission.job_id;
      setStatus("streaming");
      openStream(submission.job_id);
    },
    [cleanup, openStream]
  );

  /**
   * Join a job that already exists — never POSTs (ADR 0053).
   *
   * Re-entrant on purpose: it returns early when this hook is already
   * streaming `id`, so an effect that fires again on re-render (or
   * twice under React StrictMode's double-invoked mount) cannot open
   * a second EventSource on the same job. The guard is the live
   * source, not a "have attached" flag, so the StrictMode sequence
   * mount → cleanup (closes the source) → mount does re-open and the
   * reader is not left dead.
   *
   * Attaching to an *already terminal* job is fine and is the reload
   * case: the stream route replays one terminal frame and closes
   * (ADR 0038), which lands here as a normal terminal frame and
   * fetches the settled detail.
   */
  const attach = useCallback(
    (id: string, options: AttachOptions = {}) => {
      if (sourceRef.current !== null && jobIdRef.current === id) return;
      cleanup();
      onDoneRef.current = options.onDone ?? null;
      setEvents([]);
      setDetail(null);
      setPlan(null);
      setError(null);
      setJobId(id);
      jobIdRef.current = id;
      setStatus("streaming");
      openStream(id);
    },
    [cleanup, openStream]
  );

  const review = useCallback(
    async (action: ReviewAction, planEdits?: Plan) => {
      const id = jobIdRef.current;
      if (id === null) {
        setError("no active job to review");
        return;
      }
      try {
        await reviewPlan(id, {
          action,
          ...(action === "revise" && planEdits ? { plan: planEdits } : {}),
        });
      } catch (err) {
        setError(
          err instanceof ApiError
            ? `review failed (${err.status}): ${err.message}`
            : String(err)
        );
        return;
      }
      // Clear the plan (it's been resolved) and go back to streaming
      // until the workflow terminates. The EventSource stays open
      // through the review — the runner keeps emitting node_completed
      // + terminal frames on the same connection.
      setPlan(null);
      setStatus(action === "cancel" ? "streaming" : "streaming");
    },
    []
  );

  return {
    status,
    jobId,
    events,
    detail,
    plan,
    error,
    submit,
    attach,
    review,
  };
}
