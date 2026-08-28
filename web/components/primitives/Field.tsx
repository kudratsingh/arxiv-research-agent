"use client";

/**
 * Field — one labelled single-line control, with its hint and its error.
 *
 * THE ERROR IS NOT A LIVE REGION. 03 §7.3 allows exactly two, product-wide:
 * one `role="status"` on the trace spine and one `role="alert"` for
 * user-triggered failures. A field that announced itself on every keystroke
 * would be a third, and would talk over both. The error is wired through
 * `aria-invalid` and `aria-describedby` instead, which is what a screen
 * reader reads when focus reaches the control — the 422 field mapping in
 * 03 §2.2 lands here.
 *
 * COLOUR IS NOT THE ERROR SIGNAL EITHER. The row carries the slashed-square
 * mark of 03 §3.4 and a clipped "Error:" prefix, so the state survives both
 * a forced-colours substitution and a monochrome print.
 *
 * The control is `text-ui-base` — 16px — in every size. 03 §7.5: "all inputs
 * are 16px to prevent iOS focus zoom", which is a viewport bug rather than a
 * type-scale preference, so it does not step with the control height.
 */

import { useId, type InputHTMLAttributes, type ReactNode } from "react";

import { Mark } from "./marks";
import "./primitives.css";
import { FOCUSABLE_CLASS, cx, targetClass, type ControlSize } from "./styles";
import { VISUALLY_HIDDEN_CLASS, VisuallyHidden } from "./VisuallyHidden";

export interface FieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "size" | "id"> {
  /** Required. A placeholder is not a label. */
  label: ReactNode;
  /** Clip the label rather than drop it — the control stays named. */
  labelHidden?: boolean;
  hint?: ReactNode;
  /** Truthy switches the control into its invalid presentation. */
  error?: ReactNode;
  size?: ControlSize;
  id?: string;
}

export function Field({
  label,
  labelHidden = false,
  hint,
  error,
  size = "md",
  id,
  className,
  required,
  ...rest
}: FieldProps) {
  const generated = useId();
  const inputId = id ?? `${generated}-input`;
  const hintId = `${generated}-hint`;
  const errorId = `${generated}-error`;

  // Order matters: the hint explains the field, the error explains the
  // rejection, and a screen reader reads them in the order listed.
  const describedBy =
    [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") ||
    undefined;

  return (
    <div className={cx("flex flex-col gap-1", className)}>
      <label
        htmlFor={inputId}
        className={cx(
          "text-ui-sm font-medium text-ink",
          labelHidden && VISUALLY_HIDDEN_CLASS,
        )}
      >
        {label}
        {/* Part of the label, not an aria-hidden decoration: "(required)"
            reads naturally after the name and needs no clipped twin. */}
        {required ? <span className="text-ink-muted"> (required)</span> : null}
      </label>

      <input
        {...rest}
        id={inputId}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cx(
          "w-full rounded-md border bg-surface px-3 text-ui-base text-ink",
          "transition-colors duration-fast ease-standard",
          "placeholder:text-ink-faint disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-disabled",
          FOCUSABLE_CLASS,
          targetClass(size),
          error ? "border-critical" : "border-border-strong",
        )}
      />

      {hint ? (
        <p id={hintId} className="text-ui-xs text-ink-muted">
          {hint}
        </p>
      ) : null}

      {error ? (
        <p
          id={errorId}
          className="flex items-center gap-1 text-ui-xs text-critical-text"
        >
          <Mark mark="slashed-square" />
          <VisuallyHidden>Error:</VisuallyHidden>
          {error}
        </p>
      ) : null}
    </div>
  );
}
