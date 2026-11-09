"use client";

import { ScoredSections } from "./ScoredSections";
import { AssistanceTaskContext, AssistanceDisposition, RequestCoverage, taskDefaults } from "./AssistanceTaskContext";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { contextHref, resumeContext, useProductContext } from "@/lib/workspace/productContext";
import { contextRequest, errorMessage, readerHref, workspaceRequest, type EntryRevision, type LearningThread, type ProjectDetail, type ResumeContext } from "@/lib/workspace/api";
import { passageAnchor, type AssistanceInput, type AssistanceJob, type AssistancePreview, type EvidenceUnit } from "@/lib/workspace/assistanceTypes";
import { useManualForm } from "@/lib/workspace/useManualForm";
import { invalidateContextIndex } from "@/lib/workspace/useContextIndex";
import { Message } from "./Common";

const terminal = new Set(["ready", "ready_partial", "cancelled", "failed", "interrupted", "budget_stopped", "stale"]);
const stateLabel: Record<string, string> = { queued: "Queued", drafting: "Running local draft", checking: "Checking", repairing: "Repairing", ready: "Completed simulation", ready_partial: "Completed with abstentions", cancelled: "Cancelled", failed: "Failed", interrupted: "Interrupted · inspect before continuing", budget_stopped: "Budget refused", stale: "Source or request changed" };
const initial = { depth: "overview", background: "", direction: "overview", follow_up: "", units: "[]" };

export default function AssistancePanel({ owner, workId, versionId, returnTo, onSource }: {
  owner: string; workId: string; versionId: string; returnTo: string; onSource: (anchor: string) => void;
}) {
  const context = useProductContext();
  const form = useManualForm(owner, `assistance:${workId}:${versionId}:${context.mode}:${context.project ?? ""}`, "assistance", 0, initial);
  // Separate recovery key preserves existing assistance drafts when adding policy fields.
  const taskForm = useManualForm(owner, `assistance-task:${workId}:${versionId}:${context.mode}:${context.project ?? ""}`, "assistance-task", 0, taskDefaults);
  const [units, setUnits] = useState<EvidenceUnit[]>([]), [jobs, setJobs] = useState<AssistanceJob[]>([]);
  const [project, setProject] = useState<ProjectDetail | null>(null), [loaded, setLoaded] = useState(false);
  const [preview, setPreview] = useState<AssistancePreview | null>(null), [job, setJob] = useState<AssistanceJob | null>(null);
  const [notice, setNotice] = useState(""), [savedThread, setSavedThread] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0), [running, setRunning] = useState(false);
  const jobRef = useRef<AssistanceJob | null>(null), stop = useRef(false), mounted = useRef(true);
  const selected: string[] = (() => { try { const value: unknown = JSON.parse(form.values.units!); return Array.isArray(value) && value.every(x => typeof x === "string") ? value : []; } catch { return []; } })();
  const publish = (value: AssistanceJob) => { jobRef.current = value; if (mounted.current) setJob(old => old?.id === value.id && old.revision > value.revision ? old : value); };
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; stop.current = true; }; }, []);
  useEffect(() => {
    const pending = new AbortController();
    const query = new URLSearchParams({ work_id: workId, version_id: versionId });
    if (context.mode === "research" && context.project) query.set("project", context.project);
    Promise.all([
      workspaceRequest<{ units: EvidenceUnit[] }>(`assistance/catalog?${query}`, undefined, pending.signal),
      workspaceRequest<AssistanceJob[]>(`assistance/jobs?${new URLSearchParams({ work_id: workId, version_id: versionId })}`, undefined, pending.signal),
      context.mode === "research" && context.project ? contextRequest<ProjectDetail>(`/projects/${context.project}`, undefined, pending.signal) : Promise.resolve(null),
    ]).then(([catalog, previous, active]) => {
      if (pending.signal.aborted) return;
      setUnits(catalog.units); setJobs(previous); setProject(active); setLoaded(true);
      const requested = new URL(location.href).searchParams.get("assistance");
      const saved = previous.find(value => value.id === requested);
      if (saved) { jobRef.current = saved; setJob(saved); }
    }).catch(failure => { if (!pending.signal.aborted) setNotice(errorMessage(failure)); });
    return () => pending.abort();
  }, [workId, versionId, context.mode, context.project, attempt]);
  function change(field: string, value: string) { form.change(field, value); setPreview(null); }
  function input(): AssistanceInput {
    const chosen = units.filter(unit => selected.includes(unit.id));
    const intent = context.mode === "research" ? taskForm.values.intent as "answer" | "comparison" | "application_assessment" : "answer";
    return { mode: context.mode, work_id: workId, version_id: versionId,
      material_ids: [...new Set(chosen.map(unit => unit.reference.material_id))], span_ids: [...new Set(chosen.map(unit => unit.reference.span_id))], unit_ids: selected,
      depth: form.values.depth === "technical" ? "technical" : "overview", background: form.values.background!,
      direction: form.values.direction as AssistanceInput["direction"], follow_up: form.values.follow_up!,
      project_id: context.mode === "research" ? context.project : null, project_revision: project?.revision ?? null,
      parent_job: job?.result ? job.id : null, origin: resumeContext(context, returnTo),
      task_context: { intent, requested_parts: (taskForm.values.requested_parts ?? "").split("\n").map(part => part.trim()).filter(Boolean).map((request, i) => ({ id: `p${i + 1}`, request, kind: intent === "comparison" && i === 0 ? "comparison" : "answer" })), application_context: Object.fromEntries(Object.keys(taskDefaults).filter(key => key !== "intent" && key !== "requested_parts").map(key => [key, intent === "application_assessment" ? taskForm.values[key]! : ""])) } };
  }
  async function prepare() {
    if (form.busy) return;
    form.setBusy(true); setNotice("");
    try { setPreview(await workspaceRequest<AssistancePreview>("assistance/preview", { input: input() })); setNotice("Request sealed for review. No execution or provider contact occurred."); }
    catch (failure) { setPreview(null); setNotice(errorMessage(failure)); }
    finally { form.setBusy(false); }
  }
  async function continueJob(value: AssistanceJob) {
    publish(value);
    const url = new URL(location.href); url.searchParams.set("assistance", value.id); history.replaceState(history.state, "", url);
    for (let count = 0; count < 4 && !terminal.has(value.state) && !stop.current; count++) {
      value = await workspaceRequest<AssistanceJob>(`assistance/jobs/${value.id}/advance`, {});
      publish(value);
    }
    if (mounted.current) { setNotice(terminal.has(value.state) ? `${stateLabel[value.state]}. Results remain simulated and unqualified.` : "Paused at a durable stage. Inspect and explicitly continue."); setAttempt(n => n + 1); }
  }
  async function run(resume?: AssistanceJob) {
    if (form.busy || (!resume && !preview)) return;
    stop.current = false; form.setBusy(true); setRunning(true);
    try {
      let value = resume;
      if (!value) {
        const payload = { input: input(), expected_digest: preview!.request_digest };
        value = await workspaceRequest<AssistanceJob>("assistance/jobs", { ...payload, request_id: form.attempt(payload) });
        form.clear(false, { ...form.values });
        taskForm.clear(false, { ...taskForm.values });
        setPreview(null);
      }
      await continueJob(value);
    } catch (failure) { setNotice(`${errorMessage(failure)} Inspect stored status before continuing; no automatic retry was made.`); }
    finally { if (mounted.current) { form.setBusy(false); setRunning(false); } }
  }
  async function inspect(action = "") {
    const value = jobRef.current;
    if (!value) return;
    if (action === "cancel") stop.current = true;
    try { publish(await workspaceRequest<AssistanceJob>(`assistance/jobs/${value.id}${action ? `/${action}` : ""}`, action ? {} : undefined)); }
    catch (failure) { setNotice(errorMessage(failure)); }
  }
  async function save(target: "thread" | "project") {
    if (!job?.result || !job.assistance_output || form.busy) return;
    const stored = job.request.assistance;
    const chosen = Object.values(job.request.units).find(ref => ref.work_id === stored.work_id && ref.version_id === stored.version_id); if (!chosen) return;
    const origin: ResumeContext = stored.origin ?? { mode: stored.mode, project_id: stored.project_id, thread_id: null, return_to: returnTo };
    const entryId = `assistance-${job.id}`, threadId = `thread-${job.id.slice(5, 37)}`;
    const body = ["Simulated assistance · factual quality and human support unmeasured.", ...job.assistance_output.claims.map(c => `${c.claim_id}: ${c.text}`), "Proposed next action: " + job.assistance_output.proposal, "Durable simulation: " + job.id].join("\n\n");
    form.setBusy(true);
    try {
      const entry = await contextRequest<EntryRevision>("/entries", { id: entryId, revision: 0, request_id: `save-${job.id}`, context: origin, data: { work_id: stored.work_id, version_id: stored.version_id, kind: "note", body, anchor: passageAnchor(chosen) } });
      if (target === "project") {
        if (!stored.project_id) throw new Error("Select a project before linking this saved note.");
        const current = await contextRequest<ProjectDetail>(`/projects/${stored.project_id}`);
        if (!current.entries.some(link => link.entry_id === entry.id && link.entry_revision === entry.revision)) await contextRequest(`/projects/${stored.project_id}/entries`, { revision: current.revision, request_id: `link-${job.id}`, entry_id: entry.id, entry_revision: entry.revision });
        setNotice("Simulated result saved as a shared note and linked to the project. It remains unverified.");
      } else {
        const thread = await contextRequest<LearningThread>("/threads", { id: threadId, revision: 0, request_id: `thread-${job.id}`, data: { title: "Simulated guided reading", goal: stored.follow_up || job.assistance_output.questions[0], prerequisite: `Resume simulation ${job.id}; understanding is unmeasured.`, status: "active", origin, source: { work_id: chosen.work_id, version_id: chosen.version_id, anchor: passageAnchor(chosen) }, entry: { entry_id: entry.id, entry_revision: entry.revision } } });
        setSavedThread(thread.id); setNotice("Learning thread and shared note saved. Return to this source's Understand tab to inspect the durable simulation.");
      }
      invalidateContextIndex();
    } catch (failure) { setNotice(`The simulation remains saved. ${errorMessage(failure)} A shared note may already be saved; retry uses the same identity.`); }
    finally { form.setBusy(false); }
  }
  const result = job?.assistance_output;
  return <section className="ws-assistance" aria-label="Grounded assistance · local simulation">
    <h2>{context.mode === "research" ? "Investigate with selected evidence" : "Understand this paper"}</h2>
    <p className="workspace-version-notice">Local simulation · provider execution disabled · $0. These extractive fixtures exercise the pipeline; semantic support, checker reliability and human usefulness are unmeasured.</p>
    <Message>{notice || form.notice || taskForm.notice}</Message>
    <button type="button" disabled={form.busy} onClick={() => { setNotice(""); setAttempt(n => n + 1); }}>Reload assistance context</button>
    {!loaded && notice && <button type="button" onClick={() => { setNotice(""); setAttempt(n => n + 1); }}>Retry loading assistance</button>}
    {context.mode === "research" && <p>{project ? <>Research question: <strong>{project.data.question}</strong></> : !loaded ? notice ? "Research project context is unavailable. Retry before preparing an answer." : "Loading research project context…" : "Select a Research project before preparing an answer."}</p>}
    <form id={form.surfaceId} className="workspace-controls" onSubmit={event => { event.preventDefault(); void prepare(); }}>
      <div id={taskForm.surfaceId}><AssistanceTaskContext values={taskForm.values} research={context.mode === "research"} busy={form.busy} change={(key, value) => { taskForm.change(key, value); setPreview(null); }} /></div>
      <label>Explanation depth<select disabled={form.busy} value={form.values.depth} onChange={e => change("depth", e.target.value)}><option value="overview">Conceptual overview</option><option value="technical">Technical details</option></select></label>
      <label>Background to include explicitly<textarea maxLength={1000} rows={2} readOnly={form.busy} value={form.values.background} onChange={e => change("background", e.target.value)} /></label>
      <p className="daily-muted">Private notes, reading history and saved preferences are excluded. Only background and application context entered here and the disclosed project question, scope and constraints enter the request.</p>
      <label>Dive direction<select disabled={form.busy} value={form.values.direction} onChange={e => change("direction", e.target.value)}>{["overview", "method", "assumptions", "implementation"].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Follow-up question<textarea rows={2} maxLength={1000} readOnly={form.busy} value={form.values.follow_up} onChange={e => change("follow_up", e.target.value)} /></label>
      <fieldset disabled={form.busy}><legend>Select retained evidence · maximum eight units</legend>
        {selected.some(id => !units.some(unit => unit.id === id)) && <p className="workspace-version-notice">Some selected passages are unavailable. Explicitly discard or reselect; no newer source version was substituted.</p>}
        {!loaded && !notice && <p aria-busy="true">Loading retained evidence…</p>}
        {loaded && !units.length && <p>No coherent retained passages are available. Manual reading remains available; no source is fabricated.</p>}
        {units.map(unit => <details className="ws-record-details" data-assistance-unit={unit.id} key={unit.id}><summary>{unit.title} · {unit.reference.scope}{unit.reference.page ? ` · page ${unit.reference.page}` : ""}</summary>
          <label><input type="checkbox" checked={selected.includes(unit.id)} onChange={e => change("units", JSON.stringify(e.target.checked ? [...selected, unit.id] : selected.filter(id => id !== unit.id)))} />Include this evidence unit</label>
          <blockquote>{unit.reference.quote}</blockquote><p>{unit.complete ? "Retained text coverage recorded as complete; extraction quality remains a separate question." : "Selected abstract or excerpt; omitted material may change interpretation."}</p>
          {unit.warnings.map(warning => <p key={warning}>{warning}</p>)}<details><summary>Exact evidence identity</summary><pre tabIndex={0}>{JSON.stringify(unit.reference, null, 2)}</pre></details>
        </details>)}
      </fieldset>
      <div className="workspace-toolbar"><button className="daily-button" disabled={form.busy || !selected.length || context.mode === "research" && !project}>Preview assistance request</button><button type="button" className="daily-secondary" disabled={form.busy} onClick={() => { form.clear(true); taskForm.clear(true); setPreview(null); }}>Discard assistance edits</button></div>
      {!form.storage && <p>Draft recovery is unavailable. Copy your edits before reloading.</p>}
      {!taskForm.storage && <p>Task context recovery is unavailable. Copy your application details before reloading.</p>}
    </form>
    {preview && <section aria-label="Sealed assistance request"><h3>Review the exact context</h3><p>{context.mode === "learn" ? "Learning explanation and guided dive" : "Project answer and source comparison"} · {preview.request.assistance.depth} · {selected.length} selected units</p><p>{preview.request.capacity.basis}. Provider token counts: unmeasured. Four calls reserve draft, mandatory check, one repair and mandatory recheck.</p><details><summary>Exact candidate request · selected evidence only</summary><pre tabIndex={0}>{JSON.stringify(preview.request.candidate_initial_wire, null, 2)}</pre></details><details><summary>Local integrity bindings, schemas and limits</summary><p>This local record retains parent spans for integrity. Only the candidate request above is outbound context; parent text and navigation history are excluded.</p><pre tabIndex={0}>{JSON.stringify(preview.request, null, 2)}</pre></details><button className="daily-button" type="button" disabled={form.busy} onClick={() => void run()}>Run local assistance simulation · $0</button></section>}
    {job && <section aria-label="Durable assistance job"><h3>{running ? "Running local pipeline" : stateLabel[job.state]}</h3><p>{stateLabel[job.state]} · {job.usage.used_calls}/4 simulated calls · provider spend $0</p>
      {job.request.project_context && <p>Question at request time: <strong>{job.request.project_context.question}</strong>{project && project.revision !== job.request.project_context.revision && " · The project has changed; this result retains the earlier question."}</p>}
      <div className="workspace-toolbar"><button type="button" onClick={() => void inspect()}>Inspect stored status</button><button type="button" disabled={terminal.has(job.state)} onClick={() => void inspect("cancel")}>Cancel simulation</button><button type="button" disabled={form.busy || terminal.has(job.state)} onClick={() => void run(job)}>Continue saved simulation</button><button type="button" disabled={form.busy} onClick={() => void inspect("recover")}>Recover interrupted status</button></div>
      {job.error && <p className="workspace-version-notice">{job.error}. Failed or interrupted output is not an accepted result.</p>}
      <details><summary>Stage receipts and split accounting</summary><pre tabIndex={0}>{JSON.stringify({ steps: job.steps, usage: job.usage, quality: job.quality, wire_records: job.wire_records }, null, 2)}</pre></details>
      {result && <section aria-label="Simulated assistance result"><h3>Selected-source reading guide · simulated</h3><p>Factual acceptance and checker qualification remain disabled. A machine-supported quotation does not establish the scientific truth of its content.</p>
        <AssistanceDisposition output={result} />
        <RequestCoverage output={result} prefix={job.id} />
        {result.abstention && <p>Abstention: {result.abstention}</p>}
        {result.claims.map(claim => <article key={claim.claim_id} id={`${job.id}-${claim.claim_id}`}><h4>Retained claim {claim.claim_id}</h4><p>{claim.text}</p><p className="workspace-version-notice">Simulated checker: {job.quality.claim_checks?.find(check => check.claim_id === claim.claim_id)?.decision ?? "unscored"}. Whole-claim support remains unqualified.</p>{claim.handles.map(handle => { const ref = job.request.units[handle]; if (!ref) return null; const anchor = passageAnchor(ref); return <div key={handle}><blockquote>{ref.quote}</blockquote><p>{ref.scope} · pinned version · {ref.page ? `page ${ref.page}` : "abstract text"}</p>{ref.work_id === workId && ref.version_id === versionId ? <button type="button" onClick={() => onSource(anchor)}>Open exact cited passage</button> : <Link href={contextHref(readerHref({ work_id: ref.work_id }, ref.version_id, anchor, undefined, returnTo), context)}>Open exact cited passage</Link>}<details><summary>Citation identity and offsets</summary><pre tabIndex={0}>{JSON.stringify(ref, null, 2)}</pre></details></div>; })}</article>)}
        {result.background_claims ? <ScoredSections output={result} prefix={job.id} /> : <>
        <h4>Background explanation · unverified simulation</h4><p>{result.background}</p>
        {result.comparison && <><h4>Comparison interpretation · unverified simulation</h4><p>{result.comparison}</p><p>Separate evidence basis: {(result.comparison_basis ?? []).join(", ")}. Agreements, disagreements and compatible evaluation conditions require semantic review.</p></>}
        <h4>Assumptions and missing evidence</h4>{[...(result.assumptions ?? []), ...result.gaps].map((text, i) => <p key={i}>{text}</p>)}
        </>}
        <h4>Choose the next question</h4>{result.questions.map(question => <button key={question} type="button" disabled={form.busy} onClick={() => { change("follow_up", question); change("units", JSON.stringify(job.request.assistance.unit_ids)); }}>{question}</button>)}
        <h4>{result.response_disposition === "full_abstention" ? "Missing details · next action" : "Proposed experiment · not a finding"}</h4><p>{result.proposal}</p>
        <div className="workspace-toolbar"><button type="button" disabled={form.busy} onClick={() => void save("thread")}>Save simulation to a learning thread</button>{job.request.assistance.project_id && <button type="button" disabled={form.busy} onClick={() => void save("project")}>Save simulation to project notes</button>}</div>
        {savedThread && <Link href={contextHref(`/workspace/threads/${savedThread}?mode=learn&thread=${savedThread}`, { ...context, mode: "learn", thread: savedThread, explicit: true })}>Open saved learning thread</Link>}
      </section>}
    </section>}
    {jobs.length > 0 && <details><summary>Resume saved assistance for this version</summary>{jobs.map(value => <p key={value.id}><button type="button" disabled={form.busy || form.dirty} onClick={() => { publish(value); const url = new URL(location.href); url.searchParams.set("assistance", value.id); history.replaceState(history.state, "", url); }}>{value.request.assistance.mode} · {value.request.assistance.direction} · {stateLabel[value.state]}</button></p>)}</details>}
  </section>;
}
