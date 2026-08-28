// The workbench shell's copy (WO-08), in WO-12's dictionary.
//
// WHY A FOURTH FILE RATHER THAN MORE OF threads.ts. 06-WORK-ORDERS.md §5.6's
// file-ownership rule: one file per surface, "so WO-13 … WO-19 add their own
// file rather than queueing on a shared one". The same rule applies
// backwards — WO-08 and WO-12 were written concurrently, and this file is
// the seam that let both land without one editing the other's module.
//
// WHAT IS *NOT* HERE, DELIBERATELY. The workspace indicator, the rail's
// heading, its collapse and expand labels, and the drawer's own name are
// already `WORKSPACE` and `THREAD_RAIL` in ./threads.ts. The shell imports
// those rather than restating them: a second copy of "Shared workspace"
// would be a second thing to keep honest, and 03 §6's indicator is exactly
// the sentence seam S6 exists to protect.
//
// Every string below is held to the same gate as the rest of the dictionary
// — 03 §5.5's deny-list, seam S6's ownership prohibition and RC-12's
// lexicon — by web/tests/copy/shell-copy.test.ts, which reuses
// `DENY_LIST` / `LEXICON_PHRASES` / `findForbidden` from ./index.ts rather
// than restating any of them.
//
// Import this module directly (`@/lib/copy/shell`), never through the
// barrel: every string here is route JavaScript, and a barrel import pulls
// all four surfaces into a route that needed one.

/**
 * The shell's chrome.
 *
 * `offline` is a *state*, not an announcement. 03 §7.3 allows exactly two
 * live regions product-wide — one `role="status"` and one `role="alert"` —
 * and both are spoken for by the trace spine and by user-triggered
 * failures, so the shell states this and WO-12's `StatusBanner` is what
 * announces it.
 *
 * `newQuestion` is the icon strip's only navigation. It goes to `/`, the
 * landing composer, and says what the user gets rather than what the
 * control does — the same sentence `THREAD.notFoundBackToStart` uses for
 * the same destination.
 */
export const SHELL = {
  offline: "Offline",
  newQuestion: "Start a new question",
  closeDrawer: "Close the thread drawer",
  /**
   * The pan region inside the drawer. The rail it wraps is a fixed 256px
   * (`ConversationSidebar.tsx:89`), which is wider than the drawer's
   * content box at a 320px viewport, so 04 §8.3 item 4's `ScrollRegion`
   * carries it — and a focusable scroll container must be named.
   */
  drawerList: "Thread list",
} as const;

/**
 * The theme control (03 §4.9, RC-05).
 *
 * Three words, and the third is the one that matters: "System" is a
 * *preference*, not a theme. The product stores it as such, so the control
 * has to name it as such — a toggle that offered only Light and Dark would
 * be unable to express "follow the OS" and would silently freeze whichever
 * theme the user last saw.
 */
export const THEME_CONTROL = {
  groupLabel: "Theme",
  light: "Light",
  dark: "Dark",
  system: "System",
} as const;
