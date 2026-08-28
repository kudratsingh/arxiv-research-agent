/**
 * VisuallyHidden — text that is in the accessibility tree and not on screen.
 *
 * No hooks and no state, so it is deliberately NOT a client component: a
 * server-rendered landmark name or status word costs a surface nothing in
 * route JavaScript (04 §8.1).
 *
 * There is no `focusable` variant. Exactly one element in the product
 * reverses the clip — the skip link — and it owns that rule itself
 * (`.ew-skip-link` in primitives.css), which keeps this component to the one
 * thing it does.
 */

import type { ReactNode } from "react";

import "./primitives.css";

/** Exported so a pattern can clip an element it renders itself. */
export const VISUALLY_HIDDEN_CLASS = "ew-visually-hidden";

/**
 * The tags a clipped element is ever legitimately rendered as. Deliberately
 * a closed union rather than `ElementType`: a visually hidden `<button>` or
 * `<a>` is almost always a mistake (SkipLink is the exception and owns its
 * own anchor), and a closed union keeps the props type exact.
 */
export type VisuallyHiddenTag =
  | "span"
  | "div"
  | "p"
  | "h1"
  | "h2"
  | "h3"
  | "h4"
  | "h5"
  | "h6"
  | "legend";

export interface VisuallyHiddenProps {
  children: ReactNode;
  /** Defaults to `span`. */
  as?: VisuallyHiddenTag;
  /** So the text can be referenced by `aria-describedby` / `aria-labelledby`. */
  id?: string;
  className?: string;
}

export function VisuallyHidden({
  children,
  as: Tag = "span",
  id,
  className,
}: VisuallyHiddenProps) {
  return (
    <Tag id={id} className={[VISUALLY_HIDDEN_CLASS, className].filter(Boolean).join(" ")}>
      {children}
    </Tag>
  );
}
