/**
 * LedgerView — the learner's record, and nothing it cannot prove (WO-W14).
 *
 * `00-VISION.md` §5.4 describes the surface: skills appear with the
 * evidence that demonstrated them — which check, which date, which
 * artifact — what was never assessed is marked unobserved rather than
 * guessed at, and the record is built on the evidence store's worldview.
 * `01-LEARNING-AGENT.md` §4.4 states the rule that makes it testable:
 * everything a surface says about progress is a *view* over the append-only
 * event log, so **there is no displayed claim without an event behind it**.
 * That is the web tier's own state-machine honesty rule ("the machine never
 * invents a stage") pointed at learning, and it is what this component is
 * shaped around.
 *
 * HOW THAT RULE IS MADE STRUCTURAL RATHER THAN REMEMBERED. Nothing is
 * rendered from the summary directly. `evidenceRows` and `scheduleRows` are
 * pure functions that turn the wire object into rows whose TYPE cannot
 * express a claim with no backing: `LedgerEvidenceRow.evidenceRef` is a
 * non-nullable string and `eventIds` is non-empty by construction, because
 * both builders drop anything that would violate it. The component renders
 * exactly the rows they return and stamps the backing ids onto the DOM as
 * `data-event-ids`, so `web/tests/patterns/LedgerView.test.tsx` can assert
 * the property over the rendered output rather than over an intention.
 *
 * An event the builder drops is COUNTED, never silently swallowed:
 * `withheldCount` feeds the footnote, because a filtered list presented as
 * the whole log would be its own dishonesty.
 *
 * A PATTERN, SO IT NEVER FETCHES (04-ARCHITECTURE.md §5.1). The summary
 * arrives as a prop; `components/features/LedgerSurface.tsx` is the half
 * that reads `/api/learn/progress` through the query layer. Every state
 * this file can be in is therefore reachable from a story with no network.
 *
 * NO EXPORT CONTROL, DELIBERATELY. The Ledger's export is real in the
 * vision (00 §5.4) and is not scheduled in Phase W, so there is no button,
 * no menu entry and no "coming soon" here — an affordance that cannot do
 * what it offers is the exact failure this work order's criterion 4 names.
 */

import { EmptyState } from "@/components/patterns/EmptyState";
import type {
  LearnerProgressSummary,
  ProgressEvidence,
  ProgressSchedule,
} from "@/lib/api";
import {
  LEDGER,
  assessmentCount,
  evidenceKindLabel,
  foldedFrom,
  recordedOn,
  scheduleFigure,
  withheldEvidence,
} from "@/lib/copy/ledger";

import "@/components/primitives/primitives.css";

/**
 * One rendered evidence row.
 *
 * `evidenceRef` is `string`, not `string | null`, and that is the whole
 * point of the type: the wire allows null (`ProgressEvidence.evidence_ref`
 * is nullable for every kind except `assessment`, which the store refuses
 * to write without one), and a row that reached the DOM without one would
 * be a rendered claim with nothing behind it.
 */
export interface LedgerEvidenceRow {
  eventId: string;
  kind: string;
  /** Never null, never blank. */
  evidenceRef: string;
  pathId: string | null;
  ts: string;
  /** The source events this row is made of. Never empty. */
  eventIds: readonly string[];
}

/** One rendered schedule row: session arithmetic for one path. */
export interface LedgerScheduleRow {
  pathId: string;
  /** The backend's own `schedule_label`, passed through unedited. */
  label: string;
  assessmentsRecorded: number;
  /** The source events this row is made of. Never empty. */
  eventIds: readonly string[];
}

/** Every event the summary carries, assessments and artifacts alike. */
function sourceEvents(summary: LearnerProgressSummary): ProgressEvidence[] {
  return [...summary.assessments, ...summary.artifacts];
}

/** An `evidence_ref` that actually points at something. */
function hasEvidence(event: ProgressEvidence): event is ProgressEvidence & {
  evidence_ref: string;
} {
  return typeof event.evidence_ref === "string" && event.evidence_ref.trim() !== "";
}

/**
 * The evidence log, newest first.
 *
 * Sorted by timestamp descending and then by `event_id`, so the order is
 * total: two events recorded in the same second must still render in a
 * stable order or a story's assertion becomes a coin flip.
 */
export function evidenceRows(summary: LearnerProgressSummary): LedgerEvidenceRow[] {
  return sourceEvents(summary)
    .filter(hasEvidence)
    .map((event) => ({
      eventId: event.event_id,
      kind: event.kind,
      evidenceRef: event.evidence_ref,
      pathId: event.path_id,
      ts: event.ts,
      eventIds: [event.event_id],
    }))
    .sort((left, right) =>
      left.ts === right.ts
        ? left.eventId.localeCompare(right.eventId)
        : right.ts.localeCompare(left.ts),
    );
}

/** Events the log is not showing, because they carry no evidence reference. */
export function withheldCount(summary: LearnerProgressSummary): number {
  return sourceEvents(summary).filter((event) => !hasEvidence(event)).length;
}

/**
 * Schedule rows, each carrying the events its arithmetic is made of.
 *
 * A path appears in `schedule_progress` because events named it, so the
 * backing set is the `session_completed` ids the fold already attached plus
 * the assessment and artifact events recorded against the same path. A row
 * with an empty union is dropped: the fold cannot produce one, and if it
 * ever did it would be a path claiming a schedule with no session behind it.
 */
export function scheduleRows(summary: LearnerProgressSummary): LedgerScheduleRow[] {
  const events = sourceEvents(summary);
  return summary.schedule_progress
    .map((entry: ProgressSchedule) => ({
      pathId: entry.path_id,
      label: entry.schedule_label,
      assessmentsRecorded: entry.assessments_recorded,
      eventIds: [
        ...entry.event_ids,
        ...events
          .filter((event) => event.path_id === entry.path_id)
          .map((event) => event.event_id),
      ],
    }))
    .filter((row) => row.eventIds.length > 0);
}

export interface LedgerUnavailableProps {
  onRetry?: () => void;
}

/** The backend said no, or the flag is off. Same shape as `PathUnavailable`. */
export function LedgerUnavailable({ onRetry }: LedgerUnavailableProps) {
  return (
    <section
      data-ledger-unavailable=""
      className="mx-auto flex h-full w-full max-w-content flex-col justify-center gap-4 px-6 py-10"
    >
      <h1 className="font-report text-report-h1 text-ink">
        {LEDGER.unavailableHeading}
      </h1>
      <p className="max-w-measure text-ui-base text-ink-muted">
        {LEDGER.unavailableBody}
      </p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="ew-focusable ew-target inline-flex w-fit items-center border border-border-strong px-4 text-ui-sm font-medium text-ink hover:bg-sunken"
        >
          {LEDGER.retry}
        </button>
      ) : null}
    </section>
  );
}

function EvidenceRow({ row }: { row: LedgerEvidenceRow }) {
  const recorded = recordedOn(row.ts);
  return (
    <li
      data-ledger-row=""
      data-event-ids={row.eventIds.join(" ")}
      data-evidence-ref={row.evidenceRef}
      className="border border-border-subtle bg-surface p-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="text-ui-base font-medium text-ink">
          {evidenceKindLabel(row.kind)}
        </p>
        {recorded === null ? null : (
          <p className="font-mono text-mono-xs text-ink-muted">{recorded}</p>
        )}
      </div>
      <dl className="mt-4 grid gap-2 text-ui-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
        {row.pathId === null ? null : (
          <>
            <dt className="font-mono text-mono-xs uppercase text-ink-muted">
              {LEDGER.pathLabel}
            </dt>
            <dd className="min-w-0 break-words text-ink">{row.pathId}</dd>
          </>
        )}
        <dt className="font-mono text-mono-xs uppercase text-ink-muted">
          {LEDGER.evidenceRefLabel}
        </dt>
        <dd className="min-w-0 break-words font-mono text-mono-xs text-ink">
          {row.evidenceRef}
        </dd>
      </dl>
    </li>
  );
}

function ScheduleRow({ row }: { row: LedgerScheduleRow }) {
  const observed = row.assessmentsRecorded > 0;
  return (
    <li
      data-ledger-schedule-row=""
      data-event-ids={row.eventIds.join(" ")}
      data-observation={observed ? "observed" : "not-observed"}
      className="border border-border-subtle bg-surface p-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="font-mono text-mono-xs text-ink-muted">{row.pathId}</p>
        <p className="font-mono text-mono-xs uppercase text-ink-muted">
          {observed ? LEDGER.observed : LEDGER.notObserved}
        </p>
      </div>
      {/*
        Criterion 3: the label and the arithmetic are ONE string in ONE
        element, so no layout change can leave "3 of 3 sessions" standing on
        its own where it would read as a knowledge claim.
      */}
      <p
        data-ledger-schedule-figure=""
        className="mt-2 text-ui-base font-medium text-ink"
      >
        {scheduleFigure(row.label)}
      </p>
      {observed ? (
        <p className="mt-3 text-ui-sm text-ink-muted">
          {assessmentCount(row.assessmentsRecorded)}
        </p>
      ) : (
        <p className="mt-1 max-w-measure text-ui-xs text-ink-muted">
          {LEDGER.notObservedBody}
        </p>
      )}
    </li>
  );
}

export interface LedgerViewProps {
  summary: LearnerProgressSummary;
}

export function LedgerView({ summary }: LedgerViewProps) {
  const evidence = evidenceRows(summary);
  const schedule = scheduleRows(summary);
  const withheld = withheldEvidence(withheldCount(summary));
  const empty = evidence.length === 0 && schedule.length === 0;

  return (
    <article data-ledger="" className="mx-auto w-full max-w-content px-6 py-10">
      <header className="border-b border-border-strong pb-7">
        <p className="font-mono text-mono-xs uppercase tracking-wide text-signature-text">
          {LEDGER.eyebrow}
        </p>
        <h1 className="mt-3 font-report text-report-h1 text-ink">{LEDGER.heading}</h1>
        <p className="mt-3 max-w-measure text-ui-base text-ink-muted">{LEDGER.lead}</p>
        <p className="mt-3 font-mono text-mono-xs text-ink-muted">
          {foldedFrom(summary.event_count)}
        </p>
      </header>

      {empty ? (
        <EmptyState
          heading={LEDGER.emptyHeading}
          headingLevel={2}
          body={LEDGER.emptyBody}
          className="mt-7 border border-border-subtle px-5 py-6"
        />
      ) : null}

      {evidence.length === 0 ? null : (
        <section data-ledger-evidence="" className="mt-8">
          <h2 className="text-ui-lg font-semibold text-ink">
            {LEDGER.evidenceHeading}
          </h2>
          <p className="mt-2 max-w-measure text-ui-sm text-ink-muted">
            {LEDGER.evidenceIntro}
          </p>
          <ol aria-label={LEDGER.evidenceHeading} className="mt-5 grid gap-3">
            {evidence.map((row) => (
              <EvidenceRow key={row.eventId} row={row} />
            ))}
          </ol>
        </section>
      )}

      {schedule.length === 0 ? null : (
        <section data-ledger-schedule="" className="mt-8">
          <h2 className="text-ui-lg font-semibold text-ink">
            {LEDGER.scheduleHeading}
          </h2>
          <p className="mt-2 max-w-measure text-ui-sm text-ink-muted">
            {LEDGER.scheduleIntro}
          </p>
          <ol aria-label={LEDGER.scheduleHeading} className="mt-5 grid gap-3">
            {schedule.map((row) => (
              <ScheduleRow key={row.pathId} row={row} />
            ))}
          </ol>
        </section>
      )}

      {/*
        The footnote sits at page level rather than inside the evidence
        section on purpose: when EVERY event lacks a reference the log is
        empty and the count is exactly what a reader most needs to see.
      */}
      {withheld === null ? null : (
        <footer
          data-ledger-withheld=""
          className="mt-8 border-t border-border-subtle pt-4 text-ui-xs text-ink-muted"
        >
          <p>{withheld}</p>
        </footer>
      )}
    </article>
  );
}
