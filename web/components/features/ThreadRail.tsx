"use client";

/**
 * ThreadRail — the rail with its data behind it (RC-10's rename of
 * `ConversationRail`; WO-14).
 *
 * This is the only module in the rail that reaches the data layer. It owns
 * WO-11's three consumers and nothing else:
 *
 *   `useConversationList`   → the rows, `canLoadMore` and `loadMore`
 *   `query.refetch()`       → the Retry, which re-runs `GET /conversations`
 *                             and cannot reach a mutation (criterion 6)
 *   `useDeleteConversation` → the optimistic removal and its rollback
 *
 * WHY IT IS LOADED LAZILY, AND WHY THAT IS A MEASUREMENT RATHER THAN A
 * STYLE. `components/app/ThreadRailBridge.tsx` imports this module through
 * `React.lazy`, exactly as WO-08's shell imports `ThreadDrawer`. The bridge
 * is reached from `app/(workspace)/layout.tsx`, so anything it imports
 * statically is charged to BOTH routes' first-load JavaScript. This module
 * pulls in TanStack Query — +8,016 B gzip on `/`, the figure WO-08 measured
 * when it tried to mount `<Providers>` in the root layout — plus the two
 * Radix packages behind the overflow menu and the confirmation. `/` has
 * 4,632 B of headroom under RC-01's 148,480 B ceiling, so a static import
 * breaches a gated row before the first row of the list renders. The
 * Suspense fallback the bridge renders is the same skeleton this component
 * renders while its own first page is in flight, so the split is invisible.
 *
 * WHY IT PROVIDES A QueryClient IF NOBODY ELSE HAS. `app/layout.tsx` does
 * not mount `<Providers>` yet and its comment says why with the numbers:
 * TanStack in the root layout is +8 KB gzip on two gated rows for a library
 * that, in M1, had no consumer. This rail is its first consumer and it
 * arrives in a lazy chunk, where those bytes are not charged to a route
 * budget. `EnsureQueryClient` therefore uses the app's client when there is
 * one and creates a private one when there is not — so WO-20 can mount
 * `<Providers>` at the root and this file needs no edit, and the cache
 * stops being private the moment it does. It is deliberately NOT an
 * unconditional provider: a nested client under a mounted one would
 * partition the cache and make this rail's optimistic delete invisible to
 * the thread surface reading the same rows.
 */

import * as navigation from "next/navigation";
import { useCallback, useContext, useState, type ReactNode } from "react";

import { QueryClientContext, QueryClientProvider } from "@tanstack/react-query";

import { ThreadList, type ThreadSummary } from "@/components/patterns/ThreadList";
import { THREAD_RAIL } from "@/lib/copy/threads";
import { createQueryClient } from "@/lib/queries/client";
import { useConversationList, useDeleteConversation } from "@/lib/queries/conversations";

/** What a document whose router cannot be read has in its query string. */
const NO_SEARCH = new URLSearchParams();

/**
 * The route's query string, or an empty one where the router is a stand-in.
 *
 * WHY `useSearchParams` AND NOT `window.location.search`. It is the only
 * source that updates when the thread writes `?job=` into a URL whose PATH
 * has not changed, and that is the case R-02 is really about:
 * `ConversationThread.tsx:132-142` calls `router.replace` with the same path
 * and a new query, and the App Router re-renders nothing above the segment
 * — so a location read would go stale exactly when a run is attached. It is
 * also why this component sits behind the bridge's Suspense boundary:
 * `useSearchParams` opts its subtree into client-side rendering and Next
 * fails the build for a statically prerendered route without one
 * (`app/(workspace)/c/[id]/page.tsx:22-24` carries the same note for the
 * same reason).
 *
 * WHY IT IS RESOLVED, ONCE, RATHER THAN IMPORTED BY NAME. The rail is
 * mounted by a LAYOUT, so it renders on every route in the workbench,
 * inside every tree that stands in for the router rather than running one.
 * `web/tests/shell/wiring.test.tsx` is one such tree — its `next/navigation`
 * double predates this rail and supplies `useRouter` and `usePathname` only
 * — and a router substitute missing one export must not be able to unmount
 * the rail and take the workbench's navigation with it. The `try` covers
 * the ACCESS and not merely its result, because a module double may throw
 * on an export it does not define rather than answering `undefined`. The
 * failure mode is "no run is attached", which is the truthful answer when
 * the URL cannot be read, and `WorkbenchShell.readRailMode` already makes
 * the same trade for `matchMedia`.
 *
 * The resolution happens once, at module load, so hook order is fixed for
 * the lifetime of the module — this is not a conditional hook.
 */
function resolveSearchHook(): () => Pick<URLSearchParams, "get"> {
  try {
    const hook = (navigation as Partial<typeof navigation>).useSearchParams;
    if (typeof hook === "function") return hook;
  } catch {
    /* No such export on this router. Fall through to the empty query. */
  }
  return () => NO_SEARCH;
}

const useRouteSearch = resolveSearchHook();

export interface ThreadRailProps {
  /** The thread the route is on. The bridge derives it from `usePathname()`. */
  activeConversationId?: string | null;
  /** Overrides the route's own `?job=`. Stories and tests only. */
  attachedJobId?: string | null;
  /** Where a row click goes. The bridge pushes it. */
  onNavigate?: (href: string) => void;
  /** Rows per page. Defaults to `CONVERSATION_PAGE_SIZE` — the server's own. */
  limit?: number;
}

export function ThreadRail({
  activeConversationId = null,
  attachedJobId,
  onNavigate,
  limit,
}: ThreadRailProps) {
  const search = useRouteSearch();
  // The `?job=` contract is read straight off the URL because the URL is
  // where it lives (03 §2.1, MUST-KEEP 1): the thread writes it and a
  // reload reads it back. Nothing derives it from a store the rail would
  // have to be told about.
  const attachedId = attachedJobId ?? search.get("job");

  const list = useConversationList(limit === undefined ? {} : { limit });
  const remove = useDeleteConversation();

  const [pendingDelete, setPendingDelete] = useState<ThreadSummary | null>(null);
  const [deleteFailed, setDeleteFailed] = useState(false);

  const threads: ThreadSummary[] = list.conversations.map((row) => ({
    id: row.conversation_id,
    title: row.title,
  }));

  const confirmDelete = useCallback(() => {
    const target = pendingDelete;
    if (target === null) return;
    setDeleteFailed(false);
    remove.mutate(target.id, {
      onSuccess: () => {
        // Closing the dialog is what moves focus: `ThreadList` sends it
        // back to the row's overflow button, or — as here, where that
        // button has just been deleted — to the rail's first control.
        setPendingDelete(null);
        // Deleting the thread you are reading leaves the route pointing at
        // a 404. `ConversationsShell.tsx:17-19` sent the empty id to `/`;
        // this is the same move with the href spelled out.
        if (target.id === activeConversationId) onNavigate?.("/");
      },
      onError: () => {
        // The row is already back — `useDeleteConversation`'s `onError`
        // restores every cached page — so the dialog closes and the rail
        // says so. It does NOT offer to try again: R-01 and H6 forbid
        // replaying a write, and a retry button beside a failed DELETE is
        // exactly that.
        setPendingDelete(null);
        setDeleteFailed(true);
      },
    });
  }, [activeConversationId, onNavigate, pendingDelete, remove]);

  /**
   * The next thing the user does with the list clears the previous
   * failure's sentence.
   *
   * Cleared in the handlers rather than from an effect watching
   * `isFetching`: a `setState` inside an effect is a cascading render the
   * React compiler's lint rejects, and the honest trigger is the user's
   * action anyway — the sentence describes an attempt, and the attempt
   * stops being the latest news the moment another one starts.
   */
  const startDelete = useCallback((thread: ThreadSummary) => {
    setDeleteFailed(false);
    setPendingDelete(thread);
  }, []);

  const loadMore = useCallback(() => {
    setDeleteFailed(false);
    list.loadMore();
  }, [list]);

  const retry = useCallback(() => {
    setDeleteFailed(false);
    void list.query.refetch();
  }, [list.query]);

  const notice = list.query.isError
    ? {
        sentence: THREAD_RAIL.error,
        recovery: THREAD_RAIL.errorRecovery,
        retryLabel: THREAD_RAIL.retry,
        // `refetch` on the LIST query. There is no path from this control
        // to a mutation — criterion 6, asserted by a test that watches
        // every request the rail makes.
        onRetry: retry,
      }
    : deleteFailed
      ? { sentence: THREAD_RAIL.deleteFailed }
      : null;

  // No wrapper element. The bridge's Suspense fallback renders
  // `ThreadRailFrame` as its own root, and a wrapper here would mean the
  // tree gains a box at the moment the chunk resolves — a structural
  // difference between two states criterion 4 says the user must not be
  // able to see.
  return (
    <ThreadList
      threads={threads}
      loading={list.query.isPending}
      activeConversationId={activeConversationId}
      attachedJobId={attachedId}
      canLoadMore={list.canLoadMore}
      isLoadingMore={list.isLoadingMore}
      onLoadMore={loadMore}
      notice={notice}
      onNavigate={onNavigate}
      onDeleteRequest={startDelete}
      pendingDelete={pendingDelete}
      onDeleteCancel={() => setPendingDelete(null)}
      onDeleteConfirm={confirmDelete}
      deletePending={remove.isPending}
    />
  );
}

/**
 * The app's QueryClient if there is one, a private one if there is not.
 * See the module header for why both halves of that sentence are load-bearing.
 */
export function EnsureQueryClient({ children }: { children: ReactNode }) {
  const existing = useContext(QueryClientContext);
  const [fallback] = useState(createQueryClient);
  if (existing !== undefined) return <>{children}</>;
  return <QueryClientProvider client={fallback}>{children}</QueryClientProvider>;
}

/** The lazy entry point the bridge imports. */
export default function ThreadRailWithClient(props: ThreadRailProps) {
  return (
    <EnsureQueryClient>
      <ThreadRail {...props} />
    </EnsureQueryClient>
  );
}
