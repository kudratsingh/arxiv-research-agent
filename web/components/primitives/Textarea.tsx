"use client";

/**
 * Textarea — the multi-line sibling of Field, plus the character budget the
 * query composer needs.
 *
 * `limit` IS NOT `maxLength`. A native `maxLength` silently truncates a
 * paste, which is the worst possible way to tell someone their question is
 * too long — the text simply disappears. `limit` instead lets the value
 * exceed it and turns the counter into a stated, marked, coloured refusal,
 * so 03 §2.2's `NearLimit` and `OverLimit` states are both reachable by
 * passing a `value` and a `limit` and nothing else (criterion 2). A caller
 * that genuinely wants truncation can still pass `maxLength` through.
 *
 * The counter is described, not announced: it is in `aria-describedby`, not
 * a live region, for the same reason Field's error is (03 §7.3 allows
 * exactly two live regions product-wide).
 */

import {
  useId,
  useState,
  type ChangeEvent,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";

import { Mark } from "./marks";
import "./primitives.css";
import { FOCUSABLE_CLASS, cx } from "./styles";
import { VISUALLY_HIDDEN_CLASS, VisuallyHidden } from "./VisuallyHidden";

export interface TextareaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id"> {
  label: ReactNode;
  labelHidden?: boolean;
  hint?: ReactNode;
  error?: ReactNode;
  /** Show "n / limit" and mark the value as over budget beyond it. */
  limit?: number;
  /** The fraction of `limit` at which the counter starts warning. */
  nearLimitRatio?: number;
  id?: string;
}

export function Textarea({
  label,
  labelHidden = false,
  hint,
  error,
  limit,
  nearLimitRatio = 0.9,
  id,
  className,
  rows = 4,
  required,
  value,
  defaultValue,
  onChange,
  "aria-describedby": describedByProp,
  ...rest
}: TextareaProps) {
  const generated = useId();
  const textareaId = id ?? `${generated}-textarea`;
  const hintId = `${generated}-hint`;
  const errorId = `${generated}-error`;
  const countId = `${generated}-count`;

  // Mirrors the value so an UNCONTROLLED textarea still counts. When the
  // caller controls `value`, that wins on every render and the mirror is
  // never read — no second source of truth.
  const [mirrored, setMirrored] = useState(() => String(defaultValue ?? ""));
  const text = value === undefined ? mirrored : String(value);
  const count = text.length;
  const over = limit !== undefined && count > limit;
  const near =
    limit !== undefined && !over && count >= Math.floor(limit * nearLimitRatio);

  // A CALLER'S `aria-describedby` IS MERGED, NOT OVERWRITTEN (WO-17).
  // `{...rest}` is spread before the attribute below, so a caller-supplied
  // value would otherwise be silently dropped — and WO-17's arXiv column
  // needs one shared description ("sent to arXiv verbatim") on every row
  // without repeating that sentence under each of them. The caller's ids
  // come first because they describe the field's purpose; the hint, count
  // and error describe its current state.
  const describedBy =
    [
      describedByProp,
      hint ? hintId : null,
      limit !== undefined ? countId : null,
      error ? errorId : null,
    ]
      .filter(Boolean)
      .join(" ") || undefined;

  function handleChange(event: ChangeEvent<HTMLTextAreaElement>) {
    if (value === undefined) setMirrored(event.target.value);
    onChange?.(event);
  }

  return (
    <div className={cx("flex flex-col gap-1", className)}>
      <label
        htmlFor={textareaId}
        className={cx(
          "text-ui-sm font-medium text-ink",
          labelHidden && VISUALLY_HIDDEN_CLASS,
        )}
      >
        {label}
        {required ? <span className="text-ink-muted"> (required)</span> : null}
      </label>

      <textarea
        {...rest}
        id={textareaId}
        rows={rows}
        required={required}
        value={value}
        defaultValue={value === undefined ? defaultValue : undefined}
        onChange={handleChange}
        aria-invalid={error || over ? true : undefined}
        aria-describedby={describedBy}
        className={cx(
          "w-full resize-y rounded-md border bg-surface p-3 text-ui-base text-ink",
          "transition-colors duration-fast ease-standard",
          "placeholder:text-ink-faint disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-disabled",
          FOCUSABLE_CLASS,
          error || over ? "border-critical" : "border-border-strong",
        )}
      />

      <div className="flex items-start justify-between gap-4">
        {hint ? (
          <p id={hintId} className="text-ui-xs text-ink-muted">
            {hint}
          </p>
        ) : (
          <span />
        )}

        {limit !== undefined ? (
          <p
            id={countId}
            className={cx(
              "shrink-0 text-ui-xs tabular-nums",
              over ? "text-critical-text" : near ? "text-review-text" : "text-ink-muted",
            )}
          >
            {/* The word is what carries "over budget"; the colour repeats it. */}
            {over ? <VisuallyHidden>Over the limit: </VisuallyHidden> : null}
            {count} / {limit}
          </p>
        ) : null}
      </div>

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
