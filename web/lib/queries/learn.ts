"use client";

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

export function useLearnPaths(): UseQueryResult<LearnPathList, Error> {
  return useQuery({
    queryKey: queryKeys.learnPaths.list(),
    queryFn: ({ signal }) => listLearnPaths({ signal }),
  });
}

export function useLearnPath(
  pathId: string | null
): UseQueryResult<LearnPathDetail, Error> {
  return useQuery({
    queryKey: queryKeys.learnPaths.detail(pathId ?? ""),
    queryFn: ({ signal }) => getLearnPath(pathId as string, { signal }),
    enabled: pathId !== null,
  });
}

export function useLearnerProgress(): UseQueryResult<
  LearnerProgressSummary,
  Error
> {
  return useQuery({
    queryKey: queryKeys.learnProgress.summary(),
    queryFn: ({ signal }) => getLearnerProgress({ signal }),
  });
}
