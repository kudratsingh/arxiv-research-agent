"use client";

import { useResearchStream } from "@/lib/useResearchStream";
import QueryForm from "./QueryForm";
import EventLog from "./EventLog";
import JobSummary from "./JobSummary";
import ReportView from "./ReportView";

export default function ResearchApp() {
  const { status, jobId, events, detail, error, submit } = useResearchStream();

  const busy = status === "submitting" || status === "streaming";

  return (
    <div className="space-y-6">
      <QueryForm onSubmit={submit} busy={busy} jobId={jobId} error={error} />

      {events.length > 0 && (
        <section className="rounded-lg border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Progress
          </h2>
          <EventLog events={events} />
          {detail && <JobSummary detail={detail} />}
        </section>
      )}

      {detail && (detail.result || detail.error) && (
        <ReportView detail={detail} />
      )}
    </div>
  );
}
