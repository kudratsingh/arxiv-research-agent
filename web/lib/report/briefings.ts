// One shared source of truth for WHICH briefing is on screen (WO-18 c9).
//
// THE DEFECT THIS CLOSES IS REAL AND WAS REPRODUCED. 00-DISCOVERY.md carried
// it as an inference — "the terminal path may render a successful report
// twice, once as the newly reloaded historical turn and once as retained
// current-job detail … it must be confirmed with a deterministic browser
// test before being promoted to a defect". A Chromium run against
// `next start` on the attach path confirms it: after the terminal frame,
// `ConversationThread`'s `onDone` calls `load()`, the refetched thread now
// contains the finished run and auto-expands it
// (`ConversationThread.tsx:45-51`), and the "Current turn" panel below it is
// still holding the same job's `detail` and rendering it through
// `ReportView` (`ConversationThread.tsx:230-235`). Two `.report-prose`
// blocks, one job. The measurement is in this work order's PR body.
//
// 03 §4.7 names the remedy rather than the symptom: "The new split gives the
// current run and the thread history one shared source of truth for 'which
// job is on screen'." This module is that source of truth, and it is a pure
// function so the property can be asserted without a browser.
//
// THE RULE IS ONE LINE. A job id appears at most once in the output. The
// current run does not ADD a briefing; it REPLACES the history's copy of the
// same run, in place, and is appended only when history has not caught up
// with it yet. There is no arrangement of inputs that produces two entries
// for one job — `web/tests/report/briefings.test.ts` drives the reproduced
// scenario frame by frame and asserts exactly that.
//
// WO-20 composes the route from this. The legacy path keeps its defect until
// WO-20 stops rendering `ConversationThread` and WO-31 deletes it; that
// sequencing is the work orders', not this module's.

/** What a run's failure contributes, if it failed (RC-16: unedited). */
export interface BriefingFailure {
  errorType: string | null;
  error: string | null;
}

/**
 * A turn as the thread's history knows it.
 *
 * `ConversationJobSummary` (`schemas.py:184-191`) carries no status and no
 * error, so a historical turn cannot say whether its run failed. That is a
 * contract fact, not an omission here: a failed-partial turn read back from
 * history is indistinguishable from a successful one, and this module does
 * not invent the difference.
 */
export interface HistoryTurn {
  jobId: string;
  ordinal: number;
  question: string;
  markdown: string;
}

/** The run this browser is watching, as `GET /research/{id}` settled it. */
export interface CurrentRun {
  jobId: string;
  question: string;
  markdown: string;
  /** `null` unless the run failed. */
  failure: BriefingFailure | null;
}

/** One briefing to render. Exactly one per job id, always. */
export interface Briefing {
  jobId: string;
  ordinal: number;
  question: string;
  markdown: string;
  /**
   * `true` when the current run is the authority for this body — either
   * because it is the run in flight, or because it is the one that just
   * settled and history has been refetched to include it.
   */
  live: boolean;
  /** Only ever known for the current run. See `HistoryTurn`. */
  failure: BriefingFailure | null;
}

/**
 * The briefings a thread shows, in ordinal order, deduplicated by job id.
 *
 * The current run's body wins over the history copy when it has one: `GET
 * /research/{id}` is the reconciling read H9 requires before success is
 * claimed, so it is the fresher of the two. When it is empty — a run still
 * in flight, or one that failed with nothing retained — the history copy
 * stands, because a settled body already on the wire is not something to
 * throw away for a run that has not written one.
 */
export function selectBriefings(
  turns: readonly HistoryTurn[],
  current: CurrentRun | null,
): Briefing[] {
  const ordered = [...turns].sort((left, right) => left.ordinal - right.ordinal);

  const briefings: Briefing[] = ordered.map((turn) => ({
    jobId: turn.jobId,
    ordinal: turn.ordinal,
    question: turn.question,
    markdown: turn.markdown,
    live: false,
    failure: null,
  }));

  if (current === null) return briefings;

  const existing = briefings.findIndex((entry) => entry.jobId === current.jobId);

  if (existing >= 0) {
    // THE WHOLE DEFECT, IN ONE BRANCH. History has caught up with the run
    // this browser is watching, so the run is already on screen. It is
    // updated, never appended.
    const found = briefings[existing] as Briefing;
    briefings[existing] = {
      ...found,
      question: current.question === "" ? found.question : current.question,
      markdown: current.markdown === "" ? found.markdown : current.markdown,
      live: true,
      failure: current.failure,
    };
    return briefings;
  }

  // History has not caught up yet: the run is the newest turn.
  const lastOrdinal = briefings.at(-1)?.ordinal ?? 0;
  briefings.push({
    jobId: current.jobId,
    ordinal: lastOrdinal + 1,
    question: current.question,
    markdown: current.markdown,
    live: true,
    failure: current.failure,
  });
  return briefings;
}
