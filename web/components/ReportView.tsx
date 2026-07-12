"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ExportDropdown from "./ExportDropdown";
import type { JobDetail } from "@/lib/types";

interface ReportViewProps {
  detail: JobDetail;
}

export default function ReportView({ detail }: ReportViewProps) {
  if (detail.status === "failed" && detail.error) {
    return (
      <section className="rounded-lg border border-red-300 bg-red-50 p-5 dark:border-red-800 dark:bg-red-950/40">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-red-800 dark:text-red-200">
          Job failed
        </h2>
        <p className="font-mono text-sm text-red-900 dark:text-red-100">
          <span className="font-semibold">
            {detail.error_type ?? "unknown"}
          </span>
          : {detail.error}
        </p>
      </section>
    );
  }

  if (!detail.result) return null;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-950">
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Report
        </h2>
        <ExportDropdown jobId={detail.job_id} />
      </div>
      <div className="report-prose">
        {/* react-markdown emits plain HTML by default (no raw HTML
        passthrough), so the report body is safe to render even
        though it originated from an LLM. remark-gfm enables tables,
        strikethrough, and task lists — features the synthesizer
        emits in its markdown output. */}
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {detail.result}
        </ReactMarkdown>
      </div>
    </section>
  );
}
