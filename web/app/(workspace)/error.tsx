"use client";

import { lazy, Suspense } from "react";

/**
 * `app/(workspace)/error.tsx` — the shell-level recovery boundary
 * (04 §2.1, 03 §2.2 row 21's route-level sibling).
 *
 * THIS IS WHERE WO-08'S SLOT RULE DOES HOLD. Unlike `app/not-found.tsx`
 * (read its header for the measurement), an `error.tsx` boundary is placed
 * INSIDE its segment's layout: the layout renders, and the boundary swaps
 * only the layout's `children`. So this component arrives as `children` of
 * `WorkbenchShell`, inside the single `<main id="main">`, with the header
 * and the thread rail still on screen and still usable — which is the whole
 * point of putting it here rather than at the root. A crash in the landing
 * composer costs the composer, not the workbench.
 *
 * Next requires an `error.tsx` to be a client component, so this entry is in
 * the first-load chunk union of BOTH routes in the group. The actual surface
 * and its copy stay behind `lazy()`: the isolated work-order builds passed,
 * but WO-09 + WO-14 + WO-17 together exceeded `/c/[id]` by 1,095 B gzip.
 * Moving the shared recovery surface—not the ceiling—restored the ratified
 * budget. `null` is only the chunk-flight fallback after a render has
 * already failed; the settled surface still owns the required `h1` and
 * recovery control.
 *
 * IT DOES NOT LOG. `error.digest` is the server's own correlation hash and
 * the server already logged the stack under it; sending a second report
 * from here would be a network call on a surface that exists because
 * something already failed.
 */

const RouteError = lazy(() => import("@/components/patterns/RouteError"));

export default function WorkspaceError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <Suspense fallback={null}>
      <RouteError kind="workspace" error={error} reset={reset} />
    </Suspense>
  );
}
