/**
 * SkipLink — the first stop in the tab order (03 §7.2).
 *
 * Clipped until it takes `:focus-visible`, then revealed as a fixed overlay
 * at the top-left (`.ew-skip-link` in primitives.css). It is a plain
 * `<a href="#main">`, not a button with a scroll handler, because the anchor
 * is what actually moves the reading cursor for a screen reader: a
 * programmatic scroll moves pixels and leaves the virtual cursor behind.
 *
 * The target it points at is WO-08's `<main id="main">`; this primitive owns
 * only the link. `targetId` exists so a route with a differently named main
 * region can still use it, not so the default gets edited.
 *
 * No hooks: a server component, which is what lets it be the first element
 * inside `<body>` without pulling the shell into the client bundle.
 */

import type { ReactNode } from "react";

import "./primitives.css";
import { FOCUSABLE_CLASS, cx } from "./styles";
import { VISUALLY_HIDDEN_CLASS } from "./VisuallyHidden";

export interface SkipLinkProps {
  /** The id of the element to skip to. Defaults to WO-08's `main`. */
  targetId?: string;
  children?: ReactNode;
  className?: string;
}

export function SkipLink({
  targetId = "main",
  children = "Skip to main content",
  className,
}: SkipLinkProps) {
  return (
    <a
      href={`#${targetId}`}
      className={cx(
        VISUALLY_HIDDEN_CLASS,
        "ew-skip-link",
        FOCUSABLE_CLASS,
        // These only become visible once the clip is reversed; a clipped
        // element has no box for padding or a border to show in.
        "focus-visible:rounded-md focus-visible:border focus-visible:border-border-strong",
        "focus-visible:bg-surface focus-visible:px-4 focus-visible:py-2",
        "focus-visible:text-ui-sm focus-visible:font-medium focus-visible:text-ink",
        "focus-visible:shadow-elev-2",
        className,
      )}
    >
      {children}
    </a>
  );
}
