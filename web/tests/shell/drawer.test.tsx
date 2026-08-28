/**
 * WO-08 criterion 6 — the drawer is an APG dialog.
 *
 * "focus trapped, Escape closes, focus restored to the trigger; the trigger
 * is a labelled header button, never hover-only."
 *
 * Four assertions, and the fourth is the one the baseline actually failed:
 * `ConversationSidebar.tsx:133` reveals its destructive control with
 * `opacity-0 group-hover:opacity-100`, so this file also asserts that the
 * drawer's own trigger is reachable and named without any pointer event at
 * all — it is found by role and name, and operated with the keyboard.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkbenchShell } from "@/components/app/WorkbenchShell";
import { THREAD_RAIL } from "@/lib/copy/threads";

import { render, screen, user, waitFor, within } from "../support/render";
import { MODE_WIDTHS, installMatchMedia, uninstallMatchMedia } from "./support";

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

function Rail() {
  // `preventDefault` only so jsdom does not log "navigation to another
  // Document" on the click test below. The drawer's own handler is on an
  // ancestor and still sees the bubbling event, which is the thing under
  // test.
  return (
    <ul>
      {[
        ["/c/thread-1", "Retrieval-augmented verification"],
        ["/c/thread-2", "Sparse attention survey"],
      ].map(([href, title]) => (
        <li key={href}>
          <a href={href} onClick={(event) => event.preventDefault()}>
            {title}
          </a>
        </li>
      ))}
    </ul>
  );
}

function renderShell(props: Partial<React.ComponentProps<typeof WorkbenchShell>> = {}) {
  return render(
    <WorkbenchShell rail={<Rail />} railMode="drawer" {...props}>
      <div>
        <h1>Work surface</h1>
        <button type="button">A control behind the drawer</button>
      </div>
    </WorkbenchShell>,
  );
}

/**
 * Open the drawer and wait for its lazily-imported module to arrive.
 *
 * `hidden: true` on every query for something OUTSIDE the dialog is not a
 * workaround — it is the modal contract working. Radix puts
 * `aria-hidden="true"` on the rest of the document, so Testing Library's
 * accessibility-tree queries correctly stop finding the trigger the moment
 * the dialog opens. Asserting on the element captured beforehand is what
 * lets a test talk about a node the user can no longer reach.
 */
async function openDrawer(): Promise<{ dialog: HTMLElement; trigger: HTMLElement }> {
  const trigger = screen.getByRole("button", { name: THREAD_RAIL.openDrawer });
  await user().click(trigger);
  const dialog = await waitFor(() => screen.getByRole("dialog", { name: THREAD_RAIL.heading }));
  return { dialog, trigger };
}

beforeEach(() => {
  installMatchMedia({ width: MODE_WIDTHS.drawer });
});

afterEach(() => {
  uninstallMatchMedia();
});

describe("criterion 6 — the trigger", () => {
  it("is a labelled button in the header, not a hover affordance", () => {
    const { container } = renderShell();
    const trigger = screen.getByRole("button", { name: THREAD_RAIL.openDrawer });
    expect(container.querySelector("header")?.contains(trigger)).toBe(true);
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    // Nothing about it is revealed by hover: no opacity-0, no group-hover.
    expect(trigger.className).not.toMatch(/opacity-0|group-hover/);
  });

  it("is reachable and operable from the keyboard alone", async () => {
    renderShell();
    const trigger = screen.getByRole("button", { name: THREAD_RAIL.openDrawer });
    // Tab once for the skip link, once for the trigger.
    await user().tab();
    await user().tab();
    expect(trigger).toHaveFocus();

    await user().keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: THREAD_RAIL.heading })).toBeInTheDocument();
  });

  it("reports its expanded state while the drawer is open", async () => {
    renderShell();
    const { trigger } = await openDrawer();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});

describe("criterion 6 — the dialog", () => {
  it("opens as a modal dialog carrying the rail", async () => {
    renderShell();
    const { dialog } = await openDrawer();
    expect(dialog).toHaveAttribute("role", "dialog");
    expect(within(dialog).getByRole("link", { name: /retrieval-augmented/i })).toBeInTheDocument();
  });

  it("traps focus inside itself", async () => {
    renderShell();
    const behind = screen.getByRole("button", { name: "A control behind the drawer" });
    const { dialog } = await openDrawer();

    // Radix moves focus into the dialog on open; tabbing round the whole
    // panel must never land on the control behind it. `behind` is captured
    // before the open because the modal removes it from the a11y tree.
    for (let index = 0; index < 8; index += 1) {
      await user().tab();
      expect(behind).not.toHaveFocus();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it("closes on Escape", async () => {
    renderShell();
    await openDrawer();
    await user().keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: THREAD_RAIL.heading })).toBeNull();
    });
  });

  it("restores focus to the trigger when it closes", async () => {
    renderShell();
    const { trigger } = await openDrawer();
    await user().keyboard("{Escape}");
    await waitFor(() => {
      expect(trigger).toHaveFocus();
    });
  });

  it("closes when a thread inside it is followed, so the drawer cannot cover the page", async () => {
    renderShell();
    const { dialog } = await openDrawer();
    await user().click(within(dialog).getByRole("link", { name: /sparse attention/i }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: THREAD_RAIL.heading })).toBeNull();
    });
  });
});

describe("criterion 3 — the same drawer is how the 56px strip expands over content", () => {
  it("opens from the strip's own named control between 768px and 1023px", async () => {
    installMatchMedia({ width: MODE_WIDTHS.compact });
    renderShell({ railMode: "compact" });

    const nav = screen.getByRole("navigation", { name: THREAD_RAIL.heading });
    await user().click(within(nav).getByRole("button", { name: THREAD_RAIL.openDrawer }));

    const dialog = await screen.findByRole("dialog", { name: THREAD_RAIL.heading });
    expect(within(dialog).getByRole("link", { name: /retrieval-augmented/i })).toBeInTheDocument();
  });
});

describe("the drawer's module is not in the first render", () => {
  it("is only imported once the drawer has been asked for", () => {
    // The budget consequence, asserted structurally: nothing renders the
    // dialog until a trigger is pressed, which is what keeps Radix out of
    // both routes' first-load chunk union (13,792 B gzip on `/`).
    renderShell();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.querySelectorAll("[data-thread-drawer-rail]")).toHaveLength(0);
  });
});
