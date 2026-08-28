"use client";

// Conversation list, detail, and the two conversation mutations
// (04-ARCHITECTURE.md §4.6).
//
// Three things here are behaviour changes rather than plumbing:
//
//   1. The list sends **explicit `limit` and `offset`**. Today's client
//      sends neither (`web/lib/api.ts:67-73` → `lib/api/client.ts`) and
//      is therefore silently cut off at `DEFAULT_LIST_LIMIT = 50`
//      (`src/api/conversations.py:35`) with nothing on the wire to say
//      so. Every request this module makes carries both.
//
//   2. Pagination is **"Load more"**, and nothing else. `GET
//      /conversations` returns a bare array — no `total`, no `has_more`
//      (`routes.py:560-600`) — so a page count or "showing 50 of N"
//      would have to be invented. `canLoadMore` is false as soon as a
//      page comes back shorter than `limit`; that is the only signal the
//      contract supports (03-DESIGN-BRIEF.md §2.3).
//
//   3. Report bodies arrive in full with the detail response
//      (`schemas.py:184-191`), so turns render collapsed and the
//      Markdown pipeline is **not loaded until one is expanded**. See
//      `loadReportRenderer` at the bottom of this file.

import { useEffect, useState } from "react";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type UseInfiniteQueryResult,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  type ConversationDetail,
  type ConversationListItem,
} from "@/lib/api/index";

import {
  loadReportRenderer,
  type ReportRenderer,
} from "@/lib/report/renderer";

import { mutationKeys, queryKeys } from "./keys";

// ---------------------------------------------------------------------------
// Paging.
// ---------------------------------------------------------------------------

/** Mirrors `DEFAULT_LIST_LIMIT` (`src/api/conversations.py:35`). */
export const CONVERSATION_PAGE_SIZE = 50;

/** Mirrors `MAX_LIST_LIMIT` (`src/api/conversations.py:36`). */
export const MAX_CONVERSATION_PAGE_SIZE = 200;

/**
 * Keep the page size inside the server's `ge=1, le=200` bounds so an
 * out-of-range value is a clamped request rather than a 422 the user has
 * to read.
 */
export function clampConversationPageSize(limit: number): number {
  if (!Number.isFinite(limit)) return CONVERSATION_PAGE_SIZE;
  return Math.min(Math.max(Math.trunc(limit), 1), MAX_CONVERSATION_PAGE_SIZE);
}

/** One page of the list, with both parameters always on the wire. */
export function fetchConversationPage(
  limit: number,
  offset: number,
  signal?: AbortSignal
): Promise<ConversationListItem[]> {
  return listConversations({ limit, offset, signal });
}

type ConversationPages = InfiniteData<ConversationListItem[], number>;

export interface ConversationListOptions {
  /** Rows per page. Defaults to the server's own default. */
  limit?: number;
  enabled?: boolean;
}

export interface ConversationListResult {
  /** Every row fetched so far, in server order (newest first). */
  conversations: ConversationListItem[];
  /**
   * Whether a "Load more" control should be rendered at all.
   *
   * False the moment a page returns fewer than `limit` rows. There is no
   * total to compare against and no page number to show — the API
   * supplies neither, so neither is offered.
   */
  canLoadMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
  /** Rows requested per page, for the caller that wants to say so. */
  limit: number;
  query: UseInfiniteQueryResult<ConversationPages, Error>;
}

export function useConversationList(
  options: ConversationListOptions = {}
): ConversationListResult {
  const limit = clampConversationPageSize(options.limit ?? CONVERSATION_PAGE_SIZE);

  const query = useInfiniteQuery<
    ConversationListItem[],
    Error,
    ConversationPages,
    readonly unknown[],
    number
  >({
    queryKey: queryKeys.conversations.list(limit),
    queryFn: ({ pageParam, signal }) =>
      fetchConversationPage(limit, pageParam, signal),
    initialPageParam: 0,
    // A short page is the end of the list. This is the only
    // "is there more?" signal the contract can give.
    getNextPageParam: (lastPage, _allPages, lastPageParam) =>
      lastPage.length < limit ? undefined : lastPageParam + limit,
    enabled: options.enabled ?? true,
  });

  const conversations = query.data?.pages.flat() ?? [];

  return {
    conversations,
    canLoadMore: query.hasNextPage,
    isLoadingMore: query.isFetchingNextPage,
    loadMore: () => {
      if (query.hasNextPage && !query.isFetchingNextPage) {
        void query.fetchNextPage();
      }
    },
    limit,
    query,
  };
}

// ---------------------------------------------------------------------------
// Detail.
// ---------------------------------------------------------------------------

/**
 * One question-and-report turn in a thread.
 *
 * `report` is the raw Markdown **string**. Nothing in this layer parses
 * it; see `useReportRenderer`.
 */
export interface ConversationTurn {
  jobId: string;
  ordinal: number;
  question: string;
  report: string;
  createdAt: number;
}

/** Turns in ordinal order. Pure, so it is testable without a cache. */
export function conversationTurns(
  detail: ConversationDetail | undefined
): ConversationTurn[] {
  if (detail === undefined) return [];
  return [...detail.jobs]
    .map((job) => ({
      jobId: job.job_id,
      ordinal: job.ordinal,
      question: job.query,
      report: job.report,
      createdAt: job.created_at,
    }))
    .sort((left, right) => left.ordinal - right.ordinal);
}

export interface ConversationDetailResult {
  detail: ConversationDetail | undefined;
  turns: ConversationTurn[];
  query: UseQueryResult<ConversationDetail, Error>;
}

export function useConversationDetail(
  conversationId: string | null
): ConversationDetailResult {
  const query = useQuery({
    queryKey: queryKeys.conversations.detail(conversationId ?? ""),
    queryFn: ({ signal }) =>
      getConversation(conversationId as string, { signal }),
    enabled: conversationId !== null,
  });

  return { detail: query.data, turns: conversationTurns(query.data), query };
}

// ---------------------------------------------------------------------------
// Mutations. Both are `retry: false` — the client default forces it, and
// each states it so the property survives a client swap.
// ---------------------------------------------------------------------------

export function useCreateConversation(): UseMutationResult<
  ConversationDetail,
  Error,
  string | undefined
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: mutationKeys.conversations.create(),
    retry: false,
    mutationFn: (title?: string) => createConversation(title),
    onSuccess: (created) => {
      queryClient.setQueryData(
        queryKeys.conversations.detail(created.conversation_id),
        created
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.lists(),
      });
    },
  });
}

/** What `onMutate` snapshots so `onError` can put it all back. */
export interface DeleteConversationContext {
  lists: [readonly unknown[], ConversationPages | undefined][];
  detail: ConversationDetail | undefined;
}

/**
 * Delete a thread, optimistically.
 *
 * The row leaves every cached page before the request is sent, and comes
 * back — with its detail entry — if the request fails. The confirmation
 * dialog and the copy that names what the API actually deletes belong to
 * the surface work orders; this is the cache half.
 */
export function useDeleteConversation(): UseMutationResult<
  void,
  Error,
  string,
  DeleteConversationContext
> {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string, DeleteConversationContext>({
    mutationKey: mutationKeys.conversations.delete(),
    retry: false,
    mutationFn: (conversationId: string) => deleteConversation(conversationId),
    onMutate: async (conversationId) => {
      // In-flight reads would otherwise land after the optimistic write
      // and resurrect the row.
      await queryClient.cancelQueries({
        queryKey: queryKeys.conversations.all(),
      });

      const lists = queryClient.getQueriesData<ConversationPages>({
        queryKey: queryKeys.conversations.lists(),
      });
      const detail = queryClient.getQueryData<ConversationDetail>(
        queryKeys.conversations.detail(conversationId)
      );

      queryClient.setQueriesData<ConversationPages>(
        { queryKey: queryKeys.conversations.lists() },
        (pages) =>
          pages === undefined
            ? pages
            : {
                ...pages,
                pages: pages.pages.map((page) =>
                  page.filter((row) => row.conversation_id !== conversationId)
                ),
              }
      );
      queryClient.removeQueries({
        queryKey: queryKeys.conversations.detail(conversationId),
      });

      return { lists, detail };
    },
    onError: (_error, conversationId, context) => {
      if (context === undefined) return;
      for (const [key, pages] of context.lists) {
        queryClient.setQueryData(key, pages);
      }
      if (context.detail !== undefined) {
        queryClient.setQueryData(
          queryKeys.conversations.detail(conversationId),
          context.detail
        );
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.all(),
      });
    },
  });
}

// ---------------------------------------------------------------------------
// The Markdown parse boundary.
// ---------------------------------------------------------------------------

/**
 * The boundary itself now lives in `lib/report/renderer.ts` (WO-18), and is
 * re-exported here so this module's public shape is unchanged.
 *
 * WHY IT MOVED. This module imports `@tanstack/react-query` and `lib/api`.
 * Everything that only wants to RENDER Markdown — the reading surface and
 * its stories — would otherwise pull the whole query layer in to reach a
 * dynamic `import()` that has nothing to do with it. `useReportRenderer`
 * below is a hook about when a turn is expanded, so it stays; the loader is
 * about a module, so it does not.
 */
export type { ReportRenderer, ReportRendererProps } from "@/lib/report/renderer";
export { loadReportRenderer };

/**
 * The renderer for one turn, or `null` while it is collapsed.
 *
 * Returning `null` for a collapsed turn is not a convenience — it is the
 * guarantee. A collapsed turn never triggers the import, so it never
 * parses, and `web/tests/queries/conversations.test.ts` asserts exactly
 * that by counting how many times the module is loaded.
 */
export function useReportRenderer(expanded: boolean): ReportRenderer | null {
  const [renderer, setRenderer] = useState<ReportRenderer | null>(null);

  useEffect(() => {
    if (!expanded || renderer !== null) return;
    let live = true;
    void loadReportRenderer().then((loaded) => {
      // `() => loaded`, not `loaded`: the state IS a function, and a
      // bare `setRenderer(loaded)` would be read as an updater and
      // called with `null`.
      if (live) setRenderer(() => loaded);
    });
    return () => {
      live = false;
    };
  }, [expanded, renderer]);

  return expanded ? renderer : null;
}
