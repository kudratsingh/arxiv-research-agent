// WO-11 criteria 2, 3 and 5 — explicit pagination parameters, "Load
// more" semantics, and optimistic delete with rollback.
//
// The list handler here is the one place in this suite that does not
// replay a recording byte-for-byte: it slices the RECORDED rows by the
// `limit`/`offset` the client sent, because a pagination test needs a
// server that paginates. Nothing is invented — the rows are the recorded
// ones and the slicing is what `src/api/conversations.py:35-36` does.

import { createElement, type ReactElement, type ReactNode } from "react";

import { http, HttpResponse } from "msw";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { API_BASE, listConversations, type ConversationListItem } from "@/lib/api/index";
import { createQueryClient } from "@/lib/queries/client";
import {
  CONVERSATION_PAGE_SIZE,
  MAX_CONVERSATION_PAGE_SIZE,
  clampConversationPageSize,
  conversationTurns,
  useConversationDetail,
  useConversationList,
  useCreateConversation,
  useDeleteConversation,
} from "@/lib/queries/conversations";
import { queryKeys } from "@/lib/queries/keys";
import type { ConversationDetail } from "@/lib/api/index";

import {
  errorFixture,
  fixtureResponse,
  handlers,
  loadFixture,
  server,
  setupMswServer,
} from "../support/msw";
import { act, renderHook, waitFor } from "../support/render";

const RECORDED_ROWS = loadFixture("conversations.list").body as ConversationListItem[];
const RECORDED_DETAIL = loadFixture("conversations.detail").body as ConversationDetail;

/** Every list request this file saw, newest last. */
const requested: URL[] = [];

const pagingList = http.get(`${API_BASE}/conversations`, ({ request }) => {
  const url = new URL(request.url);
  requested.push(url);
  const limitParam = url.searchParams.get("limit");
  const offsetParam = url.searchParams.get("offset");
  const limit = limitParam === null ? RECORDED_ROWS.length : Number(limitParam);
  const offset = offsetParam === null ? 0 : Number(offsetParam);
  return HttpResponse.json(RECORDED_ROWS.slice(offset, offset + limit));
});

// `pagingList` first so it wins over the recorded list handler; the rest
// of the defaults (conversation detail, the job states) come along
// because `resetHandlers(...extra)` REPLACES the handler list rather
// than layering onto it.
setupMswServer(pagingList, ...handlers);

beforeEach(() => {
  requested.length = 0;
});

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }): ReactElement {
    return createElement(QueryClientProvider, { client }, children);
  };
}

function testClient(): QueryClient {
  // Reads do not retry here: a retry policy is tested in client.test.ts,
  // and three attempts per failing read would only slow this file down.
  return createQueryClient({ defaultOptions: { queries: { retry: false } } });
}

// ---------------------------------------------------------------------------
// Criterion 2 — explicit limit and offset.
// ---------------------------------------------------------------------------

describe("the list sends explicit limit and offset (criterion 2)", () => {
  it("puts both on the request URL", async () => {
    const client = testClient();
    const { result } = renderHook(() => useConversationList(), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));

    expect(requested).toHaveLength(1);
    const url = requested[0];
    if (url === undefined) throw new Error("no request recorded");
    expect(url.searchParams.get("limit")).toBe(String(CONVERSATION_PAGE_SIZE));
    expect(url.searchParams.get("offset")).toBe("0");
    // The whole query string, so this fails if either parameter is
    // dropped from the URL builder rather than from the hook.
    expect(url.search).toBe(`?limit=${CONVERSATION_PAGE_SIZE}&offset=0`);
  });

  it("advances offset by limit on the next page, never by a row count", async () => {
    const client = testClient();
    const { result } = renderHook(() => useConversationList({ limit: 2 }), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));

    act(() => {
      result.current.loadMore();
    });
    await waitFor(() => expect(requested).toHaveLength(2));

    expect(requested.map((url) => url.search)).toEqual([
      "?limit=2&offset=0",
      "?limit=2&offset=2",
    ]);
  });

  it("leaves the M0 call sites alone — no parameters, no query string", async () => {
    // `components/ConversationSidebar.tsx` still calls it bare. The
    // typed client must behave exactly as it did, which is also why the
    // truncation this fixes is silent today.
    await listConversations();
    const url = requested.at(-1);
    expect(url?.search).toBe("");
  });

  it("clamps a page size to the server's own bounds instead of earning a 422", () => {
    expect(clampConversationPageSize(0)).toBe(1);
    expect(clampConversationPageSize(-5)).toBe(1);
    expect(clampConversationPageSize(10_000)).toBe(MAX_CONVERSATION_PAGE_SIZE);
    expect(clampConversationPageSize(2.7)).toBe(2);
    expect(clampConversationPageSize(Number.NaN)).toBe(CONVERSATION_PAGE_SIZE);
  });
});

// ---------------------------------------------------------------------------
// Criterion 3 — "Load more", and nothing that needs a total.
// ---------------------------------------------------------------------------

describe("pagination is Load more (criterion 3)", () => {
  it("hides the control when a page comes back shorter than limit", async () => {
    const client = testClient();
    const { result } = renderHook(() => useConversationList(), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));
    // Two recorded rows, a page size of fifty: this is the end of the list.
    expect(result.current.conversations).toHaveLength(RECORDED_ROWS.length);
    expect(result.current.canLoadMore).toBe(false);
  });

  it("offers it while a page comes back full, and retires it at the end", async () => {
    const client = testClient();
    const { result } = renderHook(() => useConversationList({ limit: 2 }), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));
    // A full page tells us nothing about what follows, so the control stays.
    expect(result.current.canLoadMore).toBe(true);

    act(() => {
      result.current.loadMore();
    });

    await waitFor(() => expect(result.current.canLoadMore).toBe(false));
    // The empty second page appends nothing and ends the list.
    expect(result.current.conversations).toHaveLength(2);
  });

  it("does not fire a second request when there is nothing more to load", async () => {
    const client = testClient();
    const { result } = renderHook(() => useConversationList(), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));

    act(() => {
      result.current.loadMore();
    });
    await waitFor(() => expect(result.current.isLoadingMore).toBe(false));
    expect(requested).toHaveLength(1);
  });

  it("exposes no total, no page count, and no 'showing 50 of N'", async () => {
    // `GET /conversations` returns a bare array (`routes.py:560-600`),
    // so any of these would be invented. The recorded body proves it.
    expect(Array.isArray(loadFixture("conversations.list").body)).toBe(true);

    const client = testClient();
    const { result } = renderHook(() => useConversationList(), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));

    const forbidden = ["total", "count", "pageCount", "pages", "of"];
    for (const name of Object.keys(result.current)) {
      expect(forbidden, name).not.toContain(name);
    }
  });
});

// ---------------------------------------------------------------------------
// Criterion 5 — optimistic delete with rollback.
// ---------------------------------------------------------------------------

function seedList(client: QueryClient): readonly unknown[] {
  const key = queryKeys.conversations.list(CONVERSATION_PAGE_SIZE);
  client.setQueryData(key, { pages: [RECORDED_ROWS], pageParams: [0] });
  return key;
}

function rowIds(client: QueryClient, key: readonly unknown[]): string[] {
  const data = client.getQueryData<{ pages: ConversationListItem[][] }>(key);
  return (data?.pages ?? []).flat().map((row) => row.conversation_id);
}

describe("delete is optimistic and rolls back (criterion 5)", () => {
  const TARGET = "baseline-empty";
  const detailKey = queryKeys.conversations.detail(TARGET);

  it("puts the row — and its detail — back when the request fails", async () => {
    const client = testClient();
    const key = seedList(client);
    client.setQueryData(detailKey, RECORDED_DETAIL);

    // The response is held open so the optimistic state can be observed
    // mid-flight; the body is the recorded 502 envelope.
    let release = (): void => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.delete(`${API_BASE}/conversations/:conversationId`, async () => {
        await held;
        return fixtureResponse(loadFixture("error.502"));
      })
    );

    const { result } = renderHook(() => useDeleteConversation(), {
      wrapper: wrapper(client),
    });

    const settled = result.current
      .mutateAsync(TARGET)
      .then(() => "resolved" as const, () => "rejected" as const);

    // In flight: gone from the list, and its detail entry with it.
    await waitFor(() => expect(rowIds(client, key)).not.toContain(TARGET));
    expect(client.getQueryData(detailKey)).toBeUndefined();

    release();
    expect(await settled).toBe("rejected");

    // Rolled back: the row is where it was, in its original position.
    await waitFor(() => expect(rowIds(client, key)).toContain(TARGET));
    expect(rowIds(client, key)).toEqual(
      RECORDED_ROWS.map((row) => row.conversation_id)
    );
    expect(client.getQueryData(detailKey)).toEqual(RECORDED_DETAIL);
  });

  it("rolls back a 404 from the recorded envelope too", async () => {
    const client = testClient();
    const key = seedList(client);
    server.use(
      errorFixture("error.404", "delete", `${API_BASE}/conversations/:conversationId`)
    );

    const { result } = renderHook(() => useDeleteConversation(), {
      wrapper: wrapper(client),
    });

    await act(async () => {
      await result.current.mutateAsync(TARGET).catch(() => undefined);
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(rowIds(client, key)).toContain(TARGET);
  });

  it("does not retry the delete", async () => {
    const client = testClient();
    seedList(client);
    let attempts = 0;
    server.use(
      http.delete(`${API_BASE}/conversations/:conversationId`, () => {
        attempts += 1;
        return fixtureResponse(loadFixture("error.502"));
      })
    );

    const { result } = renderHook(() => useDeleteConversation(), {
      wrapper: wrapper(client),
    });
    await act(async () => {
      await result.current.mutateAsync(TARGET).catch(() => undefined);
    });

    expect(attempts).toBe(1);
  });

  it("leaves an unseeded cache alone rather than inventing an entry", async () => {
    // The rollback path has nothing to restore when nothing was cached.
    const client = testClient();
    server.use(
      errorFixture("error.404", "delete", `${API_BASE}/conversations/:conversationId`)
    );

    const { result } = renderHook(() => useDeleteConversation(), {
      wrapper: wrapper(client),
    });
    await act(async () => {
      await result.current.mutateAsync(TARGET).catch(() => undefined);
    });

    expect(client.getQueryData(detailKey)).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Create — the third idempotent write §4.1 assigns to a mutation.
// ---------------------------------------------------------------------------

describe("creating a thread", () => {
  // No fixture records `POST /conversations`; the body below is a
  // `ConversationDetail` per `src/api/schemas.py:194-201`, echoed back
  // with the title the client sent. It costs no model spend — the route
  // writes a row (`routes.py:520-556`).
  const created: ConversationDetail = {
    conversation_id: "created-1",
    title: "A new thread",
    created_at: 1_787_883_500,
    updated_at: 1_787_883_500,
    jobs: [],
  };

  it("seeds the detail cache and marks the list stale", async () => {
    const client = testClient();
    const key = seedList(client);
    server.use(
      http.post(`${API_BASE}/conversations`, () =>
        HttpResponse.json(created, { status: 201 })
      )
    );

    const { result } = renderHook(() => useCreateConversation(), {
      wrapper: wrapper(client),
    });
    await act(async () => {
      await result.current.mutateAsync("A new thread");
    });

    expect(
      client.getQueryData(queryKeys.conversations.detail("created-1"))
    ).toEqual(created);
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it("does not retry a failed create", async () => {
    const client = testClient();
    let attempts = 0;
    server.use(
      http.post(`${API_BASE}/conversations`, () => {
        attempts += 1;
        return fixtureResponse(loadFixture("error.502"));
      })
    );

    const { result } = renderHook(() => useCreateConversation(), {
      wrapper: wrapper(client),
    });
    await act(async () => {
      await result.current.mutateAsync(undefined).catch(() => undefined);
    });

    expect(attempts).toBe(1);
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// Detail.
// ---------------------------------------------------------------------------

describe("conversation detail", () => {
  it("returns turns in ordinal order, with the report still unparsed", async () => {
    const client = testClient();
    const { result } = renderHook(
      () => useConversationDetail("baseline-populated"),
      { wrapper: wrapper(client) }
    );

    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));

    expect(result.current.detail).toEqual(RECORDED_DETAIL);
    expect(result.current.turns.map((turn) => turn.ordinal)).toEqual([1]);
    const turn = result.current.turns[0];
    expect(typeof turn?.report).toBe("string");
    expect(turn?.report).toContain("# Retrieval-Augmented Verification");
  });

  it("does not fetch until it has an id", () => {
    const client = testClient();
    const { result } = renderHook(() => useConversationDetail(null), {
      wrapper: wrapper(client),
    });
    expect(result.current.query.fetchStatus).toBe("idle");
    expect(result.current.turns).toEqual([]);
  });

  it("sorts turns by ordinal without mutating the cached response", () => {
    const detail: ConversationDetail = {
      ...RECORDED_DETAIL,
      jobs: [
        { job_id: "b", ordinal: 2, query: "second", report: "b", created_at: 2 },
        { job_id: "a", ordinal: 1, query: "first", report: "a", created_at: 1 },
      ],
    };
    expect(conversationTurns(detail).map((turn) => turn.jobId)).toEqual([
      "a",
      "b",
    ]);
    expect(detail.jobs.map((job) => job.job_id)).toEqual(["b", "a"]);
    expect(conversationTurns(undefined)).toEqual([]);
  });
});
