// Diagnostics copy (WO-16).
//
// A SEPARATE FILE, NOT AN ADDITION TO `run.ts`, and deliberately NOT
// re-exported from `lib/copy/index.ts`. Two reasons, both structural:
//
//   1. 06-WORK-ORDERS.md §5.6's file-ownership table gives each surface work
//      order its own copy file so WO-13 … WO-19 do not queue on a shared
//      one. This is WO-16's.
//   2. The barrel is route JavaScript. `Diagnostics.tsx` imports
//      `@/lib/copy/diagnostics` and `@/lib/copy/run` directly, so a route
//      that renders the disclosure does not also pull the thread and error
//      dictionaries into its first-load chunk (04 §8.1).
//
// `DIAGNOSTICS` — the trigger label, the empty sentence, the copy action
// and its note — was written by WO-12 in `lib/copy/run.ts` as a handoff,
// before this file existed. It has MOVED here, verbatim and unedited: it is
// this surface's copy under §5.6's ownership table, and keeping it in
// `run.ts` would have made `Diagnostics.tsx` import that module, which puts
// `run.ts`'s ten composers into the Storybook project's graph where nothing
// drives them (vitest.config.mts's measurement hazard, WO-13 … WO-19).
// `run.ts` carries a pointer comment where it was.
//
// THE GATE. `web/tests/copy/diagnostics-copy.test.ts` walks every export
// below with `collectCopyStrings`, drives every exported function, and
// applies 03 §5.5's deny-list, seam S6's ownership list and RC-12's lexicon
// to the result — the same three lists `tests/copy/forbidden.test.ts`
// applies to the other three modules, imported from `lib/copy` rather than
// restated.

/**
 * The diagnostics disclosure — collapsed by default, so routine SSE frames
 * are never announced (03 §7.3).
 *
 * `copyNote` states the redaction rule as a promise the user can check:
 * no report text, no question text, no headers, no URLs beyond the path
 * template, and nothing transmitted anywhere.
 */
export const DIAGNOSTICS = {
  label: "Technical events",
  logLabel: "Received frames",
  empty: "No frames have been received on this connection.",
  copyAction: "Copy diagnostics",
  copyNote:
    "Copies the last 200 frames and the raw error strings to the clipboard. No question text, no briefing text, no headers and no keys, and nothing is sent anywhere.",
  copied: "Copied to the clipboard.",
} as const;

/**
 * The diagnostics table itself (03 §4.5: "a `<table>` of received frames
 * (time · event · detail)").
 *
 * `scrollLabel` is the REQUIRED accessible name of the `ScrollRegion` the
 * table pans inside — required at runtime, not merely typed, because a
 * focusable scroll container with no name is an unlabelled stop in the tab
 * order (`components/primitives/ScrollRegion.tsx`).
 */
export const DIAGNOSTICS_TABLE = {
  /** The `<caption>`. Clipped, so the table is named without being titled. */
  caption: "Received frames, run transitions and failures, oldest first.",
  scrollLabel: "Diagnostics table",
  columns: {
    time: "Time",
    event: "Event",
    detail: "Detail",
  },
} as const;

/**
 * What produced a record, as one word per kind.
 *
 * These are jargon on purpose, and this is the one surface in the product
 * where that is right: the reader of this table is about to paste it into
 * an issue, exactly as `rawErrorEvidence()`'s labels are the API's own
 * field names for the same reason (RC-16).
 *
 * None of the six is a lexicon word — a `node_completed` is still a
 * **Checkpoint** on every other surface, and nothing here says otherwise.
 */
export const DIAGNOSTICS_KIND_LABEL = {
  frame: "frame",
  transition: "transition",
  connection: "connection",
  terminal: "terminal",
  failure: "failure",
  vital: "web vital",
} as const;

/**
 * The web-vitals block (04 §9.2 item 2), rendered only behind `?debug=perf`.
 *
 * `note` is the honest half. Field p75 is not available to this product and
 * this copy does not pretend otherwise: these are one browser's numbers,
 * measured in this tab, held in memory, and sent nowhere.
 */
export const DIAGNOSTICS_VITALS = {
  label: "Web vitals",
  note: "Measured in this browser and held in memory. Nothing is sent anywhere.",
  empty: "No web vitals have been reported yet.",
  scrollLabel: "Web vitals table",
  columns: {
    metric: "Metric",
    value: "Value",
    rating: "Rating",
  },
  /** The three 04 §9.2 names, spelled out. Keys are the library's own. */
  metric: {
    LCP: "Largest contentful paint",
    INP: "Interaction to next paint",
    CLS: "Cumulative layout shift",
  },
  /** `web-vitals` reports one of these three per metric. */
  rating: {
    good: "good",
    "needs-improvement": "needs improvement",
    poor: "poor",
  },
} as const;

/** Every state the "Copy diagnostics" control can be in besides at rest. */
export const DIAGNOSTICS_ACTIONS = {
  copying: "Copying…",
  copyFailed:
    "Copying to the clipboard failed. Select the rows and copy them by hand.",
} as const;

/**
 * How much is held, and the two facts about it that matter.
 *
 * Not "on this connection": these records outlive a connection — a
 * reconnect is itself one of them — and the qualifier 03 §5.5 requires is
 * the one about CHECKPOINT counts, which this is not. The two true
 * statements are the ceiling and that a reload clears it (04 §9.2).
 */
export function diagnosticsRetained(count: number, capacity: number): string {
  const noun = count === 1 ? "record" : "records";
  return `${count} ${noun} held in memory. The last ${capacity} are kept, and a reload clears them.`;
}

/**
 * The count of records a full buffer has already dropped, or `null`.
 *
 * Returning `null` rather than "0 dropped" is the point: a buffer that has
 * dropped nothing should say nothing, not reassure.
 */
export function diagnosticsDropped(dropped: number): string | null {
  if (dropped <= 0) return null;
  const noun = dropped === 1 ? "record" : "records";
  return `${dropped} older ${noun} fell off the end of the buffer.`;
}
