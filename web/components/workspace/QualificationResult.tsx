"use client";

import { ScoredSections } from "./ScoredSections";

import Link from "next/link";
import { useEffect, useState } from "react";
import { contextHref, resumeContext, useProductContext } from "@/lib/workspace/productContext";
import { contextRequest, errorMessage, readerHref, workspaceRequest, type EntryRevision, type LearningThread, type ProjectDetail } from "@/lib/workspace/api";
import { passageAnchor, type AssistanceInput, type AssistanceOutput, type EvidenceReference } from "@/lib/workspace/assistanceTypes";
import { invalidateContextIndex } from "@/lib/workspace/useContextIndex";
import { Message } from "./Common";

export interface QualificationJob {
  id: string; state: string; case_id: string; packet_digest: string; simulated: boolean;
  assistance_output: AssistanceOutput | null; source_binding_intact: boolean;
  request: { assistance: AssistanceInput; units: Record<string, EvidenceReference>; project_context: { question: string; revision: number } | null };
  result: { grounding?: { assessments: { claim_id: string; decision: string | null; reason: string }[] } } | null;
  workflow_usd: string; checker_usd: string; unknown_usd: string;
  steps: unknown[]; contacts: unknown[];
}

/** Read-only, quarantined production-pipeline results. No dispatch API exists. */
export default function QualificationResult({ workId, versionId, returnTo, onSource }: {
  workId: string; versionId: string; returnTo: string; onSource: (anchor: string) => void;
}) {
  const context = useProductContext();
  const [jobs, setJobs] = useState<QualificationJob[]>([]), [job, setJob] = useState<QualificationJob | null>(null);
  const [loaded, setLoaded] = useState(false), [notice, setNotice] = useState(""), [attempt, setAttempt] = useState(0), [busy, setBusy] = useState(false);
  const [savedThread, setSavedThread] = useState<string | null>(null);
  useEffect(() => {
    const pending = new AbortController();
    workspaceRequest<QualificationJob[]>(`qualification/results?${new URLSearchParams({ work_id: workId, version_id: versionId })}`, undefined, pending.signal)
      .then(values => {
        if (pending.signal.aborted) return;
        setJobs(values); setLoaded(true);
        const requested = new URL(location.href).searchParams.get("qualification");
        setJob(values.find(value => value.id === requested) ?? null);
        if (requested && !values.some(value => value.id === requested)) setNotice("This result is unavailable for this source, version or principal. No substitute was selected.");
      }).catch(failure => { if (!pending.signal.aborted) setNotice(errorMessage(failure)); });
    return () => pending.abort();
  }, [workId, versionId, attempt]);
  function select(value: QualificationJob) {
    setJob(value);
    const url = new URL(location.href); url.searchParams.set("qualification", value.id);
    history.replaceState(history.state, "", url);
  }
  async function save(target: "thread" | "project") {
    if (!job?.assistance_output || !job.source_binding_intact || busy) return;
    const stored = job.request.assistance;
    const ref = Object.values(job.request.units).find(r => r.work_id === stored.work_id && r.version_id === stored.version_id);
    if (!ref) return;
    const origin = stored.origin ?? { ...resumeContext(context, returnTo), mode: stored.mode, project_id: stored.project_id };
    const body = [job.simulated ? "Offline simulated qualification result · not quality evidence." : "Quarantined experimental result · human review pending.", ...job.assistance_output.claims.map(c => `${c.claim_id}: ${c.text}`), "Proposed next action: " + job.assistance_output.proposal, "Qualification record: " + job.id].join("\n\n");
    setBusy(true);
    try {
      const entry = await contextRequest<EntryRevision>("/entries", { id: `qualification-${job.id}`, revision: 0, request_id: `save-${job.id}`, context: origin, data: { work_id: stored.work_id, version_id: stored.version_id, kind: "note", body, anchor: passageAnchor(ref) } });
      if (target === "project") {
        if (!stored.project_id) throw new Error("This result has no originating project.");
        const project = await contextRequest<ProjectDetail>(`/projects/${stored.project_id}`);
        if (!project.entries.some(link => link.entry_id === entry.id && link.entry_revision === entry.revision)) await contextRequest(`/projects/${stored.project_id}/entries`, { revision: project.revision, request_id: `link-${job.id}`, entry_id: entry.id, entry_revision: entry.revision });
      } else {
        const thread = await contextRequest<LearningThread>("/threads", { id: `thread-${job.id.slice(4, 36)}`, revision: 0, request_id: `thread-${job.id}`, data: { title: "Experimental guided reading", goal: stored.follow_up || "Inspect the retained evidence", prerequisite: "Resume quarantined result " + job.id, status: "active", origin, source: { work_id: ref.work_id, version_id: ref.version_id, anchor: passageAnchor(ref) }, entry: { entry_id: entry.id, entry_revision: entry.revision } } });
        setSavedThread(thread.id);
      }
      invalidateContextIndex(); setNotice("Experimental result saved with its exact source context. It remains unqualified.");
    } catch (failure) { setNotice(`${errorMessage(failure)} A note may already be saved; retry preserves the same identities.`); }
    finally { setBusy(false); }
  }
  const output = job?.assistance_output;
  return <section className="ws-assistance" aria-label="Quarantined qualification results">
    <h2>Experimental reading results</h2>
    <p className="workspace-version-notice">Quarantined · everyday generation disabled. Offline simulations do not qualify model quality, checker reliability or personal usefulness.</p>
    <Message>{notice}</Message>
    <button type="button" disabled={busy} onClick={() => { setLoaded(false); setNotice(""); setAttempt(n => n + 1); }}>Reload stored qualification results</button>
    {!loaded && !notice && <p aria-busy="true">Loading quarantined results…</p>}
    {loaded && !jobs.length && <p>No qualification results for this exact version. Opening this panel cannot generate one.</p>}
    <ul>{jobs.map(value => <li key={value.id}><button type="button" aria-pressed={job?.id === value.id} disabled={busy} onClick={() => select(value)}>{value.case_id} · {value.state} · {value.simulated ? "offline simulation" : "experimental provider result"}</button></li>)}</ul>
    {job && <section aria-label="Persisted qualification result">
      <h3>{job.case_id} · {job.state}</h3>
      <p>{job.simulated ? "Simulated transport and counts · zero provider contacts · actual new spend $0." : "Experimental provider output; inspect metered receipts below."}</p>
      {job.request.project_context && <p>Sealed research question: <strong>{job.request.project_context.question}</strong></p>}
      {!job.source_binding_intact && <p role="alert">Retained evidence changed. Claims are hidden; no newer source was substituted.</p>}
      {!output && <p>No completed content is available. Failed, cancelled or uncertain work is not an accepted summary and cannot be replayed from Reader.</p>}
      {output && <>
        {output.abstention && <p>Abstention: {output.abstention}</p>}
        {output.claims.map(claim => <article key={claim.claim_id} id={`${job.id}-${claim.claim_id}`}><h4>Claim {claim.claim_id}</h4><p>{claim.text}</p><p>Machine checker: {job.result?.grounding?.assessments.find(c => c.claim_id === claim.claim_id)?.decision ?? "unscored"}. Human support: unmeasured.</p>{claim.handles.map(handle => {
          const ref = job.request.units[handle]; if (!ref) return null;
          const anchor = passageAnchor(ref);
          return <div key={handle}><blockquote>{ref.quote}</blockquote><p>{ref.scope} · exact source version{ref.page ? ` · page ${ref.page}` : ""}</p>{ref.work_id === workId && ref.version_id === versionId ? <button type="button" onClick={() => onSource(anchor)}>Open qualification passage</button> : <Link href={contextHref(readerHref({ work_id: ref.work_id }, ref.version_id, anchor, undefined, returnTo), context)}>Open qualification passage</Link>}<details><summary>Exact citation identity</summary><pre tabIndex={0}>{JSON.stringify(ref, null, 2)}</pre></details></div>;
        })}</article>)}
        {output.background_claims ? <ScoredSections output={output} prefix={job.id} /> : <>
        <h4>Background · unverified explanation</h4><p>{output.background}</p>
        {output.comparison && <><h4>Comparison · independently cited basis</h4><p>{output.comparison}</p><p>Basis: {(output.comparison_basis ?? []).join(", ")}. Compatible conditions and omissions require human review.</p></>}
        <h4>Assumptions and missing evidence</h4><ul>{[...(output.assumptions ?? []), ...output.gaps].map((text, i) => <li key={i}>{text}</li>)}</ul>
        </>}
        <h4>Follow-up questions</h4><ul>{output.questions.map(text => <li key={text}>{text}</li>)}</ul>
        <h4>Proposed experiment · not a finding</h4><p>{output.proposal}</p>
        <button type="button" disabled={busy} onClick={() => void save("thread")}>Save experimental learning thread</button>
        {savedThread && <Link href={contextHref(`/workspace/threads/${savedThread}`, { ...context, mode: job.request.assistance.mode, project: job.request.assistance.project_id })}>Open experimental learning thread →</Link>}
        {job.request.assistance.project_id && <button type="button" disabled={busy} onClick={() => void save("project")}>Link experimental result to project</button>}
      </>}
      <details><summary>Request, exact packet and split accounting</summary><pre tabIndex={0}>{JSON.stringify({ packet_digest: job.packet_digest, request: job.request, workflow_usd: job.workflow_usd, checker_usd: job.checker_usd, unknown_usd: job.unknown_usd, steps: job.steps, contacts: job.contacts }, null, 2)}</pre></details>
    </section>}
  </section>;
}
