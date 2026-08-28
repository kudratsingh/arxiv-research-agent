"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import ConversationThread from "@/components/ConversationThread";

// WO-08 moved this file from `app/c/[id]/page.tsx` into the `(workspace)`
// route group. A route group adds no URL segment, so this is still
// `/c/[id]`, and `?job=` is untouched (ADR 0053, MUST-KEEP #1).
//
// The only edit to its body: the manual shell wrapper it used to render
// around itself is gone: the shell is now `app/(workspace)/layout.tsx`.
// The rail it used to render is now the layout's `nav[aria-label="Threads"]`, and the
// thread renders inside the layout's single `<main id="main">`. The ad-hoc
// "Loading conversation…" fallback stays until WO-09 replaces it with a
// real `loading.tsx`.

export default function ConversationPage() {
  const params = useParams<{ id: string }>();
  const conversationId = params?.id ?? "";
  return (
    // `useSearchParams` opts its subtree into client-side rendering; Next
    // requires the Suspense boundary so the rest of the page can still be
    // prerendered (next build fails the route otherwise).
    <Suspense
      fallback={
        <div className="px-6 py-10 text-sm text-slate-500 dark:text-slate-400">
          Loading conversation…
        </div>
      }
    >
      <ConversationThreadRoute conversationId={conversationId} />
    </Suspense>
  );
}

/**
 * Bridge the `?job=` handoff (ADR 0053) into the thread.
 *
 * The landing page submits the first query and redirects here with
 * the accepted job_id attached, so the thread attaches to that job
 * rather than starting one of its own. Because the id lives in the
 * URL and not in component state, a reload — or a link pasted into
 * another tab — re-attaches to the same job.
 */
function ConversationThreadRoute({
  conversationId,
}: {
  conversationId: string;
}) {
  const searchParams = useSearchParams();
  return (
    <ConversationThread
      // Keyed so switching threads gets a fresh instance. The App
      // Router re-renders this page in place when only the dynamic
      // segment changes, and without the key the new conversation
      // would inherit the previous one's stream, event log and job
      // id — and the URL sync would then write that foreign job id
      // into this conversation's URL.
      key={conversationId}
      conversationId={conversationId}
      adoptJobId={searchParams.get("job")}
    />
  );
}
