/**
 * WO-08 criteria 1, 3, 9 and 10 — landmarks, the three modes, the identity
 * slot, and the skip link.
 *
 * These are the assertions that do not need a browser. The ones that do —
 * the axe run across every audited state (criterion 1's second sentence),
 * the 380px work surface at 412px (criterion 4), the reflow sweep
 * (criterion 5) and the no-flash theme (criterion 8's second half) — are
 * WO-21's, per the WO-01-c5 precedent, and the shell publishes
 * `data-rail-mode` / `data-rail-collapsed` / `data-workbench-region` so
 * that harness can assert a mode instead of inferring one from a pixel
 * width.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MAIN_ID,
  RAIL_ID,
  WORKBENCH_COMPOSER_SLOT_ID,
  WORKSPACE_INDICATOR,
  WorkbenchShell,
  readRailCollapsed,
  readRailMode,
} from "@/components/app/WorkbenchShell";
import { SHELL } from "@/lib/copy/shell";
import { THREAD_RAIL, WORKSPACE } from "@/lib/copy/threads";
import { RAIL_COLLAPSED_STORAGE_KEY } from "@/lib/tokens";

import { act, render, screen, user, within } from "../support/render";
import { MODE_WIDTHS, installMatchMedia, setViewportWidth, uninstallMatchMedia } from "./support";

// `next/link` needs an App Router context this bare render has no reason to
// build; the same stand-in web/tests/HomePage.test.tsx uses.
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

/** A rail with the legacy sidebar's markup shape and no network behind it. */
function Rail() {
  return (
    <aside className="flex h-full w-rail shrink-0 flex-col">
      <ul>
        <li>
          <a href="/c/thread-1">Retrieval-augmented verification</a>
        </li>
      </ul>
    </aside>
  );
}

function Surface() {
  return (
    <div>
      <h1>Retrieval-augmented verification</h1>
    </div>
  );
}

function renderShell(props: Partial<React.ComponentProps<typeof WorkbenchShell>> = {}) {
  return render(
    <WorkbenchShell rail={<Rail />} {...props}>
      <Surface />
    </WorkbenchShell>,
  );
}

beforeEach(() => {
  installMatchMedia({ width: MODE_WIDTHS.expanded });
  window.localStorage.clear();
});

afterEach(() => {
  uninstallMatchMedia();
  window.localStorage.clear();
});

/* =========================================================================
 * Criterion 1 — landmarks
 * ========================================================================= */

describe("criterion 1 — exactly one main, and every landmark named", () => {
  it("renders exactly one <main id=\"main\"> per document", () => {
    renderShell();
    const mains = document.querySelectorAll("main");
    expect(mains).toHaveLength(1);
    expect(mains[0]).toHaveAttribute("id", MAIN_ID);
    // The id is what SkipLink points at by default, so the two cannot
    // disagree without this failing.
    expect(document.getElementById(MAIN_ID)?.tagName).toBe("MAIN");
  });

  it("renders one banner and one named navigation", () => {
    renderShell();
    expect(screen.getAllByRole("banner")).toHaveLength(1);
    const navs = screen.getAllByRole("navigation");
    expect(navs).toHaveLength(1);
    expect(navs[0]).toHaveAccessibleName(THREAD_RAIL.heading);
    expect(navs[0]).toHaveAttribute("id", RAIL_ID);
  });

  it("puts every element between the skip link and the end inside a landmark", () => {
    const { container } = renderShell();
    // The shell's own children, in order: the skip link (which axe's
    // `region` rule exempts) and the grid. Everything the grid contains is
    // header / nav / main.
    const shell = container.querySelector("[data-workbench-shell]");
    expect(shell).not.toBeNull();
    const tags = [...(shell?.children ?? [])].map((child) => child.tagName);
    expect(tags).toEqual(["HEADER", "NAV", "MAIN"]);
  });

  it("does not render a second main when the rail is a drawer", () => {
    renderShell({ railMode: "drawer" });
    expect(document.querySelectorAll("main")).toHaveLength(1);
    // 04 §8.3 item 1: below md the rail is not in the layout AT ALL.
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});

/* =========================================================================
 * Criterion 10 — the skip link
 * ========================================================================= */

describe("criterion 10 — the skip link is first in tab order and targets #main", () => {
  it("is the first focusable element in the document", async () => {
    renderShell();
    const link = screen.getByRole("link", { name: WORKSPACE.skipToContent });
    await user().tab();
    expect(link).toHaveFocus();
  });

  it("points at the id the main region carries", () => {
    renderShell();
    const link = screen.getByRole("link", { name: WORKSPACE.skipToContent });
    expect(link).toHaveAttribute("href", `#${MAIN_ID}`);
    // The target really exists — axe's `skip-link` rule checks exactly this.
    expect(document.querySelector(`#${MAIN_ID}`)).not.toBeNull();
  });

  it("comes before the header in document order", () => {
    const { container } = renderShell();
    const link = screen.getByRole("link", { name: WORKSPACE.skipToContent });
    const header = container.querySelector("header");
    expect(link.compareDocumentPosition(header as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
});

/* =========================================================================
 * Criterion 3 — the three modes
 * ========================================================================= */

describe("criterion 3 — three layout modes, derived from the viewport", () => {
  it.each([
    [MODE_WIDTHS.drawer, "drawer"],
    [MODE_WIDTHS.compact, "compact"],
    [MODE_WIDTHS.expanded, "expanded"],
  ])("resolves %ipx to the %s mode", (width, mode) => {
    installMatchMedia({ width });
    expect(readRailMode()).toBe(mode);
  });

  it("re-reads the mode when the viewport crosses a breakpoint", async () => {
    installMatchMedia({ width: MODE_WIDTHS.expanded });
    const { container } = renderShell();
    expect(container.querySelector("[data-rail-mode]")).toHaveAttribute(
      "data-rail-mode",
      "expanded",
    );

    await act(async () => {
      setViewportWidth(MODE_WIDTHS.drawer);
    });

    expect(container.querySelector("[data-rail-mode]")).toHaveAttribute(
      "data-rail-mode",
      "drawer",
    );
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("shows the full rail at >=1024px", () => {
    renderShell({ railMode: "expanded", railCollapsed: false });
    const nav = screen.getByRole("navigation", { name: THREAD_RAIL.heading });
    expect(within(nav).getByRole("link", { name: /retrieval-augmented/i })).toBeInTheDocument();
    expect(
      within(nav).getByRole("button", { name: THREAD_RAIL.collapse }),
    ).toBeInTheDocument();
  });

  it("shows a 56px icon strip between 768px and 1023px, every control named", () => {
    renderShell({ railMode: "compact" });
    const nav = screen.getByRole("navigation", { name: THREAD_RAIL.heading });
    // The thread list is NOT in the strip; it is one control away.
    expect(within(nav).queryByRole("link", { name: /retrieval-augmented/i })).toBeNull();

    const named = [
      ...within(nav).getAllByRole("link"),
      ...within(nav).getAllByRole("button"),
    ];
    expect(named.length).toBeGreaterThan(0);
    for (const control of named) {
      expect(control).toHaveAccessibleName();
      expect(control.getAttribute("aria-label") ?? control.textContent ?? "").not.toBe("");
    }
    expect(within(nav).getByRole("link", { name: SHELL.newQuestion })).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: THREAD_RAIL.openDrawer })).toBeInTheDocument();
    // RC-04: no collapse toggle below 1024px, because collapsed IS the
    // default down there.
    expect(within(nav).queryByRole("button", { name: /rail/i })).toBeNull();
  });
});

/* =========================================================================
 * Criterion 3 — the persisted collapse preference (RC-05)
 * ========================================================================= */

describe("criterion 3 — the collapse toggle persists to RAIL_COLLAPSED_STORAGE_KEY", () => {
  it("writes the reserved key, and nothing else", async () => {
    renderShell({ railMode: "expanded" });
    await user().click(screen.getByRole("button", { name: THREAD_RAIL.collapse }));

    expect(window.localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe("1");
    // RC-05 allows exactly two keys product-wide, and the other is WO-01's.
    expect(window.localStorage.length).toBe(1);
    expect(window.localStorage.key(0)).toBe(RAIL_COLLAPSED_STORAGE_KEY);
  });

  it("collapses the rail to the strip and back", async () => {
    renderShell({ railMode: "expanded" });
    await user().click(screen.getByRole("button", { name: THREAD_RAIL.collapse }));

    const nav = screen.getByRole("navigation", { name: THREAD_RAIL.heading });
    expect(within(nav).queryByRole("link", { name: /retrieval-augmented/i })).toBeNull();
    expect(within(nav).getByRole("button", { name: THREAD_RAIL.expand })).toBeInTheDocument();

    await user().click(screen.getByRole("button", { name: THREAD_RAIL.expand }));
    expect(
      within(screen.getByRole("navigation", { name: THREAD_RAIL.heading })).getByRole("link", {
        name: /retrieval-augmented/i,
      }),
    ).toBeInTheDocument();
  });

  it("restores the stored preference on the next render", () => {
    window.localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, "1");
    expect(readRailCollapsed()).toBe(true);
    const { container } = renderShell({ railMode: "expanded" });
    expect(container.querySelector("[data-rail-collapsed]")).toHaveAttribute(
      "data-rail-collapsed",
      "true",
    );
  });

  it("is ignored below 1024px, where collapsed is the default (RC-04)", () => {
    window.localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, "0");
    const { container } = renderShell({ railMode: "compact" });
    expect(container.querySelector("[data-rail-collapsed]")).toHaveAttribute(
      "data-rail-collapsed",
      "true",
    );
  });

  it("treats a storage-blocked context as expanded rather than throwing", () => {
    const getItem = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("storage is partitioned");
      });
    try {
      expect(readRailCollapsed()).toBe(false);
      expect(() => renderShell({ railMode: "expanded" })).not.toThrow();
    } finally {
      getItem.mockRestore();
    }
  });
});

/* =========================================================================
 * Criterion 9 — the workspace indicator and the empty identity slot
 * ========================================================================= */

describe("criterion 9 — a workspace indicator, and no fake login", () => {
  it("carries the §6 indicator string verbatim, in the header", () => {
    const { container } = renderShell();
    const header = container.querySelector("header");
    expect(header).not.toBeNull();
    // Rendered as a lead plus its qualification, so the assertion is on
    // the header's text rather than on one node: the qualification is the
    // honest half and must not be droppable.
    const headerText = (header as HTMLElement).textContent ?? "";
    expect(headerText).toContain(WORKSPACE.indicator);
    expect(headerText).toContain(WORKSPACE.indicatorDetail);
    expect(WORKSPACE_INDICATOR).toContain(WORKSPACE.indicatorDetail);
    // Seam S6: no ownership language anywhere in the shell.
    expect(WORKSPACE_INDICATOR).toMatch(/^Shared workspace/);
    expect(document.body.textContent ?? "").not.toMatch(/your (threads|conversations|workspace)/i);
  });

  it("renders no avatar, no sign-in and no disabled login (D-009)", () => {
    renderShell();
    expect(document.querySelectorAll("img")).toHaveLength(0);
    for (const control of [...screen.queryAllByRole("button"), ...screen.queryAllByRole("link")]) {
      const name = control.getAttribute("aria-label") ?? control.textContent ?? "";
      expect(name).not.toMatch(/sign\s?(in|out)|log\s?(in|out)|account|profile/i);
      // "A disabled login button is still a fake login" — so there must be
      // no disabled control at all in the header chrome.
      expect(control).not.toBeDisabled();
    }
  });
});

/* =========================================================================
 * The composer slot (criterion 7's DOM half) and the offline state
 * ========================================================================= */

describe("the reserved composer slot", () => {
  it("is the last row of main, and is empty in M1", () => {
    renderShell();
    const main = document.getElementById(MAIN_ID);
    const slot = document.getElementById(WORKBENCH_COMPOSER_SLOT_ID);
    expect(slot).not.toBeNull();
    expect(slot?.parentElement).toBe(main);
    expect(main?.lastElementChild).toBe(slot);
    expect(slot?.childElementCount).toBe(0);
    expect(slot).toHaveAttribute("data-workbench-region", "composer");
  });
});

describe("the offline state", () => {
  it("states it without adding a third live region (03 §7.3)", () => {
    const { container } = renderShell({ offline: true });
    expect(container.querySelector("[data-workbench-offline]")).not.toBeNull();
    expect(screen.getByText(SHELL.offline)).toBeInTheDocument();
    expect(document.querySelectorAll('[role="status"], [role="alert"], [aria-live]')).toHaveLength(
      0,
    );
  });

  it("says nothing when online", () => {
    const { container } = renderShell({ offline: false });
    expect(container.querySelector("[data-workbench-offline]")).toBeNull();
    expect(screen.queryByText(SHELL.offline)).toBeNull();
  });
});
