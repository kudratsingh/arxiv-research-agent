import Link from "next/link";
import { useState } from "react";
import { contextRequest, errorMessage, type EntryRevision, type LearningThread, type ProjectDetail, type SourceReference } from "@/lib/workspace/api";
import { contextHref, resumeContext, useProductContext } from "@/lib/workspace/productContext";
import { invalidateContextIndex, useContextIndex } from "@/lib/workspace/useContextIndex";
import { useManualForm } from "@/lib/workspace/useManualForm";
import { Message } from "./Common";
import { parseMaterialAnchor } from "@/lib/workspace/materialAnchors";
import ProjectEditor from "./ProjectEditor";
import ThreadEditor from "./ThreadEditor";

export default function ReaderContextActions({ owner, source: sourceInput, entries: entriesInput, returnTo: returnInput, blocked = false }: { owner: string; source: SourceReference; entries: EntryRevision[]; returnTo: string; blocked?: boolean }) {
  const [{ source, entries, returnTo }] = useState(() => ({ source: { ...sourceInput }, entries: entriesInput.map(entry => ({ ...entry })), returnTo: returnInput }));
  const context = useProductContext(), { index, error, reload, setIndex } = useContextIndex();
  const [creating, setCreating] = useState(false), [learning, setLearning] = useState(false);
  const [savedProject, setSavedProject] = useState<ProjectDetail | null>(null), [savedThread, setSavedThread] = useState<LearningThread | null>(null);
  const form = useManualForm(owner, `source-link:${source.work_id}:${source.version_id}:${source.anchor}`, source.work_id, 0, { project: context.project ?? "", role: "source", label: "", entry: "" });
  const selected = index?.projects.find(project => project.id === form.values.project && project.data.status === "active");
  const entry = entries.find(value => value.id === form.values.entry);
  const entryReference = entry ? { entry_id: entry.id, entry_revision: entry.revision } : undefined;
  const range = /^(abstract|excerpt|full_text):(\d+):(\d+)$/.exec(source.anchor ?? "");
  const evidence = Boolean(range && Number(range[3]) > Number(range[2]) || parseMaterialAnchor(source.anchor ?? ""));
  function acknowledge(result: ProjectDetail) {
    if (index) setIndex({ ...index, projects: index.projects.map(project => project.id === result.id ? result : project) });
    setSavedProject(result); invalidateContextIndex(); form.clear(false, { ...form.values, label: "" });
  }
  async function attach(kind: "source" | "entry") {
    if (!selected || form.busy || blocked || kind === "entry" && !entry) return;
    const input = kind === "source" ? { revision: selected.revision, role: form.values.role === "evidence" ? "evidence" : "source", label: form.values.label, reference: source }
      : { revision: selected.revision, ...entryReference };
    const request_id = form.attempt(input); form.setBusy(true);
    try {
      acknowledge(await contextRequest<ProjectDetail>(`/projects/${selected.id}/${kind === "source" ? "sources" : "entries"}`, { ...input, request_id }));
      form.setNotice(kind === "source" ? "Exact source link saved. This does not establish factual support." : "Existing note revision linked. Its text remains one shared Library record.");
    } catch (failure) { form.setNotice(errorMessage(failure)); } finally { form.setBusy(false); }
  }
  if (index && index.principal_key_id !== owner) return <p role="alert">Project context belongs to a different local account. No link was made.</p>;
  return <section id={form.surfaceId} aria-label="Cross-mode source actions" className="workspace-controls">
    <h2>Investigate or learn from this exact source</h2>
    <p>{source.work_id} · {source.version_id} · {source.anchor}</p>
    <p className="daily-muted">Carried source and note choices are fixed when this panel opens. Links never move your source or copy all notes. Finish or discard edits before choosing Use current viewed source context.</p>
    {error && <p role="alert">{error}</p>}{!index && !error && <p aria-busy="true">Loading owned projects…</p>}
    {index && <fieldset disabled={blocked}><legend>Explicit project and learning actions</legend><label>Project for this source<select value={form.values.project} disabled={form.busy} onChange={event => form.change("project", event.target.value)}><option value="">Choose an existing project</option>{form.values.project && !selected && <option value={form.values.project}>Archived or unavailable project</option>}{index.projects.filter(project => project.data.status === "active").map(project => <option key={project.id} value={project.id}>{project.data.title}</option>)}</select></label>
      <label>Link role<select value={form.values.role} disabled={form.busy} onChange={event => form.change("role", event.target.value)}><option value="source">Whole-source reference — no support claim</option><option value="evidence" disabled={!evidence}>Selected retained passage — evidence link</option></select></label>
      <label>Project link label (optional)<input value={form.values.label} maxLength={2000} readOnly={form.busy} onChange={event => form.change("label", event.target.value)} /></label>
      <label>Explicit shared note link (optional)<select value={form.values.entry} disabled={form.busy} onChange={event => form.change("entry", event.target.value)}><option value="">No note selected</option>{entries.map(value => <option key={value.id} value={value.id}>{value.kind} · revision {value.revision} · {value.body.slice(0, 100)}</option>)}</select></label>
      <div className="workspace-toolbar"><button type="button" className="daily-button" disabled={!selected || form.busy} onClick={() => void attach("source")}>{form.busy ? "Saving link…" : "Attach source to project"}</button><button type="button" disabled={!selected || !entry || form.busy} onClick={() => void attach("entry")}>Link selected saved note</button>
        <button type="button" disabled={form.busy} onClick={() => setCreating(true)}>Investigate this in a new project</button><button type="button" disabled={form.busy} onClick={() => setLearning(true)}>Learn this prerequisite</button>
        <button type="button" disabled={form.busy} onClick={() => void reload()}>Reload project versions</button><button type="button" disabled={form.busy} onClick={() => form.clear(true)}>Discard local link edits</button></div>
      {creating && <ProjectEditor owner={owner} source={source} entry={entryReference} question={entry?.kind === "question" ? entry.body : ""} onCancel={() => setCreating(false)} onSaved={value => { form.clear(); setSavedProject(value); setCreating(false); void reload(); }} />}
      {learning && <ThreadEditor owner={owner} source={source} entry={entryReference} origin={resumeContext(context, returnTo)} onCancel={() => setLearning(false)} onSaved={value => { form.clear(); setSavedThread(value); setLearning(false); }} />}
    </fieldset>}
    {savedProject && <Link className="daily-link" href={contextHref("/workspace/projects", { ...context, mode: "research", project: savedProject.id, thread: null, explicit: true })} prefetch={false}>Open saved project →</Link>}
    {savedThread && <Link className="daily-link" href={contextHref(`/workspace/threads/${savedThread.id}`, { ...context, mode: "learn", project: null, thread: savedThread.id, explicit: true })} prefetch={false}>Open saved learning thread →</Link>}
    <Message>{form.notice}</Message>
  </section>;
}
