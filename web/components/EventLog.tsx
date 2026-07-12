"use client";

import { useEffect, useRef } from "react";
import type { SseEvent, SseEventName } from "@/lib/types";

interface EventLogProps {
  events: SseEvent[];
}

const NAME_COLORS: Record<SseEventName, string> = {
  job_started: "text-blue-600 dark:text-blue-400",
  node_completed: "text-blue-600 dark:text-blue-400",
  plan_ready: "text-amber-600 dark:text-amber-400",
  job_completed: "text-emerald-600 dark:text-emerald-400",
  job_failed: "text-red-600 dark:text-red-400",
  job_cancelled: "text-amber-600 dark:text-amber-400",
  stream_note: "text-amber-600 dark:text-amber-400",
  error: "text-red-600 dark:text-red-400",
};

export default function EventLog({ events }: EventLogProps) {
  const containerRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <ul
      ref={containerRef}
      role="log"
      aria-live="polite"
      className="max-h-80 overflow-y-auto rounded-md border border-slate-200 bg-white font-mono text-xs dark:border-slate-800 dark:bg-slate-950"
    >
      {events.map((evt, idx) => (
        <li
          key={idx}
          className="grid grid-cols-[5.5rem_10rem_1fr] items-baseline gap-2 border-b border-slate-100 px-3 py-1.5 last:border-b-0 dark:border-slate-800"
        >
          <span className="text-slate-400 dark:text-slate-500">
            {formatTime(evt.receivedAt)}
          </span>
          <span
            className={`font-semibold ${NAME_COLORS[evt.name] ?? ""}`}
          >
            {evt.name}
          </span>
          <span className="break-words">{formatDetail(evt)}</span>
        </li>
      ))}
    </ul>
  );
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour12: false });
}

function formatDetail(evt: SseEvent): string {
  const data = evt.data;
  if (!data) return "";
  if (evt.name === "job_started") {
    return "workflow starting";
  }
  if (evt.name === "node_completed") {
    const parts: string[] = [];
    if (typeof data.node === "string") parts.push(`node=${data.node}`);
    const delta = data.state_delta as Record<string, unknown> | undefined;
    if (delta) {
      for (const [k, v] of Object.entries(delta)) {
        parts.push(`${k}=${formatValue(v)}`);
      }
    }
    return parts.join(" ");
  }
  if (evt.name === "plan_ready") {
    const plan = data.plan as
      | { sub_questions?: string[]; search_queries?: string[] }
      | undefined;
    const n_sub = plan?.sub_questions?.length ?? 0;
    const n_q = plan?.search_queries?.length ?? 0;
    return `sub_questions=${n_sub} search_queries=${n_q} (awaiting review)`;
  }
  if (evt.name === "job_completed") {
    const elapsed =
      typeof data.elapsed_sec === "number"
        ? `${data.elapsed_sec.toFixed(1)}s`
        : "?";
    return `elapsed=${elapsed}`;
  }
  if (evt.name === "job_failed") {
    const errType =
      typeof data.error_type === "string" ? data.error_type : "error";
    const errMsg = typeof data.error === "string" ? data.error : "";
    return `${errType}: ${errMsg}`;
  }
  if (evt.name === "job_cancelled") {
    return "cancelled";
  }
  if (evt.name === "stream_note" && typeof data.message === "string") {
    return data.message;
  }
  return "";
}

function formatValue(v: unknown): string {
  if (typeof v === "number" && !Number.isInteger(v)) return v.toFixed(2);
  return String(v);
}
