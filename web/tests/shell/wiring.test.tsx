/**
 * WO-08 — the `(workspace)` layout's wiring, and the three stores the shell
 * reads the browser through.
 *
 * Two things are proven here that the shell's own tests deliberately cannot
 * be, because they pass `rail` and therefore never touch the data layer:
 *
 *   1. The layout hands the shell a real rail, and that rail behaves the
 *      way `ConversationsShell` behaved — same navigation, same active
 *      thread. The move into a layout must not change navigation.
 *   2. The server snapshots. `useSyncExternalStore` calls
 *      `getServerSnapshot` only during hydration, which no jsdom render
 *      reaches, so the three values are pinned directly. They are not
 *      arbitrary: each one is the value whose CSS the client's answer
 *      overrides rather than the other way round.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ThreadRailBridge, { activeConversationIdFrom } from "@/components/app/ThreadRailBridge";
import WorkspaceLayout from "@/app/(workspace)/layout";
import {
  WorkbenchShell,
  readOffline,
  readRailMode,
  serverOffline,
  serverRailCollapsed,
  serverRailMode,
  writeRailCollapsed,
} from "@/components/app/WorkbenchShell";
import { serverThemePreference } from "@/components/patterns/ThemeToggle";
import { THREAD_RAIL } from "@/lib/copy/threads";
import { SHELL } from "@/lib/copy/shell";
import { RAIL_COLLAPSED_STORAGE_KEY } from "@/lib/tokens";

import { act, render, screen, user, waitFor, within } from "../support/render";
import { MODE_WIDTHS, installMatchMedia, uninstallMatchMedia } from "./support";

const push = vi.fn();
let pathname = "/";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  usePathname: () => pathname,
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

const originalFetch = globalThis.fetch;

function installFetch(): void {
  globalThis.fetch = vi.fn(async () =>
    new Response(
      JSON.stringify([
        { conversation_id: "conv-1", title: "Retrieval-augmented verification", updated_at: 0 },
        { conversation_id: "conv-2", title: "Sparse attention survey", updated_at: 0 },
      ]),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  ) as unknown as typeof fetch;
}

beforeEach(() => {
  installMatchMedia({ width: MODE_WIDTHS.expanded });
  installFetch();
  push.mockClear();
  pathname = "/";
  window.localStorage.clear();
});

afterEach(() => {
  uninstallMatchMedia();
  globalThis.fetch = originalFetch;
  window.localStorage.clear();
});

/* =========================================================================
 * The layout
 * ========================================================================= */

describe("the (workspace) layout mounts the shell around its children", () => {
  it("renders the shell's landmarks around whatever the route is", async () => {
    // `await WorkspaceLayout(...)` rather than `<WorkspaceLayout/>`: WO-W17b
    // made it an async server component so it can resolve the request's
    // identity descriptor, and `createRoot` cannot render one of those. It is
    // the form `tests/fonts.test.ts` and `tests/tokens.test.ts` already use
    // for the async root layout. Every assertion below is unchanged.
    render(await WorkspaceLayout({ children: <h1>A route</h1> }));

    expect(document.querySelectorAll("main")).toHaveLength(1);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: THREAD_RAIL.heading })).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByRole("heading", { name: "A route" })).toBeInTheDocument();

    // The real rail, with the real client behind it.
    expect(await screen.findByRole("link", { name: /retrieval-augmented/i })).toBeInTheDocument();
  });
});

/* =========================================================================
 * The rail bridge
 * ========================================================================= */

describe("ThreadRailBridge preserves ConversationsShell's navigation", () => {
  it.each([
    ["/", null],
    ["/c/conv-1", "conv-1"],
    ["/c/conv%2F1%202", "conv/1 2"],
    ["/c/conv-1/extra", "conv-1"],
    [null, null],
  ])("derives the active thread from %s", (input, expected) => {
    expect(activeConversationIdFrom(input)).toBe(expected);
  });

  it("keeps a malformed escape sequence rather than blanking the rail", () => {
    expect(activeConversationIdFrom("/c/%E0%A4%A")).toBe("%E0%A4%A");
  });

  it("pushes /c/<id> exactly as the previous shell did", async () => {
    pathname = "/c/conv-1";
    render(<ThreadRailBridge />);

    await user().click(await screen.findByRole("link", { name: /sparse attention/i }));
    expect(push).toHaveBeenCalledWith("/c/conv-2");
  });
});

/* =========================================================================
 * The stores
 * ========================================================================= */

describe("the server snapshots", () => {
  it("claims the expanded mode, which is what the CSS paints at desktop widths", () => {
    expect(serverRailMode()).toBe("expanded");
  });

  it("claims an expanded rail, because a server has no storage to read", () => {
    expect(serverRailCollapsed()).toBe(false);
  });

  it("claims online, because a server cannot know otherwise", () => {
    expect(serverOffline()).toBe(false);
  });

  it("claims the `system` theme preference, never a theme", () => {
    expect(serverThemePreference()).toBe("system");
  });
});

describe("the mode store degrades rather than throws", () => {
  it("falls back to the expanded mode where matchMedia does not exist", () => {
    uninstallMatchMedia();
    const stored = window.matchMedia;
    // @ts-expect-error — deliberately removing a browser API.
    delete window.matchMedia;
    try {
      expect(readRailMode()).toBe("expanded");
      expect(() =>
        render(
          <WorkbenchShell rail={<nav aria-label="ignored" />}>
            <p>surface</p>
          </WorkbenchShell>,
        ),
      ).not.toThrow();
    } finally {
      window.matchMedia = stored;
      installMatchMedia({ width: MODE_WIDTHS.expanded });
    }
  });
});

describe("the collapse store", () => {
  it("reacts to a write from another tab", async () => {
    const { container } = render(
      <WorkbenchShell rail={<p>rail</p>} railMode="expanded">
        <p>surface</p>
      </WorkbenchShell>,
    );
    expect(container.querySelector("[data-rail-collapsed]")).toHaveAttribute(
      "data-rail-collapsed",
      "false",
    );

    await act(async () => {
      window.localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, "1");
      window.dispatchEvent(new StorageEvent("storage", { key: RAIL_COLLAPSED_STORAGE_KEY }));
    });

    expect(container.querySelector("[data-rail-collapsed]")).toHaveAttribute(
      "data-rail-collapsed",
      "true",
    );
  });

  it("swallows a storage write that throws", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage is partitioned");
    });
    try {
      expect(() => writeRailCollapsed(true)).not.toThrow();
    } finally {
      setItem.mockRestore();
    }
  });
});

describe("the offline store", () => {
  it("reads navigator.onLine", () => {
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    try {
      expect(readOffline()).toBe(true);
    } finally {
      online.mockRestore();
    }
  });

  it("re-reads it on the browser's own offline and online events", async () => {
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    try {
      render(
        <WorkbenchShell rail={<p>rail</p>} railMode="expanded">
          <p>surface</p>
        </WorkbenchShell>,
      );
      expect(screen.queryByText(SHELL.offline)).toBeNull();

      online.mockReturnValue(false);
      await act(async () => {
        window.dispatchEvent(new Event("offline"));
      });
      await waitFor(() => expect(screen.getByText(SHELL.offline)).toBeInTheDocument());

      online.mockReturnValue(true);
      await act(async () => {
        window.dispatchEvent(new Event("online"));
      });
      await waitFor(() => expect(screen.queryByText("Offline")).toBeNull());
    } finally {
      online.mockRestore();
    }
  });
});
