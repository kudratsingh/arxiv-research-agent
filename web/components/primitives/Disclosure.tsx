"use client";

/**
 * Disclosure — a real `<button aria-expanded>` over a panel (criterion 5).
 *
 * NO RADIX HERE, ON PURPOSE. Dialog and Menu buy focus trapping, roving
 * focus and typeahead — genuinely hard behaviour that is worth route
 * JavaScript. A disclosure is a button, a boolean, `aria-expanded` and
 * `aria-controls`; importing `@radix-ui/react-collapsible` to get that would
 * add a package to every route that shows one for no accessibility gain
 * (R-11, 04 §8.1). 01-RESEARCH.md recommends the disclosure over a
 * half-built menu precisely because it is this small.
 *
 * `<details>/<summary>` was the other candidate and loses on two counts: its
 * open/close is not scriptable without fighting the element, and Safari
 * still exposes `<summary>` inconsistently to VoiceOver.
 *
 * The panel is `hidden` when closed rather than unmounted, so `aria-controls`
 * always points at a node that exists and the panel's own scroll position
 * survives a toggle. The entrance is `ew-enter` — opacity only, no
 * transform, so reduced motion removes an animation and not information
 * (criterion 9).
 *
 * WHY THE PANEL CARRIES `ew-disclosure-panel` (WO-27 criterion 7). `hidden`
 * hides an element through the user-agent stylesheet's `[hidden] { display:
 * none }`, and **any author rule that sets `display` beats it** — origin
 * wins before specificity is even consulted. A caller passing a layout
 * utility through `panelClassName` therefore un-hides the panel while
 * `aria-expanded` still says `false`, and neither the caller nor this
 * component has any way to notice.
 *
 * That is not hypothetical: `Diagnostics` passes `panelClassName="flex flex-
 * col gap-3"`, and WO-27's keyboard walk found its `role="log"` live region
 * displayed, tabbable and announcing on a collapsed disclosure — the exact
 * thing `Diagnostics`'s own header says cannot happen, and a third live
 * region where 03 §7.3 allows two. axe has no rule for it, so the full-matrix
 * sweep was green over it in both themes at all three widths.
 *
 * The class exists so `primitives.css` can carry a `.ew-disclosure-panel
 * [hidden]` rule, whose specificity (0,2,0) beats any single utility class a
 * caller can pass. It is deliberately a policy in the primitive rather than a
 * rule in `Diagnostics`: the next caller to pass `grid` would reintroduce the
 * defect, and would be just as right to.
 *
 * Controlled and uncontrolled both work: pass `open` + `onOpenChange`, or
 * neither and let it own the boolean.
 */

import { useId, useState, type ReactNode } from "react";

import "./primitives.css";
import { FOCUSABLE_CLASS, cx, targetClass, type ControlSize } from "./styles";

export interface DisclosureProps {
  /** The button's content — the accessible name of the control. */
  label: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  /** Controlled mode. Pair with `onOpenChange`. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  size?: ControlSize;
  /** Extra content on the trigger's right, e.g. a StatusBadge. */
  aside?: ReactNode;
  id?: string;
  className?: string;
  panelClassName?: string;
}

export function Disclosure({
  label,
  children,
  defaultOpen = false,
  open,
  onOpenChange,
  size = "sm",
  aside,
  id,
  className,
  panelClassName,
}: DisclosureProps) {
  const generated = useId();
  const buttonId = id ?? `${generated}-trigger`;
  const panelId = `${generated}-panel`;

  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const isOpen = open ?? uncontrolled;

  function toggle() {
    const next = !isOpen;
    if (open === undefined) setUncontrolled(next);
    onOpenChange?.(next);
  }

  return (
    <div className={cx("flex flex-col", className)}>
      <button
        type="button"
        id={buttonId}
        aria-expanded={isOpen}
        aria-controls={panelId}
        onClick={toggle}
        className={cx(
          "flex w-full items-center justify-between gap-2 rounded-md px-2",
          "text-ui-sm font-medium text-ink transition-colors duration-fast ease-standard hover:bg-sunken",
          FOCUSABLE_CLASS,
          targetClass(size),
        )}
      >
        <span className="flex items-center gap-2">
          {/* The chevron is decoration: aria-expanded is the state, and the
              rotation is a static end position rather than an entrance, so
              nothing is lost when the transition collapses to 1ms. */}
          <svg
            aria-hidden="true"
            focusable="false"
            viewBox="0 0 16 16"
            width="16"
            height="16"
            className={cx(
              "transition-transform duration-base ease-standard",
              isOpen && "rotate-90",
            )}
            style={{ flex: "none" }}
          >
            <path
              d="M6 3.5 10.5 8 6 12.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {label}
        </span>
        {aside}
      </button>

      <div
        id={panelId}
        role="group"
        aria-labelledby={buttonId}
        hidden={!isOpen}
        className={cx(
          "ew-disclosure-panel ew-enter px-2 py-2 text-ui-sm text-ink",
          panelClassName,
        )}
      >
        {children}
      </div>
    </div>
  );
}
