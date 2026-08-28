/**
 * Criterion 5, first clause: "`Dialog` traps focus and restores it to the
 * trigger on close (APG)". Both halves are asserted here, by behaviour
 * rather than by the presence of a library.
 */

import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/primitives/Button";
import { Dialog, DialogClose } from "@/components/primitives/Dialog";
import { render, screen, user, waitFor } from "../support/render";

function ConfirmDialog({ onOpenChange }: { onOpenChange?: (open: boolean) => void }) {
  return (
    <Dialog
      title="Delete this thread?"
      description="The thread, its jobs and its reports are removed."
      trigger={<Button variant="critical">Delete thread</Button>}
      onOpenChange={onOpenChange}
      footer={
        <>
          <DialogClose asChild>
            <Button variant="secondary">Keep thread</Button>
          </DialogClose>
          <DialogClose asChild>
            <Button variant="critical">Delete thread now</Button>
          </DialogClose>
        </>
      }
    />
  );
}

describe("Dialog", () => {
  it("is closed until asked", () => {
    render(<ConfirmDialog />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens from a prop, with no interaction at all", () => {
    render(<Dialog title="Export unavailable" defaultOpen />);
    expect(screen.getByRole("dialog", { name: "Export unavailable" })).toBeInTheDocument();
  });

  it("is named by its title and described by its description", async () => {
    render(<ConfirmDialog />);
    await user().click(screen.getByRole("button", { name: "Delete thread" }));

    const dialog = await screen.findByRole("dialog", { name: "Delete this thread?" });
    expect(dialog).toHaveAccessibleDescription(
      "The thread, its jobs and its reports are removed.",
    );
  });

  it("is modal: the rest of the document leaves the accessibility tree", async () => {
    const { container } = render(<ConfirmDialog />);
    await user().click(screen.getByRole("button", { name: "Delete thread" }));
    await screen.findByRole("dialog");

    // Radix implements modality with `aria-hidden` on everything outside the
    // dialog rather than with `aria-modal` on the dialog itself. That is the
    // stronger of the two — `aria-modal` is advisory and several screen
    // readers ignore it — so the assertion is on the mechanism that works.
    expect(container).toHaveAttribute("aria-hidden", "true");

    await user().keyboard("{Escape}");
    await waitFor(() => expect(container).not.toHaveAttribute("aria-hidden"));
  });

  it("moves focus into the dialog on open", async () => {
    render(<ConfirmDialog />);
    await user().click(screen.getByRole("button", { name: "Delete thread" }));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  });

  it("traps focus: tabbing past the last control returns to the first", async () => {
    render(<ConfirmDialog />);
    await user().click(screen.getByRole("button", { name: "Delete thread" }));
    const dialog = await screen.findByRole("dialog");

    const tabbable = [...dialog.querySelectorAll("button")];
    expect(tabbable.length).toBeGreaterThanOrEqual(3);

    (tabbable.at(-1) as HTMLElement).focus();
    await user().tab();
    // Whatever it wrapped to, it did not escape the dialog.
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(tabbable[0]);
  });

  it("traps focus backwards too", async () => {
    render(<ConfirmDialog />);
    await user().click(screen.getByRole("button", { name: "Delete thread" }));
    const dialog = await screen.findByRole("dialog");
    const tabbable = [...dialog.querySelectorAll("button")];

    (tabbable[0] as HTMLElement).focus();
    await user().tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(tabbable.at(-1));
  });

  it("closes on Escape and restores focus to the trigger", async () => {
    render(<ConfirmDialog />);
    const trigger = screen.getByRole("button", { name: "Delete thread" });
    await user().click(trigger);
    await screen.findByRole("dialog");

    await user().keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("closes from a footer button and restores focus to the trigger", async () => {
    render(<ConfirmDialog />);
    const trigger = screen.getByRole("button", { name: "Delete thread" });
    await user().click(trigger);

    await user().click(await screen.findByRole("button", { name: "Keep thread" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("closes from the close button", async () => {
    render(<ConfirmDialog />);
    await user().click(screen.getByRole("button", { name: "Delete thread" }));
    await user().click(await screen.findByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("reports every open and close to the caller", async () => {
    const onOpenChange = vi.fn();
    render(<ConfirmDialog onOpenChange={onOpenChange} />);

    await user().click(screen.getByRole("button", { name: "Delete thread" }));
    expect(onOpenChange).toHaveBeenCalledWith(true);

    await user().keyboard("{Escape}");
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("sends focus where the caller asks", async () => {
    function WithInitialFocus() {
      const keep = useRef<HTMLButtonElement>(null);
      return (
        <Dialog
          title="Delete this thread?"
          defaultOpen
          initialFocusRef={keep}
          footer={
            <>
              <Button variant="critical">Delete thread now</Button>
              <Button ref={keep} variant="secondary">
                Keep thread
              </Button>
            </>
          }
        />
      );
    }

    render(<WithInitialFocus />);
    // Without the ref, Radix would focus the destructive button — it is
    // first in the DOM.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Keep thread" })).toHaveFocus(),
    );
  });

  it("clears aria-describedby when there is no description", () => {
    render(<Dialog title="Export unavailable" defaultOpen />);
    expect(screen.getByRole("dialog")).not.toHaveAttribute("aria-describedby");
  });

  it("renames the close control when asked", () => {
    render(<Dialog title="Export unavailable" defaultOpen closeLabel="Dismiss" />);
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("tints a critical dialog without changing what it says", () => {
    render(<Dialog title="Delete this thread?" defaultOpen tone="critical" />);
    expect(screen.getByRole("dialog", { name: "Delete this thread?" })).toBeInTheDocument();
    expect(screen.getByText("Delete this thread?")).toHaveClass("text-critical-text");
  });

  it("renders body content and a footer when given them", () => {
    render(
      <Dialog title="Export unavailable" defaultOpen footer={<Button>Close</Button>}>
        There is no report to export yet.
      </Dialog>,
    );
    expect(screen.getByText("There is no report to export yet.")).toBeInTheDocument();
  });
});
