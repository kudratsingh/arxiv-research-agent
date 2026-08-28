"use client";

/**
 * Dialog — the APG modal pattern: focus trapped inside while open, focus
 * restored to the trigger on close (criterion 5).
 *
 * RADIX EARNS ITS PLACE HERE. The trap is not the hard part; the hard parts
 * are restoring focus to the right element when the dialog closes for any of
 * six reasons, keeping the rest of the document out of the accessibility
 * tree without making it unfocusable-but-visible, sequencing the Escape
 * handler against nested layers, and doing all of that without a scroll
 * jump. `@radix-ui/react-dialog` is imported as its own package — never the
 * `radix-ui` barrel, which is the budget leak R-11 names and which WO-23
 * measures.
 *
 * The entrance is `ew-enter`: opacity only. The dialog is centred by flex
 * rather than by a `-translate-x-1/2` pair, so there is no transform to
 * animate and nothing for reduced motion to strip (criterion 9).
 *
 * DARK MODE. 03 §3.6: "In dark mode every elevated surface must
 * additionally step canvas → surface and carry a border-strong outline,
 * because the dark shadow values carry almost no signal on their own." The
 * panel therefore carries `bg-surface` + `border-border-strong` in both
 * themes rather than switching on one.
 */

import * as RadixDialog from "@radix-ui/react-dialog";
import { useId, type ReactNode, type RefObject } from "react";

import { Button } from "./Button";
import "./primitives.css";
import { cx } from "./styles";

export interface DialogProps {
  /** Required: the dialog's accessible name. */
  title: ReactNode;
  children?: ReactNode;
  /** Wired to `aria-describedby`. Omit and Radix's own warning is suppressed. */
  description?: ReactNode;
  /** Actions row, bottom-right. */
  footer?: ReactNode;
  /** Rendered inside `Dialog.Trigger asChild` — focus returns here on close. */
  trigger?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** `critical` tints the title's rule; the words still carry the meaning. */
  tone?: "default" | "critical";
  /**
   * Where focus lands on open. Radix defaults to the first tabbable element,
   * which for a delete confirmation is the destructive button — point this
   * at Cancel instead.
   */
  initialFocusRef?: RefObject<HTMLElement | null>;
  closeLabel?: string;
  className?: string;
}

export function Dialog({
  title,
  children,
  description,
  footer,
  trigger,
  open,
  defaultOpen,
  onOpenChange,
  tone = "default",
  initialFocusRef,
  closeLabel = "Close",
  className,
}: DialogProps) {
  const generated = useId();
  const titleId = `${generated}-title`;
  const descriptionId = `${generated}-description`;

  return (
    <RadixDialog.Root
      {...(open === undefined ? { defaultOpen } : { open })}
      onOpenChange={onOpenChange}
    >
      {trigger ? <RadixDialog.Trigger asChild>{trigger}</RadixDialog.Trigger> : null}

      <RadixDialog.Portal>
        {/* The scrim. `sunken` reads as a wash in light and as a deepening in
            dark, which is the one role that behaves the same way in both. */}
        <RadixDialog.Overlay className="fixed inset-0 bg-sunken opacity-80" />

        <div className="fixed inset-0 flex items-center justify-center overflow-y-auto p-4">
          <RadixDialog.Content
            aria-labelledby={titleId}
            // Explicit `undefined` is Radix's documented way to say "this
            // dialog has no description", and suppresses its dev warning.
            {...(description ? { "aria-describedby": descriptionId } : { "aria-describedby": undefined })}
            onOpenAutoFocus={(event) => {
              const target = initialFocusRef?.current;
              if (!target) return;
              event.preventDefault();
              target.focus();
            }}
            className={cx(
              "ew-enter w-full max-w-lg",
              "rounded-lg border border-border-strong bg-surface p-6 shadow-elev-3",
              className,
            )}
          >
            <div className="flex items-start justify-between gap-4">
              <RadixDialog.Title
                id={titleId}
                className={cx(
                  "text-ui-lg font-semibold",
                  tone === "critical" ? "text-critical-text" : "text-ink",
                )}
              >
                {title}
              </RadixDialog.Title>

              <RadixDialog.Close asChild>
                <Button variant="ghost" iconOnly aria-label={closeLabel}>
                  <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
                    <path
                      d="M4 4 12 12M12 4 4 12"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                    />
                  </svg>
                </Button>
              </RadixDialog.Close>
            </div>

            {description ? (
              <RadixDialog.Description id={descriptionId} className="mt-2 text-ui-sm text-ink-muted">
                {description}
              </RadixDialog.Description>
            ) : null}

            {children ? <div className="mt-4 text-ui-sm text-ink">{children}</div> : null}

            {footer ? <div className="mt-6 flex justify-end gap-2">{footer}</div> : null}
          </RadixDialog.Content>
        </div>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

/** Re-exported so a pattern can close the dialog from its own footer button. */
export const DialogClose = RadixDialog.Close;
