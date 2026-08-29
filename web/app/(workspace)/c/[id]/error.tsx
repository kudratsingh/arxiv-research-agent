"use client";

import { lazy, Suspense } from "react";

/**
 * `app/(workspace)/c/[id]/error.tsx` — the thread route's own boundary
 * (04 §2.1: "route-level recovery so a thread crash does not blank the
 * shell").
 *
 * WHY A SECOND BOUNDARY, WHEN `../../error.tsx` ALREADY EXISTS. React error
 * boundaries are caught by the nearest one, and "nearest" decides how much
 * of the page survives. Without this file a thread that throws unmounts the
 * whole group's `children` and the shell-level boundary renders instead —
 * correct, but it reports the failure as the workbench's rather than as
 * this thread's, and it discards the route context that names what went
 * wrong. With it, the failure stays inside the thread's own segment and the
 * copy can say the narrower true thing.
 *
 * THE SENTENCE IS THE NARROWER TRUE THING. `ROUTE_ERROR.errorBody` says
 * "the run itself is unaffected", which is honest for a render failure in
 * the shell — nothing was in flight. This boundary is reached with a run
 * possibly streaming, so it says what it can actually promise instead:
 * whatever the research service already accepted is untouched, and this
 * page sends nothing again on its own. H6 and R-01: a mutation is never
 * retried for anyone, and `reset()` is not a retry — it re-renders this
 * segment and issues no request of its own.
 *
 * `reset` and NOT a reload, here. Unlike `app/global-error.tsx`, the
 * document is intact: the stylesheet, the fonts and the shell are all still
 * loaded, and the thing that threw is one client subtree. Re-rendering it is
 * the cheap recovery, and it keeps the rail, the header and the theme
 * exactly where they were.
 *
 * The surface and copy are error-only for the same measured reason as the
 * parent boundary; see `../../error.tsx`. Keeping only the tiny `lazy()`
 * entry in first-load JS avoids paying twice for a state the healthy route
 * never renders.
 */

const RouteError = lazy(() => import("@/components/patterns/RouteError"));

export default function ThreadError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <Suspense fallback={null}>
      <RouteError kind="thread" error={error} reset={reset} />
    </Suspense>
  );
}
