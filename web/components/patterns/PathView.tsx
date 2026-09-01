import Link from "next/link";

import type {
  LearnEntry,
  LearnPathDetail,
  ProgressResourceObservation,
} from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";

import "@/components/primitives/primitives.css";
import "./path.css";

export interface PathViewProps {
  path: LearnPathDetail;
  /** Resource facts derived from recorded session events, or an empty list. */
  observations?: ProgressResourceObservation[];
}

function EntryCard({
  entry,
  observations,
  latestObservedAt,
}: {
  entry: LearnEntry;
  observations: ReadonlyMap<string, ProgressResourceObservation>;
  latestObservedAt: string | null;
}) {
  const observation = observations.get(entry.resource_id);
  const observed = observation !== undefined;
  const current =
    observation !== undefined && observation.last_observed_at === latestObservedAt;

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
            <h3 className="mt-2 font-report text-report-h2 text-ink">
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

export function PathView({ path, observations = [] }: PathViewProps) {
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
          />
        ))}
      </ol>

      <footer className="mt-8 border-t border-border-subtle pt-4 text-ui-xs text-ink-muted">
        <p>{LEARN.linkOutOnly}</p>
      </footer>
    </article>
  );
}
