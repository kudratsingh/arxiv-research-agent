"use client";

/**
 * ThreadDrawer — the thread rail as an APG modal dialog (WO-08 criterion 6).
 *
 * Below 768px the rail is not in the layout at all (04-ARCHITECTURE.md §8.3
 * item 1); this is where it goes instead. Between 768 and 1023px it is what
 * "expands over content on demand" means for the 56px icon strip
 * (03-DESIGN-BRIEF.md §7.5).
 *
 * IT IS THE `Dialog` PRIMITIVE, NOT A SECOND IMPLEMENTATION. Focus
 * trapping, Escape, the scrim, and focus restoration to whatever was
 * focused when it opened are Radix's, through WO-07's wrapper. This module
 * adds three things and nothing else: the title, the panel's width, and the
 * fact that a navigation inside a drawer must close the drawer.
 *
 * WHY THERE IS NO `<nav>` IN HERE. The shell renders exactly one
 * `nav[aria-label="Threads"]`, and at the widths where this drawer is
 * reachable that nav is either absent (below 768px) or the icon strip
 * (768–1023px). A second `nav` with the same name would be a duplicate
 * landmark. The dialog does not need one: `[role=dialog]` is one of axe's
 * `region` matchers, so its content is not "outside a landmark".
 *
 * LAZY BY CONSTRUCTION. The shell mounts this module only once the drawer
 * has been opened, via `next/dynamic`. That is a budget decision with a
 * measured number behind it: statically importing the Dialog primitive into
 * the `/` route's graph costs 13,792 B gzip of first-load JavaScript and
 * breaches RC-01's 148,480 B ceiling on its own. See the PR body.
 */

import type { ReactNode } from "react";

import { Dialog } from "@/components/primitives/Dialog";
import { ScrollRegion } from "@/components/primitives/ScrollRegion";
import { SHELL } from "@/lib/copy/shell";
import { THREAD_RAIL } from "@/lib/copy/threads";

export interface ThreadDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The rail's contents — the shell passes the same node it would render in the rail. */
  children: ReactNode;
  /** Overridable so a story or a test can name the drawer something else. */
  title?: string;
}

export default function ThreadDrawer({
  open,
  onOpenChange,
  children,
  title = THREAD_RAIL.heading,
}: ThreadDrawerProps) {
  return (
    <Dialog
      title={title}
      open={open}
      onOpenChange={onOpenChange}
      closeLabel={SHELL.closeDrawer}
    >
      {/* `onClick` rather than a per-row callback: the rail this wraps is a
          feature component this work order renders unmodified, so the drawer
          cannot know which of its descendants is a link. A click that lands
          on an anchor inside a modal drawer is always a navigation, and a
          drawer that survives the navigation would cover the page the user
          just asked for. */}
      <div
        data-thread-drawer-rail=""
        onClick={(event) => {
          if ((event.target as HTMLElement).closest("a[href]")) {
            onOpenChange(false);
          }
        }}
      >
        {/* The rail this wraps is `w-64 shrink-0` (ConversationSidebar.tsx:89)
            — 256px at every width, which is wider than the dialog's content
            box at a 320px viewport. ScrollRegion is 04 §8.3 item 4's answer
            to exactly that: the PANEL pans, the page does not. It comes out
            when WO-14's ThreadRail replaces the fixed width. */}
        <ScrollRegion label={SHELL.drawerList}>{children}</ScrollRegion>
      </div>
    </Dialog>
  );
}
