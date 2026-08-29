/**
 * `app/not-found.tsx` — the product 404 (03 §2.2 row 22, WO-09 criterion 1).
 *
 * It replaces the framework default
 * ([baseline](../../docs/revamp/baseline/screenshots/framework-not-found-desktop.png)),
 * which is Next's `next-error-h1`: the numeral 404 beside "This page could
 * not be found", centred on an otherwise empty document. No rail, no
 * landmarks, no way back into the product, and — because it is not inside
 * the shell — the `landmark-one-main` and `region` failures that WO-08
 * exists to close.
 *
 * WHY THIS FILE IS AT THE ROOT AND RENDERS THE SHELL ITSELF, RATHER THAN
 * SITTING IN `(workspace)/` AND INHERITING IT. This is the one place where
 * WO-08's slot rule — "WO-09's recovery surfaces render as `children`,
 * inside `main`, and therefore inherit the landmark structure and the `h1`
 * position for free" (components/app/WorkbenchShell.tsx) — does not hold,
 * and the reason is Next's, not ours. It was measured on this branch
 * against `next build --webpack` + `next start`, Next 16.3.3:
 *
 *   arrangement                                   GET /does-not-exist
 *   ------------------------------------------------------------------
 *   app/(workspace)/not-found.tsx alone           404, framework default.
 *                                                 The group's not-found is
 *                                                 never consulted: an
 *                                                 unmatched URL matches no
 *                                                 segment in the group, so
 *                                                 the boundary Next
 *                                                 resolves is the root's.
 *   + app/(workspace)/[...unmatched]/page.tsx     404, our component — and
 *     calling notFound()                          `<body>` EMPTY. The
 *                                                 `notFound()` throw aborts
 *                                                 the streamed shell, so
 *                                                 the whole surface is
 *                                                 client-rendered: no
 *                                                 `data-workbench-shell`,
 *                                                 no `id="main"`, no
 *                                                 `nav[aria-label]` in the
 *                                                 HTML at all.
 *   app/not-found.tsx rendering WorkbenchShell    404, statically
 *   (this file)                                   prerendered, and the HTML
 *                                                 contains the shell, the
 *                                                 single `<main id="main">`
 *                                                 and the rail landmark.
 *
 * The third row is the only one that satisfies criterion 1's "the rail
 * intact", because it is the only one where the rail is in the response.
 * The middle row is worth recording rather than merely rejecting: it is the
 * arrangement the slot rule implies, it looks correct in a browser, and it
 * ships a 404 with no server-rendered content — which axe, Lighthouse and
 * every crawler read as an empty page.
 *
 * The cost is one extra mount site for the shell. It is not a second shell
 * on any document: Next's not-found boundary REPLACES the segment tree
 * below the root layout, so when this renders, `app/(workspace)/layout.tsx`
 * does not. `web/tests/shell/recovery.test.tsx` asserts exactly one
 * `<main>` here for that reason.
 *
 * ROUTE BUDGETS. `/_not-found` is its own build entry, so the shell modules
 * this file pulls in are attributed to that entry and not to `/` or
 * `/c/[id]` (web/scripts/route-budgets.mjs reads each entry's own
 * `page_client-reference-manifest.js`). The PR body carries the measured
 * before/after for both gated route rows.
 */

import ThreadRailBridge from "@/components/app/ThreadRailBridge";
import { WorkbenchShell } from "@/components/app/WorkbenchShell";
import { NotFound } from "@/components/patterns/NotFound";
import { ROUTE_ERROR } from "@/lib/copy/recovery";

export default function NotFoundPage() {
  return (
    // The same two arguments `app/(workspace)/layout.tsx` passes, for the
    // same reason: the rail is handed in rather than defaulted inside the
    // shell, so `WorkbenchShell` still has no path to the data layer.
    <WorkbenchShell rail={<ThreadRailBridge />}>
      <NotFound
        heading={ROUTE_ERROR.notFoundHeading}
        body={ROUTE_ERROR.notFoundBody}
        // Criterion 1 names this action and this destination. It is the
        // same sentence the collapsed rail's `+` control uses for the same
        // place (`SHELL.newQuestion`), because it is the same offer.
        actionLabel={ROUTE_ERROR.notFoundAction}
        actionHref="/"
      />
    </WorkbenchShell>
  );
}
