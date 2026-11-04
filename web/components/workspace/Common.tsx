"use client";

import type { SourceStatus } from "@/lib/workspace/api";
import { displayDate } from "@/lib/workspace/api";
import { useSyntheticPreview } from "./PreviewContext";

/** One polite mutation result per live route; errors share this region. */
export function Message({ children }: { children: React.ReactNode }) {
  return (
    <p role="status" className="daily-muted">
      {children}
    </p>
  );
}

export function LoadingState({
  error,
  retry,
}: {
  error: string;
  retry: () => void;
}) {
  return error ? (
    <div className="workspace-alert error">
      <h1>Workspace unavailable</h1>
      <p>{error}</p>
      <p>No fictional items have been substituted.</p>
      <button className="daily-secondary" onClick={retry}>
        Retry connection
      </button>
    </div>
  ) : (
    <p className="daily-muted" aria-busy="true">
      Opening your local workspace…
    </p>
  );
}

export function ServiceNotice({ error }: { error: string }) {
  return error ? (
    <div className="workspace-alert error">
      <p>{error}</p>
      <p>
        The records below are the last loaded view. Unsaved edits are not
        durable server saves.
      </p>
    </div>
  ) : null;
}

export function sourceAvailable(source: SourceStatus) {
  return ["ok", "success", "not_modified", "partial"].includes(source.status);
}

export function Coverage({ sources, children }: { sources: SourceStatus[]; children?: React.ReactNode }) {
  const syntheticPreview = useSyntheticPreview();
  const good = sources.filter(sourceAvailable).length;
  const limited = sources.filter(
    (source) =>
      source.status === "partial" || source.receipt.truncated === true,
  ).length;
  return (
    <details className="daily-coverage" data-complete={good === sources.length && !limited}>
      <summary>
        <span className="daily-status-dot" aria-hidden="true" />
        {syntheticPreview ? "Sample source checks" : "Source checks"}: {good} of {sources.length} available
        <span>
          {good < sources.length
            ? "Unavailable checks"
            : limited
              ? `${limited} limited source windows`
              : syntheticPreview ? "Synthetic sample checks" : "Bounded metadata checks"}
        </span>
      </summary>
      {children}
      {syntheticPreview ? <p>These sample papers and source check results are synthetic. They do not represent live fetches or establish source coverage.</p> : <p>
        At most 25 items per check, with a seven-day candidate window. A partial
        check contains real metadata but does not establish full coverage of the
        requested window. A successful check can be empty. A failed check cannot
        establish that nothing changed.
      </p>}
      <ul>
        {sources.map((source) => (
          <li key={source.source_id}>
            <strong>{source.name}</strong>
            <span>
              {source.status.replaceAll("_", " ")} ·{" "}
              {syntheticPreview ? "Synthetic sample status" : source.last_success_at
                ? `last success ${displayDate(source.last_success_at)}`
                : source.status === "partial"
                  ? "Limited fetch committed; no complete-window success recorded"
                  : "No successful check recorded"}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function GenerationBoundary() {
  return (
    <div className="daily-generation">
      <span className="daily-eyebrow">Grounded analysis · later milestone</span>
      <h3>Follow the source first.</h3>
      <p>
        Grounded summaries and guided deep dives need a separately approved
        source scope, model and spending ceiling. Reading and your notes are
        available now.
      </p>
      <button className="daily-secondary" disabled>
        Generation awaiting approval
      </button>
    </div>
  );
}
