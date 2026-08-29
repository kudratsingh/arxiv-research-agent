"use client";

/**
 * ThreadRailBridge — the only part of the shell that touches the data layer.
 *
 * It exists so that `WorkbenchShell` does not. 04-ARCHITECTURE.md §5.1's
 * layer rule is that a component's states are reachable by passing props,
 * "so their stories need no MSW and no network"; the shell's `rail` prop is
 * that seam, and this module is what the `(workspace)` layout passes
 * through it. Keeping the import here rather than as the shell's default
 * has one measurable consequence beyond tidiness: the Storybook project
 * never loads `lib/api` at all, so the coverage report counts the client
 * once instead of once per Vitest project.
 *
 * WHAT IT PRESERVES. `ConversationsShell.tsx:17-19` navigated with
 * `router.push('/c/' + id)`, or `/` for the empty id, and passed the route's
 * own `params.id` as the active thread. Both survive verbatim — the active
 * id now comes from `usePathname()` because a layout has no `params`, and it
 * is decoded because a pathname is percent-encoded and `params.id` was not.
 * WO-14 changed one thing about the push: the rail hands over a full HREF
 * rather than an id, because the attached run's row carries `?job=` and an
 * id cannot express that (criterion 1, R-02).
 *
 * WO-14 — THE SWAP, AND WHY THE RAIL ARRIVES LAZILY.
 * `components/ConversationSidebar.tsx` is no longer rendered here; it stays
 * on disk until WO-31 removes it, with its own tests still green.
 * `components/features/ThreadRail.tsx` replaces it through `React.lazy`,
 * for the same reason WO-08 lazily imports `ThreadDrawer`: this module is
 * reached from `app/(workspace)/layout.tsx`, so everything it imports
 * statically is charged to BOTH routes' first-load JavaScript, and the rail
 * pulls in TanStack Query (+8,016 B gzip on `/` when WO-08 measured it) and
 * two Radix packages. `/` has 4,632 B of headroom under RC-01's 148,480 B
 * ceiling. The fallback below is not a placeholder for that split — it is
 * the rail's own loading state, the same chrome and the same three rows at
 * the same height (03 §2.2 row 2), so the chunk boundary cannot be seen and
 * cannot shift anything when it resolves.
 */

import { usePathname, useRouter } from "next/navigation";
import { Suspense, lazy } from "react";

import { COMPACT_QUERY } from "@/components/app/WorkbenchShell";
import {
  ThreadListSkeleton,
  ThreadRailFrame,
} from "@/components/patterns/ThreadRailFrame";
import { THREAD_RAIL } from "@/lib/copy/threads";

/**
 * The request is started when this MODULE is evaluated — but only at the
 * widths where the rail is going to be rendered.
 *
 * `lazy(() => import(…))` defers the request to first render, which is the
 * right default for a surface that may never be shown — the drawer WO-08
 * lazily imports is exactly that. At `compact` and `expanded` the rail is
 * the opposite: it is rendered on every route in the workbench, so waiting
 * for a render to begin fetching it buys nothing and costs latency on the
 * critical path. Hoisting the `import()` keeps the only property the budget
 * accounting cares about — it is still a separate chunk, absent from both
 * routes' first-load union — while removing that latency, and it is what
 * makes the fallback a frame rather than a state.
 *
 * WHAT THE UNCONDITIONAL HOIST COST, AND WHERE (Gate 3 criterion 7).
 * "Rendered on every route in the workbench" is true above 768px and false
 * below it: WO-08's repair is that the rail is *not in the layout at all* in
 * `drawer` mode. This module is still imported by `app/(workspace)/layout.tsx`
 * at every width, so an unconditional hoist fetched the rail's chunk —
 * `ThreadRail` plus the Dialog primitive plus `@radix-ui/react-dialog`,
 * **34,396 B** over three requests, measured on `/c/[id]` — on the one form
 * factor that never renders a pixel of it, and it landed on the critical path
 * ahead of `GET /conversations/{id}`. `docs/revamp/evidence/gate-3/lighthouse-diff.md`
 * §4.2 records the LCP that produced.
 *
 * So the warm-up is now asked the same question the shell asks: does this
 * viewport have a rail? `COMPACT_QUERY` is imported rather than restated, so
 * there is still exactly one definition of 768px on the JavaScript side. A
 * viewport that later crosses the breakpoint still gets the rail — `lazy`
 * calls `loadRail` on the first render either way, and the promise is
 * memoised, so the chunk is requested once whichever path reaches it first.
 */
let railChunk: Promise<typeof import("@/components/features/ThreadRail")> | null =
  null;

function loadRail(): Promise<typeof import("@/components/features/ThreadRail")> {
  railChunk ??= import("@/components/features/ThreadRail");
  return railChunk;
}

if (typeof window !== "undefined" && window.matchMedia?.(COMPACT_QUERY).matches) {
  void loadRail();
}

const ThreadRail = lazy(loadRail);

/** `/c/<id>` → `<id>`, decoded. Anything else → `null`. */
export function activeConversationIdFrom(pathname: string | null): string | null {
  const match = /^\/c\/([^/]+)/.exec(pathname ?? "");
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    // A malformed escape sequence in the URL is not a reason to blank the
    // rail; the raw segment still identifies the row to highlight.
    return match[1];
  }
}

/** The rail's chrome with its three reserved rows, and no data layer at all. */
export function ThreadRailFallback() {
  return (
    <ThreadRailFrame
      heading={THREAD_RAIL.heading}
      newThreadLabel={THREAD_RAIL.newThread}
      state="loading"
    >
      <ThreadListSkeleton label={THREAD_RAIL.loading} />
    </ThreadRailFrame>
  );
}

export default function ThreadRailBridge() {
  const router = useRouter();
  const pathname = usePathname();

  return (
    <Suspense fallback={<ThreadRailFallback />}>
      <ThreadRail
        activeConversationId={activeConversationIdFrom(pathname)}
        onNavigate={(href) => {
          router.push(href);
        }}
      />
    </Suspense>
  );
}
