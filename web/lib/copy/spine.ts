// The trace spine's own copy (WO-15; 03 §5.3, §5.4, §5.5, §5.7).
//
// WHY A FOURTH COPY FILE RATHER THAN MORE OF `run.ts`. 06-WORK-ORDERS.md
// §5.6's file-ownership table gives every surface its own module behind
// `lib/copy/`, so WO-13 … WO-19 add a file instead of queueing on a shared
// one. Everything here is *structural* copy for the spine — region and
// ledger names, the two words the blind spot needs, the joiners — and every
// *sentence* it renders still comes from `run.ts`, which is where WO-12 put
// them. This file composes; it does not restate.
//
// IT IS NOT RE-EXPORTED FROM `lib/copy/index.ts`. That barrel is WO-12's
// file and its own header asks importers to reach for the surface module
// directly, because a barrel import pulls three (now four) files into a
// route that needed one. `web/tests/copy/spine-copy.test.ts` is this
// module's gate and reuses `lib/copy`'s deny-list, lexicon list, required
// qualifiers and walker rather than restating any of them.
//
// THE THREE STRUCTURAL RULES OF 03 §5.5 APPLY HERE UNCHANGED:
//
//   - "on this connection" travels with every checkpoint COUNT. The two
//     places a count appears below both route through `checkpointCount()`,
//     so the qualifier cannot be dropped by editing this file.
//   - "observed" travels with every checkpoint NAME. The ledger names
//     checkpoints through `observedCheckpoint()`.
//   - "not reported" replaces "unknown", everywhere. `checkpointName()` is
//     the only way this surface turns a label into text, which is what
//     closes WO-10's known issue: `machine.ts`'s `checkpointLabel()` still
//     returns the literal "unknown" for the absent case and is a
//     test/diagnostic helper, never a source of rendered copy. See
//     `observedNode()` in `lib/job/machine.ts`.

import {
  RUN_STATUS_LINE,
  RUN_STATUS_WORD,
  checkpointCount,
  lastUpdated,
} from "./trace";

// ---------------------------------------------------------------------------
// Structure.
// ---------------------------------------------------------------------------

/**
 * The names, labels and joiners the spine's structure needs.
 *
 * `running` is the one status WORD this file adds, and it is deliberately
 * bare: 03 §5.4's running row reads "Running · N checkpoints observed on
 * this connection · updated 41s ago", and only the first segment of that
 * line is a material transition. Splitting it here is what lets the
 * product's single `role="status"` announce "Running" once instead of
 * re-announcing on every checkpoint (03 §5.7).
 *
 * `notReportedYet` is state C of 06-WORK-ORDERS.md §4 — attached, and the
 * API has not said what the run is doing. It says "not reported" rather
 * than "unknown" for the reason the whole dictionary does: silence is the
 * API's behaviour, not a gap in our knowledge of it.
 */
export const SPINE = {
  /** The labelled region wrapping the four segments (03 §5.7). */
  regionLabel: "Research trace",
  /** The legend disclosure's trigger. */
  legendLabel: "What the marks mean",
  /** The nested ledger's accessible name, and its scroll region's. */
  ledgerLabel: "Checkpoints observed on this connection",
  /** Shown in place of the ledger when nothing has been observed. */
  ledgerEmpty: `${checkpointCount(0)}.`,
  /** The dimensioned dashed void's text equivalent (03 §3.4, §5.8). */
  voidWord: RUN_STATUS_WORD.notObserved,
  /** The sentence under it. 03 §5.3 prints it beneath the spine. */
  voidDescription: RUN_STATUS_LINE.positionNotReported,
  /** The material half of 03 §5.4's running line. */
  running: "Running",
  /** Attached, with no status reported yet (§4 state C). */
  notReportedYet: "Attached to this run. Its status is not reported yet.",
  /** Between a phrase and the observation detail that follows it. */
  separator: " · ",
  /** Between a finished sentence and the same detail. */
  gap: " ",
} as const;

/** The four segment names live in `run.ts` as `SPINE_SEGMENTS`. */

// ---------------------------------------------------------------------------
// Composition.
// ---------------------------------------------------------------------------

/**
 * A segment's accessible line: its name, then its status word.
 *
 * 03 §3.4's precedence is word, then mark, then colour, and §5.7 requires
 * the word to be on the same visual line as the mark. Both are rendered as
 * text; this is the joined form a screen reader hears for one segment.
 */
export function segmentLabel(segment: string, word: string): string {
  return `${segment}${SPINE.separator}${word}`;
}

/**
 * The observation detail: how many checkpoints, and how long ago.
 *
 * NEVER announced. It changes on every `node_completed`, and 03 §5.7 is
 * explicit that the live region announces material transitions and "never
 * individual checkpoints" — so this is rendered beside the announcement
 * rather than inside it.
 */
export function observationDetail(
  count: number,
  secondsAgo?: number | null,
): string {
  const updated = lastUpdated(secondsAgo);
  return updated === null
    ? checkpointCount(count)
    : `${checkpointCount(count)}${SPINE.separator}${updated}`;
}

/**
 * What goes between the announcement and the detail.
 *
 * A middot after a bare phrase ("Running · 3 checkpoints…", 03 §5.4
 * verbatim); a plain space after a sentence that already ends in a full
 * stop, because "…are not replayed. · 1 checkpoint" is not a sentence
 * anybody wrote.
 */
export function detailSeparator(announcement: string): string {
  return /[.!?]$/.test(announcement) ? SPINE.gap : SPINE.separator;
}
