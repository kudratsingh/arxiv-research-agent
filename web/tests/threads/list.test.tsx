/**
 * WO-14 — the rail's markup: every state, the `?job=` rule, the
 * permanently focusable destructive control, and the reserved height that
 * makes the loading→loaded transition move nothing.
 *
 * Criteria 1, 2, 4, 5, 7 and 8 are asserted here, against
 * `components/patterns/ThreadList.tsx`, because all six are properties of
 * the markup rather than of the query layer — which is exactly why the rail
 * is split in two (04 §5.1). The feature's half is in ./rail.test.tsx.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { useState } from "react";

import { describe, expect, it, vi } from "vitest";

import { EmptyState } from "@/components/patterns/EmptyState";
import {
  ThreadList,
  threadMenuLabel,
  threadRowHref,
  type ThreadSummary,
} from "@/components/patterns/ThreadList";
import { SKELETON_ROW_COUNT } from "@/components/patterns/ThreadRailFrame";
import { THREAD, THREAD_RAIL, THREAD_ROW, deleteDialog } from "@/lib/copy/threads";

import { render, screen, user, waitFor, within } from "../support/render";

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

const THREADS: ThreadSummary[] = [
  { id: "thread-1", title: "Retrieval-augmented verification" },
  { id: "thread-2", title: "Sparse attention survey" },
  { id: "thread-3", title: "Eval harness drift" },
];

/**
 * The pattern's source with its prose removed.
 *
 * The comments name the defect they exist to prevent — "never `opacity-0`",
 * `ConversationSidebar.tsx:133` — so a scan over the raw file would be
 * failed by its own documentation. Stripping comments first is what makes
 * the assertion about the CODE.
 */
const SOURCE = readFileSync(
  path.resolve(__dirname, "..", "..", "components", "patterns", "ThreadList.tsx"),
  "utf8",
)
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

function rows(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>("[data-thread-row]"));
}

/* =========================================================================
 * Criterion 1 — the `?job=` preservation rule (R-02)
 * ========================================================================= */

describe("criterion 1 — the attached run's row keeps ?job=", () => {
  it.each([
    ["no run attached", "thread-1", "thread-1", null, "/c/thread-1"],
    ["the attached thread's own row", "thread-1", "thread-1", "job-9", "/c/thread-1?job=job-9"],
    ["another thread's row", "thread-2", "thread-1", "job-9", "/c/thread-2"],
    ["no active thread at all", "thread-1", null, "job-9", "/c/thread-1"],
  ])("%s", (_name, rowId, activeId, jobId, expected) => {
    expect(threadRowHref(rowId, activeId, jobId)).toBe(expected);
  });

  it("percent-encodes both halves, so a title-shaped id cannot break the URL", () => {
    expect(threadRowHref("a b/c", "a b/c", "j?b&x")).toBe("/c/a%20b%2Fc?job=j%3Fb%26x");
  });

  it("renders the parameter on exactly one row, and marks that row Live", () => {
    render(
      <ThreadList threads={THREADS} activeConversationId="thread-2" attachedJobId="job-9" />,
    );

    const live = screen.getByRole("link", { name: /Sparse attention/ });
    expect(live).toHaveAttribute("href", "/c/thread-2?job=job-9");
    expect(within(live).getByText(THREAD_ROW.live)).toBeInTheDocument();
    expect(live).toHaveAttribute("aria-current", "page");

    expect(screen.getByRole("link", { name: /Retrieval-augmented/ })).toHaveAttribute(
      "href",
      "/c/thread-1",
    );
    expect(document.querySelectorAll("[data-thread-row-live]")).toHaveLength(1);
  });

  it("marks nothing Live when the active thread has no run attached", () => {
    render(<ThreadList threads={THREADS} activeConversationId="thread-2" />);
    expect(screen.queryByText(THREAD_ROW.live)).toBeNull();
    expect(document.querySelectorAll("[data-thread-row-live]")).toHaveLength(0);
  });

  it("hands the navigating caller the same href it rendered", async () => {
    const onNavigate = vi.fn();
    render(
      <ThreadList
        threads={THREADS}
        activeConversationId="thread-1"
        attachedJobId="job-9"
        onNavigate={onNavigate}
      />,
    );

    await user().click(screen.getByRole("link", { name: /Retrieval-augmented/ }));
    expect(onNavigate).toHaveBeenCalledWith("/c/thread-1?job=job-9");
  });
});

/* =========================================================================
 * Criterion 2 — the destructive control
 * ========================================================================= */

describe("criterion 2 — the overflow is permanently focusable", () => {
  it("renders one named overflow button per row, in every row", () => {
    render(<ThreadList threads={THREADS} />);
    for (const thread of THREADS) {
      expect(
        screen.getByRole("button", { name: threadMenuLabel(thread.title) }),
      ).toBeInTheDocument();
    }
  });

  it("names each one after its own thread, so two rows are not one control", () => {
    expect(threadMenuLabel("Sparse attention survey")).toBe(
      `${THREAD_ROW.menuLabel}: Sparse attention survey`,
    );
    // An untitled thread falls back to the dictionary word alone rather
    // than to a dangling colon.
    expect(threadMenuLabel("   ")).toBe(THREAD_ROW.menuLabel);
  });

  it("is reached and operated with the keyboard alone — no pointer event anywhere", async () => {
    render(<ThreadList threads={[THREADS[0] as ThreadSummary]} />);
    const keyboard = user();

    // Tab order: new research → the row's link → the row's overflow.
    await keyboard.tab();
    expect(screen.getByRole("link", { name: THREAD_RAIL.newThread })).toHaveFocus();
    await keyboard.tab();
    expect(screen.getByRole("link", { name: /Retrieval-augmented/ })).toHaveFocus();
    await keyboard.tab();

    const overflow = screen.getByRole("button", {
      name: threadMenuLabel(THREADS[0]?.title ?? ""),
    });
    expect(overflow).toHaveFocus();

    await keyboard.keyboard("{Enter}");
    const menu = await screen.findByRole("menu");
    expect(
      within(menu).getByRole("menuitem", { name: THREAD_ROW.delete }),
    ).toBeInTheDocument();
  });

  it("asks for the confirmation rather than deleting from the menu", async () => {
    const onDeleteRequest = vi.fn();
    render(<ThreadList threads={THREADS} onDeleteRequest={onDeleteRequest} />);

    await user().click(
      screen.getByRole("button", { name: threadMenuLabel(THREADS[1]?.title ?? "") }),
    );
    await user().click(await screen.findByRole("menuitem", { name: THREAD_ROW.delete }));

    expect(onDeleteRequest).toHaveBeenCalledWith(THREADS[1]);
  });

  it("carries no opacity-0 and no group-hover — the ConversationSidebar.tsx:133 defect", () => {
    expect(SOURCE).not.toMatch(/opacity-0/);
    expect(SOURCE).not.toMatch(/group-hover/);
    for (const button of screen.queryAllByRole("button")) {
      expect(button.className).not.toMatch(/opacity-0|group-hover|invisible|hidden/);
    }
  });
});

/* =========================================================================
 * Criterion 3 — the confirmation's focus restoration
 *
 * Radix cannot do this one: it restores focus to `Dialog.Trigger`'s ref,
 * and this dialog is opened by a menu item in a portal. See ThreadList.tsx.
 * ========================================================================= */

describe("criterion 3 — focus comes back from the confirmation", () => {
  function Host({ deleteRow }: { deleteRow?: boolean }) {
    const [pending, setPending] = useState<ThreadSummary | null>(null);
    const [rows, setRows] = useState(THREADS);
    return (
      <ThreadList
        threads={rows}
        pendingDelete={pending}
        onDeleteRequest={setPending}
        onDeleteCancel={() => setPending(null)}
        onDeleteConfirm={() => {
          if (deleteRow) setRows((current) => current.filter((row) => row.id !== pending?.id));
          setPending(null);
        }}
      />
    );
  }

  async function openConfirmation(title: string) {
    const acting = user();
    await acting.click(screen.getByRole("button", { name: threadMenuLabel(title) }));
    await acting.click(await screen.findByRole("menuitem", { name: THREAD_ROW.delete }));
    await screen.findByRole("dialog");
    return acting;
  }

  it("returns focus to the row's own overflow button after Cancel", async () => {
    render(<Host />);
    const title = THREADS[1]?.title ?? "";
    const acting = await openConfirmation(title);

    await acting.click(screen.getByRole("button", { name: deleteDialog(title).cancel }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: threadMenuLabel(title) })).toHaveFocus();
    });
  });

  it("falls back to the rail's first control when that row has just gone", async () => {
    render(<Host deleteRow />);
    const title = THREADS[1]?.title ?? "";
    const acting = await openConfirmation(title);

    await acting.click(
      screen.getByRole("button", { name: deleteDialog(title).confirm }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: threadMenuLabel(title) })).toBeNull();
    });
    // Not `<body>`, which is where Radix would leave it.
    await waitFor(() => {
      expect(screen.getByRole("link", { name: THREAD_RAIL.newThread })).toHaveFocus();
    });
  });
});

/* =========================================================================
 * Criterion 4 — the loading state, and the height that does not move
 * ========================================================================= */

describe("criterion 4 — three reserved rows, no spinner", () => {
  it("renders exactly three skeleton rows with the chrome already drawn", () => {
    render(<ThreadList threads={[]} loading />);

    expect(document.querySelectorAll("[data-thread-row-skeleton]")).toHaveLength(
      SKELETON_ROW_COUNT,
    );
    expect(screen.getByRole("heading", { name: THREAD_RAIL.heading })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: THREAD_RAIL.newThread })).toBeInTheDocument();
    expect(screen.getByRole("list")).toHaveAttribute("aria-busy", "true");
  });

  it("announces the load with aria-busy and a clipped word, never a spinner", () => {
    const { container } = render(<ThreadList threads={[]} loading />);
    expect(screen.getByText(THREAD_RAIL.loading)).toBeInTheDocument();
    expect(container.querySelectorAll("[role='progressbar'], .animate-spin")).toHaveLength(0);
    // 03 §3.7 forbids skeleton shimmer outright, and the primitive has no
    // animation at all — so there is nothing here for reduced motion to
    // take away either.
    expect(container.querySelectorAll(".ew-skeleton")).not.toHaveLength(0);
  });

  /**
   * CLS 0.000, asserted structurally.
   *
   * jsdom has no layout engine, so a pixel measurement here would be
   * theatre. What CAN be proved is the property the pixel measurement would
   * depend on: the loading row and the loaded row are the SAME element type
   * carrying the SAME class, whose height is one declaration in
   * ./threads.css (`--ew-thread-row-height`), and the chrome above them is
   * identical in both states — so there is no element that can move. WO-21
   * measures the CLS number itself in a real engine; this is the invariant
   * that number rests on.
   */
  it("reserves the loaded row's own height, from one declaration", () => {
    const loading = render(<ThreadList threads={[]} loading />);
    const reserved = Array.from(
      loading.container.querySelectorAll("[data-thread-row-skeleton]"),
    );
    expect(reserved).toHaveLength(SKELETON_ROW_COUNT);
    for (const row of reserved) expect(row.className).toContain("ew-thread-row");
    const chromeBefore = loading.container.querySelector(".ew-thread-rail__chrome")?.innerHTML;
    loading.unmount();

    const loaded = render(<ThreadList threads={THREADS} />);
    for (const row of rows()) expect(row.className).toContain("ew-thread-row");
    expect(loaded.container.querySelector(".ew-thread-rail__chrome")?.innerHTML).toBe(
      chromeBefore,
    );

    const css = readFileSync(
      path.resolve(__dirname, "..", "..", "components", "patterns", "threads.css"),
      "utf8",
    );
    expect(css).toContain("min-height: var(--ew-thread-row-height)");
    // One declaration of the value, so the two states cannot drift apart.
    expect(css.match(/--ew-thread-row-height:/g)).toHaveLength(2); // base + coarse pointer
  });
});

/* =========================================================================
 * Criteria 5, 6 and 7 — empty, the alert's position, and "Load more"
 * ========================================================================= */

describe("the chrome's own controls", () => {
  it("sends New research to the landing composer, never to a thread it created", async () => {
    const onNavigate = vi.fn();
    render(<ThreadList threads={THREADS} onNavigate={onNavigate} />);

    const start = screen.getByRole("link", { name: THREAD_RAIL.newThread });
    expect(start).toHaveAttribute("href", "/");
    await user().click(start);

    // A rail button that created a bare thread would spend a rate-limit
    // slot (`routes.py:545`) on a thread with no question in it.
    expect(onNavigate).toHaveBeenCalledWith("/");
  });

  it("opens a thread from the overflow menu as well as from the row", async () => {
    const onNavigate = vi.fn();
    render(
      <ThreadList
        threads={THREADS}
        activeConversationId="thread-1"
        attachedJobId="job-9"
        onNavigate={onNavigate}
      />,
    );

    const acting = user();
    await acting.click(
      screen.getByRole("button", { name: threadMenuLabel(THREADS[0]?.title ?? "") }),
    );
    await acting.click(await screen.findByRole("menuitem", { name: THREAD_ROW.open }));

    // The same href the row carries, `?job=` included.
    expect(onNavigate).toHaveBeenCalledWith("/c/thread-1?job=job-9");
  });
});

describe("the EmptyState pattern the rail renders", () => {
  it("carries a heading and an action when a caller has one", () => {
    render(
      <EmptyState
        heading={THREAD.emptyHeading}
        headingLevel={2}
        body={THREAD.emptyBody}
        action={<button type="button">{THREAD.followUpLabel}</button>}
      />,
    );

    const heading = screen.getByRole("heading", { name: THREAD.emptyHeading });
    expect(heading.tagName).toBe("H2");
    expect(screen.getByText(THREAD.emptyBody)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: THREAD.followUpLabel }),
    ).toBeInTheDocument();
  });

  it("is a sentence and nothing else by default, which is what the rail wants", () => {
    render(<EmptyState body={THREAD_RAIL.empty} />);
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.getByText(THREAD_RAIL.empty)).toBeInTheDocument();
  });
});

describe("criterion 5 — the empty state is its own state", () => {
  it("says 03 §2.2 row 3's sentence, with no busy list and no alert", () => {
    render(<ThreadList threads={[]} />);
    expect(screen.getByText(THREAD_RAIL.empty)).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.querySelector("[data-thread-rail]")).toHaveAttribute(
      "data-thread-rail-state",
      "empty",
    );
  });

  it("is not what a loading rail shows", () => {
    render(<ThreadList threads={[]} loading />);
    expect(screen.queryByText(THREAD_RAIL.empty)).toBeNull();
    expect(document.querySelector("[data-empty-state]")).toBeNull();
  });
});

describe("criterion 6 — the alert sits at the top of the rail", () => {
  const notice = {
    sentence: THREAD_RAIL.error,
    recovery: THREAD_RAIL.errorRecovery,
    retryLabel: THREAD_RAIL.retry,
  };

  it("renders role=alert above the list, with the retry beside it", () => {
    const onRetry = vi.fn();
    const { container } = render(
      <ThreadList threads={THREADS} notice={{ ...notice, onRetry }} />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(THREAD_RAIL.error);
    expect(alert).toHaveTextContent(THREAD_RAIL.errorRecovery);

    const list = screen.getByRole("list");
    // DOCUMENT_POSITION_FOLLOWING: the list comes after the alert.
    expect(alert.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // And the alert comes after the chrome, so the rail's controls do not move.
    const chrome = container.querySelector(".ew-thread-rail__chrome") as HTMLElement;
    expect(chrome.compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("has no retry at all when the notice is about a failed write", () => {
    render(<ThreadList threads={THREADS} notice={{ sentence: THREAD_RAIL.deleteFailed }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(THREAD_RAIL.deleteFailed);
    expect(screen.queryByRole("button", { name: THREAD_RAIL.retry })).toBeNull();
  });

  it("runs the retry the caller gave it, and nothing else", async () => {
    const onRetry = vi.fn();
    render(<ThreadList threads={[]} notice={{ ...notice, onRetry }} />);
    await user().click(screen.getByRole("button", { name: THREAD_RAIL.retry }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("criterion 7 — Load more", () => {
  it("is absent unless a page came back full", () => {
    render(<ThreadList threads={THREADS} />);
    expect(screen.queryByRole("button", { name: THREAD_RAIL.loadMore })).toBeNull();
  });

  it("appears when there is another page, and says nothing about how many", async () => {
    const onLoadMore = vi.fn();
    render(<ThreadList threads={THREADS} canLoadMore onLoadMore={onLoadMore} />);

    const more = screen.getByRole("button", { name: THREAD_RAIL.loadMore });
    await user().click(more);
    expect(onLoadMore).toHaveBeenCalledTimes(1);
    // No total and no page number: `GET /conversations` supplies neither.
    expect(document.body.textContent).not.toMatch(/\d+\s*(?:of|\/)\s*\d+/);
  });

  it("refuses the second press while a page is in flight", async () => {
    const onLoadMore = vi.fn();
    render(<ThreadList threads={THREADS} canLoadMore isLoadingMore onLoadMore={onLoadMore} />);

    const more = screen.getByRole("button", { name: THREAD_RAIL.loadMore });
    expect(more).toHaveAttribute("aria-busy", "true");
    await user().click(more);
    expect(onLoadMore).not.toHaveBeenCalled();
  });
});

/* =========================================================================
 * Criterion 8 — the reserved owner slot
 * ========================================================================= */

describe("criterion 8 — the owner slot", () => {
  it("is in every row, empty, and says nothing", () => {
    render(<ThreadList threads={THREADS} activeConversationId="thread-1" />);
    const slots = document.querySelectorAll("[data-thread-owner-slot]");
    expect(slots).toHaveLength(THREADS.length);

    for (const slot of slots) {
      expect(slot.textContent).toBe("");
      expect(slot.children).toHaveLength(0);
      // No badge, no placeholder, and no name — a named empty slot would be
      // announced as an owner that does not exist (03 §6, seam S6).
      expect(slot.getAttribute("aria-label")).toBeNull();
      expect(slot.getAttribute("title")).toBeNull();
    }
  });

  it("is zero-height by rule, not by being absent", () => {
    const css = readFileSync(
      path.resolve(__dirname, "..", "..", "components", "patterns", "threads.css"),
      "utf8",
    );
    expect(css).toMatch(/\.ew-thread-row__owner\s*\{[^}]*height:\s*0/);
    expect(css).toMatch(/\.ew-thread-row__owner\s*\{[^}]*display:\s*block/);
  });

  it("renders no ownership copy anywhere in a populated rail", () => {
    render(<ThreadList threads={THREADS} />);
    expect(document.body.textContent).not.toMatch(
      /owner|owned by|your threads|shared with/i,
    );
  });
});

/* =========================================================================
 * The list's own name and the rail's state hook
 * ========================================================================= */

describe("the rail names itself and publishes its state", () => {
  it("labels the list by the rail's heading", () => {
    render(<ThreadList threads={THREADS} />);
    const heading = screen.getByRole("heading", { name: THREAD_RAIL.heading });
    expect(screen.getByRole("list")).toHaveAttribute("aria-labelledby", heading.id);
  });

  it.each([
    ["loading", <ThreadList key="l" threads={[]} loading />],
    ["empty", <ThreadList key="e" threads={[]} />],
    ["list", <ThreadList key="p" threads={THREADS} />],
    [
      "error",
      <ThreadList
        key="x"
        threads={[]}
        notice={{ sentence: THREAD_RAIL.error, retryLabel: THREAD_RAIL.retry, onRetry: () => {} }}
      />,
    ],
  ])("publishes data-thread-rail-state=%s for WO-21", (state, element) => {
    render(element);
    expect(document.querySelector("[data-thread-rail]")).toHaveAttribute(
      "data-thread-rail-state",
      state,
    );
  });
});
