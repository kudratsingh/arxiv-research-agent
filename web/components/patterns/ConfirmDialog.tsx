"use client";

/**
 * ConfirmDialog — what replaces `confirm()` (03 §4.9, WO-14 criterion 3).
 *
 * THE THING IT REPLACES IS ONE LINE OF CODE AND FOUR DEFECTS.
 * `ConversationSidebar.tsx:74` calls
 * `confirm("Delete this conversation and all its jobs?")`, which (1) uses
 * the wrong noun for the product's own object (03 §1.5), (2) promises an
 * erasure the system does not perform (03 §8.2 — the Postgres cascade
 * removes the conversation's job rows, `src/api/conversations.py:547`,
 * while the job store's own records live under `api_job_retention_sec`,
 * `src/config.py:307`), (3) is a browser chrome dialog no design token can
 * reach, and (4) blocks the main thread while it is open. This component
 * fixes the last two; `lib/copy/threads.ts`'s `deleteDialog()` fixes the
 * first two and is the only place the sentence exists.
 *
 * IT CARRIES NO STRINGS OF ITS OWN — not even "Cancel". Every word arrives
 * in `copy`, so the dialog cannot drift from the dictionary the gate reads
 * (WO-12 criterion 1, enforced here by `copy/no-inline-text`).
 *
 * FOCUS STARTS ON CANCEL, NOT ON THE DESTRUCTIVE BUTTON. Radix focuses the
 * first tabbable element on open, which for this footer is the Close mark;
 * `initialFocusRef` moves it to Cancel instead, so Enter on an
 * accidentally-opened dialog does nothing. Containment and restoration are
 * the `Dialog` primitive's, which is Radix's — see its header for why that
 * dependency is earned.
 *
 * PENDING IS `busy`, NEVER `disabled`. A disabled confirm button drops out
 * of the tab order the instant it is pressed and strands the keyboard user
 * inside a modal whose only remaining stop is Cancel. `Button`'s `busy`
 * keeps focus and refuses the second click.
 */

import { useRef, type ReactNode } from "react";

import { Button } from "@/components/primitives/Button";
import { Dialog } from "@/components/primitives/Dialog";

/**
 * The five strings a confirmation needs.
 *
 * Structurally identical to `DeleteDialogCopy` in `lib/copy/threads.ts` and
 * deliberately not an import of it: this pattern confirms *anything*, and a
 * type that named deletion would make the next caller either lie or fork
 * the component.
 */
export interface ConfirmCopy {
  /** The dialog's accessible name. */
  heading: string;
  /** What actually happens. Wired to `aria-describedby`. */
  body: string;
  /** The destructive verb, repeated — never "OK". */
  confirm: string;
  cancel: string;
  /** Shown on the confirm button while the request is in flight. */
  pending: string;
}

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  copy: ConfirmCopy;
  /** Runs on confirm. The dialog does not close itself — the caller does. */
  onConfirm: () => void;
  /** The request is in flight: the confirm button is busy, Cancel still works. */
  pending?: boolean;
  /** `critical` for a destructive confirmation; the words still carry it. */
  tone?: "default" | "critical";
  /** The close mark's accessible name. */
  closeLabel: string;
  /** Extra content between the body and the footer, e.g. an alert. */
  children?: ReactNode;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  copy,
  onConfirm,
  pending = false,
  tone = "critical",
  closeLabel,
  children,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  return (
    <Dialog
      title={copy.heading}
      description={copy.body}
      open={open}
      onOpenChange={onOpenChange}
      tone={tone}
      initialFocusRef={cancelRef}
      closeLabel={closeLabel}
      footer={
        <>
          <Button
            ref={cancelRef}
            variant="secondary"
            onClick={() => onOpenChange(false)}
            data-confirm-cancel=""
          >
            {copy.cancel}
          </Button>
          <Button
            variant={tone === "critical" ? "critical" : "primary"}
            busy={pending}
            onClick={onConfirm}
            data-confirm-accept=""
          >
            {pending ? copy.pending : copy.confirm}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}
