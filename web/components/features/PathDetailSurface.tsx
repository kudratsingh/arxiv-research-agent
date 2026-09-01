"use client";

import { PathUnavailable, PathView } from "@/components/patterns/PathView";
import type {
  LearnerProgressSummary,
  ProgressResourceObservation,
} from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";
import { useLearnerProgress, useLearnPath } from "@/lib/queries/learn";

export interface PathDetailSurfaceProps {
  pathId: string;
}

export function resourceObservationsFromEvents(
  progress: LearnerProgressSummary | undefined,
  pathId: string
): ProgressResourceObservation[] {
  return (
    progress?.resource_observations.filter(
      (observation) => observation.path_id === pathId
    ) ?? []
  );
}

export function PathDetailSurface({ pathId }: PathDetailSurfaceProps) {
  const path = useLearnPath(pathId);
  const progress = useLearnerProgress();

  if (path.isPending) {
    return (
      <div
        aria-busy="true"
        className="mx-auto flex h-full w-full max-w-content items-center px-6 py-10 text-ui-sm text-ink-muted"
      >
        {LEARN.pathLoading}
      </div>
    );
  }

  if (path.isError) {
    return <PathUnavailable onRetry={() => void path.refetch()} />;
  }

  return (
    <PathView
      path={path.data}
      observations={resourceObservationsFromEvents(progress.data, pathId)}
    />
  );
}
