/**
 * `app/(workspace)/c/[id]/loading.tsx` — the thread route's loading state
 * (04 §2.1, 03 §2.2 row 6, WO-09 criterion 4).
 *
 * A `loading.tsx` is a Suspense fallback Next wraps around the segment, so
 * this renders as `children` of `WorkbenchShell`, inside the single
 * `<main id="main">`, with the header and the thread rail already on screen
 * — WO-08's slot rule, holding exactly as written.
 *
 * IT IS A SERVER COMPONENT AND STAYS ONE. Nothing here has state, so
 * nothing here is in `/c/[id]`'s client chunk union on account of this
 * file. (`ThreadSkeleton` does reach the client bundle, but through
 * `./page.tsx`'s Suspense fallback rather than through this module — see
 * below.)
 *
 * THREE PATHS REACH A "this thread is not here yet" FRAME, AND ALL THREE
 * NOW RENDER THE SAME COMPONENT. That is the whole of criterion 4: not that
 * one file is pretty, but that the frame is one designed state instead of
 * three accidents with three different heights.
 *
 *   this file                 A CLIENT-SIDE NAVIGATION into `/c/[id]` — a
 *                             rail row, or the landing submit's redirect.
 *                             The segment suspends while its RSC payload is
 *                             fetched and this is painted meanwhile.
 *   ./page.tsx's fallback     The Suspense boundary `useSearchParams`
 *                             requires. Rarely painted (the route is
 *                             dynamic, so the hook resolves during SSR
 *                             rather than suspending) — but it is the
 *                             string criterion 4 names at `page.tsx:19`,
 *                             and it is now this component.
 *   ConversationThread's      What a COLD LOAD actually shows: the server
 *   `conversation === null`   renders through both boundaries into the
 *                             thread, whose fetch has not resolved. Also
 *                             this component now.
 *
 * The measured CLS for the cold-load transition, and the axe result for the
 * served HTML, are in the PR body.
 */

import { ThreadSkeleton } from "@/components/patterns/ThreadSkeleton";

export default function ThreadLoading() {
  return <ThreadSkeleton />;
}
