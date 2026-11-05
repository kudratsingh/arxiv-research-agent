import { useState, type FormEvent } from "react";
import { contextRequest, errorMessage, type EntryReference, type ProjectDetail, type ProjectWrite, type ResearchProject, type SourceReference } from "@/lib/workspace/api";
import { stableContextId, useManualForm } from "@/lib/workspace/useManualForm";
import { Message } from "./Common";
import { invalidateContextIndex } from "@/lib/workspace/useContextIndex";

export default function ProjectEditor({ owner, project, source: sourceInput, entry: entryInput, question = "", onSaved, onCancel, onReload }: {
  owner: string; project?: ResearchProject; source?: SourceReference; entry?: EntryReference; question?: string;
  onSaved: (value: ProjectDetail) => void; onCancel?: () => void; onReload?: () => void;
}) {
  const [{ source, entry }] = useState(() => ({ source: sourceInput ? { ...sourceInput } : undefined, entry: entryInput ? { ...entryInput } : undefined }));
  const [id] = useState(() => project?.id ?? stableContextId("project"));
  const form = useManualForm(owner, project?.id ?? `project-new:${JSON.stringify({ source: source ?? null, entry: entry ?? null })}`, id, project?.revision ?? 0, {
    title: project?.data.title ?? "", question: project?.data.question ?? question, scope: project?.data.scope ?? "", constraints: project?.data.constraints ?? "",
    actions: project?.data.next_actions.join("\n") ?? "", status: project?.data.status ?? "active",
  }, !project);
  async function save(event: FormEvent) {
    event.preventDefault(); if (form.busy) return;
    const input: Omit<ProjectWrite, "request_id"> = { id: form.draft.id, revision: form.draft.revision,
      data: { title: form.values.title!, question: form.values.question!, scope: form.values.scope!, constraints: form.values.constraints!, next_actions: form.values.actions!.split("\n").map(s => s.trim()).filter(Boolean), status: form.values.status === "archived" ? "archived" : "active" },
      ...(source ? { initial_source: source } : {}), ...(entry ? { origin_entry: entry } : {}) };
    const request_id = form.attempt(input); form.setBusy(true);
    try { const result = await contextRequest<ProjectDetail>("/projects", { ...input, request_id }); form.clear(); invalidateContextIndex(); form.setNotice("Project saved on the server. Shared Library records are unchanged."); onSaved(result); }
    catch (failure) { form.setNotice(errorMessage(failure)); } finally { form.setBusy(false); }
  }
  return <form id={form.surfaceId} className="workspace-controls" onSubmit={event => void save(event)} aria-label={project ? "Edit research project" : "Create research project"}>
    <h2>{project ? "Edit project" : "Create a research project"}</h2>
    <p className="daily-muted">A project organizes your question and explicit links. Creating it runs no model and changes no interests.</p>
    {source && <p>Carried source: {source.work_id} · {source.version_id} · {source.anchor}</p>}
    {entry && <p>Explicit saved-entry link: {entry.entry_id} · revision {entry.entry_revision}</p>}
    {project && <p>Saved project revision {project.revision} · local edit base {form.draft.revision}. Reloading does not overwrite local edits.</p>}
    {project && project.revision > form.draft.revision && <section className="workspace-version-notice" aria-label="Latest saved project for review"><h3>Review the latest saved revision</h3><p>{project.data.title}</p><p>{project.data.question}</p><p>{project.data.scope}</p><p>{project.data.constraints}</p><ul>{project.data.next_actions.map((action, i) => <li key={i}>{action}</li>)}</ul><p>Status: {project.data.status}</p><button type="button" disabled={form.busy} onClick={() => form.rebase(project.revision)}>Keep my edits on reviewed revision</button></section>}
    {([['title', 'Project title', 240], ['question', 'Research question', 4000], ['scope', 'Scope', 4000], ['constraints', 'Constraints', 4000], ['actions', 'Next actions, one per line', 10000]] as const).map(([field, label, limit]) => <label key={field}>{label}
      <textarea required={field === "title" || field === "question"} maxLength={limit} value={form.values[field]} readOnly={form.busy} onChange={event => form.change(field, event.target.value)} rows={field === "title" ? 1 : 3} />
    </label>)}
    {project && <label>Status<select value={form.values.status} disabled={form.busy} onChange={event => form.change("status", event.target.value)}><option value="active">Active</option><option value="archived">Archived — preserve shared sources and notes</option></select></label>}
    <div className="workspace-toolbar"><button className="daily-button" disabled={form.busy}>{form.busy ? "Saving project…" : project ? "Save project changes" : "Create project"}</button>
      <button className="daily-secondary" type="button" disabled={form.busy} onClick={() => { form.clear(true); onCancel?.(); }}>Discard local project edits</button>{onReload && <button type="button" disabled={form.busy} onClick={onReload}>Reload saved project</button>}</div>
    {!form.storage && <p className="workspace-version-notice">Browser recovery is unavailable. Keep this tab open or copy edits before a full reload.</p>}
    <Message>{form.notice}</Message>
  </form>;
}
