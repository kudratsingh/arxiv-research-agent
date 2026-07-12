"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError, getConversation } from "@/lib/api";
import { useResearchStream } from "@/lib/useResearchStream";
import type { ConversationDetail, ConversationJobSummary } from "@/lib/types";
import EventLog from "./EventLog";
import ExportDropdown from "./ExportDropdown";
import JobSummary from "./JobSummary";
import PlanReview from "./PlanReview";
import QueryForm from "./QueryForm";
import ReportView from "./ReportView";

interface ConversationThreadProps {
  conversationId: string;
}

export default function ConversationThread({
  conversationId,
}: ConversationThreadProps) {
  const [conversation, setConversation] = useState<ConversationDetail | null>(
    null
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const detail = await getConversation(conversationId);
      setConversation(detail);
      setLoadError(null);
      // Auto-expand the newest turn so the reviewer lands on the
      // freshest content when navigating in.
      if (detail.jobs.length > 0) {
        setExpanded((prev) => {
          const next = new Set(prev);
          next.add(detail.jobs[detail.jobs.length - 1]!.job_id);
          return next;
        });
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setLoadError("Conversation not found.");
      } else {
        setLoadError(err instanceof Error ? err.message : String(err));
      }
    }
  }, [conversationId]);

  useEffect(() => {
    void load();
  }, [load]);

  const {
    status,
    jobId,
    events,
    detail,
    plan,
    error: submitError,
    submit,
    review,
  } = useResearchStream();

  const busy =
    status === "submitting" ||
    status === "streaming" ||
    status === "awaiting_review";
  const awaitingReview = status === "awaiting_review" && plan !== null;

  const handleSubmit = useCallback(
    async (query: string) => {
      await submit(query, {
        conversation_id: conversationId,
        onDone: () => {
          // Reload conversation to pick up the newly-appended job.
          void load();
        },
      });
    },
    [conversationId, load, submit]
  );

  const toggle = useCallback((jobId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }, []);

  if (loadError) {
    return (
      <div className="px-6 py-10">
        <p className="text-sm text-red-700 dark:text-red-300">{loadError}</p>
      </div>
    );
  }
  if (conversation === null) {
    return (
      <div className="px-6 py-10 text-sm text-slate-500 dark:text-slate-400">
        Loading conversation…
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
        <h1 className="truncate text-lg font-semibold" title={conversation.title}>
          {conversation.title}
        </h1>
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          {conversation.jobs.length}{" "}
          {conversation.jobs.length === 1 ? "turn" : "turns"} ·{" "}
          {new Date(conversation.created_at * 1000).toLocaleString()}
        </p>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
        {conversation.jobs.map((job) => (
          <ConversationTurn
            key={job.job_id}
            job={job}
            expanded={expanded.has(job.job_id)}
            onToggle={() => toggle(job.job_id)}
          />
        ))}

        {(busy || detail || submitError) && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Current turn
              {jobId && (
                <span className="ml-2 font-mono text-[0.65rem] text-slate-400">
                  {jobId}
                </span>
              )}
            </p>
            {events.length > 0 && (
              <div className="mt-3">
                <EventLog events={events} />
              </div>
            )}
            {awaitingReview && plan && (
              <div className="mt-4">
                <PlanReview plan={plan} onReview={review} />
              </div>
            )}
            {detail && <JobSummary detail={detail} />}
            {detail && (detail.result || detail.error) && (
              <div className="mt-4">
                <ReportView detail={detail} />
              </div>
            )}
            {submitError && (
              <p
                role="alert"
                className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200"
              >
                {submitError}
              </p>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-slate-200 bg-white px-6 py-4 dark:border-slate-800 dark:bg-slate-950">
        <QueryForm
          onSubmit={handleSubmit}
          busy={busy}
          jobId={null}
          error={null}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface TurnProps {
  job: ConversationJobSummary;
  expanded: boolean;
  onToggle: () => void;
}

function ConversationTurn({ job, expanded, onToggle }: TurnProps) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start gap-3 px-5 py-3 text-left hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500/40 dark:hover:bg-slate-900"
      >
        <span
          aria-hidden
          className={`mt-1 text-xs text-slate-400 transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        >
          &#9654;
        </span>
        <span className="flex-1">
          <span className="block text-[0.65rem] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Turn {job.ordinal}
          </span>
          <span className="mt-0.5 block text-sm font-medium text-slate-900 dark:text-slate-100">
            {job.query}
          </span>
        </span>
      </button>
      {expanded && (
        <div className="border-t border-slate-200 dark:border-slate-800">
          <div className="flex items-center justify-end px-5 pt-3">
            <ExportDropdown jobId={job.job_id} />
          </div>
          <div className="report-prose px-5 pb-5">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {job.report}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </article>
  );
}
