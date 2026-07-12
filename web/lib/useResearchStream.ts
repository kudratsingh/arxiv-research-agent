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
  submit: (query: string) => Promise<void>;
  review: (action: ReviewAction, plan?: Plan) => Promise<void>;
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

  const finalize = useCallback(async (id: string) => {
    try {
      const settled = await getJob(id);
      setDetail(settled);
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

  const submit = useCallback(
    async (query: string) => {
      cleanup();
      setStatus("submitting");
      setEvents([]);
      setDetail(null);
      setPlan(null);
      setError(null);

      let submission;
      try {
        submission = await submitResearch(query);
      } catch (err) {
        setStatus("idle");
        setError(err instanceof Error ? err.message : String(err));
        return;
      }

      setJobId(submission.job_id);
      jobIdRef.current = submission.job_id;
      setStatus("streaming");

      const source = new EventSource(streamUrl(submission.job_id));
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
          void finalize(submission.job_id);
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
    [cleanup, finalize]
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

  return { status, jobId, events, detail, plan, error, submit, review };
}
