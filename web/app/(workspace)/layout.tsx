/**
 * The `(workspace)` route group's layout — the workbench shell (WO-08).
 *
 * `(workspace)` IS A ROUTE GROUP, so it contributes **no URL segment**
 * (04-ARCHITECTURE.md §2.1). `/` and `/c/[id]?job=` are byte-identical to
 * what they were before this file existed, which criterion 2 asserts as a
 * routing test rather than as a claim.
 *
 * WHY A LAYOUT AND NOT A COMPONENT. Before this, `web/app/page.tsx:54` and
 * `web/app/c/[id]/page.tsx:12` each wrapped themselves in
 * `<ConversationsShell>` by hand — "which is how the missing `<main>` went
 * unnoticed across every state". A layout cannot be forgotten by a new
 * route, so `landmark-one-main` cannot regress the way it originally
 * arrived. WO-09's `error.tsx` and `c/[id]/loading.tsx` land inside this
 * same layout and inherit the landmarks for free.
 *
 * A server component. `WorkbenchShell` is the client boundary, and it is as
 * far down the tree as that boundary can be pushed while still owning the
 * three responsive modes.
 *
 * WHY THE SHELL'S MODULES LIVE UNDER `components/app/` AND NOT BESIDE THIS
 * FILE. RC-10 assigns `WorkbenchShell` to an `app/` *layer*, and the obvious
 * reading is a directory next to this one. It measures wrong.
 * `web/scripts/route-budgets.mjs` attributes a client module to a route only
 * when it is a route-segment file (`isOnRouteSegmentPath`, matched against
 * `page|layout|error|loading|…`), because the Next 16 manifest for one entry
 * also lists other entries' modules. A `WorkbenchShell.tsx` sitting in
 * `app/(workspace)/` is an `app/` file that is not a segment file, so its
 * chunk — the whole shell, plus everything it pulls in — is silently
 * dropped from `/` and `/c/[id]`: this branch measured `/` at 135,547 B in
 * that arrangement, 4,423 B *below* main, while adding code to both routes.
 * Under `components/` the same modules are counted unconditionally. The
 * layer is expressed as `components/app/`, which also puts them inside the
 * existing Storybook glob and the no-literal-colour rule's `files`.
 */

import type { ReactNode } from "react";

import ThreadRailBridge from "@/components/app/ThreadRailBridge";
import { WorkbenchShell } from "@/components/app/WorkbenchShell";

/**
 * The rail is passed in rather than defaulted inside the shell. See
 * components/app/ThreadRailBridge.tsx: it is the only module in the shell
 * that reaches the data layer, and keeping it out of `WorkbenchShell.tsx` is
 * what lets the shell's stories and tests render the whole thing with no
 * network.
 */
export default function WorkspaceLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <WorkbenchShell rail={<ThreadRailBridge />}>{children}</WorkbenchShell>;
}
