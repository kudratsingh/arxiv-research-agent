/**
 * ThreadRailFrame — the rail chrome, and the skeleton that stands inside it
 * (WO-14 criterion 4).
 *
 * WHY THIS IS ITS OWN MODULE, AND NOT THE TOP OF ThreadList.tsx. It is the
 * one part of the rail that `components/app/ThreadRailBridge.tsx` imports
 * STATICALLY, as the Suspense fallback for the lazily-imported feature. The
 * bridge is reached from `app/(workspace)/layout.tsx`, so everything it
 * imports statically lands in BOTH routes' first-load JavaScript — and
 * `ThreadList` pulls in `@radix-ui/react-dropdown-menu` (the row overflow
 * menu) and `@radix-ui/react-dialog` (the confirmation), which WO-08
 * measured at 13,792 B gzip for the dialog alone. `/` has 4,632 B of
 * headroom under RC-01's 148,480 B ceiling. So the module boundary here is
 * a budget boundary: this file is Radix-free and query-free, and it is the
 * only part of the rail that a route pays for up front.
 *
 * THE CONSEQUENCE IS A FEATURE, NOT A COMPROMISE. The fallback the bridge
 * renders while the rail's chunk arrives is the same three skeleton rows,
 * in the same chrome, at the same height as the rail's own loading state —
 * so the chunk boundary is invisible and nothing moves when it resolves.
 * That is the same property criterion 4 asks for across the
 * loading→loaded transition, and both come from `.ew-thread-row` in
 * ./threads.css owning the height once.
 *
 * NO SPINNER, ANYWHERE (03 §2.2 row 2, §3.7). `Skeleton` does not animate;
 * `aria-busy` on the list is how the load is announced, and the bars are
 * `aria-hidden` because a skeleton read aloud is a stutter of nothing.
 */

import Link from "next/link";
import type { ReactNode, Ref } from "react";

import { Skeleton } from "@/components/primitives/Skeleton";
import { cx } from "@/components/primitives/styles";

import "./threads.css";

/** How many rows the loading state reserves. 03 §2.2 row 2: three. */
export const SKELETON_ROW_COUNT = 3;

/**
 * The heading's id, shared by every renderer of the rail.
 *
 * One constant rather than three defaults, because the bridge's Suspense
 * fallback and the rail's own loading state have to produce IDENTICAL
 * markup — a list named by the heading in one and unnamed in the other
 * would be a real difference between two states the user is supposed not to
 * be able to tell apart. `web/tests/threads/bridge.test.tsx` compares the
 * two trees node for node.
 */
export const THREAD_RAIL_HEADING_ID = "thread-rail-heading";

export interface ThreadRailFrameProps {
  /** The rail's own heading — rendered in every state, including loading. */
  heading: string;
  /** The label of the control that starts a new thread. */
  newThreadLabel: string;
  /**
   * Where "new research" goes. `/` is the landing composer, and it is the
   * honest destination: a thread is created by the landing submit's
   * `POST /conversations` → `POST /research` pair (03 §2.1), so a rail
   * button that created a bare thread on its own would spend a rate-limit
   * slot (`routes.py:545`) for a thread with no question in it.
   */
  newThreadHref?: string;
  /** Called with `newThreadHref`, so the shell can push the same route. */
  onNavigate?: (href: string) => void;
  /** The `role="alert"` slot, ABOVE the list (03 §2.2 row 4). */
  notice?: ReactNode;
  /** The list, the empty state, or the skeleton. */
  children: ReactNode;
  /** "Load more", when a page came back full. */
  footer?: ReactNode;
  /** WO-21's hook: which of the rail's states this is. */
  state: "loading" | "empty" | "list" | "error";
  className?: string;
  /** `id` of the heading, so the list can be named by it. */
  headingId?: string;
  /**
   * The rail's root element, for the one caller that needs to find a
   * control inside its own subtree rather than in the document: the
   * confirmation's focus restoration (`ThreadList.tsx`).
   */
  rootRef?: Ref<HTMLDivElement>;
}

export function ThreadRailFrame({
  heading,
  newThreadLabel,
  newThreadHref = "/",
  onNavigate,
  notice,
  children,
  footer,
  state,
  className,
  headingId = THREAD_RAIL_HEADING_ID,
  rootRef,
}: ThreadRailFrameProps) {
  return (
    <div
      ref={rootRef}
      className={cx("ew-thread-rail", className)}
      data-thread-rail=""
      data-thread-rail-state={state}
    >
      <div className="ew-thread-rail__chrome">
        <Link
          href={newThreadHref}
          onClick={() => onNavigate?.(newThreadHref)}
          data-thread-rail-new=""
          className={cx(
            "ew-focusable ew-target ew-target--sm inline-flex items-center justify-center gap-2",
            "rounded-md border border-transparent bg-primary px-3 text-ui-sm font-medium text-primary-on",
            "hover:bg-primary-strong",
          )}
        >
          {newThreadLabel}
        </Link>
        <h2 id={headingId} className="ew-thread-rail__heading">
          {heading}
        </h2>
      </div>

      {notice ? <div className="ew-thread-rail__notice">{notice}</div> : null}

      {children}

      {footer ? <div className="ew-thread-rail__foot">{footer}</div> : null}
    </div>
  );
}

export interface ThreadListSkeletonProps {
  /** A clipped word for the list, which has no rows to name it yet. */
  label: string;
  rows?: number;
  /** Names the list after the rail's heading, as the loaded list is. */
  labelledBy?: string;
}

/**
 * Three rows at real row height, `aria-busy`, no spinner.
 *
 * The `<li>` carries `.ew-thread-row` — the SAME class the loaded row
 * carries — so the reserved height cannot drift from the real one. That
 * identity is what `web/tests/threads/list.test.tsx` asserts structurally,
 * and what WO-21 measures as CLS 0.000 in a real engine.
 */
export function ThreadListSkeleton({
  label,
  rows = SKELETON_ROW_COUNT,
  labelledBy = THREAD_RAIL_HEADING_ID,
}: ThreadListSkeletonProps) {
  const count = Math.max(1, Math.trunc(rows));

  return (
    <ul
      aria-busy="true"
      aria-labelledby={labelledBy}
      className="ew-thread-rail__list"
      data-thread-list=""
    >
      {Array.from({ length: count }, (_, index) => (
        <li key={index} className="ew-thread-row" data-thread-row-skeleton="">
          <Skeleton
            className="w-full px-2"
            label={index === 0 ? label : undefined}
            height="var(--text-ui-sm-line)"
          />
        </li>
      ))}
    </ul>
  );
}
