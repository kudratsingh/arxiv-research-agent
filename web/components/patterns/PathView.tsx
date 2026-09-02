import Link from "next/link";
import { useId } from "react";

import { Button } from "@/components/primitives/Button";
import type {
  LearnEntry,
  LearnPathDetail,
  ProgressResourceObservation,
} from "@/lib/api";
import { LEARN, type SessionStartRefusal } from "@/lib/copy/learn";

import "@/components/primitives/primitives.css";
import "./path.css";

/** One entry's refusal, as the feature hands it down. */
export interface PathStartRefusal extends SessionStartRefusal {
  /** Which entry was refused. No other entry on the path is affected. */
  resourceId: string;
}

export interface PathViewProps {
  path: LearnPathDetail;
  /** Resource facts derived from recorded session events, or an empty list. */
  observations?: ProgressResourceObservation[];
  /**
   * Start one guided session on this entry.
   *
   * Omitted, no start affordance renders at all — this pattern never fetches
   * and never offers a control for a write it cannot issue (04 §5.1). The
   * feature that owns `createLearnSession` passes it; a story passes a spy.
   */
  onStartSession?: (entry: LearnEntry) => void;
  /** The entry whose start POST is outstanding, or `null`. */
  startingResourceId?: string | null;
  /** The refusal to render, or `null`. */
  startRefusal?: PathStartRefusal | null;
}

function StartAction({
  entry,
  describedBy,
  onStartSession,
  starting,
  otherStarting,
  refusal,
}: {
  entry: LearnEntry;
  describedBy: string;
  onStartSession: (entry: LearnEntry) => void;
  starting: boolean;
  otherStarting: boolean;
  refusal: PathStartRefusal | null;
}) {
  return (
    <div className="mt-5 border-t border-border-subtle pt-4">
      <Button
        variant="primary"
        // `busy`, not `disabled`: the control stays focusable and announced
        // while it refuses a second click, which is the argument
        // `primitives/Button.tsx` makes and the session composer already
        // follows. It is a refusal, not a progress indicator — no bar, no
        // spinner and no claim about how far the service has got, because a
        // POST that has not answered has produced no fact to report.
        busy={starting}
        // A start on ANOTHER entry is outstanding. Unavailable, but nothing
        // on THIS control is working, so `aria-busy` would announce work that
        // is not happening: `aria-disabled` is the honest half of the pair,
        // and `Button` honours a caller's value with the same click guard.
        aria-disabled={otherStarting || undefined}
        aria-describedby={describedBy}
        data-start-session={entry.resource_id}
        onClick={() => onStartSession(entry)}
      >
        {starting ? LEARN.startingSession : LEARN.startSession}
      </Button>

      {refusal ? (
        <div
          role="alert"
          data-start-refusal={entry.resource_id}
          className="mt-4 border-l-2 border-critical bg-sunken px-4 py-3"
        >
          <p className="text-ui-sm font-semibold text-ink">
            {LEARN.startRefusedHeading}
          </p>
          <p className="mt-1 max-w-measure text-ui-sm text-ink-muted">
            {refusal.message}
          </p>
          {refusal.detail === null ? null : (
            <dl className="mt-2">
              <dt className="font-mono text-mono-xs uppercase text-ink-muted">
                {LEARN.startRefusedDetail}
              </dt>
              {/* RC-16: the service's own word, verbatim and unedited. */}
              <dd className="font-mono text-mono-xs text-ink">{refusal.detail}</dd>
            </dl>
          )}
        </div>
      ) : null}
    </div>
  );
}

function EntryCard({
  entry,
  observations,
  latestObservedAt,
  onStartSession,
  startingResourceId,
  startRefusal,
}: {
  entry: LearnEntry;
  observations: ReadonlyMap<string, ProgressResourceObservation>;
  latestObservedAt: string | null;
  onStartSession?: (entry: LearnEntry) => void;
  startingResourceId: string | null;
  startRefusal: PathStartRefusal | null;
}) {
  const observation = observations.get(entry.resource_id);
  const observed = observation !== undefined;
  const current =
    observation !== undefined && observation.last_observed_at === latestObservedAt;
  const titleId = useId();
  const refusal =
    startRefusal !== null && startRefusal.resourceId === entry.resource_id
      ? startRefusal
      : null;

  return (
    <li
      data-path-entry=""
      data-observation={observed ? "observed" : "not-observed"}
      className="path-spine__entry relative grid grid-cols-[2.5rem_minmax(0,1fr)] gap-4 pb-8 last:pb-0"
    >
      <div aria-hidden="true" className="path-spine__marker font-mono">
        <span>{entry.position}</span>
      </div>
      <article className="min-w-0 border border-border-subtle bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-mono-xs uppercase text-ink-muted">
              {current
                ? LEARN.nextObserved
                : observed
                  ? LEARN.observed
                  : LEARN.notObserved}
            </p>
            <h3 id={titleId} className="mt-2 font-report text-report-h2 text-ink">
              {entry.title}
            </h3>
            <p className="mt-1 text-ui-xs text-ink-muted">{entry.attribution}</p>
          </div>
          <span className="font-mono text-mono-xs text-ink-muted">
            {entry.est_minutes} {LEARN.minutes}
          </span>
        </div>

        <p className="mt-4 max-w-measure text-ui-sm text-ink-muted">
          {entry.rationale}
        </p>

        <div className="mt-5 flex flex-wrap gap-3">
          <a
            href={entry.canonical_url}
            target="_blank"
            rel="noreferrer"
            className="ew-focusable ew-target inline-flex items-center border-b border-primary text-ui-sm font-medium text-primary hover:text-primary-strong"
          >
            {LEARN.openPaper}
          </a>
          <span className="inline-flex items-center text-ui-sm text-ink-muted">
            {entry.briefing_markdown
              ? LEARN.briefingAvailable
              : LEARN.briefingUnavailable}
          </span>
        </div>

        {entry.vocabulary.length > 0 ? (
          <dl className="mt-5 border-t border-border-subtle pt-4">
            <dt className="font-mono text-mono-xs uppercase text-ink-muted">
              {LEARN.vocabulary}
            </dt>
            <dd className="mt-2 text-ui-sm text-ink">
              {entry.vocabulary.join(", ")}
            </dd>
          </dl>
        ) : null}

        {onStartSession === undefined ? null : (
          <StartAction
            entry={entry}
            describedBy={titleId}
            onStartSession={onStartSession}
            starting={startingResourceId === entry.resource_id}
            otherStarting={
              startingResourceId !== null &&
              startingResourceId !== entry.resource_id
            }
            refusal={refusal}
          />
        )}
      </article>
    </li>
  );
}

export interface PathUnavailableProps {
  onRetry?: () => void;
}

export function PathUnavailable({ onRetry }: PathUnavailableProps) {
  return (
    <section
      data-path-unavailable=""
      className="mx-auto flex h-full w-full max-w-content flex-col justify-center gap-4 px-6 py-10"
    >
      <h1 className="font-report text-report-h1 text-ink">
        {LEARN.pathUnavailableHeading}
      </h1>
      <p className="max-w-measure text-ui-base text-ink-muted">
        {LEARN.pathUnavailableBody}
      </p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="ew-focusable ew-target inline-flex w-fit items-center border border-border-strong px-4 text-ui-sm font-medium text-ink hover:bg-sunken"
        >
          {LEARN.retry}
        </button>
      ) : null}
    </section>
  );
}

export function PathView({
  path,
  observations = [],
  onStartSession,
  startingResourceId = null,
  startRefusal = null,
}: PathViewProps) {
  const pathObservations = observations.filter(
    (observation) => observation.path_id === path.path_id
  );
  const byResource = new Map(
    pathObservations.map((observation) => [observation.resource_id, observation])
  );
  const latestObservedAt = pathObservations.reduce<string | null>(
    (latest, observation) =>
      latest === null || observation.last_observed_at > latest
        ? observation.last_observed_at
        : latest,
    null
  );

  return (
    <article data-path-view="" className="mx-auto w-full max-w-content px-6 py-10">
      <Link
        href="/learn"
        className="ew-focusable ew-target inline-flex items-center text-ui-sm text-primary hover:text-primary-strong"
      >
        {LEARN.backToPaths}
      </Link>

      <header className="mt-6 border-b border-border-strong pb-7">
        <p className="font-mono text-mono-xs uppercase tracking-wide text-signature-text">
          {LEARN.pathLabel}
        </p>
        <h1 className="mt-3 max-w-measure font-report text-report-h1 text-ink">
          {path.title}
        </h1>
        <p className="mt-3 max-w-measure text-ui-base text-ink-muted">
          {path.goal}
        </p>
        <dl className="mt-5 flex flex-wrap gap-x-5 gap-y-2 font-mono text-mono-xs text-ink-muted">
          <div className="flex gap-1">
            <dd>{path.entry_count}</dd>
            <dt>{LEARN.papers}</dt>
          </div>
          <div className="flex gap-1">
            <dd>{path.est_minutes_total}</dd>
            <dt>{LEARN.minutes}</dt>
          </div>
          <div className="flex gap-1">
            <dt>{LEARN.updated}</dt>
            <dd>{path.updated_at}</dd>
          </div>
        </dl>
      </header>

      {path.fixture ? (
        <aside className="mt-6 border-l-2 border-review bg-review-surface px-4 py-3">
          <p className="font-mono text-mono-xs uppercase text-review-text">
            {LEARN.fixtureLabel}
          </p>
          <p className="mt-1 text-ui-sm text-ink">{LEARN.fixtureShort}</p>
        </aside>
      ) : null}

      <div className="mt-7 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-ui-lg font-semibold text-ink">{LEARN.entriesLabel}</h2>
        <p className="text-ui-xs text-ink-muted">
          {pathObservations.length === 0 ? LEARN.noProgress : LEARN.progressSource}
        </p>
      </div>

      <ol aria-label={LEARN.entriesLabel} className="path-spine mt-6">
        {path.entries.map((entry) => (
          <EntryCard
            key={entry.resource_id}
            entry={entry}
            observations={byResource}
            latestObservedAt={latestObservedAt}
            onStartSession={onStartSession}
            startingResourceId={startingResourceId}
            startRefusal={startRefusal}
          />
        ))}
      </ol>

      <footer className="mt-8 border-t border-border-subtle pt-4 text-ui-xs text-ink-muted">
        <p>{LEARN.linkOutOnly}</p>
      </footer>
    </article>
  );
}
