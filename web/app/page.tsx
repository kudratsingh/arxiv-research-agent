"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import ConversationsShell from "@/components/ConversationsShell";
import QueryForm from "@/components/QueryForm";
import { ApiError, createConversation, submitResearch } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(
    async (query: string) => {
      setBusy(true);
      setError(null);
      try {
        // A new conversation is created for the very first query,
        // then the query is submitted and we redirect into
        // `/c/[id]?job=[job_id]`.
        //
        // ADR 0053: the `job` parameter is the whole point. This page
        // used to throw the accepted job_id away and push a bare
        // `/c/[id]`, and nothing downstream could recover it — the
        // thread has no way to ask "which job is in flight?", and a
        // job parked in `pending_review` is not in the conversation's
        // job list either (the runner appends only on success). So the
        // user paid for a planner call, watched an empty page, and the
        // job died 30 minutes later on the HITL timeout. Carrying the
        // id in the URL also makes a reload of the thread re-attach to
        // the same job instead of buying a second one.
        const conv = await createConversation();
        const accepted = await submitResearch(query, {
          conversation_id: conv.conversation_id,
        });
        router.push(
          `/c/${encodeURIComponent(conv.conversation_id)}` +
            `?job=${encodeURIComponent(accepted.job_id)}`
        );
      } catch (err) {
        setBusy(false);
        setError(
          err instanceof ApiError
            ? `submit failed: ${err.message}`
            : String(err)
        );
      }
    },
    [router]
  );

  return (
    <ConversationsShell activeConversationId={null}>
      <div className="mx-auto flex h-full max-w-3xl flex-col justify-center gap-6 px-6">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            arxiv-research-agent
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Ask a research question to kick off a new conversation. Follow-ups
            stay in the same thread and reuse prior findings as retrievable
            context.
          </p>
        </header>
        <QueryForm
          onSubmit={handleSubmit}
          busy={busy}
          jobId={null}
          error={error}
        />
      </div>
    </ConversationsShell>
  );
}
