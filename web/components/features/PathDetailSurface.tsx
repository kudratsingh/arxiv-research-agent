"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import {
  PathUnavailable,
  PathView,
  type PathStartRefusal,
} from "@/components/patterns/PathView";
import {
  ApiError,
  createLearnSession,
  type LearnEntry,
  type LearnerProgressSummary,
  type ProgressResourceObservation,
  type SessionCreateRequest,
} from "@/lib/api";
import { LEARN, describeSessionStart } from "@/lib/copy/learn";
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

/**
 * The contract's own bounds on `available_minutes`
 * (`src/api/sessions.py::SessionCreateRequest`, `ge=5, le=180`).
 *
 * Declared rather than inlined so the reason the field is sometimes omitted
 * is readable beside the numbers that cause it.
 */
export const SESSION_MINUTES_MIN = 5;
export const SESSION_MINUTES_MAX = 180;

/**
 * The create body for one path entry.
 *
 * THE TIME BUDGET IS THE PATH'S OWN, AND IT IS SENT ONLY WHEN THE CONTRACT
 * ACCEPTS IT. `est_minutes` is what the published manifest declares for this
 * entry (`LearnEntry.est_minutes`), which is the budget for the one session a
 * start opens — not `est_minutes_total`, which is the whole sequence. When it
 * falls outside the endpoint's declared 5–180 range the field is OMITTED
 * rather than clamped: a clamped value is a number this surface invented, and
 * the endpoint already has an honest answer for the absence — the learner's
 * own `time_budget_min_per_day` (`src/api/sessions.py::create_session`).
 * Sending an out-of-range value would 422, which is a refusal about our
 * request rather than anything the reader could act on.
 */
export function sessionCreateRequest(
  pathId: string,
  entry: LearnEntry
): SessionCreateRequest {
  const minutes = entry.est_minutes;
  const usable =
    Number.isInteger(minutes) &&
    minutes >= SESSION_MINUTES_MIN &&
    minutes <= SESSION_MINUTES_MAX;
  return usable
    ? { path_id: pathId, resource_id: entry.resource_id, available_minutes: minutes }
    : { path_id: pathId, resource_id: entry.resource_id };
}

export function PathDetailSurface({ pathId }: PathDetailSurfaceProps) {
  const path = useLearnPath(pathId);
  const progress = useLearnerProgress();
  const router = useRouter();

  const [starting, setStarting] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<PathStartRefusal | null>(null);
  /**
   * The duplicate-submit guard, and it is a ref rather than state on purpose.
   *
   * `POST /learn/sessions` starts a graph run and carries no idempotency key,
   * for exactly the reason `POST /research` does not — so a second one is a
   * second session that cannot be taken back. A `useState` flag is not a
   * guard: React batches the update, so two clicks inside one frame both read
   * the pre-update value and both issue the write. A ref is written
   * synchronously, before the `await`, which is the discipline
   * `SessionDetailSurface`'s `turnInFlight` already follows for the turn.
   */
  const startInFlight = useRef(false);

  const startSession = useCallback(
    async (entry: LearnEntry) => {
      if (startInFlight.current) return;
      startInFlight.current = true;
      setRefusal(null);
      setStarting(entry.resource_id);
      try {
        const accepted = await createLearnSession(
          sessionCreateRequest(pathId, entry)
        );
        // No state reset on the success path, deliberately. The route is
        // leaving; re-arming the button under a page that is unmounting would
        // open a window in which one more click buys one more session.
        router.push(`/learn/sessions/${encodeURIComponent(accepted.session_id)}`);
      } catch (error) {
        startInFlight.current = false;
        setStarting(null);
        setRefusal({
          resourceId: entry.resource_id,
          ...describeSessionStart(
            error instanceof ApiError ? error.failure : null
          ),
        });
      }
    },
    [pathId, router]
  );

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
      onStartSession={(entry) => void startSession(entry)}
      startingResourceId={starting}
      startRefusal={refusal}
    />
  );
}
