"use client";

// The `(learn)` read hooks — TanStack Query over `lib/api`, and nothing else.
//
// Every learn surface reads through this module rather than calling the client
// directly, so the cache keys have one definition (`./keys`) and a refetch
// after a write invalidates the same key the read used.
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  getLearnPath,
  getLearnerProgress,
  listLearnPaths,
  type LearnPathDetail,
  type LearnPathList,
  type LearnerProgressSummary,
} from "@/lib/api";

import { queryKeys } from "./keys";

/** Every published path. */
export function useLearnPaths(): UseQueryResult<LearnPathList, Error> {
  return useQuery({
    queryKey: queryKeys.learnPaths.list(),
    queryFn: ({ signal }) => listLearnPaths({ signal }),
  });
}

/**
 * One path's detail. Disabled while `pathId` is null, so a surface waiting on
 * the id it needs issues no request rather than one for the empty string.
 */
export function useLearnPath(
  pathId: string | null
): UseQueryResult<LearnPathDetail, Error> {
  return useQuery({
    queryKey: queryKeys.learnPaths.detail(pathId ?? ""),
    queryFn: ({ signal }) => getLearnPath(pathId as string, { signal }),
    enabled: pathId !== null,
  });
}

/**
 * The learner's recorded activity. The learner-profile flag is off by default,
 * so a failure here is the ordinary case and every caller states it as one.
 */
export function useLearnerProgress(): UseQueryResult<
  LearnerProgressSummary,
  Error
> {
  return useQuery({
    queryKey: queryKeys.learnProgress.summary(),
    queryFn: ({ signal }) => getLearnerProgress({ signal }),
  });
}
