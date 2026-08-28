"use client";

/**
 * Menu — a genuine menu, with the roving focus the baseline never had.
 *
 * THE COUNTER-EXAMPLE IS IN THIS REPOSITORY. `web/components/ExportDropdown.tsx:69`
 * renders `role="menu"` over a `<ul>` of `<a role="menuitem">` and stops
 * there: no `tabindex="-1"` on the items, no arrow-key handling, no
 * typeahead, no focus moved into the list on open, no focus returned to the
 * trigger on close. A screen-reader user is told "menu" and then handed a
 * list that behaves like ordinary links — the announcement and the behaviour
 * disagree, which is worse than never claiming to be a menu at all. RC-09
 * deletes that component in favour of an `ExportDisclosure`; what survives
 * is this primitive, for the one control in the product that really is a
 * menu — the thread-row overflow (03 §4.2).
 *
 * `@radix-ui/react-dropdown-menu`, imported as its own package rather than
 * through the `radix-ui` barrel (R-11). It supplies exactly the list above:
 * `RovingFocusGroup` gives the items a single tab stop and arrow-key
 * movement, typeahead jumps by first letter, Home/End work, Escape closes
 * and returns focus to the trigger.
 *
 * `modal={false}` IS DELIBERATE. Radix's modal mode calls `hideOthers()`,
 * which puts `aria-hidden="true"` on everything outside the menu — including
 * the trigger that opened it. For a dialog that is correct and axe forgives
 * it (`focusable-modal-open`); for a menu there is no modal dialog for axe
 * to find, so the same technique produces a real `aria-hidden-focus`
 * violation. A row overflow menu should not be modal in the first place.
 */

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";

import "./primitives.css";
import { FOCUSABLE_CLASS, cx, targetClass } from "./styles";

export interface MenuProps {
  /** Rendered inside `Trigger asChild` — a Button, normally. */
  trigger: ReactNode;
  /** `MenuItem` / `MenuSeparator` children. */
  children: ReactNode;
  /**
   * Override the menu's accessible name. Leave it off and the menu is named
   * by its trigger, which is the APG pattern and what Radix wires by
   * default — an icon-only "Thread actions" button names its own menu. Pass
   * it only when the trigger's name is not the right name for the surface,
   * and note that it has to clear Radix's `aria-labelledby` to take effect
   * at all, because `aria-labelledby` outranks `aria-label` in the ARIA name
   * computation.
   */
  label?: string;
  align?: "start" | "center" | "end";
  side?: "top" | "right" | "bottom" | "left";
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * Render the surface into `document.body`. On by default because an
   * overflow menu inside a scrolling rail is clipped otherwise; a story or a
   * test that wants the surface inline can turn it off.
   */
  portal?: boolean;
  className?: string;
}

export function Menu({
  trigger,
  children,
  label,
  align = "end",
  side = "bottom",
  open,
  defaultOpen,
  onOpenChange,
  portal = true,
  className,
}: MenuProps) {
  const content = (
    <DropdownMenu.Content
      {...(label ? { "aria-label": label, "aria-labelledby": undefined } : {})}
      align={align}
      side={side}
      sideOffset={4}
      className={cx(
        "ew-enter z-10 min-w-rail-collapsed rounded-md border border-border-strong",
        "bg-surface p-1 shadow-elev-2",
        className,
      )}
    >
      {children}
    </DropdownMenu.Content>
  );

  return (
    <DropdownMenu.Root
      modal={false}
      {...(open === undefined ? { defaultOpen } : { open })}
      onOpenChange={onOpenChange}
    >
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
      {portal ? <DropdownMenu.Portal>{content}</DropdownMenu.Portal> : content}
    </DropdownMenu.Root>
  );
}

export interface MenuItemProps {
  children: ReactNode;
  /** Runs on click, Enter and Space alike — Radix normalises the three. */
  onSelect?: (event: Event) => void;
  disabled?: boolean;
  /** `critical` for a destructive row. The word still says what it does. */
  tone?: "default" | "critical";
  className?: string;
}

export function MenuItem({
  children,
  onSelect,
  disabled = false,
  tone = "default",
  className,
}: MenuItemProps) {
  return (
    <DropdownMenu.Item
      disabled={disabled}
      onSelect={onSelect}
      className={cx(
        "flex cursor-default select-none items-center gap-2 rounded-sm px-3 text-ui-sm",
        // No `outline-none` here. Radix moves real DOM focus to the
        // highlighted item, so `ew-focusable`'s :focus-visible ring is the
        // keyboard indicator and the tint below is the pointer one — the
        // focus policy needs no exception for menus (criterion 4).
        "data-[highlighted]:bg-sunken",
        FOCUSABLE_CLASS,
        targetClass("sm"),
        disabled
          ? "text-ink-disabled"
          : tone === "critical"
            ? "text-critical-text"
            : "text-ink",
        className,
      )}
    >
      {children}
    </DropdownMenu.Item>
  );
}

export function MenuSeparator() {
  return <DropdownMenu.Separator className="my-1 h-px bg-border-subtle" />;
}
