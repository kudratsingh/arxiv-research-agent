/**
 * WO-27 criterion 7 — what a story may assume about the rail at its width.
 *
 * THE PROBLEM THIS SOLVES, AND WHERE IT CAME FROM. The Gate 3 pack ran every
 * story in a real browser at RC-14's five widths in three modes — 3,915
 * renders — and found 48 play-function assertion errors across 6 stories
 * (`evidence/gate-3/known-gaps.md` §2d). Eighteen of them were three `Shell`
 * stories looking for the rail at 320 and 412, where **the product
 * deliberately does not have one**. The pack's own verdict: "The components
 * are behaving correctly; the stories do not say which viewport they are
 * meaningful at."
 *
 * WHY NOT SIMPLY PIN A VIEWPORT. `parameters.viewport` tells Storybook's
 * toolbar what to open with; it does not stop a harness — the Gate 3 render
 * matrix, a future visual-regression sweep, a reader dragging the canvas —
 * from rendering the story at some other width. A story that throws when
 * someone resizes it is still a broken story, and "declare the viewport"
 * would only move the failure somewhere less visible. So the play functions
 * branch on what the product actually did, and assert something true in each
 * branch rather than skipping.
 *
 * WHY THE TEST IS `display`, AND WHY THAT IS RIGHT IN BOTH ENVIRONMENTS.
 * Below `md`, `WorkbenchShell` resolves `railMode` to `drawer` and does not
 * render the rail at all — but the three stories in question pass
 * `railMode="expanded"` as a prop, so the `<nav>` IS in their DOM and
 * `workbench.css`'s `@media (max-width: 767px) { .ew-shell__rail { display:
 * none } }` is what removes it. Reading `display` therefore distinguishes the
 * two cases in a real browser.
 *
 * In jsdom — where the Vitest Storybook project runs every story once — no
 * `@media` block whose media list omits `screen` is ever applied
 * (jsdom/living/helpers/style-rules.js; see also
 * `web/tests/primitives/support/css.ts`). So `display` comes back as the base
 * value and jsdom takes the `in-layout` branch, which is the branch jsdom can
 * satisfy. That is not a coincidence being exploited: it is the same fact —
 * "is the responsive rule in effect here?" — read the same way in both.
 *
 * `window.innerWidth` was the obvious alternative and is wrong for exactly
 * that reason: jsdom reports 1024 regardless of any viewport a harness sets,
 * so a width-based branch would send jsdom down whichever path the number
 * happened to pick rather than the one its rendering supports.
 */

/** Where the rail is, from the document's point of view. */
export type RailPresentation =
  /** Rendered and laid out: the story may look for it. */
  | "in-layout"
  /** In the DOM but `display: none` — below `md`, by 04 §8.3 repair step 1. */
  | "hidden-by-css"
  /** Not rendered: the shell resolved `railMode` to `drawer`. */
  | "not-rendered";

/** The shell's rail landmark, by the id `WorkbenchShell` gives it. */
export const RAIL_SELECTOR = "#workbench-rail";

export function railPresentation(root: ParentNode = document): RailPresentation {
  const rail = root.querySelector(RAIL_SELECTOR);
  if (rail === null) return "not-rendered";
  return window.getComputedStyle(rail).display === "none" ? "hidden-by-css" : "in-layout";
}

/** True when a story may assert on rail contents at the current width. */
export function railIsAvailable(root: ParentNode = document): boolean {
  return railPresentation(root) === "in-layout";
}
