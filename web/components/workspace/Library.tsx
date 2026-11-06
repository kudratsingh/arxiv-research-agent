"use client";
import { loadContextEditors, loadContextReadouts } from "./contextModules";

import Link from "next/link";
import { requestPaperNavigation } from "@/lib/workspace/navigation";
import { useSearchParams } from "next/navigation";
import { lazy, Suspense, useState, useSyncExternalStore } from "react";
import { errorMessage, readerHref, workspaceRequest, type WorkItem } from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { useReadingActions } from "@/lib/workspace/useReadingActions";
import { libraryQueue, neighbours, readerTarget, resolveFocus } from "@/lib/workspace/queue";
import { setQueryParam, useQueryParam, WORKSPACE_URL_EVENT } from "@/lib/workspace/urlState";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";
import { LoadingState, Message, ServiceNotice } from "./Common";
import { QueueList } from "./Queue";
import { PlayerBar } from "./PlayerBar";
import { ControlBar, SidebarSection, StageHeaderSlot } from "./Slots";

import { FocusPaper } from "./FocusPaper";
import { contextHref, useProductContext } from "@/lib/workspace/productContext";
import { Mascot } from "./Mascot";

const PreviewImport = lazy(() => loadContextEditors().then((module) => ({ default: module.PreviewImport })));
const LearningThreadList = lazy(() => loadContextReadouts().then(module => ({ default: module.LearningThreadList })));

const FOCUS_EVENT = "workspace:library-focus";
function focusKey(owner: string, view: string) {
  return `arxiv.workspace.library-focus.v1:${encodeURIComponent(owner)}:${view}`;
}
function subscribeFocus(callback: () => void) {
  window.addEventListener(FOCUS_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => { window.removeEventListener(FOCUS_EVENT, callback); window.removeEventListener("storage", callback); };
}
function serverFocus(): null { return null; }

export function LiveLibrary() {
  const context = useProductContext();
  const { state, setState, error, reload } = useWorkspace();
  const [notice, setNotice] = useState("");
  const [manual, setManual] = useState("");
  const [busy, setBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importOpened, setImportOpened] = useState(false);
  const [threadsOpen, setThreadsOpen] = useState(false);
  const routerView = useSearchParams().get("view");
  const view = useQueryParam("view") ?? routerView;
  const focusId = useQueryParam("focus");
  const filter = view && ["saved", "notes", "read", "archived", "all"].includes(view) ? view : "saved";
  const owner = state?.principal_key_id ?? "";
  const storedFocus = useSyncExternalStore(subscribeFocus, () => {
    try { return sessionStorage.getItem(focusKey(owner, filter)); } catch { return null; }
  }, serverFocus);
  const actions = useReadingActions(state, setState, setNotice);
  const actionBusy = busy || actions.busy || importBusy;
  if (!state) return <div className="ws-library-state"><Mascot mood={error ? "alert" : "busy"} size={72} /><LoadingState error={error} retry={() => void reload()} /></div>;
  const works = libraryQueue(state, filter);
  const focused = resolveFocus(works, state.works.map((work) => work.work_id), focusId ?? storedFocus);
  const position = neighbours(works, focused?.work_id ?? null);
  const target = focused ? readerTarget(focused) : null;
  const resume = focused?.reading.context;
  const readerContext = resume ? { mode: resume.mode, project: resume.project_id, thread: resume.thread_id, explicit: true, invalid: false } : context;
  const returnTo = contextHref(`/workspace/library?view=${filter}${focused ? `&focus=${encodeURIComponent(focused.work_id)}` : ""}`, context);
  const href = focused && target ? contextHref(readerHref(focused, target.version, target.anchor, undefined, returnTo), readerContext) : "";
  const available = focused && target && (focused.versions.length
    ? focused.versions.some((version) => version.version_id === target.version) : focused.version_id === target.version);
  const notebook = filter === "notes"
    ? [...works.filter((work) => work.work_id === focused?.work_id), ...works.filter((work) => work.work_id !== focused?.work_id)]
    : focused ? [focused] : [];
  function remember(id: string) {
    try { sessionStorage.setItem(focusKey(owner, filter), id); window.dispatchEvent(new Event(FOCUS_EVENT)); }
    catch { setNotice("Reading selection cannot be remembered in this browser. Your server-saved notes are unchanged."); }
  }
  function closeDrawer() {
    if (document.querySelector('.workspace-app [role="dialog"][aria-modal="true"]')) dispatchWorkspaceCommand("escape");
  }
  function choose(id: string) {
    if (actionBusy) return;
    requestPaperNavigation();
    remember(id); setQueryParam("focus", id);
    Array.from(document.querySelectorAll<HTMLElement>(".ws-queue-row[data-work-id]")).find((row) => row.dataset.workId === id)?.scrollIntoView?.({ block: "nearest" });
    closeDrawer();
  }
  async function undo() {
    if (actionBusy) return;
    const id = actions.undoWorkId;
    if (await actions.undo() && id) choose(id);
  }
  async function saveManual(event: React.FormEvent) {
    event.preventDefault(); if (actionBusy) return;
    setBusy(true);
    try {
      const work = await workspaceRequest<WorkItem>("manual", { value: manual.trim() });
      await reload(); setManual("");
      setNotice(`Saved ${work.title}. Access remains ${work.access_state}; an original link is available in the reader.`);
    } catch (failure) { setNotice(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  return <div className="ws-library">
    <StageHeaderSlot position={focused ? { n: position.index + 1, N: position.count } : undefined} />
    <div className="daily-page-meta"><span className="daily-eyebrow">Your library · server-backed</span></div>
    <div className="daily-intro ws-library-intro"><div><h1>Keep the source.<br /><em>Keep your thinking.</em></h1><p>Saved reading, questions and next steps retain their source version.</p></div></div>
    <ServiceNotice error={error} />
    <SidebarSection label="Library view"><h2>Your library</h2><label>Library view<select value={filter} disabled={actionBusy} onChange={(event) => {
      if (actionBusy) return;
      window.history.pushState(window.history.state, "", contextHref(`/workspace/library?view=${encodeURIComponent(event.target.value)}`, context));
      window.dispatchEvent(new Event(WORKSPACE_URL_EVENT));
      closeDrawer();
    }}><option value="saved">Saved</option><option value="notes">With notes or questions</option><option value="read">Read</option><option value="archived">Archived</option><option value="all">All personal state</option></select></label>
      <QueueList items={works} focusId={focused?.work_id ?? null} onSelect={choose} label="Library reading queue" />
    </SidebarSection>
    <SidebarSection label="Quick add"><h2>Save a source</h2><form className="workspace-form-stack" onSubmit={(event) => void saveManual(event)}>
      <label>Save an arXiv ID, DOI or source URL<input value={manual} maxLength={2048} required readOnly={actionBusy} onChange={(event) => setManual(event.target.value)} placeholder="arXiv:2601.01234 · 10.1234/example · https://…" /></label>
      <button className="daily-secondary" disabled={actionBusy}>{busy ? "Saving source…" : "Save source link"}</button>
      <p className="daily-muted">Unsupported or inaccessible sources stay link/metadata items. Saving does not crawl the page or run a model.</p>
    </form></SidebarSection>
    <SidebarSection label="Import preview notes"><details className="ws-library-import" onToggle={(event) => { if (event.currentTarget.open) setImportOpened(true); }}>
      <summary>Import preview notes</summary>
      {importOpened && <Suspense fallback={<p className="daily-muted">Opening the explicit preview transfer…</p>}><PreviewImport revision={state.profile.revision} reload={reload} announce={setNotice} disabled={busy || actions.busy} onBusyChange={setImportBusy} /></Suspense>}
    </details></SidebarSection>
    {focused ? <>
      {available ? <><h2 className="sr-only">Focused source</h2><FocusPaper position={{ index: position.index, count: position.count }} item={focused} href={href} /></> : <section className="daily-empty ws-empty"><Mascot mood="alert" size={72} /><div><h2>This retained source version is unavailable.</h2><p>A newer version has not been substituted. Your notes still retain their original version and passage.</p></div></section>}
      {notebook.some((work) => work.entries.length > 0) && <section className="ws-library-notebook" aria-labelledby="library-notebook"><h2 id="library-notebook">Questions, notes and next actions</h2>
        {filter === "notes" && <p className="daily-muted">All notebook entries in this view, with the focused source first.</p>}
        {notebook.flatMap((item) => item.entries.map((entry) => <article key={entry.id} className="daily-notebook-entry">
          <span className="daily-eyebrow">Your {entry.kind.replaceAll("-", " ")}</span><p>{entry.body}</p>
          <p className="workspace-note-context">{item.title} · Source {entry.version_id} · {entry.anchor}</p>
          <Link href={contextHref(readerHref(item, entry.version_id, entry.anchor, entry.id, returnTo), entry.context ? { mode: entry.context.mode, project: entry.context.project_id, thread: entry.context.thread_id, explicit: true, invalid: false } : context)} prefetch={false} className="daily-link">Resume this question →</Link>
        </article>))}
      </section>}
    </> : <section className="daily-empty ws-empty"><Mascot mood="sleepy" size={72} /><div><h2>{filter === "saved" ? "Save something worth returning to." : "No items in this view."}</h2><p>Your notes and reading state will appear here after a successful server save.</p><Link href={contextHref("/workspace/today", context)} className="daily-link" prefetch={false}>Back to Today →</Link></div></section>}
    <details id="learning-threads" onToggle={event => setThreadsOpen(event.currentTarget.open)}><summary>Your saved learning threads</summary>{threadsOpen && <Suspense fallback={<p aria-busy="true">Opening learning threads…</p>}><LearningThreadList owner={owner} /></Suspense>}</details>
    <ControlBar>{focused && !available && <Link href={href} prefetch={false} className="daily-link" data-command="open">Open retained source context →</Link>}{focused && available && <PlayerBar item={focused} href={href} index={position.index} count={position.count}
      busy={actionBusy} onPrevious={position.previous && !actionBusy ? () => choose(position.previous!.work_id) : undefined}
      onNext={position.next && !actionBusy ? () => choose(position.next!.work_id) : undefined}>
      <div className="ws-player-actions">
        <button type="button" className="ws-player-action" disabled={actionBusy} data-command="save" aria-pressed={focused.reading.status === "saved"} aria-label={`${focused.reading.status === "saved" ? "Unsave" : "Save"} ${focused.title}`} onClick={() => { if (!actionBusy) void actions.status(focused, focused.reading.status === "saved" ? "unread" : "saved"); }}>{focused.reading.status === "saved" ? "Unsave" : "Save"}</button>
        <button type="button" className="ws-player-action" disabled={actionBusy} data-command="dismiss" aria-label={`Dismiss ${focused.title}`} onClick={() => { if (!actionBusy) void actions.status(focused, "dismissed"); }}>Dismiss</button>
        <button type="button" className="ws-player-action" disabled={actionBusy} data-command="snooze" aria-label={`Snooze one day ${focused.title}`} onClick={() => { if (!actionBusy) void actions.status(focused, "snoozed"); }}>Snooze one day</button>
      </div>
    </PlayerBar>}
      {actions.hasUndo && <button type="button" className="ws-player-action" data-command="undo" disabled={actionBusy} onClick={() => void undo()}>Undo last change</button>}
      <Message>{notice}</Message>
    </ControlBar>
  </div>;
}
