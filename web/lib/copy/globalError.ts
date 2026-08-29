// `app/global-error.tsx`'s copy (WO-09 criterion 5), in WO-12's dictionary.
//
// WHY A SIXTH FILE AND NOT THREE MORE KEYS IN ./recovery.ts. Measured, and
// the measurement is the same one that moved `ROUTE_ERROR` out of
// ./threads.ts. `app/global-error.tsx` is a client boundary Next installs on
// EVERY route, and so are the two `error.tsx` boundaries in
// `app/(workspace)/`. Webpack emits each of those entries as its own chunk
// and inlines the small modules they share rather than splitting them — and
// it inlines a module WHOLE, with every export, because its used-export set
// is the union across the entries that import it. One copy module holding
// both `RECOVERY` and `GLOBAL_ERROR` therefore shipped the global boundary's
// sentences inside both `error.tsx` chunks as well as inside its own: three
// copies, two of which no code path can reach. Splitting the module splits
// the bytes, and `/c/[id]`'s first-load union carries both `error.tsx`
// chunks.
//
// 06-WORK-ORDERS.md §5.6's rule is one copy file per SURFACE, and
// 04-ARCHITECTURE.md §2.1 lists `global-error.tsx` as a surface of its own —
// "last-resort boundary", on its own row, beside `not-found.tsx`. So this is
// the rule applied, not bent around a bundler.
//
// Every string below is held to the same gate as the rest of the dictionary
// — 03 §5.5's deny-list, seam S6's ownership prohibition and RC-12's
// lexicon — by web/tests/copy/recovery-copy.test.ts, which walks this module
// beside ./recovery.ts and reuses `DENY_LIST` / `LEXICON_PHRASES` /
// `findForbidden` from ./index.ts rather than restating any of them.

/**
 * The last-resort boundary — the one surface with no shell, no tokens and
 * no stylesheet.
 *
 * It replaces `<html>`, so the root layout is gone and with it the font
 * variables, the pre-paint theme script and every `--color-*` custom
 * property. The wording has to survive that, which is why it names what is
 * missing instead of pretending the frame is still there.
 *
 * `body` says "reloading is the only recovery" because it is: a global
 * error boundary's `reset()` re-renders the same tree that just threw, and
 * this boundary is reached only when the failure was above every other
 * boundary. Offering "try again" here would be offering the thing that
 * already failed.
 */
export const GLOBAL_ERROR = {
  /** The `<title>` of a document that no longer has the root layout's. */
  documentTitle: "The workbench could not be drawn",
  heading: "The workbench could not be drawn",
  body: "The failure reached above the whole workbench, so its frame — the header, the thread rail, the theme control — is not on this screen. Reloading this address is the only recovery from here.",
  detail:
    "Nothing the research service already accepted is affected. This page never held the work itself.",
  action: "Reload this page",
  referenceLabel: "Reference",
} as const;
