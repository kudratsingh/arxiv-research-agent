"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import ConversationThread from "@/components/ConversationThread";
import { ThreadSkeleton } from "@/components/patterns/ThreadSkeleton";

// WO-08 moved this file from `app/c/[id]/page.tsx` into the `(workspace)`
// route group. A route group adds no URL segment, so this is still
// `/c/[id]`, and `?job=` is untouched (ADR 0053, MUST-KEEP #1).
//
// The only edit to its body: the manual shell wrapper it used to render
// around itself is gone: the shell is now `app/(workspace)/layout.tsx`.
// The rail it used to render is now the layout's `nav[aria-label="Threads"]`, and the
// thread renders inside the layout's single `<main id="main">`.
//
// WO-09 made the second edit, and it is one expression: the Suspense
// fallback below. It was the string "Loading conversation…" in a
// `px-6 py-10` box — the state 04-ARCHITECTURE.md §2.1 and WO-09
// criterion 4 both name by file and line.
//
// WHEN THIS FALLBACK IS ACTUALLY PAINTED, MEASURED RATHER THAN ASSUMED.
// Almost never, and that is worth writing down because the obvious reading
// is wrong. `/c/[id]` is a DYNAMIC route, so `useSearchParams` resolves
// during SSR instead of suspending: the server renders straight through
// this boundary into `ConversationThread`, which paints its own
// `conversation === null` state. So the loading state a cold load shows is
// `ConversationThread`'s, and that is where WO-09 put `ThreadSkeleton` too
// — the same component, so the two cannot drift.
//
// The boundary itself still has to exist: `next build` fails the route
// without it. WO-09 measured deleting it (saving 1,064 B of first-load JS
// on `/c/[id]`) and the page then opts out of SSR entirely — the served
// HTML for `/c/[id]` has an EMPTY `<main>`, which axe-core 4.13.0 in
// headless Chrome reads as `h1: 0`, `page-has-heading-one` VIOLATION. So
// the boundary stays, and its fallback is the same skeleton as everywhere
// else rather than a second design for a frame nobody sees.

export default function ConversationPage() {
  const params = useParams<{ id: string }>();
  const conversationId = params?.id ?? "";
  return (
    // `useSearchParams` opts its subtree into client-side rendering; Next
    // requires the Suspense boundary so the rest of the page can still be
    // prerendered (next build fails the route otherwise). See the header
    // for what this fallback is and is not.
    <Suspense fallback={<ThreadSkeleton />}>
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
