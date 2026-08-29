// The recovery surfaces' copy (WO-09), in WO-12's dictionary.
//
// A FIFTH SURFACE FILE, FOR THE REASON THE FOURTH ONE EXISTS.
// 06-WORK-ORDERS.md §5.6's file-ownership rule is one file per surface, "so
// WO-13 … WO-19 add their own file rather than queueing on a shared one".
// WO-08 applied it backwards to create `./shell.ts`; this file is the same
// move for WO-09, and it is why eight concurrent work orders can all add
// copy without one editing another's module.
//
// WHAT IS *NOT* HERE, DELIBERATELY. The inline thread-not-found sentence —
// the H8 one, the one that has to name BOTH causes of a 404 — stays as
// `THREAD.notFound*` in ./threads.ts, because it is a state of the THREAD
// surface and WO-20 renders it there. Only the two surfaces that are whole
// pages of their own live here.
//
// That sentence is the important one. `src/api/routes.py:59`'s
// `_check_ownership` raises 404 for a thread that belongs to another
// principal *and* for one that never existed, and it does so on purpose:
// "leaking 'this exists but you can't touch it' is an info-disclosure
// vector". So the sentence may never say "deleted" and may never say "no
// permission" — the client genuinely cannot tell which happened. Keeping it
// in ./threads.ts means there is exactly one copy of it, gated by
// web/tests/copy/forbidden.test.ts, and this work order's own gate
// (web/tests/copy/recovery-copy.test.ts) re-asserts the H8 property against
// it rather than against a second copy that could drift.
//
// Every string below is held to the same gate as the rest of the dictionary
// — 03 §5.5's deny-list, seam S6's ownership prohibition and RC-12's
// lexicon — by web/tests/copy/recovery-copy.test.ts, which reuses
// `DENY_LIST` / `LEXICON_PHRASES` / `findForbidden` from ./index.ts rather
// than restating any of them.
//
// Import this module directly (`@/lib/copy/recovery`), never through the
// barrel: a barrel import pulls all six surfaces into a chunk that needed
// one. The two error boundaries reach it from their shared error-only lazy
// module; server recovery surfaces import it directly.

/**
 * `app/not-found.tsx` and the shell-level error boundary (03 §2.2 rows 22,
 * 21). Moved here from ./threads.ts by WO-09 — see the note there for the
 * measurement that made it a byte question rather than a filing question.
 *
 * `notFoundAction` is deliberately the same sentence as `SHELL.newQuestion`
 * and `THREAD.notFoundBackToStart`: three surfaces offering the same
 * destination should offer it in the same words. It is criterion 1's named
 * primary action.
 */
export const ROUTE_ERROR = {
  notFoundHeading: "This page does not exist",
  notFoundBody: "The address does not match anything in this workbench.",
  notFoundAction: "Start a new question",
  errorHeading: "This page could not be rendered",
  errorBody: "Something failed while drawing this page. The run itself is unaffected.",
  errorAction: "Try rendering it again",
} as const;

/**
 * The route-loading skeleton and the thread-level error boundary.
 *
 * `loadingHeading` is the `h1` of a surface that has nothing to title
 * itself with yet. It is clipped rather than drawn — the visible title row
 * is a placeholder bar at the real title's line height — because
 * criterion 2 requires an `h1` on EVERY recovery surface and criterion 4
 * requires the loading state to reserve the loaded state's geometry. A
 * clipped heading satisfies both: `page-has-heading-one` passes, and the
 * box the title will occupy is the box the placeholder occupies.
 *
 * `threadErrorBody` is deliberately not `ROUTE_ERROR.errorBody`. The
 * shell-level boundary can honestly say "the run itself is unaffected",
 * because a render failure in the shell touched nothing. The thread-level
 * boundary is reached with a run possibly in flight, so it says the
 * narrower true thing: this page sends nothing again by itself (H6, R-01 —
 * a mutation is never retried for anyone).
 */
export const RECOVERY = {
  loadingHeading: "Loading this thread",
  loadingReport: "Loading the briefing",
  /**
   * Not `THREAD.loadErrorHeading` ("This thread could not be loaded"),
   * which belongs to a different state: that one is `GET /conversations/{id}`
   * failing, and WO-20 renders it inline with a Retry. This one is the
   * thread's own markup throwing while React drew it, where there is
   * nothing to re-fetch and nothing to retry.
   */
  threadErrorHeading: "This thread could not be drawn",
  threadErrorBody:
    "Something failed while drawing this thread. Whatever the research service already accepted is untouched, and this page sends nothing again on its own.",
  /**
   * Next hands an error boundary an `error.digest` — a hash the server
   * logged the real failure under. RC-16's rule applies to it exactly as it
   * applies to a backend `error` string: it is shown labelled, under the
   * sentence, never as the sentence. When the runtime produced no digest
   * the row is absent rather than filled with a placeholder.
   */
  referenceLabel: "Reference",
  referenceRecovery: "Quote this reference to whoever operates this deployment.",
} as const;
