// The briefing half of the copy dictionary (WO-18).
//
// WO-12 criterion 1 makes `web/lib/copy/` the single edit site for every
// user-facing string, and 06-WORK-ORDERS.md §5.4 gives each surface its own
// file behind the barrel so WO-13 … WO-19 never queue on one another. This
// is WO-18's file. The gate over it is
// `web/tests/copy/report-copy.test.ts`, which reuses `DENY_LIST`,
// `LEXICON_PHRASES`, `collectCopyStrings` and `findForbidden` from
// `@/lib/copy` — WO-12's lists, not a copy of them — because a second
// forbidden-string list would be a second thing to keep in step.
//
// WHY FIVE OF THESE STRINGS ALSO APPEAR IN `BRIEFING` (`./run.ts`), AND WHY
// THIS FILE DOES NOT IMPORT THEM. WO-12 wrote `BRIEFING` for this surface
// before this surface existed, so `heading`, `empty`, `partial`,
// `partialDetail` and `sectionRailLabel` are already in the dictionary and
// must not drift. The obvious move — `import { BRIEFING } from "./run"` —
// costs more than it looks:
//
//   `lib/copy/run.ts` would join the Storybook project's module graph
//   through `ReportReader`, and the merged coverage report CONCATENATES the
//   function lists of a module both Vitest projects load (the measurement
//   hazard recorded verbatim in `web/vitest.config.mts` for WO-13 … WO-19,
//   which the same note says cost an early WO-12 draft nine points of the
//   functions column). `run.ts`'s eleven composers are exercised by the unit
//   project and by nothing in Storybook, so importing it here would add
//   eleven uncovered entries to a column with no headroom — and the
//   thresholds are not ours to move.
//
// So the five strings are declared here and `web/tests/copy/report-copy.test.ts`
// asserts each is character-identical to its `BRIEFING` counterpart. That is
// a mechanical equality check on every render of the test suite, not a
// convention: the two cannot drift without a red run. WO-31 collapses
// `BRIEFING` into this file when the legacy surfaces that read it are gone,
// and the assertion is what makes that a deletion rather than a merge.
//
// TWO STRINGS ARE ACCESSIBLE NAMES, NOT VISIBLE TEXT, and they are in the
// dictionary on purpose. `copy/no-inline-text` deliberately leaves
// `aria-label` alone — a rule that flagged non-rendered strings would be
// routed around within a week — but a screen-reader user reads a
// `ScrollRegion`'s required label exactly as a sighted user reads a
// paragraph. The lint rule's scope is a lint decision; the dictionary's is a
// product decision.

/**
 * The reading surface's strings.
 *
 * `partialWord` is the `StatusBanner` word D-010 ruling 2 introduces. 03
 * §3.4 puts the word ahead of the mark and the mark ahead of the colour, so
 * a banner above a briefing has to say which of the two it is before it is
 * any colour at all — and "Partial" is the true one: a failed run whose
 * `result` survived is neither a success nor a total loss. The no-briefing
 * case passes no word and takes `SEVERITY_WORD.critical` ("Failed") from
 * `./errors`, so there is exactly one place that word is written.
 *
 * `noBriefing` is 03 §2.2 row 15 — failed, `result` empty. It is
 * deliberately NOT `empty`, whose second sentence ("One is written when the
 * run finishes") promises something this run will never produce.
 *
 * `loading` names the one thing genuinely happening while the skeleton is on
 * screen: the Markdown pipeline is being fetched (`loadReportRenderer`,
 * `lib/report/renderer.ts`). It claims no position, no fraction and no
 * finish time — none of those exist here any more than they do for a run
 * (H4).
 */
export const REPORT = {
  /** Identical to `BRIEFING.heading`; asserted. */
  heading: "Briefing",
  /** Identical to `BRIEFING.empty`; asserted. */
  empty: "No briefing yet. One is written when the run finishes.",
  /** Identical to `BRIEFING.partial`; asserted. */
  partial: "Partial briefing from a run that failed.",
  /** Identical to `BRIEFING.partialDetail`; asserted. */
  partialDetail:
    "This is what the run had written when it stopped. It is kept because it was already paid for.",
  /** Identical to `BRIEFING.sectionRailLabel`; asserted. */
  railLabel: "Sections",
  partialWord: "Partial",
  noBriefing: "This run stopped before a briefing was written.",
  loading: "Getting the briefing ready to read.",
} as const;

/**
 * The accessible name of the region a wide table pans inside (03 §7.5,
 * 04 §8.3 item 4).
 *
 * Numbered rather than fixed. `ScrollRegion` refuses an empty name because
 * an unlabelled focus stop announces as "region" and nothing else — but
 * four regions all announcing "Table in this briefing" is barely better,
 * and the ordinal is the only distinguishing fact the report reliably
 * supplies. A caption would be better still; Markdown tables do not have
 * one, and inventing one from the first header cell would be a guess.
 */
export function tableRegionLabel(ordinal: number): string {
  return `Table ${Math.max(1, Math.trunc(ordinal))} in this briefing`;
}

/** The same, for a code block that is wider than the reading column. */
export function codeRegionLabel(ordinal: number): string {
  return `Code block ${Math.max(1, Math.trunc(ordinal))} in this briefing`;
}
