// The Ledger's half of the copy dictionary (WO-W14).
//
// Everything a reader sees on `/learn/progress` is a string in this file,
// for the reason the barrel states: the honesty rules are rules about
// *sentences*, and a sentence rule enforced in the component that renders
// it can only be enforced by remembering it.
//
// THIS FILE IS SEPARATE FROM `./learn.ts` ON PURPOSE. The path surfaces'
// copy and the Ledger's are two surfaces with two owners
// (`05-WEDGE-WORK-ORDERS.md` §5.4: one file per surface behind the
// barrel), and both are held to the same lists.
//
// FOUR THINGS ARE STRUCTURAL HERE, NOT STYLISTIC:
//
//   - NO KNOWLEDGE SCALAR EXISTS. `01-LEARNING-AGENT.md` §4.1 allows three
//     currencies of progress — assessment events, repetition history and
//     artifacts — and bans one: "You are 87% through Transformers" is a
//     claim about a latent variable no judge can measure. There is no key
//     in this file that can carry a percentage, a grade or a level, and
//     `web/tests/copy/forbidden.test.ts` holds every string here to the
//     pedagogy vocabulary in `./index.ts` so a later one cannot either.
//   - SCHEDULE ARITHMETIC CARRIES ITS LABEL IN THE SAME STRING.
//     `scheduleFigure` composes "Schedule · 3 of 3 sessions" as ONE value
//     rather than leaving a label and a number to be placed next to each
//     other, because 01 §4.1 requires session arithmetic to be labelled as
//     schedule progress rather than knowledge, and two elements can drift
//     apart under a layout change while one string cannot.
//   - AN ABSENCE IS REPORTED AS AN ABSENCE. A path with no assessment
//     event reads "Not yet observed", never a zero: `00-VISION.md` §5.4
//     ("what was never assessed is marked unobserved, not guessed at").
//   - THE WORD "LEDGER" IS THE LEXICON'S (00 §5.5). Never dashboard,
//     never profile, never stats.
//
// Nothing here offers an export. The export pipeline exists for reports
// (ADR 0031) but the Ledger's export is not in Phase W's scope, and a
// control that pretends otherwise is the failure mode criterion 4 names.

export const LEDGER = {
  eyebrow: "Learning record",
  heading: "Ledger",
  /**
   * The page's one claim about itself. It is a claim about provenance —
   * where the lines came from — and not about what anyone knows.
   */
  lead:
    "Every line here is folded from recorded events. Nothing on this page " +
    "is inferred, and nothing here is a claim about what is understood.",

  /** The evidence log. */
  evidenceHeading: "Recorded evidence",
  evidenceIntro:
    "What was recorded, when it was recorded, and the record that backs it. " +
    "The Ledger holds that each of these happened — never how well.",
  evidenceRefLabel: "Evidence",
  pathLabel: "Path",

  /** The schedule half, which is arithmetic about sittings. */
  scheduleHeading: "Schedule progress",
  scheduleIntro:
    "Sessions counted against each path. This is arithmetic about sittings, " +
    "not a statement about what was learned.",
  /** The word that travels with every figure. See `scheduleFigure`. */
  scheduleLabel: "Schedule",

  /**
   * Observation, and the honest absence of it.
   *
   * Both markers are rendered, and the pair is the point: a row that said
   * "Observed" only when it had something to say would leave the reader to
   * infer the other case, and 00 §5.4 is that what was never assessed is
   * MARKED unobserved rather than left blank.
   */
  observed: "Observed",
  notObserved: "Not yet observed",
  notObservedBody:
    "No assessment event has been recorded against this path. That is an " +
    "absence in the record, not a result.",

  /** The empty state (criterion 4). Honest, calm, and offering nothing. */
  emptyHeading: "No sessions yet",
  emptyBody:
    "Nothing has been recorded on this deployment. When a guided session " +
    "ends, it appears here with the events behind it.",

  /** The feature's two non-content states. */
  loading: "Loading the Ledger…",
  unavailableHeading: "The Ledger is unavailable",
  unavailableBody:
    "The learning record is not available from the research service right now.",
  retry: "Try again",
} as const;

/**
 * The two strings that live on ANOTHER route, and why they are a separate
 * export rather than two more keys in `LEDGER`.
 *
 * ONE LINK, NOT A SECOND NAVIGATION ROW. 00 §5.5: "the moment the shell
 * needs a second row of navigation, the design has failed this section."
 * The Ledger is one of the four allowed surfaces, so it gets a way in —
 * from `/learn`, the surface a reader is already on, rather than from new
 * chrome on every page.
 *
 * AND IT IS A SEPARATE BINDING FOR A MEASURED REASON. `lib/copy/index.ts`
 * warns that "every string in here is route JavaScript"; an object literal
 * is one binding, so a module that imported `LEDGER` for two of its keys
 * would ship all of them. Measured on this branch: `/learn` first-load JS
 * went 157,649 B → 160,793 B when `PathListSurface` imported `LEDGER`, and
 * back to within a few hundred bytes of the baseline once the two strings
 * it actually renders became their own export. Same rule as the
 * `run.ts` → `trace.ts` split, one level down.
 */
export const LEDGER_ENTRY = {
  openLedger: "Open the Ledger",
  entryBody: "What has been recorded so far, with the events behind each line.",
} as const;

/**
 * The event kinds this surface has a sentence for.
 *
 * `01-LEARNING-AGENT.md` §4.4 reserves the full vocabulary; Phase W writes
 * three of them. A kind with no entry is NOT translated — `evidenceKindLabel`
 * falls back to the neutral form rather than inventing a description of an
 * event this surface has never seen.
 */
export const EVIDENCE_KIND_LABEL: Readonly<Record<string, string>> = {
  assessment: "Explain-back recorded",
  artifact_produced: "Briefing produced",
  session_completed: "Session recorded",
  review_item: "Review recorded",
  plan_approved: "Path approved",
  replan: "Path revised",
};

/** The neutral form, for a kind this surface has no sentence for. */
export const EVIDENCE_KIND_FALLBACK = "Recorded event";

/** One event's kind, as a sentence — or the neutral form. */
export function evidenceKindLabel(kind: string): string {
  return EVIDENCE_KIND_LABEL[kind] ?? EVIDENCE_KIND_FALLBACK;
}

/**
 * The day an event was recorded, from its UTC timestamp — or `null`.
 *
 * THE DATE IS SLICED, NEVER PARSED. `new Date(ts).toLocaleDateString()`
 * re-projects a UTC instant into whichever zone the reader's browser is
 * in, so an event recorded at 00:30Z renders as the previous day for a
 * reader in the Americas. A ledger row that changes date depending on who
 * is reading it is not a record.
 *
 * `null`, RATHER THAN A PLACEHOLDER SENTENCE, WHEN THE TIMESTAMP CARRIES
 * NO DATE, and the shape is `run.lastUpdated`'s for a reason beyond
 * symmetry. The alternative — "date not reported" — needs `NOT_REPORTED`
 * from `./errors`, and importing one word from the failure dictionary
 * ships all 19 KB of it: measured on this branch, that single import cost
 * `/learn` 2,317 B and `/learn/progress` 2,033 B of first-load JavaScript,
 * because an object literal is one binding and a bundler cannot split it.
 * The contract makes `ProgressEvidence.ts` required and ISO-8601, so this
 * branch is defensive; the honest render for a date nothing supplies is no
 * date element at all, which is what `LedgerView` does with the `null`.
 */
export function recordedOn(ts: string): string | null {
  const day = /^\d{4}-\d{2}-\d{2}/.exec(ts)?.[0];
  return day === undefined ? null : `Recorded ${day}`;
}

/** Where the page came from: the size of the event page it was folded from. */
export function foldedFrom(count: number): string {
  if (count === 0) return "Folded from no recorded events.";
  return `Folded from ${count} recorded event${count === 1 ? "" : "s"}.`;
}

/**
 * How many assessment events a path carries.
 *
 * A COUNT OF EVENTS, NEVER A GRADE (the same rule `ProgressSchedule`
 * carries on the wire). Zero is not rendered through here at all — it is
 * `LEDGER.notObserved`, because "0 assessments recorded" reads as a score
 * of nothing and the absence of an observation is not a low result.
 */
export function assessmentCount(count: number): string {
  return `${count} assessment${count === 1 ? "" : "s"} recorded`;
}

/**
 * Session arithmetic with its label welded on (criterion 3).
 *
 * `label` is the backend's own `schedule_label`, which
 * `src/learning/progress_store.py::_SCHEDULE_LABEL_PATTERN` bounds to
 * `N of M sessions` or `N sessions recorded`. It passes through unedited —
 * it is arithmetic the ledger computed, not a sentence this surface
 * composed — and the word that makes it schedule progress rather than
 * knowledge is prefixed here so the two cannot be separated by a layout.
 */
export function scheduleFigure(label: string): string {
  return `${LEDGER.scheduleLabel} · ${label}`;
}

/**
 * The events this page is NOT showing, and why.
 *
 * An event with no `evidence_ref` cannot be rendered as a demonstrated
 * fact — that is criterion 1's whole content — but dropping it silently
 * would make the visible list look like the whole log. `null` when there
 * is nothing to say, so the footnote does not render at all.
 */
export function withheldEvidence(count: number): string | null {
  if (count === 0) return null;
  return (
    `${count} recorded event${count === 1 ? " is" : "s are"} not listed here: ` +
    `${count === 1 ? "it carries" : "they carry"} no evidence reference.`
  );
}
