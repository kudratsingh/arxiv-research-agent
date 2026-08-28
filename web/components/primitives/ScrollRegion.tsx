/**
 * ScrollRegion — the pan surface of 04 §8.3 item 4 (criterion 6).
 *
 * `overflow-x: auto` + `tabindex="0"` + `role="region"` + a REQUIRED
 * accessible name. All four together, or none of them: a region that scrolls
 * but cannot be focused is unreachable by keyboard (SC 2.1.1), and a focused
 * region with no name is an unlabelled stop in the tab order that a screen
 * reader announces as "region" and nothing else.
 *
 * THE NAME IS ENFORCED AT RUNTIME, not merely typed. TypeScript makes
 * `label` required, but a `label` computed from data can still arrive empty
 * — a table with no caption, a heading that has not loaded — and that is
 * exactly the case where the defect ships. Throwing is the only version of
 * this rule that survives contact with real data, and criterion 6 asks for a
 * test that fails when the name is omitted, which an unenforced type cannot
 * provide.
 *
 * This is what wraps report tables and the diagnostics rows, so that the
 * TABLE pans and the PAGE does not (SC 1.4.10 Reflow). The `scrollWidth <=
 * clientWidth` assertion that proves it is WO-08's, in Playwright, at 320 /
 * 360 / 412px.
 *
 * No hooks: a server component.
 */

import type { ReactNode } from "react";

import "./primitives.css";
import { cx } from "./styles";

export interface ScrollRegionProps {
  /** Required, and required to be non-empty. See the header. */
  label: string;
  children: ReactNode;
  /**
   * `horizontal` is the default and the one 04 §8.3 asks for. `both` is for
   * a diagnostics pane that is also taller than its box.
   */
  axis?: "horizontal" | "both";
  id?: string;
  className?: string;
}

export function ScrollRegion({
  label,
  children,
  axis = "horizontal",
  id,
  className,
}: ScrollRegionProps) {
  if (typeof label !== "string" || label.trim() === "") {
    throw new Error(
      "ScrollRegion: label is required and must be non-empty. A focusable " +
        "scroll container with no accessible name is an unlabelled stop in " +
        "the tab order (04 §8.3 item 4).",
    );
  }

  return (
    <div
      id={id}
      role="region"
      aria-label={label}
      tabIndex={0}
      className={cx(
        "ew-scroll-region ew-focusable",
        axis === "both" && "overflow-y-auto",
        className,
      )}
    >
      {children}
    </div>
  );
}
