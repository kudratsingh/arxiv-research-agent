/**
 * ThreadSkeleton — the thread route's loading state (03 §2.2 row 6,
 * WO-09 criterion 4).
 *
 * IT REPLACES A STRING — in all three places that string was rendered.
 * `app/(workspace)/c/[id]/page.tsx:19` is the one criterion 4 names, and
 * `components/ConversationThread.tsx:182` is the one a cold load actually
 * paints (the route is dynamic, so `useSearchParams` resolves during SSR
 * instead of suspending). Both were a `px-6 py-10` box holding the text
 * "Loading conversation…" — about 40px tall against a loaded header of
 * 79px, so every arrival moved the reading position. `app/(workspace)/c/[id]/loading.tsx`
 * is the third, for client-side navigation.
 *
 * WHAT "RESERVES THE REAL HEADER + REPORT HEIGHT" MEANS, EXACTLY. Every
 * number below is the loaded thread's own geometry, not an approximation
 * of it:
 *
 *   header padding   `px-6 py-4`      — ConversationThread.tsx:189
 *   title line box   28px             — `--text-ui-xl-line`, the loaded
 *                                       title's line height
 *   gap              2px              — `mt-0.5`, ConversationThread.tsx:193
 *   meta line box    16px             — `--text-ui-xs-line`
 *   bottom rule      1px              — the header's border
 *   report column    `min-h-0 flex-1` — the same track the loaded
 *                                       transcript fills, so its height is
 *                                       the container's and not the
 *                                       content's
 *
 * The report column is the part that would otherwise be guessed at. It is
 * not given a line count that happens to look right; it is given the
 * remaining grid track, which is definite in both states because
 * `.ew-shell__surface` is a fixed-height box (workbench.css). A skeleton
 * whose height is derived from its own content cannot promise CLS 0.
 *
 * THE `h1` IS CLIPPED, AND THAT IS THE HONEST FORM. Criterion 2 requires
 * an `h1` on every recovery surface; this surface has nothing to title
 * itself with, because the thread's title is exactly what has not arrived.
 * So the heading is real and in the accessibility tree — `page-has-heading-one`
 * is clean, `empty-heading` is clean — and the space where the visible
 * title will be drawn is held by a placeholder bar at that title's line
 * height. Printing a fake title, or promoting "Loading this thread" to a
 * visible `h1` that then vanishes, would be the layout shift wearing a
 * different coat.
 *
 * NOTHING MOVES AND NOTHING SHIMMERS. `Skeleton` has no animation at all
 * (03 §3.7 forbids skeleton shimmer by name), so this surface loses no
 * information under `prefers-reduced-motion`.
 *
 * `aria-busy` is on the container that owns the load, which is this one —
 * the Skeleton primitive deliberately leaves that to its caller, because
 * only the caller knows where the boundary is.
 */

import { Skeleton } from "@/components/primitives/Skeleton";
import { VisuallyHidden } from "@/components/primitives/VisuallyHidden";
import { RECOVERY } from "@/lib/copy/recovery";

export interface ThreadSkeletonProps {
  className?: string;
}

export function ThreadSkeleton({ className }: ThreadSkeletonProps) {
  return (
    <div
      aria-busy="true"
      data-recovery-surface="loading"
      className={["flex h-full flex-col", className].filter(Boolean).join(" ")}
    >
      <header className="border-b border-border-subtle px-6 py-4">
        <VisuallyHidden as="h1">{RECOVERY.loadingHeading}</VisuallyHidden>
        {/* The title's line box, held open at the title's own line height. */}
        <Skeleton width="24ch" height="var(--text-ui-xl-line)" />
        {/* `mt-05` is 2px: the loaded header's `mt-0.5` between the two rows. */}
        <Skeleton
          width="16ch"
          height="var(--text-ui-xs-line)"
          className="mt-05"
        />
      </header>

      <div className="min-h-0 flex-1 overflow-hidden px-6 py-5">
        <Skeleton
          lines={10}
          height="var(--text-report-body-size)"
          label={RECOVERY.loadingReport}
        />
      </div>
    </div>
  );
}
