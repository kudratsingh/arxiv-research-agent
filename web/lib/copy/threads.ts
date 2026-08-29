// The thread half of the copy dictionary (WO-12 criteria 1, 2).
//
// This is the file seam S6 is enforced in (04 §10). There is no user
// identity in this product — D-009 forbids faking one, and MT-01 is a
// separate backend workstream — so nothing here may say *your* threads or
// *my* workspace. `web/tests/copy/forbidden.test.ts` carries the four
// banned possessive phrases beside 03 §5.5's list, which is what turns S6
// from a thing a reviewer has to remember into a thing a test fails on.
//
// The lexicon (03 §1.5, RC-12 register 1) also lands here: a
// `Conversation` is a **Thread** on screen, and stays `/conversations` on
// the wire. Register 3 is the query keys and the API paths, which nothing
// in this file touches.

// ---------------------------------------------------------------------------
// The rail (03 §2.2 rows 2, 3, 4).
// ---------------------------------------------------------------------------

/**
 * The thread rail.
 *
 * `empty` is deliberately different from the loading state and from the
 * "no briefing yet" state; three different absences that look the same are
 * the baseline's problem, not this one's.
 *
 * `error` and `errorRecovery` are 03 §2.2 row 4: an inline alert at the
 * top of the rail, plus a Retry that re-runs `GET /conversations` **only**.
 * A mutation is never retried for anyone (H6, R-01).
 */
export const THREAD_RAIL = {
  heading: "Threads",
  newThread: "New research",
  loading: "Loading threads",
  empty: "No threads yet. Your first question starts one.",
  error: "The research service is not reachable.",
  errorRecovery: "Retry loading the list. Nothing is sent again on its own.",
  retry: "Retry",
  loadMore: "Load more",
  // `GET /conversations` returns a bare array with no `total` and no
  // `has_more` (03 §2.3), so "Load more" is the only honest control and
  // there is no page count to print beside it.
  endOfList: "That is every thread this deployment has.",
  collapse: "Collapse the rail",
  expand: "Expand the rail",
  openDrawer: "Threads",
} as const;

/** One row in the rail. */
export const THREAD_ROW = {
  menuLabel: "Thread actions",
  delete: "Delete thread",
  open: "Open thread",
  /** The reserved, empty owner slot (04 §10 seam S4/S6). Rendered, never filled. */
  ownerSlotLabel: "Owner",
} as const;

/** "3 turns", and the singular that a naive template gets wrong. */
export function turnCount(count: number): string {
  const n = Math.max(0, Math.trunc(count));
  if (n === 0) return "No turns yet";
  return `${n} turn${n === 1 ? "" : "s"}`;
}

// ---------------------------------------------------------------------------
// The thread surface (03 §2.2 rows 5, 21).
// ---------------------------------------------------------------------------

export const THREAD = {
  emptyHeading: "Nothing asked yet",
  emptyBody:
    "A turn is one question and the briefing it produced. Ask the first question below.",
  followUpLabel: "Ask a follow-up",
  // H8: a 404 is "not available". The API returns it both for a thread
  // that never existed and for one belonging to another principal
  // (`_check_ownership`, `src/api/routes.py:59`), so the copy names both
  // and claims neither.
  notFoundHeading: "This thread is not available",
  notFoundBody:
    "It may never have existed, or it may belong to another principal. The API answers the same way for both, so this page cannot tell which.",
  notFoundBackToStart: "Start a new question",
  notFoundBackToList: "See the threads this deployment has",
  loadErrorHeading: "This thread could not be loaded",
} as const;

// ---------------------------------------------------------------------------
// Deletion (03 §8.2; D-010 ruling 3).
// ---------------------------------------------------------------------------

/** What `deleteDialog()` gives `ConfirmDialog`. */
export interface DeleteDialogCopy {
  heading: string;
  body: string;
  confirm: string;
  cancel: string;
  pending: string;
}

/**
 * The delete confirmation, per 03 §8.2 and D-010 ruling 3.
 *
 * The second sentence is the honest one and it is load-bearing. The
 * Postgres cascade removes the conversation's job rows
 * (`src/api/conversations.py:547`), but the job store's own records live
 * under `api_job_retention_sec` on a separate lifecycle
 * (`src/config.py:307`, default 24 h) — so deleting a thread does not
 * necessarily make a recently-finished run unreachable by id. The baseline
 * said "Delete this conversation and all its jobs?"
 * (`ConversationSidebar.tsx:74`), which is wrong twice: the wrong noun,
 * and a promise of erasure the system does not perform.
 */
export function deleteDialog(title: string): DeleteDialogCopy {
  const named = title.trim();
  return {
    heading: named === "" ? "Delete this thread?" : `Delete “${named}”?`,
    body: "This removes the thread and its briefings from this workspace. Run records are kept separately and expire on their own schedule.",
    confirm: "Delete thread",
    cancel: "Cancel",
    pending: "Deleting…",
  };
}

// ---------------------------------------------------------------------------
// The shell (03 §6, 04 §10).
// ---------------------------------------------------------------------------

/**
 * The workspace indicator that occupies the identity slot today.
 *
 * 03 §6: the slot is *reserved and occupied by truthful content*, not left
 * empty and not filled with a disabled account menu. What is true today is
 * that everyone reaching this deployment sees the same threads, because
 * there is one server key and one principal.
 */
export const WORKSPACE = {
  indicator: "Shared workspace",
  indicatorDetail:
    "Everyone with access to this deployment sees these threads. There are no separate accounts.",
  skipToContent: "Skip to content",
  mainLandmark: "Workbench",
} as const;

// `ROUTE_ERROR` MOVED TO ./recovery.ts (WO-09), AND IT WAS MEASURED, NOT
// TIDIED. It is `app/not-found.tsx`'s and the route error boundaries' copy —
// WO-09's surface — and 06-WORK-ORDERS.md §5.6's rule is one copy file per
// surface. Keeping it here had a price the ratchet could see: an
// `error.tsx` is a client boundary on BOTH routes in the group, so importing
// this module from one made webpack emit a SECOND copy of the whole of
// `threads.ts` beside the one the shell already loads. `/c/[id]`'s
// first-load union carried both (200,395 B against a 199,680 B ceiling);
// with `ROUTE_ERROR` in ./recovery.ts the boundaries import ~40 lines
// instead of ~180 and the row passes. The strings themselves are unchanged.
