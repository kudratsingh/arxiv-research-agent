import { useState, type FormEvent } from "react";
import { contextRequest, errorMessage, type ProjectArtifactWrite, type ProjectDetail } from "@/lib/workspace/api";
import { stableContextId, useManualForm } from "@/lib/workspace/useManualForm";
import { Message } from "./Common";
import { invalidateContextIndex } from "@/lib/workspace/useContextIndex";
const KINDS = ["observation", "assumption", "hypothesis", "comparison", "proposed-experiment"] as const;
export default function ArtifactEditor({ owner, project, onSaved, onReload }: { owner: string; project: ProjectDetail; onSaved: (value: ProjectDetail) => void; onReload?: () => void }) {
  const [id] = useState(() => stableContextId("artifact"));
  const form = useManualForm(owner, `artifact-new:${project.id}`, id, project.revision, { kind: "observation", body: "", evidence: "" }, true);
  async function save(event: FormEvent) {
    event.preventDefault(); if (form.busy) return;
    const input: Omit<ProjectArtifactWrite, "request_id"> = { id: form.draft.id, revision: form.draft.revision, artifact_revision: 0,
      data: { kind: KINDS.find(kind => kind === form.values.kind) ?? "observation", body: form.values.body!, evidence_link_ids: form.values.evidence!.split("\n").filter(Boolean) } };
    const request_id = form.attempt(input); form.setBusy(true);
    try { const result = await contextRequest<ProjectDetail>(`/projects/${project.id}/artifacts`, { ...input, request_id }); form.clear(); invalidateContextIndex(); form.setNotice("Authored record saved as manual and unverified. No experiment was executed."); onSaved(result); }
    catch (failure) { form.setNotice(errorMessage(failure)); } finally { form.setBusy(false); }
  }
  const selected = form.values.evidence!.split("\n").filter(Boolean);
  const available = project.sources.filter(source => source.status === "active" && source.role === "evidence");
  return <form id={form.surfaceId} className="workspace-controls" aria-label="Authored research record" onSubmit={event => void save(event)}>
    <h2>Record your reasoning</h2><p className="daily-muted">These are your authored records. A link identifies a passage; it does not verify your conclusion.</p>
    {project.revision > form.draft.revision && <section className="workspace-version-notice" aria-label="Latest saved project for authored record review"><h3>Review the latest saved revision</h3><p>Project revision {project.revision} · {project.data.title}</p><p>{project.data.question}</p><ul>{project.sources.map(source => <li key={source.id}>{source.reference.title} · {source.status} · {source.role}</li>)}</ul><button type="button" disabled={form.busy} onClick={() => form.rebase(project.revision)}>Keep my edits on reviewed revision</button></section>}
    <label>Record type<select value={form.values.kind} disabled={form.busy} onChange={event => form.change("kind", event.target.value)}>{KINDS.map(kind => <option key={kind} value={kind}>{kind.replaceAll("-", " ")}</option>)}</select></label>
    <label>Your text<textarea required maxLength={10000} rows={5} value={form.values.body} readOnly={form.busy} onChange={event => form.change("body", event.target.value)} /></label>
    <fieldset><legend>Explicit evidence links (optional)</legend>{available.map(source => <label key={source.id}><input type="checkbox" disabled={form.busy} checked={selected.includes(source.id)} onChange={event => {
      const ids = new Set(form.values.evidence!.split("\n").filter(Boolean)); if (event.target.checked) ids.add(source.id); else ids.delete(source.id); form.change("evidence", Array.from(ids).join("\n"));
    }} />{source.reference.title} · {source.reference.anchor}</label>)}{selected.filter(id => !available.some(source => source.id === id)).map(id => <label key={id}><input type="checkbox" checked disabled={form.busy} onChange={() => form.change("evidence", selected.filter(value => value !== id).join("\n"))} />Unavailable evidence link {id} — remove before saving</label>)}</fieldset>
    <div className="workspace-toolbar"><button className="daily-button" disabled={form.busy}>{form.busy ? "Saving record…" : "Save authored record"}</button><button type="button" className="daily-secondary" disabled={form.busy} onClick={() => form.clear(true)}>Discard local record edits</button>{onReload && <button type="button" disabled={form.busy} onClick={onReload}>Reload saved project</button>}</div><Message>{form.notice}</Message>
  </form>;
}
