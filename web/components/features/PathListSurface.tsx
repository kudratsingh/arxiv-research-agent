"use client";

import { EmptyState } from "@/components/patterns/EmptyState";
import { PathUnavailable } from "@/components/patterns/PathView";
import { LEARN } from "@/lib/copy/learn";
import { useLearnPaths } from "@/lib/queries/learn";

import { PathList } from "./PathList";

export function PathListSurface() {
  const query = useLearnPaths();

  if (query.isPending) {
    return (
      <div
        aria-busy="true"
        className="mx-auto flex h-full w-full max-w-content items-center px-6 py-10 text-ui-sm text-ink-muted"
      >
        {LEARN.listLoading}
      </div>
    );
  }

  if (query.isError) {
    return <PathUnavailable onRetry={() => void query.refetch()} />;
  }

  return (
    <section className="mx-auto w-full max-w-content px-6 py-10">
      <header className="border-b border-border-strong pb-7">
        <p className="font-mono text-mono-xs uppercase tracking-wide text-signature-text">
          {LEARN.listEyebrow}
        </p>
        <h1 className="mt-3 max-w-measure font-report text-report-h1 text-ink">
          {LEARN.listHeading}
        </h1>
        <p className="mt-3 max-w-measure text-ui-base text-ink-muted">
          {LEARN.listBody}
        </p>
      </header>

      {query.data.paths.length === 0 ? (
        <EmptyState
          heading={LEARN.listEmptyHeading}
          headingLevel={2}
          body={LEARN.listEmptyBody}
          className="mt-6 px-0"
        />
      ) : (
        <div className="mt-6">
          <PathList paths={query.data.paths} />
        </div>
      )}
    </section>
  );
}
