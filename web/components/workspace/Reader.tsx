"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { lazy, Suspense, useState } from "react";
import { normalizeReaderReturnTo, type WorkItem } from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { LoadingState } from "./Common";

const ReaderContent = lazy(() => import("./ReaderContent"));
const ReaderReviewContext = lazy(() => import("./ReaderReviewContext"));

export function LiveReader({ id }: { id: string }) {
  const { state, setState, error, reload } = useWorkspace();
  const params = useSearchParams();
  const requestedVersion = params.get("version");
  const requestedEntry = params.get("entry");
  const returnTo = normalizeReaderReturnTo(params.get("return_to"));
  const [review, setReview] = useState<{ returnTo: string; works: WorkItem[] } | null>(null);
  const reviewWorks = review?.returnTo === returnTo ? review.works : [];
  const reviewContext = returnTo.startsWith("/workspace/review")
    ? <Suspense fallback={null}><ReaderReviewContext returnTo={returnTo} onReady={setReview} /></Suspense> : null;

  const item = state?.works.find((work) => work.work_id === id);
  return <>{reviewContext}{!state
    ? <LoadingState error={error} retry={() => void reload()} />
    : !item ? <div className="daily-empty" data-reader-unavailable="">
        <h1>This source is not in the loaded workspace.</h1>
        <p>
          No fictional source was substituted. Save the source URL in Library or
          return to Radar.
        </p>
        <Link href="/workspace/library" className="daily-link" prefetch={false} scroll={false}>
          Open Library →
        </Link>
      </div>
    : <Suspense fallback={<p className="daily-muted" aria-busy="true">Opening the retained source reader…</p>}><ReaderContent
      key={`${state.principal_key_id}:${item.work_id}:${requestedVersion ?? ""}:${requestedEntry ?? ""}`}
      item={item}
      state={state}
      setState={setState}
      error={error}
      requestedVersion={requestedVersion}
      requestedEntry={requestedEntry}
      returnTo={returnTo}
      reviewWorks={reviewWorks}
    /></Suspense>}</>;
}
