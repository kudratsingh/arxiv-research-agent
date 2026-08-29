// The metrics half of the copy dictionary (WO-19).
//
// WO-12 criterion 1 makes `web/lib/copy/` the single edit site for every
// user-facing string, and 06-WORK-ORDERS.md §5.4 gives each surface its own
// file behind the barrel so WO-13 … WO-19 never queue on one another. This
// file and `./exports.ts` are WO-19's two. The gate over both is
// `web/tests/copy/metrics-copy.test.ts`, which reuses `DENY_LIST`,
// `LEXICON_PHRASES`, `collectCopyStrings` and `findForbidden` from
// `@/lib/copy` — WO-12's lists, not a second copy of them.
//
// WHY SIX OF THESE STRINGS ALSO APPEAR IN `BRIEFING` (`./run.ts`), AND WHY
// THIS FILE DOES NOT IMPORT THEM. WO-12 wrote `BRIEFING` for this surface
// before the surface existed, so `metricsLabel`, `costLabel`,
// `qualityLabel`, `callsLabel`, `iterationsLabel` and `durationLabel` are
// already in the dictionary and must not drift. The obvious move —
// `import { BRIEFING } from "./run"` — costs more than it looks, and
// `lib/copy/report.ts` records the measurement in full: `run.ts` would join
// the Storybook project's module graph through `MetricsStrip`, and the
// merged coverage report CONCATENATES the function lists of a module both
// Vitest projects load (`web/vitest.config.mts`, the hazard recorded for
// WO-13 … WO-19). `run.ts`'s composers are driven by the unit project and by
// nothing in Storybook, so importing it here would add uncovered entries to
// a column with no headroom — and the thresholds are not ours to move.
//
// So the six strings are declared here and `web/tests/copy/metrics-copy.test.ts`
// asserts each is character-identical to its `BRIEFING` counterpart. That is
// a mechanical equality check on every render of the suite, not a
// convention: the two cannot drift without a red run. WO-31 collapses
// `BRIEFING` into these files when the legacy surfaces that read it are
// gone, and the assertion is what makes that a deletion rather than a merge.
//
// `NOT_REPORTED` IS IMPORTED RATHER THAN RESTATED, unlike the six above.
// `./errors` is already in both projects' graphs — `StatusBanner` and
// `ReportReader` both import it — so there is no measurement cost to pay,
// and 03 §5.5's qualifier is the one string in this file that other surfaces
// also say out loud. One definition wins wherever it is free.

import { NOT_REPORTED } from "./errors";

/**
 * The five real fields, their labels, and what a missing one says.
 *
 * THE FIELD IS `elapsed_sec`; THE WORD IS "Duration". RC-21 keeps
 * `JobSummary`'s five fields verbatim (iterations, quality score, cost, LLM
 * calls, elapsed) — that is the MUST-KEEP — while the WORD on screen is
 * WO-12's, because `RUN.terminalLine` already says "duration" for the same
 * number (`./run.ts`) and one quantity may not have two names in one
 * product. 03 §1.5's lexicon table does not rule on this field, so the
 * merged dictionary is the tie-break rather than a fresh choice.
 *
 * `absent` is an EM DASH (U+2014), not a hyphen-minus. 03 §4.7 asks for the
 * dash by name — `JobSummary.tsx:36` renders `-`, which reads as a minus
 * sign in a column of numbers, and next to `$0.1800` that is actively
 * misleading.
 *
 * `absentReading` is what a screen reader says in place of the dash. A bare
 * "—" is announced as "dash" or as nothing at all depending on the AT's
 * punctuation setting, so the dd carries the words as well and hides the one
 * the other user does not need. It is `NOT_REPORTED` — "not reported"
 * describes the response; "unknown" would describe us, and only one of those
 * is a fact (03 §5.5).
 *
 * `absentNote` is the criterion-2 explanation, and it is VISIBLE text rather
 * than a `title`. A `title` attribute is unreachable by keyboard, invisible
 * on touch, and unread by most screen readers — three ways of saying it is
 * not an explanation. It renders only when at least one field is missing,
 * because a legend for a symbol that is not on screen is noise.
 */
export const METRICS = {
  /** Identical to `BRIEFING.metricsLabel`; asserted. */
  label: "Run metrics",
  /** Identical to `BRIEFING.iterationsLabel`; asserted. */
  iterationsLabel: "Iterations",
  /** Identical to `BRIEFING.qualityLabel`; asserted. */
  qualityLabel: "Quality score",
  /** Identical to `BRIEFING.costLabel`; asserted. */
  costLabel: "Cost",
  /** Identical to `BRIEFING.callsLabel`; asserted. */
  callsLabel: "LLM calls",
  /** Identical to `BRIEFING.durationLabel`; asserted. */
  durationLabel: "Duration",
  absent: "—",
  absentReading: NOT_REPORTED,
  absentNote: "A dash means the run did not report that number.",
} as const;
