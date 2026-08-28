"use client";

/**
 * Button — the product's only clickable control.
 *
 * Every state is a prop: `variant`, `size`, `disabled`, `busy`, `iconOnly`,
 * `fullWidth`. Nothing is fetched, nothing is derived from context, so the
 * stories need no MSW and no network (04 §5.1, criterion 2).
 *
 * TWO DELIBERATE CHOICES.
 *
 * `busy` does not set the `disabled` attribute. A disabled button leaves the
 * focus ring behind and drops out of the tab order the instant it is
 * pressed, which strands a keyboard user mid-form. `aria-disabled` plus a
 * click guard keeps the control focusable and announced while refusing the
 * second submit — the APG guidance for a control that is temporarily
 * unavailable rather than permanently inapplicable. `disabled` is still
 * there for the permanent case.
 *
 * A CALLER MAY DECLARE `aria-disabled` WITHOUT CLAIMING `busy` (WO-13
 * criterion 7). 03 §2.2 row 4 requires the landing submit to refuse while
 * the research service is unreachable, "with the reason attached to it" —
 * `aria-disabled` plus `aria-describedby`, explicitly "not a bare disabled
 * button". That state is unavailable but it is not *busy*: nothing is in
 * flight, and emitting `aria-busy` for it would announce work that is not
 * happening. So `aria-disabled` passed by a caller is honoured — it earns
 * the same click guard and the same unavailable styling as `busy` — while
 * `aria-busy` stays exclusively `busy`'s. Before this, `aria-disabled` was
 * written after the prop spread and a caller's value was silently dropped.
 *
 * `iconOnly` throws without an accessible name. A silent icon button is the
 * single most common way a component library ships an axe `button-name`
 * violation, and the failure is invisible until an audit. Failing loudly at
 * render is cheaper than failing quietly in production.
 */

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import "./primitives.css";
import {
  CONTROL_PADDING,
  FOCUSABLE_CLASS,
  cx,
  targetClass,
  type ControlSize,
} from "./styles";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "critical";

export interface ButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  variant?: ButtonVariant;
  size?: ControlSize;
  /** Work is in flight: `aria-busy`, `aria-disabled`, clicks refused, focus kept. */
  busy?: boolean;
  /** Square control with no visible label. Requires `aria-label`. */
  iconOnly?: boolean;
  fullWidth?: boolean;
  /** Defaults to `"button"`, never the HTML default of `"submit"`. */
  type?: "button" | "submit" | "reset";
  children?: ReactNode;
}

/**
 * Colour per variant. Only `--color-*` roles appear; the ESLint
 * no-literal-colour rule and the repository scan in tests/tokens.test.ts
 * both hold this file to that.
 */
const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary:
    "border-transparent bg-primary text-primary-on hover:bg-primary-strong",
  secondary:
    "border-border-strong bg-surface text-ink hover:bg-sunken",
  ghost:
    "border-transparent bg-canvas text-ink hover:bg-sunken",
  critical:
    "border-transparent bg-critical text-critical-on hover:bg-critical-text",
};

/**
 * Unavailable, in both senses. `aria-disabled` styles the same way the
 * `disabled` attribute does, so the two are indistinguishable on screen and
 * differ only in whether focus survives.
 */
const UNAVAILABLE_CLASS =
  "cursor-not-allowed border-border-subtle bg-sunken text-ink-disabled hover:bg-sunken";

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "sm",
    busy = false,
    iconOnly = false,
    fullWidth = false,
    type = "button",
    disabled = false,
    className,
    onClick,
    children,
    ...rest
  },
  ref,
) {
  const named =
    Boolean(rest["aria-label"]) || Boolean(rest["aria-labelledby"]);
  if (iconOnly && !named) {
    throw new Error(
      "Button: iconOnly requires an accessible name. Pass aria-label (or " +
        "aria-labelledby) — an icon alone leaves the control unnamed for a " +
        "screen reader and fails axe's button-name rule.",
    );
  }

  // A caller's own `aria-disabled`, read out of the spread rather than
  // overwritten by it. Strictly `=== true`: `aria-disabled="false"` is a
  // truthy string and must not disable anything.
  const declaredUnavailable = rest["aria-disabled"] === true;
  const refuses = busy || declaredUnavailable;
  const unavailable = disabled || refuses;

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      disabled={disabled}
      aria-busy={busy || undefined}
      aria-disabled={refuses || undefined}
      onClick={(event) => {
        // `busy` and a caller's `aria-disabled` both leave the button
        // enabled on purpose (see the header), so the guard has to live
        // here rather than in the DOM.
        if (refuses) {
          event.preventDefault();
          return;
        }
        onClick?.(event);
      }}
      className={cx(
        "inline-flex items-center justify-center gap-2 border font-medium",
        "rounded-md transition-colors duration-fast ease-standard",
        FOCUSABLE_CLASS,
        targetClass(size),
        iconOnly ? "px-0" : CONTROL_PADDING[size],
        unavailable ? UNAVAILABLE_CLASS : VARIANT_CLASS[variant],
        fullWidth && "w-full",
        className,
      )}
    >
      {children}
    </button>
  );
});
