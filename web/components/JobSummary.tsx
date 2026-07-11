"use client";

import type { JobDetail } from "@/lib/types";

interface JobSummaryProps {
  detail: JobDetail;
}

export default function JobSummary({ detail }: JobSummaryProps) {
  return (
    <dl className="mt-4 grid grid-cols-2 gap-3 rounded-md border border-slate-200 bg-white p-4 font-mono text-sm dark:border-slate-800 dark:bg-slate-950 sm:grid-cols-5">
      <Stat label="Iterations" value={fmt(detail.iterations)} />
      <Stat label="Quality" value={fmtScore(detail.quality_score)} />
      <Stat label="Cost" value={fmtCost(detail.cost_usd)} />
      <Stat label="LLM calls" value={fmt(detail.llm_calls)} />
      <Stat label="Elapsed" value={fmtElapsed(detail.elapsed_sec)} />
    </dl>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-[0.65rem] uppercase tracking-wider text-slate-500 dark:text-slate-400">
        {label}
      </dt>
      <dd className="mt-1 text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}

function fmt(v: number | null): string {
  return v == null ? "-" : String(v);
}

function fmtScore(v: number | null): string {
  return v == null ? "-" : v.toFixed(2);
}

function fmtCost(v: number | null): string {
  return v == null ? "-" : `$${v.toFixed(4)}`;
}

function fmtElapsed(v: number | null): string {
  return v == null ? "-" : `${v.toFixed(1)}s`;
}
