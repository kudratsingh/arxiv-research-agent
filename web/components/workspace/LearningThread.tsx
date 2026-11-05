"use client";
import { loadContextEditors } from "./contextModules";

import Link from "next/link";
import { lazy, Suspense, useEffect, useState } from "react";
import { contextRequest, errorMessage, readerHref, type LearningThread } from "@/lib/workspace/api";
import { contextHref, useProductContext } from "@/lib/workspace/productContext";
import { useContextIndex } from "@/lib/workspace/useContextIndex";
const ThreadEditor = lazy(() => loadContextEditors().then(module => ({ default: module.ThreadEditor })));
export function LiveLearningThread({ id }: { id: string }) {
  return <ThreadScreen key={id} id={id} />;
}
function ThreadScreen({ id }: { id: string }) {
  const { index } = useContextIndex(), context = useProductContext();
  const [thread, setThread] = useState<LearningThread | null>(null), [error, setError] = useState("");
  const [edit, setEdit] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    contextRequest<LearningThread>(`/threads/${id}`, undefined, controller.signal).then(value => { if (!controller.signal.aborted) { setThread(value); setError(""); } }).catch(failure => { if (!controller.signal.aborted) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [id, retry]);
  const origin = thread?.data.origin;
  const originContext = origin ? { mode: origin.mode, project: origin.project_id, thread: origin.thread_id, explicit: true, invalid: false } : context;
  const returnHref = thread && origin ? contextHref(thread.source
    ? readerHref(thread.source, thread.source.version_id, thread.source.anchor, undefined, origin.return_to)
    : origin.return_to, originContext) : "";
  return <div className="ws-learning-thread"><h1>{thread?.data.title ?? "Learning thread"}</h1>
    {!thread && !error && <p aria-busy="true">Loading the saved learning context…</p>}
    {error && <section data-workspace-unavailable=""><h2>This learning thread is unavailable.</h2><p>{error}</p><button type="button" onClick={() => setRetry(value => value + 1)}>Retry thread</button></section>}
    {thread && <><p>Declared learning goal · {thread.data.status} · revision {thread.revision}</p><h2>What you want to understand</h2><p>{thread.data.goal}</p><h3>Prerequisite</h3><p>{thread.data.prerequisite || "No prerequisite declared."}</p>
      <p className="daily-muted">This is a manual learning thread. No explanation was generated and reading does not establish mastery.</p>
      {thread.source && <section><h2>Exact source context</h2><p>{thread.source.title} · {thread.source.version_id} · {thread.source.anchor}</p>{thread.source.quote && <blockquote>{thread.source.quote}</blockquote>}
        {thread.source.available ? <Link className="daily-link" href={contextHref(readerHref(thread.source, thread.source.version_id, thread.source.anchor, undefined, contextHref(`/workspace/threads/${thread.id}`, { ...context, mode: "learn", thread: thread.id, explicit: true })), { ...context, mode: "learn", project: null, thread: thread.id, explicit: true })} prefetch={false}>Read this exact prerequisite source →</Link> : <p>This pinned source is unavailable; a newer version has not been substituted.</p>}</section>}
      {thread.data.entry && <p>Linked shared entry {thread.data.entry.entry_id} · exact revision {thread.data.entry.entry_revision}. Later edits are not substituted into this source link.</p>}
      <div className="workspace-toolbar"><Link className="daily-link" href={returnHref} prefetch={false} scroll={false}>{origin?.project_id ? "Return to project" : "Return to originating source"}</Link><button type="button" onClick={() => setEdit(true)}>Edit learning thread</button></div>
      {edit && index && <Suspense fallback={<p aria-busy="true">Opening thread editor…</p>}><ThreadEditor owner={index.principal_key_id} thread={thread} origin={thread.data.origin} onCancel={() => setEdit(false)} onReload={() => setRetry(value => value + 1)} onSaved={value => { setThread(value); setEdit(false); }} /></Suspense>}
    </>}
  </div>;
}
