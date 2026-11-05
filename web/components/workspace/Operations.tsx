"use client";
import { useId, useRef, useState } from "react";
import { displayDate, errorMessage, requestId, workspaceRequest, type ScheduleData, type WorkspaceState } from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { setQueryParam, useQueryParam } from "@/lib/workspace/urlState";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";
import { LoadingState, Message, ServiceNotice } from "./Common";
import { ControlBar, SidebarSection, StageHeaderSlot } from "./Slots";
import { useSyntheticPreview } from "./PreviewContext";

type ScheduleDraft = { revision: number; data: ScheduleData };

export function LiveOperations() {
  const { state, setState, error, reload } = useWorkspace();
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<ScheduleDraft | null>(null);
  const attempts = useRef(new Map<string, string>());
  const formId = useId();
  const focusId = useQueryParam("focus");
  const synthetic = useSyntheticPreview();
  if (!state) return <LoadingState error={error} retry={() => void reload()} />;
  const loadedState = state;
  const schedule = draft?.data ?? loadedState.schedule;
  const sources = state.sources;
  const focused = sources.find((source) => source.source_id === focusId) ?? sources[0];
  const index = sources.findIndex((source) => source.source_id === focused?.source_id);
  const dirty = !!draft && (draft.data.timezone !== state.schedule.timezone || draft.data.local_time !== state.schedule.local_time);
  function choose(id: string) {
    if (busy) return;
    setQueryParam("focus", id);
    if (document.querySelector('.workspace-app [role="dialog"][aria-modal="true"]')) dispatchWorkspaceCommand("escape");
  }
  function edit(change: Partial<ScheduleData>) {
    setDraft({ revision: draft?.revision ?? loadedState.schedule.revision, data: { enabled: false, timezone: schedule.timezone, local_time: schedule.local_time, ...change } });
  }
  async function check(sourceId?: string) {
    if (busy || synthetic) return;
    setBusy(true);
    setNotice(sourceId ? "Checking only this approved source. No model is running." : "Checking a bounded set of public source metadata. No model is running.");
    try {
      const next = await workspaceRequest<WorkspaceState>("refresh", { source_ids: sourceId ? [sourceId] : [] });
      setState(next);
      setNotice("Source check finished. Inspect its receipt for coverage, limits and any failure.");
    } catch (failure) { setNotice(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const input = { revision: draft?.revision ?? loadedState.schedule.revision,
      data: { enabled: false, timezone: schedule.timezone, local_time: schedule.local_time } };
    const fingerprint = JSON.stringify(input), id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id); setBusy(true);
    try {
      const saved = await workspaceRequest<WorkspaceState["schedule"]>("schedule", { ...input, request_id: id });
      setState({ ...loadedState, schedule: saved });
      setDraft(null);
      setNotice("Schedule preferences saved. Recurring checks remain disabled until you confirm the time.");
    } catch (failure) { setNotice(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  return <div className="ws-operations">
    <StageHeaderSlot position={focused ? { n: index + 1, N: sources.length } : undefined} />
    <div className="daily-page-meta"><span className="daily-eyebrow">Sources &amp; checks · local operations</span><span className="daily-muted">No external delivery</span></div>
    <div className="daily-intro"><div><h1>Know what was checked.<br /><em>And what wasn’t.</em></h1>
      <p>{synthetic ? "Synthetic sample receipts, durable task state and local schedule preferences." : "Actual source receipts, durable task state and local schedule preferences."}</p></div></div>
    <ServiceNotice error={error} />
    <SidebarSection label="Source queue"><h2>Sources</h2><ol className="ws-queue ws-source-queue" aria-label="Source checks queue">
      {sources.map((source, i) => <li key={source.source_id}><button type="button" className="ws-queue-row ws-source-row" disabled={busy}
        aria-current={source.source_id === focused?.source_id ? "true" : undefined}
        aria-label={`Show source ${i + 1} of ${sources.length}: ${source.name} · ${source.status.replaceAll("_", " ")}`} onClick={() => choose(source.source_id)}>
        <span className="ws-source-number" aria-hidden="true">{i + 1}</span><span className="ws-queue-text"><span>{source.name}</span><span>{source.status.replaceAll("_", " ")}</span></span>
      </button></li>)}
    </ol><button type="button" className="daily-secondary" disabled={busy || synthetic} onClick={() => void check()}>Check sources now</button>
      {synthetic && <p className="daily-muted">Live source checks are disabled in this synthetic design preview.</p>}
    </SidebarSection>
    <section aria-labelledby="source-health" className="ws-source-detail">
      <div className="daily-section-heading"><h2 id="source-health">Source health and coverage</h2><span>{sources.length} configured sources</span></div>
      {focused ? <article className="workspace-source"><header><h2>{focused.name}</h2><span className="daily-eyebrow">{focused.status.replaceAll("_", " ")}</span></header>
        <dl><dt>Last success</dt><dd>{focused.last_success_at ? displayDate(focused.last_success_at) : "No successful check recorded"}</dd>
          <dt>Scope</dt><dd>{synthetic ? "Synthetic sample receipt; it does not establish source coverage." : "Bounded public metadata; at most 25 items per check, with a seven-day default candidate window."}</dd></dl>
        <details><summary className="daily-link">Inspect this check’s receipt</summary><pre className="workspace-receipt" tabIndex={0} role="region" aria-label={`${focused.name} check receipt`}>{JSON.stringify(focused.receipt, null, 2)}</pre></details>
      </article> : <p>No sources are configured.</p>}
    </section>
    <section className="workspace-form-stack workspace-import ws-schedule" aria-labelledby="schedule-title">
      <span className="daily-eyebrow">Local schedule · awaiting your time</span><h2 id="schedule-title">A regular check, when you choose.</h2>
      <p className="daily-muted">Your computer must be running. After a missed window, the worker prepares one bounded catch-up edition rather than claiming delivery while it was asleep. No email, push, SMS or chat destination is enabled.</p>
      <div className="workspace-alert"><strong>{state.schedule.enabled ? "A recurring schedule is enabled" : "Recurring schedule disabled"}</strong>
        <p>Next check: {state.schedule.next_check ? displayDate(state.schedule.next_check) : "None scheduled"}</p></div>
      <form id={formId} onSubmit={(event) => void save(event)}>
        <label>IANA timezone<input value={schedule.timezone} disabled={busy} onChange={(event) => edit({ timezone: event.target.value })} placeholder="America/Los_Angeles" required /></label>
        <label>Proposed local check time<input type="time" value={schedule.local_time} disabled={busy} onChange={(event) => edit({ local_time: event.target.value })} required /></label>
      </form>
      {dirty && <p className="daily-muted">Unsaved schedule preferences.</p>}
    </section>
    <section className="workspace-import" aria-labelledby="queued-work"><div className="daily-section-heading"><h2 id="queued-work">Durable local work</h2><span>{state.tasks.length} recorded tasks</span></div>
      {state.tasks.length === 0 ? <p className="daily-muted">No queued or recorded scheduled tasks. {synthetic ? "Source checks disabled in this synthetic preview." : "Manual source checks remain available."}</p> : state.tasks.map((task, i) => <article className="workspace-inline-note" key={String(task.id ?? i)}>
        <span className="daily-eyebrow">{String(task.kind ?? "metadata check")} · {String(task.status ?? task.state ?? "unknown")}</span><p>Due: {displayDate(typeof task.due_at === "string" ? task.due_at : null)}</p>
        {task.reason != null && <p>{String(task.reason)}</p>}<p className="workspace-note-context">Attempt {String(task.attempts ?? task.attempt ?? "not recorded")}</p></article>)}
    </section>
    <div className="daily-generation"><h3>Generation stays separate.</h3><p>Metadata checks do not construct model clients. Grounded summaries and deep dives remain blocked until a separate source-and-budget approval is recorded.</p></div>
    <ControlBar><div className="ws-operations-actions" aria-busy={busy}>
      <button type="button" className="daily-secondary" data-command="prev" aria-label="Previous source" disabled={busy || index <= 0} onClick={() => choose(sources[index - 1]!.source_id)}>Previous</button>
      <span className="ws-operations-position">{focused ? `${index + 1} / ${sources.length}` : "No source"}</span>
      <button type="button" className="daily-secondary" data-command="next" aria-label="Next source" disabled={busy || index < 0 || index >= sources.length - 1} onClick={() => choose(sources[index + 1]!.source_id)}>Next</button>
      {focused && <button type="button" className="daily-secondary" data-command="check-sources" disabled={busy || synthetic} onClick={() => void check(focused.source_id)}>Check {focused.name} now</button>}
      <button type="submit" form={formId} className="daily-button" disabled={busy}>{state.schedule.enabled ? "Pause schedule and save preferences" : "Save preferences · keep schedule disabled"}</button>
    </div><Message>{notice}</Message></ControlBar>
  </div>;
}
