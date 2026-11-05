"use client";
import { loadContextEditors } from "./contextModules";

import Link from "next/link";
import { lazy, Suspense, useEffect, useState } from "react";
import { contextRequest, errorMessage, readerHref, requestId, type ProjectDetail } from "@/lib/workspace/api";
import { commitContextNavigation, contextHref, resumeContext, useProductContext } from "@/lib/workspace/productContext";
import { WORKSPACE_URL_EVENT } from "@/lib/workspace/urlState";
import { useContextIndex } from "@/lib/workspace/useContextIndex";
import { useDraftGuard } from "@/lib/workspace/useManualForm";
import { Message } from "./Common";
const ProjectEditor = lazy(() => loadContextEditors().then(module => ({ default: module.ProjectEditor })));
const ArtifactEditor = lazy(() => loadContextEditors().then(module => ({ default: module.ArtifactEditor })));
const ThreadEditor = lazy(() => loadContextEditors().then(module => ({ default: module.ThreadEditor })));

export function LiveProjects() {
  const context = useProductContext();
  return <ProjectScreen key={context.project ?? "none"} />;
}
function ProjectScreen() {
  const { index, error, reload } = useContextIndex(), context = useProductContext();
  const [detail, setDetail] = useState<ProjectDetail | null>(null), [failure, setFailure] = useState("");
  const [edit, setEdit] = useState(false), [create, setCreate] = useState(false), [thread, setThread] = useState(false), [artifact, setArtifact] = useState(false);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [readRevision, setReadRevision] = useState(0);
  const [savedCreation, setSavedCreation] = useState<ProjectDetail | null>(null);
  useDraftGuard(false, busy, () => setNotice("Wait for this project request to finish before leaving."));
  useEffect(() => {
    if (!context.project) return;
    const controller = new AbortController();
    contextRequest<ProjectDetail>(`/projects/${context.project}`, undefined, controller.signal).then(value => {
      if (!controller.signal.aborted) { setDetail(value); setFailure(""); }
    }).catch(failure => { if (!controller.signal.aborted) setFailure(errorMessage(failure)); });
    return () => controller.abort();
  }, [context.project, readRevision]);
  useEffect(() => {
    if (!savedCreation) return;
    const href = contextHref("/workspace/projects", { mode: "research", project: savedCreation.id, thread: null, explicit: true, invalid: false });
    // The saved form unmounts before this acknowledgement effect; other vetoes still apply.
    commitContextNavigation(href, target => { history.replaceState(history.state, "", target); window.dispatchEvent(new Event(WORKSPACE_URL_EVENT)); });
  }, [savedCreation]);
  function saved(value: ProjectDetail) { if (context.project !== value.id) setSavedCreation(value); else setDetail(value); setEdit(false); setCreate(false); void reload(); setNotice("Project saved on the server."); }
  async function unlink(link: string) {
    if (!detail || busy) return;
    setBusy(true);
    try { setDetail(await contextRequest<ProjectDetail>(`/projects/${detail.id}/unlink`, { revision: detail.revision, request_id: requestId(), link_id: link })); setNotice("Project link removed. The Library source, notes and retained material are unchanged."); }
    catch (failure) { setNotice(errorMessage(failure)); } finally { setBusy(false); }
  }
  const projectContext = { ...context, mode: "research" as const, project: detail?.id ?? context.project, thread: null, explicit: true };
  const projectHref = contextHref("/workspace/projects", projectContext);
  const current = detail && (!context.project || detail.id === context.project) ? detail : null;
  return <div className="ws-projects">
    <h1>Research projects</h1><p>Investigate a question with explicit sources and your own reasoning. Library records stay shared.</p>
    {!index && !error && <p aria-busy="true">Loading owned projects…</p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => void reload()}>Retry project list</button></p>}
    {index && <><div className="workspace-toolbar"><button className="daily-button" type="button" disabled={busy || create || edit || artifact || thread} onClick={() => setCreate(true)}>Create a project</button><Link className="daily-link" href={contextHref("/workspace/library", context)} prefetch={false}>Shared Library →</Link></div>
      <ul>{index.projects.map(project => <li key={project.id}><Link prefetch={false} scroll={false} href={contextHref("/workspace/projects", { ...projectContext, project: project.id })}>{project.data.title}</Link> · {project.data.status} · revision {project.revision}</li>)}</ul>
      {!index.projects.length && <p>No projects yet. Create one explicitly; your saved organizing question has not been imported.</p>}
    </>}
    {context.project && !current && !failure && <p aria-busy="true">Loading this owned project…</p>}
    {savedCreation && <p>Created {savedCreation.data.title}. <Link href={contextHref("/workspace/projects", { ...projectContext, project: savedCreation.id })} prefetch={false}>Open saved project →</Link></p>}
    {failure && <section data-workspace-unavailable=""><h2>This project is unavailable.</h2><p>{failure} Another project has not been substituted.</p><button type="button" onClick={() => setReadRevision(value => value + 1)}>Retry project</button></section>}
    {create && index && <Suspense fallback={<p aria-busy="true">Opening project form…</p>}><ProjectEditor owner={index.principal_key_id} onSaved={saved} onCancel={() => setCreate(false)} /></Suspense>}
    {current && index && <section aria-label="Project workspace">
      <h2>{current.data.title}</h2><p className="ws-question">{current.data.question}</p><p>Project revision {current.revision} · {current.data.status}</p>
      <p>{current.data.scope || "No scope declared."}</p><p>{current.data.constraints || "No constraints declared."}</p>
      <div className="workspace-toolbar"><Link className="daily-link" href={contextHref("/workspace/today", projectContext)} prefetch={false}>Research this question →</Link><Link className="daily-link" href={contextHref("/workspace/radar", projectContext)} prefetch={false}>Search project sources →</Link>
        <button type="button" disabled={busy || create || artifact || thread} onClick={() => setEdit(true)}>Edit project</button>{!edit && <button type="button" disabled={busy || create || artifact || thread} onClick={() => setReadRevision(value => value + 1)}>Reload saved project</button>}</div>
      {edit && <Suspense fallback={<p aria-busy="true">Opening project editor…</p>}><ProjectEditor owner={index.principal_key_id} project={current} onSaved={saved} onCancel={() => setEdit(false)} onReload={() => setReadRevision(value => value + 1)} /></Suspense>}
      <h3>Next actions</h3><ul>{current.data.next_actions.map((action, i) => <li key={i}>{action}</li>)}</ul>
      <h3>Sources and exact evidence</h3><p>Source identity and retained passages are inspectable. A citation alone does not establish factual support.</p>
      {!current.sources.some(source => source.status === "active") && <p>No linked sources. Open a Reader source and choose Investigate this.</p>}
      {current.sources.map(source => <article key={source.id} className="workspace-artifact"><h4>{source.reference.title}</h4><p>{source.role === "evidence" ? "Retained evidence passage" : "Whole-source reference"} · {source.status} · {source.reference.version_id} · {source.reference.anchor}</p>
        {source.label && <p>{source.label}</p>}{source.reference.quote && <blockquote>{source.reference.quote}</blockquote>}
        {source.reference.available ? <Link className="daily-link" href={contextHref(readerHref(source.reference, source.reference.version_id, source.reference.anchor, undefined, projectHref), projectContext)} prefetch={false}>Open exact project passage →</Link> : <p>This pinned source is unavailable. No newer version is substituted.</p>}
        {source.status === "active" && <button type="button" disabled={busy || current.data.status === "archived"} onClick={() => void unlink(source.id)}>Remove project link</button>}
      </article>)}
      <h3>Linked shared notes</h3>{current.entries.map(link => <article key={link.entry_id}><p>Entry {link.entry_id} · linked revision {link.entry_revision}{link.current_revision !== link.entry_revision ? ` · current revision ${link.current_revision ?? "unavailable"}` : ""}</p>
        {link.entry ? <><p>{link.entry.body}</p><Link className="daily-link" href={contextHref(readerHref(link.entry, link.entry.version_id, link.entry.anchor, link.current_revision === link.entry_revision ? link.entry.id : undefined, projectHref), projectContext)} prefetch={false}>Open linked note source →</Link>{link.current_revision !== link.entry_revision && <p>The linked historical text is shown here. Reader opens this exact source passage without substituting a later note revision.</p>}</> : <p>This linked entry is unavailable; its reference remains recorded.</p>}
      </article>)}
      <h3>Authored records</h3>{current.artifacts.map(item => <article key={item.id}><h4>{item.data.kind.replaceAll("-", " ")}</h4><p>Manual · unverified · revision {item.revision}</p><p>{item.data.body || `Linked entry ${item.data.entry?.entry_id}`}</p><p>{item.data.evidence_link_ids.length} explicit evidence links</p></article>)}
      {current.data.status === "archived" && <p className="workspace-version-notice">This project is archived. Source links and authored records are read-only until you explicitly edit and unarchive it. Shared notes remain available; manual learning threads can retain this origin.</p>}
      <button type="button" disabled={current.data.status === "archived" || create || edit || thread} onClick={() => setArtifact(true)}>Add authored research record</button>
      {artifact && <Suspense fallback={<p aria-busy="true">Opening authored-record form…</p>}><ArtifactEditor key={current.revision} owner={index.principal_key_id} project={current} onReload={() => setReadRevision(value => value + 1)} onSaved={value => { setDetail(value); setArtifact(false); }} /></Suspense>}
      <h3>Learning threads</h3><ul>{current.threads.map(item => <li key={item.id}><Link href={contextHref(`/workspace/threads/${item.id}`, { ...projectContext, mode: "learn", project: null, thread: item.id })} prefetch={false}>{item.data.title}</Link></li>)}</ul>
      <button type="button" disabled={create || edit || artifact} onClick={() => setThread(true)}>Learn this prerequisite</button>
      {thread && <Suspense fallback={<p aria-busy="true">Opening learning-thread form…</p>}><ThreadEditor owner={index.principal_key_id} origin={resumeContext(projectContext, projectHref)} onCancel={() => setThread(false)} onSaved={value => { setDetail({ ...current, threads: [...current.threads, value] }); setThread(false); }} /></Suspense>}
    </section>}
    <Message>{notice}</Message>
  </div>;
}
