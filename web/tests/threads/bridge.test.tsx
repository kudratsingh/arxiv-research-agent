/**
 * WO-14 criterion 1 — the swap, and the R-02 test the card asks for by
 * name: "a test navigates from a running thread's own rail row and asserts
 * the job stays attached".
 *
 * This is the only file that exercises the whole chain the user actually
 * touches — `app/(workspace)/layout.tsx` → `ThreadRailBridge` → the lazy
 * `ThreadRail` → `ThreadList` → the router — with a real query client and a
 * real HTTP layer under it. Everything else in this directory tests one
 * link of that chain.
 *
 * WHAT R-02 IS. `03-DESIGN-BRIEF.md` §2.1: "a thread row in the rail that
 * points at the thread you are currently running loses `?job=`. Today that
 * silently detaches a paid run." `ConversationThread.tsx:132-142` writes the
 * parameter at most once per job id and deliberately does NOT rewrite it
 * when the URL loses it — its own comment names the sidebar link as the way
 * that happens — so the detachment is permanent for that run. The row for
 * the attached thread therefore has to carry the parameter itself, and this
 * file is where that is proved end to end.
 */

import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ThreadRailBridge, {
  ThreadRailFallback,
  activeConversationIdFrom,
} from "@/components/app/ThreadRailBridge";
import { ThreadList, threadMenuLabel } from "@/components/patterns/ThreadList";
import { SKELETON_ROW_COUNT } from "@/components/patterns/ThreadRailFrame";
import { API_BASE, type ConversationListItem } from "@/lib/api/index";
import { THREAD_RAIL, THREAD_ROW } from "@/lib/copy/threads";

import { handlers, setupMswServer } from "../support/msw";
import { render, screen, user, waitFor, within } from "../support/render";

const push = vi.fn();
let pathname = "/";
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  usePathname: () => pathname,
  useSearchParams: () => search,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const ROWS: ConversationListItem[] = [
  {
    conversation_id: "conv-1",
    title: "Retrieval-augmented verification",
    created_at: 0,
    updated_at: 2,
  },
  { conversation_id: "conv-2", title: "Sparse attention survey", created_at: 0, updated_at: 1 },
];

setupMswServer(
  http.get(`${API_BASE}/conversations`, () => HttpResponse.json(ROWS)),
  ...handlers,
);

beforeEach(() => {
  push.mockClear();
  pathname = "/";
  search = new URLSearchParams();
});

/**
 * Wait for the rows, across two boundaries rather than one.
 *
 * The rail's chunk has to arrive AND its first page has to land, so this
 * wait is longer than Testing Library's one-second default: under a full
 * parallel run the module runner's first transform of the rail's graph can
 * take most of that second on its own, and a timeout there would be a slow
 * machine reported as a broken rail.
 */
async function railRows(): Promise<void> {
  await screen.findByRole("link", { name: /Retrieval-augmented/ }, { timeout: 10_000 });
}

/* =========================================================================
 * Criterion 1 — R-02
 * ========================================================================= */

describe("criterion 1 — navigating from the running thread's own row", () => {
  it("keeps ?job= attached, and pushes exactly the href it rendered", async () => {
    pathname = "/c/conv-1";
    search = new URLSearchParams("job=job-77");

    render(<ThreadRailBridge />);
    await railRows();

    const row = screen.getByRole("link", { name: /Retrieval-augmented/ });
    expect(row).toHaveAttribute("href", "/c/conv-1?job=job-77");
    expect(within(row).getByText(THREAD_ROW.live)).toBeInTheDocument();

    await user().click(row);

    // The paid run survives the navigation. Before WO-14 this pushed
    // `/c/conv-1` and the thread never wrote the parameter back.
    expect(push).toHaveBeenCalledWith("/c/conv-1?job=job-77");
    expect(push).not.toHaveBeenCalledWith("/c/conv-1");
  });

  it("does not carry that run onto another thread's row", async () => {
    pathname = "/c/conv-1";
    search = new URLSearchParams("job=job-77");

    render(<ThreadRailBridge />);
    await railRows();

    const other = screen.getByRole("link", { name: /Sparse attention/ });
    expect(other).toHaveAttribute("href", "/c/conv-2");
    await user().click(other);
    expect(push).toHaveBeenCalledWith("/c/conv-2");
  });

  it("marks nothing Live when the route has no run attached", async () => {
    pathname = "/c/conv-1";
    render(<ThreadRailBridge />);
    await railRows();

    expect(screen.queryByText(THREAD_ROW.live)).toBeNull();
    expect(screen.getByRole("link", { name: /Retrieval-augmented/ })).toHaveAttribute(
      "href",
      "/c/conv-1",
    );
  });
});

/* =========================================================================
 * What the swap preserves
 * ========================================================================= */

describe("the swap keeps ConversationsShell's navigation contract", () => {
  it.each([
    ["/", null],
    ["/c/conv-1", "conv-1"],
    ["/c/conv%2F1%202", "conv/1 2"],
    ["/c/conv-1/extra", "conv-1"],
    [null, null],
  ])("derives the active thread from %s", (input, expected) => {
    expect(activeConversationIdFrom(input)).toBe(expected);
  });

  it("marks the row for the route it is on", async () => {
    pathname = "/c/conv-2";
    render(<ThreadRailBridge />);
    await railRows();

    expect(screen.getByRole("link", { name: /Sparse attention/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("link", { name: /Retrieval-augmented/ }),
    ).not.toHaveAttribute("aria-current");
  });

  it("renders the new rail, not the legacy sidebar", async () => {
    render(<ThreadRailBridge />);
    await railRows();

    // The rail's own chrome…
    expect(screen.getByRole("heading", { name: THREAD_RAIL.heading })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: THREAD_RAIL.newThread })).toBeInTheDocument();
    // …and none of `ConversationSidebar`'s, which stays on disk until WO-31.
    expect(screen.queryByRole("button", { name: /New conversation/i })).toBeNull();
    expect(document.body.textContent).not.toMatch(/Recent|conversation/i);
    // Every row has the permanently focusable overflow the sidebar hid
    // behind `opacity-0 group-hover:opacity-100`.
    for (const row of ROWS) {
      expect(
        screen.getByRole("button", { name: threadMenuLabel(row.title) }),
      ).toBeInTheDocument();
    }
  });
});

/* =========================================================================
 * The lazy boundary
 * ========================================================================= */

describe("the rail arrives lazily, and the seam does not show", () => {
  it("renders the loading state's own chrome and rows until the chunk lands", async () => {
    render(<ThreadRailBridge />);

    // The fallback IS the loading state: same chrome, same three rows, same
    // height — so the chunk boundary cannot shift anything.
    expect(document.querySelectorAll("[data-thread-row-skeleton]")).toHaveLength(
      SKELETON_ROW_COUNT,
    );
    expect(screen.getByRole("heading", { name: THREAD_RAIL.heading })).toBeInTheDocument();
    expect(document.querySelector("[data-thread-rail]")).toHaveAttribute(
      "data-thread-rail-state",
      "loading",
    );

    await railRows();
    await waitFor(() => {
      expect(document.querySelectorAll("[data-thread-row-skeleton]")).toHaveLength(0);
    });
  });

  /**
   * The fallback and the rail's own loading state are the SAME TREE.
   *
   * This is criterion 4's structural claim at the chunk boundary rather
   * than at the query boundary: if these two differed by so much as a
   * wrapper element, the moment the lazy chunk resolved would move
   * something, and no amount of matching row heights would save it. Node
   * for node, both are `ThreadRailFrame` + `ThreadListSkeleton`.
   */
  it("renders the same markup from the fallback as the rail's own loading state", () => {
    const { container, unmount } = render(<ThreadRailFallback />);
    const fallback = container.innerHTML;
    unmount();

    const { container: loading } = render(<ThreadList threads={[]} loading />);
    expect(loading.innerHTML).toBe(fallback);
  });
});
