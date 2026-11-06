import { useState, type FormEvent } from "react";
import { contextRequest, errorMessage, type EntryReference, type LearningThread, type LearningThreadWrite, type ResumeContext, type SourceReference } from "@/lib/workspace/api";
import { stableContextId, useManualForm } from "@/lib/workspace/useManualForm";
import { Message } from "./Common";
import { SourceReferenceDetails } from "./SourceReferenceDetails";
import { invalidateContextIndex } from "@/lib/workspace/useContextIndex";

export default function ThreadEditor({ owner, thread, origin: originInput, source: sourceInput, entry: entryInput, onSaved, onCancel, onReload }: {
  owner: string; thread?: LearningThread; origin: ResumeContext; source?: SourceReference; entry?: EntryReference;
  onSaved: (value: LearningThread) => void; onCancel?: () => void; onReload?: () => void;
}) {
  const [carried] = useState(() => ({ origin: { ...(thread?.data.origin ?? originInput) }, source: thread?.data.source ? { ...thread.data.source } : sourceInput ? { ...sourceInput } : null, entry: thread?.data.entry ? { ...thread.data.entry } : entryInput ? { ...entryInput } : null }));
  const { origin, source, entry } = carried;
  const [id] = useState(() => thread?.id ?? stableContextId("thread"));
  const form = useManualForm(owner, thread?.id ?? `thread-new:${JSON.stringify({ origin, source: source ?? null, entry: entry ?? null })}`, id, thread?.revision ?? 0,
    { title: thread?.data.title ?? "", goal: thread?.data.goal ?? "", prerequisite: thread?.data.prerequisite ?? "", status: thread?.data.status ?? "active" }, !thread);
  async function save(event: FormEvent) {
    event.preventDefault(); if (form.busy) return;
    const input: Omit<LearningThreadWrite, "request_id"> = { id: form.draft.id, revision: form.draft.revision, data: {
      title: form.values.title!, goal: form.values.goal!, prerequisite: form.values.prerequisite!, status: form.values.status === "archived" ? "archived" : "active",
      origin, source, entry,
    } };
    const request_id = form.attempt(input); form.setBusy(true);
    try { const result = await contextRequest<LearningThread>("/threads", { ...input, request_id }); form.clear(); invalidateContextIndex(); form.setNotice("Learning thread saved. This is your learning goal, not a generated explanation or a mastery judgment."); onSaved(result); }
    catch (failure) { form.setNotice(errorMessage(failure)); } finally { form.setBusy(false); }
  }
  return <form id={form.surfaceId} className="workspace-controls" aria-label="Learning thread" onSubmit={event => void save(event)}>
    <h2>{thread ? "Edit learning thread" : "Learn this prerequisite"}</h2>
    <p className="daily-muted">Record what you want to understand. The originating project and exact source remain attached. No model runs.</p>
    {thread && thread.revision > form.draft.revision && <section className="workspace-version-notice" aria-label="Latest saved thread for review"><h3>Review the latest saved revision</h3><p>{thread.data.title}</p><p>{thread.data.goal}</p><p>{thread.data.prerequisite}</p><p>Status: {thread.data.status}</p><button type="button" disabled={form.busy} onClick={() => form.rebase(thread.revision)}>Keep my edits on reviewed revision</button></section>}
    {source && <section className="ws-source-card"><h3>Prerequisite source</h3><SourceReferenceDetails reference={source} /></section>}
    <details className="ws-record-details"><summary>Origin and return details</summary><p>Carried origin: {origin.mode} · {origin.project_id ?? "no project"} · {origin.return_to}</p></details>
    {([['title', 'Thread title', 240], ['goal', 'What do you want to understand?', 4000], ['prerequisite', 'Prerequisite or term to learn', 2000]] as const).map(([field, label, max]) => <label key={field}>{label}<textarea rows={field === "title" ? 1 : 3} required={field !== "prerequisite"} maxLength={max} value={form.values[field]} readOnly={form.busy} onChange={event => form.change(field, event.target.value)} /></label>)}
    {thread && <label>Status<select value={form.values.status} disabled={form.busy} onChange={event => form.change("status", event.target.value)}><option value="active">Active</option><option value="archived">Archived</option></select></label>}
    <div className="workspace-toolbar"><button className="daily-button" disabled={form.busy}>{form.busy ? "Saving thread…" : "Save learning thread"}</button><button type="button" className="daily-secondary" disabled={form.busy} onClick={() => { form.clear(true); onCancel?.(); }}>Discard local thread edits</button>{onReload && <button type="button" disabled={form.busy} onClick={onReload}>Reload saved thread</button>}</div>
    {!form.storage && <p className="workspace-version-notice">Browser recovery is unavailable. Copy edits before a full reload.</p>}<Message>{form.notice}</Message>
  </form>;
}
