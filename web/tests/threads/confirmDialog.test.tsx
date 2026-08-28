/**
 * WO-14 criterion 3 — `ConfirmDialog` replaces `confirm()`.
 *
 * "APG modal, focus contained and restored, labelled by its heading. Copy
 * per the ratified deletion ruling, asserted verbatim."
 *
 * The copy half is asserted TWICE and deliberately: once against
 * `deleteDialog()` as a string (the ruling, verbatim, so a reviewer can
 * diff it against 03 §8.2 without running anything), and once against what
 * the dialog actually renders (so a component that reworded the ruling on
 * its way to the screen fails). D-010 ruling 3 rests on two backend facts —
 * the Postgres cascade at `src/api/conversations.py:547` and the separate
 * `api_job_retention_sec` lifecycle at `src/config.py:307` — which is why
 * "removes the thread and its briefings" is the accurate sentence and
 * "deletes all its jobs" (`ConversationSidebar.tsx:74`) is not.
 */

import { useState } from "react";

import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "@/components/patterns/ConfirmDialog";
import { deleteDialog } from "@/lib/copy/threads";

import { render, screen, user, waitFor, within } from "../support/render";

const TITLE = "Retrieval-augmented evaluation";
const COPY = deleteDialog(TITLE);

function renderDialog(
  overrides: Partial<React.ComponentProps<typeof ConfirmDialog>> = {},
) {
  const onOpenChange = vi.fn();
  const onConfirm = vi.fn();
  const result = render(
    <>
      <button type="button">A control behind the dialog</button>
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        onConfirm={onConfirm}
        copy={COPY}
        closeLabel={COPY.close}
        {...overrides}
      />
    </>,
  );
  return { ...result, onOpenChange, onConfirm };
}

/* =========================================================================
 * The ratified copy, verbatim
 * ========================================================================= */

describe("the deletion copy is the ruling, word for word", () => {
  it("names the thread in the heading, with the user's own title untouched", () => {
    expect(COPY.heading).toBe("Delete “Retrieval-augmented evaluation”?");
    expect(deleteDialog("").heading).toBe("Delete this thread?");
    expect(deleteDialog("  padded  ").heading).toBe("Delete “padded”?");
  });

  it("states what deletion does, and does not promise what it does not do", () => {
    expect(COPY.body).toBe(
      "This removes the thread and its briefings from this workspace. " +
        "Run records are kept separately and expire on their own schedule.",
    );
    // The baseline's sentence, and the two words that made it wrong.
    expect(COPY.body).not.toMatch(/\bjobs?\b/i);
    expect(COPY.body).not.toMatch(/\bconversations?\b/i);
    expect(`${COPY.heading} ${COPY.body}`).not.toMatch(/permanently|forever|erase/i);
  });

  it("repeats the verb on the destructive control rather than saying OK", () => {
    expect(COPY.confirm).toBe("Delete thread");
    expect(COPY.cancel).toBe("Cancel");
    expect(COPY.pending).toBe("Deleting…");
    expect(COPY.close).toBe("Close without deleting");
  });

  it("renders those exact strings, not a reworded version of them", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: COPY.heading })).toBeInTheDocument();
    expect(within(dialog).getByText(COPY.body)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: COPY.confirm })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: COPY.cancel })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: COPY.close })).toBeInTheDocument();
  });
});

/* =========================================================================
 * The APG modal
 * ========================================================================= */

describe("criterion 3 — the APG modal contract", () => {
  it("is labelled by its heading and described by its body", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    const heading = within(dialog).getByRole("heading", { name: COPY.heading });

    expect(dialog).toHaveAttribute("aria-labelledby", heading.id);
    const describedBy = dialog.getAttribute("aria-describedby");
    expect(describedBy).not.toBeNull();
    expect(document.getElementById(describedBy as string)).toHaveTextContent(COPY.body);
  });

  it("opens with focus on Cancel, never on the destructive button", async () => {
    renderDialog();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: COPY.cancel })).toHaveFocus();
    });
    // Enter on a dialog nobody meant to open therefore cancels it.
    expect(screen.getByRole("button", { name: COPY.confirm })).not.toHaveFocus();
  });

  it("contains focus: tabbing round never reaches the page behind it", async () => {
    const { container } = renderDialog();
    const behind = container.querySelector("button") as HTMLElement;
    const dialog = screen.getByRole("dialog");

    for (let index = 0; index < 8; index += 1) {
      await user().tab();
      expect(behind).not.toHaveFocus();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it("closes on Escape, on Cancel and on the close mark — three ways out", async () => {
    const { onOpenChange } = renderDialog();
    await user().keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenLastCalledWith(false);

    await user().click(screen.getByRole("button", { name: COPY.cancel }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);

    await user().click(screen.getByRole("button", { name: COPY.close }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  /**
   * WHERE THE OTHER HALF OF "FOCUS RESTORED" LIVES, AND WHY.
   *
   * Radix restores focus by focusing `Dialog.Trigger`'s ref inside
   * `onCloseAutoFocus`, having called `preventDefault()` first — so a dialog
   * that is opened by anything OTHER than a `Dialog.Trigger` restores focus
   * to nothing at all. This one is opened by a menu item, in a portal, three
   * components away from the row it belongs to; WO-08's shell hit the same
   * wall with the drawer and solved it the same way. The restoration is
   * therefore the rail's, and it is asserted in ./list.test.tsx for both
   * destinations: back to the row's overflow button after Cancel, and to the
   * rail's first control when the row itself has just been deleted.
   *
   * This case pins the half that IS this component's: closing does not leave
   * focus somewhere inside a dialog that no longer exists.
   */
  it("leaves nothing focused inside itself once it closes", async () => {
    function Host() {
      const [open, setOpen] = useState(true);
      return (
        <ConfirmDialog
          open={open}
          onOpenChange={setOpen}
          onConfirm={() => {}}
          copy={COPY}
          closeLabel={COPY.close}
        />
      );
    }

    render(<Host />);
    const dialog = await screen.findByRole("dialog");
    await user().keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(dialog.contains(document.activeElement)).toBe(false);
  });

  it("confirms without closing itself — the caller owns the outcome", async () => {
    const { onConfirm, onOpenChange } = renderDialog();
    await user().click(screen.getByRole("button", { name: COPY.confirm }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});

/* =========================================================================
 * The in-flight state — the rail's eighth state (`deleting`)
 * ========================================================================= */

describe("pending", () => {
  it("says so on the button, stays focusable, and refuses a second press", async () => {
    const { onConfirm } = renderDialog({ pending: true });
    const confirm = screen.getByRole("button", { name: COPY.pending });

    expect(confirm).toHaveAttribute("aria-busy", "true");
    // `aria-disabled`, not `disabled`: a disabled button drops out of the
    // tab order and strands the keyboard user inside the modal.
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).not.toBeDisabled();

    await user().click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("leaves Cancel working while the request is in flight", async () => {
    const { onOpenChange } = renderDialog({ pending: true });
    await user().click(screen.getByRole("button", { name: COPY.cancel }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });
});

describe("tone", () => {
  it("uses the primary confirm button when the confirmation is not destructive", () => {
    renderDialog({ tone: "default" });
    const confirm = screen.getByRole("button", { name: COPY.confirm });
    expect(confirm.className).toMatch(/bg-primary/);
  });

  it("uses the critical one by default, because the default caller is a delete", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: COPY.confirm }).className).toMatch(
      /bg-critical/,
    );
  });
});
