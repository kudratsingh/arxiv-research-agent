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
        // A new conversation is created for the very first query;
        // then we redirect into `/c/[id]` and let ConversationThread
        // pick up the streaming from there.
        const conv = await createConversation();
        await submitResearch(query, { conversation_id: conv.conversation_id });
        router.push(`/c/${conv.conversation_id}`);
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
