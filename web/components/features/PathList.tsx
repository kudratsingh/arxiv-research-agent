import Link from "next/link";

import type { LearnPathSummary } from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";

import "@/components/primitives/primitives.css";

export interface PathListProps {
  paths: LearnPathSummary[];
}

export function PathList({ paths }: PathListProps) {
  return (
    <ul className="divide-y divide-border-subtle border-y border-border-subtle">
      {paths.map((path) => (
        <li key={path.path_id} className="py-6">
          <article className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="font-report text-report-h2 text-ink">
                  {path.title}
                </h2>
                {path.fixture ? (
                  <span className="border border-review px-2 py-1 font-mono text-mono-xs uppercase text-review-text">
                    {LEARN.fixtureLabel}
                  </span>
                ) : null}
              </div>
              <p className="mt-2 max-w-measure text-ui-sm text-ink-muted">
                {path.goal}
              </p>
              <dl className="mt-4 flex flex-wrap gap-x-5 gap-y-2 font-mono text-mono-xs text-ink-muted">
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
            </div>
            <Link
              href={`/learn/paths/${encodeURIComponent(path.path_id)}`}
              className="ew-focusable ew-target inline-flex items-center justify-center border border-border-strong px-4 text-ui-sm font-medium text-ink hover:bg-sunken"
            >
              {LEARN.openPath}
            </Link>
          </article>
        </li>
      ))}
    </ul>
  );
}
