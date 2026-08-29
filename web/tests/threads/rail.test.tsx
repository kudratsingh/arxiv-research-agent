/**
 * WO-14 — the rail with its data behind it: criteria 1, 3, 4, 6 and 7 as
 * behaviour rather than as markup.
 *
 * Every request this file makes goes through MSW and is RECORDED, because
 * two of the criteria are claims about requests rather than about pixels:
 * the Retry re-runs `GET /conversations` and can reach no mutation
 * (criterion 6), and a failed DELETE is never replayed (R-01, H6). A test
 * that only looked at the screen could not tell either of those from its
 * opposite.
 */

import { createElement, type ReactElement, type ReactNode } from "react";

import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  EnsureQueryClient,
  ThreadRail,
} from "@/components/features/ThreadRail";
import { SKELETON_ROW_COUNT } from "@/components/patterns/ThreadRailFrame";
import { threadMenuLabel } from "@/components/patterns/ThreadList";
import { API_BASE, type ConversationListItem } from "@/lib/api/index";
import { THREAD_RAIL, THREAD_ROW, deleteDialog } from "@/lib/copy/threads";
import { createQueryClient } from "@/lib/queries/client";
import { queryKeys } from "@/lib/queries/keys";

import { handlers, server, setupMswServer } from "../support/msw";
import { render, screen, user, waitFor, within } from "../support/render";

/* -------------------------------------------------------------------------
 * The router. `?job=` is read with `useSearchParams` because it is the only
 * source that updates when the thread rewrites a query string in place.
 * ---------------------------------------------------------------------- */

let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => search,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

/* -------------------------------------------------------------------------
 * A server that pages, and a log of everything asked of it.
 * ---------------------------------------------------------------------- */

const ROWS: readonly ConversationListItem[] = Array.from({ length: 5 }, (_, index) => ({
  conversation_id: `thread-${index + 1}`,
  title: `Thread ${index + 1}`,
  created_at: 0,
  updated_at: index,
}));

/**
 * The server's copy of the list, which a DELETE really removes from.
 *
 * A handler that answered 204 and then kept serving the row would make the
 * optimistic removal look correct for one frame and then be undone by
 * `onSettled`'s invalidation — which is exactly the bug this pair of
 * assertions exists to catch, so the fake server has to behave like the
 * real one.
 */
let rows: ConversationListItem[] = [...ROWS];

interface Recorded {
  method: string;
  path: string;
  search: string;
}

const requests: Recorded[] = [];
let listStatus = 200;
let deleteStatus = 204;

function record(request: Request): void {
  const url = new URL(request.url);
  requests.push({ method: request.method, path: url.pathname, search: url.search });
}

const listHandler = http.get(`${API_BASE}/conversations`, ({ request }) => {
  record(request);
  if (listStatus !== 200) {
    return HttpResponse.json({ detail: "upstream" }, { status: listStatus });
  }
  const url = new URL(request.url);
  const limit = Number(url.searchParams.get("limit") ?? rows.length);
  const offset = Number(url.searchParams.get("offset") ?? 0);
  return HttpResponse.json(rows.slice(offset, offset + limit));
});

const deleteHandler = http.delete(`${API_BASE}/conversations/:id`, ({ request, params }) => {
  record(request);
  if (deleteStatus !== 204) {
    return HttpResponse.json({ detail: "conflict" }, { status: deleteStatus });
  }
  rows = rows.filter((row) => row.conversation_id !== params["id"]);
  return new HttpResponse(null, { status: 204 });
});

setupMswServer(listHandler, deleteHandler, ...handlers);

beforeEach(() => {
  requests.length = 0;
  listStatus = 200;
  deleteStatus = 204;
  rows = [...ROWS];
  search = new URLSearchParams();
});

function testClient(): QueryClient {
  // No read retries: the retry policy has its own tests in
  // tests/queries/client.test.ts, and three attempts per failing read would
  // only make this file slow.
  return createQueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }): ReactElement {
    return createElement(QueryClientProvider, { client }, children);
  };
}

function renderRail(
  props: Partial<React.ComponentProps<typeof ThreadRail>> = {},
  client: QueryClient = testClient(),
) {
  const Wrapper = wrapper(client);
  const result = render(
    <Wrapper>
      <ThreadRail limit={3} {...props} />
    </Wrapper>,
  );
  return { ...result, client };
}

async function firstPage(): Promise<void> {
  await screen.findByRole("link", { name: "Thread 1" });
}

/* =========================================================================
 * Criterion 4 — the load
 * ========================================================================= */

describe("criterion 4 — the first page", () => {
  it("reserves three rows while it is in flight, then replaces them", async () => {
    renderRail();

    expect(document.querySelectorAll("[data-thread-row-skeleton]")).toHaveLength(
      SKELETON_ROW_COUNT,
    );
    expect(screen.getByRole("list")).toHaveAttribute("aria-busy", "true");

    await firstPage();
    expect(document.querySelectorAll("[data-thread-row-skeleton]")).toHaveLength(0);
    expect(screen.getByRole("list")).not.toHaveAttribute("aria-busy", "true");
    // The chrome was there the whole time, which is why nothing moved.
    expect(screen.getByRole("heading", { name: THREAD_RAIL.heading })).toBeInTheDocument();
  });

  it("sends the explicit limit and offset WO-11 put on the wire", async () => {
    renderRail();
    await firstPage();
    expect(requests).toEqual([
      { method: "GET", path: "/api/conversations", search: "?limit=3&offset=0" },
    ]);
  });

  it("shows the empty state, not a spinner, when the deployment has no threads", async () => {
    server.use(
      http.get(`${API_BASE}/conversations`, ({ request }) => {
        record(request);
        return HttpResponse.json([]);
      }),
    );
    renderRail();
    expect(await screen.findByText(THREAD_RAIL.empty)).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
  });
});

/* =========================================================================
 * Criterion 6 — the error, and what Retry is allowed to do
 * ========================================================================= */

describe("criterion 6 — the rail's error state", () => {
  it("renders an alert at the top with the dictionary's sentence", async () => {
    listStatus = 502;
    renderRail();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(THREAD_RAIL.error);
    expect(alert).toHaveTextContent(THREAD_RAIL.errorRecovery);
    expect(document.querySelector("[data-thread-rail]")).toHaveAttribute(
      "data-thread-rail-state",
      "error",
    );
  });

  it("re-runs GET /conversations, and reaches no mutation at all", async () => {
    listStatus = 502;
    renderRail();
    await screen.findByRole("alert");
    expect(requests).toHaveLength(1);

    listStatus = 200;
    await user().click(screen.getByRole("button", { name: THREAD_RAIL.retry }));

    await firstPage();
    expect(requests.map((entry) => entry.method)).toEqual(["GET", "GET"]);
    expect(requests.every((entry) => entry.path === "/api/conversations")).toBe(true);
    // Nothing was written, at any point, by a control whose job is to read.
    expect(requests.some((entry) => entry.method !== "GET")).toBe(false);
  });

  it("does not retry on its own — the second request needs the button", async () => {
    listStatus = 502;
    renderRail();
    await screen.findByRole("alert");

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(requests).toHaveLength(1);
  });
});

/* =========================================================================
 * Criterion 7 — "Load more"
 * ========================================================================= */

describe("criterion 7 — Load more appears only when a page came back full", () => {
  it("pages by limit, and stops offering when the page is short", async () => {
    renderRail();
    await firstPage();

    const more = screen.getByRole("button", { name: THREAD_RAIL.loadMore });
    await user().click(more);

    expect(await screen.findByRole("link", { name: "Thread 4" })).toBeInTheDocument();
    expect(requests.map((entry) => entry.search)).toEqual([
      "?limit=3&offset=0",
      "?limit=3&offset=3",
    ]);

    // Five rows, page size three: the second page is short, so there is
    // nothing more to offer. No total was ever needed to know that.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: THREAD_RAIL.loadMore })).toBeNull();
    });
  });

  it("is absent when the whole list fits in one page", async () => {
    renderRail({ limit: 50 });
    await firstPage();
    expect(screen.queryByRole("button", { name: THREAD_RAIL.loadMore })).toBeNull();
  });
});

/* =========================================================================
 * Criteria 1 and 3 — the attached run, and deletion
 * ========================================================================= */

describe("criterion 1 — the attached run's row keeps ?job= through the query layer", () => {
  it("reads the parameter off the route and puts it on that row only", async () => {
    search = new URLSearchParams("job=job-77");
    renderRail({ activeConversationId: "thread-2" });
    await firstPage();

    const live = screen.getByRole("link", { name: /Thread 2/ });
    expect(live).toHaveAttribute("href", "/c/thread-2?job=job-77");
    expect(within(live).getByText(THREAD_ROW.live)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Thread 1" })).toHaveAttribute(
      "href",
      "/c/thread-1",
    );
  });
});

describe("criterion 3 — deletion, end to end", () => {
  async function openConfirmation(title: string) {
    const acting = user();
    await acting.click(screen.getByRole("button", { name: threadMenuLabel(title) }));
    await acting.click(await screen.findByRole("menuitem", { name: THREAD_ROW.delete }));
    await screen.findByRole("dialog");
    return acting;
  }

  it("asks first, then removes the row optimistically and sends one DELETE", async () => {
    renderRail();
    await firstPage();

    const acting = await openConfirmation("Thread 2");
    expect(screen.getByRole("dialog")).toHaveTextContent(deleteDialog("Thread 2").body);
    // Nothing has been sent while the question is on screen.
    expect(requests.filter((entry) => entry.method === "DELETE")).toHaveLength(0);

    await acting.click(
      screen.getByRole("button", { name: deleteDialog("Thread 2").confirm }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "Thread 2" })).toBeNull();
    });
    expect(
      requests.filter((entry) => entry.method === "DELETE").map((entry) => entry.path),
    ).toEqual(["/api/conversations/thread-2"]);
  });

  it("cancelling sends nothing", async () => {
    renderRail();
    await firstPage();

    const acting = await openConfirmation("Thread 2");
    await acting.click(
      screen.getByRole("button", { name: deleteDialog("Thread 2").cancel }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(screen.getByRole("link", { name: "Thread 2" })).toBeInTheDocument();
    expect(requests.every((entry) => entry.method === "GET")).toBe(true);
  });

  it("leaves the thread you were reading when you delete it", async () => {
    const onNavigate = vi.fn();
    renderRail({ activeConversationId: "thread-2", onNavigate });
    await firstPage();

    const acting = await openConfirmation("Thread 2");
    await acting.click(
      screen.getByRole("button", { name: deleteDialog("Thread 2").confirm }),
    );

    await waitFor(() => {
      expect(onNavigate).toHaveBeenCalledWith("/");
    });
  });

  it("stays put when the deleted thread is not the one on screen", async () => {
    const onNavigate = vi.fn();
    renderRail({ activeConversationId: "thread-1", onNavigate });
    await firstPage();

    const acting = await openConfirmation("Thread 2");
    await acting.click(
      screen.getByRole("button", { name: deleteDialog("Thread 2").confirm }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "Thread 2" })).toBeNull();
    });
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("rolls the row back, says so, and offers no retry for a write", async () => {
    deleteStatus = 409;
    renderRail();
    await firstPage();

    const acting = await openConfirmation("Thread 2");
    await acting.click(
      screen.getByRole("button", { name: deleteDialog("Thread 2").confirm }),
    );

    // WO-11's rollback puts the row back in every cached page…
    expect(await screen.findByRole("link", { name: "Thread 2" })).toBeInTheDocument();
    // …and the rail says what happened, with no control that would repeat
    // the write (R-01, H6).
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(THREAD_RAIL.deleteFailed);
    expect(within(alert).queryByRole("button")).toBeNull();

    const deletes = requests.filter((entry) => entry.method === "DELETE");
    expect(deletes).toHaveLength(1);
  });

  it("clears the failure sentence when the next attempt starts", async () => {
    deleteStatus = 409;
    renderRail();
    await firstPage();

    let acting = await openConfirmation("Thread 2");
    await acting.click(
      screen.getByRole("button", { name: deleteDialog("Thread 2").confirm }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(THREAD_RAIL.deleteFailed);

    deleteStatus = 204;
    acting = await openConfirmation("Thread 2");
    expect(screen.queryByRole("alert")).toBeNull();
    await acting.click(
      screen.getByRole("button", { name: deleteDialog("Thread 2").confirm }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "Thread 2" })).toBeNull();
    });
  });
});

/* =========================================================================
 * The client the rail runs on
 * ========================================================================= */

describe("EnsureQueryClient", () => {
  it("uses the app's client when one is mounted, so the cache is shared", async () => {
    const client = testClient();
    render(
      <QueryClientProvider client={client}>
        <EnsureQueryClient>
          <ThreadRail limit={3} />
        </EnsureQueryClient>
      </QueryClientProvider>,
    );

    await firstPage();
    // The rows landed in the client the app owns, not in a private one.
    expect(
      client.getQueryData(queryKeys.conversations.list(3)),
    ).toBeDefined();
  });

  it("creates one when nothing else has, so the rail works before WO-20 mounts Providers", async () => {
    render(
      <EnsureQueryClient>
        <ThreadRail limit={3} />
      </EnsureQueryClient>,
    );
    await firstPage();
    expect(requests).toHaveLength(1);
  });
});
