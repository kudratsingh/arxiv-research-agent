"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { lazy, Suspense, useEffect, useState } from "react";
import { normalizeReaderReturnTo, type WorkItem } from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { readerModule, type ReaderContentComponent } from "@/lib/workspace/readerModule";
import { LoadingState } from "./Common";

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
  const hasItem = Boolean(item);
  const contentKey = state ? `${state.principal_key_id}:${id}:${requestedVersion ?? ""}:${requestedEntry ?? ""}` : "";
  const [Content, setContent] = useState<ReaderContentComponent | null>(() => readerModule.peek());
  const [contentError, setContentError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  useEffect(() => {
    if (!hasItem || Content) return;
    let active = true;
    readerModule.load().then(component => {
      if (active) { setContent(() => component); setContentError(false); }
    }).catch(() => { if (active) setContentError(true); });
    return () => { active = false; };
  }, [hasItem, Content, loadAttempt, contentKey]);
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
    : contentError ? <section className="workspace-alert error" data-reader-unavailable="">
        <h1>This source view could not be opened.</h1>
        <p>Your source and saved notes are unchanged. Retry to open this exact source version.</p>
        <button type="button" className="daily-secondary" onClick={() => { setContentError(false); setLoadAttempt(value => value + 1); }}>Retry source view</button>
      </section>
    : !Content ? <p className="daily-muted" aria-busy="true">Opening the retained source reader…</p>
    : <Content
      key={contentKey}
      item={item}
      state={state}
      setState={setState}
      error={error}
      requestedVersion={requestedVersion}
      requestedEntry={requestedEntry}
      returnTo={returnTo}
      reviewWorks={reviewWorks}
    />}</>;
}
