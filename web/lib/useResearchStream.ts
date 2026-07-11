"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJob, streamUrl, submitResearch, ApiError } from "./api";
import {
  JobDetail,
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
 *   3. On a terminal event, GET the status URL for the settled
 *      JobDetail (the report body + metrics).
 *
 * Idempotent to caller re-submissions — a fresh submit closes any
 * open stream and resets `events` before starting.
 */
export interface UseResearchStreamState {
  status: "idle" | "submitting" | "streaming" | "done";
  jobId: string | null;
  events: SseEvent[];
  detail: JobDetail | null;
  error: string | null;
  submit: (query: string) => Promise<void>;
}

const EVENT_NAMES: readonly SseEventName[] = [
  "job_started",
  "node_completed",
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
  const [error, setError] = useState<string | null>(null);

  const sourceRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const submit = useCallback(
    async (query: string) => {
      cleanup();
      setStatus("submitting");
      setEvents([]);
      setDetail(null);
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
        if (TERMINAL_EVENTS.has(name)) {
          source.close();
          sourceRef.current = null;
          finalize(submission.job_id);
        }
      };

      for (const name of EVENT_NAMES) {
        source.addEventListener(name, handleFrame(name) as EventListener);
      }
      source.addEventListener("error", () => {
        // EventSource auto-reconnects unless we close it. On terminal
        // frames we're already closed. Mid-stream network hiccups are
        // logged as a soft note rather than treated as a hard error.
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

      async function finalize(id: string) {
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
      }
    },
    [cleanup]
  );

  return { status, jobId, events, detail, error, submit };
}
