"use client";

/**
 * `/c/[id]` — the thread workspace (WO-20; 03 §2.1, §2.2 rows 5–7, 9–16, 21).
 *
 * `?job=` IS READ HERE AND NOWHERE ELSE. The route group adds no URL segment
 * and the parameter is byte-identical to what it was before WO-08 moved this
 * file (`web/tests/shell/routing.test.ts`); what changed is what receives it.
 * It used to be `ConversationThread`'s `adoptJobId`; it is now
 * `JobRunProvider`'s `jobId`, which attaches, re-attaches when the value
 * changes, and never POSTs (ADR 0053). `ActiveRunPanel` is given the same
 * value so it can tell "the URL already says this" from "the URL has to be
 * told", which is criterion 1's at-most-once rule.
 *
 * ONE MACHINE, ONE JOB (criterion 3). There is exactly one `JobRunProvider`
 * on this route, and both surfaces under it read the same `state.jobId` —
 * `ActiveRunPanel` to render the run, `ThreadTimeline` to merge that run into
 * the thread's history through `selectBriefings`. They cannot disagree because
 * there is no second place for either of them to look.
 *
 * KEYED ON THE THREAD. `ConversationThread` carried this key with a comment
 * worth keeping: the App Router re-renders this page in place when only the
 * dynamic segment changes, and without the key the new thread would inherit
 * the previous one's stream and job id — and the URL sync would then write
 * that foreign id into this thread's URL. The key is on the provider, so the
 * machine, the panel and the timeline all remount together.
 *
 * THE QUERY CLIENT IS MOUNTED HERE, NOT IN THE LAYOUT, AND IT IS A
 * MEASUREMENT. `useConversationDetail` needs one; a `<Providers>` in
 * `app/(workspace)/layout.tsx` would put TanStack Query into `/`'s first-load
 * JavaScript too (+8,016 B gzip, the figure WO-08 measured), and `/` is the
 * tighter of the two rows. The rail keeps its own client in its lazy chunk
 * (`ThreadRail.tsx`'s `EnsureQueryClient`), so on this route there are two
 * caches rather than one. The keys they share are `conversations.*`, and the
 * only write across that boundary is the rail's optimistic delete — which,
 * for the thread on screen, navigates away rather than leaving a stale row.
 * WO-31/WO-32 can collapse them once `/`'s ceiling has room.
 *
 * THE SUSPENSE BOUNDARY. `useSearchParams` opts its subtree into client-side
 * rendering and `next build` fails the route without one. WO-09 measured what
 * removing it does — the served HTML for `/c/[id]` gets an EMPTY `<main>`,
 * which axe reads as `page-has-heading-one` VIOLATION — so it stays, and its
 * fallback is the same `ThreadSkeleton` every other loading frame on this
 * route uses.
 */

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback } from "react";

import { QueryProvider } from "@/app/providers";
import { ActiveRunPanel } from "@/components/features/ActiveRunPanel";
import {
  FollowUpComposer,
  ThreadTimeline,
} from "@/components/features/ThreadTimeline";
import { ThreadSkeleton } from "@/components/patterns/ThreadSkeleton";
import { JobRunProvider } from "@/lib/job/provider";

export default function ConversationPage() {
  const params = useParams<{ id: string }>();
  const conversationId = params?.id ?? "";
  return (
    <Suspense fallback={<ThreadSkeleton />}>
      <ConversationWorkspace conversationId={conversationId} />
    </Suspense>
  );
}

function ConversationWorkspace({ conversationId }: { conversationId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const adoptJobId = searchParams.get("job");

  // `replace`, not `push`: the pre-attach URL is not a state worth a
  // back-button stop (`ConversationThread.tsx:124-127`).
  const syncUrl = useCallback(
    (href: string) => {
      router.replace(href);
    },
    [router],
  );

  return (
    <QueryProvider>
      <JobRunProvider
        key={conversationId}
        jobId={adoptJobId}
        conversationId={conversationId}
      >
        <ThreadTimeline
          conversationId={conversationId}
          runPanel={
            <ActiveRunPanel
              conversationId={conversationId}
              adoptJobId={adoptJobId}
              onSyncUrl={syncUrl}
            />
          }
          composer={<FollowUpComposer conversationId={conversationId} />}
        />
      </JobRunProvider>
    </QueryProvider>
  );
}
